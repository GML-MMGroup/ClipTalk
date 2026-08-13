<div align="center">

<!-- 👇 在这里替换你的封面 Banner -->

<img src="./assets/banner.png" alt="ClipTalk Banner" width="100%" />

# ClipTalk ✂️

### 一个通过对话完成视频剪辑的 AI Agent

**只需要说出来，视频就剪好了。**

[![License](https://img.shields.io/badge/license-GPL%20v3-blue)](./LICENSE)
[![Stars](https://img.shields.io/github/stars/GML-MMGroup/ClipTalk?style=social)](https://github.com/GML-MMGroup/ClipTalk)
[![Version](https://img.shields.io/badge/version-1.0.0-brightgreen)](https://github.com/GML-MMGroup/ClipTalk/releases)
[![Discord](https://img.shields.io/badge/Discord-Join-5865f2)](https://discord.gg/yourlink)

[English](./README.md) · **简体中文** · [在线体验](#) · [文档](#)

</div>

---

## 📰 最新动态

* **[2026-08-12]** 🚀 优化时间轴显示，并新增 **竖屏创作模式** 切换支持。
* **[2026-07-20]** ✨ 新增 **高光剪辑 Agent**，支持自动提取视频高光片段。
* **[2026-07-10]** 🎉 ClipTalk 正式 **开源**！

<!-- 后续更新持续追加到这里 -->

---

## 🗺️ Roadmap

ClipTalk 正在持续迭代，希望打造一个更强大的对话式视频剪辑体验。

* [x] 💬 **对话式剪辑基础设施**
* [x] ⚡ **高光剪辑 Agent**
* [ ] 👤 **人脸匹配剪辑** — 找到视频中的目标人物，并提取其出现在画面中的所有片段。
* [ ] 🔊 **声纹识别剪辑** — 通过声纹识别目标说话人，并提取该人物讲话的片段。
* [ ] 🧭 **话题分割剪辑** — 理解视频内容，并围绕指定话题自动提取相关片段。
* [ ] 🎞️ **可二次编辑时间轴** — 对 AI 自动生成的剪辑结果继续在时间轴中进行精细调整和二次编辑。

---

## 🌟 效果展示 — 一句话，完成一次剪辑

> 只需要一句自然语言指令，ClipTalk 即可完成真实的视频剪辑任务。
>
> <!-- 在这里添加 GIF 对比：原始素材 → 用户指令 → 剪辑结果 -->
<div align="center">
<table>
  <tr>
    <td align="center"><b>📰 新闻与资讯高光</b><br/><img src="./assets/cases/news-broadcast.gif" width="240"/></td>
    <td align="center"><b>🧵 DIY 与手工教程</b><br/><img src="./assets/cases/diy-craft.gif" width="240"/></td>
    <td align="center"><b>📦 产品介绍</b><br/><img src="./assets/cases/product.gif" width="240"/></td>
  </tr>
  <tr>
    <td align="center"><b>🏢 生活 Vlog</b><br/><img src="./assets/cases/meeting.gif" width="240"/></td>
    <td align="center"><b>🎵 音乐表演高光</b><br/><img src="./assets/cases/music.gif" width="240"/></td>
    <td align="center"><b>⚽ 体育赛事高光</b><br/><img src="./assets/cases/sports.gif" width="240"/></td>
  </tr>
</table>
</div>

---

## 💡 什么是 ClipTalk？

ClipTalk 是一个 **AI 视频剪辑 Agent**。

你不需要在时间轴上反复拖拽素材，也不需要在几个小时的视频中来回寻找片段。你只需要用自然语言描述自己想要什么，Agent 就可以自动完成整个剪辑流程：

**理解视频内容 → 定位目标内容 → 规划剪辑方案 → 执行剪辑 → 输出最终片段。**

<div align="center">
  <img src="./assets/showcase/conversational-highlight-editing-preview.gif" alt="ClipTalk conversational highlight editing workflow" width="900" />
  <br />
  <sub><b>“把最精彩的部分剪成一个高光视频。”</b> — ClipTalk 会自动分析视频内容、展示事件时间轴，并生成多个 AI 剪辑版本。</sub>
</div>

<br />

> 上传一个 1 小时的视频，告诉 ClipTalk 你想要哪些内容，让它自动理解素材、规划剪辑并输出最终视频。

---

## ✨ 核心特性

### 💬 对话式剪辑

只需要描述你想要什么，就可以完成视频剪辑。

从：

*“把最精彩的部分剪成一个高光视频”*

到：

*“把介绍 XX 产品的部分剪出来”*

ClipTalk 可以直接把自然语言指令转换成具体的剪辑操作。

你还可以通过多轮对话继续调整结果，例如：

*“再短一点”*

或者：

*“从讲价格的地方开始。”*

### 🎯 四大核心剪辑能力

* **⚡ 高光切片提取** — 自动理解长视频内容，识别其中最有价值的时刻，并生成精炼的高光片段。

* **👤 人脸匹配剪辑** — 找到视频中的目标人物，并自动提取其出现在画面中的片段。

* **🧭 话题分割剪辑** — 根据指定话题定位并提取相关内容，例如 *“把讲解 XX 产品的片段剪出来。”*

* **🔊 声纹识别剪辑** — 通过声纹识别指定说话人，并自动提取该人物讲话的所有片段。

---

## 🏗️ 工作原理

ClipTalk 会把自然语言剪辑指令转换成完整的视频剪辑流程。

### 👤 人脸匹配剪辑

```text
💬 “把所有王总出现的画面剪出来”
        ↓
🤖 Agent 理解目标人物
        ↓
👤 人脸匹配 → 定位所有目标人物出现的画面
        ↓
✂️ 剪辑片段 → 🎞️ 合成 → ✅ 完成
```

### ⚡ 高光剪辑

```text
💬 “把最精彩的部分剪成一个高光视频”
        ↓
🤖 Agent 分析视频内容
        ↓
🎬 理解事件 → 识别高光时刻 → 选择关键片段
        ↓
✂️ 剪辑并排序 → 🎞️ 合成 → ✅ 完成
```

### 🧭 话题分割剪辑

```text
💬 “把讲解 XX 产品的片段剪出来”
        ↓
🤖 Agent 理解目标话题
        ↓
📝 分析对话 → 🧭 话题分割 → 定位相关内容
        ↓
✂️ 剪辑片段 → 🎞️ 合成 → ✅ 完成
```

**一句指令输入，最终视频输出。**

---

## 🚀 快速开始

需要 Linux x86_64（Windows 可使用 WSL2）、Python 3.10/3.11、FFmpeg 和 ffprobe。

```bash
git clone https://github.com/GML-MMGroup/ClipTalk.git
cd ClipTalk

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-audiovisual.txt
bash start.sh
```

### 模型职责

* **VLM · 必需** — 理解画面、发现事件并精修镜头边界。
* **LLM · 可选** — 规划镜头取舍、顺序和不同成片方向；可以直接复用 VLM。
* **SenseVoice · 可选/本地运行** — 补充带时间范围的对白、情绪和声音证据；不可用时仍可纯视觉分析。

打开终端输出的访问地址，在 **Settings** 中配置 VLM，并按需配置独立 LLM；然后上传视频并描述剪辑要求。

---

## ⚙️ 部署与配置

### ⚡ 本地安装使用 NVIDIA GPU

如果机器拥有 NVIDIA GPU，并且显卡驱动支持 CUDA 12.1，可以将 CPU 依赖安装命令替换为：

```bash
python -m pip install -r requirements-audiovisual-cu121.txt
```

请在一个全新的虚拟环境中，只安装 CPU 或 CUDA 版本中的一种依赖文件。

目前提供的 Docker 镜像为 CPU-only。GPU Docker 容器需要另外构建支持 CUDA 的镜像，并配置 NVIDIA Container Toolkit。

### 🎙️ 语音模型与首次启动

服务器会在后台启动一个 SenseVoice Worker，Web 页面不会等待它初始化完成。

缺失的 SenseVoice / VAD 模型会自动从 ModelScope 下载到：

```text
./data/models
```

因此，第一次执行带语音分析的视频任务可能会花费更长时间。

如果希望在启动应用前提前下载并验证模型，可以执行：

```bash
# 使用 HIGHLIGHT_SENSEVOICE_DEVICE 指定的设备（默认：auto）
python tools/prepare_speech_models.py

# 同时准备 CAM++，用于说话人相关任务
python tools/prepare_speech_models.py --with-speakers
```

### 🐳 使用 Docker 运行

```bash
git clone https://github.com/GML-MMGroup/ClipTalk.git
cd ClipTalk
cp .env.example .env
docker compose up --build
```

等待容器进入健康状态后，在 Docker 主机上打开：

```text
http://127.0.0.1:<CLIPTALK_PORT>
```

然后在 **Settings** 页面中配置视觉模型和剪辑规划模型。

`CLIPTALK_PORT` 从 `.env` 文件中读取，默认值为：

```text
5180
```

Docker 会将上传的视频、模型缓存、任务记录以及渲染结果保存在 Docker 管理的 `cliptalk-data` Volume 中。

执行：

```bash
docker compose down
```

不会删除该 Volume。

而：

```bash
docker compose down -v
```

会永久删除该 Volume 中的数据。

旧版本使用 `./data` 目录进行 bind mount。

升级版本不会删除这个目录，但其中的数据不会自动迁移到新的 named volume，因此迁移已有任务之前请先做好备份。

常用检查命令：

```bash
docker compose ps
docker compose logs --tail=200 cliptalk
```

在 Apple Silicon 或其他非 amd64 主机上，由于固定版本 PyTorch 镜像的限制，可能需要启用 Linux/amd64 模拟：

```text
DOCKER_DEFAULT_PLATFORM=linux/amd64
```

这种方式的运行速度会比原生 Linux x86_64 环境更慢。

### 🌐 应该打开哪个地址？

| ClipTalk 运行位置     | 打开的地址                                               |
| ----------------- | --------------------------------------------------- |
| 本地运行，同一台电脑访问      | Uvicorn 输出的 URL：`http://127.0.0.1:<HIGHLIGHT_PORT>` |
| Docker 运行，同一台电脑访问 | `http://127.0.0.1:<CLIPTALK_PORT>`                  |
| 远程服务器本地运行         | `http://<server-ip>:<HIGHLIGHT_PORT>`               |
| 远程服务器 Docker 运行   | `http://<server-ip>:<CLIPTALK_PORT>`                |

Docker 默认绑定：

```text
127.0.0.1
```

如果需要远程访问 Docker 部署，请修改 `.env`，配置监听地址和访问 Token：

```bash
CLIPTALK_BIND_ADDRESS=0.0.0.0
HIGHLIGHT_ACCESS_TOKEN=replace-with-a-long-random-token
```

如果使用非 Docker 方式在远程服务器部署，请在执行：

```bash
bash start.sh
```

之前配置：

```bash
HIGHLIGHT_HOST=0.0.0.0
```

并设置相同的访问 Token。

随后，在服务器防火墙或安全组中放行 `HIGHLIGHT_PORT` 对应端口，然后访问：

```text
http://<server-ip>:<HIGHLIGHT_PORT>/?token=<your-token>
```

不要在其他设备上使用 `127.0.0.1` 访问服务器，因为它始终指向当前设备自身。

如果需要将 ClipTalk 部署到公网，请使用带身份验证的 HTTPS 反向代理，而不是直接暴露开发服务器。

如果 Docker 默认端口已经被占用，可以在 `.env` 中将 `CLIPTALK_PORT` 修改为其他空闲端口，然后使用对应地址访问。

### 🔧 可选环境变量配置

推荐直接通过 Web UI 配置视觉模型和剪辑规划模型。

如果需要无界面部署，可以复制项目提供的环境变量模板，并只修改需要的字段：

```bash
cp .env.example .env
```

`start.sh` 会直接读取该文件，Docker Compose 也会将其中的配置传入容器。

常见配置项包括：

```text
HIGHLIGHT_HOST
HIGHLIGHT_PORT
HIGHLIGHT_DATA_ROOT
VISION_*
LLM_*
```

以及 SenseVoice 对应的设备和模型配置。

请勿将 `.env` 或 API Key 提交到 Git 仓库。

可以使用与服务启动时相同的端口检查服务状态：

```bash
SERVICE_PORT="${HIGHLIGHT_PORT:-5180}"  # Docker 环境请使用 CLIPTALK_PORT
curl -s "http://127.0.0.1:${SERVICE_PORT}/api/health" | python -m json.tool
```

返回：

```text
ok: true
```

说明 HTTP 服务已经正常运行。

开始执行视频分析之前，通常还应该看到：

```text
mediaToolsReady: true
analysisReady: true
```

语音能力属于辅助模块，因此模型下载过程中：

```text
speechReady
```

即使仍然为 `false`，也不会影响只依赖视觉能力的分析任务。

如果命令无法连接服务，请检查：

* 启动进程是否仍在运行；
* 终端中是否存在错误信息；
* 当前使用的 Host 和 Port 是否与启动时一致。

如果 FFmpeg 和 ffprobe 已经位于 `PATH` 中，但系统仍然无法找到媒体工具，可以在 `.env` 中手动设置：

```text
FFMPEG_BIN
FFPROBE_BIN
```

为它们对应的绝对路径。

正常使用 ClipTalk **不需要 Node.js 构建步骤**，浏览器所需资源已经包含在：

```text
static/
```

目录中。

只有重新构建 `package.json` 中定义的可选前端动画或图标资源时，才需要 Node.js。

---

## 🤝 参与贡献

<div align="center">

⭐ 如果 ClipTalk 对你有帮助，欢迎给项目点一个 Star！

Made with ❤️ by the ClipTalk Team

</div>
