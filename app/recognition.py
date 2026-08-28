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
CONTINUITY_MULTIMODAL_INDEX_VERSION = "multimodal-index-v8-continuity"
PREVIOUS_MULTIMODAL_INDEX_VERSION = "multimodal-index-v9-person-continuity"
MULTIMODAL_INDEX_VERSION = "multimodal-index-v11-face-anchored-person-identity"
RECOGNITION_SCHEMA_VERSION = 10
RECOGNITION_MODALITIES = ("speech", "visual", "ocr", "audio", "person")

PERSON_TRACK_CONTINUITY_GAP_SECONDS = 2.0
PERSON_IDENTITY_SIMILARITY_THRESHOLD = .42
PERSON_DUPLICATE_REVIEW_SIMILARITY = .62
PERSON_SAME_FRAME_TOLERANCE_SECONDS = .05
PERSON_SAMPLE_SUPPORT_SECONDS = .3
PERSON_SCENE_CUT_BRIDGE_GAP_SECONDS = 1.1
PERSON_SCENE_CUT_BRIDGE_SIMILARITY = .72
# SFace's published generic threshold is too permissive for this pipeline's
# compressed, interview-style crops: different men in the regression asset
# reach .461 cosine similarity, while repeated observations of the same five
# people stay at or above .661. Keep a measured safety margin between them.
PERSON_FACE_MATCH_SIMILARITY = .58
PERSON_FACE_CONFLICT_SIMILARITY = .50


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
    yolox = Path(getattr(settings, "recognition_yolox_model", ""))
    youtureid = Path(getattr(settings, "recognition_youtureid_model", ""))
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
            "status": "ready" if enabled and all(path.is_file() for path in (yunet, sface, yolox, youtureid)) else "degraded",
            "reason": "" if all(path.is_file() for path in (yunet, sface, yolox, youtureid)) else "person_body_or_face_models_not_prepared",
            "detector": "OpenCV Zoo YOLOX",
            "reId": "OpenCV Zoo YoutuReID",
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
    inferred_end = max((_number(shot.get("end"), lower) for shot in shots), default=lower)
    upper = max(lower, _number(end, inferred_end)) if end is not None else max(lower, inferred_end)
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
        # The media duration is the first instant *after* the last decodable
        # frame. Requesting that exact timestamp makes ffmpeg legitimately
        # return one frame fewer and used to leave otherwise complete scans at
        # 99.9% forever. Scene-cut boundaries remain valid samples; only the
        # terminal source boundary is moved slightly inside the asset.
        terminal_boundary = upper is not None and shot_end >= upper - .0005
        terminal_margin = min(.05, max(.001, (shot_end - shot_start) * .25))
        final_sample = max(shot_start, shot_end - terminal_margin) if terminal_boundary else shot_end
        values.add(round(final_sample, 3))
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


def _center_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_box, right_box = list(left.get("box") or []), list(right.get("box") or [])
    if len(left_box) < 4 or len(right_box) < 4:
        return 1.0
    left_center = ((_number(left_box[0]) + _number(left_box[2])) / 2, (_number(left_box[1]) + _number(left_box[3])) / 2)
    right_center = ((_number(right_box[0]) + _number(right_box[2])) / 2, (_number(right_box[1]) + _number(right_box[3])) / 2)
    width = max(1.0, _number(left.get("frameWidth"), _number(right.get("frameWidth"), 1)))
    height = max(1.0, _number(left.get("frameHeight"), _number(right.get("frameHeight"), 1)))
    return min(1.0, math.hypot((left_center[0] - right_center[0]) / width, (left_center[1] - right_center[1]) / height) * 2)


def link_body_tracklets(
    detections: list[dict[str, Any]], *, maximum_gap: float = .65,
    scene_cuts: Iterable[Any] | None = None,
) -> list[dict[str, Any]]:
    """Associate dense body detections without carrying identity across edits.

    A fixed interview camera can place several consecutive people inside an
    almost identical box.  Spatial continuity is useful inside a shot, but it
    is not identity evidence across a cut.  Reset active tracklets whenever a
    scene boundary is crossed and let the identity clusterer reconnect only
    when ReID or a face anchor supports it.
    """
    from scipy.optimize import linear_sum_assignment

    rows = sorted((dict(item) for item in detections), key=lambda item: (_number(item.get("start")), str(item.get("id") or "")))
    cuts = sorted(_number(value) for value in scene_cuts or [])
    by_time: dict[float, list[dict[str, Any]]] = {}
    for row in rows:
        by_time.setdefault(round(_number(row.get("start")), 3), []).append(row)
    active: dict[str, dict[str, Any]] = {}
    next_track = 1
    result: list[dict[str, Any]] = []
    for time_value, frame_rows in sorted(by_time.items()):
        active = {
            key: value for key, value in active.items()
            if time_value - _number(value.get("start")) <= maximum_gap
            and not any(
                _number(value.get("start")) < cut <= time_value
                for cut in cuts
            )
        }
        track_ids = list(active)
        assignments: dict[int, str] = {}
        if track_ids and frame_rows:
            cost = np.full((len(track_ids), len(frame_rows)), 10.0, dtype=np.float32)
            for left_index, track_id in enumerate(track_ids):
                previous = active[track_id]
                for right_index, detection in enumerate(frame_rows):
                    similarity = _cosine(previous.get("embedding") or [], detection.get("embedding") or [])
                    previous_face = list(previous.get("faceEmbedding") or [])
                    detection_face = list(detection.get("faceEmbedding") or [])
                    face_similarity = (
                        _cosine(previous_face, detection_face)
                        if previous_face and detection_face else None
                    )
                    if (
                        face_similarity is not None
                        and face_similarity < PERSON_FACE_CONFLICT_SIMILARITY
                    ):
                        # Some fixed-camera edits are too visually similar for
                        # the generic scene detector. A conflicting face is a
                        # stronger boundary than box overlap or clothing ReID.
                        continue
                    iou = _box_iou(previous.get("box"), detection.get("box"))
                    center = _center_distance(previous, detection)
                    value = .48 * (1 - max(-1.0, similarity)) / 2 + .32 * (1 - iou) + .20 * center
                    if face_similarity is not None and face_similarity >= PERSON_FACE_MATCH_SIMILARITY:
                        value = max(0.0, value - .12)
                    if similarity >= .2 or iou >= .08:
                        cost[left_index, right_index] = value
            left_indices, right_indices = linear_sum_assignment(cost)
            for left_index, right_index in zip(left_indices.tolist(), right_indices.tolist()):
                if float(cost[left_index, right_index]) <= .62:
                    assignments[right_index] = track_ids[left_index]
        for index, detection in enumerate(frame_rows):
            track_id = assignments.get(index)
            if not track_id:
                track_id = f"body_track_{next_track:05d}"
                next_track += 1
            detection["trackletId"] = track_id
            active[track_id] = detection
            result.append(detection)
    return result


def cluster_person_tracks(
    tracks: list[dict[str, Any]], *, similarity_threshold: float = PERSON_IDENTITY_SIMILARITY_THRESHOLD,
    scene_cuts: Iterable[Any] | None = None,
    maximum_gap: float = PERSON_TRACK_CONTINUITY_GAP_SECONDS,
    algorithm_version: str = "editing-algorithm-v1",
) -> list[dict[str, Any]]:
    tracks = sorted((dict(item) for item in tracks if item.get("embedding")), key=lambda item: _number(item.get("start")))
    identity_scene_cuts = sorted(_number(value) for value in scene_cuts or [])
    clusters: list[dict[str, Any]] = []
    for track in tracks:
        embedding = list(track.get("embedding") or [])
        face_embedding = list(track.get("faceEmbedding") or [])
        # Faces detected in one sampled frame are a hard cannot-link pair.  It
        # lets us use a slightly more tolerant identity threshold for pose and
        # lighting changes without merging two people who are visibly present
        # at the same time.
        tracklet_id = str(track.get("trackletId") or "")
        track_time = _number(track.get("start"))

        def identity_profile(cluster: dict[str, Any]) -> dict[str, Any]:
            body_similarity = _cosine(cluster["centroid"], embedding)
            cluster_face = list(cluster.get("faceCentroid") or [])
            face_similarity = (
                _cosine(cluster_face, face_embedding)
                if cluster_face and face_embedding else None
            )
            last_time = max((_number(value.get("start")) for value in cluster.get("tracks") or []), default=-1)
            crossed_shot = any(last_time < cut <= track_time for cut in identity_scene_cuts)
            required = similarity_threshold + (.1 if algorithm_version == "editing-algorithm-v2" and crossed_shot else 0)
            return {
                "body": body_similarity,
                "face": face_similarity,
                "sameTracklet": bool(tracklet_id and tracklet_id in cluster.get("trackletIds", set())),
                "crossedShot": crossed_shot,
                "required": min(.9, required),
            }

        def identity_eligible(profile: dict[str, Any]) -> bool:
            face_similarity = profile["face"]
            if face_similarity is not None:
                # Once both sides have a face anchor it owns the identity
                # decision.  Body appearance must not override a conflicting
                # face merely because several interviewees occupy the same
                # fixed camera position.
                if face_similarity >= PERSON_FACE_MATCH_SIMILARITY:
                    return True
                return bool(
                    profile["sameTracklet"]
                    and not profile["crossedShot"]
                    and face_similarity >= PERSON_FACE_CONFLICT_SIMILARITY
                )
            if profile["sameTracklet"] and not profile["crossedShot"]:
                return True
            return profile["body"] >= profile["required"]

        candidates = [
            (cluster, identity_profile(cluster)) for cluster in clusters
            if not any(
                abs(_number(existing.get("start")) - _number(track.get("start")))
                <= PERSON_SAME_FRAME_TOLERANCE_SECONDS
                for existing in cluster["tracks"]
            )
        ]
        candidates = [item for item in candidates if identity_eligible(item[1])]

        def identity_rank(item: tuple[dict[str, Any], dict[str, Any]]) -> tuple[float, float, float]:
            profile = item[1]
            face_similarity = profile["face"]
            face_priority = 2.0 if face_similarity is not None and face_similarity >= PERSON_FACE_MATCH_SIMILARITY else (
                1.0 if profile["sameTracklet"] else 0.0
            )
            return (
                face_priority,
                face_similarity if face_similarity is not None else profile["body"],
                profile["body"],
            )

        ranked_candidates = sorted(
            candidates, key=identity_rank, reverse=True,
        )
        cluster = ranked_candidates[0][0] if ranked_candidates else None
        best_profile = ranked_candidates[0][1] if ranked_candidates else None
        if (
            algorithm_version == "editing-algorithm-v2" and cluster is not None
            and best_profile is not None
            and not best_profile["sameTracklet"]
            and not (
                best_profile["face"] is not None
                and best_profile["face"] >= PERSON_FACE_MATCH_SIMILARITY
            )
            and len(ranked_candidates) > 1
            and best_profile["body"] - ranked_candidates[1][1]["body"] < .06
        ):
            cluster = None
        if cluster is None:
            cluster = {
                "tracks": [], "embeddings": [], "centroid": embedding,
                "faceEmbeddings": [], "faceCentroid": [], "trackletIds": set(),
            }
            clusters.append(cluster)
        public_track = {
            key: value for key, value in track.items()
            if key not in {"embedding", "faceEmbedding"}
        }
        # Retain the embedding only while constructing continuity ranges. It is
        # never exposed in the anonymous-person index or persisted as UI data.
        public_track["_continuityEmbedding"] = embedding
        public_track["_continuityFaceEmbedding"] = face_embedding
        cluster["tracks"].append(public_track)
        if tracklet_id:
            cluster["trackletIds"].add(tracklet_id)
        cluster["embeddings"].append(embedding)
        cluster["centroid"] = np.mean(np.asarray(cluster["embeddings"], dtype=np.float32), axis=0).tolist()
        if face_embedding:
            cluster["faceEmbeddings"].append(face_embedding)
            cluster["faceCentroid"] = np.mean(
                np.asarray(cluster["faceEmbeddings"], dtype=np.float32), axis=0,
            ).tolist()
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
        lead_window = min(PERSON_SAMPLE_SUPPORT_SECONDS, max(.12, maximum_gap * .15))
        trail_window = min(PERSON_SAMPLE_SUPPORT_SECONDS, max(.12, maximum_gap * .15))
        for item in observed_items:
            time_value = _number(item.get("start"))
            start = max(0.0, _number(item.get("start"), time_value) - lead_window)
            end = max(start + .1, _number(item.get("end"), time_value) + trail_window)
            previous_cut = max((cut for cut in cuts if cut <= time_value), default=None)
            next_cut = min((cut for cut in cuts if cut > time_value), default=None)
            if previous_cut is not None:
                start = max(start, previous_cut)
            if next_cut is not None:
                end = min(end, next_cut)
            end = max(start + .1, end)
            previous_observed_time = (
                _number(range_evidence[-1].get("lastObservedTime")) if range_evidence else time_value
            )
            crossed_cut = bool(
                ranges and any(previous_observed_time < cut <= time_value for cut in cuts)
            )
            previous_embedding = range_evidence[-1].get("_lastEmbedding") if range_evidence else None
            continuity_similarity = _cosine(previous_embedding or [], item.get("_continuityEmbedding") or [])
            cut_bridge_threshold = max(
                PERSON_SCENE_CUT_BRIDGE_SIMILARITY,
                min(.96, similarity_threshold + .18),
            )
            short_confident_cut = bool(
                crossed_cut
                and time_value - previous_observed_time <= PERSON_SCENE_CUT_BRIDGE_GAP_SECONDS
                and continuity_similarity >= cut_bridge_threshold
            )
            if ranges and (not crossed_cut or short_confident_cut) and start - ranges[-1]["end"] <= maximum_gap:
                gap = max(0.0, time_value - _number(range_evidence[-1].get("lastObservedTime"), time_value))
                ranges[-1]["end"] = round(max(ranges[-1]["end"], end), 3)
                range_evidence[-1]["observedCount"] += 1
                range_evidence[-1]["maxObservedGap"] = round(max(
                    _number(range_evidence[-1].get("maxObservedGap")), gap,
                ), 3)
                range_evidence[-1]["lastObservedTime"] = round(time_value, 3)
                range_evidence[-1]["_lastEmbedding"] = item.get("_continuityEmbedding") or []
                if short_confident_cut:
                    range_evidence[-1]["sceneCutBridgeCount"] += 1
            else:
                ranges.append({"start": round(start, 3), "end": round(end, 3)})
                range_evidence.append({
                "observedCount": 1,
                    "maxObservedGap": 0.0,
                    "lastObservedTime": round(time_value, 3),
                    "sceneCutBridgeCount": 0,
                    "_lastEmbedding": item.get("_continuityEmbedding") or [],
                })
        for range_index, evidence in enumerate(range_evidence):
            evidence.pop("lastObservedTime", None)
            evidence.pop("_lastEmbedding", None)
            evidence["interpolated"] = bool(
                _number(evidence.get("maxObservedGap")) > max(.75, maximum_gap * .6)
                or int(evidence.get("sceneCutBridgeCount") or 0) > 0
            )
            if algorithm_version == "editing-algorithm-v2":
                evidence["status"] = (
                    "face_confirmed" if any(
                        str(item.get("identityStatus") or "") == "face_confirmed"
                        and ranges[range_index]["start"] - .001 <= _number(item.get("start")) <= ranges[range_index]["end"] + .001
                        for item in observed_items
                    ) else "body_tracked"
                )
                evidence["confidence"] = round(max(.5, min(.96,
                    .58
                    + (.18 if evidence["status"] == "face_confirmed" else .08)
                    + min(.12, .02 * math.sqrt(evidence["observedCount"]))
                    - (.12 if evidence["interpolated"] else 0)
                )), 3)
                if evidence["confidence"] < .62:
                    evidence["status"] = "possible"
            else:
                evidence["confidence"] = round(
                    max(.55, min(.98, .72 + min(.18, .03 * evidence["observedCount"])
                    - (.1 if evidence["interpolated"] else 0))), 3,
                )
        appearance_seconds = sum(max(0.0, item["end"] - item["start"]) for item in ranges)
        face_anchor_count = len(cluster.get("faceEmbeddings") or [])
        result.append({
            "id": f"person_{index + 1}", "modality": "person",
            "label": f"人物 {chr(65 + index) if index < 26 else index + 1}",
            "text": f"人物 {chr(65 + index) if index < 26 else index + 1}",
            "start": ranges[0]["start"], "end": ranges[-1]["end"], "ranges": ranges,
            "rangeEvidence": range_evidence,
            "trackIds": [str(item.get("id") or "") for item in items],
            "trackCount": len(items), "confidence": (
                round(float(np.mean([_number(value.get("confidence"), .5) for value in range_evidence])), 3)
                if algorithm_version == "editing-algorithm-v2" and range_evidence
                else round(min(1.0, .55 + .06 * len(items)), 3)
            ),
            "confidenceCalibration": "person-identity-v3-face-anchor" if algorithm_version == "editing-algorithm-v2" else "legacy-observation-count",
            "faceAnchorCount": face_anchor_count,
            "appearanceSeconds": round(appearance_seconds, 3),
            "reviewRecommended": (
                len(items) < 3 or appearance_seconds < 1.0
                or (algorithm_version == "editing-algorithm-v2" and face_anchor_count == 0)
            ),
            "representativeTime": round(_number(representative.get("start")), 3),
            "representativeBox": [round(_number(value), 2) for value in representative.get("box") or []],
            "anonymous": True, "scope": "single_video",
        })
    # A same-frame cannot-link is still the safest automatic decision for a
    # normal shot.  Split screens, mirrors and replay overlays are the notable
    # exception: the same real person can legitimately occur twice in one
    # frame.  Surface very similar cluster centroids for human review instead
    # of silently merging them (which would be destructive for real groups of
    # lookalike people).
    duplicate_threshold = max(PERSON_DUPLICATE_REVIEW_SIMILARITY, similarity_threshold + .12)
    for left_index, left_cluster in enumerate(clusters):
        for right_index in range(left_index + 1, len(clusters)):
            right_cluster = clusters[right_index]
            body_similarity = _cosine(
                left_cluster.get("centroid") or [], right_cluster.get("centroid") or [],
            )
            left_face = left_cluster.get("faceCentroid") or []
            right_face = right_cluster.get("faceCentroid") or []
            face_similarity = _cosine(left_face, right_face) if left_face and right_face else None
            if face_similarity is not None:
                duplicate = face_similarity >= PERSON_FACE_MATCH_SIMILARITY
                similarity = face_similarity
                evidence_type = "face_anchor"
            else:
                duplicate = body_similarity >= duplicate_threshold
                similarity = body_similarity
                evidence_type = "body_reid"
            if not duplicate:
                continue
            left_person = result[left_index]
            right_person = result[right_index]
            left_person.setdefault("possibleDuplicatePersonIds", []).append(right_person["id"])
            right_person.setdefault("possibleDuplicatePersonIds", []).append(left_person["id"])
            left_person["duplicateReviewRecommended"] = True
            right_person["duplicateReviewRecommended"] = True
            left_person["duplicateEvidenceType"] = evidence_type
            right_person["duplicateEvidenceType"] = evidence_type
            left_person["duplicateSimilarity"] = round(max(
                _number(left_person.get("duplicateSimilarity")), similarity,
            ), 3)
            right_person["duplicateSimilarity"] = round(max(
                _number(right_person.get("duplicateSimilarity")), similarity,
            ), 3)
            left_person["duplicateBodySimilarity"] = round(max(
                _number(left_person.get("duplicateBodySimilarity")), body_similarity,
            ), 3)
            right_person["duplicateBodySimilarity"] = round(max(
                _number(right_person.get("duplicateBodySimilarity")), body_similarity,
            ), 3)
            left_person["reviewRecommended"] = True
            right_person["reviewRecommended"] = True
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
