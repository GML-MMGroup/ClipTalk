from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any, Iterable


EVIDENCE_GRAPH_VERSION = 2
PIPELINE_VERSION = "quality-loop-v3"


CONTENT_WEIGHTS: dict[str, dict[str, float]] = {
    "访谈口播": {"userMatch": .30, "speechValue": .25, "completeness": .20, "visualIntensity": .10, "novelty": .10, "technicalQuality": .05},
    "新闻纪实": {"userMatch": .25, "eventValue": .25, "speechValue": .20, "completeness": .15, "novelty": .10, "technicalQuality": .05},
    "体育游戏": {"eventValue": .30, "visualIntensity": .22, "audioIntensity": .13, "novelty": .15, "userMatch": .15, "technicalQuality": .05},
    "直播PK": {"eventValue": .25, "visualIntensity": .25, "userMatch": .20, "audioIntensity": .10, "novelty": .15, "technicalQuality": .05},
    "Vlog教程": {"completeness": .25, "eventValue": .22, "userMatch": .20, "visualIntensity": .12, "novelty": .11, "technicalQuality": .10},
    "表演音乐": {"audioIntensity": .24, "visualIntensity": .24, "eventValue": .20, "userMatch": .17, "novelty": .10, "technicalQuality": .05},
    "产品展示": {"userMatch": .25, "eventValue": .25, "completeness": .20, "speechValue": .12, "novelty": .10, "technicalQuality": .08},
    "综合": {"userMatch": .24, "eventValue": .22, "completeness": .17, "visualIntensity": .13, "speechValue": .09, "audioIntensity": .05, "novelty": .07, "technicalQuality": .03},
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _content_route(profile: dict[str, Any]) -> str:
    text = " ".join([
        str(profile.get("primaryType") or ""),
        *[str(value) for value in profile.get("secondaryTypes") or []],
        str(profile.get("narrativeMode") or ""),
    ]).lower()
    if any(token in text for token in ("直播", "pk", "互动")):
        return "直播PK"
    if any(token in text for token in ("体育", "比赛", "游戏", "电竞")):
        return "体育游戏"
    if any(token in text for token in ("新闻", "纪实", "调查", "报道")):
        return "新闻纪实"
    if any(token in text for token in ("访谈", "口播", "采访", "对白")):
        return "访谈口播"
    if any(token in text for token in ("vlog", "教程", "手工", "步骤", "生活")):
        return "Vlog教程"
    if any(token in text for token in ("音乐", "表演", "演唱", "舞台")):
        return "表演音乐"
    if any(token in text for token in ("产品", "商品", "演示", "测评")):
        return "产品展示"
    return "综合"


def _intent_values(intent: dict[str, Any] | None) -> tuple[list[str], list[str], list[str]]:
    intent = intent if isinstance(intent, dict) else {}
    hard = intent.get("hardConstraints") if isinstance(intent.get("hardConstraints"), dict) else {}
    soft = intent.get("softGoals") if isinstance(intent.get("softGoals"), dict) else {}
    return (
        _strings(soft.get("focus")),
        _strings(hard.get("includeRules")),
        _strings(hard.get("contentExclusions") or hard.get("excludeRules")),
    )


def _text_match_score(text: str, values: Iterable[str]) -> float:
    compact = re.sub(r"\s+", "", text.lower())
    values = [re.sub(r"\s+", "", str(value).lower()) for value in values if str(value).strip()]
    if not values:
        return 65.0
    matches = 0.0
    for value in values:
        if value in compact:
            matches += 1.0
            continue
        chunks = re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}", value)
        if chunks and sum(chunk in compact for chunk in chunks) >= max(1, math.ceil(len(chunks) * .6)):
            matches += .7
    return min(100.0, 45.0 + 55.0 * matches / max(1, len(values)))


def _unit_score_vector(candidate: dict[str, Any], intent: dict[str, Any] | None) -> dict[str, float]:
    score = max(0.0, min(100.0, _number(candidate.get("score"), 50.0)))
    confidence = max(0.0, min(1.0, _number(candidate.get("boundaryConfidence"), .55)))
    audio = candidate.get("audioEvidence") if isinstance(candidate.get("audioEvidence"), dict) else {}
    evidence = _strings(candidate.get("evidence"))
    transcript = str(audio.get("transcriptExcerpt") or "")
    text = " ".join([
        str(candidate.get("title") or ""), str(candidate.get("reason") or ""),
        str(candidate.get("role") or ""), transcript, *evidence,
        *[str(value) for value in audio.get("emotions") or []],
        *[str(value) for value in audio.get("audioEvents") or []],
    ])
    focus, includes, excludes = _intent_values(intent)
    user_match = _text_match_score(text, [*focus, *includes])
    if any(re.sub(r"\s+", "", value.lower()) in re.sub(r"\s+", "", text.lower()) for value in excludes):
        user_match = 0.0
    duration = max(.01, _number(candidate.get("end")) - _number(candidate.get("start")))
    minimum = max(.01, _number(candidate.get("minimumKeepSeconds"), min(duration, 2.0)))
    complete = min(100.0, 55.0 + 35.0 * confidence + 10.0 * min(1.0, duration / minimum))
    role = str(candidate.get("role") or "").lower()
    visual_boost = 12.0 if any(token in role for token in ("高潮", "反应", "动作", "climax", "reaction")) else 0.0
    speech_value = min(100.0, 35.0 + (45.0 if transcript else 0.0) + 5.0 * len(audio.get("speakers") or []))
    audio_value = min(100.0, 35.0 + 12.0 * len(audio.get("emotions") or []) + 10.0 * len(audio.get("audioEvents") or []))
    return {
        "userMatch": round(user_match, 1),
        "eventValue": round(score, 1),
        "completeness": round(complete, 1),
        "visualIntensity": round(min(100.0, score * .78 + visual_boost), 1),
        "speechValue": round(speech_value, 1),
        "audioIntensity": round(audio_value, 1),
        "novelty": round(max(45.0, min(100.0, 55.0 + len(evidence) * 6.0)), 1),
        "technicalQuality": round(max(50.0, min(100.0, 70.0 + confidence * 25.0)), 1),
        "confidence": round(confidence * 100.0, 1),
    }


def _weighted_score(scores: dict[str, float], route: str) -> float:
    weights = CONTENT_WEIGHTS.get(route, CONTENT_WEIGHTS["综合"])
    return round(sum(scores.get(key, 50.0) * weight for key, weight in weights.items()), 1)


def _facts(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    confidence = max(.35, min(1.0, _number(candidate.get("boundaryConfidence"), .55)))
    values: list[dict[str, Any]] = []
    for index, evidence in enumerate(_strings(candidate.get("evidence"))[:8], 1):
        values.append({
            "source": "vlm", "type": "visual_observation", "value": evidence,
            "confidence": round(confidence, 3), "evidenceRefs": [f"candidate:{candidate.get('index', 0)}:evidence:{index}"],
        })
    audio = candidate.get("audioEvidence") if isinstance(candidate.get("audioEvidence"), dict) else {}
    if str(audio.get("transcriptExcerpt") or "").strip():
        values.append({"source": "sensevoice", "type": "transcript", "value": str(audio["transcriptExcerpt"])[:800], "confidence": .86, "evidenceRefs": []})
    for emotion in _strings(audio.get("emotions"))[:4]:
        values.append({"source": "sensevoice", "type": "emotion", "value": emotion, "confidence": .72, "evidenceRefs": []})
    for event in _strings(audio.get("audioEvents"))[:4]:
        values.append({"source": "sensevoice", "type": "audio_event", "value": event, "confidence": .74, "evidenceRefs": []})
    return values


def _safe_ranges(candidate: dict[str, Any]) -> dict[str, Any]:
    start = round(max(0.0, _number(candidate.get("start"))), 3)
    end = round(max(start, _number(candidate.get("end"), start)), 3)
    peak_start = round(max(start, min(end, _number(candidate.get("peakStart"), start))), 3)
    peak_end = round(max(peak_start, min(end, _number(candidate.get("peakEnd"), end))), 3)
    speech_start = _number(candidate.get("speechAlignedStart"), start)
    speech_end = _number(candidate.get("speechAlignedEnd"), end)
    return {
        "full": {"start": start, "end": end},
        "speech": {"start": round(max(0.0, min(start, speech_start)), 3), "end": round(max(end, speech_end), 3)},
        "action": {"start": start, "end": end},
        "peak": {"start": peak_start, "end": peak_end},
        "minimumKeepSeconds": round(max(.8, min(end - start, _number(candidate.get("minimumKeepSeconds"), 2.0))), 3),
    }


def _relations(candidate: dict[str, Any], index_to_id: dict[str, str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for relation, field in (("requires", "requiresCandidateIndices"), ("leads_to", "leadsToCandidateIndices")):
        for value in candidate.get(field) or []:
            target = index_to_id.get(str(value))
            if target and not any(item["type"] == relation and item["target"] == target for item in result):
                result.append({"type": relation, "target": target})
    return result


def _macro_chapters(duration: float, profile: dict[str, Any], units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    duration = max(0.0, duration)
    span = 300.0 if duration >= 900 else max(60.0, min(240.0, duration / max(1, math.ceil(duration / 180.0))))
    chapters: list[dict[str, Any]] = []
    cursor = 0.0
    while cursor < duration - .01:
        end = min(duration, cursor + span)
        unit_ids = [unit["unitId"] for unit in units if unit["range"]["end"] > cursor and unit["range"]["start"] < end]
        chapters.append({
            "chapterId": f"chapter_{len(chapters) + 1:03d}", "start": round(cursor, 3), "end": round(end, 3),
            "contentType": profile.get("primaryType") or "综合视频", "unitIds": unit_ids,
            "evidenceCovered": bool(unit_ids),
        })
        cursor = end
    return chapters


def build_evidence_graph(
    manifest: dict[str, Any], *, intent: dict[str, Any] | None = None,
    source_hash: str = "", model_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = [item for item in manifest.get("candidates") or [] if isinstance(item, dict)]
    profile = dict(manifest.get("contentProfile") or {})
    route = _content_route(profile)
    index_to_id = {
        str(candidate.get("index", index)): str(candidate.get("candidateId") or f"unit_{index + 1:04d}")
        for index, candidate in enumerate(candidates)
    }
    units: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        unit_id = index_to_id[str(candidate.get("index", index))]
        ranges = _safe_ranges(candidate)
        scores = _unit_score_vector(candidate, intent)
        confidence = scores["confidence"] / 100.0
        reasons: list[str] = []
        if confidence < .72:
            reasons.append("视觉或边界置信度低于深度复核阈值")
        if str(candidate.get("speechBoundaryStatus") or "") not in {"", "complete", "adjusted", "no_speech"}:
            reasons.append("话语边界与视觉范围存在冲突")
        if str(candidate.get("role") or "").lower() in {"高潮", "结果", "climax", "result"} and confidence < .82:
            reasons.append("关键故事职责仍需确认动态边界")
        units.append({
            "unitId": unit_id,
            "candidateIndex": int(candidate.get("index", index)),
            "range": dict(ranges["full"]),
            "safeRanges": ranges,
            "title": str(candidate.get("title") or "精彩镜头")[:120],
            "role": str(candidate.get("role") or "highlight")[:50],
            "possibleEvent": str(candidate.get("possibleEvent") or candidate.get("possible_event") or "")[:120],
            "reason": str(candidate.get("reason") or "")[:800],
            "facts": _facts(candidate),
            "scores": {**scores, "composite": _weighted_score(scores, route)},
            "relations": [],
            "uncertainty": {"value": round(1.0 - confidence, 3), "reasons": reasons, "requiresDynamicReview": bool(reasons)},
            "provenance": {"candidateId": str(candidate.get("candidateId") or ""), "selectionBackend": manifest.get("selectionBackend")},
        })
    for unit, candidate in zip(units, candidates):
        unit["relations"] = _relations(candidate, index_to_id)

    unit_by_candidate = {str(unit["candidateIndex"]): unit["unitId"] for unit in units}
    unit_by_id = {unit["unitId"]: unit for unit in units}
    events: list[dict[str, Any]] = []
    for position, group in enumerate(manifest.get("eventGroups") or [], 1):
        if not isinstance(group, dict):
            continue
        ids: list[str] = []
        for segment in [*(group.get("segments") or []), *(group.get("availableSegments") or [])]:
            if not isinstance(segment, dict):
                continue
            value = str(segment.get("candidateId") or "")
            if not value and segment.get("candidateIndex") is not None:
                value = unit_by_candidate.get(str(segment.get("candidateIndex")), "")
            if value in unit_by_id and value not in ids:
                ids.append(value)
        events.append({
            "eventId": str(group.get("id") or f"event_{position:03d}"),
            "title": str(group.get("title") or f"精彩事件 {position}")[:160],
            "summary": str(group.get("summary") or group.get("reason") or "")[:1000],
            "score": round(_number(group.get("score"), 0.0), 1),
            "unitIds": ids,
            "recommended": str(group.get("id")) in {str(value) for value in manifest.get("recommendedGroupIds") or []},
        })
    duration = _number((manifest.get("video") or {}).get("duration"), 0.0)
    chapters = _macro_chapters(duration, profile, units)
    for unit in units:
        chapter = next((item for item in chapters if item["start"] <= unit["range"]["start"] < item["end"]), None)
        unit["chapterId"] = chapter["chapterId"] if chapter else None
    covered = sum(max(0.0, chapter["end"] - chapter["start"]) for chapter in chapters if chapter["evidenceCovered"])
    uncertain = [unit for unit in units if unit["uncertainty"]["requiresDynamicReview"]]
    usage = [item for item in manifest.get("usage") or [] if isinstance(item, dict)]
    graph = {
        "schemaVersion": EVIDENCE_GRAPH_VERSION,
        "pipelineVersion": PIPELINE_VERSION,
        "sourceHash": source_hash,
        "profile": {**profile, "routingType": route},
        "chapters": chapters,
        "units": units,
        "events": events,
        "coverage": {
            "duration": round(duration, 3), "chapterCount": len(chapters),
            "coveredChapterCount": sum(bool(item["evidenceCovered"]) for item in chapters),
            "coverageRatio": round(covered / duration, 4) if duration else 0.0,
        },
        "modelBudget": {
            "vlmUsed": int((model_budget or {}).get("vlmUsed") if not usage and (model_budget or {}).get("vlmUsed") is not None else len(usage)),
            "vlmLimit": int((model_budget or {}).get("vlmLimit") or max(len(usage), 1)),
            "llmUsed": int((model_budget or {}).get("llmUsed") or 0), "llmLimit": int((model_budget or {}).get("llmLimit") or 4),
            "uncertaintyAllowance": 2,
        },
        "uncertainUnitIds": [unit["unitId"] for unit in sorted(uncertain, key=lambda item: -item["scores"]["composite"])],
        "provenance": {"promptVersion": manifest.get("promptVersion"), "selectionBackend": manifest.get("selectionBackend")},
    }
    graph["graphHash"] = evidence_graph_hash(graph)
    return graph


def evidence_graph_hash(graph: dict[str, Any]) -> str:
    payload = {
        "schemaVersion": graph.get("schemaVersion"), "sourceHash": graph.get("sourceHash"),
        "profile": graph.get("profile"), "units": graph.get("units"), "events": graph.get("events"),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def evidence_summary(graph: dict[str, Any] | None) -> dict[str, Any]:
    graph = graph if isinstance(graph, dict) else {}
    coverage = graph.get("coverage") if isinstance(graph.get("coverage"), dict) else {}
    return {
        "schemaVersion": graph.get("schemaVersion"), "graphHash": graph.get("graphHash"),
        "unitCount": len(graph.get("units") or []), "eventCount": len(graph.get("events") or []),
        "chapterCount": len(graph.get("chapters") or []),
        "coverageRatio": coverage.get("coverageRatio"),
        "uncertainUnitCount": len(graph.get("uncertainUnitIds") or []),
        "routingType": (graph.get("profile") or {}).get("routingType"),
    }


def select_evidence(
    graph: dict[str, Any], *, unit_ids: Iterable[str] | None = None,
    start: float | None = None, end: float | None = None,
) -> dict[str, Any]:
    requested = {str(value) for value in unit_ids or [] if str(value)}
    units = []
    for unit in graph.get("units") or []:
        if requested and str(unit.get("unitId")) not in requested:
            continue
        if start is not None and _number(unit.get("range", {}).get("end")) <= start:
            continue
        if end is not None and _number(unit.get("range", {}).get("start")) >= end:
            continue
        units.append(unit)
    selected_ids = {str(unit.get("unitId")) for unit in units}
    events = [
        event for event in graph.get("events") or []
        if selected_ids.intersection(str(value) for value in event.get("unitIds") or [])
    ]
    return {"schemaVersion": graph.get("schemaVersion"), "graphHash": graph.get("graphHash"), "units": units, "events": events}


def feedback_route(text: str, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    value = str(text or "").strip()
    lowered = value.lower()
    if re.search(r"重新通看|重新分析全片|从头分析|完整重分析", value):
        route = "full_reanalysis"
    elif re.search(r"顺序|重排|先.*后|放到.*前|放到.*后", value):
        route = "pure_reorder"
    elif re.search(r"提前|延长|缩短|结尾|开头|起点|终点|边界", value):
        route = "local_boundary_edit"
    elif re.search(r"换一批|完全不同|不要重复|其他内容", value):
        route = "evidence_rescore"
    elif re.search(r"识别错|其实是|界面|logo|标志|屏幕文字|动作没识别|没有识别", lowered):
        route = "targeted_visual_search"
    elif re.search(r"更偏|重点|不要|排除|保留|目标|时长|节奏|字幕|说话人|speaker", lowered):
        route = "intent_update"
    else:
        route = "intent_update"
    return {
        "route": route,
        "requiresVlm": route in {"targeted_visual_search", "full_reanalysis"},
        "reuseEvidenceGraph": route != "full_reanalysis" and bool(graph),
    }
