# AI-assisted installation / AI 辅助安装

This document is the canonical execution guide for an AI coding agent that is
asked to install, repair, start, or validate ClipTalk. Human-oriented background
remains in [`getting-started.md`](getting-started.md) and advanced deployment
details remain in [`deployment.md`](deployment.md).

本文是 AI 编码 Agent 安装、修复、启动或验证 ClipTalk 时的唯一执行指南。
面向普通用户的背景说明见 [`getting-started.md`](getting-started.md)，高级部署
参数见 [`deployment.md`](deployment.md)。

## Prompt for an agent / 可直接交给 AI 的提示词

中文：

> 阅读仓库根目录 AGENTS.md 和 docs/AI_INSTALL.md。先只读检查当前机器，说明
> 你选择的 CPU/GPU、本机或 Docker 安装方式及影响，再完成 ClipTalk 安装与
> 验证。不要覆盖已有配置、密钥、素材、模型和任务数据；需要 sudo、远程开放
> 端口或删除数据时先询问我。最后分别汇报运行环境和模型能力是否就绪。

English:

> Read AGENTS.md and docs/AI_INSTALL.md. Inspect the machine without changing it,
> explain the selected local/Docker and CPU/GPU route, then install and validate
> ClipTalk. Preserve existing configuration, credentials, media, models, and task
> data. Ask before sudo, remote exposure, or deletion. Report runtime readiness
> and model-capability readiness separately.

## 1. Establish the current state / 确认当前状态

Begin in the repository root. These probes are read-only; run only commands that
exist on the host and record failures instead of hiding them:

```bash
uname -srm
python3 --version
node --version
ffmpeg -version
ffmpeg -hide_banner -encoders
ffmpeg -hide_banner -filters
df -h .
docker version
docker compose version
nvidia-smi
```

Then use the project preflight. Neither command installs or downloads anything:

```bash
python3 tools/setup.py --check --profile auto
python3 tools/setup.py --dry-run --profile auto
```

Required local baseline:

- x86-64 Linux or Windows WSL2.
- Python 3.10 or 3.11.
- Node.js 22.x.
- FFmpeg and FFprobe; FFmpeg must expose `libx264` and `drawtext`.
- At least 6 GiB free for CPU or 10 GiB for GPU; prefer 10 GiB and 16 GiB
  respectively, before later model and media growth.
- A writable project/data location whose path does not contain spaces.

本机安装要求 x86-64 Linux/WSL2、Python 3.10–3.11、Node.js 22、支持
`libx264` 与 `drawtext` 的 FFmpeg/FFprobe，以及足够磁盘空间。macOS、ARM
或其他未经验证的平台不能被 Agent 宣称为受支持的原生安装；应解释限制并让
用户选择兼容的 x86-64 主机或经验证的容器环境。

## 2. Choose one owner and one route / 选择唯一管理方式

Do not run local and Docker supervisors for the same instance. Preserve an
existing working route unless the user asks to migrate.

Choose local installation when all of the following are true:

- The host is supported Linux/WSL2 x86-64.
- Compatible Python, Node.js, and FFmpeg can be installed without destabilizing
  another application.
- The user did not request container isolation.

Choose Docker when the user explicitly requests isolation, system runtimes are
incompatible, or the installation is intended to be reproducible on a server.
Use CPU unless a compatible NVIDIA container runtime is already verified or the
user explicitly requests GPU.

同一个实例只能由一种方式管理。已有可工作的部署方式时，不主动迁移。本机
满足要求且用户未要求隔离时优先使用本机安装；依赖冲突、服务器复现或用户
要求隔离时使用 Docker。未验证 NVIDIA 容器运行环境时默认 CPU。

Before downloading, tell the user that the default setup includes large Python
packages, Chromium, recognition dependencies, TalkNet code, and model weights.
If system packages or `sudo` are needed, show the exact proposed command and wait
for approval. Do not silently install global Python or npm packages.

## 3A. Supported local installation / 本机安装

Run the repository-owned installer. Its default `auto` profile selects GPU only
when a suitable visible NVIDIA driver is detected:

```bash
python3 tools/setup.py --profile auto
```

The installer is restartable and works inside `.venv`; rerun the same command
after fixing a failed prerequisite. Do not manually reproduce its pip/npm or
TalkNet steps unless diagnosing the failing stage.

If Conda or another environment shadows a capable system FFmpeg, identify both
paths and configure only the necessary overrides in `.env`, preserving every
existing line:

```dotenv
FFMPEG_BIN=/usr/bin/ffmpeg
FFPROBE_BIN=/usr/bin/ffprobe
```

Never replace `.env` with an example file. Never copy credentials or absolute
paths from another machine. If GPU setup fails because the host is incompatible,
explain the failure and offer the supported CPU retry:

```bash
python3 tools/setup.py --profile cpu
```

Validate without starting a long-running service:

```bash
bash -n start.sh
bash start.sh --check
.venv/bin/python tools/doctor.py
```

To validate the running service, start `bash start.sh` in a supervised terminal,
wait for its ready message, and query the local health endpoint:

```bash
curl -fsS http://127.0.0.1:5180/api/health
```

Keep the process running only when the user asked to start the application.
Otherwise stop only the processes created by this installation attempt. Never
kill an unrelated process occupying port 5180; report it or offer a different
`HIGHLIGHT_PORT`.

## 3B. Docker installation / Docker 安装

Require Docker Engine 24+ and Docker Compose 2.24+. Validate configuration before
building. The default CPU route is:

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail=200 cliptalk agent
```

Use the GPU route only after `docker run --gpus all` or an equivalent read-only
probe confirms that the NVIDIA runtime works:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
docker compose -f docker-compose.yml -f docker-compose.gpu.yml ps
```

Confirm health at `http://127.0.0.1:5180/api/health`. Docker data lives in the
`cliptalk-data` named volume. Routine repair may use `docker compose down`, but
must never use `docker compose down -v` because that deletes persistent project
data. Do not prune global Docker images, volumes, or caches without a separate,
explicit user request.

Docker 默认只发布到 `127.0.0.1`，本机使用不要求访问令牌。只有用户明确要求
远程访问时，才允许设置非回环 `CLIPTALK_BIND_ADDRESS`；此时必须同时配置至少
16 字符的独立 `HIGHLIGHT_ACCESS_TOKEN`，并要求使用 HTTPS 反向代理。不要把
令牌写进版本控制、文档或聊天输出。

## 4. Readiness is two-stage / 两阶段就绪标准

Runtime installation is complete only when:

1. The selected installer/build completed without a hidden failing stage.
2. FFmpeg, FFprobe, H.264 encoding, subtitle rendering, data-directory access,
   Python dependencies, and the local Agent service pass their checks.
3. `/api/health` responds from the expected local address when the service is
   intentionally started.

Product capability is complete only when the user has opened **Settings** and
the first-use checklist confirms the visual model, editing-planner model, and
Agent Tool Calling probe. TalkNet is an optional enhancement and its unavailable
state must be reported, but it does not block basic editing.

运行安装完成的标准是安装阶段没有失败、Doctor 的必需项通过，并且主动启动
服务后健康接口可访问。完整产品能力还要求用户在页面“设置”中使用自己的模型
服务，并通过视觉分析、剪辑规划和 Agent Tool Calling 检查。Agent 不得索要、
代填或在终端回显模型 API Key。

## 5. Recovery rules / 故障恢复规则

- Missing system package: report the package and proposed package-manager command;
  ask before `sudo`.
- Wrong Python or Node version: install/use a compatible isolated runtime rather
  than modifying unrelated projects.
- FFmpeg lacks `libx264` or `drawtext`: locate a compatible binary or ask to
  install one; use `FFMPEG_BIN`/`FFPROBE_BIN` when appropriate.
- Insufficient disk: stop before download and report minimum and recommended free
  space. Do not delete user data automatically.
- Failed TalkNet stage: retry `python3 tools/install_talknet.py` after the cause is
  fixed; do not overwrite a manually managed directory.
- Port conflict: identify and report it; never terminate an unowned process.
- Docker failure: inspect bounded logs and Compose state. Preserve the named volume.
- Interrupted installation: rerun the same supported installer; it preserves
  downloaded dependencies, configuration, media, and tasks where supported.

## 6. Final report / 最终汇报

Always finish with a concise report containing:

- Route used: local or Docker, CPU or GPU.
- Commands/checks completed and their actual outcomes.
- Runtime readiness: ready or blocked, with the exact blocker.
- Model capability readiness: configured, still requiring UI setup, or failed.
- Local URL and whether the service was left running.
- Warnings or optional capabilities that remain unavailable.
- The single next action required from the user, if any.

Do not summarize a partial installation as successful. Do not expose credentials,
private endpoints, full environment files, or machine-specific secrets in the
report.

最终必须分别报告安装路径、验证结果、运行环境状态、模型能力状态、本地地址、
服务是否保持运行、可选能力告警和用户下一步。部分完成不能笼统写成“安装成功”。
