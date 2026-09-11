---
name: cliptalk-broll-overlay-editor
version: 1.0.0
description: Adds relevant B-roll or cutaway overlays to an existing timeline while preserving the primary audio and making the result reviewable before final export.
allowed-tools: inspect_workspace search_content review_content_evidence propose_broll_overlay confirm_timeline_edit render_review_preview
workflow-profile: broll-overlay
---

# B-roll Overlay Editor

Use supporting visuals without breaking the main story or soundtrack.

- Start from an active edit session or accepted output.
- Search for visual support only for the requested overlay topic.
- Keep primary dialogue/audio as the backbone unless the user asks to replace it.
- Add muted cutaways at source-backed moments and keep their IDs visible for later toggling.
- Render a review preview; do not export without a delivery step.
