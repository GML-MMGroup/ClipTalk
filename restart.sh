#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PROJECT_ROOT/vlm-highlight.pid"

cd "$PROJECT_ROOT"

LOG_FILE="${HIGHLIGHT_LOG_FILE:-$PROJECT_ROOT/vlm-highlight.log}"
HOST="${HIGHLIGHT_HOST:-$(python3 -c 'from app.config import Settings; print(Settings.from_environment().host)')}"
PORT="${HIGHLIGHT_PORT:-$(python3 -c 'from app.config import Settings; print(Settings.from_environment().port)')}"

is_project_server() {
  local pid="$1" cwd command
  [ -d "/proc/$pid" ] || return 1
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  command="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  [ "$cwd" = "$PROJECT_ROOT" ] && [[ "$command" == *"uvicorn app.main:app"* ]]
}

listener_pid() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null \
      | grep -E ":${PORT}([[:space:]]|$)" \
      | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' \
      | head -n 1
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1
  fi
}

stop_project_server() {
  local pid="$1" pgid
  is_project_server "$pid" || return 0
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  if [ -n "$pgid" ] && [ "$pgid" != "1" ]; then
    kill -TERM -- "-$pgid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  else
    kill -TERM "$pid" 2>/dev/null || true
  fi
  for _ in $(seq 1 25); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.2
  done
  if kill -0 "$pid" 2>/dev/null; then
    if [ -n "$pgid" ] && [ "$pgid" != "1" ]; then
      kill -KILL -- "-$pgid" 2>/dev/null || true
    else
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
}

OLD_PID=""
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(tr -dc '0-9' < "$PID_FILE")"
fi
PORT_PID="$(listener_pid || true)"

# Prefer the listener PID when the pid file is stale. Never terminate a
# process unless its cwd and command line identify this project.
for candidate_pid in "$OLD_PID" "$PORT_PID"; do
  [ -n "$candidate_pid" ] || continue
  if is_project_server "$candidate_pid"; then
    stop_project_server "$candidate_pid"
  fi
done
rm -f "$PID_FILE"

if PORT_PID="$(listener_pid || true)"; then
  if [ -n "$PORT_PID" ]; then
    echo "端口 $PORT 仍被占用，且不是可安全识别的本项目服务（PID=$PORT_PID）" >&2
    exit 1
  fi
fi

setsid nohup env HIGHLIGHT_HOST="$HOST" HIGHLIGHT_PORT="$PORT" \
  python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" \
  </dev/null >"$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

for _ in $(seq 1 50); do
  if ! kill -0 "$NEW_PID" 2>/dev/null; then
    echo "启动失败"
    rm -f "$PID_FILE"
    tail -n 100 "$LOG_FILE"
    exit 1
  fi
  if curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    echo "视觉高光服务已启动：PID=$NEW_PID，远程端口=$PORT（请使用编辑器转发后的浏览器地址，不要打开 0.0.0.0）"
    exit 0
  fi
  sleep 0.2
done

echo "启动超时"
kill -TERM "$NEW_PID" 2>/dev/null || true
rm -f "$PID_FILE"
tail -n 100 "$LOG_FILE"
exit 1
