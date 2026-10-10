"""Offline regression matrix for the 2026-09-25 algorithm audit."""
import copy
import time

import pytest

from app.agent_platform import AgentPlatform
from app.automatic_delivery_effects import delivery_effects
from app.content_search import rank_units
from app.delivery_contract import audio_filters, duration_budget
from app.edl_optimizer import _select_duration_subset
from app.rendered_content_qc import assess_coverage, coverage_requirements, coverage_prompt


def test_delivery_time_translation_uses_frozen_timeline_without_mutation():
    from app.delivery_lineage import freeze_timeline, mapped_session
    session = {"id": "edit", "revision": 1, "schedule": [{"clipId": "c", "outputStart": 0, "outputEnd": 5}]}
    output = {"deliveryTimeline": freeze_timeline(session), "deliveryTimeMap": {"schemaVersion": 1, "bodyOffsetSeconds": 2.5}}
    session["schedule"][0]["outputStart"] = 4
    result = mapped_session(session, output)
    assert result["schedule"][0] == {"clipId": "c", "outputStart": 2.5, "outputEnd": 7.5}
    assert output["deliveryTimeline"]["schedule"][0]["outputStart"] == 0
    assert session["schedule"][0]["outputStart"] == 4


@pytest.mark.parametrize("count,expected", [(9, "clear"), (49, "unknown")])
def test_caption_check_scales_with_budget_without_false_clear(tmp_path, count, expected):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.source_subtitle_check import check_source_subtitles
    client = SimpleNamespace(analyze_image=Mock(return_value={"frames": [{"dialogueSubtitle": "absent", "confidence": .99}]}))
    runtime = SimpleNamespace(
        build_edit_session_render_plan=lambda *_: ([{"start": i * 5, "end": i * 5 + 4} for i in range(count)], []),
        extract_frames_at_times=lambda source, root, times, **kw: [SimpleNamespace(path=root / f"{i}.jpg") for i in range(len(times))],
        cancel_events={}, settings=SimpleNamespace(ffmpeg="ffmpeg"), create_vision_client_for_job=lambda _: client)
    report = check_source_subtitles(runtime, {"id": "job", "sourcePath": "source.mp4", "workDirectory": str(tmp_path)}, {}, {"id": "draft"})
    assert report["status"] == expected
    assert 0 < report["sampleCount"] <= 48
    assert report["coverageComplete"] is (count <= 48)


def test_quality_repair_can_return_to_highlight_analysis():
    from app.quality_repair import quality_repair_plan
    steps = [{"tool": t} for t in ("analyze_highlights", "propose_timeline_edit", "run_delivery_qc")]
    artifact = {"reports": [{"issues": [{"code": "content_goal_mismatch"}]}]}
    assert quality_repair_plan(artifact, steps)["replayFromTool"] == "analyze_highlights"
    assert not quality_repair_plan(artifact, steps, {"outputFilename": "selected.mp4"})["available"]


def test_repair_keeps_independent_completed_work():
    from app.quality_repair import repair_step_ids
    steps = [{"id": "analysis", "dependencies": []}, {"id": "cover", "dependencies": []},
             {"id": "edit", "dependencies": ["analysis"]}, {"id": "render", "dependencies": ["edit", "cover"]}]
    assert repair_step_ids(steps, "analysis") == {"analysis", "edit", "render"}


def test_stale_guard_kills_child_process(monkeypatch):
    import sys
    from app.media import _run_cancellable
    from app.process_supervisor import process_supervisor
    processes = []
    start = process_supervisor.start
    def record(*args, **kwargs):
        process = start(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(process_supervisor, "start", record)
    def stale():
        raise RuntimeError("stale plan")
    with pytest.raises(RuntimeError, match="stale plan"):
        _run_cancellable([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60, cancelled=stale)
    assert processes and all(process.poll() is not None for process in processes)


def test_direct_preflight_is_read_only_and_does_not_claim_a_preview(monkeypatch):
    from app import main
    session = {"id": "edit", "revision": 1}
    job = {"id": "test_direct_preflight", "editSessions": [session],
           "agentTimelineBatch": {"variants": [{"sessionId": "edit"}]}}
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "edit_session_preflight", lambda *_: {"ready": True})
    monkeypatch.setattr(main, "_edit_session_preview_fingerprint", lambda *_: "fp")
    original = copy.deepcopy(job)
    result = main.dispatch_agent_tool({"jobId": job["id"], "executionMode": "automatic_delivery"}, "prepare_delivery_timeline", {})
    assert result["artifact"]["kind"] == "delivery_timeline_ready"
    assert result["artifact"]["sessions"] == [{"sessionId": "edit", "revision": 1, "fingerprint": "fp"}]
    assert "future" not in result and "previewUrl" not in result["artifact"]
    assert job == original


def test_missing_cover_image_is_uncertainty_not_success(tmp_path):
    from app.cover_delivery import verify_cover_intro_frame
    assert verify_cover_intro_frame(tmp_path / "final.mp4", None, ffmpeg="unused", ffprobe="unused")["status"] == "unknown"


@pytest.mark.parametrize("goal", ["不要字幕但要封面", "不要字幕，但是要封面", "不要字幕，封面要加上"])
def test_contrast_preserves_affirmative_requirement(goal):
    brief = AgentPlatform._editing_brief(goal, {})
    assert not brief["subtitleRequested"]
    assert brief["coverRequested"]


@pytest.mark.parametrize("goal,target,tolerance", [
    ("剪成15±0.5秒的视频", 15, .5),
    ("剪成15.5秒，允许误差0.5秒", 15.5, .5),
    ("剪成15秒，允许误差0秒", 15, 0),
])
def test_fractional_duration_survives_parsing(goal, target, tolerance):
    brief = AgentPlatform._editing_brief(goal, {})
    assert brief["targetSeconds"] == target
    assert brief["durationToleranceSeconds"] == tolerance


def test_quieter_is_not_denoise_or_normalization():
    brief = AgentPlatform._editing_brief("只把当前成片音量调小一点，不要降噪", {})
    audio = delivery_effects({"profile": "audio-polish", "brief": brief})["audio"]
    assert audio_filters(audio) == ["volume=-3dB"]
    louder = AgentPlatform._editing_brief("音量提高6dB", {})
    assert audio_filters(louder["audioOperations"]) == ["volume=6dB"]


def test_music_removal_is_not_falsely_implemented_with_denoise():
    brief = AgentPlatform._editing_brief("为当前成片去掉背景音乐，保留人声", {})
    with pytest.raises(ValueError, match="不支持"):
        audio_filters(brief["audioOperations"])


def test_motion_intro_is_an_addon_to_highlights():
    brief = AgentPlatform._editing_brief("将视频剪成30秒，加1秒动态图文片头，标题写：新品发布", {})
    motion = delivery_effects({"profile": "highlight", "brief": brief})["motion"]
    assert motion["intro"] and motion["duration"] == 1
    assert motion["title"] == "新品发布"
    assert duration_budget(brief)["finalSeconds"] == 31


def test_inclusive_duration_reserves_intro_time():
    brief = AgentPlatform._editing_brief("剪成总时长15秒，包含1秒封面片头", {})
    assert duration_budget(brief)["bodySeconds"] == 14
    assert duration_budget(brief)["finalSeconds"] == 15
    with pytest.raises(ValueError, match="不足"):
        duration_budget({**brief, "targetSeconds": .5})


@pytest.mark.parametrize("score", [0, 90])
def test_explicit_negative_evidence_cannot_be_overruled_by_keyword(score):
    units = [{"id": "u1", "modality": "speech", "text": "这里没有汽车，只有冰箱", "start": 0, "end": 3}]
    models = [{"matches": [{"unit_id": "u1", "score": score, "satisfied": False,
                           "support_level": "explicit", "evidence_grounded": True, "reason": "明确说没有汽车"}]}]
    assert rank_units({"query": "汽车", "modalities": ["speech"]}, units, models) == []


@pytest.mark.parametrize("count", [16, 17, 50, 200])
def test_duration_selection_has_no_candidate_count_cliff(count):
    segments = [{"id": f"s{i}", "start": i * 5, "end": i * 5 + 4, "score": 80, "eventId": "e1"} for i in range(count)]
    before = copy.deepcopy(segments)
    started = time.monotonic()
    selected, _ = _select_duration_subset(segments, {}, target=30, upper_limit=33)
    assert 28 <= sum(s["end"] - s["start"] for s in selected) <= 33
    assert segments == before
    assert time.monotonic() - started < 15


def test_mandatory_clips_are_not_soft_preferences():
    segments = [{"id": f"s{i}", "start": i * 5, "end": i * 5 + 4, "score": 100} for i in range(20)]
    segments[-1].update(essential=True, score=0)
    selected, _ = _select_duration_subset(segments, {}, target=12, upper_limit=13)
    assert segments[-1] in selected
    for item in segments:
        item["essential"] = True
    with pytest.raises(ValueError, match="必须保留"):
        _select_duration_subset(segments, {}, target=12, upper_limit=13)


def test_coverage_requires_all_original_requirements():
    samples = [{"clipId": "c1", "evidence": {"ranges": [{"start": 0, "end": 3}]}}]
    raw = {"querySatisfied": True, "requirements": [{"requirement": "冰箱", "status": "supported", "clipIds": ["c1"], "reason": "画面中有冰箱"}]}
    result = assess_coverage(raw, samples, "展示冰箱和汽车")
    assert result["status"] == "needs_review"
    assert any("汽车" in issue["message"] for issue in result["issues"])
    raw["requirements"].append({"requirement": "汽车", "status": "supported", "clipIds": ["c1"], "reason": "后面有汽车"})
    assert assess_coverage(raw, samples, "展示冰箱和汽车")["status"] == "supported"


def test_coverage_ids_are_stable_and_more_than_twelve_requirements_checked():
    query = "、".join(f"主题{i}" for i in range(14))
    expected = coverage_requirements(query)
    assert len(expected) == 14
    assert expected == coverage_requirements(query)
    assert expected[0]["id"] in coverage_prompt({"query": query}, [], [])
    samples = [{"clipId": "c1", "evidence": {"ranges": []}}]
    raw = {"querySatisfied": True, "requirements": [
        {"requirementId": row["id"], "requirement": row["requirement"], "status": "supported", "clipIds": ["c1"], "reason": "已检查"}
        for row in expected[:-1]]}
    assert assess_coverage(raw, samples, query)["status"] == "needs_review"


@pytest.mark.parametrize("query", ["和平饭店", "中华人民共和国", "温和清洁"])
def test_coverage_does_not_split_lexical_conjunction(query):
    assert [row["requirement"] for row in coverage_requirements(query)] == [query]
