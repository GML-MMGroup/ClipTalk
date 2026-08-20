from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main as main_module
from app.api_schemas import DeleteJobRequest
from app.store import JobStore
from app.task_queue import DurableTaskStore


def _request(session: str = "browser-session") -> Request:
    scope = {
        "type": "http",
        "method": "DELETE",
        "path": "/api/jobs/test",
        "headers": [(b"x-cliptalk-session", session.encode()), (b"user-agent", b"pytest")],
        "client": ("127.0.0.1", 1234),
        "state": {},
    }
    request = Request(scope)
    request.state.request_id = "request-test"
    return request


def _job(root: Path, job_id: str) -> dict:
    source = root / "uploads" / f"{job_id}.mp4"
    work = root / "work" / job_id
    output = root / "outputs" / job_id
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    source.write_bytes(b"source")
    return {
        "id": job_id,
        "revision": 0,
        "status": "completed",
        "stage": "completed",
        "progress": 1.0,
        "filename": "source.mp4",
        "sourcePath": str(source),
        "workDirectory": str(work),
        "outputDirectory": str(output),
        "outputs": [],
        "messages": [],
        "request": {},
        "createdAt": "2026-08-20T00:00:00+00:00",
        "updatedAt": "2026-08-20T00:00:00+00:00",
    }


def test_delete_requires_one_time_intent_bound_to_revision(tmp_path: Path) -> None:
    original_settings = main_module.settings
    original_store = main_module.job_store
    original_analysis_store = main_module.analysis_task_store
    original_render_store = main_module.render_task_store
    job_id = "job_delete_intent_test"
    try:
        main_module.settings = replace(original_settings, data_root=tmp_path)
        main_module.settings.ensure_directories()
        main_module.job_store = JobStore(tmp_path / "jobs.sqlite3")
        main_module.analysis_task_store = DurableTaskStore(tmp_path / "analysis.sqlite3")
        main_module.render_task_store = DurableTaskStore(tmp_path / "render.sqlite3", one_active_per_job=False)
        main_module.delete_intents.clear()
        main_module.delete_attempts.clear()
        job = _job(tmp_path, job_id)
        main_module.jobs[job_id] = job
        main_module.save_job(job)

        intent = main_module.create_job_delete_intent(job_id, _request())
        result = main_module.delete_job(
            job_id,
            DeleteJobRequest(revision=intent["revision"], deleteIntent=intent["deleteIntent"]),
            _request(),
        )

        assert result["deleted"] is True
        assert result["requestId"] == "request-test"
        assert job_id not in main_module.jobs
        assert not Path(job["sourcePath"]).exists()
        records = [json.loads(line) for line in (tmp_path / "audit" / "job-deletions.jsonl").read_text().splitlines()]
        assert [record["result"] for record in records[-2:]] == ["authorized", "deleted"]

        with pytest.raises(HTTPException, match="删除凭证无效或已使用"):
            main_module.delete_job(
                job_id,
                DeleteJobRequest(revision=intent["revision"], deleteIntent=intent["deleteIntent"]),
                _request(),
            )
    finally:
        main_module.jobs.pop(job_id, None)
        main_module.delete_intents.clear()
        main_module.delete_attempts.clear()
        main_module.settings = original_settings
        main_module.job_store = original_store
        main_module.analysis_task_store = original_analysis_store
        main_module.render_task_store = original_render_store


def test_delete_rejects_revision_changed_after_confirmation(tmp_path: Path) -> None:
    original_settings = main_module.settings
    job_id = "job_delete_revision_test"
    try:
        main_module.settings = replace(original_settings, data_root=tmp_path)
        main_module.settings.ensure_directories()
        main_module.delete_intents.clear()
        job = _job(tmp_path, job_id)
        main_module.jobs[job_id] = job
        intent = main_module.create_job_delete_intent(job_id, _request("revision-session"))
        job["revision"] = int(intent["revision"]) + 1

        with pytest.raises(HTTPException, match="任务已发生变化"):
            main_module.delete_job(
                job_id,
                DeleteJobRequest(revision=intent["revision"], deleteIntent=intent["deleteIntent"]),
                _request("revision-session"),
            )
        assert Path(job["sourcePath"]).is_file()
    finally:
        main_module.jobs.pop(job_id, None)
        main_module.delete_intents.clear()
        main_module.settings = original_settings
