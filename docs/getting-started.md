# 首次安装与使用

默认安装包含网页、AI 助手、语音与内容识别依赖，以及 TalkNet 人物说话识别。
不需要复制开发者的 `.env`，不需要填写 Python、模型目录或显卡编号。
模型 API 的使用费用、下载所需网络与磁盘空间由部署者承担。

## 本机安装（Linux / Windows WSL2）

目前本机安装目标为 x86-64 Linux，Python 3.10–3.11、Node.js 22。
Windows 使用 WSL2。其他系统可参考 Docker 部署，但尚未验证 macOS/ARM 原生安装。

先安装 Git、Python venv、Node.js 22 和 FFmpeg。Node.js 必须是 22.x；发行版版本过旧时请使用 Node.js 官方安装包或版本管理器。Debian/Ubuntu 系统组件示例：

```bash
sudo apt-get update
sudo apt-get install -y git curl python3-venv ffmpeg libgomp1 libsndfile1
```

发行版提供的 Python/Node 版本可能不匹配，请先执行 `python3 --version`、`node --version`。
如果系统 Python 不是 3.10–3.11，可用已安装的 `python3.11` 替换以下安装命令中的 `python3`。
FFmpeg 应支持 H.264 编码和 drawtext；安装脚本不会自行提权或修改系统软件。
如果 Conda 等环境遮蔽了系统 FFmpeg，检查结果会显示实际使用的路径；可在 `.env` 中将 `FFMPEG_BIN`、`FFPROBE_BIN` 指向可用的系统程序后重新检查。

在项目目录中执行：

```bash
python3 tools/setup.py
bash start.sh
```

安装器先检查前置条件，再安装到项目 `.venv` 和 `data/models/talknet`。
它默认安装 TalkNet 的代码、隔离环境及权重；已有 `.env`、素材与手动模型目录不会被覆盖。
检测到兼容 NVIDIA 驱动时选择 GPU 依赖，否则安装 CPU 环境。
首次安装会下载较大的依赖、Chromium 和模型。CPU 安装至少需要 6 GiB、建议预留 10 GiB；GPU 安装至少需要 10 GiB、建议预留 16 GiB，后续内容识别模型和素材还会继续占用空间。
失败会停止并显示失败阶段；修复网络或系统依赖后可重新执行，不会删除任务。
如果直接运行 `bash start.sh` 时检测到安装不完整，交互式终端会询问是否启动统一安装器；脚本或服务管理器等非交互环境不会自动下载。

启动脚本会一起启动网页和本地 AI 助手，默认打开：

```text
http://127.0.0.1:5180
```

等待终端显示“ClipTalk 网页服务已启动”或“ClipTalk 剪辑能力已就绪”，然后在页面“设置”中配置视觉模型、剪辑规划和 AI 助手所需的模型服务。
页面顶部的“首次使用检查”会分别显示基础剪辑和 Agent Tool Calling 是否就绪；人物说话识别是可选增强项，不会阻断基础剪辑。
保存后上传视频并描述目标。按 `Ctrl+C` 会停止本次启动的服务，不会终止此前已运行的独立助手。
端口被其他程序占用时会报错，不会自动杀掉那个程序。

## 安装验证

```bash
python3 tools/setup.py --check
python3 tools/setup.py --dry-run
.venv/bin/python tools/doctor.py
```

`--check` 只检查系统前置条件；`--dry-run` 只显示步骤，均不会安装或下载。
安装结束时会载入 TalkNet 权重并执行小型前向计算，不只是检查文件存在。
完整视频效果仍应使用自己的素材预览验证；CPU 上长视频的人物说话识别可能明显较慢。

在页面“设置 → 人物说话识别”点击“检查能力”，可查看可用、未安装完整、待检查、已关闭或不可用状态。
能力检查不会上传素材或安装软件。第一次检查可能需要等待依赖载入。
其他语音、图文和人物模型仍可能在首次使用时下载；可提前运行：

```bash
.venv/bin/python tools/prepare_recognition_models.py --data-root data
```

## 默认安装失败或已有安装需要修复

仅重试 TalkNet 安装：

```bash
python3 tools/install_talknet.py
```

需要强制 CPU 或 GPU 时，向安装命令添加 `--profile cpu` 或 `--profile gpu`。
CPU 兼容适配会随默认安装准备，无须用户手改第三方源码。
上游视频处理命令暂不支持带空格的安装路径；安装器会提前提示，请使用无空格的项目/数据路径。
手动安装目录只检查、不自动修改；迁移方法见 [部署说明](deployment.md)。

## Docker

建议使用 Docker Engine 24+ 与 Docker Compose 2.24+。Windows 用户可在 WSL2 中配合 Docker Desktop 使用；GPU 模式还需要 NVIDIA Container Toolkit，并应先确认 `docker run --gpus all` 能看到显卡。

```bash
docker compose up --build -d
```

默认构建 CPU 环境并安装 TalkNet，首次构建需要下载模型。
GPU 部署使用仓库的 GPU Compose 配置，详见 [部署说明](deployment.md)。
数据卷挂载在 `/app/data`；镜像内 TalkNet 位于 `/opt/cliptalk-models`，不会被空数据卷遮住。
默认端口只发布到宿主机 `127.0.0.1:5180`。不要直接将无认证服务改为公网可访问。
查看启动状态使用 `docker compose ps`，持续查看日志使用 `docker compose logs -f cliptalk agent`，停止服务使用 `docker compose down`。

## 配置原则

普通本机用户可以完全不创建 `.env`。要更改端口、数据目录时参考根目录 [`.env.example`](../.env.example)。
服务器、访问认证、并发和 GPU 等完整参数见 [高级参数参考](environment.example)。
只复制确实需要修改的项，留空的 TalkNet 路径会自动发现，不要复制别人机器上的绝对路径。
