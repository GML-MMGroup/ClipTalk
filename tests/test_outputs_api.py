from __future__ import annotations

import pytest

from app.outputs_api import OUTPUT_ROUTES, build_outputs_router


def test_outputs_router_registers_methods_and_status_codes() -> None:
    def handler(job_id: str, version_id: str = "", filename: str = "", plan_id: str = "") -> dict:
        return {"jobId": job_id}

    router = build_outputs_router({name: handler for name, _path, _method, _status in OUTPUT_ROUTES})
    routes = {
        (route.path, next(iter(route.methods))): route
        for route in router.routes
    }
    assert set(routes) == {(path, method) for _name, path, method, _status in OUTPUT_ROUTES}
    for _name, path, method, status_code in OUTPUT_ROUTES:
        assert routes[(path, method)].status_code == status_code


def test_outputs_router_rejects_missing_handler() -> None:
    with pytest.raises(ValueError, match="缺少成片路由处理器"):
        build_outputs_router({})
