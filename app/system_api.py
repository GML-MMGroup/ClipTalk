from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_system_router(
    *,
    health: Callable[..., Any],
    runtime_metrics: Callable[..., Any],
) -> APIRouter:
    """Own operational health and metrics endpoints."""
    router = APIRouter(prefix="/api", tags=["system"])
    router.add_api_route("/health", health, methods=["GET"])
    router.add_api_route("/metrics", runtime_metrics, methods=["GET"])
    return router
