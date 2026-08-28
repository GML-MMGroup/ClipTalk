from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_client_observability_router(*, report_client_error: Callable[..., Any]) -> APIRouter:
    """Expose the intentionally small browser-runtime reporting contract."""
    router = APIRouter(prefix="/api", tags=["observability"])
    router.add_api_route("/client-errors", report_client_error, methods=["POST"], status_code=204)
    return router
