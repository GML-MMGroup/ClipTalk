from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability import JsonLogFormatter, RequestMetrics, RequestObservabilityMiddleware


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
