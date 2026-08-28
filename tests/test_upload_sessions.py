from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from app.upload_sessions import UploadSessionStore


def test_upload_session_resumes_from_durable_offset_and_consumes_atomically(tmp_path) -> None:
    store = UploadSessionStore(tmp_path / "sessions", maximum_bytes=32)
    created = store.create("../clip.mp4", 6)
    assert created["filename"] == "clip.mp4"
    assert store.append(created["id"], 0, b"abc")["offset"] == 3

    resumed = UploadSessionStore(tmp_path / "sessions", maximum_bytes=32)
    assert resumed.get(created["id"])["offset"] == 3
    assert resumed.append(created["id"], 3, b"def")["offset"] == 6
    destination = tmp_path / "uploads" / "video.mp4"
    destination.parent.mkdir()
    receipt = resumed.consume(created["id"], destination)

    assert destination.read_bytes() == b"abcdef"
    assert receipt.sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert not (tmp_path / "sessions" / f"{created['id']}.part").exists()


def test_upload_session_rejects_stale_offsets(tmp_path) -> None:
    store = UploadSessionStore(tmp_path / "sessions", maximum_bytes=32)
    created = store.create("clip.mp4", 6)
    store.append(created["id"], 0, b"abc")
    with pytest.raises(HTTPException) as error:
        store.append(created["id"], 0, b"def")
    assert error.value.status_code == 409
