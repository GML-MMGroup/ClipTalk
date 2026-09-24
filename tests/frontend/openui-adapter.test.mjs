/* ClipTalk × OpenUI：转译层单元测试
 *
 * adapter 是纯函数，所以可以在 Node 里直接跑，不需要浏览器。
 * 这是"确定性转译"路线相对"LLM 生成 UI"的核心优势：可验证、可回归。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function loadAdapter() {
  const source = readFileSync(path.join(root, "static/openui-adapter.js"), "utf8");
  const sandbox = { window: {} };
  new Function("window", source)(sandbox.window);
  return sandbox.window.ClipTalkOpenUIAdapter;
}

const adapter = loadAdapter();

test("adapter 挂载到 window", () => {
  assert.equal(typeof adapter.activityToOpenUILang, "function");
});

test("空活动流渲染为空态而不是报错", () => {
  const code = adapter.activityToOpenUILang([]);
  assert.match(code, /^root = Card\(\[empty\]\)/);
  assert.match(code, /还没有活动记录/);
});

test("非数组输入被安全处理", () => {
  assert.match(adapter.activityToOpenUILang(null), /还没有活动记录/);
  assert.match(adapter.activityToOpenUILang(undefined), /还没有活动记录/);
});

test("活动项转成 ListItem，时间并入标题", () => {
  const code = adapter.activityToOpenUILang([
    { time: "10:24", title: "完成高光分析", detail: "识别到 6 个候选片段" },
  ]);
  assert.match(code, /i0 = ListItem\("10:24 · 完成高光分析", "识别到 6 个候选片段"\)/);
  assert.match(code, /items = ListBlock\(\[i0\], "number", "small"\)/);
});

test("首行是入口 root = Card，符合库的实际 root 约定", () => {
  const code = adapter.activityToOpenUILang([{ time: "", title: "A", detail: "B" }]);
  assert.ok(code.split("\n")[0].startsWith("root = Card("), "首行必须是入口");
});

test("引用先定义后使用，ListBlock 在最后", () => {
  const code = adapter.activityToOpenUILang([
    { time: "", title: "A", detail: "B" },
    { time: "", title: "C", detail: "D" },
  ]);
  const lines = code.split("\n");
  assert.match(lines[lines.length - 1], /^items = ListBlock\(\[i0, i1\]/);
});

test("双引号被转义，不会截断 OpenUI Lang 字符串", () => {
  const code = adapter.activityToOpenUILang([{ time: "", title: '含"引号"的标题', detail: "x" }]);
  assert.ok(code.includes('含\\"引号\\"的标题'), "双引号必须转义");
});

test("反斜杠被转义", () => {
  const code = adapter.activityToOpenUILang([{ time: "", title: "路径 C:\\temp", detail: "" }]);
  assert.ok(code.includes("C:\\\\temp"), "反斜杠必须转义");
});

test("换行被折叠为空格，保持行式语法", () => {
  const code = adapter.activityToOpenUILang([{ time: "", title: "第一行\n第二行", detail: "" }]);
  const itemLine = code.split("\n").find((line) => line.startsWith("i0 = "));
  assert.equal(itemLine.split("\n").length, 1, "单条目必须占一行");
  assert.ok(itemLine.includes("第一行 第二行"));
});

test("超长文案被截断并带省略号", () => {
  const code = adapter.activityToOpenUILang([{ time: "", title: "x".repeat(300), detail: "" }]);
  const itemLine = code.split("\n").find((line) => line.startsWith("i0 = "));
  assert.ok(itemLine.includes("…"), "超长内容应截断");
  assert.ok(itemLine.length < 200);
});

test("最多渲染 80 条，防止单帧过大", () => {
  const items = Array.from({ length: 120 }, (_, index) => ({
    time: "",
    title: "t" + index,
    detail: "",
  }));
  const code = adapter.activityToOpenUILang(items);
  assert.ok(code.includes("i79"), "第 80 条应保留");
  assert.ok(!code.includes("i80"), "第 81 条应被丢弃");
});

test("缺失字段不会产生 undefined", () => {
  const code = adapter.activityToOpenUILang([{ title: "只有标题" }]);
  assert.ok(!code.includes("undefined"), "不应出现 undefined");
});
