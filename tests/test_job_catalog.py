from __future__ import annotations

import app.main as main_module


def _job(
    job_id: str,
    *,
    updated_at: str,
    status: str,
    workflow: str,
    filename: str,
) -> dict:
    content_mode = workflow != "highlight"
    return {
        "id": job_id,
        "revision": 1,
        "status": status,
        "stage": "content_search_ready" if content_mode else "queued",
        "detail": f"处理 {filename}",
        "filename": filename,
        "taskMode": "content_extract" if content_mode else "highlight",
        "workflowKind": workflow,
        "request": {"workflowKind": workflow},
        "createdAt": updated_at,
        "updatedAt": updated_at,
        "videoInfo": {"duration": 90.0, "width": 1920, "height": 1080, "has_audio": True},
        "eventGroups": [],
        "candidates": [],
        "contentSearch": {},
        "outputVersions": [],
    }


def _catalog(monkeypatch) -> None:
    catalog = {
        "job-completed": _job(
            "job-completed",
            updated_at="2026-08-28T12:01:00Z",
            status="completed",
            workflow="highlight",
            filename="发布会.mp4",
        ),
        "job-active": _job(
            "job-active",
            updated_at="2026-08-28T12:02:00Z",
            status="running",
            workflow="content_search",
            filename="厨房素材.mp4",
        ),
        "job-review": _job(
            "job-review",
            updated_at="2026-08-28T12:03:00Z",
            status="awaiting_content_confirmation",
            workflow="person_edit",
            filename="人物访谈.mp4",
        ),
        "job-failed": _job(
            "job-failed",
            updated_at="2026-08-28T12:04:00Z",
            status="failed",
            workflow="speaker_edit",
            filename="播客.mp4",
        ),
    }
    monkeypatch.setattr(main_module, "jobs", catalog)
    monkeypatch.setattr(
        main_module,
        "thumbnail_state",
        lambda _job: {"status": "ready", "errorCode": None, "detail": ""},
    )
    monkeypatch.setattr(main_module, "schedule_job_thumbnail", lambda _job_id: None)


def test_job_catalog_paginates_newest_first(monkeypatch) -> None:
    _catalog(monkeypatch)

    first = main_module.list_jobs(limit=2)
    second = main_module.list_jobs(limit=2, cursor=first["nextCursor"])

    assert [job["id"] for job in first["jobs"]] == ["job-failed", "job-review"]
    assert first["hasMore"] is True
    assert first["nextCursor"] == "2"
    assert [job["id"] for job in second["jobs"]] == ["job-active", "job-completed"]
    assert second["hasMore"] is False
    assert second["nextCursor"] is None


def test_job_catalog_filters_canonical_status_workflow_and_search(monkeypatch) -> None:
    _catalog(monkeypatch)

    active = main_module.list_jobs(status="active")
    review = main_module.list_jobs(status="action_required")
    person = main_module.list_jobs(workflow="person_edit")
    search = main_module.list_jobs(q="访谈")

    assert [job["id"] for job in active["jobs"]] == ["job-active"]
    assert [job["id"] for job in review["jobs"]] == ["job-review"]
    assert [job["id"] for job in person["jobs"]] == ["job-review"]
    assert [job["id"] for job in search["jobs"]] == ["job-review"]


def test_job_catalog_rejects_invalid_cursor(monkeypatch) -> None:
    _catalog(monkeypatch)

    try:
        main_module.list_jobs(cursor="not-a-cursor")
    except main_module.HTTPException as error:
        assert error.status_code == 400
        assert error.detail == "任务列表游标无效"
    else:
        raise AssertionError("invalid cursors must not silently restart pagination")
