# ClipTalk 环境与部署配置

本文档是运行配置的维护入口。真实密钥只写入本机 `.env`，不要写入代码、测试、日志或提交记录。

## 1. 运行环境

| 项目 | 基线 | 说明 |
| --- | --- | --- |
| 操作系统 | Linux x86_64 | Docker 和本机启动均以 Linux 为支持基线 |
| Python | 3.10 | `.python-version` 固定主版本 |
| Node.js | 22 | 仅构建前端资源和运行浏览器测试需要 |
| FFmpeg / FFprobe | 4.3+ | 必须同时可执行 |
| 磁盘 | 15 GiB 起 | 不含用户上传视频；完整识别模型会额外占用数 GiB |

执行只读自检：

```bash
python3 tools/doctor.py --profile visual
python3 tools/doctor.py --profile cpu
python3 tools/doctor.py --profile cuda
```

`visual` 只检查视觉分析基线；`cpu` 检查 SenseVoice、OCR 和多模态索引依赖；`cuda` 额外要求 PyTorch 能识别 NVIDIA CUDA。未配置模型密钥只产生提醒，不阻止服务启动。

## 2. 安装配置

### 纯视觉最小环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

### CPU 视听环境

```bash
python3 -m pip install -r requirements-audiovisual.txt
```

需要 OCR、文字/画面/声音向量和匿名人物识别时：

```bash
python3 -m pip install -r requirements-recognition-cpu.txt
python3 tools/prepare_recognition_models.py --data-root data
```

### NVIDIA CUDA 可选环境

当前验证组合使用 CUDA 12.1 PyTorch，并让 PaddlePaddle 使用其 CUDA 11.8 wheel。两者依赖宿主机提供兼容的 NVIDIA 驱动：

```bash
python3 -m pip install -r requirements-audiovisual-cu121.txt
python3 -m pip install -r requirements-recognition-cu118.txt
python3 tools/prepare_recognition_models.py --data-root data
python3 tools/doctor.py --profile cuda
```

TalkNet 是独立的可选主动说话人后端，不随默认依赖安装。只有在已准备其仓库、checkpoint 和隔离 Python 后，才配置 `HIGHLIGHT_TALKNET_*`。

## 3. `.env` 配置

```bash
cp .env.example .env
chmod 600 .env
```

### 视觉模型

视觉模型必须支持图片输入和 OpenAI Chat Completions 兼容请求：

```dotenv
VISION_PROVIDER=ark
VISION_API_KEY=replace-with-real-secret
VISION_MODEL=replace-with-vision-model-id
VISION_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

也可以首次启动后在右上角“设置”中保存。界面保存的密钥位于 `data/vision-settings.json`，文件权限为 `0600`，`data/` 不得提交。

### 文本规划模型

未配置独立 LLM 时可以复用视觉模型。独立 OpenAI 兼容接口使用：

```dotenv
LLM_API_KEY=replace-with-real-secret
LLM_MODEL=replace-with-text-model-id
LLM_BASE_URL=https://provider.example/v1
```

Anthropic 兼容接口使用 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` 和 `ANTHROPIC_MODEL`。

### 服务与存储

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `HIGHLIGHT_HOST` | `127.0.0.1` | 非回环地址必须配置访问令牌 |
| `HIGHLIGHT_PORT` | `5180` | 本机服务端口；Docker 容器内固定为 5180 |
| `HIGHLIGHT_ACCESS_TOKEN` | 空 | 公网或局域网部署时至少 16 字符 |
| `HIGHLIGHT_DATA_ROOT` | `./data` | 上传、任务、模型、缓存和输出目录 |
| `HIGHLIGHT_MAX_WORKERS` | `1` | 最大并行 Worker，代码上限为 4 |
| `HIGHLIGHT_MAX_UPLOAD_BYTES` | 8 GiB | 单文件上传上限 |
| `HIGHLIGHT_MAX_STORAGE_BYTES` | 50 GiB | 全部运行数据磁盘上限 |
| `HIGHLIGHT_RETENTION_DAYS` | `0` | 0 表示不自动清理 |
| `HIGHLIGHT_LOG_LEVEL` | `INFO` | JSON 日志级别 |
| `HIGHLIGHT_LOG_FILE` | `./vlm-highlight.log` | `restart.sh` 的输出日志位置 |

远程部署必须置于 HTTPS 反向代理后，不要把访问令牌放入 URL。

### 识别能力

- `HIGHLIGHT_RECOGNITION_PROFILE=auto`：按已安装依赖启用能力。
- `HIGHLIGHT_RECOGNITION_PYTHON`：把可选原生识别模型隔离到另一 Python 环境。
- `HIGHLIGHT_SENSEVOICE_DEVICE=auto`：自动选择 CPU 或 CUDA。
- `HIGHLIGHT_RECOGNITION_MODEL_CACHE=./data/models/recognition`：模型缓存位置。
- `CONTENT_SEARCH_DIALOGUE_V2=true`：启用对话图检索，仅排障回滚时关闭。

完整变量、默认模型和超时配置以 `.env.example` 为准。

## 4. Docker Compose

Docker 镜像是 CPU 基线：

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# 将输出写入 .env 的 HIGHLIGHT_ACCESS_TOKEN
docker compose up --build -d
docker compose ps
```

Compose 会把 `.env` 注入容器，并把 `./data` 挂载到 `/app/data`。容器内监听 `0.0.0.0:5180`，宿主机只映射 `127.0.0.1:5180`。修改宿主机访问方式时仍应通过反向代理提供 HTTPS。

## 5. 提交安全

上传前执行：

```bash
python3 tools/check_repository.py
```

检查会拒绝真实 `.env`、运行目录、视频、数据库、日志、根目录截图、已知密钥格式、机器绝对路径和超过 50 MiB 的文件。模型名称、端口或依赖发生变化时，应同时更新 `.env.example` 与本文档。
