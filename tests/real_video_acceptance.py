"""Opt-in real-video acceptance runner (not collected by ordinary pytest).

Usage:
  python3 tests/real_video_acceptance.py --video /path/video.mp4 --check
  python3 tests/real_video_acceptance.py --video /path/video.mp4 --run \
    --topic '把介绍小米产品的部分剪出来' --anchor '从讲价格的地方开始'

Uses real HTTP endpoints, configured models, analysis workers and rendering.
Creates NEW jobs, consumes model quota, retains jobs and downloaded review MP4s.
Never uses cached job fixtures or bypasses review gates. Run against a local
development service. Reference-voice identity matching and faces are not tested.
Ground truth for topic/voice relevance still requires human review.
Authentication, when needed: CLIPTALK_TEST_TOKEN environment variable.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse
import uuid
import sys

import httpx


def media_info(path: Path, ffprobe: str) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(result.stdout)


def verify_media(path: Path, ffmpeg: str, ffprobe: str, expected: float | None) -> dict:
    info = media_info(path, ffprobe)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    duration = float(info["format"]["duration"])
    if duration <= 0 or (expected and abs(duration - expected) > max(.3, expected * .01)):
        raise ValueError("Rendered duration does not match the timeline")
    subprocess.run([ffmpeg, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
                   check=True, capture_output=True, timeout=max(120, duration * 5))
    return {"duration": duration, "width": video["width"], "height": video["height"],
            "hasAudio": any(s["codec_type"] == "audio" for s in info["streams"]),
            "fullDecodePassed": True, "file": str(path)}


class Runner:
    def __init__(self, args, directory):
        self.args, self.directory = args, directory
        token = os.environ.get("CLIPTALK_TEST_TOKEN", "")
        self.client = httpx.Client(base_url=args.base_url.rstrip("/"), timeout=180,
                                   headers={"Authorization": f"Bearer {token}"} if token else {})
        if args.in_process:
            self.client.close()
            root = Path(__file__).resolve().parents[1]
            config_root = args.config_root.resolve()
            os.environ["HIGHLIGHT_DATA_ROOT"] = str(directory / "runtime")
            os.environ["FFMPEG_BIN"], os.environ["FFPROBE_BIN"] = args.ffmpeg, args.ffprobe
            os.environ.setdefault("HIGHLIGHT_SPEECH_MODEL_CACHE", str(config_root / "models"))
            sys.path.insert(0, str(root))
            from app import main as application
            from fastapi.testclient import TestClient
            # Resolve credentials in place, without copying configuration files.
            for attr, filename in (("vision_store", "vision-settings.json"),
                                   ("llm_store", "llm-settings.json"),
                                   ("agent_model_store", "agent-settings.json")):
                store = getattr(application, attr)
                setattr(application, attr, type(store)(config_root / filename, store.defaults))
            # No lifespan recovery: only jobs created by this process are run.
            self.client = TestClient(application.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.results = []

    def request(self, method, route, **kwargs):
        response = self.client.request(method, route, **kwargs)
        if response.is_error:
            # Do not include raw server bodies or credential-bearing requests.
            raise RuntimeError(f"HTTP {response.status_code}: {route}")
        return response.json()

    def upload(self, video=None):
        video = video or self.args.video
        with video.open("rb") as stream:
            job = self.request("POST", "/api/jobs", files={"video": (video.name, stream, "video/mp4")},
                               data={"agent_draft": "true", "draft_session_id": uuid.uuid4().hex,
                                     "force_reanalyze": "true"})["job"]
        workspace = self.request("POST", "/api/agent/workspaces", json={"jobId": job["id"],
                                 "title": "真实视频验收 " + uuid.uuid4().hex[:8]})["workspace"]
        return job["id"], workspace["id"]

    def save(self):
        (self.directory / "report.json").write_text(json.dumps({
            "mode": "current_code_asgi_models_and_render" if self.args.in_process else "live_http_models_and_render", "source": str(self.args.video),
            "results": self.results,
            "limitations": ["人脸未测试", "参考声音声纹匹配未测试", "内容准确性及发言完整性需人工审核"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def review_checkpoint(self, name, workspace_id, plan):
        step = next(s for s in plan["steps"] if s.get("status") == "action_required")
        workspace = self.request("GET", f"/api/agent/workspaces/{workspace_id}")["workspace"]
        job_id = workspace["jobId"]
        job = self.request("GET", f"/api/jobs/{job_id}")["job"]
        search = job.get("contentSearch") or {}
        checkpoint = {"planId": plan["id"], "jobId": job_id, "stepId": step["id"],
                      "searchId": search.get("id"), "message": (step.get("result") or {}).get("message"),
                      "matches": [{k: m.get(k) for k in ("id", "start", "end", "transcriptExcerpt", "previewUrl")}
                                  for m in search.get("candidates") or []]}
        (self.directory / f"{name}-checkpoint.json").write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2))
        if step.get("tool") != "review_content_evidence" and (step.get("result") or {}).get("action") != "content_evidence_review":
            return False
        path = self.args.review_input
        if not path or not path.is_file():
            return False
        approved = json.loads(path.read_text())
        if any(approved.get(k) != checkpoint[k] for k in ("planId", "jobId", "stepId", "searchId")):
            return False
        if approved.get("reviewed") is not True:
            return False
        rows = approved.get("matches") or []
        lookup = {m["id"]: m for m in checkpoint["matches"]}
        if not rows or len({m["id"] for m in rows}) != len(rows):
            raise ValueError("Review requires distinct explicit candidate selections")
        for row in rows:
            if row["id"] not in lookup or any(row.get(k) != lookup[row["id"]].get(k) for k in ("start", "end")):
                raise ValueError("Reviewed ranges differ from the current checkpoint")
        prefix = f"/api/jobs/{job_id}/content-search"
        for row in rows:
            self.request("PATCH", prefix + "/boundary", json={"searchId": search["id"],
                         "matchId": row["id"], "start": row["start"], "end": row["end"]})
        ids = [row["id"] for row in rows]
        self.request("PATCH", prefix + "/review-draft", json={"searchId": search["id"],
                     "selectedMatchIds": ids, "orderedMatchIds": ids})
        self.request("POST", f"/api/agent/plans/{plan['id']}/actions/resolve", json={"approved": True,
                     "value": {"context": {"jobId": job_id, "stepId": step["id"]},
                               "selection": {"searchId": search["id"], "matchIds": ids}}})
        return True

    def case(self, name, goal, previous=None, existing=None):
        result = {"case": name, "goal": goal, "status": "running"}
        self.results.append(result)
        self.save()
        plan_id = None
        try:
            job_id, workspace_id = existing or ((previous["jobId"], previous["workspaceId"]) if previous else self.upload(
                self.args.speaker_video if name == "speaker" else None))
            result.update(jobId=job_id, workspaceId=workspace_id)
            ui = {"viewer": {"outputFilename": previous["filename"]}} if previous and previous.get("filename") else {}
            if previous and not ui:
                current = self.request("GET", f"/api/jobs/{job_id}")["job"]
                if current.get("activeEditSessionId") != previous.get("sessionId"):
                    raise ValueError("Active timeline differs from the previous test result")
            reply = self.request("POST", f"/api/agent/workspaces/{workspace_id}/messages", json={
                "text": goal, "clientMessageId": uuid.uuid4().hex,
                "executionMode": "autonomous_review", "uiContext": ui,
            })
            plan = reply.get("plan")
            if not plan:
                result.update(status="needs_review", reason="message_did_not_produce_plan")
                return result
            plan_id = plan["id"]
            result["planId"] = plan_id
            result["tools"] = [s["tool"] for s in plan.get("steps", [])]
            if any(s.get("sideEffect") == "export" for s in plan.get("steps", [])):
                raise ValueError("Unexpected formal export in review-only acceptance")
            required = {"highlight": "analyze_highlights", "topic": "search_content",
                        "anchor": "search_content", "shorter": "propose_timeline_edit",
                        "speaker": "discover_speakers", "voice": "propose_timeline_edit"}[name]
            if required not in result["tools"]:
                raise ValueError(f"Expected workflow tool missing: {required}")
            self.request("POST", f"/api/agent/plans/{plan_id}/confirm", json={"planHash": plan["planHash"]})
            deadline, last_print = time.monotonic() + self.args.timeout, 0
            while time.monotonic() < deadline:
                plan = self.request("GET", f"/api/agent/plans/{plan_id}")["plan"]
                status = plan["status"]
                if status == "action_required":
                    if self.review_checkpoint(name, workspace_id, plan):
                        continue
                    if self.args.review_input:
                        time.sleep(2)
                        continue
                if time.monotonic() - last_print > 30:
                    print(name, status, flush=True)
                    last_print = time.monotonic()
                if status in {"preview_ready", "completed", "failed", "cancelled", "no_result", "action_required"}:
                    break
                time.sleep(2)
            else:
                self.request("POST", f"/api/agent/plans/{plan_id}/cancel")
                result.update(status="timeout", reason="Owned test plan cancelled at deadline")
                return result
            result["planStatus"] = status
            if status not in {"preview_ready", "completed"}:
                result["status"] = "needs_review" if status == "action_required" else status
                result["stepStates"] = [{"tool": s.get("tool"), "status": s.get("status")}
                                        for s in plan.get("steps", [])]
                result["requiredActions"] = [
                    {"tool": s.get("tool"), "action": (s.get("result") or {}).get("action"),
                     "message": (s.get("result") or {}).get("message")}
                    for s in plan.get("steps", []) if s.get("status") == "action_required"
                ]
                return result
            # Only accept an artifact from THIS plan, never a preserved old output.
            previews = []
            for step in plan.get("steps", []):
                artifact = (step.get("result") or {}).get("artifact") or {}
                if artifact.get("kind") == "review_preview_batch":
                    previews.extend(artifact.get("previews") or [])
                elif artifact.get("kind") == "review_preview":
                    previews.append(artifact)
            if not previews:
                raise ValueError("Plan finished without a fresh review video artifact")
            result["media"] = []
            for index, item in enumerate(previews):
                url = item.get("previewUrl") or item.get("videoUrl") or ""
                if not url.startswith("/api/") or url.startswith("//"):
                    raise ValueError("Missing or non-local preview URL")
                destination = self.directory / f"{name}-{index + 1}.mp4"
                with self.client.stream("GET", url) as response:
                    response.raise_for_status()
                    with destination.open("wb") as output:
                        for chunk in response.iter_bytes():
                            output.write(chunk)
                media = verify_media(destination, self.args.ffmpeg, self.args.ffprobe, item.get("duration"))
                case_source = self.args.speaker_video if name == "speaker" and self.args.speaker_video else self.args.video
                case_has_audio = any(s["codec_type"] == "audio" for s in
                                     media_info(case_source, self.args.ffprobe)["streams"])
                if case_has_audio and not media["hasAudio"]:
                    raise ValueError("Source audio was lost")
                result["media"].append(media)
            first = previews[0]
            result["filename"] = first.get("filename") or ""
            result["sessionId"] = first.get("sessionId")
            result["duration"] = result["media"][0]["duration"]
            if name == "shorter":
                target = max(4, round(previous["duration"] * .8))
                if not result["duration"] < previous["duration"] or abs(result["duration"] - target) > max(5, target * .1):
                    raise ValueError("Relative shortening did not meet its target")
            result.update(status="render_passed", semanticVerdict="manual_review_required")
        except Exception as error:
            result.update(status="failed", errorType=type(error).__name__)
            # Record actionable local assertions without dumping model/server responses.
            if isinstance(error, ValueError):
                result["reason"] = str(error)
            if plan_id:
                try:
                    current = self.request("GET", f"/api/agent/plans/{plan_id}")["plan"]
                    if current.get("status") in {"running", "awaiting_confirmation"}:
                        self.request("POST", f"/api/agent/plans/{plan_id}/cancel")
                        result["cancelRequested"] = True
                except Exception:
                    result["cleanupWarning"] = "Could not confirm cancellation; inspect the recorded test plan"
        finally:
            self.save()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:5191")
    parser.add_argument("--topic", default="把介绍产品的部分剪出来")
    parser.add_argument("--anchor", default="从讲价格的地方开始")
    parser.add_argument("--speaker", default="识别视频中的说话人，只保留说话人 B 的发言，生成审核样片")
    parser.add_argument("--speaker-video", type=Path, help="A real multi-speaker video for speaker acceptance")
    parser.add_argument("--review-input", type=Path, help="Explicit reviewed checkpoint JSON; waits until the plan deadline, never auto-approves")
    parser.add_argument("--cases", nargs="+", choices=["highlight", "topic", "shorter", "anchor", "speaker"],
                        default=["highlight", "topic", "shorter", "anchor", "speaker"])
    parser.add_argument("--timeout", type=int, default=1800, help="Per-plan timeout seconds")
    parser.add_argument("--in-process", action="store_true", help="Run current application code in-process with real model/render calls and isolated job storage")
    parser.add_argument("--config-root", type=Path, default=Path("data"), help="Read existing model configuration in place for --in-process")
    parser.add_argument("--output", type=Path, default=Path("local-artifacts"))
    parser.add_argument("--ffmpeg", default="/usr/bin/ffmpeg")
    parser.add_argument("--ffprobe", default="/usr/bin/ffprobe")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Read-only local checks; no upload or model calls")
    group.add_argument("--run", action="store_true", help="Create real jobs and invoke configured models")
    args = parser.parse_args()
    if urlparse(args.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Use a loopback development server")
    if not args.video.is_file() or args.timeout <= 0:
        parser.error("A real video and positive timeout are required")
    if args.speaker_video and not args.speaker_video.is_file():
        parser.error("Speaker video does not exist")
    for binary in (args.ffmpeg, args.ffprobe):
        if not shutil.which(binary):
            parser.error(f"Missing binary: {binary}")
    encoders = subprocess.run([args.ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, check=True).stdout
    if "libx264" not in encoders:
        parser.error("FFmpeg requires libx264")
    source = media_info(args.video, args.ffprobe)
    print("Video:", args.video, "duration:", source["format"]["duration"], flush=True)
    if args.check:
        print("Local checks passed. Server/model readiness is checked during --run.")
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="live-video-acceptance-", dir=args.output)).resolve()
    runner = Runner(args, directory)
    print("Report directory:", directory, flush=True)
    try:
        needs_highlight = bool(set(args.cases) & {"highlight", "shorter", "anchor"})
        highlight = runner.case("highlight", "把最精彩的部分剪成一个高光视频") if needs_highlight else {}
        if "topic" in args.cases:
            runner.case("topic", args.topic)
        if set(args.cases) & {"shorter", "anchor"} and highlight.get("status") == "render_passed" and highlight.get("sessionId"):
            shorter = runner.case("shorter", "再短一点", highlight)
            if shorter.get("status") == "render_passed" and "anchor" in args.cases:
                runner.case("anchor", args.anchor, shorter)
            elif "anchor" in args.cases:
                runner.results.append({"case": "anchor", "status": "blocked", "reason": "Previous revision did not finish"})
        else:
            runner.results.extend({"case": name, "status": "blocked", "reason": "No referenceable highlight preview"}
                                  for name in ("shorter", "anchor") if name in args.cases)
        if "speaker" in args.cases:
            runner.case("speaker", args.speaker)
        runner.save()
    finally:
        runner.client.close()
    print("Results:", directory / "report.json")
    return 0 if all(r["status"] == "render_passed" for r in runner.results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
