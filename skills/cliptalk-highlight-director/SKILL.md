---
name: cliptalk-highlight-director
version: 1.2.0
description: Finds and assembles the strongest moments from a source video. Use when the requested result is a highlight reel, recap, trailer, or best-moments cut rather than a literal content extraction.
allowed-tools: inspect_workspace analyze_highlights propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: highlight
---

# Highlight Director

Build an evidence-backed highlight cut that preserves complete actions and intelligible speech.

- Inspect existing evidence before scheduling analysis; reuse it only when its source revision, scope, and target remain compatible.
- Analyze highlights when the workspace has no relevant candidates or the user explicitly requests a fresh analysis.
- Plan around the requested duration, focus, pacing, source order, and subtitle preference.
- Prefer a smaller coherent sequence over unrelated high-scoring fragments.
- In autonomous-review mode, validate and apply the timeline proposal without interrupting the user, then finish with a low-bitrate review preview. In stepwise-review mode, require the user to review and apply the proposal. Never treat a preview as permission for final export.
