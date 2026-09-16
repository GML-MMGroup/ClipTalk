from __future__ import annotations

import re
from pathlib import Path
from typing import Any


NAMING_VERSION = 2

_INVALID_FILENAME = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")
_SPACE = re.compile(r"\s+")
_SEPARATOR = re.compile(r"\s*[·|｜]\s*")
_ENGINE_PREFIX = re.compile(r"^(?:AI|LLM|VLM)\s*[·|｜:_-]*\s*", re.IGNORECASE)
_ASPECT_PREFIX = re.compile(r"^(?:16\s*[:x×]\s*9|9\s*[:x×]\s*16|1\s*[:x×]\s*1)\s*", re.IGNORECASE)

_GENERIC_VARIANTS = {
    "", "成片", "内容视频", "高光成片", "正式成片", "审核样片", "审核预览", "agent 审核预览",
}
_GENERIC_SUBJECTS = {"事件高光合集", "内容探索", "内容检索", "视频剪辑", "高光剪辑", "智能高光", "自动剪辑"}
_GENERIC_SUBJECT_MARKERS = (
    "自动分析整个源视频", "先发现真实精彩事件", "综合判断", "关键事件", "完整表达",
)
_PLATFORM_LABELS = {
    "douyin": "抖音", "tiktok": "TikTok", "xiaohongshu": "小红书",
    "bilibili": "哔哩哔哩", "wechat": "视频号", "weixin": "视频号",
    "youtube": "YouTube", "instagram": "Instagram", "generic": "通用",
}


def _display_text(value: Any, maximum: int = 48) -> str:
    text = _SPACE.sub(" ", str(value or "").strip())
    return text[:maximum].rstrip(" ._-·|｜")


def _source_stem(value: Any) -> str:
    return _display_text(Path(str(value or "视频")).stem, 48) or "视频"


def _filename_component(value: Any, fallback: str, maximum: int) -> str:
    text = _INVALID_FILENAME.sub("-", str(value or fallback))
    text = _SEPARATOR.sub("-", text)
    text = _SPACE.sub("_", text).strip(" ._-")
    return text[:maximum].rstrip(" ._-") or fallback


def _meaningful_subject(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) > 48 or raw.startswith(("仅根据对白", "分别检索", "请根据当前视频", "按源视频时间顺序")):
        return ""
    text = _display_text(value, 48)
    if not text or text in _GENERIC_SUBJECTS or any(marker in text for marker in _GENERIC_SUBJECT_MARKERS):
        return ""
    text = re.sub(r"^(?:请|帮我|请帮我)\s*", "", text)
    return text[:24].rstrip("，,。；;：: ._-·|｜")


def _normalized_variant(value: Any, subject: str = "") -> str:
    text = _display_text(value, 40)
    if "安全时间线草案" in text or "时间线草稿" in text:
        return "精剪版"
    text = _ENGINE_PREFIX.sub("", text)
    text = re.sub(r"\s*[·|｜]\s*(?:视觉推荐|剪辑规划|成片审片|高清导出|AI 样片|高清成片)\s*$", "", text)
    text = _ASPECT_PREFIX.sub("", text)
    aliases = {
        "二次精剪成片": "精剪版",
        "竖屏正式成片": "竖屏版",
        "方屏正式成片": "方屏版",
    }
    text = aliases.get(text, text)
    text = re.sub(r"审核预览$", "版", text)
    text = re.sub(r"审核样片$", "版", text)
    if text.endswith("正式成片"):
        text = f"{text[:-4].rstrip()}正式版"
    if subject:
        escaped = re.escape(subject)
        text = re.sub(rf"^{escaped}\s*[·|｜:_-]+\s*", "", text, flags=re.IGNORECASE)
    if text.casefold() in _GENERIC_VARIANTS or text == subject:
        return ""
    return text[:20].rstrip(" ._-·|｜")


def output_aspect_label(output: dict[str, Any]) -> str:
    reframe = output.get("reframe") if isinstance(output.get("reframe"), dict) else {}
    delivery = output.get("delivery") if isinstance(output.get("delivery"), dict) else {}
    explicit = str(reframe.get("aspect") or delivery.get("aspect") or "").strip().lower().replace("×", ":").replace("x", ":")
    if explicit in {"16:9", "9:16", "1:1"}:
        return explicit
    try:
        width, height = float(output.get("width") or 0), float(output.get("height") or 0)
    except (TypeError, ValueError):
        return ""
    if width <= 0 or height <= 0:
        return ""
    ratio = width / height
    for label, target in (("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0)):
        if abs(ratio - target) / target <= .03:
            return label
    return f"{int(round(width))}:{int(round(height))}"


def _named_aspect_label(version: dict[str, Any], output: dict[str, Any]) -> str:
    aspect = output_aspect_label(output)
    if aspect:
        return aspect
    text = " ".join(str(value or "") for value in (
        version.get("displayName"), version.get("sourceLabel"), output.get("displayTitle"), output.get("title"),
    ))
    match = re.search(r"(?<!\d)(16\s*[:x×]\s*9|9\s*[:x×]\s*16|1\s*[:x×]\s*1)(?!\d)", text, re.IGNORECASE)
    return re.sub(r"\s+", "", match.group(1)).lower().replace("x", ":").replace("×", ":") if match else ""


def _parent_version(job: dict[str, Any], version: dict[str, Any]) -> dict[str, Any] | None:
    parent_id = str(version.get("parentVersionId") or version.get("sourceVersionId") or "")
    if not parent_id:
        return None
    return next((
        item for item in job.get("outputVersions") or []
        if isinstance(item, dict) and str(item.get("id") or "") == parent_id
    ), None)


def _parent_name_parts(job: dict[str, Any], version: dict[str, Any]) -> tuple[str, str]:
    parent = _parent_version(job, version)
    if not parent:
        return "", ""
    output = next((item for item in parent.get("outputs") or [] if isinstance(item, dict)), {})
    subject = _meaningful_subject(output.get("nameSubject"))
    variant = _normalized_variant(output.get("nameVariant"), subject)
    if subject:
        return subject, variant
    title = _display_text(output.get("displayTitle") or output.get("title"), 48)
    if " · " in title:
        left, right = title.split(" · ", 1)
        return _meaningful_subject(left), _normalized_variant(right, left)
    return _meaningful_subject(title), ""


def _subject(job: dict[str, Any], version: dict[str, Any], output: dict[str, Any]) -> str:
    if int(output.get("namingVersion") or 0) >= NAMING_VERSION:
        stored = _meaningful_subject(output.get("nameSubject"))
        if stored:
            return stored
    parent_subject, _ = _parent_name_parts(job, version)
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    brief = job.get("brief") if isinstance(job.get("brief"), dict) else {}
    focus = brief.get("focus") if isinstance(brief.get("focus"), list) else []
    candidates = [
        version.get("contentSearchInstruction"),
        output.get("contentSearchInstruction"),
        parent_subject,
        request.get("contentInstruction"),
        request.get("instruction"),
        *focus,
        brief.get("narrativeGoal"),
        brief.get("objective"),
    ]
    for candidate in candidates:
        value = _meaningful_subject(candidate)
        if value:
            return value
    return _source_stem(job.get("filename"))[:24]


def _variant(job: dict[str, Any], version: dict[str, Any], output: dict[str, Any], subject: str) -> str:
    if int(output.get("namingVersion") or 0) >= NAMING_VERSION:
        stored = _normalized_variant(output.get("nameVariant"), subject)
        if stored:
            return stored
    kind = str(version.get("variantKind") or output.get("outputKind") or "")
    parent_subject, parent_variant = _parent_name_parts(job, version)
    if kind in {"formal_export", "social_reframe_export", "social_reframe_final"} and parent_subject:
        return parent_variant
    if kind in {"cover_intro_export", "cover_intro"}:
        return "封面片头版"
    if kind in {"motion_intro_export", "motion_intro_output"}:
        return "动态图文片头版"
    if kind == "delivery_master" or str(output.get("outputKind") or "") == "delivery_master":
        delivery = output.get("delivery") if isinstance(output.get("delivery"), dict) else {}
        platform = str(delivery.get("platform") or "generic").strip().lower()
        return f"{_PLATFORM_LABELS.get(platform, _display_text(platform, 12) or '通用')}交付版"
    for candidate in (version.get("displayName"), output.get("displayName"), output.get("title")):
        value = _normalized_variant(candidate, subject)
        if value:
            return value
    return ""


def build_download_filename(
    *, source_filename: str, display_title: str, version_number: Any = 1,
    aspect: str = "", position: int = 1, output_count: int = 1,
    preview_only: bool = False, extension: str = "mp4",
) -> str:
    source = _source_stem(source_filename)
    file_title = _display_text(display_title, 48) or "成片"
    if file_title == source:
        file_title = "成片"
    elif file_title.startswith(f"{source} · "):
        file_title = file_title[len(source) + 3:]
    try:
        number = max(1, int(version_number or 1))
    except (TypeError, ValueError):
        number = 1
    parts = [
        _filename_component(source, "视频", 24),
        _filename_component(file_title, "成片", 32),
        f"V{number}",
    ]
    if aspect:
        parts.append(str(aspect).replace(":", "x").replace("×", "x"))
    if output_count > 1:
        parts.append(f"{max(1, int(position or 1)):02d}")
    if preview_only:
        parts.append("审核样片")
    suffix = str(extension or "mp4").lower().lstrip(".") or "mp4"
    return f"{'_'.join(parts)}.{suffix}"


def build_output_naming(
    job: dict[str, Any], version: dict[str, Any], output: dict[str, Any],
    *, position: int = 1, output_count: int = 1, extension: str = "mp4",
) -> dict[str, Any]:
    subject = _subject(job, version, output)
    variant = _variant(job, version, output, subject)
    display_title = f"{subject} · {variant}" if subject and variant else subject or variant or "成片"
    display_title = _display_text(display_title, 48) or "成片"
    aspect = _named_aspect_label(version, output)
    preview_only = bool(output.get("previewOnly") or version.get("previewOnly"))
    return {
        "namingVersion": NAMING_VERSION,
        "nameSubject": subject,
        "nameVariant": variant,
        "displayTitle": display_title,
        "aspectLabel": aspect,
        "downloadFilename": build_download_filename(
            source_filename=str(job.get("filename") or "视频"),
            display_title=display_title,
            version_number=version.get("number") or output.get("versionNumber") or 1,
            aspect=aspect,
            position=position,
            output_count=output_count,
            preview_only=preview_only,
            extension=extension,
        ),
    }


def apply_output_naming(job: dict[str, Any]) -> None:
    versions = [item for item in job.get("outputVersions") or [] if isinstance(item, dict)]
    for version in sorted(versions, key=lambda item: int(item.get("number") or 0)):
        outputs = [item for item in version.get("outputs") or [] if isinstance(item, dict)]
        for position, output in enumerate(outputs, 1):
            output.update(build_output_naming(job, version, output, position=position, output_count=len(outputs)))
        previews = [item for item in version.get("previewOutputs") or [] if isinstance(item, dict)]
        for position, output in enumerate(previews, 1):
            output.update(build_output_naming(
                job, {**version, "previewOnly": True}, output,
                position=position, output_count=len(previews),
            ))
    active_id = str(job.get("currentOutputVersionId") or "")
    active = next((item for item in versions if str(item.get("id") or "") == active_id), None)
    if active:
        job["outputs"] = active.get("outputs") or []
