from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_kept_router(
    *,
    list_kept_outputs: Callable[..., Any],
    kept_media: Callable[..., Any],
    delete_kept_output: Callable[..., Any],
) -> APIRouter:
    """Own the durable kept-output collection and media endpoints."""
    router = APIRouter(prefix="/api/kept", tags=["kept"])
    router.add_api_route("", list_kept_outputs, methods=["GET"])
    router.add_api_route("/{job_id}/{filename}", kept_media, methods=["GET"])
    router.add_api_route("/{job_id}/{filename}", delete_kept_output, methods=["DELETE"])
    return router
