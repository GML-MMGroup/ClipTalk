#!/bin/bash
# ClipTalk 启动器（2026-09-17）：容器里必须用 /opt/conda/bin/python3，
# 非交互 SSH 的 PATH 不带 /opt/conda/bin，直接用 python3 会缺 uvicorn。
cd /data/chuangxin.zhang/VideoPilot/new || exit 1
exec /opt/conda/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 5191
