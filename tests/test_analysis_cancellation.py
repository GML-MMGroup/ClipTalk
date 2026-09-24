from __future__ import annotations

import threading
import time

import pytest

from app import main as main_app
from app.media import MediaError, _run_cancellable


def test_content_progress_cannot_resurrect_cancelled_job(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = "job_cancel_progress_guard"
    event = threading.Event()
    event.set()
    job = {
        "id": job_id,
        "status": "cancelled",
        "stage": "cancelled",
        "progress": .4,
        "detail": "任务已取消",
    }
    monkeypatch.setitem(main_app.jobs, job_id, job)
    monkeypatch.setitem(main_app.cancel_events, job_id, event)
    monkeypatch.setattr(main_app, "save_job", lambda _job: None)

    main_app._content_progress(
        job_id, .8, "content_recognition", "人物识别（1000/2800 帧）",
        completed=1000, total=2800, unit="帧",
    )

    assert job["status"] == "cancelled"
    assert job["stage"] == "cancelled"
    assert job["progress"] == .4
    assert job["detail"] == "任务已取消"


def test_cancellable_media_process_stops_during_execution() -> None:
    started = time.monotonic()

    def cancelled() -> bool:
        return time.monotonic() - started >= .15

    with pytest.raises(MediaError, match="任务已取消"):
        _run_cancellable(
            ["/bin/sh", "-c", "sleep 10"], timeout=20, cancelled=cancelled,
        )

    assert time.monotonic() - started < 2
