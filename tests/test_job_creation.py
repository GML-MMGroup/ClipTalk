from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.job_creation import (
    parse_job_creation_options,
    persist_upload,
    storage_usage_bytes,
)


def valid_options(**overrides):
    values = {
        "filename": "source.mp4", "task_mode": "highlight", "instruction": "",
        "count": "auto", "target_seconds": "auto", "total_target_seconds": "",
        "theme": "人物反应", "analysis_mode": "audiovisual",
        "recognition_profile": "auto", "force_reanalyze": "true",
        "subtitle_mode": "none", "subtitle_style": "clean",
        "edit_mode": "ai_plan", "structure": "auto", "auto_variant_count": "3",
        "technique_preset": "auto", "allow_speed": "true",
        "allow_transitions": "true", "allow_audio_bridges": "true",
        "allow_cutaways": "true", "allow_silence_compression": "true",
        "allow_cold_open": "false",
    }
    values.update(overrides)
    return parse_job_creation_options(**values)


def test_creation_options_normalize_form_values() -> None:
    options = valid_options(
        count="4", total_target_seconds="30", subtitle_mode="BURN",
        auto_variant_count="2", force_reanalyze="cached", allow_speed="false",
    )
    assert options.count == 4
    assert options.total_seconds == 30
    assert options.target_seconds == 30
    assert options.subtitle_mode == "burn"
    assert options.auto_variant_count == 2
    assert options.force_reanalyze is False
    assert options.technique_policy["allowSpeed"] is False
    assert options.storage_mode == "editable"


def test_creation_options_accept_one_off_storage() -> None:
    assert valid_options(storage_mode="one_off").storage_mode == "one_off"


def test_content_search_options_are_normalized() -> None:
    options = valid_options(
        task_mode="content_extract", instruction="找出产品演示", search_scope_kind="custom",
        search_scope_start="30", search_scope_end="90", search_result_limit="1",
        search_boundary_mode="context", content_auto_generate="true",
        content_exclusions="片头，Speaker 2，片头",
        search_evidence_mode="screen_text", search_allowed_capabilities="ocr",
    )
    assert options.search_scope_kind == "custom"
    assert (options.search_scope_start, options.search_scope_end) == (30.0, 90.0)
    assert options.search_result_limit == 1
    assert options.search_boundary_mode == "context"
    assert options.content_auto_generate is True
    assert options.content_exclusions == ["片头", "Speaker 2"]
    assert options.content_evidence_mode == "screen_text"
    assert options.content_allowed_capabilities == ["ocr"]


def test_content_search_defaults_to_all_reliable_results() -> None:
    options = valid_options(task_mode="content_extract", instruction="找出产品演示")
    assert options.search_result_limit == 12


@pytest.mark.parametrize("overrides,status", [
    ({"filename": "source.txt"}, 400),
    ({"task_mode": "content_extract", "instruction": ""}, 400),
    ({"count": "9"}, 400),
    ({"total_target_seconds": "3"}, 400),
    ({"recognition_profile": "ultra"}, 400),
    ({"auto_variant_count": "5"}, 400),
    ({"search_scope_kind": "unknown"}, 400),
    ({"search_scope_kind": "custom", "search_scope_start": "20", "search_scope_end": "10"}, 400),
    ({"search_result_limit": "5"}, 400),
    ({"search_boundary_mode": "loose"}, 400),
    ({"search_evidence_mode": "everything"}, 400),
    ({"search_allowed_capabilities": "speech,face_id"}, 400),
    ({"storage_mode": "temporary"}, 400),
])
def test_creation_options_reject_invalid_input(overrides, status: int) -> None:
    with pytest.raises(HTTPException) as captured:
        valid_options(**overrides)
    assert captured.value.status_code == status


def test_storage_usage_counts_hardlinks_once(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"123456")
    linked = tmp_path / "linked.bin"
    os.link(source, linked)
    (tmp_path / "other.bin").write_bytes(b"12")
    assert storage_usage_bytes(tmp_path) == 8


class FakeUpload:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.closed = False

    async def read(self, _size: int = -1) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    async def close(self) -> None:
        self.closed = True


def test_persist_upload_hashes_and_validates_size(tmp_path: Path) -> None:
    upload = FakeUpload([b"abc", b"def"])
    destination = tmp_path / "upload.mp4"
    receipt = asyncio.run(persist_upload(
        upload, destination, expected_size_bytes="6", used_storage_bytes=0,
        maximum_upload_bytes=10, maximum_storage_bytes=20,
    ))
    assert receipt.size == 6
    assert receipt.sha256 == "bef57ec7f53a6d40beb640a780a639c83bc29ac8a9816f1fc6c5c6dcd93c4721"
    assert destination.read_bytes() == b"abcdef"
    assert upload.closed is True


def test_persist_upload_removes_partial_file_on_limit_error(tmp_path: Path) -> None:
    upload = FakeUpload([b"12345", b"67890"])
    destination = tmp_path / "upload.mp4"
    with pytest.raises(HTTPException) as captured:
        asyncio.run(persist_upload(
            upload, destination, expected_size_bytes="", used_storage_bytes=0,
            maximum_upload_bytes=6, maximum_storage_bytes=20,
        ))
    assert captured.value.status_code == 413
    assert not destination.exists()
    assert upload.closed is True
