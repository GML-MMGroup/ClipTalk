from pathlib import Path

from app.output_library import library_outputs
from app.kept_api import build_kept_router
from app.output_naming import build_output_naming


def make_job(tmp_path):
    (tmp_path / "final.mp4").write_bytes(b"test output")
    (tmp_path / "preview.mp4").write_bytes(b"test preview")
    return {"id": "job_library", "filename": "访谈.mp4", "outputDirectory": str(tmp_path),
            "outputVersions": [{"id": "v1", "number": 1, "outputs": [{"filename": "final.mp4", "duration": 12}]},
                               {"id": "v2", "number": 2, "previewOnly": True, "outputs": [{"filename": "preview.mp4"}]}]}


def test_library_reads_formal_outputs_without_creating_retained_copies(tmp_path):
    job = make_job(tmp_path)
    job["outputVersions"][0]["coverVersionId"] = "cover_v001"
    job["outputVersions"][0]["outputs"][0].update({
        "coverVersionId": "cover_v001", "coverContentHash": "sha256:cover",
    })
    before = set(tmp_path.iterdir())
    rows = library_outputs([job], [])
    assert len(rows) == 1
    assert rows[0]["filename"] == "final.mp4"
    assert rows[0]["versionId"] == "v1"
    assert rows[0]["kept"] is False
    assert rows[0]["sourceFileAvailable"] is True
    assert rows[0]["coverUrl"].endswith("/outputs/final.mp4/cover")
    assert rows[0]["coverVersionId"] == "cover_v001"
    assert rows[0]["coverContentHash"] == "sha256:cover"
    assert str(tmp_path) not in str(rows)
    assert set(tmp_path.iterdir()) == before


def test_library_deduplicates_but_preserves_orphaned_copies(tmp_path):
    job = make_job(tmp_path)
    saved = {"jobId": job["id"], "filename": "final.mp4", "videoUrl": "/api/kept/file", "keptAt": "2026-09-14"}
    rows = library_outputs([job], [saved])
    assert len(rows) == 1 and rows[0]["kept"]
    assert rows[0]["videoUrl"].startswith("/api/jobs/")
    (tmp_path / "final.mp4").unlink()
    rows = library_outputs([job], [saved])
    assert rows[0]["videoUrl"] == saved["videoUrl"]
    assert rows[0]["sourceTaskAvailable"] and not rows[0]["sourceFileAvailable"]
    assert library_outputs([], [saved])[0]["sourceTaskAvailable"] is False


def test_library_excludes_missing_files_preview_items_and_escape_paths(tmp_path):
    job = make_job(tmp_path)
    job["outputVersions"][0]["outputs"] = [
        {"filename": "missing.mp4"}, {"filename": "preview.mp4", "previewOnly": True},
        {"filename": "../outside.mp4"}, {"filename": "final.mp4", "outputKind": "agent_review_preview"},
    ]
    assert library_outputs([job], [{"previewOnly": True}]) == []


def test_library_does_not_expose_symlink_outside_output_directory(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    job = make_job(outputs)
    (tmp_path / "outside.mp4").write_bytes(b"private")
    (outputs / "final.mp4").unlink()
    (outputs / "final.mp4").symlink_to(tmp_path / "outside.mp4")
    assert library_outputs([job], []) == []


def test_library_router_preserves_existing_endpoints():
    router = build_kept_router(list_kept_outputs=lambda: {}, kept_media=lambda: {}, kept_cover=lambda: {}, delete_kept_output=lambda: {}, list_library_outputs=lambda: {})
    assert {route.path for route in router.routes} == {"/api/kept", "/api/kept/{job_id}/{filename}", "/api/kept/{job_id}/{filename}/cover", "/api/library/outputs"}


def test_long_instructions_and_internal_draft_names_are_not_public_titles():
    result = build_output_naming({"filename": "访谈.mp4", "request": {"contentInstruction": "仅根据对白检索：分别检索访谈中的核心话题，保留必要上下文"}},
                                 {"number": 1, "displayName": "Agent 安全时间线草案"}, {"title": "内容视频"})
    assert result["displayTitle"] == "访谈 · 精剪版"
