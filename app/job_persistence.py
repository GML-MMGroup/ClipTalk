"""Commit once to SQLite, then refresh the disposable JSON backup."""
from __future__ import annotations

import logging
import copy
from pathlib import Path
from typing import Any, Callable

from .store import JobStore


def persist_job(store: JobStore, job: dict[str, Any], path: Path,
                write_backup: Callable[[Path, dict[str, Any]], None]) -> None:
    revision = max(0, int(job.get("revision") or 0))
    rollback = store.committed_snapshot(str(job["id"]))
    snapshot = {**copy.deepcopy(job), "revision": revision + 1}
    try:
        store.save(snapshot, expected_revision=revision)
    except Exception:
        # Legacy writers still share this dict. Restore the last authoritative
        # snapshot in place before releasing the caller's workspace lock.
        try:
            persisted = store.get(str(job["id"]))
        except Exception:
            persisted = rollback
        if persisted is not None:
            job.clear()
            job.update(persisted)
        raise
    job["revision"] = revision + 1
    try:
        write_backup(path, snapshot)
    except Exception:
        # A failed backup is not a failed user save. SQLite is already committed.
        logging.getLogger(__name__).warning("Job JSON backup needs rebuilding: %s", job["id"], exc_info=True)
