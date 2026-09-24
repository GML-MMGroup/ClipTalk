#!/usr/bin/env python3
"""Run real user prompts through ClipTalk's autonomous Agent workflow.

The validator uses only public HTTP APIs. It creates retained, editable jobs,
approves exactly one initial plan, stops at a review sample or an explicit
failure, and writes both machine-readable and human-readable diagnostics.
Formal export is never requested or confirmed by this tool.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings

TERMINAL_PLAN_STATUSES = {"preview_ready", "no_result", "failed", "cancelled"}
ACTIVE_PLAN_STATUSES = {"approved", "running", "action_required"}
NO_MATCH_PATTERN = re.compile(
    r"没有|未找到|无有效|无法生成|不足|不包含|不存在|no match|no candidate|empty",
    re.IGNORECASE,
)
LIMITATION_PATTERN = re.compile(
    r"无法|不能|不支持|冲突|不足|没有|未找到|需要|限制|no match|unsupported|constraint",
    re.IGNORECASE,
)
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compact_text(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def recursive_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(recursive_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(recursive_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def collect_artifacts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            kind = str(value.get("kind") or "")
            if kind:
                artifacts.append(value)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for step in plan.get("steps") or []:
        if isinstance(step, dict):
            visit(step.get("result"))
    return artifacts


def plan_error_text(plan: dict[str, Any]) -> str:
    values = [str(plan.get("error") or "")]
    for step in plan.get("steps") or []:
        if isinstance(step, dict):
            values.append(str(step.get("error") or ""))
    return compact_text(" ".join(value for value in values if value), 2000)


def output_aspect(output: dict[str, Any]) -> str:
    reframe = output.get("reframe") if isinstance(output.get("reframe"), dict) else {}
    explicit = str(reframe.get("aspect") or output.get("aspect") or "")
    if explicit:
        return explicit
    width = finite_number(output.get("width"))
    height = finite_number(output.get("height"))
    if not width or not height:
        return ""
    ratio = width / height
    for label, expected in (("9:16", 9 / 16), ("1:1", 1), ("16:9", 16 / 9), ("4:5", 4 / 5)):
        if abs(ratio - expected) <= 0.03:
            return label
    return f"{int(width)}:{int(height)}"


@dataclass
class Issue:
    severity: str
    code: str
    phase: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""


def add_issue(
    issues: list[Issue], severity: str, code: str, phase: str, message: str,
    *, evidence: dict[str, Any] | None = None, recommendation: str = "",
) -> None:
    issues.append(Issue(
        severity=severity, code=code, phase=phase, message=message,
        evidence=evidence or {}, recommendation=recommendation,
    ))


def evaluate_plan_contract(plan: dict[str, Any], scenario: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    skill_id = str(plan.get("skillId") or "")
    allowed_skills = [str(value) for value in scenario.get("expectedSkillAnyOf") or []]
    if allowed_skills and skill_id not in allowed_skills:
        add_issue(
            issues, "error", "plan.skill_mismatch", "planning",
            f"Agent 选择了与场景预期不一致的 Skill：{skill_id or '空'}。",
            evidence={"actual": skill_id, "expectedAnyOf": allowed_skills},
            recommendation="检查 Skill 路由特征、场景前置条件和多约束请求的优先级。",
        )
    if str(plan.get("executionMode") or "") != "autonomous_review":
        add_issue(
            issues, "error", "plan.execution_mode_mismatch", "planning",
            "计划没有使用自动执行到审核样片模式。",
            evidence={"executionMode": plan.get("executionMode")},
        )
    steps = [step for step in plan.get("steps") or [] if isinstance(step, dict)]
    if not steps:
        add_issue(issues, "error", "plan.empty", "planning", "Agent 返回了空执行计划。")
        return issues
    forbidden_tools = {str(value) for value in scenario.get("forbiddenTools") or [] if str(value)}
    used_forbidden = [
        str(step.get("tool") or "") for step in steps
        if str(step.get("tool") or "") in forbidden_tools
    ]
    if used_forbidden:
        add_issue(
            issues, "error", "plan.forbidden_tool", "planning",
            "计划包含用户明确禁止的分析或产物步骤。",
            evidence={"tools": used_forbidden},
            recommendation="否定句中的成片、封面、字幕和审核样片只能作为禁止约束，不能触发对应工具。",
        )
    formal_tools = [
        str(step.get("tool") or "") for step in steps
        if "formal" in str(step.get("tool") or "").lower()
        or str(step.get("tool") or "") in {"export_video", "render_final", "publish_output"}
    ]
    if formal_tools:
        add_issue(
            issues, "error", "plan.formal_export_included", "planning",
            "审核测试计划中包含正式导出或发布步骤。",
            evidence={"tools": formal_tools},
            recommendation="审核样片和正式导出必须保持独立确认边界。",
        )
    side_effects = [str(step.get("sideEffect") or "") for step in steps]
    if "formal_export" in side_effects:
        add_issue(
            issues, "error", "plan.formal_side_effect", "planning",
            "计划声明了正式导出副作用。", evidence={"sideEffects": side_effects},
        )
    return issues


def _session_duration(session: dict[str, Any]) -> float | None:
    explicit = finite_number(session.get("duration"))
    if explicit and explicit > 0:
        return explicit
    schedule = [item for item in session.get("schedule") or [] if isinstance(item, dict)]
    ends = [finite_number(item.get("outputEnd")) for item in schedule]
    valid = [value for value in ends if value is not None]
    return max(valid) if valid else None


def _selected_session(job: dict[str, Any]) -> dict[str, Any] | None:
    sessions = [item for item in job.get("editSessions") or [] if isinstance(item, dict)]
    active_id = str(job.get("activeEditSessionId") or "")
    return next((item for item in sessions if str(item.get("id") or "") == active_id), None) or (
        sessions[-1] if sessions else None
    )


def _preview_outputs(plan: dict[str, Any], job: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = [
        item for item in [
            *(job.get("agentReviewPreviews") or []),
            *(job.get("agentPreviewOutputs") or []),
        ]
        if isinstance(item, dict)
    ]
    seen = {str(item.get("previewUrl") or item.get("filename") or "") for item in outputs}
    for artifact in collect_artifacts(plan):
        candidates: list[dict[str, Any]] = []
        if str(artifact.get("kind") or "") == "review_preview":
            candidates = [artifact]
        elif isinstance(artifact.get("previews"), list):
            candidates = [item for item in artifact["previews"] if isinstance(item, dict)]
        elif isinstance(artifact.get("output"), dict):
            candidates = [artifact["output"]]
        for item in candidates:
            key = str(item.get("previewUrl") or item.get("filename") or "")
            if key and key not in seen:
                seen.add(key)
                outputs.append(item)
    return outputs


def _projected_preview_outputs(job: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = [
        item for item in [
            *(job.get("agentReviewPreviews") or []),
            *(job.get("agentPreviewOutputs") or []),
            *(job.get("outputs") or []),
        ]
        if isinstance(item, dict)
        and (item.get("previewOnly") is True or item.get("previewUrl") or item.get("videoUrl") or item.get("filename"))
    ]
    for version in job.get("outputVersions") or []:
        if not isinstance(version, dict):
            continue
        outputs.extend(
            item for item in [
                *(version.get("outputs") or []),
                *(version.get("previewOutputs") or []),
            ]
            if isinstance(item, dict)
            and (item.get("previewOnly") is True or item.get("previewUrl") or item.get("videoUrl") or item.get("filename"))
        )
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in outputs:
        key = str(item.get("previewUrl") or item.get("videoUrl") or item.get("filename") or item.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _formal_outputs(job: dict[str, Any]) -> list[dict[str, Any]]:
    versions = [item for item in job.get("outputVersions") or [] if isinstance(item, dict)]
    version_by_id = {
        str(item.get("id") or item.get("versionId") or ""): item
        for item in versions
        if str(item.get("id") or item.get("versionId") or "")
    }
    active_version = next((
        item for item in versions
        if str(item.get("id") or item.get("versionId") or "")
        == str(job.get("activeOutputVersionId") or job.get("outputVersionId") or "")
    ), None)
    if active_version is None and versions:
        active_version = versions[-1]

    def is_formal(output: dict[str, Any], version: dict[str, Any] | None = None) -> bool:
        owner = version_by_id.get(str(output.get("versionId") or "")) or version or active_version
        kind = str(output.get("variantKind") or (owner or {}).get("variantKind") or "")
        if kind == "formal_export":
            return True
        if "previewOnly" in output:
            return output.get("previewOnly") is False
        return isinstance(owner, dict) and owner.get("previewOnly") is False

    outputs = [
        item for item in job.get("outputs") or []
        if isinstance(item, dict) and is_formal(item)
    ]
    for version in versions:
        if not is_formal({}, version):
            continue
        outputs.extend(
            item for item in version.get("outputs") or []
            if isinstance(item, dict) and is_formal(item, version)
        )
    return outputs


def evaluate_terminal_state(
    plan: dict[str, Any], job: dict[str, Any], workspace: dict[str, Any],
    scenario: dict[str, Any], transitions: list[dict[str, Any]],
) -> list[Issue]:
    issues: list[Issue] = []
    status = str(plan.get("status") or "")
    expected = str(scenario.get("expectedOutcome") or "preview_ready")
    error_text = plan_error_text(plan)
    previews = _preview_outputs(plan, job)
    session = _selected_session(job)
    sessions = [item for item in job.get("editSessions") or [] if isinstance(item, dict)]
    steps = [step for step in plan.get("steps") or [] if isinstance(step, dict)]
    failed_steps = [step for step in steps if str(step.get("status") or "") == "failed"]
    if bool(scenario.get("forbidImplicitDuration")):
        brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
        request_state = job.get("request") if isinstance(job.get("request"), dict) else {}
        observed_targets = [
            finite_number(brief.get("targetSeconds")),
            finite_number(job.get("targetSeconds")),
            finite_number(job.get("totalTargetSeconds")),
            finite_number(request_state.get("targetSeconds")),
            finite_number(request_state.get("totalTargetSeconds")),
            *[
                finite_number((step.get("arguments") or {}).get("targetSeconds"))
                for step in steps if isinstance(step.get("arguments"), dict)
            ],
        ]
        observed_targets = [value for value in observed_targets if value is not None]
        if observed_targets:
            add_issue(
                issues, "error", "plan.implicit_duration", "plan",
                "用户未指定成片时长，但计划或任务状态写入了硬性时长目标。",
                evidence={"observedTargetSeconds": observed_targets},
                recommendation=(
                    "只把用户明确给出的总时长写入 targetSeconds；"
                    "短视频和画幅词不能推导硬时长。"
                ),
            )
    for step in failed_steps:
        error = compact_text(step.get("error"), 900)
        is_expected_no_match = expected == "graceful_no_match" and bool(NO_MATCH_PATTERN.search(error))
        if is_expected_no_match:
            continue
        add_issue(
            issues, "error", "execution.step_failed", "execution",
            f"计划步骤“{step.get('title') or step.get('tool')}”执行失败。",
            evidence={
                "tool": step.get("tool"), "attempts": step.get("attempts"),
                "error": error,
            },
            recommendation="修复该工具的输入归一化或执行异常，并确保失败不会继续触发下游操作。",
        )

    expected_artifact_kind = str(scenario.get("expectedArtifactKind") or "")
    artifacts = collect_artifacts(plan)
    if expected == "artifact_ready":
        artifact_found = bool(expected_artifact_kind) and any(
            str(artifact.get("kind") or "") == expected_artifact_kind
            for artifact in artifacts
        )
        if status != "preview_ready" or not artifact_found:
            add_issue(
                issues, "error", "execution.artifact_not_ready", "execution",
                "工件型场景没有执行到完成状态，或没有产生期望工件。",
                evidence={
                    "planStatus": status,
                    "expectedArtifactKind": expected_artifact_kind,
                    "artifactKinds": [str(item.get("kind") or "") for item in artifacts],
                    "error": error_text,
                },
                recommendation="非视频预览类 Skill 应返回可追踪 artifact，并让计划进入完成状态。",
            )
    elif expected == "preview_ready" and status != "preview_ready":
        add_issue(
            issues, "error", "execution.review_not_ready", "execution",
            "正常场景没有执行到审核样片。",
            evidence={"planStatus": status, "error": error_text},
            recommendation="沿失败步骤检查候选、时间线应用和审核渲染链路。",
        )
    elif expected == "graceful_no_match":
        graceful = status == "no_result" or (
            status == "failed" and bool(NO_MATCH_PATTERN.search(error_text))
        )
        if not graceful:
            add_issue(
                issues, "error", "execution.no_match_not_graceful", "execution",
                "不存在内容场景没有以明确、可理解的无结果状态停止。",
                evidence={"planStatus": status, "error": error_text, "previewCount": len(previews)},
                recommendation="无有效候选时应停止后续时间线和渲染，并返回具体原因。",
            )
        if sessions or previews:
            add_issue(
                issues, "error", "execution.irrelevant_artifact", "execution",
                "无匹配场景仍然建立了时间线或生成了样片。",
                evidence={"sessionCount": len(sessions), "previewCount": len(previews)},
                recommendation="候选为空时不得应用空时间线或用无关片段补足目标时长。",
            )
    elif expected == "preview_or_clear_limitation":
        clear_failure = status == "no_result" or (
            status == "failed" and bool(LIMITATION_PATTERN.search(error_text))
        )
        if status != "preview_ready" and not clear_failure:
            add_issue(
                issues, "error", "execution.constraint_unresolved", "execution",
                "复杂约束场景既没有生成审核样片，也没有清楚说明限制。",
                evidence={"planStatus": status, "error": error_text},
            )

    action_steps = [step for step in steps if str(step.get("status") or "") == "action_required"]
    if action_steps or status == "action_required" or any(item.get("planStatus") == "action_required" for item in transitions):
        add_issue(
            issues, "error", "execution.unexpected_confirmation", "execution",
            "自动模式在初始计划确认后再次要求用户参与。",
            evidence={"steps": [str(step.get("title") or step.get("tool") or "") for step in action_steps]},
            recommendation="autonomous_review 应自动完成候选选择、时间线应用和审核样片生成。",
        )
    repeated = [
        {"tool": step.get("tool"), "title": step.get("title"), "attempts": step.get("attempts")}
        for step in steps if int(step.get("attempts") or 0) > 2
    ]
    retried = [
        {"tool": step.get("tool"), "title": step.get("title"), "attempts": step.get("attempts")}
        for step in steps if int(step.get("attempts") or 0) == 2
    ]
    if repeated:
        add_issue(
            issues, "error", "execution.replan_loop", "execution",
            "同一计划步骤重复执行超过两次。", evidence={"steps": repeated},
            recommendation="对确定性无结果设置重试上限，重规划必须改变查询或策略。",
        )
    elif retried:
        add_issue(
            issues, "warning", "execution.step_retried", "execution",
            "计划包含一次自动重试。", evidence={"steps": retried},
        )

    preview_step_present = any(
        str(step.get("tool") or "") in {"render_review_preview", "render_social_preview"}
        for step in steps
    )
    evidence_only_result = bool(
        not preview_step_present
        and any(
            str((step.get("result") or {}).get("artifact", {}).get("kind") or "")
            in {"content_search_result", "speaker_scoped_content_search"}
            for step in steps if isinstance(step.get("result"), dict)
        )
    )
    if (
        status == "preview_ready" and expected != "artifact_ready" and not previews
        and not evidence_only_result
    ):
        add_issue(
            issues, "error", "artifact.preview_missing", "artifact",
            "计划标记为审核就绪，但没有可读取的审核样片工件。",
        )
    if (
        status == "preview_ready"
        and expected != "artifact_ready"
        and previews
        and not evidence_only_result
        and not _projected_preview_outputs(job)
    ):
        add_issue(
            issues, "error", "artifact.preview_not_projected", "artifact",
            "审核样片只存在于 Agent 计划结果中，没有投影到任务公开结果区。",
            evidence={
                "planPreviewCount": len(previews),
                "jobAgentReviewPreviews": len(job.get("agentReviewPreviews") or []),
                "jobAgentPreviewOutputs": len(job.get("agentPreviewOutputs") or []),
                "outputVersionCount": len(job.get("outputVersions") or []),
            },
            recommendation="把 Agent 审核样片写入任务快照，前端才能在结果区展示可点击入口。",
        )
    formal = _formal_outputs(job)
    if formal:
        add_issue(
            issues, "error", "artifact.formal_output_created", "artifact",
            "测试在没有正式导出确认的情况下生成了正式输出。",
            evidence={"filenames": [item.get("filename") for item in formal]},
            recommendation="正式输出必须保留独立人工确认。",
        )

    target = scenario.get("targetDuration") if isinstance(scenario.get("targetDuration"), dict) else {}
    minimum = finite_number(target.get("minimum"))
    maximum = finite_number(target.get("maximum"))
    duration_candidates = [
        finite_number(item.get("duration")) for item in previews
        if finite_number(item.get("duration")) is not None
    ]
    session_duration = _session_duration(session or {})
    if session_duration is not None:
        duration_candidates.append(session_duration)
    duration = duration_candidates[0] if duration_candidates else None
    if status == "preview_ready" and minimum is not None and maximum is not None:
        if duration is None:
            add_issue(
                issues, "warning", "artifact.duration_unknown", "artifact",
                "审核样片和时间线都没有可验证的时长。",
            )
        elif duration < minimum - 0.05 or duration > maximum + 0.05:
            add_issue(
                issues, "error", "artifact.target_duration_mismatch", "artifact",
                f"审核结果时长 {duration:.2f} 秒不在目标范围 {minimum:.2f}–{maximum:.2f} 秒内。",
                evidence={"actual": duration, "minimum": minimum, "maximum": maximum},
                recommendation="候选编排和时间线拟合必须共同遵守总时长约束。",
            )

    expected_aspect = str(scenario.get("expectedAspect") or "")
    if status == "preview_ready" and expected_aspect:
        aspects = [output_aspect(item) for item in previews if output_aspect(item)]
        if not aspects:
            info = job.get("videoInfo") if isinstance(job.get("videoInfo"), dict) else {}
            aspects = [output_aspect(info)] if output_aspect(info) else []
        if expected_aspect not in aspects:
            add_issue(
                issues, "error", "artifact.aspect_mismatch", "artifact",
                f"审核结果没有生成要求的 {expected_aspect} 画幅。",
                evidence={"expected": expected_aspect, "observed": aspects},
                recommendation="画幅要求必须进入社媒预览步骤并写入输出元数据。",
            )
    if status == "preview_ready" and bool(scenario.get("expectedCoverIntro")):
        has_cover_intro = any(
            isinstance(output.get("coverIntro"), dict)
            and bool(output.get("coverIntro", {}).get("enabled"))
            for output in previews
        )
        if not has_cover_intro:
            add_issue(
                issues, "error", "artifact.cover_intro_missing", "artifact",
                "用户要求封面放在开头，但审核结果没有可追踪的封面片头。",
                evidence={
                    "previewFilenames": [item.get("filename") or item.get("previewUrl") for item in previews],
                    "previewKinds": [item.get("outputKind") or item.get("kind") for item in previews],
                },
                recommendation="保存封面后应生成带当前任务封面片头的审核预览，并在后续画幅预览中继承 coverIntro 元数据。",
            )

    if status == "preview_ready":
        result_text = recursive_text({"plan": plan, "session": session})
        missing_terms = [term for term in scenario.get("expectedTerms") or [] if str(term).lower() not in result_text.lower()]
        if missing_terms:
            add_issue(
                issues, "warning", "semantic.request_terms_untraceable", "semantic",
                "部分用户目标没有出现在计划结果或时间线证据中。",
                evidence={"missingTerms": missing_terms},
                recommendation="在候选和时间线片段上保留目标类别、命中证据和来源关系。",
            )

    for artifact in collect_artifacts(plan):
        if str(artifact.get("kind") or "") != "delivery_qc_report":
            continue
        for report in artifact.get("reports") or []:
            if not isinstance(report, dict):
                continue
            for value in report.get("issues") or []:
                if not isinstance(value, dict):
                    continue
                issue_code = str(value.get("code") or "issue")
                source_passthrough = bool(
                    isinstance(plan.get("brief"), dict)
                    and plan["brief"].get("formatOnly")
                )
                # A pure aspect conversion preserves the complete source by
                # contract. Long static product shots are inherited source
                # characteristics, not proof that the reframe introduced a
                # broken frame sequence. Keep them visible, but do not fail
                # the aspect/lineage capability scenario.
                inherited_static = source_passthrough and issue_code in {
                    "freeze_frames", "black_frames",
                }
                severity = (
                    "warning" if inherited_static
                    else "error" if str(value.get("severity") or "") == "error"
                    else "warning"
                )
                add_issue(
                    issues, severity, f"qc.{issue_code}", "quality",
                    str(value.get("message") or "审核样片质检发现问题。"),
                    evidence=value.get("evidence") if isinstance(value.get("evidence"), dict) else {},
                    recommendation="区分源素材固有问题、选段问题和渲染问题后再决定是否重编排。",
                )
    if str(workspace.get("jobId") or "") != str(job.get("id") or ""):
        add_issue(
            issues, "error", "handoff.workspace_job_mismatch", "handoff",
            "Agent Workspace 与最终任务绑定不一致。",
            evidence={"workspaceJobId": workspace.get("jobId"), "jobId": job.get("id")},
        )
    return issues


class ApiFailure(RuntimeError):
    def __init__(self, method: str, path: str, response: httpx.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        self.status_code = response.status_code
        self.detail = compact_text(detail, 1200)
        super().__init__(f"{method} {path} 返回 HTTP {response.status_code}: {self.detail}")


class AgentScenarioClient:
    def __init__(self, base_url: str, token: str, request_timeout: float) -> None:
        headers = {"Accept": "application/json"}
        if token:
            headers["X-Highlight-Token"] = token
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers,
            timeout=httpx.Timeout(request_timeout, connect=min(request_timeout, 15.0)),
        )

    def close(self) -> None:
        self.client.close()

    def json(
        self, method: str, path: str, *, recovery_seconds: float = 0, **kwargs: Any,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(0, recovery_seconds)
        while True:
            try:
                response = self.client.request(method, path, **kwargs)
            except httpx.HTTPError as error:
                if method == "GET" and time.monotonic() < deadline:
                    time.sleep(1)
                    continue
                raise RuntimeError(f"无法访问 {method} {path}: {error}") from error
            if method == "GET" and response.status_code in {502, 503, 504} and time.monotonic() < deadline:
                time.sleep(1)
                continue
            break
        if response.status_code >= 400:
            raise ApiFailure(method, path, response)
        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError(f"{method} {path} 未返回 JSON") from error
        if not isinstance(payload, dict):
            raise TypeError(f"{method} {path} 返回了非对象 JSON")
        return payload

    def wait_until_ready(self, timeout: float = 90, stable_checks: int = 2) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        stable = 0
        last_error = ""
        latest: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                health = self.json("GET", "/api/health")
                agent_health = self.json("GET", "/api/agent/health")
                ready = bool(health.get("ok")) and str(agent_health.get("status") or "") == "ok"
                if ready:
                    stable += 1
                    latest = {"health": health, "agentHealth": agent_health}
                    if stable >= stable_checks:
                        return latest
                else:
                    stable = 0
                    last_error = f"health={health.get('ok')}, agent={agent_health.get('status')}"
            except (ApiFailure, RuntimeError, TypeError) as error:
                stable = 0
                last_error = str(error)
            time.sleep(1)
        raise RuntimeError(f"服务在 {timeout:.0f} 秒内未恢复稳定：{last_error or '未就绪'}")

    def upload(self, video: Path, scenario: dict[str, Any], force_reanalyze: bool) -> dict[str, Any]:
        prompt = str(scenario["prompt"])
        data = {
            "task_mode": "content_extract",
            "intent_mode": "content_extract",
            "parameter_context": "adaptive_v1",
            "storage_mode": "editable",
            "instruction": prompt,
            "count": "auto",
            "target_seconds": "auto",
            "analysis_mode": "audiovisual",
            "recognition_profile": "auto",
            "force_reanalyze": "true" if force_reanalyze else "false",
            "subtitle_mode": "none",
            "subtitle_style": "clean",
            "edit_mode": "ai_plan",
            "structure": "auto",
            "auto_variant_count": "1",
            "source_scope_kind": "all",
            "result_strategy": "review",
            "search_scope_kind": "all",
            "search_result_limit": "12",
            "search_boundary_mode": "complete",
            "content_auto_generate": "false",
            "entry_workflow": "agent",
        }
        tagged_name = f"agent-test-{scenario['id']}--{video.name}"
        deadline = time.monotonic() + 900
        while True:
            try:
                with video.open("rb") as handle:
                    payload = self.json(
                        "POST", "/api/jobs", data=data,
                        files={"video": (tagged_name, handle, "video/mp4")},
                    )
                break
            except ApiFailure as error:
                rate_limited = error.status_code == 429 and "upload_rate_limited" in error.detail
                if not rate_limited or time.monotonic() >= deadline:
                    raise
                print(f"[{scenario['id']}] 上传限流，15 秒后重试", flush=True)
                time.sleep(15)
        job = payload.get("job")
        if not isinstance(job, dict):
            raise TypeError("上传响应缺少 job 对象")
        return job

    def job(self, job_id: str) -> dict[str, Any]:
        payload = self.json(
            "GET", f"/api/jobs/{quote(job_id, safe='')}", recovery_seconds=90,
        )
        job = payload.get("job")
        if not isinstance(job, dict):
            raise TypeError(f"任务 {job_id} 响应缺少 job 对象")
        return job

    def workspace_by_job(self, job_id: str) -> dict[str, Any]:
        return self.json(
            "GET", f"/api/agent/workspaces/by-job/{quote(job_id, safe='')}",
            recovery_seconds=90,
        )

    def workspace(self, workspace_id: str) -> dict[str, Any]:
        return self.json(
            "GET", f"/api/agent/workspaces/{quote(workspace_id, safe='')}",
            recovery_seconds=90,
        )

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self.json("POST", f"/api/jobs/{quote(job_id, safe='')}/cancel")

    def cancel_plan(self, plan_id: str) -> dict[str, Any]:
        return self.json("POST", f"/api/agent/plans/{quote(plan_id, safe='')}/cancel")

    def create_plan(self, workspace_id: str, prompt: str, skill_id: str | None = None) -> dict[str, Any]:
        payload = self.json(
            "POST", f"/api/agent/workspaces/{quote(workspace_id, safe='')}/messages",
            json={"text": prompt, "skillId": skill_id, "executionMode": "autonomous_review"},
        )
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            raise TypeError("Agent 规划响应缺少 plan 对象")
        return plan

    def confirm(self, plan: dict[str, Any]) -> dict[str, Any]:
        plan_id = str(plan.get("id") or "")
        payload = self.json(
            "POST", f"/api/agent/plans/{quote(plan_id, safe='')}/confirm",
            json={"planHash": plan.get("planHash")},
        )
        confirmed = payload.get("plan")
        if not isinstance(confirmed, dict):
            raise TypeError("确认响应缺少 plan 对象")
        return confirmed

    def probe(self, path: str) -> dict[str, Any]:
        try:
            with self.client.stream("GET", path, headers={"Range": "bytes=0-0"}) as response:
                first = next(response.iter_bytes(), b"")
                return {
                    "path": path,
                    "statusCode": response.status_code,
                    "contentType": response.headers.get("content-type", ""),
                    "readable": response.status_code < 400 and bool(first),
                }
        except httpx.HTTPError as error:
            return {"path": path, "statusCode": 0, "readable": False, "error": str(error)}


def _active_plan(detail: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    workspace = detail.get("workspace") if isinstance(detail.get("workspace"), dict) else {}
    plan_id = str(workspace.get("activePlanId") or "")
    plans = [item for item in detail.get("plans") or [] if isinstance(item, dict)]
    plan = next((item for item in plans if str(item.get("id") or "") == plan_id), None)
    if plan is None and plans:
        plan = plans[-1]
    return workspace, plan or {}


def _snapshot(workspace: dict[str, Any], plan: dict[str, Any], job: dict[str, Any], elapsed: float) -> dict[str, Any]:
    return {
        "observedAt": now_iso(),
        "elapsedSeconds": round(elapsed, 1),
        "workspaceJobId": workspace.get("jobId"),
        "workspaceStatus": workspace.get("status"),
        "planStatus": plan.get("status"),
        "jobStatus": job.get("status"),
        "jobStage": job.get("stage"),
        "steps": [
            {
                "id": step.get("id"), "tool": step.get("tool"),
                "status": step.get("status"), "attempts": step.get("attempts"),
                "error": compact_text(step.get("error"), 240),
            }
            for step in plan.get("steps") or [] if isinstance(step, dict)
        ],
    }


def run_scenario(
    client: AgentScenarioClient, scenario: dict[str, Any], *, defaults: dict[str, Any],
    force_reanalyze: bool, request_timeout: float,
) -> dict[str, Any]:
    del request_timeout
    started_at = now_iso()
    started = time.monotonic()
    result: dict[str, Any] = {
        "id": scenario["id"], "kind": scenario.get("kind"),
        "video": scenario["video"], "prompt": scenario["prompt"],
        "startedAt": started_at, "finishedAt": "", "passed": False,
        "initialJobId": "", "finalJobId": "", "workspaceId": "", "planId": "",
        "planningSeconds": None, "executionSeconds": None,
        "transitions": [], "issues": [], "previewProbes": [],
    }
    issues: list[Issue] = []
    initial_job_id = ""
    active_job_id = ""
    workspace_id = ""
    video = (ROOT / str(scenario["video"])).resolve()
    try:
        if not video.is_file():
            raise RuntimeError(f"场景视频不存在：{video}")
        print(f"\n[{scenario['id']}] 上传 {video.name}", flush=True)
        job = client.upload(video, scenario, force_reanalyze)
        initial_job_id = str(job.get("id") or "")
        active_job_id = initial_job_id
        result["initialJobId"] = initial_job_id
        detail = client.workspace_by_job(initial_job_id)
        workspace = detail.get("workspace") if isinstance(detail.get("workspace"), dict) else {}
        workspace_id = str(workspace.get("id") or "")
        if not workspace_id:
            raise RuntimeError("上传完成后没有 Agent Workspace")
        result["workspaceId"] = workspace_id
        plan_started = time.monotonic()
        print(f"[{scenario['id']}] 提交 Agent 用户输入", flush=True)
        plan = client.create_plan(workspace_id, str(scenario["prompt"]), scenario.get("skillId"))
        result["planningSeconds"] = round(time.monotonic() - plan_started, 2)
        result["planId"] = str(plan.get("id") or "")
        result["initialPlan"] = plan
        issues.extend(evaluate_plan_contract(plan, scenario))
        if str(plan.get("status") or "") != "awaiting_confirmation":
            add_issue(
                issues, "error", "plan.not_awaiting_confirmation", "planning",
                "计划创建后没有停在唯一的初始确认点。",
                evidence={"status": plan.get("status")},
            )
        print(f"[{scenario['id']}] 确认唯一一次计划", flush=True)
        plan = client.confirm(plan)
        execution_started = time.monotonic()
        phase_timeout = float(defaults.get("phaseTimeoutSeconds") or 1800)
        stall_seconds = float(defaults.get("stallSeconds") or 180)
        poll_interval = float(defaults.get("pollIntervalSeconds") or 2)
        last_fingerprint = ""
        last_progress_fingerprint = ""
        last_change = time.monotonic()
        stall_reported = False
        orphan_reported = False
        job_action_reported = False
        final_job = job
        final_workspace = workspace
        while True:
            detail = client.workspace(workspace_id)
            current_workspace, current_plan = _active_plan(detail)
            if current_plan:
                plan = current_plan
            final_workspace = current_workspace or final_workspace
            active_job_id = str(final_workspace.get("jobId") or initial_job_id)
            final_job = client.job(active_job_id)
            snapshot = _snapshot(final_workspace, plan, final_job, time.monotonic() - execution_started)
            execution = final_job.get("execution") if isinstance(final_job.get("execution"), dict) else {}
            timing = execution.get("timing") if isinstance(execution.get("timing"), dict) else {}
            progress_fingerprint = json.dumps({
                "jobId": final_job.get("id"),
                "revision": final_job.get("revision"),
                "lastProgressAt": final_job.get("lastProgressAt"),
                "executionLastProgressAt": timing.get("lastProgressAt"),
            }, sort_keys=True, ensure_ascii=False)
            if progress_fingerprint != last_progress_fingerprint:
                last_progress_fingerprint = progress_fingerprint
                last_change = time.monotonic()
                if stall_reported:
                    issues = [value for value in issues if value.code != "execution.stalled"]
                    stall_reported = False
            fingerprint = json.dumps({key: value for key, value in snapshot.items() if key not in {"observedAt", "elapsedSeconds"}}, sort_keys=True, ensure_ascii=False)
            if fingerprint != last_fingerprint:
                result["transitions"].append(snapshot)
                last_fingerprint = fingerprint
                current_step = next((step for step in snapshot["steps"] if step.get("status") in {"running", "waiting_operation", "action_required"}), None)
                label = current_step.get("tool") if current_step else snapshot.get("planStatus")
                print(f"[{scenario['id']}] {label} · {snapshot.get('jobStage')}", flush=True)
            action_required = str(execution.get("actionRequired") or "")
            if (
                not job_action_reported
                and str(execution.get("status") or "") == "waiting_user"
                and action_required
            ):
                add_issue(
                    issues, "error", "execution.unexpected_confirmation", "execution",
                    "自动模式在媒体子任务中要求用户参与。",
                    evidence={
                        "planStatus": plan.get("status"),
                        "planStep": current_step,
                        "jobStatus": final_job.get("status"),
                        "jobStage": final_job.get("stage"),
                        "actionRequired": action_required,
                    },
                    recommendation="autonomous_review 应根据用户条件自动选择人物，并将 job 级人工点同步到计划状态。",
                )
                job_action_reported = True
                try:
                    cancelled = client.cancel_plan(str(plan.get("id") or ""))
                    if isinstance(cancelled.get("plan"), dict):
                        plan = cancelled["plan"]
                except (ApiFailure, RuntimeError, TypeError):
                    client.cancel_job(active_job_id)
                break
            unchanged = time.monotonic() - last_change
            if unchanged >= stall_seconds and not stall_reported:
                add_issue(
                    issues, "warning", "execution.stalled", "execution",
                    f"状态连续 {unchanged:.0f} 秒没有变化。",
                    evidence={"snapshot": snapshot},
                    recommendation="检查后台 Future 回调、任务轮询和 Agent waiting_operation 恢复。",
                )
                stall_reported = True
            if str(plan.get("status") or "") in TERMINAL_PLAN_STATUSES:
                if bool(execution.get("active")):
                    if not orphan_reported:
                        add_issue(
                            issues, "error", "state.orphaned_media_operation", "execution",
                            "Agent 计划已经终止，但媒体子任务仍在后台运行。",
                            evidence={
                                "planStatus": plan.get("status"),
                                "jobId": final_job.get("id"),
                                "execution": execution,
                            },
                            recommendation="计划失败时应取消或接管仍在运行的分析、自动编排和渲染操作。",
                        )
                        orphan_reported = True
                else:
                    break
            if time.monotonic() - execution_started > phase_timeout:
                add_issue(
                    issues, "error", "execution.timeout", "execution",
                    f"Agent 执行超过 {phase_timeout:.0f} 秒仍未结束。",
                    evidence={"lastSnapshot": snapshot},
                )
                break
            time.sleep(poll_interval)
        result["executionSeconds"] = round(time.monotonic() - execution_started, 2)
        result["finalJobId"] = str(final_job.get("id") or "")
        result["finalPlan"] = plan
        result["finalWorkspace"] = final_workspace
        result["finalJob"] = final_job
        issues.extend(evaluate_terminal_state(plan, final_job, final_workspace, scenario, result["transitions"]))
        for preview in _preview_outputs(plan, final_job):
            path = str(preview.get("previewUrl") or preview.get("videoUrl") or "")
            if not path:
                continue
            probe = client.probe(path)
            result["previewProbes"].append(probe)
            if not probe.get("readable"):
                add_issue(
                    issues, "error", "artifact.preview_unreadable", "delivery",
                    "审核样片 URL 无法读取。", evidence=probe,
                    recommendation="检查预览路由、文件发布和 Range 请求支持。",
                )
    except (ApiFailure, RuntimeError, TypeError, ValueError) as error:
        add_issue(
            issues, "error", "scenario.runtime_failure", "runtime",
            f"场景执行中断：{error}", evidence={"error": str(error)},
        )
        cleanup_job_id = active_job_id or initial_job_id
        if workspace_id:
            try:
                detail = client.workspace(workspace_id)
                current_workspace, _ = _active_plan(detail)
                cleanup_job_id = str(current_workspace.get("jobId") or cleanup_job_id)
            except (ApiFailure, RuntimeError, TypeError):
                pass
        if cleanup_job_id:
            try:
                cleanup_job = client.job(cleanup_job_id)
                execution = cleanup_job.get("execution") if isinstance(cleanup_job.get("execution"), dict) else {}
                active_status = str(cleanup_job.get("status") or "") in {"queued", "running", "cancelling"}
                if active_status or bool(execution.get("active")):
                    client.cancel_job(cleanup_job_id)
                    result["cleanup"] = {"jobId": cleanup_job_id, "cancelRequested": True}
            except (ApiFailure, RuntimeError, TypeError) as cleanup_error:
                result["cleanup"] = {
                    "jobId": cleanup_job_id, "cancelRequested": False,
                    "error": compact_text(cleanup_error, 500),
                }
    result["finishedAt"] = now_iso()
    result["elapsedSeconds"] = round(time.monotonic() - started, 2)
    result["issues"] = [asdict(value) for value in sorted(issues, key=lambda value: SEVERITY_ORDER[value.severity])]
    result["passed"] = not any(value.severity == "error" for value in issues)
    print(f"[{scenario['id']}] {'通过' if result['passed'] else '发现问题'} · {len(issues)} 项", flush=True)
    return result


def markdown_report(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Agent 真实用户场景验证报告",
        "",
        f"- 开始：{report.get('startedAt')}",
        f"- 结束：{report.get('finishedAt')}",
        f"- 结果：{'通过' if report.get('passed') else '发现问题'}",
        f"- 场景：{summary.get('passed', 0)}/{summary.get('total', 0)} 通过",
        f"- 问题：{summary.get('errors', 0)} errors / {summary.get('warnings', 0)} warnings / {summary.get('info', 0)} info",
        "",
        "## 场景结果",
        "",
        "| 场景 | 视频 | 状态 | 最终任务 | 耗时 | 问题 |",
        "|---|---|---|---|---:|---:|",
    ]
    for item in report.get("scenarios") or []:
        lines.append(
            f"| `{item.get('id')}` | {Path(str(item.get('video') or '')).name} | "
            f"{'通过' if item.get('passed') else '失败'} | `{item.get('finalJobId') or item.get('initialJobId') or '-'}` | "
            f"{item.get('elapsedSeconds', 0):.1f}s | {len(item.get('issues') or [])} |"
        )
    lines.extend(["", "## 问题明细", ""])
    problems = [
        (item, value)
        for item in report.get("scenarios") or []
        for value in item.get("issues") or []
    ]
    problems.extend(({"id": "system"}, value) for value in report.get("preflightIssues") or [])
    if not problems:
        lines.append("没有发现可自动判定的问题。")
    else:
        for item, value in sorted(problems, key=lambda pair: SEVERITY_ORDER.get(str(pair[1].get("severity")), 9)):
            lines.extend([
                f"### {str(value.get('severity') or '').upper()} · `{item.get('id')}` · `{value.get('code')}`",
                "",
                str(value.get("message") or ""),
                "",
            ])
            if value.get("recommendation"):
                lines.extend([f"建议：{value['recommendation']}", ""])
            if value.get("evidence"):
                lines.extend([
                    "```json",
                    json.dumps(value["evidence"], ensure_ascii=False, indent=2),
                    "```",
                    "",
                ])
    lines.extend(["## 用户输入", ""])
    for item in report.get("scenarios") or []:
        lines.extend([f"- `{item.get('id')}`：{item.get('prompt')}", ""])
    return "\n".join(lines).rstrip() + "\n"


def local_token(base_url: str, settings: Settings) -> str:
    host = (urlsplit(base_url).hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return os.environ.get("HIGHLIGHT_ACCESS_TOKEN", "").strip() or settings.access_token
    return ""


def load_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or int(data.get("schemaVersion") or 0) != 1:
        raise ValueError("场景清单 schemaVersion 必须为 1")
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    scenarios = [item for item in data.get("scenarios") or [] if isinstance(item, dict)]
    ids = [str(item.get("id") or "") for item in scenarios]
    if not scenarios or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("场景清单必须包含非空且唯一的 id")
    required = {"video", "prompt", "expectedOutcome"}
    for item in scenarios:
        missing = sorted(key for key in required if not item.get(key))
        if missing:
            raise ValueError(f"场景 {item['id']} 缺少字段：{', '.join(missing)}")
    return defaults, scenarios


def parser_for(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用 cest-video 真实模拟用户验证 ClipTalk Agent")
    parser.add_argument(
        "--manifest", type=Path,
        default=ROOT / "tests" / "fixtures" / "agent_user_scenarios.json",
    )
    parser.add_argument("--base-url", default=f"http://127.0.0.1:{settings.port}")
    parser.add_argument("--token", default="")
    parser.add_argument("--case", action="append", default=[], help="只运行指定场景 ID，可重复传入")
    parser.add_argument("--limit", type=int, default=0, help="只运行筛选后的前 N 个场景；0 为全部")
    parser.add_argument("--request-timeout", type=float, default=180)
    parser.add_argument("--phase-timeout", type=float, default=0, help="覆盖清单中的单场景超时")
    parser.add_argument("--poll-interval", type=float, default=0, help="覆盖清单中的轮询间隔")
    parser.add_argument("--stall-seconds", type=float, default=0, help="覆盖清单中的停滞告警阈值")
    parser.add_argument("--force-reanalyze", action="store_true", help="禁用相同源视频的分析复用")
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="仅校验并列出场景，不创建任务")
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_environment()
    args = parser_for(settings).parse_args(argv)
    manifest = args.manifest.expanduser().resolve()
    defaults, scenarios = load_manifest(manifest)
    if args.case:
        wanted = set(args.case)
        known = {str(item["id"]) for item in scenarios}
        missing = sorted(wanted - known)
        if missing:
            raise SystemExit(f"未知场景：{', '.join(missing)}")
        scenarios = [item for item in scenarios if str(item["id"]) in wanted]
    if args.limit:
        if args.limit < 1:
            raise SystemExit("--limit 必须大于 0")
        scenarios = scenarios[:args.limit]
    if args.phase_timeout > 0:
        defaults["phaseTimeoutSeconds"] = args.phase_timeout
    if args.poll_interval > 0:
        defaults["pollIntervalSeconds"] = args.poll_interval
    if args.stall_seconds > 0:
        defaults["stallSeconds"] = args.stall_seconds
    for item in scenarios:
        video = (ROOT / str(item["video"])).resolve()
        print(f"{item['id']}: {video.name} · {item['prompt']}")
    if args.dry_run:
        return 0

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = (args.output_dir or ROOT / "test-results" / f"agent-scenarios-{timestamp}").expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schemaVersion": 1, "startedAt": now_iso(), "finishedAt": "", "passed": False,
        "configuration": {
            "manifest": str(manifest), "baseUrl": args.base_url.rstrip("/"),
            "forceReanalyze": bool(args.force_reanalyze), "defaults": defaults,
        },
        "service": {}, "preflightIssues": [], "scenarios": [], "summary": {},
    }
    token = args.token.strip() or local_token(args.base_url, settings)
    client = AgentScenarioClient(args.base_url, token, args.request_timeout)
    try:
        health = client.json("GET", "/api/health")
        agent_health = client.json("GET", "/api/agent/health")
        report["service"] = {"health": health, "agentHealth": agent_health}
        required_health = {
            "visionConfigured": health.get("visionConfigured"),
            "llmConfigured": health.get("llmConfigured"),
            "speechRecognitionConfigured": health.get("speechRecognitionConfigured"),
            "ffmpeg": health.get("ffmpeg"), "ffprobe": health.get("ffprobe"),
            "agent": agent_health.get("status") == "ok",
        }
        for name, ready in required_health.items():
            if not ready:
                report["preflightIssues"].append(asdict(Issue(
                    severity="error", code=f"preflight.{name}", phase="preflight",
                    message=f"真实 Agent 测试依赖未就绪：{name}。",
                )))
        if not report["preflightIssues"]:
            for scenario in scenarios:
                print(f"\n[{scenario['id']}] 等待服务稳定", flush=True)
                client.wait_until_ready()
                case_result = run_scenario(
                    client, scenario, defaults=defaults,
                    force_reanalyze=args.force_reanalyze,
                    request_timeout=args.request_timeout,
                )
                report["scenarios"].append(case_result)
                report["finishedAt"] = now_iso()
                (output_dir / "report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
                )
    except KeyboardInterrupt:
        report["preflightIssues"].append(asdict(Issue(
            severity="error", code="run.interrupted", phase="runtime",
            message="验证被中断；已创建任务仍保留。",
        )))
    except (ApiFailure, RuntimeError, TypeError) as error:
        report["preflightIssues"].append(asdict(Issue(
            severity="error", code="preflight.service_unreachable", phase="preflight",
            message=f"无法启动真实 Agent 测试：{error}", evidence={"error": str(error)},
        )))
    finally:
        client.close()
        report["finishedAt"] = now_iso()
        all_issues = [
            *report["preflightIssues"],
            *(value for item in report["scenarios"] for value in item.get("issues") or []),
        ]
        errors = sum(value.get("severity") == "error" for value in all_issues)
        warnings = sum(value.get("severity") == "warning" for value in all_issues)
        info = sum(value.get("severity") == "info" for value in all_issues)
        passed_cases = sum(bool(item.get("passed")) for item in report["scenarios"])
        report["summary"] = {
            "total": len(report["scenarios"]), "passed": passed_cases,
            "failed": len(report["scenarios"]) - passed_cases,
            "errors": errors, "warnings": warnings, "info": info,
        }
        report["passed"] = errors == 0 and not (args.fail_on_warning and warnings > 0)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "report.md").write_text(markdown_report(report), encoding="utf-8")
    print(
        f"\nAgent 场景：{report['summary']['passed']}/{report['summary']['total']} 通过；"
        f"{report['summary']['errors']} errors，{report['summary']['warnings']} warnings",
    )
    print(f"报告：{output_dir / 'report.md'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
