"""Output-scoped delivery contracts, immutable export identity and permissions."""
from __future__ import annotations

import hashlib
import json
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from .api_schemas import FinalizeOutputVersionRequest
from .media import normalize_subtitle_style
from .render_spec import output_spec, content_hash


@dataclass(frozen=True)
class FormalExport:
    title: str
    key: str
    render_args: tuple[Any, ...]


def prepare_formal_export(job_id: str, version: dict[str, Any], request: FinalizeOutputVersionRequest,
                          quality_status: str, subtitle_draft: dict | None = None) -> FormalExport:
    """Validate user approval and freeze the reproducible render specification."""
    if request.subtitleMode not in {"none", "burn"}:
        raise HTTPException(400, "字幕方式无效")
    if request.subtitleMode == "burn" and not request.subtitleDraftId:
        raise HTTPException(409, "添加字幕前必须先完成字幕校对")
    if not version.get("previewOnly"):
        raise HTTPException(409, "该版本已经是正式成片")
    if quality_status != "passed" and not request.acknowledgeQualityRisk:
        gate = version.get("qualityGate") if isinstance(version.get("qualityGate"), dict) else {}
        reasons = [str(value) for value in gate.get("reasons") or [] if str(value)]
        summary = {
            "review_unavailable": "AI 审片未完成，无法证明该样片达到自动质量标准",
            "needs_review": "该样片未通过自动质量门",
        }.get(quality_status, "该样片尚未完成质量检查")
        if reasons:
            summary += "：" + "；".join(reasons[:3])
        raise HTTPException(409, f"{summary}。如已人工预览并接受风险，请明确确认后再导出高清成片")
    output = select_export_output(version, request.outputFilename, request.outputRevision)
    if not request.outputFilename or not request.outputRevision or request.specVersion != 1:
        raise HTTPException(409, {"code": "export_confirmation_required", "message": "请刷新样片并重新确认导出文件与规格"})
    style = normalize_subtitle_style(request.subtitleStyle)
    if request.subtitleMode == "burn" and (not subtitle_draft
            or request.subtitleDraftRevision != subtitle_draft.get("revision")
            or request.subtitleDraftHash != content_hash(subtitle_draft)):
        raise HTTPException(409, "字幕草稿已变化，请重新校对并确认")
    spec = output_spec(output, version, subtitle_mode=request.subtitleMode, subtitle_style=style,
                       subtitle_draft=subtitle_draft)
    key = export_key(job_id, version, output, {"subtitleMode": request.subtitleMode,
                     "subtitleStyle": style, "subtitleDraftId": request.subtitleDraftId, "specHash": spec["hash"]})
    title = str(output.get("displayName") or output.get("title") or "AI 精剪成片")
    source_meta = {name: copy.deepcopy(version[name]) for name in (
        "strategyKey", "displayName", "sourceLabel", "strategyDescription", "recommended",
        "recommendationReason", "reviewStatus", "reviewReport", "qualityGate", "qualityStatus",
        "generationBatchId", "editorialNarrative", "orderMode", "orderReason", "parentVersionId",
    ) if version.get(name) is not None}
    source_id = str(version["id"])
    source_meta.update({"sourceVersionId": source_id, "parentVersionId": source_id,
                        "variantKind": "formal_export", "sourceOutputFilename": output["filename"],
                        "exportKey": key, "qualityStatus": quality_status})
    args = ([], "single_reel", "complete", "", True, spec["segments"], title, spec["chapters"],
            request.subtitleMode, "selection", style, source_meta, False, spec["cutaways"],
            spec["techniquePolicy"], source_id, request.subtitleDraftId, spec["textLayers"], spec["reframe"], spec)
    return FormalExport(title=title, key=key, render_args=copy.deepcopy(args))


def output_revision(version: dict[str, Any], output: dict[str, Any]) -> str:
    # Exclude presentation, progress, kept flags and generated URLs. Only changes
    # to the selected edit or its quality decision invalidate a confirmation.
    payload = {
        "versionId": version.get("id"),
        "output": {key: output.get(key) for key in (
            "filename", "segments", "cutaways", "chapters", "techniquePolicy",
            "subtitleMode", "subtitleStyle", "subtitleDraftId", "socialReframe", "reframe",
            "textLayers", "renderSpec", "subtitleDraftRevision", "subtitleCues", "subtitleLayout", "subtitleCueStyles",
        )},
        "quality": {key: version.get(key) for key in ("qualityGate", "qualityStatus", "reviewReport")},
        "versionSpec": {key: version.get(key) for key in ("reframe", "textLayers", "socialReframe")},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def select_export_output(version: dict[str, Any], filename: str | None,
                         revision: str | None) -> dict[str, Any]:
    outputs = [item for item in version.get("outputs") or [] if isinstance(item, dict)]
    if filename:
        output = next((item for item in outputs if item.get("filename") == filename), None)
        if output is None:
            raise HTTPException(404, "所选文件不属于此样片版本")
    elif len(outputs) == 1:
        output = outputs[0]  # Legacy single-output clients remain unambiguous.
    else:
        raise HTTPException(409, "该版本包含多个文件，请明确选择要导出的文件")
    if not output.get("segments"):
        raise HTTPException(409, "样片缺少可复现的剪辑时间线")
    if revision and revision != output_revision(version, output):
        raise HTTPException(409, "所选样片已更新，请重新预览并确认导出")
    return output


def export_key(job_id: str, version: dict[str, Any], output: dict[str, Any], params: dict[str, Any]) -> str:
    payload = [job_id, output_revision(version, output), params]
    return "formal:" + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def merge_committed_version(job: dict[str, Any], version: dict[str, Any]) -> list[dict[str, Any]]:
    """Called under the workspace lock so simultaneous renders cannot lose outputs."""
    versions = list(job.get("outputVersions") or [])
    key = version.get("exportKey")
    for existing in versions:
        if existing.get("id") == version.get("id") or (key and existing.get("exportKey") == key):
            return versions
    return [*versions, version]


def output_capabilities(job: dict[str, Any], version: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    filename = str(output.get("filename") or "")
    directory = job.get("outputDirectory")
    safe = bool(filename and Path(filename).name == filename and directory)
    exists = safe and (Path(directory) / filename).is_file()
    preview = bool(version.get("previewOnly") or output.get("previewOnly"))
    source = bool(job.get("sourcePath") and Path(job["sourcePath"]).is_file())
    reasons = {
        "keep": "审核样片不能存入成片库，请先确认并导出高清成片" if preview else "输出文件不可用" if not exists else "",
        "download": "输出文件不可用" if not exists else "",
        "edit": "缺少可编辑时间线" if not output.get("segments") else "源视频不可用" if not source else "",
        "export": "该文件已经是正式成片" if not preview else "缺少可复现的时间线" if not output.get("segments") else "源视频不可用" if not source else "",
    }
    if not reasons["export"]:
        try:
            output_spec(output, version, subtitle_mode="none", subtitle_style="clean")
        except HTTPException as error:
            reasons["export"] = error.detail.get("message", "请重新生成样片") if isinstance(error.detail, dict) else str(error.detail)
    return {
        "canKeep": not bool(reasons["keep"]), "canDownload": not bool(reasons["download"]),
        "canEdit": not bool(reasons["edit"]), "canExport": not bool(reasons["export"]),
        "disabledReason": reasons,
    }
