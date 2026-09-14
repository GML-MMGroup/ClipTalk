from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import threading
import time
import uuid
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from .agent_store import AgentStore, content_hash, now_iso, parse_skill_markdown
from .service_security import service_token, plugin_tree_hash


CORE_TOOL_CATALOG: tuple[dict[str, Any], ...] = (
    {"name": "inspect_workspace", "description": "读取当前素材、任务状态和已有分析结果；也可在执行前核验当前任务是否具备所选 Skill 的必要成片或时间线", "sideEffect": "read", "parameters": {"type": "object", "properties": {"requiredState": {"type": "string"}, "preconditionCode": {"type": "string"}, "preconditionMessage": {"type": "string"}}, "additionalProperties": False}},
    {"name": "analyze_highlights", "description": "运行多模态高光分析并生成候选", "sideEffect": "analysis", "parameters": {"type": "object", "properties": {"instruction": {"type": "string"}, "targetSeconds": {"type": "number"}, "focus": {"type": "string"}}, "additionalProperties": False}},
    {"name": "search_content", "description": "根据语义、字幕和画面证据搜索内容片段", "sideEffect": "analysis", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "review_content_evidence", "description": "请求用户审核并保存将用于组合的内容候选", "sideEffect": "review", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "minimumSelection": {"type": "integer"}, "selectionPolicy": {"type": "string", "enum": ["all_reliable", "unique_or_review"]}}, "required": ["query"], "additionalProperties": False}},
    {"name": "discover_people", "description": "发现素材中的人物和出现区间", "sideEffect": "analysis", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "select_people", "description": "请求用户确认需要保留或排除的人物", "sideEffect": "identity", "parameters": {"type": "object", "properties": {"mode": {"type": "string"}, "description": {"type": "string"}}, "additionalProperties": False}},
    {"name": "discover_speakers", "description": "发现当前素材内的匿名说话人", "sideEffect": "analysis", "parameters": {"type": "object", "properties": {"expectedSpeakers": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "select_speakers", "description": "请求用户确认说话人及保留方式", "sideEffect": "identity", "parameters": {"type": "object", "properties": {"mode": {"type": "string"}, "label": {"type": "string"}}, "additionalProperties": False}},
    {"name": "propose_timeline_edit", "description": "根据已确认的证据建立一到四个可审阅、尚未应用的时间线修改", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"instruction": {"type": "string"}, "variantCount": {"type": "integer"}, "variantDirections": {"type": "array"}, "targetSeconds": {"type": "number"}, "toleranceSeconds": {"type": "number"}, "durationSource": {"type": "string"}, "anchorStartQuery": {"type": "string"}}, "required": ["instruction"], "additionalProperties": False}},
    {"name": "confirm_timeline_edit", "description": "请求用户审核并确认已应用的时间线修改", "sideEffect": "preview", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "prepare_subtitle_review", "description": "生成已确认时间线对应的可审阅字幕草稿；自动模式仅应用低风险校对并继续生成样片", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"style": {"type": "string"}, "requireConfirmedDraft": {"type": "boolean"}, "autoReview": {"type": "boolean"}}, "additionalProperties": False}},
    {"name": "render_review_preview", "description": "渲染带轻水印、低码率和审阅字幕的审核样片；不做正式导出", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"subtitleMode": {"type": "string"}}, "additionalProperties": False}},
    {"name": "render_social_preview", "description": "从已有成片生成指定社媒画幅的审核预览；无论目标比例为何，默认完整保留原始画面并使用同画面虚化背景补足画布，只有用户明确要求时才裁切或留黑边，不覆盖原成片", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "aspect": {"type": "string"}, "fit": {"type": "string"}, "focusX": {"type": "number"}, "focusY": {"type": "number"}}, "required": ["aspect", "fit"], "additionalProperties": False}},
    {"name": "propose_cover_candidates", "description": "从已有成片或源视频抽取、去重并评分可追溯的封面候选帧，不修改当前封面", "sideEffect": "analysis", "parameters": {"type": "object", "properties": {"sourceScope": {"type": "string"}, "candidateBudget": {"type": "integer"}, "aspectRatios": {"type": "array"}, "titleText": {"type": "string"}, "focus": {"type": "string"}}, "required": ["sourceScope", "candidateBudget", "aspectRatios"], "additionalProperties": False}},
    {"name": "render_cover_variants", "description": "从已评分候选帧生成不覆盖现有封面的本地审核预览，保留来源、评分和内容哈希", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"aspectRatios": {"type": "array"}, "directions": {"type": "array"}, "titleText": {"type": "string"}}, "required": ["aspectRatios", "directions"], "additionalProperties": False}},
    {"name": "review_cover_variants", "description": "审核封面候选；自动模式按当前主题和画幅自动选优，分步模式请求用户选择", "sideEffect": "review", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "confirm_cover", "description": "保存当前任务封面版本；自动成片模式随后生成正式成片，分步模式仅保存用户选择", "sideEffect": "preview", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "run_delivery_qc", "description": "对已有成片运行完整解码、目标时长、音轨、黑帧、冻结、静音和响度检查，不修改媒体", "sideEffect": "analysis", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "strict": {"type": "boolean"}, "targetSeconds": {"type": "number"}, "toleranceSeconds": {"type": "number"}}, "additionalProperties": False}},
    {"name": "validate_task_provenance", "description": "校验当前工作区、源素材、时间范围、候选、时间线、封面、字幕和输出均属于当前任务", "sideEffect": "read", "parameters": {"type": "object", "properties": {"strict": {"type": "boolean"}}, "additionalProperties": False}},
    {"name": "select_multi_topic_evidence", "description": "从内容检索结果中按多个必需主题选择可靠候选；缺少任一主题时返回结构化无结果", "sideEffect": "review", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "minimumPerTopic": {"type": "integer"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "compose_cover_intro", "description": "把当前任务已确认封面合成为当前成片的短片头，不复用其他任务封面", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"duration": {"type": "number"}}, "additionalProperties": False}},
    {"name": "analyze_reframe_safe_areas", "description": "分析当前输出画幅转换的安全策略，保护人物、字幕、屏幕文字和产品主体", "sideEffect": "analysis", "parameters": {"type": "object", "properties": {"aspect": {"type": "string"}, "fit": {"type": "string"}}, "required": ["aspect"], "additionalProperties": False}},
    {"name": "layout_subtitles", "description": "更新当前精剪时间线已确认字幕稿的布局，支持顶部/底部、安全区、字号和双语等要求；不会自行生成字幕文字", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"position": {"type": "string"}, "style": {"type": "string"}, "fontSizeRatio": {"type": "number"}}, "additionalProperties": False}},
    {"name": "polish_audio_mix", "description": "基于当前任务输出生成音频优化版本，支持响度规范化、保守降噪和人声优先", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "noiseReduction": {"type": "boolean"}, "voiceFirst": {"type": "boolean"}}, "additionalProperties": False}},
    {"name": "propose_broll_overlay", "description": "把已确认的辅助画面作为静音插入镜头加入当前时间线，保留主音频", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "maxOverlays": {"type": "integer"}}, "required": ["query"], "additionalProperties": False}},
    {"name": "render_graphics_package", "description": "在当前精剪时间线添加可编辑图文层，如标题、标签、参数卡、价格、Logo、水印或 CTA", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "placement": {"type": "string"}, "style": {"type": "string"}}, "additionalProperties": False}},
    {"name": "render_motion_graphics", "description": "使用本地 HTML/React 风格渲染管线生成动态图文、标题卡、片头或封面动效视频，不依赖外部 API", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "subtitle": {"type": "string"}, "aspect": {"type": "string"}, "duration": {"type": "number"}, "theme": {"type": "string"}}, "additionalProperties": False}},
    {"name": "compose_motion_intro", "description": "把本地图文动效合成为当前任务成片片头，生成新版本，不覆盖原成片", "sideEffect": "preview", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "introFilename": {"type": "string"}}, "additionalProperties": False}},
    {"name": "export_editing_draft", "description": "导出当前任务的本地剪辑草稿包，供外部编辑器或剪映映射器使用；不写入第三方软件目录", "sideEffect": "export", "parameters": {"type": "object", "properties": {"format": {"type": "string"}}, "additionalProperties": False}},
    {"name": "export_delivery_master", "description": "将当前确认输出生成正式交付版本或平台包；需要明确授权，不覆盖历史版本", "sideEffect": "export", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "platform": {"type": "string"}, "aspect": {"type": "string"}}, "additionalProperties": False}},
    {"name": "diagnose_edit_failure", "description": "诊断当前 Agent 计划、素材证据、时间线、画幅、封面、字幕、预览和导出问题", "sideEffect": "read", "parameters": {"type": "object", "properties": {"focus": {"type": "string"}}, "additionalProperties": False}},
    {"name": "cancel_operation", "description": "取消当前计划启动的后台操作", "sideEffect": "analysis", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
)

FORBIDDEN_AUTONOMOUS_EFFECTS = frozenset({"export", "delete"})
SAFE_AUTONOMOUS_EXPORT_TOOLS = frozenset({"export_editing_draft"})
ACTION_REQUIRED_EFFECTS = frozenset({"identity", "review"})
VALID_SIDE_EFFECTS = frozenset({"read", "analysis", "preview", "identity", "review", "export", "delete"})
AUTONOMOUS_REVIEW = "autonomous_review"
STEPWISE_REVIEW = "stepwise_review"
VALID_EXECUTION_MODES = frozenset({AUTONOMOUS_REVIEW, STEPWISE_REVIEW})


for _tool in CORE_TOOL_CATALOG:
    if _tool["name"] in {"analyze_highlights", "search_content", "discover_people", "discover_speakers"}:
        _tool["parameters"]["properties"].update({
            "sourceScopeKind": {"type": "string", "enum": ["all", "custom"]},
            "sourceScopeStart": {"type": "number", "minimum": 0},
            "sourceScopeEnd": {"type": "number", "exclusiveMinimum": 0},
        })
    if _tool["name"] == "propose_timeline_edit":
        _tool["parameters"]["properties"]["distinctSourceAcrossVariants"] = {"type": "boolean"}


class AgentServiceError(RuntimeError):
    pass


class AgentServiceClient:
    def __init__(self, base_url: str, timeout_seconds: float = 120.0, token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.token = token

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + max(1.0, float(self.timeout_seconds))
        request_id = str(payload.get("requestId") or "")
        response: httpx.Response | None = None
        last_error: Exception | None = None
        # Side-effect requests are never blindly replayed after a lost response.
        attempts = 1 if path == "/v1/tools/execute" else 2
        for attempt in range(attempts):
            remaining = max(0.1, deadline - time.monotonic())
            try:
                response = httpx.post(
                    f"{self.base_url}{path}", json=payload,
                    headers={"Authorization": f"Bearer {self.token}", **({"Idempotency-Key": request_id} if request_id else {})},
                    timeout=httpx.Timeout(remaining, connect=min(5.0, remaining)),
                )
                if response.status_code >= 500 and attempt + 1 < attempts and deadline - time.monotonic() > .2:
                    continue
                response.raise_for_status()
                last_error = None
                break
            except httpx.HTTPStatusError as error:
                last_error = error
                break
            except httpx.HTTPError as error:
                last_error = error
                if attempt + 1 < attempts and deadline - time.monotonic() > .2:
                    continue
                break
        if response is None or last_error is not None:
            if isinstance(last_error, httpx.HTTPStatusError):
                detail = ""
                try:
                    body = last_error.response.json()
                    if isinstance(body, dict):
                        detail = str(body.get("message") or body.get("error") or "")
                except ValueError:
                    detail = last_error.response.text[:500]
                if detail == "Agent 模型尚未配置完整":
                    detail = "未找到可用的 Agent 模型；请配置 Agent 模型，或先保存可复用的文本模型连接"
                service_error = AgentServiceError(f"Pi Agent 请求未完成：{detail or f'HTTP {last_error.response.status_code}'}")
                service_error.status_code = last_error.response.status_code
                raise service_error from last_error
            raise AgentServiceError(f"Pi Agent 服务不可用：{last_error or '请求超时'}") from last_error
        try:
            result = response.json()
        except ValueError as error:
            raise AgentServiceError("Pi Agent 服务返回了无效响应") from error
        if not isinstance(result, dict):
            raise AgentServiceError("Pi Agent 服务返回了无效响应")
        return result

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/plan", payload)

    def generate_skill(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/skills/generate", payload)

    def route_skill(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/skills/route", payload)

    def probe(self, model: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/probe", {"model": model})

    def activate_plugin(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/plugins/activate", payload)

    def deactivate_plugin(self, plugin_id: str) -> dict[str, Any]:
        return self._post("/v1/plugins/deactivate", {"pluginId": plugin_id})

    def execute_plugin_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation_id = str(payload.get("operationId") or "")
        if not operation_id:
            raise AgentServiceError("工具执行缺少 operationId")
        try:
            operation = self._post("/v1/tools/execute", payload)
        except AgentServiceError as error:
            if 400 <= getattr(error, "status_code", 0) < 500:
                raise
            try:
                operation = self._post("/v1/operations/get", {"operationId": operation_id})
            except AgentServiceError:
                operation = {"status": "uncertain"}
        if operation.get("status") == "succeeded":
            result = operation.get("result")
            return result if isinstance(result, dict) else {"value": result}
        return {"actionRequired": True, "operationId": operation_id,
                "operationStatus": operation.get("status") or "uncertain", "retryable": False,
                "message": "工具执行结果待核实；请检查操作记录，不要重复执行。"}

    def query_plugin_operation(self, operation_id: str) -> dict[str, Any]:
        return self._post("/v1/operations/get", {"operationId": operation_id})

    def health(self) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self.base_url}/health", timeout=3.0)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return {"status": "unavailable"}


ToolDispatcher = Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]]
ModelConfigResolver = Callable[[], dict[str, Any]]
WorkspaceStateListener = Callable[[dict[str, Any], dict[str, Any] | None], None]
ActionResolutionValidator = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]
PlanningContextProvider = Callable[[str], dict[str, Any]]


# A Skill supplies editorial policy; this registry owns executable workflow
# shape. Generated Skills fall back to their explicit allow-list, while trusted
# Plugins can later register profiles through the same contract.
SKILL_PROFILES: dict[str, dict[str, Any]] = {
    "cliptalk-highlight-director": {"kind": "highlight", "tools": {"inspect_workspace", "analyze_highlights", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview"}},
    "cliptalk-content-extractor": {"kind": "content", "tools": {"inspect_workspace", "search_content", "review_content_evidence", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview"}},
    "cliptalk-interview-editor": {"kind": "interview", "tools": {"inspect_workspace", "discover_speakers", "select_speakers", "search_content", "review_content_evidence", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview"}},
    "cliptalk-person-editor": {"kind": "person", "tools": {"inspect_workspace", "discover_people", "select_people", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview"}},
    "cliptalk-speaker-editor": {"kind": "speaker", "tools": {"inspect_workspace", "discover_speakers", "select_speakers", "search_content", "review_content_evidence", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview"}},
    "cliptalk-revision-editor": {"kind": "revision", "tools": {"inspect_workspace", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview"}},
    "cliptalk-shortform-hook-director": {"kind": "shortform", "tools": {"inspect_workspace", "analyze_highlights", "search_content", "review_content_evidence", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview"}},
    "cliptalk-delivery-qc": {"kind": "delivery-qc", "tools": {"inspect_workspace", "run_delivery_qc"}},
    "cliptalk-social-reframe-exporter": {"kind": "social-reframe", "tools": {"inspect_workspace", "render_social_preview", "run_delivery_qc"}},
    "cliptalk-smart-reframe": {"kind": "social-reframe", "tools": {"inspect_workspace", "render_social_preview", "run_delivery_qc"}},
    "cliptalk-cover-director": {"kind": "cover", "tools": {"inspect_workspace", "propose_cover_candidates", "render_cover_variants", "review_cover_variants", "confirm_cover"}},
    "cliptalk-subtitle-editor": {"kind": "revision", "tools": {"inspect_workspace", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview"}},
    "cliptalk-source-provenance-guard": {"kind": "source-provenance", "tools": {"inspect_workspace", "validate_task_provenance"}},
    "cliptalk-multi-topic-assembler": {"kind": "multi-topic", "tools": {"inspect_workspace", "search_content", "select_multi_topic_evidence", "propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review", "render_review_preview", "render_social_preview", "run_delivery_qc"}},
    "cliptalk-cover-intro-composer": {"kind": "cover-intro", "tools": {"inspect_workspace", "propose_cover_candidates", "render_cover_variants", "review_cover_variants", "confirm_cover", "compose_cover_intro", "run_delivery_qc"}},
    "cliptalk-dynamic-reframe-director": {"kind": "dynamic-reframe", "tools": {"inspect_workspace", "analyze_reframe_safe_areas", "render_social_preview", "run_delivery_qc"}},
    "cliptalk-caption-layout-director": {"kind": "caption-layout", "tools": {"inspect_workspace", "layout_subtitles", "prepare_subtitle_review", "render_review_preview"}},
    "cliptalk-audio-polish-mixer": {"kind": "audio-polish", "tools": {"inspect_workspace", "polish_audio_mix", "run_delivery_qc"}},
    "cliptalk-broll-overlay-editor": {"kind": "broll-overlay", "tools": {"inspect_workspace", "search_content", "review_content_evidence", "propose_broll_overlay", "confirm_timeline_edit", "render_review_preview"}},
    "cliptalk-graphics-packager": {"kind": "graphics-package", "tools": {"inspect_workspace", "render_graphics_package", "render_review_preview"}},
    "cliptalk-local-motion-renderer": {"kind": "local-motion", "tools": {"inspect_workspace", "render_motion_graphics", "compose_motion_intro", "run_delivery_qc"}},
    "cliptalk-local-draft-exporter": {"kind": "local-draft", "tools": {"inspect_workspace", "export_editing_draft"}},
    "cliptalk-platform-delivery-exporter": {"kind": "platform-delivery", "tools": {"inspect_workspace", "export_delivery_master", "run_delivery_qc"}},
    "cliptalk-edit-diagnostics": {"kind": "edit-diagnostics", "tools": {"inspect_workspace", "diagnose_edit_failure"}},
}
WORKFLOW_PROFILE_KINDS = frozenset(profile["kind"] for profile in SKILL_PROFILES.values())

ACTIVE_PLAN_STATUSES = frozenset({
    "awaiting_confirmation", "approved", "running", "action_required",
})


class AgentPlatform:
    """Plan-gated orchestration around Pi and the existing media kernel."""

    def __init__(
        self, *, data_root: Path, service_url: str,
        model_config_resolver: ModelConfigResolver, timeout_seconds: float = 120.0,
    ) -> None:
        self.data_root = data_root / "agent"
        self.skills_root = self.data_root / "skills"
        self.plugins_root = self.data_root / "plugins"
        self.sessions_root = self.data_root / "sessions"
        for path in (self.skills_root, self.plugins_root, self.sessions_root):
            path.mkdir(parents=True, exist_ok=True)
        self.store = AgentStore(self.data_root / "agent.sqlite3")
        self.client = AgentServiceClient(service_url, timeout_seconds=timeout_seconds,
                                         token=service_token(self.data_root / "service-token"))
        self.model_config_resolver = model_config_resolver
        self._dispatch_tool: ToolDispatcher | None = None
        self._workspace_state_listener: WorkspaceStateListener | None = None
        self._action_resolution_validator: ActionResolutionValidator | None = None
        self._planning_context_provider: PlanningContextProvider | None = None
        self._execution_lock = threading.RLock()
        self._operation_handles: dict[tuple[str, str], dict[str, Any]] = {}

    def configure_tool_dispatcher(self, dispatcher: ToolDispatcher) -> None:
        self._dispatch_tool = dispatcher

    def adopt_recovered_operation(
        self, plan_id: str, step_id: str, future: Future[Any], operation_id: str,
    ) -> bool:
        """Reconnect a durable media Future to its Agent step after restart."""
        with self._execution_lock:
            plan = self.store.get("plans", plan_id)
            step = next((item for item in (plan or {}).get("steps", []) if item.get("id") == step_id), None)
            if not plan or not step or str(step.get("status") or "") != "waiting_operation":
                return False
            self._operation_handles[(plan_id, step_id)] = {
                "future": future, "cancel": None, "operationId": operation_id,
            }
        future.add_done_callback(
            lambda completed: self._future_finished(plan_id, step_id, operation_id, completed)
        )
        return True

    def configure_workspace_state_listener(self, listener: WorkspaceStateListener) -> None:
        """Persist a compact Agent summary alongside the media job when available."""
        self._workspace_state_listener = listener

    def configure_action_resolution_validator(self, validator: ActionResolutionValidator) -> None:
        """Attach product-specific validation for review selections."""
        self._action_resolution_validator = validator

    def configure_planning_context_provider(self, provider: PlanningContextProvider) -> None:
        """Provide a compact, read-only material snapshot before planning."""
        self._planning_context_provider = provider

    def _notify_workspace_state(
        self, workspace: dict[str, Any], plan: dict[str, Any] | None = None,
    ) -> None:
        listener = self._workspace_state_listener
        if listener is None:
            return
        try:
            listener(copy.deepcopy(workspace), copy.deepcopy(plan) if plan else None)
        except Exception:
            # Agent orchestration must not lose a completed plan merely because
            # the presentation-side job summary could not be refreshed.
            return

    def restore_plugins(self) -> None:
        for plugin in self.store.list(
            "plugins", predicate=lambda item: item.get("status") == "enabled" and item.get("trusted"),
        ):
            try:
                runtime = self.client.activate_plugin({
                    "pluginId": plugin["id"], "version": plugin.get("version"),
                    "contentHash": plugin["contentHash"], "path": plugin["path"],
                    "treeHash": plugin.get("treeHash"),
                    "entrypoint": plugin["entrypoint"], "tools": plugin["tools"],
                })
            except AgentServiceError as error:
                plugin["runtime"] = {"status": "unavailable", "error": str(error)}
            else:
                plugin["runtime"] = runtime
            self.store.save("plugins", plugin)

    def seed_skills(self, source_root: Path) -> None:
        if not source_root.is_dir():
            return
        for skill_file in sorted(source_root.glob("*/SKILL.md")):
            markdown = skill_file.read_text(encoding="utf-8")
            fields = parse_skill_markdown(markdown)
            skill_id = fields["name"]
            existing = self.store.get("skills", skill_id)
            digest = content_hash(markdown)
            if existing and existing.get("contentHash") == digest:
                continue
            self.store.save("skills", {
                "id": skill_id, "name": skill_id, "description": fields["description"],
                "status": "enabled", "source": "builtin", "version": fields.get("version") or "1.0.0",
                "contentHash": digest, "skillMarkdown": markdown,
                "path": str(skill_file.parent.resolve()), "allowedTools": fields.get("allowedTools") or [],
                "workflowProfile": fields.get("workflowProfile") or "",
                "validation": {"valid": True, "errors": []},
            })

    def install_skill(
        self, *, markdown: str, source: str, status: str = "validated", path: str = "",
    ) -> dict[str, Any]:
        fields = parse_skill_markdown(markdown)
        digest = content_hash(markdown)
        skill_id = fields["name"]
        available_tools = {item["name"] for item in self.tool_catalog()}
        missing_tools = sorted(set(fields.get("allowedTools") or []) - available_tools)
        workflow_profile = str(fields.get("workflowProfile") or "")
        invalid_profile = bool(workflow_profile and workflow_profile not in WORKFLOW_PROFILE_KINDS)
        validation: dict[str, Any] = {"valid": not missing_tools and not invalid_profile, "errors": []}
        if missing_tools:
            validation["errors"].append(f"缺少工具：{', '.join(missing_tools)}")
            status = "draft"
        if invalid_profile:
            validation["errors"].append(f"未知工作流档案：{workflow_profile}")
            status = "draft"
        existing = self.store.get("skills", skill_id)
        declared_version = str(fields.get("version") or "1.0.0")
        version = declared_version
        if existing and source != "builtin" and declared_version == "1.0.0":
            major = int(str(existing.get("version") or "0").split(".")[0] or 0) + 1
            version = f"{major}.0.0"
        return self.store.save("skills", {
            "id": skill_id, "name": skill_id, "description": fields["description"],
            "status": status, "source": source, "version": version,
            "contentHash": digest, "skillMarkdown": markdown, "path": path,
            "allowedTools": fields.get("allowedTools") or [],
            "workflowProfile": workflow_profile, "validation": validation,
        })

    def generate_skill(self, *, request: str) -> dict[str, Any]:
        result = self.client.generate_skill({
            "request": request, "model": self.model_config_resolver(),
            "toolCatalog": self.tool_catalog(),
        })
        markdown = str(result.get("skillMarkdown") or "")
        skill = self.install_skill(markdown=markdown, source="generated", status="draft")
        profile = self._profile_for_skill(skill)
        profile_valid = bool(skill.get("workflowProfile")) and bool(profile.get("managed"))
        skill["simulation"] = result.get("simulation") or {}
        simulation_valid = bool((skill["simulation"] or {}).get("valid"))
        skill["validation"] = {
            "valid": bool((skill.get("validation") or {}).get("valid")) and simulation_valid and profile_valid,
            "errors": list((skill.get("validation") or {}).get("errors") or [])
            + ([] if simulation_valid else ["模拟规划未通过"])
            + ([] if profile_valid else ["生成 Skill 必须声明有效的 workflow-profile，并完整包含该档案所需工具"]),
        }
        skill["status"] = "validated" if skill["validation"]["valid"] else "draft"
        return self.store.save("skills", skill)

    def enable_skill(self, skill_id: str, expected_hash: str) -> dict[str, Any]:
        skill = self.store.get("skills", skill_id)
        if not skill:
            raise KeyError(skill_id)
        if str(skill.get("contentHash") or "") != expected_hash:
            raise ValueError("Skill 内容已经变化，请重新审核")
        if not bool((skill.get("validation") or {}).get("valid")):
            raise ValueError("Skill 校验未通过")
        skill["status"] = "enabled"
        return self.store.save("skills", skill)

    def tool_catalog(self) -> list[dict[str, Any]]:
        catalog = [copy.deepcopy(item) for item in CORE_TOOL_CATALOG]
        for plugin in self.store.list(
            "plugins", predicate=lambda item: item.get("status") == "enabled",
        ):
            for tool in plugin.get("tools") or []:
                if not isinstance(tool, dict) or not tool.get("name"):
                    continue
                catalog.append({
                    "name": str(tool["name"]),
                    "description": str(tool.get("description") or "Plugin tool"),
                    "sideEffect": str(tool.get("sideEffect") or "analysis"),
                    "pluginId": plugin["id"], "pluginVersion": plugin.get("version"),
                    "contentHash": plugin.get("contentHash"), "treeHash": plugin.get("treeHash"),
                    "parameters": tool.get("parameters") or {"type": "object"},
                })
        return catalog

    def _planning_context(self, job_id: str) -> dict[str, Any]:
        provider = self._planning_context_provider
        if provider is None:
            return {"jobId": job_id, "available": False}
        try:
            value = provider(job_id)
        except Exception:
            return {"jobId": job_id, "available": False}
        return copy.deepcopy(value) if isinstance(value, dict) else {"jobId": job_id, "available": False}

    @staticmethod
    def _chinese_number(value: str) -> float | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text == "半":
            return .5
        digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9}
        if all(character in digits for character in text):
            return float("".join(str(digits[character]) for character in text))
        if "十" in text:
            left, right = text.split("十", 1)
            tens = digits.get(left, 1) if left else 1
            ones = digits.get(right, 0) if right else 0
            return float(tens * 10 + ones)
        return None

    @classmethod
    def _source_range(cls, text: str, context: dict[str, Any]) -> dict[str, Any] | None:
        match = re.search(r"(最后|结尾|末尾|开头|前)\s*([0-9.零〇一二两三四五六七八九十半]+)\s*(分钟|分|秒钟|秒)", text)
        if not match:
            existing = context.get("sourceRange")
            return copy.deepcopy(existing) if isinstance(existing, dict) else None
        try:
            amount = float(match[2])
        except ValueError:
            amount = cls._chinese_number(match[2])
        if amount is None or amount <= 0:
            return None
        seconds = amount * (60 if match[3] in {"分钟", "分"} else 1)
        duration = float(context.get("duration") or context.get("sourceDuration") or 0)
        tail = match[1] in {"最后", "结尾", "末尾"}
        return {
            "kind": "custom", "start": max(0, duration - seconds) if tail else 0,
            "end": duration if tail else min(seconds, duration) if duration else seconds,
            "description": match[0], "requiresDuration": tail and duration <= 0,
        }

    @classmethod
    def _duration_target(cls, text: str) -> tuple[int | None, bool]:
        normalized = re.sub(
            r"(?:最后|结尾|末尾|开头|前)\s*[0-9.零〇一二两三四五六七八九十半]+\s*(?:分钟|分|秒钟|秒)",
            "", str(text or ""),
        )
        # A duration mentioned as something to avoid is not a requested
        # target. For example, “不要因为默认 30 秒目标丢片段” used to be
        # compiled into an explicit 30-second cut.
        normalized = re.sub(
            r"(?:不要|不能|不应|无需|不需要)[^，,。；;]{0,80}?"
            r"\d+(?:\.\d+)?\s*(?:秒钟|秒|s(?![a-z])|分钟|分)"
            r"[^，,。；;]{0,80}(?=[，,。；;]|$)",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        # Parse an explicit target/tolerance pair before the generic duration
        # patterns. In text such as ``60±6 秒`` the generic expression can
        # only attach the unit to ``6`` and would mistake the tolerance for the
        # target duration.
        tolerance_match = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:±|\+\s*/\s*-|\+\s*-)\s*"
            r"(\d+(?:\.\d+)?)\s*(?:秒钟|秒|s(?![a-z]))",
            normalized,
            re.IGNORECASE,
        )
        if tolerance_match:
            return round(float(tolerance_match.group(1))), True
        total_match = re.search(
            r"(?:总(?:时长|长度)|组合成|合成为|拼接(?:合成)?(?:成|为)|拼成|剪成|做成|最终(?:视频|成片)?(?:为|要)?)"
            r".{0,12}?(\d+(?:\.\d+)?)\s*(?:秒钟|秒|s(?![a-z]))",
            normalized,
            re.IGNORECASE,
        )
        if total_match:
            return round(float(total_match.group(1))), True
        minute_match = re.search(r"(?:约|大约|约为|做成)?\s*(\d+(?:\.\d+)?)\s*(?:分钟|分)", normalized)
        second_match = re.search(
            r"(?:约|大约|约为|做成)?\s*(\d+(?:\.\d+)?)\s*(?:秒钟|秒|s(?![a-z]))",
            normalized,
            re.IGNORECASE,
        )
        if minute_match:
            minutes = float(minute_match.group(1))
            trailing = re.search(rf"{re.escape(minute_match.group(0))}\s*(\d+)\s*秒", normalized)
            return round(minutes * 60 + (float(trailing.group(1)) if trailing else 0)), True
        if second_match:
            return round(float(second_match.group(1))), True
        chinese_minute = re.search(r"([零〇一二两三四五六七八九十半]+)\s*(?:分钟|分)(半)?", normalized)
        if chinese_minute:
            minutes = cls._chinese_number(chinese_minute.group(1))
            if minutes is not None:
                return round((minutes + (.5 if chinese_minute.group(2) else 0)) * 60), True
        chinese_second = re.search(r"([零〇一二两三四五六七八九十]+)\s*(?:秒钟|秒)", normalized)
        if chinese_second:
            seconds = cls._chinese_number(chinese_second.group(1))
            if seconds is not None:
                return round(seconds), True
        return None, False

    @staticmethod
    def _duration_tolerance(text: str) -> int | None:
        match = re.search(
            r"\d+(?:\.\d+)?\s*(?:±|\+\s*/\s*-|\+\s*-)\s*"
            r"(\d+(?:\.\d+)?)\s*(?:秒钟|秒|s(?![a-z]))",
            str(text or ""),
            re.IGNORECASE,
        )
        return max(0, round(float(match.group(1)))) if match else None

    @staticmethod
    def _relative_duration_request(text: str) -> bool:
        return bool(re.search(
            r"(?:再短一点|再短些|更短(?:一点|些)?|稍微短(?:一点|些)?|"
            r"再精简(?:一点|些)?|再紧凑(?:一点|些)?)",
            str(text or ""),
        ))

    @staticmethod
    def _anchor_start(text: str) -> dict[str, Any] | None:
        match = re.search(
            r"从\s*(?:讲到|讲|提到|介绍|说到|说)?\s*"
            r"(.{1,100}?)(?:的地方|的位置|那里|那儿|处)?\s*"
            r"(?:开始|起)(?:剪|保留|播放|做|生成|编辑)?",
            str(text or ""),
        )
        if not match:
            return None
        query = str(match.group(1) or "").strip(" 　：:，,。；;")
        query = re.sub(r"(?:的)?(?:部分|内容|片段|画面)$", "", query).strip()
        if re.fullmatch(r"[\d\s:.：零一二三四五六七八九十百]+(?:秒|分钟|分)?", query):
            return None
        return {"query": query[:240], "selectionPolicy": "unique_or_review"} if query else None

    @staticmethod
    def _editing_brief(goal: str, context: dict[str, Any]) -> dict[str, Any]:
        text = str(goal or "").strip()
        # Parse requested deliverables only from affirmative clauses. Artifact
        # names inside “不要创建成片/不能沿用旧封面” are constraints, not work
        # the Agent is authorized to perform.
        affirmative_text = re.sub(
            r"(?:不要|不能|不应|无需|不需要)[^，,。；;\n]*",
            "",
            text,
        )
        # Keep the retrieval instruction separate from the conversational
        # wrapper and the requested deliverable.  Sending the whole sentence
        # (for example “upload this video, find X, then make several cuts”)
        # to semantic retrieval used to pollute the evidence query with
        # planning language and made every request look like the same edit.
        anchor_start = AgentPlatform._anchor_start(text)
        retrieval_query = str((anchor_start or {}).get("query") or AgentPlatform._retrieval_query(text))
        source_range = AgentPlatform._source_range(text, context)
        excluded_clauses = re.findall(r"(?:不要|不保留|删除|去掉|排除|剔除|移除)([^，,。；;\n]+)", text)
        target_seconds, explicit_duration = AgentPlatform._duration_target(text)
        explicit_tolerance = AgentPlatform._duration_tolerance(text)
        relative_duration = target_seconds is None and AgentPlatform._relative_duration_request(text)
        input_context = context.get("inputContext") if isinstance(context.get("inputContext"), dict) else {}
        editing_context = context.get("editing") if isinstance(context.get("editing"), dict) else {}
        current_duration = input_context.get("outputDurationSeconds")
        current_duration_source = "referenced_output" if isinstance(current_duration, (int, float)) else ""
        if not isinstance(current_duration, (int, float)):
            current_duration = editing_context.get("currentDurationSeconds")
            current_duration_source = str(editing_context.get("currentDurationSource") or "current_edit")
        unresolved_relative_duration = bool(relative_duration and not (
            isinstance(current_duration, (int, float)) and not isinstance(current_duration, bool)
            and float(current_duration) > 0
        ))
        duration_source = "explicit" if explicit_duration else ""
        if relative_duration and not unresolved_relative_duration:
            target_seconds = max(4, round(float(current_duration) * .8))
            explicit_duration = True
            duration_source = "relative"
        elif target_seconds is None and isinstance(context.get("targetSeconds"), (int, float)):
            target_seconds = int(context["targetSeconds"])
            duration_source = "context"
        if relative_duration:
            # This is a timeline adjustment, not a request to search for the
            # literal phrase “再短一点” inside the video.
            retrieval_query = ""
        interview = bool(re.search(r"访谈|采访|问答|播客|证言", text))
        cover_intro_requested = bool(re.search(r"片头|(?:最)?开头.{0,30}封面|封面.{0,20}(?:放进|合入|加入|插入|作为开头)", affirmative_text))
        cover_intro_only_opening = bool(
            cover_intro_requested
            and not re.search(r"短视频|短片|reel|hook|爆点|口播|切片", text, re.IGNORECASE)
        )
        short_form = bool(
            re.search(r"短视频|短片|reel|hook|爆点|口播|切片", text, re.IGNORECASE)
            or (re.search(r"开头", text) and not cover_intro_only_opening)
        )
        # “短视频/Hook” describes an editorial form, not a duration. Only an
        # explicit user duration may become a hard fitting constraint.
        variants = AgentPlatform._requested_variant_count(text)
        subtitle_requested = bool(re.search(
            r"(?:加上?|添加|生成|制作|配上?|烧录|导出|需要|要有|带)(?:对应的?|顶部|底部|双语|中英|中文|英文|汉语)?字幕"
            r"|字幕(?:稿|文件|样式|校对|审核)|SRT|双语字幕",
            affirmative_text,
            re.IGNORECASE,
        ))
        preview_requested = bool(re.search(r"审阅样片|审核样片|低码率|审阅预览|预览样片", affirmative_text))
        qc_requested = bool(re.search(r"质检|交付检查|检查(?:成片|输出|视频).*(?:质量|交付)|是否可以交付", text))
        social_delivery = AgentPlatform._social_delivery(text)
        cover_requested = bool(re.search(r"封面|缩略图|海报帧|poster\s*frame|thumbnail", affirmative_text, re.IGNORECASE))
        audio_polish_requested = bool(re.search(r"降噪|人声增强|声音增强|音频优化|音量|响度|爆音|削波|静音|背景音乐|混音|音乐压低", affirmative_text))
        broll_requested = bool(re.search(r"穿插|补充画面|补画面|覆盖画面|叠加画面|b-?roll|B-?roll|空镜|产品画面覆盖", affirmative_text, re.IGNORECASE))
        graphics_requested = bool(re.search(
            r"标题卡|参数卡|价格卡|报价卡|角标|标签|贴纸|水印|logo|Logo|CTA|关键词高亮|图文|文字(?!幕)层"
            r"|(?:添加|加上?|叠加|写上?|显示|放上?)[^。；;\n]{0,24}(?:价格|报价)"
            r"|(?:添加|加上?|叠加|写上?|显示|放上?)[^。；;\n]{0,24}(?:文本|文字(?!幕)|文案|说明)",
            affirmative_text,
        ))
        graphics_text_match = re.search(
            r"(?:添加|加上?|叠加|写上?|显示|放上?)[^。；;\n]{0,24}?(?:文本|文字(?!幕)|文案|说明)"
            r"\s*(?:是|为|用|写|内容为|：|:)?\s*[“\"'‘]([^。；;”\"'’\n]{1,120})[”\"'’]",
            text,
        )
        if not graphics_text_match:
            graphics_text_match = re.search(
                r"(?:添加|加上?|叠加|写上?|显示|放上?)[^。；;\n]{0,24}?(?:文本|文字(?!幕)|文案|说明)"
                r"\s*(?:是|为|用|写|内容为|：|:)\s*([^，,。；;\n]{1,120})",
                text,
            )
        graphics_text = str(graphics_text_match.group(1) if graphics_text_match else "").strip(" \t\r\n“”\"'‘’")
        motion_graphics_requested = bool(re.search(
            r"Remotion|HyperFrames?|HTML\s*(?:视频|动效)|动效|动态图文|动态字幕|动态封面|动态片头|标题动画|片头动画|可视化视频",
            text,
            re.IGNORECASE,
        ))
        motion_intro_requested = bool(
            motion_graphics_requested
            and re.search(r"当前成片|已有成片|合入|加入|插入|放到|作为|片头|开头", text)
        )
        draft_export_requested = bool(re.search(r"剪映|CapCut|草稿|工程文件|项目文件|导出草稿|导出工程|外部编辑器", affirmative_text, re.IGNORECASE))
        delivery_export_requested = bool(re.search(r"正式导出|高清导出|导出高清|最终导出|可下载|下载|交付包|发布(?!会)|出片|成品文件", affirmative_text))
        diagnostics_requested = bool(re.search(r"为什么|为何|哪里.{0,8}问题|诊断|排查|卡住|失败|未找到|不合理|怎么回事", text))
        multi_topic_requested = bool(re.search(
            r"分别|各(?:类|段|个|自)|每(?:类|段|个)|\d+\s*段|[一二两三四五六七八九十]\s*段|、.*、",
            retrieval_query or text,
        ))
        composition_requested = bool(re.search(
            r"组合|合成|剪辑|成片|版本|合集|精华|整理(?:成|为)|做成|剪成|剪出来|截出来|制作|编排|删除|去掉|排除|剔除|移除|只保留|重排|缩短|加速|返修",
            affirmative_text,
        ))
        cover_aspect = str(social_delivery.get("aspect") or "16:9")
        cover_title_match = re.search(
            r"(?:封面|缩略图|海报帧)[^。；;\n]{0,20}?(?:标题|文案|文本描述|文字描述|文字)"
            r"\s*(?:是|为|用|写|添加|加上|改成|：|:)?\s*[“\"'‘]?([^，,。；;”\"'’]{1,80})",
            text,
        )
        cover_title = str(cover_title_match.group(1) if cover_title_match else "").strip(" \t\r\n“”\"'‘’")
        # A cover aspect and a video delivery aspect are independent. Keep an
        # explicit vertical/video request when both appear in the same goal;
        # only suppress social delivery for a cover-only request.
        video_format_requested = bool(re.search(
            r"(?:竖屏|横屏|方形|方屏)(?:的)?(?:视频|成片|输出|版本|审核样片|审阅样片|样片)|社媒|抖音|视频号|小红书|reels?|shorts?"
            r"|(?:9:16|4:5|1:1|16:9)\s*(?:的)?(?:视频|成片|输出|版本)"
            r"|(?:视频|成片|输出|版本)\s*(?:为|做成|改成|转换为|设置为)\s*(?:9:16|4:5|1:1|16:9)",
            text, re.IGNORECASE,
        ))
        if cover_requested and not video_format_requested:
            social_delivery = {
                "requested": False, "aspect": "", "fit": "blur", "focusX": .5, "focusY": .5,
            }
        selection_mode = (
            "exclude" if re.search(
                r"(?:删除|去掉|排除|剔除|移除|不保留|不要)"
                r".{0,18}(?:已选|说话人|Speaker|主持人|嘉宾|歌手|人物|这个人|该人物|男性|女性|男生|女生|男人|女人|穿.{0,8}(?:衣|服))",
                text, re.IGNORECASE,
            )
            else "compare" if re.search(r"比较|对比|分别|各自|每个人|每位", text)
            else "include"
        )
        speaker_targeted = bool(re.search(
            r"主持人|嘉宾|说话人|发言人|声音|音色|旁白|(?:女性|男性|女生|男生|女人|男人|某人).{0,8}(?:说话|发言|回答|讲述)|Speaker\s*\d+",
            text, re.IGNORECASE,
        ))
        # An interaction such as “主持人与歌手交谈” is a semantic content
        # target, not an instruction to include or exclude a voice cluster.
        if retrieval_query and re.search(r"交谈|对话|交流|谈话|聊天", retrieval_query):
            speaker_targeted = False
        speaker_label_match = re.search(
            r"(?:说话人|Speaker)\s*([A-ZＡ-Ｚ]|\d{1,2})\b",
            text,
            re.IGNORECASE,
        )
        if speaker_label_match:
            label_clause = next((clause for clause in re.split(r"[，,。；;\n]", text) if speaker_label_match.group(0) in clause), "")
            if re.search(r"只保留|保留|选择", label_clause) and not re.search(r"不要|不保留|排除|删除|去掉", label_clause):
                selection_mode = "include"
        speaker_target_label = (
            f"说话人 {str(speaker_label_match.group(1)).upper()}"
            if speaker_label_match else ""
        )
        # ``人物`` in interview prose usually means respondents, not visual
        # identity tracking.  Requiring an appearance/selection cue keeps
        # requests such as “不同人物关于成长的回答” on the interview
        # workflow instead of launching a multi-thousand-frame body scan.
        person_targeted = not speaker_targeted and bool(re.search(
            r"出镜|人脸|面孔|某人|这个人|该人物|目标人物|"
            r"人物\s*[A-ZＡ-Ｚ0-9一二三四五六七八九十]+|"
            r"(?:选择|确认|指定|识别).{0,8}(?:画面)?人物|"
            r"(?:人物|有哪些人|都有谁).{0,12}(?:选|选择|确认)|"
            r"红衣|黑衣|白衣|蓝衣|穿.{0,8}(?:衣|服)|"
            r"(?:女性|男性|女生|男生|女人|男人).{0,10}(?:出镜|出现|画面)",
            text,
        ))
        person_description_match = re.search(
            r"(穿[^，,。；;]{1,40}?(?:衣|服|上衣)[^，,。；;]{0,12}?(?:人|人物))",
            text,
        )
        person_description = str(
            person_description_match.group(1) if person_description_match else ""
        ).strip()
        # “找到 X” is a complete request in its own right.  It should end in
        # evidence review rather than silently creating a timeline, subtitles,
        # and a sample that the user did not ask for.
        format_only = bool(social_delivery["requested"] and not retrieval_query)
        timeline_requested = bool(
            composition_requested or short_form or variants > 1 or target_seconds or subtitle_requested
            or preview_requested or anchor_start
            or (social_delivery["requested"] and (retrieval_query or format_only))
        )
        # A project output aspect is a delivery default, not a new editing
        # request. Apply it only when this goal already asks for a timeline;
        # a search-only request must still stop at candidate review. Explicit
        # aspect wording in the current goal always wins over the default.
        project_aspect = str((context.get("delivery") or {}).get("outputAspect") or "source")
        if timeline_requested and not social_delivery["requested"] and project_aspect in {"16:9", "9:16", "1:1", "4:5"}:
            social_delivery = {
                "requested": True, "aspect": project_aspect,
                "fit": "crop" if (context.get("delivery") or {}).get("outputFit") == "crop" else "blur",
                "focusX": .5, "focusY": .5,
            }
        return {
            "schemaVersion": 2,
            "goal": text[:1000], "targetSeconds": target_seconds,
            "inheritedContentConstraint": copy.deepcopy((context.get("evidence") or {}).get("contentConstraint"))
            if not retrieval_query and (timeline_requested or social_delivery.get("requested")) else None,
            "durationExplicit": explicit_duration,
            "durationSource": duration_source or "none",
            "relativeDurationBaseSeconds": round(float(current_duration), 3)
            if relative_duration and not unresolved_relative_duration else None,
            "relativeDurationBaseSource": current_duration_source if relative_duration else "",
            "unresolvedRelativeDuration": unresolved_relative_duration,
            "durationToleranceSeconds": (
                explicit_tolerance if explicit_tolerance is not None
                else 15 if target_seconds == 180
                else max(5, round((target_seconds or 60) * .1))
            ),
            "themeOrganized": bool(re.search(r"主题|按.*回答|访谈|采访|问答", text)),
            "interview": interview,
            "removeRepetition": bool(re.search(r"重复|冗余|精简|删", text)),
            "speakerTargeted": speaker_targeted,
            "speakerTargetLabel": speaker_target_label,
            "personTargeted": person_targeted,
            "personDescription": person_description,
            "subjectKind": "speaker" if speaker_targeted else "person" if person_targeted else "content",
            "selectionMode": selection_mode,
            "keepQuestionContext": (interview or bool(re.search(r"提问|上下文|转场", affirmative_text))) and not any("提问" in clause or "问题" in clause for clause in excluded_clauses),
            "shortForm": short_form,
            "specificContentTarget": bool(retrieval_query) or bool(re.search(r"围绕|关于|主题|观点|案例|演示|说过|讲到", text)),
            "retrievalQuery": retrieval_query,
            "anchorStart": copy.deepcopy(anchor_start),
            # A cover supplements a video deliverable; it must never turn an
            # explicit short-video/edit request into a cover-only workflow.
            "delivery": "timeline" if timeline_requested else "artifact" if cover_requested else "candidates",
            "variantCount": variants,
            "requiresEvidenceReview": bool(
                timeline_requested and (retrieval_query or interview or speaker_targeted)
            ),
            "subtitleRequested": subtitle_requested,
            "reviewPreviewRequested": preview_requested,
            "deliveryQcRequested": qc_requested,
            "coverIntroRequested": cover_intro_requested,
            "audioPolishRequested": audio_polish_requested,
            "brollRequested": broll_requested,
            "graphicsRequested": graphics_requested,
            "graphicsText": graphics_text,
            "motionGraphicsRequested": motion_graphics_requested,
            "motionIntroRequested": bool(motion_intro_requested),
            "draftExportRequested": draft_export_requested,
            "deliveryExportRequested": delivery_export_requested,
            "diagnosticsRequested": diagnostics_requested,
            "multiTopicRequested": multi_topic_requested,
            "formatOnly": format_only,
            "socialDelivery": social_delivery,
            "coverRequested": cover_requested,
            "coverAspect": cover_aspect,
            "coverTitle": cover_title,
            "sourceScope": "custom" if source_range else str(context.get("sourceScope") or "all"),
            "sourceRange": source_range,
            "excludedContent": [clause for clause in excluded_clauses if not re.search(r"字幕|封面|复用|重复使用|默认|创建|生成|渲染|导出|时长|秒|分钟", clause)],
            "distinctSourceAcrossVariants": bool(re.search(r"(?:不要|不允许|禁止|不能|不得|不)\s*(?:重复使用|复用|重复).{0,8}(?:片段|镜头|素材)", text)),
        }

    @staticmethod
    def _retrieval_query(goal: str) -> str:
        """Extract the semantic target, never the surrounding task chatter."""
        text = re.sub(r"\s+", " ", str(goal or "")).strip()
        if not text:
            return ""
        # Agent-entry messages can carry source metadata and an instruction
        # prefix.  Neither is evidence the video search should try to match.
        text = re.sub(r"(?:上传|从)\s*[^，,；;：:]{1,160}?\s*(?:，|,|；|;)?\s*(?:交给|让)?\s*(?:智能)?剪辑\s*Agent\s*[:：]?", "", text, flags=re.I)
        text = re.sub(r"(?:素材范围|范围)\s*[:：].*$", "", text, flags=re.I)
        # A generic highlight request describes an editorial ranking task,
        # not a semantic phrase that must literally occur in the media.
        if re.search(r"最精彩的部分|精彩部分|高光(?:视频|成片|片段)?", text) and not re.search(
            r"关于|围绕|介绍|讲解|讲到|提到|指定主题|找到|查找|搜索|检索|找出", text
        ):
            return ""
        enumerated = re.search(
            r"(?:分别(?:是|为)|包括|包含)\s*[:：]?\s*(.{2,160}?)(?=(?:[。！？!?；;]|每(?:个|段)|各(?:个|段)|$))",
            text,
        )
        about_answer = re.search(
            r"关于\s*(.{2,160}?)\s*的(?:回答|回应|发言|观点|内容)",
            text,
        )
        natural_extract = re.search(
            r"(?:把|将)?\s*((?:介绍|讲解|讲到|提到|讨论|说到).{1,120}?)"
            r"(?:的)?(?:部分|片段|内容|画面)?\s*(?:剪出来|截出来|提取出来|保留下来)(?:[。！？!?,，]|$)",
            text,
        )
        match = enumerated or about_answer or natural_extract or re.search(
            r"(?:(?:只\s*)?(?:找出|找到|查找|搜索|检索|定位|提取|截取)(?:并列出)?\s*[:：]?\s*|^(?:只保留|保留)\s*[:：]?\s*)"
            r"(.{2,160}?)(?=(?:[，,；;。！？!?]|并(?:且|做|生成|给|合成|剪辑|制作|组合|删除|去掉|排除)?|然后|随后|再|做成|剪成|制作|组合|合成)|$)",
            text,
        )
        value = match.group(1) if match else ""
        value = re.sub(r"^(?:所有|全部|视频中|素材中|其中的?)\s*", "", value).strip()
        value = re.sub(r"^关于", "", value).strip()
        value = re.sub(r"(?:的)?候选片段(?:和|及)?源视频时间$", "", value).strip()
        value = re.sub(r"(?:的)?(?:相关)?(?:视频)?(?:片段|画面|镜头|内容|场景|部分)$", "", value).strip(" ：:，,。；;")
        if enumerated and value:
            return f"分别查找{value}，各类片段作为并列候选"[:240]
        if not value:
            # Quick-mode followups often pass only a noun phrase such as
            # “产品新老替换和核心卖点”.  Treat that as the semantic target
            # instead of falling back to the whole Agent goal or shortform
            # routing.  Exclude operational UI commands so “生成计划/重启服务”
            # does not become a media retrieval query.
            phrase = text.strip(" ：:，,。；;")
            if (
                2 <= len(phrase) <= 80
                and not re.search(
                    r"上传|交给|Agent|生成|合成|剪辑|剪一个|导出|输出|封面|字幕|竖屏|横屏|方形|方屏|"
                    r"审核|审阅|预览|样片|短视频|短片|Hook|hook|成片|交付|检查|计划|规划|重启|"
                    r"修复|优化|为什么|为何|怎么|如何|打不开|卡住|失败|测试|9:16|4:5|1:1|16:9",
                    phrase,
                    re.IGNORECASE,
                )
            ):
                value = phrase
        return value[:240]

    @staticmethod
    def _replan_force_replay_tools(failed_step: dict[str, Any]) -> set[str]:
        """Invalidate an upstream artifact known to have caused the failure."""
        failed_tool = str(failed_step.get("tool") or "")
        if failed_tool in {
            "analyze_highlights",
            "search_content",
            "discover_people",
            "discover_speakers",
            "propose_timeline_edit",
            "render_review_preview",
            "run_delivery_qc",
        }:
            return {failed_tool}
        if (
            failed_tool == "review_content_evidence"
            and any(
                message in str(failed_step.get("error") or "")
                for message in (
                    "没有生成可用于自动编排的有效候选",
                    "自动编排缺少必要类别的候选",
                )
            )
        ):
            return {"search_content"}
        return set()

    @staticmethod
    def _automatic_replan_block_reason(failed_step: dict[str, Any]) -> str:
        """Return why rebuilding the same DAG cannot repair this failure."""
        error = str(failed_step.get("error") or "")
        if (
            str(failed_step.get("tool") or "") == "review_content_evidence"
            and "自动编排缺少必要类别的候选" in error
        ):
            return "missing_required_evidence_category"
        return ""

    @staticmethod
    def _requested_variant_count(goal: str) -> int:
        text = str(goal or "")
        short = re.search(r"(?:做|生成|给我|提供)\s*([2-4两二三四])\s*版(?:[，,。；;\s]|$)", text)
        if short:
            return int(short[1]) if short[1].isdigit() else {"两": 2, "二": 2, "三": 3, "四": 4}[short[1]]
        # Explicit counts win; generic “different versions/cuts” intentionally
        # defaults to three choices so the promise is observable and useful.
        match = re.search(r"(?:生成|给我|做|提供)?\s*([2-4])\s*(?:个|种|版)?\s*(?:不同的?)?(?:成片|版本|剪辑方案|剪法)", text)
        if match:
            return int(match.group(1))
        chinese = re.search(r"(?:两|二|三|四)\s*(?:个|种|版)?\s*(?:不同的?)?(?:成片|版本|剪辑方案|剪法)", text)
        if chinese:
            return {"两": 2, "二": 2, "三": 3, "四": 4}.get(chinese.group(0)[0], 3)
        if re.search(r"不同(?:的)?(?:成片|版本|剪辑方案|剪法)|多个(?:成片|版本|剪辑方案)|多版", text):
            return 3
        return 1

    @staticmethod
    def _social_delivery(goal: str) -> dict[str, Any]:
        """Return a delivery-format request without confusing it with the edit goal."""
        text = str(goal or "").lower()
        if "9:16" in text or re.search(
            r"(?:合成|生成|输出|做(?:成|一个|一条)?|剪成|制作|转换为|改成).{0,18}竖屏|竖屏(?:的)?(?:视频|成片|输出|版本)",
            text,
        ):
            aspect = "9:16"
        elif "1:1" in text or re.search(r"方(?:形|屏)", text):
            aspect = "1:1"
        elif "4:5" in text:
            aspect = "4:5"
        elif "16:9" in text or re.search(
            r"(?:合成|生成|输出|做成|剪成|制作|转换为|改成).{0,18}横屏|横屏(?:的)?(?:视频|成片|输出|版本)",
            text,
        ):
            aspect = "16:9"
        elif re.search(r"小红书|抖音|reels?|shorts?|视频号|竖屏", text, re.IGNORECASE):
            aspect = "9:16"
        else:
            aspect = ""
        if re.search(r"中心裁切|居中裁切|裁满|裁切铺满|放大裁切|\bcrop\b", text):
            fit = "crop"
        elif re.search(r"留黑|黑边|黑色留边|\bpad\b", text):
            fit = "pad"
        else:
            # Any unspecified aspect conversion must preserve the complete
            # source composition. Fill the unused canvas with a blurred copy
            # instead of silently cropping content from any edge.
            fit = "blur"
        focus_x = .25 if re.search(r"主体靠左|焦点靠左|人物靠左", text) else .75 if re.search(r"主体靠右|焦点靠右|人物靠右", text) else .5
        focus_y = .25 if re.search(r"主体靠上|焦点靠上", text) else .75 if re.search(r"主体靠下|焦点靠下", text) else .5
        return {"requested": bool(aspect), "aspect": aspect, "fit": fit, "focusX": focus_x, "focusY": focus_y}

    @classmethod
    def _skill_routing_eligibility(
        cls, skill: dict[str, Any], *, brief: dict[str, Any], context: dict[str, Any],
    ) -> tuple[bool, str]:
        """Reject a format-conversion Skill when the user still needs a source edit.

        A platform name or aspect ratio is delivery metadata.  It must never
        displace an explicit source-content query such as “find X and make a
        cut”.  Social reframing also has a hard media precondition: an
        existing accepted output to use as its source.
        """
        profile = cls._profile_for_skill(skill)
        kind = str(profile.get("kind") or "")
        delivery = cls._social_delivery(str(brief.get("goal") or ""))
        editing = context.get("editing") if isinstance(context.get("editing"), dict) else {}
        has_outputs = bool(editing.get("hasOutputs"))
        source_edit_requested = bool(brief.get("retrievalQuery")) and str(brief.get("delivery") or "") == "timeline"
        if kind in {"social-reframe", "dynamic-reframe"} and source_edit_requested:
            return False, "请求仍需从源片检索并组合内容，不能直接改画幅"
        if kind in {"social-reframe", "dynamic-reframe"} and not has_outputs:
            return False, "画幅转换需要当前任务已有可审核成片；不能拿源视频或其他任务输出代替"
        if kind == "audio-polish" and not has_outputs:
            return False, "音频优化需要当前任务已有可试听成片；不能拿源视频或其他任务输出代替"
        if kind == "platform-delivery" and not has_outputs:
            return False, "正式交付需要当前任务已有审核通过的成片；不能导出源视频或其他任务输出"
        if kind == "cover-intro" and not has_outputs:
            return False, "封面片头需要当前任务已有成片；不能先生成无归属封面或复用其他任务封面"
        if kind == "local-motion" and bool(brief.get("motionIntroRequested")) and not has_outputs:
            return False, "动态图文片头合成需要当前任务已有成片；不能先生成无法合入的独立动效"
        if kind == "delivery-qc" and source_edit_requested:
            return False, "请求仍需先生成内容剪辑，不能只运行交付质检"
        if kind == "delivery-qc" and not has_outputs:
            return False, "交付质检需要已有成片"
        if kind == "local-draft":
            return True, ""
        has_timeline = bool(editing.get("hasActiveSession"))
        if (
            kind in {"caption-layout", "graphics-package", "broll-overlay"}
            or str(skill.get("id") or "") == "cliptalk-subtitle-editor"
        ) and not has_timeline:
            return False, "该编辑需要当前任务已有已确认时间线；不能重新分析源视频或复用其他任务的编辑结果"
        return True, ""

    @classmethod
    def _skill_precondition_descriptor(
        cls, skill: dict[str, Any], *, brief: dict[str, Any], context: dict[str, Any],
    ) -> dict[str, str] | None:
        eligible, reason = cls._skill_routing_eligibility(skill, brief=brief, context=context)
        if eligible:
            return None
        kind = str(cls._profile_for_skill(skill).get("kind") or "")
        if kind in {"caption-layout", "graphics-package", "broll-overlay"} or str(skill.get("id") or "") == "cliptalk-subtitle-editor":
            required_state, code = "active_timeline", "missing_current_timeline"
        elif kind in {"social-reframe", "dynamic-reframe", "audio-polish", "platform-delivery", "cover-intro", "delivery-qc"} or (
            kind == "local-motion" and bool(brief.get("motionIntroRequested"))
        ):
            required_state, code = "current_output", "missing_current_output"
        else:
            required_state, code = "compatible_request", "incompatible_skill_goal"
        return {
            "requiredState": required_state,
            "preconditionCode": code,
            "preconditionMessage": reason,
        }

    @staticmethod
    def _profile_for_skill(skill: dict[str, Any]) -> dict[str, Any]:
        known = SKILL_PROFILES.get(str(skill.get("id") or ""))
        if known:
            return {"kind": known["kind"], "tools": set(known["tools"]), "managed": True}
        allowed = {str(item) for item in skill.get("allowedTools") or [] if str(item)}
        requested_kind = str(skill.get("workflowProfile") or "").strip().lower()
        requested = next((value for value in SKILL_PROFILES.values() if value["kind"] == requested_kind), None)
        if requested and set(requested["tools"]).issubset(allowed):
            return {"kind": requested["kind"], "tools": set(requested["tools"]), "managed": True}
        return {"kind": "custom", "tools": allowed, "managed": False}

    @staticmethod
    def _supports_autonomous_review(skills: list[dict[str, Any]]) -> bool:
        """Only first-party workflow Skills may silently cross review gates."""
        return bool(skills) and all(
            str(skill.get("id") or "") in SKILL_PROFILES
            and str(skill.get("source") or "") in {"builtin", "test"}
            and not skill.get("pluginId")
            for skill in skills
        )

    def _enabled_skill_for_kind(self, kind: str) -> dict[str, Any] | None:
        return next((
            item for item in self.store.list(
                "skills", newest_first=False,
                predicate=lambda candidate: candidate.get("status") == "enabled",
            )
            if str(self._profile_for_skill(item).get("kind") or "") == str(kind)
        ), None)

    def _compose_skills(
        self, primary: dict[str, Any], *, brief: dict[str, Any], context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build one auditable Skill chain without letting add-ons steal the edit goal."""
        skills = [primary]
        kinds = {str(self._profile_for_skill(primary).get("kind") or "custom")}

        def append_kind(kind: str, *, required: bool = True) -> None:
            if kind in kinds:
                return
            skill = self._enabled_skill_for_kind(kind)
            if skill is None:
                if required:
                    raise ValueError(f"当前缺少已启用的 {kind} Skill，无法完整覆盖用户要求")
                return
            skills.append(skill)
            kinds.add(kind)

        primary_kind = next(iter(kinds))
        # Audit and diagnostic Skills mention many artifact names while
        # describing what they inspect. Those nouns are not requests to create
        # a cover, export, reframe, or edit, so their workflow must stay read-only.
        if primary_kind in {"source-provenance", "edit-diagnostics", "delivery-qc"}:
            return skills
        if primary_kind == "revision" and brief.get("retrievalQuery"):
            append_kind("content")
        if (
            bool(brief.get("socialDelivery", {}).get("requested"))
            and primary_kind not in {"social-reframe", "dynamic-reframe", "local-motion"}
        ):
            append_kind("social-reframe")
        if bool(brief.get("coverIntroRequested")) and "cover-intro" not in kinds:
            append_kind("cover-intro", required=False)
        explicit_caption_position = bool(re.search(
            r"字幕.{0,16}(?:顶部|上方|顶端|底部|下方|底端)|(?:顶部|上方|顶端|底部|下方|底端).{0,16}字幕",
            str(brief.get("goal") or ""),
        ))
        if (
            bool(brief.get("subtitleRequested"))
            and (primary_kind == "revision" or explicit_caption_position)
            and "caption-layout" not in kinds
        ):
            append_kind("caption-layout", required=False)
        if bool(brief.get("audioPolishRequested")) and "audio-polish" not in kinds:
            append_kind("audio-polish", required=False)
        if bool(brief.get("brollRequested")) and "broll-overlay" not in kinds:
            append_kind("broll-overlay", required=False)
        if bool(brief.get("graphicsRequested")) and "graphics-package" not in kinds:
            append_kind("graphics-package", required=False)
        if bool(brief.get("deliveryQcRequested")) and "delivery-qc" not in kinds and "social-reframe" not in kinds:
            append_kind("delivery-qc")
        if bool(brief.get("coverRequested")) and "cover" not in kinds and primary_kind != "cover-intro":
            append_kind("cover")
        if bool(brief.get("deliveryExportRequested")) and "platform-delivery" not in kinds:
            append_kind("platform-delivery", required=False)
        return skills

    @staticmethod
    def _skill_chain_payload(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{
            "id": item["id"], "version": item.get("version") or "1.0.0",
            "contentHash": item.get("contentHash") or "",
            "role": "primary" if index == 0 else "addon",
            "workflowProfile": item.get("workflowProfile") or "",
        } for index, item in enumerate(skills)]

    def _resolve_skill_chain(
        self, primary: dict[str, Any], raw_chain: Any,
    ) -> list[dict[str, Any]]:
        resolved = [primary]
        for value in raw_chain if isinstance(raw_chain, list) else []:
            skill_id = str(value.get("id") or "") if isinstance(value, dict) else ""
            if not skill_id or skill_id == primary.get("id"):
                continue
            skill = self.store.get("skills", skill_id)
            if skill and skill.get("status") == "enabled":
                resolved.append(skill)
        return resolved

    def _compile_profile_plan(
        self, raw: dict[str, Any], *, skill: dict[str, Any], goal: str, context: dict[str, Any],
        skills: list[dict[str, Any]] | None = None,
        execution_mode: str = AUTONOMOUS_REVIEW,
    ) -> dict[str, Any]:
        """Compile a stable plan skeleton from facts; keep LLM prose as metadata.

        This removes conditional workflow choice from the model for built-in
        Skills. Custom Skills remain constrained by their declared tool set.
        """
        result = copy.deepcopy(raw) if isinstance(raw, dict) else {}
        strategy = result.get("strategy") if isinstance(result.get("strategy"), dict) else {}
        selected_skills = skills or [skill]
        profile = self._profile_for_skill(skill)
        mode = (
            str(execution_mode) if str(execution_mode) in VALID_EXECUTION_MODES
            else AUTONOMOUS_REVIEW
        )
        if not self._supports_autonomous_review(selected_skills):
            mode = STEPWISE_REVIEW
        profile_kinds = {str(self._profile_for_skill(item).get("kind") or "custom") for item in selected_skills}
        # A standalone cover task ends in an explicit creative choice. Keep
        # that task in review mode even when cover generation is an automatic
        # add-on to a larger editing workflow.
        if str(profile.get("kind") or "") == "cover":
            mode = STEPWISE_REVIEW
        brief = self._editing_brief(goal, context)
        # Plans created before the duration-inference fix may still carry the
        # legacy 30s short-form default. Content retrieval must never inherit
        # that implicit cap unless the user explicitly requested a duration.
        if (not brief.get("durationExplicit")
                and brief.get("specificContentTarget")
                and brief.get("targetSeconds") is not None):
            brief["targetSeconds"] = None
        result["brief"] = brief
        result["planningContext"] = context
        result["profile"] = profile["kind"]
        result["executionMode"] = mode
        result["skillChain"] = self._skill_chain_payload(selected_skills)
        if not profile["managed"]:
            return result

        tool_map = {item["name"]: item for item in self.tool_catalog()}
        steps: list[dict[str, Any]] = []
        decision: list[dict[str, Any]] = []

        def add(tool: str, title: str, arguments: dict[str, Any], output: str, dependencies: list[str] | None = None) -> str:
            referenced_output = (context.get("inputContext") or {}).get("outputFilename")
            if referenced_output and tool == "render_social_preview" and not any(s["tool"] == "render_review_preview" for s in steps):
                arguments = {**arguments, "filename": referenced_output}
            source_range = brief.get("sourceRange")
            if tool in {"analyze_highlights", "search_content", "discover_people", "discover_speakers"} and source_range:
                if source_range.get("requiresDuration"):
                    raise ValueError("尚未读取素材时长，无法确定末尾范围，请在素材就绪后重试")
                arguments = {**arguments, "sourceScopeKind": "custom", "sourceScopeStart": source_range["start"], "sourceScopeEnd": source_range["end"]}
            step_id = f"step_{len(steps) + 1}_{tool}"
            steps.append({
                "id": step_id, "title": title, "tool": tool, "arguments": arguments,
                "dependencies": list(dependencies) if dependencies is not None else ([steps[-1]["id"]] if steps else []), "expectedOutput": output,
                "sideEffect": tool_map[tool]["sideEffect"], "estimatedSeconds": 0, "optional": False,
            })
            return step_id

        def qc_arguments() -> dict[str, Any]:
            arguments: dict[str, Any] = {"strict": True}
            if isinstance(brief.get("targetSeconds"), (int, float)):
                arguments["targetSeconds"] = float(brief["targetSeconds"])
                arguments["toleranceSeconds"] = float(
                    brief.get("durationToleranceSeconds") or 0
                )
            return arguments

        kind = str(profile["kind"])
        precondition = self._skill_precondition_descriptor(
            skill, brief=brief, context=context,
        )
        if precondition:
            add(
                "inspect_workspace", "检查所选编辑能力的前置条件",
                precondition,
                "当前任务前置条件状态；缺失时返回结构化说明并停止后续操作",
            )
            reason = precondition["preconditionMessage"]
            result["summary"] = f"先检查当前任务是否满足所选编辑能力的前置条件。{reason}。不会分析源视频、复用其他任务结果或启动渲染。"
            result["steps"] = steps
            result["decisionRecord"] = [{
                "rule": "skill_precondition",
                "outcome": "stop_with_clear_limitation",
                "reason": reason,
            }]
            return result
        add("inspect_workspace", "核查可复用素材与分析结果", {}, "素材、转写、证据和已有编辑状态")
        speaker = context.get("speaker") if isinstance(context.get("speaker"), dict) else {}
        people = context.get("people") if isinstance(context.get("people"), dict) else {}
        has_candidates = bool((context.get("evidence") or {}).get("hasCandidates")) if isinstance(context.get("evidence"), dict) else False
        # The deterministic brief owns the evidence query.  A planning model
        # may describe the strategy, but it must not expand a concise target
        # into a long list of guessed objects/actions that makes retrieval both
        # slower and less precise.
        explicit_retrieval_query = str(
            brief.get("retrievalQuery") or strategy.get("searchQuery") or ""
        ).strip()
        retrieval_query = explicit_retrieval_query or str(brief["goal"]).strip()
        if brief.get("excludedContent"):
            retrieval_query += "；不要" + "、".join(brief["excludedContent"])
        needs_timeline = (
            str(brief.get("delivery") or "timeline") == "timeline"
            and kind not in {
                "delivery-qc", "social-reframe", "cover", "source-provenance",
                "dynamic-reframe", "cover-intro", "caption-layout", "audio-polish",
                "broll-overlay", "graphics-package", "local-motion", "local-draft",
                "platform-delivery", "edit-diagnostics",
            }
        )
        requested_variants = max(1, min(4, int(brief.get("variantCount") or 1)))
        timeline_step_id: str | None = None

        if kind == "source-provenance":
            add("validate_task_provenance", "校验当前任务素材边界", {"strict": True}, "当前任务、源素材、范围和可复用产物的归属报告")
            decision.append({"rule": "task_provenance", "outcome": "validate", "reason": "目标要求核对任务隔离或防止旧状态复用"})
        elif kind == "edit-diagnostics":
            add("diagnose_edit_failure", "诊断当前剪辑流程问题", {"focus": brief["goal"][:240]}, "失败原因、受影响产物和可执行下一步")
            decision.append({"rule": "diagnostics", "outcome": "inspect", "reason": "目标要求解释失败、卡住或界面结果异常"})
        elif kind == "local-motion":
            editing = context.get("editing") if isinstance(context.get("editing"), dict) else {}
            social = brief.get("socialDelivery") if isinstance(brief.get("socialDelivery"), dict) else {}
            aspect = str(social.get("aspect") or brief.get("coverAspect") or "9:16")
            duration = max(0.5, min(8.0, float(brief.get("targetSeconds") or 1.5)))
            title_text = str(brief.get("coverTitle") or brief.get("retrievalQuery") or brief.get("goal") or "")[:120]
            motion_step = add(
                "render_motion_graphics",
                "生成本地图文动效视频",
                {
                    "title": title_text,
                    "subtitle": str(brief.get("goal") or "")[:180],
                    "aspect": aspect,
                    "duration": duration,
                    "theme": "cliptalk",
                },
                "由本地 HTML/Playwright/FFmpeg 管线生成的动效视频",
            )
            qc_dependency = motion_step
            if bool(brief.get("motionIntroRequested")) and bool(editing.get("hasOutputs")):
                qc_dependency = add(
                    "compose_motion_intro",
                    "合成动态图文片头成片",
                    {},
                    "带本地图文动效片头的新成片版本",
                    [motion_step],
                )
            add("run_delivery_qc", "检查动效视频质量", qc_arguments(), "动效视频质检报告", [qc_dependency])
            decision.append({"rule": "local_motion", "outcome": "html_video", "reason": "目标要求本地图文动效、标题卡或片头"})
        elif kind == "local-draft":
            add(
                "export_editing_draft",
                "导出本地剪辑草稿包",
                {"format": "cliptalk-json"},
                "包含当前时间线、输出版本和封面引用的本地草稿包",
            )
            decision.append({"rule": "local_draft", "outcome": "cliptalk_json", "reason": "目标要求导出草稿或外部编辑器工程"})
        elif kind == "dynamic-reframe":
            delivery = brief.get("socialDelivery") if isinstance(brief.get("socialDelivery"), dict) else {}
            aspect = str(delivery.get("aspect") or "9:16")
            fit = str(delivery.get("fit") or "blur")
            safe_step = add("analyze_reframe_safe_areas", "分析画幅安全区", {"aspect": aspect, "fit": fit}, "人物、字幕、文字和主体保护策略")
            social_step = add(
                "render_social_preview", f"生成 {aspect} 画幅审核预览",
                {"aspect": aspect, "fit": fit, "focusX": float(delivery.get("focusX", .5)), "focusY": float(delivery.get("focusY", .5))},
                f"不覆盖原成片的 {aspect} 审核预览", [safe_step],
            )
            add("run_delivery_qc", "检查画幅预览质量", qc_arguments(), "画幅预览的完整质检报告", [social_step])
            decision.append({"rule": "dynamic_reframe", "outcome": fit, "reason": f"按当前成片生成 {aspect} 画幅预览"})
        elif kind == "cover-intro":
            aspect = str(brief.get("coverAspect") or "16:9")
            title_text = str(brief.get("coverTitle") or "")[:80]
            candidate_arguments: dict[str, Any] = {
                "sourceScope": "accepted_cut", "candidateBudget": 16,
                "aspectRatios": [aspect], "focus": str(brief.get("goal") or "")[:240],
            }
            if title_text:
                candidate_arguments["titleText"] = title_text
            cover_candidate_step = add("propose_cover_candidates", "提取并评分封面候选", candidate_arguments, "当前任务内可追溯封面候选")
            render_arguments: dict[str, Any] = {
                "aspectRatios": [aspect],
                "directions": ["source_clean", "source_editorial", "source_cinematic"],
            }
            if title_text:
                render_arguments["titleText"] = title_text
            cover_variant_step = add("render_cover_variants", "生成封面预览版本", render_arguments, "不覆盖当前封面的封面预览", [cover_candidate_step])
            cover_review_step = add("review_cover_variants", "选择当前任务封面", {}, "已选择的当前任务封面", [cover_variant_step])
            cover_confirm_step = add("confirm_cover", "保存当前任务封面", {}, "已绑定当前任务的封面版本", [cover_review_step])
            intro_step = add("compose_cover_intro", "合成封面片头", {"duration": 1.0}, "带当前封面片头的新成片版本", [cover_confirm_step])
            add("run_delivery_qc", "检查封面片头成片质量", qc_arguments(), "封面片头成片质检报告", [intro_step])
            decision.append({"rule": "cover_intro", "outcome": "compose", "reason": "目标要求封面出现在视频开头"})
        elif kind == "caption-layout":
            position = "top" if re.search(r"顶部|上方|顶端", str(brief.get("goal") or "")) else "bottom"
            subtitle_step = add(
                "prepare_subtitle_review",
                "自动生成并校对字幕草稿" if mode == AUTONOMOUS_REVIEW else "生成字幕校对稿",
                {
                    "style": "clean",
                    "requireConfirmedDraft": mode != AUTONOMOUS_REVIEW,
                    "autoReview": mode == AUTONOMOUS_REVIEW,
                },
                (
                    "与当前时间线对应、可在成片阶段继续修改的自动校对字幕草稿"
                    if mode == AUTONOMOUS_REVIEW else
                    "与当前时间线对应、待人工校对的字幕草稿"
                ),
            )
            layout_step = add(
                "layout_subtitles", "应用字幕排版策略",
                {"position": position, "style": "clean"},
                "在已确认字幕草稿上应用布局，不改动字幕文字",
                [subtitle_step],
            )
            add("render_review_preview", "生成带字幕最终审核样片", {"subtitleMode": "burned_in_review_watermarked_low_bitrate"}, "带已确认字幕与布局的最终审核样片", [layout_step])
            decision.append({
                "rule": "caption_layout", "outcome": position,
                "reason": (
                    "自动生成并校对字幕草稿，应用排版后直接生成带字幕审核样片；成片阶段仍可修改"
                    if mode == AUTONOMOUS_REVIEW else
                    "生成字幕校对稿，经人工确认后应用排版并生成带字幕样片"
                ),
            })
        elif kind == "audio-polish":
            polish_step = add(
                "polish_audio_mix", "生成音频优化版本",
                {"noiseReduction": bool(brief.get("audioPolishRequested")), "voiceFirst": True},
                "不覆盖原输出的音频优化版本",
            )
            add("run_delivery_qc", "检查音频优化版本质量", qc_arguments(), "音频优化版本质检报告", [polish_step])
            decision.append({"rule": "audio_polish", "outcome": "normalize", "reason": "目标要求音频优化或响度处理"})
        elif kind == "broll-overlay":
            add("search_content", "检索辅助画面素材", {"query": retrieval_query[:500] or brief["goal"][:500]}, "可作为 B-roll 的视觉候选")
            review_step = add(
                "review_content_evidence",
                "自动筛选辅助画面候选" if mode == AUTONOMOUS_REVIEW else "确认辅助画面候选",
                {"query": retrieval_query[:500] or brief["goal"][:500], "minimumSelection": 1},
                "已确认的辅助画面候选",
            )
            broll_step = add("propose_broll_overlay", "加入辅助画面插入轨", {"query": retrieval_query[:500] or brief["goal"][:500], "maxOverlays": 6}, "当前时间线的 B-roll 插入草稿", [review_step])
            add("render_review_preview", "生成辅助画面审核预览", {"subtitleMode": "none"}, "带辅助画面的审核样片", [broll_step])
            decision.append({"rule": "broll_overlay", "outcome": "cutaways", "reason": "目标要求穿插或覆盖辅助画面"})
        elif kind == "graphics-package":
            graphics_step = add(
                "render_graphics_package", "添加图文包装层",
                {"text": str(brief.get("graphicsText") or brief.get("retrievalQuery") or "")[:120], "placement": "top", "style": "clean"},
                "当前时间线的可编辑图文层",
            )
            add("render_review_preview", "生成图文包装审核预览", {"subtitleMode": "none"}, "带图文包装的审核样片", [graphics_step])
            decision.append({"rule": "graphics_package", "outcome": "text_layers", "reason": "目标要求标题、标签、参数卡或水印"})
        elif kind == "platform-delivery":
            delivery = brief.get("socialDelivery") if isinstance(brief.get("socialDelivery"), dict) else {}
            export_step = add(
                "export_delivery_master", "导出正式交付版本",
                {"platform": "generic", "aspect": str(delivery.get("aspect") or "")},
                "需要明确授权的正式交付文件",
            )
            add("run_delivery_qc", "检查正式交付质量", qc_arguments(), "正式交付文件质检报告", [export_step])
            decision.append({"rule": "delivery_export", "outcome": "requires_approval", "reason": "正式导出必须保留明确确认点"})
        elif kind == "multi-topic":
            add(
                "search_content", "提取多主题剪辑证据",
                {"query": retrieval_query[:500]},
                "每个必需主题的候选时间段、证据与可用上下文",
            )
            if needs_timeline:
                add(
                    "select_multi_topic_evidence",
                    "自动筛选多主题候选片段" if mode == AUTONOMOUS_REVIEW else "确认多主题候选片段",
                    {"query": retrieval_query[:500], "minimumPerTopic": 1},
                    "每个主题至少一个可靠候选，缺失则返回无结果",
                )
            decision.append({"rule": "multi_topic", "outcome": "balanced_selection", "reason": "目标包含多个必需主题或分段配额"})
        elif kind in {"highlight", "shortform"} and not has_candidates:
            if bool(brief.get("formatOnly")):
                decision.append({
                    "rule": "source_passthrough",
                    "outcome": "full_source_timeline",
                    "reason": "仅改变画幅或安全区，直接以完整素材建立时间线，不执行高光筛选",
                })
            elif kind == "shortform" and bool(brief["specificContentTarget"]):
                add("search_content", "提取指定主题的 Hook 证据", {
                    "query": retrieval_query[:500],
                }, "可作为短视频开场和完整观点的内容证据")
                decision.append({"rule": "shortform_evidence", "outcome": "search", "reason": "目标指定了主题或观点"})
                if needs_timeline:
                    add(
                        "review_content_evidence",
                        "自动筛选短视频候选片段" if mode == AUTONOMOUS_REVIEW else "确认短视频候选片段",
                        {"query": retrieval_query[:500], "minimumSelection": 1},
                        "用户确认的 Hook 与正文候选",
                    )
            else:
                highlight_arguments: dict[str, Any] = {"instruction": brief["goal"]}
                if brief.get("targetSeconds") is not None:
                    highlight_arguments["targetSeconds"] = brief["targetSeconds"]
                add(
                    "analyze_highlights", "提取高光候选",
                    highlight_arguments, "按内容质量排序的高光证据",
                )
                decision.append({"rule": "highlight_evidence", "outcome": "analyze", "reason": "未发现可复用高光候选"})
        elif kind in {"content", "interview", "speaker"} or (kind == "revision" and "content" in profile_kinds):
            requires_speaker_scope = kind == "speaker" or bool(brief["speakerTargeted"])
            if requires_speaker_scope and bool(speaker.get("needsDiscovery")):
                add("discover_speakers", "补全说话人证据", {}, "说话人分段与角色置信度")
                decision.append({"rule": "speaker_evidence", "outcome": "discover", "reason": "现有说话人证据不可用"})
            needs_speaker_confirmation = requires_speaker_scope and (
                bool(speaker.get("needsConfirmation"))
                or (not bool(speaker.get("selectedCount")) and kind == "speaker")
            )
            if needs_speaker_confirmation and mode != AUTONOMOUS_REVIEW:
                add("select_speakers", "确认目标说话人与保留方式", {"mode": brief.get("selectionMode") or "include"}, "已保存的说话人范围")
                decision.append({"rule": "speaker_identity", "outcome": "confirm", "reason": str(speaker.get("confirmationReason") or "目标涉及特定声音或角色不确定")})
            elif needs_speaker_confirmation:
                add(
                    "select_speakers", "Agent 核定目标说话人",
                    {
                        "mode": brief.get("selectionMode") or "include",
                        "label": brief.get("speakerTargetLabel") or "",
                    },
                    "可靠证据支持的说话人范围，无法消歧时返回无结果",
                )
                decision.append({
                    "rule": "speaker_identity", "outcome": "evidence_rank_or_no_result",
                    "reason": "自动模式不插入说话人确认点；仅采用可靠证据，无法消歧时返回无结果",
                })
            search_query = retrieval_query
            review_query = retrieval_query
            if kind == "interview":
                # Subtitle delivery is downstream rendering, not evidence that
                # the source contains useful screen text. Keep interview
                # discovery on spoken Q&A so a request to add subtitles does
                # not trigger a full-source OCR/visual scan.
                if explicit_retrieval_query:
                    search_query = (
                        f"仅根据对白检索：分别检索以下回答主题：{explicit_retrieval_query}；"
                        "各主题作为独立候选，不要求同一片段同时命中；"
                        "口头提问仅作为回答的可选上下文补齐，不作为必选主题；"
                        "不使用画面或屏幕文字作为主题证据"
                    )[:500]
                    review_query = explicit_retrieval_query
                else:
                    search_query = (
                        "仅根据对白检索：访谈中的完整回答、观点、经历和问答内容；"
                        "口头提问仅作为回答的可选上下文补齐，不作为必选主题；"
                        "去重、长停顿、字幕和生成样片属于剪辑要求，不作为检索主题；"
                        "不使用画面或屏幕文字作为主题证据"
                    )[:500]
                    review_query = "访谈完整回答和必要问题上下文"
            if brief.get("anchorStart") and re.search(
                r"从\s*(?:讲到|讲|提到|介绍|说到|说)", str(brief.get("goal") or "")
            ) and not re.search(r"画面|屏幕|镜头|字幕|文字|出现|展示", str(brief.get("goal") or "")):
                search_query = f"仅根据对白检索：{brief['anchorStart']['query']}；定位相关发言，不使用画面或屏幕文字作为证据"
            add(
                "search_content",
                "检索目标内容" if not needs_timeline else "提取剪辑证据",
                {"query": search_query[:500]},
                "与目标相关的候选时间段、证据与可用上下文",
            )
            decision.append({
                "rule": "semantic_query", "outcome": "search",
                "reason": f"从任务描述中抽取检索目标“{search_query[:80]}”",
            })
            if needs_timeline and bool(brief.get("requiresEvidenceReview")):
                review_arguments: dict[str, Any] = {
                    "query": review_query[:500], "minimumSelection": 1,
                }
                if brief.get("anchorStart"):
                    review_arguments["selectionPolicy"] = "unique_or_review"
                add(
                    "review_content_evidence",
                    "核定起剪位置" if brief.get("anchorStart") else
                    "自动筛选用于组合的候选片段" if mode == AUTONOMOUS_REVIEW else
                    "确认用于组合的候选片段",
                    review_arguments,
                    (
                        "Agent 自动选定的候选片段及其排列范围"
                        if mode == AUTONOMOUS_REVIEW else "用户确认的候选片段及其排列范围"
                    ),
                )
                decision.append({
                    "rule": "evidence_review",
                    "outcome": "unique_or_review" if brief.get("anchorStart") else
                    "auto_select" if mode == AUTONOMOUS_REVIEW else "confirm",
                    "reason": (
                        "自动模式由 Agent 依据有效证据筛选并保存候选"
                        if mode == AUTONOMOUS_REVIEW else "用户同时要求检索与组合成片，需先审核候选"
                    ),
                })
        elif kind == "person":
            if bool(people.get("needsDiscovery")):
                add("discover_people", "发现画面人物", {}, "人物簇与出镜区间")
            if (
                bool(people.get("needsConfirmation", not bool(people.get("selectedCount"))))
                and mode != AUTONOMOUS_REVIEW
            ):
                add("select_people", "确认目标人物与保留方式", {"mode": brief.get("selectionMode") or "include"}, "已保存的人物范围")
            elif bool(people.get("needsConfirmation", not bool(people.get("selectedCount")))):
                add(
                    "select_people", "Agent 核定目标人物",
                    {
                        "mode": brief.get("selectionMode") or "include",
                        "description": brief.get("personDescription") or "",
                    },
                    "可靠证据支持的人物范围，无法消歧时返回无结果",
                )
                decision.append({
                    "rule": "person_identity", "outcome": "evidence_rank_or_no_result",
                    "reason": "自动模式不插入人物确认点；仅采用可靠证据，无法消歧时返回无结果",
                })
        elif kind == "revision":
            decision.append({"rule": "source_analysis", "outcome": "reuse", "reason": "返修流程不重新分析源素材"})
        elif kind == "delivery-qc":
            add("run_delivery_qc", "检查成片交付质量", qc_arguments(), "逐文件质检报告与可追踪问题")
            decision.append({"rule": "delivery_qc", "outcome": "analyze", "reason": "对现有成片运行确定性媒体检查"})
        elif kind == "social-reframe":
            delivery = brief.get("socialDelivery") if isinstance(brief.get("socialDelivery"), dict) else {}
            aspect = str(delivery.get("aspect") or "9:16")
            fit = str(delivery.get("fit") or "blur")
            add(
                "render_social_preview", f"生成 {aspect} 社媒审核预览",
                {"aspect": aspect, "fit": fit, "focusX": float(delivery.get("focusX", .5)), "focusY": float(delivery.get("focusY", .5))},
                f"不覆盖原成片的 {aspect} 审核预览",
            )
            add("run_delivery_qc", "检查社媒预览质量", qc_arguments(), "画幅预览的完整质检报告")
            decision.append({"rule": "social_reframe", "outcome": fit, "reason": f"按请求生成 {aspect} 预览"})
        elif kind == "cover":
            aspect = str(brief.get("coverAspect") or "16:9")
            title_text = str(brief.get("coverTitle") or "")[:80]
            candidate_arguments: dict[str, Any] = {
                "sourceScope": "accepted_cut",
                "candidateBudget": 16,
                "aspectRatios": [aspect],
                "focus": str(brief.get("goal") or "")[:240],
            }
            if title_text:
                candidate_arguments["titleText"] = title_text
            cover_candidate_step = add(
                "propose_cover_candidates", "提取并评分封面候选",
                candidate_arguments,
                "带源时间、证据、六维评分和去重结果的封面候选集",
            )
            render_arguments: dict[str, Any] = {
                "aspectRatios": [aspect],
                "directions": ["source_clean", "source_editorial", "source_cinematic"],
            }
            if title_text:
                render_arguments["titleText"] = title_text
            cover_variant_step = add(
                "render_cover_variants", "生成三种本地封面预览",
                render_arguments,
                "三种不覆盖当前封面的可追溯封面预览",
                [cover_candidate_step],
            )
            cover_review_step = add("review_cover_variants", "自动优选当前任务封面", {}, "按当前主题和画幅自动选择的封面候选", [cover_variant_step])
            add("confirm_cover", "保存当前任务封面", {}, "已绑定当前任务的封面版本", [cover_review_step])
            decision.append({
                "rule": "cover_generation", "outcome": "local_source_variants",
                "reason": f"从当前任务生成 {aspect} 的三种源帧封面方向，不调用外部生成服务",
            })

        # Managed profiles own the executable timeline instruction.  The model
        # may describe a strategy, but it must not turn a render/QC recovery
        # into a different edit (for example by inventing speed changes).
        # Keeping this value deterministic also lets a replan safely reuse an
        # already applied timeline when its source request did not change.
        instruction = str(brief["goal"] or strategy.get("timelineInstruction") or "")
        if brief["targetSeconds"]:
            instruction = f"{instruction}；目标 {brief['targetSeconds']} 秒，允许浮动 ±{brief['durationToleranceSeconds']} 秒"
        if brief.get("anchorStart"):
            anchor_query = str(brief["anchorStart"].get("query") or "")
            instruction = (
                f"{instruction}；以已核定的“{anchor_query}”匹配片段作为新时间线起点，"
                "移除此前内容，保留后续可用编辑内容"
            )
        if kind == "shortform":
            instruction = f"{instruction}；前 1–3 秒必须进入明确 Hook，保留完整观点或动作，不使用片头、空白铺垫或重复表达"
        if needs_timeline:
            timeline_title = (
                f"建立精剪时间线并准备 {requested_variants} 种结构方向"
                if requested_variants > 1 else "建立可审阅精剪时间线"
            )
            timeline_output = (
                f"以已确认候选为依据，可生成 {requested_variants} 种结构方向的待审核草案"
                if requested_variants > 1 else "尚未应用的可编辑时间线草案"
            )
            timeline_arguments: dict[str, Any] = {
                "instruction": instruction[:500], "variantCount": requested_variants,
            }
            if brief.get("targetSeconds") is not None:
                timeline_arguments.update({
                    "targetSeconds": float(brief["targetSeconds"]),
                    "toleranceSeconds": float(brief["durationToleranceSeconds"]),
                    "durationSource": str(brief.get("durationSource") or "explicit"),
                })
            if brief.get("anchorStart"):
                timeline_arguments["anchorStartQuery"] = str(
                    brief["anchorStart"].get("query") or ""
                )[:240]
            if brief.get("distinctSourceAcrossVariants"):
                timeline_arguments["distinctSourceAcrossVariants"] = True
            variant_directions = [str(item)[:240] for item in strategy.get("variantDirections") or []][:requested_variants]
            if variant_directions:
                timeline_arguments["variantDirections"] = variant_directions
            add("propose_timeline_edit", timeline_title, timeline_arguments, timeline_output)
            timeline_step_id = add(
                "confirm_timeline_edit",
                "验证并应用时间线方案" if mode == AUTONOMOUS_REVIEW else "确认并应用时间线草案",
                {}, "已应用并保存的时间线",
            )
        subtitle_dependency_id = timeline_step_id
        subtitle_requested = bool(brief.get("subtitleRequested")) and kind != "caption-layout"
        subtitle_position = "top" if re.search(
            r"字幕.{0,16}(?:顶部|上方|顶端)|(?:顶部|上方|顶端).{0,16}字幕",
            str(brief.get("goal") or ""),
        ) else "bottom"
        if subtitle_requested:
            subtitle_dependency_id = add(
                "prepare_subtitle_review",
                "自动生成并校对字幕草稿" if mode == AUTONOMOUS_REVIEW else "生成字幕校对稿",
                {
                    "style": "clean",
                    "requireConfirmedDraft": mode != AUTONOMOUS_REVIEW,
                    "autoReview": mode == AUTONOMOUS_REVIEW,
                },
                (
                    "与已应用时间线对应、可在成片阶段继续修改的自动校对字幕草稿"
                    if mode == AUTONOMOUS_REVIEW else
                    "与已应用时间线对应、待人工校对的字幕草稿"
                ),
                [timeline_step_id] if timeline_step_id else None,
            )
            if "caption-layout" in profile_kinds:
                subtitle_dependency_id = add(
                    "layout_subtitles",
                    "应用顶部字幕排版" if subtitle_position == "top" else "应用字幕排版策略",
                    {"position": subtitle_position, "style": "clean"},
                    "在已确认字幕草稿上应用布局，不改动字幕文字",
                    [subtitle_dependency_id],
                )
                decision.append({
                    "rule": "caption_layout",
                    "outcome": subtitle_position,
                    "reason": "目标明确要求字幕位置，先生成并确认字幕，再调整布局并渲染审核样片",
                })
        preview_dependency_id = subtitle_dependency_id or timeline_step_id
        review_preview_step_id: str | None = None
        if subtitle_requested:
            review_preview_step_id = add(
                "render_review_preview", "生成带字幕最终审核样片",
                {"subtitleMode": "burned_in_review_watermarked_low_bitrate"},
                "带已确认字幕与布局的最终审核样片",
                [preview_dependency_id] if preview_dependency_id else None,
            )
        elif bool(brief.get("reviewPreviewRequested")) or (mode == AUTONOMOUS_REVIEW and needs_timeline):
            review_preview_step_id = add(
                "render_review_preview", "准备低码率审阅样片",
                {"subtitleMode": "burned_in_review_watermarked_low_bitrate"},
                "带轻水印的审阅样片",
                [preview_dependency_id] if preview_dependency_id else None,
            )
        cover_confirm_step_id: str | None = None
        if kind != "cover" and bool(brief.get("coverRequested")) and "cover" in profile_kinds:
            aspect = str(brief.get("coverAspect") or "16:9")
            title_text = str(brief.get("coverTitle") or "")[:80]
            candidate_arguments: dict[str, Any] = {
                "sourceScope": "accepted_cut",
                "candidateBudget": 16,
                "aspectRatios": [aspect],
                "focus": str(brief.get("goal") or "")[:240],
            }
            if title_text:
                candidate_arguments["titleText"] = title_text
            cover_candidate_step = add(
                "propose_cover_candidates", "提取并评分封面候选",
                candidate_arguments,
                "带源时间、证据、六维评分和去重结果的封面候选集",
                [timeline_step_id] if timeline_step_id else None,
            )
            render_arguments: dict[str, Any] = {
                "aspectRatios": [aspect],
                "directions": ["source_clean", "source_editorial", "source_cinematic"],
            }
            if title_text:
                render_arguments["titleText"] = title_text
            cover_variant_step = add(
                "render_cover_variants", "生成三种本地封面预览",
                render_arguments,
                "三种不覆盖当前封面的可追溯封面预览",
                [cover_candidate_step],
            )
            cover_review_step = add("review_cover_variants", "自动优选当前任务封面", {}, "按当前主题和画幅自动选择的封面候选", [cover_variant_step])
            cover_confirm_step_id = add("confirm_cover", "保存当前任务封面", {}, "已绑定当前任务的封面版本", [cover_review_step])
            decision.append({
                "rule": "cover_generation", "outcome": "local_source_variants",
                "reason": f"从当前成片生成 {aspect} 的三种源帧封面方向，不调用外部生成服务",
            })
        social = brief.get("socialDelivery") if isinstance(brief.get("socialDelivery"), dict) else {}
        final_delivery_step_id: str | None = review_preview_step_id
        delivery_qc_needed = False
        if kind not in {"social-reframe", "dynamic-reframe", "local-motion", "delivery-qc"} and bool(social.get("requested")):
            if not bool(brief.get("reviewPreviewRequested")) and mode != AUTONOMOUS_REVIEW:
                review_preview_step_id = add(
                    "render_review_preview", "生成画幅转换所需的审核输出",
                    {"subtitleMode": "none"}, "不覆盖原版本的已确认时间线输出",
                    [preview_dependency_id] if preview_dependency_id else None,
                )
            aspect = str(social.get("aspect") or "9:16")
            social_dependency_id = review_preview_step_id or preview_dependency_id
            social_step = add(
                "render_social_preview", f"生成 {aspect} 社媒审核预览",
                {"aspect": aspect, "fit": str(social.get("fit") or "blur"),
                 "focusX": float(social.get("focusX", .5)), "focusY": float(social.get("focusY", .5))},
                f"不覆盖原成片的 {aspect} 审核预览",
                [social_dependency_id] if social_dependency_id else None,
            )
            final_delivery_step_id = social_step
            delivery_qc_needed = True
        if (
            kind != "cover-intro"
            and bool(brief.get("coverIntroRequested"))
            and "cover-intro" in profile_kinds
            and cover_confirm_step_id
        ):
            intro_dependencies = [cover_confirm_step_id]
            if final_delivery_step_id:
                intro_dependencies.append(final_delivery_step_id)
            elif preview_dependency_id:
                intro_dependencies.append(preview_dependency_id)
            intro_step = add(
                "compose_cover_intro", "合成封面片头审核样片",
                {"duration": 1.0},
                "带当前任务封面片头的最终审核样片",
                intro_dependencies,
            )
            final_delivery_step_id = intro_step
            delivery_qc_needed = True
            decision.append({
                "rule": "cover_intro",
                "outcome": "compose_review_preview",
                "reason": "目标要求封面出现在视频开头，因此封面确认后继续合成审核样片",
            })
        if delivery_qc_needed and final_delivery_step_id:
            add(
                "run_delivery_qc",
                "检查最终审核样片质量" if bool(brief.get("coverIntroRequested")) else "检查社媒预览质量",
                qc_arguments(),
                "最终审核样片的完整质检报告",
                [final_delivery_step_id],
            )
        elif kind not in {"social-reframe", "dynamic-reframe", "local-motion", "delivery-qc"} and bool(brief.get("deliveryQcRequested")):
            if needs_timeline and not bool(brief.get("reviewPreviewRequested")):
                add("render_review_preview", "生成质检所需的审核输出", {"subtitleMode": "none"}, "已确认时间线的审核输出")
            add("run_delivery_qc", "检查成片交付质量", qc_arguments(), "逐文件质检报告与可追踪问题")
        target = (f"目标区间约 {brief['targetSeconds']}±{brief['durationToleranceSeconds']} 秒（实际时长将在候选与时间线确认后确定）"
                  if brief["targetSeconds"] else "不设时长上限，完整保留符合条件的片段（完成后统计实际时长）")
        if kind == "delivery-qc":
            result["summary"] = "检查已有成片的可解码性、时长、音画流、黑帧、冻结、静音和响度；不修改或导出媒体。"
        elif kind == "social-reframe":
            result["summary"] = "从已有成片生成不覆盖原文件的社媒画幅审核预览，使用双遍响度规范化，并在完成后运行交付质检。"
        elif kind == "cover":
            result["summary"] = (
                f"从已有成片优先提取并评分封面候选，生成 {brief.get('coverAspect') or '16:9'} 的三种本地审核预览。"
                "选择后保存为新的封面版本；不修改视频、不覆盖历史封面，也不发布到外部平台。"
            )
        elif kind == "source-provenance":
            result["summary"] = "校验当前 Agent 工作区、源素材、范围和可复用产物是否都属于本次任务；不修改媒体。"
        elif kind == "edit-diagnostics":
            result["summary"] = "诊断当前剪辑流程的失败或异常状态，输出具体原因和下一步；不修改媒体。"
        elif kind == "dynamic-reframe":
            result["summary"] = "从当前成片生成目标画幅审核预览，默认完整保留原画面并用虚化背景补齐，同时运行质检。"
        elif kind == "cover-intro":
            result["summary"] = "从当前任务生成并确认封面，然后把封面合成为当前成片片头并质检；不会复用其他任务封面。"
        elif kind == "caption-layout":
            result["summary"] = "为当前时间线生成字幕排版草稿并渲染审核预览，优先满足位置、安全区和可读性要求。"
        elif kind == "audio-polish":
            result["summary"] = "基于当前成片生成音频优化版本，进行响度规范化和保守降噪后运行质检。"
        elif kind == "broll-overlay":
            result["summary"] = "检索并加入相关辅助画面插入轨，保留主音频，完成后生成审核预览。"
        elif kind == "graphics-package":
            result["summary"] = "在当前时间线添加可编辑图文包装层，并生成审核预览。"
        elif kind == "local-motion":
            result["summary"] = "生成动态图文、标题卡或片头视频。"
        elif kind == "local-draft":
            result["summary"] = "导出当前任务本地剪辑草稿包，供外部编辑器映射使用；不会写入剪映或其他第三方目录。"
        elif kind == "platform-delivery":
            result["summary"] = "确认效果后生成可下载的成片。"
        elif kind == "multi-topic":
            result["summary"] = (
                f"按多个必需主题整理素材，{target}。"
                "保留各主题的相关片段，缺少内容时提示你补充。"
            )
        elif not needs_timeline:
            result["summary"] = (
                f"查找与“{retrieval_query[:100]}”相关的片段，供你预览和选择。"
            )
        elif kind == "interview" and mode == STEPWISE_REVIEW:
            result["summary"] = (
                f"将访谈素材剪辑为{target}的主题精华：一次性检索核心回答、必要提问、自然转场和可删重复，"
                "按主题保留完整观点并删除冗余表达。确认片段后生成剪辑预览。"
            )
        else:
            variant_clause = (
                f"自动选择片段，生成 {requested_variants} 个剪辑预览。"
                if mode == AUTONOMOUS_REVIEW and requested_variants > 1 else
                "自动选择片段并生成剪辑预览。"
                if mode == AUTONOMOUS_REVIEW else
                f"先确认片段，再比较 {requested_variants} 种剪辑方案。"
                if requested_variants > 1 else "先确认片段，再安排播放顺序。"
            )
            delivery_clause = (
                f"随后自动生成 {social.get('aspect')} 社媒审核预览并质检。"
                if bool(social.get("requested")) and mode == AUTONOMOUS_REVIEW else
                f"确认后生成 {social.get('aspect')} 预览。"
                if bool(social.get("requested")) else ""
            )
            final_clause = (
                "同时生成封面供你选择。"
                if mode == AUTONOMOUS_REVIEW and bool(brief.get("coverRequested"))
                else ""
            )
            result["summary"] = (
                f"将素材剪辑为{target}的视频。{variant_clause}"
                f"{delivery_clause}{final_clause}"
            )
        constraints = []
        if brief.get("sourceRange"):
            scope = brief["sourceRange"]
            constraints.append(f"素材范围 {scope['start']:g}–{scope['end']:g} 秒")
        if brief.get("excludedContent"):
            constraints.append("排除：" + "、".join(brief["excludedContent"]))
        if brief.get("subtitleRequested"):
            constraints.append("生成字幕")
        if brief.get("distinctSourceAcrossVariants"):
            constraints.append("各版本不得复用源片段；无法满足时停止并说明原因")
        if constraints:
            result["summary"] += " 要求：" + "；".join(constraints) + "。"
        result["steps"] = steps
        result["decisionRecord"] = decision
        return result

    def create_workspace(self, *, job_id: str, title: str = "") -> dict[str, Any]:
        for existing in self.store.list("workspaces"):
            if existing.get("jobId") == job_id:
                return existing
        workspace = self.store.save("workspaces", {
            "id": f"ws_{uuid.uuid4().hex}", "jobId": job_id,
            "title": title or "智能剪辑工作区", "revision": 1,
            "status": "ready", "activePlanId": None,
        })
        self.store.append_event(workspace["id"], "workspace.created", {"workspace": workspace})
        self._notify_workspace_state(workspace)
        return workspace

    def workspace_for_job(self, job_id: str) -> dict[str, Any] | None:
        return next((
            item for item in self.store.list("workspaces")
            if str(item.get("jobId") or "") == str(job_id)
        ), None)

    def bind_workspace_to_job(
        self, *, workspace_id: str, job_id: str, source_job_id: str = "",
    ) -> dict[str, Any]:
        workspace = self.store.get("workspaces", workspace_id)
        if not workspace:
            raise KeyError(workspace_id)
        workspace["jobId"] = job_id
        if source_job_id:
            workspace.setdefault("sourceJobId", source_job_id)
        workspace = self.store.save("workspaces", workspace)
        plan = self.store.get("plans", str(workspace.get("activePlanId") or ""))
        self._notify_workspace_state(workspace, plan)
        return workspace

    def active_plan_for_workspace(self, workspace: dict[str, Any]) -> dict[str, Any] | None:
        plan_id = str(workspace.get("activePlanId") or "")
        if plan_id:
            plan = self.store.get("plans", plan_id)
            if plan and str(plan.get("status") or "") in ACTIVE_PLAN_STATUSES:
                return plan
        return next((
            item for item in self.store.list(
                "plans", predicate=lambda candidate: candidate.get("workspaceId") == workspace.get("id"),
            )
            if str(item.get("status") or "") in ACTIVE_PLAN_STATUSES
        ), None)

    def _enabled_skill(self, skill_id: str | None) -> dict[str, Any]:
        if skill_id:
            skill = self.store.get("skills", skill_id)
            if not skill or skill.get("status") != "enabled":
                raise ValueError("指定的 Skill 不存在或尚未启用")
            return skill
        enabled = self.store.list(
            "skills", newest_first=False,
            predicate=lambda item: item.get("status") == "enabled",
        )
        if not enabled:
            raise ValueError("当前没有已启用的 Skill")
        raise ValueError("自动 Skill 路由需要提供当前目标")

    def route_skill(self, goal: str, *, planning_context: dict[str, Any] | None = None) -> dict[str, Any]:
        enabled = self.store.list(
            "skills", newest_first=False,
            predicate=lambda item: item.get("status") == "enabled",
        )
        if not enabled:
            raise ValueError("当前没有已启用的 Skill")
        context = planning_context if isinstance(planning_context, dict) else {}
        brief = self._editing_brief(goal, context)
        eligible = [
            item for item in enabled
            if self._skill_routing_eligibility(item, brief=brief, context=context)[0]
        ]
        if not eligible:
            raise ValueError("当前没有满足素材前置条件的 Skill；请先生成或选择一个可审核成片")
        editing = context.get("editing") if isinstance(context.get("editing"), dict) else {}
        source_edit_requested = str(brief.get("delivery") or "") == "timeline" and bool(
            brief.get("retrievalQuery") or re.search(r"高光|最精彩|精彩部分", str(goal or ""))
        )
        revision_requested = bool(editing.get("hasActiveSession") or editing.get("hasOutputs")) and bool(
            brief.get("durationSource") == "relative"
            or brief.get("anchorStart")
            or re.search(
                r"当前成片|已有成片|时间线|二次精剪|返修|重排|缩短|恢复|加字幕|添加文本|添加文字|加文字|叠加文字",
                str(goal or ""),
            )
        )
        preferred_kind = ""
        if bool(brief.get("diagnosticsRequested")):
            preferred_kind = "edit-diagnostics"
        elif (
            re.search(r"新任务|同一源|同源|复用|沿用|旧任务|串(?:任务|用)|上个任务|上一次", str(goal or ""))
            and re.search(r"检查|核查|校验|验证|排查|是否|有没有|误用|串用", str(goal or ""))
        ):
            preferred_kind = "source-provenance"
        elif revision_requested and (brief.get("durationSource") == "relative" or brief.get("anchorStart")):
            preferred_kind = "revision"
        elif bool(brief.get("draftExportRequested")) and not source_edit_requested:
            preferred_kind = "local-draft"
        elif bool(brief.get("motionGraphicsRequested")) and not source_edit_requested:
            preferred_kind = "local-motion"
        elif bool(brief.get("deliveryExportRequested")) and bool(editing.get("hasOutputs")) and not source_edit_requested:
            preferred_kind = "platform-delivery"
        elif bool(brief.get("audioPolishRequested")) and bool(editing.get("hasOutputs")) and not source_edit_requested:
            preferred_kind = "audio-polish"
        elif bool(brief.get("socialDelivery", {}).get("requested")) and bool(editing.get("hasOutputs")) and not source_edit_requested:
            preferred_kind = "dynamic-reframe"
        elif bool(brief.get("deliveryQcRequested")) and bool(editing.get("hasOutputs")) and not source_edit_requested:
            preferred_kind = "delivery-qc"
        elif revision_requested:
            if bool(brief.get("subtitleRequested")):
                preferred_kind = "caption-layout"
            elif bool(brief.get("graphicsRequested")):
                preferred_kind = "graphics-package"
            elif bool(brief.get("brollRequested")):
                preferred_kind = "broll-overlay"
            else:
                preferred_kind = "revision"
        elif bool(brief.get("multiTopicRequested")) and bool(brief.get("retrievalQuery")):
            preferred_kind = "multi-topic"
        elif bool(brief.get("speakerTargeted")):
            preferred_kind = "speaker"
        elif bool(brief.get("personTargeted")):
            preferred_kind = "person"
        elif bool(brief.get("interview")):
            preferred_kind = "interview"
        elif bool(brief.get("shortForm")):
            preferred_kind = "shortform"
        elif bool(brief.get("retrievalQuery")):
            preferred_kind = "content"
        elif str(brief.get("delivery") or "") == "timeline":
            # A format/aspect request that also asks for a new cut is a
            # highlight edit unless the user actually identifies a person,
            # speaker, interview structure, or semantic retrieval target.
            # Leaving this to model routing allowed words such as “主播” to
            # select the identity editor and manufacture an unnecessary gate.
            preferred_kind = "highlight"
        if preferred_kind:
            deterministic = next((
                item for item in eligible
                if str(self._profile_for_skill(item).get("kind") or "") == preferred_kind
            ), None)
            if deterministic:
                return deterministic
        result = self.client.route_skill({
            "goal": goal, "model": self.model_config_resolver(),
            "skills": [{
                "id": item["id"], "description": item["description"],
                "version": item["version"], "contentHash": item["contentHash"],
            } for item in eligible],
            "routingHints": {
                "sourceEditRequested": bool(brief.get("retrievalQuery")) and str(brief.get("delivery") or "") == "timeline",
                "hasExistingOutputs": bool((context.get("editing") or {}).get("hasOutputs")),
                "socialDelivery": self._social_delivery(goal),
            },
        })
        selected_id = str(result.get("skillId") or "")
        selected = next((item for item in eligible if item["id"] == selected_id), None)
        if not selected:
            raise AgentServiceError("Agent 没有选择有效的 Skill")
        return selected

    def create_plan(
        self, *, workspace_id: str, goal: str, skill_id: str | None = None,
        execution_mode: str = AUTONOMOUS_REVIEW,
        input_context: dict[str, Any] | None = None, replaces_plan_id: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        workspace, skill, payload = self.prepare_plan_request(
            workspace_id=workspace_id, goal=goal, skill_id=skill_id,
            execution_mode=execution_mode,
            input_context=input_context, replaces_plan_id=replaces_plan_id, message_id=message_id,
        )
        try:
            try:
                result = self.client.plan(payload)
                return self.persist_plan_result(
                    workspace=workspace, skill=skill, goal=goal, result=result,
                    execution_mode=execution_mode,
                )
            except (AgentServiceError, ValueError) as error:
                return self.persist_fallback_plan(
                    workspace=workspace, skill=skill, goal=goal,
                    execution_mode=execution_mode, error=error,
                )
        finally:
            self.release_plan_request(
                workspace_id, request_id=str(workspace.get("planningRequestId") or ""),
            )

    def persist_fallback_plan(
        self, *, workspace: dict[str, Any], skill: dict[str, Any], goal: str,
        execution_mode: str, error: Exception,
    ) -> dict[str, Any]:
        """Compile a deterministic plan only for first-party managed Skills."""
        if not bool(self._profile_for_skill(skill).get("managed")):
            raise error
        warning = str(error)[:500]
        plan = self.persist_plan_result(
            workspace=workspace, skill=skill, goal=goal,
            result={
                "plan": {
                    "summary": goal,
                    "strategy": {},
                    "planningSource": "deterministic_fallback",
                    "planningWarning": warning,
                },
                "events": [{
                    "phase": "plan_ready", "title": "已切换本地确定性规划",
                    "detail": "在线规划服务暂不可用，已按内置 Skill 工作流生成可确认计划。",
                }],
            },
            execution_mode=execution_mode,
        )
        self.store.append_event(str(workspace["id"]), "planning.fallback", {
            "planId": plan["id"], "reason": warning,
        })
        return plan

    def prepare_plan_request(
        self, *, workspace_id: str, goal: str, skill_id: str | None = None,
        execution_mode: str = AUTONOMOUS_REVIEW,
        input_context: dict[str, Any] | None = None, replaces_plan_id: str | None = None,
        message_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        normalized_mode = str(execution_mode or AUTONOMOUS_REVIEW)
        if normalized_mode not in VALID_EXECUTION_MODES:
            raise ValueError("Agent 执行方式无效")
        planning_brief = self._editing_brief(goal, {})
        planning_surface = "editor" if (
            str(planning_brief.get("delivery") or "") == "timeline"
            or bool(planning_brief.get("anchorStart"))
            or bool(planning_brief.get("durationSource") == "relative")
            or bool(re.search(
                r"当前成片|已有成片|时间线|二次精剪|返修|重排|缩短|恢复|加字幕|添加文本|添加文字|加文字|叠加文字",
                str(goal or ""),
            ))
        ) else "agent"
        with self._execution_lock:
            workspace = self.store.get("workspaces", workspace_id)
            if not workspace:
                raise KeyError(workspace_id)
            active_plan = self.active_plan_for_workspace(workspace)
            replacing = bool(active_plan and active_plan["id"] == replaces_plan_id and active_plan.get("status") == "awaiting_confirmation")
            if (active_plan and not replacing) or workspace.get("planningRequestId"):
                raise ValueError("当前已有正在生成、等待确认或执行中的 Agent 计划；请先在计划面板完成、停止或取消该计划")
            workspace.update({
                "status": "planning", "planningRequestId": f"planning_{uuid.uuid4().hex}",
                "planningStartedAt": now_iso(), "planningExecutionMode": normalized_mode,
                "planningSurface": planning_surface,
                "planningInputContext": copy.deepcopy(input_context or {}),
                "replacesPlanId": replaces_plan_id if replacing else None,
                "planningMessageId": message_id,
            })
            workspace = self.store.save("workspaces", workspace)
        try:
            self._notify_workspace_state(workspace)
            planning_context = self._planning_context(str(workspace.get("jobId") or ""))
            planning_context["inputContext"] = copy.deepcopy(input_context or {})
            if (input_context or {}).get("outputAspect"):
                planning_context["delivery"] = {"outputAspect": input_context["outputAspect"], "outputFit": input_context.get("outputFit", "blur")}
            ranges = (input_context or {}).get("sourceRanges") or []
            if len(ranges) == 1:
                planning_context.update({"sourceScope": "custom", "sourceRange": ranges[0]})
            brief = self._editing_brief(goal, planning_context)
            if brief.get("unresolvedRelativeDuration"):
                raise ValueError("找不到当前成片的可用时长，无法理解“再短一点”。请先选择一个成片版本，或直接说明目标秒数。")
            skill = self._enabled_skill(skill_id) if skill_id else self.route_skill(goal, planning_context=planning_context)
            eligible, reason = self._skill_routing_eligibility(skill, brief=brief, context=planning_context)
            # An explicitly selected Skill is allowed to produce a structured
            # prerequisite result. Automatic routing still excludes it so an
            # inapplicable editor can never displace a valid source workflow.
            if not eligible and not skill_id:
                raise ValueError(f"当前 Skill 不适用于该目标：{reason}")
            profile = self._profile_for_skill(skill)
            skills = self._compose_skills(skill, brief=brief, context=planning_context)
            model = self.model_config_resolver()
            catalog = self.tool_catalog()
        except Exception:
            self.release_plan_request(
                workspace_id, request_id=str(workspace.get("planningRequestId") or ""),
            )
            raise
        allowed_tools = sorted({
            tool for item in skills for tool in self._profile_for_skill(item).get("tools", set())
        })
        payload = {
            "requestId": str(workspace.get("planningRequestId") or ""),
            "workspaceId": workspace_id, "sessionDir": str(self.sessions_root),
            "goal": goal, "skill": {
                "id": skill["id"], "version": skill["version"],
                "contentHash": skill["contentHash"], "markdown": skill["skillMarkdown"],
            },
            "skills": [{
                "id": item["id"], "version": item["version"],
                "contentHash": item["contentHash"], "markdown": item["skillMarkdown"],
                "role": "primary" if index == 0 else "addon",
                "workflowProfile": self._profile_for_skill(item)["kind"],
            } for index, item in enumerate(skills)],
            "workspace": {"jobId": workspace["jobId"], "revision": workspace["revision"]},
            "planningContext": planning_context, "brief": brief,
            "executionMode": normalized_mode,
            "profile": {"kind": profile["kind"], "managed": bool(profile["managed"]), "allowedTools": allowed_tools},
            "toolCatalog": catalog, "model": model,
        }
        return workspace, skill, payload

    def release_plan_request(self, workspace_id: str, *, request_id: str = "") -> None:
        """Clear an in-flight planning reservation after stream completion/error."""
        with self._execution_lock:
            workspace = self.store.get("workspaces", workspace_id)
            if not workspace:
                return
            current_request_id = str(workspace.get("planningRequestId") or "")
            if not current_request_id or (request_id and current_request_id != request_id):
                return
            workspace.pop("planningRequestId", None)
            workspace.pop("planningStartedAt", None)
            workspace.pop("planningExecutionMode", None)
            workspace.pop("planningSurface", None)
            if not workspace.get("activePlanId"):
                workspace["status"] = "ready"
            else:
                previous = self.store.get("plans", workspace["activePlanId"])
                if previous and previous.get("status") == "awaiting_confirmation":
                    workspace["status"] = "awaiting_plan_confirmation"
            workspace.pop("planningInputContext", None)
            workspace.pop("planningMessageId", None)
            workspace.pop("replacesPlanId", None)
            workspace = self.store.save("workspaces", workspace)
        self._notify_workspace_state(workspace)

    def recover_stale_planning_requests(self, *, max_age_seconds: float | None = None) -> int:
        """Release reservations whose owning HTTP planning stream no longer exists."""
        maximum_age = max(
            30.0,
            float(max_age_seconds if max_age_seconds is not None else self.client.timeout_seconds + 30.0),
        )
        now = datetime.now(timezone.utc)
        recovered = 0
        with self._execution_lock:
            workspaces = self.store.list(
                "workspaces",
                predicate=lambda item: bool(item.get("planningRequestId")),
            )
            for workspace in workspaces:
                try:
                    started = datetime.fromisoformat(str(workspace.get("planningStartedAt") or ""))
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    age = (now - started.astimezone(timezone.utc)).total_seconds()
                except (TypeError, ValueError):
                    age = maximum_age + 1.0
                if age <= maximum_age:
                    continue
                request_id = str(workspace.pop("planningRequestId", "") or "")
                workspace.pop("planningStartedAt", None)
                workspace.pop("planningExecutionMode", None)
                workspace.pop("planningSurface", None)
                if not workspace.get("activePlanId"):
                    workspace["status"] = "ready"
                workspace = self.store.save("workspaces", workspace)
                self.store.append_event(workspace["id"], "planning.recovered", {
                    "requestId": request_id,
                    "reason": "规划连接已超时，工作区已恢复为可重试状态",
                })
                recovered += 1
                self._notify_workspace_state(workspace)
        return recovered

    def recover_completed_operations(self) -> int:
        """Settle Agent steps whose durable media operation finished while detached.

        A service restart can lose the in-memory Future callback while the job
        record already contains terminal content-search state.  Polling the
        task then shows a permanent ``waiting_operation`` step.  This recovery
        reads the current task snapshot through the planning-context provider
        and applies the same terminal mapping used by live Future callbacks.
        """
        recovered: list[tuple[str, str, str, dict[str, Any], str]] = []
        with self._execution_lock:
            plans = self.store.list(
                "plans",
                predicate=lambda item: item.get("status") == "running",
            )
            for plan in plans:
                workspace = self.store.get("workspaces", str(plan.get("workspaceId") or ""))
                for step in plan.get("steps") or []:
                    if str(step.get("status") or "") != "waiting_operation":
                        continue
                    result = copy.deepcopy(step.get("result") if isinstance(step.get("result"), dict) else {})
                    if workspace and not self._operation_result_job_id(plan, result):
                        result["jobId"] = str(workspace.get("jobId") or "")
                    job_id = self._operation_result_job_id(plan, result)
                    if not job_id:
                        continue
                    context = self._planning_context(job_id)
                    evidence = context.get("evidence") if isinstance(context.get("evidence"), dict) else {}
                    job_status = str(context.get("jobStatus") or "").strip()
                    search_status = str(evidence.get("lastSearchStatus") or "").strip()
                    if job_status in {"queued", "running", "cancelling", "briefing"} or search_status in {
                        "queued", "indexing", "scanning", "running",
                    }:
                        continue
                    status, resolved, error = self._background_operation_resolution(
                        plan, step, {**result, "operationCompleted": True},
                    )
                    recovered.append((str(plan["id"]), str(step["id"]), status, resolved, error))
        count = 0
        for plan_id, step_id, status, result, error in recovered:
            self._complete_step(plan_id, step_id, status=status, result=result, error=error)
            count += 1
        return count

    def record_planning_progress(self, workspace_id: str, update: dict[str, Any]) -> None:
        """Persist an auditable planning milestone for polling and reloads.

        Pi's reasoning can take longer than a browser navigation or a task
        status poll.  Keep only public workflow milestones here—never model
        chain-of-thought—so the task surface can report useful live state.
        """
        phase = str(update.get("phase") or "").strip()[:80]
        title = str(update.get("title") or "正在生成 Agent 执行计划").strip()[:160]
        detail = str(update.get("detail") or "正在整理可确认的剪辑步骤。").strip()[:500]
        with self._execution_lock:
            workspace = self.store.get("workspaces", workspace_id)
            if not workspace or str(workspace.get("status") or "") != "planning":
                return
            workspace["planningProgress"] = {
                "phase": phase, "title": title, "detail": detail,
                "updatedAt": now_iso(),
            }
            workspace = self.store.save("workspaces", workspace)
        self._notify_workspace_state(workspace)

    def persist_plan_result(
        self, *, workspace: dict[str, Any], skill: dict[str, Any],
        goal: str, result: dict[str, Any], execution_mode: str = AUTONOMOUS_REVIEW,
    ) -> dict[str, Any]:
        workspace_id = str(workspace["id"])
        raw_plan = result.get("plan") if isinstance(result.get("plan"), dict) else result
        context = raw_plan.get("planningContext") if isinstance(raw_plan, dict) and isinstance(raw_plan.get("planningContext"), dict) else self._planning_context(str(workspace.get("jobId") or ""))
        context = copy.deepcopy(context)
        frozen = copy.deepcopy(workspace.get("planningInputContext") or {})
        context["inputContext"] = frozen
        if frozen.get("outputAspect"):
            context["delivery"] = {"outputAspect": frozen["outputAspect"], "outputFit": frozen.get("outputFit", "blur")}
        ranges = frozen.get("sourceRanges") or []
        if len(ranges) == 1:
            context.update({"sourceScope": "custom", "sourceRange": ranges[0]})
        brief = self._editing_brief(goal, context)
        if bool(self._profile_for_skill(skill).get("managed")):
            # Built-in workflow composition is server-owned. A planning model
            # must not turn words such as “旧封面/旧输出” in an audit request
            # into media-producing add-ons.
            skills = self._compose_skills(skill, brief=brief, context=context)
        else:
            skills = self._resolve_skill_chain(
                skill, raw_plan.get("skillChain") if isinstance(raw_plan, dict) else None,
            )
        compiled = self._compile_profile_plan(
            raw_plan, skill=skill, skills=skills, goal=goal, context=context,
            execution_mode=execution_mode,
        )
        plan = self._normalize_plan(
            compiled, workspace=workspace, skill=skill, skills=skills, goal=goal,
        )
        plan["inputContext"] = frozen
        plan["replacesPlanId"] = workspace.get("replacesPlanId")
        # Bind review approval to the actual selection and output version.
        if frozen:
            plan["planHash"] = content_hash(plan["planHash"] + json.dumps(frozen, sort_keys=True, ensure_ascii=False))
        with self._execution_lock:
            latest_workspace = self.store.get("workspaces", workspace_id)
            expected_request = str(workspace.get("planningRequestId") or "")
            if expected_request and (not latest_workspace or latest_workspace.get("planningRequestId") != expected_request):
                raise ValueError("这次规划请求已失效，请查看当前计划")
            if latest_workspace:
                workspace = latest_workspace
            replaced = self.store.get("plans", str(workspace.get("replacesPlanId") or ""))
            if workspace.get("replacesPlanId") and (not replaced or replaced.get("status") != "awaiting_confirmation"):
                raise ValueError("原方案状态已变化，请重新查看；未替换原方案")
            plan = self.store.save("plans", plan)
            if replaced:
                replaced.update({"status": "cancelled", "supersededBy": plan["id"], "completedAt": now_iso()})
                self.store.save("plans", replaced)
            messages = list(workspace.get("messages") or [])
            if not workspace.get("planningMessageId"):
                messages.extend([
                {"role": "user", "text": goal, "createdAt": now_iso()},
                {"role": "assistant", "kind": "plan", "text": plan["summary"], "planId": plan["id"], "createdAt": now_iso()},
                ])
            latest_workspace = self.store.get("workspaces", workspace_id)
            if latest_workspace:
                workspace = latest_workspace
            workspace.update({
                "activePlanId": plan["id"], "status": "awaiting_plan_confirmation",
                "messages": messages, "selectedSkillId": skill["id"],
                "executionMode": plan["executionMode"],
            })
            workspace.pop("planningRequestId", None)
            workspace.pop("planningStartedAt", None)
            workspace.pop("planningExecutionMode", None)
            workspace.pop("planningSurface", None)
            workspace.pop("planningInputContext", None)
            workspace.pop("planningMessageId", None)
            workspace.pop("replacesPlanId", None)
            self.store.save("workspaces", workspace)
            for event in result.get("events") or []:
                if isinstance(event, dict):
                    self.store.append_event(workspace_id, "agent.message_update", event)
            self.store.append_event(workspace_id, "plan.created", {"plan": plan})
            self.store.append_event(workspace_id, "plan.confirmation_required", {
                "planId": plan["id"], "planHash": plan["planHash"],
            })
            self._notify_workspace_state(workspace, plan)
            return plan


    def _normalize_plan(
        self, raw: dict[str, Any], *, workspace: dict[str, Any],
        skill: dict[str, Any], goal: str, skills: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tool_map = {item["name"]: item for item in self.tool_catalog()}
        selected_skills = skills or [skill]
        profile = self._profile_for_skill(skill)
        execution_mode = str(raw.get("executionMode") or STEPWISE_REVIEW)
        if execution_mode not in VALID_EXECUTION_MODES or not self._supports_autonomous_review(selected_skills):
            execution_mode = STEPWISE_REVIEW
        allowed_tools: set[str] = set()
        for selected in selected_skills:
            selected_profile = self._profile_for_skill(selected)
            declared_tools = {str(item) for item in selected.get("allowedTools") or [] if str(item)}
            allowed_tools.update(set(selected_profile["tools"]) if selected_profile["managed"] else declared_tools)
        raw_steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
        if not raw_steps or len(raw_steps) > 24:
            raise ValueError("Agent 必须生成 1–24 个计划步骤")
        seen: set[str] = set()
        steps: list[dict[str, Any]] = []
        for index, value in enumerate(raw_steps, 1):
            if not isinstance(value, dict):
                raise ValueError("计划步骤格式无效")
            step_id = str(value.get("id") or f"step_{index}")[:64]
            tool_name = str(value.get("tool") or "")
            if step_id in seen:
                raise ValueError("计划步骤 ID 重复")
            if tool_name not in tool_map:
                raise ValueError(f"计划引用了未安装的工具：{tool_name}")
            if allowed_tools and tool_name not in allowed_tools:
                raise ValueError(f"计划引用了当前 Skill 未授权的工具：{tool_name}")
            seen.add(step_id)
            dependencies = [str(item) for item in value.get("dependencies") or []]
            declared_effect = str(tool_map[tool_name].get("sideEffect") or "analysis")
            requested_effect = str(value.get("sideEffect") or declared_effect)
            if requested_effect != declared_effect:
                raise ValueError(f"步骤 {step_id} 不能改变工具声明的副作用级别")
            effect = declared_effect
            if effect not in VALID_SIDE_EFFECTS:
                raise ValueError(f"步骤 {step_id} 的副作用级别无效")
            arguments = value.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError(f"步骤 {step_id} 的工具参数必须是对象")
            self._validate_tool_arguments(step_id, tool_map[tool_name], arguments)
            steps.append({
                "id": step_id, "index": index,
                "title": str(value.get("title") or tool_name)[:160],
                "tool": tool_name, "arguments": arguments,
                "dependencies": dependencies, "expectedOutput": str(value.get("expectedOutput") or "")[:500],
                "sideEffect": effect, "estimatedSeconds": min(86400, max(0, int(value.get("estimatedSeconds") or 0))),
                "optional": bool(value.get("optional")), "status": "pending", "attempts": 0,
                "pluginId": tool_map[tool_name].get("pluginId"),
                "pluginVersion": tool_map[tool_name].get("pluginVersion"),
                "contentHash": tool_map[tool_name].get("contentHash"),
                "treeHash": tool_map[tool_name].get("treeHash"),
            })
        for step in steps:
            unknown = set(step["dependencies"]) - seen
            if unknown:
                raise ValueError(f"步骤 {step['id']} 引用了不存在的依赖")
        self._validate_acyclic(steps)
        self._validate_timeline_review_gate(steps)
        canonical = {
            "workspaceId": workspace["id"], "workspaceRevision": workspace["revision"],
            "executionMode": execution_mode,
            "goal": goal, "skillId": skill["id"], "skillVersion": skill["version"],
            "skillHash": skill["contentHash"], "skills": self._skill_chain_payload(selected_skills), "steps": [
                {key: value for key, value in step.items() if key not in {"status", "attempts"}}
                for step in steps
            ],
        }
        digest = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "id": f"plan_{uuid.uuid4().hex}", **canonical,
            "summary": str(raw.get("summary") or goal)[:1000],
            "status": "awaiting_confirmation", "revision": 1,
            "planHash": digest, "steps": steps,
            "approval": None, "agent": raw.get("agent") or {},
            "brief": raw.get("brief") if isinstance(raw.get("brief"), dict) else {},
            "planningContext": raw.get("planningContext") if isinstance(raw.get("planningContext"), dict) else {},
            "decisionRecord": raw.get("decisionRecord") if isinstance(raw.get("decisionRecord"), list) else [],
            "profile": str(raw.get("profile") or profile["kind"]),
            "planningSource": str(raw.get("planningSource") or "agent_service"),
            "planningWarning": str(raw.get("planningWarning") or "")[:500],
        }

    @staticmethod
    def _validate_tool_arguments(
        step_id: str, tool: dict[str, Any], arguments: dict[str, Any],
    ) -> None:
        schema = tool.get("parameters")
        if not isinstance(schema, dict):
            return
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        missing = [str(name) for name in required if str(name) not in arguments]
        if missing:
            raise ValueError(f"步骤 {step_id} 缺少工具参数：{', '.join(missing)}")
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(arguments) - set(properties))
            if unknown:
                raise ValueError(f"步骤 {step_id} 包含未声明参数：{', '.join(unknown)}")
        expected_types: dict[str, tuple[type[Any], ...]] = {
            "string": (str,), "number": (int, float), "integer": (int,),
            "boolean": (bool,), "object": (dict,), "array": (list,),
        }
        for name, value in arguments.items():
            property_schema = properties.get(name)
            if not isinstance(property_schema, dict) or not property_schema.get("type"):
                continue
            expected = expected_types.get(str(property_schema["type"]))
            if expected and (isinstance(value, bool) and str(property_schema["type"]) in {"number", "integer"} or not isinstance(value, expected)):
                raise ValueError(f"步骤 {step_id} 的参数 {name} 类型无效")
            if "enum" in property_schema and value not in property_schema["enum"]:
                raise ValueError(f"步骤 {step_id} 的参数 {name} 不在允许范围内")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not math.isfinite(value):
                    raise ValueError(f"步骤 {step_id} 的参数 {name} 必须为有限数值")
                for boundary, invalid in (
                    ("minimum", lambda limit: value < limit),
                    ("maximum", lambda limit: value > limit),
                    ("exclusiveMinimum", lambda limit: value <= limit),
                    ("exclusiveMaximum", lambda limit: value >= limit),
                ):
                    if boundary in property_schema and invalid(property_schema[boundary]):
                        raise ValueError(f"步骤 {step_id} 的参数 {name} 超出允许范围")
        if "sourceScopeStart" in arguments and "sourceScopeEnd" in arguments:
            if arguments["sourceScopeEnd"] <= arguments["sourceScopeStart"]:
                raise ValueError(f"步骤 {step_id} 的素材结束时间必须大于开始时间")


    @staticmethod
    def _validate_acyclic(steps: list[dict[str, Any]]) -> None:
        dependencies = {step["id"]: set(step["dependencies"]) for step in steps}
        ready = [step_id for step_id, items in dependencies.items() if not items]
        visited: set[str] = set()
        while ready:
            current = ready.pop()
            if current in visited:
                continue
            visited.add(current)
            for step_id, items in dependencies.items():
                items.discard(current)
                if not items and step_id not in visited:
                    ready.append(step_id)
        if len(visited) != len(steps):
            raise ValueError("执行计划包含循环依赖")

    @staticmethod
    def _step_execution_signatures(steps: list[dict[str, Any]]) -> dict[str, str]:
        """Hash a step together with the exact dependency chain it consumes.

        A confirmation tool commonly has no arguments of its own.  Matching
        only ``tool + arguments`` therefore reused an old confirmation after a
        replan had produced a different timeline proposal.  Dependency-aware
        signatures make reuse transitive: a step is reusable only when both it
        and every upstream input are unchanged.
        """
        by_id = {
            str(step.get("id") or ""): step
            for step in steps if str(step.get("id") or "")
        }
        signatures: dict[str, str] = {}
        visiting: set[str] = set()

        def signature(step_id: str) -> str:
            if step_id in signatures:
                return signatures[step_id]
            if step_id in visiting or step_id not in by_id:
                return ""
            visiting.add(step_id)
            step = by_id[step_id]
            payload = {
                "tool": str(step.get("tool") or ""),
                "arguments": step.get("arguments") or {},
                "pluginIdentity": [step.get(key) for key in ("pluginId", "pluginVersion", "contentHash", "treeHash")],
                "dependencies": [
                    signature(str(dependency))
                    for dependency in step.get("dependencies") or []
                ],
            }
            visiting.discard(step_id)
            digest = hashlib.sha256(
                json.dumps(
                    payload, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), default=str,
                ).encode("utf-8")
            ).hexdigest()
            signatures[step_id] = digest
            return digest

        for step_id in by_id:
            signature(step_id)
        return signatures

    @staticmethod
    def _validate_timeline_review_gate(steps: list[dict[str, Any]]) -> None:
        """Keep an AI timeline draft separate from its user-approved edit state."""
        subtitle_review = next((step for step in steps if step["tool"] == "prepare_subtitle_review"), None)
        for layout in (step for step in steps if step["tool"] == "layout_subtitles"):
            if subtitle_review is None:
                raise ValueError("字幕排版前必须先生成并确认字幕审核稿")
            if int(layout["index"]) <= int(subtitle_review["index"]):
                raise ValueError("字幕排版必须在字幕审核稿生成并确认后执行")
            if subtitle_review["id"] not in set(layout["dependencies"]):
                raise ValueError("字幕排版步骤必须依赖已确认的字幕审核稿")
        proposal = next((step for step in steps if step["tool"] == "propose_timeline_edit"), None)
        if proposal is None:
            return
        confirmation = next((step for step in steps if step["tool"] == "confirm_timeline_edit"), None)
        if confirmation is None:
            raise ValueError("时间线提案后必须加入确认时间线步骤，再生成字幕或审核样片")
        if proposal["id"] not in set(confirmation["dependencies"]):
            raise ValueError("确认时间线步骤必须依赖时间线提案")
        for step in steps:
            if step["tool"] not in {"prepare_subtitle_review", "layout_subtitles", "render_review_preview"}:
                continue
            if int(step["index"]) <= int(confirmation["index"]):
                raise ValueError("字幕和审核样片必须在时间线确认后执行")

    def approve_plan(self, plan_id: str, *, expected_hash: str) -> dict[str, Any]:
        with self._execution_lock:
            plan = self.store.get("plans", plan_id)
            if not plan:
                raise KeyError(plan_id)
            if plan.get("status") != "awaiting_confirmation":
                raise ValueError("计划当前不能确认")
            if plan.get("planHash") != expected_hash:
                raise ValueError("计划已经变化，请重新审核")
            workspace = self.store.get("workspaces", str(plan["workspaceId"]))
            if workspace and workspace.get("planningRequestId"):
                raise ValueError("正在准备修改方案，请等待完成后确认")
            validator = getattr(self, "_reference_validator", None)
            if validator:
                validator(plan)
            if not workspace or workspace.get("revision") != plan.get("workspaceRevision"):
                raise ValueError("素材工作区已经变化，请重新规划")
            for step in plan["steps"]:
                if step.get("pluginId"):
                    self._validate_plugin_identity(step)
            plan["status"] = "approved"
            plan["approval"] = {
                "approvedAt": now_iso(), "planHash": expected_hash,
                "workspaceRevision": workspace["revision"],
                "executionMode": str(plan.get("executionMode") or STEPWISE_REVIEW),
                "allowedTools": sorted({step["tool"] for step in plan["steps"]}),
                "allowedSideEffects": sorted({step["sideEffect"] for step in plan["steps"]}),
                "pluginVersions": {
                    str(step["pluginId"]): str(step.get("pluginVersion") or "")
                    for step in plan["steps"] if step.get("pluginId")
                },
                "pluginHashes": {str(step["pluginId"]): [step.get("contentHash"), step.get("treeHash")]
                                 for step in plan["steps"] if step.get("pluginId")},
                "skillHash": plan["skillHash"],
                "skillHashes": {
                    str(item.get("id") or ""): str(item.get("contentHash") or "")
                    for item in plan.get("skills") or [] if str(item.get("id") or "")
                },
            }
            plan = self.store.save("plans", plan)
            run = self.store.save("runs", {
                "id": f"run_{uuid.uuid4().hex}", "workspaceId": workspace["id"],
                "planId": plan_id, "status": "running", "startedAt": now_iso(),
            })
            plan["runId"] = run["id"]
            plan["status"] = "running"
            plan = self.store.save("plans", plan)
            workspace.update({
                "status": "running", "activePlanId": plan_id,
                "executionMode": str(plan.get("executionMode") or STEPWISE_REVIEW),
            })
            self.store.save("workspaces", workspace)
            self.store.append_event(workspace["id"], "plan.approved", {"planId": plan_id, "runId": run["id"]})
        self._notify_workspace_state(workspace, plan)
        self._advance_plan(plan_id)
        return self.store.get("plans", plan_id) or plan

    @staticmethod
    def _action_required_message(step: dict[str, Any]) -> str:
        tool = str(step.get("tool") or "")
        return {
            "review_content_evidence": "请在内容候选面板勾选要用于组合的片段；保存选择后再继续。",
            "select_multi_topic_evidence": "请在内容候选面板确认每个主题的可用片段；保存后再继续。",
            "select_people": "请在人物面板完成目标人物选择后再继续。",
            "select_speakers": "请在说话人面板完成目标声音选择后再继续。",
            "review_cover_variants": "请在封面审核面板选择并保存当前任务封面；如任务要求片头或目标画幅，后续会继续生成最终审核样片。",
            "export_editing_draft": "将导出当前任务本地草稿包；请确认后再继续。",
            "export_delivery_master": "正式交付会生成新的可下载版本；请确认后再导出。",
        }.get(tool, "该步骤需要你在审核面板完成结构化确认。")

    def _advance_plan(self, plan_id: str) -> None:
        with self._execution_lock:
            plan = self.store.get("plans", plan_id)
            if not plan or plan.get("status") != "running":
                return
            if any(step["status"] in {"running", "waiting_operation", "action_required"} for step in plan["steps"]):
                return
            completed = {step["id"] for step in plan["steps"] if step["status"] in {"completed", "skipped"}}
            failed_required = any(step["status"] == "failed" and not step.get("optional") for step in plan["steps"])
            if failed_required:
                self._finish_plan(plan, "failed")
                return
            next_step = next((
                step for step in plan["steps"]
                if step["status"] == "pending" and set(step["dependencies"]).issubset(completed)
            ), None)
            if next_step is None:
                if all(step["status"] in {"completed", "skipped", "failed"} for step in plan["steps"]):
                    self._finish_plan(plan, "preview_ready")
                return
            execution_mode = str(plan.get("executionMode") or STEPWISE_REVIEW)
            requires_action = (
                (
                    next_step["sideEffect"] in FORBIDDEN_AUTONOMOUS_EFFECTS
                    and str(next_step.get("tool") or "") not in SAFE_AUTONOMOUS_EXPORT_TOOLS
                )
                or (
                    next_step["sideEffect"] == "identity"
                    and execution_mode != AUTONOMOUS_REVIEW
                )
                or (
                    next_step["sideEffect"] == "review"
                    and execution_mode != AUTONOMOUS_REVIEW
                )
            )
            if requires_action:
                next_step["status"] = "action_required"
                next_step["result"] = {
                    "message": self._action_required_message(next_step),
                    "action": "structured_review",
                }
                plan["status"] = "action_required"
                self.store.save("plans", plan)
                self.store.append_event(plan["workspaceId"], "action.required", {
                    "planId": plan_id, "step": next_step,
                    "reason": "该步骤需要结构化用户确认",
                })
                workspace = self.store.get("workspaces", str(plan["workspaceId"]))
                if workspace:
                    self._notify_workspace_state(workspace, plan)
                return
            next_step["status"] = "running"
            next_step["attempts"] = int(next_step.get("attempts") or 0) + 1
            plan = self.store.save("plans", plan)
            self.store.append_event(plan["workspaceId"], "step.started", {
                "planId": plan_id, "step": next_step,
            })
            workspace = self.store.get("workspaces", str(plan["workspaceId"]))
            if workspace:
                self._notify_workspace_state(workspace, plan)
        self._execute_step(plan_id, next_step["id"])

    def _validate_plugin_identity(self, step: dict[str, Any]) -> None:
        plugin = self.store.get("plugins", str(step["pluginId"])) or {}
        if plugin.get("status") != "enabled" or any(
            not step.get(key) or step.get(key) != plugin.get(registry_key)
            for key, registry_key in (("pluginVersion", "version"), ("contentHash", "contentHash"), ("treeHash", "treeHash"))
        ):
            raise ValueError("Plugin 内容已变化或审批缺少内容指纹，请重新规划并审批")
        if plugin.get("path") and plugin_tree_hash(Path(plugin["path"])) != step["treeHash"]:
            raise ValueError("Plugin 源码已变化，请重新规划并审批")

    def _execute_step(self, plan_id: str, step_id: str) -> None:
        plan = self.store.get("plans", plan_id)
        if not plan:
            return
        workspace = self.store.get("workspaces", plan["workspaceId"])
        step = next((item for item in plan["steps"] if item["id"] == step_id), None)
        if not workspace or not step or plan.get("status") != "running" or step.get("status") != "running":
            return
        attempt = int(step.get("attempts") or 0)
        try:
            if step.get("pluginId"):
                self._validate_plugin_identity(step)
                approved_hashes = (plan.get("approval") or {}).get("pluginHashes") or {}
                if approved_hashes.get(str(step["pluginId"])) != [step.get("contentHash"), step.get("treeHash")]:
                    raise ValueError("Plugin 审批指纹不匹配，请重新审批")
                result = self.client.execute_plugin_tool({
                    "pluginId": step["pluginId"], "pluginVersion": step.get("pluginVersion"),
                    "contentHash": step.get("contentHash"), "treeHash": step.get("treeHash"),
                    "operationId": f"{plan_id}:{step_id}:{plan.get('planHash', '')}",
                    "tool": step["tool"], "arguments": step["arguments"],
                    "context": {"workspaceId": workspace["id"], "jobId": workspace["jobId"]},
                })
            else:
                if self._dispatch_tool is None:
                    raise RuntimeError("媒体工具调度器尚未初始化")
                result = self._dispatch_tool(workspace, step["tool"], step["arguments"])
        except Exception as error:
            self._complete_step(plan_id, step_id, status="failed", error=str(error), expected_attempt=attempt)
            return
        future = result.pop("future", None) if isinstance(result, dict) else None
        cancel_operation = result.pop("cancel", None) if isinstance(result, dict) else None
        if isinstance(future, Future):
            with self._execution_lock:
                current = self.store.get("plans", plan_id)
                current_step = next((item for item in (current or {}).get("steps", []) if item["id"] == step_id), None)
                if (not current or current.get("status") != "running" or not current_step
                        or current_step.get("status") != "running"
                        or int(current_step.get("attempts") or 0) != attempt):
                    if callable(cancel_operation):
                        cancel_operation()
                    future.cancel()
                    return
                operation_id = str(result.get("operationId") or f"operation_{uuid.uuid4().hex}")
                current_step["status"] = "waiting_operation"
                current_step["operationId"] = operation_id
                current_step["result"] = {
                    **result,
                    "operationOwner": "agent",
                    "planId": plan_id,
                    "runId": str(current.get("runId") or ""),
                    "stepId": step_id,
                    "planRevision": int(current.get("revision") or 1),
                }
                self._operation_handles[(plan_id, step_id)] = {
                    "future": future,
                    "cancel": cancel_operation if callable(cancel_operation) else None,
                    "operationId": operation_id,
                }
                self.store.save("plans", current)
                self._notify_workspace_state(workspace, current)
            future.add_done_callback(
                lambda completed: self._future_finished(plan_id, step_id, operation_id, completed)
            )
            return
        if isinstance(result, dict) and result.get("actionRequired"):
            with self._execution_lock:
                current = self.store.get("plans", plan_id)
                current_step = next((item for item in (current or {}).get("steps", []) if item["id"] == step_id), None)
                if (not current or current.get("status") != "running" or not current_step
                        or current_step.get("status") != "running"
                        or int(current_step.get("attempts") or 0) != attempt):
                    return
                current_step["status"] = "action_required"
                current_step["result"] = result
                current["status"] = "action_required"
                self.store.save("plans", current)
                self.store.append_event(current["workspaceId"], "action.required", {
                    "planId": plan_id, "step": current_step,
                })
                self._notify_workspace_state(workspace, current)
            return
        self._complete_step(plan_id, step_id, status="completed", result=result, expected_attempt=attempt)

    def _future_finished(
        self, plan_id: str, step_id: str, operation_id: str, future: Future[Any],
    ) -> None:
        with self._execution_lock:
            handle = self._operation_handles.get((plan_id, step_id))
            if not handle or handle.get("future") is not future:
                return
            self._operation_handles.pop((plan_id, step_id), None)
            current = self.store.get("plans", plan_id)
            current_step = next((
                item for item in (current or {}).get("steps") or [] if item.get("id") == step_id
            ), None)
            if (
                not current or str(current.get("status") or "") != "running"
                or not current_step or str(current_step.get("status") or "") != "waiting_operation"
                or str(current_step.get("operationId") or "") != operation_id
            ):
                return
        def finish(**kwargs: Any) -> None:
            self._complete_step(
                plan_id, step_id, expected_attempt=int(current_step.get("attempts") or 0),
                expected_operation_id=operation_id, **kwargs,
            )
        if future.cancelled():
            finish(status="failed", error="后台操作已取消")
            return
        error = future.exception()
        if error is not None:
            finish(status="failed", error=str(error))
            return
        # Preserve durable handoff information from dispatch and merge any
        # artifact produced by the worker (for example a QC report). Older
        # behavior discarded a Future's useful return value and exposed only
        # an operation-completed marker.
        latest_plan = self.store.get("plans", plan_id) or {}
        latest_step = next((
            item for item in latest_plan.get("steps") or [] if item.get("id") == step_id
        ), {})
        prior_result = latest_step.get("result") if isinstance(latest_step.get("result"), dict) else {}
        completed_result = future.result()
        completed_payload = completed_result if isinstance(completed_result, dict) else {}
        status, result, error = self._background_operation_resolution(
            latest_plan, latest_step,
            {**prior_result, **completed_payload, "operationCompleted": True},
        )
        finish(status=status, result=result, error=error)

    def _background_operation_resolution(
        self, plan: dict[str, Any], step: dict[str, Any], result: dict[str, Any],
    ) -> tuple[str, dict[str, Any], str]:
        """Map a completed worker handoff to the Agent step's real terminal state.

        Media workers normally finish at a product checkpoint.  For Agent-owned
        search steps that checkpoint is not a user-visible pause; the Agent must
        either continue with candidates or stop the downstream timeline/render
        chain when no reliable candidates exist.
        """
        explicit_terminal = str(result.get("terminalStatus") or "").strip()
        if explicit_terminal == "no_result":
            return "completed", result, ""
        if str(step.get("tool") or "") != "search_content":
            return "completed", result, ""

        job_id = self._operation_result_job_id(plan, result)
        if not job_id:
            return "completed", result, ""
        context = self._planning_context(job_id)
        if not bool(context.get("available", True)):
            return "completed", result, ""
        job_status = str(context.get("jobStatus") or "").strip()
        if job_status == "failed":
            message = str(context.get("error") or "内容检索失败")
            return "failed", result, message

        evidence = context.get("evidence") if isinstance(context.get("evidence"), dict) else {}
        search_status = str(evidence.get("lastSearchStatus") or "").strip()
        candidate_count = int(
            evidence.get("contentCandidateCount")
            if "contentCandidateCount" in evidence else evidence.get("candidateCount") or 0
        )
        clarification = evidence.get("lastSearchClarification") if isinstance(evidence.get("lastSearchClarification"), dict) else {}
        message = str(
            clarification.get("message")
            or clarification.get("question")
            or evidence.get("lastSearchMessage")
            or "没有找到可用于自动剪辑的可靠候选。"
        )
        if search_status in {"queued", "indexing", "scanning", "running"}:
            return "completed", result, ""
        if candidate_count <= 0 and search_status in {
            "needs_clarification", "ready", "completed", "awaiting_content_confirmation", "no_result",
        }:
            no_match = {
                "kind": "no_match",
                "reasonCode": str(clarification.get("kind") or search_status or "no_match"),
                "message": message[:1000],
                "candidateCount": 0,
                "searchStatus": search_status,
                "coverageComplete": bool(evidence.get("coverageComplete")),
            }
            return "completed", {
                **result,
                "terminalStatus": "no_result",
                "artifact": no_match,
            }, ""
        return "completed", result, ""

    @staticmethod
    def _operation_result_job_id(plan: dict[str, Any], result: dict[str, Any]) -> str:
        artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
        job = result.get("job") if isinstance(result.get("job"), dict) else {}
        workspace = plan.get("workspace") if isinstance(plan.get("workspace"), dict) else {}
        return str(
            artifact.get("jobId")
            or result.get("jobId")
            or job.get("id")
            or workspace.get("jobId")
            or ""
        ).strip()

    def _cancel_plan_operations(self, plan_id: str) -> None:
        """Cancel only Futures and media operations started by this Agent plan."""
        with self._execution_lock:
            handles = [
                handle for (owner_plan_id, _step_id), handle in self._operation_handles.items()
                if owner_plan_id == plan_id
            ]
            self._operation_handles = {
                key: handle for key, handle in self._operation_handles.items()
                if key[0] != plan_id
            }
        for handle in handles:
            cancel = handle.get("cancel")
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass
            future = handle.get("future")
            if isinstance(future, Future):
                future.cancel()

    def _complete_step(
        self, plan_id: str, step_id: str, *, status: str,
        result: Any = None, error: str = "", expected_attempt: int | None = None,
        expected_operation_id: str | None = None,
    ) -> None:
        should_replan = False
        no_result = bool(
            status == "completed" and isinstance(result, dict)
            and str(result.get("terminalStatus") or "") == "no_result"
        )
        with self._execution_lock:
            plan = self.store.get("plans", plan_id)
            if not plan or plan.get("status") != "running":
                return
            step = next((item for item in plan["steps"] if item["id"] == step_id), None)
            if not step or step.get("status") not in {"running", "waiting_operation"}:
                return
            if expected_attempt is not None and int(step.get("attempts") or 0) != expected_attempt:
                return
            if expected_operation_id is not None and step.get("operationId") != expected_operation_id:
                return
            step.update({"status": status, "completedAt": now_iso()})
            if result is not None:
                step["result"] = result
            if error:
                step["error"] = error[:2000]
            if no_result:
                for downstream in plan["steps"]:
                    if downstream.get("status") == "pending":
                        downstream.update({
                            "status": "skipped", "completedAt": now_iso(),
                            "skipReason": "上游检索没有得到可用于自动编排的可靠结果",
                        })
            self.store.save("plans", plan)
            self.store.append_event(plan["workspaceId"], f"step.{status}", {
                "planId": plan_id, "step": step,
            })
            workspace = self.store.get("workspaces", str(plan["workspaceId"]))
            if workspace:
                self._notify_workspace_state(workspace, plan)
            should_replan = status == "failed" and not step.get("optional")
            if no_result:
                self._finish_plan(plan, "no_result")
                return
        if should_replan and self._attempt_replan(plan_id, step_id):
            return
        self._advance_plan(plan_id)

    def _attempt_replan(self, plan_id: str, failed_step_id: str) -> bool:
        with self._execution_lock:
            plan = self.store.get("plans", plan_id)
            if not plan or int(plan.get("replanCount") or 0) >= 2:
                return False
            workspace = self.store.get("workspaces", str(plan["workspaceId"]))
            skill = self.store.get("skills", str(plan["skillId"]))
            failed_step = next((item for item in plan["steps"] if item["id"] == failed_step_id), None)
            if not workspace or not skill or not failed_step:
                return False
            block_reason = self._automatic_replan_block_reason(failed_step)
            if block_reason:
                self.store.append_event(plan["workspaceId"], "plan.replan_skipped", {
                    "planId": plan_id, "failedStepId": failed_step_id,
                    "reason": block_reason, "error": str(failed_step.get("error") or "")[:1000],
                })
                return False
            previous_steps = copy.deepcopy(plan["steps"])
            selected_skills = [skill]
            for item in plan.get("skills") or []:
                skill_id = str(item.get("id") or "") if isinstance(item, dict) else ""
                if not skill_id or skill_id == str(skill.get("id") or ""):
                    continue
                selected = self.store.get("skills", skill_id)
                if selected:
                    selected_skills.append(selected)
            context = (
                copy.deepcopy(plan.get("planningContext"))
                if isinstance(plan.get("planningContext"), dict)
                else self._planning_context(str(workspace.get("jobId") or ""))
            )
            brief = self._editing_brief(str(plan.get("goal") or ""), context)
            profile = self._profile_for_skill(skill)
            allowed_tools = sorted({
                tool
                for selected in selected_skills
                for tool in self._profile_for_skill(selected).get("tools", set())
            })
            payload = {
                "workspaceId": workspace["id"], "sessionDir": str(self.sessions_root),
                "goal": plan["goal"],
                "skill": {
                    "id": skill["id"], "version": skill["version"],
                    "contentHash": skill["contentHash"], "markdown": skill["skillMarkdown"],
                },
                "skills": [{
                    "id": selected["id"], "version": selected["version"],
                    "contentHash": selected["contentHash"], "markdown": selected["skillMarkdown"],
                    "role": "primary" if index == 0 else "addon",
                    "workflowProfile": self._profile_for_skill(selected)["kind"],
                } for index, selected in enumerate(selected_skills)],
                "workspace": {"jobId": workspace["jobId"], "revision": workspace["revision"]},
                "planningContext": context, "brief": brief,
                "executionMode": str(plan.get("executionMode") or STEPWISE_REVIEW),
                "profile": {
                    "kind": profile["kind"], "managed": bool(profile["managed"]),
                    "allowedTools": allowed_tools,
                },
                "toolCatalog": self.tool_catalog(), "model": self.model_config_resolver(),
                "replan": {
                    "completedSteps": [
                        {"id": item["id"], "tool": item["tool"], "result": item.get("result")}
                        for item in previous_steps if item["status"] == "completed"
                    ],
                    "failedStep": {
                        "id": failed_step["id"], "tool": failed_step["tool"],
                        "arguments": failed_step["arguments"], "error": failed_step.get("error"),
                    },
                    "approvedEnvelope": plan.get("approval") or {},
                },
            }
        try:
            result = self.client.plan(payload)
            raw_plan = result.get("plan") if isinstance(result.get("plan"), dict) else result
            compiled = self._compile_profile_plan(
                raw_plan, skill=skill, skills=selected_skills, goal=plan["goal"], context=context,
                execution_mode=str(plan.get("executionMode") or STEPWISE_REVIEW),
            )
            replacement = self._normalize_plan(
                compiled, workspace=workspace, skill=skill, skills=selected_skills, goal=plan["goal"],
            )
        except Exception as error:
            self.store.append_event(plan["workspaceId"], "plan.replan_failed", {
                "planId": plan_id, "error": str(error)[:1000],
            })
            return False
        previous_signatures = self._step_execution_signatures(previous_steps)
        replacement_signatures = self._step_execution_signatures(replacement["steps"])
        completed_by_signature = {
            previous_signatures.get(str(item.get("id") or "")): item
            for item in previous_steps
            if item.get("status") == "completed"
            and previous_signatures.get(str(item.get("id") or ""))
        }
        force_replay_tools = self._replan_force_replay_tools(failed_step)
        for step in replacement["steps"]:
            if str(step.get("tool") or "") in force_replay_tools:
                continue
            previous = completed_by_signature.get(
                replacement_signatures.get(str(step.get("id") or ""))
            )
            if previous:
                step.update({
                    "status": "completed",
                    "attempts": int(previous.get("attempts") or 1),
                    "completedAt": previous.get("completedAt") or now_iso(),
                    "result": copy.deepcopy(previous.get("result")),
                })
        approval = plan.get("approval") if isinstance(plan.get("approval"), dict) else {}
        new_tools = {step["tool"] for step in replacement["steps"]}
        new_effects = {step["sideEffect"] for step in replacement["steps"]}
        new_plugins = {
            str(step["pluginId"]): str(step.get("pluginVersion") or "")
            for step in replacement["steps"] if step.get("pluginId")
        }
        old_seconds = sum(int(step.get("estimatedSeconds") or 0) for step in previous_steps)
        new_seconds = sum(int(step.get("estimatedSeconds") or 0) for step in replacement["steps"])
        minor = (
            new_tools.issubset(set(approval.get("allowedTools") or []))
            and new_effects.issubset(set(approval.get("allowedSideEffects") or []))
            and all(dict(approval.get("pluginVersions") or {}).get(key) == value for key, value in new_plugins.items())
            and all(dict(approval.get("pluginHashes") or {}).get(str(step["pluginId"]))
                    == [step.get("contentHash"), step.get("treeHash")]
                    and step.get("contentHash") and step.get("treeHash")
                    for step in replacement["steps"] if step.get("pluginId"))
            and all(
                dict(approval.get("skillHashes") or {}).get(str(item.get("id") or ""))
                == str(item.get("contentHash") or "")
                for item in replacement.get("skills") or []
            )
            and new_seconds <= max(old_seconds + 60, int(old_seconds * 1.25))
        )
        with self._execution_lock:
            current = self.store.get("plans", plan_id)
            if not current or current.get("status") != "running":
                return False
            history = list(current.get("revisionHistory") or [])
            history.append({
                "revision": current.get("revision"), "planHash": current.get("planHash"),
                "steps": previous_steps, "replannedAt": now_iso(),
            })
            current.update({
                "summary": replacement["summary"], "steps": replacement["steps"],
                "planHash": replacement["planHash"], "agent": replacement.get("agent") or {},
                "skills": replacement.get("skills") or current.get("skills") or [],
                "brief": replacement.get("brief") or current.get("brief") or {},
                "planningContext": replacement.get("planningContext") or current.get("planningContext") or {},
                "decisionRecord": replacement.get("decisionRecord") or [],
                "profile": replacement.get("profile") or current.get("profile") or "",
                "revision": int(current.get("revision") or 1) + 1,
                "replanCount": int(current.get("replanCount") or 0) + 1,
                "revisionHistory": history[-10:],
            })
            if minor:
                current["status"] = "running"
                current["approval"]["lastAutomaticReplanAt"] = now_iso()
            else:
                current["status"] = "awaiting_confirmation"
                current["approval"] = None
            self.store.save("plans", current)
            self.store.append_event(current["workspaceId"], "plan.replanned", {
                "planId": plan_id, "revision": current["revision"], "material": not minor,
                "failedStepId": failed_step_id,
            })
            if not minor:
                self.store.append_event(current["workspaceId"], "plan.confirmation_required", {
                    "planId": plan_id, "planHash": current["planHash"], "reason": "重大重新规划",
                })
            if workspace:
                self._notify_workspace_state(workspace, current)
        if minor:
            self._advance_plan(plan_id)
        return True

    def _finish_plan(self, plan: dict[str, Any], status: str) -> None:
        plan["status"] = status
        plan["completedAt"] = now_iso()
        self.store.save("plans", plan)
        run_id = str(plan.get("runId") or "")
        if run_id:
            run = self.store.get("runs", run_id)
            if run:
                run.update({"status": status, "completedAt": now_iso()})
                self.store.save("runs", run)
        workspace = self.store.get("workspaces", plan["workspaceId"])
        if workspace:
            workspace["status"] = status
            result_id = f"plan-result:{plan['id']}"
            messages = [m for m in workspace.get("messages") or [] if m.get("id") != result_id]
            artifacts = [(step.get("result") or {}).get("artifact") or {} for step in plan.get("steps") or []]
            has_preview = any("preview" in str(a.get("kind") or "") for a in artifacts)
            quality_failed = any(a.get("kind") == "delivery_qc_report" and a.get("passed") is False for a in artifacts)
            result_text = (
                "审核样片已生成；检查存在提醒，请查看本次方案的检查详情。" if quality_failed else
                "审核样片已生成，正式导出需另行确认。" if has_preview else "本次方案已执行完成，可查看对应结果。"
            ) if status == "preview_ready" else {
                "failed": "本次方案执行失败，原有结果仍保留。请查看失败步骤。",
                "no_result": "本次未找到可用片段，可以调整条件重新检索；原有结果仍保留。",
                "cancelled": "本次方案已停止，原有结果仍保留。",
            }.get(status, "本次方案已结束，原有结果仍保留。")
            messages.append({"id": result_id, "role": "assistant", "kind": "plan_result", "planId": plan["id"], "text": result_text, "createdAt": now_iso()})
            workspace["messages"] = messages
            workspace = self.store.save("workspaces", workspace)
        event_type = {
            "preview_ready": "preview.ready",
            "no_result": "plan.no_result",
            "cancelled": "plan.cancelled",
        }.get(status, "plan.failed")
        self.store.append_event(plan["workspaceId"], event_type, {"planId": plan["id"]})
        if workspace:
            self._notify_workspace_state(workspace, plan)
        if status in {"failed", "no_result", "cancelled"}:
            self._cancel_plan_operations(str(plan.get("id") or ""))
        finished = getattr(self, "_conversation_finished", None)
        if finished:
            finished(plan["workspaceId"])

    def cancel_plan(self, plan_id: str) -> dict[str, Any]:
        with self._execution_lock:
            plan = self.store.get("plans", plan_id)
            if not plan:
                raise KeyError(plan_id)
            if plan.get("status") in {"preview_ready", "no_result", "failed", "cancelled"}:
                return plan
            plan["status"] = "cancelled"
            plan["completedAt"] = now_iso()
            run = self.store.get("runs", str(plan.get("runId") or "")) if plan.get("runId") else None
            if run:
                run.update({"status": "cancelled", "completedAt": plan["completedAt"]})
                self.store.save("runs", run)
            for step in plan["steps"]:
                if step["status"] in {"pending", "running", "waiting_operation", "action_required"}:
                    step["status"] = "cancelled"
            plan = self.store.save("plans", plan)
            workspace = self.store.get("workspaces", str(plan["workspaceId"]))
            if workspace:
                workspace["status"] = "cancelled"
                workspace = self.store.save("workspaces", workspace)
            self.store.append_event(plan["workspaceId"], "plan.cancelled", {"planId": plan_id})
        self._cancel_plan_operations(plan_id)
        if workspace:
            self._notify_workspace_state(workspace, plan)
        return plan

    def retry_action(self, plan_id: str) -> dict[str, Any]:
        """Re-run a recoverable action step whose artifact was never created."""
        pending_plan = self.store.get("plans", plan_id)
        uncertain_step = next((step for step in (pending_plan or {}).get("steps") or []
                               if step.get("pluginId") and step.get("status") == "action_required"
                               and (step.get("result") or {}).get("retryable") is False), None)
        if uncertain_step:
            # This button is a read-only reconciliation, never an execution retry.
            operation = self.client.query_plugin_operation(str(uncertain_step["result"]["operationId"]))
            if operation.get("status") != "succeeded":
                return self.store.get("plans", plan_id) or pending_plan
            with self._execution_lock:
                current = self.store.get("plans", plan_id)
                step = next((item for item in (current or {}).get("steps") or [] if item["id"] == uncertain_step["id"]), None)
                if (not current or current.get("status") != "action_required" or not step
                        or step.get("result") != uncertain_step.get("result")):
                    raise ValueError("操作状态已变化，请刷新")
                step["status"] = "running"
                current["status"] = "running"
                self.store.save("plans", current)
            self._complete_step(plan_id, step["id"], status="completed", result=operation.get("result"),
                                expected_attempt=int(step.get("attempts") or 0))
            return self.store.get("plans", plan_id) or current
        retry_failed_chain = False
        retry_qc_chain = False
        retry_subtitle_chain = False
        with self._execution_lock:
            plan = self.store.get("plans", plan_id)
            if not plan:
                raise KeyError(plan_id)
            qc_step = next((
                item for item in plan.get("steps") or []
                if str(item.get("tool") or "") == "run_delivery_qc"
            ), None)
            qc_result = qc_step.get("result") if isinstance((qc_step or {}).get("result"), dict) else {}
            qc_artifact = qc_result.get("artifact") if isinstance(qc_result.get("artifact"), dict) else {}
            brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
            target = float(brief.get("targetSeconds") or 0)
            tolerance = float(brief.get("durationToleranceSeconds") or 0)
            preview_durations: list[float] = []
            for candidate_step in plan.get("steps") or []:
                candidate_result = candidate_step.get("result") if isinstance(candidate_step.get("result"), dict) else {}
                artifact = candidate_result.get("artifact") if isinstance(candidate_result.get("artifact"), dict) else {}
                if artifact.get("kind") == "social_reframe_preview" and isinstance(artifact.get("output"), dict):
                    preview_durations.append(float(artifact["output"].get("duration") or 0))
                elif artifact.get("kind") == "review_preview_batch":
                    preview_durations.extend(
                        float(item.get("duration") or 0)
                        for item in artifact.get("previews") or [] if isinstance(item, dict)
                    )
            composition_retryable = bool(
                target and preview_durations
                and any(duration < target - tolerance or duration > target + tolerance for duration in preview_durations)
            )
            if (
                plan.get("status") == "preview_ready"
                and qc_artifact.get("passed") is False
                and composition_retryable
            ):
                replay_index = next((
                    index for index, item in enumerate(plan["steps"])
                    if str(item.get("tool") or "") in {"review_content_evidence", "propose_timeline_edit"}
                ), None)
                if replay_index is None:
                    raise ValueError("当前质检问题没有可安全重建的时间线步骤")
                for step in plan["steps"][replay_index:]:
                    step["status"] = "pending"
                    for key in ("completedAt", "error", "result", "operationId"):
                        step.pop(key, None)
                plan["status"] = "running"
                plan["replanCount"] = 0
                plan.pop("completedAt", None)
                plan = self.store.save("plans", plan)
                workspace = self.store.get("workspaces", str(plan["workspaceId"]))
                if workspace:
                    workspace["status"] = "running"
                    workspace = self.store.save("workspaces", workspace)
                self.store.append_event(plan["workspaceId"], "plan.retry_started", {
                    "planId": plan_id, "failedStepId": str((qc_step or {}).get("id") or ""),
                    "replayFromTool": plan["steps"][replay_index]["tool"],
                    "reason": "delivery_qc_failed",
                })
                if workspace:
                    self._notify_workspace_state(workspace, plan)
                retry_qc_chain = True
            elif plan.get("status") == "no_result":
                terminal_step = next((
                    item for item in plan["steps"]
                    if isinstance(item.get("result"), dict)
                    and str(item["result"].get("terminalStatus") or "") == "no_result"
                ), None)
                terminal_artifact = (
                    terminal_step.get("result", {}).get("artifact")
                    if isinstance((terminal_step or {}).get("result"), dict) else {}
                )
                reason_code = str((terminal_artifact or {}).get("reasonCode") or "")
                terminal_tool = str((terminal_step or {}).get("tool") or "")
                replay_tool = (
                    "propose_timeline_edit"
                    if reason_code in {"insufficient_coverage", "duration_constraint_unmet"}
                    and terminal_tool == "propose_timeline_edit"
                    else terminal_tool
                    if reason_code == "ambiguous_identity"
                    and terminal_tool in {"select_people", "select_speakers"}
                    else "search_content"
                )
                replay_index = next((
                    index for index, item in enumerate(plan["steps"])
                    if str(item.get("tool") or "") == replay_tool
                ), None)
                if replay_index is None:
                    raise ValueError("当前无结果计划没有可安全重跑的步骤")
                for step in plan["steps"][replay_index:]:
                    step["status"] = "pending"
                    for key in ("completedAt", "error", "result", "operationId"):
                        step.pop(key, None)
                plan["status"] = "running"
                plan["replanCount"] = 0
                plan.pop("completedAt", None)
                plan = self.store.save("plans", plan)
                workspace = self.store.get("workspaces", str(plan["workspaceId"]))
                if workspace:
                    workspace["status"] = "running"
                    workspace = self.store.save("workspaces", workspace)
                self.store.append_event(plan["workspaceId"], "plan.retry_started", {
                    "planId": plan_id,
                    "replayFromTool": plan["steps"][replay_index]["tool"],
                    "reason": reason_code or "no_result",
                })
                if workspace:
                    self._notify_workspace_state(workspace, plan)
                retry_failed_chain = True
            elif plan.get("status") == "failed":
                failed_step = next(
                    (item for item in plan["steps"] if item.get("status") == "failed"),
                    None,
                )
                replay_tools = self._replan_force_replay_tools(failed_step or {})
                replay_index = next((
                    index for index, item in enumerate(plan["steps"])
                    if str(item.get("tool") or "") in replay_tools
                ), None)
                if failed_step is None or replay_index is None:
                    raise ValueError("当前失败步骤不能安全地自动重跑")
                for step in plan["steps"][replay_index:]:
                    step["status"] = "pending"
                    for key in ("completedAt", "error", "result", "operationId"):
                        step.pop(key, None)
                plan["status"] = "running"
                plan["replanCount"] = 0
                plan.pop("completedAt", None)
                plan = self.store.save("plans", plan)
                workspace = self.store.get("workspaces", str(plan["workspaceId"]))
                if workspace:
                    workspace["status"] = "running"
                    workspace = self.store.save("workspaces", workspace)
                self.store.append_event(plan["workspaceId"], "plan.retry_started", {
                    "planId": plan_id, "failedStepId": failed_step["id"],
                    "replayFromTool": plan["steps"][replay_index]["tool"],
                })
                if workspace:
                    self._notify_workspace_state(workspace, plan)
                retry_failed_chain = True
            elif plan.get("status") != "action_required":
                raise ValueError("计划当前没有可重试的审核步骤")
            if retry_failed_chain or retry_qc_chain:
                step = None
            else:
                step = next((item for item in plan["steps"] if item["status"] == "action_required"), None)
            action_tool = str((step or {}).get("tool") or "")
            stale_autonomous_subtitle = bool(
                action_tool == "prepare_subtitle_review"
                and str(plan.get("executionMode") or "") == AUTONOMOUS_REVIEW
            )
            stale_subtitle_layout = action_tool == "layout_subtitles"
            if not (retry_failed_chain or retry_qc_chain) and (
                not step or (
                    action_tool != "propose_timeline_edit"
                    and not stale_autonomous_subtitle
                    and not stale_subtitle_layout
                )
            ):
                raise ValueError("当前审核步骤不能自动重试")
            if retry_failed_chain or retry_qc_chain:
                pass
            elif stale_subtitle_layout:
                # Older plans could mark subtitle preparation completed even
                # though its durable draft/session state was lost. Never let a
                # generic confirmation skip layout_subtitles: replay from the
                # subtitle preparation step so the requested layout is really
                # applied before rendering the review sample.
                replay_index = next((
                    index for index, item in enumerate(plan["steps"])
                    if str(item.get("tool") or "") == "prepare_subtitle_review"
                    and int(item.get("index") or index) < int(step.get("index") or len(plan["steps"]))
                ), None)
                if replay_index is None:
                    raise ValueError("字幕排版缺少字幕草稿步骤，请修改规划后重试")
                for replay_step in plan["steps"][replay_index:]:
                    replay_step["status"] = "pending"
                    for key in ("completedAt", "error", "result", "operationId"):
                        replay_step.pop(key, None)
                plan["status"] = "running"
                plan.pop("completedAt", None)
                plan = self.store.save("plans", plan)
                workspace = self.store.get("workspaces", str(plan["workspaceId"]))
                if not workspace:
                    raise ValueError("Agent Workspace 不存在")
                workspace["status"] = "running"
                workspace = self.store.save("workspaces", workspace)
                self.store.append_event(plan["workspaceId"], "action.retried", {
                    "planId": plan_id,
                    "stepId": step["id"],
                    "replayFromTool": "prepare_subtitle_review",
                    "reason": "subtitle_layout_missing_draft",
                })
                self._notify_workspace_state(workspace, plan)
                retry_subtitle_chain = True
            elif stale_autonomous_subtitle:
                workspace = self.store.get("workspaces", str(plan["workspaceId"]))
                if not workspace:
                    raise ValueError("Agent Workspace 不存在")
                step["arguments"] = {
                    **(step.get("arguments") if isinstance(step.get("arguments"), dict) else {}),
                    "requireConfirmedDraft": False,
                    "autoReview": True,
                }
                step.update({
                    "status": "running", "attempts": int(step.get("attempts") or 0) + 1,
                    "result": {"message": "正在自动生成并校对字幕草稿"},
                })
                step.pop("completedAt", None)
                step.pop("error", None)
                plan["status"] = "running"
                plan = self.store.save("plans", plan)
                self.store.append_event(plan["workspaceId"], "action.retried", {
                    "planId": plan_id, "stepId": step["id"],
                    "reason": "migrate_manual_subtitle_gate_to_automatic_review",
                })
                self._notify_workspace_state(workspace, plan)
            else:
                result = step.get("result") if isinstance(step.get("result"), dict) else {}
                if str(result.get("sessionId") or ""):
                    raise ValueError("时间线草案已经生成，请直接打开审核")
                workspace = self.store.get("workspaces", str(plan["workspaceId"]))
                if not workspace:
                    raise ValueError("Agent Workspace 不存在")
                step.update({
                    "status": "running", "attempts": int(step.get("attempts") or 0) + 1,
                    "result": {"message": "正在重新生成待审核时间线草案"},
                })
                step.pop("completedAt", None)
                step.pop("error", None)
                plan["status"] = "running"
                plan = self.store.save("plans", plan)
                self.store.append_event(plan["workspaceId"], "action.retried", {
                    "planId": plan_id, "stepId": step["id"],
                })
                self._notify_workspace_state(workspace, plan)
        if retry_failed_chain or retry_qc_chain or retry_subtitle_chain:
            self._advance_plan(plan_id)
        else:
            self._execute_step(plan_id, str(step["id"]))
        return self.store.get("plans", plan_id) or plan

    def resolve_action(
        self, plan_id: str, *, approved: bool, value: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._execution_lock:
            plan = self.store.get("plans", plan_id)
            if not plan:
                raise KeyError(plan_id)
            if plan.get("status") != "action_required":
                raise ValueError("计划当前没有待确认操作")
            step = next((item for item in plan["steps"] if item["status"] == "action_required"), None)
            if not step:
                raise ValueError("待确认步骤不存在")
            if approved and step.get("pluginId") and (step.get("result") or {}).get("retryable") is False:
                raise ValueError("工具执行结果尚未核实，请查询操作记录；不能直接确认完成")
            if not approved:
                step.update({"status": "failed", "error": "用户拒绝了该步骤", "completedAt": now_iso()})
                plan["status"] = "failed"
                self.store.save("plans", plan)
                self._finish_plan(plan, "failed")
                return self.store.get("plans", plan_id) or plan
            workspace = self.store.get("workspaces", str(plan["workspaceId"]))
            if not workspace:
                raise ValueError("Agent Workspace 不存在")
            resolved_value = self._validate_action_resolution(workspace, step, value)
            if self._action_resolution_validator:
                resolved_value = self._action_resolution_validator(workspace, step, resolved_value)
            if (step.get("result") or {}).get("action") == "content_evidence_review":
                binder = getattr(self, "_reference_review_binder", None)
                if binder:
                    binder(plan, workspace, resolved_value)
                # Evidence approval precedes the proposal: replay, don't skip it.
                step.update({"status": "pending", "reviewConfirmation": resolved_value})
                step.pop("result", None)
                step.pop("completedAt", None)
            else:
                step.update({
                    "status": "completed", "completedAt": now_iso(),
                    "result": {"userConfirmed": True, "value": resolved_value},
                })
            plan["status"] = "running"
            plan = self.store.save("plans", plan)
            self.store.append_event(plan["workspaceId"], "action.resolved", {
                "planId": plan_id, "stepId": step["id"], "approved": True,
            })
            if workspace:
                self._notify_workspace_state(workspace, plan)
        self._advance_plan(plan_id)
        return self.store.get("plans", plan_id) or plan

    @staticmethod
    def _validate_action_resolution(
        workspace: dict[str, Any], step: dict[str, Any], value: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("请提交本次审核面板产生的结构化确认结果")
        context = value.get("context") if isinstance(value.get("context"), dict) else {}
        if (
            str(context.get("jobId") or "") != str(workspace.get("jobId") or "")
            or str(context.get("stepId") or "") != str(step.get("id") or "")
        ):
            raise ValueError("确认结果与当前 Agent 步骤不匹配，请在对应审核面板完成选择")
        selection = value.get("selection") if isinstance(value.get("selection"), dict) else {}
        required_key = {
            "select_people": "personIds",
            "select_speakers": "speakerRefs",
            "review_cover_variants": "variantIds",
        }.get(str(step.get("tool") or ""))
        if required_key:
            selected = selection.get(required_key)
            if not isinstance(selected, list) or not [item for item in selected if str(item).strip()]:
                label = "人物" if required_key == "personIds" else "说话人" if required_key == "speakerRefs" else "封面"
                raise ValueError(f"请先在审核面板选择至少一个{label}，再继续计划")
        tool_name = str(step.get("tool") or "")
        if tool_name == "layout_subtitles":
            raise ValueError("字幕排版不能通过空确认跳过；请重新生成字幕草稿并执行排版")
        if tool_name == "propose_timeline_edit" and (step.get("result") or {}).get("action") != "content_evidence_review":
            if not str(selection.get("editSessionId") or "") or not str(selection.get("proposalId") or ""):
                raise ValueError("请先在精剪时间线生成待审核的时间线草案，再继续计划")
        if tool_name == "confirm_timeline_edit":
            revision = selection.get("revision")
            if not str(selection.get("editSessionId") or "") or not isinstance(revision, int) or isinstance(revision, bool):
                raise ValueError("请先在精剪时间线应用并保存审核后的草案，再继续计划")
        return copy.deepcopy(value)
