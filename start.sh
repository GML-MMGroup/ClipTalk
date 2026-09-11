#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

CLIPTALK_PYTHON="python3"
if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  CLIPTALK_PYTHON="$PROJECT_ROOT/.venv/bin/python"
fi
exec "$CLIPTALK_PYTHON" tools/launch.py "$@"
