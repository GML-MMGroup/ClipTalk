"""One converged form object for the create-job endpoint.

``create_job`` used to declare 45 separate ``Form(...)`` parameters, which made
the signature the only documentation of an intake contract that is really one
object.  The dataclass below keeps every field name identical, so the HTTP
contract does not change; only the Python signature converges.
"""
from __future__ import annotations

import dataclasses
import inspect
from typing import Any, Callable

from fastapi import Form


@dataclasses.dataclass
class CreateJobForm:
    upload_session_id: str = ""
    expected_size_bytes: str = ""
    task_mode: str = "auto"
    intent_mode: str = ""
    parameter_context: str = "legacy_explicit"
    storage_mode: str = "editable"
    instruction: str = ""
    count: str = "auto"
    target_seconds: str = "auto"
    total_target_seconds: str = ""
    theme: str = ""
    analysis_mode: str = "audiovisual"
    recognition_profile: str = "auto"
    force_reanalyze: str = "true"
    subtitle_mode: str = "none"
    subtitle_style: str = "clean"
    edit_mode: str = "ai_plan"
    structure: str = "auto"
    # The default variant count lives with the highlight settings; an empty
    # string means "not sent" and the endpoint applies its own default.
    auto_variant_count: str = ""
    technique_preset: str = "auto"
    allow_speed: str = "true"
    allow_transitions: str = "true"
    allow_audio_bridges: str = "true"
    allow_cutaways: str = "true"
    allow_silence_compression: str = "true"
    allow_cold_open: str = "false"
    source_scope_kind: str = "all"
    source_scope_start: str = ""
    source_scope_end: str = ""
    result_strategy: str = "smart"
    search_scope_kind: str = "all"
    search_scope_start: str = ""
    search_scope_end: str = ""
    search_result_limit: str = "12"
    search_boundary_mode: str = "complete"
    content_auto_generate: str = "false"
    content_exclusions: str = ""
    search_evidence_mode: str = ""
    search_allowed_capabilities: str = ""
    entry_workflow: str = ""
    workflow_kind: str = ""
    agent_draft: str = "false"
    draft_session_id: str = ""


def form_dependency(cls: type) -> Callable[..., Any]:
    """Expose a dataclass as a form body without renaming a single field."""
    parameters = [
        inspect.Parameter(
            field.name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=Form(field.default),
        )
        for field in dataclasses.fields(cls)
    ]

    async def dependency(**data: Any) -> Any:
        return cls(**data)

    dependency.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
    return dependency


create_job_form = form_dependency(CreateJobForm)
