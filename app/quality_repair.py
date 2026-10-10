"""Route explicit quality retries to the failed stage, not always the editor."""
from __future__ import annotations


def repair_step_ids(steps: list[dict], root_id: str) -> set[str]:
    """Invalidate only consumers of the repaired artifact, not other branches."""
    affected = {root_id}
    while True:
        more = {str(step["id"]) for step in steps if set(step.get("dependencies") or []) & affected}
        if more <= affected:
            return affected
        affected |= more


def quality_repair_plan(artifact: dict, steps: list[dict], frozen: dict | None = None) -> dict:
    issues = [i for r in artifact.get("reports") or [] for i in r.get("issues") or [] if isinstance(i, dict)]
    codes = {str(i.get("code") or "") for i in issues}
    tools = [str(s.get("tool") or "") for s in steps]
    candidates = []
    if codes & {"content_goal_mismatch", "content_render_sample_mismatch", "content_boundary_unverified", "content_semantic_boundary_changed", "content_range_exceeded"}:
        retrieval_tool = "search_content" if "search_content" in tools else "analyze_highlights"
        candidates.append((retrieval_tool, "重新检索并核验片段", "片段内容或完整性不满足要求，需要从源素材重新取证。"))
    if codes & {"requested_cover_not_validated", "requested_cover_intro_missing", "requested_cover_intro_not_rendered"}:
        candidates.append(("propose_cover_candidates", "重新生成并核对封面", "封面未满足要求，需要重新选帧、生成和检查。"))
    if codes & {"requested_subtitles_missing", "requested_subtitle_not_applied", "requested_subtitles_not_rendered"}:
        candidates.append(("prepare_subtitle_review", "重新生成并校对字幕", "请求的字幕未正确应用，需要重新准备并检查字幕。"))
    if "target_duration_mismatch" in codes:
        candidates.append(("propose_timeline_edit", "重新编排并质检", "时长不满足要求，需要重新编排。"))
    if "delivery_aspect_mismatch" in codes:
        candidates.append(("render_social_preview", "重新生成画幅预览", "成片画幅与要求不符。"))
    unknown_codes = {"content_goal_uncertain", "content_render_sample_uncertain", "content_render_sample_unverified", "content_render_sample_unavailable", "delivery_aspect_unavailable"}
    if codes and codes <= unknown_codes:
        candidates.append(("run_delivery_qc", "重新检查当前样片", "证据不足不等于内容错误，先复查，不改动剪辑。"))
    if not candidates or any(tool not in tools for tool, _, _ in candidates):
        return {"available": False, "reason": "需要人工检查或当前计划缺少对应修复步骤。"}
    tool, label, reason = min(candidates, key=lambda row: tools.index(row[0]))
    if tool in {"search_content", "analyze_highlights"} and any((frozen or {}).get(key) for key in ("contentSelection", "outputFilename", "editSessionId")):
        return {"available": False, "reason": "当前计划限定了具体片段或版本，需要重新确认检索范围，不能自动扩大。"}
    return {"available": True, "replayFromTool": tool, "label": label, "reason": reason,
            "requiresConfirmation": True, "issueCodes": sorted(codes)}
