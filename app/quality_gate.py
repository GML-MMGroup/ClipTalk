from __future__ import annotations

import copy
import math
from typing import Any

from .editing_intent import evaluate_sequence_against_intent
from .editing_techniques import composition_effective_duration, normalize_audio_bridge, normalize_transition


QUALITY_GATE_VERSION = "composition-quality-v3"
PASS_SCORE = 75.0
RECOMMEND_SCORE = 82.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _identity(item: dict[str, Any], index: int) -> str:
    return str(item.get("id") or item.get("candidateId") or f"segment_{index + 1}")


def _event_id(item: dict[str, Any]) -> str:
    return str(item.get("groupId") or item.get("chapterId") or item.get("eventId") or "")


def _protected_role(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or item.get("storyFunction") or "").lower()
    return any(token in role for token in (
        "高潮", "反应", "结果", "结尾", "收束", "关键动作",
        "climax", "reaction", "result", "ending", "action",
    ))


def _issue(
    category: str, severity: str, description: str, *, segment_ids: list[str] | None = None,
    evidence: Any = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "category": category,
        "severity": severity,
        "description": description,
    }
    if segment_ids:
        result["segmentIds"] = segment_ids
    if evidence is not None:
        result["evidence"] = evidence
    return result


def _issue_key(item: dict[str, Any]) -> tuple[Any, ...]:
    category = str(item.get("category") or "editorial").lower()
    segment_ids = tuple(sorted(str(value) for value in item.get("segmentIds") or [] if str(value)))
    description = "".join(str(item.get("description") or "").lower().split())
    # Reports from VLM, LLM and deterministic checks frequently describe the
    # same cut with different prose. Category + affected segments is the most
    # stable identity; use a short text prefix only when no segment is known.
    return (category, segment_ids, "" if segment_ids else description[:36])


def deduplicate_issues(*collections: Any) -> list[dict[str, Any]]:
    severity_rank = {"minor": 1, "major": 2, "critical": 3}
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    order: list[tuple[Any, ...]] = []
    for collection in collections:
        for raw in collection if isinstance(collection, list) else []:
            if not isinstance(raw, dict):
                continue
            item = copy.deepcopy(raw)
            severity = str(item.get("severity") or "minor").lower()
            item["severity"] = severity if severity in severity_rank else "minor"
            key = _issue_key(item)
            previous = merged.get(key)
            if previous is None:
                merged[key] = item
                order.append(key)
            elif severity_rank[item["severity"]] > severity_rank[str(previous.get("severity") or "minor")]:
                merged[key] = item
    return [merged[key] for key in order]


def validate_edit_sequence(
    segments: list[dict[str, Any]], *, editing_intent: dict[str, Any] | None = None,
    target_seconds: float | None = None, insufficient_evidence: bool = False,
    require_verified_uncertainty: bool = True,
) -> dict[str, Any]:
    """Validate an executable EDL before any automatic preview is exposed.

    A reel may contain multiple event chapters.  Each contiguous chapter must
    stay internally coherent; different chapters must not be disguised as a
    continuous event with dissolves or audio bridges.
    """
    sequence = [item for item in segments if isinstance(item, dict)]
    duration = composition_effective_duration(sequence)
    intent_report = evaluate_sequence_against_intent(sequence, editing_intent or {})
    issues = list(intent_report.get("issues") or [])
    event_runs: list[str] = []
    seen_events: set[str] = set()
    repeated_events: set[str] = set()
    unresolved: list[str] = []
    clipped_actions: list[str] = []
    unsafe_speed: list[str] = []

    for index, item in enumerate(sequence):
        identity = _identity(item, index)
        event_id = _event_id(item)
        if event_id and (not event_runs or event_runs[-1] != event_id):
            if event_id in seen_events:
                repeated_events.add(event_id)
            event_runs.append(event_id)
            seen_events.add(event_id)
        uncertainty = item.get("uncertainty") if isinstance(item.get("uncertainty"), dict) else {}
        verification = item.get("verificationState") if isinstance(item.get("verificationState"), dict) else {}
        if require_verified_uncertainty and bool(uncertainty.get("requiresDynamicReview")):
            if str(verification.get("status") or "unverified") not in {"verified", "not_required"}:
                unresolved.append(identity)
        if item.get("actionComplete") is False and _protected_role(item):
            clipped_actions.append(identity)
        if _protected_role(item) and _number(item.get("playbackRate"), 1.0) > 1.001:
            unsafe_speed.append(identity)

        if index <= 0:
            continue
        previous = sequence[index - 1]
        previous_event = _event_id(previous)
        if event_id and previous_event and event_id != previous_event:
            transition = normalize_transition(item.get("transitionIn"))
            bridge = normalize_audio_bridge(item.get("audioBridge"))
            if transition["type"] == "dissolve":
                issues.append(_issue(
                    "cross_event_dissolve", "critical",
                    "不同事件章节之间使用了溶解，容易造成虚假的连续时空关系",
                    segment_ids=[_identity(previous, index - 1), identity],
                ))
            if bridge["type"] != "none":
                issues.append(_issue(
                    "cross_event_audio_bridge", "critical",
                    "不同事件章节之间不能使用 J-cut/L-cut 声音桥",
                    segment_ids=[_identity(previous, index - 1), identity],
                ))

    if repeated_events:
        issues.append(_issue(
            "interleaved_chapters", "major",
            "同一事件被其他事件打断后再次出现，章节内部关系被拆散",
            evidence=sorted(repeated_events),
        ))
    if unresolved:
        issues.append(_issue(
            "unverified_evidence", "critical",
            "关键镜头仍存在未完成的动态证据复核",
            segment_ids=unresolved,
        ))
    if clipped_actions:
        issues.append(_issue(
            "action_boundary", "critical",
            "高潮、结果或关键动作镜头的动作边界不完整",
            segment_ids=clipped_actions,
        ))
    if unsafe_speed:
        issues.append(_issue(
            "protected_speed", "critical",
            "高潮、人物反应或结果镜头不能自动加速",
            segment_ids=unsafe_speed,
        ))

    duration_ratio = None
    duration_passed = True
    if target_seconds and target_seconds > 0:
        duration_ratio = duration / target_seconds
        if duration_ratio > 1.15 + .001:
            duration_passed = False
            issues.append(_issue(
                "duration_overflow", "critical",
                f"成片 {duration:.1f} 秒，超过目标时长允许上限 15%",
            ))
        elif duration_ratio < .80 - .001:
            duration_passed = False
            severity = "major" if insufficient_evidence else "critical"
            issues.append(_issue(
                "duration_shortfall", severity,
                f"成片 {duration:.1f} 秒，低于目标时长 20% 以上"
                + ("；已确认素材不足，允许保留完整表达但不能作为推荐版本" if insufficient_evidence else ""),
            ))

    issues = deduplicate_issues(issues)
    critical = [item for item in issues if item.get("severity") == "critical"]
    hard_passed = bool(sequence) and not critical and bool(intent_report.get("passed"))
    return {
        "schemaVersion": 1,
        "qualityGateVersion": QUALITY_GATE_VERSION,
        "passed": hard_passed and duration_passed,
        "hardConstraintsPassed": hard_passed,
        "durationPassed": duration_passed,
        "duration": round(duration, 3),
        "targetSeconds": target_seconds,
        "durationRatio": round(duration_ratio, 4) if duration_ratio is not None else None,
        "chapterCount": len(event_runs),
        "eventIds": event_runs,
        "multiEventComposition": len(event_runs) > 1,
        "intentValidation": intent_report,
        "criticalCount": len(critical),
        "majorCount": sum(item.get("severity") == "major" for item in issues),
        "issues": issues,
    }


def build_quality_gate(
    review_report: dict[str, Any] | None,
    sequence_validation: dict[str, Any] | None,
) -> dict[str, Any]:
    review = review_report if isinstance(review_report, dict) else {}
    validation = sequence_validation if isinstance(sequence_validation, dict) else {}
    score = _number(review.get("calibratedScore"), _number(review.get("overallScore"), 0.0))
    issues = deduplicate_issues(validation.get("issues") or [], review.get("issues") or [], review.get("deterministicChecks") or [])
    critical = [item for item in issues if item.get("severity") == "critical"]
    passed = bool(validation.get("passed")) and not critical and score >= PASS_SCORE
    recommended = passed and score >= RECOMMEND_SCORE
    reasons: list[str] = []
    if not validation.get("passed"):
        reasons.append("剪辑序列未通过边界、章节或用户硬约束校验")
    if critical:
        reasons.append(f"仍有 {len(critical)} 个关键问题")
    if score < PASS_SCORE:
        reasons.append(f"校准审片得分 {score:.1f}，低于展示门槛 {PASS_SCORE:.0f}")
    elif score < RECOMMEND_SCORE:
        reasons.append(f"已达到可展示门槛，但未达到推荐门槛 {RECOMMEND_SCORE:.0f}")
    return {
        "schemaVersion": 1,
        "qualityGateVersion": QUALITY_GATE_VERSION,
        "passed": passed,
        "recommended": recommended,
        "score": round(score, 1),
        "passThreshold": PASS_SCORE,
        "recommendThreshold": RECOMMEND_SCORE,
        "criticalCount": len(critical),
        "majorCount": sum(item.get("severity") == "major" for item in issues),
        "reasons": reasons,
        "issues": issues[:20],
    }
