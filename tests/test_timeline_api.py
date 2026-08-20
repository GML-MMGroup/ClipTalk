from __future__ import annotations

import pytest

from app.timeline_api import TIMELINE_ROUTES, build_timeline_router


def test_timeline_router_registers_complete_contract() -> None:
    def handler(job_id: str, group_id: str = "", segment_id: str = "", candidate_index: int = 0) -> dict:
        return {"jobId": job_id}

    handlers = {name: handler for name, _path, _method in TIMELINE_ROUTES}
    router = build_timeline_router(handlers)
    actual = {
        (route.path, next(iter(route.methods)))
        for route in router.routes
    }
    expected = {(path, method) for _name, path, method in TIMELINE_ROUTES}
    assert actual == expected


def test_timeline_router_rejects_missing_handler() -> None:
    with pytest.raises(ValueError, match="缺少时间轴路由处理器"):
        build_timeline_router({})
