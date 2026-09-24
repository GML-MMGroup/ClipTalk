"""UI contracts must describe the selected artifact, not inferred task defaults."""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main
from app.api_schemas import ProjectSettingsRequest
from app.edit_sessions import create_or_resume_edit_session, refresh_edit_session, _job_requested_reframe
from app.job_projection import ui_presentation_snapshot


def test_partial_fit_updates_preserve_aspect_and_unknown_preferences(monkeypatch):
    job = {"id": "settings_ui", "projectSettings": {"outputAspect": "9:16", "custom": "keep"}}
    monkeypatch.setattr(main, "jobs", {job["id"]: job})
    monkeypatch.setattr(main, "save_job", lambda _: None)
    monkeypatch.setattr(main, "public_job", copy.deepcopy)
    main.update_job_project_settings(job["id"], ProjectSettingsRequest(outputFit="crop"))
    assert job["projectSettings"] == {"outputAspect": "9:16", "outputFit": "crop", "custom": "keep"}
    main.update_job_project_settings(job["id"], ProjectSettingsRequest())
    assert job["projectSettings"]["outputFit"] == "crop"
    assert job["projectSettings"]["outputAspect"] == "9:16"
    with pytest.raises(ValueError):
        ProjectSettingsRequest(outputFit="stretch")


def test_project_defaults_apply_to_new_timelines_not_existing_outputs():
    job = {"id": "canvas_ui", "videoInfo": {"duration": 100},
           "projectSettings": {"outputAspect": "9:16", "outputFit": "crop"},
           "outputVersions": [{"id": "v1", "number": 1, "outputs": [
               {"filename": "source-canvas.mp4", "segments": [{"start": 2, "end": 8}]}]}]}
    assert _job_requested_reframe(job)["fit"] == "crop"
    session, _ = create_or_resume_edit_session(job, version_id="v1")
    assert session["reframe"] is None
    job["projectSettings"]["outputAspect"] = "16:9"
    job["brief"] = {"socialDelivery": {"requested": True, "aspect": "9:16", "fit": "blur"}}
    refresh_edit_session(session, job)
    assert session["reframe"] is None
    assert main._effective_edit_session_reframe(job, session) is None


def test_actual_output_dimensions_are_probed_and_cached_without_changing_job(monkeypatch, tmp_path):
    media = tmp_path / "v1.mp4"
    media.write_bytes(b"test artifact; probe mocked")
    calls = []
    def probe(path, executable):
        calls.append(path)
        return SimpleNamespace(width=1024, height=576)
    monkeypatch.setattr(main, "probe_video", probe)
    job = main.new_job_record(job_id="dimensions_ui", source=Path("/tmp/source.mp4"), filename="source.mp4",
                              size=10, count="auto", target_seconds="auto", theme="")
    job.update({"outputDirectory": str(tmp_path), "videoInfo": {"width": 1080, "height": 1920, "duration": 10},
                "outputVersions": [{"id": "v1", "number": 1, "outputs": [{"filename": "v1.mp4", "duration": 5}]}]})
    original = copy.deepcopy(job)
    for _ in range(2):
        output = main.public_job(job)["outputVersions"][0]["outputs"][0]
        assert (output["width"], output["height"]) == (1024, 576)
    assert calls == [media]
    assert job == original


def test_missing_quality_is_not_a_pass():
    assert main.output_version_quality_status({"outputs": [{"filename": "formal.mp4"}]}) == "pending"
    assert main.output_version_quality_status({"qualityGate": {"passed": True}}) == "passed"


def test_candidate_review_is_the_third_stage_not_sample_review():
    view = ui_presentation_snapshot({"status": "awaiting_content_confirmation"}, workflow={}, execution={}, output_count=0)
    assert view["journeyStage"] == 2
