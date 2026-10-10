"""Intro animation for cover stills, and multi-aspect delivery exports."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app import media
from app.edit_sessions import (
    apply_edit_operation,
    build_edit_session_render_plan,
    create_or_resume_edit_session,
)
from app.main import _append_aspect_exports, _normalized_aspect_exports, _output_aspect


def _capture_command(segments: list[dict], tmp_path: Path) -> str:
    captured: list[list[str]] = []

    class _Capture(BaseException):
        pass

    def fake_start(command: list[str], **_kwargs: object) -> None:
        captured.append(list(command))
        raise _Capture()

    source = tmp_path / "source.mp4"
    source.write_bytes(b"")
    original = media.process_supervisor.start
    media.process_supervisor.start = fake_start  # type: ignore[assignment]
    try:
        with pytest.raises(_Capture):
            media.render_composition(
                source, tmp_path / "out" / "render.mp4",
                segments=segments, has_audio=True, ffmpeg="ffmpeg",
                auto_letterbox_crop=False,
            )
    finally:
        media.process_supervisor.start = original  # type: ignore[assignment]
    assert captured, "渲染命令没有被构造"
    return " ".join(captured[0])


def _cover_segment(**overrides: object) -> dict:
    segment = {
        "id": "cover", "start": 0.0, "end": 3.0, "assetKind": "image",
        "assetPath": "/tmp/cover.png", "assetDuration": 3.0,
        "transitionIn": {"type": "cut", "duration": 0},
    }
    segment.update(overrides)
    return segment


def test_a_cover_still_is_fitted_to_the_delivery_canvas(tmp_path: Path) -> None:
    command = _capture_command(
        [_cover_segment(canvasWidth=1920, canvasHeight=1080)],
        tmp_path,
    )
    assert "force_original_aspect_ratio=decrease" in command
    assert "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black" in command


def test_no_animation_keeps_the_still_untouched(tmp_path: Path) -> None:
    command = _capture_command(
        [_cover_segment(canvasWidth=1920, canvasHeight=1080, coverAnimation="none")],
        tmp_path,
    )
    assert ",fade=t=in" not in command
    assert "zoompan" not in command


def test_fade_animation_opens_from_black(tmp_path: Path) -> None:
    command = _capture_command(
        [_cover_segment(canvasWidth=1920, canvasHeight=1080, coverAnimation="fade")],
        tmp_path,
    )
    assert ",fade=t=in:st=0:d=" in command


def test_push_in_animation_needs_a_known_canvas(tmp_path: Path) -> None:
    command = _capture_command(
        [_cover_segment(canvasWidth=1920, canvasHeight=1080, coverAnimation="zoom")],
        tmp_path,
    )
    assert "zoompan=" in command
    assert "s=1920x1080" in command

    # Without a canvas the push-in is skipped instead of guessing a size.
    plain = _capture_command([_cover_segment(coverAnimation="zoom")], tmp_path)
    assert "zoompan" not in plain


def test_unknown_animation_is_ignored(tmp_path: Path) -> None:
    command = _capture_command(
        [_cover_segment(canvasWidth=1920, canvasHeight=1080, coverAnimation="spin")],
        tmp_path,
    )
    assert "zoompan" not in command
    assert ",fade=t=in" not in command


def _cover_job(tmp_path: Path) -> tuple[dict, dict]:
    cover = tmp_path / "covers" / "cover.png"
    cover.parent.mkdir(parents=True, exist_ok=True)
    cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    job = {
        "id": "job-1",
        "workflowKind": "highlight",
        "workDirectory": str(tmp_path),
        "videoInfo": {"duration": 90.0, "width": 1920, "height": 1080},
        "outputVersions": [{
            "id": "version-1",
            "number": 1,
            "outputs": [{
                "filename": "version-1.mp4",
                "segments": [
                    {"id": "s1", "start": 0.0, "end": 5.0},
                    {"id": "s2", "start": 10.0, "end": 15.0},
                ],
            }],
        }],
        "coverVersions": [{"id": "cv1", "artifactFile": "covers/cover.png"}],
        "currentCoverVersionId": "cv1",
    }
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    return job, session


def test_inserted_cover_defaults_to_a_fade(tmp_path: Path) -> None:
    job, session = _cover_job(tmp_path)
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 2.0,
    })
    assert session["clips"][0]["coverAnimation"] == "fade"
    segments, _cutaways = build_edit_session_render_plan(job, session)
    cover = segments[0]
    assert cover["coverAnimation"] == "fade"
    assert cover["canvasWidth"] == 1920
    assert cover["canvasHeight"] == 1080


def test_cover_animation_can_be_requested_and_changed(tmp_path: Path) -> None:
    job, session = _cover_job(tmp_path)
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 2.0, "animation": "zoom",
    })
    assert session["clips"][0]["coverAnimation"] == "zoom"

    clip_id = str(session["clips"][0]["id"])
    apply_edit_operation(job, session, revision=1, operation={
        "type": "update_clip", "clipId": clip_id, "coverAnimation": "none",
    })
    assert session["clips"][0]["coverAnimation"] == "none"


def test_animation_change_is_refused_for_video_clips(tmp_path: Path) -> None:
    job, session = _cover_job(tmp_path)
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 2.0,
    })
    video_clip = next(
        clip for clip in session["clips"]
        if str(clip.get("assetKind") or "") != "image"
    )
    apply_edit_operation(job, session, revision=1, operation={
        "type": "update_clip", "clipId": str(video_clip["id"]), "coverAnimation": "zoom",
    })
    assert "coverAnimation" not in video_clip


def test_aspect_exports_are_normalized_and_deduplicated() -> None:
    assert _normalized_aspect_exports(["9:16", "9:16", "nonsense", "1:1"]) == ["9:16", "1:1"]
    assert _normalized_aspect_exports(None) == []
    assert _output_aspect({"width": 1920, "height": 1080}) == "16:9"
    assert _output_aspect({"width": 1080, "height": 1920}) == "9:16"
    assert _output_aspect({}) == ""


def test_append_aspect_exports_adds_one_file_per_aspect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_root = tmp_path / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "master.mp4").write_bytes(b"master")
    job = {"id": "job-1", "outputDirectory": str(output_root)}
    version = {"id": "v1", "outputs": [{
        "filename": "master.mp4", "width": 1920, "height": 1080, "hasAudio": True,
    }]}

    calls: list[tuple[str, str]] = []

    class _Info:
        width, height, duration, has_audio = 1080, 1920, 42.0, True

    def fake_reframe(source: Path, output: Path, **kwargs: object) -> _Info:
        calls.append((str(source.name), str(output.name)))
        output.write_bytes(b"copy")
        return _Info()

    monkeypatch.setattr(media, "create_social_reframe_preview", fake_reframe)
    created = _append_aspect_exports(job, version, {"renderAspectExports": ["9:16", "16:9"]})

    # 16:9 is already the master's own canvas, so only 9:16 is rendered.
    assert [item["aspect"] for item in created] == ["9:16"]
    assert calls == [("master.mp4", "master-9x16.mp4")]
    assert [item["filename"] for item in version["outputs"]] == ["master.mp4", "master-9x16.mp4"]
    assert version["outputs"][1]["aspectExportOf"] == "master.mp4"
    assert version["outputs"][1]["previewOnly"] is False


def test_append_aspect_exports_is_a_no_op_without_a_master(tmp_path: Path) -> None:
    job = {"id": "job-1", "outputDirectory": str(tmp_path)}
    version = {"id": "v1", "outputs": []}
    assert _append_aspect_exports(job, version, {"renderAspectExports": ["9:16"]}) == []
    assert version["outputs"] == []


def test_original_outputs_survive_an_aspect_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_root = tmp_path / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "master.mp4").write_bytes(b"master")
    job = {"id": "job-1", "outputDirectory": str(output_root)}
    master = {"filename": "master.mp4", "width": 1920, "height": 1080, "hasAudio": True}
    version = {"id": "v1", "outputs": [copy.deepcopy(master)]}

    class _Info:
        width, height, duration, has_audio = 720, 720, 42.0, True

    def fake_reframe(source: Path, output: Path, **kwargs: object) -> _Info:
        output.write_bytes(b"copy")
        return _Info()

    monkeypatch.setattr(media, "create_social_reframe_preview", fake_reframe)
    _append_aspect_exports(job, version, {"renderAspectExports": ["1:1"]})
    assert version["outputs"][0] == master
    assert len(version["outputs"]) == 2
