from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

from .media import probe_video, render_composition
from .quality_gate import validate_edit_sequence


SUBTITLE_RENDER_VERSION = "short-edge-safe-width-v2"


def event_group_edl_hash(group: dict[str, Any]) -> str:
    payload = {
        "title": group.get("title"),
        "segments": [
            {
                "start": item.get("start"),
                "end": item.get("end"),
                "playbackRate": item.get("playbackRate", 1.0),
                "silenceCuts": item.get("silenceCuts"),
                "transitionIn": item.get("transitionIn"),
                "audioBridge": item.get("audioBridge"),
                "editOrder": item.get("editOrder"),
            }
            for item in group.get("segments", [])
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def composition_edl_hash(
    selections: list[dict[str, Any]],
    *,
    source_hash: str,
    output_mode: str,
    subtitle_mode: str,
    subtitle_style: str,
    variant_mode: str,
    variant_label: str,
    order_mode: str = "source",
    subtitle_draft_revision: str = "",
) -> str:
    payload = {
        "sourceHash": source_hash,
        "outputMode": output_mode,
        "subtitleMode": subtitle_mode,
        "variantMode": variant_mode,
        "variantLabel": variant_label,
        "orderMode": order_mode,
        "selections": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "segments": [
                    {
                        "id": segment.get("id"),
                        "start": segment.get("start"),
                        "end": segment.get("end"),
                        "role": segment.get("role"),
                        "playbackRate": segment.get("playbackRate", 1.0),
                        "silenceCuts": segment.get("silenceCuts"),
                        "transitionIn": segment.get("transitionIn"),
                        "audioBridge": segment.get("audioBridge"),
                        "editOrder": segment.get("editOrder"),
                    }
                    for segment in item.get("segments", [])
                ],
            }
            for item in selections
        ],
        "cutaways": [cutaway for item in selections for cutaway in (item.get("cutaways") or [])],
        "techniquePolicy": [item.get("techniquePolicy") for item in selections],
    }
    if subtitle_mode == "burn":
        payload["subtitleStyle"] = subtitle_style
        payload["subtitleDraftRevision"] = subtitle_draft_revision
        payload["subtitleRenderVersion"] = SUBTITLE_RENDER_VERSION
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def validate_render_selections(
    selections: list[dict[str, Any]],
    *,
    editing_intent: dict[str, Any] | None,
    target_seconds: Any = None,
    automatic: bool = False,
) -> list[dict[str, Any]]:
    """Apply the final deterministic quality gate before FFmpeg starts."""

    try:
        requested_target = (
            float(target_seconds) if target_seconds not in (None, "", "auto") else None
        )
    except (TypeError, ValueError):
        requested_target = None
    for selection in selections:
        optimization = selection.get("edlOptimization")
        optimization = optimization if isinstance(optimization, dict) else {}
        quality = optimization.get("qualityReport")
        quality = quality if isinstance(quality, dict) else {}
        checks = quality.get("checks")
        checks = checks if isinstance(checks, dict) else {}
        intent_check = quality.get("userIntent")
        intent_check = intent_check if isinstance(intent_check, dict) else {}
        segments = list(selection.get("segments") or [])
        if not segments:
            raise RuntimeError("所选内容在应用用户排除条件后没有可生成的镜头")
        if checks.get("semanticBoundaries") is False or intent_check.get("unsafeSpeechSegmentIds"):
            raise RuntimeError("成片计划仍存在可能截断的对白，已停止渲染并要求重新规划安全边界")
        if intent_check.get("excludedMatches"):
            raise RuntimeError("成片计划包含用户明确要求排除的内容，已停止渲染")
        if intent_check.get("missingIncludeRules") or intent_check.get("missingSpeakers"):
            raise RuntimeError("成片计划尚未覆盖用户明确要求保留的内容，已停止渲染并要求重新规划")
        sequence_validation = validate_edit_sequence(
            segments,
            editing_intent=editing_intent or {},
            target_seconds=requested_target if automatic else None,
            insufficient_evidence=bool(selection.get("durationInsufficientEvidence")),
            require_verified_uncertainty=False,
        )
        selection["sequenceValidation"] = sequence_validation
        blocking_issues = [
            item
            for item in sequence_validation.get("issues") or []
            if item.get("severity") == "critical"
        ]
        duration_outside_target = sequence_validation.get("durationPreferred") is False
        if automatic and (
            not sequence_validation.get("passed")
            or duration_outside_target
            or blocking_issues
        ):
            duration_issue = next((
                item for item in sequence_validation.get("issues") or []
                if str(item.get("category") or "").startswith("duration")
            ), None)
            top = str(((duration_issue or (blocking_issues[0] if blocking_issues else {}))).get("description") or "")
            raise RuntimeError(
                f"自动成片未通过渲染前质量门：{top or '镜头边界、章节关系或目标时长不安全'}；已停止渲染并返回重新选片"
            )
    return selections


class CompositionPreviewPaths:
    @staticmethod
    def event_preview(job: dict[str, Any], group: dict[str, Any]) -> Path:
        group_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(group.get("id") or "event"))[:96] or "event"
        return (
            Path(job["workDirectory"])
            / "event-previews"
            / f"{group_id}-{event_group_edl_hash(group)}.mp4"
        )


class CompositionPreviewService:
    """Generate immutable event-group review previews from their EDL."""

    def __init__(
        self,
        *,
        ffmpeg: str,
        ffprobe: str,
        generation_lock: threading.Lock | threading.RLock,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.generation_lock = generation_lock

    def prepare_event_preview(self, job: dict[str, Any], group: dict[str, Any]) -> Path:
        if not list(group.get("segments") or []):
            raise ValueError("事件高光没有可预览镜头")
        output = CompositionPreviewPaths.event_preview(job, group)
        if output.is_file():
            return output
        source = Path(job["sourcePath"])
        if not source.is_file():
            raise FileNotFoundError("源视频不存在")
        with self.generation_lock:
            if output.is_file():
                return output
            info = probe_video(source, self.ffprobe)
            render_composition(
                source,
                output,
                segments=list(group.get("segments") or []),
                has_audio=info.has_audio,
                ffmpeg=self.ffmpeg,
                preview_width=960,
            )
        return output
