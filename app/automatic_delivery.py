"""Policy for opt-in, request-scoped automatic delivery.

Keep the new mode separate from legacy review approval. In particular it never
authorizes plugins, deletion, publication, or relabelling a review proxy.
"""
from __future__ import annotations

import os
from typing import Any

AUTOMATIC_DELIVERY = "automatic_delivery"
AUTOMATIC_MODES = frozenset({AUTOMATIC_DELIVERY, "autonomous_review"})
DELIVERY_TOOL = "deliver_current_plan"
VIDEO_TOOLS = frozenset({
    "render_review_preview", "render_social_preview", "compose_cover_intro",
})


def enabled() -> bool:
    return os.environ.get("CLIPTALK_AUTOMATIC_DELIVERY", "1").lower() not in {"0", "false", "off"}


def subtitle_source_ready(draft: dict[str, Any]) -> bool:
    if draft.get("sourceSubtitleAcknowledged") is not False:
        return True
    check = draft.get("sourceSubtitleCheck") or {}
    return (draft.get("confirmationMode") == "automatic_delivery" and check.get("status") == "clear"
            and bool(check.get("outputFingerprints"))
            and check["outputFingerprints"] == draft.get("outputFingerprints"))


def blocking_quality_issues(result: Any) -> list[dict[str, Any]]:
    artifact = result.get("artifact", {}) if isinstance(result, dict) else {}
    if artifact.get("kind") != "delivery_qc_report":
        return []
    # Warnings and unknown semantic checks are not failures. Explicit errors
    # (including missing requested deliverables) must never be auto-accepted.
    return [issue for report in artifact.get("reports", [])
            for issue in report.get("issues", [])
            if isinstance(issue, dict) and issue.get("severity") == "error"]


def delivery_session_ids(plan: dict[str, Any]) -> list[str]:
    """Only sessions produced/verified by this plan, never an unrelated latest one."""
    ids: list[str] = []
    for step in plan.get("steps", []):
        if step.get("status") != "completed":
            continue
        artifact = (step.get("result") or {}).get("artifact") or {}
        candidates = [artifact, artifact.get("output") or {}, *(artifact.get("previews") or []), *(artifact.get("sessions") or [])]
        for item in candidates:
            session_id = str(item.get("sourceEditSessionId") or item.get("sessionId") or "")
            if session_id and session_id not in ids:
                ids.append(session_id)
    return ids


def may_auto_approve(plan: dict[str, Any]) -> bool:
    return (enabled() and plan.get("executionMode") == AUTOMATIC_DELIVERY
            and not (plan.get("brief") or {}).get("coverSourceStatus") == "requires_external_asset"
            and all(not step.get("pluginId") and step.get("sideEffect") != "delete"
                    and (step.get("sideEffect") != "export" or step.get("tool") == DELIVERY_TOOL)
                    for step in plan.get("steps", [])))
