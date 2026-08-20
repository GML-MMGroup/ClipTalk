from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_content_search_router(
    *,
    content_search_feedback: Callable[..., Any],
    update_content_search_boundary: Callable[..., Any] | None = None,
    restore_content_search: Callable[..., Any],
    get_content_search_history: Callable[..., Any] | None = None,
    list_content_search_turns: Callable[..., Any] | None = None,
    recommend_content_search_order: Callable[..., Any],
    update_content_search_review_draft: Callable[..., Any],
    update_content_search_dialogue_mode: Callable[..., Any] | None = None,
    confirm_content_search: Callable[..., Any],
    list_content_persons: Callable[..., Any],
    update_content_person_label: Callable[..., Any],
    select_content_person_target: Callable[..., Any],
    confirm_content_person_speaker: Callable[..., Any],
    content_person_thumbnail: Callable[..., Any],
    content_search_bulk_keep: Callable[..., Any] | None = None,
    update_content_selection_basket: Callable[..., Any] | None = None,
    confirm_content_selection_basket: Callable[..., Any] | None = None,
) -> APIRouter:
    """Own content-search review, history and render-confirmation routes."""
    router = APIRouter(prefix="/api/jobs/{job_id}/content-search", tags=["content-search"])
    router.add_api_route("/feedback", content_search_feedback, methods=["POST"], status_code=202)
    if update_content_search_boundary is not None:
        router.add_api_route("/boundary", update_content_search_boundary, methods=["PATCH"])
    if content_search_bulk_keep is not None:
        router.add_api_route("/bulk-keep", content_search_bulk_keep, methods=["POST"], status_code=202)
    if update_content_selection_basket is not None:
        router.add_api_route("/basket", update_content_selection_basket, methods=["PUT"])
    if confirm_content_selection_basket is not None:
        router.add_api_route("/basket/confirm", confirm_content_selection_basket, methods=["POST"], status_code=202)
    router.add_api_route("/history/{search_id}/restore", restore_content_search, methods=["POST"])
    if get_content_search_history is not None:
        router.add_api_route("/history/{search_id}", get_content_search_history, methods=["GET"])
    if list_content_search_turns is not None:
        router.add_api_route("/turns", list_content_search_turns, methods=["GET"])
    router.add_api_route("/order-recommendation", recommend_content_search_order, methods=["POST"])
    router.add_api_route("/review-draft", update_content_search_review_draft, methods=["PATCH"])
    if update_content_search_dialogue_mode is not None:
        router.add_api_route("/dialogue-mode", update_content_search_dialogue_mode, methods=["PATCH"])
    router.add_api_route("/confirm", confirm_content_search, methods=["POST"], status_code=202)
    router.add_api_route("/persons", list_content_persons, methods=["GET"])
    router.add_api_route("/persons/{person_id}", update_content_person_label, methods=["PATCH"])
    router.add_api_route("/target-person", select_content_person_target, methods=["POST"], status_code=202)
    router.add_api_route("/confirm-speaker", confirm_content_person_speaker, methods=["POST"], status_code=202)
    router.add_api_route("/persons/{person_id}/thumbnail", content_person_thumbnail, methods=["GET"])
    return router
