#!/usr/bin/env python3
"""Run a real video through ClipTalk's four public editing workflows.

The command is intentionally dataset-free: callers provide one source video and
workflow instructions. It creates normal, retained jobs and records enough
contract information to diagnose discovery, analysis, review, confirmation,
rendering, and media-delivery failures without reaching into the server's data
directory.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: I001


WORKFLOWS = ("highlight", "content_search", "person_edit", "speaker_edit")
TASK_MODES = {
    "highlight": "highlight",
    "content_search": "content_extract",
    "person_edit": "content_extract",
    "speaker_edit": "content_extract",
}
ENTRY_WORKFLOWS = {
    "person_edit": "person_discovery",
    "speaker_edit": "voice_discovery",
}
REVIEW_STATUSES = {
    workflow: "awaiting_confirmation" if workflow == "highlight" else "awaiting_content_confirmation"
    for workflow in WORKFLOWS
}
TERMINAL_FAILURES = {"failed", "cancelled"}
ACTIVE_STATUSES = {"briefing", "queued", "running", "rendering", "cancelling"}
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def interval_overlap(left: tuple[float, float], right: tuple[float, float]) -> float:
    return max(0.0, min(left[1], right[1]) - max(left[0], right[0]))


def compact_text(value: Any, limit: int = 300) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


@dataclass
class Issue:
    severity: str
    code: str
    flow: str
    phase: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""


@dataclass
class Transition:
    observedAt: str
    elapsedSeconds: float
    status: str
    stage: str
    progress: float | None
    detail: str


class ApiFailure(RuntimeError):
    def __init__(self, method: str, path: str, response: httpx.Response) -> None:
        request_id = response.headers.get("x-request-id", "")
        try:
            payload = response.json()
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        except (ValueError, TypeError):
            detail = response.text
        self.method = method
        self.path = path
        self.status_code = response.status_code
        self.detail = compact_text(detail, 900)
        self.request_id = request_id
        super().__init__(
            f"{method} {path} 返回 HTTP {response.status_code}: {self.detail}"
            + (f" (request-id: {request_id})" if request_id else "")
        )


class WorkflowClient:
    def __init__(self, base_url: str, token: str, request_timeout: float) -> None:
        headers = {"Accept": "application/json"}
        if token:
            headers["X-Highlight-Token"] = token
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(request_timeout, connect=min(15.0, request_timeout)),
            follow_redirects=False,
        )

    def close(self) -> None:
        self.client.close()

    def request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise RuntimeError(f"无法访问 {method} {path}: {error}") from error
        if response.status_code >= 400:
            raise ApiFailure(method, path, response)
        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError(f"{method} {path} 未返回 JSON") from error
        if not isinstance(payload, dict):
            raise RuntimeError(f"{method} {path} 返回了非对象 JSON")  # noqa: TRY004
        return payload

    def health(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/health")

    def create_job(self, video: Path, workflow: str, instruction: str, force_reanalyze: bool) -> dict[str, Any]:
        task_mode = TASK_MODES[workflow]
        common = {
            "expected_size_bytes": str(video.stat().st_size),
            "task_mode": task_mode,
            "intent_mode": task_mode,
            "workflow_kind": workflow,
            "entry_workflow": ENTRY_WORKFLOWS.get(workflow, ""),
            "parameter_context": "legacy_explicit",
            "storage_mode": "editable",
            "instruction": instruction,
            "count": "auto",
            "target_seconds": "auto",
            "analysis_mode": "audiovisual",
            "recognition_profile": "auto",
            "force_reanalyze": "true" if force_reanalyze else "false",
            "subtitle_mode": "none",
            "subtitle_style": "clean",
            "edit_mode": "ai_plan",
            "structure": "auto",
            "auto_variant_count": "1",
            "source_scope_kind": "all",
            "result_strategy": "review",
        }
        if task_mode == "content_extract":
            common.update({
                "search_scope_kind": "all",
                "search_result_limit": "12",
                "search_boundary_mode": "complete",
                "content_auto_generate": "false",
            })
        media_type = "video/mp4" if video.suffix.lower() == ".mp4" else "application/octet-stream"
        with video.open("rb") as handle:
            return self.request_json(
                "POST",
                "/api/jobs",
                data=common,
                files={"video": (video.name, handle, media_type)},
            )

    def create_same_source_task(
        self, job_id: str, workflow: str, instruction: str, expected_speaker_count: int,
        *, analysis_only: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"workflowKind": workflow, "instruction": instruction}
        if workflow == "highlight" and analysis_only:
            payload["autoCompose"] = False
        if workflow == "speaker_edit" and expected_speaker_count > 0:
            payload["expectedSpeakerCount"] = expected_speaker_count
        return self.request_json(
            "POST", f"/api/jobs/{quote(job_id, safe='')}/tasks", json=payload,
        )

    def get_job(self, job_id: str) -> dict[str, Any]:
        payload = self.request_json("GET", f"/api/jobs/{quote(job_id, safe='')}")
        job = payload.get("job")
        if not isinstance(job, dict):
            raise RuntimeError(f"任务 {job_id} 响应缺少 job 对象")  # noqa: TRY004
        return job

    def confirm_highlight(self, job_id: str, selection: dict[str, Any]) -> dict[str, Any]:
        payload = {
            **selection,
            "outputMode": "single_reel",
            "subtitleMode": "none",
            "subtitleStyle": "clean",
            "orderMode": "source",
            "acceptOvertime": True,
        }
        return self.request_json(
            "POST", f"/api/jobs/{quote(job_id, safe='')}/confirm", json=payload,
        )

    def confirm_content(self, job_id: str, search_id: str, match_ids: list[str]) -> dict[str, Any]:
        return self.request_json(
            "POST",
            f"/api/jobs/{quote(job_id, safe='')}/content-search/confirm",
            json={
                "searchId": search_id,
                "matchIds": match_ids,
                "outputMode": "single_reel",
                "orderMode": "source",
                "subtitleMode": "none",
                "subtitleStyle": "clean",
                "acknowledgeIncomplete": True,
            },
        )

    def list_persons(self, job_id: str) -> dict[str, Any]:
        return self.request_json(
            "GET", f"/api/jobs/{quote(job_id, safe='')}/content-search/persons",
        )

    def select_person(self, job_id: str, person_id: str) -> dict[str, Any]:
        return self.request_json(
            "POST", f"/api/jobs/{quote(job_id, safe='')}/content-search/target-person",
            json={"personIds": [person_id], "matchMode": "any", "activity": "appearance"},
        )

    def discover_voices(self, job_id: str, expected_speaker_count: int) -> dict[str, Any]:
        return self.request_json(
            "POST", f"/api/jobs/{quote(job_id, safe='')}/content-search/voices/discover",
            json={"expectedSpeakerCount": expected_speaker_count, "force": False},
        )

    def list_voices(self, job_id: str) -> dict[str, Any]:
        return self.request_json(
            "GET", f"/api/jobs/{quote(job_id, safe='')}/content-search/voices",
        )

    def select_speaker(
        self, job_id: str, speaker_ref: str, query: str,
    ) -> dict[str, Any]:
        return self.request_json(
            "POST", f"/api/jobs/{quote(job_id, safe='')}/content-search/target-speakers",
            json={"speakerRefs": [speaker_ref], "mode": "include", "query": query},
        )

    def send_message(self, job_id: str, text: str) -> dict[str, Any]:
        """Use the same atomic command engine as the browser conversation."""
        return self.request_json(
            "POST",
            f"/api/jobs/{quote(job_id, safe='')}/messages",
            json={"text": text, "uiContext": {"source": "workflow-validator"}},
        )

    def probe_output(self, job_id: str, output: dict[str, Any]) -> dict[str, Any]:
        filename = str(output.get("filename") or "")
        path = str(output.get("videoUrl") or "")
        if not path:
            path = f"/api/jobs/{quote(job_id, safe='')}/outputs/{quote(filename, safe='')}"
        try:
            with self.client.stream("GET", path, headers={"Range": "bytes=0-0"}) as response:
                if response.status_code >= 400:
                    raise ApiFailure("GET", path, response)
                first_chunk = next(response.iter_bytes(), b"")
                return {
                    "path": path,
                    "statusCode": response.status_code,
                    "contentType": response.headers.get("content-type", ""),
                    "contentLength": response.headers.get("content-length", ""),
                    "rangeSupported": response.status_code == 206,
                    "readable": bool(first_chunk),
                }
        except httpx.HTTPError as error:
            raise RuntimeError(f"无法读取输出 {filename}: {error}") from error


def issue(
    issues: list[Issue], severity: str, code: str, flow: str, phase: str,
    message: str, *, evidence: dict[str, Any] | None = None, recommendation: str = "",
) -> None:
    issues.append(Issue(
        severity=severity,
        code=code,
        flow=flow,
        phase=phase,
        message=message,
        evidence=evidence or {},
        recommendation=recommendation,
    ))


def video_duration(job: dict[str, Any]) -> float | None:
    info = job.get("videoInfo") if isinstance(job.get("videoInfo"), dict) else {}
    return finite_number(info.get("duration"))


def validate_range(
    item: dict[str, Any], duration: float | None, *, flow: str, phase: str,
    identity: str, issues: list[Issue],
) -> tuple[float, float] | None:
    start = finite_number(item.get("start"))
    end = finite_number(item.get("end"))
    if start is None or end is None:
        issue(
            issues, "error", "range.not_numeric", flow, phase,
            f"{identity} 的起止时间不是有限数字。",
            evidence={"start": item.get("start"), "end": item.get("end")},
            recommendation="检查分析结果序列化和模型输出校验。",
        )
        return None
    if start < 0 or end <= start:
        issue(
            issues, "error", "range.invalid", flow, phase,
            f"{identity} 的时间范围无效。",
            evidence={"start": start, "end": end},
            recommendation="在候选落库前拒绝负时间和非正时长区间。",
        )
        return None
    if duration is not None and end > duration + 0.15:
        issue(
            issues, "error", "range.out_of_source", flow, phase,
            f"{identity} 超出源视频时长。",
            evidence={"start": start, "end": end, "videoDuration": duration},
            recommendation="对候选边界执行源时长裁剪，并记录发生裁剪的原因。",
        )
    declared = finite_number(item.get("duration"))
    actual = end - start
    if declared is not None and abs(declared - actual) > max(0.25, actual * 0.05):
        issue(
            issues, "warning", "range.duration_mismatch", flow, phase,
            f"{identity} 的 duration 与起止时间不一致。",
            evidence={"declared": declared, "calculated": round(actual, 3)},
            recommendation="统一从 start/end 重新计算持久化时长。",
        )
    return start, end


def validate_highlight(job: dict[str, Any], max_selected: int) -> tuple[dict[str, Any] | None, dict[str, Any], list[Issue]]:
    issues: list[Issue] = []
    flow = "highlight"
    if str(job.get("taskMode") or "") != flow:
        issue(issues, "error", "job.task_mode_mismatch", flow, "review", "服务返回了错误的任务类型。", evidence={"taskMode": job.get("taskMode")})
    duration = video_duration(job)
    groups = [value for value in job.get("eventGroups") or [] if isinstance(value, dict)]
    candidates = [value for value in job.get("candidates") or [] if isinstance(value, dict)]
    metrics: dict[str, Any] = {
        "videoDuration": duration,
        "eventGroupCount": len(groups),
        "rawCandidateCount": len(candidates),
        "recommendedGroupCount": len(job.get("recommendedGroupIds") or []),
    }
    source_validation = job.get("sourceValidation") if isinstance(job.get("sourceValidation"), dict) else {}
    for warning in source_validation.get("warnings") or []:
        issue(issues, "warning", "source.coverage_warning", flow, "analysis", compact_text(warning), recommendation="人工检查对应时间范围是否解码完整。")
    if job.get("directorDegraded"):
        issue(issues, "warning", "highlight.director_degraded", flow, "analysis", "视觉导演发生降级，候选质量可能低于正常模式。", evidence={"reason": compact_text(job.get("directorDegradedReason"))}, recommendation="检查视觉模型调用、响应格式和超时日志。")
    if not groups:
        issue(
            issues, "error", "highlight.no_event_groups", flow, "review",
            "高光分析没有生成可确认的事件组。",
            evidence={"rawCandidateCount": len(candidates), "detail": compact_text(job.get("detail"))},
            recommendation="检查视觉候选、事件归组门槛和降级链路。",
        )
        if candidates:
            valid_indices = []
            intervals: list[tuple[float, float]] = []
            for index, candidate in enumerate(candidates):
                current = validate_range(candidate, duration, flow=flow, phase="review", identity=f"候选 {index + 1}", issues=issues)
                if current and not any(interval_overlap(current, old) > 0.01 for old in intervals):
                    valid_indices.append(index)
                    intervals.append(current)
                if len(valid_indices) >= max_selected:
                    break
            return ({"indices": valid_indices} if valid_indices else None), metrics, issues

    lookup = {str(group.get("id") or ""): group for group in groups if str(group.get("id") or "")}
    recommended = [str(value) for value in job.get("recommendedGroupIds") or []]
    missing = [value for value in recommended if value not in lookup]
    if missing:
        issue(issues, "error", "highlight.invalid_recommendation", flow, "review", "推荐事件 ID 不存在于事件组中。", evidence={"missingGroupIds": missing}, recommendation="保存任务前校验 recommendedGroupIds 的引用完整性。")
    ordered_ids = list(dict.fromkeys([*recommended, *lookup.keys()]))
    selected_ids: list[str] = []
    selected_segments: dict[str, list[str]] = {}
    occupied: list[tuple[float, float]] = []
    skipped_overlap: list[str] = []
    skipped_segments: list[dict[str, Any]] = []
    total_segments = 0
    for group_id in ordered_ids:
        group = lookup.get(group_id)
        if not group:
            continue
        segments = [value for value in group.get("segments") or [] if isinstance(value, dict)]
        if not segments:
            issue(issues, "error", "highlight.empty_event_group", flow, "review", f"事件组 {group_id} 没有镜头。", recommendation="归组完成后删除空事件，或阻止其进入审核。")
            continue
        ranges: list[tuple[float, float]] = []
        ids: list[str] = []
        invalid = False
        skipped_before_group = len(skipped_segments)
        for index, segment in enumerate(segments):
            segment_id = str(segment.get("id") or "")
            if not segment_id:
                issue(issues, "error", "highlight.segment_missing_id", flow, "review", f"事件组 {group_id} 的第 {index + 1} 个镜头缺少 ID。", recommendation="候选落库时生成并校验稳定 ID。")
                invalid = True
                continue
            current = validate_range(segment, duration, flow=flow, phase="review", identity=f"镜头 {segment_id}", issues=issues)
            if current is None:
                invalid = True
                continue
            if not segment.get("reusableAnchor"):
                conflict = next(
                    (old for old in [*occupied, *ranges] if interval_overlap(current, old) > 0.01),
                    None,
                )
                if conflict is not None:
                    skipped_segments.append({
                        "groupId": group_id,
                        "segmentId": segment_id,
                        "range": list(current),
                        "overlaps": list(conflict),
                    })
                    continue
                ranges.append(current)
            ids.append(segment_id)
        if invalid or not ids:
            if not ids and len(skipped_segments) > skipped_before_group:
                skipped_overlap.append(group_id)
            continue
        selected_ids.append(group_id)
        selected_segments[group_id] = ids
        occupied.extend(ranges)
        total_segments += len(ids)
        if len(selected_ids) >= max_selected:
            break
    if skipped_overlap:
        issue(
            issues, "warning", "highlight.overlapping_groups", flow, "review",
            "部分推荐事件复用了主体镜头，自动验证已跳过这些事件。",
            evidence={"skippedGroupIds": skipped_overlap},
            recommendation="在推荐阶段去重主体时间范围，或明确标记可复用上下文锚点。",
        )
    if skipped_segments:
        issue(
            issues, "warning", "highlight.overlapping_segments", flow, "review",
            "推荐选择包含确认接口不接受的重叠主体镜头；自动验证已剔除冲突镜头后继续。",
            evidence={"skippedSegments": skipped_segments},
            recommendation="在事件审核结果发布前使用与确认接口相同的主体镜头重叠校验。",
        )
    metrics.update({"selectedGroupCount": len(selected_ids), "selectedSegmentCount": total_segments})
    if not selected_ids:
        issue(issues, "error", "highlight.no_confirmable_selection", flow, "review", "没有可安全提交的高光选择。", recommendation="修复空组、无效边界或重复镜头后重试。")
        return None, metrics, issues
    return {"groupIds": selected_ids, "segmentIds": selected_segments}, metrics, issues


def candidate_has_evidence(candidate: dict[str, Any]) -> bool:
    collection_fields = ("evidenceRefs", "matchedEvidence", "matchedModalities")
    if any(candidate.get(key) for key in collection_fields):
        return True
    return any(compact_text(candidate.get(key)) for key in ("transcriptExcerpt", "ocrExcerpt", "reason", "visualDescription"))


def validate_workflow_identity(job: dict[str, Any], workflow: str) -> list[Issue]:
    issues: list[Issue] = []
    expected_task_mode = TASK_MODES[workflow]
    if str(job.get("taskMode") or "") != expected_task_mode:
        issue(
            issues, "error", "job.task_mode_mismatch", workflow, "creation",
            "服务返回了错误的底层任务类型。",
            evidence={"expected": expected_task_mode, "actual": job.get("taskMode")},
            recommendation="创建任务时同时校验 workflowKind 与 taskMode 的映射。",
        )
    actual_workflow = str(job.get("workflowKind") or "")
    if actual_workflow and actual_workflow != workflow:
        issue(
            issues, "error", "job.workflow_kind_mismatch", workflow, "creation",
            "服务返回了错误的产品工作流。",
            evidence={"expected": workflow, "actual": actual_workflow},
            recommendation="显式 workflow_kind 不应再被意图分类结果覆盖。",
        )
    return issues


def validate_person_discovery(
    job: dict[str, Any], payload: dict[str, Any],
) -> tuple[str | None, dict[str, Any], list[Issue]]:
    flow = "person_edit"
    issues = validate_workflow_identity(job, flow)
    persons = [value for value in payload.get("persons") or [] if isinstance(value, dict)]
    raw_person_count = int((job.get("contentIndex") or {}).get("rawAnonymousPersonCount") or len(persons))
    metrics: dict[str, Any] = {
        "personCount": len(persons),
        "rawPersonCount": raw_person_count,
        "manualMergeCount": max(0, raw_person_count - len(persons)),
    }
    duration = video_duration(job)
    ranked: list[tuple[float, float, str]] = []
    seen: set[str] = set()
    for position, person in enumerate(persons, 1):
        person_id = str(person.get("id") or "")
        if not person_id:
            issue(issues, "error", "person.missing_id", flow, "discovery", f"第 {position} 个人物缺少 ID。")
            continue
        if person_id in seen:
            issue(issues, "error", "person.duplicate_id", flow, "discovery", "人物目录包含重复 ID。", evidence={"personId": person_id})
            continue
        seen.add(person_id)
        ranges = [value for value in person.get("ranges") or [] if isinstance(value, dict)]
        appearance_seconds = 0.0
        for range_position, item in enumerate(ranges, 1):
            current = validate_range(
                item, duration, flow=flow, phase="discovery",
                identity=f"人物 {person_id} 出镜区间 {range_position}", issues=issues,
            )
            if current:
                appearance_seconds += current[1] - current[0]
        ranked.append((appearance_seconds, float(person.get("confidence") or 0), person_id))
    if not persons:
        issue(
            issues, "error", "person.no_candidates", flow, "discovery",
            "人物发现没有返回可选择的匿名人物。",
            evidence={"stage": job.get("stage"), "detail": compact_text(job.get("detail"))},
            recommendation="检查人物索引、检测阈值和内容索引缓存。",
        )
        return None, metrics, issues
    ranked.sort(reverse=True)
    short_people = sum(1 for appearance, _confidence, _person_id in ranked if appearance < 1.0)
    review_people = sum(bool(value.get("reviewRecommended")) for value in persons)
    metrics.update({
        "shortAppearancePersonCount": short_people,
        "reviewRecommendedPersonCount": review_people,
        "personFragmentationRate": round(short_people / max(1, len(persons)), 4),
    })
    if len(persons) >= 3 and short_people / len(persons) > .35:
        issue(
            issues, "warning", "person.fragmentation_high", flow, "discovery",
            "短暂人物卡占比过高，人物识别可能仍然偏碎。",
            evidence={"shortCards": short_people, "personCount": len(persons)},
            recommendation="检查待复核人物并合并重复卡；若大量卡片仅出现不足 1 秒，应重新评估轨迹连续性阈值。",
        )
    selected = ranked[0][2] if ranked else None
    metrics.update({
        "selectedPersonId": selected,
        "selectedAppearanceSeconds": round(ranked[0][0], 3) if ranked else 0,
    })
    return selected, metrics, issues


def validate_speaker_discovery(
    job: dict[str, Any], payload: dict[str, Any], expected_speaker_count: int = 0,
) -> tuple[str | None, dict[str, Any], list[Issue]]:
    flow = "speaker_edit"
    issues = validate_workflow_identity(job, flow)
    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    voices = [value for value in payload.get("voices") or [] if isinstance(value, dict)]
    timeline = [value for value in payload.get("timeline") or [] if isinstance(value, dict)]
    metrics: dict[str, Any] = {
        "discoveryStatus": status.get("status"),
        "voiceCount": len(voices),
        "timelineTurnCount": len(timeline),
        "expectedSpeakerCount": expected_speaker_count or None,
        "reviewRequiredCount": sum(bool(value.get("requiresReview")) for value in voices),
    }
    if str(status.get("status") or "") != "ready":
        issue(
            issues, "error", "speaker.discovery_not_ready", flow, "discovery",
            "说话人发现没有进入 ready 状态。",
            evidence={"status": status},
            recommendation="检查语音识别、说话人分离模型及后台任务错误。",
        )
    if expected_speaker_count and len(voices) != expected_speaker_count:
        issue(
            issues, "warning", "speaker.expected_count_mismatch", flow, "discovery",
            "识别出的声音数量与指定人数不一致。",
            evidence={"expected": expected_speaker_count, "actual": len(voices)},
            recommendation="试听代表片段；必要时调整人数重新识别或人工拆分/合并声音。",
        )
    if not voices:
        issue(
            issues, "error", "speaker.no_candidates", flow, "discovery",
            "说话人发现没有返回可选择的声音。",
            recommendation="确认视频含清晰语音，并检查 ASR、VAD、聚类模型配置。",
        )
        return None, metrics, issues
    duration = video_duration(job)
    short_turns = sum(
        1 for turn in timeline
        if max(0.0, float(turn.get("end") or 0) - float(turn.get("start") or 0)) < 1.0
    )
    turns_per_minute = len(timeline) / max(1 / 60, float(duration or 0) / 60)
    metrics.update({
        "shortTurnCount": short_turns,
        "shortTurnRate": round(short_turns / max(1, len(timeline)), 4),
        "turnsPerMinute": round(turns_per_minute, 3),
    })
    if len(timeline) >= 8 and short_turns / len(timeline) > .4:
        issue(
            issues, "warning", "speaker.fragmentation_high", flow, "discovery",
            "不足 1 秒的发言轮次占比过高，说话人时间轴可能偏碎。",
            evidence={"shortTurns": short_turns, "timelineTurns": len(timeline)},
            recommendation="检查短停顿桥接、VAD 边界和人工拆分记录；优先以发言事件展示连续轮次。",
        )
    ranked: list[tuple[bool, float, str]] = []
    seen: set[str] = set()
    for position, voice in enumerate(voices, 1):
        speaker_ref = str(voice.get("speakerRef") or "")
        if not speaker_ref:
            issue(issues, "error", "speaker.missing_ref", flow, "discovery", f"第 {position} 个声音缺少 speakerRef。")
            continue
        if speaker_ref in seen:
            issue(issues, "error", "speaker.duplicate_ref", flow, "discovery", "声音目录包含重复 speakerRef。", evidence={"speakerRef": speaker_ref})
            continue
        seen.add(speaker_ref)
        for range_position, item in enumerate(voice.get("representativeSegments") or [], 1):
            if isinstance(item, dict):
                validate_range(
                    item, duration, flow=flow, phase="discovery",
                    identity=f"声音 {speaker_ref} 代表片段 {range_position}", issues=issues,
                )
        quality = voice.get("quality") if isinstance(voice.get("quality"), dict) else {}
        if quality.get("suspectedMixed"):
            issue(
                issues, "warning", "speaker.suspected_mixed_cluster", flow, "discovery",
                f"声音 {speaker_ref} 的簇内差异较大，可能混入不同人物。",
                evidence={"quality": quality},
                recommendation="试听代表片段，并用人数重识别或时间轴校正拆分该声音。",
            )
        ranked.append((not bool(voice.get("requiresReview")), float(voice.get("speechSeconds") or 0), speaker_ref))
    ranked.sort(reverse=True)
    selected = ranked[0][2] if ranked else None
    selected_voice = next((value for value in voices if str(value.get("speakerRef")) == selected), None)
    if selected_voice and selected_voice.get("requiresReview"):
        issue(
            issues, "warning", "speaker.auto_selected_unverified", flow, "selection",
            "没有无需复核的声音；自动测试选择了发言时长最长的声音。",
            evidence={"speakerRef": selected, "quality": selected_voice.get("quality")},
            recommendation="真实剪辑时应先试听，自动测试的选择只验证流程连通性。",
        )
    metrics.update({
        "selectedSpeakerRef": selected,
        "selectedSpeechSeconds": finite_number((selected_voice or {}).get("speechSeconds")),
    })
    return selected, metrics, issues


def validate_content(
    job: dict[str, Any], max_selected: int, *, flow: str = "content_search",
) -> tuple[tuple[str, list[str]] | None, dict[str, Any], list[Issue]]:
    issues: list[Issue] = []
    issues.extend(validate_workflow_identity(job, flow))
    search = job.get("contentSearch") if isinstance(job.get("contentSearch"), dict) else {}
    search_id = str(search.get("id") or "")
    candidates = [value for value in search.get("candidates") or [] if isinstance(value, dict)]
    duration = video_duration(job)
    completeness = search.get("completeness") if isinstance(search.get("completeness"), dict) else {}
    coverage = search.get("coverage") if isinstance(search.get("coverage"), dict) else {}
    execution = search.get("executionPlan") if isinstance(search.get("executionPlan"), dict) else {}
    pending_count = int(completeness.get("pendingCount") or 0)
    metrics: dict[str, Any] = {
        "videoDuration": duration,
        "searchId": search_id,
        "candidateCount": len(candidates),
        "resultMode": search.get("resultMode"),
        "coverageStatus": search.get("coverageStatus") or coverage.get("status"),
        "completenessStatus": completeness.get("status"),
        "pendingReviewCount": pending_count,
        "candidateEventCount": len(search.get("candidateEvents") or []),
        "candidateEventCompressionRatio": round(
            len(search.get("candidateEvents") or []) / max(1, len(candidates)), 4,
        ),
    }
    if not search_id:
        issue(issues, "error", "content.missing_search", flow, "review", "任务没有可确认的 contentSearch ID。", recommendation="确保检索记录先持久化，再切换到等待确认状态。")
    clarification = search.get("clarification")
    if clarification:
        issue(issues, "error", "content.clarification_required", flow, "review", "检索条件仍需用户澄清，自动流程无法继续。", evidence={"clarification": search.get("clarification")}, recommendation="传入更明确的人物、对白、动作、场景或时间条件。")
    coverage_complete = search.get("coverageComplete")
    coverage_incomplete = (
        coverage_complete is False
        or str(search.get("coverageStatus") or "") in {"partial", "unavailable"}
    )
    coverage_warnings = list(dict.fromkeys([
        *(execution.get("warnings") or []), *(completeness.get("warnings") or []),
    ]))
    # Ranked retrieval deliberately scans only enough evidence to return the
    # requested best matches. Partial full-source coverage is actionable only
    # for find-all searches, or when the service reports an actual failure.
    if coverage_incomplete and (
        str(search.get("resultMode") or "") == "exhaustive" or coverage_warnings
    ):
        issue(issues, "warning", "content.coverage_incomplete", flow, "analysis", "内容索引或必要模态没有完整覆盖检索范围。", evidence={"coverageStatus": search.get("coverageStatus"), "warnings": list(dict.fromkeys([*(execution.get("warnings") or []), *(completeness.get("warnings") or [])]))}, recommendation="检查语音、OCR、人物、画面索引的失败操作后补检。")
    semantic_coverage = coverage.get("semantic") if isinstance(coverage.get("semantic"), dict) else {}
    semantic_completed = finite_number(semantic_coverage.get("completed"))
    semantic_total = finite_number(semantic_coverage.get("total"))
    if semantic_completed is not None and semantic_total is not None and semantic_completed > semantic_total:
        issue(issues, "warning", "content.coverage_counter_invalid", flow, "analysis", "语义覆盖计数 completed 大于 total，进度契约自相矛盾。", evidence={"completed": semantic_completed, "total": semantic_total, "percent": semantic_coverage.get("percent")}, recommendation="统一 coverage.semantic 与 retrievalStats 中已复核/总单元的字段方向。")
    if clarification:
        return None, metrics, issues
    if not candidates:
        issue(issues, "error", "content.no_matches", flow, "review", "内容检索没有返回任何候选。", evidence={"instruction": compact_text(search.get("instruction")), "coverageStatus": search.get("coverageStatus")}, recommendation="先确认查询确实存在于视频，再检查能力路由、召回阈值和覆盖缺口。")

    lookup: dict[str, dict[str, Any]] = {}
    evidence_count = 0
    reliable_ids: list[str] = []
    for index, candidate in enumerate(candidates):
        match_id = str(candidate.get("id") or "")
        identity = f"内容候选 {match_id or index + 1}"
        if not match_id:
            issue(issues, "error", "content.match_missing_id", flow, "review", f"{identity} 缺少 ID。", recommendation="检索结果落库前生成稳定 match ID。")
            continue
        lookup[match_id] = candidate
        valid_range = validate_range(candidate, duration, flow=flow, phase="review", identity=identity, issues=issues)
        has_evidence = candidate_has_evidence(candidate)
        evidence_count += int(has_evidence)
        if not has_evidence:
            issue(issues, "warning", "content.match_without_evidence", flow, "review", f"{identity} 没有可展示的命中证据。", evidence={"title": compact_text(candidate.get("title"))}, recommendation="候选必须携带证据引用、对白/OCR 摘要或明确匹配理由。")
        review_status = str(candidate.get("reviewStatus") or "")
        requires_review = bool(candidate.get("requiresReview"))
        if valid_range and review_status != "rejected" and not requires_review:
            reliable_ids.append(match_id)
    metrics["evidenceBackedCount"] = evidence_count
    metrics["reliableCandidateCount"] = len(reliable_ids)

    if pending_count > 0:
        issue(
            issues, "error", "content.human_review_required", flow, "confirmation",
            f"还有 {pending_count} 个不确定候选必须人工保留或排除，脚本不会替用户做语义判断。",
            evidence={"pendingCount": pending_count},
            recommendation="在审核界面逐项处理不确定候选后，再次运行或手工生成成片。",
        )
        return None, metrics, issues
    defaults = [str(value) for value in search.get("defaultSelectedIds") or []]
    invalid_defaults = [value for value in defaults if value not in lookup]
    if invalid_defaults:
        issue(issues, "error", "content.invalid_default_selection", flow, "review", "默认选择引用了不存在的候选。", evidence={"missingMatchIds": invalid_defaults}, recommendation="更新候选列表时同步过滤 defaultSelectedIds。")
    reliable_set = set(reliable_ids)
    ordered = list(dict.fromkeys([value for value in defaults if value in reliable_set] + reliable_ids))
    selected = ordered[:max_selected]
    metrics["selectedMatchCount"] = len(selected)
    if not selected:
        issue(issues, "error", "content.no_confirmable_selection", flow, "review", "没有无需人工判断且可安全提交的内容候选。", recommendation="人工审核 possible 候选，或改进检索置信度校准。")
        return None, metrics, issues
    return (search_id, selected), metrics, issues


def validate_outputs(job: dict[str, Any], flow: str) -> tuple[list[dict[str, Any]], list[Issue]]:
    issues: list[Issue] = []
    outputs = [value for value in job.get("outputs") or [] if isinstance(value, dict)]
    if not outputs:
        issue(issues, "error", "render.no_outputs", flow, "render", "任务完成但没有输出文件。", evidence={"status": job.get("status"), "stage": job.get("stage")}, recommendation="检查渲染任务持久化、staging 发布和输出版本同步。")
        return outputs, issues
    for index, output in enumerate(outputs):
        identity = str(output.get("filename") or f"输出 {index + 1}")
        if not output.get("filename"):
            issue(issues, "error", "render.output_missing_filename", flow, "render", f"{identity} 缺少文件名。", recommendation="输出发布前校验 filename 和实际文件一致。")
        duration = finite_number(output.get("duration"))
        if duration is None or duration <= 0:
            issue(issues, "error", "render.invalid_duration", flow, "render", f"{identity} 的成片时长无效。", evidence={"duration": output.get("duration")}, recommendation="渲染后使用 ffprobe 校验正式输出。")
        if not output.get("videoUrl"):
            issue(issues, "warning", "render.missing_video_url", flow, "delivery", f"{identity} 没有公开 videoUrl。", recommendation="public_job 应为每个输出稳定生成媒体 URL。")
    return outputs, issues


class WorkflowRunner:
    def __init__(
        self, client: WorkflowClient, *, video: Path, poll_interval: float,
        phase_timeout: float, stall_seconds: float, max_selected: int,
        analysis_only: bool, force_reanalyze: bool,
    ) -> None:
        self.client = client
        self.video = video
        self.poll_interval = poll_interval
        self.phase_timeout = phase_timeout
        self.stall_seconds = stall_seconds
        self.max_selected = max_selected
        self.analysis_only = analysis_only
        self.force_reanalyze = force_reanalyze

    def wait_for(self, job_id: str, flow: str, phase: str, accepted: set[str]) -> tuple[dict[str, Any], list[Transition], list[Issue]]:
        started = time.monotonic()
        last_change = started
        last_signature: tuple[Any, ...] | None = None
        transitions: list[Transition] = []
        issues: list[Issue] = []
        stall_reported = False
        while True:
            job = self.client.get_job(job_id)
            status = str(job.get("status") or "unknown")
            stage = str(job.get("stage") or "")
            progress = finite_number(job.get("progress"))
            detail = compact_text(job.get("detail"), 240)
            signature = (status, stage, progress, detail)
            elapsed = time.monotonic() - started
            if signature != last_signature:
                transitions.append(Transition(now_iso(), round(elapsed, 3), status, stage, progress, detail))
                last_signature = signature
                last_change = time.monotonic()
                stall_reported = False
            if status in accepted:
                return job, transitions, issues
            if status in TERMINAL_FAILURES:
                issue(issues, "error", f"{phase}.terminal_failure", flow, phase, f"任务以 {status} 结束。", evidence={"stage": stage, "detail": detail, "error": compact_text(job.get("error"), 900)}, recommendation="根据 jobId 和阶段查看服务日志中的结构化错误。")
                return job, transitions, issues
            if status == "awaiting_model_decision":
                issue(issues, "error", f"{phase}.model_decision_required", flow, phase, "任务等待模型决策，无法无人值守继续。", evidence={"pendingDecision": job.get("pendingDecision")}, recommendation="在界面完成决策，或为验证查询提供无歧义的显式任务模式。")
                return job, transitions, issues
            if elapsed >= self.phase_timeout:
                issue(issues, "error", f"{phase}.timeout", flow, phase, f"等待阶段超过 {self.phase_timeout:g} 秒。", evidence={"status": status, "stage": stage, "detail": detail, "progress": progress}, recommendation="检查任务队列、模型响应时间和 Worker 是否存活。")
                return job, transitions, issues
            unchanged = time.monotonic() - last_change
            if unchanged >= self.stall_seconds and not stall_reported:
                issue(issues, "warning", f"{phase}.stalled", flow, phase, f"任务状态超过 {self.stall_seconds:g} 秒没有变化。", evidence={"status": status, "stage": stage, "detail": detail, "progress": progress}, recommendation="检查对应阶段耗时、队列积压和外部模型超时配置。")
                stall_reported = True
            time.sleep(self.poll_interval)

    def wait_for_auto_composition(
        self, job_id: str,
    ) -> tuple[dict[str, Any], list[Transition], list[Issue]]:
        """Wait for conversational highlight auto-render before manual confirmation."""
        started = time.monotonic()
        transitions: list[Transition] = []
        issues: list[Issue] = []
        last_signature: tuple[Any, ...] | None = None
        while True:
            job = self.client.get_job(job_id)
            status = str(job.get("status") or "unknown")
            stage = str(job.get("stage") or "")
            progress = finite_number(job.get("progress"))
            detail = compact_text(job.get("detail"), 240)
            auto = job.get("autoComposition") if isinstance(job.get("autoComposition"), dict) else {}
            auto_status = str(auto.get("status") or "")
            auto_phase = str(auto.get("phase") or "")
            signature = (status, stage, auto_status, auto_phase, compact_text(auto.get("detail"), 160))
            elapsed = time.monotonic() - started
            if signature != last_signature:
                transitions.append(Transition(now_iso(), round(elapsed, 3), status, f"{stage}:{auto_phase}", progress, detail))
                last_signature = signature
            outputs = [value for value in job.get("outputs") or [] if isinstance(value, dict)]
            if outputs and auto_status not in {"running", "queued", "cancelling"}:
                return job, transitions, issues
            if status in TERMINAL_FAILURES:
                issue(issues, "error", "render.terminal_failure", "highlight", "render", f"自动成片以 {status} 结束。", evidence={"stage": stage, "autoStatus": auto_status, "detail": detail, "error": compact_text(job.get("error"), 900)}, recommendation="检查自动成片与质检日志。")
                return job, transitions, issues
            if auto_status in {"failed", "cancelled", "partial"} or (
                auto_status and auto_status not in {"running", "queued", "cancelling"} and not outputs
            ):
                issue(issues, "warning", "highlight.auto_composition_no_output", "highlight", "render", "后台自动成片结束但没有可验证输出，将回退到显式确认。", evidence={"autoStatus": auto_status, "autoPhase": auto_phase, "autoError": compact_text(auto.get("error"), 900)}, recommendation="检查自动成片质量门禁和输出发布。")
                return job, transitions, issues
            if elapsed >= self.phase_timeout:
                issue(issues, "warning", "highlight.auto_composition_timeout", "highlight", "render", f"后台自动成片超过 {self.phase_timeout:g} 秒，将停止等待。", evidence={"autoStatus": auto_status, "autoPhase": auto_phase, "detail": detail}, recommendation="检查自动质检、返修和证据补检是否收敛。")
                return job, transitions, issues
            time.sleep(self.poll_interval)

    def run_flow(
        self, flow: str, instruction: str, *, existing_job: dict[str, Any] | None = None,
        expected_speaker_count: int = 0, speaker_query: str = "",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "flow": flow,
            "instruction": instruction,
            "jobId": "",
            "discoveryTransitions": [],
            "analysisTransitions": [],
            "renderTransitions": [],
            "selection": {},
            "metrics": {},
            "outputs": [],
            "mediaProbes": [],
            "issues": [],
        }
        issues: list[Issue] = []
        try:
            if existing_job is None:
                created = self.client.create_job(self.video, flow, instruction, self.force_reanalyze)
                created_job = created.get("job") if isinstance(created.get("job"), dict) else created
            else:
                created_job = existing_job
            job_id = str(created_job.get("id") or "")
            if not job_id:
                raise RuntimeError("创建任务响应缺少 job.id")
            result["jobId"] = job_id
            print(f"[{flow}] 已创建任务 {job_id}", flush=True)
            issues.extend(validate_workflow_identity(created_job, flow))

            if flow == "speaker_edit":
                self.client.discover_voices(job_id, expected_speaker_count)
                print(f"[{flow}] 已启动说话人识别", flush=True)
                job, transitions, wait_issues = self.wait_for(
                    job_id, flow, "discovery", {REVIEW_STATUSES[flow]},
                )
                result["discoveryTransitions"] = [asdict(value) for value in transitions]
                issues.extend(wait_issues)
                voices_payload = self.client.list_voices(job_id)
                speaker_ref, discovery_metrics, discovery_issues = validate_speaker_discovery(
                    job, voices_payload, expected_speaker_count,
                )
                result["metrics"]["discovery"] = discovery_metrics
                issues.extend(discovery_issues)
                if not speaker_ref:
                    return self._finish_result(result, job, issues)
                result["selection"] = {
                    "speakerRef": speaker_ref, "mode": "include", "query": speaker_query,
                }
                selected = self.client.select_speaker(job_id, speaker_ref, speaker_query)
                selected_job = selected.get("job") if isinstance(selected.get("job"), dict) else None
                if selected_job and str(selected_job.get("id") or job_id) != job_id:
                    raise RuntimeError("说话人选择意外切换到了其他任务")
                print(f"[{flow}] 已选择声音 {speaker_ref}，等待发言片段", flush=True)
                job, transitions, wait_issues = self.wait_for(
                    job_id, flow, "analysis", {REVIEW_STATUSES[flow], "completed"},
                )
                result["analysisTransitions"] = [asdict(value) for value in transitions]
                issues.extend(wait_issues)
            else:
                job, transitions, wait_issues = self.wait_for(
                    job_id, flow, "discovery" if flow == "person_edit" else "analysis",
                    {REVIEW_STATUSES[flow], "completed"},
                )
                transition_key = "discoveryTransitions" if flow == "person_edit" else "analysisTransitions"
                result[transition_key] = [asdict(value) for value in transitions]
                issues.extend(wait_issues)

            status = str(job.get("status") or "")
            if status not in {REVIEW_STATUSES[flow], "completed"}:
                return self._finish_result(result, job, issues)

            if flow == "person_edit" and status != "completed":
                persons_payload = self.client.list_persons(job_id)
                person_id, discovery_metrics, discovery_issues = validate_person_discovery(
                    job, persons_payload,
                )
                result["metrics"]["discovery"] = discovery_metrics
                issues.extend(discovery_issues)
                if not person_id:
                    return self._finish_result(result, job, issues)
                result["selection"] = {
                    "personIds": [person_id], "matchMode": "any", "activity": "appearance",
                }
                self.client.select_person(job_id, person_id)
                print(f"[{flow}] 已选择人物 {person_id}，等待出镜片段", flush=True)
                job, transitions, wait_issues = self.wait_for(
                    job_id, flow, "analysis", {REVIEW_STATUSES[flow], "completed"},
                )
                result["analysisTransitions"] = [asdict(value) for value in transitions]
                issues.extend(wait_issues)
                status = str(job.get("status") or "")
                if status not in {REVIEW_STATUSES[flow], "completed"}:
                    return self._finish_result(result, job, issues)

            if flow == "highlight":
                selection, metrics, validation_issues = validate_highlight(job, self.max_selected)
            else:
                selection, metrics, validation_issues = validate_content(
                    job, self.max_selected, flow=flow,
                )
            if flow in {"person_edit", "speaker_edit"}:
                result["metrics"]["content"] = metrics
            else:
                result["metrics"] = metrics
            issues.extend(validation_issues)
            if status == "completed":
                self._inspect_outputs(result, job, flow, issues)
                return self._finish_result(result, job, issues)
            if self.analysis_only or selection is None:
                return self._finish_result(result, job, issues)
            auto = job.get("autoComposition") if isinstance(job.get("autoComposition"), dict) else {}
            if existing_job is not None and flow == "highlight" and str(auto.get("status") or "") in {"running", "queued"}:
                job, auto_transitions, auto_issues = self.wait_for_auto_composition(job_id)
                result["renderTransitions"] = [asdict(value) for value in auto_transitions]
                issues.extend(auto_issues)
                if job.get("outputs"):
                    self._inspect_outputs(result, job, flow, issues)
                    return self._finish_result(result, job, issues)
                current_auto = job.get("autoComposition") if isinstance(job.get("autoComposition"), dict) else {}
                if str(current_auto.get("status") or "") in {"running", "queued", "cancelling"}:
                    issue(issues, "error", "highlight.auto_composition_still_active", flow, "confirmation", "后台自动成片仍在运行，脚本不会并发提交人工确认。", evidence={"autoStatus": current_auto.get("status"), "autoPhase": current_auto.get("phase")}, recommendation="等待后台任务结束，或在服务端拒绝同一任务的并发确认。")
                    return self._finish_result(result, job, issues)

            if flow == "highlight":
                self.client.confirm_highlight(job_id, selection)
            else:
                search_id, match_ids = selection
                self.client.confirm_content(job_id, search_id, match_ids)
            print(f"[{flow}] 已提交确认，等待成片", flush=True)
            rendered, render_transitions, render_wait_issues = self.wait_for(job_id, flow, "render", {"completed"})
            result["renderTransitions"] = [asdict(value) for value in render_transitions]
            issues.extend(render_wait_issues)
            if str(rendered.get("status") or "") == "completed":
                self._inspect_outputs(result, rendered, flow, issues)
                job = rendered
            return self._finish_result(result, job, issues)
        except (ApiFailure, RuntimeError, OSError) as error:
            phase = "creation" if not result["jobId"] else "confirmation"
            evidence: dict[str, Any] = {"error": str(error)}
            if isinstance(error, ApiFailure):
                evidence.update({"statusCode": error.status_code, "requestId": error.request_id})
            issue(issues, "error", f"{phase}.request_failed", flow, phase, f"流程请求失败：{error}", evidence=evidence, recommendation="按响应状态和 request-id 对照服务日志定位。")
            failure_job = None
            if result["jobId"]:
                try:
                    failure_job = self.client.get_job(str(result["jobId"]))
                except (ApiFailure, RuntimeError):
                    pass
            return self._finish_result(result, failure_job, issues)

    def _inspect_outputs(
        self, result: dict[str, Any], job: dict[str, Any], flow: str, issues: list[Issue],
    ) -> None:
        outputs, output_issues = validate_outputs(job, flow)
        issues.extend(output_issues)
        result["outputs"] = [{
            key: output.get(key) for key in (
                "filename", "title", "displayTitle", "duration", "segmentCount",
                "videoUrl", "previewUrl", "previewReady", "previewOnly",
            ) if key in output
        } for output in outputs]
        for output in outputs:
            try:
                probe = self.client.probe_output(str(job.get("id") or ""), output)
                result["mediaProbes"].append(probe)
                if not probe["readable"]:
                    issue(issues, "error", "delivery.empty_response", flow, "delivery", f"输出 {output.get('filename')} 可请求但没有读取到媒体字节。", evidence=probe, recommendation="检查 FileResponse 指向的实际文件和反向代理 Range 配置。")
                content_type = str(probe.get("contentType") or "")
                if not content_type.startswith("video/"):
                    issue(issues, "warning", "delivery.unexpected_content_type", flow, "delivery", f"输出 {output.get('filename')} 的 Content-Type 不是 video/*。", evidence=probe, recommendation="媒体响应应返回正确的视频 MIME 类型。")
            except (ApiFailure, RuntimeError) as error:
                issue(issues, "error", "delivery.output_unreachable", flow, "delivery", f"输出 {output.get('filename')} 无法访问。", evidence={"error": str(error)}, recommendation="检查输出发布是否原子完成，以及媒体路由鉴权和文件路径。")

    @staticmethod
    def _finish_result(result: dict[str, Any], job: dict[str, Any] | None, issues: list[Issue]) -> dict[str, Any]:
        if job:
            result["finalState"] = {
                "status": job.get("status"),
                "stage": job.get("stage"),
                "detail": compact_text(job.get("detail"), 500),
                "error": compact_text(job.get("error"), 900),
            }
        result["issues"] = [asdict(value) for value in sorted(issues, key=lambda value: SEVERITY_ORDER[value.severity])]
        result["passed"] = not any(value.severity == "error" for value in issues)
        return result


def local_default_token(base_url: str, settings: Settings) -> str:
    host = (urlsplit(base_url).hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return os.environ.get("HIGHLIGHT_ACCESS_TOKEN", "").strip() or settings.access_token
    return ""


def parser_for(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="用一个真实视频自动验证高光剪辑、内容探索、按人物剪辑和按说话人剪辑",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--video", required=True, type=Path, help="待验证的真实视频；脚本不内置测试集")
    parser.add_argument("--base-url", default=f"http://127.0.0.1:{settings.port}", help="已启动的 ClipTalk 服务地址")
    parser.add_argument("--token", default="", help="访问令牌；本机地址默认读取 HIGHLIGHT_ACCESS_TOKEN")
    parser.add_argument("--highlight-instruction", default="生成一条包含关键动作、情绪变化和完整结果的高光")
    parser.add_argument("--search-query", default="查找视频中有明确对白或关键动作的片段")
    parser.add_argument("--person-instruction", default="提取所选画面人物的所有出镜片段")
    parser.add_argument("--speaker-query", default="", help="选择说话人后附加的发言内容筛选；留空提取全部发言")
    parser.add_argument("--expected-speaker-count", type=int, default=0, help="预计说话人数；0 表示自动判断")
    parser.add_argument(
        "--workflows", nargs="+", choices=WORKFLOWS, default=list(WORKFLOWS),
        help="要验证的工作流；默认依次验证四种模式",
    )
    parser.add_argument(
        "--mode", choices=("conversation", "independent"), default="conversation",
        help="conversation 只上传一次并基于同一素材切换任务；independent 每种模式分别上传",
    )
    parser.add_argument("--phase-timeout", type=float, default=1800, help="每个分析或渲染阶段的最长等待秒数")
    parser.add_argument("--request-timeout", type=float, default=180, help="单次 HTTP 请求超时秒数（含上传）")
    parser.add_argument("--poll-interval", type=float, default=2, help="状态轮询间隔秒数")
    parser.add_argument("--stall-seconds", type=float, default=180, help="状态无变化多久后报告卡顿提醒")
    parser.add_argument("--max-selected", type=int, default=3, help="每条流程最多自动确认的候选数")
    parser.add_argument("--analysis-only", action="store_true", help="只验证到候选审核，不确认和渲染")
    parser.add_argument("--reuse-analysis", action="store_true", help="允许服务复用相同要求的分析缓存")
    parser.add_argument("--fail-on-warning", action="store_true", help="存在 warning 时也返回失败退出码")
    parser.add_argument("--output", type=Path, help="JSON 报告路径；默认写入 test-results/")
    return parser


def health_issues(health: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    if not health.get("ok"):
        issue(issues, "error", "service.unhealthy", "system", "preflight", "服务健康检查未通过。", evidence={"health": health}, recommendation="先修复 /api/health 报告的问题。")
    for field_name, label in (("ffmpeg", "FFmpeg"), ("ffprobe", "FFprobe"), ("visionConfigured", "视觉模型")):
        if not health.get(field_name):
            issue(issues, "error", f"service.{field_name}_missing", "system", "preflight", f"{label} 未就绪，无法完成真实端到端验证。", recommendation="运行 python3 tools/doctor.py 并补齐对应配置。")
    if not health.get("speechRecognitionConfigured"):
        issue(issues, "warning", "service.speech_unavailable", "system", "preflight", "语音识别未配置，依赖对白的内容检索可能漏检。", recommendation="配置 SenseVoice 或 Whisper 后再验证对白检索。")
    return issues


def validate_handoff(
    parent: dict[str, Any], child: dict[str, Any], action: str,
    *, from_mode: str, to_mode: str,
) -> list[Issue]:
    issues: list[Issue] = []
    parent_id = str(parent.get("id") or "")
    child_id = str(child.get("id") or "")
    handoff = child.get("handoff") if isinstance(child.get("handoff"), dict) else {}
    if action != "job-handoff" or not child_id or child_id == parent_id:
        issue(
            issues, "error", "conversation.handoff_missing", "conversation", "handoff",
            "对话中的任务模式切换没有创建独立子任务。",
            evidence={"action": action, "parentJobId": parent_id, "returnedJobId": child_id},
            recommendation="模式切换应复用源素材创建子任务，并返回 job-handoff。",
        )
        return issues
    from_task_mode = TASK_MODES.get(from_mode, from_mode)
    to_task_mode = TASK_MODES.get(to_mode, to_mode)
    if str(child.get("taskMode") or "") != to_task_mode:
        issue(issues, "error", "conversation.target_mode_mismatch", "conversation", "handoff", "对话切换后的任务类型不正确。", evidence={"expected": to_task_mode, "actual": child.get("taskMode")}, recommendation="工作流切换结果应显式写入正确的 taskMode。")
    actual_workflow = str(child.get("workflowKind") or "")
    if to_mode in WORKFLOWS and actual_workflow != to_mode:
        issue(issues, "error", "conversation.target_workflow_mismatch", "conversation", "handoff", "切换后的产品工作流不正确。", evidence={"expected": to_mode, "actual": actual_workflow}, recommendation="同一 taskMode 下必须用 workflowKind 区分内容、人物和说话人流程。")
    expected = {
        "fromJobId": parent_id,
        "toJobId": child_id,
        "fromTaskMode": from_task_mode,
        "toTaskMode": to_task_mode,
    }
    if from_mode in WORKFLOWS:
        expected["fromWorkflowKind"] = from_mode
    if to_mode in WORKFLOWS:
        expected["toWorkflowKind"] = to_mode
    mismatches = {
        key: {"expected": value, "actual": handoff.get(key)}
        for key, value in expected.items()
        if str(handoff.get(key) or "") != value
    }
    if mismatches:
        issue(issues, "error", "conversation.handoff_contract_broken", "conversation", "handoff", "子任务的 handoff 元数据不完整或指向错误。", evidence={"mismatches": mismatches}, recommendation="在父子任务保存完成后原子登记双向 handoff。")
    inherited = [
        value for value in child.get("messages") or []
        if isinstance(value, dict) and value.get("inherited")
    ]
    if not inherited:
        issue(issues, "warning", "conversation.history_not_inherited", "conversation", "handoff", "切换任务后没有保留此前对话历史。", recommendation="复制历史消息并标记 originJobId、originTaskMode 和 inherited。")
    if to_mode == "highlight" and child.get("contentSearch"):
        issue(issues, "error", "conversation.content_state_leaked", "conversation", "handoff", "内容检索候选泄漏到了新的高光任务。", recommendation="子任务只继承消息和素材，不继承另一模式的候选状态。")
    return issues


def summarize(report: dict[str, Any], output_path: Path) -> None:
    all_issues = [value for flow in report.get("flows") or [] for value in flow.get("issues") or []]
    all_issues.extend(report.get("preflightIssues") or [])
    all_issues.extend((report.get("conversation") or {}).get("issues") or [])
    counts = {severity: sum(value.get("severity") == severity for value in all_issues) for severity in SEVERITY_ORDER}
    print("\nClipTalk 四模式工作流验证结果")
    for flow in report.get("flows") or []:
        icon = "✓" if flow.get("passed") else "×"
        state = (flow.get("finalState") or {}).get("status") or "未创建"
        print(f"{icon} {flow['flow']}：{state}；任务 {flow.get('jobId') or '-'}；问题 {len(flow.get('issues') or [])} 个")
    print(f"汇总：{counts['error']} 个错误，{counts['warning']} 个警告，{counts['info']} 个提示")
    for value in sorted(all_issues, key=lambda item: SEVERITY_ORDER.get(str(item.get("severity")), 9)):
        icon = {"error": "×", "warning": "!", "info": "·"}.get(value.get("severity"), "·")
        print(f"{icon} [{value.get('flow')}/{value.get('phase')}] {value.get('message')}")
    print(f"完整报告：{output_path.resolve()}")
    print("验证任务会保留在项目中，脚本没有删除源文件、任务或输出。")


def main(argv: Iterable[str] | None = None) -> int:
    settings = Settings.from_environment()
    parser = parser_for(settings)
    args = parser.parse_args(list(argv) if argv is not None else None)
    video = args.video.expanduser().resolve()
    if not video.is_file():
        parser.error(f"视频不存在：{video}")
    if video.stat().st_size <= 0:
        parser.error(f"视频为空：{video}")
    if args.phase_timeout <= 0 or args.request_timeout <= 0 or args.poll_interval <= 0 or args.stall_seconds <= 0:
        parser.error("timeout、poll interval 和 stall seconds 必须大于 0")
    if not 1 <= args.max_selected <= 8:
        parser.error("--max-selected 必须在 1–8 之间")
    if not 0 <= args.expected_speaker_count <= 12:
        parser.error("--expected-speaker-count 必须在 0–12 之间")
    workflows = list(dict.fromkeys(args.workflows))
    instructions = {
        "highlight": args.highlight_instruction,
        "content_search": args.search_query,
        "person_edit": args.person_instruction,
        "speaker_edit": "识别本视频中的说话人",
    }
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_path = args.output or ROOT / "test-results" / f"workflow-validation-{timestamp}.json"
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    token = args.token.strip() or local_default_token(args.base_url, settings)
    client = WorkflowClient(args.base_url, token, args.request_timeout)
    started_at = now_iso()
    report: dict[str, Any] = {
        "schemaVersion": 2,
        "startedAt": started_at,
        "finishedAt": "",
        "passed": False,
        "service": {"baseUrl": args.base_url.rstrip("/")},
        "video": {"filename": video.name, "sizeBytes": video.stat().st_size},
        "configuration": {
            "phaseTimeoutSeconds": args.phase_timeout,
            "pollIntervalSeconds": args.poll_interval,
            "stallSeconds": args.stall_seconds,
            "maxSelected": args.max_selected,
            "analysisOnly": args.analysis_only,
            "forceReanalyze": not args.reuse_analysis,
            "mode": args.mode,
            "workflows": workflows,
            "expectedSpeakerCount": args.expected_speaker_count or None,
            "speakerQuery": args.speaker_query,
        },
        "preflightIssues": [],
        "conversation": {"mode": args.mode, "handoffs": [], "issues": []},
        "flows": [],
    }
    interrupted = False
    try:
        health = client.health()
        report["service"]["health"] = {
            key: health.get(key) for key in (
                "ok", "service", "visionConfigured", "visionProviderLabel", "visionModel",
                "llmConfigured", "speechRecognitionConfigured", "speechEngine", "ffmpeg", "ffprobe",
            )
        }
        preflight = health_issues(health)
        report["preflightIssues"] = [asdict(value) for value in preflight]
        if any(value.severity == "error" for value in preflight):
            print("预检发现阻断项；仍将尝试所选流程，以收集实际 API 错误。", flush=True)
        runner = WorkflowRunner(
            client,
            video=video,
            poll_interval=args.poll_interval,
            phase_timeout=args.phase_timeout,
            stall_seconds=args.stall_seconds,
            max_selected=args.max_selected,
            analysis_only=args.analysis_only,
            force_reanalyze=not args.reuse_analysis,
        )
        if args.mode == "independent":
            report["flows"] = [
                runner.run_flow(
                    workflow, instructions[workflow],
                    expected_speaker_count=args.expected_speaker_count,
                    speaker_query=args.speaker_query,
                )
                for workflow in workflows
            ]
        else:
            root_workflow = "content_search" if "content_search" in workflows else workflows[0]
            root_result = runner.run_flow(
                root_workflow, instructions[root_workflow],
                expected_speaker_count=args.expected_speaker_count,
                speaker_query=args.speaker_query,
            )
            report["flows"].append(root_result)
            parent_id = str(root_result.get("jobId") or "")
            if parent_id:
                for workflow in (value for value in workflows if value != root_workflow):
                    try:
                        parent = client.get_job(parent_id)
                        response = client.create_same_source_task(
                            parent_id, workflow, instructions[workflow], args.expected_speaker_count,
                            analysis_only=args.analysis_only,
                        )
                        child = response.get("job") if isinstance(response.get("job"), dict) else {}
                        report["conversation"]["handoffs"].append({
                            "action": response.get("action"),
                            "mechanism": "same-source-task",
                            "fromJobId": parent_id,
                            "toJobId": child.get("id"),
                            "fromTaskMode": parent.get("taskMode"),
                            "toTaskMode": child.get("taskMode"),
                            "fromWorkflowKind": parent.get("workflowKind"),
                            "toWorkflowKind": child.get("workflowKind"),
                        })
                        handoff_problems = validate_handoff(
                            parent, child, str(response.get("action") or ""),
                            from_mode=root_workflow, to_mode=workflow,
                        )
                        report["conversation"]["issues"].extend(
                            asdict(value) for value in handoff_problems
                        )
                        if not any(value.severity == "error" for value in handoff_problems):
                            report["flows"].append(runner.run_flow(
                                workflow, instructions[workflow], existing_job=child,
                                expected_speaker_count=args.expected_speaker_count,
                                speaker_query=args.speaker_query,
                            ))
                    except (ApiFailure, RuntimeError) as error:
                        problems: list[Issue] = []
                        issue(
                            problems, "error", "conversation.switch_failed", "conversation", "handoff",
                            f"从 {root_workflow} 切换到 {workflow} 失败：{error}",
                            evidence={"parentJobId": parent_id, "targetWorkflow": workflow, "error": str(error)},
                            recommendation="检查同源任务创建、源素材复用和父子任务登记。",
                        )
                        report["conversation"]["issues"].extend(asdict(value) for value in problems)
            else:
                problems = []
                issue(problems, "error", "conversation.no_parent_job", "conversation", "handoff", "初始任务未创建，无法验证同一素材中的模式切换。", recommendation="先修复初始任务创建错误。")
                report["conversation"]["issues"].extend(
                    asdict(value) for value in problems
                )
    except (ApiFailure, RuntimeError) as error:
        issue_list: list[Issue] = []
        issue(issue_list, "error", "service.unreachable", "system", "preflight", f"无法完成服务预检：{error}", evidence={"error": str(error)}, recommendation="确认服务已启动、端口正确且访问令牌有效。")
        report["preflightIssues"].extend(asdict(value) for value in issue_list)
    except KeyboardInterrupt:
        interrupted = True
        issue_list = []
        issue(
            issue_list, "error", "run.interrupted", "system", "execution",
            "验证被用户中断，当前报告不代表流程通过。",
            recommendation="确认服务和任务状态后重新运行；已创建的任务仍会保留。",
        )
        report["preflightIssues"].extend(asdict(value) for value in issue_list)
    finally:
        client.close()
        report["finishedAt"] = now_iso()
        all_issues = [
            *report["preflightIssues"],
            *((report.get("conversation") or {}).get("issues") or []),
            *(value for flow in report["flows"] for value in flow.get("issues") or []),
        ]
        has_errors = any(value.get("severity") == "error" for value in all_issues)
        has_warnings = any(value.get("severity") == "warning" for value in all_issues)
        report["summary"] = {
            "errors": sum(value.get("severity") == "error" for value in all_issues),
            "warnings": sum(value.get("severity") == "warning" for value in all_issues),
            "info": sum(value.get("severity") == "info" for value in all_issues),
        }
        report["passed"] = not has_errors and not (args.fail_on_warning and has_warnings)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        summarize(report, output_path)
    if interrupted:
        return 130
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
