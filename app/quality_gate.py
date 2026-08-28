from __future__ import annotations

import copy
import math
from typing import Any

from .editing_intent import evaluate_sequence_against_intent
from .editing_techniques import composition_effective_duration, normalize_audio_bridge, normalize_transition


QUALITY_GATE_VERSION = "composition-quality-v8-completeness-pre-render"
PASS_SCORE = 50.0
RECOMMEND_SCORE = 75.0


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


def _compact_issue_text(item: dict[str, Any]) -> str:
    evidence = item.get("evidence")
    if isinstance(evidence, dict):
        evidence_text = " ".join(str(value) for value in evidence.values())
    elif isinstance(evidence, list):
        evidence_text = " ".join(str(value) for value in evidence)
    else:
        evidence_text = str(evidence or "")
    related = " ".join(str(value) for value in item.get("relatedDescriptions") or [])
    return "".join(f"{item.get('description') or ''} {evidence_text} {related}".lower().split())


def _issue_root(item: dict[str, Any]) -> str:
    """Map differently worded model/validator findings to one repairable cause."""
    category = str(item.get("category") or "editorial").lower()
    text = _compact_issue_text(item)
    if category.startswith("duration_") or (
        category in {"duration", "ending", "goal", "goal_match"}
        and any(token in text for token in ("目标时长", "实际时长", "成片总时长", "低于目标", "超过目标"))
    ):
        return "duration"
    if category == "cross_event_audio_bridge" or any(
        token in text for token in ("l-cut", "lcut", "j-cut", "jcut", "声音桥", "audio_bridge")
    ):
        return "cross_event_audio_bridge"
    if category == "cross_event_dissolve" or (
        "跨事件" in text and any(token in text for token in ("溶解", "叠化", "dissolve"))
    ):
        return "cross_event_dissolve"
    if category in {"audio_cut", "audiovisual", "audio"} and any(
        token in text for token in ("音量", "波形", "突变", "rms", "samplejump", "爆音", "音频切点")
    ):
        return "audio_cut"
    action_subject = any(token in text for token in ("动作", "操作", "表演", "魔术", "高潮"))
    action_failure = any(token in text for token in (
        "截断", "未完成", "不完整", "中途", "缺少", "未形成", "未呈现", "结果", "落点", "边界",
    ))
    if (
        any(token in text for token in ("动作未完整", "动作不完整", "动作中途", "操作中途", "完整动作", "结果状态"))
        or action_subject and action_failure
    ):
        return "action_boundary"
    if category in {"ending", "content", "narrative"} and any(token in text for token in (
        "结尾", "收束", "收尾", "自然结束", "对白未说完", "语句未表达完整", "停在", "中间结束",
    )):
        return "ending_boundary"
    if any(token in text for token in ("黑场重叠", "重叠黑场", "fade_black重叠", "转场重叠")):
        return "transition_overlap"
    if category in {"continuity", "visual_continuity", "audiovisual"} and any(
        token in text for token in ("服装", "景别", "视觉跳", "画面跳", "场景跳", "视觉不连续")
    ):
        return "visual_discontinuity"
    return category


def _issue_output_anchor(item: dict[str, Any]) -> int | None:
    value = item.get("outputTime")
    if value is None and isinstance(item.get("evidence"), dict):
        value = item["evidence"].get("outputTime")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number * 2) if math.isfinite(number) else None


def _issue_key(item: dict[str, Any]) -> tuple[Any, ...]:
    category = str(item.get("category") or "editorial").lower()
    root = _issue_root(item)
    segment_ids = tuple(sorted(str(value) for value in item.get("segmentIds") or [] if str(value)))
    description = "".join(str(item.get("description") or "").lower().split())
    anchor = _issue_output_anchor(item)
    if root == "duration":
        return (root,)
    if root in {
        "cross_event_audio_bridge", "cross_event_dissolve", "audio_cut",
        "transition_overlap", "visual_discontinuity",
    } and anchor is not None:
        # Rendered-media checks and model reviews often list a different pair
        # of segment ids for the same cut. The output-time bucket is stable.
        return (root, anchor)
    if root == "action_boundary" and segment_ids:
        return (root, segment_ids)
    return (root or category, segment_ids, "" if segment_ids else description[:36])


def _issues_share_root_cause(left: dict[str, Any], right: dict[str, Any]) -> bool:
    root = _issue_root(left)
    right_root = _issue_root(right)
    left_ids = {str(value) for value in left.get("segmentIds") or [] if str(value)}
    right_ids = {str(value) for value in right.get("segmentIds") or [] if str(value)}
    # Intent validation describes an omitted prerequisite as "missing context",
    # while dynamic review often describes the visible symptom as an incomplete
    # climax/action.  When both point at the same protected shot they are one
    # repair, not two independent deductions.
    if {root, right_root} == {"missing_context", "action_boundary"}:
        return bool(left_ids and right_ids and left_ids.intersection(right_ids))
    if root != right_root:
        return False
    if root in {"action_boundary", "ending_boundary"}:
        return bool(left_ids and right_ids and left_ids.intersection(right_ids))
    left_anchor = _issue_output_anchor(left)
    right_anchor = _issue_output_anchor(right)
    if root in {
        "cross_event_audio_bridge", "cross_event_dissolve", "audio_cut",
        "transition_overlap", "visual_discontinuity",
    }:
        return left_anchor is not None and right_anchor is not None and abs(left_anchor - right_anchor) <= 1
    return _issue_key(left) == _issue_key(right)


def deduplicate_issues(*collections: Any) -> list[dict[str, Any]]:
    severity_rank = {"minor": 1, "major": 2, "critical": 3}
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    order: list[tuple[Any, ...]] = []
    for collection in collections:
        for raw in collection if isinstance(collection, list) else []:
            if not isinstance(raw, dict):
                continue
            item = copy.deepcopy(raw)
            if not item.get("segmentIds") and isinstance(item.get("evidence"), list):
                evidence_ids = [
                    str(value.get("segmentId") or "")
                    for value in item["evidence"] if isinstance(value, dict)
                ]
                evidence_ids = list(dict.fromkeys(value for value in evidence_ids if value))
                if evidence_ids:
                    item["segmentIds"] = evidence_ids[:8]
            severity = str(item.get("severity") or "minor").lower()
            item["severity"] = severity if severity in severity_rank else "minor"
            key = _issue_key(item)
            previous = merged.get(key)
            if previous is None:
                matching_key = next((
                    existing_key for existing_key in order
                    if _issues_share_root_cause(merged[existing_key], item)
                ), None)
                if matching_key is not None:
                    key = matching_key
                    previous = merged[key]
            if previous is None:
                item["duplicateCount"] = max(1, int(item.get("duplicateCount") or 1))
                merged[key] = item
                order.append(key)
            else:
                descriptions = list(previous.get("relatedDescriptions") or [])
                for description in (previous.get("description"), item.get("description")):
                    description = str(description or "").strip()
                    if description and description not in descriptions:
                        descriptions.append(description)
                previous["duplicateCount"] = int(previous.get("duplicateCount") or 1) + int(item.get("duplicateCount") or 1)
                previous["relatedDescriptions"] = descriptions[:6]
                if severity_rank[item["severity"]] > severity_rank[str(previous.get("severity") or "minor")]:
                    previous["severity"] = item["severity"]
                # Keep the most concrete explanation while severity is merged
                # independently. Generic "unverified" notices should not hide
                # the actual incomplete action the user can repair.
                if len(str(item.get("description") or "")) > len(str(previous.get("description") or "")):
                    previous["description"] = item.get("description")
                    if item.get("evidence") is not None:
                        previous["evidence"] = copy.deepcopy(item.get("evidence"))
                if previous.get("outputTime") in (None, 0, 0.0) and item.get("outputTime") not in (None, 0, 0.0):
                    previous["outputTime"] = item.get("outputTime")
                combined_ids = list(dict.fromkeys([
                    *(str(value) for value in previous.get("segmentIds") or [] if str(value)),
                    *(str(value) for value in item.get("segmentIds") or [] if str(value)),
                ]))
                if combined_ids:
                    previous["segmentIds"] = combined_ids[:8]
                previous["fixable"] = bool(previous.get("fixable") or item.get("fixable"))
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
    issues = copy.deepcopy(list(intent_report.get("issues") or []))
    segment_by_id = {
        _identity(item, index): item
        for index, item in enumerate(sequence)
    }
    for issue in issues:
        if str(issue.get("category") or "") != "missing_context":
            continue
        evidence = issue.get("evidence") if isinstance(issue.get("evidence"), list) else []
        protected_ids = list(dict.fromkeys(
            str(value.get("segmentId") or "")
            for value in evidence if isinstance(value, dict)
            if str(value.get("segmentId") or "") in segment_by_id
            and _protected_role(segment_by_id[str(value.get("segmentId") or "")])
        ))
        if protected_ids:
            issue.update({
                "category": "action_boundary",
                "severity": "critical",
                "description": "高潮、结果或关键动作镜头缺少必需上下文，不能进入渲染",
                "segmentIds": protected_ids,
            })
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
        if duration_ratio > 1.25 + .001:
            duration_passed = False
            issues.append(_issue(
                "duration_overflow", "critical",
                f"成片 {duration:.1f} 秒，超过目标时长最高展示上限 25%",
            ))
        elif duration_ratio > 1.10 + .001:
            issues.append(_issue(
                "duration_overflow", "major",
                f"成片 {duration:.1f} 秒，超过目标时长 10%；可展示但不进入推荐",
            ))
        elif duration_ratio < .70 - .001:
            duration_passed = False
            severity = "major" if insufficient_evidence else "critical"
            issues.append(_issue(
                "duration_shortfall", severity,
                f"成片 {duration:.1f} 秒，低于目标时长 30% 以上"
                + ("；已确认素材不足，允许保留完整表达但不能作为推荐版本" if insufficient_evidence else ""),
            ))
        elif duration_ratio < .90 - .001:
            issues.append(_issue(
                "duration_shortfall", "major",
                f"成片 {duration:.1f} 秒，低于目标时长 10%；可展示但不进入推荐",
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
        "durationPreferred": duration_ratio is None or (.90 - .001 <= duration_ratio <= 1.10 + .001),
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
    # V4 calibrated reports already expose a canonical issue list containing
    # deterministic checks. Adding that raw list again would inflate the
    # displayed duplicate count even though scoring is unaffected.
    deterministic = [] if "root-cause" in str(review.get("calibrationVersion") or "") else review.get("deterministicChecks") or []
    issues = deduplicate_issues(validation.get("issues") or [], review.get("issues") or [], deterministic)
    critical = [item for item in issues if item.get("severity") == "critical"]
    passed = bool(validation.get("passed")) and not critical and score >= PASS_SCORE
    recommended = passed and score >= RECOMMEND_SCORE and validation.get("durationPreferred", True) is not False
    reasons: list[str] = []
    if not validation.get("passed"):
        reasons.append("剪辑序列未通过边界、章节或用户硬约束校验")
    if critical:
        reasons.append(f"仍有 {len(critical)} 个关键问题")
    if score < PASS_SCORE:
        reasons.append(f"校准审片得分 {score:.1f}，低于展示门槛 {PASS_SCORE:.0f}")
    elif score < RECOMMEND_SCORE:
        reasons.append(f"已达到可展示门槛，但未达到推荐门槛 {RECOMMEND_SCORE:.0f}")
    elif validation.get("durationPreferred", True) is False:
        reasons.append("已达到可展示门槛，但时长未进入目标的推荐区间")
    return {
        "schemaVersion": 1,
        "qualityGateVersion": QUALITY_GATE_VERSION,
        "passed": passed,
        "recommended": recommended,
        "score": round(score, 1),
        "passThreshold": PASS_SCORE,
        "recommendThreshold": RECOMMEND_SCORE,
        "durationPreferred": validation.get("durationPreferred"),
        "criticalCount": len(critical),
        "majorCount": sum(item.get("severity") == "major" for item in issues),
        "reasons": reasons,
        "issues": issues[:20],
    }
