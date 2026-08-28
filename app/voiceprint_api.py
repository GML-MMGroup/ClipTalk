from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_voiceprint_router(
    *,
    list_voice_profiles: Callable[..., Any],
    enroll_voice_profile: Callable[..., Any],
    append_voice_profile: Callable[..., Any],
    rename_voice_profile: Callable[..., Any],
    delete_voice_profile: Callable[..., Any],
) -> APIRouter:
    """Instance-local voice-profile management endpoints."""
    router = APIRouter(prefix="/api/voice-profiles", tags=["voiceprints"])
    router.add_api_route("", list_voice_profiles, methods=["GET"])
    router.add_api_route("/enroll", enroll_voice_profile, methods=["POST"], status_code=201)
    router.add_api_route("/{profile_id}/enroll", append_voice_profile, methods=["POST"])
    router.add_api_route("/{profile_id}", rename_voice_profile, methods=["PATCH"])
    router.add_api_route("/{profile_id}", delete_voice_profile, methods=["DELETE"])
    return router
