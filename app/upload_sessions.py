from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .durable_files import atomic_write_json


@dataclass(frozen=True)
class ConsumedUpload:
    filename: str
    size: int
    sha256: str


class UploadSessionStore:
    """Disk-backed offset uploads that survive browser or service restarts."""

    def __init__(self, root: Path, maximum_bytes: int) -> None:
        self.root = root
        self.maximum_bytes = maximum_bytes
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    def _id(self, session_id: str) -> str:
        if not re.fullmatch(r"upl_[a-f0-9]{32}", str(session_id or "")):
            raise HTTPException(404, "上传会话不存在")
        return session_id

    def _meta_path(self, session_id: str) -> Path:
        return self.root / f"{self._id(session_id)}.json"

    def _data_path(self, session_id: str) -> Path:
        return self.root / f"{self._id(session_id)}.part"

    def _read(self, session_id: str) -> dict[str, Any]:
        try:
            metadata = json.loads(self._meta_path(session_id).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise HTTPException(404, "上传会话不存在或已过期") from error
        try:
            actual_size = self._data_path(session_id).stat().st_size
        except OSError:
            actual_size = int(metadata.get("offset") or 0)
        declared_size = int(metadata.get("size") or 0)
        metadata["offset"] = max(0, min(actual_size, declared_size)) if declared_size > 0 else max(0, actual_size)
        return metadata

    def _write_fast_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        """Update upload progress without forcing a disk sync for every chunk.

        The part file size is the source of truth for resume offsets, so this
        metadata can be published cheaply. Final job creation still validates
        the byte count and SHA-256 before accepting the upload.
        """
        path = self._meta_path(session_id)
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def get(self, session_id: str) -> dict[str, Any]:
        return self._read(session_id)

    def create(self, filename: str, size: int) -> dict[str, Any]:
        if size <= 0 or size > self.maximum_bytes:
            raise HTTPException(413, "视频大小超出上传限制")
        self.cleanup_stale()
        session_id = f"upl_{uuid.uuid4().hex}"
        clean_name = Path(filename or "video.mp4").name[:240]
        now = time.time()
        metadata = {"id": session_id, "filename": clean_name, "size": size, "offset": 0, "createdAt": now, "updatedAt": now}
        with self._lock:
            self._data_path(session_id).touch(exist_ok=False)
            atomic_write_json(self._meta_path(session_id), metadata)
        return metadata

    def append(self, session_id: str, offset: int, payload: bytes) -> dict[str, Any]:
        with self._lock:
            metadata = self._read(session_id)
            data_path = self._data_path(session_id)
            try:
                current = data_path.stat().st_size
            except OSError:
                current = int(metadata["offset"])
            if offset != current:
                raise HTTPException(409, f"上传偏移不一致，服务端已收到 {current} 字节")
            if current + len(payload) > int(metadata["size"]):
                raise HTTPException(413, "上传数据超过声明的文件大小")
            with data_path.open("ab") as handle:
                handle.write(payload)
            metadata["offset"] = current + len(payload)
            metadata["updatedAt"] = time.time()
            self._write_fast_metadata(session_id, metadata)
        return metadata

    def consume(self, session_id: str, destination: Path) -> ConsumedUpload:
        with self._lock:
            metadata = self._read(session_id)
            size = int(metadata["size"])
            source = self._data_path(session_id)
            try:
                actual_size = source.stat().st_size
            except OSError as error:
                raise HTTPException(404, "上传会话不存在或已过期") from error
            if actual_size != size:
                raise HTTPException(409, f"视频尚未上传完整：{actual_size}/{size} 字节")
            digest = hashlib.sha256()
            with source.open("rb") as handle:
                for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                    digest.update(chunk)
            source.replace(destination)
            self._meta_path(session_id).unlink(missing_ok=True)
        return ConsumedUpload(str(metadata["filename"]), size, digest.hexdigest())

    def cleanup_stale(self, maximum_age_seconds: float = 24 * 60 * 60) -> int:
        cutoff = time.time() - maximum_age_seconds
        removed = 0
        with self._lock:
            for metadata_path in self.root.glob("upl_*.json"):
                try:
                    metadata = self._read(metadata_path.stem)
                    if float(metadata.get("updatedAt") or metadata_path.stat().st_mtime) >= cutoff:
                        continue
                    self._data_path(metadata_path.stem).unlink(missing_ok=True)
                    metadata_path.unlink(missing_ok=True)
                    removed += 1
                except (HTTPException, OSError, ValueError):
                    continue
        return removed
