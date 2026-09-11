---
name: cliptalk-smart-reframe
description: Creates a subject-aware, time-varying crop track and a review-only social-format preview from an accepted ClipTalk cut. Use for automatic vertical, square, or portrait reframing; do not use for a fixed manual crop or before content editing is accepted.
allowed-tools: inspect_workspace build_subject_track propose_crop_track render_reframe_preview review_reframe_quality confirm_reframe run_delivery_qc
---

# Smart Reframe

Turn an accepted cut into a stable, subject-aware composition without changing its editorial content.

- Require an accepted output or review output as the source. Preserve it unchanged and create a new preview version.
- Resolve the target subject from an explicit person, object, current speaker, or editorial subject rule. Reuse compatible person tracks, active-speaker evidence, shot boundaries, object evidence, subtitles, and manual selections before scheduling new analysis.
- Build a confidence-bearing subject track, then solve a piecewise crop track per shot. A crop track contains time-varying center, scale, confidence, evidence references, and fallback state; it is not one static `focusX/focusY` pair.
- Keep the subject inside the action-safe region while protecting subtitle and title-safe regions. Prefer a slightly wider stable crop over aggressive face chasing.
- Bound crop-center velocity, acceleration, and zoom change inside a shot. Reset or deliberately ease composition at a detected cut; never smooth motion across unrelated shots.
- Use group framing when several required subjects are visible. Use current-speaker framing only when speaker attribution is reliable and switching will not create distracting ping-pong motion.
- Fall back shot by shot to the complete frame with a blurred background when the subject is missing, confidence is low, the required group cannot fit, the crop would remove important action, or subtitle-safe placement cannot be maintained.
- `render_reframe_preview` produces a review-only artifact. `review_reframe_quality` must report crop losses, fallback spans, high-motion spans, subtitle conflicts, identity uncertainty, and manual keyframes.
- Require `confirm_reframe` before treating a crop track as accepted. Never overwrite the source output, claim formal platform certification, publish, or create a final master as part of this Skill.

Read [references/contracts.md](references/contracts.md) when implementing the crop solver, fallbacks, artifact schema, and quality gates.
