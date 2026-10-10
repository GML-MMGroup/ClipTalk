"""Durable source-rendered delivery; invoked only by the approved core tool."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

from .automatic_delivery import AUTOMATIC_DELIVERY, DELIVERY_TOOL, delivery_session_ids
from .render_spec import content_hash
from .automatic_delivery_effects import delivery_effects, apply_effects
from .delivery_lineage import intro_offset, freeze_timeline, cover_interval, remap_subtitle_cues
from .delivery_contract import cover_intro_seconds


def prepare_delivery(runtime: Any, workspace: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("executionMode") != AUTOMATIC_DELIVERY or not plan.get("approval"):
        raise RuntimeError("自动交付缺少本次请求授权")
    if plan.get("id") != workspace.get("activePlanId"):
        raise RuntimeError("当前要求已变化，未生成旧方案成片")
    if DELIVERY_TOOL not in plan["approval"].get("allowedTools", []):
        raise RuntimeError("本次计划未授权自动交付")
    job_id = str(workspace["jobId"])
    with runtime.jobs_lock:
        job = runtime.jobs[job_id]
        effects = delivery_effects(plan)
        standalone = bool(effects.get("motion") and not effects["motion"]["intro"])
        sessions = []
        session_ids = delivery_session_ids(plan)
        direct = {row["sessionId"]: row for step in plan.get("steps", [])
                  if step.get("status") == "completed" and step.get("tool") == "prepare_delivery_timeline"
                  for row in ((step.get("result") or {}).get("artifact") or {}).get("sessions", [])
                  if row.get("sessionId")}
        frozen_input = copy.deepcopy(plan.get("inputContext") or {})
        if not standalone and plan.get("profile") in {"audio-polish", "local-motion", "cover-intro"} and not any(frozen_input.get(k) for k in ("editSessionId", "outputFilename")):
            editing = (plan.get("planningContext") or {}).get("editing") or {}
            if editing.get("currentOutputFilename"):
                frozen_input.update(outputFilename=editing["currentOutputFilename"], outputVersionId=editing.get("currentOutputVersionId"))
            elif editing.get("activeSessionId"):
                frozen_input.update(editSessionId=editing["activeSessionId"], editSessionRevision=editing.get("activeSessionRevision"))
        if standalone:
            session_ids = []
            frozen_input = {}
        selected_context = runtime.output_download_context(job, str(frozen_input.get("outputFilename") or "")) if frozen_input.get("outputFilename") else None
        selected_formal = bool(selected_context and not selected_context[0].get("previewOnly") and not selected_context[1].get("previewOnly"))
        # Effects must consume the selected final file, including its earlier
        # audio/intro edits, not silently rebuild its ancestral timeline.
        if not session_ids and frozen_input.get("editSessionId") and not selected_formal:
            pinned = runtime.find_edit_session(job, frozen_input["editSessionId"])
            if int(pinned.get("revision") or 0) != int(frozen_input.get("editSessionRevision") or 0):
                raise RuntimeError("选定的成片时间线已变化，请重新选择")
            session_ids = [frozen_input["editSessionId"]]
        for session_id in session_ids:
            session = runtime.find_edit_session(job, session_id)
            if session.get("pendingProposal"):
                raise RuntimeError("存在尚未确认的修改，未覆盖当前版本")
            if session.get("previewStatus") != "ready" and session_id not in direct:
                raise RuntimeError("当前时间线预览尚未完成")
            fingerprint = runtime._edit_session_preview_fingerprint(job, session)
            approved = direct.get(session_id)
            if approved and (approved.get("fingerprint") != fingerprint or approved.get("revision") != session.get("revision")):
                raise RuntimeError("已核对时间线发生变化，请重新核对后生成")
            if not approved and session.get("previewFingerprint") != fingerprint:
                raise RuntimeError("时间线或字幕已变化，未导出旧预览")
            preflight = runtime.edit_session_preflight(session, job)
            if not preflight.get("ready"):
                raise RuntimeError("；".join(str(i.get("message")) for i in preflight.get("issues", [])
                                           if i.get("severity") == "error") or "时间线检查未通过")
            segments, cutaways = runtime.build_edit_session_render_plan(job, session)
            draft_id = session.get("subtitleDraftId") if session.get("subtitleEnabled") else None
            if draft_id:
                runtime._validated_subtitle_draft_for_burn(job, draft_id)
            spec = runtime.freeze_spec(
                segments=segments, cutaways=cutaways, text_layers=session.get("textLayers"),
                reframe=runtime._effective_edit_session_reframe(job, session),
                subtitle_mode="burn" if draft_id else "none", subtitle_style=session.get("subtitleStyle") or "clean",
                subtitle_draft=runtime._subtitle_draft_for_job(job, draft_id) if draft_id else None,
            )
            session["renderPlanFingerprint"] = fingerprint
            sessions.append({"id": session_id, "revision": int(session.get("revision") or 0),
                             "fingerprint": fingerprint, "spec": spec})
        source_filename = str(frozen_input.get("outputFilename") or "")
        source_version_id = ""
        if not sessions and not standalone:
            context = runtime.output_download_context(job, source_filename) if source_filename else None
            if not context or context[0].get("previewOnly") or context[1].get("previewOnly"):
                raise RuntimeError("缺少本次请求可复现的时间线或已选正式成片，未把审核样片复制为成片")
            source_version_id = context[1]["id"]
            if frozen_input.get("outputVersionId") and source_version_id != frozen_input["outputVersionId"]:
                raise RuntimeError("选定的成片版本已变化，未处理其他版本")
        brief = plan.get("brief") or {}
        cover = None if standalone and not brief.get("coverRequested") else runtime.current_cover_version(job)
        if brief.get("coverRequested") and not cover:
            raise RuntimeError("本次要求的封面尚未完成")
        request = {"planId": plan["id"], "sessions": sessions, "sourceFilename": source_filename,
                   "sourceVersionId": source_version_id, "effects": effects, "standalone": standalone,
                   "coverVersionId": str((cover or {}).get("id") or ""),
                   "intro": cover_intro_seconds(brief) > 0,
                   "introDuration": cover_intro_seconds(brief) or 1.0}
        request["requestHash"] = content_hash(request)
        runtime.save_job(job)
    future = runtime.submit_render_task(job_id, runtime.run_automatic_delivery, request,
                                        dedup_key=f"automatic-delivery:{plan['id']}:{request['requestHash']}")
    return {"operationId": getattr(future, "operation_id", f"{job_id}:{plan['id']}:delivery"),
            "operation": "automatic_delivery", "accepted": True, "future": future,
            "cancel": lambda: runtime.cancel_job(job_id)}


def run_delivery(runtime: Any, job_id: str, request: dict[str, Any]) -> dict[str, Any]:
    plan_id = str(request["planId"])

    def guard() -> dict[str, Any]:
        job = runtime.jobs[job_id]
        plan = runtime.agent_platform.store.get("plans", plan_id) or {}
        event = runtime.cancel_events.get(job_id)
        if plan.get("status") not in {"running", "approved"} or (event and event.is_set()):
            raise RuntimeError("本次生成已停止，保留已有版本")
        if str((job.get("agent") or {}).get("planId") or "") != plan_id:
            raise RuntimeError("当前请求已变化，未覆盖结果")
        if request["coverVersionId"] and job.get("currentCoverVersionId") != request["coverVersionId"]:
            raise RuntimeError("封面已变化，未合入旧封面")
        for frozen in request["sessions"]:
            session = runtime.find_edit_session(job, frozen["id"])
            if (int(session.get("revision") or 0) != frozen["revision"]
                    or runtime._edit_session_preview_fingerprint(job, session) != frozen["fingerprint"]):
                raise RuntimeError("时间线或字幕已变化，未提交旧版本")
        if request.get("sourceVersionId"):
            context = runtime.output_download_context(job, request["sourceFilename"])
            if not context or context[1]["id"] != request["sourceVersionId"] or context[0].get("previewOnly") or context[1].get("previewOnly"):
                raise RuntimeError("选定的正式视频已变化，未继续交付")
        return job

    outputs = []
    items = request["sessions"] or ([{"standalone": True}] if request.get("standalone") else [{"sourceFilename": request["sourceFilename"]}])
    for item_index, item in enumerate(items, 1):
        with runtime.jobs_lock:
            job = guard()
            key = str(item.get("id") or item.get("sourceFilename") or "standalone-motion")
            existing = next((v for v in job.get("outputVersions", [])
                             if v.get("automaticPlanId") == plan_id and v.get("automaticItemId") == key
                             and v.get("automaticRequestHash") == request["requestHash"]), None)
            if existing and existing.get("outputs") and all(
                (Path(job["outputDirectory"]) / o["filename"]).is_file()
                and (Path(job["outputDirectory"]) / o["filename"]).stat().st_size > 0
                for o in existing["outputs"]
            ):
                outputs.extend(copy.deepcopy(existing["outputs"]))
                continue
            if item.get("id"):
                session = runtime.find_edit_session(job, item["id"])
                if (int(session.get("revision") or 0) != item["revision"]
                        or runtime._edit_session_preview_fingerprint(job, session) != item["fingerprint"]):
                    raise RuntimeError("时间线已变化，未继续旧版本交付")
        if item.get("id"):
            runtime.run_edit_session_render(job_id, item["id"], item["revision"], item["spec"])
        with runtime.jobs_lock:
            job = guard()
            if item.get("id"):
                session = runtime.find_edit_session(job, item["id"])
                if session.get("status") != "rendered":
                    raise RuntimeError(session.get("renderError") or "正式视频生成失败")
                version = runtime.find_output_version(job, session["renderedVersionId"])
                output = copy.deepcopy(version["outputs"][0])
            elif item.get("standalone"):
                output, version = {"filename": "motion.mp4"}, {"id": ""}
            else:
                output, version, _ = runtime.output_download_context(job, item["sourceFilename"])
                output = copy.deepcopy(output)
            if output.get("previewOnly") or version.get("previewOnly"):
                raise RuntimeError("不能将审核样片当作正式成片")
            parent_id = version["id"]
            cover = next((c for c in job.get("coverVersions", []) if c.get("id") == request["coverVersionId"]), None)
            cover_path = runtime.cover_version_path(job, cover) if cover else None
            source_path = Path(job["outputDirectory"]) / output["filename"]
            # A bounded name avoids accumulating every previous plan/hash
            # during repeated user edits (eventually exceeding NAME_MAX).
            delivery_stem = f"delivery-{plan_id[-12:]}-{request['requestHash'][:12]}-{item_index}"
            work_path = Path(job.get("workDirectory") or job["outputDirectory"]) / "automatic-delivery" / request["requestHash"] / key
        def check_live():
            with runtime.jobs_lock:
                guard()
            return False
        body_offset = intro_offset(output)
        original_cues = copy.deepcopy(output.get("subtitleCues"))
        added_intro_seconds = 0.0
        previous_cover = output.get("coverIntro") or {}
        previous_cover_duration = float(previous_cover.get("duration") or 0) if previous_cover.get("enabled") else 0
        removed_start, removed_duration = cover_interval(output) if request["intro"] else (0.0, 0.0)
        if request["intro"] and previous_cover_duration:
            # Remove only the known leading cover, preserving the selected
            # final master's audio, subtitles and other prior transformations.
            from .cover_delivery import remove_leading_intro
            stripped = source_path.with_name(f"{delivery_stem}-body.mp4")
            remove_leading_intro(source_path, stripped, duration=previous_cover_duration,
                                 ffmpeg=runtime.settings.ffmpeg, ffprobe=runtime.settings.ffprobe,
                                 cancelled=check_live, start=removed_start)
            source_path = stripped
            body_offset = max(0, body_offset - previous_cover_duration)
        if item.get("id"):
            output["deliveryTimeline"] = freeze_timeline(session)
        if request.get("effects"):
            target = source_path.with_name(f"{delivery_stem}-processed.mp4")
            output.update(apply_effects(runtime, None if item.get("standalone") else source_path,
                                        target, request["effects"], work_path, check_live))
            source_path = target
            if (request["effects"].get("motion") or {}).get("intro"):
                added_motion = float((output.get("motionIntro") or {}).get("introDuration") or 0)
                added_intro_seconds += added_motion
                body_offset += added_motion
                if previous_cover_duration and not request["intro"]:
                    output["coverIntro"]["start"] = float(previous_cover.get("start") or 0) + added_motion
        # Media work runs outside the global jobs lock.
        if request["intro"]:
            if not cover_path or not cover_path.is_file():
                raise RuntimeError("本次封面文件不存在，未省略片头")
            target = source_path.with_name(f"{delivery_stem}-intro.mp4")
            media = runtime.render_cover_intro(source_path, cover_path, target,
                duration=request["introDuration"], ffmpeg=runtime.settings.ffmpeg, ffprobe=runtime.settings.ffprobe,
                cancelled=check_live)
            body_offset += float(media["introDuration"])
            added_intro_seconds += float(media["introDuration"])
            output.update({"filename": target.name, "duration": float(media["duration"]),
                           "width": int(media["width"]), "height": int(media["height"]),
                           "hasAudio": bool(media["hasAudio"]),
                           "coverIntro": {"enabled": True, "start": 0, "duration": float(media["introDuration"]),
                                          "coverVersionId": request["coverVersionId"], "sourceFilename": source_path.name}})
        else:
            # A separate final version owns a separate file. This copies only
            # the verified full-quality render above, never a review proxy.
            target = source_path.with_name(f"{delivery_stem}-final.mp4")
            shutil.copy2(source_path, target)
            output["filename"] = target.name
        output["deliveryTimeMap"] = {"schemaVersion": 1, "bodyOffsetSeconds": round(body_offset, 6)}
        if original_cues is not None:
            output["subtitleCues"] = remap_subtitle_cues(original_cues, prepend_seconds=added_intro_seconds,
                                                       removed_start=removed_start, removed_duration=removed_duration)
        if request["intro"] or request.get("effects"):
            output.update(qualityReport={}, qualityGate={}, reviewReport={}, qualityStatus="pending", reviewStatus="pending")
        output["deliveryOperations"] = [*(output.get("deliveryOperations") or []),
                                        {"planId": plan_id, "parentVersionId": parent_id,
                                         "effects": copy.deepcopy(request.get("effects") or {}),
                                         "coverIntro": "replace" if request["intro"] and previous_cover_duration else "prepend" if request["intro"] else "unchanged",
                                         "requestHash": request["requestHash"]}]
        with runtime.jobs_lock:
            job = guard()
            version_id, number = runtime.next_output_version(job)
            output.update({"previewOnly": False, "outputKind": "delivery_master", "planId": plan_id,
                           "versionId": version_id, "versionNumber": number, "versionCreatedAt": runtime.now_iso()})
            version = {"id": version_id, "number": number, "createdAt": runtime.now_iso(),
                       "outputs": [output], "previewOnly": False, "variantKind": "automatic_delivery",
                       "parentVersionId": parent_id, "automaticPlanId": plan_id, "automaticItemId": key,
                       "automaticRequestHash": request["requestHash"]}
            if cover:
                runtime.bind_cover_to_output_version(job, cover, version)
            job.setdefault("outputVersions", []).append(version)
            job["currentOutputVersionId"] = version_id
            outputs.append(copy.deepcopy(output))
            job["outputs"] = copy.deepcopy(outputs)
            job["automaticDelivery"] = {"planId": plan_id, "status": "checking", "outputs": copy.deepcopy(outputs)}
            runtime._sync_output_manifest(job)
            runtime.save_job(job)
    return {"artifact": {"kind": "delivery_master", "jobId": job_id, "outputs": outputs,
                         "output": outputs[0], "message": "正式视频已生成，正在完成最后检查。"}}
