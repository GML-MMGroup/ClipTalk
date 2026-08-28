from __future__ import annotations

import copy
import difflib
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUBTITLE_PRESETS: dict[str, dict[str, Any]] = {
    "clean": {
        "preset": "clean", "fontSizeRatio": .040,
        "horizontal": "center", "vertical": "bottom",
        "offsetXRatio": 0.0, "offsetYRatio": 0.0,
    },
    "bold": {
        "preset": "bold", "fontSizeRatio": .046,
        "horizontal": "center", "vertical": "bottom",
        "offsetXRatio": 0.0, "offsetYRatio": -.012,
    },
    "social": {
        "preset": "social", "fontSizeRatio": .052,
        "horizontal": "center", "vertical": "bottom",
        "offsetXRatio": 0.0, "offsetYRatio": -.035,
    },
}

_DRAFT_ID = re.compile(r"^sub_[a-f0-9]{16,40}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_layout(value: Any = None, preset: str = "clean") -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    preset_name = str(raw.get("preset") or preset or "clean").strip().lower()
    if preset_name not in SUBTITLE_PRESETS:
        preset_name = "clean"
    result = copy.deepcopy(SUBTITLE_PRESETS[preset_name])
    horizontal = str(raw.get("horizontal") or result["horizontal"]).lower()
    vertical = str(raw.get("vertical") or result["vertical"]).lower()
    result["horizontal"] = horizontal if horizontal in {"left", "center", "right"} else "center"
    result["vertical"] = vertical if vertical in {"top", "middle", "bottom"} else "bottom"
    for key, low, high in (
        ("fontSizeRatio", .012, .080),
        ("offsetXRatio", -.40, .40),
        ("offsetYRatio", -.40, .40),
    ):
        try:
            result[key] = max(low, min(high, float(raw.get(key, result[key]))))
        except (TypeError, ValueError):
            pass
    return result


def normalize_segments(outputs: Any) -> list[list[dict[str, Any]]]:
    normalized: list[list[dict[str, Any]]] = []
    if not isinstance(outputs, list):
        return normalized
    for output in outputs:
        source = output.get("segments") if isinstance(output, dict) else None
        if not isinstance(source, list):
            source = []
        segments: list[dict[str, Any]] = []
        for segment in source:
            if not isinstance(segment, dict):
                continue
            try:
                start = round(max(0.0, float(segment.get("start") or 0)), 3)
                end = round(float(segment.get("end") or 0), 3)
            except (TypeError, ValueError):
                continue
            if end - start < .08:
                continue
            pieces = []
            for piece in segment.get("silenceCuts") or []:
                if not isinstance(piece, dict):
                    continue
                try:
                    piece_start = round(float(piece.get("start") or 0), 3)
                    piece_end = round(float(piece.get("end") or 0), 3)
                except (TypeError, ValueError):
                    continue
                if piece_end > piece_start:
                    pieces.append({"start": piece_start, "end": piece_end})
            transition = segment.get("transitionIn") if isinstance(segment.get("transitionIn"), dict) else {}
            transition_type = str(transition.get("type") or "cut").lower()
            if transition_type not in {"cut", "dissolve", "fade_black"}:
                transition_type = "cut"
            try:
                transition_duration = round(max(0.0, float(transition.get("duration") or 0)), 3)
            except (TypeError, ValueError):
                transition_duration = 0.0
            segments.append({
                "start": start,
                "end": end,
                "playbackRate": round(float(segment.get("playbackRate") or 1), 3),
                "silenceCuts": pieces,
                "transitionIn": {"type": transition_type, "duration": transition_duration},
            })
        normalized.append(segments)
    return normalized


def output_fingerprints(outputs: Any) -> list[str]:
    values = []
    for segments in normalize_segments(outputs):
        encoded = json.dumps(segments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        values.append(hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24])
    return values


def draft_directory(work_directory: str | Path) -> Path:
    path = Path(work_directory) / "subtitle-drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def draft_path(work_directory: str | Path, draft_id: str) -> Path:
    if not _DRAFT_ID.fullmatch(str(draft_id or "")):
        raise ValueError("字幕草稿编号无效")
    return draft_directory(work_directory) / f"{draft_id}.json"


def load_draft(work_directory: str | Path, draft_id: str) -> dict[str, Any] | None:
    path = draft_path(work_directory, draft_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def save_draft(work_directory: str | Path, draft: dict[str, Any]) -> dict[str, Any]:
    path = draft_path(work_directory, str(draft.get("id") or ""))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return draft


def validate_cues(cues: Any, output_count: int) -> list[dict[str, Any]]:
    if not isinstance(cues, list) or len(cues) > 1000:
        raise ValueError("字幕条目无效或数量过多")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise ValueError(f"第 {position + 1} 条字幕无效")
        cue_id = str(cue.get("id") or "")
        if not cue_id or cue_id in seen:
            raise ValueError("字幕编号缺失或重复")
        seen.add(cue_id)
        text = str(cue.get("text") or "").strip()
        if len(text) > 500:
            raise ValueError(f"第 {position + 1} 条字幕超过 500 字")
        try:
            output_index = int(cue.get("outputIndex") or 0)
            start = round(max(0.0, float(cue.get("start") or 0)), 3)
            end = round(float(cue.get("end") or 0), 3)
        except (TypeError, ValueError) as error:
            raise ValueError(f"第 {position + 1} 条字幕时间无效") from error
        if output_index < 0 or output_index >= max(1, output_count):
            raise ValueError(f"第 {position + 1} 条字幕所属成片无效")
        if end - start < .08:
            raise ValueError(f"第 {position + 1} 条字幕结束时间必须晚于开始时间")
        result.append({
            **cue,
            "id": cue_id,
            "outputIndex": output_index,
            "start": start,
            "end": end,
            "text": text,
            "originalText": str(cue.get("originalText") or text),
            "suggestionStatus": str(cue.get("suggestionStatus") or "none"),
        })
    for output_index in range(max(1, output_count)):
        ordered = sorted((cue for cue in result if cue["outputIndex"] == output_index), key=lambda cue: cue["start"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["start"] < previous["end"] - .02:
                raise ValueError("同一成片中的字幕时间不能重叠")
    return result


def has_pending_suggestions(draft: dict[str, Any]) -> bool:
    return any(str(cue.get("suggestionStatus") or "") == "pending" for cue in draft.get("cues") or [])


_SUBTITLE_PUNCTUATION = re.compile(r"[\s，。！？；：、,.!?;:'\"“”‘’（）()《》〈〉【】\[\]—…·-]+")


def normalize_correction_profile(value: Any) -> dict[str, Any]:
    """Keep the global LLM context useful without treating it as ground truth."""
    raw = value if isinstance(value, dict) else {}
    terms: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("terms") or []:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or item.get("canonical") or "").strip()[:80]
        key = re.sub(r"\s+", "", term).casefold()
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        sources = [
            str(source)[:40] for source in item.get("sources") or []
            if str(source) in {"transcript_repeat", "screen_text", "filename", "context"}
        ]
        terms.append({
            "term": term,
            "variants": [str(variant).strip()[:80] for variant in item.get("variants") or [] if str(variant).strip()][:8],
            "confidence": round(confidence, 3),
            "sources": list(dict.fromkeys(sources)),
            "evidence": str(item.get("evidence") or "")[:240],
        })
        if len(terms) >= 32:
            break
    return {
        "summary": str(raw.get("summary") or "")[:500],
        "terms": terms,
        "uncertainTerms": [str(item).strip()[:80] for item in raw.get("uncertainTerms") or [] if str(item).strip()][:24],
    }


def evaluate_subtitle_suggestion(cue: dict[str, Any], item: Any) -> dict[str, Any] | None:
    """Validate a text-only correction and assign risk independently of the LLM."""
    if not isinstance(item, dict):
        return None
    original = str(cue.get("text") or "").strip()
    proposed = str(item.get("text") or "").strip()
    if not original or not proposed or proposed == original or len(proposed) > 500:
        return None
    original_plain = _SUBTITLE_PUNCTUATION.sub("", original)
    proposed_plain = _SUBTITLE_PUNCTUATION.sub("", proposed)
    similarity = difflib.SequenceMatcher(None, original_plain.casefold(), proposed_plain.casefold()).ratio()
    length_delta = abs(len(proposed_plain) - len(original_plain))
    # A subtitle checker may repair recognition, not paraphrase or invent a sentence.
    if similarity < .56 or length_delta > max(8, math.ceil(len(original_plain) * .45)):
        return None
    try:
        confidence = max(0.0, min(1.0, float(item.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    digits_changed = re.findall(r"\d+(?:\.\d+)?", original) != re.findall(r"\d+(?:\.\d+)?", proposed)
    latin_changed = [value.casefold() for value in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", original)] != [
        value.casefold() for value in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", proposed)
    ]
    punctuation_only = original_plain == proposed_plain
    changed_size = max(len(original_plain), len(proposed_plain)) * (1 - similarity)
    if digits_changed or latin_changed:
        risk = "high"
    elif punctuation_only or (confidence >= .9 and similarity >= .72 and changed_size <= max(2, len(original_plain) * .18)):
        risk = "low"
    else:
        risk = "medium"
    evidence = [str(value).strip()[:180] for value in item.get("evidence") or [] if str(value).strip()][:6]
    return {
        "suggestedText": proposed,
        "suggestionReason": str(item.get("reason") or "根据完整逐字稿发现可能的识别问题")[:300],
        "suggestionConfidence": round(confidence, 3),
        "suggestionStatus": "pending",
        "suggestionBasis": "global_context_and_local_cues",
        "suggestionRisk": risk,
        "suggestionEvidence": evidence,
        "suggestionMetrics": {
            "similarity": round(similarity, 3),
            "digitsChanged": digits_changed,
            "latinTermsChanged": latin_changed,
        },
    }


def parse_style_command(
    command: str,
    current_style: dict[str, Any],
    *,
    cue_id: str | None = None,
    frame_width: float | None = None,
    frame_height: float = 1080,
) -> dict[str, Any]:
    text = str(command or "").strip().lower()
    if not text:
        raise ValueError("请输入字号或位置调整命令")
    style = normalize_layout(current_style)
    explicit_cue = bool(re.search(r"(这条|当前(?:这)?条|本条|this cue|current cue)", text))
    scope = "cue" if cue_id and explicit_cue else "global"
    changes: list[str] = []

    preset_match = re.search(r"(?:样式|风格|preset)\s*(?:改成|设为|用|:)?\s*(clean|bold|social|清爽|醒目|社交)", text)
    if preset_match:
        preset_map = {"清爽": "clean", "醒目": "bold", "社交": "social"}
        preset = preset_map.get(preset_match.group(1), preset_match.group(1))
        style = normalize_layout(SUBTITLE_PRESETS[preset])
        changes.append(f"样式改为 {preset}")

    percent_size = re.search(r"(?:字号|字体(?:大小)?)\s*(?:改成|设为|调到|为|:)?\s*(\d+(?:\.\d+)?)\s*%", text)
    pixel_size = re.search(r"(?:字号|字体(?:大小)?)\s*(?:改成|设为|调到|为|:)?\s*(\d+(?:\.\d+)?)\s*(?:px|像素|号)?", text)
    if percent_size:
        style["fontSizeRatio"] = max(.012, min(.080, float(percent_size.group(1)) / 100))
        changes.append(f"字号设为画面短边的 {style['fontSizeRatio'] * 100:.1f}%")
    elif pixel_size:
        pixels = float(pixel_size.group(1))
        short_edge = min(float(frame_width or frame_height), float(frame_height))
        style["fontSizeRatio"] = max(.012, min(.080, pixels / max(1.0, short_edge)))
        changes.append(f"字号设为约 {pixels:.0f}px")
    elif re.search(r"(更大|放大|调大|大一点|bigger|larger)", text):
        style["fontSizeRatio"] = min(.080, style["fontSizeRatio"] * 1.1)
        changes.append("字号增大 10%")
    elif re.search(r"(更小|缩小|调小|小一点|smaller)", text):
        style["fontSizeRatio"] = max(.012, style["fontSizeRatio"] / 1.1)
        changes.append("字号减小约 10%")

    if re.search(r"(左上|top.?left)", text):
        style.update(horizontal="left", vertical="top"); changes.append("移动到左上")
    elif re.search(r"(右上|top.?right)", text):
        style.update(horizontal="right", vertical="top"); changes.append("移动到右上")
    elif re.search(r"(左下|bottom.?left)", text):
        style.update(horizontal="left", vertical="bottom"); changes.append("移动到左下")
    elif re.search(r"(右下|bottom.?right)", text):
        style.update(horizontal="right", vertical="bottom"); changes.append("移动到右下")
    elif re.search(r"(顶部|上方|置顶|top)", text):
        style["vertical"] = "top"; changes.append("移动到顶部")
    elif re.search(r"(正中|居中位置|画面中央|middle)", text):
        style.update(horizontal="center", vertical="middle"); changes.append("移动到画面中央")
    elif re.search(r"(底部|下方|置底|bottom)", text):
        style["vertical"] = "bottom"; changes.append("移动到底部")
    elif re.search(r"(靠左|左对齐|align left)", text):
        style["horizontal"] = "left"; changes.append("左对齐")
    elif re.search(r"(靠右|右对齐|align right)", text):
        style["horizontal"] = "right"; changes.append("右对齐")
    elif re.search(r"(水平居中|center)", text):
        style["horizontal"] = "center"; changes.append("水平居中")

    shift = re.search(r"(?:整体|全部|所有字幕)?\s*(?:向|往)?(上|下|左|右)\s*(?:移动|移|挪|偏移|调)?\s*(\d+(?:\.\d+)?)\s*(%|px|像素)?", text)
    if shift:
        direction, amount_text, unit = shift.groups()
        amount = float(amount_text)
        ratio = amount / 100 if unit == "%" else amount / max(1.0, frame_height)
        if direction in {"上", "下"}:
            style["offsetYRatio"] += -ratio if direction == "上" else ratio
        else:
            style["offsetXRatio"] += -ratio if direction == "左" else ratio
        changes.append(f"向{direction}偏移 {amount:g}{unit or 'px'}")

    style = normalize_layout(style)
    if not changes:
        raise ValueError("暂时没理解这条命令。可尝试“字号 48px”“整体上移 5%”或“当前这条放到左上”。")
    return {
        "scope": scope,
        "cueId": cue_id if scope == "cue" else None,
        "style": style,
        "summary": "；".join(changes),
        "safeArea": .05,
    }
