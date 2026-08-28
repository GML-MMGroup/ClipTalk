from __future__ import annotations

from typing import Any, Literal


AnalysisManifestOutcome = Literal["review", "empty", "invalid"]


def analysis_manifest_outcome(manifest: dict[str, Any]) -> AnalysisManifestOutcome:
    """Classify the current discovery manifest before job state is mutated."""
    groups = manifest.get("eventGroups")
    candidates = manifest.get("candidates")
    if isinstance(groups, list) and groups:
        return "review"
    if isinstance(candidates, list) and candidates:
        return "invalid"
    return "empty"
