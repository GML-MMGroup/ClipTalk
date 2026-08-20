from app.editing_techniques import plan_editing_techniques
from app.quality_gate import build_quality_gate, deduplicate_issues, validate_edit_sequence
from app.main import _fit_edit_sequence_to_target


def _segment(identity: str, start: float, end: float, event: str, role: str = "development") -> dict:
    return {
        "id": identity,
        "candidateId": identity,
        "start": start,
        "end": end,
        "groupId": event,
        "chapterId": event,
        "role": role,
        "speechBoundaryStatus": "no_speech",
        "actionComplete": True,
        "score": 90,
    }


def test_cross_event_transition_uses_chapter_separator_and_no_audio_bridge():
    segments = [
        {**_segment("a", 0, 5, "event_a"), "hasSpeech": True},
        _segment("b", 80, 86, "event_b"),
    ]
    planned = plan_editing_techniques(segments, policy={"allowTransitions": True, "allowAudioBridges": True})
    assert planned["segments"][1]["transitionIn"]["type"] == "fade_black"
    assert planned["segments"][1]["audioBridge"]["type"] == "none"


def test_quality_gate_allows_multiple_contiguous_event_chapters():
    sequence = [
        _segment("a1", 0, 5, "event_a", "context"),
        _segment("a2", 5, 10, "event_a", "climax"),
        {**_segment("b1", 30, 36, "event_b", "result"), "transitionIn": {"type": "fade_black", "duration": .35}},
    ]
    result = validate_edit_sequence(sequence, target_seconds=18, require_verified_uncertainty=False)
    assert result["multiEventComposition"] is True
    assert result["chapterCount"] == 2
    assert not any(item["category"] == "cross_event_dissolve" for item in result["issues"])


def test_quality_gate_rejects_false_cross_event_continuity():
    sequence = [
        _segment("a", 0, 5, "event_a"),
        {
            **_segment("b", 60, 65, "event_b"),
            "transitionIn": {"type": "dissolve", "duration": .22},
            "audioBridge": {"type": "j_cut", "duration": .5},
        },
    ]
    result = validate_edit_sequence(sequence, require_verified_uncertainty=False)
    assert result["passed"] is False
    assert {item["category"] for item in result["issues"]} >= {
        "cross_event_dissolve", "cross_event_audio_bridge",
    }


def test_duration_overflow_is_a_hard_failure():
    result = validate_edit_sequence(
        [_segment("a", 0, 35, "event_a")],
        target_seconds=30,
        require_verified_uncertainty=False,
    )
    assert result["passed"] is False
    assert any(item["category"] == "duration_overflow" for item in result["issues"])


def test_review_gate_separates_display_and_recommend_thresholds():
    validation = {"passed": True, "issues": []}
    display = build_quality_gate({"calibratedScore": 79, "issues": [], "deterministicChecks": []}, validation)
    recommend = build_quality_gate({"calibratedScore": 86, "issues": [], "deterministicChecks": []}, validation)
    assert display["passed"] is True and display["recommended"] is False
    assert recommend["passed"] is True and recommend["recommended"] is True


def test_duplicate_model_and_deterministic_issues_are_penalized_once():
    merged = deduplicate_issues(
        [{"category": "speech_boundary", "severity": "major", "segmentIds": ["a"], "description": "对白截断"}],
        [{"category": "speech_boundary", "severity": "critical", "segmentIds": ["a"], "description": "句尾被截断"}],
    )
    assert len(merged) == 1
    assert merged[0]["severity"] == "critical"


def test_duration_fill_does_not_destroy_llm_order():
    selected = {
        **_segment("late", 50, 55, "event_late", "hook"),
        "chapterTitle": "冷开场",
        "editOrder": 0,
        "essential": True,
    }
    early = {
        **_segment("early", 5, 10, "event_early", "result"),
        "groupTitle": "补充章节",
        "standalone": True,
        "editorialScore": 92,
        "minimumKeepSeconds": 2,
    }
    candidates = {
        "late": {**selected, "id": "late", "groupTitle": "冷开场"},
        "early": early,
    }
    fitted, _ = _fit_edit_sequence_to_target([selected], candidates, 10)
    assert [item["candidateId"] for item in fitted] == ["late", "early"]
