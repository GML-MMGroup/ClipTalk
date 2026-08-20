from __future__ import annotations

from app.media_api import build_media_router


def test_media_router_owns_all_delivery_routes() -> None:
    def handler(job_id: str, filename: str = "", download: int = 0, format: str = "srt") -> dict:
        return {"jobId": job_id, "filename": filename, "download": download, "format": format}

    router = build_media_router(
        source_media=handler,
        job_thumbnail=handler,
        retry_job_thumbnail=handler,
        preview_media=handler,
        preview_media_status=handler,
        browser_preview_media=handler,
        get_job_waveform=handler,
        get_job_timeline_assets=handler,
        get_job_transcript=handler,
        get_job_evidence=handler,
        get_job_recognition=handler,
        get_job_timeline_sprite=handler,
        download_fragment=handler,
        preview_event_group=handler,
        output_subtitles=handler,
        output_media=handler,
        output_preview_media=handler,
        output_browser_preview_media=handler,
    )
    paths = {route.path for route in router.routes}
    assert paths == {
        "/api/jobs/{job_id}/source",
        "/api/jobs/{job_id}/thumbnail",
        "/api/jobs/{job_id}/thumbnail/retry",
        "/api/jobs/{job_id}/preview",
        "/api/jobs/{job_id}/preview-status",
        "/api/jobs/{job_id}/browser-preview",
        "/api/jobs/{job_id}/waveform",
        "/api/jobs/{job_id}/timeline-assets",
        "/api/jobs/{job_id}/transcript",
        "/api/jobs/{job_id}/evidence",
        "/api/jobs/{job_id}/recognition",
        "/api/jobs/{job_id}/timeline-sprite",
        "/api/jobs/{job_id}/fragment",
        "/api/jobs/{job_id}/event-groups/{group_id}/preview",
        "/api/jobs/{job_id}/outputs/{filename}/subtitles",
        "/api/jobs/{job_id}/outputs/{filename}",
        "/api/jobs/{job_id}/outputs/{filename}/preview",
        "/api/jobs/{job_id}/outputs/{filename}/browser-preview",
    }
    methods = {route.path: route.methods for route in router.routes}
    assert methods["/api/jobs/{job_id}/thumbnail/retry"] == {"POST"}
    assert all(value == {"GET"} for path, value in methods.items() if not path.endswith("/retry"))
