# ClipTalk 环境与部署配置

本文档是运行配置的维护入口。真实密钥只写入本机 `.env`，不要写入代码、测试、日志或提交记录。

## 1. 运行环境

| 项目 | 基线 | 说明 |
| --- | --- | --- |
| 操作系统 | Linux x86_64 | Docker 和本机启动均以 Linux 为支持基线 |
| Python | 3.10–3.11 | `.python-version` 固定为 3.10；当前依赖不支持 3.12 |
| Node.js | 22 | 仅构建前端资源和运行浏览器测试需要 |
| FFmpeg / FFprobe | 4.3+ | 必须同时可执行 |
| curl | 任一受支持版本 | `restart.sh` 用于本机健康检查 |
| 中文字幕字体 | 文泉驿正黑 | Debian/Ubuntu 安装 `fonts-wqy-zenhei` |
| 磁盘 | 15 GiB 起 | 不含用户上传视频；完整识别模型会额外占用数 GiB |

执行只读自检：

```bash
python3 tools/doctor.py --profile visual
python3 tools/doctor.py --profile cpu
python3 tools/doctor.py --profile cuda
```

`visual` 检查服务、媒体工具和字幕字体基线；`cpu` 检查 SenseVoice、OCR 和多模态索引依赖；`cuda` 额外要求 PyTorch 与 PaddlePaddle 都能使用 NVIDIA CUDA。未配置模型密钥只产生提醒，不阻止服务启动。

## 2. 安装配置

### CPU 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-cpu.txt
```

CPU 版包含服务、SenseVoice、OCR、文字/画面/声音向量和匿名人物识别的完整依赖。首次使用识别能力前准备本地模型：

```bash
python3 tools/prepare_recognition_models.py --data-root data
```

### NVIDIA CUDA 可选环境

当前验证组合使用 CUDA 12.1 PyTorch，并让 PaddlePaddle 使用其 CUDA 11.8 wheel。两者依赖宿主机提供兼容的 NVIDIA 驱动：

```bash
python3 -m pip install -r requirements-gpu.txt
python3 tools/prepare_recognition_models.py --data-root data
python3 tools/doctor.py --profile cuda
```

TalkNet 是独立的可选主动说话人后端，不随默认依赖安装。只有在已准备其仓库、checkpoint 和隔离 Python 后，才配置 `HIGHLIGHT_TALKNET_*`。

### 开发与测试工具

CPU/GPU 文件只包含运行依赖。开发环境另外安装测试与静态检查工具：

```bash
python3 -m pip install 'pytest>=9,<10' 'ruff>=0.12,<1'
```

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
| `CONTENT_SEARCH_MODEL_CONCURRENCY` | `3` | 单次内容检索的语义复核并发数，代码上限为 4 |
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

### 跨视频声纹人物

声纹人物库默认关闭，必须为每个部署单独配置 32 字节加密密钥：

```bash
python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
# 将输出写入 .env 的 HIGHLIGHT_VOICEPRINT_ENCRYPTION_KEY，然后重启服务
```

人物名称、CAM++ 参考向量和聚合向量会整体写入 `data/voiceprints/profiles.enc`，使用 AES-GCM 加密。上传或从视频截取的参考声音仅存在于 `data/runtime/voiceprint-temp`，向量提取完成或失败后都会删除。密钥不会写入声纹文件；丢失或更换密钥后旧库无法恢复，应先备份或删除旧库再重新注册。

默认匹配策略为三态判定：相似度低于 `0.31` 排除，`0.31–0.38` 标记为待复核；高于 `0.38` 且领先其他已注册人物至少 `0.05` 才自动保留。阈值可通过 `HIGHLIGHT_VOICEPRINT_*_THRESHOLD` 调整。串音、重叠说话和竞争人物分数接近的片段不会自动进入成片。

一句话入口先使用本地规则判断任务方向。规则置信度不足且剪辑规划模型可用时，只把文字要求发送给模型做一次轻量分类；视频不会在此步骤上传给模型。分类置信度低于 0.78、模型超时或未配置时，界面会要求用户明确选择，不会猜测执行。

浏览器对不小于 16 MiB 的视频自动启用 4 MiB 分片上传。服务端将当前偏移持久化到 `data/uploads/.sessions`；浏览器刷新、网络断开或响应丢失后会先读取服务端偏移并从下一分片继续。文件完整后才会原子移入正式上传目录并执行解码覆盖校验。

`GET /api/runtime` 的 `stagePerformance` 汇总各处理阶段的样本数、平均耗时和最长耗时，`resources` 提供进程峰值内存及数据盘使用情况。指标不包含文件名、剪辑要求或任务 ID。

## 4. Docker Compose

Docker Compose 默认使用 `cpu`，包含 SenseVoice、OCR、多模态索引、匿名人物识别和中文字幕字体：

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# 将输出写入 .env 的 HIGHLIGHT_ACCESS_TOKEN
docker compose up --build -d
docker compose ps
docker compose exec -T cliptalk python tools/container_smoke.py
```

GPU 容器需要宿主机安装 NVIDIA Container Toolkit，并叠加 GPU Compose 配置；该配置会安装 GPU requirements 并向容器公开显卡：

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T cliptalk python tools/container_smoke.py
```

Compose 会把 `.env` 注入容器，并使用 `cliptalk-data` 命名卷持久化 `/app/data`。命名卷能保留容器内非 root 用户的正确权限，首次启动无需在宿主机手工修改目录所有者。容器内监听 `0.0.0.0:5180`，宿主机只映射 `127.0.0.1:5180`。修改宿主机访问方式时仍应通过反向代理提供 HTTPS。

## 5. 提交安全

上传前执行：

```bash
python3 tools/check_repository.py
```

检查会拒绝真实 `.env`、运行目录、视频、数据库、日志、根目录截图、已知密钥格式、机器绝对路径和超过 50 MiB 的文件。模型名称、端口或依赖发生变化时，应同时更新 `.env.example` 与本文档。

发布包没有携带 `.git` 元数据时，检查器会自动改为扫描源码快照，并跳过 `data/`、`tmp/`、`node_modules/` 等目录内部的逐文件读取；这些目录及根目录媒体仍会作为边界问题报告。检查器只报告，不会删除或移动用户素材。
