from __future__ import annotations

import hashlib
import hmac
import ipaddress
import socket
from urllib.parse import urlparse


class SecurityConfigurationError(RuntimeError):
    """Raised when a deployment or outbound endpoint is unsafe by default."""


def is_loopback_bind_host(host: str) -> bool:
    value = str(host or "").strip().lower().strip("[]")
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def validate_deployment_access(host: str, access_token: str) -> None:
    """Refuse an externally reachable bind without a meaningful bearer token."""
    if is_loopback_bind_host(host):
        return
    token = str(access_token or "").strip()
    if len(token) < 16:
        raise SecurityConfigurationError(
            "HIGHLIGHT_HOST 不是本机回环地址时，必须配置至少 16 字符的 "
            "HIGHLIGHT_ACCESS_TOKEN"
        )


def session_cookie_value(access_token: str) -> str:
    return hmac.new(
        str(access_token).encode("utf-8"),
        b"cliptalk-browser-session-v1",
        hashlib.sha256,
    ).hexdigest()


def access_token_matches(provided: str | None, expected: str) -> bool:
    value = str(provided or "")
    return bool(value) and hmac.compare_digest(value, str(expected))


def session_cookie_matches(provided: str | None, access_token: str) -> bool:
    value = str(provided or "")
    return bool(value) and hmac.compare_digest(value, session_cookie_value(access_token))


def validate_public_http_endpoint(url: str, *, allow_private: bool = False) -> str:
    """Validate a user-controlled model endpoint before the server connects.

    Custom on-premise model gateways remain possible through the explicit
    HIGHLIGHT_ALLOW_PRIVATE_MODEL_ENDPOINTS opt-in. Public deployments default
    to blocking loopback, private, link-local, reserved and metadata networks.
    """
    normalized = str(url or "").strip().rstrip("/")
    if len(normalized) > 2048:
        raise SecurityConfigurationError("接口地址过长")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SecurityConfigurationError("接口地址必须是有效的 HTTP 或 HTTPS 地址")
    if parsed.username is not None or parsed.password is not None:
        raise SecurityConfigurationError("接口地址不能包含用户名或密码")
    hostname = parsed.hostname.rstrip(".").lower()
    if allow_private:
        return normalized
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise SecurityConfigurationError("默认禁止连接本机或内网模型地址")
    try:
        direct_ip = ipaddress.ip_address(hostname)
    except ValueError:
        direct_ip = None
    if direct_ip is not None:
        addresses = [direct_ip]
    else:
        try:
            resolved = socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as error:
            raise SecurityConfigurationError(f"无法解析模型接口域名：{hostname}") from error
        addresses = []
        for item in resolved:
            try:
                address = ipaddress.ip_address(item[4][0])
            except (ValueError, IndexError):
                continue
            if address not in addresses:
                addresses.append(address)
    if not addresses:
        raise SecurityConfigurationError("模型接口域名没有可用的网络地址")
    if any(not address.is_global for address in addresses):
        raise SecurityConfigurationError("默认禁止连接本机、内网、链路本地或保留网络地址")
    return normalized
