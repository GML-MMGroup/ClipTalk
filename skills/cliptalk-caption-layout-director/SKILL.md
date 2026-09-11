---
name: cliptalk-caption-layout-director
version: 1.1.0
description: Lays out subtitles for an existing ClipTalk timeline, including top/bottom placement, safe margins, readable wrapping, bilingual order, and review rendering.
allowed-tools: inspect_workspace layout_subtitles prepare_subtitle_review render_review_preview
workflow-profile: caption-layout
---

# Caption Layout Director

Turn subtitle placement requirements into a timeline-bound subtitle draft.

- Work only against the active task and active edit session.
- Preserve recognized speech timing and meaning; do not invent or paraphrase dialogue.
- Honor explicit placement such as top, bottom, center, bilingual, large text, or compact style.
- Keep subtitles clear of faces, product details, screen text, and frame margins where the available evidence supports it.
- In autonomous-review mode, automatically create and conservatively proofread the subtitle draft, apply the requested layout, and continue to the review sample. Defer uncertain corrections for later manual review instead of blocking the plan.
- In stepwise-review mode, pause at the dedicated subtitle review drawer only when the user selected stepwise execution; do not open the secondary fine-cut editor for subtitle text review.
- Preserve an editable subtitle track in the finished-sample view so the user can correct wording, timing, and layout later.
- Render only review previews unless a delivery Skill later handles final export.
