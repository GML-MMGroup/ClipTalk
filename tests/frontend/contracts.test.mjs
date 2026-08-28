import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const read = (path) => fs.readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

test("workflow copy uses one four-mode terminology contract", () => {
  const context = { window: {} };
  vm.runInNewContext(read("static/ui-copy.js"), context);
  const copy = context.window.ClipTalkCopy;

  assert.deepEqual([...copy.WORKFLOWS.highlight.navigation[2]], ["事件审核", "确认事件与内部镜头"]);
  assert.equal(copy.WORKFLOWS.content_search.output, "内容视频");
  assert.equal(copy.WORKFLOWS.person_edit.timeline, "人物出镜时间线");
  assert.equal(copy.WORKFLOWS.speaker_edit.candidate, "发言片段");
  assert.equal(copy.ACTIONS.preview, "生成预览");
  assert.equal(copy.ACTIONS.exportVersion, "导出新版本");
});

test("workspace state prefers canonical presentation and execution facts", () => {
  const context = { window: {} };
  vm.runInNewContext(read("static/workspace-state.js"), context);
  const { derive, STATES } = context.window.ClipTalkWorkspaceState;

  assert.equal(derive({
    job: {
      status: "running",
      execution: { schemaVersion: 1, status: "waiting_user", active: false },
      presentation: { phase: "review", state: "action_required" },
    },
  }), STATES.REVIEWING);
  assert.equal(derive({
    job: {
      status: "running",
      execution: { schemaVersion: 1, status: "completed", outcome: "output_ready" },
      presentation: { phase: "complete", state: "ready" },
    },
  }), STATES.COMPLETED);
});

test("API errors preserve recovery action and request number", async () => {
  const memory = new Map();
  const context = {
    window: {
      sessionStorage: {
        getItem: (key) => memory.get(key) || "",
        setItem: (key, value) => memory.set(key, String(value)),
        removeItem: (key) => memory.delete(key),
      },
      crypto: { randomUUID: () => "browser-session-1" },
      document: { querySelector: () => null },
    },
    Headers,
    fetch: async () => new Response(JSON.stringify({
      detail: { code: "internal_error", message: "处理暂时失败" },
      error: {
        code: "internal_error",
        message: "处理暂时失败",
        recoveryAction: "retry",
        requestId: "req-500-1",
      },
    }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    }),
  };
  vm.runInNewContext(read("static/api-client.js"), context);

  await assert.rejects(
    context.window.ClipTalkApi.request("/api/failing"),
    (error) => {
      assert.equal(error.status, 500);
      assert.equal(error.code, "internal_error");
      assert.equal(error.recoveryAction, "retry");
      assert.equal(error.requestId, "req-500-1");
      assert.match(error.message, /处理暂时失败 · 请重试 · 请求编号 req-500-1/);
      return true;
    },
  );
});

test("workspace copy and dialogs avoid mixed-language and native blocking UI", () => {
  const html = read("static/index.html");
  const app = read("static/app.js");
  const source = `${html}\n${app}`;
  const bannedKickers = [
    "CREATE WORKFLOW",
    "SOURCE VIDEO",
    "CURRENT REVIEW",
    "RAW VISUAL MOMENTS",
    "SPEAKER-BASED EDITING",
    "PERSON-BASED EDITING",
  ];

  for (const phrase of bannedKickers) assert.equal(source.includes(phrase), false, phrase);
  assert.equal(/window\.(prompt|confirm)\s*\(/.test(app), false);
  assert.match(html, /id="inputPrompt"/);
  assert.match(html, /static\/ui-copy\.js/);
});

test("compact workspace rules cover small laptop viewports and long lists", () => {
  const css = read("static/workspace-polish.css");

  assert.match(css, /@media \(max-width: 1366px\)/);
  assert.match(css, /grid-template-columns:\s*220px minmax\(430px, 1fr\) 260px/);
  assert.match(css, /\.current-person-range-more/);
  assert.match(css, /\.current-voice-turn-more/);
});
