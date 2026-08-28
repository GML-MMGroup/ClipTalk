from __future__ import annotations

from starlette.requests import Request

import app.main as main_module


def _request(request_id: str = "req-contract-1") -> Request:
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/jobs/demo",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "scheme": "http",
    })
    request.state.request_id = request_id
    return request


def _content_job(kind: str, **overrides):
    job = {
        "id": f"job-{kind}",
        "taskMode": "content_extract",
        "workflowKind": kind,
        "request": {"workflowKind": kind},
        "status": "awaiting_content_confirmation",
        "stage": "content_search_ready",
        "contentSearch": {
            "id": f"search-{kind}",
            "status": "ready",
            "candidates": [{"id": "candidate-1", "start": 1, "end": 2}],
        },
    }
    job.update(overrides)
    return job


def test_api_error_payload_is_actionable_and_backward_compatible() -> None:
    payload = main_module.api_error_payload(
        _request(),
        status_code=429,
        detail={"code": "upload_rate_limited", "message": "上传任务过于频繁"},
    )

    assert payload["detail"]["message"] == "上传任务过于频繁"
    assert payload["code"] == "upload_rate_limited"
    assert payload["requestId"] == "req-contract-1"
    assert payload["error"] == {
        "code": "upload_rate_limited",
        "message": "上传任务过于频繁",
        "recoveryAction": "wait_and_retry",
        "requestId": "req-contract-1",
    }


def test_validation_error_keeps_the_legacy_detail_list() -> None:
    errors = [{"loc": ["body", "instruction"], "msg": "Field required"}]
    payload = main_module.api_error_payload(
        _request("req-validation-1"),
        status_code=422,
        detail=errors,
        default_code="validation_error",
        message_override="请求参数不完整或格式无效，请检查后重试。",
    )

    assert payload["detail"] == errors
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["recoveryAction"] == "check_input"


def test_highlight_presentation_exposes_review_action() -> None:
    presentation = main_module.workflow_presentation_snapshot({
        "id": "highlight-1",
        "taskMode": "highlight",
        "workflowKind": "highlight",
        "request": {"workflowKind": "highlight"},
        "status": "awaiting_confirmation",
        "stage": "refine_vlm",
        "candidates": [{"index": 0}],
    })

    assert presentation["workflowKind"] == "highlight"
    assert presentation["phase"] == "review"
    assert presentation["state"] == "action_required"
    assert presentation["primaryAction"]["kind"] == "review_highlights"
    assert presentation["terminology"]["result"] == "高光成片"


def test_content_presentation_exposes_review_action() -> None:
    presentation = main_module.workflow_presentation_snapshot(_content_job("content_search"))

    assert presentation["workflowKind"] == "content_search"
    assert presentation["phase"] == "review"
    assert presentation["primaryAction"]["kind"] == "review_content"
    assert presentation["primaryAction"]["label"] == "确认内容片段"
    assert presentation["terminology"]["candidate"] == "匹配片段"


def test_person_presentation_requests_target_before_search() -> None:
    presentation = main_module.workflow_presentation_snapshot(_content_job(
        "person_edit",
        contentSearch={},
    ))

    assert presentation["workflowKind"] == "person_edit"
    assert presentation["primaryAction"]["kind"] == "select_person"
    assert presentation["terminology"]["result"] == "人物剪辑"


def test_speaker_presentation_requests_ready_speaker_selection() -> None:
    presentation = main_module.workflow_presentation_snapshot(_content_job(
        "speaker_edit",
        contentSearch={},
        voiceDiscovery={"status": "ready"},
    ))

    assert presentation["workflowKind"] == "speaker_edit"
    assert presentation["primaryAction"]["kind"] == "select_speaker"
    assert presentation["terminology"]["candidate"] == "发言片段"
