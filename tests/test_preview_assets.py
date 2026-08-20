from __future__ import annotations

import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.preview_assets import PreviewAssetPaths, PreviewAssetService, PreviewProxyScheduler


class ImmediateExecutor:
    def submit(self, fn):
        future: Future = Future()
        try:
            future.set_result(fn())
        except Exception as error:
            future.set_exception(error)
        return future


def make_service(root: Path) -> PreviewAssetService:
    return PreviewAssetService(
        data_root=root,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        source_lock=threading.Lock(),
        output_lock=threading.Lock(),
        browser_lock=threading.Lock(),
    )


def test_source_identity_distinguishes_truncated_duration_and_sanitizes_path(tmp_path: Path) -> None:
    job = {
        "id": "job_1",
        "sourceHash": "../same source",
        "sourceValidation": {"status": "truncated", "effectiveDuration": 12.3456},
    }
    identity = PreviewAssetPaths.source_identity(job)
    assert identity == "../same source-effective-12346"
    assert PreviewAssetPaths(tmp_path).source_proxy(identity).name == "proxy-samesource-effective-12346.mp4"


def test_scheduler_deduplicates_and_applies_failure_cooldown() -> None:
    now = [100.0]
    calls: list[str] = []

    def prepare(job_id: str) -> None:
        calls.append(job_id)
        raise RuntimeError("proxy failed")

    scheduler = PreviewProxyScheduler(
        executor=ImmediateExecutor(),
        prepare=prepare,
        cooldown_seconds=10,
        clock=lambda: now[0],
    )
    assert scheduler.schedule("job_1", "source_1") is True
    assert scheduler.failure("source_1") == "proxy failed"
    assert scheduler.schedule("job_1", "source_1") is False
    now[0] += 11
    assert scheduler.failure("source_1") is None
    assert scheduler.schedule("job_1", "source_1") is True
    assert calls == ["job_1", "job_1"]


def test_long_truncated_source_uses_effective_duration_for_proxy(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    job = {
        "id": "job_1",
        "sourceHash": "source_1",
        "sourcePath": str(source),
        "videoInfo": {"duration": 4200},
        "sourceValidation": {"status": "truncated", "effectiveDuration": 4200},
    }

    def create(_source, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"proxy")

    with (
        patch("app.preview_assets.probe_video", return_value=SimpleNamespace(duration=7200, has_audio=True)),
        patch("app.preview_assets.create_preview_proxy", side_effect=create) as create_mock,
    ):
        output = make_service(tmp_path).prepare_source(job)
    assert output.read_bytes() == b"proxy"
    assert create_mock.call_args.kwargs["maximum_dimension"] == 720
    assert create_mock.call_args.kwargs["maximum_duration"] == 4200


def test_output_preview_reuses_cache_and_confines_filename(tmp_path: Path) -> None:
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    (output_directory / "clip.mp4").write_bytes(b"video")
    job = {
        "id": "job_1",
        "outputDirectory": str(output_directory),
        "workDirectory": str(tmp_path / "work"),
    }

    def create(_source, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"preview")

    with (
        patch("app.preview_assets.probe_video", return_value=SimpleNamespace(duration=10, has_audio=False)),
        patch("app.preview_assets.create_preview_proxy", side_effect=create) as create_mock,
    ):
        service = make_service(tmp_path)
        first = service.prepare_output(job, "../clip.mp4")
        second = service.prepare_output(job, "clip.mp4")
    assert first == second == tmp_path / "work" / "output-previews" / "clip.mp4"
    assert create_mock.call_count == 1


def test_browser_preview_uses_smaller_dimension_for_long_media(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    job = {
        "id": "job_1",
        "sourcePath": str(source),
        "workDirectory": str(tmp_path / "work"),
        "outputDirectory": str(tmp_path / "outputs"),
    }

    def create(_source, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"webm")

    with (
        patch("app.preview_assets.probe_video", return_value=SimpleNamespace(duration=1900, has_audio=True)),
        patch("app.preview_assets.create_webm_preview", side_effect=create) as create_mock,
    ):
        output = make_service(tmp_path).prepare_browser(job)
    assert output.name == "source.webm"
    assert create_mock.call_args.kwargs["maximum_dimension"] == 720
