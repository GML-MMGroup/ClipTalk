"""Opt-in real CPU smoke test; no downloads or changes to the installed model."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tools.install_talknet import adapted_source


@pytest.mark.skipif(os.environ.get("RUN_TALKNET_SMOKE") != "1", reason="requires a local TalkNet installation")
def test_real_talknet_cpu_adapter_loads_models_and_runs_forward(tmp_path):
    root = Path(__file__).resolve().parents[1]
    installed = root / "data/models/talknet"
    assert (installed / "venv/bin/python").is_file()
    repository = tmp_path / "repository"
    shutil.copytree(installed / "repository", repository,
                    ignore=shutil.ignore_patterns("*.pth", "*.model", "*.pckl", "__pycache__", ".git"))
    for name in ("demoTalkNet.py", "talkNet.py"):
        (repository / name).write_text(adapted_source(name, (repository / name).read_text()))
    detector = Path("model/faceDetector/s3fd/sfd_face.pth")
    (repository / detector).symlink_to(installed / "repository" / detector)
    result = subprocess.run([str(installed / "venv/bin/python"), str(root / "tools/talknet_worker.py"),
                             "--healthcheck", "--verify-model", "--device", "cpu", "--repository", str(repository),
                             "--checkpoint", str(installed / "pretrain_TalkSet.model")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"status": "ready"' in result.stdout
    assert '"device": "cpu"' in result.stdout
