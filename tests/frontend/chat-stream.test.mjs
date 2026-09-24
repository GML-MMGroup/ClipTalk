/**
 * chat-stream.js 单元测试
 *
 * 覆盖：
 *   1. 卡片按 id 幂等（重复 emit 不堆积）
 *   2. 内容未变化时不写 DOM（轮询不闪烁）
 *   3. 内容变化时更新卡片正文
 *   4. liveUpdate 定点更新字段
 *   5. finalize 的定稿语义
 *   6. 待处理条（action bar）的登记/清除与主操作回调
 *   7. 未读提示：非贴底时累计、贴底时清零
 *   8. 宿主被 innerHTML 摘掉后可重新挂回（renderConversation 重绘场景）
 *   9. legacyDock 逃生阀
 */
import assert from "node:assert/strict";
import test, { before, after } from "node:test";
import { chromium } from "playwright";
import { readFileSync } from "node:fs";

const STREAM_SOURCE = readFileSync(new URL("../../static/chat-stream.js", import.meta.url), "utf8");

let browser;
let page;

const SKELETON = `
  <aside class="chat-panel">
    <section id="chatMessages" style="height:200px;overflow:auto"></section>
    <form id="chatForm"></form>
  </aside>
`;

async function boot({ search = "" } = {}) {
  // 用路由拦截构造离线页面，避免依赖外部网络；同时保留 URL 查询参数能力。
  await page.unroute("**/*").catch(() => {});
  await page.route("**/*", (route) => route.fulfill({
    status: 200,
    contentType: "text/html",
    body: SKELETON,
  }));
  await page.goto(`https://stream.local/${search}`);
  await page.addScriptTag({ content: STREAM_SOURCE });
}

before(async () => {
  browser = await chromium.launch();
  page = await browser.newPage();
});

after(async () => {
  await browser?.close();
});

test("emit 创建卡片，且相同 id 重复 emit 不堆积", async () => {
  await boot();
  const result = await page.evaluate(() => {
    const cs = window.ClipTalkChatStream;
    cs.emit({ id: "plan:1", kind: "plan-card", html: "<p>第一版</p>" });
    cs.emit({ id: "plan:1", kind: "plan-card", html: "<p>第一版</p>" });
    cs.emit({ id: "plan:2", kind: "result", html: "<p>成片</p>" });
    return {
      count: cs._cards().length,
      domCount: document.querySelectorAll("#csStreamHost .cs-card").length,
      hostInMessages: Boolean(document.querySelector("#chatMessages #csStreamHost")),
    };
  });
  assert.equal(result.count, 2);
  assert.equal(result.domCount, 2);
  assert.equal(result.hostInMessages, true);
});

test("历史恢复不增加未读也不改变滚动位置，随后实时消息正常计数", async () => {
  await boot();
  const result = await page.evaluate(() => {
    const cs = window.ClipTalkChatStream;
    cs.restore(() => {
      for (let i = 0; i < 8; i++) cs.emit({ id: `history:${i}`, html: '<p style="height:100px">历史</p>' });
    });
    const root = document.querySelector('#chatMessages');
    root.scrollTop = 90;
    cs.restore(() => cs.emit({ id: 'history:9', html: '<p style="height:100px">恢复</p>' }));
    const top = root.scrollTop;
    const historicalUnread = document.querySelector('#csUnreadPill')?.hidden !== false;
    cs.emit({ id: 'live:1', html: '<p>新消息</p>' });
    return { top, historicalUnread, unread: document.querySelector('#csUnreadPill').textContent };
  });
  assert.equal(result.top, 90);
  assert.equal(result.historicalUnread, true);
  assert.match(result.unread, /1 条新消息/);
});

test("操作条轮询保留焦点，禁用理由可见，回调始终使用最新状态", async () => {
  await boot();
  const result = await page.evaluate(() => {
    const cs = window.ClipTalkChatStream;
    let count = 0;
    cs.action({ id: 'a', summary: '待核验', primaryLabel: '核验片段', onPrimary: () => { count = 1; } });
    const button = document.querySelector('[data-cs-action="primary"]');
    button.focus();
    cs.action({ id: 'a', summary: '待核验', primaryLabel: '核验片段', onPrimary: () => { count = 2; } });
    const preserved = button === document.activeElement;
    button.click();
    cs.action({ id: 'a', primaryLabel: '继续', disabled: true, reason: '请先完成核验', onPrimary: () => { count = 3; } });
    button.click();
    const reason = document.querySelector('[data-cs-action-reason]').textContent;
    cs.remove('a');
    return { preserved, count, reason, hidden: document.querySelector('#csActionBar').hidden };
  });
  assert.equal(result.preserved, true);
  assert.equal(result.count, 2);
  assert.equal(result.reason, '请先完成核验');
  assert.equal(result.hidden, true);
});

test("卡片焦点离开后补写轮询内容", async () => {
  await boot();
  await page.evaluate(() => {
    const cs = window.ClipTalkChatStream;
    cs.emit({ id: 'focused', html: '<button>旧内容</button>' });
    cs.cardElement('focused').querySelector('button').focus();
    cs.emit({ id: 'focused', html: '<p>最新内容</p>' });
    document.activeElement.blur();
  });
  assert.match(await page.locator('[data-cs-id="focused"]').textContent(), /最新内容/);
});

test("内容未变化时不重写 DOM，变化时才更新", async () => {
  await boot();
  const result = await page.evaluate(async () => {
    const cs = window.ClipTalkChatStream;
    cs.emit({ id: "plan:1", kind: "plan-card", html: "<p>稳定内容</p>" });
    const body = document.querySelector('[data-cs-id="plan:1"] .cs-card-body');
    let mutations = 0;
    const observer = new MutationObserver((records) => { mutations += records.length; });
    observer.observe(body, { childList: true, subtree: true, characterData: true });
    cs.emit({ id: "plan:1", kind: "plan-card", html: "<p>稳定内容</p>" });
    await new Promise((resolve) => setTimeout(resolve, 50));
    const afterSame = mutations;
    cs.emit({ id: "plan:1", kind: "plan-card", html: "<p>阶段推进了</p>" });
    await new Promise((resolve) => setTimeout(resolve, 50));
    observer.disconnect();
    return { afterSame, afterChange: mutations, text: body.textContent };
  });
  assert.equal(result.afterSame, 0, "相同内容不应触发 DOM 变更");
  assert.ok(result.afterChange > 0, "内容变化应更新 DOM");
  assert.match(result.text, /阶段推进了/);
});

test("liveUpdate 定点更新字段文本与进度条", async () => {
  await boot();
  const result = await page.evaluate(() => {
    const cs = window.ClipTalkChatStream;
    cs.emit({
      id: "plan:9",
      kind: "executing",
      html: `<strong data-cs-field="step">开始</strong><div data-cs-field="percent" role="progressbar" data-cs-value="0"><i data-cs-bar style="width:0%"></i></div>`,
    });
    cs.liveUpdate("plan:9", {
      step: { text: "分析镜头 3/8" },
      percent: { value: 42 },
    });
    const card = document.querySelector('[data-cs-id="plan:9"]');
    return {
      step: card.querySelector('[data-cs-field="step"]').textContent,
      value: card.querySelector('[data-cs-field="percent"]').dataset.csValue,
      width: card.querySelector("[data-cs-bar]").style.width,
    };
  });
  assert.equal(result.step, "分析镜头 3/8");
  assert.equal(result.value, "42");
  assert.equal(result.width, "42%");
});

test("finalize 标记定稿并移除 aria-busy", async () => {
  await boot();
  const result = await page.evaluate(() => {
    const cs = window.ClipTalkChatStream;
    cs.emit({ id: "plan:1", kind: "executing", html: "<p>执行中</p>" });
    const before = document.querySelector('[data-cs-id="plan:1"] .cs-card-body').getAttribute("aria-busy");
    cs.finalize("plan:1");
    const card = document.querySelector('[data-cs-id="plan:1"]');
    return { before, final: card.dataset.csFinal, after: card.querySelector(".cs-card-body").getAttribute("aria-busy") };
  });
  assert.equal(result.before, "true");
  assert.equal(result.final, "true");
  assert.equal(result.after, null);
});

test("待处理条：登记后显示，主操作回调可触发，清除后隐藏", async () => {
  await boot();
  const result = await page.evaluate(async () => {
    const cs = window.ClipTalkChatStream;
    let fired = 0;
    cs.emit({ id: "plan:5", kind: "plan-card", html: "<p>计划</p>" });
    cs.action({ id: "plan:5", summary: "计划待确认", primaryLabel: "确认并开始", onPrimary: () => { fired += 1; } });
    const bar = document.getElementById("csActionBar");
    const visible = !bar.classList.contains("hidden");
    const summary = bar.querySelector("[data-cs-action-summary]")?.textContent;
    bar.querySelector('[data-cs-action="primary"]').click();
    await new Promise((resolve) => setTimeout(resolve, 20));
    const firedCount = fired;
    cs.clearAction("plan:5");
    return { visible, summary, firedCount, hiddenAfter: bar.classList.contains("hidden") };
  });
  assert.equal(result.visible, true);
  assert.equal(result.summary, "计划待确认");
  assert.equal(result.firedCount, 1);
  assert.equal(result.hiddenAfter, true);
});

test("未读提示：非贴底时累计，回到底部后清零", async () => {
  await boot();
  const result = await page.evaluate(async () => {
    const cs = window.ClipTalkChatStream;
    const messages = document.getElementById("chatMessages");
    messages.innerHTML = "<div style='height:800px'></div>";
    messages.append(cs.hostElement());
    messages.scrollTop = 0;
    await new Promise((resolve) => setTimeout(resolve, 20));
    cs.emit({ id: "plan:1", kind: "executing", html: "<p>步骤 1</p>" });
    cs.emit({ id: "plan:2", kind: "result", html: "<p>成片</p>" });
    const pill = document.getElementById("csUnreadPill");
    const visible = !pill.classList.contains("hidden");
    const label = pill.textContent;
    cs.scrollToBottom("auto");
    await new Promise((resolve) => setTimeout(resolve, 120));
    return { visible, label, hiddenAfterScroll: pill.classList.contains("hidden") };
  });
  assert.equal(result.visible, true);
  assert.match(result.label, /条新消息/);
  assert.equal(result.hiddenAfterScroll, true);
});

test("宿主被 innerHTML 摘掉后可以重新挂回（对话重绘场景）", async () => {
  await boot();
  const result = await page.evaluate(() => {
    const cs = window.ClipTalkChatStream;
    cs.emit({ id: "plan:1", kind: "plan-card", html: "<p>内容</p>" });
    const messages = document.getElementById("chatMessages");
    const hostRef = cs.hostElement();
    messages.innerHTML = "<article class='chat-message'>历史消息</article>";
    // 整体重绘会把宿主摘掉；此时还不能调用 hostElement()，它会自动挂回。
    const detached = hostRef.parentElement !== messages;
    cs.hostElement();
    const reattached = Boolean(messages.querySelector("#csStreamHost"));
    const keptText = messages.querySelector("#csStreamHost").textContent;
    return { detached, reattached, keptText };
  });
  assert.equal(result.detached, true, "整体重绘后宿主应被摘掉");
  assert.equal(result.reattached, true);
  assert.match(result.keptText, /内容/, "卡片内容不应丢失");
});

test("查看详情只滚动聊天区，已可见卡片不移动任何容器", async () => {
  await boot();
  await page.emulateMedia({ reducedMotion: "reduce" });
  const result = await page.evaluate(() => {
    const cs = window.ClipTalkChatStream;
    const panel = document.querySelector(".chat-panel");
    const shell = document.createElement("main");
    shell.style.cssText = "height:160px;overflow:hidden;padding-top:60px";
    panel.before(shell);
    shell.append(panel);
    cs.emit({ id: "first", html: '<div style="height:40px">第一张</div>' });
    cs.emit({ id: "middle", html: '<div style="height:400px">长卡片</div>' });
    cs.emit({ id: "last", html: '<div style="height:40px">最后一张</div>' });
    const chat = document.querySelector("#chatMessages");
    chat.scrollTop = 0;
    shell.scrollTop = 0;
    cs.focusCard("last");
    const afterBelow = { shell: shell.scrollTop, chat: chat.scrollTop };
    cs.focusCard("last");
    const afterVisible = { shell: shell.scrollTop, chat: chat.scrollTop };
    cs.focusCard("middle");
    const largeTop = cs.cardElement("middle").getBoundingClientRect().top - chat.getBoundingClientRect().top;
    cs.focusCard("first");
    return {
      afterBelow, afterVisible, largeTop,
      shellAfter: shell.scrollTop, chatAfter: chat.scrollTop,
      focused: document.activeElement === cs.cardElement("first"),
      flash: cs.cardElement("first").classList.contains("cs-flash"),
    };
  });
  assert.equal(result.afterBelow.shell, 0);
  assert.ok(result.afterBelow.chat > 0);
  assert.deepEqual(result.afterVisible, result.afterBelow);
  assert.ok(Math.abs(result.largeTop) < 1);
  assert.equal(result.shellAfter, 0);
  assert.equal(result.chatAfter, 0);
  assert.equal(result.focused, true);
  assert.equal(result.flash, true);
  await page.emulateMedia({ reducedMotion: "no-preference" });
});

test("?legacyDock=1 打开逃生阀", async () => {
  await boot({ search: "?legacyDock=1" });
  const enabled = await page.evaluate(() => window.ClipTalkChatStream.legacyDockEnabled());
  assert.equal(enabled, true);
  await boot();
  const disabled = await page.evaluate(() => window.ClipTalkChatStream.legacyDockEnabled());
  assert.equal(disabled, false);
});
