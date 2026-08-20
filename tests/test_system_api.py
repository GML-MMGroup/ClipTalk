from __future__ import annotations

from app.system_api import build_system_router


def test_system_router_registers_health_and_metrics() -> None:
    def handler() -> dict:
        return {"ok": True}

    router = build_system_router(health=handler, runtime_metrics=handler)
    assert {(route.path, next(iter(route.methods))) for route in router.routes} == {
        ("/api/health", "GET"),
        ("/api/metrics", "GET"),
    }
