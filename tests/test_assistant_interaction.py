from concurrent.futures import Future
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent_api import build_agent_router
from app.agent_platform import AgentPlatform, AgentServiceError
from app.assistant_interaction import AssistantInteraction, freeze_context, message_intent, revised_goal, validate_frozen


@pytest.fixture
def setup(tmp_path):
    platform = AgentPlatform(data_root=tmp_path, service_url="http://unused.invalid", model_config_resolver=lambda: {})
    platform.install_skill(markdown="---\nname: test-editor\ndescription: Test editor\nallowed-tools: inspect_workspace\n---\nInspect only.", source="test", status="enabled")
    platform.install_skill(markdown="---\nname: cliptalk-smart-reframe\ndescription: Change aspect\nallowed-tools: inspect_workspace render_social_preview run_delivery_qc\n---\nChange aspect.", source="test", status="enabled")
    platform.client = Mock()
    platform.client.route_skill.return_value = {"skillId": "test-editor"}
    platform.client.plan.return_value = {"plan": {"summary": "测试方案", "steps": [{"id": "inspect", "tool": "inspect_workspace", "title": "检查状态", "arguments": {}, "dependencies": [], "expectedOutput": "状态", "sideEffect": "read"}]}}
    job = {"id": "job_test", "revision": 1, "videoInfo": {"duration": 20}, "contentSearch": {"id": "search", "candidates": [{"id": "a", "start": 1, "end": 2}, {"id": "b", "start": 3, "end": 4}]}}
    workspace = platform.create_workspace(job_id=job["id"])
    service = AssistantInteraction(platform, lambda _: job)
    return platform, service, workspace["id"], job


def send(service, workspace, text, key="one", **extra):
    return service.handle(workspace, {"text": text, "clientMessageId": key, **extra})


@pytest.mark.parametrize("text,intent", [("为什么有无关画面？", "answer"), ("有用吗", "answer"), ("怎么优化音频？", "answer"), ("剪成竖屏", "edit"), ("制作一段动态图文片头", "edit"), ("优化当前样片的人声清晰度", "edit"), ("全面检查当前成片中的黑帧和静音", "edit"), ("校对字幕并适配竖屏", "edit"), ("诊断当前成片的剪辑问题", "edit"), ("再短一点", "edit"), ("从讲价格的地方开始", "edit"), ("第二段不对", "feedback"), ("可以", "confirmation"), ("一个温暖的夏天", "clarification")])
def test_intents(text, intent):
    assert message_intent(text) == intent


def test_explicit_skill_turns_an_ambiguous_description_into_an_action(setup):
    platform, service, workspace, _ = setup
    response = send(service, workspace, "一个温暖的夏天", skillId="test-editor")

    assert response["action"] == "plan_confirmation"
    assert response["plan"]["skillId"] == "test-editor"


def test_question_never_calls_planner(setup):
    platform, service, workspace, _ = setup
    response = send(service, workspace, "为什么有无关画面？")
    assert response["action"] == "answer"
    platform.client.plan.assert_not_called()
    assert len(service.workspace(workspace)["messages"]) == 2


def test_answer_provider_is_read_only_and_falls_back_safely(setup):
    platform, service, workspace, _ = setup
    platform._conversation_answer_provider = Mock(side_effect=RuntimeError("secret"))
    result = send(service, workspace, "为什么？")
    assert "secret" not in result["message"]
    assert result["action"] == "answer"
    platform.client.plan.assert_not_called()


def test_duplicate_submission_creates_one_plan(setup):
    platform, service, workspace, _ = setup
    first = send(service, workspace, "找到目标片段")
    second = send(service, workspace, "找到目标片段")
    assert first["plan"]["id"] == second["plan"]["id"]
    assert platform.client.plan.call_count == 1
    assert len(service.workspace(workspace)["messages"]) == 2
    with pytest.raises(ValueError):
        send(service, workspace, "改成横屏")


def test_failed_revision_preserves_original_plan(setup):
    platform, service, workspace, _ = setup
    original = send(service, workspace, "剪成竖屏")["plan"]
    platform.client.plan.side_effect = AgentServiceError("offline")
    result = send(service, workspace, "改成方屏", "two")
    assert result["retryable"]
    assert platform.store.get("plans", original["id"])["status"] == "awaiting_confirmation"
    assert service.workspace(workspace)["activePlanId"] == original["id"]
    assert not service.workspace(workspace).get("planningRequestId")


def test_successful_revision_replaces_only_when_ready(setup):
    platform, service, workspace, _ = setup
    original = send(service, workspace, "剪成竖屏")["plan"]
    replacement = send(service, workspace, "改成方屏", "two")["plan"]
    assert replacement["replacesPlanId"] == original["id"]
    assert "竖屏" not in replacement["goal"]
    assert platform.store.get("plans", original["id"])["supersededBy"] == replacement["id"]
    assert replacement["status"] == "awaiting_confirmation"


def test_running_changes_are_durable_and_do_not_cancel(setup):
    platform, service, workspace, _ = setup
    plan = send(service, workspace, "剪成竖屏")["plan"]
    platform.store.save("plans", {**plan, "status": "running"})
    result = send(service, workspace, "不要字幕", "two")
    assert result["action"] == "pending_change"
    assert platform.store.get("plans", plan["id"])["status"] == "running"
    assert service.workspace(workspace)["pendingChanges"][0]["text"] == "不要字幕"
    service.change(workspace, "discard")
    assert not service.workspace(workspace)["pendingChanges"]


def test_stop_waits_for_actual_future_on_repeated_attempts(setup):
    platform, service, workspace, _ = setup
    plan = send(service, workspace, "剪成竖屏")["plan"]
    platform.store.save("plans", {**plan, "status": "running"})
    future = Future()
    future.set_running_or_notify_cancel()
    platform._operation_handles[(plan["id"], "inspect")] = {"future": future}
    send(service, workspace, "改成方屏", "two")
    with pytest.raises(ValueError, match="尚未"):
        service.change(workspace, "stop")
    with pytest.raises(ValueError, match="尚未"):
        service.change(workspace, "stop")
    assert send(service, workspace, "找到新的片段", "three")["action"] == "clarification"
    future.set_result({})
    assert service.change(workspace, "prepare")["plan"]["status"] == "awaiting_confirmation"


def test_freeze_and_revalidate_selection(setup):
    _, _, _, job = setup
    frozen = freeze_context(job, {"jobId": job["id"], "searchId": "search", "selected": {"contentMatchIds": ["b", "a"]}})
    assert frozen["contentSelection"]["matchIds"] == ["b", "a"]
    job["contentSearch"]["candidates"][0]["end"] = 2.5
    with pytest.raises(ValueError, match="证据已更新"):
        validate_frozen(job, frozen)


@pytest.mark.parametrize("ui", [{"jobId": "other"}, {"jobRevision": 0}, {"searchId": "old", "selected": {"contentMatchIds": ["a"]}}, {"viewer": {"outputFilename": "missing.mp4"}}, {"timeDomain": "preview", "timelineSelection": {"start": 1, "end": 3}}])
def test_bad_references_never_fall_back(setup, ui):
    platform, service, workspace, _ = setup
    result = send(service, workspace, "合成为竖屏", uiContext=ui)
    assert result["action"] == "clarification"
    platform.client.plan.assert_not_called()


def test_selection_is_bound_to_plan_hash_and_approval(setup):
    platform, service, workspace, job = setup
    plan = send(service, workspace, "合成所选片段", uiContext={"searchId": "search", "selected": {"contentMatchIds": ["b"]}})["plan"]
    assert plan["inputContext"]["contentSelection"]["matchIds"] == ["b"]
    job["contentSearch"]["candidates"][1]["start"] = 2.9
    with pytest.raises(ValueError, match="引用片段"):
        platform.approve_plan(plan["id"], expected_hash=plan["planHash"])


def test_new_search_does_not_bind_old_empty_selection(setup):
    _, service, workspace, _ = setup
    result = send(service, workspace, "找到红色汽车", uiContext={"searchId": "search", "selected": {"contentMatchIds": []}})
    assert result["action"] == "plan_confirmation"
    assert not result["plan"]["inputContext"].get("contentSelection")


def test_anchor_search_does_not_freeze_previous_candidate_selection(setup):
    _, service, workspace, _ = setup
    result = send(service, workspace, "从讲价格的地方开始", uiContext={
        "searchId": "search", "selected": {"contentMatchIds": ["a"]},
    })
    assert result["action"] == "plan_confirmation"
    assert not result["plan"]["inputContext"].get("contentSelection")


def test_vague_confirmation_never_exports(setup):
    platform, service, workspace, _ = setup
    result = send(service, workspace, "可以")
    assert result["action"] == "clarification"
    platform.client.plan.assert_not_called()


def test_pending_conflicts_are_not_silently_merged(setup):
    platform, service, workspace, _ = setup
    plan = send(service, workspace, "剪成竖屏")["plan"]
    platform.store.save("plans", {**plan, "status": "running"})
    send(service, workspace, "改成30秒", "two")
    send(service, workspace, "改成60秒", "three")
    platform.store.save("plans", {**plan, "status": "preview_ready"})
    with pytest.raises(ValueError, match="冲突"):
        service.change(workspace, "prepare")
    assert len(service.workspace(workspace)["pendingChanges"]) == 2


def test_stream_answer_and_history_survive_reload(setup):
    platform, _, workspace, job = setup
    app = FastAPI()
    app.include_router(build_agent_router(platform=platform, job_getter=lambda _: job))
    with TestClient(app) as client:
        response = client.post(f"/api/agent/workspaces/{workspace}/messages/stream", json={"text": "为什么有无关画面", "clientMessageId": "question"})
        assert response.status_code == 200
        assert "event: assistant.result" in response.text
        assert "event: plan\n" not in response.text
        saved = client.get(f"/api/agent/workspaces/{workspace}").json()
        assert [m["role"] for m in saved["workspace"]["messages"]] == ["user", "assistant"]


def test_revision_removes_conflicting_old_parameters():
    result = revised_goal("剪成9:16竖屏60秒并添加字幕", "改为方屏30秒，不要字幕")
    assert "9:16" not in result and "60秒" not in result and "添加字幕" not in result


def test_preview_time_question_does_not_become_source_edit(setup):
    platform, service, workspace, _ = setup
    result = send(service, workspace, "这里为什么不对", uiContext={"timeDomain": "preview", "timelineSelection": {"start": 1, "end": 2}})
    assert result["action"] == "answer"
    platform.client.plan.assert_not_called()


def test_review_explicitly_rebinds_new_evidence(setup):
    _, service, workspace, job = setup
    plan = {"inputContext": {"jobId": job["id"], "contentSelection": {"searchId": "old"}}}
    service.bind_review(plan, service.workspace(workspace), {"selection": {"searchId": "search", "matchIds": ["b"]}})
    assert plan["inputContext"]["contentSelection"]["matchIds"] == ["b"]
    assert plan["referenceReviews"][0]["previous"]["contentSelection"]["searchId"] == "old"


def test_approved_same_source_handoff_not_rejected_as_cross_task():
    validate_frozen({"id": "child", "parentJobId": "source"}, {"jobId": "source"})
    with pytest.raises(ValueError):
        validate_frozen({"id": "child", "parentJobId": "source"}, {"jobId": "source", "outputFilename": "old.mp4"})


def test_output_revision_keeps_aspect_and_binds_its_timeline(setup):
    _, service, workspace, job = setup
    job["editSessions"] = [{"id": "session", "revision": 4}]
    job["outputs"] = [{"filename": "square.mp4", "duration": 18.5, "sourceEditSessionId": "session", "reframe": {"aspect": "1:1", "fit": "blur"}}]
    frozen = freeze_context(job, {"viewer": {"outputFilename": "square.mp4"}})
    assert frozen["outputAspect"] == "1:1"
    assert frozen["outputDurationSeconds"] == 18.5
    assert frozen["editSessionRevision"] == 4
    plan = send(service, workspace, "不要字幕", uiContext={"viewer": {"outputFilename": "square.mp4"}})["plan"]
    assert plan["goal"].startswith("修改当前成片")
    assert plan["planningContext"]["delivery"]["outputAspect"] == "1:1"
    job["editSessions"][0]["revision"] = 5
    with pytest.raises(ValueError, match="时间线已变化"):
        validate_frozen(job, frozen)


def test_missing_addon_releases_revision_reservation(setup):
    platform, service, workspace, _ = setup
    original = send(service, workspace, "找到目标片段")["plan"]
    platform._compose_skills = Mock(side_effect=ValueError("缺少执行能力"))
    result = send(service, workspace, "改成方屏", "two")
    assert result["retryable"]
    assert not service.workspace(workspace).get("planningRequestId")
    assert platform.store.get("plans", original["id"])["status"] == "awaiting_confirmation"


def test_confirmation_uses_seen_plan_hash_not_an_inferred_action(setup):
    platform, service, workspace, _ = setup
    plan = send(service, workspace, "找到目标片段")["plan"]
    platform.approve_plan = Mock(return_value={**plan, "status": "running"})
    stale = send(service, workspace, "可以", "two", replyToActionId=plan["id"], uiContext={"confirmationHash": "old"})
    assert stale["action"] == "clarification"
    platform.approve_plan.assert_not_called()
    result = send(service, workspace, "可以", "three", replyToActionId=plan["id"], uiContext={"confirmationHash": plan["planHash"]})
    assert result["action"] == "plan_updated"
    platform.approve_plan.assert_called_once_with(plan["id"], expected_hash=plan["planHash"])


def test_natural_confirmation_never_starts_formal_export(setup):
    platform, service, workspace, _ = setup
    plan = send(service, workspace, "找到目标片段")["plan"]
    platform.store.save("plans", {**plan, "steps": [{"tool": "export_delivery", "sideEffect": "export"}]})
    platform.approve_plan = Mock()
    result = send(service, workspace, "可以", "two", replyToActionId=plan["id"], uiContext={"confirmationHash": plan["planHash"]})
    assert result["action"] == "clarification"
    platform.approve_plan.assert_not_called()
