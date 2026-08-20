from __future__ import annotations

import math
import re
import threading
from pathlib import Path
from typing import Any

from .asset_scheduler import SingleFlightAssetScheduler
from .media import create_preview_proxy, create_webm_preview, probe_video


class PreviewAssetPaths:
    """Resolve source, output, and browser preview cache paths."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root

    @staticmethod
    def source_identity(job: dict[str, Any]) -> str:
        identity = str(job.get("sourceHash") or job.get("id") or "source")
        validation = job.get("sourceValidation")
        validation = validation if isinstance(validation, dict) else {}
        if validation.get("status") == "truncated":
            effective = float(
                validation.get("effectiveDuration")
                or (job.get("videoInfo") or {}).get("duration")
                or 0
            )
            if math.isfinite(effective) and effective > 0:
                identity += f"-effective-{round(effective * 1000)}"
        return identity

    @staticmethod
    def safe_identity(identity: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "", str(identity))[:96] or "source"

    def source_proxy(self, identity: str) -> Path:
        return self.data_root / "cache" / f"proxy-{self.safe_identity(identity)}.mp4"

    @staticmethod
    def output_preview(job: dict[str, Any], filename: str) -> Path:
        return Path(job["workDirectory"]) / "output-previews" / Path(filename).name

    @staticmethod
    def browser_preview(job: dict[str, Any], filename: str | None = None) -> Path:
        name = f"{Path(filename).stem}.webm" if filename else "source.webm"
        return Path(job["workDirectory"]) / "browser-previews" / name


class PreviewProxyScheduler(SingleFlightAssetScheduler):
    """Run source proxy generation once per source with failure cooldown."""

    default_cooldown_seconds = 60.0


class PreviewAssetService:
    """Generate reusable MP4 and WebM review assets."""

    def __init__(
        self,
        *,
        data_root: Path,
        ffmpeg: str,
        ffprobe: str,
        source_lock: threading.Lock | threading.RLock,
        output_lock: threading.Lock | threading.RLock,
        browser_lock: threading.Lock | threading.RLock,
    ) -> None:
        self.paths = PreviewAssetPaths(data_root)
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.source_lock = source_lock
        self.output_lock = output_lock
        self.browser_lock = browser_lock

    def prepare_source(self, job: dict[str, Any]) -> Path:
        source = Path(job["sourcePath"])
        if not source.is_file():
            raise FileNotFoundError("源视频不存在")
        identity = self.paths.source_identity(job)
        output = self.paths.source_proxy(identity)
        if output.is_file():
            return output
        with self.source_lock:
            if output.is_file():
                return output
            info = probe_video(source, self.ffprobe)
            effective_duration = float((job.get("videoInfo") or {}).get("duration") or 0)
            validation = job.get("sourceValidation")
            truncated = (
                isinstance(validation, dict)
                and str(validation.get("status") or "") == "truncated"
                and math.isfinite(effective_duration)
                and effective_duration > 0
            )
            sizing_duration = effective_duration if truncated else info.duration
            maximum_dimension = 1280 if sizing_duration <= 1800 else 960 if sizing_duration <= 3600 else 720
            create_preview_proxy(
                source,
                output,
                has_audio=info.has_audio,
                ffmpeg=self.ffmpeg,
                maximum_dimension=maximum_dimension,
                maximum_duration=effective_duration if truncated else None,
            )
        return output

    def prepare_output(self, job: dict[str, Any], filename: str) -> Path:
        filename = Path(filename).name
        source = Path(job["outputDirectory"]) / filename
        output = self.paths.output_preview(job, filename)
        if output.is_file():
            return output
        if not source.is_file():
            raise FileNotFoundError("输出文件不存在")
        with self.output_lock:
            if output.is_file():
                return output
            info = probe_video(source, self.ffprobe)
            create_preview_proxy(source, output, has_audio=info.has_audio, ffmpeg=self.ffmpeg)
        return output

    def prepare_browser(self, job: dict[str, Any], filename: str | None = None) -> Path:
        filename = Path(filename).name if filename else None
        source = Path(job["outputDirectory"]) / filename if filename else Path(job["sourcePath"])
        output = self.paths.browser_preview(job, filename)
        if output.is_file():
            return output
        if not source.is_file():
            raise FileNotFoundError("预览源文件不存在")
        with self.browser_lock:
            if output.is_file():
                return output
            info = probe_video(source, self.ffprobe)
            maximum_dimension = 960 if info.duration <= 1800 else 720
            create_webm_preview(
                source,
                output,
                has_audio=info.has_audio,
                ffmpeg=self.ffmpeg,
                maximum_dimension=maximum_dimension,
            )
        return output
