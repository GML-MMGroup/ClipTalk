from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable


ACTIVE_SPEAKER_PROTOCOL_VERSION = "videopilot-asd-v2"
_RUNTIME_PROBE_LOCK = threading.Lock()
_RUNTIME_PROBE_CACHE: dict[str, Any] = {"key": "", "checkedAt": 0.0, "ready": False, "reason": ""}
ACTIVE_SPEAKER_WORKER_REVISION = "multi-target-windowed-identity-gate-v3"


def _talknet_progress_snapshot(
    root: Path, response_path: Path, expected_frames: int, *, started_wall_time: float,
) -> dict[str, Any]:
    """Describe the latest observable TalkNet phase without inventing progress.

    The official TalkNet demo writes one artifact after each major phase.  Frame
    extraction is the only phase with a trustworthy numerator and denominator;
    the later phases are therefore milestone-based and intentionally
    indeterminate within each milestone.
    """
    # demoTalkNet receives ``--videoFolder .../window-000`` and
    # ``--videoName input``, so its artifacts live below
    # ``talknet-official/window-000/input``. Keep the old location as a
    # fallback for caches produced by earlier workers.
    official_root = root / "talknet-official" / "window-000" / "input"
    if official_root.exists():
        input_roots = sorted((root / "talknet-official").glob("window-*/input"))
    else:
        official_root = root / "talknet-official" / "input"
        input_roots = [official_root]
    input_roots = input_roots or [official_root]
    frame_roots = [path / "pyframes" for path in input_roots]
    work_roots = [path / "pywork" for path in input_roots]
    crop_roots = [path / "pycrop" for path in input_roots]

    def current_file(path: Path) -> bool:
        try:
            # A TalkNet cache directory is content-addressed by source and
            # worker revision. Existing artifacts are valid work for this
            # run; requiring a fresh mtime made a long identity-gate phase
            # appear as ``0/N frames`` after the service restarted.
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    try:
        completed_frames = min(
            expected_frames,
            sum(
                1 for frame_root in frame_roots
                for path in frame_root.glob("*.jpg") if current_file(path)
            ),
        )
    except OSError:
        completed_frames = 0

    if current_file(response_path):
        return {"phase": "complete", "fraction": 1.0}
    if all(current_file(work_root / "scores.pckl") for work_root in work_roots):
        return {"phase": "finalizing", "fraction": .98}
    if all(current_file(work_root / "tracks.pckl") for work_root in work_roots):
        return {"phase": "av_scoring", "fraction": .90}
    if all(current_file(work_root / "faces.pckl") for work_root in work_roots):
        try:
            crop_count = sum(
                1 for crop_root in crop_roots
                for path in crop_root.glob("*.avi") if current_file(path)
            )
        except OSError:
            crop_count = 0
        return {"phase": "track_building", "fraction": .78, "completed": crop_count}
    if all(current_file(work_root / "scene.pckl") for work_root in work_roots):
        return {"phase": "face_detection", "fraction": .62}
    if completed_frames >= expected_frames:
        return {"phase": "scene_detection", "fraction": .55}
    frame_fraction = completed_frames / max(1, expected_frames)
    return {
        "phase": "frame_extraction",
        "fraction": round(.52 * frame_fraction, 4),
        "completed": completed_frames,
        "total": expected_frames,
        "unit": "帧",
    }


def _emit_talknet_progress(
    progress: Callable[[dict[str, Any]], None] | None, payload: dict[str, Any],
) -> None:
    if progress:
        progress(payload)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def active_speaker_runtime(settings: Any, *, probe: bool = True) -> dict[str, Any]:
    mode = str(getattr(settings, "active_speaker_mode", "shadow") or "shadow").lower()
    python = Path(str(getattr(settings, "talknet_worker_python", "") or ""))
    script = Path(str(getattr(settings, "talknet_worker_script", "") or ""))
    checkpoint = Path(str(getattr(settings, "talknet_checkpoint", "") or ""))
    repository = Path(str(getattr(settings, "talknet_repository", "") or ""))
    files_ready = (
        mode != "off" and python.is_file() and script.is_file() and checkpoint.is_file()
        and (repository / "demoTalkNet.py").is_file()
    )
    missing = [
        label for label, path in (
            ("worker_python", python), ("worker_script", script), ("checkpoint", checkpoint),
            ("repository", repository / "demoTalkNet.py"),
        ) if not path.is_file()
    ]
    ready = files_ready
    reason = "" if files_ready else "active_speaker_disabled" if mode == "off" else f"talknet_missing:{','.join(missing)}"
    if files_ready and not probe:
        # The health endpoint is called during frontend bootstrap. Do not
        # synchronously import CUDA/TalkNet there; the real worker will probe
        # itself when an active-speaker task actually needs to run.
        ready = False
        reason = "talknet_probe_deferred"
    elif files_ready:
        try:
            stat_material = ":".join(
                f"{path}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
                for path in (python, script, checkpoint, repository / "demoTalkNet.py")
            )
            probe_key = hashlib.sha256(f"{stat_material}:{getattr(settings, 'talknet_device', '')}".encode()).hexdigest()
            now = time.monotonic()
            with _RUNTIME_PROBE_LOCK:
                cached = _RUNTIME_PROBE_CACHE.copy()
                if cached.get("key") == probe_key and now - float(cached.get("checkedAt") or 0) < 60:
                    ready = bool(cached.get("ready"))
                    reason = str(cached.get("reason") or "")
                else:
                    process = subprocess.run(
                        [
                            str(python), str(script), "--healthcheck",
                            "--repository", str(repository),
                            "--checkpoint", str(checkpoint),
                            "--device", str(getattr(settings, "talknet_device", "cuda:0") or "cuda:0"),
                        ],
                        # Health is queried during every frontend bootstrap. A
                        # broken CUDA/TalkNet environment must degrade quickly
                        # instead of holding the whole UI on a 15s request.
                        capture_output=True, text=True, check=False, timeout=3,
                    )
                    ready = process.returncode == 0
                    detail = (process.stderr or process.stdout or "worker healthcheck failed").strip()[-300:]
                    reason = "" if ready else f"talknet_probe_failed:{detail}"
                    _RUNTIME_PROBE_CACHE.update({
                        "key": probe_key, "checkedAt": now, "ready": ready, "reason": reason,
                    })
        except (OSError, subprocess.SubprocessError) as error:
            ready = False
            reason = f"talknet_probe_failed:{str(error)[:180]}"
    return {
        "backend": "talknet", "protocolVersion": ACTIVE_SPEAKER_PROTOCOL_VERSION,
        "mode": mode if mode in {"off", "shadow", "primary"} else "shadow",
        "status": "ready" if ready else "disabled" if mode == "off" else "degraded",
        "coverageComplete": bool(ready),
        "reason": reason,
        "device": str(getattr(settings, "talknet_device", "cuda:0") or "cuda:0"),
    }


def _validated_rows(
    payload: dict[str, Any], *, start: float, end: float, field: str = "matches",
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in payload.get(field) or []:
        if not isinstance(source, dict):
            continue
        row_start = max(start, _number(source.get("start"), -1.0))
        row_end = min(end, _number(source.get("end"), -1.0))
        score = max(0.0, min(1.0, _number(source.get("score"))))
        if row_start < start or row_end <= row_start or score <= 0:
            continue
        evidence_times = sorted({
            round(value, 3) for value in (_number(item, -1.0) for item in source.get("evidenceTimes") or [])
            if row_start - .1 <= value <= row_end + .1
        })
        normalized = {
            "start": round(row_start, 3), "end": round(row_end, 3),
            "score": round(score, 4), "evidenceTimes": evidence_times,
            "trackIds": [str(item) for item in source.get("trackIds") or [] if str(item)],
        }
        official_track_ids = [
            str(item) for item in source.get("officialTrackIds") or [] if str(item)
        ]
        if official_track_ids:
            normalized["officialTrackIds"] = official_track_ids
        result.append(normalized)
    result.sort(key=lambda item: (item["start"], item["end"]))
    return result


def calibrate_diarized_speaker(
    active_speaker_rows: list[dict[str, Any]], speech_units: list[dict[str, Any]],
) -> dict[str, Any]:
    """Associate a face with a diarized speaker using repeated ASD evidence."""
    available_speakers = sorted({
        str(value).strip()
        for unit in speech_units if isinstance(unit, dict)
        for value in unit.get("speakers") or [] if str(value).strip()
    })
    overlap_by_speaker: dict[str, float] = {}
    intervals_by_speaker: dict[str, int] = {}
    for row in active_speaker_rows:
        start, end = _number(row.get("start")), _number(row.get("end"))
        if end <= start:
            continue
        row_overlaps: dict[str, float] = {}
        for unit in speech_units:
            overlap = max(
                0.0,
                min(end, _number(unit.get("end"))) - max(start, _number(unit.get("start"))),
            )
            if overlap <= 0:
                continue
            for speaker in {str(value).strip() for value in unit.get("speakers") or [] if str(value).strip()}:
                row_overlaps[speaker] = row_overlaps.get(speaker, 0.0) + overlap
        if not row_overlaps:
            continue
        row_best, row_best_overlap = max(row_overlaps.items(), key=lambda item: item[1])
        for speaker, overlap in row_overlaps.items():
            overlap_by_speaker[speaker] = overlap_by_speaker.get(speaker, 0.0) + overlap
        if row_best_overlap / max(.001, end - start) >= .5:
            intervals_by_speaker[row_best] = intervals_by_speaker.get(row_best, 0) + 1
    ranked = sorted(overlap_by_speaker.items(), key=lambda item: (-item[1], item[0]))
    if not ranked:
        return {"speaker": None, "confidence": 0.0, "evidenceIntervals": 0, "overlapSeconds": 0.0}
    best_speaker, best_overlap = ranked[0]
    second_overlap = ranked[1][1] if len(ranked) > 1 else 0.0
    purity = best_overlap / max(.001, sum(overlap_by_speaker.values()))
    margin = (best_overlap - second_overlap) / max(.001, best_overlap)
    evidence_intervals = intervals_by_speaker.get(best_speaker, 0)
    # A single diarization label is not identity evidence.  Backends sometimes
    # collapse a multi-person interview into one coarse ``Speaker 1`` stream;
    # overlap purity is then trivially 1.0 for every visible face.  TalkNet may
    # still provide valid per-face speaking boundaries, but it must not turn
    # that non-discriminative label into a global person-to-speaker binding.
    diarization_is_discriminative = len(available_speakers) >= 2
    accepted = (
        diarization_is_discriminative
        and best_overlap >= 2.0 and evidence_intervals >= 2
        and purity >= .8 and margin >= .25
    )
    confidence = min(
        .98,
        .45 + .3 * purity + .1 * min(1.0, evidence_intervals / 3.0) + .15 * margin,
    ) if accepted else 0.0
    return {
        "speaker": best_speaker if accepted else None,
        "confidence": round(confidence, 3),
        "evidenceIntervals": evidence_intervals,
        "overlapSeconds": round(best_overlap, 3),
        "purity": round(purity, 3),
        "margin": round(margin, 3),
        "availableSpeakers": available_speakers,
        "reason": "" if accepted else (
            "insufficient_diarization_diversity" if not diarization_is_discriminative
            else "insufficient_calibration_evidence"
        ),
        "candidates": [
            {"speaker": speaker, "overlapSeconds": round(overlap, 3)}
            for speaker, overlap in ranked
        ],
    }


def _failed_runtime(runtime: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    return {
        **runtime,
        "status": "degraded",
        "reason": reason,
        "coverageComplete": False,
        "matches": [],
        **extra,
    }


def run_talknet_active_speakers(
    *, source: Path, work_directory: Path, source_hash: str, persons: list[dict[str, Any]],
    person_tracks: list[dict[str, Any]], speech_units: list[dict[str, Any]],
    scope_start: float, scope_end: float, settings: Any,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run an isolated TalkNet-compatible worker using a strict JSON protocol.

    The worker owns model-specific dependencies. It receives only project-local
    anonymous track IDs and must return grounded source-time intervals. This
    keeps the web process independent from TalkNet's legacy Python environment.
    """
    runtime = active_speaker_runtime(settings)
    if runtime["status"] != "ready":
        return {**runtime, "attempted": False, "matches": []}
    person_ids = list(dict.fromkeys(
        str(person.get("id") or "") for person in persons if str(person.get("id") or "")
    ))
    targets: list[dict[str, Any]] = []
    for person_id in person_ids:
        person = next(item for item in persons if str(item.get("id") or "") == person_id)
        candidate_tracks = [item for item in person_tracks
            if str(item.get("personId") or "") == person_id
            and isinstance(item.get("box"), list) and len(item.get("box") or []) == 4
        ]
        relevant_sources = [
            item for item in candidate_tracks
            if scope_start <= _number(item.get("start")) <= scope_end
        ]
        # A candidate-level boundary retry may cover a range without one of
        # the sparse reusable reference frames. Keep the nearest grounded face
        # references so the worker can still identify the requested person.
        if not relevant_sources and candidate_tracks:
            center = (scope_start + scope_end) * .5
            relevant_sources = sorted(
                candidate_tracks, key=lambda item: abs(_number(item.get("start")) - center),
            )[:3]
        relevant_tracks = [{
            "id": str(item.get("id") or ""),
            "time": round(_number(item.get("start")), 3),
            "box": [round(_number(value), 2) for value in item.get("box") or []],
            "frameWidth": max(1, int(_number(item.get("frameWidth"), 640))),
        } for item in relevant_sources]
        if relevant_tracks:
            targets.append({
                "id": person_id,
                "referenceTime": _number(person.get("representativeTime")),
                "referenceBox": list(person.get("representativeBox") or []),
                "targetTracks": relevant_tracks,
            })
    speech_ranges = [{
        "id": str(item.get("id") or ""),
        "start": round(max(scope_start, _number(item.get("start"))), 3),
        "end": round(min(scope_end, _number(item.get("end"))), 3),
    } for item in speech_units if _number(item.get("end")) > scope_start and _number(item.get("start")) < scope_end]
    # Safe contiguous-window acceleration: only narrow the official scan when
    # the selected person's reference anchors are concentrated. Sparse anchors
    # spanning most of the video retain the strict full-scope scan.
    anchor_times = [
        _number(track.get("time")) for target in targets
        for track in target.get("targetTracks") or []
        if scope_start <= _number(track.get("time")) <= scope_end
    ]
    scan_start, scan_end = scope_start, scope_end
    scan_windows: list[dict[str, float]] = []
    if len(anchor_times) >= 2:
        proposed_start = max(scope_start, min(anchor_times) - 12.0)
        proposed_end = min(scope_end, max(anchor_times) + 12.0)
        if proposed_end - proposed_start <= (scope_end - scope_start) * .65:
            scan_start, scan_end = proposed_start, proposed_end
    if len(anchor_times) >= 3:
        raw_windows = sorted((max(scope_start, time_value - 12.0), min(scope_end, time_value + 12.0)) for time_value in anchor_times)
        for start, end in raw_windows:
            if scan_windows and start <= scan_windows[-1]["end"] + 20.0:
                scan_windows[-1]["end"] = round(max(scan_windows[-1]["end"], end), 3)
            else:
                scan_windows.append({"start": round(start, 3), "end": round(end, 3)})
        # Each official TalkNet invocation loads a sizeable model. Coalesce
        # the nearest gaps until at most six invocations remain; the added
        # scan seconds are cheaper than repeatedly paying model startup cost.
        while len(scan_windows) > 6:
            gaps = [
                (scan_windows[index + 1]["start"] - scan_windows[index]["end"], index)
                for index in range(len(scan_windows) - 1)
            ]
            _, index = min(gaps)
            scan_windows[index]["end"] = scan_windows[index + 1]["end"]
            del scan_windows[index + 1]
        if sum(item["end"] - item["start"] for item in scan_windows) > (scope_end - scope_start) * .65:
            scan_windows = []
    scan_scope = {"start": round(scan_start, 3), "end": round(scan_end, 3), "mode": "windows" if scan_windows else ("bounded" if scan_start > scope_start or scan_end < scope_end else "full")}
    if not targets:
        return {
            **runtime, "attempted": False, "reason": "no_target_tracks", "coverageComplete": False,
            "resultsByPerson": {person_id: {"matches": [], "presenceMatches": []} for person_id in person_ids},
        }

    cache_material = json.dumps({
        "protocol": ACTIVE_SPEAKER_PROTOCOL_VERSION,
        "sourceHash": source_hash,
        "scope": [round(scope_start, 3), round(scope_end, 3)],
        "scanScope": scan_scope,
        "scanWindows": scan_windows,
        "checkpoint": {
            "path": str(getattr(settings, "talknet_checkpoint", "")),
            "size": Path(str(getattr(settings, "talknet_checkpoint", ""))).stat().st_size,
            "mtimeNs": Path(str(getattr(settings, "talknet_checkpoint", ""))).stat().st_mtime_ns,
        },
        "workerProtocol": ACTIVE_SPEAKER_PROTOCOL_VERSION,
        "workerRevision": ACTIVE_SPEAKER_WORKER_REVISION,
        "talknetRepository": str(getattr(settings, "talknet_repository", "")),
    }, ensure_ascii=False, sort_keys=True)
    cache_key = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
    root = work_directory / "active-speaker" / cache_key
    target_material = json.dumps({
        "targets": [{
            "id": item["id"],
            "trackIds": [track["id"] for track in item["targetTracks"]],
        } for item in targets],
    }, ensure_ascii=False, sort_keys=True)
    target_key = hashlib.sha256(target_material.encode("utf-8")).hexdigest()[:20]
    request_path = root / f"request-{target_key}.json"
    response_path = root / f"response-{target_key}.json"

    def normalized_results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw = payload.get("resultsByPerson") if isinstance(payload.get("resultsByPerson"), dict) else {}
        results: dict[str, dict[str, Any]] = {}
        for person_id in person_ids:
            person_payload = raw.get(person_id) if isinstance(raw.get(person_id), dict) else {}
            # Keep the documented single-person facade compatible with v1
            # workers that return top-level matches. Production uses the v2
            # batch shape, but local/isolated workers may still implement the
            # strict legacy protocol.
            if not person_payload and len(person_ids) == 1 and isinstance(payload.get("matches"), list):
                person_payload = payload
            results[person_id] = {
                "matches": _validated_rows(
                    person_payload,
                    start=scope_start, end=scope_end,
                ),
                "presenceMatches": _validated_rows(
                    person_payload,
                    start=scope_start, end=scope_end, field="presenceMatches",
                ),
            }
        return results
    if response_path.is_file():
        try:
            cached = json.loads(response_path.read_text(encoding="utf-8"))
            if cached.get("protocolVersion") == ACTIVE_SPEAKER_PROTOCOL_VERSION:
                return {
                    **runtime, "attempted": True, "cacheHit": True,
                    "resultsByPerson": normalized_results(cached),
                    "modelVersion": str(cached.get("modelVersion") or ""),
                    "coverageComplete": True,
                    "elapsedMilliseconds": 0.0,
                }
        except (OSError, TypeError, ValueError):
            pass
    root.mkdir(parents=True, exist_ok=True)
    request_payload = {
        "protocolVersion": ACTIVE_SPEAKER_PROTOCOL_VERSION,
        "sourcePath": str(source), "sourceHash": source_hash,
        "targets": targets, "speechRanges": speech_ranges,
        "scope": {"start": scope_start, "end": scope_end},
        "scanScope": scan_scope,
        "scanWindows": scan_windows,
        "talknetRepository": str(getattr(settings, "talknet_repository", "")),
        "checkpoint": str(getattr(settings, "talknet_checkpoint", "")),
        "device": runtime["device"], "outputPath": str(response_path),
        "lockPath": str(root / ".talknet-worker.lock"),
        "identityGate": {
            "modelPath": str(getattr(settings, "recognition_sface_model", "")),
            "threshold": 0.58,
        },
    }
    request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    expected_frames = max(1, int(math.ceil((sum(item["end"] - item["start"] for item in scan_windows) if scan_windows else scan_end - scan_start) * 25)))
    _emit_talknet_progress(progress, {"phase": "starting", "fraction": 0.0})
    started = time.monotonic()
    started_wall_time = time.time()
    command = [
        str(getattr(settings, "talknet_worker_python")),
        str(getattr(settings, "talknet_worker_script")),
        "--request", str(request_path), "--response", str(response_path),
    ]
    timeout_seconds = max(10.0, _number(getattr(settings, "talknet_timeout_seconds", 900.0), 900.0))
    try:
        process = subprocess.Popen(
            # TalkNet's legacy demo writes one status line per frame. The API
            # observes progress through artifacts, so piping stdout/stderr
            # here would eventually fill the OS pipe and deadlock the worker
            # before it can produce its response.
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        return _failed_runtime(
            runtime, f"talknet_worker_failed:{str(error)[:180]}", attempted=True,
            elapsedMilliseconds=round((time.monotonic() - started) * 1000, 1),
        )
    stopped_reason = ""
    last_progress_at = 0.0
    while process.poll() is None:
        elapsed = time.monotonic() - started
        if progress and elapsed - last_progress_at >= 2.0:
            progress(_talknet_progress_snapshot(
                root, response_path, expected_frames, started_wall_time=started_wall_time,
            ))
            last_progress_at = elapsed
        if cancelled and cancelled():
            stopped_reason = "talknet_cancelled"
        elif elapsed >= timeout_seconds:
            stopped_reason = "talknet_timeout"
        if stopped_reason:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                pass
            break
        time.sleep(.5)
    if stopped_reason:
        return _failed_runtime(
            runtime, stopped_reason, attempted=True,
            elapsedMilliseconds=round((time.monotonic() - started) * 1000, 1),
        )
    stdout, stderr = process.communicate()
    if process.returncode != 0 or not response_path.is_file():
        detail = (stderr or stdout or "missing response").strip()[-500:]
        return _failed_runtime(
            runtime, f"talknet_worker_exit_{process.returncode}:{detail}", attempted=True,
            elapsedMilliseconds=round((time.monotonic() - started) * 1000, 1),
        )
    try:
        payload = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as error:
        return _failed_runtime(runtime, f"talknet_invalid_response:{error}", attempted=True)
    if payload.get("protocolVersion") != ACTIVE_SPEAKER_PROTOCOL_VERSION:
        return _failed_runtime(runtime, "talknet_protocol_mismatch", attempted=True)
    _emit_talknet_progress(progress, {"phase": "complete", "fraction": 1.0})
    return {
        **runtime, "attempted": True, "cacheHit": False,
        "resultsByPerson": normalized_results(payload),
        "modelVersion": str(payload.get("modelVersion") or ""),
        "coverageComplete": True,
        "elapsedMilliseconds": round((time.monotonic() - started) * 1000, 1),
    }


def run_talknet_active_speaker(
    *, source: Path, work_directory: Path, source_hash: str, person: dict[str, Any],
    person_tracks: list[dict[str, Any]], speech_units: list[dict[str, Any]],
    scope_start: float, scope_end: float, settings: Any,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Backward-compatible single-target facade over the v2 batch worker."""
    result = run_talknet_active_speakers(
        source=source, work_directory=work_directory, source_hash=source_hash,
        persons=[person], person_tracks=person_tracks, speech_units=speech_units,
        scope_start=scope_start, scope_end=scope_end, settings=settings,
        progress=progress, cancelled=cancelled,
    )
    person_result = (result.get("resultsByPerson") or {}).get(str(person.get("id") or ""), {})
    return {
        **{key: value for key, value in result.items() if key != "resultsByPerson"},
        "matches": list(person_result.get("matches") or []),
        "presenceMatches": list(person_result.get("presenceMatches") or []),
    }
