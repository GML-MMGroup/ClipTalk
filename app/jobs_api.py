from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_jobs_router(
    *,
    list_jobs: Callable[..., Any],
    create_job: Callable[..., Any],
    get_job: Callable[..., Any],
    get_job_status: Callable[..., Any],
    cancel_job: Callable[..., Any],
    finalize_one_off_job: Callable[..., Any],
    create_job_delete_intent: Callable[..., Any],
    delete_job: Callable[..., Any],
) -> APIRouter:
    """Own the core job collection and lifecycle URL surface."""
    router = APIRouter(prefix="/api/jobs", tags=["jobs"])
    router.add_api_route("", list_jobs, methods=["GET"])
    router.add_api_route("", create_job, methods=["POST"], status_code=202)
    router.add_api_route("/{job_id}", get_job, methods=["GET"])
    router.add_api_route("/{job_id}/status", get_job_status, methods=["GET"])
    router.add_api_route("/{job_id}/cancel", cancel_job, methods=["POST"])
    router.add_api_route("/{job_id}/finalize-one-off", finalize_one_off_job, methods=["POST"])
    router.add_api_route("/{job_id}/delete-intent", create_job_delete_intent, methods=["POST"])
    router.add_api_route("/{job_id}", delete_job, methods=["DELETE"])
    return router
