from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.kept_library import KeptLibraryService


def make_service(root: Path) -> KeptLibraryService:
    return KeptLibraryService(
        data_root=root,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        preview_lock=threading.Lock(),
    )


def test_kept_library_saves_lists_and_removes_copy(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video-bytes")
    record = {
        "jobId": "job_1", "filename": "highlight.mp4",
        "sourceFilename": "访谈.mp4", "title": "关键片段",
        "versionNumber": 2, "strategyKey": "llm", "position": 1,
        "keptAt": "2026-08-14T00:00:00+00:00",
    }
    stored = service.save_copy(source=source, record=record)
    assert stored["sizeBytes"] == len(b"video-bytes")
    listed = service.list_records()
    assert len(listed) == 1
    assert listed[0]["videoUrl"] == "/api/kept/job_1/highlight.mp4"
    assert "LLM" in listed[0]["downloadFilename"]
    service.remove("job_1", "highlight.mp4")
    assert service.list_records() == []


@pytest.mark.parametrize("job_id,filename", [
    ("../escape", "clip.mp4"),
    ("job_1", "../clip.mp4"),
    ("job_1", ""),
])
def test_kept_library_rejects_path_traversal(tmp_path: Path, job_id: str, filename: str) -> None:
    with pytest.raises(HTTPException):
        make_service(tmp_path).output_paths(job_id, filename)
