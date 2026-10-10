"""Recovery guidance must match the actual stopped operation, including old plans."""
import copy

import pytest

from app.job_projection import plan_terminal_reason, plan_with_presentation, ui_presentation_snapshot


def plan_for(code, kind="no_match", required_state="", message="具体原因"):
    return {"id": "p", "status": "no_result", "steps": [{
        "status": "completed", "tool": "inspect_workspace" if kind == "precondition_missing" else "search_content",
        "arguments": {"requiredState": required_state},
        "result": {"terminalStatus": "no_result", "artifact": {
            "kind": kind, "reasonCode": code, "message": message,
        }},
    }]}


@pytest.mark.parametrize("code,kind,required,expected", [
    ("missing_output", "precondition_missing", "current_output", "missing_base_output"),
    ("missing_precondition", "precondition_missing", "current_output", "missing_base_output"),
    ("missing_precondition", "precondition_missing", "active_timeline", "missing_precondition"),
    ("no_match", "no_match", "", "no_match"),
    ("cover_mismatch", "cover_check", "", "cover_mismatch"),
    ("duration_constraint_unmet", "no_match", "", "unknown"),
])
def test_recovery_is_specific_and_does_not_mutate_history(code, kind, required, expected):
    plan = plan_for(code, kind, required)
    original = copy.deepcopy(plan)
    reason = plan_with_presentation(plan)["terminalReason"]
    assert reason["code"] == expected
    assert plan == original
    job = {"status": "completed", "stage": "agent_no_result", "agent": {
        "status": "no_result", "terminalReason": reason,
    }}
    view = ui_presentation_snapshot(job, workflow={}, execution={}, output_count=0)
    assert view["label"] == reason["label"]
    assert view["detail"] == "具体原因"
    assert view["primaryActionKey"] == reason["actionKey"]
    if expected != "no_match":
        assert "重新查找" not in reason["hint"]


def test_unknown_legacy_outcome_does_not_claim_no_match():
    reason = plan_terminal_reason({"status": "no_result", "steps": []})
    assert reason["code"] == "unknown"
    assert reason["actionKey"] == "view_details"
    assert "未找到" not in reason["label"]


def test_retry_does_not_reuse_old_terminal_reason():
    plan = plan_for("missing_output")
    plan["terminalReason"] = plan_terminal_reason(plan)
    plan["status"] = "running"
    assert plan_with_presentation(plan)["terminalReason"] is None


def test_failed_step_preserves_actual_failure():
    reason = plan_terminal_reason({"status": "failed", "steps": [
        {"status": "failed", "tool": "render_review_preview", "error": "磁盘空间不足"},
    ]})
    assert reason["code"] == "processing_failed"
    assert reason["message"] == "磁盘空间不足"


def test_legacy_plan_api_projects_recovery_without_rewriting_store(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.agent_api import build_agent_router
    from app.agent_store import AgentStore

    store = AgentStore(tmp_path / "agent.sqlite")
    plan = plan_for('missing_precondition', 'precondition_missing', 'current_output')
    plan.update({'workspaceId': 'ws', 'goal': '添加动态片头'})
    store.save('plans', plan)
    store.save('workspaces', {'id': 'ws', 'jobId': 'job', 'activePlanId': 'p', 'messages': [
        {'id': 'result', 'kind': 'plan_result', 'planId': 'p', 'role': 'assistant', 'text': '本次未找到可用片段，可以调整条件重新检索。'},
    ]})
    original_plan = store.get('plans', 'p')
    original_workspace = store.get('workspaces', 'ws')
    platform = SimpleNamespace(store=store)
    app = FastAPI()
    app.include_router(build_agent_router(platform=platform, job_getter=lambda _: {'id': 'job'}))
    with TestClient(app) as client:
        result = client.get('/api/agent/plans/p').json()
        assert result['plan']['terminalReason']['code'] == 'missing_base_output'
        workspace = client.get('/api/agent/workspaces/ws').json()
        assert '需要先生成基础成片' in workspace['workspace']['messages'][0]['text']
        assert '重新检索' not in workspace['workspace']['messages'][0]['text']
    assert store.get('plans', 'p') == original_plan
    assert store.get('workspaces', 'ws') == original_workspace
