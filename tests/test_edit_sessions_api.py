from __future__ import annotations

import pytest

from app.edit_sessions_api import EDIT_SESSION_ROUTES, build_edit_sessions_router


def test_edit_sessions_router_registers_complete_contract() -> None:
    def handler(
        job_id: str,
        session_id: str = "",
        proposal_id: str = "",
    ) -> dict:
        return {"jobId": job_id}

    router = build_edit_sessions_router({
        name: handler for name, _path, _method, _status in EDIT_SESSION_ROUTES
    })
    actual = {
        (route.path, next(iter(route.methods))): route.status_code
        for route in router.routes
    }
    expected = {
        (path, method): status_code
        for _name, path, method, status_code in EDIT_SESSION_ROUTES
    }
    assert actual == expected


def test_edit_sessions_router_rejects_missing_handler() -> None:
    with pytest.raises(ValueError, match="缺少二次编辑路由处理器"):
        build_edit_sessions_router({})
