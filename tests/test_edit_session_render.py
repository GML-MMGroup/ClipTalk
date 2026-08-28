from __future__ import annotations

import copy

from app import main
from app.edit_sessions import create_or_resume_edit_session


def _render_job() -> dict:
    return {
        "id": "secondary-render-job",
        "workflowKind": "content_search",
        "videoInfo": {"duration": 60.0},
        "request": {},
        "outputs": [{"filename": "version-1.mp4"}],
        "currentOutputVersionId": "version-1",
        "outputVersions": [{
            "id": "version-1",
            "number": 1,
            "outputs": [{
                "filename": "version-1.mp4",
                "segments": [{"id": "source-1", "start": 4.0, "end": 10.0, "role": "原成片"}],
            }],
        }],
    }


def test_secondary_render_commits_a_child_version_and_preserves_parent(monkeypatch) -> None:
    job = _render_job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    parent_before = copy.deepcopy(job["outputVersions"][0])
    messages: list[str] = []

    def fake_confirmed_render(*args) -> None:
        metadata = dict(args[12])
        job["outputVersions"].append({
            "id": "version-2", "number": 2, **metadata,
            "outputs": [{"filename": "version-2.mp4", "segments": copy.deepcopy(args[6])}],
        })
        job["currentOutputVersionId"] = "version-2"
        job["status"] = "completed"

    monkeypatch.setattr(main, "jobs", {job["id"]: job})
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "run_confirmed_render", fake_confirmed_render)
    monkeypatch.setattr(main, "append_message", lambda _job_id, _role, text, **_kwargs: messages.append(text))

    main.run_edit_session_render(job["id"], session["id"], session["revision"])

    assert job["outputVersions"][0] == parent_before
    assert len(job["outputVersions"]) == 2
    child = job["outputVersions"][1]
    assert child["parentVersionId"] == "version-1"
    assert child["editSessionId"] == session["id"]
    assert child["origin"] == "secondary_edit"
    assert session["status"] == "rendered"
    assert session["renderedVersionId"] == "version-2"
    assert messages and "原版本保持不变" in messages[-1]


def test_preview_fingerprint_tracks_timeline_and_subtitle_revision(monkeypatch) -> None:
    job = _render_job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )
    initial = main._edit_session_preview_fingerprint(job, session)
    session["clips"][0]["audioGain"] = 1.25
    changed_timeline = main._edit_session_preview_fingerprint(job, session)
    assert changed_timeline != initial

    draft = {"id": "subtitle-1", "revision": 1, "cues": [], "globalStyle": {}, "cueStyleOverrides": {}}
    monkeypatch.setattr(main, "_subtitle_draft_for_job", lambda _job, _draft_id: draft)
    session.update({"subtitleEnabled": True, "subtitleDraftId": "subtitle-1"})
    first_subtitle = main._edit_session_preview_fingerprint(job, session)
    draft["revision"] = 2
    assert main._edit_session_preview_fingerprint(job, session) != first_subtitle


def test_secondary_render_does_not_mistake_preserved_parent_for_success(monkeypatch) -> None:
    job = _render_job()
    session, _created = create_or_resume_edit_session(
        job, version_id="version-1", output_filename="version-1.mp4",
    )

    def fake_failed_render(*_args) -> None:
        job["status"] = "completed"
        job["error"] = "编码失败"
        job["detail"] = "新版本生成失败，已保留此前成片"

    monkeypatch.setattr(main, "jobs", {job["id"]: job})
    monkeypatch.setattr(main, "save_job", lambda _job: None)
    monkeypatch.setattr(main, "run_confirmed_render", fake_failed_render)

    main.run_edit_session_render(job["id"], session["id"], session["revision"])

    assert len(job["outputVersions"]) == 1
    assert job["currentOutputVersionId"] == "version-1"
    assert session["status"] == "failed"
    assert not session.get("renderedVersionId")
    assert "编码失败" in session["renderError"]
    assert job["detail"] == "二次编辑版本生成失败，草稿和原版本均已保留"
