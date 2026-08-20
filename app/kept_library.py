from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import FileResponse

from .media import create_preview_proxy, probe_video


class KeptLibraryService:
    """Filesystem-backed durable output library, independent of job cleanup."""

    def __init__(
        self, *, data_root: Path, ffmpeg: str, ffprobe: str,
        preview_lock: threading.Lock | threading.RLock,
    ) -> None:
        self.data_root = data_root
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.preview_lock = preview_lock

    def job_directory(self, job_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", job_id) or job_id in {".", ".."}:
            raise HTTPException(400, "保留库任务编号无效")
        return self.data_root / "kept" / job_id

    def output_paths(self, job_id: str, filename: str) -> tuple[Path, Path]:
        if not filename or Path(filename).name != filename or filename in {".", ".."}:
            raise HTTPException(400, "保留库文件名无效")
        media = self.job_directory(job_id) / filename
        return media, media.with_name(f"{media.name}.json")

    @staticmethod
    def preview_path(media: Path) -> Path:
        return media.with_name(f".{media.name}.preview.mp4")

    @staticmethod
    def _download_component(value: Any, fallback: str, maximum: int = 48) -> str:
        text = Path(str(value or fallback)).stem
        text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", text).strip(" .-_")
        text = re.sub(r"\s+", "_", text)
        return text[:maximum] or fallback

    @classmethod
    def friendly_download_filename(
        cls, *, source_filename: str, version_number: Any = 1,
        strategy_key: str = "manual", source_label: str = "",
        display_name: str = "", title: str = "高光成片",
        position: int = 1, extension: str = "mp4",
    ) -> str:
        try:
            version = max(1, int(version_number or 1))
        except (TypeError, ValueError):
            version = 1
        try:
            index = max(1, int(position or 1))
        except (TypeError, ValueError):
            index = 1
        key = str(strategy_key or "").lower()
        label_text = f"{source_label} {display_name}".upper()
        if key == "vlm" or "VLM" in label_text:
            strategy = "VLM"
        elif key in {"narrative", "emotion", "information", "llm"} or "LLM" in label_text:
            strategy = "LLM"
        else:
            strategy = "手动合成"
        clean_title = re.sub(
            r"\s*[·|｜]\s*(?:VLM|LLM).*?$", "",
            str(display_name or title or "高光成片"), flags=re.IGNORECASE,
        ).strip()
        title_parts = [part.strip() for part in re.split(r"[·|｜]", clean_title) if part.strip()]
        if len(title_parts) > 1 and title_parts[0] == title_parts[-1]:
            clean_title = title_parts[0]
        source = cls._download_component(source_filename, "视频", 48)
        title_part = cls._download_component(clean_title, "高光成片", 48)
        suffix = str(extension or "mp4").lower().lstrip(".") or "mp4"
        return f"{source}_V{version:03d}_{strategy}-{title_part}_{index:02d}.{suffix}"

    def public_record(self, record: dict[str, Any]) -> dict[str, Any]:
        job_id = str(record["jobId"])
        filename = str(record["filename"])
        download_name = str(record.get("downloadFilename") or self.friendly_download_filename(
            source_filename=str(record.get("sourceFilename") or "视频"),
            version_number=record.get("versionNumber", 1),
            strategy_key=str(record.get("strategyKey") or "manual"),
            source_label=str(record.get("sourceLabel") or ""),
            display_name=str(record.get("displayName") or ""),
            title=str(record.get("title") or "高光成片"),
            position=int(record.get("position") or 1),
        ))
        return {
            **record,
            "downloadFilename": download_name,
            "videoUrl": f"/api/kept/{quote(job_id, safe='')}/{quote(filename, safe='')}",
            "downloadUrl": f"/api/kept/{quote(job_id, safe='')}/{quote(filename, safe='')}?download=1",
        }

    def list_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for metadata in (self.data_root / "kept").glob("*/*.mp4.json"):
            try:
                record = json.loads(metadata.read_text(encoding="utf-8"))
                media, expected_metadata = self.output_paths(str(record["jobId"]), str(record["filename"]))
                if expected_metadata != metadata or not media.is_file():
                    continue
                record["sizeBytes"] = media.stat().st_size
                records.append(self.public_record(record))
            except (OSError, ValueError, KeyError, TypeError, HTTPException):
                continue
        return sorted(records, key=lambda item: str(item.get("keptAt", "")), reverse=True)

    def save_copy(self, *, source: Path, record: dict[str, Any], existing_preview: Path | None = None) -> dict[str, Any]:
        if not source.is_file():
            raise HTTPException(404, "待保留的高光文件不存在")
        media, metadata = self.output_paths(str(record["jobId"]), str(record["filename"]))
        media.parent.mkdir(parents=True, exist_ok=True)
        temporary = media.with_name(f".{media.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            temporary.replace(media)
            stored = {**record, "sizeBytes": media.stat().st_size}
            metadata.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
            if existing_preview and existing_preview.is_file():
                shutil.copy2(existing_preview, self.preview_path(media))
            return stored
        finally:
            temporary.unlink(missing_ok=True)

    def media_response(self, job_id: str, filename: str, *, download: bool = False) -> FileResponse:
        path, metadata = self.output_paths(job_id, filename)
        if not path.is_file() or not metadata.is_file():
            raise HTTPException(404, "保留库文件不存在")
        download_name = filename
        if download:
            try:
                record = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                record = {}
            if isinstance(record, dict):
                download_name = str(record.get("downloadFilename") or self.friendly_download_filename(
                    source_filename=str(record.get("sourceFilename") or "视频"),
                    version_number=record.get("versionNumber", 1),
                    strategy_key=str(record.get("strategyKey") or "manual"),
                    source_label=str(record.get("sourceLabel") or ""),
                    display_name=str(record.get("displayName") or ""),
                    title=str(record.get("title") or "高光成片"),
                    position=int(record.get("position") or 1),
                ))
        served_path = path
        if not download:
            preview = self.preview_path(path)
            if not preview.is_file():
                with self.preview_lock:
                    if not preview.is_file():
                        info = probe_video(path, self.ffprobe)
                        create_preview_proxy(path, preview, has_audio=info.has_audio, ffmpeg=self.ffmpeg)
            served_path = preview
        return FileResponse(
            served_path,
            media_type="video/mp4",
            filename=download_name if download else filename,
            content_disposition_type="attachment" if download else "inline",
        )

    def remove(self, job_id: str, filename: str) -> None:
        media, metadata = self.output_paths(job_id, filename)
        media.unlink(missing_ok=True)
        self.preview_path(media).unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        try:
            media.parent.rmdir()
        except OSError:
            pass
