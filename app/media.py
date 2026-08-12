from __future__ import annotations

import json
import math
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    width: int
    height: int
    has_audio: bool


@dataclass(frozen=True)
class SampledFrame:
    path: Path
    time: float


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
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        video = next(item for item in streams if item.get("codec_type") == "video")
        duration = float(data.get("format", {}).get("duration") or video.get("duration"))
    except (ValueError, TypeError, StopIteration, json.JSONDecodeError) as error:
        raise MediaError("无法读取有效的视频流和时长") from error
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError("视频时长无效")
    return VideoInfo(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        has_audio=any(item.get("codec_type") == "audio" for item in streams),
    )


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
        process = subprocess.Popen(
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
    frames: list[SampledFrame] = []
    # Seeking each timestamp in its own ffmpeg process made a single VLM
    # refinement spawn dozens of processes (and was especially costly on
    # network storage). Open a bounded batch of inputs in one process instead.
    # Each input still seeks independently, but process startup and Python
    # scheduling overhead are paid once per batch.
    batch_size = 16
    for batch_start in range(0, len(requested), batch_size):
        batch = requested[batch_start:batch_start + batch_size]
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
    return frames


def extract_first_frame(source: Path, output: Path, *, ffmpeg: str) -> Path:
    """Extract and cache the first decodable video frame for task covers."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file() and output.stat().st_size > 0:
        return output
    temporary = output.with_name(f".{output.stem}.tmp{output.suffix}")
    temporary.unlink(missing_ok=True)
    _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-frames:v", "1", "-vf", "scale=720:-2:force_original_aspect_ratio=decrease",
        "-q:v", "3", "-y", str(temporary),
    ], timeout=60)
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise MediaError("无法提取视频首帧")
    temporary.replace(output)
    return output


def extract_audio_waveform(
    source: Path,
    *,
    ffmpeg: str,
    bins: int = 1600,
    sample_rate: int = 8000,
    duration: float | None = None,
    progress_callback: Callable[[float, float, float], None] | None = None,
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
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        progress_reader = threading.Thread(target=read_progress, name="waveform-progress", daemon=True)
        progress_reader.start()
        watchdog = threading.Timer(600, lambda: (timed_out.set(), process.kill()))
        watchdog.daemon = True
        watchdog.start()
        pcm = process.stdout.read() if process.stdout is not None else b""
        return_code = process.wait()
        watchdog.cancel()
        progress_reader.join(timeout=2)
    except OSError as error:
        raise MediaError(f"无法生成音频波形：{error}") from error
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()
    if timed_out.is_set():
        raise MediaError("音频波形生成超时")
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
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
    progress_callback: Callable[[float], None] | None = None,
) -> float:
    """Render one event highlight from an ordered list of source ranges."""
    valid = [item for item in segments if float(item.get("end", 0)) - float(item.get("start", 0)) >= .2]
    if not valid:
        raise MediaError("事件高光没有可渲染的镜头")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.mp4")
    count = len(valid)
    filters: list[str] = []
    input_arguments: list[str] = []
    durations: list[float] = []
    for index, segment in enumerate(valid):
        start = max(0.0, float(segment["start"]))
        end = max(start + .2, float(segment["end"]))
        duration = end - start
        durations.append(duration)
        input_arguments.extend(["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source)])
        video_source = f"[{index}:v]"
        scale = f",scale='min({int(preview_width)},iw)':-2:force_original_aspect_ratio=decrease" if preview_width else ""
        filters.append(
            f"{video_source}setpts=PTS-STARTPTS"
            f"{scale},fps=30,settb=AVTB,format=yuv420p[v{index}]"
        )
        if has_audio:
            audio_source = f"[{index}:a]"
            fade = min(.08, duration / 5)
            filters.append(
                f"{audio_source}asetpts=PTS-STARTPTS,"
                f"aresample=async=1:first_pts=0,afade=t=in:st=0:d={fade:.3f},"
                f"afade=t=out:st={max(0.0, duration - fade):.3f}:d={fade:.3f}[a{index}]"
            )
    video_current = "v0"
    audio_current = "a0"
    composed_duration = durations[0]
    for index in range(1, count):
        transition = valid[index].get("transitionIn") or {}
        dissolve = transition.get("type") == "dissolve"
        transition_duration = min(
            .4,
            max(.08, float(transition.get("duration") or .18)),
            durations[index - 1] / 3,
            durations[index] / 3,
        ) if dissolve else 0.0
        next_video = f"vc{index}"
        next_audio = f"ac{index}"
        temporary_video = f"vtmp{index}"
        temporary_audio = f"atmp{index}"
        if dissolve and transition_duration >= .08:
            offset = max(.01, composed_duration - transition_duration)
            filters.append(
                f"[{video_current}][v{index}]xfade=transition=fade:duration={transition_duration:.3f}:"
                f"offset={offset:.3f}[{temporary_video}]"
            )
            filters.append(f"[{temporary_video}]setpts=PTS-STARTPTS[{next_video}]")
            if has_audio:
                filters.append(
                    f"[{audio_current}][a{index}]acrossfade=d={transition_duration:.3f}:c1=tri:c2=tri[{temporary_audio}]"
                )
                filters.append(f"[{temporary_audio}]asetpts=PTS-STARTPTS[{next_audio}]")
            composed_duration += durations[index] - transition_duration
        else:
            filters.append(f"[{video_current}][v{index}]concat=n=2:v=1:a=0[{temporary_video}]")
            filters.append(f"[{temporary_video}]setpts=PTS-STARTPTS[{next_video}]")
            if has_audio:
                filters.append(f"[{audio_current}][a{index}]concat=n=2:v=0:a=1[{temporary_audio}]")
                filters.append(f"[{temporary_audio}]asetpts=PTS-STARTPTS[{next_audio}]")
            composed_duration += durations[index]
        video_current = next_video
        audio_current = next_audio
    output_video_label = video_current if count > 1 else "v0"
    if subtitle_path and subtitle_cues and not preview_width:
        subtitle_style = normalize_subtitle_style(subtitle_style)
        style = SUBTITLE_STYLES[subtitle_style]
        subtitle_dir = subtitle_path.with_suffix(".cues")
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        for cue_index, cue in enumerate(subtitle_cues):
            text_path = subtitle_dir / f"{cue_index:04d}.txt"
            text_path.write_text(str(cue.get("text") or "").replace("\n", " "), encoding="utf-8")
            escaped_text_path = str(text_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            escaped_font_path = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc".replace(":", "\\:")
            next_label = f"vsub{cue_index}"
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
    if has_audio:
        command.extend(["-map", f"[{audio_current if count > 1 else 'a0'}]"])
    command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "25" if preview_width else "20", "-pix_fmt", "yuv420p"])
    if has_audio:
        command.extend(["-c:a", "aac", "-b:a", "96k" if preview_width else "160k"])
    command.extend([
        "-movflags", "+faststart", "-shortest",
        "-progress", "pipe:1", "-nostats", "-y", str(temporary),
    ])
    process = subprocess.Popen(
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
