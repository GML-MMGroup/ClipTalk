#!/usr/bin/env python3
"""Foreground supervisor for the web and optional local Agent service."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.config import Settings  # noqa: E402


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=.5):
            return True
    except OSError:
        return False


def service_ready(url: str, service: str) -> bool:
    try:
        with urlopen(url, timeout=1) as response:
            return json.load(response).get("service") == service
    except (OSError, ValueError, URLError):
        return False


def agent_matches_credentials(url: str, settings: Settings) -> bool:
    token = os.environ.get("CLIPTALK_AGENT_SERVICE_TOKEN", "").strip()
    if not token:
        try:
            token = (settings.data_root / "agent/service-token").read_text().strip()
        except OSError:
            return False
    if len(token) < 32:
        return False
    request = Request(url + "/v1/operations/get", data=b'{"operationId":"cliptalk-launch-readiness"}',
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urlopen(request, timeout=2) as response:
            return response.status == 200
    except HTTPError as error:
        return error.code == 404
    except (OSError, URLError):
        return False


def stop_owned(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        # Only the process group created by this launcher is in scope.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="一起启动网页和 AI 助手；Ctrl+C 停止本次启动的服务")
    parser.add_argument("--external-agent", action="store_true", help="不启动本地助手，使用已配置的独立服务")
    parser.add_argument("--check", action="store_true", help="只检查运行环境，不启动服务")
    args = parser.parse_args()
    from tools.doctor import inspect_environment
    report = inspect_environment("visual")
    for check in report["checks"]:
        if check["status"] != "ok":
            print(f"{check['name']}：{check['detail']}", flush=True)
    if not report["ready"]:
        print("启动条件不满足，请先运行 python3 tools/setup.py。", file=sys.stderr)
        return 1
    if args.check:
        return 0
    settings = Settings.from_environment()
    probe_host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
    if port_open(probe_host, settings.port):
        print(f"端口 {settings.port} 已被使用；不会停止或覆盖已有服务。", file=sys.stderr)
        return 1
    owned: list[subprocess.Popen] = []
    stopping = False

    def request_stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        agent_url = settings.agent_service_url.rstrip("/")
        parsed = urlparse(agent_url)
        managed = not args.external_agent and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"} and parsed.path in {"", "/"}
        if managed:
            port = parsed.port or 80
            if port_open(parsed.hostname, port):
                if not (service_ready(agent_url + "/health", "cliptalk-agent-service") and agent_matches_credentials(agent_url, settings)):
                    raise RuntimeError(f"助手端口 {port} 被其他服务占用或凭据不匹配；请更换端口，已有服务不会被终止。")
                print("复用当前项目已运行的 AI 助手服务。", flush=True)
            else:
                if not (ROOT / "agent-service/node_modules/@earendil-works/pi-coding-agent").is_dir():
                    raise RuntimeError("缺少 AI 助手依赖，请先运行 python3 tools/setup.py。")
                environment = dict(os.environ, HIGHLIGHT_DATA_ROOT=str(settings.data_root),
                                   CLIPTALK_AGENT_HOST="127.0.0.1", CLIPTALK_AGENT_PORT=str(port))
                agent = subprocess.Popen(["node", "server.mjs"], cwd=ROOT / "agent-service", env=environment, start_new_session=True)
                owned.append(agent)
                deadline = time.monotonic() + 30
                while not service_ready(agent_url + "/health", "cliptalk-agent-service"):
                    if stopping:
                        return 0
                    if agent.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("AI 助手启动失败或超时，请查看上方日志。")
                    time.sleep(.2)
        else:
            print("使用独立部署的 AI 助手服务。请确认该服务可访问。", flush=True)
        if stopping:
            return 0
        web = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", settings.host,
                                "--port", str(settings.port)], cwd=ROOT, start_new_session=True)
        owned.append(web)
        deadline = time.monotonic() + 180
        announced = False
        while not stopping:
            if any(process.poll() is not None for process in owned):
                raise RuntimeError("服务已退出，正在停止本次启动的其他服务。请查看上方错误信息。")
            if not announced and service_ready(f"http://{probe_host}:{settings.port}/api/health", "cliptalk"):
                print(f"ClipTalk 已就绪：http://{probe_host}:{settings.port}；按 Ctrl+C 停止。", flush=True)
                announced = True
            if not announced and time.monotonic() > deadline:
                raise RuntimeError("网页服务启动超时，请检查日志和运行环境。")
            time.sleep(.3)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"启动失败：{error}", file=sys.stderr)
        return 1
    finally:
        for process in reversed(owned):
            stop_owned(process)


if __name__ == "__main__":
    raise SystemExit(main())
