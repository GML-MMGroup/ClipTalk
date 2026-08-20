from __future__ import annotations

from pathlib import Path

import pytest

from app.subtitle_review import (
    load_draft,
    normalize_layout,
    output_fingerprints,
    parse_style_command,
    save_draft,
    validate_cues,
)


def test_output_fingerprint_changes_with_reviewed_timeline() -> None:
    base = [{"segments": [{"start": 1, "end": 4, "playbackRate": 1}]}]
    changed = [{"segments": [{"start": 1, "end": 4.1, "playbackRate": 1}]}]
    assert output_fingerprints(base) != output_fingerprints(changed)
    assert output_fingerprints(base) == output_fingerprints([{"segments": [{"end": 4, "start": 1}]}])


def test_style_command_defaults_global_and_requires_explicit_current_cue() -> None:
    base = normalize_layout(preset="clean")
    global_change = parse_style_command("字号 54px，整体上移 5%", base, cue_id="cue_1", frame_height=1080)
    assert global_change["scope"] == "global"
    assert global_change["style"]["fontSizeRatio"] == pytest.approx(.05)
    assert global_change["style"]["offsetYRatio"] == pytest.approx(-.05)
    cue_change = parse_style_command("当前这条放到左上", base, cue_id="cue_1")
    assert cue_change["scope"] == "cue"
    assert cue_change["cueId"] == "cue_1"
    assert cue_change["style"]["horizontal"] == "left"
    assert cue_change["style"]["vertical"] == "top"


def test_style_command_clamps_size_and_offsets_to_supported_range() -> None:
    result = parse_style_command("字号 500px，向下移动 90%", normalize_layout(), frame_height=1000)
    assert result["style"]["fontSizeRatio"] == .08
    assert result["style"]["offsetYRatio"] == .4


def test_validate_cues_rejects_overlapping_timing() -> None:
    with pytest.raises(ValueError, match="不能重叠"):
        validate_cues([
            {"id": "one", "outputIndex": 0, "start": 0, "end": 2, "text": "一"},
            {"id": "two", "outputIndex": 0, "start": 1.5, "end": 3, "text": "二"},
        ], 1)


def test_draft_persistence_is_scoped_to_work_directory(tmp_path: Path) -> None:
    draft = {"id": "sub_1234567890abcdef", "jobId": "job_1", "revision": 1, "cues": []}
    save_draft(tmp_path, draft)
    assert load_draft(tmp_path, draft["id"]) == draft
    with pytest.raises(ValueError):
        load_draft(tmp_path, "../outside")
