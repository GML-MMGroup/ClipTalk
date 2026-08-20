from __future__ import annotations

import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.settings_api import build_settings_router
from app.vision_settings import LlmConfigurationStore, VisionConfigurationStore


def _client(directory: str, *, allow_private: bool = False) -> TestClient:
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
    ))
    return TestClient(app)


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
