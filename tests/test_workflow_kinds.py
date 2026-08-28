from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app import main
from app.api_schemas import PersonTargetRequest, SameSourceTaskRequest
from app.main import source_project_id_for_job, workflow_kind_for_job, workflow_snapshot


@pytest.mark.parametrize(
    ("job", "expected"),
    [
        ({"workflowKind": "highlight", "taskMode": "content_extract"}, "highlight"),
        ({"request": {"workflowKind": "person_edit"}, "taskMode": "content_extract"}, "person_edit"),
        ({"request": {"entryWorkflow": "voice_discovery"}, "taskMode": "content_extract"}, "speaker_edit"),
        ({"request": {"entryWorkflow": "person_discovery"}, "taskMode": "content_extract"}, "person_edit"),
        ({"taskMode": "content_extract"}, "content_search"),
        ({"taskMode": "highlight"}, "highlight"),
    ],
)
def test_workflow_kind_preserves_explicit_modes_and_upgrades_legacy_jobs(job, expected) -> None:
    assert workflow_kind_for_job(job) == expected


def test_request_workflow_wins_over_stale_generic_router_state() -> None:
    job = {
        "workflowKind": "content_search", "taskMode": "content_extract",
        "request": {
            "workflowKind": "person_edit", "entryWorkflow": "person_discovery",
        },
    }
    assert workflow_kind_for_job(job) == "person_edit"


@pytest.mark.parametrize(
    ("job", "operation"),
    [
        ({"workflowKind": "highlight", "request": {}, "briefStatus": "confirmed"}, "highlight_analysis"),
        ({"workflowKind": "content_search", "request": {}, "taskMode": "content_extract"}, "content_initial_search"),
        ({"workflowKind": "content_search", "request": {}, "taskMode": "content_extract", "pendingContentSearch": {"id": "next"}}, "content_followup_search"),
        ({"workflowKind": "person_edit", "request": {}, "taskMode": "content_extract"}, "person_discovery"),
        ({"workflowKind": "speaker_edit", "request": {}, "taskMode": "content_extract"}, "speaker_discovery"),
    ],
)
def test_analysis_operation_is_workflow_specific(job, operation) -> None:
    assert main.analysis_operation_for_job(job)["kind"] == operation


def test_incompatible_stored_operation_cannot_override_workflow() -> None:
    job = {
        "workflowKind": "speaker_edit", "taskMode": "content_extract", "request": {},
        "analysisOperation": {"kind": "content_initial_search", "payload": {}},
    }
    assert main.analysis_operation_for_job(job)["kind"] == "speaker_discovery"


def test_submit_workflow_analysis_uses_exact_worker_and_arguments(monkeypatch) -> None:
    job_id = "dispatch-speaker"
    captured = []
    main.jobs[job_id] = {
        "id": job_id, "workflowKind": "speaker_edit", "taskMode": "content_extract",
        "request": {"workflowKind": "speaker_edit"}, "revision": 0,
    }
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(
        main, "submit_analysis_task",
        lambda submitted_id, target, *args: captured.append((submitted_id, target, args)) or object(),
    )
    try:
        main.submit_workflow_analysis(job_id)
        assert captured == [(job_id, main.run_current_voice_discovery, (job_id,))]
        assert main.jobs[job_id]["analysisOperation"]["kind"] == "speaker_discovery"
    finally:
        main.jobs.pop(job_id, None)


def test_unbound_selector_routes_unrelated_search_to_isolated_content_task() -> None:
    speaker = {
        "workflowKind": "speaker_edit", "taskMode": "content_extract",
        "request": {"workflowKind": "speaker_edit"},
    }
    assert main._explicit_cross_workflow(speaker, "帮我找到和家用电器相关的片段") == "content_search"
    assert main._explicit_cross_workflow(speaker, "识别并选择视频中的说话人") is None


def test_bound_person_followup_stays_in_person_task() -> None:
    job = {
        "workflowKind": "person_edit", "taskMode": "content_extract",
        "request": {
            "workflowKind": "person_edit",
            "contentSearchPersonTarget": {"personIds": ["person_1"], "matchMode": "any"},
        },
    }
    assert main._explicit_cross_workflow(job, "找出这个人物正在做饭的片段") is None


def test_reanalyze_resumes_speaker_discovery_not_generic_content_search(monkeypatch) -> None:
    job_id = "retry-speaker"
    submitted = []
    main.jobs[job_id] = {
        "id": job_id, "status": "cancelled", "stage": "cancelled",
        "workflowKind": "speaker_edit", "taskMode": "content_extract",
        "request": {"workflowKind": "speaker_edit", "entryWorkflow": "voice_discovery"},
        "analysisOperation": {"kind": "speaker_discovery", "payload": {}, "attempt": 1},
        "voiceDiscovery": {"status": "cancelled", "expectedSpeakerCount": 2},
        "messages": [], "revision": 0,
    }
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda job: copy.deepcopy(job))
    monkeypatch.setattr(
        main, "submit_workflow_analysis",
        lambda submitted_id, operation=None, payload=None: submitted.append((submitted_id, operation, payload)),
    )
    try:
        result = main.reanalyze_cancelled_job(job_id)
        assert submitted == [(job_id, "speaker_discovery", {})]
        assert result["job"]["status"] == "queued"
        assert main.jobs[job_id]["voiceDiscovery"]["status"] == "running"
    finally:
        main.jobs.pop(job_id, None)
        main.cancel_events.pop(job_id, None)


def test_person_retry_archives_stale_scan_without_losing_history(monkeypatch) -> None:
    job_id = "retry-person"
    main.jobs[job_id] = {
        "id": job_id, "status": "failed", "stage": "failed",
        "workflowKind": "person_edit", "taskMode": "content_extract",
        "request": {"workflowKind": "person_edit", "entryWorkflow": "person_discovery"},
        "analysisOperation": {"kind": "person_discovery", "payload": {}, "attempt": 1},
        "contentSearch": {"id": "stale-scan", "status": "scanning", "candidates": []},
        "contentSearchHistory": [], "messages": [], "revision": 0,
    }
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "public_job", lambda job: copy.deepcopy(job))
    monkeypatch.setattr(main, "submit_workflow_analysis", lambda *_args, **_kwargs: None)
    try:
        main.reanalyze_cancelled_job(job_id)
        assert main.jobs[job_id]["contentSearch"] is None
        assert main.jobs[job_id]["contentSearchHistory"][0]["id"] == "stale-scan"
        assert main.jobs[job_id]["contentSearchHistory"][0]["status"] == "interrupted"
    finally:
        main.jobs.pop(job_id, None)
        main.cancel_events.pop(job_id, None)


def test_person_target_activity_is_optional_and_typed() -> None:
    assert PersonTargetRequest(personIds=["person_1"], matchMode="any").activity is None
    assert PersonTargetRequest(
        personIds=["person_1"], matchMode="any", activity="appearance",
    ).activity == "appearance"
    with pytest.raises(ValidationError):
        PersonTargetRequest(personIds=["person_1"], activity="voice")


def test_same_source_task_request_accepts_the_four_public_workflows() -> None:
    for workflow in ("highlight", "content_search", "person_edit", "speaker_edit"):
        assert SameSourceTaskRequest(workflowKind=workflow).workflowKind == workflow
    assert SameSourceTaskRequest(workflowKind="highlight", autoCompose=False).autoCompose is False


def test_source_project_and_workflow_snapshots_are_workflow_specific() -> None:
    base = {
        "id": "one", "sourceHash": "same-media", "status": "awaiting_content_confirmation",
        "stage": "voice_discovery_available", "taskMode": "content_extract",
        "workflowKind": "speaker_edit", "request": {}, "voiceDiscovery": {"status": "ready"},
    }
    assert source_project_id_for_job(base) == source_project_id_for_job({**base, "id": "two"})
    snapshot = workflow_snapshot(base)
    assert snapshot["kind"] == "speaker_edit"
    assert snapshot["actionRequired"]["kind"] == "select_speaker"
    assert any(step["label"] == "选择目标说话人" for step in snapshot["steps"])


def test_same_source_speaker_task_reuses_asset_and_keeps_parent_isolated(tmp_path, monkeypatch) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = uploads / "parent.mp4"
    source.write_bytes(b"same-source")
    parent_id = "workflow-parent"
    parent = {
        "id": parent_id, "status": "completed", "stage": "completed",
        "filename": "interview.mp4", "sourcePath": str(source),
        "sourceHash": "asset-hash", "sizeBytes": source.stat().st_size,
        "storageMode": "editable", "taskMode": "highlight",
        "request": {"analysisMode": "audiovisual"},
        "videoInfo": {"duration": 30.0, "has_audio": True},
        "messages": [{"id": "old", "role": "user", "text": "旧任务"}],
        "outputs": [], "outputVersions": [],
    }
    monkeypatch.setattr(main, "settings", replace(main.settings, data_root=tmp_path))
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "schedule_job_thumbnail", lambda _job_id: None)
    with main.jobs_lock:
        main.jobs[parent_id] = parent
    child_id = ""
    try:
        result = main.create_same_source_task_job(
            parent_id, SameSourceTaskRequest(workflowKind="speaker_edit"),
        )
        child = result["job"]
        child_id = child["id"]
        assert child["workflowKind"] == "speaker_edit"
        assert child["taskMode"] == "content_extract"
        assert child["request"]["entryWorkflow"] == "voice_discovery"
        assert child["parentJobId"] == parent_id
        assert child["status"] == "awaiting_content_confirmation"
        assert result["handoff"]["fromJobId"] == parent_id
        assert main.jobs[parent_id]["status"] == "completed"
        assert main.jobs[parent_id]["activeChildJobId"] == child_id
    finally:
        with main.jobs_lock:
            main.jobs.pop(parent_id, None)
            if child_id:
                main.jobs.pop(child_id, None)


def test_same_source_highlight_can_disable_automatic_composition(tmp_path, monkeypatch) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = uploads / "parent.mp4"
    source.write_bytes(b"same-source")
    parent_id = "highlight-analysis-parent"
    parent = {
        "id": parent_id, "status": "completed", "stage": "completed",
        "filename": "source.mp4", "sourcePath": str(source),
        "sourceHash": "highlight-analysis-hash", "sizeBytes": source.stat().st_size,
        "storageMode": "editable", "taskMode": "content_extract",
        "workflowKind": "content_search", "request": {"analysisMode": "audiovisual"},
        "videoInfo": {"duration": 30.0, "has_audio": True},
        "messages": [], "outputs": [], "outputVersions": [],
    }

    def enqueue_without_worker(job, **_kwargs) -> None:
        with main.jobs_lock:
            main.jobs[job["id"]] = job

    monkeypatch.setattr(main, "settings", replace(main.settings, data_root=tmp_path))
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "enqueue_job", enqueue_without_worker)
    with main.jobs_lock:
        main.jobs[parent_id] = parent
    child_id = ""
    try:
        result = main.create_same_source_task_job(
            parent_id,
            SameSourceTaskRequest(workflowKind="highlight", autoCompose=False),
        )
        child = result["job"]
        child_id = child["id"]
        assert child["workflowKind"] == "highlight"
        assert child["autoCompose"] is False
        assert main.jobs[child_id]["autoCompose"] is False
    finally:
        with main.jobs_lock:
            main.jobs.pop(parent_id, None)
            if child_id:
                main.jobs.pop(child_id, None)
