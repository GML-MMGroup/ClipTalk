from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter


TIMELINE_ROUTES = (
    ("create_event_group", "/api/jobs/{job_id}/event-groups", "POST"),
    ("create_event_group_from_candidates", "/api/jobs/{job_id}/event-groups/from-candidates", "POST"),
    ("rename_event_group", "/api/jobs/{job_id}/event-groups/{group_id}", "PATCH"),
    ("add_event_group_segment", "/api/jobs/{job_id}/event-groups/{group_id}/segments", "POST"),
    ("adjust_event_group_segment", "/api/jobs/{job_id}/event-groups/{group_id}/segments/{segment_id}/adjust", "POST"),
    ("delete_event_group_segment", "/api/jobs/{job_id}/event-groups/{group_id}/segments/{segment_id}", "DELETE"),
    ("reorder_event_group_segments", "/api/jobs/{job_id}/event-groups/{group_id}/segments/reorder", "POST"),
    ("move_event_group_segment", "/api/jobs/{job_id}/event-groups/{group_id}/segments/{segment_id}/move", "POST"),
    ("adjust_job_candidate", "/api/jobs/{job_id}/candidates/{candidate_index}/adjust", "POST"),
    ("set_review_exclusions", "/api/jobs/{job_id}/review-exclusions", "POST"),
    ("set_job_timeline_selection", "/api/jobs/{job_id}/selection", "POST"),
    ("undo_job_timeline", "/api/jobs/{job_id}/timeline/undo", "POST"),
    ("redo_job_timeline", "/api/jobs/{job_id}/timeline/redo", "POST"),
    ("apply_edit_proposal", "/api/jobs/{job_id}/edit-proposals/{proposal_id}/apply", "POST"),
    ("cancel_edit_proposal", "/api/jobs/{job_id}/edit-proposals/{proposal_id}", "DELETE"),
    ("preview_technique_plan", "/api/jobs/{job_id}/technique-plan", "POST"),
    ("update_event_segment_technique", "/api/jobs/{job_id}/event-groups/{group_id}/segments/{segment_id}/technique", "PATCH"),
)


def build_timeline_router(handlers: Mapping[str, Callable[..., Any]]) -> APIRouter:
    """Own timeline, event-group and per-shot editing routes."""
    missing = [name for name, _path, _method in TIMELINE_ROUTES if name not in handlers]
    if missing:
        raise ValueError(f"缺少时间轴路由处理器：{', '.join(missing)}")
    router = APIRouter(tags=["timeline"])
    for name, path, method in TIMELINE_ROUTES:
        router.add_api_route(path, handlers[name], methods=[method])
    return router
