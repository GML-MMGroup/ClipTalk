#!/usr/bin/env python3
"""Install into the project, never into system Python or the user's .env."""
from __future__ import annotations

import argparse
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


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


def prerequisites() -> list[str]:
    problems = []
    if not (3, 10) <= sys.version_info[:2] < (3, 12):
        problems.append("需要 Python 3.10 或 3.11，请用对应的 python 命令运行安装脚本。")
    if platform.system() != "Linux":
        problems.append("本机安装目前支持 Linux / WSL2；其他系统请使用 Docker，见 docs/getting-started.md。")
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        problems.append("当前依赖版本需要 x86_64 环境，ARM 设备请使用远程 x86_64 主机。")
    for binary in ("ffmpeg", "ffprobe", "node", "npm", "git"):
        if not shutil.which(binary):
            problems.append(f"未找到 {binary}，请先安装，见 docs/getting-started.md。")
    if shutil.which("node"):
        try:
            version = subprocess.check_output(["node", "--version"], text=True, timeout=5).strip()
            if version.split(".")[0] != "v22":
                problems.append(f"需要 Node.js 22，当前为 {version}。")
        except (OSError, subprocess.SubprocessError):
            problems.append("无法运行 Node.js，请检查安装。")
    if not Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc").is_file():
        problems.append("缺少中文字幕字体；Debian/Ubuntu 可安装 fonts-wqy-zenhei。")
    return problems


def installation_steps(root: Path, profile: str) -> list[tuple[list[str], Path]]:
    python = str(root / ".venv/bin/python")
    steps = []
    if not (root / ".venv").exists():
        steps.append(([sys.executable, "-m", "venv", str(root / ".venv")], root))
    steps.extend([
        ([python, "-m", "pip", "install", "--upgrade", "pip"], root),
        ([python, "-m", "pip", "install", "-r", f"requirements-{profile}.txt"], root),
        (["npm", "ci"], root),
        (["npm", "ci"], root / "agent-service"),
        (["node", "node_modules/playwright/cli.js", "install", "chromium"], root),
        ([python, "tools/install_talknet.py", "--profile", profile], root),
        ([python, "tools/doctor.py", "--profile", "cuda" if profile == "gpu" else "cpu"], root),
    ])
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 ClipTalk 和 TalkNet；不会覆盖 .env")
    parser.add_argument("--profile", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--check", action="store_true", help="只检查系统前置条件，不安装")
    parser.add_argument("--dry-run", action="store_true", help="只列出安装步骤，不写文件或下载")
    args = parser.parse_args()
    profile = automatic_profile() if args.profile == "auto" else args.profile
    print(f"安装环境：{profile}（TalkNet 默认包含在内）")
    if args.dry_run:
        for command, directory in installation_steps(ROOT, profile):
            print(f"[{directory.relative_to(ROOT) or '.'}] {shlex.join(command)}")
        return 0
    problems = prerequisites()
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
        for command, directory in installation_steps(ROOT, profile):
            print(f"正在执行：{shlex.join(command)}", flush=True)
            subprocess.run(command, cwd=directory, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"安装未完成：{error}。修复后可重新运行；已有配置和素材未被覆盖。", file=sys.stderr)
        return 1
    print("安装完成。运行 bash start.sh，然后在页面“设置”中配置模型。")
    print("首次使用识别能力可能下载模型；可提前运行 .venv/bin/python tools/prepare_recognition_models.py --data-root data。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
