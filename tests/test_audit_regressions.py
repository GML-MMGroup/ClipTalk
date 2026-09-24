"""Regression cases discovered by exercising the complete editing workflow."""
from concurrent.futures import Future
from pathlib import Path
from threading import Event, Thread

import pytest

from app.agent_platform import AgentPlatform
from app.job_projection import ui_presentation_snapshot


@pytest.fixture
def platform(tmp_path):
    value = AgentPlatform(data_root=tmp_path, service_url="http://unused.invalid", model_config_resolver=lambda: {})
    value.seed_skills(Path(__file__).resolve().parents[1] / "skills")
    return value


def compile_goal(platform, text, skill_id="cliptalk-content-extractor"):
    skill = platform.store.get("skills", skill_id)
    context = {"duration": 600, "speaker": {"available": True, "needsConfirmation": True}}
    brief = platform._editing_brief(text, context)
    skills = platform._compose_skills(skill, brief=brief, context=context)
    return platform._compile_profile_plan({}, skill=skill, skills=skills, goal=text, context=context)


def test_excluded_questions_do_not_invert_the_included_speaker(platform):
    plan = compile_goal(platform, "只保留 Speaker 2 的发言，不要主持人提问", "cliptalk-speaker-editor")
    step = next(step for step in plan["steps"] if step["tool"] == "select_speakers")
    assert step["arguments"] == {"mode": "include", "label": "说话人 2"}
    assert plan["brief"]["keepQuestionContext"] is False
    assert "不要主持人提问" in next(step for step in plan["steps"] if step["tool"] == "search_content")["arguments"]["query"]


@pytest.mark.parametrize("prefix,start,end", [("最后两分钟", 480, 600), ("开头30秒", 0, 30)])
def test_source_window_is_not_a_requested_output_duration(platform, prefix, start, end):
    plan = compile_goal(platform, f"保留{prefix}里讲续航的内容")
    assert plan["brief"]["targetSeconds"] is None
    search = next(step for step in plan["steps"] if step["tool"] == "search_content")
    assert search["arguments"]["sourceScopeStart"] == start
    assert search["arguments"]["sourceScopeEnd"] == end
    assert "素材范围" in plan["summary"]


def test_output_duration_can_coexist_with_a_source_window(platform):
    plan = compile_goal(platform, "从最后两分钟里剪成30秒")
    assert plan["brief"]["targetSeconds"] == 30
    assert plan["brief"]["sourceRange"]["start"] == 480


@pytest.mark.parametrize("text", ["加中文字幕", "添加英文字幕", "不要封面，加中文字幕"])
def test_language_qualified_subtitles_compile_real_subtitle_steps(platform, text):
    plan = compile_goal(platform, f"把视频剪成60秒，{text}")
    tools = [step["tool"] for step in plan["steps"]]
    assert "prepare_subtitle_review" in tools
    assert plan["brief"]["graphicsRequested"] is False
    assert "生成字幕" in plan["summary"]


def test_negated_subtitle_is_not_requested(platform):
    plan = compile_goal(platform, "剪成60秒，不要生成字幕，不要封面")
    assert not plan["brief"]["subtitleRequested"]
    assert not plan["brief"]["coverRequested"]


def test_short_chinese_version_count_and_no_reuse_are_preserved(platform):
    plan = compile_goal(platform, "做三版，每版30秒，不要复用片段")
    step = next(step for step in plan["steps"] if step["tool"] == "propose_timeline_edit")
    assert step["arguments"]["variantCount"] == 3
    assert step["arguments"]["distinctSourceAcrossVariants"] is True
    assert "各版本不得复用" in plan["summary"]


@pytest.mark.parametrize("completion", ["success", "no_result", "failure", "future", "action"])
def test_cancelled_dispatch_cannot_resurrect_plan_or_register_an_operation(platform, completion):
    started, release, cancelled = Event(), Event(), Event()
    workspace = platform.create_workspace(job_id="isolated")
    platform.store.save("runs", {"id": "run_audit", "status": "running"})
    plan = platform.store.save("plans", {
        "id": "plan_audit", "workspaceId": workspace["id"], "runId": "run_audit", "status": "running",
        "steps": [{"id": "inspect", "tool": "inspect_workspace", "arguments": {}, "status": "running", "attempts": 1}],
    })
    future = Future()
    def dispatch(*_):
        started.set()
        assert release.wait(5)
        if completion == "failure":
            raise RuntimeError("late failure")
        if completion == "future":
            return {"future": future, "cancel": cancelled.set}
        if completion == "action":
            return {"actionRequired": True}
        return {"terminalStatus": "no_result"} if completion == "no_result" else {"ok": True}
    platform.configure_tool_dispatcher(dispatch)
    thread = Thread(target=platform._execute_step, args=(plan["id"], "inspect"))
    thread.start()
    try:
        assert started.wait(5)
        platform.cancel_plan(plan["id"])
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    result = platform.store.get("plans", plan["id"])
    assert result["status"] == "cancelled"
    assert result["steps"][0]["status"] == "cancelled"
    assert platform.store.get("runs", "run_audit")["status"] == "cancelled"
    assert not platform._operation_handles
    if completion == "future":
        assert future.cancelled() and cancelled.is_set()


def test_cancelled_and_handed_off_jobs_have_distinct_presentation():
    cancelled = ui_presentation_snapshot({"status": "cancelled"}, workflow={}, execution={}, output_count=0)
    assert cancelled["group"] == "cancelled"
    handed_off = ui_presentation_snapshot({"status": "completed", "stage": "agent_handed_off", "agentHandoffJobId": "child"}, workflow={}, execution={}, output_count=0)
    assert handed_off["key"] == "handed_off"
    assert handed_off["handoffJobId"] == "child"


def test_an_old_preview_does_not_hide_a_running_plan():
    value = ui_presentation_snapshot({"status": "awaiting_agent_plan", "agent": {"status": "running"}, "agentReviewPreviews": [{"filename": "old.mp4"}]}, workflow={}, execution={}, output_count=0)
    assert value["key"] == "running" and value["running"]


def test_agent_qc_failure_is_not_presented_as_a_completed_export():
    value = ui_presentation_snapshot({
        "status": "completed",
        "agent": {
            "status": "preview_ready", "successfulSteps": 9, "skippedSteps": 1,
            "settledSteps": 10, "totalSteps": 10,
            "quality": {
                "status": "failed", "passed": False,
                "issues": [{"severity": "error", "message": "检测到持续静止画面。"}],
            },
        },
        "outputVersions": [{
            "previewOnly": True,
            "outputs": [{"filename": "review.mp4", "previewOnly": True}],
        }],
    }, workflow={}, execution={"status": "completed"}, output_count=1)

    assert value["label"] == "审核样片待修正"
    assert value["headline"] == "执行完成 · 质检未通过"
    assert value["primaryActionKey"] == "repair_and_recheck"
    assert value["artifactStage"] == "review_preview"
    assert value["outputCount"] == 0
    assert value["previewCount"] == 1
    assert value["executionProgress"] == {
        "successful": 9, "skipped": 1, "settled": 10, "total": 10,
        "currentStepId": "", "currentStepTitle": "",
    }


def test_review_preview_waits_for_export_until_a_formal_output_exists():
    preview = ui_presentation_snapshot({
        "status": "awaiting_agent_plan",
        "agent": {
            "status": "preview_ready", "completedSteps": 3, "totalSteps": 3,
            "quality": {"status": "passed", "passed": True, "issues": []},
        },
        "agentReviewPreviews": [{"filename": "review.mp4"}],
    }, workflow={}, execution={"status": "waiting_user"}, output_count=0)
    exported = ui_presentation_snapshot({
        "status": "completed",
        "outputVersions": [{
            "previewOnly": False,
            "outputs": [{"filename": "master.mp4", "previewOnly": False}],
        }],
    }, workflow={}, execution={"status": "completed", "outcome": "output_ready"}, output_count=1)

    assert preview["label"] == "审核样片已就绪 · 待确认导出"
    assert preview["primaryActionKey"] == "export_formal"
    assert preview["artifactStage"] == "review_preview"
    assert exported["label"] == "1 条成片已完成"
    assert exported["artifactStage"] == "formal_output"


def test_activating_agent_draft_is_queued_before_worker_submission(monkeypatch, tmp_path):
    from app import main
    from app.api_schemas import ActivateAgentDraftRequest

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    job = {
        "id": "draft_activation",
        "status": "awaiting_agent_instruction",
        "stage": "agent_workspace_ready",
        "agentDraft": True,
        "sourcePath": str(source),
        "videoInfo": {"duration": 120},
        "request": {"entryWorkflow": "agent", "workflowKind": "highlight"},
        "messages": [],
    }
    submitted = {}
    monkeypatch.setattr(main, "jobs", {job["id"]: job})
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "public_job", lambda value: {
        **value, "execution": main.execution_snapshot(value),
    })

    def capture_submission(value):
        submitted.update({"status": value.get("status"), "stage": value.get("stage")})

    monkeypatch.setattr(main, "enqueue_job", capture_submission)
    result = main.activate_agent_draft(
        job["id"],
        ActivateAgentDraftRequest(workflowKind="highlight"),
    )

    assert submitted == {"status": "queued", "stage": "queued"}
    assert result["job"]["execution"]["status"] == "queued"
    assert result["job"]["execution"]["active"] is True


@pytest.mark.parametrize("arguments", [
    {"sourceScopeKind": "invalid"}, {"sourceScopeStart": -1},
    {"sourceScopeEnd": 0}, {"sourceScopeStart": float("nan")},
    {"sourceScopeEnd": float("inf")}, {"sourceScopeStart": 20, "sourceScopeEnd": 10},
])
def test_invalid_source_windows_are_rejected(platform, arguments):
    from app.agent_platform import CORE_TOOL_CATALOG
    tool = next(tool for tool in CORE_TOOL_CATALOG if tool["name"] == "analyze_highlights")
    with pytest.raises(ValueError):
        platform._validate_tool_arguments("source", tool, arguments)


def test_superseded_planning_request_cannot_commit(platform):
    workspace = platform.create_workspace(job_id="isolated")
    workspace["planningRequestId"] = "old"
    platform.store.save("workspaces", {**workspace, "planningRequestId": "new"})
    skill = platform.store.get("skills", "cliptalk-content-extractor")
    before = platform.store.list("plans")
    with pytest.raises(ValueError, match="已失效"):
        platform.persist_plan_result(workspace=workspace, skill=skill, goal="剪成30秒", result={})
    assert platform.store.list("plans") == before


def test_export_rejects_unacknowledged_subtitles_before_starting_background_work(monkeypatch):
    from fastapi import HTTPException
    import app.main as main
    from app.api_schemas import EditSessionRenderRequest
    job = {"id": "audit_export", "status": "completed"}
    session = {"revision": 2}
    monkeypatch.setattr(main, "jobs", {job["id"]: job})
    monkeypatch.setattr(main, "has_active_execution", lambda _: False)
    monkeypatch.setattr(main, "find_edit_session", lambda *_: session)
    monkeypatch.setattr(main, "build_edit_session_render_plan", lambda *_: {})
    monkeypatch.setattr(main, "edit_session_preflight", lambda *_: {"ready": True})
    monkeypatch.setattr(main, "_subtitle_draft_for_job", lambda *_: {"status": "auto_reviewed", "sourceSubtitleAcknowledged": False})
    monkeypatch.setattr(main, "submit_render_task", lambda *_: pytest.fail("must reject before scheduling export"))
    with pytest.raises(HTTPException) as error:
        main.render_edit_session(job["id"], "session", EditSessionRenderRequest(revision=2, subtitleMode="burn", subtitleDraftId="draft"))
    assert error.value.status_code == 409
    assert job["status"] == "completed"
