from __future__ import annotations

from typing import Any


def _review_preview_count(job: dict[str, Any]) -> int:
    values = [
        *(job.get("agentReviewPreviews") or []),
        *(job.get("agentPreviewOutputs") or []),
    ]
    identities = {
        str(item.get("filename") or item.get("previewUrl") or item.get("sessionId") or item.get("id") or "")
        for item in values
        if isinstance(item, dict)
    }
    identities.discard("")
    version_previews = sum(
        len(version.get("outputs") or [])
        for version in job.get("outputVersions") or []
        if isinstance(version, dict) and bool(version.get("previewOnly"))
    )
    return max(len(identities), version_previews)


def _formal_output_count(job: dict[str, Any]) -> int:
    versions = job.get("outputVersions") if isinstance(job.get("outputVersions"), list) else []
    if versions:
        return sum(
            1
            for version in versions if isinstance(version, dict) and not bool(version.get("previewOnly"))
            for output in version.get("outputs") or []
            if isinstance(output, dict) and not bool(output.get("previewOnly"))
        )
    return sum(
        1 for output in job.get("outputs") or []
        if isinstance(output, dict) and not bool(output.get("previewOnly"))
    )


def ui_presentation_snapshot(
    job: dict[str, Any],
    *,
    workflow: dict[str, Any],
    execution: dict[str, Any],
    output_count: int,
) -> dict[str, Any]:
    """Return the complete, directly renderable workspace presentation.

    Raw job, workflow and execution states remain available for diagnostics,
    but browser surfaces should render these fields instead of rebuilding the
    same precedence rules independently.
    """
    agent = job.get("agent") if isinstance(job.get("agent"), dict) else {}
    status = str(execution.get("status") or job.get("status") or "")
    raw_status = str(job.get("status") or "")
    stage = str(job.get("stage") or "")
    agent_status = str(agent.get("status") or agent.get("workspaceStatus") or "")
    previews = _review_preview_count(job)
    formal_outputs = _formal_output_count(job)
    quality = agent.get("quality") if isinstance(agent.get("quality"), dict) else {
        "status": "not_run", "passed": None, "issues": [],
    }
    progress = {
        "successful": max(0, int(agent.get("successfulSteps") or 0)),
        "skipped": max(0, int(agent.get("skippedSteps") or 0)),
        "settled": max(0, int(agent.get("settledSteps") or agent.get("completedSteps") or 0)),
        "total": max(0, int(agent.get("totalSteps") or 0)),
        "currentStepId": str(agent.get("currentStepId") or ""),
        "currentStepTitle": str(agent.get("currentStepTitle") or ""),
    }
    artifact_stage = "formal_output" if formal_outputs else "review_preview" if previews else "none"

    def result(key: str, **values: Any) -> dict[str, Any]:
        journey = {
            "waiting_instruction": 0, "plan_planning": 1, "plan_confirmation": 1,
            "running": 2, "content_review": 2, "preview_review": 3,
            "export_running": 4, "handed_off": 2,
            "exported": 4 if formal_outputs else 3 if previews else 1,
            "failed": 3 if formal_outputs or previews else 2,
            "cancelled": 3 if formal_outputs or previews else 2,
            "no_result": 2,
        }.get(key, 0)
        action = values.get("primaryActionKey")
        attention = []
        if values.get("group") in {"action_required", "failed", "no_result", "cancelled", "handed_off"}:
            attention.append({"label": values.get("headline"), "actionKey": action,
                              "tab": "materials" if journey == 3 else None, "target": "#agentPlanDock"})
        if quality.get("status") in {"warning", "failed"}:
            attention.append({"label": "查看质量提醒并定位问题片段", "actionKey": "review_quality",
                              "target": ".agent-qc-summary, .quality-gate-result-card, #agentPlanDock", "tab": None})
        return {
            "schemaVersion": 4,
            "key": key,
            "outputCount": formal_outputs,
            "previewCount": previews,
            "executionProgress": progress,
            "quality": quality,
            "artifactStage": artifact_stage,
            "journeyStage": journey,
            "journeyDetail": values.get("detail", ""),
            "attentionItems": attention,
            "availableActions": [action] if action else [],
            **values,
        }

    # Agent review state takes precedence over an older formal output and over
    # legacy jobs that persisted preview_ready as outer status=completed.
    operations = list((job.get("renderOperations") or {}).values())
    active_export = any(item.get("status") in {"queued", "running"} for item in operations) or (execution.get("active") or raw_status in {"running", "rendering"}) and (
        execution.get("operation") in {"render", "export", "secondary_edit_rendering"}
        or stage in {"rendering", "render"}
    )
    formal_versions = [version for version in job.get("outputVersions") or []
                       if version.get("outputs") and not version.get("previewOnly")]
    delivered_ids = {version.get("id") for version in formal_versions}
    delivered_plan = bool(agent.get("planId")) and any(
        operation.get("status") == "completed" and operation.get("agentPlanId") == agent.get("planId")
        and delivered_ids.intersection(operation.get("resultVersionIds") or []) for operation in operations)
    previews_to_review = job.get("agentReviewPreviews") or []
    # A newer preview in the same plan still needs review; artifact lineage is
    # more specific than the plan-level fallback used for legacy records.
    if previews_to_review:
        delivered_plan = False
    delivered_lineage = bool(previews_to_review) and all(any(
        version.get("editSessionId") == (preview.get("sourceEditSessionId") or preview.get("sessionId"))
        and version.get("editSessionId")
        and version.get("editSessionRevision") == preview.get("revision")
        for version in formal_versions) for preview in previews_to_review)
    if agent_status == "preview_ready" and not active_export and not delivered_plan and not delivered_lineage:
        quality_status = str(quality.get("status") or "not_run")
        if quality_status == "failed":
            return result(
                "preview_review", group="action_required", label="审核样片待修正",
                headline="执行完成 · 质检未通过",
                detail="样片已保留；请修正质检问题后重新检查。",
                railTitle="样片质检", running=False, tone="attention",
                primaryActionKey="repair_and_recheck",
            )
        if quality_status == "warning":
            return result(
                "preview_review", group="action_required", label="审核样片有质量提醒",
                headline="执行完成 · 建议人工复核",
                detail="样片已保留；完整播放并确认风险后可生成正式视频。",
                railTitle="样片复核", running=False, tone="attention",
                primaryActionKey="export_formal",
            )
        return result(
            "preview_review", group="action_required", label="审核样片已就绪 · 待确认导出",
            headline="执行完成 · 审核样片已就绪",
            detail="预览剪辑效果，满意后生成成片。",
            railTitle="审核样片", running=False, tone="success",
            primaryActionKey="export_formal",
        )

    if not active_export and (delivered_plan or delivered_lineage):
        return result("exported", group="completed", label="正式视频已生成", headline="正式视频已生成",
                      detail="成片已就绪，可以预览或下载。", railTitle="成片已就绪",
                      running=False, tone="success", primaryActionKey="download")
    handoff_job_id = str(job.get("agentHandoffJobId") or (job.get("latestHandoff") or {}).get("toJobId") or "")
    if stage == "agent_handed_off" and handoff_job_id:
        return result(
            "handed_off", group="handed_off", label="历史处理记录", headline="这是一条历史处理记录",
            detail="打开当前任务查看最新进度与结果。", railTitle="历史记录", running=False,
            tone="neutral", primaryActionKey="open_handoff", handoffJobId=handoff_job_id,
        )
    if status == "cancelled" or agent_status == "cancelled" or "cancelled" in stage:
        return result(
            "cancelled", group="cancelled", label="已取消", headline="任务已取消",
            detail=f"已保留 {output_count} 条已有版本。" if output_count else "素材仍在，可以修改要求后重新开始。",
            railTitle="任务已取消", running=False, tone="neutral", primaryActionKey="restart",
        )
    if status == "failed" or agent_status == "failed" or stage == "agent_plan_failed" or stage.endswith("_failed"):
        error = job.get("error")
        if isinstance(error, dict):
            error_detail = error.get("message") or error.get("detail")
        else:
            error_detail = error
        generation_text = f"{job.get('detail') or ''} {error_detail or ''} {job.get('currentAction') or ''}".lower()
        generation_failure = (
            raw_status == "failed"
            and str(job.get("taskMode") or "") == "content_extract"
            and any(term in generation_text for term in ("生成", "渲染", "合成", "编码", "edl"))
        )
        workflow_kind = str(job.get("workflowKind") or (job.get("request") or {}).get("workflowKind") or "")
        failure_label = "处理失败"
        if generation_failure:
            failure_label = (
                "人物剪辑生成失败" if workflow_kind == "person_edit"
                else "说话人剪辑生成失败" if workflow_kind == "speaker_edit"
                else "内容视频生成失败"
            )
        return result(
            "failed", group="failed", label=failure_label,
            headline="视频生成没有完成" if generation_failure else "任务没有完成",
            detail=str(error_detail or job.get("detail") or "可查看失败步骤并从已保存的素材继续。"),
            railTitle="任务未完成", running=False, tone="danger", primaryActionKey="retry",
        )
    if agent_status == "no_result" or stage == "agent_no_result" or execution.get("outcome") == "no_result":
        return result(
            "no_result", group="no_result", label="未找到内容", headline="没有找到可靠匹配",
            detail=str(job.get("detail") or "素材已保留。可以放宽条件、换一种描述或选择其他剪辑方式。"),
            railTitle="没有匹配结果", running=False, tone="neutral", primaryActionKey="revise_instruction",
        )
    if raw_status == "awaiting_agent_instruction" or (job.get("agentDraft") and not job.get("instructionSubmitted")):
        return result(
            "waiting_instruction", group="draft", label="待输入剪辑要求", headline="素材已就绪",
            detail="描述想保留的内容，或选择一种快速剪辑方式。",
            railTitle="等待剪辑要求", running=False, tone="neutral", primaryActionKey="focus_composer",
        )
    if raw_status == "brief_confirmation" or execution.get("actionRequired") == "confirm_brief":
        return result(
            "plan_confirmation", group="action_required", label="等待确认剪辑需求", headline="剪辑需求已整理",
            detail="确认目标、重点和时长后再开始读取视频内容。",
            railTitle="需求确认", running=False, tone="attention", primaryActionKey="confirm_brief",
        )
    if raw_status == "awaiting_model_decision" or execution.get("actionRequired") == "resolve_model_stage":
        return result(
            "content_review", group="action_required", label="需要处理模型阶段", headline="分析在检查点暂停",
            detail="选择重试、降级继续或停止；已完成的结果会保留。",
            railTitle="等待处理", running=False, tone="attention", primaryActionKey="review_action",
        )
    if raw_status == "awaiting_agent_plan":
        completed = max(0, int(agent.get("completedSteps") or 0))
        total = max(0, int(agent.get("totalSteps") or 0))
        if agent_status == "awaiting_confirmation":
            return result(
                "plan_confirmation", group="action_required", label="请确认剪辑计划", headline="计划已生成，等待确认",
                detail="核对目标、素材范围和人工确认点后再开始执行。",
                railTitle="确认执行计划", running=False, tone="attention", primaryActionKey="confirm_plan",
            )
        if agent_status == "action_required":
            title = str(agent.get("currentStepTitle") or "当前步骤")
            return result(
                "content_review", group="action_required", label=f"需要确认：{title}", headline=title,
                detail="完成当前选择后，Agent 会继续执行余下步骤。",
                railTitle="等待确认", running=False, tone="attention", primaryActionKey="review_action",
            )
        if previews and agent_status not in {"approved", "running"}:
            suffix = f" · {previews} 个" if previews else ""
            return result(
                "preview_review", group="action_required", label=f"审核样片已生成{suffix}", headline="审核样片已生成",
                detail="先预览时间线；确认后生成高清新版本，当前样片会保留。",
                railTitle="审核样片", running=False, tone="success", primaryActionKey="review_preview",
            )
        if agent_status in {"approved", "running"}:
            suffix = f" · {min(completed, total)}/{total} 步" if total else ""
            return result(
                "running", group="active", label=f"Agent 正在执行{suffix}",
                headline=str(agent.get("currentStepTitle") or "正在执行剪辑计划"),
                detail=f"已完成 {min(completed, total)}/{total} 步。" if total else "结果会写入当前任务。",
                railTitle="执行剪辑计划", running=True, tone="active", primaryActionKey="view_activity",
            )
        return result(
            "plan_planning", group="agent_planning", label="正在生成剪辑计划", headline="正在规划剪辑步骤",
            detail="当前只整理目标、工具与确认点，不会静默修改素材。",
            railTitle="生成执行计划", running=True, tone="active", primaryActionKey="view_activity",
        )

    operation = str(execution.get("operation") or "")
    if (execution.get("active") or status in {"running", "rendering"}) and operation in {
        "render", "auto_composition", "quality_review", "secondary_edit_rendering", "export",
    }:
        return result(
            "export_running", group="active", label="正在生成正式视频", headline="正在生成正式新版本",
            detail="已有版本保持不变，完成后会新增一个版本。" if output_count else "完成后可直接预览和下载。",
            railTitle="生成正式视频", running=True, tone="active", primaryActionKey="view_activity",
        )
    if execution.get("outcome") == "no_acceptable_output":
        rejected_count = max(0, int((execution.get("result") or {}).get("qualityRejectedCount") or 0))
        suffix = f" · {rejected_count} 个样片待人工检查" if rejected_count else ""
        return result(
            "no_result", group="action_required", label=f"自动成片未通过质量门{suffix}",
            headline="自动成片需要人工检查",
            detail="候选片段和未通过的样片均已保留，可以调整后重新生成。",
            railTitle="质量检查", running=False, tone="attention", primaryActionKey="review_content",
        )
    if (
        raw_status in {"awaiting_content_confirmation", "awaiting_confirmation"}
        or execution.get("actionRequired") in {"review_content", "review_highlights"}
    ):
        content_review = raw_status == "awaiting_content_confirmation" or execution.get("actionRequired") == "review_content"
        return result(
            "content_review", group="action_required",
            label="等待确认匹配片段" if content_review else "等待审核事件与镜头",
            headline="匹配片段已就绪" if content_review else "事件与镜头已就绪",
            detail="选择要保留的内容并检查边界，然后生成审核样片。",
            railTitle="片段确认" if content_review else "事件审核",
            running=False, tone="attention", primaryActionKey="review_content",
        )
    if previews and not output_count:
        return result(
            "preview_review", group="action_required", label=f"审核样片已生成 · {previews} 个", headline="审核样片已生成",
            detail="先预览时间线；确认后生成高清新版本，当前样片会保留。",
            railTitle="审核样片", running=False, tone="success", primaryActionKey="review_preview",
        )
    if formal_outputs or execution.get("outcome") == "output_ready" or status == "completed" or raw_status == "completed":
        has_output = bool(formal_outputs or execution.get("outcome") == "output_ready")
        return result(
            "exported", group="completed",
            label=f"{formal_outputs or 1} 条正式视频已完成" if has_output else "已完成",
            headline="正式视频已完成" if has_output else "任务已完成",
            detail="可以预览、下载或基于当前版本继续精剪。" if has_output else "结果已保存，可以随时继续查看。",
            railTitle="成片版本" if has_output else "任务结果",
            running=False, tone="success", primaryActionKey="view_outputs" if has_output else "view_results",
        )
    if execution.get("active") or status in {"briefing", "queued", "running", "rendering", "cancelling"}:
        detail = str(execution.get("detail") or job.get("detail") or ("等待开始" if status == "queued" else "正在处理素材"))
        return result(
            "running", group="active", label=detail, headline="正在处理素材",
            detail=str(execution.get("detail") or job.get("detail") or "完成后会进入内容审核。"),
            railTitle="处理进度", running=status != "queued", tone="active", primaryActionKey="view_activity",
        )
    return result(
        "running", group="other", label=str(job.get("detail") or "等待继续"), headline="任务已保存",
        detail=str(job.get("detail") or "可以继续当前剪辑流程。"), railTitle="任务状态",
        running=False, tone="neutral", primaryActionKey=None,
    )
