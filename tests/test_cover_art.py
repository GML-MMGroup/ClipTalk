from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

import app.cover_art as cover_art
from app.cover_art import (
    COVER_SCORE_WEIGHTS,
    cover_sample_points,
    render_cover_variant,
    score_cover_frames,
)


def _frame(path: Path, *, color: tuple[int, int, int], accent: tuple[int, int, int]) -> Path:
    image = Image.new("RGB", (640, 360), color)
    draw = ImageDraw.Draw(image)
    draw.ellipse((220, 65, 420, 300), fill=accent)
    draw.rectangle((280, 130, 360, 250), fill=(245, 245, 240))
    image.save(path, "JPEG")
    return path


def test_cover_sample_points_prioritize_evidence_and_remain_diverse() -> None:
    points = cover_sample_points(60, [
        {"id": "event_a", "start": 8, "end": 14, "score": 95, "title": "关键反应"},
        {"id": "event_b", "start": 35, "end": 42, "score": 85, "title": "动作结果"},
    ], budget=8)

    assert 5 <= len(points) <= 8
    assert points == sorted(points, key=lambda item: item["time"])
    assert any("event_a" in item["evidenceRefs"] for item in points)
    assert any("event_b" in item["evidenceRefs"] for item in points)
    assert all(0 <= item["time"] < 60 for item in points)


def test_cover_scoring_suppresses_black_and_duplicate_frames(tmp_path: Path) -> None:
    first = _frame(tmp_path / "first.jpg", color=(35, 70, 110), accent=(230, 95, 40))
    duplicate = tmp_path / "duplicate.jpg"
    duplicate.write_bytes(first.read_bytes())
    distinct = _frame(tmp_path / "distinct.jpg", color=(120, 45, 30), accent=(35, 190, 120))
    black = tmp_path / "black.jpg"
    Image.new("RGB", (640, 360), "black").save(black, "JPEG")

    selected, rejected = score_cover_frames([
        {"id": "a", "path": first, "evidenceStrength": .9, "evidenceText": "关键人物反应"},
        {"id": "a2", "path": duplicate, "evidenceStrength": .8, "evidenceText": "关键人物反应"},
        {"id": "b", "path": distinct, "evidenceStrength": .75, "evidenceText": "动作结果"},
        {"id": "black", "path": black, "evidenceStrength": 1.0},
    ], request_focus="人物 反应", limit=8)

    assert {item["id"] for item in selected} == {"a", "b"}
    assert {item["rejectionReason"] for item in rejected} == {"black_frame", "duplicate"}
    for item in selected:
        assert item["score"]["total"] == sum(item["score"][key] for key in COVER_SCORE_WEIGHTS)
        assert 0 <= item["score"]["total"] <= 100


def test_person_cover_rejects_frames_without_a_detected_face(tmp_path: Path, monkeypatch) -> None:
    no_person = _frame(tmp_path / "car.jpg", color=(35, 70, 110), accent=(230, 95, 40))
    person = _frame(tmp_path / "person.jpg", color=(120, 45, 30), accent=(35, 190, 120))
    original = cover_art.inspect_cover_frame

    def inspect(path: Path):
        result = original(path)
        result["faceCount"] = 1 if path.name == "person.jpg" else 0
        return result

    monkeypatch.setattr(cover_art, "inspect_cover_frame", inspect)
    selected, rejected = score_cover_frames([
        {"id": "car", "path": no_person, "evidenceStrength": 1.0},
        {"id": "person", "path": person, "evidenceStrength": .8},
    ], require_person=True)

    assert [item["id"] for item in selected] == ["person"]
    assert any(item["id"] == "car" and item["rejectionReason"] == "missing_person" for item in rejected)


def test_cover_renderer_creates_three_ratio_correct_local_variants(tmp_path: Path) -> None:
    source = _frame(tmp_path / "source.jpg", color=(25, 60, 90), accent=(230, 120, 55))
    for direction in ("source_clean", "source_editorial", "source_cinematic"):
        output = tmp_path / f"{direction}.jpg"
        result = render_cover_variant(
            source, output, aspect="16:9", direction=direction, title="值得记住的关键一刻",
        )
        with Image.open(output) as rendered:
            assert rendered.size == (1280, 720)
        assert result["contentHash"].startswith("sha256:")
        assert result["direction"] == direction
