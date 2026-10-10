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
AWAITING_AGENT_PLAN = "awaiting_agent_plan"
AWAITING_AGENT_INSTRUCTION = "awaiting_agent_instruction"
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
    AWAITING_AGENT_PLAN,
    AWAITING_AGENT_INSTRUCTION,
})

CANCELLABLE_STATUSES = ACTIVE_EXECUTION_STATUSES | WAITING_USER_STATUSES
TERMINAL_STATUSES = frozenset({COMPLETED, CANCELLED, FAILED})
BACKGROUND_ACTIVE_STATUSES = frozenset({"queued", "running", "cancelling"})


def job_status(job: dict[str, Any]) -> str:
    return str(job.get("status") or "")


def background_status(job: dict[str, Any]) -> str:
    auto = job.get("autoComposition")
    if not isinstance(auto, dict):
        return ""
    return str(auto.get("status") or "")


def has_background_execution(job: dict[str, Any]) -> bool:
    return background_status(job) in BACKGROUND_ACTIVE_STATUSES


def has_active_execution(job: dict[str, Any]) -> bool:
    return job_status(job) in ACTIVE_EXECUTION_STATUSES or has_background_execution(job)


def can_cancel(job: dict[str, Any]) -> bool:
    return has_active_execution(job) or job_status(job) in CANCELLABLE_STATUSES


def can_delete(job: dict[str, Any]) -> bool:
    return not has_active_execution(job)


_STATUS_MEMORY: dict[str, str] = {}


def audit_status_transition(job: dict[str, Any], *, logger: object = None) -> None:
    """Report undeclared statuses and terminal-state resurrections.

    Advisory only. An unexpected transition is logged so it can be found, never
    blocked, because this table cannot be assumed complete.
    """
    job_id = str(job.get("id") or "")
    if not job_id:
        return
    new_status = job_status(job)
    declared = (
        new_status in TERMINAL_STATUSES
        or new_status in ACTIVE_EXECUTION_STATUSES
        or new_status in WAITING_USER_STATUSES
    )
    if not declared and logger is not None:
        logger.warning("任务 %s 的状态 %r 不在声明的状态表中", job_id, new_status)
    old_status = _STATUS_MEMORY.get(job_id)
    if old_status in TERMINAL_STATUSES and new_status not in TERMINAL_STATUSES:
        if logger is not None:
            logger.warning(
                "任务 %s 从终态 %s 回到了非终态 %s", job_id, old_status, new_status,
            )
    _STATUS_MEMORY[job_id] = new_status


def forget_status_memory(job_id: str) -> None:
    _STATUS_MEMORY.pop(str(job_id or ""), None)


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
