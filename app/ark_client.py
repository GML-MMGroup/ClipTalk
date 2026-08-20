from __future__ import annotations

import base64
import json
import mimetypes
import re
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx


class VisionRequestError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


# Backwards-compatible import for saved integrations and existing callers.
ArkRequestError = VisionRequestError


@runtime_checkable
class VisionModelClient(Protocol):
    """Small provider-neutral contract used by the highlight pipeline."""

    model: str

    def cancel(self) -> None: ...

    def analyze_image(
        self,
        prompt: str,
        image_path: Path,
        *,
        maximum_tokens: int = 2200,
        system_prompt: str = "",
    ) -> dict[str, Any]: ...

    def analyze_video(
        self,
        prompt: str,
        video_path: Path,
        *,
        maximum_tokens: int = 2200,
        system_prompt: str = "",
    ) -> dict[str, Any]: ...

    def complete_json(
        self,
        prompt: str,
        *,
        maximum_tokens: int = 2200,
        system_prompt: str = "",
    ) -> dict[str, Any]: ...


def parse_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, re.DOTALL | re.IGNORECASE)
    if fenced:
        value = fenced.group(1)
    else:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            value = value[start:end + 1]
    try:
        # Vision models occasionally put a literal newline/tab inside a JSON
        # string even when explicitly asked for JSON. Python's non-strict mode
        # accepts those control characters without weakening structural checks.
        parsed = json.loads(value, strict=False)
    except json.JSONDecodeError as error:
        raise ArkRequestError(f"视觉模型没有返回合法 JSON：{error}", retryable=True) from error
    if not isinstance(parsed, dict):
        raise ArkRequestError("视觉模型返回值必须是 JSON 对象")
    return parsed


class OpenAICompatibleVisionClient:
    """Vision client for multimodal OpenAI Chat Completions compatible APIs.

    Provider-specific extensions are opt-in. This keeps the request accepted by
    strict compatible gateways while allowing Ark's thinking switch when used.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        provider_name: str = "视觉模型服务",
        thinking_type: str = "",
        response_format: str = "json_object",
        timeout_seconds: float = 90.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        normalized_url = base_url.rstrip("/")
        self.url = normalized_url if normalized_url.endswith("/chat/completions") else f"{normalized_url}/chat/completions"
        self.provider_name = provider_name.strip() or "视觉模型服务"
        self.thinking_type = thinking_type.strip().lower()
        self.response_format = response_format.strip().lower()
        self.timeout_seconds = timeout_seconds
        self._active_lock = threading.Lock()
        self._active_client: httpx.Client | None = None
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._active_lock:
            client = self._active_client
        if client is not None:
            try:
                client.close()
            except RuntimeError:
                pass

    def analyze_image(
        self,
        prompt: str,
        image_path: Path,
        *,
        maximum_tokens: int = 2200,
        system_prompt: str = "",
    ) -> dict[str, Any]:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            },
        ]
        return self._complete(content, maximum_tokens=maximum_tokens, system_prompt=system_prompt)

    def analyze_video(
        self,
        prompt: str,
        video_path: Path,
        *,
        maximum_tokens: int = 2200,
        system_prompt: str = "",
    ) -> dict[str, Any]:
        """Send the rendered review proxy as real dynamic video evidence.

        OpenAI-compatible multimodal gateways that do not implement
        ``video_url`` return a normal request error; callers then fall back to
        the labelled contact sheet without losing the review job.
        """
        encoded = base64.b64encode(video_path.read_bytes()).decode("ascii")
        mime = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
        content = [
            {"type": "text", "text": prompt},
            {"type": "video_url", "video_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]
        return self._complete(content, maximum_tokens=maximum_tokens, system_prompt=system_prompt)

    def complete_json(
        self,
        prompt: str,
        *,
        maximum_tokens: int = 2200,
        system_prompt: str = "",
    ) -> dict[str, Any]:
        return self._complete(prompt, maximum_tokens=maximum_tokens, system_prompt=system_prompt)

    def _complete(
        self,
        content: str | list[dict[str, Any]],
        *,
        maximum_tokens: int,
        system_prompt: str = "",
    ) -> dict[str, Any]:
        if self._cancelled.is_set():
            raise ArkRequestError(f"{self.provider_name}请求已取消")
        messages: list[dict[str, Any]] = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": content})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": maximum_tokens,
        }
        if self.response_format in {"json_object", "json"}:
            payload["response_format"] = {"type": "json_object"}
        if self.thinking_type in {"disabled", "enabled", "auto"}:
            payload["thinking"] = {"type": self.thinking_type}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        for attempt in range(2):
            if self._cancelled.is_set():
                raise ArkRequestError(f"{self.provider_name}请求已取消")
            try:
                with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds, connect=20.0)) as client:
                    with self._active_lock:
                        self._active_client = client
                    try:
                        response = client.post(self.url, headers=headers, json=payload)
                    finally:
                        with self._active_lock:
                            if self._active_client is client:
                                self._active_client = None
                if response.status_code >= 400:
                    detail = response.text[:800]
                    if response.status_code in (408, 429) or response.status_code >= 500:
                        raise ArkRequestError(
                            f"{self.provider_name}暂时不可用（HTTP {response.status_code}）：{detail}",
                            retryable=True,
                        )
                    raise ArkRequestError(f"{self.provider_name}请求失败（HTTP {response.status_code}）：{detail}")
                body = response.json()
                message = body.get("choices", [{}])[0].get("message", {})
                answer = message.get("content", "")
                if isinstance(answer, list):
                    answer = "".join(str(item.get("text", "")) for item in answer if isinstance(item, dict))
                if not isinstance(answer, str) or not answer.strip():
                    raise ArkRequestError(f"{self.provider_name}返回了空结果", retryable=True)
                parsed = parse_json_object(answer)
                parsed["_usage"] = body.get("usage", {})
                return parsed
            except ArkRequestError as error:
                last_error = error
                if self._cancelled.is_set():
                    raise ArkRequestError(f"{self.provider_name}请求已取消") from error
                if not error.retryable or attempt == 1:
                    raise
                if self._cancelled.wait(1.5 * (attempt + 1)):
                    raise ArkRequestError(f"{self.provider_name}请求已取消") from error
            except (httpx.HTTPError, ValueError) as error:
                last_error = error
                if self._cancelled.is_set():
                    raise ArkRequestError(f"{self.provider_name}请求已取消") from error
                if attempt == 1:
                    break
                if self._cancelled.wait(1.5 * (attempt + 1)):
                    raise ArkRequestError(f"{self.provider_name}请求已取消") from error
        raise ArkRequestError(str(last_error or f"{self.provider_name}请求失败"))


class ArkVisionClient(OpenAICompatibleVisionClient):
    """Legacy Ark preset retained for backwards compatibility."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        thinking_type: str = "disabled",
        timeout_seconds: float = 90.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_name="火山方舟",
            thinking_type=thinking_type,
            response_format="json_object",
            timeout_seconds=timeout_seconds,
        )


def vision_provider_label(provider: str) -> str:
    value = provider.strip().lower().replace("-", "_")
    return {
        "ark": "火山方舟",
        "volcengine_ark": "火山方舟",
        "openai": "OpenAI",
        "openai_compatible": "OpenAI 兼容接口",
    }.get(value, provider.strip() or "OpenAI 兼容接口")


def create_vision_client(
    *,
    provider: str,
    api_key: str,
    model: str,
    base_url: str,
    thinking_type: str = "",
    response_format: str = "json_object",
    timeout_seconds: float = 90.0,
) -> VisionModelClient:
    normalized_provider = provider.strip().lower().replace("-", "_") or "openai_compatible"
    if normalized_provider in {"ark", "volcengine_ark"}:
        return ArkVisionClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            thinking_type=thinking_type or "disabled",
            timeout_seconds=timeout_seconds,
        )
    return OpenAICompatibleVisionClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_name=vision_provider_label(normalized_provider),
        thinking_type=thinking_type,
        response_format=response_format,
        timeout_seconds=timeout_seconds,
    )


class AnthropicCompatibleClient:
    """Minimal Anthropic Messages client for compatible gateways such as Ark."""

    def __init__(self, *, auth_token: str, model: str, base_url: str, timeout_seconds: float = 60.0) -> None:
        self.auth_token = auth_token
        self.model = model
        self.url = f"{base_url.rstrip('/')}/v1/messages"
        self.timeout_seconds = timeout_seconds
        self._active_lock = threading.Lock()
        self._active_client: httpx.Client | None = None
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._active_lock:
            client = self._active_client
        if client is not None:
            try:
                client.close()
            except RuntimeError:
                pass

    def complete_json(self, prompt: str, *, maximum_tokens: int = 2200, system_prompt: str = "") -> dict[str, Any]:
        if self._cancelled.is_set():
            raise ArkRequestError("Anthropic 兼容接口请求已取消")
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": maximum_tokens,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt.strip():
            payload["system"] = system_prompt.strip()
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "x-api-key": self.auth_token,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(2):
            if self._cancelled.is_set():
                raise ArkRequestError("Anthropic 兼容接口请求已取消")
            try:
                with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds, connect=20.0)) as client:
                    with self._active_lock:
                        self._active_client = client
                    try:
                        response = client.post(self.url, headers=headers, json=payload)
                    finally:
                        with self._active_lock:
                            if self._active_client is client:
                                self._active_client = None
                if response.status_code >= 400:
                    detail = response.text[:800]
                    if response.status_code in (408, 429) or response.status_code >= 500:
                        raise ArkRequestError(f"Anthropic 兼容接口暂时不可用（HTTP {response.status_code}）：{detail}", retryable=True)
                    raise ArkRequestError(f"Anthropic 兼容接口请求失败（HTTP {response.status_code}）：{detail}")
                body = response.json()
                content = body.get("content", [])
                answer = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
                if not answer.strip():
                    raise ArkRequestError("Anthropic 兼容接口返回了空结果", retryable=True)
                parsed = parse_json_object(answer)
                parsed["_usage"] = body.get("usage", {})
                return parsed
            except ArkRequestError as error:
                last_error = error
                if self._cancelled.is_set():
                    raise ArkRequestError("Anthropic 兼容接口请求已取消") from error
                if not error.retryable or attempt == 1:
                    raise
                if self._cancelled.wait(1.5 * (attempt + 1)):
                    raise ArkRequestError("Anthropic 兼容接口请求已取消") from error
            except (httpx.HTTPError, ValueError) as error:
                last_error = error
                if self._cancelled.is_set():
                    raise ArkRequestError("Anthropic 兼容接口请求已取消") from error
                if attempt == 1:
                    break
                if self._cancelled.wait(1.5 * (attempt + 1)):
                    raise ArkRequestError("Anthropic 兼容接口请求已取消") from error
        raise ArkRequestError(str(last_error or "Anthropic 兼容接口请求失败"))
