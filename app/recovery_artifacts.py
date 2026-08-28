from __future__ import annotations

from pathlib import Path
from typing import Any


def recovery_artifact_health(job: dict[str, Any]) -> dict[str, Any]:
    source = Path(str(job.get("sourcePath") or ""))
    output_directory = Path(str(job.get("outputDirectory") or ""))
    expected_outputs = [
        str(item.get("filename") or "")
        for version in job.get("outputVersions") or []
        for item in version.get("outputs") or []
        if item.get("filename")
    ]
    missing_outputs = [name for name in expected_outputs if not (output_directory / name).is_file()]
    return {
        "sourcePresent": source.is_file(),
        "expectedOutputCount": len(expected_outputs),
        "missingOutputCount": len(missing_outputs),
        "healthy": source.is_file() and not missing_outputs,
    }
