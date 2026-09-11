---
name: cliptalk-subtitle-editor
version: 1.1.0
description: Revises subtitles on an existing ClipTalk timeline with readable placement, timing, line wrapping, and style-safe review output. Use when the user asks to add, fix, move, restyle, or verify subtitles without redoing source analysis.
allowed-tools: inspect_workspace propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: revision
---

# Subtitle Editor

Make subtitle changes as a reversible timeline revision.

- Inspect the active task, accepted timeline, subtitle draft, and current output before editing. Never reuse subtitle drafts from another task or source revision.
- Preserve the spoken meaning and timing. Split long cues at natural pauses, wrap lines for the target frame, and keep text clear of faces, product details, and the safe margins.
- Treat placement, size, contrast, bilingual ordering, and top/bottom position as explicit user requirements; do not silently move subtitles to satisfy a crop.
- In autonomous-review mode, generate the timeline-bound subtitle draft, apply only evidence-backed low-risk corrections, and continue directly to a watermarked review preview. Do not pause merely to make the user choose whether subtitles should continue.
- In stepwise-review mode, expose the subtitle review drawer as an optional checkpoint without routing through the secondary fine-cut editor.
- Keep the subtitle draft editable from the finished sample and final timeline. Do not perform formal export.
