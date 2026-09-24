import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
function functionSource(name) {
  const start = source.indexOf(`async function ${name}(`);
  const end = source.indexOf("\n}", start) + 2;
  return source.slice(start, end);
}
const helper = source.slice(source.indexOf("function captureSecondaryEditorAction("), source.indexOf("async function reviewSecondaryEditorSubtitles("));
const riskHelper = source.slice(source.indexOf("function agentReviewExportRisk("), source.indexOf("async function exportAgentReviewPreview("));
function harness() {
  let resolveRequest;
  const requests = [], busy = [], toasts = [];
  const session = { id: "session-A", revision: 1, clips: [{ id: "clip" }], subtitleEnabled: false,
    previewStatus: "ready", previewRevision: 1, pendingProposal: { id: "proposal-A" } };
  const context = { currentJob: { id: "A" }, secondaryEditSession: session, secondaryEditActivationToken: 1,
    secondaryEditBusy: false, secondaryEditSelectedClips: new Set(), secondaryEditSubtitleNeedsReview: false,
    secondaryEditorOpen: () => true, secondaryEditorInspectorHasChanges: () => false,
    secondaryEditorTimelineDuration: () => 10, formatTime: String,
    setSecondaryEditorBusy: (...args) => busy.push(args), showToast: message => toasts.push(message),
    $: () => ({ value: "new version", checked: false }),
    syncSecondaryEditorSessionToJob() {}, secondaryEditorMarkPreviewStale() {}, renderSecondaryEditorProposal() {}, renderSecondaryEditor() {},
    apiJson: (path, options) => { requests.push({ path, options }); return new Promise(resolve => { resolveRequest = resolve; }); },
    requestActionConfirmation: async () => true, closeSecondaryEditor() {}, renderJob() {}, clearTimeout() {}, pollJob() {}, pollTimer: 0,
  };
  context.api = context.apiJson;
  vm.createContext(context);
  vm.runInContext(helper, context);
  vm.runInContext(riskHelper, context);
  return { context, requests, busy, toasts,
    switchTask() { context.currentJob = { id: "B" }; context.secondaryEditSession = { id: "session-B", revision: 1 }; context.secondaryEditActivationToken++; },
    resolve(payload) { resolveRequest(payload); },
    run(name, args = "") { vm.runInContext(functionSource(name), context); return vm.runInContext(`${name}(${args})`, context); },
  };
}

for (const [name, args] of [["createSecondaryEditorProposal", "'shorten'"], ["selectSecondaryEditorProposal", "'variant'"],
  ["applySecondaryEditorProposal", ""], ["cancelSecondaryEditorProposal", ""]]) {
  test(`${name}: late response cannot replace another task's session or busy state`, async () => {
    const h = harness(); const pending = h.run(name, args);
    h.switchTask(); const busyCount = h.busy.length;
    h.resolve({ session: { id: "late-A", revision: 2 } }); await pending;
    assert.equal(h.context.secondaryEditSession.id, "session-B");
    assert.equal(h.busy.length, busyCount); assert.equal(h.toasts.length, 0);
  });
}
for (const change of ["task", "revision", "activation", "subtitles"]) {
  test(`export confirmation aborts after ${change} changes`, async () => {
    const h = harness();
    h.context.secondaryEditSession.pendingProposal = null;
    h.context.requestActionConfirmation = async () => {
      if (change === "task") h.switchTask();
      if (change === "revision") h.context.secondaryEditSession.revision++;
      if (change === "activation") h.context.secondaryEditActivationToken++;
      if (change === "subtitles") h.context.secondaryEditSession.subtitleEnabled = true;
      return true;
    };
    await h.run("generateSecondaryEditorVersion"); assert.equal(h.requests.length, 0);
  });
}
