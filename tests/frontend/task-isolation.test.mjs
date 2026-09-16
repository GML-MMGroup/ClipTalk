import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { extname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const projectRoot = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const staticRoot = join(projectRoot, "static");
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".woff2": "font/woff2",
};

function draftJob(id, detail = "视频已就绪，等待你描述剪辑要求") {
  return {
    id,
    filename: "same-video.mp4",
    taskMode: "highlight",
    status: "awaiting_agent_instruction",
    stage: "agent_workspace_ready",
    progress: 0,
    detail,
    agentDraft: true,
    instructionSubmitted: false,
    videoInfo: { duration: 120, width: 1280, height: 720, has_audio: true, frame_rate: 25 },
    request: { entryWorkflow: "agent", workflowKind: "highlight", sourceScope: { kind: "all", start: 0, end: 120 } },
    messages: [
      { id: `${id}_msg`, role: "assistant", kind: "notice", text: detail, createdAt: "2026-09-03T00:00:00+00:00" },
    ],
    outputs: [],
    candidates: [],
    eventGroups: [],
  };
}

async function readRequestBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return Buffer.concat(chunks);
}

async function waitUntil(predicate, message, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(message);
}

async function expectCount(locator, expected, message, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await locator.count() === expected) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  assert.equal(await locator.count(), expected, message);
}

async function chooseQuickWorkflow(page, workflowKind) {
  if (!await page.locator("#quickWorkflowPicker").isVisible()) {
    await page.locator("#assistantActionDock [data-open-capability-drawer]").first().click();
  }
  await page.locator(`#quickWorkflowPicker [data-capability-category-switch='${workflowKind}']`).click();
  await page.locator(`#quickWorkflowPicker [data-workflow-switch='${workflowKind}']`).click();
}

async function startStubServer({ holdFirstJob = false, omitAgentDraftFlag = false } = {}) {
  const uploads = new Map();
  const uploadCreates = [];
  const jobPosts = [];
  const legacyActivations = [];
  const agentMessages = [];
  let uploadIndex = 0;
  let jobIndex = 0;
  let releaseFirstJob = () => {};
  const firstJobReleased = holdFirstJob
    ? new Promise((resolveRelease) => { releaseFirstJob = resolveRelease; })
    : Promise.resolve();
  const server = createServer(async (request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    if (url.pathname === "/api/health") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ uiContractVersion: 2, ok: true, visionConfigured: true, llmConfigured: true, ffmpeg: true, ffprobe: true }));
      return;
    }
    if (url.pathname === "/api/setup/status") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ complete: true, canCreateTask: true, canUseAgent: true, steps: [] }));
      return;
    }
    if (url.pathname === "/api/settings/vision" || url.pathname === "/api/settings/llm") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ providers: [], activeProvider: "", mode: "reuse_vision" }));
      return;
    }
    if (url.pathname === "/api/uploads" && request.method === "POST") {
      const body = JSON.parse((await readRequestBody(request)).toString("utf8") || "{}");
      const id = `upl_${String(++uploadIndex).padStart(32, "0")}`;
      const upload = { id, filename: body.filename || "same-video.mp4", size: Number(body.size || 0), offset: 0 };
      uploads.set(id, upload);
      uploadCreates.push(upload);
      response.statusCode = 201;
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ upload }));
      return;
    }
    if (url.pathname.startsWith("/api/uploads/")) {
      const id = url.pathname.split("/").pop();
      const upload = uploads.get(id);
      if (!upload) {
        response.statusCode = 404;
        response.setHeader("Content-Type", "application/json");
        response.end(JSON.stringify({ detail: "上传会话不存在" }));
        return;
      }
      if (request.method === "PATCH") {
        const body = await readRequestBody(request);
        upload.offset += body.length;
      }
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ upload }));
      return;
    }
    if (url.pathname === "/api/jobs") {
      response.setHeader("Content-Type", "application/json");
      if (request.method === "POST") {
        const body = (await readRequestBody(request)).toString("latin1");
        const uploadSessionId = body.match(/name="upload_session_id"\r\n\r\n([^\r\n]+)/)?.[1] || "";
        const draftSessionId = body.match(/name="draft_session_id"\r\n\r\n([^\r\n]+)/)?.[1] || "";
        const index = ++jobIndex;
        jobPosts.push({ index, uploadSessionId, draftSessionId });
        if (holdFirstJob && index === 1) await firstJobReleased;
        const job = draftJob(index === 1 ? "job_first" : "job_second", index === 1 ? "first progress" : "second progress");
        if (omitAgentDraftFlag) delete job.agentDraft;
        response.statusCode = 202;
        response.end(JSON.stringify({ job }));
        return;
      }
      response.end(JSON.stringify({ jobs: [] }));
      return;
    }
    if (url.pathname.endsWith("/activate") && request.method === "POST") {
      const id = url.pathname.split("/")[3];
      const body = JSON.parse((await readRequestBody(request)).toString("utf8") || "{}");
      legacyActivations.push({ id, body });
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ job: { ...draftJob(id, "legacy activated"), agentDraft: false, instructionSubmitted: true, status: "queued" } }));
      return;
    }
    if (url.pathname === "/api/agent/workspaces" && request.method === "POST") {
      const body = JSON.parse((await readRequestBody(request)).toString("utf8") || "{}");
      response.statusCode = 201;
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ workspace: { id: `ws_${body.jobId || "unknown"}`, jobId: body.jobId || "" } }));
      return;
    }
    if (url.pathname === "/api/agent/skills" && request.method === "GET") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ skills: [
        { id: "cliptalk-cover-director", name: "cliptalk-cover-director", status: "enabled" },
        { id: "cliptalk-local-motion-renderer", name: "cliptalk-local-motion-renderer", status: "enabled" },
        { id: "cliptalk-shortform-hook-director", name: "cliptalk-shortform-hook-director", status: "enabled" },
      ] }));
      return;
    }
    if (url.pathname.includes("/api/agent/workspaces/") && url.pathname.endsWith("/messages/stream") && request.method === "POST") {
      const id = url.pathname.split("/")[4];
      const body = JSON.parse((await readRequestBody(request)).toString("utf8") || "{}");
      agentMessages.push({ id, body });
      response.setHeader("Content-Type", "text/event-stream; charset=utf-8");
      response.end("event: error\ndata: {\"message\":\"stubbed agent stream\"}\n\n");
      return;
    }
    if (url.pathname.startsWith("/api/jobs/")) {
      const id = url.pathname.split("/")[3];
      response.setHeader("Content-Type", "application/json");
      const job = draftJob(id);
      if (omitAgentDraftFlag) delete job.agentDraft;
      response.end(JSON.stringify({ job, ready: false, preparing: false }));
      return;
    }
    if (url.pathname.startsWith("/api/")) {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({}));
      return;
    }
    const filePath = join(staticRoot, url.pathname === "/" ? "index.html" : url.pathname.replace(/^\/static\//, ""));
    try {
      const body = await readFile(filePath);
      response.setHeader("Content-Type", contentTypes[extname(filePath)] || "application/octet-stream");
      response.end(body);
    } catch {
      response.statusCode = 404;
      response.end("not found");
    }
  });
  await new Promise((resolveListen) => server.listen(0, "127.0.0.1", resolveListen));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    uploadCreates,
    jobPosts,
    legacyActivations,
    agentMessages,
    releaseFirstJob,
    close: () => new Promise((resolveClose) => server.close(resolveClose)),
  };
}

async function withPage(callback, options = {}) {
  const stub = await startStubServer(options);
  const temp = await mkdtemp(join(tmpdir(), "cliptalk-task-isolation-"));
  const video = join(temp, "same-video.mp4");
  await writeFile(video, Buffer.alloc(17 * 1024 * 1024));
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.addInitScript(() => sessionStorage.setItem("cliptalk_access_token", "browser-test-token"));
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("[data-home-create]").first().click();
    await callback({ page, stub, video, errors });
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await stub.close();
    await rm(temp, { recursive: true, force: true });
  }
}

test("same source file creates a new task with a fresh upload session", async () => {
  await withPage(async ({ page, stub, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");
    await page.evaluate(() => window.openNewTaskFromHome?.());
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_second");
    assert.equal(stub.jobPosts.length, 2);
    assert.equal(stub.uploadCreates.length, 2);
    assert.notEqual(stub.jobPosts[0].uploadSessionId, stub.jobPosts[1].uploadSessionId);
    assert.notEqual(stub.jobPosts[0].draftSessionId, stub.jobPosts[1].draftSessionId);
    assert.equal(await page.locator("#chatMessages").textContent().then((text) => text.includes("first progress")), false);
    assert.equal(await page.locator("#chatMessages").textContent().then((text) => text.includes("second progress")), true);
  });
});

test("new task clears stale Agent plan UI from the previous task", async () => {
  await withPage(async ({ page, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");
    await page.evaluate(() => {
      const dock = document.querySelector("#agentPlanDock");
      dock.classList.remove("hidden");
      dock.dataset.status = "preview_ready";
      dock.dataset.tone = "complete";
      dock.innerHTML = "<header><small>短视频剪辑计划</small><b>样片待修正</b></header><footer><span>12/12 步</span><button>打开时间线</button></footer>";
      document.querySelector(".chat-panel")?.classList.add("agent-plan-active");
      const drawer = document.querySelector("#agentPlanDrawer");
      drawer.classList.remove("hidden");
      drawer.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
      document.querySelector("#agentPlanDrawerPlan").innerHTML = "<p>旧任务计划详情</p>";
      document.querySelector("#agentPlanDrawerScrim")?.classList.remove("hidden");
      const context = document.querySelector("#chatContextBar");
      context.classList.remove("hidden");
      context.innerHTML = "<small>本次会附带</small><button>当前检索已选 3 段</button>";
      const basket = document.querySelector("#contentSelectionBasket");
      basket.classList.remove("hidden");
      basket.innerHTML = "<strong>旧任务成片清单</strong>";
    });

    await page.evaluate(() => window.openNewTaskFromHome?.());

    const resetState = await page.evaluate(() => {
      const dock = document.querySelector("#agentPlanDock");
      const drawer = document.querySelector("#agentPlanDrawer");
      return {
        currentJobId: window.ClipTalkCurrentJobId?.() || "",
        dockHidden: dock.classList.contains("hidden"),
        dockText: dock.textContent.trim(),
        planActive: document.querySelector(".chat-panel")?.classList.contains("agent-plan-active"),
        drawerHidden: drawer.classList.contains("hidden"),
        drawerOpen: drawer.classList.contains("open"),
        drawerAria: drawer.getAttribute("aria-hidden"),
        drawerText: document.querySelector("#agentPlanDrawerPlan")?.textContent.trim(),
        scrimHidden: document.querySelector("#agentPlanDrawerScrim")?.classList.contains("hidden"),
        chatText: String(document.querySelector("#chatMessages")?.textContent || "").replace(/\s+/g, ""),
        contextHidden: document.querySelector("#chatContextBar")?.classList.contains("hidden"),
        contextText: document.querySelector("#chatContextBar")?.textContent.trim(),
        basketHidden: document.querySelector("#contentSelectionBasket")?.classList.contains("hidden"),
        basketText: document.querySelector("#contentSelectionBasket")?.textContent.trim(),
      };
    });
    assert.deepEqual(resetState, {
      currentJobId: "",
      dockHidden: true,
      dockText: "",
      planActive: false,
      drawerHidden: true,
      drawerOpen: false,
      drawerAria: "true",
      drawerText: "",
      scrimHidden: true,
      chatText: "AIAI先添加视频，再告诉我你想怎么剪。试试保留完整发言提取高光按描述找片段",
      contextHidden: true,
      contextText: "",
      basketHidden: true,
      basketText: "",
    });
  });
});

test("a requirement committed before upload continues into Agent planning after the source is ready", async () => {
  await withPage(async ({ page, stub, video }) => {
    assert.equal(await page.locator("#ctV4ProjectName").textContent(), "新任务");
    assert.match(await page.locator("#chatMessages").textContent(), /先添加视频.*想怎么剪.*保留完整发言/s);

    await page.locator("#chatInput").fill("找出所有汽车画面，剪成 9:16 审核样片并添加字幕");
    await page.keyboard.press("Enter");

    assert.match(await page.locator("#chatMessages").textContent(), /要求已暂存.*选择视频后.*自动开始整理剪辑计划/s);
    assert.equal(await page.locator("#newTaskDraftStatus").textContent(), "剪辑要求已暂存 · 选择视频后自动继续");
    assert.equal(await page.locator("#newTaskDraftStatus").getAttribute("data-state"), "ready");

    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");
    await waitUntil(() => stub.agentMessages.length === 1, "committed draft was not submitted to the Agent after upload");
    assert.equal(stub.agentMessages[0].body.text, "找出所有汽车画面，剪成 9:16 审核样片并添加字幕");
  });
});

test("late upload response from an older creation session cannot replace the newer task", async () => {
  await withPage(async ({ page, stub, video }) => {
    await page.setInputFiles("#videoInput", video);
    await waitUntil(() => stub.jobPosts.length === 1, "first job creation request was not sent");
    await page.locator("#sidebarNewTask").click();
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_second");
    stub.releaseFirstJob();
    await page.waitForTimeout(200);
    assert.equal(await page.evaluate(() => window.ClipTalkCurrentJobId?.()), "job_second");
    assert.equal(stub.jobPosts.length, 2);
    assert.notEqual(stub.jobPosts[0].uploadSessionId, stub.jobPosts[1].uploadSessionId);
  }, { holdFirstJob: true });
});

test("agent draft keeps automatic routing compact and opens grouped capabilities in a drawer", async () => {
  await withPage(async ({ page, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");

    const agentControl = await page.locator("#agentSkillMenuButton").evaluate((button) => ({
      visible: getComputedStyle(button).display !== "none",
      height: button.getBoundingClientRect().height,
      insideComposer: Boolean(button.closest(".chat-input-shell")),
    }));
    assert.equal(agentControl.visible, true);
    assert.ok(agentControl.height >= 28, `Agent/Skill control is too small: ${agentControl.height}px`);
    assert.equal(agentControl.insideComposer, true);

	    assert.equal(await page.locator("#chatLegacyModeButton").isVisible(), false,
	      "the retired quick workflow trigger should stay hidden");
	    assert.equal(await page.locator("#chatMessages [data-workflow-switch]").count(), 0,
	      "the conversation should not duplicate quick workflow choices");
    assert.equal(await page.locator("#quickWorkflowPicker").isVisible(), false);
    assert.match(await page.locator("#assistantActionDock").textContent(), /自动选择/);
    assert.match(await page.locator("#assistantActionDock").textContent(), /执行前说明采用的能力/);
    const capabilityTrigger = page.locator("#assistantActionDock [data-open-capability-drawer]").first();
    await capabilityTrigger.click();
    assert.equal(await page.locator("#ctV4AssistantQuickStart").getAttribute("aria-hidden"), "false");
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#ctV4AssistantQuickStart").getAttribute("aria-hidden"), "true");
    assert.equal(await capabilityTrigger.evaluate((node) => document.activeElement === node), true);
    await capabilityTrigger.click();
    const choices = page.locator("#quickWorkflowPicker [data-capability-category-switch]");
    await expectCount(choices, 9, "a restored upload draft should show automatic routing and eight capability categories");
    assert.equal(await page.locator("#quickWorkflowPicker").isVisible(), true);
    assert.deepEqual((await choices.evaluateAll((buttons) => buttons.map((button) => ({
      key: button.dataset.capabilityCategorySwitch,
      label: button.querySelector("strong")?.textContent?.trim(),
    })))).slice(0, 5), [
      { key: "auto", label: "自动选择" },
      { key: "highlight", label: "智能高光" },
      { key: "content_search", label: "内容检索" },
      { key: "person_edit", label: "人物聚焦" },
      { key: "speaker_edit", label: "发言剪辑" },
    ]);
    await page.locator("#capabilityDrawerClose").click();
    const suggestion = page.locator("#composerSuggestion");
    await expectCount(suggestion, 1, "the composer should expose one video-aware suggestion in draft mode");
    await page.waitForFunction(() => /^试试：“.+”$/.test(document.querySelector("#composerSuggestion")?.textContent || ""));
    assert.match(await suggestion.textContent(), /试试：“.+”/);
    await suggestion.click();
    assert.match(await page.locator("#chatInput").inputValue(), /可审核短片|高光片段|整理每个人/);
    await expectCount(page.locator("#composerSuggestion:not(.hidden)"), 0, "suggestion should hide after it fills the input");
    await page.locator("#chatInput").fill("");
    await expectCount(page.locator("#composerSuggestion:not(.hidden)"), 1, "suggestion should return when the draft input is empty");
    await chooseQuickWorkflow(page, "content_search");
    await page.waitForFunction(() => document.querySelector("#quickWorkflowPicker")?.textContent?.includes("已选择"));
    assert.equal(await page.locator("#ctV4AssistantQuickStart").getAttribute("aria-hidden"), "false");
    assert.match(await page.locator("#chatMessages").evaluate((node) => getComputedStyle(node).overflowY), /hidden/);
    assert.match(await page.locator("#quickWorkflowPicker").evaluate((node) => getComputedStyle(node).overflowY), /auto/);
    assert.match(await page.locator("#quickWorkflowPicker").textContent(), /内容检索/);
    assert.match(await page.locator("#quickWorkflowPicker").textContent(), /检索内容/);
    assert.equal(await page.locator("#quickWorkflowPicker [data-workflow-launch-instruction]").count(), 1);
    assert.match(await page.locator("#quickWorkflowPicker [data-workflow-launch-instruction]").inputValue(), /核心主题|汽车画面/);
    assert.match(String(await page.locator("#chatInput").getAttribute("placeholder") || ""), /所有汽车画面/);
    assert.equal(await page.locator("#quickWorkflowPicker:not(.hidden)").count(), 1);
  });
});

test("new-task empty state keeps capability routing out of the first step", async () => {
  await withPage(async ({ page, video }) => {
    assert.equal(await page.locator("#quickWorkflowPicker").isVisible(), false);
    assert.equal(await page.locator("#assistantActionDock").isVisible(), false);
    await page.locator('[data-empty-prompt="按描述找片段"]').click();
    assert.equal(await page.locator("#chatInput").inputValue(), "按描述找片段");

    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");
    assert.equal(await page.locator("#assistantActionDock").isVisible(), true);
    assert.match(await page.locator("#assistantActionDock").textContent(), /自动选择/);
    await page.locator("#assistantActionDock [data-open-capability-drawer]").first().click();
    assert.equal(await page.locator("#quickWorkflowPicker [data-capability-category-switch]").count(), 9);
  });
});

test("light theme keeps the Skill advanced menu readable", async () => {
  await withPage(async ({ page, video }) => {
    await page.evaluate(() => {
      document.documentElement.dataset.theme = "light";
      localStorage.setItem("cliptalk_theme", "light");
    });
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");
    await page.locator("#agentSkillMenuButton").click();
    await page.locator("#agentSkillMenu").waitFor({ state: "visible" });

    const audit = await page.evaluate(() => {
      const rgb = (value) => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
      const luminance = (value) => {
        const channels = rgb(value).map((channel) => channel / 255)
          .map((channel) => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
        return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
      };
      const contrast = (foreground, background) => {
        const a = luminance(foreground), b = luminance(background);
        return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      };
      const stylePair = (element) => {
        const style = getComputedStyle(element);
        return { foreground: style.color, background: style.backgroundColor,
          luminance: luminance(style.backgroundColor), contrast: contrast(style.color, style.backgroundColor),
          fontFamily: style.fontFamily, fontSize: Number.parseFloat(style.fontSize), fontWeight: Number(style.fontWeight) };
      };
      return {
        menu: stylePair(document.querySelector("#agentSkillMenu")),
        menuSelect: stylePair(document.querySelector("#agentSkillSelect")),
        manageButton: stylePair(document.querySelector("#agentRegistryButton")),
        assistantFont: getComputedStyle(document.querySelector(".chat-message.assistant .bubble p")).fontFamily,
        notoLoaded: document.fonts.check('12px "Noto Sans SC"'),
      };
    });

    for (const [name, surface] of Object.entries(audit).filter(([, value]) => typeof value === "object")) {
      assert.ok(surface.luminance > .72, `${name} remains a dark-theme surface: ${JSON.stringify(surface)}`);
      assert.ok(surface.contrast >= 4.5, `${name} lacks readable light-theme contrast: ${JSON.stringify(surface)}`);
      assert.match(surface.fontFamily, /Noto Sans SC/, `${name} does not use the local Chinese UI font`);
      assert.ok(surface.fontSize >= 11, `${name} type is too small: ${surface.fontSize}px`);
    }
    assert.match(audit.assistantFont, /Noto Sans SC/);
    assert.doesNotMatch(audit.assistantFont, /WenKai/);
    assert.equal(audit.notoLoaded, true);
  });
});

test("awaiting instruction jobs expose composer suggestions even without an agentDraft flag", async () => {
  await withPage(async ({ page, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");
    await page.waitForFunction(() => /^试试：“.+”$/.test(document.querySelector("#composerSuggestion")?.textContent || ""));
    assert.equal(await page.locator("#quickWorkflowPicker").isVisible(), false);
    assert.match(await page.locator("#composerSuggestion").textContent(), /试试：“.+”/);
    assert.match(String(await page.locator("#chatInput").getAttribute("placeholder") || ""), /描述你想怎么剪/);
  }, { omitAgentDraftFlag: true });
});

test("agent draft input submits to the default Agent when no quick workflow is selected", async () => {
  await withPage(async ({ page, stub, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");
    assert.match(String(await page.locator("#chatInput").getAttribute("placeholder") || ""), /描述你想怎么剪/);

    await page.locator("#chatInput").fill("帮我找出所有汽车画面并合成竖屏视频");
    await page.keyboard.press("Enter");

    await waitUntil(() => stub.agentMessages.length === 1, "default Agent input was not submitted");
    assert.equal(stub.agentMessages[0].id, "ws_job_first");
    assert.equal(stub.agentMessages[0].body.text, "帮我找出所有汽车画面并合成竖屏视频");
    assert.equal(stub.legacyActivations.length, 0);
  });
});

test("grouped capability selection sets a Skill and automatic mode clears it", async () => {
  await withPage(async ({ page, stub, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");

    await page.locator("#assistantActionDock [data-open-capability-drawer]").first().click();
    await page.locator('#quickWorkflowPicker [data-capability-category-switch="package"]').click();
    await page.locator('#quickWorkflowPicker [data-draft-capability-skill="cliptalk-cover-director"]').click();
    await page.waitForFunction(() => document.querySelector("#agentSkillSelect")?.value === "cliptalk-cover-director");
    assert.equal(await page.locator("#agentSkillSelect").inputValue(), "cliptalk-cover-director");
    assert.equal(await page.locator("#quickWorkflowPicker").isVisible(), false);
    assert.match(await page.locator("#assistantActionDock").textContent(), /视觉包装.*生成视频封面.*生成封面方案/s);
    assert.match(await page.locator("#directorTaskSummary").textContent(), /已选择生成视频封面.*补充要求后生成方案/s);
    await page.waitForFunction(() => document.querySelector("#ctTaskJourney")?.textContent?.includes("设置封面"));
    assert.match(await page.locator("#ctTaskJourney").textContent(), /1 \/ 3.*设置封面/s);
    assert.equal(await page.locator("#ctV4MaterialsSummary").evaluate((node) => node.classList.contains("cover-draft")), true);
    assert.equal((await page.locator(".ct-v4-version-card > header > span").textContent()).trim(), "2");
    assert.match(await page.locator(".ct-v4-version-card").textContent(), /封面结果.*等待封面方案.*生成后可选择并保存为当前封面/s);
    assert.equal(await page.locator(".ct-v4-version-card > footer").isVisible(), false);

    await page.locator("#assistantActionDock [data-change-draft-capability]").click();
    await page.locator('#quickWorkflowPicker [data-capability-category-switch="auto"]').click();
    assert.equal(await page.locator("#agentSkillSelect").inputValue(), "");
    assert.equal(await page.locator("#quickWorkflowPicker").isVisible(), false);
    assert.match(await page.locator("#assistantActionDock").textContent(), /自动选择/);
    assert.match(await page.locator("#assistantActionDock").textContent(), /执行前说明采用的能力/);

    await page.locator("#chatInput").fill("");
    await page.locator("#assistantActionDock [data-open-capability-drawer]").first().click();
    await page.locator('#quickWorkflowPicker [data-capability-category-switch="package"]').click();
    await page.locator('#quickWorkflowPicker [data-draft-capability-skill="cliptalk-local-motion-renderer"]').click();
    await page.waitForFunction(() => document.querySelector("#chatInput")?.value.includes("动态图文片头"));
    assert.equal(await page.locator("#chatInput").inputValue(), "为当前视频制作一段简洁的动态图文片头，突出核心主题，并保持与原视频风格一致。");
    assert.match(await page.locator("#assistantActionDock").textContent(), /视觉包装.*制作动态图文.*生成标题卡、动画片头或说明画面/s);

    await page.evaluate(() => { document.documentElement.dataset.theme = "light"; });
    const actionCopy = page.locator("#assistantActionDock .assistant-action-copy");
    await actionCopy.hover();
    const hoverColours = await actionCopy.evaluate((node) => ({
      title: getComputedStyle(node.querySelector("strong")).color,
      detail: getComputedStyle(node.querySelector("span")).color,
      background: getComputedStyle(node).backgroundColor,
    }));
    assert.equal(hoverColours.title, "rgb(24, 49, 38)");
    assert.equal(hoverColours.detail, "rgb(82, 106, 94)");
    assert.equal(hoverColours.background, "rgba(0, 0, 0, 0)");

    await page.locator("#assistantActionDock .assistant-action-primary").click();
    await waitUntil(() => stub.agentMessages.length === 1, "selected motion capability was not submitted");
    assert.equal(stub.agentMessages[0].body.skillId, "cliptalk-local-motion-renderer");
    assert.match(stub.agentMessages[0].body.text, /制作一段简洁的动态图文片头/);

  });
});

test("capability recommendation preserves an existing instruction and can be appended", async () => {
  await withPage(async ({ page, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");
    await page.locator("#chatInput").fill("保留品牌绿色");
    await page.locator("#assistantActionDock [data-open-capability-drawer]").first().click();
    await page.locator('#quickWorkflowPicker [data-capability-category-switch="package"]').click();
    await page.locator('#quickWorkflowPicker [data-draft-capability-skill="cliptalk-local-motion-renderer"]').click();
    await page.waitForFunction(() => document.querySelector("#composerSuggestion")?.textContent.includes("添加建议"));
    assert.equal(await page.locator("#chatInput").inputValue(), "保留品牌绿色");
    assert.match(await page.locator("#composerSuggestion").textContent(), /添加建议.*动态图文片头/);
    await page.locator("#composerSuggestion").click();
    assert.match(await page.locator("#chatInput").inputValue(), /保留品牌绿色\n为当前视频制作一段简洁的动态图文片头/);
  });
});

test("highlight quick workflow starts after target duration is configured", async () => {
  await withPage(async ({ page, stub, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");

    await chooseQuickWorkflow(page, "highlight");
	    await page.waitForFunction(() => document.querySelector("#quickWorkflowPicker")?.textContent?.includes("开始智能高光"));
	    await page.locator("#quickWorkflowPicker [data-workflow-target-seconds]").fill("30");
	    await page.locator("#quickWorkflowPicker [data-workflow-variant-count]").selectOption("2");
	    await page.locator("#quickWorkflowPicker [data-start-workflow-switch]").click();

    await waitUntil(() => stub.legacyActivations.length === 1, "highlight quick workflow was not started");
    assert.equal(stub.legacyActivations[0].id, "job_first");
    assert.equal(stub.legacyActivations[0].body.workflowKind, "highlight");
    assert.equal(stub.legacyActivations[0].body.targetSeconds, 30);
    assert.equal(stub.legacyActivations[0].body.variantCount, 2);
  });
});

const quickWorkflowStartCases = [
  {
    workflowKind: "content_search",
    launchText: "开始内容检索",
    instruction: "查找所有汽车画面",
    expectedInstruction: "查找所有汽车画面",
  },
  {
    workflowKind: "person_edit",
    launchText: "开始人物聚焦",
    expectedInstruction: "识别视频中的主要人物，整理每个人的代表画面，让我核对后选择需要保留的人物。",
  },
  {
    workflowKind: "speaker_edit",
    launchText: "开始发言剪辑",
    expectedInstruction: "识别视频中的说话人，整理每个人的代表发言，让我试听后选择需要保留的声音。",
    expectedSpeakerCount: 2,
  },
];

for (const quickCase of quickWorkflowStartCases) {
  test(`${quickCase.workflowKind} quick workflow starts from its launch card`, async () => {
    await withPage(async ({ page, stub, video }) => {
      await page.setInputFiles("#videoInput", video);
      await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");

      await chooseQuickWorkflow(page, quickCase.workflowKind);
      await page.waitForFunction((text) => document.querySelector("#quickWorkflowPicker")?.textContent?.includes(text), quickCase.launchText);
      if (quickCase.instruction) await page.locator("#chatInput").fill(quickCase.instruction);
      if (quickCase.expectedSpeakerCount) await page.locator("#quickWorkflowPicker [data-workflow-speaker-count]").fill(String(quickCase.expectedSpeakerCount));
      await page.locator("#quickWorkflowPicker [data-start-workflow-switch]").click();

      await waitUntil(() => stub.legacyActivations.length === 1, `${quickCase.workflowKind} quick workflow was not started`);
      assert.equal(stub.legacyActivations[0].id, "job_first");
      assert.equal(stub.legacyActivations[0].body.workflowKind, quickCase.workflowKind);
      assert.equal(stub.legacyActivations[0].body.instruction, quickCase.expectedInstruction);
      if (quickCase.expectedSpeakerCount) {
        assert.equal(stub.legacyActivations[0].body.expectedSpeakerCount, quickCase.expectedSpeakerCount);
      }
    });
  });
}

test("content search quick workflow requires a search instruction before starting", async () => {
  await withPage(async ({ page, stub, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");

    await chooseQuickWorkflow(page, "content_search");
    await page.locator("#chatInput").fill("");
    await page.locator("#quickWorkflowPicker [data-start-workflow-switch]").click();

    await page.waitForFunction(() => document.querySelector("#quickWorkflowPicker [role='alert']")?.textContent === "请先在输入框描述要查找的内容。");
    assert.equal(stub.legacyActivations.length, 0);
    assert.equal(stub.agentMessages.length, 0);

    await page.locator("#chatInput").fill("查找所有冰箱画面");
    await expectCount(page.locator("#quickWorkflowPicker [role='alert']"), 0, "content search validation did not clear");
  });
});

test("content search quick workflow starts from Enter after a mode is selected", async () => {
  await withPage(async ({ page, stub, video }) => {
    await page.setInputFiles("#videoInput", video);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === "job_first");

    await chooseQuickWorkflow(page, "content_search");
    await page.locator("#chatInput").fill("查找所有汽车画面");
    await page.keyboard.press("Enter");

    await waitUntil(() => stub.legacyActivations.length === 1, "content search quick workflow was not started from Enter");
    assert.equal(stub.legacyActivations[0].body.workflowKind, "content_search");
    assert.equal(stub.legacyActivations[0].body.instruction, "查找所有汽车画面");
    assert.equal(stub.agentMessages.length, 0);
  });
});
