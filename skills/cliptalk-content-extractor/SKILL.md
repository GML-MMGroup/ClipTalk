---
name: cliptalk-content-extractor
version: 1.2.0
description: Locates and assembles source passages matching a semantic request. Use for extracting explanations, topics, quotes, demonstrations, or other specifically described content.
allowed-tools: inspect_workspace search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: content
---

# Content Extractor

Turn the requested subject and boundaries into a traceable content-selection plan.

- Inspect reusable transcripts and indexes before scheduling a search.
- Search for meaning and supporting visual evidence, not keywords alone.
- Preserve enough context for statements and demonstrations to remain understandable.
- Make ordering and overlap handling explicit before proposing the timeline.
- Keep the semantic target separate from duration, variant, subtitle, aspect-ratio, and delivery instructions. Those explicit deliverables are composed after content selection rather than mixed into the search query.
- A find-only request ends with evidence rather than creating an unrequested cut. For a combined cut, autonomous-review mode may select valid candidates and apply its timeline proposal without interrupting the user; stepwise-review mode requires candidate and timeline confirmation.
- Autonomous-review mode must finish with a low-resolution review preview. Stepwise-review mode prepares subtitles or a review preview only when requested. Never treat a preview as a formal export.
