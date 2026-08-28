import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { chromium } from "playwright";


const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const staticRoot = join(projectRoot, "static");
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".woff2": "font/woff2",
};


async function startStubServer() {
  const requests = [];
  let voiceDiscoveryStarted = false;
  let voiceProgressReported = false;
  const server = createServer(async (request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    if (url.pathname === "/api/health") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({
        ok: true,
        visionConfigured: false,
        llmConfigured: false,
        speechEngine: "sensevoice",
        senseVoiceModel: "SenseVoiceSmall",
        speechModelStatus: "ready",
        speechDevice: "cpu",
        ffmpeg: true,
        ffprobe: true,
        keptLibrary: false,
      }));
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/settings/vision") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({
        activeProvider: "ark",
        providers: [
          { id: "ark", name: "火山方舟", description: "豆包及方舟接入点", baseUrl: "https://ark.example/v3", baseUrlEditable: false, thinkingSupported: true, active: true, configured: true, keyConfigured: true, keyHint: "ark-****test", model: "doubao-vision", thinkingType: "disabled", responseFormat: "json_object", models: [{ id: "doubao-vision", recommended: true, supportsVideo: true }], verifiedAt: null },
          { id: "openai", name: "OpenAI", description: "OpenAI 官方多模态模型", baseUrl: "https://api.openai.com/v1", baseUrlEditable: false, thinkingSupported: false, active: false, configured: false, keyConfigured: false, keyHint: "", model: "", thinkingType: "", responseFormat: "json_object", models: [], verifiedAt: null },
          { id: "openai_compatible", name: "兼容接口", description: "其他兼容服务", baseUrl: "", baseUrlEditable: true, thinkingSupported: true, active: false, configured: false, keyConfigured: false, keyHint: "", model: "", thinkingType: "", responseFormat: "json_object", models: [], verifiedAt: null },
        ],
      }));
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/settings/llm") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({
        mode: "reuse_vision", reuseVision: true, activeProvider: "ark",
        providers: [{ id: "ark", name: "火山方舟", description: "豆包及方舟文本模型", protocol: "openai", baseUrl: "https://ark.example/v3", baseUrlEditable: false, thinkingSupported: true, active: true, configured: true, keyConfigured: true, keyHint: "ark-****test", model: "doubao-text", thinkingType: "disabled", responseFormat: "json_object", models: [{ id: "doubao-text", recommended: true, supportsJson: true }], verifiedAt: null }],
      }));
      return;
    }
    if (url.pathname === "/api/jobs") {
      const token = String(request.headers["x-highlight-token"] || "");
      response.setHeader("Content-Type", "application/json");
      if (token !== "browser-test-token") {
        requests.push({ path: url.pathname, token, method: request.method });
        response.statusCode = 401;
        response.end(JSON.stringify({ detail: "访问令牌无效" }));
        return;
      }
      response.setHeader("Set-Cookie", "highlight_session=test-session; Path=/; HttpOnly; SameSite=Strict");
      if (request.method === "POST") {
        const chunks = [];
        for await (const chunk of request) chunks.push(chunk);
        requests.push({ path: url.pathname, token, method: request.method, body: Buffer.concat(chunks).toString("utf8") });
        response.statusCode = 202;
        response.end(JSON.stringify({ job: {
          id: "job_voice_upload", filename: "sample.mp4", taskMode: "content_extract",
          status: "awaiting_content_confirmation", stage: "voice_discovery_available",
          progress: 0, detail: "视频已上传，可以开始识别本视频说话人",
          videoInfo: { duration: 120, width: 1280, height: 720, has_audio: true, frame_rate: 25 },
          request: { entryWorkflow: "voice_discovery", contentInstruction: "识别本视频中的说话人" },
          messages: [], outputs: [], candidates: [], eventGroups: [], recognition: {},
        } }));
        return;
      }
      requests.push({ path: url.pathname, token, method: request.method });
      response.end(JSON.stringify({ jobs: [] }));
      return;
    }
    if (request.method === "POST" && url.pathname === "/api/jobs/job_voice_upload/content-search/voices/discover") {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      requests.push({ path: url.pathname, method: request.method, body: Buffer.concat(chunks).toString("utf8") });
      voiceDiscoveryStarted = true;
      response.statusCode = 202;
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ accepted: true, job: {
        id: "job_voice_upload", filename: "sample.mp4", taskMode: "content_extract",
        status: "running", stage: "voice_discovery", progress: .05,
        detail: "正在识别当前视频中的多个声音",
        videoInfo: { duration: 120, width: 1280, height: 720, has_audio: true, frame_rate: 25 },
        request: { entryWorkflow: "voice_discovery" }, messages: [], outputs: [], candidates: [], eventGroups: [],
        voiceDiscovery: { status: "running" },
      } }));
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/jobs/job_voice_upload/content-search/voices") {
      requests.push({ path: url.pathname, method: request.method });
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({
        voices: [], timeline: [], revision: 0, canUndo: false,
        status: voiceDiscoveryStarted ? {
          status: "running", expectedSpeakerCount: 2,
          ...(voiceProgressReported ? {
            stageProgress: .5, stageCompleted: 1, stageTotal: 2, stageUnit: "个声音",
            detail: "正在整理声音 1/2", currentAction: "正在分析声音 A 的代表发言",
            progressMode: "determinate",
          } : {
            detail: "正在识别当前视频中的多个声音", currentAction: "正在执行说话人分离与声音聚类",
            progressMode: "indeterminate",
          }),
        } : { status: "not_started", expectedSpeakerCount: 0 },
      }));
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/jobs/job_voice_upload/status") {
      requests.push({ path: url.pathname, method: request.method });
      response.setHeader("Content-Type", "application/json");
      if (!voiceDiscoveryStarted || voiceProgressReported) {
        response.end(JSON.stringify({ changed: false, revision: voiceProgressReported ? 2 : 0 }));
        return;
      }
      voiceProgressReported = true;
      response.end(JSON.stringify({ changed: true, revision: 2, job: {
        id: "job_voice_upload", revision: 2, status: "running", stage: "voice_discovery",
        progress: .52, stageProgress: .5, stageCompleted: 1, stageTotal: 2, stageUnit: "个声音",
        detail: "正在整理声音 1/2", currentAction: "正在分析声音 A 的代表发言",
        progressMode: "determinate", voiceDiscovery: { status: "running", expectedSpeakerCount: 2 },
        messages: [
          { id: "voice-user", role: "user", text: "识别当前视频中的说话人", kind: "message" },
          { id: "voice-progress", role: "assistant", text: "已开始分析语音并区分说话人。", kind: "notice" },
        ],
        execution: {
          schemaVersion: 1, status: "running", operation: "speaker_discovery", phase: "voice_discovery",
          active: true, detail: "正在分析声音 A 的代表发言", capabilities: { canCancel: true },
        },
      } }));
      return;
    }
    if (request.method === "POST" && url.pathname === "/api/jobs/job_cancel_test/cancel") {
      requests.push({ path: url.pathname, method: request.method });
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 280));
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ job: {
        id: "job_cancel_test", revision: 2, filename: "cancel.mp4",
        taskMode: "content_extract", workflowKind: "content_search",
        status: "cancelled", stage: "cancelled", progress: .15,
        detail: "任务已取消", currentAction: "任务已取消", progressMode: "stopped",
        videoInfo: { duration: 60, width: 1280, height: 720, has_audio: true, frame_rate: 25 },
        request: { workflowKind: "content_search", contentInstruction: "找出接水的片段" },
        messages: [{ id: "cancelled", role: "assistant", kind: "notice", text: "任务已取消" }],
        outputs: [], outputVersions: [], candidates: [], eventGroups: [], contentSearch: null,
        execution: {
          schemaVersion: 1, status: "cancelled", operation: "content_search", phase: "cancelled",
          active: false, detail: "任务已取消", outcome: "cancelled",
          capabilities: { canCancel: false, canDelete: true },
        },
      } }));
      return;
    }
    if (request.method === "POST" && url.pathname.endsWith("/content-search/target-person")) {
      let body = "";
      for await (const chunk of request) body += chunk;
      requests.push({ path: url.pathname, body: JSON.parse(body || "{}") });
      response.statusCode = 409;
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ detail: "browser test stops after request capture" }));
      return;
    }
    let path;
    if (url.pathname === "/") {
      path = join(staticRoot, "index.html");
    } else if (url.pathname.startsWith("/static/")) {
      path = normalize(join(staticRoot, url.pathname.slice("/static/".length)));
      if (!path.startsWith(staticRoot)) {
        response.statusCode = 403;
        response.end("forbidden");
        return;
      }
    } else {
      response.statusCode = 404;
      response.end("not found");
      return;
    }
    try {
      const metadata = await stat(path);
      if (!metadata.isFile()) throw new Error("not a file");
      response.setHeader("Content-Type", contentTypes[extname(path)] || "application/octet-stream");
      response.end(await readFile(path));
    } catch {
      response.statusCode = 404;
      response.end("not found");
    }
  });
  await new Promise((resolveStarted) => server.listen(0, "127.0.0.1", resolveStarted));
  const address = server.address();
  return {
    requests,
    url: `http://127.0.0.1:${address.port}`,
    close: () => new Promise((resolveClosed, reject) => server.close((error) => error ? reject(error) : resolveClosed())),
  };
}

async function openAuthenticatedWorkspace(page, url) {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.locator("#accessTokenDialog[open]").waitFor({ state: "visible" });
  await page.locator("#accessTokenDialog input").fill("browser-test-token");
  await page.locator("#accessTokenDialog button[type=submit]").click();
  await page.locator('#homeView[data-home-state="empty"]').waitFor({ state: "visible" });
}


test("workspace loads, authenticates without URL token, and opens new-task flow", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#accessTokenDialog[open]").waitFor({ state: "visible" });
    await page.locator("#accessTokenDialog input").fill("browser-test-token");
    await page.locator("#accessTokenDialog button[type=submit]").click();
    await page.locator('#homeView[data-home-state="empty"]').waitFor({ state: "visible" });
    assert.equal(await page.title(), "ClipTalk");
    assert.equal(await page.locator(".home-summary").isVisible(), false);
    assert.equal(await page.locator("#homeTaskGrid .home-empty").count(), 0);
    assert.equal(await page.locator("#homeTaskGrid > *").count(), 1);
    assert.match(await page.locator("#homeView").textContent(), /开始剪辑/);
    assert.match(await page.locator("[data-home-create]").textContent(), /进入后选择视频/);
    assert.doesNotMatch(await page.locator("#homeView").textContent(), /AI VIDEO EDITING WORKSPACE|RECENT TASKS|拖入视频或点击选择素材/);
    assert.ok(stub.requests.some((item) => item.token === ""));
    assert.ok(stub.requests.some((item) => item.token === "browser-test-token"));
    assert.equal(
      await page.evaluate(() => sessionStorage.getItem("cliptalk_access_token")),
      "browser-test-token",
    );
    await page.locator("[data-home-create]").click();
    await page.locator("#uploadView").waitFor({ state: "visible" });
    await page.locator("#uploadForm").waitFor({ state: "visible" });
    assert.equal(await page.locator(".studio").evaluate((node) => node.classList.contains("task-creation-mode")), true);
    assert.equal(await page.locator(".chat-panel").isVisible(), false);
    assert.equal(await page.locator(".panel-resizer-left").isVisible(), false);
    const creationCanvas = await page.locator(".studio").evaluate((node) => {
      const review = node.querySelector(":scope > .review-panel");
      const assistant = node.querySelector(":scope > .chat-panel");
      const style = getComputedStyle(node);
      return {
        studioWidth: node.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
        reviewWidth: review.getBoundingClientRect().width,
        assistantHidden: assistant.getAttribute("aria-hidden"),
      };
    });
    assert.ok(Math.abs(creationCanvas.studioWidth - creationCanvas.reviewWidth) < 4);
    assert.equal(creationCanvas.assistantHidden, "true");
    await page.evaluate(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([new Uint8Array(256)], "sample.mp4", { type: "video/mp4" }));
      const input = document.querySelector("#videoInput");
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      const preview = document.querySelector("#localPreviewVideo");
      Object.defineProperty(preview, "duration", { configurable: true, value: 120 });
      Object.defineProperty(preview, "videoWidth", { configurable: true, value: 1280 });
      Object.defineProperty(preview, "videoHeight", { configurable: true, value: 720 });
      preview.dispatchEvent(new Event("loadedmetadata"));
    });
    assert.equal(await page.locator(".studio").evaluate((node) => node.classList.contains("task-creation-mode")), true);
    assert.equal(await page.locator(".chat-panel").isVisible(), false);
    assert.equal(await page.locator(".chat-panel").getAttribute("aria-hidden"), "true");
    assert.equal(await page.locator(".brief-task-section, .brief-storage-section").count(), 0);
    assert.equal(await page.locator("#briefContentInstruction").count(), 1);
    assert.equal(await page.locator("#briefContentInstruction").isVisible(), false);
    assert.equal(await page.locator("#briefReuseAnalysis, #briefTargetDuration, #briefResultStrategy").count(), 0);
    assert.equal(await page.locator("#briefInstruction").count(), 0);
    assert.equal(await page.locator("[data-workflow-choice]").count(), 4);
    assert.equal(await page.locator("#taskSetupView").isVisible(), true);
    assert.match(await page.locator("#taskSetupView > header").textContent(), /任务开始后.*AI 助手.*后续修改/s);
    assert.equal(await page.locator("#briefAutoInstruction").isVisible(), true);
    assert.equal(await page.locator("#taskSetupPortal > .brief-card").count(), 1);
    assert.equal(await page.locator("#chatMessages .brief-card").count(), 0);
    const workflowGrid = await page.locator(".workflow-entry-grid").evaluate((node) => ({
      columns: getComputedStyle(node).gridTemplateColumns.split(" ").length,
      width: node.getBoundingClientRect().width,
    }));
    assert.equal(workflowGrid.columns, 2);
    assert.ok(workflowGrid.width > 520);
    assert.equal(await page.locator("#voiceProfileButton").count(), 0);
    assert.equal(await page.locator('[data-workflow-choice="person_edit"]').textContent().then((value) => /所有出镜片段/.test(value)), true);
    assert.match(await page.locator("#localPreviewPanel").textContent(), /任务设置/);
    await page.locator('[data-workflow-choice="content_search"]').click();
    await page.locator("#briefContentInstruction").fill("找出后半段的产品演示");
    assert.match(await page.locator(".brief-core-settings").textContent(), /素材范围/);
    assert.equal(await page.locator("#briefHighlightSettings").isVisible(), false);
    assert.equal(await page.locator("#briefContentSettings").isVisible(), true);
    assert.equal(await page.locator("#briefIntentClarification").isVisible(), false);
    assert.equal(await page.evaluate(() => pendingCreateIntentMode), "content_extract");
    await page.locator("#briefSourceScope").selectOption("back_half");
    const creationOptions = await page.evaluate(() => activeBriefOptions("找出产品演示"));
    assert.deepEqual(creationOptions.sourceScope, { kind: "back_half", start: 60, end: 120 });
    assert.equal("targetSeconds" in creationOptions, false);
    assert.equal("resultStrategy" in creationOptions, false);
    const formValues = await page.evaluate(() => {
      const form = window.ClipTalkTaskCreation.buildForm({
        file: new File([new Uint8Array(8)], "sample.mp4", { type: "video/mp4" }),
        instruction: "找出产品演示", sourceScope: { kind: "back_half", start: 60, end: 120 },
      });
      return Object.fromEntries([...form.entries()].filter(([, value]) => typeof value === "string"));
    });
    assert.equal(formValues.source_scope_kind, "back_half");
    assert.equal(formValues.source_scope_start, "60");
    assert.equal(formValues.parameter_context, "adaptive_v1");
    assert.equal(formValues.force_reanalyze, "false");
    assert.equal("total_target_seconds" in formValues, false);
    assert.equal("result_strategy" in formValues, false);
    assert.equal("technique_preset" in formValues, false);
    const finalizingFact = await page.evaluate(() => stageProgressFact({
      status: "running",
      progressMode: "finalizing",
      etaMode: "finalizing",
      stageCompleted: 40,
      stageTotal: 40,
      stageUnit: "个音频分块",
    }, 100, true));
    assert.match(finalizingFact, /40\/40 个音频分块.*正在整理结果/);
    const indexReadyFacts = await page.evaluate(() => ({
      stage: stageProgressFact({ status: "running", progressMode: "completed" }, 100, false),
      eta: progressEtaText({ status: "running", progressMode: "completed" }, false),
    }));
    assert.equal(indexReadyFacts.stage, "当前阶段已完成");
    assert.equal(indexReadyFacts.eta, "正在进入下一阶段");
    assert.equal(await page.locator("#contentEvidenceQuestion").count(), 0);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("queued content search can stop immediately and explains cancellation latency", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.evaluate(() => {
      const job = {
        id: "job_cancel_test", revision: 1, filename: "cancel.mp4",
        taskMode: "content_extract", workflowKind: "content_search",
        status: "queued", stage: "content_search", progress: .15,
        detail: "等待开始检索", currentAction: "等待后台开始处理", progressMode: "indeterminate",
        videoInfo: { duration: 60, width: 1280, height: 720, has_audio: true, frame_rate: 25 },
        request: { workflowKind: "content_search", contentInstruction: "找出接水的片段" },
        messages: [], outputs: [], outputVersions: [], candidates: [], eventGroups: [],
        execution: {
          schemaVersion: 1, status: "queued", operation: "content_search", phase: "content_search",
          active: true, detail: "等待后台开始处理", outcome: "none",
          capabilities: { canCancel: true, canDelete: false },
        },
      };
      homeNavigationRequested = false;
      currentJob = job;
      currentJobRevision = "";
      document.querySelector(".studio")?.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      renderConversation(job);
    });
    const stopButton = page.locator("[data-inline-cancel]");
    assert.equal(await stopButton.isEnabled(), true);
    await stopButton.click();
    assert.equal(await stopButton.textContent(), "正在停止…");
    assert.match(await page.locator("#inlineAnalysisProgress [data-inline-detail]").textContent(), /停止请求已发送/);
    assert.match(await page.locator("#inlineAnalysisProgress [data-inline-eta]").textContent(), /最长约 15 秒/);
    assert.match(await page.locator("#toastRegion").textContent(), /已收到停止请求/);
    await page.waitForFunction(() => currentJob?.status === "cancelled");
    assert.ok(stub.requests.some((item) => item.path === "/api/jobs/job_cancel_test/cancel" && item.method === "POST"));
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("chat context hides defaults and reveals only instruction-relevant state", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      currentJob = {
        id: "chat-context-job", taskMode: "highlight", status: "awaiting_confirmation",
        videoInfo: { duration: 90 }, candidates: [], eventGroups: [], messages: [], outputs: [],
      };
      currentCandidate = null;
      currentEventGroup = null;
      currentEventSegment = null;
      currentOutput = null;
      viewerMediaKind = "source";
      outputAssemblyMode = "single_reel";
      pendingTimelineSelection = null;
      timelineChatSelections = [];
      ignoredChatContextKeys = new Set();
      chatInput.value = "";
      renderChatContextBar();
      const defaults = {
        hidden: document.querySelector("#chatContextBar").classList.contains("hidden"),
        text: document.querySelector("#chatContextBar").textContent,
        context: collectChatUiContext(),
      };

      chatInput.value = "从这里开始，保留当前这段";
      chatInput.dispatchEvent(new Event("input", { bubbles: true }));
      const referencedPlayhead = {
        hidden: document.querySelector("#chatContextBar").classList.contains("hidden"),
        text: document.querySelector("#chatContextBar").textContent,
        context: collectChatUiContext(),
      };

      chatInput.value = "换一种节奏";
      chatInput.dispatchEvent(new Event("input", { bubbles: true }));
      viewerMediaKind = "candidate";
      currentCandidate = { index: 2, start: 12, end: 18 };
      renderChatContextBar();
      const candidate = {
        text: document.querySelector("#chatContextBar").textContent,
        context: collectChatUiContext(),
      };

      viewerMediaKind = "source";
      currentCandidate = null;
      outputAssemblyMode = "separate_events";
      renderChatContextBar();
      const nonDefaultOutput = {
        text: document.querySelector("#chatContextBar").textContent,
        context: collectChatUiContext(),
      };
      return { defaults, referencedPlayhead, candidate, nonDefaultOutput };
    });
    assert.equal(audit.defaults.hidden, true);
    assert.equal(audit.defaults.text, "");
    assert.deepEqual(audit.defaults.context, {});
    assert.equal(audit.referencedPlayhead.hidden, false);
    assert.match(audit.referencedPlayhead.text, /本次会附带.*播放头/);
    assert.equal(typeof audit.referencedPlayhead.context.playheadSeconds, "number");
    assert.equal("viewer" in audit.referencedPlayhead.context, false);
    assert.equal("composition" in audit.referencedPlayhead.context, false);
    assert.match(audit.candidate.text, /正在预览高光候选/);
    assert.equal(audit.candidate.context.viewer.kind, "candidate");
    assert.equal("playheadSeconds" in audit.candidate.context, false);
    assert.doesNotMatch(audit.candidate.text, /合成一条/);
    assert.match(audit.nonDefaultOutput.text, /分别导出/);
    assert.equal(audit.nonDefaultOutput.context.composition.outputMode, "separate_events");
    assert.doesNotMatch(audit.nonDefaultOutput.text, /正在看源视频/);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("unrouted follow-up thinking uses the generic video editing assistant", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const labels = await page.evaluate(() => {
      const config = commandThinkingConfig("帮我找到做家务的片段");
      const generic = document.createElement("div");
      generic.innerHTML = thinkingMessageMarkup(config);
      const routed = document.createElement("div");
      routed.innerHTML = thinkingMessageMarkup(config, { workflowKind: "content_search" });
      return {
        generic: generic.querySelector("small")?.textContent || "",
        routed: routed.querySelector("small")?.textContent || "",
      };
    });
    assert.equal(labels.generic, "视频剪辑助手");
    assert.equal(labels.routed, "视频剪辑助手");
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("compact navigation rail opens a focused history drawer", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.route("**/api/jobs", async (route) => {
      if (
        route.request().method() !== "GET"
        || route.request().headers()["x-highlight-token"] !== "browser-test-token"
      ) return route.fallback();
      const base = {
        sourceProjectId: "asset_shared", filename: "interview.mp4", taskMode: "content_extract",
        status: "completed", stage: "completed", progress: 1, outputs: [], outputVersions: [],
        videoInfo: { duration: 60, width: 1280, height: 720 }, candidateCount: 2,
      };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ jobs: [
        { ...base, id: "task-content", workflowKind: "content_search", updatedAt: "2026-08-25T01:00:00Z" },
        { ...base, id: "task-person", workflowKind: "person_edit", updatedAt: "2026-08-25T02:00:00Z" },
        { ...base, id: "task-running", workflowKind: "highlight", status: "running", stage: "analysis", progress: .43, detail: "正在分析素材", updatedAt: "2026-08-25T03:00:00Z" },
      ] }) });
    });
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#accessTokenDialog[open]").waitFor({ state: "visible" });
    await page.locator("#accessTokenDialog input").fill("browser-test-token");
    await page.locator("#accessTokenDialog button[type=submit]").click();
    await page.waitForFunction(() => document.querySelector("#homeView")?.dataset.homeState === "ready");
    assert.equal(await page.locator("#sidebarHistoryDrawer").getAttribute("aria-hidden"), "true");
    assert.equal(await page.locator("#appSidebar").evaluate((node) => getComputedStyle(node).width), "72px");
    assert.equal(await page.locator(".app-sidebar-primary .app-sidebar-action").count(), 4);
    assert.equal(await page.locator("#sidebarCurrentTask").isDisabled(), true);
    assert.equal(await page.locator(".app-sidebar-footer, #sidebarCollapse, #sidebarTaskRefresh").count(), 0);
    await page.locator("#sidebarHistoryToggle").click();
    await page.locator("#sidebarHistoryList .shell-task-card").first().waitFor({ state: "visible" });
    assert.equal(await page.locator("#sidebarHistoryDrawer").getAttribute("aria-hidden"), "false");
    assert.equal(await page.locator("#sidebarHistoryToggle").getAttribute("aria-expanded"), "true");
    assert.equal(await page.locator("#homeView").getAttribute("data-home-state"), "ready");
    assert.equal(await page.locator(".home-summary").isVisible(), false);
    assert.equal(await page.locator("#homeAssetCount").textContent(), "1");
    assert.equal(await page.locator("#homeTaskCount").textContent(), "3");
    assert.equal(await page.locator("#homeOutputCount").textContent(), "0");
    assert.equal(await page.locator("#homeTaskGrid .shell-task-card").count(), 1);
    assert.equal(await page.locator("#sidebarAttentionCount").textContent(), "1");
    const rows = await page.locator("#sidebarHistoryList .shell-task-card").evaluateAll((nodes) => nodes.map((node) => ({
      openId: node.querySelector("[data-shell-open]")?.dataset.shellOpen || "",
      deleteId: node.querySelector("[data-shell-delete]")?.dataset.shellDelete || "",
      label: node.querySelector(".shell-task-open > small")?.textContent.split(" · ")[0] || "",
    })));
    assert.deepEqual(rows, [
      { openId: "task-running", deleteId: "", label: "智能高光" },
      { openId: "task-person", deleteId: "task-person", label: "按人物剪辑" },
      { openId: "task-content", deleteId: "task-content", label: "内容探索" },
    ]);
    assert.equal(await page.locator("#sidebarHistoryList .task-stage-track, #sidebarHistoryList .shell-task-meta").count(), 0);
    assert.deepEqual(await page.locator("#sidebarHistoryList .shell-task-state").allTextContents(), ["进行中", "已完成", "已完成"]);
    assert.equal(await page.locator("#sidebarHistoryList .shell-task-progress").count(), 1);
    assert.match(await page.locator("#sidebarHistoryList .shell-task-progress").getAttribute("aria-label"), /43%/);
    await page.evaluate(() => {
      window.ClipTalkCurrentJobId = () => "task-running";
      window.ClipTalkAppShell.syncCurrentJob({ id: "task-running" });
    });
    assert.equal(await page.locator("#sidebarCurrentTask").isEnabled(), true);
    assert.equal(await page.locator("#sidebarCurrentTask").getAttribute("title"), "返回当前任务");
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#sidebarHistoryDrawer").getAttribute("aria-hidden"), "true");
    assert.equal(await page.locator("#sidebarHistoryToggle").getAttribute("aria-expanded"), "false");
    assert.equal(await page.evaluate(() => document.activeElement?.id), "sidebarHistoryToggle");
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("home task load failure keeps new-task entry and offers retry", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  let attempts = 0;
  try {
    await page.route("**/api/jobs", async (route) => {
      if (
        route.request().method() !== "GET"
        || route.request().headers()["x-highlight-token"] !== "browser-test-token"
      ) return route.fallback();
      attempts += 1;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "任务服务暂时不可用" }),
      });
    });
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#accessTokenDialog[open]").waitFor({ state: "visible" });
    await page.locator("#accessTokenDialog input").fill("browser-test-token");
    await page.locator("#accessTokenDialog button[type=submit]").click();
    await page.locator('.home-view[data-home-state="error"] .home-error-card').waitFor({ state: "visible" });
    assert.equal(await page.locator("[data-home-create]").isVisible(), true);
    assert.match(await page.locator(".home-error-card").textContent(), /最近任务暂时无法加载/);
    await page.locator("[data-home-retry]").click();
    await page.locator('.home-view[data-home-state="error"] .home-error-card').waitFor({ state: "visible" });
    assert.ok(attempts >= 2);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("upload workflow entries reveal only relevant controls and highlight starts without a prompt", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.locator("[data-home-create]").click();
    await page.evaluate(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([new Uint8Array(256)], "highlight.mp4", { type: "video/mp4" }));
      const input = document.querySelector("#videoInput");
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      Object.defineProperty(document.querySelector("#localPreviewVideo"), "duration", { configurable: true, value: 90 });
    });
    await page.locator('[data-workflow-choice="content_search"]').click();
    assert.equal(await page.locator("#briefContentSettings").isVisible(), true);
    assert.equal(await page.locator("#briefHighlightSettings").isVisible(), false);
    assert.equal(await page.locator("#chatInput").isDisabled(), true);
    assert.equal(await page.locator("#briefContentInstruction").evaluate((node) => node === document.activeElement), true);
    await page.locator("#briefContentInstruction").fill("找出煎鸡蛋的画面");
    assert.equal(await page.locator("#chatInput").inputValue(), "");

    await page.locator('[data-workflow-choice="person_edit"]').click();
    assert.equal(await page.locator("#briefPersonSettings").isVisible(), true);
    assert.equal(await page.locator("#briefContentSettings").isVisible(), false);
    assert.equal(await page.locator("#chatInput").isDisabled(), true);

    await page.locator('[data-workflow-choice="speaker_edit"]').click();
    assert.equal(await page.locator("#briefSpeakerSettings").isVisible(), true);
    assert.equal(await page.locator("#briefPersonSettings").isVisible(), false);

    await page.locator('[data-workflow-choice="highlight"]').click();
    assert.equal(await page.locator("#briefHighlightSettings").isVisible(), true);
    assert.match(await page.locator("#briefHighlightSettings").textContent(), /目标成片时长（秒）.*最短为 4 秒/s);
    assert.equal(await page.locator("#briefSpeakerSettings").isVisible(), false);
    assert.equal(await page.locator("#chatInput").isDisabled(), true);
    assert.equal(await page.locator("#chatInput").inputValue(), "");
    assert.equal(await page.locator("#briefHighlightInstruction").isVisible(), true);
    await page.locator("#briefHighlightInstruction").fill("重点保留产品演示");
    assert.equal(await page.locator("#briefHighlightInstruction").inputValue(), "重点保留产品演示");
    await page.locator("#briefHighlightInstruction").fill("");
    await page.locator("#briefHighlightTargetSeconds").fill("30");
    await page.locator("#briefHighlightVariantCount").selectOption("2");
    await page.locator('[data-start-workflow="highlight"]').click();
    await page.waitForFunction(() => currentJob?.id === "job_voice_upload");
    assert.equal(await page.locator(".studio").evaluate((node) => node.classList.contains("task-creation-mode")), false);
    assert.equal(await page.locator(".chat-panel").isVisible(), true);
    assert.equal(await page.locator(".chat-panel").getAttribute("aria-hidden"), null);
    const creation = stub.requests.find((item) => item.path === "/api/jobs" && item.method === "POST");
    assert.ok(creation, "highlight entry should upload without requiring text input");
    assert.match(creation.body, /name="workflow_kind"\r?\n\r?\nhighlight/);
    assert.match(creation.body, /name="task_mode"\r?\n\r?\nhighlight/);
    assert.match(creation.body, /name="total_target_seconds"\r?\n\r?\n30/);
    assert.match(creation.body, /name="auto_variant_count"\r?\n\r?\n2/);
    assert.match(creation.body, /自动分析所选素材并生成高光视频/);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("content search starts from the inline task dialog", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.locator("[data-home-create]").click();
    await page.evaluate(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([new Uint8Array(256)], "content.mp4", { type: "video/mp4" }));
      const input = document.querySelector("#videoInput");
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      Object.defineProperty(document.querySelector("#localPreviewVideo"), "duration", { configurable: true, value: 90 });
    });
    await page.locator('[data-workflow-choice="content_search"]').click();
    await page.locator("#briefContentInstruction").fill("找出煎鸡蛋的画面");
    await page.locator("[data-start-content-search]").click();
    await page.waitForFunction(() => currentJob?.id === "job_voice_upload");

    const creation = stub.requests.find((item) => item.path === "/api/jobs" && item.method === "POST");
    assert.ok(creation, "content search should submit from the inline task dialog");
    assert.match(creation.body, /name="workflow_kind"\r?\n\r?\ncontent_search/);
    assert.match(creation.body, /name="task_mode"\r?\n\r?\ncontent_extract/);
    assert.match(creation.body, /找出煎鸡蛋的画面/);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("speaker workflow uses its own upload entry and starts with the configured count", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.locator("[data-home-create]").click();
    await page.evaluate(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([new Uint8Array(256)], "sample.mp4", { type: "video/mp4" }));
      const input = document.querySelector("#videoInput");
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    assert.equal(await page.locator("#chatInput").inputValue(), "");
    await page.locator('[data-workflow-choice="speaker_edit"]').click();
    assert.equal(await page.locator("#briefSpeakerSettings").isVisible(), true);
    assert.equal(await page.locator("#chatInput").isDisabled(), true);
    await page.locator("#briefExpectedVoiceCount").selectOption("2");
    await page.locator('[data-start-workflow="speaker_edit"]').click();
    await page.waitForFunction(() => currentJob?.id === "job_voice_upload");
    await page.waitForFunction(() => document.querySelector("#voiceProfilePanel") && !document.querySelector("#voiceProfilePanel").classList.contains("hidden"));

    const creation = stub.requests.find((item) => item.path === "/api/jobs" && item.method === "POST");
    assert.ok(creation, "speaker entry should formally upload the selected video");
    assert.match(creation.body, /name="entry_workflow"\r?\n\r?\nvoice_discovery/);
    assert.match(creation.body, /name="workflow_kind"\r?\n\r?\nspeaker_edit/);
    assert.match(creation.body, /name="task_mode"\r?\n\r?\ncontent_extract/);
    assert.match(creation.body, /识别本视频中的说话人/);
    await page.waitForFunction(() => document.querySelector("#currentVoiceCount")?.textContent === "识别中");
    await page.locator("#currentVoiceList .voice-discovery-progress").waitFor({ state: "visible" });
    await page.waitForFunction(() => document.querySelector("#currentVoiceList")?.textContent.includes("正在分析声音 A 的代表发言"));
    assert.match(await page.locator("#currentVoiceList .voice-discovery-progress").textContent(), /已完成 1\/2 个声音/);
    assert.equal(await page.locator("[data-inline-cancel]").textContent(), "停止说话人识别");
    const discovery = stub.requests.find((item) => item.path.endsWith("/content-search/voices/discover") && item.method === "POST");
    assert.ok(discovery);
    assert.deepEqual(JSON.parse(discovery.body), { expectedSpeakerCount: 2, force: false });
    assert.equal(await page.locator("#chatInput").inputValue(), "");
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("speaker panel clears the previous video and ignores its late response", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  let releaseVideoA;
  const videoARequested = new Promise((resolveRequested) => { releaseVideoA = resolveRequested; });
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/jobs/job-video-a/content-search/voices", async (route) => {
      releaseVideoA();
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 260));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        status: { status: "ready" }, revision: 0, canUndo: false, timeline: [],
        voices: [{ speakerRef: "Speaker A", label: "视频 A 的人物", speechSeconds: 8, segmentCount: 2, representativeSegments: [] }],
      }) });
    });
    await page.route("**/api/jobs/job-video-b/content-search/voices", async (route) => {
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 80));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        status: { status: "ready" }, revision: 0, canUndo: false, timeline: [],
        voices: [{ speakerRef: "Speaker B", label: "视频 B 的人物", speechSeconds: 11, segmentCount: 3, representativeSegments: [] }],
      }) });
    });
    const makeJob = (id, filename) => ({
      id, filename, taskMode: "content_extract", status: "completed", stage: "completed",
      progress: 1, videoInfo: { duration: 30, width: 1280, height: 720, has_audio: true, frame_rate: 25 },
      request: {}, messages: [], outputs: [], outputVersions: [], candidates: [], eventGroups: [],
    });
    await page.evaluate((job) => {
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      currentJob = job;
      openVoiceProfiles();
    }, makeJob("job-video-a", "video-a.mp4"));
    await videoARequested;
    await page.evaluate((job) => {
      switchWorkspaceJob(job);
      openVoiceProfiles();
    }, makeJob("job-video-b", "video-b.mp4"));

    assert.equal((await page.locator("#currentVoiceList").textContent()).includes("视频 A 的人物"), false);
    assert.match(await page.locator("#currentVoiceList").textContent(), /正在读取当前视频/);
    await page.locator("#currentVoiceList").getByText("视频 B 的人物").waitFor({ state: "visible" });
    await page.waitForTimeout(260);
    const finalText = await page.locator("#currentVoiceList").textContent();
    assert.match(finalText, /视频 B 的人物/);
    assert.equal(finalText.includes("视频 A 的人物"), false);
    assert.equal(await page.evaluate(() => currentVoiceJobId), "job-video-b");
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("content match cards remain readable in a narrow review rail", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(async () => {
      const host = document.createElement("section");
      host.className = "chat-messages";
      host.style.cssText = "position:fixed;inset:12px auto auto 12px;width:300px;height:820px;z-index:500;background:#071018;overflow:auto";
      const reviewJob = {
        id: "job-content-boundary",
        status: "awaiting_content_confirmation",
        taskMode: "content_extract",
        videoInfo: { duration: 120, has_audio: true, frame_rate: 25 },
        speechAnalysis: { segments: [] },
        contentIndex: { persons: [{
          id: "person_1", label: "女嘉宾", defaultLabel: "人物 A", userLabeled: true,
          thumbnailUrl: "/person-1.jpg", primarySpeaker: "Speaker 2", speakerConfidence: .93,
          speakerReviewRequired: false,
        }] },
        contentSearch: {
          id: "search_test",
          status: "review_required",
          resultMode: "top_k",
          executionPlan: { allowedCapabilities: ["visual"] },
          queryPlan: { predicates: [{ kind: "person.appearance", value: "目标人物" }] },
          instruction: "找出整理桌面物品和清理厨余垃圾的画面",
          defaultSelectedIds: ["match_1"],
          retrievalStats: {
            localRecallCount: 111, totalMilliseconds: 531,
            personDescriptionResolution: { evidence: [{
              personId: "person_1", status: "reliable", confidence: .88,
              reason: "三张代表画面均符合描述",
            }] },
          },
          candidates: [{
            id: "match_1",
            title: "整理桌面物品",
            start: 76.2,
            end: 78,
            duration: 1.8,
            score: 86,
            confidence: .8,
            evidenceType: "visual",
            matchedModalities: ["visual"],
            evidenceRefs: Array.from({ length: 111 }, (_, index) => ({ id: `evidence_${index}` })),
            matchType: "visual_dense_fallback",
            boundarySource: "targeted_dense_frames",
            matchedPersonIds: ["person_1"],
            matchedPersonLabels: ["女嘉宾"],
            personDescriptionEvidence: {
              personId: "person_1", status: "reliable", confidence: .88,
              reason: "三张代表画面均符合描述",
            },
            activeSpeakerEvidence: {
              personId: "person_1", personLabel: "女嘉宾",
              associationMethod: "active_speaker_talknet", asdScore: .93,
            },
            matchedEvidence: "画面中可见手持小物件放置到圆桌上的收纳盒旁，整理桌面零散物品。",
          }, {
            id: "match_2",
            title: "清理厨余垃圾",
            start: 53.2,
            end: 56.7,
            duration: 3.5,
            score: 83,
            confidence: .78,
            evidenceType: "visual",
            matchedModalities: ["visual"],
            evidenceRefs: [{ id: "evidence_cleanup" }],
            matchType: "visual_dense_fallback",
            boundarySource: "targeted_dense_frames",
            matchedEvidence: "人物将厨余垃圾装袋并清理台面。",
          }],
        },
      };
      reviewJob.contentSearchSession = { activeSearchId: reviewJob.contentSearch.id, state: "ready" };
      currentJob = reviewJob;
      waveformData = { duration: 120, hasAudio: true, peaks: [], rms: [] };
      host.innerHTML = contentSearchReviewMarkup(reviewJob);
      wireContentBoundaryEditors(host.querySelector(".content-search-review"), reviewJob);
      document.body.append(host);
      syncContentSearchOutputControls(host, reviewJob);
      syncContentSearchSubtitleControls(host, reviewJob);
      const row = host.querySelector(".content-match-row");
      const main = host.querySelector(".content-match-main");
      const copy = host.querySelector(".content-match-copy");
      const actions = host.querySelector(".content-match-buttons");
      const title = host.querySelector(".content-match-title strong");
      const evidence = host.querySelector(".content-match-evidence");
      const actionButtons = [...actions.querySelectorAll("button")];
      const mainRect = main.getBoundingClientRect();
      const actionsRect = actions.getBoundingClientRect();
      const outputSelect = host.querySelector("[data-content-output-mode]");
      const orderSelect = host.querySelector("[data-content-order-mode]");
      const outputControls = host.querySelector(".content-output-controls");
      const contentActions = host.querySelector(".content-search-actions");
      const confirmContentButton = host.querySelector("[data-confirm-content]");
      const subtitleInput = host.querySelector("[data-content-subtitle]");
      const subtitleStatus = host.querySelector("[data-content-subtitle-status]");
      const singleSelectionOutputHidden = host.querySelector("[data-content-output-wrap]").classList.contains("hidden");
      host.querySelectorAll("[data-content-match]")[1].checked = true;
      syncContentSearchOutputControls(host, reviewJob);
      const recovery = host.querySelector(".content-search-recovery");
      const boundaryButton = host.querySelector('[data-content-boundary-open="match_1"]');
      const boundaryEditor = host.querySelector('[data-content-boundary-editor="match_1"]');
      boundaryButton.click();
      const directBoundaryMovedToInspector = !timelineExpanded
        && boundaryEditor.parentElement === document.querySelector("#contentBoundaryInspector")
        && !boundaryEditor.classList.contains("hidden");
      const originalBoundaryEnd = Number(boundaryEditor.dataset.boundaryEnd);
      boundaryEditor.querySelector('[data-boundary-adjust="end:frame"]').click();
      const adjustedBoundaryEnd = Number(boundaryEditor.dataset.boundaryEnd);
      boundaryEditor.querySelector("[data-boundary-cancel]").click();
      const directEntryInitiallyClosed = boundaryEditor.classList.contains("hidden");
      copy.click();
      const cardPreviewStayedClosed = boundaryEditor.classList.contains("hidden");
      setTimelineExpanded(true);
      const timelineMatchButton = [...document.querySelectorAll("#timelineLabels .timeline-label.content-match")]
        .find((button) => button.textContent.includes("整理桌面物品"));
      timelineMatchButton.click();
      const timelinePreviewStayedClosed = boundaryEditor.classList.contains("hidden");
      const timelineEvidencePanelOpen = !document.querySelector("#evidencePanel").classList.contains("content-boundary-view")
        && document.querySelector("#contentBoundaryInspector").classList.contains("hidden")
        && document.querySelector('[data-content-detail-mode="evidence"]').getAttribute("aria-pressed") === "true";
      document.querySelector('[data-content-detail-mode="edit"]').click();
      const timelineBoundaryInspectorOpen = document.querySelector("#evidencePanel").classList.contains("content-boundary-view")
        && boundaryEditor.parentElement === document.querySelector("#contentBoundaryInspector")
        && document.querySelector('[data-content-detail-mode="edit"]').getAttribute("aria-pressed") === "true";
      const timelineBoundaryDialogActions = [...boundaryEditor.querySelectorAll("[data-boundary-adjust]")]
        .map((button) => button.textContent.trim());
      const beforeOneSecondNudge = Number(boundaryEditor.dataset.boundaryStart);
      boundaryEditor.querySelector('[data-boundary-adjust="start:-1"]').click();
      const oneSecondNudgeDelta = Number(boundaryEditor.dataset.boundaryStart) - beforeOneSecondNudge;
      timelineMatchButton.click();
      const evidenceClickLeavesEditorResumable = !document.querySelector("#evidencePanel").classList.contains("content-boundary-view")
        && document.querySelector("#contentBoundaryInspector").classList.contains("hidden")
        && contentBoundaryTimelineEdit?.editor === boundaryEditor
        && Math.abs(Number(boundaryEditor.dataset.boundaryStart) - (beforeOneSecondNudge - 1)) < 1e-6;
      document.querySelector('[data-content-detail-mode="edit"]').click();
      const timelineDirectActionsVisible = ["timelineContentToggleSelected", "timelineContentMoveEarlier", "timelineContentMoveLater"]
        .every((id) => !document.querySelector(`#${id}`).classList.contains("hidden"));
      const timelineSelectedSequence = timelineMatchButton.querySelector("b")?.textContent || "";
      const timelineTrimButton = document.querySelector("#timelineContentTrim");
      const timelineTrimAvailable = !document.querySelector("#timelineContentTrimGroup").classList.contains("hidden")
        && !timelineTrimButton.disabled;
      timelineTrimButton.click();
      const timelineTrimOpenedEditor = !boundaryEditor.classList.contains("hidden");
      const timelineSelection = document.querySelector("#timelineSelection");
      const timelineBoundaryVisible = !timelineSelection.classList.contains("hidden")
        && timelineSelection.classList.contains("content-boundary-edit")
        && timelineSelection.classList.contains("boundary-editable");
      const timelineBoundarySummary = document.querySelector("#timelineSelectionSummary")?.textContent || "";
      const timelineStartInput = document.querySelector("#timelineSelectionStartInput");
      timelineStartInput.value = "76.6";
      timelineStartInput.dispatchEvent(new Event("change", { bubbles: true }));
      const timelineTypedBoundaryStart = Number(boundaryEditor.dataset.boundaryStart);
      const startSecondsInput = boundaryEditor.querySelector('[data-boundary-value="start"]');
      startSecondsInput.value = "76.4";
      startSecondsInput.dispatchEvent(new Event("change", { bubbles: true }));
      const typedBoundaryStart = Number(boundaryEditor.dataset.boundaryStart);
      const mirror = document.createElement("section");
      mirror.innerHTML = contentSearchReviewMarkup(reviewJob);
      document.body.append(mirror);
      const mirrorRoot = mirror.querySelector(".content-search-review");
      wireContentBoundaryEditors(mirrorRoot, reviewJob);
      const resumedEditor = mirror.querySelector('[data-content-boundary-editor="match_1"]');
      const boundarySurvivesRerender = resumedEditor.classList.contains("hidden")
        && Number(boundaryEditor.dataset.boundaryStart) === 76.4
        && contentBoundaryTimelineEdit.editor === boundaryEditor
        && boundaryEditor.parentElement === document.querySelector("#contentBoundaryInspector");
      mirror.remove();
      const completeMarkup = contentSearchReviewMarkup({
        ...reviewJob,
        contentSearch: {
          ...reviewJob.contentSearch,
          resultMode: "exhaustive",
          coverageComplete: true,
          retrievalStats: { ...reviewJob.contentSearch.retrievalStats, coverageComplete: true },
        },
      });
      const tieredDocument = new DOMParser().parseFromString(contentSearchReviewMarkup({
        ...reviewJob,
        contentSearch: {
          ...reviewJob.contentSearch,
          resultMode: "exhaustive",
          coverageComplete: false,
          scanProgress: { state: "partial", coveredPercent: 37.5 },
          completeness: { status: "incomplete", possibleCount: 1, channels: [] },
          candidates: [
            { ...reviewJob.contentSearch.candidates[0], confidenceTier: "reliable", requiresReview: false },
            { ...reviewJob.contentSearch.candidates[1], confidenceTier: "possible", requiresReview: true },
          ],
        },
      }), "text/html");
      const decoupledDocument = new DOMParser().parseFromString(contentSearchReviewMarkup({
        ...reviewJob,
        contentSelectionBasket: {
          schemaVersion: "content-selection-basket-v2",
          entryMode: "explicit",
          initialized: true,
          items: [{ searchId: "search_test", matchId: "match_2" }],
        },
      }), "text/html");
      const decoupledCheckedIds = [...decoupledDocument.querySelectorAll("[data-content-match]:checked")]
        .map((input) => input.value);
      const legacyBasketCount = contentBasketItems({
        ...reviewJob,
        contentSelectionBasket: {
          schemaVersion: "content-selection-basket-v1",
          initialized: true,
          items: [{ searchId: "search_test", matchId: "match_2" }],
        },
      }).length;
      renderContentSelectionBasket({
        ...reviewJob,
        id: "basket-ui-test",
        taskMode: "content_extract",
        contentSelectionBasket: {
          schemaVersion: "content-selection-basket-v2",
          entryMode: "explicit",
          initialized: true,
          items: [{
            searchId: "search_test", matchId: "match_1", title: "整理桌面物品",
            sourceQuery: "找整理桌面的片段", start: 76.2, end: 78, duration: 1.8,
          }],
        },
      });
      const basketRoot = document.querySelector("#contentSelectionBasket");
      const basketAudit = {
        hidden: basketRoot.classList.contains("hidden"),
        summary: basketRoot.querySelector("summary")?.textContent || "",
        itemCount: basketRoot.querySelectorAll("ol > li").length,
        itemText: basketRoot.querySelector("ol > li")?.textContent || "",
        generateLabel: basketRoot.querySelector("[data-content-basket-confirm]")?.textContent || "",
        outputMode: basketRoot.querySelector("[data-content-basket-output]")?.value || "",
        orderMode: basketRoot.querySelector("[data-content-basket-order]")?.value || "",
        outputOptions: [...basketRoot.querySelectorAll("[data-content-basket-output] option")].map((item) => item.value),
        orderOptions: [...basketRoot.querySelectorAll("[data-content-basket-order] option")].map((item) => item.value),
      };
      const previousCurrentJob = currentJob;
      currentJob = {
        ...reviewJob,
        taskMode: "content_extract",
        contentSelectionBasket: {
          schemaVersion: "content-selection-basket-v2", entryMode: "explicit", initialized: true,
          items: [{ searchId: "search_test", matchId: "match_1" }],
        },
      };
      const basketInjectedIntoChat = chatUiContextEntries().some((entry) => entry.key === "contentMatches");
      currentJob = previousCurrentJob;
      const noDialogueSubtitleState = {
        disabled: subtitleInput.disabled,
        checked: subtitleInput.checked,
        message: subtitleStatus.textContent,
        hidden: subtitleInput.closest(".content-subtitle-toggle").classList.contains("hidden"),
      };
      reviewJob.speechAnalysis.segments = [{ start: 76.4, end: 77.5, text: "把物品放进收纳盒。" }];
      syncContentSearchSubtitleControls(host, reviewJob);
      const dialogueSubtitleState = {
        disabled: subtitleInput.disabled,
        message: subtitleStatus.textContent,
        hidden: subtitleInput.closest(".content-subtitle-toggle").classList.contains("hidden"),
      };
      orderSelect.value = "llm_recommend";
      syncContentSearchOutputControls(host, reviewJob);
      const llmHint = host.querySelector("[data-content-order-hint]").textContent;
      outputSelect.value = "separate_events";
      syncContentSearchOutputControls(host, reviewJob);
      const separateState = {
        hidden: host.querySelector("[data-content-order-wrap]").classList.contains("hidden"),
        disabled: orderSelect.disabled,
        hint: host.querySelector("[data-content-order-hint]").textContent,
      };
      const confirmationPromise = requestActionConfirmation({
        title: "确认生成内容合集",
        summary: "检查内容排序控件",
        orderMode: "selection",
        orderItems: [
          { id: "match_1", label: "整理桌面物品", meta: "01:16→01:18" },
          { id: "match_2", label: "清理厨余垃圾", meta: "00:53→00:56" },
        ],
        showOrderOptions: true,
      });
      await Promise.resolve();
      const modalOrderVisible = getComputedStyle(document.querySelector("#actionConfirmOrderWrap")).display !== "none";
      const reorderButtonCount = document.querySelectorAll("#actionConfirmOrderList [data-order-up], #actionConfirmOrderList [data-order-down]").length;
      document.querySelector("#actionConfirmCancel").click();
      await confirmationPromise;
      reviewJob.speechAnalysis.segments = [];
      syncContentSearchSubtitleControls(host, reviewJob);
      return {
        rowColumns: getComputedStyle(row).gridTemplateColumns,
        copyWidth: copy.getBoundingClientRect().width,
        actionsBelowContent: actionsRect.top >= mainRect.bottom,
        actionsShareRow: new Set(actionButtons.map((button) => Math.round(button.getBoundingClientRect().top))).size === 1,
        titleSize: Number.parseFloat(getComputedStyle(title).fontSize),
        evidenceSize: Number.parseFloat(getComputedStyle(evidence).fontSize),
        rawDiagnosticsVisible: host.textContent.includes("visual_dense_fallback") || host.textContent.includes("targeted_dense_frames"),
        translatedDiagnosticsVisible: host.textContent.includes("局部逐帧复检") && host.textContent.includes("局部画面复检"),
        outputOptions: [...outputSelect.options].map((option) => option.value),
        orderOptions: [...orderSelect.options].map((option) => option.value),
        llmHint,
        separateState,
        modalOrderVisible,
        reorderButtonCount,
        outputControlColumns: getComputedStyle(outputControls).gridTemplateColumns,
        singleSelectionOutputHidden,
        confirmButtonWidth: confirmContentButton.getBoundingClientRect().width,
        contentEditEntryCount: host.querySelectorAll("[data-content-edit-selected]").length,
        confirmButtonText: confirmContentButton.textContent,
        actionWidth: contentActions.getBoundingClientRect().width,
        noDialogueSubtitleState,
        dialogueSubtitleState,
        personCardLabel: host.querySelector(".content-person-card strong")?.textContent,
        personSpeakerText: host.querySelector(".content-person-card span")?.textContent,
        personLabelButton: host.querySelector("[data-person-label]")?.dataset.personLabel,
        recoveryText: recovery?.textContent || "",
        recoveryOpen: Boolean(recovery?.open),
        recoveryAfterActions: Boolean(contentActions.compareDocumentPosition(recovery) & Node.DOCUMENT_POSITION_FOLLOWING),
        completeRecoveryCount: new DOMParser().parseFromString(completeMarkup, "text/html").querySelectorAll(".content-search-recovery").length,
        possibleToggleText: tieredDocument.querySelector("[data-content-show-possible]")?.textContent || "",
        layeredPersonEvidenceText: host.querySelector(".content-person-evidence-summary")?.textContent || "",
        layeredCandidateEvidenceText: host.querySelector(".content-match-row .content-evidence-chips")?.textContent || "",
        possibleInitiallyHidden: tieredDocument.querySelector(".content-candidate-possible")?.classList.contains("hidden"),
        tieredReviewText: tieredDocument.body.textContent,
        mergeAddButtonText: host.querySelector("[data-content-basket-add]")?.textContent || "",
        decoupledCheckedIds,
        legacyBasketCount,
        basketAudit,
        basketInjectedIntoChat,
        boundaryButtonText: boundaryButton.textContent,
        boundaryPreviewButtonText: host.querySelector('[data-content-preview="match_1"]')?.textContent || "",
        boundaryCopyIsPreview: host.querySelector('[data-content-card-preview="match_1"]')?.getAttribute("role") === "button",
        directEntryInitiallyClosed,
        directBoundaryMovedToInspector,
        cardPreviewStayedClosed,
        timelinePreviewStayedClosed,
        timelineEvidencePanelOpen,
        timelineBoundaryInspectorOpen,
        evidenceClickLeavesEditorResumable,
        timelineBoundaryDialogActions,
        oneSecondNudgeDelta,
        timelineDirectActionsVisible,
        timelineSelectedSequence,
        timelineTrimAvailable,
        timelineTrimOpenedEditor,
        boundarySurvivesRerender,
        timelineBoundaryVisible,
        timelineBoundarySummary,
        timelineTypedBoundaryStart,
        timelineSaveButtonText: document.querySelector("#timelineSelectionConfirm")?.textContent || "",
        timelineHandleCount: timelineSelection.querySelectorAll(".timeline-handle").length,
        timelineOverlayDisplay: getComputedStyle(timelineSelection).display,
        timelineHandleDisplay: getComputedStyle(timelineSelection.querySelector(".timeline-handle.start")).display,
        typedBoundaryStart,
        legacyBoundaryButtonCount: host.querySelectorAll('[data-content-feedback="boundary_incorrect"]').length,
        boundaryEditorVisible: !boundaryEditor.classList.contains("hidden"),
        boundaryFrameText: boundaryEditor.querySelector("[data-boundary-frame-rate]").textContent,
        boundaryFrameDelta: adjustedBoundaryEnd - originalBoundaryEnd,
        boundaryHasManualActions: ["开始秒数", "结束秒数", "前一帧", "后一帧", "前一秒", "后一秒", "预览片段", "取消", "保存修改"].every((label) => boundaryEditor.textContent.includes(label)),
      };
    });
    await page.screenshot({ path: join(projectRoot, "test-results/subtitle-availability.png") });
    await page.locator(".content-search-actions").screenshot({ path: join(projectRoot, "test-results/subtitle-availability-control.png") });
    assert.ok(audit.copyWidth >= 175, `copy width was ${audit.copyWidth}px`);
    assert.equal(audit.actionsBelowContent, true);
    assert.equal(audit.actionsShareRow, true);
    assert.ok(audit.titleSize >= 14);
    assert.ok(audit.evidenceSize >= 12);
    assert.equal(audit.rawDiagnosticsVisible, false);
    assert.equal(audit.translatedDiagnosticsVisible, true);
    assert.deepEqual(audit.outputOptions, ["single_reel", "separate_events"]);
    assert.equal(audit.singleSelectionOutputHidden, true);
    assert.deepEqual(audit.orderOptions, ["source", "selection", "llm_recommend"]);
    assert.match(audit.llmHint, /不会增删片段|不会.*起止点/);
    assert.deepEqual(audit.separateState, {
      hidden: true,
      disabled: true,
      hint: "每个片段独立输出，不涉及合成顺序。",
    });
    assert.equal(audit.modalOrderVisible, true);
    assert.equal(audit.reorderButtonCount, 4);
    assert.equal(audit.outputControlColumns.trim().split(/\s+/).length, 1);
    assert.ok(audit.confirmButtonWidth > 0);
    assert.equal(audit.contentEditEntryCount, 0);
    assert.equal(audit.confirmButtonText, "生成当前检索视频");
    assert.deepEqual(audit.noDialogueSubtitleState, {
      disabled: true,
      checked: false,
      message: "所选片段没有可转写对白，无需添加字幕。",
      hidden: true,
    });
    assert.equal(audit.dialogueSubtitleState.disabled, false);
    assert.equal(audit.dialogueSubtitleState.hidden, false);
    assert.match(audit.dialogueSubtitleState.message, /检测到 1 段可转写对白/);
    assert.equal(audit.personCardLabel, "女嘉宾");
    assert.match(audit.personSpeakerText, /Speaker 2.*93%/);
    assert.equal(audit.personLabelButton, "person_1");
    assert.match(audit.layeredPersonEvidenceText, /人物描述采用多帧匹配.*1 个人物证据充分/s);
    assert.match(audit.layeredCandidateEvidenceText, /外观描述 88%.*主动说话 93%/s);
    assert.match(audit.recoveryText, /结果可能有遗漏.*提高采样密度并检查剩余范围/);
    assert.equal(audit.recoveryOpen, false);
    assert.equal(audit.recoveryAfterActions, true);
    assert.equal(audit.completeRecoveryCount, 0);
    assert.match(audit.possibleToggleText, /待试听复核.*1 个内容段/);
    assert.equal(audit.possibleInitiallyHidden, true);
    assert.match(audit.tieredReviewText, /已找到 1 个可用片段.*检索覆盖待确认/);
    assert.equal(audit.tieredReviewText.includes("覆盖 100%"), false);
    assert.equal(audit.tieredReviewText.includes("匹配分"), false);
    assert.equal(audit.tieredReviewText.includes("项需复核"), false);
    assert.equal(audit.mergeAddButtonText, "");
    assert.deepEqual(audit.decoupledCheckedIds, ["match_1"]);
    assert.equal(audit.legacyBasketCount, 0);
    assert.equal(audit.basketAudit.hidden, false);
    assert.match(audit.basketAudit.summary, /成片清单.*1 段.*实际 1\.8 秒.*查看明细/s);
    assert.equal(audit.basketAudit.itemCount, 1);
    assert.match(audit.basketAudit.itemText, /找整理桌面的片段.*整理桌面物品.*01:16\.2.*01:18\.0/s);
    assert.equal(audit.basketAudit.generateLabel, "生成清单内容");
    assert.equal(audit.basketAudit.outputMode, "single_reel");
    assert.equal(audit.basketAudit.orderMode, "source");
    assert.deepEqual(audit.basketAudit.outputOptions, ["single_reel", "separate_events"]);
    assert.deepEqual(audit.basketAudit.orderOptions, ["source", "selection", "ai_plan"]);
    assert.equal(audit.basketInjectedIntoChat, false);
    assert.equal(audit.boundaryButtonText, "直接修剪");
    assert.equal(audit.boundaryPreviewButtonText, "预览");
    assert.equal(audit.boundaryCopyIsPreview, true);
    assert.equal(audit.directEntryInitiallyClosed, true);
    assert.equal(audit.directBoundaryMovedToInspector, true);
    assert.equal(audit.cardPreviewStayedClosed, true);
    assert.equal(audit.timelinePreviewStayedClosed, true);
    assert.equal(audit.timelineEvidencePanelOpen, true);
    assert.equal(audit.timelineBoundaryInspectorOpen, true);
    assert.equal(audit.evidenceClickLeavesEditorResumable, true);
    assert.deepEqual(audit.timelineBoundaryDialogActions, ["前一帧", "后一帧", "前一秒", "后一秒", "前一帧", "后一帧", "前一秒", "后一秒"]);
    assert.ok(Math.abs(audit.oneSecondNudgeDelta + 1) < 1e-6);
    assert.equal(audit.timelineDirectActionsVisible, true);
    assert.equal(audit.timelineSelectedSequence, "P01");
    assert.equal(audit.timelineTrimAvailable, true);
    assert.equal(audit.timelineTrimOpenedEditor, true);
    assert.equal(audit.boundarySurvivesRerender, true);
    assert.equal(audit.timelineBoundaryVisible, true);
    assert.match(audit.timelineBoundarySummary, /修剪「整理桌面物品」.*01:15\.2.*01:18\.0.*2\.80 秒/);
    assert.equal(audit.timelineTypedBoundaryStart, 76.6);
    assert.equal(audit.timelineSaveButtonText, "保存边界");
    assert.equal(audit.timelineHandleCount, 2);
    assert.notEqual(audit.timelineOverlayDisplay, "none");
    assert.notEqual(audit.timelineHandleDisplay, "none");
    assert.equal(audit.typedBoundaryStart, 76.4);
    assert.equal(audit.legacyBoundaryButtonCount, 0);
    assert.equal(audit.boundaryEditorVisible, true);
    assert.match(audit.boundaryFrameText, /25 fps.*40.0 ms/);
    assert.ok(Math.abs(audit.boundaryFrameDelta - .04) < 1e-6);
    assert.equal(audit.boundaryHasManualActions, true);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("confirmation dialog keeps every selected item and wraps long labels", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.evaluate(() => {
      const details = Array.from({ length: 25 }, (_, index) => `片段 ${index + 1} · 完整标题 ${"很长的内容说明".repeat(8)}`);
      const orderItems = details.map((label, index) => ({ id: `match_${index + 1}`, label, meta: `${index}:00 → ${index}:05` }));
      window.__dialogResult = requestActionConfirmation({
        title: "确认全部片段", summary: "应完整显示 25 条", details,
        orderMode: "selection", orderItems, showOrderOptions: true,
      });
    });
    await page.locator("#actionConfirm").waitFor({ state: "visible" });
    assert.equal(await page.locator("#actionConfirmDetails li").count(), 25);
    assert.match(await page.locator("#actionConfirmDetails li").last().textContent(), /片段 25/);
    assert.equal(await page.locator("#actionConfirmOrderList > div").count(), 25);
    assert.equal(await page.locator("#actionConfirmOrderList > div > span").first().evaluate((node) => getComputedStyle(node).whiteSpace), "normal");
    await page.locator("#actionConfirmCancel").click();
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("rendered content stays anchored to the source review timeline", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      document.querySelector("#reviewView")?.classList.remove("hidden");
      document.querySelector("#timelinePanel")?.classList.remove("hidden");
      const matches = [{
        id: "match_1", title: "嘉宾回答第一个问题", start: 10, end: 18, duration: 8,
        score: 96, reason: "完整回答", matchedEvidence: "回答内容一",
      }, {
        id: "match_2", title: "嘉宾回答第二个问题", start: 42, end: 51, duration: 9,
        score: 93, reason: "完整回答", matchedEvidence: "回答内容二",
      }];
      const baseJob = {
        id: "content_timeline_job", taskMode: "content_extract",
        status: "awaiting_content_confirmation", videoInfo: { duration: 90, has_audio: true },
        contentSearch: { id: "search_1", defaultSelectedIds: ["match_1"], candidates: matches },
        eventGroups: [], recommendedGroupIds: [], recommendedIndices: [], candidates: [],
      };
      currentJob = baseJob;
      currentOutput = null;
      currentEventGroup = null;
      currentEventSegment = null;
      currentCandidate = null;
      viewerMediaKind = "source";
      timelineViewStart = 0;
      timelineViewEnd = 90;
      waveformData = null;
      timelineAssets = null;
      updateTimeline();
      const review = {
        title: document.querySelector("#timelineTitle")?.textContent || "",
        hint: document.querySelector("#timelineHint")?.textContent || "",
        layout: document.querySelector("#timelineViewport")?.dataset.trackLayout || "",
        trackLabels: [...document.querySelectorAll("#timelineTrackLabels span")].map((node) => node.textContent),
        matchCards: document.querySelectorAll("#timelineLabels .timeline-label.content-match").length,
        clipBlocks: document.querySelectorAll("#timelineClips .timeline-clip").length,
        shotMarkers: document.querySelectorAll("#timelineShotMarkers .timeline-shot-marker").length,
        relations: document.querySelector("#timelineEventRelations")?.childElementCount || 0,
        firstCardText: document.querySelector("#timelineLabels .timeline-label")?.textContent || "",
      };
      let previewedMatchId = "";
      const originalPreviewContentMatch = previewContentMatch;
      previewContentMatch = (match) => { previewedMatchId = String(match?.id || ""); };
      document.querySelector("#timelineLabels .timeline-label")?.click();
      previewContentMatch = originalPreviewContentMatch;
      review.previewedMatchId = previewedMatchId;

      const groups = matches.map((match, index) => ({
        id: `content_group_${index + 1}`, title: match.title, summary: match.reason,
        score: match.score, actualDuration: match.duration, contentMatchId: match.id,
        segments: [{
          id: `segment_${index + 1}`, candidateId: match.id, start: match.start, end: match.end,
          duration: match.duration, role: "内容检索结果", reason: match.reason, score: match.score,
        }],
      }));
      const output = {
        filename: "content-v1.mp4", duration: 17, displayTitle: "内容视频 V1",
        segments: [{
          ...groups[1].segments[0], groupId: groups[1].id, chapterTitle: groups[1].title,
        }, {
          ...groups[0].segments[0], groupId: groups[0].id, chapterTitle: groups[0].title,
        }],
      };
      currentJob = {
        ...baseJob, status: "completed", eventGroups: groups,
        recommendedGroupIds: groups.map((group) => group.id),
      };
      currentOutput = output;
      currentCandidate = null;
      viewerMediaKind = "output";
      timelineCoordinateSpace = "source";
      timelineViewStart = 0;
      timelineViewEnd = 90;
      updateTimeline();
      const outputView = {
        title: document.querySelector("#timelineTitle")?.textContent || "",
        layout: document.querySelector("#timelineViewport")?.dataset.trackLayout || "",
        trackLabels: [...document.querySelectorAll("#timelineTrackLabels span")].map((node) => node.textContent),
        matches: [...document.querySelectorAll("#timelineLabels .timeline-label")].map((node) => node.textContent.trim()),
        composedSegments: document.querySelectorAll("#timelineLabels .timeline-sequence-segment").length,
        relationCurves: document.querySelectorAll("#timelineEventRelations .timeline-event-curve").length,
        summary: document.querySelector("#timelineEventSummaryTime")?.textContent || "",
        summaryButtons: document.querySelectorAll("#timelineEventSummaryText button").length,
        clock: document.querySelector("#timelineClockLabel")?.textContent || "",
        duration: document.querySelector("#timelineDuration")?.textContent || "",
        coordinateSwitches: document.querySelectorAll("#timelineCoordinateSwitch").length,
      };

      updateTimeline();
      const sourceView = {
        layout: document.querySelector("#timelineViewport")?.dataset.trackLayout || "",
        trackLabels: [...document.querySelectorAll("#timelineTrackLabels span")].map((node) => node.textContent),
        clock: document.querySelector("#timelineClockLabel")?.textContent || "",
        duration: document.querySelector("#timelineDuration")?.textContent || "",
      };

      currentJob = {
        ...currentJob, taskMode: "highlight", contentSearch: null,
        status: "awaiting_confirmation",
      };
      currentOutput = null;
      viewerMediaKind = "source";
      updateTimeline();
      const highlightView = {
        title: document.querySelector("#timelineTitle")?.textContent || "",
        layout: document.querySelector("#timelineViewport")?.dataset.trackLayout || "",
        trackLabels: [...document.querySelectorAll("#timelineTrackLabels span")].map((node) => node.textContent),
      };
      return { review, outputView, sourceView, highlightView };
    });
    assert.equal(audit.review.title, "内容检索时间轴");
    assert.match(audit.review.hint, /匹配片段/);
    assert.equal(audit.review.layout, "content-review");
    assert.deepEqual(audit.review.trackLabels, ["匹配片段", "画面", "音频"]);
    assert.equal(audit.review.matchCards, 2);
    assert.equal(audit.review.clipBlocks, 0);
    assert.equal(audit.review.shotMarkers, 0);
    assert.equal(audit.review.relations, 0);
    assert.match(audit.review.firstCardText, /P01.*嘉宾回答第一个问题.*已选/);
    assert.equal(audit.review.previewedMatchId, "match_1");
    assert.equal(audit.outputView.title, "内容视频来源时间线");
    assert.equal(audit.outputView.layout, "content-review");
    assert.deepEqual(audit.outputView.trackLabels, ["匹配片段", "画面", "音频"]);
    assert.equal(audit.outputView.matches.length, 2);
    assert.match(audit.outputView.matches[0], /P01.*嘉宾回答第一个问题.*已采用/);
    assert.match(audit.outputView.matches[1], /P02.*嘉宾回答第二个问题.*已采用/);
    assert.equal(audit.outputView.composedSegments, 0);
    assert.equal(audit.outputView.relationCurves, 0);
    assert.match(audit.outputView.summary, /2 个片段.*内容视频 17\.0 秒/);
    assert.equal(audit.outputView.summaryButtons, 0);
    assert.equal(audit.outputView.clock, "源片");
    assert.equal(audit.outputView.duration, "01:30.0");
    assert.equal(audit.outputView.coordinateSwitches, 0);
    assert.equal(audit.sourceView.layout, "content-review");
    assert.deepEqual(audit.sourceView.trackLabels, ["匹配片段", "画面", "音频"]);
    assert.equal(audit.sourceView.clock, "源片");
    assert.equal(audit.sourceView.duration, "01:30.0");
    assert.equal(audit.highlightView.title, "智能剪辑时间线");
    assert.equal(audit.highlightView.layout, "hierarchy");
    assert.deepEqual(audit.highlightView.trackLabels, ["事件", "镜头", "画面", "音频"]);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("highlight output uses the source event-shot timeline and jumps to source", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      document.querySelector("#reviewView")?.classList.remove("hidden");
      document.querySelector("#timelinePanel")?.classList.remove("hidden");
      const groups = [{
        id: "event_cook", title: "准备并完成早餐", score: 94,
        segments: [{
          id: "shot_prepare", candidateId: "candidate_1", start: 10, end: 15,
          duration: 5, role: "事件建立",
        }, {
          id: "shot_finish", candidateId: "candidate_2", start: 20, end: 26,
          duration: 6, role: "高潮",
        }],
      }, {
        id: "event_serve", title: "早餐装盘上桌", score: 91,
        segments: [{
          id: "shot_serve", candidateId: "candidate_3", start: 40, end: 44,
          duration: 4, role: "事件结果",
        }],
      }];
      currentJob = {
        id: "highlight_output_hierarchy", taskMode: "highlight", status: "awaiting_confirmation",
        videoInfo: { duration: 60, has_audio: true }, eventGroups: groups,
        recommendedGroupIds: groups.map((group) => group.id), candidates: [], recommendedIndices: [],
      };
      currentOutput = {
        filename: "highlight-v1.mp4", duration: 15, title: "高光成片",
        segments: [
          { ...groups[0].segments[0], eventGroupId: groups[0].id, eventTitle: groups[0].title },
          { ...groups[0].segments[1], eventGroupId: groups[0].id, eventTitle: groups[0].title },
          { ...groups[1].segments[0], eventGroupId: groups[1].id, eventTitle: groups[1].title },
        ],
      };
      currentEventGroup = null;
      currentEventSegment = null;
      currentCandidate = null;
      viewerMediaKind = "output";
      timelineCoordinateSpace = "source";
      timelineViewStart = 0;
      timelineViewEnd = 60;
      waveformData = null;
      timelineAssets = null;
      updateTimeline();
      let sourceJump = null;
      const originalPreviewCompositionSourceSegment = previewCompositionSourceSegment;
      previewCompositionSourceSegment = (composed, segmentIndex, sourceTime) => {
        sourceJump = { filename: composed?.filename, segmentIndex, sourceTime };
      };
      const output = {
        title: document.querySelector("#timelineTitle")?.textContent || "",
        layout: document.querySelector("#timelineViewport")?.dataset.trackLayout || "",
        labels: [...document.querySelectorAll("#timelineTrackLabels span")].map((node) => node.textContent),
        events: [...document.querySelectorAll("#timelineLabels .timeline-label")].map((node) => node.textContent.trim()),
        shots: [...document.querySelectorAll("#timelineShotMarkers .timeline-shot-marker")].map((node) => node.textContent.trim()),
        clipLefts: [...document.querySelectorAll("#timelineClips .timeline-clip")].map((node) => Number.parseFloat(node.style.left)),
        clock: document.querySelector("#timelineClockLabel")?.textContent || "",
        duration: document.querySelector("#timelineDuration")?.textContent || "",
        coordinateSwitches: document.querySelectorAll("#timelineCoordinateSwitch").length,
      };
      document.querySelector("#timelineShotMarkers .timeline-shot-marker")?.click();
      previewCompositionSourceSegment = originalPreviewCompositionSourceSegment;
      currentOutput = null;
      viewerMediaKind = "source";
      updateTimeline();
      const source = {
        layout: document.querySelector("#timelineViewport")?.dataset.trackLayout || "",
        labels: [...document.querySelectorAll("#timelineTrackLabels span")].map((node) => node.textContent),
        eventCount: document.querySelectorAll("#timelineLabels .timeline-label").length,
        shotCount: document.querySelectorAll("#timelineShotMarkers .timeline-shot-marker").length,
      };
      return { output, source, sourceJump };
    });
    assert.equal(audit.output.title, "成片来源时间线");
    assert.equal(audit.output.layout, "hierarchy");
    assert.deepEqual(audit.output.labels, ["事件", "镜头", "画面", "音频"]);
    assert.equal(audit.output.events.length, 2);
    assert.match(audit.output.events[0], /E1.*准备并完成早餐.*已采用/);
    assert.match(audit.output.events[1], /E2.*早餐装盘上桌.*已采用/);
    assert.equal(audit.output.shots.length, 3);
    assert.match(audit.output.shots[0], /镜头 01.*建立/);
    assert.match(audit.output.shots[1], /镜头 02.*高潮/);
    assert.match(audit.output.shots[2], /镜头 03.*结果/);
    assert.ok(Math.abs(audit.output.clipLefts[0] - 10 / 60 * 100) < .001);
    assert.ok(Math.abs(audit.output.clipLefts[1] - 20 / 60 * 100) < .001);
    assert.ok(Math.abs(audit.output.clipLefts[2] - 40 / 60 * 100) < .001);
    assert.equal(audit.output.clock, "源片");
    assert.equal(audit.output.duration, "01:00.0");
    assert.equal(audit.output.coordinateSwitches, 0);
    assert.deepEqual(audit.sourceJump, { filename: "highlight-v1.mp4", segmentIndex: 0, sourceTime: 10 });
    assert.equal(audit.source.layout, audit.output.layout);
    assert.deepEqual(audit.source.labels, audit.output.labels);
    assert.equal(audit.source.eventCount, 2);
    assert.equal(audit.source.shotCount, 3);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("review sample makes formal export primary and low-resolution download secondary", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      studio.classList.add("director-merged");
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      const sample = {
        filename: "review-sample.mp4", title: "节奏连贯版", displayName: "节奏连贯版",
        duration: 18, start: 0, end: 18, previewOnly: true, segments: [],
        downloadUrl: "/api/jobs/export-hierarchy/outputs/review-sample.mp4?download=1",
      };
      const formal = {
        filename: "formal.mp4", title: "节奏连贯版", displayName: "节奏连贯版",
        duration: 18, start: 0, end: 18, previewOnly: false, segments: [],
        downloadUrl: "/api/jobs/export-hierarchy/outputs/formal.mp4?download=1",
      };
      currentJob = {
        id: "export-hierarchy", taskMode: "highlight", status: "completed",
        videoInfo: { duration: 60, width: 1920, height: 1080, has_audio: true },
        eventGroups: [], candidates: [], recommendedGroupIds: [],
        outputVersions: [
          {
            id: "v001", number: 1, previewOnly: true, qualityStatus: "passed", outputs: [sample],
            reviewReport: {
              overallScore: 53, rubricScore: 61, deterministicPenalty: 7,
              scores: { content: 62, narrative: 55, rhythm: 64, continuity: 58, audiovisual: 72, goalMatch: 56 },
              summary: "高潮上下文需要修复",
            },
          },
          { id: "v002", number: 2, previewOnly: false, variantKind: "formal_export", qualityStatus: "passed", outputs: [formal] },
        ],
        outputs: [sample], messages: [], request: {},
      };
      renderOutputs(currentJob);
      selectOutput(sample.filename);
      const finalize = document.querySelector("#finalizePreviewButton");
      const download = document.querySelector("#downloadButton");
      const nearbyDownloads = [...document.querySelectorAll("#clipStrip [data-output-download]")].map((link) => ({
        filename: link.dataset.outputDownload,
        text: link.textContent,
        href: link.getAttribute("href"),
        aria: link.getAttribute("aria-label"),
      }));
      const preview = {
        finalizeText: finalize.textContent,
        finalizeTitle: finalize.title,
        finalizeAria: finalize.getAttribute("aria-label"),
        finalizeBackground: getComputedStyle(finalize).backgroundColor,
        downloadText: download.textContent,
        downloadTitle: download.title,
        downloadAria: download.getAttribute("aria-label"),
        downloadBackground: getComputedStyle(download).backgroundColor,
        downloadColor: getComputedStyle(download).color,
        secondaryClass: download.classList.contains("review-sample-download"),
        reviewScore: document.querySelector("#clipScore")?.textContent || "",
        reviewScoreTitle: document.querySelector("#clipScore")?.title || "",
        qualityText: document.querySelector(".output-quality-detail")?.textContent || "",
        dimensionCount: document.querySelectorAll(".output-review-dimensions > span").length,
        viewerBadge: document.querySelector("#viewerBadge")?.textContent || "",
      };
      selectOutput(formal.filename);
      const formalState = {
        finalizeHidden: finalize.classList.contains("hidden"),
        downloadText: download.textContent,
        secondaryClass: download.classList.contains("review-sample-download"),
      };
      selectOutput(sample.filename);
      return { preview, formalState, nearbyDownloads };
    });
    assert.equal(audit.preview.finalizeText, "确认版本并导出高清");
    assert.match(audit.preview.finalizeTitle, /源视频分辨率.*正式成片/);
    assert.equal(audit.preview.finalizeAria, "确认当前版本并导出高清正式成片");
    assert.equal(audit.preview.finalizeBackground, "rgb(168, 194, 105)");
    assert.equal(audit.preview.downloadText, "下载 V1 审核样片");
    assert.match(audit.preview.downloadTitle, /当前预览的 V1.*低分辨率审核样片.*不会创建正式高清成片/);
    assert.equal(audit.preview.downloadAria, "下载当前预览的 V1 低清审核样片，不导出高清版本");
    assert.equal(audit.preview.downloadBackground, "rgba(0, 0, 0, 0)");
    assert.equal(audit.preview.downloadColor, "rgb(131, 148, 155)");
    assert.equal(audit.preview.secondaryClass, true);
    assert.equal(audit.preview.reviewScore, "综合审片 53/100");
    assert.match(audit.preview.reviewScoreTitle, /内容、叙事、节奏、连续性、音画与目标匹配/);
    assert.match(audit.preview.qualityText, /内容62.*叙事55.*节奏64.*连续性58.*音画72.*目标匹配56/s);
    assert.match(audit.preview.qualityText, /维度加权 61\.0.*根因校准 -7\.0/);
    assert.equal(audit.preview.dimensionCount, 6);
    assert.match(audit.preview.viewerBadge, /V1.*样片.*质量通过/);
    assert.deepEqual(audit.formalState, {
      finalizeHidden: true, downloadText: "下载 V2 高清 MP4", secondaryClass: false,
    });
    assert.deepEqual(audit.nearbyDownloads.map((item) => item.filename).sort(), ["formal.mp4", "review-sample.mp4"]);
    assert.match(audit.nearbyDownloads.find((item) => item.filename === "formal.mp4").text, /下载 V2 高清/);
    assert.match(audit.nearbyDownloads.find((item) => item.filename === "review-sample.mp4").text, /下载 V1 样片/);
    assert.match(audit.nearbyDownloads.find((item) => item.filename === "formal.mp4").aria, /V2.*高清 MP4/);
    await page.screenshot({ path: join(projectRoot, "test-results/export-action-hierarchy.png"), fullPage: true });
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("switching from a rendered output to source preserves the mapped source time", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(async () => {
      document.querySelector("#reviewView")?.classList.remove("hidden");
      document.querySelector("#timelinePanel")?.classList.remove("hidden");
      currentJob = {
        id: "source_switch_job", filename: "源视频.mp4", taskMode: "highlight",
        status: "completed", previewReady: true, previewUrl: "/api/jobs/source_switch_job/preview",
        videoInfo: { duration: 90, width: 1920, height: 1080, has_audio: true },
        eventGroups: [], candidates: [], recommendedGroupIds: [], recommendedIndices: [], outputVersions: [],
      };
      currentOutput = { filename: "cut.mp4", duration: 10, segments: [{ start: 38, end: 48 }] };
      viewerMediaKind = "output";
      timelineViewStart = 0;
      timelineViewEnd = 20;
      waveformData = { duration: 90, minimums: [], maximums: [] };
      Object.defineProperty(mainVideo, "duration", { configurable: true, value: 90 });
      Object.defineProperty(mainVideo, "readyState", { configurable: true, value: 1 });
      Object.defineProperty(mainVideo, "currentTime", { configurable: true, writable: true, value: 5 });
      const originalSetMainVideoSource = setMainVideoSource;
      const originalRequestMainVideoAutoplay = requestMainVideoAutoplay;
      const originalTimelineAbsoluteTime = timelineAbsoluteTime;
      const originalSafePlay = safePlay;
      setMainVideoSource = () => true;
      requestMainVideoAutoplay = () => {};
      timelineAbsoluteTime = () => 43;
      safePlay = async () => true;
      const select = document.querySelector("#videoViewSelect");
      select.innerHTML = '<option value="source">源视频</option><option value="cut.mp4">成片</option>';
      select.value = "source";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      mainVideo.dispatchEvent(new Event("loadedmetadata"));
      const result = {
        mediaKind: viewerMediaKind,
        outputCleared: currentOutput === null,
        currentTime: Number(mainVideo.currentTime),
        timelineCurrent: document.querySelector("#timelineCurrent")?.textContent || "",
        viewStart: timelineViewStart,
        viewEnd: timelineViewEnd,
      };
      timelineAbsoluteTime = originalTimelineAbsoluteTime;
      currentEventGroup = { id: "event_preview", segments: [{ start: 60, end: 70 }] };
      viewerMediaKind = "event";
      previewCurrentVoice(64, 68);
      mainVideo.dispatchEvent(new Event("loadedmetadata"));
      await new Promise((resolve) => window.setTimeout(resolve, 100));
      result.voicePreview = {
        mediaKind: viewerMediaKind,
        currentTime: Number(mainVideo.currentTime),
        previewEnd: candidatePreviewEnd,
        timelineCurrent: document.querySelector("#timelineCurrent")?.textContent || "",
      };
      setMainVideoSource = originalSetMainVideoSource;
      requestMainVideoAutoplay = originalRequestMainVideoAutoplay;
      timelineAbsoluteTime = originalTimelineAbsoluteTime;
      safePlay = originalSafePlay;
      return result;
    });
    assert.equal(audit.mediaKind, "source");
    assert.equal(audit.outputCleared, true);
    assert.ok(Math.abs(audit.currentTime - 43) < .01);
    assert.equal(audit.timelineCurrent, "00:43.0");
    assert.ok(audit.viewStart <= 43 && audit.viewEnd >= 43);
    assert.deepEqual(audit.voicePreview, {
      mediaKind: "source", currentTime: 64, previewEnd: 68, timelineCurrent: "01:04.0",
    });
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("timeline keeps a story event when it contains additional unique shots", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      document.querySelector("#reviewView")?.classList.remove("hidden");
      document.querySelector("#timelinePanel")?.classList.remove("hidden");
      const sharedShot = {
        id: "shared_shot", start: 0, end: 6.6, duration: 6.6,
        role: "事件建立", reason: "下班回家",
      };
      currentJob = {
        id: "contained_event_timeline_job", taskMode: "highlight",
        status: "awaiting_confirmation", videoInfo: { duration: 81.6, has_audio: true },
        candidates: [], recommendedIndices: [],
        recommendedGroupIds: ["event_short", "event_story"],
        eventGroups: [{
          id: "event_short", title: "下班回家开启居家日常", score: 92,
          segments: [{ ...sharedShot, id: "short_shared_shot" }],
        }, {
          id: "event_story", title: "下班后居家日常完整记录", score: 90,
          segments: [
            { ...sharedShot, id: "story_shared_shot" },
            { id: "story_development", start: 51.7, end: 55.7, duration: 4, role: "发展" },
            { id: "story_result", start: 75.8, end: 79.4, duration: 3.6, role: "结果" },
          ],
        }],
      };
      currentOutput = null;
      currentEventGroup = null;
      currentEventSegment = null;
      currentCandidate = null;
      viewerMediaKind = "source";
      timelineViewStart = 0;
      timelineViewEnd = 81.6;
      waveformData = null;
      timelineAssets = null;
      updateTimeline();
      return {
        eventLabels: [...document.querySelectorAll("#timelineLabels .timeline-label")]
          .map((node) => node.textContent.trim()),
        clipCount: document.querySelectorAll("#timelineClips .timeline-clip").length,
        shotMarkerCount: document.querySelectorAll("#timelineShotMarkers .timeline-shot-marker").length,
      };
    });
    assert.equal(audit.eventLabels.length, 2);
    assert.match(audit.eventLabels[0], /下班回家开启居家日常/);
    assert.match(audit.eventLabels[1], /下班后居家日常完整记录/);
    assert.equal(audit.clipCount, 4);
    assert.equal(audit.shotMarkerCount, 4);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("question-only search does not render person or dialogue controls", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(100);
    const audit = await page.evaluate(() => {
      const job = {
        id: "question_only_job",
        taskMode: "content_extract",
        contentIndex: { persons: [{ id: "person_1", label: "人物 A", defaultLabel: "人物 A" }] },
        contentSearch: {
          id: "question_search",
          status: "needs_clarification",
          candidates: [],
          queryPlan: { predicates: [{ id: "q", kind: "question.evidence", value: "采访问题", source: "all" }] },
          executionPlan: { allowedCapabilities: [] },
          clarification: {
            kind: "evidence_type",
            question: "确认问题证据来源",
            message: "将同时检查口头提问和画面中的问题文字，只输出问题片段，不包含回答内容，也不要求确认人物。",
            options: [{
              id: "complete_required_set", label: "启用并继续（口头问题、画面问题）",
              capabilities: ["speech", "ocr"], recommended: true,
            }],
          },
        },
      };
      const document = new DOMParser().parseFromString(contentSearchReviewMarkup(job), "text/html");
      const blockedDocument = new DOMParser().parseFromString(contentSearchReviewMarkup({
        id: "blocked_job", taskMode: "content_extract",
        contentSearch: {
          id: "blocked_search", status: "needs_clarification", candidates: [],
          instruction: "找到女性说话的片段",
          clarification: {
            kind: "query_semantics", question: "请补充这次想找的内容关系",
            message: "person.speaking 必须引用人物目录中的 personRef。",
            validationErrors: [{
              code: "person_speaking_requires_person_ref",
              message: "person.speaking 必须引用人物目录中的 personRef。",
            }],
          },
        },
      }), "text/html");
      return {
        flow: document.querySelector(".content-flow-strip")?.textContent || "",
        text: document.body.textContent || "",
        dialogueControls: document.querySelectorAll("[data-content-dialogue-mode]").length,
        personPanels: document.querySelectorAll("[data-person-target-panel]").length,
        blockedTitle: blockedDocument.querySelector(".content-search-review.empty header strong")?.textContent || "",
        blockedState: blockedDocument.querySelector(".content-search-blocked-state")?.textContent || "",
        blockedText: blockedDocument.body.textContent || "",
      };
    });
    assert.equal(audit.flow, "");
    assert.match(audit.text, /只输出问题片段.*不包含回答内容/);
    assert.equal(audit.dialogueControls, 0);
    assert.equal(audit.personPanels, 0);
    assert.equal(audit.blockedTitle, "检索条件需要调整");
    assert.match(audit.blockedState, /检索尚未开始.*重新提交后会继续显示识别与扫描进度/s);
    assert.doesNotMatch(audit.blockedText, /person\.speaking|personRef/);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("speaker confirmation identifies the target anonymous person", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const host = document.createElement("section");
      host.innerHTML = contentSearchReviewMarkup({
        contentIndex: { persons: [
          { id: "person_1", label: "人物 A", defaultLabel: "人物 A", userLabeled: false },
          { id: "person_2", label: "人物 B", defaultLabel: "人物 B", userLabeled: false },
        ] },
        contentSearch: {
          status: "needs_clarification", candidates: [],
          executionPlan: { allowedCapabilities: ["person", "speech", "visual"] },
          clarification: {
            kind: "active_speaker_link", question: "请确认人物与说话人",
            message: "人物标签已经生效",
            options: [{
              id: "confirm_speaker_1", personId: "person_2", speakerRef: "Speaker 1",
              start: .6, end: 7.9, transcript: "Hello there",
            }],
          },
        },
      });
      document.body.append(host);
      const target = host.querySelector('[data-content-person-target-state="true"]');
      const targetChoiceDocument = new DOMParser().parseFromString(contentSearchReviewMarkup({
        contentIndex: { persons: [
          { id: "person_1", label: "人物 A", defaultLabel: "人物 A", userLabeled: false },
          { id: "person_2", label: "人物 B", defaultLabel: "人物 B", userLabeled: false },
        ] },
        contentSearch: {
          status: "needs_clarification", candidates: [], instruction: "找出目标人物说话的片段",
          executionPlan: { allowedCapabilities: ["person", "speech", "visual"] },
          clarification: { kind: "person_target", question: "请确认目标人物", message: "请选择人物卡" },
        },
      }), "text/html");
      const outputDocument = new DOMParser().parseFromString(contentOutputResultMarkup({
        id: "content_job", taskMode: "content_extract", status: "running", outputMode: "single_reel",
        outputVersions: [{
          id: "v001", number: 1, outputMode: "single_reel",
          outputs: [{ filename: "v001-content.mp4", duration: 54.4, segmentCount: 3, downloadUrl: "/api/jobs/content_job/outputs/v001-content.mp4?download=1" }],
        }],
      }), "text/html");
      const capabilityDocument = new DOMParser().parseFromString(contentSearchReviewMarkup({
        taskMode: "content_extract",
        contentSearch: {
          status: "needs_clarification", candidates: [], instruction: "找出人物 A 说话的片段",
          executionPlan: { allowedCapabilities: [] },
          clarification: {
            kind: "evidence_type", question: "确认识别依据",
            message: "这条描述要求同时核对人物、听到的对白、画面，单独选择其中一项不能完成检索。",
            alternativeHint: "如果只想按单一条件查找，请直接修改描述。",
            options: [{
              id: "mixed", label: "按必要依据查找（人物、听到的对白、画面）",
              capabilities: ["person", "speech", "visual"], recommended: true, disabled: false,
            }, {
              id: "person", label: "人物", capabilities: ["person"], disabled: true,
              disabledReason: "还需同时启用听到的对白、画面",
            }],
          },
        },
      }), "text/html");
      return {
        targetId: target?.dataset.contentPerson || "",
        targetText: target?.textContent || "",
        guidance: host.querySelector(".content-search-review.empty > p")?.textContent || "",
        explanation: host.querySelector(".content-speaker-explanation")?.textContent || "",
        previewLabel: host.querySelector("[data-content-speaker-preview]")?.textContent || "",
        confirmLabel: host.querySelector("[data-content-speaker-confirm]")?.textContent || "",
        confirmCount: host.querySelectorAll("[data-content-speaker-confirm]").length,
        selectedTargetButton: target?.querySelector(".content-person-choice span")?.textContent || "",
        anonymousTargetButtons: [...targetChoiceDocument.querySelectorAll("[data-person-target]")].map((input) => ({
          personId: input.value,
          checked: input.checked,
        })),
        anonymousLabelButtons: [...targetChoiceDocument.querySelectorAll("[data-person-label]")].map((button) => button.textContent),
        anonymousTargetHelp: targetChoiceDocument.querySelector(".content-person-panel > p")?.textContent || "",
        outputCardText: outputDocument.querySelector(".content-output-result-card")?.textContent || "",
        outputPreviewFilename: outputDocument.querySelector("[data-auto-output]")?.dataset.autoOutput || "",
        outputDownloadFilename: outputDocument.querySelector("[data-output-download]")?.dataset.outputDownload || "",
        outputDownloadText: outputDocument.querySelector("[data-output-download]")?.textContent || "",
        capabilityTitle: capabilityDocument.querySelector(".content-search-review.empty strong")?.textContent || "",
        completeCapabilityText: capabilityDocument.querySelector("[data-content-evidence-choice]")?.textContent || "",
        personCapabilityDisabled: capabilityDocument.querySelector(".content-evidence-option.unavailable")?.disabled || false,
        personCapabilityReason: capabilityDocument.querySelector(".content-evidence-option.unavailable small")?.textContent || "",
        capabilityAlternative: capabilityDocument.querySelector(".content-capability-alternative")?.textContent || "",
      };
    });
    assert.equal(audit.targetId, "person_2");
    assert.match(audit.targetText, /本次检索人物.*人物 B.*已选择/);
    assert.match(audit.guidance, /本次目标是“人物 B”.*无需先修改名称/);
    assert.match(audit.explanation, /画面人物簇 2 个.*逐字稿 Speaker 1 组.*不等于真实人数.*请以预览的音画内容为准/);
    assert.equal(audit.previewLabel, "预览音画");
    assert.equal(audit.confirmLabel, "确认 人物 B 对应 Speaker 1");
    assert.equal(audit.confirmCount, 1);
    assert.equal(audit.selectedTargetButton, "已选择");
    assert.deepEqual(audit.anonymousTargetButtons, [
      { personId: "person_1", checked: false },
      { personId: "person_2", checked: false },
    ]);
    assert.deepEqual(audit.anonymousLabelButtons, ["添加标签（可选）", "添加标签（可选）"]);
    assert.match(audit.anonymousTargetHelp, /可选择一个或多个人物.*添加项目内标签是可选操作/);
    assert.match(audit.outputCardText, /内容视频已生成.*V1.*3 个已确认片段.*点击预览/);
    assert.equal(audit.outputPreviewFilename, "v001-content.mp4");
    assert.equal(audit.outputDownloadFilename, "v001-content.mp4");
    assert.equal(audit.outputDownloadText, "下载 V1 高清");
    assert.equal(audit.capabilityTitle, "确认识别依据");
    assert.match(audit.completeCapabilityText, /按必要依据查找.*人物.*听到的对白.*画面/);
    assert.equal(audit.personCapabilityDisabled, true);
    assert.match(audit.personCapabilityReason, /还需同时启用听到的对白、画面/);
    assert.match(audit.capabilityAlternative, /只想按单一条件查找.*修改描述/);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("anonymous person selector submits multiple ids and match mode", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.evaluate(() => {
      const job = {
        id: "target_click_job",
        taskMode: "content_extract",
        status: "awaiting_content_confirmation",
        stage: "content_search_ready",
        messages: [],
        request: {},
        contentPersonTargetHistory: [{
          id: "selection_1", personIds: ["person_1", "person_2"],
          labels: ["人物 A", "人物 B"], matchMode: "any",
        }],
        contentIndex: { persons: [
          { id: "person_1", label: "人物 A", defaultLabel: "人物 A", userLabeled: false },
          { id: "person_2", label: "人物 B", defaultLabel: "人物 B", userLabeled: false },
        ] },
        contentSearch: {
          status: "needs_clarification", candidates: [], instruction: "找出目标人物说话的片段",
          executionPlan: { allowedCapabilities: ["person", "speech", "visual"] },
          clarification: { kind: "person_target", question: "请确认目标人物", message: "请选择人物卡" },
        },
      };
      currentJob = job;
      renderConversation(job);
    });
    const historyPresentation = await page.locator(".content-person-history-row").evaluate((row) => {
      const button = row.querySelector("[data-person-history-target]");
      const style = getComputedStyle(button);
      return {
        text: row.textContent.replace(/\s+/g, "").trim(),
        color: style.color,
        background: style.backgroundColor,
        border: style.borderTopColor,
      };
    });
    assert.match(historyPresentation.text, /人物A、人物B任一人物出现查看这些片段/);
    assert.equal(historyPresentation.color, "rgb(184, 207, 206)");
    assert.equal(historyPresentation.background, "rgb(21, 38, 45)");
    assert.equal(historyPresentation.border, "rgba(0, 0, 0, 0)");
    await page.evaluate(() => {
      const inputs = [...document.querySelectorAll("[data-person-target]")];
      inputs.forEach((input) => {
        input.checked = true;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
      const mode = document.querySelector('[data-person-match-mode][value="all"]');
      mode.checked = true;
      mode.dispatchEvent(new Event("change", { bubbles: true }));
      document.querySelector("[data-person-target-confirm]").click();
    });
    for (let attempt = 0; attempt < 20 && !stub.requests.some((item) => item.path.endsWith("/content-search/target-person")); attempt += 1) {
      await page.waitForTimeout(25);
    }
    const targetRequest = stub.requests.find((item) => item.path.endsWith("/content-search/target-person"));
    assert.deepEqual(targetRequest?.body, {
      personIds: ["person_1", "person_2"], matchMode: "all",
    });
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("subtitle review drawer supports readable cue editing and split controls", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.evaluate(() => {
      subtitleReviewDraft = {
        id: "sub_1234567890abcdef", revision: 1, status: "draft",
        globalStyle: { preset: "clean", fontSizeRatio: .04, horizontal: "center", vertical: "bottom", offsetXRatio: 0, offsetYRatio: 0 },
        cueStyleOverrides: {},
        correctionContext: { generatedAt: "2026-08-25T00:00:00Z", summary: "产品功能说明", terms: [{ term: "ClipTalk", evidence: "屏幕文字重复出现" }] },
        cues: [{ id: "cue_test", outputIndex: 0, start: 0, end: 3, sourceStart: 12, sourceEnd: 15, text: "这是需要人工校对的一条字暮", originalText: "这是需要人工校对的一条字暮", suggestionStatus: "pending", suggestedText: "这是需要人工校对的一条字幕", suggestionRisk: "low", suggestionConfidence: .96, suggestionReason: "全文重复", suggestionEvidence: ["相邻字幕使用“字幕”"], showSpeakerLabel: true, speakerLabel: "说话人 B", speakerColor: "0x8FD3FF" }],
      };
      currentJob = { id: "portrait_subtitle", videoInfo: { width: 576, height: 1024 } };
      subtitleReviewActiveCueId = "cue_test";
      document.querySelector("#subtitleReview").classList.remove("hidden");
      renderSubtitleCueList();
    });
    const panel = page.locator(".subtitle-review-panel");
    await panel.waitFor({ state: "visible" });
    const initial = await page.evaluate(() => ({
      panelWidth: document.querySelector(".subtitle-review-panel").getBoundingClientRect().width,
      textareaSize: Number.parseFloat(getComputedStyle(document.querySelector(".subtitle-cue textarea")).fontSize),
      commandPlaceholder: document.querySelector("#subtitleCommandInput").placeholder,
      footerVisible: document.querySelector(".subtitle-review-footer").getBoundingClientRect().height > 0,
      previewText: document.querySelector("#subtitlePreviewText").textContent,
      previewColor: getComputedStyle(document.querySelector("#subtitlePreviewText")).color,
      previewFontSize: Number.parseFloat(getComputedStyle(document.querySelector("#subtitlePreviewText")).fontSize),
      previewMaxWidth: Number.parseFloat(getComputedStyle(document.querySelector("#subtitlePreviewText")).maxWidth),
      stageWidth: document.querySelector("#subtitlePreviewStage").clientWidth,
      contextText: document.querySelector("#subtitleCorrectionContext").textContent,
      safeButtonText: document.querySelector("#subtitleAcceptSafeButton").textContent,
      riskText: document.querySelector(".subtitle-suggestion-head span").textContent,
    }));
    await page.locator("#subtitleAcceptSafeButton").click();
    assert.equal(await page.locator(".subtitle-suggestion").count(), 0);
    await page.locator("[data-cue-split]").click();
    assert.equal(await page.locator(".subtitle-cue").count(), 2);
    assert.ok(initial.panelWidth >= 700);
    assert.ok(initial.textareaSize >= 15);
    assert.match(initial.commandPlaceholder, /字号 48px/);
    assert.equal(initial.footerVisible, true);
    assert.match(initial.previewText, /^说话人 B：/);
    assert.equal(initial.previewColor, "rgb(143, 211, 255)");
    assert.ok(initial.previewFontSize < 12, `portrait preview font should use the short edge, got ${initial.previewFontSize}`);
    assert.ok(initial.previewMaxWidth < initial.stageWidth * .4, "preview text must stay inside the contained portrait video");
    assert.match(initial.contextText, /ClipTalk/);
    assert.match(initial.safeButtonText, /1/);
    assert.match(initial.riskText, /低风险/);
    assert.deepEqual(pageErrors, []);
    await panel.screenshot({ path: join(projectRoot, "test-results/subtitle-review-drawer.png") });
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("AI edit proposal renders a continuous output-time track and locates its source clip", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const proposalJob = {
        pendingEditProposal: {
          id: "proposal_test", status: "pending", title: "收紧开场",
          preview: {
            totalOutputDuration: 7,
            outputs: [{
              id: "proposal_reel", label: "提案成片", duration: 7,
              schedule: [
                { segmentId: "shot_2", objectId: "shot_2", objectType: "segment", groupId: "event_1", label: "发展", state: "moved", sourceStart: 20, sourceEnd: 24, outputStart: 0, outputEnd: 4, effectiveDuration: 4, transitionOverlap: 0, playbackRate: 1, transitionType: "cut", order: 1 },
                { segmentId: "shot_1", objectId: "shot_1", objectType: "segment", groupId: "event_1", label: "开场", state: "adjusted", sourceStart: 10, sourceEnd: 13, outputStart: 4, outputEnd: 7, effectiveDuration: 3, transitionOverlap: 0, playbackRate: 1, transitionType: "cut", order: 2 },
              ],
            }],
          },
        },
      };
      document.querySelector("#reviewView")?.classList.remove("hidden");
      document.querySelector("#timelinePanel")?.classList.remove("hidden");
      renderTimelineProposalPreview(proposalJob);
      const proposalTrack = document.querySelector("#timelineProposalTrack");
      document.body.append(proposalTrack);
      proposalTrack.style.cssText += ";position:fixed;left:20px;top:20px;width:900px;z-index:500";
      const blocks = [...document.querySelectorAll(".proposal-schedule-block")];
      const calls = {};
      const originals = { showSource, setTimelineView, seekSourceTime, updateTimeline };
      showSource = (options) => { calls.showSource = options; };
      setTimelineView = (start, end) => { calls.view = [start, end]; };
      seekSourceTime = (second) => { calls.seek = second; };
      updateTimeline = () => { calls.updated = true; };
      blocks[0]?.click();
      ({ showSource, setTimelineView, seekSourceTime, updateTimeline } = originals);
      return {
        hidden: document.querySelector("#timelineProposalTrack").classList.contains("hidden"),
        blockCount: blocks.length,
        firstLeft: Number.parseFloat(blocks[0]?.style.left || "-1"),
        secondLeft: Number.parseFloat(blocks[1]?.style.left || "-1"),
        baselineWidth: document.querySelector(".proposal-output-line > i")?.getBoundingClientRect().width || 0,
        duration: document.querySelector("#timelineProposalDuration")?.textContent || "",
        calls,
      };
    });
    assert.equal(audit.hidden, false);
    assert.equal(audit.blockCount, 2);
    assert.equal(audit.firstLeft, 0);
    assert.ok(audit.secondLeft > 50 && audit.secondLeft < 60);
    assert.ok(audit.baselineWidth > 200);
    assert.match(audit.duration, /00:07/);
    assert.deepEqual(audit.calls.showSource, { autoplay: false });
    assert.equal(audit.calls.seek, 20);
    assert.equal(audit.calls.updated, true);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});


test("task display keeps waiting and failure states ahead of existing outputs", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const outputs = [{ filename: "one.mp4" }, { filename: "two.mp4" }];
      const failed = displayStatusForJob({ status: "failed", outputs, outputVersions: [{ number: 1, outputs }] });
      const waiting = displayStatusForJob({ status: "awaiting_confirmation", outputs, outputVersions: [{ number: 1, outputs }] });
      const composing = displayStatusForJob({
        status: "awaiting_confirmation",
        stage: "auto_composition",
        autoComposition: { status: "running", completedVersions: 1, totalVersions: 2 },
      });
      const canonicalComposing = displayStatusForJob({
        status: "awaiting_confirmation",
        execution: {
          schemaVersion: 1, status: "running", operation: "quality_review", active: true,
          detail: "正在复核成片", outcome: "none", progress: { completed: 1, total: 3 }, result: {}, capabilities: {},
        },
      });
      const rejected = displayStatusForJob({
        status: "awaiting_confirmation",
        execution: {
          schemaVersion: 1, status: "waiting_user", operation: "auto_composition", active: false,
          outcome: "no_acceptable_output", progress: {}, result: { qualityRejectedCount: 2 }, capabilities: {},
        },
      });
      const queued = displayStatusForJob({ status: "queued", outputs, outputVersions: [{ number: 1, outputs }] });
      const queuedJob = {
        id: "queued-progress", filename: "等待测试.mp4", status: "queued", stage: "queued",
        taskMode: "highlight", workflowKind: "highlight", progress: 0,
        detail: "任务已进入队列", currentAction: "任务已进入队列", model: "系统",
        processingElapsedSeconds: 0, processingTimingVersion: 1,
        progressFacts: {
          workflow: { fraction: 0 }, stage: { label: "等待开始", mode: "indeterminate" },
          timing: { processingElapsedSeconds: 0, processingTimingVersion: 1 },
          activity: { detail: "任务已进入队列", model: "系统" },
        },
      };
      const progressHost = document.createElement("div");
      progressHost.innerHTML = inlineAnalysisProgressMarkup(queuedJob);
      const queuedProgress = {
        workflow: progressHost.querySelector("[data-inline-workflow-percent]")?.textContent,
        stage: progressHost.querySelector("[data-inline-stage-label]")?.textContent,
        detail: progressHost.querySelector("[data-inline-detail]")?.textContent,
        fact: progressHost.querySelector("[data-inline-stage-progress]")?.textContent,
        elapsed: progressHost.querySelector("[data-inline-elapsed]")?.textContent,
        eta: progressHost.querySelector("[data-inline-eta]")?.textContent,
        currentSteps: progressHost.querySelectorAll(".inline-stage-chain .current").length,
      };
      renderDirectorTaskSummary(queuedJob);
      const queuedSummary = document.querySelector("#directorTaskSummary")?.textContent;
      const separate = displayStatusForJob({
        status: "completed",
        outputVersions: [
          { number: 1, outputs: [{ filename: "one.mp4" }] },
          { number: 2, outputs: [{ filename: "two-a.mp4" }, { filename: "two-b.mp4" }] },
        ],
      });
      return { failed, waiting, composing, canonicalComposing, rejected, queued, queuedProgress, queuedSummary, separate };
    });
    assert.match(audit.failed.text, /处理失败/);
    assert.match(audit.failed.text, /已保留 1 个版本 · 2 条视频/);
    assert.match(audit.waiting.text, /等待确认高光/);
    assert.match(audit.waiting.text, /1 个版本 · 2 条视频/);
    assert.equal(audit.composing.text, "正在生成成片 · 已完成 1/2 个");
    assert.equal(audit.composing.running, true);
    assert.equal(audit.canonicalComposing.text, "正在审片 · 已完成 1/3 个");
    assert.match(audit.rejected.text, /未通过质量门/);
    assert.match(audit.queued.text, /排队中/);
    assert.equal(audit.queued.running, false);
    assert.deepEqual(audit.queuedProgress, {
      workflow: "排队中",
      stage: "当前阶段 · 等待处理",
      detail: "任务已提交，正在等待后台开始处理",
      fact: "等待后台开始处理",
      elapsed: "处理用时尚未开始",
      eta: "排队时间不计入处理用时",
      currentSteps: 0,
    });
    assert.match(audit.queuedSummary, /当前阶段 · 等待处理.*任务已提交，正在等待后台开始处理/s);
    assert.match(audit.separate.text, /已完成 · 2 个版本 · 3 条视频/);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("raw visual candidates can be confirmed without subtitle-scope errors", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  const requests = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/jobs/raw_candidate_job/confirm", async (route) => {
      requests.push(JSON.parse(route.request().postData() || "{}"));
      await route.fulfill({
        status: 202, contentType: "application/json",
        body: JSON.stringify({ job: { id: "raw_candidate_job", status: "running", candidates: [] } }),
      });
    });
    await page.evaluate(async () => {
      currentJob = {
        id: "raw_candidate_job", status: "awaiting_confirmation", filename: "source.mp4",
        candidates: [{ index: 0, title: "精彩镜头", start: 2, end: 6, duration: 4 }],
        eventGroups: [], outputVersions: [], outputs: [],
      };
      requestActionConfirmation = async () => ({ orderMode: "selection", orderedItems: [{ id: "0" }] });
      await confirmCandidates([0], "single_reel");
    });
    assert.deepEqual(pageErrors, []);
    assert.deepEqual(requests, [{ indices: [0], outputMode: "single_reel", orderMode: "selection" }]);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("derived task conversation collapses inherited history and exposes quality recovery", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const job = {
        id: "quality-child", taskMode: "highlight", status: "awaiting_confirmation", stage: "review",
        handoff: { fromJobId: "content-parent", fromTaskMode: "content_extract", toTaskMode: "highlight" },
        messages: [
          { id: "old", role: "user", text: "找到煎鸡蛋", inherited: true },
          { id: "new", role: "user", text: "全片生成高光", inherited: false },
        ],
        eventGroups: [{ id: "event_1", title: "事件一", summary: "事件", score: 90, actualDuration: 5, segments: [] }],
        recommendedGroupIds: ["event_1"], candidates: [], request: {}, outputVersions: [], outputs: [],
        autoComposition: { status: "completed", rejectedVersionCount: 2 },
        execution: {
          schemaVersion: 1, status: "waiting_user", operation: "auto_composition", active: false,
          outcome: "no_acceptable_output", progress: {},
          result: {
            outputCount: 0, qualityRejectedCount: 2, qualityReasons: ["镜头衔接不完整"],
            qualityIssues: [{ severity: "critical", outputTime: 20.8, duplicateCount: 3, description: "动作在操作中途截断，缺少完成结果" }],
            qualityRepair: { status: "not_improved", detail: "返修没有明确提升" },
          },
          capabilities: { canCancel: true },
        },
      };
      currentJob = job;
      renderConversation(job);
      return {
        historySummary: document.querySelector(".conversation-task-history summary")?.textContent || "",
        historyOpen: document.querySelector(".conversation-task-history details")?.open,
        boundary: document.querySelector(".conversation-task-history > p")?.textContent || "",
        quality: document.querySelector(".quality-gate-result-card")?.textContent || "",
        actionCount: document.querySelectorAll(".quality-gate-result-card button").length,
      };
    });
    assert.match(audit.historySummary, /此前任务对话.*1 条/);
    assert.equal(audit.historyOpen, false);
    assert.match(audit.boundary, /内容探索.*高光剪辑/);
    assert.match(audit.quality, /2 个独立样片均未达到展示标准/);
    assert.match(audit.quality, /镜头衔接不完整/);
    assert.match(audit.quality, /成片 00:20\.8/);
    assert.match(audit.quality, /已合并 3 条重复诊断/);
    assert.match(audit.quality, /动作在操作中途截断/);
    assert.match(audit.quality, /自动返修并复审/);
    assert.match(audit.quality, /重新规划剪辑方案/);
    assert.equal(audit.actionCount, 2);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("failed automatic quality keeps rendered drafts visible for manual review", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const output = { filename: "draft.mp4", duration: 23, previewOnly: true, manualReviewRequired: true };
      const version = {
        id: "v001", number: 1, previewOnly: true, manualReviewRequired: true,
        reviewStatus: "needs_user_review", displayName: "完整事件版", sourceLabel: "视觉推荐",
        qualityGate: { passed: false, recommended: false, score: 48 }, outputs: [output],
      };
      const job = {
        id: "quality-manual", taskMode: "highlight", status: "awaiting_confirmation", stage: "auto_composition",
        messages: [], eventGroups: [], recommendedGroupIds: [], candidates: [], request: { autoVariantCount: 1 },
        outputs: [output], outputVersions: [version],
        autoComposition: {
          status: "completed", phase: "done", versions: [{ displayName: "完整事件版", sourceLabel: "视觉推荐" }],
          manualReviewRequired: true, manualReviewVersionId: "v001",
        },
        execution: {
          schemaVersion: 1, status: "waiting_user", operation: "auto_composition", active: false,
          outcome: "no_acceptable_output", progress: {},
          result: { outputCount: 1, qualityPassedCount: 0, qualityRejectedCount: 1, qualityReasons: ["得分低于当前展示门槛"], qualityIssues: [] },
          capabilities: { canCancel: true },
        },
      };
      currentJob = job;
      renderConversation(job);
      renderOutputs(job);
      return {
        quality: document.querySelector(".quality-gate-result-card")?.textContent || "",
        summary: document.querySelector(".auto-compose-result-card")?.textContent || "",
        chatVersionCount: document.querySelectorAll(".auto-compose-result-card .auto-version-button").length,
        version: document.querySelector("#clipStrip .clip-version-button")?.textContent || "",
        outputName: document.querySelector("#clipStrip .clip-version-button")?.dataset.autoOutput || "",
      };
    });
    assert.match(audit.quality, /所有已成功渲染的独立方案都已保留/);
    assert.match(audit.summary, /1\s*个版本/);
    assert.match(audit.summary, /0\s*个通过/);
    assert.match(audit.summary, /1\s*个需复核/);
    assert.equal(audit.chatVersionCount, 0);
    assert.match(audit.version, /需人工复核/);
    assert.equal(audit.outputName, "draft.mp4");
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("mixed quality results expose passed and manual-review variants together", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const makeVersion = (number, passed) => {
        const filename = `variant-${number}.mp4`;
        const output = {
          filename, duration: 22 + number, previewOnly: true,
          ...(passed ? {} : { manualReviewRequired: true }),
        };
        return {
          id: `v00${number}`, number, previewOnly: true,
          displayName: `独立方案 ${number}`, sourceLabel: number === 1 ? "视觉推荐" : "剪辑规划",
          recommended: passed, outputs: [output],
          qualityGate: { passed, recommended: passed, score: passed ? 86 : 68 - number },
          ...(passed ? {} : {
            manualReviewRequired: true, reviewStatus: "needs_user_review",
            recommendationReason: "未通过自动质量门，保留为可预览的人工复核版本",
          }),
        };
      };
      const versions = [makeVersion(1, true), makeVersion(2, false), makeVersion(3, false)];
      const job = {
        id: "mixed-quality", taskMode: "highlight", status: "awaiting_confirmation", stage: "auto_composition",
        messages: [], eventGroups: [], recommendedGroupIds: [], candidates: [], request: { autoVariantCount: 3 },
        outputs: versions[0].outputs, outputVersions: versions,
        autoComposition: {
          status: "completed", phase: "done",
          versions: versions.map(({ displayName, sourceLabel, manualReviewRequired, qualityGate }) => ({
            displayName, sourceLabel, manualReviewRequired, qualityGate,
          })),
          qualityPassedCount: 1, manualReviewRequired: true,
          manualReviewVersionIds: ["v002", "v003"],
        },
        execution: {
          schemaVersion: 1, status: "waiting_user", operation: "auto_composition", active: false,
          outcome: "output_ready", progress: {},
          result: { outputCount: 3, qualityPassedCount: 1, qualityRejectedCount: 2 },
          capabilities: { canCancel: true },
        },
      };
      currentJob = job;
      renderConversation(job);
      renderOutputs(job);
      const details = [...document.querySelectorAll("#clipStrip .clip-version-button")].map((button) => ({
        text: button.textContent || "", filename: button.dataset.autoOutput || "",
      }));
      document.querySelector("[data-open-output-versions]")?.click();
      return {
        summary: document.querySelector(".auto-compose-result-card")?.textContent || "",
        chatVersionCount: document.querySelectorAll(".auto-compose-result-card .auto-version-button").length,
        details,
        openedCompose: directorStage === "compose",
      };
    });
    assert.match(audit.summary, /3\s*个版本/);
    assert.match(audit.summary, /1\s*个通过/);
    assert.match(audit.summary, /2\s*个需复核/);
    assert.equal(audit.chatVersionCount, 0);
    assert.equal(audit.details.length, 3);
    assert.equal(audit.details.filter((item) => /AI 推荐/.test(item.text)).length, 1);
    assert.equal(audit.details.filter((item) => /需人工复核/.test(item.text)).length, 2);
    assert.deepEqual(audit.details.map((item) => item.filename).sort(), [
      "variant-1.mp4", "variant-2.mp4", "variant-3.mp4",
    ]);
    assert.equal(audit.openedCompose, true);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("target-length auto cuts do not report the full recommendation pool as unfinished", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const ranges = [[30.01, 62.56], [253.02, 269.09], [321.12, 331.29], [472.55, 484.24], [524.289, 537.99]];
      const eventGroups = ranges.map(([start, end], index) => ({
        id: `event_${index}`, title: `推荐事件 ${index + 1}`, summary: "完整语义事件",
        score: 96 - index, actualDuration: end - start,
        segments: [{ id: `segment_${index}`, start, end, duration: end - start, role: "主体镜头" }],
      }));
      const outputRanges = [ranges.slice(0, 3), [ranges[0], ranges[2], ranges[3]], [ranges[1], ranges[3], ranges[4]]];
      const outputVersions = outputRanges.map((items, index) => {
        const segments = items.map(([start, end], segmentIndex) => ({
          id: `output_${index}_${segmentIndex}`, start, end, duration: end - start,
        }));
        return {
          id: `v00${index + 1}`, number: index + 1, previewOnly: true,
          generationBatchId: "batch_1", strategyKey: ["vlm", "narrative", "emotion"][index],
          displayName: ["事件核心版", "AI · 叙事完整版", "AI · 情绪高潮版"][index],
          qualityStatus: "passed", qualityGate: { passed: true, recommended: index === 2 },
          createdAt: "2026-08-25T10:00:00Z",
          outputs: [{ filename: `cut-${index + 1}.mp4`, duration: [60.3, 62.3, 59.8][index], previewOnly: true, segments }],
        };
      });
      const job = {
        id: "recommendation-pool", taskMode: "highlight", status: "awaiting_confirmation", stage: "review",
        messages: [
          { id: "a1", role: "assistant", kind: "auto-compose", createdAt: "2026-08-25T09:58:00Z", text: "视觉模型已完成事件发现，正在生成完整事件版。" },
          { id: "a2", role: "assistant", kind: "result", createdAt: "2026-08-25T09:59:00Z", text: "AI 样片 V1 已就绪：包含 3 个高光事件。" },
          { id: "a3", role: "assistant", kind: "composition-review-result", createdAt: "2026-08-25T10:00:00Z", text: "自动成片质量检查完成，3 个版本通过。" },
        ], eventGroups, recommendedGroupIds: eventGroups.map((group) => group.id),
        candidates: [], request: { totalTargetSeconds: 60 }, totalTargetSeconds: 60,
        allocatedTotalSeconds: 84.181, durationTolerance: .1,
        outputs: outputVersions[0].outputs, outputVersions,
        autoComposition: {
          status: "completed", phase: "done", batches: [{ id: "batch_1", mode: "initial" }],
          versions: outputVersions.map((version) => ({ displayName: version.displayName })),
        },
        execution: { active: false, status: "waiting_user", operation: "auto_composition", progress: {}, result: {} },
      };
      currentJob = job;
      renderConversation(job);
      const initial = {
        recommendation: document.querySelector(".event-recommendation")?.textContent || "",
        callout: document.querySelector(".timeline-render-pending")?.textContent || "",
        result: document.querySelector(".auto-compose-result-card")?.textContent || "",
        stale: document.querySelector(".auto-compose-result-card")?.classList.contains("timeline-stale") || false,
        dockVisible: getComputedStyle(document.querySelector("#autoCompositionDock")).display !== "none",
        archiveCount: document.querySelectorAll(".auto-compose-result-log .auto-compose-activity-item").length,
        archiveOpen: document.querySelector(".auto-compose-result-log")?.open || false,
      };
      job.timelineUndo = [{ createdAt: "2026-08-25T10:01:00Z", target: "eventGroups" }];
      currentJob = job;
      renderConversation(job);
      const edited = {
        callout: document.querySelector(".timeline-render-pending")?.textContent || "",
        stale: document.querySelector(".auto-compose-result-card")?.classList.contains("timeline-stale") || false,
      };
      return { initial, edited };
    });
    assert.match(audit.initial.recommendation, /完整推荐事件池\s*84\.2 秒/);
    assert.match(audit.initial.recommendation, /并非尚未完成的成片/);
    assert.match(audit.initial.callout, /可选：全部推荐事件版/);
    assert.match(audit.initial.callout, /比目标长 24\.2 秒/);
    assert.doesNotMatch(audit.initial.recommendation, /推荐时间轴尚未生成/);
    assert.match(audit.initial.result, /已按 60 秒目标取舍并重编排/);
    assert.match(audit.initial.result, /查看完整执行记录\s*3 条/);
    assert.equal(audit.initial.stale, false);
    assert.equal(audit.initial.dockVisible, false);
    assert.equal(audit.initial.archiveCount, 3);
    assert.equal(audit.initial.archiveOpen, false);
    assert.match(audit.edited.callout, /当前修改尚未生成/);
    assert.equal(audit.edited.stale, true);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("exhausted automatic repair explains evidence shortage without offering the same replan again", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const job = {
        id: "quality-exhausted", taskMode: "highlight", status: "awaiting_confirmation", stage: "review",
        messages: [], eventGroups: [{ id: "event_1", title: "事件一", summary: "事件", score: 90, actualDuration: 5, segments: [] }], recommendedGroupIds: ["event_1"],
        candidates: [], request: {}, outputVersions: [], outputs: [], autoComposition: { status: "completed" },
        execution: {
          schemaVersion: 1, status: "waiting_user", operation: "auto_composition", active: false, outcome: "no_acceptable_output", progress: {},
          result: {
            outputCount: 0, qualityRejectedCount: 1, qualityReasons: ["仍有关键问题"],
            qualityIssues: [{ severity: "critical", description: "源素材没有拍到动作完成结果" }],
            qualityRepair: { status: "insufficient_evidence", localRepairAttempts: 2, detail: "补检后仍没有完整结果镜头" },
          }, capabilities: { canCancel: true },
        },
      };
      currentJob = job;
      renderConversation(job);
      return {
        text: document.querySelector(".quality-gate-result-card")?.textContent || "",
        actionCount: document.querySelectorAll(".quality-gate-result-card button").length,
      };
    });
    assert.match(audit.text, /2 轮局部修复、问题镜头补检和重新编排/);
    assert.match(audit.text, /补检后仍没有完整结果镜头/);
    assert.doesNotMatch(audit.text, /重新规划剪辑方案/);
    assert.equal(audit.actionCount, 1);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("background composition stays visible as a timestamped live log outside the transcript", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(async () => {
      const job = {
        id: "auto-progress-layout", taskMode: "highlight",
        status: "awaiting_confirmation", stage: "auto_composition", messages: [
          { id: "m1", role: "assistant", kind: "recommendation", createdAt: "2026-08-21T10:30:30Z", text: "事件整理完成：已归并为 2 个高光事件。" },
          { id: "m2", role: "assistant", kind: "auto-compose", createdAt: "2026-08-21T10:30:31Z", text: "视觉模型已完成事件发现，正在生成完整事件版。" },
          { id: "m3", role: "assistant", kind: "result", createdAt: "2026-08-21T10:30:35Z", text: "AI 样片 V1 已就绪：包含 2 个高光事件、4 个镜头。" },
          { id: "m4", role: "assistant", kind: "composition-review", createdAt: "2026-08-21T10:32:21Z", text: "成片 V1 审片完成：31/100，发现动作不完整。" },
        ],
        eventGroups: [], candidates: [], outputs: [], outputVersions: [], request: { autoVariantCount: 1 },
        autoComposition: {
          status: "running", phase: "evidence_recovery", progress: .93,
          completedVersions: 1, totalVersions: 1, currentVersion: 1,
          detail: "正在补检问题镜头附近的源画面",
          qualityRepair: { round: 2, maxRounds: 2 },
        },
        execution: {
          schemaVersion: 1, status: "running", operation: "quality_review", phase: "evidence_recovery",
          active: true, background: true, detail: "正在补检问题镜头附近的源画面",
          outcome: "none", progress: { completed: 1, total: 1 }, result: {}, capabilities: { canCancel: true },
        },
      };
      currentJob = job;
      document.querySelector(".studio")?.classList.remove("home-mode");
      renderConversation(job);
      await new Promise((resolve) => requestAnimationFrame(resolve));
      const dedicated = document.querySelector(".auto-compose-progress");
      const dock = document.querySelector("#autoCompositionDock");
      const chat = document.querySelector("#chatMessages");
      const composer = document.querySelector("#chatForm");
      const audit = {
        dedicatedCount: document.querySelectorAll(".auto-compose-progress").length,
        genericCount: document.querySelectorAll(".inline-analysis-progress").length,
        detail: dedicated?.querySelector("[data-auto-compose-detail]")?.textContent || "",
        hint: dedicated?.querySelector("[data-auto-compose-versions]")?.textContent || "",
        detailWidth: dedicated?.querySelector("[data-auto-compose-detail]")?.getBoundingClientRect().width || 0,
        dockVisible: dock ? getComputedStyle(dock).display !== "none" : false,
        outsideTranscript: Boolean(dock && chat && !chat.contains(dock)),
        beforeComposer: Boolean(dock && composer && (dock.compareDocumentPosition(composer) & Node.DOCUMENT_POSITION_FOLLOWING)),
        activityCount: dock?.querySelectorAll(".auto-compose-log .auto-compose-activity-item").length || 0,
        recentCount: dock?.querySelectorAll(".auto-compose-activity-recent .auto-compose-activity-item").length || 0,
        times: [...(dock?.querySelectorAll(".auto-compose-activity-item time") || [])].map((node) => node.textContent),
        transcriptActivityCount: [...chat.querySelectorAll(".bubble p")].filter((node) => /事件整理完成|样片 V1|审片完成/.test(node.textContent)).length,
        sampleLogText: dock?.textContent || "",
      };
      job.autoComposition.status = "completed";
      job.autoComposition.phase = "done";
      job.execution.active = false;
      job.execution.status = "waiting_user";
      updateAutoCompositionProgress(job);
      audit.hiddenAfterCompletion = getComputedStyle(dock).display === "none";
      return audit;
    });
    assert.equal(audit.dedicatedCount, 1);
    assert.equal(audit.genericCount, 0);
    assert.match(audit.detail, /补检问题镜头/);
    assert.match(audit.hint, /补检问题镜头附近的动作与结果/);
    assert.ok(audit.detailWidth > 120);
    assert.equal(audit.dockVisible, true);
    assert.equal(audit.outsideTranscript, true);
    assert.equal(audit.beforeComposer, true);
    assert.equal(audit.activityCount, 4);
    assert.equal(audit.recentCount, 2);
    assert.equal(audit.times.every((value) => /^\d{2}:\d{2}:\d{2}$/.test(value)), true);
    assert.equal(audit.transcriptActivityCount, 0);
    assert.match(audit.sampleLogText, /样片渲染完成/);
    assert.doesNotMatch(audit.sampleLogText, /AI 样片 V1 已就绪/);
    assert.equal(audit.hiddenAfterCompletion, true);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("a derived highlight response may switch jobs while ordinary stale responses remain blocked", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const originalRenderJob = renderJob;
      const previousJob = currentJob;
      const previousRevision = currentJobRevision;
      try {
        renderJob = (job) => { currentJob = job; };
        currentJob = { id: "parent-content-job" };
        currentJobRevision = "parent-revision";
        const token = captureJobAction();
        const strictResult = commitJobAction({ id: "derived-highlight-job" }, token);
        const afterStrict = currentJob.id;
        const derivedResult = commitJobAction(
          { id: "derived-highlight-job", status: "queued" },
          token,
          { allowJobSwitch: true },
        );
        return { strictResult, afterStrict, derivedResult, afterDerived: currentJob.id, revision: currentJobRevision };
      } finally {
        renderJob = originalRenderJob;
        currentJob = previousJob;
        currentJobRevision = previousRevision;
      }
    });
    assert.equal(audit.strictResult, false);
    assert.equal(audit.afterStrict, "parent-content-job");
    assert.equal(audit.derivedResult, true);
    assert.equal(audit.afterDerived, "derived-highlight-job");
    assert.equal(audit.revision, "");
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("completed highlight alternatives use the one-click background render action", async () => {
  const source = await readFile(join(staticRoot, "app.js"), "utf8");
  assert.match(source, /data-alternative-job/);
  assert.match(source, /requestAlternativeCut\(job\)/);
  assert.match(source, /`\/api\/jobs\/\$\{job\.id\}\/alternative`/);
  assert.doesNotMatch(source, /data-prompt="基于当前成片换一种剪法/);
});

test("generated output versions open a persistent secondary editor", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  const operations = [];
  const subtitleUpdates = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const job = {
    id: "secondary-editor-job", filename: "访谈.mp4", workflowKind: "speaker_edit",
    taskMode: "content_extract", status: "completed", stage: "completed",
    previewUrl: "/api/jobs/secondary-editor-job/preview",
    videoInfo: { duration: 120, width: 1280, height: 720, frame_rate: 25, has_audio: true },
    request: {}, messages: [], candidates: [], eventGroups: [],
    outputVersions: [{
      id: "version_1", number: 1, outputs: [{
        filename: "version_1.mp4", duration: 15.08, segmentCount: 2,
        downloadUrl: "/api/jobs/secondary-editor-job/outputs/version_1.mp4/download",
        segments: [
          { id: "source_1", start: 83.45, end: 92.53, role: "问题" },
          { id: "source_2", start: 100, end: 106, role: "回答" },
        ],
      }],
    }],
    outputs: [], currentOutputVersionId: "version_1",
  };
  let session = {
    id: "edit_session_1", title: "基于 V1 精剪", status: "draft", revision: 0,
    baseVersionId: "version_1", baseVersionNumber: 1, baseOutputFilename: "version_1.mp4",
    workflowKind: "speaker_edit", duration: 15.08, clipCount: 2, canUndo: false, canRedo: false,
    textLayers: [],
    subtitleEnabled: true, subtitleDraftId: "sub_test", subtitleStyle: "clean", schedule: [
      { clipId: "clip_1", outputStart: 0, outputEnd: 9.08 },
      { clipId: "clip_2", outputStart: 9.08, outputEnd: 15.08 },
    ],
    clips: [
      { id: "clip_1", title: "问题", sourceRef: { kind: "output_segment", id: "source_1" }, sourceStart: 83.45, sourceEnd: 92.53, duration: 9.08, playbackRate: 1, transitionIn: { type: "cut", duration: 0 }, audioBridge: { type: "none", duration: 0 } },
      { id: "clip_2", title: "回答", sourceRef: { kind: "output_segment", id: "source_2" }, sourceStart: 100, sourceEnd: 106, duration: 6, playbackRate: 1, transitionIn: { type: "cut", duration: 0 }, audioBridge: { type: "none", duration: 0 } },
    ],
  };
  const refreshSessionSchedule = () => {
    const durations = session.clips.map((clip) => (clip.sourceEnd - clip.sourceStart) / clip.playbackRate);
    let outputEnd = 0;
    const schedule = session.clips.map((clip, index) => {
      clip.duration = durations[index];
      const overlap = index > 0 && clip.transitionIn.type !== "cut" ? Math.min(.35, durations[index - 1] / 3, durations[index] / 3) : 0;
      const outputStart = outputEnd - overlap;
      outputEnd = outputStart + durations[index];
      return { clipId: clip.id, outputStart, outputEnd, effectiveDuration: durations[index], transitionOverlap: overlap };
    });
    session = { ...session, revision: session.revision + 1, canUndo: true, clipCount: session.clips.length, duration: outputEnd, schedule };
  };
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/jobs/secondary-editor-job/timeline-assets", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        ready: true, generating: false,
        spriteUrl: "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==",
        sprite: {
          spriteWidth: 160, spriteHeight: 90, tileWidth: 80, tileHeight: 45,
          items: [
            { index: 0, time: 84, column: 0, row: 0 },
            { index: 1, time: 91, column: 1, row: 0 },
            { index: 2, time: 101, column: 0, row: 1 },
            { index: 3, time: 105, column: 1, row: 1 },
          ],
        },
        sceneCuts: [90, 102],
      }) });
    });
    await page.route("**/api/jobs/secondary-editor-job/waveform", async (route) => {
      const values = Array.from({ length: 240 }, (_unused, index) => .08 + Math.abs(Math.sin(index / 9)) * .5);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        schemaVersion: 3, duration: 120, hasAudio: true, rms: values,
        minimums: values.map((value) => -value), maximums: values,
        normalizationPeak: .58, silences: [{ start: 89.8, end: 90.2 }],
      }) });
    });
    await page.route("**/api/jobs/secondary-editor-job/subtitle-drafts/sub_test", async (route) => {
      const draft = {
        id: "sub_test", jobId: job.id, status: "confirmed", revision: 1,
        sourceSubtitleAcknowledged: true, outputFingerprints: ["test"],
        globalStyle: {}, cueStyleOverrides: {},
        cues: [
          { id: "cue_1", outputIndex: 0, start: 1, end: 4, text: "第一个问题", originalText: "第一个问题", suggestionStatus: "none" },
          { id: "cue_2", outputIndex: 0, start: 10, end: 11, text: "第二个回答", originalText: "第二个回答", suggestionStatus: "none" },
        ],
      };
      if (route.request().method() === "PUT") {
        const payload = route.request().postDataJSON();
        subtitleUpdates.push(payload);
        draft.revision = payload.revision + 1;
        draft.cues = payload.cues;
        draft.globalStyle = payload.globalStyle;
        draft.cueStyleOverrides = payload.cueStyleOverrides;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ draft }) });
    });
    await page.route("**/api/jobs/secondary-editor-job/edit-sessions**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() === "POST" && url.pathname.endsWith("/edit-sessions")) {
        await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ created: true, session, job }) });
        return;
      }
      if (request.method() === "PATCH") {
        const payload = request.postDataJSON();
        operations.push(payload.operation);
        if (payload.operation.type === "trim_clip") {
          const clip = session.clips.find((item) => item.id === payload.operation.clipId);
          clip.sourceStart = payload.operation.sourceStart;
          clip.sourceEnd = payload.operation.sourceEnd;
          refreshSessionSchedule();
        } else if (payload.operation.type === "roll_trim") {
          const clip = session.clips.find((item) => item.id === payload.operation.clipId);
          const adjacent = session.clips.find((item) => item.id === payload.operation.adjacentClipId);
          clip.sourceStart = payload.operation.sourceStart;
          clip.sourceEnd = payload.operation.sourceEnd;
          adjacent.sourceStart = payload.operation.adjacentSourceStart;
          adjacent.sourceEnd = payload.operation.adjacentSourceEnd;
          refreshSessionSchedule();
        } else if (payload.operation.type === "update_clip") {
          const clip = session.clips.find((item) => item.id === payload.operation.clipId);
          clip.playbackRate = payload.operation.playbackRate;
          clip.transitionIn = { type: payload.operation.transitionType, duration: payload.operation.transitionType === "cut" ? 0 : .35 };
          clip.audioBridge = { type: payload.operation.audioBridgeType, duration: payload.operation.audioBridgeType === "none" ? 0 : .18 };
          refreshSessionSchedule();
        } else if (payload.operation.type === "delete_clips") {
          const removed = new Set(payload.operation.clipIds);
          session.clips = session.clips.filter((clip) => !removed.has(clip.id));
          refreshSessionSchedule();
        } else if (payload.operation.type === "insert_clip") {
          const inserted = {
            id: "clip_inserted", title: payload.operation.title,
            sourceRef: payload.operation.sourceRef,
            sourceStart: payload.operation.sourceStart, sourceEnd: payload.operation.sourceEnd,
            duration: payload.operation.sourceEnd - payload.operation.sourceStart,
            playbackRate: 1, transitionIn: { type: "cut", duration: 0 }, audioBridge: { type: "none", duration: 0 },
          };
          const clips = [...session.clips];
          clips.splice(payload.operation.targetIndex, 0, inserted);
          session.clips = clips;
          refreshSessionSchedule();
        } else if (payload.operation.type === "reorder_clips") {
          const lookup = new Map(session.clips.map((clip) => [clip.id, clip]));
          session.clips = payload.operation.clipIds.map((id) => lookup.get(id));
          refreshSessionSchedule();
        } else if (payload.operation.type === "add_text_layer") {
          session.textLayers.push({
            id: `edit_text_${session.textLayers.length + 1}`,
            text: payload.operation.text,
            start: payload.operation.start,
            end: payload.operation.end,
            style: payload.operation.style,
          });
          session = { ...session, revision: session.revision + 1, canUndo: true };
        } else if (payload.operation.type === "update_text_layer") {
          const layer = session.textLayers.find((item) => item.id === payload.operation.layerId);
          if (payload.operation.text !== undefined) layer.text = payload.operation.text;
          if (payload.operation.start !== undefined) layer.start = payload.operation.start;
          if (payload.operation.end !== undefined) layer.end = payload.operation.end;
          if (payload.operation.style !== undefined) layer.style = payload.operation.style;
          session = { ...session, revision: session.revision + 1, canUndo: true };
        } else if (payload.operation.type === "delete_text_layer") {
          session.textLayers = session.textLayers.filter((item) => item.id !== payload.operation.layerId);
          session = { ...session, revision: session.revision + 1, canUndo: true };
        }
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ summary: "已移除 1 个片段", session }) });
        return;
      }
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not stubbed" }) });
    });
    await page.evaluate((value) => {
      document.body.dataset.shellMode = "workspace";
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      document.querySelector("#reviewView")?.classList.remove("hidden");
      currentJob = value;
      renderOutputs(value);
      setDirectorStage("compose");
    }, job);
    assert.equal(await page.locator("#secondaryEditCurrentButton").isVisible(), true);
    assert.equal(await page.locator("#secondaryEditCurrentButton").getAttribute("data-secondary-edit-version"), "version_1");
    assert.equal(await page.locator("#secondaryEditCurrentButton").getAttribute("data-secondary-edit-output"), "version_1.mp4");
    assert.equal(await page.locator(".clip-version-edit").textContent(), "精剪此版本");
    const outputActionColors = await page.evaluate(() => ({
      selector: getComputedStyle(document.querySelector("#videoViewSelect")).backgroundColor,
      edit: getComputedStyle(document.querySelector("#secondaryEditCurrentButton")).backgroundColor,
      download: getComputedStyle(document.querySelector("#downloadButton")).backgroundColor,
      downloadText: getComputedStyle(document.querySelector("#downloadButton")).color,
      evidenceTitle: getComputedStyle(document.querySelector("#clipTitle")).color,
      evidenceReason: getComputedStyle(document.querySelector("#clipReason")).color,
      explanation: getComputedStyle(document.querySelector("#outputExplanation")).color,
    }));
    assert.match(outputActionColors.selector, /255, 255, 255/);
    assert.equal(outputActionColors.edit, "rgb(255, 245, 239)");
    assert.equal(outputActionColors.download, "rgb(237, 135, 84)");
    assert.equal(outputActionColors.downloadText, "rgb(255, 255, 255)");
    assert.equal(outputActionColors.evidenceTitle, "rgb(38, 49, 56)");
    assert.equal(outputActionColors.evidenceReason, "rgb(86, 99, 107)");
    assert.equal(outputActionColors.explanation, "rgb(62, 75, 82)");
    await page.locator("#secondaryEditCurrentButton").click();
    await page.locator("#secondaryEditor").waitFor({ state: "visible" });
    assert.equal(await page.locator("#secondarySubtitleAdd").isVisible(), true);
    assert.equal(await page.locator("#secondarySubtitleAdd").textContent(), "＋ 文本");
    assert.equal(await page.locator('[data-secondary-inspector-tab="clip"]').getAttribute("aria-pressed"), "true");
    await page.locator('[data-secondary-inspector-tab="ai"]').click();
    assert.equal(await page.locator('[data-secondary-inspector-panel="ai"]').isVisible(), true);
    assert.equal(await page.locator('[data-secondary-inspector-panel="clip"]').isVisible(), false);
    await page.locator('[data-secondary-inspector-tab="clip"]').click();
    assert.equal(await page.locator('[data-secondary-inspector-panel="clip"]').isVisible(), true);
    assert.deepEqual(await page.evaluate(() => ({
      earlier: secondaryEditorReorderedClipIds(
        [{ id: "clip_1" }, { id: "clip_2" }, { id: "clip_3" }],
        new Set(["clip_3"]), 0,
      ),
      later: secondaryEditorReorderedClipIds(
        [{ id: "clip_1" }, { id: "clip_2" }, { id: "clip_3" }],
        new Set(["clip_1"]), 3,
      ),
    })), {
      earlier: ["clip_3", "clip_1", "clip_2"],
      later: ["clip_2", "clip_3", "clip_1"],
    });
    await page.locator("[data-secondary-clip='clip_2']").dragTo(
      page.locator("[data-secondary-clip='clip_1']"),
      { targetPosition: { x: 3, y: 36 } },
    );
    await page.waitForFunction(() => document.querySelector("[data-secondary-clip]")?.dataset.secondaryClip === "clip_2");
    assert.deepEqual(operations.at(-1), { type: "reorder_clips", clipIds: ["clip_2", "clip_1"] });
    const secondClipBounds = await page.locator("[data-secondary-clip='clip_1']").boundingBox();
    assert.ok(secondClipBounds);
    await page.locator("[data-secondary-clip='clip_2']").dragTo(
      page.locator("[data-secondary-clip='clip_1']"),
      { targetPosition: { x: secondClipBounds.width - 3, y: 36 } },
    );
    await page.waitForFunction(() => document.querySelector("[data-secondary-clip]")?.dataset.secondaryClip === "clip_1");
    assert.deepEqual(operations.at(-1), { type: "reorder_clips", clipIds: ["clip_1", "clip_2"] });
    operations.length = 0;
    await page.locator("[data-secondary-clip='clip_1']").click({ position: { x: 30, y: 36 } });
    const timeSemantics = await page.evaluate(() => ({
      precise: formatPreciseTimecode(83.45),
      parsedTimecode: parseTimecodeValue("01:23.45"),
      parsedSeconds: parseTimecodeValue("83.45"),
      frameTimecode: formatFrameTimecode(83.45, 25),
    }));
    assert.deepEqual(timeSemantics, {
      precise: "01:23.45", parsedTimecode: 83.45, parsedSeconds: 83.45, frameTimecode: "00:01:23:11",
    });
    assert.equal(await page.locator("#secondaryInspectorStart").inputValue(), "01:23.45");
    assert.equal(await page.locator("#secondaryInspectorEnd").inputValue(), "01:32.53");
    assert.equal(await page.locator("#secondaryEditorVideo").evaluate((video) => video.controls), false);
    assert.equal(await page.locator("#secondaryEditorMediaControls").isVisible(), true);
    const mediaControlBounds = await page.locator("#secondaryEditorMediaControls").boundingBox();
    const playerBounds = await page.locator(".secondary-editor-player").boundingBox();
    const editorVideoBounds = await page.locator("#secondaryEditorVideo").boundingBox();
    assert.ok(mediaControlBounds && playerBounds && mediaControlBounds.height <= 44 && mediaControlBounds.height < playerBounds.height / 4);
    assert.ok(editorVideoBounds && mediaControlBounds.y >= editorVideoBounds.y + editorVideoBounds.height - 1);
    assert.equal(await page.locator("#secondaryEditorMediaControls").evaluate((controls) => getComputedStyle(controls).position), "relative");
    assert.equal(await page.locator("#secondaryEditorMediaControls").evaluate((controls) => getComputedStyle(controls).backgroundImage), "none");
    assert.match(await page.locator("#secondaryInspectorForm").textContent(), /源片入点.*源片出点.*源片长度.*成片位置/s);
    assert.match(await page.locator("#secondaryInspectorStartMeta").textContent(), /83\.45 秒 · TC 00:01:23:11/);
    assert.match(await page.locator("#secondaryInspectorTimingSummary").textContent(), /源片长度9\.08 秒.*成片位置00:00\.00 → 00:09\.08.*片段播放时长9\.08 秒/s);
    assert.match(await page.locator("#secondaryEditorLibraryBody").textContent(), /源片 01:23\.45 → 01:32\.53/);
    assert.deepEqual(await page.locator("#secondaryEditorLibraryBody [data-secondary-material-group] summary strong").allTextContents(), [
      "当前成片素材", "推荐补充", "已保留素材", "待确认与已移除",
    ]);
    assert.match(await page.locator("#secondaryEditorLibraryContext").textContent(), /已继承说话人模式/);
    assert.doesNotMatch(await page.locator("#secondaryEditorLibraryBody").textContent(), /version_1\.mp4/);
    const modeAwareGroups = await page.evaluate(() => {
      const summarize = (job, draft) => Object.fromEntries(
        secondaryEditorMaterialGroups(job, draft).map((group) => [group.id, group.items.map((item) => item.title)]),
      );
      return {
        highlight: summarize({
          id: "highlight-materials", workflowKind: "highlight",
          eventGroups: [{ id: "event-1", title: "倒水", segments: [{ id: "shot-1", start: 4, end: 7, title: "水流特写" }] }],
          candidates: [], outputVersions: [],
        }, { workflowKind: "highlight", clips: [] }),
        content: summarize({
          id: "content-materials", workflowKind: "content_search",
          contentSearch: { id: "search-new" }, contentSearchSession: { activeSearchId: "search-new" },
          contentSearchRecords: [
            { id: "search-old", instruction: "找接水", timelineCandidates: [{ id: "old-1", start: 20, end: 22, title: "历史接水" }] },
            { id: "search-new", instruction: "找切西瓜", candidates: [
              { id: "new-1", start: 30, end: 32, title: "可靠结果", confidenceTier: "reliable" },
              { id: "new-2", start: 40, end: 42, title: "待复核结果", confidenceTier: "possible", reviewStatus: "pending" },
            ] },
          ], outputVersions: [],
        }, { workflowKind: "content_search", clips: [{ id: "current-1", title: "当前片段", sourceRef: { kind: "manual_range", id: "manual-1" }, sourceStart: 10, sourceEnd: 12 }] }),
        person: summarize({
          id: "person-materials", workflowKind: "person_edit", contentSearchRecords: [],
          contentSearchPersonTarget: { personIds: ["person-1"], matchMode: "any", activity: "appearance" },
          contentIndex: { persons: [{ id: "person-1", label: "人物 A", ranges: [{ start: 1, end: 2 }, { start: 6, end: 8 }] }] },
          outputVersions: [],
        }, { workflowKind: "person_edit", clips: [{ id: "person-current", title: "人物 A 出镜", sourceRef: { kind: "person_range", id: "person-1:0" }, sourceStart: 1, sourceEnd: 2 }] }),
        speaker: summarize({
          id: "speaker-materials", workflowKind: "speaker_edit",
          contentSearch: { id: "voice-search" }, contentSearchRecords: [{ id: "voice-search", candidates: [{ id: "voice-1", start: 12, end: 15, title: "声音 A 发言", confidenceTier: "reliable" }] }],
          outputVersions: [],
        }, { workflowKind: "speaker_edit", clips: [] }),
      };
    });
    assert.deepEqual(modeAwareGroups.highlight.recommended, ["水流特写"]);
    assert.deepEqual(modeAwareGroups.content, {
      timeline: ["当前片段"], recommended: ["可靠结果"], kept: ["历史接水"], review: ["待复核结果"],
    });
    assert.deepEqual(modeAwareGroups.person.timeline, ["人物 A 出镜"]);
    assert.deepEqual(modeAwareGroups.person.recommended, ["人物 A 出镜 · 第 2 段"]);
    assert.deepEqual(modeAwareGroups.speaker.recommended, ["声音 A 发言"]);
    assert.equal(await page.evaluate(() => secondaryEditorInsertionIndex()), 1);
    assert.match(await page.locator("#secondaryEditorLibraryInsertHint").textContent(), /第 1 段.*之后/);
    assert.equal(await page.locator("#secondaryEditorInsertTarget").inputValue(), "1");
    assert.equal(await page.locator("#secondaryEditorLibraryBody [data-secondary-material-insert]").first().textContent(), "再次插入");
    await page.locator("#secondaryEditorLibraryBody [data-secondary-material-preview]").last().click();
    assert.equal(await page.evaluate(() => secondaryEditView), "source");
    assert.match(await page.locator("#secondaryEditorVideoBadge").textContent(), /素材预览/);
    assert.equal(await page.locator("#secondaryEditorMediaSeek").getAttribute("data-coordinate"), "material");
    assert.equal(await page.locator("#secondaryEditorLibraryBody [data-secondary-material].previewing").count(), 1);
    await page.locator("#secondaryEditorInsertTarget").selectOption("0");
    assert.equal(await page.evaluate(() => secondaryEditorInsertionIndex()), 0);
    assert.match(await page.locator("#secondaryEditorLibraryInsertHint").textContent(), /已固定位置.*时间线开头/);
    await page.locator("#secondaryEditorInsertFollow").click();
    assert.equal(await page.evaluate(() => secondaryEditorInsertionIndex()), 1);
    assert.equal(await page.locator("#secondaryEditorTrimLeft").isVisible(), true);
    assert.equal(await page.locator("#secondaryEditorTrimRight").isVisible(), true);
    assert.equal(await page.locator("#secondaryEditorDuplicate").isVisible(), true);
    assert.equal(await page.locator("#secondaryEditorMarker").isVisible(), true);
    assert.match(await page.locator("#secondaryEditorClock").textContent(), /^成片 /);
    await page.locator('[data-secondary-view="source"]').click();
    assert.equal(await page.locator('[data-secondary-view="source"]').getAttribute("aria-pressed"), "true");
    assert.match(await page.locator("#secondaryEditorVideoBadge").textContent(), /源视频 · 完整时间线/);
    assert.equal(await page.evaluate(() => secondaryEditView), "source");
    assert.equal(await page.locator("#secondaryEditorMediaSeek").getAttribute("data-coordinate"), "source");
    await page.locator('[data-secondary-view="sequence"]').click();
    assert.equal(await page.locator('[data-secondary-view="sequence"]').getAttribute("aria-pressed"), "true");
    assert.equal(await page.evaluate(() => secondaryEditView), "sequence");
    assert.equal(await page.locator("#secondaryEditorMediaSeek").getAttribute("data-coordinate"), "sequence");
    assert.ok(Number(await page.locator("#secondaryEditorMediaSeek").getAttribute("max")) > 15);
    await page.locator("#secondaryEditorMediaSeek").fill("4");
    assert.ok(await page.evaluate(() => secondaryEditPlayheadTime >= 3.99));
    await page.locator("#secondaryEditorMediaMute").click();
    assert.equal(await page.locator("#secondaryEditorMediaMute").getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator("#secondaryEditorTimeline [data-secondary-clip]").count(), 2);
    await page.locator("#secondaryEditorTimeline [data-secondary-clip]").nth(1).click({ modifiers: ["Shift"] });
    assert.equal(await page.locator("#secondaryEditorTimeline [data-secondary-clip].selected").count(), 2);
    assert.match(await page.locator("#secondaryInspectorTitle").textContent(), /批量设置 · 2 个片段/);
    await page.locator("#secondaryEditorTimeline [data-secondary-clip]").first().click();
    assert.match(await page.locator("#clipStrip .clip-version-entry").first().getAttribute("class"), /quality-passed/);
    assert.equal(await page.locator("#clipStrip .clip-version-button").first().getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator("#clipStrip .clip-version-index").first().evaluate((node) => getComputedStyle(node).borderRadius), "10px");
    assert.match(await page.locator("#clipStrip .clip-version-entry").first().evaluate((node) => getComputedStyle(node).animationName), /output-card-enter/);
    assert.ok(await page.locator("#secondaryEditorRuler .secondary-editor-ruler-tick").count() >= 3);
    assert.equal(await page.locator("#secondaryEditorPlayhead").isVisible(), true);
    await page.waitForFunction(() => document.querySelector("#secondaryEditorMediaState")?.textContent.includes("画面缩略图 · 音频波形"));
    assert.equal(await page.locator("#secondaryEditorTimeline canvas[data-secondary-waveform]").count(), 2);
    assert.equal(await page.locator("#secondaryEditorTimeline [data-secondary-trim]").count(), 4);
    await page.waitForFunction(() => document.querySelectorAll("#secondaryEditorSubtitleBlocks [data-secondary-cue]").length === 2);
    await page.locator("[data-secondary-cue='cue_1'] [data-secondary-cue-text]").fill("修改后的问题");
    await page.locator("#secondaryEditorTimelineMeta").click();
    await page.waitForFunction(() => document.querySelector("#secondaryEditorSubtitleStatus")?.textContent.includes("已保存"));
    assert.equal(subtitleUpdates.at(-1).cues[0].text, "修改后的问题");
    await page.evaluate(() => secondaryEditorSeekOutputTime(2, false));
    const subtitlePreview = page.locator("#secondaryEditorSubtitlePreview");
    await subtitlePreview.waitFor({ state: "visible" });
    assert.match(await page.locator("#secondarySubtitleTransformClip").textContent(), /问题/);
    assert.match(await page.locator("#secondarySubtitleTransformCount").textContent(), /第 1 段.*1 条字幕/);
    const subtitleBounds = await subtitlePreview.boundingBox();
    assert.ok(subtitleBounds);
    const moveHandleBounds = await page.locator("[data-secondary-subtitle-move]").boundingBox();
    assert.ok(moveHandleBounds);
    const updatesBeforeMove = subtitleUpdates.length;
    await page.mouse.move(moveHandleBounds.x + moveHandleBounds.width / 2, moveHandleBounds.y + moveHandleBounds.height / 2);
    await page.mouse.down();
    await page.mouse.move(moveHandleBounds.x + moveHandleBounds.width / 2 + 36, moveHandleBounds.y + moveHandleBounds.height / 2 - 20, { steps: 4 });
    await page.mouse.up();
    await page.waitForFunction(() => document.querySelector("#secondaryEditorSubtitleStatus")?.textContent.includes("已保存"));
    assert.ok(subtitleUpdates.length > updatesBeforeMove);
    assert.ok(Math.abs(Number(subtitleUpdates.at(-1).cueStyleOverrides.cue_1.offsetXRatio || 0)) > .01);
    assert.ok(Math.abs(Number(subtitleUpdates.at(-1).cueStyleOverrides.cue_1.offsetYRatio || 0)) > .01);
    assert.equal(subtitleUpdates.at(-1).cueStyleOverrides.cue_2, undefined);
    assert.equal(Object.keys(subtitleUpdates.at(-1).globalStyle).length, 0);
    const resizeHandle = page.locator("[data-secondary-subtitle-resize]");
    const resizeBounds = await resizeHandle.boundingBox();
    assert.ok(resizeBounds);
    const fontBeforeResize = Number(subtitleUpdates.at(-1).cueStyleOverrides.cue_1.fontSizeRatio || .04);
    const updatesBeforeResize = subtitleUpdates.length;
    await page.mouse.move(resizeBounds.x + resizeBounds.width / 2, resizeBounds.y + resizeBounds.height / 2);
    await page.mouse.down();
    await page.mouse.move(resizeBounds.x + resizeBounds.width / 2 + 28, resizeBounds.y + resizeBounds.height / 2 + 18, { steps: 4 });
    await page.mouse.up();
    await page.waitForFunction(() => document.querySelector("#secondaryEditorSubtitleStatus")?.textContent.includes("已保存"));
    assert.ok(subtitleUpdates.length > updatesBeforeResize);
    assert.ok(Number(subtitleUpdates.at(-1).cueStyleOverrides.cue_1.fontSizeRatio) > fontBeforeResize);
    assert.equal(subtitleUpdates.at(-1).cueStyleOverrides.cue_2, undefined);
    const firstClipSubtitleStyle = { ...subtitleUpdates.at(-1).cueStyleOverrides.cue_1 };
    await page.evaluate(() => secondaryEditorSeekOutputTime(10.25, false));
    await subtitlePreview.waitFor({ state: "visible" });
    assert.match(await page.locator("#secondarySubtitleTransformClip").textContent(), /回答/);
    assert.match(await page.locator("#secondarySubtitleTransformCount").textContent(), /第 2 段.*1 条字幕/);
    const updatesBeforeSecondClip = subtitleUpdates.length;
    await subtitlePreview.focus();
    await subtitlePreview.press("ArrowLeft");
    await page.waitForFunction(() => document.querySelector("#secondaryEditorSubtitleStatus")?.textContent.includes("已保存"));
    assert.ok(subtitleUpdates.length > updatesBeforeSecondClip);
    assert.ok(Number(subtitleUpdates.at(-1).cueStyleOverrides.cue_2.offsetXRatio) < 0);
    assert.deepEqual(subtitleUpdates.at(-1).cueStyleOverrides.cue_1, firstClipSubtitleStyle);
    const updatesBeforeTextBox = subtitleUpdates.length;
    await page.locator("#secondarySubtitleAdd").click();
    const previewTextEditor = page.locator("#secondaryEditorTextLayerCanvas [data-secondary-text-content]");
    await previewTextEditor.waitFor({ state: "visible" });
    await previewTextEditor.fill("第二段补充说明");
    await previewTextEditor.press("Enter");
    await page.waitForFunction(() => secondaryEditSession?.textLayers?.[0]?.text === "第二段补充说明" && !secondaryEditBusy);
    assert.equal(subtitleUpdates.length, updatesBeforeTextBox);
    const savedTextBox = await page.evaluate(() => secondaryEditSession.textLayers[0]);
    assert.ok(savedTextBox);
    assert.equal(savedTextBox.text, "第二段补充说明");
    assert.ok(Number(savedTextBox.start) >= 9.08 && Number(savedTextBox.end) <= 15.08);
    assert.equal(savedTextBox.style.vertical, "middle");
    assert.equal(await page.locator(`[data-secondary-text-block='${savedTextBox.id}']`).count(), 1);
    assert.equal(await page.locator("#secondaryTextDelete").isVisible(), true);
    await page.locator("#secondaryTextDelete").click();
    await page.waitForFunction(() => secondaryEditSession.textLayers.length === 0);
    assert.equal(operations.at(-1).type, "delete_text_layer");
    operations.length = 0;
    await page.locator('[data-secondary-inspector-tab="clip"]').click();
    await page.locator("[data-secondary-clip='clip_1']").click();
    const originalFirstWidth = Number.parseFloat(await page.locator("[data-secondary-clip='clip_1']").evaluate((node) => node.style.width));
    const originalSecondLeft = Number.parseFloat(await page.locator("[data-secondary-clip='clip_2']").evaluate((node) => node.style.left));
    await page.locator("#secondaryInspectorSpeed").selectOption("1.25");
    const speedPreviewFirstWidth = Number.parseFloat(await page.locator("[data-secondary-clip='clip_1']").evaluate((node) => node.style.width));
    const speedPreviewSecondLeft = Number.parseFloat(await page.locator("[data-secondary-clip='clip_2']").evaluate((node) => node.style.left));
    assert.ok(speedPreviewFirstWidth < originalFirstWidth);
    assert.ok(speedPreviewSecondLeft < originalSecondLeft);
    assert.match(await page.locator("#secondaryEditorTimelineMeta").textContent(), /13\.3 秒 · 预览/);
    assert.match(await page.locator("#secondaryEditorTimelineDraftState").textContent(), /15\.08 秒 → 13\.26 秒/);
    assert.match(await page.locator("#secondaryEditorSaveState").textContent(), /尚未保存.*时间线为预览/);
    assert.match(await page.locator("#secondaryInspectorTimingSummary").textContent(), /片段播放时长7\.26 秒 · 1\.25×.*预计成片总长15\.08 → 13\.26 秒/s);
    assert.match(await page.locator("#secondaryEditorSubtitleSummary").textContent(), /保存后需重新对齐字幕/);
    assert.equal(await page.locator("[data-secondary-clip='clip_1']").getAttribute("class").then((value) => value.includes("pending-settings")), true);
    assert.equal(await page.locator("#secondaryEditorPreview").isDisabled(), true);
    assert.equal(await page.locator("#secondaryEditorExport").isDisabled(), true);
    assert.equal(await page.locator("#secondaryInspectorReset").isDisabled(), false);
    assert.equal(operations.length, 0);
    await page.locator("#secondaryInspectorReset").click();
    assert.equal(await page.locator("#secondaryEditorTimelineDraftState").evaluate((node) => node.classList.contains("hidden")), true);
    assert.equal(Number.parseFloat(await page.locator("[data-secondary-clip='clip_1']").evaluate((node) => node.style.width)), originalFirstWidth);
    await page.locator("#secondaryInspectorEnd").fill("01:31.00");
    assert.match(await page.locator("#secondaryEditorTimelineDraftState").textContent(), /15\.08 秒 → 13\.55 秒/);
    assert.match(await page.locator("#secondaryInspectorTimingSummary").textContent(), /源片长度7\.55 秒.*预计成片总长15\.08 → 13\.55 秒/s);
    await page.locator("#secondaryInspectorReset").click();
    await page.locator("[data-secondary-clip='clip_2']").click();
    await page.locator("#secondaryInspectorTransition").selectOption("dissolve");
    assert.match(await page.locator("#secondaryEditorTimelineDraftState").textContent(), /15\.08 秒 → 14\.73 秒/);
    assert.match(await page.locator("#secondaryInspectorTimingSummary").textContent(), /预计成片位置00:08\.73 → 00:14\.73.*预计成片总长15\.08 → 14\.73 秒.*转场重叠/s);
    await page.locator("#secondaryInspectorReset").click();
    await page.locator("[data-secondary-clip='clip_1']").click();
    const fittedWidth = await page.locator("#secondaryEditorTimelineCanvas").evaluate((node) => node.getBoundingClientRect().width);
    await page.locator("#secondaryEditorZoomIn").click();
    const zoomedWidth = await page.locator("#secondaryEditorTimelineCanvas").evaluate((node) => node.getBoundingClientRect().width);
    assert.ok(zoomedWidth > fittedWidth * 1.5);
    await page.locator("#secondaryEditorZoomFit").click();
    await page.locator("#secondaryEditorRuler").focus();
    await page.keyboard.press("End");
    assert.equal(await page.locator("#secondaryEditorPlayhead").evaluate((node) => node.style.left), "100%");
    assert.equal(await page.locator("#secondaryEditorTimeline [data-secondary-clip].selected").getAttribute("data-secondary-clip"), "clip_2");
    assert.equal(await page.evaluate(() => secondaryEditorInsertionIndex()), 2);
    assert.equal(await page.locator("#secondaryEditorInsertTarget").inputValue(), "2");
    await page.keyboard.press("Home");
    assert.equal(await page.locator("#secondaryEditorPlayhead").evaluate((node) => node.style.left), "0%");
    assert.equal(await page.locator("#secondaryEditorTimeline [data-secondary-clip].selected").getAttribute("data-secondary-clip"), "clip_1");
    assert.equal(await page.evaluate(() => secondaryEditorInsertionIndex()), 1);
    await page.locator("#secondaryEditorNextFrame").click();
    assert.notEqual(await page.locator("#secondaryEditorPlayhead").evaluate((node) => node.style.left), "0%");
    const trimHandle = page.locator("[data-secondary-clip='clip_1'] [data-secondary-trim='end']");
    const trimBox = await trimHandle.boundingBox();
    assert.ok(trimBox);
    await page.mouse.move(trimBox.x + trimBox.width / 2, trimBox.y + trimBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(trimBox.x - 30, trimBox.y + trimBox.height / 2, { steps: 4 });
    await page.mouse.up();
    await page.waitForFunction(() => document.querySelector("#secondaryEditorSaveState")?.textContent.includes("已自动保存"));
    assert.equal(operations[0].type, "roll_trim");
    assert.ok(operations[0].sourceEnd < 92.53);
    assert.equal(operations[0].adjacentClipId, "clip_2");
    assert.ok(operations[0].adjacentSourceStart < 100);
    assert.ok(Math.abs(session.duration - 15.08) < .02);
    assert.match(await page.locator("#secondaryEditorSubtitleStatus").textContent(), /时间线已变化.*重新对齐字幕/);
    assert.match(await page.locator("#secondaryEditorLibraryTitle").textContent(), /说话人发言结果/);
    assert.match(await page.locator("#secondaryEditorSaveState").textContent(), /已自动保存|草稿 r1/);
    assert.match(await page.locator(".secondary-ai-editor").textContent(), /快捷批量编辑/);
    assert.match(await page.locator(".secondary-ai-editor").textContent(), /结构变化/);
    assert.match(await page.locator(".secondary-ai-editor").textContent(), /预览样片/);
    assert.equal(await page.locator("#secondaryEditorAiForm button").textContent(), "预览时间线修改");
    assert.equal(await page.locator("[data-secondary-clip='clip_1'] [data-secondary-clip-delete]").isVisible(), true);
    await page.locator("[data-secondary-clip='clip_1'] [data-secondary-clip-delete]").click();
    await page.waitForFunction(() => document.querySelectorAll("#secondaryEditorTimeline [data-secondary-clip]").length === 1);
    assert.deepEqual(operations.map((operation) => operation.type), ["roll_trim", "delete_clips"]);
    assert.deepEqual(operations[1], { type: "delete_clips", clipIds: ["clip_1"] });
    assert.equal(await page.locator("#secondaryEditorUndo").isDisabled(), false);
    assert.equal(await page.locator("#secondaryEditorInsertTarget").inputValue(), "1");
    await page.locator("#secondaryEditorInsertTarget").selectOption("0");
    const removedGroup = page.locator('[data-secondary-material-group="review"]');
    await removedGroup.locator("summary").click();
    assert.match(await removedGroup.textContent(), /问题.*已移除.*可重新插入恢复/s);
    assert.equal(await removedGroup.locator("[data-secondary-material-insert]").first().textContent(), "恢复到时间线");
    await removedGroup.locator("[data-secondary-material-insert]").first().click();
    await page.waitForFunction(() => document.querySelectorAll("#secondaryEditorTimeline [data-secondary-clip]").length === 2);
    assert.equal(operations[2].type, "insert_clip");
    assert.equal(operations[2].targetIndex, 0);
    assert.equal(await page.locator("#secondaryEditorTimeline [data-secondary-clip].selected").getAttribute("data-secondary-clip"), "clip_inserted");
    await page.locator("#secondaryInspectorEnd").fill("01:31.00");
    await page.locator("#secondaryInspectorSpeed").selectOption("1.25");
    assert.match(await page.locator("#secondaryEditorSaveState").textContent(), /尚未保存.*时间线为预览/);
    await page.locator("#secondaryInspectorSave").click();
    await page.waitForFunction(() => document.querySelector("#secondaryEditorSaveState")?.textContent.includes("已自动保存"));
    assert.deepEqual(operations.slice(3).map((operation) => operation.type), ["trim_clip", "update_clip"]);
    assert.equal(operations[4].playbackRate, 1.25);
    assert.equal(operations[4].transitionType, "cut");
    assert.equal(await page.locator("#secondaryInspectorEnd").inputValue(), "01:31.00");
    assert.equal(await page.locator("#secondaryInspectorSpeed").inputValue(), "1.25");
    assert.equal(await page.locator("#secondaryEditorTimelineDraftState").evaluate((node) => node.classList.contains("hidden")), true);
    await page.setViewportSize({ width: 760, height: 820 });
    assert.equal(await page.locator(".secondary-editor-library").isVisible(), false);
    await page.locator("#secondaryEditorLibraryToggle").click();
    assert.equal(await page.locator(".secondary-editor-library").isVisible(), true);
    assert.match(await page.locator("#secondaryEditorLibraryBody [data-secondary-material]").first().textContent(), /时间线 1 处.*再次插入.*从时间线移除/s);
    await page.locator("#secondaryEditorLibraryBody [data-secondary-material-remove]").first().click();
    await page.waitForFunction(() => document.querySelectorAll("#secondaryEditorTimeline [data-secondary-clip]").length === 1);
    assert.deepEqual(operations[5], { type: "delete_clips", clipIds: ["clip_inserted"] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.locator("#secondaryEditorClose").click();
    assert.equal(await page.locator("#secondaryEditor").evaluate((node) => node.classList.contains("hidden")), true);
    await page.evaluate(() => showSource({ autoplay: false }));
    assert.equal(await page.locator("#secondaryEditCurrentButton").isVisible(), false);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("failed secondary subtitle setup restores its toggle without a runtime error", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/jobs/secondary-subtitle-failure/subtitle-drafts", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "字幕草稿建立失败" }),
      });
    });
    await page.evaluate(() => {
      currentJob = { id: "secondary-subtitle-failure", previewUrl: "/preview" };
      secondaryEditSession = {
        id: "edit_session_failure", revision: 0, subtitleStyle: "clean",
        clips: [{ id: "clip_1", sourceStart: 1, sourceEnd: 3, playbackRate: 1 }],
      };
    });
    await page.evaluate(() => {
      const checkbox = document.querySelector("#secondaryEditorSubtitleEnabled");
      checkbox.checked = true;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForFunction(() => document.querySelector("#secondaryEditorSubtitleEnabled")?.checked === false);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("subtitle review waits for on-demand transcription and opens automatically", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const requestBodies = [];
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/jobs/subtitle-on-demand/subtitle-drafts", async (route) => {
      const body = route.request().postDataJSON();
      requestBodies.push(body);
      if (requestBodies.length < 3) {
        await route.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({
            status: "transcribing", retryAfterMs: 10,
            transcription: {
              status: requestBodies.length === 1 ? "queued" : "running",
              progress: requestBodies.length === 1 ? 0 : .56,
              detail: requestBodies.length === 1 ? "对白识别已进入队列" : "正在识别对白（2/4 个音频分块）",
            },
          }),
        });
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ draft: {
          id: "sub_on_demand", jobId: "subtitle-on-demand", status: "draft", revision: 1,
          sourceSubtitleAcknowledged: false,
          globalStyle: { preset: "clean", fontSizeRatio: .04, horizontal: "center", vertical: "bottom", offsetXRatio: 0, offsetYRatio: 0 },
          cueStyleOverrides: {},
          cues: [{ id: "cue_1", outputIndex: 0, start: 0, end: 2, sourceStart: 1, sourceEnd: 3, text: "自动识别的对白", originalText: "自动识别的对白", suggestionStatus: "none" }],
        } }),
      });
    });
    await page.evaluate(() => {
      currentJob = { id: "subtitle-on-demand", previewUrl: "/preview", videoInfo: { width: 1280, height: 720 } };
      window.__subtitleReviewResult = reviewSubtitlesBeforeRender([{
        segments: [{ id: "clip_1", start: 1, end: 3, playbackRate: 1 }],
      }]);
    });
    await page.waitForFunction(() => !document.querySelector("#subtitleReview")?.classList.contains("hidden"));
    assert.equal(requestBodies.length, 3);
    assert.equal(requestBodies[0].startTranscription, true);
    assert.equal(requestBodies[1].startTranscription, false);
    assert.match(await page.locator("#subtitleCueList").textContent(), /自动识别的对白/);
    await page.locator("[data-subtitle-close]").last().click();
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("person frame indexing shows startup honestly before counted progress", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const started = {
        status: "running", stage: "content_recognition", progressMode: "indeterminate",
        etaMode: "waiting_first_sample", processingElapsedSeconds: 94,
        currentAction: "人物识别 1/2 · 正在准备解码分析帧 · 共 1352 帧，首批完成后显示进度",
      };
      const advancing = {
        ...started, progressMode: "determinate", etaMode: "collecting",
        stageCompleted: 4, stageTotal: 1352, stageUnit: "帧", stageProgress: 4 / 1352,
        currentAction: "人物识别 1/2 · 正在解码分析帧（4/1352 帧）",
      };
      return {
        startupFact: stageProgressFact(started, 0, true),
        startupEta: progressEtaText(started, true),
        elapsed: processingElapsedLabel(started),
        advancingFact: stageProgressFact(advancing, 1, false),
        legacyDecode: friendlyProgressDetail("正在抽取人物轨迹采样帧（4/1352 帧）"),
        legacyTracking: friendlyProgressDetail("正在建立人物轨迹（504/2809 帧）"),
      };
    });
    assert.deepEqual(audit, {
      startupFact: "正在准备首批采样帧",
      startupEta: "首批完成后开始估算速度",
      elapsed: "任务已运行 1:34",
      advancingFact: "已完成 4/1352 帧",
      legacyDecode: "人物识别 1/2 · 正在解码分析帧（4/1352 帧）",
      legacyTracking: "人物识别 2/2 · 正在检测人物并关联轨迹（504/2809 帧）",
    });
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("replanned highlight batches disclose target and evidence reuse", async () => {
  const source = await readFile(join(staticRoot, "app.js"), "utf8");
  assert.match(source, /batch\.mode === "replan"/);
  assert.match(source, /重排批次/);
  assert.match(source, /batch\.evidenceSource === "existing_analysis"/);
  assert.match(source, /复用已有分析/);
});

test("highlight review reveals only settings relevant to the current selection", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const segment = (id, start, end) => ({ id, start, end, duration: end - start });
      const job = {
        id: "highlight_dynamic_settings",
        status: "awaiting_confirmation",
        videoInfo: { has_audio: true, width: 1920, height: 1080 },
        eventGroups: [
          { id: "event_1", title: "事件一", segments: [segment("shot_1", 2, 6)] },
          { id: "event_2", title: "事件二", segments: [segment("shot_2", 12, 16)] },
        ],
        speechAnalysis: { segments: [] },
      };
      const railBody = document.querySelector("#railBody") || Object.assign(document.createElement("div"), { id: "railBody" });
      const railOutput = document.querySelector("#railOutput") || Object.assign(document.createElement("div"), { id: "railOutput" });
      if (!railBody.isConnected) document.body.append(railBody);
      if (!railOutput.isConnected) document.body.append(railOutput);
      railBody.innerHTML = `<article class="event-group-row" data-event-group="event_1">
        <input class="rail-event-check" type="checkbox" value="event_1" checked>
        <div class="event-segment" data-segment-id="shot_1">
          <div class="segment-technique-controls"><select class="segment-speed"></select></div>
        </div>
      </article><button class="open-compose-stage" type="button">继续生成成片</button>`;
      currentJob = job;
      eventGroupSelectionOrder = ["event_1"];
      pendingSegmentSelections = new Map([["event_1", new Set(["shot_1"])]]);
      bindRailEventActions(job);
      renderRailOutput(job);
      railBody.querySelector(".open-compose-stage").addEventListener("click", () => setDirectorStage("compose"));
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      document.querySelector("#reviewView")?.classList.remove("hidden");
      document.querySelector("#timelinePanel")?.classList.remove("hidden");
      setDirectorStage("events");
      setReviewLowerPanelMode("review");
      const techniqueToggle = railBody.querySelector(".segment-technique-toggle");
      const techniqueControls = railBody.querySelector(".segment-technique-controls");
      const initial = {
        outputModes: document.querySelectorAll("#railOutput [data-output-mode]").length,
        subtitles: document.querySelectorAll("#railOutput #subtitleMode").length,
        specs: document.querySelector("#railOutput .output-specs-summary")?.textContent || "",
        techniqueHidden: techniqueControls.classList.contains("hidden"),
        dockTitle: document.querySelector("#reviewActionTitle")?.textContent || "",
        dockMeta: document.querySelector("#reviewActionMeta")?.textContent || "",
        dockPrimary: document.querySelector("#reviewActionPrimary")?.textContent || "",
        dockDisabled: document.querySelector("#reviewActionPrimary")?.disabled,
      };
      setTimelineExpanded(true);
      initial.precision = {
        dockParent: document.querySelector("#reviewActionDock")?.parentElement?.id || "",
        workbenchHidden: getComputedStyle(document.querySelector("#reviewWorkbench")).display === "none",
        contextVisible: getComputedStyle(document.querySelector("#timelinePrecisionContext")).display !== "none",
        toggleLabel: document.querySelector("#timelineExpandToggle")?.textContent || "",
      };
      setTimelineExpanded(false);
      document.querySelector("#reviewActionPrimary").click();
      const dockOpenedCompose = directorStage === "compose";
      setDirectorStage("events");
      techniqueToggle.click();
      const techniqueExpanded = !techniqueControls.classList.contains("hidden");
      railBody.innerHTML += '<input class="rail-event-check" type="checkbox" value="event_2" checked>';
      eventGroupSelectionOrder = ["event_1", "event_2"];
      pendingSegmentSelections.set("event_2", new Set(["shot_2"]));
      job.speechAnalysis.segments = [{ start: 12.2, end: 14, text: "这是第二个事件的对白。" }];
      renderRailOutput(job);
      return {
        initial,
        dockOpenedCompose,
        techniqueExpanded,
        multipleOutputModes: document.querySelectorAll("#railOutput [data-output-mode]").length,
        multipleHasSubtitles: document.querySelectorAll("#railOutput #subtitleMode").length,
      };
    });
    assert.equal(audit.initial.outputModes, 0);
    assert.equal(audit.initial.subtitles, 0);
    assert.match(audit.initial.specs, /MP4 · H\.264.*1920×1080.*自动设置/s);
    assert.equal(audit.initial.techniqueHidden, true);
    assert.match(audit.initial.dockTitle, /已选 1 个事件 · 1 个镜头/);
    assert.match(audit.initial.dockMeta, /预计 4\.0 秒/);
    assert.equal(audit.initial.dockPrimary, "继续生成成片");
    assert.equal(audit.initial.dockDisabled, false);
    assert.deepEqual(audit.initial.precision, {
      dockParent: "timelinePrecisionContext", workbenchHidden: true,
      contextVisible: true, toggleLabel: "返回审核列表",
    });
    assert.equal(audit.dockOpenedCompose, true);
    assert.equal(audit.techniqueExpanded, true);
    assert.equal(audit.multipleOutputModes, 2);
    assert.equal(audit.multipleHasSubtitles, 1);
    assert.deepEqual(pageErrors, []);
    await page.evaluate(() => {
      const visualJob = {
        ...currentJob,
        filename: "舞台表演.mp4", taskMode: "highlight", workflowKind: "highlight",
        status: "awaiting_confirmation", stage: "review", progress: 1,
        videoInfo: { duration: 30, width: 1920, height: 1080, has_audio: true, frame_rate: 25 },
        request: {}, messages: [], outputs: [], outputVersions: [],
        candidates: [{ index: 0, title: "舞台动作候选", start: 3, end: 6, duration: 3, score: 82 }],
        recommendedGroupIds: ["event_1", "event_2"],
      };
      switchWorkspaceJob(visualJob);
      setDirectorStage("events");
    });
    assert.deepEqual(await page.locator("#reviewPanelSwitch button:not(.hidden)").evaluateAll((buttons) => buttons.map((button) => button.textContent.trim())), ["高光事件2", "镜头候选1", "精细时间线"]);
    assert.equal(await page.locator("#openCandidateDrawer").evaluate((button) => button.parentElement?.classList.contains("review-panel-switch-tabs")), true);
    await page.locator("#openCandidateDrawer").click();
    assert.equal(await page.locator("#candidateDrawer").isVisible(), true);
    assert.equal(await page.locator("#openCandidateDrawer").getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator("#reviewView").getAttribute("data-lower-panel-mode"), "collapsed");
    assert.equal(await page.locator("#reviewWorkbench").isVisible(), false);
    assert.equal(await page.locator("#timelinePanel").isVisible(), false);
    await page.locator("#reviewPanelReviewTab").click();
    assert.equal(await page.locator("#candidateDrawer").getAttribute("aria-hidden"), "true");
    assert.equal(await page.locator("#reviewPanelReviewTab").getAttribute("aria-pressed"), "true");
    await page.locator("#openCandidateDrawer").click();
    await page.locator("#reviewPanelTimelineTab").click();
    assert.equal(await page.locator("#candidateDrawer").getAttribute("aria-hidden"), "true");
    assert.equal(await page.locator("#reviewPanelTimelineTab").getAttribute("aria-pressed"), "true");
    const precisionLayout = await page.evaluate(() => {
      const view = document.querySelector("#reviewView").getBoundingClientRect();
      const player = document.querySelector("#reviewStage").getBoundingClientRect();
      const timeline = document.querySelector("#timelinePanel").getBoundingClientRect();
      const workbench = document.querySelector("#reviewWorkbench").getBoundingClientRect();
      const timelineStyle = getComputedStyle(document.querySelector("#timelinePanel"));
      const viewportStyle = getComputedStyle(document.querySelector("#timelineViewport"));
      const trackStyle = getComputedStyle(document.querySelector("#timelineTrackContent"));
      const switchStyle = getComputedStyle(document.querySelector("#reviewPanelSwitch"));
      return {
        gridRows: getComputedStyle(document.querySelector("#reviewView")).gridTemplateRows,
        view: { top: view.top, bottom: view.bottom, height: view.height },
        player: { top: player.top, bottom: player.bottom, height: player.height },
        workbench: { top: workbench.top, bottom: workbench.bottom, height: workbench.height },
        timeline: { top: timeline.top, bottom: timeline.bottom, height: timeline.height },
        colors: {
          timeline: timelineStyle.backgroundImage,
          viewport: viewportStyle.backgroundImage,
          track: trackStyle.backgroundImage,
          switcher: switchStyle.backgroundImage,
          trackLabel: getComputedStyle(document.querySelector("#timelineTrackLabels span")).color,
        },
      };
    });
    assert.ok(precisionLayout.timeline.top - precisionLayout.player.bottom <= 50, JSON.stringify(precisionLayout));
    assert.ok(precisionLayout.timeline.height >= 250, JSON.stringify(precisionLayout));
    assert.ok(precisionLayout.timeline.bottom <= precisionLayout.view.bottom + 1, JSON.stringify(precisionLayout));
    assert.match(precisionLayout.colors.timeline, /linear-gradient/);
    assert.match(precisionLayout.colors.viewport, /linear-gradient/);
    assert.match(precisionLayout.colors.track, /linear-gradient/);
    assert.match(precisionLayout.colors.switcher, /linear-gradient/);
    assert.equal(precisionLayout.colors.trackLabel, "rgb(83, 97, 105)");
    await page.screenshot({ path: join(projectRoot, "test-results/single-timeline-highlight.png"), fullPage: true });
    await page.evaluate(() => setTimelineExpanded(false));
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("single-input upload confirms ambiguous routing and keeps one primary result", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const posts = [];
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/workflow-intent/classify", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          decision: {
            action: "clarify", workflowKind: "highlight", confidence: .62,
            reason: "要求没有说明是查找内容还是生成成片", needsConfirmation: true,
          },
          options: [
            { id: "highlight", label: "自动生成高光" },
            { id: "content_search", label: "查找并截取内容" },
            { id: "person_edit", label: "按画面人物剪辑" },
            { id: "speaker_edit", label: "按说话人剪辑" },
          ],
        }),
      });
    });
    await page.route("**/api/jobs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      posts.push(route.request().postData() || "");
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ job: { id: "routed-highlight", workflowKind: "highlight", status: "queued", messages: [] } }),
      });
    });
    await page.locator("[data-home-create]").click();
    await page.evaluate(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File([new Uint8Array(64)], "ambiguous.mp4", { type: "video/mp4" }));
      const input = document.querySelector("#videoInput");
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      const preview = document.querySelector("#localPreviewVideo");
      Object.defineProperty(preview, "duration", { configurable: true, value: 120 });
      preview.dispatchEvent(new Event("loadedmetadata"));
    });
    assert.equal(await page.locator(".chat-panel").isVisible(), false);
    await page.locator("#briefAutoInstruction").fill("帮我剪一下这个视频");
    await page.locator("[data-start-auto-workflow]").click();
    await page.locator("#briefIntentClarification").waitFor({ state: "visible" });
    assert.equal(posts.length, 0);
    await page.locator('[data-intent-choice="highlight"]').click();
    await page.waitForFunction(() => pendingCreateIntentMode === "highlight");
    await page.waitForFunction(() => currentJob?.id === "routed-highlight");
    assert.equal(posts.length, 1);
    assert.match(posts[0], /name="intent_mode"\r?\n\r?\nhighlight/);
    assert.match(posts[0], /name="source_scope_kind"\r?\n\r?\nall/);
    assert.match(posts[0], /name="parameter_context"\r?\n\r?\nadaptive_v1/);
    assert.doesNotMatch(posts[0], /name="auto_variant_count"|name="result_strategy"|name="target_seconds"/);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("review exclusions use the shared JSON request contract", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const captured = [];
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/jobs/job-review/review-exclusions", async (route) => {
      captured.push({
        contentType: route.request().headers()["content-type"],
        body: route.request().postDataJSON(),
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ job: { id: "job-review", reviewExcludedCandidates: [2, 4] } }),
      });
    });
    const result = await page.evaluate(() => window.ClipTalkReviewActions.persistExclusions({
      jobId: "job-review", indices: [4, 2, 4],
    }));
    assert.deepEqual(result.job.reviewExcludedCandidates, [2, 4]);
    assert.equal(captured[0].contentType, "application/json");
    assert.deepEqual(captured[0].body, { indices: [4, 2] });
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("browser runtime errors are reported once without query strings", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const captured = [];
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/client-errors", async (route) => {
      captured.push(route.request().postDataJSON());
      await route.fulfill({ status: 204, body: "" });
    });
    await page.evaluate(() => {
      window.ClipTalkRuntimeErrors.report({
        kind: "error", name: "ReferenceError", message: "missingName is not defined",
        stack: "ReferenceError: missingName is not defined", scriptPath: "/static/app.js?secret=1", line: 10,
      });
      window.ClipTalkRuntimeErrors.report({
        kind: "error", name: "ReferenceError", message: "missingName is not defined",
        stack: "ReferenceError: missingName is not defined", scriptPath: "/static/app.js?secret=1", line: 10,
      });
    });
    await page.waitForTimeout(100);
    assert.equal(captured.length, 1);
    assert.equal(captured[0].pagePath, "/");
    assert.doesNotMatch(captured[0].scriptPath, /secret/);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("task switches clear transient feedback and never invent a zero person-track count", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(async () => {
      const makeJob = (id, title, candidates = []) => ({
        id, filename: `${id}.mp4`, taskMode: "highlight", workflowKind: "highlight",
        status: "awaiting_confirmation", stage: "review", progress: 1,
        videoInfo: { duration: 30, width: 1280, height: 720, has_audio: true },
        request: {}, messages: [], outputs: [], outputVersions: [], candidates,
        eventGroups: candidates.length ? [{ id: `${id}_event`, title, segments: [] }] : [],
        recommendedGroupIds: candidates.length ? [`${id}_event`] : [],
      });
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      const first = makeJob("transient-a", "事件 A", [{
        index: 0, title: "人物完成动作", reason: "动作完整", score: 92,
        start: 2, end: 6, duration: 4, audioEvidence: {},
      }]);
      const second = makeJob("transient-b", "事件 B");
      switchWorkspaceJob(first);
      openCandidateDrawer();
      const initialDrawerTitle = document.querySelector("#candidateDrawerTitle")?.textContent || "";
      const search = document.querySelector("#candidateDrawerSearch");
      search.value = "不存在";
      search.dispatchEvent(new Event("input", { bubbles: true }));
      const filteredDrawer = {
        title: document.querySelector("#candidateDrawerTitle")?.textContent || "",
        empty: document.querySelector("#candidateDrawerList")?.textContent || "",
        hasClear: Boolean(document.querySelector("[data-candidate-search-clear]")),
      };
      showToast("任务 A 的旧提示", "neutral");
      const confirmationPromise = requestActionConfirmation({
        title: "任务 A 的确认", summary: "切换任务后不应继续显示", details: [],
      });
      await Promise.resolve();
      const beforeSwitch = {
        toast: document.querySelector("#toastRegion")?.textContent || "",
        drawerOpen: document.querySelector("#candidateDrawer")?.classList.contains("open"),
        confirmationOpen: !document.querySelector("#actionConfirm")?.classList.contains("hidden"),
      };
      switchWorkspaceJob(second);
      const confirmationResult = await confirmationPromise;
      const afterSwitch = {
        toast: document.querySelector("#toastRegion")?.textContent || "",
        toastJobId: document.querySelector("#toastRegion")?.dataset.jobId || "",
        drawerOpen: document.querySelector("#candidateDrawer")?.classList.contains("open"),
        drawerJobId: document.querySelector("#candidateDrawer")?.dataset.jobId || "",
        drawerTitle: document.querySelector("#candidateDrawerTitle")?.textContent || "",
        drawerSearch: document.querySelector("#candidateDrawerSearch")?.value || "",
        drawerList: document.querySelector("#candidateDrawerList")?.textContent || "",
        confirmationOpen: !document.querySelector("#actionConfirm")?.classList.contains("hidden"),
        confirmationResult,
      };
      return {
        initialDrawerTitle, filteredDrawer, beforeSwitch, afterSwitch,
        personMessages: {
          missing: personTargetToastPresentation({ reused: true, job: {} }, 1),
          zero: personTargetToastPresentation({ reused: true, job: { contentSearch: { candidateCount: 0, candidates: [] } } }, 1),
          inferred: personTargetToastPresentation({ reused: true, job: { contentSearch: { candidates: [{ id: "m1" }, { id: "m2" }] } } }, 1),
          positive: personTargetToastPresentation({ reused: true, job: { contentSearch: { candidateCount: 3 } } }, 1),
        },
      };
    });
    assert.equal(audit.initialDrawerTitle, "精彩镜头候选（1）");
    assert.deepEqual(audit.filteredDrawer, {
      title: "搜索结果（0/1）",
      empty: "没有匹配的镜头当前候选池仍然存在，只是没有镜头符合搜索条件。清除搜索",
      hasClear: true,
    });
    assert.deepEqual(audit.beforeSwitch, {
      toast: "任务 A 的旧提示×", drawerOpen: true, confirmationOpen: true,
    });
    assert.deepEqual(audit.afterSwitch, {
      toast: "", toastJobId: "", drawerOpen: false, drawerJobId: "",
      drawerTitle: "精彩镜头候选", drawerSearch: "", drawerList: "",
      confirmationOpen: false, confirmationResult: false,
    });
    assert.deepEqual(audit.personMessages, {
      missing: { message: "已复用人物轨迹，检索结果已更新", tone: "neutral" },
      zero: { message: "已检查所选人物轨迹，没有找到可用出镜片段", tone: "neutral" },
      inferred: { message: "已复用人物轨迹，整理出 2 个出镜片段", tone: "success" },
      positive: { message: "已复用人物轨迹，整理出 3 个出镜片段", tone: "success" },
    });
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("person workflow uses a dedicated workspace and stable source-time person tracks", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  const pageErrors = [];
  let targetPayload = null;
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const personJob = {
    id: "person-workspace-job", filename: "person-interview.mp4", taskMode: "content_extract", workflowKind: "person_edit",
    status: "completed", stage: "completed", progress: 1,
    videoInfo: { duration: 30, width: 1280, height: 720, has_audio: true, frame_rate: 25 },
    request: {}, messages: [], outputs: [], outputVersions: [], candidates: [],
    eventGroups: [{ id: "stale_person_selection", title: "人物 A 出镜 1", segments: [{ id: "stale_person_segment", start: 1, end: 4 }] }],
    contentIndex: { persons: [
      { id: "person_1", label: "人物 A", defaultLabel: "人物 A", confidence: .91, representativeTime: 2,
        thumbnailUrl: "", ranges: [{ start: 1, end: 4 }, { start: 12, end: 16 }] },
      { id: "person_2", label: "人物 B", defaultLabel: "人物 B", confidence: .86, reviewRecommended: true, representativeTime: 7,
        thumbnailUrl: "", ranges: [{ start: 6, end: 10 }] },
    ] },
  };
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/jobs/person-workspace-job/content-search/target-person", async (route) => {
      targetPayload = route.request().postDataJSON();
      const resultCandidate = {
        id: "person_match_1", title: "人物 A 出镜 · 第 1 段", start: 1, end: 4, duration: 3,
        score: 100, confidenceTier: "reliable", reviewStatus: "confirmed", evidenceType: "person",
        matchedModalities: ["person"], matchedPersonIds: ["person_1"], matchedPersonLabels: ["人物 A"],
        selected: true, requiresReview: false,
      };
      const resultSearch = {
        id: "person_search_1", status: "confirmed", instruction: "提取人物 A 的所有出镜片段",
        resultMode: "exhaustive", coverageComplete: true, candidates: [resultCandidate],
        defaultSelectedIds: [resultCandidate.id], completeness: { status: "complete", occurrenceCount: 1, clipCount: 1, channels: [] },
        executionPlan: { allowedCapabilities: ["person"] }, retrievalStats: { totalMilliseconds: 15, coverageComplete: true },
        intent: { query: "提取人物 A 的所有出镜片段", personTarget: targetPayload },
      };
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ reused: true, job: {
          ...personJob, status: "awaiting_content_confirmation", stage: "content_search_ready",
          contentUiRevision: "person-target-1", contentSearchPersonTarget: targetPayload,
          request: { contentSearchPersonTarget: targetPayload }, contentSearch: resultSearch,
          contentSearchSession: { activeSearchId: resultSearch.id, state: "ready" }, contentSearchRecords: [resultSearch],
          messages: [{ id: "person_search_message", role: "assistant", kind: "content-search", contentSearchId: resultSearch.id, text: "已整理出 1 个出镜片段" }],
        } }),
      });
    });
    await page.evaluate((job) => {
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      switchWorkspaceJob(job);
    }, personJob);
    assert.equal(await page.locator("[data-open-person-workspace]").isVisible(), false);
    assert.equal(await page.locator("#reviewPanelSubjectTab").isVisible(), true);
    assert.equal(await page.locator("#reviewPanelSubjectLabel").textContent(), "画面人物");
    assert.equal(await page.locator("#reviewPanelSubjectCount").textContent(), "2");
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-controls"), "personProfilePanel");
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "false");
    await page.locator("#reviewPanelSubjectTab").click();
    await page.locator(".current-person-card").first().waitFor({ state: "visible" });
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "true");
    assert.equal(await page.locator("#reviewPanelSubjectTab").evaluate((button) => button.classList.contains("active")), true);
    await page.locator("#reviewPanelSubjectTab").click();
    assert.equal(await page.locator("#personProfilePanel").evaluate((panel) => panel.classList.contains("hidden")), true);
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "false");
    assert.equal(await page.locator("#reviewView").getAttribute("data-lower-panel-mode"), "collapsed");
    await page.locator("#reviewPanelSubjectTab").click();
    await page.locator(".current-person-card").first().waitFor({ state: "visible" });
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "true");
    const dockState = await page.evaluate(() => ({
      parentId: document.querySelector("#personProfilePanel")?.parentElement?.id,
      workspaceOpen: document.body.classList.contains("person-workspace-open"),
      chatDisplay: getComputedStyle(document.querySelector(".chat-panel")).display,
      workbenchVisible: !document.querySelector("#reviewWorkbench")?.classList.contains("hidden"),
      timelineTitle: document.querySelector("#timelineTitle")?.textContent,
    }));
    assert.deepEqual(dockState, {
      parentId: "reviewWorkbench", workspaceOpen: true, chatDisplay: "flex", workbenchVisible: true,
      timelineTitle: "人物出镜时间线",
    });
    assert.equal(await page.locator("#timelinePanel").isVisible(), false);
    const workbenchResizer = page.locator("#reviewWorkbenchResizer");
    assert.equal(await workbenchResizer.isVisible(), true);
    assert.equal(await workbenchResizer.getAttribute("aria-orientation"), "horizontal");
    assert.equal(await workbenchResizer.getAttribute("aria-disabled"), "false");
    const initialWorkbenchHeight = await page.locator("#reviewWorkbench").evaluate((panel) => panel.getBoundingClientRect().height);
    const resizerBox = await workbenchResizer.boundingBox();
    assert.ok(resizerBox, "person workbench resize handle should have a bounding box");
    await page.mouse.move(resizerBox.x + resizerBox.width / 2, resizerBox.y + resizerBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(resizerBox.x + resizerBox.width / 2, resizerBox.y - 60, { steps: 4 });
    await page.mouse.up();
    const enlargedWorkbenchHeight = await page.locator("#reviewWorkbench").evaluate((panel) => panel.getBoundingClientRect().height);
    assert.ok(enlargedWorkbenchHeight > initialWorkbenchHeight + 40,
      `person workbench height did not grow: ${initialWorkbenchHeight} -> ${enlargedWorkbenchHeight}`);
    assert.equal(await page.locator("#reviewView").evaluate((view) => Boolean(view.style.getPropertyValue("--review-workbench-height"))), true);
    const heightBeforeKeyboard = enlargedWorkbenchHeight;
    await workbenchResizer.focus();
    await page.keyboard.press("ArrowDown");
    const keyboardAdjustedHeight = await page.locator("#reviewWorkbench").evaluate((panel) => panel.getBoundingClientRect().height);
    assert.ok(keyboardAdjustedHeight < heightBeforeKeyboard - 10,
      `keyboard resize did not shrink the panel: ${heightBeforeKeyboard} -> ${keyboardAdjustedHeight}`);
    await workbenchResizer.dblclick();
    const resetWorkbenchHeight = await page.locator("#reviewWorkbench").evaluate((panel) => panel.getBoundingClientRect().height);
    assert.ok(Math.abs(resetWorkbenchHeight - initialWorkbenchHeight) <= 2,
      `double-click did not restore the default height: ${initialWorkbenchHeight} -> ${resetWorkbenchHeight}`);
    assert.equal(await page.locator("#timelineViewport").getAttribute("data-track-layout"), "source-tracks");
    assert.equal(await page.locator("#timelineLabels .timeline-label").count(), 0);
    assert.equal(await page.locator(".current-person-card").count(), 2);
    assert.match(await page.locator(".current-person-card").nth(0).textContent(), /人物 A.*7\.0 秒出镜.*2 段.*2 次画面观测.*自动分组/);
    assert.match(await page.locator(".current-person-card").nth(1).textContent(), /人物 B.*短暂或不稳定/);
    assert.equal(await page.locator("#personMergeToolbar").isVisible(), true);
    assert.equal(await page.locator("[data-current-person-range]").count(), 3);
    assert.equal(await page.locator('[data-current-person="person_1"] [data-current-person-range]').count(), 2);
    assert.match(await page.locator('[data-current-person="person_1"] .current-person-ranges').textContent(), /全部出镜片段.*片段 1.*00:01.*00:04.*片段 2.*00:12.*00:16/);
    await page.evaluate(() => {
      Object.defineProperty(mainVideo, "duration", { configurable: true, value: 30 });
      Object.defineProperty(mainVideo, "readyState", { configurable: true, value: 1 });
      Object.defineProperty(mainVideo, "currentTime", { configurable: true, writable: true, value: 11 });
    });
    await page.locator('[data-current-person-preview="person_1"]').click();
    const representativePreview = await page.evaluate(() => ({
      currentTime: mainVideo.currentTime,
      previewEnd: candidatePreviewEnd,
      status: document.querySelector("#personProfileStatus")?.textContent || "",
    }));
    assert.equal(representativePreview.currentTime, 1);
    assert.equal(representativePreview.previewEnd, 4);
    assert.match(representativePreview.status, /正在预览 人物 A 的出镜片段.*00:01.*00:04/);
    await page.locator('[data-current-person="person_1"] [data-current-person-range="1"]').click();
    const secondRangePreview = await page.evaluate(() => ({
      currentTime: mainVideo.currentTime,
      previewEnd: candidatePreviewEnd,
      status: document.querySelector("#personProfileStatus")?.textContent || "",
    }));
    assert.equal(secondRangePreview.currentTime, 12);
    assert.equal(secondRangePreview.previewEnd, 16);
    assert.match(secondRangePreview.status, /正在预览 人物 A 的出镜片段.*00:12.*00:16/);
    await page.screenshot({ path: join(projectRoot, "test-results/person-segment-list.png"), fullPage: true });
    const reviewSummary = page.locator(".current-person-review-group > summary");
    await reviewSummary.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    assert.equal(await reviewSummary.evaluate((summary) => document.activeElement === summary), true);
    assert.equal(await reviewSummary.evaluate((summary) => getComputedStyle(summary).outlineStyle), "solid");
    assert.equal(await page.locator("#timelinePersonTrack").isVisible(), false);
    await page.evaluate(() => {
      currentJob.contentIndex.persons.push(
        { id: "person_3", label: "人物 C", defaultLabel: "人物 C", confidence: .88, representativeTime: 18, thumbnailUrl: "", ranges: [{ start: 17.6, end: 18.3 }] },
        { id: "person_4", label: "人物 D", defaultLabel: "人物 D", confidence: .86, representativeTime: 21, thumbnailUrl: "", ranges: [{ start: 20.8, end: 21 }] },
        { id: "person_5", label: "人物 E", defaultLabel: "人物 E", confidence: .82, representativeTime: 26, thumbnailUrl: "", ranges: [{ start: 25.4, end: 26.1 }] },
      );
      renderCurrentPersons();
    });
    await page.locator("#reviewPanelTimelineTab").click();
    assert.equal(await page.locator("#timelinePersonTrack").isVisible(), true);
    assert.equal(await page.locator("#timelineViewport").isVisible(), false);
    assert.equal(await page.locator("[data-timeline-person-row]").count(), 5);
    assert.equal(await page.locator('[data-timeline-person-row="person_1"] [data-timeline-person-range]').count(), 2);
    assert.equal(await page.locator('[data-timeline-person-row="person_2"] [data-timeline-person-range]').count(), 1);
    assert.match(await page.locator("#timelinePersonTrackCount").textContent(), /5 人 · 6 段/);
    assert.equal(await page.locator("#personProfilePanel").isVisible(), false);
    assert.equal(await page.locator("[data-timeline-person-select]").count(), 5);
    assert.equal(await page.locator("#reviewPanelTimelineTab").getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator("#reviewActionDock").evaluate((node) => node.parentElement?.id), "timelinePrecisionContext");
    assert.equal(await page.locator("#reviewWorkbench").isVisible(), false);
    await page.locator("#reviewPanelSubjectTab").click();
    await page.locator(".current-person-card").first().waitFor({ state: "visible" });
    assert.equal(await page.locator("#personProfilePanel").evaluate((node) => node.parentElement?.id), "reviewWorkbench");
    assert.equal(pageErrors.length, 0);
    await page.locator("#reviewPanelTimelineTab").click();
    await page.locator('[data-timeline-person-row="person_1"] [data-timeline-person-range="0"]').click();
    const timelineRangePreview = await page.evaluate(() => ({
      currentTime: mainVideo.currentTime,
      previewEnd: candidatePreviewEnd,
      status: document.querySelector("#personProfileStatus")?.textContent || "",
    }));
    assert.equal(timelineRangePreview.currentTime, 1);
    assert.equal(timelineRangePreview.previewEnd, 4);
    assert.match(timelineRangePreview.status, /正在预览 人物 A 的出镜片段.*00:01.*00:04/);
    const personTrackFit = await page.evaluate(() => {
      const panel = document.querySelector("#timelinePanel").getBoundingClientRect();
      const track = document.querySelector("#timelinePersonTrack").getBoundingClientRect();
      const lastPerson = document.querySelector('[data-timeline-person-label-ref="person_5"]').getBoundingClientRect();
      return {
        startsNearPanelTop: track.top - panel.top < 70,
        lastPersonInsideTrack: lastPerson.bottom <= track.bottom + 1,
        lastPersonInsideViewport: lastPerson.bottom <= window.innerHeight + 1,
      };
    });
    assert.equal(personTrackFit.startsNearPanelTop, true);
    assert.equal(personTrackFit.lastPersonInsideTrack, true);
    assert.equal(personTrackFit.lastPersonInsideViewport, true);
    await page.screenshot({ path: join(projectRoot, "test-results/person-workspace-dock.png"), fullPage: true });
    await page.setViewportSize({ width: 900, height: 820 });
    const narrowPrecision = await page.evaluate(() => ({
      documentFits: document.documentElement.scrollWidth <= window.innerWidth + 1,
      primaryVisible: getComputedStyle(document.querySelector("#reviewActionPrimary")).display !== "none",
      returnVisible: getComputedStyle(document.querySelector("#reviewPanelReviewTab")).display !== "none",
      lastPersonInsideTrack: document.querySelector('[data-timeline-person-label-ref="person_5"]').getBoundingClientRect().bottom
        <= document.querySelector("#timelinePersonTrack").getBoundingClientRect().bottom + 1,
    }));
    assert.deepEqual(narrowPrecision, {
      documentFits: true, primaryVisible: true, returnVisible: true, lastPersonInsideTrack: true,
    });
    await page.setViewportSize({ width: 1280, height: 820 });
    await page.locator('[data-timeline-person-select][value="person_1"]').check();
    assert.equal(await page.locator('[data-timeline-person-row="person_2"]').evaluate((row) => row.classList.contains("muted")), true);
    assert.equal(await page.locator("#searchSelectedPersons").isDisabled(), false);
    assert.match(await page.locator("#reviewActionTitle").textContent(), /已选 1 人/);
    await page.locator("#reviewActionPrimary").click();
    await page.waitForFunction(() => currentJob?.contentSearchPersonTarget?.personIds?.[0] === "person_1");
    assert.deepEqual(targetPayload, { personIds: ["person_1"], matchMode: "any", activity: "appearance" });
    assert.equal(await page.locator("#personProfilePanel").isVisible(), false);
    assert.equal(await page.locator("#reviewView").getAttribute("data-lower-panel-mode"), "review");
    assert.equal(await page.locator("#reviewWorkbench").isVisible(), true);
    assert.equal(await page.locator("#reviewWorkbenchTitle").textContent(), "第 2 步 · 核对出镜片段");
    assert.equal(await page.locator("#reviewPanelReviewLabel").textContent(), "出镜片段");
    assert.equal(await page.locator("#reviewPanelReviewCount").textContent(), "1");
    assert.equal(await page.locator("#reviewPanelSubjectLabel").textContent(), "重新选人物");
    assert.equal(await page.locator("[data-content-match-row]").count(), 1);
    assert.match(await page.locator(".person-review-handoff").textContent(), /1 个出镜片段就在下方.*更换人物/s);
    await page.screenshot({ path: join(projectRoot, "test-results/person-review-handoff.png"), fullPage: true });
    await page.locator("[data-return-person-selection]").click();
    assert.equal(await page.locator("#personProfilePanel").isVisible(), true);
    await page.locator("#closePersonProfiles").click();
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "false");
    assert.equal(await page.locator(".chat-panel").evaluate((node) => getComputedStyle(node).display), "flex");
    assert.equal(pageErrors.length, 0);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("voice workflow supports correction timeline and temporary cross-video matching", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  const pageErrors = [];
  let temporarySessionPayload = null;
  let voiceRolePayload = null;
  let voiceCorrectionPayload = null;
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.route("**/api/jobs/voice-job/content-search/voices", async (route) => {
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          status: { status: "ready", speakerCount: 2, storesEmbeddings: false },
          voices: [
            { speakerRef: "Speaker 0", label: "声音 A", speechSeconds: 18.4, segmentCount: 7,
              sampleCount: 3, requiresReview: false, quality: { clusterMinimumSimilarity: .84 },
              narration: { status: "candidate", score: .78, reasons: ["发言分布在视频多个位置", "与其他声音重叠较少"] },
              representativeSegments: [{ start: 4.2, end: 8.1, text: "欢迎大家来到今天的节目" }] },
            { speakerRef: "Speaker 1", label: "声音 B", speechSeconds: 9.1, segmentCount: 4,
              sampleCount: 2, requiresReview: true, quality: { clusterMinimumSimilarity: .34, suspectedMixed: true, warning: "簇内声音差异较大" },
              representativeSegments: [{ start: 12.0, end: 14.6, text: "这里可能有重叠说话" }] },
          ],
          timeline: [
            { turnId: "voice_turn_00000", start: 4.2, end: 8.1, duration: 3.9, speakerRef: "Speaker 0", label: "声音 A", text: "欢迎大家来到今天的节目", overlapSeconds: 0, requiresReview: false },
            { turnId: "voice_turn_00001", start: 12, end: 14.6, duration: 2.6, speakerRef: "Speaker 1", label: "声音 B", text: "这里可能有重叠说话", overlapSeconds: .3, requiresReview: true },
          ],
          revision: 0, canUndo: false,
        }),
      });
    });
    await page.route("**/api/jobs/voice-job/content-search/voices/role", async (route) => {
      voiceRolePayload = JSON.parse(route.request().postData() || "{}");
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ voices: [
          { speakerRef: "Speaker 0", label: "旁白", speechSeconds: 18.4, segmentCount: 7,
            sampleCount: 3, requiresReview: false, quality: { clusterMinimumSimilarity: .84 },
            narration: { status: "confirmed", score: 1, reasons: ["已由用户确认为本视频旁白"], confirmedByUser: true },
            representativeSegments: [{ start: 4.2, end: 8.1, text: "欢迎大家来到今天的节目" }] },
          { speakerRef: "Speaker 1", label: "声音 B", speechSeconds: 9.1, segmentCount: 4,
            sampleCount: 2, requiresReview: true, quality: { clusterMinimumSimilarity: .34, suspectedMixed: true, warning: "簇内声音差异较大" },
            narration: { status: "unlikely", score: .31, reasons: [] },
            representativeSegments: [{ start: 12.0, end: 14.6, text: "这里可能有重叠说话" }] },
        ] }),
      });
    });
    await page.route("**/api/jobs/voice-job/content-search/voices/timeline", async (route) => {
      voiceCorrectionPayload = route.request().postDataJSON();
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          voices: [{ speakerRef: "Speaker 0", label: "旁白", speechSeconds: 21, segmentCount: 2,
            sampleCount: 3, requiresReview: false, userCorrected: true, quality: { clusterMinimumSimilarity: .84 },
            narration: { status: "confirmed", score: 1, reasons: ["已由用户确认为本视频旁白"], confirmedByUser: true },
            representativeSegments: [{ start: 4.2, end: 8.1, text: "欢迎大家来到今天的节目" }] }],
          timeline: [
            { turnId: "voice_turn_00000", start: 4.2, end: 8.1, duration: 3.9, speakerRef: "Speaker 0", label: "旁白", text: "欢迎大家来到今天的节目", overlapSeconds: 0, requiresReview: false },
            { turnId: "voice_turn_00001", start: 12, end: 14.6, duration: 2.6, speakerRef: "Speaker 0", label: "旁白", text: "这里可能有重叠说话", overlapSeconds: 0, requiresReview: false },
          ],
          revision: 1, canUndo: true,
        }),
      });
    });
    await page.route("**/api/jobs/voice-job/content-search/voices/timeline/undo", async (route) => {
      await route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          voices: [
            { speakerRef: "Speaker 0", label: "旁白", speechSeconds: 18.4, segmentCount: 7,
              sampleCount: 3, requiresReview: false, quality: { clusterMinimumSimilarity: .84 },
              narration: { status: "confirmed", score: 1, reasons: ["已由用户确认为本视频旁白"], confirmedByUser: true },
              representativeSegments: [{ start: 4.2, end: 8.1, text: "欢迎大家来到今天的节目" }] },
            { speakerRef: "Speaker 1", label: "声音 B", speechSeconds: 9.1, segmentCount: 4,
              sampleCount: 2, requiresReview: true, quality: { clusterMinimumSimilarity: .34, suspectedMixed: true, warning: "簇内声音差异较大" },
              narration: { status: "unlikely", score: .31, reasons: [] },
              representativeSegments: [{ start: 12, end: 14.6, text: "这里可能有重叠说话" }] },
          ],
          timeline: [
            { turnId: "voice_turn_00000", start: 4.2, end: 8.1, duration: 3.9, speakerRef: "Speaker 0", label: "旁白", text: "欢迎大家来到今天的节目", overlapSeconds: 0, requiresReview: false },
            { turnId: "voice_turn_00001", start: 12, end: 14.6, duration: 2.6, speakerRef: "Speaker 1", label: "声音 B", text: "这里可能有重叠说话", overlapSeconds: .3, requiresReview: true },
          ],
          revision: 0, canUndo: false,
        }),
      });
    });
    await page.route("**/api/jobs/voice-job/content-search/voice-sessions/sources", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ maximumSelection: 12, sources: [{ jobId: "target-job", filename: "另一段采访.mp4", duration: 42 }] }) });
    });
    await page.route("**/api/jobs/voice-job/content-search/voice-sessions", async (route) => {
      temporarySessionPayload = JSON.parse(route.request().postData() || "{}");
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ accepted: true, session: { id: "voice_session_test", status: "queued", progress: 0, detail: "正在排队", results: [] } }) });
    });
    await page.route("**/api/jobs/voice-job/content-search/voice-sessions/voice_session_test", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session: { id: "voice_session_test", status: "completed", progress: 1, detail: "已完成 1 个视频，1 个视频找到匹配发言", results: [{ sourceJobId: "target-job", filename: "另一段采访.mp4", status: "ready", matchedSegmentCount: 3, pendingReviewCount: 0, resultJobId: "result-job" }] } }) });
    });
    await page.evaluate(() => {
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      switchWorkspaceJob({
        id: "voice-job", filename: "voice-interview.mp4", taskMode: "content_extract", workflowKind: "speaker_edit", status: "completed", stage: "completed", progress: 1,
        videoInfo: { duration: 30, width: 1280, height: 720, has_audio: true, frame_rate: 25 },
        request: {}, messages: [], outputs: [], outputVersions: [], candidates: [],
        eventGroups: [{ id: "stale_voice_selection", title: "声音 B 发言 1", segments: [{ id: "stale_voice_segment", start: 12, end: 14.6 }] }],
      });
    });
    assert.equal(await page.locator("[data-open-speaker-workspace]").isVisible(), false);
    assert.equal(await page.locator("#reviewPanelSubjectTab").isVisible(), true);
    assert.equal(await page.locator("#reviewPanelSubjectLabel").textContent(), "说话人");
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-controls"), "voiceProfilePanel");
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "false");
    await page.locator("#reviewPanelSubjectTab").click();
    await page.locator(".current-voice-card").first().waitFor({ state: "visible" });
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "true");
    assert.equal(await page.locator("#reviewPanelSubjectCount").textContent(), "2");
    await page.locator("#reviewPanelSubjectTab").click();
    assert.equal(await page.locator("#voiceProfilePanel").evaluate((panel) => panel.classList.contains("hidden")), true);
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "false");
    await page.locator("#reviewPanelSubjectTab").click();
    await page.locator(".current-voice-card").first().waitFor({ state: "visible" });
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "true");
    assert.match(await page.locator("#voiceProfilePanel > header").textContent(), /右侧视频和时间轴始终可以操作/);
    const dockState = await page.evaluate(() => ({
      parentId: document.querySelector("#voiceProfilePanel")?.parentElement?.id,
      ariaModal: document.querySelector("#voiceProfilePanel")?.getAttribute("aria-modal"),
      backdropCount: document.querySelectorAll("#voiceProfileBackdrop").length,
      bodyLocked: document.body.classList.contains("settings-open"),
      workspaceOpen: document.body.classList.contains("voice-workspace-open"),
      chatDisplay: getComputedStyle(document.querySelector(".chat-panel")).display,
      workbenchVisible: !document.querySelector("#reviewWorkbench")?.classList.contains("hidden"),
      reviewDisplay: getComputedStyle(document.querySelector(".review-panel")).display,
      reviewWidth: document.querySelector(".review-panel").getBoundingClientRect().width,
      playerPointerEvents: getComputedStyle(document.querySelector("#mainVideo")).pointerEvents,
    }));
    assert.deepEqual(dockState, {
      parentId: "reviewWorkbench", ariaModal: null, backdropCount: 0, bodyLocked: false,
      workspaceOpen: true, chatDisplay: "flex", workbenchVisible: true, reviewDisplay: "block",
      reviewWidth: dockState.reviewWidth, playerPointerEvents: "auto",
    });
    assert.ok(dockState.reviewWidth > 500, `review workspace width was ${dockState.reviewWidth}px`);
    await page.screenshot({ path: join(projectRoot, "test-results/voice-workspace-dock.png"), fullPage: true });
    assert.equal(await page.locator(".current-voice-card").count(), 2);
    assert.match(await page.locator(".current-voice-card").nth(0).textContent(), /声音 A.*18\.4 秒发言.*疑似旁白/);
    assert.match(await page.locator(".current-voice-card").nth(1).textContent(), /声音 B.*疑似混声/);
    await page.locator('[data-current-voice-role="Speaker 0"]').click();
    assert.deepEqual(voiceRolePayload, { speakerRef: "Speaker 0", role: "narrator" });
    await page.waitForFunction(() => document.querySelector(".current-voice-card")?.textContent.includes("已确认旁白"));
    assert.match(await page.locator(".current-voice-card").nth(0).textContent(), /旁白.*已确认旁白/);
    assert.equal(await page.locator("#expectedVoiceCount").inputValue(), "0");
    assert.match(await page.locator("#discoverCurrentVoices").textContent(), /重新识别说话人/);
    assert.equal(await page.locator("#discoverCurrentVoices").isDisabled(), false);
    await page.locator("#expectedVoiceCount").selectOption("2");
    assert.match(await page.locator("#discoverCurrentVoices").textContent(), /按新人数重新识别/);
    assert.equal(await page.locator("#discoverCurrentVoices").isDisabled(), false);
    await page.locator("#expectedVoiceCount").selectOption("0");
    assert.equal(await page.locator("#discoverCurrentVoices").isDisabled(), false);
    assert.equal(await page.locator(".current-voice-turn").count(), 2);
    assert.equal(await page.locator("#currentVoiceTimeline").count(), 0);
    assert.match(await page.locator("#currentVoiceTimelineSection > summary").textContent(), /校正发言归属.*勾选分错的发言/);
    assert.equal(await page.locator("#timelineSpeakerTrack").isVisible(), false);
    await page.locator("#reviewPanelTimelineTab").click();
    assert.equal(await page.locator("#timelineSpeakerTrack").isVisible(), true);
    assert.equal(await page.locator("#timelineTitle").textContent(), "说话人时间线");
    assert.equal(await page.locator("#timelineViewport").getAttribute("data-track-layout"), "source-tracks");
    assert.equal(await page.locator("#timelineViewport").isVisible(), false);
    assert.deepEqual(await page.locator("#timelineTrackLabels span").allTextContents(), ["画面", "音频"]);
    assert.equal(await page.locator("#timelineLabels .timeline-label").count(), 0);
    assert.equal(await page.locator("[data-timeline-speaker-turn]").count(), 2);
    assert.equal(await page.locator("[data-timeline-speaker-row]").count(), 2);
    assert.deepEqual(await page.locator("[data-timeline-speaker-row]").evaluateAll((rows) => rows.map((row) => ({
      speaker: row.dataset.timelineSpeakerRow,
      turns: [...row.querySelectorAll("[data-timeline-speaker-ref]")].map((turn) => turn.dataset.timelineSpeakerRef),
    }))), [
      { speaker: "Speaker 0", turns: ["Speaker 0"] },
      { speaker: "Speaker 1", turns: ["Speaker 1"] },
    ]);
    assert.match(await page.locator("#timelineSpeakerTrackCount").textContent(), /2 人 · 2 段/);
    assert.equal(await page.locator("#voiceProfilePanel").isVisible(), false);
    assert.equal(await page.locator("[data-timeline-speaker-select]").count(), 2);
    assert.equal(await page.locator("#reviewPanelTimelineTab").getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator("#reviewActionDock").evaluate((node) => node.parentElement?.id), "timelinePrecisionContext");
    assert.equal(await page.locator("#reviewWorkbench").isVisible(), false);
    await page.locator("#reviewActionSettings").click();
    assert.equal(await page.locator("#timelinePrecisionDrawer").isVisible(), true);
    assert.equal(await page.locator("#currentVoiceTimelineSection").evaluate((node) => node.parentElement?.id), "timelinePrecisionDrawerBody");
    assert.equal(await page.locator("#reassignVoiceTurns").isVisible(), true);
    await page.locator("#currentVoiceTurns [data-voice-turn-select]").nth(1).check();
    assert.match(await page.locator("#voiceTurnSelectionSummary").textContent(), /已选 1 段.*2\.6 秒/);
    await page.locator("#voiceReassignTarget").selectOption("Speaker 0");
    assert.equal(await page.locator("#reassignVoiceTurns").isDisabled(), false);
    await page.locator("#reassignVoiceTurns").click();
    await page.waitForFunction(() => document.querySelector("#voiceProfileStatus")?.textContent.includes("后续提取立即生效"));
    assert.deepEqual(voiceCorrectionPayload, {
      operation: "reassign", turnIds: ["voice_turn_00001"], targetSpeakerRef: "Speaker 0", label: "", revision: 0,
    });
    assert.match(await page.locator("#currentVoiceTurnCount").textContent(), /已校正 r1/);
    await page.locator("#undoVoiceCorrection").click();
    await page.waitForFunction(() => document.querySelector("#voiceProfileStatus")?.textContent.includes("已撤销最近一次校正"));
    assert.match(await page.locator("#currentVoiceTurnCount").textContent(), /自动分组/);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#timelinePrecisionDrawer").isVisible(), false);
    assert.equal(await page.locator("#currentVoiceTimelineSection").evaluate((node) => node.closest("#voiceProfilePanel")?.id), "voiceProfilePanel");
    assert.equal(await page.locator("#reviewActionSettings").evaluate((node) => document.activeElement === node), true);
    const timelineAlignment = await page.evaluate(() => {
      const speakers = document.querySelector(".timeline-speaker-track-content").getBoundingClientRect();
      const review = document.querySelector("#reviewView").getBoundingClientRect();
      const player = document.querySelector("#reviewStage").getBoundingClientRect();
      const timeline = document.querySelector("#timelinePanel").getBoundingClientRect();
      return {
        speakerTrackHasWidth: speakers.width > timeline.width * .7,
        speakerTrackNearTop: speakers.top - timeline.top < 70,
        timelineBelowPlayer: timeline.top >= player.bottom - 1,
        timelineInsideWorkspace: timeline.bottom <= review.bottom + 1,
        timelineInsideViewport: timeline.bottom <= window.innerHeight + 1,
        timelineHeight: timeline.height,
      };
    });
    assert.equal(timelineAlignment.speakerTrackHasWidth, true);
    assert.equal(timelineAlignment.speakerTrackNearTop, true);
    assert.equal(timelineAlignment.timelineBelowPlayer, true);
    assert.equal(timelineAlignment.timelineInsideWorkspace, true);
    assert.equal(timelineAlignment.timelineInsideViewport, true);
    assert.ok(timelineAlignment.timelineHeight >= 240, `timeline height was ${timelineAlignment.timelineHeight}px`);
    await page.locator("#timelinePanel").screenshot({ path: join(projectRoot, "test-results/voice-speaker-timeline.png") });
    await page.locator("[data-timeline-speaker-turn]").first().click();
    assert.equal(await page.locator(".current-voice-card").first().evaluate((node) => node.classList.contains("focused")), true);
    const optionalVoiceCompleteness = await page.evaluate(() => effectiveContentSearchCompleteness({
      intent: { schemaVersion: "current-voice-target-intent-v2" },
      completeness: { status: "review_required", pendingCount: 3 },
      candidates: [1, 2, 3].map((value) => ({ id: `possible_${value}`, requiresReview: true, reviewStatus: "pending" })),
    }));
    assert.equal(optionalVoiceCompleteness.status, "complete");
    assert.equal(optionalVoiceCompleteness.pendingCount, 0);
    assert.deepEqual(optionalVoiceCompleteness.optionalCandidateIds, ["possible_1", "possible_2", "possible_3"]);
    await page.locator('[data-timeline-speaker-select][value="Speaker 0"]').check();
    assert.equal(await page.locator('[data-timeline-speaker-ref="Speaker 0"]').evaluate((node) => node.classList.contains("selected")), true);
    await page.locator('[data-timeline-speaker-select][value="Speaker 1"]').check();
    assert.equal(await page.locator("#mergeSelectedVoices").isDisabled(), false);
    await page.locator("#reviewActionMode").selectOption("qa_pair");
    assert.equal(await page.locator("#currentVoiceMode").inputValue(), "qa_pair");
    assert.equal(await page.locator("#reviewActionPrimary").isDisabled(), true);
    await page.locator('[data-timeline-speaker-select][value="Speaker 1"]').uncheck();
    await page.locator("#reviewPanelSubjectTab").click();
    assert.equal(await page.locator("#voiceProfilePanel").isVisible(), true);
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator("#crossVideoVoiceSection").evaluate((node) => node.open), false);
    await page.locator("#crossVideoVoiceSection > summary").click();
    await page.locator("[data-temporary-voice-source]").check();
    await page.locator("#startTemporaryVoiceSearch").click();
    await page.locator(".temporary-session-result.ready").waitFor({ state: "visible" });
    assert.deepEqual(temporarySessionPayload.referenceSpeakerRef, "Speaker 0");
    assert.deepEqual(temporarySessionPayload.targetJobIds, ["target-job"]);
    assert.match(await page.locator("#temporaryVoiceSession").textContent(), /找到 3 段/);
    await page.locator("#closeVoiceProfiles").click();
    assert.equal(await page.locator("#reviewPanelSubjectTab").getAttribute("aria-expanded"), "false");
    assert.equal(await page.locator(".chat-panel").evaluate((node) => getComputedStyle(node).display), "flex");
    assert.equal(await page.locator("#voiceProfilePanel").evaluate((node) => node.classList.contains("hidden")), true);
    await page.evaluate(() => resetCurrentVoiceState("next-video"));
    assert.equal(await page.locator("#currentVoiceMode").inputValue(), "include");
    assert.equal(pageErrors.length, 0);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("content review stays in the review stage and generated versions follow their result messages", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const candidate = {
        id: "match_1", title: "说话人 B 的完整回答", start: 10, end: 18, duration: 8,
        score: 72, confidenceTier: "possible", reviewStatus: "kept", requiresReview: false,
        speaker: "说话人 B", evidenceType: "speech", matchedModalities: ["speech"],
        transcriptExcerpt: "这是已经试听并确认保留的回答。",
      };
      const search = {
        id: "search_timeline", status: "confirmed", createdAt: "2026-08-25T12:00:00Z",
        instruction: "保留说话人 B 的完整问答", resultMode: "exhaustive",
        coverageComplete: true, defaultSelectedIds: ["match_1"], candidates: [candidate],
        completeness: { status: "complete", occurrenceCount: 1, clipCount: 1, channels: [] },
        executionPlan: { allowedCapabilities: ["speech"] },
        retrievalStats: { totalMilliseconds: 850, evidenceHitCount: 0, coverageComplete: true },
        intent: { schemaVersion: "current-voice-target-intent-v2", query: "保留说话人 B 的完整问答" },
      };
      const output = (filename) => ({
        filename, duration: 8, segmentCount: 1,
        previewUrl: `/api/outputs/${filename}`, segments: [{ start: 10, end: 18 }],
      });
      const job = {
        id: "job_content_timeline", taskMode: "content_extract", status: "awaiting_content_confirmation",
        stage: "content_confirmation", filename: "访谈.mp4", videoInfo: { duration: 90, width: 1280, height: 720, has_audio: true },
        speechAnalysis: { segments: [{ start: 10, end: 18, text: "这是已经试听并确认保留的回答。" }] },
        request: { entryWorkflow: "voice_discovery" }, contentSearch: search,
        contentSearchSession: { activeSearchId: search.id, state: "ready" }, contentSearchRecords: [search],
        messages: [
          { id: "m1", role: "user", kind: "message", text: "识别当前视频中的说话人" },
          { id: "m2", role: "assistant", kind: "content-search", contentSearchId: search.id, text: "已整理说话人 B 的 1 段发言。" },
          { id: "m3", role: "user", kind: "message", text: "确认 1 个内容片段并开始生成。" },
          { id: "m4", role: "assistant", kind: "result", outputVersionId: "version_1", text: "已保存为 V1：按源视频时间顺序合成。" },
          { id: "m5", role: "user", kind: "message", text: "重新选择已经检索到的内容片段" },
          { id: "m6", role: "assistant", kind: "revision", text: "已返回内容片段确认。" },
          { id: "m7", role: "user", kind: "message", text: "确认 1 个内容片段并开始生成。" },
          { id: "m8", role: "assistant", kind: "result", text: "已保存为 V2：按源视频时间顺序合成。" },
        ],
        outputVersions: [
          { id: "version_1", number: 1, outputMode: "single_reel", contentSearchId: search.id, outputs: [output("v001-content.mp4")] },
          { id: "version_2", number: 2, outputMode: "single_reel", contentSearchId: search.id, outputs: [output("v002-content.mp4")] },
        ],
        outputs: [output("v001-content.mp4"), output("v002-content.mp4")],
      };
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      document.querySelector("#uploadView")?.classList.add("hidden");
      document.querySelector("#reviewView")?.classList.remove("hidden");
      setupDirectorWorkspace();
      currentJob = job;
      renderConversation(job);
      renderReviewRail(job);
      setDirectorStage("events");
      setReviewLowerPanelMode("collapsed");
      setReviewLowerPanelMode("review");
      const chat = document.querySelector("#chatMessages");
      const rail = document.querySelector("#railBody");
      if (!chat || !rail) throw new Error(`workspace roots missing: chat=${Boolean(chat)} rail=${Boolean(rail)} host=${Boolean(document.querySelector("#chatStageHost"))} ready=${document.querySelector("#chatStageHost")?.dataset.ready || ""}`);
      const keys = [...chat.querySelectorAll(":scope > [data-conversation-key]")].map((node) => node.dataset.conversationKey);
      const resultOne = keys.indexOf("message:m4");
      const versionOne = keys.indexOf("output-version:version_1");
      const resultTwo = keys.indexOf("message:m8");
      const versionTwo = keys.indexOf("output-version:version_2");
      const reviewState = {
        chatFullReviewCount: [...chat.querySelectorAll(".content-search-review")].filter((node) => !node.closest("#chatStageHost")).length,
        chatSummaryCount: [...chat.querySelectorAll(".content-search-history-summary")].filter((node) => !node.closest("#chatStageHost")).length,
        railFullReviewCount: rail.querySelectorAll(".content-search-review").length,
        chronological: resultOne >= 0 && versionOne === resultOne + 1 && resultTwo >= 0 && versionTwo === resultTwo + 1,
        reviewText: rail.textContent,
        reviewDockVisible: getComputedStyle(document.querySelector("#reviewActionDock")).display !== "none",
        reviewDockTitle: document.querySelector("#reviewActionTitle")?.textContent || "",
        reviewDockPrimary: document.querySelector("#reviewActionPrimary")?.textContent || "",
        embeddedActionHidden: getComputedStyle(rail.querySelector(".content-search-actions")).display === "none",
      };
      setTimelineExpanded(true);
      reviewState.precisionHostHidden = getComputedStyle(document.querySelector("#chatStageHost")).display === "none";
      reviewState.precisionDockVisible = getComputedStyle(document.querySelector("#reviewActionDock")).display !== "none";
      reviewState.precisionToggleLabel = document.querySelector("#timelineExpandToggle")?.textContent || "";
      reviewState.precisionDockParent = document.querySelector("#reviewActionDock")?.parentElement?.id || "";
      reviewState.precisionWorkbenchHidden = getComputedStyle(document.querySelector("#reviewWorkbench")).display === "none";
      const precisionSettingsButton = document.querySelector("#reviewActionSettings");
      precisionSettingsButton?.click();
      reviewState.precisionSettingsDrawer = {
        buttonVisible: Boolean(precisionSettingsButton && getComputedStyle(precisionSettingsButton).display !== "none"),
        drawerVisible: getComputedStyle(document.querySelector("#timelinePrecisionDrawer")).display !== "none",
        subtitleToggle: Boolean(document.querySelector("[data-precision-content-subtitle]")),
      };
      document.querySelector("#timelinePrecisionDrawerClose")?.click();
      setTimelineExpanded(false);

      const completed = { ...job, status: "completed", stage: "completed" };
      currentJob = completed;
      renderConversation(completed);
      renderReviewRail(completed);
      renderOutputs(completed);
      setDirectorStage("compose");
      setTimelineExpanded(true);
      const outputPrecision = {
        selectParent: document.querySelector("#videoViewSelect")?.parentElement?.id || "",
        optionCount: document.querySelector("#videoViewSelect")?.options.length || 0,
        meta: document.querySelector("#timelinePrecisionOutputMeta")?.textContent || "",
        toggleLabel: document.querySelector("#timelineExpandToggle")?.textContent || "",
        workbenchHidden: getComputedStyle(document.querySelector("#reviewWorkbench")).display === "none",
      };
      setTimelineExpanded(false);
      const outputSelectRestored = document.querySelector("#videoViewSelect")?.parentElement?.classList.contains("asset-actions") || false;
      return {
        ...reviewState,
        completedChatActions: chat.querySelectorAll(".completed-dialog-actions, [data-content-edit-query]").length,
        outputButtons: document.querySelectorAll("#clipStrip .clip-version-button").length,
        outputActions: document.querySelector(".clip-header-actions")?.textContent || "",
        reviewDockHiddenAfterCompose: getComputedStyle(document.querySelector("#reviewActionDock")).display === "none",
        outputPrecision,
        outputSelectRestored,
      };
    });
    assert.equal(audit.chatFullReviewCount, 0);
    assert.equal(audit.chatSummaryCount, 1);
    assert.equal(audit.railFullReviewCount, 1);
    assert.equal(audit.chronological, true);
    assert.match(audit.reviewText, /已试听保留/);
    assert.doesNotMatch(audit.reviewText, /默认不选中/);
    assert.match(audit.reviewText, /已检查全片说话人时间轴/);
    assert.equal(audit.reviewDockVisible, true);
    assert.match(audit.reviewDockTitle, /已核对 1 个片段/);
    assert.equal(audit.reviewDockPrimary, "生成所选片段");
    assert.equal(audit.embeddedActionHidden, true);
    assert.equal(audit.precisionHostHidden, true);
    assert.equal(audit.precisionDockVisible, true, JSON.stringify(audit));
    assert.equal(audit.precisionToggleLabel, "返回审核列表");
    assert.equal(audit.precisionDockParent, "timelinePrecisionContext");
    assert.equal(audit.precisionWorkbenchHidden, true);
    assert.deepEqual(audit.precisionSettingsDrawer, {
      buttonVisible: true, drawerVisible: true, subtitleToggle: true,
    });
    assert.equal(audit.completedChatActions, 0);
    assert.equal(audit.outputButtons, 2);
    assert.match(audit.outputActions, /重新选择素材.*修改查找条件/);
    assert.equal(audit.reviewDockHiddenAfterCompose, true);
    assert.equal(audit.outputPrecision.selectParent, "timelinePrecisionContext");
    assert.equal(audit.outputPrecision.optionCount, 3);
    assert.match(audit.outputPrecision.meta, /8\.0 秒/);
    assert.equal(audit.outputPrecision.toggleLabel, "返回版本列表");
    assert.equal(audit.outputPrecision.workbenchHidden, true);
    assert.equal(audit.outputSelectRestored, true);
    assert.deepEqual(pageErrors, []);
    await page.evaluate(() => {
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      document.querySelector("#uploadView")?.classList.add("hidden");
      document.querySelector("#reviewView")?.classList.remove("hidden");
      setDirectorStage("compose");
      setTimelineExpanded(true);
    });
    await page.locator("#videoViewSelect").selectOption("v001-content.mp4");
    assert.equal(await page.evaluate(() => currentOutput?.filename), "v001-content.mp4");
    assert.match(await page.locator("#timelinePrecisionOutputMeta").textContent(), /8\.0 秒/);
    await page.screenshot({ path: join(projectRoot, "test-results/single-timeline-output.png"), fullPage: true });
    await page.evaluate(() => {
      setTimelineExpanded(false);
      currentJob = {
        ...currentJob,
        workflowKind: "content_search",
        request: { ...currentJob.request, entryWorkflow: "content_search" },
        status: "awaiting_content_confirmation",
        stage: "content_confirmation",
      };
      currentOutput = null;
      viewerMediaKind = "source";
      renderConversation(currentJob);
      renderReviewRail(currentJob);
      setDirectorStage("events");
      document.querySelector("#uploadView")?.classList.add("hidden");
      document.querySelector("#reviewView")?.classList.remove("hidden");
      updateTimeline();
      setTimelineExpanded(true);
    });
    await page.screenshot({ path: join(projectRoot, "test-results/single-timeline-content.png"), fullPage: true });
    await page.evaluate(() => setTimelineExpanded(false));
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("a second content search keeps the previous result visible and reusable", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(async () => {
      const previous = {
        id: "search_water", status: "ready", createdAt: "2026-08-26T17:17:00Z",
        instruction: "找出接水的片段", candidateCount: 2, candidateDetailsLoaded: true,
        defaultSelectedIds: ["water_reliable"],
        candidates: [
          { id: "water_reliable", title: "水杯接水", start: 10, end: 14, reviewStatus: "confirmed" },
          { id: "water_possible", title: "靠近水池", start: 20, end: 23, reviewStatus: "pending", requiresReview: true },
        ],
      };
      const current = {
        id: "search_melon", status: "ready", createdAt: "2026-08-26T17:19:00Z",
        instruction: "找出切西瓜的片段", candidateCount: 1, candidateDetailsLoaded: true,
        defaultSelectedIds: ["melon_1"],
        candidates: [{ id: "melon_1", title: "切西瓜", start: 30, end: 36, reviewStatus: "confirmed" }],
        retrievalStats: {}, executionPlan: { allowedCapabilities: ["visual"] },
      };
      const job = {
        id: "", taskMode: "content_extract", status: "awaiting_content_confirmation",
        videoInfo: { duration: 60, width: 1280, height: 720, has_audio: true, frame_rate: 25 },
        request: { entryWorkflow: "content_search" }, contentSearch: current,
        contentSearchSession: { activeSearchId: current.id, state: "ready" },
        contentSearchRecords: [previous, current], contentSelectionBasket: {
          schemaVersion: "content-selection-basket-v2", entryMode: "explicit", initialized: true, items: [],
        },
      };
      const summary = new DOMParser().parseFromString(contentSearchHistorySummaryMarkup(previous), "text/html");
      const review = new DOMParser().parseFromString(contentSearchReviewMarkup(job, current), "text/html");
      currentJob = job;
      const button = document.createElement("button");
      document.body.append(button);
      await addRetainedContentSearchToBasket(previous.id, button, job);
      button.remove();
      previous.timelineCandidates = previous.candidates.map((candidate) => ({ ...candidate }));
      previous.candidates = [];
      previous.candidateDetailsLoaded = false;
      currentJob = job;
      currentOutput = null;
      viewerMediaKind = "source";
      timelinePanel.classList.remove("hidden");
      updateTimeline();
      const timelineLabels = [...document.querySelectorAll("#timelineLabels .timeline-label")];
      return {
        summaryText: summary.body.textContent,
        summaryOpenLabel: summary.querySelector("[data-content-history-open]")?.textContent || "",
        summaryAddLabel: summary.querySelector("[data-content-history-add]")?.textContent || "",
        retainedPanelText: review.querySelector(".content-retained-searches")?.textContent || "",
        retainedRows: review.querySelectorAll("[data-retained-search-id]").length,
        basketItems: job.contentSelectionBasket.items.map((item) => ({
          searchId: item.searchId, matchId: item.matchId, sourceQuery: item.sourceQuery,
        })),
        retainedTimelineLabels: timelineLabels.filter((item) => item.classList.contains("retained-search")).map((item) => item.textContent),
        currentTimelineLabels: timelineLabels.filter((item) => !item.classList.contains("retained-search")).map((item) => item.textContent),
        retainedTimelineSearchIds: timelineLabels.filter((item) => item.classList.contains("retained-search")).map((item) => item.dataset.contentSearchId),
        timelineLegend: document.querySelector("#timelinePanel > footer")?.textContent || "",
      };
    });
    assert.match(audit.summaryText, /已保留结果/);
    assert.match(audit.summaryText, /不会被后续检索覆盖/);
    assert.equal(audit.summaryOpenLabel, "查看片段");
    assert.equal(audit.summaryAddLabel, "加入成片清单");
    assert.match(audit.retainedPanelText, /之前的结果仍然可用/);
    assert.match(audit.retainedPanelText, /找出接水的片段/);
    assert.equal(audit.retainedRows, 1);
    assert.deepEqual(audit.basketItems, [{
      searchId: "search_water", matchId: "water_reliable", sourceQuery: "找出接水的片段",
    }]);
    assert.equal(audit.retainedTimelineLabels.length, 2);
    assert.match(audit.retainedTimelineLabels.join(" "), /上次 · 找出接水的片段/);
    assert.deepEqual(audit.retainedTimelineSearchIds, ["search_water", "search_water"]);
    assert.equal(audit.currentTimelineLabels.length, 1);
    assert.match(audit.currentTimelineLabels[0], /切西瓜/);
    assert.match(audit.timelineLegend, /当前检索.*已保留检索/s);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("person result drawer plays every track clip and exposes one-click composition", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.evaluate(() => {
      const people = [
        { id: "person_2", label: "人物 B", ranges: [{ start: 87.42, end: 88.58 }] },
        { id: "person_5", label: "人物 E", ranges: [{ start: 593.24, end: 596.4 }] },
        { id: "person_3", label: "人物 C", ranges: [{ start: 211.42, end: 212.08 }] },
      ];
      const candidates = people.map((person, index) => ({
        id: `person_match_${index + 1}`, title: `${person.label}出镜 · 第 1 段`,
        start: person.ranges[0].start, end: person.ranges[0].end,
        duration: person.ranges[0].end - person.ranges[0].start,
        score: 100, confidenceTier: "reliable", reviewStatus: "confirmed",
        evidenceType: "person", matchedModalities: ["person"],
        matchedPersonIds: [person.id], matchedPersonLabels: [person.label],
        selected: true, requiresReview: false,
      }));
      const search = {
        id: "search_person_drawer", status: "confirmed", instruction: "提取所选画面人物的所有出镜片段",
        resultMode: "exhaustive", coverageComplete: true, candidates,
        defaultSelectedIds: candidates.map((item) => item.id),
        completeness: { status: "complete", occurrenceCount: 3, clipCount: 3, channels: [] },
        executionPlan: { allowedCapabilities: ["person"] },
        retrievalStats: { totalMilliseconds: 20, coverageComplete: true, selectionReuse: { reused: true } },
        intent: { query: "提取所选画面人物的所有出镜片段", personTarget: { personIds: people.map((item) => item.id), matchMode: "any", activity: "appearance" } },
      };
      const job = {
        id: "job_person_drawer", taskMode: "content_extract", workflowKind: "person_edit",
        status: "awaiting_content_confirmation", stage: "content_search_ready", filename: "人物素材.mp4",
        videoInfo: { duration: 643, width: 960, height: 540, has_audio: true, frame_rate: 25 },
        request: { contentSearchPersonTarget: { personIds: people.map((item) => item.id), matchMode: "any", activity: "appearance" } },
        contentIndex: { persons: people }, contentSearch: search,
        contentSearchSession: { activeSearchId: search.id, state: "ready" }, contentSearchRecords: [search],
        messages: [{ id: "person_result", role: "assistant", kind: "content-search", contentSearchId: search.id, text: "已复用人物轨迹，整理出 3 个出镜片段。" }],
        outputs: [], outputVersions: [], candidates: [],
      };
      studio.classList.remove("home-mode");
      document.querySelector("#homeView")?.classList.add("hidden");
      setupDirectorWorkspace();
      document.querySelector("#uploadView")?.classList.add("hidden");
      document.querySelector("#reviewView")?.classList.remove("hidden");
      document.querySelector(".review-panel")?.classList.remove("hidden");
      currentJob = job;
      renderConversation(job);
      renderReviewRail(job);
      setDirectorStage("events");
      setReviewLowerPanelMode("collapsed");
      Object.defineProperty(mainVideo, "duration", { configurable: true, value: 643 });
      Object.defineProperty(mainVideo, "readyState", { configurable: true, value: 1 });
      Object.defineProperty(mainVideo, "currentTime", { configurable: true, writable: true, value: 0 });
      window.__contentPreviewPlayTimes = [];
      mainVideo.play = () => {
        window.__contentPreviewPlayTimes.push(Number(mainVideo.currentTime));
        return Promise.resolve();
      };
    });
    assert.equal(await page.locator("#reviewWorkbenchTitle").textContent(), "第 2 步 · 核对出镜片段");
    assert.equal(await page.locator("#reviewPanelSwitch").isVisible(), true);
    assert.equal(await page.locator("#reviewPanelReviewLabel").textContent(), "出镜片段");
    assert.equal(await page.locator("#reviewPanelReviewCount").textContent(), "3");
    assert.equal(await page.locator("#reviewPanelSubjectLabel").textContent(), "重新选人物");
    assert.equal(await page.locator("#reviewPanelSubjectCount").textContent(), "3");
    assert.equal(await page.locator("#reviewWorkbench").isVisible(), false);
    assert.equal(await page.locator("#timelinePanel").isVisible(), false);
    assert.ok(await page.locator("#viewerShell").evaluate((viewer) => viewer.getBoundingClientRect().height > 560));
    const playerGeometry = await page.evaluate(() => {
      const frame = document.querySelector("#mediaFrame").getBoundingClientRect();
      const controls = document.querySelector("#viewerShell > .player-controls").getBoundingClientRect();
      return {
        frameBottom: frame.bottom, controlsTop: controls.top,
        controlsPosition: getComputedStyle(document.querySelector("#viewerShell > .player-controls")).position,
        controlsBackground: getComputedStyle(document.querySelector("#viewerShell > .player-controls")).backgroundImage,
      };
    });
    assert.ok(playerGeometry.controlsTop >= playerGeometry.frameBottom - 1, JSON.stringify(playerGeometry));
    assert.equal(playerGeometry.controlsPosition, "relative");
    assert.equal(playerGeometry.controlsBackground, "none");
    await page.locator("#reviewPanelReviewTab").click();
    assert.match(await page.locator(".person-review-handoff").textContent(), /3 个出镜片段就在下方.*更换人物/s);
    assert.equal(await page.locator(".person-edit-mini-flow li").count(), 3);
    assert.match(await page.locator(".person-edit-mini-flow").textContent(), /选择人物.*核对出镜.*合成视频/s);
    assert.match(await page.locator(".person-edit-mini-flow .current").textContent(), /核对出镜/);
    assert.equal(await page.locator("#reviewActionPrimary").textContent(), "核对完成，合成视频");
    assert.equal(await page.locator("#reviewView").evaluate((view) => view.classList.contains("workbench-resizable")), true);
    const resultResizer = page.locator("#reviewWorkbenchResizer");
    const resultResizerAudit = await page.evaluate(() => ({
      handleDisplay: getComputedStyle(document.querySelector("#reviewWorkbenchResizer")).display,
      workbenchDisplay: getComputedStyle(document.querySelector("#reviewWorkbench")).display,
      reviewDisplay: getComputedStyle(document.querySelector("#reviewView")).display,
      reviewPanelDisplay: getComputedStyle(document.querySelector(".review-panel")).display,
    }));
    assert.equal(await resultResizer.isVisible(), true, JSON.stringify(resultResizerAudit));
    assert.equal(await resultResizer.getAttribute("aria-disabled"), "false");
    const resultInitialHeight = await page.locator("#reviewWorkbench").evaluate((panel) => panel.getBoundingClientRect().height);
    const resultResizerBox = await resultResizer.boundingBox();
    assert.ok(resultResizerBox, "person segment result resize handle should have a bounding box");
    await page.mouse.move(resultResizerBox.x + resultResizerBox.width / 2, resultResizerBox.y + resultResizerBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(resultResizerBox.x + resultResizerBox.width / 2, resultResizerBox.y - 55, { steps: 4 });
    await page.mouse.up();
    const resultEnlargedHeight = await page.locator("#reviewWorkbench").evaluate((panel) => panel.getBoundingClientRect().height);
    const resultResizeAudit = await page.evaluate(() => ({
      rows: getComputedStyle(document.querySelector("#reviewView")).gridTemplateRows,
      requestedHeight: document.querySelector("#reviewView").style.getPropertyValue("--review-workbench-height"),
      storedHeight: document.querySelector("#reviewView").dataset.reviewWorkbenchHeight,
      timelineExpanded: document.body.dataset.timelineExpanded,
    }));
    assert.ok(resultEnlargedHeight > resultInitialHeight + 35,
      `person segment result height did not grow: ${resultInitialHeight} -> ${resultEnlargedHeight}; ${JSON.stringify(resultResizeAudit)}`);
    await page.locator("#reviewPanelTimelineTab").click();
    assert.equal(await page.locator("#reviewWorkbench").isVisible(), false);
    assert.equal(await page.locator("#timelinePanel").isVisible(), true);
    assert.equal(await page.locator("#timelineTitle").textContent(), "人物出镜时间线");
    await page.locator("#reviewPanelTimelineTab").click();
    assert.equal(await page.locator("#reviewView").getAttribute("data-lower-panel-mode"), "collapsed");
    assert.equal(await page.locator("#timelinePanel").isVisible(), false);
    assert.equal(await page.locator("#reviewWorkbench").isVisible(), false);
    await page.locator("#reviewPanelReviewTab").click();
    await page.evaluate(() => openCandidateDrawer());
    assert.equal(await page.locator("#candidateDrawer").getAttribute("aria-hidden"), "false");
    assert.match(await page.locator("#candidateDrawerKicker").textContent(), /PERSON TRACK CLIPS/);
    assert.match(await page.locator("#candidateDrawerTitle").textContent(), /人物出镜片段（3）/);
    assert.match(await page.locator("#candidateDrawerDescription").textContent(), /人物 B、人物 E、人物 C.*连续播放.*合成一条视频/);
    assert.equal(await page.locator("[data-drawer-content-candidate]").count(), 3);
    assert.equal(await page.locator("[data-drawer-content-check]:checked").count(), 3);
    assert.match(await page.locator("[data-drawer-content-compose]").textContent(), /合成所选 3 段/);
    await page.locator("[data-drawer-content-candidate]").nth(1).locator("[data-drawer-content-preview]").click();
    await page.waitForFunction(() => window.__contentPreviewPlayTimes.length > 0);
    let preview = await page.evaluate(() => ({ currentTime: mainVideo.currentTime, previewEnd: candidatePreviewEnd, title: reviewTitle.textContent }));
    assert.equal(preview.currentTime, 593.24);
    assert.ok(Math.abs(preview.previewEnd - 596.4) < .001);
    assert.match(preview.title, /人物 E出镜/);
    assert.deepEqual(await page.evaluate(() => window.__contentPreviewPlayTimes), [593.24]);
    await page.evaluate(() => { window.__contentPreviewPlayTimes.length = 0; });
    await page.locator("[data-drawer-content-play-all]").click();
    await page.waitForFunction(() => window.__contentPreviewPlayTimes.length > 0);
    preview = await page.evaluate(() => ({ currentTime: mainVideo.currentTime, count: contentPreviewSequence?.matches?.length, position: contentPreviewSequence?.position }));
    assert.equal(preview.currentTime, 87.42);
    assert.equal(preview.count, 3);
    assert.equal(preview.position, 0);
    assert.deepEqual(await page.evaluate(() => window.__contentPreviewPlayTimes), [87.42]);
    await page.evaluate(() => {
      mainVideo.currentTime = candidatePreviewEnd;
      mainVideo.dispatchEvent(new Event("timeupdate"));
    });
    await page.waitForFunction(() => contentPreviewSequence?.position === 1 && Math.abs(mainVideo.currentTime - 593.24) < .001);
    await page.waitForFunction(() => window.__contentPreviewPlayTimes.length === 2);
    assert.deepEqual(await page.evaluate(() => window.__contentPreviewPlayTimes), [87.42, 593.24]);
    await page.screenshot({ path: join(projectRoot, "test-results/person-content-drawer.png"), fullPage: true });
    await page.locator("[data-drawer-content-compose]").click();
    await page.locator("#actionConfirm:not(.hidden)").waitFor({ state: "visible" });
    assert.match(await page.locator("#actionConfirm").textContent(), /第 3 步 · 合成人物出镜视频.*3 个已核对片段合成一条.*不会再增删片段/s);
    await page.locator("#actionConfirmCancel").click();
    const failedGeneration = await page.evaluate(() => {
      currentJob.status = "failed";
      currentJob.stage = "failed";
      currentJob.detail = "人物出镜视频生成没有完成";
      currentJob.error = "确认片段完整性校验失败";
      currentJob.currentAction = "合成已停止";
      renderConversation(currentJob);
      renderReviewRail(currentJob);
      setDirectorStage("events");
      return {
        flow: directorFlowStage(currentJob),
        railTitle: document.querySelector("#railTitle")?.textContent || "",
        railText: document.querySelector("#railBody")?.textContent || "",
        status: (renderReviewStatus(currentJob), document.querySelector("#reviewStatus")?.textContent || ""),
      };
    });
    assert.equal(failedGeneration.flow, "events");
    assert.equal(failedGeneration.railTitle, "核对人物出镜");
    assert.match(failedGeneration.railText, /上次合成没有完成.*人物选择和出镜边界均未丢失/s);
    assert.equal(failedGeneration.status, "人物剪辑生成失败");
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("evidence inspector width is draggable, keyboard adjustable, and resettable", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.evaluate(() => {
      localStorage.removeItem("cliptalk-evidence-panel-width-v1");
      studio.classList.remove("home-mode");
      setupDirectorWorkspace();
      document.querySelector("#uploadView")?.classList.add("hidden");
      document.querySelector("#reviewView")?.classList.remove("hidden");
      document.querySelector("#reviewView")?.classList.add("timeline-hidden");
      document.querySelector("#evidencePanel")?.classList.remove("hidden", "evidence-placeholder");
      document.querySelector("#evidencePanel")?.classList.add("candidate-mode");
      restoreEvidencePanelWidth();
    });
    const handle = page.locator("#reviewEvidenceResizer");
    await handle.waitFor({ state: "visible" });
    await page.waitForFunction(() => Number(document.querySelector("#reviewEvidenceResizer")?.getAttribute("aria-valuenow")) > 0);
    assert.equal(await handle.getAttribute("aria-orientation"), "vertical");
    assert.equal(await handle.getAttribute("aria-disabled"), "false");
    const panel = page.locator("#evidencePanel");
    const initialWidth = await panel.evaluate((node) => node.getBoundingClientRect().width);
    const box = await handle.boundingBox();
    assert.ok(box, "evidence panel resize handle should have a bounding box");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x - 70, box.y + box.height / 2, { steps: 4 });
    await page.mouse.up();
    const draggedWidth = await panel.evaluate((node) => node.getBoundingClientRect().width);
    const layoutAudit = await page.evaluate(() => ({
      stage: document.querySelector("#reviewStage")?.getBoundingClientRect().toJSON(),
      panel: document.querySelector("#evidencePanel")?.getBoundingClientRect().toJSON(),
      handle: document.querySelector("#reviewEvidenceResizer")?.getBoundingClientRect().toJSON(),
      panelDisplay: getComputedStyle(document.querySelector("#evidencePanel")).display,
      stageDisplay: getComputedStyle(document.querySelector("#reviewStage")).display,
      columns: getComputedStyle(document.querySelector("#reviewStage")).gridTemplateColumns,
      classes: document.querySelector("#evidencePanel")?.className,
    }));
    assert.ok(draggedWidth > initialWidth + 50, `evidence width did not grow: ${initialWidth} -> ${draggedWidth}; ${JSON.stringify(layoutAudit)}`);
    assert.ok(await page.evaluate(() => Number(JSON.parse(localStorage.getItem("cliptalk-evidence-panel-width-v1") || "null")?.width) > 0));
    await handle.focus();
    await page.keyboard.press("ArrowRight");
    const keyboardWidth = await panel.evaluate((node) => node.getBoundingClientRect().width);
    assert.ok(keyboardWidth < draggedWidth - 10, `keyboard resize did not shrink the panel: ${draggedWidth} -> ${keyboardWidth}`);
    await handle.dblclick();
    await page.waitForTimeout(50);
    const resetWidth = await panel.evaluate((node) => node.getBoundingClientRect().width);
    assert.ok(Math.abs(resetWidth - initialWidth) <= 3, `double-click did not restore default width: ${initialWidth} -> ${resetWidth}`);
    assert.equal(await page.evaluate(() => localStorage.getItem("cliptalk-evidence-panel-width-v1")), null);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("long person and speaker timelines render progressively without losing selection", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    const audit = await page.evaluate(() => {
      const personRanges = Array.from({ length: 125 }, (_, index) => ({
        id: `range_${index}`,
        start: index * 2,
        end: index * 2 + 1,
      }));
      currentJob = {
        id: "job-long-person",
        taskMode: "content_extract",
        workflowKind: "person_edit",
        request: { workflowKind: "person_edit" },
        status: "awaiting_content_confirmation",
        stage: "content_search_ready",
        contentIndex: {
          persons: [{
            id: "person_a",
            label: "人物 A",
            confidence: .95,
            ranges: personRanges,
            trackCount: 125,
          }],
        },
        contentSearch: {},
      };
      currentPersonJobId = "";
      renderCurrentPersons();
      const initialPersonRows = document.querySelectorAll("[data-current-person-range]").length;
      const firstPersonMore = document.querySelector("[data-current-person-ranges-more]");
      const firstPersonMoreText = firstPersonMore?.textContent || "";
      firstPersonMore?.click();
      const expandedPersonRows = document.querySelectorAll("[data-current-person-range]").length;

      currentVoices = [{
        speakerRef: "speaker_a",
        label: "说话人 A",
        speechSeconds: 175,
        segmentCount: 175,
      }];
      currentVoiceTimeline = Array.from({ length: 175 }, (_, index) => ({
        turnId: `turn_${index}`,
        speakerRef: "speaker_a",
        label: "说话人 A",
        start: index * 2,
        end: index * 2 + 1,
        text: `发言 ${index + 1}`,
      }));
      currentVoiceTurnLimit = currentVoiceTurnPageSize;
      renderCurrentVoiceTimeline();
      const initialVoiceRows = document.querySelectorAll("[data-voice-turn-preview]").length;
      const firstVoiceCheck = document.querySelector("[data-voice-turn-select]");
      if (firstVoiceCheck) {
        firstVoiceCheck.checked = true;
        firstVoiceCheck.dispatchEvent(new Event("change", { bubbles: true }));
      }
      document.querySelector("[data-current-voice-turn-more]")?.click();
      return {
        initialPersonRows,
        firstPersonMoreText,
        expandedPersonRows,
        initialVoiceRows,
        expandedVoiceRows: document.querySelectorAll("[data-voice-turn-preview]").length,
        voiceSelectionPreserved: Boolean(
          document.querySelector('[data-voice-turn-select][value="turn_0"]')?.checked,
        ),
      };
    });
    assert.equal(audit.initialPersonRows, 40);
    assert.match(audit.firstPersonMoreText, /再显示 40 段 · 尚有 85 段/);
    assert.equal(audit.expandedPersonRows, 80);
    assert.equal(audit.initialVoiceRows, 80);
    assert.equal(audit.expandedVoiceRows, 160);
    assert.equal(audit.voiceSelectionPreserved, true);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("settings workspace stays light, bounded, and reports unsaved changes", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.evaluate(() => window.openSettings());
    await page.waitForFunction(() => document.querySelectorAll("#visionProviderList button").length === 3);
    const audit = await page.evaluate(() => {
      const panel = document.querySelector("#settingsPanel");
      const header = panel.querySelector(":scope > header").getBoundingClientRect();
      const tabs = panel.querySelector(".model-role-tabs").getBoundingClientRect();
      const form = document.querySelector("#visionSettingsForm");
      const runtime = document.querySelector(".runtime-settings-summary");
      return {
        scrollTop: panel.scrollTop,
        headerHeight: header.height,
        tabsAfterHeader: tabs.top >= header.bottom,
        formWidth: form.getBoundingClientRect().width,
        formBackground: getComputedStyle(form).backgroundColor,
        inputBackground: getComputedStyle(document.querySelector("#visionApiKey")).backgroundColor,
        runtimeBackground: getComputedStyle(runtime).backgroundImage,
        saveDisabled: document.querySelector("#saveVisionSettings").disabled,
        dirtyLabel: document.querySelector("#visionDirtyState").textContent,
      };
    });
    assert.equal(audit.scrollTop, 0);
    assert.ok(audit.headerHeight >= 100);
    assert.equal(audit.tabsAfterHeader, true);
    assert.ok(audit.formWidth <= 1120);
    assert.equal(audit.formBackground, "rgba(255, 255, 255, 0.78)");
    assert.equal(audit.inputBackground, "rgba(255, 255, 255, 0.94)");
    assert.match(audit.runtimeBackground, /linear-gradient/);
    assert.equal(audit.saveDisabled, true);
    assert.equal(audit.dirtyLabel, "所有修改已保存");

    await page.locator("#visionApiKey").fill("temporary-unsaved-key");
    assert.deepEqual(await page.evaluate(() => ({
      dirty: document.querySelector("#visionSettingsForm").dataset.dirty,
      label: document.querySelector("#visionDirtyState").textContent,
      saveDisabled: document.querySelector("#saveVisionSettings").disabled,
      discardDisabled: document.querySelector("#discardVisionSettings").disabled,
    })), {
      dirty: "true", label: "存在未保存修改", saveDisabled: false, discardDisabled: false,
    });
    await page.locator("#discardVisionSettings").click();
    assert.deepEqual(await page.evaluate(() => ({
      dirty: document.querySelector("#visionSettingsForm").dataset.dirty,
      label: document.querySelector("#visionDirtyState").textContent,
      saveDisabled: document.querySelector("#saveVisionSettings").disabled,
      keyValue: document.querySelector("#visionApiKey").value,
    })), {
      dirty: "false", label: "所有修改已保存", saveDisabled: true, keyValue: "",
    });

    await page.locator('[data-model-role="llm"]').click();
    await page.locator("#llmUseIndependent").click();
    assert.deepEqual(await page.evaluate(() => ({
      dirty: document.querySelector("#llmSettingsForm").dataset.dirty,
      label: document.querySelector("#llmDirtyState").textContent,
      saveDisabled: document.querySelector("#saveLlmSettings").disabled,
    })), {
      dirty: "true", label: "存在未保存修改", saveDisabled: false,
    });
    await page.locator("#discardLlmSettings").click();
    assert.deepEqual(await page.evaluate(() => ({
      dirty: document.querySelector("#llmSettingsForm").dataset.dirty,
      label: document.querySelector("#llmDirtyState").textContent,
      reuseSelected: document.querySelector("#llmReuseVision").getAttribute("aria-checked"),
    })), {
      dirty: "false", label: "所有修改已保存", reuseSelected: "true",
    });

    await page.evaluate(() => { document.querySelector("#settingsPanel").scrollTop = 420; });
    await page.locator("#closeSettings").click();
    await page.evaluate(() => window.openSettings());
    assert.equal(await page.locator("#settingsPanel").evaluate((panel) => panel.scrollTop), 0);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await stub.close();
  }
});

test("visual system assigns functional fonts and removes idle chrome", async () => {
  const visualCss = await readFile(join(staticRoot, "visual-system.css"), "utf8");
  assert.match(visualCss, /font-family:\s*"VP Editorial Song"/);
  assert.match(visualCss, /font-family:\s*"VP Assistant WenKai"/);
  assert.match(visualCss, /font-family:\s*"VP Metric Display"/);
  for (const filename of [
    "vp-editorial-song.woff2",
    "vp-assistant-wenkai.woff2",
    "vp-metric-display.woff2",
  ]) {
    assert.ok((await stat(join(staticRoot, "fonts", filename))).size > 1_000);
  }

  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  try {
    await openAuthenticatedWorkspace(page, stub.url);
    await page.evaluate(async () => {
      await Promise.all([
        document.fonts.load('700 40px "VP Editorial Song"', "开始剪辑"),
        document.fonts.load('500 14px "VP Assistant WenKai"', "视频剪辑助手"),
        document.fonts.load('800 italic 20px "VP Metric Display"', "41/100"),
      ]);
    });
    const audit = await page.evaluate(() => {
      const home = document.querySelector("#homeView");
      const heading = document.querySelector(".home-heading h1");
      const assistantCopy = document.querySelector(".chat-message.assistant .bubble p");
      const metric = document.querySelector(".home-summary b");
      const createSurface = document.querySelector(".home-create-surface");
      const sidebar = document.querySelector(".app-sidebar");
      const studio = document.querySelector(".studio.home-mode");
      const root = getComputedStyle(document.documentElement);
      return {
        hasRedundantHomeButton: Boolean(document.querySelector("#homeButton")),
        bodyBackground: getComputedStyle(document.body).backgroundImage,
        homeBackground: getComputedStyle(home).backgroundColor,
        sidebarBackground: getComputedStyle(sidebar).backgroundImage,
        studioBackground: getComputedStyle(studio).backgroundImage,
        headingFamily: getComputedStyle(heading).fontFamily,
        assistantFamily: getComputedStyle(assistantCopy).fontFamily,
        metricFamily: getComputedStyle(metric).fontFamily,
        createBorderStyle: getComputedStyle(createSurface).borderTopStyle,
        accent: root.getPropertyValue("--accent").trim(),
        fontsReady: [
          document.fonts.check('700 40px "VP Editorial Song"', "开始剪辑"),
          document.fonts.check('500 14px "VP Assistant WenKai"', "视频剪辑助手"),
          document.fonts.check('800 italic 20px "VP Metric Display"', "41/100"),
        ],
      };
    });
    assert.equal(audit.hasRedundantHomeButton, false);
    assert.match(audit.bodyBackground, /linear-gradient/);
    assert.match(audit.bodyBackground, /rgb\(7, 16, 23\)/);
    assert.match(audit.bodyBackground, /rgb\(255, 255, 255\)/);
    assert.equal(audit.homeBackground, "rgba(0, 0, 0, 0)");
    assert.match(audit.sidebarBackground, /linear-gradient/);
    assert.match(audit.sidebarBackground, /rgb\(7, 16, 23\)/);
    assert.match(audit.studioBackground, /linear-gradient/);
    assert.match(audit.studioBackground, /rgb\(255, 255, 255\)/);
    assert.match(audit.headingFamily, /VP Editorial Song/);
    assert.match(audit.assistantFamily, /VP Assistant WenKai/);
    assert.match(audit.metricFamily, /VP Metric Display/);
    assert.equal(audit.createBorderStyle, "solid");
    assert.equal(audit.accent, "#a8c269");
    assert.deepEqual(audit.fontsReady, [true, true, true]);

    const workflowAudit = await page.evaluate(() => {
      const nav = document.querySelector("#directorStageNav");
      const mount = document.querySelector("#workspaceFlowMount");
      const stages = Array.from(nav.children);
      studio.classList.remove("home-mode");
      mount.append(nav);
      stages.forEach((stage, index) => {
        stage.classList.remove("complete", "current", "upcoming");
        if (index === 0) stage.classList.add("complete");
        else if (index === 1) stage.classList.add("current");
        else stage.classList.add("upcoming");
      });
      const segment = (index) => stages[index].querySelector(".stage-segment");
      const fill = (index) => segment(index).querySelector("i");
      return {
        navBackground: getComputedStyle(nav).backgroundColor,
        navBorder: getComputedStyle(nav).borderTopWidth,
        navShadow: getComputedStyle(nav).boxShadow,
        segmentHeight: getComputedStyle(segment(1)).height,
        segmentRadius: getComputedStyle(segment(1)).borderRadius,
        labelDisplay: getComputedStyle(stages[1].querySelector("strong")).display,
        completeFill: getComputedStyle(fill(0)).backgroundColor,
        currentFill: getComputedStyle(fill(1)).backgroundColor,
        upcomingFill: getComputedStyle(fill(2)).backgroundColor,
        currentSweep: getComputedStyle(segment(1), "::after").animationName,
      };
    });
    assert.equal(workflowAudit.navBackground, "rgba(0, 0, 0, 0)");
    assert.equal(workflowAudit.navBorder, "0px");
    assert.equal(workflowAudit.navShadow, "none");
    assert.equal(workflowAudit.segmentHeight, "4px");
    assert.equal(workflowAudit.segmentRadius, "999px");
    assert.equal(workflowAudit.labelDisplay, "block");
    assert.equal(workflowAudit.completeFill, "rgb(104, 131, 106)");
    assert.equal(workflowAudit.currentFill, "rgb(168, 194, 105)");
    assert.equal(workflowAudit.upcomingFill, "rgba(168, 194, 105, 0.08)");
    assert.equal(workflowAudit.currentSweep, "workflow-line-sweep");

    const mediaAudit = await page.evaluate(() => {
      document.body.dataset.shellMode = "workspace";
      document.body.dataset.shellView = "workspace";
      const shell = document.querySelector(".viewer-shell");
      const frame = document.querySelector(".viewer-shell > .media-frame");
      const video = document.querySelector("#mainVideo");
      const controls = document.querySelector(".viewer-shell > .player-controls");
      return {
        shellBackground: getComputedStyle(shell).backgroundImage,
        frameBackground: getComputedStyle(frame).backgroundImage,
        videoBackground: getComputedStyle(video).backgroundColor,
        controlsBackground: getComputedStyle(controls).backgroundColor,
        controlsColor: getComputedStyle(controls).color,
      };
    });
    assert.match(mediaAudit.shellBackground, /linear-gradient/);
    assert.match(mediaAudit.frameBackground, /linear-gradient/);
    assert.equal(mediaAudit.videoBackground, "rgba(0, 0, 0, 0)");
    assert.equal(mediaAudit.controlsBackground, "rgba(250, 251, 252, 0.94)");
    assert.equal(mediaAudit.controlsColor, "rgb(38, 49, 56)");
  } finally {
    await browser.close();
    await stub.close();
  }
});
