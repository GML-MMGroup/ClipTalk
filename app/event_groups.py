from __future__ import annotations

import copy
import itertools
import math
import uuid
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def composition_duration(segments: list[dict[str, Any]]) -> float:
    total = sum(max(0.0, _number(item.get("end")) - _number(item.get("start"))) for item in segments)
    overlap = sum(
        max(0.0, _number((item.get("transitionIn") or {}).get("duration")))
        for item in segments[1:]
        if (item.get("transitionIn") or {}).get("type") == "dissolve"
    )
    return round(max(0.0, total - overlap), 3)


def recalculate_event_group(group: dict[str, Any]) -> dict[str, Any]:
    segments = group.setdefault("segments", [])
    for position, segment in enumerate(segments):
        segment["editOrder"] = position
        segment["duration"] = round(max(0.0, _number(segment.get("end")) - _number(segment.get("start"))), 3)
        transition = segment.setdefault("transitionIn", {"type": "cut", "duration": 0.0})
        transition_type = "dissolve" if transition.get("type") == "dissolve" and position else "cut"
        transition["type"] = transition_type
        transition["duration"] = round(max(0.0, min(.4, _number(transition.get("duration"), .18))), 3) if transition_type == "dissolve" else 0.0
    group["actualDuration"] = composition_duration(segments)
    group["totalDuration"] = group["actualDuration"]
    available = group.get("availableSegments") or segments
    essential = [item for item in available if item.get("essential")]
    if not essential and available:
        max(available, key=lambda item: _number(item.get("score"), 0))["essential"] = True
        essential = [item for item in available if item.get("essential")]
    group["minimumDuration"] = composition_duration(essential)
    group["preferredDuration"] = composition_duration(available)
    return group


def _segment_from_candidate(
    candidate: dict[str, Any],
    *,
    group_id: str,
    order: int,
    role: str,
    essential: bool,
    reusable_anchor: bool,
    transition_type: str,
) -> dict[str, Any]:
    start = round(_number(candidate.get("start")), 3)
    end = round(max(start, _number(candidate.get("end"))), 3)
    return {
        "id": f"segment_{group_id}_{order}_{uuid.uuid4().hex[:8]}",
        "eventId": group_id,
        "candidateId": str(candidate.get("candidateId") or f"candidate_{candidate.get('index', order)}"),
        "semanticUnitId": str(candidate.get("semanticUnitId") or f"semantic_{candidate.get('index', order)}"),
        "candidateIndex": int(candidate.get("index", order)),
        "start": start,
        "end": end,
        "duration": round(end - start, 3),
        "sourceOrder": start,
        "editOrder": order,
        "role": role[:40] or "精彩镜头",
        "score": round(max(0.0, min(100.0, _number(candidate.get("score"), 50))), 2),
        "reason": str(candidate.get("reason") or "视觉模型识别的事件镜头")[:600],
        "evidence": list(candidate.get("evidence") or [])[:8],
        "audioEvidence": dict(candidate.get("audioEvidence") or {}),
        "peakStart": round(_number(candidate.get("peakStart"), start), 3),
        "peakEnd": round(_number(candidate.get("peakEnd"), end), 3),
        "minimumKeepSeconds": round(max(.35, _number(candidate.get("minimumKeepSeconds"), min(end - start, 2.0))), 3),
        "boundaryConfidence": round(max(0.0, min(1.0, _number(candidate.get("boundaryConfidence"), .5))), 3),
        "safeStart": round(_number(candidate.get("safeStart"), start), 3),
        "safeEnd": round(_number(candidate.get("safeEnd"), end), 3),
        "originalStart": round(_number(candidate.get("originalStart"), start), 3),
        "originalEnd": round(_number(candidate.get("originalEnd"), end), 3),
        "boundarySource": str(candidate.get("boundarySource") or "visual"),
        "speechBoundaryStatus": str(candidate.get("speechBoundaryStatus") or "no_speech"),
        "boundaryAdjusted": bool(candidate.get("boundaryAdjusted")),
        "hasSpeech": bool(candidate.get("hasSpeech")),
        "speechUnits": copy.deepcopy(candidate.get("speechUnits") or []),
        "speechUnitCount": int(candidate.get("speechUnitCount") or len(candidate.get("speechUnits") or [])),
        "essential": bool(essential),
        "reusableAnchor": bool(reusable_anchor),
        "transitionIn": {
            "type": "dissolve" if transition_type == "dissolve" and order else "cut",
            "duration": .18 if transition_type == "dissolve" and order else 0.0,
        },
    }


def build_event_groups(
    candidates: list[dict[str, Any]],
    model_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate a VLM event plan and turn moment references into an editable EDL."""
    groups: list[dict[str, Any]] = []
    used_subject_indices: set[int] = set()
    raw_groups = model_result.get("event_groups") or model_result.get("eventGroups") or []
    for raw_group in raw_groups if isinstance(raw_groups, list) else []:
        if not isinstance(raw_group, dict):
            continue
        raw_moments = raw_group.get("moments") or []
        if not isinstance(raw_moments, list):
            continue
        raw_moments = sorted(
            (item for item in raw_moments if isinstance(item, dict)),
            key=lambda item: _number(item.get("order"), 10_000),
        )
        group_id = f"event_{uuid.uuid4().hex[:12]}"
        segments: list[dict[str, Any]] = []
        for raw_moment in raw_moments:
            try:
                index = int(raw_moment.get("candidate_index", raw_moment.get("index", -1)))
            except (TypeError, ValueError):
                continue
            if index < 0 or index >= len(candidates):
                continue
            reusable = bool(raw_moment.get("reusable_anchor") or raw_moment.get("reusableAnchor"))
            if index in used_subject_indices and not reusable:
                continue
            if not reusable:
                used_subject_indices.add(index)
            segments.append(_segment_from_candidate(
                candidates[index],
                group_id=group_id,
                order=len(segments),
                role=str(raw_moment.get("role") or "精彩镜头"),
                essential=bool(raw_moment.get("essential", len(segments) == 0)),
                reusable_anchor=reusable,
                transition_type=str(raw_moment.get("transition_in") or raw_moment.get("transitionIn") or "cut"),
            ))
        if not segments:
            continue
        group = {
            "id": group_id,
            "index": len(groups),
            "title": str(raw_group.get("title") or candidates[segments[0]["candidateIndex"]].get("title") or "精彩事件")[:80],
            "summary": str(raw_group.get("summary") or raw_group.get("reason") or "由多个相关镜头组成的事件高光")[:600],
            "score": round(max(0.0, min(100.0, _number(raw_group.get("score"), max(item["score"] for item in segments)))), 2),
            "assemblyStrategy": "adaptive",
            "segments": segments,
            "availableSegments": copy.deepcopy(segments),
        }
        groups.append(recalculate_event_group(group))

    # Never lose a strong model-verified moment because the grouping response
    # omitted it. It remains a one-shot event and is clearly represented as such.
    for index, candidate in enumerate(candidates):
        if index in used_subject_indices:
            continue
        group_id = f"event_{uuid.uuid4().hex[:12]}"
        group = {
            "id": group_id,
            "index": len(groups),
            "title": str(candidate.get("title") or "精彩事件")[:80],
            "summary": str(candidate.get("reason") or "当前只发现一个可靠镜头")[:600],
            "score": round(_number(candidate.get("score"), 50), 2),
            "assemblyStrategy": "source_order",
            "segments": [_segment_from_candidate(
                candidate, group_id=group_id, order=0, role="核心镜头",
                essential=True, reusable_anchor=False, transition_type="cut",
            )],
        }
        group["availableSegments"] = copy.deepcopy(group["segments"])
        groups.append(recalculate_event_group(group))
    groups.sort(key=lambda item: (-_number(item.get("score")), min(segment["start"] for segment in item["segments"])))
    for index, group in enumerate(groups):
        group["index"] = index
    return groups


def split_event_groups_at_scene_cuts(
    groups: list[dict[str, Any]], scene_cuts: list[float] | None, *, minimum_shot_seconds: float = 1.2,
) -> list[dict[str, Any]]:
    """Expose physical shots inside a VLM range without changing its event."""
    cuts = sorted({_number(value) for value in scene_cuts or [] if _number(value) > 0})
    if not cuts:
        return groups
    result = copy.deepcopy(groups)

    def split(segment: dict[str, Any]) -> list[dict[str, Any]]:
        start, end = _number(segment.get("start")), _number(segment.get("end"))
        internal = [value for value in cuts if start + minimum_shot_seconds <= value <= end - minimum_shot_seconds]
        # Splitting a continuous spoken expression would make its physical
        # sub-shots independently selectable and could reintroduce a mid-line
        # cut. Keep one semantic edit segment while exposing its visual shots.
        if segment.get("hasSpeech"):
            item = copy.deepcopy(segment)
            item.setdefault("shotId", str(item.get("id") or "shot"))
            boundaries = [start, *internal, end]
            item["visualShots"] = [
                {
                    "id": f"{item['shotId']}_visual_{index + 1}",
                    "start": round(left, 3), "end": round(right, 3),
                    "duration": round(right - left, 3),
                }
                for index, (left, right) in enumerate(zip(boundaries, boundaries[1:]))
            ]
            item["physicalShotCount"] = len(item["visualShots"])
            return [item]
        boundaries = [start, *internal, end]
        if len(boundaries) == 2:
            item = copy.deepcopy(segment)
            item.setdefault("shotId", str(item.get("id") or "shot"))
            return [item]
        pieces: list[dict[str, Any]] = []
        base_id = str(segment.get("id") or f"segment_{uuid.uuid4().hex[:8]}")
        for index, (left, right) in enumerate(zip(boundaries, boundaries[1:])):
            item = copy.deepcopy(segment)
            item.update({
                "id": f"{base_id}_shot_{index + 1}", "shotId": f"{base_id}_shot_{index + 1}",
                "parentSegmentId": base_id, "start": round(left, 3), "end": round(right, 3),
                "duration": round(right - left, 3), "sourceOrder": round(left, 3),
                "role": str(segment.get("role") or "精彩镜头") if index == 0 else "镜头延续",
                "transitionIn": {"type": "cut", "duration": 0.0},
                "splitBySceneCut": True,
                "physicalShotCount": 1,
            })
            pieces.append(item)
        return pieces

    for group in result:
        available: list[dict[str, Any]] = []
        for segment in group.get("availableSegments") or group.get("segments") or []:
            available.extend(split(segment))
        selected_parent_ids = {
            str(segment.get("parentSegmentId") or segment.get("id"))
            for segment in group.get("segments") or []
        }
        group["availableSegments"] = available
        group["segments"] = [
            segment for segment in available
            if str(segment.get("parentSegmentId") or segment.get("id")) in selected_parent_ids
        ]
        recalculate_event_group(group)
    return result


def _recommended_groups(groups: list[dict[str, Any]], requested_count: int | None) -> list[dict[str, Any]]:
    ranked = sorted(groups, key=lambda item: (-_number(item.get("score")), item.get("index", 0)))
    if requested_count is not None:
        limit = max(1, requested_count)
        if not ranked:
            return []
        # A requested number is an upper bound, not a quota. Do not append a
        # weak tail merely to fill the requested count.
        quality_floor = max(72.0, _number(ranked[0].get("score")) - 15.0)
        qualified = [group for group in ranked if _number(group.get("score")) >= quality_floor]
        return (qualified or ranked[:1])[:limit]
    if not ranked:
        return []
    threshold = max(76.0, _number(ranked[0].get("score")) - 10.0)
    return [group for group in ranked if _number(group.get("score")) >= threshold][:5] or ranked[:1]


def _trim_segment_to_duration(segment: dict[str, Any], duration: float) -> dict[str, Any]:
    """Trim a candidate around its verified peak without moving outside it."""
    result = copy.deepcopy(segment)
    source_start = _number(result.get("start"))
    source_end = max(source_start, _number(result.get("end")))
    source_duration = source_end - source_start
    # A broad candidate can contain several sentence-level speech units. It is
    # safe to retain a whole unit around the verified visual peak, but never to
    # cut through one. Legacy candidates without speechUnits remain indivisible.
    if result.get("hasSpeech"):
        units = [
            item for item in result.get("speechUnits") or []
            if _number(item.get("end")) > _number(item.get("start"))
        ]
        if not units or float(duration) >= source_duration - .001:
            return result
        peak_start = max(source_start, min(source_end, _number(result.get("peakStart"), source_start)))
        peak_end = max(peak_start, min(source_end, _number(result.get("peakEnd"), peak_start)))
        peak_center = (peak_start + peak_end) / 2
        anchor = max(units, key=lambda item: (
            max(0.0, min(peak_end, _number(item.get("end"))) - max(peak_start, _number(item.get("start")))),
            -abs((_number(item.get("start")) + _number(item.get("end"))) / 2 - peak_center),
        ))
        chosen = [anchor]
        start = min(peak_start, _number(anchor.get("start")))
        end = max(peak_end, _number(anchor.get("end")))
        # Include every speech unit touched by the visual peak/core.
        for unit in units:
            if _number(unit.get("end")) > start and _number(unit.get("start")) < end and unit not in chosen:
                chosen.append(unit)
                start = min(start, _number(unit.get("start")))
                end = max(end, _number(unit.get("end")))
        # Add adjacent complete sentences while they fit the allocated budget.
        for unit in sorted(
            (item for item in units if item not in chosen),
            key=lambda item: abs((_number(item.get("start")) + _number(item.get("end"))) / 2 - peak_center),
        ):
            next_start = min(start, _number(unit.get("start")))
            next_end = max(end, _number(unit.get("end")))
            if next_end - next_start <= float(duration) + .001:
                chosen.append(unit)
                start, end = next_start, next_end
        result.update({
            "originalStart": round(source_start, 3), "originalEnd": round(source_end, 3),
            "start": round(start, 3), "end": round(end, 3),
            "duration": round(end - start, 3), "trimmedForBudget": True,
            "trimmedToCompleteSpeechUnits": True,
            "selectedSpeechUnitIds": [str(item.get("id") or "") for item in chosen],
        })
        return result
    keep = min(source_duration, max(.35, float(duration)))
    if keep >= source_duration - .001:
        return result
    peak_start = max(source_start, min(source_end, _number(result.get("peakStart"), source_start + source_duration * .4)))
    peak_end = max(peak_start, min(source_end, _number(result.get("peakEnd"), source_start + source_duration * .6)))
    peak_duration = peak_end - peak_start
    if peak_duration <= keep:
        start = peak_start - (keep - peak_duration) / 2
    else:
        start = (peak_start + peak_end - keep) / 2
    start = max(source_start, min(source_end - keep, start))
    end = start + keep
    result["originalStart"] = round(source_start, 3)
    result["originalEnd"] = round(source_end, 3)
    result["start"] = round(start, 3)
    result["end"] = round(end, 3)
    result["duration"] = round(keep, 3)
    result["trimmedForBudget"] = True
    return result


def _segment_floor(segment: dict[str, Any]) -> float:
    duration = max(.35, _number(segment.get("end")) - _number(segment.get("start")))
    if segment.get("hasSpeech"):
        if segment.get("speechUnits"):
            return min(duration, max(.35, _number(segment.get("minimumKeepSeconds"), duration)))
        return duration
    return min(duration, max(.35, _number(segment.get("minimumKeepSeconds"), duration)))


def _group_core_segment(group: dict[str, Any]) -> dict[str, Any] | None:
    available = list(group.get("availableSegments") or group.get("segments") or [])
    if not available:
        return None
    essential = [item for item in available if item.get("essential")]
    pool = essential or available
    # Prefer a strong concise representative so several distinct events can
    # coexist before spending the remaining budget on context.
    return max(pool, key=lambda item: (
        _number(item.get("score")) - min(20.0, _segment_floor(item) * .35),
        -_segment_floor(item),
    ))


def _group_floor(group: dict[str, Any]) -> float:
    core = _group_core_segment(group)
    return _segment_floor(core) if core else math.inf


def _text_tokens(value: Any) -> set[str]:
    compact = "".join(character.lower() for character in str(value or "") if character.isalnum())
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index:index + 2] for index in range(len(compact) - 1)}


def _combination_quality(groups: tuple[dict[str, Any], ...], target: float) -> tuple[float, float, float]:
    base = sum(_number(group.get("score")) for group in groups)
    duplicate_penalty = 0.0
    for left, right in itertools.combinations(groups, 2):
        left_tokens = _text_tokens(f"{left.get('title', '')}{left.get('summary', '')}")
        right_tokens = _text_tokens(f"{right.get('title', '')}{right.get('summary', '')}")
        if left_tokens and right_tokens:
            similarity = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
            duplicate_penalty += similarity * 28.0
    roles = {
        str(segment.get("role") or "").lower()
        for group in groups for segment in group.get("availableSegments") or group.get("segments") or []
    }
    role_coverage = sum(
        any(token in role for role in roles)
        for token in ("建立", "开场", "发展", "高潮", "反应", "结果", "结尾")
    )
    starts = [
        _number(segment.get("start"))
        for group in groups for segment in group.get("availableSegments") or group.get("segments") or []
    ]
    temporal_spread = (max(starts) - min(starts)) if len(starts) > 1 else 0.0
    floor_total = sum(_group_floor(group) for group in groups)
    quality = base + role_coverage * 2.5 + min(12.0, temporal_spread / max(5.0, target) * 8.0) - duplicate_penalty
    return quality, -abs(target - floor_total), temporal_spread


def _fit_group_to_budget(group: dict[str, Any], budget: float) -> None:
    source_segments = copy.deepcopy(group.get("availableSegments") or group.get("segments", []))
    budget = max(.35, float(budget))
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    remaining = budget

    core = _group_core_segment(group)
    if core:
        segment_duration = max(.35, _number(core.get("end")) - _number(core.get("start")))
        fitted = _trim_segment_to_duration(core, min(segment_duration, max(remaining, _segment_floor(core))))
        selected.append(fitted)
        selected_ids.add(str(core.get("id")))
        remaining = max(0.0, budget - composition_duration(selected))

    optional = sorted(
        (item for item in source_segments if str(item.get("id")) not in selected_ids),
        key=lambda item: (not bool(item.get("essential")), item.get("editOrder", 0), -_number(item.get("score"))),
    )
    for segment in optional:
        if remaining < .35:
            break
        segment_duration = max(0.0, _number(segment.get("end")) - _number(segment.get("start")))
        if segment_duration <= remaining + .001:
            selected.append(segment)
            selected_ids.add(str(segment.get("id")))
        elif not segment.get("hasSpeech") and remaining >= max(2.0, _segment_floor(segment)) and composition_duration(selected) < budget * .9:
            fitted = _trim_segment_to_duration(segment, remaining)
            fitted["essential"] = False
            fitted["role"] = str(fitted.get("role") or "上下文镜头")
            selected.append(fitted)
            selected_ids.add(str(segment.get("id")))
        remaining = max(0.0, budget - composition_duration(selected))

    selected.sort(key=lambda item: item.get("editOrder", 0))
    group["segments"] = selected
    group["allocatedDuration"] = round(budget, 3)
    recalculate_event_group(group)
    actual = _number(group.get("actualDuration"))
    tolerance = max(.5, budget * .1)
    group["durationStatus"] = "on_target" if abs(actual - budget) <= tolerance else ("under_target" if actual < budget else "over_target")
    group["durationGap"] = round(budget - actual, 3)


def allocate_event_group_budget(
    groups: list[dict[str, Any]],
    *,
    total_target_seconds: float | None,
    requested_count: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    groups = copy.deepcopy(groups)
    qualified = _recommended_groups(groups, requested_count)
    if not qualified:
        return groups, []
    if total_target_seconds is None:
        for group in groups:
            group["allocatedDuration"] = group["preferredDuration"]
        desired = min(len(qualified), max(1, min(3, requested_count or 3)))
        return groups, [group["id"] for group in qualified[:desired]]

    target = max(4.0, float(total_target_seconds))
    duration_upper_limit = target + max(5.0, target * .15)
    desired = min(len(qualified), max(1, min(3, requested_count or 3)))
    recommended: list[dict[str, Any]] = []
    for count in range(desired, 0, -1):
        fitting = [
            combination for combination in itertools.combinations(qualified, count)
            if sum(_group_floor(group) for group in combination) <= duration_upper_limit + .001
        ]
        if fitting:
            recommended = list(max(
                fitting,
                key=lambda combination: _combination_quality(combination, target),
            ))
            break
    if not recommended:
        # No complete core fits the cap. Keep the strongest concise event and
        # report the unavoidable overrun instead of cutting its dialogue.
        recommended = [max(qualified, key=lambda group: (
            _number(group.get("score")) - min(25.0, _group_floor(group) * .25),
            -_group_floor(group),
        ))]

    minimums = {item["id"]: _group_floor(item) for item in recommended}
    budgets = dict(minimums)
    remaining = max(0.0, target - sum(budgets.values()))
    while remaining > .01:
        open_groups = [item for item in recommended if budgets[item["id"]] + .01 < _number(item.get("preferredDuration"))]
        if not open_groups:
            break
        weights = {
            item["id"]: max(1.0, _number(item.get("score"))) * max(.25, _number(item.get("preferredDuration")) - budgets[item["id"]])
            for item in open_groups
        }
        total_weight = sum(weights.values())
        distributed = 0.0
        for item in open_groups:
            room = _number(item.get("preferredDuration")) - budgets[item["id"]]
            addition = min(room, remaining * weights[item["id"]] / total_weight)
            budgets[item["id"]] += addition
            distributed += addition
        if distributed <= .001:
            break
        remaining -= distributed
    selected_ids = {item["id"] for item in recommended}
    reduction_reason = ""
    if len(recommended) < desired:
        reduction_reason = (
            f"保留 {desired} 个事件的完整核心会超过 {duration_upper_limit:.1f} 秒上限，"
            f"已减少为 {len(recommended)} 个事件"
        )
    for group in groups:
        if group["id"] in selected_ids:
            _fit_group_to_budget(group, budgets[group["id"]])
            group["durationUpperLimit"] = round(duration_upper_limit, 3)
            group["eventReductionReason"] = reduction_reason
        else:
            group["allocatedDuration"] = group["preferredDuration"]
    return groups, [item["id"] for item in recommended]


def event_groups_total(groups: list[dict[str, Any]], group_ids: list[str]) -> float:
    selected = {value for value in group_ids}
    return round(sum(_number(group.get("actualDuration")) for group in groups if group.get("id") in selected), 3)


def build_final_reel(selections: list[dict[str, Any]], *, order_mode: str = "source") -> dict[str, Any]:
    """Flatten selected event chapters into one non-repeating final EDL."""
    chapters: list[dict[str, Any]] = []
    for selection in selections:
        segments = copy.deepcopy(selection.get("segments") or [{
            "start": selection.get("start", 0), "end": selection.get("end", 0),
            "transitionIn": {"type": "cut", "duration": 0.0},
        }])
        valid = [item for item in segments if _number(item.get("end")) - _number(item.get("start")) >= .2]
        if not valid:
            continue
        chapters.append({
            "id": str(selection.get("id") or f"candidate_{selection.get('index', len(chapters))}"),
            "title": str(selection.get("title") or "高光事件"),
            "score": _number(selection.get("score"), 0),
            "segments": sorted(valid, key=lambda item: _number(item.get("editOrder"), 10_000)),
            "sourceStart": min(_number(item.get("start")) for item in valid),
        })
    if order_mode == "source":
        # Explicit source mode globally reorders every selected shot by its
        # original media timestamp, even when one chapter contains shots that
        # surround shots from another chapter.
        ordered_segments = [
            (chapter, segment)
            for chapter in chapters
            for segment in chapter["segments"]
        ]
        ordered_segments.sort(key=lambda item: (
            _number(item[1].get("start"), 0),
            -_number(item[0].get("score"), 0),
            _number(item[1].get("editOrder"), 10_000),
        ))
    else:
        ordered_segments = [
            (chapter, segment)
            for chapter in chapters
            for segment in chapter["segments"]
        ]
    reel_segments: list[dict[str, Any]] = []
    occupied: list[tuple[float, float]] = []
    included_chapters: list[dict[str, Any]] = []
    chapter_order_map: dict[str, int] = {}
    chapter_segments_map: dict[str, list[dict[str, Any]]] = {}
    deduplication_log: list[dict[str, Any]] = []
    for chapter, segment in ordered_segments:
        start = _number(segment.get("start"))
        end = _number(segment.get("end"))
        overlapping_index = next((
            index for index, (left, right) in enumerate(occupied)
            if max(start, left) < min(end, right)
        ), None)
        if overlapping_index is not None:
            existing = reel_segments[overlapping_index]
            old_start, old_end = _number(existing.get("start")), _number(existing.get("end"))
            existing["start"] = round(min(old_start, start), 3)
            existing["end"] = round(max(old_end, end), 3)
            existing["duration"] = round(existing["end"] - existing["start"], 3)
            contributor = str(chapter["id"])
            contributors = existing.setdefault("contributingChapterIds", [str(existing.get("chapterId") or "")])
            if contributor not in contributors:
                contributors.append(contributor)
            occupied[overlapping_index] = (existing["start"], existing["end"])
            deduplication_log.append({
                "action": "merged_overlap",
                "keptSegmentId": str(existing.get("id") or ""),
                "mergedSegmentId": str(segment.get("id") or ""),
                "resultStart": existing["start"], "resultEnd": existing["end"],
                "reason": "源区间重叠，已合并为连续镜头而非静默删除",
            })
            continue
        chapter_id = str(chapter["id"])
        if chapter_id not in chapter_order_map:
            chapter_order_map[chapter_id] = len(chapter_order_map)
        segment["chapterId"] = chapter_id
        segment["chapterTitle"] = chapter["title"]
        segment["chapterOrder"] = chapter_order_map[chapter_id]
        segment["editOrder"] = len(reel_segments)
        segment["transitionIn"] = {"type": "cut", "duration": 0.0}
        segment["contributingChapterIds"] = [chapter_id]
        reel_segments.append(segment)
        chapter_segments_map.setdefault(chapter_id, []).append(segment)
        occupied.append((start, end))
    # Keep chapter metadata in the same order as the flattened EDL. The
    # selected groups can arrive in score order, while source-order rendering
    # may place an earlier chapter's shot before a later group's shot.
    ordered_chapters = sorted(chapters, key=lambda chapter: chapter_order_map.get(str(chapter["id"]), 10_000))
    for chapter in ordered_chapters:
        chapter_segments = chapter_segments_map.get(str(chapter["id"]), [])
        contributed_segments = [
            segment for segment in reel_segments
            if str(chapter["id"]) in (segment.get("contributingChapterIds") or [])
        ]
        if chapter_segments or contributed_segments:
            included_chapters.append({
                "id": chapter["id"], "title": chapter["title"],
                "score": round(chapter["score"], 2),
                "segmentCount": len(chapter_segments),
                "duration": composition_duration(chapter_segments or contributed_segments),
                "mergedIntoOverlap": not bool(chapter_segments),
            })
    if not reel_segments:
        return {"segments": [], "chapters": [], "actualDuration": 0.0}
    weighted_duration = sum(max(.001, item["duration"]) for item in included_chapters)
    score = sum(item["score"] * max(.001, item["duration"]) for item in included_chapters) / weighted_duration
    return {
        "id": "final_reel",
        "title": "高光成片",
        "summary": f"由 {len(included_chapters)} 个高光事件、{len(reel_segments)} 个不重复镜头组合",
        "score": round(score, 2),
        "segments": reel_segments,
        "chapters": included_chapters,
        "actualDuration": composition_duration(reel_segments),
        "deduplicationLog": deduplication_log,
    }


def legacy_candidates_to_event_groups(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return build_event_groups(candidates, {"event_groups": []})
