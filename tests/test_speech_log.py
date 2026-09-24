from __future__ import annotations

from app.speech import _rotate_sensevoice_worker_log
from app.speech_worker import _sensevoice_runtime_config


def test_sensevoice_worker_log_rotation_keeps_a_bounded_tail(tmp_path) -> None:
    worker_directory = tmp_path / "speech-worker"
    worker_directory.mkdir()
    log_path = worker_directory / "worker.log"
    log_path.write_bytes(b"0123456789abcdef")

    assert _rotate_sensevoice_worker_log(
        worker_directory, maximum_bytes=10, backup_bytes=6,
    )
    assert log_path.read_bytes() == b""
    assert (worker_directory / "worker.log.1").read_bytes() == b"abcdef"


def test_sensevoice_worker_log_rotation_leaves_small_log_untouched(tmp_path) -> None:
    worker_directory = tmp_path / "speech-worker"
    worker_directory.mkdir()
    log_path = worker_directory / "worker.log"
    log_path.write_bytes(b"small")

    assert not _rotate_sensevoice_worker_log(
        worker_directory, maximum_bytes=10, backup_bytes=6,
    )
    assert log_path.read_bytes() == b"small"
    assert not (worker_directory / "worker.log.1").exists()


def test_sensevoice_worker_ignores_stale_persisted_metadata(tmp_path) -> None:
    config = _sensevoice_runtime_config({
        "model_name": "iic/SenseVoiceSmall",
        "device": "cpu",
        "vad_model": "fsmn-vad",
        "punc_model": "",
        "spk_model": "cam++",
        "diarization": False,
        "model_cache": str(tmp_path / "models"),
        "worker_directory": str(tmp_path / "speech-worker"),
        "runtime_version": "old",
        "algorithm_version": "legacy",
    })

    assert config["model_cache"] == tmp_path / "models"
    assert "worker_directory" not in config
    assert "runtime_version" not in config
    assert "algorithm_version" not in config
