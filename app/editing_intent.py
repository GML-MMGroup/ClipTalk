from __future__ import annotations

import copy
import math
import re
from typing import Any


INTENT_SCHEMA_VERSION = 1

_EDITORIAL_EXCLUSIONS = {
    "重复镜头", "低价值拖尾", "黑屏", "模糊画面", "无价值停顿", "片头广告",
    "duplicate shots", "black frames", "dead air", "low value",
}


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[\n，,;；、]+", value)
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def compile_editing_intent(
    brief: dict[str, Any] | None,
    request: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compile user-facing choices into one executable editorial contract."""
    brief = brief if isinstance(brief, dict) else {}
    request = request if isinstance(request, dict) else {}
    target = _number(
        brief.get("targetDurationSeconds"),
        _number(request.get("totalTargetSeconds")),
    )
    tolerance_ratio = max(.03, min(.2, _number(request.get("durationTolerance"), .1) or .1))
    tolerance = max(2.0, target * tolerance_ratio) if target else None
    focus = _strings(brief.get("focus")) or _strings(request.get("theme")) or ["综合判断"]
    include = _strings(brief.get("includeRules") or brief.get("keep") or brief.get("mustKeep"))
    exclude = _strings(brief.get("excludeRules") or brief.get("exclude") or brief.get("mustExclude"))
    speakers = _strings(brief.get("speakerFocus"))
    style = brief.get("style") if isinstance(brief.get("style"), dict) else {}
    structure = str(brief.get("structure") or request.get("structure") or "auto")
    allow_reorder = bool(style.get("allowReorder", request.get("editMode") == "ai_plan"))
    event_count = brief.get("eventCount", request.get("count", "auto"))
    try:
        event_count = int(event_count) if str(event_count).lower() != "auto" else "auto"
    except (TypeError, ValueError):
        event_count = "auto"
    content_exclusions = [
        rule for rule in exclude
        if rule.lower() not in _EDITORIAL_EXCLUSIONS
        and not any(token in rule.lower() for token in ("重复", "黑屏", "拖尾", "停顿", "duplicate", "black frame"))
    ]
    pace = str(style.get("pace") or "自然")
    focus_text = " ".join(focus).lower()
    weights = {
        "visual": .24, "speech": .18, "emotion": .16,
        "story": .20, "goal": .22,
    }
    if any(token in focus_text for token in ("人物反应", "情绪", "表情", "reaction", "emotion")):
        weights.update({"emotion": .28, "visual": .22, "goal": .24, "speech": .10, "story": .16})
    elif any(token in focus_text for token in ("对白", "信息", "观点", "金句", "speech", "information")):
        weights.update({"speech": .30, "story": .22, "goal": .24, "visual": .14, "emotion": .10})
    elif any(token in focus_text for token in ("动作", "视觉冲击", "高潮", "action", "visual")):
        weights.update({"visual": .31, "emotion": .20, "goal": .23, "story": .16, "speech": .10})
    return {
        "schemaVersion": INTENT_SCHEMA_VERSION,
        "objective": str(brief.get("objective") or "事件高光合集"),
        "narrativeGoal": str(brief.get("narrativeGoal") or ""),
        "hardConstraints": {
            "targetSeconds": target,
            "toleranceSeconds": tolerance,
            "minimumSeconds": max(0.0, target - tolerance) if target and tolerance else None,
            "maximumSeconds": target + tolerance if target and tolerance else None,
            "eventCount": event_count,
            "includeRules": include,
            "excludeRules": exclude,
            "contentExclusions": content_exclusions,
            "speakerFocus": speakers,
            "preserveCompleteSpeech": True,
            "preserveCompleteActions": True,
            "forbidDuplicateSource": True,
            "aspectRatio": str(brief.get("aspectRatio") or "原始比例"),
        },
        "softGoals": {
            "focus": focus,
            "structure": structure,
            "qualityFirstEventCount": True,
            "preferCompleteEvents": True,
            "scoringWeights": weights,
        },
        "style": {
            "pace": pace,
            "tone": str(style.get("tone") or "纪实自然"),
            "allowReorder": allow_reorder,
        },
        "techniquePolicy": copy.deepcopy(brief.get("techniquePolicy") or request.get("techniquePolicy") or {}),
    }


def apply_user_feedback_to_brief(
    brief: dict[str, Any] | None,
    text: str,
) -> tuple[dict[str, Any], list[str]]:
    """Persist explicit revision language as executable brief constraints."""
    result = copy.deepcopy(brief) if isinstance(brief, dict) else {}
    message = str(text or "").strip()
    changes: list[str] = []
    if not message:
        return result, changes

    duration = re.search(r"(?:目标|总时长|成片|改成|调整为|控制在).*?(\d+(?:\.\d+)?)\s*(?:秒|s)\b", message, re.I)
    if duration:
        result["targetDurationSeconds"] = float(duration.group(1))
        changes.append(f"目标时长 {float(duration.group(1)):g} 秒")

    def add_rule(field: str, value: str, label: str) -> None:
        value = re.sub(r"(?:的)?(?:镜头|片段|内容)$", "", value.strip(" ，,。.!！?？；;：:"))
        if not value or value in {"这个", "这些", "它", "他们", "画面", "内容"}:
            return
        if field == "excludeRules" and any(token in value for token in ("太快", "截断", "打乱顺序", "调整顺序", "重排")):
            return
        rules = _strings(result.get(field))
        if value not in rules:
            rules.append(value)
            result[field] = rules
            changes.append(f"{label}“{value}”")

    for match in re.finditer(r"(?:不要|排除|去掉|删掉|避免)([^，,。.!！?？；;]{1,32})", message):
        add_rule("excludeRules", match.group(1), "排除")
    for match in re.finditer(r"(?:必须保留|一定要有|务必保留|保留)([^，,。.!！?？；;]{1,32})", message):
        add_rule("includeRules", match.group(1), "保留")

    focus_match = re.search(r"(?:更偏|重点(?:关注)?|多保留|突出)([^，,。.!！?？；;]{1,28})", message)
    if focus_match:
        focus = _strings(result.get("focus"))
        value = focus_match.group(1).strip()
        if value and value not in focus:
            focus.append(value)
            result["focus"] = focus
            changes.append(f"重点“{value}”")

    style = result.get("style") if isinstance(result.get("style"), dict) else {}
    if re.search(r"(?:开头|前面).{0,8}(?:太慢|拖沓)|(?:节奏|剪得).{0,6}(?:更快|紧凑)|快节奏", message):
        style["pace"] = "紧凑"
        result["style"] = style
        changes.append("节奏更紧凑")
    elif re.search(r"(?:节奏|剪得).{0,6}(?:自然|舒缓)|不要太快", message):
        style["pace"] = "自然"
        result["style"] = style
        changes.append("节奏保持自然")
    if re.search(r"(?:保持|按照).{0,8}(?:原顺序|时间顺序)|不要(?:调整|改变|打乱).{0,6}顺序", message):
        style["allowReorder"] = False
        result["style"] = style
        changes.append("保持源时间顺序")
    elif re.search(r"(?:允许|可以).{0,8}(?:重排|调整顺序)|重新编排", message):
        style["allowReorder"] = True
        result["style"] = style
        changes.append("允许重新编排")
    if re.search(r"(?:完整保留|不要截断|别截断).{0,8}(?:一句话|对白|说话|表达)", message):
        add_rule("includeRules", "对白表达完整", "保留")
    return result, list(dict.fromkeys(changes))


def _candidate_text(candidate: dict[str, Any]) -> str:
    audio = candidate.get("audioEvidence") if isinstance(candidate.get("audioEvidence"), dict) else {}
    speech = candidate.get("speechUnits") if isinstance(candidate.get("speechUnits"), list) else []
    values: list[Any] = [
        candidate.get("title"), candidate.get("groupTitle"), candidate.get("role"),
        candidate.get("storyFunction"), candidate.get("reason"), candidate.get("emotionDirection"),
        audio.get("transcriptExcerpt"), *(candidate.get("evidence") or []),
        *(unit.get("text") for unit in speech if isinstance(unit, dict)),
        *(audio.get("speakers") or []), *(audio.get("emotions") or []), *(audio.get("audioEvents") or []),
    ]
    return " ".join(str(value) for value in values if value).lower()


def _rule_matches_text(rule: str, text: str) -> bool:
    value = re.sub(r"\s+", "", str(rule or "").lower())
    compact = re.sub(r"\s+", "", text)
    if not value:
        return False
    if value in compact:
        return True
    english = re.findall(r"[a-z0-9]{2,}", value)
    chinese = re.findall(r"[\u4e00-\u9fff]+", value)
    pieces: list[str] = list(english)
    for chunk in chinese:
        if len(chunk) <= 2:
            pieces.append(chunk)
        else:
            pieces.extend(chunk[index:index + 2] for index in range(len(chunk) - 1))
    pieces = [piece for piece in pieces if piece not in {"镜头", "片段", "内容", "画面", "保留", "不要"}]
    if not pieces:
        return False
    hits = sum(piece in compact for piece in pieces)
    return hits >= max(1, math.ceil(len(pieces) * .6))


def candidate_requirement_alignment(candidate: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
    text = _candidate_text(candidate)
    hard = intent.get("hardConstraints") if isinstance(intent.get("hardConstraints"), dict) else {}
    soft = intent.get("softGoals") if isinstance(intent.get("softGoals"), dict) else {}
    focus = _strings(soft.get("focus"))
    includes = _strings(hard.get("includeRules"))
    exclusions = _strings(hard.get("contentExclusions"))
    speakers = _strings(hard.get("speakerFocus"))
    matched_focus = [value for value in focus if _rule_matches_text(value, text)]
    matched_include = [value for value in includes if _rule_matches_text(value, text)]
    matched_exclude = [value for value in exclusions if _rule_matches_text(value, text)]
    matched_speaker = [value for value in speakers if _rule_matches_text(value, text)]
    score = 50.0
    score += min(24.0, 12.0 * len(matched_focus))
    score += min(18.0, 9.0 * len(matched_include))
    if speakers:
        score += 14.0 if matched_speaker else -18.0
    score -= min(60.0, 30.0 * len(matched_exclude))
    return {
        "score": round(max(0.0, min(100.0, score)), 1),
        "hardRejected": bool(matched_exclude),
        "matchedFocus": matched_focus,
        "matchedInclude": matched_include,
        "matchedExclude": matched_exclude,
        "matchedSpeakers": matched_speaker,
    }


def evaluate_sequence_against_intent(
    segments: list[dict[str, Any]], intent: dict[str, Any],
) -> dict[str, Any]:
    hard = intent.get("hardConstraints") if isinstance(intent.get("hardConstraints"), dict) else {}
    style = intent.get("style") if isinstance(intent.get("style"), dict) else {}
    duration = sum(max(0.0, (
        _number(item.get("effectiveDuration"))
        or ((_number(item.get("end"), 0) or 0) - (_number(item.get("start"), 0) or 0))
    )) for item in segments)
    minimum = _number(hard.get("minimumSeconds"))
    maximum = _number(hard.get("maximumSeconds"))
    identities: set[str] = set()
    semantic: set[str] = set()
    duplicates: list[str] = []
    exclusions: list[dict[str, Any]] = []
    unsafe_speech: list[str] = []
    missing_context: list[dict[str, Any]] = []
    broken_story_edges: list[dict[str, Any]] = []
    include_rules = _strings(hard.get("includeRules"))
    covered_includes: set[str] = set()
    covered_speakers: set[str] = set()
    candidate_positions = {
        str(item.get("candidateIndex")): position
        for position, item in enumerate(segments)
        if item.get("candidateIndex") is not None
    }
    for item in segments:
        identity = str(item.get("id") or item.get("candidateId") or "")
        semantic_id = str(item.get("semanticUnitId") or item.get("candidateId") or identity)
        if identity and identity in identities:
            duplicates.append(identity)
        identities.add(identity)
        if semantic_id and semantic_id in semantic:
            duplicates.append(semantic_id)
        semantic.add(semantic_id)
        alignment = candidate_requirement_alignment(item, intent)
        covered_includes.update(alignment["matchedInclude"])
        covered_speakers.update(alignment["matchedSpeakers"])
        if alignment["hardRejected"]:
            exclusions.append({"segmentId": identity, "rules": alignment["matchedExclude"]})
        if str(item.get("speechBoundaryStatus") or "no_speech") not in {"complete", "adjusted", "no_speech"}:
            unsafe_speech.append(identity)
        position = candidate_positions.get(str(item.get("candidateIndex")))
        for required in item.get("requiresCandidateIndices") or []:
            required_position = candidate_positions.get(str(required))
            if required_position is None and not bool(item.get("standalone", True)):
                missing_context.append({"segmentId": identity, "requiredCandidateIndex": required})
            elif required_position is not None and position is not None and required_position > position:
                broken_story_edges.append({"from": required, "to": item.get("candidateIndex"), "type": "requires"})
        for target in item.get("leadsToCandidateIndices") or []:
            target_position = candidate_positions.get(str(target))
            if target_position is not None and position is not None and target_position < position:
                broken_story_edges.append({"from": item.get("candidateIndex"), "to": target, "type": "leads_to"})
    source_order_ok = bool(style.get("allowReorder")) or all(
        (_number(left.get("start"), 0) or 0) <= (_number(right.get("start"), 0) or 0)
        for left, right in zip(segments, segments[1:])
    )
    duration_ok = (minimum is None or duration >= minimum - .05) and (maximum is None or duration <= maximum + .05)
    generic_speech_rules = {
        rule for rule in include_rules
        if any(token in rule.lower() for token in ("对白完整", "对白表达完整", "完整表达", "完整一句话"))
    }
    if generic_speech_rules and not unsafe_speech:
        covered_includes.update(generic_speech_rules)
    if segments:
        covered_includes.update(rule for rule in include_rules if rule in {"关键事件", "精彩事件", "高光内容"})
    covered_includes.update(
        rule for rule in include_rules
        if "完整动作" in rule and all(bool(item.get("actionComplete", True)) for item in segments)
    )
    missing_includes = [rule for rule in include_rules if rule not in covered_includes]
    speaker_focus = _strings(hard.get("speakerFocus"))
    missing_speakers = [speaker for speaker in speaker_focus if speaker not in covered_speakers]
    issues: list[dict[str, Any]] = []
    if not duration_ok:
        issues.append({"category": "duration", "severity": "major", "description": "成片时长未进入用户目标区间"})
    if duplicates:
        issues.append({"category": "duplicate", "severity": "critical", "description": "成片存在重复源镜头", "segmentIds": duplicates})
    if exclusions:
        issues.append({"category": "excluded_content", "severity": "critical", "description": "成片包含用户要求排除的内容", "evidence": exclusions})
    if unsafe_speech:
        issues.append({"category": "speech_boundary", "severity": "critical", "description": "对白边界未验证完整", "segmentIds": unsafe_speech})
    if not source_order_ok:
        issues.append({"category": "order", "severity": "major", "description": "当前需求不允许重排，但镜头未按源时间排列"})
    if missing_context:
        issues.append({"category": "missing_context", "severity": "major", "description": "非独立镜头缺少必要上下文", "evidence": missing_context})
    if broken_story_edges:
        issues.append({"category": "story_order", "severity": "major", "description": "镜头顺序破坏已识别的因果或递进关系", "evidence": broken_story_edges})
    if missing_includes:
        issues.append({"category": "required_content", "severity": "critical", "description": "成片未覆盖用户明确要求保留的内容", "evidence": missing_includes})
    if missing_speakers:
        issues.append({"category": "required_speaker", "severity": "critical", "description": "成片未覆盖用户指定的说话人", "evidence": missing_speakers})
    alignments = [candidate_requirement_alignment(item, intent)["score"] for item in segments]
    alignment_score = sum(alignments) / len(alignments) if alignments else 0.0
    score = alignment_score
    score -= 18 if not duration_ok else 0
    score -= 35 if duplicates else 0
    score -= 45 if exclusions else 0
    score -= 35 if unsafe_speech else 0
    score -= 18 if not source_order_ok else 0
    score -= min(24, len(missing_context) * 8)
    score -= min(24, len(broken_story_edges) * 8)
    score -= min(45, len(missing_includes) * 18)
    score -= min(45, len(missing_speakers) * 22)
    return {
        "schemaVersion": INTENT_SCHEMA_VERSION,
        "passed": bool(segments) and not any(item["severity"] == "critical" for item in issues),
        "hardConstraintsPassed": not issues,
        "score": round(max(0.0, min(100.0, score)), 1),
        "duration": round(duration, 3),
        "durationPassed": duration_ok,
        "sourceOrderPassed": source_order_ok,
        "duplicateIds": list(dict.fromkeys(duplicates)),
        "excludedMatches": exclusions,
        "unsafeSpeechSegmentIds": unsafe_speech,
        "missingContext": missing_context,
        "brokenStoryEdges": broken_story_edges,
        "missingIncludeRules": missing_includes,
        "missingSpeakers": missing_speakers,
        "issues": issues,
    }
