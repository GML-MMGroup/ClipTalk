import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
import { chromium } from "playwright";

const stateSource = readFileSync(new URL("../../static/delivery-state.js", import.meta.url), "utf8");
const source = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const finalize = source.slice(source.indexOf("async function finalizePreviewVersion("), source.indexOf("async function regenerateMissingAutoVariants("));

test("synthetic Agent previews use their session, never a fabricated version API", async () => {
  const dispatcher = source.slice(source.indexOf("window.ClipTalkVersionAction ="), source.indexOf("function renderOutputPreviewSelector("));
  const calls = [];
  const entry = { version: { id: "agent-review-previews", previewOnly: true }, output: { filename: "agent.mp4", previewOnly: true } };
  const context = { window: { ClipTalkOpenAgentTimeline: options => calls.push(["session", options.sessionId]) },
    locateJobOutput: () => entry, sourceEditSessionForOutput: () => ({ id: "real-session" }),
    exportAgentReviewPreview: output => calls.push(["render", output.filename]),
    openSecondaryEditor: () => assert.fail("Synthetic version sent to normal editor"),
    finalizePreviewVersion: () => assert.fail("Synthetic version sent to normal finalize"), showToast: message => calls.push(["toast", message]),
  };
  vm.createContext(context);
  vm.runInContext(dispatcher, context);
  await context.window.ClipTalkVersionAction("agent.mp4", "edit");
  await context.window.ClipTalkVersionAction("agent.mp4", "export");
  assert.deepEqual(calls, [["session", "real-session"], ["render", "agent.mp4"]]);
  context.sourceEditSessionForOutput = () => null;
  await context.window.ClipTalkVersionAction("agent.mp4", "edit");
  assert.match(calls.at(-1)[1], /缺少可编辑/);
});

for (const change of ["job", "revision", "subtitles", "stale preview"]) {
  test(`Agent export visibly rejects changed ${change}`, async () => {
    const exportSource = source.slice(source.indexOf("async function exportAgentReviewPreview("), source.indexOf("// Agent plan surfaces use"));
    const session = { id: "s", revision: 2, previewRevision: 2, previewStatus: "ready", clips: [{ sourceStart: 1, sourceEnd: 5 }] };
    const initialJob = { id: "A", editSessions: [session] };
    const messages = [], requests = [];
    const context = { window: { structuredClone }, currentJob: initialJob, actionBusy: false,
      api: async () => ({ job: initialJob }), agentReviewPreviewsForJob: () => [],
      agentReviewExportRisk: () => ({ warningCodes: [] }),
      item: { filename: "agent.mp4", sourceEditSessionId: "s", revision: 2, qualityStatus: "passed" },
      captureJobAction: () => ({ jobId: "A" }), jobActionStillCurrent: () => context.currentJob.id === "A",
      showToast: message => messages.push(message), apiJson: (...args) => requests.push(args),
      requestActionConfirmation: async () => {
        if (change === "job") context.currentJob = { id: "B" };
        if (change === "revision") session.revision++;
        if (change === "subtitles") session.subtitleDraftId = "new-draft";
        return true;
      },
    };
    if (change === "stale preview") session.previewStatus = "stale";
    vm.createContext(context);
    vm.runInContext(exportSource, context);
    await vm.runInContext("exportAgentReviewPreview(item)", context);
    assert.equal(requests.length, 0);
    assert.ok(messages.length && /变化|最新预览/.test(messages[0]));
  });
}

function harness() {
  const output = { filename: "second.mp4", outputRevision: "revision", subtitleMode: "burn", subtitleStyle: "bold", segments: [{ start: 10, end: 12 }] };
  const version = { id: "v1", outputs: [output], qualityStatus: "passed" };
  const job = { id: "A", outputVersions: [version] };
  const requests = [];
  const context = {
    window: {}, currentJob: job, actionBusy: false, output, version,
    $: () => ({ value: "none" }), showToast() {}, outputVersionQuality: () => "passed", formatTime: String,
    captureJobAction: () => ({ jobId: context.currentJob.id }),
    jobActionStillCurrent: token => token.jobId === context.currentJob.id,
    requestActionConfirmation: async () => true,
    reviewSubtitlesBeforeRender: async () => ({ id: "draft" }),
    apiJson: async (path, options) => { requests.push({ path, options }); return { job }; },
    commitJobAction: () => false, clearTimeout() {}, pollTimer: 0, pollJob() {},
  };
  vm.createContext(context);
  vm.runInContext(stateSource, context);
  vm.runInContext(finalize, context);
  return { context, requests, run: () => vm.runInContext("finalizePreviewVersion(version, output)", context) };
}

for (const checkpoint of ["confirmation", "subtitle review"]) {
  test(`export aborts if task changes during ${checkpoint}`, async () => {
    const h = harness();
    const switchTask = async () => {
      h.context.currentJob = { id: "B", outputVersions: [] };
      return checkpoint === "confirmation" ? true : { id: "draft" };
    };
    h.context[checkpoint === "confirmation" ? "requestActionConfirmation" : "reviewSubtitlesBeforeRender"] = switchTask;
    await h.run();
    assert.equal(h.requests.length, 0);
  });
}

test("export ignores unrelated global subtitles and sends selected output identity", async () => {
  const h = harness();
  await h.run();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].path, "/api/jobs/A/output-versions/v1/finalize");
  assert.equal(h.requests[0].options.body.outputFilename, "second.mp4");
  assert.equal(h.requests[0].options.body.outputRevision, "revision");
  assert.equal(h.requests[0].options.body.subtitleMode, "burn");
  assert.equal(h.requests[0].options.body.subtitleStyle, "bold");
});

test("export rejects a changed selected revision without rejecting unrelated progress updates", async () => {
  const h = harness();
  h.context.requestActionConfirmation = async () => {
    h.context.currentJob.revision = 123;
    return true;
  };
  await h.run();
  assert.equal(h.requests.length, 1);
  h.context.requestActionConfirmation = async () => {
    h.context.output.outputRevision = "changed";
    return true;
  };
  await h.run();
  assert.equal(h.requests.length, 1);
});

for (const orderMode of ['source', 'selection', 'ai_plan']) {
  test(`basket confirmation reflects ${orderMode} and rejects a changed basket`, async () => {
    const fn = source.slice(source.indexOf('async function confirmContentSelectionBasket('), source.indexOf('async function reopenCurrentJobForEditing('));
    const items = [{ title: '后段', start: 20, end: 25 }, { title: '前段', start: 1, end: 8 }];
    const job = { id: 'A', contentSelectionBasket: { orderMode, outputMode: 'separate_events', items } };
    let shown;
    const messages = [];
    const context = {
      currentJob: job, actionBusy: false, contentBasketItems: () => items,
      interactionCapabilitiesForJob: () => ({ canMutateContentBasket: true }),
      contentBasketTimingSummary: () => ({ uniqueDuration: 12, overlapCount: 0 }),
      captureJobAction: () => ({ jobId: 'A' }), jobActionStillCurrent: () => true,
      formatTime: String, showToast: text => messages.push(text),
      apiJson: () => assert.fail('changed basket submitted'),
      requestActionConfirmation: async options => { shown = options; job.contentSelectionBasket.items = []; return true; },
    };
    vm.createContext(context);
    vm.runInContext(fn, context);
    await vm.runInContext('confirmContentSelectionBasket()', context);
    assert.match(shown.summary, /每段分别生成/);
    assert.match(shown.summary, orderMode === 'ai_plan' ? /最终顺序以预览为准/ : orderMode === 'source' ? /按源视频时间/ : /按加入顺序/);
    assert.match(shown.details[0], orderMode === 'source' ? /前段/ : /后段/);
    assert.match(messages[0], /清单已变化/);
  });
}

test("per-export choices are editable, isolated and frozen at confirmation", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.setContent('<ul id="details"></ul><select id="subtitleMode"><option value="burn">burn</option></select>');
    await page.addScriptTag({ content: stateSource });
    await page.evaluate(() => {
      window.form = window.ClipTalkDelivery.mountOptions(document.querySelector("#details"), { subtitleMode: "none", subtitleStyle: "bold", outputFilename: "selected.mp4" });
    });
    await page.getByLabel("本次导出字幕").selectOption("burn");
    await page.getByLabel("本次导出样式").selectOption("social");
    assert.match(await page.locator('fieldset [role="status"]').textContent(), /添加字幕.*短视频/);
    assert.deepEqual(await page.evaluate(() => window.form.read()), { subtitleMode: "burn", subtitleStyle: "social", outputFilename: "selected.mp4" });
    assert.equal(await page.locator("#subtitleMode").inputValue(), "burn");
    assert.equal(await page.evaluate(() => Object.isFrozen(window.form.read())), true);
    await page.getByLabel("本次导出字幕").selectOption("none");
    assert.equal(await page.getByLabel("本次导出样式").isDisabled(), true);
    assert.match(await page.locator('fieldset [role="status"]').textContent(), /不添加字幕/);
    await page.evaluate(() => window.form.remove());
    assert.equal(await page.locator("fieldset").count(), 0);
  } finally { await browser.close(); }
});

test("keep returns a structured failure to delivery dialogs", async () => {
  const fn = source.slice(source.indexOf("async function saveCurrentOutputToLibrary("), source.indexOf("async function finalizeOneOffTask("));
  const context = { window: {}, currentJob: { id: "A" }, currentOutput: { filename: "clip.mp4" }, actionBusy: false,
    $: () => null, captureJobAction: () => ({ jobId: "A" }), jobActionStillCurrent: () => true,
    syncLibrarySaveAction() {}, showToast() {}, apiJson: async () => { throw new Error("disk full"); } };
  vm.createContext(context);
  vm.runInContext(fn, context);
  const result = await vm.runInContext("saveCurrentOutputToLibrary()", context);
  assert.equal(result.ok, false);
  assert.equal(result.error, "disk full");
  assert.equal(context.actionBusy, false);
});

test("planning and rendering busy states never claim that a save is underway", () => {
  const fn = source.slice(source.indexOf("function setSecondaryEditorBusy("), source.indexOf("function secondaryEditor", source.indexOf("function setSecondaryEditorBusy(")));
  const state = { dataset: { state: "draft" }, textContent: "" };
  const context = { secondaryEditBusy: false, $: selector => selector === "#secondaryEditorSaveState" ? state : { querySelectorAll: () => [] }, syncSecondaryEditorControls() {} };
  vm.createContext(context);
  vm.runInContext(fn, context);
  vm.runInContext('setSecondaryEditorBusy(true, "正在解析", "working")', context);
  assert.equal(state.dataset.state, "draft");
  vm.runInContext('setSecondaryEditorBusy(true, "正在生成", "render")', context);
  assert.equal(state.dataset.state, "draft");
  assert.equal(state.dataset.operation, "render");
  vm.runInContext('setSecondaryEditorBusy(true, "正在保存", "save")', context);
  assert.equal(state.dataset.state, "saving");
  vm.runInContext('setSecondaryEditorBusy(false, "已保存", "save")', context);
  assert.equal(state.dataset.state, "saved");
});
