from __future__ import annotations

from pathlib import Path

from tools.validate_agent_scenarios import (
    evaluate_plan_contract,
    evaluate_terminal_state,
    load_manifest,
    markdown_report,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "agent_user_scenarios.json"
CAPABILITY_MANIFEST = ROOT / "tests" / "fixtures" / "agent_capability_questions.json"


def scenario(**overrides):
    value = {
        "id": "case",
        "video": "cest-video/访谈.mp4",
        "prompt": "剪成 60 秒访谈精华",
        "expectedOutcome": "preview_ready",
        "expectedSkillAnyOf": ["cliptalk-interview-editor"],
        "expectedTerms": ["访谈"],
        "targetDuration": {"minimum": 54, "maximum": 66},
        "expectedAspect": "9:16",
    }
    value.update(overrides)
    return value


def ready_plan(**overrides):
    value = {
        "id": "plan_1",
        "skillId": "cliptalk-interview-editor",
        "executionMode": "autonomous_review",
        "status": "preview_ready",
        "steps": [
            {
                "id": "timeline",
                "tool": "confirm_timeline_edit",
                "title": "应用访谈时间线",
                "status": "completed",
                "attempts": 1,
                "result": {"artifact": {"kind": "applied_timeline_batch"}},
            },
            {
                "id": "preview",
                "tool": "render_review_preview",
                "title": "生成访谈审核样片",
                "status": "completed",
                "attempts": 1,
                "result": {
                    "artifact": {
                        "kind": "review_preview_batch",
                        "previews": [{
                            "kind": "review_preview",
                            "duration": 60,
                            "previewUrl": "/review.mp4",
                            "previewOnly": True,
                        }],
                    },
                },
            },
        ],
    }
    value.update(overrides)
    return value


def ready_job(**overrides):
    value = {
        "id": "job_1",
        "videoInfo": {"width": 576, "height": 1024},
        "activeEditSessionId": "edit_1",
        "editSessions": [{
            "id": "edit_1", "duration": 60,
            "clips": [{"id": "clip_1", "title": "访谈回答"}],
            "schedule": [{"clipId": "clip_1", "outputStart": 0, "outputEnd": 60}],
        }],
        "agentReviewPreviews": [{
            "kind": "review_preview",
            "outputKind": "agent_review_preview",
            "duration": 60,
            "previewUrl": "/review.mp4",
            "previewOnly": True,
        }],
        "outputs": [],
        "outputVersions": [],
    }
    value.update(overrides)
    return value


def test_manifest_covers_every_cest_video_with_normal_and_pressure_cases() -> None:
    defaults, scenarios = load_manifest(MANIFEST)
    assert defaults["phaseTimeoutSeconds"] == 1800
    assert len(scenarios) == 12
    by_video: dict[str, list[dict]] = {}
    for item in scenarios:
        by_video.setdefault(item["video"], []).append(item)
    assert set(by_video) == {
        "cest-video/产品宣传.mp4",
        "cest-video/人物对话.mp4",
        "cest-video/唱歌.mp4",
        "cest-video/小米产品.mp4",
        "cest-video/直播pk_V004_手动合成-情绪集中版_·_正式导出_01.mp4",
        "cest-video/访谈.mp4",
    }
    assert all(len(items) == 2 for items in by_video.values())
    assert all(any(item["kind"] == "normal" for item in items) for items in by_video.values())


def test_capability_question_manifest_covers_agent_and_skill_regressions() -> None:
    defaults, scenarios = load_manifest(CAPABILITY_MANIFEST)
    assert defaults["executionMode"] == "autonomous_review"
    assert len(scenarios) == 54
    assert len({item["id"] for item in scenarios}) == 54
    # The real acceptance videos are intentionally not published with a
    # release. Keep the manifest safe and portable without requiring those
    # local media files during the ordinary repository test suite.
    video_paths = [Path(item["video"]) for item in scenarios]
    assert all(path.parts and not path.is_absolute() and ".." not in path.parts for path in video_paths)
    assert all(item.get("expectedSkillAnyOf") for item in scenarios)

    skill_ids = {skill for item in scenarios for skill in item["expectedSkillAnyOf"]}
    assert {
        "cliptalk-content-extractor",
        "cliptalk-highlight-director",
        "cliptalk-shortform-hook-director",
        "cliptalk-interview-editor",
        "cliptalk-person-editor",
        "cliptalk-speaker-editor",
    } <= skill_ids
    kinds = {str(item.get("kind") or "") for item in scenarios}
    assert {"normal", "constraint", "cross_modal", "no_match"} <= kinds
    assert "ui_regression" not in kinds
    assert {"isolation", "capability_guard"} <= kinds
    assert any(item.get("expectedAspect") == "9:16" for item in scenarios)
    assert any(item.get("expectedAspect") == "1:1" for item in scenarios)
    assert {item.get("skillId") for item in scenarios if item.get("skillId")} == {
        "cliptalk-audio-polish-mixer",
        "cliptalk-broll-overlay-editor",
        "cliptalk-caption-layout-director",
        "cliptalk-cover-intro-composer",
        "cliptalk-dynamic-reframe-director",
        "cliptalk-edit-diagnostics",
        "cliptalk-graphics-packager",
        "cliptalk-local-draft-exporter",
        "cliptalk-local-motion-renderer",
        "cliptalk-multi-topic-assembler",
        "cliptalk-platform-delivery-exporter",
        "cliptalk-smart-reframe",
        "cliptalk-source-provenance-guard",
        "cliptalk-subtitle-editor",
    }


def test_capability_question_runner_uses_dedicated_manifest_by_default(monkeypatch) -> None:
    import tools.run_agent_capability_questions as runner

    captured: list[list[str]] = []

    def fake_validate(args):
        captured.append(args)
        return 0

    monkeypatch.setattr(runner, "validate_agent_scenarios_main", fake_validate)
    assert runner.main(["--dry-run"]) == 0
    assert captured == [["--manifest", str(CAPABILITY_MANIFEST), "--dry-run"]]


def test_capability_question_runner_respects_explicit_manifest(monkeypatch) -> None:
    import tools.run_agent_capability_questions as runner

    captured: list[list[str]] = []

    def fake_validate(args):
        captured.append(args)
        return 0

    monkeypatch.setattr(runner, "validate_agent_scenarios_main", fake_validate)
    assert runner.main(["--manifest", "custom.json", "--dry-run"]) == 0
    assert captured == [["--manifest", "custom.json", "--dry-run"]]

    captured.clear()
    assert runner.main(["--manifest=custom.json", "--dry-run"]) == 0
    assert captured == [["--manifest=custom.json", "--dry-run"]]


def test_plan_contract_rejects_wrong_skill_and_formal_export() -> None:
    plan = ready_plan(
        skillId="cliptalk-person-editor",
        steps=[{
            "id": "export", "tool": "render_final", "sideEffect": "formal_export",
            "status": "pending", "attempts": 0,
        }],
    )
    issues = evaluate_plan_contract(plan, scenario())
    codes = {issue.code for issue in issues}
    assert codes == {
        "plan.skill_mismatch",
        "plan.formal_export_included",
        "plan.formal_side_effect",
    }


def test_plan_contract_rejects_user_forbidden_tools() -> None:
    plan = ready_plan(steps=[{
        "id": "cover", "tool": "propose_cover_candidates", "sideEffect": "analysis",
        "status": "pending", "attempts": 0,
    }])

    issues = evaluate_plan_contract(
        plan,
        scenario(
            expectedSkillAnyOf=["cliptalk-content-extractor"],
            forbiddenTools=["propose_cover_candidates", "render_review_preview"],
        ),
    )

    assert "plan.forbidden_tool" in {issue.code for issue in issues}


def test_ready_preview_passes_duration_aspect_and_confirmation_contract() -> None:
    plan = ready_plan()
    job = ready_job()
    workspace = {"id": "ws_1", "jobId": "job_1"}
    issues = evaluate_terminal_state(plan, job, workspace, scenario(), [])
    assert issues == []


def test_ready_preview_requires_user_visible_result_projection() -> None:
    plan = ready_plan()
    job = ready_job(agentReviewPreviews=[], agentPreviewOutputs=[], outputs=[], outputVersions=[])
    workspace = {"id": "ws_1", "jobId": "job_1"}

    issues = evaluate_terminal_state(plan, job, workspace, scenario(), [])

    assert "artifact.preview_not_projected" in {issue.code for issue in issues}


def test_constraint_scenario_accepts_typed_no_result_without_artifacts() -> None:
    plan = ready_plan(status="no_result", steps=[{
        "id": "review", "tool": "review_content_evidence", "title": "检查必需类别",
        "status": "completed", "attempts": 1,
        "result": {"artifact": {
            "kind": "no_match", "reasonCode": "missing_required_categories",
            "message": "洗衣机换新只有可能相关证据，不足以自动成片。",
        }},
    }])
    job = ready_job(activeEditSessionId=None, editSessions=[])

    issues = evaluate_terminal_state(
        plan, job, {"id": "ws_1", "jobId": "job_1"},
        scenario(expectedOutcome="preview_or_clear_limitation"), [],
    )

    assert issues == []


def test_no_duration_scenario_rejects_hidden_target_even_when_no_result_is_typed() -> None:
    plan = ready_plan(
        status="no_result",
        brief={"targetSeconds": 30},
        steps=[{
            "id": "timeline", "tool": "propose_timeline_edit", "status": "completed",
            "attempts": 1, "arguments": {"targetSeconds": 30},
            "result": {"artifact": {
                "kind": "no_match", "reasonCode": "duration_constraint_unmet",
                "message": "无法收敛到 30 秒。",
            }},
        }],
    )
    job = ready_job(
        activeEditSessionId=None, editSessions=[],
        request={"targetSeconds": "auto", "totalTargetSeconds": None},
    )

    issues = evaluate_terminal_state(
        plan, job, {"id": "ws_1", "jobId": "job_1"},
        scenario(
            expectedOutcome="preview_or_clear_limitation", expectedAspect="",
            targetDuration={}, forbidImplicitDuration=True,
        ),
        [],
    )

    assert "plan.implicit_duration" in {issue.code for issue in issues}


def test_evidence_only_search_completion_does_not_require_video_preview() -> None:
    plan = ready_plan(steps=[
        {
            "id": "inspect", "tool": "inspect_workspace", "title": "检查素材",
            "status": "completed", "attempts": 1,
        },
        {
            "id": "search", "tool": "search_content", "title": "检索空调内容",
            "status": "completed", "attempts": 1,
            "result": {"artifact": {
                "kind": "content_search_result", "jobId": "job_1", "query": "空调新老替换",
            }},
        },
    ])
    job = ready_job(activeEditSessionId=None, editSessions=[])

    issues = evaluate_terminal_state(
        plan, job, {"id": "ws_1", "jobId": "job_1"},
        scenario(
            expectedOutcome="preview_or_clear_limitation",
            targetDuration={}, expectedAspect="", expectedTerms=["空调", "新老替换"],
        ),
        [],
    )

    assert issues == []


def test_format_only_passthrough_keeps_inherited_freeze_as_warning() -> None:
    plan = ready_plan(
        brief={"formatOnly": True},
        steps=[{
            "id": "qc", "tool": "run_delivery_qc", "title": "检查画幅预览",
            "status": "completed", "attempts": 1,
            "result": {"artifact": {
                "kind": "delivery_qc_report",
                "reports": [{"issues": [{
                    "code": "freeze_frames", "severity": "error",
                    "message": "检测到持续静止画面。", "evidence": {"longestSeconds": 5},
                }]}],
            }},
        }],
    )

    issues = evaluate_terminal_state(
        plan, ready_job(), {"id": "ws_1", "jobId": "job_1"}, scenario(), [],
    )

    freeze = next(issue for issue in issues if issue.code == "qc.freeze_frames")
    assert freeze.severity == "warning"


def test_unexpected_confirmation_retry_and_bad_preview_are_reported() -> None:
    plan = ready_plan(
        status="action_required",
        steps=[{
            "id": "timeline", "tool": "confirm_timeline_edit", "title": "确认时间线",
            "status": "action_required", "attempts": 3,
        }],
    )
    job = ready_job(
        videoInfo={"width": 1024, "height": 576},
        editSessions=[{"id": "edit_1", "duration": 12, "clips": [], "schedule": []}],
        outputs=[{"filename": "formal.mp4", "duration": 12, "previewOnly": False}],
    )
    issues = evaluate_terminal_state(
        plan, job, {"id": "ws_1", "jobId": "job_1"}, scenario(),
        [{"planStatus": "action_required"}],
    )
    codes = {issue.code for issue in issues}
    assert {
        "execution.review_not_ready",
        "execution.unexpected_confirmation",
        "execution.replan_loop",
        "artifact.formal_output_created",
    } <= codes


def test_preview_only_top_level_output_inherits_active_preview_version() -> None:
    job = ready_job(
        outputs=[{"filename": "review.mp4", "duration": 60}],
        activeOutputVersionId="version_preview",
        outputVersions=[{
            "id": "version_preview", "previewOnly": True, "variantKind": "independent",
            "outputs": [{"filename": "review.mp4", "duration": 60}],
        }],
    )
    issues = evaluate_terminal_state(
        ready_plan(), job, {"id": "ws_1", "jobId": "job_1"}, scenario(), [],
    )
    assert "artifact.formal_output_created" not in {issue.code for issue in issues}


def test_explicit_formal_output_is_reported_even_when_nested() -> None:
    job = ready_job(
        outputs=[],
        outputVersions=[{
            "id": "version_formal", "previewOnly": False, "variantKind": "formal_export",
            "outputs": [{"filename": "formal.mp4", "duration": 60}],
        }],
    )
    issues = evaluate_terminal_state(
        ready_plan(), job, {"id": "ws_1", "jobId": "job_1"}, scenario(), [],
    )
    assert "artifact.formal_output_created" in {issue.code for issue in issues}


def test_failed_tool_error_is_reported_separately_from_terminal_status() -> None:
    plan = ready_plan(
        status="failed",
        steps=[{
            "id": "timeline", "tool": "propose_timeline_edit", "title": "建立时间线",
            "status": "failed", "attempts": 1, "error": "'int' object is not iterable",
        }],
    )
    issues = evaluate_terminal_state(
        plan, ready_job(), {"id": "ws_1", "jobId": "job_1"}, scenario(), [],
    )
    failure = next(issue for issue in issues if issue.code == "execution.step_failed")
    assert failure.evidence["tool"] == "propose_timeline_edit"
    assert "int" in failure.evidence["error"]


def test_no_match_must_stop_without_timeline_or_preview() -> None:
    no_match = scenario(
        expectedOutcome="graceful_no_match",
        targetDuration={"minimum": 27, "maximum": 33},
        expectedAspect="",
    )
    plan = ready_plan(
        status="no_result",
        error="内容检索没有生成可用于自动编排的有效候选",
        steps=[{
            "id": "search", "tool": "review_content_evidence", "status": "completed",
            "attempts": 1, "result": {"artifact": {
                "kind": "no_match", "reasonCode": "no_match", "candidateCount": 0,
            }},
        }],
    )
    clean_job = ready_job(activeEditSessionId="", editSessions=[], agentReviewPreviews=[])
    workspace = {"id": "ws_1", "jobId": "job_1"}
    issues = evaluate_terminal_state(plan, clean_job, workspace, no_match, [])
    assert issues == []

    dirty_job = ready_job()
    dirty_issues = evaluate_terminal_state(plan, dirty_job, workspace, no_match, [])
    assert "execution.irrelevant_artifact" in {issue.code for issue in dirty_issues}


def test_markdown_report_contains_jobs_and_issue_evidence() -> None:
    report = {
        "startedAt": "2026-09-01T00:00:00+00:00",
        "finishedAt": "2026-09-01T01:00:00+00:00",
        "passed": False,
        "summary": {"total": 1, "passed": 0, "errors": 1, "warnings": 0, "info": 0},
        "preflightIssues": [],
        "scenarios": [{
            "id": "case", "video": "cest-video/访谈.mp4", "prompt": "剪成访谈精华",
            "passed": False, "finalJobId": "job_1", "elapsedSeconds": 12.3,
            "issues": [{
                "severity": "error", "code": "execution.timeout", "phase": "execution",
                "message": "执行超时", "evidence": {"stage": "search"}, "recommendation": "检查任务",
            }],
        }],
    }
    text = markdown_report(report)
    assert "`job_1`" in text
    assert "`execution.timeout`" in text
    assert '"stage": "search"' in text
    assert "剪成访谈精华" in text
