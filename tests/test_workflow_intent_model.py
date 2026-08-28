from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import main
from app.api_schemas import WorkflowIntentRequest


class IntentClient:
    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.cancelled = False

    def complete_json(self, *_args, **_kwargs):
        self.calls += 1
        return dict(self.response)

    def cancel(self):
        self.cancelled = True


def clear_intent_cache() -> None:
    with main.workflow_intent_cache_lock:
        main.workflow_intent_cache.clear()


def test_workflow_intent_endpoint_uses_validated_model_result_and_cache() -> None:
    clear_intent_cache()
    client = IntentClient({
        "action": "start_workflow",
        "workflowKind": "content_search",
        "confidence": .95,
        "needsConfirmation": False,
        "reason": "用户要求定位具体内容",
    })
    request = WorkflowIntentRequest(text="查找所有提到续航的片段")
    with patch.object(main, "create_llm_client_for_job", return_value=client):
        first = main.classify_workflow_intent(request)
        second = main.classify_workflow_intent(request)

    assert first["decision"]["workflowKind"] == "content_search"
    assert first["decision"]["source"] == "model_primary_v2"
    assert first["decision"]["cacheHit"] is False
    assert second["decision"]["cacheHit"] is True
    assert client.calls == 1
    assert client.cancelled is True


def test_workflow_intent_endpoint_requires_manual_choice_when_model_fails() -> None:
    clear_intent_cache()
    with patch.object(main, "create_llm_client_for_job", side_effect=RuntimeError("offline")), \
            pytest.raises(HTTPException) as captured:
        main.classify_workflow_intent(WorkflowIntentRequest(text="帮我处理一下"))

    assert captured.value.status_code == 503
    assert captured.value.detail["code"] == "intent_model_unavailable"
    assert len(captured.value.detail["options"]) == 4


def test_conversation_model_can_switch_workflow_and_explicit_choice_bypasses_it() -> None:
    job = {"workflowKind": "content_search", "request": {}, "status": "completed"}
    with patch.object(main, "classify_workflow_intent_model", return_value={
        "action": "switch_workflow",
        "workflowKind": "speaker_edit",
        "confidence": .96,
        "reason": "用户要求按匿名声音选择",
    }) as classifier:
        target, confirmation = main._conversation_workflow_route(job, "切换到按说话人剪辑")
    assert target == "speaker_edit"
    assert confirmation is None
    classifier.assert_called_once()

    with patch.object(main, "classify_workflow_intent_model") as classifier:
        target, confirmation = main._conversation_workflow_route(
            job, "继续查找", confirmed_workflow="content_search",
        )
    assert target is None
    assert confirmation is None
    classifier.assert_not_called()
