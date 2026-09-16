"""Read-only union of formal task outputs and independently retained copies."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from .output_naming import build_output_naming


def library_outputs(jobs: Iterable[dict[str, Any]], retained: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    task_ids: set[str] = set()
    for job in jobs:
        job_id = str(job.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", job_id) or job_id in {".", ".."}:
            continue
        task_ids.add(job_id)
        if not job.get("outputDirectory"):
            continue
        directory = Path(job["outputDirectory"]).resolve()
        versions = job.get("outputVersions") or [{"number": 1, "outputs": job.get("outputs") or []}]
        for version in versions:
            if version.get("previewOnly"):
                continue
            for position, item in enumerate(version.get("outputs") or [], 1):
                filename = str(item.get("filename") or "")
                if item.get("previewOnly") or item.get("outputKind") in {
                    "agent_review_preview", "review_preview", "social_reframe_preview", "cover_intro_review_preview",
                }:
                    continue
                if not filename or Path(filename).name != filename or not filename.lower().endswith(".mp4"):
                    continue
                path = (directory / filename).resolve()
                try:
                    if path.parent != directory or not path.is_file():
                        continue
                    size = path.stat().st_size
                except OSError:
                    continue
                url = f"/api/jobs/{quote(job_id, safe='')}/outputs/{quote(filename, safe='')}"
                naming = build_output_naming(job, version, item, position=position, output_count=len(version.get("outputs") or []))
                records[job_id, filename] = {
                    **naming, "jobId": job_id, "filename": filename,
                    "versionId": version.get("id"), "versionNumber": version.get("number") or 1,
                    "sourceFilename": job.get("filename") or "", "duration": item.get("duration") or 0,
                    "width": item.get("width"), "height": item.get("height"), "sizeBytes": size,
                    "createdAt": version.get("createdAt") or item.get("createdAt") or job.get("createdAt") or "",
                    "videoUrl": url + "/browser-preview", "downloadUrl": url + "?download=1",
                    "coverUrl": url + "/cover" if (item.get("coverVersionId") or version.get("coverVersionId")) else None,
                    "coverVersionId": item.get("coverVersionId") or version.get("coverVersionId"),
                    "coverContentHash": item.get("coverContentHash") or version.get("coverContentHash"),
                    "kept": False, "sourceTaskAvailable": True, "sourceFileAvailable": True,
                    "canKeep": (item.get("capabilities") or {}).get("canKeep") is not False,
                }
    for saved in retained:
        if saved.get("previewOnly"):
            continue
        key = str(saved.get("jobId") or ""), str(saved.get("filename") or "")
        if key in records:
            records[key].update(kept=True, keptAt=saved.get("keptAt"))
        else:
            records[key] = {
                **saved, "kept": True, "sourceTaskAvailable": key[0] in task_ids,
                "sourceFileAvailable": False, "canKeep": False,
            }
    return sorted(records.values(), key=lambda row: str(row.get("createdAt") or row.get("keptAt") or ""), reverse=True)
