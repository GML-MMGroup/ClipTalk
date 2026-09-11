---
name: cliptalk-cover-intro-composer
version: 1.0.0
description: Creates task-local cover candidates and composes the confirmed cover into the beginning of the current output as a short intro, keeping cover selection separate from video editing.
allowed-tools: inspect_workspace propose_cover_candidates render_cover_variants review_cover_variants confirm_cover compose_cover_intro run_delivery_qc
workflow-profile: cover-intro
---

# Cover Intro Composer

Make a cover and an in-video intro from the current task only.

- Prefer the current accepted cut as the cover source; use source video only when no accepted cut exists and the user is explicitly still preparing a first result.
- Generate task-local cover candidates with source time, evidence, score, and content hash.
- Confirm exactly one cover variant before composing it into the video.
- Compose the confirmed cover as a short opening intro only on the current task's current output; never attach a cover from another task or an older output.
- Keep formal export separate from review previews unless the user explicitly confirms export.
