# ClipTalk User Guide: From Upload to a Finished Edit

> This guide assumes deployment is already complete (native or Docker) and the service is running locally.
> For deployment steps, see the root [README.md](../README.md) and [CONFIGURATION.md](./CONFIGURATION.md).

---

## Step 0: Make sure the service is running

- **Docker deployment**: open <http://127.0.0.1:5180> in your browser (use the port you actually configured).
- **Native deployment**: run `./start.sh`, then open the URL printed in the terminal.

The first time you open the page you will be asked for the **access token** (the `HIGHLIGHT_ACCESS_TOKEN` from your `.env`). The browser remembers it after the first entry.

---

## Step 1: Configure the vision model (required, one time only)

ClipTalk relies on a **vision model (VLM)** to understand frames, discover events, and refine shot boundaries. A separate **text LLM (optional)** plans shot selection and ordering; if it is not configured, the VLM is reused automatically.

1. Click **Settings** in the top-right corner of the page.
2. Fill in the vision model configuration:
   - **Provider**: `ark` (Volcano Ark), `openai`, or any OpenAI Chat Completions compatible endpoint;
   - **API Key**: your key;
   - **Model**: a multimodal model ID from your provider that **accepts image input**;
   - **Base URL**: the Ark default is `https://ark.cn-beijing.volces.com/api/v3`; for OpenAI-compatible providers, follow their documentation.
3. (Optional) Configure a separate planning LLM, or simply choose to reuse the vision model.
4. Save. Keys saved through the UI are stored in `data/vision-settings.json` (permission 0600) and never enter the code repository.

> Alternatively, set `VISION_API_KEY` / `VISION_MODEL` etc. in `.env` and restart the service — both approaches are equivalent.

---

## Step 2: Upload a video

1. Return to the main screen (a chat-style interface).
2. Click the upload entry (or **drag and drop** a video file into the chat area).
3. Wait for the upload to finish. The page will show "**Video ready**".
   - The default per-file limit is **8 GiB**. Files above 16 MiB automatically use chunked upload with **resumable transfer**, so a dropped connection or page refresh will not force you to start over.

> Tip: for your first run, pick a **5–15 minute** clip to get familiar with the workflow quickly.

---

## Step 3: Choose an editing workflow

Once the video is ready, the assistant shows a **task settings** card with two paths:

**Option A: Let AI recommend**
Describe the outcome you want in the recommendation box (for example: "Keep the product introduction and cut it into one complete video"), then click **Let AI recommend**. AI only recommends a workflow and will ask you to confirm when the intent is ambiguous — it never starts a task on its own.

**Option B: Choose manually (four workflows)**

| Workflow | Best for | What to fill in before starting |
| --- | --- | --- |
| ⚡ **Highlight editing** | Watch the whole video, auto-discover exciting events, produce several highlight versions | Highlight theme (optional), target duration (optional), number of versions (default 3) |
| 🔍 **Content search** | Find actions, objects, scenes, dialogue, on-screen text, or sounds by description | A search query, e.g. "find the shots of frying an egg" |
| 👤 **Person-based editing** | Extract every segment where a specific person appears | Nothing — just start person recognition |
| 🔊 **Speaker-based editing** | Separate voices and extract everything a specific speaker says | Expected number of speakers (choose "auto" if unsure) |

You can also set the **source scope**: full video / opening / first half / middle / second half / ending / custom start–end times. To edit only a middle portion, choose "custom" and enter the range.

Click the corresponding button (e.g. **Start highlight analysis** / **Start search**) to begin analysis.

---

## Step 4: Wait for analysis to finish

- The system automatically runs: speech recognition (SenseVoice) → frame understanding via the VLM → event/segment organization.
- **The first run downloads local model weights** (SenseVoice, OCR, recognition models — several GiB in total). Download time depends on your network; afterwards they are cached in the data directory and reused.
- On a CPU deployment, analysis time scales with video length — please be patient with long videos. The page shows per-stage progress.

---

## Step 5: Review the AI's analysis

After analysis you enter the **review stage**. What you review depends on the workflow:

- **Highlight editing**: inspect the "event & shot timeline", confirm the discovered events and inner shots, and **add good shots to the final-cut list**.
- **Content search**: preview the **matched segments** and tick the ones you actually want.
- **Person-based editing**: correct the person groups on the **person cards** (merge/split incorrect groups), pick the target person(s), and confirm the appearance scope ("any person appears" or "all persons on screen together").
- **Speaker-based editing**: **listen** to each speaker group, correct them, choose the target speaker, and confirm which speech segments to keep.

Keep what you want, drop the rest — this determines the final cut.

---

## Step 6: Generate versions and preview

1. After confirming the list, move to the **generate version / compose video** stage.
2. The system composes the video automatically according to your confirmed scope (subtitles rendered included).
3. Highlight editing produces **multiple edited versions** by default (3), which you can **preview** and compare one by one.

---

## Step 7: Export and download

1. Once a preview looks good, click **Download** to save the final video; you can also click **Export new version** to regenerate after adjustments.
2. The downloaded file is the final deliverable.
3. All task data (uploads, caches, models, outputs) lives in the data directory:
   - Native deployment: `data/` inside the project;
   - Docker deployment: the named volume `cliptalk_cliptalk-data` (mounted at `/app/data` in the container).

---

## Step 8 (optional): Refine through conversation

A generated cut is not the end of the conversation. Keep adjusting in natural language, for example:

- "Make it shorter"
- "Start from the part about pricing"
- "Only keep the segments with audience reactions"

ClipTalk re-plans and regenerates on top of the existing analysis.

---

## FAQ

**Q: Clicking start says the model is not configured?**
Open "Settings" in the top-right corner and complete the VLM configuration; or check that `VISION_API_KEY` and `VISION_MODEL` are set in `.env` and restart the service.

**Q: The first analysis is very slow?**
Local model weights are likely downloading (several GiB, first time only). Watch the terminal for progress; afterwards they are cached and reused.

**Q: Which video formats are supported?**
Common formats such as MP4/MOV/MKV all work (decoded by the bundled FFmpeg). For videos with unusual codecs, transcode to H.264 MP4 first.

**Q: How do I stop / restart the service?**
- Docker: `docker compose down` to stop; `docker compose up -d` to start again — data is preserved.
- Native: terminate the `start.sh` process and run it again.

**Q: How do I wipe all task data?**
With Docker, `docker compose down -v` removes the data volume (**irreversible** — uploads, caches, and exports are all lost).

---

*For deployment and configuration details, see [CONFIGURATION.md](./CONFIGURATION.md).*
