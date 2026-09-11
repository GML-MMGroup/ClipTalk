---
name: cliptalk-audio-polish-mixer
version: 1.0.0
description: Produces a task-local audio-polished preview or output from an existing cut, applying loudness normalization, optional noise reduction, fades, muting, and voice-first mix policy.
allowed-tools: inspect_workspace polish_audio_mix run_delivery_qc
workflow-profile: audio-polish
---

# Audio Polish Mixer

Improve audio clarity on the current task's existing output.

- Use the current task's selected output as the only source.
- Apply voice-first normalization and conservative noise reduction when requested.
- Preserve duration and picture content unless the user explicitly asks for timing changes.
- Keep the result as a new task-local version or preview; never overwrite the source output.
- Run QC after the audio pass and surface clipping, silence, or missing-audio warnings.
