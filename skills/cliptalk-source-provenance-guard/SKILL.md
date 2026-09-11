---
name: cliptalk-source-provenance-guard
version: 1.0.0
description: Verifies that a ClipTalk Agent plan uses the current task, source revision, selected scope, and task-local artifacts before reusing analysis, covers, subtitles, timelines, or outputs.
allowed-tools: inspect_workspace validate_task_provenance
workflow-profile: source-provenance
---

# Source Provenance Guard

Prevent cross-task state leakage before an edit or delivery step.

- Inspect the active workspace and validate the bound job, source asset, source scope, active plan, edit session, cover, subtitle draft, and output references.
- Treat a same-source upload as a new task unless the user explicitly asks to continue the previous task.
- Never reuse a previous task's time range, cover, subtitle draft, candidate selection, timeline, render, or progress state as the current task's result.
- Return a clear prerequisite or mismatch diagnosis instead of repairing by silently switching jobs.
- This Skill does not render or export media.
