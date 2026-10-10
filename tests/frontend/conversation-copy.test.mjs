/**
 * 历史消息文案归一测试。
 *
 * 消息流是持久化的：早期版本「封面保存」这一个事件在已存消息里留下了多种说法
 * （还带「不修改视频画面」「可继续绑定」等约束/引导句）。这些旧说法不会因为
 * 代码改动而消失，所以渲染前必须归一，并且同一状态只保留最新一条。
 * 归一只能作用于助手消息——用户自己的输入永远原样保留。
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

const appSource = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const copySource = readFileSync(new URL("../../static/ui-copy.js", import.meta.url), "utf8");
const workspaceSource = readFileSync(new URL("../../static/agent-workspace.js", import.meta.url), "utf8");

function extract(name) {
  const start = appSource.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return appSource.slice(start, appSource.indexOf("\n}", start) + 2);
}

function contextFor(names = []) {
  const window = {};
  const context = vm.createContext({ window });
  vm.runInContext(copySource, context);
  if (names.length) vm.runInContext(names.map(extract).join("\n"), context);
  return context;
}

// vm 里创建的数组来自另一个 realm，跨 realm 的深比较会失败；只比较字符串标量。
function textsOf(messages) {
  return Array.from(messages, (message) => String(message.text));
}

const LEGACY_TO_CANONICAL = [
  ["封面已保存；生成成片后可继续绑定", "封面已保存。"],
  ["封面已保存；本次只更新封面，不修改视频画面", "封面已保存。"],
  ["封面已保存；正在生成可下载成片", "封面已保存。"],
  ["封面已保存，并关联到 1 条当前成片；视频画面未改动", "封面已保存。"],
  ["封面已生成并保存为当前任务封面。点击下方按钮即可查看或下载。", "封面已保存。"],
  ["本次方案已执行完成，可查看对应结果。", "本次方案已执行完成。"],
  ["本次要求已完成，可以查看结果。", "本次要求已完成。"],
];

test("历史封面与方案完成消息归一为单句", () => {
  const { normalizeLegacyCopy } = contextFor().window.ClipTalkCopy;
  for (const [legacy, canonical] of LEGACY_TO_CANONICAL) {
    assert.equal(normalizeLegacyCopy(legacy), canonical, legacy);
  }
  // 未命中的文案必须原样返回，避免误伤普通消息。
  for (const untouched of ["封面已保存。", "视频《小米产品.mp4》已添加。", "本次方案已执行完成。"]) {
    assert.equal(normalizeLegacyCopy(untouched), untouched);
  }
});

test("同一状态文案在历史流里只保留最新一条", () => {
  const context = contextFor(["compactConversationMessages"]);
  const compacted = context.compactConversationMessages([
    { role: "assistant", kind: "result", text: "封面已保存；正在生成可下载成片", createdAt: "2026-09-23T07:01:51Z" },
    { role: "assistant", kind: "result", text: "封面已保存；生成成片后可继续绑定", createdAt: "2026-09-23T11:09:49Z" },
    { role: "assistant", kind: "result", text: "本次方案已执行完成，可查看对应结果。", createdAt: "2026-10-08T03:00:00Z" },
    { role: "assistant", kind: "result", text: "封面已保存；本次只更新封面，不修改视频画面", createdAt: "2026-10-09T03:43:44Z" },
  ]);
  assert.deepEqual(textsOf(compacted), ["本次方案已执行完成。", "封面已保存。"]);
  assert.equal(String(compacted[compacted.length - 1].createdAt), "2026-10-09T03:43:44Z");
});

test("归一不改写用户消息，也不误伤其它流程消息", () => {
  const context = contextFor(["compactConversationMessages"]);
  const compacted = context.compactConversationMessages([
    { role: "user", kind: "request", text: "封面已保存；生成成片后可继续绑定" },
    { role: "assistant", kind: "search-log", text: "内容检索已完成，我正在自动核定可用范围。" },
  ]);
  assert.deepEqual(textsOf(compacted), [
    "封面已保存；生成成片后可继续绑定",
    "内容检索已完成，我正在自动核定可用范围。",
  ]);
});

test("Agent 步骤结果与消息流都走同一份归一表", () => {
  assert.match(copySource, /normalizeLegacyCopy/);
  assert.match(appSource, /message\?\.role === "user" \? raw : legacyCopy\?\.normalizeLegacyCopy\?\.\(raw\)/);
  assert.match(workspaceSource, /function legacyCopyText\(value\)/);
  assert.match(workspaceSource, /legacyCopyText\(step\.error \|\| step\.result\?\.message/);
});
