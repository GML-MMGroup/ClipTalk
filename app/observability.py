from __future__ import annotations

import json
import logging
import os
import re
import resource
import shutil
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


def _safe_client_text(value: Any, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value or ""))
    return text[:limit]


def _safe_client_path(value: Any, limit: int = 500) -> str:
    text = _safe_client_text(value, limit * 2)
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    path = parsed.path or (text if text.startswith("/") else "")
    return _safe_client_text(path, limit)


def client_error_log_fields(report: Any) -> dict[str, Any]:
    """Return a bounded payload without query strings, fragments, or browser input."""
    data = report.model_dump() if hasattr(report, "model_dump") else dict(report or {})
    stack_lines = _safe_client_text(data.get("stack"), 4000).splitlines()[:16]
    return {
        "clientErrorKind": _safe_client_text(data.get("kind") or "error", 32),
        "clientErrorName": _safe_client_text(data.get("name") or "Error", 80),
        "clientErrorMessage": _safe_client_text(data.get("message"), 700),
        "clientErrorStack": "\n".join(stack_lines),
        "pagePath": _safe_client_path(data.get("pagePath")),
        "scriptPath": _safe_client_path(data.get("scriptPath")),
        "line": data.get("line"),
        "column": data.get("column"),
        "jobId": _safe_client_text(data.get("jobId"), 96),
        "build": _safe_client_text(data.get("build"), 120),
    }


def process_resource_snapshot(data_root: str) -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # Linux reports KiB; ClipTalk's supported server and container targets are
    # Linux. Keep the field explicit and stable for local performance audits.
    peak_resident_bytes = max(0, int(usage.ru_maxrss)) * 1024
    disk = shutil.disk_usage(data_root)
    return {
        "peakResidentMemoryBytes": peak_resident_bytes,
        "dataDiskUsedBytes": max(0, int(disk.used)),
        "dataDiskFreeBytes": max(0, int(disk.free)),
    }


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict):
            payload.update(structured)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_json_logging() -> logging.Logger:
    logger = logging.getLogger("cliptalk")
    level_name = os.environ.get("HIGHLIGHT_LOG_LEVEL", "INFO").strip().upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._total = 0
        self._active = 0
        self._duration_ms = 0.0
        self._statuses: Counter[str] = Counter()
        self._methods: Counter[str] = Counter()

    def begin(self) -> None:
        with self._lock:
            self._active += 1

    def finish(self, *, method: str, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            self._total += 1
            self._duration_ms += max(0.0, duration_ms)
            self._statuses[str(status_code)] += 1
            self._methods[str(method).upper()] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = self._total
            return {
                "uptimeSeconds": round(max(0.0, time.time() - self._started_at), 1),
                "requestsTotal": total,
                "requestsActive": self._active,
                "averageDurationMilliseconds": round(self._duration_ms / max(1, total), 2),
                "statusCounts": dict(sorted(self._statuses.items())),
                "methodCounts": dict(sorted(self._methods.items())),
            }


class JobStageMetrics:
    """Aggregate stage throughput without retaining filenames or instructions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, tuple[str, float]] = {}
        self._samples: Counter[str] = Counter()
        self._duration_ms: Counter[str] = Counter()
        self._maximum_ms: Counter[str] = Counter()

    def transition(self, job_id: str, stage: str) -> None:
        now = time.perf_counter()
        normalized_stage = str(stage or "unknown")
        with self._lock:
            previous = self._active.get(str(job_id))
            if previous and previous[0] != normalized_stage:
                elapsed_ms = max(0.0, (now - previous[1]) * 1000)
                self._samples[previous[0]] += 1
                self._duration_ms[previous[0]] += elapsed_ms
                self._maximum_ms[previous[0]] = max(self._maximum_ms[previous[0]], elapsed_ms)
            if previous is None or previous[0] != normalized_stage:
                self._active[str(job_id)] = (normalized_stage, now)

    def finish(self, job_id: str) -> None:
        now = time.perf_counter()
        with self._lock:
            previous = self._active.pop(str(job_id), None)
            if not previous:
                return
            elapsed_ms = max(0.0, (now - previous[1]) * 1000)
            self._samples[previous[0]] += 1
            self._duration_ms[previous[0]] += elapsed_ms
            self._maximum_ms[previous[0]] = max(self._maximum_ms[previous[0]], elapsed_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            stages = {}
            for stage, samples in sorted(self._samples.items()):
                stages[stage] = {
                    "samples": samples,
                    "averageDurationMilliseconds": round(self._duration_ms[stage] / max(1, samples), 2),
                    "maximumDurationMilliseconds": round(self._maximum_ms[stage], 2),
                }
            return {"activeJobs": len(self._active), "stages": stages}


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, metrics: RequestMetrics, logger: logging.Logger) -> None:
        super().__init__(app)
        self.metrics = metrics
        self.logger = logger

    async def dispatch(self, request: Request, call_next):
        provided_id = request.headers.get("X-Request-ID", "")
        request_id = provided_id if REQUEST_ID_PATTERN.fullmatch(provided_id) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        self.metrics.begin()
        try:
            response = await call_next(request)
            status_code = int(response.status_code)
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            self.logger.exception("http_request_failed", extra={"structured": {
                "requestId": request_id,
                "method": request.method,
                "path": request.url.path,
            }})
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            self.metrics.finish(
                method=request.method,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            self.logger.info("http_request", extra={"structured": {
                "requestId": request_id,
                "method": request.method,
                "path": request.url.path,
                "statusCode": status_code,
                "durationMilliseconds": round(duration_ms, 2),
                "client": request.client.host if request.client else "unknown",
            }})
