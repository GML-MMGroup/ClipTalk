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
from .output_naming import NAMING_VERSION, build_output_naming


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

    @classmethod
    def friendly_output_naming(
        cls, *, source_filename: str, version_number: Any = 1,
        strategy_key: str = "manual", source_label: str = "",
        display_name: str = "", title: str = "高光成片",
        position: int = 1, extension: str = "mp4", display_title: str = "",
        name_subject: str = "", name_variant: str = "", aspect: str = "",
        preview_only: bool = False, output_count: int = 1,
    ) -> dict[str, Any]:
        output = {
            "title": title,
            "displayName": display_name,
            "previewOnly": preview_only,
            **({"reframe": {"aspect": aspect}} if aspect else {}),
        }
        if display_title:
            output.update({
                "namingVersion": NAMING_VERSION,
                "displayTitle": display_title,
                "nameSubject": name_subject or str(display_title).split(" · ", 1)[0],
                "nameVariant": name_variant or (str(display_title).split(" · ", 1)[1] if " · " in str(display_title) else ""),
            })
        version = {
            "number": version_number,
            "strategyKey": strategy_key,
            "sourceLabel": source_label,
            "displayName": display_name,
            "previewOnly": preview_only,
        }
        return build_output_naming(
            {"filename": source_filename}, version, output,
            position=position, output_count=output_count, extension=extension,
        )

    @classmethod
    def friendly_download_filename(cls, **kwargs: Any) -> str:
        return str(cls.friendly_output_naming(**kwargs)["downloadFilename"])

    @classmethod
    def _record_naming(cls, record: dict[str, Any], *, extension: str = "mp4") -> dict[str, Any]:
        return cls.friendly_output_naming(
            source_filename=str(record.get("sourceFilename") or "视频"),
            version_number=record.get("versionNumber", 1),
            strategy_key=str(record.get("strategyKey") or "manual"),
            source_label=str(record.get("sourceLabel") or ""),
            display_name=str(record.get("displayName") or ""),
            title=str(record.get("title") or "高光成片"),
            position=int(record.get("position") or 1),
            extension=extension,
            display_title=str(record.get("displayTitle") or ""),
            name_subject=str(record.get("nameSubject") or ""),
            name_variant=str(record.get("nameVariant") or ""),
            aspect=str(record.get("aspectLabel") or ""),
            preview_only=bool(record.get("previewOnly")),
            output_count=int(record.get("outputCount") or 1),
        )

    def public_record(self, record: dict[str, Any]) -> dict[str, Any]:
        job_id = str(record["jobId"])
        filename = str(record["filename"])
        naming = self._record_naming(record)
        return {
            **record,
            **naming,
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
        temporary_metadata = metadata.with_name(f".{metadata.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            temporary.replace(media)
            stored = {**record, "sizeBytes": media.stat().st_size}
            temporary_metadata.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary_metadata.replace(metadata)
            if existing_preview and existing_preview.is_file():
                shutil.copy2(existing_preview, self.preview_path(media))
            return stored
        finally:
            temporary.unlink(missing_ok=True)
            temporary_metadata.unlink(missing_ok=True)

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
                download_name = str(self._record_naming(record)["downloadFilename"])
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
