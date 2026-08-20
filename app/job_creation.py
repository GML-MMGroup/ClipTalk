from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fastapi import HTTPException

from .editing_techniques import normalize_technique_policy
from .media import normalize_subtitle_style


SUPPORTED_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"})


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

    normalized_scope = str(search_scope_kind or "all").strip().lower()
    if normalized_scope not in {"all", "opening", "front_half", "middle", "back_half", "ending", "custom"}:
        raise HTTPException(400, "内容检索范围无效")
    scope_values: list[float | None] = []
    for raw in (search_scope_start, search_scope_end):
        if str(raw or "").strip() == "":
            scope_values.append(None)
            continue
        try:
            parsed_scope_value = float(raw)
        except (TypeError, ValueError) as error:
            raise HTTPException(400, "自定义检索时间格式无效") from error
        if not math.isfinite(parsed_scope_value) or parsed_scope_value < 0 or parsed_scope_value > 7200:
            raise HTTPException(400, "自定义检索时间必须在视频支持范围内")
        scope_values.append(parsed_scope_value)
    if normalized_scope == "custom" and (
        scope_values[0] is None or scope_values[1] is None or scope_values[1] <= scope_values[0]
    ):
        raise HTTPException(400, "自定义检索范围必须包含有效的开始和结束时间")
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
        parsed_variants = 3
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
    try:
        with destination.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > maximum_upload_bytes:
                    raise HTTPException(413, "视频超过上传大小限制")
                if used_storage_bytes + size > maximum_storage_bytes:
                    raise HTTPException(507, "上传后将超过项目存储上限，请先清理旧任务")
                digest.update(chunk)
                target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    if size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "上传的视频为空")
    try:
        expected_size = int(expected_size_bytes) if expected_size_bytes.strip() else None
    except ValueError as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "源文件大小信息无效，请重新选择视频") from error
    if expected_size is not None and expected_size > 0 and size != expected_size:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            400,
            f"视频上传不完整：原文件为 {expected_size} 字节，服务端只收到 {size} 字节。请检查网络后重新上传。",
        )
    return PersistedUpload(size=size, sha256=digest.hexdigest())
