# ClipTalk Agent Instructions

本文件是仓库级 Agent 约定。安装与部署任务必须继续阅读
[`docs/AI_INSTALL.md`](docs/AI_INSTALL.md)，不要根据经验另写一套安装流程。

This file defines repository-wide instructions for coding agents. For setup or
deployment work, also read [`docs/AI_INSTALL.md`](docs/AI_INSTALL.md). Do not
invent a parallel installation procedure.

## Installation workflow / 安装流程

- Start with read-only discovery. Identify the operating system, architecture,
  Python and Node.js versions, FFmpeg capabilities, free disk space, Docker,
  and visible NVIDIA hardware before choosing an installation route.
- Run `python3 tools/setup.py --check --profile auto` and
  `python3 tools/setup.py --dry-run --profile auto` before an actual local
  installation. Use the repository scripts instead of reproducing their work
  as ad-hoc shell commands.
- Prefer the supported local installer on x86-64 Linux or WSL2. Use Docker when
  the user requests isolation or the host cannot reasonably satisfy the local
  prerequisites. Do not claim native macOS or ARM support.
- Explain large downloads, expected disk use, and the chosen CPU/GPU route
  before starting an installation.
- Treat runtime installation and model configuration as separate milestones.
  A healthy web service is not the same as a fully configured editing system.
  Model credentials are configured by the user in the product settings.

- 安装前先执行只读探测，再选择本机或 Docker 路径。
- x86-64 Linux/WSL2 默认优先使用仓库统一安装器；用户要求隔离或本机依赖
  不适合时再使用 Docker。不要宣称原生支持 macOS 或 ARM。
- 下载大型依赖或模型前，先说明 CPU/GPU 方案、磁盘占用和网络影响。
- “运行环境安装完成”和“模型能力配置完成”必须分别汇报，不能混为一谈。

## Safety boundaries / 安全边界

- Do not overwrite `.env`, saved credentials, `data/`, model caches, uploads,
  outputs, or manually managed TalkNet directories.
- Never print, commit, or copy API keys and access tokens into documentation or
  command logs. A loopback-only local installation does not require an access
  token. Remote exposure requires explicit user intent, a strong token, and an
  HTTPS reverse proxy.
- Ask before using `sudo`, changing system packages, exposing a network port,
  switching an existing installation between local and Docker management, or
  deleting data. Never run `docker compose down -v` as routine cleanup.
- Do not stop unrelated processes to reclaim a port. Report the owning process
  or offer a different port.
- Preserve `README.md`, `README_zh.md`, and `LICENSE` unless the user explicitly
  asks to modify them. Do not publish local tests, screenshots, videos, secrets,
  or runtime data when preparing a release.

- 不覆盖 `.env`、已有密钥、任务数据、素材、输出、模型缓存或手动维护的
  TalkNet 目录。
- 使用 `sudo`、修改系统软件、开放远程端口、切换部署方式或删除数据前，
  必须先取得用户确认。
- 不要为了释放端口而结束不属于本次启动的进程。
- 未经明确要求，不修改 `README.md`、`README_zh.md` 和 `LICENSE`。

## Verification and handoff / 验证与交付

- Local verification: run `bash -n start.sh`, `bash start.sh --check`, and the
  appropriate `.venv/bin/python tools/doctor.py` profile after installation.
- Docker verification: render both CPU and GPU Compose configurations before
  building; after startup inspect `docker compose ps`, bounded recent logs, and
  `/api/health`.
- Run `python3 tools/check_repository.py --mode deployment` after changing
  installation or deployment files.
- Report the exact route used, checks that passed, unresolved warnings, the
  local URL, whether the process remains running, and the next user action.
  Never hide a failed optional capability behind a generic success message.

- 本机安装后检查启动脚本、Doctor 和健康接口；Docker 安装先验证 CPU/GPU
  Compose 配置，再检查容器状态、有限范围日志和健康接口。
- 最终说明安装方式、通过项、剩余告警、本地访问地址、服务是否仍在运行，
  以及用户下一步需要在界面完成的模型配置。
