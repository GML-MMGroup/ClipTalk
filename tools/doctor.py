#!/usr/bin/env python3
"""Check whether the local ClipTalk runtime is ready without changing it."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.security import SecurityConfigurationError  # noqa: E402


BASE_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "httpx": "httpx",
    "Python Multipart": "multipart",
    "Pydantic": "pydantic",
    "Starlette": "starlette",
    "Cryptography": "cryptography",
    "Pillow": "PIL",
    "OpenCV": "cv2",
}
AUDIO_MODULES = {
    "NumPy": "numpy",
    "SciPy": "scipy",
    "scikit-learn": "sklearn",
    "PyTorch": "torch",
    "Torchaudio": "torchaudio",
    "FunASR": "funasr",
    "Faster Whisper": "faster_whisper",
    "CTranslate2": "ctranslate2",
}
RECOGNITION_MODULES = {
    "Transformers": "transformers",
    "Safetensors": "safetensors",
    "SentencePiece": "sentencepiece",
    "PaddlePaddle": "paddle",
    "PaddleOCR": "paddleocr",
}

SUBTITLE_FONT = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")


def _result(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _binary_version(binary: str) -> tuple[bool, str]:
    resolved = binary if Path(binary).is_file() else shutil.which(binary)
    if not resolved:
        return False, f"未找到 {binary}"
    try:
        completed = subprocess.run(
            [resolved, "-version"], capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"无法执行：{error}"
    first_line = (completed.stdout or completed.stderr or "").splitlines()
    detail = first_line[0].strip() if first_line else str(resolved)
    return completed.returncode == 0, detail[:180]


def _writable_location(path: Path) -> tuple[bool, str]:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    writable = candidate.exists() and candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)
    return writable, f"目标 {path}；检查位置 {candidate}"


def _module_checks(modules: dict[str, str], *, required: bool) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    missing_status = "blocker" if required else "warning"
    for label, module in modules.items():
        available = importlib.util.find_spec(module) is not None
        results.append(_result(label, "ok" if available else missing_status, "已安装" if available else f"缺少 Python 模块 {module}"))
    return results


def inspect_environment(profile: str = "visual") -> dict[str, Any]:
    settings = Settings.from_environment()
    checks: list[dict[str, str]] = []

    python_ready = sys.version_info >= (3, 10) and sys.version_info < (3, 12)
    checks.append(_result(
        "Python", "ok" if python_ready else "blocker",
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}；支持 3.10–3.11",
    ))
    for label, binary in (("FFmpeg", settings.ffmpeg), ("FFprobe", settings.ffprobe)):
        ready, detail = _binary_version(binary)
        checks.append(_result(label, "ok" if ready else "blocker", detail))
    checks.append(_result(
        "中文字幕字体", "ok" if SUBTITLE_FONT.is_file() else "blocker",
        str(SUBTITLE_FONT) if SUBTITLE_FONT.is_file() else f"缺少 {SUBTITLE_FONT}（Debian/Ubuntu 包：fonts-wqy-zenhei）",
    ))

    writable, detail = _writable_location(settings.data_root)
    checks.append(_result("数据目录", "ok" if writable else "blocker", detail))
    try:
        settings.validate_deployment_security()
    except SecurityConfigurationError as error:
        checks.append(_result("部署访问控制", "blocker", str(error)))
    else:
        token_state = "已配置访问令牌" if settings.access_token else "仅允许本机访问，无需令牌"
        checks.append(_result("部署访问控制", "ok", f"监听 {settings.host}:{settings.port}；{token_state}"))

    checks.extend(_module_checks(BASE_MODULES, required=True))
    if profile in {"cpu", "cuda"}:
        checks.extend(_module_checks(AUDIO_MODULES, required=True))
        checks.extend(_module_checks(RECOGNITION_MODULES, required=True))

    vision_file = settings.data_root / "vision-settings.json"
    vision_ready = bool(settings.vision_api_key and settings.vision_model and settings.vision_base_url) or vision_file.is_file()
    checks.append(_result(
        "视觉模型配置", "ok" if vision_ready else "warning",
        "已配置，可创建分析任务" if vision_ready else "服务可启动，但需要在界面或 .env 中配置视觉模型",
    ))

    if profile == "cuda":
        cuda_ready = False
        cuda_detail = "PyTorch 未安装或 CUDA 不可用"
        if importlib.util.find_spec("torch") is not None:
            try:
                import torch

                cuda_ready = bool(torch.cuda.is_available())
                cuda_detail = (
                    f"CUDA 可用；设备数 {torch.cuda.device_count()}"
                    if cuda_ready else f"PyTorch {torch.__version__} 未检测到 CUDA"
                )
            except Exception as error:  # pragma: no cover - depends on host CUDA runtime
                cuda_detail = f"CUDA 探测失败：{str(error)[:140]}"
        checks.append(_result("NVIDIA CUDA", "ok" if cuda_ready else "blocker", cuda_detail))
        paddle_cuda_ready = False
        paddle_cuda_detail = "PaddlePaddle 未安装或不是 CUDA 构建"
        if importlib.util.find_spec("paddle") is not None:
            try:
                import paddle

                paddle_cuda_ready = bool(paddle.device.is_compiled_with_cuda())
                paddle_cuda_detail = (
                    f"PaddlePaddle {paddle.__version__} CUDA 构建"
                    if paddle_cuda_ready else f"PaddlePaddle {paddle.__version__} 是 CPU 构建"
                )
            except Exception as error:  # pragma: no cover - depends on Paddle runtime
                paddle_cuda_detail = f"Paddle CUDA 探测失败：{str(error)[:140]}"
        checks.append(_result(
            "PaddlePaddle CUDA", "ok" if paddle_cuda_ready else "blocker", paddle_cuda_detail,
        ))

    blockers = sum(item["status"] == "blocker" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    return {
        "profile": profile,
        "ready": blockers == 0,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="只读检查 ClipTalk 本机运行环境")
    parser.add_argument("--profile", choices=("visual", "cpu", "cuda"), default="visual")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true", help="存在警告时也返回非零状态")
    args = parser.parse_args()

    report = inspect_environment(args.profile)
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        icons = {"ok": "✓", "warning": "!", "blocker": "×"}
        print(f"ClipTalk 环境检查 · {args.profile}")
        for item in report["checks"]:
            print(f"{icons[item['status']]} {item['name']}：{item['detail']}")
        print(f"结果：{report['blockers']} 个阻断项，{report['warnings']} 个提醒")
    return 1 if report["blockers"] or (args.strict and report["warnings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
