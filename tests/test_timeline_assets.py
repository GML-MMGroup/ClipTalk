from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.timeline_assets import TimelineAssetCache, TimelineAssetScheduler, TimelineAssetService


def test_timeline_cache_sanitizes_identity_and_writes_atomically(tmp_path: Path) -> None:
    cache = TimelineAssetCache(tmp_path)
    metadata, sprite = cache.timeline_paths("../../unsafe identity")
    partial_metadata, partial_sprite = cache.partial_paths("../../unsafe identity")
    assert metadata.parent == tmp_path / "cache"
    assert metadata.name == "timeline-unsafeidentity.json"
    assert sprite.name == "timeline-unsafeidentity.jpg"
    assert partial_metadata.name == "timeline-unsafeidentity.partial.json"
    assert partial_sprite.name == "timeline-unsafeidentity.partial.jpg"
    cache.write_metadata(metadata, {"schemaVersion": 4, "sprite": {"items": []}})
    assert json.loads(metadata.read_text(encoding="utf-8"))["schemaVersion"] == 4
    assert list(metadata.parent.glob("*.tmp")) == []


def test_scheduler_rejects_duplicate_inflight_generation() -> None:
    started = threading.Event()
    release = threading.Event()

    def prepare(_job_id: str) -> None:
        started.set()
        assert release.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=1) as executor:
        scheduler = TimelineAssetScheduler(executor=executor, prepare=prepare)
        assert scheduler.schedule("job_1", "source_1") is True
        assert started.wait(timeout=2)
        assert scheduler.schedule("job_1", "source_1") is False
        release.set()
    assert scheduler.failure("source_1") is None


class ImmediateExecutor:
    def submit(self, fn):
        future: Future = Future()
        try:
            future.set_result(fn())
        except Exception as error:
            future.set_exception(error)
        return future


def test_scheduler_applies_failure_cooldown_and_force_retry() -> None:
    now = [100.0]
    calls: list[str] = []

    def prepare(job_id: str) -> None:
        calls.append(job_id)
        raise RuntimeError("sprite failed")

    scheduler = TimelineAssetScheduler(
        executor=ImmediateExecutor(), prepare=prepare,
        cooldown_seconds=10, clock=lambda: now[0],
    )
    assert scheduler.schedule("job_1", "source_1") is True
    assert scheduler.failure("source_1") == "sprite failed"
    assert scheduler.schedule("job_1", "source_1") is False
    assert scheduler.schedule("job_1", "source_1", force=True) is True
    assert calls == ["job_1", "job_1"]
    now[0] += 11
    assert scheduler.failure("source_1") is None


def make_service(root: Path) -> TimelineAssetService:
    return TimelineAssetService(
        data_root=root,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        generation_lock=threading.Lock(),
        waveform_lock=threading.Lock(),
    )


def test_generator_publishes_sprite_before_scene_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    work = tmp_path / "work"
    work.mkdir()
    job = {
        "id": "job_1", "sourceHash": "source_1", "sourcePath": str(source),
        "workDirectory": str(work), "videoInfo": {"duration": 20},
        "sourceValidation": {"status": "complete"},
    }

    def create_sprite(_source, output, **kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"jpeg")
        return {"items": [{"time": 0}, {"time": 10}], "columns": kwargs["columns"]}

    with (
        patch("app.timeline_assets.probe_video", return_value=SimpleNamespace(duration=20.0)),
        patch("app.timeline_assets.create_timeline_thumbnail_sprite", side_effect=create_sprite),
        patch("app.timeline_assets.detect_scene_changes", return_value=[4.0, 12.0]),
        patch("app.timeline_assets.load_analysis_checkpoint", return_value=None),
        patch("app.timeline_assets.coarse_frame_limit", return_value=2),
    ):
        metadata = make_service(tmp_path).prepare(job)
    assert metadata["sceneCutsReady"] is True
    assert metadata["sceneCuts"] == [4.0, 12.0]
    persisted, sprite = TimelineAssetCache(tmp_path).timeline_paths("source_1")
    assert sprite.read_bytes() == b"jpeg"
    assert json.loads(persisted.read_text(encoding="utf-8"))["sprite"]["columns"] == 12


def test_waveform_reuses_pipeline_cache_without_decoding(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    work = tmp_path / "work"
    work.mkdir()
    expected = {"schemaVersion": 3, "duration": 8.0, "rms": [0.1]}
    (work / "timeline-waveform.json").write_text(json.dumps(expected), encoding="utf-8")
    job = {
        "id": "job_1", "sourcePath": str(source), "workDirectory": str(work),
    }
    with patch("app.timeline_assets.probe_video") as probe:
        result = make_service(tmp_path).waveform(job)
    assert result == expected
    probe.assert_not_called()
