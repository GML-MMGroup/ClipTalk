---
name: cliptalk-edit-diagnostics
version: 1.0.0
description: Diagnoses failed or confusing ClipTalk Agent flows, including missing content, stale task state, wrong aspect, reused covers, stuck planning, short clips, subtitle issues, and export readiness.
allowed-tools: inspect_workspace diagnose_edit_failure
workflow-profile: edit-diagnostics
---

# Edit Diagnostics

Explain why an Agent workflow failed or looks wrong.

- Inspect current task status, active plan, failed steps, output versions, source scope, evidence, timeline, cover, subtitles, and delivery previews.
- Prefer concrete causes over generic retry language.
- Distinguish missing source evidence, duration infeasibility, stale task state, wrong output selection, unavailable preview, and formal export not yet approved.
- Return actionable next steps without changing media state.
