---
name: cliptalk-local-motion-renderer
version: 1.0.0
description: Generate local motion-graphics clips such as title cards, animated intros, visual explainers, and cover motion using the built-in HTML/Playwright/FFmpeg pipeline without external APIs.
allowed-tools: inspect_workspace render_motion_graphics compose_motion_intro run_delivery_qc
workflow-profile: local-motion
---

# ClipTalk Local Motion Renderer

Use this skill when the user asks for Remotion-like, HyperFrames-like, HTML video, animated text, title-card, intro, dynamic cover, or visual explainer assets that can be rendered locally.

Hard boundaries:

- Do not call cloud rendering, TTS, music, image-generation, or video-generation APIs.
- Produce a separate local motion clip unless the user also asks to merge it into an existing cut; when they do, use `compose_motion_intro` to create a new output version.
- Keep the output as an auditable preview artifact; formal delivery still needs the delivery-export skill.
- Prefer the project’s ClipTalk visual identity, dark UI palette, readable Chinese typography, and safe-area margins.

Execution:

1. Inspect the workspace only to confirm the current task and any requested aspect ratio.
2. Render the motion clip with `render_motion_graphics`.
3. If the user asked for a motion intro on the current cut and the workspace has an output, compose it with `compose_motion_intro`.
4. Run `run_delivery_qc` on the generated local clip or composed output.
