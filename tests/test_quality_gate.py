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


def test_quality_gate_rejects_protected_climax_with_missing_required_context():
    climax = {
        **_segment("climax", 80, 90, "event_a", "climax"),
        "candidateIndex": 4,
        "standalone": False,
        "requiresCandidateIndices": [3],
    }
    result = validate_edit_sequence([climax], require_verified_uncertainty=False)
    assert result["passed"] is False
    issue = next(item for item in result["issues"] if item["category"] == "action_boundary")
    assert issue["severity"] == "critical"
    assert issue["segmentIds"] == ["climax"]
    assert "不能进入渲染" in issue["description"]


def test_extreme_duration_overflow_is_a_hard_failure():
    result = validate_edit_sequence(
        [_segment("a", 0, 40, "event_a")],
        target_seconds=30,
        require_verified_uncertainty=False,
    )
    assert result["passed"] is False
    assert any(item["category"] == "duration_overflow" for item in result["issues"])


def test_moderate_duration_gap_is_displayable_but_not_recommended():
    validation = validate_edit_sequence(
        [_segment("a", 0, 23, "event_a")],
        target_seconds=30,
        require_verified_uncertainty=False,
    )
    gate = build_quality_gate({
        "calibratedScore": 62, "issues": [], "deterministicChecks": [],
    }, validation)
    assert validation["passed"] is True
    assert validation["durationPreferred"] is False
    assert gate["passed"] is True
    assert gate["recommended"] is False


def test_moderate_duration_overflow_remains_displayable():
    validation = validate_edit_sequence(
        [_segment("a", 0, 35, "event_a")],
        target_seconds=30,
        require_verified_uncertainty=False,
    )
    assert validation["passed"] is True
    assert validation["durationPreferred"] is False


def test_review_gate_separates_display_and_recommend_thresholds():
    validation = {"passed": True, "issues": []}
    display = build_quality_gate({"calibratedScore": 62, "issues": [], "deterministicChecks": []}, validation)
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


def test_same_incomplete_action_is_one_root_cause_across_review_categories():
    merged = deduplicate_issues(
        [{
            "category": "action", "severity": "major", "segmentIds": ["shot"],
            "outputTime": 20.8, "description": "切西瓜动作未完整呈现，操作中途结束",
        }],
        [{
            "category": "content", "severity": "major", "segmentIds": ["shot"],
            "outputTime": 20.8, "description": "缺少动作完成后的结果状态",
        }],
        [{
            "category": "unverified_evidence", "severity": "critical", "segmentIds": ["shot"],
            "description": "动态复核未确认完整边界，动作在操作中途截断",
        }],
    )
    assert len(merged) == 1
    assert merged[0]["severity"] == "critical"
    assert merged[0]["duplicateCount"] == 3
    assert "动作" in merged[0]["description"]


def test_incomplete_action_root_merges_narrative_and_continuity_wording():
    merged = deduplicate_issues(
        [{
            "category": "continuity", "severity": "major", "segmentIds": ["shot"],
            "outputTime": 8.9, "description": "章节动作不完整，操作中途切走",
        }],
        [{
            "category": "narrative", "severity": "major", "segmentIds": ["shot"],
            "outputTime": 8.9, "description": "该动作未完成，缺少结果",
        }],
    )
    assert len(merged) == 1
    assert merged[0]["duplicateCount"] == 2


def test_missing_context_and_incomplete_climax_are_one_root_cause():
    merged = deduplicate_issues(
        [{
            "category": "action", "severity": "critical", "segmentIds": ["climax"],
            "description": "魔术高潮缺少完整动作结果",
        }],
        [{
            "category": "missing_context", "severity": "major",
            "description": "非独立镜头缺少必要上下文",
            "evidence": [{"segmentId": "climax", "requiredCandidateIndex": 3}],
        }],
    )
    assert len(merged) == 1
    assert merged[0]["severity"] == "critical"
    assert merged[0]["duplicateCount"] == 2


def test_same_rendered_cut_is_deduplicated_by_output_time():
    merged = deduplicate_issues(
        [{
            "category": "audiovisual", "severity": "major", "segmentIds": ["a", "b"],
            "outputTime": 14.06, "description": "第1段切到第2段时音量或波形突变",
        }],
        [{
            "category": "audio_cut", "severity": "minor", "outputTime": 14.08,
            "description": "切点 1->2 音量突变",
        }],
    )
    assert len(merged) == 1
    assert merged[0]["duplicateCount"] == 2


def test_v4_gate_does_not_readd_deterministic_issue_to_canonical_list():
    canonical = {
        "category": "audio_cut", "severity": "major", "outputTime": 14.0,
        "description": "切点音量突变", "duplicateCount": 2,
    }
    gate = build_quality_gate({
        "calibratedScore": 80, "calibrationVersion": "composition-calibration-v4-root-cause",
        "issues": [canonical], "deterministicChecks": [{**canonical, "duplicateCount": 1}],
    }, {"passed": True, "issues": []})
    assert gate["issues"][0]["duplicateCount"] == 2


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
