from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_media_router(
    *,
    source_media: Callable[..., Any],
    job_thumbnail: Callable[..., Any],
    retry_job_thumbnail: Callable[..., Any],
    preview_media: Callable[..., Any],
    preview_media_status: Callable[..., Any],
    browser_preview_media: Callable[..., Any],
    get_job_waveform: Callable[..., Any],
    get_job_timeline_assets: Callable[..., Any],
    get_job_transcript: Callable[..., Any],
    get_job_evidence: Callable[..., Any],
    get_job_recognition: Callable[..., Any],
    get_job_timeline_sprite: Callable[..., Any],
    download_fragment: Callable[..., Any],
    preview_event_group: Callable[..., Any],
    output_subtitles: Callable[..., Any],
    output_media: Callable[..., Any],
    output_preview_media: Callable[..., Any],
    output_browser_preview_media: Callable[..., Any],
) -> APIRouter:
    """Own the public media-delivery URL surface.

    The handlers remain dependency-injected so media storage and rendering can
    be extracted from the application state incrementally without introducing
    a circular import back to ``main``.
    """
    router = APIRouter(tags=["media"])
    routes = (
        ("/api/jobs/{job_id}/source", source_media),
        ("/api/jobs/{job_id}/thumbnail", job_thumbnail),
        ("/api/jobs/{job_id}/preview", preview_media),
        ("/api/jobs/{job_id}/preview-status", preview_media_status),
        ("/api/jobs/{job_id}/browser-preview", browser_preview_media),
        ("/api/jobs/{job_id}/waveform", get_job_waveform),
        ("/api/jobs/{job_id}/timeline-assets", get_job_timeline_assets),
        ("/api/jobs/{job_id}/transcript", get_job_transcript),
        ("/api/jobs/{job_id}/evidence", get_job_evidence),
        ("/api/jobs/{job_id}/recognition", get_job_recognition),
        ("/api/jobs/{job_id}/timeline-sprite", get_job_timeline_sprite),
        ("/api/jobs/{job_id}/fragment", download_fragment),
        ("/api/jobs/{job_id}/event-groups/{group_id}/preview", preview_event_group),
        ("/api/jobs/{job_id}/outputs/{filename}/subtitles", output_subtitles),
        ("/api/jobs/{job_id}/outputs/{filename}", output_media),
        ("/api/jobs/{job_id}/outputs/{filename}/preview", output_preview_media),
        ("/api/jobs/{job_id}/outputs/{filename}/browser-preview", output_browser_preview_media),
    )
    for path, endpoint in routes:
        router.add_api_route(path, endpoint, methods=["GET"])
    router.add_api_route(
        "/api/jobs/{job_id}/thumbnail/retry", retry_job_thumbnail, methods=["POST"], status_code=202,
    )
    return router
