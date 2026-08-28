from __future__ import annotations

import json
from pathlib import Path

from tools.validate_workflows import (
    WorkflowClient,
    WorkflowRunner,
    candidate_has_evidence,
    health_issues,
    interval_overlap,
    validate_content,
    validate_handoff,
    validate_highlight,
    validate_outputs,
    validate_person_discovery,
    validate_speaker_discovery,
)
from tools.validate_workflows import main as validate_main


def test_interview_quality_script_requires_private_real_dataset() -> None:
    package = json.loads(
        (Path(__file__).resolve().parents[1] / "package.json").read_text(encoding="utf-8")
    )
    command = package["scripts"]["benchmark:interview-quality"]
    assert "--strict-interview" in command
    assert "--require-input" in command


def runner_for(client, video) -> WorkflowRunner:
    return WorkflowRunner(
        client, video=video, poll_interval=.001, phase_timeout=1, stall_seconds=1,
        max_selected=3, analysis_only=True, force_reanalyze=True,
    )


def test_interval_overlap_only_counts_positive_intersection() -> None:
    assert interval_overlap((1, 3), (2, 4)) == 1
    assert interval_overlap((1, 2), (2, 4)) == 0


def test_highlight_validation_uses_valid_non_overlapping_recommendations() -> None:
    job = {
        "taskMode": "highlight",
        "videoInfo": {"duration": 30},
        "recommendedGroupIds": ["event_1", "event_2"],
        "eventGroups": [
            {"id": "event_1", "segments": [{"id": "shot_1", "start": 1, "end": 5, "duration": 4}]},
            {"id": "event_2", "segments": [{"id": "shot_2", "start": 4, "end": 7, "duration": 3}]},
            {"id": "event_3", "segments": [{"id": "shot_3", "start": 10, "end": 13, "duration": 3}]},
        ],
    }

    selection, metrics, issues = validate_highlight(job, 3)

    assert selection == {
        "groupIds": ["event_1", "event_3"],
        "segmentIds": {"event_1": ["shot_1"], "event_3": ["shot_3"]},
    }
    assert metrics["selectedSegmentCount"] == 2
    assert any(value.code == "highlight.overlapping_groups" for value in issues)


def test_highlight_validation_reports_broken_ranges_and_references() -> None:
    job = {
        "taskMode": "highlight",
        "videoInfo": {"duration": 8},
        "recommendedGroupIds": ["missing", "event_1"],
        "eventGroups": [{"id": "event_1", "segments": [{"id": "shot_1", "start": 7, "end": 10}]}],
    }

    selection, _, issues = validate_highlight(job, 3)

    assert selection is not None
    assert {value.code for value in issues} >= {
        "highlight.invalid_recommendation",
        "range.out_of_source",
    }


def test_highlight_validation_removes_overlaps_inside_one_event() -> None:
    job = {
        "taskMode": "highlight",
        "videoInfo": {"duration": 20},
        "recommendedGroupIds": ["event_1"],
        "eventGroups": [{
            "id": "event_1",
            "segments": [
                {"id": "shot_1", "start": 1, "end": 6},
                {"id": "shot_2", "start": 5, "end": 8},
                {"id": "shot_3", "start": 10, "end": 12},
            ],
        }],
    }

    selection, _, issues = validate_highlight(job, 3)

    assert selection == {
        "groupIds": ["event_1"],
        "segmentIds": {"event_1": ["shot_1", "shot_3"]},
    }
    assert any(value.code == "highlight.overlapping_segments" for value in issues)


def test_content_validation_requires_human_decision_for_pending_candidates() -> None:
    job = {
        "taskMode": "content_extract",
        "videoInfo": {"duration": 30},
        "contentSearch": {
            "id": "search_1",
            "resultMode": "exhaustive",
            "completeness": {"status": "incomplete", "pendingCount": 1},
            "candidates": [{
                "id": "match_1", "start": 2, "end": 4, "duration": 2,
                "reason": "匹配动作", "requiresReview": True,
            }],
        },
    }

    selection, metrics, issues = validate_content(job, 3)

    assert selection is None
    assert metrics["pendingReviewCount"] == 1
    assert any(value.code == "content.human_review_required" for value in issues)


def test_content_clarification_is_not_duplicated_as_no_match_errors() -> None:
    selection, _, issues = validate_content({
        "taskMode": "content_extract",
        "videoInfo": {"duration": 30},
        "contentSearch": {
            "id": "search_1",
            "clarification": {"kind": "person_target", "message": "请选择人物"},
            "candidates": [],
        },
    }, 3)

    assert selection is None
    assert [value.code for value in issues] == ["content.clarification_required"]


def test_content_validation_prefers_reliable_default_selection() -> None:
    job = {
        "taskMode": "content_extract",
        "videoInfo": {"duration": 30},
        "contentSearch": {
            "id": "search_1",
            "defaultSelectedIds": ["match_2", "match_1"],
            "completeness": {"status": "complete", "pendingCount": 0},
            "candidates": [
                {"id": "match_1", "start": 2, "end": 4, "transcriptExcerpt": "目标对白"},
                {"id": "match_2", "start": 8, "end": 10, "matchedModalities": ["visual"]},
                {"id": "match_3", "start": 12, "end": 14, "reason": "不确定", "requiresReview": True},
            ],
        },
    }

    selection, metrics, issues = validate_content(job, 2)

    assert selection == ("search_1", ["match_2", "match_1"])
    assert metrics["evidenceBackedCount"] == 3
    assert not any(value.severity == "error" for value in issues)


def test_content_validation_reports_impossible_coverage_counter() -> None:
    job = {
        "taskMode": "content_extract",
        "videoInfo": {"duration": 30},
        "contentSearch": {
            "id": "search_1",
            "coverage": {"semantic": {"completed": 497, "total": 160, "percent": 100}},
            "completeness": {"status": "complete", "pendingCount": 0},
            "candidates": [{"id": "match_1", "start": 2, "end": 4, "reason": "匹配"}],
        },
    }

    selection, _, issues = validate_content(job, 3)

    assert selection == ("search_1", ["match_1"])
    assert any(value.code == "content.coverage_counter_invalid" for value in issues)


def test_person_discovery_selects_longest_valid_appearance() -> None:
    job = {
        "taskMode": "content_extract", "workflowKind": "person_edit",
        "videoInfo": {"duration": 30},
    }
    selected, metrics, issues = validate_person_discovery(job, {"persons": [
        {"id": "person_1", "confidence": .95, "ranges": [{"start": 1, "end": 3}]},
        {"id": "person_2", "confidence": .8, "ranges": [
            {"start": 5, "end": 9}, {"start": 12, "end": 15},
        ]},
    ]})

    assert selected == "person_2"
    assert metrics["selectedAppearanceSeconds"] == 7
    assert not any(value.severity == "error" for value in issues)


def test_speaker_discovery_prefers_verified_voice_and_reports_mixed_cluster() -> None:
    job = {
        "taskMode": "content_extract", "workflowKind": "speaker_edit",
        "videoInfo": {"duration": 30},
    }
    selected, metrics, issues = validate_speaker_discovery(job, {
        "status": {"status": "ready"},
        "timeline": [{"start": 1, "end": 2}],
        "voices": [
            {
                "speakerRef": "SPEAKER_00", "speechSeconds": 12, "requiresReview": True,
                "representativeSegments": [{"start": 1, "end": 3}],
                "quality": {"suspectedMixed": True},
            },
            {
                "speakerRef": "SPEAKER_01", "speechSeconds": 5, "requiresReview": False,
                "representativeSegments": [{"start": 8, "end": 10}], "quality": {},
            },
        ],
    }, expected_speaker_count=2)

    assert selected == "SPEAKER_01"
    assert metrics["voiceCount"] == 2
    assert any(value.code == "speaker.suspected_mixed_cluster" for value in issues)
    assert not any(value.severity == "error" for value in issues)


def test_speaker_discovery_marks_unverified_automatic_choice() -> None:
    selected, _, issues = validate_speaker_discovery({
        "taskMode": "content_extract", "workflowKind": "speaker_edit",
        "videoInfo": {"duration": 10},
    }, {
        "status": {"status": "ready"},
        "voices": [{
            "speakerRef": "SPEAKER_00", "speechSeconds": 4, "requiresReview": True,
            "representativeSegments": [{"start": 1, "end": 2}], "quality": {},
        }],
    })

    assert selected == "SPEAKER_00"
    assert any(value.code == "speaker.auto_selected_unverified" for value in issues)


def test_ranked_search_partial_source_coverage_is_not_a_false_warning() -> None:
    selection, _, issues = validate_content({
        "taskMode": "content_extract",
        "videoInfo": {"duration": 30},
        "contentSearch": {
            "id": "search_ranked", "resultMode": "top_k",
            "coverageComplete": False, "coverageStatus": "partial",
            "executionPlan": {"warnings": []},
            "completeness": {"status": "not_applicable", "warnings": [], "pendingCount": 0},
            "candidates": [{"id": "match_1", "start": 2, "end": 4, "reason": "可靠视觉证据"}],
        },
    }, 3)

    assert selection == ("search_ranked", ["match_1"])
    assert not any(value.code == "content.coverage_incomplete" for value in issues)


def test_evidence_and_output_contract_checks() -> None:
    assert candidate_has_evidence({"evidenceRefs": [{"id": "speech_1"}]})
    assert candidate_has_evidence({"reason": "画面中出现目标"})
    assert not candidate_has_evidence({"title": "只有标题"})

    outputs, issues = validate_outputs(
        {"status": "completed", "outputs": [{"filename": "result.mp4", "duration": 0}]},
        "highlight",
    )
    assert len(outputs) == 1
    assert {value.code for value in issues} == {"render.invalid_duration", "render.missing_video_url"}


def test_health_issues_distinguish_blockers_and_speech_warning() -> None:
    issues = health_issues({
        "ok": True,
        "ffmpeg": True,
        "ffprobe": False,
        "visionConfigured": False,
        "speechRecognitionConfigured": False,
    })
    severities = {value.code: value.severity for value in issues}
    assert severities["service.ffprobe_missing"] == "error"
    assert severities["service.visionConfigured_missing"] == "error"
    assert severities["service.speech_unavailable"] == "warning"


def test_conversation_handoff_requires_isolated_child_and_history() -> None:
    parent = {
        "id": "content_job", "taskMode": "content_extract", "workflowKind": "content_search",
    }
    child = {
        "id": "highlight_job",
        "taskMode": "highlight",
        "workflowKind": "highlight",
        "handoff": {
            "fromJobId": "content_job",
            "toJobId": "highlight_job",
            "fromTaskMode": "content_extract",
            "toTaskMode": "highlight",
            "fromWorkflowKind": "content_search",
            "toWorkflowKind": "highlight",
        },
        "messages": [{"text": "旧对话", "inherited": True}],
    }
    assert validate_handoff(
        parent, child, "job-handoff", from_mode="content_search", to_mode="highlight",
    ) == []

    child["contentSearch"] = {"id": "leaked"}
    codes = {value.code for value in validate_handoff(
        parent, child, "job-handoff", from_mode="content_search", to_mode="highlight",
    )}
    assert "conversation.content_state_leaked" in codes


def test_handoff_distinguishes_content_person_and_speaker_workflows() -> None:
    parent = {
        "id": "root", "taskMode": "content_extract", "workflowKind": "content_search",
    }
    child = {
        "id": "speaker", "taskMode": "content_extract", "workflowKind": "speaker_edit",
        "handoff": {
            "fromJobId": "root", "toJobId": "speaker",
            "fromTaskMode": "content_extract", "toTaskMode": "content_extract",
            "fromWorkflowKind": "content_search", "toWorkflowKind": "speaker_edit",
        },
        "messages": [{"text": "旧对话", "inherited": True}],
    }

    assert validate_handoff(
        parent, child, "job-handoff", from_mode="content_search", to_mode="speaker_edit",
    ) == []


def test_person_runner_discovers_selects_then_validates_content(tmp_path) -> None:
    class PersonClient:
        def __init__(self) -> None:
            self.calls = []
            self.job = {
                "id": "person_job", "taskMode": "content_extract", "workflowKind": "person_edit",
                "status": "awaiting_content_confirmation", "stage": "person_discovery_ready",
                "videoInfo": {"duration": 20},
            }

        def create_job(self, *_args):
            self.calls.append("create")
            return {"job": dict(self.job)}

        def get_job(self, _job_id):
            return dict(self.job)

        def list_persons(self, _job_id):
            self.calls.append("list_persons")
            return {"persons": [{
                "id": "person_1", "confidence": .9,
                "ranges": [{"start": 2, "end": 8}],
            }]}

        def select_person(self, _job_id, person_id):
            self.calls.append(("select_person", person_id))
            self.job["contentSearch"] = {
                "id": "search_person", "completeness": {"status": "complete", "pendingCount": 0},
                "candidates": [{"id": "match_1", "start": 2, "end": 8, "reason": "人物出镜"}],
            }
            return {"job": dict(self.job)}

    client = PersonClient()
    result = runner_for(client, tmp_path / "video.mp4").run_flow(
        "person_edit", "提取所选人物",
    )

    assert result["passed"]
    assert result["selection"]["personIds"] == ["person_1"]
    assert client.calls == ["create", "list_persons", ("select_person", "person_1")]


def test_speaker_runner_starts_discovery_before_selecting_voice(tmp_path) -> None:
    class SpeakerClient:
        def __init__(self) -> None:
            self.calls = []
            self.job = {
                "id": "speaker_job", "taskMode": "content_extract", "workflowKind": "speaker_edit",
                "status": "awaiting_content_confirmation", "stage": "voice_discovery_ready",
                "videoInfo": {"duration": 20},
            }

        def create_job(self, *_args):
            self.calls.append("create")
            return {"job": dict(self.job)}

        def discover_voices(self, _job_id, expected):
            self.calls.append(("discover_voices", expected))
            return {"accepted": True, "job": dict(self.job)}

        def get_job(self, _job_id):
            return dict(self.job)

        def list_voices(self, _job_id):
            self.calls.append("list_voices")
            return {
                "status": {"status": "ready"}, "timeline": [{"start": 1, "end": 4}],
                "voices": [{
                    "speakerRef": "SPEAKER_00", "speechSeconds": 3,
                    "requiresReview": False,
                    "representativeSegments": [{"start": 1, "end": 4}], "quality": {},
                }],
            }

        def select_speaker(self, _job_id, speaker_ref, query):
            self.calls.append(("select_speaker", speaker_ref, query))
            self.job["contentSearch"] = {
                "id": "search_speaker", "completeness": {"status": "complete", "pendingCount": 0},
                "candidates": [{"id": "match_1", "start": 1, "end": 4, "transcriptExcerpt": "你好"}],
            }
            return {"job": dict(self.job)}

    client = SpeakerClient()
    result = runner_for(client, tmp_path / "video.mp4").run_flow(
        "speaker_edit", "识别说话人", expected_speaker_count=1, speaker_query="你好",
    )

    assert result["passed"]
    assert result["selection"]["speakerRef"] == "SPEAKER_00"
    assert client.calls == [
        "create", ("discover_voices", 1), "list_voices",
        ("select_speaker", "SPEAKER_00", "你好"),
    ]


def test_analysis_only_disables_same_source_highlight_composition() -> None:
    client = WorkflowClient("http://127.0.0.1:1", "", 1)
    captured = {}

    def request_json(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"job": {}}

    client.request_json = request_json
    try:
        client.create_same_source_task(
            "parent", "highlight", "生成高光", 0, analysis_only=True,
        )
    finally:
        client.close()

    assert captured["json"]["autoCompose"] is False


def test_interrupted_validation_writes_a_failed_report(tmp_path, monkeypatch) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "report.json"

    def interrupt(_client):
        raise KeyboardInterrupt

    monkeypatch.setattr(WorkflowClient, "health", interrupt)
    exit_code = validate_main([
        "--video", str(video), "--output", str(output),
        "--base-url", "http://127.0.0.1:1",
    ])
    report = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 130
    assert report["passed"] is False
    assert report["summary"]["errors"] == 1
    assert report["preflightIssues"][0]["code"] == "run.interrupted"
