from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_content_search_router(
    *,
    content_search_feedback: Callable[..., Any],
    update_content_search_boundary: Callable[..., Any] | None = None,
    add_content_search_manual_range: Callable[..., Any] | None = None,
    restore_content_search: Callable[..., Any],
    cancel_content_search: Callable[..., Any] | None = None,
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
    merge_content_persons: Callable[..., Any] | None = None,
    reassign_content_person_ranges: Callable[..., Any] | None = None,
    undo_content_person_merge: Callable[..., Any] | None = None,
    select_target_voice: Callable[..., Any] | None = None,
    list_current_voices: Callable[..., Any] | None = None,
    discover_current_voices: Callable[..., Any] | None = None,
    label_current_voice: Callable[..., Any] | None = None,
    set_current_voice_role: Callable[..., Any] | None = None,
    select_current_voice: Callable[..., Any] | None = None,
    select_current_voices: Callable[..., Any] | None = None,
    edit_current_voices: Callable[..., Any] | None = None,
    undo_current_voice_edit: Callable[..., Any] | None = None,
    list_temporary_voice_sources: Callable[..., Any] | None = None,
    create_temporary_voice_session: Callable[..., Any] | None = None,
    get_temporary_voice_session: Callable[..., Any] | None = None,
    cancel_temporary_voice_session: Callable[..., Any] | None = None,
    content_search_bulk_keep: Callable[..., Any] | None = None,
    update_content_selection_basket: Callable[..., Any] | None = None,
    confirm_content_selection_basket: Callable[..., Any] | None = None,
) -> APIRouter:
    """Own content-search review, history and render-confirmation routes."""
    router = APIRouter(prefix="/api/jobs/{job_id}/content-search", tags=["content-search"])
    router.add_api_route("/feedback", content_search_feedback, methods=["POST"], status_code=202)
    if update_content_search_boundary is not None:
        router.add_api_route("/boundary", update_content_search_boundary, methods=["PATCH"])
    if add_content_search_manual_range is not None:
        router.add_api_route("/manual-range", add_content_search_manual_range, methods=["POST"])
    if content_search_bulk_keep is not None:
        router.add_api_route("/bulk-keep", content_search_bulk_keep, methods=["POST"], status_code=202)
    if update_content_selection_basket is not None:
        router.add_api_route("/basket", update_content_selection_basket, methods=["PUT"])
    if confirm_content_selection_basket is not None:
        router.add_api_route("/basket/confirm", confirm_content_selection_basket, methods=["POST"], status_code=202)
    router.add_api_route("/history/{search_id}/restore", restore_content_search, methods=["POST"])
    if cancel_content_search is not None:
        router.add_api_route("/{search_id}/cancel", cancel_content_search, methods=["POST"])
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
    if merge_content_persons is not None:
        router.add_api_route("/persons/merge", merge_content_persons, methods=["POST"])
    if reassign_content_person_ranges is not None:
        router.add_api_route("/persons/ranges/reassign", reassign_content_person_ranges, methods=["POST"])
    if undo_content_person_merge is not None:
        router.add_api_route("/persons/merge/undo", undo_content_person_merge, methods=["POST"])
    if select_target_voice is not None:
        router.add_api_route("/target-voice", select_target_voice, methods=["POST"], status_code=202)
    if list_current_voices is not None:
        router.add_api_route("/voices", list_current_voices, methods=["GET"])
    if discover_current_voices is not None:
        router.add_api_route("/voices/discover", discover_current_voices, methods=["POST"], status_code=202)
    if label_current_voice is not None:
        router.add_api_route("/voices/label", label_current_voice, methods=["PATCH"])
    if set_current_voice_role is not None:
        router.add_api_route("/voices/role", set_current_voice_role, methods=["PATCH"])
    if select_current_voice is not None:
        router.add_api_route("/target-speaker", select_current_voice, methods=["POST"], status_code=202)
    if select_current_voices is not None:
        router.add_api_route("/target-speakers", select_current_voices, methods=["POST"], status_code=202)
    if edit_current_voices is not None:
        router.add_api_route("/voices/timeline", edit_current_voices, methods=["PATCH"])
    if undo_current_voice_edit is not None:
        router.add_api_route("/voices/timeline/undo", undo_current_voice_edit, methods=["POST"])
    if list_temporary_voice_sources is not None:
        router.add_api_route("/voice-sessions/sources", list_temporary_voice_sources, methods=["GET"])
    if create_temporary_voice_session is not None:
        router.add_api_route("/voice-sessions", create_temporary_voice_session, methods=["POST"], status_code=202)
    if get_temporary_voice_session is not None:
        router.add_api_route("/voice-sessions/{session_id}", get_temporary_voice_session, methods=["GET"])
    if cancel_temporary_voice_session is not None:
        router.add_api_route("/voice-sessions/{session_id}/cancel", cancel_temporary_voice_session, methods=["POST"])
    return router
