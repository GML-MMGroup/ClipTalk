#!/usr/bin/env python3
"""Install into the project, never into system Python or the user's .env."""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.config import load_env  # noqa: E402

BUNDLED_SUBTITLE_FONT = ROOT / "fonts/SourceHanSansSC-Bold.otf"
SYSTEM_SUBTITLE_FONT = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
MINIMUM_FREE_GIB = {"cpu": 6, "gpu": 10}
RECOMMENDED_FREE_GIB = {"cpu": 10, "gpu": 16}


def automatic_profile() -> str:
    """Prefer the CUDA 12.1 profile only when a suitable NVIDIA driver is visible."""
    if not shutil.which("nvidia-smi"):
        return "cpu"
    try:
        versions = subprocess.check_output(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True, timeout=5)
        return "gpu" if any(tuple(int(part) for part in version.strip().split(".")[:2]) >= (525, 60)
                            for version in versions.splitlines()) else "cpu"
    except (OSError, ValueError, subprocess.SubprocessError):
        return "cpu"


def _configured_binary(environment_name: str, fallback: str) -> str:
    configured = os.environ.get(environment_name, "").strip()
    return shutil.which(configured or fallback) or configured or fallback


def _ffmpeg_capability(binary: str, flag: str, name: str) -> bool:
    try:
        completed = subprocess.run(
            [binary, "-hide_banner", flag], capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and name in (completed.stdout + completed.stderr)


def prerequisites(profile: str = "cpu") -> list[str]:
    problems = []
    ffmpeg = _configured_binary("FFMPEG_BIN", "ffmpeg")
    ffprobe = _configured_binary("FFPROBE_BIN", "ffprobe")
    if not (3, 10) <= sys.version_info[:2] < (3, 12):
        problems.append("需要 Python 3.10 或 3.11，请用对应的 python 命令运行安装脚本。")
    if platform.system() != "Linux":
        problems.append("本机安装目前支持 Linux / WSL2；其他系统请使用 Docker，见 docs/getting-started.md。")
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        problems.append("当前依赖版本需要 x86_64 环境，ARM 设备请使用远程 x86_64 主机。")
    for binary in ("node", "npm", "git"):
        if not shutil.which(binary):
            problems.append(f"未找到 {binary}，请先安装，见 docs/getting-started.md。")
    for label, binary in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        if not shutil.which(binary) and not Path(binary).is_file():
            problems.append(f"未找到 {label}，请先安装，见 docs/getting-started.md。")
    if shutil.which("node"):
        try:
            version = subprocess.check_output(["node", "--version"], text=True, timeout=5).strip()
            if version.split(".")[0] != "v22":
                problems.append(f"需要 Node.js 22，当前为 {version}。")
        except (OSError, subprocess.SubprocessError):
            problems.append("无法运行 Node.js，请检查安装。")
    if importlib.util.find_spec("venv") is None or importlib.util.find_spec("ensurepip") is None:
        problems.append("当前 Python 缺少 venv/ensurepip；Debian/Ubuntu 可安装 python3-venv。")
    if (shutil.which(ffmpeg) or Path(ffmpeg).is_file()) and not _ffmpeg_capability(ffmpeg, "-encoders", "libx264"):
        problems.append(f"当前 FFmpeg（{ffmpeg}）不包含 libx264 编码器，无法生成 H.264 成片。")
    if (shutil.which(ffmpeg) or Path(ffmpeg).is_file()) and not _ffmpeg_capability(ffmpeg, "-filters", "drawtext"):
        problems.append(f"当前 FFmpeg（{ffmpeg}）不包含 drawtext 滤镜，无法渲染字幕。")
    if not (BUNDLED_SUBTITLE_FONT.is_file() or SYSTEM_SUBTITLE_FONT.is_file()):
        problems.append("缺少中文字幕字体，且仓库内置 SourceHanSansSC-Bold.otf 不完整。")
    try:
        free_gib = shutil.disk_usage(ROOT).free / 1024**3
        if free_gib < MINIMUM_FREE_GIB[profile]:
            problems.append(
                f"磁盘空间不足：可用 {free_gib:.1f} GiB，{profile.upper()} 安装至少需要 "
                f"{MINIMUM_FREE_GIB[profile]} GiB。"
            )
    except OSError:
        problems.append("无法读取项目目录的可用磁盘空间。")
    return problems


def prerequisite_warnings(profile: str) -> list[str]:
    warnings = []
    try:
        free_gib = shutil.disk_usage(ROOT).free / 1024**3
        if MINIMUM_FREE_GIB[profile] <= free_gib < RECOMMENDED_FREE_GIB[profile]:
            warnings.append(
                f"可用空间 {free_gib:.1f} GiB；建议为 {profile.upper()} 安装预留至少 "
                f"{RECOMMENDED_FREE_GIB[profile]} GiB，后续模型还会占用更多空间。"
            )
    except OSError:
        pass
    return warnings


def installation_steps(root: Path, profile: str) -> list[tuple[list[str], Path]]:
    python = str(root / ".venv/bin/python")
    steps = []
    if not (root / ".venv").exists():
        steps.append(([sys.executable, "-m", "venv", str(root / ".venv")], root))
    steps.extend([
        ([python, "-m", "pip", "install", "--upgrade", "pip"], root),
        ([python, "-m", "pip", "install", "-r", f"requirements-{profile}.txt"], root),
        (["npm", "ci", "--omit=dev", "--ignore-scripts"], root),
        (["npm", "ci", "--omit=dev", "--ignore-scripts"], root / "agent-service"),
        (["node", "node_modules/playwright/cli.js", "install", "chromium"], root),
        ([python, "tools/install_talknet.py", "--profile", profile], root),
        ([python, "tools/doctor.py", "--profile", "cuda" if profile == "gpu" else "cpu"], root),
    ])
    return steps


def step_label(command: list[str], directory: Path) -> str:
    joined = " ".join(command)
    if " -m venv " in f" {joined} ":
        return "创建 Python 隔离环境"
    if "requirements-" in joined:
        return "安装 Python 运行依赖"
    if command[:2] == ["npm", "ci"] and directory == ROOT:
        return "安装网页运行依赖"
    if command[:2] == ["npm", "ci"]:
        return "安装 AI 助手运行依赖"
    if "playwright" in joined:
        return "安装本地动效渲染浏览器"
    if "install_talknet.py" in joined:
        return "安装 TalkNet 人物说话识别"
    if "doctor.py" in joined:
        return "执行最终环境检查"
    return "准备运行环境"


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="安装 ClipTalk 和 TalkNet；不会覆盖 .env")
    parser.add_argument("--profile", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--check", action="store_true", help="只检查系统前置条件，不安装")
    parser.add_argument("--dry-run", action="store_true", help="只列出安装步骤，不写文件或下载")
    args = parser.parse_args()
    profile = automatic_profile() if args.profile == "auto" else args.profile
    print(f"安装环境：{profile}（TalkNet 默认包含在内）", flush=True)
    if args.dry_run:
        for command, directory in installation_steps(ROOT, profile):
            print(f"[{directory.relative_to(ROOT) or '.'}] {shlex.join(command)}")
        return 0
    problems = prerequisites(profile)
    for warning in prerequisite_warnings(profile):
        print(f"! {warning}", file=sys.stderr)
    for problem in problems:
        print(f"× {problem}", file=sys.stderr)
    if problems:
        return 1
    if args.check:
        print("系统前置条件已满足。尚未检查或安装 Python/Node 项目依赖。")
        return 0
    if (ROOT / ".venv").exists() and not (ROOT / ".venv/bin/python").is_file():
        print("已有 .venv 不是可用的 Python 环境；请先检查该目录，安装器不会覆盖它。", file=sys.stderr)
        return 1
    try:
        steps = installation_steps(ROOT, profile)
        for index, (command, directory) in enumerate(steps, start=1):
            label = step_label(command, directory)
            print(f"[{index}/{len(steps)}] {label}", flush=True)
            print(f"正在执行：{shlex.join(command)}", flush=True)
            subprocess.run(command, cwd=directory, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        recovery = "python3 tools/setup.py"
        if profile == "gpu":
            recovery += " --profile gpu（若显卡环境不兼容，可改用 --profile cpu）"
        print(
            f"安装未完成：{error}。修复网络或上方阶段提示后运行 {recovery}；"
            "已有配置、已下载依赖和素材不会被删除。",
            file=sys.stderr,
        )
        return 1
    print("安装完成。运行 bash start.sh，然后在页面“设置”中配置模型。")
    print("首次使用识别能力可能下载模型；可提前运行 .venv/bin/python tools/prepare_recognition_models.py --data-root data。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
