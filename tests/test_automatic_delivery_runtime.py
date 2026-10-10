import copy
import threading
import shutil
import subprocess
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.automatic_delivery_runtime import prepare_delivery, run_delivery


@pytest.fixture
def runtime(tmp_path):
    session = {"id": "edit", "revision": 1, "previewStatus": "ready", "previewFingerprint": "fp"}
    plan = {"id": "plan_current", "planHash": "hash", "status": "running", "executionMode": "automatic_delivery",
            "approval": {"allowedTools": ["deliver_current_plan"]}, "steps": [
                {"status": "completed", "result": {"artifact": {"previews": [{"sessionId": "edit"}]}}}], "brief": {}}
    job = {"id": "job", "agent": {"planId": plan["id"]}, "outputDirectory": str(tmp_path),
           "editSessions": [session], "outputVersions": [], "currentCoverVersionId": "cover",
           "coverVersions": [{"id": "cover"}]}
    service = SimpleNamespace(
        jobs={"job": job}, jobs_lock=threading.RLock(), cancel_events={},
        agent_platform=SimpleNamespace(store=SimpleNamespace(get=lambda *args: copy.deepcopy(plan))),
        find_edit_session=lambda job, sid: next(s for s in job["editSessions"] if s["id"] == sid),
        _edit_session_preview_fingerprint=lambda *_: "fp", edit_session_preflight=lambda *_: {"ready": True},
        build_edit_session_render_plan=lambda *_: ([{"start": 1, "end": 4}], []),
        freeze_spec=lambda **kwargs: kwargs, _effective_edit_session_reframe=lambda *_: None,
        current_cover_version=lambda job: job["coverVersions"][0], save_job=Mock(),
        submit_render_task=Mock(return_value=Future()), run_automatic_delivery=Mock(),
        next_output_version=lambda j: (f"v{len(j['outputVersions']) + 1}", len(j["outputVersions"]) + 1),
        now_iso=lambda: "2026-09-24T00:00:00Z", _sync_output_manifest=Mock(),
        bind_cover_to_output_version=Mock(), cover_version_path=lambda *_: tmp_path / "cover.jpg",
        find_output_version=lambda job, vid: next(v for v in job["outputVersions"] if v["id"] == vid),
        settings=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe"),
    )
    def render(job_id, session_id, revision, spec):
        assert spec["segments"] == [{"start": 1, "end": 4}]
        (tmp_path / "master.mp4").write_bytes(b"source-rendered-master")
        output = {"filename": "master.mp4", "previewOnly": False}
        job["outputVersions"].append({"id": "base", "outputs": [output], "previewOnly": False})
        session.update({"status": "rendered", "renderedVersionId": "base"})
    service.run_edit_session_render = Mock(side_effect=render)
    service.output_download_context = Mock(return_value=None)
    return service, job, session, plan


def prepare(runtime):
    service, job, session, plan = runtime
    prepare_delivery(service, {"jobId": "job", "activePlanId": plan["id"]}, plan)
    return service.submit_render_task.call_args.args[2]


def test_delivery_uses_frozen_source_spec_and_is_idempotent(runtime):
    service, job, _, _ = runtime
    request = prepare(runtime)
    result = run_delivery(service, "job", request)
    filename = result["artifact"]["output"]["filename"]
    assert filename.endswith("-final.mp4")
    assert (Path(job["outputDirectory"]) / filename).read_bytes() == b"source-rendered-master"
    assert result["artifact"]["output"]["previewOnly"] is False
    assert service.run_edit_session_render.call_count == 1
    run_delivery(service, "job", request)
    assert service.run_edit_session_render.call_count == 1
    assert job["automaticDelivery"]["status"] == "checking"


def test_direct_delivery_requires_exact_preflight_revision_and_fingerprint(runtime):
    _, _, session, plan = runtime
    session.update(previewStatus="idle", previewFingerprint=None)
    plan["steps"] = [{"tool": "prepare_delivery_timeline", "status": "completed", "result": {"artifact": {
        "sessions": [{"sessionId": "edit", "revision": 1, "fingerprint": "fp"}]}}}]
    assert prepare(runtime)["sessions"][0]["id"] == "edit"
    session["revision"] = 2
    with pytest.raises(RuntimeError, match="已核对时间线发生变化"):
        prepare(runtime)


def test_no_timeline_never_copies_a_review_proxy(runtime):
    service, _, _, plan = runtime
    plan["steps"] = []
    with pytest.raises(RuntimeError, match="未把审核样片复制"):
        prepare(runtime)
    service.submit_render_task.assert_not_called()


@pytest.mark.parametrize("profile", ["audio-polish", "cover-intro"])
def test_effect_followup_keeps_selected_formal_edits_instead_of_ancestor_timeline(runtime, profile):
    service, _, session, plan = runtime
    plan.update(profile=profile, steps=[], inputContext={"outputFilename": "with-intro.mp4", "outputVersionId": "v-final",
                                                              "editSessionId": "edit", "editSessionRevision": 1})
    service.output_download_context.return_value = ({"filename": "with-intro.mp4", "previewOnly": False}, {"id": "v-final"}, None)
    session["revision"] = 2  # A changed ancestor cannot invalidate a selected immutable final.
    request = prepare(runtime)
    assert request["sessions"] == []
    assert request["sourceVersionId"] == "v-final"


def test_standalone_motion_does_not_bind_unrelated_cover(runtime):
    _, _, _, plan = runtime
    plan.update(profile="local-motion", steps=[], brief={"graphicsText": "新品发布"})
    request = prepare(runtime)
    assert not request["coverVersionId"]


def test_repeated_delivery_does_not_grow_the_filename(runtime):
    service, job, _, plan = runtime
    filename = "previous-edit-" + "x" * 210 + ".mp4"
    (Path(job["outputDirectory"]) / filename).write_bytes(b"formal")
    plan.update(steps=[], inputContext={"outputFilename": filename, "outputVersionId": "v-formal"})
    service.output_download_context.return_value = ({"filename": filename, "previewOnly": False}, {"id": "v-formal"}, None)
    output = run_delivery(service, "job", prepare(runtime))["artifact"]["output"]
    assert len(output["filename"].encode()) < 100
    assert (Path(job["outputDirectory"]) / output["filename"]).read_bytes() == b"formal"


@pytest.mark.parametrize("change", ["revision", "cancel", "cover", "plan"])
def test_stale_or_cancelled_delivery_cannot_publish(runtime, change):
    service, job, session, plan = runtime
    request = prepare(runtime)
    if change == "revision":
        session["revision"] = 2
    elif change == "cancel":
        service.cancel_events["job"] = threading.Event()
        service.cancel_events["job"].set()
    elif change == "cover":
        job["currentCoverVersionId"] = "different"
    else:
        job["agent"]["planId"] = "new-plan"
    with pytest.raises(RuntimeError):
        run_delivery(service, "job", request)
    assert job["outputVersions"] == []


def test_only_explicit_intro_is_composed_and_uses_frozen_duration(runtime):
    service, job, _, plan = runtime
    plan["brief"] = {"coverRequested": True, "coverIntroRequested": True, "coverIntroDurationSeconds": 2}
    (Path(job["outputDirectory"]) / "cover.jpg").write_bytes(b"cover")
    def intro(source, cover, target, **kwargs):
        assert source.name == "master.mp4"
        assert kwargs["duration"] == 2
        target.write_bytes(b"master-with-intro")
        return {"duration": 5, "introDuration": 2, "width": 320, "height": 180, "hasAudio": False}
    service.render_cover_intro = Mock(side_effect=intro)
    result = run_delivery(service, "job", prepare(runtime))
    assert result["artifact"]["output"]["coverIntro"]["duration"] == 2
    assert result["artifact"]["output"]["coverIntro"]["coverVersionId"] == "cover"


def test_cancel_during_media_render_does_not_publish_final(runtime):
    service, job, _, _ = runtime
    request = prepare(runtime)
    service.cancel_events["job"] = threading.Event()
    render = service.run_edit_session_render.side_effect
    def cancel_after_render(*args):
        render(*args)
        service.cancel_events["job"].set()
    service.run_edit_session_render.side_effect = cancel_after_render
    with pytest.raises(RuntimeError, match="已停止"):
        run_delivery(service, "job", request)
    assert not any(v.get("automaticPlanId") for v in job["outputVersions"])


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")
def test_real_media_delivery_preserves_audio_and_prepends_requested_cover(runtime):
    from PIL import Image
    from app.cover_delivery import render_cover_intro
    from app.media import probe_video
    service, job, session, plan = runtime
    directory = Path(job["outputDirectory"])
    ffmpeg = "/usr/bin/ffmpeg" if Path("/usr/bin/ffmpeg").is_file() else shutil.which("ffmpeg")
    ffprobe = "/usr/bin/ffprobe" if Path("/usr/bin/ffprobe").is_file() else shutil.which("ffprobe")
    service.settings.ffmpeg = ffmpeg
    service.settings.ffprobe = ffprobe
    source = directory / "source.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "5",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(source)], check=True, timeout=30)
    Image.new("RGB", (320, 180), "green").save(directory / "cover.jpg")
    def render(job_id, session_id, revision, spec):
        segment = spec["segments"][0]
        subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", str(segment["start"]), "-i", str(source),
                        "-t", str(segment["end"] - segment["start"]), "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac", str(directory / "master.mp4")], check=True, timeout=30)
        job["outputVersions"].append({"id": "base", "outputs": [{"filename": "master.mp4", "previewOnly": False,
            "subtitleCues": [{"start": .5, "end": 1.5, "text": "对白"}]}]})
        session.update({"status": "rendered", "renderedVersionId": "base"})
    service.run_edit_session_render = render
    service.render_cover_intro = render_cover_intro
    plan["brief"] = {"coverRequested": True, "coverIntroRequested": True, "coverIntroDurationSeconds": 1}
    result = run_delivery(service, "job", prepare(runtime))
    output = result["artifact"]["output"]
    path = directory / output["filename"]
    info = probe_video(path, ffprobe)
    assert 3.9 <= info.duration <= 4.2
    assert (info.width, info.height) == (320, 180)
    assert info.has_audio
    assert output["subtitleCues"] == [{"start": 1.5, "end": 2.5, "text": "对白"}]
    subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"], check=True, timeout=30)
    # Follow-up changes the cover on the selected formal file, even when the
    # ancestor session has since changed. It must replace, not stack intros.
    first_version = copy.deepcopy(job["outputVersions"][-1])
    first_output = copy.deepcopy(output)
    first_output["audioPolish"] = {"gainDb": -3}
    service.output_download_context.return_value = (first_output, first_version, path)
    plan.update(id="plan_replacement", profile="cover-intro", steps=[], inputContext={
        "outputFilename": output["filename"], "outputVersionId": first_version["id"],
        "editSessionId": session["id"], "editSessionRevision": 1})
    session["revision"] = 2
    job["agent"]["planId"] = plan["id"]
    plan["brief"]["coverIntroDurationSeconds"] = .5
    Image.new("RGB", (320, 180), "red").save(directory / "cover.jpg")
    replaced = run_delivery(service, "job", prepare(runtime))["artifact"]["output"]
    assert replaced["duration"] == pytest.approx(3.5, abs=.2)
    assert replaced["audioPolish"] == {"gainDb": -3}
    assert replaced["deliveryTimeMap"]["bodyOffsetSeconds"] == .5
    assert replaced["subtitleCues"] == [{"start": 1, "end": 2, "text": "对白"}]
    assert replaced["deliveryOperations"][-1]["coverIntro"] == "replace"
    assert path.is_file()  # Previous version remains available.
    from app.cover_delivery import verify_cover_intro_frame
    actual_check = verify_cover_intro_frame(directory / replaced["filename"], directory / "cover.jpg", ffmpeg=ffmpeg, ffprobe=ffprobe)
    assert actual_check["status"] == "supported"
    # The old file starts with green, not the newly approved red cover.
    wrong_check = verify_cover_intro_frame(path, directory / "cover.jpg", ffmpeg=ffmpeg, ffprobe=ffprobe)
    assert wrong_check["status"] == "mismatch"


@pytest.mark.parametrize("profile,intro", [("audio-polish", False), ("local-motion", False), ("local-motion", True)])
def test_effects_are_frozen_and_published_through_one_delivery(runtime, monkeypatch, profile, intro):
    import app.automatic_delivery_runtime as module
    service, job, session, plan = runtime
    plan.update(profile=profile, goal="新品发布", brief={"motionIntroRequested": intro, "audioPolishRequested": profile == "audio-polish"})
    if profile == "local-motion" and not intro:
        plan["steps"] = []
    def effect(runtime, source, target, effects, work, guard):
        guard()
        assert (source is None) == (profile == "local-motion" and not intro)
        target.write_bytes(b"full-quality-effect")
        return {"filename": target.name, "duration": 4, "width": 320, "height": 180, "hasAudio": bool(source)}
    monkeypatch.setattr(module, "apply_effects", effect)
    request = prepare(runtime)
    original_effects = copy.deepcopy(request["effects"])
    plan["brief"]["targetSeconds"] = 7
    result = run_delivery(service, "job", request)
    assert request["effects"] == original_effects
    assert result["artifact"]["output"]["previewOnly"] is False
    assert (Path(job["outputDirectory"]) / result["artifact"]["output"]["filename"]).read_bytes() == b"full-quality-effect"
    run_delivery(service, "job", request)
    assert len([v for v in job["outputVersions"] if v.get("automaticPlanId")]) == 1
