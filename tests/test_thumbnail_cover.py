from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from app.media import MediaError, extract_first_frame


def _seek_second(command: list[str]) -> float:
    return float(command[command.index("-ss") + 1]) if "-ss" in command else 0.0


def test_thumbnail_uses_first_non_black_decodable_frame(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "cover.jpg"
    attempts: list[float] = []

    def fake_run(command: list[str], *, timeout: float = 0):
        second = _seek_second(command)
        attempts.append(second)
        color = (0, 0, 0) if second == 0 else (180, 90, 35)
        Image.new("RGB", (64, 36), color).save(Path(command[-1]), "JPEG")

    with patch("app.media._run", side_effect=fake_run):
        result = extract_first_frame(source, output, ffmpeg="ffmpeg")

    assert result == output
    assert output.is_file()
    assert attempts == [0.0, 0.5]


def test_thumbnail_reports_all_black_opening(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "cover.jpg"

    def fake_run(command: list[str], *, timeout: float = 0):
        Image.new("RGB", (64, 36), (0, 0, 0)).save(Path(command[-1]), "JPEG")

    with patch("app.media._run", side_effect=fake_run):
        with pytest.raises(MediaError, match="前 3 秒只有纯黑画面"):
            extract_first_frame(source, output, ffmpeg="ffmpeg")

    assert not output.exists()


def test_thumbnail_continues_after_decode_error(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "cover.jpg"

    def fake_run(command: list[str], *, timeout: float = 0):
        if _seek_second(command) < 1:
            raise MediaError("frame unavailable")
        Image.new("RGB", (64, 36), (40, 120, 200)).save(Path(command[-1]), "JPEG")

    with patch("app.media._run", side_effect=fake_run):
        extract_first_frame(source, output, ffmpeg="ffmpeg")

    assert output.is_file()
