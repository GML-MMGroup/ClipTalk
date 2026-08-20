from __future__ import annotations

from unittest.mock import patch

from app import main as main_module


def test_render_request_is_serialized_and_reconstructed() -> None:
    request = main_module.LlmOrderRequest(
        groupIds=["event_1"],
        segmentIds={"event_1": ["shot_1"]},
    )
    payload = main_module._serializable_render_arg(request)
    calls: list[tuple[str, main_module.LlmOrderRequest]] = []

    def run_llm_order_generation(
        job_id: str, restored: main_module.LlmOrderRequest,
    ) -> None:
        calls.append((job_id, restored))

    with patch.object(main_module, "run_llm_order_generation", run_llm_order_generation):
        main_module.run_persisted_render_task(
            "job_1", "run_llm_order_generation", [payload],
        )

    assert calls[0][0] == "job_1"
    assert calls[0][1].groupIds == ["event_1"]
    assert calls[0][1].segmentIds == {"event_1": ["shot_1"]}


def test_unknown_persisted_render_kind_is_rejected() -> None:
    try:
        main_module.run_persisted_render_task("job_1", "removed_render", [])
    except RuntimeError as error:
        assert "不支持的持久化渲染任务" in str(error)
    else:
        raise AssertionError("unknown render kind should fail")
