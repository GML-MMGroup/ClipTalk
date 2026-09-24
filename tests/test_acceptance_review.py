import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("real_video_acceptance", Path(__file__).with_name("real_video_acceptance.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("approval", ["missing", "stale", "changed", "valid"])
def test_review_checkpoint_requires_explicit_current_ranges(tmp_path, approval):
    runner = object.__new__(module.Runner)
    runner.directory = tmp_path
    runner.args = SimpleNamespace(review_input=tmp_path / "approval.json")
    writes = []
    def request(method, route, **kwargs):
        if method != "GET":
            writes.append((route, kwargs["json"]))
            return {}
        if "workspaces" in route:
            return {"workspace": {"jobId": "job"}}
        return {"job": {"contentSearch": {"id": "search", "candidates": [{"id": "m", "start": 2, "end": 8}]}}}
    runner.request = request
    plan = {"id": "plan", "steps": [{"id": "step", "tool": "review_content_evidence", "status": "action_required", "result": {}}]}
    value = {"planId": "plan", "jobId": "job", "stepId": "step", "searchId": "search", "reviewed": True,
             "matches": [{"id": "m", "start": 2, "end": 8}]}
    if approval == "stale":
        value["searchId"] = "old"
    if approval == "changed":
        value["matches"][0]["end"] = 9
    if approval != "missing":
        runner.args.review_input.write_text(json.dumps(value))
    if approval == "changed":
        with pytest.raises(ValueError, match="ranges"):
            runner.review_checkpoint("topic", "workspace", plan)
    else:
        assert runner.review_checkpoint("topic", "workspace", plan) is (approval == "valid")
    assert len(writes) == (3 if approval == "valid" else 0)
    assert (tmp_path / "topic-checkpoint.json").is_file()
