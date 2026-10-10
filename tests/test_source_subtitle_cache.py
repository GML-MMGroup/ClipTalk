import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.source_subtitle_cache import SubtitleFrameCache, frame_cache_key
from app.source_subtitle_check import check_source_subtitles


@pytest.fixture
def scenario(tmp_path):
    client = SimpleNamespace(model="vision-v1", url="https://example.invalid/v1/chat/completions",
                             api_key="secret-must-not-be-stored", thinking_type="disabled", response_format="json",
                             analyze_image=Mock(return_value={"frames": [{"dialogueSubtitle": "absent", "confidence": .99}]}))
    def extract(source, root, times, **kwargs):
        root.mkdir(parents=True, exist_ok=True)
        frames = []
        for index, timestamp in enumerate(times):
            path = root / f"{index}.jpg"
            path.write_bytes(f"test-frame-at-{timestamp}".encode())
            frames.append(SimpleNamespace(path=path))
        return frames
    runtime = SimpleNamespace(
        build_edit_session_render_plan=lambda *_: ([{"start": 0, "end": 4}], []),
        extract_frames_at_times=extract, cancel_events={},
        settings=SimpleNamespace(ffmpeg="ffmpeg", data_root=tmp_path / "data"),
        create_vision_client_for_job=lambda _: client)
    job = {"id": "first", "sourceHash": "video-content-hash", "sourcePath": "source.mp4", "workDirectory": str(tmp_path / "first")}
    return runtime, job, client


def run(scenario, draft="draft"):
    runtime, job, _ = scenario
    return check_source_subtitles(runtime, job, {}, {"id": draft, "outputFingerprints": [draft]})


def test_reuse_across_jobs_preserves_current_output_binding(scenario, tmp_path):
    runtime, job, client = scenario
    first = run(scenario)
    job.update(id="second", workDirectory=str(tmp_path / "second"))
    second = run(scenario, "new-draft")
    assert first["status"] == second["status"] == "clear"
    assert first["modelCallCount"] == 3 and second["modelCallCount"] == 0
    assert second["cacheHitCount"] == 3 and client.analyze_image.call_count == 3
    assert second["outputFingerprints"] == ["new-draft"]
    database = SubtitleFrameCache(runtime.settings.data_root).path.read_bytes()
    for secret in (b"secret-must-not-be-stored", client.url.encode(), client.model.encode()):
        assert secret not in database


@pytest.mark.parametrize("change", ["model", "endpoint", "thinking", "format", "source", "rules", "frame", "time"])
def test_changed_evidence_invalidates_cache(scenario, monkeypatch, change):
    runtime, job, client = scenario
    assert run(scenario)["modelCallCount"] == 3
    if change in {"model", "endpoint", "thinking", "format"}:
        setattr(client, {"endpoint": "url", "thinking": "thinking_type", "format": "response_format"}.get(change, change), "changed")
    elif change == "source":
        job["sourceHash"] = "different-video"
    elif change == "rules":
        monkeypatch.setattr("app.source_subtitle_check.SUBTITLE_CHECK_RULES", "new-rules")
    elif change == "time":
        runtime.build_edit_session_render_plan = lambda *_: ([{"start": 1, "end": 5}], [])
    else:
        extract = runtime.extract_frames_at_times
        def changed(*args, **kwargs):
            frames = extract(*args, **kwargs)
            for frame in frames:
                frame.path.write_bytes(b"different-pixels")
            return frames
        runtime.extract_frames_at_times = changed
    assert run(scenario, "next")["modelCallCount"] == 3


def test_unknown_is_rechecked_and_cannot_become_clear_from_cache(scenario):
    client = scenario[2]
    client.analyze_image.return_value = {"frames": [{"dialogueSubtitle": "absent", "confidence": .5}]}
    assert run(scenario)["status"] == "unknown"
    assert run(scenario, "second")["modelCallCount"] == 1
    assert client.analyze_image.call_count == 2


def test_present_is_reusable_but_does_not_mark_remaining_frames_clear(scenario):
    scenario[2].analyze_image.return_value = {"frames": [{"dialogueSubtitle": "present", "confidence": .99}]}
    assert run(scenario)["status"] == "present"
    second = run(scenario, "second")
    assert second["status"] == "present" and second["sampleCount"] == 1
    assert second["modelCallCount"] == 0
    assert second["checkedSegmentCount"] == 1 and not second["coverageComplete"]


def test_cached_partial_scan_stays_unknown(scenario):
    runtime = scenario[0]
    runtime.build_edit_session_render_plan = lambda *_: ([{"start": i * 5, "end": i * 5 + 4} for i in range(49)], [])
    assert run(scenario)["status"] == "unknown"
    second = run(scenario, "second")
    assert second["status"] == "unknown" and not second["coverageComplete"]
    assert second["cacheHitCount"] == 48 and second["modelCallCount"] == 0


def test_cancelled_model_response_is_not_published_or_cached(scenario):
    runtime, job, client = scenario
    event = runtime.cancel_events[job["id"]] = threading.Event()
    def cancel(*args, **kwargs):
        event.set()
        return {"frames": [{"dialogueSubtitle": "absent", "confidence": 1}]}
    client.analyze_image.side_effect = cancel
    assert run(scenario)["status"] == "unknown"
    assert not SubtitleFrameCache(runtime.settings.data_root).path.exists()


def test_corrupt_cache_falls_back_to_live_check(scenario):
    cache = SubtitleFrameCache(scenario[0].settings.data_root)
    cache.path.parent.mkdir(parents=True)
    cache.path.write_bytes(b"not-a-database")
    assert run(scenario)["status"] == "clear"
    assert run(scenario, "second")["modelCallCount"] == 3


def test_cache_is_bounded_expiring_and_concurrent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.source_subtitle_cache.MAX_CACHE_ROWS", 4)
    monkeypatch.setattr("app.source_subtitle_cache.time.time", lambda: 1000)
    cache = SubtitleFrameCache(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: cache.put(str(index), "clear"), range(12)))
    with sqlite3.connect(cache.path) as connection:
        assert connection.execute("SELECT count(*) FROM frames").fetchone()[0] == 4
    cache.put("last", "present")
    assert cache.get("last") == "present"
    monkeypatch.setattr("app.source_subtitle_cache.time.time", lambda: 1000 + 8 * 86400)
    assert cache.get("last") is None


def test_missing_identity_disables_reuse(scenario, tmp_path):
    _, job, client = scenario
    job.pop("sourceHash")
    assert run(scenario)["modelCallCount"] == run(scenario, "second")["modelCallCount"] == 3
    assert frame_cache_key("source", SimpleNamespace(), tmp_path / "missing", 0, "rules") is None


@pytest.mark.parametrize("interruption", ["cancel", "revision"])
def test_old_subtitle_result_cannot_attach_after_interruption(monkeypatch, tmp_path, interruption):
    from app import main
    session = {"id": "edit", "revision": 1, "clips": [{"id": "c", "sourceStart": 0, "sourceEnd": 2}]}
    job = {"id": "subtitle-interruption", "editSessions": [session], "workDirectory": str(tmp_path),
           "agent": {"executionMode": "automatic_delivery"}}
    monkeypatch.setitem(main.jobs, job["id"], job)
    event = threading.Event()
    monkeypatch.setitem(main.cancel_events, job["id"], event)
    monkeypatch.setattr(main, "_subtitle_transcription_complete", lambda *_: True)
    monkeypatch.setattr(main, "create_subtitle_draft", lambda *_: {"draft": {"id": "draft", "cues": []}})
    monkeypatch.setattr(main, "suggest_subtitle_corrections", lambda *_: {})
    def check(runtime, job_snapshot, session_snapshot, draft):
        if interruption == "cancel":
            event.set()
        else:
            session["revision"] = 2
        assert session_snapshot["revision"] == 1
        return {"status": "clear"}
    monkeypatch.setattr("app.source_subtitle_check.check_source_subtitles", check)
    save_draft, save_job = Mock(), Mock()
    monkeypatch.setattr(main, "save_subtitle_draft_file", save_draft)
    monkeypatch.setattr(main, "save_job", save_job)
    with pytest.raises(RuntimeError, match="已停止|时间线已变化"):
        main.run_agent_auto_subtitle_review(job["id"], session["id"])
    save_draft.assert_not_called()
    save_job.assert_not_called()
    assert not session.get("subtitleEnabled")
