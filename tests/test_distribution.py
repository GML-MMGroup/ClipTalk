from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app import config
from app.local_capabilities import active_speaker_warning, describe_talknet, local_capabilities
from app.system_api import build_system_router
from tools.install_talknet import REVISION, adapted_source, download_weight, prepare_repository
from tools.launch import agent_matches_credentials, service_ready, stop_owned
from tools.setup import automatic_profile, installation_steps
from tools.talknet_worker import visible_cuda_device


@pytest.fixture
def clean_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "load_env", lambda: None)
    for name in list(os.environ):
        if name.startswith(("HIGHLIGHT_", "VISION_", "ARK_", "LLM_", "AGENT_", "CLIPTALK_")):
            monkeypatch.delenv(name)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


def test_clean_checkout_needs_no_machine_paths(clean_settings):
    settings = config.Settings.from_environment()
    assert settings.host == "127.0.0.1"
    assert settings.port == 5180 and settings.maximum_workers == 1
    assert settings.allow_unauthenticated_remote is False
    assert settings.talknet_worker_python == str(clean_settings / "data/models/talknet/venv/bin/python")
    assert settings.talknet_repository == str(clean_settings / "data/models/talknet/repository")
    assert settings.talknet_checkpoint == str(clean_settings / "data/models/talknet/pretrain_TalkSet.model")
    assert settings.talknet_device == "auto"
    settings.validate_deployment_security()
    capability = local_capabilities(settings)["talknet"]
    assert capability["status"] == "not_installed"
    assert str(clean_settings) not in json.dumps(capability)


def test_existing_overrides_win_and_blank_paths_are_auto(clean_settings, monkeypatch):
    monkeypatch.setenv("HIGHLIGHT_DATA_ROOT", str(clean_settings / "custom-data"))
    monkeypatch.setenv("HIGHLIGHT_TALKNET_PYTHON", "/custom/environment/python")
    monkeypatch.setenv("HIGHLIGHT_TALKNET_REPOSITORY", "relative/repository")
    monkeypatch.setenv("HIGHLIGHT_TALKNET_CHECKPOINT", "")
    monkeypatch.setenv("HIGHLIGHT_TALKNET_DEVICE", "cuda:1")
    settings = config.Settings.from_environment()
    assert settings.talknet_worker_python == "/custom/environment/python"
    assert settings.talknet_repository == str(clean_settings / "relative/repository")
    assert settings.talknet_checkpoint.startswith(str(clean_settings / "custom-data"))
    assert settings.talknet_device == "cuda:1"


def test_ffmpeg_follows_path_without_ignoring_explicit_configuration(clean_settings, monkeypatch):
    monkeypatch.setattr(config.shutil, "which", lambda name: "/custom/bin/ffmpeg" if name == "ffmpeg" else None)
    # 本机 .env 设置了 FFMPEG_BIN，会让该测试变成环境依赖；测 PATH 回退时需屏蔽
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    assert config.Settings.from_environment().ffmpeg == "/custom/bin/ffmpeg"
    monkeypatch.setenv("FFMPEG_BIN", "/missing/chosen/ffmpeg")
    assert config.Settings.from_environment().ffmpeg == "/missing/chosen/ffmpeg"


def test_default_install_contains_talknet_and_both_services(tmp_path):
    steps = installation_steps(tmp_path, "cpu")
    commands = [command for command, _ in steps]
    assert any("tools/install_talknet.py" in command for command in commands)
    assert any(command[:2] == ["npm", "ci"] and "--omit=dev" in command and cwd == tmp_path / "agent-service" for command, cwd in steps)
    assert not any(".env" in argument for command in commands for argument in command)
    (tmp_path / ".venv").mkdir()
    assert not any(command[1:3] == ["-m", "venv"] for command, _ in installation_steps(tmp_path, "gpu"))


def test_cpu_default_without_nvidia_and_driver_gated_gpu(monkeypatch):
    monkeypatch.setattr("tools.setup.shutil.which", lambda _name: None)
    assert automatic_profile() == "cpu"
    monkeypatch.setattr("tools.setup.shutil.which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr("tools.setup.subprocess.check_output", lambda *_args, **_kwargs: "535.104.05\n")
    assert automatic_profile() == "gpu"
    monkeypatch.setattr("tools.setup.subprocess.check_output", lambda *_args, **_kwargs: "510.00\n")
    assert automatic_profile() == "cpu"


def test_device_mapping_respects_container_visible_devices():
    assert visible_cuda_device("auto", "2,5") == "2,5"
    assert visible_cuda_device("cuda:1", "2,5") == "5"
    assert visible_cuda_device("cuda:0", "GPU-abc") == "GPU-abc"
    assert visible_cuda_device("cuda:1", None) == "1"
    with pytest.raises(ValueError):
        visible_cuda_device("cuda:1", "0")
    with pytest.raises(ValueError):
        visible_cuda_device("cuda:0", "-1")
    with pytest.raises(ValueError):
        visible_cuda_device("invalid", None)


def test_upstream_adapter_is_checked_and_idempotent():
    source = "import torch\nmodel = torch.ones(1).cuda()\nvalue = torch.load(path)\n"
    patched = adapted_source("talkNet.py", source)
    assert ".cuda()" not in patched
    assert "map_location=CLIPTALK_DEVICE" in patched
    assert adapted_source("talkNet.py", patched) == patched
    ast.parse(patched)
    with pytest.raises(ValueError):
        adapted_source("talkNet.py", "# unexpected upstream")
    demo = "import torch\nargs = parser.parse_args()\nDET = S3FD(device='cuda')\nx = torch.ones(1).cuda()\nif True:\n\tif True:\n\t\tvisualization(vidTracks, scores, args)\n"
    patched_demo = adapted_source("demoTalkNet.py", demo)
    assert "--noVisualization" in patched_demo
    assert "if not args.noVisualization:" in patched_demo
    assert "S3FD(device=CLIPTALK_DEVICE)" in patched_demo


def test_failed_download_is_not_promoted_or_reported_installed(tmp_path, monkeypatch):
    def fake_run(command):
        Path(command[-1]).write_text("<html>network login required</html>")
    monkeypatch.setattr("tools.install_talknet.run", fake_run)
    target = tmp_path / "model.pth"
    with pytest.raises(RuntimeError, match="下载不完整"):
        download_weight(sys.executable, "model-id", target)
    assert not target.exists()
    target.write_bytes(b"user file")
    with pytest.raises(RuntimeError, match="不会覆盖"):
        download_weight(sys.executable, "model-id", target)
    assert target.read_bytes() == b"user file"


def test_repository_checkout_failure_can_be_retried_without_overwrite(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    attempts = []

    def fake_run(command, **kwargs):
        if command[1] == "clone":
            checkout = Path(command[-1])
            checkout.mkdir()
            (checkout / "marker").write_text("partial source")
            attempts.append(checkout)
        elif len(attempts) == 1:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("tools.install_talknet.run", fake_run)
    monkeypatch.setattr("tools.install_talknet.subprocess.check_output", lambda *args, **kwargs: REVISION)
    with pytest.raises(subprocess.CalledProcessError):
        prepare_repository(repository)
    assert not repository.exists()
    prepare_repository(repository)
    assert len(attempts) == 2
    assert attempts[0].is_dir(), "The incomplete checkout must remain recoverable"
    assert (repository / "marker").is_file()


@pytest.mark.parametrize(("runtime", "status"), [
    ({"status": "degraded", "reason": "talknet_missing:checkpoint"}, "not_installed"),
    ({"status": "degraded", "reason": "talknet_probe_deferred"}, "unchecked"),
    ({"status": "disabled"}, "disabled"),
    ({"status": "ready", "mode": "shadow"}, "disabled"),
    ({"status": "ready", "mode": "primary", "device": "cpu"}, "available"),
    ({"status": "degraded", "reason": "sensitive path and raw failure"}, "unavailable"),
])
def test_capability_status_is_truthful_and_redacts_internal_errors(runtime, status):
    result = describe_talknet(runtime)
    assert result["status"] == status
    assert "sensitive path" not in json.dumps(result)
    if status != "available":
        assert "不能保证" in result["impact"]
        assert "逐段核对" in active_speaker_warning(runtime)
    else:
        assert active_speaker_warning(runtime) == ""
        assert "CPU" in result["detail"]


def test_explicit_capability_route_is_separate_from_fast_health():
    router = build_system_router(health=lambda: {}, runtime_metrics=lambda: {}, local_capabilities=lambda: {})
    assert any(route.path == "/api/capabilities/local" for route in router.routes)


def test_launcher_never_trusts_an_unrelated_healthy_port(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.launch.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unavailable")))
    assert not service_ready("http://127.0.0.1/health", "cliptalk")
    monkeypatch.delenv("CLIPTALK_AGENT_SERVICE_TOKEN", raising=False)
    assert not agent_matches_credentials("http://127.0.0.1", SimpleNamespace(data_root=tmp_path))


def test_launcher_only_stops_processes_it_was_given():
    calls = []
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: calls.append("terminate"), wait=lambda **_kwargs: calls.append("wait"))
    stop_owned(process)
    assert calls == ["terminate", "wait"]


def test_dry_run_does_not_create_environment_or_download():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run([sys.executable, str(root / "tools/setup.py"), "--dry-run", "--profile", "cpu"], capture_output=True, text=True, check=True)
    assert "install_talknet.py" in completed.stdout
    assert "npm ci" in completed.stdout
    assert "TalkNet 默认包含" in completed.stdout


def test_docker_default_installs_models_outside_data_volume():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "RUN python tools/install_talknet.py" in dockerfile
    assert "--data-root /opt/cliptalk-models" in dockerfile
    assert "HIGHLIGHT_TALKNET_PYTHON=/opt/cliptalk-models" in dockerfile
