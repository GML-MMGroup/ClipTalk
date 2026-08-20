from __future__ import annotations

import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.ark_client import VisionRequestError
from app.security import (
    SecurityConfigurationError,
    access_token_matches,
    session_cookie_matches,
    session_cookie_value,
    validate_deployment_access,
    validate_public_http_endpoint,
)
from app.vision_settings import LlmConfigurationStore, VisionConfigurationStore


def test_public_bind_requires_a_meaningful_access_token() -> None:
    validate_deployment_access("127.0.0.1", "")
    validate_deployment_access("::1", "")
    with pytest.raises(SecurityConfigurationError, match="HIGHLIGHT_ACCESS_TOKEN"):
        validate_deployment_access("0.0.0.0", "")
    with pytest.raises(SecurityConfigurationError, match="至少 16 字符"):
        validate_deployment_access("0.0.0.0", "too-short")
    validate_deployment_access("0.0.0.0", "a-secure-token-value")


def test_browser_session_cookie_does_not_contain_the_access_token() -> None:
    token = "a-secure-token-value"
    cookie = session_cookie_value(token)
    assert token not in cookie
    assert access_token_matches(token, token)
    assert not access_token_matches("wrong", token)
    assert session_cookie_matches(cookie, token)
    assert not session_cookie_matches(cookie, "another-secure-token")


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/v1",
    "http://169.254.169.254/latest/meta-data",
    "http://10.1.2.3/v1",
    "http://[::1]/v1",
    "http://localhost:8000/v1",
])
def test_model_endpoint_blocks_non_public_addresses(url: str) -> None:
    with pytest.raises(SecurityConfigurationError):
        validate_public_http_endpoint(url)


def test_model_endpoint_blocks_dns_resolving_to_private_network() -> None:
    result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.5", 443))]
    with patch("app.security.socket.getaddrinfo", return_value=result):
        with pytest.raises(SecurityConfigurationError, match="内网"):
            validate_public_http_endpoint("https://models.example/v1")


def test_model_endpoint_accepts_public_network_and_explicit_private_opt_in() -> None:
    result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    with patch("app.security.socket.getaddrinfo", return_value=result):
        assert validate_public_http_endpoint("https://models.example/v1/") == "https://models.example/v1"
    assert validate_public_http_endpoint("http://127.0.0.1:8000/v1", allow_private=True).endswith("/v1")


def test_vision_store_requires_key_again_when_endpoint_changes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = VisionConfigurationStore(Path(directory) / "vision.json", {
            "provider": "openai_compatible", "apiKey": "", "model": "",
            "baseUrl": "", "thinkingType": "", "responseFormat": "json_object",
            "timeoutSeconds": 90,
        })
        store.save(
            provider="openai_compatible", api_key="first-secret", model="vlm",
            base_url="https://first.example/v1", thinking_type="",
            response_format="json_object",
        )
        with pytest.raises(VisionRequestError, match="重新填写 API Key"):
            store.save(
                provider="openai_compatible", api_key="", model="vlm",
                base_url="https://second.example/v1", thinking_type="",
                response_format="json_object",
            )


def test_llm_store_requires_key_again_when_endpoint_changes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = LlmConfigurationStore(Path(directory) / "llm.json", {
            "mode": "independent", "provider": "openai_compatible", "apiKey": "",
            "model": "", "baseUrl": "", "thinkingType": "",
            "responseFormat": "json_object", "timeoutSeconds": 60,
        })
        store.save(
            reuse_vision=False, provider="openai_compatible", api_key="first-secret",
            model="planner", base_url="https://first.example/v1", thinking_type="",
            response_format="json_object",
        )
        with pytest.raises(VisionRequestError, match="重新填写 API Key"):
            store.save(
                reuse_vision=False, provider="openai_compatible", api_key="",
                model="planner", base_url="https://second.example/v1", thinking_type="",
                response_format="json_object",
            )
