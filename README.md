<div align="center">

<!-- 👇 在这里替换成你的封面 Banner 图（就用我们之前设计的那张海报） -->
<img src="./assets/banner.png" alt="ClipTalk Banner" width="100%" />

# ClipTalk ✂️

### An AI Agent That Edits Videos Through Conversation

**Just say it. It's edited.**

[![License](https://img.shields.io/badge/license-GPL%20v3-blue)](./LICENSE)
[![Stars](https://img.shields.io/github/stars/GML-MMGroup/ClipTalk?style=social)](https://github.com/GML-MMGroup/ClipTalk)
[![Version](https://img.shields.io/badge/version-1.0.0-brightgreen)](https://github.com/GML-MMGroup/ClipTalk/releases)
[![Discord](https://img.shields.io/badge/Discord-Join-5865f2)](https://discord.gg/yourlink)

**English** · [简体中文](./README_zh.md) · [Live Demo](#) · [Documentation](#)

</div>

---

## 🎥 See It In Action

<!-- 👇 在这里放核心演示 GIF：用户输入一句话 → Agent 执行 → 成片输出 -->
<div align="center">
  <img src="./assets/demo.gif" alt="ClipTalk Demo" width="90%" />
</div>

<br/>

> Upload a 1-hour livestream, then just type: *"Merge all his speaking
> clips"*, *"Cut out Mr. Wang's scenes"*, *"Clip the product intro"*, or
> *"Make a 60s highlight"* — ClipTalk understands your footage, plans the
> edit, calls the right tools, and delivers the finished clips.

---

## 📰 News

- **[2026‑07‑10]** 🎉 ClipTalk is now open‑source!
- **[2026‑08‑12]** 🚀 Added one‑command highlight generation for videos.
- **[2026‑08‑12]** ✨ Added conversational editing feature.

<!-- 后续更新持续追加到这里 -->

---

## 🌟 Showcase — One Sentence, One Edit

> Real editing tasks completed by ClipTalk with a single instruction.
> <!-- 在这里放不同场景的剪辑案例，建议用 GIF 对比：原始素材 → 指令 → 成片 -->

<div align="center">
  <img src="./assets/showcase/conversational-highlight-editing-preview.gif" alt="ClipTalk conversational highlight editing workflow" width="900" />
  <br />
  <sub><b>“Make a highlight from the best moments.”</b> — ClipTalk analyzes the footage, presents the event timeline, and delivers multiple AI-edited versions.</sub>
</div>

<br />

<table>
  <tr>
    <td align="center"><b>📰 News &amp; Broadcast Highlights</b><br/><img src="./assets/cases/news-broadcast.gif" width="240"/></td>
    <td align="center"><b>🧵 DIY &amp; Craft Tutorials</b><br/><img src="./assets/cases/diy-craft.gif" width="240"/></td>
    <td align="center"><b>📦 Product Demos</b><br/><img src="./assets/cases/product.gif" width="240"/></td>
  </tr>
  <tr>
    <td align="center"><b>🏢 Lifestyle Vlogs </b><br/><img src="./assets/cases/meeting.gif" width="240"/></td>
    <td align="center"><b>🎵 Music Performance Highlights</b><br/><img src="./assets/cases/music.gif" width="240"/></td>
    <td align="center"><b>⚽ Sports Highlights</b><br/><img src="./assets/cases/sports.gif" width="240"/></td>
  </tr>
</table>

---

## 💡 What is ClipTalk?

ClipTalk is an **AI video-editing agent**. You don't drag clips on a
timeline or scrub through hours of footage — you just describe what you
want in natural language, and the agent handles the entire process:
**understanding the footage → locating the target content → planning the
edit → executing cuts → delivering the final clips.**

It's not a keyword search over subtitles. ClipTalk actually **understands
who is on screen, who is speaking, and what they are talking about** —
combining speech recognition, voiceprint identification, face detection,
and topic segmentation — so instructions like *"cut out Mr. Wang's
scenes"* just work, even in a multi-speaker 1-hour recording.

---

## ✨ Core Features

### 1. 💬 Conversational Editing
Describe the task, get the result. No timeline skills required —
*"merge all his speaking clips"* is a complete editing workflow in one
sentence. Follow up with refinements: *"make it shorter"*, *"start from
the part about pricing"*.

### 2. 🧠 Content-Aware Footage Understanding
ClipTalk builds a structured understanding of your video before editing:
- **Speech transcription** — full subtitles with timestamps
- **Voiceprint ID** — knows *who* is speaking, not just *that* someone is
- **Face detection & tracking** — locates every person's on-screen segments
- **Topic segmentation** — finds where the product intro starts and ends

### 3. 🎯 Person-Targeted Clipping
Name a person, get their clips. *"Cut out Mr. Wang's scenes"* combines
face and voice identification to extract every segment where the target
person appears or speaks — across the entire footage.

### 4. 🗣️ Speech Merge
Automatically detect and merge all segments where a specific speaker is
talking, removing silence, filler, and other speakers' turns — turning
scattered moments into one continuous clip.

### 5. ⚡ One-Command Highlights
*"Make a 60s highlight"* — the agent scores the footage for energy,
key statements, and audience reactions, then assembles a tight highlight
reel with subtitles, ready to publish.

### 6. 🤖 Agent-Orchestrated Multi-Step Edits
Behind every instruction, the agent **plans and executes a tool
pipeline** — reading subtitles, running voice ID, locating segments,
cutting clips — and shows you its working log in real time, step by step,
with nothing hidden.

### 7. 🎞️ Editable Timeline Output
Results don't disappear into a black box. Every edit lands on a
**multi-track timeline** (video / audio / subtitles) where you can
inspect the cuts, nudge boundaries, and re-render — AI does the heavy
lifting, you keep the final say.

### 8. 🔄 Iterative Refinement
Not happy with a result? Just keep talking. Each instruction builds on
the previous state — *"remove the second clip"*, *"add subtitles"*,
*"export vertical for mobile"* — no need to start over.

### 9. 📚 Built for Long Footage
Designed for the hard cases: 1-hour livestreams, multi-speaker panels,
full-day event recordings. The longer and messier the footage, the more
time ClipTalk saves.

### 10. 🔌 Modular Tool System
Transcription, voiceprint, face detection, and rendering are pluggable
tools behind a unified agent interface — swap in your preferred models
or extend the toolbox with your own.

---

## 🛠️ The Agent's Toolbox

| Tool | Capability |
|------|-----------|
| 📝 **Transcriber** | Speech-to-text with word-level timestamps |
| 🔊 **Voice ID** | Identifies and tracks individual speakers by voiceprint |
| 👤 **Face Tracker** | Detects and tracks every person's on-screen presence |
| 🧭 **Topic Segmenter** | Splits footage into semantic sections and topics |
| ⭐ **Highlight Scorer** | Ranks moments by energy, key statements, and reactions |
| ✂️ **Cutter** | Executes precise, frame-accurate cuts and merges |
| 🎞️ **Compositor** | Assembles clips, subtitles, and audio into the final render |

---

## 🏗️ How It Works
```
💬 "Cut out Mr. Wang's scenes"
↓
🤖 Agent plans the edit
↓
📝 Read subtitles → 🔊 Voice ID → 👤 Face tracking → 🧭 Locate segments
↓
✂️ Cut clips → 🎞️ Compose → ✅ Done
```
One instruction in, finished clips out — every step visible in the
agent's working log.

---

## 🚀 Quick Start

### ✅ Prerequisites

- The native setup below is tested on **Linux x86_64**. On Windows, use
  **WSL2**; on other platforms, Docker is the recommended starting point.
- **Python 3.10 or 3.11** (the pinned PyTorch 2.2 runtime does not target
  newer Python releases)
- Python's `venv` module, plus **FFmpeg** and **ffprobe** available on `PATH`
- A vision-language model endpoint that accepts image input through an
  OpenAI-compatible Chat Completions API (Volcengine Ark is supported) before
  you run the first analysis; an API key is not required merely to open the UI
- About **2 GiB of free disk space** for the default SenseVoice and VAD
  models; more is required when speaker diarization is enabled

Verify the local runtime before installing:

```bash
python3 --version       # must report 3.10.x or 3.11.x
python3 -m venv --help  # confirms that the venv module is installed
ffmpeg -version
ffprobe -version
```

### 💻 Run locally

```bash
git clone https://github.com/GML-MMGroup/ClipTalk.git
cd ClipTalk

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

# CPU (recommended for the first setup)
python -m pip install -r requirements-audiovisual.txt

# Start the web app in the foreground
bash start.sh
```

After the terminal reports that Uvicorn is running, open
**<http://127.0.0.1:5180>** in a browser on the same computer. This is the
default local address, not a universal deployment URL. If you changed
`HIGHLIGHT_PORT`, use the configured port instead.

#### Configure the models

In the top-right corner, choose **Settings** and configure:

1. **Vision model** — provider, API key, base URL, and a model capable of
   understanding images.
2. **Editing planner** — reuse the vision model, or configure a separate
   text LLM for shot selection, ordering, and multi-version planning.

Use **Verify connection and load list** in the settings panel before saving. The
credentials are stored locally under `data/` and are not returned by the
public settings API.

#### Create your first edit

Create the first task by uploading one video, describing the highlight you
want, and confirming the request. The UI can open before the speech model is
ready; visual analysis remains available if optional speech preparation fails.

---

## ⚙️ Deployment and configuration

### ⚡ NVIDIA GPU for a local install

If the machine has an NVIDIA GPU and its driver supports CUDA 12.1, replace
the CPU dependency command with:

```bash
python -m pip install -r requirements-audiovisual-cu121.txt
```

Install only one CPU/CUDA requirement file in a fresh virtual environment.
The supplied Docker image is CPU-only; GPU containers require a separate
CUDA-enabled image and NVIDIA Container Toolkit configuration.

### 🎙️ Speech models and first run

The server starts a SenseVoice worker in the background. The web interface does
not wait for it. Missing SenseVoice/VAD components are downloaded from
ModelScope into `./data/models`, so the first speech-assisted analysis may take
longer. To download and validate them before starting the app, run:

```bash
# Uses the device selected by HIGHLIGHT_SENSEVOICE_DEVICE (default: auto)
python tools/prepare_speech_models.py

# Also prepare CAM++ for speaker-aware tasks
python tools/prepare_speech_models.py --with-speakers
```

### 🐳 Run with Docker

```bash
git clone https://github.com/GML-MMGroup/ClipTalk.git
cd ClipTalk
cp .env.example .env
docker compose up --build
```

Wait until the container is healthy, then open
**<http://127.0.0.1:5180>** on the Docker host and configure the
vision/planning models from **Settings**. Docker stores uploaded media, model
caches, task records, and rendered outputs in the Docker-managed
`cliptalk-data` volume. `docker compose down` preserves that volume;
`docker compose down -v` permanently removes it.

Older releases used a `./data` bind mount. Upgrading does not delete that
directory, but it is not imported into the new named volume automatically;
back it up before migrating existing tasks.

Useful checks:

```bash
docker compose ps
docker compose logs --tail=200 cliptalk
```

On Apple Silicon or another non-amd64 host, the pinned PyTorch image may need
Linux/amd64 emulation (`DOCKER_DEFAULT_PLATFORM=linux/amd64`), which is slower
than running on a native Linux x86_64 host.

### 🌐 Which address should I open?

| Where ClipTalk runs | Address to open |
| --- | --- |
| On the same computer as the browser | `http://127.0.0.1:5180` |
| On a remote server or VM | `http://<server-ip>:5180` |
| Local run with a custom `HIGHLIGHT_PORT` | Replace `5180` with that port |
| Docker with a custom `CLIPTALK_PORT` | Replace `5180` with that port |

Docker binds to `127.0.0.1` by default. For remote Docker access, edit `.env`
and set both a bind address and an access token:

```bash
CLIPTALK_BIND_ADDRESS=0.0.0.0
HIGHLIGHT_ACCESS_TOKEN=replace-with-a-long-random-token
```

For a non-Docker remote deployment, set `HIGHLIGHT_HOST=0.0.0.0` and the same
access token before running `bash start.sh`. Then allow TCP port `5180` in the
server firewall/security group and open
`http://<server-ip>:5180/?token=<your-token>`. Do not use `127.0.0.1` from
another device—it always points back to that device itself. For an
internet-facing deployment, put ClipTalk behind an authenticated HTTPS reverse
proxy instead of exposing the development server directly.

If port `5180` is already in use with Docker, set `CLIPTALK_PORT=8080` in
`.env` and open `http://127.0.0.1:8080`.

### 🔧 Optional environment configuration

The UI is the recommended place to configure the vision and planning models.
For headless deployments, copy the supplied template and edit only the values
you need. `start.sh` reads this file directly, and Docker Compose passes it
into the container:

```bash
cp .env.example .env
```

Common options include `HIGHLIGHT_HOST`, `HIGHLIGHT_PORT`,
`HIGHLIGHT_DATA_ROOT`, `VISION_*`, `LLM_*`, and the SenseVoice device/model
settings. Do not commit `.env` or API keys.

Inspect the default local service with:

```bash
curl -s http://127.0.0.1:5180/api/health | python -m json.tool
```

`ok: true` means that the HTTP service is alive. Before starting an analysis,
also expect `mediaToolsReady: true` and `analysisReady: true`. Speech is
auxiliary: `speechReady` can remain false while models download, without
blocking visual-only analysis.

If the command cannot connect, confirm that the startup process is still
running, inspect its error output, and verify that the host and port match the
address you are opening. If media tools are unavailable despite being on
`PATH`, set `FFMPEG_BIN` and `FFPROBE_BIN` to their absolute paths in `.env`.

No Node.js build is required for normal use—the browser assets are already
included in `static/`. Node.js is needed only when rebuilding the optional
frontend animation/icon bundles defined in `package.json`.

## 🤝 Contributing
We welcome contributions of all kinds! Please see our Contributing Guide to get started.


⭐ If you find ClipTalk useful, please give us a star!

Made with ❤️ by the ClipTalk Team

</div>
