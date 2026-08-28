from __future__ import annotations

from fastapi import FastAPI

from app.jobs_api import build_jobs_router


def test_jobs_router_owns_core_lifecycle_routes() -> None:
    def handler(job_id: str = "", revision: int | None = None) -> dict:
        return {"jobId": job_id, "revision": revision}

    router = build_jobs_router(
        list_jobs=handler,
        create_job=handler,
        get_job=handler,
        get_job_status=handler,
        cancel_job=handler,
        finalize_one_off_job=handler,
        create_job_delete_intent=handler,
        delete_job=handler,
    )
    routes = {(route.path, next(iter(route.methods))): route for route in router.routes}
    assert set(routes) == {
        ("/api/jobs", "GET"),
        ("/api/jobs", "POST"),
        ("/api/jobs/{job_id}", "GET"),
        ("/api/jobs/{job_id}/status", "GET"),
        ("/api/jobs/{job_id}/cancel", "POST"),
        ("/api/jobs/{job_id}/finalize-one-off", "POST"),
        ("/api/jobs/{job_id}/delete-intent", "POST"),
        ("/api/jobs/{job_id}", "DELETE"),
    }
    assert routes[("/api/jobs", "POST")].status_code == 202

    app = FastAPI()
    app.include_router(router)
    schemas = app.openapi()["components"]["schemas"]
    assert "JobDocumentResponse" in schemas
    assert "JobRequestResponse" in schemas
    assert "OutputVersionResponse" in schemas
