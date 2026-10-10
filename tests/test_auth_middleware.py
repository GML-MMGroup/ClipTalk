from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app import main
from app.security import is_loopback_client_address

REMOTE_PEER = "203.0.113.9"
SECURE_TOKEN = "a-secure-token-value"


@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", True),
    ("::1", True),
    ("localhost", True),
    ("10.0.0.5", False),
    ("203.0.113.9", False),
    ("", False),
    (None, False),
    ("not-an-address", False),
])
def test_loopback_client_detection(host: str | None, expected: bool) -> None:
    assert is_loopback_client_address(host) is expected


async def _request_async(host: str, path: str, **kwargs: Any) -> httpx.Response:
    """Issue a request whose real TCP peer address is ``host``.

    ``httpx.ASGITransport`` writes the address straight into the ASGI scope, so
    the middleware sees it exactly as uvicorn would report a remote client.
    """
    transport = httpx.ASGITransport(app=main.app, client=(host, 51234))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver",
    ) as client:
        return await client.get(path, **kwargs)


def _get(host: str, **kwargs: Any) -> httpx.Response:
    return asyncio.run(_request_async(host, "/api/jobs", **kwargs))


def _with_token(token: str):
    """Swap the frozen Settings for one carrying the given access token."""
    return patch.object(main, "settings", replace(main.settings, access_token=token))


def test_remote_client_is_rejected_when_no_token_is_configured() -> None:
    with _with_token(""):
        response = _get(REMOTE_PEER)
    assert response.status_code == 401
    assert "invalid_access_token" in response.text


def test_loopback_client_is_served_when_no_token_is_configured() -> None:
    with _with_token(""):
        response = _get("127.0.0.1")
    assert response.status_code != 401


def test_remote_client_is_rejected_with_a_wrong_token() -> None:
    with _with_token(SECURE_TOKEN):
        response = _get(REMOTE_PEER, headers={"X-Highlight-Token": "wrong-token"})
    assert response.status_code == 401


def test_remote_client_is_served_with_a_valid_token() -> None:
    with _with_token(SECURE_TOKEN):
        response = _get(REMOTE_PEER, headers={"X-Highlight-Token": SECURE_TOKEN})
    assert response.status_code != 401


def test_forwarded_for_header_cannot_spoof_a_loopback_peer() -> None:
    """A spoofable header must never be trusted for the loopback exemption."""
    with _with_token(""):
        response = _get(REMOTE_PEER, headers={"X-Forwarded-For": "127.0.0.1"})
    assert response.status_code == 401


def test_health_endpoint_stays_reachable_without_credentials() -> None:
    with _with_token(SECURE_TOKEN):
        response = asyncio.run(_request_async(REMOTE_PEER, "/api/health"))
    assert response.status_code != 401


def test_deployment_refuses_remote_bind_without_a_token() -> None:
    """The startup guard itself must stay fail-closed after the switch removal."""
    from app.security import SecurityConfigurationError, validate_deployment_access

    validate_deployment_access("127.0.0.1", "")
    with pytest.raises(SecurityConfigurationError):
        validate_deployment_access("0.0.0.0", "")
