from __future__ import annotations

import json
from concurrent.futures import Future
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.agent_platform import AgentPlatform, AgentServiceError


HIGHLIGHT_SKILL = """---
name: cliptalk-highlight-director
version: 1.2.0
description: Builds an evidence-backed highlight cut and a review sample.
allowed-tools: inspect_workspace analyze_highlights propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: highlight
---

# Highlight Director
"""


class DeterministicPlanningClient:
    """The workflow compiler, rather than a live model, owns this acceptance test."""

    def plan(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"plan": {"summary": "自动生成高光审核样片", "steps": [{
            "id": "model_placeholder", "title": "模型占位步骤",
            "tool": "inspect_workspace", "arguments": {}, "dependencies": [],
            "expectedOutput": "素材状态", "sideEffect": "read",
        }]}}


class UnavailablePlanningClient:
    def plan(self, _payload: dict[str, Any]) -> dict[str, Any]:
        raise AgentServiceError("Pi Agent 服务不可用：timed out")


@pytest.mark.parametrize(("checkpoint_status", "tool"), [
    ("awaiting_content_confirmation", "discover_people"),
    ("awaiting_confirmation", "analyze_highlights"),
])
def test_autonomous_checkpoint_never_surfaces_user_confirmation(
    checkpoint_status: str, tool: str,
) -> None:
    from app import main

    job_id = "job_agent_autonomous_discovery_checkpoint"
    workspace = {
        "id": "ws_agent_checkpoint", "jobId": job_id,
        "sourceJobId": job_id, "status": "ready",
        "executionMode": "autonomous_review",
    }
    plan = {
        "id": "plan_agent_checkpoint", "status": "running",
        "steps": [{
            "id": "step_discover", "title": "发现画面人物",
            "tool": tool, "status": "waiting_operation",
        }],
    }
    with main.jobs_lock:
        main.jobs[job_id] = {
            "id": job_id, "status": checkpoint_status,
            "stage": "content_search_ready", "actionRequired": {"kind": "select_person"},
        }
    try:
        with patch.object(main, "save_job"):
            main.sync_agent_workspace_to_job(workspace, plan)
        with main.jobs_lock:
            job = main.jobs[job_id]
            assert job["status"] == "awaiting_agent_plan"
            assert job["stage"] == "agent_plan_running"
            assert job["actionRequired"] is None
            assert job["agent"]["executionMode"] == "autonomous_review"
    finally:
        with main.jobs_lock:
            main.jobs.pop(job_id, None)


def test_agent_plan_progress_points_at_failed_step() -> None:
    from app import main

    summary = main._agent_plan_progress({
        "id": "plan_failed",
        "status": "failed",
        "steps": [
            {"id": "s1", "title": "核查素材", "tool": "inspect_workspace", "status": "completed"},
            {"id": "s2", "title": "提取高光候选", "tool": "analyze_highlights", "status": "failed"},
            {"id": "s3", "title": "建立时间线", "tool": "propose_timeline_edit", "status": "pending"},
        ],
    })

    assert summary["currentStepId"] == "s2"
    assert summary["currentStepTitle"] == "提取高光候选"
    assert summary["currentStepTool"] == "analyze_highlights"
    assert summary["currentStepStatus"] == "failed"


def test_retry_rule_allows_failed_highlight_analysis() -> None:
    assert AgentPlatform._replan_force_replay_tools({
        "tool": "analyze_highlights",
        "status": "failed",
        "error": "'job_missing_from_memory'",
    }) == {"analyze_highlights"}


def test_agent_analysis_submit_recovers_job_from_durable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_disk_recovery"
    job = {
        "id": job_id,
        "status": "awaiting_agent_plan",
        "stage": "agent_plan_running",
        "progress": 0.2,
        "request": {"theme": "赛道开场", "autoRecommend": True},
        "sourcePath": str(tmp_path / "source.mp4"),
        "workDirectory": str(tmp_path / "work" / job_id),
        "outputDirectory": str(tmp_path / "outputs" / job_id),
        "createdAt": "2026-09-05T00:00:00+00:00",
        "updatedAt": "2026-09-05T00:00:00+00:00",
        "taskMode": "highlight",
        "workflowKind": "highlight",
        "resolvedTaskKind": "highlight",
    }
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / f"{job_id}.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    calls: list[tuple[str, str, tuple[Any, ...]]] = []
    future: Future[Any] = Future()

    def fake_submit_analysis_task(submitted_job_id: str, target: Any, *args: Any) -> Future[Any]:
        calls.append((submitted_job_id, target.__name__, args))
        return future

    monkeypatch.setattr(main, "job_path", lambda requested_id: jobs_dir / f"{requested_id}.json")
    monkeypatch.setattr(main.job_store, "load_all", lambda: [])
    monkeypatch.setattr(main.job_store, "save", lambda _job, **_options: None)
    monkeypatch.setattr(main, "submit_analysis_task", fake_submit_analysis_task)

    with main.jobs_lock:
        main.jobs.pop(job_id, None)
        main.cancel_events.pop(job_id, None)
    try:
        result = main.submit_workflow_analysis(job_id, "highlight_analysis", {"targetSeconds": 60})
        assert result is future
        assert calls == [(job_id, "run_job", (job_id,))]
        with main.jobs_lock:
            restored = main.jobs[job_id]
        assert restored["analysisOperation"]["kind"] == "highlight_analysis"
        assert restored["analysisOperation"]["payload"] == {"targetSeconds": 60}
    finally:
        with main.jobs_lock:
            main.jobs.pop(job_id, None)
            main.cancel_events.pop(job_id, None)


def test_agent_review_preview_is_projected_to_public_job(tmp_path: Path) -> None:
    from app import main

    job_id = "job_agent_review_projection"
    workspace = {
        "id": "ws_agent_review_projection",
        "jobId": job_id,
        "sourceJobId": job_id,
        "status": "preview_ready",
        "executionMode": "autonomous_review",
    }
    plan = {
        "id": "plan_agent_review_projection",
        "status": "preview_ready",
        "skillId": "cliptalk-highlight-director",
        "steps": [{
            "id": "render",
            "title": "准备低码率审阅样片",
            "tool": "render_review_preview",
            "status": "completed",
            "result": {"artifact": {
                "kind": "review_preview_batch",
                "previewOnly": True,
                "previews": [{
                    "kind": "review_preview",
                    "sessionId": "edit_session_review",
                    "revision": 2,
                    "previewUrl": "/api/jobs/job_agent_review_projection/edit-sessions/edit_session_review/preview?r=2",
                    "title": "高光审核样片",
                    "duration": 56.4,
                    "previewOnly": True,
                }],
            }},
        }],
    }
    job = {
        "id": job_id,
        "status": "awaiting_agent_plan",
        "stage": "agent_plan_running",
        "workDirectory": str(tmp_path / "work"),
        "outputDirectory": str(tmp_path / "outputs"),
        "outputVersions": [],
        "outputs": [],
        "editSessions": [{
            "id": "edit_session_review", "revision": 2, "duration": 56.4,
            "previewStatus": "ready",
            "clips": [
                {"id": "clip_1", "title": "开场", "sourceStart": 4, "sourceEnd": 14, "duration": 10},
                {"id": "clip_2", "title": "重点", "sourceStart": 20, "sourceEnd": 30, "duration": 10},
            ],
            "preflight": {
                "ready": True, "errorCount": 0, "warningCount": 0,
                "unacknowledgedWarningCount": 0, "issues": [],
            },
        }],
    }
    with patch.dict(main.jobs, {job_id: job}, clear=False), patch.object(main, "save_job") as save:
        main.sync_agent_workspace_to_job(workspace, plan)
        public = main.public_job(job)

    assert job["status"] == "awaiting_agent_plan"
    assert job["stage"] == "agent_preview_review"
    assert job["actionRequired"] == "review_preview"
    assert job["agentReviewPreviews"][0]["outputKind"] == "agent_review_preview"
    assert job["agentReviewPreviews"][0]["sourceEditSessionId"] == "edit_session_review"
    assert job["agentReviewPreviews"][0]["clipCount"] == 2
    assert job["agentReviewPreviews"][0]["segments"][0]["start"] == 4
    assert job["agentReviewPreviews"][0]["qualityStatus"] == "passed"
    assert public["agentReviewPreviews"][0]["title"] == "高光审核样片"
    assert public["agentReviewPreviews"][0]["previewOnly"] is True
    assert public["outputVersions"] == []
    save.assert_called_once_with(job)


def test_opening_existing_job_backfills_agent_review_preview_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_review_projection_backfill"
    workspace = {
        "id": "ws_agent_review_projection_backfill",
        "jobId": job_id,
        "sourceJobId": job_id,
        "status": "preview_ready",
        "executionMode": "autonomous_review",
        "activePlanId": "plan_agent_review_projection_backfill",
    }
    plan = {
        "id": "plan_agent_review_projection_backfill",
        "status": "preview_ready",
        "skillId": "cliptalk-highlight-director",
        "steps": [{
            "id": "render",
            "title": "准备低码率审阅样片",
            "tool": "render_review_preview",
            "status": "completed",
            "result": {"artifact": {
                "kind": "review_preview_batch",
                "previewOnly": True,
                "previews": [{
                    "kind": "review_preview",
                    "sessionId": "edit_session_backfill",
                    "revision": 1,
                    "previewUrl": "/api/jobs/job_agent_review_projection_backfill/edit-sessions/edit_session_backfill/preview?r=1",
                    "title": "旧任务审核样片",
                    "duration": 42.0,
                    "previewOnly": True,
                }],
            }},
        }],
    }
    job = {
        "id": job_id,
        "status": "completed",
        "stage": "agent_plan_finished",
        "workDirectory": str(tmp_path / "work"),
        "outputDirectory": str(tmp_path / "outputs"),
        "outputVersions": [],
        "outputs": [],
    }
    monkeypatch.setattr(main.agent_platform, "workspace_for_job", lambda requested_id: workspace if requested_id == job_id else None)
    monkeypatch.setattr(main.agent_platform.store, "get", lambda kind, requested_id: plan if kind == "plans" and requested_id == plan["id"] else None)

    with patch.dict(main.jobs, {job_id: job}, clear=False), patch.object(main, "save_job") as save:
        response = main.get_job(job_id)

    public = response["job"]
    assert job["agentReviewPreviews"][0]["title"] == "旧任务审核样片"
    assert public["agentReviewPreviews"][0]["previewUrl"].endswith("/preview?r=1")
    assert main.job_has_visible_review_result(job) is True
    save.assert_called_once_with(job)


def test_agent_review_projection_uses_rendered_content_warnings_from_current_revision() -> None:
    from app import main

    plan = {
        "id": "plan_rendered_warning",
        "status": "preview_ready",
        "steps": [{
            "id": "render", "status": "completed",
            "result": {"artifact": {
                "kind": "review_preview", "sessionId": "edit_rendered_warning",
                "revision": 3, "previewUrl": "/preview/rendered-warning.mp4",
            }},
        }],
    }
    warning = {
        "severity": "warning", "code": "content_render_sample_unverified",
        "message": "成片抽检发现未满足或无法确认原要求的画面，请检查问题片段",
        "evidence": {"ranges": [{"start": 0, "end": 12}]},
    }
    job = {"editSessions": [{
        "id": "edit_rendered_warning", "revision": 3, "duration": 12,
        "clips": [{"id": "clip", "sourceStart": 0, "sourceEnd": 12, "duration": 12}],
        "preflight": {"ready": True, "warningCount": 0, "issues": []},
        "contentVerificationRevision": 3,
        "contentVerification": {"status": "needs_review", "passed": False, "issues": [warning]},
    }]}

    preview = main._agent_review_previews_from_plan(plan, job)[0]

    assert preview["qualityStatus"] == "needs_review"
    assert preview["preflight"]["issues"][-1]["code"] == "content_render_sample_unverified"
    assert preview["preflight"]["unacknowledgedWarningCount"] == 1


def test_agent_planning_context_counts_review_preview_as_visible_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_review_context"
    job = {
        "id": job_id,
        "status": "completed",
        "stage": "agent_plan_finished",
        "workDirectory": str(tmp_path / "work"),
        "outputDirectory": str(tmp_path / "outputs"),
        "outputVersions": [],
        "outputs": [],
        "agentReviewPreviews": [{
            "kind": "review_preview",
            "outputKind": "agent_review_preview",
            "title": "审核样片",
            "previewUrl": "/api/jobs/job_agent_review_context/edit-sessions/edit_session_context/preview?r=1",
            "previewOnly": True,
        }],
    }
    monkeypatch.setattr(main.agent_platform, "workspace_for_job", lambda requested_id: None)

    with patch.dict(main.jobs, {job_id: job}, clear=False):
        context = main.agent_planning_context(job_id)

    assert context["editing"]["hasOutputs"] is True
    assert main._workflow_routing_context(job)["hasOutputs"] is True


def test_autonomous_agent_reaches_review_sample_without_intermediate_user_action(
    tmp_path: Path,
) -> None:
    """Accept the plan once, then verify that Agent stops only at review-ready."""
    platform = AgentPlatform(
        data_root=tmp_path,
        service_url="http://agent.invalid",
        model_config_resolver=lambda: {"model": "deterministic-test"},
    )
    platform.client = DeterministicPlanningClient()  # type: ignore[assignment]
    platform.install_skill(
        markdown=HIGHLIGHT_SKILL, source="builtin", status="enabled",
    )
    platform.configure_planning_context_provider(lambda job_id: {
        "jobId": job_id,
        "evidence": {"hasCandidates": True, "candidateCount": 3},
        "editing": {"hasActiveSession": False, "hasOutputs": False},
    })

    review_future: Future[dict[str, Any]] = Future()
    calls: list[dict[str, Any]] = []

    def dispatch(
        workspace: dict[str, Any], tool: str, arguments: dict[str, Any],
    ) -> dict[str, Any]:
        calls.append({
            "tool": tool,
            "arguments": arguments,
            "executionMode": workspace.get("executionMode"),
        })
        if tool == "propose_timeline_edit":
            return {
                "actionRequired": False,
                "artifact": {"kind": "timeline_proposal", "proposalId": "proposal_1"},
            }
        if tool == "confirm_timeline_edit":
            return {
                "artifact": {
                    "kind": "applied_timeline_batch",
                    "variants": [{"sessionId": "edit_1", "revision": 1}],
                },
            }
        if tool == "render_review_preview":
            return {
                "accepted": True,
                "operationId": "job_auto:agent_review_batch:1",
                "future": review_future,
            }
        return {"artifact": {"kind": "workspace_snapshot"}}

    platform.configure_tool_dispatcher(dispatch)
    workspace = platform.create_workspace(job_id="job_auto")
    plan = platform.create_plan(
        workspace_id=workspace["id"],
        skill_id="cliptalk-highlight-director",
        goal="剪成 60 秒高光成片",
        execution_mode="autonomous_review",
    )

    # Planning is still hash-bound: no media work starts before this one approval.
    assert plan["status"] == "awaiting_confirmation"
    assert calls == []
    waiting = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])

    assert waiting["status"] == "running"
    assert waiting["steps"][-1]["status"] == "waiting_operation"
    assert [item["tool"] for item in calls] == [
        "inspect_workspace",
        "propose_timeline_edit",
        "confirm_timeline_edit",
        "render_review_preview",
    ]
    assert all(item["executionMode"] == "autonomous_review" for item in calls)
    assert all(step["status"] != "action_required" for step in waiting["steps"])

    # Finishing the background proxy render must surface a review artifact,
    # never a formal output or another timeline-confirmation prompt.
    review_future.set_result({
        "artifact": {
            "kind": "review_preview_batch",
            "previewOnly": True,
            "previews": [{
                "kind": "review_preview",
                "sessionId": "edit_1",
                "revision": 1,
                "previewUrl": "/api/jobs/job_auto/edit-sessions/edit_1/preview?r=1",
                "previewOnly": True,
            }],
        },
    })

    completed = platform.store.get("plans", plan["id"])
    assert completed is not None
    assert completed["status"] == "preview_ready"
    assert all(step["status"] == "completed" for step in completed["steps"])
    artifact = completed["steps"][-1]["result"]["artifact"]
    assert artifact["kind"] == "review_preview_batch"
    assert artifact["previewOnly"] is True
    assert artifact["previews"][0]["previewOnly"] is True

    events = platform.store.events_after(workspace["id"])
    assert "action.required" not in {event["type"] for event in events}
    assert events[-1]["type"] == "preview.ready"


def test_managed_skill_uses_deterministic_plan_when_planning_service_times_out(
    tmp_path: Path,
) -> None:
    platform = AgentPlatform(
        data_root=tmp_path, service_url="http://agent.invalid",
        model_config_resolver=lambda: {"model": "offline"}, timeout_seconds=17,
    )
    assert platform.client.timeout_seconds == 17
    platform.client = UnavailablePlanningClient()  # type: ignore[assignment]
    platform.install_skill(markdown=HIGHLIGHT_SKILL, source="builtin", status="enabled")
    platform.configure_planning_context_provider(lambda job_id: {
        "jobId": job_id,
        "evidence": {"hasCandidates": True, "candidateCount": 2},
        "editing": {"hasActiveSession": False, "hasOutputs": False},
    })
    workspace = platform.create_workspace(job_id="job_fallback")

    plan = platform.create_plan(
        workspace_id=workspace["id"], skill_id="cliptalk-highlight-director",
        goal="剪成 60 秒高光审核样片", execution_mode="autonomous_review",
    )

    assert plan["status"] == "awaiting_confirmation"
    assert plan["planningSource"] == "deterministic_fallback"
    assert "timed out" in plan["planningWarning"]
    assert [step["tool"] for step in plan["steps"]] == [
        "inspect_workspace", "propose_timeline_edit",
        "confirm_timeline_edit", "render_review_preview",
    ]
    assert "planningRequestId" not in platform.store.get("workspaces", workspace["id"])
    assert "planning.fallback" in {
        event["type"] for event in platform.store.events_after(workspace["id"])
    }
