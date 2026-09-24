import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const html = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
const app = readFileSync(new URL("../../static/app.js", import.meta.url), "utf8");
const agent = readFileSync(new URL("../../static/agent-workspace.js", import.meta.url), "utf8");
const agentCss = readFileSync(new URL("../../static/agent-workspace.css", import.meta.url), "utf8");
const apiClient = readFileSync(new URL("../../static/api-client.js", import.meta.url), "utf8");
const creation = readFileSync(new URL("../../static/task-creation.js", import.meta.url), "utf8");
const agentService = readFileSync(new URL("../../agent-service/server.mjs", import.meta.url), "utf8");

test("current-task conversation enters the plan-gated Agent workspace", () => {
  assert.match(html, /id="agentPlanDock"/);
  assert.match(html, /id="agentPlanDrawer"/);
  assert.match(html, /id="agentPlanDrawerActivity"/);
  assert.match(html, /id="agentSkillMenuButton"/);
  assert.match(html, /id="agentSkillSelect"/);
  assert.match(html, /id="composerSuggestion"/);
  assert.match(app, /function composerSuggestionText/);
  assert.match(app, /syncComposerSuggestion/);
  assert.match(app, /ClipTalkAgentWorkspace\?\.submitGoal/);
  assert.match(agent, /messages\/stream/);
  assert.match(agent, /api\.requestResponse\(/);
  assert.match(agent, /ClipTalkRefreshCurrentJob\?\.\(\)/);
  assert.match(agent, /createPlanningTrace/);
  assert.match(agent, /"cliptalk-interview-editor": "访谈剪辑"/);
  assert.match(agent, /skillOptionLabel\(skill\)/);
  assert.match(agent, /planning\.progress/);
  assert.match(agent, /renderPlanningStatus/);
  assert.match(agent, /计划开始后，规划、执行和确认记录会显示在这里/);
  assert.match(agent, /auditable planning trace/);
  assert.match(agent, /agent-planning-trace/);
  assert.match(apiClient, /async function requestResponse/);
  assert.match(agent, /planHash: plan\.planHash/);
  assert.match(agent, /确认并开始/);
  assert.match(agent, /data-agent-plan-revise/);
  assert.match(agent, /async function submitPlanRevision/);
  assert.match(agent, /await submitGoal\(revision/);
  assert.match(agent, /data-agent-plan-open/);
  assert.match(agentCss, /agent-plan-drawer/);
  assert.match(agentCss, /agent-plan-segments/);
  assert.match(agent, /planningFlowMarkup/);
  assert.match(agent, /目标.*当前阶段.*下一步/s);
  assert.match(agent, /确认前不会分析或渲染/);
  assert.match(agent, /agent-plan-control/);
  assert.match(agentCss, /agent-planning-flow/);
  assert.match(agent, /agent-planning-stage-label/);
  assert.match(agentCss, /\.agent-plan-dock \.agent-planning-flow li/);
  assert.doesNotMatch(agentCss, /\.agent-plan-dock li\s*\{/);
  assert.match(agentCss, /overflow:\s*visible/);
  assert.match(agentCss, /agent-planning-live/);
  assert.match(agent, /`已用 \$\{elapsed\}`/);
  assert.doesNotMatch(agentService, /正在生成可确认计划（已等待/);
  assert.match(agentService, /正在等待规划结果/);
  assert.doesNotMatch(agentService, /正在标记确认点/);
  assert.doesNotMatch(agentService, /规划关注 · 目标边界/);
  assert.doesNotMatch(agentService, /规划关注 · 确认边界/);
  assert.doesNotMatch(agentService, /lastPlanningFocusIndex/);
  assert.doesNotMatch(agentService, /% planningFocuses\.length/);
  assert.match(agentCss, /agent-step-marker/);
  assert.match(agent, /function subscribeActivity/);
  assert.match(agent, /new EventSource/);
  assert.match(agent, /timeline_proposal/);
  assert.match(agent, /data-agent-action-open-timeline/);
  assert.match(agent, /打开精剪时间线/);
  assert.match(agent, /ClipTalkOpenAgentTimeline/);
  assert.match(app, /window\.ClipTalkOpenAgentTimeline/);
  assert.match(app, /inspectorMode: "ai"/);
  assert.match(app, /生成修改清单/);
  assert.match(agent, /确认时间线草案/);
  assert.match(agent, /已确认时间线，继续/);
  assert.match(agent, /review_content_evidence/);
  assert.match(agent, /social_reframe_preview/);
  assert.match(agent, /ClipTalkOpenAgentPreview/);
  assert.match(app, /agentPreviewOutputs/);
  assert.match(app, /window\.ClipTalkOpenAgentPreview/);
  assert.match(agent, /已选好片段，继续/);
  assert.match(agent, /plan\.replan_skipped/);
  assert.match(agent, /未重复执行相同步骤/);
  assert.match(agent, /repeatedPlanningUpdates/);
  assert.match(agent, /正在执行前置步骤/);
  assert.match(agent, /请先在精剪时间线建立并确认字幕草稿/);
  assert.match(agent, /完成样片审核，继续/);
  assert.match(agentCss, /overflow-y: auto/);
});

test("Agent plans restore after reload and show user-facing step progress", () => {
  assert.match(agent, /workspaces\/by-job/);
  assert.match(agent, /resumeForJob/);
  assert.match(agent, /执行 \$\{progress\.settled\}\/\$\{progress\.total\}/);
  assert.match(agent, /跳过 \$\{progress\.skipped\}/);
  assert.match(agent, /repair_and_recheck|修正并重新质检/);
  assert.match(agent, /function toolLabel/);
  assert.match(app, /ClipTalkAgentWorkspace\?\.resumeForJob/);
  assert.match(app, /请确认剪辑计划/);
  assert.match(app, /正在生成剪辑计划/);
  assert.match(app, /clearRecoveredPollError/);
  assert.match(app, /errorSource !== "poll"/);
});

test("new uploads enter an Agent draft before planning or legacy workflows", () => {
  assert.match(creation, /id="briefAgentGoal"/);
  assert.match(creation, /id="briefAgentSkillSelect"/);
  assert.match(creation, /data-start-agent/);
  assert.match(app, /entryWorkflow: "agent"/);
  assert.match(creation, /brief-template-picker/);
  assert.match(app, /createAgentJobFromBrief/);
  assert.match(app, /await window\.ClipTalkAgentWorkspace\?\.submitGoal/);
  assert.match(app, /bootstrapAgentDraftFromUpload/);
  assert.match(creation, /自动选择会根据描述组合能力/);
  assert.match(creation, /data-capability-category="auto"/);
  assert.match(app, /draftCapabilityCategories/);
  assert.match(app, /data-capability-category-switch/);
  assert.match(app, /data-draft-capability-skill/);
  assert.match(app, /需先有审核样片/);
});

test("uploads open a durable Agent draft and keep legacy modes on the same workspace", () => {
  assert.match(html, /id="chatLegacyModeButton"/);
  assert.match(creation, /agent_draft/);
  assert.match(creation, /draft_session_id/);
  assert.match(app, /bootstrapAgentDraftFromUpload/);
  assert.match(app, /agentDraft: true/);
  assert.match(app, /draftSessionId: sessionId/);
  assert.match(app, /\/activate/);
  assert.doesNotMatch(app, /legacy-activate/);
  assert.match(app, /待输入剪辑要求/);
});

test("Skill and trusted Plugin management expose explicit review boundaries", () => {
  assert.match(html, /Skills 与 Plugins/);
  assert.match(agent, /skills\/generate/);
  assert.match(agent, /skills\/install/);
  assert.match(agent, /plugins\/inspect/);
  assert.match(agent, /trusted: true/);
  assert.match(agent, /拥有宿主权限/);
});

test("Agent model settings require a real Tool Calling probe", () => {
  assert.match(html, /id="agentSettingsForm"/);
  assert.match(agent, /settings\/agent\/probe/);
  assert.match(agent, /probe\.toolCalling/);
  assert.match(agent, /复用文本模型/);
});

test("Agent service accepts the review gate emitted by content-composition Skills", () => {
  assert.match(agentService, /Type\.Literal\("review"\)/);
  assert.match(agentService, /Skill 目录/);
  assert.match(agentService, /payload\.skills/);
});
