from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


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


def _nonnegative_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(0, value)


def _boolean(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _executable(name: str, command: str, fallback: str) -> str:
    """Resolve an explicit executable or discover it from PATH."""
    configured = os.environ.get(name, "").strip()
    if configured:
        return shutil.which(configured) or str(Path(configured).expanduser())
    return shutil.which(command) or fallback


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
    access_token: str
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
            ffmpeg=_executable("FFMPEG_BIN", "ffmpeg", "/usr/bin/ffmpeg"),
            ffprobe=_executable("FFPROBE_BIN", "ffprobe", "/usr/bin/ffprobe"),
            maximum_upload_bytes=_positive_int("HIGHLIGHT_MAX_UPLOAD_BYTES", 8 * 1024**3),
            maximum_workers=min(4, _positive_int("HIGHLIGHT_MAX_WORKERS", 1)),
            access_token=os.environ.get("HIGHLIGHT_ACCESS_TOKEN", "").strip(),
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
        )

    def ensure_directories(self) -> None:
        for child in ("jobs", "uploads", "work", "outputs", "kept", "cache", "models"):
            (self.data_root / child).mkdir(parents=True, exist_ok=True)
        self.speech_model_cache.mkdir(parents=True, exist_ok=True)

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
