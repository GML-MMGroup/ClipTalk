from __future__ import annotations

import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.settings_api import build_settings_router
from app.vision_settings import LlmConfigurationStore, VisionConfigurationStore
from app.setup_readiness import agent_probe_ready, save_agent_probe


def _client(directory: str, *, allow_private: bool = False, **options) -> TestClient:
    vision = VisionConfigurationStore(Path(directory) / "vision.json", {
        "provider": "openai_compatible", "apiKey": "", "model": "",
        "baseUrl": "", "thinkingType": "", "responseFormat": "json_object",
        "timeoutSeconds": 90,
    })
    llm = LlmConfigurationStore(Path(directory) / "llm.json", {
        "mode": "reuse_vision", "provider": "openai_compatible", "apiKey": "",
        "model": "", "baseUrl": "", "thinkingType": "",
        "responseFormat": "json_object", "timeoutSeconds": 60,
    })
    app = FastAPI()
    app.include_router(build_settings_router(
        vision_store=vision,
        llm_store=llm,
        allow_private_model_endpoints=allow_private,
        **options,
    ))
    return TestClient(app)


@pytest.mark.parametrize("failure", ["unsupported", "unavailable"])
def test_effective_probe_reuses_model_and_failed_retest_invalidates_success(tmp_path, failure):
    model = {"provider": "openai_compatible", "apiKey": "test-only-key", "model": "shared-model",
             "baseUrl": "https://example.invalid/v1", "configSource": "llm_fallback"}
    record = tmp_path / "probe.json"
    calls = []
    def probe(selected):
        calls.append(selected.copy())
        if len(calls) == 1:
            return {"toolCalling": True, "piVersion": "test"}
        if failure == "unavailable":
            raise RuntimeError("test service unavailable")
        return {"toolCalling": False}
    client = _client(str(tmp_path), agent_store=object(), agent_probe=probe,
                     effective_agent_model=lambda: model.copy(), agent_probe_record=record)
    assert client.post("/api/settings/agent/probe-effective").status_code == 200
    assert agent_probe_ready(record, model)
    assert client.post("/api/settings/agent/probe-effective").status_code == 400
    assert not agent_probe_ready(record, model)
    assert calls == [model, model]
    assert not (tmp_path / "llm.json").exists(), "Testing reuse must not save independent settings"
    assert "test-only-key" not in record.read_text()


def test_failed_probe_does_not_clear_another_models_record(tmp_path):
    old = {"apiKey": "test-only", "model": "old", "baseUrl": "https://example.invalid/v1"}
    current = {**old, "model": "current"}
    record = tmp_path / "probe.json"
    def probe(_):
        save_agent_probe(record, current, {"toolCalling": True})
        raise RuntimeError("old probe finished late")
    client = _client(str(tmp_path), agent_store=object(), agent_probe=probe,
                     effective_agent_model=lambda: old.copy(), agent_probe_record=record)
    assert client.post("/api/settings/agent/probe-effective").status_code == 400
    assert agent_probe_ready(record, current)


def test_settings_router_keeps_existing_public_paths() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = _client(directory)
        assert client.get("/api/settings/vision").status_code == 200
        assert client.get("/api/settings/llm").status_code == 200


def test_settings_router_rejects_private_model_endpoint() -> None:
    with tempfile.TemporaryDirectory() as directory:
        response = _client(directory).post("/api/settings/vision", json={
            "provider": "openai_compatible",
            "apiKey": "secret",
            "model": "vlm",
            "baseUrl": "http://169.254.169.254/latest/meta-data",
        })
        assert response.status_code == 400
        assert "禁止" in response.json()["detail"]


def test_settings_router_does_not_send_saved_key_to_changed_endpoint() -> None:
    public_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    with tempfile.TemporaryDirectory() as directory, patch(
        "app.security.socket.getaddrinfo", return_value=public_dns,
    ):
        client = _client(directory)
        saved = client.post("/api/settings/vision", json={
            "provider": "openai_compatible",
            "apiKey": "saved-secret",
            "model": "vlm",
            "baseUrl": "https://first.example/v1",
        })
        assert saved.status_code == 200
        response = client.post("/api/settings/vision", json={
            "provider": "openai_compatible",
            "apiKey": "",
            "model": "vlm",
            "baseUrl": "https://second.example/v1",
        })
        assert response.status_code == 400
        assert "重新填写 API Key" in response.json()["detail"]
