from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.task_queue import DurableTaskExecutor, DurableTaskStore


def test_durable_executor_records_successful_task() -> None:
    with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=1) as pool:
        store = DurableTaskStore(Path(directory) / "tasks.sqlite3")
        executor = DurableTaskExecutor(store=store, executor=pool)

        def add(left: int, right: int) -> int:
            return left + right

        task_id, future = executor.submit(job_id="job_1", target=add, args=(2, 3))
        assert future.result(timeout=2) == 5
        task = store.get(task_id)
        assert task is not None
        assert task["status"] == "completed"
        assert task["attempts"] == 1


def test_store_prevents_two_active_analysis_tasks_for_one_job() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = DurableTaskStore(Path(directory) / "tasks.sqlite3")
        store.enqueue(job_id="job_1", kind="run_job", args=("job_1",))
        with pytest.raises(RuntimeError, match="已有未完成"):
            store.enqueue(job_id="job_1", kind="run_job", args=("job_1", "retry"))
        assert store.cancel_job("job_1")
        replacement = store.enqueue(job_id="job_1", kind="run_job", args=("job_1", "retry"))
        assert replacement["status"] == "queued"


def test_store_can_allow_overlapping_render_tasks_for_one_job() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = DurableTaskStore(
            Path(directory) / "render-tasks.sqlite3",
            one_active_per_job=False,
        )
        first = store.enqueue(job_id="job_1", kind="render", args=("preview",))
        second = store.enqueue(job_id="job_1", kind="render", args=("final",))
        assert first["status"] == "queued"
        assert second["status"] == "queued"
        assert store.recoverable_job_ids() == {"job_1"}


def test_running_task_is_recovered_after_simulated_restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = DurableTaskStore(Path(directory) / "tasks.sqlite3")
        task = store.enqueue(job_id="job_1", kind="record", args=("job_1", "retry"))
        assert store.claim(task["id"])
        calls: list[tuple[str, str]] = []

        def record(job_id: str, action: str) -> None:
            calls.append((job_id, action))

        with ThreadPoolExecutor(max_workers=1) as pool:
            executor = DurableTaskExecutor(store=store, executor=pool)
            recovered = executor.recover(
                resolve_target=lambda kind: record if kind == "record" else None,
                should_run=lambda job_id: job_id == "job_1",
            )
            assert len(recovered) == 1
            recovered[0][2].result(timeout=2)
        assert calls == [("job_1", "retry")]
        persisted = store.get(task["id"])
        assert persisted is not None
        assert persisted["status"] == "completed"
        assert persisted["attempts"] == 2


def test_recovery_cancels_unknown_or_obsolete_task_kind() -> None:
    with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=1) as pool:
        store = DurableTaskStore(Path(directory) / "tasks.sqlite3")
        task = store.enqueue(job_id="job_1", kind="removed_task", args=("job_1",))
        executor = DurableTaskExecutor(store=store, executor=pool)
        assert executor.recover(resolve_target=lambda _kind: None, should_run=lambda _job: True) == []
        assert store.get(task["id"])["status"] == "cancelled"
