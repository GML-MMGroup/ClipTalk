from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .editing_techniques import composition_schedule


EDIT_SESSION_SCHEMA_VERSION = 2
EDIT_SESSION_SPEEDS = (0.5, 0.75, 1.0, 1.1, 1.25, 1.5, 2.0)
EDIT_SESSION_TRANSITIONS = {"cut", "dissolve", "fade_black"}
EDIT_SESSION_AUDIO_BRIDGES = {"none", "j_cut", "l_cut"}
MIN_EDIT_CLIP_SECONDS = 0.25
EDIT_PROPOSAL_OPERATION_TYPES = frozenset({
    "insert_clip", "delete_clips", "trim_clip", "split_clip", "reorder_clips",
    "update_clip", "update_clips", "set_subtitle", "add_marker",
})


class EditSessionError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _duration(start: float, end: float, rate: float = 1.0) -> float:
    return round(max(0.0, float(end) - float(start)) / max(0.01, float(rate)), 3)


def _find_version(job: dict[str, Any], version_id: str) -> dict[str, Any]:
    version = next(
        (item for item in job.get("outputVersions") or [] if str(item.get("id")) == str(version_id)),
        None,
    )
    if not version:
        raise EditSessionError("成片版本不存在")
    return version


def _find_output(version: dict[str, Any], filename: str | None) -> dict[str, Any]:
    outputs = [item for item in version.get("outputs") or [] if isinstance(item, dict)]
    if filename:
        output = next((item for item in outputs if str(item.get("filename")) == str(filename)), None)
        if not output:
            raise EditSessionError("该版本中的成片不存在")
        return output
    if len(outputs) != 1:
        raise EditSessionError("该版本包含多条视频，请先选择要编辑的成片")
    return outputs[0]


def _compact_clip(
    segment: dict[str, Any], index: int, workflow_kind: str, *, source_kind: str = "output_segment",
) -> dict[str, Any]:
    start = round(float(segment.get("start") or 0), 3)
    end = round(float(segment.get("end") or 0), 3)
    rate = float(segment.get("playbackRate") or 1)
    segment_id = str(segment.get("id") or segment.get("candidateId") or f"segment_{index}")
    title = str(
        segment.get("title")
        or segment.get("shotTitle")
        or segment.get("role")
        or segment.get("chapterTitle")
        or f"片段 {index + 1}"
    )[:100]
    return {
        "id": _id("edit_clip"),
        "sourceRef": {"kind": source_kind, "id": segment_id},
        "title": title,
        "sourceStart": start,
        "sourceEnd": end,
        "duration": _duration(start, end, rate),
        "playbackRate": rate,
        "transitionIn": copy.deepcopy(segment.get("transitionIn") or {"type": "cut", "duration": 0}),
        "audioBridge": copy.deepcopy(segment.get("audioBridge") or {"type": "none", "duration": 0}),
        "audioGain": round(max(0.0, min(2.0, float(segment.get("audioGain", 1.0)))), 3),
        "muted": bool(segment.get("muted")),
        "audioFadeIn": round(max(0.0, min(0.35, float(segment.get("audioFadeIn", .06)))), 3),
        "audioFadeOut": round(max(0.0, min(0.35, float(segment.get("audioFadeOut", .06)))), 3),
        "boundaryConfidence": round(max(0.0, min(1.0, float(
            segment.get("boundaryConfidence") or (segment.get("quality") or {}).get("boundaryConfidence") or 1.0
        ))), 3),
        "origin": {
            "workflowKind": workflow_kind,
            "eventId": str(segment.get("eventGroupId") or segment.get("eventId") or ""),
            "candidateId": str(segment.get("candidateId") or ""),
            "matchId": str((segment.get("contributingMatchIds") or [""])[0] or ""),
        },
    }


def _session_state(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "clips": copy.deepcopy(session.get("clips") or []),
        "subtitleEnabled": bool(session.get("subtitleEnabled")),
        "subtitleDraftId": session.get("subtitleDraftId"),
        "subtitleStyle": str(session.get("subtitleStyle") or "clean"),
        "disabledCutawayIds": list(session.get("disabledCutawayIds") or []),
        "markers": copy.deepcopy(session.get("markers") or []),
    }


def _restore_state(session: dict[str, Any], state: dict[str, Any]) -> None:
    for key in ("clips", "subtitleEnabled", "subtitleDraftId", "subtitleStyle", "disabledCutawayIds", "markers"):
        session[key] = copy.deepcopy(state.get(key))


def _invalidate_preview(session: dict[str, Any]) -> None:
    if session.get("previewStatus") in {"ready", "rendering", "failed"} or session.get("previewFingerprint"):
        session["previewStatus"] = "stale"
    session["previewError"] = None


def _schedule_for_clips(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments = [
        {
            "id": clip.get("id"),
            "start": clip.get("sourceStart"),
            "end": clip.get("sourceEnd"),
            "playbackRate": clip.get("playbackRate") or 1,
            "transitionIn": clip.get("transitionIn") or {"type": "cut", "duration": 0},
        }
        for clip in clips
    ]
    schedule = composition_schedule(segments)
    return [
        {
            "clipId": str(clips[index].get("id") or ""),
            "outputStart": float(item.get("outputStart") or 0),
            "outputEnd": float(item.get("outputEnd") or 0),
            "effectiveDuration": float(item.get("effectiveDuration") or 0),
            "transitionOverlap": float(item.get("transitionOverlap") or 0),
        }
        for index, item in enumerate(schedule)
    ]


def edit_session_preflight(
    session: dict[str, Any], job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clips = [item for item in session.get("clips") or [] if isinstance(item, dict)]
    issues: list[dict[str, Any]] = []
    for index, clip in enumerate(clips):
        source_duration = float(clip.get("sourceEnd") or 0) - float(clip.get("sourceStart") or 0)
        if source_duration < MIN_EDIT_CLIP_SECONDS:
            issues.append({"severity": "error", "code": "clip_too_short", "clipId": clip.get("id"), "message": f"片段 {index + 1} 短于 {MIN_EDIT_CLIP_SECONDS:.2f} 秒"})
        transition = clip.get("transitionIn") if isinstance(clip.get("transitionIn"), dict) else {}
        transition_duration = float(transition.get("duration") or 0)
        effective_duration = _duration(float(clip.get("sourceStart") or 0), float(clip.get("sourceEnd") or 0), float(clip.get("playbackRate") or 1))
        if index and transition_duration >= min(effective_duration, float(clips[index - 1].get("duration") or 0)):
            issues.append({"severity": "error", "code": "transition_too_long", "clipId": clip.get("id"), "message": f"片段 {index + 1} 的转场长于相邻片段"})
        if float(clip.get("playbackRate") or 1) != 1:
            issues.append({"severity": "info", "code": "speed_changed", "clipId": clip.get("id"), "message": f"片段 {index + 1} 使用 {float(clip.get('playbackRate') or 1):g}× 速度"})
        if bool(clip.get("muted")):
            issues.append({"severity": "info", "code": "muted", "clipId": clip.get("id"), "message": f"片段 {index + 1} 已静音"})
        if float(clip.get("boundaryConfidence", 1.0) or 0) < .6:
            issues.append({"severity": "warning", "code": "uncertain_action_boundary", "clipId": clip.get("id"), "message": f"片段 {index + 1} 的动作边界置信度较低，建议先预览"})
        if index:
            previous = clips[index - 1]
            source_gap = abs(float(clip.get("sourceStart") or 0) - float(previous.get("sourceEnd") or 0))
            bridge = str((clip.get("audioBridge") or {}).get("type") or "none")
            if source_gap > 20 and not clip.get("muted") and not previous.get("muted") and bridge == "none":
                issues.append({"severity": "warning", "code": "audio_jump", "clipId": clip.get("id"), "message": f"片段 {index} 与 {index + 1} 的源声音跨度较大，建议试听衔接"})
            previous_event = str((previous.get("origin") or {}).get("eventId") or "")
            current_event = str((clip.get("origin") or {}).get("eventId") or "")
            if previous_event and current_event and previous_event != current_event and str(transition.get("type") or "cut") != "cut":
                issues.append({"severity": "warning", "code": "cross_event_transition", "clipId": clip.get("id"), "message": f"片段 {index + 1} 跨事件使用柔和转场，可能弱化叙事切点"})
    if not clips:
        issues.append({"severity": "error", "code": "empty_timeline", "message": "成片时间线为空"})
    if session.get("subtitleEnabled") and not session.get("subtitleDraftId"):
        issues.append({"severity": "warning", "code": "subtitle_unconfirmed", "message": "字幕已开启，但还没有确认的字幕草稿"})
    for left_index, left in enumerate(clips):
        for right in clips[left_index + 1:]:
            overlap = max(0.0, min(float(left.get("sourceEnd") or 0), float(right.get("sourceEnd") or 0)) - max(float(left.get("sourceStart") or 0), float(right.get("sourceStart") or 0)))
            shorter = min(
                float(left.get("sourceEnd") or 0) - float(left.get("sourceStart") or 0),
                float(right.get("sourceEnd") or 0) - float(right.get("sourceStart") or 0),
            )
            if shorter > 0 and overlap / shorter >= .8:
                issues.append({"severity": "warning", "code": "duplicate_source", "clipId": right.get("id"), "message": "时间线中存在高度重复的源片段"})
                break
    event_sequence = [str((item.get("origin") or {}).get("eventId") or "") for item in clips]
    compact_events = [value for index, value in enumerate(event_sequence) if value and (index == 0 or value != event_sequence[index - 1])]
    if len(compact_events) != len(set(compact_events)):
        issues.append({"severity": "warning", "code": "event_interleave", "message": "同一事件被其他事件切开后再次出现，建议确认叙事顺序"})
    transcript = list(((job or {}).get("speechAnalysis") or {}).get("segments") or [])
    for index, clip in enumerate(clips):
        for boundary_name, boundary in (("入点", float(clip.get("sourceStart") or 0)), ("出点", float(clip.get("sourceEnd") or 0))):
            if any(
                float(item.get("start") or 0) + .12 < boundary < float(item.get("end") or 0) - .12
                and str(item.get("text") or "").strip()
                for item in transcript if isinstance(item, dict)
            ):
                issues.append({"severity": "warning", "code": "speech_truncation", "clipId": clip.get("id"), "message": f"片段 {index + 1} 的{boundary_name}落在一句话中间"})
                break
    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    acknowledged = {str(value) for value in session.get("acknowledgedWarningCodes") or []}
    return {
        "ready": not errors,
        "errorCount": len(errors), "warningCount": len(warnings),
        "unacknowledgedWarningCount": sum(str(item.get("code") or "") not in acknowledged for item in warnings),
        "acknowledgedWarningCodes": sorted(acknowledged),
        "infoCount": len(issues) - len(errors) - len(warnings),
        "issues": issues,
    }


def refresh_edit_session(session: dict[str, Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
    session["schemaVersion"] = EDIT_SESSION_SCHEMA_VERSION
    clips = session.get("clips") if isinstance(session.get("clips"), list) else []
    for index, clip in enumerate(clips):
        clip["order"] = index
        clip["sourceStart"] = round(float(clip.get("sourceStart") or 0), 3)
        clip["sourceEnd"] = round(float(clip.get("sourceEnd") or 0), 3)
        clip["duration"] = _duration(clip["sourceStart"], clip["sourceEnd"], float(clip.get("playbackRate") or 1))
        clip["audioGain"] = round(max(0.0, min(2.0, float(clip.get("audioGain", 1.0)))), 3)
        clip["muted"] = bool(clip.get("muted"))
        clip["audioFadeIn"] = round(max(0.0, min(.35, float(clip.get("audioFadeIn", .06)))), 3)
        clip["audioFadeOut"] = round(max(0.0, min(.35, float(clip.get("audioFadeOut", .06)))), 3)
    session.setdefault("markers", [])
    schedule = _schedule_for_clips(clips)
    session["schedule"] = schedule
    session["duration"] = round(max((float(item["outputEnd"]) for item in schedule), default=0.0), 3)
    session["clipCount"] = len(clips)
    session["canUndo"] = bool(session.get("undo"))
    session["canRedo"] = bool(session.get("redo"))
    session["preflight"] = edit_session_preflight(session, job)
    return session


def public_edit_session(session: dict[str, Any]) -> dict[str, Any]:
    refresh_edit_session(session)
    return {
        key: copy.deepcopy(value)
        for key, value in session.items()
        if key not in {"undo", "redo", "previewPath"}
    }


def create_or_resume_edit_session(
    job: dict[str, Any], *, version_id: str, output_filename: str | None = None,
) -> tuple[dict[str, Any], bool]:
    version = _find_version(job, version_id)
    output = _find_output(version, output_filename)
    filename = str(output.get("filename") or "")
    for session in reversed(job.get("editSessions") or []):
        if (
            str(session.get("baseVersionId")) == str(version_id)
            and str(session.get("baseOutputFilename")) == filename
            and str(session.get("status") or "draft") in {"draft", "rendered", "failed"}
        ):
            return refresh_edit_session(session), False
    workflow_kind = str(job.get("workflowKind") or (job.get("request") or {}).get("workflowKind") or "highlight")
    clips = [
        _compact_clip(item, index, workflow_kind)
        for index, item in enumerate(output.get("segments") or [])
        if float(item.get("end") or 0) > float(item.get("start") or 0)
    ]
    if not clips:
        raise EditSessionError("该成片没有可编辑的片段信息")
    now = _now_iso()
    session = {
        "schemaVersion": EDIT_SESSION_SCHEMA_VERSION,
        "id": _id("edit_session"),
        "jobId": str(job.get("id") or ""),
        "baseVersionId": str(version_id),
        "baseVersionNumber": int(version.get("number") or 1),
        "baseOutputFilename": filename,
        "workflowKind": workflow_kind,
        "title": f"基于 V{int(version.get('number') or 1)} 精剪",
        "status": "draft",
        "revision": 0,
        "clips": clips,
        "cutaways": copy.deepcopy(output.get("cutaways") or []),
        "disabledCutawayIds": [],
        "markers": [],
        "subtitleEnabled": bool(output.get("subtitleMode") == "burn"),
        "subtitleDraftId": None,
        "subtitleStyle": str(output.get("subtitleStyle") or "clean"),
        "undo": [],
        "redo": [],
        "createdAt": now,
        "updatedAt": now,
    }
    refresh_edit_session(session)
    job.setdefault("editSessions", []).append(session)
    job["activeEditSessionId"] = session["id"]
    return session, True


def _content_search_records(job: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in [
        job.get("contentSearch"),
        *(job.get("contentSearchRecords") or []),
        *(job.get("contentSearchHistory") or []),
    ]:
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("id") or "")
        key = record_id or f"anonymous:{id(record)}"
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
    return records


def create_or_resume_content_edit_session(
    job: dict[str, Any], *, search_id: str, selected_match_ids: list[str], order_mode: str = "source",
) -> tuple[dict[str, Any], bool]:
    search = next(
        (record for record in _content_search_records(job) if str(record.get("id") or "") == str(search_id)),
        None,
    )
    if not search:
        raise EditSessionError("内容检索结果不存在")
    requested_ids = [str(value) for value in selected_match_ids if str(value)]
    requested_ids = list(dict.fromkeys(requested_ids))
    if not requested_ids:
        raise EditSessionError("请先选择要精剪的内容片段")
    lookup = {str(item.get("id") or ""): item for item in search.get("candidates") or []}
    missing = [match_id for match_id in requested_ids if match_id not in lookup]
    if missing:
        raise EditSessionError("部分所选内容片段已失效，请刷新后重新选择")
    ordered_matches = [lookup[match_id] for match_id in requested_ids]
    if str(order_mode or "source") == "source":
        ordered_matches.sort(key=lambda item: (float(item.get("start") or 0), float(item.get("end") or 0)))
    source_match_ids = [str(item.get("id") or "") for item in ordered_matches]
    for session in reversed(job.get("editSessions") or []):
        if (
            str(session.get("sourceSearchId") or "") == str(search_id)
            and list(session.get("sourceMatchIds") or []) == source_match_ids
            and str(session.get("status") or "draft") in {"draft", "rendered", "failed"}
        ):
            return refresh_edit_session(session), False
    workflow_kind = str(job.get("workflowKind") or "content_search")
    clips = [
        _compact_clip(item, index, workflow_kind, source_kind="content_match")
        for index, item in enumerate(ordered_matches)
        if float(item.get("end") or 0) > float(item.get("start") or 0)
    ]
    if not clips:
        raise EditSessionError("所选内容没有可编辑的有效时间范围")
    now = _now_iso()
    session = {
        "schemaVersion": EDIT_SESSION_SCHEMA_VERSION,
        "id": _id("edit_session"),
        "jobId": str(job.get("id") or ""),
        "baseVersionId": "",
        "baseVersionNumber": 0,
        "baseOutputFilename": "",
        "sourceSearchId": str(search_id),
        "sourceMatchIds": source_match_ids,
        "workflowKind": workflow_kind,
        "title": "内容探索精剪",
        "status": "draft",
        "revision": 0,
        "clips": clips,
        "cutaways": [],
        "disabledCutawayIds": [],
        "markers": [],
        "subtitleEnabled": False,
        "subtitleDraftId": None,
        "subtitleStyle": "clean",
        "undo": [],
        "redo": [],
        "createdAt": now,
        "updatedAt": now,
    }
    refresh_edit_session(session)
    job.setdefault("editSessions", []).append(session)
    job["activeEditSessionId"] = session["id"]
    return session, True


def find_edit_session(job: dict[str, Any], session_id: str) -> dict[str, Any]:
    session = next(
        (item for item in job.get("editSessions") or [] if str(item.get("id")) == str(session_id)),
        None,
    )
    if not session:
        raise EditSessionError("编辑草稿不存在")
    return session


def _clip_lookup(session: dict[str, Any], clip_id: str) -> dict[str, Any]:
    clip = next((item for item in session.get("clips") or [] if str(item.get("id")) == str(clip_id)), None)
    if not clip:
        raise EditSessionError("编辑片段不存在")
    return clip


def _validate_range(job: dict[str, Any], start: Any, end: Any) -> tuple[float, float]:
    try:
        start_value = round(float(start), 3)
        end_value = round(float(end), 3)
    except (TypeError, ValueError) as error:
        raise EditSessionError("片段时间范围无效") from error
    source_duration = float((job.get("videoInfo") or {}).get("duration") or 0)
    if start_value < 0 or end_value > source_duration + .01 or end_value - start_value < MIN_EDIT_CLIP_SECONDS:
        raise EditSessionError(f"片段必须位于源视频内，且至少保留 {MIN_EDIT_CLIP_SECONDS:.2f} 秒")
    return start_value, end_value


def _normalize_transition(value: Any) -> dict[str, Any]:
    transition_type = str(value or "cut")
    if transition_type not in EDIT_SESSION_TRANSITIONS:
        raise EditSessionError("不支持的转场方式")
    return {"type": transition_type, "duration": 0.35 if transition_type != "cut" else 0.0}


def _transition_with_duration(value: Any, duration: Any = None) -> dict[str, Any]:
    transition = _normalize_transition(value)
    if transition["type"] == "cut":
        return transition
    try:
        requested = float(duration) if duration is not None else transition["duration"]
    except (TypeError, ValueError):
        requested = transition["duration"]
    transition["duration"] = round(max(.08, min(.4, requested)), 3)
    return transition


def _normalize_bridge(value: Any) -> dict[str, Any]:
    bridge_type = str(value or "none")
    if bridge_type not in EDIT_SESSION_AUDIO_BRIDGES:
        raise EditSessionError("不支持的声音衔接方式")
    return {"type": bridge_type, "duration": 0.18 if bridge_type != "none" else 0.0}


def _apply_operation(job: dict[str, Any], session: dict[str, Any], operation: dict[str, Any]) -> str:
    operation_type = str(operation.get("type") or "")
    clips = session.setdefault("clips", [])
    if operation_type == "trim_clip":
        clip = _clip_lookup(session, str(operation.get("clipId") or ""))
        start, end = _validate_range(job, operation.get("sourceStart"), operation.get("sourceEnd"))
        clip.update({"sourceStart": start, "sourceEnd": end})
        session["markers"] = [
            marker for marker in session.get("markers") or []
            if str(marker.get("clipId")) != str(clip.get("id"))
            or start <= float(marker.get("sourceTime") or 0) <= end
        ]
        return f"已调整“{clip.get('title') or '片段'}”边界"
    if operation_type == "roll_trim":
        clip = _clip_lookup(session, str(operation.get("clipId") or ""))
        adjacent = _clip_lookup(session, str(operation.get("adjacentClipId") or ""))
        boundary = str(operation.get("boundary") or "")
        clip_index = clips.index(clip)
        adjacent_index = clips.index(adjacent)
        if boundary == "start" and adjacent_index != clip_index - 1:
            raise EditSessionError("入点滚动裁剪必须使用前一个相邻片段")
        if boundary == "end" and adjacent_index != clip_index + 1:
            raise EditSessionError("出点滚动裁剪必须使用后一个相邻片段")
        if boundary not in {"start", "end"}:
            raise EditSessionError("滚动裁剪方向无效")
        start, end = _validate_range(job, operation.get("sourceStart"), operation.get("sourceEnd"))
        adjacent_start, adjacent_end = _validate_range(
            job, operation.get("adjacentSourceStart"), operation.get("adjacentSourceEnd"),
        )
        clip.update({"sourceStart": start, "sourceEnd": end})
        adjacent.update({"sourceStart": adjacent_start, "sourceEnd": adjacent_end})
        changed_ids = {str(clip.get("id")), str(adjacent.get("id"))}
        ranges = {
            str(clip.get("id")): (start, end),
            str(adjacent.get("id")): (adjacent_start, adjacent_end),
        }
        session["markers"] = [
            marker for marker in session.get("markers") or []
            if str(marker.get("clipId")) not in changed_ids
            or ranges[str(marker.get("clipId"))][0] <= float(marker.get("sourceTime") or 0) <= ranges[str(marker.get("clipId"))][1]
        ]
        return "已滚动调整相邻片段边界，后续片段位置保持不变"
    if operation_type == "split_clip":
        clip = _clip_lookup(session, str(operation.get("clipId") or ""))
        split_at = round(float(operation.get("sourceTime") or 0), 3)
        start, end = float(clip["sourceStart"]), float(clip["sourceEnd"])
        if split_at - start < MIN_EDIT_CLIP_SECONDS or end - split_at < MIN_EDIT_CLIP_SECONDS:
            raise EditSessionError("切分点距离片段边界太近")
        index = clips.index(clip)
        second = copy.deepcopy(clip)
        second["id"] = _id("edit_clip")
        second["sourceStart"] = split_at
        second["title"] = f"{str(clip.get('title') or '片段')}（后半）"[:100]
        second["transitionIn"] = {"type": "cut", "duration": 0.0}
        clip["sourceEnd"] = split_at
        clips.insert(index + 1, second)
        for marker in session.get("markers") or []:
            if str(marker.get("clipId")) == str(clip.get("id")) and float(marker.get("sourceTime") or 0) >= split_at:
                marker["clipId"] = second["id"]
        return f"已在 {split_at:.2f} 秒切分片段"
    if operation_type == "delete_clips":
        ids = {str(value) for value in operation.get("clipIds") or [] if str(value)}
        if not ids:
            raise EditSessionError("请选择要删除的片段")
        previous = len(clips)
        session["clips"] = [item for item in clips if str(item.get("id")) not in ids]
        removed = previous - len(session["clips"])
        if not removed:
            raise EditSessionError("没有找到要删除的片段")
        session["markers"] = [
            marker for marker in session.get("markers") or []
            if str(marker.get("clipId") or "") not in ids
        ]
        return f"已移除 {removed} 个片段"
    if operation_type == "duplicate_clips":
        ids = [str(value) for value in operation.get("clipIds") or [] if str(value)]
        selected = [clip for clip in clips if str(clip.get("id")) in set(ids)]
        if not selected:
            raise EditSessionError("请选择要复制的片段")
        insert_at = max(clips.index(clip) for clip in selected) + 1
        duplicates = []
        for clip in selected:
            duplicate = copy.deepcopy(clip)
            duplicate["id"] = _id("edit_clip")
            duplicate["title"] = f"{str(clip.get('title') or '片段')}（副本）"[:100]
            duplicates.append(duplicate)
        clips[insert_at:insert_at] = duplicates
        operation["createdClipIds"] = [str(item["id"]) for item in duplicates]
        return f"已复制 {len(duplicates)} 个片段"
    if operation_type == "trim_to_playhead":
        clip = _clip_lookup(session, str(operation.get("clipId") or ""))
        side = str(operation.get("side") or "")
        if side not in {"left", "right"}:
            raise EditSessionError("裁切方向无效")
        split_at = round(float(operation.get("sourceTime") or 0), 3)
        start, end = float(clip["sourceStart"]), float(clip["sourceEnd"])
        if split_at - start < MIN_EDIT_CLIP_SECONDS or end - split_at < MIN_EDIT_CLIP_SECONDS:
            raise EditSessionError("播放头距离片段边界太近")
        if side == "left":
            clip["sourceStart"] = split_at
        else:
            clip["sourceEnd"] = split_at
        session["markers"] = [
            marker for marker in session.get("markers") or []
            if str(marker.get("clipId")) != str(clip.get("id"))
            or float(clip["sourceStart"]) <= float(marker.get("sourceTime") or 0) <= float(clip["sourceEnd"])
        ]
        return f"已裁掉播放头{('左' if side == 'left' else '右')}侧"
    if operation_type == "reorder_clips":
        ids = [str(value) for value in operation.get("clipIds") or []]
        lookup = {str(item.get("id")): item for item in clips}
        if len(ids) != len(clips) or len(set(ids)) != len(ids) or set(ids) != set(lookup):
            raise EditSessionError("排序必须包含当前时间线上的全部片段")
        session["clips"] = [lookup[value] for value in ids]
        return "已更新片段顺序"
    if operation_type == "insert_clip":
        start, end = _validate_range(job, operation.get("sourceStart"), operation.get("sourceEnd"))
        clip = {
            "id": _id("edit_clip"),
            "sourceRef": copy.deepcopy(operation.get("sourceRef") or {"kind": "manual_range", "id": ""}),
            "title": str(operation.get("title") or "补充片段")[:100],
            "sourceStart": start,
            "sourceEnd": end,
            "duration": _duration(start, end),
            "playbackRate": 1.0,
            "transitionIn": {"type": "cut", "duration": 0.0},
            "audioBridge": {"type": "none", "duration": 0.0},
            "audioGain": 1.0,
            "muted": False,
            "audioFadeIn": .06,
            "audioFadeOut": .06,
            "origin": {"workflowKind": str(session.get("workflowKind") or "")},
        }
        target_index = operation.get("targetIndex")
        try:
            target_index = max(0, min(len(clips), int(target_index)))
        except (TypeError, ValueError):
            target_index = len(clips)
        clips.insert(target_index, clip)
        return f"已加入“{clip['title']}”"
    if operation_type in {"update_clip", "update_clips"}:
        clip_ids = (
            [str(value) for value in operation.get("clipIds") or []]
            if operation_type == "update_clips"
            else [str(operation.get("clipId") or "")]
        )
        targets = [_clip_lookup(session, clip_id) for clip_id in clip_ids if clip_id]
        if not targets:
            raise EditSessionError("请选择要更新的片段")
        if operation.get("playbackRate") is not None:
            rate = float(operation["playbackRate"])
            if not any(abs(rate - allowed) < .001 for allowed in EDIT_SESSION_SPEEDS):
                raise EditSessionError("不支持的播放速度")
        else:
            rate = None
        for clip in targets:
            if rate is not None:
                clip["playbackRate"] = rate
            if operation.get("transitionType") is not None or operation.get("transitionDuration") is not None:
                clip["transitionIn"] = _transition_with_duration(
                    operation.get("transitionType", (clip.get("transitionIn") or {}).get("type")),
                    operation.get("transitionDuration"),
                )
            if operation.get("audioBridgeType") is not None:
                clip["audioBridge"] = _normalize_bridge(operation.get("audioBridgeType"))
            if operation.get("audioGain") is not None:
                clip["audioGain"] = round(max(0.0, min(2.0, float(operation["audioGain"]))), 3)
            if operation.get("muted") is not None:
                clip["muted"] = bool(operation["muted"])
            for key in ("audioFadeIn", "audioFadeOut"):
                if operation.get(key) is not None:
                    clip[key] = round(max(0.0, min(.35, float(operation[key]))), 3)
        return f"已更新 {len(targets)} 个片段的剪辑参数"
    if operation_type == "add_marker":
        clip = _clip_lookup(session, str(operation.get("clipId") or ""))
        source_time = round(float(operation.get("sourceTime") or 0), 3)
        if source_time < float(clip["sourceStart"]) or source_time > float(clip["sourceEnd"]):
            raise EditSessionError("标记必须位于片段范围内")
        marker = {
            "id": _id("edit_marker"), "clipId": str(clip["id"]), "sourceTime": source_time,
            "label": str(operation.get("label") or "标记")[:80], "color": str(operation.get("color") or "lime")[:20],
        }
        session.setdefault("markers", []).append(marker)
        operation["markerId"] = marker["id"]
        return "已添加时间线标记"
    if operation_type == "update_marker":
        marker = next((item for item in session.get("markers") or [] if str(item.get("id")) == str(operation.get("markerId") or "")), None)
        if not marker:
            raise EditSessionError("时间线标记不存在")
        if operation.get("label") is not None:
            marker["label"] = str(operation.get("label") or "标记")[:80]
        if operation.get("color") is not None:
            marker["color"] = str(operation.get("color") or "lime")[:20]
        return "已更新时间线标记"
    if operation_type == "delete_marker":
        marker_id = str(operation.get("markerId") or "")
        before = len(session.get("markers") or [])
        session["markers"] = [item for item in session.get("markers") or [] if str(item.get("id")) != marker_id]
        if len(session["markers"]) == before:
            raise EditSessionError("时间线标记不存在")
        return "已删除时间线标记"
    if operation_type == "set_subtitle":
        session["subtitleEnabled"] = bool(operation.get("enabled"))
        session["subtitleDraftId"] = str(operation.get("subtitleDraftId") or "") or None
        session["subtitleStyle"] = str(operation.get("subtitleStyle") or "clean")
        return "已更新字幕设置"
    if operation_type == "toggle_cutaway":
        cutaway_id = str(operation.get("cutawayId") or "")
        if not cutaway_id:
            raise EditSessionError("插入镜头编号无效")
        disabled = {str(value) for value in session.get("disabledCutawayIds") or []}
        if bool(operation.get("enabled", True)):
            disabled.discard(cutaway_id)
        else:
            disabled.add(cutaway_id)
        session["disabledCutawayIds"] = sorted(disabled)
        return "已更新插入镜头"
    raise EditSessionError("不支持的编辑操作")


def apply_edit_operation(
    job: dict[str, Any], session: dict[str, Any], *, revision: int, operation: dict[str, Any],
) -> dict[str, Any]:
    if int(session.get("revision") or 0) != int(revision):
        raise EditSessionError("编辑草稿已在其他位置更新，请刷新后重试")
    if str(session.get("status") or "draft") == "rendering":
        raise EditSessionError("当前草稿正在生成，暂时不能修改")
    before = _session_state(session)
    summary = _apply_operation(job, session, operation)
    after = _session_state(session)
    if before != after:
        session.setdefault("undo", []).append({"before": before, "after": after, "summary": summary})
        del session["undo"][:-50]
        session["redo"] = []
        session["revision"] = int(session.get("revision") or 0) + 1
        session["status"] = "draft"
        session["renderedVersionId"] = None
        session["pendingProposal"] = None
        session["updatedAt"] = _now_iso()
        _invalidate_preview(session)
    refresh_edit_session(session)
    return {"summary": summary, "session": session}


def undo_edit_session(session: dict[str, Any], revision: int) -> dict[str, Any]:
    if int(session.get("revision") or 0) != int(revision):
        raise EditSessionError("编辑草稿已更新，请刷新后重试")
    history = session.setdefault("undo", [])
    if not history:
        raise EditSessionError("没有可撤销的修改")
    entry = history.pop()
    _restore_state(session, entry["before"])
    session.setdefault("redo", []).append(entry)
    session["revision"] = int(session.get("revision") or 0) + 1
    session["status"] = "draft"
    session["updatedAt"] = _now_iso()
    _invalidate_preview(session)
    refresh_edit_session(session)
    return session


def redo_edit_session(session: dict[str, Any], revision: int) -> dict[str, Any]:
    if int(session.get("revision") or 0) != int(revision):
        raise EditSessionError("编辑草稿已更新，请刷新后重试")
    history = session.setdefault("redo", [])
    if not history:
        raise EditSessionError("没有可重做的修改")
    entry = history.pop()
    _restore_state(session, entry["after"])
    session.setdefault("undo", []).append(entry)
    session["revision"] = int(session.get("revision") or 0) + 1
    session["status"] = "draft"
    session["updatedAt"] = _now_iso()
    _invalidate_preview(session)
    refresh_edit_session(session)
    return session


def edit_session_subtitle_outputs(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"segments": [
        {
            "id": clip.get("id"),
            "start": clip.get("sourceStart"),
            "end": clip.get("sourceEnd"),
            "playbackRate": clip.get("playbackRate") or 1,
            "transitionIn": clip.get("transitionIn") or {"type": "cut", "duration": 0},
        }
        for clip in session.get("clips") or []
    ]}]


def _segment_sources(job: dict[str, Any], session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    if session.get("baseVersionId"):
        version = _find_version(job, str(session.get("baseVersionId") or ""))
        output = _find_output(version, str(session.get("baseOutputFilename") or ""))
        for item in output.get("segments") or []:
            sources[str(item.get("id") or item.get("candidateId") or "")] = item
    for group in job.get("eventGroups") or []:
        for item in [*(group.get("segments") or []), *(group.get("availableSegments") or [])]:
            sources.setdefault(str(item.get("id") or ""), item)
    for item in job.get("candidates") or []:
        candidate_key = item.get("id") or item.get("candidateId")
        if candidate_key in (None, "") and item.get("index") is not None:
            candidate_key = item.get("index")
        sources.setdefault(str(candidate_key or ""), item)
    for record in _content_search_records(job):
        for item in record.get("candidates") or []:
            sources.setdefault(str(item.get("id") or ""), item)
    return sources


def build_edit_session_render_plan(
    job: dict[str, Any], session: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not session.get("clips"):
        raise EditSessionError("时间线为空，无法生成新版本")
    sources = _segment_sources(job, session)
    segments: list[dict[str, Any]] = []
    for index, clip in enumerate(session.get("clips") or []):
        source_ref = clip.get("sourceRef") if isinstance(clip.get("sourceRef"), dict) else {}
        source = copy.deepcopy(sources.get(str(source_ref.get("id") or "")) or {})
        start, end = _validate_range(job, clip.get("sourceStart"), clip.get("sourceEnd"))
        source.update({
            "id": str(clip.get("id") or _id("edit_clip")),
            "start": start,
            "end": end,
            "duration": round(end - start, 3),
            "sourceOrder": start,
            "editOrder": index,
            "role": str(clip.get("title") or source.get("role") or "二次编辑片段")[:100],
            "playbackRate": float(clip.get("playbackRate") or 1),
            "transitionIn": copy.deepcopy(clip.get("transitionIn") or {"type": "cut", "duration": 0}),
            "audioBridge": copy.deepcopy(clip.get("audioBridge") or {"type": "none", "duration": 0}),
            "audioGain": float(clip.get("audioGain", 1.0)),
            "muted": bool(clip.get("muted")),
            "audioFadeIn": float(clip.get("audioFadeIn", .06)),
            "audioFadeOut": float(clip.get("audioFadeOut", .06)),
            "sourceDuration": round(end - start, 3),
            "effectiveDuration": _duration(start, end, float(clip.get("playbackRate") or 1)),
            "userConfirmed": True,
            "reason": str(source.get("reason") or ("用户从内容探索结果直接精剪" if session.get("sourceSearchId") else "用户基于已有成片进行二次编辑"))[:600],
            "evidence": list(source.get("evidence") or (["用户确认内容探索片段后进入精剪。"] if session.get("sourceSearchId") else ["用户从成片版本继续编辑。"])) ,
        })
        segments.append(source)
    disabled = {str(value) for value in session.get("disabledCutawayIds") or []}
    cutaways = [
        copy.deepcopy(item) for index, item in enumerate(session.get("cutaways") or [])
        if str(item.get("id") or index) not in disabled
    ]
    return segments, cutaways


def build_edit_proposal(
    job: dict[str, Any], session: dict[str, Any], *, text: str, selected_clip_ids: list[str],
    model_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content = str(text or "").strip()
    if not content:
        raise EditSessionError("请输入要修改的内容")
    selected = [str(value) for value in selected_clip_ids if str(value)]
    operations: list[dict[str, Any]] = []

    if isinstance(model_result, dict):
        valid_clip_ids = {str(item.get("id") or "") for item in session.get("clips") or []}
        for raw in model_result.get("operations") or []:
            if not isinstance(raw, dict) or str(raw.get("type") or "") not in EDIT_PROPOSAL_OPERATION_TYPES:
                continue
            operation = copy.deepcopy(raw)
            operation_type = str(operation["type"])
            if operation_type in {"trim_clip", "split_clip", "update_clip", "add_marker"}:
                if str(operation.get("clipId") or "") not in valid_clip_ids:
                    continue
            if operation_type in {"delete_clips", "update_clips"}:
                ids = [str(value) for value in operation.get("clipIds") or [] if str(value) in valid_clip_ids]
                if not ids:
                    ids = [value for value in selected if value in valid_clip_ids]
                operation["clipIds"] = list(dict.fromkeys(ids))
                if not operation["clipIds"]:
                    continue
            if operation_type == "reorder_clips":
                ids = [str(value) for value in operation.get("clipIds") or []]
                if len(ids) != len(valid_clip_ids) or set(ids) != valid_clip_ids:
                    continue
            operations.append(operation)
            if len(operations) >= 32:
                break
    structured_operations = bool(operations) and isinstance(model_result, dict)

    delete_requested = bool(re.search(r"删除|移除|去掉|删掉|不要(?:这些|所选|当前)?片段", content))
    reverse_requested = bool(re.search(r"倒序|反向排列", content))
    source_order_requested = bool(re.search(r"源时间|原视频顺序|时间顺序", content))
    normal_speed_requested = bool(re.search(r"正常速度|恢复原速|原速播放", content))
    speed_match = re.search(
        r"(?:(\d+(?:\.\d+)?)\s*(?:倍|[x×])|(?:[x×])\s*(\d+(?:\.\d+)?))",
        content, re.IGNORECASE,
    )
    speed_requested = bool(
        normal_speed_requested or speed_match or re.search(r"加速|倍速|播放速度", content)
    )
    transition_requested = bool(re.search(r"叠化|淡黑|硬切|取消转场", content))

    if not structured_operations and reverse_requested and source_order_requested:
        raise EditSessionError("倒序与按源时间排序互相冲突，请只保留一种排序要求")
    if not structured_operations and delete_requested and (speed_requested or transition_requested):
        raise EditSessionError("不能同时删除并调整同一批所选片段；请先完成删除，再选择要调整的片段")

    if not structured_operations and delete_requested:
        if not selected:
            raise EditSessionError("请先选择要移除的片段")
        operations.append({"type": "delete_clips", "clipIds": selected})

    if not structured_operations and speed_requested:
        if not selected:
            raise EditSessionError("请先选择要调整速度的片段")
        raw_rate = next((value for value in (speed_match.groups() if speed_match else ()) if value), None)
        rate = 1.0 if normal_speed_requested else float(raw_rate) if raw_rate else 1.25
        if not any(abs(rate - allowed) < .001 for allowed in EDIT_SESSION_SPEEDS):
            raise EditSessionError("播放速度仅支持 0.5、0.75、1、1.1、1.25、1.5 或 2 倍")
        operations.extend({"type": "update_clip", "clipId": value, "playbackRate": rate} for value in selected)

    if not structured_operations and transition_requested:
        if not selected:
            raise EditSessionError("请先选择要调整转场的片段")
        transition = "dissolve" if "叠化" in content else "fade_black" if "淡黑" in content else "cut"
        operations.extend({"type": "update_clip", "clipId": value, "transitionType": transition} for value in selected)

    remaining_clips = [
        item for item in session.get("clips") or []
        if not delete_requested or str(item.get("id")) not in set(selected)
    ]
    if not structured_operations and reverse_requested:
        operations.append({"type": "reorder_clips", "clipIds": [str(item.get("id")) for item in reversed(remaining_clips)]})
    elif not structured_operations and source_order_requested:
        ordered = sorted(remaining_clips, key=lambda item: float(item.get("sourceStart") or 0))
        operations.append({"type": "reorder_clips", "clipIds": [str(item.get("id")) for item in ordered]})

    if not operations:
        raise EditSessionError("可组合使用：删除所选、设置倍速、修改转场、倒序或按源时间排序；其他修改请使用右侧片段设置")
    preview = copy.deepcopy(session)
    before = float(refresh_edit_session(preview).get("duration") or 0)
    changes = []
    for operation in operations:
        changes.append(_apply_operation(job, preview, operation))
    refresh_edit_session(preview)
    proposal = {
        "id": _id("edit_proposal"),
        "status": "pending",
        "baseRevision": int(session.get("revision") or 0),
        "title": str((model_result or {}).get("title") or (
            "AI 编辑提案" if isinstance(model_result, dict) else "快捷编辑提案"
        ))[:80],
        "summary": str((model_result or {}).get("summary") or "；".join(changes))[:800],
        "sourceText": content[:500],
        "operations": operations,
        "preview": {
            "durationBefore": before,
            "durationAfter": float(preview.get("duration") or 0),
            "clipCountBefore": len(session.get("clips") or []),
            "clipCountAfter": len(preview.get("clips") or []),
            "operationCount": len(operations),
            "preflight": edit_session_preflight(preview, job),
        },
        "planner": "llm_structured_v2" if isinstance(model_result, dict) else "local_compatibility_parser",
        "createdAt": _now_iso(),
    }
    session["pendingProposal"] = proposal
    session["updatedAt"] = _now_iso()
    _invalidate_preview(session)
    return proposal


def apply_edit_proposal(job: dict[str, Any], session: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    proposal = session.get("pendingProposal") if isinstance(session.get("pendingProposal"), dict) else None
    if not proposal or str(proposal.get("id")) != str(proposal_id):
        raise EditSessionError("编辑提案不存在")
    if int(proposal.get("baseRevision") or 0) != int(session.get("revision") or 0):
        raise EditSessionError("时间线已经变化，请重新生成提案")
    before = _session_state(session)
    summaries = [_apply_operation(job, session, item) for item in proposal.get("operations") or []]
    after = _session_state(session)
    session.setdefault("undo", []).append({"before": before, "after": after, "summary": proposal.get("summary")})
    del session["undo"][:-50]
    session["redo"] = []
    session["revision"] = int(session.get("revision") or 0) + 1
    session["pendingProposal"] = None
    session["status"] = "draft"
    session["updatedAt"] = _now_iso()
    refresh_edit_session(session)
    return {"summary": "；".join(summaries), "session": session}


def cancel_edit_proposal(session: dict[str, Any], proposal_id: str) -> None:
    proposal = session.get("pendingProposal") if isinstance(session.get("pendingProposal"), dict) else None
    if not proposal or str(proposal.get("id")) != str(proposal_id):
        raise EditSessionError("编辑提案不存在")
    session["pendingProposal"] = None
    session["updatedAt"] = _now_iso()
