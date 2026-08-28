from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter


EDIT_SESSION_ROUTES = (
    ("create_edit_session", "/api/jobs/{job_id}/edit-sessions", "POST", 201),
    ("update_edit_session", "/api/jobs/{job_id}/edit-sessions/{session_id}", "PATCH", 200),
    ("undo_edit_session", "/api/jobs/{job_id}/edit-sessions/{session_id}/undo", "POST", 200),
    ("redo_edit_session", "/api/jobs/{job_id}/edit-sessions/{session_id}/redo", "POST", 200),
    ("preview_edit_session", "/api/jobs/{job_id}/edit-sessions/{session_id}/preview", "POST", 202),
    ("edit_session_preview_media", "/api/jobs/{job_id}/edit-sessions/{session_id}/preview", "GET", 200),
    ("render_edit_session", "/api/jobs/{job_id}/edit-sessions/{session_id}/render", "POST", 202),
    ("create_edit_session_proposal", "/api/jobs/{job_id}/edit-sessions/{session_id}/proposals", "POST", 200),
    ("apply_edit_session_proposal", "/api/jobs/{job_id}/edit-sessions/{session_id}/proposals/{proposal_id}/apply", "POST", 200),
    ("cancel_edit_session_proposal", "/api/jobs/{job_id}/edit-sessions/{session_id}/proposals/{proposal_id}", "DELETE", 200),
)


def build_edit_sessions_router(handlers: Mapping[str, Callable[..., Any]]) -> APIRouter:
    missing = [name for name, _path, _method, _status in EDIT_SESSION_ROUTES if name not in handlers]
    if missing:
        raise ValueError(f"缺少二次编辑路由处理器：{', '.join(missing)}")
    router = APIRouter(tags=["edit-sessions"])
    for name, path, method, status_code in EDIT_SESSION_ROUTES:
        router.add_api_route(path, handlers[name], methods=[method], status_code=status_code)
    return router
