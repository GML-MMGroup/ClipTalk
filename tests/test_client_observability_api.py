from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api_schemas import ClientErrorReportRequest
from app.client_observability_api import build_client_observability_router


def test_client_error_router_accepts_the_bounded_report_contract() -> None:
    received = []

    def report_client_error(report: ClientErrorReportRequest):
        received.append(report)

    app = FastAPI()
    app.include_router(build_client_observability_router(report_client_error=report_client_error))
    response = TestClient(app).post("/api/client-errors", json={
        "kind": "error",
        "name": "ReferenceError",
        "message": "missingName is not defined",
        "pagePath": "/",
    })
    assert response.status_code == 204
    assert received[0].name == "ReferenceError"
