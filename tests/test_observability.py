from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api_schemas import ClientErrorReportRequest
from app.observability import JobStageMetrics, JsonLogFormatter, RequestMetrics, RequestObservabilityMiddleware, client_error_log_fields, process_resource_snapshot


def test_json_log_formatter_keeps_structured_fields() -> None:
    record = logging.LogRecord("cliptalk", logging.INFO, __file__, 1, "request", (), None)
    record.structured = {"requestId": "req-1", "durationMilliseconds": 12.5}
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["message"] == "request"
    assert payload["requestId"] == "req-1"
    assert payload["durationMilliseconds"] == 12.5


def test_request_metrics_tracks_active_status_and_duration() -> None:
    metrics = RequestMetrics()
    metrics.begin()
    assert metrics.snapshot()["requestsActive"] == 1
    metrics.finish(method="GET", status_code=200, duration_ms=25)
    snapshot = metrics.snapshot()
    assert snapshot["requestsTotal"] == 1
    assert snapshot["requestsActive"] == 0
    assert snapshot["statusCounts"] == {"200": 1}
    assert snapshot["methodCounts"] == {"GET": 1}
    assert snapshot["averageDurationMilliseconds"] == 25


def test_job_stage_metrics_aggregate_without_job_content(monkeypatch) -> None:
    clock = iter([1.0, 1.4, 2.0])
    monkeypatch.setattr("app.observability.time.perf_counter", lambda: next(clock))
    metrics = JobStageMetrics()
    metrics.transition("job-secret-id", "speech_recognition")
    metrics.transition("job-secret-id", "coarse_vlm")
    metrics.finish("job-secret-id")
    snapshot = metrics.snapshot()
    assert snapshot["activeJobs"] == 0
    assert snapshot["stages"]["speech_recognition"] == {
        "samples": 1,
        "averageDurationMilliseconds": 400.0,
        "maximumDurationMilliseconds": 400.0,
    }
    assert "job-secret-id" not in json.dumps(snapshot)


def test_process_resource_snapshot_reports_memory_and_data_disk(tmp_path) -> None:
    snapshot = process_resource_snapshot(str(tmp_path))
    assert snapshot["peakResidentMemoryBytes"] > 0
    assert snapshot["dataDiskFreeBytes"] > 0


def test_observability_middleware_returns_request_id() -> None:
    metrics = RequestMetrics()
    logger = logging.getLogger("cliptalk-test-observability")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    app = FastAPI()
    app.add_middleware(RequestObservabilityMiddleware, metrics=metrics, logger=logger)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    response = TestClient(app).get("/ok", headers={"X-Request-ID": "browser:test-1"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "browser:test-1"
    assert metrics.snapshot()["requestsTotal"] == 1


def test_client_error_fields_remove_queries_and_bound_untrusted_text() -> None:
    report = ClientErrorReportRequest(
        kind="unhandledrejection",
        name="ReferenceError",
        message="subtitleDraftId is not defined" + "x" * 900,
        stack="\n".join(f"frame-{index}" for index in range(30)),
        pagePath="https://example.test/workspace?token=secret#fragment",
        scriptPath="https://example.test/static/app.js?v=secret",
        jobId="job_123",
    )
    fields = client_error_log_fields(report)
    assert fields["pagePath"] == "/workspace"
    assert fields["scriptPath"] == "/static/app.js"
    assert "secret" not in json.dumps(fields)
    assert len(fields["clientErrorMessage"]) == 700
    assert len(fields["clientErrorStack"].splitlines()) == 16
