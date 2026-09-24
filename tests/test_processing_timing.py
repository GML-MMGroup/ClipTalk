from datetime import datetime, timedelta, timezone

from app.main import _update_processing_elapsed


def test_processing_timing_excludes_waiting_and_freezes_after_completion() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = {
        "status": "running",
        "startedAt": start.isoformat().replace("+00:00", "Z"),
        "processingElapsedSeconds": 0,
    }

    _update_processing_elapsed(job, now=start)
    job["status"] = "running"
    _update_processing_elapsed(job, now=start.replace(second=30))
    assert job["processingElapsedSeconds"] == 30

    job["status"] = "awaiting_confirmation"
    _update_processing_elapsed(job, now=start.replace(second=31))
    _update_processing_elapsed(job, now=start + timedelta(seconds=90))
    assert job["processingElapsedSeconds"] == 31

    job["status"] = "running"
    _update_processing_elapsed(job, now=start + timedelta(seconds=100))
    _update_processing_elapsed(job, now=start + timedelta(seconds=115))
    assert job["processingElapsedSeconds"] == 46

    job["status"] = "completed"
    _update_processing_elapsed(job, now=start + timedelta(seconds=116))
    _update_processing_elapsed(job, now=start + timedelta(seconds=500))
    assert job["processingElapsedSeconds"] == 47


def test_processing_timing_follows_agent_execution_and_excludes_user_waits() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = {
        "status": "awaiting_agent_plan",
        "stage": "agent_plan_running",
        "processingElapsedSeconds": 300,
        "processingTimingVersion": 1,
        "agent": {"status": "running", "completedSteps": 7, "totalSteps": 10},
    }

    _update_processing_elapsed(job, now=start)
    assert job["processingActiveSince"] == "2026-01-01T00:00:00Z"
    _update_processing_elapsed(job, now=start + timedelta(seconds=45))
    assert job["processingElapsedSeconds"] == 345

    job["agent"]["status"] = "action_required"
    _update_processing_elapsed(job, now=start + timedelta(seconds=46))
    _update_processing_elapsed(job, now=start + timedelta(seconds=120))
    assert job["processingElapsedSeconds"] == 346
    assert "processingActiveSince" not in job

    job["agent"]["status"] = "running"
    _update_processing_elapsed(job, now=start + timedelta(seconds=130))
    _update_processing_elapsed(job, now=start + timedelta(seconds=150))
    assert job["processingElapsedSeconds"] == 366

    job["agent"]["status"] = "preview_ready"
    _update_processing_elapsed(job, now=start + timedelta(seconds=151))
    _update_processing_elapsed(job, now=start + timedelta(seconds=300))
    assert job["processingElapsedSeconds"] == 367
    assert "processingActiveSince" not in job
