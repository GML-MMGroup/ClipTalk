from app.runtime_services import RuntimeServices


def test_runtime_services_owns_and_shuts_down_process_resources() -> None:
    class ActiveClient:
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    runtime = RuntimeServices.create(1)
    runtime.cancel_events["job_1"] = __import__("threading").Event()
    client = ActiveClient()
    runtime.active_model_clients["job_1"] = client
    future = runtime.analysis_executor.submit(lambda: "ok")
    assert future.result(timeout=2) == "ok"
    runtime.shutdown()
    assert runtime.cancel_events["job_1"].is_set()
    assert client.cancelled is True
