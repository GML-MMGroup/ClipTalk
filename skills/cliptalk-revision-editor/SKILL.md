---
name: cliptalk-revision-editor
version: 1.2.0
description: Revises an existing ClipTalk cut or review timeline. Use when the user asks to shorten, reorder, remove, restore, subtitle, or otherwise refine an existing result without redoing source analysis unnecessarily.
allowed-tools: inspect_workspace propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: revision
---

# Revision Editor

Prefer the smallest reversible timeline change that satisfies the request.

- Inspect the active output, edit session, evidence, and previous revisions first.
- Do not rerun source analysis unless the requested evidence is genuinely missing.
- When the revision introduces new content, person, or speaker evidence, compose the matching discovery Skill before returning to the existing edit session.
- Express edits against stable segments rather than raw file paths.
- Preserve a clear before/after explanation. Autonomous-review mode may validate and apply the reversible proposal before preparing the review sample; stepwise-review mode requires the user to apply it.
- Never overwrite an accepted version or formally export without a separate confirmation.
