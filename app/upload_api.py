from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_upload_router(*, create_upload: Callable[..., Any], append_upload: Callable[..., Any], get_upload: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/uploads", tags=["uploads"])
    router.add_api_route("", create_upload, methods=["POST"], status_code=201)
    router.add_api_route("/{session_id}", get_upload, methods=["GET"])
    router.add_api_route("/{session_id}", append_upload, methods=["PATCH"])
    return router
