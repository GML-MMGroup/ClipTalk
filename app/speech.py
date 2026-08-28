from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np


_whisper_models: dict[tuple[str, str], Any] = {}
_whisper_lock = threading.Lock()
_sensevoice_model: Any = None
_sensevoice_key: tuple[str, ...] | None = None
_sensevoice_lock = threading.Lock()
_sensevoice_state_lock = threading.Lock()
_sensevoice_state: dict[str, Any] = {
    "status": "not_started", "device": None, "error": None, "loadedAt": None,
}

LANGUAGES = {"zh", "en", "yue", "ja", "ko", "nospeech"}
EMOTIONS = {
    "neutral": "neutral", "happy": "happy", "sad": "sad", "angry": "angry",
    "fearful": "fearful", "disgusted": "disgusted", "surprised": "surprised",
    "emo_unk": "unknown", "unknown": "unknown",
}
EVENTS = {
    "speech": "speech", "bgm": "bgm", "applause": "applause", "laughter": "laughter",
    "laugh": "laughter", "cry": "cry", "cough": "cough", "sneeze": "sneeze",
    "breath": "breath", "music": "bgm",
}
TAG_PATTERN = re.compile(r"<\|([^|>]+)\|>")
SPEECH_SCHEMA_VERSION = 9
SPEECH_WORKER_RUNTIME_VERSION = "9.0"
SPEECH_REQUEST_LEASE_SECONDS = 30.0
SPEECH_REQUEST_TIMEOUT_SECONDS = 4 * 60 * 60
MAX_SPEECH_SEGMENT_SECONDS = 90.0
REPAIRED_SPEECH_SEGMENT_SECONDS = 60.0


def _set_sensevoice_state(**patch: Any) -> None:
    with _sensevoice_state_lock:
        _sensevoice_state.update(patch)


def sensevoice_status(status_path: Path | None = None) -> dict[str, Any]:
    if status_path and status_path.is_file():
        try:
            value = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except (OSError, ValueError):
            pass
    with _sensevoice_state_lock:
        return dict(_sensevoice_state)


def _resolve_sensevoice_device(requested: str) -> str:
    value = requested.strip().lower()
    if value == "cpu":
        return "cpu"
    if value.startswith("cuda"):
        return value
    # Auto-select an available GPU instead of falling back to CPU whenever a
    # multi-GPU host is detected.  SenseVoice is launched in a worker process,
    # so a short nvidia-smi query here cannot block the web service startup.
    visible = (os.environ.get("CUDA_VISIBLE_DEVICES") or os.environ.get("NVIDIA_VISIBLE_DEVICES") or "").strip()
    visible_ids: list[str] | None = None
    if visible and visible.lower() not in {"-1", "none", "void", "all"}:
        visible_ids = [item.strip() for item in visible.split(",") if item.strip()]
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
            text=True, capture_output=True, timeout=4, check=False,
        )
        candidates: list[tuple[float, float, str]] = []
        for line in result.stdout.splitlines():
            fields = [item.strip() for item in line.split(",")]
            if len(fields) < 3:
                continue
            physical, free_text, utilization_text = fields[:3]
            if visible_ids is not None and physical not in visible_ids:
                continue
            try:
                free_mb = float(free_text)
                utilization = float(utilization_text)
            except ValueError:
                continue
            # Prefer free memory, then lower utilization.  Return the visible
            # ordinal when CUDA_VISIBLE_DEVICES remaps physical IDs.
            ordinal = str(visible_ids.index(physical)) if visible_ids and physical in visible_ids else physical
            candidates.append((free_mb, -utilization, ordinal))
        if candidates:
            return f"cuda:{max(candidates)[2]}"
    except (OSError, subprocess.TimeoutExpired):
        pass
    # Do not infer CUDA availability from /dev/nvidia* alone. In containers
    # those nodes can exist while the driver is unavailable; sending FunASR
    # to cuda:0 then hangs model initialisation instead of falling back.
    return "cpu"


def _sensevoice_model_options(
    *,
    model_name: str,
    device: str,
    vad_model: str,
    punc_model: str,
    spk_model: str,
    diarization: bool,
    algorithm_version: str = "editing-algorithm-v1",
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "model": model_name,
        "vad_model": vad_model,
        "vad_kwargs": {"max_single_segment_time": 3000 if algorithm_version == "editing-algorithm-v2" else 30000},
        "device": device,
        "disable_update": True,
    }
    # SenseVoice already produces punctuation. Passing an empty model name to
    # FunASR is not equivalent to disabling the component, so omit the option
    # entirely unless a deployment explicitly requests one.
    if punc_model.strip():
        options["punc_model"] = punc_model.strip()
    if diarization:
        options["spk_model"] = spk_model
        # VAD boundaries stay source-aligned and are safe for CAM++ speaker
        # assignment even when token-level punctuation alignment is absent.
        options["spk_mode"] = "vad_segment"
    return options


def _cluster_short_speaker_embeddings(
    embeddings: Any, *, oracle_num: int | None = None,
) -> Any:
    """Cluster a short recording without FunASR's all-one-speaker shortcut.

    FunASR 1.4's CAM++ backend returns label zero for every matrix with fewer
    than 20 rows. Short interviews commonly fall into that branch, even when
    two clearly different voices alternate. Use deterministic cosine K-means
    and a conservative silhouette gate instead. An explicitly supplied
    speaker count remains authoritative.
    """
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score, silhouette_score

    rows = embeddings.detach().cpu().numpy() if hasattr(embeddings, "detach") else np.asarray(embeddings)
    rows = np.asarray(rows, dtype=np.float32)
    if rows.ndim != 2 or rows.shape[0] < 1:
        raise ValueError("说话人聚类需要二维声纹矩阵")
    rows /= np.maximum(np.linalg.norm(rows, axis=1, keepdims=True), 1e-8)
    count = int(rows.shape[0])
    requested = max(0, min(count, int(oracle_num or 0)))
    if requested == 1 or count == 1:
        return np.zeros(count, dtype=int)
    if requested >= 2:
        return KMeans(n_clusters=requested, random_state=0, n_init=10).fit_predict(rows)
    if count == 2:
        similarity = float(np.dot(rows[0], rows[1]))
        return np.asarray([0, 1], dtype=int) if similarity < .55 else np.zeros(2, dtype=int)
    pairwise = np.matmul(rows, rows.T)
    if float(pairwise[np.triu_indices(count, 1)].min()) >= .82:
        return np.zeros(count, dtype=int)

    maximum = min(12, count - 1, max(2, int(round(math.sqrt(count))) + 2))
    best: tuple[float, float, Any] | None = None
    for clusters in range(2, maximum + 1):
        label_runs = [
            KMeans(n_clusters=clusters, random_state=seed, n_init=10).fit_predict(rows)
            for seed in (0, 17, 43)
        ]
        labels = label_runs[0]
        sizes = np.bincount(labels, minlength=clusters)
        # A one-off cough/noise fragment must not become a confident person.
        if count >= 6 and int(sizes.min()) < 2:
            continue
        silhouette = float(silhouette_score(rows, labels, metric="cosine"))
        stability = min(adjusted_rand_score(labels, value) for value in label_runs[1:])
        penalized = silhouette * .82 + stability * .18 - .035 * (clusters - 2)
        if best is None or penalized > best[0]:
            best = (penalized, silhouette, labels)
    if best is None or best[1] < .22:
        return np.zeros(count, dtype=int)
    return np.asarray(best[2], dtype=int)


def _configure_speaker_cluster_backend(model: Any) -> None:
    """Make CAM++ prefer reviewable over-separation to irreversible merging."""
    import types

    backend = getattr(model, "cb_model", None)
    if backend is None or getattr(backend, "_videopilot_cluster_v3", False):
        return
    original_forward = backend.forward
    if isinstance(getattr(backend, "model_config", None), dict):
        # Keep ambiguous voices separate without turning normal within-speaker
        # variation into duplicate Speaker cards. The former .86 threshold was
        # intentionally over-conservative and fragmented longer conversations.
        backend.model_config["merge_thr"] = .82

    def conservative_forward(_backend: Any, matrix: Any, **params: Any) -> Any:
        oracle = params.get("oracle_num")
        if oracle is not None or int(matrix.shape[0]) < 20:
            return _cluster_short_speaker_embeddings(matrix, oracle_num=oracle)
        return original_forward(matrix, **params)

    backend.forward = types.MethodType(conservative_forward, backend)
    backend._videopilot_cluster_v3 = True


def _sensevoice_instance(
    *,
    model_name: str,
    device: str,
    vad_model: str,
    punc_model: str,
    spk_model: str,
    diarization: bool,
    model_cache: Path,
    algorithm_version: str = "editing-algorithm-v1",
) -> tuple[Any, str]:
    global _sensevoice_model, _sensevoice_key
    resolved = _resolve_sensevoice_device(device)
    key = (model_name, resolved, vad_model, punc_model, spk_model if diarization else "", str(model_cache), algorithm_version)
    with _sensevoice_lock:
        if _sensevoice_model is not None and _sensevoice_key == key:
            return _sensevoice_model, resolved
        _set_sensevoice_state(status="preparing", device=resolved, error=None)
        model_cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MODELSCOPE_CACHE", str(model_cache))
        try:
            from funasr import AutoModel
            options = _sensevoice_model_options(
                model_name=model_name,
                device=resolved,
                vad_model=vad_model,
                punc_model=punc_model,
                spk_model=spk_model,
                diarization=diarization,
                algorithm_version=algorithm_version,
            )
            try:
                instance = AutoModel(**options)
            except Exception:
                if not resolved.startswith("cuda"):
                    raise
                resolved = "cpu"
                options["device"] = resolved
                key = (model_name, resolved, vad_model, punc_model, spk_model if diarization else "", str(model_cache), algorithm_version)
                instance = AutoModel(**options)
            if diarization:
                _configure_speaker_cluster_backend(instance)
        except Exception as error:
            _set_sensevoice_state(status="failed", device=resolved, error=str(error)[:800])
            raise RuntimeError(f"SenseVoice 模型加载失败：{error}") from error
        _sensevoice_model = instance
        _sensevoice_key = key
        _set_sensevoice_state(status="ready", device=resolved, error=None, loadedAt=time.time())
        return instance, resolved


def prewarm_sensevoice(**options: Any) -> None:
    try:
        _sensevoice_instance(**options)
    except Exception:
        # Health exposes the failure. Startup must remain available.
        return


def launch_sensevoice_worker(*, worker_directory: Path, **options: Any) -> None:
    """Launch a persistent model worker outside the web process so loading cannot freeze HTTP."""
    worker_directory.mkdir(parents=True, exist_ok=True)
    config_path = worker_directory / "config.json"
    status_path = worker_directory / "status.json"
    pid_path = worker_directory / "worker.pid"
    def worker_command(pid: int) -> bytes:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")

    def is_worker(pid: int) -> bool:
        try:
            command = worker_command(pid)
            return b"app.speech_worker" in command and str(worker_directory).encode() in command
        except OSError:
            return False

    def live_pids() -> list[int]:
        found: list[int] = []
        for proc in Path("/proc").glob("[0-9]*"):
            try:
                pid = int(proc.name)
            except ValueError:
                continue
            if is_worker(pid):
                found.append(pid)
        return found

    preferred: int | None = None
    try:
        if pid_path.is_file():
            candidate = int(pid_path.read_text(encoding="utf-8").strip())
            if is_worker(candidate):
                preferred = candidate
    except (OSError, ValueError):
        preferred = None

    candidates = live_pids()
    desired_config = {
        **options, "model_cache": str(options["model_cache"]),
        "worker_directory": str(worker_directory),
        # A persistent worker survives web-service restarts. Tie it to the
        # speech payload schema so code changes cannot leave an old worker
        # serving stale normalisation logic.
        "runtime_version": SPEECH_WORKER_RUNTIME_VERSION,
    }
    # A long-lived worker survives web-service reloads. Reuse it only when its
    # model/device/diarization configuration still matches the current
    # settings; otherwise the web process would silently keep the old CPU +
    # CAM++ configuration forever.
    config_mismatch = False
    if candidates and config_path.is_file():
        try:
            existing_config = json.loads(config_path.read_text(encoding="utf-8"))
            config_mismatch = any(existing_config.get(key) != value for key, value in desired_config.items())
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            config_mismatch = True
    if config_mismatch:
        for pid in candidates:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        candidates = []
        preferred = None
    if preferred is None and candidates:
        # Keep the worker recorded in status.json when possible; it may still
        # be finishing a request after a web-service restart.
        try:
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
            status_pid = int(status.get("pid") or 0)
            if status_pid in candidates:
                preferred = status_pid
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            preferred = None
        preferred = preferred or candidates[0]

    # Older service restarts could orphan workers. Keep one valid worker and
    # terminate the rest before accepting a new request; otherwise each worker
    # races on the shared status/request directory and all inference slows down.
    if preferred is not None:
        pid_path.write_text(str(preferred), encoding="utf-8")
        for pid in candidates:
            if pid == preferred:
                continue
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        return

    config_path.write_text(json.dumps(desired_config, ensure_ascii=False), encoding="utf-8")
    status_path.write_text(json.dumps({
        "status": "preparing", "device": None, "error": None,
    }, ensure_ascii=False), encoding="utf-8")
    log = (worker_directory / "worker.log").open("ab")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.speech_worker", str(config_path)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
    finally:
        log.close()
    pid_path.write_text(str(process.pid), encoding="utf-8")


def _sensevoice_via_worker(
    source: Path,
    *,
    worker_directory: Path,
    cancelled: Any,
    progress_callback: Any = None,
    preset_speaker_count: int | None = None,
) -> dict[str, Any]:
    requests = worker_directory / "requests"
    results = worker_directory / "results"
    requests.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    request_path = requests / f"{request_id}.json"
    result_path = results / f"{request_id}.json"
    lease_path = requests / f"{request_id}.lease"
    cancel_path = requests / f"{request_id}.cancel"
    created_at = time.time()
    deadline_at = created_at + SPEECH_REQUEST_TIMEOUT_SECONDS

    def refresh_lease() -> None:
        lease_temporary = lease_path.with_suffix(".lease.tmp")
        lease_temporary.write_text(json.dumps({
            "requestId": request_id, "ownerPid": os.getpid(),
            "heartbeatAt": time.time(), "deadlineAt": deadline_at,
        }, ensure_ascii=False), encoding="utf-8")
        lease_temporary.replace(lease_path)

    refresh_lease()
    temporary = request_path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "id": request_id, "source": str(source), "ownerPid": os.getpid(),
        "createdAt": created_at, "deadlineAt": deadline_at,
        "presetSpeakerCount": int(preset_speaker_count or 0),
    }, ensure_ascii=False), encoding="utf-8")
    temporary.replace(request_path)
    status_path = worker_directory / "status.json"
    last_lease_refresh = 0.0
    try:
        while not result_path.is_file():
            now = time.time()
            if cancelled and cancelled():
                request_path.unlink(missing_ok=True)
                cancel_path.touch()
                raise RuntimeError("任务已取消")
            if now >= deadline_at:
                request_path.unlink(missing_ok=True)
                cancel_path.touch()
                raise RuntimeError("SenseVoice 识别超过 4 小时，已终止本次请求")
            if now - last_lease_refresh >= 2.0:
                refresh_lease()
                last_lease_refresh = now
            status = sensevoice_status(status_path)
            status_request_id = str(status.get("requestId") or "")
            if progress_callback and status.get("status") == "running" and status_request_id == request_id:
                try:
                    progress_callback(
                        status.get("progress"), status.get("processed"), status.get("total"), status.get("phase"),
                    )
                except TypeError:
                    try:
                        progress_callback(status.get("progress"), status.get("processed"), status.get("total"))
                    except TypeError:
                        progress_callback(status.get("progress"))
            elif progress_callback:
                live_requests = []
                for candidate in requests.glob("*.json"):
                    candidate_lease = requests / f"{candidate.stem}.lease"
                    try:
                        if now - candidate_lease.stat().st_mtime <= SPEECH_REQUEST_LEASE_SECONDS:
                            live_requests.append(candidate)
                    except OSError:
                        continue
                live_requests.sort(key=lambda path: path.stat().st_mtime)
                queued_ids = [path.stem for path in live_requests]
                position = queued_ids.index(request_id) + 1 if request_id in queued_ids else len(queued_ids) + 1
                phase = f"queued:{position}:{max(position, len(queued_ids))}"
                try:
                    progress_callback(None, None, None, phase)
                except TypeError:
                    progress_callback(None)
            if status.get("status") == "failed":
                request_path.unlink(missing_ok=True)
                raise RuntimeError(str(status.get("error") or "SenseVoice 工作进程启动失败"))
            try:
                pid = int((worker_directory / "worker.pid").read_text(encoding="utf-8").strip())
                os.kill(pid, 0)
            except (OSError, ValueError):
                request_path.unlink(missing_ok=True)
                raise RuntimeError("SenseVoice 工作进程未运行")
            time.sleep(.2)
        value = json.loads(result_path.read_text(encoding="utf-8"))
    finally:
        result_path.unlink(missing_ok=True)
        lease_path.unlink(missing_ok=True)
        cancel_path.unlink(missing_ok=True)
    if value.get("error"):
        raise RuntimeError(str(value["error"])[:1000])
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("SenseVoice 工作进程没有返回有效结果")
    return payload


def parse_rich_tags(value: Any) -> dict[str, Any]:
    if isinstance(value, (list, tuple)):
        text = " ".join(str(item or "").strip() for item in value if str(item or "").strip())
    else:
        text = str(value or "")
    language: str | None = None
    emotions: list[str] = []
    events: list[str] = []
    for raw in TAG_PATTERN.findall(text):
        tag = raw.strip().lower()
        if tag in LANGUAGES:
            language = tag
        if tag in EMOTIONS and EMOTIONS[tag] not in emotions:
            emotions.append(EMOTIONS[tag])
        if tag in EVENTS and EVENTS[tag] not in events:
            events.append(EVENTS[tag])
    clean = TAG_PATTERN.sub("", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return {"text": clean, "language": language, "emotions": emotions, "audioEvents": events}


def _milliseconds(value: Any, default: float = 0.0) -> float:
    try:
        return round(max(0.0, float(value)) / 1000.0, 3)
    except (TypeError, ValueError):
        return default


def _timestamp_aligned_words(
    text: str, timestamp: Any, *, sentence_start: float, sentence_end: float,
) -> list[dict[str, Any]]:
    """Convert FunASR token timestamps into conservative source-time words."""
    if not isinstance(timestamp, list):
        return []
    pairs = [pair for pair in timestamp if isinstance(pair, (list, tuple)) and len(pair) >= 2]
    tokens = list(re.finditer(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[^\s]", text))
    if not pairs or len(pairs) != len(tokens):
        return []
    raw_max = max(float(pair[1]) for pair in pairs)
    relative = sentence_start > .01 and raw_max <= (sentence_end - sentence_start + 2.0) * 1000
    offset = sentence_start if relative else 0.0
    words: list[dict[str, Any]] = []
    for token, pair in zip(tokens, pairs):
        start = offset + _milliseconds(pair[0])
        end = offset + _milliseconds(pair[1])
        start = max(sentence_start, min(sentence_end, start))
        end = max(start, min(sentence_end, end))
        words.append({
            "word": token.group(0), "start": round(start, 3), "end": round(end, 3),
            "charStart": token.start(), "charEnd": token.end(),
        })
    return words


def _split_aligned_sentence(segment: dict[str, Any]) -> list[dict[str, Any]]:
    """Split only on strongly punctuated, timestamp-aligned sentence ends."""
    words = list(segment.get("words") or [])
    text = str(segment.get("text") or "")
    if len(words) < 2:
        return [segment]
    boundaries = [index for index, word in enumerate(words) if str(word.get("word") or "") in "。！？!?；;"]
    if not boundaries or boundaries[-1] != len(words) - 1:
        boundaries.append(len(words) - 1)
    result: list[dict[str, Any]] = []
    first = 0
    for boundary in boundaries:
        selected = words[first:boundary + 1]
        if not selected:
            continue
        start = float(selected[0]["start"])
        end = float(selected[-1]["end"])
        char_start = int(selected[0].get("charStart") or 0)
        char_end = int(selected[-1].get("charEnd") or len(text))
        clause_text = text[char_start:char_end].strip()
        if end - start < .18 or not clause_text:
            if result:
                result[-1]["end"] = max(float(result[-1]["end"]), end)
                result[-1]["text"] = (str(result[-1]["text"]) + clause_text).strip()
                result[-1]["words"].extend(selected)
            first = boundary + 1
            continue
        result.append({
            **segment, "start": round(start, 3), "end": round(end, 3),
            "text": clause_text, "words": selected,
            "timingSource": "sensevoice_token_timestamp",
        })
        first = boundary + 1
    return result or [segment]


def _balanced_text_chunks(value: Any, count: int) -> list[str]:
    """Split transcript text in order without cutting Latin words when possible."""
    text = str(value or "").strip()
    count = max(1, int(count))
    if count == 1:
        return [text]
    if not text:
        return [""] * count
    word_tokens = re.findall(r"\S+\s*", text)
    tokens = word_tokens if len(word_tokens) >= count else list(text)
    size = len(tokens)
    chunks: list[str] = []
    for index in range(count):
        start = round(index * size / count)
        end = round((index + 1) * size / count)
        chunks.append("".join(tokens[start:end]).strip())
    return chunks


def repair_long_speech_segments(
    segments: list[dict[str, Any]],
    *,
    maximum_seconds: float = MAX_SPEECH_SEGMENT_SECONDS,
    target_seconds: float = REPAIRED_SPEECH_SEGMENT_SECONDS,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Bound malformed long SenseVoice spans while preserving transcript order.

    FunASR can occasionally fail to align punctuation timestamps on long media
    and collapse many VAD regions into one file-length sentence.  Rejecting the
    whole transcript discards otherwise useful recognition, so divide that span
    into conservative time windows and mark their timing as approximate.
    """
    repaired: list[dict[str, Any]] = []
    repaired_count = 0
    dropped_count = 0
    maximum_seconds = max(1.0, float(maximum_seconds))
    target_seconds = max(1.0, min(maximum_seconds, float(target_seconds)))
    for source in segments:
        segment = dict(source)
        start = max(0.0, float(segment.get("start") or 0.0))
        end = max(start, float(segment.get("end") or start))
        duration = end - start
        if duration <= maximum_seconds:
            repaired.append(segment)
            continue
        text = str(segment.get("text") or "").strip()
        events = list(segment.get("audioEvents") or [])
        # A punctuation-only, file-length span carries no usable transcript.
        # Dropping it is safer than manufacturing dozens of meaningless cues.
        if not re.search(r"[\w\u3400-\u9fff]", text) and not events:
            dropped_count += 1
            continue
        chunk_count = max(2, int(math.ceil(duration / target_seconds)))
        text_chunks = _balanced_text_chunks(text, chunk_count)
        for index in range(chunk_count):
            chunk_start = start + duration * index / chunk_count
            chunk_end = start + duration * (index + 1) / chunk_count
            chunk_text = text_chunks[index]
            if not chunk_text and not events:
                continue
            chunk = {
                **segment,
                "start": round(chunk_start, 3),
                "end": round(chunk_end, 3),
                "text": chunk_text,
                "words": [],
                "timingApproximate": True,
                "timingSource": "repaired_long_segment",
            }
            repaired.append(chunk)
        repaired_count += 1
    repaired.sort(key=lambda item: (float(item.get("start") or 0), float(item.get("end") or 0)))
    return repaired, {"repairedLongSegments": repaired_count, "droppedLongSegments": dropped_count}


def normalize_sensevoice_result(result: Any) -> dict[str, Any]:
    items = result if isinstance(result, list) else [result]
    segments: list[dict[str, Any]] = []
    detected_language: str | None = None
    speaker_names: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        overall = parse_rich_tags(item.get("text"))
        detected_language = detected_language or item.get("language") or overall["language"]
        sentences = item.get("sentence_info") or item.get("sentenceInfo") or []
        if not isinstance(sentences, list) or not sentences:
            sentences = [{
                "start": item.get("start", 0), "end": item.get("end", 0),
                "text": item.get("text", ""), "spk": item.get("spk"),
                "timestamp": item.get("timestamp"),
            }]
        for sentence in sentences:
            if not isinstance(sentence, dict):
                continue
            sentence_text = sentence.get("text")
            if sentence_text in (None, "", []):
                sentence_text = sentence.get("sentence")
            rich = parse_rich_tags(sentence_text)
            text = rich["text"] or overall["text"]
            if not text and not rich["audioEvents"] and not overall["audioEvents"]:
                continue
            raw_speaker = sentence.get("spk", sentence.get("speaker"))
            speaker: str | None = None
            if raw_speaker not in (None, "", -1, "-1"):
                key = str(raw_speaker)
                if key not in speaker_names:
                    speaker_names[key] = f"Speaker {len(speaker_names) + 1}"
                speaker = speaker_names[key]
            start = _milliseconds(sentence.get("start", 0))
            end = _milliseconds(sentence.get("end", sentence.get("start", 0)), start)
            if end <= start:
                timestamp = sentence.get("timestamp") or []
                flat = [point for pair in timestamp if isinstance(pair, (list, tuple)) for point in pair[:2]] if isinstance(timestamp, list) else []
                if flat:
                    start, end = _milliseconds(min(flat)), _milliseconds(max(flat))
            emotions = rich["emotions"] or overall["emotions"]
            events = list(dict.fromkeys((rich["audioEvents"] or overall["audioEvents"])))
            words = sentence.get("words") if isinstance(sentence.get("words"), list) else []
            if not words:
                words = _timestamp_aligned_words(
                    text, sentence.get("timestamp"), sentence_start=start, sentence_end=max(start, end),
                )
            normalized_segment = {
                "start": start, "end": max(start, end), "text": text,
                "words": words, "speaker": speaker,
                "emotion": emotions[0] if emotions else "neutral",
                "audioEvents": events,
                "language": rich["language"] or overall["language"] or detected_language,
            }
            segments.extend(_split_aligned_sentence(normalized_segment))
    segments, repair_stats = repair_long_speech_segments(segments)
    return {
        "language": detected_language,
        "diarization": any(item.get("speaker") for item in segments),
        "segments": segments,
        **repair_stats,
    }


def enforce_speaker_turn_contract(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply overlap cannot-link and calibrated turn quality for v2."""
    rows = sorted((dict(item) for item in segments), key=lambda item: (
        float(item.get("start") or 0), float(item.get("end") or 0),
    ))
    existing = [str(item.get("speaker") or "") for item in rows if item.get("speaker")]
    next_speaker = len(dict.fromkeys(existing)) + 1
    active: list[dict[str, Any]] = []
    for row in rows:
        start, end = float(row.get("start") or 0), float(row.get("end") or 0)
        active = [item for item in active if float(item.get("end") or 0) > start + .12]
        same = next((item for item in active if row.get("speaker") and item.get("speaker") == row.get("speaker")), None)
        if same and min(end, float(same.get("end") or 0)) - start >= .12:
            row["speaker"] = f"Speaker {next_speaker}"
            next_speaker += 1
            row["overlapStatus"] = "separated_overlap"
            same["overlapStatus"] = "separated_overlap"
        else:
            row["overlapStatus"] = "overlap" if active else "none"
        active.append(row)
    by_speaker: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_speaker.setdefault(str(row.get("speaker") or "unknown"), []).append(row)
    for speaker_rows in by_speaker.values():
        turn_scores: list[float] = []
        for row in speaker_rows:
            duration = max(0.0, float(row.get("end") or 0) - float(row.get("start") or 0))
            duration_score = 1.0 if 1.5 <= duration <= 3.2 else max(.45, 1 - abs(duration - 2.25) / 8)
            text_score = min(1.0, max(.45, len(str(row.get("text") or "").strip()) / 12))
            overlap_penalty = .22 if row.get("overlapStatus") != "none" else 0.0
            turn_score = max(.35, min(.95, .52 * duration_score + .48 * text_score - overlap_penalty))
            boundary = .92 if row.get("words") else .68 if not row.get("timingApproximate") else .5
            row["turnConfidence"] = round(turn_score, 3)
            row["boundaryConfidence"] = round(boundary, 3)
            turn_scores.append(turn_score)
        cluster_score = max(.4, min(.95,
            float(np.mean(turn_scores)) + min(.08, math.log1p(len(turn_scores)) * .02)
        ))
        for row in speaker_rows:
            row["clusterConfidence"] = round(cluster_score, 3)
            row["requiresReview"] = bool(
                cluster_score < .62 or float(row["turnConfidence"]) < .6
                or row.get("overlapStatus") != "none" or float(row["boundaryConfidence"]) < .6
            )
    return rows


def _read_cache(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.is_file():
        return None
    try:
        value = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("segments"), list):
        return None
    return value


def _write_cache(cache_path: Path, payload: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(cache_path)


def _analyze_sensevoice(
    source: Path,
    *,
    model_name: str,
    device: str,
    vad_model: str,
    punc_model: str,
    spk_model: str,
    diarization: bool,
    model_cache: Path,
    cancelled: Any,
    progress_callback: Any = None,
    preset_speaker_count: int | None = None,
    algorithm_version: str = "editing-algorithm-v1",
) -> dict[str, Any]:
    model, actual_device = _sensevoice_instance(
        model_name=model_name, device=device, vad_model=vad_model, punc_model=punc_model,
        spk_model=spk_model, diarization=diarization, model_cache=model_cache,
        algorithm_version=algorithm_version,
    )
    if cancelled and cancelled():
        raise RuntimeError("任务已取消")
    started = time.monotonic()
    try:
        generate_options: dict[str, Any] = {
            "input": str(source), "cache": {}, "language": "auto", "use_itn": True,
            "batch_size_s": 60, "merge_vad": False,
            "sentence_timestamp": True, "progress_callback": progress_callback,
        }
        if diarization and int(preset_speaker_count or 0) > 0:
            generate_options["preset_spk_num"] = int(preset_speaker_count or 0)
        result = model.generate(
            **generate_options,
        )
    except Exception as error:
        raise RuntimeError(f"SenseVoice 推理失败：{error}") from error
    if cancelled and cancelled():
        raise RuntimeError("任务已取消")
    normalized = normalize_sensevoice_result(result)
    if algorithm_version == "editing-algorithm-v2":
        normalized["segments"] = enforce_speaker_turn_contract(normalized["segments"])
    return {
        "schemaVersion": SPEECH_SCHEMA_VERSION, "engine": "sensevoice", "model": model_name,
        "device": actual_device, "language": normalized.get("language"),
        "diarization": normalized.get("diarization", False),
        "presetSpeakerCount": int(preset_speaker_count or 0),
        "segments": normalized["segments"],
        "repairedLongSegments": int(normalized.get("repairedLongSegments") or 0),
        "droppedLongSegments": int(normalized.get("droppedLongSegments") or 0),
        "inferenceSeconds": round(time.monotonic() - started, 3),
    }


def _analyze_whisper(
    source: Path, *, model_name: str, device: str = "auto", cancelled: Any = None,
) -> dict[str, Any]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError("Whisper 回退需要安装 faster-whisper") from error
    resolved_device = device if device in {"cpu", "cuda"} else "cuda"
    if device == "auto":
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() < 1:
                resolved_device = "cpu"
        except Exception:
            resolved_device = "cpu"
    compute_type = "float16" if resolved_device == "cuda" else "int8"
    key = (model_name, resolved_device)
    with _whisper_lock:
        model = _whisper_models.get(key)
        if model is None:
            try:
                model = WhisperModel(model_name, device=resolved_device, compute_type=compute_type)
            except Exception:
                if resolved_device != "cuda":
                    raise
                resolved_device = "cpu"
                key = (model_name, resolved_device)
                model = _whisper_models.get(key) or WhisperModel(model_name, device="cpu", compute_type="int8")
            _whisper_models[key] = model
    generated, info = model.transcribe(
        str(source), beam_size=3, vad_filter=True, word_timestamps=True,
        condition_on_previous_text=False,
    )
    segments: list[dict[str, Any]] = []
    for segment in generated:
        if cancelled and cancelled():
            raise RuntimeError("任务已取消")
        if not str(segment.text).strip():
            continue
        segments.append({
            "start": round(float(segment.start), 3), "end": round(float(segment.end), 3),
            "text": str(segment.text).strip(), "speaker": None, "emotion": "neutral",
            "audioEvents": [], "language": getattr(info, "language", None),
            "words": [
                {"start": round(float(word.start), 3), "end": round(float(word.end), 3), "text": str(word.word)}
                for word in (segment.words or []) if word.start is not None and word.end is not None
            ],
        })
    return {
        "schemaVersion": SPEECH_SCHEMA_VERSION, "engine": "whisper", "model": model_name,
        "device": resolved_device, "language": getattr(info, "language", None),
        "diarization": False, "segments": segments,
    }


def analyze_speech(
    source: Path,
    cache_path: Path,
    *,
    engine: str,
    model_name: str,
    device: str = "auto",
    vad_model: str = "fsmn-vad",
    punc_model: str = "ct-punc",
    spk_model: str = "cam++",
    diarization: bool = True,
    model_cache: Path | None = None,
    whisper_model: str = "",
    whisper_device: str = "auto",
    cancelled: Any = None,
    progress_callback: Any = None,
    preset_speaker_count: int | None = None,
    algorithm_version: str = "editing-algorithm-v1",
) -> dict[str, Any]:
    cached = _read_cache(cache_path)
    if (
        cached
        and cached.get("schemaVersion") == SPEECH_SCHEMA_VERSION
        and (not diarization or bool(cached.get("diarization")))
        and int(cached.get("presetSpeakerCount") or 0) == int(preset_speaker_count or 0)
        and str(cached.get("algorithmVersion") or "editing-algorithm-v1") == algorithm_version
    ):
        return cached
    if engine == "sensevoice":
        try:
            resolved_cache = model_cache or cache_path.parent / "models"
            worker_directory = resolved_cache.parent / "cache" / "speech-worker"
            last_error: Exception | None = None
            for attempt in range(2):
                launch_sensevoice_worker(
                    worker_directory=worker_directory, model_name=model_name, device=device,
                    vad_model=vad_model, punc_model=punc_model, spk_model=spk_model,
                    diarization=diarization, model_cache=resolved_cache,
                    algorithm_version=algorithm_version,
                )
                try:
                    payload = _sensevoice_via_worker(
                        source, worker_directory=worker_directory, cancelled=cancelled,
                        progress_callback=progress_callback,
                        preset_speaker_count=preset_speaker_count,
                    )
                    break
                except Exception as error:
                    last_error = error
                    if cancelled and cancelled():
                        raise
                    if attempt == 0:
                        time.sleep(1.0)
            else:
                raise last_error or RuntimeError("SenseVoice 请求失败")
        except Exception as sensevoice_error:
            if not whisper_model or (cancelled and cancelled()):
                raise
            payload = _analyze_whisper(
                source, model_name=whisper_model, device=whisper_device, cancelled=cancelled,
            )
            payload["fallbackFrom"] = "sensevoice"
            payload["fallbackReason"] = str(sensevoice_error)[:500]
    elif engine == "whisper":
        if not model_name:
            raise RuntimeError("没有配置 Whisper 模型")
        payload = _analyze_whisper(source, model_name=model_name, device=device, cancelled=cancelled)
    else:
        raise RuntimeError(f"不支持的语音引擎：{engine}")
    payload["algorithmVersion"] = algorithm_version
    _write_cache(cache_path, payload)
    return payload


def transcribe_media(
    source: Path, cache_path: Path, *, model_name: str, device: str = "auto", cancelled: Any = None,
) -> list[dict[str, Any]]:
    """Backward-compatible Whisper entrypoint for old callers."""
    return analyze_speech(
        source, cache_path, engine="whisper", model_name=model_name,
        device=device, cancelled=cancelled,
    )["segments"]


def transcript_context(segments: list[dict[str, Any]], start: float, end: float, *, limit: int = 1200) -> str:
    snippets: list[str] = []
    for item in segments:
        if float(item.get("end", 0)) <= start or float(item.get("start", 0)) >= end:
            continue
        tags = [str(item.get("speaker") or "").strip()]
        emotion = str(item.get("emotion") or "neutral")
        if emotion not in {"", "neutral", "unknown"}:
            tags.append(f"emotion={emotion}")
        events = [str(value) for value in item.get("audioEvents", []) if value not in {"", "speech"}]
        if events:
            tags.append("events=" + ",".join(events))
        prefix = " ".join(f"[{value}]" for value in tags if value)
        snippets.append(
            f"[{float(item['start']):.1f}-{float(item['end']):.1f}s]{prefix} {item.get('text', '')}".strip()
        )
    return "\n".join(snippets)[:limit]


def speech_evidence(segments: list[dict[str, Any]], start: float, end: float) -> dict[str, Any]:
    selected = [
        item for item in segments
        if float(item.get("end", 0)) > start and float(item.get("start", 0)) < end
    ]
    speakers = list(dict.fromkeys(str(item["speaker"]) for item in selected if item.get("speaker")))
    speaker_sequence = [str(item["speaker"]) for item in selected if item.get("speaker")]
    speaker_turns = sum(
        previous != current
        for previous, current in zip(speaker_sequence, speaker_sequence[1:])
    )
    emotions = list(dict.fromkeys(
        str(item["emotion"]) for item in selected if item.get("emotion") not in {None, "", "neutral", "unknown"}
    ))
    events = list(dict.fromkeys(
        str(event) for item in selected for event in item.get("audioEvents", []) if event not in {"", "speech"}
    ))
    languages = list(dict.fromkeys(str(item["language"]) for item in selected if item.get("language")))
    return {
        "transcriptExcerpt": " ".join(str(item.get("text") or "") for item in selected)[:500],
        "speakers": speakers, "speakerTurns": speaker_turns,
        "emotions": emotions, "audioEvents": events, "languages": languages,
    }
