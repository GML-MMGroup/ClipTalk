from __future__ import annotations

import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from .process_supervisor import process_supervisor

from .editing_techniques import (
    composition_effective_duration,
    composition_schedule,
    normalize_audio_bridge,
    normalize_playback_rate,
    normalize_transition,
    source_pieces,
    source_duration_meets_minimum,
)


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    width: int
    height: int
    has_audio: bool
    video_duration: float = 0.0
    audio_duration: float = 0.0
    container_duration: float = 0.0
    frame_rate: float = 0.0


@dataclass(frozen=True)
class SampledFrame:
    path: Path
    time: float


CONTENT_RENDER_FPS = 30.0
CONTENT_BOUNDARY_EPSILON = min(1.0 / CONTENT_RENDER_FPS / 4.0, 0.008)


def exclusive_render_duration(duration: float, *, strict: bool = False) -> float:
    """Return a duration whose final frame stays inside a right-open range."""
    value = max(0.0, float(duration or 0.0))
    if not strict:
        return value
    return max(0.001, value - CONTENT_BOUNDARY_EPSILON)


_uniform_frame_locks_guard = threading.Lock()
_uniform_frame_locks: dict[str, threading.Lock] = {}


def _uniform_frame_lock(directory: Path) -> threading.Lock:
    key = str(directory.resolve())
    with _uniform_frame_locks_guard:
        return _uniform_frame_locks.setdefault(key, threading.Lock())


SUBTITLE_STYLES: dict[str, dict[str, str | int]] = {
    "clean": {
        "fontcolor": "white",
        "fontsize": 20,
        "borderw": 2,
        "bordercolor": "black@0.65",
        "x": "(w-text_w)/2",
        "y": "h-text_h-38",
    },
    "bold": {
        "fontcolor": "0xFFE66D",
        "fontsize": 24,
        "borderw": 3,
        "bordercolor": "black@0.78",
        "x": "(w-text_w)/2",
        "y": "h-text_h-48",
    },
    "social": {
        "fontcolor": "white",
        "fontsize": 28,
        "borderw": 1,
        "bordercolor": "black@0.9",
        "box": 1,
        "boxcolor": "black@0.55",
        "boxborderw": 12,
        "x": "(w-text_w)/2",
        "y": "h-text_h-72",
    },
}


def subtitle_font_pixels(frame_width: float, frame_height: float, size_ratio: float) -> float:
    """Resolve subtitle size against the short edge for orientation-safe typography."""
    width = max(1.0, float(frame_width or 0))
    height = max(1.0, float(frame_height or 0))
    ratio = max(.012, min(.080, float(size_ratio or .040)))
    return min(width, height) * ratio


def _subtitle_character_units(character: str) -> float:
    if character.isspace():
        return .35
    return 1.0 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else .56


def wrap_subtitle_text(value: str, maximum_units: float) -> str:
    """Wrap drawtext input to the same 90% safe width used by the browser preview."""
    limit = max(6.0, float(maximum_units or 0))
    lines: list[str] = []
    for paragraph in str(value or "").replace("\r", "").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current: list[str] = []
        units = 0.0
        for character in paragraph:
            character_units = _subtitle_character_units(character)
            if current and units + character_units > limit:
                lines.append("".join(current).rstrip())
                current = []
                units = 0.0
            current.append(character)
            units += character_units
        if current:
            lines.append("".join(current).rstrip())
    return "\n".join(lines)


def normalize_subtitle_style(value: str | None) -> str:
    style = str(value or "clean").strip().lower()
    return style if style in SUBTITLE_STYLES else "clean"


def _run(command: list[str], *, timeout: float = 600.0) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MediaError(f"媒体命令无法执行：{error}") from error
    if result.returncode != 0:
        raise MediaError((result.stderr or result.stdout or "媒体命令执行失败")[-2000:])
    return result


def probe_video(path: Path, ffprobe: str) -> VideoInfo:
    result = _run([
        ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
    ], timeout=60)
    try:
        def parsed_duration(value: Any) -> float:
            try:
                number = float(value or 0)
            except (TypeError, ValueError):
                return 0.0
            return number if math.isfinite(number) and number > 0 else 0.0

        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        video = next(item for item in streams if item.get("codec_type") == "video")
        container_duration = parsed_duration(data.get("format", {}).get("duration"))
        video_duration = parsed_duration(video.get("duration"))
        audio_durations = [
            parsed_duration(item.get("duration"))
            for item in streams if item.get("codec_type") == "audio"
        ]
        audio_duration = max(audio_durations, default=0.0)
        # Editing and visual coverage must use the video stream's own length.
        # Container duration is often inherited from a slightly longer audio
        # track or an MP4 edit list and is not proof that visual frames exist.
        duration = video_duration if math.isfinite(video_duration) and video_duration > 0 else container_duration

        def parsed_frame_rate(value: Any) -> float:
            text = str(value or "").strip()
            try:
                if "/" in text:
                    numerator, denominator = text.split("/", 1)
                    rate = float(numerator) / float(denominator)
                else:
                    rate = float(text)
            except (TypeError, ValueError, ZeroDivisionError):
                return 0.0
            return rate if math.isfinite(rate) and 1.0 <= rate <= 240.0 else 0.0

        frame_rate = parsed_frame_rate(video.get("avg_frame_rate")) or parsed_frame_rate(video.get("r_frame_rate"))
    except (ValueError, TypeError, StopIteration, json.JSONDecodeError) as error:
        raise MediaError("无法读取有效的视频流和时长") from error
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError("视频时长无效")
    return VideoInfo(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        has_audio=any(item.get("codec_type") == "audio" for item in streams),
        video_duration=video_duration if math.isfinite(video_duration) else 0.0,
        audio_duration=audio_duration if math.isfinite(audio_duration) else 0.0,
        container_duration=container_duration if math.isfinite(container_duration) else duration,
        frame_rate=frame_rate,
    )


def _clock_text(seconds: float) -> str:
    total = max(0, round(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def validate_video_decodable_coverage(
    path: Path,
    *,
    duration: float,
    ffmpeg: str,
    container_duration: float | None = None,
) -> dict[str, Any]:
    """Validate tail coverage using several points instead of one hard probe.

    MP4 metadata can remain readable after a file has been truncated. ffprobe
    then reports the original duration even though later packets do not exist.
    A single seek can fail on long GOPs, VFR media and MP4 edit lists.  The
    validator therefore walks backwards through a bounded tail window.  A
    deeper successful probe becomes a warning.  If the whole tail window is
    unreadable while the beginning still decodes, the file is rejected instead
    of silently shortening the timeline: a shortened timeline makes a partial
    upload look like a valid short recording.
    """
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError("视频时长无效")
    if duration < 60:
        margins = [max(.15, duration * .02), max(.5, duration * .08), max(1.0, duration * .2)]
    else:
        hard_window = min(180.0, max(60.0, duration * .01))
        margins = [2.0, 10.0, 30.0, hard_window]
    probe_points: list[float] = []
    for margin in margins:
        second = round(max(0.0, duration - min(margin, duration * .8)), 3)
        if not probe_points or abs(second - probe_points[-1]) > .05:
            probe_points.append(second)
    attempts: list[dict[str, Any]] = []

    def decode_probe(probe_at: float) -> bool:
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-ss", f"{probe_at:.3f}", "-i", str(path),
            "-map", "0:v:0", "-frames:v", "1", "-an", "-sn", "-dn",
            "-f", "framehash", "-",
        ]
        try:
            result = subprocess.run(
                command, text=True, capture_output=True, timeout=45, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            attempts.append({"time": probe_at, "decoded": False, "error": str(error)[:300]})
            return False
        decoded = result.returncode == 0 and any(
            line.strip() and not line.lstrip().startswith("#")
            for line in (result.stdout or "").splitlines()
        )
        attempts.append({"time": probe_at, "decoded": decoded})
        return decoded

    successful_index: int | None = None
    for index, probe_at in enumerate(probe_points):
        decoded = decode_probe(probe_at)
        if decoded:
            successful_index = index
            break
    if successful_index is None:
        # Locate the last readable area only to produce a useful diagnostic.
        # Do not use it as a replacement duration: this exact pattern is what a
        # fast-start MP4 with a truncated media payload looks like.
        first_probe = min(.25, max(.05, duration * .001))
        if not decode_probe(first_probe):
            raise MediaError("源视频没有可解码画面，无法进行视觉分析。请重新选择可正常播放的视频文件。")
        low, high = first_probe, probe_points[-1] if probe_points else duration
        for _ in range(14):
            if high - low <= 1.0:
                break
            middle = round((low + high) / 2.0, 3)
            if decode_probe(middle):
                low = middle
            else:
                high = middle
        last_decodable = max(first_probe, low)
        try:
            file_size = path.stat().st_size
        except OSError:
            file_size = 0
        size_text = f"（当前文件 {file_size / 1_000_000:.1f} MB）" if file_size > 0 else ""
        raise MediaError(
            "当前选择的源视频内容不完整："
            f"轨道元数据标记时长为 {_clock_text(duration)}，"
            f"但画面数据只能读取到约 {_clock_text(last_decodable)}{size_text}。"
            "播放器可能仍会显示元数据中的完整时长，但后段并没有可解码画面。"
            "已停止分析，避免把局部内容误当成全片；请重新选择完整的原始视频。"
        )
    warnings: list[str] = []
    if successful_index >= 2:
        latest_failed = attempts[successful_index - 1]["time"] if successful_index else duration
        warnings.append(
            f"视频尾部 {_clock_text(latest_failed)} 之后未能稳定快速定位画面；"
            "可能是长 GOP、可变帧率或尾部仅有音频。系统将继续分析，并以实际可解码画面为准。"
        )
    container = float(container_duration or 0)
    if math.isfinite(container) and container - duration > max(2.0, duration * .0005):
        warnings.append(
            f"容器总时长比视频画面长 {container - duration:.1f} 秒；尾部可能只有声音，已按视频流时长分析。"
        )
    return {
        "status": "warning" if warnings else "ok",
        "videoDuration": round(duration, 3),
        "effectiveDuration": round(duration, 3),
        "containerDuration": round(container, 3) if container > 0 else None,
        "lastDecodedProbe": round(attempts[successful_index]["time"], 3),
        "attempts": attempts,
        "warnings": warnings,
    }


def validate_uniform_frame_coverage(
    frames: list[SampledFrame],
    *,
    duration: float,
    maximum_frames: int,
) -> None:
    """Ensure uniform samples represent the whole declared video timeline."""
    duration = max(0.0, float(duration))
    interval = max(2.0, duration / max(12, int(maximum_frames)))
    expected = max(1, min(int(maximum_frames), math.ceil(duration / interval)))
    minimum_count = max(2, math.ceil(expected * .85))
    latest = max((float(frame.time) for frame in frames), default=0.0)
    required_latest = max(0.0, duration - max(2.5, interval * 2.5))
    if len(frames) < minimum_count or latest + .05 < required_latest:
        raise MediaError(
            "源视频文件不完整："
            f"全片抽帧预计获得约 {expected} 帧，实际仅获得 {len(frames)} 帧，"
            f"画面只覆盖到 {_clock_text(latest)} / {_clock_text(duration)}。"
            "已停止视觉分析，避免把视频开头的局部结果误当成全片结果；请重新上传完整视频。"
        )


def snapshot_sampled_frames(
    frames: list[SampledFrame], output_directory: Path,
) -> list[SampledFrame]:
    """Freeze analysis inputs so background cache refreshes cannot remove them."""
    output_directory.mkdir(parents=True, exist_ok=True)
    snapshots: list[SampledFrame] = []
    for index, frame in enumerate(frames):
        target = output_directory / f"analysis-{index:05d}{frame.path.suffix.lower() or '.jpg'}"
        if not target.is_file() or target.stat().st_size <= 0:
            if not frame.path.is_file() or frame.path.stat().st_size <= 0:
                raise MediaError(f"分析画面缓存缺失：{frame.path.name}，请重新抽取该画面")
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.unlink(missing_ok=True)
            try:
                os.link(frame.path, temporary)
            except OSError:
                shutil.copy2(frame.path, temporary)
            temporary.replace(target)
        snapshots.append(SampledFrame(path=target, time=frame.time))
    return snapshots


def extract_uniform_frames(
    source: Path,
    output_directory: Path,
    *,
    duration: float,
    ffmpeg: str,
    maximum_frames: int = 96,
    progress_callback: Callable[[list[SampledFrame]], None] | None = None,
    progress_batch_size: int = 8,
    progress_first_batch_size: int | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[SampledFrame]:
    output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = output_directory / ".uniform-frames.json"
    with _uniform_frame_lock(output_directory):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        except (OSError, ValueError):
            manifest = {}
        if (
            manifest.get("schemaVersion") == 1
            and int(manifest.get("maximumFrames") or 0) == int(maximum_frames)
            and abs(float(manifest.get("duration") or 0) - float(duration)) < .02
        ):
            cached_frames = [
                SampledFrame(path=output_directory / str(item.get("filename") or ""), time=float(item.get("time") or 0))
                for item in manifest.get("items") or []
            ]
            if cached_frames and all(frame.path.is_file() and frame.path.stat().st_size > 0 for frame in cached_frames):
                validate_uniform_frame_coverage(
                    cached_frames, duration=duration, maximum_frames=maximum_frames,
                )
                if progress_callback is not None:
                    progress_callback(cached_frames)
                return cached_frames
        manifest_path.unlink(missing_ok=True)
        for stale_frame in output_directory.glob("frame-*.jpg"):
            stale_frame.unlink(missing_ok=True)
        frames = _extract_uniform_frames_uncached(
            source,
            output_directory,
            duration=duration,
            ffmpeg=ffmpeg,
            maximum_frames=maximum_frames,
            progress_callback=progress_callback,
            progress_batch_size=progress_batch_size,
            progress_first_batch_size=progress_first_batch_size,
            cancelled=cancelled,
        )
        validate_uniform_frame_coverage(
            frames, duration=duration, maximum_frames=maximum_frames,
        )
        temporary_manifest = manifest_path.with_suffix(".tmp")
        temporary_manifest.write_text(json.dumps({
            "schemaVersion": 1,
            "duration": duration,
            "maximumFrames": maximum_frames,
            "items": [{"filename": frame.path.name, "time": frame.time} for frame in frames],
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary_manifest.replace(manifest_path)
        return frames


def _extract_uniform_frames_uncached(
    source: Path,
    output_directory: Path,
    *,
    duration: float,
    ffmpeg: str,
    maximum_frames: int,
    progress_callback: Callable[[list[SampledFrame]], None] | None,
    progress_batch_size: int,
    progress_first_batch_size: int | None,
    cancelled: Callable[[], bool] | None,
) -> list[SampledFrame]:
    output_directory.mkdir(parents=True, exist_ok=True)
    interval = max(2.0, duration / max(12, maximum_frames))
    pattern = output_directory / "frame-%05d.jpg"
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-vf", f"fps=1/{interval:.6f},scale=512:-2:force_original_aspect_ratio=decrease",
        "-q:v", "3", "-y", str(pattern),
    ]
    timeout = max(180.0, duration * 1.5)
    started_at = time.monotonic()
    last_reported = 0
    batch_size = max(1, int(progress_batch_size))
    first_batch_size = max(1, int(progress_first_batch_size or batch_size))
    try:
        process = process_supervisor.start(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        raise MediaError(f"媒体命令无法执行：{error}") from error

    def sampled(paths: list[Path]) -> list[SampledFrame]:
        return [
            SampledFrame(path=path, time=min(duration, index * interval))
            for index, path in enumerate(paths)
        ]

    try:
        while process.poll() is None:
            if cancelled and cancelled():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                raise MediaError("任务已取消")
            if time.monotonic() - started_at > timeout:
                process.kill()
                process.wait(timeout=10)
                raise MediaError("时间轴缩略图抽帧超时")
            paths = sorted(output_directory.glob("frame-*.jpg"))
            # FFmpeg may still be writing the newest JPEG. Only expose files
            # that are no longer the active output so browsers never receive a
            # partially encoded tile.
            stable_paths = paths[:-1]
            if (
                progress_callback is not None
                and len(stable_paths) >= (first_batch_size if last_reported == 0 else last_reported + batch_size)
            ):
                try:
                    progress_callback(sampled(stable_paths))
                    last_reported = len(stable_paths)
                except Exception:
                    # A failed preview publication must not abort the actual
                    # extraction; the final sprite can still be produced.
                    pass
            time.sleep(0.2)
        stderr = process.stderr.read() if process.stderr is not None else ""
        if process.returncode != 0:
            raise MediaError((stderr or "时间轴缩略图抽帧失败")[-2000:])
    finally:
        if process.stderr is not None:
            process.stderr.close()
    paths = sorted(output_directory.glob("frame-*.jpg"))
    frames = sampled(paths)
    if progress_callback is not None and len(frames) > last_reported:
        try:
            progress_callback(frames)
        except Exception:
            pass
    return frames


def extract_frames_at_times(
    source: Path,
    output_directory: Path,
    times: Iterable[float],
    *,
    ffmpeg: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[SampledFrame]:
    output_directory.mkdir(parents=True, exist_ok=True)
    requested = [max(0.0, float(value)) for value in times]
    manifest_path = output_directory / ".detail-frames.json"
    requested_signature = [round(value, 3) for value in requested]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    except (OSError, ValueError, TypeError):
        manifest = {}
    if manifest.get("schemaVersion") == 1 and manifest.get("times") == requested_signature:
        cached = [
            SampledFrame(path=output_directory / str(item.get("filename") or ""), time=float(item.get("time") or 0))
            for item in manifest.get("items") or [] if isinstance(item, dict)
        ]
        if len(cached) == len(requested) and all(
            frame.path.is_file() and frame.path.stat().st_size > 0 for frame in cached
        ):
            if progress_callback is not None:
                try:
                    progress_callback(len(cached), len(cached))
                except Exception:
                    pass
            return cached
    manifest_path.unlink(missing_ok=True)
    for stale in output_directory.glob("detail-*.jpg"):
        stale.unlink(missing_ok=True)
    frames: list[SampledFrame] = []
    # Seeking each timestamp in its own ffmpeg process made a single VLM
    # refinement spawn dozens of processes (and was especially costly on
    # network storage). Open a bounded batch of inputs in one process instead.
    # Each input still seeks independently, but process startup and Python
    # scheduling overhead are paid once per batch.
    batch_size = 16
    # Publish the first measured result quickly. A full 16-input FFmpeg batch
    # can take long enough to look stalled on network storage; a four-frame
    # warm-up costs only one extra process and lets counted progress begin much
    # sooner. Later batches keep the more efficient size.
    first_batch_size = min(4, len(requested))
    batch_starts = (
        [0, *range(first_batch_size, len(requested), batch_size)]
        if requested else []
    )
    for batch_start in batch_starts:
        current_batch_size = first_batch_size if batch_start == 0 else batch_size
        batch = requested[batch_start:batch_start + current_batch_size]
        command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
        for second in batch:
            command.extend(["-ss", f"{second:.3f}", "-i", str(source)])
        for local_index, second in enumerate(batch):
            absolute_index = batch_start + local_index
            path = output_directory / f"detail-{absolute_index:03d}.jpg"
            command.extend([
                "-map", f"{local_index}:v:0", "-frames:v", "1", "-an",
                "-vf", "scale=640:-2:force_original_aspect_ratio=decrease",
                "-q:v", "2", "-y", str(path),
            ])
        _run(command, timeout=max(60, len(batch) * 12))
        for local_index, second in enumerate(batch):
            absolute_index = batch_start + local_index
            path = output_directory / f"detail-{absolute_index:03d}.jpg"
            if path.is_file():
                frames.append(SampledFrame(path=path, time=second))
        if progress_callback is not None:
            try:
                progress_callback(min(len(requested), batch_start + len(batch)), len(requested))
            except Exception:
                pass
    if len(frames) == len(requested):
        temporary_manifest = manifest_path.with_suffix(".tmp")
        temporary_manifest.write_text(json.dumps({
            "schemaVersion": 1,
            "times": requested_signature,
            "items": [{"filename": frame.path.name, "time": round(frame.time, 3)} for frame in frames],
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary_manifest.replace(manifest_path)
    return frames


def _thumbnail_is_black(path: Path) -> bool:
    """Return true only for frames that are effectively solid black."""
    try:
        with Image.open(path) as image:
            grayscale = ImageOps.grayscale(image)
            grayscale.thumbnail((180, 180))
            histogram = grayscale.histogram()
            pixels = max(1, sum(histogram))
            dark_pixels = sum(histogram[:19])
            mean = ImageStat.Stat(grayscale).mean[0]
            return dark_pixels / pixels >= .985 and mean <= 12
    except (OSError, ValueError) as error:
        raise MediaError(f"封面图像无法读取：{error}") from error


def extract_first_frame(source: Path, output: Path, *, ffmpeg: str) -> Path:
    """Extract the first decodable, non-black frame in the opening seconds."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file() and output.stat().st_size > 0:
        return output
    errors: list[str] = []
    decoded_black_frame = False
    for index, second in enumerate((0.0, 0.5, 1.0, 2.0, 3.0)):
        temporary = output.with_name(f".{output.stem}.{index}.tmp{output.suffix}")
        temporary.unlink(missing_ok=True)
        command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
        if second > 0:
            command.extend(["-ss", f"{second:.3f}"])
        command.extend([
            "-i", str(source), "-map", "0:v:0", "-frames:v", "1", "-an",
            "-vf", "scale=720:-2:force_original_aspect_ratio=decrease",
            "-q:v", "3", "-y", str(temporary),
        ])
        try:
            _run(command, timeout=60)
            if not temporary.is_file() or temporary.stat().st_size == 0:
                errors.append(f"{second:g} 秒未输出画面")
                continue
            if _thumbnail_is_black(temporary):
                decoded_black_frame = True
                errors.append(f"{second:g} 秒为纯黑画面")
                continue
            temporary.replace(output)
            return output
        except MediaError as error:
            errors.append(f"{second:g} 秒：{str(error)[:240]}")
        finally:
            temporary.unlink(missing_ok=True)
    if decoded_black_frame:
        raise MediaError("视频前 3 秒只有纯黑画面")
    detail = errors[-1] if errors else "没有可解码的视频画面"
    raise MediaError(f"无法提取视频封面：{detail}")


def extract_audio_waveform(
    source: Path,
    *,
    ffmpeg: str,
    bins: int = 1600,
    sample_rate: int = 8000,
    duration: float | None = None,
    progress_callback: Callable[[float, float, float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, list[float] | int]:
    """Decode mono PCM and retain signed min/max envelopes for timeline zooming."""
    bins = max(200, min(60000, int(bins)))
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-progress", "pipe:2", "-nostats",
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-acodec", "pcm_s16le", "-f", "s16le", "-",
    ]
    process: subprocess.Popen[bytes] | None = None
    progress_lines: list[str] = []
    timed_out = threading.Event()
    cancelled_process = threading.Event()

    def read_progress() -> None:
        if process is None or process.stderr is None:
            return
        for raw in iter(process.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()
            progress_lines.append(line)
            if not progress_callback or not duration or duration <= 0:
                continue
            key, _, value = line.partition("=")
            if key not in {"out_time_us", "out_time_ms"}:
                continue
            try:
                processed = max(0.0, float(value) / 1_000_000.0)
                progress_callback(min(.995, processed / duration), min(duration, processed), duration)
            except (TypeError, ValueError):
                continue

    try:
        process = process_supervisor.start(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        progress_reader = threading.Thread(target=read_progress, name="waveform-progress", daemon=True)
        progress_reader.start()
        def watch_cancellation() -> None:
            while process is not None and process.poll() is None:
                if cancelled and cancelled():
                    cancelled_process.set()
                    process.terminate()
                    return
                time.sleep(.1)
        cancellation_watcher = threading.Thread(
            target=watch_cancellation, name="waveform-cancellation", daemon=True,
        )
        cancellation_watcher.start()
        watchdog = threading.Timer(600, lambda: (timed_out.set(), process.kill()))
        watchdog.daemon = True
        watchdog.start()
        pcm = process.stdout.read() if process.stdout is not None else b""
        return_code = process.wait()
        watchdog.cancel()
        progress_reader.join(timeout=2)
        cancellation_watcher.join(timeout=1)
    except OSError as error:
        raise MediaError(f"无法生成音频波形：{error}") from error
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()
    if timed_out.is_set():
        raise MediaError("音频波形生成超时")
    if cancelled_process.is_set():
        raise MediaError("任务已取消")
    if return_code != 0:
        detail = "\n".join(progress_lines)[-2000:]
        raise MediaError(detail or "音频波形生成失败")
    samples = array("h")
    samples.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return {"sampleRate": sample_rate, "peaks": [], "rms": [], "minimums": [], "maximums": []}
    if progress_callback is not None and duration and duration > 0:
        try:
            progress_callback(1.0, duration, duration)
        except Exception:
            pass
    samples_per_bin = max(1, math.ceil(len(samples) / bins))
    peaks: list[float] = []
    rms_values: list[float] = []
    minimums: list[float] = []
    maximums: list[float] = []
    for offset in range(0, len(samples), samples_per_bin):
        chunk = samples[offset:offset + samples_per_bin]
        minimum = min(chunk) / 32768.0
        maximum = max(chunk) / 32768.0
        peak = max(abs(minimum), abs(maximum))
        mean_square = sum(value * value for value in chunk) / len(chunk)
        peaks.append(round(min(1.0, peak), 4))
        rms_values.append(round(min(1.0, math.sqrt(mean_square) / 32768.0), 4))
        minimums.append(round(max(-1.0, minimum), 4))
        maximums.append(round(min(1.0, maximum), 4))
    return {
        "sampleRate": sample_rate,
        "peaks": peaks,
        "rms": rms_values,
        "minimums": minimums,
        "maximums": maximums,
    }


def silence_intervals_from_waveform(
    waveform: dict[str, Any], *, duration: float, minimum_duration: float = .3,
    rms_threshold: float = .008,
) -> list[dict[str, float]]:
    """Derive conservative silence boundaries from an existing RMS envelope.

    The analysis pipeline already decodes the complete audio stream to create
    the timeline waveform. Reusing that measured envelope avoids a second
    full-media FFmpeg pass. A deliberately low threshold favours false
    negatives over cutting quiet speech as silence.
    """
    rms: list[float] = []
    for value in waveform.get("rms") or []:
        try:
            number = max(0.0, float(value))
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            rms.append(number)
    duration = max(0.0, float(duration or 0))
    if not rms or duration <= 0:
        return []
    seconds_per_bin = duration / len(rms)
    minimum_bins = max(1, math.ceil(max(.12, minimum_duration) / seconds_per_bin))
    intervals: list[dict[str, float]] = []
    run_start: int | None = None
    for index, value in enumerate([*rms, float("inf")]):
        if value <= rms_threshold:
            if run_start is None:
                run_start = index
            continue
        if run_start is None:
            continue
        if index - run_start >= minimum_bins:
            start = run_start * seconds_per_bin
            end = min(duration, index * seconds_per_bin)
            intervals.append({
                "start": round(start, 3), "end": round(end, 3),
                "duration": round(end - start, 3), "source": "waveform_rms",
            })
        run_start = None
    return intervals


def create_timeline_thumbnail_sprite(
    source: Path,
    output: Path,
    *,
    duration: float,
    ffmpeg: str,
    frame_count: int = 48,
    columns: int = 12,
    partial_output: Path | None = None,
    partial_callback: Callable[[dict[str, Any]], None] | None = None,
    frames_directory: Path | None = None,
    preserve_frames: bool = False,
    sampled_frames: list[SampledFrame] | None = None,
) -> dict[str, Any]:
    frame_count = max(12, min(96, frame_count))
    temporary_frames = frames_directory or output.parent / f".{output.stem}-frames"
    if frames_directory is None:
        shutil.rmtree(temporary_frames, ignore_errors=True)
    tile_width, tile_height = 160, 90
    partial_tiles: list[Image.Image] = []

    def publish_partial(frames: list[SampledFrame]) -> None:
        if partial_output is None or partial_callback is None or not frames:
            return
        for frame in frames[len(partial_tiles):]:
            with Image.open(frame.path) as image:
                partial_tiles.append(ImageOps.fit(
                    image.convert("RGB"),
                    (tile_width, tile_height),
                    method=Image.Resampling.LANCZOS,
                ))
        partial_columns = min(columns, len(partial_tiles))
        partial_rows = math.ceil(len(partial_tiles) / partial_columns)
        partial_sprite = Image.new(
            "RGB",
            (partial_columns * tile_width, partial_rows * tile_height),
            "#0c111c",
        )
        items: list[dict[str, float | int]] = []
        for index, (frame, tile) in enumerate(zip(frames, partial_tiles)):
            column = index % partial_columns
            row = index // partial_columns
            partial_sprite.paste(tile, (column * tile_width, row * tile_height))
            items.append({
                "time": round(frame.time, 3), "index": index, "column": column, "row": row,
                "brightness": 0.5, "sharpness": 0.5, "motion": 0.0,
                "black": 0, "blurred": 0, "faces": 0,
            })
        partial_output.parent.mkdir(parents=True, exist_ok=True)
        temporary_partial = partial_output.with_name(f".{partial_output.stem}.tmp{partial_output.suffix}")
        partial_sprite.save(temporary_partial, "JPEG", quality=76)
        temporary_partial.replace(partial_output)
        partial_callback({
            "tileWidth": tile_width,
            "tileHeight": tile_height,
            "columns": partial_columns,
            "rows": partial_rows,
            "spriteWidth": partial_columns * tile_width,
            "spriteHeight": partial_rows * tile_height,
            "items": items,
        })

    if sampled_frames:
        frames = [frame for frame in sampled_frames if frame.path.is_file()]
        if partial_output is not None and partial_callback is not None:
            publish_partial(frames)
    else:
        frames = extract_uniform_frames(
            source,
            temporary_frames,
            duration=duration,
            ffmpeg=ffmpeg,
            maximum_frames=frame_count,
            progress_callback=publish_partial if partial_output is not None and partial_callback is not None else None,
            progress_batch_size=8,
            progress_first_batch_size=4,
        )
    if not frames:
        raise MediaError("无法生成时间轴缩略图")
    rows = math.ceil(len(frames) / columns)
    sprite = Image.new("RGB", (columns * tile_width, rows * tile_height), "#0c111c")
    items: list[dict[str, float | int]] = []
    face_detector: Any = None
    cv2_module: Any = None
    try:
        import cv2
        cv2_module = cv2
        cascade = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        detector = cv2.CascadeClassifier(str(cascade))
        if not detector.empty():
            face_detector = detector
    except (ImportError, AttributeError, OSError):
        pass
    previous_gray: Image.Image | None = None
    for index, frame in enumerate(frames):
        with Image.open(frame.path) as image:
            tile = ImageOps.fit(image.convert("RGB"), (tile_width, tile_height), method=Image.Resampling.LANCZOS)
        gray = tile.convert("L").resize((80, 45), Image.Resampling.BILINEAR)
        brightness = ImageStat.Stat(gray).mean[0] / 255.0
        sharpness = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0] / 255.0
        motion = ImageStat.Stat(ImageChops.difference(gray, previous_gray)).mean[0] / 255.0 if previous_gray else 0.0
        faces = 0
        if face_detector is not None and cv2_module is not None:
            try:
                import numpy
                faces = len(face_detector.detectMultiScale(
                    numpy.asarray(gray), scaleFactor=1.12, minNeighbors=4, minSize=(18, 18),
                ))
            except Exception:
                faces = 0
        previous_gray = gray
        column = index % columns
        row = index // columns
        sprite.paste(tile, (column * tile_width, row * tile_height))
        items.append({
            "time": round(frame.time, 3), "index": index, "column": column, "row": row,
            "brightness": round(brightness, 4), "sharpness": round(sharpness, 4), "motion": round(motion, 4),
            "black": int(brightness < .08), "blurred": int(sharpness < .025), "faces": faces,
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".tmp.jpg")
    sprite.save(temporary_output, "JPEG", quality=80, optimize=True)
    temporary_output.replace(output)
    if not preserve_frames:
        shutil.rmtree(temporary_frames, ignore_errors=True)
    return {
        "tileWidth": tile_width,
        "tileHeight": tile_height,
        "columns": columns,
        "rows": rows,
        "spriteWidth": columns * tile_width,
        "spriteHeight": rows * tile_height,
        "items": items,
    }


def detect_scene_changes(
    source: Path,
    *,
    ffmpeg: str,
    threshold: float = 0.34,
    maximum: int = 400,
) -> list[float]:
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "info", "-i", str(source),
        "-vf", f"select='gt(scene,{max(0.1, min(0.9, threshold)):.3f})',showinfo",
        "-an", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MediaError(f"镜头切换检测失败：{error}") from error
    times = [float(value) for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr)]
    deduplicated: list[float] = []
    for value in times:
        if not deduplicated or value - deduplicated[-1] >= 0.35:
            deduplicated.append(round(value, 3))
        if len(deduplicated) >= maximum:
            break
    return deduplicated


def detect_scene_changes_in_ranges(
    source: Path,
    ranges: list[tuple[float, float]],
    *,
    ffmpeg: str,
    threshold: float = 0.34,
    maximum: int = 240,
) -> list[float]:
    """Detect physical cuts only inside VLM-verified candidate windows."""
    normalized = sorted(
        (max(0.0, float(start)), max(0.0, float(end)))
        for start, end in ranges if float(end) - float(start) >= .5
    )
    merged: list[list[float]] = []
    for start, end in normalized:
        if merged and start <= merged[-1][1] + .25:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    detected: list[float] = []
    for range_start, range_end in merged:
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "info", "-ss", f"{range_start:.3f}",
            "-t", f"{range_end - range_start:.3f}", "-i", str(source),
            "-vf", f"select='gt(scene,{max(0.1, min(0.9, threshold)):.3f})',showinfo",
            "-an", "-f", "null", "-",
        ]
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for raw in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr):
            relative = float(raw)
            absolute = range_start + relative if relative <= range_end - range_start + .5 else relative
            if range_start + .2 <= absolute <= range_end - .2:
                detected.append(round(absolute, 3))
        if len(detected) >= maximum:
            break
    result: list[float] = []
    for value in sorted(set(detected)):
        if not result or value - result[-1] >= .35:
            result.append(value)
        if len(result) >= maximum:
            break
    return result


def detect_silence_intervals(source: Path, *, ffmpeg: str, minimum_duration: float = 0.3) -> list[dict[str, float]]:
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "info", "-i", str(source), "-vn",
        "-af", f"silencedetect=noise=-36dB:d={minimum_duration:.2f}", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MediaError(f"静音检测失败：{error}") from error
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)", result.stderr)]
    return [
        {"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)}
        for start, end in zip(starts, ends) if end > start
    ]


def format_time(seconds: float) -> str:
    value = max(0, int(round(seconds)))
    hours, remainder = divmod(value, 3600)
    minutes, second = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{second:02d}"


def create_contact_sheet(frames: list[SampledFrame], output: Path, *, columns: int = 4) -> Path:
    if not frames:
        raise MediaError("没有可用于视觉分析的画面")
    tile_width, tile_height, label_height = 320, 180, 28
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), "#111722")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, frame in enumerate(frames):
        with Image.open(frame.path) as source:
            tile = ImageOps.fit(source.convert("RGB"), (tile_width, tile_height), method=Image.Resampling.LANCZOS)
        x = index % columns * tile_width
        y = index // columns * (tile_height + label_height)
        sheet.paste(tile, (x, y))
        draw.rectangle((x, y + tile_height, x + tile_width, y + tile_height + label_height), fill="#111722")
        draw.text((x + 9, y + tile_height + 7), f"FRAME {index + 1:02d}  T={format_time(frame.time)}", fill="#ffffff", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, "JPEG", quality=88, optimize=True)
    return output


def create_director_contact_sheet(
    rows: list[tuple[int, str, SampledFrame]],
    output: Path,
) -> Path:
    """Create a three-frame-per-candidate sheet with an unambiguous candidate mapping."""
    if not rows:
        raise MediaError("没有可用于事件导演分析的候选画面")
    tile_width, tile_height, label_height = 300, 169, 30
    columns = 3
    row_count = math.ceil(len(rows) / columns)
    sheet = Image.new("RGB", (columns * tile_width, row_count * (tile_height + label_height)), "#07111f")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for position, (candidate_index, phase, frame) in enumerate(rows):
        with Image.open(frame.path) as source:
            tile = ImageOps.fit(source.convert("RGB"), (tile_width, tile_height), method=Image.Resampling.LANCZOS)
        x = position % columns * tile_width
        y = position // columns * (tile_height + label_height)
        sheet.paste(tile, (x, y))
        draw.rectangle((x, y + tile_height, x + tile_width, y + tile_height + label_height), fill="#07111f")
        label = f"CANDIDATE {candidate_index:02d}  {phase.upper()}  T={format_time(frame.time)}"
        draw.text((x + 8, y + tile_height + 8), label, fill="#dceaff", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, "JPEG", quality=87, optimize=True)
    return output


def create_labeled_contact_sheet(
    frames: list[SampledFrame],
    labels: list[str],
    output: Path,
    *,
    columns: int = 4,
) -> Path:
    """Create a readable contact sheet for reviewing a rendered composition.

    Unlike the source-discovery contact sheet, labels describe positions on the
    *rendered* timeline (including cut-side context).  This makes the sheet a
    faithful review artifact instead of another source-video sample.
    """
    if not frames:
        raise MediaError("没有可用于成片审片的画面")
    columns = max(2, min(5, int(columns)))
    tile_width, tile_height, label_height = 320, 180, 42
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), "#09131d")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, frame in enumerate(frames):
        with Image.open(frame.path) as source:
            tile = ImageOps.fit(source.convert("RGB"), (tile_width, tile_height), method=Image.Resampling.LANCZOS)
        x = index % columns * tile_width
        y = index // columns * (tile_height + label_height)
        sheet.paste(tile, (x, y))
        draw.rectangle((x, y + tile_height, x + tile_width, y + tile_height + label_height), fill="#09131d")
        label = str(labels[index] if index < len(labels) else f"OUT {format_time(frame.time)}")[:78]
        draw.text((x + 8, y + tile_height + 7), label, fill="#e7f1ff", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, "JPEG", quality=89, optimize=True)
    return output


def render_clip(
    source: Path,
    output: Path,
    *,
    start: float,
    end: float,
    has_audio: bool,
    ffmpeg: str,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.mp4")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(source),
        "-t", f"{max(0.2, end - start):.3f}", "-map", "0:v:0",
    ]
    if has_audio:
        command.extend(["-map", "0:a?"])
    command.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
    ])
    if has_audio:
        command.extend(["-c:a", "aac", "-b:a", "160k"])
    command.extend(["-movflags", "+faststart", "-avoid_negative_ts", "make_zero", "-y", str(temporary)])
    process = process_supervisor.start(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    while process.poll() is None:
        if cancelled and cancelled():
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            raise MediaError("任务已取消")
        time.sleep(0.2)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise MediaError((stderr or stdout or "高光视频渲染失败")[-2000:])
    temporary.replace(output)


def render_composition(
    source: Path,
    output: Path,
    *,
    segments: list[dict[str, Any]],
    has_audio: bool,
    ffmpeg: str,
    cancelled: Callable[[], bool] | None = None,
    preview_width: int | None = None,
    subtitle_path: Path | None = None,
    subtitle_cues: list[dict[str, Any]] | None = None,
    subtitle_style: str = "clean",
    subtitle_layout: dict[str, Any] | None = None,
    subtitle_cue_styles: dict[str, dict[str, Any]] | None = None,
    subtitle_frame_width: int | None = None,
    subtitle_frame_height: int | None = None,
    cutaways: list[dict[str, Any]] | None = None,
    progress_callback: Callable[[float], None] | None = None,
    strict_source_boundaries: bool = False,
) -> float:
    """Render an editorial sequence, including timing and continuity techniques.

    The caller supplies logical shots.  Silence compression expands a logical
    shot into source pieces, while playback speed and transitions define the
    output schedule.  Audio is mixed on that schedule so a J/L bridge can cross
    a picture cut without changing any selected source boundary.
    """
    valid = [
        item for item in segments
        if source_duration_meets_minimum(item.get("start", 0), item.get("end", 0))
    ]
    if not valid:
        raise MediaError("事件高光没有可渲染的镜头")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.mp4")
    cutaways = [
        item for item in (cutaways or [])
        if source_duration_meets_minimum(item.get("sourceStart", 0), item.get("sourceEnd", 0))
    ]

    # Expand silence-compressed shots into executable pieces.  The first piece
    # keeps the logical transition; later pieces are direct cuts.
    expanded: list[dict[str, Any]] = []
    logical_first: dict[str, int] = {}
    logical_last: dict[str, int] = {}
    for logical_index, segment in enumerate(valid):
        segment_id = str(segment.get("id") or f"segment_{logical_index}")
        rate = normalize_playback_rate(segment.get("playbackRate"))
        pieces = source_pieces(segment)
        for piece_index, piece in enumerate(pieces):
            item = {
                **segment,
                "id": f"{segment_id}_piece_{piece_index}",
                "logicalId": segment_id,
                "logicalIndex": logical_index,
                "start": piece["start"],
                "end": piece["end"],
                "playbackRate": rate,
                "transitionIn": (
                    normalize_transition(segment.get("transitionIn"), first=logical_index == 0)
                    if piece_index == 0 else {"type": "cut", "duration": 0.0}
                ),
            }
            logical_first.setdefault(segment_id, len(expanded))
            logical_last[segment_id] = len(expanded)
            expanded.append(item)
    if not expanded:
        raise MediaError("事件高光没有可渲染的有效镜头")

    count = len(expanded)
    schedule_segments = [
        {
            **item,
            "end": float(item.get("start") or 0.0) + exclusive_render_duration(
                float(item.get("end") or 0.0) - float(item.get("start") or 0.0),
                strict=strict_source_boundaries,
            ),
        }
        for item in expanded
    ]
    schedule = composition_schedule(schedule_segments)
    composed_duration = composition_effective_duration(expanded)
    filters: list[str] = []
    input_arguments: list[str] = []
    durations: list[float] = []
    # L-cut extends the previous source audio past its picture end.  Track that
    # separately so the corresponding video stays at its original duration.
    audio_extensions = [0.0 for _ in expanded]
    audio_pre_extensions = [0.0 for _ in expanded]
    for logical_index in range(1, len(valid)):
        bridge = normalize_audio_bridge(valid[logical_index].get("audioBridge"))
        if bridge["type"] == "l_cut":
            previous_id = str(valid[logical_index - 1].get("id") or f"segment_{logical_index - 1}")
            previous_piece = logical_last.get(previous_id)
            if previous_piece is not None:
                audio_extensions[previous_piece] = bridge["duration"] * normalize_playback_rate(expanded[previous_piece].get("playbackRate"))
        elif bridge["type"] == "j_cut":
            current_id = str(valid[logical_index].get("id") or f"segment_{logical_index}")
            current_piece = logical_first.get(current_id)
            if current_piece is not None:
                rate = normalize_playback_rate(expanded[current_piece].get("playbackRate"))
                audio_pre_extensions[current_piece] = min(
                    float(expanded[current_piece]["start"]), bridge["duration"] * rate,
                )

    for index, segment in enumerate(expanded):
        start = max(0.0, float(segment["start"]))
        end = max(start + .2, float(segment["end"]))
        source_duration = end - start
        render_source_duration = exclusive_render_duration(
            source_duration, strict=strict_source_boundaries,
        )
        rate = normalize_playback_rate(segment.get("playbackRate"))
        duration = render_source_duration / rate
        durations.append(duration)
        input_start = max(0.0, start - audio_pre_extensions[index])
        video_trim_start = start - input_start
        input_duration = audio_pre_extensions[index] + render_source_duration + audio_extensions[index]
        input_arguments.extend(["-ss", f"{input_start:.3f}", "-t", f"{input_duration:.3f}", "-i", str(source)])
        video_source = f"[{index}:v]"
        scale = (
            f",scale='if(gte(iw,ih),min({int(preview_width)},iw),-2)':"
            f"'if(gte(iw,ih),-2,min({int(preview_width)},ih))'"
            if preview_width else ""
        )
        filters.append(
            f"{video_source}trim=start={video_trim_start:.3f}:duration={render_source_duration:.3f},setpts=(PTS-STARTPTS)/{rate:.3f}"
            f"{scale},fps={CONTENT_RENDER_FPS:.3f},settb=AVTB,format=yuv420p[v{index}]"
        )
        if has_audio:
            audio_source = f"[{index}:a]"
            output_start = float(schedule[index]["outputStart"])
            logical_index = int(segment.get("logicalIndex") or 0)
            bridge = normalize_audio_bridge(valid[logical_index].get("audioBridge"), first=logical_index == 0)
            is_first_piece = logical_first.get(str(segment.get("logicalId"))) == index
            if is_first_piece and bridge["type"] == "j_cut":
                output_start = max(0.0, output_start - audio_pre_extensions[index] / rate)
            elif is_first_piece and bridge["type"] == "l_cut":
                # Let the previous voice finish before this shot's synchronous
                # sound enters.  Video is already visible during this interval.
                output_start += bridge["duration"]
            audio_duration = input_duration / rate
            fallback_fade = max(0.0, min(.35, float(segment.get("audioEdgeFadeSeconds") or .06)))
            fade_in = min(max(0.0, float(segment.get("audioFadeIn", fallback_fade))), audio_duration / 3)
            fade_out = min(max(0.0, float(segment.get("audioFadeOut", fallback_fade))), audio_duration / 3)
            gain = 0.0 if segment.get("muted") else max(0.0, min(2.0, float(segment.get("audioGain", 1.0))))
            delay_ms = max(0, round(output_start * 1000))
            fade_filters = ""
            if fade_in > 0:
                fade_filters += f"afade=t=in:st=0:d={fade_in:.3f},"
            if fade_out > 0:
                fade_filters += f"afade=t=out:st={max(0.0, audio_duration - fade_out):.3f}:d={fade_out:.3f},"
            filters.append(
                f"{audio_source}atrim=duration={input_duration:.3f},asetpts=PTS-STARTPTS,"
                f"atempo={rate:.3f},aresample=async=1:first_pts=0,"
                f"volume={gain:.3f},"
                f"{fade_filters}"
                f"adelay={delay_ms}|{delay_ms}[a{index}]"
            )
    video_current = "v0"
    composed_duration = durations[0]
    for index in range(1, count):
        transition = normalize_transition(expanded[index].get("transitionIn"))
        dissolve = transition.get("type") in {"dissolve", "fade_black"}
        transition_duration = min(
            .4,
            max(.08, float(transition.get("duration") or .18)),
            durations[index - 1] / 3,
            durations[index] / 3,
        ) if dissolve else 0.0
        next_video = f"vc{index}"
        temporary_video = f"vtmp{index}"
        if dissolve and transition_duration >= .08:
            offset = max(.01, composed_duration - transition_duration)
            xfade_name = "fadeblack" if transition.get("type") == "fade_black" else "fade"
            filters.append(
                f"[{video_current}][v{index}]xfade=transition={xfade_name}:duration={transition_duration:.3f}:"
                f"offset={offset:.3f}[{temporary_video}]"
            )
            filters.append(f"[{temporary_video}]setpts=PTS-STARTPTS[{next_video}]")
            composed_duration += durations[index] - transition_duration
        else:
            filters.append(f"[{video_current}][v{index}]concat=n=2:v=1:a=0[{temporary_video}]")
            filters.append(f"[{temporary_video}]setpts=PTS-STARTPTS[{next_video}]")
            composed_duration += durations[index]
        video_current = next_video
    output_video_label = video_current if count > 1 else "v0"

    # Muted cutaways cover a jump cut while the primary soundtrack continues.
    cutaway_input_count = 0
    for cutaway_index, cutaway in enumerate(cutaways):
        primary_id = str(cutaway.get("primarySegmentId") or "")
        logical_position = next((i for i, item in enumerate(valid) if str(item.get("id") or f"segment_{i}") == primary_id), None)
        if logical_position is None:
            continue
        primary_schedule = composition_schedule(valid)[logical_position]
        cutaway_start = max(0.0, float(primary_schedule["outputStart"]) + float(cutaway.get("outputOffset") or 0))
        source_start = max(0.0, float(cutaway.get("sourceStart") or 0))
        source_end = max(source_start + .2, float(cutaway.get("sourceEnd") or source_start))
        duration = min(source_end - source_start, max(.2, composed_duration - cutaway_start))
        if duration + 1e-6 < .2:
            continue
        input_index = count + cutaway_input_count
        cutaway_input_count += 1
        input_arguments.extend(["-ss", f"{source_start:.3f}", "-t", f"{duration:.3f}", "-i", str(source)])
        scale = (
            f",scale='if(gte(iw,ih),min({int(preview_width)},iw),-2)':"
            f"'if(gte(iw,ih),-2,min({int(preview_width)},ih))'"
            if preview_width else ""
        )
        cutaway_label = f"broll{cutaway_index}"
        filters.append(
            f"[{input_index}:v]setpts=PTS-STARTPTS+{cutaway_start:.3f}/TB{scale},"
            f"fps={CONTENT_RENDER_FPS:.3f},settb=AVTB,format=yuv420p[{cutaway_label}]"
        )
        next_label = f"voverlay{cutaway_index}"
        filters.append(
            f"[{output_video_label}][{cutaway_label}]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2:"
            f"eof_action=pass:enable='between(t,{cutaway_start:.3f},{cutaway_start + duration:.3f})'[{next_label}]"
        )
        output_video_label = next_label

    audio_output_label: str | None = None
    if has_audio:
        audio_inputs = "".join(f"[a{index}]" for index in range(count))
        filters.append(
            f"{audio_inputs}amix=inputs={count}:duration=longest:dropout_transition=0:normalize=0,"
            f"apad=pad_dur={composed_duration:.3f},atrim=duration={composed_duration:.3f},"
            "loudnorm=I=-16:LRA=11:TP=-1.5,alimiter=limit=0.95,asetpts=PTS-STARTPTS[aout]"
        )
        audio_output_label = "aout"
    if subtitle_path and subtitle_cues:
        subtitle_style = normalize_subtitle_style(subtitle_style)
        visual_style = {
            key: value for key, value in SUBTITLE_STYLES[subtitle_style].items()
            if key not in {"fontsize", "x", "y"}
        }
        default_layout = subtitle_layout if isinstance(subtitle_layout, dict) else {}
        cue_style_lookup = subtitle_cue_styles if isinstance(subtitle_cue_styles, dict) else {}
        subtitle_dir = subtitle_path.with_suffix(".cues")
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        for cue_index, cue in enumerate(subtitle_cues):
            text_path = subtitle_dir / f"{cue_index:04d}.txt"
            speaker_prefix = (
                f"{str(cue.get('speakerLabel') or '')}："
                if cue.get("showSpeakerLabel") and cue.get("speakerLabel") else ""
            )
            layout = cue_style_lookup.get(str(cue.get("id") or "")) or default_layout
            try:
                size_ratio = max(.012, min(.080, float(layout.get("fontSizeRatio") or .040)))
                offset_x = max(-.40, min(.40, float(layout.get("offsetXRatio") or 0)))
                offset_y = max(-.40, min(.40, float(layout.get("offsetYRatio") or 0)))
            except (AttributeError, TypeError, ValueError):
                size_ratio, offset_x, offset_y = .040, 0.0, 0.0
            reference_width = max(1, int(subtitle_frame_width or 1920))
            reference_height = max(1, int(subtitle_frame_height or 1080))
            font_pixels = subtitle_font_pixels(reference_width, reference_height, size_ratio)
            maximum_units = reference_width * .90 / max(1.0, font_pixels)
            rendered_text = wrap_subtitle_text(
                speaker_prefix + str(cue.get("text") or "").replace("\n", " "),
                maximum_units,
            )
            text_path.write_text(rendered_text, encoding="utf-8")
            escaped_text_path = str(text_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            escaped_font_path = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc".replace(":", "\\:")
            next_label = f"vsub{cue_index}"
            horizontal = str(layout.get("horizontal") or "center")
            vertical = str(layout.get("vertical") or "bottom")
            x_anchor = {"left": "w*0.05", "right": "w-text_w-w*0.05"}.get(horizontal, "(w-text_w)/2")
            y_anchor = {"top": "h*0.05", "middle": "(h-text_h)/2"}.get(vertical, "h-text_h-h*0.05")
            x_expression = f"max(w*0.05\\,min(w-text_w-w*0.05\\,{x_anchor}+w*{offset_x:.5f}))"
            y_expression = f"max(h*0.05\\,min(h-text_h-h*0.05\\,{y_anchor}+h*{offset_y:.5f}))"
            style = {
                **visual_style,
                "fontsize": f"min(w\\,h)*{size_ratio:.5f}",
                "x": x_expression,
                "y": y_expression,
            }
            if cue.get("speakerColor"):
                style["fontcolor"] = str(cue["speakerColor"])
            style_options = ":".join(f"{key}={value}" for key, value in style.items())
            filters.append(
                f"[{output_video_label}]drawtext=fontfile='{escaped_font_path}':textfile='{escaped_text_path}':"
                f"{style_options}:"
                f"enable='between(t,{float(cue['start']):.3f},{float(cue['end']):.3f})'[{next_label}]"
            )
            output_video_label = next_label
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", *input_arguments,
        "-filter_complex", ";".join(filters), "-map", f"[{output_video_label}]",
    ]
    if audio_output_label:
        command.extend(["-map", f"[{audio_output_label}]"])
    command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "25" if preview_width else "20", "-pix_fmt", "yuv420p"])
    if has_audio:
        command.extend(["-c:a", "aac", "-b:a", "96k" if preview_width else "160k"])
    command.extend([
        "-movflags", "+faststart", "-shortest",
        "-progress", "pipe:1", "-nostats", "-y", str(temporary),
    ])
    process = process_supervisor.start(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    progress_lines: queue.Queue[str | None] = queue.Queue()

    def read_progress_output() -> None:
        if process.stdout is not None:
            for raw_line in process.stdout:
                progress_lines.put(raw_line)
        progress_lines.put(None)

    progress_reader = threading.Thread(
        target=read_progress_output,
        name="ffmpeg-composition-progress",
        daemon=True,
    )
    progress_reader.start()
    reported_progress = 0.0

    def report_progress(value: float) -> None:
        nonlocal reported_progress
        if progress_callback is None:
            return
        value = max(reported_progress, min(1.0, float(value)))
        if value <= reported_progress and value < 1.0:
            return
        reported_progress = value
        try:
            progress_callback(value)
        except Exception:
            # Rendering must not fail because a UI progress observer failed.
            pass

    def consume_progress_lines() -> None:
        while True:
            try:
                raw_line = progress_lines.get_nowait()
            except queue.Empty:
                return
            if raw_line is None:
                return
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            name, raw_value = line.split("=", 1)
            if name in {"out_time_us", "out_time_ms"}:
                try:
                    rendered_seconds = float(raw_value) / 1_000_000
                except ValueError:
                    continue
                report_progress(min(.995, rendered_seconds / max(.001, composed_duration)))

    while process.poll() is None:
        if cancelled and cancelled():
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            progress_reader.join(timeout=1)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            temporary.unlink(missing_ok=True)
            raise MediaError("任务已取消")
        consume_progress_lines()
        time.sleep(.2)
    progress_reader.join(timeout=1)
    consume_progress_lines()
    stdout = ""
    if process.stdout is not None:
        process.stdout.close()
    stderr = process.stderr.read() if process.stderr is not None else ""
    if process.stderr is not None:
        process.stderr.close()
    if process.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise MediaError((stderr or stdout or "事件高光组合渲染失败")[-3000:])
    temporary.replace(output)
    report_progress(1.0)
    return round(composed_duration, 3)


def validate_rendered_clip(
    output: Path,
    *,
    expected_duration: float,
    expect_audio: bool,
    ffmpeg: str,
    ffprobe: str,
) -> VideoInfo:
    """Probe and fully decode a rendered clip before exposing it to the UI."""
    try:
        info = probe_video(output, ffprobe)
        tolerance = max(0.5, expected_duration * 0.05)
        if abs(info.duration - expected_duration) > tolerance:
            raise MediaError(
                f"成片时长质检失败：期望 {expected_duration:.3f} 秒，实际 {info.duration:.3f} 秒"
            )
        if info.width <= 0 or info.height <= 0:
            raise MediaError("成片画面尺寸无效")
        if expect_audio and not info.has_audio:
            raise MediaError("源视频包含音频，但成片音轨缺失")
        _run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(output),
            "-map", "0:v:0", "-f", "null", "-",
        ], timeout=max(90.0, expected_duration * 3.0))
        return info
    except Exception:
        output.unlink(missing_ok=True)
        raise


def create_preview_proxy(
    source: Path,
    output: Path,
    *,
    has_audio: bool,
    ffmpeg: str,
    maximum_dimension: int = 1280,
    maximum_duration: float | None = None,
) -> None:
    maximum_dimension = max(360, min(1280, int(maximum_dimension)))
    if maximum_dimension % 2:
        maximum_dimension -= 1
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.mp4")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-map", "0:v:0", "-vf",
        f"scale=w='if(gte(iw,ih),min({maximum_dimension},iw),-2)':h='if(gte(iw,ih),-2,min({maximum_dimension},ih))'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-level:v", "4.1",
        "-force_key_frames", "expr:gte(t,n_forced*2)",
    ]
    if has_audio:
        command.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "96k"])
    if maximum_duration is not None and math.isfinite(float(maximum_duration)) and float(maximum_duration) > 0:
        command.extend(["-t", f"{float(maximum_duration):.3f}"])
    command.extend(["-movflags", "+faststart", "-y", str(temporary)])
    _run(command, timeout=3600)
    temporary.replace(output)


def create_webm_preview(
    source: Path,
    output: Path,
    *,
    has_audio: bool,
    ffmpeg: str,
    maximum_dimension: int = 960,
) -> None:
    """Create a royalty-free browser fallback for Chromium builds without H.264.

    The primary review proxy remains MP4 because it is faster and smaller on
    normal Chrome/Safari installations. Some embedded/open-source Chromium
    builds ship without proprietary H.264/AAC decoders, so an H.264 proxy can
    never fix their MEDIA_ERR_SRC_NOT_SUPPORTED error. VP9 + Opus in WebM is
    generated only after the browser reports that failure.
    """
    maximum_dimension = max(360, min(1280, int(maximum_dimension)))
    if maximum_dimension % 2:
        maximum_dimension -= 1
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.webm")
    temporary.unlink(missing_ok=True)
    # The Conda ffmpeg used by the analysis environment is intentionally
    # minimal and may not contain libvpx. Prefer the system build for WebM,
    # while retaining the configured binary as a portable fallback.
    webm_ffmpeg = shutil.which("ffmpeg", path="/usr/bin:/usr/local/bin") or ffmpeg
    command = [
        webm_ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-map", "0:v:0", "-vf",
        f"scale=w='if(gte(iw,ih),min({maximum_dimension},iw),-2)':h='if(gte(iw,ih),-2,min({maximum_dimension},ih))'",
        "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
        "-row-mt", "1", "-threads", "8", "-b:v", "0", "-crf", "36",
    ]
    if has_audio:
        command.extend(["-map", "0:a?", "-c:a", "libopus", "-b:a", "96k"])
    else:
        command.append("-an")
    command.extend(["-y", str(temporary)])
    _run(command, timeout=3600)
    temporary.replace(output)
