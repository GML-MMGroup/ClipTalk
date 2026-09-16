import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { chromium } from "playwright";

const productionCss = [...readFileSync(new URL("../../static/index.html", import.meta.url), "utf8").matchAll(/href="\/static\/([^"?]+\.css)/g)].map(match => readFileSync(new URL(`../../static/${match[1]}`, import.meta.url), "utf8")).join("\n");

const css = readFileSync(new URL("../../static/agent-workspace.css", import.meta.url), "utf8");
const tokensCss = readFileSync(new URL("../../static/cliptalk-tokens.css", import.meta.url), "utf8");
const referenceV3Css = readFileSync(new URL("../../static/workspace-components.css", import.meta.url), "utf8");
const workbenchV4Css = readFileSync(new URL("../../static/workbench.css", import.meta.url), "utf8");
const workbenchV4Source = readFileSync(new URL("../../static/workspace-controller.js", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const timelinePresentationJs = readFileSync(new URL("../../static/timeline-presentation.js", import.meta.url), "utf8");
const agent = readFileSync(new URL("../../static/agent-workspace.js", import.meta.url), "utf8");

test("generated segment thumbnails remain visible while the player shows the source video", () => {
  assert.match(workbenchV4Source, /const adoptedMode = Boolean\(adoptedSegments\.length\)/);
  assert.doesNotMatch(
    workbenchV4Source,
    /const adoptedMode = Boolean\(outputSnapshot\.isReviewSample\s*&&\s*adoptedSegments\.length\)/,
  );
});

test("submitting an Agent goal clears the composer while planning is in progress", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    await page.setContent(`
      <section id="chatMessages"></section>
      <textarea id="chatInput">生成一条 60 秒高光视频</textarea>
      <button id="sendButton" type="button">发送</button>
      <script>
        window.ClipTalkApi = {
          requestJson: async () => ({ workspace: { id: 'ws_planning', jobId: 'job_planning' } }),
          requestResponse: async () => new Promise(() => {}),
        };
        window.ClipTalkCurrentJobId = () => 'job_planning';
        window.ClipTalkRefreshCurrentJob = () => {};
        window.showToast = () => {};
      </script>
      <script>${agent}</script>`);

    await page.evaluate(() => {
      window.ClipTalkAgentWorkspace.submitGoal(document.querySelector('#chatInput').value);
    });
    await page.waitForFunction(() => document.querySelector('#chatInput').disabled);

    assert.equal(await page.locator('#chatInput').inputValue(), '');
    assert.equal(await page.locator('#chatInput').isDisabled(), true);
    assert.match(await page.locator('#chatMessages').textContent(), /生成一条 60 秒高光视频/);
  } finally {
    await browser.close();
  }
});

test("Agent plan control summary remains readable at narrow sidebar widths", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    await page.setContent(`<style>${css}</style>
      <body data-shell-mode="workspace">
        <section class="agent-plan-dock" data-tone="running">
          <header><small>内容剪辑计划</small><b class="agent-planning-live"><i></i>构建中</b></header>
          <section class="agent-plan-control" aria-label="Agent 任务控制台">
            <dl>
              <div><dt>目标</dt><dd>找出所有关于汽车的画面，合成竖屏视频</dd></div>
              <div><dt>当前阶段</dt><dd>正在安排执行步骤</dd></div>
              <div><dt>下一步</dt><dd>确认后开始检索、编排或生成样片</dd></div>
            </dl>
            <small>自动执行到审核样片</small>
          </section>
        </section>
      </body>`);

    for (const width of [320, 361, 400]) {
      await page.setViewportSize({ width, height: 240 });
      const rows = await page.locator(".agent-plan-control div").evaluateAll((items) => items.map((item) => {
        const term = item.querySelector("dt").getBoundingClientRect();
        const detail = item.querySelector("dd").getBoundingClientRect();
        const detailStyle = getComputedStyle(item.querySelector("dd"));
        return {
          termRight: term.right,
          detailLeft: detail.left,
          detailRight: detail.right,
          containerRight: item.getBoundingClientRect().right,
          whiteSpace: detailStyle.whiteSpace,
          overflow: detailStyle.overflow,
          lineClamp: detailStyle.webkitLineClamp,
        };
      }));

      assert.equal(rows.length, 3);
      rows.forEach((row) => {
        assert.ok(row.detailLeft > row.termRight, `detail must sit after label at ${width}px`);
        assert.ok(row.detailRight <= row.containerRight + 1, `detail must not overflow at ${width}px`);
        assert.equal(row.whiteSpace, "normal");
        assert.equal(row.overflow, "visible");
        assert.equal(row.lineClamp, "none");
      });
    }
  } finally {
    await browser.close();
  }
});

test("retained content-search result uses the same visual surface as the content plan", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    await page.setContent(`
      <style>${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace">
        <aside id="assistantPanel">
          <section id="chatMessages">
            <article class="chat-message content-search-message">
              <div class="recommendation-wrap">
                <section class="content-search-review historical">
                  <header><div><small>已保留结果 · 选择片段</small><strong>相关片段检索完成</strong></div></header>
                  <button class="content-history-toggle">收起已保留结果</button>
                </section>
              </div>
            </article>
          </section>
        </aside>
      </body>`);

    const result = await page.locator('.content-search-review.historical').evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        backgroundImage: style.backgroundImage,
        borderLeftColor: style.borderLeftColor,
        borderLeftWidth: style.borderLeftWidth,
        color: style.color,
      };
    });
    const toggle = await page.locator('.content-history-toggle').evaluate((element) => {
      const style = getComputedStyle(element);
      return { backgroundColor: style.backgroundColor, color: style.color };
    });

    assert.match(result.backgroundImage, /radial-gradient\(circle at 14% 0%/);
    assert.match(result.backgroundImage, /rgba?\(31, 57, 55/);
    assert.equal(result.borderLeftColor, 'rgb(169, 207, 145)');
    assert.equal(result.borderLeftWidth, '2px');
    assert.equal(result.color, 'rgb(237, 245, 241)');
    assert.equal(toggle.backgroundColor, 'rgba(8, 18, 21, 0.34)');
    assert.equal(toggle.color, 'rgb(211, 228, 220)');
  } finally {
    await browser.close();
  }
});

test("retained content-search evidence uses readable light-theme surfaces", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    await page.setContent(`
      <style>${productionCss}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace">
        <aside id="assistantPanel">
          <section id="chatMessages">
            <article class="chat-message content-search-message">
              <div class="recommendation-wrap">
                <section class="content-search-review historical">
                  <header><div><small>已保留结果 · 选择片段</small><strong>相关片段检索完成 · 3 个证据充分</strong><p>出现小米 logo</p><p class="content-search-stats">已引用 3 条索引证据</p></div><b>核对片段</b></header>
                  <button class="content-history-toggle">收起已保留结果</button>
                  <details class="content-review-diagnostics"><summary>查找依据与诊断</summary></details>
                  <div class="content-match-list">
                    <article class="content-match-row"><div class="content-match-main"><input type="checkbox" checked><div class="content-match-copy"><div class="content-match-title"><strong>出现小米 logo · 第 1 段</strong><b class="confidence-reliable">证据充分</b></div><p class="content-match-meta">04:33.4 → 04:41.2 · 7.8 秒 · 画面</p><div class="content-evidence-chips"><i>对象语境支持</i><button class="content-evidence-count">查看证据（1）</button></div><p class="content-match-diagnostics">局部逐帧复检 · 边界：局部画面复检</p><p class="content-match-evidence"><small>匹配证据</small>画面中白色背景上清晰显示红色方形小米 MI logo</p></div></div><div class="content-match-buttons"><button class="content-match-preview">播放</button></div></article>
                  </div>
                  <div class="content-exhaustive-controls content-exhaustive-controls-bottom"><span>选择片段</span><button>取消全部</button></div>
                  <footer class="content-history-actions"><button>恢复为当前检索并编辑</button></footer>
                  <p class="content-search-safety">人物仅使用画面描述或匿名 Speaker 标签，不进行实名识别。</p>
                </section>
              </div>
            </article>
          </section>
        </aside>
      </body>`);
    await page.evaluate(() => { document.documentElement.dataset.theme = "light"; });
    await page.waitForTimeout(250);

    const audit = await page.evaluate(() => {
      const values = (value) => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
      const luminance = (value) => {
        const channels = values(value).map((channel) => channel / 255)
          .map((channel) => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
        return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
      };
      const inspect = (selector) => {
        const element = document.querySelector(selector);
        const style = getComputedStyle(element);
        let surface = element;
        while (surface.parentElement && getComputedStyle(surface).backgroundColor === "rgba(0, 0, 0, 0)") surface = surface.parentElement;
        const backgroundColor = getComputedStyle(surface).backgroundColor;
        const foreground = luminance(style.color), background = luminance(backgroundColor);
        return { background: backgroundColor, backgroundImage: style.backgroundImage,
          contrast: (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05) };
      };
      return {
        panel: inspect(".content-search-review"),
        row: inspect(".content-match-row"),
        diagnostics: inspect(".content-review-diagnostics"),
        toggle: inspect(".content-history-toggle"),
        evidence: inspect(".content-match-evidence"),
        primary: inspect(".content-match-preview"),
      };
    });

    for (const name of ["panel", "row", "diagnostics", "toggle"]) {
      const surface = audit[name];
      assert.ok(surface.contrast >= 4.5, `${name} contrast is too low: ${JSON.stringify(surface)}`);
      assert.doesNotMatch(surface.background, /rgb\((?:0|1[0-9]|2[0-9]|3[0-9]),/,
        `${name} retained a near-black background: ${surface.background}`);
    }
    assert.equal(audit.panel.backgroundImage, "none");
    assert.ok(audit.evidence.contrast >= 4.5);
    assert.ok(audit.primary.contrast >= 4.5);
  } finally {
    await browser.close();
  }
});

test("collapsed content-search summary does not retain a dark card in light theme", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    await page.setContent(`<!doctype html><html data-theme="light"><style>${productionCss}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace">
        <main id="workspace" class="studio">
          <aside id="assistantPanel"><section id="chatMessages">
            <article class="chat-message assistant content-search-message content-search-history-message current">
              <div class="recommendation-wrap"><section class="content-search-history-summary">
                <button type="button" data-content-history-open="search-1">
                  <span><small>18:38 · 当前检索</small><strong>出现小米 logo</strong></span><b>3 段</b><em>查看片段</em>
                </button>
              </section></div>
            </article>
          </section></aside>
        </main>
      </body></html>`);
    await page.waitForTimeout(250);

    const initial = await page.evaluate(() => {
      const read = (selector) => getComputedStyle(document.querySelector(selector));
      const summary = read(".content-search-history-summary");
      return {
        background: summary.backgroundColor,
        image: summary.backgroundImage,
        border: summary.borderColor,
        buttonBackground: read(".content-search-history-summary > button").backgroundColor,
        small: read(".content-search-history-summary small").color,
        title: read(".content-search-history-summary strong").color,
        count: read(".content-search-history-summary b").color,
        action: read(".content-search-history-summary em").color,
      };
    });
    assert.equal(initial.background, "rgb(247, 247, 244)");
    assert.equal(initial.image, "none");
    assert.equal(initial.buttonBackground, "rgba(0, 0, 0, 0)");
    for (const key of ["small", "title", "count", "action"]) {
      assert.notEqual(initial[key], "rgb(203, 216, 220)", `${key} retained the dark-theme text colour`);
    }

    await page.locator(".content-search-history-summary > button").hover();
    await page.waitForTimeout(250);
    assert.equal(
      await page.locator(".content-search-history-summary > button").evaluate((node) => getComputedStyle(node).backgroundColor),
      "rgb(237, 243, 238)",
    );
  } finally {
    await browser.close();
  }
});

test("portrait sample controls stay attached to the true rendered video frame", async () => {
  assert.match(appSource, /--media-rendered-width/);
  assert.match(appSource, /--portrait-shell-height/);
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 700 } });

  try {
    await page.setContent(`
      <style>*,*::before,*::after{box-sizing:border-box}${workbenchV4Css}</style>
      <style>
        html body.ct-workbench-v4 #reviewView #reviewStage { width: 718px !important; height: 540px !important; padding: 0 !important; }
        html body.ct-workbench-v4 #reviewView #reviewStage #viewerShell { position: relative !important; display: grid !important; grid-template-rows: 484px 56px !important; --media-rendered-width: 272px; }
        html body.ct-workbench-v4 #reviewView #reviewStage #mediaFrame { width: 272px !important; height: 484px !important; place-self: center !important; }
        html body.ct-workbench-v4 #reviewView #reviewStage #mainVideo { display: block !important; width: 100% !important; height: 100% !important; }
        html body.ct-workbench-v4 #reviewView #reviewStage .player-controls { position: relative !important; width: 272px !important; height: 56px !important; display: grid !important; }
      </style>
      <body class="ct-workbench-v4" data-shell-mode="workspace">
        <section id="reviewView" data-review-layout="portrait" style="--portrait-shell-width:272px;--portrait-shell-height:540px">
          <section id="reviewStage">
            <div id="viewerShell" class="viewer-shell portrait">
              <div id="mediaFrame"><video id="mainVideo"></video></div>
              <div class="player-controls">
                <div class="player-transport-group"><button id="playerPlay"></button></div>
                <div class="player-progress-group">
                  <input id="playerSeek" type="range" min="0" max="1000" value="500">
                  <span id="playerClock">00:10 / 00:20</span>
                </div>
                <button id="playerRate">1.0×</button>
                <button id="playerFullscreen">全屏</button>
              </div>
            </div>
          </section>
        </section>
      </body>`);

    const geometry = await page.evaluate(() => {
      const frame = document.querySelector('#mediaFrame').getBoundingClientRect();
      const seek = document.querySelector('#playerSeek').getBoundingClientRect();
      const shell = document.querySelector('#viewerShell').getBoundingClientRect();
      return {
        shell: { left: shell.left, right: shell.right, width: shell.width },
        frame: { left: frame.left, right: frame.right, width: frame.width },
        seek: { left: seek.left, right: seek.right, width: seek.width },
      };
    });

    assert.ok(Math.abs(geometry.shell.left - geometry.frame.left) <= 1.1, JSON.stringify(geometry));
    assert.ok(Math.abs(geometry.shell.width - geometry.frame.width) <= 2, JSON.stringify(geometry));
    assert.ok(geometry.seek.left >= geometry.frame.left, JSON.stringify(geometry));
    assert.ok(geometry.seek.right <= geometry.frame.right, JSON.stringify(geometry));
  } finally {
    await browser.close();
  }
});

test("content-search overview uses one clip colour and only shows range when zoomed", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    await page.setContent(`
      <style>${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace">
        <section id="reviewView" data-workbench-kind="content_search">
          <section id="timelinePanel">
            <div id="timelineOverview" class="timeline-overview">
              <i class="timeline-overview-clip"></i>
              <i class="timeline-overview-clip recommended"></i>
              <i class="timeline-overview-clip output used-in-output"></i>
              <i class="timeline-overview-clip unused-in-output"></i>
              <i class="timeline-view-window"></i>
              <i id="timelineOverviewPlayhead"></i>
            </div>
          </section>
        </section>
      </body>`);

    const fullView = await page.evaluate(() => ({
      clipColours: [...document.querySelectorAll('.timeline-overview-clip')].map((item) => getComputedStyle(item).backgroundColor),
      rangeDisplay: getComputedStyle(document.querySelector('.timeline-view-window')).display,
      playheadColour: getComputedStyle(document.querySelector('#timelineOverviewPlayhead')).backgroundColor,
    }));
    assert.deepEqual([...new Set(fullView.clipColours)], ['rgb(125, 169, 163)']);
    assert.equal(fullView.rangeDisplay, 'none');
    assert.equal(fullView.playheadColour, 'rgb(241, 217, 161)');

    await page.locator('#timelineOverview').evaluate((element) => element.classList.add('timeline-zoomed'));
    const zoomedRange = await page.locator('.timeline-view-window').evaluate((element) => {
      const style = getComputedStyle(element);
      return { display: style.display, backgroundColor: style.backgroundColor, borderColor: style.borderColor };
    });
    assert.equal(zoomedRange.display, 'block');
    assert.equal(zoomedRange.backgroundColor, 'rgba(0, 0, 0, 0)');
    assert.equal(zoomedRange.borderColor, 'rgba(190, 218, 203, 0.32)');
  } finally {
    await browser.close();
  }
});

test("content-search timeline removes the empty toolbar row until a toolbar exists", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });

  try {
    await page.setContent(`
      <style>${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace" data-ct-timeline-ready="true">
        <section id="reviewView" class="review-view" data-workbench-kind="content_search">
          <header class="review-header"></header>
          <section id="reviewStage"></section>
          <section id="timelinePanel" class="timeline-panel"></section>
        </section>
      </body>`);

    const compact = await page.evaluate(() => ({
      rows: getComputedStyle(document.querySelector('#reviewView')).gridTemplateRows.split(' ').length,
      timelineRow: getComputedStyle(document.querySelector('#timelinePanel')).gridRowStart,
    }));
    assert.equal(compact.rows, 3);
    assert.equal(compact.timelineRow, '3');

    await page.locator('#reviewView').evaluate((review) => {
      const toolbar = document.createElement('nav');
      toolbar.id = 'ctEditorToolbar';
      toolbar.className = 'ct-editor-toolbar';
      review.insertBefore(toolbar, document.querySelector('#timelinePanel'));
    });
    const withToolbar = await page.evaluate(() => ({
      rows: getComputedStyle(document.querySelector('#reviewView')).gridTemplateRows.split(' ').length,
      toolbarRow: getComputedStyle(document.querySelector('#ctEditorToolbar')).gridRowStart,
      timelineRow: getComputedStyle(document.querySelector('#timelinePanel')).gridRowStart,
    }));
    assert.equal(withToolbar.rows, 4);
    assert.equal(withToolbar.toolbarRow, '3');
    assert.equal(withToolbar.timelineRow, '4');
  } finally {
    await browser.close();
  }
});

test("resized assistant rail owns its internal width and wraps long messages", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  try {
    await page.setContent(`
      <style>${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace">
        <main id="workspace" class="studio">
          <aside id="assistantPanel" class="chat-panel" style="display:grid; width:350px; overflow:hidden">
            <header class="panel-header" style="min-width:479px">AI 剪辑助手</header>
            <section id="chatMessages" style="width:100%; padding:4px 14px 10px">
              <article class="chat-message assistant">
                <span class="avatar">AI</span>
                <div class="bubble"><small>智能剪辑 Agent</small><p>封面已生成并保存为当前任务封面，正在基于已审核时间线生成可下载成片；这是一条用于验证窄栏长文本必须自动换行且不能越过对话面板边界的消息。</p></div>
              </article>
            </section>
            <form id="chatForm" style="min-width:479px">输入剪辑要求</form>
          </aside>
        </main>
      </body>`);

    const geometry = await page.evaluate(() => {
      const panel = document.querySelector('#assistantPanel');
      const panelRect = panel.getBoundingClientRect();
      const messages = document.querySelector('#chatMessages').getBoundingClientRect();
      const header = document.querySelector('.panel-header').getBoundingClientRect();
      const composer = document.querySelector('#chatForm').getBoundingClientRect();
      const article = document.querySelector('.chat-message').getBoundingClientRect();
      const bubble = document.querySelector('.bubble').getBoundingClientRect();
      const paragraph = document.querySelector('.bubble p');
      const lineHeight = Number.parseFloat(getComputedStyle(paragraph).lineHeight);
      return {
        panelRight: panelRect.right,
        panelScrollWidth: panel.scrollWidth,
        panelClientWidth: panel.clientWidth,
        panelTrack: getComputedStyle(panel).gridTemplateColumns,
        messagesRight: messages.right,
        headerRight: header.right,
        composerRight: composer.right,
        articleRight: article.right,
        bubbleRight: bubble.right,
        scrollWidth: paragraph.scrollWidth,
        clientWidth: paragraph.clientWidth,
        lineCount: Math.round(paragraph.getBoundingClientRect().height / lineHeight),
      };
    });

    assert.ok(geometry.panelScrollWidth <= geometry.panelClientWidth + 1, JSON.stringify(geometry));
    assert.ok(geometry.headerRight <= geometry.panelRight + 0.5, JSON.stringify(geometry));
    assert.ok(geometry.messagesRight <= geometry.panelRight + 0.5, JSON.stringify(geometry));
    assert.ok(geometry.composerRight <= geometry.panelRight + 0.5, JSON.stringify(geometry));
    assert.ok(geometry.articleRight <= geometry.messagesRight + 0.5, JSON.stringify(geometry));
    assert.ok(geometry.bubbleRight <= geometry.messagesRight + 0.5, JSON.stringify(geometry));
    assert.ok(geometry.scrollWidth <= geometry.clientWidth + 1, JSON.stringify(geometry));
    assert.ok(geometry.lineCount >= 2, JSON.stringify(geometry));
  } finally {
    await browser.close();
  }
});

test("planning generation progress is wide and animated in the reference workspace", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 360, height: 320 } });

  try {
    await page.setContent(`<style>${tokensCss}</style><style>${css}</style><style>${referenceV3Css}</style>
      <body class="ct-faithful-v3" data-shell-mode="workspace">
        <section id="agentPlanDock" class="agent-plan-dock">
          <section class="agent-planning-live-track" aria-label="当前规划阶段" data-active-index="3">
            <header><span>当前阶段</span><strong>拆解剪辑任务</strong><b>67%</b></header>
            <div class="agent-planning-live-bar" role="progressbar" aria-label="计划生成进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="67">
              <i style="transform:scaleX(0.67)"></i>
            </div>
            <p>正在把目标拆成可执行步骤。</p>
          </section>
        </section>
      </body>`);

    const metrics = await page.locator(".agent-planning-live-bar").evaluate((bar) => {
      const rect = bar.getBoundingClientRect();
      const trackRect = bar.closest(".agent-planning-live-track").getBoundingClientRect();
      const before = getComputedStyle(bar, "::before");
      const after = getComputedStyle(bar, "::after");
      const fill = getComputedStyle(bar.querySelector("i"));
      return {
        width: rect.width,
        trackWidth: trackRect.width,
        height: rect.height,
        overflow: getComputedStyle(bar).overflow,
        beforeAnimation: before.animationName,
        afterAnimation: after.animationName,
        fillTransition: fill.transitionProperty,
      };
    });

    assert.ok(metrics.width >= metrics.trackWidth - 2, `expected live bar to fill track, got ${metrics.width}/${metrics.trackWidth}`);
    assert.ok(metrics.height >= 9, `expected thicker live bar, got ${metrics.height}`);
    assert.equal(metrics.overflow, "hidden");
    assert.equal(metrics.beforeAnimation, "agent-planning-stripe-flow");
    assert.equal(metrics.afterAnimation, "agent-planning-sweep");
    assert.match(metrics.fillTransition, /transform/);
  } finally {
    await browser.close();
  }
});

test("content editing plan card keeps readable typography and contrast in the reference workspace", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 380, height: 360 } });

  try {
    await page.setContent(`<style>${tokensCss}</style><style>${css}</style><style>${referenceV3Css}</style>
      <body class="ct-faithful-v3" data-shell-mode="workspace">
        <section id="agentPlanDock" class="agent-plan-dock" data-tone="running" data-plan-surface="agent">
          <header><small>内容剪辑计划</small><b>进行中</b></header>
          <section class="agent-plan-control" aria-label="Agent 任务控制台">
            <dl>
              <div><dt>目标</dt><dd>找出所有关于冰箱的画面，合成一个竖屏视频</dd></div>
              <div><dt>当前阶段</dt><dd>正在检索可用内容</dd></div>
              <div><dt>下一步</dt><dd>建立可审阅精剪时间线</dd></div>
            </dl>
            <small>自动执行到审核样片</small>
          </section>
        </section>
      </body>`);

    const audit = await page.locator("#agentPlanDock").evaluate((dock) => {
      const parseRgb = (value) => {
        const [r, g, b] = value.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number);
        return [r, g, b];
      };
      const luminance = ([r, g, b]) => {
        const channel = [r, g, b].map((item) => {
          const value = item / 255;
          return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * channel[0] + 0.7152 * channel[1] + 0.0722 * channel[2];
      };
      const contrast = (fg, bg) => {
        const bright = Math.max(luminance(fg), luminance(bg));
        const dark = Math.min(luminance(fg), luminance(bg));
        return (bright + 0.05) / (dark + 0.05);
      };
      const title = dock.querySelector("header small");
      const detail = dock.querySelector(".agent-plan-control dd");
      const panel = dock.querySelector(".agent-plan-control");
      const titleStyle = getComputedStyle(title);
      const detailStyle = getComputedStyle(detail);
      return {
        titleFont: Number.parseFloat(titleStyle.fontSize),
        detailFont: Number.parseFloat(detailStyle.fontSize),
        titleContrast: contrast(parseRgb(titleStyle.color), parseRgb(getComputedStyle(dock).backgroundColor)),
        detailContrast: contrast(parseRgb(detailStyle.color), parseRgb(getComputedStyle(panel).backgroundColor)),
        dockBackground: getComputedStyle(dock).backgroundColor,
        panelBackground: getComputedStyle(panel).backgroundColor,
      };
    });

    assert.ok(audit.titleFont >= 14, `title font too small: ${audit.titleFont}`);
    assert.ok(audit.detailFont >= 12, `detail font too small: ${audit.detailFont}`);
    assert.ok(audit.titleContrast >= 4.5, `title contrast too low: ${audit.titleContrast}`);
    assert.ok(audit.detailContrast >= 4.5, `detail contrast too low: ${audit.detailContrast}`);
    assert.notEqual(audit.dockBackground, "rgba(0, 0, 0, 0)");
    assert.notEqual(audit.panelBackground, "rgba(0, 0, 0, 0)");
  } finally {
    await browser.close();
  }
});

test("waiting instruction timeline uses real source thumbnails instead of solid placeholders", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });

  try {
    await page.setContent(`<style>${referenceV3Css}\n${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace">
        <main id="reviewView">
          <video id="mainVideo" src="/api/jobs/job_waiting_instruction/video"></video>
          <section id="ctTimelinePlaceholder">
            <header><strong>时间线</strong><span>提交要求后，镜头、声音与文字会在这里展开</span></header>
            <div class="ct-placeholder-ruler"><span>00:00</span><i></i><i></i><i></i><span>源片结束</span></div>
            <div class="ct-placeholder-track picture"><b>画面</b><span data-ct-source-strip><i></i><i></i><i></i><i></i><i></i></span></div>
            <div class="ct-placeholder-track audio"><b>音频</b><span aria-hidden="true"><canvas data-ct-source-waveform></canvas></span></div>
            <div class="ct-placeholder-track subtitle"><b>字幕</b><span><i></i><i></i><i></i></span></div>
            <div class="ct-placeholder-track overlay"><b>封面/文本</b><span><i></i></span></div>
            <em class="ct-placeholder-playhead" aria-hidden="true"></em>
          </section>
          <section id="timelinePanel" class="timeline-panel hidden"></section>
        </main>
        <aside id="reviewRail">
          <nav id="reviewPanelSwitch"></nav>
          <section id="ctReviewEmpty"></section>
          <section id="reviewWorkbench"></section>
          <section id="railBody"><div class="rail-empty"></div></section>
        </aside>
        <h1 id="reviewTitle">产品宣传.mp4</h1>
        <script>
          window.ClipTalkCurrentJobId = () => "job_waiting_instruction";
          window.ClipTalkCurrentJobSnapshot = () => ({ id: "job_waiting_instruction", videoInfo: { duration: 664.1 } });
          window.ClipTalkWorkspaceState = { derivePresentation: () => ({ key: "waiting_instruction", label: "等待剪辑要求" }) };
          window.fetch = async (path) => {
            if (String(path).includes("/api/jobs/job_waiting_instruction/waveform")) {
              return {
                ok: true,
                json: async () => ({
                  schemaVersion: 3,
                  duration: 664.1,
                  hasAudio: true,
                  normalizationPeak: 1,
                  minimums: [-.2, -.6, -.3, -.8, -.4, -.5],
                  maximums: [.25, .7, .35, .9, .45, .55],
                  peaks: [.25, .7, .35, .9, .45, .55],
                }),
              };
            }
            if (!String(path).includes("/api/jobs/job_waiting_instruction/timeline-assets")) throw new Error("unexpected fetch " + path);
            return {
              ok: true,
              json: async () => ({
                schemaVersion: 4,
                duration: 664.1,
                spriteUrl: "/api/jobs/job_waiting_instruction/timeline-sprite?revision=test",
                sprite: {
                  columns: 4,
                  rows: 2,
                  items: Array.from({ length: 8 }, (_, index) => ({
                    index,
                    time: index * 83,
                    column: index % 4,
                    row: Math.floor(index / 4),
                  })),
                },
              }),
            };
          };
        </script>
        <script>${timelinePresentationJs}</script>
      </body>`);

    await page.evaluate(() => window.ClipTalkTimelinePresentation.sync());

    await page.waitForFunction(() => document.querySelector("#ctTimelinePlaceholder")?.dataset.ctTimelineAssetState === "ready");
    await page.waitForFunction(() => document.querySelector("#ctTimelinePlaceholder")?.dataset.ctWaveformState === "ready");

    const audit = await page.locator("#ctTimelinePlaceholder").evaluate((placeholder) => {
      const frames = [...placeholder.querySelectorAll(".ct-source-frame")];
      return {
        state: placeholder.dataset.ctTimelineAssetState,
        frameCount: frames.length,
        firstBackground: getComputedStyle(frames[0]).backgroundImage,
        hasSolidPlaceholders: Boolean(placeholder.querySelector(".picture > span > i:not(.ct-source-frame)")),
        ruler: placeholder.querySelector(".ct-placeholder-ruler").textContent,
        hint: placeholder.querySelector("header span").textContent,
        waveformState: placeholder.dataset.ctWaveformState,
        waveformPaintedPixels: (() => {
          const canvas = placeholder.querySelector("[data-ct-source-waveform]");
          const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
          let painted = 0;
          for (let index = 3; index < pixels.length; index += 4) if (pixels[index]) painted += 1;
          return painted;
        })(),
      };
    });
    const emptyPanelText = await page.locator("#ctReviewEmpty").textContent();

    await page.evaluate(() => {
      const video = document.querySelector("#mainVideo");
      window.__sourceTimelineTestTime = 0;
      Object.defineProperty(video, "duration", { configurable: true, get: () => 664.1 });
      Object.defineProperty(video, "currentTime", { configurable: true, get: () => window.__sourceTimelineTestTime });
      Object.defineProperty(video, "paused", { configurable: true, get: () => false });
      Object.defineProperty(video, "ended", { configurable: true, get: () => false });
      video.dispatchEvent(new Event("play"));
    });
    await page.waitForTimeout(30);
    await page.evaluate(() => {
      window.__sourceTimelineTestTime = 332.05;
      document.querySelector("#mainVideo").dispatchEvent(new Event("timeupdate"));
    });
    const playheadAudit = await page.locator("#ctTimelinePlaceholder").evaluate((placeholder) => {
      const strip = placeholder.querySelector(".picture > span").getBoundingClientRect();
      const playhead = placeholder.querySelector(".ct-placeholder-playhead").getBoundingClientRect();
      document.querySelector("#mainVideo").dispatchEvent(new Event("pause"));
      return {
        actual: playhead.left,
        expected: strip.left + strip.width / 2,
        progress: Number(placeholder.dataset.ctPlaybackProgress),
      };
    });

    assert.equal(audit.state, "ready");
    assert.equal(audit.frameCount, 8);
    assert.match(audit.firstBackground, /timeline-sprite\?revision=test/);
    assert.equal(audit.hasSolidPlaceholders, false);
    assert.match(audit.ruler, /11:04/);
    assert.match(audit.hint, /源视频已就绪/);
    assert.equal(audit.waveformState, "ready");
    assert.ok(audit.waveformPaintedPixels > 0);
    assert.ok(Math.abs(playheadAudit.actual - playheadAudit.expected) < 2);
    assert.ok(Math.abs(playheadAudit.progress - .5) < .001);
    assert.doesNotMatch(emptyPanelText, /描述剪辑要求/);
    assert.equal(await page.locator("#ctReviewEmpty [data-ct-focus-composer], #ctReviewEmpty .ct-review-guide-action").count(), 0);
  } finally {
    await browser.close();
  }
});

test("pending timeline assets stay in a generating state instead of becoming an empty ready track", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });

  try {
    await page.setContent(`<style>${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace">
        <main id="reviewView">
          <video id="mainVideo" src="/api/jobs/job_timeline_pending/video"></video>
          <section id="ctTimelinePlaceholder">
            <header><strong>时间线</strong><span>等待时间轴资源</span></header>
            <div class="ct-placeholder-ruler"><span>00:00</span><i></i><span>源片结束</span></div>
            <div class="ct-placeholder-track picture"><b>画面</b><span data-ct-source-strip><i></i><i></i></span></div>
            <div class="ct-placeholder-track audio"><b>音频</b><span><canvas data-ct-source-waveform></canvas></span></div>
          </section>
        </main>
        <script>
          window.ClipTalkCurrentJobId = () => "job_timeline_pending";
          window.fetch = async (path) => {
            if (String(path).includes("/waveform")) return { ok: true, json: async () => ({ duration: 60, hasAudio: false }) };
            return { ok: true, json: async () => ({ ready: false, generating: true, retryAfterSeconds: 1 }) };
          };
        </script>
        <script>${timelinePresentationJs}</script>
      </body>`);

    await page.waitForFunction(() => document.querySelector("#ctTimelinePlaceholder")?.dataset.ctTimelineAssetState === "loading");
    const state = await page.locator("#ctTimelinePlaceholder").evaluate((node) => ({
      assetState: node.dataset.ctTimelineAssetState,
      hint: node.querySelector("header span").textContent,
      frames: node.querySelectorAll(".ct-source-frame").length,
    }));
    assert.equal(state.assetState, "loading");
    assert.match(state.hint, /正在生成时间轴缩略图/);
    assert.equal(state.frames, 0);
  } finally {
    await browser.close();
  }
});

test("workbench control styling preserves timeline thumbnail sprite images", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    await page.setContent(`<style>${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace">
        <section id="timelinePanel" class="timeline-panel">
          <div id="timelineViewport" class="timeline-viewport">
            <button
              class="timeline-thumbnail"
              type="button"
              style="width:160px;height:90px;background-image:url('data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==')"
            ></button>
            <button class="timeline-toolbar-action" type="button">普通控件</button>
          </div>
        </section>
      </body>`);

    const audit = await page.evaluate(() => {
      const thumbnail = document.querySelector(".timeline-thumbnail");
      const control = document.querySelector(".timeline-toolbar-action");
      return {
        thumbnailImage: getComputedStyle(thumbnail).backgroundImage,
        controlColor: getComputedStyle(control).backgroundColor,
      };
    });

    assert.match(audit.thumbnailImage, /^url\(/);
    assert.notEqual(audit.thumbnailImage, "none");
    assert.notEqual(audit.controlColor, "rgba(0, 0, 0, 0)");
  } finally {
    await browser.close();
  }
});

test("compact v4 workspace keeps inactive panels inside the viewport", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });

  try {
    await page.setContent(`<style>${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace" data-ct-compact-view="preview">
        <main id="workspace" class="studio director-merged">
          <nav id="ctCompactWorkspaceNav" class="ct-compact-workspace-nav"></nav>
          <aside id="assistantPanel" class="chat-panel"></aside>
          <section class="review-panel glass-panel"><div id="reviewView" class="review-view"></div></section>
          <aside id="reviewRail" class="review-rail"></aside>
        </main>
      </body>`);

    const audit = async () => page.evaluate(() => {
      const readPanel = (selector) => {
        const element = document.querySelector(selector);
        const rect = element.getBoundingClientRect();
        return { display: getComputedStyle(element).display, left: rect.left, right: rect.right, width: rect.width };
      };
      return {
        workspaceDisplay: getComputedStyle(document.querySelector("#workspace")).display,
        assistant: readPanel("#assistantPanel"),
        preview: readPanel(".review-panel"),
        review: readPanel("#reviewRail"),
        viewport: window.innerWidth,
      };
    });

    const preview = await audit();
    assert.equal(preview.workspaceDisplay, "block");
    assert.equal(preview.assistant.display, "none");
    assert.equal(preview.preview.display, "grid");
    assert.equal(preview.review.display, "none");
    assert.ok(preview.preview.right <= preview.viewport);

    await page.evaluate(() => { document.body.dataset.ctCompactView = "review"; });
    const review = await audit();
    assert.equal(review.preview.display, "none");
    assert.equal(review.review.display, "flex");
    assert.ok(review.review.right <= review.viewport);
  } finally {
    await browser.close();
  }
});

test("model recovery decision stays readable inside the narrow assistant rail", async () => {
  assert.match(appSource, /status\.classList\.add\("chat-analysis-console"\)/);
  assert.match(appSource, /job\?\.status !== "awaiting_model_decision"/);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 760 } });

  try {
    await page.setContent(`<style>${referenceV3Css}</style><style>${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace">
        <main id="workspace" class="studio director-merged" style="height:760px">
          <aside id="assistantPanel" class="chat-panel" style="height:760px">
            <header class="panel-header"></header>
            <section id="chatMessages" class="chat-messages">
              <section id="jobStatus" class="analysis-console chat-analysis-console decision-mode">
                <div class="progress-orb"><span>AI</span><b>6%</b></div>
                <div class="analysis-copy"><small>AI 分析</small><strong>等待选择</strong></div>
                <ol class="stage-chain"><li>准备</li><li>语音</li><li>视觉</li></ol>
                <div id="analysisDecision" class="analysis-decision">
                  <p><b>语言分析未完成。</b>语音仅用于辅助判断，不影响继续进行视觉高光分析。</p>
                  <small class="analysis-decision-reason"><b>原因</b>_sensevoice_instance() got an unexpected keyword argument algorithm_version</small>
                  <button class="primary">继续视觉分析</button><button>重试语音分析</button><button>取消任务</button>
                </div>
                <button id="cancelButton">停止分析</button><p id="jobError"></p>
              </section>
            </section>
            <form id="chatForm" class="chat-composer"><div class="chat-input-shell"></div></form>
          </aside>
          <section class="review-panel"></section>
        </main>
      </body>`);

    const metrics = await page.evaluate(() => {
      const host = document.querySelector("#jobStatus");
      const hostRect = host.getBoundingClientRect();
      const visibleChildren = [...host.querySelectorAll("*")].filter((node) => {
        const rect = node.getBoundingClientRect();
        return getComputedStyle(node).display !== "none" && rect.width > 0 && rect.height > 0;
      });
      return {
        hostWidth: hostRect.width,
        hostClientWidth: host.clientWidth,
        hostScrollWidth: host.scrollWidth,
        orbDisplay: getComputedStyle(host.querySelector(".progress-orb")).display,
        stageListDisplay: getComputedStyle(host.querySelector(".stage-chain")).display,
        decisionDisplay: getComputedStyle(host.querySelector("#analysisDecision")).display,
        buttonCount: host.querySelectorAll("#analysisDecision button").length,
        overflowCount: visibleChildren.filter((node) => {
          const rect = node.getBoundingClientRect();
          return rect.left < hostRect.left - .5 || rect.right > hostRect.right + .5;
        }).length,
      };
    });

    assert.ok(metrics.hostWidth <= 480);
    assert.ok(metrics.hostScrollWidth <= metrics.hostClientWidth);
    assert.equal(metrics.orbDisplay, "none");
    assert.equal(metrics.stageListDisplay, "none");
    assert.equal(metrics.decisionDisplay, "grid");
    assert.equal(metrics.buttonCount, 3);
    assert.equal(metrics.overflowCount, 0);
  } finally {
    await browser.close();
  }
});

test("waiting instruction keeps one message scroller and a compact action dock above the composer", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 760 } });

  try {
    await page.setContent(`<style>${referenceV3Css}</style><style>${workbenchV4Css}</style>
      <body class="ct-workbench-v4" data-shell-view="workspace" data-shell-mode="workspace" data-workspace-state="awaiting_instruction">
        <main id="workspace" class="studio director-merged" style="height:760px">
          <aside id="assistantPanel" class="chat-panel" style="height:760px">
            <nav id="appSidebar"></nav>
            <header class="panel-header"><div class="director"><strong>剪辑助理</strong><small>等待素材</small></div></header>
            <section id="chatMessages" class="chat-messages">
              <article class="chat-message assistant agent-draft-modes"><span class="avatar">AI</span><div class="bubble"><p>我已拿到源视频，请告诉我想保留什么，也可以选择快捷剪辑模式。</p></div></article>
            </section>
            <section id="assistantActionDock" class="assistant-action-dock">
              <div class="assistant-action-summary"><i class="assistant-action-icon"></i><button class="assistant-action-copy"><small>处理方式 · 推荐</small><strong>自动选择</strong><span>根据描述匹配剪辑能力</span></button><button class="assistant-action-change">选择</button></div>
            </section>
            <section id="ctV4AssistantQuickStart" class="ct-v4-assistant-quick-start capability-drawer hidden" aria-hidden="true">
              <header><strong>快捷开始</strong></header>
              <section id="quickWorkflowPicker" class="quick-workflow-picker">
                <header><strong>今天想创作什么？</strong><p>选择一种方式开始，不会复用上一次任务进度。</p></header>
                <div class="legacy-workflow-grid"><button class="legacy-workflow-card"><i class="legacy-workflow-thumb"></i><span><strong>内容探索</strong><small>按你的描述查找画面、动作、对白、文字或声音。</small></span></button></div>
              </section>
            </section>
            <form id="chatForm" class="chat-composer">
              <div class="chat-input-shell"><textarea id="chatInput" placeholder="描述你想剪什么"></textarea></div>
            </form>
          </aside>
        </main>
      </body>`);

    const metrics = await page.evaluate(() => {
      const rect = (selector) => document.querySelector(selector).getBoundingClientRect();
      const panel = rect("#assistantPanel");
      const messages = rect("#chatMessages");
      const lastMessage = rect("#chatMessages > .chat-message:last-child");
      const actionDock = rect("#assistantActionDock");
      const inputShell = rect(".chat-input-shell");
      const form = rect("#chatForm");
      const messageStyle = getComputedStyle(document.querySelector("#chatMessages"));
      const drawerStyle = getComputedStyle(document.querySelector("#ctV4AssistantQuickStart"));
      return {
        messageFlexGrow: messageStyle.flexGrow,
        messageTopMargin: Math.round(Number.parseFloat(messageStyle.marginTop) || 0),
        messageOverflow: messageStyle.overflowY,
        drawerDisplay: drawerStyle.display,
        actionDockTop: Math.round(actionDock.top),
        actionDockBottom: Math.round(actionDock.bottom),
        lastMessageBottom: Math.round(lastMessage.bottom),
        panelBottom: Math.round(panel.bottom),
        actionToInputGap: Math.round(inputShell.top - actionDock.bottom),
        composerBottomReserve: Math.round(panel.bottom - form.bottom),
        messagesHeight: Math.round(messages.height),
      };
    });

    assert.ok(Number(metrics.messageFlexGrow) >= 0);
    assert.equal(metrics.messageTopMargin, 0);
    assert.match(metrics.messageOverflow, /auto|hidden/);
    assert.equal(metrics.drawerDisplay, "none");
    assert.ok(metrics.actionDockTop >= metrics.lastMessageBottom, "the action dock should follow the conversation");
    assert.ok(metrics.actionDockBottom <= metrics.panelBottom, "the action dock should stay inside the assistant panel");
    assert.ok(metrics.actionToInputGap >= 0, `the action dock overlaps the input box: ${metrics.actionToInputGap}px`);
    assert.ok(metrics.composerBottomReserve <= 16, `composer is not pinned to the bottom: ${metrics.composerBottomReserve}px`);
    assert.ok(metrics.messagesHeight >= 0);
  } finally {
    await browser.close();
  }
});

test("completed social preview is visible and opens from Agent review results", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 720 } });

  try {
    await page.setContent(`<style>${css}</style>
      <body data-shell-mode="workspace">
        <aside class="chat-panel">
          <section id="agentPlanDock" class="agent-plan-dock hidden"></section>
          <button id="agentPlanDrawerScrim" class="hidden"></button>
          <aside id="agentPlanDrawer" class="agent-plan-drawer hidden" aria-hidden="true">
            <header><div><small id="agentPlanDrawerKicker"></small><strong id="agentPlanDrawerTitle"></strong></div><button id="agentPlanDrawerClose"></button></header>
            <nav><button data-agent-drawer-tab="plan"></button><button data-agent-drawer-tab="activity"></button></nav>
            <section id="agentPlanDrawerPlan" data-agent-drawer-panel="plan"></section>
            <section id="agentPlanDrawerActivity" data-agent-drawer-panel="activity"></section>
            <footer id="agentPlanDrawerFooter"></footer>
          </aside>
          <section id="chatMessages"></section>
        </aside>
        <script>
          window.__openedAgentPreview = null;
          window.__openedAgentEditor = false;
          window.ClipTalkApi = { requestJson: async (path) => {
            if (path.includes('/api/agent/workspaces/')) return window.__agentDetail;
            if (path.includes('/api/agent/skills')) return { skills: [] };
            if (path.includes('/api/settings/agent')) return { providers: [] };
            return {};
          } };
          window.ClipTalkCurrentJobId = () => 'job_social_preview';
          window.ClipTalkCurrentJobSnapshot = () => window.__currentAgentJob || ({ id: 'job_social_preview', outputs: [], outputVersions: [] });
          window.ClipTalkOpenAgentPreview = async (payload) => { window.__openedAgentPreview = payload; return true; };
          window.ClipTalkOpenAgentReview = async () => { window.__openedAgentEditor = true; return true; };
          window.ClipTalkRefreshCurrentJob = () => {};
          window.showToast = () => {};
          window.EventSource = class { addEventListener() {} close() {} };
        </script>
        <script>${agent}</script>`);

    await page.evaluate(async () => {
      const review = {
        kind: "review_preview", sessionId: "edit_review", title: "横版时间线样片",
        duration: 4.801, previewUrl: "/review.mp4",
      };
      const social = {
        filename: "agent-social-9x16-test.mp4", title: "9:16 社媒审核预览",
        duration: 4.833, width: 540, height: 960,
        previewUrl: "/social.mp4", videoUrl: "/social.mp4",
        outputKind: "social_reframe_preview", socialReframe: true,
        reframe: { aspect: "9:16", fit: "crop" },
      };
      window.__currentAgentJob = {
        id: "job_social_preview", outputs: [], outputVersions: [],
        agentPreviewOutputs: [{
          filename: "agent-social-9x16-blur.mp4", title: "9:16 虚化背景审核预览",
          planId: "plan_social",
          duration: 4.833, width: 540, height: 960,
          previewUrl: "/social-blur.mp4", videoUrl: "/social-blur.mp4",
          outputKind: "social_reframe_preview", socialReframe: true,
          reframe: { aspect: "9:16", fit: "blur" },
        }],
      };
      const plan = {
        id: "plan_social", workspaceId: "ws_social", status: "preview_ready",
        skillId: "cliptalk-content-extractor", executionMode: "autonomous_review",
        summary: "已生成普通审核样片和竖屏审核预览。",
        steps: [
          { id: "review", status: "completed", result: { artifact: { kind: "review_preview_batch", previews: [review] } } },
          { id: "social", status: "completed", result: { artifact: { kind: "social_reframe_preview", output: social } } },
          { id: "cover", title: "生成可选封面", status: "skipped" },
          { id: "qc", tool: "run_delivery_qc", title: "检查社媒预览质量", status: "completed", result: { artifact: {
            kind: "delivery_qc_report", passed: false,
            reports: [{ issues: [{
              severity: "error", code: "target_duration_mismatch",
              message: "成片时长不在目标范围内。",
              evidence: { ranges: [{ start: 8, end: 13, duration: 5 }] },
            }] }],
          } } },
        ],
      };
      window.__agentDetail = {
        workspace: { id: "ws_social", jobId: "job_social_preview", activePlanId: "plan_social" },
        plans: [plan],
      };
      await window.ClipTalkAgentWorkspace.resumeForJob({
        id: "job_social_preview", revision: 1,
        agent: { workspaceId: "ws_social", planId: "plan_social" },
      });
    });

    const results = page.locator("#agentPlanDrawerPlan .agent-review-results button");
    assert.equal(await results.count(), 3);
    assert.match(await page.locator("#agentPlanDock").textContent(), /审核样片待修正/);
    assert.match(await page.locator("#agentPlanDock").textContent(), /质检未通过/);
    assert.match(await page.locator("#agentPlanDock").textContent(), /播放问题片段 00:08–00:13/);
    assert.match(await page.locator("#agentPlanDock").textContent(), /修正并重新质检/);
    assert.match(await page.locator("#agentPlanDock").textContent(), /执行 4\/4 · 跳过 1/);
    assert.equal(await page.locator("#agentPlanDock [data-qc-start]").getAttribute("data-qc-start"), "8");
    assert.equal(await page.locator("#agentPlanDock .assistant-plan-summary").count(), 1, "Compact summary is collapsible; execution details stay in the drawer");
    const segmentColours = await page.locator("#agentPlanDrawerPlan .agent-plan-segments i").evaluateAll((items) =>
      items.map((item) => ({ state: item.dataset.state, colour: getComputedStyle(item).backgroundColor })));
    assert.notEqual(
      segmentColours.find((item) => item.state === "completed")?.colour,
      segmentColours.find((item) => item.state === "skipped")?.colour,
    );
    assert.doesNotMatch(await page.locator("#agentPlanDock").textContent(), /查看.*审核预览/);
    assert.match(await page.locator("#agentPlanDrawerPlan .agent-qc-summary").textContent(), /成片时长不在目标范围内/);
    assert.match(await results.nth(0).textContent(), /9:16 虚化背景审核预览/);
    assert.match(await results.nth(0).textContent(), /540×960 · 9:16 · 虚化背景/);
    assert.match(await results.nth(1).textContent(), /9:16 社媒审核预览/);
    assert.match(await results.nth(2).textContent(), /横版时间线样片/);

    await results.nth(0).click();
    assert.deepEqual(await page.evaluate(() => window.__openedAgentPreview), {
      filename: "agent-social-9x16-blur.mp4",
      planId: "plan_social",
      previewUrl: "/social-blur.mp4",
      videoUrl: "/social-blur.mp4",
      title: "9:16 虚化背景审核预览",
      width: 540,
      height: 960,
      duration: 4.833,
      outputKind: "social_reframe_preview",
      socialReframe: true,
      reframe: { aspect: "9:16", fit: "blur" },
      kind: "social_reframe_preview",
      aspect: "9:16",
    });

    await page.evaluate(() => {
      window.__openedAgentPreview = null;
      document.querySelector('#agentPlanDrawerPlan [data-agent-review-open][data-session-id="edit_review"]').click();
    });
    const standardPreview = await page.evaluate(() => window.__openedAgentPreview);
    assert.equal(standardPreview.sessionId, "edit_review");
    assert.equal(standardPreview.previewUrl, "/review.mp4");
    assert.equal(standardPreview.outputKind, "review_preview");
    assert.equal(await page.evaluate(() => window.__openedAgentEditor), false,
      "playing a timeline-backed review sample must not enter the secondary editor");
  } finally {
    await browser.close();
  }
});

test("an external cover mismatch stays visible and blocks final generation", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 720 } });

  try {
    await page.setContent(`<style>${productionCss}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace">
        <aside id="assistantPanel" class="chat-panel">
          <section id="agentPlanDock" class="agent-plan-dock hidden"></section>
          <button id="agentPlanDrawerScrim" class="hidden"></button>
          <aside id="agentPlanDrawer" class="agent-plan-drawer hidden" aria-hidden="true">
            <header><div><small id="agentPlanDrawerKicker"></small><strong id="agentPlanDrawerTitle"></strong></div><button id="agentPlanDrawerClose"></button></header>
            <nav><button data-agent-drawer-tab="plan"></button><button data-agent-drawer-tab="activity"></button></nav>
            <section id="agentPlanDrawerPlan" data-agent-drawer-panel="plan"></section>
            <section id="agentPlanDrawerActivity" data-agent-drawer-panel="activity"></section>
            <footer id="agentPlanDrawerFooter"></footer>
          </aside>
          <section id="chatMessages"></section>
          <textarea id="chatInput"></textarea>
        </aside>
        <script>
          window.ClipTalkApi = { requestJson: async (path) => path.includes('/api/agent/workspaces/') ? window.__agentDetail : { skills: [], providers: [] } };
          window.ClipTalkCurrentJobId = () => 'job_cover_mismatch';
          window.ClipTalkCurrentJobSnapshot = () => window.__currentAgentJob;
          window.ClipTalkRefreshCurrentJob = () => {};
          window.showToast = () => {};
          window.EventSource = class { addEventListener() {} close() {} };
        </script>
        <script>${agent}</script>`);

    await page.evaluate(async () => {
      const goal = '找出汽车画面，合成竖屏视频，并找到小米创始人雷军的照片作为封面，封面上写上小米牛逼，雷军牛逼！！！';
      window.__currentAgentJob = {
        id: 'job_cover_mismatch', outputs: [], outputVersions: [],
        currentCoverVersionId: 'cover_v001',
        coverVersions: [{
          id: 'cover_v001', previewUrl: '/wrong-source-cover.jpg', titleText: '',
          provenance: { kind: 'source_frame_composite' },
        }],
        agentReviewPreviews: [{
          kind: 'review_preview', sessionId: 'edit_review', title: '当前审核样片',
          duration: 12, previewUrl: '/review.mp4',
        }],
      };
      const plan = {
        id: 'plan_cover_mismatch', workspaceId: 'ws_cover_mismatch', status: 'preview_ready',
        skillId: 'cliptalk-content-extractor', executionMode: 'autonomous_review', goal,
        brief: { goal, coverRequested: true }, summary: '审核样片已生成。',
        steps: [
          { id: 'cover', tool: 'confirm_cover', title: '保存当前任务封面', status: 'completed' },
          { id: 'preview', tool: 'render_review_preview', title: '生成审核样片', status: 'completed' },
        ],
      };
      window.__agentDetail = {
        workspace: { id: 'ws_cover_mismatch', jobId: 'job_cover_mismatch', activePlanId: plan.id },
        plans: [plan],
      };
      await window.ClipTalkAgentWorkspace.resumeForJob({
        id: 'job_cover_mismatch', revision: 1,
        agent: { workspaceId: 'ws_cover_mismatch', planId: plan.id },
      });
    });

    const dock = page.locator('#agentPlanDock');
    assert.match(await dock.textContent(), /封面需要处理/);
    assert.match(await dock.textContent(), /不是“小米创始人雷军”的外部图片/);
    assert.match(await dock.textContent(), /封面文字与要求不一致/);
    assert.match(await dock.textContent(), /要求文字：小米牛逼，雷军牛逼！！！/);
    assert.equal(await dock.locator('.agent-cover-status img').count(), 1);
    assert.equal(await dock.locator('[data-agent-preview-export]').count(), 0);
    assert.equal(await dock.locator('[data-agent-replan]').textContent(), '修改封面要求');
  } finally {
    await browser.close();
  }
});

test("completed composite plan opens final cover-intro vertical preview before cover utilities", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 720 } });

  try {
    await page.setContent(`<style>${css}</style>
      <body data-shell-mode="workspace">
        <aside class="chat-panel">
          <section id="agentPlanDock" class="agent-plan-dock hidden"></section>
          <button id="agentPlanDrawerScrim" class="hidden"></button>
          <aside id="agentPlanDrawer" class="agent-plan-drawer hidden" aria-hidden="true">
            <header><div><small id="agentPlanDrawerKicker"></small><strong id="agentPlanDrawerTitle"></strong></div><button id="agentPlanDrawerClose"></button></header>
            <nav><button data-agent-drawer-tab="plan"></button><button data-agent-drawer-tab="activity"></button></nav>
            <section id="agentPlanDrawerPlan" data-agent-drawer-panel="plan"></section>
            <section id="agentPlanDrawerActivity" data-agent-drawer-panel="activity"></section>
            <footer id="agentPlanDrawerFooter"></footer>
          </aside>
          <section id="chatMessages"></section>
        </aside>
        <script>
          window.__openedAgentPreview = null;
          window.ClipTalkApi = { requestJson: async (path) => {
            if (path.includes('/api/agent/workspaces/')) return window.__agentDetail;
            if (path.includes('/api/agent/skills')) return { skills: [] };
            if (path.includes('/api/settings/agent')) return { providers: [] };
            return {};
          } };
          window.ClipTalkCurrentJobId = () => 'job_composite_preview';
          window.ClipTalkCurrentJobSnapshot = () => window.__currentAgentJob;
          window.ClipTalkOpenAgentPreview = async (payload) => { window.__openedAgentPreview = payload; return true; };
          window.ClipTalkOpenAgentReview = async () => true;
          window.ClipTalkRefreshCurrentJob = () => {};
          window.showToast = () => {};
          window.EventSource = class { addEventListener() {} close() {} };
        </script>
        <script>${agent}</script>`);

    await page.evaluate(async () => {
      window.__currentAgentJob = {
        id: "job_composite_preview",
        currentCoverVersionId: "cover_current",
        coverVersions: [{
          id: "cover_current",
          previewUrl: "/cover.jpg",
          aspectRatio: "9:16",
          direction: "source_editorial",
          score: { total: 86 },
        }],
        outputs: [],
        outputVersions: [],
        agentPreviewOutputs: [
          {
            filename: "agent-social-9x16-blur.mp4",
            title: "9:16 虚化背景审核预览",
            duration: 27.5,
            width: 1080,
            height: 1920,
            previewUrl: "/social.mp4",
            videoUrl: "/social.mp4",
            outputKind: "social_reframe_preview",
            socialReframe: true,
            reframe: { aspect: "9:16", fit: "blur" },
          },
          {
            filename: "agent-cover-intro-preview.mp4",
            title: "带封面片头的审核样片",
            duration: 28.5,
            width: 1080,
            height: 1920,
            previewUrl: "/cover-intro.mp4",
            videoUrl: "/cover-intro.mp4",
            outputKind: "cover_intro_review_preview",
            previewOnly: true,
            reframe: { aspect: "9:16", fit: "blur" },
            coverIntro: { enabled: true, duration: 1, coverVersionId: "cover_current" },
          },
        ],
      };
      const plan = {
        id: "plan_composite", workspaceId: "ws_composite", status: "preview_ready",
        skillId: "cliptalk-content-extractor", executionMode: "autonomous_review",
        summary: "找出汽车画面，生成顶部字幕、竖屏审核样片和当前任务封面片头。",
        steps: [
          { id: "sub_layout", tool: "layout_subtitles", title: "应用顶部字幕排版", status: "completed" },
          { id: "social", tool: "render_social_preview", title: "生成 9:16 社媒审核预览", status: "completed" },
          { id: "cover", tool: "confirm_cover", title: "保存当前任务封面", status: "completed" },
          { id: "intro", tool: "compose_cover_intro", title: "合成封面片头审核样片", status: "completed" },
          { id: "qc", tool: "run_delivery_qc", title: "检查最终审核样片质量", status: "completed" },
        ],
      };
      window.__agentDetail = {
        workspace: { id: "ws_composite", jobId: "job_composite_preview", activePlanId: "plan_composite" },
        plans: [plan],
      };
      window.__currentAgentJob.agentPreviewOutputs.forEach((item) => { item.planId = plan.id; });
      await window.ClipTalkAgentWorkspace.resumeForJob({
        id: "job_composite_preview", revision: 1,
        agent: { workspaceId: "ws_composite", planId: "plan_composite" },
      });
    });

    const dockText = await page.locator("#agentPlanDock").textContent();
    assert.match(dockText, /播放带封面片头的9:16样片/);
    assert.match(dockText, /生成成片/);
    assert.match(dockText, /待确认/);
    assert.match(dockText, /样片已生成，确认无误后即可生成成片/);
    assert.doesNotMatch(dockText, /审核样片待确认生成成片/);
    assert.match(dockText, /查看封面/);
    assert.doesNotMatch(dockText, /打开封面时间轴/);

    const results = page.locator("#agentPlanDrawerPlan .agent-review-results button");
    assert.equal(await results.count(), 2);
    assert.match(await results.nth(0).textContent(), /带封面片头的审核样片/);
    assert.match(await results.nth(0).textContent(), /封面片头/);

    await page.locator("#agentPlanDock [data-agent-review-open]").evaluate((button) => button.click());
    assert.deepEqual(await page.evaluate(() => window.__openedAgentPreview), {
      filename: "agent-cover-intro-preview.mp4",
      planId: "plan_composite",
      previewUrl: "/cover-intro.mp4",
      videoUrl: "/cover-intro.mp4",
      title: "带封面片头的审核样片",
      width: 1080,
      height: 1920,
      duration: 28.5,
      outputKind: "cover_intro_review_preview",
      previewOnly: true,
      reframe: { aspect: "9:16", fit: "blur" },
      coverIntro: { enabled: true, duration: 1, coverVersionId: "cover_current" },
      kind: "cover_intro_review_preview",
      aspect: "9:16",
    });
  } finally {
    await browser.close();
  }
});

test("plan details and revision editor follow both workspace themes", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 720 } });

  const assertThemeTone = async (locator, property, light) => {
    const rgb = await locator.evaluate((node, name) => getComputedStyle(node)[name], property);
    const channels = rgb.match(/[\d.]+/g).slice(0, 3).map(Number);
    assert.equal(channels.reduce((sum, value) => sum + value, 0) / 3 > 150, light, `${property}: ${rgb}`);
  };
  try {
    await page.setContent(`<style>${productionCss}</style>
      <body class="ct-workbench-v4" data-shell-mode="workspace">
        <aside id="assistantPanel" class="chat-panel">
          <section id="agentPlanDock" class="agent-plan-dock hidden"></section>
          <button id="agentPlanDrawerScrim" class="hidden"></button>
          <aside id="agentPlanDrawer" class="agent-plan-drawer hidden" aria-hidden="true">
            <header><div><small id="agentPlanDrawerKicker"></small><strong id="agentPlanDrawerTitle"></strong></div><button id="agentPlanDrawerClose"></button></header>
            <nav><button data-agent-drawer-tab="plan"></button><button data-agent-drawer-tab="activity"></button></nav>
            <section id="agentPlanDrawerPlan" class="agent-plan-drawer-panel" data-agent-drawer-panel="plan"></section>
            <section id="agentPlanDrawerActivity" class="agent-plan-drawer-panel" data-agent-drawer-panel="activity"></section>
            <footer id="agentPlanDrawerFooter"></footer>
          </aside>
          <section id="chatMessages"></section>
        </aside>
        <script>
          window.ClipTalkApi = { requestJson: async (path) => path.includes('/api/agent/skills') ? { skills: [] } : window.__agentDetail };
          window.ClipTalkCurrentJobId = () => 'job_revision';
          window.ClipTalkCurrentJobSnapshot = () => ({ id: 'job_revision', outputs: [], outputVersions: [] });
          window.ClipTalkRefreshCurrentJob = () => {};
          window.showToast = () => {};
          window.EventSource = class { addEventListener() {} close() {} };
        </script>
        <script>${agent}</script>`);

    await page.evaluate(async () => {
      const plan = {
        id: 'plan_revision', workspaceId: 'ws_revision', status: 'awaiting_confirmation',
        skillId: 'cliptalk-content-extractor', executionMode: 'autonomous_review',
        summary: '重新整理现有时间线并生成审核版本。',
        steps: [
          { id: 'step_done', title: '核查现有时间线', status: 'completed' },
          { id: 'step_waiting', tool: 'propose_timeline_edit', title: '建立二次精剪草案', status: 'pending', expectedOutput: '待审核时间线草案' },
        ],
      };
      window.__agentDetail = {
        workspace: { id: 'ws_revision', jobId: 'job_revision', activePlanId: 'plan_revision' },
        plans: [plan],
      };
      await window.ClipTalkAgentWorkspace.resumeForJob({
        id: 'job_revision', revision: 1,
        agent: { workspaceId: 'ws_revision', planId: 'plan_revision' },
      });
    });

    const drawer = page.locator('#agentPlanDrawer');
    const dock = page.locator('#agentPlanDock');
    assert.equal(await drawer.evaluate((node) => node.parentElement === document.body), true,
      'the workspace-wide plan drawer must not remain inside the clipped assistant rail');
    await dock.locator('[data-agent-plan-open]').evaluate((button) => button.click());
    await page.waitForTimeout(50);
    assert.equal(await drawer.getAttribute('aria-hidden'), 'false');
    assert.equal(await drawer.evaluate((node) => !node.classList.contains('hidden')), true);
    await page.locator('#agentPlanDrawerClose').evaluate((button) => button.click());
    assert.equal(await drawer.getAttribute('data-plan-surface'), 'editor');
    assert.equal(await dock.getAttribute('data-plan-surface'), 'editor');
    await assertThemeTone(dock, "backgroundColor", false);
    await assertThemeTone(dock.locator('.agent-plan-control dd').first(), "color", true);
    await assertThemeTone(drawer, "backgroundColor", false);
    await assertThemeTone(drawer.locator('.agent-step-marker').nth(1), "backgroundColor", false);
    await assertThemeTone(drawer.locator('.agent-plan-step-list strong').nth(1), "color", true);

    await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });
    await assertThemeTone(drawer, "backgroundColor", true);
    await assertThemeTone(drawer.locator('.agent-plan-drawer-panel').first(), "backgroundColor", true);
    await assertThemeTone(drawer.locator('.agent-step-marker').nth(1), "backgroundColor", true);
    await assertThemeTone(drawer.locator('.agent-plan-step-list strong').nth(1), "color", false);
    await dock.locator('[data-agent-plan-revise]').evaluate((button) => button.click());
    const revision = drawer.locator('.agent-plan-revision');
    assert.equal(await revision.isVisible(), true);
    await assertThemeTone(revision, "backgroundColor", true);
    await assertThemeTone(revision.locator('textarea'), "backgroundColor", true);
    await assertThemeTone(revision.locator('textarea'), "color", false);
    await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });

    await page.evaluate(async () => {
      window.__agentDetail = {
        workspace: {
          id: 'ws_planning_revision', jobId: 'job_planning_revision',
          status: 'planning', planningRequestId: 'planning_revision',
          planningSurface: 'editor',
          planningProgress: {
            phase: 'decomposing_goal', title: '正在整理二次精剪步骤',
            detail: '核对时间线结构与审核样片要求。',
          },
        },
        plans: [],
      };
      await window.ClipTalkAgentWorkspace.resumeForJob({
        id: 'job_planning_revision', revision: 1,
        status: 'awaiting_agent_plan', request: { entryWorkflow: 'agent' },
        agent: { workspaceId: 'ws_planning_revision', planId: '' },
      });
    });
    assert.equal(await dock.getAttribute('data-plan-surface'), 'editor');
    await assertThemeTone(dock, "backgroundColor", false);
    await assertThemeTone(dock.locator('.agent-plan-control dd').first(), "color", true);
    for (const panel of await dock.locator('.agent-plan-control').all()) {
      await assertThemeTone(panel, "backgroundColor", false);
    }
  } finally {
    await browser.close();
  }
});

test("subtitle layout stays behind subtitle review and hides implementation details", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 720 } });

  try {
    await page.setContent(`<style>${css}</style>
      <body data-shell-mode="workspace">
        <aside class="chat-panel">
          <section id="agentPlanDock" class="agent-plan-dock hidden"></section>
          <button id="agentPlanDrawerScrim" class="hidden"></button>
          <aside id="agentPlanDrawer" class="agent-plan-drawer hidden" aria-hidden="true">
            <header><div><small id="agentPlanDrawerKicker"></small><strong id="agentPlanDrawerTitle"></strong></div><button id="agentPlanDrawerClose"></button></header>
            <nav><button data-agent-drawer-tab="plan"></button><button data-agent-drawer-tab="activity"></button></nav>
            <section id="agentPlanDrawerPlan" class="agent-plan-drawer-panel" data-agent-drawer-panel="plan"></section>
            <section id="agentPlanDrawerActivity" class="agent-plan-drawer-panel" data-agent-drawer-panel="activity"></section>
            <footer id="agentPlanDrawerFooter"></footer>
          </aside>
          <section id="chatMessages"></section>
        </aside>
        <script>
          window.ClipTalkApi = { requestJson: async (path) => path.includes('/api/agent/skills') ? { skills: [] } : window.__agentDetail };
          window.ClipTalkCurrentJobId = () => 'job_subtitles';
          window.ClipTalkCurrentJobSnapshot = () => ({ id: 'job_subtitles', editSessions: [] });
          window.ClipTalkRefreshCurrentJob = () => {};
          window.showToast = () => {};
          window.EventSource = class { addEventListener() {} close() {} };
        </script>
        <script>${agent}</script>`);

    await page.evaluate(async () => {
      const plan = {
        id: 'plan_subtitles', workspaceId: 'ws_subtitles', status: 'action_required',
        skillId: 'cliptalk-caption-layout-director', executionMode: 'stepwise_review',
        summary: '先确认字幕内容，再应用顶部排版并生成审核样片。',
        steps: [
          { id: 'cut_preview', tool: 'render_review_preview', title: '生成无字幕剪辑样片', status: 'completed', expectedOutput: '无字幕审核样片' },
          { id: 'subtitle_review', tool: 'prepare_subtitle_review', title: '生成并确认字幕审核稿', status: 'action_required', expectedOutput: '已确认的字幕草稿', result: { sessionId: 'edit_subtitles' } },
          { id: 'subtitle_layout', tool: 'layout_subtitles', title: '应用顶部字幕排版', status: 'pending', expectedOutput: '在已确认字幕稿上应用布局' },
          { id: 'subtitle_preview', tool: 'render_review_preview', title: '生成带字幕最终审核样片', status: 'pending', expectedOutput: '字幕审核样片' },
        ],
      };
      window.__agentDetail = {
        workspace: { id: 'ws_subtitles', jobId: 'job_subtitles', activePlanId: 'plan_subtitles' },
        plans: [plan],
      };
      await window.ClipTalkAgentWorkspace.resumeForJob({
        id: 'job_subtitles', revision: 1,
        agent: { workspaceId: 'ws_subtitles', planId: 'plan_subtitles' },
      });
    });

    const steps = page.locator('#agentPlanDrawerPlan .agent-plan-step-list li');
    assert.deepEqual(await steps.locator('strong').allTextContents(), [
      '生成无字幕剪辑样片', '生成并确认字幕审核稿', '应用顶部字幕排版', '生成带字幕最终审核样片',
    ]);
    assert.equal(await steps.nth(0).locator('b').textContent(), '已完成');
    assert.equal(await steps.nth(1).locator('b').textContent(), '需要你处理');
    assert.equal(await steps.nth(2).locator('b').textContent(), '等待执行');
    assert.equal(await steps.nth(2).locator('p').count(), 0);
    assert.equal(await page.locator('#agentPlanDrawerFooter [data-agent-action-open-timeline]').textContent(), '生成并校对字幕');
    const drawerText = await page.locator('#agentPlanDrawerPlan').textContent();
    assert.doesNotMatch(drawerText, /技术详情|调整字幕位置/);
  } finally {
    await browser.close();
  }
});

test("autonomous subtitle layout recovery explains the missing draft and retries instead of skipping layout", async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 720 } });

  try {
    await page.setContent(`<style>${css}</style>
      <body data-shell-mode="workspace">
        <aside class="chat-panel">
          <section id="agentPlanDock" class="agent-plan-dock hidden"></section>
          <button id="agentPlanDrawerScrim" class="hidden"></button>
          <aside id="agentPlanDrawer" class="agent-plan-drawer hidden" aria-hidden="true">
            <header><div><small id="agentPlanDrawerKicker"></small><strong id="agentPlanDrawerTitle"></strong></div><button id="agentPlanDrawerClose"></button></header>
            <nav><button data-agent-drawer-tab="plan"></button><button data-agent-drawer-tab="activity"></button></nav>
            <section id="agentPlanDrawerPlan" class="agent-plan-drawer-panel" data-agent-drawer-panel="plan"></section>
            <section id="agentPlanDrawerActivity" class="agent-plan-drawer-panel" data-agent-drawer-panel="activity"></section>
            <footer id="agentPlanDrawerFooter"></footer>
          </aside>
          <section id="chatMessages"></section>
        </aside>
        <script>
          window.__agentRequests = [];
          window.__agentDetail = null;
          window.ClipTalkApi = {
            requestJson: async (path) => {
              if (path.includes('/actions/retry')) {
                window.__agentRequests.push(path);
                return new Promise(() => {});
              }
              return window.__agentDetail;
            },
          };
          window.ClipTalkCurrentJobId = () => 'job_layout_recovery';
          window.ClipTalkCurrentJobSnapshot = () => ({ id: 'job_layout_recovery', editSessions: [] });
          window.ClipTalkRefreshCurrentJob = () => {};
          window.showToast = () => {};
          window.EventSource = class { addEventListener() {} close() {} };
        </script>
        <script>${agent}</script>`);

    await page.evaluate(async () => {
      const plan = {
        id: 'plan_layout_recovery', workspaceId: 'ws_layout_recovery', status: 'action_required',
        skillId: 'cliptalk-content-extractor', executionMode: 'autonomous_review',
        summary: '完整保留符合条件的片段并生成顶部字幕审核样片。',
        steps: [
          { id: 'subtitle_review', tool: 'prepare_subtitle_review', title: '自动生成并校对字幕草稿', status: 'completed', expectedOutput: '自动校对字幕草稿' },
          {
            id: 'subtitle_layout', tool: 'layout_subtitles', title: '应用顶部字幕排版', status: 'action_required',
            expectedOutput: '在字幕草稿上应用顶部布局',
            result: { actionRequired: true, action: 'subtitle_review', message: '请先生成并确认当前时间线的字幕草稿，再调整字幕排版。' },
          },
          { id: 'subtitle_preview', tool: 'render_review_preview', title: '生成带字幕最终审核样片', status: 'pending', expectedOutput: '字幕审核样片' },
        ],
      };
      window.__agentDetail = {
        workspace: { id: 'ws_layout_recovery', jobId: 'job_layout_recovery', activePlanId: 'plan_layout_recovery' },
        plans: [plan],
      };
      await window.ClipTalkAgentWorkspace.resumeForJob({
        id: 'job_layout_recovery', revision: 1,
        agent: { workspaceId: 'ws_layout_recovery', planId: 'plan_layout_recovery' },
      });
    });
    await page.waitForFunction(() => window.__agentRequests.length === 1);

    const dockText = await page.locator('#agentPlanDock').textContent();
    assert.match(dockText, /自动恢复中/);
    assert.match(dockText, /Agent 将重新生成字幕草稿并应用顶部排版，无需手动确认/);
    assert.doesNotMatch(dockText, /确认并继续/);
    const recovery = page.locator('#agentPlanDock [data-agent-action-retry]');
    assert.equal(await recovery.isDisabled(), true);
    assert.equal(await recovery.textContent(), '正在恢复字幕并应用排版…');
    assert.deepEqual(await page.evaluate(() => window.__agentRequests), [
      '/api/agent/plans/plan_layout_recovery/actions/retry',
    ]);
    const drawerText = await page.locator('#agentPlanDrawerPlan').textContent();
    assert.match(drawerText, /自动恢复中/);
    assert.match(drawerText, /请先生成并确认当前时间线的字幕草稿，再调整字幕排版/);
  } finally {
    await browser.close();
  }
});
