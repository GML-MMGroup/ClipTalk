from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.composition_assets import (
    CompositionPreviewPaths,
    CompositionPreviewService,
    composition_edl_hash,
    event_group_edl_hash,
    validate_render_selections,
)


def selection() -> dict:
    return {
        "id": "event_1",
        "title": "开场",
        "segments": [{
            "id": "segment_1",
            "start": 1.0,
            "end": 5.0,
            "role": "setup",
            "transitionIn": {"type": "cut", "duration": 0},
        }],
    }


def composition_hash(items: list[dict], *, subtitle_mode: str, subtitle_style: str) -> str:
    return composition_edl_hash(
        items,
        source_hash="source_1",
        output_mode="single_reel",
        subtitle_mode=subtitle_mode,
        subtitle_style=subtitle_style,
        variant_mode="complete",
        variant_label="完整事件版",
    )


def test_event_hash_changes_only_when_rendered_edl_changes() -> None:
    group = selection()
    initial = event_group_edl_hash(group)
    assert event_group_edl_hash({**group, "summary": "未参与渲染的说明"}) == initial
    changed = {**group, "segments": [{**group["segments"][0], "end": 6.0}]}
    assert event_group_edl_hash(changed) != initial


def test_composition_hash_tracks_effective_subtitle_configuration() -> None:
    items = [selection()]
    assert composition_hash(items, subtitle_mode="none", subtitle_style="clean") == composition_hash(
        items, subtitle_mode="none", subtitle_style="cinematic",
    )
    assert composition_hash(items, subtitle_mode="burn", subtitle_style="clean") != composition_hash(
        items, subtitle_mode="burn", subtitle_style="cinematic",
    )


def test_preview_path_sanitizes_group_identity(tmp_path: Path) -> None:
    job = {"workDirectory": str(tmp_path)}
    group = {**selection(), "id": "../../unsafe event"}
    path = CompositionPreviewPaths.event_preview(job, group)
    assert path.parent == tmp_path / "event-previews"
    assert path.name.startswith("unsafeevent-")


def test_render_gate_rejects_empty_or_explicitly_excluded_content() -> None:
    with pytest.raises(RuntimeError, match="没有可生成"):
        validate_render_selections([{"segments": []}], editing_intent={})
    excluded = selection()
    excluded["edlOptimization"] = {
        "qualityReport": {"userIntent": {"excludedMatches": ["广告"]}},
    }
    with pytest.raises(RuntimeError, match="明确要求排除"):
        validate_render_selections([excluded], editing_intent={})


def test_automatic_render_gate_blocks_critical_issue_but_foreground_records_it() -> None:
    report = {
        "issues": [{"severity": "critical", "category": "cross_event_dissolve", "description": "跨事件溶解"}],
    }
    foreground = selection()
    with patch("app.composition_assets.validate_edit_sequence", return_value=report):
        validate_render_selections([foreground], editing_intent={}, automatic=False)
    assert foreground["sequenceValidation"] == report
    with patch("app.composition_assets.validate_edit_sequence", return_value=report):
        with pytest.raises(RuntimeError, match="渲染前质量门"):
            validate_render_selections([selection()], editing_intent={}, automatic=True)


def test_event_preview_generation_is_cached(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    job = {"sourcePath": str(source), "workDirectory": str(tmp_path / "work")}
    group = selection()
    service = CompositionPreviewService(
        ffmpeg="ffmpeg", ffprobe="ffprobe", generation_lock=threading.Lock(),
    )

    def render(_source, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"preview")
        return 4.0

    with (
        patch("app.composition_assets.probe_video", return_value=SimpleNamespace(has_audio=True)),
        patch("app.composition_assets.render_composition", side_effect=render) as render_mock,
    ):
        first = service.prepare_event_preview(job, group)
        source.unlink()
        second = service.prepare_event_preview(job, group)
    assert first == second
    assert first.read_bytes() == b"preview"
    assert render_mock.call_count == 1
    assert render_mock.call_args.kwargs["preview_width"] == 960
