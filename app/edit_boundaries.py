from __future__ import annotations

import copy
import math
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def normalized_speech_segments(segments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in segments or []:
        if not isinstance(item, dict):
            continue
        start = max(0.0, _number(item.get("start")))
        end = max(start, _number(item.get("end"), start))
        text = str(item.get("text") or "").strip()
        if end - start < .08 or not text:
            continue
        result.append({**item, "start": start, "end": end, "text": text})
    return sorted(result, key=lambda item: (item["start"], item["end"]))


def normalized_silences(intervals: list[dict[str, Any]] | None) -> list[dict[str, float]]:
    result: list[dict[str, float]] = []
    for item in intervals or []:
        if not isinstance(item, dict):
            continue
        start = max(0.0, _number(item.get("start")))
        end = max(start, _number(item.get("end"), start))
        if end - start >= .12:
            result.append({"start": start, "end": end, "duration": end - start})
    return sorted(result, key=lambda item: item["start"])


def _speech_containing(value: float, segments: list[dict[str, Any]], margin: float = .08) -> dict[str, Any] | None:
    return next(
        (item for item in segments if item["start"] + margin < value < item["end"] - margin),
        None,
    )


def _safe_start_inside_speech(value: float, speech: dict[str, Any], silences: list[dict[str, float]]) -> tuple[float, str]:
    internal = [
        item["end"] for item in silences
        if speech["start"] + .08 <= item["end"] <= value and item["start"] < value
    ]
    if internal:
        return max(internal), "silence_end"
    return float(speech["start"]), "speech_start"


def _safe_end_inside_speech(value: float, speech: dict[str, Any], silences: list[dict[str, float]]) -> tuple[float, str]:
    internal = [
        item["start"] for item in silences
        if value <= item["start"] <= speech["end"] - .08 and item["end"] > value
    ]
    if internal:
        return min(internal), "silence_start"
    return float(speech["end"]), "speech_end"


def semantic_safe_range(
    start: float,
    end: float,
    *,
    speech_segments: list[dict[str, Any]] | None = None,
    silences: list[dict[str, Any]] | None = None,
    lower_bound: float = 0.0,
    upper_bound: float | None = None,
) -> dict[str, Any]:
    """Expand unsafe speech cuts to a VAD/silence boundary.

    This intentionally expands rather than shortens a spoken expression. A
    later event selector may drop a whole shot or event when the expanded
    duration does not fit the requested reel.
    """
    original_start = max(lower_bound, _number(start))
    original_end = max(original_start, _number(end, original_start))
    safe_start, safe_end = original_start, original_end
    sources: list[str] = []
    speech = normalized_speech_segments(speech_segments)
    quiet = normalized_silences(silences)
    start_speech = _speech_containing(safe_start, speech)
    if start_speech:
        safe_start, source = _safe_start_inside_speech(safe_start, start_speech, quiet)
        sources.append(source)
    end_speech = _speech_containing(safe_end, speech)
    if end_speech:
        safe_end, source = _safe_end_inside_speech(safe_end, end_speech, quiet)
        sources.append(source)
    safe_start = max(lower_bound, safe_start)
    if upper_bound is not None:
        safe_end = min(max(safe_start, float(upper_bound)), safe_end)
    safe_end = max(safe_start, safe_end)
    adjusted = abs(safe_start - original_start) > .01 or abs(safe_end - original_end) > .01
    overlaps_speech = any(item["end"] > safe_start and item["start"] < safe_end for item in speech)
    return {
        "start": round(safe_start, 3),
        "end": round(safe_end, 3),
        "originalStart": round(original_start, 3),
        "originalEnd": round(original_end, 3),
        "boundarySource": "+".join(dict.fromkeys(sources)) if sources else ("speech_aligned" if overlaps_speech else "visual"),
        "speechBoundaryStatus": "adjusted" if adjusted else ("complete" if overlaps_speech else "no_speech"),
        "boundaryAdjusted": adjusted,
        "hasSpeech": overlaps_speech,
    }


def annotate_candidate_boundaries(
    candidates: list[dict[str, Any]],
    *,
    speech_segments: list[dict[str, Any]] | None = None,
    silences: list[dict[str, Any]] | None = None,
    duration: float | None = None,
) -> list[dict[str, Any]]:
    speech = normalized_speech_segments(speech_segments)
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        item = copy.deepcopy(candidate)
        safe = semantic_safe_range(
            _number(item.get("start")), _number(item.get("end")),
            speech_segments=speech_segments, silences=silences,
            upper_bound=duration,
        )
        item.update({
            "start": safe["start"], "end": safe["end"],
            "duration": round(safe["end"] - safe["start"], 3),
            "safeStart": safe["start"], "safeEnd": safe["end"],
            "originalStart": safe["originalStart"], "originalEnd": safe["originalEnd"],
            "boundarySource": safe["boundarySource"],
            "speechBoundaryStatus": safe["speechBoundaryStatus"],
            "boundaryAdjusted": safe["boundaryAdjusted"],
            "hasSpeech": safe["hasSpeech"],
        })
        if safe["hasSpeech"]:
            overlapping = [
                segment for segment in speech
                if segment["end"] > safe["start"] and segment["start"] < safe["end"]
            ]
            peak_start = max(safe["start"], _number(item.get("peakStart"), safe["start"]))
            peak_end = min(safe["end"], max(peak_start, _number(item.get("peakEnd"), safe["end"])))
            peak_center = (peak_start + peak_end) / 2
            primary = max(overlapping, key=lambda segment: (
                max(0.0, min(peak_end, segment["end"]) - max(peak_start, segment["start"])),
                -abs((segment["start"] + segment["end"]) / 2 - peak_center),
            )) if overlapping else None
            speech_units = [{
                "id": str(segment.get("id") or f"speech_{index}"),
                "start": round(segment["start"], 3), "end": round(segment["end"], 3),
                "duration": round(segment["end"] - segment["start"], 3),
                "text": str(segment.get("text") or "")[:500],
            } for index, segment in enumerate(overlapping)]
            item["speechUnits"] = speech_units
            item["speechUnitCount"] = len(speech_units)
            model_floor = max(.35, _number(item.get("minimumKeepSeconds"), .35))
            speech_floor = (primary["end"] - primary["start"]) if primary else model_floor
            # A candidate may contain several complete sentences. Preserve at
            # least the sentence around the visual peak, not the entire broad
            # VLM window. This lets several complete spoken events coexist in
            # a target-length reel without cutting any sentence in half.
            item["minimumKeepSeconds"] = round(min(
                item["duration"], max(model_floor, speech_floor),
            ), 3)
        result.append(item)
    return result


def load_transcript_segments(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("segments")
    return normalized_speech_segments(payload if isinstance(payload, list) else [])
