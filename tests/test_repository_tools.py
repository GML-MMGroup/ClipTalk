from pathlib import Path

from tools.check_repository import (
    configuration_errors,
    environment_names_from_example,
    environment_names_from_python,
    filesystem_files,
    repository_errors,
)
from tools.doctor import inspect_environment


ROOT = Path(__file__).resolve().parents[1]


def requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "--", "-r")):
            continue
        name = line.split(";", 1)[0]
        for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
            name = name.split(separator, 1)[0]
        names.add(name.strip().lower().replace("_", "-"))
    return names


def test_cpu_and_gpu_manifests_cover_direct_runtime_dependencies() -> None:
    manifests = sorted(path.name for path in ROOT.glob("requirements*.txt"))
    assert manifests == ["requirements-cpu.txt", "requirements-gpu.txt"]
    shared = {
        "fastapi", "uvicorn", "httpx", "python-multipart", "pydantic", "starlette",
        "pillow", "opencv-python-headless", "cryptography", "numpy", "scipy",
        "scikit-learn", "funasr", "faster-whisper", "ctranslate2", "torch",
        "torchaudio", "transformers", "safetensors", "sentencepiece", "paddleocr",
    }
    assert shared <= requirement_names(ROOT / "requirements-cpu.txt")
    assert shared <= requirement_names(ROOT / "requirements-gpu.txt")
    assert "paddlepaddle" in requirement_names(ROOT / "requirements-cpu.txt")
    assert "paddlepaddle-gpu" in requirement_names(ROOT / "requirements-gpu.txt")


def test_environment_example_covers_runtime_settings() -> None:
    assert configuration_errors(ROOT) == []
    names = environment_names_from_example(ROOT / ".env.example")
    assert environment_names_from_python(ROOT / "app" / "config.py") <= names
    assert {"HIGHLIGHT_LOG_FILE", "CONTENT_SEARCH_DIALOGUE_V2"} <= names


def test_doctor_report_never_exposes_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("VISION_API_KEY", "never-print-this-secret-value")
    monkeypatch.setenv("VISION_MODEL", "test-model")
    monkeypatch.setenv("VISION_BASE_URL", "https://vision.example/v1")
    report = inspect_environment("visual")
    assert "never-print-this-secret-value" not in str(report)
    assert {"profile", "ready", "blockers", "warnings", "checks"} <= set(report)


def test_filesystem_snapshot_scan_prunes_runtime_and_dependency_data(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "private.mp4").write_bytes(b"private")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "bundle.js").write_text("large", encoding="utf-8")
    assert filesystem_files(tmp_path) == ["app/main.py"]


def test_deployment_mode_allows_local_runtime_artifacts_without_weakening_source_mode(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "config.py").write_text("import os\nos.environ.get('HIGHLIGHT_PORT')\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("HIGHLIGHT_PORT=5180\n", encoding="utf-8")
    (tmp_path / ".env").write_text("HIGHLIGHT_PORT=5191\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "vlm-highlight.log").write_text("runtime", encoding="utf-8")
    assert repository_errors(tmp_path, mode="deployment") == []
    source_errors = repository_errors(tmp_path, mode="source")
    assert any("真实环境文件" in error for error in source_errors)
    assert any("运行目录" in error for error in source_errors)
