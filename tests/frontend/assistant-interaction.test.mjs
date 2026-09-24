import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { chromium } from "playwright";

const source = readFileSync(new URL("../../static/agent-workspace.js", import.meta.url), "utf8");
const app = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");

test("an answer preserves input references and restores durable messages without creating a plan", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<section id="chatMessages"></section><form id="chatForm"><textarea id="chatInput">这里为什么不对</textarea><button id="sendButton">发送</button></form>`);
    await page.evaluate(() => {
      window.ClipTalkCurrentJobId = () => "job";
      window.ClipTalkCollectAssistantContext = () => ({ jobId: "job", capturedText: document.querySelector("#chatInput").value, timeDomain: "preview", viewer: { outputFilename: "v2.mp4" } });
      window.__messages = [];
      window.ClipTalkApi = {
        requestJson: async () => ({ workspace: { id: "ws", jobId: "job", messages: window.__messages }, plans: [] }),
        requestResponse: async (_path, options) => {
          window.__request = JSON.parse(options.body);
          window.__messages = [{ id: window.__request.clientMessageId, role: "user", text: window.__request.text }, { id: "reply", role: "assistant", text: "已有检查记录不足以确定原因。" }];
          return new Response('event: assistant.result\ndata: {"action":"answer","message":"已有检查记录不足以确定原因。"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
        },
      };
    });
    await page.addScriptTag({ content: source });
    await page.evaluate(() => window.ClipTalkAgentWorkspace.submitGoal(document.querySelector("#chatInput").value));
    const result = await page.evaluate(() => ({ request: window.__request, messages: window.ClipTalkAgentWorkspace.conversationMessages({ id: "job", messages: [] }) }));
    assert.equal(result.request.uiContext.capturedText, "这里为什么不对");
    assert.equal(result.request.uiContext.timeDomain, "preview");
    assert.equal(result.messages.length, 2);
    const restored = await page.evaluate(() => window.ClipTalkAgentWorkspace.conversationMessages({ id: "job", messages: [{ id: "earlier-same-text", role: "user", text: "这里为什么不对" }] }));
    assert.equal(restored.filter((m) => m.role === "user").length, 2, "Distinct messages with identical wording are not dropped");
    assert.ok(result.request.clientMessageId);
    assert.equal(await page.locator("#chatInput").isEnabled(), true);
    assert.equal(await page.locator("#chatInput").inputValue(), "");
  } finally { await browser.close(); }
});

test("network retry reuses message ID while a new instruction gets a new ID", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<section id="chatMessages"></section><textarea id="chatInput"></textarea><button id="sendButton">发送</button>`);
    await page.evaluate(() => {
      window.ClipTalkCurrentJobId = () => "job";
      window.__ids = [];
      window.ClipTalkApi = {
        requestJson: async () => ({ workspace: { id: "ws", jobId: "job" } }),
        requestResponse: async (_path, options) => { window.__ids.push(JSON.parse(options.body).clientMessageId); throw new Error("offline"); },
      };
    });
    await page.addScriptTag({ content: source });
    await page.evaluate(async () => {
      await window.ClipTalkAgentWorkspace.submitGoal("找到目标");
      await window.ClipTalkAgentWorkspace.submitGoal("找到目标");
      await window.ClipTalkAgentWorkspace.submitGoal("改成竖屏");
    });
    const ids = await page.evaluate(() => window.__ids);
    assert.equal(ids[0], ids[1]);
    assert.notEqual(ids[1], ids[2]);
  } finally { await browser.close(); }
});

test("composer guards IME and shares structured references", () => {
  assert.match(app, /!event\.isComposing && event\.keyCode !== 229/);
  assert.match(app, /ClipTalkCollectAssistantContext/);
  assert.match(app, /selected: \{ contentMatchIds: contentIds \}/);
  const revision = source.slice(source.indexOf("async function submitPlanRevision"), source.indexOf("async function resolveAction"));
  assert.doesNotMatch(revision, /\/cancel/);
  assert.match(source, /item\.planId === plan\?\.id/);
});
