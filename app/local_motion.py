from __future__ import annotations

import html
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .media import probe_video


ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}


def motion_canvas_size(aspect: str) -> tuple[int, int]:
    return ASPECT_SIZES.get(str(aspect or "").strip(), ASPECT_SIZES["9:16"])


def build_motion_graphics_html(
    *,
    title: str,
    subtitle: str = "",
    label: str = "",
    aspect: str = "9:16",
    theme: str = "cliptalk",
) -> str:
    width, height = motion_canvas_size(aspect)
    safe_title = html.escape(title.strip()[:120] or "精彩内容")
    safe_subtitle = html.escape(subtitle.strip()[:220])
    safe_label = html.escape(label.strip()[:60] or "ClipTalk")
    warm = theme == "warm"
    accent = "#ff965d" if not warm else "#f0b15f"
    green = "#9fd3b0" if not warm else "#6a9f73"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
@font-face {{
  font-family: "NotoSC";
  src: url("../../static/fonts/noto-sans-sc-zh-700.woff2") format("woff2");
  font-weight: 700;
}}
@font-face {{
  font-family: "Inter";
  src: url("../../static/fonts/inter-variable.woff2") format("woff2");
}}
:root {{
  --progress: 0;
  --w: {width}px;
  --h: {height}px;
  --accent: {accent};
  --green: {green};
}}
* {{ box-sizing: border-box; }}
html, body {{
  width: var(--w);
  height: var(--h);
  margin: 0;
  overflow: hidden;
  background: #071013;
  color: #f7fbf8;
  font-family: Inter, NotoSC, system-ui, sans-serif;
}}
.canvas {{
  position: relative;
  width: 100%;
  height: 100%;
  padding: {max(54, int(height * 0.058))}px {max(46, int(width * 0.064))}px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background:
    radial-gradient(circle at calc(18% + var(--progress) * 18%) 14%, rgba(159, 211, 176, .24), transparent 30%),
    radial-gradient(circle at 88% 72%, rgba(255, 150, 93, .20), transparent 28%),
    linear-gradient(145deg, #081115 0%, #101d21 48%, #071013 100%);
}}
.canvas::before {{
  content: "";
  position: absolute;
  inset: 2.8%;
  border: 1.5px solid rgba(188, 220, 204, .28);
  border-radius: 32px;
  box-shadow: 0 0 60px rgba(88, 145, 120, .12) inset;
}}
.grid {{
  position: absolute;
  inset: 0;
  opacity: .18;
  background-image:
    linear-gradient(rgba(255,255,255,.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.08) 1px, transparent 1px);
  background-size: 72px 72px;
  transform: translateY(calc(var(--progress) * -34px));
}}
.label {{
  position: relative;
  align-self: flex-start;
  padding: 12px 18px;
  border: 1px solid rgba(255, 150, 93, .42);
  border-radius: 999px;
  color: var(--accent);
  font-size: {max(24, int(width * 0.026))}px;
  letter-spacing: .06em;
  text-transform: uppercase;
}}
.title {{
  position: relative;
  max-width: 92%;
  margin-top: auto;
  margin-bottom: 34px;
  font-family: NotoSC, Inter, sans-serif;
  font-size: {max(72, int(width * 0.112))}px;
  line-height: 1.02;
  letter-spacing: -.04em;
  text-shadow: 0 10px 46px rgba(0,0,0,.36);
  transform: translateY(calc((1 - var(--progress)) * 36px));
  opacity: clamp(.18, calc(var(--progress) * 1.5), 1);
}}
.subtitle {{
  position: relative;
  max-width: 82%;
  color: rgba(230, 241, 235, .78);
  font-size: {max(28, int(width * 0.038))}px;
  line-height: 1.35;
  margin-bottom: {max(64, int(height * 0.078))}px;
  opacity: clamp(.1, calc(var(--progress) * 1.25), 1);
}}
.bar {{
  position: absolute;
  left: 7%;
  right: 7%;
  bottom: 5%;
  height: 6px;
  border-radius: 999px;
  background: rgba(255,255,255,.12);
  overflow: hidden;
}}
.bar::after {{
  content: "";
  display: block;
  height: 100%;
  width: calc(var(--progress) * 100%);
  background: linear-gradient(90deg, var(--green), var(--accent));
}}
</style>
</head>
<body>
<main class="canvas">
  <div class="grid"></div>
  <div class="label">{safe_label}</div>
  <section>
    <h1 class="title">{safe_title}</h1>
    <p class="subtitle">{safe_subtitle}</p>
  </section>
  <div class="bar"></div>
</main>
</body>
</html>"""


def render_html_motion_video(
    *,
    html_path: Path,
    output_path: Path,
    frames_dir: Path,
    width: int,
    height: int,
    duration: float,
    fps: int,
    ffmpeg: str,
    renderer_script: Path,
) -> Path:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js 不可用，无法执行本地 HTML 动效渲染")
    frames_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            node,
            str(renderer_script),
            "--html",
            str(html_path),
            "--frames",
            str(frames_dir),
            "--width",
            str(width),
            "--height",
            str(height),
            "--duration",
            f"{duration:.3f}",
            "--fps",
            str(fps),
        ],
        check=True,
        timeout=max(120.0, duration * fps * 4.0),
    )
    temporary = output_path.with_suffix(".tmp.mp4")
    temporary.unlink(missing_ok=True)
    encoders = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    encoder = "libx264" if " libx264 " in encoders.stdout else "mpeg4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame-%06d.png"),
            "-t",
            f"{duration:.3f}",
            "-vf",
            f"scale={width}:{height}:flags=lanczos,format=yuv420p",
            "-c:v",
            encoder,
            "-b:v",
            "4M",
            "-movflags",
            "+faststart",
            str(temporary),
        ],
        check=True,
        timeout=max(120.0, duration * 20.0),
    )
    temporary.replace(output_path)
    return output_path


def _video_encoder(ffmpeg: str) -> str:
    encoders = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    return "libx264" if " libx264 " in encoders.stdout else "mpeg4"


def compose_motion_intro_video(
    *,
    intro_path: Path,
    source_path: Path,
    output_path: Path,
    ffmpeg: str,
    ffprobe: str,
) -> dict[str, Any]:
    """Prepend a local motion clip to a video without mutating the source."""
    intro = probe_video(intro_path, ffprobe)
    source = probe_video(source_path, ffprobe)
    width = max(2, int(source.width) // 2 * 2)
    height = max(2, int(source.height) // 2 * 2)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.stem}.{uuid.uuid4().hex}.tmp.mp4")
    temporary.unlink(missing_ok=True)
    intro_filter = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p[v0]"
    )
    source_filter = (
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p[v1]"
    )
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(intro_path), "-i", str(source_path),
    ]
    if source.has_audio:
        command.extend([
            "-f", "lavfi", "-t", f"{max(0.1, intro.duration):.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-filter_complex",
            f"{intro_filter};{source_filter};[1:a]aresample=48000[a1];"
            "[v0][2:a][v1][a1]concat=n=2:v=1:a=1[v][a]",
            "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k",
        ])
    else:
        command.extend([
            "-filter_complex", f"{intro_filter};{source_filter};[v0][v1]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-an",
        ])
    command.extend([
        "-c:v", _video_encoder(ffmpeg), "-b:v", "5M",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary),
    ])
    try:
        subprocess.run(command, check=True, timeout=max(300.0, (source.duration + intro.duration) * 10.0))
        rendered = probe_video(temporary, ffprobe)
        if rendered.duration < source.duration + intro.duration - .45:
            raise RuntimeError("动态图文片头成片时长校验失败")
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "duration": round(rendered.duration, 3),
        "width": rendered.width,
        "height": rendered.height,
        "hasAudio": rendered.has_audio,
        "introDuration": round(intro.duration, 3),
    }


def write_editing_draft_package(job: dict[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    edit_sessions = job.get("editSessions") or []
    timeline_exports = []
    if isinstance(edit_sessions, list):
        for session in edit_sessions:
            if not isinstance(session, dict):
                continue
            clips = [item for item in session.get("clips") or [] if isinstance(item, dict)]
            cursor = 0.0
            timeline = []
            for clip in clips:
                start = max(0.0, float(clip.get("sourceStart") or 0))
                end = max(start, float(clip.get("sourceEnd") or start))
                rate = max(0.05, float(clip.get("playbackRate") or 1))
                duration = max(0.0, (end - start) / rate)
                timeline.append({
                    "clipId": str(clip.get("id") or ""),
                    "title": str(clip.get("title") or ""),
                    "sourceStart": round(start, 3),
                    "sourceEnd": round(end, 3),
                    "outputStart": round(cursor, 3),
                    "outputEnd": round(cursor + duration, 3),
                    "playbackRate": round(rate, 4),
                })
                cursor += duration
            timeline_exports.append({
                "sessionId": str(session.get("id") or ""),
                "title": str(session.get("title") or ""),
                "duration": round(cursor, 3),
                "timeline": timeline,
                "textLayers": session.get("textLayers") or [],
                "cutaways": session.get("cutaways") or [],
            })
    payload = {
        "schemaVersion": "cliptalk-editing-draft-v1",
        "jobId": str(job.get("id") or ""),
        "source": {
            "filename": str(job.get("originalFilename") or job.get("filename") or ""),
            "sourceAssetId": str(job.get("sourceAssetId") or job.get("sourceHash") or ""),
            "duration": job.get("duration"),
            "videoInfo": job.get("videoInfo") or {},
        },
        "activeEditSessionId": str(job.get("activeEditSessionId") or ""),
        "editSessions": job.get("editSessions") or [],
        "timelines": timeline_exports,
        "outputVersions": job.get("outputVersions") or [],
        "coverVersions": job.get("coverVersions") or [],
        "notes": [
            "这是 ClipTalk 本地草稿包，不依赖外部 API。",
            "当 timelines 为空时，此包仅代表源素材草稿；需要先生成或确认时间线后才能映射为可编辑剪辑序列。",
            "如需导入剪映，需要再增加剪映草稿格式映射器；当前不直接写入本机剪映目录。",
        ],
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination
