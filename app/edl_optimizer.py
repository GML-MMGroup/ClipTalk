from __future__ import annotations

import copy
import itertools
import math
from typing import Any

from .edit_boundaries import semantic_safe_range
from .editing_intent import candidate_requirement_alignment, evaluate_sequence_against_intent


MIN_EDL_SEGMENT_SECONDS = .2
DURATION_EPSILON = 1e-6


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _duration(segment: dict[str, Any]) -> float:
    return max(0.0, _number(segment.get("end")) - _number(segment.get("start")))


def _event_id(segment: dict[str, Any]) -> str:
    return str(segment.get("groupId") or segment.get("chapterId") or segment.get("eventId") or "")


def _candidate_id(segment: dict[str, Any]) -> str:
    # The edit-segment id identifies one concrete selectable source range.
    # Several physical shots may legitimately share a semantic candidate id,
    # so preferring candidateId would collapse them in the final candidate map.
    return str(segment.get("id") or segment.get("candidateId") or "")


def _range_for_minimum(candidate: dict[str, Any], start: float, end: float, minimum: float) -> tuple[float, float]:
    left = _number(candidate.get("start"), start)
    right = max(left, _number(candidate.get("end"), end))
    available = right - left
    keep = min(available, max(.35, minimum))
    if end - start >= keep - .01:
        return start, end
    peak_start = max(left, min(right, _number(candidate.get("peakStart"), start)))
    peak_end = max(peak_start, min(right, _number(candidate.get("peakEnd"), end)))
    center = (peak_start + peak_end) / 2 if peak_end > peak_start else (start + end) / 2
    expanded_start = max(left, min(right - keep, center - keep / 2))
    return expanded_start, expanded_start + keep


def _merge_overlaps(
    segments: list[dict[str, Any]], *, order_mode: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not segments:
        return [], []
    ordered = (
        sorted(segments, key=lambda item: (_number(item.get("start")), _number(item.get("end"))))
        if order_mode == "source" else
        sorted(segments, key=lambda item: _number(item.get("editOrder")))
    )
    merged: list[dict[str, Any]] = []
    log: list[dict[str, Any]] = []
    for source in ordered:
        item = copy.deepcopy(source)
        item.setdefault(
            "contributingEventIds",
            list(item.get("contributingChapterIds") or ([_event_id(item)] if _event_id(item) else [])),
        )
        overlapping_index = next((
            index for index, previous in enumerate(merged)
            if max(_number(item.get("start")), _number(previous.get("start")))
            < min(_number(item.get("end")), _number(previous.get("end"))) - .01
        ), None)
        if overlapping_index is None:
            merged.append(item)
            continue
        previous = merged[overlapping_index]
        previous_end = _number(previous.get("end"))
        previous["end"] = round(max(previous_end, _number(item.get("end"))), 3)
        previous["start"] = round(min(_number(previous.get("start")), _number(item.get("start"))), 3)
        previous["duration"] = round(_duration(previous), 3)
        for event_id in item.get("contributingEventIds") or []:
            if event_id and event_id not in previous["contributingEventIds"]:
                previous["contributingEventIds"].append(event_id)
        log.append({
            "action": "merged_overlap", "keptSegmentId": _candidate_id(previous),
            "mergedSegmentId": _candidate_id(item), "resultStart": previous["start"],
            "resultEnd": previous["end"], "reason": "源区间重叠，合并为连续范围",
        })
    return merged, log


def _select_duration_subset(
    segments: list[dict[str, Any]], candidate_map: dict[str, dict[str, Any]],
    *, target: float, upper_limit: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if sum(_duration(item) for item in segments) <= upper_limit + .01:
        return segments, []
    best: tuple[float, tuple[int, ...]] | None = None
    if len(segments) <= 16:
        for count in range(1, len(segments) + 1):
            for indices in itertools.combinations(range(len(segments)), count):
                chosen = [segments[index] for index in indices]
                duration = sum(_duration(item) for item in chosen)
                if duration > upper_limit + .01:
                    continue
                events = {_event_id(item) for item in chosen if _event_id(item)}
                quality = sum(_number(
                    candidate_map.get(_candidate_id(item), item).get("editorialScore"),
                    _number(candidate_map.get(_candidate_id(item), item).get("score"), 50),
                ) for item in chosen)
                essential = sum(bool(item.get("essential")) for item in chosen)
                roles = {str(item.get("storyFunction") or item.get("role") or "") for item in chosen}
                event_capacity = max(1, min(4, round(target / 20.0)))
                event_switches = sum(
                    bool(_event_id(left) and _event_id(right) and _event_id(left) != _event_id(right))
                    for left, right in zip(chosen, chosen[1:])
                )
                score = (
                    min(len(events), event_capacity) * 5.0
                    - max(0, len(events) - event_capacity) * 14.0
                    + quality * .11 + essential * 4.0 + min(5, len(roles)) * 2.0
                    - event_switches * 2.5 - abs(target - duration) * 2.4
                    - (30.0 if duration < target * .55 else 0.0)
                )
                key = (score, indices)
                if best is None or key > best:
                    best = key
    if best is None:
        chosen = [max(segments, key=lambda item: (
            _number(candidate_map.get(_candidate_id(item), item).get("score"), 50) - _duration(item) * .3,
            -_duration(item),
        ))]
    else:
        keep = set(best[1])
        chosen = [item for index, item in enumerate(segments) if index in keep]
    chosen_ids = {id(item) for item in chosen}
    removed = [
        {
            "segmentId": _candidate_id(item), "eventId": _event_id(item),
            "duration": round(_duration(item), 3),
            "reason": "完整保留该镜头会超过动态时长上限，已整镜头移除",
        }
        for item in segments if id(item) not in chosen_ids
    ]
    return chosen, removed


def optimize_edl(
    segments: list[dict[str, Any]],
    *,
    candidate_pool: list[dict[str, Any]] | None = None,
    speech_segments: list[dict[str, Any]] | None = None,
    silences: list[dict[str, Any]] | None = None,
    target_seconds: float | None = None,
    order_mode: str = "selection",
    allow_fill: bool = True,
    video_duration: float | None = None,
    editing_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce the single validated EDL consumed by the renderer.

    Model output, duration repair and user selections all pass through this
    function. It never shortens a spoken expression merely to hit duration.
    """
    intent = editing_intent if isinstance(editing_intent, dict) else {}
    raw_pool = [copy.deepcopy(item) for item in candidate_pool or [] if isinstance(item, dict)]
    recall_origins = {"speech_signal", "visual_change", "waveform"}
    pool = [
        item for item in raw_pool
        if str(item.get("semanticStatus") or "").lower() != "recall_only"
        and str(item.get("candidateOrigin") or "").lower() not in recall_origins
    ]
    # Canonicalise only overlapping copies.  Adjacent physical shots may share
    # a semantic parent and remain useful, while a reusable anchor copied into
    # another event must not consume duration twice.
    canonical_pool: list[dict[str, Any]] = []
    for item in sorted(pool, key=lambda value: (
        -_number(value.get("editorialScore"), _number(value.get("score"))),
        _number(value.get("start")),
    )):
        semantic_id = str(item.get("semanticUnitId") or item.get("candidateId") or item.get("id") or "")
        start, end = _number(item.get("start")), _number(item.get("end"))
        if any(
            semantic_id
            and semantic_id == str(existing.get("semanticUnitId") or existing.get("candidateId") or existing.get("id") or "")
            and min(end, _number(existing.get("end"))) - max(start, _number(existing.get("start"))) > .12
            for existing in canonical_pool
        ):
            continue
        canonical_pool.append(item)
    pool = canonical_pool
    if intent:
        for item in pool:
            alignment = candidate_requirement_alignment(item, intent)
            item["requirementAlignment"] = alignment
            item["editorialScore"] = round(
                _number(item.get("score"), 50) * .65 + _number(alignment.get("score"), 50) * .35, 2,
            )
        pool = [item for item in pool if not (item.get("requirementAlignment") or {}).get("hardRejected")]
    candidate_map = {_candidate_id(item): item for item in pool if _candidate_id(item)}
    normalized: list[dict[str, Any]] = []
    boundary_adjustments: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for position, source in enumerate(segments or []):
        if not isinstance(source, dict):
            continue
        item = copy.deepcopy(source)
        candidate = candidate_map.get(_candidate_id(item), item)
        if intent and candidate_requirement_alignment(candidate, intent)["hardRejected"]:
            rejected.append({"segmentId": _candidate_id(item), "reason": "命中用户明确排除内容"})
            continue
        start = _number(item.get("start"))
        end = max(start, _number(item.get("end"), start))
        minimum = max(.35, min(
            max(.35, _number(candidate.get("end"), end) - _number(candidate.get("start"), start)),
            _number(candidate.get("minimumKeepSeconds"), .35),
        ))
        start, end = _range_for_minimum(candidate, start, end, minimum)
        safe = semantic_safe_range(
            start, end, speech_segments=speech_segments, silences=silences,
            lower_bound=max(0.0, _number(candidate.get("start"), 0.0)),
            upper_bound=_number(candidate.get("end"), video_duration or end) if candidate is not item else video_duration,
        )
        if safe["end"] - safe["start"] + DURATION_EPSILON < MIN_EDL_SEGMENT_SECONDS:
            rejected.append({"segmentId": _candidate_id(item), "reason": "安全边界后时长不足"})
            continue
        item.update({
            "start": safe["start"], "end": safe["end"],
            "duration": round(safe["end"] - safe["start"], 3),
            "editOrder": position,
            "boundarySource": safe["boundarySource"],
            "speechBoundaryStatus": safe["speechBoundaryStatus"],
        })
        if safe["boundaryAdjusted"]:
            adjustment = {
                "segmentId": _candidate_id(item), "originalStart": safe["originalStart"],
                "originalEnd": safe["originalEnd"], "safeStart": safe["start"],
                "safeEnd": safe["end"], "source": safe["boundarySource"],
            }
            item["boundaryAdjustment"] = adjustment
            boundary_adjustments.append(adjustment)
        normalized.append(item)

    normalized, overlap_log = _merge_overlaps(normalized, order_mode=order_mode)
    # Semantic duplicates can have different physical segment IDs after VLM
    # grouping. Keep the stronger one so variants never repeat the same moment
    # under two labels.
    deduplicated: list[dict[str, Any]] = []
    semantic_positions: dict[str, int] = {}
    semantic_log: list[dict[str, Any]] = []
    for item in normalized:
        # Explicit content-search selections are an authorization boundary:
        # the user chose these source ranges individually. A shared recall
        # chapter or semantic label must never silently remove one of them.
        if item.get("userConfirmed"):
            deduplicated.append(item)
            continue
        semantic_id = str(item.get("semanticUnitId") or item.get("candidateId") or "")
        if not semantic_id or semantic_id not in semantic_positions:
            if semantic_id:
                semantic_positions[semantic_id] = len(deduplicated)
            deduplicated.append(item)
            continue
        previous_index = semantic_positions[semantic_id]
        previous = deduplicated[previous_index]
        # Scene-cut splitting intentionally creates adjacent physical shots
        # under one semantic unit.  Deduplicate only competing copies of the
        # same source moment, not those complementary adjacent shots.
        if min(_number(previous.get("end")), _number(item.get("end"))) - max(
            _number(previous.get("start")), _number(item.get("start"))
        ) <= .12:
            deduplicated.append(item)
            continue
        previous_score = _number(candidate_map.get(_candidate_id(previous), previous).get("editorialScore"), _number(previous.get("score"), 0))
        current_score = _number(candidate_map.get(_candidate_id(item), item).get("editorialScore"), _number(item.get("score"), 0))
        if current_score > previous_score:
            deduplicated[previous_index] = item
            kept, removed = item, previous
        else:
            kept, removed = previous, item
        semantic_log.append({
            "action": "removed_semantic_duplicate", "semanticUnitId": semantic_id,
            "keptSegmentId": _candidate_id(kept), "removedSegmentId": _candidate_id(removed),
        })
    normalized = deduplicated
    try:
        target = float(target_seconds) if target_seconds not in (None, 0, "", "auto") else None
    except (TypeError, ValueError):
        target = None
    upper_limit = target * 1.10 if target else None

    def total() -> float:
        return round(sum(_duration(item) for item in normalized), 3)

    removal_log: list[dict[str, Any]] = []
    if upper_limit is not None:
        normalized, removal_log = _select_duration_subset(
            normalized, candidate_map, target=target, upper_limit=upper_limit,
        )

    if allow_fill and target and total() < target * .90:
        occupied = [(_number(item.get("start")), _number(item.get("end"))) for item in normalized]
        used = {_candidate_id(item) for item in normalized}
        present_events = {_event_id(item) for item in normalized if _event_id(item)}
        ranked = sorted(pool, key=lambda item: (
            -int(bool(_event_id(item)) and _event_id(item) not in present_events),
            -_number(item.get("editorialScore"), _number(item.get("score"))),
            _number(item.get("start")),
        ))
        for candidate in ranked:
            candidate_id = _candidate_id(candidate)
            start, end = _number(candidate.get("start")), _number(candidate.get("end"))
            if (
                not candidate_id or candidate_id in used
                or end - start + DURATION_EPSILON < MIN_EDL_SEGMENT_SECONDS
            ):
                continue
            if any(max(start, left) < min(end, right) for left, right in occupied):
                continue
            safe = semantic_safe_range(
                start, end, speech_segments=speech_segments, silences=silences,
                lower_bound=start, upper_bound=end,
            )
            addition = safe["end"] - safe["start"]
            if upper_limit is not None and total() + addition > upper_limit + .01:
                continue
            item = {
                **copy.deepcopy(candidate), "start": safe["start"], "end": safe["end"],
                "duration": round(addition, 3), "editOrder": len(normalized),
                "addedByDurationOptimizer": True,
                "reason": "最终 EDL 优化：补充不重复且优先来自新事件的完整镜头。",
            }
            normalized.append(item)
            occupied.append((safe["start"], safe["end"]))
            used.add(candidate_id)
            if _event_id(item):
                present_events.add(_event_id(item))
            if total() >= target - .05:
                break

    if order_mode == "source":
        normalized.sort(key=lambda item: (_number(item.get("start")), _number(item.get("editOrder"))))
    else:
        normalized.sort(key=lambda item: _number(item.get("editOrder")))
    for index, item in enumerate(normalized):
        item["editOrder"] = index
        item["duration"] = round(_duration(item), 3)

    event_ids = {
        event_id for item in normalized
        for event_id in (item.get("contributingEventIds") or [_event_id(item)])
        if event_id
    }
    actual = total()
    tolerance = target * .1 if target else 0.0
    available_event_ids = {_event_id(item) for item in pool if _event_id(item)}
    duration_status = (
        "automatic" if target is None else
        "on_target" if target - tolerance <= actual <= target + tolerance else
        "under_target" if actual < target else "over_target"
    )
    semantic_boundaries_ok = all(
        str(item.get("speechBoundaryStatus") or "no_speech") in {"complete", "adjusted", "no_speech"}
        for item in normalized
    )
    no_temporal_overlap = all(
        not (
            max(_number(left.get("start")), _number(right.get("start")))
            < min(_number(left.get("end")), _number(right.get("end"))) - .01
        )
        for index, left in enumerate(normalized)
        for right in normalized[index + 1:]
    )
    within_upper_limit = upper_limit is None or actual <= upper_limit + .01
    quality_score = 100
    if duration_status == "under_target" and target:
        quality_score -= min(24, round(max(0.0, target - actual) / max(1.0, target) * 40))
    elif duration_status == "over_target":
        quality_score -= 25
    quality_score -= min(18, len(rejected) * 6)
    if not semantic_boundaries_ok:
        quality_score -= 30
    if not no_temporal_overlap:
        quality_score -= 25
    intent_report = evaluate_sequence_against_intent(normalized, intent) if intent else None
    if intent_report:
        quality_score = round(quality_score * .55 + float(intent_report.get("score") or 0) * .45)
        if not intent_report.get("passed"):
            quality_score -= 20
    editorial_warnings: list[str] = []
    if target and duration_status == "under_target":
        editorial_warnings.append("现有不重复完整镜头不足，成片短于目标时长")
    if target and target >= 20 and len(event_ids) < 2 and len(available_event_ids) >= 2:
        editorial_warnings.append("候选池包含多个事件，但最终成片仅覆盖一个事件")
        quality_score -= 8
    if target and target >= 10 and len(normalized) < 2 and len(pool) >= 2:
        editorial_warnings.append("候选池包含多个镜头，但最终成片仅保留一个镜头")
        quality_score -= 8
    return {
        "segments": normalized,
        "actualDuration": actual,
        "targetSeconds": target,
        "durationUpperLimit": round(upper_limit, 3) if upper_limit is not None else None,
        "durationStatus": duration_status,
        "eventCount": len(event_ids), "shotCount": len(normalized),
        "boundaryAdjustments": boundary_adjustments,
        "overlapResolutions": overlap_log,
        "semanticDeduplication": semantic_log,
        "removedSegments": removal_log,
        "rejectedSegments": rejected,
        "qualityReport": {
            "score": max(0, min(100, quality_score)),
            "passed": bool(normalized) and semantic_boundaries_ok and no_temporal_overlap and within_upper_limit
            and (not intent_report or bool(intent_report.get("passed"))),
            "checks": {
                "hasValidSegments": bool(normalized),
                "semanticBoundaries": semantic_boundaries_ok,
                "noTemporalOverlap": no_temporal_overlap,
                "withinDynamicUpperLimit": within_upper_limit,
                "targetFit": duration_status in {"automatic", "on_target"},
            },
            "availableEventCount": len(available_event_ids),
            "availableShotCount": len(pool),
            "warnings": editorial_warnings,
            "userIntent": intent_report,
        },
    }
