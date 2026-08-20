from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


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
