from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def build_health_snapshot(
    *, settings: Any, speech_state: dict[str, Any],
    active_vision: dict[str, Any], vision_provider_name: str,
    active_llm: dict[str, Any], recognition_state: dict[str, Any],
) -> dict[str, Any]:
    """Build the stable public health contract from resolved dependencies."""
    vision_configured = bool(
        active_vision.get("apiKey") and active_vision.get("model") and active_vision.get("baseUrl")
    )
    llm_configured = bool(active_llm.get("apiKey") and active_llm.get("model") and active_llm.get("baseUrl"))
    return {
        "ok": True,
        "service": "vlm-highlight-cutter",
        "visionConfigured": vision_configured,
        "visionProvider": active_vision.get("provider"),
        "visionProviderLabel": vision_provider_name,
        "visionModel": active_vision.get("model"),
        "visionThinking": active_vision.get("thinkingType") or None,
        "visionResponseFormat": active_vision.get("responseFormat"),
        # Legacy fields remain part of the compatibility contract.
        "arkConfigured": vision_configured,
        "arkModel": active_vision.get("model"),
        "arkThinking": active_vision.get("thinkingType") or None,
        "llmConfigured": llm_configured,
        "llmModel": active_llm.get("model"),
        "llmProvider": active_llm.get("provider"),
        "llmProviderLabel": active_llm.get("providerLabel"),
        "llmUsesVision": active_llm.get("mode") == "reuse_vision",
        "llmUsesArkFallback": active_llm.get("mode") == "reuse_vision" and active_llm.get("provider") == "ark",
        "anthropicConfigured": llm_configured and active_llm.get("protocol") == "anthropic",
        "anthropicModel": active_llm.get("model") if active_llm.get("protocol") == "anthropic" else None,
        "speechRecognitionConfigured": settings.speech_engine == "sensevoice" or bool(settings.whisper_model),
        "speechEngine": settings.speech_engine,
        "senseVoiceModel": settings.sensevoice_model,
        "speechModelStatus": speech_state.get("status"),
        "speechDevice": speech_state.get("device"),
        "speechDiarization": settings.sensevoice_diarization,
        "speechModelError": speech_state.get("error"),
        "contentRecognition": recognition_state,
        "ffmpeg": Path(settings.ffmpeg).is_file(),
        "ffprobe": Path(settings.ffprobe).is_file(),
        "dataRoot": str(settings.data_root),
        "keptLibrary": True,
        "portraitProxyMaxDimension": 1280,
    }


def build_runtime_metrics(
    *, job_statuses: Iterable[str], http_metrics: dict[str, Any],
    analysis_queue: dict[str, int], render_queue: dict[str, int],
    analysis_workers: int,
) -> dict[str, Any]:
    """Aggregate low-cardinality process metrics without exposing job data."""
    status_counts: dict[str, int] = {}
    for raw_status in job_statuses:
        status = str(raw_status or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "http": http_metrics,
        "jobs": dict(sorted(status_counts.items())),
        "analysisQueue": analysis_queue,
        "renderQueue": render_queue,
        "workers": {"analysis": analysis_workers, "render": 2, "preview": 1},
    }
