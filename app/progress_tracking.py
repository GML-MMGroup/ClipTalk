from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def stage_progress_for(
    stage: str,
    overall: float,
    detail: str = "",
    *,
    completed: Any = None,
    total: Any = None,
    fraction: Any = None,
) -> float | None:
    """Return measured stage progress from facts, never from presentation prose."""
    del overall, detail
    measured_fraction = _finite_number(fraction)
    if measured_fraction is not None:
        return max(0.0, min(1.0, measured_fraction))
    measured_completed = _finite_number(completed)
    measured_total = _finite_number(total)
    if measured_completed is not None and measured_total is not None and measured_total > 0:
        return max(0.0, min(1.0, measured_completed / measured_total))
    if stage in {"completed", "awaiting_confirmation", "content_search_ready", "edit_planning_complete"}:
        return 1.0
    return None


def structured_progress(
    job: dict[str, Any],
    *,
    stage: str,
    overall: float,
    detail: str,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize progress facts so the UI never has to parse status prose."""
    now = _now_iso()
    now_value = datetime.now(timezone.utc)
    previous_stage = str(job.get("stage") or "")
    stage_started_at = str(job.get("stageStartedAt") or "")
    if previous_stage != stage or not stage_started_at:
        stage_started_at = now
    text = str(detail or "")
    measured = facts if isinstance(facts, dict) else {}
    completed = _finite_number(measured.get("completed"))
    total = _finite_number(measured.get("total"))
    if completed is not None and completed.is_integer():
        completed = int(completed)
    if total is not None and total.is_integer():
        total = int(total)
    if total is None or total <= 0:
        completed = total = None
    unit = str(measured.get("unit") or "")
    current_item_index = _finite_number(measured.get("currentItemIndex"))
    finalizing = bool(measured.get("finalizing"))
    progress_mode = "finalizing" if finalizing else ("determinate" if completed is not None and total else "indeterminate")
    model = {
        "speech_recognition": "SenseVoice", "speech_analysis": "SenseVoice",
        "content_recognition": "多模态识别",
        "coarse_vlm": "VLM", "refine_vlm": "VLM", "event_grouping": "VLM", "event_director": "VLM",
        "edit_planning": "LLM", "auto_composition": "LLM + VLM", "rendering": "FFmpeg",
    }.get(stage, "系统")
    started = job.get("startedAt") or job.get("createdAt")
    try:
        elapsed = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(str(started).replace("Z", "+00:00"))).total_seconds())
    except (TypeError, ValueError):
        elapsed = 0.0

    # Counted model stages report the item currently being processed (for
    # example 2/5), not the number already finished. Observe transitions from
    # one item to the next and learn the real average duration from those
    # completed units. This is substantially more useful than extrapolating a
    # long early model request from the weighted overall percentage.
    same_stage = previous_stage == stage
    observed_index = int(job.get("stageObservedIndex") or 0) if same_stage else 0
    sample_count = int(job.get("stageSampleCount") or 0) if same_stage else 0
    average_seconds = float(job.get("stageAverageSeconds") or 0.0) if same_stage else 0.0
    unit_started_at = str(job.get("stageUnitStartedAt") or "") if same_stage else ""
    try:
        unit_started_value = datetime.fromisoformat(unit_started_at.replace("Z", "+00:00")) if unit_started_at else now_value
    except (TypeError, ValueError):
        unit_started_value = now_value
        unit_started_at = now
    if completed is not None and total:
        current_index = max(1, min(int(current_item_index if current_item_index is not None else completed), int(total)))
        if not same_stage or observed_index <= 0:
            observed_index = current_index
            unit_started_at = now
            unit_started_value = now_value
            sample_count = 0
            average_seconds = 0.0
        elif current_index > observed_index:
            finished_units = current_index - observed_index
            sample_seconds = max(0.1, (now_value - unit_started_value).total_seconds()) / finished_units
            average_seconds = (
                (average_seconds * sample_count + sample_seconds * finished_units)
                / max(1, sample_count + finished_units)
            )
            sample_count += finished_units
            observed_index = current_index
            unit_started_at = now
            unit_started_value = now_value

    eta = None
    eta_mode = "collecting"
    if finalizing:
        eta_mode = "finalizing"
    elif completed is not None and total and average_seconds > 0 and sample_count > 0:
        current_unit_elapsed = max(0.0, (now_value - unit_started_value).total_seconds())
        current_unit_remaining = max(0.0, average_seconds - current_unit_elapsed)
        later_units = max(0, int(total) - int(observed_index))
        eta = round(max(0.0, min(86400.0, current_unit_remaining + later_units * average_seconds)))
        eta_mode = "stage_average"
    elif completed is not None and total:
        eta_mode = "waiting_first_sample"
    elif overall > 0.03 and elapsed > 20:
        # A weighted pipeline milestone is not evidence of work throughput.
        # Deriving ETA from it makes the estimate grow while a model request is
        # waiting, so uncounted remote stages intentionally remain unestimated.
        eta_mode = "unavailable"
    return {
        "stageStartedAt": stage_started_at,
        "lastProgressAt": now,
        "stageCompleted": completed,
        "stageTotal": total,
        "stageUnit": unit,
        "currentAction": text,
        "model": model,
        "progressMode": progress_mode,
        "etaSeconds": eta,
        "etaMode": eta_mode,
        "stageObservedIndex": observed_index if completed is not None and total else None,
        "stageUnitStartedAt": unit_started_at if completed is not None and total else None,
        "stageAverageSeconds": round(average_seconds, 3) if average_seconds > 0 else None,
        "stageSampleCount": sample_count if completed is not None and total else 0,
    }
