from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class JobStore:
    """Small durable job index; JSON files remain readable migration backups."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
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

    def save(self, job: dict[str, Any]) -> None:
        payload = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
        with self.lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs(id,payload,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (job["id"], payload, job.get("updatedAt", "")),
            )

    def load_all(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT payload FROM jobs ORDER BY updated_at").fetchall()
        jobs: list[dict[str, Any]] = []
        for (payload,) in rows:
            try:
                jobs.append(json.loads(payload))
            except (TypeError, ValueError):
                continue
        return jobs

    def delete(self, job_id: str) -> None:
        with self.lock, self._connect() as connection:
            connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))
