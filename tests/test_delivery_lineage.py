import copy
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from app.delivery_lineage import derive_lineage, intro_offset, mapped_session, replace_cover_lineage, remap_subtitle_cues


@pytest.fixture
def source():
    return {
        "filename": "master.mp4", "versionId": "v1", "duration": 12, "previewOnly": False,
        "sourceEditSessionId": "edit", "segments": [{"id": "c", "start": 5, "end": 15}],
        "deliveryTimeMap": {"schemaVersion": 1, "bodyOffsetSeconds": 2},
        "deliveryTimeline": {"id": "edit", "revision": 1, "schedule": [{"clipId": "c", "outputStart": 0, "outputEnd": 10}]},
        "deliveryOperations": [{"operation": "initial"}],
        "coverIntro": {"enabled": True, "start": 0, "duration": 2},
        "subtitleCues": [{"start": 3, "end": 5, "text": "对白"}], "subtitleMode": "burn",
        "audioPolish": {"gainDb": -3}, "qualityReport": {"passed": True}, "qualityStatus": "passed",
    }


def test_derived_chain_keeps_frozen_evidence_and_accumulates_offsets(source):
    original = copy.deepcopy(source)
    motion = {**source, **derive_lineage(source, "compose_motion_intro", prepend_seconds=1.5), "filename": "motion.mp4"}
    reframe = {**motion, **derive_lineage(motion, "render_social_preview"), "filename": "vertical.mp4"}
    audio = {**reframe, **derive_lineage(reframe, "polish_audio_mix"), "filename": "audio.mp4"}
    export = {**audio, **derive_lineage(audio, "export_delivery_master")}
    assert intro_offset(export) == 3.5
    assert export["coverIntro"]["start"] == 1.5
    assert export["subtitleCues"] == [{"start": 4.5, "end": 6.5, "text": "对白"}]
    assert mapped_session({}, export)["schedule"][0]["outputStart"] == 3.5
    assert [op["operation"] for op in export["deliveryOperations"]] == [
        "initial", "compose_motion_intro", "render_social_preview", "polish_audio_mix", "export_delivery_master"]
    assert export["qualityStatus"] == "pending" and not export["qualityReport"]
    export["deliveryTimeline"]["revision"] = 10
    assert source == original


def test_legacy_offset_migrates_without_changing_timeline(source):
    source.pop("deliveryTimeMap")
    source["motionIntro"] = {"enabled": True, "introDuration": 1}
    derived = derive_lineage(source, "render_social_preview")
    assert intro_offset(derived) == 3
    assert derived["deliveryTimeline"] == source["deliveryTimeline"]


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf")])
def test_bad_intro_offset_is_rejected(source, duration):
    with pytest.raises(ValueError):
        derive_lineage(source, "compose_motion_intro", prepend_seconds=duration)


@pytest.fixture
def dispatch(monkeypatch, tmp_path, source):
    from app import main
    job = {"id": "lineage-test", "revision": 1, "outputDirectory": str(tmp_path), "workDirectory": str(tmp_path),
           "outputs": [source], "outputVersions": [{"id": "v1", "number": 1, "outputs": [source]}],
           "currentOutputVersionId": "v1", "editSessions": []}
    (tmp_path / "master.mp4").write_bytes(b"master")
    (tmp_path / "intro.mp4").write_bytes(b"intro")
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "normalize_output_versions", lambda *_: None)
    monkeypatch.setattr(main, "all_job_outputs", lambda *_: [source])
    monkeypatch.setattr(main, "output_download_context", lambda *_: (source, job["outputVersions"][0], 1))
    monkeypatch.setattr(main, "next_output_version", lambda *_: ("v2", 2))
    monkeypatch.setattr(main, "save_job", lambda *_: None)
    monkeypatch.setattr(main, "_sync_output_manifest", lambda *_: None)
    monkeypatch.setattr(main, "probe_video", lambda *_: SimpleNamespace(duration=12, width=320, height=180, has_audio=True, hasAudio=True))
    def compose(**kwargs):
        kwargs["output_path"].write_bytes(b"composed")
        return {"duration": 13.5, "introDuration": 1.5, "width": 320, "height": 180, "hasAudio": True}
    def reframe(source, target, **kwargs):
        target.write_bytes(b"reframed")
        return SimpleNamespace(duration=12, width=180, height=320)
    def submit(worker):
        result = Future()
        try:
            result.set_result(worker())
        except Exception as error:
            result.set_exception(error)
        return result
    monkeypatch.setattr(main, "compose_motion_intro_video", compose)
    monkeypatch.setattr(main, "create_social_reframe_preview", reframe)
    monkeypatch.setattr(main.output_preview_executor, "submit", submit)
    def call(tool, **arguments):
        queued = main.dispatch_agent_tool({"jobId": job["id"], "executionMode": "autonomous_review"}, tool,
                                          {"filename": "master.mp4", **arguments})
        return queued["future"].result()["artifact"]["output"]
    return call, job


@pytest.mark.parametrize("preview", [False, True])
def test_motion_dispatch_keeps_source_quality_tier_and_updates_mapping(dispatch, source, preview):
    call, job = dispatch
    source["previewOnly"] = preview
    output = call("compose_motion_intro", introFilename="intro.mp4")
    assert output["previewOnly"] is preview
    assert job["outputVersions"][-1]["previewOnly"] is preview
    assert output["deliveryTimeMap"]["bodyOffsetSeconds"] == 3.5
    assert output["coverIntro"]["start"] == 1.5
    assert output["subtitleCues"][0]["start"] == 4.5
    assert output["qualityStatus"] == "pending"


def test_reframe_dispatch_keeps_lineage(dispatch, source):
    call, _ = dispatch
    output = call("render_social_preview", aspect="9:16", fit="pad")
    for key in ("deliveryTimeMap", "deliveryTimeline", "subtitleCues", "audioPolish", "coverIntro"):
        assert output[key] == source[key]
    assert output["deliveryOperations"][-1]["operation"] == "render_social_preview"
    assert output["previewOnly"] and output["qualityStatus"] == "pending"


def test_export_dispatch_keeps_lineage_and_records_parent(dispatch, source):
    call, _ = dispatch
    output = call("export_delivery_master", platform="generic")
    assert output["deliveryTimeMap"] == source["deliveryTimeMap"]
    assert output["deliveryOperations"][-1]["sourceFilename"] == "master.mp4"
    assert output["deliveryOperations"][-1]["parentVersionId"] == "v1"


@pytest.mark.parametrize("operations,expected", [
    ({"gainDb": -6}, "volume=-6dB"),
    ({"mute": True}, "volume=0"),
    ({"noiseReduction": True}, "afftdn"),
    ({"gainDb": 0}, "anull"),
    ({"gainDb": -6, "normalizeLoudness": True}, "loudnorm=I=-16:LRA=11:TP=-1.5,alimiter=limit=0.95,volume=-6dB"),
    ({}, "loudnorm=I=-16:LRA=11:TP=-1.5,alimiter=limit=0.95"),
])
def test_audio_dispatch_keeps_lineage_and_applies_only_requested_operations(dispatch, source, monkeypatch, operations, expected):
    from pathlib import Path
    commands = []
    def render(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"audio-updated")
    monkeypatch.setattr("app.media._run_cancellable", render)
    call, _ = dispatch
    output = call("polish_audio_mix", **operations)
    assert output["deliveryTimeMap"] == source["deliveryTimeMap"]
    assert output["subtitleCues"] == source["subtitleCues"]
    assert output["deliveryOperations"][-1]["operation"] == "polish_audio_mix"
    assert output["audioPolish"]["gainDb"] == operations.get("gainDb", 0)
    assert commands[0][commands[0].index("-af") + 1] == expected
    assert output["qualityStatus"] == "pending"


def test_replacing_cover_after_motion_keeps_body_and_caption_positions(source):
    source["coverIntro"]["start"] = 1
    source["deliveryTimeMap"]["bodyOffsetSeconds"] = 3
    source["motionIntro"] = {"enabled": True, "introDuration": 1}
    source["subtitleCues"] = [{"start": 4, "end": 5, "text": "对白"}]
    original = copy.deepcopy(source)
    result = replace_cover_lineage(source, .5)
    assert result["deliveryTimeMap"]["bodyOffsetSeconds"] == 1.5
    assert result["subtitleCues"] == [{"start": 2.5, "end": 3.5, "text": "对白"}]
    assert result["motionIntro"] == source["motionIntro"]
    assert result["deliveryOperations"][-1]["removedStart"] == 1
    assert source == original


def test_caption_removal_clips_crossing_cues_and_discards_removed_cues():
    result = remap_subtitle_cues([
        {"start": .2, "end": .6}, {"start": 1.2, "end": 1.8},
        {"start": .5, "end": 3.5}, {"start": 4, "end": 5}],
        removed_start=1, removed_duration=2, prepend_seconds=.5)
    assert result == [{"start": .7, "end": 1.1}, {"start": 1, "end": 2}, {"start": 2.5, "end": 3.5}]


@pytest.mark.parametrize("start,duration", [(3, 2), (-1, 2), (0, 0), (0, float("nan"))])
def test_cover_record_cannot_cut_into_body(source, start, duration):
    source["coverIntro"].update(start=start, duration=duration)
    with pytest.raises(ValueError, match="不能安全替换"):
        replace_cover_lineage(source, 1)


@pytest.mark.parametrize("aspect", ["9:16", "1:1", "unsupported"])
def test_export_rejects_wrong_aspect_without_creating_version(dispatch, aspect):
    call, job = dispatch
    with pytest.raises(RuntimeError, match="画幅"):
        call("export_delivery_master", aspect=aspect)
    assert len(job["outputVersions"]) == 1
    from pathlib import Path
    assert not list(Path(job["outputDirectory"]).glob("delivery-*.mp4"))


def test_export_accepts_matching_aspect(dispatch):
    output = dispatch[0]("export_delivery_master", aspect="16:9")
    assert output["delivery"]["aspect"] == "16:9"
    assert (output["width"], output["height"]) == (320, 180)


@pytest.mark.parametrize("interruption", ["cancel", "version"])
def test_export_does_not_publish_over_new_user_action(dispatch, monkeypatch, interruption):
    from pathlib import Path
    import threading
    from app import main
    call, job = dispatch
    copy_file = main.shutil.copy2
    monkeypatch.delitem(main.cancel_events, job["id"], raising=False)
    def copy_then_interrupt(source, target):
        copy_file(source, target)
        if interruption == "cancel":
            event = threading.Event()
            event.set()
            monkeypatch.setitem(main.cancel_events, job["id"], event)
        else:
            job["currentOutputVersionId"] = "new-choice"
    monkeypatch.setattr(main.shutil, "copy2", copy_then_interrupt)
    with pytest.raises(RuntimeError, match="已停止|已变化"):
        call("export_delivery_master", aspect="16:9")
    assert len(job["outputVersions"]) == 1
    assert not list(Path(job["outputDirectory"]).glob("delivery-*.mp4"))


@pytest.mark.parametrize("interruption", ["none", "cover", "version", "cancel"])
def test_agent_cover_replacement_preserves_edits_and_rejects_stale_cover(dispatch, source, monkeypatch, interruption):
    import threading
    from pathlib import Path
    from app import main
    call, job = dispatch
    root = Path(job["workDirectory"])
    (root / "new-cover.jpg").write_bytes(b"cover")
    job.update(currentCoverVersionId="new-cover", coverVersions=[{"id": "new-cover", "artifactFile": "new-cover.jpg"}])
    event = threading.Event()
    monkeypatch.setitem(main.cancel_events, job["id"], event)
    original = copy.deepcopy(source)
    removed = []
    def remove(video, target, **kwargs):
        assert video.name == "master.mp4"
        assert kwargs["duration"] == 2 and kwargs["start"] == 0
        removed.append(target)
        target.write_bytes(b"selected-master-without-old-cover")
    def render(video, cover, target, **kwargs):
        assert video.read_bytes() == b"selected-master-without-old-cover"
        target.write_bytes(b"new-preview")
        if interruption == "cover":
            job["currentCoverVersionId"] = "another-cover"
        elif interruption == "version":
            job["currentOutputVersionId"] = "another-version"
        elif interruption == "cancel":
            event.set()
        return {"duration": 10.5, "introDuration": .5, "width": 320, "height": 180, "hasAudio": True}
    monkeypatch.setattr("app.cover_delivery.remove_leading_intro", remove)
    monkeypatch.setattr(main, "render_cover_intro", render)
    if interruption != "none":
        with pytest.raises(RuntimeError, match="已变化|已停止"):
            call("compose_cover_intro", duration=.5)
        assert not job.get("agentPreviewOutputs")
        assert not list(root.glob("agent-cover-intro-preview-*.mp4"))
    else:
        output = call("compose_cover_intro", duration=.5)
        assert output["deliveryTimeMap"]["bodyOffsetSeconds"] == .5
        assert output["subtitleCues"][0]["start"] == 1.5
        assert output["coverIntro"]["coverVersionId"] == "new-cover"
        assert output["audioPolish"] == source["audioPolish"] and output["previewOnly"]
    assert source == original
    assert removed and all(not path.exists() for path in removed)
