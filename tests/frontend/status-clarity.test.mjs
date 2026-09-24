import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
function extract(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf("\n}", start) + 2);
}
function contextFor(names, values = {}) {
  const context = vm.createContext(values);
  vm.runInContext(names.map(extract).join("\n"), context);
  return context;
}

for (const [status, expected] of [["draft", "字幕草稿已保存，待确认"], ["confirmed", "字幕修改已保存并确认"], ["auto_reviewed", "字幕修改已保存，已自动校对"]]) {
  test(`subtitle save reports the returned ${status} state`, async () => {
    const label = { textContent: "" };
    const context = contextFor(["secondaryEditorSubtitleSavedMessage", "saveSecondaryEditorSubtitleDraft"], {
      currentJob: { id: "job" }, secondaryEditSubtitleDraft: { id: "draft", status: "confirmed", cues: [] },
      secondaryEditSubtitleSaving: false, secondaryEditSubtitleSaveTimer: null,
      window: { clearTimeout() {} }, $: () => label,
      captureSecondaryEditorAction: () => ({ current: () => true }),
      apiJson: async () => ({ draft: { id: "draft", status } }), showToast: assert.fail,
    });
    await context.saveSecondaryEditorSubtitleDraft();
    assert.equal(label.textContent, expected);
    assert.equal(context.secondaryEditSubtitleDraft.status, status);
  });
}

test("late subtitle save does not update another editor", async () => {
  const label = { textContent: "" };
  const context = contextFor(["secondaryEditorSubtitleSavedMessage", "saveSecondaryEditorSubtitleDraft"], {
    currentJob: { id: "job" }, secondaryEditSubtitleDraft: { id: "old", cues: [] },
    secondaryEditSubtitleSaving: false, secondaryEditSubtitleSaveTimer: null,
    window: { clearTimeout() {} }, $: () => label,
    captureSecondaryEditorAction: () => ({ current: () => false }),
    apiJson: async () => { label.textContent = "new editor"; return { draft: { id: "old", status: "confirmed" } }; },
    showToast: assert.fail,
  });
  await context.saveSecondaryEditorSubtitleDraft();
  assert.equal(label.textContent, "new editor");
  assert.equal(context.secondaryEditSubtitleDraft.status, undefined);
});

test("cover status requires a binding to the selected output, not merely a selected image", () => {
  const { coverTimelineSavedState: state } = contextFor(["coverTimelineSavedState"]);
  assert.equal(state({}, null, false), "待保存");
  assert.equal(state({}, null, true), "图片已保存");
  assert.equal(state({ currentCoverVersionId: "new" }, { coverVersionId: "old" }, true), "图片已保存");
  assert.equal(state({ currentCoverVersionId: "new" }, { coverVersionId: "new" }, true), "已关联此版本");
  assert.equal(state({ currentCoverVersionId: "new" }, { coverVersionId: "new", coverIntro: { enabled: true } }, true), "已加入此版本片头");
});

test("output labels show actual dimensions and never infer HD from formal status", () => {
  const { outputResolutionLabel: label } = contextFor(["outputResolutionLabel"]);
  assert.equal(label({ width: 640, height: 360 }), " · 640×360");
  assert.equal(label({ width: 1080, height: 1920 }), " · 1080×1920");
  assert.equal(label({}), "");
  assert.equal(label({ width: Infinity, height: 1080 }), "");
  assert.doesNotMatch(source, /高清成片|高清 MP4|独立高清副本/);
});

test("all three formal export confirmations explain that download comes after generation", () => {
  for (const name of ["generateSecondaryEditorVersion", "exportAgentReviewPreview", "finalizePreviewVersion"]) {
    assert.match(extract(name), /将生成正式视频，完成后点击“下载 MP4”保存到电脑/);
  }
});

for (const invalid of ["stale", "missing_url", "dirty", "proposal"]) {
  test(`review playback rejects ${invalid} without loading a file`, () => {
    const context = contextFor(["secondaryEditorPreviewIsCurrent", "playSecondaryEditorReviewPreview"], {
      secondaryEditSession: { previewStatus: "ready", revision: 2, previewRevision: invalid === "stale" ? 1 : 2,
        previewUrl: invalid === "missing_url" ? "" : "/review.mp4", pendingProposal: invalid === "proposal" ? {} : null },
      secondaryEditorInspectorHasChanges: () => invalid === "dirty", $: assert.fail,
    });
    assert.equal(context.playSecondaryEditorReviewPreview(), false);
  });
}
