from __future__ import annotations

import asyncio
import copy
import io
import tempfile
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.datastructures import UploadFile

from app.agent_platform import SKILL_PROFILES, AgentPlatform
from app.agent_store import AgentStore, parse_skill_markdown


SKILL = """---
name: test-editor
description: Plans test video edits for Agent platform verification.
allowed-tools: inspect_workspace analyze_highlights search_content review_content_evidence discover_people select_people discover_speakers select_speakers propose_timeline_edit confirm_timeline_edit prepare_subtitle_review layout_subtitles render_review_preview cancel_operation
---

# Test Editor

Inspect the workspace and produce a review result.
"""


class FakeAgentClient:
    def __init__(self, steps: list[dict[str, Any]] | None = None) -> None:
        self.steps = steps or [{
            "id": "inspect", "title": "检查素材", "tool": "inspect_workspace",
            "arguments": {}, "dependencies": [], "expectedOutput": "素材状态",
            "sideEffect": "read", "estimatedSeconds": 1, "optional": False,
        }]

    def plan(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"plan": {"summary": "测试计划", "steps": self.steps}, "events": []}

    def route_skill(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"skillId": "test-editor", "reason": "matches"}

    def generate_skill(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "skillMarkdown": """---
name: generated-editor
description: Generated test profile for Agent platform verification.
allowed-tools: inspect_workspace propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: revision
---

# Generated Editor
""",
            "simulation": {"valid": True, "requiredTools": ["inspect_workspace"]},
        }

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}


def platform_at(path: Path, steps: list[dict[str, Any]] | None = None) -> AgentPlatform:
    platform = AgentPlatform(
        data_root=path, service_url="http://agent.invalid",
        model_config_resolver=lambda: {"model": "fake"},
    )
    platform.client = FakeAgentClient(steps)  # type: ignore[assignment]
    platform.install_skill(markdown=SKILL, source="test", status="enabled")
    return platform


def test_plugin_approval_binds_both_content_and_tree_hashes(tmp_path):
    platform = platform_at(tmp_path)
    plugin = {"id": "plugin-test", "version": "1.0.0", "status": "enabled", "contentHash": "content-a", "treeHash": "tree-a",
              "tools": [{"name": "plugin-check", "sideEffect": "read"}]}
    platform.store.save("plugins", plugin)
    catalog = next(item for item in platform.tool_catalog() if item["name"] == "plugin-check")
    platform._validate_plugin_identity(catalog)
    changed = {**plugin, "contentHash": "content-b"}
    platform.store.save("plugins", changed)
    with pytest.raises(ValueError, match="重新规划"):
        platform._validate_plugin_identity(catalog)
    platform.store.save("plugins", {**plugin, "treeHash": "tree-b"})
    with pytest.raises(ValueError, match="重新规划"):
        platform._validate_plugin_identity(catalog)
    legacy = {**catalog, "contentHash": None, "treeHash": None}
    with pytest.raises(ValueError):
        platform._validate_plugin_identity(legacy)


def test_uncertain_plugin_result_cannot_be_confirmed_as_success(tmp_path):
    platform = platform_at(tmp_path)
    workspace = platform.create_workspace(job_id="isolated-job")
    plan = platform.store.save("plans", {"id": "uncertain-plan", "status": "action_required", "workspaceId": workspace["id"],
        "steps": [{"id": "step", "pluginId": "plugin", "status": "action_required", "attempts": 1,
                   "result": {"operationId": "op", "operationStatus": "uncertain", "retryable": False}}]})
    with pytest.raises(ValueError, match="尚未核实"):
        platform.resolve_action(plan["id"], approved=True)
    calls = []
    def query(operation_id):
        calls.append(operation_id)
        return {"status": "uncertain"}
    platform.client.query_plugin_operation = query
    assert platform.retry_action(plan["id"])["status"] == "action_required"
    assert calls == ["op"]


def test_cover_requested_with_a_short_video_still_compiles_a_timeline_delivery() -> None:
    brief = AgentPlatform._editing_brief(
        "把嘉宾发言剪成45秒短视频，添加字幕并生成一张16:9封面", {},
    )

    assert brief["targetSeconds"] == 45
    assert brief["coverRequested"] is True


def test_cover_review_retry_rebuilds_candidates_from_structured_goal_constraints(tmp_path: Path) -> None:
    platform = platform_at(tmp_path)
    workspace = platform.create_workspace(job_id="job_cover_retry")
    calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(_workspace: dict[str, Any], tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((tool, copy.deepcopy(arguments)))
        if tool == "review_cover_variants":
            return {"actionRequired": True, "message": "请检查重新生成的封面候选"}
        return {"ok": True}

    platform.configure_tool_dispatcher(dispatch)
    plan = platform.store.save("plans", {
        "id": "plan_cover_retry", "workspaceId": workspace["id"],
        "status": "action_required", "executionMode": "stepwise_review",
        "goal": "用第54s小米创始人雷军的照片作为封面，封面上写上产品时刻",
        "planningContext": {"jobId": "job_cover_retry"},
        "brief": {"coverRequested": True, "coverSourceTime": None, "coverSubject": ""},
        "steps": [{
            "id": "inspect", "index": 0, "title": "检查素材", "tool": "inspect_workspace",
            "arguments": {}, "dependencies": [], "expectedOutput": "素材", "sideEffect": "read",
            "estimatedSeconds": 1, "optional": False, "status": "completed", "attempts": 1,
        }, {
            "id": "candidate", "index": 1, "title": "提取封面", "tool": "propose_cover_candidates",
            "arguments": {"sourceScope": "accepted_cut", "candidateBudget": 16, "aspectRatios": ["16:9"]},
            "dependencies": ["inspect"], "expectedOutput": "候选", "sideEffect": "analysis",
            "estimatedSeconds": 1, "optional": False, "status": "completed", "attempts": 1,
        }, {
            "id": "render", "index": 2, "title": "生成封面", "tool": "render_cover_variants",
            "arguments": {"aspectRatios": ["16:9"]}, "dependencies": ["candidate"],
            "expectedOutput": "封面", "sideEffect": "render", "estimatedSeconds": 1,
            "optional": False, "status": "completed", "attempts": 1,
        }, {
            "id": "review", "index": 3, "title": "检查封面", "tool": "review_cover_variants",
            "arguments": {}, "dependencies": ["render"], "expectedOutput": "确认", "sideEffect": "review",
            "estimatedSeconds": 0, "optional": False, "status": "action_required", "attempts": 0,
            "result": {"action": "structured_review"},
        }, {
            "id": "confirm", "index": 4, "title": "保存封面", "tool": "confirm_cover",
            "arguments": {}, "dependencies": ["review"], "expectedOutput": "封面", "sideEffect": "write",
            "estimatedSeconds": 1, "optional": False, "status": "pending", "attempts": 0,
        }],
    })
    workspace["status"] = "action_required"
    platform.store.save("workspaces", workspace)

    retried = platform.retry_action(plan["id"])

    assert retried["status"] == "action_required"
    assert retried["brief"]["coverSourceTime"] == 54.0
    assert retried["brief"]["coverSubject"] == "小米创始人雷军"
    candidate_arguments = next(step for step in retried["steps"] if step["tool"] == "propose_cover_candidates")["arguments"]
    assert candidate_arguments["sourceTime"] == 54.0
    assert candidate_arguments["subject"] == "小米创始人雷军"
    assert [tool for tool, _arguments in calls] == [
        "propose_cover_candidates", "render_cover_variants",
    ]
    assert next(step for step in retried["steps"] if step["tool"] == "review_cover_variants")["status"] == "action_required"


def test_interview_respondents_do_not_trigger_visual_person_tracking() -> None:
    brief = AgentPlatform._editing_brief(
        "把不同人物关于成长、工作和未来的回答整理成 90 秒访谈精华，"
        "保留必要问题上下文并添加字幕。",
        {},
    )

    assert brief["interview"] is True
    assert brief["personTargeted"] is False
    assert brief["subjectKind"] == "content"


def test_explicit_anonymous_speaker_label_is_preserved_in_brief() -> None:
    brief = AgentPlatform._editing_brief(
        "识别视频中的说话人，只保留说话人 B 的所有发言，生成审核样片。",
        {},
    )

    assert brief["speakerTargeted"] is True
    assert brief["speakerTargetLabel"] == "说话人 B"
    assert brief["subjectKind"] == "speaker"


def test_visual_identity_request_still_selects_person_targeting() -> None:
    brief = AgentPlatform._editing_brief(
        "识别画面中的人物，只保留穿黑色上衣的人出镜的片段。",
        {},
    )

    assert brief["personTargeted"] is True
    assert brief["subjectKind"] == "person"
    assert brief["personDescription"] == "穿黑色上衣的人"
    assert brief["delivery"] == "timeline"


def test_combined_vertical_video_and_cover_request_preserves_both_deliverables() -> None:
    brief = AgentPlatform._editing_brief(
        "找出所有汽车画面，合成一个竖屏的视频，在顶部添加字幕，最开头放封面，文本描述：小米牛逼！",
        {},
    )

    assert brief["socialDelivery"] == {
        "requested": True, "aspect": "9:16", "fit": "blur", "focusX": .5, "focusY": .5,
    }
    assert brief["coverRequested"] is True
    assert brief["coverTitle"] == "小米牛逼！"
    assert brief["coverIntroRequested"] is True
    assert brief["shortForm"] is False
    assert brief["retrievalQuery"] == "汽车"
    assert brief["delivery"] == "timeline"


def test_external_person_cover_is_parsed_without_silent_source_frame_fallback() -> None:
    goal = (
        "找出所有汽车相关画面，合成竖屏视频，并在顶部添加对应字幕。"
        "并找到小米创始人雷军的照片作为封面，封面上写上小米牛逼，雷军牛逼！！！"
    )
    brief = AgentPlatform._editing_brief(goal, {})

    assert brief["coverRequested"] is True
    assert brief["coverTitle"] == "小米牛逼，雷军牛逼！！！"
    assert brief["coverSourceKind"] == "external_image"
    assert brief["coverSubject"] == "小米创始人雷军"
    assert brief["coverSourceStatus"] == "requires_external_asset"

    source_cover = AgentPlatform._editing_brief(
        "使用视频画面制作封面，封面文字写关键时刻，并导出竖屏视频。", {},
    )
    assert source_cover["coverTitle"] == "关键时刻"
    assert source_cover["coverSourceKind"] == "source_frame"


def test_named_source_frame_cover_preserves_subject_and_exact_time() -> None:
    brief = AgentPlatform._editing_brief(
        "用第54秒小米创始人雷军的画面作为封面，封面写上发布会高光。", {},
    )

    assert brief["coverSourceKind"] == "source_frame"
    assert brief["coverSourceStatus"] == "available"
    assert brief["coverSubject"] == "小米创始人雷军"
    assert brief["coverIdentityPolicy"] == "verify"
    assert brief["coverSourceTime"] == 54


def test_deictic_source_frame_cover_preserves_exact_time_without_duration_target() -> None:
    brief = AgentPlatform._editing_brief(
        "找出所有汽车相关画面，合成竖屏视频，并在顶部添加对应字幕。"
        "并选取54s出现的那个人作为封面，封面上写好上：小米牛逼！！雷军雷神！！！！",
        {},
    )

    assert brief["retrievalQuery"] == "汽车"
    assert brief["targetSeconds"] is None
    assert brief["durationSource"] == "none"
    assert brief["coverSourceKind"] == "source_frame"
    assert brief["coverSourceStatus"] == "available"
    assert brief["coverSubject"] == "那个人"
    assert brief["coverIdentityPolicy"] == "verify"
    assert brief["coverSourceTime"] == 54
    assert brief["coverTitle"] == "小米牛逼！！雷军雷神！！！！"
    understanding = AgentPlatform._plan_understanding(brief, {})
    cover_item = next(item for item in understanding["items"] if item["label"] == "封面")
    assert "54 秒画面" in cover_item["value"]
    assert "人物：那个人" in cover_item["value"]


def test_generic_cover_style_is_not_treated_as_a_person_subject() -> None:
    brief = AgentPlatform._editing_brief("选择最具有冲击性的画面作为封面", {})

    assert brief["coverRequested"] is True
    assert brief["operationIntent"] == "cover_asset"
    assert brief["coverSourceKind"] == "source_frame"
    assert brief["coverSubject"] == ""
    assert brief["coverIdentityPolicy"] == "ignore"
    understanding = AgentPlatform._plan_understanding(brief, {})
    cover_item = next(item for item in understanding["items"] if item["label"] == "封面")
    assert "人物：" not in cover_item["value"]


def test_cover_only_plan_uses_source_video_when_no_adopted_timeline_exists(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    platform = platform_at(tmp_path)
    platform.install_skill(
        markdown=(root / "skills" / "cliptalk-cover-director" / "SKILL.md").read_text(encoding="utf-8"),
        source="test", status="enabled",
    )
    platform.configure_planning_context_provider(lambda job_id: {
        "jobId": job_id,
        "editing": {"hasOutputs": False, "hasActiveSession": False},
    })
    workspace = platform.create_workspace(job_id="job_fresh_cover")

    plan = platform.create_plan(
        workspace_id=workspace["id"],
        goal="选择最具有冲击性的画面作为封面",
    )

    candidate_arguments = next(
        step for step in plan["steps"] if step["tool"] == "propose_cover_candidates"
    )["arguments"]
    assert plan["skillId"] == "cliptalk-cover-director"
    assert candidate_arguments["sourceScope"] == "source_video"
    assert "subject" not in candidate_arguments


def test_external_cover_requirement_stops_managed_plan_before_media_work() -> None:
    root = Path(__file__).resolve().parents[1]
    skill_ids = (
        "cliptalk-content-extractor",
        "cliptalk-social-reframe-exporter",
        "cliptalk-caption-layout-director",
        "cliptalk-cover-director",
    )
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        for skill_id in skill_ids:
            platform.install_skill(
                markdown=(root / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8"),
                source="test", status="enabled",
            )
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "editing": {"hasOutputs": False},
            "evidence": {"hasCandidates": False},
        })
        workspace = platform.create_workspace(job_id="job_external_cover")
        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-content-extractor",
            goal=(
                "找出汽车画面，合成竖屏视频；找到雷军的照片作为封面，"
                "封面上写上小米牛逼，雷军牛逼！"
            ),
        )

        assert [step["tool"] for step in plan["steps"]] == ["inspect_workspace"]
        assert plan["steps"][0]["arguments"]["requiredState"] == "external_cover_asset"
        assert plan["steps"][0]["arguments"]["preconditionCode"] == "missing_external_cover_asset"
        assert "不会用源视频画面替代" in plan["steps"][0]["expectedOutput"]
        assert "不支持联网找图或导入独立封面图片" in plan["summary"]
        with pytest.raises(ValueError, match="无法获取.*外部封面图片"):
            platform.approve_plan(plan["id"], expected_hash=plan["planHash"])


def test_cover_timestamp_does_not_become_target_duration() -> None:
    brief = AgentPlatform._editing_brief(
        "找出所有汽车相关画面，合成竖屏视频，并在顶部添加对应字幕。"
        "并选取54s出现的那个人作为封面，封面上写好上：小米牛逼！！雷军雷神！！！！",
        {},
    )

    assert brief["targetSeconds"] is None
    assert brief["durationExplicit"] is False
    assert brief["retrievalQuery"] == "汽车"
    assert brief["coverRequested"] is True
    assert brief["coverTitle"] == "小米牛逼！！雷军雷神！！！！"
    assert brief["socialDelivery"]["aspect"] == "9:16"
    assert brief["subtitleRequested"] is True
    understanding = AgentPlatform._plan_understanding(brief, {})
    by_label = {item["label"]: item["value"] for item in understanding["items"]}
    assert by_label["检索目标"] == "汽车"
    assert by_label["成片时长"] == "不限制，使用符合条件的可靠片段"
    assert "9:16" in by_label["输出方式"]
    assert "小米牛逼！！雷军雷神！！！！" in by_label["封面"]


def test_add_text_command_is_graphics_not_a_cover_title() -> None:
    brief = AgentPlatform._editing_brief(
        "给当前成片顶部加文字‘小米牛逼’，显示 3 秒。", {},
    )

    assert brief["graphicsRequested"] is True
    assert brief["graphicsText"] == "小米牛逼"
    assert brief["targetSeconds"] is None
    assert brief["durationExplicit"] is False
    assert brief["coverRequested"] is False
    assert brief["coverTitle"] == ""


def test_intent_brief_handles_common_chinese_editing_ambiguities() -> None:
    context = {
        "duration": 200,
        "editing": {
            "hasOutputs": True,
            "hasActiveSession": True,
            "currentDurationSeconds": 100,
        },
    }

    overlay = AgentPlatform._editing_brief(
        "找出所有汽车相关画面，顶部添加“小米汽车”文字，显示5秒，合成竖屏视频",
        context,
    )
    assert overlay["retrievalQuery"] == "汽车"
    assert overlay["graphicsRequested"] is True
    assert overlay["graphicsText"] == "小米汽车"
    assert overlay["overlayDurationSeconds"] == 5
    assert overlay["targetSeconds"] is None
    assert overlay["socialDelivery"]["aspect"] == "9:16"

    explicit_range = AgentPlatform._editing_brief("从 01:20 开始剪到 02:10，做成竖屏", context)
    assert explicit_range["operationIntent"] == "compose_timeline"
    assert explicit_range["sourceRange"] == {
        "kind": "custom", "start": 80.0, "end": 130.0,
        "description": "从 01:20 开始剪到 02:10", "requiresDuration": False,
        "source": "explicit_range",
    }

    remove_prefix = AgentPlatform._editing_brief("剪掉前30秒，保留后面的内容", context)
    assert remove_prefix["operationIntent"] == "compose_timeline"
    assert remove_prefix["retrievalQuery"] == ""
    assert remove_prefix["removedSourceRanges"][0]["start"] == 0
    assert remove_prefix["removedSourceRanges"][0]["end"] == 30

    semantic_range = AgentPlatform._editing_brief("把讲价格的地方开始到讲配置结束剪出来", context)
    assert semantic_range["retrievalQuery"] == "价格"
    assert semantic_range["anchorStart"] == {"query": "价格", "selectionPolicy": "unique_or_review"}
    assert semantic_range["sourceEndAnchor"] == {"query": "配置", "selectionPolicy": "unique_or_review"}

    search_only = AgentPlatform._editing_brief("不要生成成片，只列出汽车相关候选", context)
    assert search_only["operationIntent"] == "search_only"
    assert search_only["delivery"] == "candidates"
    assert search_only["retrievalQuery"] == "汽车"

    product_shorter = AgentPlatform._editing_brief("把介绍XX产品的部分剪出来，再短一点", context)
    assert product_shorter["retrievalQuery"] == "介绍XX产品"
    assert product_shorter["targetSeconds"] == 80
    assert product_shorter["durationSource"] == "relative"

    social_only = AgentPlatform._editing_brief("做一个小红书视频，但不要裁切，保留完整画面", context)
    assert social_only["operationIntent"] == "reframe_existing"
    assert social_only["retrievalQuery"] == ""
    assert social_only["socialDelivery"] == {
        "requested": True, "aspect": "9:16", "fit": "blur", "focusX": .5, "focusY": .5,
    }

    subtitles = AgentPlatform._editing_brief("只导出字幕文件，不要生成视频", context)
    assert subtitles["operationIntent"] == "export_subtitles"
    assert subtitles["delivery"] == "artifact"
    assert subtitles["subtitleAssetRequested"] is True

    speaker = AgentPlatform._editing_brief("只保留雷军说话的片段", context)
    assert speaker["speakerTargeted"] is True
    assert speaker["speakerTargetLabel"] == "雷军"
    assert speaker["subjectKind"] == "speaker"

    person = AgentPlatform._editing_brief("只保留54秒出现的那个人的画面", context)
    assert person["personTargeted"] is True
    assert person["personDescription"] == "54 秒出现的那个人"
    assert person["personSourceTime"] == 54
    assert person["retrievalQuery"] == ""

    negative = AgentPlatform._editing_brief("去掉没有汽车的部分，保留有汽车的画面", context)
    assert negative["retrievalQuery"] == "汽车"
    assert negative["selectionMode"] == "include"


def test_cover_text_command_does_not_become_a_generic_text_layer() -> None:
    brief = AgentPlatform._editing_brief(
        "生成本次任务封面，封面文字写‘小米牛逼！’。", {},
    )

    assert brief["coverRequested"] is True
    assert brief["coverTitle"] == "小米牛逼！"
    assert brief["graphicsRequested"] is False


def test_subtitle_file_intent_routes_to_export_without_video_rendering(tmp_path: Path) -> None:
    platform = platform_at(tmp_path)
    caption_skill = """---
name: cliptalk-caption-layout-director
version: 1.1.0
description: Caption layout and subtitle export.
allowed-tools: inspect_workspace layout_subtitles prepare_subtitle_review render_review_preview export_subtitles
workflow-profile: caption-layout
---

# Caption
"""
    platform.install_skill(markdown=caption_skill, source="test", status="enabled")
    platform.configure_planning_context_provider(lambda job_id: {
        "jobId": job_id,
        "editing": {"hasOutputs": True, "hasActiveSession": False},
    })
    workspace = platform.create_workspace(job_id="job_subtitle_export_intent")

    plan = platform.create_plan(workspace_id=workspace["id"], goal="只导出字幕文件，不要生成视频")

    assert plan["skillId"] == "cliptalk-caption-layout-director"
    assert plan["brief"]["operationIntent"] == "export_subtitles"
    assert [step["tool"] for step in plan["steps"]] == ["inspect_workspace", "export_subtitles"]
    assert plan["steps"][1]["arguments"] == {"format": "srt"}


def test_source_range_edit_is_not_routed_as_existing_output_reframe(tmp_path: Path) -> None:
    platform = platform_at(tmp_path)
    revision_skill = """---
name: cliptalk-revision-editor
version: 1.1.0
description: Timeline revision.
allowed-tools: inspect_workspace propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: revision
---

# Revision
"""
    social_skill = """---
name: cliptalk-social-reframe-exporter
version: 1.1.0
description: Social reframe.
allowed-tools: inspect_workspace render_social_preview run_delivery_qc
workflow-profile: social-reframe
---

# Social
"""
    platform.install_skill(markdown=revision_skill, source="test", status="enabled")
    platform.install_skill(markdown=social_skill, source="test", status="enabled")
    platform.configure_planning_context_provider(lambda job_id: {
        "jobId": job_id,
        "duration": 200,
        "editing": {"hasOutputs": True, "hasActiveSession": True},
    })
    workspace = platform.create_workspace(job_id="job_source_range_intent")

    plan = platform.create_plan(workspace_id=workspace["id"], goal="从 01:20 开始剪到 02:10，做成竖屏")

    assert plan["skillId"] == "cliptalk-revision-editor"
    assert plan["brief"]["sourceRange"]["start"] == 80.0
    assert plan["brief"]["sourceRange"]["end"] == 130.0
    assert "render_social_preview" not in [step["tool"] for step in plan["steps"][:3]]
    timeline = next(step for step in plan["steps"] if step["tool"] == "propose_timeline_edit")
    assert "仅使用源视频 80 到 130 秒范围" in timeline["arguments"]["instruction"]


def test_conversational_edit_phrases_compile_to_the_expected_internal_brief() -> None:
    context = {
        "editing": {
            "hasOutputs": True,
            "currentDurationSeconds": 100,
            "currentDurationSource": "current_output_version",
        },
    }

    highlight = AgentPlatform._editing_brief("把最精彩的部分剪成一个高光视频", context)
    assert highlight["retrievalQuery"] == ""
    assert highlight["delivery"] == "timeline"

    product = AgentPlatform._editing_brief("把介绍 XX 产品的部分剪出来", context)
    assert product["retrievalQuery"] == "介绍 XX 产品"
    assert product["delivery"] == "timeline"

    shorter = AgentPlatform._editing_brief("再短一点", context)
    assert shorter["retrievalQuery"] == ""
    assert shorter["targetSeconds"] == 80
    assert shorter["durationExplicit"] is True
    assert shorter["durationSource"] == "relative"
    assert shorter["relativeDurationBaseSeconds"] == 100

    anchor = AgentPlatform._editing_brief("从讲价格的地方开始", context)
    assert anchor["retrievalQuery"] == "价格"
    assert anchor["anchorStart"] == {
        "query": "价格", "selectionPolicy": "unique_or_review",
    }
    assert anchor["delivery"] == "timeline"
    assert anchor["graphicsRequested"] is False

    price_card = AgentPlatform._editing_brief("在顶部添加价格卡", context)
    assert price_card["graphicsRequested"] is True


def test_relative_duration_without_a_current_cut_is_explicitly_unresolved() -> None:
    brief = AgentPlatform._editing_brief("再短一点", {"editing": {"hasOutputs": False}})

    assert brief["targetSeconds"] is None
    assert brief["unresolvedRelativeDuration"] is True


def test_existing_voice_composition_keeps_reference_identity_scope(tmp_path):
    platform = platform_at(tmp_path)
    name = "cliptalk-speaker-editor"
    profile = SKILL_PROFILES[name]
    skill = platform.install_skill(markdown=f"---\nname: {name}\ndescription: Test\nallowed-tools: {' '.join(sorted(profile['tools']))}\n---\nTest",
                                   source="test", status="enabled")
    goal = "把当前已核验的目标声音片段合成为审核样片"
    context = {"evidence": {"hasCandidates": True, "hasContentSearch": True,
                           "contentConstraint": {"contract": {"predicates": [{"kind": "speech.voice_identity"}]}}}}
    brief = platform._editing_brief(goal, context)
    plan = platform._compile_profile_plan({}, skill=skill, goal=goal, context=context,
        skills=platform._compose_skills(skill, brief=brief, context=context))
    names = [s["tool"] for s in plan["steps"]]
    assert "select_speakers" not in names
    assert "search_content" not in names
    assert "review_content_evidence" in names
    assert "render_review_preview" in names


@pytest.mark.parametrize("goal,expected", [
    ("把最精彩的部分剪成一个高光视频", "highlight"),
    ("把介绍 XX 产品的部分剪出来", "content"),
    ("再短一点", "revision"),
    ("从讲价格的地方开始", "revision"),
])
def test_conversational_routing_and_executable_plan(tmp_path, goal, expected):
    platform = platform_at(tmp_path)
    for name, profile in SKILL_PROFILES.items():
        platform.install_skill(
            markdown=f"---\nname: {name}\ndescription: Test\nallowed-tools: {' '.join(sorted(profile['tools']))}\n---\nTest",
            source="test", status="enabled",
        )
    context = {"editing": {"hasOutputs": True, "hasActiveSession": True,
                           "currentDurationSeconds": 100},
               "delivery": {"outputAspect": "9:16"}}
    skill = platform.route_skill(goal, planning_context=context)
    assert platform._profile_for_skill(skill)["kind"] == expected
    brief = platform._editing_brief(goal, context)
    plan = platform._compile_profile_plan(
        {}, skill=skill, goal=goal, context=context,
        skills=platform._compose_skills(skill, brief=brief, context=context),
    )
    steps = {s["tool"]: s for s in plan["steps"]}
    assert "propose_timeline_edit" in steps
    assert "render_review_preview" in steps
    if goal == "再短一点":
        assert "search_content" not in steps
        assert steps["propose_timeline_edit"]["arguments"]["targetSeconds"] == 80
    if goal == "从讲价格的地方开始":
        assert steps["search_content"]["arguments"]["query"].startswith("仅根据对白检索：价格")
        assert steps["review_content_evidence"]["arguments"]["selectionPolicy"] == "unique_or_review"
        assert steps["propose_timeline_edit"]["arguments"]["anchorStartQuery"] == "价格"


def test_cover_intro_wording_does_not_route_all_content_request_to_shortform() -> None:
    content_skill = """---
name: cliptalk-content-extractor
description: Content extraction.
allowed-tools: inspect_workspace search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: content
---
"""
    shortform_skill = """---
name: cliptalk-shortform-hook-director
description: Shortform hook editing.
allowed-tools: inspect_workspace analyze_highlights search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: shortform
---
"""
    cover_skill = """---
name: cliptalk-cover-director
description: Cover creation.
allowed-tools: inspect_workspace propose_cover_candidates render_cover_variants review_cover_variants confirm_cover
workflow-profile: cover
---
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=content_skill, source="test", status="enabled")
        platform.install_skill(markdown=shortform_skill, source="test", status="enabled")
        platform.install_skill(markdown=cover_skill, source="test", status="enabled")

        selected = platform.route_skill(
            "帮我找出所有关于汽车的画面，合成一个竖屏的视频，并且在顶部增加对应字幕。"
            "最开头放一个封面，上面加文本描述：小米牛逼！",
            planning_context={"editing": {"hasOutputs": False, "hasActiveSession": False}},
        )

        assert selected["id"] == "cliptalk-content-extractor"


def test_short_topic_phrase_routes_to_content_not_shortform() -> None:
    content_skill = """---
name: cliptalk-content-extractor
description: Content extraction.
allowed-tools: inspect_workspace search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: content
---
"""
    shortform_skill = """---
name: cliptalk-shortform-hook-director
description: Shortform hook editing.
allowed-tools: inspect_workspace analyze_highlights search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: shortform
---
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=content_skill, source="test", status="enabled")
        platform.install_skill(markdown=shortform_skill, source="test", status="enabled")

        brief = AgentPlatform._editing_brief("产品新老替换和核心卖点", {})
        selected = platform.route_skill(
            "产品新老替换和核心卖点",
            planning_context={"editing": {"hasOutputs": False, "hasActiveSession": False}},
        )

        assert brief["retrievalQuery"] == "产品新老替换和核心卖点"
        assert brief["shortForm"] is False
        assert selected["id"] == "cliptalk-content-extractor"


def test_short_video_cover_request_adds_the_cover_skill_as_an_edit_addon() -> None:
    speaker_skill = """---
name: cliptalk-speaker-editor
description: Speaker editing.
allowed-tools: inspect_workspace discover_speakers select_speakers search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: speaker
---
"""
    cover_skill = """---
name: cliptalk-cover-director
description: Cover creation.
allowed-tools: inspect_workspace propose_cover_candidates render_cover_variants review_cover_variants confirm_cover
workflow-profile: cover
---
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=speaker_skill, source="test", status="enabled")
        platform.install_skill(markdown=cover_skill, source="test", status="enabled")
        primary = platform._enabled_skill("cliptalk-speaker-editor")
        brief = AgentPlatform._editing_brief("把嘉宾发言剪成45秒短视频并生成16:9封面", {})

        skills = platform._compose_skills(primary, brief=brief, context={})

        assert [item["id"] for item in skills] == [
            "cliptalk-speaker-editor", "cliptalk-cover-director",
        ]


def test_cover_addon_keeps_first_party_short_video_plan_in_autonomous_review() -> None:
    skills = [
        {"id": "cliptalk-speaker-editor", "source": "builtin", "pluginId": None},
        {"id": "cliptalk-cover-director", "source": "builtin", "pluginId": None},
    ]

    assert AgentPlatform._supports_autonomous_review(skills) is True


def test_plain_timeline_request_routes_deterministically_to_highlight_skill() -> None:
    highlight_skill = """---
name: cliptalk-highlight-director
description: Builds a highlight timeline and review preview.
allowed-tools: inspect_workspace analyze_highlights propose_timeline_edit confirm_timeline_edit render_review_preview
workflow-profile: highlight
---

# Highlight Director
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=highlight_skill, source="test", status="enabled")
        selected = platform.route_skill(
            "输出约 20 秒 1:1 审核预览，左右主播都要完整可见，弹幕文字仍可辨认。",
            planning_context={"editing": {"hasOutputs": False}},
        )
        assert selected["id"] == "cliptalk-highlight-director"

        workspace = platform.create_workspace(job_id="job_light_planning_surface")
        reserved, _skill, _payload = platform.prepare_plan_request(
            workspace_id=workspace["id"],
            goal="在二次精剪时间线缩短片段并生成审核样片",
        )
        assert reserved["planningSurface"] == "editor"
        platform.release_plan_request(
            workspace["id"], request_id=reserved["planningRequestId"],
        )
        assert "planningSurface" not in platform.store.get("workspaces", workspace["id"])


def test_plan_never_executes_before_hash_bound_confirmation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        calls: list[str] = []
        platform.configure_tool_dispatcher(
            lambda _workspace, tool, _arguments: calls.append(tool) or {"ok": True},
        )
        workspace = platform.create_workspace(job_id="job_test")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="检查素材")

        assert plan["status"] == "awaiting_confirmation"
        assert calls == []
        with pytest.raises(ValueError, match="计划已经变化"):
            platform.approve_plan(plan["id"], expected_hash="0" * 64)
        assert calls == []

        completed = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert calls == ["inspect_workspace"]
        assert completed["status"] == "preview_ready"
        assert completed["steps"][0]["status"] == "completed"


def test_cancelled_plan_cancels_owned_operation_and_ignores_late_callback() -> None:
    steps = [{
        "id": "preview", "title": "生成审核样片", "tool": "render_review_preview",
        "arguments": {}, "dependencies": [], "expectedOutput": "审核样片",
        "sideEffect": "preview", "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        future: Future[dict[str, Any]] = Future()
        assert future.set_running_or_notify_cancel() is True
        cancelled: list[str] = []
        platform.configure_tool_dispatcher(lambda _workspace, _tool, _arguments: {
            "operationId": "operation_owned", "accepted": True, "future": future,
            "cancel": lambda: cancelled.append("called"),
        })
        workspace = platform.create_workspace(job_id="job_owned")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="生成审核样片")
        waiting = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert waiting["steps"][0]["status"] == "waiting_operation"

        stopped = platform.cancel_plan(plan["id"])
        assert stopped["status"] == "cancelled"
        assert cancelled == ["called"]

        future.set_result({"artifact": {"kind": "review_preview"}})
        persisted = platform.store.get("plans", plan["id"])
        assert persisted is not None
        assert persisted["status"] == "cancelled"
        assert persisted["steps"][0]["status"] == "cancelled"


def test_no_result_is_terminal_and_skips_downstream_steps() -> None:
    steps = [{
        "id": "search", "title": "检索内容", "tool": "search_content",
        "arguments": {"query": "不存在的内容"}, "dependencies": [],
        "expectedOutput": "检索结果", "sideEffect": "analysis",
        "estimatedSeconds": 1, "optional": False,
    }, {
        "id": "inspect", "title": "检查结果", "tool": "inspect_workspace",
        "arguments": {}, "dependencies": ["search"],
        "expectedOutput": "检查结果", "sideEffect": "read",
        "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        platform.configure_tool_dispatcher(lambda _workspace, _tool, _arguments: {
            "terminalStatus": "no_result",
            "artifact": {"kind": "no_match", "reasonCode": "no_match", "candidateCount": 0},
        })
        workspace = platform.create_workspace(job_id="job_no_result")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="查找不存在的内容")
        completed = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])

        assert completed["status"] == "no_result"
        assert [step["status"] for step in completed["steps"]] == ["completed", "skipped"]
        assert completed["steps"][0]["outcome"] == "no_result"
        assert completed["steps"][1]["blockedByStepId"] == "search"
        assert "未形成可靠结果" in completed["steps"][1]["skipReason"]
        assert platform.store.get("workspaces", workspace["id"])["status"] == "no_result"
        assert platform.store.events_after(workspace["id"])[-1]["type"] == "plan.no_result"


def test_no_result_plan_can_retry_from_content_search_without_new_approval() -> None:
    steps = [{
        "id": "inspect", "title": "核查素材", "tool": "inspect_workspace",
        "arguments": {}, "dependencies": [], "expectedOutput": "素材",
        "sideEffect": "read", "estimatedSeconds": 1, "optional": False,
    }, {
        "id": "search", "title": "检索内容", "tool": "search_content",
        "arguments": {"query": "讲解洗衣机和冰箱"}, "dependencies": ["inspect"],
        "expectedOutput": "候选", "sideEffect": "analysis", "estimatedSeconds": 1,
        "optional": False,
    }, {
        "id": "review", "title": "自动筛选", "tool": "review_content_evidence",
        "arguments": {"query": "讲解洗衣机和冰箱"}, "dependencies": ["search"],
        "expectedOutput": "选择", "sideEffect": "review", "estimatedSeconds": 1,
        "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        calls: list[str] = []
        first_search = True

        def dispatch(_workspace: dict, tool: str, _arguments: dict) -> dict:
            nonlocal first_search
            calls.append(tool)
            if tool == "search_content" and first_search:
                first_search = False
                return {
                    "terminalStatus": "no_result",
                    "artifact": {"kind": "no_match", "candidateCount": 0},
                }
            return {"ok": True}

        platform.configure_tool_dispatcher(dispatch)
        workspace = platform.create_workspace(job_id="job_retry_no_result")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="讲解洗衣机和冰箱")
        completed = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert completed["status"] == "no_result"

        retried = platform.retry_action(plan["id"])

        assert retried["status"] == "action_required"
        assert calls == [
            "inspect_workspace", "search_content", "search_content",
        ]
        assert retried["steps"][0]["attempts"] == 1
        assert retried["steps"][1]["attempts"] == 2
        assert retried["steps"][2]["status"] == "action_required"
        retry_events = [
            item for item in platform.store.events_after(workspace["id"])
            if item["type"] == "plan.retry_started"
        ]
        assert retry_events[-1]["payload"]["reason"] == "no_result"


def test_ambiguous_identity_retry_replays_identity_step_before_content_search() -> None:
    steps = [{
        "id": "speaker", "title": "核定说话人", "tool": "select_speakers",
        "arguments": {"mode": "include"}, "dependencies": [],
        "expectedOutput": "目标声音", "sideEffect": "identity",
        "estimatedSeconds": 1, "optional": False,
    }, {
        "id": "search", "title": "检索发言", "tool": "search_content",
        "arguments": {"query": "嘉宾发言"}, "dependencies": ["speaker"],
        "expectedOutput": "发言候选", "sideEffect": "analysis",
        "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        calls: list[str] = []
        first_identity = True

        def dispatch(_workspace: dict, tool: str, _arguments: dict) -> dict:
            nonlocal first_identity
            calls.append(tool)
            if tool == "select_speakers" and first_identity:
                first_identity = False
                return {
                    "terminalStatus": "no_result",
                    "artifact": {"kind": "no_match", "reasonCode": "ambiguous_identity"},
                }
            return {"ok": True}

        platform.configure_tool_dispatcher(dispatch)
        workspace = platform.create_workspace(job_id="job_retry_identity")
        plan = platform.create_plan(
            workspace_id=workspace["id"], goal="保留嘉宾发言",
            execution_mode="autonomous_review",
        )
        # The generic test skill does not advertise the managed autonomous
        # profile; force the stored mode so this test exercises retry routing,
        # rather than the unrelated stepwise identity review gate.
        plan["executionMode"] = "autonomous_review"
        platform.store.save("plans", plan)
        completed = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert completed["status"] == "no_result"

        retried = platform.retry_action(plan["id"])

        assert retried["status"] == "preview_ready"
        assert calls == ["select_speakers", "select_speakers", "search_content"]
        assert retried["steps"][0]["attempts"] == 2
        retry_event = next(
            item for item in reversed(platform.store.events_after(workspace["id"]))
            if item["type"] == "plan.retry_started"
        )
        assert retry_event["payload"]["replayFromTool"] == "select_speakers"


def test_insufficient_coverage_retry_reuses_search_and_replays_timeline_only() -> None:
    steps = [{
        "id": "search", "title": "检索内容", "tool": "search_content",
        "arguments": {"query": "产品讲解"}, "dependencies": [],
        "expectedOutput": "候选", "sideEffect": "analysis", "estimatedSeconds": 1,
        "optional": False,
    }, {
        "id": "review", "title": "自动筛选", "tool": "review_content_evidence",
        "arguments": {"query": "产品讲解"}, "dependencies": ["search"],
        "expectedOutput": "选择", "sideEffect": "review", "estimatedSeconds": 1,
        "optional": False,
    }, {
        "id": "timeline", "title": "建立时间线", "tool": "propose_timeline_edit",
        "arguments": {"instruction": "目标 30 秒"}, "dependencies": ["review"],
        "expectedOutput": "时间线", "sideEffect": "preview", "estimatedSeconds": 1,
        "optional": False,
    }, {
        "id": "confirm", "title": "确认时间线", "tool": "confirm_timeline_edit",
        "arguments": {}, "dependencies": ["timeline"], "expectedOutput": "已应用时间线",
        "sideEffect": "preview", "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        workspace = platform.create_workspace(job_id="job_retry_timeline_coverage")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="产品讲解")
        plan["status"] = "no_result"
        plan["steps"][0].update({"status": "completed", "attempts": 1, "result": {"ok": True}})
        plan["steps"][1].update({"status": "completed", "attempts": 1, "result": {"ok": True}})
        plan["steps"][2].update({
            "status": "completed", "attempts": 1,
            "result": {
                "terminalStatus": "no_result",
                "artifact": {"kind": "no_match", "reasonCode": "insufficient_coverage"},
            },
        })
        plan["steps"][3].update({"status": "skipped", "attempts": 0})
        platform.store.save("plans", plan)

        with patch.object(platform, "_advance_plan") as advance:
            recovered = platform.retry_action(plan["id"])

        assert recovered["status"] == "running"
        assert recovered["steps"][0]["status"] == "completed"
        assert recovered["steps"][1]["status"] == "completed"
        assert recovered["steps"][2]["status"] == "pending"
        assert recovered["steps"][3]["status"] == "pending"
        advance.assert_called_once_with(plan["id"])
        retry_event = next(
            item for item in reversed(platform.store.events_after(workspace["id"]))
            if item["type"] == "plan.retry_started"
        )
        assert retry_event["payload"]["replayFromTool"] == "propose_timeline_edit"
        assert retry_event["payload"]["reason"] == "insufficient_coverage"


def test_retry_clears_cover_timestamp_misread_as_duration() -> None:
    goal = (
        "找出所有汽车相关画面，合成竖屏视频，并在顶部添加对应字幕。"
        "并选取54s出现的那个人作为封面，封面上写好上：小米牛逼！！雷军雷神！！！！"
    )
    steps = [{
        "id": "search", "title": "检索内容", "tool": "search_content",
        "arguments": {"query": "汽车"}, "dependencies": [],
        "expectedOutput": "候选", "sideEffect": "analysis", "estimatedSeconds": 1,
        "optional": False,
    }, {
        "id": "review", "title": "自动筛选", "tool": "review_content_evidence",
        "arguments": {"query": "汽车"}, "dependencies": ["search"],
        "expectedOutput": "选择", "sideEffect": "review", "estimatedSeconds": 1,
        "optional": False,
    }, {
        "id": "timeline", "title": "建立时间线", "tool": "propose_timeline_edit",
        "arguments": {
            "instruction": f"{goal}；目标 54 秒，允许浮动 ±5 秒",
            "targetSeconds": 54.0,
            "toleranceSeconds": 5.0,
            "durationSource": "explicit",
        },
        "dependencies": ["review"], "expectedOutput": "时间线",
        "sideEffect": "preview", "estimatedSeconds": 1, "optional": False,
    }, {
        "id": "qc", "title": "质检", "tool": "run_delivery_qc",
        "arguments": {"strict": True, "targetSeconds": 54.0, "toleranceSeconds": 5.0},
        "dependencies": ["timeline"], "expectedOutput": "质检",
        "sideEffect": "analysis", "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        workspace = platform.create_workspace(job_id="job_retry_cover_timestamp_duration")
        plan = {
            "id": "plan_retry_cover_timestamp_duration",
            "workspaceId": workspace["id"],
            "workspaceRevision": workspace["revision"],
            "goal": goal,
            "status": "no_result",
            "summary": "旧计划误把封面时间码当成目标时长",
            "skillId": "cliptalk-content-extractor",
            "brief": {
                "targetSeconds": 54,
                "durationExplicit": True,
                "durationSource": "explicit",
                "durationToleranceSeconds": 5,
            },
            "planningContext": {},
            "steps": copy.deepcopy(steps),
            "createdAt": "2026-09-14T00:00:00+00:00",
            "updatedAt": "2026-09-14T00:00:00+00:00",
        }
        plan["steps"][0].update({"status": "completed", "attempts": 1, "result": {"ok": True}})
        plan["steps"][1].update({"status": "completed", "attempts": 1, "result": {"ok": True}})
        plan["steps"][2].update({
            "status": "completed", "attempts": 1,
            "result": {
                "terminalStatus": "no_result",
                "artifact": {"kind": "no_match", "reasonCode": "insufficient_coverage"},
            },
        })
        plan["steps"][3].update({"status": "skipped", "attempts": 0})
        platform.store.save("plans", plan)

        with patch.object(platform, "_advance_plan"):
            recovered = platform.retry_action(plan["id"])

        timeline_args = recovered["steps"][2]["arguments"]
        qc_args = recovered["steps"][3]["arguments"]
        assert recovered["brief"]["targetSeconds"] is None
        assert recovered["brief"]["durationExplicit"] is False
        assert "targetSeconds" not in timeline_args
        assert "toleranceSeconds" not in timeline_args
        assert "目标 54 秒" not in timeline_args["instruction"]
        assert "targetSeconds" not in qc_args
        assert "toleranceSeconds" not in qc_args


def test_preview_ready_retry_clears_stale_agent_no_result_job_state() -> None:
    from app import main

    job_id = "job_stale_no_result_preview_ready"
    job = {
        "id": job_id, "status": "completed", "stage": "agent_no_result",
        "progress": 1.0, "detail": "旧的无结果提示",
        "agent": {"workspaceId": "ws_retry", "status": "no_result"},
    }
    workspace = {
        "id": "ws_retry", "jobId": job_id, "status": "preview_ready",
        "executionMode": "autonomous_review",
    }
    plan = {
        "id": "plan_retry", "planHash": "hash", "status": "preview_ready",
        "summary": "已生成审核样片", "skillId": "cliptalk-content-extractor",
        "steps": [{
            "id": "render", "title": "生成审核样片", "tool": "render_review_preview",
            "status": "completed",
        }],
    }
    with patch.dict(main.jobs, {job_id: job}, clear=False), patch.object(main, "save_job") as save:
        main.sync_agent_workspace_to_job(workspace, plan)

    assert job["status"] == "awaiting_agent_plan"
    assert job["stage"] == "agent_preview_review"
    assert job["actionRequired"] == "review_preview"
    assert job["progress"] == 1.0
    assert job["agent"]["status"] == "preview_ready"
    assert "旧的无结果提示" not in job["detail"]
    save.assert_called_once_with(job)


def test_qc_failed_preview_projects_repair_state_and_issue_ranges() -> None:
    from app import main

    job_id = "job_qc_failed_preview"
    job = {
        "id": job_id, "status": "awaiting_agent_plan", "stage": "agent_plan_running",
        "progress": .8, "outputs": [], "outputVersions": [],
    }
    workspace = {
        "id": "ws_qc_failed", "jobId": job_id, "status": "preview_ready",
        "executionMode": "autonomous_review",
    }
    plan = {
        "id": "plan_qc_failed", "status": "preview_ready", "steps": [{
            "id": "qc", "tool": "run_delivery_qc", "title": "检查成片质量",
            "status": "completed", "result": {"artifact": {
                "kind": "delivery_qc_report", "passed": False, "strict": True,
                "reports": [{"issues": [{
                    "severity": "error", "code": "freeze_frames",
                    "message": "检测到持续静止画面。",
                    "evidence": {"ranges": [{"start": 8, "end": 13, "duration": 5}]},
                }]}],
            }},
        }],
    }

    with patch.dict(main.jobs, {job_id: job}, clear=False), patch.object(main, "save_job"):
        main.sync_agent_workspace_to_job(workspace, plan)

    assert job["status"] == "awaiting_agent_plan"
    assert job["stage"] == "agent_qc_failed"
    assert job["actionRequired"] == "repair_and_recheck"
    assert job["agent"]["quality"]["status"] == "failed"
    assert job["agent"]["quality"]["issues"][0]["ranges"][0] == {
        "start": 8.0, "end": 13.0, "duration": 5.0,
    }


def test_workspace_rejects_a_second_planning_or_active_plan_request() -> None:
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        workspace = platform.create_workspace(job_id="job_test")

        reserved, _skill, _payload = platform.prepare_plan_request(
            workspace_id=workspace["id"], goal="先生成一份计划",
        )
        with pytest.raises(ValueError, match="正在生成"):
            platform.prepare_plan_request(workspace_id=workspace["id"], goal="不要并行生成第二份")
        platform.release_plan_request(
            workspace["id"], request_id=str(reserved["planningRequestId"]),
        )

        plan = platform.create_plan(workspace_id=workspace["id"], goal="生成一份可确认计划")
        with pytest.raises(ValueError, match="等待确认"):
            platform.create_plan(workspace_id=workspace["id"], goal="不要覆盖待确认计划")
        assert plan["status"] == "awaiting_confirmation"


def test_planning_progress_is_persisted_for_task_polling_and_reload() -> None:
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        snapshots: list[dict[str, Any]] = []
        platform.configure_workspace_state_listener(lambda workspace, _plan: snapshots.append(workspace))
        workspace = platform.create_workspace(job_id="job_progress")
        reserved, _skill, _payload = platform.prepare_plan_request(
            workspace_id=workspace["id"], goal="生成剪辑计划",
        )
        platform.record_planning_progress(reserved["id"], {
            "phase": "decomposing_goal", "title": "正在按主题组织剪辑结构",
            "detail": "正在整理回答顺序与删重策略。",
        })
        stored = platform.store.get("workspaces", reserved["id"])
        assert stored is not None
        assert stored["planningProgress"]["phase"] == "decomposing_goal"
        assert snapshots[-1]["planningProgress"]["title"] == "正在按主题组织剪辑结构"
        platform.release_plan_request(
            reserved["id"], request_id=str(reserved["planningRequestId"]),
        )


def test_stale_planning_reservation_is_recovered_after_a_server_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        workspace = platform.create_workspace(job_id="job_stale_planning")
        reserved, _skill, _payload = platform.prepare_plan_request(
            workspace_id=workspace["id"], goal="生成自动剪辑计划",
        )
        reserved["planningStartedAt"] = "invalid-interrupted-stream-time"
        platform.store.save("workspaces", reserved)

        assert platform.recover_stale_planning_requests(max_age_seconds=30) == 1
        recovered = platform.store.get("workspaces", workspace["id"])
        assert recovered is not None
        assert recovered["status"] == "ready"
        assert "planningRequestId" not in recovered
        assert platform.store.events_after(workspace["id"])[-1]["type"] == "planning.recovered"


def test_background_step_preserves_durable_handoff_result() -> None:
    steps = [{
        "id": "search", "title": "查找目标内容", "tool": "search_content",
        "arguments": {"query": "主讲人"}, "dependencies": [], "expectedOutput": "同源任务",
        "sideEffect": "analysis", "estimatedSeconds": 5, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps)
        future: Future[None] = Future()
        platform.configure_tool_dispatcher(lambda *_args: {
            "future": future, "operationId": "job_child:search",
            "job": {"id": "job_child", "status": "queued"},
        })
        workspace = platform.create_workspace(job_id="job_source")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="找主讲人")
        waiting = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert waiting["steps"][0]["status"] == "waiting_operation"

        future.set_result(None)
        completed = platform.store.get("plans", plan["id"])
        assert completed is not None
        assert completed["status"] == "preview_ready"
        assert completed["steps"][0]["result"]["job"]["id"] == "job_child"
        assert completed["steps"][0]["result"]["operationCompleted"] is True


def test_background_step_merges_worker_artifact_into_step_result() -> None:
    steps = [{
        "id": "qc", "title": "检查成片", "tool": "run_delivery_qc",
        "arguments": {"strict": True}, "dependencies": [], "expectedOutput": "质检报告",
        "sideEffect": "analysis", "estimatedSeconds": 5, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps)
        platform.install_skill(markdown="""---
name: qc-worker-test
description: Test asynchronous QC artifact handling.
allowed-tools: run_delivery_qc
---

# QC worker test
""", source="test", status="enabled")
        future: Future[dict[str, Any]] = Future()
        platform.configure_tool_dispatcher(lambda *_args: {
            "future": future, "operationId": "job_test:delivery_qc",
            "accepted": True,
        })
        workspace = platform.create_workspace(job_id="job_test")
        plan = platform.create_plan(
            workspace_id=workspace["id"], goal="检查成片", skill_id="qc-worker-test",
        )
        waiting = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert waiting["steps"][0]["status"] == "waiting_operation"

        future.set_result({"artifact": {"kind": "delivery_qc_report", "passed": True}})
        completed = platform.store.get("plans", plan["id"])
        assert completed is not None
        assert completed["steps"][0]["result"]["artifact"]["passed"] is True
        assert completed["steps"][0]["result"]["accepted"] is True


def test_delivery_qc_fails_when_requested_visual_deliverables_are_only_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app import main

    job_id = "job_delivery_visual_contract"
    filename = "review.mp4"
    (tmp_path / filename).write_bytes(b"not-read-because-probe-is-mocked")
    job = {
        "id": job_id,
        "outputDirectory": str(tmp_path),
        "brief": {
            "subtitleRequested": True,
            "graphicsRequested": True,
            "coverRequested": True,
            "coverIntroRequested": True,
            "coverTitle": "小米牛逼！",
        },
        "coverDraft": {
            "titleText": "小米牛逼！",
            "source": {"kind": "accepted_timeline", "editSessionId": "edit_1"},
        },
        "currentCoverVersionId": "cover_v001",
        "coverVersions": [{
            "id": "cover_v001", "titleText": "小米牛逼！",
            "titleLines": ["小米牛逼！"], "evidenceRefs": ["match_1"],
        }],
        "outputs": [{
            "filename": filename, "duration": 10.0,
            # Old metadata is intentionally not accepted as render proof.
            "subtitleMode": "burn", "coverIntro": {"enabled": False},
        }],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "analyze_rendered_media", lambda *_args, **_kwargs: {
        "passed": True, "issues": [], "media": {"duration": 10.0},
    })

    def submit(worker: Any) -> Future[dict[str, Any]]:
        future: Future[dict[str, Any]] = Future()
        future.set_result(worker())
        return future

    monkeypatch.setattr(main.output_preview_executor, "submit", submit)
    queued = main.dispatch_agent_tool({"jobId": job_id}, "run_delivery_qc", {"filename": filename})
    artifact = queued["future"].result()["artifact"]
    report = artifact["reports"][0]

    assert artifact["passed"] is False
    assert {issue["code"] for issue in report["issues"]} == {
        "requested_subtitles_not_rendered",
        "requested_text_not_rendered",
        "requested_cover_intro_not_rendered",
    }
    assert report["deliverables"]["cover"]["passed"] is True


def test_delivery_qc_accepts_verified_subtitles_text_and_current_cover_intro(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app import main

    job_id = "job_delivery_visual_verified"
    filename = "verified.mp4"
    (tmp_path / filename).write_bytes(b"not-read-because-probe-is-mocked")
    job = {
        "id": job_id,
        "outputDirectory": str(tmp_path),
        "brief": {
            "subtitleRequested": True, "graphicsRequested": True,
            "coverRequested": True, "coverIntroRequested": True,
            "coverTitle": "小米牛逼！",
        },
        "coverDraft": {
            "titleText": "小米牛逼！",
            "source": {"kind": "accepted_timeline", "editSessionId": "edit_1"},
        },
        "currentCoverVersionId": "cover_v001",
        "coverVersions": [{
            "id": "cover_v001", "titleText": "小米牛逼！",
            "titleLines": ["小米牛逼！"], "evidenceRefs": ["match_1"],
        }],
        "outputs": [{
            "filename": filename, "duration": 10.0,
            "overlayVerification": {
                "renderPipelineVersion": 2, "applied": True,
                "appliedCueCount": 3, "subtitleCueCount": 2, "textLayerCount": 1,
            },
            "coverIntro": {"enabled": True, "coverVersionId": "cover_v001"},
        }],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "analyze_rendered_media", lambda *_args, **_kwargs: {
        "passed": True, "issues": [], "media": {"duration": 10.0},
    })

    def submit(worker: Any) -> Future[dict[str, Any]]:
        future: Future[dict[str, Any]] = Future()
        future.set_result(worker())
        return future

    monkeypatch.setattr(main.output_preview_executor, "submit", submit)
    queued = main.dispatch_agent_tool({"jobId": job_id}, "run_delivery_qc", {"filename": filename})
    artifact = queued["future"].result()["artifact"]

    assert artifact["passed"] is True
    assert artifact["reports"][0]["issues"] == []
    assert all(
        value["passed"]
        for value in artifact["reports"][0]["deliverables"].values()
        if value["required"]
    )


def test_background_content_search_no_candidates_finishes_as_no_result() -> None:
    steps = [{
        "id": "search", "title": "检索内容", "tool": "search_content",
        "arguments": {"query": "产品新老替换和核心卖点"}, "dependencies": [],
        "expectedOutput": "候选", "sideEffect": "analysis",
        "estimatedSeconds": 5, "optional": False,
    }, {
        "id": "review", "title": "自动筛选", "tool": "review_content_evidence",
        "arguments": {"query": "产品新老替换和核心卖点"}, "dependencies": ["search"],
        "expectedOutput": "选择", "sideEffect": "review",
        "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps)
        future: Future[None] = Future()
        platform.configure_tool_dispatcher(lambda *_args: {
            "future": future,
            "operationId": "job_content:content_initial_search",
            "operation": "content_initial_search",
            "artifact": {
                "kind": "content_search_result",
                "jobId": "job_content",
                "query": "产品新老替换和核心卖点",
            },
        })
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id,
            "available": True,
            "jobStatus": "awaiting_agent_plan",
            "evidence": {
                "lastSearchStatus": "needs_clarification",
                "candidateCount": 3,
                "contentCandidateCount": 0,
                "coverageComplete": False,
                "lastSearchClarification": {
                    "kind": "coverage_incomplete",
                    "message": "当前没有找到可靠匹配，但必要识别尚未完整覆盖检索范围。",
                    "canContinue": False,
                },
            },
        })
        workspace = platform.create_workspace(job_id="job_content")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="产品新老替换和核心卖点")
        waiting = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert waiting["steps"][0]["status"] == "waiting_operation"

        future.set_result(None)
        completed = platform.store.get("plans", plan["id"])

        assert completed is not None
        assert completed["status"] == "no_result"
        assert completed["steps"][0]["status"] == "completed"
        assert completed["steps"][0]["result"]["terminalStatus"] == "no_result"
        assert completed["steps"][0]["result"]["artifact"]["reasonCode"] == "coverage_incomplete"
        assert completed["steps"][1]["status"] == "skipped"


def test_recover_completed_content_search_waiting_operation_after_restart() -> None:
    steps = [{
        "id": "search", "title": "检索内容", "tool": "search_content",
        "arguments": {"query": "汽车"}, "dependencies": [],
        "expectedOutput": "候选", "sideEffect": "analysis",
        "estimatedSeconds": 5, "optional": False,
    }, {
        "id": "review", "title": "自动筛选", "tool": "review_content_evidence",
        "arguments": {"query": "汽车"}, "dependencies": ["search"],
        "expectedOutput": "选择", "sideEffect": "review",
        "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps)
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id,
            "available": True,
            "jobStatus": "awaiting_agent_plan",
            "evidence": {
                "lastSearchStatus": "needs_clarification",
                "contentCandidateCount": 0,
                "lastSearchClarification": {
                    "kind": "no_visual_match",
                    "message": "没有找到可靠汽车画面。",
                },
            },
        })
        workspace = platform.create_workspace(job_id="job_restart_content")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="找出汽车画面并合成视频")
        plan["status"] = "running"
        workspace["status"] = "running"
        workspace["activePlanId"] = plan["id"]
        plan["steps"][0].update({
            "status": "waiting_operation",
            "operationId": "job_restart_content:content_initial_search",
            "result": {
                "operation": "content_initial_search",
                "artifact": {
                    "kind": "content_search_result",
                    "jobId": "job_restart_content",
                    "query": "汽车",
                },
            },
        })
        platform.store.save("workspaces", workspace)
        platform.store.save("plans", plan)

        assert platform.recover_completed_operations() == 1
        recovered = platform.store.get("plans", plan["id"])

        assert recovered is not None
        assert recovered["status"] == "no_result"
        assert recovered["steps"][0]["status"] == "completed"
        assert recovered["steps"][1]["status"] == "skipped"


def test_identity_step_pauses_for_structured_confirmation() -> None:
    steps = [{
        "id": "people", "title": "选择人物", "tool": "select_people",
        "arguments": {}, "dependencies": [], "expectedOutput": "已确认的人物",
        "sideEffect": "identity", "estimatedSeconds": 5, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps)
        platform.configure_tool_dispatcher(lambda *_args: {"unexpected": True})
        workspace = platform.create_workspace(job_id="job_test")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="保留主讲人")
        paused = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert paused["status"] == "action_required"

        with pytest.raises(ValueError, match="确认结果"):
            platform.resolve_action(plan["id"], approved=True, value={"confirmedInReviewPanel": True})

        completed = platform.resolve_action(plan["id"], approved=True, value={
            "context": {"jobId": "job_test", "stepId": "people"},
            "selection": {"personIds": ["person_1"]},
        })
        assert completed["status"] == "preview_ready"
        assert completed["steps"][0]["result"]["userConfirmed"] is True


def test_timeline_draft_and_confirmation_are_separate_gates_before_subtitles() -> None:
    steps = [
        {
            "id": "inspect", "title": "核查素材", "tool": "inspect_workspace",
            "arguments": {}, "dependencies": [], "expectedOutput": "素材状态",
            "sideEffect": "read", "estimatedSeconds": 1, "optional": False,
        },
        {
            "id": "timeline", "title": "整理时间线草稿", "tool": "propose_timeline_edit",
            "arguments": {"instruction": "按主题组织"}, "dependencies": ["inspect"],
            "expectedOutput": "时间线草稿", "sideEffect": "preview", "estimatedSeconds": 1, "optional": False,
        },
        {
            "id": "confirm_timeline", "title": "确认时间线草稿", "tool": "confirm_timeline_edit",
            "arguments": {}, "dependencies": ["timeline"],
            "expectedOutput": "已应用的时间线", "sideEffect": "preview", "estimatedSeconds": 1, "optional": False,
        },
        {
            "id": "subtitles", "title": "整理字幕草稿", "tool": "prepare_subtitle_review",
            "arguments": {"style": "clean"}, "dependencies": ["confirm_timeline"],
            "expectedOutput": "字幕草稿", "sideEffect": "preview", "estimatedSeconds": 1, "optional": False,
        },
        {
            "id": "review", "title": "渲染审核样片", "tool": "render_review_preview",
            "arguments": {"subtitleMode": "burned_in_review_watermarked_low_bitrate"}, "dependencies": ["subtitles"],
            "expectedOutput": "低码率带水印审阅样片", "sideEffect": "preview", "estimatedSeconds": 1, "optional": False,
        },
    ]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps)
        calls: list[str] = []

        def dispatch(_workspace: dict[str, Any], tool: str, _arguments: dict[str, Any]) -> dict[str, Any]:
            calls.append(tool)
            if tool in {"propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review"}:
                return {"actionRequired": True, "action": tool}
            return {"artifact": {"tool": tool}}

        platform.configure_tool_dispatcher(dispatch)
        workspace = platform.create_workspace(job_id="job_test")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="制作访谈精华")
        paused = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])

        assert paused["status"] == "action_required"
        assert calls == ["inspect_workspace", "propose_timeline_edit"]
        assert [step["status"] for step in paused["steps"]] == ["completed", "action_required", "pending", "pending", "pending"]

        paused = platform.resolve_action(plan["id"], approved=True, value={
            "context": {"jobId": "job_test", "stepId": "timeline"},
            "selection": {"kind": "timeline_proposal", "editSessionId": "edit_1", "proposalId": "proposal_1"},
        })
        assert paused["status"] == "action_required"
        assert calls == ["inspect_workspace", "propose_timeline_edit", "confirm_timeline_edit"]

        paused = platform.resolve_action(plan["id"], approved=True, value={
            "context": {"jobId": "job_test", "stepId": "confirm_timeline"},
            "selection": {"kind": "timeline_confirmation", "editSessionId": "edit_1", "revision": 1},
        })
        assert paused["status"] == "action_required"
        assert calls == ["inspect_workspace", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review"]

        paused = platform.resolve_action(plan["id"], approved=True, value={
            "context": {"jobId": "job_test", "stepId": "subtitles"},
            "review": {"kind": "subtitle_review"},
        })
        assert paused["status"] == "preview_ready"
        assert calls == ["inspect_workspace", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview"]


def test_missing_timeline_artifact_can_be_retried_in_the_existing_plan() -> None:
    steps = [{
        "id": "timeline", "title": "整理时间线草稿", "tool": "propose_timeline_edit",
        "arguments": {"instruction": "按高光组织"}, "dependencies": [],
        "expectedOutput": "时间线草稿", "sideEffect": "preview",
        "estimatedSeconds": 1, "optional": False,
    }, {
        "id": "confirm_timeline", "title": "确认时间线草稿", "tool": "confirm_timeline_edit",
        "arguments": {}, "dependencies": ["timeline"], "expectedOutput": "已应用的时间线",
        "sideEffect": "preview", "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps)
        calls = 0

        def dispatch(_workspace: dict[str, Any], tool: str, _arguments: dict[str, Any]) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if tool == "propose_timeline_edit" and calls == 1:
                return {"actionRequired": True, "action": "timeline_proposal", "sessionId": None}
            return {
                "actionRequired": True, "action": tool,
                "sessionId": "edit_recovered", "proposalId": "proposal_recovered",
            }

        platform.configure_tool_dispatcher(dispatch)
        workspace = platform.create_workspace(job_id="job_retry_timeline")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="生成高光草案")
        paused = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert paused["steps"][0]["result"]["sessionId"] is None

        recovered = platform.retry_action(plan["id"])

        assert calls == 2
        assert recovered["status"] == "action_required"
        assert recovered["steps"][0]["result"]["sessionId"] == "edit_recovered"
        assert recovered["steps"][0]["result"]["proposalId"] == "proposal_recovered"


def test_legacy_autonomous_subtitle_gate_retries_as_automatic_review() -> None:
    steps = [{
        "id": "subtitles", "title": "生成并校对字幕", "tool": "prepare_subtitle_review",
        "arguments": {"style": "clean", "requireConfirmedDraft": True}, "dependencies": [],
        "expectedOutput": "字幕草稿", "sideEffect": "preview",
        "estimatedSeconds": 1, "optional": False,
    }, {
        "id": "preview", "title": "生成带字幕审核样片", "tool": "render_review_preview",
        "arguments": {"subtitleMode": "burned_in_review_watermarked_low_bitrate"},
        "dependencies": ["subtitles"], "expectedOutput": "审核样片", "sideEffect": "preview",
        "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        calls: list[tuple[str, dict[str, Any]]] = []

        def dispatch(_workspace: dict[str, Any], tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            calls.append((tool, dict(arguments)))
            if tool == "prepare_subtitle_review" and len(calls) == 1:
                return {"actionRequired": True, "action": "subtitle_review", "sessionId": "edit_1"}
            return {"artifact": {"kind": "subtitle_review_draft" if tool == "prepare_subtitle_review" else "review_preview"}}

        platform.configure_tool_dispatcher(dispatch)
        workspace = platform.create_workspace(job_id="job_legacy_subtitle_gate")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="自动生成字幕审核样片")
        plan["executionMode"] = "autonomous_review"
        platform.store.save("plans", plan)
        paused = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert paused["status"] == "action_required"

        recovered = platform.retry_action(plan["id"])

        assert recovered["status"] == "preview_ready"
        assert [tool for tool, _arguments in calls] == [
            "prepare_subtitle_review", "prepare_subtitle_review", "render_review_preview",
        ]
        assert calls[1][1]["requireConfirmedDraft"] is False
        assert calls[1][1]["autoReview"] is True
        retry_event = next(
            item for item in reversed(platform.store.events_after(workspace["id"]))
            if item["type"] == "action.retried"
        )
        assert retry_event["payload"]["reason"] == "migrate_manual_subtitle_gate_to_automatic_review"


def test_missing_subtitle_draft_replays_preparation_before_layout() -> None:
    steps = [{
        "id": "subtitles", "title": "自动生成并校对字幕草稿", "tool": "prepare_subtitle_review",
        "arguments": {"style": "clean", "autoReview": True}, "dependencies": [],
        "expectedOutput": "自动校对字幕草稿", "sideEffect": "preview",
        "estimatedSeconds": 1, "optional": False,
    }, {
        "id": "layout", "title": "应用顶部字幕排版", "tool": "layout_subtitles",
        "arguments": {"position": "top", "style": "clean"}, "dependencies": ["subtitles"],
        "expectedOutput": "顶部字幕排版", "sideEffect": "preview",
        "estimatedSeconds": 1, "optional": False,
    }, {
        "id": "preview", "title": "生成带字幕审核样片", "tool": "render_review_preview",
        "arguments": {"subtitleMode": "burned_in_review_watermarked_low_bitrate"},
        "dependencies": ["layout"], "expectedOutput": "审核样片", "sideEffect": "preview",
        "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        calls: list[str] = []
        first_layout = True

        def dispatch(_workspace: dict[str, Any], tool: str, _arguments: dict[str, Any]) -> dict[str, Any]:
            nonlocal first_layout
            calls.append(tool)
            if tool == "layout_subtitles" and first_layout:
                first_layout = False
                return {
                    "actionRequired": True,
                    "action": "subtitle_review",
                    "message": "请先生成并确认当前时间线的字幕草稿，再调整字幕排版。",
                }
            return {"artifact": {"kind": tool}}

        platform.configure_tool_dispatcher(dispatch)
        workspace = platform.create_workspace(job_id="job_missing_subtitle_layout")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="在顶部添加字幕并生成审核样片")
        plan["executionMode"] = "autonomous_review"
        platform.store.save("plans", plan)
        paused = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])

        assert paused["status"] == "action_required"
        assert paused["steps"][1]["tool"] == "layout_subtitles"
        assert paused["steps"][1]["status"] == "action_required"
        with pytest.raises(ValueError, match="不能通过空确认跳过"):
            platform.resolve_action(plan["id"], approved=True, value={
                "context": {
                    "jobId": workspace["jobId"],
                    "stepId": paused["steps"][1]["id"],
                },
                "review": {"kind": "review"},
            })

        recovered = platform.retry_action(plan["id"])

        assert recovered["status"] == "preview_ready"
        assert calls == [
            "prepare_subtitle_review", "layout_subtitles",
            "prepare_subtitle_review", "layout_subtitles", "render_review_preview",
        ]
        assert all(step["status"] == "completed" for step in recovered["steps"])
        retry_event = next(
            item for item in reversed(platform.store.events_after(workspace["id"]))
            if item["type"] == "action.retried"
        )
        assert retry_event["payload"]["reason"] == "subtitle_layout_missing_draft"
        assert retry_event["payload"]["replayFromTool"] == "prepare_subtitle_review"


def test_timeline_actions_require_a_pending_draft_then_an_applied_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_timeline_gate"
    job = {
        "id": job_id, "revision": 7, "activeEditSessionId": "edit_1",
        "editSessions": [{
            "id": "edit_1", "revision": 0,
            "pendingProposal": {"id": "proposal_1", "status": "pending"},
        }],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    workspace = {"jobId": job_id}

    with pytest.raises(ValueError, match="生成待审核的时间线草案"):
        main.validate_agent_action_resolution(workspace, {
            "tool": "propose_timeline_edit",
        }, {
            "context": {"jobId": job_id},
            "selection": {"editSessionId": "edit_1", "proposalId": "missing_proposal"},
        })

    proposed = main.validate_agent_action_resolution(workspace, {
        "tool": "propose_timeline_edit",
    }, {
        "context": {"jobId": job_id},
        "selection": {"editSessionId": "edit_1", "proposalId": "proposal_1"},
    })
    assert proposed["verifiedJobRevision"] == 7

    job["editSessions"][0].update({"revision": 1, "pendingProposal": None})
    confirmed = main.validate_agent_action_resolution(workspace, {
        "tool": "confirm_timeline_edit",
    }, {
        "context": {"jobId": job_id},
        "selection": {"editSessionId": "edit_1", "revision": 1},
    })
    assert confirmed["verifiedJobRevision"] == 7


def test_propose_timeline_tool_generates_the_review_draft_it_requires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_proposal"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "content_search",
        "videoInfo": {"duration": 60}, "editSessions": [],
        "contentSearch": {
            "id": "search_1",
            "candidates": [{"id": "match_1", "start": 5, "end": 14, "title": "核心回答"}],
            "reviewDraft": {"selectedMatchIds": ["match_1"], "orderedMatchIds": ["match_1"]},
        },
    }
    from app.content_contract import build_contract, confirm_human_range
    for match in job["contentSearch"]["candidates"]:
        confirm_human_range(match, build_contract(job["contentSearch"]))
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    def generate_proposal(_job_id: str, session_id: str, request: Any) -> dict[str, Any]:
        session = main.find_edit_session(job, session_id)
        proposal = {
            "id": "proposal_agent_1", "status": "pending", "title": "Agent 时间线草案",
            "summary": request.text, "operations": [],
        }
        session["pendingProposal"] = proposal
        return {"proposal": proposal, "session": session}

    monkeypatch.setattr(main, "create_edit_session_proposal", generate_proposal)
    result = main.dispatch_agent_tool(
        {"jobId": job_id}, "propose_timeline_edit",
        {"instruction": "删除重复表达并保留完整观点", "variantCount": 1},
    )

    assert result["actionRequired"] is True
    assert result["proposalId"] == "proposal_agent_1"
    assert "Agent 已生成待审核时间线草案" in result["message"]
    session = job["editSessions"][0]
    assert session["pendingProposal"]["id"] == "proposal_agent_1"
    assert session["agentTimelineRequest"]["instruction"] == "删除重复表达并保留完整观点"


def test_subtitle_layout_requires_an_existing_confirmed_subtitle_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_caption_layout_gate"
    session = {"id": "edit_caption", "revision": 2, "subtitleEnabled": False, "subtitleDraftId": None}
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "activeEditSessionId": session["id"],
        "editSessions": [session], "workDirectory": "/tmp/not-used",
    })

    result = main.dispatch_agent_tool(
        {"jobId": job_id}, "layout_subtitles", {"position": "top", "style": "clean"},
    )

    assert result["actionRequired"] is True
    assert result["action"] == "subtitle_review"
    assert "先生成并确认" in result["message"]
    assert session["revision"] == 2


def test_export_subtitles_tool_returns_download_artifact_without_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_export_subtitles"
    filename = "review output.mp4"
    job = {
        "id": job_id,
        "revision": 1,
        "outputDirectory": "/tmp/not-used",
        "outputVersions": [{
            "id": "v1",
            "number": 1,
            "outputs": [{
                "filename": filename,
                "duration": 2.0,
                "subtitleCues": [
                    {"start": 0.0, "end": 1.2, "text": "你好"},
                    {"start": 1.2, "end": 2.0, "text": "世界"},
                ],
            }],
        }],
    }
    monkeypatch.setitem(main.jobs, job_id, job)

    result = main.dispatch_agent_tool(
        {"jobId": job_id},
        "export_subtitles",
        {"format": "vtt"},
    )

    artifact = result["artifact"]
    assert artifact["kind"] == "subtitle_export"
    assert artifact["filename"] == filename
    assert artifact["format"] == "vtt"
    assert artifact["cueCount"] == 2
    assert artifact["downloadUrl"] == f"/api/jobs/{job_id}/outputs/review%20output.mp4/subtitles?format=vtt"
    assert "没有生成或修改视频" in artifact["message"]


def test_autonomous_subtitle_review_runs_without_a_manual_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_caption_review_gate"
    session = {
        "id": "edit_caption", "revision": 2,
        "clips": [{"id": "clip_1", "sourceStart": 0.0, "sourceEnd": 2.0}],
        "subtitleEnabled": False, "subtitleDraftId": None,
    }
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "activeEditSessionId": session["id"],
        "editSessions": [session],
    })
    completed: Future[dict[str, Any]] = Future()
    completed.set_result({"artifact": {"kind": "subtitle_review_draft", "autoReviewed": True}})
    submitted: dict[str, Any] = {}

    def submit(target: Any, *args: Any) -> Future[dict[str, Any]]:
        submitted.update({"target": target, "args": args})
        return completed

    monkeypatch.setattr(main.output_preview_executor, "submit", submit)

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "prepare_subtitle_review",
        {"style": "clean", "requireConfirmedDraft": True},
    )

    assert result["accepted"] is True
    assert result["operation"] == "agent_subtitle_review"
    assert result["future"] is completed
    assert result["sessionId"] == session["id"]
    assert "actionRequired" not in result
    assert submitted == {
        "target": main.run_agent_auto_subtitle_review,
        "args": (job_id, session["id"], "clean"),
    }


def test_agent_auto_subtitle_review_applies_only_low_risk_corrections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_caption_auto_review"
    session = {
        "id": "edit_caption_auto", "revision": 2,
        "clips": [{"id": "clip_1", "sourceStart": 0.0, "sourceEnd": 2.0}],
        "subtitleEnabled": False, "subtitleDraftId": None,
    }
    job = {
        "id": job_id, "revision": 1, "activeEditSessionId": session["id"],
        "editSessions": [session], "workDirectory": "/tmp/not-used",
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "_subtitle_transcription_complete", lambda _job: True)
    monkeypatch.setattr(main, "create_subtitle_draft", lambda *_args, **_kwargs: {"draft": {
        "id": "sub_1234567890abcdef", "revision": 1,
        "cues": [
            {"id": "cue_low", "text": "小米苏七", "suggestedText": "小米 SU7", "suggestionStatus": "none"},
            {"id": "cue_medium", "text": "一百公里", "suggestedText": "100 公里", "suggestionStatus": "none"},
        ],
    }})

    def suggest(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"suggestionCount": 2, "draft": {
            "id": "sub_1234567890abcdef", "revision": 2,
            "cues": [
                {"id": "cue_low", "text": "小米苏七", "suggestedText": "小米 SU7", "suggestionStatus": "pending", "suggestionRisk": "low"},
                {"id": "cue_medium", "text": "一百公里", "suggestedText": "100 公里", "suggestionStatus": "pending", "suggestionRisk": "medium"},
            ],
        }}

    saved: dict[str, Any] = {}
    monkeypatch.setattr(main, "suggest_subtitle_corrections", suggest)
    monkeypatch.setattr(main, "save_subtitle_draft_file", lambda _directory, draft: saved.update(draft))
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    result = main.run_agent_auto_subtitle_review(job_id, session["id"], "clean")

    assert result["artifact"]["autoReviewed"] is True
    assert result["artifact"]["lowRiskAppliedCount"] == 1
    assert saved["status"] == "auto_reviewed"
    assert saved["cues"][0]["text"] == "小米 SU7"
    assert saved["cues"][0]["suggestionStatus"] == "accepted"
    assert saved["cues"][1]["text"] == "一百公里"
    assert saved["cues"][1]["suggestionStatus"] == "deferred"
    assert session["subtitleEnabled"] is True
    assert session["subtitleDraftId"] == "sub_1234567890abcdef"
    assert session["subtitleReviewMode"] == "automatic"


def test_subtitle_layout_updates_the_confirmed_draft_without_replacing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_caption_layout_update"
    draft_id = "sub_confirmed"
    session = {
        "id": "edit_caption", "revision": 2,
        "subtitleEnabled": True, "subtitleDraftId": draft_id,
    }
    job = {
        "id": job_id, "revision": 1, "activeEditSessionId": session["id"],
        "editSessions": [session], "workDirectory": "/tmp/not-used",
    }
    draft = {
        "id": draft_id, "jobId": job_id, "status": "confirmed", "revision": 3,
        "cues": [{"id": "cue_1", "start": 0.0, "end": 1.0, "text": "已确认字幕"}],
        "globalStyle": {"vertical": "bottom"}, "cueStyleOverrides": {},
    }
    saved: dict[str, Any] = {}
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "_subtitle_draft_for_job", lambda _job, _draft_id: draft)
    monkeypatch.setattr(main, "save_subtitle_draft_file", lambda _directory, value: saved.update(value))
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    result = main.dispatch_agent_tool(
        {"jobId": job_id}, "layout_subtitles", {"position": "top", "style": "clean"},
    )

    artifact = result["artifact"]
    assert artifact["subtitleDraftId"] == draft_id
    assert artifact["cueCount"] == 1
    assert saved["id"] == draft_id
    assert saved["revision"] == 4
    assert saved["globalStyle"]["vertical"] == "top"
    assert session["subtitleDraftId"] == draft_id
    assert session["revision"] == 3


def test_workspace_inspection_returns_typed_no_result_for_missing_edit_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_missing_edit_prerequisite"
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "workflowKind": "content_search",
        "videoInfo": {"duration": 60}, "outputs": [], "editSessions": [],
        "request": {"sourceScopeKind": "all"},
    })

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "inspect_workspace",
        {
            "requiredState": "current_output",
            "preconditionCode": "missing_current_output",
            "preconditionMessage": "画幅转换需要当前任务已有可审核成片",
        },
    )

    assert result["terminalStatus"] == "no_result"
    assert result["artifact"]["kind"] == "precondition_missing"
    assert result["artifact"]["reasonCode"] == "missing_current_output"
    assert "前置条件未满足" in result["message"]
    assert any("当前任务生成并确认成片" in item for item in result["artifact"]["suggestions"])


def test_format_only_proposal_uses_full_source_without_highlight_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_source_passthrough"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "highlight",
        "videoInfo": {"duration": 65.8}, "editSessions": [], "candidates": [],
        "request": {
            "targetSeconds": "auto", "totalTargetSeconds": None,
            "sourceScope": {"start": 0.0, "end": 65.8},
        },
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    def generate_proposal(_job_id: str, session_id: str, request: Any) -> dict[str, Any]:
        session = main.find_edit_session(job, session_id)
        proposal = main.build_secondary_edit_proposal(
            job, session, text=request.text,
            selected_clip_ids=[str(item["id"]) for item in session["clips"]],
            model_result={
                "title": "完整素材画幅转换",
                "summary": "保留全片",
                "operations": [{
                    "type": "reorder_clips",
                    "clipIds": [str(item["id"]) for item in session["clips"]],
                }],
            },
        )
        return {"proposal": proposal, "session": session}

    monkeypatch.setattr(main, "create_edit_session_proposal", generate_proposal)
    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "propose_timeline_edit",
        {"instruction": "输出 1:1 方屏，左右人物不能被裁掉", "variantCount": 1},
    )

    assert result["actionRequired"] is False
    assert result["proposalId"]
    session = job["editSessions"][0]
    assert session["title"] == "完整素材画幅转换"
    assert session["duration"] == 65.8
    assert session["clips"][0]["sourceStart"] == 0.0
    assert session["clips"][0]["sourceEnd"] == 65.8
    assert job["contentSearch"]["reviewDraft"]["source"] == "agent_source_passthrough"


def test_agent_highlight_analysis_does_not_start_legacy_auto_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_highlight_evidence_only"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "highlight",
        "status": "awaiting_agent_plan", "request": {},
        "videoInfo": {"duration": 90},
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    future: Future[dict[str, Any]] = Future()
    monkeypatch.setattr(main, "submit_workflow_analysis", lambda *_args, **_kwargs: future)

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "analyze_highlights", {"instruction": "剪演唱高潮", "targetSeconds": 45},
    )

    assert result["future"] is future
    assert job["autoCompose"] is False
    assert job["request"]["targetSeconds"] == 45


def test_autonomous_speaker_selection_uses_one_reliable_discovery_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh speaker evidence must not be mistaken for an empty selection."""
    from app import main

    job_id = "job_agent_reliable_speaker"
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "workflowKind": "speaker_edit",
        "taskMode": "content_extract", "videoInfo": {"duration": 60},
        "voiceDiscovery": {"status": "ready"},
    })
    persisted: list[dict[str, Any]] = []

    def select_voice(_job_id: str, request: Any) -> dict[str, Any]:
        persisted.append({
            "speakerRefs": list(request.speakerRefs), "mode": request.mode,
            "query": request.query,
        })
        return {"accepted": True, "job": {"id": job_id}}

    monkeypatch.setattr(main, "select_current_voices", select_voice)
    monkeypatch.setattr(main, "_public_current_voice_catalog", lambda _job: [{
        "speakerRef": "Speaker 2", "requiresReview": False,
        "quality": {"suspectedMixed": False},
        "narration": {"status": "candidate", "score": 0.906},
    }])

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "select_speakers", {"mode": "include"},
    )

    assert result["artifact"]["selectedIds"] == ["Speaker 2"]
    assert result["artifact"]["source"] == "voice_timeline_heuristics"
    assert persisted == [{"speakerRefs": ["Speaker 2"], "mode": "include", "query": ""}]


def test_autonomous_speaker_selection_honors_explicit_anonymous_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_explicit_speaker_b"
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "workflowKind": "speaker_edit",
        "taskMode": "content_extract", "videoInfo": {"duration": 60},
        "voiceDiscovery": {"status": "ready"},
        "voiceSpeakerCatalog": [
            {"speakerRef": "SPEAKER_00", "requiresReview": False, "quality": {}},
            {"speakerRef": "SPEAKER_01", "requiresReview": True, "quality": {}},
        ],
    })
    persisted: list[list[str]] = []

    def select_voice(_job_id: str, request: Any) -> dict[str, Any]:
        persisted.append(list(request.speakerRefs))
        return {"accepted": True, "job": {"id": job_id}}

    monkeypatch.setattr(main, "select_current_voices", select_voice)
    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "select_speakers", {"mode": "include", "label": "说话人 B"},
    )

    assert result["artifact"]["selectedIds"] == ["SPEAKER_01"]
    assert result["artifact"]["source"] == "explicit_anonymous_label"
    assert persisted == [["SPEAKER_01"]]


def test_autonomous_person_selection_resolves_explicit_visible_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_black_shirt"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "person_edit",
        "taskMode": "content_extract", "request": {},
        "videoInfo": {"duration": 60},
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "_load_content_person_index", lambda _job: {
        "personTracks": [], "persons": [{"id": "person_2", "representativeTime": 3.0}],
    })
    monkeypatch.setattr(main, "_content_person_catalog", lambda _job, _index: [
        {"id": "person_1", "representativeTime": 1.0},
        {"id": "person_2", "representativeTime": 3.0},
    ])
    monkeypatch.setattr(main, "_match_person_catalog_by_visual_description", lambda *_args, **_kwargs: (
        [{"id": "person_2", "representativeTime": 3.0}],
        {"reliablePersonIds": ["person_2"], "uncertainPersonIds": []},
    ))
    selected: list[list[str]] = []

    def persist(_job_id: str, request: Any, **_kwargs: Any) -> dict[str, Any]:
        selected.append(list(request.personIds))
        return {"accepted": True}

    monkeypatch.setattr(main, "select_content_person_target", persist)
    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "select_people", {"mode": "include", "description": "穿黑色上衣的人"},
    )

    assert result["artifact"]["selectedIds"] == ["person_2"]
    assert result["artifact"]["source"] == "visual_description_consensus"
    assert selected == [["person_2"]]


def test_autonomous_person_selection_adopts_reliable_track_results_without_review_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_black_shirt_tracks"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "person_edit",
        "taskMode": "content_extract", "request": {},
        "videoInfo": {"duration": 60},
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "_load_content_person_index", lambda _job: {
        "personTracks": [], "persons": [{"id": "person_2", "representativeTime": 3.0}],
    })
    monkeypatch.setattr(main, "_content_person_catalog", lambda _job, _index: [
        {"id": "person_2", "representativeTime": 3.0},
    ])
    monkeypatch.setattr(main, "_match_person_catalog_by_visual_description", lambda *_args, **_kwargs: (
        [{"id": "person_2", "representativeTime": 3.0}],
        {"reliablePersonIds": ["person_2"], "uncertainPersonIds": []},
    ))

    def persist(_job_id: str, _request: Any, **_kwargs: Any) -> dict[str, Any]:
        job.update({
            "status": "awaiting_content_confirmation",
            "stage": "content_search_ready",
            "actionRequired": "review_content",
            "contentSearch": {
                "id": "search_person_2",
                "candidates": [
                    {
                        "id": "match_reliable", "start": 1.0, "end": 4.0,
                        "confidenceTier": "reliable", "selected": True,
                    },
                    {
                        "id": "match_possible", "start": 5.0, "end": 7.0,
                        "confidenceTier": "possible", "requiresReview": True,
                    },
                ],
            },
        })
        return {"accepted": True}

    monkeypatch.setattr(main, "select_content_person_target", persist)
    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "select_people", {"mode": "include", "description": "穿黑色上衣的人"},
    )

    assert result["artifact"]["matchIds"] == ["match_reliable"]
    assert job["status"] == main.AWAITING_AGENT_PLAN
    assert job["stage"] == "agent_plan_running"
    assert job["actionRequired"] is None
    assert job["contentSearch"]["reviewDraft"]["selectedMatchIds"] == ["match_reliable"]


def test_autonomous_person_selection_model_failure_becomes_typed_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_person_model_failure"
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "workflowKind": "person_edit",
        "taskMode": "content_extract", "request": {}, "videoInfo": {"duration": 60},
    })
    monkeypatch.setattr(main, "_load_content_person_index", lambda _job: {"personTracks": []})
    monkeypatch.setattr(main, "_content_person_catalog", lambda _job, _index: [
        {"id": "person_1", "representativeTime": 1.0},
    ])
    monkeypatch.setattr(
        main, "_match_person_catalog_by_visual_description",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("invalid JSON")),
    )

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "select_people", {"mode": "include", "description": "穿黑色上衣的人"},
    )

    assert result["terminalStatus"] == "no_result"
    assert result["artifact"]["reasonCode"] == "identity_verification_unavailable"
    assert "invalid JSON" in result["artifact"]["message"]


def test_agent_speaker_search_keeps_the_selected_voice_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_speaker_scoped_search"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "speaker_edit",
        "taskMode": "content_extract", "status": "awaiting_agent_plan",
        "stage": "agent_plan_running", "videoInfo": {"duration": 60},
        "contentSearch": {
            "id": "speaker_search_1",
            "intent": {
                "schemaVersion": "current-voice-target-intent-v2",
                "speakerRefs": ["Speaker 2"], "voiceSelectionMode": "include",
            },
            "candidates": [],
        },
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    calls: list[tuple[str, list[str], str, str]] = []

    def scoped_search(target_job_id: str, refs: list[str], query: str, mode: str) -> dict[str, Any]:
        calls.append((target_job_id, refs, query, mode))
        job["contentSearch"]["candidates"] = [{"id": "speaker_match_1"}]
        return job

    monkeypatch.setattr(main, "_apply_current_speakers_search", scoped_search)
    monkeypatch.setattr(main, "queue_content_followup", lambda *_args, **_kwargs: pytest.fail("must not leave speaker scope"))

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "search_content", {"query": "最有冲击力的一句话"},
    )

    assert calls == [(job_id, ["Speaker 2"], "最有冲击力的一句话", "include")]
    assert result["artifact"]["kind"] == "speaker_scoped_content_search"
    assert result["artifact"]["candidateCount"] == 1
    assert job["status"] == "awaiting_agent_plan"


def test_ambiguous_autonomous_identity_selection_requests_review_not_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_ambiguous_speaker"
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "workflowKind": "speaker_edit",
        "taskMode": "content_extract", "videoInfo": {"duration": 60},
        "voiceDiscovery": {"status": "ready"},
    })
    monkeypatch.setattr(main, "_public_current_voice_catalog", lambda _job: [
        {
            "speakerRef": "Speaker 1", "requiresReview": False,
            "quality": {"suspectedMixed": False},
            "narration": {"status": "candidate", "score": 0.91},
        },
        {
            "speakerRef": "Speaker 2", "requiresReview": False,
            "quality": {"suspectedMixed": False},
            "narration": {"status": "candidate", "score": 0.88},
        },
    ])

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "select_speakers", {"mode": "include"},
    )

    assert result["actionRequired"] is True
    assert result["action"] == "identity_selection"
    assert "说话人面板" in result["message"]
    assert "terminalStatus" not in result


def test_autonomous_timeline_is_applied_and_queued_for_review_without_user_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_autonomous"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "content_search",
        "videoInfo": {"duration": 60}, "editSessions": [], "outputVersions": [],
        "contentSearch": {
            "id": "search_auto",
            "candidates": [{"id": "match_auto", "start": 4, "end": 12, "title": "核心片段"}],
            "reviewDraft": {"selectedMatchIds": ["match_auto"], "orderedMatchIds": ["match_auto"]},
        },
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    from app.content_contract import build_contract, confirm_human_range
    for match in job["contentSearch"]["candidates"]:
        confirm_human_range(match, build_contract(job["contentSearch"]))

    def generate_proposal(_job_id: str, session_id: str, request: Any) -> dict[str, Any]:
        session = main.find_edit_session(job, session_id)
        clip_ids = [str(item["id"]) for item in session["clips"]]
        proposal = {
            "id": "proposal_auto", "status": "pending", "baseRevision": session["revision"],
            "title": "自动审核方案", "summary": request.text,
            "operations": [{"type": "reorder_clips", "clipIds": clip_ids}],
        }
        session["pendingProposal"] = proposal
        return {"proposal": proposal, "session": session}

    queued: dict[str, Any] = {}
    future: Future[dict[str, Any]] = Future()

    def queue(_job_id: str, target: Any, variants: list[dict[str, Any]]) -> Future[dict[str, Any]]:
        queued.update({"target": target, "variants": variants})
        return future

    monkeypatch.setattr(main, "create_edit_session_proposal", generate_proposal)
    monkeypatch.setattr(main, "submit_render_task", queue)
    workspace = {"jobId": job_id, "executionMode": "autonomous_review", "activePlanId": "plan_auto"}

    proposed = main.dispatch_agent_tool(workspace, "propose_timeline_edit", {
        "instruction": "保留完整观点并删除重复表达", "variantCount": 1,
    })
    assert proposed["actionRequired"] is False
    assert proposed["timelineBatch"][0]["proposalId"] == "proposal_auto"

    applied = main.dispatch_agent_tool(workspace, "confirm_timeline_edit", {})
    session = job["editSessions"][0]
    assert applied["artifact"]["kind"] == "applied_timeline_batch"
    assert session["pendingProposal"] is None
    assert session["revision"] == 1

    rendering = main.dispatch_agent_tool(workspace, "render_review_preview", {})
    assert rendering["accepted"] is True
    assert queued["target"] is main.run_agent_review_batch
    assert queued["variants"] == [{
        "sessionId": session["id"], "revision": 1, "title": "自动审核方案",
    }]
    assert job["outputVersions"] == []


def test_autonomous_timeline_rejects_model_proposal_that_deletes_every_clip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_safe_proposal"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "highlight",
        "videoInfo": {"duration": 60}, "editSessions": [], "outputVersions": [],
        "candidates": [{
            "candidateId": "candidate_0", "index": 0,
            "start": 10, "end": 20, "title": "高潮片段", "score": 90,
        }],
        "recommendedGroupIds": [],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    def unsafe_proposal(_job_id: str, session_id: str, request: Any) -> dict[str, Any]:
        session = main.find_edit_session(job, session_id)
        clip_ids = [str(item["id"]) for item in session["clips"]]
        proposal = {
            "id": "proposal_delete_all", "status": "pending",
            "baseRevision": session["revision"], "title": "删除全部",
            "summary": request.text,
            "operations": [{"type": "delete_clips", "clipIds": clip_ids}],
            "preview": {
                "durationBefore": session["duration"], "durationAfter": 0,
                "clipCountBefore": len(clip_ids), "clipCountAfter": 0,
                "preflight": {"errorCount": 1},
            },
        }
        session["pendingProposal"] = proposal
        return {"proposal": proposal, "session": session}

    monkeypatch.setattr(main, "create_edit_session_proposal", unsafe_proposal)
    workspace = {"jobId": job_id, "executionMode": "autonomous_review"}
    proposed = main.dispatch_agent_tool(workspace, "propose_timeline_edit", {
        "instruction": "剪成高潮；目标 20 秒，允许浮动 ±2 秒", "variantCount": 1,
    })

    assert proposed["proposalId"] != "proposal_delete_all"
    session = main.find_edit_session(job, proposed["sessionId"])
    assert session["pendingProposal"]["title"] == "Agent 安全时间线草案"
    applied = main.dispatch_agent_tool(workspace, "confirm_timeline_edit", {})
    assert applied["artifact"]["kind"] == "applied_timeline_batch"
    assert len(session["clips"]) == 1
    assert 18 <= session["duration"] <= 22


def test_autonomous_content_assembly_balances_parallel_predicates_and_ignores_stale_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_balanced_content"
    predicates = [
        {"id": "p1", "kind": "visual.semantic", "value": "冰箱换新"},
        {"id": "p2", "kind": "visual.semantic", "value": "空调换新"},
        {"id": "p3", "kind": "visual.semantic", "value": "洗衣机换新"},
    ]
    candidates = [
        {"id": "m1", "start": 10, "end": 40, "duration": 30, "score": 90,
         "confidenceTier": "reliable", "predicateResults": [{"predicateId": "p1", "satisfied": True}]},
        {"id": "m2", "start": 60, "end": 61, "duration": 1, "score": 85,
         "confidenceTier": "reliable", "predicateResults": [{"predicateId": "p2", "satisfied": True}]},
        {"id": "m3", "start": 100, "end": 101, "duration": 1, "score": 80,
         "confidenceTier": "reliable", "predicateResults": [{"predicateId": "p3", "satisfied": True}]},
    ]
    job = {
        "id": job_id, "revision": 1, "workflowKind": "content_search",
        "videoInfo": {"duration": 140}, "outputVersions": [],
        "activeEditSessionId": "stale_session",
        "editSessions": [{
            "id": "stale_session", "sourceSearchId": "old_search",
            "sourceMatchIds": ["old_match"], "clips": [], "status": "draft", "revision": 0,
        }],
        "contentSearch": {
            "id": "search_balanced", "candidates": candidates,
            "intent": {"targetSeconds": 60, "predicates": predicates},
        },
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    workspace = {
        "jobId": job_id, "executionMode": "autonomous_review", "activePlanId": "plan_balanced",
    }

    reviewed = main.dispatch_agent_tool(
        workspace, "review_content_evidence", {"query": "三类产品各约20秒"},
    )
    assert reviewed["artifact"]["matchIds"] == ["m1", "m2", "m3"]
    assert job["status"] == main.AWAITING_AGENT_PLAN
    assert job["stage"] == "agent_plan_running"
    assert job["actionRequired"] is None

    from app.content_contract import build_contract, confirm_human_range
    for match in job["contentSearch"]["candidates"]:
        confirm_human_range(match, build_contract(job["contentSearch"]))
    proposed = main.dispatch_agent_tool(
        workspace, "propose_timeline_edit", {"instruction": "每类20秒，共60秒", "variantCount": 1},
    )
    # A duration goal cannot expand two one-second evidence hits into 20s each.
    assert proposed["terminalStatus"] == "no_result"
    session = main.find_edit_session(job, job["activeEditSessionId"])
    assert session["id"] != "stale_session"
    assert session["duration"] == 22.0
    assert [clip["sourceRef"]["id"] for clip in session["clips"]] == ["m1", "m2", "m3"]
    assert [clip["duration"] for clip in session["clips"]] == [20.0, 1.0, 1.0]
    assert session["agentAssembly"]["targetSeconds"] == 60.0


def test_autonomous_content_review_uses_all_reliable_matches_when_default_focus_is_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_all_reliable_content"
    candidates = [
        {
            "id": "m1", "start": 0.0, "end": 31.275, "duration": 31.275,
            "title": "可复用画面事实", "confidenceTier": "reliable",
        },
        {
            "id": "m2", "start": 131.92, "end": 133.92, "duration": 2.0,
            "title": "画面中出现汽车", "confidenceTier": "reliable",
            "selected": True,
        },
        {
            "id": "m3", "start": 615.526, "end": 620.923, "duration": 5.397,
            "title": "车辆局部画面", "confidenceTier": "reliable",
        },
        {
            "id": "m4", "start": 626.02, "end": 628.869, "duration": 2.849,
            "title": "汽车外观画面", "confidenceTier": "reliable",
        },
    ]
    job = {
        "id": job_id, "revision": 1, "workflowKind": "content_search",
        "videoInfo": {"duration": 664.1}, "outputVersions": [], "editSessions": [],
        "contentSearch": {
            "id": "search_car", "instruction": "汽车", "candidates": candidates,
            "defaultSelectedIds": ["m2"],
            "reviewDraft": {
                "schemaVersion": "content-review-draft-v1",
                "searchId": "search_car",
                "selectedMatchIds": ["m2"],
                "orderedMatchIds": ["m2"],
            },
        },
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    reviewed = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "review_content_evidence",
        {"query": "汽车"},
    )

    assert reviewed["artifact"]["matchIds"] == ["m1", "m2", "m3", "m4"]
    assert reviewed["artifact"]["coverageSeconds"] == pytest.approx(41.521)
    assert job["contentSearch"]["reviewDraft"]["source"] == "agent_autonomous_review"
    assert job["contentSearch"]["defaultSelectedIds"] == ["m1", "m2", "m3", "m4"]


def test_autonomous_content_review_respects_user_confirmed_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_user_confirmed_subset"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "content_search",
        "videoInfo": {"duration": 120}, "outputVersions": [], "editSessions": [],
        "contentSearch": {
            "id": "search_manual",
            "candidates": [
                {"id": "m1", "start": 0, "end": 10, "confidenceTier": "reliable"},
                {"id": "m2", "start": 20, "end": 30, "confidenceTier": "reliable"},
            ],
            "defaultSelectedIds": ["m1", "m2"],
            "reviewDraft": {
                "schemaVersion": "content-review-draft-v1",
                "searchId": "search_manual",
                "selectedMatchIds": ["m2"],
                "orderedMatchIds": ["m2"],
                "source": "user",
            },
        },
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    reviewed = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "review_content_evidence",
        {"query": "汽车"},
    )

    assert reviewed["artifact"]["matchIds"] == ["m2"]
    assert job["contentSearch"]["defaultSelectedIds"] == ["m2"]


def test_anchor_review_auto_selects_one_reliable_match_and_pauses_for_multiple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_anchor_review"
    job = {
        "id": job_id, "revision": 1, "videoInfo": {"duration": 120},
        "outputVersions": [], "editSessions": [],
        "contentSearch": {
            "id": "search_anchor", "instruction": "价格",
            "candidates": [
                {"id": "m1", "start": 10, "end": 14, "confidenceTier": "reliable"},
                {"id": "m2", "start": 30, "end": 34, "confidenceTier": "possible", "requiresReview": True, "selected": True},
            ],
        },
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    selected = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "review_content_evidence",
        {"query": "价格", "selectionPolicy": "unique_or_review"},
    )
    assert selected["artifact"]["matchIds"] == ["m1"]

    job["contentSearch"]["reviewDraft"] = {}
    job["contentSearch"]["confirmedMatchIds"] = []
    job["contentSearch"]["candidates"][1].update({
        "confidenceTier": "reliable", "requiresReview": False,
    })
    paused = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "review_content_evidence",
        {"query": "价格", "selectionPolicy": "unique_or_review"},
    )
    assert paused["actionRequired"] is True
    assert paused["action"] == "structured_review"
    for candidate in job["contentSearch"]["candidates"]:
        candidate.update({"confidenceTier": "possible", "requiresReview": True})
    missing = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "review_content_evidence", {"query": "价格", "selectionPolicy": "unique_or_review"},
    )
    assert missing["terminalStatus"] == "no_result"


def test_agent_duration_fit_ignores_auto_job_target_and_uses_timeline_instruction() -> None:
    from app import main

    job = {
        "targetSeconds": "auto", "request": {"targetSeconds": "auto"},
        "videoInfo": {"duration": 180}, "speechAnalysis": {"segments": []},
    }
    session = {
        "clips": [{"id": "c1", "sourceStart": 30.0, "sourceEnd": 50.0}],
        "duration": 20.0,
        "agentTimelineRequest": {"instruction": "组织访谈精华；目标 90 秒，允许浮动 ±9 秒"},
    }

    result = main._fit_agent_session_to_target(job, session)

    assert result["targetSeconds"] == 90.0
    assert result["actualSeconds"] == 90.0
    assert result["status"] == "on_target"


def test_agent_duration_fit_uses_subtle_speed_to_keep_complete_speech_in_tolerance() -> None:
    from app import main

    job = {
        "videoInfo": {"duration": 200},
        "speechAnalysis": {"segments": [{"start": 50.0, "end": 150.0, "text": "完整回答"}]},
    }
    session = {
        "clips": [{"id": "c1", "sourceStart": 90.0, "sourceEnd": 110.0}],
        "duration": 20.0,
        "agentTimelineRequest": {"instruction": "目标 90 秒，允许浮动 ±9 秒"},
    }

    result = main._fit_agent_session_to_target(job, session)

    assert result["status"] == "on_target"
    assert result["actualSeconds"] <= 99.0
    assert session["clips"][0]["playbackRate"] == 1.1


def test_agent_duration_fit_drops_one_complete_nonessential_clip_before_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job = {
        "videoInfo": {"duration": 180}, "speechAnalysis": {"segments": []},
        "request": {"targetSeconds": 60},
    }
    session = {
        "clips": [
            {"id": f"c{index}", "sourceStart": index * 20.0, "sourceEnd": index * 20.0 + 13.0}
            for index in range(6)
        ],
        "duration": 78.0,
    }

    def expand_to_complete_boundary(
        _start: float, _end: float, *, lower_bound: float, upper_bound: float, **_kwargs: Any,
    ) -> dict[str, Any]:
        center = (_start + _end) / 2
        start = max(lower_bound, center - 6.5)
        end = min(upper_bound, center + 6.5)
        return {
            "start": start, "end": end, "boundarySource": "complete_unit",
            "speechBoundaryStatus": "adjusted",
        }

    monkeypatch.setattr(main, "semantic_safe_range", expand_to_complete_boundary)
    result = main._fit_agent_session_to_target(job, session)

    assert result["status"] == "on_target"
    assert 54 <= result["actualSeconds"] <= 66
    assert len(session["clips"]) == 5


def test_autonomous_content_assembly_reports_missing_category_as_terminal_evidence_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_missing_content_category"
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "workflowKind": "content_search",
        "videoInfo": {"duration": 140}, "outputVersions": [], "editSessions": [],
        "contentSearch": {
            "id": "search_missing", "candidates": [{
                "id": "m1", "start": 10, "end": 20, "duration": 10,
                "predicateResults": [{"predicateId": "p1", "satisfied": True}],
            }],
            "intent": {"predicates": [
                {"id": "p1", "kind": "visual.semantic", "value": "冰箱换新"},
                {"id": "p2", "kind": "visual.semantic", "value": "空调换新"},
            ]},
        },
    })
    workspace = {"jobId": job_id, "executionMode": "autonomous_review"}

    result = main.dispatch_agent_tool(
        workspace, "review_content_evidence", {"query": "两类换新画面"},
    )
    assert result["terminalStatus"] == "no_result"
    assert result["artifact"]["reasonCode"] == "missing_required_categories"
    assert "空调换新" in result["artifact"]["message"]


def test_autonomous_content_assembly_does_not_count_possible_match_as_required_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_possible_required_category"
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "workflowKind": "content_search",
        "videoInfo": {"duration": 140}, "outputVersions": [], "editSessions": [],
        "contentSearch": {
            "id": "search_possible", "candidates": [
                {
                    "id": "m1", "start": 10, "end": 20, "duration": 10,
                    "confidenceTier": "reliable",
                    "predicateResults": [{"predicateId": "p1", "satisfied": True}],
                },
                {
                    "id": "m2", "start": 40, "end": 41, "duration": 1,
                    "confidenceTier": "possible", "requiresReview": True,
                    "predicateResults": [{"predicateId": "p2", "satisfied": True}],
                },
            ],
            "intent": {"targetSeconds": 40, "predicates": [
                {"id": "p1", "kind": "visual.semantic", "value": "冰箱换新"},
                {"id": "p2", "kind": "visual.semantic", "value": "洗衣机换新"},
            ]},
        },
    })
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "review_content_evidence", {"query": "冰箱和洗衣机换新"},
    )

    assert result["terminalStatus"] == "no_result"
    assert result["artifact"]["reasonCode"] == "missing_required_categories"
    assert "洗衣机换新" in result["artifact"]["message"]


def test_social_preview_can_use_an_agent_review_proxy_before_a_formal_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app import main

    job_id = "job_agent_social_proxy"
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    review_proxy = tmp_path / "review-proxy.mp4"
    review_proxy.write_bytes(b"review")
    work_directory = tmp_path / "work"
    work_directory.mkdir()
    session_id = "edit_social_proxy"
    job = {
        "id": job_id, "revision": 1, "filename": "source.mp4",
        "workDirectory": str(work_directory), "outputDirectory": str(output_directory),
        "outputVersions": [], "outputs": [],
        "currentOutputVersionId": None,
        "agentTimelineBatch": {"variants": [{"sessionId": session_id}]},
        "editSessions": [{
            "id": session_id, "revision": 1, "previewPath": str(review_proxy),
            "subtitleEnabled": False,
            "clips": [{"id": "clip_1", "sourceStart": 4.0, "sourceEnd": 10.0}],
        }],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "probe_video", lambda *_args, **_kwargs: SimpleNamespace(has_audio=True))

    def render(_source: Path, output: Path, **_kwargs: Any) -> Any:
        output.write_bytes(b"vertical-preview")
        return SimpleNamespace(duration=6.0, width=1080, height=1920)

    def submit(worker: Any) -> Future[dict[str, Any]]:
        future: Future[dict[str, Any]] = Future()
        try:
            future.set_result(worker())
        except Exception as error:  # pragma: no cover - surfaced by result()
            future.set_exception(error)
        return future

    monkeypatch.setattr(main, "create_social_reframe_preview", render)
    monkeypatch.setattr(main.output_preview_executor, "submit", submit)

    queued = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "render_social_preview", {"aspect": "9:16", "fit": "crop"},
    )
    artifact = queued["future"].result()["artifact"]

    assert artifact["kind"] == "social_reframe_preview"
    assert artifact["output"]["width"] == 1080
    assert artifact["output"]["height"] == 1920
    assert len(job["agentPreviewOutputs"]) == 1
    filename = job["agentPreviewOutputs"][0]["filename"]
    assert main.output_download_context(job, filename) is not None
    public_preview = main.public_job(job)["agentPreviewOutputs"][0]
    assert public_preview["previewUrl"].endswith(filename)
    assert public_preview["outputKind"] == "social_reframe_preview"
    assert public_preview["socialReframe"] is True
    assert public_preview["sourceEditSessionId"] == session_id
    session = job["editSessions"][0]
    assert session["reframe"] == {
        "aspect": "9:16", "fit": "crop", "focusX": .5, "focusY": .5,
    }
    assert session["previewPath"].endswith(filename)
    assert session["previewOverlayVerification"]["renderPipelineVersion"] == 3


def test_reframe_analysis_can_use_projected_agent_review_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app import main

    job_id = "job_agent_reframe_from_review_preview"
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    review_proxy = tmp_path / "review-proxy.mp4"
    review_proxy.write_bytes(b"review")
    session_id = "edit_reframe_proxy"
    job = {
        "id": job_id, "revision": 1, "filename": "source.mp4",
        "workDirectory": str(tmp_path / "work"), "outputDirectory": str(output_directory),
        "outputVersions": [], "outputs": [],
        "agentReviewPreviews": [{
            "kind": "review_preview",
            "outputKind": "agent_review_preview",
            "title": "审核样片",
            "previewUrl": f"/api/jobs/{job_id}/edit-sessions/{session_id}/preview?r=1",
            "sourceEditSessionId": session_id,
            "previewOnly": True,
        }],
        "editSessions": [{
            "id": session_id, "revision": 1, "previewPath": str(review_proxy),
            "clips": [{"id": "clip_1", "sourceStart": 4.0, "sourceEnd": 10.0}],
        }],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "probe_video", lambda *_args, **_kwargs: SimpleNamespace(width=1920, height=1080, has_audio=True))

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "analyze_reframe_safe_areas", {"aspect": "9:16", "fit": "blur"},
    )

    artifact = result["artifact"]
    assert artifact["kind"] == "reframe_safe_area_report"
    assert artifact["sourceFilename"] == review_proxy.name
    assert artifact["source"]["ratio"] == 1.7778
    assert artifact["fit"] == "blur"


def test_propose_timeline_tool_builds_draft_directly_from_highlight_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_highlight_proposal"
    job = {
        "id": job_id, "revision": 1, "workflowKind": "highlight",
        "videoInfo": {"duration": 90}, "editSessions": [],
        "recommendedIndices": [1, 0],
        "candidates": [
            {"index": 0, "start": 20, "end": 27, "title": "高潮", "score": 96},
            {"index": 1, "start": 5, "end": 11, "title": "开场", "score": 92},
            {"index": 2, "start": 50, "end": 58, "title": "未推荐镜头", "score": 70},
        ],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    def generate_proposal(_job_id: str, session_id: str, request: Any) -> dict[str, Any]:
        session = main.find_edit_session(job, session_id)
        proposal = {
            "id": "proposal_highlight_1", "status": "pending", "title": "高光时间线草案",
            "summary": request.text, "operations": [],
        }
        session["pendingProposal"] = proposal
        return {"proposal": proposal, "session": session}

    monkeypatch.setattr(main, "create_edit_session_proposal", generate_proposal)
    result = main.dispatch_agent_tool(
        {"jobId": job_id}, "propose_timeline_edit",
        {"instruction": "前 3 秒进入 Hook，随后展示高潮", "variantCount": 1},
    )

    assert result["proposalId"] == "proposal_highlight_1"
    assert "Agent 已生成待审核时间线草案" in result["message"]
    assert "请先在精剪时间线生成" not in result["message"]
    session = job["editSessions"][0]
    assert session["sourceCandidateIds"] == ["1", "0"]
    assert [clip["title"] for clip in session["clips"]] == ["开场", "高潮"]
    assert session["pendingProposal"]["id"] == "proposal_highlight_1"


def test_interview_profile_compiles_three_minute_theme_cut_without_identity_gate() -> None:
    interview_skill = """---
name: cliptalk-interview-editor
description: Interview test profile.
allowed-tools: inspect_workspace discover_speakers select_speakers search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: interview
---

# Interview
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=interview_skill, source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "targetSeconds": None,
            "speaker": {"available": True, "needsDiscovery": False, "needsConfirmation": False},
            "evidence": {"hasCandidates": True},
        })
        workspace = platform.create_workspace(job_id="job_interview")
        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-interview-editor",
            goal="将视频剪辑成3分钟访谈精华，按主题组织回答，删除重复表达",
        )
        tools = [step["tool"] for step in plan["steps"]]
        assert tools == [
            "inspect_workspace", "search_content", "review_content_evidence",
            "propose_timeline_edit", "confirm_timeline_edit", "render_review_preview",
        ]
        assert plan["executionMode"] == "autonomous_review"
        assert plan["brief"]["targetSeconds"] == 180
        assert plan["brief"]["durationToleranceSeconds"] == 15
        assert "select_speakers" not in tools
        assert "confirm_timeline_edit" in tools
        search_step = next(step for step in plan["steps"] if step["tool"] == "search_content")
        assert search_step["arguments"]["query"].startswith("仅根据对白检索")
        assert "访谈中的完整回答" in search_step["arguments"]["query"]
        assert "删除重复表达" not in search_step["arguments"]["query"]
        assert "不使用画面或屏幕文字" in search_step["arguments"]["query"]
        review_step = next(step for step in plan["steps"] if step["tool"] == "review_content_evidence")
        assert review_step["arguments"]["query"] == "访谈完整回答和必要问题上下文"


def test_autonomous_timeline_proposal_stops_with_no_result_when_search_has_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    job_id = "job_agent_no_candidates_before_timeline"
    monkeypatch.setitem(main.jobs, job_id, {
        "id": job_id, "revision": 1, "workflowKind": "content_search",
        "videoInfo": {"duration": 90}, "outputVersions": [], "outputs": [],
        "editSessions": [],
        "contentSearch": {
            "id": "search_empty", "instruction": "访谈上下文",
            "status": "no_match", "candidateCount": 0, "candidates": [],
        },
    })

    result = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "propose_timeline_edit", {"instruction": "整理访谈精华"},
    )

    assert result["terminalStatus"] == "no_result"
    assert result["artifact"]["kind"] == "no_match"
    assert result["artifact"]["reasonCode"] == "no_match"
    assert "已跳过后续时间线与渲染步骤" in result["message"]


def test_content_profile_extracts_semantic_target_and_plans_only_requested_deliverables() -> None:
    content_skill = """---
name: cliptalk-content-extractor
description: Content extraction test profile.
allowed-tools: inspect_workspace search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: content
---

# Content extractor
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=content_skill, source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "sourceScope": "all", "evidence": {"hasCandidates": False},
        })

        workspace = platform.create_workspace(job_id="job_housework")
        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-content-extractor",
            goal="上传 source.mp4，交给智能剪辑 Agent：帮我找到做家务的片段，并做一些合理组合，给我不同的成片；素材范围：全片",
        )
        assert plan["brief"]["retrievalQuery"] == "做家务"
        assert plan["brief"]["variantCount"] == 3
        assert plan["brief"]["delivery"] == "timeline"
        assert [step["tool"] for step in plan["steps"]] == [
            "inspect_workspace", "search_content", "review_content_evidence",
            "propose_timeline_edit", "confirm_timeline_edit", "render_review_preview",
        ]
        assert plan["steps"][1]["arguments"]["query"] == "做家务"
        assert plan["steps"][3]["arguments"]["variantCount"] == 3
        assert "字幕" not in " ".join(step["title"] for step in plan["steps"])
        assert sum(step["tool"] == "render_review_preview" for step in plan["steps"]) == 1

        compiled = platform._compile_profile_plan(
            {"strategy": {"searchQuery": "扫地、拖地、洗衣、做饭、接水等所有家务动作和相关工具"}},
            skill=platform.store.get("skills", "cliptalk-content-extractor"),
            goal="帮我找到做家务的片段，并合理组合",
            context={"sourceScope": "all", "evidence": {"hasCandidates": False}},
        )
        search_step = next(step for step in compiled["steps"] if step["tool"] == "search_content")
        assert search_step["arguments"]["query"] == "做家务"

        review_workspace = platform.create_workspace(job_id="job_subtitle_preview")
        review_plan = platform.create_plan(
            workspace_id=review_workspace["id"], skill_id="cliptalk-content-extractor",
            goal="找到做家务的片段，组合成 1 分钟成片并添加字幕，生成低码率审阅样片",
        )
        assert [step["tool"] for step in review_plan["steps"]] == [
            "inspect_workspace", "search_content", "review_content_evidence",
            "propose_timeline_edit", "confirm_timeline_edit",
            "prepare_subtitle_review", "render_review_preview",
        ]
        subtitle_previews = [step for step in review_plan["steps"] if step["tool"] == "render_review_preview"]
        assert [step["title"] for step in subtitle_previews] == ["生成带字幕最终审核样片"]
        subtitle_step = next(step for step in review_plan["steps"] if step["tool"] == "prepare_subtitle_review")
        assert subtitle_step["arguments"]["requireConfirmedDraft"] is False
        assert subtitle_step["arguments"]["autoReview"] is True

        search_only_workspace = platform.create_workspace(job_id="job_watermelon")
        search_only = platform.create_plan(
            workspace_id=search_only_workspace["id"], skill_id="cliptalk-content-extractor",
            goal="找出切西瓜的片段",
        )
        assert search_only["brief"]["retrievalQuery"] == "切西瓜"
        assert search_only["brief"]["delivery"] == "candidates"
        assert [step["tool"] for step in search_only["steps"]] == ["inspect_workspace", "search_content"]


def test_social_reframe_cannot_displace_source_content_assembly() -> None:
    social_skill = {
        "id": "cliptalk-social-reframe-exporter",
        "allowedTools": ["inspect_workspace", "render_social_preview", "run_delivery_qc"],
    }
    content_skill = {
        "id": "cliptalk-content-extractor",
        "allowedTools": ["inspect_workspace", "search_content", "review_content_evidence", "propose_timeline_edit", "confirm_timeline_edit"],
    }
    goal = "上传 source.mp4，找到做家务的片段并合成为 4:5 小红书版本"
    context = {"editing": {"hasOutputs": False}}
    brief = AgentPlatform._editing_brief(goal, context)
    social_ok, social_reason = AgentPlatform._skill_routing_eligibility(
        social_skill, brief=brief, context=context,
    )
    content_ok, _ = AgentPlatform._skill_routing_eligibility(
        content_skill, brief=brief, context=context,
    )
    assert not social_ok
    assert "源片检索" in social_reason
    assert content_ok

    delivery_goal = "把已有成片改成 4:5 小红书审核预览"
    delivery_context = {"editing": {"hasOutputs": True}}
    delivery_brief = AgentPlatform._editing_brief(delivery_goal, delivery_context)
    assert AgentPlatform._skill_routing_eligibility(
        social_skill, brief=delivery_brief, context=delivery_context,
    )[0]


def test_cover_lineage_constraint_does_not_replace_a_new_video_edit_with_audit() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        for skill_id in (
            "cliptalk-highlight-director", "cliptalk-shortform-hook-director",
            "cliptalk-source-provenance-guard",
        ):
            platform.install_skill(
                markdown=(root / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8"),
                source="test", status="enabled",
            )

        selected = platform.route_skill(
            "做一个竖屏成片，最开头加封面；封面必须来自本次任务的视频，不能复用其他任务封面。",
            planning_context={"editing": {"hasOutputs": False, "hasActiveSession": False}},
        )

        assert selected["id"] in {
            "cliptalk-highlight-director", "cliptalk-shortform-hook-director",
        }


def test_content_evidence_review_is_a_real_agent_gate() -> None:
    steps = [
        {
            "id": "inspect", "title": "检查素材", "tool": "inspect_workspace",
            "arguments": {}, "dependencies": [], "expectedOutput": "素材状态",
            "sideEffect": "read", "estimatedSeconds": 1, "optional": False,
        },
        {
            "id": "review", "title": "确认候选", "tool": "review_content_evidence",
            "arguments": {"query": "做家务", "minimumSelection": 1}, "dependencies": ["inspect"],
            "expectedOutput": "用户选择", "sideEffect": "review", "estimatedSeconds": 0, "optional": False,
        },
    ]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps)
        calls: list[str] = []
        platform.configure_tool_dispatcher(
            lambda _workspace, tool, _arguments: calls.append(tool) or {"artifact": {"tool": tool}},
        )
        workspace = platform.create_workspace(job_id="job_review")
        plan = platform.create_plan(
            workspace_id=workspace["id"], goal="审核候选",
            execution_mode="stepwise_review",
        )
        paused = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert calls == ["inspect_workspace"]
        assert paused["status"] == "action_required"
        assert paused["steps"][1]["status"] == "action_required"
        assert "内容候选面板" in paused["steps"][1]["result"]["message"]


def test_builtin_autonomous_plan_runs_review_steps_through_to_preview() -> None:
    skill = """---
name: cliptalk-highlight-director
version: 1.2.0
description: Autonomous highlight test profile.
allowed-tools: inspect_workspace analyze_highlights propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: highlight
---

# Highlight
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=skill, source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "evidence": {"hasCandidates": True},
        })
        calls: list[str] = []
        platform.configure_tool_dispatcher(lambda _workspace, tool, _arguments: (
            calls.append(tool) or {"artifact": {"kind": tool}}
        ))
        workspace = platform.create_workspace(job_id="job_autonomous")
        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-highlight-director",
            goal="自动剪出高光版本",
        )
        completed = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])

        assert plan["executionMode"] == "autonomous_review"
        assert completed["status"] == "preview_ready"
        assert calls == [
            "inspect_workspace", "propose_timeline_edit",
            "confirm_timeline_edit", "render_review_preview",
        ]
        assert all(step["status"] == "completed" for step in completed["steps"])


def test_generated_profile_uses_the_platform_workflow_contract() -> None:
    generated_skill = """---
name: generated-topic-editor
description: Generated topic-editor test profile.
allowed-tools: inspect_workspace discover_speakers select_speakers search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: interview
---

# Generated topic editor
"""
    unsafe_steps = [{
        "id": "bad", "title": "不相关的人物筛选", "tool": "select_people",
        "arguments": {}, "dependencies": [], "sideEffect": "identity",
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), unsafe_steps)
        platform.install_skill(markdown=generated_skill, source="generated", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "speaker": {"available": True, "needsDiscovery": False, "needsConfirmation": False},
            "evidence": {"hasCandidates": True},
        })
        workspace = platform.create_workspace(job_id="job_generated")
        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="generated-topic-editor",
            goal="按主题剪辑访谈精华，删除重复表达",
        )
        assert plan["profile"] == "interview"
        assert plan["executionMode"] == "stepwise_review"
        assert [step["tool"] for step in plan["steps"]] == [
            "inspect_workspace", "search_content", "review_content_evidence",
            "propose_timeline_edit", "confirm_timeline_edit",
        ]


def test_shortform_hook_profile_does_not_invent_duration_and_chooses_evidence() -> None:
    shortform_skill = """---
name: cliptalk-shortform-hook-director
description: Short-form Hook test profile.
allowed-tools: inspect_workspace analyze_highlights search_content propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: shortform
---

# Short-form Hook Director
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=shortform_skill, source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "targetSeconds": None, "evidence": {"hasCandidates": False},
        })

        hook_workspace = platform.create_workspace(job_id="job_hook")
        hook_plan = platform.create_plan(
            workspace_id=hook_workspace["id"], skill_id="cliptalk-shortform-hook-director",
            goal="剪一个抓人的短视频 Hook",
        )
        assert [step["tool"] for step in hook_plan["steps"]] == [
            "inspect_workspace", "analyze_highlights", "propose_timeline_edit",
            "confirm_timeline_edit", "render_review_preview",
        ]
        assert hook_plan["brief"]["targetSeconds"] is None
        assert "targetSeconds" not in hook_plan["steps"][1]["arguments"]
        assert "前 1–3 秒必须进入明确 Hook" in hook_plan["steps"][2]["arguments"]["instruction"]

        topic_workspace = platform.create_workspace(job_id="job_hook_topic")
        topic_plan = platform.create_plan(
            workspace_id=topic_workspace["id"], skill_id="cliptalk-shortform-hook-director",
            goal="围绕产品演示剪一个 45 秒短视频",
        )
        assert [step["tool"] for step in topic_plan["steps"]][1] == "search_content"
        assert topic_plan["brief"]["targetSeconds"] == 45


def test_delivery_qc_profile_compiles_read_only_media_checks() -> None:
    skill = """---
name: cliptalk-delivery-qc
description: Delivery QC test profile.
allowed-tools: inspect_workspace run_delivery_qc
workflow-profile: delivery-qc
---

# Delivery QC
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=skill, source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "editing": {"hasOutputs": True},
        })
        workspace = platform.create_workspace(job_id="job_qc")
        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-delivery-qc",
            goal="检查现有成片是否可以交付",
        )
        assert plan["profile"] == "delivery-qc"
        assert [step["tool"] for step in plan["steps"]] == [
            "inspect_workspace", "run_delivery_qc",
        ]
        assert plan["steps"][1]["arguments"] == {"strict": True}


@pytest.mark.parametrize(
    ("goal", "aspect", "fit"),
    [
        ("生成抖音竖屏审核预览", "9:16", "blur"),
        ("生成 1:1 方形版本并保留完整画面", "1:1", "blur"),
        ("生成 4:5 小红书预览", "4:5", "blur"),
    ],
)
def test_social_reframe_profile_compiles_preview_then_qc(
    goal: str, aspect: str, fit: str,
) -> None:
    skill = """---
name: cliptalk-social-reframe-exporter
description: Social reframe test profile.
allowed-tools: inspect_workspace render_social_preview run_delivery_qc
workflow-profile: social-reframe
---

# Social Reframe
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=skill, source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "editing": {"hasOutputs": True},
        })
        workspace = platform.create_workspace(job_id=f"job_{aspect}_{fit}")
        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-social-reframe-exporter",
            goal=goal,
        )
        assert plan["profile"] == "social-reframe"
        assert [step["tool"] for step in plan["steps"]] == [
            "inspect_workspace", "render_social_preview", "run_delivery_qc",
        ]
        assert plan["steps"][1]["arguments"]["aspect"] == aspect
        assert plan["steps"][1]["arguments"]["fit"] == fit


def test_new_cliptalk_skill_profiles_compile_executable_steps() -> None:
    root = Path(__file__).resolve().parents[1]
    scenarios = [
        ("cliptalk-source-provenance-guard", "同一源视频新任务，检查不要复用旧任务", {}, ["inspect_workspace", "validate_task_provenance"]),
        ("cliptalk-multi-topic-assembler", "分别找出冰箱、空调、洗衣机片段，每段20秒，合成60秒", {}, ["inspect_workspace", "search_content", "select_multi_topic_evidence", "propose_timeline_edit", "confirm_timeline_edit", "render_review_preview"]),
        ("cliptalk-cover-intro-composer", "给当前成片生成封面，并把封面作为1秒片头", {"editing": {"hasOutputs": True}}, ["inspect_workspace", "propose_cover_candidates", "render_cover_variants", "review_cover_variants", "confirm_cover", "compose_cover_intro", "run_delivery_qc"]),
        ("cliptalk-dynamic-reframe-director", "把已有成片改成竖屏，完整保留画面并用虚化背景补齐", {"editing": {"hasOutputs": True}}, ["inspect_workspace", "analyze_reframe_safe_areas", "render_social_preview", "run_delivery_qc"]),
        ("cliptalk-caption-layout-director", "把当前时间线字幕放到顶部安全区", {"editing": {"hasActiveSession": True}}, ["inspect_workspace", "prepare_subtitle_review", "layout_subtitles", "render_review_preview"]),
        ("cliptalk-caption-layout-director", "只导出字幕文件，不要生成视频", {"editing": {"hasOutputs": True}}, ["inspect_workspace", "export_subtitles"]),
        ("cliptalk-audio-polish-mixer", "给当前成片做人声增强和降噪", {"editing": {"hasOutputs": True}}, ["inspect_workspace", "polish_audio_mix", "run_delivery_qc"]),
        ("cliptalk-broll-overlay-editor", "给当前时间线穿插汽车产品画面", {"editing": {"hasActiveSession": True}}, ["inspect_workspace", "search_content", "review_content_evidence", "propose_broll_overlay", "render_review_preview"]),
        ("cliptalk-graphics-packager", "给当前时间线加顶部参数卡和水印", {"editing": {"hasActiveSession": True}}, ["inspect_workspace", "render_graphics_package", "render_review_preview"]),
        ("cliptalk-local-motion-renderer", "生成一个竖屏动态图文标题卡，不调用外部 API", {}, ["inspect_workspace", "render_motion_graphics", "run_delivery_qc"]),
        ("cliptalk-local-motion-renderer", "给当前成片合入一个动态图文片头，不调用外部 API", {"editing": {"hasOutputs": True}}, ["inspect_workspace", "render_motion_graphics", "compose_motion_intro", "run_delivery_qc"]),
        ("cliptalk-local-draft-exporter", "导出当前任务剪映草稿桥接包", {}, ["inspect_workspace", "export_editing_draft"]),
        ("cliptalk-platform-delivery-exporter", "确认后导出高清正式交付版本", {"editing": {"hasOutputs": True}}, ["inspect_workspace", "export_delivery_master", "run_delivery_qc"]),
        ("cliptalk-edit-diagnostics", "诊断为什么当前任务未找到可用内容", {}, ["inspect_workspace", "diagnose_edit_failure"]),
    ]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        for skill_id, _goal, _context, _tools in scenarios:
            markdown = (root / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8")
            platform.install_skill(markdown=markdown, source="test", status="enabled")
        context_by_job: dict[str, dict[str, Any]] = {}
        platform.configure_planning_context_provider(lambda job_id: {"jobId": job_id, **context_by_job.get(job_id, {})})
        for index, (skill_id, goal, context, expected_tools) in enumerate(scenarios):
            job_id = f"job_new_skill_{index}"
            context_by_job[job_id] = context
            workspace = platform.create_workspace(job_id=job_id)
            plan = platform.create_plan(workspace_id=workspace["id"], skill_id=skill_id, goal=goal)
            assert [step["tool"] for step in plan["steps"]] == expected_tools
            assert plan["profile"] == SKILL_PROFILES[skill_id]["kind"]


def test_local_motion_intro_without_existing_output_renders_standalone_preview() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        skill_id = "cliptalk-local-motion-renderer"
        platform.install_skill(
            markdown=(root / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8"),
            source="test", status="enabled",
        )
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id,
            "editing": {"hasOutputs": False, "hasActiveSession": False},
        })
        workspace = platform.create_workspace(job_id="job_standalone_motion_intro")

        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id=skill_id,
            goal="为当前视频制作一段简洁的动态图文片头，突出核心主题，并保持与原视频风格一致。",
        )

        assert [step["tool"] for step in plan["steps"]] == [
            "inspect_workspace", "render_motion_graphics", "run_delivery_qc",
        ]
        assert plan["decisionRecord"][0]["outcome"] != "stop_with_clear_limitation"


def test_automatic_route_prefers_timeline_addon_over_reframe_for_current_graphics_edit() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        for skill_id in (
            "cliptalk-dynamic-reframe-director",
            "cliptalk-graphics-packager",
        ):
            platform.install_skill(
                markdown=(root / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8"),
                source="test", status="enabled",
            )
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id,
            "editing": {"hasOutputs": True, "hasActiveSession": True},
        })
        workspace = platform.create_workspace(job_id="job_graphics_route")

        plan = platform.create_plan(
            workspace_id=workspace["id"],
            goal="给当前时间线顶部添加“小米汽车”文字，显示5秒，并做成竖屏。",
        )

        assert plan["skillId"] == "cliptalk-graphics-packager"
        assert plan["brief"]["operationIntent"] == "revise_timeline"
        assert [step["tool"] for step in plan["steps"]] == [
            "inspect_workspace", "render_graphics_package", "render_review_preview",
            "render_social_preview", "run_delivery_qc",
        ]


@pytest.mark.parametrize(
    ("skill_id", "goal", "required_state"),
    [
        (
            "cliptalk-smart-reframe",
            "把当前已确认成片改成 9:16，完整保留画面并用虚化背景补齐",
            "current_output",
        ),
        (
            "cliptalk-subtitle-editor",
            "把当前已确认时间线的字幕放到顶部安全区",
            "active_timeline",
        ),
        (
            "cliptalk-cover-intro-composer",
            "选择当前任务封面并作为 1 秒片头合入当前成片",
            "current_output",
        ),
        (
            "cliptalk-local-motion-renderer",
            "给当前成片合入一个 1.5 秒动态图文片头",
            "current_output",
        ),
    ],
)
def test_explicit_skill_with_missing_prerequisite_compiles_clear_terminal_check(
    skill_id: str, goal: str, required_state: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(
            markdown=(root / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8"),
            source="test", status="enabled",
        )
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id,
            "editing": {"hasOutputs": False, "hasActiveSession": False},
        })
        workspace = platform.create_workspace(job_id=f"job_missing_{skill_id}")

        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id=skill_id, goal=goal,
        )

        assert plan["skillId"] == skill_id
        assert len(plan["steps"]) == 1
        assert plan["steps"][0]["tool"] == "inspect_workspace"
        assert plan["steps"][0]["arguments"]["requiredState"] == required_state
        assert plan["steps"][0]["arguments"]["preconditionCode"].startswith("missing_")
        assert "前置条件" in plan["summary"]


def test_managed_provenance_plan_ignores_model_invented_media_addons() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        for skill_id in ("cliptalk-source-provenance-guard", "cliptalk-cover-director"):
            platform.install_skill(
                markdown=(root / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8"),
                source="test", status="enabled",
            )
        platform.client.plan = lambda _payload: {  # type: ignore[method-assign]
            "plan": {
                "summary": "检查是否复用了旧任务封面",
                "steps": [],
                "skillChain": [
                    {"id": "cliptalk-source-provenance-guard"},
                    {"id": "cliptalk-cover-director"},
                ],
            },
            "events": [],
        }
        platform.configure_planning_context_provider(lambda job_id: {"jobId": job_id, "editing": {}})
        workspace = platform.create_workspace(job_id="job_provenance_only")

        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-source-provenance-guard",
            goal="检查同一源视频新任务是否复用了旧任务时间范围、封面或输出",
        )

        assert [step["tool"] for step in plan["steps"]] == [
            "inspect_workspace", "validate_task_provenance",
        ]
        assert [item["id"] for item in plan["skills"]] == [
            "cliptalk-source-provenance-guard",
        ]


def test_local_draft_export_runs_autonomously_after_initial_plan_confirmation() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(
            markdown=(root / "skills" / "cliptalk-local-draft-exporter" / "SKILL.md").read_text(encoding="utf-8"),
            source="test",
            status="enabled",
        )
        platform.configure_tool_dispatcher(
            lambda _workspace, tool, _arguments: {"artifact": {"kind": "editing_draft_package", "tool": tool}},
        )
        workspace = platform.create_workspace(job_id="job_source_only_draft")
        plan = platform.create_plan(
            workspace_id=workspace["id"],
            skill_id="cliptalk-local-draft-exporter",
            goal="导出当前任务剪映草稿桥接包",
            execution_mode="autonomous_review",
        )
        completed = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert completed["status"] == "preview_ready"
        assert [step["status"] for step in completed["steps"]] == ["completed", "completed"]
        assert completed["steps"][1]["result"]["artifact"]["kind"] == "editing_draft_package"


def test_custom_skill_plan_rejects_a_tool_outside_its_allow_list() -> None:
    bounded_skill = """---
name: bounded-editor
description: A constrained test editor.
allowed-tools: inspect_workspace
---

# Bounded
"""
    steps = [{
        "id": "bad", "title": "越权分析", "tool": "analyze_highlights",
        "arguments": {}, "dependencies": [], "expectedOutput": "候选",
        "sideEffect": "analysis", "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps)
        platform.install_skill(markdown=bounded_skill, source="test", status="enabled")
        workspace = platform.create_workspace(job_id="job_bounded")
        with pytest.raises(ValueError, match="未授权"):
            platform.create_plan(workspace_id=workspace["id"], goal="检查素材", skill_id="bounded-editor")


def test_plan_validation_rejects_cycles_and_unknown_tools() -> None:
    cyclic = [
        {"id": "a", "title": "A", "tool": "inspect_workspace", "arguments": {}, "dependencies": ["b"], "sideEffect": "read"},
        {"id": "b", "title": "B", "tool": "inspect_workspace", "arguments": {}, "dependencies": ["a"], "sideEffect": "read"},
    ]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), cyclic)
        workspace = platform.create_workspace(job_id="job_test")
        with pytest.raises(ValueError, match="循环依赖"):
            platform.create_plan(workspace_id=workspace["id"], goal="循环")

        platform.client.steps = [{
            "id": "bad", "title": "未知", "tool": "invented_tool",
            "arguments": {}, "dependencies": [], "sideEffect": "analysis",
        }]
        with pytest.raises(ValueError, match="未安装的工具"):
            platform.create_plan(workspace_id=workspace["id"], goal="未知工具")

        platform.client.steps = [{
            "id": "unsafe", "title": "绕过人物确认", "tool": "select_people",
            "arguments": {}, "dependencies": [], "sideEffect": "read",
        }]
        with pytest.raises(ValueError, match="不能改变工具声明"):
            platform.create_plan(workspace_id=workspace["id"], goal="绕过确认")

        platform.client.steps = [{
            "id": "timeline", "title": "时间线草稿", "tool": "propose_timeline_edit",
            "arguments": {"instruction": "按主题组织"}, "dependencies": [], "sideEffect": "preview",
        }]
        with pytest.raises(ValueError, match="必须加入确认时间线"):
            platform.create_plan(workspace_id=workspace["id"], goal="生成时间线")


def test_generated_skill_stays_reviewable_before_enable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        skill = platform.generate_skill(request="生成一个检查视频素材状态的测试 Skill")
        assert skill["status"] == "validated"
        assert skill["source"] == "generated"
        enabled = platform.enable_skill(skill["id"], skill["contentHash"])
        assert enabled["status"] == "enabled"


def test_agent_model_config_reuses_a_complete_text_model_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    class Config:
        def __init__(self, value: dict[str, Any]) -> None:
            self.value = value

        def resolve(self) -> dict[str, Any]:
            return dict(self.value)

    monkeypatch.setattr(main, "agent_model_store", Config({
        "provider": "openai_compatible", "apiKey": "", "model": "", "baseUrl": "",
    }))
    monkeypatch.setattr(main, "llm_store", Config({
        "provider": "anthropic_compatible", "protocol": "anthropic",
        "apiKey": "text-key", "model": "text-tool-model", "baseUrl": "https://example.invalid/v1",
    }))

    resolved = main.agent_model_config()
    assert resolved["configSource"] == "llm_fallback"
    assert resolved["model"] == "text-tool-model"


def test_failed_step_automatically_replans_inside_approved_envelope() -> None:
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        attempts = 0

        def dispatch(_workspace: dict[str, Any], _tool: str, _arguments: dict[str, Any]) -> dict[str, Any]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient inspection failure")
            return {"ok": True}

        platform.configure_tool_dispatcher(dispatch)
        workspace = platform.create_workspace(job_id="job_test")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="检查并恢复")
        completed = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert completed["status"] == "preview_ready"
        assert completed["replanCount"] == 1
        assert attempts == 2


def test_missing_required_evidence_category_stops_without_repeating_the_same_plan() -> None:
    steps = [{
        "id": "review", "title": "自动筛选用于组合的候选片段",
        "tool": "review_content_evidence", "arguments": {"query": "三类换新画面"},
        "dependencies": [], "expectedOutput": "三类候选均已覆盖",
        "sideEffect": "review", "estimatedSeconds": 1, "optional": False,
    }]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        calls = 0

        def dispatch(_workspace: dict[str, Any], _tool: str, _arguments: dict[str, Any]) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            raise RuntimeError("自动编排缺少必要类别的候选：空调新老替换")

        platform.configure_tool_dispatcher(dispatch)
        workspace = platform.create_workspace(job_id="job_missing_category")
        plan = platform.create_plan(
            workspace_id=workspace["id"], goal="三类换新画面",
            execution_mode="autonomous_review",
        )
        # The generic test Skill is custom/unmanaged and its fake plan omits
        # executionMode; exercise the managed autonomous path used in production.
        plan["executionMode"] = "autonomous_review"
        platform.store.save("plans", plan)
        failed = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])

        assert failed["status"] == "failed"
        assert int(failed.get("replanCount") or 0) == 0
        assert calls == 1
        events = platform.store.events_after(workspace["id"], 0)
        assert [item["type"] for item in events].count("step.failed") == 1
        assert [item["type"] for item in events].count("plan.replan_skipped") == 1
        assert [item["type"] for item in events].count("plan.replanned") == 0


def test_failed_empty_candidate_chain_retries_from_search_without_repeating_inspection() -> None:
    steps = [
        {
            "id": "inspect", "title": "检查素材", "tool": "inspect_workspace",
            "arguments": {}, "dependencies": [], "expectedOutput": "素材状态",
            "sideEffect": "read", "estimatedSeconds": 1, "optional": False,
        },
        {
            "id": "search", "title": "提取证据", "tool": "search_content",
            "arguments": {"query": "分别查找三类片段"}, "dependencies": ["inspect"],
            "expectedOutput": "候选", "sideEffect": "analysis", "estimatedSeconds": 1,
            "optional": False,
        },
        {
            "id": "review", "title": "自动筛选", "tool": "review_content_evidence",
            "arguments": {"query": "分别查找三类片段"}, "dependencies": ["search"],
            "expectedOutput": "自动候选", "sideEffect": "review", "estimatedSeconds": 1,
            "optional": False,
        },
    ]
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory), steps=steps)
        calls: list[str] = []
        platform.configure_tool_dispatcher(
            lambda _workspace, tool, _arguments: calls.append(tool) or {"ok": True},
        )
        workspace = platform.create_workspace(job_id="job_retry_candidates")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="分别查找三类片段")
        plan["status"] = "failed"
        plan["steps"][0].update({"status": "completed", "result": {"ok": True}})
        plan["steps"][1].update({"status": "completed", "result": {"operationCompleted": True}})
        plan["steps"][2].update({
            "status": "failed", "error": "内容检索没有生成可用于自动编排的有效候选",
        })
        platform.store.save("plans", plan)

        recovered = platform.retry_action(plan["id"])

        assert recovered["status"] == "action_required"
        assert calls == ["search_content"]
        assert recovered["steps"][0]["status"] == "completed"
        assert recovered["steps"][1]["status"] == "completed"


def test_qc_failed_preview_can_rebuild_from_evidence_without_repeating_search() -> None:
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        calls: list[str] = []
        platform.configure_tool_dispatcher(
            lambda _workspace, tool, _arguments: calls.append(tool) or {"ok": True},
        )
        workspace = platform.create_workspace(job_id="job_retry_qc")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="重建审核样片")
        plan.update({
            "status": "preview_ready", "executionMode": "autonomous_review",
            "brief": {"targetSeconds": 60, "durationToleranceSeconds": 6},
        })
        plan["steps"] = [
            {
                "id": "inspect", "tool": "inspect_workspace", "title": "检查素材",
                "arguments": {}, "dependencies": [], "sideEffect": "read", "optional": False,
                "status": "completed", "attempts": 1, "result": {"ok": True},
            },
            {
                "id": "search", "tool": "search_content", "title": "检索内容",
                "arguments": {"query": "三类内容"}, "dependencies": ["inspect"],
                "sideEffect": "analysis", "optional": False, "status": "completed", "attempts": 1,
                "result": {"ok": True},
            },
            {
                "id": "review", "tool": "review_content_evidence", "title": "均衡候选",
                "arguments": {"query": "三类内容"}, "dependencies": ["search"],
                "sideEffect": "review", "optional": False, "status": "completed", "attempts": 1,
                "result": {"ok": True},
            },
            {
                "id": "timeline", "tool": "propose_timeline_edit", "title": "重建时间线",
                "arguments": {"instruction": "每类20秒"}, "dependencies": ["review"],
                "sideEffect": "preview", "optional": False, "status": "completed", "attempts": 1,
                "result": {"ok": True},
            },
            {
                "id": "preview", "tool": "render_review_preview", "title": "审核样片",
                "arguments": {}, "dependencies": ["timeline"], "sideEffect": "preview",
                "optional": False, "status": "completed", "attempts": 1,
                "result": {"artifact": {"kind": "review_preview_batch", "previews": [{"duration": 40}]}},
            },
            {
                "id": "qc", "tool": "run_delivery_qc", "title": "质检",
                "arguments": {"strict": True}, "dependencies": ["preview"],
                "sideEffect": "analysis", "optional": False, "status": "completed", "attempts": 1,
                "result": {"artifact": {"kind": "delivery_qc_report", "passed": False}},
            },
        ]
        platform.store.save("plans", plan)

        recovered = platform.retry_action(plan["id"])

        assert recovered["status"] == "preview_ready"
        assert calls == [
            "review_content_evidence", "propose_timeline_edit", "render_review_preview", "run_delivery_qc",
        ]
        assert recovered["steps"][0]["status"] == "completed"
        assert recovered["steps"][1]["status"] == "completed"


def test_replan_reuse_signature_invalidates_downstream_confirmation() -> None:
    previous = [{
        "id": "timeline", "tool": "propose_timeline_edit",
        "arguments": {"instruction": "保留完整动作"}, "dependencies": [],
    }, {
        "id": "confirm", "tool": "confirm_timeline_edit",
        "arguments": {}, "dependencies": ["timeline"],
    }]
    unchanged = [dict(step) for step in previous]
    changed = [{
        **previous[0], "arguments": {"instruction": "改为二倍速"},
    }, dict(previous[1])]

    old_signatures = AgentPlatform._step_execution_signatures(previous)
    unchanged_signatures = AgentPlatform._step_execution_signatures(unchanged)
    changed_signatures = AgentPlatform._step_execution_signatures(changed)

    assert unchanged_signatures["confirm"] == old_signatures["confirm"]
    assert changed_signatures["timeline"] != old_signatures["timeline"]
    assert changed_signatures["confirm"] != old_signatures["confirm"]


def test_material_replan_requires_a_new_confirmation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))

        def fail_and_expand(_workspace: dict[str, Any], _tool: str, _arguments: dict[str, Any]) -> dict[str, Any]:
            platform.client.steps = [{
                "id": "analysis", "title": "新增分析", "tool": "analyze_highlights",
                "arguments": {}, "dependencies": [], "expectedOutput": "高光候选",
                "sideEffect": "analysis", "estimatedSeconds": 30, "optional": False,
            }]
            raise RuntimeError("inspection cannot continue")

        platform.configure_tool_dispatcher(fail_and_expand)
        workspace = platform.create_workspace(job_id="job_test")
        plan = platform.create_plan(workspace_id=workspace["id"], goal="需要扩大能力")
        replanned = platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
        assert replanned["status"] == "awaiting_confirmation"
        assert replanned["approval"] is None
        assert replanned["replanCount"] == 1
        assert replanned["steps"][0]["tool"] == "analyze_highlights"


def test_store_events_are_ordered_and_skill_frontmatter_is_strict() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = AgentStore(Path(directory) / "agent.sqlite3")
        first = store.append_event("ws_1", "one", {"value": 1})
        second = store.append_event("ws_1", "two", {"value": 2})
        assert [item["type"] for item in store.events_after("ws_1", first["sequence"])] == ["two"]
        assert second["sequence"] > first["sequence"]

    assert parse_skill_markdown(SKILL)["name"] == "test-editor"
    with pytest.raises(ValueError, match="Skill name"):
        parse_skill_markdown(SKILL.replace("test-editor", "Bad Skill"))


def test_agent_upload_entry_creates_a_source_workspace_without_enqueuing_analysis() -> None:
    from app import main
    from app.store import JobStore

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        original_settings, original_store, original_agent_platform = main.settings, main.job_store, main.agent_platform
        main.settings = replace(original_settings, data_root=root)
        main.settings.ensure_directories()
        main.job_store = JobStore(root / "jobs.sqlite3")
        main.agent_platform = AgentPlatform(
            data_root=root, service_url="http://agent.invalid",
            model_config_resolver=lambda: {"model": "fake"},
        )
        main.agent_platform.configure_workspace_state_listener(main.sync_agent_workspace_to_job)
        uploaded = UploadFile(filename="interview.mp4", file=io.BytesIO(b"video"))
        video_info = SimpleNamespace(
            duration=60.0, width=1280, height=720, has_audio=True,
            video_duration=60.0, audio_duration=60.0, container_duration=60.0,
            frame_rate=25.0,
        )
        try:
            with patch.object(main, "probe_video", return_value=video_info), patch.object(
                main, "validate_video_decodable_coverage", return_value={"status": "ready", "warnings": []},
            ), patch.object(main, "schedule_job_thumbnail"), patch.object(main, "enqueue_job") as enqueue:
                result = asyncio.run(main.create_job(
                    video=uploaded, upload_session_id="", expected_size_bytes="",
                    task_mode="content_extract", intent_mode="content_extract",
                    parameter_context="adaptive_v1", storage_mode="editable",
                    instruction="剪成一段访谈精华", count="auto", target_seconds="auto",
                    total_target_seconds="", theme="", analysis_mode="audiovisual",
                    recognition_profile="auto", force_reanalyze="false", subtitle_mode="none",
                    subtitle_style="clean", edit_mode="ai_plan", structure="auto",
                    auto_variant_count="3", technique_preset="auto", allow_speed="true",
                    allow_transitions="true", allow_audio_bridges="true", allow_cutaways="true",
                    allow_silence_compression="true", allow_cold_open="false",
                    source_scope_kind="all", source_scope_start="", source_scope_end="",
                    result_strategy="smart", search_scope_kind="all", search_scope_start="",
                    search_scope_end="", search_result_limit="12", search_boundary_mode="complete",
                    content_auto_generate="false", content_exclusions="", search_evidence_mode="",
                    search_allowed_capabilities="", entry_workflow="agent", workflow_kind="content_search",
                ))
            job = result["job"]
            assert job["status"] == "awaiting_agent_plan"
            assert job["stage"] == "agent_workspace_ready"
            assert job["request"]["entryWorkflow"] == "agent"
            assert job["agent"]["workspaceId"]
            enqueue.assert_not_called()
        finally:
            for job_id, job in list(main.jobs.items()):
                if str(job.get("sourcePath") or "").startswith(str(root)):
                    main.jobs.pop(job_id, None)
                    main.cancel_events.pop(job_id, None)
            main.settings, main.job_store, main.agent_platform = original_settings, original_store, original_agent_platform


def test_agent_draft_idempotency_is_bound_to_draft_session_not_source_hash() -> None:
    from app import main
    from app.store import JobStore

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        original_settings, original_store, original_agent_platform = main.settings, main.job_store, main.agent_platform
        main.settings = replace(original_settings, data_root=root)
        main.settings.ensure_directories()
        main.job_store = JobStore(root / "jobs.sqlite3")
        main.agent_platform = AgentPlatform(
            data_root=root, service_url="http://agent.invalid",
            model_config_resolver=lambda: {"model": "fake"},
        )
        main.agent_platform.configure_workspace_state_listener(main.sync_agent_workspace_to_job)
        video_info = SimpleNamespace(
            duration=60.0, width=1280, height=720, has_audio=True,
            video_duration=60.0, audio_duration=60.0, container_duration=60.0,
            frame_rate=25.0,
        )

        def create_draft(draft_session_id: str) -> dict[str, Any]:
            return asyncio.run(main.create_job(
                video=UploadFile(filename="same-video.mp4", file=io.BytesIO(b"same video bytes")),
                upload_session_id="", expected_size_bytes="",
                task_mode="highlight", intent_mode="highlight",
                parameter_context="adaptive_v1", storage_mode="editable",
                instruction="", count="auto", target_seconds="auto",
                total_target_seconds="", theme="", analysis_mode="audiovisual",
                recognition_profile="auto", force_reanalyze="false", subtitle_mode="none",
                subtitle_style="clean", edit_mode="ai_plan", structure="auto",
                auto_variant_count="3", technique_preset="auto", allow_speed="true",
                allow_transitions="true", allow_audio_bridges="true", allow_cutaways="true",
                allow_silence_compression="true", allow_cold_open="false",
                source_scope_kind="all", source_scope_start="", source_scope_end="",
                result_strategy="smart", search_scope_kind="all", search_scope_start="",
                search_scope_end="", search_result_limit="12", search_boundary_mode="complete",
                content_auto_generate="false", content_exclusions="", search_evidence_mode="",
                search_allowed_capabilities="", entry_workflow="agent", workflow_kind="highlight",
                agent_draft="true", draft_session_id=draft_session_id,
            ))["job"]

        try:
            with patch.object(main, "probe_video", return_value=video_info), patch.object(
                main, "validate_video_decodable_coverage", return_value={"status": "ready", "warnings": []},
            ), patch.object(main, "schedule_job_thumbnail"), patch.object(main, "enqueue_job") as enqueue:
                first = create_draft("draft-a")
                retry = create_draft("draft-a")
                second = create_draft("draft-b")

            assert retry["id"] == first["id"]
            assert second["id"] != first["id"]
            first_private = main.jobs[first["id"]]
            second_private = main.jobs[second["id"]]
            assert first_private["sourceHash"] == second_private["sourceHash"]
            assert first["messages"] != second["messages"]
            assert first["draftSessionId"] == "draft-a"
            assert second["draftSessionId"] == "draft-b"
            enqueue.assert_not_called()
        finally:
            for job_id, job in list(main.jobs.items()):
                if str(job.get("sourcePath") or "").startswith(str(root)):
                    main.jobs.pop(job_id, None)
                    main.cancel_events.pop(job_id, None)
            main.settings, main.job_store, main.agent_platform = original_settings, original_store, original_agent_platform


def test_v2_editing_brief_parses_real_chinese_requests_without_hidden_deliverables() -> None:
    female = AgentPlatform._editing_brief("找到女性说话的片段", {})
    assert female["speakerTargeted"] is True
    assert female["personTargeted"] is False
    assert female["delivery"] == "candidates"
    assert female["subtitleRequested"] is False
    assert female["reviewPreviewRequested"] is False

    keep_only = AgentPlatform._editing_brief(
        "只保留讲解手机芯片型号和跑分参数的片段，剪成约 30 秒审核样片。", {},
    )
    assert keep_only["retrievalQuery"] == "讲解手机芯片型号和跑分参数"
    assert keep_only["requiresEvidenceReview"] is True

    interview_topics = AgentPlatform._editing_brief(
        "把不同员工关于入职、成长和未来的回答组织成约 90 秒访谈精华，保留必要问题上下文。", {},
    )
    assert interview_topics["retrievalQuery"] == "入职、成长和未来"

    minute = AgentPlatform._editing_brief("找到产品演示并剪成一分钟成片", {})
    assert minute["targetSeconds"] == 60
    assert minute["durationExplicit"] is True
    assert minute["retrievalQuery"] == "产品演示"

    social = AgentPlatform._editing_brief("找到做家务的片段并合成为 9:16，保留完整画面，人物靠左", {})
    assert social["retrievalQuery"] == "做家务"
    assert social["socialDelivery"] == {
        "requested": True, "aspect": "9:16", "fit": "blur", "focusX": .25, "focusY": .5,
    }
    plain_vertical = AgentPlatform._editing_brief("找出刷碗和切西瓜的片段，最后成片要竖屏", {})
    assert plain_vertical["socialDelivery"]["fit"] == "blur"
    source_landscape_target_vertical = AgentPlatform._editing_brief(
        "找出所有关于汽车的画面，按源视频时间顺序合成竖屏视频；原视频是横屏，要最大化保留原始画面信息。",
        {},
    )
    assert source_landscape_target_vertical["socialDelivery"]["aspect"] == "9:16"
    no_default_duration = AgentPlatform._editing_brief(
        "找出所有关于汽车的画面，不限制总时长，有多少用多少，不要因为默认 30 秒目标丢片段。",
        {},
    )
    assert no_default_duration["targetSeconds"] is None
    assert no_default_duration["durationExplicit"] is False
    assert no_default_duration["selectionMode"] == "include"
    multiple_negative_defaults = AgentPlatform._editing_brief(
        "找出全片所有关于汽车的画面并合成视频；我没有指定成片时长，"
        "不要自动套用 30 秒或 60 秒目标，也不要丢掉超出默认时长的命中片段。",
        {},
    )
    assert multiple_negative_defaults["targetSeconds"] is None
    assert multiple_negative_defaults["durationExplicit"] is False
    assert multiple_negative_defaults["selectionMode"] == "include"
    interaction = AgentPlatform._editing_brief(
        "只保留主持人与歌手交谈的内容，不要演唱。", {},
    )
    assert interaction["retrievalQuery"] == "主持人与歌手交谈"
    assert interaction["speakerTargeted"] is False
    assert interaction["selectionMode"] == "include"
    launch_event = AgentPlatform._editing_brief(
        "剪一条约 60 秒的小米汽车发布会精华，保持横屏。", {},
    )
    assert launch_event["deliveryExportRequested"] is False
    vertical_cut = AgentPlatform._editing_brief(
        "做一个竖屏成片，最开头加封面。", {},
    )
    assert vertical_cut["socialDelivery"]["aspect"] == "9:16"
    search_only = AgentPlatform._editing_brief(
        "只检索并列出所有关于冰箱的候选片段和源视频时间，"
        "不要创建成片、封面或审核样片；等我确认候选后再进入时间线。",
        {},
    )
    assert search_only["retrievalQuery"] == "冰箱"
    assert search_only["delivery"] == "candidates"
    assert search_only["coverRequested"] is False
    assert search_only["reviewPreviewRequested"] is False
    washer_preview = AgentPlatform._editing_brief(
        "找出所有关于洗衣机的画面，合成竖屏审核样片；"
        "每段顶部叠加对应字幕，开头使用本次任务从源视频生成的封面。",
        {},
    )
    assert washer_preview["socialDelivery"]["aspect"] == "9:16"
    assert washer_preview["coverIntroRequested"] is True
    format_only = AgentPlatform._editing_brief(
        "输出 1:1 方屏，左右两边的重要人物和字幕都不能被裁掉。", {},
    )
    assert format_only["formatOnly"] is True
    assert format_only["subtitleRequested"] is False
    for instruction, aspect in (
        ("生成方形审核片", "1:1"),
        ("最终成品给我方屏比例", "1:1"),
        ("生成 4:5 审核片", "4:5"),
        ("生成 16:9 审核片", "16:9"),
    ):
        delivery = AgentPlatform._editing_brief(instruction, {})["socialDelivery"]
        assert delivery["aspect"] == aspect
        assert delivery["fit"] == "blur"
    cropped = AgentPlatform._editing_brief("生成 9:16 并居中裁切", {})
    assert cropped["socialDelivery"]["fit"] == "crop"
    black_bars = AgentPlatform._editing_brief("生成 9:16 并保留黑边", {})
    assert black_bars["socialDelivery"]["fit"] == "pad"

    appliance = AgentPlatform._editing_brief(
        "帮我找出三个片段，分别是冰箱、空调、洗衣机的新老替换片段。"
        "每个片段要20s，组合成一个60s的视频。最终成品给我方屏比例。",
        {},
    )
    assert appliance["retrievalQuery"] == "分别查找冰箱、空调、洗衣机的新老替换，各类片段作为并列候选"
    assert appliance["targetSeconds"] == 60
    assert appliance["socialDelivery"] == {
        "requested": True, "aspect": "1:1", "fit": "blur", "focusX": .5, "focusY": .5,
    }

    spliced = AgentPlatform._editing_brief(
        "三类每段约20秒，按冰箱、空调、洗衣机顺序拼接成约60秒成品。", {},
    )
    assert spliced["targetSeconds"] == 60

    explicit_tolerance = AgentPlatform._editing_brief(
        "每类约 20 秒，组合成 60±6 秒视频；生成 9:16 审核预览并质检。", {},
    )
    assert explicit_tolerance["targetSeconds"] == 60
    assert explicit_tolerance["durationToleranceSeconds"] == 6

    cover_landscape_video_portrait = AgentPlatform._editing_brief(
        "找出汽车画面，封面做成16:9，视频竖屏。", {},
    )
    assert cover_landscape_video_portrait["coverAspect"] == "16:9"
    assert cover_landscape_video_portrait["socialDelivery"]["aspect"] == "9:16"
    assert cover_landscape_video_portrait["delivery"] == "timeline"

    time_anchor = AgentPlatform._editing_brief("从 1:20 出现汽车的地方开始剪。", {})
    assert time_anchor["targetSeconds"] is None
    assert time_anchor["retrievalQuery"] == "汽车"
    assert time_anchor["anchorStart"] == {
        "query": "汽车", "selectionPolicy": "unique_or_review", "sourceTimeSeconds": 80.0,
    }

    quoted_graphics = AgentPlatform._editing_brief(
        "找出所有汽车画面，顶部添加“小米汽车”文字。", {},
    )
    assert quoted_graphics["graphicsRequested"] is True
    assert quoted_graphics["graphicsText"] == "小米汽车"

    assert AgentPlatform._replan_force_replay_tools({
        "tool": "review_content_evidence",
        "error": "内容检索没有生成可用于自动编排的有效候选",
    }) == {"search_content"}
    assert AgentPlatform._replan_force_replay_tools({
        "tool": "review_content_evidence",
        "error": "自动编排缺少必要类别的候选：空调换新",
    }) == {"search_content"}


def test_project_output_aspect_is_a_delivery_default_not_a_search_command() -> None:
    context = {"delivery": {"outputAspect": "9:16"}}

    generated = AgentPlatform._editing_brief("生成一条高光成片", context)
    assert generated["delivery"] == "timeline"
    assert generated["socialDelivery"] == {
        "requested": True, "aspect": "9:16", "fit": "blur", "focusX": .5, "focusY": .5,
    }

    search_only = AgentPlatform._editing_brief("找出所有汽车画面", context)
    assert search_only["delivery"] == "candidates"
    assert search_only["socialDelivery"]["requested"] is False

    explicit_override = AgentPlatform._editing_brief("生成横屏 16:9 高光成片", context)
    assert explicit_override["socialDelivery"]["aspect"] == "16:9"


def test_content_and_social_delivery_are_compiled_as_one_versioned_skill_chain() -> None:
    content_skill = """---
name: cliptalk-content-extractor
version: 1.1.0
description: Content extraction test profile.
allowed-tools: inspect_workspace search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: content
---

# Content
"""
    social_skill = """---
name: cliptalk-social-reframe-exporter
version: 1.1.0
description: Social delivery test profile.
allowed-tools: inspect_workspace render_social_preview run_delivery_qc
workflow-profile: social-reframe
---

# Social
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=content_skill, source="test", status="enabled")
        platform.install_skill(markdown=social_skill, source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "editing": {"hasOutputs": False},
            "evidence": {"hasCandidates": False},
        })
        workspace = platform.create_workspace(job_id="job_composite_social")
        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-content-extractor",
            goal="找到做家务的片段并合理组合成 60 秒 9:16 竖屏审核版本",
        )
        assert [(item["id"], item["role"], item["version"]) for item in plan["skills"]] == [
            ("cliptalk-content-extractor", "primary", "1.1.0"),
            ("cliptalk-social-reframe-exporter", "addon", "1.1.0"),
        ]
        assert [step["tool"] for step in plan["steps"]] == [
            "inspect_workspace", "search_content", "review_content_evidence",
            "propose_timeline_edit", "confirm_timeline_edit", "render_review_preview",
            "render_social_preview", "run_delivery_qc",
        ]
        assert plan["steps"][6]["arguments"]["aspect"] == "9:16"
        assert plan["steps"][6]["arguments"]["fit"] == "blur"
        assert plan["steps"][7]["arguments"] == {
            "strict": True, "targetSeconds": 60.0, "toleranceSeconds": 6.0,
        }
        evidence_step = plan["steps"][2]
        assert evidence_step["title"] == "自动筛选用于组合的候选片段"
        assert evidence_step["expectedOutput"] == "Agent 自动选定的候选片段及其排列范围"
        assert "随后自动生成 9:16 社媒审核预览并质检" in plan["summary"]
        assert "确认时间线后" not in plan["summary"]


def test_agent_cover_intro_composes_from_latest_social_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app import main

    job_id = "job_agent_cover_intro_from_social_preview"
    work = tmp_path / "work"
    outputs = tmp_path / "outputs"
    cover = work / "cover-director" / "draft" / "variants" / "approved.jpg"
    social = outputs / "agent-social-9x16-blur.mp4"
    work.mkdir()
    outputs.mkdir()
    cover.parent.mkdir(parents=True)
    cover.write_bytes(b"cover")
    social.write_bytes(b"vertical-review")
    job = {
        "id": job_id,
        "revision": 1,
        "workflowKind": "content_search",
        "workDirectory": str(work),
        "outputDirectory": str(outputs),
        "currentCoverVersionId": "cover_v001",
        "coverVersions": [{
            "id": "cover_v001",
            "artifactFile": str(cover.relative_to(work)),
            "contentHash": "sha256:test",
        }],
        "outputs": [],
        "outputVersions": [],
        "agentPreviewOutputs": [{
            "filename": social.name,
            "title": "9:16 虚化背景审核预览",
            "duration": 12.0,
            "width": 1080,
            "height": 1920,
            "previewOnly": True,
            "outputKind": "social_reframe_preview",
            "socialReframe": True,
            "reframe": {"aspect": "9:16", "fit": "blur", "focusX": .5, "focusY": .5},
        }],
    }
    monkeypatch.setitem(main.jobs, job_id, job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    captured: dict[str, Any] = {}

    def render(video: Path, cover_path: Path, output: Path, **_kwargs: Any) -> dict[str, Any]:
        captured["video"] = video
        captured["cover"] = cover_path
        output.write_bytes(b"cover-intro-preview")
        return {"duration": 13.0, "width": 1080, "height": 1920, "hasAudio": True, "introDuration": 1.0}

    def submit(worker: Any) -> Future[dict[str, Any]]:
        future: Future[dict[str, Any]] = Future()
        try:
            future.set_result(worker())
        except Exception as error:  # pragma: no cover - surfaced by result()
            future.set_exception(error)
        return future

    monkeypatch.setattr(main, "render_cover_intro", render)
    monkeypatch.setattr(main.output_preview_executor, "submit", submit)

    queued = main.dispatch_agent_tool(
        {"jobId": job_id, "executionMode": "autonomous_review"},
        "compose_cover_intro", {"duration": 1.0},
    )
    artifact = queued["future"].result()["artifact"]

    assert artifact["kind"] == "cover_intro_review_preview"
    assert captured["video"] == social
    assert captured["cover"] == cover
    assert len(job["agentPreviewOutputs"]) == 2
    output = job["agentPreviewOutputs"][-1]
    assert output["previewOnly"] is True
    assert output["outputKind"] == "cover_intro_review_preview"
    assert output["sourceOutputFilename"] == social.name
    assert output["reframe"] == {"aspect": "9:16", "fit": "blur", "focusX": .5, "focusY": .5}
    assert output["coverIntro"]["coverVersionId"] == "cover_v001"
    assert not job.get("outputVersions")


def test_vertical_content_cover_intro_and_top_captions_compile_to_one_final_preview_chain() -> None:
    content_skill = """---
name: cliptalk-content-extractor
version: 1.1.0
description: Content extraction test profile.
allowed-tools: inspect_workspace search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: content
---

# Content
"""
    social_skill = """---
name: cliptalk-social-reframe-exporter
version: 1.1.0
description: Social delivery test profile.
allowed-tools: inspect_workspace render_social_preview run_delivery_qc
workflow-profile: social-reframe
---

# Social
"""
    cover_skill = """---
name: cliptalk-cover-director
version: 1.1.0
description: Cover creation.
allowed-tools: inspect_workspace propose_cover_candidates render_cover_variants review_cover_variants confirm_cover
workflow-profile: cover
---

# Cover
"""
    cover_intro_skill = """---
name: cliptalk-cover-intro-composer
version: 1.1.0
description: Cover intro composer.
allowed-tools: inspect_workspace propose_cover_candidates render_cover_variants review_cover_variants confirm_cover compose_cover_intro run_delivery_qc
workflow-profile: cover-intro
---

# Cover intro
"""
    caption_skill = """---
name: cliptalk-caption-layout-director
version: 1.1.0
description: Caption layout.
allowed-tools: inspect_workspace layout_subtitles prepare_subtitle_review render_review_preview export_subtitles
workflow-profile: caption-layout
---

# Captions
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        for markdown in (content_skill, social_skill, cover_skill, cover_intro_skill, caption_skill):
            platform.install_skill(markdown=markdown, source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id, "editing": {"hasOutputs": False},
            "evidence": {"hasCandidates": False},
        })
        workspace = platform.create_workspace(job_id="job_composite_final_preview")
        goal = (
            "找出所有关于汽车的画面，合成竖屏审核样片；每段顶部叠加对应字幕，"
            "开头使用本次任务从源视频生成的封面，封面文字写‘小米牛逼！’，不能复用其他任务封面。"
        )

        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-content-extractor",
            goal=goal,
        )

        assert [item["id"] for item in plan["skills"]] == [
            "cliptalk-content-extractor",
            "cliptalk-social-reframe-exporter",
            "cliptalk-cover-intro-composer",
            "cliptalk-caption-layout-director",
            "cliptalk-cover-director",
        ]
        tools = [step["tool"] for step in plan["steps"]]
        assert tools == [
            "inspect_workspace",
            "search_content",
            "review_content_evidence",
            "propose_timeline_edit",
            "confirm_timeline_edit",
            "prepare_subtitle_review",
            "layout_subtitles",
            "render_review_preview",
            "propose_cover_candidates",
            "render_cover_variants",
            "review_cover_variants",
            "confirm_cover",
            "render_social_preview",
            "compose_cover_intro",
            "run_delivery_qc",
        ]
        by_tool = {step["tool"]: step for step in plan["steps"]}
        subtitle_previews = [step for step in plan["steps"] if step["tool"] == "render_review_preview"]
        assert by_tool["layout_subtitles"]["arguments"] == {"position": "top", "style": "clean"}
        assert by_tool["prepare_subtitle_review"]["arguments"]["requireConfirmedDraft"] is False
        assert by_tool["prepare_subtitle_review"]["arguments"]["autoReview"] is True
        assert [step["title"] for step in subtitle_previews] == ["生成带字幕最终审核样片"]
        assert by_tool["prepare_subtitle_review"]["dependencies"] == [by_tool["confirm_timeline_edit"]["id"]]
        assert by_tool["layout_subtitles"]["dependencies"] == [by_tool["prepare_subtitle_review"]["id"]]
        assert subtitle_previews[0]["dependencies"] == [by_tool["layout_subtitles"]["id"]]
        assert by_tool["render_social_preview"]["arguments"]["aspect"] == "9:16"
        assert by_tool["render_social_preview"]["arguments"]["fit"] == "blur"
        assert by_tool["render_cover_variants"]["arguments"]["titleText"] == "小米牛逼！"
        assert by_tool["compose_cover_intro"]["dependencies"] == [
            by_tool["confirm_cover"]["id"],
            by_tool["render_social_preview"]["id"],
        ]
        assert by_tool["run_delivery_qc"]["dependencies"] == [by_tool["compose_cover_intro"]["id"]]


@pytest.mark.parametrize(
    ("skill_id", "workflow_profile", "goal", "context_key", "selection_tool"),
    [
        ("cliptalk-speaker-editor", "speaker", "只保留女性说话片段并剪成成片", "speaker", "select_speakers"),
        ("cliptalk-person-editor", "person", "删除已选男性的出镜片段", "people", "select_people"),
    ],
)
def test_reliable_identity_selection_is_reused_without_a_duplicate_gate(
    skill_id: str, workflow_profile: str, goal: str, context_key: str, selection_tool: str,
) -> None:
    discovery_tool = "discover_speakers" if workflow_profile == "speaker" else "discover_people"
    allowed = (
        "inspect_workspace discover_speakers select_speakers search_content review_content_evidence "
        "propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview"
        if workflow_profile == "speaker" else
        "inspect_workspace discover_people select_people propose_timeline_edit confirm_timeline_edit "
        "prepare_subtitle_review render_review_preview"
    )
    skill_markdown = f"""---
name: {skill_id}
version: 1.1.0
description: Identity reuse test profile.
allowed-tools: {allowed}
workflow-profile: {workflow_profile}
---

# Identity
"""
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown=skill_markdown, source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id,
            context_key: {
                "available": True, "needsDiscovery": False,
                "needsConfirmation": False, "selectedCount": 1,
            },
            "evidence": {"hasCandidates": True},
        })
        workspace = platform.create_workspace(job_id=f"job_{workflow_profile}_reuse")
        plan = platform.create_plan(workspace_id=workspace["id"], skill_id=skill_id, goal=goal)
        tools = [step["tool"] for step in plan["steps"]]
        assert discovery_tool not in tools
        assert selection_tool not in tools


def test_autonomous_person_discovery_finishes_with_agent_identity_gate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        platform = platform_at(Path(directory))
        platform.install_skill(markdown="""---
name: cliptalk-person-editor
version: 1.1.0
description: Person editor test profile.
allowed-tools: inspect_workspace discover_people select_people propose_timeline_edit confirm_timeline_edit render_review_preview
workflow-profile: person
---

# Person editor
""", source="test", status="enabled")
        platform.configure_planning_context_provider(lambda job_id: {
            "jobId": job_id,
            "people": {
                "available": False, "needsDiscovery": True,
                "needsConfirmation": True, "selectedCount": 0,
            },
            "evidence": {"hasCandidates": False},
        })
        workspace = platform.create_workspace(job_id="job_person_autonomous_gate")
        plan = platform.create_plan(
            workspace_id=workspace["id"], skill_id="cliptalk-person-editor",
            goal="只保留穿黑色上衣的男士提到 AI 的完整回答，剪成 30 秒样片",
        )

        tools = [step["tool"] for step in plan["steps"]]
        assert tools[:3] == ["inspect_workspace", "discover_people", "select_people"]
        assert plan["steps"][2]["title"] == "Agent 核定目标人物"
        assert plan["executionMode"] == "autonomous_review"


def test_skill_frontmatter_version_is_declared_and_validated() -> None:
    versioned = SKILL.replace("description:", "version: 2.3.4\ndescription:")
    assert parse_skill_markdown(versioned)["version"] == "2.3.4"
    with pytest.raises(ValueError, match="version"):
        parse_skill_markdown(versioned.replace("2.3.4", "v2"))
