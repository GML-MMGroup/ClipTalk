"""Evidence-backed editing contracts, independent of retrieval/model providers.

Retrieval confidence is deliberately never used as boundary confidence. Unknown
evidence stays unknown, including for negation. Verification is sampled, not a
claim of exhaustive frame-by-frame recognition.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any, Callable

VERSION = "content-contract-v2-complete-evidence-20260922"
VISIBLE_KINDS = {"visual.object", "visual.text", "visual.scene", "person.visible", "person.appearance", "screen.text", "screen_text.text"}


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:24]


def build_contract(search: dict) -> dict:
    intent = search.get("intent") or {}
    plan = search.get("queryPlan") or intent.get("queryPlan") or {}
    predicates = copy.deepcopy(plan.get("predicates") or intent.get("predicates") or [])
    kinds = {str(p.get("kind") or "") for p in predicates}
    relations = copy.deepcopy(plan.get("relations") or intent.get("relations") or [])
    if kinds and kinds <= VISIBLE_KINDS and not relations:
        strategy = "visible_intervals"
    elif any("action" in k or "event" in k for k in kinds):
        strategy = "complete_event"
    elif kinds and all(k.startswith(("speech.", "dialogue.")) or k == "person.speaking" for k in kinds):
        strategy = "speech_expression"
    else:
        strategy = "semantic_context"
    if search.get("recordType") == "assembly" and search.get("basketSnapshot"):
        strategy = "selection_union"
    contract = {
        "version": VERSION,
        "query": str(search.get("instruction") or intent.get("query") or ""),
        "predicates": predicates, "logic": copy.deepcopy(plan.get("logic") or intent.get("logic") or {}),
        "relations": relations, "excludeRules": copy.deepcopy(intent.get("excludeRules") or []),
        "includeRules": copy.deepcopy(intent.get("includeRules") or []),
        "scope": copy.deepcopy(intent.get("searchScope") or plan.get("scope") or {}),
        "boundaryMode": str(intent.get("boundaryMode") or "complete"),
        "personTarget": copy.deepcopy(intent.get("personTarget") or {}),
        "speakerRefs": copy.deepcopy(intent.get("speakerRefs") or []),
        "strategy": strategy,
    }
    contract["fingerprint"] = fingerprint(contract)
    return contract


def evaluate_logic(logic: dict, values: dict[str, bool | None]) -> bool | None:
    op = logic.get("op")
    if op == "predicate":
        return values.get(str(logic.get("predicateId") or ""))
    if op == "not":
        value = evaluate_logic(logic.get("child") or {}, values)
        return None if value is None else not value
    children = [evaluate_logic(c, values) for c in logic.get("children") or []]
    if not children:
        return None
    if op in {"and", "all"}:
        return False if False in children else None if None in children else True
    if op in {"or", "any"}:
        return True if True in children else None if None in children else False
    return None


def row_verdict(row: dict, contract: dict) -> bool | None:
    # Explicit booleans only; strings, missing fields and model guesses fail closed.
    values = {str(k): v if type(v) is bool else None for k, v in (row.get("predicates") or {}).items()}
    logic = contract.get("logic") or {}
    if not logic:
        logic = {"op": "and", "children": [
            {"op": "predicate", "predicateId": p["id"]} for p in contract.get("predicates") or []
            if p.get("id") and p.get("required", True)
        ]}
    verdict = evaluate_logic(logic, values)
    if not contract.get("predicates"):
        verdict = row.get("querySatisfied") if type(row.get("querySatisfied")) is bool else None
    if contract.get("excludeRules") and row.get("exclusionsClear") is not True:
        return None
    if contract.get("relations") and row.get("relationsSatisfied") is not True:
        return None
    return verdict


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def speech_verification_evidence(transcript: list[dict], left: float, right: float) -> dict:
    """Keep dialogue context separate from admissible clip boundaries.

    Compact full utterances instead of slicing serialized word-level JSON,
    which can lose the question or even end in an incomplete JSON object.
    """
    local, context = [], []
    for segment in transcript:
        if not isinstance(segment, dict):
            continue
        start, end = finite(segment.get("start")), finite(segment.get("end"))
        if start is None or end is None or end <= start:
            continue
        row = {key: segment[key] for key in ("start", "end", "text", "speaker") if key in segment}
        if end >= left and start <= right:
            local.append(row)
        elif end >= left - 30 and start <= right + 30:
            context.append(row)
    # Bound model input without silently dropping local evidence.
    if len(local) > 200 or sum(len(str(row.get("text") or "")) for row in local) > 16000:
        raise ValueError("speech_verification_evidence_budget_exceeded")
    context.sort(key=lambda row: min(abs(row["end"] - left), abs(row["start"] - right)))
    nearby, remaining = [], 6000
    for row in context[:60]:
        size = len(str(row.get("text") or ""))
        if size <= remaining:
            nearby.append(row)
            remaining -= size
    return {"local": local, "contextOnly": sorted(nearby, key=lambda row: row["start"])}


def verification_current(match: dict, contract: dict) -> bool:
    if contract.get("strategy") == "selection_union":
        contract = match.get("sourceContentContract") or {}
    verification = match.get("boundaryVerification") or {}
    return (verification.get("version") == VERSION
            and verification.get("contractFingerprint") == contract.get("fingerprint")
            and (verification.get("status") == "verified" or (
                verification.get("status") == "human_confirmed"
                and verification.get("manualOverride") is True))
            and verification.get("verifiedRange") == [match.get("start"), match.get("end")])


def confirm_human_range(match: dict, contract: dict) -> None:
    """Explicit manual boundary override, not merely checking a selection box."""
    match["boundaryVerification"] = {
        "version": VERSION, "status": "human_confirmed", "method": "human_review", "manualOverride": True,
        "contractFingerprint": contract["fingerprint"], "strategy": contract["strategy"],
        "verifiedRange": [match.get("start"), match.get("end")], "exhaustive": False,
    }
    match["allowedRanges"] = [{"start": match["start"], "end": match["end"]}]


def candidate_selection(match: dict) -> None:
    """Record intent to use a clip without erasing independent quality evidence."""
    match.update({"selected": True, "reviewStatus": "kept"})
    check = match.get("boundaryVerification") or {}
    verified = check.get("version") == VERSION and (
        check.get("status") == "verified"
        or (check.get("status") == "human_confirmed" and check.get("manualOverride") is True))
    match["requiresReview"] = not verified
    decision = match.setdefault("decision", {})
    decision["reviewRequired"] = not verified
    if not verified:
        decision["reviewReasons"] = list(dict.fromkeys([
            *(decision.get("reviewReasons") or []), "内容完整性或边界仍待核验",
        ]))


def pending_match(match: dict, contract: dict, reason: str) -> dict:
    result = copy.deepcopy(match)
    result.setdefault("candidateRange", {"start": match.get("start"), "end": match.get("end")})
    result.update({"allowedRanges": [], "boundaryConfidence": 0,
                   "requiresReview": True, "selected": False, "reviewStatus": "pending"})
    result["boundaryVerification"] = {
        "version": VERSION, "status": "pending", "reason": reason,
        "contractFingerprint": contract["fingerprint"], "strategy": contract["strategy"],
    }
    result["reviewReasons"] = list(dict.fromkeys([*(result.get("reviewReasons") or []), "边界待核验：" + reason]))
    return result


def semantic_anchor_window(match: dict, contract: dict, duration: float) -> dict:
    """A retrieved still is a search anchor, not a certified two-second edit.

    Explore a bounded local window only on fresh machine candidates. Explicit
    human choices and previously checked ranges are never silently expanded.
    """
    result = copy.deepcopy(match)
    anchors = [finite(t) for t in match.get("evidenceTimes") or []]
    if (contract.get("strategy") not in {"semantic_context", "complete_event"}
            or contract.get("boundaryMode") != "complete"
            or len(anchors) != 1 or anchors[0] is None
            or match.get("matchType") != "visual_dense_fallback"
            or match.get("manualBoundary") or match.get("boundaryVerification")
            or match.get("reviewStatus") in {"kept", "confirmed", "rejected"}):
        return result
    start, end = finite(match.get("start")), finite(match.get("end"))
    if start is None or end is None or not 0 < end - start <= 2.1:
        return result
    scope = contract.get("scope") or {}
    lower = finite(scope.get("start")) or (finite(scope.get("startUs")) or 0) / 1e6
    upper = finite(scope.get("end")) or (finite(scope.get("endUs")) or 0) / 1e6 or duration
    left, right = max(lower, anchors[0] - 8), min(duration, upper, anchors[0] + 8)
    if left <= start < end <= right:
        result.update({"start": left, "end": right, "duration": right - left,
                       "retrievalAnchorRange": {"start": start, "end": end},
                       "boundarySource": "semantic_anchor_context"})
    return result


def refine_matches(matches: list[dict], contract: dict, inspect: Callable,
                   *, duration: float, fps: float = 25, max_frames: int = 480) -> list[dict]:
    """Inspect returns timestamped predicate verdicts or semantic interval verdicts.

    Visible intervals use positive runs only: a missing/negative sample always
    breaks a run. Event/speech/semantic intervals require whole-interval support
    from the modality-aware adapter instead of trimming to isolated keyframes.
    """
    output = []
    remaining = max_frames
    fps = fps if math.isfinite(fps) and fps > 0 else 25
    for original in matches:
        original = semantic_anchor_window(original, contract, duration)
        if verification_current(original, contract):
            output.append(copy.deepcopy(original))
            continue
        start, end = finite(original.get("start")), finite(original.get("end"))
        if start is None or end is None or end <= start:
            output.append(pending_match(original, contract, "invalid_range"))
            continue
        scope = contract.get("scope") or {}
        lower = finite(scope.get("start")) or (finite(scope.get("startUs")) or 0) / 1e6
        upper = finite(scope.get("end")) or (finite(scope.get("endUs")) or 0) / 1e6 or duration
        left, right = max(lower, start - 2), min(max(0, duration - 1/fps), upper, end + 2)
        visible = contract["strategy"] == "visible_intervals"
        step = .25 if visible else max(.5, (right - left) / 47)
        times = sorted(set([round(left + i * step, 3) for i in range(max(0, math.ceil((right - left) / step)))] + [round(right, 3)]))
        if len(times) > remaining or right <= left:
            output.append(pending_match(original, contract, "verification_budget_exhausted"))
            continue
        remaining -= len(times)
        try:
            response = inspect(contract, original, times, "points" if visible else "intervals")
            if not isinstance(response, dict):
                raise ValueError("invalid_verifier_response")
            ranges: list[tuple[float, float]] = []
            if visible:
                def observations(raw: dict, allowed: list[float]) -> dict:
                    found = {}
                    for row in raw.get("observations") or []:
                        t = finite(row.get("time"))
                        if t is not None and t in allowed:
                            # Conflicting duplicate model rows are unknown.
                            value = row_verdict(row, contract)
                            found[t] = value if t not in found else None
                    return found
                verdicts = observations(response, times)
                edges = []
                for a, b in zip(times, times[1:]):
                    if verdicts.get(a) != verdicts.get(b) and True in (verdicts.get(a), verdicts.get(b)):
                        edges.extend([round(a + (b - a) / 3, 3), round(a + 2 * (b - a) / 3, 3)])
                edges = sorted(set(edges) - set(times))
                if edges:
                    if len(edges) > remaining:
                        raise ValueError("verification_budget_exhausted")
                    remaining -= len(edges)
                    verdicts.update(observations(inspect(contract, original, edges, "points"), edges))
                    times = sorted(set(times + edges))
                run = []
                for t in times:
                    if verdicts.get(t) is True:
                        run.append(t)
                    else:
                        if len(run) >= 2:
                            ranges.append((run[0], run[-1]))
                        run = []
                if len(run) >= 2:
                    ranges.append((run[0], run[-1]))
            else:
                rejection_counts = {}
                for row in response.get("intervals") or []:
                    a, b = finite(row.get("start")), finite(row.get("end"))
                    allowed = response.get("allowedBoundaryTimes") or times
                    if (a in allowed and b in allowed and a is not None and b is not None
                            and left <= a < b <= right and row.get("wholeIntervalSupported") is True
                            and row_verdict(row, contract) is True):
                        ranges.append((a, b))
                    else:
                        reason = ("unsupported_predicates" if row_verdict(row, contract) is not True
                                  else "whole_interval_unproven" if row.get("wholeIntervalSupported") is not True
                                  else "invalid_boundary")
                        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            # A short semantic range must still contain the evidence used to
            # describe the complete event. Otherwise a setup can replace its
            # payoff while retaining the old retrieval explanation.
            lost_support = False
            if not visible and contract.get("boundaryMode") == "complete":
                anchors = [finite(t) for t in original.get("evidenceTimes") or []]
                anchors = [t for t in anchors if t is not None and start <= t <= end]
                if len(anchors) >= 2:
                    kept = [(a, b) for a, b in ranges
                            if a <= min(anchors) + 1 / fps and b >= max(anchors) - 1 / fps]
                    lost_support = bool(ranges) and not kept
                    ranges = kept
                    if lost_support and remaining >= len(times):
                        # One bounded repair in the same source window, never
                        # expand the user's selection or loop indefinitely.
                        remaining -= len(times)
                        retry_contract = {**contract, "boundaryRepair": {
                            "reason": "supporting_evidence_trimmed",
                            "requiredEvidenceTimes": anchors,
                            "instruction": "上一范围裁掉了完整事件的证据。请重新确定包含这些证据和事件结果的完整范围；无法确认就返回空列表。",
                        }}
                        retry = inspect(retry_contract, original, times, "intervals")
                        if isinstance(retry, dict):
                            response = retry
                            allowed = retry.get("allowedBoundaryTimes") or times
                            for row in retry.get("intervals") or []:
                                a, b = finite(row.get("start")), finite(row.get("end"))
                                if (a is not None and b is not None and a in allowed and b in allowed
                                        and left <= a < b <= right
                                        and a <= min(anchors) + 1 / fps and b >= max(anchors) - 1 / fps
                                        and row.get("wholeIntervalSupported") is True
                                        and row_verdict(row, contract) is True):
                                    ranges.append((a, b))
                            lost_support = not bool(ranges)
            # Never expand a user-selected candidate without explicit review.
            ranges = sorted(set((round(math.ceil(max(a, start) * fps) / fps, 3),
                                 round(math.floor(min(b, end) * fps) / fps, 3)) for a, b in ranges))
            ranges = [(a, b) for a, b in ranges if b - a >= .25]
            supported_partial = bool(ranges)
            if original.get("expressionRange") and contract.get("boundaryMode") == "complete":
                # A relevant short sentence is not proof of a complete answer.
                ranges = [(a, b) for a, b in ranges
                          if abs(a - start) <= 1 / fps + .001 and abs(b - end) <= 1 / fps + .001]
            if not ranges:
                pending = pending_match(original, contract,
                    "supporting_evidence_trimmed" if lost_support else
                    "incomplete_expression" if original.get("expressionRange") and supported_partial else "no_supported_interval")
                if not visible:
                    pending["boundaryVerification"]["diagnostics"] = {
                        "returnedIntervalCount": len(response.get("intervals") or []),
                        "rejectedIntervals": rejection_counts,
                        "requiresFullExpression": bool(original.get("expressionRange")),
                    }
                output.append(pending)
                continue
            for index, (a, b) in enumerate(ranges):
                result = copy.deepcopy(original)
                if not visible:
                    proof = next((row for row in response.get("intervals") or []
                                  if finite(row.get("start")) is not None and finite(row.get("end")) is not None
                                  and abs(float(row["start"]) - a) <= 1 / fps + .001
                                  and abs(float(row["end"]) - b) <= 1 / fps + .001
                                  and row.get("wholeIntervalSupported") is True
                                  and row_verdict(row, contract) is True), {})
                    valid_ids = {p.get("id") for p in contract.get("predicates") or []}
                    result["verifiedPredicateIds"] = [key for key, value in (proof.get("predicates") or {}).items()
                                                      if key in valid_ids and value is True]
                    result["boundaryEvidence"] = {"start": a, "end": b,
                        "predicates": copy.deepcopy(proof.get("predicates") or {}),
                        "reason": str(proof.get("reason") or "")[:600]}
                if original.get("expressionRange"):
                    result["expressionCompleteness"] = "verified"
                result.update({"start": a, "end": b, "duration": round(b-a, 3),
                               "startUs": round(a*1e6), "endUs": round(b*1e6),
                               "sourceRange": {"startUs": round(a*1e6), "endUs": round(b*1e6)},
                               "candidateRange": {"start": start, "end": end},
                               "evidenceRanges": [{"start": a, "end": b}],
                               "allowedRanges": [{"start": a, "end": b}],
                               "boundaryConfidence": .9, "boundarySource": "contract_verified",
                               "sourceMatchId": original.get("id"),
                               "requiresReview": False, "selected": original.get("selected", True),
                               "reviewStatus": "confirmed"})
                if len(ranges) > 1:
                    result["id"] = f"{original['id']}_part_{index+1}"
                result["boundaryVerification"] = {
                    "version": VERSION, "status": "verified", "contractFingerprint": contract["fingerprint"],
                    "strategy": contract["strategy"], "verifiedRange": [a, b],
                    "sampleCount": len(times), "samplingIntervalSeconds": step,
                    "method": "sampled_predicate_verification" if visible else "whole_interval_verification",
                    "exhaustive": False,
                }
                output.append(result)
        except Exception as error:
            # Preserve candidates for review; no fallback to the original range.
            safe_reasons = {"verification_budget_exhausted", "invalid_verifier_response",
                            "目标声音或人物身份需要专用证据核验，请人工审核", "缺少可定位的语音证据",
                            "核验画面抽取不完整"}
            reason = str(error) if str(error) in safe_reasons else "verification_unavailable"
            output.append(pending_match(original, contract, reason))
    return output


def selection_binding(search: dict, matches: list[dict]) -> dict:
    return {
        "searchId": search.get("id"), "contract": build_contract(search),
        "selectionFingerprint": fingerprint(matches),
        "matches": copy.deepcopy(matches),
    }


def timeline_content_report(session: dict, job: dict | None = None) -> dict:
    binding = session.get("contentBinding") or {}
    if not binding and not session.get("sourceSearchId"):
        return {"status": "not_applicable", "passed": True, "issues": []}
    if binding.get("matches") and all(m.get("evidenceType") == "source_scope" for m in binding["matches"]):
        return {"status": "not_applicable", "passed": True, "issues": []}
    contract = binding.get("contract") or {}
    lookup = {str(m.get("id")): m for m in binding.get("matches") or []}
    issues = []
    for clip in session.get("clips") or []:
        source = clip.get("sourceRef") or {}
        match = lookup.get(str(source.get("id"))) or {}
        # Source-only transformations have no content filtering requirement.
        if match.get("evidenceType") == "source_scope":
            continue
        if not match or not verification_current(match, contract):
            code, message = "content_boundary_unverified", "片段内容或边界尚未核验，不能视为符合原要求"
        else:
            a, b = finite(clip.get("sourceStart")), finite(clip.get("sourceEnd"))
            contained = a is not None and b is not None and b > a and any(
                a >= r["start"] - .001 and b <= r["end"] + .001 for r in match.get("allowedRanges") or [])
            if contained:
                match_contract = match.get("sourceContentContract") if contract.get("strategy") == "selection_union" else contract
                match_contract = match_contract or {}
                if match_contract.get("strategy") != "visible_intervals" and match_contract.get("boundaryMode") != "exact" and (
                    abs(a - match["start"]) > .001 or abs(b - match["end"]) > .001
                ):
                    issues.append({"severity": "warning", "code": "content_semantic_boundary_changed",
                        "clipId": clip.get("id"), "message": "完整表达或事件的范围已改变，需要重新核验语义完整性。"})
                continue
            code, message = "content_range_exceeded", "时间线超出了已核验的可剪范围，请审核新增内容"
        issues.append({"severity": "warning", "code": code, "clipId": clip.get("id"), "message": message})
    if session.get("cutaways") and any(c.get("id") not in (session.get("disabledCutawayIds") or []) for c in session["cutaways"]):
        issues.append({"severity": "warning", "code": "content_cutaway_unverified", "message": "补画面尚未核验是否符合原检索条件。"})
    expected = [str(m.get("id")) for m in binding.get("matches") or []]
    actual = list(dict.fromkeys(str((c.get("sourceRef") or {}).get("id")) for c in session.get("clips") or []))
    if expected and actual != expected:
        issues.append({"severity": "warning", "code": "content_selection_changed",
                       "message": "片段选择或顺序与确认的检索结果不同，请审核这次改动。"})
    return {"version": VERSION, "status": "needs_review" if issues else "passed", "passed": not issues,
            "method": "source_range_contract_check", "exhaustive": False, "issues": issues,
            "contractFingerprint": contract.get("fingerprint")}
