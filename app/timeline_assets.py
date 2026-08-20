from __future__ import annotations

import json
import math
import re
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from .asset_scheduler import SingleFlightAssetScheduler
from .media import (
    SampledFrame,
    create_timeline_thumbnail_sprite,
    detect_scene_changes,
    detect_silence_intervals,
    extract_audio_waveform,
    probe_video,
    silence_intervals_from_waveform,
)
from .pipeline import coarse_frame_limit, load_analysis_checkpoint


class TimelineAssetCache:
    """Resolve timeline cache paths and publish metadata atomically."""

    def __init__(self, data_root: Path) -> None:
        self.root = data_root / "cache"

    @staticmethod
    def safe_identity(identity: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "", str(identity))[:96]

    def waveform_path(self, identity: str) -> Path:
        return self.root / f"waveform-{self.safe_identity(identity)}.json"

    def timeline_paths(self, identity: str) -> tuple[Path, Path]:
        safe = self.safe_identity(identity)
        return self.root / f"timeline-{safe}.json", self.root / f"timeline-{safe}.jpg"

    def partial_paths(self, identity: str) -> tuple[Path, Path]:
        safe = self.safe_identity(identity)
        return self.root / f"timeline-{safe}.partial.json", self.root / f"timeline-{safe}.partial.jpg"

    @staticmethod
    def write_metadata(path: Path, metadata: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class TimelineAssetScheduler(SingleFlightAssetScheduler):
    """Single-flight background scheduler with bounded failure cooldown."""


class TimelineAssetService:
    """Generate and serve reusable waveform and timeline review assets."""

    def __init__(
        self, *, data_root: Path, ffmpeg: str, ffprobe: str,
        generation_lock: threading.Lock | threading.RLock,
        waveform_lock: threading.Lock | threading.RLock,
    ) -> None:
        self.cache = TimelineAssetCache(data_root)
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.generation_lock = generation_lock
        self.waveform_lock = waveform_lock

    def prepare(self, job: dict[str, Any]) -> dict[str, Any]:
        source = Path(job["sourcePath"])
        identity = str(job.get("sourceHash") or job["id"])
        work_directory = Path(job["workDirectory"])
        validated_duration = float((job.get("videoInfo") or {}).get("duration") or 0)
        source_truncated = str((job.get("sourceValidation") or {}).get("status") or "") == "truncated"
        metadata_path, sprite_path = self.cache.timeline_paths(identity)
        partial_metadata_path, partial_sprite_path = self.cache.partial_paths(identity)
        with self.generation_lock:
            if metadata_path.is_file() and sprite_path.is_file():
                try:
                    cached = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    cached = {}
                duration_matches = (
                    not source_truncated
                    or abs(float(cached.get("duration") or 0) - validated_duration) < .1
                )
                if duration_matches and (
                    cached.get("schemaVersion") == 3 or cached.get("sceneCutsReady") is True
                ):
                    return cached
                if not duration_matches:
                    cached = {}
            else:
                cached = {}
            info = probe_video(source, self.ffprobe)
            if source_truncated and validated_duration > 0:
                info = replace(info, duration=min(info.duration, validated_duration))
            if not (
                cached.get("schemaVersion") == 4
                and cached.get("sprite") and sprite_path.is_file()
            ):
                checkpoint = load_analysis_checkpoint(work_directory) or {}
                checkpoint_frames = [
                    SampledFrame(path=Path(str(item.get("path") or "")), time=float(item.get("time") or 0))
                    for item in checkpoint.get("frames") or []
                    if isinstance(item, dict) and item.get("path")
                ]
                checkpoint_frames = [frame for frame in checkpoint_frames if frame.path.is_file()]
                if len(checkpoint_frames) < 2:
                    checkpoint_frames = []

                def publish_partial(sprite: dict[str, Any]) -> None:
                    frame_count = len(sprite.get("items") or [])
                    self.cache.write_metadata(partial_metadata_path, {
                        "schemaVersion": 4,
                        "duration": info.duration,
                        "sprite": sprite,
                        "sceneCuts": [],
                        "sceneCutsReady": False,
                        "partial": True,
                        "frameCount": frame_count,
                        "frameTarget": coarse_frame_limit(info.duration),
                    })

                sprite = create_timeline_thumbnail_sprite(
                    source,
                    sprite_path,
                    duration=info.duration,
                    ffmpeg=self.ffmpeg,
                    frame_count=coarse_frame_limit(info.duration),
                    columns=12,
                    partial_output=partial_sprite_path,
                    partial_callback=publish_partial,
                    frames_directory=work_directory / "timeline-frames",
                    preserve_frames=True,
                    sampled_frames=checkpoint_frames or None,
                )
                cached = {
                    "schemaVersion": 4,
                    "duration": info.duration,
                    "sprite": sprite,
                    "sceneCuts": [],
                    "sceneCutsReady": False,
                    "partial": False,
                    "frameCount": len(sprite.get("items") or []),
                    "frameTarget": len(sprite.get("items") or []),
                }
                self.cache.write_metadata(metadata_path, cached)
                partial_metadata_path.unlink(missing_ok=True)
                partial_sprite_path.unlink(missing_ok=True)
            try:
                scene_cuts = detect_scene_changes(source, ffmpeg=self.ffmpeg)
            except Exception:
                scene_cuts = []
            metadata = {
                **cached,
                "sceneCuts": scene_cuts,
                "sceneCutsReady": True,
                "partial": False,
            }
            self.cache.write_metadata(metadata_path, metadata)
            return metadata

    def waveform(self, job: dict[str, Any]) -> dict[str, Any]:
        source = Path(job["sourcePath"])
        if not source.is_file():
            raise FileNotFoundError("源视频不存在")
        identity = str(job.get("sourceHash") or job["id"])
        pipeline_cache = Path(job.get("workDirectory", "")) / "timeline-waveform.json"
        if pipeline_cache.is_file():
            try:
                cached = json.loads(pipeline_cache.read_text(encoding="utf-8"))
                if cached.get("schemaVersion") == 3 and cached.get("duration"):
                    return cached
            except (OSError, ValueError, TypeError):
                pass
        cache_path = self.cache.waveform_path(identity)
        with self.waveform_lock:
            if cache_path.is_file():
                try:
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
                    if cached.get("schemaVersion") == 3:
                        return cached
                except (OSError, ValueError):
                    cache_path.unlink(missing_ok=True)
            info = probe_video(source, self.ffprobe)
            waveform: dict[str, Any] = {
                "schemaVersion": 3,
                "duration": info.duration,
                "hasAudio": info.has_audio,
                "sampleRate": 8000,
                "peaks": [],
                "rms": [],
                "minimums": [],
                "maximums": [],
                "silences": [],
            }
            if info.has_audio:
                waveform_bins = max(4000, min(60000, math.ceil(info.duration * 12)))
                waveform.update(extract_audio_waveform(
                    source, ffmpeg=self.ffmpeg, bins=waveform_bins, sample_rate=1000,
                ))
                waveform["pointsPerSecond"] = round(len(waveform["rms"]) / info.duration, 3)
                waveform["normalizationPeak"] = max(waveform["peaks"], default=0.0)
                waveform["silences"] = silence_intervals_from_waveform(
                    waveform, duration=info.duration,
                )
                if not waveform["silences"] and not waveform.get("rms"):
                    try:
                        waveform["silences"] = detect_silence_intervals(source, ffmpeg=self.ffmpeg)
                    except Exception:
                        waveform["silences"] = []
            self.cache.write_metadata(cache_path, waveform)
            return waveform

    def status(
        self, *, job_id: str, job: dict[str, Any],
        scheduler: TimelineAssetScheduler, retry: bool = False,
    ) -> dict[str, Any]:
        identity = str(job.get("sourceHash") or job_id)
        metadata_path, sprite_path = self.cache.timeline_paths(identity)
        partial_metadata_path, partial_sprite_path = self.cache.partial_paths(identity)
        if metadata_path.is_file() and sprite_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = {}
            if metadata.get("sprite"):
                generating = metadata.get("schemaVersion") == 4 and metadata.get("sceneCutsReady") is not True
                if generating:
                    scheduler.schedule(job_id, identity, force=retry)
                return {
                    **metadata,
                    "ready": True,
                    "generating": generating,
                    "spriteUrl": f"/api/jobs/{job_id}/timeline-sprite?revision={sprite_path.stat().st_mtime_ns}",
                }
        scheduler.schedule(job_id, identity, force=retry)
        generation_error = scheduler.failure(identity)
        if partial_metadata_path.is_file() and partial_sprite_path.is_file():
            try:
                metadata = json.loads(partial_metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = {}
            if metadata.get("sprite"):
                revision = int(metadata.get("frameCount") or partial_sprite_path.stat().st_mtime_ns)
                return {
                    **metadata,
                    "ready": True,
                    "generating": generation_error is None,
                    "generationError": generation_error,
                    "retryable": generation_error is not None,
                    "partial": True,
                    "spriteUrl": f"/api/jobs/{job_id}/timeline-sprite?partial=true&revision={revision}",
                }
        return {
            "ready": False,
            "generating": generation_error is None,
            "generationError": generation_error,
            "retryable": generation_error is not None,
            "retryAfterSeconds": 10 if generation_error else None,
            "duration": float((job.get("videoInfo") or {}).get("duration") or 0),
        }

    def sprite_path(
        self, *, job_id: str, job: dict[str, Any], partial: bool,
        scheduler: TimelineAssetScheduler,
    ) -> Path:
        identity = str(job.get("sourceHash") or job_id)
        _, complete = self.cache.timeline_paths(identity)
        _, partial_path = self.cache.partial_paths(identity)
        selected = partial_path if partial and partial_path.is_file() else complete
        if not selected.is_file():
            scheduler.schedule(job_id, identity)
            raise FileNotFoundError("时间轴缩略图仍在生成")
        return selected
