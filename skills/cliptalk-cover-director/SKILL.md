---
name: cliptalk-cover-director
version: 1.0.0
description: Produces evidence-backed cover candidates and three reviewable local cover variants for a ClipTalk video. Use when the user asks for a cover, poster frame, or thumbnail; do not use for timeline editing or social-video reframing.
allowed-tools: inspect_workspace propose_cover_candidates render_cover_variants review_cover_variants confirm_cover
workflow-profile: cover
---

# Cover Director

Create a recognizable, faithful, small-screen-legible cover and require an exact user selection before changing the current cover.

- Prefer an accepted cut as the source. Fall back to the source video only when no accepted output is available.
- Propose diverse frames across evidence-backed moments. Preserve source time, evidence references, component scores, and rejection reasons; suppress black and perceptually duplicate frames.
- Rank with the declared 100-point policy: request alignment 25, subject readability 20, emotion or action 20, visual clarity 15, title-safe space 10, and distinctiveness 10.
- Render three local, source-derived directions: clean, editorial, and cinematic. Add title text only when the request explicitly supplies it; do not invent a quotation or claim.
- Keep every output as a review artifact. `review_cover_variants` must stop for the user to choose one exact variant, even when the surrounding Agent uses autonomous review.
- `confirm_cover` may version and activate only that reviewed variant and matching content hash. Preserve previous versions, never modify the video output, and never publish externally.
- Do not claim generated imagery, identity retouching, platform certification, or formal campaign export. Those capabilities are outside this version.
