from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .speech import (
    SPEECH_REQUEST_LEASE_SECONDS,
    _analyze_sensevoice, _resolve_sensevoice_device, _sensevoice_instance,
)


def write_json(path: Path, value: dict[str, Any]) -> None:
    value = dict(value)
    if path.name == "status.json":
        value.setdefault("updatedAt", time.time())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    worker_directory = Path(config.pop("worker_directory"))
    config.pop("runtime_version", None)
    config["model_cache"] = Path(config["model_cache"])
    status_path = worker_directory / "status.json"
    requests = worker_directory / "requests"
    results = worker_directory / "results"
    requests.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    # Requests are owned by a live web-process lease. Discard leftovers from
    # crashes/restarts so they can never run hours later without a user job.
    now = time.time()
    for request_path in requests.glob("*.json"):
        lease_path = requests / f"{request_path.stem}.lease"
        try:
            live = now - lease_path.stat().st_mtime <= SPEECH_REQUEST_LEASE_SECONDS
        except OSError:
            live = False
        if not live:
            request_path.unlink(missing_ok=True)
            lease_path.unlink(missing_ok=True)
            (requests / f"{request_path.stem}.cancel").unlink(missing_ok=True)
    for marker in [*requests.glob("*.cancel"), *requests.glob("*.lease")]:
        if not (requests / f"{marker.stem}.json").is_file():
            marker.unlink(missing_ok=True)
    for result_path in results.glob("*.json"):
        try:
            if now - result_path.stat().st_mtime > 24 * 60 * 60:
                result_path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        selected_device = _resolve_sensevoice_device(str(config.get("device") or "auto"))
        config["device"] = selected_device
        write_json(status_path, {
            "status": "preparing", "device": selected_device, "error": None, "pid": os.getpid(),
        })
        _, actual_device = _sensevoice_instance(**config)
        write_json(status_path, {
            "status": "ready", "device": actual_device, "error": None,
            "pid": os.getpid(), "loadedAt": time.time(),
        })
    except Exception as error:
        write_json(status_path, {
            "status": "failed", "device": None, "error": str(error)[:1000], "pid": os.getpid(),
        })
        return 1
    while True:
        pending = sorted(requests.glob("*.json"), key=lambda path: path.stat().st_mtime)
        if not pending:
            time.sleep(.2)
            continue
        request_path = pending[0]
        request_id = request_path.stem
        cancel_path = requests / f"{request_id}.cancel"
        lease_path = requests / f"{request_id}.lease"
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request_id = str(request["id"])
            cancel_path = requests / f"{request_id}.cancel"
            lease_path = requests / f"{request_id}.lease"

            def request_is_live() -> bool:
                try:
                    lease_fresh = time.time() - lease_path.stat().st_mtime <= SPEECH_REQUEST_LEASE_SECONDS
                except OSError:
                    return False
                return lease_fresh and time.time() < float(request.get("deadlineAt") or float("inf"))

            if cancel_path.is_file() or not request_is_live():
                cancel_path.unlink(missing_ok=True)
                request_path.unlink(missing_ok=True)
                lease_path.unlink(missing_ok=True)
                continue
            write_json(status_path, {"status": "running", "phase": "recognizing", "device": config.get("device"), "error": None, "pid": os.getpid(), "requestId": request_id, "progress": 0.0, "processed": 0, "total": None})
            has_intermediate_progress = False
            def report_progress(*args: Any) -> None:
                nonlocal has_intermediate_progress
                # FunASR invokes this callback between inference batches. Turn
                # the filesystem cancellation marker into an exception here
                # instead of waiting for model.generate() to finish the whole
                # recording before noticing it.
                if cancel_path.is_file():
                    raise RuntimeError("任务已取消")
                if not request_is_live():
                    raise RuntimeError("请求租约已失效，识别已停止")
                numeric = [item for item in args if isinstance(item, (int, float))]
                processed = numeric[0] if numeric else None
                total = numeric[1] if len(numeric) > 1 else None
                raw_value = (
                    float(processed) / float(total)
                    if processed is not None and total is not None and float(total) > 1
                    else (float(processed) if processed is not None else None)
                )
                raw_value = max(0.0, min(1.0, raw_value)) if raw_value is not None else None
                finalizing = raw_value is not None and raw_value >= 1.0
                if raw_value is not None and 0.0 < raw_value < 1.0:
                    has_intermediate_progress = True
                # The model callback reaching 1.0 only means that its audio
                # batches have been consumed. model.generate() may still be
                # merging VAD segments, punctuation and speaker information.
                # Reserve the real 100% for the result file becoming ready.
                value = None if finalizing or not has_intermediate_progress else raw_value
                phase = "finalizing" if finalizing else ("recognizing_measured" if has_intermediate_progress else "recognizing")
                write_json(status_path, {"status": "running", "phase": phase, "device": config.get("device"), "error": None, "pid": os.getpid(), "requestId": request_id, "progress": value, "processed": processed, "total": total})
            payload = _analyze_sensevoice(
                Path(request["source"]), **config, cancelled=cancel_path.is_file, progress_callback=report_progress,
                preset_speaker_count=int(request.get("presetSpeakerCount") or 0) or None,
            )
            write_json(status_path, {"status": "running", "phase": "finalizing", "device": config.get("device"), "error": None, "pid": os.getpid(), "requestId": request_id, "progress": None, "processed": None, "total": None})
            write_json(results / f"{request_id}.json", {"payload": payload})
        except Exception as error:
            write_json(results / f"{request_id}.json", {"error": str(error)[:2000]})
        finally:
            request_path.unlink(missing_ok=True)
            cancel_path.unlink(missing_ok=True)
            write_json(status_path, {"status": "ready", "device": config.get("device"), "error": None, "pid": os.getpid(), "loadedAt": time.time()})


if __name__ == "__main__":
    raise SystemExit(main())
