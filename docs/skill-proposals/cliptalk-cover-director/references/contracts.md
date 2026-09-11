# Cover Director Contracts

## ClipTalk activation metadata

When the runtime tools and managed plan compiler are implemented, promote this proposal with:

```yaml
version: 0.1.0
workflow-profile: cover
```

These are ClipTalk-specific frontmatter extensions and intentionally remain outside the proposal `SKILL.md` until activation.

## Preconditions

- A workspace contains a decodable source video.
- Candidate generation may use an accepted edit, highlight evidence, event graph, person evidence, or source-wide adaptive sampling.
- Source-wide sampling is a fallback, not a reason to rerun compatible multimodal analysis.

## Tool contracts

### `propose_cover_candidates`

Input:

```json
{
  "sourceScope": "accepted_cut|source_video",
  "aspectRatios": ["16:9"],
  "candidateBudget": 16,
  "titleText": "optional",
  "focus": ["人物反应", "关键动作"]
}
```

Output invariants:

- `candidateId`, `sourceTime`, `shotId`, `frameArtifact`, and `evidenceRefs` are present.
- `score.total` equals the sum of the six score components and is between 0 and 100.
- Candidates within the same shot and perceptually near-duplicate cluster are represented once unless the alternatives express meaningfully different emotion or action.
- Rejected candidates retain machine-readable reasons such as `blur`, `black_frame`, `subject_clipped`, `duplicate`, or `unsupported_identity`.

### `render_cover_variants`

Input:

```json
{
  "candidateIds": ["cover_candidate_1"],
  "directions": ["source_clean", "source_title", "generative"],
  "aspectRatios": ["16:9"],
  "titleText": "optional",
  "brandPresetId": "optional"
}
```

Every output is a new preview artifact with `variantId`, dimensions, direction, source references, title-safe-zone result, rendering parameters, and provenance. `generative` is invalid without an explicit request recorded in the active plan.

### `review_cover_variants`

Returns an approval action containing preview URLs, score explanations, risk warnings, and editable title or focal-region controls. Autonomous review is not allowed for the first approved cover direction.

### `confirm_cover`

Input names one `variantId` and one aspect ratio. The tool atomically marks a version current, retains the previous version, and records approver, timestamp, content hash, and provenance. It never publishes externally.

## Artifact schema

```json
{
  "schemaVersion": 1,
  "variantId": "cover_variant_01",
  "status": "preview|approved|superseded",
  "direction": "source_clean|source_title|generative",
  "aspectRatio": "16:9",
  "width": 1280,
  "height": 720,
  "source": {
    "jobId": "job_1",
    "outputVersionId": "optional",
    "sourceTime": 18.24,
    "evidenceRefs": ["event_4", "person_2"]
  },
  "score": {
    "requestAlignment": 23,
    "subjectReadability": 18,
    "emotionOrAction": 17,
    "visualClarity": 14,
    "titleSafeSpace": 9,
    "distinctiveness": 8,
    "total": 89
  },
  "provenance": {
    "kind": "source_frame|composite|generated",
    "model": "optional",
    "promptHash": "optional",
    "createdAt": "ISO-8601"
  }
}
```

## Acceptance gates

- At least three directions are shown when three valid directions exist; otherwise explain why fewer were safe.
- The chosen cover remains recognizable at 320 px width.
- Text, if present, passes contrast and overflow checks and stays inside the ratio-specific safe zone.
- A source-derived cover resolves back to an exact source timestamp and evidence set.
- A generated cover is visibly labelled as generated in review metadata and cannot be approved if it introduces unsupported claims or identities.
