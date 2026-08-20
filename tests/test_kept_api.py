from __future__ import annotations

from app.kept_api import build_kept_router


def test_kept_router_registers_collection_and_media_contract() -> None:
    def handler(job_id: str = "", filename: str = "") -> dict:
        return {"jobId": job_id, "filename": filename}

    router = build_kept_router(
        list_kept_outputs=handler,
        kept_media=handler,
        delete_kept_output=handler,
    )
    assert {(route.path, next(iter(route.methods))) for route in router.routes} == {
        ("/api/kept", "GET"),
        ("/api/kept/{job_id}/{filename}", "GET"),
        ("/api/kept/{job_id}/{filename}", "DELETE"),
    }
