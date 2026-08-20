from __future__ import annotations

import importlib.util
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

from .active_speaker import active_speaker_runtime


LEGACY_MULTIMODAL_INDEX_VERSION = "multimodal-index-v4"
MULTIMODAL_INDEX_VERSION = "multimodal-index-v7-dense-screen-text"
RECOGNITION_SCHEMA_VERSION = 7
RECOGNITION_MODALITIES = ("speech", "visual", "ocr", "audio", "person")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def normalize_recognition_profile(value: Any, *, cuda_available: bool = False) -> dict[str, str]:
    requested = str(value or "auto").strip().lower()
    if requested not in {"auto", "balanced", "full"}:
        requested = "auto"
    effective = "full" if requested == "auto" and cuda_available else (
        "balanced" if requested == "auto" else requested
    )
    return {"requested": requested, "effective": effective}


def runtime_capabilities(settings: Any, *, probe_active_speaker: bool = True) -> dict[str, Any]:
    torch_ready = importlib.util.find_spec("torch") is not None
    cuda = False
    if torch_ready:
        try:
            import torch

            cuda = bool(torch.cuda.is_available())
        except Exception:
            cuda = False
    profile = normalize_recognition_profile(getattr(settings, "recognition_profile", "auto"), cuda_available=cuda)
    yunet = Path(getattr(settings, "recognition_yunet_model", ""))
    sface = Path(getattr(settings, "recognition_sface_model", ""))
    enabled = bool(getattr(settings, "recognition_enabled", True))
    capabilities = {
        "schemaVersion": RECOGNITION_SCHEMA_VERSION,
        "indexVersion": MULTIMODAL_INDEX_VERSION,
        "enabled": enabled,
        "profile": profile,
        "device": "cuda" if cuda else "cpu",
        "speech": {"status": "ready"},
        "ocr": {
            "status": "ready" if enabled and getattr(settings, "recognition_ocr_enabled", True) and importlib.util.find_spec("paddleocr") else "degraded",
            "reason": "" if importlib.util.find_spec("paddleocr") else "paddleocr_not_installed",
        },
        "visualEmbedding": {
            "status": "ready" if enabled and importlib.util.find_spec("transformers") and torch_ready else "degraded",
            "model": getattr(settings, "recognition_siglip_model", ""),
        },
        "audioEmbedding": {
            "status": "ready" if enabled and importlib.util.find_spec("transformers") and torch_ready else "degraded",
            "model": getattr(settings, "recognition_clap_model", ""),
        },
        "objectGrounding": {
            "status": "ready" if enabled and importlib.util.find_spec("transformers") and torch_ready else "degraded",
            "model": getattr(settings, "recognition_grounding_model", ""),
        },
        "anonymousPersons": {
            "status": "ready" if enabled and yunet.is_file() and sface.is_file() else "degraded",
            "reason": "" if yunet.is_file() and sface.is_file() else "face_models_not_prepared",
        },
        "activeSpeaker": active_speaker_runtime(settings, probe=probe_active_speaker),
    }
    if not enabled:
        for key, value in capabilities.items():
            if isinstance(value, dict) and "status" in value:
                value.update({"status": "disabled", "reason": "recognition_v4_disabled"})
    return capabilities


def build_shots(duration: float, scene_cuts: Iterable[Any] | None = None) -> list[dict[str, Any]]:
    duration = max(0.0, _number(duration))
    cuts = sorted({
        round(max(0.0, min(duration, _number(value))), 3)
        for value in scene_cuts or []
        if 0.12 < _number(value) < duration - 0.12
    })
    boundaries = [0.0, *cuts, duration]
    shots: list[dict[str, Any]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end - start < 0.08:
            if shots:
                shots[-1]["end"] = round(end, 3)
                shots[-1]["duration"] = round(end - float(shots[-1]["start"]), 3)
            continue
        shots.append({
            "id": f"shot_{len(shots):05d}",
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "keyframeTimes": [],
        })
    return shots


def shot_sample_times(
    shots: list[dict[str, Any]], *, maximum_per_shot: int = 6, global_limit: int = 1200,
) -> list[float]:
    values: list[tuple[float, bool]] = []
    maximum_per_shot = max(1, int(maximum_per_shot))
    for shot in shots:
        start = _number(shot.get("start"))
        end = max(start, _number(shot.get("end"), start))
        duration = end - start
        margin = min(.15, duration * .12)
        if duration <= .25:
            times = [(start + end) * .5]
        else:
            base = [start + margin, (start + end) * .5, end - margin]
            extra_count = min(maximum_per_shot - 3, max(0, math.ceil(duration / 8.0) - 1))
            extras = [start + duration * (index + 1) / (extra_count + 1) for index in range(extra_count)]
            times = sorted({round(value, 3) for value in [*base, *extras]})[:maximum_per_shot]
        shot["keyframeTimes"] = times
        for index, value in enumerate(times):
            values.append((value, index in {0, len(times) - 1} or len(times) == 1))
    if len(values) <= global_limit:
        return sorted({value for value, _ in values})
    required = [value for value, essential in values if essential]
    optional = [value for value, essential in values if not essential]
    if len(required) >= global_limit:
        stride = len(required) / global_limit
        return sorted({required[min(len(required) - 1, int(index * stride))] for index in range(global_limit)})
    remaining = global_limit - len(required)
    stride = len(optional) / max(1, remaining)
    sampled = [optional[min(len(optional) - 1, int(index * stride))] for index in range(remaining)] if optional else []
    return sorted({*required, *sampled})


def dense_person_sample_times(
    shots: list[dict[str, Any]], *, start: float = 0.0, end: float | None = None,
    interval: float = .5,
) -> list[float]:
    """Return a continuous, scene-aware sampling schedule for face tracks.

    The generic content index intentionally uses sparse keyframes. Person
    retrieval has a different recall requirement: a face that is absent from
    one representative frame must not erase an otherwise valid appearance
    interval. Keep scene boundaries as evidence points and sample every
    ``interval`` seconds inside the requested range.
    """
    lower = max(0.0, _number(start))
    upper = max(lower, _number(end, lower)) if end is not None else None
    step = max(.1, _number(interval, .5))
    values: set[float] = set()
    for shot in shots:
        shot_start = max(lower, _number(shot.get("start")))
        shot_end = _number(shot.get("end"), shot_start)
        if upper is not None:
            shot_end = min(upper, shot_end)
        if shot_end <= shot_start:
            continue
        value = shot_start
        while value < shot_end:
            values.add(round(value, 3))
            value += step
        values.add(round(shot_end, 3))
    return sorted(values)


def motion_priority_times(frames: Iterable[Any], *, maximum: int = 120) -> list[float]:
    scored: list[tuple[float, float]] = []
    previous: np.ndarray | None = None
    previous_time = 0.0
    for frame in sorted(frames, key=lambda item: _number(getattr(item, "time", 0.0))):
        try:
            with Image.open(Path(getattr(frame, "path"))) as image:
                current = np.asarray(image.convert("L").resize((48, 27)), dtype=np.float32)
        except Exception:
            continue
        current_time = _number(getattr(frame, "time", 0.0))
        if previous is not None:
            score = float(np.mean(np.abs(current - previous)))
            scored.append(((previous_time + current_time) * .5, score))
        previous, previous_time = current, current_time
    selected: list[float] = []
    for value, _ in sorted(scored, key=lambda item: item[1], reverse=True):
        if all(abs(value - existing) >= .75 for existing in selected):
            selected.append(round(value, 3))
        if len(selected) >= max(0, maximum):
            break
    return sorted(selected)


def _normal_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", str(value or "").lower())


def _box_iou(left: Iterable[Any] | None, right: Iterable[Any] | None) -> float:
    a = list(left or [])
    b = list(right or [])
    if len(a) < 4 or len(b) < 4:
        return 0.0
    ax1, ay1, ax2, ay2 = map(_number, a[:4])
    bx1, by1, bx2, by2 = map(_number, b[:4])
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1) + max(0.0, bx2 - bx1) * max(0.0, by2 - by1) - intersection
    return intersection / union if union > 0 else 0.0


def merge_ocr_detections(detections: list[dict[str, Any]], *, maximum_gap: float = 2.5) -> list[dict[str, Any]]:
    rows = sorted((dict(item) for item in detections if _normal_text(item.get("text"))), key=lambda item: _number(item.get("time")))
    units: list[dict[str, Any]] = []
    for row in rows:
        time_value = _number(row.get("time"))
        normalized = _normal_text(row.get("text"))
        target = next((unit for unit in reversed(units[-20:]) if (
            normalized == unit["normalizedText"]
            and time_value - _number(unit.get("end")) <= maximum_gap
            and (_box_iou(unit.get("box"), row.get("box")) >= .25 or not row.get("box"))
        )), None)
        if target is None:
            units.append({
                "id": f"ocr_{len(units):05d}", "modality": "ocr",
                "start": round(time_value, 3), "end": round(time_value, 3),
                "text": str(row.get("text") or "")[:500], "normalizedText": normalized,
                "confidence": round(max(0.0, min(1.0, _number(row.get("confidence"), .5))), 3),
                "box": list(row.get("box") or []), "evidenceTimes": [round(time_value, 3)],
            })
        else:
            target["end"] = round(time_value, 3)
            target["confidence"] = round(max(_number(target.get("confidence")), _number(row.get("confidence"))), 3)
            target["evidenceTimes"].append(round(time_value, 3))
    return units


def _cosine(left: Iterable[Any], right: Iterable[Any]) -> float:
    a = np.asarray(list(left), dtype=np.float32)
    b = np.asarray(list(right), dtype=np.float32)
    if not a.size or a.shape != b.shape:
        return -1.0
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator > 0 else -1.0


def cluster_person_tracks(
    tracks: list[dict[str, Any]], *, similarity_threshold: float = .45,
    scene_cuts: Iterable[Any] | None = None, maximum_gap: float = 1.25,
) -> list[dict[str, Any]]:
    tracks = sorted((dict(item) for item in tracks if item.get("embedding")), key=lambda item: _number(item.get("start")))
    clusters: list[dict[str, Any]] = []
    for track in tracks:
        embedding = list(track.get("embedding") or [])
        candidates = [
            cluster for cluster in clusters
            if _cosine(cluster["centroid"], embedding) >= similarity_threshold
        ]
        cluster = max(candidates, key=lambda item: _cosine(item["centroid"], embedding), default=None)
        if cluster is None:
            cluster = {"tracks": [], "embeddings": [], "centroid": embedding}
            clusters.append(cluster)
        cluster["tracks"].append({key: value for key, value in track.items() if key != "embedding"})
        cluster["embeddings"].append(embedding)
        cluster["centroid"] = np.mean(np.asarray(cluster["embeddings"], dtype=np.float32), axis=0).tolist()
    result: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters):
        items = cluster["tracks"]
        observed_items = sorted(items, key=lambda item: _number(item.get("start")))
        representative = max(items, key=lambda item: (
            max(0.0, _number((item.get("box") or [0, 0, 0, 0])[2]) - _number((item.get("box") or [0, 0, 0, 0])[0]))
            * max(0.0, _number((item.get("box") or [0, 0, 0, 0])[3]) - _number((item.get("box") or [0, 0, 0, 0])[1]))
            * max(.1, _number(item.get("confidence"), .5))
        ))
        ranges: list[dict[str, float]] = []
        range_evidence: list[dict[str, Any]] = []
        cuts = sorted(_number(value) for value in scene_cuts or [])
        # A symmetric window is dangerous for appearance retrieval: the first
        # face observation often starts after a shot already contains another
        # person, so expanding backwards can put the wrong person into the
        # returned clip. Keep both sides tiny; continuity is recovered by
        # merging observations, not by padding into neighboring content.
        lead_window = min(.08, max(.04, maximum_gap * .08))
        trail_window = min(.08, max(.04, maximum_gap * .08))
        for item in observed_items:
            time_value = _number(item.get("start"))
            start = max(0.0, _number(item.get("start"), time_value) - lead_window)
            end = max(start + .1, _number(item.get("end"), time_value) + trail_window)
            crossed_cut = bool(ranges and any(ranges[-1]["end"] < cut < start for cut in cuts))
            if ranges and not crossed_cut and start - ranges[-1]["end"] <= maximum_gap:
                gap = max(0.0, time_value - _number(range_evidence[-1].get("lastObservedTime"), time_value))
                ranges[-1]["end"] = round(max(ranges[-1]["end"], end), 3)
                range_evidence[-1]["observedCount"] += 1
                range_evidence[-1]["maxObservedGap"] = round(max(
                    _number(range_evidence[-1].get("maxObservedGap")), gap,
                ), 3)
                range_evidence[-1]["lastObservedTime"] = round(time_value, 3)
            else:
                ranges.append({"start": round(start, 3), "end": round(end, 3)})
                range_evidence.append({
                    "observedCount": 1,
                    "maxObservedGap": 0.0,
                    "lastObservedTime": round(time_value, 3),
                })
        for evidence in range_evidence:
            evidence.pop("lastObservedTime", None)
            evidence["interpolated"] = bool(
                _number(evidence.get("maxObservedGap")) > max(.75, maximum_gap * .6)
            )
            evidence["confidence"] = round(
                max(.55, min(.98, .72 + min(.18, .03 * evidence["observedCount"])
                - (.1 if evidence["interpolated"] else 0))), 3,
            )
        result.append({
            "id": f"person_{index + 1}", "modality": "person",
            "label": f"人物 {chr(65 + index) if index < 26 else index + 1}",
            "text": f"人物 {chr(65 + index) if index < 26 else index + 1}",
            "start": ranges[0]["start"], "end": ranges[-1]["end"], "ranges": ranges,
            "rangeEvidence": range_evidence,
            "trackIds": [str(item.get("id") or "") for item in items],
            "trackCount": len(items), "confidence": round(min(1.0, .55 + .06 * len(items)), 3),
            "representativeTime": round(_number(representative.get("start")), 3),
            "representativeBox": [round(_number(value), 2) for value in representative.get("box") or []],
            "anonymous": True, "scope": "single_video",
        })
    return result


def conservative_face_speaker_links(
    persons: list[dict[str, Any]], speech_units: list[dict[str, Any]], *, minimum_turns: int = 3,
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    speakers = sorted({str(speaker) for unit in speech_units for speaker in unit.get("speakers") or [] if speaker})
    for speaker in speakers:
        turns = [unit for unit in speech_units if speaker in (unit.get("speakers") or [])]
        if len(turns) < minimum_turns:
            continue
        total = sum(max(.01, _number(unit.get("end")) - _number(unit.get("start"))) for unit in turns)
        ranked: list[tuple[dict[str, Any], float]] = []
        for person in persons:
            ranges = person.get("ranges") or [{"start": person.get("start"), "end": person.get("end")}]
            overlap = sum(
                max(0.0, min(_number(unit.get("end")), _number(span.get("end"))) - max(_number(unit.get("start")), _number(span.get("start"))))
                for unit in turns for span in ranges
            )
            ranked.append((person, overlap / total if total else 0.0))
        ranked.sort(key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] < .8 or (len(ranked) > 1 and ranked[1][1] > .25):
            continue
        links.append({
            "personId": ranked[0][0]["id"], "speaker": speaker,
            "confidence": round(ranked[0][1], 3), "turnCount": len(turns),
            "scope": "single_video", "anonymous": True,
        })
    return links


def evidence_ref(kind: str, unit_id: Any, *, start: Any = None, end: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": str(kind), "id": str(unit_id)}
    if start is not None:
        result["start"] = round(_number(start), 3)
    if end is not None:
        result["end"] = round(_number(end), 3)
    return result


def known_evidence_ids(index: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for field in (
        "shots", "speechUnits", "dialogueTurns", "visualUnits", "embeddingVisualUnits",
        "ocrUnits", "audioUnits", "personTracks", "persons",
    ):
        for item in index.get(field) or []:
            value = str(item.get("id") or item.get("unitId") or "")
            if value:
                ids.add(value)
    return ids


def ground_evidence_refs(
    refs: Iterable[dict[str, Any]], index: dict[str, Any],
    *, extra_evidence_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    allowed = known_evidence_ids(index) | {
        str(value) for value in (extra_evidence_ids or []) if str(value)
    }
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = (str(ref.get("type") or ""), str(ref.get("id") or ""))
        if not key[1] or key[1] not in allowed or key in seen:
            continue
        seen.add(key)
        result.append(dict(ref))
    return result


def write_embedding_matrix(path: Path, ids: list[str], matrix: Any, *, model: str) -> dict[str, Any]:
    values = np.asarray(matrix, dtype=np.float32)
    if values.ndim != 2 or values.shape[0] != len(ids):
        raise ValueError("embedding matrix shape does not match ids")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    values = values / np.maximum(norms, 1e-12)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, values.astype(np.float16), allow_pickle=False)
    manifest = {"path": path.name, "ids": list(ids), "shape": list(values.shape), "dtype": "float16", "model": model}
    path.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return manifest


def vector_recall(query: Iterable[Any], manifest: dict[str, Any], directory: Path, *, limit: int = 24) -> list[dict[str, Any]]:
    path = directory / str(manifest.get("path") or "")
    if not path.is_file():
        return []
    matrix = np.load(path, mmap_mode="r", allow_pickle=False).astype(np.float32)
    vector = np.asarray(list(query), dtype=np.float32)
    if matrix.ndim != 2 or vector.ndim != 1 or matrix.shape[1] != vector.shape[0]:
        return []
    vector /= max(float(np.linalg.norm(vector)), 1e-12)
    scores = matrix @ vector
    ids = list(manifest.get("ids") or [])
    ranked = np.argsort(scores)[::-1][:max(1, int(limit))]
    return [{"id": str(ids[index]), "score": round(float(scores[index]), 6)} for index in ranked if index < len(ids)]


def recognition_summary(index: dict[str, Any] | None, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = index if isinstance(index, dict) else {}
    coverage = dict(payload.get("modalityCoverage") or {})
    processed = {
        str(value) for value in payload.get("recognitionCompletedModalities") or [] if str(value)
    }
    available = {
        str(value) for value in payload.get("recognitionAvailableModalities") or [] if str(value)
    }
    if "recognitionCompletedModalities" in payload:
        coverage = {key: key in available for key in RECOGNITION_MODALITIES}
    elif "visual" in coverage:
        # Old light indexes counted navigation probes as visual recognition.
        # They are not semantic evidence, so only an actual embedding index
        # may advertise visual coverage during legacy-cache reuse.
        coverage["visual"] = bool(payload.get("embeddingVisualUnits"))
    counts = {
        "shots": len(payload.get("shots") or []),
        "speech": len(payload.get("speechUnits") or []),
        # Lightweight probe timestamps are navigation hints, not semantic
        # recognition. Only actual embedding/VLM evidence counts as visual
        # coverage in the user-facing summary.
        "visual": len(payload.get("embeddingVisualUnits") or []),
        "ocr": len(payload.get("ocrUnits") or []),
        "audio": len(payload.get("audioUnits") or []),
        "persons": len(payload.get("persons") or []),
        "dialogueTurns": len(payload.get("dialogueTurns") or []),
        "responseBlocks": len((payload.get("dialogueGraph") or {}).get("responseBlocks") or []),
    }
    return {
        "schemaVersion": RECOGNITION_SCHEMA_VERSION,
        "indexVersion": payload.get("schemaVersion") or MULTIMODAL_INDEX_VERSION,
        "status": payload.get("status") or "not_started",
        "profile": payload.get("recognitionProfile") or {},
        "modalityCoverage": coverage,
        "counts": counts,
        "requestedModalities": list(payload.get("recognitionRequestedModalities") or []),
        "processedModalities": sorted(processed),
        "availableModalities": sorted(available),
        "skippedModalities": list(payload.get("recognitionSkippedModalities") or []),
        "degradedReasons": list(payload.get("degradedReasons") or []),
        "dialogue": {
            key: (payload.get("dialogueGraph") or {}).get(key)
            for key in ("schemaVersion", "status", "coverageComplete", "classifiedTurnCount", "turnCount")
            if (payload.get("dialogueGraph") or {}).get(key) is not None
        },
        "capabilities": capabilities or {},
    }
