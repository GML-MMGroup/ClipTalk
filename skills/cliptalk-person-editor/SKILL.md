---
name: cliptalk-person-editor
version: 1.2.0
description: Creates cuts based on who appears on screen. Use when the user wants to keep, remove, follow, or compare visible people rather than select by spoken content alone.
allowed-tools: inspect_workspace discover_people select_people propose_timeline_edit confirm_timeline_edit prepare_subtitle_review render_review_preview
workflow-profile: person
---

# Person Editor

Discover visual identities before editing by person.

- Reuse a compatible person catalog and saved selection when their source and analysis revisions still match; otherwise schedule discovery or confirmation.
- Require structured user confirmation before binding a discovered face to a requested person.
- Keep identity uncertainty visible and never infer a real name from appearance.
- Preserve explicit include, exclude, compare, or per-person rules instead of converting every request into an include operation.
- Propose the timeline from confirmed rules. Autonomous-review mode may validate and apply that proposal and finish with a review sample; stepwise-review mode requires the user to apply the draft.
- Identity confirmation does not authorize a preview, render, or export that the user did not request.
