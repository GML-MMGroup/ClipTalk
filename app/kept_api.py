from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_kept_router(
    *,
    list_kept_outputs: Callable[..., Any],
    kept_media: Callable[..., Any],
    delete_kept_output: Callable[..., Any],
    kept_cover: Callable[..., Any] | None = None,
    list_library_outputs: Callable[..., Any] | None = None,
) -> APIRouter:
    """Own the durable kept-output collection and media endpoints."""
    router = APIRouter(tags=["kept"])
    router.add_api_route("/api/kept", list_kept_outputs, methods=["GET"])
    router.add_api_route("/api/kept/{job_id}/{filename}", kept_media, methods=["GET"])
    if kept_cover is not None:
        router.add_api_route("/api/kept/{job_id}/{filename}/cover", kept_cover, methods=["GET"])
    router.add_api_route("/api/kept/{job_id}/{filename}", delete_kept_output, methods=["DELETE"])
    if list_library_outputs is not None:
        router.add_api_route("/api/library/outputs", list_library_outputs, methods=["GET"])
    return router
