---
name: cliptalk-dynamic-reframe-director
version: 1.0.0
description: Converts an existing cut or freshly generated review output to vertical, square, or horizontal formats using shot-aware safe-area checks and complete-frame blurred padding by default.
allowed-tools: inspect_workspace analyze_reframe_safe_areas render_social_preview run_delivery_qc
workflow-profile: dynamic-reframe
---

# Dynamic Reframe Director

Adapt the current output to the requested aspect ratio without losing source information.

- Verify a current accepted output or review proxy exists before rendering a social-format preview.
- Analyze source and target dimensions, face/text/product protection, and requested focus before choosing the fit.
- Default to complete-frame foreground plus same-frame blurred background when ratios differ.
- Crop only when the user explicitly asks for crop-to-fill or a focal crop.
- Report the final aspect, fit policy, source filename, and QC result.
