"""User-facing capability states, without exposing local paths or model errors."""
from __future__ import annotations

from typing import Any

from .active_speaker import active_speaker_runtime

INSTALL_COMMAND = "python3 tools/setup.py"
REPAIR_COMMAND = "python3 tools/install_talknet.py"


def describe_talknet(runtime: dict[str, Any]) -> dict[str, Any]:
    status, reason = runtime.get("status"), str(runtime.get("reason") or "")
    if status == "disabled":
        state, label = "disabled", "已关闭"
        detail = "人物说话识别被运行配置关闭；需要时将 HIGHLIGHT_ACTIVE_SPEAKER_MODE 改为 primary 并重启。"
    elif reason.startswith("talknet_missing:"):
        state, label = "not_installed", "未安装完整"
        detail = "人物说话识别的环境或模型缺失，请重新运行默认安装命令。"
    elif reason == "talknet_probe_deferred" or status == "deferred":
        state, label = "unchecked", "待检查"
        detail = "已发现安装文件，尚未验证依赖和计算设备。点击“检查能力”确认能否运行。"
    elif status == "ready" and runtime.get("mode") == "shadow":
        state, label = "disabled", "仅对比模式"
        detail = "模型环境可用，但配置为 shadow，结果仅用于对比，不作为剪辑的主要依据。"
    elif status == "ready":
        state, label = "available", "可用"
        detail = "环境和计算设备检查通过；识别结果仍需预览核对。"
        if runtime.get("device") == "cpu":
            detail += " 当前使用 CPU，长视频处理可能较慢。"
    else:
        state, label = "unavailable", "不可用"
        if "CUDA" in reason or "GPU" in reason:
            detail = "指定的 GPU 不可用。请检查驱动和设备配置，或重新安装 CPU 环境。"
        elif "CPU 兼容" in reason:
            detail = "已有 TalkNet 缺少 CPU 兼容适配，请按部署说明更新安装。"
        elif "timed out" in reason.lower():
            detail = "能力检查超时，可能正在载入依赖；请稍后重试。"
        elif "模型" in reason:
            detail = "模型文件缺失或不完整，请重新运行安装脚本。"
        else:
            detail = "依赖或运行环境检查失败，请运行环境检查并按部署说明修复。"
    return {"id": "talknet", "name": "人物说话识别", "status": state, "label": label,
            "detail": detail, "device": runtime.get("device", "auto"),
            "impact": "用于区分人物正在讲话还是仅出现在画面中；不可用时不能保证完整、准确地保留该人物的说话区间。",
            "installCommand": INSTALL_COMMAND, "repairCommand": REPAIR_COMMAND}


def local_capabilities(settings: Any, *, probe: bool = False) -> dict[str, Any]:
    return {"talknet": describe_talknet(active_speaker_runtime(settings, probe=probe, probe_timeout=30))}


def active_speaker_warning(runtime: dict[str, Any]) -> str:
    capability = describe_talknet(runtime)
    if capability["status"] == "available":
        return ""
    return (f"人物说话识别{capability['label']}。本次会使用替代方式查找，可能混入仅出镜或遗漏说话的片段；"
            "生成前请逐段核对。可在设置中检查能力并按安装说明修复。")
