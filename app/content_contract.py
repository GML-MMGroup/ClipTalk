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

VERSION = "content-contract-v1"
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


def verification_current(match: dict, contract: dict) -> bool:
    if contract.get("strategy") == "selection_union":
        contract = match.get("sourceContentContract") or {}
    verification = match.get("boundaryVerification") or {}
    return (verification.get("version") == VERSION
            and verification.get("contractFingerprint") == contract.get("fingerprint")
            and verification.get("status") in {"verified", "human_confirmed"}
            and verification.get("verifiedRange") == [match.get("start"), match.get("end")])


def confirm_human_range(match: dict, contract: dict) -> None:
    """Only called from an explicit per-candidate user review action."""
    match["boundaryVerification"] = {
        "version": VERSION, "status": "human_confirmed", "method": "human_review",
        "contractFingerprint": contract["fingerprint"], "strategy": contract["strategy"],
        "verifiedRange": [match.get("start"), match.get("end")], "exhaustive": False,
    }
    match["allowedRanges"] = [{"start": match["start"], "end": match["end"]}]


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
                for row in response.get("intervals") or []:
                    a, b = finite(row.get("start")), finite(row.get("end"))
                    allowed = response.get("allowedBoundaryTimes") or times
                    if (a in allowed and b in allowed and a is not None and b is not None
                            and left <= a < b <= right and row.get("wholeIntervalSupported") is True
                            and row_verdict(row, contract) is True):
                        ranges.append((a, b))
            # Never expand a user-selected candidate without explicit review.
            ranges = sorted(set((round(math.ceil(max(a, start) * fps) / fps, 3),
                                 round(math.floor(min(b, end) * fps) / fps, 3)) for a, b in ranges))
            ranges = [(a, b) for a, b in ranges if b - a >= .25]
            if not ranges:
                output.append(pending_match(original, contract, "no_supported_interval"))
                continue
            for index, (a, b) in enumerate(ranges):
                result = copy.deepcopy(original)
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
                        "clipId": clip.get("id"), "message": "完整表达或事件的范围已改变，需要重新核验语义完整性"})
                continue
            code, message = "content_range_exceeded", "时间线超出了已核验的可剪范围，请审核新增内容"
        issues.append({"severity": "warning", "code": code, "clipId": clip.get("id"), "message": message})
    if session.get("cutaways") and any(c.get("id") not in (session.get("disabledCutawayIds") or []) for c in session["cutaways"]):
        issues.append({"severity": "warning", "code": "content_cutaway_unverified", "message": "补画面尚未核验是否符合原检索条件"})
    expected = [str(m.get("id")) for m in binding.get("matches") or []]
    actual = list(dict.fromkeys(str((c.get("sourceRef") or {}).get("id")) for c in session.get("clips") or []))
    if expected and actual != expected:
        issues.append({"severity": "warning", "code": "content_selection_changed",
                       "message": "片段选择或顺序与确认的检索结果不同，请审核这次改动"})
    return {"version": VERSION, "status": "needs_review" if issues else "passed", "passed": not issues,
            "method": "source_range_contract_check", "exhaustive": False, "issues": issues,
            "contractFingerprint": contract.get("fingerprint")}
