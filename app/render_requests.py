"""One converged argument object for the delivery render entry point.

``run_confirmed_render`` used to take 21 positional parameters, which made every
call site a positional puzzle.  Callers now build a :class:`RenderRequest`; the
legacy positional form is still accepted while older call sites migrate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RenderRequest:
    job_id: str
    selection_keys: list[Any] = field(default_factory=list)
    output_mode: str = "single_reel"
    variant_mode: str = "complete"
    variant_label: str = ""
    finalize_status: bool = True
    planned_sequence: list[dict[str, Any]] | None = None
    planned_title: str = ""
    planned_chapters: list[dict[str, Any]] | None = None
    subtitle_mode: str = "none"
    order_mode: str = "source"
    subtitle_style: str = "clean"
    auto_meta: dict[str, Any] | None = None
    background_auto: bool = False
    planned_cutaways: list[dict[str, Any]] | None = None
    technique_policy: dict[str, Any] | None = None
    finalize_source_version_id: str | None = None
    subtitle_draft_id: str | None = None
    text_layers: list[dict[str, Any]] | None = None
    output_reframe: dict[str, Any] | None = None
    render_spec: dict[str, Any] | None = None

    def render_arguments(self) -> list[Any]:
        """The legacy positional form, kept for stored/queued render arguments."""
        return [
            self.job_id, self.selection_keys, self.output_mode, self.variant_mode,
            self.variant_label, self.finalize_status, self.planned_sequence,
            self.planned_title, self.planned_chapters, self.subtitle_mode,
            self.order_mode, self.subtitle_style, self.auto_meta, self.background_auto,
            self.planned_cutaways, self.technique_policy, self.finalize_source_version_id,
            self.subtitle_draft_id, self.text_layers, self.output_reframe, self.render_spec,
        ]
