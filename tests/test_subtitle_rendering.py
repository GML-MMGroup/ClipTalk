from __future__ import annotations

import pytest
import subprocess
import tempfile
from pathlib import Path

from app.media import render_composition, subtitle_font_pixels, wrap_subtitle_text
from app.subtitle_review import normalize_layout, parse_style_command


def test_subtitle_size_uses_short_edge_for_portrait_and_landscape() -> None:
    assert subtitle_font_pixels(1920, 1080, .04) == pytest.approx(43.2)
    assert subtitle_font_pixels(576, 1024, .04) == pytest.approx(23.04)


def test_portrait_subtitle_wraps_to_safe_video_width() -> None:
    text = "说话人 B：到变化，我想到的是，刚上初中的时候，我的心态非常不稳，"
    maximum_units = 576 * .90 / subtitle_font_pixels(576, 1024, .04)
    wrapped = wrap_subtitle_text(text, maximum_units)
    assert "\n" in wrapped
    assert wrapped.replace("\n", "") == text


def test_pixel_size_command_uses_portrait_short_edge() -> None:
    result = parse_style_command(
        "字号 24px", normalize_layout(), frame_width=576, frame_height=1024,
    )
    assert result["style"]["fontSizeRatio"] == pytest.approx(24 / 576)


def test_portrait_drawtext_render_accepts_short_edge_expression_and_wrapping() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "portrait.mp4"
        output = root / "captioned.mp4"
        subprocess.run([
            "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:size=360x640:rate=25:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
        ], check=True)
        render_composition(
            source, output,
            segments=[{"id": "one", "start": 0, "end": 1, "transitionIn": {"type": "cut"}}],
            has_audio=False, ffmpeg="/usr/bin/ffmpeg",
            subtitle_path=root / "captions.ass",
            subtitle_cues=[{
                "id": "cue", "start": 0, "end": .9,
                "text": "这是一条足够长并且需要在竖屏安全宽度内自动换行的测试字幕",
                "speakerLabel": "说话人 B", "showSpeakerLabel": True,
            }],
            subtitle_layout={"fontSizeRatio": .04, "horizontal": "center", "vertical": "bottom"},
            subtitle_frame_width=360, subtitle_frame_height=640,
        )
        assert output.is_file()
        cue_text = (root / "captions.cues" / "0000.txt").read_text(encoding="utf-8")
        assert "\n" in cue_text
