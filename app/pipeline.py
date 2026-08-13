from __future__ import annotations

import json
import math
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .edit_boundaries import annotate_candidate_boundaries
from .ark_client import VisionModelClient
from .event_groups import allocate_event_group_budget, build_event_groups, event_groups_total, split_event_groups_at_scene_cuts
from .media import (
    SampledFrame,
    VideoInfo,
    create_contact_sheet,
    create_director_contact_sheet,
    detect_silence_intervals,
    detect_scene_changes_in_ranges,
    extract_audio_waveform,
    extract_frames_at_times,
    extract_uniform_frames,
    silence_intervals_from_waveform,
    probe_video,
    render_clip,
    validate_rendered_clip,
)
from .prompts import (
    COMMON_SYSTEM_PROMPT,
    PROMPT_VERSION,
    boundary_refinement_prompt,
    coarse_discovery_prompt,
    content_classification_prompt,
    event_director_prompt,
    generic_content_profile,
)
from .speech import analyze_speech, speech_evidence, transcript_context


ProgressCallback = Callable[[float, str, str], None]
ANALYSIS_CACHE_VERSION = f"visual-highlights-v12-sentence-units-{PROMPT_VERSION}"


class ModelDecisionRequired(RuntimeError):
    def __init__(self, stage: str, message: str, attempts: int) -> None:
        super().__init__(message)
        self.stage = stage
        self.attempts = attempts


def checkpoint_path(work_directory: Path) -> Path:
    return work_directory / "analysis-checkpoint.json"


def write_analysis_checkpoint(work_directory: Path, payload: dict[str, Any]) -> None:
    path = checkpoint_path(work_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        **payload,
        "schemaVersion": 1,
        "promptVersion": PROMPT_VERSION,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_analysis_checkpoint(work_directory: Path) -> dict[str, Any] | None:
    path = checkpoint_path(work_directory)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if value.get("schemaVersion") != 1 or value.get("promptVersion") != PROMPT_VERSION:
        return None
    return value


@dataclass(frozen=True)
class HighlightCandidate:
    start: float
    end: float
    score: float
    title: str
    reason: str
    evidence: list[str]
    visual_signature: str = ""
    role: str = ""
    possible_event: str = ""
    audio_evidence: dict[str, Any] = field(default_factory=dict)
    peak_start: float = 0.0
    peak_end: float = 0.0
    minimum_keep_seconds: float = 0.0
    boundary_confidence: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def coarse_frame_limit(video_duration: float) -> int:
    """Adaptive full-video sampling cap used to bound VLM page requests."""
    return max(48, min(72, math.ceil(max(0.0, float(video_duration)) / 6.0)))


def refinement_candidate_limit(
    *, discovery_only: bool, total_target_seconds: float | None, target_seconds: float, count: int,
) -> int:
    if discovery_only:
        duration_hint = float(total_target_seconds or max(30.0, target_seconds * max(1, count)))
        return max(5, min(8, math.ceil(duration_hint / 12.0) + 2))
    return max(count, min(8, count * 2))


def normalize_content_profile(raw: Any, theme: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return generic_content_profile(theme)
    weights = raw.get("evidence_weights") or raw.get("evidenceWeights") or {}
    visual = max(0.0, _number(weights.get("visual"), .7))
    speech = max(0.0, _number(weights.get("speech"), .2))
    audio = max(0.0, _number(weights.get("audio"), .1))
    total = visual + speech + audio or 1.0
    definitions = raw.get("highlight_definition") or raw.get("highlightDefinition") or []
    downrank = raw.get("downrank_conditions") or raw.get("downrankConditions") or []
    return {
        "primaryType": str(raw.get("primary_type") or raw.get("primaryType") or "综合视频")[:50],
        "secondaryTypes": [str(item)[:50] for item in (raw.get("secondary_types") or raw.get("secondaryTypes") or []) if str(item).strip()][:2],
        "narrativeMode": str(raw.get("narrative_mode") or raw.get("narrativeMode") or "综合信号")[:50],
        "highlightDefinition": [str(item)[:240] for item in definitions if str(item).strip()][:8]
        or generic_content_profile(theme)["highlightDefinition"],
        "downrankConditions": [str(item)[:240] for item in downrank if str(item).strip()][:8],
        "evidenceWeights": {
            "visual": round(visual / total, 3),
            "speech": round(speech / total, 3),
            "audio": round(audio / total, 3),
        },
        "reason": str(raw.get("reason") or "视觉模型根据全片总览判断")[:500],
        "fallback": False,
    }


def candidate_evidence(raw: Any, fallback: list[str]) -> list[str]:
    if isinstance(raw, dict):
        raw = [raw.get("start"), raw.get("peak"), raw.get("end")]
    cleaned = clean_model_evidence(raw)
    return cleaned or fallback


def validated_model_time(value: Any, allowed_times: list[float], *, tolerance: float) -> float | None:
    """Accept a model time only when a displayed frame can support it."""
    second = _number(value, -1.0)
    if second < 0 or not allowed_times:
        return None
    nearest = min(allowed_times, key=lambda item: abs(item - second))
    return round(nearest, 3) if abs(nearest - second) <= max(.25, tolerance) else None


def safe_output_filename(title: str, position: int) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", title).strip(" .-")
    cleaned = re.sub(r"\s+", "_", cleaned)[:60] or "highlight"
    return f"{position:02d}-{cleaned}.mp4"


def clean_model_evidence(items: Any) -> list[str]:
    cleaned: list[str] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, str):
            continue
        # Model-readable contact-sheet labels are evidence selectors, not a
        # trustworthy clock. The verified start/end values are shown separately.
        value = re.sub(r"(?:T\s*=\s*)?\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?", "对应画面", item)
        value = re.sub(r"\b\d{1,2}\.\d{2}(?:\s*[-–至]\s*\d{1,2}\.\d{2})?\s*秒", "对应画面", value)
        value = re.sub(r"\s+", " ", value).strip(" ，,；;")
        if value and value not in cleaned:
            cleaned.append(value[:300])
    return cleaned[:8]


def _exclusion_instruction(ranges: list[tuple[float, float]]) -> str:
    if not ranges:
        return ""
    formatted = "、".join(f"{start:.2f}–{end:.2f} 秒" for start, end in ranges)
    return f"\n禁止选择这些已经使用过的时间区间，也不要让新候选与其发生任何重叠：{formatted}。"


def _candidate_from_coarse(
    raw: Any,
    *,
    duration: float,
    target_seconds: float,
    automatic_duration: bool = False,
) -> HighlightCandidate | None:
    if not isinstance(raw, dict):
        return None
    center = _number(raw.get("center_seconds"), -1)
    if center < 0 or center > duration:
        return None
    suggested_limit = 30.0 if automatic_duration else target_seconds * 1.5
    suggested_default = 10.0 if automatic_duration else target_seconds
    suggested = max(4.0, min(suggested_limit, _number(raw.get("suggested_duration"), suggested_default)))
    start = max(0.0, center - suggested / 2)
    end = min(duration, start + suggested)
    start = max(0.0, end - suggested)
    return HighlightCandidate(
        start=start,
        end=end,
        score=max(0.0, min(100.0, _number(raw.get("score"), 50))),
        title=str(raw.get("title") or "视觉高光")[:80],
        reason=str(raw.get("reason") or "视觉模型候选")[:600],
        evidence=clean_model_evidence(raw.get("evidence", [])),
        role=str(raw.get("moment_role") or raw.get("role") or "")[:40],
        possible_event=str(raw.get("possible_event") or raw.get("possibleEvent") or "")[:80],
        audio_evidence={},
        peak_start=round(max(start, center - min(2.0, suggested * .2)), 3),
        peak_end=round(min(end, center + min(2.0, suggested * .2)), 3),
        minimum_keep_seconds=round(min(suggested, max(2.0, suggested * .35)), 3),
        boundary_confidence=.45,
    )


def _refined_candidate(
    raw: dict[str, Any],
    fallback: HighlightCandidate,
    *,
    duration: float,
    target_seconds: float,
    automatic_duration: bool = False,
    allowed_times: list[float] | None = None,
) -> HighlightCandidate:
    start = max(0.0, min(duration, _number(raw.get("start_seconds"), fallback.start)))
    end = max(start, min(duration, _number(raw.get("end_seconds"), fallback.end)))
    if allowed_times:
        ordered_times = sorted(set(allowed_times))
        step = max((right - left for left, right in zip(ordered_times, ordered_times[1:])), default=1.0)
        # Boundary sheets represent intervals between sampled frames. Accept a
        # model boundary up to one sampling step from the nearest visible
        # frame, especially at the physical end of a video where FFmpeg may
        # not decode the final requested timestamp.
        start = validated_model_time(raw.get("start_seconds"), ordered_times, tolerance=step * 1.1)
        end = validated_model_time(raw.get("end_seconds"), ordered_times, tolerance=step * 1.1)
        start = start if start is not None else min(ordered_times, key=lambda item: abs(item - fallback.start))
        end = end if end is not None else min(ordered_times, key=lambda item: abs(item - fallback.end))
    # Respect the candidate's semantic core instead of imposing a universal
    # four-second floor. Short actions and reactions are valid physical shots;
    # spoken candidates already carry a longer minimum keep duration.
    minimum = min(duration, max(.8, fallback.minimum_keep_seconds or .8))
    # Frame sampling quantises model boundaries. A nominal four-second range
    # can become 3.95s after snapping; that is still valid and must not be
    # replaced by the broad coarse fallback range.
    if end - start < minimum - .15:
        center = (fallback.start + fallback.end) / 2
        fallback_duration = max(4.0, min(30.0, fallback.duration)) if automatic_duration else target_seconds
        start = max(0.0, center - fallback_duration / 2)
        end = min(duration, start + fallback_duration)
    maximum = min(duration, 30.0 if automatic_duration else max(6.0, target_seconds * 1.5))
    if end - start > maximum:
        center = (start + end) / 2
        start = max(0.0, center - maximum / 2)
        end = min(duration, start + maximum)
    if allowed_times:
        ordered_times = sorted(set(allowed_times))
        start = min(ordered_times, key=lambda item: abs(item - start))
        end = min(ordered_times, key=lambda item: abs(item - end))
        if end <= start:
            later = [item for item in ordered_times if item > start]
            end = later[0] if later else min(duration, start + minimum)
    candidate_duration = max(.2, end - start)
    default_peak_start = start + candidate_duration * .35
    default_peak_end = start + candidate_duration * .65
    peak_start = max(start, min(end, _number(raw.get("peak_start_seconds"), default_peak_start)))
    peak_end = max(peak_start, min(end, _number(raw.get("peak_end_seconds"), default_peak_end)))
    if allowed_times:
        ordered_times = sorted(set(allowed_times))
        step = max((right - left for left, right in zip(ordered_times, ordered_times[1:])), default=1.0)
        verified_peak_start = validated_model_time(raw.get("peak_start_seconds"), ordered_times, tolerance=step * .8)
        verified_peak_end = validated_model_time(raw.get("peak_end_seconds"), ordered_times, tolerance=step * .8)
        peak_start = verified_peak_start if verified_peak_start is not None else min(ordered_times, key=lambda item: abs(item - peak_start))
        peak_end = verified_peak_end if verified_peak_end is not None else min(ordered_times, key=lambda item: abs(item - peak_end))
        peak_start = max(start, min(end, peak_start))
        peak_end = max(peak_start, min(end, peak_end))
    if peak_end <= peak_start:
        peak_start = max(start, min(end, default_peak_start))
        peak_end = max(peak_start, min(end, default_peak_end))
    minimum_keep = _number(raw.get("minimum_keep_seconds"), max(2.0, candidate_duration * .35))
    minimum_keep = min(candidate_duration, max(.8, peak_end - peak_start, minimum_keep))
    boundary_confidence = max(0.0, min(1.0, _number(raw.get("boundary_confidence"), .7)))
    return HighlightCandidate(
        start=round(start, 3),
        end=round(end, 3),
        score=max(0.0, min(100.0, _number(raw.get("score"), fallback.score))),
        title=str(raw.get("title") or fallback.title)[:80],
        reason=str(raw.get("reason") or fallback.reason)[:600],
        evidence=candidate_evidence(raw.get("evidence"), fallback.evidence),
        visual_signature=fallback.visual_signature,
        role=str(raw.get("role") or fallback.role)[:40],
        possible_event=fallback.possible_event,
        audio_evidence=fallback.audio_evidence,
        peak_start=round(peak_start, 3),
        peak_end=round(peak_end, 3),
        minimum_keep_seconds=round(minimum_keep, 3),
        boundary_confidence=round(boundary_confidence, 3),
    )


def _character_bigrams(value: str) -> set[str]:
    normalized = "".join(character.lower() for character in value if character.isalnum())
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index:index + 2] for index in range(len(normalized) - 1)}


def candidate_text_similarity(left: HighlightCandidate, right: HighlightCandidate) -> float:
    generic_titles = {"视觉高光", "高光片段", "精彩片段", "候选片段"}
    if left.title.strip() in generic_titles or right.title.strip() in generic_titles:
        return 0.0
    left_tokens = _character_bigrams(left.title)
    right_tokens = _character_bigrams(right.title)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def speech_signal_candidates(
    segments: list[dict[str, Any]], *, video_duration: float, maximum: int = 4,
) -> list[HighlightCandidate]:
    """Promote strong audio/dialogue evidence into visually verified candidates."""
    candidates: list[HighlightCandidate] = []
    for item in segments:
        start = max(0.0, _number(item.get("start"), 0.0))
        end = min(video_duration, max(start, _number(item.get("end"), start)))
        text = str(item.get("text") or "").strip()
        duration = end - start
        if duration < .8 or duration > 45 or not text:
            continue
        emotion = str(item.get("emotion") or "neutral").lower()
        events = [str(value) for value in item.get("audioEvents") or []]
        score = 74.0 + min(10.0, len(text) / 14.0)
        if emotion not in {"", "neutral", "unknown"}:
            score += 8.0
        if any(value in {"applause", "laughter", "cry", "cough"} for value in events):
            score += 7.0
        if len(text) < 8 and not events and emotion in {"", "neutral", "unknown"}:
            continue
        evidence = [f"语音内容：{text[:120]}"]
        if emotion not in {"", "neutral", "unknown"}:
            evidence.append(f"情绪信号：{emotion}")
        if events:
            evidence.append("声音事件：" + "、".join(events[:4]))
        candidates.append(HighlightCandidate(
            start=round(start, 3), end=round(end, 3), score=min(96.0, score),
            title=(text[:28] + "…") if len(text) > 28 else text,
            reason="由完整对白、情绪或声音事件触发，仍需视觉模型验证画面价值。",
            evidence=evidence, role="对白/声音高光", possible_event="视听高光",
            audio_evidence={
                "transcriptExcerpt": text[:500], "emotion": emotion,
                "audioEvents": events, "source": "sensevoice",
            },
            peak_start=round(start, 3), peak_end=round(end, 3),
            minimum_keep_seconds=round(duration, 3), boundary_confidence=.9,
        ))
    ranked = sorted(candidates, key=lambda item: (-item.score, item.start))
    selected: list[HighlightCandidate] = []
    for candidate in ranked:
        if any(max(candidate.start, item.start) < min(candidate.end, item.end) for item in selected):
            continue
        selected.append(candidate)
        if len(selected) >= max(1, maximum):
            break
    return selected


def image_average_hash(path: Path) -> str:
    with Image.open(path) as image:
        pixels = list(image.convert("L").resize((8, 8), Image.Resampling.LANCZOS).getdata())
    average = sum(pixels) / len(pixels)
    return "".join("1" if value >= average else "0" for value in pixels)


def candidate_visual_similarity(left: HighlightCandidate, right: HighlightCandidate) -> float:
    if len(left.visual_signature) != 64 or len(right.visual_signature) != 64:
        return 0.0
    distance = sum(a != b for a, b in zip(left.visual_signature, right.visual_signature))
    return 1.0 - distance / 64.0


def select_non_overlapping(candidates: list[HighlightCandidate], count: int) -> list[HighlightCandidate]:
    selected: list[HighlightCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (-item.score, item.start)):
        overlap = any(max(candidate.start, other.start) < min(candidate.end, other.end) for other in selected)
        too_close = any(
            0 <= max(candidate.start, other.start) - min(candidate.end, other.end) < 1.0
            for other in selected
        )
        semantic_duplicate = any(
            candidate_text_similarity(candidate, other) >= 0.58
            or candidate_visual_similarity(candidate, other) >= 0.93
            for other in selected
        )
        if overlap or too_close or semantic_duplicate:
            continue
        selected.append(candidate)
        if len(selected) >= count:
            break
    return sorted(selected, key=lambda item: item.start)


def select_montage_moments(candidates: list[HighlightCandidate], count: int) -> list[HighlightCandidate]:
    """Keep multiple complementary shots from one event while removing temporal/visual duplicates."""
    selected: list[HighlightCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (-item.score, item.start)):
        # Frame timestamps are quantised, so two adjacent shots can overlap by
        # a few milliseconds after snapping. Treat that as a shared cut point,
        # not as a duplicate moment.
        if any(
            min(candidate.end, other.end) - max(candidate.start, other.start) > .12
            for other in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= count:
            break
    return sorted(selected, key=lambda item: item.start)


def overlaps_ranges(candidate: HighlightCandidate, ranges: list[tuple[float, float]]) -> bool:
    return any(max(candidate.start, start) < min(candidate.end, end) for start, end in ranges)


def audio_hotspot_context(waveform: dict[str, Any], duration: float) -> str:
    rms = [float(value) for value in waveform.get("rms", [])]
    if not rms:
        return ""
    ranked = sorted(range(len(rms)), key=lambda index: rms[index], reverse=True)
    selected: list[float] = []
    for index in ranked:
        second = index / max(1, len(rms) - 1) * duration
        if all(abs(second - existing) >= 6.0 for existing in selected):
            selected.append(second)
        if len(selected) >= 10:
            break
    values = "、".join(f"{value:.1f}s" for value in sorted(selected))
    return f"\n本地音频能量分析发现这些时间附近存在明显声音变化，可作为辅助证据但不能代替画面判断：{values}。"


def candidate_audio_energy(candidate: HighlightCandidate, waveform: dict[str, Any], duration: float) -> float:
    rms = [float(value) for value in waveform.get("rms", [])]
    if not rms or duration <= 0:
        return 0.0
    start = max(0, min(len(rms) - 1, int(candidate.start / duration * len(rms))))
    end = max(start + 1, min(len(rms), math.ceil(candidate.end / duration * len(rms))))
    region = rms[start:end]
    peak = max(region, default=0.0)
    sorted_all = sorted(rms)
    reference = sorted_all[min(len(sorted_all) - 1, int(len(sorted_all) * .9))] or 1.0
    return max(0.0, min(1.0, peak / reference))


def recommended_candidate_indices(candidates: list[dict[str, Any]], *, maximum: int = 5) -> list[int]:
    if not candidates:
        return []
    top_score = max(float(item["score"]) for item in candidates)
    # Scores from separate model calls are not perfectly calibrated. Recommend
    # candidates close to the best result instead of treating 85 as universal.
    threshold = max(78.0, top_score - 8.0)
    ranked = sorted(candidates, key=lambda item: (-float(item["score"]), int(item["index"])))
    selected = [int(item["index"]) for item in ranked if float(item["score"]) >= threshold][:maximum]
    return selected or [int(ranked[0]["index"])]


def refinement_window_seconds(
    candidate: HighlightCandidate,
    *,
    video_duration: float,
    target_seconds: float,
    automatic_duration: bool,
) -> float:
    if automatic_duration:
        # Context must be wider than the clip itself so the model can see both
        # natural event boundaries. This intentionally does not use the old
        # 20-second automatic placeholder.
        return min(video_duration, max(30.0, min(90.0, candidate.duration * 1.75)))
    return min(video_duration, max(target_seconds * 1.6, 12.0))


def touches_refinement_boundary(
    candidate: HighlightCandidate,
    *,
    window_start: float,
    window_end: float,
    sample_step: float,
    video_duration: float,
) -> bool:
    tolerance = max(0.75, sample_step * 1.15)
    touches_left = window_start > 0.05 and candidate.start <= window_start + tolerance
    touches_right = window_end < video_duration - 0.05 and candidate.end >= window_end - tolerance
    return touches_left or touches_right


class HighlightPipeline:
    def __init__(self, *, client: VisionModelClient, ffmpeg: str, ffprobe: str, selection_backend: str = "openai-compatible-vlm") -> None:
        self.client = client
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.selection_backend = selection_backend

    def _analyze_with_heartbeat(
        self,
        *,
        prompt_text: str,
        image_path: Path,
        progress_value: float,
        stage: str,
        detail: str,
        progress: ProgressCallback,
        maximum_tokens: int,
        system_prompt: str = COMMON_SYSTEM_PROMPT,
    ) -> dict[str, Any]:
        stopped = threading.Event()
        started = time.monotonic()

        def heartbeat() -> None:
            while not stopped.wait(5):
                elapsed = int(time.monotonic() - started)
                visible_detail = f"{detail}（模型响应较慢，仍在处理中）" if elapsed >= 60 else detail
                progress(progress_value, stage, visible_detail)

        thread = threading.Thread(target=heartbeat, name="ark-progress-heartbeat", daemon=True)
        thread.start()
        try:
            try:
                return self.client.analyze_image(
                    prompt_text, image_path, maximum_tokens=maximum_tokens, system_prompt=system_prompt,
                )
            except TypeError as error:
                if "system_prompt" not in str(error):
                    raise
                return self.client.analyze_image(prompt_text, image_path, maximum_tokens=maximum_tokens)
        finally:
            stopped.set()

    def _complete_with_heartbeat(
        self,
        *,
        prompt_text: str,
        progress_value: float,
        stage: str,
        detail: str,
        progress: ProgressCallback,
        maximum_tokens: int,
        system_prompt: str = COMMON_SYSTEM_PROMPT,
    ) -> dict[str, Any]:
        stopped = threading.Event()
        started = time.monotonic()

        def heartbeat() -> None:
            while not stopped.wait(5):
                elapsed = int(time.monotonic() - started)
                visible_detail = f"{detail}（模型响应较慢，仍在处理中）" if elapsed >= 60 else detail
                progress(progress_value, stage, visible_detail)

        thread = threading.Thread(target=heartbeat, name="ark-event-heartbeat", daemon=True)
        thread.start()
        try:
            try:
                return self.client.complete_json(
                    prompt_text, maximum_tokens=maximum_tokens, system_prompt=system_prompt,
                )
            except TypeError as error:
                if "system_prompt" not in str(error):
                    raise
                return self.client.complete_json(prompt_text, maximum_tokens=maximum_tokens)
        finally:
            stopped.set()

    def _request_content_profile(
        self,
        *,
        overview_sheet: Path,
        video_duration: float,
        theme: str,
        analysis_mode: str,
        progress: ProgressCallback,
    ) -> dict[str, Any]:
        progress(.12, "content_classification", "视觉大模型正在识别视频类型与高光标准")
        return self._analyze_with_heartbeat(
            prompt_text=content_classification_prompt(
                video_duration=video_duration, theme=theme, analysis_mode=analysis_mode,
            ),
            image_path=overview_sheet,
            progress_value=.12,
            stage="content_classification",
            detail="视觉大模型正在识别视频类型与高光标准",
            progress=progress,
            maximum_tokens=1000,
        )

    def _request_event_director(
        self,
        *,
        director_sheet: Path,
        candidates: list[dict[str, Any]],
        content_profile: dict[str, Any],
        theme: str,
        requested_count: int | None,
        total_target_seconds: float | None,
        transcript_available: bool,
        progress: ProgressCallback,
    ) -> dict[str, Any]:
        progress(.84, "event_grouping", f"正在把 {len(candidates)} 个精彩镜头整理为高光事件")
        return self._analyze_with_heartbeat(
            prompt_text=event_director_prompt(
                moments=candidates,
                content_profile=content_profile,
                theme=theme,
                requested_count=requested_count,
                total_target_seconds=total_target_seconds,
                transcript_available=transcript_available,
            ),
            image_path=director_sheet,
            progress_value=.84,
            stage="event_grouping",
            detail="视觉大模型正在查看候选起点、高潮与终点并编排事件",
            progress=progress,
            maximum_tokens=3000,
        )

    def _finish_event_manifest(
        self,
        *,
        source: Path,
        info: dict[str, Any],
        candidates: list[dict[str, Any]],
        grouping: dict[str, Any],
        content_profile: dict[str, Any],
        total_target_seconds: float | None,
        requested_count: int | None,
        theme: str,
        analysis_mode: str,
        transcript_available: bool,
        speech_segments: list[dict[str, Any]],
        silence_intervals: list[dict[str, Any]],
        scene_cuts: list[float],
        speech_error: str,
        speech_analysis: dict[str, Any],
        exclusions: list[tuple[float, float]],
        usage: list[dict[str, Any]],
        progress: ProgressCallback,
        degraded: bool = False,
    ) -> dict[str, Any]:
        candidates = annotate_candidate_boundaries(
            candidates,
            speech_segments=speech_segments,
            silences=silence_intervals,
            duration=float(info.get("duration") or 0) or None,
        )
        if not scene_cuts:
            scene_cuts = detect_scene_changes_in_ranges(
                source,
                [(float(candidate.get("start") or 0), float(candidate.get("end") or 0)) for candidate in candidates],
                ffmpeg=self.ffmpeg,
            )
        event_groups = build_event_groups(candidates, grouping)
        event_groups = split_event_groups_at_scene_cuts(event_groups, scene_cuts)
        event_groups, recommended_group_ids = allocate_event_group_budget(
            event_groups,
            total_target_seconds=total_target_seconds,
            requested_count=requested_count,
        )
        allocated_total = event_groups_total(event_groups, recommended_group_ids)
        tolerance = max(4.0, float(total_target_seconds or allocated_total) * .1)
        duration_status = (
            "on_target" if total_target_seconds is None or abs(allocated_total - total_target_seconds) <= tolerance
            else ("under_target" if allocated_total < total_target_seconds else "over_target")
        )
        progress(1.0, "awaiting_confirmation", f"VLM 精修保留 {len(candidates)} 个候选镜头，已归并为 {len(event_groups)} 个精彩事件")
        return {
            "schemaVersion": 4,
            "promptVersion": PROMPT_VERSION,
            "source": source.name,
            "video": info,
            "candidateCount": len(candidates),
            "candidates": candidates,
            "eventGroupCount": len(event_groups),
            "eventGroups": event_groups,
            "recommendedGroupIds": recommended_group_ids,
            "recommendedCount": len(recommended_group_ids),
            "totalTargetSeconds": total_target_seconds,
            "allocatedTotalSeconds": allocated_total,
            "durationStatus": duration_status,
            "durationGap": round(total_target_seconds - allocated_total, 3) if total_target_seconds is not None else 0.0,
            "durationTolerance": .1,
            "durationUpperLimit": round(
                float(total_target_seconds) + max(5.0, float(total_target_seconds) * .15), 3,
            ) if total_target_seconds is not None else None,
            "eventReductionReason": next((
                str(group.get("eventReductionReason"))
                for group in event_groups
                if group.get("id") in recommended_group_ids and group.get("eventReductionReason")
            ), ""),
            "theme": theme,
            "selectionBackend": self.selection_backend,
            "analysisMode": analysis_mode,
            "contentProfile": content_profile,
            "transcriptAvailable": transcript_available,
            "speechRecognitionError": speech_error or None,
            "speechAnalysis": speech_analysis,
            "excludedRanges": [{"start": start, "end": end} for start, end in exclusions],
            "usage": usage,
            "directorDegraded": degraded,
        }

    def run(
        self,
        *,
        source: Path,
        work_directory: Path,
        output_directory: Path,
        count: int,
        target_seconds: float,
        theme: str,
        progress: ProgressCallback,
        cancelled: Callable[[], bool],
        excluded_ranges: list[tuple[float, float]] | None = None,
        automatic_duration: bool = False,
        discovery_only: bool = False,
        analysis_mode: str = "visual",
        whisper_model: str = "",
        whisper_device: str = "auto",
        speech_engine: str = "sensevoice",
        sensevoice_model: str = "iic/SenseVoiceSmall",
        sensevoice_device: str = "auto",
        sensevoice_vad_model: str = "fsmn-vad",
        sensevoice_punc_model: str = "",
        sensevoice_spk_model: str = "cam++",
        sensevoice_diarization: bool = True,
        speech_model_cache: Path | None = None,
        total_target_seconds: float | None = None,
        requested_count: int | None = None,
        resume_action: str | None = None,
        scene_cuts: list[float] | None = None,
    ) -> dict[str, Any]:
        exclusions = [
            (max(0.0, float(start)), max(0.0, float(end)))
            for start, end in (excluded_ranges or [])
            if float(end) > float(start)
        ]
        checkpoint = load_analysis_checkpoint(work_directory) if resume_action else None
        if resume_action and not checkpoint:
            raise RuntimeError("分析检查点不存在或版本不兼容，请重新创建任务")

        if checkpoint and checkpoint.get("decisionStage") == "event_director":
            candidates = list(checkpoint.get("candidates") or [])
            if not candidates:
                raise RuntimeError("事件导演检查点缺少精修候选")
            content_profile = dict(checkpoint.get("contentProfile") or generic_content_profile(theme))
            usage = list(checkpoint.get("usage") or [])
            if resume_action == "fallback":
                grouping: dict[str, Any] = {"event_groups": []}
                degraded = True
            elif resume_action == "retry":
                try:
                    grouping = self._request_event_director(
                        director_sheet=Path(checkpoint["directorSheet"]),
                        candidates=candidates,
                        content_profile=content_profile,
                        theme=theme,
                        requested_count=requested_count,
                        total_target_seconds=total_target_seconds,
                        transcript_available=bool(checkpoint.get("transcriptAvailable")),
                        progress=progress,
                    )
                    usage.append(grouping.pop("_usage", {}))
                    degraded = False
                except Exception as error:
                    attempts = int(checkpoint.get("decisionAttempts") or 1) + 1
                    write_analysis_checkpoint(work_directory, {
                        **checkpoint, "decisionRequired": True, "decisionStage": "event_director",
                        "decisionError": str(error)[:800], "decisionAttempts": attempts,
                    })
                    raise ModelDecisionRequired("event_director", str(error), attempts) from error
            else:
                raise RuntimeError("不支持的分析恢复操作")
            manifest = self._finish_event_manifest(
                source=source,
                info=dict(checkpoint["video"]),
                candidates=candidates,
                grouping=grouping,
                content_profile=content_profile,
                total_target_seconds=total_target_seconds,
                requested_count=requested_count,
                theme=theme,
                analysis_mode=analysis_mode,
                transcript_available=bool(checkpoint.get("transcriptAvailable")),
                speech_segments=list(checkpoint.get("speechSegments") or []),
                silence_intervals=list((checkpoint.get("audioWaveform") or {}).get("silences") or []),
                scene_cuts=list(checkpoint.get("sceneCuts") or scene_cuts or []),
                speech_error=str(checkpoint.get("speechRecognitionError") or ""),
                speech_analysis=dict(checkpoint.get("speechAnalysis") or {}),
                exclusions=exclusions,
                usage=usage,
                progress=progress,
                degraded=degraded,
            )
            write_analysis_checkpoint(work_directory, {**checkpoint, "phase": "completed", "decisionRequired": False})
            return manifest

        speech_resumed = bool(checkpoint and checkpoint.get("decisionStage") == "speech_analysis")
        if speech_resumed:
            info = VideoInfo(**dict(checkpoint["video"]))
            audio_waveform = dict(checkpoint.get("audioWaveform") or {})
            audio_context = str(checkpoint.get("audioContext") or "")
            speech_error = ""
            usage = list(checkpoint.get("usage") or [])
            if resume_action == "fallback":
                speech_segments = []
                speech_error = str(checkpoint.get("decisionError") or "SenseVoice 不可用")[:300]
                speech_analysis = {
                    "engine": speech_engine, "status": "degraded", "degraded": True,
                    "error": speech_error, "segments": 0,
                }
            elif resume_action == "retry":
                try:
                    speech_analysis = analyze_speech(
                        source, work_directory / "transcript.json", engine=speech_engine,
                        model_name=sensevoice_model if speech_engine == "sensevoice" else whisper_model,
                        device=sensevoice_device if speech_engine == "sensevoice" else whisper_device,
                        vad_model=sensevoice_vad_model, punc_model=sensevoice_punc_model,
                        spk_model=sensevoice_spk_model, diarization=sensevoice_diarization,
                        model_cache=speech_model_cache, whisper_model=whisper_model,
                        whisper_device=whisper_device, cancelled=cancelled,
                    )
                    speech_segments = list(speech_analysis.get("segments") or [])
                    speech_analysis = {**speech_analysis, "status": "ready", "segments": len(speech_segments)}
                except Exception as error:
                    attempts = int(checkpoint.get("decisionAttempts") or 1) + 1
                    write_analysis_checkpoint(work_directory, {
                        **checkpoint, "decisionRequired": True, "decisionStage": "speech_analysis",
                        "decisionError": str(error)[:800], "decisionAttempts": attempts,
                    })
                    raise ModelDecisionRequired("speech_analysis", str(error), attempts) from error
            else:
                raise RuntimeError("不支持的分析恢复操作")

        if checkpoint and checkpoint.get("decisionStage") == "content_classification":
            info_data = dict(checkpoint["video"])
            info = VideoInfo(**info_data)
            frames = [SampledFrame(path=Path(item["path"]), time=float(item["time"])) for item in checkpoint.get("frames", [])]
            audio_context = str(checkpoint.get("audioContext") or "")
            audio_waveform = dict(checkpoint.get("audioWaveform") or {})
            speech_segments = list(checkpoint.get("speechSegments") or [])
            speech_error = str(checkpoint.get("speechRecognitionError") or "")
            speech_analysis = dict(checkpoint.get("speechAnalysis") or {})
            usage = list(checkpoint.get("usage") or [])
            if resume_action == "fallback":
                content_profile = generic_content_profile(theme)
            elif resume_action == "retry":
                try:
                    classified = self._request_content_profile(
                        overview_sheet=Path(checkpoint["overviewSheet"]),
                        video_duration=float(info.duration), theme=theme,
                        analysis_mode=analysis_mode, progress=progress,
                    )
                    usage.append(classified.pop("_usage", {}))
                    content_profile = normalize_content_profile(classified, theme)
                except Exception as error:
                    attempts = int(checkpoint.get("decisionAttempts") or 1) + 1
                    write_analysis_checkpoint(work_directory, {
                        **checkpoint, "decisionRequired": True, "decisionStage": "content_classification",
                        "decisionError": str(error)[:800], "decisionAttempts": attempts,
                    })
                    raise ModelDecisionRequired("content_classification", str(error), attempts) from error
            else:
                raise RuntimeError("不支持的分析恢复操作")
        else:
            if not speech_resumed:
                speech_analysis: dict[str, Any] = {
                    "engine": speech_engine, "status": "not_run", "segments": 0,
                }
                progress(0.02, "probing", "正在读取视频信息")
                info = probe_video(source, self.ffprobe)
                if cancelled():
                    raise RuntimeError("任务已取消")
                audio_waveform: dict[str, Any] = {}
                if analysis_mode == "audiovisual" and info.has_audio:
                    progress(0.05, "audio_analysis", "正在分析声音能量与停顿")
                    waveform_bins = max(4000, min(60000, math.ceil(info.duration * 12)))
                    def report_waveform_progress(fraction: float, processed: float, total: float) -> None:
                        progress(
                            0.04 + 0.02 * min(.995, max(0.0, fraction)),
                            "audio_analysis",
                            f"音频波形已处理 {round(processed)}/{round(total)} 秒",
                        )
                    audio_waveform = extract_audio_waveform(
                        source, ffmpeg=self.ffmpeg, bins=waveform_bins, sample_rate=1000,
                        duration=info.duration, progress_callback=report_waveform_progress,
                        cancelled=cancelled,
                    )
                    silence_intervals = silence_intervals_from_waveform(
                        audio_waveform, duration=info.duration,
                    )
                    if not silence_intervals and not audio_waveform.get("rms"):
                        try:
                            silence_intervals = detect_silence_intervals(source, ffmpeg=self.ffmpeg)
                        except Exception:
                            silence_intervals = []
                    audio_waveform.update({
                        "schemaVersion": 3, "duration": info.duration, "hasAudio": True,
                        "silences": silence_intervals,
                    })
                    waveform_cache = work_directory / "timeline-waveform.json"
                    waveform_cache.parent.mkdir(parents=True, exist_ok=True)
                    waveform_cache.write_text(json.dumps(audio_waveform, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                audio_context = audio_hotspot_context(audio_waveform, info.duration)
                speech_segments = []
                speech_error = ""
                if analysis_mode == "audiovisual" and info.has_audio:
                    progress(0.06, "speech_recognition", "SenseVoice 正在理解对白、情绪、声音事件与说话人")
                    speech_checkpoint = {
                        "phase": "speech_analysis_ready", "video": asdict(info),
                        "audioContext": audio_context, "audioWaveform": audio_waveform, "usage": [],
                    }
                    write_analysis_checkpoint(work_directory, speech_checkpoint)
                    try:
                        def report_speech_progress(
                            value: Any = None,
                            processed: Any = None,
                            total: Any = None,
                            phase: Any = None,
                        ) -> None:
                            del processed, total
                            raw_fraction = max(0.0, float(value or 0))
                            fraction = min(1.0, raw_fraction)
                            # Older persistent speech workers do not expose a
                            # phase field, so a raw 1.0 must remain compatible
                            # and still enter the explicit finalizing state.
                            finalizing = str(phase or "") == "finalizing" or raw_fraction >= 1.0
                            measured = str(phase or "") == "recognizing_measured"
                            progress(
                                0.06 + 0.02 * fraction,
                                "speech_recognition",
                                "SenseVoice 正在整理识别结果"
                                if finalizing
                                else (f"SenseVoice 正在理解对白 · {int(fraction * 100)}%" if measured else "SenseVoice 正在理解对白、情绪与声音事件"),
                            )

                        speech_analysis = analyze_speech(
                            source, work_directory / "transcript.json", engine=speech_engine,
                            model_name=sensevoice_model if speech_engine == "sensevoice" else whisper_model,
                            device=sensevoice_device if speech_engine == "sensevoice" else whisper_device,
                            vad_model=sensevoice_vad_model, punc_model=sensevoice_punc_model,
                            spk_model=sensevoice_spk_model, diarization=sensevoice_diarization,
                            model_cache=speech_model_cache, whisper_model=whisper_model,
                            whisper_device=whisper_device, cancelled=cancelled,
                            progress_callback=report_speech_progress,
                        )
                        speech_segments = list(speech_analysis.get("segments") or [])
                        speech_analysis = {**speech_analysis, "status": "ready", "segments": len(speech_segments)}
                    except Exception as error:
                        if cancelled():
                            raise
                        write_analysis_checkpoint(work_directory, {
                            **speech_checkpoint, "decisionRequired": True,
                            "decisionStage": "speech_analysis", "decisionError": str(error)[:800],
                            "decisionAttempts": 1,
                        })
                        raise ModelDecisionRequired("speech_analysis", str(error), 1) from error
                elif analysis_mode == "audiovisual":
                    speech_analysis = {"engine": speech_engine, "status": "no_audio", "segments": 0}

            progress(0.08, "sampling", "正在均匀抽取视频画面")
            # Bound sequential VLM round trips while retaining full-video
            # coverage. Four-minute sources use 48 frames; long sources rise
            # gradually to a hard limit of 72.
            maximum_coarse_frames = coarse_frame_limit(info.duration)
            sampling_interval = max(2.0, info.duration / max(12, maximum_coarse_frames))
            expected_coarse_frames = max(1, min(maximum_coarse_frames, math.ceil(info.duration / sampling_interval)))
            def report_sampling_progress(extracted: list[SampledFrame]) -> None:
                completed = min(expected_coarse_frames, len(extracted))
                fraction = completed / expected_coarse_frames
                progress(
                    0.08 + 0.04 * fraction,
                    "sampling",
                    f"已抽取 {completed}/{expected_coarse_frames} 帧画面",
                )
            frames = extract_uniform_frames(
                source, work_directory / "coarse-frames", duration=info.duration,
                ffmpeg=self.ffmpeg, maximum_frames=maximum_coarse_frames,
                progress_callback=report_sampling_progress,
                progress_batch_size=4,
                progress_first_batch_size=1,
                cancelled=cancelled,
            )
            if len(frames) < 2:
                raise RuntimeError("视频可用画面不足，无法进行视觉高光分析")
            overview_count = min(16, len(frames))
            overview_frames = [
                frames[round(index * (len(frames) - 1) / max(1, overview_count - 1))]
                for index in range(overview_count)
            ]
            overview_sheet = create_contact_sheet(overview_frames, work_directory / "content-overview.jpg", columns=4)
            usage = []
            base_checkpoint = {
                "phase": "content_classification_ready", "video": asdict(info),
                "frames": [{"path": str(item.path), "time": item.time} for item in frames],
                "audioContext": audio_context, "audioWaveform": audio_waveform,
                "speechSegments": speech_segments, "speechRecognitionError": speech_error,
                "speechAnalysis": speech_analysis,
                "overviewSheet": str(overview_sheet), "usage": usage,
            }
            write_analysis_checkpoint(work_directory, base_checkpoint)
            try:
                classified = self._request_content_profile(
                    overview_sheet=overview_sheet, video_duration=info.duration,
                    theme=theme, analysis_mode=analysis_mode, progress=progress,
                )
                usage.append(classified.pop("_usage", {}))
                content_profile = normalize_content_profile(classified, theme)
            except Exception as error:
                write_analysis_checkpoint(work_directory, {
                    **base_checkpoint, "decisionRequired": True,
                    "decisionStage": "content_classification", "decisionError": str(error)[:800],
                    "decisionAttempts": 1,
                })
                raise ModelDecisionRequired("content_classification", str(error), 1) from error

        if len(frames) < 2:
            raise RuntimeError("分析检查点中的可用画面不足")
        write_analysis_checkpoint(work_directory, {
            "phase": "content_classification_complete",
            "video": {"duration": info.duration, "width": info.width, "height": info.height, "has_audio": info.has_audio},
            "frames": [{"path": str(item.path), "time": item.time} for item in frames],
            "audioContext": audio_context, "audioWaveform": audio_waveform,
            "speechSegments": speech_segments, "speechRecognitionError": speech_error,
            "speechAnalysis": speech_analysis,
            "contentProfile": content_profile, "usage": usage, "decisionRequired": False,
        })
        # A slightly denser contact sheet reduces sequential VLM round trips
        # without reducing full-video coverage.
        pages = [frames[index:index + 16] for index in range(0, len(frames), 16)]
        coarse: list[HighlightCandidate] = []
        for index, page in enumerate(pages):
            if cancelled():
                raise RuntimeError("任务已取消")
            sheet = create_contact_sheet(page, work_directory / "coarse-sheets" / f"sheet-{index:03d}.jpg")
            progress(
                0.14 + 0.36 * index / max(1, len(pages)),
                "coarse_vlm",
                f"视觉大模型正在分析第 {index + 1}/{len(pages)} 组画面",
            )
            result = self._analyze_with_heartbeat(
                prompt_text=coarse_discovery_prompt(
                    content_profile=content_profile,
                    theme=theme,
                    video_duration=info.duration,
                    exclusions=_exclusion_instruction(exclusions),
                    audio_context=audio_context + (f"\n当前联系表附近逐字稿：{transcript_context(speech_segments, page[0].time, page[-1].time)}" if speech_segments else ""),
                ),
                image_path=sheet,
                progress_value=0.14 + 0.36 * index / max(1, len(pages)),
                stage="coarse_vlm",
                detail=f"视觉大模型正在分析第 {index + 1}/{len(pages)} 组画面",
                progress=progress,
                maximum_tokens=1200,
            )
            usage.append(result.pop("_usage", {}))
            for raw in result.get("candidates", []):
                if not isinstance(raw, dict):
                    continue
                page_times = [frame.time for frame in page]
                interval = max((right - left for left, right in zip(page_times, page_times[1:])), default=2.0)
                verified_center = validated_model_time(raw.get("center_seconds"), page_times, tolerance=interval * .8)
                if verified_center is None:
                    continue
                raw = {**raw, "center_seconds": verified_center}
                candidate = _candidate_from_coarse(
                    raw,
                    duration=info.duration,
                    target_seconds=target_seconds,
                    automatic_duration=automatic_duration,
                )
                if candidate:
                    coarse.append(candidate)

        progress(.50, "coarse_vlm", f"已完成 {len(pages)}/{len(pages)} 组画面分析")

        audio_candidates = (
            speech_signal_candidates(speech_segments, video_duration=info.duration)
            if analysis_mode == "audiovisual" and speech_segments else []
        )
        coarse.extend(audio_candidates)
        if not coarse:
            raise RuntimeError("视觉大模型没有发现可用高光，请调整主题后重试")
        if exclusions:
            # Coarse ranges are intentionally broad. Filter by candidate center
            # first, then apply a strict overlap check after boundary refinement.
            coarse = [candidate for candidate in coarse if not any(
                start <= (candidate.start + candidate.end) / 2 <= end
                for start, end in exclusions
            )]
        if not coarse:
            raise RuntimeError("排除已有高光后没有剩余候选，请缩短片段或调整主题")
        # Refine more candidates than requested so deterministic overlap checks
        # still have alternatives without inventing time ranges.
        refinement_target = refinement_candidate_limit(
            discovery_only=discovery_only,
            total_target_seconds=total_target_seconds,
            target_seconds=target_seconds,
            count=count,
        )
        # Adjacent moments can be different physical shots belonging to the
        # same event. Do not apply title/one-second-gap deduplication before
        # visual refinement, otherwise a complete event can collapse into one
        # shot. Exact overlaps are removed here; semantic/visual deduplication
        # is deferred until the model has refined the real boundaries.
        refinement_pool = select_montage_moments(coarse, refinement_target)
        refined: list[HighlightCandidate] = []
        for index, candidate in enumerate(refinement_pool):
            if cancelled():
                raise RuntimeError("任务已取消")
            refined_candidate = candidate
            keep_candidate = True
            center = (candidate.start + candidate.end) / 2
            window = refinement_window_seconds(
                candidate,
                video_duration=info.duration,
                target_seconds=target_seconds,
                automatic_duration=automatic_duration,
            )
            # Boundary expansion is useful only for strong candidates. Avoid
            # doubling every VLM call when a candidate merely touches a wide
            # analysis window.
            maximum_passes = 2 if (
                automatic_duration and index < 2 and window < info.duration and candidate.score >= 90
            ) else 1
            for pass_index in range(maximum_passes):
                previous_refined = refined_candidate
                window_start = max(0.0, min(info.duration - window, center - window / 2))
                window_end = min(info.duration, window_start + window)
                frame_count = 11 if automatic_duration else 9
                sample_step = window / max(1, frame_count - 1)
                times = [
                    min(info.duration - 0.05, window_start + window * step / (frame_count - 1))
                    for step in range(frame_count)
                ]
                pass_directory = work_directory / "refine-frames" / f"candidate-{index:03d}-pass-{pass_index + 1}"
                detail_frames = extract_frames_at_times(source, pass_directory, times, ffmpeg=self.ffmpeg)
                sheet = create_contact_sheet(
                    detail_frames,
                    work_directory / "refine-sheets" / f"candidate-{index:03d}-pass-{pass_index + 1}.jpg",
                    columns=4 if automatic_duration else 3,
                )
                base_progress = 0.52 + 0.28 * index / max(1, len(refinement_pool))
                pass_text = "" if pass_index == 0 else "（边界触窗，已扩大观察范围）"
                detail = f"视觉大模型正在精修候选 {index + 1}/{len(refinement_pool)}{pass_text}"
                progress(base_progress, "refine_vlm", detail)
                result = self._analyze_with_heartbeat(
                    prompt_text=boundary_refinement_prompt(
                        content_profile=content_profile,
                        theme=theme,
                        candidate_title=refined_candidate.title,
                        candidate_role=refined_candidate.role,
                        video_duration=info.duration,
                        exclusions=_exclusion_instruction(exclusions),
                        speech_context=transcript_context(speech_segments, window_start, window_end) if speech_segments else "",
                    ),
                    image_path=sheet,
                    progress_value=base_progress,
                    stage="refine_vlm",
                    detail=detail,
                    progress=progress,
                    maximum_tokens=900,
                )
                usage.append(result.pop("_usage", {}))
                if result.get("keep") is False:
                    keep_candidate = False
                    break
                next_refined = _refined_candidate(
                    result,
                    previous_refined,
                    duration=info.duration,
                    target_seconds=target_seconds,
                    automatic_duration=automatic_duration,
                    allowed_times=[frame.time for frame in detail_frames],
                )
                # An expanded observation window may tempt the model to jump
                # to a neighbouring event. A boundary-refinement pass is only
                # allowed to refine/extend the same temporal moment.
                shared_seconds = max(
                    0.0,
                    min(previous_refined.end, next_refined.end)
                    - max(previous_refined.start, next_refined.start),
                )
                required_shared = min(
                    1.0,
                    min(previous_refined.duration, next_refined.duration) * .2,
                )
                if pass_index > 0 and shared_seconds < required_shared:
                    refined_candidate = previous_refined
                    break
                refined_candidate = next_refined
                if pass_index + 1 >= maximum_passes or not touches_refinement_boundary(
                    refined_candidate,
                    window_start=window_start,
                    window_end=window_end,
                    sample_step=sample_step,
                    video_duration=info.duration,
                ):
                    break
                center = (refined_candidate.start + refined_candidate.end) / 2
                window = min(info.duration, max(60.0, window * 1.8, refined_candidate.duration * 2.2))
            if not keep_candidate:
                continue
            if audio_waveform:
                energy = candidate_audio_energy(refined_candidate, audio_waveform, info.duration)
                refined_candidate = HighlightCandidate(
                    start=refined_candidate.start,
                    end=refined_candidate.end,
                    score=round(min(100.0, refined_candidate.score * .9 + energy * 10.0), 2),
                    title=refined_candidate.title,
                    reason=refined_candidate.reason,
                    evidence=refined_candidate.evidence + ([f"声音辅助证据：该区间音频能量强度约为 {energy * 100:.0f}%"] if energy >= .65 else []),
                    visual_signature=refined_candidate.visual_signature,
                    role=refined_candidate.role,
                    possible_event=refined_candidate.possible_event,
                    audio_evidence=refined_candidate.audio_evidence,
                    peak_start=refined_candidate.peak_start,
                    peak_end=refined_candidate.peak_end,
                    minimum_keep_seconds=refined_candidate.minimum_keep_seconds,
                    boundary_confidence=refined_candidate.boundary_confidence,
                )
            if detail_frames:
                refined_candidate = HighlightCandidate(
                    start=refined_candidate.start,
                    end=refined_candidate.end,
                    score=refined_candidate.score,
                    title=refined_candidate.title,
                    reason=refined_candidate.reason,
                    evidence=refined_candidate.evidence,
                    visual_signature=image_average_hash(detail_frames[len(detail_frames) // 2].path),
                    role=refined_candidate.role,
                    possible_event=refined_candidate.possible_event,
                    audio_evidence=speech_evidence(
                        speech_segments, refined_candidate.start, refined_candidate.end,
                    ) if speech_segments else {},
                    peak_start=refined_candidate.peak_start,
                    peak_end=refined_candidate.peak_end,
                    minimum_keep_seconds=refined_candidate.minimum_keep_seconds,
                    boundary_confidence=refined_candidate.boundary_confidence,
                )
            refined.append(refined_candidate)

        progress(.80, "refine_vlm", f"已完成 {len(refinement_pool)}/{len(refinement_pool)} 个候选精修")

        eligible = [candidate for candidate in refined if not overlaps_ranges(candidate, exclusions)]
        selected = select_montage_moments(eligible, min(14, max(8, count * 3)))
        if not selected:
            raise RuntimeError(
                "排除已有高光后，视觉模型没有给出不重叠的新片段" if exclusions
                else "候选区间全部重叠或无效，无法生成高光"
            )
        if discovery_only:
            candidates = [{
                "index": index,
                "candidateId": f"candidate_{index}",
                "semanticUnitId": f"semantic_{index}",
                "start": candidate.start,
                "end": candidate.end,
                "duration": round(candidate.duration, 3),
                "peakStart": candidate.peak_start,
                "peakEnd": candidate.peak_end,
                "minimumKeepSeconds": candidate.minimum_keep_seconds,
                "boundaryConfidence": candidate.boundary_confidence,
                "score": round(candidate.score, 2),
                "title": candidate.title,
                "reason": candidate.reason,
                "evidence": candidate.evidence,
                "role": candidate.role,
                "possibleEvent": candidate.possible_event,
                "audioEvidence": candidate.audio_evidence,
            } for index, candidate in enumerate(selected)]
            director_times: list[float] = []
            director_labels: list[tuple[int, str]] = []
            for candidate in candidates:
                start, end = float(candidate["start"]), float(candidate["end"])
                inset = min(.2, max(.02, (end - start) * .05))
                for phase, second in (
                    ("START", min(end, start + inset)),
                    ("PEAK", (float(candidate.get("peakStart") or start) + float(candidate.get("peakEnd") or end)) / 2),
                    ("END", max(start, end - inset)),
                ):
                    director_times.append(second)
                    director_labels.append((int(candidate["index"]), phase))
            def report_director_frames(completed: int, total: int) -> None:
                progress(
                    .80 + .03 * completed / max(1, total),
                    "event_grouping",
                    f"已提取 {completed}/{total} 帧事件编排画面",
                )
            director_frames = extract_frames_at_times(
                source, work_directory / "director-frames", director_times, ffmpeg=self.ffmpeg,
                progress_callback=report_director_frames,
            )
            if len(director_frames) != len(director_labels):
                raise RuntimeError("候选导演画面提取不完整")
            director_sheet = create_director_contact_sheet(
                [(label[0], label[1], frame) for label, frame in zip(director_labels, director_frames)],
                work_directory / "event-director-sheet.jpg",
            )
            director_checkpoint = {
                "phase": "event_director_ready", "video": asdict(info),
                "candidates": candidates, "contentProfile": content_profile,
                "directorSheet": str(director_sheet), "transcriptAvailable": bool(speech_segments),
                "speechSegments": speech_segments, "audioWaveform": audio_waveform,
                "sceneCuts": list(scene_cuts or []),
                "speechRecognitionError": speech_error, "speechAnalysis": speech_analysis, "usage": usage,
            }
            write_analysis_checkpoint(work_directory, director_checkpoint)
            try:
                grouping = self._request_event_director(
                    director_sheet=director_sheet,
                    candidates=candidates,
                    content_profile=content_profile,
                    theme=theme,
                    requested_count=requested_count,
                    total_target_seconds=total_target_seconds,
                    transcript_available=bool(speech_segments),
                    progress=progress,
                )
                usage.append(grouping.pop("_usage", {}))
            except Exception as error:
                write_analysis_checkpoint(work_directory, {
                    **director_checkpoint, "decisionRequired": True,
                    "decisionStage": "event_director", "decisionError": str(error)[:800],
                    "decisionAttempts": 1,
                })
                raise ModelDecisionRequired("event_director", str(error), 1) from error
            manifest = self._finish_event_manifest(
                source=source, info=asdict(info), candidates=candidates, grouping=grouping,
                content_profile=content_profile, total_target_seconds=total_target_seconds,
                requested_count=requested_count, theme=theme, analysis_mode=analysis_mode,
                transcript_available=bool(speech_segments), speech_error=speech_error,
                speech_segments=speech_segments,
                silence_intervals=list(audio_waveform.get("silences") or []),
                scene_cuts=list(scene_cuts or []),
                speech_analysis=speech_analysis,
                exclusions=exclusions, usage=usage, progress=progress,
            )
            write_analysis_checkpoint(work_directory, {
                **director_checkpoint, "phase": "completed", "decisionRequired": False,
            })
            return manifest
        progress(0.83, "rendering", f"正在渲染 {len(selected)} 个高光片段")
        output_directory.mkdir(parents=True, exist_ok=True)
        outputs: list[dict[str, Any]] = []
        for index, candidate in enumerate(selected):
            if cancelled():
                raise RuntimeError("任务已取消")
            filename = safe_output_filename(candidate.title, index + 1)
            output_path = output_directory / filename
            render_clip(
                source,
                output_path,
                start=candidate.start,
                end=candidate.end,
                has_audio=info.has_audio,
                ffmpeg=self.ffmpeg,
                cancelled=cancelled,
            )
            rendered = validate_rendered_clip(
                output_path,
                expected_duration=candidate.duration,
                expect_audio=info.has_audio,
                ffmpeg=self.ffmpeg,
                ffprobe=self.ffprobe,
            )
            outputs.append({
                "filename": filename,
                "start": candidate.start,
                "end": candidate.end,
                "duration": round(rendered.duration, 3),
                "score": round(candidate.score, 2),
                "title": candidate.title,
                "reason": candidate.reason,
                "evidence": candidate.evidence,
            })
            progress(0.83 + 0.15 * (index + 1) / len(selected), "rendering", f"已生成 {index + 1}/{len(selected)} 个片段")

        manifest = {
            "schemaVersion": 1,
            "source": source.name,
            "video": asdict(info),
            "requestedCount": count,
            "actualCount": len(outputs),
            "targetSeconds": target_seconds,
            "theme": theme,
            "selectionBackend": self.selection_backend,
            "analysisMode": analysis_mode,
            "transcriptAvailable": bool(speech_segments),
            "speechRecognitionError": speech_error or None,
            "speechAnalysis": speech_analysis,
            "excludedRanges": [{"start": start, "end": end} for start, end in exclusions],
            "outputs": outputs,
            "usage": usage,
        }
        (output_directory / "highlights.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        progress(1.0, "completed", f"已生成 {len(outputs)} 个视觉高光片段")
        return manifest
