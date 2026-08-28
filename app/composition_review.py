from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import sys
from array import array
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

from .editing_techniques import (
    composition_effective_duration,
    composition_schedule,
    normalize_audio_bridge,
    normalize_playback_rate,
    normalize_transition,
)
from .media import create_labeled_contact_sheet, extract_frames_at_times
from .quality_gate import deduplicate_issues


REVIEW_DIMENSIONS = ("content", "narrative", "rhythm", "continuity", "audiovisual", "goalMatch")
REVIEW_CALIBRATION_VERSION = "composition-calibration-v7-root-cause-balanced"
REPAIR_ACTIONS = {
    "adjust_bounds", "remove_segment", "replace_segment", "insert_segment", "reorder_segments",
    "set_transition", "set_audio_bridge", "set_audio_fade", "set_speed",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def composition_review_timeline(
    segments: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    schedule = composition_schedule(segments)
    transcript = transcript_segments or []
    rows: list[dict[str, Any]] = []
    for index, (segment, timing) in enumerate(zip(segments, schedule), 1):
        start = _number(segment.get("start"))
        end = max(start, _number(segment.get("end"), start))
        spoken = []
        for unit in transcript:
            if not isinstance(unit, dict):
                continue
            left = _number(unit.get("start"))
            right = max(left, _number(unit.get("end"), left))
            if max(start, left) >= min(end, right):
                continue
            text = str(unit.get("text") or unit.get("sentence") or "").strip()
            if text:
                spoken.append({
                    "start": round(left, 3), "end": round(right, 3),
                    "speaker": str(unit.get("speaker") or ""), "text": text[:240],
                })
        rows.append({
            "index": index,
            "segmentId": str(segment.get("id") or segment.get("candidateId") or f"segment_{index}"),
            "candidateId": str(segment.get("candidateId") or segment.get("id") or f"segment_{index}"),
            "eventId": str(segment.get("groupId") or segment.get("chapterId") or segment.get("eventId") or ""),
            "role": str(segment.get("role") or "精彩镜头")[:80],
            "sourceStart": round(start, 3), "sourceEnd": round(end, 3),
            "outputStart": timing["outputStart"], "outputEnd": timing["outputEnd"],
            "transitionOverlap": timing.get("transitionOverlap", 0.0),
            "score": round(_number(segment.get("score"), 50), 2),
            "reason": str(segment.get("reason") or "")[:300],
            "playbackRate": normalize_playback_rate(segment.get("playbackRate")),
            "transitionIn": normalize_transition(segment.get("transitionIn"), first=index == 1),
            "audioBridge": normalize_audio_bridge(segment.get("audioBridge"), first=index == 1),
            "audioEdgeFadeSeconds": round(max(.06, min(.35, _number(segment.get("audioEdgeFadeSeconds"), .06))), 3),
            "silenceCuts": list(segment.get("silenceCuts") or [])[:8],
            "actionComplete": bool(segment.get("actionComplete", True)),
            "uncertainty": dict(segment.get("uncertainty") or {}),
            "verificationState": dict(segment.get("verificationState") or {}),
            "safeRanges": dict(segment.get("safeRanges") or {}),
            "audioEvidence": {
                key: value for key, value in dict(segment.get("audioEvidence") or {}).items()
                if key in {"transcriptExcerpt", "speakers", "emotions", "audioEvents", "energy"}
            },
            "transcript": spoken[:12],
        })
    return {"duration": composition_effective_duration(segments), "segments": rows}


def build_composition_review_sheet(
    output: Path,
    segments: list[dict[str, Any]],
    work_directory: Path,
    *,
    ffmpeg: str,
) -> tuple[Path, dict[str, Any]]:
    """Sample the actual rendered output, with dense coverage around cuts."""
    duration = max(.2, composition_effective_duration(segments))
    schedule = composition_schedule(segments)
    samples: list[tuple[float, str]] = []
    uniform_count = max(6, min(14, math.ceil(duration / 5.0) + 1))
    for index in range(uniform_count):
        second = min(max(0.0, duration - .05), duration * index / max(1, uniform_count - 1))
        samples.append((second, f"OUT {second:06.2f}s · 全片采样"))
    for index, timing in enumerate(schedule[1:], 2):
        cut = _number(timing.get("outputStart"))
        samples.extend([
            (max(0.0, cut - .18), f"CUT {index - 1}→{index} · 前  {max(0.0, cut - .18):06.2f}s"),
            (min(duration - .05, cut + .18), f"CUT {index - 1}→{index} · 后  {min(duration, cut + .18):06.2f}s"),
        ])
    unique: dict[int, tuple[float, str]] = {}
    for second, label in samples:
        key = round(max(0.0, min(duration - .05, second)) * 20)
        unique.setdefault(key, (max(0.0, min(duration - .05, second)), label))
    # The automatic cutter currently caps a reel at 14 source moments.  Keep
    # both sides of every cut plus the global samples (up to 40 frames) so a
    # late jump cut is not silently dropped merely because it appears last.
    chosen = sorted(unique.values(), key=lambda item: item[0])[:48]
    times = [item[0] for item in chosen]
    frames = extract_frames_at_times(output, work_directory / "frames", times, ffmpeg=ffmpeg)
    sheet = create_labeled_contact_sheet(
        frames, [item[1] for item in chosen], work_directory / "composition-review.jpg", columns=4,
    )
    visual_metrics = rendered_visual_metrics(frames)
    return sheet, {
        "duration": round(duration, 3),
        "frameCount": len(frames),
        "cutCount": max(0, len(schedule) - 1),
        "samples": [{"time": round(second, 3), "label": label} for second, label in chosen],
        "visualMetrics": visual_metrics,
    }


def prepare_dynamic_review_proxy(
    output: Path,
    destination: Path,
    *,
    ffmpeg: str,
    maximum_bytes: int = 22 * 1024 * 1024,
) -> Path:
    """Create a compact, cached dynamic-video sample for VLM review."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size > 1024:
        return destination
    if output.stat().st_size <= maximum_bytes and output.suffix.lower() == ".mp4":
        # Keep the real rendered output when the provider upload remains small.
        return output
    temporary = destination.with_suffix(".tmp.mp4")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(output),
        "-vf", "scale='min(720,iw)':-2:force_original_aspect_ratio=decrease,fps=8",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "31",
        "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(temporary),
    ]
    result = subprocess.run(command, capture_output=True, timeout=900, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or b"review proxy failed")[-1200:].decode("utf-8", "replace"))
    temporary.replace(destination)
    return destination


def _dbfs(value: float) -> float:
    return round(20.0 * math.log10(max(1e-9, value)), 2)


def analyze_rendered_audio(
    output: Path,
    segments: list[dict[str, Any]],
    *,
    ffmpeg: str,
    sample_rate: int = 8000,
) -> dict[str, Any]:
    """Measure the *rendered output* PCM, including every edit boundary.

    These are deterministic engineering checks, not source-side model guesses:
    clipping, unexpected silence, level discontinuity and sample jumps are all
    measured after transitions, speed changes and audio bridges were rendered.
    """
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(output),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, timeout=900, check=False)
    if result.returncode != 0:
        detail = (result.stderr or b"")[-800:].decode("utf-8", "replace")
        return {"status": "unavailable", "reason": detail or "audio decode failed", "issues": []}
    samples = array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return {"status": "no_audio", "duration": 0.0, "issues": []}
    scale = 32768.0
    peak = max(abs(value) for value in samples) / scale
    rms = math.sqrt(sum(float(value) * float(value) for value in samples) / len(samples)) / scale
    clipping = sum(abs(value) >= 32700 for value in samples) / len(samples)
    window = max(1, int(sample_rate * .05))
    silent = 0
    windows = 0
    for offset in range(0, len(samples), window):
        block = samples[offset:offset + window]
        if not block:
            continue
        block_rms = math.sqrt(sum(float(value) * float(value) for value in block) / len(block)) / scale
        silent += block_rms < 10 ** (-45 / 20)
        windows += 1
    cuts: list[dict[str, Any]] = []
    for index, timing in enumerate(composition_schedule(segments)[1:], 2):
        second = _number(timing.get("outputStart"))
        center = max(1, min(len(samples) - 2, round(second * sample_rate)))
        radius = max(1, round(sample_rate * .18))
        before = samples[max(0, center - radius):center]
        after = samples[center:min(len(samples), center + radius)]
        before_rms = math.sqrt(sum(float(value) * float(value) for value in before) / max(1, len(before))) / scale
        after_rms = math.sqrt(sum(float(value) * float(value) for value in after) / max(1, len(after))) / scale
        delta = abs(_dbfs(before_rms) - _dbfs(after_rms))
        jump = abs(samples[center] - samples[center - 1]) / scale
        cuts.append({
            "cut": f"{index - 1}->{index}", "outputTime": round(second, 3),
            "beforeRmsDbfs": _dbfs(before_rms), "afterRmsDbfs": _dbfs(after_rms),
            "rmsDeltaDb": round(delta, 2), "sampleJump": round(jump, 4),
            "abrupt": delta >= 14.0 or jump >= .72,
        })
    issues: list[dict[str, Any]] = []
    if clipping > .001:
        issues.append({"severity": "major", "category": "audio_clipping", "description": "渲染音轨存在明显削波", "value": round(clipping, 6)})
    silence_ratio = silent / max(1, windows)
    if silence_ratio > .62 and rms > 10 ** (-55 / 20):
        issues.append({"severity": "major", "category": "unexpected_silence", "description": "成片静音占比异常偏高", "value": round(silence_ratio, 4)})
    for item in cuts:
        if item["abrupt"]:
            issues.append({
                "severity": "major" if item["rmsDeltaDb"] >= 20 or item["sampleJump"] >= .9 else "minor",
                "category": "audio_cut", "description": f"切点 {item['cut']} 音量或波形突变",
                "outputTime": item["outputTime"], "value": {"rmsDeltaDb": item["rmsDeltaDb"], "sampleJump": item["sampleJump"]},
            })
    return {
        "status": "completed", "sampleRate": sample_rate,
        "duration": round(len(samples) / sample_rate, 3),
        "peakDbfs": _dbfs(peak), "rmsDbfs": _dbfs(rms),
        "clippingRatio": round(clipping, 7), "silenceRatio": round(silence_ratio, 4),
        "cutChecks": cuts, "issues": issues[:12],
    }


def rendered_visual_metrics(frames: list[Any]) -> dict[str, Any]:
    luminance: list[float] = []
    changes: list[float] = []
    previous: Image.Image | None = None
    for sampled in frames:
        try:
            with Image.open(sampled.path) as source:
                gray = source.convert("L").resize((96, 54), Image.Resampling.BILINEAR)
                luminance.append(float(ImageStat.Stat(gray).mean[0]))
                if previous is not None:
                    changes.append(float(ImageStat.Stat(ImageChops.difference(previous, gray)).mean[0]))
                previous = gray.copy()
        except (OSError, ValueError):
            continue
    return {
        "sampleCount": len(luminance),
        "blackFrameRatio": round(sum(value < 7 for value in luminance) / max(1, len(luminance)), 4),
        "freezePairRatio": round(sum(value < .65 for value in changes) / max(1, len(changes)), 4),
        "meanLuminance": round(sum(luminance) / max(1, len(luminance)), 2),
        "meanFrameChange": round(sum(changes) / max(1, len(changes)), 2),
    }


def review_cache_key(
    *, version_signature: str, goal: dict[str, Any], visual_model: str, llm_model: str,
    prompt_version: str = "",
) -> str:
    payload = json.dumps({
        "signature": version_signature, "goal": goal, "visualModel": visual_model,
        "llmModel": llm_model, "promptVersion": prompt_version,
        "calibration": REVIEW_CALIBRATION_VERSION,
    }, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def normalize_review_report(
    visual: dict[str, Any] | None,
    editorial: dict[str, Any] | None,
) -> dict[str, Any]:
    visual = visual if isinstance(visual, dict) else {}
    editorial = editorial if isinstance(editorial, dict) else {}
    raw_scores = editorial.get("scores") if isinstance(editorial.get("scores"), dict) else {}
    visual_scores = visual.get("scores") if isinstance(visual.get("scores"), dict) else {}
    scores = {
        key: round(max(0.0, min(100.0, _number(raw_scores.get(key), _number(visual_scores.get(key), 70)))), 1)
        for key in REVIEW_DIMENSIONS
    }
    supplied_overall = _number(editorial.get("overallScore"), -1)
    overall = supplied_overall if supplied_overall >= 0 else sum(scores.values()) / len(scores)
    issues: list[dict[str, Any]] = []
    for collection in (visual.get("issues") or [], editorial.get("issues") or []):
        for source in collection if isinstance(collection, list) else []:
            if not isinstance(source, dict):
                continue
            severity = str(source.get("severity") or "minor").lower()
            if severity not in {"critical", "major", "minor"}:
                severity = "minor"
            issue = {
                "id": str(source.get("id") or f"issue_{len(issues) + 1}"),
                "severity": severity,
                "category": str(source.get("category") or "editorial")[:50],
                "segmentIds": [str(value) for value in (source.get("segmentIds") or []) if str(value)][:8],
                "outputTime": round(max(0.0, _number(source.get("outputTime"))), 3),
                "description": str(source.get("description") or source.get("reason") or "")[:400],
                "evidence": str(source.get("evidence") or "")[:400],
                "fixable": bool(source.get("fixable", True)),
            }
            signature = (issue["category"], tuple(issue["segmentIds"]), issue["description"][:80])
            if not any((item["category"], tuple(item["segmentIds"]), item["description"][:80]) == signature for item in issues):
                issues.append(issue)
    actions: list[dict[str, Any]] = []
    for raw in editorial.get("repairActions") or []:
        if not isinstance(raw, dict):
            continue
        action_type = str(raw.get("type") or "").strip().lower()
        if action_type not in REPAIR_ACTIONS:
            continue
        actions.append({
            "type": action_type,
            "segmentId": str(raw.get("segmentId") or ""),
            "replacementCandidateId": str(raw.get("replacementCandidateId") or ""),
            "afterSegmentId": str(raw.get("afterSegmentId") or ""),
            "start": round(_number(raw.get("start")), 3) if raw.get("start") is not None else None,
            "end": round(_number(raw.get("end")), 3) if raw.get("end") is not None else None,
            "orderedSegmentIds": [str(value) for value in (raw.get("orderedSegmentIds") or []) if str(value)],
            "playbackRate": _number(raw.get("playbackRate"), 1.0),
            "transitionIn": raw.get("transitionIn") if isinstance(raw.get("transitionIn"), dict) else {},
            "audioBridge": raw.get("audioBridge") if isinstance(raw.get("audioBridge"), dict) else {},
            "audioFadeSeconds": round(max(.06, min(.35, _number(raw.get("audioFadeSeconds"), .12))), 3),
            "reason": str(raw.get("reason") or "")[:300],
        })
    return {
        "schemaVersion": 1,
        "overallScore": round(max(0.0, min(100.0, overall)), 1),
        "scores": scores,
        "issues": issues[:18],
        "criticalCount": sum(item["severity"] == "critical" for item in issues),
        "majorCount": sum(item["severity"] == "major" for item in issues),
        "minorCount": sum(item["severity"] == "minor" for item in issues),
        "repairActions": actions[:3],
        "summary": str(editorial.get("summary") or visual.get("summary") or "成片审片完成")[:600],
        "strengths": [str(value)[:240] for value in (editorial.get("strengths") or visual.get("strengths") or [])][:5],
    }


def sanitize_review_report(
    report: dict[str, Any], *, timeline: dict[str, Any] | None = None,
    target_seconds: float | None = None,
) -> dict[str, Any]:
    """Remove batch-level and transition-overlap false positives before gating."""
    cleaned = copy.deepcopy(report)
    rows = [item for item in (timeline or {}).get("segments") or [] if isinstance(item, dict)]
    valid_transition_overlaps: list[dict[str, Any]] = []
    invalid_cross_event_bridges: list[dict[str, Any]] = []
    invalid_cross_event_dissolves: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if index <= 0:
            continue
        previous = rows[index - 1]
        boundary = {
            "time": _number(row.get("outputStart")),
            "ids": {
                str(previous.get("segmentId") or ""),
                str(row.get("segmentId") or ""),
            },
        }
        transition_type = str((row.get("transitionIn") or {}).get("type") or "cut")
        bridge_type = str((row.get("audioBridge") or {}).get("type") or "none")
        if _number(row.get("transitionOverlap")) > .001 and transition_type in {"dissolve", "fade_black"}:
            valid_transition_overlaps.append(boundary)
        previous_event = str(previous.get("eventId") or "")
        event_id = str(row.get("eventId") or "")
        if previous_event and event_id and previous_event != event_id:
            if bridge_type != "none":
                invalid_cross_event_bridges.append(boundary)
            if transition_type == "dissolve":
                invalid_cross_event_dissolves.append(boundary)

    timeline_has_event_ids = bool(rows) and all(str(row.get("eventId") or "") for row in rows)

    def matches_boundary(item_ids: set[str], output_time: float, boundaries: list[dict[str, Any]]) -> bool:
        return any(
            abs(output_time - boundary["time"]) <= .4
            or (item_ids and item_ids.issubset(boundary["ids"]))
            for boundary in boundaries
        )

    actual = _number((timeline or {}).get("duration"))
    target = _number(target_seconds)
    ratio = actual / target if actual > 0 and target > 0 else None
    issues: list[dict[str, Any]] = []
    removed_issue_ids: set[str] = set()
    # Model opinions are warnings by default. Only a dynamically observed,
    # evidence-backed action truncation may remain critical here. Media,
    # speech, duplicate-source and explicit user-constraint hard failures are
    # added later by deterministic validators.
    model_hard_categories = {"action"}
    for raw in cleaned.get("issues") or []:
        if not isinstance(raw, dict):
            continue
        item = copy.deepcopy(raw)
        category = str(item.get("category") or "editorial").lower()
        text = f"{item.get('description') or ''} {item.get('evidence') or ''}".lower()
        item_ids = {str(value) for value in item.get("segmentIds") or [] if str(value)}
        output_time = _number(item.get("outputTime"), -999.0)

        batch_count_claim = (
            any(token in text for token in ("仅产出1条", "只产出1条", "仅生成1条", "只生成1条"))
            or ("未完成生成" in text and any(token in text for token in ("条视频", "个视频", "高光视频")))
        )
        if batch_count_claim and category not in {"duration", "duration_shortfall", "duration_overflow"}:
            removed_issue_ids.add(str(item.get("id") or ""))
            continue

        cross_event_claim = any(token in text for token in ("不同事件", "独立事件", "跨事件", "跨章节", "章节间"))
        bridge_claim = cross_event_claim and any(token in text for token in (
            "j-cut", "jcut", "l-cut", "lcut", "声音桥", "audio bridge", "audio_bridge",
        ))
        if bridge_claim and timeline_has_event_ids and not matches_boundary(
            item_ids, output_time, invalid_cross_event_bridges,
        ):
            # A bridge belongs to the incoming row.  Models occasionally read a
            # valid J-cut on shot N as if it continued from N into N+1.
            removed_issue_ids.add(str(item.get("id") or ""))
            continue
        dissolve_claim = cross_event_claim and any(token in text for token in ("溶解", "叠化", "dissolve"))
        if dissolve_claim and timeline_has_event_ids and not matches_boundary(
            item_ids, output_time, invalid_cross_event_dissolves,
        ):
            removed_issue_ids.add(str(item.get("id") or ""))
            continue

        overlap_claim = any(token in text for token in (
            "时间重叠", "时间线重叠", "时间码冲突", "outputend", "transitionoverlap",
        ))
        valid_overlap = overlap_claim and any(
            abs(output_time - overlap["time"]) <= .4
            or (item_ids and item_ids.issubset(overlap["ids"]))
            for overlap in valid_transition_overlaps
        )
        if valid_overlap:
            removed_issue_ids.add(str(item.get("id") or ""))
            continue

        if category in {"duration", "duration_shortfall", "duration_overflow"} and ratio is not None:
            item["outputTime"] = round(actual, 3)
            if ratio < .70:
                item.update({
                    "severity": "critical", "category": "duration_shortfall",
                    "description": f"本条样片 {actual:.1f} 秒，低于目标 {target:.1f} 秒的 70%，不满足最低展示时长",
                })
            elif ratio < .90:
                item.update({
                    "severity": "major", "category": "duration_shortfall",
                    "description": f"本条样片 {actual:.1f} 秒，低于目标 {target:.1f} 秒；可作为偏短备选，但不进入推荐",
                })
            elif ratio > 1.25:
                item.update({
                    "severity": "critical", "category": "duration_overflow",
                    "description": f"本条样片 {actual:.1f} 秒，超过目标 {target:.1f} 秒的 125%，不满足最高展示时长",
                })
            elif ratio > 1.10:
                item.update({
                    "severity": "major", "category": "duration_overflow",
                    "description": f"本条样片 {actual:.1f} 秒，超过目标 {target:.1f} 秒；可作为偏长备选，但不进入推荐",
                })
            elif batch_count_claim:
                removed_issue_ids.add(str(item.get("id") or ""))
                continue

        if str(item.get("severity") or "") == "critical":
            evidence_backed_action = (
                category in model_hard_categories
                and bool(item_ids)
                and bool(str(item.get("evidence") or "").strip())
                and any(token in text for token in ("截断", "未完成", "不完整", "动作中途", "操作中途"))
            )
            if not evidence_backed_action:
                item["severity"] = "major"
        issues.append(item)

    actions = []
    for action in cleaned.get("repairActions") or []:
        if not isinstance(action, dict):
            continue
        reason = str(action.get("reason") or "").lower()
        if any(token in reason for token in ("时间重叠", "时间码冲突", "outputend")):
            continue
        actions.append(action)
    issues = deduplicate_issues(issues)
    cleaned.update({
        "issues": issues[:18],
        "criticalCount": sum(item.get("severity") == "critical" for item in issues),
        "majorCount": sum(item.get("severity") == "major" for item in issues),
        "minorCount": sum(item.get("severity") == "minor" for item in issues),
        "repairActions": actions[:3],
        "sanitizedIssueIds": sorted(value for value in removed_issue_ids if value),
    })
    return cleaned


def calibrate_review_report(
    report: dict[str, Any],
    *,
    media_evidence: dict[str, Any] | None = None,
    target_seconds: float | None = None,
    actual_seconds: float | None = None,
) -> dict[str, Any]:
    """Turn subjective model scores into a stable, evidence-backed score."""
    calibrated = copy.deepcopy(report)
    scores = dict(calibrated.get("scores") or {})
    weights = {
        "content": .20, "narrative": .20, "rhythm": .15,
        "continuity": .20, "audiovisual": .15, "goalMatch": .10,
    }
    weighted = sum(max(0.0, min(100.0, _number(scores.get(key), 70))) * weight for key, weight in weights.items())
    model_score = max(0.0, min(100.0, _number(calibrated.get("overallScore"), weighted)))
    # Temper both model opinions with the fixed rubric instead of allowing a
    # single generous overall score to dominate ranking.
    base = .35 * model_score + .65 * weighted
    evidence = media_evidence if isinstance(media_evidence, dict) else {}
    audio = evidence.get("audioMetrics") if isinstance(evidence.get("audioMetrics"), dict) else {}
    visual = evidence.get("visualMetrics") if isinstance(evidence.get("visualMetrics"), dict) else {}
    intent = evidence.get("intentValidation") if isinstance(evidence.get("intentValidation"), dict) else {}
    deterministic: list[dict[str, Any]] = []
    for item in audio.get("issues") or []:
        if isinstance(item, dict):
            deterministic.append({**item, "source": "rendered_audio"})
    if _number(visual.get("blackFrameRatio")) > .08:
        deterministic.append({"severity": "major", "category": "black_frames", "description": "成片黑帧占比异常", "source": "rendered_video"})
    if _number(visual.get("freezePairRatio")) > .55:
        deterministic.append({"severity": "major", "category": "freeze", "description": "成片连续画面疑似长时间冻结", "source": "rendered_video"})
    if target_seconds and actual_seconds:
        signed_ratio = (float(actual_seconds) - float(target_seconds)) / max(1.0, float(target_seconds))
        if signed_ratio > .25:
            deterministic.append({
                "severity": "critical", "category": "duration_overflow",
                "description": f"实际时长超过目标 {signed_ratio * 100:.0f}%（最高展示上限 25%）", "source": "rendered_timeline",
            })
        elif signed_ratio > .10:
            deterministic.append({
                "severity": "major", "category": "duration_overflow",
                "description": f"实际时长超过目标 {signed_ratio * 100:.0f}%，可展示但不进入推荐", "source": "rendered_timeline",
            })
        elif signed_ratio < -.30:
            deterministic.append({
                "severity": "critical", "category": "duration_shortfall",
                "description": f"实际时长低于目标 {abs(signed_ratio) * 100:.0f}%（最低展示比例 70%）", "source": "rendered_timeline",
            })
        elif signed_ratio < -.10:
            deterministic.append({
                "severity": "major", "category": "duration_shortfall",
                "description": f"实际时长低于目标 {abs(signed_ratio) * 100:.0f}%，可展示但不进入推荐", "source": "rendered_timeline",
            })
    for item in intent.get("issues") or []:
        if not isinstance(item, dict):
            continue
        deterministic.append({
            **item,
            "severity": str(item.get("severity") or "major"),
            "source": "user_intent_validator",
        })
    model_issues = deduplicate_issues(list(calibrated.get("issues") or []))
    deterministic = deduplicate_issues(deterministic)
    combined_issues = deduplicate_issues(model_issues, deterministic)
    counts = {
        severity: sum(item.get("severity") == severity for item in combined_issues)
        for severity in ("critical", "major", "minor")
    }
    # Dimension scores already express the visible impact of an issue. Apply
    # a bounded root-cause penalty here to enforce confidence without charging
    # the same bad cut once as content, once as continuity and again as an
    # unverified fact. Critical issues still fail the hard gate independently.
    penalty = min(
        15.0,
        min(10.0, counts["critical"] * 5.0)
        + min(6.0, counts["major"] * 1.5)
        + min(2.0, counts["minor"] * .5),
    )
    score = max(0.0, min(100.0, base - penalty))
    calibrated.update({
        "schemaVersion": 2,
        "modelOverallScore": round(model_score, 1),
        "rubricScore": round(weighted, 1),
        "overallScore": round(score, 1),
        "calibratedScore": round(score, 1),
        "calibrationVersion": REVIEW_CALIBRATION_VERSION,
        "deterministicChecks": deterministic[:16],
        "issues": combined_issues[:18],
        "deterministicPenalty": round(penalty, 2),
        "criticalCount": counts["critical"],
        "majorCount": counts["major"],
        "minorCount": counts["minor"],
    })
    return calibrated


def apply_review_repairs(
    segments: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    maximum_actions: int = 3,
) -> dict[str, Any]:
    """Apply only model actions that can be verified against known evidence."""
    result = copy.deepcopy(segments)
    candidate_map: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        for key in (candidate.get("id"), candidate.get("candidateId")):
            if key:
                candidate_map[str(key)] = candidate
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def locate(segment_id: str) -> int | None:
        return next((index for index, item in enumerate(result) if str(item.get("id") or item.get("candidateId")) == segment_id), None)

    for raw in actions[:maximum_actions]:
        action = copy.deepcopy(raw)
        action_type = str(action.get("type") or "")
        segment_id = str(action.get("segmentId") or "")
        index = locate(segment_id) if segment_id else None
        reason = ""
        if action_type == "remove_segment":
            if index is None or len(result) <= 1:
                reason = "镜头不存在或不能删除唯一镜头"
            else:
                result.pop(index)
        elif action_type == "replace_segment":
            replacement = candidate_map.get(str(action.get("replacementCandidateId") or ""))
            if index is None or not replacement:
                reason = "原镜头或替换候选不存在"
            else:
                replacement_id = str(replacement.get("id") or replacement.get("candidateId") or "")
                if any(str(item.get("id") or item.get("candidateId")) == replacement_id for pos, item in enumerate(result) if pos != index):
                    reason = "替换候选已在成片中"
                else:
                    start, end = _number(replacement.get("start")), _number(replacement.get("end"))
                    if end - start + 1e-6 < .2:
                        reason = "替换候选时长无效"
                    else:
                        original_order = result[index].get("editOrder", index)
                        result[index] = {
                            **copy.deepcopy(replacement), "id": replacement_id,
                            "candidateId": replacement_id, "start": start, "end": end,
                            "duration": round(end - start, 3), "editOrder": original_order,
                            "reason": str(action.get("reason") or replacement.get("reason") or "AI 审片替换镜头"),
                        }
        elif action_type == "insert_segment":
            replacement = candidate_map.get(str(action.get("replacementCandidateId") or ""))
            replacement_id = str((replacement or {}).get("id") or (replacement or {}).get("candidateId") or "")
            if not replacement:
                reason = "插入候选不存在"
            elif any(str(item.get("candidateId") or item.get("id")) == replacement_id for item in result):
                reason = "插入候选已在成片中"
            else:
                start, end = _number(replacement.get("start")), _number(replacement.get("end"))
                minimum = max(.35, _number(replacement.get("minimumKeepSeconds"), .35))
                if end - start < minimum:
                    reason = "插入候选不满足最短完整时长"
                else:
                    after_id = str(action.get("afterSegmentId") or "")
                    after_index = locate(after_id) if after_id else None
                    if after_id and after_index is None:
                        reason = "指定的插入位置不存在"
                    else:
                        insert_at = 0 if not after_id else int(after_index) + 1
                        result.insert(insert_at, {
                            **copy.deepcopy(replacement), "id": replacement_id,
                            "candidateId": replacement_id, "start": start, "end": end,
                            "duration": round(end - start, 3),
                            "reason": str(action.get("reason") or replacement.get("reason") or "AI 审片补充必要镜头"),
                            "transitionIn": normalize_transition({"type": "cut"}, first=insert_at == 0),
                        })
        elif action_type == "adjust_bounds":
            if index is None:
                reason = "镜头不存在"
            else:
                item = result[index]
                candidate = candidate_map.get(str(item.get("candidateId") or item.get("id") or ""))
                if not candidate:
                    reason = "缺少候选安全边界"
                else:
                    candidate_start = _number(candidate.get("start"))
                    candidate_end = _number(candidate.get("end"))
                    lower = max(candidate_start, _number(candidate.get("safeStart"), candidate_start))
                    upper = min(candidate_end, _number(candidate.get("safeEnd"), candidate_end))
                    start = max(lower, _number(action.get("start"), _number(item.get("start"))))
                    end = min(upper, _number(action.get("end"), _number(item.get("end"))))
                    minimum = max(.35, _number(candidate.get("minimumKeepSeconds"), .35))
                    if end - start < minimum:
                        reason = "调整后低于候选最短完整时长"
                    else:
                        item.update({"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)})
        elif action_type == "reorder_segments":
            ordered = [str(value) for value in action.get("orderedSegmentIds") or []]
            current = [str(item.get("id") or item.get("candidateId")) for item in result]
            if len(ordered) != len(current) or set(ordered) != set(current):
                reason = "排序必须完整保留当前全部镜头"
            else:
                by_id = {str(item.get("id") or item.get("candidateId")): item for item in result}
                result = [by_id[value] for value in ordered]
        elif action_type == "set_transition":
            if index is None or index == 0:
                reason = "首镜头或镜头不存在，不能设置入场转场"
            else:
                result[index]["transitionIn"] = normalize_transition(action.get("transitionIn"))
        elif action_type == "set_audio_bridge":
            if index is None or index == 0:
                reason = "首镜头或镜头不存在，不能设置声音桥"
            else:
                result[index]["audioBridge"] = normalize_audio_bridge(action.get("audioBridge"))
                if result[index]["audioBridge"]["type"] != "none":
                    result[index]["transitionIn"] = normalize_transition({"type": "cut"})
        elif action_type == "set_audio_fade":
            if index is None:
                reason = "镜头不存在，不能平滑音频切点"
            else:
                fade = max(.06, min(.35, _number(action.get("audioFadeSeconds"), .12)))
                result[index]["audioEdgeFadeSeconds"] = round(fade, 3)
                if index > 0:
                    result[index - 1]["audioEdgeFadeSeconds"] = round(fade, 3)
        elif action_type == "set_speed":
            if index is None:
                reason = "镜头不存在"
            else:
                item = result[index]
                if item.get("hasSpeech") or item.get("speechUnits") or str(item.get("role") or "").lower() in {"climax", "reaction", "result", "高潮", "人物反应", "结果", "结尾"}:
                    reason = "对白、高潮、反应或结尾镜头禁止自动变速"
                else:
                    item["playbackRate"] = normalize_playback_rate(action.get("playbackRate"), 1.25)
        else:
            reason = "不支持的返修动作"
        if reason:
            rejected.append({**action, "rejectedReason": reason})
        else:
            applied.append(action)
    for index, item in enumerate(result):
        item["editOrder"] = index
    return {"segments": result, "appliedActions": applied, "rejectedActions": rejected}


def review_improved(before: dict[str, Any], after: dict[str, Any]) -> bool:
    score_gain = _number(after.get("overallScore")) - _number(before.get("overallScore"))
    critical_reduced = int(after.get("criticalCount") or 0) < int(before.get("criticalCount") or 0)
    major_reduced = int(after.get("majorCount") or 0) < int(before.get("majorCount") or 0)
    introduced_critical = int(after.get("criticalCount") or 0) > int(before.get("criticalCount") or 0)
    return not introduced_critical and (score_gain >= 3.0 or critical_reduced or (major_reduced and score_gain >= 0))
