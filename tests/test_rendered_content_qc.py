import copy
from types import SimpleNamespace

import pytest

from app.agent_platform import AgentPlatform
from app.content_contract import build_contract, confirm_human_range, selection_binding
from app.content_search import parse_content_intent
from app.rendered_content_qc import assess_sample, assess_coverage, aspect_check


QUERY = "产品新老替换和核心卖点"
GOAL = "找出产品新老替换和核心卖点画面，合成竖屏产品宣传短片，并生成审核样片。并找到一个具有冲击力的画面做封面，封面上写：小米厉害！！"
CONTRACT = {"query": QUERY, "strategy": "semantic_context", "predicates": [{"id": "p1", "value": "新老替换"}]}
CLIP = {"id": "c1", "title": "冰箱换新", "sourceStart": 95.4, "sourceEnd": 117.28}
TIMES = [.12, 5.53, 10.94, 16.35, 21.76]


@pytest.mark.parametrize("query,expected", [
    (GOAL, True), ("生成竖屏品牌宣传短片，并制作封面", True),
    ("生成横屏产品宣传短片，并制作封面", True),
    ("制作9:16封面", False), ("制作竖屏封面，视频保持原样", False),
])
def test_video_aspect_is_not_erased_by_cover(query, expected):
    brief = AgentPlatform._editing_brief(query, {})
    assert brief["socialDelivery"]["requested"] is expected
    if query == GOAL:
        assert brief["socialDelivery"]["aspect"] == "9:16"
        assert brief["coverTitle"] == "小米厉害！！"


def test_semantic_clip_uses_context_not_unanimous_still_frames():
    raw = {"observations": [{"frameIndex": i, "predicates": {"p1": False}, "reason": "本帧只显示冰箱"} for i in range(1, 6)],
           "summary": {"querySatisfied": True, "reason": "前后场景与源对白支持冰箱换新过程"}}
    result = assess_sample(raw, CONTRACT, TIMES, CLIP, 0, 21.88)
    assert result["status"] == "supported"
    assert result["issue"] is None
    assert result["evidence"]["observations"][0]["outputTime"] == .12


@pytest.mark.parametrize("value,status", [(False, "mismatch"), (None, "unknown"), ("false", "unknown")])
def test_semantic_uncertainty_is_not_mismatch(value, status):
    result = assess_sample({"summary": {"querySatisfied": value, "reason": "检查说明"}}, CONTRACT, TIMES, CLIP, 0, 21.88)
    assert result["status"] == status
    assert result["issue"]["severity"] == ("error" if status == "mismatch" else "warning")


def test_missing_duplicate_or_rounded_frames_are_unknown_not_false():
    contract = {**CONTRACT, "strategy": "visible_intervals"}
    for raw in ({}, {"observations": [{"time": 0, "predicates": {"p1": True}}]},
                {"observations": [{"frameIndex": 1, "predicates": {"p1": True}}] * 2}):
        assert assess_sample(raw, contract, TIMES, CLIP, 0, 21.88)["status"] == "unknown"
    raw = {"observations": [{"frameIndex": i, "predicates": {"p1": i != 3}} for i in range(1, 6)]}
    assert assess_sample(raw, contract, TIMES, CLIP, 0, 21.88)["status"] == "mismatch"


def test_full_query_coverage_keeps_distinct_requirements_and_real_clip_bindings():
    sample = assess_sample({}, CONTRACT, TIMES, CLIP, 0, 21.88)
    result = assess_coverage({"querySatisfied": None, "requirements": [
        {"requirement": "产品新老替换", "status": "supported", "reason": "冰箱换新过程", "clipIds": ["c1"]},
        {"requirement": "核心卖点", "status": "unknown", "reason": "仅抽样画面不足以确认", "clipIds": ["c1"]},
    ]}, [sample], QUERY)
    assert len(result["requirements"]) == 2
    assert result["issues"][0]["status"] == "unknown"
    assert result["issues"][0]["evidence"]["ranges"] == [{"start": 0, "end": 21.88}]
    for raw in ({"querySatisfied": True}, {"requirements": "wrong"},
                {"querySatisfied": True, "requirements": [{"requirement": QUERY, "status": "supported", "reason": "yes", "clipIds": ["invented"]}]}):
        assert assess_coverage(raw, [sample], QUERY)["issues"]


def test_aspect_check_uses_actual_video_dimensions():
    assert aspect_check(720, 1280, "9:16") is None
    issue = aspect_check(960, 540, "9:16")
    assert issue["code"] == "delivery_aspect_mismatch"
    assert issue["severity"] == "error"
    assert "960×540" in issue["message"]
    assert aspect_check(None, None, "9:16")["status"] == "unavailable"
    assert aspect_check(960, 540, "source") is None


def test_delivery_worker_reports_wrong_video_aspect_even_with_portrait_cover(monkeypatch, tmp_path):
    from concurrent.futures import Future
    from app import main
    (tmp_path / "review.mp4").touch()
    job = {"id": "qc_aspect_test", "outputDirectory": str(tmp_path), "brief": {},
           "outputs": [{"filename": "review.mp4", "duration": 23.88}],
           "coverVersions": [{"id": "cover", "width": 720, "height": 1280, "titleText": "旧标题", "titleLines": ["旧标题"]}], "currentCoverVersionId": "cover"}
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "analyze_rendered_media", lambda *a, **kw: {
        "passed": True, "issues": [], "media": {"duration": 23.88, "width": 960, "height": 540}})
    def submit(worker):
        future = Future()
        future.set_result(worker())
        return future
    monkeypatch.setattr(main.output_preview_executor, "submit", submit)
    queued = main.dispatch_agent_tool({"jobId": job["id"]}, "run_delivery_qc", {
        "expectedAspect": "9:16", "requireCover": True, "expectedCoverTitle": "小米厉害！！"})
    artifact = queued["future"].result()["artifact"]
    assert artifact["passed"] is False
    assert artifact["reports"][0]["aspectCheck"]["status"] == "mismatch"
    assert artifact["reports"][0]["issues"][0]["code"] == "delivery_aspect_mismatch"
    assert any(issue["code"] == "requested_cover_not_validated" for issue in artifact["reports"][0]["issues"])


def test_distinct_content_goals_are_not_collapsed_to_first_visual_branch():
    predicates = [
        {"id": "p1", "kind": "visual.semantic", "value": "产品新老替换", "sourceSpan": {"start": 0, "end": 6, "text": "产品新老替换"}},
        {"id": "p2", "kind": "speech.semantic", "value": "核心卖点", "sourceSpan": {"start": 7, "end": 11, "text": "核心卖点"}},
        {"id": "p3", "kind": "screen_text.text", "value": "核心卖点", "sourceSpan": {"start": 7, "end": 11, "text": "核心卖点"}},
    ]
    for p in predicates:
        p["subject"] = {"description": "产品", "type": "object"}
    result = parse_content_intent(QUERY, {"query": QUERY, "retrievalScope": "broad_multisource", "predicates": predicates,
        "logic": {"op": "any", "children": [{"op": "predicate", "predicateId": p["id"]} for p in predicates]}})
    assert {p["id"] for p in result["predicates"]} == {"p1", "p2", "p3"}


def test_rendered_qc_saves_context_and_distinguishes_service_failure(monkeypatch, tmp_path):
    from app import main
    calls = []
    class Vision:
        def analyze_image(self, prompt, sheet, **kwargs):
            calls.append(prompt)
            if sheet.name == "coverage.jpg":
                assert QUERY in prompt and "核心卖点" in prompt
                return {"querySatisfied": True, "requirements": [
                    {"requirement": QUERY, "status": "supported", "clipIds": ["c1"], "reason": "画面和对白上下文分别支持两项目标"}]}
            return {"summary": {"querySatisfied": True, "reason": "本段支持换新目标"}, "observations": [
                {"frameIndex": i, "predicates": {"p1": i == 5}, "reason": "抽样画面"} for i in range(1, 6)]}
    monkeypatch.setattr(main, "create_vision_client_for_job", lambda job: Vision())
    monkeypatch.setattr(main, "extract_frames_at_times", lambda path, root, times, **kw: [SimpleNamespace(time=t) for t in times])
    def sheet(frames, path, **kwargs):
        assert kwargs["preserve_frame"] is True
        return path
    monkeypatch.setattr(main, "create_contact_sheet", sheet)
    record = {"id": "search", "instruction": QUERY, "intent": {"predicates": [{"id": "p1", "kind": "visual.semantic", "value": QUERY}]}}
    match = {"id": "m1", "start": 95.4, "end": 117.28}
    confirm_human_range(match, build_contract(record))
    session = {"id": "s1", "revision": 2, "sourceSearchId": "search", "contentBinding": selection_binding(record, [match]),
               "clips": [{**CLIP, "sourceRef": {"id": "m1"}}], "schedule": [{"clipId": "c1", "outputStart": 0, "outputEnd": 21.88}]}
    job = {"workDirectory": str(tmp_path), "transcript": [{"start": 96, "end": 97, "text": "新冰箱更节能"}]}
    original = copy.deepcopy(session)
    report = main._check_rendered_content(job, session, tmp_path / "actual.mp4")
    assert report["passed"] is True
    assert report["samples"][0]["status"] == "supported"
    assert report["previewBinding"]["revision"] == 2
    assert len(calls) == 2 and "新冰箱更节能" in calls[0]
    assert session == original
    def unavailable(job):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(main, "create_vision_client_for_job", unavailable)
    report = main._check_rendered_content(job, session, tmp_path / "actual.mp4")
    assert not report["passed"]
    assert report["issues"][-1]["status"] == "unavailable"
    assert report["renderedSampling"]["clipCount"] == 0
