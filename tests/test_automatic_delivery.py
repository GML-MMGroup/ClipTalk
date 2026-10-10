from concurrent.futures import Future
from pathlib import Path

import pytest

from app.agent_platform import AgentPlatform
from app.automatic_delivery import blocking_quality_issues, delivery_session_ids, may_auto_approve


@pytest.fixture
def platform(tmp_path):
    service = AgentPlatform(data_root=tmp_path, service_url="http://agent.invalid",
                            model_config_resolver=lambda: {"model": "test"})
    service.install_skill(markdown="""---
name: cliptalk-highlight-director
version: 1.0.0
description: Creates a highlight video from reliable evidence.
allowed-tools: inspect_workspace analyze_highlights propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
---
# Highlight
""", source="builtin", status="enabled")
    service.configure_planning_context_provider(lambda _: {
        "evidence": {"hasCandidates": True, "candidateCount": 2},
        "editing": {"hasActiveSession": False, "hasOutputs": False},
    })
    class Client:
        def plan(self, _):
            return {"plan": {"summary": "测试"}}
    service.client = Client()
    return service


def create(platform, mode="automatic_delivery"):
    ws = platform.create_workspace(job_id="job_auto")
    return platform.create_plan(workspace_id=ws["id"], skill_id="cliptalk-highlight-director",
                                goal="剪成60秒高光视频", execution_mode=mode)


def test_single_submission_delivers_and_checks_without_approval(platform):
    calls = []
    delivery = Future()
    def dispatch(ws, tool, args):
        calls.append(tool)
        assert ws["executionMode"] == "automatic_delivery"
        if tool == "deliver_current_plan":
            return {"future": delivery, "operationId": "delivery_1"}
        return {"artifact": {"kind": "delivery_qc_report", "reports": [], "passed": True}}
    platform.configure_tool_dispatcher(dispatch)
    plan = create(platform)
    assert plan["status"] == "running"
    assert calls[-1] == "deliver_current_plan"
    assert plan["approval"]["planHash"] == plan["planHash"]
    delivery.set_result({"artifact": {"kind": "delivery_master", "outputs": [{"filename": "final.mp4"}]}})
    final = platform.store.get("plans", plan["id"])
    assert final["status"] == "completed"
    assert calls[-1] == "run_delivery_qc"


def test_legacy_mode_does_not_start_or_gain_export_authority(platform):
    platform.configure_tool_dispatcher(lambda *_: pytest.fail("must wait for approval"))
    plan = create(platform, "autonomous_review")
    assert plan["status"] == "awaiting_confirmation"
    assert "deliver_current_plan" not in [s["tool"] for s in plan["steps"]]


@pytest.mark.parametrize("goal", ["剪成15秒视频，不加字幕，不加封面", "剪辑高光，不添加字幕，不做封面"])
def test_explicitly_excluded_subtitles_and_cover_are_not_generated(goal):
    brief = AgentPlatform._editing_brief(goal, {})
    assert not brief["subtitleRequested"]
    assert not brief["coverRequested"]


def test_dialogue_subtitles_and_motion_title_are_literal_requirements():
    assert AgentPlatform._editing_brief("剪成15秒，添加对白字幕", {})["subtitleRequested"]
    brief = AgentPlatform._editing_brief("为当前成片增加1秒的动态图文片头，标题写：新品发布", {})
    assert brief["graphicsText"] == "新品发布"
    assert brief["motionIntroDurationSeconds"] == 1
    assert brief["targetSeconds"] is None
    assert not brief["coverIntroRequested"]
    brief = AgentPlatform._editing_brief("剪成15秒，添加对白字幕，生成16:9封面，封面文字：认真对话", {})
    assert brief["subtitleRequested"] and brief["coverRequested"]
    assert not brief["graphicsRequested"]
    brief = AgentPlatform._editing_brief("生成16:9封面。把封面放在视频开头1秒。", {})
    assert brief["coverIntroRequested"]
    assert brief["coverIntroDurationSeconds"] == 1


def test_ambiguous_person_in_automatic_mode_asks_once_instead_of_ending(monkeypatch):
    from app import main
    job_id = "test_auto_ambiguous_person"
    monkeypatch.setitem(main.jobs, job_id, {"id": job_id, "revision": 1, "workflowKind": "person_edit",
                                          "request": {}, "videoInfo": {"duration": 10}})
    monkeypatch.setattr(main, "_load_content_person_index", lambda _: {"personTracks": []})
    monkeypatch.setattr(main, "_content_person_catalog", lambda *_: [{"id": "p1"}, {"id": "p2"}])
    monkeypatch.setattr(main, "_match_person_catalog_by_visual_description", lambda *_, **__: (
        [], {"reliablePersonIds": [], "uncertainPersonIds": ["p1", "p2"]}))
    result = main.dispatch_agent_tool({"jobId": job_id, "executionMode": "automatic_delivery"},
                                      "select_people", {"description": "穿黑衣服的人"})
    assert result["actionRequired"]
    assert result["action"] == "identity_selection"
    assert "2 个候选" in result["message"]


def test_automatic_cover_intro_checks_body_plus_intro_without_reframing_video(platform):
    goal = "剪成15秒视频，生成16:9封面。把封面放在视频开头1秒。"
    compiled = platform._compile_profile_plan({}, skill=platform.store.get("skills", "cliptalk-highlight-director"),
                                               goal=goal, context={}, execution_mode="automatic_delivery")
    qc = next(s for s in compiled["steps"] if s["tool"] == "run_delivery_qc")["arguments"]
    assert qc["requireCoverIntro"]
    # 封面片头默认合入且计入总时长：正文 14 秒 + 封面片头 1 秒 = 成片 15 秒。
    assert qc["targetSeconds"] == 15
    assert "expectedAspect" not in qc


def test_direct_delivery_skips_only_unrequested_unneeded_review(platform):
    skill = platform.store.get("skills", "cliptalk-highlight-director")
    for goal, direct in [("剪成30秒高光视频", True), ("剪成30秒高光并生成审核样片", False), ("剪成30秒并添加字幕", False)]:
        compiled = platform._compile_profile_plan({}, skill=skill, goal=goal, context={}, execution_mode="automatic_delivery")
        tools = [step["tool"] for step in compiled["steps"]]
        assert ("prepare_delivery_timeline" in tools) is direct
        assert ("render_review_preview" in tools) is (not direct)
        assert "deliver_current_plan" in tools


def test_inclusive_budget_is_shared_by_plan_and_qc(platform):
    compiled = platform._compile_profile_plan({}, skill=platform.store.get("skills", "cliptalk-highlight-director"),
        goal="剪成总时长15秒，包含1秒封面片头，允许误差0.5秒", context={}, execution_mode="automatic_delivery")
    edit = next(step for step in compiled["steps"] if step["tool"] == "propose_timeline_edit")["arguments"]
    qc = next(step for step in compiled["steps"] if step["tool"] == "run_delivery_qc")["arguments"]
    assert edit["targetSeconds"] == 14
    assert qc["targetSeconds"] == 15
    assert edit["toleranceSeconds"] == qc["toleranceSeconds"] == .5


@pytest.mark.parametrize("placement", ["把封面放在视频开头1秒", "将封面加到成片开头一秒", "封面放到开头1秒"])
def test_cover_placement_duration_never_limits_source_selection(placement):
    brief = AgentPlatform._editing_brief(f"剪成15秒视频，添加对白字幕，生成封面。{placement}。", {})
    assert brief["sourceRange"] is None
    assert brief["targetSeconds"] == 15
    explicit = AgentPlatform._source_time_range(f"剪源片开头5秒，{placement}", {})
    assert explicit["end"] == 5
    explicit = AgentPlatform._source_time_range(f"{placement}，剪源片开头5秒", {})
    assert explicit["end"] == 5


@pytest.mark.parametrize("followup", [False, True])
def test_automatic_cover_intro_has_one_final_render_and_quality_check(platform, followup):
    root = Path(__file__).resolve().parents[1]
    for name in ("cliptalk-cover-director", "cliptalk-cover-intro-composer", "cliptalk-delivery-qc"):
        platform.install_skill(markdown=(root / "skills" / name / "SKILL.md").read_text(),
                               source="builtin", status="enabled")
    goal = ("为当前成片生成封面" if followup else "剪成15秒视频，添加对白字幕，生成封面") + "，把封面放在视频开头1秒，并检查成片质量。"
    context = {"editing": {"hasOutputs": followup, "hasActiveSession": followup}}
    skill = platform.store.get("skills", "cliptalk-cover-intro-composer" if followup else "cliptalk-highlight-director")
    brief = platform._editing_brief(goal, context)
    compiled = platform._compile_profile_plan({}, skill=skill, goal=goal, context=context,
        skills=platform._compose_skills(skill, brief=brief, context=context), execution_mode="automatic_delivery")
    tools = [s["tool"] for s in compiled["steps"]]
    assert "confirm_cover" in tools
    assert "compose_cover_intro" not in tools
    assert tools.count("deliver_current_plan") == 1
    assert tools.count("run_delivery_qc") == 1
    assert tools[-2:] == ["deliver_current_plan", "run_delivery_qc"]


@pytest.mark.parametrize("severity,expected", [("warning", "completed"), ("error", "failed")])
def test_quality_warnings_do_not_block_but_errors_do(platform, severity, expected):
    def dispatch(ws, tool, args):
        if tool == "run_delivery_qc":
            return {"artifact": {"kind": "delivery_qc_report", "passed": False,
                                 "reports": [{"issues": [{"severity": severity, "message": "检查结果"}]}]}}
        return {"artifact": {"kind": "delivery_master", "outputs": [{"filename": "final.mp4"}]}}
    platform.configure_tool_dispatcher(dispatch)
    assert create(platform)["status"] == expected


def test_feature_switch_does_not_silently_downgrade(platform, monkeypatch):
    monkeypatch.setenv("CLIPTALK_AUTOMATIC_DELIVERY", "0")
    with pytest.raises(ValueError, match="暂未启用"):
        create(platform)


@pytest.mark.parametrize("step", [
    {"tool": "deliver_current_plan", "sideEffect": "export", "pluginId": "third-party"},
    {"tool": "export_delivery_master", "sideEffect": "export"},
    {"tool": "delete_media", "sideEffect": "delete"},
])
def test_automatic_mode_cannot_authorize_unrelated_effects(step):
    assert not may_auto_approve({"executionMode": "automatic_delivery", "steps": [step]})


def test_sessions_only_come_from_completed_current_plan_artifacts():
    plan = {"steps": [
        {"status": "completed", "result": {"artifact": {"previews": [{"sessionId": "current"}]}}},
        {"status": "failed", "result": {"artifact": {"sessionId": "stale"}}},
        {"status": "completed", "result": {"artifact": {"output": {"sourceEditSessionId": "current"}}}},
    ]}
    assert delivery_session_ids(plan) == ["current"]
    assert blocking_quality_issues({"artifact": {"kind": "unrelated", "reports": []}}) == []


def test_async_review_question_is_not_mistaken_for_completed_step(platform):
    future = Future()
    platform.configure_tool_dispatcher(lambda ws, tool, args:
        {"future": future, "operationId": "caption_check"} if tool == "inspect_workspace" else {})
    plan = create(platform)
    future.set_result({"actionRequired": True, "action": "subtitle_overlap", "sessionId": "edit_1"})
    result = platform.store.get("plans", plan["id"])
    assert result["status"] == "action_required"
    assert result["steps"][0]["status"] == "action_required"


@pytest.mark.parametrize("raw,count,expected", [
    ({"frames": [{"dialogueSubtitle": "absent", "confidence": .95}]}, 1, "clear"),
    ({"frames": [{"dialogueSubtitle": "present", "confidence": .8}]}, 1, "present"),
    ({"frames": [{"dialogueSubtitle": "absent", "confidence": .5}]}, 1, "unknown"),
    ({"frames": [{"dialogueSubtitle": "absent", "confidence": True}]}, 1, "unknown"),
    ({"frames": []}, 3, "unknown"), ({}, 1, "unknown"),
])
def test_source_caption_check_requires_complete_confident_samples(raw, count, expected):
    from app.source_subtitle_check import assess_samples
    assert assess_samples(raw, count) == expected


@pytest.mark.parametrize("status,expected_calls", [("present", 1), ("unknown", 1), ("absent", 3)])
def test_source_caption_check_uses_readable_frames_not_tiny_contact_sheet(tmp_path, status, expected_calls):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.source_subtitle_check import check_source_subtitles

    frames = [SimpleNamespace(path=tmp_path / f"frame-{i}.jpg") for i in range(3)]
    client = SimpleNamespace(analyze_image=Mock(return_value={"frames": [{"dialogueSubtitle": status, "confidence": .95}]}))
    runtime = SimpleNamespace(
        build_edit_session_render_plan=lambda *_: ([{"start": 0, "end": 10}], []),
        extract_frames_at_times=Mock(return_value=frames), cancel_events={}, settings=SimpleNamespace(ffmpeg="ffmpeg"),
        create_vision_client_for_job=lambda _: client,
        create_contact_sheet=Mock(side_effect=AssertionError("Unreadable sheet must not be used")),
    )
    report = check_source_subtitles(runtime, {"id": "job", "sourcePath": "source.mp4", "workDirectory": str(tmp_path)},
                                   {}, {"id": "draft", "outputFingerprints": ["current"]})
    assert report["status"] == ("clear" if status == "absent" else status)
    assert report["sampleCount"] == expected_calls
    assert client.analyze_image.call_count == expected_calls
    assert [c.args[1] for c in client.analyze_image.call_args_list] == [f.path for f in frames[:expected_calls]]


def test_automatic_caption_check_is_bound_to_draft_not_a_fake_user_ack():
    from app.automatic_delivery import subtitle_source_ready
    draft = {"sourceSubtitleAcknowledged": False, "confirmationMode": "automatic_delivery",
             "outputFingerprints": ["cut-v2"],
             "sourceSubtitleCheck": {"status": "clear", "outputFingerprints": ["cut-v2"]}}
    assert subtitle_source_ready(draft)
    draft["outputFingerprints"] = ["cut-v3"]
    assert not subtitle_source_ready(draft)
    draft["sourceSubtitleAcknowledged"] = True
    assert subtitle_source_ready(draft)


def test_automatic_quality_repair_is_bounded_to_one_replay(platform):
    calls = []
    def dispatch(ws, tool, args):
        calls.append(tool)
        if tool == "run_delivery_qc":
            return {"artifact": {"kind": "delivery_qc_report", "passed": False,
                                 "reports": [{"issues": [{"severity": "error", "code": "target_duration_mismatch",
                                                          "message": "时长不满足要求"}]}]}}
        return {"artifact": {"kind": "delivery_master", "outputs": [{"filename": "final.mp4"}]}}
    platform.configure_tool_dispatcher(dispatch)
    result = create(platform)
    assert result["status"] == "failed"
    assert result["automaticRepairCount"] == 1
    assert calls.count("propose_timeline_edit") == 2
    assert calls.count("run_delivery_qc") == 2


def test_search_only_does_not_request_video_delivery(platform):
    platform.install_skill(markdown="""---
name: cliptalk-content-extractor
version: 1.0.0
description: Find requested video content.
allowed-tools: inspect_workspace search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
---
# Search
""", source="builtin", status="enabled")
    platform.configure_tool_dispatcher(lambda *_: {"artifact": {"kind": "content_search"}})
    ws = platform.create_workspace(job_id="job_search_only")
    result = platform.create_plan(workspace_id=ws["id"], skill_id="cliptalk-content-extractor",
                                  goal="只找出汽车出现的片段，不剪辑，不生成视频", execution_mode="automatic_delivery")
    assert not any(s["tool"] == "deliver_current_plan" for s in result["steps"])


@pytest.mark.parametrize("skill,goal,old_tool", [
    ("cliptalk-audio-polish-mixer", "为当前成片降噪并优化音量", "polish_audio_mix"),
    ("cliptalk-local-motion-renderer", "制作2秒动态图文标题卡，标题写新品发布", "render_motion_graphics"),
])
def test_advanced_automatic_tasks_use_durable_formal_delivery(platform, skill, goal, old_tool):
    platform.install_skill(markdown=f"""---
name: {skill}
version: 1.0.0
description: Local media effects.
allowed-tools: inspect_workspace {old_tool} compose_motion_intro run_delivery_qc
---
# Media
""", source="builtin", status="enabled")
    platform.configure_planning_context_provider(lambda _: {"editing": {"hasOutputs": True}})
    platform.configure_tool_dispatcher(lambda *_: {"artifact": {"kind": "delivery_master"}})
    ws = platform.create_workspace(job_id="advanced")
    result = platform.create_plan(workspace_id=ws["id"], skill_id=skill, goal=goal, execution_mode="automatic_delivery")
    assert result["status"] == "completed"
    assert [s["tool"] for s in result["steps"]] == ["inspect_workspace", "deliver_current_plan", "run_delivery_qc"]
