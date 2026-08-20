#!/usr/bin/env python3
"""VideoPilot JSON adapter for the official TalkNet-ASD demo pipeline.

This file is executed by the isolated TalkNet Python environment. The official
repository and pretrained checkpoint remain external so their dependencies do
not leak into the VideoPilot web process.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import pickle
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PROTOCOL = "videopilot-asd-v2"
FPS = 25.0
IDENTITY_GATE_VERSION = "sface-v1"
S3FD_WEIGHT_FILE_ID = "1KafnHz7ccT-3IyddBsL5yi2xGtxAKypt"


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def iou(left: list[Any], right: list[Any]) -> float:
    if len(left) != 4 or len(right) != 4:
        return 0.0
    ax1, ay1, ax2, ay2 = map(number, left)
    bx1, by1, bx2, by2 = map(number, right)
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1) + max(0.0, bx2 - bx1) * max(0.0, by2 - by1) - intersection
    return intersection / union if union > 0 else 0.0


def track_box_at(track: dict[str, Any], frame_number: int) -> list[float] | None:
    frames = track.get("track", {}).get("frame")
    boxes = track.get("track", {}).get("bbox")
    if frames is None or boxes is None or len(frames) == 0:
        return None
    first, last = int(frames[0]), int(frames[-1])
    if frame_number < first or frame_number > last:
        return None
    offset = frame_number - first
    if offset < 0 or offset >= len(boxes):
        return None
    return [number(value) for value in boxes[offset]]


def target_talknet_tracks(
    tracks: list[dict[str, Any]], target_tracks: list[dict[str, Any]], scope_start: float,
    *, source_frame_width: int,
) -> list[tuple[int, list[str], float]]:
    ranked: list[tuple[int, list[str], float, int]] = []
    for position, track in enumerate(tracks):
        overlaps: list[tuple[float, str]] = []
        for target in target_tracks:
            frame_number = int(round((number(target.get("time")) - scope_start) * FPS))
            box = track_box_at(track, frame_number)
            if box is None:
                continue
            coordinate_width = max(1.0, number(target.get("frameWidth"), 640.0))
            scale = max(1.0, float(source_frame_width)) / coordinate_width
            target_box = [number(value) * scale for value in target.get("box") or []]
            score = iou(box, target_box)
            if score >= .2:
                overlaps.append((score, str(target.get("id") or "")))
        if not overlaps:
            continue
        best = sorted((value for value, _ in overlaps), reverse=True)[:5]
        mean = sum(best) / len(best)
        ranked.append((position, list(dict.fromkeys(track_id for _, track_id in overlaps if track_id)), mean, len(overlaps)))
    if not ranked:
        return []
    # Multiple official tracks can represent the same person across cuts. Keep
    # every sufficiently supported track, not just the global best one.
    maximum_support = max(item[3] for item in ranked)
    return [
        (position, track_ids, similarity)
        for position, track_ids, similarity, support in ranked
        if similarity >= .3 and (support >= 2 or similarity >= .55 or support == maximum_support)
    ]


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-12.0, min(12.0, value))))


def identity_mask_from_similarities(
    similarities: list[float], *, threshold: float = .58, max_gap_frames: int = 5,
) -> list[bool]:
    """Threshold and smooth SFace similarities without bridging cuts."""
    mask = [number(value, -1.0) >= threshold for value in similarities]
    index = 0
    while index < len(mask):
        if mask[index]:
            index += 1
            continue
        start = index
        while index < len(mask) and not mask[index]:
            index += 1
        if start > 0 and index < len(mask) and index - start <= max_gap_frames:
            mask[start:index] = [True] * (index - start)
    return mask


def _anchor_frames_for_track(
    track: dict[str, Any], target_tracks: list[dict[str, Any]], scope_start: float,
    *, source_frame_width: int,
) -> list[int]:
    raw_frames = track.get("track", {}).get("frame")
    frames = list(raw_frames) if raw_frames is not None else []
    first = int(frames[0]) if frames else 0
    result: list[int] = []
    for target in target_tracks:
        frame_number = int(round((number(target.get("time")) - scope_start) * FPS))
        box = track_box_at(track, frame_number)
        if box is None:
            continue
        scale = max(1.0, float(source_frame_width)) / max(1.0, number(target.get("frameWidth"), 640.0))
        target_box = [number(value) * scale for value in target.get("box") or []]
        if iou(box, target_box) >= .2:
            result.append(frame_number - first)
    return result


def _crop_identity_similarities(
    crop_path: Path, reference_frames: list[int], *, model_path: Path,
) -> list[float] | None:
    """Compare TalkNet crops against target anchor crops with local SFace."""
    if not model_path.is_file() or not reference_frames:
        return None
    try:
        import cv2
        import numpy as np
        recognizer = cv2.FaceRecognizerSF.create(str(model_path), "")
        capture = cv2.VideoCapture(str(crop_path))
        if not capture.isOpened():
            return None
        frames: list[Any] = []
        while True:
            ok, image = capture.read()
            if not ok:
                break
            frames.append(image)
        capture.release()
        refs = []
        for frame_number in reference_frames:
            if 0 <= frame_number < len(frames):
                feature = recognizer.feature(cv2.resize(frames[frame_number], (112, 112))).reshape(-1).astype(np.float32)
                feature /= max(float(np.linalg.norm(feature)), 1e-12)
                refs.append(feature)
        if not refs:
            return None
        reference = np.mean(np.stack(refs), axis=0)
        reference /= max(float(np.linalg.norm(reference)), 1e-12)
        # SFace is substantially more expensive than TalkNet's ASD scoring.
        # Sample long tracks more sparsely and expand the result; identity
        # cuts are seconds long, while this keeps short detector dropouts
        # smooth. Short tracks retain finer boundary resolution.
        sample_stride = 3 if len(frames) <= 300 else 5
        sampled: dict[int, float] = {}
        for offset in range(0, len(frames), sample_stride):
            image = frames[offset]
            feature = recognizer.feature(cv2.resize(image, (112, 112))).reshape(-1).astype(np.float32)
            feature /= max(float(np.linalg.norm(feature)), 1e-12)
            sampled[offset] = float(np.dot(reference, feature))
        values: list[float] = []
        for offset in range(len(frames)):
            nearest = min(sampled, key=lambda item: abs(item - offset))
            values.append(sampled[nearest])
        return values
    except Exception:
        return None


def ensure_s3fd_weight(repository: Path) -> None:
    """Prepare the official detector weight inside the isolated runtime.

    TalkNet's import-time fallback invokes a bare ``gdown`` executable. The
    worker is launched with an absolute virtualenv Python path, so that console
    script is not necessarily on PATH even though the module is installed.
    Calling it through this interpreter makes first-run setup deterministic.
    """
    target = repository / "model" / "faceDetector" / "s3fd" / "sfd_face.pth"
    if target.is_file() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [sys.executable, "-m", "gdown", "--id", S3FD_WEIGHT_FILE_ID, "-O", str(target)],
        cwd=str(repository), capture_output=True, text=True, check=False,
    )
    if process.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        detail = (process.stderr or process.stdout or "download failed").strip()[-500:]
        raise RuntimeError(f"TalkNet S3FD weight download failed: {detail}")


def intervals_from_track(
    track: dict[str, Any], raw_scores: Any, *, scope_start: float, scope_end: float,
    track_ids: list[str], similarity: float, identity_mask: list[bool] | None = None,
) -> list[dict[str, Any]]:
    frame_values = track.get("track", {}).get("frame")
    frames = list(frame_values) if frame_values is not None else []
    scores = [number(value) for value in raw_scores]
    active: list[tuple[float, float]] = []
    for offset, frame_value in enumerate(frames[:len(scores)]):
        if identity_mask is not None and (offset >= len(identity_mask) or not identity_mask[offset]):
            continue
        window = scores[max(0, offset - 2):min(len(scores), offset + 3)]
        smoothed = sum(window) / max(1, len(window))
        if smoothed < 0:
            continue
        timestamp = scope_start + number(frame_value) / FPS
        if scope_start <= timestamp <= scope_end:
            active.append((timestamp, sigmoid(smoothed) * min(1.0, .65 + similarity * .35)))
    if not active:
        return []
    groups: list[list[tuple[float, float]]] = []
    for item in active:
        if groups and item[0] - groups[-1][-1][0] <= .12:
            groups[-1].append(item)
        else:
            groups.append([item])
    result: list[dict[str, Any]] = []
    for group in groups:
        start, end = group[0][0], min(scope_end, group[-1][0] + 1.0 / FPS)
        if end - start < .16:
            continue
        evidence = [round(value, 3) for value, _ in group[::max(1, len(group) // 12)]]
        result.append({
            "start": round(start, 3), "end": round(end, 3),
            "score": round(sum(value for _, value in group) / len(group), 4),
            "evidenceTimes": evidence, "trackIds": track_ids,
        })
    return result


def presence_intervals_from_track(
    track: dict[str, Any], *, scope_start: float, scope_end: float,
    track_ids: list[str], similarity: float, official_track_id: str,
    identity_mask: list[bool] | None = None,
) -> list[dict[str, Any]]:
    frame_values = track.get("track", {}).get("frame")
    frames = [number(value) for value in frame_values] if frame_values is not None else []
    visible = [scope_start + frame / FPS for offset, frame in enumerate(frames)
        if (identity_mask is None or (offset < len(identity_mask) and identity_mask[offset]))
        and scope_start <= scope_start + frame / FPS <= scope_end]
    if not visible:
        return []
    groups: list[list[float]] = []
    for timestamp in visible:
        if groups and timestamp - groups[-1][-1] <= .12:
            groups[-1].append(timestamp)
        else:
            groups.append([timestamp])
    return [{
        "start": round(group[0], 3),
        "end": round(min(scope_end, group[-1] + 1.0 / FPS), 3),
        "score": round(max(.01, min(1.0, similarity)), 4),
        "evidenceTimes": [
            round(value, 3) for value in group[::max(1, len(group) // 12)]
        ],
        "trackIds": track_ids,
        "officialTrackIds": [official_track_id],
    } for group in groups if min(scope_end, group[-1] + 1.0 / FPS) - group[0] >= .16]


def run(request: dict[str, Any], response_path: Path) -> None:
    if request.get("protocolVersion") != PROTOCOL:
        raise RuntimeError("unsupported protocol")
    source = Path(str(request.get("sourcePath") or ""))
    repository = Path(str(request.get("talknetRepository") or ""))
    checkpoint = Path(str(request.get("checkpoint") or ""))
    if not source.is_file() or not (repository / "demoTalkNet.py").is_file() or not checkpoint.is_file():
        raise RuntimeError("TalkNet source, repository, or checkpoint is missing")
    ensure_s3fd_weight(repository)
    scope = request.get("scope") or {}
    scope_start = max(0.0, number(scope.get("start")))
    scope_end = max(scope_start, number(scope.get("end")))
    scan_scope = request.get("scanScope") if isinstance(request.get("scanScope"), dict) else {}
    scan_start = max(scope_start, number(scan_scope.get("start"), scope_start))
    scan_end = min(scope_end, max(scan_start, number(scan_scope.get("end"), scope_end)))
    work = response_path.parent / "talknet-official"
    work.mkdir(parents=True, exist_ok=True)
    requested_windows = [item for item in request.get("scanWindows") or [] if isinstance(item, dict)]
    windows = [(max(scope_start, number(item.get("start"))), min(scope_end, number(item.get("end")))) for item in requested_windows]
    windows = [(start, end) for start, end in windows if end - start >= .5]
    if not windows:
        windows = [(scan_start, scan_end)]
    extraction_start = float(math.floor(scan_start))
    track_records: list[tuple[dict[str, Any], Any, Path]] = []
    source_frame_width = 640
    for window_index, (window_start, window_end) in enumerate(windows):
        window_root = work / f"window-{window_index:03d}"
        window_root.mkdir(parents=True, exist_ok=True)
        input_path = window_root / f"input{source.suffix.lower() or '.mp4'}"
        if not input_path.exists():
            try:
                os.symlink(source, input_path)
            except OSError:
                shutil.copy2(source, input_path)
        result_root = window_root / "input" / "pywork"
        tracks_path, scores_path = result_root / "tracks.pckl", result_root / "scores.pckl"
        if not tracks_path.is_file() or not scores_path.is_file():
            command = [
                sys.executable, str(repository / "demoTalkNet.py"),
                "--videoName", "input", "--videoFolder", str(window_root),
                "--pretrainModel", str(checkpoint), "--nDataLoaderThread", "4",
                "--start", str(int(math.floor(window_start))),
                "--duration", str(max(1, int(math.ceil(window_end - math.floor(window_start))))),
                "--noVisualization",
            ]
            environment = dict(os.environ)
            device = str(request.get("device") or "cuda:0")
            if device.startswith("cuda:"):
                environment["CUDA_VISIBLE_DEVICES"] = device.split(":", 1)[1]
            process = subprocess.run(command, cwd=str(repository), env=environment, capture_output=True, text=True, check=False)
            if process.returncode != 0:
                raise RuntimeError((process.stderr or process.stdout or "TalkNet failed")[-2000:])
        with tracks_path.open("rb") as handle:
            window_tracks = pickle.load(handle)
        with scores_path.open("rb") as handle:
            window_scores = pickle.load(handle)
        frame_offset = int(round((math.floor(window_start) - extraction_start) * FPS))
        crop_root = window_root / "input" / "pycrop"
        for position, track in enumerate(window_tracks):
            frames = track.get("track", {}).get("frame")
            if frames is not None:
                track = dict(track)
                track_data = dict(track.get("track") or {})
                track_data["frame"] = [int(value) + frame_offset for value in list(frames)]
                track["track"] = track_data
            crop_path = crop_root / f"{position:05d}.avi"
            track_records.append((track, window_scores[position] if position < len(window_scores) else [], crop_path))
        frame_paths = sorted((window_root / "input" / "pyframes").glob("*.jpg"))
        if frame_paths and source_frame_width == 640:
            sample_frame = __import__("cv2").imread(str(frame_paths[0]))
            if sample_frame is not None:
                source_frame_width = int(sample_frame.shape[1])
    if not track_records:
        raise RuntimeError("TalkNet did not produce any tracks")
    tracks = [item[0] for item in track_records]
    scores = [item[1] for item in track_records]
    crop_paths = [item[2] for item in track_records]
    # Official --start is integer-valued in its CLI; align frames to that
    # actual extraction origin rather than the fractional query scope.
    extraction_start = float(math.floor(scan_start))
    targets = [item for item in request.get("targets") or [] if isinstance(item, dict) and item.get("id")]
    identity_gate = request.get("identityGate") if isinstance(request.get("identityGate"), dict) else {}
    identity_model_path = Path(str(identity_gate.get("modelPath") or ""))
    identity_threshold = number(identity_gate.get("threshold"), .58)
    candidates_by_person = {
        str(target["id"]): target_talknet_tracks(
            tracks, list(target.get("targetTracks") or []), extraction_start,
            source_frame_width=source_frame_width,
        ) for target in targets
    }
    # One official face track may satisfy at most one selected anonymous
    # person. This prevents duplicate person cards from fabricating co-presence.
    ownership: dict[int, tuple[str, float]] = {}
    for person_id, candidates in candidates_by_person.items():
        for position, _track_ids, similarity in candidates:
            if position not in ownership or similarity > ownership[position][1]:
                ownership[position] = (person_id, similarity)
    results_by_person: dict[str, dict[str, Any]] = {}
    for person_id, candidates in candidates_by_person.items():
        matches: list[dict[str, Any]] = []
        presence: list[dict[str, Any]] = []
        selected = [item for item in candidates if ownership.get(item[0], ("", 0))[0] == person_id]
        person_target_tracks = next(
            (list(target.get("targetTracks") or []) for target in targets if str(target.get("id")) == person_id), []
        )
        for position, track_ids, similarity in selected:
            official_track_id = f"talknet_track_{position}"
            track = tracks[position]
            anchor_frames = _anchor_frames_for_track(
                track, person_target_tracks, extraction_start, source_frame_width=source_frame_width,
            )
            similarities = _crop_identity_similarities(
                crop_paths[position], anchor_frames,
                model_path=identity_model_path,
            )
            # Fail closed: an unverified whole track is exactly the behavior
            # that can include a different person after a cut.
            identity_mask = identity_mask_from_similarities(
                similarities, threshold=identity_threshold,
            ) if similarities is not None else None
            if identity_mask is None:
                continue
            presence.extend(presence_intervals_from_track(
                track, scope_start=extraction_start, scope_end=scope_end,
                track_ids=track_ids, similarity=similarity, official_track_id=official_track_id,
                identity_mask=identity_mask,
            ))
            if position >= len(scores):
                continue
            rows = intervals_from_track(
                track, scores[position], scope_start=extraction_start,
                scope_end=scope_end, track_ids=track_ids, similarity=similarity,
                identity_mask=identity_mask,
            )
            for row in rows:
                row["officialTrackIds"] = [official_track_id]
            matches.extend(rows)
        matches.sort(key=lambda item: (item["start"], item["end"]))
        presence.sort(key=lambda item: (item["start"], item["end"]))
        results_by_person[person_id] = {
            "matches": matches, "presenceMatches": presence,
            "selectedTrackCount": len(selected),
        }
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps({
        "protocolVersion": PROTOCOL, "modelVersion": checkpoint.name,
        "resultsByPerson": results_by_person,
        "provenance": {
            "repository": str(repository), "officialTrackCount": len(tracks),
            "selectedTrackCount": sum(
                int(value.get("selectedTrackCount") or 0) for value in results_by_person.values()
            ), "threshold": "smoothed_logit>=0; identity_cosine>=%.2f" % identity_threshold,
            "identityGate": IDENTITY_GATE_VERSION,
            "scanScope": {"start": round(scan_start, 3), "end": round(scan_end, 3), "mode": str(scan_scope.get("mode") or "full")},
            "sourceFrameWidth": source_frame_width,
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request")
    parser.add_argument("--response")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--repository")
    parser.add_argument("--checkpoint")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    try:
        if args.healthcheck:
            repository = Path(str(args.repository or ""))
            checkpoint = Path(str(args.checkpoint or ""))
            if not (repository / "demoTalkNet.py").is_file():
                raise RuntimeError("TalkNet repository is incomplete")
            if not checkpoint.is_file() or checkpoint.stat().st_size < 1024 * 1024:
                raise RuntimeError("TalkNet checkpoint is missing or incomplete")
            import cv2  # noqa: F401
            import numpy  # noqa: F401
            requested_device = str(args.device)
            if requested_device.startswith("cuda:"):
                os.environ["CUDA_VISIBLE_DEVICES"] = requested_device.split(":", 1)[1]
            import torch
            if requested_device.startswith("cuda"):
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA is not available in the isolated TalkNet runtime")
                float(torch.ones(1, device="cuda").cpu()[0])
            print(json.dumps({
                "protocolVersion": PROTOCOL,
                "status": "ready",
                "device": args.device,
            }))
            return 0
        if not args.request or not args.response:
            raise RuntimeError("--request and --response are required")
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        response_path = Path(args.response)
        lock_path = Path(str(request.get("lockPath") or response_path.parent / ".talknet-worker.lock"))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock_handle:
            # Keep serialization inside the isolated worker. The descriptor
            # survives a web-service restart, so a replacement worker waits
            # and then reuses the first valid response instead of rerunning
            # the full GPU scan.
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            if response_path.is_file():
                try:
                    cached = json.loads(response_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    cached = {}
                if cached.get("protocolVersion") == PROTOCOL:
                    return 0
            run(request, response_path)
        return 0
    except Exception as error:
        print(f"TalkNet worker failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
