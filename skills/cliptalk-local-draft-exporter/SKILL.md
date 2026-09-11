---
name: cliptalk-local-draft-exporter
version: 1.0.0
description: Export the current ClipTalk edit state as a local JSON draft package for external editor bridges such as Jianying or CapCut, without writing into third-party application directories.
allowed-tools: inspect_workspace export_editing_draft
workflow-profile: local-draft
---

# ClipTalk Local Draft Exporter

Use this skill when the user asks to export a draft, editing project, Jianying/CapCut bridge package, or external-editor handoff from the current task.

Hard boundaries:

- Do not write directly into Jianying, CapCut, or another app’s project directory.
- Do not claim native Jianying compatibility unless a dedicated format mapper exists.
- Export only the current task’s source metadata, edit sessions, output versions, and cover references.
- This is an export action. Keep it explicit and auditable.

Execution:

1. Inspect the workspace and confirm there is an existing timeline or output.
2. Export `cliptalk-json` via `export_editing_draft`.
3. Return the downloadable draft package path and format.
