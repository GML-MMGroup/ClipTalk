---
name: cliptalk-social-reframe-exporter
version: 1.1.0
description: Creates a review-only 9:16, 4:5, 1:1, or 16:9 version from an existing accepted ClipTalk cut, then checks the rendered preview. Use only when a cut already exists and the user asks to adapt it for Shorts, Reels, Douyin, Xiaohongshu, WeChat Channels, or square feeds; do not use when the user still needs content found and assembled from a source video.
allowed-tools: inspect_workspace render_social_preview run_delivery_qc
workflow-profile: social-reframe
---

# Social Reframe Exporter

Create a new social-format preview from an existing accepted cut and preserve the source output unchanged.

- Default to 9:16 crop when the request names a vertical short-video platform without an aspect ratio.
- Honor explicit 9:16, 4:5, 1:1, or 16:9 ratios. Use padding when the user asks to preserve the complete frame or avoid cropping, and preserve an explicit left, center, right, top, or bottom focal direction.
- If the same request first edits source material, consume the review output produced after timeline confirmation; never skip directly to an unrelated existing render.
- Treat the generated file as an approval preview. Run delivery QC after rendering and keep warnings visible for human review.
- The current crop uses an adjustable frame focus; do not claim automatic face tracking, shot-by-shot reframing, safe-zone certification, cover creation, publishing, or formal export.
- A different focal point, crop mode, subtitle layout, or final master requires a new preview or an explicit revision/export action.
