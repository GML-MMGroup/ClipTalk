---
name: cliptalk-smart-reframe
version: 1.0.0
description: Adapts an existing accepted ClipTalk cut to 9:16, 4:5, 1:1, or 16:9 while preserving the complete source frame with blurred background padding unless the user explicitly requests cropping.
allowed-tools: inspect_workspace render_social_preview run_delivery_qc
workflow-profile: social-reframe
---

# Smart Reframe

Create a review-only format version from the current accepted cut.

- Verify that the source is the active accepted output for the current task; never reuse a render, cover, or crop track from another task.
- Honor the explicit aspect ratio. When the source and target ratios differ, preserve the complete frame at the largest readable size and fill the remaining canvas with a blurred duplicate of the same frame.
- Keep faces, product details, subtitles, and on-screen text inside the safe area. Crop only when the user explicitly requests crop-to-fill or supplies a focal direction.
- Keep the original accepted cut unchanged. Render a separate preview, run delivery QC on that preview, and report the fit policy and measured output ratio.
