from __future__ import annotations

import hashlib
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.cover_delivery import (
    bind_cover_to_output_version,
    build_output_package,
    output_cover_path,
    render_cover_intro,
)


def delivery_job(tmp_path: Path) -> tuple[dict, dict, dict]:
    work = tmp_path / "work"
    outputs = tmp_path / "outputs"
    cover = work / "cover-director" / "draft" / "variants" / "approved.jpg"
    work.mkdir()
    outputs.mkdir()
    cover.parent.mkdir(parents=True)
    Image.new("RGB", (640, 360), (38, 72, 105)).save(cover, "JPEG")
    content_hash = "sha256:" + hashlib.sha256(cover.read_bytes()).hexdigest()
    (outputs / "final.mp4").write_bytes(b"video")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video")
    cover_version = {
        "id": "cover_v001", "contentHash": content_hash,
        "artifactFile": str(cover.relative_to(work)),
    }
    output = {"filename": "final.mp4", "title": "正式成片"}
    version = {"id": "v001", "number": 1, "outputs": [output]}
    job = {
        "id": "job_delivery", "filename": "source.mp4",
        "sourcePath": str(source), "videoInfo": {"duration": 12.0},
        "workDirectory": str(work), "outputDirectory": str(outputs),
        "currentCoverVersionId": "cover_v001", "coverVersions": [cover_version],
        "currentOutputVersionId": "v001", "outputVersions": [version], "outputs": [output],
    }
    return job, version, cover_version


def test_bind_cover_copies_sidecar_and_records_explicit_version(tmp_path: Path) -> None:
    job, version, cover_version = delivery_job(tmp_path)

    bound = bind_cover_to_output_version(job, cover_version, version)

    assert bound[0]["coverFilename"] == "final-cover.jpg"
    assert version["coverVersionId"] == "cover_v001"
    assert version["outputs"][0]["coverVersionId"] == "cover_v001"
    assert output_cover_path(job, version["outputs"][0], version) == tmp_path / "outputs" / "final-cover.jpg"


def test_release_package_contains_video_cover_and_manifest(tmp_path: Path) -> None:
    job, version, cover_version = delivery_job(tmp_path)
    bind_cover_to_output_version(job, cover_version, version)

    package = build_output_package(
        job, version["outputs"][0], version, video_download_name="厨房教程_V1.mp4",
    )

    with zipfile.ZipFile(package) as archive:
        assert set(archive.namelist()) == {
            "厨房教程_V1.mp4", "厨房教程_V1-cover.jpg", "manifest.json",
        }
        assert b'"coverVersionId": "cover_v001"' in archive.read("manifest.json")


def test_public_output_exposes_cover_package_and_intro_actions(tmp_path: Path) -> None:
    from app import main

    job, version, cover_version = delivery_job(tmp_path)
    bind_cover_to_output_version(job, cover_version, version)

    public = main.public_job(job)
    output = public["outputVersions"][0]["outputs"][0]

    assert output["coverUrl"].endswith("/outputs/final.mp4/cover")
    assert output["packageUrl"].endswith("/outputs/final.mp4/package")
    assert output["coverIntroAvailable"] is True


def test_intro_worker_appends_a_new_bound_output_version(tmp_path: Path, monkeypatch) -> None:
    from app import main

    job, version, cover_version = delivery_job(tmp_path)
    bind_cover_to_output_version(job, cover_version, version)
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)

    def render(_video: Path, _cover: Path, output: Path, **_kwargs):
        output.write_bytes(b"intro-video")
        return {"duration": 2.2, "width": 640, "height": 360, "hasAudio": True, "introDuration": 1.0}

    monkeypatch.setattr(main, "render_cover_intro", render)

    main.run_cover_intro_render(job["id"], "final.mp4", 1.0)

    created = job["outputVersions"][-1]
    output = created["outputs"][0]
    assert created["id"] == "v002"
    assert created["variantKind"] == "cover_intro_export"
    assert output["coverIntro"]["sourceFilename"] == "final.mp4"
    assert output["coverVersionId"] == "cover_v001"
    assert (tmp_path / "outputs" / output["filename"]).is_file()
    assert (tmp_path / "outputs" / output["coverFilename"]).is_file()
    assert job["coverIntroOperation"]["status"] == "completed"


def test_notification_failure_does_not_delete_published_cover_video(tmp_path, monkeypatch):
    from app import main
    job, version, cover = delivery_job(tmp_path)
    bind_cover_to_output_version(job, cover, version)
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda *_: None)
    def render(video, cover, target, **kwargs):
        target.write_bytes(b"published-video")
        return {"duration": 3, "introDuration": 1, "width": 320, "height": 180, "hasAudio": True}
    def fail_notice(*args, **kwargs):
        raise RuntimeError("notice unavailable")
    monkeypatch.setattr(main, "render_cover_intro", render)
    monkeypatch.setattr(main, "append_message", fail_notice)
    with pytest.raises(RuntimeError, match="notice unavailable"):
        main.run_cover_intro_render(job["id"], "final.mp4", 1)
    assert len(job["outputVersions"]) == 2
    assert (Path(job["outputDirectory"]) / job["outputs"][0]["filename"]).read_bytes() == b"published-video"


def test_intro_worker_can_use_source_video_before_any_output_exists(
    tmp_path: Path, monkeypatch,
) -> None:
    from app import main

    job, _version, _cover_version = delivery_job(tmp_path)
    job["outputVersions"] = []
    job["outputs"] = []
    job.pop("currentOutputVersionId", None)
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)

    def render(video: Path, cover: Path, output: Path, **_kwargs):
        assert video == Path(job["sourcePath"])
        assert cover.is_file()
        output.write_bytes(b"source-with-intro")
        return {"duration": 13.2, "width": 640, "height": 360, "hasAudio": True, "introDuration": 1.2}

    monkeypatch.setattr(main, "render_cover_intro", render)

    main.run_cover_intro_render(job["id"], "source.mp4", 1.2, "source_video")

    created = job["outputVersions"][-1]
    output = created["outputs"][0]
    assert created["id"] == "v001"
    assert output["title"] == "原视频（封面片头）"
    assert output["coverIntro"] == {
        "enabled": True, "start": 0, "duration": 1.2, "coverVersionId": "cover_v001",
        "sourceFilename": "source.mp4", "sourceKind": "source_video",
    }
    assert output["coverVersionId"] == "cover_v001"
    assert job["coverIntroDraft"]["renderedVersionId"] == "v001"
    assert (tmp_path / "outputs" / output["filename"]).is_file()
    assert (tmp_path / "outputs" / output["coverFilename"]).is_file()


def test_timeline_render_endpoint_requires_a_generated_output(
    tmp_path: Path, monkeypatch,
) -> None:
    from app import main
    from app.api_schemas import CoverIntroRequest

    job, _version, _cover_version = delivery_job(tmp_path)
    job["outputVersions"] = []
    job["outputs"] = []
    job.pop("currentOutputVersionId", None)
    captured = {}
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)

    def submit(job_id, target, *args):
        captured.update({"jobId": job_id, "target": target, "args": args})
        return None

    monkeypatch.setattr(main, "submit_render_task", submit)

    with pytest.raises(main.HTTPException) as error:
        main.render_cover_intro_draft(job["id"], CoverIntroRequest(duration=1.4))

    assert error.value.status_code == 409
    assert "先生成并确认成片" in str(error.value.detail)
    assert captured == {}
    assert "coverIntroOperation" not in job


def test_adjusting_an_existing_source_intro_does_not_stack_a_second_intro(
    tmp_path: Path, monkeypatch,
) -> None:
    from app import main
    from app.api_schemas import CoverIntroRequest

    job, version, cover_version = delivery_job(tmp_path)
    bind_cover_to_output_version(job, cover_version, version)
    version["outputs"][0]["coverIntro"] = {
        "enabled": True, "duration": 1.0,
        "sourceFilename": "source.mp4", "sourceKind": "source_video",
    }
    captured = {}
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "submit_render_task", lambda _job_id, _target, *args: captured.setdefault("args", args))

    main.render_cover_intro_draft(job["id"], CoverIntroRequest(duration=2.0))

    assert captured["args"] == ("final.mp4", 2.0, "output")


def test_cover_timeline_does_not_rebind_history_before_render(tmp_path, monkeypatch):
    import copy
    from app import main
    from app.api_schemas import CoverIntroRequest
    job, version, cover = delivery_job(tmp_path)
    bind_cover_to_output_version(job, cover, version)
    old_sidecar = Path(job["outputDirectory"]) / version["outputs"][0]["coverFilename"]
    old_bytes, old_version = old_sidecar.read_bytes(), copy.deepcopy(version)
    new_artifact = Path(job["workDirectory"]) / "replacement.jpg"
    Image.new("RGB", (640, 360), "red").save(new_artifact)
    job["coverVersions"].append({"id": "cover_v002", "artifactFile": "replacement.jpg"})
    job["currentCoverVersionId"] = "cover_v002"
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "normalize_output_versions", lambda *_: None)
    monkeypatch.setattr(main, "save_job", lambda *_: None)
    monkeypatch.setattr(main, "submit_render_task", lambda *_: None)
    main.render_cover_intro_draft(job["id"], CoverIntroRequest(duration=1))
    assert old_sidecar.read_bytes() == old_bytes
    assert version == old_version


@pytest.mark.parametrize("interruption", ["cover", "version", "cancel"])
def test_old_manual_cover_completion_does_not_overwrite_new_state(tmp_path, monkeypatch, interruption):
    import threading
    from app import main
    job, version, cover = delivery_job(tmp_path)
    bind_cover_to_output_version(job, cover, version)
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.delitem(main.cancel_events, job["id"], raising=False)
    monkeypatch.setattr(main, "save_job", lambda *_: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    produced = []
    def render(video, cover, target, **kwargs):
        target.write_bytes(b"stale-render")
        produced.append(target)
        job["currentAction"] = "用户的新操作"
        if interruption == "cover":
            job["currentCoverVersionId"] = "new-cover"
        elif interruption == "version":
            job["currentOutputVersionId"] = "new-version"
        else:
            event = threading.Event()
            event.set()
            monkeypatch.setitem(main.cancel_events, job["id"], event)
        return {"duration": 3, "introDuration": 1, "width": 320, "height": 180, "hasAudio": True}
    monkeypatch.setattr(main, "render_cover_intro", render)
    with pytest.raises(RuntimeError, match="已变化|已停止"):
        main.run_cover_intro_render(job["id"], "final.mp4", 1)
    assert job["currentAction"] == "用户的新操作"
    assert len(job["outputVersions"]) == 1 and not job.get("error")
    assert produced and all(not path.exists() for path in produced)


@pytest.mark.skipif(not Path("/usr/bin/ffmpeg").is_file(), reason="requires ffmpeg")
def test_real_manual_cover_replacement_keeps_later_intro_and_history(tmp_path, monkeypatch):
    from app import main
    from app.media import probe_video
    job, version, old_cover = delivery_job(tmp_path)
    outputs = Path(job["outputDirectory"])
    body = outputs / "body.mp4"
    ffmpeg, ffprobe = "/usr/bin/ffmpeg", "/usr/bin/ffprobe"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=320x180:r=30:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(body)], check=True, timeout=30)
    cover_file = Path(job["workDirectory"]) / old_cover["artifactFile"]
    covered = outputs / "covered.mp4"
    render_cover_intro(body, cover_file, covered, duration=1, ffmpeg=ffmpeg, ffprobe=ffprobe)
    # A distinct half-second intro was added after the old cover was made.
    motion_image = tmp_path / "motion.png"
    Image.new("RGB", (320, 180), "lime").save(motion_image)
    final = outputs / "final.mp4"
    render_cover_intro(covered, motion_image, final, duration=.5, ffmpeg=ffmpeg, ffprobe=ffprobe)
    original_bytes = final.read_bytes()
    source = version["outputs"][0]
    source.update(coverIntro={"enabled": True, "start": .5, "duration": 1},
                  motionIntro={"enabled": True, "introDuration": .5},
                  deliveryTimeMap={"schemaVersion": 1, "bodyOffsetSeconds": 1.5},
                  subtitleCues=[{"start": 2, "end": 2.5, "text": "对白"}], audioPolish={"gainDb": -3})
    bind_cover_to_output_version(job, old_cover, version)
    old_sidecar = outputs / source["coverFilename"]
    old_sidecar_bytes = old_sidecar.read_bytes()
    replacement = Path(job["workDirectory"]) / "replacement.jpg"
    Image.new("RGB", (320, 180), "red").save(replacement)
    job["currentCoverVersionId"] = "cover_v002"
    job["coverVersions"].append({"id": "cover_v002", "artifactFile": "replacement.jpg"})
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda *_: None)
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "settings", type("Settings", (), {"ffmpeg": ffmpeg, "ffprobe": ffprobe})())
    main.run_cover_intro_render(job["id"], "final.mp4", .5)
    result = job["outputs"][0]
    media = probe_video(outputs / result["filename"], ffprobe)
    assert media.duration == pytest.approx(3, abs=.15) and media.has_audio
    assert result["deliveryTimeMap"]["bodyOffsetSeconds"] == 1
    assert result["subtitleCues"] == [{"start": 1.5, "end": 2, "text": "对白"}]
    assert result["audioPolish"] == {"gainDb": -3}
    assert result["coverIntro"]["coverVersionId"] == "cover_v002"
    assert final.read_bytes() == original_bytes and old_sidecar.read_bytes() == old_sidecar_bytes
    assert not list(outputs.glob(".*.body.mp4"))
    # New red cover, retained green intro, then original blue body.
    for timestamp, dominant in ((.2, 0), (.7, 1), (1.3, 2)):
        frame = subprocess.run([ffmpeg, "-v", "error", "-ss", str(timestamp), "-i", str(outputs / result["filename"]),
                                "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                               capture_output=True, check=True, timeout=30).stdout
        assert len(frame) == 3 and frame[dominant] > 150


def test_cover_timeline_keeps_independent_settings_and_activation_does_not_render(
    tmp_path: Path, monkeypatch,
) -> None:
    from app import main
    from app.api_schemas import CoverTimelineDraftRequest

    job, _version, cover_version = delivery_job(tmp_path)
    work = Path(job["workDirectory"])
    first_path = work / str(cover_version["artifactFile"])
    second_path = first_path.with_name("alternate.jpg")
    Image.new("RGB", (640, 360), (112, 48, 64)).save(second_path, "JPEG")
    second_hash = "sha256:" + hashlib.sha256(second_path.read_bytes()).hexdigest()
    job["coverDraft"] = {
        "id": "draft_timeline", "status": "approved",
        "selectedVariantId": "cover_variant_one",
        "approvedVariantId": "cover_variant_one",
        "variants": [
            {
                "variantId": "cover_variant_one", "contentHash": cover_version["contentHash"],
                "artifactFile": cover_version["artifactFile"], "direction": "source_clean",
            },
            {
                "variantId": "cover_variant_two", "contentHash": second_hash,
                "artifactFile": str(second_path.relative_to(work)), "direction": "source_editorial",
            },
        ],
    }
    job["coverVersions"][0]["variantId"] = "cover_variant_one"
    monkeypatch.setitem(main.jobs, job["id"], job)
    monkeypatch.setattr(main, "save_job", lambda item: item.__setitem__("revision", int(item.get("revision") or 0) + 1))
    monkeypatch.setattr(main, "append_message", lambda *_args, **_kwargs: None)

    main.update_cover_timeline_draft(
        job["id"], CoverTimelineDraftRequest(variantId="cover_variant_one", duration=1.2),
    )
    main.update_cover_timeline_draft(
        job["id"], CoverTimelineDraftRequest(variantId="cover_variant_two", duration=2.4),
    )

    states = job["coverTimelineDraft"]["variants"]
    assert states["cover_variant_one"]["duration"] == 1.2
    assert states["cover_variant_two"]["duration"] == 2.4
    assert job["coverTimelineDraft"]["activeVariantId"] == "cover_variant_two"
    job["coverDraft"]["requestedSourceTime"] = 12.0
    job["coverDraft"]["variants"][1]["sourceTime"] = 52.0
    with pytest.raises(RuntimeError, match="不是指定的 12.0 秒附近"):
        main._activate_cover_variant(job["id"], "cover_variant_two", expected_hash=second_hash)
    job["coverDraft"]["variants"][1]["sourceTime"] = 12.0
    response = main.activate_cover_timeline_variant(
        job["id"], CoverTimelineDraftRequest(
            variantId="cover_variant_two", duration=2.4, contentHash=second_hash,
        ),
    )
    assert response["job"]["currentCoverVersionId"] == "cover_v002"
    assert job["coverIntroDraft"]["duration"] == 2.4
    assert job["outputVersions"][-1]["outputs"][0]["coverVersionId"] == "cover_v002"
    assert job.get("coverIntroOperation") is None


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires ffmpeg")
def test_cover_intro_is_a_new_decodable_video_with_expected_duration(tmp_path: Path) -> None:
    ffmpeg = "/usr/bin/ffmpeg" if Path("/usr/bin/ffmpeg").is_file() else (shutil.which("ffmpeg") or "ffmpeg")
    ffprobe = "/usr/bin/ffprobe" if Path("/usr/bin/ffprobe").is_file() else (shutil.which("ffprobe") or "ffprobe")
    video = tmp_path / "source.mp4"
    cover = tmp_path / "cover.jpg"
    output = tmp_path / "with-intro.mp4"
    Image.new("RGB", (320, 180), (120, 48, 32)).save(cover, "JPEG")
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=1.2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video),
    ], check=True)

    rendered = render_cover_intro(
        video, cover, output, duration=.6,
        ffmpeg=ffmpeg, ffprobe=ffprobe,
    )

    assert output.is_file()
    assert rendered["hasAudio"] is True
    assert rendered["duration"] >= 1.7
    assert rendered["introDuration"] == .6


@pytest.mark.skipif(not Path("/usr/bin/ffmpeg").is_file(), reason="requires ffmpeg")
def test_landscape_cover_title_margins_survive_portrait_intro(tmp_path: Path) -> None:
    from PIL import ImageDraw
    ffmpeg, ffprobe = "/usr/bin/ffmpeg", "/usr/bin/ffprobe"
    video, cover, output = tmp_path / "portrait.mp4", tmp_path / "cover.png", tmp_path / "final.mp4"
    # Simulate title blocks on both far edges of a confirmed landscape cover.
    artwork = Image.new("RGB", (320, 180), "blue")
    draw = ImageDraw.Draw(artwork)
    draw.rectangle((0, 0, 79, 179), fill="red")
    draw.rectangle((240, 0, 319, 179), fill="lime")
    artwork.save(cover)
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=white:s=180x320:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    render_cover_intro(video, cover, output, duration=.5, ffmpeg=ffmpeg, ffprobe=ffprobe)
    frame = subprocess.run([ffmpeg, "-v", "error", "-ss", "0.2", "-i", str(output), "-frames:v", "1",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    image = Image.frombytes("RGB", (180, 320), frame)
    left, right = image.getpixel((10, 160)), image.getpixel((170, 160))
    assert left[0] > 180 and left[1] < 70
    assert right[1] > 180 and right[0] < 70
