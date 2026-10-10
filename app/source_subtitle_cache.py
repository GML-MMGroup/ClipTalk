"""Bounded cache of individual subtitle observations, never whole-video claims."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any


CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_CACHE_ROWS = 8192


def frame_cache_key(source_hash: str, client: Any, frame: Path, sample_time: float,
                    rules: str) -> str | None:
    # Use the resolved client, not a possibly stale job configuration. Never
    # serialize credentials, prompts or endpoint URLs to the cache database.
    model, endpoint = getattr(client, "model", None), getattr(client, "url", None)
    if not source_hash or not isinstance(model, str) or not model or not isinstance(endpoint, str) or not endpoint:
        return None
    try:
        if not math.isfinite(float(sample_time)):
            return None
        frame_digest = hashlib.sha256(Path(frame).read_bytes()).hexdigest()
        identity = {
            "version": 1, "source": source_hash, "frame": frame_digest,
            "time": float(sample_time).hex(), "rules": rules,
            "client": f"{type(client).__module__}.{type(client).__qualname__}",
            "model": model, "endpoint": endpoint,
            "thinking": getattr(client, "thinking_type", ""),
            "format": getattr(client, "response_format", ""),
        }
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    except (OSError, TypeError, ValueError):
        return None


class SubtitleFrameCache:
    """Optional optimization: unavailable/corrupt storage must not stop checking."""

    def __init__(self, data_root: Path):
        self.path = Path(data_root).resolve() / "cache" / "source-subtitle-frames.sqlite3"

    def get(self, key: str | None) -> str | None:
        if not key or not self.path.is_file():
            return None
        try:
            connection = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=.2)
            try:
                row = connection.execute("SELECT verdict, created FROM frames WHERE key = ?", (key,)).fetchone()
                now = time.time()
                if row and row[0] in {"present", "clear"} and now - CACHE_TTL_SECONDS <= row[1] <= now:
                    return row[0]
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError):
            pass
        return None

    def put(self, key: str | None, verdict: str) -> None:
        if not key or verdict not in {"present", "clear"}:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=.2)
            try:
                with connection:
                    connection.execute("CREATE TABLE IF NOT EXISTS frames (key TEXT PRIMARY KEY, verdict TEXT NOT NULL, created REAL NOT NULL)")
                    connection.execute("INSERT OR REPLACE INTO frames VALUES (?, ?, ?)", (key, verdict, time.time()))
                    connection.execute("DELETE FROM frames WHERE created < ?", (time.time() - CACHE_TTL_SECONDS,))
                    connection.execute("DELETE FROM frames WHERE key IN (SELECT key FROM frames ORDER BY created DESC, rowid DESC LIMIT -1 OFFSET ?)", (MAX_CACHE_ROWS,))
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            pass
