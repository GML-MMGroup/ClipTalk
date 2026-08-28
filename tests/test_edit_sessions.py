from __future__ import annotations

import copy

import pytest

from app.edit_sessions import (
    EditSessionError,
    apply_edit_operation,
    apply_edit_proposal,
    build_edit_proposal,
    build_edit_session_render_plan,
    create_or_resume_content_edit_session,
    create_or_resume_edit_session,
    edit_session_preflight,
    public_edit_session,
    redo_edit_session,
    undo_edit_session,
)


def _job() -> dict:
    return {
        "id": "job-1",
        "workflowKind": "highlight",
        "videoInfo": {"duration": 90.0},
        "outputVersions": [{
            "id": "version-1",
            "number": 1,
            "outputs": [{
                "filename": "version-1.mp4",
                "subtitleMode": "none",
                "segments": [
                    {
                        "id": "source-a",
                        "start": 10.0,
                        "end": 18.0,
                        "role": "开场动作",
                        "reason": "动作完整",
                        "evidence": ["动作开始和结束均可见"],
                    },
                    {
                        "id": "source-b",
                        "start": 30.0,
                        "end": 36.0,
                        "role": "人物反应",
                        "transitionIn": {"type": "dissolve", "duration": 0.35},
                    },
                ],
                "cutaways": [{"id": "cutaway-1", "start": 31.0, "end": 32.0}],
            }],
        }],
        "candidates": [{"index": 0, "start": 45.0, "end": 49.0, "role": "补充镜头"}],
    }


def test_edit_session_branches_without_mutating_parent_and_supports_history() -> None:
    job = _job()
    original_version = copy.deepcopy(job["outputVersions"][0])

    session, created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )

    assert created is True
    assert session["baseVersionId"] == "version-1"
    assert session["clipCount"] == 2
    assert session["duration"] == pytest.approx(13.65)
    first_clip_id = session["clips"][0]["id"]

    result = apply_edit_operation(job, session, revision=0, operation={
        "type": "trim_clip",
        "clipId": first_clip_id,
        "sourceStart": 11.0,
        "sourceEnd": 17.0,
    })
    assert result["session"]["revision"] == 1
    assert result["session"]["clips"][0]["sourceStart"] == 11.0
    assert job["outputVersions"][0] == original_version

    undo_edit_session(session, revision=1)
    assert session["revision"] == 2
    assert session["clips"][0]["sourceStart"] == 10.0
    assert session["canRedo"] is True

    redo_edit_session(session, revision=2)
    assert session["revision"] == 3
    assert session["clips"][0]["sourceStart"] == 11.0
    assert session["canUndo"] is True

    public = public_edit_session(session)
    assert "undo" not in public
    assert "redo" not in public


def test_edit_session_operations_build_exact_render_edl() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    first_clip_id = session["clips"][0]["id"]

    apply_edit_operation(job, session, revision=0, operation={
        "type": "split_clip", "clipId": first_clip_id, "sourceTime": 14.0,
    })
    split_clip_id = session["clips"][1]["id"]
    apply_edit_operation(job, session, revision=1, operation={
        "type": "update_clip",
        "clipId": split_clip_id,
        "playbackRate": 1.25,
        "transitionType": "fade_black",
        "audioBridgeType": "j_cut",
    })
    apply_edit_operation(job, session, revision=2, operation={
        "type": "insert_clip",
        "sourceStart": 45.0,
        "sourceEnd": 49.0,
        "title": "补充镜头",
        "sourceRef": {"kind": "candidate", "id": "0"},
        "targetIndex": 1,
    })

    segments, cutaways = build_edit_session_render_plan(job, session)

    assert [(item["start"], item["end"]) for item in segments] == [
        (10.0, 14.0), (45.0, 49.0), (14.0, 18.0), (30.0, 36.0),
    ]
    assert segments[2]["playbackRate"] == 1.25
    assert segments[2]["transitionIn"]["type"] == "fade_black"
    assert segments[2]["audioBridge"]["type"] == "j_cut"
    assert segments[1]["role"] == "补充镜头"
    assert cutaways == [{"id": "cutaway-1", "start": 31.0, "end": 32.0}]


def test_content_search_results_can_start_editing_before_first_render() -> None:
    job = {
        "id": "content-job",
        "workflowKind": "content_search",
        "videoInfo": {"duration": 60.0},
        "contentSearch": {
            "id": "search-1",
            "candidates": [
                {"id": "match-b", "title": "第二段", "start": 20.0, "end": 25.0, "reason": "画面匹配"},
                {"id": "match-a", "title": "第一段", "start": 5.0, "end": 9.0, "reason": "对白匹配"},
            ],
        },
        "outputVersions": [],
    }

    session, created = create_or_resume_content_edit_session(
        job,
        search_id="search-1",
        selected_match_ids=["match-b", "match-a"],
        order_mode="source",
    )

    assert created is True
    assert session["title"] == "内容探索精剪"
    assert session["baseVersionId"] == ""
    assert [clip["title"] for clip in session["clips"]] == ["第一段", "第二段"]
    assert [clip["sourceRef"] for clip in session["clips"]] == [
        {"kind": "content_match", "id": "match-a"},
        {"kind": "content_match", "id": "match-b"},
    ]

    inserted = apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_clip",
        "sourceStart": 30.0,
        "sourceEnd": 33.0,
        "title": "手动补充",
        "sourceRef": {"kind": "manual_range", "id": "manual-1"},
        "targetIndex": 1,
    })["session"]
    inserted_clip_id = inserted["clips"][1]["id"]
    apply_edit_operation(job, session, revision=1, operation={
        "type": "trim_clip",
        "clipId": inserted_clip_id,
        "sourceStart": 30.5,
        "sourceEnd": 32.5,
    })

    segments, cutaways = build_edit_session_render_plan(job, session)
    assert [(item["start"], item["end"]) for item in segments] == [
        (5.0, 9.0), (30.5, 32.5), (20.0, 25.0),
    ]
    assert cutaways == []


def test_edit_proposal_is_previewed_then_applied_as_one_undo_step() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    selected_id = session["clips"][0]["id"]

    proposal = build_edit_proposal(
        job, session, text="把所选片段改成 1.25 倍速", selected_clip_ids=[selected_id],
    )

    assert proposal["title"] == "快捷编辑提案"
    assert proposal["preview"]["operationCount"] == 1
    assert proposal["preview"]["durationAfter"] < proposal["preview"]["durationBefore"]
    assert session["revision"] == 0
    assert session["clips"][0]["playbackRate"] == 1.0

    result = apply_edit_proposal(job, session, proposal["id"])
    assert result["session"]["revision"] == 1
    assert result["session"]["clips"][0]["playbackRate"] == 1.25
    assert result["session"]["pendingProposal"] is None

    undo_edit_session(session, revision=1)
    assert session["clips"][0]["playbackRate"] == 1.0


def test_v2_structured_model_proposal_uses_allowlisted_operations_only() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    clip_id = session["clips"][0]["id"]
    proposal = build_edit_proposal(
        job, session, text="把开场切短并加标记", selected_clip_ids=[clip_id],
        model_result={
            "title": "收紧开场", "summary": "裁短并标记重点",
            "operations": [
                {"type": "trim_clip", "clipId": clip_id, "sourceStart": 11, "sourceEnd": 17},
                {"type": "add_marker", "clipId": clip_id, "sourceTime": 13, "label": "重点"},
                {"type": "run_shell", "command": "ignored"},
            ],
        },
    )
    assert proposal["planner"] == "llm_structured_v2"
    assert [item["type"] for item in proposal["operations"]] == ["trim_clip", "add_marker"]
    assert proposal["preview"]["operationCount"] == 2


def test_semantic_preflight_warns_for_speech_cut_duplicate_and_audio_jump() -> None:
    job = _job()
    job["speechAnalysis"] = {"segments": [{"start": 10, "end": 13, "text": "一句完整的话"}]}
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    duplicate = copy.deepcopy(session["clips"][0])
    duplicate["id"] = "duplicate"
    duplicate["sourceStart"] = 11
    duplicate["sourceEnd"] = 17
    session["clips"].append(duplicate)
    report = edit_session_preflight(session, job)
    codes = {item["code"] for item in report["issues"]}
    assert "speech_truncation" in codes
    assert "duplicate_source" in codes
    assert "audio_jump" in codes
    assert report["ready"] is True

def test_edit_proposal_combines_speed_transition_and_timeline_order() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    selected_id = session["clips"][1]["id"]
    original_order = [clip["id"] for clip in session["clips"]]

    proposal = build_edit_proposal(
        job,
        session,
        text="把所选片段改成 1.25 倍速并使用叠化，再将整条时间线倒序",
        selected_clip_ids=[selected_id],
    )

    assert [operation["type"] for operation in proposal["operations"]] == [
        "update_clip", "update_clip", "reorder_clips",
    ]
    assert proposal["preview"]["operationCount"] == 3
    assert session["revision"] == 0

    result = apply_edit_proposal(job, session, proposal["id"])
    edited = next(clip for clip in result["session"]["clips"] if clip["id"] == selected_id)
    assert edited["playbackRate"] == 1.25
    assert edited["transitionIn"]["type"] == "dissolve"
    assert [clip["id"] for clip in result["session"]["clips"]] == list(reversed(original_order))


def test_edit_proposal_reorders_only_remaining_clips_after_delete() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    selected_id = session["clips"][0]["id"]
    remaining_id = session["clips"][1]["id"]

    proposal = build_edit_proposal(
        job,
        session,
        text="删除所选片段并将剩余镜头倒序",
        selected_clip_ids=[selected_id],
    )

    assert proposal["operations"] == [
        {"type": "delete_clips", "clipIds": [selected_id]},
        {"type": "reorder_clips", "clipIds": [remaining_id]},
    ]
    assert proposal["preview"]["clipCountAfter"] == 1

    result = apply_edit_proposal(job, session, proposal["id"])
    assert [clip["id"] for clip in result["session"]["clips"]] == [remaining_id]


def test_edit_proposal_rejects_unsupported_speed_instead_of_silently_defaulting() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )

    with pytest.raises(EditSessionError, match="仅支持 0.5、0.75、1、1.1、1.25、1.5 或 2"):
        build_edit_proposal(
            job,
            session,
            text="把所选片段改成 3 倍速",
            selected_clip_ids=[session["clips"][0]["id"]],
        )


def test_secondary_editor_core_operations_are_atomic_and_invalidate_preview() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    first_id = session["clips"][0]["id"]
    session.update({"previewStatus": "ready", "previewFingerprint": "old-preview"})

    result = apply_edit_operation(job, session, revision=0, operation={
        "type": "update_clips", "clipIds": [first_id], "playbackRate": .75,
        "transitionType": "dissolve", "transitionDuration": .2,
        "audioGain": 1.4, "muted": False, "audioFadeIn": .12, "audioFadeOut": .18,
    })
    clip = result["session"]["clips"][0]
    assert clip["playbackRate"] == .75
    assert clip["transitionIn"] == {"type": "dissolve", "duration": .2}
    assert clip["audioGain"] == 1.4
    assert clip["audioFadeIn"] == .12
    assert clip["audioFadeOut"] == .18
    assert result["session"]["previewStatus"] == "stale"

    result = apply_edit_operation(job, session, revision=1, operation={
        "type": "add_marker", "clipId": first_id, "sourceTime": 12.0, "label": "重点",
    })
    assert result["session"]["markers"][0]["label"] == "重点"

    result = apply_edit_operation(job, session, revision=2, operation={
        "type": "duplicate_clips", "clipIds": [first_id],
    })
    assert result["session"]["clipCount"] == 3
    assert result["session"]["clips"][1]["title"].endswith("（副本）")

    undo_edit_session(session, revision=3)
    assert session["clipCount"] == 2


def test_trim_to_playhead_removes_markers_from_trimmed_region() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    clip_id = session["clips"][0]["id"]
    apply_edit_operation(job, session, revision=0, operation={
        "type": "add_marker", "clipId": clip_id, "sourceTime": 11.0,
    })
    apply_edit_operation(job, session, revision=1, operation={
        "type": "trim_to_playhead", "clipId": clip_id, "sourceTime": 13.0, "side": "left",
    })
    assert session["clips"][0]["sourceStart"] == 13.0
    assert session["markers"] == []


def test_roll_trim_keeps_following_timeline_position_stable() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    first, second = session["clips"]
    original_duration = session["duration"]
    original_first_end = first["sourceEnd"]
    original_second_start = second["sourceStart"]
    result = apply_edit_operation(job, session, revision=0, operation={
        "type": "roll_trim",
        "clipId": first["id"],
        "boundary": "end",
        "sourceStart": first["sourceStart"],
        "sourceEnd": original_first_end - 1,
        "adjacentClipId": second["id"],
        "adjacentSourceStart": original_second_start - 1,
        "adjacentSourceEnd": second["sourceEnd"],
    })
    assert result["session"]["clips"][0]["sourceEnd"] == original_first_end - 1
    assert result["session"]["clips"][1]["sourceStart"] == original_second_start - 1
    assert result["session"]["duration"] == pytest.approx(original_duration)


def test_edit_session_rejects_stale_revision_and_invalid_source_range() -> None:
    job = _job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    clip_id = session["clips"][0]["id"]
    apply_edit_operation(job, session, revision=0, operation={
        "type": "update_clip", "clipId": clip_id, "playbackRate": 1.1,
    })

    with pytest.raises(EditSessionError, match="其他位置"):
        apply_edit_operation(job, session, revision=0, operation={
            "type": "delete_clips", "clipIds": [clip_id],
        })
    with pytest.raises(EditSessionError, match="源视频内"):
        apply_edit_operation(job, session, revision=1, operation={
            "type": "insert_clip", "sourceStart": 89.9, "sourceEnd": 91.0,
        })
