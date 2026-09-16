import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { chromium } from "playwright";

const css = readFileSync(new URL("../../static/workbench.css", import.meta.url), "utf8");
const runtime = readFileSync(new URL("../../static/workspace-controller.js", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const html = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
const productionCss = [...html.matchAll(/href="\/static\/([^"?]+\.css)/g)]
  .map((match) => readFileSync(new URL(`../../static/${match[1]}`, import.meta.url), "utf8"))
  .join("\n");

function contrastRatio(foreground, background) {
  const channels = (value) => {
    const hex = String(value).trim().match(/^#([\da-f]{6})$/i)?.[1];
    if (hex) return [0, 2, 4].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16));
    return (String(value).match(/[\d.]+/g) || []).slice(0, 3).map(Number);
  };
  const luminance = (value) => {
    const [red, green, blue] = channels(value).map((channel) => {
      const normalized = channel / 255;
      return normalized <= .04045 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4;
    });
    return .2126 * red + .7152 * green + .0722 * blue;
  };
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + .05) / (darker + .05);
}

test("expanded Agent plan stays inside its row instead of covering messages", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 760 } });
  try {
    await page.setContent(`<!doctype html><html data-theme="light"><style>*,*::before,*::after{box-sizing:border-box;transition:none!important}${productionCss}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace" data-shell-view="workspace">
        <main id="workspace" class="studio director-merged" style="height:760px">
          <aside id="assistantPanel" class="chat-panel">
            <header class="panel-header"><div class="director"><strong>AI 剪辑助手</strong></div></header>
            <section id="agentPlanDock" class="agent-plan-dock" data-tone="ready">
              <header><small>当前剪辑方案</small><b>待确认方案</b></header>
              <details class="assistant-plan-summary" open>
                <summary>等待确认计划</summary>
                <article class="agent-understanding-card"><header><strong>Agent 理解</strong></header><dl>
                  ${Array.from({ length: 14 }, (_, index) => `<div><dt>项目 ${index + 1}</dt><dd>这是一段用于验证长方案不会越界覆盖消息区的剪辑计划说明。</dd></div>`).join("")}
                </dl></article>
              </details>
              <footer><button>执行详情</button><button class="primary">确认并开始</button></footer>
            </section>
            <section id="chatMessages"><article class="chat-message"><div class="bubble">聊天消息仍然可以滚动查看</div></article></section>
            <aside id="autoCompositionDock" class="hidden"></aside>
            <section id="assistantActionDock" class="assistant-action-dock hidden"></section>
            <form id="chatForm" class="chat-composer"><div class="chat-input-shell"><textarea id="chatInput"></textarea></div><small>Enter 发送</small></form>
          </aside>
        </main>
      </body></html>`);
    const geometry = await page.evaluate(() => {
      const box = (selector) => document.querySelector(selector).getBoundingClientRect();
      const plan = box("#agentPlanDock");
      const summary = box("#agentPlanDock .assistant-plan-summary");
      const footer = box("#agentPlanDock > footer");
      const messages = box("#chatMessages");
      const form = box("#chatForm");
      return {
        planTop: plan.top, planBottom: plan.bottom, planHeight: plan.height,
        summaryHeight: summary.height, summaryScrollHeight: document.querySelector("#agentPlanDock .assistant-plan-summary").scrollHeight,
        footerBottom: footer.bottom, messagesTop: messages.top, messagesBottom: messages.bottom, formTop: form.top,
      };
    });
    assert.ok(geometry.planHeight <= 430, `方案卡高度失控：${geometry.planHeight}`);
    assert.ok(geometry.summaryScrollHeight > geometry.summaryHeight, "长方案应在卡片内部滚动");
    assert.ok(geometry.footerBottom <= geometry.planBottom + 1, "方案操作栏越出了方案卡");
    assert.ok(geometry.planBottom <= geometry.messagesTop + 1, "方案卡覆盖了消息区");
    assert.ok(geometry.messagesBottom <= geometry.formTop + 1, "消息区覆盖了输入框");
  } finally {
    await browser.close();
  }
});

test("journey and delivery keep actions bound to the displayed version", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  try {
    await page.setContent(fixture());
    await page.evaluate(() => {
      const output = { filename: "v2.mp4", title: "竖屏正式版", duration: 87, width: 540, height: 960, segments: [{ start: 1, end: 4 }], kept: false };
      const version = { id: "v2", number: 2, outputs: [output] };
      const job = { id: "delivery-test", status: "completed", presentation: { key: "exported", journeyStage: 4, journeyDetail: "正式文件已生成" }, outputVersions: [version] };
      window.ClipTalkCurrentJobSnapshot = () => job;
      window.ClipTalkCurrentOutputSnapshot = () => ({ mediaKind: "source", output: null });
      window.ClipTalkOrderedJobOutputs = () => [{ item: output, version }];
      window.reviewActions = [];
      window.ClipTalkVersionAction = async (filename, action) => {
        window.reviewActions.push({ filename, action });
        if (action === "keep") output.kept = true;
        return { ok: true };
      };
      const save = document.createElement("button");
      save.id = "saveToLibraryButton";
      document.body.append(save);
      window.ClipTalkWorkspaceController.mount();
    });
    assert.equal(await page.locator('#ctTaskJourney [aria-current="step"]').textContent(), "5 生成与交付");
    const journeySummary = page.locator("#ctTaskJourney .ct-journey-summary");
    assert.match(await journeySummary.textContent(), /5 \/ 5.*生成与交付/s);
    assert.equal(await journeySummary.getAttribute("aria-expanded"), "false");
    assert.equal(await page.locator("#ctTaskJourneyDetails").isHidden(), true);
    await journeySummary.click();
    assert.equal(await journeySummary.getAttribute("aria-expanded"), "true");
    assert.equal(await page.locator("#ctTaskJourneyDetails").isVisible(), true);
    const journeyGeometry = await page.evaluate(() => {
      const header = document.querySelector("#assistantPanel > .panel-header").getBoundingClientRect();
      const journey = document.querySelector("#ctTaskJourney").getBoundingClientRect();
      const messages = document.querySelector("#chatMessages").getBoundingClientRect();
      return { headerBottom: header.bottom, journeyBottom: journey.bottom, messagesTop: messages.top };
    });
    assert.ok(journeyGeometry.headerBottom + 1 >= journeyGeometry.journeyBottom);
    assert.ok(journeyGeometry.messagesTop + 1 >= journeyGeometry.headerBottom);
    await journeySummary.click();
    await page.evaluate(() => window.ClipTalkWorkspaceController.openRail('materials'));
    await page.locator("[data-ct-version-edit]").click();
    const card = page.locator("#ctV4MaterialsSummary");
    assert.match(await card.textContent(), /V2.*1:27/s);
    for (const theme of ["light", "dark"]) {
      await page.locator("html").evaluate((node, value) => { node.dataset.theme = value; }, theme);
      await page.waitForTimeout(400);
      const fits = await card.evaluate((node) => {
        const rect = node.getBoundingClientRect();
        return rect.left >= 0 && rect.right <= innerWidth;
      });
      assert.equal(fits, true);
      await page.screenshot({ path: `/tmp/cliptalk-delivery-${theme}.png` });
    }
    assert.equal(await page.locator("[data-ct-v4-export]").count(), 0);
    assert.deepEqual(await card.locator("footer button").allTextContents(), ["播放成片", "全部版本"]);
    await page.locator("#saveToLibraryButton").click();
    await page.evaluate(() => window.ClipTalkWorkspaceController.syncMaterialsSummary());
    assert.match(await card.textContent(), /已长期保留/);
    assert.deepEqual(await page.evaluate(() => window.reviewActions), [
      { filename: "v2.mp4", action: "edit" }, { filename: "v2.mp4", action: "keep" },
    ]);
    for (const [key, text] of [["failed", "任务未完成"], ["no_result", "未找到匹配内容"], ["cancelled", "已停止"]]) {
      await page.evaluate(({ key, text }) => {
        Object.assign(window.ClipTalkCurrentJobSnapshot().presentation, { key, journeyStage: 3, journeyDetail: text, attentionItems: [{ label: text, target: "#agentPlanDock" }] });
        window.ClipTalkWorkspaceController.mount();
      }, { key, text });
      assert.match(await page.locator("#ctTaskJourney p").textContent(), new RegExp(text));
      await page.locator("#ctV4Notifications").click();
      assert.equal(await page.getByRole("dialog", { name: "待处理事项", exact: true }).isVisible(), true);
      await page.getByRole("dialog", { name: "待处理事项", exact: true }).getByRole("button", { name: "关闭", exact: true }).click();
    }
  } finally { await browser.close(); }
});

test("timeline preview defers verbose evidence until the explicit evidence action", () => {
  assert.match(appSource, /previewContentMatch\(item, \{ autoplay: true, loadEvidence: false,/);
  assert.match(appSource, /function previewContentMatch\(match, \{ autoplay = true, loadEvidence = false,/);
  assert.match(appSource, /previewContentMatch\(match, \{ autoplay, loadEvidence: true, searchId \}\);/);
});

test("light version overview keeps version cards and actions on light surfaces", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.setContent(`<!doctype html><html data-theme="light"><style>*,*::before,*::after{box-sizing:border-box}${productionCss}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace"><main id="workspace" class="studio director-merged">
        <aside id="reviewRail"><section id="ctV4MaterialsSummary" data-view="versions"><section id="ctV4VersionList">
          <header><button type="button">返回概览</button><strong>全部版本</strong></header>
          <div id="clipStrip"><div class="clip-version-entry quality-needs_review kind-formal">
            <button type="button" class="auto-version-button clip-version-button active" aria-pressed="true"><i class="clip-version-index">V1</i><span><strong>内容视频</strong><em>质量待确认</em></span><small>11 个片段 · 119.4 秒 · 69 分</small></button>
            <div class="clip-version-actions"><a class="output-version-download clip-version-download" href="#">下载 MP4</a><button type="button" class="clip-version-edit">编辑此版本</button></div>
          </div></div>
        </section></section></aside>
      </main></body></html>`);
    const palette = await page.evaluate(() => {
      const read = (selector) => {
        const style = getComputedStyle(document.querySelector(selector));
        return { color: style.color, background: style.backgroundColor, image: style.backgroundImage };
      };
      return {
        card: read(".clip-version-button"),
        title: read(".clip-version-button strong"),
        meta: read(".clip-version-button > small"),
        download: read(".output-version-download"),
        edit: read(".clip-version-edit"),
        back: read("[data-theme] #ctV4VersionList > header > button"),
      };
    });
    assert.deepEqual(palette.card, { color: "rgb(32, 56, 44)", background: "rgb(232, 239, 232)", image: "none" });
    assert.ok(contrastRatio(palette.title.color, palette.card.background) >= 4.5);
    assert.ok(contrastRatio(palette.meta.color, palette.card.background) >= 4.5);
    assert.deepEqual(palette.download, { color: "rgb(247, 251, 247)", background: "rgb(53, 93, 72)", image: "none" });
    assert.deepEqual(palette.edit, { color: "rgb(53, 88, 70)", background: "rgb(255, 255, 255)", image: "none" });
    assert.equal(palette.back.background, "rgb(247, 248, 245)");
  } finally {
    await browser.close();
  }
});

test("light hidden workflow surfaces do not reintroduce dark theme islands", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  try {
    await page.setContent(`<!doctype html><html data-theme="light"><style>*,*::before,*::after{box-sizing:border-box;transition:none!important}${productionCss}</style>
      <body class="ct-workbench-v4 single-timeline-workspace" data-shell-mode="workspace" data-shell-view="workspace">
        <main id="workspace" class="studio director-merged new-task-workbench">
          <aside id="assistantPanel" class="chat-panel"><div id="chatMessages">
            <article class="chat-message"><div class="bubble"><div class="agent-goal-tags"><span>竖屏</span></div></div></article>
            <section class="auto-compose-result-card"><button class="auto-version-button">V1 · 内容视频</button></section>
            <section class="edit-proposal-card"><header><strong>修改建议</strong></header><p>调整片段顺序</p></section>
          </div><section id="agentPlanDock" class="agent-plan-dock"><section class="agent-planning-live-track"><header><strong>读取素材状态</strong></header><div class="agent-planning-live-bar"><i></i></div></section></section></aside>
          <aside id="reviewRail"><section class="quality-gate-result-card"><strong>质量待确认</strong><ul class="quality-issue-list"><li><span>主要</span><div><p>字幕可能遮挡人物</p></div></li></ul></section></aside>
          <section id="reviewView"><section id="reviewWorkbench" class="review-workbench">
            <aside class="voice-profile-panel"><article class="current-voice-card"><header><strong>Speaker A</strong></header></article><div class="current-voice-actions">操作</div><details class="cross-video-voice-section"><summary>跨视频查找</summary></details></aside>
            <aside class="person-profile-panel"><article class="current-person-card"><div class="current-person-copy"><strong>人物 1</strong></div></article></aside>
          </section><section id="timelinePanel"></section></section>
        </main>
        <aside id="agentPlanDrawer" class="agent-plan-drawer"><section class="agent-cover-result"><button data-agent-cover-open><span><strong>当前封面</strong></span></button><section class="agent-cover-timeline"><div class="agent-cover-timeline-track"><article class="video"><span><b>视频</b></span></article></div></section></section></aside>
        <section class="subtitle-review"><aside class="subtitle-review-panel"><header class="subtitle-review-header"><p>检查字幕</p><button class="subtitle-review-close">×</button></header><section class="subtitle-command-card"><div class="subtitle-section-heading"><strong>智能修改</strong></div></section><article class="subtitle-cue">字幕内容</article></aside></section>
        <div class="input-prompt"><form class="input-prompt-card"><header><button>×</button></header><label>内容<input></label></form></div>
        <article class="home-project-card"><details class="shell-task-menu" open><summary>…</summary><div><button>删除任务</button></div></details></article>
        <div class="viewer-shell"><section class="output-evidence-strip"><details class="output-evidence-popover" open><summary>生成依据</summary><div class="output-evidence-popover-body"><strong>版本依据</strong><p>已核对所选片段</p></div></details></section></div>
      </body></html>`);
    const audit = await page.evaluate(() => {
      const read = (selector) => {
        const style = getComputedStyle(document.querySelector(selector));
        return { color: style.color, background: style.backgroundColor, image: style.backgroundImage };
      };
      return {
        plan: read(".agent-planning-live-track header strong"),
        planSurface: read("#agentPlanDock"),
        planBar: read(".agent-planning-live-bar"),
        quality: read(".quality-gate-result-card"),
        qualityTitle: read(".quality-gate-result-card > strong"),
        voice: read(".current-voice-card"),
        voiceTitle: read(".current-voice-card strong"),
        person: read(".current-person-card"),
        personTitle: read(".current-person-card strong"),
        cover: read(".agent-cover-result"),
        coverTitle: read(".agent-cover-result [data-agent-cover-open] strong"),
        subtitleCommand: read(".subtitle-command-card"),
        subtitleTitle: read(".subtitle-command-card strong"),
        prompt: read(".input-prompt-card"),
        promptLabel: read(".input-prompt-card label"),
        autoVersion: read(".auto-compose-result-card .auto-version-button"),
        proposal: read(".edit-proposal-card"),
        proposalTitle: read(".edit-proposal-card strong"),
        taskMenu: read(".shell-task-menu > div"),
        taskMenuAction: read(".shell-task-menu > div button"),
        evidence: read(".output-evidence-popover-body"),
        evidenceTitle: read(".output-evidence-popover-body strong"),
      };
    });
    for (const key of ["quality", "voice", "person", "cover", "subtitleCommand", "prompt", "autoVersion", "proposal", "taskMenu"]) {
      assert.ok(!/^rgba?\((?:[0-5]?\d),\s*(?:[0-5]?\d),\s*(?:[0-5]?\d)/.test(audit[key].background), `${key}仍为深色表面：${audit[key].background}`);
      assert.equal(audit[key].image, "none", `${key}仍带有深色背景图层`);
    }
    assert.equal(audit.planBar.background, "rgb(226, 231, 226)");
    assert.equal(audit.evidence.background, "rgba(255, 255, 255, 0.98)");
    for (const [name, foreground, background] of [
      ["规划阶段", audit.plan.color, audit.planSurface.background],
      ["质量标题", audit.qualityTitle.color, audit.quality.background],
      ["说话人标题", audit.voiceTitle.color, audit.voice.background],
      ["人物标题", audit.personTitle.color, audit.person.background],
      ["封面标题", audit.coverTitle.color, audit.cover.background],
      ["字幕标题", audit.subtitleTitle.color, audit.subtitleCommand.background],
      ["补充信息标签", audit.promptLabel.color, audit.prompt.background],
      ["修改建议标题", audit.proposalTitle.color, audit.proposal.background],
      ["任务菜单操作", audit.taskMenuAction.color, audit.taskMenu.background],
      ["生成依据标题", audit.evidenceTitle.color, audit.evidence.background],
    ]) assert.ok(contrastRatio(foreground, background) >= 4.5, `${name}对比度不足：${foreground} / ${background}`);
  } finally {
    await browser.close();
  }
});

test("timeline resize observer compares stable like-for-like geometry", () => {
  assert.match(appSource, /const nextTrackBounds = \(timelineTrackContent \|\| timelineViewport\)\?\.getBoundingClientRect\(\)/);
  assert.match(appSource, /const nextViewportBounds = \(timelineViewport \|\| timelineTrackContent\)\?\.getBoundingClientRect\(\)/);
  assert.match(appSource, /const nextLayoutHeight = Math\.max\(190, Math\.round\(nextViewportBounds\?\.height \|\| 0\)\)/);
  assert.doesNotMatch(appSource, /const nextLayoutBounds = \(timelineTrackContent \|\| timelineViewport\)/);
});

test("light timeline keeps every text layer readable", async () => {
  assert.match(appSource, /window\.addEventListener\("cliptalk:themechange"[\s\S]*?drawWaveform\(true\)/);
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.setContent(`<!doctype html><html data-theme="light"><style>*,*::before,*::after{box-sizing:border-box}${css}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace"><main id="workspace" class="studio"><section id="reviewView">
        <section id="timelinePanel" class="timeline-panel">
          <header><div class="timeline-heading"><strong>审核样片时间轴</strong><span>点击片段继续播放样片</span></div>
            <section class="timeline-event-summary"><div><small>审核样片</small><strong>多辆汽车出现</strong></div><p>按最终播放顺序显示</p><span>3 个镜头</span></section>
            <div class="timeline-review-controls"><b><small>样片</small><span>00:12</span> / <span>01:32</span></b></div></header>
          <div class="timeline-toolbar"><div class="timeline-tool-group"><button type="button">适应全片</button></div></div>
          <div id="timelineOverview" class="timeline-overview"></div>
          <div id="timelineViewport" class="timeline-viewport"><div id="timelineTrackLabels" class="timeline-track-labels"><span data-track-kind="content">事件</span><span data-track-kind="audio">音频</span></div>
            <div id="timelineTrackContent" class="timeline-track-content"><button class="timeline-label"><b>E1</b><span>多辆汽车出现</span><em>已采用</em></button><canvas id="waveformCanvas"></canvas></div></div>
          <footer><span>高光镜头</span></footer>
        </section></section></main></body></html>`);
    const audit = await page.evaluate(() => {
      const style = (selector) => getComputedStyle(document.querySelector(selector));
      const pair = (name, foregroundSelector, backgroundSelector) => ({
        name,
        foreground: style(foregroundSelector).color,
        background: style(backgroundSelector).backgroundColor,
      });
      return {
        pairs: [
          pair("标题", ".timeline-heading strong", "#timelinePanel > header"),
          pair("说明", ".timeline-heading span", "#timelinePanel > header"),
          pair("摘要标签", ".timeline-event-summary small", ".timeline-event-summary"),
          pair("摘要标题", ".timeline-event-summary strong", ".timeline-event-summary"),
          pair("摘要正文", ".timeline-event-summary p", ".timeline-event-summary"),
          pair("时间码", ".timeline-review-controls b", "#timelinePanel > header"),
          pair("工具按钮", ".timeline-toolbar button", ".timeline-toolbar button"),
          pair("轨道名称", "#timelineTrackLabels span", "#timelineTrackLabels"),
          pair("音频轨道", "#timelineTrackLabels [data-track-kind='audio']", "#timelineTrackLabels"),
          pair("镜头标题", ".timeline-label span", ".timeline-label"),
          pair("底部图例", "#timelinePanel > footer span", "#timelinePanel > footer"),
        ],
        rulerColor: style("#timelineViewport").getPropertyValue("--timeline-ruler-text").trim(),
        viewportBackground: style("#timelineViewport").backgroundColor,
        waveformBlend: style("#waveformCanvas").mixBlendMode,
      };
    });
    for (const item of audit.pairs) {
      assert.ok(contrastRatio(item.foreground, item.background) >= 4.5, `${item.name}对比度不足：${item.foreground} / ${item.background}`);
    }
    assert.ok(contrastRatio(audit.rulerColor, audit.viewportBackground) >= 4.5);
    assert.equal(audit.waveformBlend, "multiply");
  } finally {
    await browser.close();
  }
});

test("light version editor uses a light media matte without dimming thumbnails", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.setContent(`<!doctype html><html data-theme="light"><style>${productionCss}</style>
      <body class="secondary-editor-open" data-shell-mode="workspace">
        <section id="secondaryEditor" class="secondary-editor secondary-editor-v2">
          <div class="secondary-editor-player"><video></video></div>
          <div class="secondary-timeline-clip" style="width:400px;height:120px">
            <span class="secondary-clip-media"><i class="secondary-clip-frame"><svg viewBox="0 0 16 9"></svg></i></span>
            <span class="secondary-clip-copy"><strong>片段标题</strong><small>1.2 秒</small><em>源片 00:01</em></span>
          </div>
        </section>
      </body></html>`);
    const palette = await page.evaluate(() => ({
      player: getComputedStyle(document.querySelector(".secondary-editor-player")).backgroundColor,
      video: getComputedStyle(document.querySelector(".secondary-editor-player video")).backgroundColor,
      frameOpacity: getComputedStyle(document.querySelector(".secondary-clip-media > i")).opacity,
      frameFilter: getComputedStyle(document.querySelector(".secondary-clip-media > i")).filter,
      frameHeight: document.querySelector(".secondary-clip-frame").getBoundingClientRect().height,
      svgHeight: document.querySelector(".secondary-clip-frame > svg").getBoundingClientRect().height,
      mediaBackground: getComputedStyle(document.querySelector(".secondary-clip-media")).backgroundColor,
      overlay: getComputedStyle(document.querySelector(".secondary-clip-media"), "::after").backgroundImage,
      clipWidth: document.querySelector(".secondary-timeline-clip").getBoundingClientRect().width,
      labelWidth: document.querySelector(".secondary-clip-copy > strong").getBoundingClientRect().width,
    }));
    assert.equal(palette.player, "rgb(231, 235, 231)");
    assert.equal(palette.video, "rgba(0, 0, 0, 0)");
    assert.equal(palette.frameOpacity, "1");
    assert.match(palette.frameFilter, /brightness\(1\.01\)/);
    assert.equal(palette.svgHeight, palette.frameHeight);
    assert.equal(palette.mediaBackground, "rgb(223, 229, 223)");
    assert.equal(palette.overlay, "none");
    assert.ok(palette.labelWidth < palette.clipWidth / 2);
  } finally {
    await browser.close();
  }
});

test("materials cards and timeline thumbnails keep theme-appropriate contrast", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.setContent(`<!doctype html><html data-theme="dark"><style>*,*::before,*::after{box-sizing:border-box;transition:none!important}${productionCss}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace"><main id="workspace" class="studio">
        <aside id="reviewRail" class="review-rail"><section id="ctV4MaterialsSummary" class="ct-v4-materials-summary">
          <article class="ct-v4-context-card ct-v4-candidates-card is-adopted"><header><span>2</span><strong>已采用片段</strong></header>
            <div class="ct-v4-candidate-preview ct-v4-adopted-preview"><button><span class="ct-v4-adopted-copy"><strong>出现小米 logo</strong><small>4:33–4:41</small></span></button></div>
          </article>
        </section></aside>
        <section id="timelinePanel" class="timeline-panel"><div id="timelineViewport" class="timeline-viewport"><div class="timeline-thumbnails"><button class="timeline-thumbnail black-frame"></button><button class="timeline-thumbnail blurred-frame"></button></div></div></section>
      </main></body></html>`);
    const snapshot = () => page.evaluate(() => {
      const style = (selector) => getComputedStyle(document.querySelector(selector));
      return {
        cardImage: style(".ct-v4-candidates-card.is-adopted").backgroundImage,
        title: style(".ct-v4-adopted-copy strong").color,
        itemBackground: style(".ct-v4-adopted-preview > button").backgroundColor,
        blackOpacity: style(".timeline-thumbnail.black-frame").opacity,
        blackFilter: style(".timeline-thumbnail.black-frame").filter,
        blurredOpacity: style(".timeline-thumbnail.blurred-frame").opacity,
      };
    });
    const dark = await snapshot();
    assert.match(dark.cardImage, /rgb\(29, 57, 52\)/);
    assert.equal(dark.title, "rgb(245, 247, 244)");

    await page.locator("html").evaluate((node) => { node.dataset.theme = "light"; });
    await page.waitForTimeout(250);
    const light = await snapshot();
    assert.match(light.cardImage, /rgb\(237, 244, 238\)/);
    assert.equal(light.title, "rgb(29, 41, 36)");
    assert.equal(light.blackOpacity, "1");
    assert.match(light.blackFilter, /brightness\(0\.7\)/);
    assert.equal(light.blurredOpacity, "1");
  } finally {
    await browser.close();
  }
});

test("collapsed review rail stays light and readable in the light theme", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  try {
    await page.setContent(`<!doctype html><html data-theme="light"><style>*,*::before,*::after{box-sizing:border-box}${css}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace">
        <main id="workspace" class="studio review-rail-collapsed">
          <aside id="appSidebar"></aside><aside id="assistantPanel"></aside><i></i><section class="review-panel"></section><i></i>
          <aside id="reviewRail" class="review-rail">
            <button id="ctV4ReviewRailToggle" class="ct-v4-review-rail-toggle has-activity" type="button" aria-label="展开素材与结果"><span aria-hidden="true">‹</span><b>结果</b><i aria-hidden="true"></i></button>
          </aside>
        </main>
      </body></html>`);
    await page.waitForTimeout(250);
    const initial = await page.evaluate(() => {
      const style = (selector) => getComputedStyle(document.querySelector(selector));
      return {
        rail: {
          width: style("#reviewRail").width,
          background: style("#reviewRail").backgroundColor,
          image: style("#reviewRail").backgroundImage,
        },
        buttonBackground: style("#ctV4ReviewRailToggle").backgroundColor,
        icon: {
          foreground: style("#ctV4ReviewRailToggle > span").color,
          background: style("#ctV4ReviewRailToggle > span").backgroundColor,
        },
        label: {
          foreground: style("#ctV4ReviewRailToggle > b").color,
          background: style("#reviewRail").backgroundColor,
        },
        activity: style("#ctV4ReviewRailToggle > i").backgroundColor,
      };
    });
    assert.equal(initial.rail.width, "52px");
    assert.equal(initial.rail.background, "rgb(243, 243, 240)");
    assert.equal(initial.rail.image, "none");
    assert.equal(initial.buttonBackground, "rgba(0, 0, 0, 0)");
    assert.ok(contrastRatio(initial.icon.foreground, initial.icon.background) >= 4.5);
    assert.ok(contrastRatio(initial.label.foreground, initial.label.background) >= 4.5);
    assert.equal(initial.activity, "rgb(53, 93, 72)");

    await page.locator("#ctV4ReviewRailToggle").hover();
    await page.waitForTimeout(250);
    const hoveredIconBackground = await page.locator("#ctV4ReviewRailToggle > span").evaluate((node) => getComputedStyle(node).backgroundColor);
    assert.equal(hoveredIconBackground, "rgb(229, 238, 231)");
  } finally {
    await browser.close();
  }
});

test("timeline keeps its footer visible and scrolls lanes instead of clipping them", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  try {
    await page.setContent(`<!doctype html><html data-theme="light"><style>*,*::before,*::after{box-sizing:border-box}${productionCss}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace">
        <main id="workspace" class="studio director-merged">
          <aside id="appSidebar"></aside><aside id="assistantPanel"></aside><i></i>
          <section id="reviewView" class="review-panel glass-panel review-view">
            <header class="review-header"></header>
            <section id="reviewStage" class="review-stage"><div id="viewerShell" class="viewer-shell"></div></section>
            <nav id="ctEditorToolbar" class="ct-editor-toolbar"></nav>
            <section id="timelinePanel" class="timeline-panel">
              <header><div class="timeline-heading"><strong>内容检索时间轴</strong><span>点击片段查看源画面</span></div><div class="timeline-review-controls"><b>08:36 / 11:04</b></div></header>
              <div class="timeline-toolbar"><div class="timeline-tool-group"><button type="button">适应全片</button></div></div>
              <div id="timelineOverview" class="timeline-overview"></div>
              <div id="timelineViewport" class="timeline-viewport">
                <div id="timelineTrackLabels" class="timeline-track-labels"><span>匹配片段</span><span>画面</span><span>音频</span></div>
                <div id="timelineTrackContent" class="timeline-track-content"></div>
              </div>
              <footer><span>当前选中</span><span>播放头</span></footer>
            </section>
          </section>
          <i></i><aside id="reviewRail"></aside>
        </main>
      </body></html>`);

    for (const height of [600, 720, 900]) {
      await page.setViewportSize({ width: 1366, height });
      const layout = await page.evaluate(() => {
        const workspace = document.querySelector("#workspace").getBoundingClientRect();
        const stage = document.querySelector("#reviewStage").getBoundingClientRect();
        const timeline = document.querySelector("#timelinePanel");
        const timelineRect = timeline.getBoundingClientRect();
        const viewport = document.querySelector("#timelineViewport");
        const footer = document.querySelector("#timelinePanel > footer").getBoundingClientRect();
        viewport.scrollTop = viewport.scrollHeight;
        return {
          workspaceBottom: workspace.bottom,
          stageHeight: stage.height,
          timelineBottom: timelineRect.bottom,
          timelineClientHeight: timeline.clientHeight,
          timelineScrollHeight: timeline.scrollHeight,
          footerTop: footer.top,
          footerBottom: footer.bottom,
          viewportClientHeight: viewport.clientHeight,
          viewportScrollHeight: viewport.scrollHeight,
          viewportScrollTop: viewport.scrollTop,
          viewportOverflowY: getComputedStyle(viewport).overflowY,
        };
      });
      assert.ok(layout.stageHeight >= 119, `${height}px viewport collapsed the player: ${JSON.stringify(layout)}`);
      assert.ok(layout.timelineBottom <= layout.workspaceBottom + 1, `${height}px viewport pushed the timeline outside the workspace`);
      assert.ok(layout.footerTop >= 0 && layout.footerBottom <= layout.timelineBottom + 1, `${height}px viewport clipped the timeline footer`);
      assert.equal(layout.timelineScrollHeight, layout.timelineClientHeight, `${height}px viewport left hidden overflow on the timeline panel`);
      assert.equal(layout.viewportOverflowY, "auto");
      if (layout.viewportScrollHeight > layout.viewportClientHeight) {
        assert.ok(layout.viewportScrollTop > 0, `${height}px viewport cannot reach lower timeline lanes`);
      }
    }
  } finally {
    await browser.close();
  }
});

test("workspace layout follows the active media without presenting manual orientation controls", () => {
  assert.doesNotMatch(html, /id="reviewLayoutSwitch"|data-review-layout-mode=/);
  assert.match(runtime, /data-ct-v4-output-aspect="source"[\s\S]*data-ct-v4-output-aspect="16:9"[\s\S]*data-ct-v4-output-aspect="9:16"/);
  assert.doesNotMatch(runtime, /data-ct-v4-layout=/);
  assert.doesNotMatch(runtime, /打开全局设置|模型、服务与 Skills 在全局设置中管理/);
  assert.doesNotMatch(runtime, /<section><strong>Agent 执行方式|<section><strong>字幕与导出|data-ct-v4-open-export/);
  assert.doesNotMatch(runtime, /可用编辑|data-ct-v4-fine-editor|function openFineEditor/);
  assert.match(runtime, /当前选择操作[\s\S]*data-ct-v4-boundary/);
  assert.match(html, /id="secondaryEditCurrentButton"/);
  assert.match(html, /data-model-role="agent"/);
  assert.match(html, /data-model-view="agent"/);
  assert.doesNotMatch(html, /<dt>输出策略<\/dt>/);
  assert.doesNotMatch(appSource, /reviewLayoutSwitch|data-review-layout-mode/);
  assert.match(appSource, /\/project-settings/);
  assert.match(appSource, /function recommendedReviewLayout\(aspect\)[\s\S]*normalized < 1 \? "portrait" : "landscape"/);
  assert.match(appSource, /function syncReviewLayoutForMedia\(aspect\)[\s\S]*nextLayout = recommendedReviewLayout\(aspect\)[\s\S]*setReviewLayout\(nextLayout, \{ source: "auto" \}\)/);
  assert.doesNotMatch(appSource, /reviewLayoutOverride/);
  assert.doesNotMatch(appSource, /cliptalk-review-layout-v1|storedReviewLayout|rememberReviewLayout/);
  const classifierSource = appSource.match(/function recommendedReviewLayout\(aspect\) \{[\s\S]*?\n\}/)?.[0];
  assert.ok(classifierSource);
  const classify = Function(`"use strict"; ${classifierSource}; return recommendedReviewLayout;`)();
  assert.equal(classify(9 / 16), "portrait");
  assert.equal(classify(1), "landscape");
  assert.equal(classify(16 / 9), "landscape");
});

test("workspace keeps secondary controls contextual and removes duplicate timeline zoom actions", () => {
  assert.doesNotMatch(html, /timelineZoomOutReview|timelineFitReview|timelineZoomInReview/);
  assert.match(html, /id="timelineZoomOut"[\s\S]*id="timelineFit"[\s\S]*id="timelineZoomIn"[\s\S]*id="timelineFocusReview"/);
  assert.match(html, /class="player-segment-group hidden"/);
  assert.match(html, /class="speaker-filter hidden"/);
  assert.match(appSource, /candidates\?\.length \|\| 0\) > 1/);
  assert.match(appSource, /focusButton\.classList\.toggle\("hidden", outputComparison \|\| !reviewRange\)/);
  assert.doesNotMatch(runtime, /data-ct-v4-rail="properties"[^>]*hidden disabled/);
  assert.match(css, /#reviewMoreActions:not\(:has\(> div > :not\(\.hidden\)\)\)/);
  assert.match(css, /#timelinePanel \.timeline-toolbar \{[\s\S]*display: grid !important/);
  assert.match(runtime, /\["analysing", "analyzing", "processing", "running"\]/);
  assert.doesNotMatch(css, /review-layout-switch|timeline-review-zoom/);
});

test("portrait workspace centers the true frame for review and splits only for precision", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.setContent(`<style>*,*::before,*::after{box-sizing:border-box}html,body{margin:0}${css}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace">
        <section id="reviewView" class="review-view" data-review-layout="landscape" style="width:1000px;height:720px">
          <header class="review-header"></header>
          <div id="reviewStage" class="review-stage"><div id="viewerShell" class="viewer-shell"></div><section id="evidencePanel" class="evidence-panel"><span class="portrait-precision-workbench-label">镜头工作台 · 当前选择</span></section></div>
          <section id="portraitPrecisionWorkbench" class="portrait-precision-workbench" data-phase="select">
            <div id="portraitWorkbenchFrame" class="portrait-workbench-frame" data-state="empty"><span class="portrait-workbench-frame-badge">源镜头预览</span></div>
            <div class="portrait-workbench-copy"><header><small>镜头检查</small><strong>选择时间线中的镜头</strong></header><p>在下方时间线选择片段。</p><dl class="portrait-workbench-facts"><div><dt>当前查看</dt><dd>源片画面</dd></div><div><dt>播放位置</dt><dd>00:00.0</dd></div></dl><ol class="portrait-workbench-guide"><li data-workbench-step="select"><i>1</i><span><b>选择镜头</b><small>在下方时间线选择</small></span></li></ol><footer><span>尚未选择</span></footer></div>
          </section>
          <nav id="ctEditorToolbar" class="ct-editor-toolbar"></nav>
          <div id="portraitVideoResizer" class="portrait-video-resizer"></div>
          <section id="timelinePanel" class="timeline-panel"></section>
        </section>
      </body>`);
    const landscape = await page.evaluate(() => {
      const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
      const stage = rect("#reviewStage");
      const timeline = rect("#timelinePanel");
      return { stageX: stage.x, stageWidth: stage.width, timelineX: timeline.x, timelineWidth: timeline.width };
    });
    assert.ok(Math.abs(landscape.stageX - landscape.timelineX) <= 1);
    assert.ok(Math.abs(landscape.stageWidth - landscape.timelineWidth) <= 1);

    await page.locator("#reviewView").evaluate((node) => {
      node.dataset.reviewLayout = "portrait";
      node.classList.add("timeline-hidden");
      document.querySelector("#timelinePanel").classList.add("hidden");
    });
    await page.waitForTimeout(220);
    const review = await page.evaluate(() => {
      const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
      const stage = rect("#reviewStage");
      const timeline = rect("#timelinePanel");
      const divider = rect("#portraitVideoResizer");
      const player = rect("#viewerShell");
      return {
        stageX: stage.x, stageWidth: stage.width,
        timelineDisplay: getComputedStyle(document.querySelector("#timelinePanel")).display,
        dividerDisplay: getComputedStyle(document.querySelector("#portraitVideoResizer")).display,
        playerX: player.x, playerWidth: player.width,
      };
    });
    assert.equal(review.timelineDisplay, "none");
    assert.equal(review.dividerDisplay, "none");
    assert.ok(review.stageWidth >= 990);
    assert.ok(review.playerWidth <= 440);
    assert.ok(Math.abs((review.playerX + review.playerWidth / 2) - (review.stageX + review.stageWidth / 2)) <= 1);

    await page.locator("#reviewView").evaluate((node) => {
      node.classList.remove("timeline-hidden");
      document.querySelector("#timelinePanel").classList.remove("hidden");
    });
    await page.waitForTimeout(220);
    const precision = await page.evaluate(() => {
      const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
      const timeline = rect("#timelinePanel");
      const divider = rect("#portraitVideoResizer");
      const player = rect("#viewerShell");
      const workbench = rect("#portraitPrecisionWorkbench");
      const frame = rect("#portraitWorkbenchFrame");
      return {
        timelineX: timeline.x, timelineRight: timeline.right,
        dividerX: divider.x, dividerRight: divider.right,
        dividerDisplay: getComputedStyle(document.querySelector("#portraitVideoResizer")).display,
        playerX: player.x, playerWidth: player.width,
        workbenchRight: workbench.right, workbenchBottom: workbench.bottom,
        workbenchWidth: workbench.width, frameWidth: frame.width, frameHeight: frame.height,
        timelineTop: timeline.top,
        workbenchDisplay: getComputedStyle(document.querySelector("#portraitPrecisionWorkbench")).display,
      };
    });
    assert.equal(precision.dividerDisplay, "block");
    assert.ok(precision.timelineRight <= precision.dividerX + 1);
    assert.ok(precision.playerX >= precision.dividerRight - 1);
    assert.ok(precision.playerWidth <= 440);
    assert.equal(precision.workbenchDisplay, "grid");
    assert.ok(precision.workbenchRight <= precision.dividerX + 1);
    assert.ok(precision.workbenchBottom <= precision.timelineTop + 1);
    assert.ok(precision.frameWidth >= precision.workbenchWidth * .5);
    assert.ok(precision.frameHeight >= 160);
  } finally {
    await browser.close();
  }
});

test("portrait output preview switches between focused review and precision layouts", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.setContent(`<style>*,*::before,*::after{box-sizing:border-box}html,body{margin:0}${css}</style>
      <body class="ct-workbench-v4 ct-output-preview-mode" data-shell-view="workspace" data-shell-mode="workspace">
        <section id="reviewView" class="review-view timeline-hidden" data-review-layout="portrait" style="width:1000px;height:720px">
          <header class="review-header"></header>
          <div id="reviewStage" class="review-stage"><div id="viewerShell" class="viewer-shell portrait"></div><section id="evidencePanel" class="evidence-panel"><span class="portrait-precision-workbench-label">镜头工作台 · 当前选择</span></section></div>
          <section id="portraitPrecisionWorkbench" class="portrait-precision-workbench"></section>
          <nav id="ctEditorToolbar" class="ct-editor-toolbar"></nav>
          <div id="portraitVideoResizer" class="portrait-video-resizer"></div>
          <section id="timelinePanel" class="timeline-panel hidden"></section>
        </section>
      </body>`);
    await page.waitForTimeout(220);
    const focused = await page.evaluate(() => {
      const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
      const stage = rect("#reviewStage");
      const player = rect("#viewerShell");
      return {
        stageX: stage.x,
        stageWidth: stage.width,
        dividerDisplay: getComputedStyle(document.querySelector("#portraitVideoResizer")).display,
        timelineDisplay: getComputedStyle(document.querySelector("#timelinePanel")).display,
        playerX: player.x,
        playerWidth: player.width,
      };
    });
    assert.equal(focused.dividerDisplay, "none");
    assert.equal(focused.timelineDisplay, "none");
    assert.ok(focused.playerWidth <= 440);
    assert.ok(Math.abs((focused.playerX + focused.playerWidth / 2) - (focused.stageX + focused.stageWidth / 2)) <= 1);

    await page.locator("#reviewView").evaluate((node) => {
      node.classList.remove("timeline-hidden");
      document.querySelector("#timelinePanel").classList.remove("hidden");
    });
    await page.waitForTimeout(220);
    const precision = await page.evaluate(() => {
      const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
      const stage = rect("#reviewStage");
      const timeline = rect("#timelinePanel");
      const divider = rect("#portraitVideoResizer");
      const player = rect("#viewerShell");
      const workbench = rect("#portraitPrecisionWorkbench");
      return {
        stageX: stage.x,
        stageWidth: stage.width,
        playerX: player.x,
        timelineRight: timeline.right,
        timelineTop: timeline.top,
        dividerX: divider.x,
        dividerRight: divider.right,
        dividerDisplay: getComputedStyle(document.querySelector("#portraitVideoResizer")).display,
        workbenchRight: workbench.right,
        workbenchBottom: workbench.bottom,
        workbenchDisplay: getComputedStyle(document.querySelector("#portraitPrecisionWorkbench")).display,
      };
    });
    assert.equal(precision.dividerDisplay, "block");
    assert.ok(precision.timelineRight <= precision.dividerX + 1);
    assert.ok(precision.playerX >= precision.dividerRight - 1);
    assert.equal(precision.workbenchDisplay, "grid");
    assert.ok(precision.workbenchRight <= precision.dividerX + 1);
    assert.ok(precision.workbenchBottom <= precision.timelineTop + 1);

    await page.locator("#reviewView").evaluate((node) => { node.dataset.reviewLayout = "landscape"; });
    const landscape = await page.evaluate(() => {
      const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
      const stage = rect("#reviewStage");
      const timeline = rect("#timelinePanel");
      return {
        stageX: stage.x,
        stageWidth: stage.width,
        timelineX: timeline.x,
        timelineWidth: timeline.width,
        dividerDisplay: getComputedStyle(document.querySelector("#portraitVideoResizer")).display,
      };
    });
    assert.equal(landscape.dividerDisplay, "none");
    assert.ok(Math.abs(landscape.stageX - landscape.timelineX) <= 1);
    assert.ok(Math.abs(landscape.stageWidth - landscape.timelineWidth) <= 1);

    await page.setViewportSize({ width: 800, height: 800 });
    await page.locator("#reviewView").evaluate((node) => {
      node.dataset.reviewLayout = "portrait";
      node.classList.remove("timeline-hidden");
      node.style.width = "800px";
      document.querySelector("#timelinePanel").classList.remove("hidden");
    });
    const compact = await page.evaluate(() => {
      const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
      const stage = rect("#reviewStage");
      const timeline = rect("#timelinePanel");
      return {
        stageX: stage.x,
        stageWidth: stage.width,
        timelineX: timeline.x,
        timelineWidth: timeline.width,
        dividerDisplay: getComputedStyle(document.querySelector("#portraitVideoResizer")).display,
      };
    });
    assert.equal(compact.dividerDisplay, "none");
    assert.ok(Math.abs(compact.stageX - compact.timelineX) <= 1);
    assert.ok(Math.abs(compact.stageWidth - compact.timelineWidth) <= 1);
  } finally {
    await browser.close();
  }
});

function fixture() {
  return `<style>*,*::before,*::after{box-sizing:border-box}html,body{margin:0}${css}</style>
    <body data-shell-view="workspace" data-shell-mode="workspace" data-workspace-state="awaiting_instruction">
      <main id="workspace" class="studio" style="--ct-user-left-pane:340px;--ct-user-right-pane:410px">
        <aside id="appSidebar" class="app-sidebar"><header class="app-sidebar-brand"></header><nav class="app-sidebar-primary"></nav></aside>
        <aside id="assistantPanel" class="chat-panel"><header class="panel-header"><div class="director"><img class="director-brand-icon"><div><strong>剪辑助理</strong><small><b id="directorState">等待剪辑要求</b></small></div></div></header><section id="directorTaskSummary"><strong>产品宣传.mp4</strong></section><section id="chatMessages"></section><form id="chatForm" class="chat-composer"><div class="chat-input-shell"><textarea id="chatInput" placeholder="描述你想剪什么，AI 会自动规划"></textarea><button id="composerSuggestion" class="composer-suggestion" type="button">试试：“生成一版可审核短片”</button><div class="composer-toolbar"><div class="composer-toolbar-left"></div><div class="composer-toolbar-right"><button id="sendButton" type="submit">发送</button></div></div></div><small>Enter 发送 · Shift+Enter 换行</small></form></aside>
        <div class="panel-resizer panel-resizer-left"></div>
        <section class="review-panel glass-panel"><div id="reviewView"><span id="reviewTitle">产品宣传.mp4</span><span id="assetDuration">时长 10:43</span><span id="assetResolution">分辨率 960×540</span><nav id="contentDetailModeSwitch"><button id="contentBoundaryEntryButton" type="button">调整边界</button></nav><div id="reviewStage" class="review-stage"><div id="viewerShell" class="viewer-shell"><div id="mediaFrame" class="media-frame"><video id="mainVideo"></video></div></div><div id="reviewEvidenceResizer"></div><section id="evidencePanel" class="evidence-panel evidence-placeholder"><header><div><small id="clipTime">审核说明</small><h3 id="clipTitle">选择事件或镜头</h3></div><button id="closeEvidenceButton" type="button">×</button></header><p id="clipReason"></p><div id="clipEvidenceMeta"></div><ul id="clipEvidence"></ul></section></div></div></section>
        <div class="panel-resizer panel-resizer-right"></div>
        <aside id="reviewRail" class="review-rail"><header class="rail-header"></header><nav id="reviewPanelSwitch"></nav><section id="ctReviewEmpty"></section><section id="reviewWorkbench" class="hidden"></section><section id="clipStrip"></section><section id="clipVersionPicker"></section></aside>
        <section id="timelineCoverTrack" class="hidden"></section><section id="subtitleReview" class="hidden"></section>
        <select id="agentExecutionMode"><option value="autonomous_review">自动执行到审核样片</option></select>
        <select id="chatComposeSubtitleMode"><option value="none">不添加字幕</option></select>
        <div class="hidden"><button id="coverIntroButton" class="download-button hidden" type="button">生成封面片头版</button></div>
      </main>
      <script>${runtime}</script>
    </body>`;
}

test("portrait workspace preserves conversation through completion and respects manual panel choices", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  try {
    await page.route("http://portrait.test/**", (route) => route.fulfill({
      status: 200,
      contentType: "text/html",
      body: fixture(),
    }));
    await page.goto("http://portrait.test/");
    const planning = await page.evaluate(() => {
      localStorage.removeItem("cliptalk-assistant-expanded:v2:new-task");
      localStorage.removeItem("cliptalk-review-rail-expanded:v1:new-task");
      localStorage.removeItem("cliptalk-portrait-panel-handoff:v1:new-task");
      const workspace = document.querySelector("#workspace");
      const review = document.querySelector("#reviewView");
      review.dataset.reviewLayout = "portrait";
      document.body.dataset.shellMode = "workspace";
      document.body.dataset.workspaceState = "analysing";
      window.ClipTalkWorkspacePanels = {
        setAssistantExpanded(expanded, { persist = false } = {}) {
          workspace.classList.toggle("assistant-collapsed", !expanded);
          if (persist) localStorage.setItem("cliptalk-assistant-expanded:v2:new-task", String(Boolean(expanded)));
        },
      };
      window.ClipTalkWorkspaceController.syncPortraitPanels("analysing");
      return {
        assistantOpen: !workspace.classList.contains("assistant-collapsed"),
        railOpen: !workspace.classList.contains("review-rail-collapsed"),
      };
    });
    assert.deepEqual(planning, { assistantOpen: true, railOpen: false });

    const review = await page.evaluate(() => {
      const workspace = document.querySelector("#workspace");
      window.ClipTalkWorkspaceController.syncPortraitPanels("reviewing");
      return {
        assistantOpen: !workspace.classList.contains("assistant-collapsed"),
        railOpen: !workspace.classList.contains("review-rail-collapsed"),
        handoff: localStorage.getItem("cliptalk-portrait-panel-handoff:v1:new-task"),
      };
    });
    assert.deepEqual(review, { assistantOpen: true, railOpen: false, handoff: null });

    const manual = await page.evaluate(() => {
      const workspace = document.querySelector("#workspace");
      window.ClipTalkWorkspacePanels.setAssistantExpanded(true, { persist: true });
      window.ClipTalkWorkspaceController.setRailExpanded(false, { persist: true, coordinate: false });
      window.ClipTalkWorkspaceController.syncPortraitPanels("completed");
      return {
        assistantOpen: !workspace.classList.contains("assistant-collapsed"),
        railOpen: !workspace.classList.contains("review-rail-collapsed"),
      };
    });
    assert.deepEqual(manual, { assistantOpen: true, railOpen: false });

    const switched = await page.evaluate(() => {
      const workspace = document.querySelector("#workspace");
      window.ClipTalkWorkspaceController.setRailExpanded(true, { persist: true });
      return {
        assistantOpen: !workspace.classList.contains("assistant-collapsed"),
        railOpen: !workspace.classList.contains("review-rail-collapsed"),
      };
    });
    assert.deepEqual(switched, { assistantOpen: true, railOpen: true });
  } finally {
    await browser.close();
  }
});

test("v4 workbench owns the reference layout and contextual rail", async () => {
  assert.match(html, /workbench\.css\?v=\d{8}-[\w-]+/);
  assert.match(html, /workspace-controller\.js\?v=\d{8}-[\w-]+/);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  try {
    await page.setContent(fixture());
    await page.waitForTimeout(50);
    const geometry = await page.evaluate(() => {
      const rect = (selector) => {
        const value = document.querySelector(selector).getBoundingClientRect();
        return { x: Math.round(value.x), y: Math.round(value.y), width: Math.round(value.width), height: Math.round(value.height) };
      };
      return {
        topbar: rect("#ctV4Topbar"),
        navigation: rect("#appSidebar"),
        assistant: rect("#assistantPanel"),
        center: rect(".review-panel"),
        rail: rect("#reviewRail"),
      };
    });

    assert.deepEqual(geometry.topbar, { x: 84, y: 0, width: 1516, height: 48 });
    assert.equal(geometry.navigation.x, 0);
    assert.equal(geometry.navigation.y, 0);
    assert.equal(geometry.navigation.width, 84);
    assert.equal(geometry.navigation.height, 900);
    assert.equal(geometry.assistant.x, 84);
    assert.equal(geometry.assistant.width, 340);
    assert.equal(geometry.center.x, 432);
    assert.equal(geometry.rail.x + geometry.rail.width, 1600);

    const composerHint = await page.evaluate(() => {
      const panel = document.querySelector("#assistantPanel").getBoundingClientRect();
      const form = document.querySelector("#chatForm").getBoundingClientRect();
      const hint = document.querySelector("#chatForm > small").getBoundingClientRect();
      return {
        text: document.querySelector("#chatForm > small").textContent.trim(),
        display: getComputedStyle(document.querySelector("#chatForm > small")).display,
        hintTop: Math.round(hint.top),
        hintBottom: Math.round(hint.bottom),
        formTop: Math.round(form.top),
        formBottom: Math.round(form.bottom),
        panelBottom: Math.round(panel.bottom),
      };
    });
    assert.equal(composerHint.text, "Enter 发送 · Shift+Enter 换行");
    assert.equal(composerHint.display, "block");
    assert.ok(composerHint.hintTop >= composerHint.formTop);
    assert.ok(composerHint.hintBottom <= composerHint.formBottom);
    assert.ok(composerHint.hintBottom <= composerHint.panelBottom);

    const composerSuggestion = await page.evaluate(() => {
      const shell = document.querySelector("#chatForm .chat-input-shell").getBoundingClientRect();
      const form = document.querySelector("#chatForm").getBoundingClientRect();
      const suggestion = document.querySelector("#composerSuggestion");
      const rect = suggestion.getBoundingClientRect();
      return {
        display: getComputedStyle(suggestion).display,
        top: Math.round(rect.top),
        bottom: Math.round(rect.bottom),
        shellTop: Math.round(shell.top),
        shellBottom: Math.round(shell.bottom),
        formBottom: Math.round(form.bottom),
      };
    });
    assert.equal(composerSuggestion.display, "block");
    assert.ok(composerSuggestion.top >= composerSuggestion.shellTop);
    assert.ok(composerSuggestion.bottom <= composerSuggestion.formBottom);

    await page.locator("#workspace").evaluate((node) => node.classList.add("assistant-collapsed"));
    const collapsed = await page.evaluate(() => {
      const rect = (selector) => {
        const value = document.querySelector(selector).getBoundingClientRect();
        return { x: Math.round(value.x), width: Math.round(value.width), display: getComputedStyle(document.querySelector(selector)).display };
      };
      return { assistant: rect("#assistantPanel"), handle: rect(".panel-resizer-left"), center: rect(".review-panel") };
    });
    assert.deepEqual(collapsed.assistant, { x: 84, width: 54, display: "block" });
    assert.equal(collapsed.handle.display, "none");
    assert.equal(collapsed.center.x, 138);
    assert.equal(collapsed.center.width, 1044);
    await page.locator("#workspace").evaluate((node) => node.classList.remove("assistant-collapsed"));

    assert.equal(await page.locator("#evidencePanel").evaluate((node) => node.parentElement.id), "reviewRail");
    const playerLayout = await page.evaluate(() => ({
      stageWidth: document.querySelector("#reviewStage").getBoundingClientRect().width,
      playerWidth: document.querySelector("#viewerShell").getBoundingClientRect().width,
      horizontalPadding: parseFloat(getComputedStyle(document.querySelector("#reviewStage")).paddingLeft) + parseFloat(getComputedStyle(document.querySelector("#reviewStage")).paddingRight),
      resizerDisplay: getComputedStyle(document.querySelector("#reviewEvidenceResizer")).display,
    }));
    assert.ok(Math.abs(playerLayout.stageWidth - playerLayout.horizontalPadding - playerLayout.playerWidth) <= 1);
    assert.equal(playerLayout.resizerDisplay, "none");

    assert.equal(await page.locator('[data-ct-v4-rail="properties"]').isVisible(), false);
    assert.equal(await page.locator('[data-ct-v4-rail="properties"]').textContent(), "片段详情");
    await page.locator("html").evaluate((node) => {
      node.dataset.theme = "light";
      document.body.dataset.shellMode = "workspace";
    });
    assert.equal(await page.locator("#evidencePanel").evaluate((node) => getComputedStyle(node).display), "none");
    assert.equal(await page.locator("#ctV4MaterialsSummary").evaluate((node) => getComputedStyle(node).display), "grid");
    const lightProperties = await page.evaluate(() => ({
      selection: getComputedStyle(document.querySelector("#ctV4PropertiesPanel .ct-v4-property-selection")).backgroundColor,
      action: getComputedStyle(document.querySelector("#ctV4PropertiesPanel .ct-v4-property-actions button")).backgroundColor,
      actionText: getComputedStyle(document.querySelector("#ctV4PropertiesPanel .ct-v4-property-actions button b")).color,
    }));
    assert.deepEqual(lightProperties, {
      selection: "rgb(247, 247, 244)",
      action: "rgb(236, 238, 235)",
      actionText: "rgb(36, 53, 44)",
    });

    await page.evaluate(() => {
      const evidence = document.querySelector("#evidencePanel");
      evidence.classList.remove("evidence-placeholder");
      evidence.classList.add("candidate-mode");
      document.querySelector("#clipTitle").textContent = "多辆汽车画面出现";
      document.querySelector("#clipTime").textContent = "00:05 → 00:12 · 7.0 秒";
      window.boundaryShortcutClicks = 0;
      document.querySelector("#contentBoundaryEntryButton").addEventListener("click", () => { window.boundaryShortcutClicks += 1; });
      window.ClipTalkWorkspaceController.mount();
    });
    await page.waitForFunction(() => document.body.dataset.ctV4RailTab === "properties");
    assert.equal(await page.locator('[data-ct-v4-rail="properties"]').isVisible(), true);
    assert.equal(await page.locator('[data-ct-v4-rail="properties"]').getAttribute("aria-selected"), "true");
    assert.equal(await page.locator("#ctV4PropertiesPanel > header strong").textContent(), "片段详情");
    assert.equal(await page.locator("#ctV4SelectionBar").isVisible(), true);
    assert.match(await page.locator("#ctV4SelectionBar").textContent(), /多辆汽车画面出现.*查看判断依据.*调整边界/s);
    const selectionPalette = await page.evaluate(() => ({
      surface: getComputedStyle(document.querySelector("#ctV4SelectionBar")).backgroundColor,
      title: getComputedStyle(document.querySelector("#ctV4SelectionBar strong")).color,
      action: getComputedStyle(document.querySelector("#ctV4SelectionBar button")).backgroundColor,
    }));
    assert.deepEqual(selectionPalette, {
      surface: "rgb(247, 247, 244)",
      title: "rgb(41, 68, 56)",
      action: "rgb(236, 238, 235)",
    });
    await page.locator("#ctV4SelectionBar [data-ct-v4-boundary-shortcut]").click();
    assert.equal(await page.evaluate(() => window.boundaryShortcutClicks), 1);
    await page.locator("#ctV4SelectionBar [data-ct-v4-show-evidence]").click();
    assert.equal(await page.locator("#evidencePanel").evaluate((node) => getComputedStyle(node).display), "block");
    assert.equal(await page.locator("body").getAttribute("data-ct-v4-evidence-open"), "true");
    await page.locator("#closeEvidenceButton").click();
    assert.equal(await page.locator("#evidencePanel").evaluate((node) => getComputedStyle(node).display), "none");
    assert.equal(await page.locator("body").getAttribute("data-ct-v4-evidence-open"), null);

    await page.evaluate(() => {
      document.querySelector("#evidencePanel").classList.add("evidence-placeholder");
      window.ClipTalkWorkspaceController.mount();
    });
    assert.equal(await page.locator('[data-ct-v4-rail="properties"]').isVisible(), false);
    assert.equal(await page.locator("body").getAttribute("data-ct-v4-rail-tab"), "materials");

    await page.locator('[data-ct-v4-rail="project"]').click();
    assert.equal(await page.locator("#ctV4ProjectPanel").evaluate((node) => getComputedStyle(node).display), "block");
    const lightProjectSettings = await page.evaluate(() => ({
      section: getComputedStyle(document.querySelector("#ctV4ProjectPanel > section")).backgroundColor,
      input: getComputedStyle(document.querySelector("#ctV4ProjectDisplayName")).backgroundColor,
      segmented: getComputedStyle(document.querySelector("#ctV4ProjectPanel .ct-v4-segmented")).backgroundColor,
      reframeFit: getComputedStyle(document.querySelector("#ctV4ReframeFit")).backgroundColor,
      reframeFitText: getComputedStyle(document.querySelector("#ctV4ReframeFit")).color,
      reframeFitWidth: document.querySelector("#ctV4ReframeFit").getBoundingClientRect().width,
      reframeSectionWidth: document.querySelector("#ctV4ReframeFit").closest("section").getBoundingClientRect().width,
    }));
    const { reframeFitWidth, reframeSectionWidth, ...lightProjectPalette } = lightProjectSettings;
    assert.deepEqual(lightProjectPalette, {
      section: "rgb(247, 247, 244)",
      input: "rgb(255, 255, 255)",
      segmented: "rgb(236, 238, 234)",
      reframeFit: "rgb(255, 255, 255)",
      reframeFitText: "rgb(38, 55, 46)",
    });
    assert.ok(Math.abs(reframeFitWidth - (reframeSectionWidth - 28)) <= 1);
    assert.doesNotMatch(await page.locator("#ctV4ProjectPanel").textContent(), /Agent 执行方式|字幕与导出|打开版本与导出设置/);
    assert.doesNotMatch(await page.locator("#ctV4PropertiesPanel").textContent(), /AI 批量修改|版本与导出/);
    assert.equal(await page.locator("#coverIntroButton").evaluate((node) => node.parentElement.classList.contains("ct-v4-version-secondary-actions")), true);

    await page.evaluate(() => {
      window.__savedOutputAspect = "";
      window.ClipTalkCurrentJobSnapshot = () => ({
        id: "job_current", filename: "source.mp4",
        projectSettings: { outputAspect: "9:16" }, outputs: [],
      });
      window.ClipTalkOrderedJobOutputs = () => [];
      window.ClipTalkUpdateProjectSettings = async ({ outputAspect }) => {
        window.__savedOutputAspect = outputAspect;
      };
      window.ClipTalkWorkspaceController.syncProjectControls();
    });
    assert.equal(await page.locator('[data-ct-v4-output-aspect="9:16"]').getAttribute("aria-pressed"), "true");
    assert.match(await page.locator("#ctV4OutputAspectStatus").textContent(), /下一次生成成片时应用 9:16/);
    await page.locator('[data-ct-v4-output-aspect="16:9"]').click();
    assert.equal(await page.evaluate(() => window.__savedOutputAspect), "16:9");

    await page.evaluate(() => {
      const job = {
        id: "job_current", filename: "source.mp4",
        projectSettings: { outputAspect: "9:16" },
      };
      window.ClipTalkCurrentJobSnapshot = () => job;
      window.ClipTalkOrderedJobOutputs = () => [{ item: { width: 1920, height: 1080 } }];
      window.ClipTalkWorkspaceController.syncProjectControls();
    });
    await page.locator('[data-ct-v4-rail="materials"]').click();
    await page.locator("#ctV4GenerateAspect").waitFor({ state: "visible" });
    const aspectActionState = await page.locator("#ctV4GenerateAspect").evaluate((node) => ({
      visible: Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length),
      className: node.className,
      disabled: node.disabled,
      text: node.textContent,
    }));
    assert.equal(aspectActionState.visible, true, JSON.stringify(aspectActionState));
    assert.equal(await page.locator("#ctV4GenerateAspect").evaluate((node) => node.closest(".ct-v4-version-card") !== null), true);
    assert.match(await page.locator("#ctV4GenerateAspect").textContent(), /生成 9:16 审核版本/);

    await page.evaluate(() => {
      document.querySelector('#ctV4MaterialsSummary').dataset.outputFilename = 'selected.mp4';
      window.ClipTalkOrderedJobOutputs = () => [{ item: { filename: 'another.mp4', width: 1080, height: 1920 } }];
      window.ClipTalkWorkspaceController.syncProjectControls();
    });
    assert.equal(await page.locator("#ctV4GenerateAspect").isVisible(), true, "Another version's canvas cannot suppress this version's action");
    await page.evaluate(() => {
      window.ClipTalkOrderedJobOutputs = () => [{ item: { filename: 'selected.mp4', width: 1080, height: 1920 } }];
      window.ClipTalkWorkspaceController.syncProjectControls();
    });
    assert.equal(await page.locator("#ctV4GenerateAspect").isVisible(), false);
  } finally {
    await browser.close();
  }
});

test("delivery checks trust rendered overlays and nested cover intro state", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  try {
    await page.setContent(fixture());
    await page.evaluate(() => {
      const output = {
        filename: "review.mp4", previewOnly: true, width: 540, height: 960,
        subtitleMode: "burn",
        coverIntro: { enabled: true, coverVersionId: "cover_v001" },
        overlayVerification: {
          renderPipelineVersion: 2, applied: true,
          appliedCueCount: 4, subtitleCueCount: 3, textLayerCount: 1,
        },
      };
      window.ClipTalkCurrentJobId = () => "job_current";
      window.ClipTalkCurrentJobSnapshot = () => ({
        id: "job_current", filename: "source.mp4", coverNeedsRegeneration: false,
      });
      window.ClipTalkCurrentOutputSnapshot = () => ({ output, isReviewSample: true });
      window.ClipTalkOrderedJobOutputs = () => [{ item: output, version: { previewOnly: true } }];
      window.ClipTalkWorkspaceController.syncMaterialsSummary();
    });
    const validText = await page.locator("#ctV4DeliveryChecks").textContent();
    assert.match(validText, /画幅9:16 · 540×960/);
    assert.match(validText, /封面已合入/);
    assert.match(validText, /字幕已烧录/);
    assert.equal(await page.locator("#ctV4VersionState").textContent(), "1 个审核样片");
    assert.match(await page.locator("[data-ct-v4-preview-version]").textContent(), /播放样片/);
    assert.equal(await page.locator("[data-ct-v4-export]").count(), 0);
    assert.equal(await page.locator(".ct-v4-version-card > footer button").count(), 2);

    await page.evaluate(() => {
      const output = {
        filename: "legacy.mp4", previewOnly: true, width: 540, height: 960,
        subtitleMode: "burn", coverIntro: { enabled: true },
      };
      window.ClipTalkCurrentJobSnapshot = () => ({
        id: "job_current", filename: "source.mp4", coverNeedsRegeneration: true,
      });
      window.ClipTalkCurrentOutputSnapshot = () => ({ output, isReviewSample: true });
      window.ClipTalkOrderedJobOutputs = () => [{ item: output, version: { previewOnly: true } }];
      window.ClipTalkWorkspaceController.syncMaterialsSummary();
    });
    const staleText = await page.locator("#ctV4DeliveryChecks").textContent();
    assert.match(staleText, /封面需更新/);
    assert.match(staleText, /字幕待烧录/);

    await page.evaluate(() => {
      const formalOne = { filename: "formal-one.mp4", width: 1920, height: 1080, duration: 48 };
      const formalTwo = { filename: "formal-two.mp4", width: 1920, height: 1080, duration: 52 };
      const sample = { filename: "sample.mp4", width: 960, height: 540, previewOnly: true };
      window.ClipTalkCurrentJobSnapshot = () => ({
        id: "job_current", filename: "source.mp4", storageMode: "editable",
      });
      window.ClipTalkCurrentOutputSnapshot = () => ({ output: formalOne, isReviewSample: false });
      window.ClipTalkOrderedJobOutputs = () => [
        { item: formalOne, version: { id: "formal_v1" } },
        { item: formalTwo, version: { id: "formal_v2" } },
        { item: sample, version: { id: "sample_v1", previewOnly: true } },
      ];
      window.ClipTalkWorkspaceController.syncMaterialsSummary();
    });
    assert.equal(await page.locator("#ctV4VersionState").textContent(), "2 个正式版本 · 1 个审核样片");
    const formalChecks = await page.locator("#ctV4DeliveryChecks").textContent();
    assert.match(formalChecks, /画幅16:9 · 1920×1080/);
    assert.doesNotMatch(formalChecks, /竖屏|封面|字幕|高清/);
    assert.match(await page.locator("[data-ct-v4-preview-version]").textContent(), /播放/);
    assert.equal(await page.locator("[data-ct-v4-export]").count(), 0);

    await page.evaluate(() => {
      const current = window.ClipTalkCurrentJobSnapshot();
      window.ClipTalkCurrentJobSnapshot = () => ({ ...current, storageMode: "one_off" });
      window.ClipTalkWorkspaceController.syncMaterialsSummary();
    });
    assert.deepEqual(await page.locator(".ct-v4-version-card > footer button").allTextContents(), ["播放成片", "全部版本"]);
  } finally {
    await browser.close();
  }
});

test("current material card shows an explicit generating state until its thumbnail is ready", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  try {
    await page.setContent(fixture());
    await page.evaluate(() => {
      window.ClipTalkCurrentJobId = () => "job_thumbnail_pending";
      window.ClipTalkCurrentJobSnapshot = () => ({
        id: "job_thumbnail_pending",
        filename: "产品宣传.mp4",
        thumbnailReady: false,
        thumbnailStatus: "pending",
      });
      window.ClipTalkWorkspaceController.syncMaterialsSummary();
    });

    const pending = await page.locator(".ct-v4-source-preview").evaluate((node) => ({
      state: node.dataset.thumbnailState,
      text: node.textContent,
      src: node.querySelector("img").getAttribute("src"),
      statusVisible: getComputedStyle(node.querySelector(".ct-v4-source-preview-state")).display,
    }));
    assert.equal(pending.state, "loading");
    assert.match(pending.text, /正在生成缩略图/);
    assert.equal(pending.src, null);
    assert.equal(pending.statusVisible, "grid");

    await page.evaluate(() => {
      window.ClipTalkCurrentJobSnapshot = () => ({
        id: "job_thumbnail_pending",
        filename: "产品宣传.mp4",
        thumbnailReady: true,
        thumbnailStatus: "ready",
      });
      window.ClipTalkWorkspaceController.syncMaterialsSummary();
    });
    const ready = await page.locator(".ct-v4-source-preview").evaluate((node) => ({
      state: node.dataset.thumbnailState,
      src: node.querySelector("img").getAttribute("src"),
      statusVisible: getComputedStyle(node.querySelector(".ct-v4-source-preview-state")).display,
    }));
    assert.equal(ready.state, "ready");
    assert.match(ready.src, /\/api\/jobs\/job_thumbnail_pending\/thumbnail$/);
    assert.equal(ready.statusVisible, "none");
  } finally {
    await browser.close();
  }
});

test("new task assistant and upload stage share one continuous surface", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  try {
    await page.setContent(`<style>html,body{margin:0}${css}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace">
        <main id="workspace" class="studio director-merged new-task-workbench">
          <aside id="appSidebar" class="app-sidebar"></aside>
          <aside id="assistantPanel" class="chat-panel"></aside>
          <div class="panel-resizer-left"></div>
          <section id="reviewView" class="review-panel glass-panel">
            <div id="uploadView" class="upload-view new-task-upload"></div>
          </section>
        </main>
      </body>`);
    const palette = await page.evaluate(() => {
      const style = (selector) => getComputedStyle(document.querySelector(selector));
      return {
        workspaceBackground: style("#workspace").background,
        assistantBackground: style("#assistantPanel").background,
        reviewBackground: style("#reviewView").background,
        uploadBackground: style("#uploadView").background,
        dividerBackground: style(".panel-resizer-left").backgroundColor,
        dividerWidth: style(".panel-resizer-left").width,
        dividerCursor: style(".panel-resizer-left").cursor,
        dividerGrip: getComputedStyle(document.querySelector(".panel-resizer-left"), "::before").backgroundColor,
      };
    });
    assert.match(palette.workspaceBackground, /rgb\(242, 241, 234\)/);
    assert.match(palette.assistantBackground, /rgb\(32, 41, 41\)/);
    assert.match(palette.reviewBackground, /rgb\(242, 241, 234\)/);
    assert.match(palette.uploadBackground, /rgba\(0, 0, 0, 0\)/);
    assert.equal(palette.dividerBackground, "rgba(0, 0, 0, 0)");
    assert.equal(palette.dividerWidth, "8px");
    assert.equal(palette.dividerCursor, "col-resize");
    assert.equal(palette.dividerGrip, "rgba(157, 190, 174, 0.2)");
  } finally {
    await browser.close();
  }
});

test("uploading a new source uses one progress surface and hides the premature local player", async () => {
  assert.match(html, /id="uploadProgress"[^>]*aria-label="视频上传进度"/);
  assert.match(html, /id="localPreviewPanel" class="media-metadata-probe hidden" hidden aria-hidden="true"/);
  assert.doesNotMatch(html, /<strong>源视频已就绪<\/strong>/);
  assert.doesNotMatch(html, /id="replaceVideoButton"|本地文件预览/);
  assert.doesNotMatch(appSource, /autoplayLocalPreview|replaceVideoButton/);
  assert.doesNotMatch(runtime, /replaceVideoButton/);
  assert.match(appSource, /#localPreviewPanel"\)\?\.classList\.add\("hidden"\)/);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  try {
    await page.setContent(`<style>*,*::before,*::after{box-sizing:border-box}html,body{margin:0}${css}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace">
        <main id="workspace" class="studio new-task-workbench">
          <section class="review-panel">
            <div id="uploadView" class="upload-view new-task-upload is-uploading">
              <div class="intro"><h1>上传素材</h1><span>先完成上传，再进入剪辑。</span></div>
              <form id="uploadForm" class="upload-card">
                <label id="dropZone" class="drop-zone has-file" data-upload-state="uploading">
                  <span class="drop-zone-add"></span><strong>产品宣传.mp4 · 上传 25%</strong><small>正在上传并创建任务，完成后自动进入工作区</small>
                  <progress id="uploadProgress" class="upload-progress" max="100" value="25"></progress>
                </label>
                <div id="localPreviewPanel" class="media-metadata-probe"><video></video></div>
              </form>
            </div>
          </section>
        </main>
      </body>`);

    const audit = await page.evaluate(() => ({
      previewDisplay: getComputedStyle(document.querySelector("#localPreviewPanel")).display,
      progressDisplay: getComputedStyle(document.querySelector("#uploadProgress")).display,
      progressValue: document.querySelector("#uploadProgress").value,
      dropMinHeight: getComputedStyle(document.querySelector("#dropZone")).minHeight,
      cursor: getComputedStyle(document.querySelector("#dropZone")).cursor,
    }));
    assert.equal(audit.previewDisplay, "none");
    assert.equal(audit.progressDisplay, "block");
    assert.equal(audit.progressValue, 25);
    assert.equal(audit.dropMinHeight, "180px");
    assert.equal(audit.cursor, "progress");
  } finally {
    await browser.close();
  }
});
