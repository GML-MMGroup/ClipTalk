---
name: cliptalk-speaker-editor
version: 1.2.0
description: Creates cuts based on who is speaking. Use when the request targets a speaker, their answers, narration, dialogue turns, or removal of one voice.
allowed-tools: inspect_workspace discover_speakers select_speakers search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: speaker
---

# Speaker Editor

Separate anonymous voices before selecting spoken material.

- Reuse current-material discovery and a saved speaker selection when their source and analysis revisions remain compatible; otherwise schedule discovery or one structured confirmation.
- Preserve explicit include or exclude intent, and treat gender or role wording as a selection description rather than an inferred real-world identity.
- Preserve complete dialogue turns and question-answer context where requested.
- Use content search only after the relevant speaker selection is known.
- For a combined cut, autonomous-review mode may select valid speech evidence and apply its timeline after speaker identity is reliably bound; stepwise-review mode requires evidence and timeline confirmation. Autonomous-review mode finishes with a review preview; never treat it as a final export.
