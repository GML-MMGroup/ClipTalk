from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def parse_skill_markdown(markdown: str) -> dict[str, Any]:
    if not markdown.startswith("---\n"):
        raise ValueError("SKILL.md 缺少 YAML frontmatter")
    end = markdown.find("\n---", 4)
    if end < 0:
        raise ValueError("SKILL.md frontmatter 未闭合")
    fields: dict[str, str] = {}
    for raw_line in markdown[4:end].splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name or len(name) > 64 or not SKILL_NAME_PATTERN.fullmatch(name):
        raise ValueError("Skill name 必须为不超过 64 字符的小写字母、数字和连字符")
    if not description or len(description) > 1024:
        raise ValueError("Skill description 必须为 1–1024 字符")
    allowed_tools = [item for item in fields.get("allowed-tools", "").split() if item]
    workflow_profile = fields.get("workflow-profile", "").strip().lower()
    version = fields.get("version", "1.0.0").strip()
    if not SKILL_VERSION_PATTERN.fullmatch(version):
        raise ValueError("Skill version 必须使用语义版本，例如 1.1.0")
    return {
        "name": name, "description": description, "allowedTools": allowed_tools,
        "workflowProfile": workflow_profile, "version": version,
    }


class AgentStore:
    """Durable Agent registry, plan, run and event store."""

    ENTITY_TABLES = frozenset({"workspaces", "skills", "plugins", "plans", "runs"})

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            for table in self.ENTITY_TABLES:
                connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ("
                    "id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                    "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, "
                "event_type TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS events_workspace_sequence "
                "ON events(workspace_id,sequence)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def save(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        if table not in self.ENTITY_TABLES:
            raise ValueError(f"不支持的数据表：{table}")
        item = dict(payload)
        item_id = str(item.get("id") or f"{table[:-1]}_{uuid.uuid4().hex}")
        timestamp = now_iso()
        item["id"] = item_id
        item.setdefault("createdAt", timestamp)
        item["updatedAt"] = timestamp
        serialized = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        with self.lock, self._connect() as connection:
            connection.execute(
                f"INSERT INTO {table}(id,payload,created_at,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (item_id, serialized, item["createdAt"], timestamp),
            )
        return item

    def get(self, table: str, item_id: str) -> dict[str, Any] | None:
        if table not in self.ENTITY_TABLES:
            raise ValueError(f"不支持的数据表：{table}")
        with self.lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT payload FROM {table} WHERE id=?", (item_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(
        self, table: str, *, newest_first: bool = True,
        predicate: Any | None = None,
    ) -> list[dict[str, Any]]:
        if table not in self.ENTITY_TABLES:
            raise ValueError(f"不支持的数据表：{table}")
        direction = "DESC" if newest_first else "ASC"
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM {table} ORDER BY updated_at {direction},id {direction}"
            ).fetchall()
        items = [json.loads(row[0]) for row in rows]
        return [item for item in items if predicate(item)] if predicate else items

    def delete(self, table: str, item_id: str) -> bool:
        if table not in self.ENTITY_TABLES:
            raise ValueError(f"不支持的数据表：{table}")
        with self.lock, self._connect() as connection:
            cursor = connection.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
        return cursor.rowcount > 0

    def append_event(
        self, workspace_id: str, event_type: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp = now_iso()
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO events(workspace_id,event_type,payload,created_at) VALUES(?,?,?,?)",
                (workspace_id, event_type, serialized, timestamp),
            )
            sequence = int(cursor.lastrowid)
        return {
            "sequence": sequence, "workspaceId": workspace_id,
            "type": event_type, "payload": payload, "createdAt": timestamp,
        }

    def events_after(
        self, workspace_id: str, sequence: int = 0, *, limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT sequence,event_type,payload,created_at FROM events "
                "WHERE workspace_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (workspace_id, max(0, sequence), min(max(1, limit), 1000)),
            ).fetchall()
        return [{
            "sequence": int(row[0]), "workspaceId": workspace_id,
            "type": str(row[1]), "payload": json.loads(row[2]), "createdAt": str(row[3]),
        } for row in rows]
