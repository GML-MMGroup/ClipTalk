from __future__ import annotations

import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


@lru_cache(maxsize=8)
def render_runtime_ready(ffmpeg: str, ffprobe: str) -> bool:
    for binary in (ffmpeg, ffprobe):
        try:
            completed = subprocess.run(
                [binary, "-version"], capture_output=True, timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if completed.returncode != 0:
            return False
    for flag, feature in (("-encoders", "libx264"), ("-filters", "drawtext")):
        try:
            completed = subprocess.run(
                [ffmpeg, "-hide_banner", flag], capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if completed.returncode != 0 or feature not in (completed.stdout + completed.stderr):
            return False
    return True


def model_fingerprint(model: dict[str, Any]) -> str:
    identity = {
        "provider": str(model.get("provider") or ""),
        "protocol": str(model.get("protocol") or ""),
        "model": str(model.get("model") or ""),
        "baseUrl": str(model.get("baseUrl") or "").rstrip("/"),
        "thinkingType": str(model.get("thinkingType") or ""),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()


def save_agent_probe(path: Path, model: dict[str, Any], result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "fingerprint": model_fingerprint(model),
        "toolCalling": bool(result.get("toolCalling")),
        "piVersion": str(result.get("piVersion") or ""),
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=".agent-probe-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def agent_probe_ready(path: Path, model: dict[str, Any]) -> bool:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return bool(record.get("toolCalling")) and record.get("fingerprint") == model_fingerprint(model)


def build_setup_status(
    *, health: dict[str, Any], agent_model: dict[str, Any], probe_ready: bool,
    runtime_ready: bool | None = None,
) -> dict[str, Any]:
    runtime_ready = bool(health.get("ffmpeg") and health.get("ffprobe")) if runtime_ready is None else runtime_ready
    vision_ready = bool(health.get("visionConfigured") or health.get("arkConfigured"))
    planner_ready = bool(health.get("llmConfigured"))
    agent_configured = all(str(agent_model.get(key) or "").strip() for key in ("apiKey", "model", "baseUrl"))
    talknet = ((health.get("localCapabilities") or {}).get("talknet") or {})

    def step(identifier: str, title: str, ready: bool, detail: str, action: str, *, optional: bool = False) -> dict[str, Any]:
        return {
            "id": identifier,
            "title": title,
            "status": "ready" if ready else "optional" if optional else "required",
            "detail": detail,
            "action": action,
        }

    steps = [
        step("runtime", "本地运行环境", runtime_ready,
             "FFmpeg 与 FFprobe 已就绪" if runtime_ready else "视频处理工具尚未就绪，请运行安装检查", "runtime"),
        step("vision", "视觉分析模型", vision_ready,
             "视觉模型已配置" if vision_ready else "请验证并保存支持图片理解的模型", "vision"),
        step("planner", "剪辑规划模型", planner_ready,
             "剪辑规划模型已配置" if planner_ready else "请选择复用视觉模型或配置独立文本模型", "llm"),
        step("agent", "Agent 执行模型", agent_configured and probe_ready,
             "Tool Calling 已验证" if agent_configured and probe_ready else
             "模型已配置，仍需验证 Tool Calling" if agent_configured else "请配置可调用工具的 Agent 模型", "agent"),
        step("local_models", "人物说话识别", talknet.get("status") == "available",
             str(talknet.get("detail") or "尚未检查；不影响基础剪辑"), "runtime", optional=True),
    ]
    can_create = runtime_ready and vision_ready and planner_ready
    can_use_agent = can_create and agent_configured and probe_ready
    return {
        "complete": can_use_agent,
        "canCreateTask": can_create,
        "canUseAgent": can_use_agent,
        "steps": steps,
    }
