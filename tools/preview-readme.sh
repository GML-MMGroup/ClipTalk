#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${README_PREVIEW_PORT:-5192}"

echo "README preview: http://127.0.0.1:${PORT}/tools/readme-preview.html"
exec python3 -m http.server "$PORT" --bind 0.0.0.0 --directory "$PROJECT_ROOT"
