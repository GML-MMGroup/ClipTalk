from __future__ import annotations

from app.evidence_graph import (
    PIPELINE_VERSION,
    build_evidence_graph,
    evidence_summary,
    feedback_route,
    select_evidence,
)
from app.main import adaptive_plan_variants, planning_transcript_context
from app.pipeline import HighlightCandidate, locally_align_candidate, refinement_candidate_limit


def sample_manifest() -> dict:
    return {
        "video": {"duration": 120.0},
        "contentProfile": {"primaryType": "新闻纪实", "narrativeMode": "事件因果"},
        "selectionBackend": "test-vlm",
        "promptVersion": "test",
        "candidates": [
            {
                "index": 0, "candidateId": "candidate_0", "start": 10.0, "end": 18.0,
                "score": 91, "title": "现场救援开始", "reason": "人员进入现场",
                "role": "事件建立", "boundaryConfidence": .9,
                "minimumKeepSeconds": 3.0, "peakStart": 13.0, "peakEnd": 15.0,
                "evidence": ["救援人员走向被困车辆"],
                "audioEvidence": {"transcriptExcerpt": "我们现在开始救援", "speakers": ["Speaker 1"]},
            },
            {
                "index": 1, "candidateId": "candidate_1", "start": 70.0, "end": 79.0,
                "score": 84, "title": "人员安全脱困", "reason": "事件出现结果",
                "role": "结果", "boundaryConfidence": .55,
                "minimumKeepSeconds": 2.0, "peakStart": 74.0, "peakEnd": 76.0,
                "evidence": ["被困人员离开车辆"], "audioEvidence": {},
            },
        ],
        "eventGroups": [{
            "id": "event_1", "title": "完整救援事件", "score": 92,
            "segments": [
                {"candidateId": "candidate_0"}, {"candidateId": "candidate_1"},
            ],
        }],
        "recommendedGroupIds": ["event_1"],
        "usage": [{"totalTokens": 100}],
    }


def test_build_evidence_graph_creates_traceable_units_and_uncertainty() -> None:
    graph = build_evidence_graph(
        sample_manifest(),
        intent={"softGoals": {"focus": ["救援"]}},
        source_hash="abc",
        model_budget={"vlmLimit": 3, "llmLimit": 4},
    )
    assert graph["pipelineVersion"] == PIPELINE_VERSION
    assert len(graph["units"]) == 2
    assert graph["events"][0]["unitIds"] == ["candidate_0", "candidate_1"]
    assert graph["units"][0]["facts"][0]["source"] == "vlm"
    assert graph["units"][0]["safeRanges"]["peak"] == {"start": 13.0, "end": 15.0}
    assert "candidate_1" in graph["uncertainUnitIds"]
    assert graph["modelBudget"]["vlmUsed"] == 1
    assert evidence_summary(graph)["unitCount"] == 2


def test_select_evidence_returns_only_requested_time_range() -> None:
    graph = build_evidence_graph(sample_manifest())
    selected = select_evidence(graph, start=0, end=30)
    assert [item["unitId"] for item in selected["units"]] == ["candidate_0"]
    assert selected["events"][0]["eventId"] == "event_1"


def test_feedback_router_avoids_full_reanalysis_for_editorial_changes() -> None:
    graph = build_evidence_graph(sample_manifest())
    assert feedback_route("更偏人物反应", graph)["route"] == "intent_update"
    assert feedback_route("把第三个镜头放到第一个前面", graph)["route"] == "pure_reorder"
    assert feedback_route("界面内容没有识别出来", graph)["route"] == "targeted_visual_search"
    assert feedback_route("重新通看全片", graph)["route"] == "full_reanalysis"


def test_refinement_budget_is_duration_aware_and_bounded() -> None:
    values = [
        refinement_candidate_limit(discovery_only=True, total_target_seconds=60, target_seconds=8, count=6, video_duration=120),
        refinement_candidate_limit(discovery_only=True, total_target_seconds=60, target_seconds=8, count=6, video_duration=600),
        refinement_candidate_limit(discovery_only=True, total_target_seconds=60, target_seconds=8, count=6, video_duration=1800),
        refinement_candidate_limit(discovery_only=True, total_target_seconds=60, target_seconds=8, count=6, video_duration=7200),
    ]
    assert values == [2, 4, 5, 6]


def test_v2_refinement_budget_uses_half_of_adaptive_recall_pool() -> None:
    assert refinement_candidate_limit(
        discovery_only=True, total_target_seconds=60, target_seconds=8,
        count=6, video_duration=7200, algorithm_version="editing-algorithm-v2",
    ) == 20
    assert refinement_candidate_limit(
        discovery_only=True, total_target_seconds=600, target_seconds=8,
        count=6, video_duration=120, algorithm_version="editing-algorithm-v2",
    ) == 24


def test_local_boundary_alignment_completes_intersecting_speech_turn() -> None:
    candidate = HighlightCandidate(
        start=10.0, end=13.0, score=80, title="回答", reason="候选", evidence=[],
        peak_start=11.0, peak_end=12.0, minimum_keep_seconds=1.0, boundary_confidence=.3,
    )
    aligned = locally_align_candidate(
        candidate,
        speech_segments=[{"start": 9.5, "end": 14.2, "text": "这是一个完整回答"}],
        scene_cuts=[], video_duration=30.0,
    )
    assert aligned.start == 9.5
    assert aligned.end == 14.2
    assert aligned.boundary_confidence >= .76
    assert aligned.audio_evidence.get("transcriptExcerpt")


def test_adaptive_variants_and_transcript_packet_follow_content() -> None:
    assert adaptive_plan_variants({"primaryType": "体育比赛"}, 2) == ["高能进程版", "逆转高潮版"]
    packet = planning_transcript_context(
        {"status": "completed", "speakers": ["A"], "segments": [
            {"start": 1, "end": 2, "text": "保留"},
            {"start": 50, "end": 51, "text": "丢弃"},
        ]},
        [{"start": 0, "end": 5}],
    )
    assert "保留" in packet
    assert "丢弃" not in packet
