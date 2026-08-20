from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .ark_client import VisionRequestError, vision_provider_label
from .security import SecurityConfigurationError, validate_public_http_endpoint
from .vision_settings import (
    LLM_PROVIDER_DEFINITIONS,
    LlmConfigurationStore,
    VisionConfigurationStore,
    discover_llm_models,
    discover_models,
    llm_provider_label,
)


class VisionDiscoverRequest(BaseModel):
    provider: str
    apiKey: str = ""
    baseUrl: str = ""


class VisionSettingsRequest(BaseModel):
    provider: str
    apiKey: str = ""
    model: str
    baseUrl: str
    thinkingType: str = ""
    responseFormat: str = "json_object"
    models: list[dict[str, Any]] | None = None
    verifiedAt: str | None = None


class LlmDiscoverRequest(BaseModel):
    provider: str
    apiKey: str = ""
    baseUrl: str = ""


class LlmSettingsRequest(BaseModel):
    reuseVision: bool = False
    provider: str = ""
    apiKey: str = ""
    model: str = ""
    baseUrl: str = ""
    thinkingType: str = ""
    responseFormat: str = "json_object"
    models: list[dict[str, Any]] | None = None
    verifiedAt: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validated_endpoint(
    provider: str,
    base_url: str,
    *,
    allowed_providers: set[str],
    provider_error: str,
    allow_private: bool,
) -> tuple[str, str]:
    provider_id = provider.strip().lower().replace("-", "_")
    if provider_id not in allowed_providers:
        raise HTTPException(400, provider_error)
    try:
        normalized_url = validate_public_http_endpoint(base_url, allow_private=allow_private)
    except SecurityConfigurationError as error:
        raise HTTPException(400, str(error)) from error
    return provider_id, normalized_url


def _connection_test_api_key(
    *, supplied_key: str, resolved: dict[str, Any], requested_base_url: str,
) -> str:
    key = supplied_key.strip()
    if key:
        return key
    saved_key = str(resolved.get("apiKey") or "")
    saved_base_url = str(resolved.get("baseUrl") or "").strip().rstrip("/")
    if saved_key and requested_base_url != saved_base_url:
        raise HTTPException(400, "接口地址已改变，请重新填写 API Key，不能向新地址发送已保存的密钥")
    return saved_key


def build_settings_router(
    *,
    vision_store: VisionConfigurationStore,
    llm_store: LlmConfigurationStore,
    allow_private_model_endpoints: bool,
) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["settings"])

    def validate_vision_endpoint(provider: str, base_url: str) -> tuple[str, str]:
        return _validated_endpoint(
            provider,
            base_url,
            allowed_providers={"ark", "openai", "openai_compatible"},
            provider_error="不支持的视觉模型服务商",
            allow_private=allow_private_model_endpoints,
        )

    def validate_llm_endpoint(provider: str, base_url: str) -> tuple[str, str]:
        return _validated_endpoint(
            provider,
            base_url,
            allowed_providers={str(item["id"]) for item in LLM_PROVIDER_DEFINITIONS},
            provider_error="不支持的剪辑规划模型服务商",
            allow_private=allow_private_model_endpoints,
        )

    @router.get("/vision")
    def get_vision_settings() -> dict[str, Any]:
        return vision_store.public_state()

    @router.post("/vision/discover")
    def discover_vision_models(request: VisionDiscoverRequest) -> dict[str, Any]:
        provider_id = request.provider.strip().lower().replace("-", "_")
        public = vision_store.public_state()
        provider_state = next((item for item in public["providers"] if item["id"] == provider_id), None)
        if provider_state is None:
            raise HTTPException(400, "不支持的视觉模型服务商")
        resolved = vision_store.resolve(provider_id)
        base_url = request.baseUrl.strip() or str(resolved.get("baseUrl") or provider_state.get("baseUrl") or "")
        provider_id, base_url = validate_vision_endpoint(provider_id, base_url)
        api_key = _connection_test_api_key(
            supplied_key=request.apiKey,
            resolved=resolved,
            requested_base_url=base_url,
        )
        if len(api_key) > 4096:
            raise HTTPException(400, "API Key 格式无效")
        try:
            models = discover_models(
                api_key=api_key,
                base_url=base_url,
                provider=provider_id,
                timeout_seconds=min(30.0, float(resolved.get("timeoutSeconds") or 20.0)),
            )
        except VisionRequestError as error:
            raise HTTPException(400, str(error)) from error
        return {
            "provider": provider_id,
            "providerLabel": vision_provider_label(provider_id),
            "baseUrl": base_url,
            "models": models,
            "verifiedAt": _now_iso(),
            "keyHint": "已验证当前输入的密钥" if request.apiKey.strip() else provider_state.get("keyHint") or "已验证保存的密钥",
        }

    @router.post("/vision")
    def save_vision_settings(request: VisionSettingsRequest) -> dict[str, Any]:
        provider_id, base_url = validate_vision_endpoint(request.provider, request.baseUrl)
        if len(request.apiKey) > 4096:
            raise HTTPException(400, "API Key 格式无效")
        if not request.model.strip() or len(request.model.strip()) > 200:
            raise HTTPException(400, "请选择有效的视觉模型")
        thinking_type = request.thinkingType.strip().lower()
        if thinking_type not in {"", "disabled", "enabled", "auto"}:
            raise HTTPException(400, "思考模式配置无效")
        response_format = request.responseFormat.strip().lower()
        if response_format not in {"json_object", "json", "none"}:
            raise HTTPException(400, "JSON 输出配置无效")
        try:
            vision_store.save(
                provider=provider_id,
                api_key=request.apiKey,
                model=request.model,
                base_url=base_url,
                thinking_type=thinking_type,
                response_format=response_format,
                models=(request.models or [])[:500],
                verified_at=request.verifiedAt,
            )
        except VisionRequestError as error:
            raise HTTPException(400, str(error)) from error
        return vision_store.public_state()

    @router.get("/llm")
    def get_llm_settings() -> dict[str, Any]:
        return llm_store.public_state()

    @router.post("/llm/discover")
    def discover_text_planning_models(request: LlmDiscoverRequest) -> dict[str, Any]:
        provider_id = request.provider.strip().lower().replace("-", "_")
        public = llm_store.public_state()
        provider_state = next((item for item in public["providers"] if item["id"] == provider_id), None)
        if provider_state is None:
            raise HTTPException(400, "不支持的剪辑规划模型服务商")
        resolved = llm_store.resolve(provider_id)
        base_url = request.baseUrl.strip() or str(resolved.get("baseUrl") or provider_state.get("baseUrl") or "")
        provider_id, base_url = validate_llm_endpoint(provider_id, base_url)
        api_key = _connection_test_api_key(
            supplied_key=request.apiKey,
            resolved=resolved,
            requested_base_url=base_url,
        )
        if len(api_key) > 4096:
            raise HTTPException(400, "API Key 格式无效")
        try:
            models = discover_llm_models(
                api_key=api_key,
                base_url=base_url,
                provider=provider_id,
                protocol=str(provider_state.get("protocol") or "openai"),
                timeout_seconds=min(30.0, float(resolved.get("timeoutSeconds") or 20.0)),
            )
        except VisionRequestError as error:
            raise HTTPException(400, str(error)) from error
        return {
            "provider": provider_id,
            "providerLabel": llm_provider_label(provider_id),
            "baseUrl": base_url,
            "models": models,
            "verifiedAt": _now_iso(),
            "keyHint": "已验证当前输入的密钥" if request.apiKey.strip() else provider_state.get("keyHint") or "已验证保存的密钥",
        }

    @router.post("/llm")
    def save_llm_settings(request: LlmSettingsRequest) -> dict[str, Any]:
        if request.reuseVision:
            llm_store.save(reuse_vision=True)
            return llm_store.public_state()
        provider_id, base_url = validate_llm_endpoint(request.provider, request.baseUrl)
        if len(request.apiKey) > 4096:
            raise HTTPException(400, "API Key 格式无效")
        if not request.model.strip() or len(request.model.strip()) > 200:
            raise HTTPException(400, "请选择有效的剪辑规划模型")
        thinking_type = request.thinkingType.strip().lower()
        if thinking_type not in {"", "disabled", "enabled", "auto"}:
            raise HTTPException(400, "思考模式配置无效")
        response_format = request.responseFormat.strip().lower()
        if response_format not in {"json_object", "json", "none"}:
            raise HTTPException(400, "JSON 输出配置无效")
        try:
            llm_store.save(
                reuse_vision=False,
                provider=provider_id,
                api_key=request.apiKey,
                model=request.model,
                base_url=base_url,
                thinking_type=thinking_type,
                response_format=response_format,
                models=(request.models or [])[:500],
                verified_at=request.verifiedAt,
            )
        except VisionRequestError as error:
            raise HTTPException(400, str(error)) from error
        return llm_store.public_state()

    return router
