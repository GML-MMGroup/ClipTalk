"""Conversation routing and immutable UI references; never execute from an answer."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import uuid
from typing import Any

from .agent_store import now_iso


def message_intent(text: str) -> str:
    value = text.strip()
    if re.fullmatch(r"(?:可以|好的?|继续|确认|开始|ok|yes)[。！!\s]*", value, re.I):
        return "confirmation"
    if re.search(r"为什么|怎么回事|是否|合理吗|在哪里|在哪|如何|怎么|解释|分析.*问题|[吗呢][？?。]*$|\b(?:what|why|how)\b", value, re.I):
        return "answer"
    if re.search(r"不对|不相关|无关|错了|不符合|有问题", value):
        return "feedback"
    if re.search(
        r"剪|找|检索|搜索|合成|合并|生成|改|调整|删除|去掉|不要|保留|添加|字幕|导出|竖屏|横屏|方屏|封面|缩短|重排|"
        r"再短一点|再短些|更短(?:一点|些)?|稍微短(?:一点|些)?|再精简|再紧凑|"
        r"从.{1,80}(?:开始|开始剪|起剪)|edit|find|merge|remove|change",
        value,
        re.I,
    ):
        return "edit"
    return "clarification"


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def output_references(job: dict) -> list[dict]:
    return [item for item in [
        *(job.get("outputs") or []), *(job.get("agentPreviewOutputs") or []),
        *(job.get("agentReviewPreviews") or []),
        *[output for version in job.get("outputVersions") or [] for output in [*(version.get("outputs") or []), *(version.get("previewOutputs") or [])]],
    ] if isinstance(item, dict)]


def freeze_context(job: dict, ui: dict, *, read_only: bool = False) -> dict:
    """Resolve IDs against server state, not client-provided evidence or paths."""
    ui = copy.deepcopy(ui)
    if len(json.dumps(ui, ensure_ascii=False)) > 20000:
        raise ValueError("引用信息过多，请减少选区后重试")
    if not isinstance(ui.get("selected", {}), dict) or not isinstance(ui.get("viewer", {}), dict):
        raise ValueError("引用格式无效，请重新选择")
    if ui.get("jobId") and ui["jobId"] != job.get("id"):
        raise ValueError("引用不属于当前任务，请重新选择")
    if ui.get("jobRevision") is not None and str(ui["jobRevision"]) != str(job.get("revision", 0)):
        raise ValueError("任务已变化，请查看最新状态后重新发送")
    frozen = {"jobId": job["id"], "ui": ui}
    selected = ui.get("selected") or {}
    if "contentMatchIds" in selected:
        if not isinstance(selected["contentMatchIds"], list) or any(not isinstance(x, str) for x in selected["contentMatchIds"]):
            raise ValueError("片段引用格式无效")
        search = job.get("contentSearch") or {}
        if ui.get("searchId") != search.get("id"):
            raise ValueError("检索结果已更新，请重新选择片段")
        ids = list(dict.fromkeys(selected["contentMatchIds"]))
        candidates = {str(item.get("id")): item for item in search.get("candidates") or []}
        if any(item not in candidates for item in ids):
            raise ValueError("引用的片段已失效，请重新选择")
        frozen["contentSelection"] = {
            "searchId": search["id"], "matchIds": ids,
            "fingerprint": fingerprint([candidates[item] for item in ids]),
        }
    viewer = ui.get("viewer") or {}
    if viewer.get("outputFilename"):
        output = next((item for item in output_references(job) if item.get("filename") == viewer["outputFilename"]), None)
        if not output:
            raise ValueError("引用的样片或版本已失效，请重新选择")
        frozen["outputFilename"] = output["filename"]
        session_id = output.get("sourceEditSessionId") or output.get("editSessionId") or output.get("sessionId")
        session = next((s for s in job.get("editSessions") or [] if s.get("id") == session_id), None)
        if session:
            frozen.update({"editSessionId": session_id, "editSessionRevision": session.get("revision", 0)})
        version = next((v for v in job.get("outputVersions") or [] if any(x.get("filename") == output["filename"] for x in v.get("outputs") or [])), None)
        if version:
            frozen["outputVersionId"] = version["id"]
        reframe = output.get("reframe") or {}
        if reframe.get("aspect"):
            frozen["outputAspect"] = reframe["aspect"]
            frozen["outputFit"] = reframe.get("fit", "blur")
        output_duration = output.get("duration")
        if not isinstance(output_duration, (int, float)) and session:
            output_duration = session.get("duration")
        if isinstance(output_duration, (int, float)) and float(output_duration) > 0:
            frozen["outputDurationSeconds"] = round(float(output_duration), 3)
    ranges = ui.get("timelineSelections") or ([ui["timelineSelection"]] if ui.get("timelineSelection") else [])
    if ranges:
        if not isinstance(ranges, list) or any(not isinstance(x, dict) for x in ranges):
            raise ValueError("时间选区格式无效")
        if ui.get("timeDomain", "source") != "source" and read_only:
            # A question may refer to sample time without mapping it back to
            # source time. Never turn that range into an editable source range.
            return frozen
        if ui.get("timeDomain", "source") != "source":
            raise ValueError("当前选区属于样片时间，请在精剪时间线确认对应片段后再发送")
        duration = float((job.get("videoInfo") or {}).get("duration") or job.get("duration") or 0)
        for item in ranges:
            if not (0 <= float(item.get("start", -1)) < float(item.get("end", -1)) <= duration):
                raise ValueError("时间选区超出源视频范围")
        frozen["sourceRanges"] = [{"start": float(x["start"]), "end": float(x["end"])} for x in ranges]
    return frozen


def validate_frozen(job: dict, frozen: dict) -> None:
    if not frozen:
        return
    if frozen.get("jobId") != job.get("id") and not (
        job.get("parentJobId") == frozen.get("jobId")
        and not frozen.get("contentSelection") and not frozen.get("outputFilename")
    ):
        raise ValueError("引用任务已变化，请重新确认方案")
    selection = frozen.get("contentSelection")
    if selection:
        search = job.get("contentSearch") or {}
        candidates = {str(x.get("id")): x for x in search.get("candidates") or []}
        if (search.get("id") != selection["searchId"]
                or any(x not in candidates for x in selection["matchIds"])
                or fingerprint([candidates[x] for x in selection["matchIds"]]) != selection["fingerprint"]):
            raise ValueError("引用片段或证据已更新，请重新核验并生成方案")
    if frozen.get("outputFilename") and not any(x.get("filename") == frozen["outputFilename"] for x in output_references(job)):
        raise ValueError("引用版本已失效，请重新选择")
    if frozen.get("editSessionId"):
        session = next((s for s in job.get("editSessions") or [] if s.get("id") == frozen["editSessionId"]), None)
        if not session or session.get("revision", 0) != frozen.get("editSessionRevision"):
            raise ValueError("引用样片的时间线已变化，请重新生成或选择最新版本")


def revised_goal(original: str, revision: str) -> str:
    base = original
    if re.search(r"竖屏|横屏|方屏|\d+:\d+", revision):
        base = re.sub(r"竖屏|横屏|方屏|\d+:\d+", "", base)
    if re.search(r"字幕", revision):
        base = re.sub(r"(?:不要|不添加|添加|加|保留|生成)?\s*(?:AI\s*)?字幕", "", base)
    if re.search(r"\d+\s*(?:秒|分钟)", revision) or re.search(
        r"再短一点|再短些|更短|再精简|再紧凑", revision
    ):
        base = re.sub(r"\d+(?:\.\d+)?\s*(?:秒|分钟)", "", base)
    return f"{revision}。保留其余要求：{base}"[:4000]


class AssistantInteraction:
    def __init__(self, platform, job_getter):
        self.platform = platform
        self.job_getter = job_getter
        self.locks: dict[str, threading.RLock] = {}
        self.stopping: dict[str, list] = {}
        platform._conversation_finished = self.on_finished
        platform._reference_validator = self.validate_plan
        platform._reference_review_binder = self.bind_review

    def bind_review(self, plan: dict, workspace: dict, resolved: dict) -> None:
        selection = resolved.get("selection") or {}
        if not selection.get("searchId") or not selection.get("matchIds"):
            raise ValueError("请提交本次核验的检索与片段范围")
        frozen = freeze_context(self.job_getter(workspace["jobId"]) or {}, {
            "jobId": workspace["jobId"], "searchId": selection["searchId"],
            "selected": {"contentMatchIds": selection["matchIds"]},
        })
        plan.setdefault("referenceReviews", []).append({"previous": plan.get("inputContext"), "confirmed": frozen, "createdAt": now_iso()})
        plan["inputContext"] = frozen

    def validate_plan(self, plan: dict) -> None:
        frozen = plan.get("inputContext") or {}
        if frozen:
            validate_frozen(self.job_getter(frozen["jobId"]) or {}, frozen)

    def workspace(self, workspace_id: str) -> dict:
        result = self.platform.store.get("workspaces", workspace_id)
        if not result:
            raise KeyError(workspace_id)
        return result

    def record(self, workspace_id: str, message: dict) -> None:
        with self.platform._execution_lock:
            workspace = self.workspace(workspace_id)
            messages = list(workspace.get("messages") or [])
            index = next((i for i, item in enumerate(messages) if item.get("id") == message["id"]), None)
            if index is None:
                messages.append(message)
            else:
                messages[index] = message
            workspace["messages"] = messages
            self.platform.store.save("workspaces", workspace)

    def answer(self, workspace: dict, plan: dict | None, text: str, ui: dict) -> str:
        job = self.job_getter(workspace["jobId"]) or {}
        issues = []
        for step in (plan or {}).get("steps") or []:
            artifact = (step.get("result") or {}).get("artifact") or {}
            for report in artifact.get("reports") or []:
                issues.extend(str(x.get("message")) for x in report.get("issues") or [] if x.get("message"))
        search = job.get("contentSearch") or {}
        provider = getattr(self.platform, "_conversation_answer_provider", None)
        if provider:
            facts = {
                "goal": (plan or {}).get("goal"), "status": (plan or {}).get("status"),
                "issues": issues, "query": search.get("instruction"),
                "coverageComplete": search.get("coverageComplete"),
                "candidates": [{k: x.get(k) for k in ("id", "start", "end", "title", "boundaryVerification")} for x in (search.get("candidates") or [])[:30]],
                "outputs": [{k: x.get(k) for k in ("filename", "title", "previewOnly", "outputKind")} for x in output_references(job)],
                "uiContext": ui,
            }
            try:
                answer = provider(workspace["jobId"], text, facts)
                if isinstance(answer, str) and answer.strip():
                    return answer.strip()[:6000] + "\n本条询问未修改视频。"
            except Exception:
                # A missing model is not authorization to run a fallback edit.
                pass
        parts = [f"当前要求：{plan['goal']}。" if plan else "当前还没有剪辑方案。"]
        if issues:
            parts.append("已有检查记录：" + "；".join(dict.fromkeys(issues)) + "。可在执行详情中定位问题。")
        if search.get("id"):
            parts.append(f"当前检索有 {len(search.get('candidates') or [])} 个候选；" + ("已完成设定范围的检索。" if search.get("coverageComplete") else "检索覆盖尚不完整，候选数量不代表全部命中。"))
        parts.append("以上仅依据已保存的任务和检查记录；不足以确定具体画面问题的原因。请引用问题片段或打开检查详情。本条询问不会修改视频。")
        return "\n".join(parts)

    def handle(self, workspace_id: str, request: dict) -> dict:
        # Serialize only one workspace, never hold the platform execution lock
        # across model calls. Client IDs make retries safe after disconnects.
        with self.locks.setdefault(workspace_id, threading.RLock()):
            workspace = self.workspace(workspace_id)
            message_id = request.get("clientMessageId") or f"msg_{uuid.uuid4().hex}"
            text = request["text"].strip()
            old = next((m for m in workspace.get("messages") or [] if m.get("id") == message_id), None)
            if old:
                if old.get("text") != text:
                    raise ValueError("消息标识已用于其他要求，请重新发送")
                if old.get("response"):
                    response = copy.deepcopy(old["response"])
                    if response.get("plan"):
                        response["plan"] = self.platform.store.get("plans", response["plan"]["id"]) or response["plan"]
                    return response
                return {"action": "clarification", "message": "这条要求已接收，正在处理。请刷新任务状态，不必重复提交。"}
            message = {"id": message_id, "role": "user", "text": text, "createdAt": now_iso(), "status": "received"}
            self.record(workspace_id, message)
            plan = self.platform.store.get("plans", str(workspace.get("activePlanId") or ""))
            try:
                intent = message_intent(text)
                if intent == "answer":
                    ui = request.get("uiContext") or {}
                    # Questions validate ownership too, but a changing progress
                    # revision does not invalidate a read-only status question.
                    frozen = freeze_context(self.job_getter(workspace["jobId"]) or {}, {k: v for k, v in ui.items() if k != "jobRevision"}, read_only=True)
                    response = {"action": "answer", "message": self.answer(workspace, plan, text, ui)}
                elif intent == "confirmation":
                    action_id = request.get("replyToActionId")
                    if not plan or action_id != plan.get("id"):
                        response = {"action": "clarification", "message": "请确认要继续哪一步。请使用当前方案或审核卡上的确认按钮；不会据此启动导出。"}
                    elif any(s.get("sideEffect") == "export" or "export" in str(s.get("tool")) for s in plan.get("steps") or []):
                        response = {"action": "clarification", "message": "这份方案涉及正式导出，请在导出确认入口核对目标版本和设置。"}
                    elif (request.get("uiContext") or {}).get("confirmationHash") != plan.get("planHash"):
                        response = {"action": "clarification", "message": "当前方案已变化，请查看最新方案后再确认。"}
                    elif plan.get("status") == "awaiting_confirmation":
                        updated = self.platform.approve_plan(plan["id"], expected_hash=plan["planHash"])
                        response = {"action": "plan_updated", "plan": updated, "message": "已确认当前方案，可在状态栏查看执行进度。"}
                    elif plan.get("status") == "action_required" and request.get("confirmationValue"):
                        updated = self.platform.resolve_action(plan["id"], approved=True, value=request["confirmationValue"])
                        response = {"action": "plan_updated", "plan": updated, "message": "已提交当前审核结果，可在状态栏查看后续进度。"}
                    else:
                        response = {"action": "clarification", "message": "请核对当前方案后使用确认按钮；片段审核与正式导出仍需在对应卡片中确认。", "plan": plan}
                elif intent in {"feedback", "clarification"}:
                    response = {"action": "clarification", "message": "请引用具体片段，并说明要删除、替换还是重新查找；目前只记录反馈，不修改视频。" if intent == "feedback" else "你希望我解释当前结果，还是执行剪辑？请补充具体操作和范围。"}
                else:
                    ui = request.get("uiContext") or {}
                    job = self.job_getter(workspace["jobId"]) or {}
                    if workspace.get("pendingStopPlanId"):
                        handles = self.stopping.get(workspace_id)
                        if (handles is not None and any(h.get("future") and not h["future"].done() for h in handles)) or (handles is None and job.get("status") in {"running", "queued"}):
                            raise ValueError("后台操作尚未确认停止，暂不创建新方案；请等待停止完成")
                    frozen = freeze_context(job, ui)
                    new_search = bool(re.search(r"找出|找到|查找|搜索|检索|重新找|\bfind\b|\bsearch\b", text, re.I))
                    if re.search(r"从.{1,80}(?:开始|起剪)", text):
                        # The anchor search produces a fresh selection while
                        # the referenced output remains the base for revision.
                        frozen.pop("contentSelection", None)
                    if new_search:
                        # Old candidates are context, not the output selection
                        # of a newly requested search.
                        frozen.pop("contentSelection", None)
                        frozen.pop("outputFilename", None)
                        frozen.pop("editSessionId", None)
                        frozen.pop("editSessionRevision", None)
                    elif re.search(r"合成|合并|这几段|所选片段|选中片段", text):
                        frozen.pop("outputFilename", None)
                        frozen.pop("editSessionId", None)
                        frozen.pop("editSessionRevision", None)
                    elif frozen.get("outputFilename"):
                        frozen.pop("contentSelection", None)
                    if (ui.get("selected") or {}).get("eventGroupIds") or (ui.get("selected") or {}).get("eventSegmentIds"):
                        raise ValueError("请使用所选事件旁的合成按钮，以保留事件和镜头顺序")
                    if len(frozen.get("sourceRanges") or []) > 1:
                        raise ValueError("请使用时间轴的合成所选片段按钮，保留多个选区及顺序")
                    if "playheadSeconds" in ui:
                        raise ValueError("已记录播放位置；请先在时间轴选定明确的起止范围，再提交修改")
                    if re.search(r"这几段|所选片段|选中片段", text) and not new_search and not (frozen.get("contentSelection") or frozen.get("sourceRanges")):
                        raise ValueError("这条要求没有绑定片段，请先选择要使用的片段")
                    if frozen.get("contentSelection") and not frozen["contentSelection"]["matchIds"]:
                        raise ValueError("当前未选择片段，请选择后再合成")
                    active = self.platform.active_plan_for_workspace(workspace)
                    if workspace.get("planningRequestId") or (active and active.get("status") != "awaiting_confirmation"):
                        pending = list(workspace.get("pendingChanges") or [])
                        pending.append({"id": message_id, "text": text, "inputContext": frozen, "status": "pending", "planId": (plan or {}).get("id")})
                        with self.platform._execution_lock:
                            current = self.workspace(workspace_id)
                            current["pendingChanges"] = pending
                            self.platform.store.save("workspaces", current)
                        response = {"action": "pending_change", "message": "修改已暂存，当前执行不会中断，也不会自动应用。请选择停止后重新规划，或完成后再处理。", "pendingChanges": pending}
                    else:
                        replaces = active["id"] if active else None
                        goal = revised_goal(active["goal"], text) if active else text
                        if not active and not new_search and re.search(
                            r"改|调整|不要|删除|去掉|缩短|重排|"
                            r"再短一点|再短些|更短(?:一点|些)?|稍微短(?:一点|些)?|再精简|再紧凑|"
                            r"从.{1,80}(?:开始|开始剪|起剪)",
                            text,
                        ) and (job.get("activeEditSessionId") or output_references(job)):
                            goal = f"修改当前成片：{text}"
                        new_plan = self.platform.create_plan(
                            workspace_id=workspace_id, goal=goal, skill_id=request.get("skillId"),
                            execution_mode=request.get("executionMode") or "autonomous_review",
                            input_context=frozen, replaces_plan_id=replaces, message_id=message_id,
                        )
                        response = {"action": "plan_confirmation", "plan": new_plan, "message": "已整理本次要求，请核对引用范围和修改项后开始执行。"}
            except (ValueError, RuntimeError) as error:
                response = {"action": "clarification", "message": str(error), "retryable": True}
            message.update({"status": "completed", "response": response, "inputContext": locals().get("frozen", {})})
            if response.get("plan"):
                message["planId"] = response["plan"]["id"]
            self.record(workspace_id, message)
            self.record(workspace_id, {"id": message_id + ":reply", "role": "assistant", "kind": response["action"], "text": response.get("message", ""), "planId": message.get("planId"), "createdAt": now_iso()})
            return response

    def change(self, workspace_id: str, choice: str) -> dict:
        with self.locks.setdefault(workspace_id, threading.RLock()):
            workspace = self.workspace(workspace_id)
            pending = workspace.get("pendingChanges") or []
            if not pending:
                return {"action": "answer", "message": "没有待处理修改。", "pendingChanges": []}
            active = self.platform.active_plan_for_workspace(workspace)
            if choice == "discard":
                pending = []
            elif choice == "after":
                pending = [{**item, "status": "after_completion"} for item in pending]
            elif choice == "stop":
                if workspace.get("planningRequestId"):
                    raise ValueError("方案仍在生成，请等生成结束后再处理修改")
                if active:
                    if any(s.get("pluginId") and (s.get("result") or {}).get("retryable") is False for s in active.get("steps") or []):
                        raise ValueError("外部操作状态尚未核实，请先在执行详情中核实，暂不重规划")
                    handles = [h for (pid, _), h in self.platform._operation_handles.items() if pid == active["id"]]
                    self.stopping[workspace_id] = handles
                    with self.platform._execution_lock:
                        current = self.workspace(workspace_id)
                        current["pendingStopPlanId"] = active["id"]
                        self.platform.store.save("workspaces", current)
                    self.platform.cancel_plan(active["id"])
                    if any(h.get("future") and not h["future"].done() for h in handles):
                        raise ValueError("已请求停止，后台操作尚未结束。请等待任务停止后再点击重新规划")
                return self.apply_pending(workspace_id, pending)
            elif choice == "prepare":
                if active or workspace.get("planningRequestId"):
                    raise ValueError("当前任务尚未结束，修改仍已保留")
                return self.apply_pending(workspace_id, pending)
            with self.platform._execution_lock:
                workspace = self.workspace(workspace_id)
                workspace["pendingChanges"] = pending
                self.platform.store.save("workspaces", workspace)
            if choice == "after" and not active:
                return self.apply_pending(workspace_id, pending)
            return {"action": "pending_change", "message": "修改已撤回。" if choice == "discard" else "当前执行结束后将整理修改方案，仍需你确认执行。", "pendingChanges": pending}

    def apply_pending(self, workspace_id: str, pending: list) -> dict:
        workspace = self.workspace(workspace_id)
        job = self.job_getter(workspace["jobId"]) or {}
        if workspace.get("pendingStopPlanId"):
            handles = self.stopping.get(workspace_id)
            if (handles is not None and any(h.get("future") and not h["future"].done() for h in handles)) or (handles is None and job.get("status") in {"running", "queued"}):
                raise ValueError("后台操作尚未确认停止，暂不启动新方案；修改已保留")
        for item in pending:
            validate_frozen(job, item["inputContext"])
        if len({fingerprint({k: v for k, v in x["inputContext"].items() if k != "ui"}) for x in pending}) != 1:
            raise ValueError("暂存修改引用了不同范围，请撤回后合并为一条明确要求")
        aspects = {{"竖屏": "9:16", "横屏": "16:9", "方屏": "1:1"}.get(a, a) for x in pending for a in re.findall(r"竖屏|横屏|方屏|\d+:\d+", x["text"])}
        durations = {int(n) * (60 if unit == "分钟" else 1) for x in pending for n, unit in re.findall(r"(\d+)\s*(秒|分钟)", x["text"])}
        if len(aspects) > 1 or len(durations) > 1 or (any("不要字幕" in x["text"] for x in pending) and any("添加字幕" in x["text"] for x in pending)):
            raise ValueError("暂存修改存在冲突，请撤回后提交最终画幅、字幕和时长要求")
        previous = self.platform.store.get("plans", str(pending[0].get("planId") or "")) or {}
        revision = "；".join(x["text"] for x in pending)
        goal = revised_goal(previous["goal"], revision) if previous.get("goal") else revision
        plan = self.platform.create_plan(workspace_id=workspace_id, goal=goal, input_context=pending[-1]["inputContext"], message_id=pending[-1]["id"])
        with self.platform._execution_lock:
            workspace = self.workspace(workspace_id)
            workspace["pendingChanges"] = []
            workspace.pop("pendingStopPlanId", None)
            pending_ids = {item["id"] for item in pending}
            for message in workspace.get("messages") or []:
                if message.get("id") in pending_ids:
                    message["planId"] = plan["id"]
            workspace.setdefault("messages", []).append({"id": f"pending-plan:{plan['id']}", "role": "assistant", "kind": "plan_confirmation", "planId": plan["id"], "text": "暂存修改已整理为新方案，确认后才会执行。", "createdAt": now_iso()})
            self.platform.store.save("workspaces", workspace)
        return {"action": "plan_confirmation", "plan": plan, "message": "修改方案已准备好，确认后才会执行。", "pendingChanges": []}

    def on_finished(self, workspace_id: str) -> None:
        def prepare():
            with self.locks.setdefault(workspace_id, threading.RLock()):
                workspace = self.workspace(workspace_id)
                pending = workspace.get("pendingChanges") or []
                if not pending or not all(x.get("status") == "after_completion" for x in pending):
                    return
                try:
                    self.apply_pending(workspace_id, pending)
                except (ValueError, RuntimeError) as error:
                    self.record(workspace_id, {"id": f"pending-error:{pending[-1]['id']}", "role": "assistant", "kind": "clarification", "text": str(error), "createdAt": now_iso()})
        threading.Thread(target=prepare, daemon=True).start()
