from __future__ import annotations

from typing import Any


BRIEFING = "briefing"
BRIEF_CONFIRMATION = "brief_confirmation"
QUEUED = "queued"
RUNNING = "running"
CANCELLING = "cancelling"
AWAITING_MODEL_DECISION = "awaiting_model_decision"
AWAITING_CONFIRMATION = "awaiting_confirmation"
AWAITING_CONTENT_CONFIRMATION = "awaiting_content_confirmation"
COMPLETED = "completed"
CANCELLED = "cancelled"
FAILED = "failed"

# These states own, or may still own, an in-process worker. They cannot be
# deleted and must be recovered after an unclean service restart.
ACTIVE_EXECUTION_STATUSES = frozenset({BRIEFING, QUEUED, RUNNING, CANCELLING})

# Waiting states have no active media worker but remain user-cancellable.
WAITING_USER_STATUSES = frozenset({
    BRIEF_CONFIRMATION,
    AWAITING_MODEL_DECISION,
    AWAITING_CONFIRMATION,
    AWAITING_CONTENT_CONFIRMATION,
})

CANCELLABLE_STATUSES = ACTIVE_EXECUTION_STATUSES | WAITING_USER_STATUSES
TERMINAL_STATUSES = frozenset({COMPLETED, CANCELLED, FAILED})


def job_status(job: dict[str, Any]) -> str:
    return str(job.get("status") or "")


def has_active_execution(job: dict[str, Any]) -> bool:
    return job_status(job) in ACTIVE_EXECUTION_STATUSES


def can_cancel(job: dict[str, Any]) -> bool:
    return job_status(job) in CANCELLABLE_STATUSES


def can_delete(job: dict[str, Any]) -> bool:
    return not has_active_execution(job)


def interrupted_job_patch(*, checkpoint_available: bool, now: str) -> dict[str, Any]:
    return {
        "status": FAILED,
        "stage": "interrupted",
        "detail": (
            "服务重启导致任务中断，已保留检查点，可从中断处恢复"
            if checkpoint_available
            else "服务重启导致任务中断，可使用原素材重新分析"
        ),
        "error": "服务重启导致任务中断",
        "resumeAvailable": checkpoint_available,
        "currentAction": "任务因服务重启而中断",
        "etaSeconds": None,
        "etaMode": "stopped",
        "progressMode": "stopped",
        "interruptedAt": now,
        "updatedAt": now,
    }
