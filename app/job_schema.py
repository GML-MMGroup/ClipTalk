from __future__ import annotations

from typing import Any


CURRENT_JOB_SCHEMA_VERSION = 5

from .algorithm_contract import ALGORITHM_V1

WORKFLOW_KINDS = frozenset({"highlight", "content_search", "person_edit", "speaker_edit"})


def normalize_job_schema(job: dict[str, Any]) -> bool:
    """Apply durable, presentation-free migrations exactly once on load."""
    changed = False
    try:
        version = max(0, int(job.get("schemaVersion") or 0))
    except (TypeError, ValueError):
        version = 0
    if version < 1:
        task_mode = str(job.get("taskMode") or "highlight")
        job.setdefault("resolvedTaskKind", task_mode)
        job.setdefault("routingConfidence", 1.0)
        job.setdefault("routingNeedsConfirmation", False)
        job.setdefault("routingReason", "由旧任务模式迁移")
        job.setdefault("routingSource", "legacy_migration")
        changed = True
    if version < 2:
        request = job.setdefault("request", {})
        if not isinstance(request, dict):
            request = {}
            job["request"] = request
        # Existing tasks retain an explicit version count. Historical tasks
        # without one use the original three-cut highlight default.
        request.setdefault("autoVariantCount", 3)
        changed = True
    request = job.get("request")
    if not isinstance(request, dict):
        request = {}
        job["request"] = request
        changed = True
    if version < 3:
        requested = str(request.get("workflowKind") or "").strip().lower()
        explicit = str(job.get("workflowKind") or "").strip().lower()
        entry = str(request.get("entryWorkflow") or "").strip().lower()
        task_mode = str(job.get("taskMode") or "highlight").strip().lower()
        workflow = (
            requested if requested in WORKFLOW_KINDS else
            explicit if explicit in WORKFLOW_KINDS else
            "speaker_edit" if entry == "voice_discovery" else
            "person_edit" if entry == "person_discovery" else
            "content_search" if task_mode == "content_extract" else
            "highlight"
        )
        expected_mode = "highlight" if workflow == "highlight" else "content_extract"
        expected_entry = (
            "voice_discovery" if workflow == "speaker_edit" else
            "person_discovery" if workflow == "person_edit" else ""
        )
        if request.get("workflowKind") != workflow:
            request["workflowKind"] = workflow
            changed = True
        if job.get("workflowKind") != workflow:
            job["workflowKind"] = workflow
            changed = True
        if job.get("taskMode") != expected_mode:
            job["taskMode"] = expected_mode
            changed = True
        if request.get("entryWorkflow") != expected_entry:
            request["entryWorkflow"] = expected_entry
            changed = True
    if version < 4:
        legacy_composition_text = "；每条由同一事件的多个镜头组成"
        composition_text = (
            "；系统将相关镜头按事件归组，并根据内容完整性自动编排；"
            "每条成片可包含一个或多个事件"
        )
        for message in job.get("messages") or []:
            if not isinstance(message, dict):
                continue
            text = str(message.get("text") or "")
            is_generated_highlight_request = (
                message.get("role") == "user"
                and message.get("kind") == "request"
                and text.startswith("分析 ")
                and legacy_composition_text in text
                and (
                    "，允许复用相同要求的分析缓存" in text
                    or "，重新调用模型分析" in text
                )
            )
            if is_generated_highlight_request:
                message["text"] = text.replace(
                    legacy_composition_text, composition_text, 1,
                )
                changed = True
    if version < 5:
        # The release boundary is deliberately one-way: persisted jobs never
        # inherit a newer decision pipeline just because the server changed.
        job.setdefault("algorithmVersion", ALGORITHM_V1)
        changed = True
    if version != CURRENT_JOB_SCHEMA_VERSION:
        job["schemaVersion"] = CURRENT_JOB_SCHEMA_VERSION
        changed = True
    return changed
