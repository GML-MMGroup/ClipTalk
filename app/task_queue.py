from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


TaskTarget = Callable[..., Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DurableTaskStore:
    """SQLite-backed queue metadata for recoverable background tasks."""

    def __init__(self, path: Path, *, one_active_per_job: bool = True) -> None:
        self.path = path
        self.one_active_per_job = one_active_per_job
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "id TEXT PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL, "
                "payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, "
                "error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS tasks_job_status ON tasks(job_id,status,created_at)"
            )
            if one_active_per_job:
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS tasks_one_active_per_job ON tasks(job_id) "
                    "WHERE status IN ('queued','running')"
                )
            else:
                # Render work may legitimately overlap for one job: automatic
                # background previews stay available while the user confirms
                # a separate final export.
                connection.execute("DROP INDEX IF EXISTS tasks_one_active_per_job")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def enqueue(self, *, job_id: str, kind: str, args: tuple[Any, ...]) -> dict[str, Any]:
        payload = json.dumps(list(args), ensure_ascii=False, separators=(",", ":"))
        task_id = f"task_{uuid.uuid4().hex}"
        now = _now_iso()
        with self.lock, self._connect() as connection:
            if self.one_active_per_job:
                active = connection.execute(
                    "SELECT id FROM tasks WHERE job_id=? AND status IN ('queued','running') LIMIT 1",
                    (job_id,),
                ).fetchone()
                if active:
                    raise RuntimeError(f"任务 {job_id} 已有未完成的队列记录")
            try:
                connection.execute(
                    "INSERT INTO tasks(id,job_id,kind,payload,status,attempts,error,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (task_id, job_id, kind, payload, "queued", 0, "", now, now),
                )
            except sqlite3.IntegrityError as error:
                raise RuntimeError(f"任务 {job_id} 已有未完成的队列记录") from error
        return {
            "id": task_id, "jobId": job_id, "kind": kind, "args": list(args),
            "status": "queued", "attempts": 0, "createdAt": now, "updatedAt": now,
        }

    def claim(self, task_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status='running',attempts=attempts+1,updated_at=? "
                "WHERE id=? AND status='queued'",
                (_now_iso(), task_id),
            )
            return cursor.rowcount == 1

    def finish(self, task_id: str, *, status: str, error: str = "") -> None:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError(f"不支持的任务终态：{status}")
        with self.lock, self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status=?,error=?,updated_at=? "
                "WHERE id=? AND status IN ('queued','running')",
                (status, str(error)[:2000], _now_iso(), task_id),
            )

    def cancel_job(self, job_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status='cancelled',updated_at=? "
                "WHERE job_id=? AND status IN ('queued','running')",
                (_now_iso(), job_id),
            )
            return cursor.rowcount > 0

    def delete_job(self, job_id: str) -> None:
        with self.lock, self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE job_id=?", (job_id,))

    def recoverable_job_ids(self) -> set[str]:
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT job_id FROM tasks WHERE status IN ('queued','running')"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def prepare_recovery(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status='queued',updated_at=? WHERE status='running'",
                (_now_iso(),),
            )
            rows = connection.execute(
                "SELECT id,job_id,kind,payload,status,attempts,created_at,updated_at "
                "FROM tasks WHERE status='queued' ORDER BY created_at,id"
            ).fetchall()
        tasks: list[dict[str, Any]] = []
        for row in rows:
            try:
                args = json.loads(row[3])
            except (TypeError, ValueError):
                self.finish(str(row[0]), status="failed", error="持久化任务参数损坏")
                continue
            if not isinstance(args, list):
                self.finish(str(row[0]), status="failed", error="持久化任务参数格式无效")
                continue
            tasks.append({
                "id": str(row[0]), "jobId": str(row[1]), "kind": str(row[2]),
                "args": args, "status": str(row[4]), "attempts": int(row[5]),
                "createdAt": str(row[6]), "updatedAt": str(row[7]),
            })
        return tasks

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT id,job_id,kind,payload,status,attempts,error,created_at,updated_at "
                "FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]), "jobId": str(row[1]), "kind": str(row[2]),
            "args": json.loads(row[3]), "status": str(row[4]),
            "attempts": int(row[5]), "error": str(row[6]),
            "createdAt": str(row[7]), "updatedAt": str(row[8]),
        }

    def stats(self) -> dict[str, int]:
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT status,COUNT(*) FROM tasks GROUP BY status ORDER BY status"
            ).fetchall()
        return {str(status): int(count) for status, count in rows}


class DurableTaskExecutor:
    """Execute queue records while preserving enough metadata for restart recovery."""

    def __init__(self, *, store: DurableTaskStore, executor: ThreadPoolExecutor) -> None:
        self.store = store
        self.executor = executor

    def _execute(self, task_id: str, target: TaskTarget, args: tuple[Any, ...]) -> Any:
        if not self.store.claim(task_id):
            return None
        try:
            result = target(*args)
        except BaseException as error:
            self.store.finish(task_id, status="failed", error=str(error))
            raise
        self.store.finish(task_id, status="completed")
        return result

    def submit(self, *, job_id: str, target: TaskTarget, args: tuple[Any, ...]) -> tuple[str, Future[Any]]:
        task = self.store.enqueue(job_id=job_id, kind=target.__name__, args=args)
        future = self.executor.submit(self._execute, task["id"], target, args)
        future.add_done_callback(
            lambda completed: self.store.finish(task["id"], status="cancelled")
            if completed.cancelled() else None
        )
        return str(task["id"]), future

    def recover(
        self,
        *,
        resolve_target: Callable[[str], TaskTarget | None],
        should_run: Callable[[str], bool],
    ) -> list[tuple[str, str, Future[Any]]]:
        recovered: list[tuple[str, str, Future[Any]]] = []
        for task in self.store.prepare_recovery():
            task_id = str(task["id"])
            job_id = str(task["jobId"])
            target = resolve_target(str(task["kind"]))
            if target is None or not should_run(job_id):
                self.store.finish(task_id, status="cancelled")
                continue
            args = tuple(task["args"])
            future = self.executor.submit(self._execute, task_id, target, args)
            future.add_done_callback(
                lambda completed, current_id=task_id: self.store.finish(current_id, status="cancelled")
                if completed.cancelled() else None
            )
            recovered.append((job_id, task_id, future))
        return recovered
