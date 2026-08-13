<div align="center">

<!-- 👇 在这里替换成你的封面 Banner 图（就用我们之前设计的那张海报） -->
<img src="./assets/banner_zh.png" alt="ClipTalk Banner" width="100%" />

# ClipTalk ✂️

### 通过对话完成视频剪辑的 AI Agent

**说句话，片子就剪好了。**

[![License](https://img.shields.io/badge/license-GPL%20v3-blue)](./LICENSE)
[![Stars](https://img.shields.io/github/stars/GML-MMGroup/ClipTalk?style=social)](https://github.com/GML-MMGroup/ClipTalk)
[![Version](https://img.shields.io/badge/version-1.0.0-brightgreen)](https://github.com/GML-MMGroup/ClipTalk/releases)
[![Discord](https://img.shields.io/badge/Discord-Join-5865f2)](https://discord.gg/yourlink)

[English](./README.md) · **简体中文** · [在线体验](#) · [使用文档](#)

</div>

---

## 📰 最新动态

- **[2026-XX-XX]** 🎉 ClipTalk 正式开源！
- **[2026-XX-XX]** 🚀 发布声纹识别功能 —— 在数小时的素材中按人名精准定位任意说话人。
- **[2026-XX-XX]** ✨ 新增直播高光一键生成能力。

<!-- 后续更新持续追加到这里 -->

---

## 🌟 案例展示 —— 一句话，一次剪辑

> 以下均为 ClipTalk 通过单条指令完成的真实剪辑任务。
> <!-- 在这里放不同场景的剪辑案例，建议用 GIF 对比：原始素材 → 指令 → 成片 -->

<table>
  <tr>
    <td align="center"><b>📰 新闻播报高光</b><br/><img src="./assets/cases/news-broadcast.gif" width="240"/></td>
    <td align="center"><b>🧵 手工教程剪辑</b><br/><img src="./assets/cases/diy-craft.gif" width="240"/></td>
    <td align="center"><b>📦 产品讲解</b><br/><img src="./assets/cases/product.gif" width="240"/></td>
  </tr>
  <tr>
    <td align="center"><b>🏢 会议录像</b><br/><img src="./assets/cases/meeting.gif" width="240"/></td>
    <td align="center"><b>🎵 音乐表演高光</b><br/><img src="./assets/cases/music.gif" width="240"/></td>
    <td align="center"><b>⚽ 体育赛事高光</b><br/><img src="./assets/cases/sports.gif" width="240"/></td>
  </tr>
</table>

---

## 💡 ClipTalk 是什么？

ClipTalk 是一个**视频剪辑 AI Agent**。你不需要在时间轴上拖拽素材，
也不需要在几小时的录像里反复拉进度条 —— 只需用自然语言描述需求，
Agent 会完成全部流程：**理解素材 → 定位目标内容 → 规划剪辑方案 →
执行剪切 → 输出成片。**

<div align="center">
  <img src="./assets/showcase/conversational-highlight-editing-preview.gif" alt="ClipTalk 对话式视频剪辑流程演示" width="90%" />
  <br />
  <sub><b>“从最精彩的片段生成一条高光。”</b> —— ClipTalk 分析素材、展示事件时间轴，并交付多个 AI 剪辑版本。</sub>
</div>

<br />

> 上传一段长视频，用一句话描述想要的内容，ClipTalk 会理解素材、规划
> 剪辑、调用相应工具，并直接交付剪好的成片。

它不是简单的字幕关键词检索。ClipTalk 能真正**理解画面里是谁、
谁在说话、在聊什么** —— 综合运用语音识别、声纹识别、人脸检测和
话题分割 —— 所以哪怕是多人出镜的 1 小时录像，*"把王总的画面剪
出来"* 这样的指令也能直接生效。

---

## ✨ 核心特性

### 1. 💬 对话式剪辑
描述任务，直接拿结果。不需要任何时间轴操作技能 —— *"把他说话的
画面合并"* 一句话就是一次完整的剪辑流程。还可以持续追加指令：
*"再剪短一点"*、*"从讲价格的部分开始"*。

### 2. 🧠 素材内容理解
剪辑开始前，ClipTalk 会先对视频建立结构化理解：
- **语音转写** —— 带时间戳的完整字幕
- **声纹识别** —— 不只是"有人在说话"，而是"*谁*在说话"
- **人脸检测与追踪** —— 定位每个人的全部出镜片段
- **话题分割** —— 找到"新品讲解"从哪一秒开始、到哪一秒结束

### 3. 🎯 指定人物剪辑
说出一个名字，就能拿到 TA 的全部片段。*"把王总的画面剪出来"* 会
结合人脸与声纹双重识别，从整段素材中提取目标人物所有出镜和发言
的片段。

### 4. 🗣️ 说话片段合并
自动检测并合并指定说话人的全部发言片段，去除静音、口水词和其他
人的发言 —— 把散落在各处的片段拼成一条连贯的成片。

### 5. ⚡ 一句话生成高光
*"剪一个 60 秒高光切片"* —— Agent 会对素材的情绪能量、金句和
观众反应打分，自动拼出一条节奏紧凑、带字幕、可直接发布的高光
视频。

### 6. 🤖 Agent 驱动的多步剪辑
每条指令背后，Agent 会**自动规划并执行一条工具流水线** —— 读取
字幕、识别声纹、定位片段、执行剪辑 —— 并把工作日志实时逐步展示
给你，全程透明，没有黑箱。

### 7. 🎞️ 可编辑的时间轴输出
结果不会消失在黑箱里。每次剪辑都会落到一条**多轨时间轴**上
（视频 / 音频 / 字幕），你可以检查每一处剪切点、微调边界、重新
渲染 —— AI 干重活，最终决定权在你手里。

### 8. 🔄 持续迭代优化
对结果不满意？继续说就行。每条指令都基于上一步的结果 —— *"删掉
第二段"*、*"加上字幕"*、*"导出竖屏版"* —— 不需要从头再来。

### 9. 📚 为长素材而生
专治难啃的素材：1 小时直播、多人圆桌、全天活动录像。素材越长
越乱，ClipTalk 帮你省下的时间就越多。

### 10. 🔌 模块化工具系统
语音转写、声纹识别、人脸检测、渲染合成都是统一 Agent 接口下的
可插拔工具 —— 可以替换成你偏好的模型，也可以自行扩展工具箱。

---

## 🛠️ Agent 的工具箱

| 工具 | 能力 |
|------|------|
| 📝 **语音转写** | 语音转文字，精确到词级时间戳 |
| 🔊 **声纹识别** | 通过声纹识别并追踪每一位说话人 |
| 👤 **人脸追踪** | 检测并追踪每个人的全部出镜片段 |
| 🧭 **话题分割** | 将素材切分为语义段落与话题 |
| ⭐ **高光打分** | 按情绪能量、金句、观众反应为片段打分排序 |
| ✂️ **剪辑执行** | 帧级精度的剪切与合并 |
| 🎞️ **合成渲染** | 将片段、字幕、音频合成为最终成片 |

---

## 🏗️ 工作原理

```
💬 "把王总的画面剪出来"
        ↓
🤖 Agent 规划剪辑方案
        ↓
📝 读取字幕 → 🔊 识别声纹 → 👤 人脸追踪 → 🧭 定位片段
        ↓
✂️ 执行剪辑 → 🎞️ 合成渲染 → ✅ 完成
```

一句指令进，成片出 —— 每一步都在 Agent 工作日志中清晰可见。

---

## 🚀 快速开始

### ✅ 环境要求

- 下方本机安装流程以 **Linux x86_64** 为主要测试环境；Windows 建议使用
  **WSL2**，其他平台建议优先使用 Docker
- **Python 3.10 或 3.11**（仓库固定使用的 PyTorch 2.2 运行时不面向更新的
  Python 版本）
- 已安装 Python `venv` 模块，系统能够直接调用 **FFmpeg** 和 **ffprobe**
- 一个支持图像输入、兼容 OpenAI Chat Completions 接口的视觉语言模型服务
  （已支持火山方舟）；打开界面不需要 API Key，但首次分析前必须配置
- 默认 SenseVoice 与 VAD 模型建议至少预留 **2 GiB 可用磁盘空间**；启用
  说话人分段后还需要额外空间

安装前先确认本机环境：

```bash
python3 --version       # 必须为 3.10.x 或 3.11.x
python3 -m venv --help  # 确认已安装 venv 模块
ffmpeg -version
ffprobe -version
```

### 💻 本机运行

```bash
git clone https://github.com/GML-MMGroup/ClipTalk.git
cd ClipTalk

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

# CPU 版本（首次部署推荐）
python -m pip install -r requirements-audiovisual.txt

# 前台启动 Web 服务
bash start.sh
```

终端显示 Uvicorn 已启动后，直接打开终端输出的完整地址。本机运行时地址
格式为 `http://127.0.0.1:<HIGHLIGHT_PORT>`；默认端口是 `5180`，但终端显示
的始终是当前配置实际使用的端口。

#### 配置模型

点击右上角的**设置**，依次配置：

1. **视觉模型**：服务商、API Key、Base URL，以及支持图像理解的模型。
2. **剪辑规划模型**：可以复用视觉模型，也可以单独配置文本 LLM，用于
   镜头筛选、顺序规划和多版本成片。

保存前先在设置面板中点击**验证连接并读取列表**。密钥保存在本机 `data/`
目录中，公开设置接口不会返回完整密钥。

#### 创建第一个剪辑任务

上传一个视频、描述需要的高光并确认要求，即可创建第一个任务。语音模型
未就绪时界面仍可打开；可选语音分析准备失败，也不会阻止纯视觉分析。

---

## ⚙️ 部署与配置

### ⚡ 本机安装使用 NVIDIA GPU

如果机器配有 NVIDIA GPU 且驱动支持 CUDA 12.1，请将 CPU 依赖命令替换为：

```bash
python -m pip install -r requirements-audiovisual-cu121.txt
```

请在全新的虚拟环境中二选一安装 CPU 或 CUDA 依赖，不要重复安装。仓库提供
的 Docker 镜像默认是 CPU 版本；GPU 容器需要另行构建 CUDA 镜像并配置
NVIDIA Container Toolkit。

### 🎙️ 语音模型与首次启动

服务会在后台启动 SenseVoice 工作进程，Web 界面不会等待它完成。缺少的
SenseVoice 和 VAD 模型会从 ModelScope 自动下载到 `./data/models`，因此
第一次使用语音辅助分析可能需要更长时间。也可以在启动前下载并验证模型：

```bash
# 使用 HIGHLIGHT_SENSEVOICE_DEVICE 指定的设备（默认 auto）
python tools/prepare_speech_models.py

# 同时准备说话人任务需要的 CAM++ 模型
python tools/prepare_speech_models.py --with-speakers
```

### 🐳 Docker 运行

```bash
git clone https://github.com/GML-MMGroup/ClipTalk.git
cd ClipTalk
cp .env.example .env
docker compose up --build
```

等待容器进入健康状态，然后在 Docker 所在电脑上打开
`http://127.0.0.1:<CLIPTALK_PORT>`，在**设置**中配置视觉模型与剪辑规划
模型。`CLIPTALK_PORT` 读取自 `.env`，默认值为 `5180`。Docker 会把上传
素材、模型缓存、任务记录和成片输出保存在由 Docker 管理的
`cliptalk-data` 数据卷中。`docker compose down` 会保留数据；执行
`docker compose down -v` 会永久删除该数据卷。

旧版本使用 `./data` 目录挂载。升级不会删除该目录，但其中的历史任务不会
自动导入新的命名卷；迁移前请先备份。

常用检查命令：

```bash
docker compose ps
docker compose logs --tail=200 cliptalk
```

Apple Silicon 或其他非 amd64 主机可能需要通过
`DOCKER_DEFAULT_PLATFORM=linux/amd64` 使用 Linux/amd64 模拟运行固定版本的
PyTorch 镜像，速度会低于原生 Linux x86_64 环境。

### 🌐 应该打开哪个地址？

| ClipTalk 运行位置 | 应打开的地址 |
| --- | --- |
| 本机运行，与浏览器在同一台电脑 | Uvicorn 输出的地址：`http://127.0.0.1:<HIGHLIGHT_PORT>` |
| Docker，与浏览器在同一台电脑 | `http://127.0.0.1:<CLIPTALK_PORT>` |
| 本机运行在远程服务器 | `http://<服务器 IP>:<HIGHLIGHT_PORT>` |
| Docker 运行在远程服务器 | `http://<服务器 IP>:<CLIPTALK_PORT>` |

Docker 默认只绑定 `127.0.0.1`。如需远程访问 Docker，请编辑 `.env`，同时
配置监听地址和访问令牌：

```bash
CLIPTALK_BIND_ADDRESS=0.0.0.0
HIGHLIGHT_ACCESS_TOKEN=请替换为足够长的随机令牌
```

非 Docker 的远程部署则需要在运行 `bash start.sh` 前设置
`HIGHLIGHT_HOST=0.0.0.0` 和相同的访问令牌。随后在服务器防火墙或云安全组
中放行实际配置的 `HIGHLIGHT_PORT`，并访问
`http://<服务器 IP>:<HIGHLIGHT_PORT>/?token=<你的令牌>`。不要在其他设备上访问
`127.0.0.1`，因为它始终指向当前设备自身。若服务需要暴露到公网，建议
使用带身份验证的 HTTPS 反向代理，不要直接公开开发服务器。

如果 Docker 的默认端口已被占用，可在 `.env` 中将 `CLIPTALK_PORT` 改为
任意空闲端口，然后使用该端口访问。

### 🔧 可选环境变量

推荐直接通过界面配置视觉模型与规划模型。无界面部署时，可以复制仓库
提供的配置模板，再按需修改；`start.sh` 会直接读取该文件，Docker Compose
也会把它传入容器：

```bash
cp .env.example .env
```

常用配置包括 `HIGHLIGHT_HOST`、`HIGHLIGHT_PORT`、
`HIGHLIGHT_DATA_ROOT`、`VISION_*`、`LLM_*` 以及 SenseVoice 的设备和
模型选项。不要提交 `.env` 或任何 API Key。

使用与启动时相同的端口查看本机服务状态：

```bash
SERVICE_PORT="${HIGHLIGHT_PORT:-5180}"  # Docker 请改用 CLIPTALK_PORT
curl -s "http://127.0.0.1:${SERVICE_PORT}/api/health" | python -m json.tool
```

`ok: true` 只表示 HTTP 服务存活。开始分析前，还应确认
`mediaToolsReady: true` 和 `analysisReady: true`。语音属于辅助信号：模型
下载期间 `speechReady` 可以为 false，不会阻止纯视觉分析。

如果无法连接，请确认启动进程仍在运行、查看终端错误信息，并检查启动时
使用的主机与端口是否和浏览器地址一致。如果 FFmpeg 已加入 `PATH` 但仍未
识别，可在 `.env` 中将 `FFMPEG_BIN` 和 `FFPROBE_BIN` 设置为绝对路径。

正常使用无需安装 Node.js：浏览器所需文件已经包含在 `static/` 中。只有
重新构建 `package.json` 中定义的前端动效或图标包时才需要 Node.js。

---

## 🤝 参与贡献

欢迎任何形式的贡献！请先阅读[贡献指南](#)。

## 📄 开源协议

本项目基于 **[GNU General Public License v3.0](./LICENSE)** 开源。

你可以自由地运行、研究、分享和修改本软件。任何分发的衍生作品也必须
以 GPL v3 协议发布，以保证软件对所有用户保持自由。完整条款请见
[LICENSE](./LICENSE) 文件。

## 💬 社区交流

- [Discord](#) · [Twitter/X](#) · [微信群](#)

<div align="center">

**⭐ 如果 ClipTalk 对你有帮助，欢迎点一个 Star！**

Made with ❤️ by the ClipTalk Team

</div>
