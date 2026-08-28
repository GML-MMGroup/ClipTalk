from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_system_router(
    *,
    health: Callable[..., Any],
    runtime_metrics: Callable[..., Any],
    classify_workflow_intent: Callable[..., Any] | None = None,
) -> APIRouter:
    """Own operational health and metrics endpoints."""
    router = APIRouter(prefix="/api", tags=["system"])
    router.add_api_route("/health", health, methods=["GET"])
    router.add_api_route("/metrics", runtime_metrics, methods=["GET"])
    if classify_workflow_intent is not None:
        router.add_api_route("/workflow-intent/classify", classify_workflow_intent, methods=["POST"])
    return router
