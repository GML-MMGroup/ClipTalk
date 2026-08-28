from __future__ import annotations

import base64
import json
import math
import os
import subprocess
import threading
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


VOICEPRINT_SCHEMA_VERSION = "voiceprint-library-v1"
VOICEPRINT_MODEL = "iic/speech_campplus_sv_zh-cn_16k-common"
VOICEPRINT_DIMENSION = 192
VOICEPRINT_REVIEW_THRESHOLD = 0.31
VOICEPRINT_ACCEPT_THRESHOLD = 0.38
VOICEPRINT_MARGIN_THRESHOLD = 0.05
MIN_ENROLLMENT_SPEECH_SECONDS = 6.0
MAX_ENROLLMENT_SPEECH_SECONDS = 60.0
MAX_EXEMPLARS = 8
# A normal conversational pause is often longer than the ASR segmenter's
# pause.  Keep the boundary strict when another speaker intervenes, but allow
# an uninterrupted speaker enough room to breathe without producing a new
# edit candidate for every sentence.
SPEAKER_TURN_CONTINUITY_GAP_SECONDS = 2.4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(vector: Iterable[float]) -> np.ndarray:
    value = np.asarray(list(vector), dtype=np.float32).reshape(-1)
    if value.size != VOICEPRINT_DIMENSION or not np.isfinite(value).all():
        raise ValueError("声纹模型返回了无效向量")
    norm = float(np.linalg.norm(value))
    if norm <= 1e-8:
        raise ValueError("声纹模型返回了空向量")
    return value / norm


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    first, second = _normalize(left), _normalize(right)
    return float(np.clip(np.dot(first, second), -1.0, 1.0))


def aggregate_embeddings(embeddings: Iterable[Iterable[float]]) -> dict[str, Any]:
    rows = [_normalize(item) for item in embeddings]
    if not rows:
        raise ValueError("没有可用的声纹样本")
    provisional = _normalize(np.mean(np.stack(rows), axis=0))
    similarities = [float(np.dot(item, provisional)) for item in rows]
    kept = [item for item, score in zip(rows, similarities) if score >= VOICEPRINT_REVIEW_THRESHOLD]
    if not kept:
        kept = [rows[int(np.argmax(similarities))]]
    if len(kept) > MAX_EXEMPLARS:
        retained_indices = sorted({
            int(round(value)) for value in np.linspace(0, len(kept) - 1, MAX_EXEMPLARS)
        })
        retained = [kept[index] for index in retained_indices]
    else:
        retained = kept
    centroid = _normalize(np.mean(np.stack(retained), axis=0))
    consistency = [float(np.dot(item, centroid)) for item in retained]
    return {
        "centroid": centroid.tolist(),
        "exemplars": [item.tolist() for item in retained],
        "sampleCount": len(retained),
        "discardedCount": len(rows) - len(retained),
        "minimumSimilarity": round(min(consistency), 4),
        "meanSimilarity": round(float(np.mean(consistency)), 4),
    }


def classify_voice_match(
    score: float, *, competing_score: float | None = None,
    review_threshold: float = VOICEPRINT_REVIEW_THRESHOLD,
    accept_threshold: float = VOICEPRINT_ACCEPT_THRESHOLD,
    margin_threshold: float = VOICEPRINT_MARGIN_THRESHOLD,
) -> dict[str, Any]:
    score = float(score)
    margin = None if competing_score is None else score - float(competing_score)
    if score < review_threshold:
        decision = "rejected"
    elif score >= accept_threshold and (margin is None or margin >= margin_threshold):
        decision = "matched"
    else:
        decision = "review"
    return {
        "decision": decision,
        "score": round(score, 4),
        "margin": round(margin, 4) if margin is not None else None,
        "reviewThreshold": review_threshold,
        "acceptThreshold": accept_threshold,
        "marginThreshold": margin_threshold,
    }


def _decode_key(value: str) -> bytes:
    raw = str(value or "").strip().encode("ascii", errors="ignore")
    if not raw:
        raise ValueError("未配置 HIGHLIGHT_VOICEPRINT_ENCRYPTION_KEY")
    try:
        decoded = base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))
    except Exception as error:
        raise ValueError("HIGHLIGHT_VOICEPRINT_ENCRYPTION_KEY 不是有效的 Base64") from error
    if len(decoded) != 32:
        raise ValueError("HIGHLIGHT_VOICEPRINT_ENCRYPTION_KEY 解码后必须为 32 字节")
    return decoded


class VoiceProfileStore:
    """Small encrypted instance-local voice profile catalog.

    The entire payload, including labels and embeddings, is encrypted.  The
    file contains only a versioned AES-GCM envelope and is replaced atomically.
    """

    def __init__(self, path: Path, encryption_key: str, *, model_id: str = VOICEPRINT_MODEL) -> None:
        self.path = Path(path)
        self.model_id = model_id
        self._lock = threading.RLock()
        self._error = ""
        try:
            self._key = _decode_key(encryption_key)
        except ValueError as error:
            self._key = None
            self._error = str(error)

    @property
    def available(self) -> bool:
        return self._key is not None

    @property
    def unavailable_reason(self) -> str:
        return self._error

    def status(self) -> dict[str, Any]:
        count = 0
        library_error = ""
        if self.available:
            try:
                count = len(self._read().get("profiles") or [])
            except Exception:
                library_error = "声纹库无法解密或内容已损坏"
        return {
            "enabled": self.available and not library_error,
            "configured": self.available,
            "reason": self.unavailable_reason or library_error or None,
            "model": self.model_id,
            "dimension": VOICEPRINT_DIMENSION,
            "profileCount": count,
            "storesRawAudio": False,
        }

    def _require(self) -> bytes:
        if self._key is None:
            raise RuntimeError(self._error or "声纹库未启用")
        return self._key

    def _empty(self) -> dict[str, Any]:
        return {"schemaVersion": VOICEPRINT_SCHEMA_VERSION, "profiles": []}

    def _read(self) -> dict[str, Any]:
        key = self._require()
        if not self.path.is_file():
            return self._empty()
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        if envelope.get("schemaVersion") != VOICEPRINT_SCHEMA_VERSION:
            raise RuntimeError("声纹库版本不兼容")
        nonce = base64.urlsafe_b64decode(str(envelope["nonce"]).encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(str(envelope["ciphertext"]).encode("ascii"))
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, VOICEPRINT_SCHEMA_VERSION.encode())
        payload = json.loads(plaintext.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
            raise RuntimeError("声纹库内容无效")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        key = self._require()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        nonce = os.urandom(12)
        plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, VOICEPRINT_SCHEMA_VERSION.encode())
        envelope = {
            "schemaVersion": VOICEPRINT_SCHEMA_VERSION,
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    @staticmethod
    def public(profile: dict[str, Any]) -> dict[str, Any]:
        return {
            key: profile.get(key) for key in (
                "id", "label", "status", "modelId", "modelRevision", "dimension",
                "sampleCount", "speechSeconds", "quality", "createdAt", "updatedAt",
            )
        }

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            profiles = self._read().get("profiles") or []
            return [self.public(item) for item in sorted(profiles, key=lambda row: str(row.get("createdAt") or ""))]

    def get(self, profile_id: str, *, public: bool = False) -> dict[str, Any]:
        with self._lock:
            profile = next((item for item in self._read().get("profiles") or [] if item.get("id") == profile_id), None)
            if profile is None:
                raise KeyError(profile_id)
            return self.public(profile) if public else dict(profile)

    def find_by_label(self, label: str) -> dict[str, Any] | None:
        wanted = str(label or "").strip().casefold()
        if not wanted:
            return None
        with self._lock:
            profile = next((item for item in self._read().get("profiles") or [] if str(item.get("label") or "").casefold() == wanted), None)
            return self.public(profile) if profile else None

    def save_enrollment(
        self, *, label: str, aggregate: dict[str, Any], speech_seconds: float,
        profile_id: str | None = None, model_revision: str = "master",
    ) -> dict[str, Any]:
        normalized_label = " ".join(str(label or "").split())[:48]
        if not normalized_label:
            raise ValueError("声纹名称不能为空")
        with self._lock:
            payload = self._read()
            profiles = payload["profiles"]
            duplicate = next((item for item in profiles if str(item.get("label") or "").casefold() == normalized_label.casefold() and item.get("id") != profile_id), None)
            if duplicate:
                raise ValueError("声纹名称已存在")
            existing = next((item for item in profiles if item.get("id") == profile_id), None) if profile_id else None
            embeddings = list(aggregate.get("exemplars") or [])
            total_seconds = float(speech_seconds)
            created_at = _now_iso()
            if existing:
                embeddings = [*(existing.get("exemplars") or []), *embeddings]
                merged = aggregate_embeddings(embeddings)
                aggregate = {**aggregate, **merged}
                total_seconds += float(existing.get("speechSeconds") or 0)
                created_at = str(existing.get("createdAt") or created_at)
            profile = {
                "id": str(profile_id or f"voice_{uuid.uuid4().hex}"),
                "label": normalized_label,
                "status": "ready",
                "modelId": self.model_id,
                "modelRevision": model_revision,
                "dimension": VOICEPRINT_DIMENSION,
                "centroid": aggregate["centroid"],
                "exemplars": list(aggregate.get("exemplars") or [])[:MAX_EXEMPLARS],
                "sampleCount": int(aggregate.get("sampleCount") or len(aggregate.get("exemplars") or [])),
                "speechSeconds": round(min(MAX_ENROLLMENT_SPEECH_SECONDS, total_seconds), 3),
                "quality": {
                    "minimumSimilarity": aggregate.get("minimumSimilarity"),
                    "meanSimilarity": aggregate.get("meanSimilarity"),
                    "discardedCount": int(aggregate.get("discardedCount") or 0),
                },
                "createdAt": created_at,
                "updatedAt": _now_iso(),
            }
            if existing:
                profiles[profiles.index(existing)] = profile
            else:
                profiles.append(profile)
            self._write(payload)
            return self.public(profile)

    def rename(self, profile_id: str, label: str) -> dict[str, Any]:
        normalized_label = " ".join(str(label or "").split())[:48]
        if not normalized_label:
            raise ValueError("声纹名称不能为空")
        with self._lock:
            payload = self._read()
            profiles = payload["profiles"]
            profile = next((item for item in profiles if item.get("id") == profile_id), None)
            if profile is None:
                raise KeyError(profile_id)
            duplicate = next((
                item for item in profiles
                if item.get("id") != profile_id
                and str(item.get("label") or "").casefold() == normalized_label.casefold()
            ), None)
            if duplicate:
                raise ValueError("声纹名称已存在")
            profile["label"] = normalized_label
            profile["updatedAt"] = _now_iso()
            self._write(payload)
            return self.public(profile)

    def delete(self, profile_id: str) -> bool:
        with self._lock:
            payload = self._read()
            retained = [item for item in payload["profiles"] if item.get("id") != profile_id]
            if len(retained) == len(payload["profiles"]):
                return False
            payload["profiles"] = retained
            self._write(payload)
            return True


class CamPlusVoiceEncoder:
    def __init__(self, *, model_id: str = VOICEPRINT_MODEL, device: str = "cpu", model_cache: Path | None = None) -> None:
        self.model_id = model_id
        self.device = device
        self.model_cache = model_cache
        self._model: Any = None
        self._lock = threading.RLock()

    def _instance(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            if self.model_cache:
                self.model_cache.mkdir(parents=True, exist_ok=True)
                os.environ.setdefault("MODELSCOPE_CACHE", str(self.model_cache))
            from funasr import AutoModel
            self._model = AutoModel(model=self.model_id, device=self.device, disable_update=True)
            return self._model

    def encode(self, audio_path: Path) -> list[float]:
        with self._lock:
            result = self._instance().generate(input=str(audio_path))
        item = result[0] if isinstance(result, list) and result else result
        embedding = item.get("spk_embedding") if isinstance(item, dict) else None
        if embedding is None:
            raise RuntimeError("CAM++ 没有返回声纹向量")
        if hasattr(embedding, "detach"):
            embedding = embedding.detach().cpu().numpy()
        return _normalize(np.asarray(embedding).reshape(-1)).tolist()


@dataclass(frozen=True)
class AudioQuality:
    duration: float
    voiced_duration: float
    voiced_ratio: float
    rms: float
    clipping_ratio: float


def wav_quality(path: Path) -> AudioQuality:
    with wave.open(str(path), "rb") as source:
        rate, frames, channels, width = source.getframerate(), source.getnframes(), source.getnchannels(), source.getsampwidth()
        if width != 2 or channels != 1 or rate != 16000:
            raise ValueError("内部声纹音频必须为 16kHz 单声道 PCM16")
        raw = source.readframes(frames)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
    clipping = float(np.mean(np.abs(samples) >= .995)) if samples.size else 0.0
    frame_size = max(1, int(rate * .03))
    usable = samples[: samples.size - samples.size % frame_size]
    if usable.size:
        frame_rms = np.sqrt(np.mean(usable.reshape(-1, frame_size) ** 2, axis=1))
        # A deliberately conservative local energy VAD: it removes silence
        # and near-silence without pretending to separate background music or
        # overlapping speakers. Those remain review risks during matching.
        voiced_ratio = float(np.mean(frame_rms >= .004))
    else:
        voiced_ratio = 0.0
    duration = frames / max(1, rate)
    return AudioQuality(
        duration=duration, voiced_duration=duration * voiced_ratio,
        voiced_ratio=voiced_ratio, rms=rms, clipping_ratio=clipping,
    )


def normalize_audio(
    source: Path, destination: Path, *, ffmpeg: str,
    start: float | None = None, end: float | None = None,
    minimum_duration: float = 2.0, minimum_voiced_seconds: float = 2.0,
) -> AudioQuality:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        command.extend(["-ss", f"{max(0.0, float(start)):.3f}"])
    command.extend(["-i", str(source)])
    if end is not None:
        duration = float(end) - float(start or 0)
        if duration <= 0:
            raise ValueError("声纹选区结束时间必须晚于开始时间")
        command.extend(["-t", f"{min(MAX_ENROLLMENT_SPEECH_SECONDS, duration):.3f}"])
    else:
        command.extend(["-t", f"{MAX_ENROLLMENT_SPEECH_SECONDS:.3f}"])
    command.extend(["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination)])
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode != 0 or not destination.is_file():
        raise ValueError(f"无法读取参考声音：{result.stderr[-300:]}")
    quality = wav_quality(destination)
    if quality.duration < minimum_duration:
        raise ValueError(f"单个声纹样本至少需要 {minimum_duration:g} 秒")
    if quality.rms < .003:
        raise ValueError("参考声音过轻或接近静音")
    if quality.voiced_duration < minimum_voiced_seconds:
        raise ValueError(f"参考片段中的有效声音不足 {minimum_voiced_seconds:g} 秒")
    if quality.clipping_ratio > .05:
        raise ValueError("参考声音削波严重，请换一段更清晰的录音")
    return quality


def split_wav_exemplars(
    source: Path, destination_directory: Path, *, target_seconds: float = 6.0,
) -> list[Path]:
    """Split a normalized WAV into independent enrollment exemplars.

    Short tail chunks are attached to the preceding chunk so CAM++ never sees
    a tiny sample. The temporary chunks are caller-owned and may be deleted as
    soon as their embeddings have been calculated.
    """
    destination_directory.mkdir(parents=True, exist_ok=True)
    with wave.open(str(source), "rb") as reader:
        params = reader.getparams()
        rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())
    bytes_per_frame = params.nchannels * params.sampwidth
    chunk_frames = max(1, int(rate * target_seconds))
    total_frames = len(frames) // bytes_per_frame
    boundaries = list(range(0, total_frames, chunk_frames))
    if len(boundaries) > 1 and total_frames - boundaries[-1] < rate * 2:
        boundaries.pop()
    paths: list[Path] = []
    for index, start_frame in enumerate(boundaries[:MAX_EXEMPLARS]):
        end_frame = boundaries[index + 1] if index + 1 < len(boundaries) else total_frames
        path = destination_directory / f"exemplar-{index + 1:02d}.wav"
        with wave.open(str(path), "wb") as writer:
            writer.setparams(params)
            writer.writeframes(frames[start_frame * bytes_per_frame:end_frame * bytes_per_frame])
        paths.append(path)
    return paths


def enroll_audio_paths(paths: Iterable[Path], encoder: CamPlusVoiceEncoder) -> dict[str, Any]:
    embeddings: list[list[float]] = []
    speech_seconds = 0.0
    for path in paths:
        quality = wav_quality(path)
        if quality.voiced_duration < 2.0 or quality.rms < .003:
            continue
        speech_seconds += quality.voiced_duration
        embeddings.append(encoder.encode(path))
    if speech_seconds < MIN_ENROLLMENT_SPEECH_SECONDS:
        raise ValueError(f"有效参考声音至少需要 {MIN_ENROLLMENT_SPEECH_SECONDS:g} 秒")
    return {**aggregate_embeddings(embeddings), "speechSeconds": min(MAX_ENROLLMENT_SPEECH_SECONDS, speech_seconds)}


def merge_target_speech_segments(
    segments: Iterable[dict[str, Any]], speaker: str,
    *, maximum_gap: float = SPEAKER_TURN_CONTINUITY_GAP_SECONDS,
) -> list[dict[str, Any]]:
    wanted = str(speaker or "").casefold()
    rows = sorted([
        dict(item) for item in segments
        if str(item.get("speaker") or "").casefold() == wanted
        and float(item.get("end") or 0) > float(item.get("start") or 0)
    ], key=lambda item: float(item.get("start") or 0))
    merged: list[dict[str, Any]] = []
    all_rows = sorted([dict(item) for item in segments], key=lambda item: float(item.get("start") or 0))
    for row in rows:
        start, end = float(row.get("start") or 0), float(row.get("end") or 0)
        if merged:
            previous = merged[-1]
            previous_source_end = float(previous.get("_sourceEnd") or previous["end"])
            gap_has_other = any(
                str(other.get("speaker") or "").casefold() not in {"", wanted}
                and float(other.get("start") or 0) < start
                and float(other.get("end") or 0) > previous_source_end
                for other in all_rows
            )
            if start - previous_source_end <= maximum_gap and not gap_has_other:
                bridged_gap = max(0.0, start - previous_source_end)
                previous["_sourceEnd"] = end
                previous["end"] = end + .2
                previous["text"] = "".join(filter(None, [str(previous.get("text") or ""), str(row.get("text") or "")]))
                previous["sourceSegmentCount"] += 1
                previous["bridgedSilenceSeconds"] = round(
                    float(previous.get("bridgedSilenceSeconds") or 0) + bridged_gap, 3,
                )
                continue
        merged.append({
            "start": max(0.0, start - .15), "end": end + .2,
            "_sourceEnd": end, "text": str(row.get("text") or ""),
            "speaker": speaker, "sourceSegmentCount": 1, "bridgedSilenceSeconds": 0.0,
        })
    for item in merged:
        item.pop("_sourceEnd", None)
    return merged
