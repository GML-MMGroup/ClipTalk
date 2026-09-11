from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat


COVER_SCHEMA_VERSION = 1
COVER_SCORE_WEIGHTS = {
    "requestAlignment": 25,
    "subjectReadability": 20,
    "emotionOrAction": 20,
    "visualClarity": 15,
    "titleSafeSpace": 10,
    "distinctiveness": 10,
}
COVER_ASPECT_SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
}
COVER_DIRECTIONS = ("source_clean", "source_editorial", "source_cinematic")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _segment_range(segment: dict[str, Any]) -> tuple[float, float]:
    start = _number(segment.get("outputStart"), _number(segment.get("start")))
    end = _number(segment.get("outputEnd"), _number(segment.get("end"), start))
    if end <= start:
        duration = _number(segment.get("effectiveDuration"), _number(segment.get("duration")))
        end = start + max(0.0, duration)
    return start, end


def cover_sample_points(
    duration: float,
    evidence_segments: Iterable[dict[str, Any]] = (),
    *,
    budget: int = 16,
    include_uniform: bool = True,
) -> list[dict[str, Any]]:
    """Return diverse, deterministic cover timestamps with evidence references."""
    duration = max(0.0, float(duration or 0.0))
    budget = max(3, min(24, int(budget or 16)))
    if duration <= 0:
        return []
    points: list[dict[str, Any]] = []
    for position, raw in enumerate(evidence_segments):
        if not isinstance(raw, dict):
            continue
        start, end = _segment_range(raw)
        start = max(0.0, min(duration, start))
        end = max(start, min(duration, end))
        if end <= start:
            continue
        identity = str(
            raw.get("id") or raw.get("candidateId") or raw.get("groupId")
            or raw.get("semanticUnitId") or f"segment_{position + 1}"
        )
        strength = max(0.0, min(1.0, _number(
            raw.get("normalizedScore"), _number(raw.get("score"), 70.0) / 100.0,
        )))
        center = (start + end) / 2
        points.append({
            "time": center, "evidenceRefs": [identity], "evidenceStrength": strength,
            "evidenceText": " ".join(str(raw.get(key) or "") for key in (
                "title", "reason", "summary", "storyFunction", "emotionDirection",
            )).strip()[:500],
        })
        if end - start >= 5 and len(points) < budget:
            points.append({
                "time": start + (end - start) * .32,
                "evidenceRefs": [identity], "evidenceStrength": strength * .96,
                "evidenceText": str(raw.get("reason") or raw.get("title") or "")[:500],
            })
    if include_uniform:
        uniform_count = max(5, min(budget, math.ceil(duration / 12)))
        for index in range(uniform_count):
            fraction = (index + 1) / (uniform_count + 1)
            points.append({
                "time": duration * fraction, "evidenceRefs": [],
                "evidenceStrength": .35, "evidenceText": "",
            })
    points.sort(key=lambda item: (-float(item["evidenceStrength"]), float(item["time"])))
    selected: list[dict[str, Any]] = []
    minimum_gap = max(.35, min(2.0, duration / max(12, budget * 2)))
    for item in points:
        if any(abs(float(item["time"]) - float(existing["time"])) < minimum_gap for existing in selected):
            continue
        selected.append(item)
        if len(selected) >= budget:
            break
    return sorted(({
        **item, "time": round(max(0.0, min(duration - .001, float(item["time"]))), 3),
    } for item in selected), key=lambda item: float(item["time"]))


def _average_hash(image: Image.Image) -> str:
    compact = image.convert("RGB").resize((8, 8), Image.Resampling.LANCZOS)
    grayscale = ImageOps.grayscale(compact)
    pixels = list(grayscale.getdata())
    mean = sum(pixels) / max(1, len(pixels))
    value = sum((1 << index) for index, pixel in enumerate(pixels) if pixel >= mean)
    channel_means = ImageStat.Stat(compact).mean
    color_signature = "".join(f"{max(0, min(255, round(channel))):02x}" for channel in channel_means)
    return f"{value:016x}{color_signature}"


def _hash_distance(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 64


def inspect_cover_frame(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    preview = ImageOps.fit(image, (256, 144), method=Image.Resampling.LANCZOS)
    grayscale = ImageOps.grayscale(preview)
    statistics = ImageStat.Stat(grayscale)
    mean = float(statistics.mean[0])
    deviation = float(statistics.stddev[0])
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    edge_mean = float(ImageStat.Stat(edges).mean[0])
    width, height = grayscale.size
    center = grayscale.crop((width // 4, height // 5, width * 3 // 4, height * 4 // 5))
    center_edges = center.filter(ImageFilter.FIND_EDGES)
    center_energy = float(ImageStat.Stat(center_edges).mean[0])
    left_safe = grayscale.crop((0, 0, width * 2 // 5, height * 3 // 4))
    right_safe = grayscale.crop((width * 3 // 5, 0, width, height * 3 // 4))
    safe_deviation = min(
        float(ImageStat.Stat(left_safe).stddev[0]),
        float(ImageStat.Stat(right_safe).stddev[0]),
    )
    dark_ratio = sum(1 for value in grayscale.resize((64, 36)).getdata() if value < 18) / (64 * 36)
    return {
        "meanLuma": round(mean, 3),
        "lumaDeviation": round(deviation, 3),
        "edgeEnergy": round(edge_mean, 3),
        "centerEdgeEnergy": round(center_energy, 3),
        "darkRatio": round(dark_ratio, 4),
        "visualClarity": max(0.0, min(1.0, (edge_mean - 2.0) / 22.0))
        * max(.25, min(1.0, deviation / 45.0)),
        "subjectSalience": max(0.0, min(1.0, center_energy / max(5.0, edge_mean * 1.35))),
        "titleSafeSpace": max(0.0, min(1.0, 1.0 - safe_deviation / 70.0)),
        "blackFrame": dark_ratio >= .985 and mean <= 12,
        "perceptualHash": _average_hash(preview),
    }


def _semantic_action_signal(text: str) -> float:
    value = str(text or "").lower()
    tokens = (
        "高潮", "关键", "反应", "情绪", "笑", "惊", "动作", "冲突", "结果", "展示",
        "peak", "reaction", "emotion", "action", "result", "demonstration",
    )
    return min(1.0, sum(token in value for token in tokens) / 3.0)


def score_cover_frames(
    frames: Iterable[dict[str, Any]],
    *,
    request_focus: str = "",
    limit: int = 16,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Score extracted frames and greedily suppress perceptual duplicates."""
    scored: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    focus_tokens = [token for token in str(request_focus or "").lower().split() if len(token) >= 2]
    for raw in frames:
        item = dict(raw)
        metrics = inspect_cover_frame(Path(str(item["path"])))
        if metrics["blackFrame"]:
            rejected.append({**item, "rejectionReason": "black_frame", "metrics": metrics})
            continue
        evidence_strength = max(0.0, min(1.0, _number(item.get("evidenceStrength"), .35)))
        evidence_text = str(item.get("evidenceText") or "").lower()
        focus_match = (
            sum(token in evidence_text for token in focus_tokens) / len(focus_tokens)
            if focus_tokens else 0.0
        )
        action_signal = max(evidence_strength * .75, _semantic_action_signal(evidence_text))
        components = {
            "requestAlignment": round(25 * min(1.0, .42 + evidence_strength * .38 + focus_match * .2)),
            "subjectReadability": round(20 * (.35 + .65 * float(metrics["subjectSalience"]))),
            "emotionOrAction": round(20 * (.30 + .70 * action_signal)),
            "visualClarity": round(15 * float(metrics["visualClarity"])),
            "titleSafeSpace": round(10 * float(metrics["titleSafeSpace"])),
            "distinctiveness": 0,
        }
        item.update({"metrics": metrics, "score": components})
        scored.append(item)
    scored.sort(key=lambda item: sum(int(value) for value in item["score"].values()), reverse=True)
    selected: list[dict[str, Any]] = []
    selected_hashes: list[str] = []
    for item in scored:
        value_hash = str(item["metrics"]["perceptualHash"])
        distance = min((_hash_distance(value_hash, existing) for existing in selected_hashes), default=64)
        if distance < 5:
            rejected.append({**item, "rejectionReason": "duplicate"})
            continue
        distinctiveness = 10 if not selected_hashes else max(4, min(10, round(distance / 3.2)))
        item["score"]["distinctiveness"] = distinctiveness
        item["score"]["total"] = sum(
            int(item["score"][key]) for key in COVER_SCORE_WEIGHTS
        )
        item["score"]["weights"] = dict(COVER_SCORE_WEIGHTS)
        selected.append(item)
        selected_hashes.append(value_hash)
        if len(selected) >= max(3, min(24, int(limit or 16))):
            break
    selected.sort(key=lambda item: int(item["score"]["total"]), reverse=True)
    return selected, rejected


def _font(font_path: Path | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path and font_path.is_file():
        return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default(size=size)


def _wrap_title(draw: ImageDraw.ImageDraw, title: str, font: ImageFont.ImageFont, maximum: int) -> list[str]:
    value = " ".join(str(title or "").strip().split())[:80]
    if not value:
        return []
    words = value.split(" ") if " " in value else list(value)
    separator = " " if " " in value else ""
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current}{separator if current else ''}{word}"
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > maximum:
            lines.append(current)
            current = word
            if len(lines) == 2:
                break
        else:
            current = candidate
    if current and len(lines) < 2:
        lines.append(current)
    return lines[:2]


def render_cover_variant(
    source: Path,
    output: Path,
    *,
    aspect: str = "16:9",
    direction: str = "source_clean",
    title: str = "",
    font_path: Path | None = None,
) -> dict[str, Any]:
    if aspect not in COVER_ASPECT_SIZES:
        raise ValueError(f"不支持的封面比例：{aspect}")
    if direction not in COVER_DIRECTIONS:
        raise ValueError(f"不支持的封面方向：{direction}")
    width, height = COVER_ASPECT_SIZES[aspect]
    with Image.open(source) as opened:
        original = opened.convert("RGB")
    if direction == "source_editorial":
        canvas = ImageOps.fit(original, (width, height), method=Image.Resampling.LANCZOS)
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=max(10, min(width, height) // 40)))
        canvas = ImageEnhance.Brightness(canvas).enhance(.48)
        margin = max(24, round(min(width, height) * .055))
        foreground = ImageOps.contain(
            original, (width - margin * 2, height - margin * 2), Image.Resampling.LANCZOS,
        )
        x = (width - foreground.width) // 2
        y = (height - foreground.height) // 2
        canvas.paste(foreground, (x, y))
    else:
        # Preserve the entire source frame when the requested cover ratio is
        # different (especially landscape source -> portrait cover). Use a
        # blurred, darkened copy to fill the canvas and contain the original
        # frame above it instead of silently cropping visual information.
        canvas = ImageOps.fit(original, (width, height), method=Image.Resampling.LANCZOS)
        if original.width and original.height and abs((original.width / original.height) - (width / height)) > .02:
            canvas = canvas.filter(ImageFilter.GaussianBlur(radius=max(10, min(width, height) // 40)))
            canvas = ImageEnhance.Brightness(canvas).enhance(.5)
            foreground = ImageOps.contain(original, (width, height), Image.Resampling.LANCZOS)
            x = (width - foreground.width) // 2
            y = (height - foreground.height) // 2
            canvas.paste(foreground, (x, y))
    if direction == "source_cinematic":
        canvas = ImageEnhance.Contrast(canvas).enhance(1.16)
        canvas = ImageEnhance.Color(canvas).enhance(.92)
        overlay = Image.new("L", (width, height), 0)
        overlay_draw = ImageDraw.Draw(overlay)
        steps = 18
        for index in range(steps):
            inset_x = round(width * .018 * index)
            inset_y = round(height * .018 * index)
            shade = round(150 * (1 - index / steps) ** 2)
            overlay_draw.rectangle((inset_x, inset_y, width - inset_x, height - inset_y), outline=shade, width=max(2, round(min(width, height) * .02)))
        shadow = Image.new("RGB", (width, height), "black")
        canvas = Image.composite(shadow, canvas, overlay)
    title_lines: list[str] = []
    if title:
        draw = ImageDraw.Draw(canvas)
        font_size = max(32, round(min(width, height) * (.075 if aspect == "16:9" else .06)))
        title_font = _font(font_path, font_size)
        maximum_width = round(width * .72)
        title_lines = _wrap_title(draw, title, title_font, maximum_width)
        if title_lines:
            line_gap = round(font_size * .18)
            boxes = [draw.textbbox((0, 0), line, font=title_font, stroke_width=1) for line in title_lines]
            text_width = max(box[2] - box[0] for box in boxes)
            text_height = sum(box[3] - box[1] for box in boxes) + line_gap * (len(boxes) - 1)
            padding_x = round(font_size * .55)
            padding_y = round(font_size * .38)
            left = round(width * .075)
            top = round(height * .12)
            draw.rounded_rectangle(
                (left - padding_x, top - padding_y, left + text_width + padding_x, top + text_height + padding_y),
                radius=round(font_size * .24), fill=(5, 9, 12, 188),
            )
            cursor_y = top
            for line, box in zip(title_lines, boxes):
                draw.text(
                    (left, cursor_y), line, font=title_font, fill="white",
                    stroke_width=max(1, font_size // 28), stroke_fill=(0, 0, 0),
                )
                cursor_y += box[3] - box[1] + line_gap
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "JPEG", quality=92, optimize=True, progressive=True)
    return {
        "width": width, "height": height, "aspectRatio": aspect,
        "direction": direction, "titleLines": title_lines,
        "contentHash": "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest(),
    }
