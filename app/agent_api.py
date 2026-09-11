from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent_platform import AgentPlatform, AgentServiceError
from .assistant_interaction import AssistantInteraction
from .agent_store import content_hash, parse_skill_markdown
from .service_security import plugin_tree_hash


class WorkspaceCreateRequest(BaseModel):
    jobId: str = Field(min_length=1, max_length=96)
    title: str = Field(default="", max_length=160)


class AgentMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    skillId: str | None = Field(default=None, max_length=64)
    executionMode: Literal["autonomous_review", "stepwise_review"] = "autonomous_review"
    clientMessageId: str | None = Field(default=None, max_length=96)
    uiContext: dict[str, Any] | None = None
    replyToActionId: str | None = Field(default=None, max_length=96)
    confirmationValue: dict[str, Any] | None = None


class PendingChangeRequest(BaseModel):
    choice: Literal["stop", "after", "discard", "prepare"]


class PlanApprovalRequest(BaseModel):
    planHash: str = Field(min_length=64, max_length=64)


class SkillGenerateRequest(BaseModel):
    request: str = Field(min_length=10, max_length=4000)


class SkillEnableRequest(BaseModel):
    contentHash: str = Field(min_length=64, max_length=64)


class PluginActivationRequest(BaseModel):
    contentHash: str = Field(min_length=64, max_length=64)
    trusted: bool = False


class ActionResolutionRequest(BaseModel):
    approved: bool
    value: dict[str, Any] | None = None


def _safe_extract(archive: Path, destination: Path, *, max_uncompressed: int = 50 * 1024 * 1024) -> None:
    total = 0
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            total += max(0, int(member.file_size))
            if total > max_uncompressed:
                raise ValueError("压缩包解压后超过 50MB 限制")
            member_path = (destination / member.filename).resolve()
            if destination not in member_path.parents and member_path != destination:
                raise ValueError("压缩包包含越界路径")
            if member.is_dir():
                member_path.mkdir(parents=True, exist_ok=True)
                continue
            member_path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, member_path.open("wb") as target:
                shutil.copyfileobj(source, target)


def _single_package_root(path: Path, required_name: str) -> Path:
    if (path / required_name).is_file():
        return path
    candidates = [item for item in path.iterdir() if item.is_dir() and (item / required_name).is_file()]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"压缩包根目录必须包含 {required_name}")


def _safe_package_id(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized) or len(normalized) > 80:
        raise ValueError("包 ID 只能包含小写字母、数字和单连字符")
    return normalized


def build_agent_router(
    *, platform: AgentPlatform,
    job_getter: Callable[[str], dict[str, Any] | None],
) -> APIRouter:
    router = APIRouter(prefix="/api/agent", tags=["agent"])
    conversation = AssistantInteraction(platform, job_getter)

    def workspace_detail(workspace: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str(workspace["id"])
        plans = platform.store.list(
            "plans", predicate=lambda item: item.get("workspaceId") == workspace_id,
        )
        runs = platform.store.list(
            "runs", predicate=lambda item: item.get("workspaceId") == workspace_id,
        )
        return {"workspace": workspace, "plans": plans, "runs": runs}

    @router.get("/health")
    def agent_health() -> dict[str, Any]:
        service = platform.client.health()
        model = platform.model_config_resolver()
        configured = all(str(model.get(key) or "").strip() for key in ("apiKey", "model", "baseUrl"))
        return {
            "status": "ok" if service.get("status") == "ok" else "degraded",
            "pi": service, "skills": len(platform.store.list("skills")),
            "plugins": len(platform.store.list("plugins")),
            "model": {
                "configured": configured,
                "source": str(model.get("configSource") or "agent_settings"),
                "provider": str(model.get("provider") or ""),
                "name": str(model.get("model") or ""),
            },
        }

    @router.get("/workspaces")
    def list_workspaces() -> dict[str, Any]:
        return {"workspaces": platform.store.list("workspaces")}

    @router.post("/workspaces", status_code=201)
    def create_workspace(request: WorkspaceCreateRequest) -> dict[str, Any]:
        job = job_getter(request.jobId)
        if not job:
            raise HTTPException(404, "素材任务不存在")
        workspace = platform.create_workspace(
            job_id=request.jobId, title=request.title or str(job.get("filename") or "智能剪辑工作区"),
        )
        return {"workspace": workspace}

    @router.get("/workspaces/by-job/{job_id}")
    def get_workspace_by_job(job_id: str) -> dict[str, Any]:
        workspace = platform.workspace_for_job(job_id)
        if not workspace:
            raise HTTPException(404, "该任务尚未创建 Agent Workspace")
        return workspace_detail(workspace)

    @router.get("/workspaces/{workspace_id}")
    def get_workspace(workspace_id: str) -> dict[str, Any]:
        workspace = platform.store.get("workspaces", workspace_id)
        if not workspace:
            raise HTTPException(404, "Agent Workspace 不存在")
        return workspace_detail(workspace)

    @router.post("/workspaces/{workspace_id}/messages", status_code=201)
    def send_message(workspace_id: str, request: AgentMessageRequest) -> dict[str, Any]:
        try:
            if request.clientMessageId or request.uiContext is not None:
                return conversation.handle(workspace_id, request.model_dump())
            plan = platform.create_plan(
                workspace_id=workspace_id, goal=request.text.strip(), skill_id=request.skillId,
                execution_mode=request.executionMode,
            )
        except KeyError as error:
            raise HTTPException(404, "Agent Workspace 不存在") from error
        except AgentServiceError as error:
            raise HTTPException(503, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"action": "plan_confirmation", "plan": plan}

    @router.post("/workspaces/{workspace_id}/pending-changes")
    def pending_changes(workspace_id: str, request: PendingChangeRequest) -> dict[str, Any]:
        try:
            return conversation.change(workspace_id, request.choice)
        except KeyError as error:
            raise HTTPException(404, "工作区不存在") from error
        except (ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from error

    @router.post("/workspaces/{workspace_id}/messages/stream")
    def stream_message_plan(
        workspace_id: str, request: AgentMessageRequest,
    ) -> StreamingResponse:
        if request.clientMessageId or request.uiContext is not None:
            if not platform.store.get("workspaces", workspace_id):
                raise HTTPException(404, "工作区不存在")

            async def conversation_events():
                task = asyncio.create_task(asyncio.to_thread(conversation.handle, workspace_id, request.model_dump()))
                task.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())
                planning_announced = False
                # Shield the durable request from an HTTP disconnect.
                try:
                    yield 'event: planning.progress\ndata: {"phase":"context_loading","title":"正在核对输入与引用范围"}\n\n'
                    while not task.done():
                        await asyncio.wait({task}, timeout=2)
                        if not task.done():
                            state = platform.store.get("workspaces", workspace_id) or {}
                            if state.get("planningRequestId") and not planning_announced:
                                planning_announced = True
                                yield 'event: planning.progress\ndata: {"phase":"decomposing_goal","title":"正在整理待确认方案","detail":"确认前不会执行媒体分析或渲染"}\n\n'
                            yield ": heartbeat\n\n"
                    result = task.result()
                    event = "plan" if result.get("action") == "plan_confirmation" else "assistant.result"
                    yield f"event: {event}\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"
                except (ValueError, RuntimeError, KeyError) as error:
                    yield f"event: error\ndata: {json.dumps({'message': str(error)}, ensure_ascii=False)}\n\n"

            return StreamingResponse(conversation_events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        try:
            workspace, skill, payload = platform.prepare_plan_request(
                workspace_id=workspace_id, goal=request.text.strip(), skill_id=request.skillId,
                execution_mode=request.executionMode,
            )
        except KeyError as error:
            raise HTTPException(404, "Agent Workspace 不存在") from error
        except (AgentServiceError, ValueError) as error:
            raise HTTPException(503 if isinstance(error, AgentServiceError) else 400, str(error)) from error

        async def proxy_events():
            event_type = "message"
            data_lines: list[str] = []
            plan_emitted = False

            async def fallback_plan(reason: str) -> tuple[str, dict[str, Any]]:
                try:
                    plan = await asyncio.to_thread(
                        platform.persist_fallback_plan,
                        workspace=workspace, skill=skill, goal=request.text.strip(),
                        execution_mode=request.executionMode,
                        error=AgentServiceError(reason),
                    )
                except (AgentServiceError, ValueError) as error:
                    return "error", {"message": str(error)}
                return "plan", {
                    "action": "plan_confirmation", "plan": plan,
                    "warning": "在线规划服务暂不可用，已使用内置确定性规划。",
                }

            async def flush_event():
                nonlocal event_type, data_lines, plan_emitted
                if not data_lines:
                    return None
                raw = "\n".join(data_lines)
                current_type = event_type
                event_type = "message"
                data_lines = []
                try:
                    value = json.loads(raw)
                except ValueError:
                    value = {"text": raw}
                if current_type == "plan":
                    if not isinstance(value, dict):
                        return "error", {"message": "Pi Agent 返回的计划事件格式无效"}
                    try:
                        plan = await asyncio.to_thread(
                            platform.persist_plan_result,
                            workspace=workspace, skill=skill, goal=request.text.strip(),
                            result={**value, "events": []}, execution_mode=request.executionMode,
                        )
                    except (ValueError, KeyError) as error:
                        return "error", {"message": str(error)}
                    plan_emitted = True
                    return "plan", {"action": "plan_confirmation", "plan": plan}
                if current_type == "error":
                    return "fallback", value
                if isinstance(value, dict):
                    await asyncio.to_thread(
                        platform.store.append_event,
                        workspace_id, "agent.message_update", value,
                    )
                    if current_type == "planning.progress":
                        await asyncio.to_thread(
                            platform.record_planning_progress, workspace_id, value,
                        )
                return current_type, value

            try:
                async with httpx.AsyncClient(timeout=platform.client.timeout_seconds) as client:
                    async with client.stream(
                        "POST", f"{platform.client.base_url}/v1/plan/stream", json=payload,
                    ) as response:
                        if response.status_code >= 400:
                            body = await response.aread()
                            name, value = await fallback_plan(
                                f"Pi Agent 请求未完成：HTTP {response.status_code} "
                                + body.decode("utf-8", "replace")[:500]
                            )
                            if name == "plan":
                                plan_emitted = True
                            yield f"event: {name}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"
                            return
                        async for line in response.aiter_lines():
                            if line.startswith("event:"):
                                event_type = line[6:].strip() or "message"
                            elif line.startswith("data:"):
                                data_lines.append(line[5:].lstrip())
                            elif not line:
                                flushed = await flush_event()
                                if flushed:
                                    name, value = flushed
                                    if name == "fallback":
                                        name, value = await fallback_plan(str(value.get("message") or value))
                                        if name == "plan":
                                            plan_emitted = True
                                    yield f"event: {name}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"
                                    if plan_emitted:
                                        return
                        flushed = await flush_event()
                        if flushed:
                            name, value = flushed
                            if name == "fallback":
                                name, value = await fallback_plan(str(value.get("message") or value))
                                if name == "plan":
                                    plan_emitted = True
                            yield f"event: {name}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"
                        if not plan_emitted:
                            name, value = await fallback_plan("Pi Agent 连接结束但没有返回计划")
                            if name == "plan":
                                plan_emitted = True
                            yield f"event: {name}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"
            except httpx.HTTPError as error:
                name, value = await fallback_plan(f"Pi Agent 服务不可用：{error}")
                if name == "plan":
                    plan_emitted = True
                yield f"event: {name}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"
            finally:
                await asyncio.to_thread(
                    platform.release_plan_request,
                    workspace_id,
                    request_id=str(workspace.get("planningRequestId") or ""),
                )

        return StreamingResponse(
            proxy_events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/workspaces/{workspace_id}/events")
    def stream_events(
        workspace_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        if not platform.store.get("workspaces", workspace_id):
            raise HTTPException(404, "Agent Workspace 不存在")

        async def events():
            try:
                cursor = max(after, int(request.headers.get("Last-Event-ID") or 0))
            except ValueError:
                cursor = after
            idle_ticks = 0
            while True:
                if await request.is_disconnected():
                    return
                rows = await asyncio.to_thread(
                    platform.store.events_after, workspace_id, cursor,
                )
                if rows:
                    idle_ticks = 0
                    for event in rows:
                        cursor = int(event["sequence"])
                        data = json.dumps(event, ensure_ascii=False)
                        yield f"id: {cursor}\nevent: {event['type']}\ndata: {data}\n\n"
                else:
                    idle_ticks += 1
                    if idle_ticks % 15 == 0:
                        yield ": keep-alive\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/plans/{plan_id}")
    def get_plan(plan_id: str) -> dict[str, Any]:
        plan = platform.store.get("plans", plan_id)
        if not plan:
            raise HTTPException(404, "执行计划不存在")
        return {"plan": plan}

    @router.post("/plans/{plan_id}/confirm")
    def confirm_plan(plan_id: str, request: PlanApprovalRequest) -> dict[str, Any]:
        try:
            plan = platform.approve_plan(plan_id, expected_hash=request.planHash)
        except KeyError as error:
            raise HTTPException(404, "执行计划不存在") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"plan": plan}

    @router.post("/plans/{plan_id}/cancel")
    def cancel_plan(plan_id: str) -> dict[str, Any]:
        try:
            return {"plan": platform.cancel_plan(plan_id)}
        except KeyError as error:
            raise HTTPException(404, "执行计划不存在") from error

    @router.post("/plans/{plan_id}/actions/resolve")
    def resolve_plan_action(plan_id: str, request: ActionResolutionRequest) -> dict[str, Any]:
        try:
            plan = platform.resolve_action(
                plan_id, approved=request.approved, value=request.value,
            )
        except KeyError as error:
            raise HTTPException(404, "执行计划不存在") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"plan": plan}

    @router.post("/plans/{plan_id}/actions/retry")
    def retry_plan_action(plan_id: str) -> dict[str, Any]:
        try:
            return {"plan": platform.retry_action(plan_id)}
        except KeyError as error:
            raise HTTPException(404, "执行计划不存在") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @router.get("/skills")
    def list_skills() -> dict[str, Any]:
        return {"skills": platform.store.list("skills")}

    @router.post("/skills/install", status_code=201)
    async def install_skill(file: UploadFile = File(...)) -> dict[str, Any]:
        if not str(file.filename or "").lower().endswith(".zip"):
            raise HTTPException(400, "请上传 ZIP 格式的标准 Skill 包")
        payload = await file.read(10 * 1024 * 1024 + 1)
        if len(payload) > 10 * 1024 * 1024:
            raise HTTPException(413, "Skill 包不能超过 10MB")
        with tempfile.TemporaryDirectory(prefix="cliptalk-skill-") as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "skill.zip"
            archive.write_bytes(payload)
            extracted = temporary_path / "extracted"
            extracted.mkdir()
            try:
                _safe_extract(archive, extracted)
                package_root = _single_package_root(extracted, "SKILL.md")
                markdown = (package_root / "SKILL.md").read_text(encoding="utf-8")
                fields = parse_skill_markdown(markdown)
                digest = content_hash(payload)
                target = platform.skills_root / fields["name"] / digest
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(package_root, target)
                skill = platform.install_skill(
                    markdown=markdown, source="upload", status="validated", path=str(target),
                )
            except (OSError, ValueError, zipfile.BadZipFile, UnicodeError) as error:
                raise HTTPException(400, str(error)) from error
        return {"skill": skill}

    @router.post("/skills/generate", status_code=201)
    def generate_skill(request: SkillGenerateRequest) -> dict[str, Any]:
        try:
            return {"skill": platform.generate_skill(request=request.request.strip())}
        except (AgentServiceError, ValueError) as error:
            raise HTTPException(503 if isinstance(error, AgentServiceError) else 400, str(error)) from error

    @router.post("/skills/{skill_id}/enable")
    def enable_skill(skill_id: str, request: SkillEnableRequest) -> dict[str, Any]:
        try:
            return {"skill": platform.enable_skill(skill_id, request.contentHash)}
        except KeyError as error:
            raise HTTPException(404, "Skill 不存在") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @router.post("/skills/{skill_id}/disable")
    def disable_skill(skill_id: str) -> dict[str, Any]:
        skill = platform.store.get("skills", skill_id)
        if not skill:
            raise HTTPException(404, "Skill 不存在")
        skill["status"] = "disabled"
        return {"skill": platform.store.save("skills", skill)}

    @router.get("/plugins")
    def list_plugins() -> dict[str, Any]:
        return {"plugins": platform.store.list("plugins")}

    @router.post("/plugins/inspect", status_code=201)
    async def inspect_plugin(file: UploadFile = File(...)) -> dict[str, Any]:
        if not str(file.filename or "").lower().endswith(".zip"):
            raise HTTPException(400, "请上传 ZIP 格式的 Plugin 包")
        payload = await file.read(25 * 1024 * 1024 + 1)
        if len(payload) > 25 * 1024 * 1024:
            raise HTTPException(413, "Plugin 包不能超过 25MB")
        digest = content_hash(payload)
        with tempfile.TemporaryDirectory(prefix="cliptalk-plugin-") as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "plugin.zip"
            archive.write_bytes(payload)
            extracted = temporary_path / "extracted"
            extracted.mkdir()
            try:
                _safe_extract(archive, extracted)
                package_root = _single_package_root(extracted, "cliptalk-plugin.json")
                manifest = json.loads((package_root / "cliptalk-plugin.json").read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise ValueError("Plugin manifest 格式无效")
                plugin_id = _safe_package_id(str(manifest.get("id") or ""))
                version = str(manifest.get("version") or "").strip()
                if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
                    raise ValueError("Plugin version 必须是精确 SemVer，不能使用范围或浮动标签")
                entrypoint = str(manifest.get("entrypoint") or "index.mjs").strip()
                entry_path = (package_root / entrypoint).resolve()
                if package_root.resolve() not in entry_path.parents or not entry_path.is_file():
                    raise ValueError("Plugin entrypoint 不存在或越过包目录")
                tools = manifest.get("tools")
                if not isinstance(tools, list) or not tools:
                    raise ValueError("Plugin 至少需要声明一个工具")
                tool_names: set[str] = set()
                for tool in tools:
                    if not isinstance(tool, dict):
                        raise ValueError("Plugin 工具声明格式无效")
                    tool_name = str(tool.get("name") or "")
                    if not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", tool_name):
                        raise ValueError("Plugin tool name 必须使用小写字母、数字和下划线")
                    if tool_name in tool_names:
                        raise ValueError(f"Plugin 工具名称重复：{tool_name}")
                    tool_names.add(tool_name)
                    if str(tool.get("sideEffect") or "analysis") not in {
                        "read", "analysis", "preview", "identity", "export", "delete",
                    }:
                        raise ValueError(f"Plugin 工具 {tool_name} 的 sideEffect 无效")
                package_json = package_root / "package.json"
                if package_json.is_file():
                    package_state = json.loads(package_json.read_text(encoding="utf-8"))
                    for dependency, requirement in (package_state.get("dependencies") or {}).items():
                        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", str(requirement)):
                            raise ValueError(f"Plugin 依赖 {dependency} 必须固定为精确 SemVer")
                target = platform.plugins_root / plugin_id / digest
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(package_root, target)
                plugin = platform.store.save("plugins", {
                    "id": plugin_id, "version": version, "contentHash": digest,
                    "treeHash": plugin_tree_hash(package_root),
                    "status": "validated", "trusted": False, "path": str(target),
                    "entrypoint": entrypoint, "tools": tools,
                    "permissions": manifest.get("permissions") or {},
                    "source": str(file.filename or "upload.zip"),
                    "warning": "此 Plugin 将在 Agent 进程内运行并拥有该进程的宿主权限。",
                })
            except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, UnicodeError) as error:
                raise HTTPException(400, str(error)) from error
        return {"plugin": plugin}

    @router.post("/plugins/{plugin_id}/activate")
    def activate_plugin(plugin_id: str, request: PluginActivationRequest) -> dict[str, Any]:
        plugin = platform.store.get("plugins", plugin_id)
        if not plugin:
            raise HTTPException(404, "Plugin 不存在")
        if not request.trusted:
            raise HTTPException(400, "必须明确确认信任此 Plugin 的宿主进程权限")
        if plugin.get("contentHash") != request.contentHash:
            raise HTTPException(409, "Plugin 内容已经变化，请重新审核")
        try:
            result = platform.client.activate_plugin({
                "pluginId": plugin_id, "version": plugin.get("version"),
                "contentHash": plugin["contentHash"], "path": plugin["path"],
                "treeHash": plugin.get("treeHash"),
                "entrypoint": plugin["entrypoint"], "tools": plugin["tools"],
            })
        except AgentServiceError as error:
            raise HTTPException(503, str(error)) from error
        plugin.update({"status": "enabled", "trusted": True, "runtime": result})
        return {"plugin": platform.store.save("plugins", plugin)}

    @router.post("/plugins/{plugin_id}/disable")
    def disable_plugin(plugin_id: str) -> dict[str, Any]:
        plugin = platform.store.get("plugins", plugin_id)
        if not plugin:
            raise HTTPException(404, "Plugin 不存在")
        try:
            platform.client.deactivate_plugin(plugin_id)
        except AgentServiceError:
            pass
        plugin["status"] = "disabled"
        return {"plugin": platform.store.save("plugins", plugin)}

    return router
