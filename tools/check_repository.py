#!/usr/bin/env python3
"""Fail fast when a ClipTalk commit contains local data or incomplete config."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import subprocess
import sys


PROTECTED_FILES = ("README.md", "README_zh.md", "LICENSE")
FORBIDDEN_PREFIXES = (
    "data/", "tmp/", "test-results/", "playwright-report/", "node_modules/",
    ".venv/", "venv/", "__pycache__/", ".pytest_cache/",
)
FORBIDDEN_SUFFIXES = (
    ".log", ".pid", ".sqlite", ".sqlite3", ".db", ".mp4", ".mov", ".mkv",
    ".avi", ".webm", ".orig", ".rej",
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{24,}\b"),
    re.compile(r"\bAKLT[A-Za-z0-9_-]{16,}\b"),
)
MACHINE_PATH_PATTERNS = (
    re.compile(r"/data/[^/\s]+/VideoPilot"),
    re.compile(r"/home/[^/\s]+/VideoPilot"),
)
MAX_TRACKED_BYTES = 50 * 1024 * 1024


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=check,
    )


def tracked_files(root: Path) -> list[str]:
    completed = _git(root, "ls-files", "-z")
    return [value for value in completed.stdout.split("\0") if value]


def environment_names_from_python(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        function = node.func
        if not isinstance(function, ast.Attribute) or function.attr != "get":
            continue
        owner = function.value
        if not (
            isinstance(owner, ast.Attribute)
            and owner.attr == "environ"
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "os"
        ):
            continue
        value = node.args[0].value
        if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", value):
            names.add(value)
    return names


def environment_names_from_shell(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]+)(?=[:}?])", text))
    return {name for name in names if name.startswith((
        "HIGHLIGHT_", "VISION_", "ARK_", "LLM_", "ANTHROPIC_", "CONTENT_SEARCH_",
    ))}


def environment_names_from_example(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", raw_line.strip())
        if match:
            names.add(match.group(1))
    return names


def configuration_errors(root: Path) -> list[str]:
    referenced = environment_names_from_python(root / "app" / "config.py")
    referenced.update(environment_names_from_shell(root / "start.sh"))
    referenced.update(environment_names_from_shell(root / "restart.sh"))
    documented = environment_names_from_example(root / ".env.example")
    return [f".env.example 缺少配置项：{name}" for name in sorted(referenced - documented)]


def repository_errors(root: Path, *, compare_ref: str = "") -> list[str]:
    errors = configuration_errors(root)
    files = tracked_files(root)
    for relative in files:
        path = Path(relative)
        lowered = relative.lower()
        if relative == ".env" or (relative.startswith(".env.") and relative != ".env.example"):
            errors.append(f"禁止提交真实环境文件：{relative}")
        if any(relative.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            errors.append(f"禁止提交运行目录：{relative}")
        if lowered.endswith(FORBIDDEN_SUFFIXES):
            errors.append(f"禁止提交运行产物或媒体：{relative}")
        if len(path.parts) == 1 and path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            errors.append(f"根目录截图必须移入 photo/ 或 assets/：{relative}")
        absolute = root / path
        if not absolute.is_file():
            continue
        if absolute.stat().st_size > MAX_TRACKED_BYTES:
            errors.append(f"文件超过 50 MiB：{relative}")
            continue
        if absolute.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2"}:
            continue
        try:
            text = absolute.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            errors.append(f"疑似包含真实密钥：{relative}")
        if any(pattern.search(text) for pattern in MACHINE_PATH_PATTERNS):
            errors.append(f"包含本机绝对路径：{relative}")

    if compare_ref:
        for protected in PROTECTED_FILES:
            changed = _git(root, "diff", "--quiet", compare_ref, "--", protected, check=False)
            if changed.returncode != 0:
                errors.append(f"受保护文件不得修改：{protected}")
    return list(dict.fromkeys(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 ClipTalk Git 提交边界")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--compare-ref", default="", help="用于保护 README 和 LICENSE 的 Git 基线")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        errors = repository_errors(root, compare_ref=args.compare_ref)
    except (OSError, subprocess.CalledProcessError, SyntaxError) as error:
        print(f"仓库检查无法完成：{error}", file=sys.stderr)
        return 2
    if errors:
        print("仓库检查失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("仓库检查通过：配置模板完整，未发现本机数据、密钥模式或超大文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
