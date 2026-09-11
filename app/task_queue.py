from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


TaskTarget = Callable[..., Any]
_task_context = threading.local()


def current_task_id() -> str:
    return str(getattr(_task_context, "task_id", ""))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DurableTaskStore:
    """SQLite-backed queue metadata for recoverable background tasks."""

    def __init__(self, path: Path, *, one_active_per_job: bool = True, lease_seconds: float = 90) -> None:
        self.path = path
        self.one_active_per_job = one_active_per_job
        self.lock = threading.RLock()
        self.owner_id = uuid.uuid4().hex
        self.lease_seconds = max(1.0, lease_seconds)
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
            columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
            for name, declaration in (("owner_id", "TEXT"), ("lease_until", "REAL"), ("dedup_key", "TEXT")):
                if name not in columns:
                    connection.execute(f"ALTER TABLE tasks ADD COLUMN {name} {declaration}")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS tasks_dedup ON tasks(job_id,dedup_key) "
                "WHERE dedup_key IS NOT NULL AND status IN ('queued','running','completed')"
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

    def enqueue(self, *, job_id: str, kind: str, args: tuple[Any, ...], dedup_key: str | None = None) -> dict[str, Any]:
        payload = json.dumps(list(args), ensure_ascii=False, separators=(",", ":"))
        task_id = f"task_{uuid.uuid4().hex}"
        now = _now_iso()
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if dedup_key:
                existing = connection.execute(
                    "SELECT id FROM tasks WHERE job_id=? AND dedup_key=? "
                    "AND status IN ('queued','running','completed')", (job_id, dedup_key),
                ).fetchone()
                if existing:
                    return {"id": existing[0], "duplicate": True}
            if self.one_active_per_job:
                active = connection.execute(
                    "SELECT id FROM tasks WHERE job_id=? AND status IN ('queued','running') LIMIT 1",
                    (job_id,),
                ).fetchone()
                if active:
                    raise RuntimeError(f"任务 {job_id} 已有未完成的队列记录")
            try:
                connection.execute(
                    "INSERT INTO tasks(id,job_id,kind,payload,status,attempts,error,created_at,updated_at,dedup_key) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (task_id, job_id, kind, payload, "queued", 0, "", now, now, dedup_key),
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
                "UPDATE tasks SET status='running',attempts=attempts+1,updated_at=?,owner_id=?,lease_until=? "
                "WHERE id=? AND status='queued'",
                (_now_iso(), self.owner_id, time.time() + self.lease_seconds, task_id),
            )
            return cursor.rowcount == 1

    def heartbeat(self, task_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET lease_until=?,updated_at=? WHERE id=? AND status='running' AND owner_id=?",
                (time.time() + self.lease_seconds, _now_iso(), task_id, self.owner_id),
            )
            return cursor.rowcount == 1

    def find_duplicate(self, job_id: str, dedup_key: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM tasks WHERE job_id=? AND dedup_key=? AND status IN ('queued','running','completed')",
                (job_id, dedup_key),
            ).fetchone()
        return self.get(row[0]) if row else None

    def release_abandoned_leases(self) -> None:
        """Only call after obtaining the exclusive application startup lock."""
        with self.lock, self._connect() as connection:
            connection.execute("UPDATE tasks SET lease_until=0 WHERE status='running'")

    def finish(self, task_id: str, *, status: str, error: str = "") -> None:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError(f"不支持的任务终态：{status}")
        with self.lock, self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status=?,error=?,updated_at=? "
                "WHERE id=? AND (status='queued' OR (status='running' AND owner_id=?))",
                (status, str(error)[:2000], _now_iso(), task_id, self.owner_id),
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
                "UPDATE tasks SET status='queued',updated_at=?,owner_id=NULL,lease_until=NULL "
                "WHERE status='running' AND COALESCE(lease_until,0) < ?",
                (_now_iso(), time.time()),
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

    def for_job(self, job_id: str) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            ids = connection.execute("SELECT id FROM tasks WHERE job_id=? ORDER BY created_at,id", (job_id,)).fetchall()
        return [record for (task_id,) in ids if (record := self.get(task_id)) is not None]

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
        stopped = threading.Event()

        def renew() -> None:
            while not stopped.wait(self.store.lease_seconds / 3):
                if not self.store.heartbeat(task_id):
                    return

        heartbeat = threading.Thread(target=renew, daemon=True, name=f"lease-{task_id}")
        heartbeat.start()
        previous_task = current_task_id()
        _task_context.task_id = task_id
        try:
            result = target(*args)
        except BaseException as error:
            self.store.finish(task_id, status="failed", error=str(error))
            raise
        finally:
            _task_context.task_id = previous_task
            stopped.set()
            heartbeat.join(timeout=1)
        self.store.finish(task_id, status="completed")
        return result

    def submit(self, *, job_id: str, target: TaskTarget, args: tuple[Any, ...], dedup_key: str | None = None) -> tuple[str, Future[Any]]:
        task = self.store.enqueue(job_id=job_id, kind=target.__name__, args=args, dedup_key=dedup_key)
        if task.get("duplicate"):
            future: Future[Any] = Future()
            future.set_result({"operationId": task["id"], "duplicate": True})
            return str(task["id"]), future
        try:
            future = self.executor.submit(self._execute, task["id"], target, args)
        except RuntimeError as error:
            self.store.finish(task["id"], status="failed", error=str(error))
            raise
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
