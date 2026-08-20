from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_chat_router(
    *,
    chat_with_job: Callable[..., Any],
    stream_chat_with_job: Callable[..., Any],
) -> APIRouter:
    """Own atomic and server-sent-event job conversation routes."""
    router = APIRouter(prefix="/api/jobs/{job_id}/messages", tags=["chat"])
    router.add_api_route("", chat_with_job, methods=["POST"])
    router.add_api_route("/stream", stream_chat_with_job, methods=["POST"])
    return router
