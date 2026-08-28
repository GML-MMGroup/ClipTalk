from __future__ import annotations

from app.content_search_api import build_content_search_router


def test_content_search_router_preserves_status_contract() -> None:
    def handler(job_id: str, search_id: str = "") -> dict:
        return {"jobId": job_id, "searchId": search_id}

    router = build_content_search_router(
        content_search_feedback=handler,
        update_content_search_boundary=handler,
        add_content_search_manual_range=handler,
        restore_content_search=handler,
        cancel_content_search=handler,
        get_content_search_history=handler,
        recommend_content_search_order=handler,
        update_content_search_review_draft=handler,
        confirm_content_search=handler,
        list_content_persons=handler,
        update_content_person_label=handler,
        select_content_person_target=handler,
        confirm_content_person_speaker=handler,
        content_person_thumbnail=handler,
        merge_content_persons=handler,
        reassign_content_person_ranges=handler,
        undo_content_person_merge=handler,
        select_target_voice=handler,
        list_current_voices=handler,
        discover_current_voices=handler,
        label_current_voice=handler,
        set_current_voice_role=handler,
        select_current_voice=handler,
        select_current_voices=handler,
        edit_current_voices=handler,
        undo_current_voice_edit=handler,
        list_temporary_voice_sources=handler,
        create_temporary_voice_session=handler,
        get_temporary_voice_session=handler,
        cancel_temporary_voice_session=handler,
    )
    routes = {(route.path, next(iter(route.methods))): route for route in router.routes}
    assert set(routes) == {
        ("/api/jobs/{job_id}/content-search/feedback", "POST"),
        ("/api/jobs/{job_id}/content-search/boundary", "PATCH"),
        ("/api/jobs/{job_id}/content-search/manual-range", "POST"),
        ("/api/jobs/{job_id}/content-search/history/{search_id}/restore", "POST"),
        ("/api/jobs/{job_id}/content-search/{search_id}/cancel", "POST"),
        ("/api/jobs/{job_id}/content-search/history/{search_id}", "GET"),
        ("/api/jobs/{job_id}/content-search/order-recommendation", "POST"),
        ("/api/jobs/{job_id}/content-search/review-draft", "PATCH"),
        ("/api/jobs/{job_id}/content-search/confirm", "POST"),
        ("/api/jobs/{job_id}/content-search/persons", "GET"),
        ("/api/jobs/{job_id}/content-search/persons/{person_id}", "PATCH"),
        ("/api/jobs/{job_id}/content-search/target-person", "POST"),
        ("/api/jobs/{job_id}/content-search/confirm-speaker", "POST"),
        ("/api/jobs/{job_id}/content-search/persons/{person_id}/thumbnail", "GET"),
        ("/api/jobs/{job_id}/content-search/persons/merge", "POST"),
        ("/api/jobs/{job_id}/content-search/persons/ranges/reassign", "POST"),
        ("/api/jobs/{job_id}/content-search/persons/merge/undo", "POST"),
        ("/api/jobs/{job_id}/content-search/target-voice", "POST"),
        ("/api/jobs/{job_id}/content-search/voices", "GET"),
        ("/api/jobs/{job_id}/content-search/voices/discover", "POST"),
        ("/api/jobs/{job_id}/content-search/voices/label", "PATCH"),
        ("/api/jobs/{job_id}/content-search/voices/role", "PATCH"),
        ("/api/jobs/{job_id}/content-search/target-speaker", "POST"),
        ("/api/jobs/{job_id}/content-search/target-speakers", "POST"),
        ("/api/jobs/{job_id}/content-search/voices/timeline", "PATCH"),
        ("/api/jobs/{job_id}/content-search/voices/timeline/undo", "POST"),
        ("/api/jobs/{job_id}/content-search/voice-sessions/sources", "GET"),
        ("/api/jobs/{job_id}/content-search/voice-sessions", "POST"),
        ("/api/jobs/{job_id}/content-search/voice-sessions/{session_id}", "GET"),
        ("/api/jobs/{job_id}/content-search/voice-sessions/{session_id}/cancel", "POST"),
    }
    assert routes[("/api/jobs/{job_id}/content-search/feedback", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/confirm", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/target-person", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/confirm-speaker", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/voices/discover", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/target-speaker", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/target-speakers", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/voice-sessions", "POST")].status_code == 202
