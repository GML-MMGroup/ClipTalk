from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter


OUTPUT_ROUTES = (
    ("render_auto_edit_plan", "/api/jobs/{job_id}/auto-plans/{plan_id}/render", "POST", 202),
    ("finalize_preview_output_version", "/api/jobs/{job_id}/output-versions/{version_id}/finalize", "POST", 202),
    ("confirm_job_candidates", "/api/jobs/{job_id}/confirm", "POST", 202),
    ("reopen_job_for_editing", "/api/jobs/{job_id}/reedit", "POST", 200),
    ("cancel_job_reediting", "/api/jobs/{job_id}/reedit/cancel", "POST", 200),
    ("adjust_job_output", "/api/jobs/{job_id}/outputs/{filename}/adjust", "POST", 200),
    ("keep_job_output", "/api/jobs/{job_id}/outputs/{filename}/keep", "POST", 200),
    ("activate_job_output_version", "/api/jobs/{job_id}/output-versions/{version_id}/activate", "POST", 200),
    ("delete_job_output_version", "/api/jobs/{job_id}/output-versions/{version_id}", "DELETE", 200),
)


def build_outputs_router(handlers: Mapping[str, Callable[..., Any]]) -> APIRouter:
    """Own output rendering, versioning and re-edit lifecycle routes."""
    missing = [name for name, _path, _method, _status in OUTPUT_ROUTES if name not in handlers]
    if missing:
        raise ValueError(f"缺少成片路由处理器：{', '.join(missing)}")
    router = APIRouter(tags=["outputs"])
    for name, path, method, status_code in OUTPUT_ROUTES:
        router.add_api_route(path, handlers[name], methods=[method], status_code=status_code)
    return router
