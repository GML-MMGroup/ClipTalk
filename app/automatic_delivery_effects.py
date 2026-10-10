"""Reproducible full-quality effects for the core automatic delivery tool."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .local_motion import build_motion_graphics_html, motion_canvas_size, render_html_motion_video, compose_motion_intro_video
from .media import probe_video, _run_cancellable
from .delivery_contract import audio_filters


def delivery_effects(plan: dict) -> dict:
    brief = plan.get("brief") or {}
    effects = {}
    if plan.get("profile") == "audio-polish" or brief.get("audioPolishRequested"):
        effects["audio"] = brief.get("audioOperations") or {"noiseReduction": False, "voiceFirst": True}
    if plan.get("profile") == "local-motion" or brief.get("motionIntroRequested"):
        effects["motion"] = {
            "title": str(brief.get("graphicsText") or brief.get("coverTitle") or brief.get("retrievalQuery") or plan.get("goal") or "精彩内容")[:120],
            "subtitle": "", "aspect": str((brief.get("socialDelivery") or {}).get("aspect") or brief.get("coverAspect") or "9:16"),
            "duration": max(.5, min(8.0, float((brief.get("motionIntroDurationSeconds") if brief.get("motionIntroRequested") else brief.get("targetSeconds")) or 1.5))),
            "intro": bool(brief.get("motionIntroRequested")),
        }
    return effects


def apply_effects(runtime: Any, source: Path | None, target: Path, effects: dict, work: Path, guard) -> dict:
    """Never consume a review proxy. Caller freezes/validates the input master."""
    guard()
    ffmpeg, ffprobe = runtime.settings.ffmpeg, runtime.settings.ffprobe
    def cancelled():
        # The shared supervisor terminates the subprocess even if this guard
        # raises because the active plan/version changed, not just on Stop.
        guard()
        return False
    metadata = {}
    motion = effects.get("motion")
    if motion:
        root = work / "motion"
        root.mkdir(parents=True, exist_ok=True)
        html = root / "index.html"
        html.write_text(build_motion_graphics_html(title=motion["title"], subtitle=motion["subtitle"], aspect=motion["aspect"]), encoding="utf-8")
        width, height = motion_canvas_size(motion["aspect"])
        motion_path = target.with_name(target.stem + "-motion.mp4") if motion["intro"] else target
        render_html_motion_video(html_path=html, output_path=motion_path, frames_dir=root / "frames",
                                 width=width, height=height, duration=motion["duration"], fps=24, ffmpeg=ffmpeg,
                                 renderer_script=Path(__file__).resolve().parents[1] / "tools/render_html_motion.mjs", cancelled=cancelled)
        guard()
        metadata["motionGraphics"] = {"renderer": "html-playwright-ffmpeg", **motion}
        if motion["intro"]:
            if source is None:
                raise RuntimeError("没有选定可用于合成动态图文片头的正式视频")
            media = compose_motion_intro_video(intro_path=motion_path, source_path=source, output_path=target,
                                              ffmpeg=ffmpeg, ffprobe=ffprobe, cancelled=cancelled)
            metadata["motionIntro"] = {"enabled": True, "introDuration": media["introDuration"],
                                       "sourceFilename": source.name, "introFilename": motion_path.name}
        source = target
    if effects.get("audio"):
        if source is None:
            raise RuntimeError("音频优化缺少正式视频")
        info = probe_video(source, ffprobe)
        if not info.has_audio:
            raise RuntimeError("当前视频没有音轨，无法进行音频优化；原视频已保留")
        filters = audio_filters(effects["audio"])
        temporary = target.with_suffix(".audio.tmp.mp4")
        _run_cancellable([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", ",".join(filters),
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(temporary)],
                       cancelled=cancelled, timeout=max(180, info.duration * 3))
        guard()
        temporary.replace(target)
        metadata["audioPolish"] = effects["audio"]
    guard()
    info = probe_video(target, ffprobe)
    return {**metadata, "filename": target.name, "duration": info.duration,
            "width": info.width, "height": info.height, "hasAudio": info.has_audio}
