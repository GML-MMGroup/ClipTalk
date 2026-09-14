#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

CLIPTALK_PYTHON="python3"
if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  CLIPTALK_PYTHON="$PROJECT_ROOT/.venv/bin/python"
fi

for CLIPTALK_ARG in "$@"; do
  if [ "$CLIPTALK_ARG" = "--check" ]; then
    exec "$CLIPTALK_PYTHON" tools/launch.py "$@"
  fi
done

if ! "$CLIPTALK_PYTHON" tools/launch.py --check; then
  if [ -t 0 ] && [ -t 1 ]; then
    printf '检测到安装尚未完成。现在运行统一安装器吗？首次安装会下载数 GB 依赖和模型。[Y/n] '
    read -r CLIPTALK_REPLY
    case "$CLIPTALK_REPLY" in
      n|N|no|NO|No)
        echo "已取消。准备好后运行：python3 tools/setup.py" >&2
        exit 1
        ;;
    esac
    "$CLIPTALK_PYTHON" tools/setup.py
    CLIPTALK_PYTHON="$PROJECT_ROOT/.venv/bin/python"
  else
    echo "安装尚未完成；非交互环境不会自动下载。请先运行：python3 tools/setup.py" >&2
    exit 1
  fi
fi
exec "$CLIPTALK_PYTHON" tools/launch.py "$@"
