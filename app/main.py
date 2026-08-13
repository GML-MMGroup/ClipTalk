from __future__ import annotations

import json
import hashlib
import copy
import math
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .ark_client import AnthropicCompatibleClient, VisionRequestError, create_vision_client, vision_provider_label
from .config import Settings
from .vision_settings import (
    LLM_PROVIDER_DEFINITIONS,
    LlmConfigurationStore,
    VisionConfigurationStore,
    discover_llm_models,
    discover_models,
    llm_provider_label,
)
from .event_groups import (
    allocate_event_group_budget,
    build_final_reel,
    composition_duration,
    event_groups_total,
    legacy_candidates_to_event_groups,
    recalculate_event_group,
)
from .edit_boundaries import load_transcript_segments, semantic_safe_range
from .edl_optimizer import optimize_edl
from .pipeline import (
    ANALYSIS_CACHE_VERSION,
    HighlightPipeline,
    ModelDecisionRequired,
    coarse_frame_limit,
    load_analysis_checkpoint,
)
from .prompts import BRIEF_PROMPT_VERSION, EDIT_PLAN_PROMPT_VERSION, PROMPT_VERSION, COMMON_SYSTEM_PROMPT, llm_edit_plan_prompt, llm_order_prompt, user_brief_prompt
from .speech import launch_sensevoice_worker, sensevoice_status
from .store import JobStore
from .media import (
    SampledFrame,
    create_timeline_thumbnail_sprite,
    create_preview_proxy,
    create_webm_preview,
    detect_scene_changes,
    detect_silence_intervals,
    extract_audio_waveform,
    silence_intervals_from_waveform,
    extract_first_frame,
    probe_video,
    render_clip,
    render_composition,
    normalize_subtitle_style,
    validate_rendered_clip,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_highlight_filename(title: str, position: int) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", title).strip(" .-")
    cleaned = re.sub(r"\s+", "_", cleaned)[:60] or "highlight"
    return f"{position:02d}-{cleaned}.mp4"


settings = Settings.from_environment()
settings.ensure_directories()
vision_store = VisionConfigurationStore(settings.data_root / "vision-settings.json", {
    "provider": settings.vision_provider,
    "apiKey": settings.vision_api_key,
    "model": settings.vision_model,
    "baseUrl": settings.vision_base_url,
    "thinkingType": settings.vision_thinking_type,
    "responseFormat": settings.vision_response_format,
    "timeoutSeconds": settings.vision_timeout_seconds,
})
explicit_anthropic = bool(settings.anthropic_base_url and settings.anthropic_auth_token and settings.anthropic_model)
explicit_llm = explicit_anthropic or any(os.environ.get(name, "").strip() for name in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"))
if explicit_anthropic:
    llm_default_provider = "anthropic" if "api.anthropic.com" in settings.anthropic_base_url else "anthropic_compatible"
    llm_default_key = settings.anthropic_auth_token
    llm_default_model = settings.anthropic_model
    llm_default_base_url = settings.anthropic_base_url
    llm_default_thinking = ""
    llm_default_response_format = "none"
else:
    if "ark.cn-" in settings.llm_base_url or "volces.com" in settings.llm_base_url:
        llm_default_provider = "ark"
    elif settings.llm_base_url.rstrip("/") == "https://api.openai.com/v1":
        llm_default_provider = "openai"
    else:
        llm_default_provider = "openai_compatible"
    llm_default_key = settings.llm_api_key
    llm_default_model = settings.llm_model
    llm_default_base_url = settings.llm_base_url
    llm_default_thinking = settings.llm_thinking_type
    llm_default_response_format = "json_object"
llm_store = LlmConfigurationStore(settings.data_root / "llm-settings.json", {
    "mode": "independent" if explicit_llm else "reuse_vision",
    "provider": llm_default_provider,
    "apiKey": llm_default_key,
    "model": llm_default_model,
    "baseUrl": llm_default_base_url,
    "thinkingType": llm_default_thinking,
    "responseFormat": llm_default_response_format,
    "timeoutSeconds": settings.llm_timeout_seconds,
})
job_store = JobStore(settings.data_root / "jobs.sqlite3")
app = FastAPI(title="VLM Highlight Cutter", version="1.0.0")
executor = ThreadPoolExecutor(max_workers=settings.maximum_workers, thread_name_prefix="vlm-highlight")
render_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="highlight-render")
preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="event-preview")
source_proxy_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="source-proxy")
output_preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="output-preview")
timeline_assets_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="timeline-assets")
jobs_lock = threading.RLock()
jobs: dict[str, dict[str, Any]] = {}
cancel_events: dict[str, threading.Event] = {}
# Keep the Future for every analysis/brief task.  Without this registry a job
# that was still waiting in ThreadPoolExecutor could only be marked
# ``cancelling``; it remained in the queue until an earlier multi-minute job
# released the sole worker.
analysis_futures: dict[str, Future[Any]] = {}
# Active clients can be visual or text-planning adapters; every adapter
# exposes cancel(), which is all the cancellation endpoint needs.
active_ark_clients: dict[str, Any] = {}
waveform_generation_lock = threading.Lock()
timeline_generation_lock = threading.Lock()
timeline_assets_schedule_lock = threading.Lock()
scheduled_timeline_assets: set[str] = set()
timeline_asset_failures: dict[str, tuple[float, str]] = {}
composition_generation_lock = threading.Lock()
fragment_download_lock = threading.Lock()
automatic_composition_lock = threading.Lock()
active_automatic_compositions: set[str] = set()
output_preview_generation_lock = threading.Lock()
browser_preview_generation_lock = threading.Lock()
source_proxy_schedule_lock = threading.Lock()
scheduled_source_proxies: set[str] = set()
source_proxy_failures: dict[str, tuple[float, str]] = {}
upload_attempts: dict[str, list[float]] = {}


@app.middleware("http")
async def protect_and_limit_requests(request: Request, call_next):
    path = request.url.path
    provided_token = request.headers.get("X-Highlight-Token") or request.query_params.get("token") or request.cookies.get("highlight_token")
    if settings.access_token and path.startswith("/api/") and path != "/api/health" and provided_token != settings.access_token:
        return JSONResponse({"detail": "访问令牌无效"}, status_code=401)
    if path == "/api/jobs" and request.method == "POST":
        address = request.client.host if request.client else "unknown"
        now = time.monotonic()
        attempts = [value for value in upload_attempts.get(address, []) if now - value < 3600]
        if len(attempts) >= 10:
            return JSONResponse({"detail": "上传任务过于频繁，请稍后再试"}, status_code=429)
        attempts.append(now)
        upload_attempts[address] = attempts
    response = await call_next(request)
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    if settings.access_token and request.query_params.get("token") == settings.access_token:
        response.set_cookie("highlight_token", settings.access_token, httponly=True, samesite="strict")
    return response


class ChatRequest(BaseModel):
    text: str
    subtitleMode: str | None = None
    selections: list[dict[str, Any]] | None = None
    orderMode: str | None = None


class BriefConfirmRequest(BaseModel):
    brief: dict[str, Any] | None = None
    confirmed: bool = True


class AnalysisDecisionRequest(BaseModel):
    action: str


class AdjustOutputRequest(BaseModel):
    start: float | None = None
    end: float | None = None
    startDelta: float = 0.0
    endDelta: float = 0.0


class KeepOutputRequest(BaseModel):
    kept: bool = True


class DeriveJobRequest(BaseModel):
    count: int | None = None
    targetSeconds: float | None = None
    theme: str | None = None
    excludeExisting: bool = True
    message: str = "根据当前结果继续生成"


class ConfirmCandidatesRequest(BaseModel):
    indices: list[int] | None = None
    groupIds: list[str] | None = None
    segmentIds: dict[str, list[str]] | None = None
    autoVariants: int | None = None
    outputMode: str = "single_reel"
    subtitleMode: str = "none"
    subtitleStyle: str = "clean"
    orderMode: str = "source"


class AutoPlanRequest(BaseModel):
    scope: str = "selected_only"
    groupIds: list[str] | None = None
    segmentIds: dict[str, list[str]] | None = None
    targetSeconds: float | None = None
    structure: str = "auto"
    variantCount: int = 3


class LlmOrderRequest(BaseModel):
    groupIds: list[str] = []
    segmentIds: dict[str, list[str]] | None = None


class RenderAutoPlanRequest(BaseModel):
    planId: str
    subtitleMode: str = "none"
    subtitleStyle: str = "clean"


class AdjustCandidateRequest(BaseModel):
    start: float
    end: float


class ReviewExclusionsRequest(BaseModel):
    indices: list[int] = []


class TimelineSelectionRequest(BaseModel):
    start: float
    end: float


class AdjustEventSegmentRequest(BaseModel):
    start: float
    end: float


class ReorderEventSegmentsRequest(BaseModel):
    segmentIds: list[str]


class AddEventSegmentRequest(BaseModel):
    start: float
    end: float
    role: str = "用户补充镜头"


class RenameEventGroupRequest(BaseModel):
    title: str


class MoveEventSegmentRequest(BaseModel):
    destinationGroupId: str
    targetIndex: int | None = None


class CreateEventGroupRequest(BaseModel):
    start: float
    end: float
    title: str = "手动事件高光"


class CreateEventFromCandidatesRequest(BaseModel):
    indices: list[int]
    title: str = "重新编排高光"


class VisionDiscoverRequest(BaseModel):
    provider: str
    apiKey: str = ""
    baseUrl: str = ""


class VisionSettingsRequest(BaseModel):
    provider: str
    apiKey: str = ""
    model: str
    baseUrl: str
    thinkingType: str = ""
    responseFormat: str = "json_object"
    models: list[dict[str, Any]] | None = None
    verifiedAt: str | None = None


class LlmDiscoverRequest(BaseModel):
    provider: str
    apiKey: str = ""
    baseUrl: str = ""


class LlmSettingsRequest(BaseModel):
    reuseVision: bool = False
    provider: str = ""
    apiKey: str = ""
    model: str = ""
    baseUrl: str = ""
    thinkingType: str = ""
    responseFormat: str = "json_object"
    models: list[dict[str, Any]] | None = None
    verifiedAt: str | None = None


def resolve_llm_configuration(job: dict[str, Any]) -> dict[str, Any]:
    """Resolve a job's immutable LLM selection against server-side secrets."""
    snapshot = job.get("llmConfig") if isinstance(job.get("llmConfig"), dict) else None
    configured = llm_store.resolve(snapshot=snapshot)
    if configured["mode"] == "reuse_vision":
        vision_snapshot = job.get("visionConfig") if isinstance(job.get("visionConfig"), dict) else None
        visual = vision_store.resolve(snapshot=vision_snapshot)
        return {
            "mode": "reuse_vision",
            "provider": visual["provider"],
            "providerLabel": vision_provider_label(str(visual["provider"])),
            "protocol": "openai",
            "apiKey": visual["apiKey"],
            "model": visual["model"],
            "baseUrl": visual["baseUrl"],
            "thinkingType": visual["thinkingType"],
            "responseFormat": visual["responseFormat"],
            "timeoutSeconds": min(90.0, float(visual["timeoutSeconds"])),
        }
    return {
        **configured,
        "providerLabel": llm_provider_label(str(configured["provider"])),
    }


def create_llm_client_for_job(job: dict[str, Any]) -> Any:
    configured = resolve_llm_configuration(job)
    missing = [label for label, value in (
        ("API Key", configured.get("apiKey")),
        ("剪辑规划模型", configured.get("model")),
        ("接口地址", configured.get("baseUrl")),
    ) if not value]
    if missing:
        raise RuntimeError(f"剪辑规划模型尚未配置：{', '.join(missing)}。请在右上角设置中完成配置")
    if configured.get("protocol") == "anthropic":
        return AnthropicCompatibleClient(
            auth_token=str(configured["apiKey"]),
            model=str(configured["model"]),
            base_url=str(configured["baseUrl"]),
            timeout_seconds=float(configured["timeoutSeconds"]),
        )
    return create_vision_client(
        provider=str(configured["provider"]),
        api_key=str(configured["apiKey"]),
        model=str(configured["model"]),
        base_url=str(configured["baseUrl"]),
        thinking_type=str(configured.get("thinkingType") or ""),
        response_format=str(configured.get("responseFormat") or "json_object"),
        timeout_seconds=float(configured["timeoutSeconds"]),
    )


def job_path(job_id: str) -> Path:
    return settings.data_root / "jobs" / f"{job_id}.json"


def analysis_cache_key(
    source_hash: str,
    theme: str,
    analysis_mode: str = "visual",
    requested_count: int | None = None,
    total_target_seconds: float | None = None,
    vision_config: dict[str, Any] | None = None,
) -> str:
    configured_vision = vision_config or vision_store.snapshot()
    identity = "\n".join((
        ANALYSIS_CACHE_VERSION,
        str(configured_vision.get("provider") or ""),
        str(configured_vision.get("model") or ""),
        str(configured_vision.get("baseUrl") or ""),
        source_hash, theme.strip(), analysis_mode,
        settings.speech_engine if analysis_mode == "audiovisual" else "none",
        settings.sensevoice_model if analysis_mode == "audiovisual" else "none",
        str(settings.sensevoice_diarization),
        str(requested_count or "auto"), str(total_target_seconds or "auto"),
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def analysis_cache_path(cache_key: str) -> Path:
    return settings.data_root / "cache" / f"{cache_key}.json"


def load_analysis_cache(cache_key: str) -> dict[str, Any] | None:
    path = analysis_cache_path(cache_key)
    if not path.is_file():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if cached.get("cacheVersion") != ANALYSIS_CACHE_VERSION or not cached.get("candidates"):
        return None
    return cached


def analysis_cache_reuse_allowed(job: dict[str, Any], resume_action: str | None = None) -> bool:
    request = job.get("request") or {}
    return not bool(request.get("forceReanalyze")) and not bool(job.get("excludedRanges")) and not resume_action


def save_analysis_cache(cache_key: str, manifest: dict[str, Any]) -> None:
    path = analysis_cache_path(cache_key)
    temporary = path.with_suffix(".tmp")
    cached = {**manifest, "cacheVersion": ANALYSIS_CACHE_VERSION, "cachedAt": now_iso()}
    temporary.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def waveform_cache_path(identity: str) -> Path:
    safe_identity = re.sub(r"[^a-zA-Z0-9_-]", "", identity)[:96]
    return settings.data_root / "cache" / f"waveform-{safe_identity}.json"


def timeline_cache_paths(identity: str) -> tuple[Path, Path]:
    safe_identity = re.sub(r"[^a-zA-Z0-9_-]", "", identity)[:96]
    root = settings.data_root / "cache"
    return root / f"timeline-{safe_identity}.json", root / f"timeline-{safe_identity}.jpg"


def timeline_partial_cache_paths(identity: str) -> tuple[Path, Path]:
    safe_identity = re.sub(r"[^a-zA-Z0-9_-]", "", identity)[:96]
    root = settings.data_root / "cache"
    return root / f"timeline-{safe_identity}.partial.json", root / f"timeline-{safe_identity}.partial.jpg"


def write_timeline_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def thumbnail_cache_path(job: dict[str, Any]) -> Path:
    return Path(job["workDirectory"]) / "thumbnail-first-frame.jpg"


def proxy_cache_path(identity: str) -> Path:
    safe_identity = re.sub(r"[^a-zA-Z0-9_-]", "", identity)[:96]
    return settings.data_root / "cache" / f"proxy-{safe_identity}.mp4"


def kept_job_directory(job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", job_id) or job_id in {".", ".."}:
        raise HTTPException(400, "保留库任务编号无效")
    return settings.data_root / "kept" / job_id


def kept_output_paths(job_id: str, filename: str) -> tuple[Path, Path]:
    if not filename or Path(filename).name != filename or filename in {".", ".."}:
        raise HTTPException(400, "保留库文件名无效")
    media = kept_job_directory(job_id) / filename
    return media, media.with_name(f"{media.name}.json")


def kept_preview_path(media: Path) -> Path:
    return media.with_name(f".{media.name}.preview.mp4")


def _download_component(value: Any, fallback: str, maximum: int = 48) -> str:
    """Make a readable, filesystem-safe component for a browser download."""
    text = Path(str(value or fallback)).stem
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", text).strip(" .-_")
    text = re.sub(r"\s+", "_", text)
    return text[:maximum] or fallback


def friendly_download_filename(
    *,
    source_filename: str,
    version_number: Any = 1,
    strategy_key: str = "manual",
    source_label: str = "",
    display_name: str = "",
    title: str = "高光成片",
    position: int = 1,
    extension: str = "mp4",
) -> str:
    """Return the user-facing download name without changing stored paths."""
    try:
        version = max(1, int(version_number or 1))
    except (TypeError, ValueError):
        version = 1
    try:
        index = max(1, int(position or 1))
    except (TypeError, ValueError):
        index = 1
    key = str(strategy_key or "").lower()
    label_text = f"{source_label} {display_name}".upper()
    if key == "vlm" or "VLM" in label_text:
        strategy = "VLM"
    elif key in {"narrative", "emotion", "information", "llm"} or "LLM" in label_text:
        strategy = "LLM"
    else:
        strategy = "手动合成"
    clean_title = re.sub(r"\s*[·|｜]\s*(?:VLM|LLM).*?$", "", str(display_name or title or "高光成片"), flags=re.IGNORECASE).strip()
    title_parts = [part.strip() for part in re.split(r"[·|｜]", clean_title) if part.strip()]
    if len(title_parts) > 1 and title_parts[0] == title_parts[-1]:
        clean_title = title_parts[0]
    source = _download_component(source_filename, "视频", 48)
    title_part = _download_component(clean_title, "高光成片", 48)
    suffix = str(extension or "mp4").lower().lstrip(".") or "mp4"
    return f"{source}_V{version:03d}_{strategy}-{title_part}_{index:02d}.{suffix}"


def public_kept_record(record: dict[str, Any]) -> dict[str, Any]:
    job_id = str(record["jobId"])
    filename = str(record["filename"])
    encoded_job = quote(job_id, safe="")
    encoded_filename = quote(filename, safe="")
    download_name = str(record.get("downloadFilename") or friendly_download_filename(
        source_filename=str(record.get("sourceFilename") or "视频"),
        version_number=record.get("versionNumber", 1),
        strategy_key=str(record.get("strategyKey") or "manual"),
        source_label=str(record.get("sourceLabel") or ""),
        display_name=str(record.get("displayName") or ""),
        title=str(record.get("title") or "高光成片"),
        position=int(record.get("position") or 1),
    ))
    return {
        **record,
        "downloadFilename": download_name,
        "videoUrl": f"/api/kept/{encoded_job}/{encoded_filename}",
        "downloadUrl": f"/api/kept/{encoded_job}/{encoded_filename}?download=1",
    }


def list_kept_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    kept_root = settings.data_root / "kept"
    for metadata in kept_root.glob("*/*.mp4.json"):
        try:
            record = json.loads(metadata.read_text(encoding="utf-8"))
            media, expected_metadata = kept_output_paths(str(record["jobId"]), str(record["filename"]))
            if expected_metadata != metadata or not media.is_file():
                continue
            record["sizeBytes"] = media.stat().st_size
            records.append(public_kept_record(record))
        except (OSError, ValueError, KeyError, TypeError, HTTPException):
            continue
    return sorted(records, key=lambda item: str(item.get("keptAt", "")), reverse=True)


def save_output_to_kept_library(job: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    source = Path(job["outputDirectory"]) / str(item["filename"])
    if not source.is_file():
        raise HTTPException(404, "待保留的高光文件不存在")
    media, metadata = kept_output_paths(str(job["id"]), str(item["filename"]))
    media.parent.mkdir(parents=True, exist_ok=True)
    temporary = media.with_name(f".{media.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        temporary.replace(media)
        context = output_download_context(job, str(item["filename"]))
        _, version, output_position = context or (item, {}, 1)
        record = {
            "id": f"{job['id']}:{item['filename']}",
            "jobId": str(job["id"]),
            "filename": str(item["filename"]),
            "sourceFilename": str(job.get("filename") or ""),
            "title": str(item.get("title") or item["filename"]),
            "versionNumber": int(version.get("number") or item.get("versionNumber") or 1),
            "strategyKey": str(version.get("strategyKey") or item.get("strategyKey") or "manual"),
            "sourceLabel": str(version.get("sourceLabel") or item.get("sourceLabel") or ""),
            "displayName": str(version.get("displayName") or item.get("displayName") or ""),
            "position": output_position,
            "downloadFilename": friendly_download_filename(
                source_filename=str(job.get("filename") or "视频"),
                version_number=version.get("number") or item.get("versionNumber") or 1,
                strategy_key=str(version.get("strategyKey") or item.get("strategyKey") or "manual"),
                source_label=str(version.get("sourceLabel") or item.get("sourceLabel") or ""),
                display_name=str(version.get("displayName") or item.get("displayName") or ""),
                title=str(item.get("title") or "高光成片"),
                position=output_position,
            ),
            "duration": float(item.get("duration") or 0),
            "score": float(item.get("score") or 0),
            "chapterCount": int(item.get("chapterCount") or 0),
            "segmentCount": int(item.get("segmentCount") or 1),
            "keptAt": now_iso(),
            "sizeBytes": media.stat().st_size,
        }
        metadata.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        existing_preview = output_preview_path(job, str(item["filename"]))
        if existing_preview.is_file():
            shutil.copy2(existing_preview, kept_preview_path(media))
        return record
    finally:
        temporary.unlink(missing_ok=True)


def remove_output_from_kept_library(job_id: str, filename: str) -> None:
    media, metadata = kept_output_paths(job_id, filename)
    media.unlink(missing_ok=True)
    kept_preview_path(media).unlink(missing_ok=True)
    metadata.unlink(missing_ok=True)
    try:
        media.parent.rmdir()
    except OSError:
        pass


def restore_kept_library_copies() -> None:
    with jobs_lock:
        pending = [
            (job, item)
            for job in jobs.values()
            for item in all_job_outputs(job)
            if item.get("kept")
        ]
    for job, item in pending:
        try:
            media, metadata = kept_output_paths(str(job["id"]), str(item["filename"]))
            if not media.is_file() or not metadata.is_file():
                save_output_to_kept_library(job, item)
        except (OSError, KeyError, TypeError, HTTPException):
            continue


def event_group_edl_hash(group: dict[str, Any]) -> str:
    payload = json.dumps({
        "title": group.get("title"),
        "segments": [{
            "start": item.get("start"), "end": item.get("end"),
            "transitionIn": item.get("transitionIn"), "editOrder": item.get("editOrder"),
        } for item in group.get("segments", [])],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


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
) -> str:
    payload = {
        "sourceHash": source_hash,
        "outputMode": output_mode,
        "subtitleMode": subtitle_mode,
        "variantMode": variant_mode,
        "variantLabel": variant_label,
        "orderMode": order_mode,
        "selections": [{
            "id": item.get("id"),
            "title": item.get("title"),
            "segments": [{
                "id": segment.get("id"),
                "start": segment.get("start"),
                "end": segment.get("end"),
                "role": segment.get("role"),
                "transitionIn": segment.get("transitionIn"),
                "editOrder": segment.get("editOrder"),
            } for segment in item.get("segments", [])],
        } for item in selections],
    }
    if subtitle_mode == "burn":
        payload["subtitleStyle"] = subtitle_style
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]


def event_group_preview_path(job: dict[str, Any], group: dict[str, Any]) -> Path:
    return Path(job["workDirectory"]) / "event-previews" / f"{group['id']}-{event_group_edl_hash(group)}.mp4"


# User-facing names for automatic compositions.  Keep the product-facing
# title separate from the engine/source label so the same version can be
# presented consistently in chat, preview, history, and download metadata.
AUTO_COMPOSITION_META: dict[str, dict[str, str]] = {
    "vlm": {
        "displayName": "完整事件版",
        "sourceLabel": "视觉推荐",
        "strategyDescription": "保留事件完整过程",
    },
    "narrative": {
        "displayName": "节奏连贯版",
        "sourceLabel": "剪辑规划",
        "strategyDescription": "强化镜头前后衔接",
    },
    "emotion": {
        "displayName": "情绪集中版",
        "sourceLabel": "剪辑规划",
        "strategyDescription": "优先保留情绪高点",
    },
    "information": {
        "displayName": "信息精简版",
        "sourceLabel": "剪辑规划",
        "strategyDescription": "优先保留关键信息",
    },
}


def auto_composition_meta(kind: str = "", plan_label: str = "") -> dict[str, str]:
    """Return stable display metadata while accepting legacy plan labels."""
    normalized = f"{kind} {plan_label}".lower()
    if kind == "vlm" or "vlm" in normalized:
        return {"strategyKey": "vlm", **AUTO_COMPOSITION_META["vlm"]}
    if "情绪" in plan_label or "emotion" in normalized:
        return {"strategyKey": "emotion", **AUTO_COMPOSITION_META["emotion"]}
    if "信息" in plan_label or "密度" in plan_label or "information" in normalized:
        return {"strategyKey": "information", **AUTO_COMPOSITION_META["information"]}
    return {"strategyKey": "narrative", **AUTO_COMPOSITION_META["narrative"]}


def automatic_composition_signature(segments: list[dict[str, Any]] | None) -> tuple[tuple[str, float, float], ...]:
    """Identify the actual source cuts used by one automatic reel.

    Plan objects call the source id ``candidateId`` while rendered segments
    keep it as ``id``.  Normalising both shapes lets us compare the initial VLM
    reel with later LLM plans before spending time rendering a duplicate.
    """
    signature: list[tuple[str, float, float]] = []
    for item in segments or []:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("candidateId") or item.get("candidate_id") or item.get("id") or "")
        try:
            start = round(float(item.get("start") or item.get("source_start") or 0), 2)
            end = round(float(item.get("end") or item.get("source_end") or 0), 2)
        except (TypeError, ValueError):
            continue
        signature.append((source_id, start, end))
    return tuple(signature)


def automatic_composition_similarity(
    left: tuple[tuple[str, float, float], ...], right: tuple[tuple[str, float, float], ...],
) -> float:
    """Measure shared source-time coverage, not merely exact JSON equality."""
    if not left or not right:
        return 0.0
    left_ranges = [(start, end) for _, start, end in left if end > start]
    right_ranges = [(start, end) for _, start, end in right if end > start]
    left_total = sum(end - start for start, end in left_ranges)
    right_total = sum(end - start for start, end in right_ranges)
    if left_total <= 0 or right_total <= 0:
        return 0.0
    intersection = 0.0
    for left_start, left_end in left_ranges:
        covered: list[tuple[float, float]] = []
        for right_start, right_end in right_ranges:
            start, end = max(left_start, right_start), min(left_end, right_end)
            if end > start:
                covered.append((start, end))
        if covered:
            covered.sort()
            merged = [list(covered[0])]
            for start, end in covered[1:]:
                if start <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])
            intersection += sum(end - start for start, end in merged)
    return round(intersection / min(left_total, right_total), 4)


def distinct_event_replacement_plans(
    job: dict[str, Any],
    seen_signatures: list[tuple[tuple[str, float, float], ...]],
    count: int,
    target_seconds: float | None,
) -> list[dict[str, Any]]:
    """Replace duplicate automatic plans with real cuts from other events.

    The editorial model can legitimately return the currently recommended
    event for every requested direction when that one event already fills the
    duration budget.  If other analyzed events exist, dropping those duplicate
    plans makes the product look as though no alternative footage was found.
    Build deterministic one-event alternatives from the existing evidence
    pool instead; this adds no model request and never invents source ranges.
    """
    requested = max(0, int(count or 0))
    if not requested:
        return []
    selected_groups = {str(value) for value in job.get("recommendedGroupIds", [])}
    candidates = _edit_plan_candidates(job, list(selected_groups), None, "all_pool")
    if not candidates:
        return []

    target = float(target_seconds) if target_seconds not in (None, "", "auto") else None

    def rank(candidate: dict[str, Any]) -> tuple[Any, ...]:
        duration = max(0.0, float(candidate.get("end") or 0) - float(candidate.get("start") or 0))
        # Prefer an entirely different event first, then the closest natural
        # duration and the strongest analyzed candidate.
        return (
            str(candidate.get("groupId")) in selected_groups,
            abs(duration - target) if target else 0.0,
            -float(candidate.get("score") or 0),
            float(candidate.get("start") or 0),
        )

    ranked = sorted(candidates, key=rank)
    replacements: list[dict[str, Any]] = []
    replacement_groups: set[str] = set()
    live_signatures = list(seen_signatures)
    for candidate in ranked:
        group_id = str(candidate.get("groupId") or "")
        if not group_id or group_id in replacement_groups:
            continue
        start = round(float(candidate.get("start") or 0), 3)
        end = round(float(candidate.get("end") or 0), 3)
        if end - start < .35:
            continue
        signature = automatic_composition_signature([{
            "candidateId": candidate.get("id"), "start": start, "end": end,
        }])
        if not signature or any(
            signature == previous or automatic_composition_similarity(signature, previous) >= .85
            for previous in live_signatures
        ):
            continue
        title = str(candidate.get("groupTitle") or "替代高光事件")[:60]
        role = str(candidate.get("role") or "精彩镜头")
        duration = round(end - start, 3)
        auto_meta = {
            "strategyKey": "event_alternative",
            "displayName": title,
            "sourceLabel": "事件替选",
            "strategyDescription": "换用另一组高分事件",
        }
        replacements.append({
            "id": f"plan_{uuid.uuid4().hex[:12]}",
            "label": title,
            "narrative": f"原剪辑方案与已有成片重复，改用“{title}”形成独立高光版本。",
            "structure": ["highlight"],
            "sequence": [{
                "id": f"plan_{uuid.uuid4().hex[:10]}",
                "candidateId": candidate.get("id"),
                "groupId": group_id,
                "chapterId": group_id,
                "chapterTitle": title,
                "chapterOrder": 0,
                "editOrder": 0,
                "start": start,
                "end": end,
                "duration": duration,
                "role": role,
                "reason": "从完整候选池换用另一个高分事件，确保版本内容真实不同。",
                "essential": True,
                "transitionIn": {"type": "cut", "duration": 0.0},
            }],
            "chapters": [{"id": f"chapter_{uuid.uuid4().hex[:8]}", "role": "highlight", "title": title, "segmentCount": 1, "duration": duration}],
            "addedByAi": [str(candidate.get("id") or "")],
            "estimatedDuration": duration,
            "targetSeconds": target,
            "durationStatus": "on_target" if not target or abs(duration - target) <= max(5.0, target * .15) else ("under_target" if duration < target else "over_target"),
            "durationGap": round(target - duration, 3) if target else 0.0,
            "warnings": ["原方案与已有成片重复，已自动换用其他高分事件"],
            "planner": "local-distinct-event-fallback",
            "autoMeta": auto_meta,
        })
        replacement_groups.add(group_id)
        live_signatures.append(signature)
        if len(replacements) >= requested:
            break
    return replacements


def output_preview_path(job: dict[str, Any], filename: str) -> Path:
    return Path(job["workDirectory"]) / "output-previews" / filename


def browser_preview_path(job: dict[str, Any], filename: str | None = None) -> Path:
    name = f"{Path(filename).stem}.webm" if filename else "source.webm"
    return Path(job["workDirectory"]) / "browser-previews" / name


def prepare_browser_preview(job_id: str, filename: str | None = None) -> Path:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise RuntimeError("任务不存在")
        if filename:
            item = next((value for value in all_job_outputs(job) if value.get("filename") == filename), None)
            if not item:
                raise RuntimeError("输出文件不存在")
            source = Path(job["outputDirectory"]) / filename
        else:
            source = Path(job["sourcePath"])
        output = browser_preview_path(job, filename)
    if output.is_file():
        return output
    if not source.is_file():
        raise RuntimeError("预览源文件不存在")
    with browser_preview_generation_lock:
        if output.is_file():
            return output
        info = probe_video(source, settings.ffprobe)
        maximum_dimension = 960 if info.duration <= 1800 else 720
        create_webm_preview(
            source,
            output,
            has_audio=info.has_audio,
            ffmpeg=settings.ffmpeg,
            maximum_dimension=maximum_dimension,
        )
    return output


def prepare_output_preview(job_id: str, filename: str) -> Path:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise RuntimeError("任务不存在")
        item = next((value for value in all_job_outputs(job) if value.get("filename") == filename), None)
        if not item:
            raise RuntimeError("输出文件不存在")
        source = Path(job["outputDirectory"]) / filename
        output = output_preview_path(job, filename)
    if output.is_file():
        return output
    if not source.is_file():
        raise RuntimeError("输出文件不存在")
    with output_preview_generation_lock:
        if output.is_file():
            return output
        info = probe_video(source, settings.ffprobe)
        create_preview_proxy(source, output, has_audio=info.has_audio, ffmpeg=settings.ffmpeg)
    return output


def find_event_group(job: dict[str, Any], group_id: str) -> dict[str, Any]:
    group = next((item for item in job.get("eventGroups", []) if str(item.get("id")) == group_id), None)
    if group is None:
        raise HTTPException(404, "事件高光不存在")
    return group


def prepare_event_group_preview(job_id: str, group_id: str) -> Path:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise RuntimeError("任务不存在")
        group = copy.deepcopy(find_event_group(job, group_id))
        source = Path(job["sourcePath"])
        output = event_group_preview_path(job, group)
    with composition_generation_lock:
        if output.is_file():
            return output
        info = probe_video(source, settings.ffprobe)
        render_composition(
            source,
            output,
            segments=group.get("segments", []),
            has_audio=info.has_audio,
            ffmpeg=settings.ffmpeg,
            preview_width=960,
        )
    return output


def cleanup_unreferenced_media_cache(job: dict[str, Any]) -> None:
    identity = str(job.get("sourceHash") or job["id"])
    with jobs_lock:
        still_used = any(
            str(other.get("sourceHash") or other["id"]) == identity
            for other in jobs.values()
        )
    if still_used:
        return
    with timeline_assets_schedule_lock:
        timeline_asset_failures.pop(identity, None)
    metadata, sprite = timeline_cache_paths(identity)
    partial_metadata, partial_sprite = timeline_partial_cache_paths(identity)
    for path in (
        waveform_cache_path(identity), metadata, sprite, partial_metadata, partial_sprite, proxy_cache_path(identity),
        proxy_cache_path(identity).with_suffix(".tmp.mp4"),
    ):
        path.unlink(missing_ok=True)


def cleanup_orphaned_media_cache() -> None:
    """Remove derived review assets whose source identity is no longer a job."""
    cache_root = settings.data_root / "cache"
    with jobs_lock:
        identities = {str(job.get("sourceHash") or job["id"]) for job in jobs.values()}
    for pattern in ("waveform-*.json", "timeline-*.json", "timeline-*.jpg", "proxy-*.mp4"):
        for path in cache_root.glob(pattern):
            if path.name.startswith("waveform-"):
                identity = path.name[len("waveform-"):-len(".json")]
            elif path.name.startswith("timeline-"):
                identity = path.name[len("timeline-"):].rsplit(".", 1)[0]
                if identity.endswith(".partial"):
                    identity = identity[:-len(".partial")]
            else:
                identity = path.name[len("proxy-"):-len(".mp4")]
            if identity and identity not in identities:
                path.unlink(missing_ok=True)


def prepare_preview_proxy(job_id: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        source = Path(job["sourcePath"])
        identity = str(job.get("sourceHash") or job_id)
    output = proxy_cache_path(identity)
    if output.is_file():
        return
    info = probe_video(source, settings.ffprobe)
    # A full-length source proxy is only for browser review. Long recordings use
    # a smaller long edge so opening a 60–90 minute portrait video does not take
    # over the machine for many minutes.
    maximum_dimension = 1280 if info.duration <= 1800 else 960 if info.duration <= 3600 else 720
    create_preview_proxy(
        source,
        output,
        has_audio=info.has_audio,
        ffmpeg=settings.ffmpeg,
        maximum_dimension=maximum_dimension,
    )


def schedule_preview_proxy(job_id: str) -> bool:
    """Start one on-demand source proxy without queuing duplicate transcodes."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return False
        identity = str(job.get("sourceHash") or job_id)
    if proxy_cache_path(identity).is_file():
        return False
    with source_proxy_schedule_lock:
        if identity in scheduled_source_proxies:
            return False
        failure = source_proxy_failures.get(identity)
        if failure and time.monotonic() - failure[0] < 60:
            return False
        source_proxy_failures.pop(identity, None)
        scheduled_source_proxies.add(identity)

    def generate() -> None:
        try:
            prepare_preview_proxy(job_id)
        except Exception as error:
            with source_proxy_schedule_lock:
                source_proxy_failures[identity] = (time.monotonic(), str(error)[:500])
        finally:
            with source_proxy_schedule_lock:
                scheduled_source_proxies.discard(identity)

    try:
        source_proxy_executor.submit(generate)
    except RuntimeError:
        with source_proxy_schedule_lock:
            scheduled_source_proxies.discard(identity)
        return False
    return True


def prepare_timeline_assets(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise RuntimeError("任务不存在")
        source = Path(job["sourcePath"])
        identity = str(job.get("sourceHash") or job_id)
        work_directory = Path(job["workDirectory"])
    metadata_path, sprite_path = timeline_cache_paths(identity)
    partial_metadata_path, partial_sprite_path = timeline_partial_cache_paths(identity)
    with timeline_generation_lock:
        if metadata_path.is_file() and sprite_path.is_file():
            try:
                cached = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = {}
            if cached.get("schemaVersion") == 3 or cached.get("sceneCutsReady") is True:
                return cached
        else:
            cached = {}
        info = probe_video(source, settings.ffprobe)
        if not (cached.get("schemaVersion") == 4 and cached.get("sprite") and sprite_path.is_file()):
            checkpoint = load_analysis_checkpoint(work_directory) or {}
            checkpoint_frames = [
                SampledFrame(path=Path(str(item.get("path") or "")), time=float(item.get("time") or 0))
                for item in checkpoint.get("frames") or []
                if isinstance(item, dict) and item.get("path")
            ]
            checkpoint_frames = [frame for frame in checkpoint_frames if frame.path.is_file()]
            if len(checkpoint_frames) < 2:
                checkpoint_frames = []

            def publish_partial(sprite: dict[str, Any]) -> None:
                frame_count = len(sprite.get("items") or [])
                partial_metadata = {
                    "schemaVersion": 4,
                    "duration": info.duration,
                    "sprite": sprite,
                    "sceneCuts": [],
                    "sceneCutsReady": False,
                    "partial": True,
                    "frameCount": frame_count,
                    "frameTarget": coarse_frame_limit(info.duration),
                }
                write_timeline_metadata(partial_metadata_path, partial_metadata)

            sprite = create_timeline_thumbnail_sprite(
                source,
                sprite_path,
                duration=info.duration,
                ffmpeg=settings.ffmpeg,
                frame_count=coarse_frame_limit(info.duration),
                columns=12,
                partial_output=partial_sprite_path,
                partial_callback=publish_partial,
                frames_directory=work_directory / "coarse-frames",
                preserve_frames=True,
                sampled_frames=checkpoint_frames or None,
            )
            # Publish the complete thumbnail sprite immediately. Scene-change
            # detection scans the full video and may take much longer, but it
            # is not required to start visually reviewing the timeline.
            cached = {
                "schemaVersion": 4,
                "duration": info.duration,
                "sprite": sprite,
                "sceneCuts": [],
                "sceneCutsReady": False,
                "partial": False,
                "frameCount": len(sprite.get("items") or []),
                "frameTarget": len(sprite.get("items") or []),
            }
            write_timeline_metadata(metadata_path, cached)
            partial_metadata_path.unlink(missing_ok=True)
            partial_sprite_path.unlink(missing_ok=True)
        try:
            scene_cuts = detect_scene_changes(source, ffmpeg=settings.ffmpeg)
        except Exception:
            scene_cuts = []
        metadata = {**cached, "sceneCuts": scene_cuts, "sceneCutsReady": True, "partial": False}
        write_timeline_metadata(metadata_path, metadata)
        return metadata


def schedule_timeline_assets(job_id: str, identity: str, *, force: bool = False) -> bool:
    with timeline_assets_schedule_lock:
        if identity in scheduled_timeline_assets:
            return False
        if force:
            timeline_asset_failures.pop(identity, None)
        failure = timeline_asset_failures.get(identity)
        if failure and time.monotonic() - failure[0] < 10:
            return False
        timeline_asset_failures.pop(identity, None)
        scheduled_timeline_assets.add(identity)

    def generate() -> None:
        try:
            prepare_timeline_assets(job_id)
            with timeline_assets_schedule_lock:
                timeline_asset_failures.pop(identity, None)
        except Exception as error:
            with timeline_assets_schedule_lock:
                timeline_asset_failures[identity] = (time.monotonic(), str(error)[:500])
        finally:
            with timeline_assets_schedule_lock:
                scheduled_timeline_assets.discard(identity)

    try:
        timeline_assets_executor.submit(generate)
    except RuntimeError:
        with timeline_assets_schedule_lock:
            scheduled_timeline_assets.discard(identity)
        return False
    return True


def timeline_asset_failure(identity: str) -> str | None:
    with timeline_assets_schedule_lock:
        failure = timeline_asset_failures.get(identity)
        if not failure or time.monotonic() - failure[0] >= 10:
            return None
        return failure[1]


def record_timeline_edit(
    job: dict[str, Any],
    *,
    target: str,
    before: Any,
    after: Any,
    candidate_index: int | None = None,
) -> None:
    if before == after:
        return
    history = job.setdefault("timelineUndo", [])
    history.append({
        "target": target,
        "candidateIndex": candidate_index,
        "before": before,
        "after": after,
        "createdAt": now_iso(),
    })
    del history[:-50]
    job["timelineRedo"] = []


PROGRESS_STAGE_LABELS = {
    "queued": "等待开始",
    "starting": "准备分析环境",
    "probing": "读取素材",
    "audio_analysis": "读取音频波形",
    "speech_recognition": "理解对白与声音",
    "speech_analysis": "理解对白与声音",
    "sampling": "抽取视频画面",
    "content_classification": "识别内容类型",
    "coarse_vlm": "粗看全片",
    "refine_vlm": "精修镜头",
    "event_grouping": "编排高光事件",
    "event_director": "编排高光事件",
    "edit_planning": "规划剪辑结构",
    "auto_composition": "生成高光版本",
    "rendering": "合成高光成片",
    "render": "合成高光成片",
    "awaiting_confirmation": "分析完成",
    "completed": "任务完成",
}


def _finite_progress_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def progress_facts_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    """Build a stable, presentation-neutral progress contract.

    ``workflow.fraction`` is the weighted pipeline completion already used by
    the application. ``stage`` only becomes determinate when the worker has a
    measured numerator and denominator. Remote model heartbeats therefore
    remain active without inventing an internal percentage.
    """
    stage_id = str(job.get("stage") or "queued")
    status = str(job.get("status") or "")
    progress_mode = str(job.get("progressMode") or "indeterminate")
    eta_mode = str(job.get("etaMode") or "collecting")
    overall = _finite_progress_number(job.get("progress"))
    overall = max(0.0, min(1.0, overall if overall is not None else 0.0))
    completed = _finite_progress_number(job.get("stageCompleted"))
    total = _finite_progress_number(job.get("stageTotal"))
    completed_seconds = _finite_progress_number(job.get("stageCompletedSeconds"))
    total_seconds = _finite_progress_number(job.get("stageTotalSeconds"))
    stage_fraction = _finite_progress_number(job.get("stageProgress"))
    measurable = (
        progress_mode == "determinate"
        and stage_fraction is not None
        and ((total is not None and total > 0) or (total_seconds is not None and total_seconds > 0))
    )
    if status == "completed" or eta_mode == "completed" or stage_id in {"completed", "awaiting_confirmation", "edit_planning_complete"}:
        mode = "completed"
    elif eta_mode in {"finalizing", "quality_check"} or progress_mode == "finalizing":
        mode = "finalizing"
    elif measurable:
        mode = "determinate"
    else:
        mode = "indeterminate"

    if stage_id in {"rendering", "render", "edit_planning", "auto_composition"}:
        workflow_phase = 2
    elif stage_id in {
        "audio_analysis", "speech_recognition", "speech_analysis", "sampling",
        "content_classification", "coarse_vlm", "refine_vlm", "event_grouping",
        "event_director", "awaiting_confirmation",
    }:
        workflow_phase = 1
    else:
        workflow_phase = 0
    if status == "completed":
        workflow_phase = 3
    elif mode == "completed" and overall >= 1.0:
        workflow_phase = 3

    return {
        "schemaVersion": 1,
        "workflow": {
            "fraction": round(overall, 4),
            "completedSteps": max(0, min(3, workflow_phase)),
            "totalSteps": 3,
            "phase": ["prepare", "analysis", "output", "completed"][max(0, min(3, workflow_phase))],
        },
        "stage": {
            "id": stage_id,
            "label": PROGRESS_STAGE_LABELS.get(stage_id, stage_id.replace("_", " ") or "处理中"),
            "mode": mode,
            "phase": "finalizing" if mode == "finalizing" else ("completed" if mode == "completed" else "processing"),
            "fraction": round(max(0.0, min(1.0, stage_fraction)), 4) if measurable and stage_fraction is not None else None,
            "completed": completed if measurable else None,
            "total": total if measurable else None,
            "unit": str(job.get("stageUnit") or ""),
            "completedSeconds": completed_seconds if measurable else None,
            "totalSeconds": total_seconds if measurable else None,
        },
        "timing": {
            "startedAt": job.get("startedAt") or job.get("createdAt"),
            "stageStartedAt": job.get("stageStartedAt"),
            "lastProgressAt": job.get("lastProgressAt") or job.get("updatedAt"),
            "etaSeconds": job.get("etaSeconds"),
            "etaMode": eta_mode,
        },
        "activity": {
            "model": str(job.get("model") or "系统"),
            "detail": str(job.get("currentAction") or job.get("detail") or PROGRESS_STAGE_LABELS.get(stage_id, "处理中")),
        },
    }


def save_job(job: dict[str, Any]) -> None:
    # Every durable mutation receives a monotonically increasing revision.
    # Lightweight polling can therefore avoid transferring and rebuilding the
    # complete review document when nothing material changed.
    job["progressFacts"] = progress_facts_snapshot(job)
    job["revision"] = max(0, int(job.get("revision") or 0)) + 1
    path = job_path(job["id"])
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    job_store.save(job)


def normalize_output_versions(job: dict[str, Any]) -> bool:
    """Upgrade legacy single-output-state jobs to an append-only version list."""
    changed = False
    versions = job.get("outputVersions")
    if not isinstance(versions, list):
        versions = []
        job["outputVersions"] = versions
        changed = True
    if not versions and job.get("outputs"):
        created_at = str(job.get("updatedAt") or job.get("createdAt") or now_iso())
        legacy_outputs = job["outputs"]
        for item in legacy_outputs:
            item.setdefault("versionId", "v001")
            item.setdefault("versionNumber", 1)
            item.setdefault("versionCreatedAt", created_at)
        versions.append({
            "id": "v001",
            "number": 1,
            "createdAt": created_at,
            "outputMode": str(job.get("outputMode") or ("single_reel" if len(legacy_outputs) == 1 else "separate_events")),
            "confirmedGroupIds": list(job.get("confirmedGroupIds", [])),
            "confirmedIndices": list(job.get("confirmedIndices", [])),
            "outputs": legacy_outputs,
        })
        job["currentOutputVersionId"] = "v001"
        changed = True
    if versions:
        current_id = str(job.get("currentOutputVersionId") or versions[-1].get("id"))
        current = next((version for version in versions if str(version.get("id")) == current_id), versions[-1])
        if job.get("currentOutputVersionId") != current.get("id"):
            job["currentOutputVersionId"] = current.get("id")
            changed = True
        # Keep the legacy field as a pointer to the active version for the rest of the app.
        if job.get("outputs") is not current.get("outputs"):
            job["outputs"] = current.setdefault("outputs", [])
            changed = True
    return changed


def next_output_version(job: dict[str, Any]) -> tuple[str, int]:
    normalize_output_versions(job)
    numbers = [int(version.get("number") or 0) for version in job.get("outputVersions", [])]
    number = max(numbers, default=0) + 1
    return f"v{number:03d}", number


def find_output_version(job: dict[str, Any], version_id: str) -> dict[str, Any] | None:
    normalize_output_versions(job)
    return next((version for version in job.get("outputVersions", []) if str(version.get("id")) == version_id), None)


def all_job_outputs(job: dict[str, Any]) -> list[dict[str, Any]]:
    normalize_output_versions(job)
    return [item for version in job.get("outputVersions", []) for item in version.get("outputs", [])]


def output_download_context(job: dict[str, Any], filename: str) -> tuple[dict[str, Any], dict[str, Any], int] | None:
    """Find an output together with its version metadata and 1-based position."""
    normalize_output_versions(job)
    for version in job.get("outputVersions", []):
        for position, item in enumerate(version.get("outputs", []), 1):
            if str(item.get("filename")) == str(filename):
                return item, version, position
    return None


def load_jobs() -> None:
    records = {job["id"]: job for job in job_store.load_all() if isinstance(job, dict) and job.get("id")}
    for path in (settings.data_root / "jobs").glob("*.json"):
        try:
            file_job = json.loads(path.read_text(encoding="utf-8"))
            stored = records.get(file_job.get("id"))
            if not stored or str(file_job.get("updatedAt", "")) > str(stored.get("updatedAt", "")):
                records[file_job["id"]] = file_job
        except (OSError, ValueError, KeyError):
            continue
    for job in records.values():
        try:
            changed = False
            if job.get("status") in ("briefing", "queued", "running", "cancelling"):
                checkpoint_available = load_analysis_checkpoint(Path(job.get("workDirectory") or "")) is not None
                job.update({
                    "status": "failed",
                    "stage": "interrupted",
                    "detail": "服务重启导致任务中断，已保留检查点，可从中断处恢复" if checkpoint_available else "服务重启导致任务中断，可使用原素材重新分析",
                    "error": "服务重启导致任务中断",
                    "resumeAvailable": checkpoint_available,
                    "currentAction": "任务因服务重启而中断",
                    "etaSeconds": None,
                    "etaMode": "stopped",
                    "progressMode": "stopped",
                    "interruptedAt": now_iso(),
                    "updatedAt": now_iso(),
                })
                changed = True
            if "messages" not in job:
                count = len(job.get("outputs", []))
                job["messages"] = [
                    {
                        "id": f"msg_{uuid.uuid4().hex}",
                        "role": "user",
                        "text": f"历史任务：分析 {job.get('filename', '视频')} 的视觉高光",
                        "kind": "request",
                        "createdAt": job.get("createdAt", now_iso()),
                    },
                    {
                        "id": f"msg_{uuid.uuid4().hex}",
                        "role": "assistant",
                        "text": f"该任务已生成 {count} 条高光，可以继续播放、下载或换掉某一条。",
                        "kind": "result",
                        "createdAt": job.get("updatedAt", now_iso()),
                    },
                ]
                changed = True
            if "parentJobId" not in job:
                job["parentJobId"] = None
                changed = True
            if "excludedRanges" not in job:
                job["excludedRanges"] = []
                changed = True
            if "reviewExcludedCandidates" not in job:
                job["reviewExcludedCandidates"] = []
                changed = True
            # Existing tasks keep their previous manual-review behavior; only
            # newly created tasks opt into automatic multi-version composition.
            if "autoCompose" not in job:
                job["autoCompose"] = False
                changed = True
            manual_index = 0
            for group in job.get("eventGroups", []):
                if group.get("assemblyStrategy") != "manual":
                    continue
                manual_index += 1
                if str(group.get("title") or "").strip() in {"时间轴选区高光", "手动事件高光", "时间轴片段", "时间轴选区"}:
                    group["title"] = f"手动高光片段 {manual_index:02d}"
                    changed = True
            if job.get("status") == "awaiting_confirmation" and not job.get("pendingSelectionGroupIds"):
                latest_message = (job.get("messages") or [])[-1] if job.get("messages") else {}
                latest_notice = latest_message if latest_message.get("role") == "assistant" and re.search(r"已准备好你选中的多个时间轴片段|已找到相同的时间轴选区", str(latest_message.get("text") or "")) else None
                manual_groups = [group for group in job.get("eventGroups", []) if group.get("assemblyStrategy") == "manual"]
                if latest_notice and manual_groups:
                    job["pendingSelectionGroupIds"] = [str(manual_groups[-1].get("id"))]
                    changed = True
            if normalize_output_versions(job):
                changed = True
            save_job(job)
            jobs[job["id"]] = job
        except (OSError, ValueError, KeyError, TypeError):
            continue


load_jobs()


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    normalize_output_versions(job)
    # Give legacy manually-created timeline groups stable, distinguishable
    # names instead of repeating the old generic label.
    manual_index = 0
    for group in job.get("eventGroups", []):
        if group.get("assemblyStrategy") != "manual":
            continue
        manual_index += 1
        if str(group.get("title") or "").strip() in {"时间轴选区高光", "手动事件高光", "时间轴片段", "时间轴选区"}:
            group["title"] = f"手动高光片段 {manual_index:02d}"
    visible = {
        key: value for key, value in job.items()
        if key not in {"sourcePath", "workDirectory", "outputDirectory", "sourceHash", "analysisCacheKey"}
    }
    auto_job = isinstance(job.get("autoComposition"), dict) and bool(job.get("autoComposition", {}).get("versions"))
    auto_plan_labels = [str(item.get("label") or "") for item in (job.get("autoPlans") or [])]
    def legacy_auto_meta(index: int) -> dict[str, str] | None:
        if not auto_job:
            return None
        if index == 0:
            return auto_composition_meta("vlm")
        return auto_composition_meta("llm", auto_plan_labels[index - 1] if index - 1 < len(auto_plan_labels) else "")

    def public_outputs(items: list[dict[str, Any]], version_meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = []
        for position, item in enumerate(items, 1):
            metadata = {**(version_meta or {}), **item}
            result.append({
                **item,
                **({key: version_meta[key] for key in ("strategyKey", "displayName", "sourceLabel", "strategyDescription") if key in version_meta} if version_meta else {}),
                "displayTitle": (
                    f"{version_meta.get('displayName')} · {version_meta.get('sourceLabel')}"
                    if version_meta and version_meta.get("displayName") else item.get("title")
                ),
                "downloadFilename": friendly_download_filename(
                    source_filename=str(job.get("filename") or "视频"),
                    version_number=metadata.get("versionNumber") or metadata.get("number") or 1,
                    strategy_key=str(metadata.get("strategyKey") or "manual"),
                    source_label=str(metadata.get("sourceLabel") or ""),
                    display_name=str(metadata.get("displayName") or ""),
                    title=str(item.get("title") or "高光成片"),
                    position=position,
                ),
                "videoUrl": f"/api/jobs/{job['id']}/outputs/{item['filename']}",
                "previewUrl": f"/api/jobs/{job['id']}/outputs/{item['filename']}/preview",
                "previewReady": output_preview_path(job, str(item["filename"])).is_file(),
                "downloadUrl": f"/api/jobs/{job['id']}/outputs/{item['filename']}?download=1",
            })
        return result
    if visible.get("outputs"):
        visible["outputs"] = public_outputs(visible["outputs"])
    if visible.get("outputVersions"):
        normalized_versions = []
        for index, version in enumerate(visible["outputVersions"]):
            version_meta = {"number": version.get("number")}
            version_meta.update({
                key: version[key]
                for key in ("strategyKey", "displayName", "sourceLabel", "strategyDescription")
                if version.get(key)
            })
            if not any(version_meta.values()):
                version_meta = legacy_auto_meta(index) or {}
            normalized_versions.append({**version, **version_meta, "outputs": public_outputs(version.get("outputs", []), version_meta)})
        visible["outputVersions"] = normalized_versions
    if auto_job:
        versions = list(visible.get("autoComposition", {}).get("versions") or [])
        normalized_auto_versions = []
        for index, version in enumerate(versions):
            if isinstance(version, dict) and version.get("displayName"):
                normalized_auto_versions.append(version)
            else:
                label = str(version or "")
                normalized_auto_versions.append(legacy_auto_meta(index) or auto_composition_meta("llm", label))
        visible["autoComposition"] = {**visible["autoComposition"], "versions": normalized_auto_versions}
    visible["sourceUrl"] = f"/api/jobs/{job['id']}/source"
    visible["previewUrl"] = f"/api/jobs/{job['id']}/preview"
    thumbnail = thumbnail_cache_path(job)
    visible["thumbnailUrl"] = f"/api/jobs/{job['id']}/thumbnail"
    visible["thumbnailReady"] = thumbnail.is_file()
    identity = str(job.get("sourceHash") or job["id"])
    proxy = proxy_cache_path(identity)
    visible["previewReady"] = proxy.is_file()
    with source_proxy_schedule_lock:
        scheduled = identity in scheduled_source_proxies
    visible["previewPreparing"] = not proxy.is_file() and (
        scheduled or proxy.with_suffix(".tmp.mp4").is_file()
    )
    return visible


def job_output_count(job: dict[str, Any]) -> int:
    versions = job.get("outputVersions") if isinstance(job.get("outputVersions"), list) else []
    if versions:
        return sum(len(version.get("outputs") or []) for version in versions if isinstance(version, dict))
    return len(job.get("outputs") or [])


def public_job_summary(job: dict[str, Any]) -> dict[str, Any]:
    """Small home-card payload; never include review evidence or edit plans."""
    video = job.get("videoInfo") if isinstance(job.get("videoInfo"), dict) else {}
    event_groups = job.get("eventGroups") if isinstance(job.get("eventGroups"), list) else []
    candidates = job.get("candidates") if isinstance(job.get("candidates"), list) else []
    thumbnail = thumbnail_cache_path(job)
    return {
        "id": job["id"],
        "revision": int(job.get("revision") or 0),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "detail": job.get("detail"),
        "filename": job.get("filename"),
        "createdAt": job.get("createdAt"),
        "updatedAt": job.get("updatedAt"),
        "videoInfo": {
            "duration": video.get("duration"),
            "width": video.get("width"),
            "height": video.get("height"),
            "has_audio": video.get("has_audio"),
        },
        "eventGroupCount": len(event_groups),
        "candidateCount": len(candidates),
        "outputCount": job_output_count(job),
        "thumbnailUrl": f"/api/jobs/{job['id']}/thumbnail",
        "thumbnailReady": thumbnail.is_file(),
    }


def public_job_status(job: dict[str, Any]) -> dict[str, Any]:
    """Progress-only snapshot used by the active workspace poller."""
    auto = job.get("autoComposition") if isinstance(job.get("autoComposition"), dict) else {}
    messages = job.get("messages") if isinstance(job.get("messages"), list) else []
    return {
        "id": job["id"],
        "revision": int(job.get("revision") or 0),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "progress": job.get("progress", 0.0),
        "stageProgress": job.get("stageProgress"),
        "stageCompleted": job.get("stageCompleted"),
        "stageTotal": job.get("stageTotal"),
        "stageUnit": job.get("stageUnit", ""),
        "stageCompletedSeconds": job.get("stageCompletedSeconds"),
        "stageTotalSeconds": job.get("stageTotalSeconds"),
        "currentAction": job.get("currentAction"),
        "detail": job.get("detail"),
        "model": job.get("model"),
        "startedAt": job.get("startedAt"),
        "createdAt": job.get("createdAt"),
        "stageStartedAt": job.get("stageStartedAt"),
        "lastProgressAt": job.get("lastProgressAt"),
        "etaSeconds": job.get("etaSeconds"),
        "etaMode": job.get("etaMode", "collecting"),
        "progressMode": job.get("progressMode"),
        "progressFacts": job.get("progressFacts") or progress_facts_snapshot(job),
        "error": job.get("error"),
        "pendingDecision": job.get("pendingDecision"),
        "resumeAvailable": bool(job.get("resumeAvailable")),
        "messageCount": len(messages),
        # Messages are small and let the dialogue advance without fetching the
        # 80KB review document. Heavy candidate and plan data stay excluded.
        "messages": messages,
        "eventGroupCount": len(job.get("eventGroups") or []),
        "candidateCount": len(job.get("candidates") or []),
        "outputVersionCount": len(job.get("outputVersions") or []),
        "outputCount": job_output_count(job),
        "autoComposition": {
            key: auto.get(key)
            for key in (
                "status", "phase", "progress", "detail", "error", "versions",
                "completedVersions", "totalVersions", "currentVersion",
                "currentVersionProgress", "renderedSeconds", "renderTotalSeconds",
                "duplicatePlansSkipped",
            )
            if key in auto
        },
    }


def update_job(job_id: str, **patch: Any) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job.update(patch)
        job["updatedAt"] = now_iso()
        save_job(job)


def stage_progress_for(stage: str, overall: float, detail: str = "") -> float | None:
    """Return measured stage progress, never a percentage inferred from milestones."""
    text = str(detail or "")
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if match:
        total = max(1, int(match.group(2)))
        current = int(match.group(1))
        # VLM messages describe the item currently being processed. Starting
        # the first request is 0/total completed, not an instant jump to 20%
        # for a five-page analysis. Completed/rendered messages keep their
        # ordinary x/total meaning.
        if stage in {"coarse_vlm", "refine_vlm"} and "正在" in text:
            current = max(0, current - 1)
        return max(0.0, min(1.0, current / total))
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return max(0.0, min(1.0, float(match.group(1)) / 100.0))
    if stage in {"completed", "awaiting_confirmation", "edit_planning_complete"}:
        return 1.0
    # Finalization is real work but SenseVoice does not expose its internal
    # completion fraction. Returning a made-up 99% made a single callback look
    # like measured progress, so this stage intentionally becomes indeterminate.
    if stage in {"speech_recognition", "speech_analysis"} and "整理识别结果" in text:
        return None
    return None


def structured_progress(job: dict[str, Any], *, stage: str, overall: float, detail: str) -> dict[str, Any]:
    """Normalize progress facts so the UI never has to parse status prose."""
    now = now_iso()
    now_value = datetime.now(timezone.utc)
    previous_stage = str(job.get("stage") or "")
    stage_started_at = str(job.get("stageStartedAt") or "")
    if previous_stage != stage or not stage_started_at:
        stage_started_at = now
    text = str(detail or "")
    speech_finalizing = stage in {"speech_recognition", "speech_analysis"} and "整理识别结果" in text
    count_match = re.search(r"(?:第\s*)?(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    completed = total = None
    unit = ""
    current_item_index = None
    if count_match:
        completed, total = float(count_match.group(1)), max(1.0, float(count_match.group(2)))
        if completed.is_integer():
            completed = int(completed)
        if total.is_integer():
            total = int(total)
        if stage in {"coarse_vlm", "refine_vlm"} and "正在" in text:
            current_item_index = completed
            completed = max(0, completed - 1)
        if "候选" in text:
            unit = "候选"
        elif "组" in text:
            unit = "组"
        elif "方案" in text:
            unit = "方案"
        elif "镜头" in text or "片段" in text:
            unit = "镜头" if "镜头" in text else "片段"
        elif "帧" in text:
            unit = "帧"
        elif "秒" in text:
            unit = "秒"
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if percent_match and stage in {"speech_recognition", "speech_analysis"}:
        completed, total, unit = round(float(percent_match.group(1))), 100, "%"
    elif speech_finalizing:
        completed, total, unit = None, None, ""
    progress_mode = "finalizing" if speech_finalizing else ("determinate" if completed is not None and total else "indeterminate")
    model = {
        "speech_recognition": "SenseVoice", "speech_analysis": "SenseVoice",
        "coarse_vlm": "VLM", "refine_vlm": "VLM", "event_grouping": "VLM", "event_director": "VLM",
        "edit_planning": "LLM", "auto_composition": "LLM + VLM", "rendering": "FFmpeg",
    }.get(stage, "系统")
    started = job.get("startedAt") or job.get("createdAt")
    try:
        elapsed = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(str(started).replace("Z", "+00:00"))).total_seconds())
    except (TypeError, ValueError):
        elapsed = 0.0

    # Counted model stages report the item currently being processed (for
    # example 2/5), not the number already finished. Observe transitions from
    # one item to the next and learn the real average duration from those
    # completed units. This is substantially more useful than extrapolating a
    # long early model request from the weighted overall percentage.
    same_stage = previous_stage == stage
    observed_index = int(job.get("stageObservedIndex") or 0) if same_stage else 0
    sample_count = int(job.get("stageSampleCount") or 0) if same_stage else 0
    average_seconds = float(job.get("stageAverageSeconds") or 0.0) if same_stage else 0.0
    unit_started_at = str(job.get("stageUnitStartedAt") or "") if same_stage else ""
    try:
        unit_started_value = datetime.fromisoformat(unit_started_at.replace("Z", "+00:00")) if unit_started_at else now_value
    except (TypeError, ValueError):
        unit_started_value = now_value
        unit_started_at = now
    if completed is not None and total:
        current_index = max(1, min(int(current_item_index if current_item_index is not None else completed), int(total)))
        if not same_stage or observed_index <= 0:
            observed_index = current_index
            unit_started_at = now
            unit_started_value = now_value
            sample_count = 0
            average_seconds = 0.0
        elif current_index > observed_index:
            finished_units = current_index - observed_index
            sample_seconds = max(0.1, (now_value - unit_started_value).total_seconds()) / finished_units
            average_seconds = (
                (average_seconds * sample_count + sample_seconds * finished_units)
                / max(1, sample_count + finished_units)
            )
            sample_count += finished_units
            observed_index = current_index
            unit_started_at = now
            unit_started_value = now_value

    eta = None
    eta_mode = "collecting"
    if speech_finalizing:
        eta_mode = "finalizing"
    elif completed is not None and total and average_seconds > 0 and sample_count > 0:
        current_unit_elapsed = max(0.0, (now_value - unit_started_value).total_seconds())
        current_unit_remaining = max(0.0, average_seconds - current_unit_elapsed)
        later_units = max(0, int(total) - int(observed_index))
        eta = round(max(0.0, min(86400.0, current_unit_remaining + later_units * average_seconds)))
        eta_mode = "stage_average"
    elif completed is not None and total:
        eta_mode = "waiting_first_sample"
    elif overall > 0.03 and elapsed > 20:
        # A weighted pipeline milestone is not evidence of work throughput.
        # Deriving ETA from it makes the estimate grow while a model request is
        # waiting, so uncounted remote stages intentionally remain unestimated.
        eta_mode = "unavailable"
    return {
        "stageStartedAt": stage_started_at,
        "lastProgressAt": now,
        "stageCompleted": completed,
        "stageTotal": total,
        "stageUnit": unit,
        "currentAction": text,
        "model": model,
        "progressMode": progress_mode,
        "etaSeconds": eta,
        "etaMode": eta_mode,
        "stageObservedIndex": observed_index if completed is not None and total else None,
        "stageUnitStartedAt": unit_started_at if completed is not None and total else None,
        "stageAverageSeconds": round(average_seconds, 3) if average_seconds > 0 else None,
        "stageSampleCount": sample_count if completed is not None and total else 0,
    }


def append_message(job_id: str, role: str, text: str, *, kind: str = "message") -> None:
    with jobs_lock:
        job = jobs[job_id]
        messages = job.setdefault("messages", [])
        messages.append({
            "id": f"msg_{uuid.uuid4().hex}",
            "role": role,
            "text": text,
            "kind": kind,
            "createdAt": now_iso(),
        })
        job["updatedAt"] = now_iso()
        save_job(job)


def finalize_job_cancellation(job_id: str, *, message: str = "任务已取消") -> None:
    """Persist a terminal cancellation exactly once.

    Workers and the HTTP cancellation endpoint may observe the same signal at
    nearly the same time.  This helper keeps the final state idempotent and
    avoids filling the conversation with duplicate cancellation notices.
    """
    should_append = False
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        should_append = job.get("status") != "cancelled"
        job.update({
            "status": "cancelled", "stage": "cancelled",
            "detail": message, "currentAction": message,
            "etaSeconds": None, "etaMode": "stopped",
            "progressMode": "stopped", "pendingDecision": None,
            "updatedAt": now_iso(),
        })
        save_job(job)
    if should_append:
        append_message(job_id, "assistant", message, kind="notice")


def submit_analysis_task(job_id: str, target: Any, *args: Any) -> Future[Any]:
    """Submit one cancellable analysis task and retain its queue handle."""
    future = executor.submit(target, *args)
    with jobs_lock:
        analysis_futures[job_id] = future

    def forget(completed: Future[Any]) -> None:
        with jobs_lock:
            if analysis_futures.get(job_id) is completed:
                analysis_futures.pop(job_id, None)

    future.add_done_callback(forget)
    return future


def new_job_record(
    *,
    job_id: str,
    source: Path,
    filename: str,
    size: int,
    count: int | str,
    target_seconds: float | str,
    theme: str,
    messages: list[dict[str, Any]] | None = None,
    parent_job_id: str | None = None,
    excluded_ranges: list[dict[str, float]] | None = None,
    auto_recommend: bool = False,
    source_hash: str | None = None,
    analysis_mode: str = "audiovisual",
    total_target_seconds: float | None = None,
    force_reanalyze: bool = False,
    require_brief: bool = False,
) -> dict[str, Any]:
    created = now_iso()
    return {
        "id": job_id,
        "status": "briefing" if require_brief else "queued",
        "progress": 0.0,
        "stageProgress": 0.0,
        "stage": "queued",
        "detail": "任务已进入队列",
        "stageCompleted": None,
        "stageTotal": None,
        "stageUnit": "",
        "stageCompletedSeconds": None,
        "stageTotalSeconds": None,
        "currentAction": "任务已进入队列",
        "model": "系统",
        "stageStartedAt": created,
        "lastProgressAt": created,
        "etaSeconds": None,
        "etaMode": "collecting",
        "progressMode": "indeterminate",
        "error": None,
        "brief": {},
        "briefStatus": "pending" if require_brief else "confirmed",
        "briefSource": "pending" if require_brief else "user",
        "briefVersion": BRIEF_PROMPT_VERSION,
        "autoCompose": True,
        "filename": filename,
        "sizeBytes": size,
        "sourceHash": source_hash,
        "visionConfig": vision_store.snapshot(),
        "llmConfig": llm_store.snapshot(),
        "request": {
            "count": count,
            "targetSeconds": target_seconds,
            "totalTargetSeconds": total_target_seconds,
            "durationTolerance": .1,
            "theme": theme.strip(),
            "autoRecommend": auto_recommend,
            "analysisMode": analysis_mode,
            "forceReanalyze": force_reanalyze,
        },
        "outputs": [],
        "outputVersions": [],
        "currentOutputVersionId": None,
        "messages": messages or [],
        "parentJobId": parent_job_id,
        "excludedRanges": excluded_ranges or [],
        "sourcePath": str(source),
        "workDirectory": str(settings.data_root / "work" / job_id),
        "outputDirectory": str(settings.data_root / "outputs" / job_id),
        "createdAt": created,
        "updatedAt": created,
    }


def _fallback_brief(job: dict[str, Any]) -> dict[str, Any]:
    request = job.get("request") or {}
    raw_target = request.get("totalTargetSeconds")
    try:
        target = float(raw_target) if raw_target not in (None, "", "auto") else None
    except (TypeError, ValueError):
        target = None
    return {
        "objective": "事件高光合集",
        "narrativeGoal": "保留真实事件中的精彩瞬间并组合成完整成片",
        "targetDurationSeconds": target,
        "eventCount": request.get("count", "auto"),
        "focus": [request.get("theme")] if request.get("theme") else ["综合判断"],
        "style": {"pace": "自然", "tone": "纪实自然", "allowReorder": False},
        "audience": "", "platform": "", "aspectRatio": "原始比例", "speakerFocus": [],
        "includeRules": [], "excludeRules": [], "subtitlePreference": request.get("subtitleMode", "none"),
        "subtitleStyle": normalize_subtitle_style(request.get("subtitleStyle")),
        "editMode": request.get("editMode", "ai_plan"), "structure": request.get("structure", "auto"),
        "assumptions": ["需求理解服务不可用，已按原始表单继续"], "confidence": 0.35,
    }


def _confirmed_brief_from_request(request: dict[str, Any]) -> dict[str, Any]:
    """Build the brief from the upload form that the user already confirmed.

    The upload form is itself an explicit confirmation.  Keeping this small
    structured copy lets the VLM/LLM receive the same constraints without
    showing a second blocking confirmation card.
    """
    theme = str(request.get("theme") or "").strip()
    focus = [part.strip() for part in re.split(r"[，,、;；\n]+", theme) if part.strip()]
    return {
        "objective": "事件高光合集",
        "narrativeGoal": "先发现真实精彩事件，再把同一事件的镜头编排成完整成片",
        "targetDurationSeconds": request.get("totalTargetSeconds"),
        "eventCount": request.get("count", "auto"),
        "focus": focus or ["综合判断"],
        "style": {"pace": "自然", "tone": "纪实自然", "allowReorder": request.get("editMode") == "ai_plan"},
        "includeRules": ["关键事件", "完整表达"],
        "excludeRules": ["重复镜头", "片头广告"],
        "subtitlePreference": request.get("subtitleMode", "none"),
        "subtitleStyle": normalize_subtitle_style(request.get("subtitleStyle")),
        "editMode": request.get("editMode", "ai_plan"),
        "structure": request.get("structure", "auto"),
        "assumptions": ["用户已在上传前置表单确认以上要求"],
        "confidence": 1.0,
    }


def run_brief_generation(job_id: str) -> None:
    client: Any = None
    with jobs_lock:
        cancel_event = cancel_events.get(job_id)

    def finish_cancelled_brief() -> None:
        finalize_job_cancellation(job_id)
        with jobs_lock:
            if cancel_events.get(job_id) is cancel_event:
                cancel_events.pop(job_id, None)

    if cancel_event is None or cancel_event.is_set():
        finish_cancelled_brief()
        return
    try:
        with jobs_lock:
            job = jobs[job_id]
            update_job(
                job_id, progress=.04, stage="briefing", stageProgress=None,
                stageCompleted=None, stageTotal=None, stageUnit="",
                detail="LLM 正在理解剪辑目标、重点和限制",
                currentAction="LLM 正在理解剪辑目标、重点和限制",
                model="LLM", progressMode="indeterminate", etaSeconds=None, etaMode="unavailable",
            )
            request = job.get("request") or {}
        prompt = user_brief_prompt(
            filename=str(job.get("filename") or ""), theme=str(request.get("theme") or ""),
            count=str(request.get("count") or "auto"), target_seconds=str(request.get("totalTargetSeconds") or "auto"),
            analysis_mode=str(request.get("analysisMode") or "audiovisual"),
            subtitle_mode=str(request.get("subtitleMode") or "none"),
            edit_mode=str(request.get("editMode") or "ai_plan"),
            structure=str(request.get("structure") or "auto"),
        )
        if cancel_event.is_set():
            raise RuntimeError("任务已取消")
        client = create_llm_client_for_job(job)
        with jobs_lock:
            active_ark_clients[job_id] = client
        brief = client.complete_json(prompt, maximum_tokens=1800, system_prompt=COMMON_SYSTEM_PROMPT)
        if cancel_event.is_set():
            raise RuntimeError("任务已取消")
        brief.pop("_usage", None)
        source = "llm"
    except Exception as error:
        if cancel_event.is_set():
            finish_cancelled_brief()
            return
        brief = _fallback_brief(jobs[job_id])
        source = "fallback"
        append_message(job_id, "assistant", f"需求理解暂不可用，已按原始要求生成简报：{str(error)[:180]}", kind="warning")
    finally:
        with jobs_lock:
            if active_ark_clients.get(job_id) is client:
                active_ark_clients.pop(job_id, None)
    if cancel_event.is_set():
        finish_cancelled_brief()
        return
    with jobs_lock:
        job = jobs[job_id]
        if cancel_event.is_set() or job.get("status") in {"cancelled", "cancelling"}:
            finish_cancelled_brief()
            return
        job.update({"status": "brief_confirmation", "stage": "brief_confirmation", "progress": .12, "detail": "需求简报已生成，等待确认", "brief": brief, "briefStatus": "pending", "briefSource": source, "briefVersion": BRIEF_PROMPT_VERSION, "updatedAt": now_iso()})
        save_job(job)
    append_message(job_id, "assistant", "我已整理出一份剪辑需求简报，请确认后再开始视觉分析。", kind="brief")


def enqueue_job(job: dict[str, Any]) -> None:
    with jobs_lock:
        jobs[job["id"]] = job
        cancel_events[job["id"]] = threading.Event()
        save_job(job)
    submit_analysis_task(job["id"], run_brief_generation if job.get("briefStatus") == "pending" else run_job, job["id"])


def run_job(job_id: str, resume_action: str | None = None) -> None:
    with jobs_lock:
        job = jobs[job_id]
        cancel_event = cancel_events[job_id]
    client: Any = None
    try:
        if cancel_event.is_set():
            raise RuntimeError("任务已取消")
        vision_config = vision_store.resolve(snapshot=job.get("visionConfig") if isinstance(job.get("visionConfig"), dict) else None)
        missing_vision = [label for label, value in (
            ("API Key", vision_config.get("apiKey")),
            ("视觉模型", vision_config.get("model")),
            ("接口地址", vision_config.get("baseUrl")),
        ) if not value]
        if missing_vision:
            raise RuntimeError(f"视觉模型尚未配置：{', '.join(missing_vision)}。请在右上角设置中完成配置")
        update_job(
            job_id,
            status="running", progress=0.01, stage="starting", stageProgress=0.0,
            stageCompleted=None, stageTotal=None, stageUnit="",
            stageCompletedSeconds=None, stageTotalSeconds=None,
            startedAt=now_iso(), stageStartedAt=now_iso(), lastProgressAt=now_iso(),
            detail="正在启动视觉高光分析", currentAction="正在启动视觉高光分析",
            model="系统", etaSeconds=None, etaMode="collecting",
            progressMode="indeterminate", error=None,
            stageObservedIndex=None, stageUnitStartedAt=None,
            stageAverageSeconds=None, stageSampleCount=0,
        )
        client = create_vision_client(
            provider=str(vision_config["provider"]),
            api_key=str(vision_config["apiKey"]),
            model=str(vision_config["model"]),
            base_url=str(vision_config["baseUrl"]),
            thinking_type=str(vision_config["thinkingType"]),
            response_format=str(vision_config["responseFormat"]),
            timeout_seconds=float(vision_config["timeoutSeconds"]),
        )
        with jobs_lock:
            active_ark_clients[job_id] = client
        pipeline = HighlightPipeline(
            client=client,
            ffmpeg=settings.ffmpeg,
            ffprobe=settings.ffprobe,
            selection_backend=f"{vision_config['provider']}-vlm",
        )

        def progress(value: float, stage: str, detail: str) -> None:
            if cancel_event.is_set():
                return
            with jobs_lock:
                current_job = jobs.get(job_id, {})
                previous_overall = float(current_job.get("progress") or 0.0)
                overall = round(max(previous_overall, max(0.0, min(1.0, value))), 4)
                progress_facts = structured_progress(current_job, stage=stage, overall=overall, detail=detail)
            measured_stage_progress = stage_progress_for(stage, overall, detail)
            update_job(
                job_id,
                progress=overall,
                stage=stage,
                stageProgress=round(measured_stage_progress, 4) if measured_stage_progress is not None else None,
                detail=detail,
                **progress_facts,
            )

        automatic = bool(job["request"].get("autoRecommend"))
        requested_count = None if str(job["request"].get("count", "auto")).lower() == "auto" else int(job["request"]["count"])
        raw_total_target = job["request"].get("totalTargetSeconds")
        total_target_seconds = None if raw_total_target in (None, "", "auto") else float(raw_total_target)
        exclusions = [
            (float(item["start"]), float(item["end"]))
            for item in job.get("excludedRanges", [])
            if isinstance(item, dict) and "start" in item and "end" in item
        ]
        source_hash = str(job.get("sourceHash") or "")
        analysis_mode = str(job["request"].get("analysisMode") or "visual")
        brief = job.get("brief") or {}
        analysis_theme = str(job["request"].get("theme") or "")
        if brief:
            analysis_theme = f"{analysis_theme}\n结构化剪辑简报：{json.dumps(brief, ensure_ascii=False)}"
        # CAM++ speaker separation is expensive. Keep the fast SenseVoice
        # path by default, but enable diarization when the user explicitly
        # asks for speaker/person-based selection or when it is configured as
        # a global requirement.
        speaker_requested = bool(re.search(r"说话人|speaker|男生|女生|男性|女性|按人物|人物筛选", analysis_theme, re.IGNORECASE))
        use_diarization = settings.sensevoice_diarization or speaker_requested
        cache_key = analysis_cache_key(
            source_hash,
            analysis_theme,
            analysis_mode,
            requested_count,
            total_target_seconds,
            job.get("visionConfig") if isinstance(job.get("visionConfig"), dict) else None,
        ) if source_hash and not exclusions else ""
        manifest = load_analysis_cache(cache_key) if cache_key and analysis_cache_reuse_allowed(job, resume_action) else None
        cache_hit = manifest is not None
        if manifest is not None:
            progress(0.96, "cache_hit", "检测到相同视频和分析要求，正在复用已验证候选")
        else:
            scene_cuts: list[float] = []
            if source_hash:
                timeline_metadata_path, _ = timeline_cache_paths(source_hash)
                if timeline_metadata_path.is_file():
                    try:
                        timeline_metadata = json.loads(timeline_metadata_path.read_text(encoding="utf-8"))
                        if timeline_metadata.get("sceneCutsReady") is True:
                            scene_cuts = [float(value) for value in timeline_metadata.get("sceneCuts") or []]
                    except (OSError, ValueError, TypeError):
                        scene_cuts = []
            manifest = pipeline.run(
                source=Path(job["sourcePath"]),
                work_directory=Path(job["workDirectory"]),
                output_directory=Path(job["outputDirectory"]),
                count=requested_count or 6,
                target_seconds=8.0,
                theme=analysis_theme,
                progress=progress,
                cancelled=cancel_event.is_set,
                excluded_ranges=exclusions,
                automatic_duration=True,
                discovery_only=True,
                analysis_mode=analysis_mode,
                whisper_model=settings.whisper_model,
                whisper_device=settings.whisper_device,
                speech_engine=settings.speech_engine,
                sensevoice_model=settings.sensevoice_model,
                sensevoice_device=settings.sensevoice_device,
                sensevoice_vad_model=settings.sensevoice_vad_model,
                sensevoice_punc_model=settings.sensevoice_punc_model,
                sensevoice_spk_model=settings.sensevoice_spk_model,
                sensevoice_diarization=use_diarization,
                speech_model_cache=settings.speech_model_cache,
                total_target_seconds=total_target_seconds,
                requested_count=requested_count,
                resume_action=resume_action,
                scene_cuts=scene_cuts,
            )
            if cache_key:
                save_analysis_cache(cache_key, manifest)
        if cancel_event.is_set():
            raise RuntimeError("任务已取消")
        if manifest.get("eventGroups"):
            update_job(
                job_id,
                status="awaiting_confirmation",
                progress=1.0,
                stageProgress=1.0,
                stage="awaiting_confirmation",
                detail=f"VLM 精修保留 {manifest['candidateCount']} 个候选镜头，已归并为 {manifest['eventGroupCount']} 个精彩事件",
                currentAction="视觉分析已完成，事件审核已就绪",
                model="VLM",
                progressMode="completed",
                etaSeconds=None,
                etaMode="completed",
                candidates=manifest["candidates"],
                eventGroups=manifest["eventGroups"],
                recommendedGroupIds=manifest["recommendedGroupIds"],
                recommendedIndices=[],
                recommendedCount=manifest["recommendedCount"],
                allocatedTotalSeconds=manifest.get("allocatedTotalSeconds"),
                totalTargetSeconds=manifest.get("totalTargetSeconds"),
                durationTolerance=manifest.get("durationTolerance", .1),
                durationUpperLimit=manifest.get("durationUpperLimit"),
                eventReductionReason=manifest.get("eventReductionReason", ""),
                durationStatus=manifest.get("durationStatus"),
                durationGap=manifest.get("durationGap", 0.0),
                videoInfo=manifest["video"],
                contentProfile=manifest.get("contentProfile"),
                speechAnalysis=manifest.get("speechAnalysis"),
                selectionBackend=manifest.get("selectionBackend") or f"{settings.vision_provider}-vlm",
                promptVersion=manifest.get("promptVersion", PROMPT_VERSION),
                directorDegraded=bool(manifest.get("directorDegraded")),
                pendingDecision=None,
                modelUsage=[] if cache_hit else manifest.get("usage", []),
                analysisCacheHit=cache_hit,
                analysisCacheKey=cache_key or None,
                **({"autoComposition": {
                    "status": "queued", "phase": "queued", "progress": 0.0,
                    "versions": [], "completedVersions": 0,
                    "totalVersions": max(1, min(4, int(job.get("request", {}).get("autoVariantCount") or 3))),
                    "currentVersion": 1, "currentVersionProgress": 0.0, "error": None,
                    "detail": "自动成片已排队，事件审核已就绪",
                }} if bool(job.get("autoCompose", True)) else {}),
            )
            duration_text = f"，推荐事件合计 {float(manifest.get('allocatedTotalSeconds') or 0):.1f} 秒"
            if manifest.get("totalTargetSeconds"):
                duration_text += f"（目标 {float(manifest['totalTargetSeconds']):.1f} 秒）"
            degraded_text = " 事件归组使用了本地降级规则，建议重点审核镜头组合。" if manifest.get("directorDegraded") else ""
            reduction_text = (
                f" {str(manifest.get('eventReductionReason')).rstrip('。')}；系统优先保留完整表达，不会为凑事件数截断对白。"
                if manifest.get("eventReductionReason") else ""
            )
            append_message(
                job_id,
                "assistant",
                f"{'已复用相同视频的分析结果：' if cache_hit else '事件整理完成：'}视觉模型保留 {manifest['candidateCount']} 个候选镜头，归并为 {manifest['eventGroupCount']} 个高光事件；当前推荐 {manifest['recommendedCount']} 个事件{duration_text}。{reduction_text}可以把已选事件合成 1 条视频，也可以分别导出。{degraded_text}",
                kind="recommendation",
            )
            for group_id in manifest.get("recommendedGroupIds", [])[:3]:
                preview_executor.submit(prepare_event_group_preview, job_id, group_id)
            if bool(job.get("autoCompose", True)):
                render_executor.submit(run_automatic_composition, job_id)
            return
        update_job(
            job_id,
            status="completed",
            progress=1.0 if finalize_status else .82,
            stageProgress=1.0 if finalize_status else 0.0,
            stage="completed",
            detail=f"已生成 {manifest['actualCount']} 个视觉高光片段",
            currentAction="视觉分析和裁剪已完成",
            progressMode="completed",
            etaSeconds=None,
            etaMode="completed",
            outputs=manifest["outputs"],
            actualCount=manifest["actualCount"],
        )
        append_message(
            job_id,
            "assistant",
            f"视觉分析和裁剪已完成，生成 {manifest['actualCount']} 条互不重叠的高光。可以播放审核，也可以下载或换掉某一条。",
            kind="result",
        )
    except ModelDecisionRequired as error:
        if cancel_event.is_set():
            finalize_job_cancellation(job_id)
            return
        stage_name = {
            "content_classification": "内容类型识别",
            "speech_analysis": "SenseVoice 富语音分析",
            "event_director": "事件高光导演",
        }.get(error.stage, "模型分析")
        with jobs_lock:
            work_directory = Path(jobs[job_id]["workDirectory"])
        saved = load_analysis_checkpoint(work_directory) or {}
        preserved: dict[str, Any] = {}
        if isinstance(saved.get("video"), dict):
            preserved["videoInfo"] = saved["video"]
        if isinstance(saved.get("contentProfile"), dict):
            preserved["contentProfile"] = saved["contentProfile"]
        if isinstance(saved.get("speechAnalysis"), dict):
            preserved["speechAnalysis"] = saved["speechAnalysis"]
        if error.stage == "event_director" and isinstance(saved.get("candidates"), list):
            preserved["candidates"] = saved["candidates"]
        update_job(
            job_id,
            status="awaiting_model_decision",
            stage=error.stage,
            detail=f"{stage_name}多次请求仍未成功，需要选择处理方式",
            error=None,
            pendingDecision={
                "stage": error.stage,
                "stageLabel": stage_name,
                "error": str(error)[:800],
                "attempts": error.attempts,
                "actions": ["retry", "fallback", "cancel"],
            },
            promptVersion=saved.get("promptVersion", PROMPT_VERSION),
            **preserved,
        )
        append_message(
            job_id,
            "assistant",
            (
                f"{stage_name}未完成。原因：{str(error)[:300]}。已经完成的画面和分析检查点均已保留。"
                + (
                    "语音仅用于辅助判断。可以直接选择“继续视觉分析”完成高光分析，也可以重试语音分析；继续视觉分析时不会使用对白、情绪、声音事件和说话人信息。"
                    if error.stage == "speech_analysis"
                    else "可以重试当前阶段、按降级规则继续或取消任务。"
                )
            ),
            kind="decision",
        )
    except Exception as error:
        cancelled = cancel_event.is_set()
        if cancelled:
            finalize_job_cancellation(job_id)
        else:
            update_job(
                job_id,
                status="failed", stage="failed",
                detail="视觉高光分析失败", currentAction="视觉高光分析失败",
                etaSeconds=None, etaMode="stopped", progressMode="stopped",
                error=str(error)[:2000],
            )
            append_message(
                job_id, "assistant", f"这次高光分析没有完成：{str(error)[:500]}", kind="error",
            )
    finally:
        with jobs_lock:
            if cancel_events.get(job_id) is cancel_event:
                cancel_events.pop(job_id, None)
            if active_ark_clients.get(job_id) is client:
                active_ark_clients.pop(job_id, None)


def run_automatic_composition(job_id: str) -> None:
    """Create one direct VLM recommendation and several LLM-reviewed versions.

    Analysis remains reusable: this worker only consumes the discovered event
    pool and appends output versions. It never replaces the source or deletes
    earlier versions.
    """
    # A retry or a repeated analysis can otherwise enqueue two workers for the
    # same job.  They would race on outputVersions and cancel_events, making a
    # perfectly valid automatic render look like a failed one.  The in-memory
    # guard is intentionally process-local; load_jobs() already marks workers
    # interrupted after a service restart, so a subsequent analysis can start
    # a fresh automatic composition.
    with automatic_composition_lock:
        if job_id in active_automatic_compositions:
            return
        active_automatic_compositions.add(job_id)
    try:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job or job.get("status") != "awaiting_confirmation":
                return
            group_ids = [str(value) for value in job.get("recommendedGroupIds", [])]
            if not group_ids:
                raise RuntimeError("没有可用于自动合成的推荐事件")
            requested_versions = max(1, min(4, int(job.get("request", {}).get("autoVariantCount") or 3)))
            llm_version_count = max(0, requested_versions - 1)
            target = job.get("totalTargetSeconds") or job.get("request", {}).get("totalTargetSeconds")
            subtitle_mode = str((job.get("brief") or {}).get("subtitlePreference") or job.get("request", {}).get("subtitleMode") or "none")
            subtitle_mode = "burn" if subtitle_mode == "burn" else "none"
            subtitle_style = normalize_subtitle_style((job.get("brief") or {}).get("subtitleStyle") or job.get("request", {}).get("subtitleStyle"))
            # Automatic versions are a background enhancement of the review
            # pool. Keep the primary job in review state so the user can
            # inspect and confirm events while these versions render.
            job["autoComposition"] = {
                "status": "running", "phase": "vlm_render", "versions": [], "error": None,
                "progress": 0.0, "completedVersions": 0, "totalVersions": requested_versions,
                "currentVersion": 1, "currentVersionProgress": 0.0,
                "detail": f"正在生成第 1/{requested_versions} 个版本 · 完整事件版",
            }
            job.update({"status": "awaiting_confirmation", "stage": "auto_composition", "progress": 1.0, "stageProgress": 1.0, "detail": "事件审核已就绪；自动成片在后台生成", "currentAction": "自动成片在后台生成", "model": "VLM + FFmpeg", "stageCompleted": 0, "stageTotal": requested_versions, "stageUnit": "版本", "progressMode": "background", "etaSeconds": None, "error": None, "pendingSelectionGroupIds": []})
            cancel_events[job_id] = threading.Event()
            save_job(job)
        append_message(job_id, "assistant", "视觉模型已完成事件发现，正在先生成保留事件完整过程的版本。", kind="auto-compose")
        vlm_meta = auto_composition_meta("vlm")
        run_confirmed_render(job_id, group_ids, "single_reel", "complete", vlm_meta["sourceLabel"], False, None, vlm_meta["displayName"], None, subtitle_mode, "source", subtitle_style, auto_meta=vlm_meta, background_auto=True)

        if llm_version_count == 0:
            with jobs_lock:
                job = jobs.get(job_id)
                if not job:
                    return
                job.setdefault("autoComposition", {}).update({
                    "status": "completed", "phase": "done", "versions": [vlm_meta],
                    "progress": 1.0, "completedVersions": 1, "totalVersions": 1,
                    "currentVersion": None, "currentVersionProgress": 1.0,
                    "detail": "自动成片版本已生成",
                })
                job["stageCompleted"] = 1
                job["stageTotal"] = 1
                job["progressMode"] = "completed"
                job["etaSeconds"] = None
                job["etaMode"] = "completed"
                job["currentAction"] = "自动成片版本已生成"
                job["detail"] = "已生成 1 个自动高光版本，可直接预览"
                save_job(job)
            append_message(job_id, "assistant", f"自动成片已完成：已生成 {vlm_meta['displayName']}，可直接预览比较。", kind="auto-compose")
            return

        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return
            job.setdefault("autoComposition", {}).update({
                "phase": "llm_plan", "versions": [vlm_meta],
                "progress": round(1 / requested_versions, 4),
                "completedVersions": 1, "totalVersions": requested_versions,
                "currentVersion": 2, "currentVersionProgress": 0.0,
                "renderedSeconds": 0.0, "renderTotalSeconds": None,
                "detail": f"剪辑规划模型正在生成剩余 {llm_version_count} 个版本",
            })
            save_job(job)
        append_message(job_id, "assistant", f"{vlm_meta['displayName']}已完成（{vlm_meta['strategyDescription']}），剪辑规划模型正在根据画面、声音、对白和目标时长生成其他版本。", kind="auto-compose")
        run_auto_plan_generation(job_id, AutoPlanRequest(scope="all_pool", groupIds=group_ids, targetSeconds=float(target) if target not in (None, "", "auto") else None, structure=str((job.get("brief") or {}).get("structure") or "auto"), variantCount=llm_version_count), background_auto=True)
        with jobs_lock:
            job = jobs.get(job_id)
            plans = list(job.get("autoPlans") or []) if job else []
            if not job:
                return
            if not plans:
                job["autoComposition"].update({
                    "status": "completed", "phase": "done", "error": "LLM 未生成可用方案",
                    "progress": 1.0, "completedVersions": 1, "totalVersions": 1,
                    "currentVersion": None, "currentVersionProgress": 1.0,
                    "versions": [vlm_meta],
                })
                job["status"] = "completed"
                job["stage"] = "completed"
                job["progress"] = 1.0
                job["stageProgress"] = 1.0
                job["detail"] = "完整事件版已生成；剪辑规划模型未返回可用方案"
                job["currentAction"] = "完整事件版已生成"
                job["progressMode"] = "completed"
                job["etaSeconds"] = None
                job["etaMode"] = "completed"
                save_job(job)
                return
            # Do not present cosmetic variants as separate cuts. A plan is
            # considered different only when its candidate order or at least
            # one local source boundary changes. Include the initial VLM reel
            # in the same set: otherwise the first LLM plan can reproduce the
            # VLM selection byte-for-byte while being shown as a new version.
            distinct_plans: list[dict[str, Any]] = []
            vlm_output = next((item for item in (job.get("outputs") or []) if item.get("segments")), None)
            vlm_signature = automatic_composition_signature(vlm_output.get("segments") if vlm_output else None)
            seen_signatures: list[tuple[tuple[str, float, float], ...]] = [vlm_signature] if vlm_signature else []
            duplicate_plan_count = 0
            for candidate_plan in plans:
                signature = automatic_composition_signature(candidate_plan.get("sequence"))
                if not signature or any(
                    signature == previous or automatic_composition_similarity(signature, previous) >= .85
                    for previous in seen_signatures
                ):
                    duplicate_plan_count += 1
                    continue
                seen_signatures.append(signature)
                distinct_plans.append(candidate_plan)
                if len(distinct_plans) >= llm_version_count:
                    break
            replacement_plans = distinct_event_replacement_plans(
                job,
                seen_signatures,
                llm_version_count - len(distinct_plans),
                float(target) if target not in (None, "", "auto") else None,
            )
            plans = [*distinct_plans, *replacement_plans]
            duplicate_plans_replaced = len(replacement_plans)
            duplicate_plans_skipped = max(0, duplicate_plan_count - duplicate_plans_replaced)
            actual_total_versions = 1 + len(plans)
            job["autoComposition"].update({
                "phase": "llm_render",
                "duplicatePlansDetected": duplicate_plan_count,
                "duplicatePlansReplaced": duplicate_plans_replaced,
                "duplicatePlansSkipped": duplicate_plans_skipped,
                "totalVersions": actual_total_versions,
                "completedVersions": 1,
                "currentVersion": 2 if plans else None,
                "currentVersionProgress": 0.0 if plans else 1.0,
                "renderedSeconds": 0.0, "renderTotalSeconds": None,
                "progress": round(1 / actual_total_versions, 4),
                "detail": f"准备生成第 2/{actual_total_versions} 个版本" if plans else "未发现与首版有实质差异的审核方案",
            })
            save_job(job)
        for index, plan in enumerate(plans):
            with jobs_lock:
                job = jobs.get(job_id)
                if not job:
                    return
                cancel_events[job_id] = threading.Event()
                job["status"] = "awaiting_confirmation"
                job["stage"] = "auto_composition"
                job["progress"] = 1.0
                job["stageProgress"] = 1.0
                total_versions = 1 + len(plans)
                current_version = index + 2
                job["autoComposition"]["progress"] = round((current_version - 1) / total_versions, 4)
                job["autoComposition"]["completedVersions"] = current_version - 1
                job["autoComposition"]["totalVersions"] = total_versions
                job["autoComposition"]["currentVersion"] = current_version
                job["autoComposition"]["currentVersionProgress"] = 0.0
                job["autoComposition"]["renderedSeconds"] = 0.0
                job["autoComposition"]["renderTotalSeconds"] = None
                job["autoComposition"]["detail"] = f"正在生成第 {current_version}/{total_versions} 个版本 · {plan.get('label') or '剪辑规划版'}"
                job["detail"] = "事件审核已就绪；" + job["autoComposition"]["detail"]
                job["currentAction"] = job["detail"]
                job["model"] = "LLM + FFmpeg"
                job["stageCompleted"] = index + 1
                job["stageTotal"] = len(plans) + 1
                job["stageUnit"] = "版本"
                job["progressMode"] = "background"
                job["lastProgressAt"] = now_iso()
                save_job(job)
            plan_label = str(plan.get("label") or f"叙事方案 {index + 1}")
            plan_meta = dict(plan.get("autoMeta") or auto_composition_meta("llm", plan_label))
            run_confirmed_render(job_id, [], "single_reel", "complete", plan_meta["sourceLabel"], index == len(plans) - 1, list(plan.get("sequence") or []), plan_meta["displayName"], list(plan.get("chapters") or []), subtitle_mode, "selection", subtitle_style, auto_meta=plan_meta, background_auto=True)
            with jobs_lock:
                job = jobs.get(job_id)
                if not job:
                    return
                completed_meta = [vlm_meta] + [
                    dict(item.get("autoMeta") or auto_composition_meta("llm", str(item.get("label") or f"叙事方案 {plan_index + 1}")))
                    for plan_index, item in enumerate(plans[:index + 1])
                ]
                completed_count = len(completed_meta)
                job.setdefault("autoComposition", {}).update({
                    "versions": completed_meta,
                    "completedVersions": completed_count,
                    "totalVersions": 1 + len(plans),
                    "progress": round(completed_count / (1 + len(plans)), 4),
                    "currentVersion": completed_count + 1 if completed_count < 1 + len(plans) else None,
                    "currentVersionProgress": 0.0 if completed_count < 1 + len(plans) else 1.0,
                    "renderedSeconds": 0.0 if completed_count < 1 + len(plans) else job.get("autoComposition", {}).get("renderedSeconds"),
                    "renderTotalSeconds": None if completed_count < 1 + len(plans) else job.get("autoComposition", {}).get("renderTotalSeconds"),
                })
                save_job(job)
        with jobs_lock:
            job = jobs.get(job_id)
            if job:
                version_meta = [vlm_meta] + [dict(plan.get("autoMeta") or auto_composition_meta("llm", str(plan.get("label") or f"叙事方案 {index + 1}"))) for index, plan in enumerate(plans)]
                job["autoComposition"].update({"status": "completed", "phase": "done", "versions": version_meta, "planIds": [plan.get("id") for plan in plans]})
                job["autoComposition"]["progress"] = 1.0
                job["autoComposition"]["completedVersions"] = len(version_meta)
                job["autoComposition"]["totalVersions"] = len(version_meta)
                job["autoComposition"]["currentVersion"] = None
                job["autoComposition"]["currentVersionProgress"] = 1.0
                job["autoComposition"]["detail"] = (
                    f"自动成片已完成，{duplicate_plans_replaced} 个重复方案已改用其他事件"
                    if duplicate_plans_replaced else (
                        f"自动成片已完成，{duplicate_plans_skipped} 个重复方案已合并"
                        if duplicate_plans_skipped else "自动成片版本已全部生成"
                    )
                )
                job["stageProgress"] = 1.0
                job["stageCompleted"] = len(version_meta)
                job["stageTotal"] = len(version_meta)
                job["stageUnit"] = "版本"
                job["currentAction"] = "自动成片版本已全部生成"
                job["lastProgressAt"] = now_iso()
                job["progressMode"] = "completed"
                job["etaSeconds"] = None
                job["etaMode"] = "completed"
                job["detail"] = (
                    f"已生成 {len(version_meta)} 个不同的自动高光版本，{duplicate_plans_replaced} 个重复方案已改用其他事件"
                    if duplicate_plans_replaced else (
                        f"已保留 {len(version_meta)} 个不同的自动高光版本，{duplicate_plans_skipped} 个重复方案已合并"
                        if duplicate_plans_skipped else f"已生成 {len(version_meta)} 个自动高光版本，可直接预览比较"
                    )
                )
                save_job(job)
        duplicate_text = (
            f"检测到 {duplicate_plans_replaced} 个重复方案，已自动改用其他高分事件。"
            if duplicate_plans_replaced else (
                f"另有 {duplicate_plans_skipped} 个与已有成片重复的方案已自动合并。"
                if duplicate_plans_skipped else ""
            )
        )
        append_message(job_id, "assistant", f"自动成片已完成：已生成 {len(version_meta)} 个不同版本（{vlm_meta['displayName']} 1 个、剪辑规划版本 {len(plans)} 个）。{duplicate_text}源视频保持不变，可直接预览比较。", kind="auto-compose")
    except Exception as error:
        error_text = str(error)[:800]
        with jobs_lock:
            job = jobs.get(job_id)
            if job:
                has_outputs = bool(job.get("outputs") or any(version.get("outputs") for version in job.get("outputVersions", [])))
                job.setdefault("autoComposition", {}).update({"status": "partial", "phase": "done", "error": error_text, "hasOutputs": has_outputs})
                if has_outputs:
                    job["status"] = "completed"
                    job["stage"] = "completed"
                    job["progress"] = 1.0
                    job["stageProgress"] = 1.0
                    job["detail"] = "完整事件版已生成，其他剪辑规划版本生成失败"
                    job["currentAction"] = "自动成片部分完成"
                    job["progressMode"] = "completed"
                    job["etaSeconds"] = None
                    job["etaMode"] = "completed"
                else:
                    job["status"] = "failed"
                    job["stage"] = "failed"
                    job["error"] = f"自动成片未生成视频：{error_text}"[:2000]
                    job["currentAction"] = "自动成片生成失败"
                    job["progressMode"] = "stopped"
                    job["etaSeconds"] = None
                    job["etaMode"] = "stopped"
                save_job(job)
        append_message(job_id, "assistant", f"自动成片未生成视频：{error_text[:300]}", kind="warning")
    finally:
        with automatic_composition_lock:
            active_automatic_compositions.discard(job_id)


def _variant_selections(selections: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "complete":
        return selections
    result = copy.deepcopy(selections)
    for selection in result:
        segments = list(selection.get("segments") or [])
        if len(segments) <= 1:
            continue
        if mode == "tight":
            keep = max(1, round(len(segments) * .65))
            segments = sorted(segments, key=lambda item: (-float(item.get("score") or 0), float(item.get("start") or 0)))[:keep]
            segments.sort(key=lambda item: float(item.get("editOrder") or item.get("start") or 0))
        elif mode == "climax":
            peak = max(range(len(segments)), key=lambda index: float(segments[index].get("score") or 0))
            indices = {peak}
            if peak > 0: indices.add(peak - 1)
            if peak + 1 < len(segments): indices.add(peak + 1)
            segments = [segment for index, segment in enumerate(segments) if index in indices]
        selection["segments"] = segments
    return result


def _choose_auto_segment_ids(job: dict[str, Any], group_ids: list[Any], mode: str, target: float) -> dict[str, list[str]]:
    groups = [group for group in job.get("eventGroups", []) if str(group.get("id")) in {str(value) for value in group_ids}]
    pool: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for group in groups:
        # `segments` contains the currently selected storyboard shots while
        # `availableSegments` is the analyzed candidate pool for that event.
        # Auto composition may draw from both, so a short manual selection does
        # not artificially cap a requested 60s (or 90s) reel.
        seen: set[str] = set()
        for segment in [*(group.get("segments") or []), *(group.get("availableSegments") or [])]:
            segment_id = str(segment.get("id") or f"{segment.get('start')}:{segment.get('end')}")
            if segment_id in seen:
                continue
            seen.add(segment_id)
            pool.append((group, segment))
    if not pool:
        return {}
    def score(item: tuple[dict[str, Any], dict[str, Any]]) -> float:
        segment = item[1]
        base = float(segment.get("score") or 0) + float(segment.get("emotionScore") or 0) * .15
        if mode == "climax" and str(segment.get("role") or "").lower() in {"高潮", "climax", "转折", "turning_point"}:
            base += 20
        if mode == "tight":
            base += max(0.0, 8.0 - float(segment.get("duration") or 0))
        return base
    ranked = sorted(pool, key=lambda item: (-score(item), float(item[1].get("start") or 0)))
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    covered_groups: set[str] = set()
    for group, segment in ranked:
        if str(group.get("id")) in covered_groups:
            continue
        selected.append((group, segment))
        covered_groups.add(str(group.get("id")))
    current = sum(float(item[1].get("duration") or (float(item[1].get("end", 0)) - float(item[1].get("start", 0)))) for item in selected)
    for group, segment in ranked:
        if any(str(segment.get("id")) == str(existing[1].get("id")) for existing in selected):
            continue
        start, end = float(segment.get("start", 0)), float(segment.get("end", 0))
        if any(max(start, float(existing[1].get("start", 0))) < min(end, float(existing[1].get("end", 0))) for existing in selected):
            continue
        duration = float(segment.get("duration") or (end - start))
        if target > 0 and current >= target * .92 and abs(current + duration - target) > abs(current - target):
            continue
        selected.append((group, segment))
        current += duration
        if target > 0 and current >= target * .92:
            break
    selected.sort(key=lambda item: float(item[1].get("start") or 0))
    result: dict[str, list[str]] = {}
    for group, segment in selected:
        result.setdefault(str(group.get("id")), []).append(str(segment.get("id")))
    return result


def _edit_plan_candidates(job: dict[str, Any], group_ids: list[str], segment_ids: dict[str, list[str]] | None, scope: str) -> list[dict[str, Any]]:
    """Build the structured evidence packet sent to the text-only editor."""
    selected_groups = {str(value) for value in group_ids}
    requested = {str(key): {str(value) for value in values} for key, values in (segment_ids or {}).items()}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in job.get("eventGroups", []):
        group_id = str(group.get("id"))
        if scope == "selected_only" and group_id not in selected_groups:
            continue
        source_segments = [*(group.get("segments") or []), *(group.get("availableSegments") or [])]
        for segment in source_segments:
            segment_id = str(segment.get("id"))
            if not segment_id or segment_id in seen:
                continue
            if scope == "selected_only" and group_id in requested and segment_id not in requested[group_id]:
                continue
            seen.add(segment_id)
            rows.append({
                "id": segment_id,
                "candidateId": str(segment.get("candidateId") or segment_id),
                "semanticUnitId": str(segment.get("semanticUnitId") or segment.get("candidateId") or segment_id),
                "groupId": group_id,
                "groupTitle": str(group.get("title") or "精彩事件"),
                "selected": group_id in selected_groups and (not requested.get(group_id) or segment_id in requested[group_id]),
                "start": round(float(segment.get("start") or 0), 3),
                "end": round(float(segment.get("end") or 0), 3),
                "duration": round(float(segment.get("duration") or (float(segment.get("end") or 0) - float(segment.get("start") or 0))), 3),
                "role": str(segment.get("role") or "精彩镜头"),
                "score": round(float(segment.get("score") or 0), 2),
                "reason": str(segment.get("reason") or "")[:300],
                "evidence": list(segment.get("evidence") or [])[:4],
                "audioEvidence": dict(segment.get("audioEvidence") or {}),
                "peakStart": round(float(segment.get("peakStart", segment.get("start") or 0)), 3),
                "peakEnd": round(float(segment.get("peakEnd", segment.get("end") or 0)), 3),
                "minimumKeepSeconds": round(float(segment.get("minimumKeepSeconds") or min(float(segment.get("duration") or 2), 2)), 3),
                "boundaryConfidence": round(float(segment.get("boundaryConfidence") or .5), 3),
                "safeStart": round(float(segment.get("safeStart", segment.get("start") or 0)), 3),
                "safeEnd": round(float(segment.get("safeEnd", segment.get("end") or 0)), 3),
                "boundarySource": str(segment.get("boundarySource") or "visual"),
                "speechBoundaryStatus": str(segment.get("speechBoundaryStatus") or "no_speech"),
                "hasSpeech": bool(segment.get("hasSpeech")),
                "speechUnits": copy.deepcopy(segment.get("speechUnits") or []),
            })
    return rows[:120]


def _job_transcript_segments(job: dict[str, Any]) -> list[dict[str, Any]]:
    speech = job.get("speechAnalysis") or {}
    segments = speech.get("segments") if isinstance(speech, dict) else None
    if isinstance(segments, list):
        return load_transcript_segments(segments)
    work_directory = str(job.get("workDirectory") or "").strip()
    path = Path(work_directory) / "transcript.json" if work_directory else None
    if not path or not path.is_file():
        return []
    try:
        return load_transcript_segments(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return []


def _job_silence_intervals(job: dict[str, Any]) -> list[dict[str, Any]]:
    work_directory = str(job.get("workDirectory") or "").strip()
    path = Path(work_directory) / "timeline-waveform.json" if work_directory else None
    if not path or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return list(payload.get("silences") or []) if isinstance(payload, dict) else []


def _semantic_safe_selections(
    job: dict[str, Any], selections: list[dict[str, Any]], *, order_mode: str = "selection",
    target_seconds: float | None = None, allow_fill: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    speech_segments = _job_transcript_segments(job)
    silences = _job_silence_intervals(job)
    video_duration = float((job.get("videoInfo") or {}).get("duration") or 0) or None
    result = copy.deepcopy(selections)
    candidate_pool = _edit_plan_candidates(job, [], None, "all_pool") if allow_fill else []
    adjustments: list[dict[str, Any]] = []
    for selection in result:
        optimized = optimize_edl(
            list(selection.get("segments") or []),
            candidate_pool=candidate_pool,
            speech_segments=speech_segments, silences=silences,
            target_seconds=target_seconds,
            order_mode=order_mode,
            allow_fill=allow_fill, video_duration=video_duration,
        )
        selection["segments"] = optimized["segments"]
        selection["actualDuration"] = optimized["actualDuration"]
        selection["edlOptimization"] = {key: value for key, value in optimized.items() if key != "segments"}
        adjustments.extend(optimized["boundaryAdjustments"])
    return result, adjustments


def _safe_plan_range(
    candidate: dict[str, Any], start: float, end: float,
    speech_segments: list[dict[str, Any]], silences: list[dict[str, Any]],
) -> dict[str, Any]:
    return semantic_safe_range(
        start, end, speech_segments=speech_segments, silences=silences,
        lower_bound=float(candidate.get("start") or 0),
        upper_bound=float(candidate.get("end") or 0),
    )


def _plan_range_for_duration(candidate: dict[str, Any], duration: float, *, within: tuple[float, float] | None = None) -> tuple[float, float]:
    left = float(candidate.get("start") or 0)
    right = max(left, float(candidate.get("end") or left))
    if within:
        left = max(left, float(within[0]))
        right = min(right, float(within[1]))
    available = max(0.0, right - left)
    keep = min(available, max(.35, float(duration)))
    peak_left = max(left, min(right, float(candidate.get("peakStart", left + available * .4))))
    peak_right = max(peak_left, min(right, float(candidate.get("peakEnd", left + available * .6))))
    peak_duration = peak_right - peak_left
    start = peak_left - (keep - peak_duration) / 2 if peak_duration <= keep else (peak_left + peak_right - keep) / 2
    start = max(left, min(right - keep, start))
    return round(start, 3), round(start + keep, 3)


def _fit_edit_sequence_to_target(
    sequence: list[dict[str, Any]],
    candidate_map: dict[str, dict[str, Any]],
    target: float | None,
    speech_segments: list[dict[str, Any]] | None = None,
    silences: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Deterministically repair an LLM plan to the requested duration.

    The LLM still decides editorial intent and ordering. This pass only trims
    inside verified candidate windows or adds the strongest unused verified
    candidates when the plan is materially short.
    """
    if not target or target <= 0 or not sequence:
        return sequence, []
    result = copy.deepcopy(sequence)
    notes: list[str] = []
    tolerance = max(4.0, target * .1)

    def total() -> float:
        return sum(max(0.0, float(item.get("end") or 0) - float(item.get("start") or 0)) for item in result)

    if total() > target + tolerance:
        for item in sorted(
            list(result),
            key=lambda value: (bool(value.get("essential")), float(candidate_map.get(str(value.get("candidateId")), {}).get("score") or 0), -float(value.get("duration") or 0)),
        ):
            excess = total() - target
            if excess <= .05:
                break
            current = max(0.0, float(item.get("end") or 0) - float(item.get("start") or 0))
            candidate = candidate_map.get(str(item.get("candidateId")))
            if not candidate:
                continue
            minimum = max(.35, min(current, float(candidate.get("minimumKeepSeconds") or .8)))
            if not item.get("essential") and current <= excess + .2 and len(result) > 1:
                result.remove(item)
                continue
            desired = max(minimum, current - excess)
            if desired >= current - .05:
                continue
            start, end = _plan_range_for_duration(candidate, desired, within=(float(item["start"]), float(item["end"])))
            safe = _safe_plan_range(candidate, start, end, speech_segments or [], silences or [])
            item.update({
                "start": safe["start"], "end": safe["end"],
                "duration": round(safe["end"] - safe["start"], 3),
                "durationAdjusted": True, "boundaryAdjustment": safe,
            })
        if total() < target - tolerance:
            notes.append("为满足目标时长，已在精彩核心范围内压缩过长镜头")

    if total() < target - tolerance:
        occupied = [(float(item["start"]), float(item["end"])) for item in result]
        used = {str(item.get("candidateId")) for item in result}
        for candidate in sorted(candidate_map.values(), key=lambda value: (-float(value.get("score") or 0), float(value.get("start") or 0))):
            candidate_id = str(candidate.get("id"))
            if candidate_id in used:
                continue
            start, end = float(candidate.get("start") or 0), float(candidate.get("end") or 0)
            if any(max(start, left) < min(end, right) for left, right in occupied):
                continue
            need = target - total()
            if need < .35:
                break
            keep = min(end - start, need)
            fitted_start, fitted_end = _plan_range_for_duration(candidate, keep)
            safe = _safe_plan_range(candidate, fitted_start, fitted_end, speech_segments or [], silences or [])
            fitted_start, fitted_end = safe["start"], safe["end"]
            if total() + fitted_end - fitted_start > target + max(5.0, target * .15) and result:
                continue
            result.append({
                "id": f"plan_{uuid.uuid4().hex[:10]}", "candidateId": candidate_id,
                "groupId": candidate["groupId"], "chapterId": candidate["groupId"],
                "chapterTitle": candidate["groupTitle"], "chapterOrder": len(result), "editOrder": len(result),
                "start": fitted_start, "end": fitted_end, "duration": round(fitted_end - fitted_start, 3),
                "role": str(candidate.get("role") or "development"),
                "reason": "目标时长校正：从完整候选池补充高分且不重复的精彩核心。",
                "essential": False, "addedByDurationOptimizer": True,
                "boundaryAdjustment": safe,
                "transitionIn": {"type": "cut", "duration": 0.0},
            })
            occupied.append((fitted_start, fitted_end))
            used.add(candidate_id)
            if total() >= target - .05:
                break
        result.sort(key=lambda item: (float(item.get("start") or 0), int(item.get("editOrder") or 0)))
        if any(item.get("addedByDurationOptimizer") for item in result):
            notes.append("已从完整候选池补充高分且不重复的镜头，使成片接近目标时长")

    upper_limit = target + max(5.0, target * .15)
    while total() > upper_limit + .01 and len(result) > 1:
        removable = min(
            result,
            key=lambda item: (
                bool(item.get("essential")),
                float(candidate_map.get(str(item.get("candidateId")), {}).get("score") or 0),
                -float(item.get("duration") or 0),
            ),
        )
        result.remove(removable)
        notes.append("为保留完整表达且控制总时长，已移除一个完整的低优先级镜头")

    optimized = optimize_edl(
        result, candidate_pool=list(candidate_map.values()),
        speech_segments=speech_segments, silences=silences,
        target_seconds=target, order_mode="selection", allow_fill=True,
    )
    result = optimized["segments"]
    if optimized["removedSegments"]:
        notes.append("最终 EDL 已按完整镜头控制动态时长上限")
    if optimized["overlapResolutions"]:
        notes.append("最终 EDL 已合并重叠源区间")

    for index, item in enumerate(result):
        item["editOrder"] = index
        item["chapterOrder"] = index
        item["duration"] = round(float(item.get("end") or 0) - float(item.get("start") or 0), 3)
    return result, notes


def _normalise_edit_plans(
    raw: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    scope: str,
    selected_group_ids: list[str],
    target: float | None,
    speech_segments: list[dict[str, Any]] | None = None,
    silences: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidate_map = {str(item["id"]): item for item in candidates}
    selected_groups = {str(value) for value in selected_group_ids}
    plans: list[dict[str, Any]] = []
    for index, item in enumerate(raw.get("plans") if isinstance(raw.get("plans"), list) else []):
        if not isinstance(item, dict):
            continue
        sequence: list[dict[str, Any]] = []
        occupied: list[tuple[float, float]] = []
        for step in item.get("sequence") if isinstance(item.get("sequence"), list) else []:
            if not isinstance(step, dict):
                continue
            candidate = candidate_map.get(str(step.get("candidate_id") or step.get("candidateId")))
            if not candidate:
                continue
            if scope == "selected_only" and str(candidate["groupId"]) not in selected_groups:
                continue
            start = float(step.get("source_start", step.get("sourceStart", candidate["start"])))
            end = float(step.get("source_end", step.get("sourceEnd", candidate["end"])))
            start = max(candidate["start"], min(candidate["end"], start))
            end = max(candidate["start"], min(candidate["end"], end))
            safe = _safe_plan_range(candidate, start, end, speech_segments or [], silences or [])
            start, end = safe["start"], safe["end"]
            minimum_keep = max(.35, min(
                float(candidate["end"]) - float(candidate["start"]),
                float(candidate.get("minimumKeepSeconds") or .35),
            ))
            if end - start < minimum_keep - .01:
                start, end = _plan_range_for_duration(candidate, minimum_keep)
                safe = _safe_plan_range(candidate, start, end, speech_segments or [], silences or [])
                start, end = safe["start"], safe["end"]
            if end - start < .35:
                continue
            if any(max(start, left) < min(end, right) for left, right in occupied):
                continue
            occupied.append((start, end))
            sequence.append({
                "id": f"plan_{uuid.uuid4().hex[:10]}",
                "candidateId": candidate["id"],
                "groupId": candidate["groupId"],
                "chapterId": candidate["groupId"],
                "chapterTitle": candidate["groupTitle"],
                "chapterOrder": len(sequence),
                "editOrder": len(sequence),
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "role": str(step.get("role") or "development"),
                "reason": str(step.get("reason") or "")[:500],
                "essential": bool(step.get("essential", False)),
                "boundaryAdjustment": safe,
                "transitionIn": {"type": "cut", "duration": 0.0},
            })
        if not sequence:
            continue
        sequence, duration_notes = _fit_edit_sequence_to_target(
            sequence, candidate_map, target,
            speech_segments=speech_segments, silences=silences,
        )
        duration = round(sum(float(item["duration"]) for item in sequence), 3)
        chapters: list[dict[str, Any]] = []
        for segment in sequence:
            role = str(segment.get("role") or "development")
            if not chapters or chapters[-1]["role"] != role:
                chapters.append({"id": f"chapter_{uuid.uuid4().hex[:8]}", "role": role, "title": role, "segmentCount": 0, "duration": 0.0})
            chapters[-1]["segmentCount"] += 1
            chapters[-1]["duration"] = round(float(chapters[-1]["duration"]) + float(segment["duration"]), 3)
        tolerance = max(4.0, (target or duration) * .1)
        warnings = list(item.get("warnings") or []) if isinstance(item.get("warnings"), list) else []
        warnings.extend(note for note in duration_notes if note not in warnings)
        if target and not (target - tolerance <= duration <= target + tolerance):
            gap = target - duration
            if gap > 0:
                warnings.append(f"素材不足：当前自然可用时长 {duration:.1f} 秒，距离目标还差 {gap:.1f} 秒；未使用重复镜头或低价值拖尾")
            else:
                warnings.append(f"当前结构 {duration:.1f} 秒，超出目标 {abs(gap):.1f} 秒；已优先保留完整表达")
        narrative = str(item.get("narrative") or "根据已有视觉、语音和事件证据重新编排")[:800]
        optimizer_added = [str(step.get("candidateId")) for step in sequence if step.get("addedByDurationOptimizer")]
        reported_added = [str(value) for value in item.get("added_by_ai", item.get("addedByAi", [])) if str(value) in candidate_map]
        plans.append({
            "id": f"plan_{uuid.uuid4().hex[:12]}",
            "label": str(item.get("label") or f"自动剪辑方案 {index + 1}")[:60],
            "narrative": narrative,
            "structure": list(item.get("structure") or []),
            "sequence": sequence,
            "chapters": chapters,
            "addedByAi": list(dict.fromkeys([*reported_added, *optimizer_added])),
            "estimatedDuration": duration,
            "targetSeconds": target,
            "durationStatus": ("on_target" if not target or target - tolerance <= duration <= target + tolerance else ("under_target" if duration < target else "over_target")),
            "durationGap": round((target - duration), 3) if target else 0.0,
            "warnings": warnings,
            "planner": "ark-llm",
        })
    return plans


def _local_edit_plan_fallback(candidates: list[dict[str, Any]], target: float | None, count: int = 3) -> list[dict[str, Any]]:
    """Safe fallback when the LLM is unavailable or returns unusable JSON."""
    ranked = sorted(candidates, key=lambda item: (-float(item.get("score") or 0), float(item.get("start") or 0)))
    plans: list[dict[str, Any]] = []
    labels = ["叙事完整版", "情绪高潮版", "信息密度版"][:max(1, min(3, count))]
    for index, label in enumerate(labels):
        chosen: list[dict[str, Any]] = []
        current = 0.0
        for candidate in ranked:
            start, end = float(candidate["start"]), float(candidate["end"])
            duration = end - start
            if any(max(start, item["start"]) < min(end, item["end"]) for item in chosen):
                continue
            if target and current >= target * .9:
                break
            keep = min(duration, max(.8, (target - current) if target else duration))
            if keep < .35:
                continue
            chosen.append({
                "id": f"plan_{uuid.uuid4().hex[:10]}", "candidateId": candidate["id"], "groupId": candidate["groupId"],
                "chapterId": candidate["groupId"], "chapterTitle": candidate["groupTitle"], "chapterOrder": len(chosen), "editOrder": len(chosen),
                "start": round(start, 3), "end": round(start + keep, 3), "duration": round(keep, 3),
                "role": "climax" if index == 1 and len(chosen) == 0 else "development", "reason": "本地降级规划：保留高分候选的有效局部。",
                "essential": len(chosen) == 0, "transitionIn": {"type": "cut", "duration": 0.0},
            })
            current += keep
        if chosen:
            fallback_duration = round(current, 3)
            fallback_warnings = ["未使用 LLM 规划，已降级到本地候选排序"]
            if target and fallback_duration < target - max(4.0, target * .1):
                fallback_warnings.append(f"素材不足：当前自然可用时长 {fallback_duration:.1f} 秒，未使用重复镜头凑时长")
            plans.append({"id": f"plan_{uuid.uuid4().hex[:12]}", "label": label, "narrative": "本地降级方案：按不同节奏优先级保留真实动作节点。", "structure": ["hook", "development", "climax"], "sequence": chosen, "chapters": [], "addedByAi": [], "estimatedDuration": fallback_duration, "targetSeconds": target, "durationStatus": ("under_target" if target and fallback_duration < target - max(4.0, target * .1) else "on_target"), "durationGap": round((target - fallback_duration), 3) if target else 0.0, "warnings": fallback_warnings, "planner": "local-fallback"})
    return plans


def run_auto_plan_generation(job_id: str, request: AutoPlanRequest, background_auto: bool = False) -> None:
    try:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return
            selected_group_ids = list(dict.fromkeys(str(value) for value in (request.groupIds or job.get("recommendedGroupIds", []))))
            target = request.targetSeconds if request.targetSeconds is not None else job.get("totalTargetSeconds") or job.get("request", {}).get("totalTargetSeconds")
            target = float(target) if target not in (None, "", "auto") else None
            scope = request.scope if request.scope in {"selected_only", "all_pool"} else "selected_only"
            evidence = _edit_plan_candidates(job, selected_group_ids, request.segmentIds, scope)
            profile = dict(job.get("contentProfile") or {})
            speech = job.get("speechAnalysis") or {}
            transcript_context = json.dumps({"status": speech.get("status"), "segments": speech.get("segments"), "speakers": speech.get("speakers")}, ensure_ascii=False)
            requested_structure = str(request.structure or job.get("brief", {}).get("structure") or "auto")
            structure_hint = {"hook_story_result": "必须尽量形成 hook、development、climax、result 的完整叙事结构。", "montage": "优先节奏连续和视觉/动作节点，不强行补齐完整叙事段落。", "auto": "根据素材完整性决定结构。"}.get(requested_structure, requested_structure)
            theme = str(job.get("request", {}).get("theme") or "")
            planning_detail = "自动成片后台：剪辑规划模型正在筛选、排序并组合高光片段" if background_auto else "剪辑规划模型正在筛选、排序并组合高光片段"
            job.update({
                "status": "awaiting_confirmation" if background_auto else "running",
                "stage": "auto_composition" if background_auto else "edit_planning",
                "progress": 1.0 if background_auto else .72,
                "stageProgress": None,
                "stageCompleted": None, "stageTotal": None, "stageUnit": "",
                "detail": planning_detail, "currentAction": planning_detail,
                "model": "LLM", "progressMode": "background" if background_auto else "indeterminate",
                "etaSeconds": None, "etaMode": "unavailable", "lastProgressAt": now_iso(),
                "autoPlans": [], "autoPlanRequest": request.model_dump() if hasattr(request, "model_dump") else request.dict(), "error": None,
            })
            if background_auto:
                job.setdefault("autoComposition", {}).update({
                    "phase": "llm_plan", "currentVersionProgress": None,
                    "detail": "剪辑规划模型正在生成后续版本",
                })
            save_job(job)
        variants = ["叙事完整版", "情绪高潮版", "信息密度版", "纪实自然版", "节奏紧凑版"][:max(1, min(5, int(request.variantCount or 3)))]
        client = create_llm_client_for_job(job)
        with jobs_lock:
            active_ark_clients[job_id] = client
        # Never hold jobs_lock while waiting for the remote LLM.  The HTTP
        # handlers and the polling endpoint use the same lock, so keeping it
        # across this request makes the whole UI appear frozen until the model
        # responds or times out.
        raw = client.complete_json(
            llm_edit_plan_prompt(
                content_profile=profile,
                theme=f"{theme}\n成片结构要求：{structure_hint}",
                target_seconds=target,
                scope=scope,
                selected_group_ids=selected_group_ids,
                variants=variants,
                candidates=evidence,
                transcript_context=transcript_context,
            ),
            maximum_tokens=5000,
            system_prompt=COMMON_SYSTEM_PROMPT,
        )
        plans = _normalise_edit_plans(
            raw, evidence, scope=scope, selected_group_ids=selected_group_ids, target=target,
            speech_segments=_job_transcript_segments(job),
            silences=_job_silence_intervals(job),
        )
        if requested_structure == "hook_story_result":
            for plan in plans:
                roles = {str(role).lower() for role in plan.get("structure", [])}
                missing = [label for role, label in (("hook", "开场"), ("development", "发展"), ("climax", "高潮"), ("result", "结尾")) if role not in roles]
                if missing:
                    plan.setdefault("warnings", []).append(f"结构提醒：当前方案缺少{'、'.join(missing)}，未强行加入低价值镜头")
        if not plans:
            plans = _local_edit_plan_fallback(evidence, target, len(variants))
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return
            job.update({"status": "awaiting_confirmation", "stage": "auto_composition" if background_auto else "edit_planning_complete", "progress": 1.0, "stageProgress": 1.0, "detail": f"已生成 {len(plans)} 个可审核剪辑方案", "currentAction": f"已验证 {len(plans)} 个剪辑方案", "progressMode": "background" if background_auto else "completed", "etaSeconds": None, "etaMode": "completed", "autoPlans": plans, "autoPlanPromptVersion": EDIT_PLAN_PROMPT_VERSION, "error": None})
            if background_auto:
                auto_state = job.setdefault("autoComposition", {})
                completed_versions = max(0, int(auto_state.get("completedVersions") or len(auto_state.get("versions") or [])))
                total_versions = max(completed_versions, int(auto_state.get("totalVersions") or completed_versions or 1))
                auto_state["progress"] = round(completed_versions / total_versions, 4)
                auto_state["detail"] = f"规划完成，准备生成 {len(plans)} 个剪辑版本"
            save_job(job)
        append_message(job_id, "assistant", f"已基于现有画面、语音和事件证据生成 {len(plans)} 个细粒度剪辑方案，请先审核每个方案的局部镜头和排列。", kind="edit-plan")
    except Exception as error:
        with jobs_lock:
            job = jobs.get(job_id)
            if job:
                evidence = _edit_plan_candidates(job, list(request.groupIds or job.get("recommendedGroupIds", [])), request.segmentIds, request.scope)
                target = request.targetSeconds or job.get("totalTargetSeconds") or job.get("request", {}).get("totalTargetSeconds")
                plans = _local_edit_plan_fallback(evidence, float(target) if target else None, request.variantCount)
                job.update({"status": "awaiting_confirmation", "stage": "auto_composition" if background_auto else "edit_planning_complete", "progress": 1.0, "stageProgress": 1.0, "detail": f"LLM 规划不可用，已生成 {len(plans)} 个本地降级方案", "currentAction": "已切换本地规划方案", "progressMode": "background" if background_auto else "completed", "etaSeconds": None, "etaMode": "completed", "autoPlans": plans, "error": None})
                if background_auto:
                    auto_state = job.setdefault("autoComposition", {})
                    completed_versions = max(0, int(auto_state.get("completedVersions") or len(auto_state.get("versions") or [])))
                    total_versions = max(completed_versions, int(auto_state.get("totalVersions") or completed_versions or 1))
                    auto_state["progress"] = round(completed_versions / total_versions, 4)
                    auto_state["detail"] = "LLM 不可用，已切换本地规划方案"
                save_job(job)
        append_message(job_id, "assistant", f"LLM 剪辑规划暂不可用，已降级为本地方案：{str(error)[:300]}", kind="warning")
    finally:
        with jobs_lock:
            active_ark_clients.pop(job_id, None)


def run_llm_order_generation(job_id: str, request: LlmOrderRequest) -> None:
    try:
        with jobs_lock:
            job = jobs[job_id]
            evidence = _edit_plan_candidates(job, request.groupIds, request.segmentIds, "selected_only")
            speech = job.get("speechAnalysis") or {}
            transcript = json.dumps({"segments": speech.get("segments"), "speakers": speech.get("speakers")}, ensure_ascii=False)
            job.update({"status": "running", "stage": "edit_planning", "progress": .72, "stageProgress": None, "stageCompleted": None, "stageTotal": None, "stageUnit": "", "detail": "LLM 正在推荐已选镜头的排列顺序", "currentAction": "LLM 正在推荐已选镜头的排列顺序", "model": "LLM", "progressMode": "indeterminate", "etaSeconds": None, "etaMode": "unavailable", "lastProgressAt": now_iso(), "error": None})
            save_job(job)
        client = create_llm_client_for_job(job)
        raw = client.complete_json(llm_order_prompt(content_profile=dict(job.get("contentProfile") or {}), theme=str(job.get("request", {}).get("theme") or ""), candidates=evidence, transcript_context=transcript), maximum_tokens=1800, system_prompt=COMMON_SYSTEM_PROMPT)
        allowed = {str(item["id"]): item for item in evidence}
        ordered = [str(value) for value in raw.get("ordered_ids", []) if str(value) in allowed]
        ordered.extend(item_id for item_id in allowed if item_id not in ordered)
        with jobs_lock:
            job = jobs[job_id]
            job.update({"status": "awaiting_confirmation", "stage": "edit_planning_complete", "progress": 1.0, "stageProgress": 1.0, "detail": "LLM 已推荐镜头顺序（未改变任何起止时间）", "currentAction": "LLM 镜头排序已完成", "progressMode": "completed", "etaSeconds": None, "etaMode": "completed", "llmOrder": {"orderedIds": ordered, "reason": str(raw.get("reason") or "")[:800]}, "error": None})
            save_job(job)
        append_message(job_id, "assistant", "LLM 已完成纯排序推荐：只调整镜头顺序，没有改变任何镜头的起止时间。请审核后再合成。", kind="edit-plan")
    except Exception as error:
        with jobs_lock:
            job = jobs[job_id]
            job.update({"status": "awaiting_confirmation", "stage": "edit_planning_complete", "progress": 1.0, "detail": f"LLM 纯排序失败：{str(error)[:180]}", "error": None})
            save_job(job)


def run_confirmed_render(job_id: str, selection_keys: list[Any], output_mode: str = "single_reel", variant_mode: str = "complete", variant_label: str = "", finalize_status: bool = True, planned_sequence: list[dict[str, Any]] | None = None, planned_title: str = "", planned_chapters: list[dict[str, Any]] | None = None, subtitle_mode: str = "none", order_mode: str = "source", subtitle_style: str = "clean", auto_meta: dict[str, str] | None = None, background_auto: bool = False) -> None:
    subtitle_mode = "burn" if str(subtitle_mode).strip().lower() == "burn" else "none"
    subtitle_style = normalize_subtitle_style(subtitle_style)
    version_committed = False
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        normalize_output_versions(job)
        previous_outputs = list(job.get("outputs", []))
        previous_version_id = job.get("currentOutputVersionId")
        version_id, version_number = next_output_version(job)
        # Analysis completion and automatic composition can overlap for a few
        # milliseconds.  The analysis worker's finally block may remove its
        # event just as the composition worker starts.  Reuse it when present,
        # otherwise create an event for this render instead of raising a
        # KeyError whose message is only the opaque job id.
        cancel_event = cancel_events.setdefault(job_id, threading.Event())
        event_groups = job.get("eventGroups") or []
        if planned_sequence:
            selections = [{
                "id": "planned_reel",
                "title": planned_title or "LLM 细粒度高光成片",
                "summary": "由 LLM 根据已有视觉、语音和事件证据重新设计的局部镜头序列。",
                "score": 0,
                "segments": copy.deepcopy(planned_sequence),
                "chapters": copy.deepcopy(planned_chapters or []),
            }]
        elif event_groups:
            selected_lookup = {str(value) for value in selection_keys}
            segment_lookup = job.get("confirmedSegmentIds") or {}
            selections = []
            for group in event_groups:
                if str(group.get("id")) not in selected_lookup:
                    continue
                selection = copy.deepcopy(group)
                selected_ids = segment_lookup.get(str(group.get("id")))
                if selected_ids is not None:
                    selected_set = {str(value) for value in selected_ids}
                    available = [*(selection.get("segments") or []), *(selection.get("availableSegments") or [])]
                    seen_ids: set[str] = set()
                    filtered: list[dict[str, Any]] = []
                    for item in available:
                        item_id = str(item.get("id"))
                        if item_id in selected_set and item_id not in seen_ids:
                            filtered.append(item)
                            seen_ids.add(item_id)
                    selection["segments"] = filtered
                selections.append(selection)
        else:
            selections = [job["candidates"][int(index)] for index in selection_keys]
        selected_event_group_ids = [str(value) for value in selection_keys] if event_groups else []
    try:
        selections = _variant_selections(selections, variant_mode) if not planned_sequence else selections
        if output_mode == "single_reel" and not planned_sequence:
            final_reel = build_final_reel(selections, order_mode=order_mode)
            if not final_reel.get("segments"):
                raise RuntimeError("所选事件中没有可用于合成的镜头")
            selections = [final_reel]
        # Rendering must preserve the EDL that was presented for review. Target
        # fitting belongs to recommendation/planning, before the user sees the
        # timeline. Re-applying the target here previously turned a displayed
        # 42.6s two-event recommendation into an undocumented 30.6s one-event
        # output. Semantic boundary validation still runs, but it may not add
        # or remove selected shots at render time.
        selections, boundary_adjustments = _semantic_safe_selections(
            job, selections, order_mode=order_mode,
            target_seconds=None,
            allow_fill=False,
        )
        composition_hash = composition_edl_hash(
            selections,
            source_hash=str(job.get("sourceHash") or ""),
            output_mode=output_mode,
            subtitle_mode=subtitle_mode,
            subtitle_style=subtitle_style,
            variant_mode=variant_mode,
            variant_label=variant_label,
            order_mode=order_mode,
        )
        output_directory = Path(job["outputDirectory"])
        with jobs_lock:
            cached_version = next(
                (
                    version for version in jobs[job_id].get("outputVersions", [])
                    if str(version.get("compositionHash") or "") == composition_hash
                    and version.get("outputs")
                    and all((output_directory / str(item.get("filename"))).is_file() for item in version.get("outputs", []))
                ),
                None,
            )
            if cached_version:
                cached_outputs = list(cached_version.get("outputs") or [])
                update_job(
                    job_id,
                    status="awaiting_confirmation" if background_auto else ("completed" if finalize_status else "running"),
                    progress=1.0,
                    stage="auto_composition" if background_auto else ("completed" if finalize_status else "rendering"),
                    detail=f"已复用已有成片版本 V{cached_version.get('number', 1)}，无需重复渲染",
                    outputs=cached_outputs,
                    outputVersions=jobs[job_id].get("outputVersions", []),
                    currentOutputVersionId=cached_version.get("id"),
                    actualCount=len(cached_outputs),
                )
                append_message(job_id, "assistant", f"已复用已有成片版本 V{cached_version.get('number', 1)}，本次选择无需重复渲染。", kind="notice")
                return
        info = probe_video(Path(job["sourcePath"]), settings.ffprobe)
        output_directory.mkdir(parents=True, exist_ok=True)
        staging_directory = output_directory / ".staging" / f"{version_id}-{uuid.uuid4().hex}"
        staging_directory.mkdir(parents=True, exist_ok=False)
        outputs: list[dict[str, Any]] = []
        render_total_seconds = round(sum(
            sum(max(0.0, float(segment.get("end", 0)) - float(segment.get("start", 0))) for segment in (selection.get("segments") or []))
            for selection in selections
        ), 3)
        last_auto_progress_at = 0.0
        last_auto_progress_value = -1.0
        last_foreground_progress_at = 0.0
        last_foreground_progress_value = -1.0

        def report_auto_render_progress(title: str, fraction: float) -> None:
            nonlocal last_auto_progress_at, last_auto_progress_value
            if not background_auto:
                return
            fraction = max(0.0, min(1.0, float(fraction)))
            current_time = time.monotonic()
            if (
                fraction < 1.0
                and current_time - last_auto_progress_at < .75
                and fraction - last_auto_progress_value < .015
            ):
                return
            with jobs_lock:
                live_job = jobs.get(job_id)
                if not live_job:
                    return
                auto_state = live_job.setdefault("autoComposition", {})
                completed_versions = max(0, int(auto_state.get("completedVersions") or 0))
                total_versions = max(completed_versions + 1, int(auto_state.get("totalVersions") or 1))
                current_version = max(1, int(auto_state.get("currentVersion") or completed_versions + 1))
                # Reserve the final 8% of each version for media validation.
                version_progress = min(.92, fraction * .92)
                overall_progress = min(.995, (completed_versions + version_progress) / total_versions)
                auto_state.update({
                    "status": "running",
                    "phase": "rendering",
                    "progress": round(overall_progress, 4),
                    "currentVersion": current_version,
                    "currentVersionProgress": round(version_progress, 4),
                    "renderedSeconds": round(render_total_seconds * fraction, 2),
                    "renderTotalSeconds": render_total_seconds,
                    "detail": f"正在生成第 {current_version}/{total_versions} 个版本 · {title}",
                })
                live_job["stage"] = "auto_composition"
                live_job["detail"] = "事件审核已就绪；" + auto_state["detail"]
                live_job["currentAction"] = auto_state["detail"]
                live_job["lastProgressAt"] = now_iso()
                save_job(live_job)
            last_auto_progress_at = current_time
            last_auto_progress_value = fraction

        def report_auto_quality_check(title: str) -> None:
            if not background_auto:
                return
            with jobs_lock:
                live_job = jobs.get(job_id)
                if not live_job:
                    return
                auto_state = live_job.setdefault("autoComposition", {})
                completed_versions = max(0, int(auto_state.get("completedVersions") or 0))
                total_versions = max(completed_versions + 1, int(auto_state.get("totalVersions") or 1))
                current_version = max(1, int(auto_state.get("currentVersion") or completed_versions + 1))
                version_progress = .96
                auto_state.update({
                    "status": "running",
                    "phase": "quality_check",
                    "progress": round(min(.995, (completed_versions + version_progress) / total_versions), 4),
                    "currentVersion": current_version,
                    "currentVersionProgress": version_progress,
                    "renderedSeconds": render_total_seconds,
                    "renderTotalSeconds": render_total_seconds,
                    "detail": f"第 {current_version}/{total_versions} 个版本已渲染，正在检查视频完整性 · {title}",
                })
                live_job["detail"] = "事件审核已就绪；" + auto_state["detail"]
                live_job["currentAction"] = auto_state["detail"]
                live_job["lastProgressAt"] = now_iso()
                save_job(live_job)

        def report_foreground_render_progress(
            title: str,
            position: int,
            selection_seconds: float,
            fraction: float,
        ) -> None:
            """Publish real FFmpeg progress for user-triggered renders."""
            nonlocal last_foreground_progress_at, last_foreground_progress_value
            if background_auto:
                return
            fraction = max(0.0, min(1.0, float(fraction)))
            overall_fraction = (position + fraction) / max(1, len(selections))
            current_time = time.monotonic()
            if (
                fraction < 1.0
                and current_time - last_foreground_progress_at < .5
                and overall_fraction - last_foreground_progress_value < .01
            ):
                return
            completed_seconds = sum(float(item.get("duration") or 0) for item in outputs)
            action = (
                f"正在合成高光成片 · 编码 {round(fraction * 100)}%"
                if output_mode == "single_reel"
                else f"正在导出第 {position + 1}/{len(selections)} 个事件视频 · 编码 {round(fraction * 100)}%"
            )
            update_job(
                job_id,
                progress=round(min(.995, .82 + .175 * overall_fraction), 4),
                stage="rendering",
                stageProgress=round(min(.995, overall_fraction), 4),
                stageCompleted=position,
                stageTotal=len(selections),
                stageUnit="成片" if output_mode == "single_reel" else "事件视频",
                stageCompletedSeconds=round(min(render_total_seconds, completed_seconds + selection_seconds * fraction), 2),
                stageTotalSeconds=render_total_seconds,
                currentAction=action,
                detail=action,
                model="FFmpeg",
                progressMode="determinate",
                etaSeconds=None,
                etaMode="encoding",
                lastProgressAt=now_iso(),
            )
            last_foreground_progress_at = current_time
            last_foreground_progress_value = overall_fraction

        def report_foreground_quality_check(title: str) -> None:
            if background_auto:
                return
            update_job(
                job_id,
                progress=.995,
                stage="rendering",
                stageProgress=.995,
                currentAction=f"{title} 已完成编码，正在检查视频完整性",
                detail="编码已完成，正在检查画面、时长与音轨",
                model="FFmpeg",
                progressMode="indeterminate",
                etaSeconds=None,
                etaMode="quality_check",
                lastProgressAt=now_iso(),
            )
        for position, selection in enumerate(selections):
            if cancel_event.is_set():
                raise RuntimeError("任务已取消")
            title = str(selection.get("title") or "highlight")
            segments = list(selection.get("segments") or [{
                "start": selection["start"], "end": selection["end"],
                "transitionIn": {"type": "cut", "duration": 0},
            }])
            selection_render_seconds = sum(
                max(0.0, float(segment.get("end", 0)) - float(segment.get("start", 0)))
                for segment in segments
            )
            auto_state = job.get("autoComposition") if isinstance(job.get("autoComposition"), dict) else {}
            auto_completed = max(0, int(auto_state.get("completedVersions") or 0))
            auto_total = max(auto_completed + 1, int(auto_state.get("totalVersions") or 1))
            filename = f"{version_id}-{safe_highlight_filename(title, position + 1)}"
            output_path = staging_directory / filename
            update_job(
                job_id,
                **({"status": "awaiting_confirmation"} if background_auto else {}),
                progress=1.0 if background_auto else round(0.82 + 0.17 * position / max(1, len(selections)), 4),
                stage="auto_composition" if background_auto else "rendering",
                stageProgress=1.0 if background_auto else round(position / max(1, len(selections)), 4),
                stageCompleted=auto_completed if background_auto else position,
                stageTotal=auto_total if background_auto else len(selections),
                stageUnit="版本" if background_auto else ("成片" if output_mode == "single_reel" else "事件视频"),
                currentAction=(
                    f"正在渲染镜头 {position + 1}/{len(segments)} · {title}"
                    if output_mode == "single_reel" else f"正在导出第 {position + 1}/{len(selections)} 个事件视频"
                ),
                model="FFmpeg",
                progressMode="background" if background_auto else "determinate",
                stageCompletedSeconds=round(sum(float(item.get("duration") or 0) for item in outputs), 3),
                stageTotalSeconds=render_total_seconds,
                lastProgressAt=now_iso(),
                detail=(
                    f"正在合成高光成片（{len(selection.get('chapters', []))} 个高光事件、{len(segments)} 个镜头）"
                    if output_mode == "single_reel"
                    else f"正在导出事件视频 {position + 1}/{len(selections)}（{len(segments)} 个镜头）"
                ),
            )
            subtitle_path = staging_directory / f"{Path(filename).stem}.ass" if subtitle_mode == "burn" else None
            subtitle_cues = _subtitle_cues(job, {"segments": segments}) if subtitle_mode == "burn" else []
            if subtitle_path:
                _write_ass_subtitles(job, {"segments": segments}, subtitle_path, subtitle_style)
            expected_duration = render_composition(
                Path(job["sourcePath"]),
                output_path,
                segments=segments,
                has_audio=info.has_audio,
                ffmpeg=settings.ffmpeg,
                cancelled=cancel_event.is_set,
                subtitle_path=subtitle_path,
                subtitle_cues=subtitle_cues,
                subtitle_style=subtitle_style,
                progress_callback=(
                    (lambda fraction, current_title=title: report_auto_render_progress(current_title, fraction))
                    if background_auto else
                    (lambda fraction, current_title=title, current_position=position, current_seconds=selection_render_seconds:
                        report_foreground_render_progress(current_title, current_position, current_seconds, fraction))
                ),
            )
            report_auto_quality_check(title)
            report_foreground_quality_check(title)
            rendered = validate_rendered_clip(
                output_path,
                expected_duration=expected_duration,
                expect_audio=info.has_audio,
                ffmpeg=settings.ffmpeg,
                ffprobe=settings.ffprobe,
            )
            requested_target = job.get("totalTargetSeconds") or job.get("request", {}).get("totalTargetSeconds")
            try:
                requested_target = float(requested_target) if requested_target not in (None, "", "auto") else None
            except (TypeError, ValueError):
                requested_target = None
            duration_tolerance = max(4.0, requested_target * .1) if requested_target else None
            duration_status = (
                "on_target" if not requested_target or abs(rendered.duration - requested_target) <= duration_tolerance
                else ("under_target" if rendered.duration < requested_target else "over_target")
            )
            version_created_at = now_iso()
            rendered_event_ids = {
                str(event_id)
                for item in segments
                for event_id in (
                    item.get("contributingEventIds")
                    or item.get("contributingChapterIds")
                    or [item.get("chapterId") or item.get("groupId") or selection.get("id")]
                )
                if event_id
            }
            rendered_event_count = len(rendered_event_ids) or 1
            edl_quality = dict((selection.get("edlOptimization") or {}).get("qualityReport") or {})
            media_quality = {
                "passed": True,
                "decoded": True,
                "durationDelta": round(rendered.duration - expected_duration, 3),
                "width": int(rendered.width), "height": int(rendered.height),
                "audioPresent": bool(rendered.has_audio),
                "audioExpected": bool(info.has_audio),
            }
            outputs.append({
                "filename": filename,
                "versionId": version_id,
                "versionNumber": version_number,
                "versionCreatedAt": version_created_at,
                "eventGroupId": selection.get("id"),
                "eventGroupIds": sorted(rendered_event_ids) if output_mode == "single_reel" else [selection.get("id")],
                "candidateIndex": selection.get("index"),
                "start": min(float(item["start"]) for item in segments),
                "end": max(float(item["end"]) for item in segments),
                "duration": round(rendered.duration, 3),
                "targetSeconds": requested_target,
                "durationStatus": duration_status,
                "durationGap": round(requested_target - rendered.duration, 3) if requested_target else 0.0,
                "score": float(selection.get("score", 0)),
                "title": f"{title} · {variant_label}" if variant_label and output_mode == "single_reel" else title,
                **(auto_meta or {}),
                "reason": str(selection.get("summary") or selection.get("reason") or "多个同一事件镜头组合成片"),
                "evidence": list(selection.get("evidence", [])),
                "segments": segments,
                "segmentCount": len(segments),
                "shotCount": len(segments),
                "physicalShotCount": sum(max(1, int(item.get("physicalShotCount") or len(item.get("visualShots") or []) or 1)) for item in segments),
                "chapters": list(selection.get("chapters", [])),
                "chapterCount": rendered_event_count,
                "eventCount": rendered_event_count,
                "durationUpperLimit": (
                    round(requested_target + max(5.0, requested_target * .15), 3)
                    if requested_target else None
                ),
                "durationDeviationReason": (
                    "为保留完整对白或动作而允许安全边界内的时长偏差"
                    if requested_target and rendered.duration > requested_target + max(4.0, requested_target * .1)
                    else (
                        "候选池中没有足够的不重复完整镜头，未使用重复或低价值拖尾强行凑时长"
                        if requested_target and rendered.duration < requested_target - max(4.0, requested_target * .1)
                        else ""
                    )
                ),
                "boundaryAdjustments": boundary_adjustments,
                "deduplicationLog": list(selection.get("deduplicationLog") or []),
                "edlOptimization": dict(selection.get("edlOptimization") or {}),
                "qualityReport": {
                    "score": int(edl_quality.get("score", 100)),
                    "passed": bool(edl_quality.get("passed", True)) and media_quality["passed"],
                    "editorial": edl_quality,
                    "media": media_quality,
                },
                "eventReductionReason": str(job.get("eventReductionReason") or ""),
                "subtitleMode": subtitle_mode,
                "subtitleStyle": subtitle_style if subtitle_mode == "burn" else None,
            })
        # Every staged file has passed media validation. Only now publish the new,
        # uniquely named version; existing versions are never touched.
        published_paths: list[Path] = []
        for item in outputs:
            published = output_directory / item["filename"]
            (staging_directory / item["filename"]).replace(published)
            published_paths.append(published)
        version_created_at = now_iso()
        output_version = {
            "id": version_id,
            "number": version_number,
            "createdAt": version_created_at,
            "outputMode": output_mode,
            "confirmedGroupIds": selection_keys if event_groups else [],
            "confirmedSegmentIds": dict(job.get("confirmedSegmentIds") or {}) if event_groups else {},
            "confirmedIndices": [] if event_groups else selection_keys,
            "compositionHash": composition_hash,
            "subtitleMode": subtitle_mode,
            "subtitleStyle": subtitle_style if subtitle_mode == "burn" else None,
            "targetSeconds": outputs[0].get("targetSeconds") if len(outputs) == 1 else None,
            "durationStatus": outputs[0].get("durationStatus") if len(outputs) == 1 else None,
            "qualityReport": outputs[0].get("qualityReport") if len(outputs) == 1 else {
                "passed": all(bool((item.get("qualityReport") or {}).get("passed")) for item in outputs),
                "outputs": [item.get("qualityReport") for item in outputs],
            },
            **(auto_meta or {}),
            "outputs": outputs,
        }
        with jobs_lock:
            existing_versions = list(jobs[job_id].get("outputVersions", []))
        output_versions = [*existing_versions, output_version]
        manifest = {
            "schemaVersion": 4,
            "source": Path(job["sourcePath"]).name,
            "video": {"duration": info.duration, "width": info.width, "height": info.height, "has_audio": info.has_audio},
            "selectionMode": "auto-recommended-confirmed",
            "outputMode": output_mode,
            "candidateCount": len(job.get("candidates", [])),
            "confirmedGroupIds": selection_keys if event_groups else [],
            "confirmedSegmentIds": dict(job.get("confirmedSegmentIds") or {}) if event_groups else {},
            "confirmedIndices": [] if event_groups else selection_keys,
            "actualCount": len(outputs),
            "theme": job["request"].get("theme", ""),
            "selectionBackend": job.get("selectionBackend") or f"{settings.vision_provider}-vlm",
            "compositionHash": composition_hash,
            "outputs": outputs,
            "outputVersions": output_versions,
            "currentOutputVersionId": version_id,
        }
        manifest_path = output_directory / "highlights.json"
        temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.{uuid.uuid4().hex}.tmp")
        temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_manifest.replace(manifest_path)
        update_job(
            job_id,
            status="awaiting_confirmation" if background_auto else ("completed" if finalize_status else "running"),
            progress=1.0,
            stage="auto_composition" if background_auto else ("completed" if finalize_status else "rendering"),
            stageProgress=1.0 if finalize_status else round(len(selections) / max(1, len(selections)), 4),
            stageCompleted=(min(auto_total, auto_completed + 1) if background_auto else len(selections)),
            stageTotal=auto_total if background_auto else len(selections),
            stageUnit="版本" if background_auto else ("成片" if output_mode == "single_reel" else "事件视频"),
            currentAction="成片已完成并通过媒体检查" if finalize_status else "当前版本已完成，继续生成下一个版本",
            model="FFmpeg",
            progressMode="background" if background_auto else ("completed" if finalize_status else "determinate"),
            etaSeconds=None,
            etaMode="completed" if finalize_status else ("background" if background_auto else "encoding"),
            stageCompletedSeconds=round(sum(float(item.get("duration") or 0) for item in outputs), 3),
            stageTotalSeconds=render_total_seconds,
            lastProgressAt=now_iso(),
            detail=(
                f"已生成自动版本：{variant_label}，继续生成下一个版本"
                if not finalize_status else (
                f"已生成 1 条高光成片，共 {outputs[0]['chapterCount']} 个高光事件、{outputs[0]['segmentCount']} 个镜头"
                if output_mode == "single_reel"
                else f"已分别导出 {len(outputs)} 个事件视频"
                )
            ),
            outputs=outputs,
            outputVersions=output_versions,
            currentOutputVersionId=version_id,
            outputMode=output_mode,
            actualCount=len(outputs),
            confirmedGroupIds=selection_keys if event_groups else [],
            confirmedSegmentIds=dict(job.get("confirmedSegmentIds") or {}) if event_groups else {},
            confirmedIndices=[] if event_groups else selection_keys,
            actualTotalSeconds=round(sum(float(item["duration"]) for item in outputs), 3),
        )
        version_committed = True
        quality_summary = ""
        if output_mode == "single_reel" and outputs:
            report = outputs[0].get("qualityReport") or {}
            warnings = list((report.get("editorial") or {}).get("warnings") or [])
            quality_summary = f" 成片质检 {int(report.get('score', 100))}/100，媒体完整性检查已通过。"
            if warnings:
                quality_summary += " " + "；".join(str(value) for value in warnings[:2]) + "。"
        append_message(
            job_id,
            "assistant",
            (
                f"已保存为 V{version_number}：将 {outputs[0]['chapterCount']} 个高光事件、{outputs[0]['segmentCount']} 个镜头合成为 1 条视频。{quality_summary}此前版本仍可播放和下载。"
                if output_mode == "single_reel"
                else f"已保存为 V{version_number}：分别导出 {len(outputs)} 条事件视频，共组合 {sum(int(item['segmentCount']) for item in outputs)} 个精彩镜头。此前版本仍被保留。"
            ),
            kind="result",
        )
        for item in outputs:
            output_preview_executor.submit(prepare_output_preview, job_id, str(item["filename"]))
    except Exception as error:
        cancelled = cancel_event.is_set()
        if not version_committed:
            for published in locals().get("published_paths", []):
                published.unlink(missing_ok=True)
        if 'staging_directory' in locals():
            shutil.rmtree(staging_directory, ignore_errors=True)
        # A failed new render must never make a previously valid version unusable.
        preserved = bool(previous_outputs)
        update_job(
            job_id,
            status="awaiting_confirmation" if background_auto and preserved else ("completed" if preserved else ("cancelled" if cancelled else "failed")),
            stage="auto_composition" if background_auto and preserved else ("completed" if preserved else ("cancelled" if cancelled else "failed")),
            progress=1.0 if preserved or background_auto else jobs[job_id].get("progress", 0),
            detail=(f"新版本{'已取消' if cancelled else '生成失败'}，已保留此前成片" if preserved else ("任务已取消" if cancelled else "高光裁剪失败")),
            currentAction=(f"新版本{'已取消' if cancelled else '生成失败'}，此前成片已保留" if preserved else ("任务已取消" if cancelled else "高光裁剪失败")),
            etaSeconds=None,
            etaMode="stopped",
            progressMode="completed" if preserved else "stopped",
            error=str(error)[:2000],
            outputs=previous_outputs,
            currentOutputVersionId=previous_version_id,
        )
        append_message(
            job_id,
            "assistant",
            (f"新版本{'已取消' if cancelled else '生成失败'}，此前所有成片版本均未改动。{'' if cancelled else str(error)[:500]}" if preserved else ("任务已取消" if cancelled else f"高光裁剪没有完成：{str(error)[:500]}")),
            kind="notice" if cancelled else "error",
        )
    finally:
        if 'staging_directory' in locals():
            shutil.rmtree(staging_directory, ignore_errors=True)
        with jobs_lock:
            cancel_events.pop(job_id, None)


def run_auto_variant_render(job_id: str, selection_keys: list[Any], output_mode: str, count: int) -> None:
    profiles = [("complete", "叙事完整"), ("tight", "节奏紧凑"), ("climax", "高潮优先"), ("complete", "信息密度")][:max(2, min(5, count))]
    for index, (mode, label) in enumerate(profiles):
        with jobs_lock:
            if job_id not in jobs:
                return
            if index:
                cancel_events[job_id] = threading.Event()
            jobs[job_id].update({"status": "running", "stage": "rendering", "progress": round(.82 + .16 * index / len(profiles), 3), "stageProgress": round(index / max(1, len(profiles)), 4), "detail": f"正在生成自动版本 {index + 1}/{len(profiles)} · {label}", "error": None})
            target = float(jobs[job_id].get("totalTargetSeconds") or jobs[job_id].get("request", {}).get("totalTargetSeconds") or 0)
            if jobs[job_id].get("eventGroups"):
                jobs[job_id]["confirmedSegmentIds"] = _choose_auto_segment_ids(jobs[job_id], selection_keys, mode, target)
            save_job(jobs[job_id])
        with jobs_lock:
            order_mode = str(jobs[job_id].get("orderMode") or "source")
            brief = jobs[job_id].get("brief") or {}
            subtitle_mode = str(brief.get("subtitlePreference") or jobs[job_id].get("request", {}).get("subtitleMode") or "none")
            subtitle_style = normalize_subtitle_style(brief.get("subtitleStyle") or jobs[job_id].get("request", {}).get("subtitleStyle"))
        run_confirmed_render(job_id, selection_keys, output_mode, "complete", label, finalize_status=index == len(profiles) - 1, subtitle_mode=subtitle_mode, order_mode=order_mode, subtitle_style=subtitle_style)
        with jobs_lock:
            if jobs[job_id].get("status") in {"failed", "cancelled"}:
                break
    with jobs_lock:
        job = jobs.get(job_id)
        if job and job.get("status") == "completed":
            job["detail"] = f"已生成 {len(profiles)} 个自动高光版本，可逐一预览选择"
            save_job(job)


def _validated_vision_endpoint(provider: str, base_url: str) -> tuple[str, str]:
    provider_id = provider.strip().lower().replace("-", "_")
    allowed = {"ark", "openai", "openai_compatible"}
    if provider_id not in allowed:
        raise HTTPException(400, "不支持的视觉模型服务商")
    normalized_url = base_url.strip().rstrip("/")
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "接口地址必须是有效的 HTTP 或 HTTPS 地址")
    if len(normalized_url) > 2048:
        raise HTTPException(400, "接口地址过长")
    return provider_id, normalized_url


def _validated_llm_endpoint(provider: str, base_url: str) -> tuple[str, str]:
    provider_id = provider.strip().lower().replace("-", "_")
    allowed = {str(item["id"]) for item in LLM_PROVIDER_DEFINITIONS}
    if provider_id not in allowed:
        raise HTTPException(400, "不支持的剪辑规划模型服务商")
    normalized_url = base_url.strip().rstrip("/")
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "接口地址必须是有效的 HTTP 或 HTTPS 地址")
    if len(normalized_url) > 2048:
        raise HTTPException(400, "接口地址过长")
    return provider_id, normalized_url


@app.get("/api/settings/vision")
def get_vision_settings() -> dict[str, Any]:
    """Return runtime provider settings without ever exposing credentials."""
    return vision_store.public_state()


@app.post("/api/settings/vision/discover")
def discover_vision_models(request: VisionDiscoverRequest) -> dict[str, Any]:
    provider_id = request.provider.strip().lower().replace("-", "_")
    public = vision_store.public_state()
    provider_state = next((item for item in public["providers"] if item["id"] == provider_id), None)
    if provider_state is None:
        raise HTTPException(400, "不支持的视觉模型服务商")
    resolved = vision_store.resolve(provider_id)
    base_url = request.baseUrl.strip() or str(resolved.get("baseUrl") or provider_state.get("baseUrl") or "")
    provider_id, base_url = _validated_vision_endpoint(provider_id, base_url)
    api_key = request.apiKey.strip() or str(resolved.get("apiKey") or "")
    if len(api_key) > 4096:
        raise HTTPException(400, "API Key 格式无效")
    try:
        models = discover_models(
            api_key=api_key,
            base_url=base_url,
            provider=provider_id,
            timeout_seconds=min(30.0, float(resolved.get("timeoutSeconds") or 20.0)),
        )
    except VisionRequestError as error:
        raise HTTPException(400, str(error)) from error
    return {
        "provider": provider_id,
        "providerLabel": vision_provider_label(provider_id),
        "baseUrl": base_url,
        "models": models,
        "verifiedAt": now_iso(),
        "keyHint": "已验证当前输入的密钥" if request.apiKey.strip() else provider_state.get("keyHint") or "已验证保存的密钥",
    }


@app.post("/api/settings/vision")
def save_vision_settings(request: VisionSettingsRequest) -> dict[str, Any]:
    provider_id, base_url = _validated_vision_endpoint(request.provider, request.baseUrl)
    if len(request.apiKey) > 4096:
        raise HTTPException(400, "API Key 格式无效")
    if not request.model.strip() or len(request.model.strip()) > 200:
        raise HTTPException(400, "请选择有效的视觉模型")
    thinking_type = request.thinkingType.strip().lower()
    if thinking_type not in {"", "disabled", "enabled", "auto"}:
        raise HTTPException(400, "思考模式配置无效")
    response_format = request.responseFormat.strip().lower()
    if response_format not in {"json_object", "json", "none"}:
        raise HTTPException(400, "JSON 输出配置无效")
    try:
        vision_store.save(
            provider=provider_id,
            api_key=request.apiKey,
            model=request.model,
            base_url=base_url,
            thinking_type=thinking_type,
            response_format=response_format,
            models=(request.models or [])[:500],
            verified_at=request.verifiedAt,
        )
    except VisionRequestError as error:
        raise HTTPException(400, str(error)) from error
    return vision_store.public_state()


@app.get("/api/settings/llm")
def get_llm_settings() -> dict[str, Any]:
    """Return text-planning settings without exposing credentials."""
    return llm_store.public_state()


@app.post("/api/settings/llm/discover")
def discover_text_planning_models(request: LlmDiscoverRequest) -> dict[str, Any]:
    provider_id = request.provider.strip().lower().replace("-", "_")
    public = llm_store.public_state()
    provider_state = next((item for item in public["providers"] if item["id"] == provider_id), None)
    if provider_state is None:
        raise HTTPException(400, "不支持的剪辑规划模型服务商")
    resolved = llm_store.resolve(provider_id)
    base_url = request.baseUrl.strip() or str(resolved.get("baseUrl") or provider_state.get("baseUrl") or "")
    provider_id, base_url = _validated_llm_endpoint(provider_id, base_url)
    api_key = request.apiKey.strip() or str(resolved.get("apiKey") or "")
    if len(api_key) > 4096:
        raise HTTPException(400, "API Key 格式无效")
    try:
        models = discover_llm_models(
            api_key=api_key,
            base_url=base_url,
            provider=provider_id,
            protocol=str(provider_state.get("protocol") or "openai"),
            timeout_seconds=min(30.0, float(resolved.get("timeoutSeconds") or 20.0)),
        )
    except VisionRequestError as error:
        raise HTTPException(400, str(error)) from error
    return {
        "provider": provider_id,
        "providerLabel": llm_provider_label(provider_id),
        "baseUrl": base_url,
        "models": models,
        "verifiedAt": now_iso(),
        "keyHint": "已验证当前输入的密钥" if request.apiKey.strip() else provider_state.get("keyHint") or "已验证保存的密钥",
    }


@app.post("/api/settings/llm")
def save_llm_settings(request: LlmSettingsRequest) -> dict[str, Any]:
    if request.reuseVision:
        llm_store.save(reuse_vision=True)
        return llm_store.public_state()
    provider_id, base_url = _validated_llm_endpoint(request.provider, request.baseUrl)
    if len(request.apiKey) > 4096:
        raise HTTPException(400, "API Key 格式无效")
    if not request.model.strip() or len(request.model.strip()) > 200:
        raise HTTPException(400, "请选择有效的剪辑规划模型")
    thinking_type = request.thinkingType.strip().lower()
    if thinking_type not in {"", "disabled", "enabled", "auto"}:
        raise HTTPException(400, "思考模式配置无效")
    response_format = request.responseFormat.strip().lower()
    if response_format not in {"json_object", "json", "none"}:
        raise HTTPException(400, "JSON 输出配置无效")
    try:
        llm_store.save(
            reuse_vision=False,
            provider=provider_id,
            api_key=request.apiKey,
            model=request.model,
            base_url=base_url,
            thinking_type=thinking_type,
            response_format=response_format,
            models=(request.models or [])[:500],
            verified_at=request.verifiedAt,
        )
    except VisionRequestError as error:
        raise HTTPException(400, str(error)) from error
    return llm_store.public_state()


@app.get("/api/health")
def health() -> dict[str, Any]:
    speech_state = sensevoice_status(settings.data_root / "cache" / "speech-worker" / "status.json")
    active_vision = vision_store.resolve()
    vision_configured = bool(active_vision["apiKey"] and active_vision["model"] and active_vision["baseUrl"])
    provider_label = vision_provider_label(str(active_vision["provider"]))
    active_llm = resolve_llm_configuration({"llmConfig": llm_store.snapshot(), "visionConfig": vision_store.snapshot()})
    llm_configured = bool(active_llm["apiKey"] and active_llm["model"] and active_llm["baseUrl"])
    return {
        "ok": True,
        "service": "vlm-highlight-cutter",
        "visionConfigured": vision_configured,
        "visionProvider": active_vision["provider"],
        "visionProviderLabel": provider_label,
        "visionModel": active_vision["model"],
        "visionThinking": active_vision["thinkingType"] or None,
        "visionResponseFormat": active_vision["responseFormat"],
        # Legacy response fields keep older cached frontends operational.
        "arkConfigured": vision_configured,
        "arkModel": active_vision["model"],
        "arkThinking": active_vision["thinkingType"] or None,
        "llmConfigured": llm_configured,
        "llmModel": active_llm["model"],
        "llmProvider": active_llm["provider"],
        "llmProviderLabel": active_llm["providerLabel"],
        "llmUsesVision": active_llm["mode"] == "reuse_vision",
        "llmUsesArkFallback": active_llm["mode"] == "reuse_vision" and active_llm["provider"] == "ark",
        "anthropicConfigured": llm_configured and active_llm["protocol"] == "anthropic",
        "anthropicModel": active_llm["model"] if active_llm["protocol"] == "anthropic" else None,
        "speechRecognitionConfigured": settings.speech_engine == "sensevoice" or bool(settings.whisper_model),
        "speechEngine": settings.speech_engine,
        "senseVoiceModel": settings.sensevoice_model,
        "speechModelStatus": speech_state.get("status"),
        "speechDevice": speech_state.get("device"),
        "speechDiarization": settings.sensevoice_diarization,
        "speechModelError": speech_state.get("error"),
        "ffmpeg": Path(settings.ffmpeg).is_file(),
        "ffprobe": Path(settings.ffprobe).is_file(),
        "dataRoot": str(settings.data_root),
        "keptLibrary": True,
        "portraitProxyMaxDimension": 1280,
    }


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    with jobs_lock:
        ordered = sorted(jobs.values(), key=lambda item: item.get("createdAt", ""), reverse=True)
        return {"jobs": [public_job_summary(job) for job in ordered[:30]]}


@app.get("/api/kept")
def list_kept_outputs() -> dict[str, Any]:
    return {"outputs": list_kept_records()}


@app.get("/api/kept/{job_id}/{filename}")
def kept_media(job_id: str, filename: str, download: int = 0) -> FileResponse:
    path, metadata = kept_output_paths(job_id, filename)
    if not path.is_file() or not metadata.is_file():
        raise HTTPException(404, "保留库文件不存在")
    download_name = filename
    if download:
        try:
            record = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        if isinstance(record, dict):
            download_name = str(record.get("downloadFilename") or friendly_download_filename(
                source_filename=str(record.get("sourceFilename") or "视频"),
                version_number=record.get("versionNumber", 1),
                strategy_key=str(record.get("strategyKey") or "manual"),
                source_label=str(record.get("sourceLabel") or ""),
                display_name=str(record.get("displayName") or ""),
                title=str(record.get("title") or "高光成片"),
                position=int(record.get("position") or 1),
            ))
    served_path = path
    if not download:
        preview = kept_preview_path(path)
        if not preview.is_file():
            with output_preview_generation_lock:
                if not preview.is_file():
                    info = probe_video(path, settings.ffprobe)
                    create_preview_proxy(path, preview, has_audio=info.has_audio, ffmpeg=settings.ffmpeg)
        served_path = preview
    return FileResponse(
        served_path,
        media_type="video/mp4",
        filename=download_name if download else filename,
        content_disposition_type="attachment" if download else "inline",
    )


@app.delete("/api/kept/{job_id}/{filename}")
def delete_kept_output(job_id: str, filename: str) -> dict[str, bool]:
    path, metadata = kept_output_paths(job_id, filename)
    if not path.is_file() and not metadata.is_file():
        raise HTTPException(404, "保留库文件不存在")
    remove_output_from_kept_library(job_id, filename)
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            item = next((value for value in all_job_outputs(job) if value.get("filename") == filename), None)
            if item:
                item["kept"] = False
                item.pop("keptAt", None)
                item.pop("keptSizeBytes", None)
                job["updatedAt"] = now_iso()
                persist_manifest_outputs(job)
                save_job(job)
    return {"deleted": True}


@app.post("/api/jobs", status_code=202)
async def create_job(
    video: UploadFile = File(...),
    count: str = Form("auto"),
    target_seconds: str = Form("auto"),
    total_target_seconds: str = Form(""),
    theme: str = Form(""),
    analysis_mode: str = Form("audiovisual"),
    force_reanalyze: str = Form("true"),
    subtitle_mode: str = Form("none"),
    subtitle_style: str = Form("clean"),
    edit_mode: str = Form("ai_plan"),
    structure: str = Form("auto"),
    auto_variant_count: str = Form("3"),
) -> dict[str, Any]:
    seen_inodes: set[tuple[int, int]] = set()
    used_storage = 0
    for existing_path in settings.data_root.rglob("*"):
        try:
            stat = existing_path.stat()
        except OSError:
            continue
        key = (stat.st_dev, stat.st_ino)
        if existing_path.is_file() and key not in seen_inodes:
            seen_inodes.add(key)
            used_storage += stat.st_size
    if used_storage >= settings.maximum_storage_bytes:
        raise HTTPException(507, "高光项目存储空间已达到配置上限，请先清理旧任务")
    parsed_count: int | str = "auto"
    if count.strip().lower() != "auto":
        try:
            parsed_count = int(count)
        except ValueError as error:
            raise HTTPException(400, "高光数量格式无效") from error
        if parsed_count < 1 or parsed_count > 8:
            raise HTTPException(400, "事件上限必须为 1–8 个")
    target_value = total_target_seconds.strip() or target_seconds.strip()
    parsed_total: float | None = None
    if target_value and target_value.lower() != "auto":
        try:
            parsed_total = float(target_value)
        except ValueError as error:
            raise HTTPException(400, "单条成片目标时长格式无效") from error
        if not math.isfinite(parsed_total) or parsed_total < 4 or parsed_total > 86400:
            raise HTTPException(400, "单条成片目标时长必须大于等于 4 秒")
    parsed_target: float | str = parsed_total if parsed_total is not None else "auto"
    auto_recommend = True
    if len(theme) > 500:
        raise HTTPException(400, "主题描述不能超过 500 字")
    analysis_mode = analysis_mode.strip().lower()
    if analysis_mode not in {"visual", "audiovisual"}:
        raise HTTPException(400, "分析信号模式无效")
    subtitle_mode = subtitle_mode.strip().lower()
    if subtitle_mode not in {"ask", "burn", "none"}:
        subtitle_mode = "none"
    subtitle_style = normalize_subtitle_style(subtitle_style)
    edit_mode = edit_mode.strip().lower()
    if edit_mode not in {"ai_plan", "recommend_review", "manual"}:
        edit_mode = "ai_plan"
    structure = structure.strip().lower()
    if structure not in {"auto", "hook_story_result", "montage"}:
        structure = "auto"
    try:
        parsed_auto_variant_count = int(auto_variant_count)
    except (TypeError, ValueError):
        parsed_auto_variant_count = 3
    if parsed_auto_variant_count < 1 or parsed_auto_variant_count > 4:
        raise HTTPException(400, "自动成片版本数量必须为 1–4")
    force_reanalyze_value = force_reanalyze.strip().lower() not in {"0", "false", "no", "off", "reuse", "cached"}
    suffix = Path(video.filename or "video.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}:
        raise HTTPException(400, "仅支持 MP4、MOV、MKV、WebM、M4V 和 AVI 视频")
    job_id = f"job_{uuid.uuid4().hex}"
    source = settings.data_root / "uploads" / f"{job_id}{suffix}"
    size = 0
    digest = hashlib.sha256()
    try:
        with source.open("wb") as target:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > settings.maximum_upload_bytes:
                    raise HTTPException(413, "视频超过上传大小限制")
                if used_storage + size > settings.maximum_storage_bytes:
                    raise HTTPException(507, "上传后将超过项目存储上限，请先清理旧任务")
                digest.update(chunk)
                target.write(chunk)
    except Exception:
        source.unlink(missing_ok=True)
        raise
    finally:
        await video.close()
    if size == 0:
        source.unlink(missing_ok=True)
        raise HTTPException(400, "上传的视频为空")
    source_hash = digest.hexdigest()
    with jobs_lock:
        duplicate_path = next((
            Path(existing["sourcePath"])
            for existing in jobs.values()
            if existing.get("sourceHash") == source_hash
            and int(existing.get("sizeBytes", -1)) == size
            and Path(existing.get("sourcePath", "")).is_file()
        ), None)
    if duplicate_path is not None:
        source.unlink(missing_ok=True)
        try:
            os.link(duplicate_path, source)
        except OSError:
            shutil.copy2(duplicate_path, source)
    filename = Path(video.filename or source.name).name
    count_text = "自动推荐事件数量" if parsed_count == "auto" else f"最多推荐 {parsed_count} 个高质量事件"
    duration_text = "单条成片时长由系统推荐" if parsed_total is None else f"单条成片目标约 {parsed_total:g} 秒"
    user_summary = f"分析 {filename}，{count_text}，{duration_text}；每条由同一事件的多个镜头组成"
    user_summary += "，重新调用模型分析" if force_reanalyze_value else "，允许复用相同要求的分析缓存"
    if theme.strip():
        user_summary += f"，重点关注：{theme.strip()}"
    initial_video_info = None
    try:
        probed = probe_video(source, settings.ffprobe)
        initial_video_info = {"duration": probed.duration, "width": probed.width, "height": probed.height, "has_audio": probed.has_audio}
    except Exception:
        # A malformed/partially supported file will be reported by the normal
        # analysis pipeline; upload should still create a recoverable task.
        initial_video_info = None
    job = new_job_record(
        job_id=job_id,
        source=source,
        filename=filename,
        size=size,
        count=parsed_count,
        target_seconds=parsed_target,
        theme=theme,
        messages=[
            {"id": f"msg_{uuid.uuid4().hex}", "role": "user", "text": user_summary, "kind": "request", "createdAt": now_iso()},
            {"id": f"msg_{uuid.uuid4().hex}", "role": "assistant", "text": "已收到。我会先通看全片，再精看候选附近画面，最后生成可独立播放的 MP4。", "kind": "notice", "createdAt": now_iso()},
        ],
        auto_recommend=auto_recommend,
        source_hash=source_hash,
        analysis_mode=analysis_mode,
        total_target_seconds=parsed_total,
        force_reanalyze=force_reanalyze_value,
        # All fields in this form were explicitly selected before upload.
        # Treat that action as the confirmation; do not gate the same task on
        # a second, generated brief confirmation.
        require_brief=False,
    )
    job["request"].update({
        "subtitleMode": subtitle_mode,
        "subtitleStyle": subtitle_style,
        "editMode": edit_mode,
        "structure": structure,
        "autoVariantCount": parsed_auto_variant_count,
    })
    if initial_video_info:
        job["videoInfo"] = initial_video_info
    job["brief"] = _confirmed_brief_from_request(job["request"])
    job["briefStatus"] = "confirmed"
    job["briefSource"] = "user_form"
    job["detail"] = "需求已确认，任务进入分析队列"
    job["messages"].append({"id": f"msg_{uuid.uuid4().hex}", "role": "assistant", "text": "已记录你的剪辑要求：单条成片目标时长和关注重点会用于后续分析；分析完成后还会在后台自动生成成片版本。", "kind": "brief-summary", "createdAt": now_iso()})
    enqueue_job(job)
    return {"job": public_job(job)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if not job.get("videoInfo") and Path(job.get("sourcePath", "")).is_file():
            try:
                info = probe_video(Path(job["sourcePath"]), settings.ffprobe)
                job["videoInfo"] = {"duration": info.duration, "width": info.width, "height": info.height, "has_audio": info.has_audio}
                save_job(job)
            except Exception:
                pass
        return {"job": public_job(job)}


@app.get("/api/jobs/{job_id}/status")
def get_job_status(job_id: str, revision: int | None = None) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        current_revision = int(job.get("revision") or 0)
        if revision is not None and revision == current_revision:
            return {"changed": False, "revision": current_revision}
        return {"changed": True, "revision": current_revision, "job": public_job_status(job)}


@app.post("/api/jobs/{job_id}/brief/confirm", status_code=202)
def confirm_job_brief(job_id: str, request: BriefConfirmRequest) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") != "brief_confirmation":
            raise HTTPException(409, "当前任务不在需求确认阶段")
        if request.brief is not None:
            job["brief"] = request.brief
            job["briefSource"] = "user"
        # The brief is the user's final set of instructions.  Keep the
        # executable request in sync with it before either saving a draft or
        # queueing analysis; otherwise run_job would continue using the
        # values from the initial upload form (most visibly the target
        # duration).
        brief = job.get("brief") or {}
        raw_target = brief.get("targetDurationSeconds")
        if raw_target in (None, "", "auto"):
            target_seconds = None
        else:
            try:
                target_seconds = float(raw_target)
            except (TypeError, ValueError):
                raise HTTPException(400, "目标总时长必须是有效数字")
            if not math.isfinite(target_seconds) or target_seconds < 4 or target_seconds > 86400:
                raise HTTPException(400, "目标总时长需在 4 到 86400 秒之间")
        job.setdefault("request", {})["totalTargetSeconds"] = target_seconds
        job["request"]["targetSeconds"] = target_seconds if target_seconds is not None else "auto"
        job["totalTargetSeconds"] = target_seconds
        subtitle = str(brief.get("subtitlePreference") or "none").strip().lower()
        if subtitle in {"ask", "burn", "none"}:
            job["request"]["subtitleMode"] = subtitle
        job["request"]["subtitleStyle"] = normalize_subtitle_style(brief.get("subtitleStyle"))
        job["brief"]["subtitleStyle"] = job["request"]["subtitleStyle"]
        edit_mode = str(brief.get("editMode") or "ai_plan").strip().lower()
        if edit_mode in {"ai_plan", "recommend_review", "manual"}:
            job["request"]["editMode"] = edit_mode
        structure = str(brief.get("structure") or "auto").strip().lower()
        if structure in {"auto", "hook_story_result", "montage"}:
            job["request"]["structure"] = structure
        if not request.confirmed:
            job["briefStatus"] = "draft"
            job["detail"] = "需求简报已保存，等待确认"
            job["updatedAt"] = now_iso()
            save_job(job)
            return {"job": public_job(job)}
        job["briefStatus"] = "confirmed"
        job["status"] = "queued"
        job["stage"] = "queued"
        job["progress"] = 0.0
        job["detail"] = "需求已确认，任务进入分析队列"
        job["updatedAt"] = now_iso()
        save_job(job)
        cancel_events[job_id] = threading.Event()
    append_message(job_id, "user", "确认需求简报，开始视觉分析。", kind="brief-confirmation")
    submit_analysis_task(job_id, run_job, job_id)
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.get("/api/jobs/{job_id}/waveform")
def get_job_waveform(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        source = Path(job["sourcePath"])
        identity = str(job.get("sourceHash") or job_id)
    if not source.is_file():
        raise HTTPException(404, "源视频不存在")
    # The analysis pipeline already decodes the source audio for audiovisual
    # jobs. Reuse that high-resolution envelope instead of running FFmpeg a
    # second time when the timeline asks for the waveform.
    pipeline_cache = Path(job.get("workDirectory", "")) / "timeline-waveform.json"
    if pipeline_cache.is_file():
        try:
            cached = json.loads(pipeline_cache.read_text(encoding="utf-8"))
            if cached.get("schemaVersion") == 3 and cached.get("duration"):
                return cached
        except (OSError, ValueError, TypeError):
            pass
    cache_path = waveform_cache_path(identity)
    with waveform_generation_lock:
        if cache_path.is_file():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("schemaVersion") == 3:
                    return cached
            except (OSError, ValueError):
                cache_path.unlink(missing_ok=True)
        info = probe_video(source, settings.ffprobe)
        waveform: dict[str, Any] = {
            "schemaVersion": 3,
            "duration": info.duration,
            "hasAudio": info.has_audio,
            "sampleRate": 8000,
            "peaks": [],
            "rms": [],
            "minimums": [],
            "maximums": [],
            "silences": [],
        }
        if info.has_audio:
            # Keep enough signed PCM envelope points for meaningful zooming.
            # Twelve points per second gives ~83 ms detail while the hard cap
            # bounds JSON size for very long recordings.
            waveform_bins = max(4000, min(60000, math.ceil(info.duration * 12)))
            waveform.update(extract_audio_waveform(
                source, ffmpeg=settings.ffmpeg, bins=waveform_bins, sample_rate=1000,
            ))
            waveform["pointsPerSecond"] = round(len(waveform["rms"]) / info.duration, 3)
            waveform["normalizationPeak"] = max(waveform["peaks"], default=0.0)
            waveform["silences"] = silence_intervals_from_waveform(
                waveform, duration=info.duration,
            )
            if not waveform["silences"] and not waveform.get("rms"):
                try:
                    waveform["silences"] = detect_silence_intervals(source, ffmpeg=settings.ffmpeg)
                except Exception:
                    waveform["silences"] = []
        temporary = cache_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(waveform, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(cache_path)
        return waveform


@app.get("/api/jobs/{job_id}/timeline-assets")
def get_job_timeline_assets(job_id: str, retry: bool = False) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        identity = str(job.get("sourceHash") or job_id)
    metadata_path, sprite_path = timeline_cache_paths(identity)
    partial_metadata_path, partial_sprite_path = timeline_partial_cache_paths(identity)

    if metadata_path.is_file() and sprite_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            metadata = {}
        if metadata.get("sprite"):
            generating = metadata.get("schemaVersion") == 4 and metadata.get("sceneCutsReady") is not True
            if generating:
                schedule_timeline_assets(job_id, identity, force=retry)
            revision = sprite_path.stat().st_mtime_ns
            return {
                **metadata,
                "ready": True,
                "generating": generating,
                "spriteUrl": f"/api/jobs/{job_id}/timeline-sprite?revision={revision}",
            }

    schedule_timeline_assets(job_id, identity, force=retry)
    generation_error = timeline_asset_failure(identity)
    if partial_metadata_path.is_file() and partial_sprite_path.is_file():
        try:
            metadata = json.loads(partial_metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            metadata = {}
        if metadata.get("sprite"):
            revision = int(metadata.get("frameCount") or partial_sprite_path.stat().st_mtime_ns)
            return {
                **metadata,
                "ready": True,
                "generating": generation_error is None,
                "generationError": generation_error,
                "retryable": generation_error is not None,
                "partial": True,
                "spriteUrl": f"/api/jobs/{job_id}/timeline-sprite?partial=true&revision={revision}",
            }
    return {
        "ready": False,
        "generating": generation_error is None,
        "generationError": generation_error,
        "retryable": generation_error is not None,
        "retryAfterSeconds": 10 if generation_error else None,
        "duration": float(job.get("videoInfo", {}).get("duration") or 0),
    }


@app.get("/api/jobs/{job_id}/transcript")
def get_job_transcript(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        path = Path(job["workDirectory"]) / "transcript.json"
    if not path.is_file():
        return {"segments": [], "available": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"segments": [], "available": False}
    return {**data, "available": bool(data.get("segments"))}


@app.get("/api/jobs/{job_id}/timeline-sprite")
def get_job_timeline_sprite(job_id: str, partial: bool = False) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        identity = str(job.get("sourceHash") or job_id)
    _, sprite_path = timeline_cache_paths(identity)
    _, partial_sprite_path = timeline_partial_cache_paths(identity)
    selected = partial_sprite_path if partial and partial_sprite_path.is_file() else sprite_path
    if not selected.is_file():
        schedule_timeline_assets(job_id, identity)
        raise HTTPException(404, "时间轴缩略图仍在生成")
    return FileResponse(
        selected,
        media_type="image/jpeg",
        content_disposition_type="inline",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


def event_groups_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "eventGroups": copy.deepcopy(job.get("eventGroups", [])),
        "recommendedGroupIds": list(job.get("recommendedGroupIds", [])),
    }


def finish_event_group_edit(job: dict[str, Any], before: dict[str, Any]) -> None:
    for index, group in enumerate(job.get("eventGroups", [])):
        group["index"] = index
        recalculate_event_group(group)
    valid_ids = {str(group["id"]) for group in job.get("eventGroups", [])}
    job["recommendedGroupIds"] = [value for value in job.get("recommendedGroupIds", []) if value in valid_ids]
    job["recommendedCount"] = len(job["recommendedGroupIds"])
    job["allocatedTotalSeconds"] = event_groups_total(job.get("eventGroups", []), job["recommendedGroupIds"])
    after = event_groups_snapshot(job)
    record_timeline_edit(job, target="eventGroups", before=before, after=after)
    job["updatedAt"] = now_iso()
    save_job(job)


def fragment_download_path(job: dict[str, Any], start: float, end: float, title: str) -> Path:
    identity = hashlib.sha1(f"{job['id']}|{start:.3f}|{end:.3f}".encode("utf-8")).hexdigest()[:12]
    filename = safe_highlight_filename(title or "高光片段", 1)
    return Path(job["workDirectory"]) / "fragment-downloads" / f"{identity}-{filename}"


@app.get("/api/jobs/{job_id}/fragment")
def download_fragment(job_id: str, start: float, end: float, title: str = "高光片段") -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        source = Path(job["sourcePath"])
    if not math.isfinite(start) or not math.isfinite(end):
        raise HTTPException(400, "片段时间范围无效")
    info = probe_video(source, settings.ffprobe)
    start = round(max(0.0, min(info.duration, float(start))), 3)
    end = round(max(0.0, min(info.duration, float(end))), 3)
    if end - start < 1.0:
        raise HTTPException(400, "片段至少需要 1 秒")
    output = fragment_download_path(job, start, end, title)
    if not output.is_file():
        with fragment_download_lock:
            if not output.is_file():
                render_clip(source, output, start=start, end=end, has_audio=info.has_audio, ffmpeg=settings.ffmpeg)
                validate_rendered_clip(
                    output,
                    expected_duration=end - start,
                    expect_audio=info.has_audio,
                    ffmpeg=settings.ffmpeg,
                    ffprobe=settings.ffprobe,
                )
    return FileResponse(output, media_type="video/mp4", filename=output.name, content_disposition_type="attachment")


@app.get("/api/jobs/{job_id}/event-groups/{group_id}/preview")
def preview_event_group(job_id: str, group_id: str, download: int = 0) -> FileResponse:
    try:
        path = prepare_event_group_preview(job_id, group_id)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, f"事件组合预览生成失败：{str(error)[:500]}") from error
    return FileResponse(path, media_type="video/mp4", content_disposition_type="attachment" if download else "inline")


@app.post("/api/jobs/{job_id}/event-groups")
def create_event_group(job_id: str, request: CreateEventGroupRequest) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在确认前创建事件高光")
        duration = float(job.get("videoInfo", {}).get("duration") or 0)
        start = round(max(0.0, min(duration, request.start)), 3)
        end = round(max(0.0, min(duration, request.end)), 3)
        if end - start < 1.0:
            raise HTTPException(400, "事件镜头至少保留 1 秒")
        before = event_groups_snapshot(job)
        group_id = f"event_{uuid.uuid4().hex[:12]}"
        segment = {
            "id": f"segment_{group_id}_{uuid.uuid4().hex[:10]}",
            "start": start, "end": end, "duration": round(end - start, 3),
            "sourceOrder": start, "editOrder": 0, "role": "用户核心镜头", "score": 100.0,
            "reason": "用户从源视频时间轴创建事件。", "evidence": ["用户手动指定源时间范围。"],
            "essential": True, "reusableAnchor": False,
            "transitionIn": {"type": "cut", "duration": 0.0},
        }
        requested_title = request.title.strip()[:80]
        generic_manual_titles = {"时间轴选区高光", "手动事件高光", "时间轴片段", "时间轴选区"}
        if not requested_title or requested_title in generic_manual_titles:
            manual_count = sum(1 for item in job.get("eventGroups", []) if item.get("assemblyStrategy") == "manual")
            requested_title = f"手动高光片段 {manual_count + 1:02d}"
        group = recalculate_event_group({
            "id": group_id, "index": len(job.get("eventGroups", [])),
            "title": requested_title,
            "summary": "由用户从时间轴创建，可继续加入同一事件的其他镜头。",
            "score": 100.0, "assemblyStrategy": "manual", "segments": [segment],
            "availableSegments": [copy.deepcopy(segment)],
        })
        job.setdefault("eventGroups", []).append(group)
        job.setdefault("recommendedGroupIds", []).append(group_id)
        # Keep the newly created timeline group as the pending selection so
        # polling does not reopen the entire event pool in the confirmation UI.
        job["pendingSelectionGroupIds"] = [group_id]
        finish_event_group_edit(job, before)
        return {"job": public_job(job), "groupId": group_id}


@app.post("/api/jobs/{job_id}/event-groups/from-candidates")
def create_event_group_from_candidates(job_id: str, request: CreateEventFromCandidatesRequest) -> dict[str, Any]:
    indices = list(dict.fromkeys(int(value) for value in request.indices))
    if not indices or len(indices) > 20:
        raise HTTPException(400, "请选择 1–20 个镜头候选")
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") != "awaiting_confirmation":
            raise HTTPException(409, "只能在事件审核阶段重新选择镜头")
        lookup = {int(item.get("index", -1)): item for item in job.get("candidates", [])}
        if any(index not in lookup for index in indices):
            raise HTTPException(400, "镜头候选编号无效")
        selected = [lookup[index] for index in indices]
        ordered_ranges = sorted((float(item["start"]), float(item["end"])) for item in selected)
        if any(start < previous_end for (_, previous_end), (start, _) in zip(ordered_ranges, ordered_ranges[1:])):
            raise HTTPException(409, "所选镜头存在重叠，请取消其中一个后重试")
        before = event_groups_snapshot(job)
        group_id = f"event_{uuid.uuid4().hex[:12]}"
        segments: list[dict[str, Any]] = []
        for order, candidate in enumerate(selected):
            start = round(float(candidate["start"]), 3)
            end = round(float(candidate["end"]), 3)
            segments.append({
                "id": f"segment_{group_id}_{order}_{uuid.uuid4().hex[:8]}",
                "candidateIndex": int(candidate["index"]),
                "start": start, "end": end, "duration": round(end - start, 3),
                "sourceOrder": start, "editOrder": order,
                "role": str(candidate.get("role") or candidate.get("title") or "用户选择镜头")[:40],
                "score": float(candidate.get("score") or 0),
                "reason": str(candidate.get("reason") or "用户从已分析候选池选择。")[:600],
                "evidence": list(candidate.get("evidence") or [])[:8],
                "audioEvidence": dict(candidate.get("audioEvidence") or {}),
                "essential": True, "reusableAnchor": False,
                "transitionIn": {"type": "cut", "duration": 0.0},
            })
        title = request.title.strip()[:80] or "重新编排高光"
        group = recalculate_event_group({
            "id": group_id, "index": len(job.get("eventGroups", [])), "title": title,
            "summary": f"由用户从已分析候选池重新选择的 {len(segments)} 个镜头组成。",
            "score": round(sum(float(item.get("score") or 0) for item in selected) / len(selected), 2),
            "assemblyStrategy": "candidate-reselection", "segments": segments,
            "availableSegments": copy.deepcopy(segments),
        })
        job.setdefault("eventGroups", []).append(group)
        job["recommendedGroupIds"] = [group_id]
        finish_event_group_edit(job, before)
        return {"job": public_job(job), "groupId": group_id}


@app.patch("/api/jobs/{job_id}/event-groups/{group_id}")
def rename_event_group(job_id: str, group_id: str, request: RenameEventGroupRequest) -> dict[str, Any]:
    title = request.title.strip()
    if not title or len(title) > 80:
        raise HTTPException(400, "事件名称必须为 1–80 字")
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在确认前编辑事件高光")
        before = event_groups_snapshot(job)
        find_event_group(job, group_id)["title"] = title
        finish_event_group_edit(job, before)
        return {"job": public_job(job)}


@app.post("/api/jobs/{job_id}/event-groups/{group_id}/segments")
def add_event_group_segment(job_id: str, group_id: str, request: AddEventSegmentRequest) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在确认前编辑事件高光")
        duration = float(job.get("videoInfo", {}).get("duration") or 0)
        start = round(max(0.0, min(duration, request.start)), 3)
        end = round(max(0.0, min(duration, request.end)), 3)
        if end - start < 1.0:
            raise HTTPException(400, "镜头至少保留 1 秒")
        group = find_event_group(job, group_id)
        before = event_groups_snapshot(job)
        added_segment = {
            "id": f"segment_{group_id}_{uuid.uuid4().hex[:10]}",
            "start": start, "end": end, "duration": round(end - start, 3),
            "sourceOrder": start, "editOrder": len(group.get("segments", [])),
            "role": request.role.strip()[:40] or "用户补充镜头", "score": 100.0,
            "reason": "用户从源视频时间轴加入该镜头。", "evidence": ["用户手动指定源时间范围。"],
            "essential": False, "reusableAnchor": False,
            "transitionIn": {"type": "cut", "duration": 0.0},
        }
        group.setdefault("segments", []).append(added_segment)
        group.setdefault("availableSegments", []).append(copy.deepcopy(added_segment))
        finish_event_group_edit(job, before)
        return {"job": public_job(job)}


@app.post("/api/jobs/{job_id}/event-groups/{group_id}/segments/{segment_id}/adjust")
def adjust_event_group_segment(job_id: str, group_id: str, segment_id: str, request: AdjustEventSegmentRequest) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在确认前编辑事件高光")
        duration = float(job.get("videoInfo", {}).get("duration") or 0)
        start = round(max(0.0, min(duration, request.start)), 3)
        end = round(max(0.0, min(duration, request.end)), 3)
        if end - start < 1.0:
            raise HTTPException(400, "镜头至少保留 1 秒")
        group = find_event_group(job, group_id)
        segment = next((item for item in group.get("segments", []) if str(item.get("id")) == segment_id), None)
        if segment is None:
            raise HTTPException(404, "事件镜头不存在")
        before = event_groups_snapshot(job)
        segment.update({"start": start, "end": end, "duration": round(end - start, 3), "sourceOrder": start})
        available = next((item for item in group.get("availableSegments", []) if str(item.get("id")) == segment_id), None)
        if available is not None:
            available.update({"start": start, "end": end, "duration": round(end - start, 3), "sourceOrder": start})
        finish_event_group_edit(job, before)
        return {"job": public_job(job)}


@app.delete("/api/jobs/{job_id}/event-groups/{group_id}/segments/{segment_id}")
def delete_event_group_segment(job_id: str, group_id: str, segment_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在确认前编辑事件高光")
        group = find_event_group(job, group_id)
        before = event_groups_snapshot(job)
        previous_count = len(group.get("segments", []))
        group["segments"] = [item for item in group.get("segments", []) if str(item.get("id")) != segment_id]
        group["availableSegments"] = [item for item in group.get("availableSegments", []) if str(item.get("id")) != segment_id]
        if len(group["segments"]) == previous_count:
            raise HTTPException(404, "事件镜头不存在")
        if not group["segments"]:
            job["eventGroups"] = [item for item in job["eventGroups"] if item is not group]
        finish_event_group_edit(job, before)
        return {"job": public_job(job)}


@app.post("/api/jobs/{job_id}/event-groups/{group_id}/segments/reorder")
def reorder_event_group_segments(job_id: str, group_id: str, request: ReorderEventSegmentsRequest) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在确认前编辑事件高光")
        group = find_event_group(job, group_id)
        lookup = {str(item["id"]): item for item in group.get("segments", [])}
        if set(request.segmentIds) != set(lookup) or len(request.segmentIds) != len(lookup):
            raise HTTPException(400, "镜头排序列表不完整")
        before = event_groups_snapshot(job)
        group["segments"] = [lookup[value] for value in request.segmentIds]
        available = group.get("availableSegments", [])
        available_lookup = {str(item.get("id")): item for item in available}
        active_ids = set(request.segmentIds)
        group["availableSegments"] = [
            available_lookup.get(value, copy.deepcopy(lookup[value])) for value in request.segmentIds
        ] + [item for item in available if str(item.get("id")) not in active_ids]
        finish_event_group_edit(job, before)
        return {"job": public_job(job)}


@app.post("/api/jobs/{job_id}/event-groups/{group_id}/segments/{segment_id}/move")
def move_event_group_segment(job_id: str, group_id: str, segment_id: str, request: MoveEventSegmentRequest) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在确认前编辑事件高光")
        source_group = find_event_group(job, group_id)
        destination = find_event_group(job, request.destinationGroupId)
        segment = next((item for item in source_group.get("segments", []) if str(item.get("id")) == segment_id), None)
        if segment is None:
            raise HTTPException(404, "事件镜头不存在")
        before = event_groups_snapshot(job)
        source_group["segments"].remove(segment)
        source_available = source_group.get("availableSegments", [])
        available_segment = next(
            (item for item in source_available if str(item.get("id")) == segment_id),
            copy.deepcopy(segment),
        )
        source_group["availableSegments"] = [
            item for item in source_available if str(item.get("id")) != segment_id
        ]
        target = len(destination.get("segments", [])) if request.targetIndex is None else max(0, min(len(destination.get("segments", [])), request.targetIndex))
        destination.setdefault("segments", []).insert(target, segment)
        destination_available = destination.setdefault("availableSegments", [])
        available_target = max(0, min(len(destination_available), target))
        destination_available.insert(available_target, available_segment)
        if not source_group["segments"]:
            job["eventGroups"] = [item for item in job["eventGroups"] if item is not source_group]
        finish_event_group_edit(job, before)
        return {"job": public_job(job)}


@app.post("/api/jobs/{job_id}/candidates/{candidate_index}/adjust")
def adjust_job_candidate(job_id: str, candidate_index: int, request: AdjustCandidateRequest) -> dict[str, Any]:
    if not math.isfinite(request.start) or not math.isfinite(request.end):
        raise HTTPException(400, "候选边界必须是有效数字")
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在候选确认阶段调整边界")
        candidates = job.get("candidates", [])
        candidate = next((item for item in candidates if int(item.get("index", -1)) == candidate_index), None)
        if candidate is None:
            raise HTTPException(404, "高光候选不存在")
        duration = float(job.get("videoInfo", {}).get("duration") or 0)
        if duration <= 0:
            raise HTTPException(409, "视频时长信息缺失")
        start = round(max(0.0, min(duration, request.start)), 3)
        end = round(max(0.0, min(duration, request.end)), 3)
        if end - start < 1.0:
            raise HTTPException(400, "候选片段必须至少保留 1 秒")
        if end - start > 180.0:
            raise HTTPException(400, "候选片段不能超过 180 秒")
        before = {key: candidate.get(key) for key in ("start", "end", "duration", "boundaryAdjusted")}
        candidate.update({"start": start, "end": end, "duration": round(end - start, 3), "boundaryAdjusted": True})
        after = {key: candidate.get(key) for key in ("start", "end", "duration", "boundaryAdjusted")}
        record_timeline_edit(job, target="candidate", candidate_index=candidate_index, before=before, after=after)
        job["updatedAt"] = now_iso()
        save_job(job)
        return {"candidate": dict(candidate)}


@app.post("/api/jobs/{job_id}/review-exclusions")
def set_review_exclusions(job_id: str, request: ReviewExclusionsRequest) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] not in ("awaiting_confirmation", "completed"):
            raise HTTPException(409, "请等待分析完成后再调整候选排除状态")
        valid = {int(item.get("index", -1)) for item in job.get("candidates", [])}
        excluded = sorted({int(index) for index in request.indices if int(index) in valid})
        job["reviewExcludedCandidates"] = excluded
        job["updatedAt"] = now_iso()
        save_job(job)
        return {"job": public_job(job)}


@app.post("/api/jobs/{job_id}/selection")
def set_job_timeline_selection(job_id: str, request: TimelineSelectionRequest) -> dict[str, Any]:
    if not math.isfinite(request.start) or not math.isfinite(request.end):
        raise HTTPException(400, "时间轴选区必须是有效数字")
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] not in ("awaiting_confirmation", "completed"):
            raise HTTPException(409, "请等待分析完成后再手动选择时间范围")
        duration = float(job.get("videoInfo", {}).get("duration") or 0)
        source_path = Path(job["sourcePath"])
    if duration <= 0:
        duration = probe_video(source_path, settings.ffprobe).duration
    start = round(max(0.0, min(duration, request.start)), 3)
    end = round(max(0.0, min(duration, request.end)), 3)
    if end - start < 1.0:
        raise HTTPException(400, "手动选区必须至少保留 1 秒")
    if end - start > 180.0:
        raise HTTPException(400, "手动选区不能超过 180 秒")
    with jobs_lock:
        previous_selection = dict(jobs[job_id].get("manualSelection") or {}) or None
        previous_title = str((previous_selection or {}).get("title") or "").strip()
    selection = {"start": start, "end": end, "duration": round(end - start, 3)}
    if previous_title:
        selection["title"] = previous_title[:80]
    with jobs_lock:
        job = jobs[job_id]
        job["manualSelection"] = selection
        record_timeline_edit(job, target="selection", before=previous_selection, after=dict(selection))
        job["updatedAt"] = now_iso()
        save_job(job)
    return {"selection": selection}


def apply_timeline_history_state(job: dict[str, Any], edit: dict[str, Any], state: str) -> None:
    value = edit.get(state)
    if edit.get("target") == "eventGroups":
        job["eventGroups"] = copy.deepcopy((value or {}).get("eventGroups", []))
        job["recommendedGroupIds"] = list((value or {}).get("recommendedGroupIds", []))
        job["recommendedCount"] = len(job["recommendedGroupIds"])
        job["allocatedTotalSeconds"] = event_groups_total(job["eventGroups"], job["recommendedGroupIds"])
        return
    if edit.get("target") == "candidates":
        job["candidates"] = copy.deepcopy((value or {}).get("candidates", []))
        job["recommendedIndices"] = list((value or {}).get("recommendedIndices", []))
        job["recommendedCount"] = len(job["recommendedIndices"])
        job["detail"] = f"当前共有 {len(job['candidates'])} 个候选"
        return
    if edit.get("target") == "selection":
        if value is None:
            job.pop("manualSelection", None)
        else:
            job["manualSelection"] = dict(value)
        return
    candidate_index = int(edit.get("candidateIndex", -1))
    candidate = next((
        item for item in job.get("candidates", []) if int(item.get("index", -1)) == candidate_index
    ), None)
    if candidate is None or value is None:
        raise HTTPException(409, "无法恢复已经不存在的候选")
    candidate.update(value)


@app.post("/api/jobs/{job_id}/timeline/undo")
def undo_job_timeline(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在候选确认阶段撤销时间轴修改")
        history = job.setdefault("timelineUndo", [])
        if not history:
            raise HTTPException(409, "没有可以撤销的时间轴修改")
        edit = history.pop()
        apply_timeline_history_state(job, edit, "before")
        job.setdefault("timelineRedo", []).append(edit)
        job["updatedAt"] = now_iso()
        save_job(job)
        return {"job": public_job(job)}


@app.post("/api/jobs/{job_id}/timeline/redo")
def redo_job_timeline(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "只能在候选确认阶段恢复时间轴修改")
        redo = job.setdefault("timelineRedo", [])
        if not redo:
            raise HTTPException(409, "没有可以恢复的时间轴修改")
        edit = redo.pop()
        apply_timeline_history_state(job, edit, "after")
        job.setdefault("timelineUndo", []).append(edit)
        job["updatedAt"] = now_iso()
        save_job(job)
        return {"job": public_job(job)}


@app.post("/api/jobs/{job_id}/auto-plans", status_code=202)
def create_auto_edit_plans(job_id: str, request: AutoPlanRequest) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") != "awaiting_confirmation":
            raise HTTPException(409, "只能在候选审核阶段生成自动剪辑方案")
        if not job.get("eventGroups"):
            raise HTTPException(409, "当前任务没有事件候选，无法生成细粒度剪辑方案")
        cancel_events[job_id] = threading.Event()
    render_executor.submit(run_auto_plan_generation, job_id, request)
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/llm-order", status_code=202)
def create_llm_order(job_id: str, request: LlmOrderRequest) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") != "awaiting_confirmation":
            raise HTTPException(409, "只能在候选确认阶段推荐镜头顺序")
        if not request.groupIds:
            raise HTTPException(400, "请至少选择一个高光事件")
        cancel_events[job_id] = threading.Event()
    render_executor.submit(run_llm_order_generation, job_id, request)
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/auto-plans/{plan_id}/render", status_code=202)
def render_auto_edit_plan(job_id: str, plan_id: str, request: RenderAutoPlanRequest | None = None) -> dict[str, Any]:
    request = request or RenderAutoPlanRequest(planId=plan_id)
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") != "awaiting_confirmation":
            raise HTTPException(409, "当前任务不在方案审核阶段")
        plan = next((item for item in job.get("autoPlans", []) if str(item.get("id")) == str(plan_id)), None)
        if not plan or not plan.get("sequence"):
            raise HTTPException(404, "剪辑方案不存在或没有可用镜头")
        job.update({"status": "running", "stage": "rendering", "progress": .82, "stageProgress": 0.0, "detail": f"正在渲染：{plan.get('label') or '自动剪辑方案'}", "error": None, "outputMode": "single_reel"})
        cancel_events[job_id] = threading.Event()
        save_job(job)
    append_message(job_id, "user", f"确认生成剪辑方案：{plan.get('label') or plan_id}", kind="confirmation")
    append_message(job_id, "assistant", "已确认方案，正在按已确认的镜头范围和方案顺序生成成片。", kind="notice")
    if request.subtitleMode not in {"none", "burn"}:
        raise HTTPException(400, "字幕方式无效，请选择“不添加字幕”或“添加 AI 字幕”")
    subtitle_style = normalize_subtitle_style(request.subtitleStyle)
    subtitle_mode = request.subtitleMode
    render_executor.submit(run_confirmed_render, job_id, [], "single_reel", "complete", str(plan.get("label") or "LLM 方案"), True, list(plan.get("sequence") or []), str(plan.get("label") or "LLM 细粒度高光成片"), list(plan.get("chapters") or []), subtitle_mode, "selection", subtitle_style)
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/confirm", status_code=202)
def confirm_job_candidates(job_id: str, request: ConfirmCandidatesRequest) -> dict[str, Any]:
    output_mode = str(request.outputMode or "single_reel")
    order_mode = str(request.orderMode or "source")
    if order_mode not in {"selection", "source", "ai_plan"}:
        raise HTTPException(400, "合成顺序模式无效")
    auto_variant_count = max(0, min(5, int(request.autoVariants or 0)))
    if output_mode not in {"single_reel", "separate_events"}:
        raise HTTPException(400, "输出模式无效")
    if request.subtitleMode not in {"none", "burn"}:
        raise HTTPException(400, "字幕方式无效，请选择“不添加字幕”或“添加 AI 字幕”")
    subtitle_mode = request.subtitleMode
    subtitle_style = normalize_subtitle_style(request.subtitleStyle)
    selection_summary = ""
    order_summary = {
        "selection": "按你选择事件和镜头的顺序",
        "source": "按原视频时间顺序",
        "ai_plan": "按 AI 规划的叙事顺序",
    }.get(order_mode, "按你选择的顺序")

    def clip_clock(value: Any) -> str:
        seconds = max(0.0, float(value or 0))
        minutes = int(seconds // 60)
        rest = seconds - minutes * 60
        return f"{minutes:02d}:{rest:04.1f}"

    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "awaiting_confirmation":
            raise HTTPException(409, "当前任务不在候选确认阶段")
        event_groups = job.get("eventGroups") or []
        if event_groups:
            group_ids = request.groupIds if request.groupIds is not None else list(job.get("recommendedGroupIds", []))
            group_ids = list(dict.fromkeys(str(value) for value in group_ids))
            lookup = {str(group.get("id")): group for group in event_groups}
            if not group_ids or len(group_ids) > 8 or any(value not in lookup for value in group_ids):
                raise HTTPException(400, "事件高光选择无效")
            requested_segments = request.segmentIds or {}
            selected_groups = []
            for value in group_ids:
                group = copy.deepcopy(lookup[value])
                ids = requested_segments.get(value)
                if ids is not None:
                    allowed = {str(item.get("id")) for item in group.get("segments", [])}
                    selected_ids = {str(item) for item in ids if str(item) in allowed}
                    by_id = {str(item.get("id")): item for item in group.get("segments", [])}
                    # Preserve the user's explicit order from the dialog;
                    # source/LLM ordering can still normalize it later.
                    group["segments"] = [by_id[item_id] for item_id in ids if str(item_id) in selected_ids]
                if not group.get("segments"):
                    raise HTTPException(400, f"事件“{group.get('title') or value}”至少需要保留一个镜头")
                group["actualDuration"] = round(sum(float(item.get("duration") or (float(item.get("end", 0)) - float(item.get("start", 0)))) for item in group["segments"]), 3)
                selected_groups.append(group)
            subject_segments: list[dict[str, Any]] = []
            for group in selected_groups:
                for segment in group.get("segments", []):
                    if segment.get("reusableAnchor"):
                        continue
                    if any(
                        max(float(segment["start"]), float(other["start"]))
                        < min(float(segment["end"]), float(other["end"]))
                        for other in subject_segments
                    ):
                        raise HTTPException(409, "所选事件组复用了主体镜头；请删除重复镜头或标记为上下文锚点")
                    subject_segments.append(segment)
            total = sum(float(item.get("actualDuration") or 0) for item in selected_groups)
            segment_count = sum(len(item.get("segments", [])) for item in selected_groups)
            selection_summary = "；".join(
                f"{group.get('title') or '未命名事件'}："
                + ", ".join(
                    f"镜头{index + 1} {clip_clock(segment.get('start'))}→{clip_clock(segment.get('end'))}"
                    for index, segment in enumerate(group.get("segments", []))
                )
                for group in selected_groups
            )
            if order_mode == "source":
                ordered = sorted(
                    ((group.get("title") or "未命名事件", segment) for group in selected_groups for segment in group.get("segments", [])),
                    key=lambda pair: float(pair[1].get("start") or 0),
                )
                selection_summary = "；".join(
                    f"{title}：{clip_clock(segment.get('start'))}→{clip_clock(segment.get('end'))}"
                    for title, segment in ordered
                )
            job.update({
                "status": "running", "stage": "rendering", "progress": .82, "stageProgress": 0.0,
                "detail": (
                    f"已确认 {len(group_ids)} 个高光事件、共 {segment_count} 个镜头，准备合成 1 条高光成片"
                    if output_mode == "single_reel"
                    else f"已确认 {len(group_ids)} 个高光事件，准备分别导出"
                ),
                "outputMode": output_mode,
                "orderMode": order_mode,
                "confirmedSegmentIds": {str(group.get("id")): [str(item.get("id")) for item in group.get("segments", [])] for group in selected_groups},
                "pendingSelectionGroupIds": [],
                "reediting": False,
                "error": None, "updatedAt": now_iso(),
            })
            cancel_events[job_id] = threading.Event()
            save_job(job)
            selections: list[Any] = group_ids
            duration_text = f"预计成片 {total:.1f} 秒"
        else:
            candidates = job.get("candidates", [])
            indices = request.indices if request.indices is not None else list(job.get("recommendedIndices", []))
            indices = list(dict.fromkeys(indices))
            if not indices:
                raise HTTPException(400, "请至少选择一个高光候选")
            if len(indices) > 8 or any(index < 0 or index >= len(candidates) for index in indices):
                raise HTTPException(400, "候选编号无效")
            selected = [candidates[index] for index in indices]
            ordered_ranges = sorted((float(item["start"]), float(item["end"])) for item in selected)
            if any(current_start < previous_end for (_, previous_end), (current_start, _) in zip(ordered_ranges, ordered_ranges[1:])):
                raise HTTPException(409, "所选候选区间发生重叠，请取消其中一条或重新选择镜头")
            job.update({
                "status": "running", "stage": "rendering", "progress": .82,
                "detail": (
                    f"已确认 {len(indices)} 个镜头，准备合成 1 条高光成片"
                    if output_mode == "single_reel"
                    else f"已确认 {len(indices)} 个镜头，准备分别导出"
                ),
                "outputMode": output_mode,
                "orderMode": order_mode,
                "pendingSelectionGroupIds": [],
                "reediting": False,
                "error": None, "updatedAt": now_iso(),
            })
            cancel_events[job_id] = threading.Event()
            save_job(job)
            selections = indices
            duration_text = "、".join(f"{float(item['duration']):.1f} 秒" for item in selected)
            total = sum(float(item.get("duration") or 0) for item in selected)
            segment_count = len(selected)
            selection_summary = "；".join(
                f"{item.get('title') or f'候选 {index + 1}'}：{clip_clock(item.get('start'))}→{clip_clock(item.get('end'))}"
                for index, item in zip(indices, selected)
            )
    if output_mode == "single_reel":
        append_message(job_id, "user", f"确认将 {len(selections)} 个高光事件合成为 1 条视频，{duration_text}", kind="confirmation")
        append_message(
            job_id,
            "assistant",
            f"确认收到。将按以下顺序合成 1 条高光成片（共 {segment_count} 个镜头，预计 {total:.1f} 秒）：{selection_summary}。"
            f"合成顺序：{order_summary}。"
            "合成期间可在视频预览区查看源片段；完成后可以预览并下载 MP4 成片。",
            kind="notice",
        )
    else:
        append_message(job_id, "user", f"确认分别导出 {len(selections)} 个事件视频，{duration_text}", kind="confirmation")
        append_message(job_id, "assistant", "确认收到，正在分别导出每个事件视频。", kind="notice")
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            job.setdefault("request", {})["subtitleMode"] = subtitle_mode
            job["request"]["subtitleStyle"] = subtitle_style
            job.setdefault("brief", {})["subtitlePreference"] = subtitle_mode
            job["brief"]["subtitleStyle"] = subtitle_style
            save_job(job)
    if auto_variant_count >= 2 and output_mode == "single_reel":
        append_message(job_id, "assistant", f"将基于当前选择自动生成 {auto_variant_count} 个不同编排版本，完成后可逐一预览。", kind="notice")
        render_executor.submit(run_auto_variant_render, job_id, selections, output_mode, auto_variant_count)
    else:
        render_executor.submit(run_confirmed_render, job_id, selections, output_mode, "complete", "", True, None, "", None, subtitle_mode, order_mode, subtitle_style)
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/reedit")
def reopen_job_for_editing(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        status = str(job.get("status") or "")
        has_outputs = bool(job.get("outputs") or any(version.get("outputs") for version in job.get("outputVersions", [])))
        # A rendered version can coexist with awaiting_confirmation while the
        # reusable event pool remains available. It is still safe to re-edit.
        if status not in {"completed", "awaiting_confirmation"} or (status == "awaiting_confirmation" and not has_outputs):
            raise HTTPException(409, "当前任务尚未生成可重新编排的成片")
        if not job.get("eventGroups") and not job.get("candidates"):
            raise HTTPException(409, "该任务没有可复用的分析候选")
        group_ids = {str(group.get("id")) for group in job.get("eventGroups", [])}
        last_groups = [str(value) for value in job.get("confirmedGroupIds", []) if str(value) in group_ids]
        if last_groups:
            job["recommendedGroupIds"] = last_groups
        candidate_indices = {int(item.get("index", -1)) for item in job.get("candidates", [])}
        last_indices = [int(value) for value in job.get("confirmedIndices", []) if int(value) in candidate_indices]
        if last_indices:
            job["recommendedIndices"] = last_indices
        job.update({
            "status": "awaiting_confirmation",
            "stage": "reediting",
            "progress": .82,
            "detail": "已返回事件审核，可重新选择镜头后生成新版本；返回操作本身不会重新分析视频",
            "reediting": True,
            "error": None,
            "updatedAt": now_iso(),
        })
        save_job(job)
    append_message(job_id, "user", "重新选择已经分析好的镜头并合成", kind="revision")
    append_message(job_id, "assistant", "已返回事件审核。可以重新选择高光事件，并从“镜头候选”中增删或移动镜头；按当前选择生成时只会重新渲染，不会再次分析视频。", kind="revision")
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/reedit/cancel")
def cancel_job_reediting(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") != "awaiting_confirmation" or not job.get("reediting") or not job.get("outputs"):
            raise HTTPException(409, "当前任务不在重新编排状态")
        job.update({
            "status": "completed", "stage": "completed", "progress": 1.0,
            "detail": "已保留上一次生成结果", "reediting": False, "updatedAt": now_iso(),
        })
        save_job(job)
        return {"job": public_job(job)}


def require_completed_job(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] != "completed":
            raise HTTPException(409, "只能修改已经完成的高光任务")
        return job


def output_by_filename(job: dict[str, Any], filename: str) -> dict[str, Any]:
    item = next((entry for entry in all_job_outputs(job) if entry.get("filename") == filename), None)
    if not item:
        raise HTTPException(404, "高光片段不存在")
    return item


def persist_manifest_outputs(job: dict[str, Any]) -> None:
    manifest_path = Path(job["outputDirectory"]) / "highlights.json"
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    manifest["outputs"] = job.get("outputs", [])
    manifest["outputVersions"] = job.get("outputVersions", [])
    manifest["currentOutputVersionId"] = job.get("currentOutputVersionId")
    manifest["actualCount"] = len(job.get("outputs", []))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def adjust_output(job_id: str, filename: str, request: AdjustOutputRequest, user_text: str | None = None) -> dict[str, Any]:
    job = require_completed_job(job_id)
    item = output_by_filename(job, filename)
    if item.get("versionId") and item.get("versionId") != job.get("currentOutputVersionId"):
        raise HTTPException(409, "历史版本不可直接改写；请先将它设为当前版本，或重新选择镜头生成新版本")
    if item.get("segments"):
        raise HTTPException(409, "组合事件高光包含多个源镜头，请在确认前展开事件组调整具体镜头")
    info = probe_video(Path(job["sourcePath"]), settings.ffprobe)
    start = float(item["start"]) if request.start is None else request.start
    end = float(item["end"]) if request.end is None else request.end
    start += request.startDelta
    end += request.endDelta
    start = round(max(0.0, min(info.duration, start)), 3)
    end = round(max(0.0, min(info.duration, end)), 3)
    if end - start < 1.0:
        raise HTTPException(400, "调整后的高光必须至少保留 1 秒")
    output_path = Path(job["outputDirectory"]) / filename
    render_clip(
        Path(job["sourcePath"]),
        output_path,
        start=start,
        end=end,
        has_audio=info.has_audio,
        ffmpeg=settings.ffmpeg,
    )
    rendered = validate_rendered_clip(
        output_path,
        expected_duration=end - start,
        expect_audio=info.has_audio,
        ffmpeg=settings.ffmpeg,
        ffprobe=settings.ffprobe,
    )
    with jobs_lock:
        current = jobs[job_id]
        current_item = output_by_filename(current, filename)
        current_item.update({"start": start, "end": end, "duration": round(rendered.duration, 3)})
        current["detail"] = f"已调整 {filename} 的剪辑边界"
        current["updatedAt"] = now_iso()
        persist_manifest_outputs(current)
        save_job(current)
        refresh_kept_copy = bool(current_item.get("kept"))
    if refresh_kept_copy:
        record = save_output_to_kept_library(current, current_item)
        with jobs_lock:
            current_item["keptAt"] = record["keptAt"]
            current_item["keptSizeBytes"] = record["sizeBytes"]
            persist_manifest_outputs(current)
            save_job(current)
    index = int(re.search(r"(\d+)", filename).group(1)) if re.search(r"(\d+)", filename) else 1
    if user_text:
        append_message(job_id, "user", user_text, kind="revision")
    append_message(
        job_id,
        "assistant",
        f"已重新裁剪第 {index} 条：{start:.1f} 秒到 {end:.1f} 秒，时长 {end - start:.1f} 秒。视觉内容没有重新分析。",
        kind="revision",
    )
    with jobs_lock:
        return jobs[job_id]


def create_derived_job(parent_job_id: str, request: DeriveJobRequest) -> dict[str, Any]:
    parent = require_completed_job(parent_job_id)
    parent_count = parent["request"].get("count")
    parent_target = parent["request"].get("totalTargetSeconds", parent["request"].get("targetSeconds"))
    fallback_count = len(parent.get("outputs", [])) or int(parent.get("recommendedCount") or 3)
    output_durations = [float(item["duration"]) for item in parent.get("outputs", []) if item.get("duration")]
    fallback_target = sum(output_durations) if output_durations else 60.0
    count = request.count if request.count is not None else (
        int(parent_count) if str(parent_count).lower() != "auto" else fallback_count
    )
    target_seconds = request.targetSeconds if request.targetSeconds is not None else (
        float(parent_target) if str(parent_target).lower() != "auto" else fallback_target
    )
    theme = request.theme.strip() if request.theme is not None else str(parent["request"].get("theme", ""))
    if count < 1 or count > 8:
        raise HTTPException(400, "事件上限必须为 1–8 个")
    if target_seconds < 4 or target_seconds > 86400:
        raise HTTPException(400, "单条成片目标时长必须大于等于 4 秒")
    if len(theme) > 500:
        raise HTTPException(400, "主题描述不能超过 500 字")
    source_parent = Path(parent["sourcePath"])
    if not source_parent.is_file():
        raise HTTPException(404, "源视频不存在")
    job_id = f"job_{uuid.uuid4().hex}"
    source = settings.data_root / "uploads" / f"{job_id}{source_parent.suffix.lower()}"
    try:
        os.link(source_parent, source)
    except OSError:
        shutil.copy2(source_parent, source)
    exclusions = list(parent.get("excludedRanges", []))
    if request.excludeExisting:
        for output in parent.get("outputs", []):
            ranges = output.get("segments") or [output]
            exclusions.extend({"start": float(item["start"]), "end": float(item["end"])} for item in ranges)
    unique_exclusions: list[dict[str, float]] = []
    seen: set[tuple[float, float]] = set()
    for item in exclusions:
        key = (round(float(item["start"]), 3), round(float(item["end"]), 3))
        if key not in seen:
            seen.add(key)
            unique_exclusions.append({"start": key[0], "end": key[1]})
    messages = [dict(message) for message in parent.get("messages", [])]
    messages.extend([
        {"id": f"msg_{uuid.uuid4().hex}", "role": "user", "text": request.message, "kind": "revision", "createdAt": now_iso()},
        {
            "id": f"msg_{uuid.uuid4().hex}",
            "role": "assistant",
            "text": "我会重新调用视觉模型，并排除已有高光区间。" if request.excludeExisting else "我会按新的要求重新分析视频。",
            "kind": "notice",
            "createdAt": now_iso(),
        },
    ])
    job = new_job_record(
        job_id=job_id,
        source=source,
        filename=parent["filename"],
        size=source.stat().st_size,
        count=count,
        target_seconds=target_seconds,
        theme=theme,
        messages=messages,
        parent_job_id=parent_job_id,
        excluded_ranges=unique_exclusions,
        source_hash=parent.get("sourceHash"),
        analysis_mode=str(parent["request"].get("analysisMode") or "visual"),
        total_target_seconds=target_seconds,
        auto_recommend=True,
        force_reanalyze=True,
    )
    enqueue_job(job)
    return job


@app.post("/api/jobs/{job_id}/outputs/{filename}/adjust")
def adjust_job_output(job_id: str, filename: str, request: AdjustOutputRequest) -> dict[str, Any]:
    return {"job": public_job(adjust_output(job_id, filename, request))}


@app.post("/api/jobs/{job_id}/outputs/{filename}/keep")
def keep_job_output(job_id: str, filename: str, request: KeepOutputRequest) -> dict[str, Any]:
    job = require_completed_job(job_id)
    item = output_by_filename(job, filename)
    record = save_output_to_kept_library(job, item) if request.kept else None
    if not request.kept:
        remove_output_from_kept_library(job_id, filename)
    with jobs_lock:
        item = output_by_filename(jobs[job_id], filename)
        item["kept"] = request.kept
        if record:
            item["keptAt"] = record["keptAt"]
            item["keptSizeBytes"] = record["sizeBytes"]
        else:
            item.pop("keptAt", None)
            item.pop("keptSizeBytes", None)
        version = find_output_version(job, str(item.get("versionId") or job.get("currentOutputVersionId")))
        version_outputs = version.get("outputs", []) if version else job.get("outputs", [])
        index = version_outputs.index(item) + 1
        jobs[job_id]["updatedAt"] = now_iso()
        persist_manifest_outputs(jobs[job_id])
        save_job(jobs[job_id])
    append_message(job_id, "user", f"{'保存到保留库' if request.kept else '从保留库移除'}第 {index} 条高光", kind="review")
    append_message(
        job_id, "assistant",
        f"第 {index} 条已{'复制到独立保留库；删除原任务也不会移除它' if request.kept else '从独立保留库移除'}。",
        kind="review",
    )
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/output-versions/{version_id}/activate")
def activate_job_output_version(job_id: str, version_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") != "completed":
            raise HTTPException(409, "任务完成后才能切换成片版本")
        version = find_output_version(job, version_id)
        if not version:
            raise HTTPException(404, "成片版本不存在")
        job["currentOutputVersionId"] = version_id
        job["outputs"] = version.setdefault("outputs", [])
        job["outputMode"] = version.get("outputMode", job.get("outputMode"))
        job["confirmedGroupIds"] = list(version.get("confirmedGroupIds", []))
        job["confirmedIndices"] = list(version.get("confirmedIndices", []))
        job["actualCount"] = len(job["outputs"])
        job["actualTotalSeconds"] = round(sum(float(item.get("duration") or 0) for item in job["outputs"]), 3)
        job["detail"] = f"已将 V{int(version.get('number') or 1)} 设为当前成片版本"
        job["updatedAt"] = now_iso()
        persist_manifest_outputs(job)
        save_job(job)
        return {"job": public_job(job)}


@app.delete("/api/jobs/{job_id}/output-versions/{version_id}")
def delete_job_output_version(job_id: str, version_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") != "completed":
            raise HTTPException(409, "任务完成后才能删除成片版本")
        normalize_output_versions(job)
        versions = job.get("outputVersions", [])
        version = next((item for item in versions if str(item.get("id")) == version_id), None)
        if not version:
            raise HTTPException(404, "成片版本不存在")
        if len(versions) <= 1:
            raise HTTPException(409, "至少保留一个成片版本")
        filenames = [str(item.get("filename")) for item in version.get("outputs", []) if item.get("filename")]
        versions.remove(version)
        if job.get("currentOutputVersionId") == version_id:
            current = max(versions, key=lambda item: int(item.get("number") or 0))
            job["currentOutputVersionId"] = current["id"]
            job["outputs"] = current.setdefault("outputs", [])
            job["outputMode"] = current.get("outputMode", job.get("outputMode"))
        job["actualCount"] = len(job.get("outputs", []))
        job["actualTotalSeconds"] = round(sum(float(item.get("duration") or 0) for item in job.get("outputs", [])), 3)
        job["detail"] = f"已删除成片版本 V{int(version.get('number') or 1)}"
        job["updatedAt"] = now_iso()
        persist_manifest_outputs(job)
        save_job(job)
    output_directory = Path(job["outputDirectory"])
    for filename in filenames:
        (output_directory / filename).unlink(missing_ok=True)
        preview = output_preview_path(job, filename)
        preview.unlink(missing_ok=True)
        preview.with_suffix(".tmp.mp4").unlink(missing_ok=True)
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/derive", status_code=202)
def derive_job(job_id: str, request: DeriveJobRequest) -> dict[str, Any]:
    return {"job": public_job(create_derived_job(job_id, request))}


CHINESE_NUMBERS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}


def parsed_index(value: str) -> int:
    return int(value) if value.isdigit() else CHINESE_NUMBERS.get(value, 1)


def parse_candidate_adjustment(text: str) -> dict[str, Any] | None:
    prefix = r"第\s*([一二两三四五六七八\d]+)\s*条"
    number = r"(\d+(?:\.\d+)?)\s*(?:秒|s)"
    boundary = re.search(
        prefix + r".*?(开头|开始|结尾|结束).*?(提前|延后|往前|往后)\s*" + number,
        text,
        flags=re.IGNORECASE,
    )
    if boundary:
        return {
            "index": parsed_index(boundary.group(1)),
            "kind": "boundary",
            "boundary": "start" if boundary.group(2) in ("开头", "开始") else "end",
            "direction": -1 if boundary.group(3) in ("提前", "往前") else 1,
            "seconds": float(boundary.group(4)),
        }
    duration = re.search(
        prefix + r".*?(?:改成|调整为|设为|时长(?:改为|调整为)?)\s*" + number,
        text,
        flags=re.IGNORECASE,
    )
    if duration:
        return {"index": parsed_index(duration.group(1)), "kind": "duration", "seconds": float(duration.group(2))}
    relative = re.search(
        prefix + r".*?(增加|延长|加长|缩短|减少)\s*" + number,
        text,
        flags=re.IGNORECASE,
    )
    if relative:
        return {
            "index": parsed_index(relative.group(1)),
            "kind": "relative",
            "direction": -1 if relative.group(2) in ("缩短", "减少") else 1,
            "seconds": float(relative.group(3)),
        }
    return None


def parse_requested_title(text: str) -> str | None:
    match = re.search(
        r"(?:命名为|取名为|改名为|叫做|名称为)\s*[“\"']?"
        r"([^”\"'，,。；;\n]{1,80}?)[”\"']?"
        r"(?=\s*(?:[，,。；;]|并?(?:加入|添加|生成|裁剪)|$))",
        text,
    )
    if not match:
        return None
    title = match.group(1).strip()
    return title[:80] if title else None


def rename_candidate_from_chat(job_id: str, text: str, human_index: int, title: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs[job_id]
        candidates = job.get("candidates", [])
        if human_index < 1 or human_index > len(candidates):
            raise HTTPException(400, f"当前只有 {len(candidates)} 条候选")
        candidate = candidates[human_index - 1]
        before = {"title": candidate.get("title"), "titleCustomized": candidate.get("titleCustomized", False)}
        candidate["title"] = title
        candidate["titleCustomized"] = True
        after = {"title": candidate.get("title"), "titleCustomized": True}
        record_timeline_edit(job, target="candidate", candidate_index=int(candidate["index"]), before=before, after=after)
        job["updatedAt"] = now_iso()
        save_job(job)
    append_message(job_id, "user", text, kind="revision")
    append_message(job_id, "assistant", f"已将第 {human_index} 条候选命名为“{title}”。", kind="revision")
    with jobs_lock:
        return public_job(jobs[job_id])


def rename_manual_selection_from_chat(job_id: str, text: str, title: str, *, append_messages: bool = True) -> dict[str, Any]:
    with jobs_lock:
        job = jobs[job_id]
        selection = job.get("manualSelection")
        if not selection:
            raise HTTPException(400, "请先在时间轴波形上拖动选择一个范围")
        before = dict(selection)
        selection["title"] = title
        record_timeline_edit(job, target="selection", before=before, after=dict(selection))
        job["updatedAt"] = now_iso()
        save_job(job)
    if append_messages:
        append_message(job_id, "user", text, kind="revision")
        append_message(job_id, "assistant", f"已将当前时间轴选区命名为“{title}”。", kind="revision")
    with jobs_lock:
        return public_job(jobs[job_id])


def apply_candidate_chat_adjustment(job_id: str, text: str, edit: dict[str, Any]) -> dict[str, Any]:
    human_index = int(edit["index"])
    with jobs_lock:
        job = jobs[job_id]
        candidates = job.get("candidates", [])
        if human_index < 1 or human_index > len(candidates):
            raise HTTPException(400, f"当前只有 {len(candidates)} 条候选")
        candidate = candidates[human_index - 1]
        start = float(candidate["start"])
        end = float(candidate["end"])
        candidate_index = int(candidate["index"])
    seconds = float(edit["seconds"])
    if seconds <= 0:
        raise HTTPException(400, "调整秒数必须大于 0")
    if edit["kind"] == "duration":
        end = start + seconds
    elif edit["kind"] == "relative":
        end += float(edit["direction"]) * seconds
    elif edit["boundary"] == "start":
        start += float(edit["direction"]) * seconds
    else:
        end += float(edit["direction"]) * seconds
    result = adjust_job_candidate(job_id, candidate_index, AdjustCandidateRequest(start=start, end=end))
    adjusted = result["candidate"]
    append_message(job_id, "user", text, kind="revision")
    append_message(
        job_id,
        "assistant",
        f"已调整第 {human_index} 条候选：{float(adjusted['start']):.1f} 秒到 {float(adjusted['end']):.1f} 秒，当前时长 {float(adjusted['duration']):.1f} 秒。确认生成时会使用这个新范围。",
        kind="revision",
    )
    with jobs_lock:
        return public_job(jobs[job_id])


def parse_manual_selection_adjustment(text: str) -> dict[str, Any] | None:
    selection = r"(?:时间轴)?(?:选中(?:的)?(?:片段|区间)?|选区|这段)"
    number = r"(\d+(?:\.\d+)?)\s*(?:秒|s)"
    both = re.search(selection + r".*?前后各(?:增加|延长|扩展)\s*" + number, text, flags=re.IGNORECASE)
    if both:
        return {"kind": "both", "seconds": float(both.group(1))}
    expand = re.search(selection + r".*?(?:扩大|扩展)\s*" + number, text, flags=re.IGNORECASE)
    if expand:
        return {"kind": "expand_total", "seconds": float(expand.group(1))}
    relative = re.search(selection + r".*?(增加|延长|加长|缩短|减少)\s*" + number, text, flags=re.IGNORECASE)
    if relative:
        return {
            "kind": "relative",
            "direction": -1 if relative.group(1) in ("缩短", "减少") else 1,
            "seconds": float(relative.group(2)),
        }
    return None


def parse_absolute_time_range(text: str) -> dict[str, float] | None:
    """Parse an absolute source-video range from a chat command."""
    token = r"(?:\d{1,3}:\d{1,2}(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?:秒|s)?"
    match = re.search(
        rf"(?:从|由|在)?\s*({token})\s*(?:到|至|[-~～—–])\s*({token})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    def seconds(value: str) -> float:
        value = re.sub(r"\s*(?:秒|s)\s*$", "", value, flags=re.IGNORECASE).strip()
        if ":" in value:
            minutes, remainder = value.split(":", 1)
            return float(minutes) * 60.0 + float(remainder)
        return float(value)

    start = seconds(match.group(1))
    end = seconds(match.group(2))
    if not math.isfinite(start) or not math.isfinite(end):
        raise HTTPException(400, "片段时间必须是有效数字")
    if end <= start:
        raise HTTPException(400, "片段结束时间必须晚于开始时间")
    return {"start": start, "end": end}


def apply_manual_selection_chat_adjustment(job_id: str, text: str, edit: dict[str, Any]) -> dict[str, Any]:
    with jobs_lock:
        selection = dict(jobs[job_id].get("manualSelection") or {})
    if not selection:
        raise HTTPException(400, "请先在时间轴波形上拖动选择一个范围")
    start = float(selection["start"])
    end = float(selection["end"])
    seconds = float(edit["seconds"])
    if edit["kind"] == "both":
        start -= seconds
        end += seconds
    elif edit["kind"] == "expand_total":
        start -= seconds / 2
        end += seconds / 2
    else:
        end += float(edit["direction"]) * seconds
    result = set_job_timeline_selection(job_id, TimelineSelectionRequest(start=start, end=end))
    adjusted = result["selection"]
    append_message(job_id, "user", text, kind="revision")
    append_message(
        job_id,
        "assistant",
        f"已调整时间轴选区：{adjusted['start']:.1f} 秒到 {adjusted['end']:.1f} 秒，当前时长 {adjusted['duration']:.1f} 秒。",
        kind="revision",
    )
    with jobs_lock:
        return public_job(jobs[job_id])


def add_manual_selection_candidate(job_id: str, text: str) -> tuple[dict[str, Any], int]:
    with jobs_lock:
        job = jobs[job_id]
        selection = dict(job.get("manualSelection") or {})
        if not selection:
            raise HTTPException(400, "请先在时间轴波形上拖动选择一个范围")
        candidates = job.setdefault("candidates", [])
        existing_position = next((
            position for position, item in enumerate(candidates)
            if item.get("manual")
            and abs(float(item["start"]) - float(selection["start"])) < 0.05
            and abs(float(item["end"]) - float(selection["end"])) < 0.05
        ), None)
        if existing_position is None:
            candidate_index = len(candidates)
            custom_title = parse_requested_title(text) or str(selection.get("title") or "").strip()
            candidates.append({
                "index": candidate_index,
                "start": float(selection["start"]),
                "end": float(selection["end"]),
                "duration": float(selection["duration"]),
                "score": 100.0,
                "title": custom_title[:80] if custom_title else "时间轴手动选择片段",
                "reason": "该范围由用户在审核时间轴上手动选择。",
                "evidence": ["用户手动指定起止边界，未使用模型推断。"],
                "manual": True,
                "titleCustomized": bool(custom_title),
            })
            recommended = [
                int(index) for index in job.setdefault("recommendedIndices", [])
                if 0 <= int(index) < candidate_index
                and not (
                    max(float(candidates[int(index)]["start"]), float(selection["start"]))
                    < min(float(candidates[int(index)]["end"]), float(selection["end"]))
                )
            ]
            if candidate_index not in recommended:
                recommended.append(candidate_index)
            job["recommendedIndices"] = recommended
            job["recommendedCount"] = len(recommended)
            job["detail"] = f"已有 {len(candidates)} 个候选，包含 1 个手动选区"
            job["updatedAt"] = now_iso()
            save_job(job)
            position = candidate_index
        else:
            position = existing_position
            custom_title = parse_requested_title(text)
            if custom_title:
                candidates[position]["title"] = custom_title
                candidates[position]["titleCustomized"] = True
                job["updatedAt"] = now_iso()
                save_job(job)
    append_message(job_id, "user", text, kind="revision")
    append_message(
        job_id,
        "assistant",
        f"已把时间轴选区加入为第 {position + 1} 条候选。可以继续调整，也可以确认生成。",
        kind="revision",
    )
    with jobs_lock:
        return public_job(jobs[job_id]), position


def resolve_candidate_position(text: str, candidates: list[dict[str, Any]]) -> int | None:
    numbered = re.search(r"第\s*([一二两三四五六七八\d]+)\s*条", text)
    if numbered:
        position = parsed_index(numbered.group(1)) - 1
        return position if 0 <= position < len(candidates) else None
    matches = [
        (len(str(item.get("title", ""))), position)
        for position, item in enumerate(candidates)
        if str(item.get("title", "")).strip() and str(item["title"]).strip() in text
    ]
    return max(matches)[1] if matches else None


def resolve_candidate_reference(fragment: str, candidates: list[dict[str, Any]]) -> int | None:
    numbered = re.search(r"(?:第\s*)?([一二两三四五六七八\d]+)\s*条", fragment)
    if numbered:
        position = parsed_index(numbered.group(1)) - 1
        return position if 0 <= position < len(candidates) else None
    return resolve_candidate_position(fragment, candidates)


def parse_named_candidate_adjustment(text: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    position = resolve_candidate_position(text, candidates)
    if position is None or re.search(r"第\s*[一二两三四五六七八\d]+\s*条", text):
        return None
    number = r"(\d+(?:\.\d+)?)\s*(?:秒|s)"
    boundary = re.search(r"(开头|开始|结尾|结束).*?(提前|延后|往前|往后)\s*" + number, text, flags=re.IGNORECASE)
    if boundary:
        return {
            "index": position + 1, "kind": "boundary",
            "boundary": "start" if boundary.group(1) in ("开头", "开始") else "end",
            "direction": -1 if boundary.group(2) in ("提前", "往前") else 1,
            "seconds": float(boundary.group(3)),
        }
    duration = re.search(r"(?:改成|调整为|设为)\s*" + number, text, flags=re.IGNORECASE)
    if duration:
        return {"index": position + 1, "kind": "duration", "seconds": float(duration.group(1))}
    relative = re.search(r"(增加|延长|加长|缩短|减少)\s*" + number, text, flags=re.IGNORECASE)
    if relative:
        return {
            "index": position + 1, "kind": "relative",
            "direction": -1 if relative.group(1) in ("缩短", "减少") else 1,
            "seconds": float(relative.group(2)),
        }
    return None


def normalize_candidate_indices(job: dict[str, Any], recommended_items: list[dict[str, Any]]) -> None:
    candidates = job.get("candidates", [])
    recommended_ids = {id(item) for item in recommended_items}
    for position, item in enumerate(candidates):
        item["index"] = position
    job["recommendedIndices"] = [position for position, item in enumerate(candidates) if id(item) in recommended_ids]
    job["recommendedCount"] = len(job["recommendedIndices"])
    job["detail"] = f"当前共有 {len(candidates)} 个候选"
    job["updatedAt"] = now_iso()


def apply_candidate_collection_command(job_id: str, text: str) -> dict[str, Any] | None:
    with jobs_lock:
        job = jobs[job_id]
        candidates = job.get("candidates", [])
        before_snapshot = {
            "candidates": copy.deepcopy(candidates),
            "recommendedIndices": list(job.get("recommendedIndices", [])),
        }
        recommended = [candidates[index] for index in job.get("recommendedIndices", []) if 0 <= index < len(candidates)]
        position = resolve_candidate_position(text, candidates)
        action = ""
        if re.search(r"(?:删除|移除|去掉|不要).*?(?:第|候选)|(?:删除|移除|去掉).*", text):
            if position is None:
                return None
            removed = candidates.pop(position)
            recommended = [item for item in recommended if item is not removed]
            action = f"已删除候选“{removed['title']}”"
        elif re.search(r"(?:复制|拷贝).*", text):
            if position is None:
                return None
            source = candidates[position]
            duplicate = {**source, "title": f"{source['title']}（副本）", "manual": True, "score": float(source.get("score", 0))}
            duplicate.pop("boundaryHistory", None)
            candidates.insert(position + 1, duplicate)
            action = f"已复制“{source['title']}”，副本默认不勾选，可调整后再生成"
        elif re.search(r"(?:拆分|拆成|分成).*(?:两段|2段)|(?:第.*条).*?(?:拆分|拆成|分成)", text):
            if position is None:
                return None
            source = candidates[position]
            split_match = re.search(r"(?:在|从)\s*(\d+(?:\.\d+)?)\s*(?:秒|s)(?:处)?(?:拆分|切开)", text, flags=re.IGNORECASE)
            split = float(split_match.group(1)) if split_match else (float(source["start"]) + float(source["end"])) / 2
            if split <= float(source["start"]) + 1 or split >= float(source["end"]) - 1:
                raise HTTPException(400, "拆分点必须距离候选两端至少 1 秒")
            first = {**source, "end": round(split, 3), "duration": round(split - float(source["start"]), 3), "title": f"{source['title']}（上）", "manual": True}
            second = {**source, "start": round(split, 3), "duration": round(float(source["end"]) - split, 3), "title": f"{source['title']}（下）", "manual": True}
            candidates[position:position + 1] = [first, second]
            recommended = [item for item in recommended if item is not source]
            recommended.extend([first, second])
            action = f"已将“{source['title']}”拆分为两段"
        else:
            merge = re.search(r"合并\s*(.+?)\s*(?:和|与|、)\s*(.+?)(?=\s*(?:命名为|取名为|改名为|，|,|。|$))", text)
            if merge:
                left_position = resolve_candidate_reference(merge.group(1), candidates)
                right_position = resolve_candidate_reference(merge.group(2), candidates)
                if left_position is None or right_position is None or left_position == right_position:
                    raise HTTPException(400, "要合并的候选编号无效")
                left, right = candidates[left_position], candidates[right_position]
                start, end = min(float(left["start"]), float(right["start"])), max(float(left["end"]), float(right["end"]))
                if end - start > 180:
                    raise HTTPException(400, "合并后的候选不能超过 180 秒")
                merged = {
                    **left, "start": start, "end": end, "duration": round(end - start, 3),
                    "title": parse_requested_title(text) or f"{left['title']} + {right['title']}",
                    "reason": "由用户手动合并两个候选区间。", "manual": True,
                }
                for removal in sorted((left_position, right_position), reverse=True):
                    candidates.pop(removal)
                candidates.insert(min(left_position, right_position), merged)
                recommended = [item for item in recommended if item is not left and item is not right] + [merged]
                action = f"已合并第 {left_position + 1} 条和第 {right_position + 1} 条"
            else:
                reorder = re.search(r"把?\s*(.+?)\s*(?:移到|移动到)\s*(.+?)(?:的位置)?\s*$", text)
                if not reorder:
                    return None
                source_position = resolve_candidate_reference(reorder.group(1), candidates)
                target_position = resolve_candidate_reference(reorder.group(2), candidates)
                if source_position is None or target_position is None:
                    raise HTTPException(400, "移动的候选编号无效")
                item = candidates.pop(source_position)
                candidates.insert(target_position, item)
                action = f"已将候选移动到第 {target_position + 1} 条"
        normalize_candidate_indices(job, recommended)
        after_snapshot = {
            "candidates": copy.deepcopy(candidates),
            "recommendedIndices": list(job.get("recommendedIndices", [])),
        }
        record_timeline_edit(job, target="candidates", before=before_snapshot, after=after_snapshot)
        save_job(job)
    append_message(job_id, "user", text, kind="revision")
    append_message(job_id, "assistant", f"{action}。", kind="revision")
    with jobs_lock:
        return public_job(jobs[job_id])


def resolve_event_group_reference(text: str, groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    numbered = re.search(r"第\s*([一二两三四五六七八\d]+)\s*(?:条|个)(?:事件|高光)?", text)
    if numbered:
        position = parsed_index(numbered.group(1)) - 1
        return groups[position] if 0 <= position < len(groups) else None
    matches = [group for group in groups if str(group.get("title", "")).strip() and str(group["title"]).strip() in text]
    return max(matches, key=lambda item: len(str(item.get("title", "")))) if matches else None


def apply_event_total_budget(job_id: str, text: str, seconds: float) -> dict[str, Any]:
    if seconds < 4 or seconds > 86400:
        raise HTTPException(400, "单条成片目标时长必须大于等于 4 秒")
    with jobs_lock:
        job = jobs[job_id]
        before = event_groups_snapshot(job)
        request_count = job.get("request", {}).get("count", "auto")
        requested_count = None if str(request_count).lower() == "auto" else int(request_count)
        groups, recommended_ids = allocate_event_group_budget(
            job.get("eventGroups", []), total_target_seconds=seconds, requested_count=requested_count,
        )
        job["eventGroups"] = groups
        job["recommendedGroupIds"] = recommended_ids
        job["totalTargetSeconds"] = seconds
        job["durationUpperLimit"] = round(seconds + max(5.0, seconds * .15), 3)
        job["eventReductionReason"] = next((
            str(group.get("eventReductionReason"))
            for group in groups
            if group.get("id") in recommended_ids and group.get("eventReductionReason")
        ), "")
        job.setdefault("request", {})["totalTargetSeconds"] = seconds
        finish_event_group_edit(job, before)
        actual = float(job.get("allocatedTotalSeconds") or 0)
    append_message(job_id, "user", text, kind="revision")
    append_message(job_id, "assistant", f"已按单条成片目标 {seconds:.1f} 秒重新分配事件时长，当前预计 {actual:.1f} 秒；优先保留核心镜头并补充同一事件的必要上下文。", kind="revision")
    with jobs_lock:
        return public_job(jobs[job_id])


@app.post("/api/jobs/{job_id}/messages")
def chat_with_job(job_id: str, request: ChatRequest) -> dict[str, Any]:
    text = request.text.strip()
    if not text or len(text) > 500:
        raise HTTPException(400, "修改要求必须为 1–500 字")
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        status = job["status"]
    if status in ("queued", "running", "cancelling"):
        append_message(job_id, "user", text, kind="message")
        append_message(job_id, "assistant", "当前视觉分析仍在后台运行，这条消息不会打断任务；完成后即可继续修改具体片段。", kind="notice")
        with jobs_lock:
            return {"action": "message", "job": public_job(jobs[job_id])}
    if status == "awaiting_confirmation":
        with jobs_lock:
            event_groups = jobs[job_id].get("eventGroups", [])
        if event_groups:
            selection_words = r"(?:时间轴)?(?:选中(?:的)?(?:\s*[一二两三四五六七八九十\d]+\s*个)?(?:片段|区间)?|选区|这段)"
            time_range = parse_absolute_time_range(text)
            direct_selection = re.search(
                rf"(?:生成|裁剪|导出|合成).*?{selection_words}|{selection_words}.*?(?:生成|裁剪|导出|合成)",
                text,
            )
            if direct_selection or time_range:
                with jobs_lock:
                    saved_selection = dict(jobs[job_id].get("manualSelection") or {})
                selections = [item for item in (request.selections or []) if isinstance(item, dict)]
                if not selections and time_range:
                    selection = set_job_timeline_selection(job_id, TimelineSelectionRequest(**time_range))["selection"]
                    selections = [selection]
                elif not selections and saved_selection:
                    selections = [saved_selection]
                if not selections:
                    raise HTTPException(400, "请先在源视频时间轴上拖动选择一个范围")
                normalized_ranges = [(round(float(item.get("start", 0)), 3), round(float(item.get("end", 0)), 3)) for item in selections]
                with jobs_lock:
                    existing_manual = next((group for group in reversed(jobs[job_id].get("eventGroups", []))
                                             if group.get("assemblyStrategy") == "manual"
                                             and [(round(float(segment.get("start", 0)), 3), round(float(segment.get("end", 0)), 3)) for segment in group.get("segments", [])] == normalized_ranges), None)
                if existing_manual:
                    with jobs_lock:
                        jobs[job_id]["pendingSelectionGroupIds"] = [str(existing_manual["id"])]
                        save_job(jobs[job_id])
                    append_message(job_id, "user", text, kind="confirmation")
                    append_message(job_id, "assistant", "已找到相同的时间轴选区，不再重复创建事件。请在确认卡中调整顺序或开始合成。", kind="notice")
                    with jobs_lock:
                        return {"action": "selection-ready-event", "groupIds": [str(existing_manual["id"])], "job": public_job(jobs[job_id])}
                created = create_event_group(
                    job_id,
                    CreateEventGroupRequest(
                        start=float(selections[0]["start"]),
                        end=float(selections[0]["end"]),
                        title=str(selections[0].get("title") or "时间轴选区高光"),
                    ),
                )
                for selection in selections[1:]:
                    add_event_group_segment(
                        job_id,
                        str(created["groupId"]),
                        AddEventSegmentRequest(
                            start=float(selection["start"]),
                            end=float(selection["end"]),
                            role=str(selection.get("title") or "时间轴选区镜头"),
                        ),
                    )
                append_message(job_id, "user", text, kind="confirmation")
                append_message(job_id, "assistant", "已准备好你选中的多个时间轴片段。请在时间轴确认镜头顺序后进入生成阶段。", kind="notice")
                with jobs_lock:
                    return {"action": "selection-ready-event", "groupIds": [str(created["groupId"])], "job": public_job(jobs[job_id])}
            total_match = re.search(r"(?:整批|总时长|(?:单条)?成片(?:总|目标)?时长).*?(\d+(?:\.\d+)?)\s*(?:秒|s)|(?:改成|调整为|设为)\s*(\d+(?:\.\d+)?)\s*(?:秒|s).*?(?:高光|成片)", text, flags=re.IGNORECASE)
            if total_match:
                return {"action": "event-budget-adjusted", "job": apply_event_total_budget(job_id, text, float(total_match.group(1) or total_match.group(2)))}
            group = resolve_event_group_reference(text, event_groups)
            requested_title = parse_requested_title(text)
            if group and requested_title and re.search(r"(?:命名为|取名为|改名为|叫做|名称为)", text):
                response = rename_event_group(job_id, str(group["id"]), RenameEventGroupRequest(title=requested_title))
                append_message(job_id, "user", text, kind="revision")
                append_message(job_id, "assistant", f"已将事件高光命名为“{requested_title}”。", kind="revision")
                with jobs_lock:
                    return {"action": "event-renamed", "job": public_job(jobs[job_id])}
            segment_match = re.search(r"第\s*([一二两三四五六七八\d]+)\s*(?:个)?镜头", text)
            if group and segment_match and re.search(r"(?:删除|移除|去掉|不要)", text):
                position = parsed_index(segment_match.group(1)) - 1
                segments = group.get("segments", [])
                if position < 0 or position >= len(segments):
                    raise HTTPException(400, f"该事件当前只有 {len(segments)} 个镜头")
                delete_event_group_segment(job_id, str(group["id"]), str(segments[position]["id"]))
                append_message(job_id, "user", text, kind="revision")
                append_message(job_id, "assistant", f"已删除“{group['title']}”的第 {position + 1} 个镜头。", kind="revision")
                with jobs_lock:
                    return {"action": "event-segment-deleted", "job": public_job(jobs[job_id])}
            if group and re.search(selection_words, text) and re.search(r"(?:加入|添加|放入)", text):
                with jobs_lock:
                    selection = dict(jobs[job_id].get("manualSelection") or {})
                if not selection:
                    raise HTTPException(400, "请先在源视频时间轴上拖动选择一个范围")
                add_event_group_segment(
                    job_id, str(group["id"]),
                    AddEventSegmentRequest(start=float(selection["start"]), end=float(selection["end"]), role="用户补充镜头"),
                )
                append_message(job_id, "user", text, kind="revision")
                append_message(job_id, "assistant", f"已把当前选区加入“{group['title']}”。", kind="revision")
                with jobs_lock:
                    return {"action": "event-segment-added", "job": public_job(jobs[job_id])}
            append_message(job_id, "user", text, kind="message")
            append_message(job_id, "assistant", "可以说“单条成片目标改成 60 秒”“删除救援事件第 2 个镜头”，或先在时间轴框选，再说“把选区加入救援事件”。", kind="guidance")
            with jobs_lock:
                return {"action": "guidance", "job": public_job(jobs[job_id])}
        requested_title = parse_requested_title(text)
        candidate_name = re.search(r"第\s*([一二两三四五六七八\d]+)\s*条.*?(?:命名为|取名为|改名为|叫做|名称为)", text)
        if requested_title and candidate_name:
            human_index = parsed_index(candidate_name.group(1))
            return {
                "action": "candidate-renamed",
                "job": rename_candidate_from_chat(job_id, text, human_index, requested_title),
            }
        if requested_title and re.search(r"(?:命名为|取名为|改名为|叫做|名称为)", text):
            original_reference = re.split(r"(?:命名为|取名为|改名为|叫做|名称为)", text, maxsplit=1)[0]
            with jobs_lock:
                named_position = resolve_candidate_position(original_reference, jobs[job_id].get("candidates", []))
            if named_position is not None:
                return {
                    "action": "candidate-renamed",
                    "job": rename_candidate_from_chat(job_id, text, named_position + 1, requested_title),
                }
        manual_edit = parse_manual_selection_adjustment(text)
        if manual_edit:
            return {
                "action": "selection-adjusted",
                "job": apply_manual_selection_chat_adjustment(job_id, text, manual_edit),
            }
        selection_words = r"(?:时间轴)?(?:选中(?:的)?(?:\s*[一二两三四五六七八九十\d]+\s*个)?(?:片段|区间)?|选区|这段)"
        time_range = parse_absolute_time_range(text)
        direct_selection = re.search(
            rf"(?:生成|裁剪|导出).*?{selection_words}|{selection_words}.*?(?:生成|裁剪|导出)",
            text,
        )
        add_selection = re.search(
            rf"(?:加入|添加|设为|作为).*?{selection_words}.*?候选|{selection_words}.*?(?:加入|添加|设为|作为).*?候选",
            text,
        )
        if direct_selection or time_range:
            if time_range:
                set_job_timeline_selection(job_id, TimelineSelectionRequest(**time_range))
            updated, position = add_manual_selection_candidate(job_id, text)
            append_message(job_id, "user", text, kind="confirmation")
            append_message(job_id, "assistant", "已准备好这个时间轴选区。请在时间轴确认镜头顺序后进入生成阶段。", kind="notice")
            return {"action": "selection-ready", "position": position, "job": updated}
        if add_selection:
            updated, _ = add_manual_selection_candidate(job_id, text)
            return {"action": "selection-added", "job": updated}
        if requested_title and re.search(selection_words, text):
            return {
                "action": "selection-renamed",
                "job": rename_manual_selection_from_chat(job_id, text, requested_title),
            }
        collection_update = apply_candidate_collection_command(job_id, text)
        if collection_update is not None:
            return {"action": "candidates-updated", "job": collection_update}
        candidate_edit = parse_candidate_adjustment(text)
        if not candidate_edit:
            with jobs_lock:
                candidate_edit = parse_named_candidate_adjustment(text, jobs[job_id].get("candidates", []))
        if candidate_edit:
            return {
                "action": "candidate-adjusted",
                "job": apply_candidate_chat_adjustment(job_id, text, candidate_edit),
            }
        append_message(job_id, "user", text, kind="message")
        append_message(
            job_id,
            "assistant",
            "候选已经准备好。可以调整时长、拖动时间轴，也可以说“把选中片段命名为调查开场”或“第 5 条改名为药房证据”。",
            kind="guidance",
        )
        with jobs_lock:
            return {"action": "guidance", "job": public_job(jobs[job_id])}
    if status != "completed":
        raise HTTPException(409, "当前任务未完成，请重新生成后再继续修改")

    # A completed job can still accept a fresh source-range selection. Reopen
    # the reusable candidate pool internally, then route the command through
    # the same confirmation/render path used during review.
    completed_time_range = parse_absolute_time_range(text)
    manual_command = bool(request.selections) or bool(
        re.search(r"(?:时间轴)?(?:选中(?:的)?(?:片段|区间)?|选区|这段).*?(?:生成|裁剪|导出|合成)|(?:生成|裁剪|导出|合成).*?(?:时间轴)?(?:选中(?:的)?(?:片段|区间)?|选区|这段)", text)
    )
    if completed_time_range or manual_command:
        if completed_time_range:
            set_job_timeline_selection(job_id, TimelineSelectionRequest(**completed_time_range))
        reopen_job_for_editing(job_id)
        return chat_with_job(job_id, request)

    boundary = re.search(
        r"第\s*([一二两三四五六七八\d]+)\s*条.*?(开头|开始|结尾|结束).*?(提前|延后|往前|往后)\s*(\d+(?:\.\d+)?)\s*秒",
        text,
    )
    if boundary:
        index = parsed_index(boundary.group(1))
        with jobs_lock:
            outputs = jobs[job_id].get("outputs", [])
            if index < 1 or index > len(outputs):
                raise HTTPException(400, f"当前只有 {len(outputs)} 条高光")
            filename = outputs[index - 1]["filename"]
        seconds = float(boundary.group(4))
        direction = -seconds if boundary.group(3) in ("提前", "往前") else seconds
        adjustment = AdjustOutputRequest(
            startDelta=direction if boundary.group(2) in ("开头", "开始") else 0,
            endDelta=direction if boundary.group(2) in ("结尾", "结束") else 0,
        )
        updated = adjust_output(job_id, filename, adjustment, user_text=text)
        return {"action": "adjusted", "job": public_job(updated)}

    replace = re.search(r"(?:换掉|替换|不要|换一个).*?第\s*([一二两三四五六七八\d]+)\s*条|第\s*([一二两三四五六七八\d]+)\s*条.*?(?:换掉|替换|不要|换一个)", text)
    if replace:
        index = parsed_index(replace.group(1) or replace.group(2))
        with jobs_lock:
            outputs = jobs[job_id].get("outputs", [])
            if index < 1 or index > len(outputs):
                raise HTTPException(400, f"当前只有 {len(outputs)} 条高光")
        derived = create_derived_job(job_id, DeriveJobRequest(
            count=1,
            targetSeconds=None if str(job["request"].get("targetSeconds")).lower() == "auto" else float(job["request"]["targetSeconds"]),
            theme=str(job["request"].get("theme", "")),
            excludeExisting=True,
            message=text,
        ))
        return {"action": "derived", "job": public_job(derived)}

    rerun = re.search(r"(?:再生成|再来|重新生成|重新分析|更偏|偏向|改成)", text)
    if rerun:
        count_match = re.search(r"([1-8一二两三四五六七八])\s*条", text)
        duration_match = re.search(r"(\d+(?:\.\d+)?)\s*秒", text)
        requested_count = job["request"].get("count")
        requested_target = job["request"].get("targetSeconds")
        fallback_count = len(job.get("outputs", [])) or int(job.get("recommendedCount") or 3)
        durations = [float(item["duration"]) for item in job.get("outputs", []) if item.get("duration")]
        fallback_target = sum(durations) if durations else 60.0
        count = parsed_index(count_match.group(1)) if count_match else (
            int(requested_count) if str(requested_count).lower() != "auto" else fallback_count
        )
        target = float(duration_match.group(1)) if duration_match else (
            float(requested_target) if str(requested_target).lower() != "auto" else fallback_target
        )
        derived = create_derived_job(job_id, DeriveJobRequest(
            count=count,
            targetSeconds=target,
            theme=text,
            excludeExisting=bool(re.search(r"不重复|不要使用|换|再生成|再来", text)),
            message=text,
        ))
        return {"action": "derived", "job": public_job(derived)}

    append_message(job_id, "user", text, kind="message")
    append_message(
        job_id,
        "assistant",
        "我可以执行例如“第 1 条开头提前 2 秒”“换掉第 2 条”或“再生成 3 条，更偏人物反应且不要重复”。",
        kind="guidance",
    )
    with jobs_lock:
        return {"action": "guidance", "job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/analysis-decision", status_code=202)
def resolve_analysis_decision(job_id: str, request: AnalysisDecisionRequest) -> dict[str, Any]:
    action = request.action.strip().lower()
    if action not in {"retry", "fallback", "cancel"}:
        raise HTTPException(400, "处理方式必须是 retry、fallback 或 cancel")
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        interrupted = job.get("status") == "failed" and job.get("stage") == "interrupted"
        if interrupted:
            if action != "retry":
                raise HTTPException(409, "服务中断任务只能选择 retry 恢复")
            checkpoint = load_analysis_checkpoint(Path(job["workDirectory"]))
            job.update({
                "status": "running", "stage": "starting", "progress": max(.01, float(job.get("progress") or 0)),
                "stageProgress": 0.0, "stageCompleted": None, "stageTotal": None, "stageUnit": "",
                "stageCompletedSeconds": None, "stageTotalSeconds": None,
                "detail": "正在从已保存的媒体与语音缓存恢复分析",
                "currentAction": "正在从检查点恢复分析", "model": "系统",
                "etaSeconds": None, "etaMode": "collecting", "progressMode": "indeterminate",
                "stageStartedAt": now_iso(), "lastProgressAt": now_iso(),
                "stageObservedIndex": None, "stageUnitStartedAt": None,
                "stageAverageSeconds": None, "stageSampleCount": 0, "error": None,
                "pendingDecision": None, "resumeAvailable": False, "updatedAt": now_iso(),
            })
            cancel_events[job_id] = threading.Event()
            save_job(job)
            submit_analysis_task(job_id, run_job, job_id)
            append_text = "已从服务中断处恢复任务。" if checkpoint else "未找到阶段检查点，已使用原素材重新启动分析。"
            # Continue below to append a durable message and return the refreshed job.
        elif job.get("status") != "awaiting_model_decision" or not job.get("pendingDecision"):
            raise HTTPException(409, "当前任务没有等待处理的模型阶段")
        if interrupted:
            pass
        elif action == "cancel":
            stage_label = str(job["pendingDecision"].get("stageLabel") or "模型阶段")
            job.update({
                "status": "cancelled", "stage": "cancelled", "detail": "任务已取消",
                "currentAction": "任务已取消", "etaSeconds": None,
                "etaMode": "stopped", "progressMode": "stopped",
                "pendingDecision": None, "updatedAt": now_iso(),
            })
            save_job(job)
            append_text = f"已取消任务；{stage_label}之前的检查点会随任务保留，删除任务时一并清理。"
        else:
            decision_stage = str(job["pendingDecision"].get("stage") or "starting")
            stage_label = str(job["pendingDecision"].get("stageLabel") or "模型阶段")
            visual_fallback = action == "fallback" and decision_stage == "speech_analysis"
            running_text = (
                "正在跳过语音辅助并继续视觉分析"
                if visual_fallback
                else f"正在{'重试' if action == 'retry' else '降级继续'}{stage_label}"
            )
            job.update({
                "status": "running", "stage": decision_stage,
                "detail": running_text,
                "currentAction": running_text,
                "etaSeconds": None, "etaMode": "collecting", "progressMode": "indeterminate",
                "stageProgress": 0.0, "stageCompleted": None, "stageTotal": None, "stageUnit": "",
                "stageObservedIndex": None, "stageUnitStartedAt": None,
                "stageAverageSeconds": None, "stageSampleCount": 0,
                "error": None, "pendingDecision": None, "updatedAt": now_iso(),
            })
            cancel_events[job_id] = threading.Event()
            save_job(job)
            append_text = (
                "已跳过语音辅助，正在继续使用视觉模型分析高光。"
                if visual_fallback
                else f"已选择{'重试当前阶段' if action == 'retry' else '按降级规则继续'}：{stage_label}。"
            )
            submit_analysis_task(job_id, run_job, job_id, action)
    append_message(job_id, "user", append_text, kind="decision")
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/reanalyze", status_code=202)
def reanalyze_cancelled_job(job_id: str) -> dict[str, Any]:
    """Restart a cancelled/failed analysis using the existing upload and brief."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") not in {"cancelled", "failed"}:
            raise HTTPException(409, "只有已取消或失败的任务可以重新分析")
        job.update({
            "status": "queued", "stage": "queued", "progress": 0.0,
            "stageProgress": 0.0, "stageCompleted": None, "stageTotal": None, "stageUnit": "",
            "stageCompletedSeconds": None, "stageTotalSeconds": None,
            "detail": "已重新提交分析，准备读取素材", "currentAction": "任务已重新进入队列",
            "model": "系统", "etaSeconds": None, "etaMode": "collecting",
            "progressMode": "indeterminate", "stageStartedAt": now_iso(), "lastProgressAt": now_iso(),
            "stageObservedIndex": None, "stageUnitStartedAt": None,
            "stageAverageSeconds": None, "stageSampleCount": 0, "error": None,
            "pendingDecision": None, "resumeAvailable": False, "updatedAt": now_iso(),
            "candidates": [], "eventGroups": [], "autoPlans": [],
            "recommendedGroupIds": [], "recommendedIndices": [],
        })
        cancel_events[job_id] = threading.Event()
        save_job(job)
    append_message(job_id, "user", "重新分析当前视频，沿用已确认的剪辑要求。", kind="retry")
    append_message(job_id, "assistant", "已重新提交分析，会复用源视频、波形和播放代理，不需要重新上传。", kind="notice")
    submit_analysis_task(job_id, run_job, job_id, "retry")
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.post("/api/jobs/{job_id}/messages/stream")
def stream_chat_with_job(job_id: str, request: ChatRequest) -> StreamingResponse:
    """Stream the durable assistant answer while keeping the existing command engine.

    Commands are still executed atomically by ``chat_with_job``. The response is
    streamed only after the resulting message is available, so incomplete text
    can never mutate a job or expose half-written JSON to the UI.
    """
    result = chat_with_job(job_id, request)
    job = result.get("job") if isinstance(result, dict) else None
    if not isinstance(job, dict):
        job = public_job(jobs[job_id])
    assistant_text = ""
    for message in reversed(job.get("messages") or []):
        if message.get("role") == "assistant":
            assistant_text = str(message.get("text") or "")
            break
    action = str(result.get("action") or "message") if isinstance(result, dict) else "message"

    def events():
        yield "event: started\ndata: {}\n\n"
        if assistant_text:
            for offset in range(0, len(assistant_text), 18):
                payload = json.dumps({"text": assistant_text[offset:offset + 18]}, ensure_ascii=False)
                yield f"event: delta\ndata: {payload}\n\n"
        final = json.dumps({"action": action, "job": job}, ensure_ascii=False)
        yield f"event: done\ndata: {final}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    client: Any = None
    immediate = False
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        cancellable = ("briefing", "brief_confirmation", "queued", "running", "cancelling", "awaiting_model_decision", "awaiting_confirmation")
        if job["status"] not in cancellable:
            return {"job": public_job(job)}
        original_status = str(job["status"])
        event = cancel_events.get(job_id)
        if event:
            event.set()
        future = analysis_futures.get(job_id)
        # Future.cancel() succeeds only before the worker starts. This is the
        # important difference between a real queue cancellation and merely
        # painting the job as "cancelling" in the UI.
        removed_from_queue = bool(future and future.cancel())
        client = active_ark_clients.get(job_id)
        immediate = (
            original_status in {"awaiting_model_decision", "awaiting_confirmation", "brief_confirmation"}
            or removed_from_queue
            # Recover stale/orphaned states defensively. A queued/cancelling
            # record with neither Future nor active client has no worker that
            # could ever advance it to a terminal state.
            or (original_status in {"queued", "briefing", "cancelling"} and future is None and client is None)
        )
        if not immediate:
            update_job(
                job_id, status="cancelling", stage="cancelling", detail="正在取消任务",
                currentAction="正在停止当前处理", etaSeconds=None,
                etaMode="stopped", progressMode="indeterminate",
            )
    # Closing a live HTTP transport can briefly block; do it outside the jobs
    # lock so status polling and unrelated tasks remain responsive.
    if client:
        client.cancel()
    if immediate:
        finalize_job_cancellation(job_id, message="任务已取消")
        with jobs_lock:
            cancel_events.pop(job_id, None)
            analysis_futures.pop(job_id, None)
    with jobs_lock:
        return {"job": public_job(jobs[job_id])}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, bool]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job["status"] in ("briefing", "queued", "running", "cancelling"):
            raise HTTPException(409, "请先取消正在运行的任务")
        jobs.pop(job_id, None)
    Path(job["sourcePath"]).unlink(missing_ok=True)
    shutil.rmtree(job["workDirectory"], ignore_errors=True)
    shutil.rmtree(job["outputDirectory"], ignore_errors=True)
    job_path(job_id).unlink(missing_ok=True)
    job_store.delete(job_id)
    cleanup_unreferenced_media_cache(job)
    return {"deleted": True}


@app.on_event("startup")
def startup_maintenance() -> None:
    # Interrupted proxy jobs leave non-playable temporary MP4s. They must not be
    # reported as active work after a restart; the selected source can request a
    # fresh proxy on demand.
    for temporary in (settings.data_root / "cache").glob("proxy-*.tmp.mp4"):
        temporary.unlink(missing_ok=True)
    cleanup_orphaned_media_cache()
    if settings.speech_engine == "sensevoice":
        threading.Thread(
            target=launch_sensevoice_worker,
            kwargs={
                "worker_directory": settings.data_root / "cache" / "speech-worker",
                "model_name": settings.sensevoice_model,
                "device": settings.sensevoice_device,
                "vad_model": settings.sensevoice_vad_model,
                "punc_model": settings.sensevoice_punc_model,
                "spk_model": settings.sensevoice_spk_model,
                "diarization": settings.sensevoice_diarization,
                "model_cache": settings.speech_model_cache,
            },
            name="sensevoice-worker-launcher",
            daemon=True,
        ).start()
    threading.Thread(target=restore_kept_library_copies, name="kept-library-repair", daemon=True).start()
    if settings.retention_days > 0:
        cutoff = time.time() - settings.retention_days * 86400
        expired: list[tuple[str, dict[str, Any]]] = []
        with jobs_lock:
            for job_id, job in list(jobs.items()):
                if job.get("status") in ("briefing", "queued", "running", "cancelling") or job.get("pinned"):
                    continue
                try:
                    timestamp = datetime.fromisoformat(str(job.get("updatedAt", ""))).timestamp()
                except ValueError:
                    continue
                if timestamp < cutoff:
                    expired.append((job_id, job))
                    jobs.pop(job_id, None)
        for job_id, job in expired:
            Path(job["sourcePath"]).unlink(missing_ok=True)
            shutil.rmtree(job["workDirectory"], ignore_errors=True)
            shutil.rmtree(job["outputDirectory"], ignore_errors=True)
            job_path(job_id).unlink(missing_ok=True)
            job_store.delete(job_id)
            cleanup_unreferenced_media_cache(job)

    # Only short, confirmed outputs are warmed at startup. Source-video proxies
    # and timeline assets are generated when that job is actually opened, so a
    # cancelled 75-minute upload cannot monopolize CPU after every restart.
    with jobs_lock:
        recent = sorted(
            (job for job in jobs.values() if job.get("status") == "completed" and job.get("outputs")),
            key=lambda item: str(item.get("updatedAt", "")),
            reverse=True,
        )[:3]
    for job in recent:
        for item in job.get("outputs", [])[:2]:
            output_preview_executor.submit(prepare_output_preview, job["id"], str(item["filename"]))


@app.get("/api/jobs/{job_id}/source")
def source_media(job_id: str) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        path = Path(job["sourcePath"])
    if not path.is_file():
        raise HTTPException(404, "源视频不存在")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=job["filename"], content_disposition_type="inline")


@app.get("/api/jobs/{job_id}/thumbnail")
def job_thumbnail(job_id: str) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        source = Path(job["sourcePath"])
        output = thumbnail_cache_path(job)
    if not source.is_file():
        raise HTTPException(404, "源视频不存在")
    try:
        extract_first_frame(source, output, ffmpeg=settings.ffmpeg)
    except Exception as error:
        raise HTTPException(404, f"首帧暂不可用：{str(error)[:160]}") from error
    return FileResponse(output, media_type="image/jpeg", filename=f"{job_id}-thumbnail.jpg", content_disposition_type="inline")


@app.get("/api/jobs/{job_id}/preview")
def preview_media(job_id: str) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        source = Path(job["sourcePath"])
        identity = str(job.get("sourceHash") or job_id)
    proxy = proxy_cache_path(identity)
    path = proxy if proxy.is_file() else source
    if not path.is_file():
        raise HTTPException(404, "审核视频不存在")
    return FileResponse(path, media_type="video/mp4" if proxy.is_file() else (mimetypes.guess_type(path.name)[0] or "application/octet-stream"), content_disposition_type="inline")


@app.get("/api/jobs/{job_id}/preview-status")
def preview_media_status(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        identity = str(job.get("sourceHash") or job_id)
    proxy = proxy_cache_path(identity)
    if not proxy.is_file():
        schedule_preview_proxy(job_id)
    with source_proxy_schedule_lock:
        preparing = identity in scheduled_source_proxies
        failure = source_proxy_failures.get(identity)
        error = failure[1] if failure and time.monotonic() - failure[0] < 60 else None
    return {"ready": proxy.is_file(), "preparing": preparing, "error": error}


@app.get("/api/jobs/{job_id}/browser-preview")
def browser_preview_media(job_id: str) -> FileResponse:
    try:
        path = prepare_browser_preview(job_id)
    except RuntimeError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(path, media_type="video/webm", content_disposition_type="inline")


def _subtitle_timestamp(seconds: float, *, vtt: bool = False) -> str:
    value = max(0.0, float(seconds))
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    whole = int(value % 60)
    millis = int(round((value - int(value)) * 1000))
    if millis >= 1000:
        whole += 1
        millis = 0
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{whole:02d}{separator}{millis:03d}"


def _subtitle_cues(job: dict[str, Any], output: dict[str, Any]) -> list[dict[str, Any]]:
    speech = job.get("speechAnalysis") or {}
    segments = speech.get("segments") if isinstance(speech, dict) else None
    # The public job keeps only the SenseVoice segment count to avoid sending
    # the full transcript to every polling response. The actual timestamped
    # segments are persisted in the work directory and must be loaded here for
    # both SRT export and burned-in subtitles.
    if not isinstance(segments, list) or not segments:
        transcript = job.get("transcript")
        if isinstance(transcript, dict):
            transcript = transcript.get("segments")
        if not isinstance(transcript, list) or not transcript:
            work_directory = str(job.get("workDirectory") or "").strip()
            transcript_path = Path(work_directory) / "transcript.json" if work_directory else None
            if transcript_path and transcript_path.is_file():
                try:
                    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
                    transcript = payload.get("segments") if isinstance(payload, dict) else []
                except (OSError, ValueError):
                    transcript = []
        segments = transcript if isinstance(transcript, list) else []
    cues: list[dict[str, Any]] = []
    offset = 0.0
    for source_segment in output.get("segments") or [output]:
        source_start = float(source_segment.get("start") or 0)
        source_end = float(source_segment.get("end") or source_start)
        for speech_segment in segments:
            text = str(speech_segment.get("text") or "").strip()
            start = max(source_start, float(speech_segment.get("start") or 0))
            end = min(source_end, float(speech_segment.get("end") or 0))
            if not text or end - start < .08:
                continue
            cue = {"start": offset + start - source_start, "end": offset + end - source_start, "text": text}
            if cues and cue["start"] <= cues[-1]["end"] + .03 and cue["text"] == cues[-1]["text"]:
                cues[-1]["end"] = max(cues[-1]["end"], cue["end"])
            else:
                cues.append(cue)
        offset += max(0.0, source_end - source_start)
    return cues


def _write_ass_subtitles(job: dict[str, Any], output: dict[str, Any], path: Path, subtitle_style: str = "clean") -> bool:
    cues = _subtitle_cues(job, output)
    if not cues:
        return False
    subtitle_style = normalize_subtitle_style(subtitle_style)
    ass_style = {
        "clean": {"font_size": 20, "primary": "&H00FFFFFF", "outline": 2, "margin_v": 38, "bold": 0},
        "bold": {"font_size": 24, "primary": "&H006DE6FF", "outline": 3, "margin_v": 48, "bold": -1},
        "social": {"font_size": 28, "primary": "&H00FFFFFF", "outline": 2, "margin_v": 72, "bold": -1},
    }[subtitle_style]
    def ass_time(value: float) -> str:
        value = max(0.0, float(value)); hours = int(value // 3600); minutes = int((value % 3600) // 60)
        seconds = int(value % 60); centiseconds = int(round((value - int(value)) * 100))
        if centiseconds >= 100: seconds += 1; centiseconds = 0
        return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
    def ass_text(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "",
        "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,WenQuanYi Zen Hei,{ass_style['font_size']},{ass_style['primary']},{ass_style['primary']},&H90000000,&H00000000,{ass_style['bold']},0,0,0,100,100,0,0,1,{ass_style['outline']},0,2,48,48,{ass_style['margin_v']},134",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines.extend(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},Default,,0,0,0,,{ass_text(cue['text'])}" for cue in cues)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return True


@app.get("/api/jobs/{job_id}/outputs/{filename}/subtitles")
def output_subtitles(job_id: str, filename: str, format: str = "srt") -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        context = output_download_context(job, filename)
        if not context:
            raise HTTPException(404, "成片不存在")
        output, version, position = context
        cues = _subtitle_cues(job, output)
        if not cues:
            raise HTTPException(404, "当前成片没有可用对白字幕")
        fmt = str(format or "srt").lower()
        if fmt not in {"srt", "vtt"}:
            raise HTTPException(400, "字幕格式仅支持 srt 或 vtt")
        subtitle_path = Path(job["outputDirectory"]) / f"{Path(filename).stem}.{fmt}"
        lines = ["WEBVTT", ""] if fmt == "vtt" else []
        for index, cue in enumerate(cues, 1):
            if fmt == "srt":
                lines.append(str(index))
            lines.append(f"{_subtitle_timestamp(cue['start'], vtt=fmt == 'vtt')} --> {_subtitle_timestamp(cue['end'], vtt=fmt == 'vtt')}")
            lines.append(cue["text"])
            lines.append("")
        subtitle_path.write_text("\n".join(lines), encoding="utf-8")
        download_name = friendly_download_filename(
            source_filename=str(job.get("filename") or "视频"),
            version_number=version.get("number") or output.get("versionNumber") or 1,
            strategy_key=str(version.get("strategyKey") or output.get("strategyKey") or "manual"),
            source_label=str(version.get("sourceLabel") or output.get("sourceLabel") or ""),
            display_name=str(version.get("displayName") or output.get("displayName") or ""),
            title=str(output.get("title") or "高光成片"),
            position=position,
            extension=fmt,
        )
    return FileResponse(subtitle_path, media_type="text/vtt" if fmt == "vtt" else "application/x-subrip", filename=download_name, content_disposition_type="attachment")


@app.get("/api/jobs/{job_id}/outputs/{filename}")
def output_media(job_id: str, filename: str, download: int = 0) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        context = output_download_context(job, filename)
        if not context:
            raise HTTPException(404, "输出文件不存在")
        output, version, position = context
        path = Path(job["outputDirectory"]) / filename
        download_name = friendly_download_filename(
            source_filename=str(job.get("filename") or "视频"),
            version_number=version.get("number") or output.get("versionNumber") or 1,
            strategy_key=str(version.get("strategyKey") or output.get("strategyKey") or "manual"),
            source_label=str(version.get("sourceLabel") or output.get("sourceLabel") or ""),
            display_name=str(version.get("displayName") or output.get("displayName") or ""),
            title=str(output.get("title") or "高光成片"),
            position=position,
        )
    if not path.is_file():
        raise HTTPException(404, "输出文件不存在")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=download_name if download else filename,
        content_disposition_type="attachment" if download else "inline",
    )


@app.get("/api/jobs/{job_id}/outputs/{filename}/preview")
def output_preview_media(job_id: str, filename: str) -> FileResponse:
    try:
        path = prepare_output_preview(job_id, filename)
    except RuntimeError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(path, media_type="video/mp4", content_disposition_type="inline")


@app.get("/api/jobs/{job_id}/outputs/{filename}/browser-preview")
def output_browser_preview_media(job_id: str, filename: str) -> FileResponse:
    try:
        path = prepare_browser_preview(job_id, filename)
    except RuntimeError as error:
        raise HTTPException(404, str(error)) from error
    return FileResponse(path, media_type="video/webm", content_disposition_type="inline")


static_directory = settings.root / "static"
app.mount("/static", StaticFiles(directory=static_directory), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(static_directory / "index.html")
