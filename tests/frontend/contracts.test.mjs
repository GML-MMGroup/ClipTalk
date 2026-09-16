import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const read = (path) => fs.readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

test("production stylesheet chain excludes retired workspace overrides", () => {
  const html = read("static/index.html");

  assert.doesNotMatch(html, /workspace-glass\.css/);
  assert.doesNotMatch(html, /sidebar-redesign\.css/);
});

test("review-sample timing accepts edit-session source ranges", () => {
  const app = read("static/app.js");
  const start = app.indexOf("function compositionTransitionOverlap");
  const end = app.indexOf("function seekCurrentMediaTime", start);
  assert.ok(start >= 0 && end > start, "composition timing helpers must remain available");

  const context = {};
  vm.runInNewContext(app.slice(start, end), context);
  const sample = {
    coverIntro: { duration: 1 },
    segments: [
      { sourceStart: 12, sourceEnd: 15, playbackRate: 1 },
      { sourceStart: 80, sourceEnd: 84, playbackRate: 2 },
    ],
  };
  const schedule = context.compositionSchedule(sample);

  assert.deepEqual(
    schedule.map((entry) => ({
      sourceStart: entry.sourceStart,
      sourceEnd: entry.sourceEnd,
      outputStart: entry.outputStart,
      outputEnd: entry.outputEnd,
    })),
    [
      { sourceStart: 12, sourceEnd: 15, outputStart: 1, outputEnd: 4 },
      { sourceStart: 80, sourceEnd: 84, outputStart: 4, outputEnd: 6 },
    ],
  );
  assert.ok(Math.abs(context.compositionSourceTimeAtOutputTime(sample, 5) - 82) < .001);
});

test("workflow copy uses one four-mode terminology contract", () => {
  const context = { window: {} };
  vm.runInNewContext(read("static/ui-copy.js"), context);
  const copy = context.window.ClipTalkCopy;

  assert.deepEqual([...copy.WORKFLOWS.highlight.navigation[2]], ["事件审核", "确认事件与候选镜头"]);
  assert.equal(copy.WORKFLOWS.content_search.output, "内容视频");
  assert.equal(copy.WORKFLOWS.person_edit.timeline, "人物出镜时间线");
  assert.equal(copy.WORKFLOWS.speaker_edit.candidate, "发言片段");
  assert.equal(copy.ACTIONS.preview, "生成剪辑预览");
  assert.equal(copy.ACTIONS.exportVersion, "生成成片");
});

test("workspace state prefers canonical presentation and execution facts", () => {
  const context = { window: {} };
  vm.runInNewContext(read("static/workspace-state.js"), context);
  const { derive, derivePresentation, STATES, PRESENTATION_STATES } = context.window.ClipTalkWorkspaceState;

  assert.equal(derive({
    job: {
      status: "running",
      execution: { schemaVersion: 1, status: "waiting_user", active: false },
      presentation: { schemaVersion: 2, key: "content_review", group: "action_required" },
    },
  }), STATES.REVIEWING);
  assert.equal(derive({
    job: {
      status: "running",
      execution: { schemaVersion: 1, status: "completed", outcome: "output_ready" },
      presentation: { schemaVersion: 2, key: "exported", group: "completed" },
    },
  }), STATES.COMPLETED);

  assert.equal(derive({
    job: {
      status: "awaiting_agent_plan",
      agentDraft: true,
      instructionSubmitted: true,
      presentation: { schemaVersion: 2, key: "plan_planning", group: "agent_planning" },
    },
  }), STATES.ANALYSING);
  assert.equal(derive({
    job: {
      status: "awaiting_agent_instruction",
      agentDraft: true,
      instructionSubmitted: false,
      presentation: { schemaVersion: 2, key: "waiting_instruction", group: "draft" },
    },
  }), STATES.AWAITING_INSTRUCTION);

  assert.equal(derivePresentation({
    presentation: { schemaVersion: 2, key: "no_result" },
  }).key, PRESENTATION_STATES.NO_RESULT);
  assert.equal(derivePresentation({
    presentation: { schemaVersion: 2, key: "failed" },
  }).key, PRESENTATION_STATES.FAILED);
  const preview = derivePresentation({
    presentation: { schemaVersion: 2, key: "preview_review", group: "action_required" },
  });
  assert.equal(preview.key, PRESENTATION_STATES.PREVIEW_REVIEW);
  assert.equal(preview.group, "action_required");
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

  context.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(
    context.window.ClipTalkApi.request("/api/offline"),
    (error) => {
      assert.equal(error.status, 0);
      assert.equal(error.code, "network_error");
      assert.equal(error.message, "网络连接失败 · 请重试");
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

test("quick workflow launch owns its instruction field and light theme surface", () => {
  const app = read("static/app.js");
  const css = `${read("static/styles.css")}\n${read("static/workbench.css")}`;

  assert.match(app, /data-workflow-launch-instruction/);
  assert.match(app, /检索内容/);
  assert.match(app, /剪辑要求/);
  assert.match(app, /人物要求/);
  assert.match(app, /发言要求/);
  assert.match(app, /createSameSourceWorkflow\(pendingWorkflowSwitch, syncInstruction\(\)\)/);
  assert.match(css, /html\[data-theme="light"\][\s\S]*\.quick-workflow-launch/);
  assert.match(css, /\.quick-workflow-launch \.workflow-launch-instruction textarea/);
});

test("subtitle review conflicts tell users to complete review instead of refreshing", () => {
  const apiClient = read("static/api-client.js");
  const app = read("static/app.js");

  assert.match(apiClient, /complete_subtitle_review:\s*"完成字幕校对"/);
  assert.match(app, /function secondaryEditorSubtitleBurnReadiness/);
  assert.match(app, /async function ensureSecondaryEditorSubtitleReadyForBurn/);
  assert.match(app, /ensureSecondaryEditorSubtitleReadyForBurn\(\)/);
  assert.match(app, /source_subtitle_ack_required/);
});

test("agent execution events refresh the current job and player without manual reload", () => {
  const workspace = read("static/agent-workspace.js");

  assert.match(workspace, /function activityEventShouldSync/);
  assert.match(workspace, /"preview\.ready"/);
  assert.match(workspace, /"plan\.completed"/);
  assert.match(workspace, /"step\.completed"/);
  assert.match(workspace, /function scheduleAgentWorkspaceSync/);
  assert.match(workspace, /await refreshPlan\(\)/);
  assert.match(workspace, /ClipTalkRefreshCurrentJob\?\.\(\)/);
  assert.match(workspace, /if \(activityEventShouldSync\(name\)\) scheduleAgentWorkspaceSync\(\)/);
  assert.match(workspace, /clearTimeout\(activityRefreshTimer\)/);
});

test("compact workspace rules cover small laptop viewports and long lists", () => {
  const css = read("static/interaction-surfaces.css");

  assert.match(css, /@media \(max-width: 1366px\)/);
  assert.match(css, /grid-template-columns:\s*220px minmax\(430px, 1fr\) 260px/);
  assert.match(css, /\.current-person-range-more/);
  assert.match(css, /\.current-voice-turn-more/);
});

test("output delivery exposes cover, package, and optional intro controls", () => {
  const html = read("static/index.html");
  const app = read("static/app.js");

  assert.match(html, /id="coverDownloadButton"/);
  assert.match(html, /id="packageDownloadButton"/);
  assert.match(html, /id="coverIntroButton"/);
  assert.match(app, /createCoverIntroOutput/);
  assert.match(app, /output\.coverUrl/);
  assert.match(app, /output\.packageUrl/);
});

test("completed cover plans show the generated image instead of only step progress", () => {
  const html = read("static/index.html");
  const app = read("static/app.js");
  const workspace = read("static/agent-workspace.js");
  const css = read("static/styles.css");

  assert.match(workspace, /function coverResultMarkup/);
  assert.match(workspace, /查看生成的封面/);
  assert.match(workspace, /下载封面 JPG/);
  assert.match(workspace, /打开封面时间轴/);
  assert.match(workspace, /ClipTalkConfirmCoverTimelineSelection/);
  assert.match(html, /id="timelineCoverTrack"/);
  assert.match(app, /function renderTimelineCoverTrack/);
  assert.match(app, /data-cover-timeline-duration/);
  assert.match(app, /cover-timeline\/activate/);
  assert.match(workspace, /选择一个封面后保存为最终封面；生成成片或导出时作为片头合入/);
  assert.match(workspace, /样片已生成，确认无误后即可生成成片/);
  assert.match(workspace, /return "待确认"/);
  assert.match(workspace, /"播放样片"/);
  assert.doesNotMatch(workspace, /审核样片待确认生成成片/);
  assert.match(app, /setRailTitle\("版本与交付"\)/);
  assert.match(css, /\.timeline-cover-track/);
  assert.match(css, /\.timeline-cover-variants/);
});

test("opening an agent review sample preserves its complete artifact state", () => {
  const html = read("static/index.html");
  const app = read("static/app.js");
  const workspace = read("static/agent-workspace.js");

  assert.match(workspace, /const preview = planReviewPreviews\(activePlan\)\.find/);
  assert.match(workspace, /\.\.\.preview,[\s\S]*outputKind: String\(preview\?\.outputKind/);
  assert.match(app, /timelineEvents = \[\], timelineHierarchyVersion = null/);
  assert.match(app, /subtitleBurned: Boolean\(subtitleBurned \|\| previous\.subtitleBurned\)/);
  assert.match(app, /segments: Array\.isArray\(segments\) && segments\.length/);
  assert.match(app, /socialReframe: Boolean\(socialReframe \|\| previous\.socialReframe \|\| aspect \|\| reframe\?\.aspect/);
  assert.match(html, /agent-workspace\.js\?v=[0-9]{8}-[\w-]+/);
  assert.match(html, /app\.js\?v=[0-9]{8}-[\w-]+/);
});

test("subtitle review opens the dedicated subtitle flow without entering the fine-cut editor", () => {
  const app = read("static/app.js");
  const start = app.indexOf("window.ClipTalkOpenAgentSubtitleReview = async");
  const end = app.indexOf("window.ClipTalkOpenAgentPreview = async", start);
  assert.ok(start >= 0 && end > start);
  const implementation = app.slice(start, end);

  assert.match(implementation, /reviewSubtitlesBeforeRender/);
  assert.match(implementation, /operation:\s*\{[\s\S]*type:\s*"set_subtitle"/);
  assert.doesNotMatch(implementation, /ClipTalkOpenAgentTimeline/);
  assert.doesNotMatch(implementation, /reviewSecondaryEditorSubtitles/);
});

test("interrupted autonomous subtitle steps resume without asking the user to choose", () => {
  const workspace = read("static/agent-workspace.js");
  const html = read("static/index.html");

  assert.match(workspace, /resumeAutonomousSubtitleRecovery\(plan, progress\)/);
  assert.match(workspace, /prepare_subtitle_review[\s\S]*autonomous_review[\s\S]*actions\/retry/);
  assert.match(workspace, /正在自动生成字幕…/);
  assert.match(html, /agent-workspace\.js\?v=[0-9]{8}-[\w-]+/);
});

test("assistant messages cannot overflow the conversation column", () => {
  const css = read("static/workbench.css");
  const html = read("static/index.html");

  assert.match(css, /Conversation width firewall/);
  assert.match(css, /Assistant rail intrinsic-width firewall/);
  assert.match(css, /aside#assistantPanel#assistantPanel\.chat-panel\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) !important;[\s\S]*?contain:\s*inline-size !important;/);
  assert.match(css, /#chatMessages > article\.chat-message\s*\{[\s\S]*?min-width:\s*0 !important;[\s\S]*?max-width:\s*100% !important;[\s\S]*?overflow:\s*hidden !important;/);
  assert.match(css, /> :where\(\.bubble, \.recommendation-wrap, \.brief-wrap\)[\s\S]*?box-sizing:\s*border-box !important;[\s\S]*?min-width:\s*0 !important;/);
  assert.match(css, /\.bubble :where\(p, li, span, strong, small\)[\s\S]*?white-space:\s*pre-wrap !important;[\s\S]*?overflow-wrap:\s*anywhere !important;/);
  assert.match(html, /workbench\.css\?v=[0-9]{8}-[\w-]+/);
});

test("timeline media assets remain visible in source and output review modes", () => {
  const app = read("static/app.js");
  const css = read("static/styles.css");
  const html = read("static/index.html");

  assert.match(app, /let waveformLoadingJobId = null/);
  assert.match(app, /waveformLoadingJobId === job\.id/);
  assert.match(app, /if \(waveformLoadingJobId === job\.id\) waveformLoadingJobId = null/);
  assert.doesNotMatch(
    css,
    /data-coordinate-space="output"[^{}]*(?:timeline-thumbnails|timeline-scene-cuts)[^{]*\{[^}]*display:\s*none\s*!important/s,
  );
  assert.doesNotMatch(
    css,
    /output-comparison-mode:has\([^)]*data-coordinate-space="output"[^)]*\)[^{]*(?:waveformState|timelineThumbnailState)[^{]*\{[^}]*display:\s*none\s*!important/s,
  );
  assert.match(css, /timeline-viewport\[data-coordinate-space="output"\] \.timeline-thumbnails[\s\S]*display:\s*flex\s*!important/);
  assert.match(html, /styles\.css\?v=[0-9]{8}-[\w-]+/);
  assert.match(html, /app\.js\?v=[0-9]{8}-[\w-]+/);
});

test("waiting instruction review rail does not duplicate the chat composer action", () => {
  const app = read("static/app.js");
  const timeline = read("static/timeline-presentation.js");
  const html = read("static/index.html");

  assert.doesNotMatch(app, /data-focus-composer>描述剪辑要求/);
  assert.match(app, /请在左侧对话框输入剪辑要求/);
  assert.doesNotMatch(timeline, /ct-review-guide-action/);
  assert.doesNotMatch(timeline, /data-ct-focus-composer/);
  assert.match(html, /timeline-presentation\.js\?v=[0-9]{8}-[\w-]+/);
});

test("new-task upload affordance always renders a visible plus inside its ring", () => {
  const css = read("static/workbench.css");
  const html = read("static/index.html");

  assert.match(html, /class="drop-zone-add"/);
  assert.match(css, /Upload affordance: draw the plus as geometry/);
  assert.match(css, /drop-zone-add::before[\s\S]*width:\s*15px !important;[\s\S]*height:\s*2px !important/);
  assert.match(css, /drop-zone-add::after[\s\S]*width:\s*2px !important;[\s\S]*height:\s*15px !important/);
  assert.match(html, /workbench\.css\?v=[0-9]{8}-[\w-]+/);
});

test("workspace composer keeps Agent and send controls in a second input row", () => {
  const css = read("static/workbench.css");
  const html = read("static/index.html");

  assert.match(css, /Canonical composer layout: text first, controls second/);
  assert.match(css, /grid-template-rows:\s*minmax\(38px, auto\) 30px !important/);
  assert.match(css, /#agentSkillMenuButton#agentSkillMenuButton\s*\{[\s\S]*?min-height:\s*28px !important/);
  assert.match(css, /\.chat-input-shell\.chat-input-shell #sendButton#sendButton\s*\{\s*position:\s*static !important/);
  assert.doesNotMatch(html, /id="composerAttachButton"/);
  assert.doesNotMatch(css, /#composerAttachButton/);
});

test("analysis progress uses one readable status hierarchy in narrow chat panels", () => {
  const css = read("static/workbench.css");

  assert.match(css, /Analysis progress v2/);
  assert.match(css, /#inlineAnalysisProgress\.inline-analysis-progress\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) !important/);
  assert.match(css, /#inlineAnalysisProgress \.inline-progress-orb\s*\{\s*display:\s*none !important/);
  assert.match(css, /\.inline-workflow-head b::before\s*\{[\s\S]*?animation:\s*ct-analysis-status-beacon/);
});

test("v4 output preview suppresses legacy result panels and evidence strip", () => {
  const app = read("static/app.js");
  const timeline = read("static/timeline-presentation.js");
  const workbench = read("static/workspace-controller.js");
  const css = read("static/workbench.css");
  const html = read("static/index.html");

  assert.match(app, /document\.body\.classList\.contains\("ct-workbench-v4"\)[\s\S]*clearOutputEvidenceStrip\(\)[\s\S]*return/);
  assert.match(app, /function cleanDisplayText\(value, fallback = ""\)/);
  assert.match(app, /suffixCleaned = text\.replace/);
  assert.match(app, /title: cleanDisplayText\(item\.title, fallback\)/);
  assert.match(app, /displayTitle: cleanDisplayText\(item\.displayTitle, cleanDisplayText\(item\.title, fallback\)\)/);
  assert.match(app, /const displayTitle = cleanDisplayText\(output\.displayTitle\)/);
  assert.match(app, /viewerMediaKind === "source" && sourceDuration > 0/);
  assert.match(app, /viewerMediaKind === "output" && currentOutput && timelineOutputDurationValue\(currentOutput\) > 0/);
  assert.match(app, /Completed content-search tasks should still show their matched source/);
  assert.match(app, /function timelineOutputAxisActive\(\)[\s\S]*return timelineHasOutputComparison\(\)/);
  assert.match(app, /const reviewingOutput = Boolean\(viewerMediaKind === "output" && currentOutput\)/);
  // Output/source axis behavior is exercised by workspace-smoke; avoid
  // constraining the implementation to one exact conditional expression.
  assert.match(app, /const reviewSample = reviewingOutput && currentOutputIsReviewSample\(currentOutput\)/);
  assert.match(app, /const outputTitle = reviewSample \? "审核样片时间轴" : "成片版本时间轴"/);
  assert.match(app, /审核样片 \$\{index \+ 1\}/);
  assert.match(app, /reviewSample \? "审核样片预览"/);
  assert.doesNotMatch(timeline, /new MutationObserver/);
  assert.match(workbench, /function clearLegacyVisualState\(workflowKind = ""\)/);
  assert.match(app, /\["clipSection", "railOutput", "reviewWorkbench", "railBody", "ctReviewEmpty"\]/);
  assert.match(app, /classList\.toggle\("ct-output-preview-mode", outputActive\)/);
  assert.match(app, /syncLegacyOutputPanelsForV4\(outputActive\)/);
  assert.match(css, /#chatStageHost > :where\(#clipSection, #railOutput\)/);
  assert.match(css, /#chatStageHost#chatStageHost > #railOutput#railOutput/);
  assert.match(css, /#reviewRail#reviewRail > #reviewPanelSwitch#reviewPanelSwitch/);
  assert.match(css, /#timelinePanel#timelinePanel\.timeline-panel:not\(\.hidden\) > #timelineViewport#timelineViewport\.timeline-viewport/);
  assert.match(css, /#reviewWorkbench#reviewWorkbench/);
  assert.match(css, /Agent sample preview geometry guard/);
  assert.match(css, /ct-agent-preview-mode\[data-shell-mode="workspace"\][\s\S]*grid-template-rows:\s*54px minmax\(320px, 1fr\) minmax\(250px, 33vh\)/);
  assert.match(css, /ct-agent-preview-mode\[data-shell-mode="workspace"\][\s\S]*#reviewStage#reviewStage\.review-stage[\s\S]*display:\s*block !important/);
  assert.match(css, /ct-agent-preview-mode\[data-shell-mode="workspace"\][\s\S]*#viewerShell#viewerShell\.viewer-shell[\s\S]*grid-row:\s*auto !important/);
  assert.match(css, /Agent sample preview semantic polish/);
  assert.match(css, /Generated-output preview/);
  assert.match(css, /ct-output-preview-mode\[data-shell-mode="workspace"\][\s\S]*#reviewPanelSwitch[\s\S]*display:\s*none !important/);
  assert.match(css, /ct-output-preview-mode\[data-shell-mode="workspace"\][\s\S]*#timelinePanel#timelinePanel\.timeline-panel:not\(\.hidden\)[\s\S]*grid-column:\s*1 \/ -1 !important/);
  assert.match(css, /\.ct-v4-candidates-card\.is-empty/);
  assert.match(css, /\.ct-v4-delivery-checks/);
  assert.match(read("static/workspace-controller.js"), /id="ctV4DeliveryChecks"/);
  assert.match(read("static/workspace-controller.js"), /ct-v4-adopted-preview/);
  assert.match(read("static/workspace-controller.js"), /竖屏/);
  assert.match(read("static/workspace-controller.js"), /root\?\.querySelector\?\.\(selector\) \|\| null/);
  assert.match(read("static/workspace-controller.js"), /sourceTitle = cleanDisplayText\(window\.ClipTalkCurrentJobSnapshot\?\.\(\)\?\.filename\)/);
  assert.match(html, /workbench\.css\?v=[0-9]{8}-[\w-]+/);
  assert.match(html, /app\.js\?v=[0-9]{8}-[\w-]+/);
  assert.match(html, /timeline-presentation\.js\?v=[0-9]{8}-[\w-]+/);
  assert.doesNotMatch(html, /cliptalk-(?:reference-v3|redesign-v1)\.js/);
  assert.match(html, /workspace-controller\.js\?v=[0-9]{8}-[\w-]+/);
});

test("adopted segments render time-coded source thumbnails and can expand", () => {
  const app = read("static/app.js");
  const workbench = read("static/workspace-controller.js");
  const css = read("static/workbench.css");

  assert.match(app, /window\.ClipTalkTimelineAssetsSnapshot = \(\) =>/);
  assert.match(app, /window\.ClipTalkSeekSourceTime = \(second\) => seekSourceTime\(second\)/);
  assert.match(workbench, /function applyAdoptedSegmentThumbnail/);
  assert.match(workbench, /timelineAssetsSnapshot\?\.spriteUrl/);
  assert.match(workbench, /adoptedSegments\.slice\(0, 3\)/);
  assert.match(workbench, /host\.dataset\.expanded/);
  assert.match(workbench, /ct-v4-adopted-thumb is-loading/);
  assert.match(workbench, /点击缩略图可跳回源片位置/);
  assert.match(workbench, /window\.ClipTalkSeekSourceTime\(start\)/);
  assert.match(css, /ct-v4-adopted-preview[\s\S]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/);
  assert.match(css, /ct-v4-adopted-preview\.is-expanded[\s\S]*repeat\(2, minmax\(0, 1fr\)\)/);
});
