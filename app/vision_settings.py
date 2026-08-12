from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import httpx

from .ark_client import VisionRequestError, vision_provider_label


PROVIDER_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "ark",
        "name": "火山方舟",
        "description": "豆包及方舟接入点",
        "baseUrl": "https://ark.cn-beijing.volces.com/api/v3",
        "baseUrlEditable": False,
        "thinkingSupported": True,
        "responseFormatDefault": "json_object",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "description": "OpenAI 官方多模态模型",
        "baseUrl": "https://api.openai.com/v1",
        "baseUrlEditable": False,
        "thinkingSupported": False,
        "responseFormatDefault": "json_object",
    },
    {
        "id": "openai_compatible",
        "name": "兼容接口",
        "description": "其他兼容 Chat Completions 的服务",
        "baseUrl": "",
        "baseUrlEditable": True,
        "thinkingSupported": True,
        "responseFormatDefault": "json_object",
    },
)


LLM_PROVIDER_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "ark",
        "name": "火山方舟",
        "description": "豆包及方舟文本模型",
        "protocol": "openai",
        "baseUrl": "https://ark.cn-beijing.volces.com/api/v3",
        "baseUrlEditable": False,
        "thinkingSupported": True,
        "responseFormatDefault": "json_object",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "description": "OpenAI 官方文本与推理模型",
        "protocol": "openai",
        "baseUrl": "https://api.openai.com/v1",
        "baseUrlEditable": False,
        "thinkingSupported": False,
        "responseFormatDefault": "json_object",
    },
    {
        "id": "openai_compatible",
        "name": "兼容接口",
        "description": "兼容 Chat Completions 的服务",
        "protocol": "openai",
        "baseUrl": "",
        "baseUrlEditable": True,
        "thinkingSupported": True,
        "responseFormatDefault": "json_object",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "description": "Anthropic 官方 Claude 模型",
        "protocol": "anthropic",
        "baseUrl": "https://api.anthropic.com",
        "baseUrlEditable": False,
        "thinkingSupported": False,
        "responseFormatDefault": "none",
    },
    {
        "id": "anthropic_compatible",
        "name": "Anthropic 兼容接口",
        "description": "兼容 Messages API 的服务",
        "protocol": "anthropic",
        "baseUrl": "",
        "baseUrlEditable": True,
        "thinkingSupported": False,
        "responseFormatDefault": "none",
    },
)


def _provider_definition(provider: str) -> dict[str, Any]:
    normalized = provider.strip().lower().replace("-", "_")
    return next((dict(item) for item in PROVIDER_DEFINITIONS if item["id"] == normalized), {
        "id": normalized or "openai_compatible",
        "name": vision_provider_label(normalized),
        "description": "OpenAI Chat Completions 兼容服务",
        "baseUrl": "",
        "baseUrlEditable": True,
        "thinkingSupported": True,
        "responseFormatDefault": "json_object",
    })


def llm_provider_label(provider: str) -> str:
    normalized = provider.strip().lower().replace("-", "_")
    definition = next((item for item in LLM_PROVIDER_DEFINITIONS if item["id"] == normalized), None)
    return str(definition["name"] if definition else normalized or "兼容接口")


def _llm_provider_definition(provider: str) -> dict[str, Any]:
    normalized = provider.strip().lower().replace("-", "_")
    return next((dict(item) for item in LLM_PROVIDER_DEFINITIONS if item["id"] == normalized), {
        "id": normalized or "openai_compatible",
        "name": llm_provider_label(normalized),
        "description": "兼容文本模型服务",
        "protocol": "openai",
        "baseUrl": "",
        "baseUrlEditable": True,
        "thinkingSupported": True,
        "responseFormatDefault": "json_object",
    })


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return f"{value[:2]}****"
    return f"{value[:4]}****{value[-4:]}"


def _models_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    return f"{value}/models"


def _is_probable_visual_model(model_id: str) -> bool:
    value = model_id.lower()
    excluded = (
        "embedding", "moderation", "whisper", "transcribe", "tts", "speech",
        "realtime", "audio", "image", "sora", "video-generation", "rerank",
    )
    if any(token in value for token in excluded):
        return False
    positive = ("doubao", "vision", "vlm", "multimodal", "gpt-4", "gpt-5", "o3", "o4")
    return any(token in value for token in positive)


def _is_probable_text_model(model_id: str) -> bool:
    value = model_id.lower()
    excluded = (
        "embedding", "moderation", "whisper", "transcribe", "tts", "speech",
        "realtime", "audio", "image-generation", "gpt-image", "sora",
        "video-generation", "rerank", "3d-generation",
    )
    return not any(token in value for token in excluded)


def discover_models(*, api_key: str, base_url: str, provider: str, timeout_seconds: float = 20.0) -> list[dict[str, Any]]:
    if not api_key.strip():
        raise VisionRequestError("请先填写 API Key")
    if not base_url.strip():
        raise VisionRequestError("请先填写接口地址")
    url = _models_url(base_url)
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key.strip()}", "Accept": "application/json"},
            timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds)),
        )
    except httpx.HTTPError as error:
        raise VisionRequestError(f"无法连接{vision_provider_label(provider)}：{error}", retryable=True) from error
    if response.status_code >= 400:
        detail = response.text[:500]
        if response.status_code in {401, 403}:
            raise VisionRequestError("API Key 验证失败，请检查密钥或账号权限")
        raise VisionRequestError(f"模型列表读取失败（HTTP {response.status_code}）：{detail}", retryable=response.status_code >= 500)
    try:
        body = response.json()
    except ValueError as error:
        raise VisionRequestError("模型服务没有返回合法的模型列表") from error
    raw_models = body.get("data") if isinstance(body, dict) else body
    if not isinstance(raw_models, list) and isinstance(body, dict):
        raw_models = body.get("models")
    if not isinstance(raw_models, list):
        raise VisionRequestError("模型服务返回格式不兼容，未找到模型数组")
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    has_explicit_modalities = any(
        isinstance(raw, dict)
        and isinstance(raw.get("modalities"), dict)
        and isinstance(raw["modalities"].get("input_modalities"), list)
        for raw in raw_models
    )
    for raw in raw_models:
        model_id = str(raw.get("id") or raw.get("name") or "").strip() if isinstance(raw, dict) else str(raw).strip()
        if not model_id or model_id in seen:
            continue
        raw_status = str(raw.get("status") or "") if isinstance(raw, dict) else ""
        if raw_status.lower() == "shutdown":
            continue
        modalities = raw.get("modalities") if isinstance(raw, dict) and isinstance(raw.get("modalities"), dict) else {}
        input_modalities = [str(item).lower() for item in modalities.get("input_modalities", []) if item]
        output_modalities = [str(item).lower() for item in modalities.get("output_modalities", []) if item]
        supports_image = "image" in input_modalities
        supports_video = "video" in input_modalities
        task_types = [str(item).lower() for item in (raw.get("task_type") or [])] if isinstance(raw, dict) else []
        domain = str(raw.get("domain") or "").lower() if isinstance(raw, dict) else ""
        explicit_visual = supports_image \
            and (not output_modalities or "text" in output_modalities) \
            and (not task_types or "visualquestionanswering" in task_types or domain == "vlm")
        probable_visual = explicit_visual if has_explicit_modalities else _is_probable_visual_model(model_id)
        # Ark and some compatible services publish exact modality metadata.
        # When it is available, use it instead of guessing from model names.
        if has_explicit_modalities and not explicit_visual:
            continue
        if not has_explicit_modalities and not probable_visual:
            continue
        features = raw.get("features") if isinstance(raw, dict) and isinstance(raw.get("features"), dict) else {}
        structured = features.get("structured_outputs") if isinstance(features.get("structured_outputs"), dict) else {}
        seen.add(model_id)
        models.append({
            "id": model_id,
            "owner": str(raw.get("owned_by") or raw.get("owner") or "") if isinstance(raw, dict) else "",
            "recommended": probable_visual and raw_status.lower() != "retiring" and not any(token in model_id.lower() for token in ("code", "ui-tars")),
            "supportsImage": supports_image if has_explicit_modalities else None,
            "supportsVideo": supports_video if has_explicit_modalities else None,
            "supportsJson": bool(structured.get("json_object")) if structured else None,
            "status": raw_status,
        })
    if not models:
        raise VisionRequestError("当前账号没有返回可见模型")
    return sorted(models, key=lambda item: (not item["recommended"], item.get("status") == "Retiring", item["id"].lower()))


def discover_llm_models(
    *,
    api_key: str,
    base_url: str,
    provider: str,
    protocol: str = "openai",
    timeout_seconds: float = 20.0,
) -> list[dict[str, Any]]:
    """Read text-capable planning models without mixing in utility models."""
    if not api_key.strip():
        raise VisionRequestError("请先填写 API Key")
    if not base_url.strip():
        raise VisionRequestError("请先填写接口地址")
    normalized_protocol = protocol.strip().lower()
    if normalized_protocol == "anthropic":
        root = base_url.strip().rstrip("/")
        if provider == "anthropic_compatible" and "volces.com" in root and root.endswith("/api/compatible"):
            url = f"{root[:-len('/api/compatible')]}/api/v3/models"
            headers = {"Authorization": f"Bearer {api_key.strip()}", "Accept": "application/json"}
        else:
            url = f"{root}/models" if root.endswith("/v1") else f"{root}/v1/models"
            headers = {
                "x-api-key": api_key.strip(),
                "anthropic-version": "2023-06-01",
                "Accept": "application/json",
            }
    else:
        url = _models_url(base_url)
        headers = {"Authorization": f"Bearer {api_key.strip()}", "Accept": "application/json"}
    try:
        response = httpx.get(
            url,
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds)),
        )
    except httpx.HTTPError as error:
        raise VisionRequestError(f"无法连接{llm_provider_label(provider)}：{error}", retryable=True) from error
    if response.status_code >= 400:
        detail = response.text[:500]
        if response.status_code in {401, 403}:
            raise VisionRequestError("API Key 验证失败，请检查密钥或账号权限")
        raise VisionRequestError(f"模型列表读取失败（HTTP {response.status_code}）：{detail}", retryable=response.status_code >= 500)
    try:
        body = response.json()
    except ValueError as error:
        raise VisionRequestError("模型服务没有返回合法的模型列表") from error
    raw_models = body.get("data") if isinstance(body, dict) else body
    if not isinstance(raw_models, list) and isinstance(body, dict):
        raw_models = body.get("models")
    if not isinstance(raw_models, list):
        raise VisionRequestError("模型服务返回格式不兼容，未找到模型数组")
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_models:
        model_id = str(raw.get("id") or raw.get("name") or "").strip() if isinstance(raw, dict) else str(raw).strip()
        if not model_id or model_id in seen or not _is_probable_text_model(model_id):
            continue
        raw_status = str(raw.get("status") or "") if isinstance(raw, dict) else ""
        if raw_status.lower() == "shutdown":
            continue
        modalities = raw.get("modalities") if isinstance(raw, dict) and isinstance(raw.get("modalities"), dict) else {}
        input_modalities = [str(item).lower() for item in modalities.get("input_modalities", []) if item]
        output_modalities = [str(item).lower() for item in modalities.get("output_modalities", []) if item]
        if input_modalities and "text" not in input_modalities:
            continue
        if output_modalities and "text" not in output_modalities:
            continue
        features = raw.get("features") if isinstance(raw, dict) and isinstance(raw.get("features"), dict) else {}
        structured = features.get("structured_outputs") if isinstance(features.get("structured_outputs"), dict) else {}
        seen.add(model_id)
        models.append({
            "id": model_id,
            "owner": str(raw.get("owned_by") or raw.get("owner") or raw.get("display_name") or "") if isinstance(raw, dict) else "",
            "recommended": raw_status.lower() != "retiring" and not any(token in model_id.lower() for token in ("embedding", "code", "coder")),
            "supportsJson": bool(structured.get("json_object")) if structured else None,
            "status": raw_status,
        })
    if not models:
        raise VisionRequestError("当前 API Key 没有返回可用文本模型，可尝试手动填写模型 ID")
    return sorted(models, key=lambda item: (not item["recommended"], item.get("status") == "Retiring", item["id"].lower()))


class VisionConfigurationStore:
    """Thread-safe runtime model configuration with redacted public output."""

    def __init__(self, path: Path, defaults: dict[str, Any]) -> None:
        self.path = path
        self.defaults = dict(defaults)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": 1, "activeProvider": self.defaults["provider"], "providers": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": 1, "activeProvider": self.defaults["provider"], "providers": {}}
        if not isinstance(value, dict):
            return {"version": 1, "activeProvider": self.defaults["provider"], "providers": {}}
        value.setdefault("providers", {})
        value.setdefault("activeProvider", self.defaults["provider"])
        return value

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)

    def resolve(self, provider: str | None = None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            provider_id = str(provider or snapshot and snapshot.get("provider") or state.get("activeProvider") or self.defaults["provider"]).strip().lower().replace("-", "_")
            definition = _provider_definition(provider_id)
            saved = dict((state.get("providers") or {}).get(provider_id) or {})
            use_defaults = provider_id == self.defaults["provider"]
            resolved = {
                "provider": provider_id,
                "apiKey": str(saved.get("apiKey") or (self.defaults.get("apiKey") if use_defaults else "") or ""),
                "model": str(saved.get("model") or (self.defaults.get("model") if use_defaults else "") or ""),
                "baseUrl": str(saved.get("baseUrl") or (self.defaults.get("baseUrl") if use_defaults else "") or definition["baseUrl"] or "").rstrip("/"),
                "thinkingType": str(saved.get("thinkingType") if saved.get("thinkingType") is not None else (self.defaults.get("thinkingType") if use_defaults else "") or ""),
                "responseFormat": str(saved.get("responseFormat") or (self.defaults.get("responseFormat") if use_defaults else "") or definition["responseFormatDefault"]),
                "timeoutSeconds": float(saved.get("timeoutSeconds") or (self.defaults.get("timeoutSeconds") if use_defaults else 90.0) or 90.0),
                "models": list(saved.get("models") or []),
                "verifiedAt": saved.get("verifiedAt"),
                "keySource": "saved" if saved.get("apiKey") else ("environment" if use_defaults and self.defaults.get("apiKey") else "none"),
            }
            if snapshot:
                for source_key, target_key in (("model", "model"), ("baseUrl", "baseUrl"), ("thinkingType", "thinkingType"), ("responseFormat", "responseFormat"), ("timeoutSeconds", "timeoutSeconds")):
                    if snapshot.get(source_key) not in (None, ""):
                        resolved[target_key] = snapshot[source_key]
            return resolved

    def snapshot(self) -> dict[str, Any]:
        resolved = self.resolve()
        return {
            "provider": resolved["provider"],
            "providerLabel": vision_provider_label(resolved["provider"]),
            "model": resolved["model"],
            "baseUrl": resolved["baseUrl"],
            "thinkingType": resolved["thinkingType"],
            "responseFormat": resolved["responseFormat"],
            "timeoutSeconds": resolved["timeoutSeconds"],
        }

    def save(
        self,
        *,
        provider: str,
        api_key: str,
        model: str,
        base_url: str,
        thinking_type: str,
        response_format: str,
        models: list[dict[str, Any]] | None = None,
        verified_at: str | None = None,
    ) -> dict[str, Any]:
        provider_id = provider.strip().lower().replace("-", "_")
        current = self.resolve(provider_id)
        key = api_key.strip() or current["apiKey"]
        if not key:
            raise VisionRequestError("请填写 API Key")
        if not model.strip():
            raise VisionRequestError("请选择或填写视觉模型")
        if not base_url.strip():
            raise VisionRequestError("请填写接口地址")
        normalized_models = []
        for item in models or current.get("models") or []:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if model_id:
                normalized_models.append({
                    "id": model_id,
                    "owner": str(item.get("owner") or ""),
                    "recommended": bool(item.get("recommended")),
                    "supportsImage": item.get("supportsImage"),
                    "supportsVideo": item.get("supportsVideo"),
                    "supportsJson": item.get("supportsJson"),
                    "status": str(item.get("status") or ""),
                })
        with self._lock:
            state = self._read()
            state["activeProvider"] = provider_id
            state.setdefault("providers", {})[provider_id] = {
                "apiKey": key,
                "model": model.strip(),
                "baseUrl": base_url.strip().rstrip("/"),
                "thinkingType": thinking_type.strip().lower(),
                "responseFormat": response_format.strip().lower() or "json_object",
                "timeoutSeconds": current["timeoutSeconds"],
                "models": normalized_models,
                "verifiedAt": verified_at or current.get("verifiedAt"),
            }
            self._write(state)
        return self.resolve(provider_id)

    def mark_verified(self, *, provider: str, api_key: str, base_url: str, models: list[dict[str, Any]], verified_at: str) -> None:
        provider_id = provider.strip().lower().replace("-", "_")
        with self._lock:
            state = self._read()
            record = dict((state.get("providers") or {}).get(provider_id) or {})
            # Discovery is a user-initiated connection test. Persisting the key
            # here lets the subsequent Save action keep the masked credential.
            record.update({"apiKey": api_key, "baseUrl": base_url.rstrip("/"), "models": models, "verifiedAt": verified_at})
            state.setdefault("providers", {})[provider_id] = record
            self._write(state)

    def public_state(self) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            active = str(state.get("activeProvider") or self.defaults["provider"])
            providers = []
            known_ids = [item["id"] for item in PROVIDER_DEFINITIONS]
            for provider_id in known_ids:
                definition = _provider_definition(provider_id)
                resolved = self.resolve(provider_id)
                providers.append({
                    **definition,
                    "active": provider_id == active,
                    "configured": bool(resolved["apiKey"] and resolved["model"] and resolved["baseUrl"]),
                    "keyConfigured": bool(resolved["apiKey"]),
                    "keyHint": _mask_key(resolved["apiKey"]),
                    "keySource": resolved["keySource"],
                    "model": resolved["model"],
                    "baseUrl": resolved["baseUrl"],
                    "thinkingType": resolved["thinkingType"],
                    "responseFormat": resolved["responseFormat"],
                    "models": resolved["models"],
                    "verifiedAt": resolved["verifiedAt"],
                })
            return {"activeProvider": active, "providers": providers}


class LlmConfigurationStore:
    """Runtime text-planning configuration with optional VLM reuse mode."""

    def __init__(self, path: Path, defaults: dict[str, Any]) -> None:
        self.path = path
        self.defaults = dict(defaults)
        self._lock = threading.RLock()

    def _empty_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "mode": str(self.defaults.get("mode") or "reuse_vision"),
            "activeProvider": str(self.defaults.get("provider") or "ark"),
            "providers": {},
        }

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self._empty_state()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._empty_state()
        if not isinstance(value, dict):
            return self._empty_state()
        value.setdefault("mode", self.defaults.get("mode") or "reuse_vision")
        value.setdefault("activeProvider", self.defaults.get("provider") or "ark")
        value.setdefault("providers", {})
        return value

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)

    def resolve(self, provider: str | None = None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            snapshot = snapshot if isinstance(snapshot, dict) else {}
            mode = str(snapshot.get("mode") or state.get("mode") or self.defaults.get("mode") or "reuse_vision")
            provider_id = str(provider or snapshot.get("provider") or state.get("activeProvider") or self.defaults.get("provider") or "ark").strip().lower().replace("-", "_")
            definition = _llm_provider_definition(provider_id)
            saved = dict((state.get("providers") or {}).get(provider_id) or {})
            use_defaults = provider_id == self.defaults.get("provider")
            resolved = {
                "mode": "reuse_vision" if mode == "reuse_vision" else "independent",
                "provider": provider_id,
                "protocol": str(saved.get("protocol") or definition["protocol"]),
                "apiKey": str(saved.get("apiKey") or (self.defaults.get("apiKey") if use_defaults else "") or ""),
                "model": str(saved.get("model") or (self.defaults.get("model") if use_defaults else "") or ""),
                "baseUrl": str(saved.get("baseUrl") or (self.defaults.get("baseUrl") if use_defaults else "") or definition["baseUrl"] or "").rstrip("/"),
                "thinkingType": str(saved.get("thinkingType") if saved.get("thinkingType") is not None else (self.defaults.get("thinkingType") if use_defaults else "") or ""),
                "responseFormat": str(saved.get("responseFormat") or (self.defaults.get("responseFormat") if use_defaults else "") or definition["responseFormatDefault"]),
                "timeoutSeconds": float(saved.get("timeoutSeconds") or (self.defaults.get("timeoutSeconds") if use_defaults else 60.0) or 60.0),
                "models": list(saved.get("models") or []),
                "verifiedAt": saved.get("verifiedAt"),
                "keySource": "saved" if saved.get("apiKey") else ("environment" if use_defaults and self.defaults.get("apiKey") else "none"),
            }
            for source_key, target_key in (
                ("protocol", "protocol"), ("model", "model"), ("baseUrl", "baseUrl"),
                ("thinkingType", "thinkingType"), ("responseFormat", "responseFormat"),
                ("timeoutSeconds", "timeoutSeconds"),
            ):
                if snapshot.get(source_key) not in (None, ""):
                    resolved[target_key] = snapshot[source_key]
            return resolved

    def snapshot(self) -> dict[str, Any]:
        resolved = self.resolve()
        result = {"mode": resolved["mode"]}
        if resolved["mode"] == "reuse_vision":
            return result
        result.update({
            "provider": resolved["provider"],
            "providerLabel": llm_provider_label(resolved["provider"]),
            "protocol": resolved["protocol"],
            "model": resolved["model"],
            "baseUrl": resolved["baseUrl"],
            "thinkingType": resolved["thinkingType"],
            "responseFormat": resolved["responseFormat"],
            "timeoutSeconds": resolved["timeoutSeconds"],
        })
        return result

    def save(
        self,
        *,
        reuse_vision: bool,
        provider: str = "",
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        thinking_type: str = "",
        response_format: str = "json_object",
        models: list[dict[str, Any]] | None = None,
        verified_at: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            if reuse_vision:
                state["mode"] = "reuse_vision"
                self._write(state)
                return self.resolve()
        provider_id = provider.strip().lower().replace("-", "_")
        current = self.resolve(provider_id)
        key = api_key.strip() or current["apiKey"]
        if not key:
            raise VisionRequestError("请填写 API Key")
        if not model.strip():
            raise VisionRequestError("请选择或填写剪辑规划模型")
        if not base_url.strip():
            raise VisionRequestError("请填写接口地址")
        normalized_models = []
        for item in models or current.get("models") or []:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if model_id:
                normalized_models.append({
                    "id": model_id,
                    "owner": str(item.get("owner") or ""),
                    "recommended": bool(item.get("recommended")),
                    "supportsJson": item.get("supportsJson"),
                    "status": str(item.get("status") or ""),
                })
        definition = _llm_provider_definition(provider_id)
        with self._lock:
            state = self._read()
            state["mode"] = "independent"
            state["activeProvider"] = provider_id
            state.setdefault("providers", {})[provider_id] = {
                "protocol": definition["protocol"],
                "apiKey": key,
                "model": model.strip(),
                "baseUrl": base_url.strip().rstrip("/"),
                "thinkingType": thinking_type.strip().lower(),
                "responseFormat": response_format.strip().lower() or definition["responseFormatDefault"],
                "timeoutSeconds": current["timeoutSeconds"],
                "models": normalized_models,
                "verifiedAt": verified_at or current.get("verifiedAt"),
            }
            self._write(state)
        return self.resolve(provider_id)

    def public_state(self) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            mode = "reuse_vision" if state.get("mode") == "reuse_vision" else "independent"
            active = str(state.get("activeProvider") or self.defaults.get("provider") or "ark")
            providers = []
            for definition_source in LLM_PROVIDER_DEFINITIONS:
                provider_id = str(definition_source["id"])
                definition = _llm_provider_definition(provider_id)
                resolved = self.resolve(provider_id)
                providers.append({
                    **definition,
                    "active": provider_id == active,
                    "configured": bool(resolved["apiKey"] and resolved["model"] and resolved["baseUrl"]),
                    "keyConfigured": bool(resolved["apiKey"]),
                    "keyHint": _mask_key(resolved["apiKey"]),
                    "keySource": resolved["keySource"],
                    "model": resolved["model"],
                    "baseUrl": resolved["baseUrl"],
                    "thinkingType": resolved["thinkingType"],
                    "responseFormat": resolved["responseFormat"],
                    "models": resolved["models"],
                    "verifiedAt": resolved["verifiedAt"],
                })
            return {
                "mode": mode,
                "reuseVision": mode == "reuse_vision",
                "activeProvider": active,
                "providers": providers,
            }
