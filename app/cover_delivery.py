from __future__ import annotations

import hashlib
import json
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .media import MediaError, _run, probe_video


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_child(root: Path, filename: str) -> Path | None:
    if not filename or Path(filename).name != filename:
        return None
    root = root.resolve()
    candidate = (root / filename).resolve()
    return candidate if candidate.parent == root else None


def output_cover_filename(video_filename: str) -> str:
    return f"{Path(video_filename).stem}-cover.jpg"


def output_package_filename(video_filename: str) -> str:
    return f"{Path(video_filename).stem}-package.zip"


def output_intro_filename(video_filename: str, version_number: int) -> str:
    return f"{Path(video_filename).stem}-cover-intro-v{version_number:03d}.mp4"


def cover_version_path(job: dict[str, Any], cover_version: dict[str, Any]) -> Path | None:
    relative = str(cover_version.get("artifactFile") or "")
    work_root = Path(str(job.get("workDirectory") or ""))
    if not relative or Path(relative).is_absolute() or not work_root:
        return None
    root = work_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def current_cover_version(job: dict[str, Any]) -> dict[str, Any] | None:
    current_id = str(job.get("currentCoverVersionId") or "")
    return next((
        item for item in job.get("coverVersions") or []
        if isinstance(item, dict) and str(item.get("id") or "") == current_id
    ), None)


def bind_cover_to_output_version(
    job: dict[str, Any], cover_version: dict[str, Any], output_version: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Copy one approved cover beside each MP4 and persist an explicit binding."""
    if not output_version:
        return []
    source = cover_version_path(job, cover_version)
    if not source or not source.is_file():
        raise MediaError("已确认封面文件不存在，无法绑定成片")
    expected_hash = str(cover_version.get("contentHash") or "")
    actual_hash = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    if expected_hash and actual_hash != expected_hash:
        raise MediaError("已确认封面内容发生变化，无法绑定成片")
    output_root = Path(str(job.get("outputDirectory") or ""))
    output_root.mkdir(parents=True, exist_ok=True)
    bound: list[dict[str, Any]] = []
    for output in output_version.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        video_filename = str(output.get("filename") or "")
        video = _safe_child(output_root, video_filename)
        if not video or not video.is_file():
            continue
        cover_filename = output_cover_filename(video_filename)
        destination = _safe_child(output_root, cover_filename)
        if not destination:
            continue
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        shutil.copy2(source, temporary)
        temporary.replace(destination)
        binding = {
            "coverVersionId": str(cover_version.get("id") or ""),
            "coverFilename": cover_filename,
            "coverContentHash": actual_hash,
            "coverBoundAt": _now_iso(),
        }
        output.update(binding)
        bound.append({"filename": video_filename, **binding})
    if bound:
        output_version.update({
            "coverVersionId": str(cover_version.get("id") or ""),
            "coverContentHash": actual_hash,
            "coverBoundAt": bound[0]["coverBoundAt"],
        })
    return bound


def output_cover_path(
    job: dict[str, Any], output: dict[str, Any], version: dict[str, Any] | None = None,
) -> Path | None:
    output_root = Path(str(job.get("outputDirectory") or ""))
    bound = _safe_child(output_root, str(output.get("coverFilename") or ""))
    if bound and bound.is_file():
        return bound
    cover_id = str(output.get("coverVersionId") or (version or {}).get("coverVersionId") or "")
    cover = next((
        item for item in job.get("coverVersions") or []
        if isinstance(item, dict) and str(item.get("id") or "") == cover_id
    ), None)
    fallback = cover_version_path(job, cover or {}) if cover else None
    return fallback if fallback and fallback.is_file() else None


def build_output_package(
    job: dict[str, Any], output: dict[str, Any], version: dict[str, Any],
    *, video_download_name: str,
) -> Path:
    output_root = Path(str(job.get("outputDirectory") or ""))
    video = _safe_child(output_root, str(output.get("filename") or ""))
    cover = output_cover_path(job, output, version)
    if not video or not video.is_file():
        raise MediaError("成片文件不存在")
    if not cover:
        raise MediaError("当前成片尚未绑定封面")
    package = _safe_child(output_root, output_package_filename(video.name))
    if not package:
        raise MediaError("无法创建发布包路径")
    video_name = Path(video_download_name).name
    package_stem = Path(video_name).stem
    manifest = {
        "schemaVersion": "cover-delivery-v1",
        "jobId": str(job.get("id") or ""),
        "outputVersionId": str(version.get("id") or ""),
        "coverVersionId": str(output.get("coverVersionId") or version.get("coverVersionId") or ""),
        "video": video_name,
        "cover": f"{package_stem}-cover.jpg",
        "coverContentHash": str(output.get("coverContentHash") or version.get("coverContentHash") or ""),
        "createdAt": _now_iso(),
    }
    temporary = package.with_name(f".{package.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(video, video_name)
            archive.write(cover, manifest["cover"])
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        temporary.replace(package)
    finally:
        temporary.unlink(missing_ok=True)
    return package


def render_cover_intro(
    video: Path, cover: Path, output: Path, *, duration: float,
    ffmpeg: str, ffprobe: str,
) -> dict[str, Any]:
    """Render a new MP4 with a silent still cover prepended; never mutate the source."""
    info = probe_video(video, ffprobe)
    intro_seconds = max(.5, min(5.0, float(duration)))
    width = max(2, int(info.width) // 2 * 2)
    height = max(2, int(info.height) // 2 * 2)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.tmp.mp4")
    cover_filter = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=30,format=yuv420p[v0]"
    )
    video_filter = (
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p[v1]"
    )
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", "30", "-t", f"{intro_seconds:.3f}", "-i", str(cover),
        "-i", str(video),
    ]
    if info.has_audio:
        command.extend([
            "-f", "lavfi", "-t", f"{intro_seconds:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-filter_complex",
            f"{cover_filter};{video_filter};[1:a]aresample=48000[a1];"
            "[v0][2:a][v1][a1]concat=n=2:v=1:a=1[v][a]",
            "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k",
        ])
    else:
        command.extend([
            "-filter_complex", f"{cover_filter};{video_filter};[v0][v1]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-an",
        ])
    command.extend([
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary),
    ])
    try:
        _run(command, timeout=max(600.0, info.duration * 12.0))
        rendered = probe_video(temporary, ffprobe)
        if rendered.duration < info.duration + intro_seconds - .35:
            raise MediaError("封面片头成片时长校验失败")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "duration": round(rendered.duration, 3), "width": rendered.width,
        "height": rendered.height, "hasAudio": rendered.has_audio,
        "introDuration": round(intro_seconds, 3),
    }
