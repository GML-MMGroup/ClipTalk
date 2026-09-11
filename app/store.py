from __future__ import annotations

import json
import copy
import sqlite3
import threading
from pathlib import Path
from typing import Any


class JobStore:
    """Authoritative transactional job records; JSON files are migration backups."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self._committed: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def save(self, job: dict[str, Any], *, expected_revision: int | None = None) -> None:
        payload = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if row:
                revision = int(json.loads(row[0]).get("revision") or 0)
                if expected_revision is not None and revision != expected_revision:
                    raise ValueError("任务已被其他操作更新，请重新加载后重试")
                if int(job.get("revision") or 0) < revision:
                    raise ValueError("不能用旧版本覆盖已保存的任务")
            connection.execute(
                "INSERT INTO jobs(id,payload,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (job["id"], payload, job.get("updatedAt", "")),
            )
        with self.lock:
            previous = self._committed.get(str(job["id"])) or {}
            if int(job.get("revision") or 0) >= int(previous.get("revision") or 0):
                self._committed[str(job["id"])] = json.loads(payload)

    def committed_snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            return copy.deepcopy(self._committed.get(job_id))

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        value = json.loads(row[0]) if row else None
        if value is not None:
            with self.lock:
                previous = self._committed.get(job_id) or {}
                if int(value.get("revision") or 0) >= int(previous.get("revision") or 0):
                    self._committed[job_id] = copy.deepcopy(value)
        return value

    def load_all(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT payload FROM jobs ORDER BY updated_at").fetchall()
        jobs: list[dict[str, Any]] = []
        for (payload,) in rows:
            try:
                value = json.loads(payload)
                jobs.append(value)
                with self.lock:
                    previous = self._committed.get(str(value["id"])) or {}
                    if int(value.get("revision") or 0) >= int(previous.get("revision") or 0):
                        self._committed[str(value["id"])] = copy.deepcopy(value)
            except (TypeError, ValueError):
                continue
        return jobs

    def delete(self, job_id: str) -> None:
        with self.lock, self._connect() as connection:
            connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))
