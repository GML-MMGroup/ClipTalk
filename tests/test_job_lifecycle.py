from app.job_lifecycle import (
    ACTIVE_EXECUTION_STATUSES,
    CANCELLABLE_STATUSES,
    can_cancel,
    can_delete,
    has_background_execution,
    has_active_execution,
    interrupted_job_patch,
)


def test_active_and_waiting_states_have_distinct_worker_semantics() -> None:
    assert {"briefing", "queued", "running", "cancelling"} == ACTIVE_EXECUTION_STATUSES
    assert has_active_execution({"status": "running"})
    assert not has_active_execution({"status": "awaiting_confirmation"})
    assert "awaiting_confirmation" in CANCELLABLE_STATUSES
    assert can_cancel({"status": "awaiting_confirmation"})
    assert not can_cancel({"status": "completed"})


def test_active_job_must_be_cancelled_before_deletion() -> None:
    assert not can_delete({"status": "queued"})
    assert can_delete({"status": "awaiting_confirmation"})
    assert can_delete({"status": "completed"})


def test_nested_automatic_composition_is_an_active_execution() -> None:
    job = {
        "status": "awaiting_confirmation",
        "autoComposition": {"status": "running"},
    }
    assert has_background_execution(job)
    assert has_active_execution(job)
    assert can_cancel(job)
    assert not can_delete(job)
    assert not has_background_execution({
        "status": "awaiting_confirmation",
        "autoComposition": {"status": "completed"},
    })


def test_interrupted_patch_is_consistent_and_resumable_only_with_checkpoint() -> None:
    resumable = interrupted_job_patch(checkpoint_available=True, now="2026-08-14T00:00:00+00:00")
    assert resumable["status"] == "failed"
    assert resumable["stage"] == "interrupted"
    assert resumable["resumeAvailable"] is True
    assert resumable["interruptedAt"] == resumable["updatedAt"]
    non_resumable = interrupted_job_patch(checkpoint_available=False, now="later")
    assert non_resumable["resumeAvailable"] is False
    assert "重新分析" in non_resumable["detail"]
