from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter


ANALYSIS_ROUTES = (
    ("confirm_job_brief", "/api/jobs/{job_id}/brief/confirm", "POST", 202),
    ("create_auto_edit_plans", "/api/jobs/{job_id}/auto-plans", "POST", 202),
    ("create_llm_order", "/api/jobs/{job_id}/llm-order", "POST", 202),
    ("derive_job", "/api/jobs/{job_id}/derive", "POST", 202),
    ("resolve_analysis_decision", "/api/jobs/{job_id}/analysis-decision", "POST", 202),
    ("reanalyze_cancelled_job", "/api/jobs/{job_id}/reanalyze", "POST", 202),
)


def build_analysis_router(handlers: Mapping[str, Callable[..., Any]]) -> APIRouter:
    """Own analysis decisions, planning and rerun lifecycle routes."""
    missing = [name for name, _path, _method, _status in ANALYSIS_ROUTES if name not in handlers]
    if missing:
        raise ValueError(f"缺少分析路由处理器：{', '.join(missing)}")
    router = APIRouter(tags=["analysis"])
    for name, path, method, status_code in ANALYSIS_ROUTES:
        router.add_api_route(path, handlers[name], methods=[method], status_code=status_code)
    return router
