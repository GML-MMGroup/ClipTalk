from app.algorithm_contract import (
    ALGORITHM_V1,
    ALGORITHM_V2,
    CostController,
    attach_candidate_quality,
    algorithm_version,
)


def test_missing_algorithm_snapshot_is_always_v1() -> None:
    assert algorithm_version({}) == ALGORITHM_V1
    assert algorithm_version({"algorithmVersion": ALGORITHM_V2}) == ALGORITHM_V2


def test_low_confidence_candidate_remains_visible_but_unselected() -> None:
    candidate = {"score": 55, "confidence": .57, "selected": True}
    attach_candidate_quality(candidate, coverage_status="partial")
    assert candidate["selected"] is False
    assert candidate["requiresReview"] is True
    assert candidate["quality"]["coverageStatus"] == "partial"
    assert "weak_evidence" in candidate["quality"]["reviewReasons"]


def test_cost_controller_never_exceeds_twice_baseline() -> None:
    budget = CostController(baseline_frames=10, baseline_vlm_calls=2, baseline_llm_calls=1)
    assert budget.consume("frames", 20)
    assert not budget.consume("frames", 1)
    assert budget.consume("vlm", 4)
    assert not budget.consume("llm", 3)
    assert budget.snapshot()["degradations"] == ["frame_budget_exhausted", "llm_budget_exhausted"]
