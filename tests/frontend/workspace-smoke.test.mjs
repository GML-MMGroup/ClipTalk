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
    if (url.pathname === "/api/jobs") {
      const token = String(request.headers["x-highlight-token"] || "");
      requests.push({ path: url.pathname, token });
      response.setHeader("Content-Type", "application/json");
      if (token !== "browser-test-token") {
        response.statusCode = 401;
        response.end(JSON.stringify({ detail: "访问令牌无效" }));
        return;
      }
      response.setHeader("Set-Cookie", "highlight_session=test-session; Path=/; HttpOnly; SameSite=Strict");
      response.end(JSON.stringify({ jobs: [] }));
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


test("workspace loads, authenticates without URL token, and opens new-task flow", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("dialog", async (dialog) => {
    assert.match(dialog.message(), /访问令牌/);
    await dialog.accept("browser-test-token");
  });
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#homeTaskGrid .home-empty").waitFor({ state: "visible" });
    assert.equal(await page.title(), "ClipTalk");
    assert.ok(stub.requests.some((item) => item.token === ""));
    assert.ok(stub.requests.some((item) => item.token === "browser-test-token"));
    assert.equal(
      await page.evaluate(() => sessionStorage.getItem("cliptalk_access_token")),
      "browser-test-token",
    );
    await page.locator("[data-home-create]").click();
    await page.locator("#uploadView").waitFor({ state: "visible" });
    await page.locator("#uploadForm").waitFor({ state: "visible" });
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
    await page.locator('[data-task-mode="content_extract"]').click();
    assert.match(await page.locator('[data-storage-mode="editable"]').getAttribute("class"), /active/);
    await page.locator('[data-storage-mode="one_off"]').click();
    assert.match(await page.locator('[data-storage-mode="one_off"]').getAttribute("class"), /active/);
    assert.match(await page.locator(".content-material-overview").textContent(), /严格按需.*只运行本次查找需要的能力/);
    await page.locator("#briefContentInstruction").fill("找出后半段的产品演示");
    assert.match(await page.locator("#contentEvidencePlan").textContent(), /系统自动判断.*根据描述组合必要的音画证据/);
    assert.equal(await page.locator("#contentEvidenceQuestion").count(), 0);
    assert.match(await page.locator('[data-content-limit="12"]').getAttribute("class"), /active/);
    assert.match(await page.locator("#contentQueryPreview").textContent(), /全部可靠结果/);
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
    await page.locator('[data-content-scope="back_half"]').click();
    await page.locator('[data-content-limit="1"]').click();
    await page.locator('[data-content-boundary="context"]').click();
    assert.equal(await page.locator('[data-content-scope="back_half"]').getAttribute("class"), "active");
    assert.match(await page.locator("#contentQueryPreview").textContent(), /产品演示/);
    assert.match(await page.locator("#contentQueryPreview").textContent(), /最多 1 段/);
    assert.match(await page.locator("#contentQueryPreview").textContent(), /前后 2 秒/);
    assert.ok(await page.locator(".content-search-conditions").isVisible());
    assert.equal(await page.evaluate(() => activeContentEvidencePlan()), null);
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
  page.on("dialog", async (dialog) => dialog.accept("browser-test-token"));
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#homeTaskGrid .home-empty").waitFor({ state: "visible" });
    const audit = await page.evaluate(async () => {
      const host = document.createElement("section");
      host.className = "chat-messages";
      host.style.cssText = "position:fixed;inset:12px auto auto 12px;width:300px;height:820px;z-index:500;background:#071018;overflow:auto";
      const reviewJob = {
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
          retrievalStats: { localRecallCount: 111, totalMilliseconds: 531 },
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
      host.innerHTML = contentSearchReviewMarkup(reviewJob);
      wireContentBoundaryEditors(host.querySelector(".content-search-review"), reviewJob);
      document.body.append(host);
      syncContentSearchOutputControls(host);
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
      const recovery = host.querySelector(".content-search-recovery");
      const boundaryButton = host.querySelector('[data-content-boundary-open="match_1"]');
      boundaryButton.click();
      const boundaryEditor = host.querySelector('[data-content-boundary-editor="match_1"]');
      const originalBoundaryEnd = Number(boundaryEditor.dataset.boundaryEnd);
      boundaryEditor.querySelector('[data-boundary-adjust="end:frame"]').click();
      const adjustedBoundaryEnd = Number(boundaryEditor.dataset.boundaryEnd);
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
      };
      const noDialogueSubtitleState = {
        disabled: subtitleInput.disabled,
        checked: subtitleInput.checked,
        message: subtitleStatus.textContent,
      };
      reviewJob.speechAnalysis.segments = [{ start: 76.4, end: 77.5, text: "把物品放进收纳盒。" }];
      syncContentSearchSubtitleControls(host, reviewJob);
      const dialogueSubtitleState = {
        disabled: subtitleInput.disabled,
        message: subtitleStatus.textContent,
      };
      orderSelect.value = "llm_recommend";
      syncContentSearchOutputControls(host);
      const llmHint = host.querySelector("[data-content-order-hint]").textContent;
      outputSelect.value = "separate_events";
      syncContentSearchOutputControls(host);
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
        confirmButtonWidth: confirmContentButton.getBoundingClientRect().width,
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
        possibleInitiallyHidden: tieredDocument.querySelector(".content-candidate-possible")?.classList.contains("hidden"),
        tieredReviewText: tieredDocument.body.textContent,
        mergeAddButtonText: host.querySelector("[data-content-basket-add]")?.textContent || "",
        decoupledCheckedIds,
        legacyBasketCount,
        basketAudit,
        boundaryButtonText: boundaryButton.textContent,
        legacyBoundaryButtonCount: host.querySelectorAll('[data-content-feedback="boundary_incorrect"]').length,
        boundaryEditorVisible: !boundaryEditor.classList.contains("hidden"),
        boundaryFrameText: boundaryEditor.querySelector("[data-boundary-frame-rate]").textContent,
        boundaryFrameDelta: adjustedBoundaryEnd - originalBoundaryEnd,
        boundaryHasManualActions: ["预览调整结果", "自动重新识别", "取消", "保存边界"].every((label) => boundaryEditor.textContent.includes(label)),
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
    assert.ok(Math.abs(audit.confirmButtonWidth - audit.actionWidth) < 1);
    assert.deepEqual(audit.noDialogueSubtitleState, {
      disabled: true,
      checked: false,
      message: "所选片段没有可转写对白，无需添加字幕。",
    });
    assert.equal(audit.dialogueSubtitleState.disabled, false);
    assert.match(audit.dialogueSubtitleState.message, /检测到 1 段可转写对白/);
    assert.equal(audit.personCardLabel, "女嘉宾");
    assert.match(audit.personSpeakerText, /Speaker 2.*93%/);
    assert.equal(audit.personLabelButton, "person_1");
    assert.match(audit.recoveryText, /还没找到想要的画面.*加密补检可能遗漏的画面/);
    assert.equal(audit.recoveryOpen, false);
    assert.equal(audit.recoveryAfterActions, true);
    assert.equal(audit.completeRecoveryCount, 0);
    assert.match(audit.possibleToggleText, /可能相关.*1 个内容段/);
    assert.equal(audit.possibleInitiallyHidden, false);
    assert.match(audit.tieredReviewText, /当前覆盖 37\.5%/);
    assert.equal(audit.tieredReviewText.includes("匹配分"), false);
    assert.equal(audit.tieredReviewText.includes("项需复核"), false);
    assert.match(audit.mergeAddButtonText, /加入合并生成/);
    assert.deepEqual(audit.decoupledCheckedIds, ["match_1"]);
    assert.equal(audit.legacyBasketCount, 0);
    assert.equal(audit.basketAudit.hidden, false);
    assert.match(audit.basketAudit.summary, /待合并片段.*1 段.*查看明细/s);
    assert.equal(audit.basketAudit.itemCount, 1);
    assert.match(audit.basketAudit.itemText, /找整理桌面的片段.*整理桌面物品.*01:16\.2.*01:18\.0/s);
    assert.equal(audit.basketAudit.generateLabel, "生成合并视频");
    assert.equal(audit.boundaryButtonText, "调整边界");
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
  page.on("dialog", async (dialog) => dialog.accept("browser-test-token"));
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#homeTaskGrid .home-empty").waitFor({ state: "visible" });
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


test("content timeline separates the composed clock from the source comparison", async () => {
  const stub = await startStubServer();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("dialog", async (dialog) => dialog.accept("browser-test-token"));
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#homeTaskGrid .home-empty").waitFor({ state: "visible" });
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
      timelineCoordinateSpace = "output";
      timelineViewStart = 0;
      timelineViewEnd = 17;
      updateTimeline();
      const outputView = {
        layout: document.querySelector("#timelineViewport")?.dataset.trackLayout || "",
        trackLabels: [...document.querySelectorAll("#timelineTrackLabels span")].map((node) => node.textContent),
        segments: [...document.querySelectorAll("#timelineLabels .timeline-sequence-segment")].map((node) => ({
          text: node.textContent.trim(), left: node.style.left, width: node.style.width,
        })),
        relationCurves: document.querySelectorAll("#timelineEventRelations .timeline-event-curve").length,
        summary: document.querySelector("#timelineEventSummaryTime")?.textContent || "",
        summaryButtons: document.querySelectorAll("#timelineEventSummaryText button").length,
        clock: document.querySelector("#timelineClockLabel")?.textContent || "",
        duration: document.querySelector("#timelineDuration")?.textContent || "",
      };

      document.querySelector("#timelineSourceAxis")?.click();
      const sourceView = {
        layout: document.querySelector("#timelineViewport")?.dataset.trackLayout || "",
        trackLabels: [...document.querySelectorAll("#timelineTrackLabels span")].map((node) => node.textContent),
        segments: [...document.querySelectorAll("#timelineLabels .timeline-sequence-segment")].map((node) => ({
          text: node.textContent.trim(), left: node.style.left,
        })),
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
    assert.equal(audit.outputView.layout, "composed-output");
    assert.deepEqual(audit.outputView.trackLabels, ["成片顺序"]);
    assert.equal(audit.outputView.segments.length, 2);
    assert.match(audit.outputView.segments[0].text, /01.*嘉宾回答第二个问题/);
    assert.match(audit.outputView.segments[1].text, /02.*嘉宾回答第一个问题/);
    assert.equal(audit.outputView.segments[0].left, "0%");
    assert.ok(Math.abs(Number.parseFloat(audit.outputView.segments[1].left) - 9 / 17 * 100) < .001);
    assert.equal(audit.outputView.relationCurves, 0);
    assert.match(audit.outputView.summary, /2 个片段.*内容视频 17\.0 秒/);
    assert.equal(audit.outputView.summaryButtons, 0);
    assert.equal(audit.outputView.clock, "成片");
    assert.equal(audit.outputView.duration, "00:17.0");
    assert.equal(audit.sourceView.layout, "composed-source");
    assert.deepEqual(audit.sourceView.trackLabels, ["采用位置", "源画面", "源音频"]);
    assert.equal(audit.sourceView.segments.length, 2);
    assert.match(audit.sourceView.segments[0].text, /01.*嘉宾回答第二个问题/);
    assert.match(audit.sourceView.segments[1].text, /02.*嘉宾回答第一个问题/);
    assert.ok(Math.abs(Number.parseFloat(audit.sourceView.segments[0].left) - 42 / 90 * 100) < .001);
    assert.ok(Math.abs(Number.parseFloat(audit.sourceView.segments[1].left) - 10 / 90 * 100) < .001);
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
      return {
        flow: document.querySelector(".content-flow-strip")?.textContent || "",
        text: document.body.textContent || "",
        dialogueControls: document.querySelectorAll("[data-content-dialogue-mode]").length,
        personPanels: document.querySelectorAll("[data-person-target-panel]").length,
      };
    });
    assert.match(audit.flow, /无需单独确认人物/);
    assert.match(audit.text, /只输出问题片段.*不包含回答内容/);
    assert.equal(audit.dialogueControls, 0);
    assert.equal(audit.personPanels, 0);
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
  page.on("dialog", async (dialog) => dialog.accept("browser-test-token"));
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#homeTaskGrid .home-empty").waitFor({ state: "visible" });
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
          outputs: [{ filename: "v001-content.mp4", duration: 54.4, segmentCount: 3 }],
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
  page.on("dialog", async (dialog) => dialog.accept("browser-test-token"));
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#homeTaskGrid .home-empty").waitFor({ state: "visible" });
    await page.evaluate(() => {
      const job = {
        id: "target_click_job",
        taskMode: "content_extract",
        status: "awaiting_content_confirmation",
        stage: "content_search_ready",
        messages: [],
        request: {},
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
  page.on("dialog", async (dialog) => dialog.accept("browser-test-token"));
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#homeTaskGrid .home-empty").waitFor({ state: "visible" });
    await page.evaluate(() => {
      subtitleReviewDraft = {
        id: "sub_1234567890abcdef", revision: 1, status: "draft",
        globalStyle: { preset: "clean", fontSizeRatio: .04, horizontal: "center", vertical: "bottom", offsetXRatio: 0, offsetYRatio: 0 },
        cueStyleOverrides: {},
        cues: [{ id: "cue_test", outputIndex: 0, start: 0, end: 3, sourceStart: 12, sourceEnd: 15, text: "这是需要人工校对的一条字幕", originalText: "这是需要人工校对的一条字幕", suggestionStatus: "none" }],
      };
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
    }));
    await page.locator("[data-cue-split]").click();
    assert.equal(await page.locator(".subtitle-cue").count(), 2);
    assert.ok(initial.panelWidth >= 700);
    assert.ok(initial.textareaSize >= 15);
    assert.match(initial.commandPlaceholder, /字号 48px/);
    assert.equal(initial.footerVisible, true);
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
  page.on("dialog", async (dialog) => dialog.accept("browser-test-token"));
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#homeTaskGrid .home-empty").waitFor({ state: "visible" });
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
  page.on("dialog", async (dialog) => dialog.accept("browser-test-token"));
  try {
    await page.goto(stub.url, { waitUntil: "domcontentloaded" });
    await page.locator("#homeTaskGrid .home-empty").waitFor({ state: "visible" });
    const audit = await page.evaluate(() => {
      const outputs = [{ filename: "one.mp4" }, { filename: "two.mp4" }];
      const failed = displayStatusForJob({ status: "failed", outputs, outputVersions: [{ number: 1, outputs }] });
      const waiting = displayStatusForJob({ status: "awaiting_confirmation", outputs, outputVersions: [{ number: 1, outputs }] });
      const queued = displayStatusForJob({ status: "queued", outputs, outputVersions: [{ number: 1, outputs }] });
      const separate = displayStatusForJob({
        status: "completed",
        outputVersions: [
          { number: 1, outputs: [{ filename: "one.mp4" }] },
          { number: 2, outputs: [{ filename: "two-a.mp4" }, { filename: "two-b.mp4" }] },
        ],
      });
      return { failed, waiting, queued, separate };
    });
    assert.match(audit.failed.text, /处理失败/);
    assert.match(audit.failed.text, /已保留 1 个版本 · 2 条视频/);
    assert.match(audit.waiting.text, /等待确认高光/);
    assert.match(audit.waiting.text, /1 个版本 · 2 条视频/);
    assert.match(audit.queued.text, /排队中/);
    assert.equal(audit.queued.running, false);
    assert.match(audit.separate.text, /已完成 · 2 个版本 · 3 条视频/);
  } finally {
    await browser.close();
    await stub.close();
  }
});
