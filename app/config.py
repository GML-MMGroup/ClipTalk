from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .security import validate_deployment_access


ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(1, value)


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(1.0, value)


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def _nonnegative_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(0, value)


def _bounded_positive_int(name: str, default: int, maximum: int) -> int:
    return min(maximum, _positive_int(name, default))


def _boolean(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


@dataclass(frozen=True)
class Settings:
    root: Path
    data_root: Path
    vision_provider: str
    vision_api_key: str
    vision_model: str
    vision_base_url: str
    vision_thinking_type: str
    vision_response_format: str
    vision_timeout_seconds: float
    # Legacy Ark values remain available so existing deployments and text-LLM
    # fallback configuration continue to work without migration.
    ark_api_key: str
    ark_model: str
    ark_base_url: str
    ark_thinking_type: str
    ark_timeout_seconds: float
    llm_api_key: str
    llm_model: str
    llm_base_url: str
    llm_thinking_type: str
    llm_timeout_seconds: float
    anthropic_base_url: str
    anthropic_auth_token: str
    anthropic_model: str
    host: str
    port: int
    ffmpeg: str
    ffprobe: str
    maximum_upload_bytes: int
    maximum_workers: int
    content_search_model_concurrency: int
    access_token: str
    allow_unauthenticated_remote: bool
    allow_private_model_endpoints: bool
    maximum_storage_bytes: int
    retention_days: int
    whisper_model: str
    whisper_device: str
    speech_engine: str
    sensevoice_model: str
    sensevoice_device: str
    sensevoice_vad_model: str
    sensevoice_punc_model: str
    sensevoice_spk_model: str
    sensevoice_diarization: bool
    speech_model_cache: Path
    voiceprint_encryption_key: str
    voiceprint_model: str
    voiceprint_device: str
    voiceprint_review_threshold: float
    voiceprint_accept_threshold: float
    voiceprint_margin_threshold: float
    recognition_enabled: bool
    recognition_profile: str
    recognition_model_cache: Path
    recognition_worker_python: str
    recognition_text_model: str
    recognition_siglip_model: str
    recognition_clap_model: str
    recognition_grounding_model: str
    recognition_yunet_model: Path
    recognition_sface_model: Path
    recognition_yolox_model: Path
    recognition_youtureid_model: Path
    recognition_ocr_enabled: bool
    content_search_dialogue_v2: bool
    active_speaker_mode: str
    talknet_worker_python: str
    talknet_worker_script: str
    talknet_repository: str
    talknet_checkpoint: str
    talknet_device: str
    talknet_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "Settings":
        load_env()
        data_root = Path(os.environ.get("HIGHLIGHT_DATA_ROOT", ROOT / "data")).resolve()
        ark_api_key = os.environ.get("ARK_API_KEY", "").strip()
        ark_model = os.environ.get("ARK_MODEL", "").strip()
        ark_base_url = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        vision_override = any(os.environ.get(name, "").strip() for name in ("VISION_API_KEY", "VISION_MODEL", "VISION_BASE_URL"))
        vision_provider = os.environ.get("VISION_PROVIDER", "openai_compatible" if vision_override else "ark").strip().lower().replace("-", "_")
        vision_api_key = os.environ.get("VISION_API_KEY", "").strip() or ark_api_key
        vision_model = os.environ.get("VISION_MODEL", "").strip() or ark_model
        vision_base_url = (os.environ.get("VISION_BASE_URL", "").strip() or ark_base_url).rstrip("/")
        default_vision_thinking = os.environ.get("ARK_THINKING_TYPE", "disabled") if vision_provider in {"ark", "volcengine_ark"} else ""
        return cls(
            root=ROOT,
            data_root=data_root,
            vision_provider=vision_provider,
            vision_api_key=vision_api_key,
            vision_model=vision_model,
            vision_base_url=vision_base_url,
            vision_thinking_type=os.environ.get("VISION_THINKING_TYPE", default_vision_thinking).strip().lower(),
            vision_response_format=os.environ.get("VISION_RESPONSE_FORMAT", "json_object").strip().lower(),
            vision_timeout_seconds=_positive_float("VISION_TIMEOUT_SECONDS", _positive_float("ARK_TIMEOUT_SECONDS", 90.0)),
            ark_api_key=ark_api_key,
            ark_model=ark_model,
            ark_base_url=ark_base_url,
            ark_thinking_type=os.environ.get("ARK_THINKING_TYPE", "disabled").strip().lower(),
            ark_timeout_seconds=_positive_float("ARK_TIMEOUT_SECONDS", 90.0),
            llm_api_key=os.environ.get("LLM_API_KEY", "").strip() or ark_api_key,
            llm_model=os.environ.get("LLM_MODEL", "").strip() or ark_model,
            llm_base_url=(os.environ.get("LLM_BASE_URL", "").strip() or ark_base_url).rstrip("/"),
            llm_thinking_type=os.environ.get("LLM_THINKING_TYPE", os.environ.get("ARK_THINKING_TYPE", "disabled")).strip().lower(),
            llm_timeout_seconds=_positive_float("LLM_TIMEOUT_SECONDS", 60.0),
            anthropic_base_url=os.environ.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/"),
            anthropic_auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip(),
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "").strip(),
            # Keep a clean checkout local-only by default. Container or remote
            # deployments can explicitly opt into 0.0.0.0 and should pair it
            # with HIGHLIGHT_ACCESS_TOKEN plus an HTTPS reverse proxy.
            host=os.environ.get("HIGHLIGHT_HOST", "127.0.0.1"),
            port=_positive_int("HIGHLIGHT_PORT", 5180),
            ffmpeg=os.environ.get("FFMPEG_BIN", "/usr/bin/ffmpeg"),
            ffprobe=os.environ.get("FFPROBE_BIN", "/usr/bin/ffprobe"),
            maximum_upload_bytes=_positive_int("HIGHLIGHT_MAX_UPLOAD_BYTES", 8 * 1024**3),
            maximum_workers=min(4, _positive_int("HIGHLIGHT_MAX_WORKERS", 1)),
            content_search_model_concurrency=_bounded_positive_int(
                "CONTENT_SEARCH_MODEL_CONCURRENCY", 3, 4,
            ),
            access_token=os.environ.get("HIGHLIGHT_ACCESS_TOKEN", "").strip(),
            allow_unauthenticated_remote=_boolean("HIGHLIGHT_ALLOW_UNAUTHENTICATED_REMOTE", False),
            allow_private_model_endpoints=_boolean("HIGHLIGHT_ALLOW_PRIVATE_MODEL_ENDPOINTS", False),
            maximum_storage_bytes=_positive_int("HIGHLIGHT_MAX_STORAGE_BYTES", 50 * 1024**3),
            retention_days=_nonnegative_int("HIGHLIGHT_RETENTION_DAYS", 0),
            whisper_model=os.environ.get("HIGHLIGHT_WHISPER_MODEL", "").strip(),
            whisper_device=os.environ.get("HIGHLIGHT_WHISPER_DEVICE", "auto").strip().lower(),
            speech_engine=os.environ.get("HIGHLIGHT_SPEECH_ENGINE", "sensevoice").strip().lower(),
            sensevoice_model=os.environ.get("HIGHLIGHT_SENSEVOICE_MODEL", "iic/SenseVoiceSmall").strip(),
            sensevoice_device=os.environ.get("HIGHLIGHT_SENSEVOICE_DEVICE", "auto").strip().lower(),
            sensevoice_vad_model=os.environ.get("HIGHLIGHT_SENSEVOICE_VAD_MODEL", "fsmn-vad").strip(),
            # SenseVoice already emits punctuation. Keep the optional external
            # punctuation model disabled unless a deployment explicitly asks
            # for it; CT-Punc alone adds roughly 1.1 GiB to first-run downloads.
            sensevoice_punc_model=os.environ.get("HIGHLIGHT_SENSEVOICE_PUNC_MODEL", "").strip(),
            sensevoice_spk_model=os.environ.get("HIGHLIGHT_SENSEVOICE_SPK_MODEL", "cam++").strip(),
            # Speaker separation is substantially more expensive than the
            # speech/emotion timeline. Enable it only for tasks that request
            # speaker-based editing, unless explicitly configured otherwise.
            sensevoice_diarization=_boolean("HIGHLIGHT_SENSEVOICE_DIARIZATION", False),
            speech_model_cache=Path(os.environ.get("HIGHLIGHT_SPEECH_MODEL_CACHE", data_root / "models")).resolve(),
            voiceprint_encryption_key=os.environ.get("HIGHLIGHT_VOICEPRINT_ENCRYPTION_KEY", "").strip(),
            voiceprint_model=os.environ.get(
                "HIGHLIGHT_VOICEPRINT_MODEL", "iic/speech_campplus_sv_zh-cn_16k-common",
            ).strip(),
            voiceprint_device=os.environ.get("HIGHLIGHT_VOICEPRINT_DEVICE", "cpu").strip().lower(),
            voiceprint_review_threshold=_bounded_float("HIGHLIGHT_VOICEPRINT_REVIEW_THRESHOLD", .31, -1.0, 1.0),
            voiceprint_accept_threshold=_bounded_float("HIGHLIGHT_VOICEPRINT_ACCEPT_THRESHOLD", .38, -1.0, 1.0),
            voiceprint_margin_threshold=_bounded_float("HIGHLIGHT_VOICEPRINT_MARGIN_THRESHOLD", .05, 0.0, 2.0),
            recognition_enabled=_boolean("HIGHLIGHT_RECOGNITION_V4", True),
            recognition_profile=(os.environ.get("HIGHLIGHT_RECOGNITION_PROFILE", "auto").strip().lower() or "auto"),
            recognition_model_cache=Path(os.environ.get("HIGHLIGHT_RECOGNITION_MODEL_CACHE", data_root / "models" / "recognition")).resolve(),
            recognition_worker_python=os.environ.get("HIGHLIGHT_RECOGNITION_PYTHON", "").strip(),
            recognition_text_model=os.environ.get("HIGHLIGHT_TEXT_EMBEDDING_MODEL", "intfloat/multilingual-e5-base").strip(),
            recognition_siglip_model=os.environ.get("HIGHLIGHT_SIGLIP_MODEL", "google/siglip2-base-patch16-224").strip(),
            recognition_clap_model=os.environ.get("HIGHLIGHT_CLAP_MODEL", "laion/clap-htsat-fused").strip(),
            recognition_grounding_model=os.environ.get("HIGHLIGHT_GROUNDING_MODEL", "IDEA-Research/grounding-dino-tiny").strip(),
            recognition_yunet_model=Path(os.environ.get("HIGHLIGHT_YUNET_MODEL", data_root / "models" / "recognition" / "face_detection_yunet_2023mar.onnx")).resolve(),
            recognition_sface_model=Path(os.environ.get("HIGHLIGHT_SFACE_MODEL", data_root / "models" / "recognition" / "face_recognition_sface_2021dec.onnx")).resolve(),
            recognition_yolox_model=Path(os.environ.get(
                "HIGHLIGHT_YOLOX_MODEL",
                data_root / "models" / "recognition" / "object_detection_yolox_2022nov.onnx",
            )).resolve(),
            recognition_youtureid_model=Path(os.environ.get(
                "HIGHLIGHT_YOUTUREID_MODEL",
                data_root / "models" / "recognition" / "person_reid_youtu_2021nov.onnx",
            )).resolve(),
            recognition_ocr_enabled=_boolean("HIGHLIGHT_OCR_ENABLED", True),
            content_search_dialogue_v2=_boolean("CONTENT_SEARCH_DIALOGUE_V2", True),
            active_speaker_mode=(os.environ.get("HIGHLIGHT_ACTIVE_SPEAKER_MODE", "primary").strip().lower() or "primary"),
            talknet_worker_python=os.environ.get("HIGHLIGHT_TALKNET_PYTHON", "").strip(),
            talknet_worker_script=os.environ.get("HIGHLIGHT_TALKNET_WORKER", str(ROOT / "tools" / "talknet_worker.py")).strip(),
            talknet_repository=os.environ.get("HIGHLIGHT_TALKNET_REPOSITORY", "").strip(),
            talknet_checkpoint=os.environ.get("HIGHLIGHT_TALKNET_CHECKPOINT", "").strip(),
            talknet_device=os.environ.get("HIGHLIGHT_TALKNET_DEVICE", "cuda:0").strip(),
            talknet_timeout_seconds=_positive_float("HIGHLIGHT_TALKNET_TIMEOUT_SECONDS", 900.0),
        )

    def ensure_directories(self) -> None:
        for child in ("jobs", "uploads", "work", "outputs", "kept", "cache", "models", "voiceprints", "runtime/voiceprint-temp"):
            (self.data_root / child).mkdir(parents=True, exist_ok=True)
        self.speech_model_cache.mkdir(parents=True, exist_ok=True)
        self.recognition_model_cache.mkdir(parents=True, exist_ok=True)

    def validate_deployment_security(self) -> None:
        validate_deployment_access(
            self.host, self.access_token,
            allow_unauthenticated_remote=self.allow_unauthenticated_remote,
        )

    def validate_vision(self) -> None:
        missing = [name for name, value in (
            ("VISION_API_KEY（或 ARK_API_KEY）", self.vision_api_key),
            ("VISION_MODEL（或 ARK_MODEL）", self.vision_model),
            ("VISION_BASE_URL（或 ARK_BASE_URL）", self.vision_base_url),
        ) if not value]
        if missing:
            raise RuntimeError(f"缺少视觉模型配置：{', '.join(missing)}")

    def validate_ark(self) -> None:
        """Compatibility alias for integrations created before VISION_* support."""
        self.validate_vision()
