import copy
import pytest

from app.content_requirements import requirement_errors
from app.content_contract import build_contract, candidate_selection, refine_matches, verification_current, semantic_anchor_window


def predicate(text, identity="p1"):
    return {"id": identity, "kind": "visual.semantic", "value": text, "sourceSpan": {"text": text}}


def test_missing_selling_point_is_not_a_successful_parse():
    assert requirement_errors("产品新老替换和核心卖点", [predicate("产品新老替换")])[0]["missingRequirements"] == ["核心卖点"]
    assert not requirement_errors("产品新老替换和核心卖点", [predicate("产品新老替换"), predicate("核心卖点", "p2")])


def test_repair_must_preserve_grounded_requirements():
    assert requirement_errors("旧产品，新产品，卖点", [predicate("旧产品")], [predicate("新产品")])
    assert not requirement_errors("红色汽车", [predicate("红色汽车")], [predicate("模型臆造的要求")])


def test_selecting_candidate_does_not_certify_its_boundary():
    contract = build_contract({"instruction": "目标", "intent": {"predicates": [predicate("目标")]}})
    match = {"start": 1, "end": 3, "boundaryVerification": {"status": "pending", "reason": "no_supported_interval"}, "requiresReview": True}
    old = copy.deepcopy(match["boundaryVerification"])
    candidate_selection(match)
    assert match["boundaryVerification"] == old
    assert match["requiresReview"] is True
    assert not verification_current(match, contract)


def test_complete_semantic_cut_cannot_drop_its_supporting_frames():
    contract = build_contract({"instruction": "新老替换", "intent": {"predicates": [predicate("新老替换")]}})
    match = {"id": "fridge", "start": 93.913, "end": 125.217, "evidenceTimes": [101.739, 125.217]}
    def inspect(*args):
        return {"allowedBoundaryTimes": [95.4, 117.28], "intervals": [{"start": 95.4, "end": 117.28, "wholeIntervalSupported": True, "predicates": {"p1": True}}]}
    result = refine_matches([match], contract, inspect, duration=643)[0]
    assert result["boundaryVerification"]["status"] == "pending"
    assert result["boundaryVerification"]["reason"] == "supporting_evidence_trimmed"
    assert result["end"] == match["end"]


def test_boundary_repair_recovers_event_ending_with_one_retry():
    contract = build_contract({"instruction": "新老替换", "intent": {"predicates": [predicate("新老替换")]}})
    calls = []
    def inspect(spec, match, times, mode):
        calls.append(spec)
        end = 8 if spec.get("boundaryRepair") else 4
        return {"allowedBoundaryTimes": [2, end], "intervals": [{"start": 2, "end": end, "wholeIntervalSupported": True, "predicates": {"p1": True}}]}
    result = refine_matches([{"id": "m", "start": 2, "end": 8, "evidenceTimes": [3, 8]}], contract, inspect, duration=10)[0]
    assert result["end"] == 8
    assert verification_current(result, contract)
    assert len(calls) == 2
    assert result["verifiedPredicateIds"] == ["p1"]


def test_parser_runs_requirement_guard():
    from app.content_search import parse_content_intent
    result = parse_content_intent("产品新老替换和核心卖点", {"query": "产品新老替换和核心卖点", "predicates": [predicate("产品新老替换")], "logic": {"op": "predicate", "predicateId": "p1"}})
    assert any(e["code"] == "requirement_coverage_missing" for e in result["validationErrors"])


def test_single_frame_opens_bounded_search_window_not_two_second_edit():
    contract = build_contract({"instruction": "卖点", "intent": {"predicates": [predicate("卖点")], "searchScope": {"start": 490, "end": 505}}})
    match = {"start": 499, "end": 501, "evidenceTimes": [500], "matchType": "visual_dense_fallback"}
    result = semantic_anchor_window(match, contract, 643)
    assert (result["start"], result["end"]) == (492, 505)
    assert "allowedRanges" not in result
    assert "retrievalAnchorRange" not in match
    assert semantic_anchor_window({**match, "reviewStatus": "kept"}, contract, 643)["start"] == 499


@pytest.mark.parametrize("code,tool", [
    ("content_goal_mismatch", "search_content"),
    ("content_semantic_boundary_changed", "search_content"),
    ("content_render_sample_uncertain", "run_delivery_qc"),
    ("content_render_sample_unavailable", "run_delivery_qc"),
    ("delivery_aspect_mismatch", "render_social_preview"),
])
def test_quality_retry_targets_cause_not_always_editing(code, tool):
    from app.quality_repair import quality_repair_plan
    result = quality_repair_plan({"reports": [{"issues": [{"code": code}]}]}, [
        {"tool": t} for t in ["search_content", "propose_timeline_edit", "render_social_preview", "run_delivery_qc"]])
    assert result["replayFromTool"] == tool
    assert result["requiresConfirmation"]


@pytest.mark.parametrize("mode", ["exception", "degraded"])
def test_failed_editor_never_becomes_successful_simple_join(monkeypatch, mode):
    from app import main
    job = {"id": "job_algorithm_planner_failure", "revision": 1, "workflowKind": "highlight",
           "videoInfo": {"duration": 60}, "editSessions": [], "outputVersions": [],
           "candidates": [{"candidateId": "candidate_0", "index": 0, "start": 10, "end": 20, "title": "候选", "score": 90}]}
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda _: None)
    def planner(*args, **kwargs):
        if mode == "exception":
            raise ValueError("private provider detail")
        return {"proposal": {"id": "degraded", "plannerDegradedReason": "TimeoutError"}}
    monkeypatch.setattr(main, "create_edit_session_proposal", planner)
    with pytest.raises(RuntimeError, match="未.*(?:应用|替代)") as error:
        main.dispatch_agent_tool({"jobId": job["id"], "executionMode": "autonomous_review"}, "propose_timeline_edit", {"instruction": "突出卖点", "variantCount": 1})
    assert "private provider detail" not in str(error.value)
    assert not job.get("agentTimelineBatch")
    assert job["editSessions"][0]["revision"] == 0


def test_router_repair_cannot_drop_condition_and_report_success(monkeypatch):
    from app import main
    first = {"query": "产品新老替换和核心卖点", "predicates": [predicate("产品新老替换"), predicate("核心卖点", "p2")],
             "validationErrors": [{"code": "invalid_logic", "message": "关系错误"}]}
    second = {"query": first["query"], "predicates": [predicate("产品新老替换")], "executionPlan": {}, "validationErrors": []}
    calls = iter([first, second])
    monkeypatch.setattr(main, "_route_content_message", lambda *a, **k: {})
    monkeypatch.setattr(main, "_content_intent_from_decision", lambda *a, **k: copy.deepcopy(next(calls)))
    result = main._parse_content_instruction({"request": {}}, first["query"])
    assert result["executionPlan"]["intentRepair"]["succeeded"] is False
    assert result["_clarification"]["kind"] == "query_semantics"
    assert "核心卖点" in result["_clarification"]["message"]


def test_verified_multi_goal_clip_is_not_duplicated_in_assembly():
    from app import main
    result = main._content_assembly_spec({"intent": {"predicates": [predicate("换新"), predicate("卖点", "p2")]},
        "candidates": [{"id": "m", "start": 1, "end": 8, "duration": 7, "verifiedPredicateIds": ["p1", "p2"], "confidenceTier": "reliable"}]})
    assert result["missingPredicates"] == []
    assert result["selectedMatchIds"] == ["m"]
