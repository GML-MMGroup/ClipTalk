---
name: cliptalk-multi-topic-assembler
version: 1.0.0
description: Builds balanced clips from multiple required topics or categories, such as one segment per appliance, speaker, product, feature, or scene type, and reports missing categories instead of filling with unrelated footage.
allowed-tools: inspect_workspace search_content select_multi_topic_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview render_social_preview run_delivery_qc
workflow-profile: multi-topic
---

# Multi-topic Assembler

Create a reviewable timeline where each requested category is represented by reliable evidence.

- Parse category requirements from the user's words and keep them as required branches.
- Search once when the current task lacks compatible evidence, then select per-category candidates from reliable matches only.
- If a required category is missing, stop with a structured evidence gap; do not use unrelated scenes, filler, or "possible" matches to satisfy the category.
- When a total duration is explicit, distribute it across categories and expand around evidence anchors while respecting source boundaries.
- Preserve source order unless the user asks for a narrative order.
- Aspect ratio, subtitles, cover, and QC are delivery add-ons after the category selection is stable.
