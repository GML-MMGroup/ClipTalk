"""Versioned, JSON-only render inputs. Frozen at confirmation, never at execution."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from fastapi import HTTPException
from .subtitle_review import output_fingerprints

SPEC_VERSION = 1


def content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def freeze_spec(*, segments: list[dict], cutaways=None, chapters=None, technique_policy=None,
                text_layers=None, reframe=None, subtitle_mode="none", subtitle_style="clean",
                subtitle_draft=None) -> dict[str, Any]:
    if not segments:
        raise HTTPException(409, "缺少可复现的剪辑时间线")
    draft = copy.deepcopy(subtitle_draft) if subtitle_mode == "burn" else None
    if subtitle_mode == "burn":
        if not draft or draft.get("status") not in {"confirmed", "auto_reviewed"}:
            raise HTTPException(409, "字幕草稿尚未完成校对")
        if draft.get("sourceSubtitleAcknowledged") is False:
            raise HTTPException(409, "请先确认原视频字幕状态")
        if output_fingerprints([{"segments": segments}]) != list(draft.get("outputFingerprints") or []):
            raise HTTPException(409, "时间线范围、顺序或速度已变化，请重新校对字幕")
    value = {"schemaVersion": SPEC_VERSION, "segments": segments, "cutaways": cutaways or [],
             "chapters": chapters or [], "techniquePolicy": technique_policy or {},
             "textLayers": text_layers or [], "reframe": reframe,
             "subtitleMode": subtitle_mode, "subtitleStyle": subtitle_style, "subtitleDraft": draft}
    value = copy.deepcopy(value)
    return {**value, "hash": content_hash(value)}


def validate_spec(spec: dict) -> dict:
    if not isinstance(spec, dict) or spec.get("schemaVersion") != SPEC_VERSION:
        raise HTTPException(409, {"code": "export_confirmation_required", "message": "请重新生成样片并确认完整导出规格"})
    value = {key: value for key, value in spec.items() if key != "hash"}
    if spec.get("hash") != content_hash(value):
        raise HTTPException(409, "导出规格指纹不匹配，请重新确认")
    return copy.deepcopy(spec)


def output_spec(output: dict, version: dict, *, subtitle_mode: str, subtitle_style: str,
                subtitle_draft=None) -> dict:
    stored = output.get("renderSpec")
    if stored:
        base = validate_spec(stored)
    else:
        # Legacy overlays/canvas cannot be reconstructed from a boolean or count.
        text_layers = output.get("textLayers", version.get("textLayers"))
        reframe = output.get("reframe", version.get("reframe"))
        if ((output.get("overlayVerification") or {}).get("textLayerCount") and text_layers is None
                or (output.get("socialReframe") or version.get("socialReframe")) and not reframe):
            raise HTTPException(409, {"code": "export_confirmation_required", "message": "旧样片缺少文字或画幅规格，请重新生成预览"})
        base = {**output, "textLayers": text_layers or [], "reframe": reframe}
    return freeze_spec(segments=base.get("segments") or [], cutaways=base.get("cutaways"),
                       chapters=base.get("chapters"), technique_policy=base.get("techniquePolicy"),
                       text_layers=base.get("textLayers"), reframe=base.get("reframe"),
                       subtitle_mode=subtitle_mode, subtitle_style=subtitle_style, subtitle_draft=subtitle_draft)
