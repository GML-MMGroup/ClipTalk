---
name: cliptalk-delivery-qc
version: 1.1.0
description: Checks an existing ClipTalk render for delivery defects such as decode failures, duration or stream mismatch, black or frozen frames, long silence, and incorrect dialogue loudness. Use for final checks, export readiness, or diagnosing a suspicious rendered file; it does not edit the timeline.
allowed-tools: inspect_workspace run_delivery_qc
workflow-profile: delivery-qc
---

# Delivery QC

Inspect the selected render without changing it, then run the deterministic delivery checks.

- Keep errors separate from warnings: an unreadable or structurally incomplete file blocks delivery; intentional fades, holds, or silence may be reviewed and waived.
- Report the affected file and measured evidence for every finding.
- Check the explicitly selected output when one is supplied; otherwise check the newest output produced by the active plan. Strict mode may block on warnings, while normal mode blocks only on errors.
- Do not claim that technical checks prove editorial quality, factual correctness, intelligibility, or lip-sync quality.
- Do not export, overwrite, delete, or silently repair a file. A repair requires a separate revision plan and a new output.
