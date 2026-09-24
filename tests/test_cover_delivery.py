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
        "enabled": True, "duration": 1.2,
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

    assert captured["args"] == ("source.mp4", 2.0, "source_video")


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
