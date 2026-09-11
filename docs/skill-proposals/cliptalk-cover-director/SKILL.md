---
name: cliptalk-cover-director
description: Produces evidence-backed cover candidates and reviewable cover variants for a ClipTalk video. Use when the user asks for a cover, poster frame, thumbnail, or multiple cover directions; do not use for timeline editing or social-video reframing.
allowed-tools: inspect_workspace propose_cover_candidates render_cover_variants review_cover_variants confirm_cover
---

# Cover Director

Create a cover that is recognizable, faithful to the source, legible at small size, and explicitly approved.

- Inspect the workspace first. Prefer the accepted cut and its evidence; use source-video evidence only when no accepted cut exists or the user asks for a source-wide cover search.
- Propose 10–20 source-frame candidates across distinct moments. Do not let many near-duplicate frames from one shot displace stronger alternatives.
- Rank candidates with this 100-point policy: request alignment 25, subject readability 20, emotion or action 20, visual clarity 15, title-safe space 10, and visual distinctiveness 10. Preserve component scores and evidence timestamps.
- Render three materially different review variants by default. Use only the requested aspect ratios; otherwise start with 16:9 and offer 9:16 or 4:5 adaptations after a direction is chosen.
- Default to source-frame or source-frame-plus-title treatments. Use a generated image only when the user explicitly requests or selects a generative direction.
- For generated variants, preserve recognizable identities and event truth. Never invent an achievement, quotation, product result, participant, or event that is not supported by project evidence. Record source references, model, prompt hash, and generation time.
- Keep important faces, hands, products, and title text outside platform crop-risk zones. Reject tiny text, unreadable contrast, clipped subjects, duplicate directions, and frames with severe blur or closed-eye artifacts.
- `review_cover_variants` is an approval checkpoint. Do not make a variant current, overwrite an existing cover, publish it, or export a final asset before `confirm_cover` identifies the exact variant and ratio.
- Preserve the previous cover as a version. A revision creates another variant rather than destructively editing the approved file.

Read [references/contracts.md](references/contracts.md) when implementing or validating the tools, scores, provenance, and review state.
