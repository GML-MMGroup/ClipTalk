#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

HOST="${HIGHLIGHT_HOST:-$(python3 -c 'from app.config import Settings; print(Settings.from_environment().host)')}"
PORT="${HIGHLIGHT_PORT:-$(python3 -c 'from app.config import Settings; print(Settings.from_environment().port)')}"

exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT"
