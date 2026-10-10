from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app import media
from app.edit_sessions import (
    apply_edit_operation,
    build_edit_session_render_plan,
    create_or_resume_edit_session,
    undo_edit_session,
)


def _job(work_directory: str) -> dict:
    return {
        "id": "job-1",
        "workflowKind": "highlight",
        "workDirectory": work_directory,
        "videoInfo": {"duration": 90.0},
        "outputVersions": [{
            "id": "version-1",
            "number": 1,
            "outputs": [{
                "filename": "version-1.mp4",
                "subtitleMode": "none",
                "segments": [
                    {"id": "source-a", "start": 10.0, "end": 18.0, "role": "开场动作"},
                    {"id": "source-b", "start": 30.0, "end": 36.0, "role": "人物反应"},
                ],
            }],
        }],
    }


def _cover_job(tmp_path: Path) -> tuple[dict, Path]:
    """A job whose confirmed cover exists on disk."""
    cover_path = tmp_path / "covers" / "cover-1.png"
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    job = _job(str(tmp_path))
    job["coverVersions"] = [{
        "id": "cover-version-1",
        "artifactFile": "covers/cover-1.png",
        "contentHash": "sha256:test",
    }]
    job["currentCoverVersionId"] = "cover-version-1"
    return job, cover_path


def test_image_asset_is_only_detected_for_image_segments() -> None:
    assert media._image_asset_for_segment({"start": 0.0, "end": 5.0}) is None
    assert media._image_asset_for_segment({"assetKind": "image"}) is None
    assert media._image_asset_for_segment(
        {"assetKind": "image", "assetPath": ""}
    ) is None
    found = media._image_asset_for_segment({
        "assetKind": "image", "assetPath": "/tmp/cover.png", "assetDuration": 3.0,
    })
    assert found == {"path": "/tmp/cover.png", "duration": 3.0}
    # Falls back to the recorded source range when assetDuration is missing.
    assert media._image_asset_for_segment(
        {"assetKind": "image", "assetPath": "/tmp/cover.png", "start": 0.0, "end": 2.5}
    ) == {"path": "/tmp/cover.png", "duration": 2.5}


def test_insert_cover_clip_adds_an_image_clip_at_the_requested_position(tmp_path: Path) -> None:
    job, cover_path = _cover_job(tmp_path)
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    before = len(session["clips"])
    base_duration = float(session["duration"])

    result = apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 3.0, "position": 0,
    })
    clips = result["session"]["clips"]
    assert len(clips) == before + 1
    cover_clip = clips[0]
    assert cover_clip["assetKind"] == "image"
    assert cover_clip["assetPath"] == str(cover_path)
    assert cover_clip["assetDuration"] == 3.0
    assert cover_clip["duration"] == 3.0
    assert cover_clip["sourceStart"] == 0.0
    assert cover_clip["sourceEnd"] == 3.0
    assert cover_clip["muted"] is True
    assert session["duration"] == pytest.approx(base_duration + 3.0, abs=.05)

    # The cover can also land in the middle instead of the head.
    apply_edit_operation(job, session, revision=1, operation={
        "type": "insert_cover_clip", "duration": 1.5, "position": 2,
    })
    assert session["clips"][2]["assetKind"] == "image"
    assert [str(item.get("assetKind") or "video") for item in session["clips"]] == [
        "image", "video", "image", "video",
    ]


def test_insert_cover_clip_is_undoable(tmp_path: Path) -> None:
    job, _cover_path = _cover_job(tmp_path)
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 2.0, "position": 0,
    })
    assert session["clips"][0]["assetKind"] == "image"

    undo_edit_session(session, revision=1)
    assert all(str(item.get("assetKind") or "") != "image" for item in session["clips"])
    assert session["canRedo"] is True


def test_insert_cover_clip_rejects_a_missing_cover(tmp_path: Path) -> None:
    from app.edit_sessions import EditSessionError
    job = _job(str(tmp_path))
    job["coverVersions"] = [{
        "id": "cover-version-1", "artifactFile": "covers/gone.png",
    }]
    job["currentCoverVersionId"] = "cover-version-1"
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    with pytest.raises(EditSessionError):
        apply_edit_operation(job, session, revision=0, operation={
            "type": "insert_cover_clip", "duration": 3.0,
        })


def test_render_plan_carries_the_image_asset_into_segments(tmp_path: Path) -> None:
    job, cover_path = _cover_job(tmp_path)
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 3.0, "position": 0,
    })
    segments, _cutaways = build_edit_session_render_plan(job, session)
    assert segments[0]["assetKind"] == "image"
    assert segments[0]["assetPath"] == str(cover_path)
    assert segments[0]["assetDuration"] == 3.0
    assert all(str(item.get("assetKind") or "video") == "video" for item in segments[1:])


def test_image_segment_renders_from_a_looped_still_with_silent_audio(tmp_path: Path) -> None:
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"")

    captured: list[list[str]] = []

    class _Capture(BaseException):
        pass

    def fake_start(command: list[str], **_kwargs: object) -> None:
        captured.append(list(command))
        raise _Capture()

    segments = [
        {
            "id": "cover", "start": 0.0, "end": 3.0, "assetKind": "image",
            "assetPath": str(cover), "assetDuration": 3.0,
            "transitionIn": {"type": "cut", "duration": 0},
        },
        {
            "id": "body", "start": 10.0, "end": 18.0,
            "transitionIn": {"type": "cut", "duration": 0},
        },
    ]
    original_start = media.process_supervisor.start
    media.process_supervisor.start = fake_start  # type: ignore[assignment]
    try:
        with pytest.raises(_Capture):
            media.render_composition(
                source, tmp_path / "out" / "render.mp4",
                segments=segments, has_audio=True, ffmpeg="ffmpeg",
                auto_letterbox_crop=False,
            )
    finally:
        media.process_supervisor.start = original_start  # type: ignore[assignment]

    assert captured, "渲染命令没有被构造"
    command = captured[0]

    # The still image becomes its own looped input instead of a source-video seek.
    assert "-loop" in command
    loop_at = command.index("-loop")
    assert command[loop_at + 1] == "1"
    assert str(cover) in command
    assert command[command.index(str(cover)) - 1] == "-i"

    # And it carries a silent audio track so the shared audio chain still applies.
    assert any("anullsrc" in str(item) for item in command)

    # A second input still exists for the real video segment.
    assert command.count("-i") >= 3
