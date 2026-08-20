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
