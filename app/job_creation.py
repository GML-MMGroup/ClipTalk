from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fastapi import HTTPException

from .editing_techniques import normalize_technique_policy
from .intent_router import (
    WORKFLOW_OPTIONS,
    IntentRoutingDecision,
    normalize_model_routing,
    route_editing_instruction,
)
from .media import normalize_subtitle_style

SUPPORTED_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"})
DEFAULT_HIGHLIGHT_VARIANT_COUNT = 3
DEFAULT_CONTENT_VARIANT_COUNT = 1


def infer_highlight_variant_count(instruction: str) -> int:
    """Infer an explicit cut count, otherwise keep the multi-cut product default."""
    text = str(instruction or "").strip()
    chinese_numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4}
    counter = r"(?:个|条|版|支)"
    between_count_and_kind = (
        r"(?:不同的?)?"
        r"(?:\s*\d+(?:\.\d+)?\s*(?:秒(?:钟)?|s|sec(?:onds?)?|分钟|分|min(?:utes?)?)\s*(?:的)?)?"
        r"(?:不同的?)?"
    )
    output_kind = (
        r"(?:高光(?:成片|视频|版本|方案|剪法|剪辑方案|短片|集锦|片段)?"
        r"|成片|视频|版本|方案|剪法|剪辑方案|短片|集锦)"
    )
    patterns = (
        rf"(?:生成|做成|剪成|制作|给我|输出|做).{{0,10}}?([1-4一二两三四])\s*{counter}{between_count_and_kind}{output_kind}",
        rf"([1-4一二两三四])\s*{counter}{between_count_and_kind}{output_kind}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1)
            return chinese_numbers.get(value, int(value) if value.isdigit() else DEFAULT_HIGHLIGHT_VARIANT_COUNT)
    return DEFAULT_HIGHLIGHT_VARIANT_COUNT


def infer_highlight_target_seconds(instruction: str) -> float | None:
    """Read an explicit final-video duration without confusing it with a source range."""
    text = str(instruction or "").strip()
    if not text:
        return None
    amount = r"(\d+(?:\.\d+)?)"
    unit = r"(秒|秒钟|s|sec(?:onds?)?|分钟|分|min(?:utes?)?)"
    patterns = (
        rf"{amount}\s*{unit}\s*(?:的)?\s*(?:高光|集锦|成片|短片|视频)",
        rf"(?:生成|做成|剪成|制作|成片时长|目标时长|控制在|压缩到).{{0,12}}?{amount}\s*{unit}",
        rf"(?:highlight|reel|final\s+video).{{0,12}}?{amount}\s*{unit}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        amount_start = match.start(1)
        source_context = text[max(0, amount_start - 8):amount_start]
        if re.search(r"(?:视频|素材|画面|内容)?\s*(?:前|后|从|第)\s*$", source_context):
            continue
        value = float(match.group(1))
        normalized_unit = str(match.group(2) or "").lower()
        if normalized_unit in {"分钟", "分", "min", "minute", "minutes"}:
            value *= 60
        if math.isfinite(value) and value >= 4:
            return value
    return None


def infer_result_strategy(instruction: str, task_mode: str) -> tuple[str, str]:
    """Return the task-appropriate delivery strategy and its provenance."""
    text = str(instruction or "").strip()
    if re.search(r"(?:先|需要|让我).{0,6}(?:审核|确认|选择)(?:候选|片段|结果)?|(?:不要|不用|无需).{0,5}(?:直接|自动)(?:生成|导出)", text):
        return "review", "instruction"
    if re.search(r"(?:直接|自动)(?:生成|合成|导出)|无需审核|不用审核", text):
        return "auto", "instruction"
    return ("review", "system_default") if task_mode == "content_extract" else ("smart", "system_default")


def resolve_creation_routing(
    instruction: str, *, intent_mode: str = "", task_mode: str = "auto",
    classifier: Callable[[str], Mapping[str, Any]] | None = None,
) -> IntentRoutingDecision:
    """Resolve the single-input product contract before persisting an upload."""
    normalized_instruction = str(instruction or "").strip()
    if len(normalized_instruction) > 500:
        raise HTTPException(400, "剪辑要求不能超过 500 字")
    requested_mode = intent_mode or task_mode
    explicit = route_editing_instruction(instruction, requested_mode)
    if explicit.source == "explicit":
        return explicit

    routing: IntentRoutingDecision | None = None
    model_error = ""
    if classifier is not None and normalized_instruction:
        try:
            predicted = classifier(str(instruction).strip())
            routing = normalize_model_routing(normalized_instruction, dict(predicted))
            if not routing.needs_confirmation:
                return routing
        except Exception as error:  # noqa: BLE001 - provider adapters expose heterogeneous errors
            model_error = str(error)[:240]

    if routing is None or routing.needs_confirmation or not routing.task_mode:
        recommendation = None if routing is None else {
            "workflowKind": routing.workflow_kind,
            "confidence": round(routing.confidence, 3),
            "reason": routing.reason,
            "source": routing.source,
        }
        raise HTTPException(409, detail={
            "code": "intent_confirmation_required",
            "message": (
                "请先用一句话描述你想得到的剪辑结果。"
                if not normalized_instruction else
                "AI 暂时不能可靠确定剪辑方式，请选择最接近你目标的一项。"
            ),
            "options": list(WORKFLOW_OPTIONS),
            "recommendation": recommendation,
            "modelError": model_error or None,
        })
    return routing


class AsyncUpload(Protocol):
    async def read(self, size: int = -1) -> bytes: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class JobCreationOptions:
    task_mode: str
    storage_mode: str
    instruction: str
    count: int | str
    total_seconds: float | None
    target_seconds: float | str
    theme: str
    analysis_mode: str
    recognition_profile: str
    subtitle_mode: str
    subtitle_style: str
    edit_mode: str
    structure: str
    auto_variant_count: int
    technique_policy: dict[str, Any]
    force_reanalyze: bool
    source_scope_kind: str
    source_scope_start: float | None
    source_scope_end: float | None
    result_strategy: str
    search_scope_kind: str
    search_scope_start: float | None
    search_scope_end: float | None
    search_result_limit: int
    search_boundary_mode: str
    content_auto_generate: bool
    content_exclusions: list[str]
    content_evidence_mode: str
    content_allowed_capabilities: list[str]
    suffix: str


@dataclass(frozen=True)
class PersistedUpload:
    size: int
    sha256: str


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def parse_job_creation_options(
    *, filename: str, task_mode: str, instruction: str, count: str,
    target_seconds: str, total_target_seconds: str, theme: str,
    analysis_mode: str, recognition_profile: str, force_reanalyze: str,
    subtitle_mode: str, subtitle_style: str, edit_mode: str, structure: str,
    auto_variant_count: str, technique_preset: str, allow_speed: str,
    allow_transitions: str, allow_audio_bridges: str, allow_cutaways: str,
    allow_silence_compression: str, allow_cold_open: str,
    source_scope_kind: str = "all", source_scope_start: str = "",
    source_scope_end: str = "", result_strategy: str = "smart",
    search_scope_kind: str = "all", search_scope_start: str = "",
    search_scope_end: str = "", search_result_limit: str = "12",
    search_boundary_mode: str = "complete", content_auto_generate: str = "false",
    content_exclusions: str = "", search_evidence_mode: str = "",
    search_allowed_capabilities: str = "", storage_mode: str = "editable",
) -> JobCreationOptions:
    normalized_task_mode = str(task_mode or "").strip().lower()
    if normalized_task_mode not in {"highlight", "content_extract"}:
        raise HTTPException(400, "任务模式无效")
    normalized_storage_mode = str(storage_mode or "editable").strip().lower()
    if normalized_storage_mode not in {"editable", "one_off"}:
        raise HTTPException(400, "任务存储方式无效")
    normalized_instruction = str(instruction or "").strip()
    if len(normalized_instruction) > 500:
        raise HTTPException(400, "内容描述不能超过 500 字")
    if normalized_task_mode == "content_extract" and not normalized_instruction:
        raise HTTPException(400, "请描述要从视频中截取的内容")

    parsed_count: int | str = "auto"
    if str(count or "auto").strip().lower() != "auto":
        try:
            parsed_count = int(count)
        except (TypeError, ValueError) as error:
            raise HTTPException(400, "高光数量格式无效") from error
        if parsed_count < 1 or parsed_count > 8:
            raise HTTPException(400, "事件上限必须为 1–8 个")

    target_value = str(total_target_seconds or "").strip() or str(target_seconds or "").strip()
    parsed_total: float | None = None
    if target_value and target_value.lower() != "auto":
        try:
            parsed_total = float(target_value)
        except ValueError as error:
            raise HTTPException(400, "单条成片目标时长格式无效") from error
        if not math.isfinite(parsed_total) or parsed_total < 4 or parsed_total > 86400:
            raise HTTPException(400, "单条成片目标时长必须大于等于 4 秒")

    if len(theme) > 500:
        raise HTTPException(400, "主题描述不能超过 500 字")
    normalized_analysis_mode = str(analysis_mode or "").strip().lower()
    if normalized_analysis_mode not in {"visual", "audiovisual"}:
        raise HTTPException(400, "分析信号模式无效")
    normalized_recognition = str(recognition_profile or "auto").strip().lower()
    if normalized_recognition not in {"auto", "balanced", "full"}:
        raise HTTPException(400, "内容识别档位无效")

    allowed_scopes = {"all", "opening", "front_half", "middle", "back_half", "ending", "custom"}

    def parse_scope(kind: str, start: str, end: str, label: str) -> tuple[str, list[float | None]]:
        normalized = str(kind or "all").strip().lower()
        if normalized not in allowed_scopes:
            raise HTTPException(400, f"{label}无效")
        values: list[float | None] = []
        for raw in (start, end):
            if str(raw or "").strip() == "":
                values.append(None)
                continue
            try:
                parsed = float(raw)
            except (TypeError, ValueError) as error:
                raise HTTPException(400, f"自定义{label}时间格式无效") from error
            if not math.isfinite(parsed) or parsed < 0 or parsed > 86400:
                raise HTTPException(400, f"自定义{label}时间必须在视频支持范围内")
            values.append(parsed)
        if normalized == "custom" and (
            values[0] is None or values[1] is None or values[1] <= values[0]
        ):
            raise HTTPException(400, f"自定义{label}必须包含有效的开始和结束时间")
        return normalized, values

    normalized_source_scope, source_scope_values = parse_scope(
        source_scope_kind, source_scope_start, source_scope_end, "素材范围",
    )
    normalized_scope, scope_values = parse_scope(
        search_scope_kind, search_scope_start, search_scope_end, "内容检索范围",
    )
    normalized_result_strategy = str(result_strategy or "smart").strip().lower()
    if normalized_result_strategy not in {"smart", "review", "auto"}:
        raise HTTPException(400, "结果策略无效")
    try:
        normalized_result_limit = int(search_result_limit)
    except (TypeError, ValueError) as error:
        raise HTTPException(400, "内容检索数量无效") from error
    if normalized_result_limit not in {1, 3, 12}:
        raise HTTPException(400, "内容检索数量只能为 1、3 或 12")
    normalized_boundary = str(search_boundary_mode or "complete").strip().lower()
    if normalized_boundary not in {"exact", "complete", "context"}:
        raise HTTPException(400, "内容片段边界方式无效")
    exclusions = list(dict.fromkeys(
        value.strip() for value in re.split(r"[，,、;；\n]+", str(content_exclusions or ""))
        if value.strip()
    ))[:20]
    normalized_evidence_mode = str(search_evidence_mode or "").strip().lower()
    if normalized_evidence_mode and normalized_evidence_mode not in {
        "speech", "screen_text", "visual", "person", "sound", "mixed",
    }:
        raise HTTPException(400, "内容检索证据类型无效")
    allowed_capabilities = list(dict.fromkeys(
        value.strip().lower() for value in re.split(
            r"[，,、;；\n]+", str(search_allowed_capabilities or "")
        ) if value.strip()
    ))
    if any(value not in {"speech", "visual", "ocr", "audio", "person"} for value in allowed_capabilities):
        raise HTTPException(400, "内容检索能力无效")

    normalized_subtitle = str(subtitle_mode or "").strip().lower()
    if normalized_subtitle not in {"ask", "burn", "none"}:
        normalized_subtitle = "none"
    normalized_edit_mode = str(edit_mode or "").strip().lower()
    if normalized_edit_mode not in {"ai_plan", "recommend_review", "manual"}:
        normalized_edit_mode = "ai_plan"
    normalized_structure = str(structure or "").strip().lower()
    if normalized_structure not in {"auto", "hook_story_result", "montage"}:
        normalized_structure = "auto"
    try:
        parsed_variants = int(auto_variant_count)
    except (TypeError, ValueError):
        parsed_variants = DEFAULT_HIGHLIGHT_VARIANT_COUNT
    if parsed_variants < 1 or parsed_variants > 4:
        raise HTTPException(400, "自动成片版本数量必须为 1–4")

    suffix = Path(filename or "video.mp4").suffix.lower()
    if suffix not in SUPPORTED_VIDEO_SUFFIXES:
        raise HTTPException(400, "仅支持 MP4、MOV、MKV、WebM、M4V 和 AVI 视频")
    return JobCreationOptions(
        task_mode=normalized_task_mode,
        storage_mode=normalized_storage_mode,
        instruction=normalized_instruction,
        count=parsed_count,
        total_seconds=parsed_total,
        target_seconds=parsed_total if parsed_total is not None else "auto",
        theme=theme,
        analysis_mode=normalized_analysis_mode,
        recognition_profile=normalized_recognition,
        subtitle_mode=normalized_subtitle,
        subtitle_style=normalize_subtitle_style(subtitle_style),
        edit_mode=normalized_edit_mode,
        structure=normalized_structure,
        auto_variant_count=parsed_variants,
        technique_policy=normalize_technique_policy({
            "preset": technique_preset,
            "allowSpeed": _truthy(allow_speed),
            "allowTransitions": _truthy(allow_transitions),
            "allowAudioBridges": _truthy(allow_audio_bridges),
            "allowCutaways": _truthy(allow_cutaways),
            "allowSilenceCompression": _truthy(allow_silence_compression),
            "allowColdOpen": _truthy(allow_cold_open),
            "maxSpeed": 1.5,
        }),
        force_reanalyze=str(force_reanalyze or "").strip().lower()
        not in {"0", "false", "no", "off", "reuse", "cached"},
        source_scope_kind=normalized_source_scope,
        source_scope_start=source_scope_values[0],
        source_scope_end=source_scope_values[1],
        result_strategy=normalized_result_strategy,
        search_scope_kind=normalized_scope,
        search_scope_start=scope_values[0],
        search_scope_end=scope_values[1],
        search_result_limit=normalized_result_limit,
        search_boundary_mode=normalized_boundary,
        content_auto_generate=_truthy(content_auto_generate),
        content_exclusions=exclusions,
        content_evidence_mode=normalized_evidence_mode,
        content_allowed_capabilities=allowed_capabilities,
        suffix=suffix,
    )


def storage_usage_bytes(data_root: Path) -> int:
    """Count physical files once even when duplicate uploads are hard-linked."""
    seen_inodes: set[tuple[int, int]] = set()
    used_storage = 0
    for existing_path in data_root.rglob("*"):
        try:
            stat = existing_path.stat()
        except OSError:
            continue
        key = (stat.st_dev, stat.st_ino)
        if existing_path.is_file() and key not in seen_inodes:
            seen_inodes.add(key)
            used_storage += stat.st_size
    return used_storage


async def persist_upload(
    upload: AsyncUpload, destination: Path, *, expected_size_bytes: str,
    used_storage_bytes: int, maximum_upload_bytes: int, maximum_storage_bytes: int,
) -> PersistedUpload:
    size = 0
    digest = hashlib.sha256()
    partial = destination.with_name(f".{destination.name}.part")
    try:
        with partial.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > maximum_upload_bytes:
                    raise HTTPException(413, "视频超过上传大小限制")
                if used_storage_bytes + size > maximum_storage_bytes:
                    raise HTTPException(507, "上传后将超过项目存储上限，请先清理旧任务")
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    if size == 0:
        partial.unlink(missing_ok=True)
        raise HTTPException(400, "上传的视频为空")
    try:
        expected_size = int(expected_size_bytes) if expected_size_bytes.strip() else None
    except ValueError as error:
        partial.unlink(missing_ok=True)
        raise HTTPException(400, "源文件大小信息无效，请重新选择视频") from error
    if expected_size is not None and expected_size > 0 and size != expected_size:
        partial.unlink(missing_ok=True)
        raise HTTPException(
            400,
            f"视频上传不完整：原文件为 {expected_size} 字节，服务端只收到 {size} 字节。请检查网络后重新上传。",
        )
    partial.replace(destination)
    return PersistedUpload(size=size, sha256=digest.hexdigest())
