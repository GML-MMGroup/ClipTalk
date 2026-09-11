#!/usr/bin/env python3
"""Prepare the default TalkNet capability without embedding machine paths."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.config import Settings  # noqa: E402

REPOSITORY = "https://github.com/TaoRuijie/TalkNet-ASD.git"
REVISION = "6d6821479af485e251c4991487e40573b42181b4"
TALKSET_ID = "1AbN9fCf9IexMxEKXLQY2KYBlb-IhSEea"
S3FD_ID = "1KafnHz7ccT-3IyddBsL5yi2xGtxAKypt"
ADAPTER_REVISION = "cliptalk-device-v1"


def adapted_source(name: str, source: str) -> str:
    """Small, checked patches to upstream inference, leaving its license intact."""
    if ADAPTER_REVISION in source:
        return source
    if name not in {"demoTalkNet.py", "talkNet.py"} or ".cuda()" not in source:
        raise ValueError(f"{name} 与已验证的上游版本不同，未修改文件。")
    source = f"# {ADAPTER_REVISION}\nimport os\nCLIPTALK_DEVICE = os.environ.get('CLIPTALK_TALKNET_DEVICE', 'cuda')\n" + source
    source = source.replace(".cuda()", ".to(CLIPTALK_DEVICE)")
    if name == "talkNet.py":
        if "torch.load(path)" not in source:
            raise ValueError("未找到模型载入位置，未修改文件。")
        source = source.replace("torch.load(path)", "torch.load(path, map_location=CLIPTALK_DEVICE)")
    else:
        if "S3FD(device='cuda')" not in source:
            raise ValueError("未找到人脸检测设备配置，未修改文件。")
        source = source.replace("S3FD(device='cuda')", "S3FD(device=CLIPTALK_DEVICE)")
        if "--noVisualization" not in source:
            source = source.replace("args = parser.parse_args()", "parser.add_argument('--noVisualization', action='store_true')\nargs = parser.parse_args()")
            target = "\t\tvisualization(vidTracks, scores, args)"
            if target not in source:
                raise ValueError("未找到结果可视化位置，未修改文件。")
            source = source.replace(target, "\t\tif not args.noVisualization:\n\t\t\tvisualization(vidTracks, scores, args)")
    ast.parse(source)
    return source


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print(shlex.join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def download_weight(python: str, file_id: str, target: Path) -> None:
    if target.is_file() and target.stat().st_size >= 1024 * 1024:
        return
    if target.exists():
        raise RuntimeError(f"模型文件不完整：{target}。请移走该文件后重试，安装器不会覆盖它。")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".download")
    run([python, "-m", "gdown", file_id, "-O", str(temporary)])
    if not temporary.is_file() or temporary.stat().st_size < 1024 * 1024:
        raise RuntimeError("模型下载不完整，请检查网络后重试。")
    with temporary.open("rb") as handle:
        if b"<html" in handle.read(512).lower():
            raise RuntimeError("下载到网页而非模型，请检查网络后重试。")
    temporary.replace(target)


def prepare_repository(repository: Path) -> None:
    if not repository.exists():
        # Publish only after clone and checkout succeed. Interrupted downloads
        # remain in their own staging directory and do not block a fresh retry.
        staging = Path(tempfile.mkdtemp(prefix=".repository-install-", dir=repository.parent))
        checkout = staging / "repository"
        try:
            run(["git", "clone", "--no-checkout", REPOSITORY, str(checkout)])
            run(["git", "checkout", "--detach", REVISION], cwd=checkout)
            checkout.rename(repository)
            staging.rmdir()
        except (OSError, subprocess.SubprocessError):
            print(f"未完成的代码下载保留在 {staging}，重试会使用新目录。", file=sys.stderr)
            raise
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    if current != REVISION:
        raise RuntimeError("已有 TalkNet 代码版本不同；保留原目录，请先检查后再安装。")


def main() -> int:
    parser = argparse.ArgumentParser(description="安装/修复 TalkNet；保留现有 .env 和手动安装目录")
    parser.add_argument("--profile", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    from tools.setup import automatic_profile
    profile = automatic_profile() if args.profile == "auto" else args.profile
    settings = Settings.from_environment()
    data_root = (args.data_root or settings.data_root).resolve()
    directory = data_root / "models/talknet"
    python = str(directory / "venv/bin/python")
    repository = directory / "repository"
    checkpoint = directory / "pretrain_TalkSet.model"
    print("默认安装人物说话识别：TalkNet 代码、隔离环境、TalkSet 和 S3FD 权重。")
    print("第三方代码许可证与模型来源见 docs/deployment.md；首次安装需要网络和磁盘空间。")
    if args.dry_run:
        print(f"位置：{directory}\n代码：{REPOSITORY}@{REVISION}\n计算环境：{profile}")
        print("已安装的环境不覆盖；缺失文件下载完成并通过检查后才报告成功。")
        return 0
    if any(character.isspace() for character in str(directory)):
        print("TalkNet 上游命令暂不支持带空白的安装路径；请将项目/数据目录放到无空格路径。", file=sys.stderr)
        return 1
    try:
        directory.mkdir(parents=True, exist_ok=True)
        managed = directory / "install.json"
        if repository.exists() and not managed.is_file():
            # A manually configured deployment belongs to its owner.
            print("检测到手动安装的 TalkNet，保留现有环境，仅验证。", flush=True)
            run([python if args.data_root else settings.talknet_worker_python,
                 settings.talknet_worker_script, "--healthcheck", "--verify-model",
                 "--repository", str(repository) if args.data_root else settings.talknet_repository,
                 "--checkpoint", str(checkpoint) if args.data_root else settings.talknet_checkpoint,
                 "--device", "auto" if args.data_root else settings.talknet_device])
            return 0
        if not managed.exists():
            managed.write_text(json.dumps({"revision": REVISION, "adapter": ADAPTER_REVISION, "status": "installing"}), encoding="utf-8")
        prepare_repository(repository)
        changes = {name: adapted_source(name, (repository / name).read_text()) for name in ("demoTalkNet.py", "talkNet.py")}
        for name, content in changes.items():
            (repository / name).write_text(content, encoding="utf-8")
        if not (directory / "venv").exists():
            run([sys.executable, "-m", "venv", str(directory / "venv")])
        if not Path(python).is_file():
            raise RuntimeError("TalkNet 虚拟环境不完整，请检查 venv 目录后重试。")
        run([python, "-m", "pip", "install", "--upgrade", "pip"])
        index = "https://download.pytorch.org/whl/" + ("cu121" if profile == "gpu" else "cpu")
        run([python, "-m", "pip", "install", "torch==2.2.0", "torchaudio==2.2.0", "torchvision==0.17.0", "--index-url", index])
        run([python, "-m", "pip", "install", "-r", str(ROOT / "tools/requirements-talknet.txt")])
        download_weight(python, TALKSET_ID, checkpoint)
        download_weight(python, S3FD_ID, repository / "model/faceDetector/s3fd/sfd_face.pth")
        run([python, str(ROOT / "tools/talknet_worker.py"), "--healthcheck", "--repository", str(repository),
             "--checkpoint", str(checkpoint), "--device", "auto", "--verify-model"])
        managed.write_text(json.dumps({"revision": REVISION, "adapter": ADAPTER_REVISION, "status": "installed",
                                      "checkpointSha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest()}), encoding="utf-8")
        print("TalkNet 已安装并通过模型载入检查。默认目录会自动发现，无需复制路径。")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"TalkNet 安装未完成：{error}。修复网络或依赖后重新运行本命令。", file=sys.stderr)
        return 1
    except RuntimeError as error:
        print(f"TalkNet 安装未完成：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
