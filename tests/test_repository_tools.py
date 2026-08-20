from pathlib import Path

from tools.check_repository import (
    configuration_errors,
    environment_names_from_example,
    environment_names_from_python,
)
from tools.doctor import inspect_environment


ROOT = Path(__file__).resolve().parents[1]


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
