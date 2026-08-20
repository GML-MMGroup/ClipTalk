from __future__ import annotations

from app.content_search_api import build_content_search_router


def test_content_search_router_preserves_status_contract() -> None:
    def handler(job_id: str, search_id: str = "") -> dict:
        return {"jobId": job_id, "searchId": search_id}

    router = build_content_search_router(
        content_search_feedback=handler,
        update_content_search_boundary=handler,
        restore_content_search=handler,
        get_content_search_history=handler,
        recommend_content_search_order=handler,
        update_content_search_review_draft=handler,
        confirm_content_search=handler,
        list_content_persons=handler,
        update_content_person_label=handler,
        select_content_person_target=handler,
        confirm_content_person_speaker=handler,
        content_person_thumbnail=handler,
    )
    routes = {(route.path, next(iter(route.methods))): route for route in router.routes}
    assert set(routes) == {
        ("/api/jobs/{job_id}/content-search/feedback", "POST"),
        ("/api/jobs/{job_id}/content-search/boundary", "PATCH"),
        ("/api/jobs/{job_id}/content-search/history/{search_id}/restore", "POST"),
        ("/api/jobs/{job_id}/content-search/history/{search_id}", "GET"),
        ("/api/jobs/{job_id}/content-search/order-recommendation", "POST"),
        ("/api/jobs/{job_id}/content-search/review-draft", "PATCH"),
        ("/api/jobs/{job_id}/content-search/confirm", "POST"),
        ("/api/jobs/{job_id}/content-search/persons", "GET"),
        ("/api/jobs/{job_id}/content-search/persons/{person_id}", "PATCH"),
        ("/api/jobs/{job_id}/content-search/target-person", "POST"),
        ("/api/jobs/{job_id}/content-search/confirm-speaker", "POST"),
        ("/api/jobs/{job_id}/content-search/persons/{person_id}/thumbnail", "GET"),
    }
    assert routes[("/api/jobs/{job_id}/content-search/feedback", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/confirm", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/target-person", "POST")].status_code == 202
    assert routes[("/api/jobs/{job_id}/content-search/confirm-speaker", "POST")].status_code == 202
