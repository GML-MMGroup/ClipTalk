from __future__ import annotations

import copy
import math
import uuid
from typing import Any


# Source timestamps are serialized as decimal seconds, but binary floating
# point subtraction can turn an exact 0.200s range into 0.19999999999999.
# Keep one shared tolerance for every EDL/renderability gate.
MIN_SOURCE_DURATION_SECONDS = 0.2
SOURCE_DURATION_EPSILON = 1e-6


def source_duration_meets_minimum(start: Any, end: Any, minimum: float = MIN_SOURCE_DURATION_SECONDS) -> bool:
    try:
        duration = float(end) - float(start)
    except (TypeError, ValueError):
        return False
    return math.isfinite(duration) and duration + SOURCE_DURATION_EPSILON >= minimum


ALLOWED_RATES = (1.0, 1.1, 1.25, 1.5)
ALLOWED_TRANSITIONS = {"cut", "dissolve", "fade_black"}
ALLOWED_BRIDGES = {"none", "j_cut", "l_cut"}

DEFAULT_TECHNIQUE_POLICY: dict[str, Any] = {
    "preset": "auto",
    "strength": "restrained",
    "allowSpeed": True,
    "allowTransitions": True,
    "allowAudioBridges": True,
    "allowCutaways": True,
    "allowSilenceCompression": True,
    "allowColdOpen": False,
    "maxSpeed": 1.5,
}

PRESET_LIMITS = {
    "auto": {"maxSpeed": 1.25, "bridgesPerMinute": 3, "cutawaysPerMinute": 3},
    "natural": {"maxSpeed": 1.1, "bridgesPerMinute": 2, "cutawaysPerMinute": 2},
    "tight": {"maxSpeed": 1.25, "bridgesPerMinute": 4, "cutawaysPerMinute": 4},
    "attraction": {"maxSpeed": 1.5, "bridgesPerMinute": 4, "cutawaysPerMinute": 4},
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def normalize_technique_policy(value: dict[str, Any] | None) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    preset = str(source.get("preset") or "auto").strip().lower()
    if preset not in PRESET_LIMITS:
        preset = "auto"
    result = {**DEFAULT_TECHNIQUE_POLICY, **source, "preset": preset}
    result["strength"] = "restrained"
    for key in (
        "allowSpeed", "allowTransitions", "allowAudioBridges", "allowCutaways",
        "allowSilenceCompression", "allowColdOpen",
    ):
        result[key] = bool(result.get(key))
    requested_max = _number(result.get("maxSpeed"), PRESET_LIMITS[preset]["maxSpeed"])
    preset_max = PRESET_LIMITS[preset]["maxSpeed"]
    result["maxSpeed"] = max(rate for rate in ALLOWED_RATES if rate <= min(1.5, requested_max, preset_max) + .001)
    result.update({
        "bridgesPerMinute": PRESET_LIMITS[preset]["bridgesPerMinute"],
        "cutawaysPerMinute": PRESET_LIMITS[preset]["cutawaysPerMinute"],
    })
    return result


def normalize_playback_rate(value: Any, maximum: float = 1.5) -> float:
    requested = max(1.0, min(_number(value, 1.0), maximum, 1.5))
    return min(ALLOWED_RATES, key=lambda rate: abs(rate - requested))


def normalize_transition(value: Any, *, first: bool = False) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    transition_type = str(source.get("type") or "cut").strip().lower()
    if first or transition_type not in ALLOWED_TRANSITIONS:
        transition_type = "cut"
    duration = 0.0
    if transition_type == "dissolve":
        duration = max(.18, min(.35, _number(source.get("duration"), .22)))
    elif transition_type == "fade_black":
        duration = max(.3, min(.4, _number(source.get("duration"), .35)))
    return {
        "type": transition_type,
        "duration": round(duration, 3),
        "reason": str(source.get("reason") or "")[:240],
    }


def normalize_audio_bridge(value: Any, *, first: bool = False) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    bridge_type = str(source.get("type") or "none").strip().lower()
    if first or bridge_type not in ALLOWED_BRIDGES:
        bridge_type = "none"
    duration = 0.0 if bridge_type == "none" else max(.3, min(1.2, _number(source.get("duration"), .6)))
    return {
        "type": bridge_type,
        "duration": round(duration, 3),
        "reason": str(source.get("reason") or "")[:240],
    }


def normalized_silence_cuts(segment: dict[str, Any]) -> list[dict[str, Any]]:
    start = _number(segment.get("start"))
    end = max(start, _number(segment.get("end"), start))
    result: list[dict[str, Any]] = []
    occupied_end = start
    for raw in sorted(segment.get("silenceCuts") or [], key=lambda item: _number(item.get("start")) if isinstance(item, dict) else 0):
        if not isinstance(raw, dict):
            continue
        left = max(start, occupied_end, _number(raw.get("start")))
        right = min(end, _number(raw.get("end"), left))
        if right - left < .45:
            continue
        retained = max(.12, min(.25, _number(raw.get("retained"), .18), right - left))
        result.append({
            "start": round(left, 3), "end": round(right, 3), "retained": round(retained, 3),
            "reason": str(raw.get("reason") or "压缩无语义停顿")[:240],
        })
        occupied_end = right
    return result


def segment_source_duration(segment: dict[str, Any]) -> float:
    return max(0.0, _number(segment.get("end")) - _number(segment.get("start")))


def segment_removed_silence(segment: dict[str, Any]) -> float:
    return round(sum(max(0.0, item["end"] - item["start"] - item["retained"]) for item in normalized_silence_cuts(segment)), 3)


def segment_effective_duration(segment: dict[str, Any]) -> float:
    rate = normalize_playback_rate(segment.get("playbackRate"))
    source_kept = max(0.0, segment_source_duration(segment) - segment_removed_silence(segment))
    return round(source_kept / rate, 3)


def transition_overlap(segments: list[dict[str, Any]], index: int) -> float:
    if index <= 0 or index >= len(segments):
        return 0.0
    transition = normalize_transition(segments[index].get("transitionIn"))
    if transition["type"] not in {"dissolve", "fade_black"}:
        return 0.0
    previous_duration = segment_effective_duration(segments[index - 1])
    current_duration = segment_effective_duration(segments[index])
    return round(min(transition["duration"], previous_duration / 3, current_duration / 3), 3)


def composition_effective_duration(segments: list[dict[str, Any]]) -> float:
    normalized = [
        item for item in segments
        if source_duration_meets_minimum(item.get("start"), item.get("end"))
    ]
    total = sum(segment_effective_duration(item) for item in normalized)
    overlap = sum(transition_overlap(normalized, index) for index in range(1, len(normalized)))
    return round(max(0.0, total - overlap), 3)


def composition_schedule(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    output_end = 0.0
    for index, segment in enumerate(segments):
        duration = segment_effective_duration(segment)
        overlap = transition_overlap(segments, index)
        output_start = max(0.0, output_end - overlap)
        output_end = output_start + duration
        result.append({
            "segmentId": str(segment.get("id") or index), "index": index,
            "outputStart": round(output_start, 3), "outputEnd": round(output_end, 3),
            "effectiveDuration": duration, "transitionOverlap": overlap,
        })
    return result


def source_pieces(segment: dict[str, Any]) -> list[dict[str, float]]:
    """Return source ranges after silence compression.

    A small natural tail is retained at the beginning of every removed pause;
    this avoids joining two phonemes on the exact same sample.
    """
    start = _number(segment.get("start"))
    end = max(start, _number(segment.get("end"), start))
    cursor = start
    pieces: list[dict[str, float]] = []
    for silence in normalized_silence_cuts(segment):
        kept_end = min(silence["end"], silence["start"] + silence["retained"])
        if kept_end - cursor >= .08:
            pieces.append({"start": round(cursor, 3), "end": round(kept_end, 3)})
        cursor = silence["end"]
    if end - cursor >= .08:
        pieces.append({"start": round(cursor, 3), "end": round(end, 3)})
    return pieces or ([{"start": round(start, 3), "end": round(end, 3)}] if end > start else [])


def _has_speech(segment: dict[str, Any]) -> bool:
    return bool(segment.get("hasSpeech") or segment.get("speechUnits") or (segment.get("audioEvidence") or {}).get("transcriptExcerpt"))


def _protected_role(segment: dict[str, Any]) -> bool:
    role = str(segment.get("role") or "").lower()
    return any(token in role for token in ("高潮", "反应", "结果", "结尾", "climax", "reaction", "result"))


def _protected_emotion(segment: dict[str, Any]) -> bool:
    evidence = segment.get("audioEvidence") or {}
    return bool(evidence.get("emotions") or evidence.get("audioEvents"))


def _silence_cuts_for_segment(segment: dict[str, Any], silences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if _protected_emotion(segment) or _protected_role(segment):
        return []
    start, end = _number(segment.get("start")), _number(segment.get("end"))
    cuts: list[dict[str, Any]] = []
    for item in silences:
        if not isinstance(item, dict):
            continue
        left = max(start, _number(item.get("start")))
        right = min(end, _number(item.get("end"), left))
        duration = right - left
        if duration < .45:
            continue
        cuts.append({
            "start": round(left, 3), "end": round(right, 3),
            "retained": .2 if duration <= 1.2 else .15,
            "reason": "压缩普通停顿，保留自然语气间隔",
        })
    return cuts


def _transition_for_pair(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_event = str(previous.get("groupId") or previous.get("chapterId") or previous.get("eventId") or "")
    current_event = str(current.get("groupId") or current.get("chapterId") or current.get("eventId") or "")
    gap = abs(_number(current.get("start")) - _number(previous.get("end")))
    if previous_event and current_event and previous_event != current_event:
        # A dissolve implies continuous time/space.  Across event chapters it
        # creates a false relationship, especially when source times are far
        # apart.  Use a short chapter separator for a large jump and a direct
        # cut for a compact thematic transition.
        if gap > 30:
            return {"type": "fade_black", "duration": .35, "reason": "进入新的事件章节，明确分隔时空关系"}
        return {"type": "cut", "duration": 0.0, "reason": "切换事件章节，避免制造虚假连续性"}
    if gap > 2.5:
        return {"type": "dissolve", "duration": .22, "reason": "同一事件存在轻微时间跳跃"}
    return {"type": "cut", "duration": 0.0, "reason": "动作或语义连续，使用硬切"}


def _audio_bridge_for_pair(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_event = str(previous.get("groupId") or previous.get("chapterId") or previous.get("eventId") or "")
    current_event = str(current.get("groupId") or current.get("chapterId") or current.get("eventId") or "")
    if previous_event and current_event and previous_event != current_event:
        return {"type": "none", "duration": 0.0, "reason": "不同事件章节保持同步音画，不使用声音桥"}
    previous_speech, current_speech = _has_speech(previous), _has_speech(current)
    if previous_speech and not current_speech:
        return {"type": "l_cut", "duration": .6, "reason": "上一镜头对白延续到无对白画面"}
    if current_speech and not previous_speech:
        return {"type": "j_cut", "duration": .5, "reason": "下一镜头对白提前进入，衔接上下文"}
    return {"type": "none", "duration": 0.0, "reason": "保持同步音画"}


def _cutaway_candidates(
    primary: dict[str, Any], pool: list[dict[str, Any]], used_ids: set[str],
) -> list[dict[str, Any]]:
    event_id = str(primary.get("groupId") or primary.get("chapterId") or primary.get("eventId") or "")
    center = (_number(primary.get("start")) + _number(primary.get("end"))) / 2
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in pool:
        item_id = str(item.get("id") or item.get("candidateId") or "")
        item_event = str(item.get("groupId") or item.get("chapterId") or item.get("eventId") or "")
        role = str(item.get("role") or "").lower()
        if not item_id or item_id in used_ids or not event_id or item_event != event_id:
            continue
        item_center = (_number(item.get("start")) + _number(item.get("end"))) / 2
        distance = abs(item_center - center)
        if distance > 15 or not any(token in role for token in ("反应", "环境", "细节", "reaction", "context", "detail")):
            continue
        ranked.append((distance - _number(item.get("score")) * .01, item))
    return [item for _, item in sorted(ranked, key=lambda pair: pair[0])]


def plan_editing_techniques(
    segments: list[dict[str, Any]], *, target_seconds: float | None = None,
    policy: dict[str, Any] | None = None, silences: list[dict[str, Any]] | None = None,
    candidate_pool: list[dict[str, Any]] | None = None, manual_selection: bool = False,
) -> dict[str, Any]:
    """Apply deterministic safety rules after the LLM has chosen content.

    The model proposes editorial intent; this pass owns the executable values.
    It never removes an explicitly selected manual shot.
    """
    normalized_policy = normalize_technique_policy(policy)
    result = copy.deepcopy([
        item for item in segments
        if source_duration_meets_minimum(item.get("start"), item.get("end"))
    ])
    if normalized_policy["allowColdOpen"] and not manual_selection and len(result) >= 3:
        cold_open_index = next((
            index for index, item in sorted(
                enumerate(result[1:], start=1),
                key=lambda pair: (-_number(pair[1].get("score")), pair[0]),
            )
            if _protected_role(item)
        ), None)
        if cold_open_index is not None:
            cold_open = result.pop(cold_open_index)
            cold_open["coldOpen"] = True
            cold_open["coldOpenReason"] = "先展示结果或高潮，随后回到事件过程"
            result.insert(0, cold_open)
    source_duration = round(sum(segment_source_duration(item) for item in result), 3)
    silences = silences or []
    pool = candidate_pool or []
    for index, segment in enumerate(result):
        segment["sourceDuration"] = round(segment_source_duration(segment), 3)
        segment["speedLocked"] = bool(segment.get("speedLocked"))
        segment["playbackRate"] = normalize_playback_rate(
            segment.get("playbackRate"), 1.5 if segment["speedLocked"] else normalized_policy["maxSpeed"],
        )
        segment.setdefault("speedReason", "保持自然节奏")
        segment["transitionIn"] = normalize_transition(segment.get("transitionIn"), first=index == 0)
        segment["audioBridge"] = normalize_audio_bridge(segment.get("audioBridge"), first=index == 0)
        if normalized_policy["allowSilenceCompression"] and not segment.get("silenceLocked"):
            segment["silenceCuts"] = _silence_cuts_for_segment(segment, silences)
        else:
            segment["silenceCuts"] = normalized_silence_cuts(segment)

    if normalized_policy["allowTransitions"]:
        for index in range(1, len(result)):
            if not result[index].get("transitionLocked"):
                result[index]["transitionIn"] = normalize_transition(_transition_for_pair(result[index - 1], result[index]))

    # Audio bridges and visual transitions are alternative continuity tools.
    if normalized_policy["allowAudioBridges"]:
        maximum_bridges = max(1, math.ceil(max(source_duration, 1) / 60 * normalized_policy["bridgesPerMinute"]))
        bridge_count = 0
        for index in range(1, len(result)):
            if bridge_count >= maximum_bridges or result[index].get("audioBridgeLocked"):
                continue
            bridge = normalize_audio_bridge(_audio_bridge_for_pair(result[index - 1], result[index]))
            if bridge["type"] != "none":
                maximum_duration = min(
                    bridge["duration"],
                    segment_effective_duration(result[index - 1]) / 3,
                    segment_effective_duration(result[index]) / 3,
                )
                if maximum_duration >= .3:
                    bridge["duration"] = round(maximum_duration, 3)
                    result[index]["audioBridge"] = bridge
                    result[index]["transitionIn"] = {"type": "cut", "duration": 0.0, "reason": "声音桥接使用直接画面切换"}
                    bridge_count += 1

    tolerance = max(4.0, _number(target_seconds) * .1) if target_seconds else 0.0
    target_upper = _number(target_seconds) + tolerance if target_seconds else None
    if normalized_policy["allowSpeed"] and target_upper and composition_effective_duration(result) > target_upper:
        eligible = [
            item for item in result
            if not item.get("speedLocked") and not _has_speech(item) and not _protected_role(item) and not _protected_emotion(item)
        ]
        eligible.sort(key=lambda item: (-segment_effective_duration(item), -_number(item.get("score"))))
        rates = [rate for rate in ALLOWED_RATES if rate <= normalized_policy["maxSpeed"] + .001]
        for segment in eligible:
            for rate in rates[1:]:
                segment["playbackRate"] = rate
                segment["speedReason"] = "无对白操作过程，轻度加速以压缩停顿"
                if composition_effective_duration(result) <= target_upper:
                    break
            if composition_effective_duration(result) <= target_upper:
                break

    for item in result:
        item["effectiveDuration"] = segment_effective_duration(item)

    cutaways: list[dict[str, Any]] = []
    if normalized_policy["allowCutaways"] and pool:
        maximum_cutaways = max(1, math.ceil(max(composition_effective_duration(result), 1) / 60 * normalized_policy["cutawaysPerMinute"]))
        used = {str(item.get("id") or item.get("candidateId") or "") for item in result}
        for segment in result:
            if len(cutaways) >= maximum_cutaways:
                break
            needs_cover = bool(segment.get("silenceCuts")) or str((segment.get("audioBridge") or {}).get("type")) in {"j_cut", "l_cut"}
            if not needs_cover:
                continue
            matches = _cutaway_candidates(segment, pool, used)
            if not matches:
                continue
            source = matches[0]
            source_id = str(source.get("id") or source.get("candidateId"))
            available = segment_effective_duration(segment)
            duration = min(2.5, max(.8, min(available * .35, segment_source_duration(source))))
            if available < .8 or duration < .8:
                continue
            cutaways.append({
                "id": f"cutaway_{uuid.uuid4().hex[:10]}",
                "primarySegmentId": str(segment.get("id") or ""),
                "candidateId": source_id,
                "sourceStart": round(_number(source.get("start")), 3),
                "sourceEnd": round(_number(source.get("start")) + duration, 3),
                "outputOffset": round(max(.15, min(available - duration, available * .35)), 3),
                "duration": round(duration, 3), "muted": True,
                "role": str(source.get("role") or "反应镜头")[:60],
                "reason": "使用同事件邻近反应或细节画面覆盖跳切，主对白保持连续",
            })
            used.add(source_id)

    actual = composition_effective_duration(result)
    minimum_safe = actual
    duration_status = "automatic"
    if target_seconds:
        duration_status = "on_target" if abs(actual - target_seconds) <= tolerance else ("under_target" if actual < target_seconds else "over_target")
    warnings: list[str] = []
    if duration_status == "over_target":
        warnings.append(
            f"安全精剪和最高 {normalized_policy['maxSpeed']:.2g}× 变速后仍为 {actual:.1f} 秒；"
            + ("手动选择不会被自动删除" if manual_selection else "需要减少低优先级完整镜头")
        )
    return {
        "segments": result,
        "cutaways": cutaways,
        "techniquePolicy": normalized_policy,
        "sourceDuration": source_duration,
        "effectiveDuration": actual,
        "minimumSafeDuration": minimum_safe,
        "targetSeconds": target_seconds,
        "durationStatus": duration_status,
        "warnings": warnings,
    }
