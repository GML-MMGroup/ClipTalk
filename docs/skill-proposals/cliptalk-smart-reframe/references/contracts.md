# Smart Reframe Contracts

## ClipTalk activation metadata

When the runtime tools and managed plan compiler are implemented, promote this proposal with:

```yaml
version: 0.1.0
workflow-profile: smart-reframe
```

These are ClipTalk-specific frontmatter extensions and intentionally remain outside the proposal `SKILL.md` until activation.

## Tool contracts

### `build_subject_track`

Input:

```json
{
  "sourceOutputId": "output_1",
  "targetMode": "person|object|active_speaker|editorial_subject",
  "targetIds": ["person_2"],
  "analysisPolicy": "reuse_then_fill_gaps"
}
```

Output is sampled on source-output time and maps every sample back to source time. Each observation includes normalized bounding box, confidence, evidence type, identity confidence, shot ID, visibility state, and required-group membership. Missing observations are explicit; they are not interpolated across shot boundaries.

### `propose_crop_track`

Input:

```json
{
  "subjectTrackId": "subject_track_1",
  "aspect": "9:16",
  "fitPolicy": "adaptive_crop_with_blur_fallback",
  "subtitleSafeArea": true,
  "motionPreset": "stable"
}
```

Output is a piecewise track whose segments are one of `crop`, `group_crop`, `blur_fallback`, or `manual`. Every segment includes start, end, crop keyframes, confidence, reason, evidence references, and constraint results.

Solver rules:

- Convert detections to a desired viewport that includes subject padding and visible motion direction.
- Solve within each shot using confidence-weighted smoothing and robust outlier rejection.
- Penalize center velocity, acceleration, and zoom-rate changes rather than applying an unconstrained moving average.
- Do not follow detection jitter smaller than a configurable dead zone.
- Do not interpolate through `missing`, `identity_conflict`, or a scene cut.
- Prefer group crop when all required subjects fit above the minimum readable scale; otherwise use fallback rather than silently excluding a required subject.

### `render_reframe_preview`

Renders a new low-bitrate, watermarked preview. The renderer consumes crop keyframes deterministically, preserves audio timing, and records the exact source output hash and crop-track hash. It must not modify source timing or choose new content.

### `review_reframe_quality`

Reports:

- subject coverage ratio and minimum on-screen size;
- crop-edge intersections for faces, hands, products, and configured protected regions;
- maximum center velocity, acceleration, and zoom rate per shot;
- fallback duration and reason distribution;
- subtitle overlap and safe-zone violations;
- identity-conflict and low-confidence spans;
- decode, duration, stream, black-frame, freeze, silence, and loudness checks from delivery QC.

Errors block confirmation. Warnings remain visible and can be waived with a recorded reason.

### `confirm_reframe`

Accepts a crop-track ID and rendered preview hash. If either changed after review, confirmation fails closed and a new review is required. Confirmation versions the track and preview; it does not publish or create a final master.

## Crop-track schema

```json
{
  "schemaVersion": 1,
  "trackId": "crop_track_01",
  "sourceOutputId": "output_1",
  "sourceOutputHash": "sha256:...",
  "aspect": "9:16",
  "segments": [
    {
      "shotId": "shot_5",
      "start": 12.0,
      "end": 16.8,
      "mode": "crop",
      "targetIds": ["person_2"],
      "confidence": 0.93,
      "keyframes": [
        {"time": 12.0, "centerX": 0.42, "centerY": 0.48, "scale": 1.0},
        {"time": 16.8, "centerX": 0.51, "centerY": 0.47, "scale": 1.04}
      ],
      "evidenceRefs": ["person_track_2"],
      "constraintStatus": "passed"
    }
  ]
}
```

## Initial acceptance thresholds

Thresholds must be calibrated on project fixtures before becoming release gates. Start with these review thresholds:

- At least 95% subject coverage on high-confidence single-subject spans.
- No protected subject intersects the crop edge for more than 250 ms on a high-confidence span.
- No smoothing or identity interpolation crosses a shot boundary.
- Every low-confidence span has an explicit fallback or manual decision.
- Rendered duration differs from the source output by no more than one output frame.
- Re-rendering the same source and crop-track hashes yields the same crop commands and artifact metadata.

## Required fixture classes

- one stable talking head;
- walking subject with pans;
- two-person interview with reliable and unreliable speaker switches;
- group shot where all required people must remain visible;
- temporary occlusion and re-entry;
- fast cut montage;
- subject absent from a shot;
- burned-in and editable subtitles near the lower safe zone;
- product or action target with no visible face.
