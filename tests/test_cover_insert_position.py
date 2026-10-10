"""A cover still may land at the head, in the middle or at the tail of a timeline."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.edit_sessions import apply_edit_operation, create_or_resume_edit_session


def _fresh(tmp_path: Path) -> tuple[dict, dict]:
    cover = tmp_path / "covers" / "cover.png"
    cover.parent.mkdir(parents=True, exist_ok=True)
    cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    job = {
        "id": "job-1",
        "workflowKind": "highlight",
        "workDirectory": str(tmp_path),
        "videoInfo": {"duration": 90.0},
        "outputVersions": [{
            "id": "version-1",
            "number": 1,
            "outputs": [{
                "filename": "version-1.mp4",
                "subtitleMode": "none",
                "segments": [
                    {"id": "s1", "start": 0.0, "end": 5.0},
                    {"id": "s2", "start": 10.0, "end": 15.0},
                    {"id": "s3", "start": 20.0, "end": 25.0},
                    {"id": "s4", "start": 30.0, "end": 35.0},
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


def _kinds(session: dict) -> list[str]:
    return [str(clip.get("assetKind") or "video") for clip in session["clips"]]


def test_position_mode_end_appends_the_cover(tmp_path: Path) -> None:
    job, session = _fresh(tmp_path)
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 2.0, "positionMode": "end",
    })
    assert session["clips"][-1]["assetKind"] == "image"
    assert _kinds(session).count("image") == 1


def test_position_mode_middle_splits_the_body(tmp_path: Path) -> None:
    job, session = _fresh(tmp_path)
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 2.0, "positionMode": "middle",
    })
    kinds = _kinds(session)
    assert kinds.count("image") == 1
    assert 0 < kinds.index("image") < len(kinds) - 1


def test_position_mode_start_keeps_the_head_default(tmp_path: Path) -> None:
    job, session = _fresh(tmp_path)
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 2.0, "positionMode": "start",
    })
    assert session["clips"][0]["assetKind"] == "image"


def test_unknown_position_mode_falls_back_to_the_head(tmp_path: Path) -> None:
    job, session = _fresh(tmp_path)
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 2.0, "positionMode": "nowhere",
    })
    assert session["clips"][0]["assetKind"] == "image"


def test_explicit_position_beats_position_mode(tmp_path: Path) -> None:
    job, session = _fresh(tmp_path)
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 1.0, "positionMode": "end", "position": 1,
    })
    assert session["clips"][1]["assetKind"] == "image"


def test_middle_insert_grows_duration_without_trimming_the_body(tmp_path: Path) -> None:
    job, session = _fresh(tmp_path)
    before_ranges = [
        (round(float(clip["sourceStart"]), 3), round(float(clip["sourceEnd"]), 3))
        for clip in session["clips"]
    ]
    before_duration = float(session["duration"])
    apply_edit_operation(job, session, revision=0, operation={
        "type": "insert_cover_clip", "duration": 2.0, "positionMode": "middle",
    })
    video_ranges = [
        (round(float(clip["sourceStart"]), 3), round(float(clip["sourceEnd"]), 3))
        for clip in session["clips"] if str(clip.get("assetKind") or "") != "image"
    ]
    # The cover is pure addition: no existing frame range is cut short.
    assert video_ranges == before_ranges
    assert float(session["duration"]) == pytest.approx(before_duration + 2.0, abs=.05)
