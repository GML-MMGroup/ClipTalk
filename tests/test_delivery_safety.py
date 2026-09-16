from __future__ import annotations

import copy
import json
import threading
import time
import subprocess
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app import main
from app.agent_platform import AgentServiceClient
from app.delivery import merge_committed_version, output_capabilities, output_revision, prepare_formal_export, select_export_output
from app.job_persistence import persist_job
from app.job_projection import ui_presentation_snapshot
from app.service_security import plugin_tree_hash, service_token
from app.store import JobStore
from app.task_queue import DurableTaskExecutor, DurableTaskStore
from app.worker_lock import WorkerLock
from app.render_spec import freeze_spec, output_spec, validate_spec, content_hash
from app.subtitle_review import output_fingerprints


def test_queue_does_not_steal_live_owner_and_fences_old_completion(tmp_path):
    first = DurableTaskStore(tmp_path / "tasks.db")
    second = DurableTaskStore(tmp_path / "tasks.db")
    task = first.enqueue(job_id="job", kind="work", args=())
    assert first.claim(task["id"])
    assert second.prepare_recovery() == []
    assert not second.claim(task["id"])
    with first._connect() as connection:
        connection.execute("UPDATE tasks SET lease_until=0")
    assert len(second.prepare_recovery()) == 1
    assert second.claim(task["id"])
    assert not first.heartbeat(task["id"])
    first.finish(task["id"], status="completed")
    assert second.get(task["id"])["status"] == "running"
    second.finish(task["id"], status="completed")
    assert first.get(task["id"])["attempts"] == 2


def test_executor_renews_lease_during_long_task(tmp_path):
    store = DurableTaskStore(tmp_path / "tasks.db", lease_seconds=1)
    observer = DurableTaskStore(tmp_path / "tasks.db", lease_seconds=1)
    started = threading.Event()
    release = threading.Event()
    def work():
        started.set()
        release.wait(5)
    with ThreadPoolExecutor(1) as pool:
        executor = DurableTaskExecutor(store=store, executor=pool)
        task_id, future = executor.submit(job_id="job", target=work, args=())
        assert started.wait(2)
        try:
            time.sleep(1.3)
            assert observer.prepare_recovery() == []
            assert observer.get(task_id)["attempts"] == 1
        finally:
            release.set()
        future.result(timeout=2)


def test_concurrent_idempotent_submission_and_retry(tmp_path):
    stores = [DurableTaskStore(tmp_path / "tasks.db", one_active_per_job=False) for _ in range(2)]
    barrier = threading.Barrier(2)
    def enqueue(store):
        barrier.wait()
        return store.enqueue(job_id="job", kind="render", args=("selected",), dedup_key="output:r1")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(enqueue, stores))
    assert results[0]["id"] == results[1]["id"]
    assert sum(bool(item.get("duplicate")) for item in results) == 1
    owner = stores[0]
    assert owner.claim(results[0]["id"])
    owner.finish(results[0]["id"], status="failed")
    retry = owner.enqueue(job_id="job", kind="render", args=(), dedup_key="output:r1")
    assert retry["id"] != results[0]["id"]
    assert owner.claim(retry["id"])
    owner.finish(retry["id"], status="completed")
    assert owner.enqueue(job_id="job", kind="render", args=(), dedup_key="output:r1")["id"] == retry["id"]
    assert owner.enqueue(job_id="job", kind="render", args=(), dedup_key="other:r1")["id"] != retry["id"]


@pytest.fixture
def delivery_job(tmp_path, monkeypatch):
    settings = replace(main.settings, data_root=tmp_path)
    settings.ensure_directories()
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "job_store", JobStore(tmp_path / "jobs.db"))
    monkeypatch.setattr(main, "render_task_store", DurableTaskStore(tmp_path / "render.db", one_active_per_job=False))
    outputs = [{"filename": f"{name}.mp4", "previewOnly": True,
                "segments": [{"id": name, "start": offset, "end": offset + 2}]}
               for name, offset in [("first", 0), ("second", 10)]]
    for output in outputs:
        (tmp_path / output["filename"]).write_bytes(b"media")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    version = {"id": "v001", "number": 1, "previewOnly": True, "qualityStatus": "passed", "outputs": outputs}
    job = {"id": "job_delivery", "filename": "source.mp4", "sourcePath": str(source),
           "outputDirectory": str(tmp_path), "workDirectory": str(tmp_path), "request": {},
           "status": "awaiting_confirmation", "stage": "review", "messages": [],
           "outputVersions": [version], "outputs": outputs, "currentOutputVersionId": "v001"}
    monkeypatch.setattr(main, "jobs", {job["id"]: job})
    monkeypatch.setattr(main, "cancel_events", {})
    main.save_job(job)
    return job


def test_finalize_routes_exact_file_and_deduplicates(delivery_job, monkeypatch):
    job = delivery_job
    seen = []
    with ThreadPoolExecutor(1) as pool:
        executor = DurableTaskExecutor(store=main.render_task_store, executor=pool)
        monkeypatch.setattr(main, "durable_render_executor", executor)
        # Real API, serialization and durable queue; no real user render.
        def render(job_id, kind, args):
            seen.append((job_id, kind, args))
        monkeypatch.setattr(main, "run_persisted_render_task", render)
        visible = main.public_job(job)
        selected = visible["outputVersions"][0]["outputs"][1]
        request = main.FinalizeOutputVersionRequest(specVersion=1, outputFilename="second.mp4", outputRevision=selected["outputRevision"])
        with ThreadPoolExecutor(2) as clients:
            results = list(clients.map(lambda _: main.finalize_preview_output_version(job["id"], "v001", request), range(2)))
        assert results[0]["operationId"] == results[1]["operationId"]
    assert len(seen) == 1
    assert seen[0][2][5][0]["id"] == "second"
    assert main.render_task_store.get(results[0]["operationId"])["status"] == "completed"


def test_ambiguous_foreign_and_stale_exports_are_rejected(delivery_job):
    version = delivery_job["outputVersions"][0]
    with pytest.raises(HTTPException, match="多个文件"):
        select_export_output(version, None, None)
    with pytest.raises(HTTPException, match="不属于"):
        select_export_output(version, "foreign.mp4", None)
    revision = output_revision(version, version["outputs"][1])
    version["outputs"][1]["segments"][0]["end"] += 1
    with pytest.raises(HTTPException, match="已更新"):
        select_export_output(version, "second.mp4", revision)


def test_queue_submission_failure_restores_workspace(delivery_job, monkeypatch):
    job = delivery_job
    version = job["outputVersions"][0]
    request = main.FinalizeOutputVersionRequest(specVersion=1, outputFilename="second.mp4", outputRevision=output_revision(version, version["outputs"][1]))
    def fail(*_args, **_kwargs):
        raise RuntimeError("executor stopped")
    monkeypatch.setattr(main, "submit_render_task", fail)
    with pytest.raises(HTTPException, match="未能进入队列"):
        main.finalize_preview_output_version(job["id"], version["id"], request)
    assert job["status"] == "awaiting_confirmation"
    assert main.job_store.get(job["id"])["status"] == "awaiting_confirmation"
    assert job["id"] not in main.cancel_events


def test_keep_formal_output_while_analysis_is_running(delivery_job):
    job = delivery_job
    version = job["outputVersions"][0]
    version["previewOnly"] = False
    output = version["outputs"][1]
    output["previewOnly"] = False
    job["status"] = "running"
    assert output_capabilities(job, version, output)["canKeep"]
    response = main.keep_job_output(job["id"], output["filename"], main.KeepOutputRequest(kept=True))
    assert response["job"]["status"] == "running"
    assert main.output_by_filename(job, output["filename"])["kept"]


def test_retention_of_older_version_does_not_use_current_version(delivery_job):
    job = delivery_job
    version = job["outputVersions"][0]
    version["previewOnly"] = False
    output = version["outputs"][0]
    output["previewOnly"] = False
    newer = {"id": "v002", "number": 2, "outputs": [{"filename": "newer.mp4"}]}
    job["outputVersions"].append(newer)
    job["currentOutputVersionId"] = newer["id"]
    job["outputs"] = newer["outputs"]
    main.keep_job_output(job["id"], output["filename"], main.KeepOutputRequest(kept=True))
    assert output["kept"]
    assert job["currentOutputVersionId"] == "v002"
    assert not newer["outputs"][0].get("kept")


def test_cancel_retention_does_not_delete_last_copy_after_source_disappears(delivery_job):
    job = delivery_job
    job["outputVersions"][0]["previewOnly"] = False
    output = job["outputs"][0]
    output["previewOnly"] = False
    main.keep_job_output(job["id"], output["filename"], main.KeepOutputRequest(kept=True))
    retained, metadata = main.kept_output_paths(job["id"], output["filename"])
    (Path(job["outputDirectory"]) / output["filename"]).unlink()
    with pytest.raises(HTTPException, match="最后可用副本") as error:
        main.delete_kept_output(job["id"], output["filename"], require_source=True)
    assert error.value.status_code == 409
    assert retained.is_file() and metadata.is_file() and output["kept"]
    assert main.delete_kept_output(job["id"], output["filename"], require_source=False)["deleted"]
    assert not retained.exists() and not output["kept"]


def test_retention_cannot_be_removed_during_an_inflight_copy(delivery_job):
    job = delivery_job
    job["outputVersions"][0]["previewOnly"] = False
    output = job["outputs"][0]
    output["previewOnly"] = False
    main.keep_job_output(job["id"], output["filename"], main.KeepOutputRequest(kept=True))
    job["libraryOperations"]["inflight"] = {"status": "running", "filename": output["filename"]}
    with pytest.raises(HTTPException, match="正在保留"):
        main.delete_kept_output(job["id"], output["filename"], require_source=True)
    assert main.kept_output_paths(job["id"], output["filename"])[0].is_file()


def test_duplicate_commit_keeps_all_outputs():
    first = {"id": "v001", "exportKey": "first"}
    second = {"id": "v002", "exportKey": "second"}
    job = {"outputVersions": [first]}
    job["outputVersions"] = merge_committed_version(job, second)
    assert merge_committed_version(job, {**second, "id": "v003"}) == [first, second]


def test_recovered_export_does_not_render_an_already_committed_version(delivery_job, monkeypatch):
    job = delivery_job
    job["outputVersions"].append({"id": "v002", "number": 2, "exportKey": "done", "outputs": [{"filename": "done.mp4"}]})
    def unexpected(*_args, **_kwargs):
        raise AssertionError("completed export must not render again")
    monkeypatch.setattr(main, "probe_video", unexpected)
    main.run_confirmed_render(job["id"], [], auto_meta={"exportKey": "done"})
    assert len(job["outputVersions"]) == 2
    assert job["status"] == "completed"


def test_failed_formal_export_remains_retryable_with_previous_outputs(delivery_job, monkeypatch):
    job = delivery_job
    version = job["outputVersions"][0]
    request = main.FinalizeOutputVersionRequest(specVersion=1, outputFilename="second.mp4", outputRevision=output_revision(version, version["outputs"][1]))
    export = prepare_formal_export(job["id"], version, request, "passed")
    def fail_probe(*_args, **_kwargs):
        raise RuntimeError("deliberate isolated media failure")
    monkeypatch.setattr(main, "probe_video", fail_probe)
    with ThreadPoolExecutor(1) as pool:
        executor = DurableTaskExecutor(store=main.render_task_store, executor=pool)
        task_id, future = executor.submit(job_id=job["id"], target=main.run_confirmed_render,
                                          args=(job["id"], *export.render_args), dedup_key=export.key)
        with pytest.raises(RuntimeError, match="isolated media failure"):
            future.result(timeout=5)
    assert main.render_task_store.get(task_id)["status"] == "failed"
    assert main.render_task_store.find_duplicate(job["id"], export.key) is None
    assert len(job["outputVersions"]) == 1


def test_sqlite_commit_survives_backup_failure_and_rejects_stale_writer(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    job = {"id": "job", "revision": 0, "detail": "new"}
    def failed_backup(*_):
        raise OSError("disk full")
    persist_job(store, job, tmp_path / "job.json", failed_backup)
    assert store.get("job")["detail"] == "new"
    assert job["revision"] == 1
    stale = {"id": "job", "revision": 0}
    with pytest.raises(ValueError, match="其他操作"):
        persist_job(store, stale, tmp_path / "job.json", failed_backup)
    assert stale == store.get("job")


def test_database_failure_does_not_publish_backup_or_revision(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "jobs.db")
    job = {"id": "job", "revision": 0}
    backups = []
    def fail(*_args, **_kwargs):
        raise OSError("database unavailable")
    monkeypatch.setattr(store, "save", fail)
    with pytest.raises(OSError):
        persist_job(store, job, tmp_path / "job.json", lambda *_args: backups.append(True))
    assert backups == [] and job["revision"] == 0


def test_load_record_prefers_sqlite_over_newer_json(delivery_job):
    job = delivery_job
    old = copy.deepcopy(job)
    old.update({"detail": "stale JSON", "updatedAt": "9999-01-01", "revision": 9999})
    main.job_path(job["id"]).write_text(json.dumps(old))
    assert main._load_job_record(job["id"]).get("detail") != "stale JSON"


@pytest.mark.parametrize("status,stage,agent,expected", [
    ("awaiting_agent_plan", "agent_planning", {}, 1),
    ("completed", "agent_handed_off", {}, 2),
    ("awaiting_agent_plan", "agent_preview_ready", {"status": "preview_ready"}, 3),
])
def test_projection_owns_journey_and_attention(status, stage, agent, expected):
    job = {"status": status, "stage": stage, "agent": agent, "agentHandoffJobId": "next"}
    presentation = ui_presentation_snapshot(job, workflow={}, execution={}, output_count=0)
    assert presentation["journeyStage"] == expected
    assert "attentionItems" in presentation and "availableActions" in presentation


def test_active_export_takes_precedence_over_old_agent_preview():
    job = {"status": "running", "stage": "rendering", "agent": {"status": "preview_ready"}}
    projection = ui_presentation_snapshot(job, workflow={}, execution={"active": True, "operation": "render"}, output_count=1)
    assert projection["key"] == "export_running"
    assert projection["journeyStage"] == 4


def test_full_export_spec_preserves_text_canvas_audio_and_hash(delivery_job):
    version = delivery_job["outputVersions"][0]
    output = version["outputs"][1]
    output.update({"textLayers": [{"id": "title", "text": "hello", "start": 0, "end": 1}],
                   "reframe": {"aspect": "9:16", "fit": "crop", "focusX": .25}})
    output["segments"][0].update({"playbackRate": 1.25, "muted": True, "audioGainDb": -6})
    revision = output_revision(version, output)
    request = main.FinalizeOutputVersionRequest(specVersion=1, outputFilename=output["filename"], outputRevision=revision)
    export = prepare_formal_export(delivery_job["id"], version, request, "passed")
    spec = validate_spec(export.render_args[-1])
    assert spec["reframe"]["focusX"] == .25
    assert spec["textLayers"][0]["text"] == "hello"
    assert spec["segments"][0]["muted"] is True
    assert export.render_args[-3] == spec["textLayers"]
    assert export.render_args[-2] == spec["reframe"]
    output["textLayers"][0]["text"] = "changed"
    assert output_revision(version, output) != revision
    assert spec["textLayers"][0]["text"] == "hello"


def test_subtitles_are_frozen_and_real_timeline_changes_rejected():
    segments = [{"start": 0, "end": 4}, {"start": 8, "end": 10}]
    draft = {"id": "draft", "revision": 2, "status": "confirmed", "sourceSubtitleAcknowledged": True,
             "cues": [{"text": "original", "start": 0, "end": 1}],
             "outputFingerprints": output_fingerprints([{"segments": segments}])}
    spec = freeze_spec(segments=segments, subtitle_mode="burn", subtitle_draft=draft)
    draft["cues"][0]["text"] = "late edit"
    assert spec["subtitleDraft"]["cues"][0]["text"] == "original"
    cosmetic = copy.deepcopy(segments)
    cosmetic[0].update({"title": "cosmetic", "playbackRate": 1, "transitionIn": {"type": "cut", "duration": 0}})
    freeze_spec(segments=cosmetic, subtitle_mode="burn", subtitle_draft=draft)
    for changed in [[segments[1], segments[0]], [{"start": 0, "end": 3}, segments[1]],
                    [{**segments[0], "playbackRate": 2}, segments[1]]]:
        with pytest.raises(HTTPException, match="重新校对"):
            freeze_spec(segments=changed, subtitle_mode="burn", subtitle_draft=draft)


def test_unreviewed_subtitle_freeze_returns_actionable_error():
    segments = [{"start": 0, "end": 4}]
    draft = {
        "id": "draft",
        "revision": 1,
        "status": "draft",
        "sourceSubtitleAcknowledged": False,
        "cues": [{"text": "草稿", "start": 0, "end": 1}],
        "outputFingerprints": output_fingerprints([{"segments": segments}]),
    }

    with pytest.raises(HTTPException) as error:
        freeze_spec(segments=segments, subtitle_mode="burn", subtitle_draft=draft)

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "subtitle_review_required"
    assert error.value.detail["recoveryAction"] == "complete_subtitle_review"


def test_legacy_missing_overlay_spec_requires_confirmation(delivery_job):
    version = delivery_job["outputVersions"][0]
    output = version["outputs"][0]
    with pytest.raises(HTTPException, match="export_confirmation_required"):
        prepare_formal_export(delivery_job["id"], version, main.FinalizeOutputVersionRequest(outputFilename=output["filename"]), "passed")
    output["overlayVerification"] = {"textLayerCount": 1}
    with pytest.raises(HTTPException, match="旧样片"):
        output_spec(output, version, subtitle_mode="none", subtitle_style="clean")


def test_live_workspace_rolls_back_when_database_rejects_save(delivery_job, monkeypatch):
    original = copy.deepcopy(delivery_job)
    def fail(*args, **kwargs):
        raise OSError("database unavailable")
    monkeypatch.setattr(main.job_store, "save", fail)
    with pytest.raises(OSError):
        main.update_job(delivery_job["id"], status="failed", filename="wrong.mp4")
    assert delivery_job == original
    monkeypatch.setattr(main.job_store, "get", fail)
    delivery_job["filename"] = "database fully unavailable"
    with pytest.raises(OSError):
        main.save_job(delivery_job)
    assert delivery_job == original
    delivery_job["filename"] = "legacy in-place mutation"
    with pytest.raises(OSError):
        main.save_job(delivery_job)
    assert delivery_job == original


def test_copy_does_not_hold_global_lock_and_pins_deletion(delivery_job, monkeypatch):
    job = delivery_job
    version = job["outputVersions"][0]
    version["previewOnly"] = False
    output = version["outputs"][0]
    output["previewOnly"] = False
    job["status"] = "completed"
    entered, release = threading.Event(), threading.Event()
    original_copy = main.save_output_to_kept_library
    def slow_copy(*args):
        entered.set()
        assert release.wait(5)
        return original_copy(*args)
    monkeypatch.setattr(main, "save_output_to_kept_library", slow_copy)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(main.keep_job_output, job["id"], output["filename"], main.KeepOutputRequest(kept=True))
        try:
            assert entered.wait(2)
            assert main.jobs_lock.acquire(timeout=.5)
            main.jobs_lock.release()
            with pytest.raises(HTTPException, match="正在复制"):
                main.delete_job_output_version(job["id"], version["id"])
        finally:
            release.set()
        future.result(timeout=3)


def test_completed_operation_supersedes_only_its_own_agent_plan():
    job = {"status": "completed", "agent": {"status": "preview_ready", "planId": "plan-A"},
           "outputVersions": [{"id": "formal", "outputs": [{"filename": "formal.mp4"}]}],
           "renderOperations": {"op": {"status": "completed", "agentPlanId": "plan-A", "resultVersionIds": ["formal"]}}}
    assert ui_presentation_snapshot(job, workflow={}, execution={}, output_count=1)["key"] == "exported"
    job["agent"]["planId"] = "plan-B"
    assert ui_presentation_snapshot(job, workflow={}, execution={}, output_count=1)["key"] == "preview_review"


def test_plugin_timeout_queries_operation_without_repeating_effect(monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append(url)
        if url.endswith("/execute"):
            raise httpx.ReadTimeout("effect may have completed")
        return httpx.Response(200, json={"status": "succeeded", "result": {"ok": True}}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    result = AgentServiceClient("http://local", token="test").execute_plugin_tool({"operationId": "stable"})
    assert result == {"ok": True}
    assert len([call for call in calls if call.endswith("/execute")]) == 1
    assert calls[-1].endswith("/operations/get")


def test_post_commit_failure_never_deletes_committed_media(delivery_job, monkeypatch):
    job = delivery_job
    version = job["outputVersions"][0]
    output = version["outputs"][0]
    request = main.FinalizeOutputVersionRequest(specVersion=1, outputFilename=output["filename"], outputRevision=output_revision(version, output))
    export = prepare_formal_export(job["id"], version, request, "passed")
    info = SimpleNamespace(duration=2.0, width=320, height=180, has_audio=False)
    monkeypatch.setattr(main, "probe_video", lambda *args: info)
    monkeypatch.setattr(main, "validate_rendered_clip", lambda *args, **kwargs: info)
    def render(source, path, **kwargs):
        path.write_bytes(b"validated-new-media")
        return 2.0
    monkeypatch.setattr(main, "render_composition", render)
    def fail_manifest(*args):
        raise OSError("injected post-commit failure")
    monkeypatch.setattr(main, "_sync_output_manifest", fail_manifest)
    main.run_confirmed_render(job["id"], *export.render_args)
    persisted = main.job_store.get(job["id"])
    assert len(persisted["outputVersions"]) == 2
    current = persisted["outputVersions"][-1]
    assert current["postCommitPending"] is True
    assert persisted["currentOutputVersionId"] == current["id"]
    assert (Path(job["outputDirectory"]) / current["outputs"][0]["filename"]).read_bytes() == b"validated-new-media"
    monkeypatch.setattr(main, "_sync_output_manifest", lambda *args: None)
    monkeypatch.setattr(main.output_preview_executor, "submit", lambda *args: None)
    main.repair_committed_output_effects(job["id"])
    main.repair_committed_output_effects(job["id"])
    assert not main.job_store.get(job["id"])["outputVersions"][-1]["postCommitPending"]
    assert len([item for item in job["messages"] if item.get("outputVersionId") == current["id"]]) == 1


def test_failed_render_does_not_restore_obsolete_current_version(delivery_job, monkeypatch):
    job = delivery_job
    version = job["outputVersions"][0]
    output = version["outputs"][0]
    request = main.FinalizeOutputVersionRequest(specVersion=1, outputFilename=output["filename"], outputRevision=output_revision(version, output))
    export = prepare_formal_export(job["id"], version, request, "passed")
    newer = {"id": "parallel-success", "number": 9, "outputs": [{"filename": "parallel.mp4"}]}
    def fail_after_other_commit(*args):
        main.update_job(job["id"], _append_output_version=newer, outputs=newer["outputs"], currentOutputVersionId=newer["id"])
        raise RuntimeError("another operation failed")
    monkeypatch.setattr(main, "probe_video", fail_after_other_commit)
    with pytest.raises(RuntimeError):
        main.run_confirmed_render(job["id"], *export.render_args)
    assert job["currentOutputVersionId"] == newer["id"]
    assert job["outputs"] == newer["outputs"]
    assert main.job_store.get(job["id"])["currentOutputVersionId"] == newer["id"]


def test_real_synthetic_render_uses_frozen_spec(delivery_job, monkeypatch):
    job = delivery_job
    subprocess.run([main.settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=160x90:rate=12:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-y", job["sourcePath"]], check=True, capture_output=True, timeout=20)
    version = job["outputVersions"][0]
    output = version["outputs"][0]
    spec = freeze_spec(segments=output["segments"], text_layers=[{"id": "t", "text": "Frozen", "start": 0, "end": 1}],
                       reframe={"aspect": "9:16", "fit": "pad", "focusX": .5, "focusY": .5})
    output["renderSpec"] = spec
    request = main.FinalizeOutputVersionRequest(specVersion=1, outputFilename=output["filename"], outputRevision=output_revision(version, output))
    export = prepare_formal_export(job["id"], version, request, "passed")
    monkeypatch.setattr(main.output_preview_executor, "submit", lambda *args: None)
    main.run_confirmed_render(job["id"], *export.render_args)
    rendered = job["outputVersions"][-1]["outputs"][0]
    assert not rendered["previewOnly"]
    assert rendered["overlayVerification"]["textLayerCount"] == 1
    assert rendered["renderSpec"]["textLayers"] == spec["textLayers"]
    info = main.probe_video(Path(job["outputDirectory"]) / rendered["filename"], main.settings.ffprobe)
    assert abs(info.duration - 2.0) < .2
    assert (info.width, info.height) == (1080, 1920)
    assert rendered["renderSpec"]["hash"] == export.render_args[-1]["hash"]


def test_single_worker_lock_is_exclusive(tmp_path):
    lock = WorkerLock(tmp_path / "worker.lock")
    try:
        with pytest.raises(RuntimeError, match="单 worker"):
            WorkerLock(tmp_path / "worker.lock")
    finally:
        lock.close()
    WorkerLock(tmp_path / "worker.lock").close()


def test_agent_client_sends_independent_credential(monkeypatch):
    seen = []
    def post(url, **kwargs):
        seen.append(kwargs["headers"])
        return httpx.Response(200, json={"status": "ok"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    client = AgentServiceClient("http://agent", token="a" * 64)
    client._post("/v1/plan", {"requestId": "request"})
    assert seen == [{"Authorization": "Bearer " + "a" * 64, "Idempotency-Key": "request"}]


def test_credentials_are_atomic_and_plugin_hash_detects_changes(tmp_path, monkeypatch):
    monkeypatch.delenv("CLIPTALK_AGENT_SERVICE_TOKEN", raising=False)
    path = tmp_path / "service-token"
    with ThreadPoolExecutor(8) as pool:
        tokens = list(pool.map(lambda _: service_token(path), range(16)))
    assert len(set(tokens)) == 1 and len(tokens[0]) == 64
    assert path.stat().st_mode & 0o777 == 0o600
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "index.mjs").write_text("export default {}")
    original = plugin_tree_hash(plugin)
    (plugin / "index.mjs").write_text("export default {changed:true}")
    assert plugin_tree_hash(plugin) != original
    (plugin / "outside").symlink_to(path)
    with pytest.raises(ValueError, match="符号链接"):
        plugin_tree_hash(plugin)
