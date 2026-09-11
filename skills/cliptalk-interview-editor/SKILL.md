---
name: cliptalk-interview-editor
version: 1.2.0
description: Produces a coherent interview edit by combining speaker discovery, topic selection, dialogue context, cleanup, subtitles, and preview. Use for interviews, podcasts, testimonials, or question-and-answer recordings.
allowed-tools: inspect_workspace discover_speakers select_speakers search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: interview
---

# Interview Editor

Plan a coherent interview story rather than a bag of isolated quotes.

- Inspect existing transcripts, speaker clusters, content matches, edit sessions, and timelines. Reuse them before starting another analysis.
- Discover or confirm speakers only when the goal explicitly scopes a voice or role and the workspace lacks reliable evidence.
- Use one evidence-extraction search to locate core viewpoints, story examples, necessary questions, natural topic transitions, repetition, and removable dead space. Do not schedule separate searches merely to split those editorial criteria.
- Use a duration only when the user explicitly requests one. Preserve only the questions and transitions needed to understand each answer; do not invent a default interview length or change the speaker's meaning to hit a target.
- For a combined cut, autonomous-review mode may select coherent evidence and apply its themed timeline without interrupting the user; stepwise-review mode requires evidence and timeline confirmation.
- Autonomous-review mode finishes with a low-bitrate review sample. If subtitles are requested, pause only when text, speaker attribution, or source-subtitle state genuinely needs confirmation. A review sample is not a formal export.
- Treat identity binding and final export as separate approvals.
