from __future__ import annotations

from app.chat_api import build_chat_router


def test_chat_router_registers_atomic_and_streaming_endpoints() -> None:
    def handler(job_id: str) -> dict:
        return {"jobId": job_id}

    router = build_chat_router(
        chat_with_job=handler,
        stream_chat_with_job=handler,
    )
    assert {
        (route.path, next(iter(route.methods)))
        for route in router.routes
    } == {
        ("/api/jobs/{job_id}/messages", "POST"),
        ("/api/jobs/{job_id}/messages/stream", "POST"),
    }
