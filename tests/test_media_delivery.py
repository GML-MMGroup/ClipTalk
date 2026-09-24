from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from app.media import analyze_rendered_media, create_social_reframe_preview, probe_video


FFMPEG = "/usr/bin/ffmpeg"
FFPROBE = "/usr/bin/ffprobe"


def make_video(path: Path, *, black: bool = False, audio: bool = False) -> None:
    video_source = (
        "color=c=black:size=640x360:rate=30:duration=1"
        if black else "testsrc2=size=640x360:rate=30:duration=1"
    )
    command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", video_source]
    if audio:
        command.extend(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1"])
    command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
    if audio:
        command.extend(["-c:a", "aac", "-shortest"])
    else:
        command.append("-an")
    command.extend(["-y", str(path)])
    subprocess.run(command, check=True)


def test_social_reframe_creates_new_vertical_preview_with_audio() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.mp4"
        output = root / "vertical.mp4"
        make_video(source, audio=True)
        original_size = source.stat().st_size

        rendered = create_social_reframe_preview(
            source, output, aspect="9:16", fit="crop", focus_x=.5, focus_y=.5,
            has_audio=True, ffmpeg=FFMPEG, ffprobe=FFPROBE,
        )

        assert (rendered.width, rendered.height) == (540, 960)
        assert rendered.has_audio is True
        assert output.is_file()
        assert source.stat().st_size == original_size


@pytest.mark.parametrize(
    ("aspect", "expected_size"),
    (("9:16", (540, 960)), ("4:5", (576, 720)), ("1:1", (720, 720)), ("16:9", (960, 540))),
)
def test_social_reframe_preserves_landscape_with_a_blurred_background_at_every_aspect(
    aspect: str,
    expected_size: tuple[int, int],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.mp4"
        output = root / f"{aspect.replace(':', 'x')}-blur.mp4"
        make_video(source, audio=True)

        rendered = create_social_reframe_preview(
            source, output, aspect=aspect, fit="blur", focus_x=.5, focus_y=.5,
            has_audio=True, ffmpeg=FFMPEG, ffprobe=FFPROBE,
        )

        assert (rendered.width, rendered.height) == expected_size
        assert rendered.has_audio is True
        assert output.is_file()


def test_delivery_qc_reports_clean_decodable_video() -> None:
    with tempfile.TemporaryDirectory() as directory:
        video = Path(directory) / "clean.mp4"
        make_video(video)
        info = probe_video(video, FFPROBE)

        report = analyze_rendered_media(
            video, ffmpeg=FFMPEG, ffprobe=FFPROBE,
            expected_duration=info.duration, expect_audio=False,
        )

        assert report["passed"] is True
        assert report["media"]["width"] == 640
        assert report["issues"] == []


def test_delivery_qc_keeps_intentional_black_as_reviewable_warning() -> None:
    with tempfile.TemporaryDirectory() as directory:
        video = Path(directory) / "black.mp4"
        make_video(video, black=True)

        report = analyze_rendered_media(video, ffmpeg=FFMPEG, ffprobe=FFPROBE)

        assert report["passed"] is True
        assert any(issue["code"] == "black_frames" for issue in report["issues"])
