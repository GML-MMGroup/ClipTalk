from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter


def build_subtitle_review_router(handlers: Mapping[str, Callable[..., Any]]) -> APIRouter:
    router = APIRouter(prefix="/api/jobs/{job_id}/subtitle-drafts", tags=["subtitle-review"])
    router.add_api_route("", handlers["create_subtitle_draft"], methods=["POST"], status_code=201)
    router.add_api_route("/{draft_id}", handlers["get_subtitle_draft"], methods=["GET"])
    router.add_api_route("/{draft_id}", handlers["update_subtitle_draft"], methods=["PUT"])
    router.add_api_route("/{draft_id}/suggestions", handlers["suggest_subtitle_corrections"], methods=["POST"])
    router.add_api_route("/{draft_id}/style-command", handlers["interpret_subtitle_style_command"], methods=["POST"])
    return router
