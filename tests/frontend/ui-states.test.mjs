/**
 * ui-states.js 单元测试
 *
 * 覆盖：
 *   1. emptyStateHtml 的结构、转义、引导动作与属性白名单
 *   2. loadingStateHtml 的骨架条与无障碍属性
 *   3. createPolling 的可见性暂停与停止语义
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

function loadAdapter() {
  const source = readFileSync(new URL("../../static/ui-states.js", import.meta.url), "utf8");
  const sandbox = { window: {}, document: { hidden: false, addEventListener() {}, removeEventListener() {} } };
  sandbox.window = sandbox;
  const fn = new Function("window", "document", source + "\nreturn window.ClipTalkUIStates;");
  return fn(sandbox, sandbox.document);
}

const ui = loadAdapter();

test("emptyStateHtml 必须有 title，否则返回空串", () => {
  assert.equal(ui.emptyStateHtml({}), "");
  assert.equal(ui.emptyStateHtml({ title: "   " }), "");
});

test("emptyStateHtml 输出 ct-empty 基础类并保留局部修饰类", () => {
  const html = ui.emptyStateHtml({ title: "还没有任务", className: "app-sidebar-empty" });
  assert.match(html, /class="ct-empty app-sidebar-empty"/);
  assert.match(html, /<strong>还没有任务<\/strong>/);
});

test("emptyStateHtml 渲染 hint 与引导动作按钮", () => {
  const html = ui.emptyStateHtml({
    title: "还没有生成成片",
    hint: "审核样片确认后会自动出现。",
    actionLabel: "打开任务列表",
    actionAttr: "data-library-tasks",
  });
  assert.match(html, /<p>审核样片确认后会自动出现。<\/p>/);
  assert.match(html, /<button type="button" class="ct-empty__action" data-library-tasks>打开任务列表<\/button>/);
});

test("emptyStateHtml 转义标题，杜绝 HTML 注入", () => {
  const html = ui.emptyStateHtml({ title: '<img src=x onerror="alert(1)">' });
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

test("emptyStateHtml 拒绝非法的 actionAttr（属性注入防护）", () => {
  const html = ui.emptyStateHtml({
    title: "标题",
    actionLabel: "点我",
    actionAttr: 'data-x onmouseover="alert(1)"',
  });
  assert.doesNotMatch(html, /onmouseover/);
  assert.doesNotMatch(html, /ct-empty__action/);
});

test("emptyStateHtml 支持 inline 变体", () => {
  const html = ui.emptyStateHtml({ title: "还没有", variant: "inline" });
  assert.match(html, /ct-empty ct-empty--inline/);
});

test("emptyStateHtml 带 role=status 便于读屏播报", () => {
  assert.match(ui.emptyStateHtml({ title: "空" }), /role="status"/);
});

test("loadingStateHtml 默认渲染 3 条骨架并带 aria-live", () => {
  const html = ui.loadingStateHtml({ label: "正在生成计划" });
  assert.match(html, /role="status"/);
  assert.match(html, /aria-live="polite"/);
  // 精确匹配 class="ct-loading__bar"：ct-loading__bars 是容器名，会污染计数
  assert.equal((html.match(/class="ct-loading__bar"/g) || []).length, 3);
  assert.match(html, /<strong>正在生成计划<\/strong>/);
});

test("loadingStateHtml 骨架条数量限制在 1–6", () => {
  assert.equal((ui.loadingStateHtml({ rows: 99 }).match(/class="ct-loading__bar"/g) || []).length, 6);
  assert.equal((ui.loadingStateHtml({ rows: 0 }).match(/class="ct-loading__bar"/g) || []).length, 1);
});

test("loadingStateHtml 可关闭骨架条", () => {
  const html = ui.loadingStateHtml({ label: "x", skeleton: false });
  assert.doesNotMatch(html, /ct-loading__bar/);
});

test("createPolling 页面隐藏时不执行", () => {
  const calls = [];
  const doc = { hidden: true, addEventListener() {}, removeEventListener() {} };
  const win = {
    document: doc,
    setInterval: () => 1,
    clearInterval: () => {},
  };
  const source = readFileSync(new URL("../../static/ui-states.js", import.meta.url), "utf8");
  const fn = new Function("window", "document", source + "\nreturn window.ClipTalkUIStates;");
  const local = fn(win, doc);

  const polling = local.createPolling(() => calls.push(1), 1000);
  polling.refresh();
  assert.equal(calls.length, 0, "隐藏状态下 refresh 不应执行任务");
  polling.stop();
});

test("createPolling 页面可见时执行", () => {
  const calls = [];
  const doc = { hidden: false, addEventListener() {}, removeEventListener() {} };
  const win = { document: doc, setInterval: () => 1, clearInterval: () => {} };
  const source = readFileSync(new URL("../../static/ui-states.js", import.meta.url), "utf8");
  const fn = new Function("window", "document", source + "\nreturn window.ClipTalkUIStates;");
  const local = fn(win, doc);

  const polling = local.createPolling(() => calls.push(1), 1000);
  polling.refresh();
  assert.equal(calls.length, 1);
  polling.stop();
});

test("createPolling stop 之后不再执行", () => {
  const calls = [];
  const doc = { hidden: false, addEventListener() {}, removeEventListener() {} };
  const win = { document: doc, setInterval: () => 7, clearInterval: () => {} };
  const source = readFileSync(new URL("../../static/ui-states.js", import.meta.url), "utf8");
  const fn = new Function("window", "document", source + "\nreturn window.ClipTalkUIStates;");
  const local = fn(win, doc);

  const polling = local.createPolling(() => calls.push(1), 1000);
  polling.stop();
  polling.refresh();
  assert.equal(calls.length, 0);
});
