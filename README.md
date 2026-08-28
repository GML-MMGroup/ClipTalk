<div align="center">

<!-- 👇 Replace this with your cover banner -->

<img src="./assets/banner.png" alt="ClipTalk Banner" width="100%" />

# ClipTalk ✂️

### An AI Agent That Edits Videos Through Conversation

**Just say it. It's edited.**


**English** · [简体中文](./README_zh.md) 
</div>

---

## 📰 News

* **[2026-08-28]** 🎬 Upgraded the **multimodal editing workspace** with reusable content-search results, person/speaker workflows, voiceprint-based clipping, and an editable fine-cut timeline; also streamlined CPU/GPU deployment.
* **[2026-08-20]** 🎯 Added **Face-Matched Editing** and **Topic-Based Editing**, enabling target-person retrieval and topic-driven clip extraction.
* **[2026-08-12]** 🚀 Optimized the timeline display and added support for switching to **vertical creation mode**.
* **[2026-07-20]** ✨ Added the **Highlight Editing Agent** for automatic highlight clip extraction.
* **[2026-07-10]** 🎉 ClipTalk is now **open-source**!

<!-- Keep adding future updates here -->

---

## 🗺️ Roadmap

ClipTalk is actively evolving toward a more powerful conversational video editing experience.

* [x] 💬 **Conversational Editing Infrastructure**
* [x] ⚡ **Highlight Editing Agent**
* [x] 👤 **Face-Matched Editing** — Find a target person and extract the segments where they appear on screen.
* [x] 🔊 **Voiceprint-Based Editing** — Identify a target speaker and extract the segments where they are speaking.
* [x] 🧭 **Topic-Based Editing** — Understand the content and extract segments around a specific topic.
* [x] 🎞️ **Editable Timeline** — Further edit and fine-tune AI-generated results directly on the timeline.


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
    <td align="center"><b>🔥 Live PK Reaction Highlights</b><br/><img src="./assets/cases/music.gif" alt="AI-edited live PK reaction highlights" width="240"/></td>
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

Requires Linux x86_64 (or WSL2), Python 3.10/3.11, FFmpeg, and ffprobe.

```bash
git clone https://github.com/GML-MMGroup/ClipTalk.git
cd ClipTalk

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-audiovisual.txt
bash start.sh
```

### Models

* **VLM · Required** — understands frames, finds events, and refines shot boundaries.
* **LLM · Optional** — plans shot selection, ordering, and alternative edits; it can reuse the VLM.
* **SenseVoice · Optional/local** — adds timestamped speech, emotion, and sound evidence; visual-only analysis remains available.

Open the URL printed in the terminal. In **Settings**, configure the VLM and optionally a separate LLM, then upload a video and describe the edit you want.

---

## ⚙️ Deployment

### 🐳 Docker

```bash
git clone https://github.com/GML-MMGroup/ClipTalk.git
cd ClipTalk
cp .env.example .env
docker compose up --build
```

Open the URL printed in the terminal, then configure the vision and planning models in **Settings**.

### 🔧 Optional setup

- **NVIDIA GPU:** install `requirements-audiovisual-cu121.txt` instead of the CPU requirements when the driver supports CUDA 12.1.
- **SenseVoice:** optional local speech models download automatically on first use; visual-only analysis works without them.
- **Environment variables:** see [`.env.example`](./.env.example). Never commit `.env` or API keys.

<details>
<summary><strong>Remote deployment and security</strong></summary>

For remote access, set `HIGHLIGHT_HOST=0.0.0.0` for a native install or `CLIPTALK_BIND_ADDRESS=0.0.0.0` for Docker. Configure a strong `HIGHLIGHT_ACCESS_TOKEN`, allow the selected port, and use an authenticated HTTPS reverse proxy for internet-facing deployments.

</details>

---
## 🤝 Contributing

Pull Requests are always welcome. Contribute code, new features, bug fixes, or other improvements to AdCraft and become a project contributor.


## 💬 Contact

For questions, feedback, collaboration, or other inquiries, feel free to contact us:

Ma Fei — mafei@gml.ac.cn
Xu Hongbo — xuhongbo@gml.ac.cn

<div align="center">

⭐ If you find ClipTalk useful, please give us a star!

Made with ❤️ by GML-MMGroup

</div>
