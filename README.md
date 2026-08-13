<div align="center">

<!-- 👇 Replace this with your cover banner -->

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

## 📰 News

* **[2026-08-12]** 🚀 Optimized the timeline display and added support for switching to **vertical creation mode**.
* **[2026-07-20]** ✨ Added the **Highlight Editing Agent** for automatic highlight clip extraction.
* **[2026-07-10]** 🎉 ClipTalk is now **open-source**!

<!-- Keep adding future updates here -->

---

## 🗺️ Roadmap

ClipTalk is actively evolving toward a more powerful conversational video editing experience.

* [x] 💬 **Conversational Editing Infrastructure**
* [x] ⚡ **Highlight Editing Agent**
* [ ] 👤 **Face-Matched Editing** — Find a target person and extract the segments where they appear on screen.
* [ ] 🔊 **Voiceprint-Based Editing** — Identify a target speaker and extract the segments where they are speaking.
* [ ] 🧭 **Topic-Based Editing** — Understand the content and extract segments around a specific topic.
* [ ] 🎞️ **Editable Timeline** — Further edit and fine-tune AI-generated results directly on the timeline.


---

## 🌟 Showcase — One Sentence, One Edit

> Real editing tasks completed by ClipTalk with a single instruction.
>
> <!-- Add GIF comparisons here: source video → instruction → result -->

<table>
  <tr>
    <td align="center"><b>📰 News &amp; Broadcast Highlights</b><br/><img src="./assets/cases/news-broadcast.gif" width="240"/></td>
    <td align="center"><b>🧵 DIY &amp; Craft Tutorials</b><br/><img src="./assets/cases/diy-craft.gif" width="240"/></td>
    <td align="center"><b>📦 Product Demos</b><br/><img src="./assets/cases/product.gif" width="240"/></td>
  </tr>
  <tr>
    <td align="center"><b>🏢 Lifestyle Vlogs</b><br/><img src="./assets/cases/meeting.gif" width="240"/></td>
    <td align="center"><b>🎵 Music Performance Highlights</b><br/><img src="./assets/cases/music.gif" width="240"/></td>
    <td align="center"><b>⚽ Sports Highlights</b><br/><img src="./assets/cases/sports.gif" width="240"/></td>
  </tr>
</table>

---

## 💡 What is ClipTalk?

ClipTalk is an **AI video-editing agent**. You don't drag clips on a timeline or scrub through hours of footage — you just describe what you want in natural language, and the agent handles the entire process:

**understanding the footage → locating the target content → planning the edit → executing cuts → delivering the final clips.**

<div align="center">
  <img src="./assets/showcase/conversational-highlight-editing-preview.gif" alt="ClipTalk conversational highlight editing workflow" width="900" />
  <br />
  <sub><b>“Make a highlight from the best moments.”</b> — ClipTalk analyzes the footage, presents the event timeline, and delivers multiple AI-edited versions.</sub>
</div>

<br />

> Upload a 1-hour video, describe the moments you want, and let ClipTalk understand the footage, plan the edit, and deliver the finished clips.

---

## ✨ Core Features

### 💬 Conversational Editing

Edit videos simply by describing what you want.

From *“make a highlight of the best moments”* to *“cut out the part where they introduce Product X”*, ClipTalk turns natural-language instructions directly into editing actions.

You can also refine the result through follow-up instructions such as *“make it shorter”* or *“start from the part about pricing”*.

### 🎯 Four Core Editing Capabilities

* **⚡ Highlight Extraction** — Automatically identify and extract the most valuable moments from long-form footage to create concise highlight clips.

* **👤 Face-Matched Editing** — Find a target person in the video and extract the segments where that person appears on screen.

* **🧭 Topic-Based Editing** — Locate and extract clips around a specific topic, such as *“cut out the parts where they explain Product X.”*

* **🔊 Voiceprint-Based Editing** — Identify a specific speaker by voiceprint and extract the segments where that person is speaking.

---

## 🏗️ How It Works

ClipTalk turns natural-language editing requests into complete video-editing workflows.

### 👤 Face-Matched Editing

```text
💬 "Cut out all scenes with Mr. Wang"
        ↓
🤖 Agent understands the target person
        ↓
👤 Face matching → Locate all matching on-screen segments
        ↓
✂️ Cut clips → 🎞️ Compose → ✅ Done
```

### ⚡ Highlight Editing

```text
💬 "Make a highlight from the best moments"
        ↓
🤖 Agent analyzes the footage
        ↓
🎬 Understand events → Identify highlight moments → Select key clips
        ↓
✂️ Cut & arrange clips → 🎞️ Compose → ✅ Done
```

### 🧭 Topic-Based Editing

```text
💬 "Cut out the parts where they explain Product X"
        ↓
🤖 Agent understands the target topic
        ↓
📝 Analyze dialogue → 🧭 Segment topics → Locate relevant sections
        ↓
✂️ Cut clips → 🎞️ Compose → ✅ Done
```

**One instruction in, finished clips out.**

---

## 🚀 Quick Start

### ✅ Prerequisites

* The native setup below is tested on **Linux x86_64**. On Windows, use **WSL2**; on other platforms, Docker is the recommended starting point.
* **Python 3.10 or 3.11** (the pinned PyTorch 2.2 runtime does not target newer Python releases)
* Python's `venv` module, plus **FFmpeg** and **ffprobe** available on `PATH`
* A vision-language model endpoint that accepts image input through an OpenAI-compatible Chat Completions API (Volcengine Ark is supported) before you run the first analysis; an API key is not required merely to open the UI
* About **2 GiB of free disk space** for the default SenseVoice and VAD models; more is required when speaker diarization is enabled

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

After the terminal reports that Uvicorn is running, open the exact URL shown in that terminal. For a local installation its format is `http://127.0.0.1:<HIGHLIGHT_PORT>`; the default port is `5180`, but the displayed value always follows your current configuration.

#### Configure the models

In the top-right corner, choose **Settings** and configure:

1. **Vision model** — provider, API key, base URL, and a model capable of understanding images.
2. **Editing planner** — reuse the vision model, or configure a separate text LLM for shot selection, ordering, and multi-version planning.

Use **Verify connection and load list** in the settings panel before saving. The credentials are stored locally under `data/` and are not returned by the public settings API.

#### Create your first edit

Create the first task by uploading one video, describing the highlight you want, and confirming the request. The UI can open before the speech model is ready; visual analysis remains available if optional speech preparation fails.

---

## ⚙️ Deployment and Configuration

### ⚡ NVIDIA GPU for a local install

If the machine has an NVIDIA GPU and its driver supports CUDA 12.1, replace the CPU dependency command with:

```bash
python -m pip install -r requirements-audiovisual-cu121.txt
```

Install only one CPU/CUDA requirement file in a fresh virtual environment.

The supplied Docker image is CPU-only; GPU containers require a separate CUDA-enabled image and NVIDIA Container Toolkit configuration.

### 🎙️ Speech Models and First Run

The server starts a SenseVoice worker in the background. The web interface does not wait for it.

Missing SenseVoice/VAD components are downloaded from ModelScope into `./data/models`, so the first speech-assisted analysis may take longer. To download and validate them before starting the app, run:

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

Wait until the container is healthy, then open `http://127.0.0.1:<CLIPTALK_PORT>` on the Docker host and configure the vision/planning models from **Settings**.

`CLIPTALK_PORT` comes from `.env` and defaults to `5180`.

Docker stores uploaded media, model caches, task records, and rendered outputs in the Docker-managed `cliptalk-data` volume.

`docker compose down` preserves that volume; `docker compose down -v` permanently removes it.

Older releases used a `./data` bind mount. Upgrading does not delete that directory, but it is not imported into the new named volume automatically; back it up before migrating existing tasks.

Useful checks:

```bash
docker compose ps
docker compose logs --tail=200 cliptalk
```

On Apple Silicon or another non-amd64 host, the pinned PyTorch image may need Linux/amd64 emulation (`DOCKER_DEFAULT_PLATFORM=linux/amd64`), which is slower than running on a native Linux x86_64 host.

### 🌐 Which Address Should I Open?

| Where ClipTalk runs          | Address to open                                                 |
| ---------------------------- | --------------------------------------------------------------- |
| Local run, same computer     | The URL printed by Uvicorn: `http://127.0.0.1:<HIGHLIGHT_PORT>` |
| Docker, same computer        | `http://127.0.0.1:<CLIPTALK_PORT>`                              |
| Local run on a remote server | `http://<server-ip>:<HIGHLIGHT_PORT>`                           |
| Docker on a remote server    | `http://<server-ip>:<CLIPTALK_PORT>`                            |

Docker binds to `127.0.0.1` by default. For remote Docker access, edit `.env` and set both a bind address and an access token:

```bash
CLIPTALK_BIND_ADDRESS=0.0.0.0
HIGHLIGHT_ACCESS_TOKEN=replace-with-a-long-random-token
```

For a non-Docker remote deployment, set `HIGHLIGHT_HOST=0.0.0.0` and the same access token before running `bash start.sh`.

Then allow the configured `HIGHLIGHT_PORT` in the server firewall/security group and open:

```text
http://<server-ip>:<HIGHLIGHT_PORT>/?token=<your-token>
```

Do not use `127.0.0.1` from another device — it always points back to that device itself.

For an internet-facing deployment, put ClipTalk behind an authenticated HTTPS reverse proxy instead of exposing the development server directly.

If the default port is already in use with Docker, set `CLIPTALK_PORT` to a free port in `.env`, then open the address using that value.

### 🔧 Optional Environment Configuration

The UI is the recommended place to configure the vision and planning models.

For headless deployments, copy the supplied template and edit only the values you need. `start.sh` reads this file directly, and Docker Compose passes it into the container:

```bash
cp .env.example .env
```

Common options include `HIGHLIGHT_HOST`, `HIGHLIGHT_PORT`, `HIGHLIGHT_DATA_ROOT`, `VISION_*`, `LLM_*`, and the SenseVoice device/model settings.

Do not commit `.env` or API keys.

Inspect a local service with the same port used to start it:

```bash
SERVICE_PORT="${HIGHLIGHT_PORT:-5180}"  # use CLIPTALK_PORT for Docker
curl -s "http://127.0.0.1:${SERVICE_PORT}/api/health" | python -m json.tool
```

`ok: true` means that the HTTP service is alive.

Before starting an analysis, also expect `mediaToolsReady: true` and `analysisReady: true`.

Speech is auxiliary: `speechReady` can remain false while models download, without blocking visual-only analysis.

If the command cannot connect, confirm that the startup process is still running, inspect its error output, and verify that the host and port match the address you are opening.

If media tools are unavailable despite being on `PATH`, set `FFMPEG_BIN` and `FFPROBE_BIN` to their absolute paths in `.env`.

No Node.js build is required for normal use — the browser assets are already included in `static/`.

Node.js is needed only when rebuilding the optional frontend animation/icon bundles defined in `package.json`.

---

## 🤝 Contributing

We welcome contributions of all kinds! Please see our Contributing Guide to get started.

<div align="center">

⭐ If you find ClipTalk useful, please give us a star!

Made with ❤️ by the ClipTalk Team

</div>
