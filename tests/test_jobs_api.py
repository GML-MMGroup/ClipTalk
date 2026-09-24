from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI

from app import main
from app.api_schemas import ProjectSettingsRequest
from app.jobs_api import build_jobs_router


def test_jobs_router_owns_core_lifecycle_routes() -> None:
    def handler(job_id: str = "", revision: int | None = None) -> dict:
        return {"jobId": job_id, "revision": revision}

    router = build_jobs_router(
        list_jobs=handler,
        create_job=handler,
        get_job=handler,
        get_job_status=handler,
        update_job_project_settings=handler,
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
        ("/api/jobs/{job_id}/project-settings", "PATCH"),
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


def test_project_output_aspect_is_persisted_without_changing_outputs() -> None:
    job_id = "job_project_settings_test"
    job = main.new_job_record(
        job_id=job_id,
        source=Path("/tmp/project-settings-source.mp4"),
        filename="source.mp4",
        size=1024,
        count="auto",
        target_seconds="auto",
        theme="",
    )
    job["status"] = "ready"
    job["projectSettings"]["customPreference"] = "keep"
    original_outputs = list(job["outputs"])

    with patch.dict(main.jobs, {job_id: job}, clear=False), patch.object(main, "save_job") as save:
        response = main.update_job_project_settings(
            job_id, ProjectSettingsRequest(outputAspect="9:16"),
        )
        planning_context = main.agent_planning_context(job_id)

    assert response["job"]["projectSettings"] == {
        "outputAspect": "9:16", "outputFit": "blur", "customPreference": "keep",
    }
    assert job["outputs"] == original_outputs
    assert planning_context["delivery"]["outputAspect"] == "9:16"
    save.assert_called_once_with(job)


def test_jobs_router_exposes_only_current_activation_route() -> None:
    def handler(*_args, **_kwargs) -> dict:
        return {}

    router = build_jobs_router(
        list_jobs=handler, create_job=handler, get_job=handler,
        get_job_status=handler, update_job_project_settings=handler,
        cancel_job=handler, finalize_one_off_job=handler,
        create_job_delete_intent=handler, delete_job=handler,
        activate_agent_draft=handler,
    )
    assert any(route.path == "/api/jobs/{job_id}/activate" for route in router.routes)
    assert not any("legacy-activate" in route.path for route in router.routes)
