import copy

import pytest

from app.content_contract import (
    build_contract, confirm_human_range, evaluate_logic, pending_match,
    refine_matches, row_verdict, selection_binding, timeline_content_report, verification_current,
)
from app.edit_sessions import create_or_resume_content_edit_session, edit_session_preflight


def search(kind="visual.object"):
    return {"id": "search_test", "instruction": "目标条件", "intent": {
        "predicates": [{"id": "p1", "kind": kind, "value": "目标条件"}],
        "logic": {"op": "predicate", "predicateId": "p1"},
    }}


def candidate(start=1, end=8):
    return {"id": "m1", "start": start, "end": end, "duration": end-start,
            "confidence": 1, "score": 100, "selected": True}


def test_speech_verification_keeps_question_as_context_not_clip_evidence():
    from app.content_contract import speech_verification_evidence
    transcript = [
        {"start": 10, "end": 15, "text": "初中最大的变化是什么？", "speaker": "Speaker 1"},
        {"start": 30, "end": 34, "text": "我的心态变好了。", "speaker": "Speaker 2", "words": [{"word": "我"}]},
        {"start": 100, "end": 105, "text": "无关内容"},
    ]
    result = speech_verification_evidence(transcript, 28, 36)
    assert [row["text"] for row in result["contextOnly"]] == ["初中最大的变化是什么？"]
    assert [row["text"] for row in result["local"]] == ["我的心态变好了。"]
    assert "words" not in result["local"][0]
    assert "words" in transcript[1]


def test_speech_verification_never_silently_truncates_local_evidence():
    from app.content_contract import speech_verification_evidence
    with pytest.raises(ValueError, match="budget"):
        speech_verification_evidence([{"start": 1, "end": 3, "text": "字" * 16001}], 0, 4)


def test_speech_context_cannot_expand_verified_clip():
    record = search("speech.semantic")
    def inspect(contract, match, times, mode):
        return {"allowedBoundaryTimes": [0, 2, 3, 9], "intervals": [
            {"start": 0, "end": 9, "wholeIntervalSupported": True, "predicates": {"p1": True}},
            {"start": 2, "end": 3, "wholeIntervalSupported": True, "predicates": {"p1": True}},
        ]}
    result = refine_matches([candidate(2, 3)], build_contract(record), inspect, duration=20)
    assert [(m["start"], m["end"]) for m in result] == [(2, 3)]


def test_relevant_sentence_does_not_certify_complete_answer():
    record = search("speech.semantic")
    match = {**candidate(2, 8), "expressionRange": [2, 8], "expressionCompleteness": "pending"}
    def inspect(contract, match, times, mode):
        return {"allowedBoundaryTimes": [2, 3], "intervals": [
            {"start": 2, "end": 3, "wholeIntervalSupported": True, "predicates": {"p1": True}}]}
    result = refine_matches([match], build_contract(record), inspect, duration=20)
    assert result[0]["boundaryVerification"]["reason"] == "incomplete_expression"
    assert result[0]["end"] == 8
    assert result[0]["boundaryVerification"]["diagnostics"]["returnedIntervalCount"] == 1
    assert result[0]["boundaryVerification"]["diagnostics"]["rejectedIntervals"] == {}


def test_unsupported_content_is_not_misreported_as_incomplete_expression():
    record = search("speech.semantic")
    item = {**candidate(2, 8), "expressionRange": [2, 8]}
    def inspect(*args):
        return {"allowedBoundaryTimes": [2, 8], "intervals": [
            {"start": 2, "end": 8, "wholeIntervalSupported": True, "predicates": {"p1": False}}]}
    result = refine_matches([item], build_contract(record), inspect, duration=20)[0]
    assert result["boundaryVerification"]["reason"] == "no_supported_interval"
    assert result["boundaryVerification"]["diagnostics"]["rejectedIntervals"] == {"unsupported_predicates": 1}


def test_transcript_cannot_approve_reference_voice_identity(monkeypatch, tmp_path):
    import threading
    from app import main
    monkeypatch.setattr(main, "create_llm_client_for_job", lambda job: pytest.fail("text cannot verify voice identity"))
    record = search("speech.voice_identity")
    result = main._verify_content_contract_matches(
        {"workDirectory": str(tmp_path), "videoInfo": {"duration": 20}}, record,
        [candidate()], threading.Event(), {})
    assert result[0]["boundaryVerification"]["status"] == "pending"
    assert result[0]["requiresReview"]


def test_voice_review_cannot_auto_adopt_high_similarity(monkeypatch):
    from app import main
    record = search("speech.voice_identity")
    record["candidates"] = [{**candidate(), "matchType": "voice_identity", "confidenceTier": "reliable"}]
    job = {"id": "voice_gate", "contentSearch": record}
    monkeypatch.setitem(main.jobs, job["id"], job)
    result = main.dispatch_agent_tool({"jobId": job["id"], "executionMode": "autonomous_review"},
                                     "review_content_evidence", {})
    assert result["action"] == "content_evidence_review"


def inspector(visible):
    def inspect(_contract, _match, times, mode):
        assert mode == "points"
        return {"observations": [{"time": t, "predicates": {"p1": visible(t)}} for t in times]}
    return inspect


@pytest.mark.parametrize("kind,strategy", [
    ("visual.object", "visible_intervals"), ("screen_text.text", "visible_intervals"),
    ("person.appearance", "visible_intervals"), ("visual.action", "complete_event"),
    ("audio.event", "complete_event"), ("speech.exact", "speech_expression"),
    ("speech.semantic", "speech_expression"), ("visual.semantic", "semantic_context"),
])
def test_modality_specific_strategy(kind, strategy):
    assert build_contract(search(kind))["strategy"] == strategy


@pytest.mark.parametrize("op,values,expected", [
    ("all", {"a": True, "b": False}, False), ("all", {"a": True}, None),
    ("any", {"a": False, "b": True}, True), ("any", {"a": False}, None),
    ("not", {}, None), ("not", {"a": False}, True),
])
def test_three_valued_logic(op, values, expected):
    logic = {"op": op, "children": [{"op": "predicate", "predicateId": x} for x in "ab"],
             "child": {"op": "predicate", "predicateId": "a"}}
    assert evaluate_logic(logic, values) is expected


def test_exclusions_and_temporal_relations_cannot_be_skipped():
    contract = build_contract(search())
    contract.update({"excludeRules": ["广告"], "relations": [{"type": "before"}]})
    assert row_verdict({"predicates": {"p1": True}}, contract) is None
    assert row_verdict({"predicates": {"p1": True}, "exclusionsClear": True}, contract) is None
    assert row_verdict({"predicates": {"p1": True}, "exclusionsClear": True, "relationsSatisfied": True}, contract) is True


def test_logo_regression_removes_unrelated_tail_and_preserves_original():
    original = candidate(273.392, 281.217)
    before = copy.deepcopy(original)
    contract = build_contract(search())
    result = refine_matches([original], contract, inspector(lambda t: 273 <= t <= 275.95), duration=643, fps=30)
    assert original == before
    assert len(result) == 1
    assert 275.8 < result[0]["end"] <= 275.95
    assert result[0]["candidateRange"]["end"] == 281.217
    assert verification_current(result[0], contract)
    assert result[0]["boundaryConfidence"] != result[0]["confidence"]
    assert result[0]["sourceRange"]["endUs"] == round(result[0]["end"]*1e6)


def test_disappearance_and_unknown_split_intervals():
    contract = build_contract(search())
    rows = refine_matches([candidate()], contract, inspector(lambda t: True if t < 3 or t > 5 else None), duration=10)
    assert len(rows) == 2
    assert rows[0]["end"] < 3 and rows[1]["start"] > 5
    assert len({r["id"] for r in rows}) == 2
    assert all(r["sourceMatchId"] == "m1" for r in rows)


@pytest.mark.parametrize("value", [False, None, "true"])
def test_no_supported_interval_is_reviewable_not_implicitly_selected(value):
    rows = refine_matches([candidate()], build_contract(search()), inspector(lambda _t: value), duration=10)
    assert rows[0]["start"] == 1 and rows[0]["end"] == 8
    assert rows[0]["selected"] is False
    assert rows[0]["allowedRanges"] == []
    assert rows[0]["boundaryConfidence"] == 0


def test_single_positive_frame_is_not_padded_to_two_seconds():
    rows = refine_matches([candidate()], build_contract(search()), inspector(lambda t: t == 4), duration=10)
    assert rows[0]["boundaryVerification"]["status"] == "pending"


def test_budget_exhaustion_makes_no_provider_call():
    def unavailable(*args):
        pytest.fail("provider must not run")
    rows = refine_matches([candidate(1, 200)], build_contract(search()), unavailable, duration=300, max_frames=1)
    assert rows[0]["boundaryVerification"]["reason"] == "verification_budget_exhausted"


def test_model_failure_preserves_review_candidate():
    def unavailable(*args):
        raise RuntimeError("provider unavailable")
    rows = refine_matches([candidate()], build_contract(search()), unavailable, duration=10)
    assert rows[0]["requiresReview"] and not rows[0]["selected"]


def test_missing_or_duplicate_timestamps_do_not_bridge_gaps():
    def inspect(spec, match, times, mode):
        rows = [{"time": t, "predicates": {"p1": True}} for t in times if t < 3 or t > 5]
        rows.extend([{"time": 4, "predicates": {"p1": True}}, {"time": 4, "predicates": {"p1": False}}])
        return {"observations": rows}
    result = refine_matches([candidate()], build_contract(search()), inspect, duration=10)
    assert all(r["end"] < 3 or r["start"] > 5 for r in result)


@pytest.mark.parametrize("kind", ["visual.action", "speech.exact", "speech.semantic", "visual.semantic"])
def test_semantic_and_event_ranges_require_whole_interval_support(kind):
    contract = build_contract(search(kind))
    def inspect(spec, match, times, mode):
        assert mode == "intervals"
        return {"intervals": [{"start": 2, "end": 6, "wholeIntervalSupported": True, "predicates": {"p1": True}}],
                "allowedBoundaryTimes": [2, 6]}
    result = refine_matches([candidate()], contract, inspect, duration=10)
    assert (result[0]["start"], result[0]["end"]) == (2, 6)


def test_stale_boundary_and_changed_query_invalidate_verification():
    contract = build_contract(search())
    match = candidate()
    confirm_human_range(match, contract)
    assert verification_current(match, contract)
    altered = copy.deepcopy(match)
    altered["end"] += 1
    assert not verification_current(altered, contract)
    changed = search()
    changed["instruction"] = "另一种目标"
    assert not verification_current(match, build_contract(changed))


def test_binding_is_immutable_and_ranges_cannot_expand_or_insert_unknown_source():
    record = search()
    contract = build_contract(record)
    match = candidate()
    confirm_human_range(match, contract)
    record["candidates"] = [match]
    job = {"id": "test", "videoInfo": {"duration": 20}, "contentSearch": record}
    session, _ = create_or_resume_content_edit_session(job, search_id=record["id"], selected_match_ids=["m1"])
    assert timeline_content_report(session)["passed"]
    record["candidates"][0]["end"] = 15
    assert session["contentBinding"]["matches"][0]["end"] == 8
    session["clips"][0]["sourceEnd"] = 9
    report = timeline_content_report(session)
    assert report["issues"][0]["code"] == "content_range_exceeded"
    session["clips"][0]["sourceRef"]["id"] = "unrelated"
    assert not timeline_content_report(session)["passed"]


def test_legacy_session_warns_but_allows_manual_editing():
    session = {"sourceSearchId": "old", "clips": [{"id": "c", "sourceStart": 2, "sourceEnd": 4}]}
    report = edit_session_preflight(session)
    assert report["ready"] is True
    assert any(i["code"] == "content_boundary_unverified" for i in report["issues"])


def test_no_content_search_does_not_change_highlight_workflow():
    assert timeline_content_report({"clips": [{"sourceStart": 2, "sourceEnd": 4}]})["status"] == "not_applicable"


def test_selection_revision_creates_new_session_and_preserves_manual_changes():
    record = search()
    record["candidates"] = [candidate()]
    job = {"id": "test", "videoInfo": {"duration": 20}, "contentSearch": record}
    first, _ = create_or_resume_content_edit_session(job, search_id=record["id"], selected_match_ids=["m1"])
    first["clips"][0]["title"] = "用户修改"
    record["candidates"][0]["end"] = 7
    second, created = create_or_resume_content_edit_session(job, search_id=record["id"], selected_match_ids=["m1"])
    assert created and first["id"] != second["id"]
    assert first["clips"][0]["title"] == "用户修改"


def test_source_only_reframe_has_no_content_requirement():
    record = {"id": "source", "candidates": [{**candidate(), "evidenceType": "source_scope"}]}
    session = {"sourceSearchId": "source", "contentBinding": selection_binding(record, record["candidates"]),
               "clips": [{"sourceRef": {"id": "m1"}, "sourceStart": 1, "sourceEnd": 8}]}
    assert timeline_content_report(session)["passed"]


def test_pending_state_survives_scoring():
    from app.content_query import attach_result_coordinates_and_scores
    item = pending_match(candidate(), build_contract(search()), "missing_evidence")
    item["confidenceTier"] = "reliable"
    assert attach_result_coordinates_and_scores([item])[0]["requiresReview"]


def test_legacy_composition_rechecks_selected_ranges_and_archives_without_overwrite(monkeypatch):
    from app import main
    record = search()
    record.update({"candidates": [candidate()], "reviewDraft": {"selectedMatchIds": ["m1"], "orderedMatchIds": ["m1"]}})
    original = copy.deepcopy(record)
    old_session = {"id": "user_draft", "clips": [{"title": "手动编辑"}]}
    job = {"id": "contract_legacy", "contentSearch": record, "videoInfo": {"duration": 10}, "editSessions": [old_session]}
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda j: None)
    def verify(job, revised, matches, event, stats):
        revised["contentContract"] = build_contract(revised)
        return refine_matches(matches, revised["contentContract"], inspector(lambda t: 1 <= t <= 3), duration=10)
    monkeypatch.setattr(main, "_verify_content_contract_matches", verify)
    result = main._prepare_content_composition_contract(job["id"])
    assert result["actionRequired"]
    assert job["contentSearch"]["id"] != original["id"]
    assert job["contentSearchHistory"][0] == original
    assert job["editSessions"] == [old_session]
    assert job["contentSearch"]["candidates"][0]["end"] <= 3
    revision_id = job["contentSearch"]["id"]
    monkeypatch.setattr(main, "_verify_content_contract_matches", lambda *args: pytest.fail("must reuse current verification"))
    assert main._prepare_content_composition_contract(job["id"]) is None
    assert job["contentSearch"]["id"] == revision_id


def test_pending_results_never_fall_back_to_highlights_or_full_video(monkeypatch):
    from app import main
    record = search()
    record["candidates"] = [pending_match(candidate(), build_contract(record), "missing_evidence")]
    job = {"id": "contract_no_fallback", "contentSearch": record, "videoInfo": {"duration": 60},
           "candidates": [{"id": "unrelated_highlight", "start": 10, "end": 50}], "editSessions": []}
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda j: None)
    result = main.dispatch_agent_tool({"jobId": job["id"], "executionMode": "autonomous_review"},
                                     "propose_timeline_edit", {"instruction": "把这些合成竖屏"})
    assert result["action"] == "content_evidence_review"
    assert job["editSessions"] == []


def test_direct_export_requires_separate_unverified_acknowledgement(monkeypatch):
    from app import main
    from fastapi import HTTPException
    record = search()
    record["candidates"] = [candidate()]
    job = {"id": "contract_confirm", "taskMode": "content_extract", "status": "awaiting_content_confirmation", "contentSearch": record}
    monkeypatch.setitem(main.jobs, job["id"], job)
    with pytest.raises(HTTPException) as raised:
        main.confirm_content_search(job["id"], main.ContentSearchConfirmRequest(
            searchId=record["id"], matchIds=["m1"], acknowledgeIncomplete=True))
    assert raised.value.status_code == 409
    assert "尚未核验" in raised.value.detail


def test_fresh_verifier_adapter_uses_predicate_results_and_budget(monkeypatch, tmp_path):
    import threading
    from types import SimpleNamespace
    from app import main
    frame_times = {}
    class Vision:
        def analyze_image(self, prompt, sheet, **kwargs):
            return {"observations": [{"time": t, "predicates": {"p1": t < 3}} for t in frame_times[str(sheet)]]}
    def extract(job, path, times, **kwargs):
        return [SimpleNamespace(time=t) for t in times]
    def sheet(frames, path, **kwargs):
        frame_times[str(path)] = [f.time for f in frames]
        return path
    monkeypatch.setattr(main, "create_vision_client_for_job", lambda job: Vision())
    monkeypatch.setattr(main, "_extract_content_frames", extract)
    monkeypatch.setattr(main, "create_contact_sheet", sheet)
    record = search()
    job = {"id": "contract_adapter", "workDirectory": str(tmp_path), "videoInfo": {"duration": 10}}
    stats = {}
    result = main._verify_content_contract_matches(job, record, [candidate()], threading.Event(), stats)
    assert 2.85 < result[0]["end"] < 3
    assert stats["contractVerifiedCount"] == 1
    assert stats["vlmCalls"] > 0


def test_rendered_qc_reads_output_not_source_and_reports_unrelated_frames(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import main
    actual_inputs, frame_times = [], {}
    class Vision:
        def analyze_image(self, prompt, sheet, **kwargs):
            return {"observations": [{"time": t, "predicates": {"p1": False}} for t in frame_times[str(sheet)]]}
    def extract(path, root, times, **kwargs):
        actual_inputs.append(path)
        return [SimpleNamespace(time=t) for t in times]
    def sheet(frames, path, **kwargs):
        frame_times[str(path)] = [f.time for f in frames]
        return path
    monkeypatch.setattr(main, "create_vision_client_for_job", lambda job: Vision())
    monkeypatch.setattr(main, "extract_frames_at_times", extract)
    monkeypatch.setattr(main, "create_contact_sheet", sheet)
    record = search()
    match = candidate()
    confirm_human_range(match, build_contract(record))
    session = {"id": "s1", "sourceSearchId": record["id"], "contentBinding": selection_binding(record, [match]),
               "clips": [{"id": "c1", "sourceRef": {"id": "m1"}, "sourceStart": 1, "sourceEnd": 8}],
               "schedule": [{"clipId": "c1", "outputStart": 0, "outputEnd": 7}]}
    output = tmp_path / "actual-render.mp4"
    report = main._check_rendered_content({"workDirectory": str(tmp_path)}, session, output)
    assert actual_inputs == [output]
    assert not report["passed"]
    assert report["issues"][0]["code"] == "content_render_sample_mismatch"
    assert report["issues"][0]["status"] == "mismatch"
    assert report["issues"][0]["evidence"]["observations"][0]["outputTime"] == .12
    assert report["renderedSampling"]["exhaustive"] is False


def test_person_appearance_uses_identity_linked_tracks_without_guessing(monkeypatch, tmp_path):
    import threading
    from app import main
    record = search("person.appearance")
    record["intent"]["predicates"][0]["personId"] = "person_1"
    job = {"workDirectory": str(tmp_path), "videoInfo": {"duration": 10}, "contentIndex": {
        "persons": [{"id": "person_1", "label": "人物 A"}],
        "personTracks": [{"personId": "person_1", "start": 1, "end": 3}],
    }}
    monkeypatch.setattr(main, "create_vision_client_for_job", lambda job: pytest.fail("must use identity evidence"))
    result = main._verify_content_contract_matches(job, record, [candidate()], threading.Event(), {})
    assert result[0]["end"] <= 3.04
    assert verification_current(result[0], record["contentContract"])


def test_evidence_approval_replays_proposal_instead_of_skipping_it(monkeypatch, tmp_path):
    from app.agent_platform import AgentPlatform
    platform = AgentPlatform(data_root=tmp_path, service_url="http://agent.invalid",
                             model_config_resolver=lambda: {"model": "fake"})
    workspace = {"id": "ws_contract", "jobId": "job_contract"}
    platform.store.save("workspaces", workspace)
    platform.store.save("plans", {"id": "plan_contract", "workspaceId": workspace["id"], "status": "action_required",
        "steps": [{"id": "propose", "tool": "propose_timeline_edit", "status": "action_required",
                   "result": {"action": "content_evidence_review"}}]})
    advanced = []
    monkeypatch.setattr(platform, "_advance_plan", lambda plan_id: advanced.append(plan_id))
    result = platform.resolve_action("plan_contract", approved=True, value={
        "context": {"jobId": "job_contract", "stepId": "propose"},
        "selection": {"searchId": "search_1", "matchIds": ["m1"]}})
    assert advanced == ["plan_contract"]
    assert result["steps"][0]["status"] == "pending"
    assert "result" not in result["steps"][0]
    platform.resolve_action("plan_contract", approved=True, value={
        "context": {"jobId": "job_contract", "stepId": "propose"},
        "selection": {"searchId": "search_1", "matchIds": ["m1"]}})
    assert advanced == ["plan_contract"]


def test_checkbox_selection_is_not_equivalent_to_human_content_approval(monkeypatch):
    from app import main
    record = search()
    match = pending_match(candidate(), build_contract(record), "insufficient_evidence")
    record.update({"candidates": [match], "reviewDraft": {"selectedMatchIds": ["m1"]}})
    job = {"id": "approval_contract", "contentSearch": record}
    monkeypatch.setitem(main.jobs, job["id"], job)
    step = {"tool": "propose_timeline_edit", "result": {"action": "content_evidence_review"}}
    value = {"context": {"jobId": job["id"]}, "selection": {"searchId": record["id"], "matchIds": ["m1"]}}
    with pytest.raises(ValueError, match="仅勾选"):
        main.validate_agent_action_resolution({"jobId": job["id"]}, step, value)
    confirm_human_range(match, build_contract(record))
    assert main.validate_agent_action_resolution({"jobId": job["id"]}, step, value)


def test_anchor_confirmation_rejects_stale_search_revision(monkeypatch):
    from app import main
    record = search("speech.semantic")
    record.update(candidates=[candidate()], reviewDraft={"selectedMatchIds": ["m1"]})
    job = {"id": "anchor_stale", "contentSearch": record}
    monkeypatch.setitem(main.jobs, job["id"], job)
    step = {"tool": "review_content_evidence", "arguments": {"selectionPolicy": "unique_or_review"}}
    value = {"context": {"jobId": job["id"]}, "selection": {"searchId": "old", "matchIds": ["m1"]}}
    with pytest.raises(ValueError, match="检索结果已更新"):
        main.validate_agent_action_resolution({"jobId": job["id"]}, step, value)
    value["selection"]["searchId"] = record["id"]
    assert main.validate_agent_action_resolution({"jobId": job["id"]}, step, value)


def test_basket_preserves_each_original_query_contract():
    first = search()
    second = search("speech.exact")
    first_match, second_match = candidate(1, 3), {**candidate(5, 7), "id": "m2"}
    for record, match in [(first, first_match), (second, second_match)]:
        confirm_human_range(match, build_contract(record))
        match["sourceContentContract"] = build_contract(record)
    basket = {"id": "basket", "recordType": "assembly", "basketSnapshot": {"items": ["m1", "m2"]}}
    contract = build_contract(basket)
    assert contract["strategy"] == "selection_union"
    assert verification_current(first_match, contract) and verification_current(second_match, contract)


def test_semantic_trim_requires_reverification_even_inside_original_range():
    record = search("speech.semantic")
    match = candidate()
    confirm_human_range(match, build_contract(record))
    session = {"sourceSearchId": record["id"], "contentBinding": selection_binding(record, [match]),
               "clips": [{"sourceRef": {"id": "m1"}, "sourceStart": 2, "sourceEnd": 7}]}
    assert timeline_content_report(session)["issues"][0]["code"] == "content_semantic_boundary_changed"


def test_automatic_proposal_checks_copy_before_mutating_draft(monkeypatch):
    from app import main
    record = search()
    match = candidate()
    confirm_human_range(match, build_contract(record))
    record["candidates"] = [match]
    job = {"id": "contract_trial", "videoInfo": {"duration": 20}, "contentSearch": record}
    session, _ = create_or_resume_content_edit_session(job, search_id=record["id"], selected_match_ids=["m1"])
    session["pendingProposal"] = {"id": "proposal_bad", "status": "pending"}
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda j: pytest.fail("unsafe proposal must not be saved"))
    def apply(job_copy, draft, proposal_id):
        draft["clips"][0]["sourceEnd"] = 15
    monkeypatch.setattr(main, "apply_secondary_edit_proposal", apply)
    result = main.dispatch_agent_tool({"jobId": job["id"], "executionMode": "autonomous_review"}, "confirm_timeline_edit", {})
    assert result["actionRequired"]
    assert session["clips"][0]["sourceEnd"] == 8
    assert session["pendingProposal"]["id"] == "proposal_bad"


def test_rendered_sample_warning_is_visible_only_for_its_revision():
    session = {"revision": 2, "clips": [{"id": "c", "sourceStart": 0, "sourceEnd": 2}],
               "contentVerificationRevision": 2, "contentVerification": {
                   "issues": [{"severity": "warning", "code": "content_render_sample_unavailable", "message": "抽检未完成"}]}}
    assert any(i["code"] == "content_render_sample_unavailable" for i in edit_session_preflight(session)["issues"])
    session["revision"] = 3
    assert not any(i["code"] == "content_render_sample_unavailable" for i in edit_session_preflight(session)["issues"])
