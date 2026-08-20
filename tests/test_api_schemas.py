from __future__ import annotations

from app import main as main_module
from app.api_schemas import (
    ChatRequest,
    ContentSearchBoundaryRequest,
    ContentSearchFeedbackRequest,
    ContentSearchOrderRequest,
    LlmOrderRequest,
    ReviewExclusionsRequest,
    TechniquePlanRequest,
)


def test_main_reexports_request_models_for_compatibility() -> None:
    assert main_module.LlmOrderRequest is LlmOrderRequest
    assert main_module.ContentSearchFeedbackRequest is ContentSearchFeedbackRequest
    assert main_module.ContentSearchBoundaryRequest is ContentSearchBoundaryRequest
    assert main_module.ContentSearchOrderRequest is ContentSearchOrderRequest


def test_list_defaults_are_isolated_between_requests() -> None:
    first_order = LlmOrderRequest()
    second_order = LlmOrderRequest()
    first_order.groupIds.append("event_1")
    assert second_order.groupIds == []

    first_plan = TechniquePlanRequest()
    second_plan = TechniquePlanRequest()
    first_plan.groupIds.append("event_2")
    assert second_plan.groupIds == []

    first_exclusions = ReviewExclusionsRequest()
    second_exclusions = ReviewExclusionsRequest()
    first_exclusions.indices.append(1)
    assert second_exclusions.indices == []


def test_content_feedback_boundary_retry_accepts_evidence_without_user_times() -> None:
    request = ContentSearchFeedbackRequest(
        verdict="boundary_incorrect",
        evidenceIds=["speech_1"],
    )
    assert request.evidenceIds == ["speech_1"]
    assert "start" not in request.model_dump()
    assert "end" not in request.model_dump()


def test_manual_content_boundary_request_carries_explicit_trim() -> None:
    request = ContentSearchBoundaryRequest(
        searchId="search_1", matchId="match_1", start=2.04, end=37.64,
    )
    assert request.operation == "save"
    assert (request.start, request.end) == (2.04, 37.64)


def test_chat_request_can_carry_content_search_options() -> None:
    request = ChatRequest(
        text="扩大到全片重新查找", searchScopeKind="all", searchResultLimit=3,
        searchBoundaryMode="complete", contentAutoGenerate=False,
        contentExclusions=["片头"], evidenceMode="mixed",
        allowedCapabilities=["speech", "ocr"],
    )
    assert request.searchScopeKind == "all"
    assert request.searchResultLimit == 3
    assert request.contentExclusions == ["片头"]
    assert request.evidenceMode == "mixed"
    assert request.allowedCapabilities == ["speech", "ocr"]


def test_chat_request_can_carry_editorial_ui_context() -> None:
    request = ChatRequest(text="把当前这段放到开头", uiContext={
        "playheadSeconds": 12.5,
        "viewer": {"kind": "segment", "groupId": "event_1", "segmentId": "shot_2"},
        "selected": {"eventGroupIds": ["event_1"]},
    })
    assert request.uiContext["playheadSeconds"] == 12.5
    assert request.uiContext["viewer"]["segmentId"] == "shot_2"


def test_content_order_request_keeps_explicit_reviewed_ids() -> None:
    request = ContentSearchOrderRequest(searchId="search_1", matchIds=["match_2", "match_1"])
    assert request.searchId == "search_1"
    assert request.matchIds == ["match_2", "match_1"]
