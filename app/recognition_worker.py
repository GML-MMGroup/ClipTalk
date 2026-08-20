from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from .recognition_pipeline import enrich_multimodal_index


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.recognition_worker REQUEST.json")
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    owner_pid = int(request.get("ownerPid") or 0)
    progress_path = Path(request["progressPath"])

    def owner_alive() -> bool:
        if owner_pid <= 0:
            return True
        try:
            os.kill(owner_pid, 0)
            return True
        except OSError:
            return False

    def report(fraction: float, detail: str) -> None:
        if not owner_alive():
            raise RuntimeError("识别任务所属服务进程已退出")
        write_json(progress_path, {
            "fraction": max(0.0, min(1.0, float(fraction))),
            "detail": str(detail), "heartbeatAt": time.time(),
            "workerPid": os.getpid(), "ownerPid": owner_pid,
        })
    raw_settings = dict(request.get("settings") or {})
    for key in ("recognition_yunet_model", "recognition_sface_model", "recognition_model_cache"):
        raw_settings[key] = Path(raw_settings[key])
    result = enrich_multimodal_index(
        source=Path(request["source"]), root=Path(request["root"]),
        duration=float(request["duration"]), scene_cuts=list(request.get("sceneCuts") or []),
        transcript_segments=list(request.get("transcriptSegments") or []),
        speech_units=list(request.get("speechUnits") or []), settings=SimpleNamespace(**raw_settings),
        recognition_profile=str(request.get("recognitionProfile") or "auto"),
        requested_modalities=list(request.get("requestedModalities") or []),
        speech_analysis_complete=bool(request.get("speechAnalysisComplete")),
        scope_start=float(request.get("scopeStart") or 0),
        scope_end=float(request["scopeEnd"]) if request.get("scopeEnd") is not None else None,
        ffmpeg=str(request["ffmpeg"]),
        progress=report,
        cancelled=lambda: not owner_alive(),
    )
    write_json(Path(request["responsePath"]), result)


if __name__ == "__main__":
    main()
