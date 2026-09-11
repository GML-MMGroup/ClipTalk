---
name: cliptalk-platform-delivery-exporter
version: 1.0.0
description: Exports a confirmed ClipTalk output for a named platform or delivery spec, preserving review/export approval boundaries and running final QC.
allowed-tools: inspect_workspace export_delivery_master run_delivery_qc
workflow-profile: platform-delivery
---

# Platform Delivery Exporter

Create a final task-local delivery master only after explicit approval.

- Use the current confirmed output or selected preview as the source.
- Honor platform, aspect, resolution, audio, cover, subtitle, filename, and package requirements.
- Do not treat a review preview as final approval.
- Produce a new output or package; never overwrite previous versions.
- Run delivery QC and report whether the file is ready for download.
