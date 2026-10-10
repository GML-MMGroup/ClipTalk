"""Immutable delivery lineage and body-to-master time translation."""
from __future__ import annotations

import copy
import math


def intro_offset(output: dict) -> float:
    mapping = output.get("deliveryTimeMap") or {}
    if mapping.get("schemaVersion") == 1:
        value = float(mapping.get("bodyOffsetSeconds") or 0)
    else:
        cover, motion = output.get("coverIntro") or {}, output.get("motionIntro") or {}
        value = (float(cover.get("duration") or 0) if cover.get("enabled") else 0)
        value += float(motion.get("introDuration") or 0) if motion.get("enabled") else 0
    if not math.isfinite(value) or value < 0:
        raise ValueError("成片时间映射无效，请重新生成该版本")
    return value


def mapped_session(session: dict, output: dict) -> dict:
    """Use the frozen published timeline, never a subsequently edited session."""
    source = copy.deepcopy(output.get("deliveryTimeline") or session)
    offset = intro_offset(output)
    for item in source.get("schedule") or []:
        item["outputStart"] = round(float(item["outputStart"]) + offset, 6)
        item["outputEnd"] = round(float(item["outputEnd"]) + offset, 6)
    return source


def freeze_timeline(session: dict) -> dict:
    return copy.deepcopy({key: session[key] for key in
                          ("id", "revision", "contentBinding", "sourceSearchId", "clips", "schedule", "duration", "cutaways", "disabledCutawayIds")
                          if key in session})


def derive_lineage(source: dict, operation: str, *, prepend_seconds: float = 0) -> dict:
    """Carry frozen evidence through a transform that preserves body timing.

    Do not copy QC pass flags: changed pixels/audio need their own check. This
    helper is not valid for trims, speed changes or reordered clips.
    """
    prepend = float(prepend_seconds)
    if not math.isfinite(prepend) or prepend < 0:
        raise ValueError("新增片头时长无效")
    inherited = copy.deepcopy({key: source[key] for key in (
        "deliveryTimeline", "coverIntro", "motionIntro", "motionGraphics", "audioPolish",
        "subtitleCues", "subtitleDraftId", "subtitleMode", "sourceEditSessionId",
        "editSessionId", "sessionId",
    ) if key in source})
    inherited["deliveryTimeMap"] = {"schemaVersion": 1, "bodyOffsetSeconds": round(intro_offset(source) + prepend, 6)}
    inherited["deliveryOperations"] = [*copy.deepcopy(source.get("deliveryOperations") or []), {
        "operation": operation, "sourceFilename": str(source.get("filename") or ""),
        "parentVersionId": str(source.get("versionId") or ""), "prependSeconds": prepend,
    }]
    if operation != "export_delivery_master":
        inherited.update(qualityReport={}, qualityGate={}, reviewReport={},
                         qualityStatus="pending", reviewStatus="pending")
    if prepend:
        cover = inherited.get("coverIntro") or {}
        if cover.get("enabled"):
            cover["start"] = round(float(cover.get("start") or 0) + prepend, 6)
        for cue in inherited.get("subtitleCues") or []:
            cue["start"] = round(float(cue["start"]) + prepend, 6)
            cue["end"] = round(float(cue["end"]) + prepend, 6)
    return inherited


def cover_interval(source: dict) -> tuple[float, float]:
    """Only a recorded interval entirely before the body may be replaced."""
    cover = source.get("coverIntro") or {}
    if not cover.get("enabled"):
        return 0.0, 0.0
    start, duration = float(cover.get("start") or 0), float(cover.get("duration") or 0)
    if (not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0
            or start + duration > intro_offset(source) + .001):
        raise ValueError("已有封面时间记录无效，不能安全替换，原成片保持不变")
    return start, duration


def remap_subtitle_cues(cues: list, *, prepend_seconds: float = 0,
                       removed_start: float = 0, removed_duration: float = 0) -> list:
    """Translate output-time captions after a known removal and prepend."""
    if any(not math.isfinite(value) or value < 0 for value in
           (prepend_seconds, removed_start, removed_duration)):
        raise ValueError("字幕时间映射无效")
    def translated(value):
        point = float(value)
        if not math.isfinite(point) or point < 0:
            raise ValueError("字幕时间无效")
        return round(point - min(removed_duration, max(0, point - removed_start)) + prepend_seconds, 6)
    result = []
    for original in cues:
        cue = copy.deepcopy(original)
        cue["start"], cue["end"] = translated(cue["start"]), translated(cue["end"])
        if cue["end"] > cue["start"]:
            result.append(cue)
    return result


def replace_cover_lineage(source: dict, duration: float) -> dict:
    start, removed = cover_interval(source)
    body = copy.deepcopy(source)
    body.pop("coverIntro", None)
    body["deliveryTimeMap"] = {"schemaVersion": 1, "bodyOffsetSeconds": intro_offset(source) - removed}
    if "subtitleCues" in body:
        body["subtitleCues"] = remap_subtitle_cues(body["subtitleCues"], removed_start=start, removed_duration=removed)
    inherited = derive_lineage(body, "replace_cover_intro" if removed else "prepend_cover_intro", prepend_seconds=duration)
    inherited["deliveryOperations"][-1].update(removedStart=start, removedSeconds=removed)
    return inherited
