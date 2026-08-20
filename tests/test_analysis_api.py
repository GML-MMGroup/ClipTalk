from __future__ import annotations

import pytest

from app.analysis_api import ANALYSIS_ROUTES, build_analysis_router


def test_analysis_router_preserves_async_status_contract() -> None:
    def handler(job_id: str) -> dict:
        return {"jobId": job_id}

    router = build_analysis_router({name: handler for name, _path, _method, _status in ANALYSIS_ROUTES})
    routes = {(route.path, next(iter(route.methods))): route for route in router.routes}
    assert set(routes) == {(path, method) for _name, path, method, _status in ANALYSIS_ROUTES}
    assert all(route.status_code == 202 for route in routes.values())


def test_analysis_router_rejects_missing_handler() -> None:
    with pytest.raises(ValueError, match="缺少分析路由处理器"):
        build_analysis_router({})
