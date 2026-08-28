from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SOURCE_EVIDENCE_SCHEMA_VERSION = "source-evidence-v1"
PREDICATE_EVIDENCE_SCHEMA_VERSION = "predicate-evidence-v1"
SOURCE_EVIDENCE_EXTRACTOR_VERSION = "opportunistic-scene-facts-v1"
SOURCE_EVIDENCE_VECTOR_VERSION = "source-evidence-vectors-v1"
MAX_SOURCE_EVIDENCE_RECORDS = 25_000

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity(source_hash: str) -> str:
    return hashlib.sha256(str(source_hash or "unknown-source").encode("utf-8")).hexdigest()[:32]


def source_evidence_directory(data_root: Path, source_hash: str) -> Path:
    """Return a source-only cache root, independent of query scope and model bundle."""
    return Path(data_root) / "cache" / f"source-evidence-{_identity(source_hash)}"


def _lock_for(root: Path) -> threading.Lock:
    key = str(root)
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _with_file_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    return descriptor


def _normalize_text(value: Any) -> str:
    return re.sub(r"[\s，,。；;：:、.!！？?()（）\-_]+", "", str(value or "").casefold())


def _record_key(record: dict[str, Any]) -> str:
    payload = {
        "modality": str(record.get("modality") or "visual"),
        "time": round(float(record.get("evidenceTime") or record.get("start") or 0), 3),
        "observation": _normalize_text(record.get("observation") or record.get("text")),
        "model": str(record.get("model") or ""),
        "extractorVersion": str(record.get("extractorVersion") or SOURCE_EVIDENCE_EXTRACTOR_VERSION),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]


def promote_source_evidence(
    data_root: Path,
    source_hash: str,
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist reusable positive facts and return their stable source-level records."""
    prepared: list[dict[str, Any]] = []
    for source in records:
        if not isinstance(source, dict) or source.get("reusable") is False:
            continue
        observation = str(source.get("observation") or source.get("text") or "").strip()
        if not observation:
            continue
        try:
            start = max(0.0, float(source.get("start") or 0))
            end = max(start, float(source.get("end") or start))
            evidence_time = max(start, min(end if end > start else float(source.get("evidenceTime") or start), float(source.get("evidenceTime") or start)))
            confidence = max(0.0, min(1.0, float(source.get("confidence") or .75)))
        except (TypeError, ValueError):
            continue
        item = {
            "schemaVersion": "source-evidence-record-v1",
            "modality": str(source.get("modality") or "visual"),
            "start": round(start, 3),
            "end": round(end, 3),
            "evidenceTime": round(evidence_time, 3),
            "observation": observation[:600],
            "text": observation[:600],
            "title": str(source.get("title") or "历史画面证据")[:100],
            "confidence": round(confidence, 3),
            "model": str(source.get("model") or "")[:160],
            "source": str(source.get("source") or "query_visual_verification")[:80],
            "extractorVersion": str(
                source.get("extractorVersion") or SOURCE_EVIDENCE_EXTRACTOR_VERSION
            )[:100],
            "createdAt": str(source.get("createdAt") or _now_iso()),
        }
        key = _record_key(item)
        item["id"] = f"source_visual_{key}"
        item["recordKey"] = key
        prepared.append(item)
    if not prepared:
        return []

    root = source_evidence_directory(data_root, source_hash)
    path = root / "evidence.json"
    with _lock_for(root):
        descriptor = _with_file_lock(root)
        try:
            payload = _read_json(path) or {
                "schemaVersion": SOURCE_EVIDENCE_SCHEMA_VERSION,
                "sourceHash": str(source_hash or ""),
                "records": [],
                "createdAt": _now_iso(),
            }
            if payload.get("schemaVersion") != SOURCE_EVIDENCE_SCHEMA_VERSION:
                payload = {
                    "schemaVersion": SOURCE_EVIDENCE_SCHEMA_VERSION,
                    "sourceHash": str(source_hash or ""),
                    "records": [],
                    "createdAt": _now_iso(),
                }
            by_key = {
                str(item.get("recordKey") or _record_key(item)): item
                for item in payload.get("records") or [] if isinstance(item, dict)
            }
            for item in prepared:
                previous = by_key.get(str(item["recordKey"]))
                if previous is None or float(item.get("confidence") or 0) >= float(previous.get("confidence") or 0):
                    by_key[str(item["recordKey"])] = item
            records_out = sorted(
                by_key.values(),
                key=lambda item: (
                    float(item.get("evidenceTime") or item.get("start") or 0),
                    str(item.get("id") or ""),
                ),
            )[-MAX_SOURCE_EVIDENCE_RECORDS:]
            payload.update({"records": records_out, "updatedAt": _now_iso()})
            _atomic_write_json(path, payload)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
    stable = {str(item.get("recordKey")): item for item in records_out}
    return [copy.deepcopy(stable[str(item["recordKey"])]) for item in prepared if str(item["recordKey"]) in stable]


def read_source_evidence(
    data_root: Path,
    source_hash: str,
    *,
    modalities: set[str] | None = None,
    start: float = 0.0,
    end: float | None = None,
) -> list[dict[str, Any]]:
    root = source_evidence_directory(data_root, source_hash)
    payload = _read_json(root / "evidence.json") or {}
    if payload.get("schemaVersion") != SOURCE_EVIDENCE_SCHEMA_VERSION:
        return []
    scope_end = float("inf") if end is None else max(start, float(end))
    results = []
    for source in payload.get("records") or []:
        if not isinstance(source, dict):
            continue
        modality = str(source.get("modality") or "")
        if modalities is not None and modality not in modalities:
            continue
        row_start = float(source.get("start") or 0)
        row_end = max(row_start, float(source.get("end") or row_start))
        if row_end < start or row_start > scope_end:
            continue
        item = copy.deepcopy(source)
        item.update({
            "summary": str(item.get("observation") or item.get("text") or "")[:600],
            "text": str(item.get("observation") or item.get("text") or "")[:600],
            "evidenceTimes": [float(item.get("evidenceTime") or row_start)],
            "sourceEvidence": True,
        })
        results.append(item)
    return results


def query_source_evidence_vectors(
    data_root: Path,
    source_hash: str,
    records: list[dict[str, Any]],
    query: str,
    *,
    model_id: str,
    model_cache: Path,
    device: str = "auto",
    limit: int = 96,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Build/reuse a source-level text vector sidecar and recall scene facts."""
    usable = [
        item for item in records if isinstance(item, dict) and item.get("id")
        and str(item.get("observation") or item.get("text") or "").strip()
    ]
    if not usable or not str(query or "").strip() or not str(model_id or "").strip():
        return [], False, None
    ids = [str(item["id"]) for item in usable]
    texts = [str(item.get("observation") or item.get("text") or "")[:600] for item in usable]
    revision = hashlib.sha256(json.dumps(
        list(zip(ids, texts)), ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()[:24]
    root = source_evidence_directory(data_root, source_hash)
    manifest_path = root / "text-vectors.json"
    matrix_path = root / "text-vectors.npy"
    cache_hit = False
    try:
        manifest = _read_json(manifest_path) or {}
        valid = bool(
            manifest.get("schemaVersion") == SOURCE_EVIDENCE_VECTOR_VERSION
            and manifest.get("revision") == revision
            and manifest.get("model") == model_id
            and manifest.get("ids") == ids
            and matrix_path.is_file()
        )
        if not valid:
            with _lock_for(root):
                descriptor = _with_file_lock(root)
                try:
                    manifest = _read_json(manifest_path) or {}
                    valid = bool(
                        manifest.get("schemaVersion") == SOURCE_EVIDENCE_VECTOR_VERSION
                        and manifest.get("revision") == revision
                        and manifest.get("model") == model_id
                        and manifest.get("ids") == ids
                        and matrix_path.is_file()
                    )
                    if not valid:
                        import numpy as np
                        from .recognition_models import TextEncoder

                        matrix = TextEncoder(
                            model_id, device=device, cache_dir=model_cache,
                        ).encode_texts(texts, query=False)
                        temporary = matrix_path.with_suffix(f".npy.{os.getpid()}.tmp")
                        with temporary.open("wb") as handle:
                            np.save(handle, matrix.astype(np.float16), allow_pickle=False)
                        temporary.replace(matrix_path)
                        manifest = {
                            "schemaVersion": SOURCE_EVIDENCE_VECTOR_VERSION,
                            "sourceHash": str(source_hash or ""),
                            "revision": revision,
                            "model": model_id,
                            "ids": ids,
                            "shape": list(matrix.shape),
                            "updatedAt": _now_iso(),
                        }
                        _atomic_write_json(manifest_path, manifest)
                    else:
                        cache_hit = True
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                    os.close(descriptor)
        else:
            cache_hit = True

        import numpy as np
        from .recognition_models import TextEncoder

        matrix = np.load(matrix_path, mmap_mode="r", allow_pickle=False).astype(np.float32)
        vector = TextEncoder(
            model_id, device=device, cache_dir=model_cache,
        ).encode_texts([query], query=True)[0].astype(np.float32)
        vector /= max(float(np.linalg.norm(vector)), 1e-12)
        scores = matrix @ vector
        ranked = np.argsort(scores)[::-1][:max(1, min(len(ids), int(limit)))]
        by_id = {str(item["id"]): item for item in usable}
        rows = []
        for position in ranked:
            if position >= len(ids):
                continue
            item = copy.deepcopy(by_id[ids[position]])
            item["sourceVectorScore"] = round(float(scores[position]), 6)
            rows.append(item)
        return rows, cache_hit, None
    except Exception as error:
        return [], cache_hit, f"source_evidence_vector_unavailable:{str(error)[:160]}"


def source_evidence_revision(data_root: Path, source_hash: str) -> str:
    payload = _read_json(
        source_evidence_directory(data_root, source_hash) / "evidence.json"
    ) or {}
    if payload.get("schemaVersion") != SOURCE_EVIDENCE_SCHEMA_VERSION:
        return "empty"
    rows = sorted(
        (
            str(item.get("recordKey") or _record_key(item)),
            round(float(item.get("confidence") or 0), 3),
        )
        for item in payload.get("records") or [] if isinstance(item, dict)
    )
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]


def predicate_cache_key(predicate: dict[str, Any], *, model_fingerprint: str) -> str:
    subject = predicate.get("subject") if isinstance(predicate.get("subject"), dict) else {}
    payload = {
        "kind": str(predicate.get("kind") or ""),
        "value": _normalize_text(
            predicate.get("entity") or predicate.get("action") or predicate.get("value")
            or predicate.get("query")
        ),
        "subject": {
            "type": str(subject.get("type") or ""),
            "description": _normalize_text(subject.get("description")),
        },
        "personId": str(predicate.get("personId") or predicate.get("subjectPersonId") or ""),
        "modelFingerprint": str(model_fingerprint or ""),
        "schemaVersion": PREDICATE_EVIDENCE_SCHEMA_VERSION,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def read_predicate_evidence(
    data_root: Path, source_hash: str, key: str,
) -> dict[str, Any] | None:
    payload = _read_json(
        source_evidence_directory(data_root, source_hash) / "predicates" / f"{key}.json"
    )
    if not payload or payload.get("schemaVersion") != PREDICATE_EVIDENCE_SCHEMA_VERSION:
        return None
    return payload


def write_predicate_evidence(
    data_root: Path, source_hash: str, key: str, payload: dict[str, Any],
) -> None:
    root = source_evidence_directory(data_root, source_hash)
    path = root / "predicates" / f"{key}.json"
    record = copy.deepcopy(payload)
    record.update({
        "schemaVersion": PREDICATE_EVIDENCE_SCHEMA_VERSION,
        "sourceHash": str(source_hash or ""),
        "updatedAt": _now_iso(),
    })
    with _lock_for(root):
        descriptor = _with_file_lock(root)
        try:
            _atomic_write_json(path, record)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def scope_is_covered(record: dict[str, Any], *, start: float, end: float) -> bool:
    if not record.get("coverageComplete"):
        return False
    scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
    try:
        return float(scope.get("start") or 0) <= start + .001 and float(scope.get("end") or 0) >= end - .001
    except (TypeError, ValueError):
        return False


def merged_duration(ranges: Iterable[tuple[float, float]]) -> float:
    normalized = sorted(
        (max(0.0, float(start)), max(0.0, float(end)))
        for start, end in ranges if float(end) > float(start)
    )
    merged: list[list[float]] = []
    for start, end in normalized:
        if not merged or start > merged[-1][1] + .001:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return round(sum(end - start for start, end in merged), 3)
