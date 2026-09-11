---
name: cliptalk-shortform-hook-director
version: 1.2.0
description: Finds and assembles a reviewable short-form cut with a strong opening hook. Use for Shorts, Reels, social clips, talking-head cutdowns, or requests for a punchier opening.
allowed-tools: inspect_workspace analyze_highlights search_content review_content_evidence propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: shortform
---

# Short-form Hook Director

Create one concise, reviewable short-form cut rather than pretending to deliver a published social asset.

- Inspect reusable transcripts, high-signal candidates, content matches, edit sessions, and timelines before scheduling analysis.
- If the goal names a topic, quote, demonstration, or claim, use semantic search to find the evidence. Otherwise, use high-signal highlight evidence. Never schedule both analyses unless the workspace proves the first evidence is insufficient.
- Default to a 30-second cut when the user gives no duration; honor an explicit 15–60 second target.
- Enter a specific payoff, question, surprising claim, action, or result within the first 1–3 seconds. Remove intros, empty setup, pauses, and repeated wording while preserving complete meaning and actions.
- When semantic search supplies a composed cut, autonomous-review mode may choose valid candidate evidence; stepwise-review mode requires user review.
- Autonomous-review mode may validate and apply its short-form timeline and must finish with a review preview. Stepwise-review mode requires the user to apply the draft and prepares a subtitle draft or preview only when requested.
- Do not claim 9:16 reframing, a cover image, brand packaging, or formal export unless a compatible delivery Skill is explicitly composed into the plan.
