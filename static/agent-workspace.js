(function initAgentWorkspace(global) {
  "use strict";

  let viewGeneration = 0;
  const pendingRequests = new Set();
  let retryCount = 0;
  const owner = () => ({ generation: viewGeneration, jobId: currentJobId() });
  const ownsView = (value) => value.generation === viewGeneration && value.jobId === currentJobId();
  const staleError = () => Object.assign(new Error("任务已切换"), { name: "StaleWorkspaceError" });
  async function viewRequest(method, path, options = {}) {
    if (!/^\/api\/agent\/(workspaces|plans)(?:\/|$)/.test(path)) {
      return global.ClipTalkApi[method](path, options);
    }
    const context = owner();
    const controller = new AbortController();
    pendingRequests.add(controller);
    try {
      const result = await global.ClipTalkApi[method](path, { ...options, signal: options.signal || controller.signal });
      if (!ownsView(context)) throw staleError();
      return result;
    } catch (error) {
      if (!ownsView(context)) throw staleError();
      throw error;
    } finally {
      pendingRequests.delete(controller);
    }
  }
  const api = {
    ...global.ClipTalkApi,
    requestJson: (path, options) => viewRequest("requestJson", path, options),
    requestResponse: (path, options) => viewRequest("requestResponse", path, options),
  };
  const workspaceByJob = new Map();
  const workspaceRestoreByJob = new Map();
  let activePlan = null;
  let activeWorkspace = null;
  let retrySubmission = null;
  let pollTimer = null;
  let registryTab = "skills";
  let agentProviders = [];
  let discoveredAgentModels = [];
  let planDrawerTab = "plan";
  let planDrawerReturnFocus = null;
  let planDrawerReleaseFocus = null;
  let planDrawerCloseTimer = null;
  let activityRefreshTimer = null;
  let activitySource = null;
  let activityWorkspaceId = "";
  let activityEvents = [];
  const automaticSubtitleResumeIds = new Set();

  const $ = (selector) => document.querySelector(selector);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);

  const SKILL_DISPLAY_NAMES = Object.freeze({
    "cliptalk-audio-polish-mixer": "人声与音频优化",
    "cliptalk-broll-overlay-editor": "补充画面剪辑",
    "cliptalk-caption-layout-director": "字幕排版",
    "cliptalk-content-extractor": "内容提取",
    "cliptalk-cover-director": "封面设计",
    "cliptalk-cover-intro-composer": "封面片头制作",
    "cliptalk-delivery-qc": "成片质量检查",
    "cliptalk-dynamic-reframe-director": "智能画幅重构",
    "cliptalk-edit-diagnostics": "剪辑问题诊断",
    "cliptalk-graphics-packager": "图文包装",
    "cliptalk-highlight-director": "智能高光",
    "cliptalk-interview-editor": "访谈剪辑",
    "cliptalk-local-draft-exporter": "本地草稿导出",
    "cliptalk-local-motion-renderer": "动态图文制作",
    "cliptalk-multi-topic-assembler": "多主题组合",
    "cliptalk-person-editor": "人物聚焦",
    "cliptalk-platform-delivery-exporter": "平台成片导出",
    "cliptalk-revision-editor": "版本编辑",
    "cliptalk-shortform-hook-director": "短视频钩子剪辑",
    "cliptalk-smart-reframe": "智能改画幅",
    "cliptalk-social-reframe-exporter": "社媒画幅适配",
    "cliptalk-source-provenance-guard": "素材来源校验",
    "cliptalk-speaker-editor": "发言剪辑",
    "cliptalk-subtitle-editor": "字幕编辑",
  });

  function skillDisplayName(skill) {
    const id = String(skill?.id || "").trim();
    const explicit = String(skill?.displayName || "").trim();
    return explicit || SKILL_DISPLAY_NAMES[id] || String(skill?.name || id || "未命名 Skill").trim();
  }

  function skillOptionLabel(skill) {
    const id = String(skill?.id || "").trim();
    const name = skillDisplayName(skill);
    return id && name !== id ? `${name} · ${id}` : name;
  }

  function currentJobId() {
    return String(global.ClipTalkCurrentJobId?.() || "");
  }

  function isAgentInstructionDraft(job) {
    if (!job || job.instructionSubmitted) return false;
    if (job.agentDraft) return true;
    if (String(job.status || "") === "awaiting_agent_instruction") return true;
    return String(job.stage || "") === "agent_workspace_ready"
      && String(job.request?.entryWorkflow || "") === "agent";
  }

  function appendMessage(role, text, kind = "") {
    const root = $("#chatMessages");
    if (!root) return;
    const article = document.createElement("article");
    article.className = `chat-message ${role} agent-message`;
    article.dataset.kind = kind;
    const source = String(text || "");
    const tags = role === "user" ? [
      /全片/.test(source) ? "全片" : /当前片段|选中片段/.test(source) ? "当前片段" : "",
      source.match(/(?:9:16|4:5|1:1|16:9)/)?.[0] || "",
      /找出|找到|查找|搜索|检索/.test(source) ? "内容检索" : "",
    ].filter(Boolean) : [];
    article.innerHTML = `<span class="avatar">${role === "user" ? "你" : "AI"}</span><div class="bubble"><small>${role === "user" ? "剪辑目标" : "智能剪辑 Agent"}</small><p>${escapeHtml(text)}</p>${tags.length ? `<div class="agent-goal-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>` : ""}</div>`;
    const pinned = root.scrollHeight - root.scrollTop - root.clientHeight < 56;
    root.append(article);
    if (pinned) root.scrollTop = root.scrollHeight;
    return article;
  }

  function conversationMessages(job) {
    if (!activeWorkspace || ![activeWorkspace.jobId, activeWorkspace.sourceJobId].includes(job?.id)) return job?.messages || [];
    const messages = [...(job.messages || [])];
    for (const item of activeWorkspace.messages || []) {
      if (messages.some((m) => m.id && item.id ? m.id === item.id : (
        m.role === item.role && m.text === item.text && m.createdAt && m.createdAt === item.createdAt
      ))) continue;
      messages.push({ ...item, inherited: false });
    }
    return messages.map((item) => {
      const plan = (activeWorkspace.planReferences || []).find((p) => p.id === item.planId);
      return plan ? { ...item, planGoal: plan.goal, planLabel: plan.id === activeWorkspace.activePlanId ? "当前方案" : "历史方案" } : item;
    }).sort((a, b) => String(a.createdAt || a.timestamp || "").localeCompare(String(b.createdAt || b.timestamp || "")));
  }

  async function refreshConversation() {
    if (!activeWorkspace?.id) return;
    const detail = await api.requestJson(`/api/agent/workspaces/${encodeURIComponent(activeWorkspace.id)}`);
    if (!detail.workspace?.id) return;
    activeWorkspace = detail.workspace;
    workspaceByJob.set(String(activeWorkspace.jobId), activeWorkspace);
    restorePlanMessages(detail);
    global.ClipTalkRenderAssistantHistory?.();
    renderPendingChanges();
  }

  function restorePlanMessages(detail) {
    activeWorkspace.planReferences = (detail.plans || []).map((p) => ({ id: p.id, goal: p.goal }));
    const messages = [...(activeWorkspace.messages || [])];
    for (const plan of detail.plans || []) {
      if (!messages.some((m) => m.role === "user" && (m.planId ? m.planId === plan.id : m.text === plan.goal))) {
        messages.push({ id: `historical:${plan.id}`, role: "user", text: plan.goal, planId: plan.id, createdAt: plan.createdAt });
      }
    }
    activeWorkspace.messages = messages;
  }

  function renderPendingChanges() {
    let panel = $("#assistantPendingChanges");
    if (!panel) {
      panel = document.createElement("section");
      panel.id = "assistantPendingChanges";
      panel.className = "assistant-pending-changes";
      $("#chatForm")?.prepend(panel);
    }
    const pending = activeWorkspace?.pendingChanges || [];
    panel.hidden = !pending.length;
    if (!pending.length) return;
    const waiting = pending.every((x) => x.status === "after_completion");
    panel.innerHTML = `<strong>${waiting ? "完成后整理修改方案" : "暂存修改 · 尚未应用"}</strong><p>${pending.map((x) => escapeHtml(x.text)).join("；")}</p><div><button type="button" data-pending-choice="stop">停止后重新规划</button><button type="button" data-pending-choice="${waiting ? "prepare" : "after"}">${waiting ? "检查并整理修改" : "完成后再处理"}</button><button type="button" data-pending-choice="discard">撤回修改</button></div><p role="status" data-pending-error></p>`;
    panel.querySelectorAll("[data-pending-choice]").forEach((button) => button.addEventListener("click", async () => {
      panel.querySelectorAll("button").forEach((node) => { node.disabled = true; });
      try {
        const result = await api.requestJson(`/api/agent/workspaces/${encodeURIComponent(activeWorkspace.id)}/pending-changes`, { method: "POST", body: { choice: button.dataset.pendingChoice } });
        if (result.plan) renderPlan(result.plan);
        await refreshConversation();
      } catch (error) {
        if (error.name === "StaleWorkspaceError") return;
        panel.querySelector("[data-pending-error]").textContent = error.message;
        panel.querySelectorAll("button").forEach((node) => { node.disabled = false; });
      }
    }));
  }

  // This is an auditable planning trace, not the model's private chain of
  // thought.  It exposes concrete workflow milestones that a user can verify.
  function createPlanningTrace(goal) {
    const trace = document.createElement("ol");
    trace.className = "agent-planning-trace";
    const steps = [
      { id: "goal", title: "已记录剪辑目标", detail: String(goal || "").slice(0, 90), state: "completed" },
      { id: "skill", title: "正在选择适用 Skill", detail: "根据目标匹配剪辑方法", state: "active" },
      { id: "context", title: "核对素材范围与可用工具", detail: "此阶段不会分析视频或渲染", state: "pending" },
      { id: "structure", title: "按主题拆解剪辑步骤", detail: "安排回答顺序、删重与片段范围", state: "pending" },
      { id: "validation", title: "校验确认点与步骤依赖", detail: "生成可审核的执行计划", state: "pending" },
    ];
    const phaseIndex = {
      skill_selected: 2,
      context_loading: 2,
      context_ready: 3,
      decomposing_goal: 3,
      validating_plan: 4,
      plan_ready: 5,
    };
    let activeIndex = 1;

    function render() {
      trace.replaceChildren(...steps.map((step) => {
        const item = document.createElement("li");
        item.dataset.state = step.state;
        const marker = document.createElement("span");
        marker.setAttribute("aria-hidden", "true");
        const copy = document.createElement("div");
        const title = document.createElement("strong");
        const detail = document.createElement("small");
        title.className = "agent-planning-stage-label";
        title.textContent = step.title;
        detail.textContent = step.detail;
        copy.append(title, detail);
        item.append(marker, copy);
        return item;
      }));
    }

    function advance(phase, detail = "", title = "") {
      const nextIndex = phaseIndex[phase];
      if (!Number.isInteger(nextIndex)) return;
      activeIndex = Math.max(activeIndex, nextIndex);
      steps.forEach((step, index) => {
        step.state = index < activeIndex ? "completed" : index === activeIndex ? "active" : "pending";
      });
      const current = steps[Math.min(activeIndex, steps.length - 1)];
      if (current) {
        if (title) current.title = String(title).slice(0, 120);
        if (detail) current.detail = String(detail).slice(0, 180);
      }
      render();
    }

    // Planning milestones live in the activity drawer; keep the conversation
    // focused on the goal and the decision the user needs to make.
    render();
    return { advance };
  }

  async function ensureWorkspace() {
    const jobId = currentJobId();
    if (!jobId) throw new Error("请先打开一个素材任务");
    if (workspaceByJob.has(jobId)) {
      activeWorkspace = workspaceByJob.get(jobId);
      return activeWorkspace;
    }
    const result = await api.requestJson("/api/agent/workspaces", {
      method: "POST", body: { jobId },
    });
    workspaceByJob.set(jobId, result.workspace);
    activeWorkspace = result.workspace;
    return activeWorkspace;
  }

  function statusLabel(status) {
    return ({
      pending: "等待执行", awaiting_confirmation: "待确认方案",
      approved: "准备执行", running: "执行中", waiting_operation: "后台处理中",
      action_required: "需要你处理", preview_ready: "计划已完成",
      no_result: "未找到可用内容", completed: "已完成", failed: "执行失败",
      skipped: "已跳过", cancelled: "已停止",
      planning: "正在规划",
    })[String(status || "")] || "处理中";
  }

  function noResultStep(plan) {
    return (plan?.steps || []).find((step) => (
      step?.outcome === "no_result"
      || (step?.result && typeof step.result === "object" && String(step.result.terminalStatus || "") === "no_result")
    )) || null;
  }

  function noResultMessageFromStep(step) {
    const result = step?.result && typeof step.result === "object" ? step.result : {};
    const artifact = result.artifact && typeof result.artifact === "object" ? result.artifact : {};
    return String(step?.outcomeMessage || artifact.message || result.message || "");
  }

  function stepDisplayStatus(step) {
    const status = String(step?.status || "");
    if (step?.outcome === "no_result" || String(step?.result?.terminalStatus || "") === "no_result") {
      return "未形成可用结果";
    }
    if (status === "skipped" && (step?.skipReason || step?.blockedByMessage)) return "未执行";
    return statusLabel(status);
  }

  function stepStatusDetail(step) {
    const noResultMessage = noResultMessageFromStep(step);
    if (noResultMessage) return noResultMessage;
    const skipReason = String(step?.skipReason || "");
    const blockedMessage = String(step?.blockedByMessage || "");
    if (skipReason && blockedMessage && !skipReason.includes(blockedMessage)) {
      return `${skipReason} 上游原因：${blockedMessage}`;
    }
    return skipReason || blockedMessage || "";
  }

  function toolLabel(tool) {
    return ({
      inspect_workspace: "读取素材状态",
      analyze_highlights: "分析高光片段",
      search_content: "查找目标内容",
      discover_people: "发现画面人物",
      select_people: "确认目标人物",
      discover_speakers: "区分说话人",
      select_speakers: "确认目标说话人",
      review_content_evidence: "确认内容候选",
      propose_timeline_edit: "生成时间线修改建议",
      confirm_timeline_edit: "确认时间线草案",
      prepare_subtitle_review: "生成字幕审核稿",
      render_review_preview: "准备审核样片",
      render_social_preview: "生成社媒画幅预览",
      layout_subtitles: "调整字幕位置",
      propose_cover_candidates: "提取封面候选",
      render_cover_variants: "生成封面预览",
      review_cover_variants: "选择当前任务封面",
      confirm_cover: "保存当前任务封面",
      compose_cover_intro: "合成封面片头",
      render_motion_graphics: "生成本地图文动效",
      compose_motion_intro: "合成动态图文片头",
      export_editing_draft: "导出本地剪辑草稿",
      run_delivery_qc: "检查成片交付质量",
      cancel_operation: "停止当前操作",
    })[String(tool || "")] || "执行剪辑工具";
  }

  function presentationSteps(plan) {
    const rawSteps = Array.isArray(plan?.steps) ? plan.steps : [];
    const steps = [];
    for (let index = 0; index < rawSteps.length; index += 1) {
      const step = rawSteps[index] || {};
      const next = rawSteps[index + 1] || {};
      // Selecting a cover and saving it are one user-facing step. In composite
      // plans this is not the final delivery action; rendering may continue.
      if (String(step.tool || "") === "review_cover_variants" && String(next.tool || "") === "confirm_cover") {
        const reviewFinished = ["completed", "skipped"].includes(String(step.status || ""));
        const hasLaterDelivery = rawSteps.slice(index + 2).some((candidate) => [
          "render_review_preview",
          "render_social_preview",
          "compose_cover_intro",
          "run_delivery_qc",
        ].includes(String(candidate?.tool || "")));
        steps.push({
          ...step,
          tool: reviewFinished ? "confirm_cover" : "review_cover_variants",
          title: hasLaterDelivery ? "保存当前任务封面" : "最后确认并保存封面",
          expectedOutput: hasLaterDelivery
            ? "保存当前任务封面后，继续合成片头或目标画幅审核样片。"
            : "选择一个封面后保存为最终封面；生成成片或导出时作为片头合入。",
          status: reviewFinished ? next.status : step.status,
          error: reviewFinished ? next.error : step.error,
          result: reviewFinished ? next.result : step.result,
        });
        index += 1;
        continue;
      }
      steps.push(step);
    }
    return steps;
  }

  function planProgress(plan) {
    const steps = presentationSteps(plan);
    const successful = steps.filter((step) => String(step?.status || "") === "completed").length;
    const skipped = steps.filter((step) => String(step?.status || "") === "skipped").length;
    const settled = successful + skipped;
    const current = String(plan?.status || "") === "failed"
      ? steps.find((step) => String(step?.status || "") === "failed") || null
      : steps.find((step) => ["running", "waiting_operation", "action_required"].includes(String(step?.status || "")))
        || steps.find((step) => String(step?.status || "") === "pending") || null;
    return { completed: settled, successful, skipped, settled, total: steps.length, current };
  }

  function isAutomaticSubtitleRecovery(plan, progress = planProgress(plan)) {
    return String(plan?.status || "") === "action_required"
      && String(plan?.executionMode || "") === "autonomous_review"
      && ["prepare_subtitle_review", "layout_subtitles"].includes(String(progress?.current?.tool || ""));
  }

  function planHandoff(plan) {
    return (plan?.steps || []).map((step) => step?.result?.job).find((job) => job?.id) || null;
  }

  function planActionMessage(plan, progress) {
    const current = progress.current || {};
    const result = current.result && typeof current.result === "object" ? current.result : {};
    if (String(current.tool || "") === "review_cover_variants") {
      return "选择并保存当前任务封面；如果任务要求片头或目标画幅，后续会继续生成最终审核样片。";
    }
    if (String(plan?.status || "") === "no_result") {
      const terminal = noResultStep(plan);
      const message = noResultMessageFromStep(terminal) || result.message;
      return String(message || "未形成足以自动编排的可靠结果。");
    }
    if (String(plan?.status || "") === "failed") {
      const failure = String(current.error || result.message || `${current.title || toolLabel(current.tool)}未完成`);
      if (failure.includes("自动编排缺少必要类别的候选") && !failure.includes("已停止自动重试")) {
        return `${failure}。已停止自动重试；已有候选已保留。可手动重新检索一次，仍缺失时请调整目标或补充素材。`;
      }
      return failure;
    }
    return String(result.message || current.expectedOutput || plan?.summary || "等待下一步执行");
  }

  function executionModeLabel(plan) {
    return String(plan?.executionMode || "stepwise_review") === "autonomous_review"
      ? "自动剪辑并预览" : "分步审核";
  }

  function planReviewPreviews(plan) {
    const previews = [];
    (plan?.steps || []).forEach((step) => {
      const artifact = step?.result?.artifact;
      if (!artifact || typeof artifact !== "object") return;
      if (artifact.kind === "review_preview_batch") {
        previews.push(...(artifact.previews || []));
      } else if (artifact.kind === "review_preview" && Array.isArray(artifact.outputs)) {
        previews.push(...artifact.outputs.map((output) => ({ ...output, kind: "review_preview" })));
      } else if (artifact.kind === "review_preview") {
        previews.push(artifact);
      } else if (artifact.kind === "social_reframe_preview" && artifact.output) {
        previews.push({ ...artifact.output, kind: "social_reframe_preview" });
      } else if (artifact.kind === "cover_intro_review_preview" && artifact.output) {
        previews.push({ ...artifact.output, kind: "cover_intro_review_preview" });
      }
    });
    const jobPreviews = global.ClipTalkCurrentJobSnapshot?.()?.agentPreviewOutputs;
    if (Array.isArray(jobPreviews)) {
      previews.push(...jobPreviews
        .filter((item) => (item.planId === plan?.id || previews.some((p) => p.filename && p.filename === item.filename)) && ([
          "social_reframe_preview",
          "cover_intro_review_preview",
          "review_preview",
        ].includes(String(item?.outputKind || "")) || item?.socialReframe))
        .map((item) => ({ ...item, kind: String(item?.outputKind || "") || (item?.socialReframe ? "social_reframe_preview" : "review_preview") })));
    }
    const seen = new Set();
    return previews.filter((item) => {
      if (!item || typeof item !== "object") return false;
      const key = `${item.kind || item.outputKind || "preview"}:${item.filename || item.sessionId || item.previewUrl || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).sort((left, right) => previewPriority(right) - previewPriority(left));
  }

  function planQcArtifact(plan) {
    const artifact = (plan?.steps || [])
      .map((step) => step?.result?.artifact)
      .find((artifact) => artifact?.kind === "delivery_qc_report") || null;
    if (artifact) return artifact;
    const checks = planReviewPreviews(plan).map((item) => item.contentVerification).filter(Boolean);
    return checks.length ? { passed: checks.every((item) => item.passed === true), reports: checks } : null;
  }

  function planQcIssueSummary(plan) {
    const artifact = planQcArtifact(plan);
    if (!artifact || artifact.passed !== false) return "";
    const issues = (artifact.reports || []).flatMap((report) => report?.issues || []);
    const messages = issues.map((issue) => String(issue?.message || "").trim().replace(/[。；;]+$/, "")).filter(Boolean);
    return messages.length ? messages.slice(0, 2).join("；") : "严格质检未通过，请查看质检详情。";
  }

  function planQcState(plan) {
    const artifact = planQcArtifact(plan);
    if (!artifact) return { status: "not_run", issues: [], firstRange: null };
    const issues = (artifact.reports || []).flatMap((report) => report?.issues || [])
      .filter((issue) => issue && typeof issue === "object");
    const firstRange = issues.flatMap((issue) => issue?.evidence?.ranges || [])
      .find((range) => Number.isFinite(Number(range?.start)) && Number.isFinite(Number(range?.end))) || null;
    if (artifact.passed === true) return { status: "passed", issues, firstRange };
    if (issues.some((issue) => String(issue?.severity || "") === "error") || !issues.length) {
      return { status: "failed", issues, firstRange };
    }
    return { status: "warning", issues, firstRange };
  }

  function formatQcRange(range) {
    if (!range) return "";
    const clock = (value) => {
      const seconds = Math.max(0, Math.floor(Number(value) || 0));
      const minutes = Math.floor(seconds / 60);
      return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    };
    return `${clock(range.start)}–${clock(range.end)}`;
  }

  function planDisplayStatus(plan) {
    if (isAutomaticSubtitleRecovery(plan)) return "自动恢复中";
    if (["preview_ready", "completed"].includes(String(plan?.status || ""))) {
      if (coverCompliance(plan).issues.length) return "封面需要处理";
      const quality = planQcState(plan).status;
      if (quality === "failed") return "审核样片待修正";
      if (quality === "warning") return "审核样片有质量提醒";
      if (planReviewPreviews(plan).length) return "待确认";
    }
    return statusLabel(plan?.status);
  }

  function previewPriority(item) {
    if (previewKind(item) === "cover_intro_review_preview") {
      return item?.reframe?.aspect ? 5 : 4;
    }
    if (previewKind(item) !== "social_reframe_preview") return 0;
    return String(item?.reframe?.fit || "") === "blur" ? 2 : 1;
  }

  function previewKind(item) {
    return String(item?.kind || item?.outputKind || "review_preview");
  }

  function previewButtonAttributes(item) {
    return [
      "data-agent-review-open",
      `data-preview-kind="${escapeHtml(previewKind(item))}"`,
      `data-session-id="${escapeHtml(item?.sessionId || "")}"`,
      `data-preview-filename="${escapeHtml(item?.filename || "")}"`,
      `data-preview-url="${escapeHtml(item?.previewUrl || item?.videoUrl || "")}"`,
      `data-preview-title="${escapeHtml(item?.title || "审核样片")}"`,
      `data-preview-width="${escapeHtml(item?.width || "")}"`,
      `data-preview-height="${escapeHtml(item?.height || "")}"`,
      `data-preview-duration="${escapeHtml(item?.duration || "")}"`,
      `data-preview-aspect="${escapeHtml(item?.reframe?.aspect || "")}"`,
    ].join(" ");
  }

  function previewMeta(item) {
    const duration = Number(item?.duration || 0).toFixed(1);
    if (previewKind(item) === "cover_intro_review_preview") {
      const aspect = String(item?.reframe?.aspect || "");
      const dimensions = Number(item?.width) > 0 && Number(item?.height) > 0
        ? `${Number(item.width)}×${Number(item.height)}` : (aspect || "审核样片");
      const fit = String(item?.reframe?.fit || "");
      const fitLabel = fit === "blur" ? "虚化背景" : fit === "pad" ? "留边" : fit === "crop" ? "中心裁切" : "";
      return `${duration} 秒 · 封面片头 · ${dimensions}${aspect ? ` · ${aspect}` : ""}${fitLabel ? ` · ${fitLabel}` : ""}`;
    }
    if (previewKind(item) === "social_reframe_preview") {
      const dimensions = Number(item?.width) > 0 && Number(item?.height) > 0
        ? `${Number(item.width)}×${Number(item.height)}` : "竖屏";
      const aspect = String(item?.reframe?.aspect || "9:16");
      const fit = String(item?.reframe?.fit || "");
      const fitLabel = fit === "blur" ? "虚化背景" : fit === "pad" ? "留边" : fit === "crop" ? "中心裁切" : "";
      return `${duration} 秒 · ${dimensions} · ${aspect}${fitLabel ? ` · ${fitLabel}` : ""}`;
    }
    return `${duration} 秒 · 审核样片`;
  }

  function actionButtonLabel(step) {
    if (step?.result?.action === "content_evidence_review") return "已核验所选片段，继续";
    const tool = String(step?.tool || "");
    if (tool === "select_people" || tool === "select_speakers") return "已完成选择，继续";
    if (tool === "review_content_evidence") return "已选好片段，继续";
    if (tool === "propose_timeline_edit") return "草案已核对，继续";
    if (tool === "confirm_timeline_edit") return "已确认时间线，继续";
    if (tool === "prepare_subtitle_review") return "已完成字幕校对，继续";
    if (tool === "render_review_preview") return "完成样片审核，继续";
    if (tool === "review_cover_variants") return "选定封面，继续";
    return "确认并继续";
  }

  function skillLabel(skillId) {
    return ({
      "cliptalk-highlight-director": "智能高光计划", "cliptalk-content-extractor": "内容检索计划",
      "cliptalk-interview-editor": "访谈剪辑计划", "cliptalk-person-editor": "人物聚焦计划",
      "cliptalk-speaker-editor": "发言剪辑计划", "cliptalk-revision-editor": "版本编辑计划",
      "cliptalk-shortform-hook-director": "短视频剪辑计划", "cliptalk-delivery-qc": "成片质检计划",
      "cliptalk-social-reframe-exporter": "社媒画幅计划",
      "cliptalk-cover-director": "封面导演计划",
    })[String(skillId || "")] || "智能剪辑计划";
  }

  function coverReviewMarkup(plan) {
    const current = planProgress(plan).current;
    if (String(current?.tool || "") !== "review_cover_variants") return "";
    const draft = global.ClipTalkCurrentJobSnapshot?.()?.coverDraft;
    const variants = Array.isArray(draft?.variants) ? draft.variants : [];
    if (!variants.length) {
      return `<section class="agent-cover-review agent-cover-review-empty"><small>封面审核</small><p>封面预览正在同步，请稍后刷新任务。</p></section>`;
    }
    return `<section class="agent-cover-review agent-cover-review-handoff"><small>封面选择</small><p>${variants.length} 张封面草稿已放入主时间轴。保存当前任务封面后，如任务要求片头或目标画幅，Agent 会继续生成最终审核样片。</p><button type="button" class="primary" data-agent-cover-timeline-open>选择并保存封面</button></section>`;
  }

  function completedCover(plan) {
    if (!["preview_ready", "completed"].includes(String(plan?.status || ""))) return null;
    if (!presentationSteps(plan).some((step) => String(step?.tool || "") === "confirm_cover")) return null;
    const job = global.ClipTalkCurrentJobSnapshot?.();
    const currentId = String(job?.currentCoverVersionId || "");
    return (job?.coverVersions || []).find((item) => String(item?.id || "") === currentId) || null;
  }

  function coverRequirement(plan) {
    const brief = plan?.brief && typeof plan.brief === "object" ? plan.brief : {};
    const goal = String(plan?.goal || brief.goal || "");
    const genericCoverSubject = (value) => {
      const normalized = String(value || "").replace(/\s+/g, "");
      if (!normalized) return true;
      return /^(?:最)?(?:具有|有)?(?:冲击性|视觉冲击|张力|感染力|吸引力|代表性|高级感|电影感|质感|氛围感|美感|精彩|好看|漂亮|清晰|醒目|震撼|燃|酷|帅|关键|重要|合适|适合|好|最佳|最好|最棒|亮眼|出彩)(?:的)?$/.test(normalized);
    };
    const externalMatch = goal.match(
      /(?:找到|寻找|查找|搜索|网上找|使用|采用|上传|提供)\s*(?:一张|一幅|一张合适的|合适的)?\s*(.{1,60}?)(?:的)?(?:照片|图片|肖像|头像)\s*(?:来)?(?:作为|用作|做成|当作)\s*(?:视频)?封面/
    );
    const sourceMatch = goal.match(
      /(?:用|使用|采用|选用|选取|选择|截取)\s*(?:第?\s*\d+(?:\.\d+)?\s*(?:秒钟|秒|s)\s*(?:左右|附近|前后)?\s*(?:出现|看到|有)?(?:的)?\s*)?(.{1,60}?)(?:的)?(?:照片|图片|肖像|头像|画面|镜头|帧)?\s*(?:来)?(?:作为|用作|做成|当作)\s*(?:视频)?封面/i
    );
    const sourceTimeMatch = goal.match(
      /(?:用|使用|采用|选用|选取|选择|截取)\s*(?:第)?\s*(\d+(?:\.\d+)?)\s*(?:秒钟|秒|s)[^。；;\n]{0,80}?(?:作为|用作|做成|当作)\s*(?:视频)?封面/i
    );
    const titleMatch = goal.match(
      /(?:封面|缩略图|海报帧)[^。；;\n]{0,30}?(?:(?:上\s*)?写(?:好)?上?|标题|文案|文字|加上|添加|放上|配上)\s*(?:是|为|用|写|内容为|：|:)?\s*[“"'‘]?([^。；;”"'’\n]{1,120})/
    );
    const rawSubject = String(brief.coverSubject || externalMatch?.[1] || sourceMatch?.[1] || "")
      .replace(/^(?:出现|看到|看见|有|画面中|视频中)(?:的)?/, "")
      .trim();
    return {
      requested: Boolean(brief.coverRequested || /封面|缩略图|海报帧/.test(goal)),
      sourceKind: String(brief.coverSourceKind || (externalMatch ? "external_image" : "source_frame")),
      sourceStatus: String(brief.coverSourceStatus || (externalMatch ? "requires_external_asset" : "available")),
      subject: genericCoverSubject(rawSubject) ? "" : rawSubject,
      sourceTime: brief.coverSourceTime !== null && brief.coverSourceTime !== undefined && Number.isFinite(Number(brief.coverSourceTime))
        ? Number(brief.coverSourceTime) : sourceTimeMatch ? Number(sourceTimeMatch[1]) : null,
      title: String(brief.coverTitle || titleMatch?.[1] || "").trim(),
      introRequested: Boolean(brief.coverIntroRequested),
    };
  }

  function coverVariantReviewError(plan, variant) {
    if (!variant) return "尚未选择封面候选";
    const requirement = coverRequirement(plan);
    const job = global.ClipTalkCurrentJobSnapshot?.() || {};
    const requestedTime = job?.coverDraft?.requestedSourceTime !== null
      && job?.coverDraft?.requestedSourceTime !== undefined
      ? Number(job.coverDraft.requestedSourceTime) : requirement.sourceTime;
    const sourceTime = Number(variant?.sourceTime);
    if (Number.isFinite(requestedTime) && (!Number.isFinite(sourceTime) || Math.abs(requestedTime - sourceTime) > .75)) {
      return Number.isFinite(sourceTime)
        ? `候选来自 ${sourceTime.toFixed(1)} 秒，不是要求的 ${requestedTime.toFixed(1)} 秒附近画面`
        : `候选缺少来源时间，无法确认是否来自 ${requestedTime.toFixed(1)} 秒附近`;
    }
    const verification = variant?.subjectVerification && typeof variant.subjectVerification === "object"
      ? variant.subjectVerification : {};
    if (requirement.subject && verification.personDetected === false) {
      return `候选未检测到人物，不能作为“${requirement.subject}”的封面`;
    }
    return "";
  }

  function coverDraftReviewErrors(plan) {
    const progress = planProgress(plan);
    if (String(plan?.status || "") !== "action_required" || String(progress.current?.tool || "") !== "review_cover_variants") return [];
    const job = global.ClipTalkCurrentJobSnapshot?.() || {};
    const variants = Array.isArray(job?.coverDraft?.variants) ? job.coverDraft.variants : [];
    if (!variants.length) return [];
    const errors = variants.map((variant) => coverVariantReviewError(plan, variant)).filter(Boolean);
    return errors.length === variants.length ? [errors[0], "当前没有符合要求的封面候选"] : [];
  }

  function coverCompliance(plan) {
    const requirement = coverRequirement(plan);
    const cover = completedCover(plan);
    const issues = [];
    if (!requirement.requested) return { requirement, cover, issues };
    const shouldHaveCover = ["preview_ready", "completed"].includes(String(plan?.status || ""))
      || requirement.sourceStatus === "requires_external_asset";
    if (!cover?.previewUrl && shouldHaveCover) issues.push("尚未生成并保存当前任务封面");
    if (cover && requirement.sourceKind === "external_image" && String(cover?.provenance?.kind || "") !== "external_image") {
      issues.push(`当前封面不是${requirement.subject ? `“${requirement.subject}”的` : "要求的"}外部图片`);
    }
    if (cover && requirement.title && String(cover.titleText || "").trim() !== requirement.title) {
      issues.push("封面文字与要求不一致");
    }
    if (
      cover && requirement.sourceKind === "source_frame" && requirement.subject
      && String(cover?.subjectVerification?.status || "") !== "user_confirmed"
    ) {
      const personDetected = cover?.subjectVerification?.personDetected;
      issues.push(personDetected === false
        ? `当前封面未检测到人物，不能作为“${requirement.subject}”的封面`
        : `尚未确认画面人物是否为“${requirement.subject}”`);
    }
    if (cover && requirement.introRequested && !planReviewPreviews(plan).some((item) => previewKind(item) === "cover_intro_review_preview")) {
      issues.push("当前审核样片尚未合入封面片头");
    }
    return { requirement, cover, issues };
  }

  function coverBlockingMessage(plan) {
    const { requirement } = coverCompliance(plan);
    if (requirement.sourceStatus !== "requires_external_asset") return "";
    return `当前版本不能联网获取${requirement.subject ? `“${requirement.subject}”的` : "指定"}图片，也不能导入独立封面素材。请改用本次视频画面制作封面。`;
  }

  function coverStatusMarkup(plan) {
    const { requirement, cover, issues } = coverCompliance(plan);
    if (!requirement.requested) return "";
    const previousRequirement = global.ClipTalkActiveCoverRequirement;
    global.ClipTalkActiveCoverRequirement = { ...requirement, planId: String(plan?.id || "") };
    if (JSON.stringify(previousRequirement || {}) !== JSON.stringify(global.ClipTalkActiveCoverRequirement)) {
      global.dispatchEvent?.(new CustomEvent("cliptalk:cover-requirement", {
        detail: global.ClipTalkActiveCoverRequirement,
      }));
    }
    const job = global.ClipTalkCurrentJobSnapshot?.() || {};
    const hasDrafts = Array.isArray(job?.coverDraft?.variants) && job.coverDraft.variants.length > 0;
    const displayIssues = [...issues, ...coverDraftReviewErrors(plan)];
    const detail = displayIssues.length
      ? [...new Set(displayIssues)].join("；")
      : `${requirement.sourceKind === "external_image" ? "外部图片" : "本次视频画面"}${requirement.title ? ` · 文案：${requirement.title}` : " · 无封面文字"}`;
    const preview = cover?.previewUrl
      ? `<button type="button" data-agent-cover-open data-cover-url="${escapeHtml(cover.previewUrl)}"><img src="${escapeHtml(cover.previewUrl)}" alt="当前任务封面预览"></button>`
      : `<span class="agent-cover-status-placeholder" aria-hidden="true">封面</span>`;
    const label = displayIssues.length
      ? "封面候选不符合要求"
      : cover?.previewUrl
        ? requirement.introRequested && !planReviewPreviews(plan).some((item) => previewKind(item) === "cover_intro_review_preview")
          ? "封面已保存 · 待更新样片" : "封面已保存"
        : hasDrafts ? "等待核对封面" : "等待生成封面";
    const sourceMeta = [
      requirement.sourceKind === "external_image" ? "外部图片" : "本次视频画面",
      Number.isFinite(requirement.sourceTime) ? `${requirement.sourceTime} 秒` : "",
      requirement.subject ? `人物：${requirement.subject}` : "",
    ].filter(Boolean).join(" · ");
    return `<section class="agent-cover-status" data-quality="${displayIssues.length ? "missing" : "ready"}">${preview}<div><small>${escapeHtml(label)}</small><strong>${escapeHtml(detail)}</strong>${sourceMeta ? `<span>${escapeHtml(sourceMeta)}</span>` : ""}${requirement.title ? `<span>要求文字：${escapeHtml(requirement.title)}</span>` : ""}</div></section>`;
  }

  function coverResultMarkup(plan) {
    const cover = completedCover(plan);
    if (!cover?.previewUrl) return "";
    const score = Number(cover?.score?.total || 0);
    const direction = ({
      source_clean: "干净源帧", source_editorial: "编辑构图", source_cinematic: "电影质感",
    })[String(cover?.direction || "")] || "已确认封面";
    return `<section class="agent-cover-result"><small>当前封面</small><button type="button" data-agent-cover-open data-cover-url="${escapeHtml(cover.previewUrl)}"><img src="${escapeHtml(cover.previewUrl)}" alt="当前任务封面"><span><strong>${escapeHtml(direction)}</strong><em>${escapeHtml(`${cover.aspectRatio || "16:9"}${score ? ` · ${score} 分` : ""}`)}</em></span></button><p>候选切换、片头时长与最终导出已移到主时间轴。封面确认和视频合成是两个独立动作。</p><a href="${escapeHtml(cover.previewUrl)}" download="video-cover.jpg">下载封面 JPG</a><button type="button" class="primary" data-agent-cover-timeline-open>打开封面时间轴</button></section>`;
  }

  function planUsesPrecisionEditor(plan) {
    if (String(plan?.skillId || "") === "cliptalk-revision-editor") return true;
    const precisionTools = new Set([
      "propose_timeline_edit",
      "confirm_timeline_edit",
      "render_review_preview",
    ]);
    return (plan?.steps || []).some((step) => precisionTools.has(String(step?.tool || "")));
  }

  function planCurrentTitle(plan, progress) {
    if (plan.status === "awaiting_confirmation") return `确认这份 ${progress.total} 步计划`;
    if (["preview_ready", "completed"].includes(plan.status)) {
      const quality = planQcState(plan).status;
      if (quality === "failed") return "执行完成 · 质检未通过";
      if (quality === "warning") return "执行完成 · 建议人工复核";
      return planReviewPreviews(plan).length ? "执行完成 · 样片已就绪" : "执行完成";
    }
    if (plan.status === "failed") return `${progress.current?.title || "执行步骤"}未完成`;
    if (plan.status === "no_result") {
      const terminal = noResultStep(plan);
      return String(terminal?.tool || "") === "propose_timeline_edit"
        ? "时间线未形成" : "未形成可用结果";
    }
    if (plan.status === "cancelled") return "计划已停止";
    return progress.current?.title || toolLabel(progress.current?.tool) || "准备下一步";
  }

  function compactPlanText(value, fallback = "按当前剪辑目标执行") {
    return String(value || fallback).replace(/\s+/g, " ").trim().slice(0, 360);
  }

  function currentStageText(plan, progress) {
    const status = String(plan?.status || "");
    if (status === "awaiting_confirmation") return "等待确认计划";
    if (isAutomaticSubtitleRecovery(plan, progress)) {
      return `正在恢复：${progress.current?.title || toolLabel(progress.current?.tool)}`;
    }
    if (status === "action_required") return `需要确认：${progress.current?.title || toolLabel(progress.current?.tool)}`;
    if (status === "failed") return `未完成：${progress.current?.title || toolLabel(progress.current?.tool)}`;
    if (status === "no_result") {
      const terminal = noResultStep(plan);
      const message = noResultMessageFromStep(terminal);
      if (message) return `${String(terminal?.tool || "") === "propose_timeline_edit" ? "时间线未形成" : "未形成可用结果"}：${message}`;
      return "未形成可用结果";
    }
    if (status === "cancelled") return "计划已停止";
    if (["preview_ready", "completed"].includes(status)) {
      const coverIssues = coverCompliance(plan).issues;
      if (coverIssues.length) return "当前封面与要求不一致";
      const quality = planQcState(plan).status;
      if (quality === "failed") return `质检未通过：${planQcIssueSummary(plan)}`;
      if (quality === "warning") return `质量提醒：${planQcIssueSummary(plan)}`;
      return planReviewPreviews(plan).length ? "样片已生成，确认无误后即可生成成片" : "结果已生成";
    }
    if (["running", "approved"].includes(status)) return `正在执行：${progress.current?.title || toolLabel(progress.current?.tool)}`;
    return planCurrentTitle(plan, progress);
  }

  function nextStepText(plan, progress) {
    const status = String(plan?.status || "");
    if (status === "awaiting_confirmation") return "确认后开始检索、编排或生成样片";
    if (isAutomaticSubtitleRecovery(plan, progress)) {
      return String(progress.current?.tool || "") === "layout_subtitles"
        ? "Agent 将重新生成字幕草稿并应用顶部排版，无需手动确认。"
        : "Agent 正在重新生成并校对字幕草稿，无需手动确认。";
    }
    if (status === "action_required") {
      const result = progress.current?.result && typeof progress.current.result === "object"
        ? progress.current.result : {};
      return String(result.message || progress.current?.expectedOutput || "完成当前选择后继续执行");
    }
    if (status === "failed") return "查看失败原因或重新执行失败链路";
    if (status === "no_result") {
      const message = noResultMessageFromStep(noResultStep(plan));
      if (/不足以达到|目标/.test(message)) return "移除或放宽目标时长后重新执行；也可以改为使用全部已命中片段。";
      return "调整目标或重新检索内容";
    }
    if (status === "cancelled") return "输入新目标可重新规划";
    if (["preview_ready", "completed"].includes(status)) {
      if (coverCompliance(plan).issues.length) return "修改封面要求后重新规划；当前样片和已有结果会保留";
      const quality = planQcState(plan).status;
      if (quality === "failed") return "修正质检问题，并重新生成样片检查";
      if (quality === "warning") return "查看提示位置，确认效果后生成成片";
      if (planReviewPreviews(plan).length) return "预览样片并确认效果";
      if (completedCover(plan)?.previewUrl) return "查看当前任务封面";
      return "在当前任务中查看结果";
    }
    if (progress.current?.expectedOutput) return progress.current.expectedOutput;
    return "等待当前步骤完成";
  }

  function planControlMarkup({ goal, stage, next, meta = "" }) {
    return `<section class="agent-plan-control" aria-label="Agent 剪辑计划">
      <dl>
        <div><dt>目标</dt><dd>${escapeHtml(compactPlanText(goal))}</dd></div>
        <div><dt>当前阶段</dt><dd>${escapeHtml(compactPlanText(stage, "正在处理"))}</dd></div>
        <div><dt>下一步</dt><dd>${escapeHtml(compactPlanText(next, "等待下一步"))}</dd></div>
      </dl>
      ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
    </section>`;
  }

  function planUnderstandingItems(plan) {
    const understanding = plan?.understanding && typeof plan.understanding === "object" ? plan.understanding : {};
    return Array.isArray(understanding.items)
      ? understanding.items.filter((item) => item && typeof item === "object" && item.label && item.value).slice(0, 8)
      : [];
  }

  function planUnderstandingMarkup(plan, { compact = false } = {}) {
    const items = planUnderstandingItems(plan);
    if (!items.length) return "";
    const visible = compact ? items.slice(0, 6) : items;
    const reviewHint = String(plan?.status || "") === "awaiting_confirmation" ? "执行前请核对" : "本次理解记录";
    return `<section class="agent-understanding-card${compact ? " compact" : ""}" aria-label="Agent 对目标的理解">
      <header><strong>${escapeHtml(plan?.understanding?.title || "Agent 理解")}</strong><span>${escapeHtml(reviewHint)}</span></header>
      <dl>${visible.map((item) => `<div data-kind="${escapeHtml(item.kind || "")}"><dt>${escapeHtml(item.label)}</dt><dd>${escapeHtml(item.value)}</dd></div>`).join("")}</dl>
      ${compact && items.length > visible.length ? `<small>还有 ${items.length - visible.length} 项可在执行详情中查看</small>` : ""}
      ${compact && String(plan?.status || "") === "awaiting_confirmation" ? `<button type="button" data-plan-revise-goal>补充或修改要求</button>` : ""}
    </section>`;
  }

  function planStatusTone(status) {
    if (["action_required", "no_result"].includes(status)) return "attention";
    if (status === "failed") return "danger";
    if (["preview_ready", "completed"].includes(status)) return "complete";
    if (["running", "approved"].includes(status)) return "running";
    return "ready";
  }

  function progressSegments(plan) {
    const progress = planProgress(plan);
    return `<div class="agent-plan-segments" role="progressbar" aria-label="Agent 执行进度" aria-valuemin="0" aria-valuemax="${progress.total}" aria-valuenow="${progress.settled}" aria-valuetext="已执行 ${progress.settled}/${progress.total}${progress.skipped ? `，跳过 ${progress.skipped}` : ""}">${presentationSteps(plan).map((step) => {
      const detail = stepStatusDetail(step);
      const title = `${step.title || toolLabel(step.tool)} · ${stepDisplayStatus(step)}${detail ? ` · ${detail}` : ""}`;
      return `<i data-state="${escapeHtml(step.status || "pending")}" title="${escapeHtml(title)}"></i>`;
    }).join("")}</div>`;
  }

  function planProgressLabel(progress) {
    return `执行 ${progress.settled}/${progress.total}${progress.skipped ? ` · 跳过 ${progress.skipped}` : ""}`;
  }

  function qcSummaryMarkup(plan) {
    const quality = planQcState(plan);
    if (!["failed", "warning"].includes(quality.status)) return "";
    const issues = quality.issues.length ? quality.issues.slice(0, 4) : [{ message: planQcIssueSummary(plan) }];
    const title = quality.status === "failed" ? "质检未通过" : "质量提醒";
    return `<section class="agent-qc-summary" data-quality="${quality.status}" role="status"><strong>${title}</strong><ul>${issues.map((issue) => {
      const evidenceRange = (issue?.evidence?.ranges || [])[0];
      const range = formatQcRange(evidenceRange);
      const preview = planReviewPreviews(plan)[0];
      const start = Number(evidenceRange?.start);
      const location = preview && evidenceRange && Number.isFinite(start)
        ? `<button type="button" ${previewButtonAttributes(preview)} data-qc-start="${Math.max(0, start)}">检查 ${escapeHtml(range)}</button>`
        : range ? `<time>${escapeHtml(range)}</time>` : "";
      return `<li><span>${escapeHtml(issue?.message || "发现需要复核的质量问题")}</span>${location}</li>`;
    }).join("")}</ul></section>`;
  }

  function planningElapsed(workspace) {
    const started = Date.parse(String(workspace?.planningStartedAt || ""));
    if (!Number.isFinite(started)) return "刚刚开始";
    const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
    const minutes = Math.floor(seconds / 60);
    const remainder = String(seconds % 60).padStart(2, "0");
    return minutes ? `${minutes}:${remainder}` : `${seconds} 秒`;
  }

  function planningFlowMarkup(phase, expanded = false, title = "", detail = "") {
    const phases = [
      ["skill_selected", "选择执行能力"],
      ["context_loading", "读取素材状态"],
      ["context_ready", "核对可用证据"],
      ["decomposing_goal", "拆解剪辑任务"],
      ["validating_plan", "整理执行依赖"],
      ["plan_ready", "计划已就绪"],
    ];
    const phaseId = String(phase || "skill_selected");
    const activeIndex = Math.max(0, phases.findIndex(([id]) => id === phaseId));
    const label = phases[activeIndex]?.[1] || String(title || "正在生成计划");
    const phaseCount = `${activeIndex + 1}/${phases.length}`;
    return `<section class="agent-planning-live-track${expanded ? " expanded" : ""}" aria-label="当前规划阶段" data-active-index="${activeIndex}">
      <header><span>当前阶段</span><strong>${escapeHtml(label)}</strong><b>阶段 ${phaseCount}</b></header>
      <div class="agent-planning-live-bar" role="progressbar" aria-label="正在生成计划" aria-valuetext="${escapeHtml(label)}"><i></i></div>
      <p>${escapeHtml(detail || title || "正在整理可确认的执行步骤")}</p>
    </section>`;
  }

  function planIsHistorical(plan) {
    if (!["completed", "preview_ready", "cancelled", "no_result"].includes(plan?.status)) return false;
    const job = global.ClipTalkCurrentJobSnapshot?.();
    const key = job?.presentation?.key;
    return Boolean(job && (["content_review", "exported", "export_running"].includes(key)
      || (job.agent?.planId && job.agent.planId !== plan.id)));
  }

  function planActionMarkup(plan, progress, shortLabel = false) {
    const detail = `<button type="button" class="agent-plan-text-action" data-agent-plan-open>${shortLabel ? "查看计划" : "执行详情"}</button>`;
    if (planIsHistorical(plan)) return shortLabel ? "" : detail;
    if (plan.status === "cancelled") return `${detail}<button type="button" class="primary" data-agent-replan>修改要求重新规划</button>`;
    if (plan.status === "failed" && progress.current?.result?.retryable !== false && !progress.current?.result?.operationId) {
      return `${detail}<button type="button" data-agent-replan>修改要求</button><button type="button" class="primary" data-agent-plan-retry-failed>重试失败步骤</button>`;
    }
    if (plan.status === "awaiting_confirmation") {
      if (coverBlockingMessage(plan)) return `${detail}<button type="button" class="primary" data-agent-plan-revise>修改封面要求</button>`;
      return `${detail}<button type="button" class="agent-plan-text-action" data-agent-plan-revise>修改规划</button><button type="button" class="primary" data-agent-plan-confirm>确认并开始</button>`;
    }
    if (plan.status === "action_required") {
      const currentTool = String(progress.current?.tool || "");
      if (progress.current?.result?.action === "content_evidence_review") {
        const job = global.ClipTalkCurrentJobSnapshot?.() || {};
        const ids = job.contentSearch?.reviewDraft?.selectedMatchIds || [];
        const candidates = job.contentSearch?.candidates || [];
        const ready = ids.length && ids.every((id) => candidates.some((c) => c.id === id && ["verified", "human_confirmed"].includes(c.boundaryVerification?.status)));
        return `${detail}<button type="button" class="primary" data-agent-evidence-open>核验所选片段</button><button type="button" data-agent-action-resolve ${ready ? "" : "disabled"}>已核验，继续</button><small>${ready ? "" : "请先检查并保存片段范围"}</small><button type="button" data-agent-action-reject>停止</button>`;
      }
      if (progress.current?.result?.retryable === false && progress.current?.result?.operationId) {
        return `${detail}<button type="button" class="agent-plan-text-action" data-agent-action-reject>停止计划</button><button type="button" class="primary" data-agent-action-retry>核实操作状态</button>`;
      }
      if (currentTool === "prepare_subtitle_review" && String(plan.executionMode || "") === "autonomous_review") {
        return `${detail}<button type="button" class="agent-plan-text-action" data-agent-plan-cancel>停止计划</button><button type="button" class="primary" disabled>正在自动生成字幕…</button>`;
      }
      if (currentTool === "review_cover_variants") {
        const subject = coverRequirement(plan).subject;
        const job = global.ClipTalkCurrentJobSnapshot?.() || {};
        const activeId = String(job?.coverTimelineDraft?.activeVariantId || job?.coverDraft?.selectedVariantId || "");
        const activeVariant = (job?.coverDraft?.variants || []).find((item) => String(item?.variantId || "") === activeId);
        const reviewError = coverVariantReviewError(plan, activeVariant);
        if (reviewError) {
          return `${detail}<button type="button" class="agent-plan-text-action" data-agent-cover-timeline-open>查看问题候选</button><button type="button" class="primary" data-agent-replan>修改封面要求</button><small>${escapeHtml(reviewError)}</small>`;
        }
        return `${detail}<button type="button" class="agent-plan-text-action" data-agent-replan>修改后重新生成</button><button type="button" class="primary" data-agent-cover-timeline-open>${escapeHtml(subject ? "核对封面人物" : "检查封面候选")}</button>`;
      }
      if (currentTool === "layout_subtitles") {
        return `${detail}<button type="button" class="agent-plan-text-action" data-agent-action-reject>停止</button><button type="button" class="primary" data-agent-action-retry>恢复字幕并应用顶部排版</button>`;
      }
      const hasTimeline = Boolean(progress.current?.result?.sessionId);
      const timelineLabel = progress.current?.result?.action === "content_evidence_review" ? "" : currentTool === "propose_timeline_edit"
        ? hasTimeline ? "打开精剪时间线" : "重新生成草案"
        : currentTool === "confirm_timeline_edit" ? "打开并审核草案"
          : currentTool === "prepare_subtitle_review" && hasTimeline ? "生成并校对字幕" : "";
      const timelineAction = timelineLabel
        ? `<button type="button" class="primary" data-agent-action-open-timeline>${timelineLabel}</button>` : "";
      const resolveClass = timelineAction ? "agent-plan-text-action" : "primary";
      return `${detail}<button type="button" class="agent-plan-text-action" data-agent-action-reject>停止</button>${timelineAction}<button type="button" class="${resolveClass}" data-agent-action-resolve>${escapeHtml(actionButtonLabel(progress.current))}</button>`;
    }
    if (["running", "approved"].includes(plan.status)) return `${detail}<button type="button" class="agent-plan-text-action" data-agent-plan-cancel>停止计划</button>`;
    if (plan.status === "no_result") {
      const terminal = noResultStep(plan);
      const artifact = terminal?.result?.artifact && typeof terminal.result.artifact === "object"
        ? terminal.result.artifact : {};
      const reasonCode = String(artifact.reasonCode || "");
      const terminalTool = String(terminal?.tool || "");
      const hasSearchStep = (plan.steps || []).some((step) => String(step?.tool || "") === "search_content");
      if (artifact.kind === "precondition_missing" || reasonCode.startsWith("missing_")) {
        return `${detail}<button type="button" class="primary" data-agent-replan>调整要求</button>`;
      }
      if (reasonCode === "ambiguous_identity" && ["select_people", "select_speakers"].includes(terminalTool)) {
        return `${detail}<button type="button" class="primary" data-agent-plan-retry-failed data-retry-label="重新识别">重新识别</button>`;
      }
      if (["insufficient_coverage", "duration_constraint_unmet"].includes(reasonCode) && terminalTool === "propose_timeline_edit") {
        return `${detail}<button type="button" class="primary" data-agent-plan-retry-failed data-retry-label="重新编排">重新编排</button>`;
      }
      if (hasSearchStep) {
        return `${detail}<button type="button" class="primary" data-agent-plan-retry-failed data-retry-label="重新检索内容">重新检索内容</button>`;
      }
      return `${detail}<button type="button" class="primary" data-agent-replan>修改要求</button>`;
    }
    const failedError = String(progress.current?.error || "");
    if (plan.status === "failed" && String(progress.current?.tool || "") === "review_content_evidence") {
      if (failedError.includes("自动编排缺少必要类别的候选")) {
        return `${detail}<button type="button" class="primary" data-agent-plan-retry-failed>重新检索缺失类别</button>`;
      }
      if (failedError.includes("内容检索没有生成可用于自动编排的有效候选")) {
        return `${detail}<button type="button" class="primary" data-agent-plan-retry-failed>重新执行失败链路</button>`;
      }
    }
    const previews = planReviewPreviews(plan);
    const cover = completedCover(plan);
    const coverState = coverCompliance(plan);
    if (["preview_ready", "completed"].includes(plan.status) && coverState.issues.length) {
      const preferred = previews[0];
      const coverAction = cover?.previewUrl
        ? `<button type="button" class="agent-plan-text-action" data-agent-cover-open data-cover-url="${escapeHtml(cover.previewUrl)}">查看当前封面</button>`
        : "";
      const previewAction = preferred
        ? `<button type="button" ${previewButtonAttributes(preferred)}>播放当前样片</button>`
        : "";
      return `${detail}${coverAction}${previewAction}<button type="button" class="primary" data-agent-replan>修改封面要求</button>`;
    }
    if (["preview_ready", "completed"].includes(plan.status) && previews.length) {
      const preferred = previews[0];
      const previewLabel = previewKind(preferred) === "cover_intro_review_preview"
        ? `播放带封面片头的${preferred.reframe?.aspect || "最终"}样片`
        : previewKind(preferred) === "social_reframe_preview"
          ? `播放 ${preferred.reframe?.aspect || "竖屏"} 样片` : "播放样片";
      const quality = planQcState(plan);
      const range = formatQcRange(quality.firstRange);
      const coverAction = cover?.previewUrl
        ? `<button type="button" class="agent-plan-text-action" data-agent-cover-open data-cover-url="${escapeHtml(cover.previewUrl)}">查看封面</button>`
        : "";
      if (quality.status === "failed") {
        const issueStart = Number(quality.firstRange?.start);
        const issueLocation = Number.isFinite(issueStart) ? ` data-qc-start="${issueStart}"` : "";
        return `${detail}${coverAction}<button type="button" ${previewButtonAttributes(preferred)}>播放完整样片</button><button type="button" class="agent-plan-text-action" ${previewButtonAttributes(preferred)}${issueLocation}>${escapeHtml(range ? `播放问题片段 ${range}` : "播放并检查问题")}</button><button type="button" class="primary" data-agent-plan-retry-failed>修正并重新质检</button>`;
      }
      const issueStart = Number(quality.firstRange?.start);
      const warningLocation = quality.status === "warning" && quality.firstRange && Number.isFinite(issueStart)
        ? ` data-qc-start="${issueStart}"` : "";
      const fullPreview = warningLocation ? `<button type="button" ${previewButtonAttributes(preferred)}>播放完整样片</button>` : "";
      return `${detail}${coverAction}${fullPreview}<button type="button" class="agent-plan-text-action" ${previewButtonAttributes(preferred)}${warningLocation}>${escapeHtml(warningLocation ? `查看问题片段 ${range}` : previewLabel)}</button><button type="button" class="primary" data-agent-preview-export data-export-plan="${escapeHtml(plan.id)}" data-export-filename="${escapeHtml(preferred.filename || "")}" data-export-revision="${escapeHtml(preferred.revision ?? preferred.sourceEditSessionRevision ?? "")}">生成成片</button>`;
    }
    if (["preview_ready", "completed"].includes(plan.status) && cover?.previewUrl) {
      return `${detail}<button type="button" class="agent-plan-text-action" data-agent-cover-open data-cover-url="${escapeHtml(cover.previewUrl)}">查看生成的封面</button><button type="button" class="primary" data-agent-cover-timeline-open>打开封面时间轴</button>`;
    }
    return detail;
  }

  function bindPlanActions(root) {
    const boundJobId = global.ClipTalkCurrentJobId?.();
    root?.querySelectorAll("[data-result-action]").forEach(button => button.addEventListener("click", () => {
      if (boundJobId !== global.ClipTalkCurrentJobId?.()) return;
      Promise.resolve(global.ClipTalkVersionAction?.(button.dataset.resultFilename, button.dataset.resultAction)).catch(error => global.showToast?.(error.message));
    }));
    root?.querySelectorAll("[data-agent-replan]").forEach(button => button.addEventListener("click", () => {
      if (boundJobId !== global.ClipTalkCurrentJobId?.()) return;
      reviseActivePlanGoal();
    }));
    root?.querySelectorAll("[data-agent-evidence-open]").forEach((button) => button.addEventListener("click", () => global.ClipTalkOpenContentEvidence?.()));
    root?.querySelectorAll("[data-plan-output-settings]").forEach((button) => button.addEventListener("click", () => global.ClipTalkWorkspaceController?.openRail?.("project")));
    root?.querySelectorAll("[data-plan-revise-goal]").forEach((button) => button.addEventListener("click", openPlanRevision));
    root?.querySelectorAll("[data-agent-plan-open]").forEach((button) => button.addEventListener("click", openPlanDrawer));
    root?.querySelectorAll("[data-agent-plan-confirm]").forEach((button) => button.addEventListener("click", confirmPlan));
    root?.querySelectorAll("[data-agent-plan-revise]").forEach((button) => button.addEventListener("click", openPlanRevision));
    root?.querySelectorAll("[data-agent-plan-cancel]").forEach((button) => button.addEventListener("click", cancelPlan));
    root?.querySelectorAll("[data-agent-plan-retry-failed]").forEach((button) => button.addEventListener("click", retryFailedPlan));
    root?.querySelectorAll("[data-agent-action-open-timeline]").forEach((button) => button.addEventListener("click", openTimelineAction));
    root?.querySelectorAll("[data-agent-action-retry]").forEach((button) => button.addEventListener("click", retryActionStep));
    root?.querySelectorAll("[data-agent-action-resolve]").forEach((button) => button.addEventListener("click", (event) => resolveAction(event, true)));
    root?.querySelectorAll("[data-agent-action-reject]").forEach((button) => button.addEventListener("click", (event) => resolveAction(event, false)));
    root?.querySelectorAll("[data-agent-preview-export]").forEach((button) => button.addEventListener("click", exportPlanPreview));
    root?.querySelectorAll("[data-agent-review-open]").forEach((button) => button.addEventListener("click", openAgentReview));
    root?.querySelectorAll("[data-agent-cover-open]").forEach((button) => button.addEventListener("click", (event) => {
      const url = String(event.currentTarget?.dataset?.coverUrl || completedCover(activePlan)?.previewUrl || "");
      if (url) global.open(url, "_blank", "noopener");
    }));
    root?.querySelectorAll("[data-agent-cover-timeline-open]").forEach((button) => button.addEventListener("click", openCoverTimeline));
  }

  function reviseActivePlanGoal() {
    if (!activePlan) return false;
    global.setChatInputDraft?.(activePlan.goal || "");
    closePlanDrawer();
    document.querySelector('#chatInput')?.focus();
    return true;
  }

  global.ClipTalkReviseAgentGoal = reviseActivePlanGoal;

  async function retryActiveCoverCandidates() {
    const step = planProgress(activePlan).current;
    if (!activePlan || String(activePlan.status || "") !== "action_required" || String(step?.tool || "") !== "review_cover_variants") {
      throw new Error("当前计划不在封面复核步骤");
    }
    const result = await api.requestJson(`/api/agent/plans/${encodeURIComponent(activePlan.id)}/actions/retry`, {
      method: "POST",
    });
    renderPlan(result.plan);
    global.ClipTalkRefreshCurrentJob?.();
    clearTimeout(pollTimer);
    pollTimer = global.setTimeout(refreshPlan, 700);
    return result.plan;
  }

  global.ClipTalkRetryCoverCandidates = retryActiveCoverCandidates;

  async function exportPlanPreview(event) {
    const button = event.currentTarget;
    if (button.dataset.exportPlan !== activePlan?.id) return global.showToast?.("方案已更新，请重新选择待生成的样片");
    const preview = planReviewPreviews(activePlan).find(item => String(item.filename || "") === button.dataset.exportFilename
      && String(item.revision ?? item.sourceEditSessionRevision ?? "") === button.dataset.exportRevision);
    if (!preview || button.disabled) return;
    button.disabled = true;
    const previousLabel = button.textContent;
    button.textContent = "正在打开导出确认…";
    try {
      if (typeof global.ClipTalkExportAgentReviewPreview === "function") {
        await global.ClipTalkExportAgentReviewPreview(preview);
      } else {
        await global.ClipTalkOpenAgentPreview?.(preview);
        const fallback = document.querySelector("#finalizePreviewButton:not(.hidden), #finalizeOneOffButton:not(.hidden)");
        if (!fallback) throw new Error("成片版本生成入口尚未就绪，请先播放样片");
        fallback.click();
      }
    } catch (error) {
      global.showToast?.(error.message || "无法打开成片版本生成确认", "error");
    } finally {
      if (button.isConnected) {
        button.disabled = false;
        button.textContent = previousLabel;
      }
    }
  }

  function openCoverTimeline() {
    if (typeof global.ClipTalkOpenCoverTimeline !== "function") {
      global.showToast?.("封面时间轴尚未加载，请刷新页面后重试", "error");
      return;
    }
    if (global.ClipTalkOpenCoverTimeline()) closePlanDrawer();
  }

  async function retryFailedPlan(event) {
    const button = event.currentTarget;
    if (!activePlan || button.disabled) return;
    button.disabled = true;
    const noResult = String(activePlan.status || "") === "no_result";
    const missingCategory = String(planProgress(activePlan).current?.error || "")
      .includes("自动编排缺少必要类别的候选");
    const retryLabel = String(button.dataset.retryLabel || "");
    button.textContent = retryLabel.includes("识别") ? "正在重新识别…"
      : retryLabel.includes("编排") ? "正在重新编排…"
      : noResult || missingCategory ? "正在重新检索…"
      : planQcState(activePlan).status === "failed" ? "正在修正并重新质检…" : "正在重新编排…";
    try {
      const result = await api.requestJson(`/api/agent/plans/${encodeURIComponent(activePlan.id)}/actions/retry`, {
        method: "POST",
      });
      renderPlan(result.plan);
      global.ClipTalkRefreshCurrentJob?.();
      pollTimer = global.setTimeout(refreshPlan, 700);
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      button.disabled = false;
      button.textContent = retryLabel || (activePlan && planQcIssueSummary(activePlan)
        ? "修正并重新质检"
        : noResult ? "重新检索内容" : missingCategory ? "重新检索缺失类别" : "重新执行失败链路");
      global.showToast?.(error.message || "无法重新执行失败链路", "error");
    }
  }

  async function retryActionStep(event) {
    const button = event.currentTarget;
    if (!activePlan || button.disabled) return;
    const previousLabel = button.textContent;
    button.disabled = true;
    button.textContent = previousLabel.includes("核实") ? "正在查询操作记录…" : "正在恢复字幕…";
    try {
      const result = await api.requestJson(`/api/agent/plans/${encodeURIComponent(activePlan.id)}/actions/retry`, {
        method: "POST",
      });
      renderPlan(result.plan);
      global.ClipTalkRefreshCurrentJob?.();
      clearTimeout(pollTimer);
      pollTimer = global.setTimeout(refreshPlan, 700);
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      button.disabled = false;
      button.textContent = previousLabel;
      global.showToast?.(error.message || "无法恢复字幕排版步骤", "error");
    }
  }

  async function openAgentReview(event) {
    const sessionId = String(event.currentTarget?.dataset?.sessionId || "");
    const kind = String(event.currentTarget?.dataset?.previewKind || "");
    const previewFilename = String(event.currentTarget?.dataset?.previewFilename || "");
    const previewUrl = String(event.currentTarget?.dataset?.previewUrl || "");
    if (typeof global.ClipTalkOpenAgentPreview !== "function") {
      global.showToast?.("审核预览播放器尚未加载，请刷新页面后重试", "error");
      return;
    }
    try {
      // Playback and editing are deliberately separate actions. A review
      // sample may carry an edit-session id for later revisions, but clicking
      // “播放” must stay in the main review player. The player exposes the
      // explicit return-to-editor action when that session is editable.
      const preview = planReviewPreviews(activePlan).find((item) => {
        if (previewFilename && String(item?.filename || "") === previewFilename) return true;
        if (previewUrl && String(item?.previewUrl || item?.videoUrl || "") === previewUrl) return true;
        if (sessionId && [item?.sessionId, item?.sourceEditSessionId, item?.editSessionId]
          .some((value) => String(value || "") === sessionId)) return true;
        return false;
      }) || {};
      await global.ClipTalkOpenAgentPreview({
        ...preview,
        filename: previewFilename || String(preview.filename || ""),
        previewUrl: previewUrl || String(preview.previewUrl || preview.videoUrl || ""),
        title: String(event.currentTarget?.dataset?.previewTitle || preview.title || "审核样片"),
        width: Number(event.currentTarget?.dataset?.previewWidth || preview.width || 0),
        height: Number(event.currentTarget?.dataset?.previewHeight || preview.height || 0),
        duration: Number(event.currentTarget?.dataset?.previewDuration || preview.duration || 0),
        aspect: String(event.currentTarget?.dataset?.previewAspect || preview.reframe?.aspect || ""),
        ...(sessionId && !preview.sessionId && !preview.sourceEditSessionId ? { sessionId } : {}),
        outputKind: String(preview?.outputKind || preview?.kind || kind || "agent_review_preview"),
      });
      seekToQcIssue(event.currentTarget);
      closePlanDrawer();
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      global.showToast?.(error.message || "无法打开审核预览", "error");
    }
  }

  function seekToQcIssue(button) {
    if (!button?.hasAttribute("data-qc-start")) return;
    const start = Number(button.dataset.qcStart);
    const video = $("#mainVideo");
    if (!Number.isFinite(start) || !video) return;
    const seek = () => {
      try {
        video.currentTime = Math.max(0, start);
        video.play?.().catch(() => {});
      } catch (_) {}
    };
    if (video.readyState >= 1) seek();
    else video.addEventListener("loadedmetadata", seek, { once: true });
  }

  function renderPlanDrawer(plan, progress) {
    const drawer = $("#agentPlanDrawer");
    const panel = $("#agentPlanDrawerPlan");
    if (!drawer || !panel) return;
    // Timeline editing can be contributed by another skill (for example the
    // content extractor), so derive the surface from actual plan tools rather
    // than relying only on the primary skill id.
    drawer.dataset.planSurface = planUsesPrecisionEditor(plan) ? "editor" : "agent";
    $("#agentPlanDrawerKicker").textContent = `${planDisplayStatus(plan)} · ${planProgressLabel(progress)}`;
    $("#agentPlanDrawerTitle").textContent = skillLabel(plan.skillId);
    const previews = planReviewPreviews(plan);
    const previewMarkup = previews.length ? `<section class="agent-review-results"><small>审核样片</small>${previews.map((item, index) => `<button type="button" ${previewButtonAttributes(item)}><strong>${escapeHtml(item.title || `审核样片 ${index + 1}`)}</strong><span>${escapeHtml(previewMeta(item))}</span><span>内容核验：${item.contentVerification?.passed === true ? "抽检通过" : item.contentVerification ? "待复核" : "无核验记录"} · 画面检查：${({ passed: "通过", warning: "有提醒", failed: "未通过", not_run: "未检查" })[planQcState(plan).status]}</span></button>`).join("")}</section>` : "";
    const qcMarkup = qcSummaryMarkup(plan);
    const coverMarkup = coverReviewMarkup(plan) || coverResultMarkup(plan);
    const understandingMarkup = planUnderstandingMarkup(plan);
    panel.innerHTML = `<section class="agent-plan-drawer-summary"><p>${escapeHtml(plan.summary || "按当前目标生成的可审核执行计划")}</p><small>${escapeHtml(executionModeLabel(plan))}</small>${understandingMarkup}${progressSegments(plan)}</section>${qcMarkup}${previewMarkup}${coverMarkup}<ol class="agent-plan-step-list">${presentationSteps(plan).map((step) => {
      const status = String(step.status || "");
      const expanded = ["running", "waiting_operation", "action_required", "failed"].includes(status)
        || Boolean(stepStatusDetail(step))
        || (status === "pending" && String(step.id || "") === String(progress.current?.id || ""));
      const executionDetail = String(step.status || "") === "failed"
        ? `<details><summary>查看执行信息</summary><small>${escapeHtml(toolLabel(step.tool))}</small></details>`
        : "";
      const result = step.result && typeof step.result === "object" ? step.result : {};
      const stepDetail = status === "action_required"
        ? String(result.message || step.expectedOutput || "等待你完成当前操作")
        : String(stepStatusDetail(step) || step.expectedOutput || "等待执行");
      const statusText = status === "action_required" && isAutomaticSubtitleRecovery(plan, progress)
        && String(step.id || "") === String(progress.current?.id || "")
        ? "自动恢复中" : stepDisplayStatus(step);
      return `<li data-step-status="${escapeHtml(step.status)}" ${expanded ? "data-expanded=true" : ""}><span class="agent-step-marker" aria-hidden="true"></span><div><header><strong>${escapeHtml(step.title || toolLabel(step.tool))}</strong><b>${escapeHtml(statusText)}</b></header>${expanded ? `<p>${escapeHtml(stepDetail)}</p>` : ""}${step.error ? `<em>${escapeHtml(step.error)}</em>` : ""}${executionDetail}</div></li>`;
    }).join("")}</ol><section class="agent-plan-revision" hidden><label><span>修改这份规划</span><textarea rows="3" maxlength="1000" data-agent-plan-revision-input placeholder="例如：不要字幕；把目标时长改为 90 秒"></textarea></label><div><button type="button" data-agent-plan-revision-close>取消</button><button type="button" class="primary" data-agent-plan-revision-submit>生成修改方案</button></div></section>`;
    $("#agentPlanDrawerFooter").innerHTML = planActionMarkup(plan, progress, true);
    bindPlanActions(drawer);
    drawer.querySelector("[data-agent-plan-revision-close]")?.addEventListener("click", closePlanRevision);
    drawer.querySelector("[data-agent-plan-revision-submit]")?.addEventListener("click", submitPlanRevision);
    renderActivity();
  }

  function renderPlan(plan) {
    activePlan = plan;
    const dock = $("#agentPlanDock");
    if (!dock) return;
    document.querySelector(".chat-panel")?.classList.add("agent-plan-active");
    dock.classList.remove("hidden");
    const progress = planProgress(plan);
    const job = global.ClipTalkCurrentJobSnapshot?.();
    const hasPreservedOutput = Boolean(
      (job?.outputs || []).length
      || (job?.outputVersions || []).some((version) => (version?.outputs || []).length)
    );
    const qcIssueSummary = planQcIssueSummary(plan);
    const cover = completedCover(plan);
    const previews = planReviewPreviews(plan);
    const coverState = coverCompliance(plan);
    const message = ["preview_ready", "completed"].includes(plan.status)
      ? coverState.issues.length
        ? `封面未按要求完成：${coverState.issues.join("；")}`
        : qcIssueSummary
        ? `审核样片已保留，但质检未通过：${qcIssueSummary}`
        : previews.length
          ? "审核样片已生成，可以在下方预览。"
          : cover
            ? "封面已生成并保存为当前任务封面。点击下方按钮即可查看或下载。"
          : `全部 ${progress.total} 个步骤均已完成，可在当前任务中查看结果。`
      : plan.status === "awaiting_confirmation" ? String(plan.summary || "检查计划范围后再开始分析或剪辑。")
        : plan.status === "failed" && hasPreservedOutput
          ? `${planActionMessage(plan, progress)}；已有成片已保留，可继续预览或下载。`
          : planActionMessage(plan, progress);
    dock.dataset.status = plan.status;
    dock.dataset.tone = coverState.issues.length || qcIssueSummary ? "attention" : planStatusTone(plan.status);
    dock.dataset.planSurface = planUsesPrecisionEditor(plan) ? "editor" : "agent";
    const controlMarkup = planControlMarkup({
      goal: plan.goal || plan.summary || message,
      stage: currentStageText(plan, progress),
      next: nextStepText(plan, progress),
      meta: executionModeLabel(plan),
    });
    const understandingMarkup = planUnderstandingMarkup(plan, { compact: true });
    const historical = planIsHistorical(plan);
    dock.dataset.historical = String(historical);
    dock.innerHTML = `<header><small>${historical ? "上次剪辑方案" : "当前剪辑方案"}</small><b>${historical ? "历史记录" : escapeHtml(planDisplayStatus(plan))}</b></header><details class="assistant-plan-summary" ${plan.status === "awaiting_confirmation" ? "open" : ""}><summary>${historical ? "查看上次处理结果" : escapeHtml(currentStageText(plan, progress))}</summary>${understandingMarkup}${controlMarkup}<p class="agent-plan-progress-summary">本次计划 · ${escapeHtml(planProgressLabel(progress))}</p></details>${coverStatusMarkup(plan)}<footer>${planActionMarkup(plan, progress)}</footer>`;
    const formal = global.ClipTalkOrderedJobOutputs?.(job)?.filter(({ item, version }) => !item.previewOnly && !version.previewOnly).at(-1);
    if (job?.presentation?.key === "exported" && historical && formal) {
      const { item, version } = formal;
      dock.dataset.tone = "success";
      dock.innerHTML = `<header><small>当前结果</small><b>成片已生成</b></header><div class="assistant-result-summary">V${Number(version.number || 1)} · ${Number(item.duration || 0).toFixed(1)} 秒 · ${escapeHtml(item.displayTitle || job.filename || "成片")}</div><footer><button type="button" class="primary" data-result-action="preview" data-result-filename="${escapeHtml(item.filename)}">播放成片</button><button type="button" data-result-action="edit" data-result-filename="${escapeHtml(item.filename)}" ${item.capabilities?.canEdit === false ? "disabled" : ""}>编辑版本</button></footer><details><summary>历史执行记录</summary>${controlMarkup}<footer>${planActionMarkup(plan, progress)}</footer></details>`;
    }
    bindPlanActions(dock);
    renderPlanDrawer(plan, progress);
    subscribeActivity(activeWorkspace?.id || plan.workspaceId);
    resumeAutonomousSubtitleRecovery(plan, progress);
  }

  function resumeAutonomousSubtitleRecovery(plan, progress) {
    const currentTool = String(progress?.current?.tool || "");
    if (
      String(plan?.status || "") !== "action_required"
      || String(plan?.executionMode || "") !== "autonomous_review"
      || !["prepare_subtitle_review", "layout_subtitles"].includes(currentTool)
    ) return;
    const planId = String(plan.id || "");
    if (!planId) return;
    const resumeKey = `${planId}:${String(progress?.current?.id || currentTool)}`;
    if (automaticSubtitleResumeIds.has(resumeKey)) return;
    automaticSubtitleResumeIds.add(resumeKey);
    const repairButton = document.querySelector("#agentPlanDock [data-agent-action-retry]");
    if (repairButton) {
      repairButton.disabled = true;
      repairButton.textContent = currentTool === "layout_subtitles" ? "正在恢复字幕并应用排版…" : "正在自动生成字幕…";
    }
    global.setTimeout(async () => {
      try {
        const result = await api.requestJson(`/api/agent/plans/${encodeURIComponent(planId)}/actions/retry`, {
          method: "POST",
        });
        renderPlan(result.plan);
        global.ClipTalkRefreshCurrentJob?.();
        pollTimer = global.setTimeout(refreshPlan, 700);
      } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
        automaticSubtitleResumeIds.delete(resumeKey);
        if (repairButton?.isConnected) {
          repairButton.disabled = false;
          repairButton.textContent = "恢复字幕并应用顶部排版";
        }
        global.showToast?.(error.message || "无法继续自动生成并排版字幕", "error");
      }
    }, 0);
  }

  function activityCopy(event) {
    const type = String(event?.type || "");
    const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
    const step = payload.step && typeof payload.step === "object" ? payload.step : {};
    if (type === "workspace.created") return ["工作区已准备", "素材与任务已关联"];
    if (type === "plan.created") return ["计划已生成", "等待确认后开始执行"];
    if (type === "plan.confirmation_required") return ["计划等待确认", "尚未开始分析或渲染"];
    if (type === "plan.approved") return ["计划已确认", "正在执行前置步骤"];
    if (type === "plan.completed") return ["计划已完成", "结果已写入当前任务"];
    if (type === "plan.cancelled") return ["计划已停止", "没有继续执行后续步骤"];
    if (type === "plan.no_result") return ["未找到可用内容", "后续时间线与渲染步骤已跳过"];
    if (type === "plan.failed") return ["计划未完成", "请检查失败步骤"];
    if (type === "step.started") return [step.title || toolLabel(step.tool), "开始执行"];
    if (type === "step.completed") return [step.title || toolLabel(step.tool), "执行完成"];
    if (type === "step.failed") return [step.title || toolLabel(step.tool), step.error || "执行失败"];
    if (type === "action.required") return [step.title || "需要你处理", step.result?.message || "等待人工确认"];
    if (type === "action.resolved") return ["人工确认已保存", "计划继续执行"];
    if (type === "plan.replanned") return payload.material
      ? ["计划已重新整理", "调整后的步骤需要重新确认"]
      : ["计划已自动调整", "正在从可恢复的失败步骤继续"];
    if (type === "plan.replan_skipped") return ["未重复执行相同步骤", payload.error || "当前证据缺口无法通过相同计划修复"];
    if (type === "agent.message_update") return [payload.title || "规划状态更新", payload.detail || "正在整理执行计划"];
    return ["计划状态更新", type.replaceAll(".", " ")];
  }

  function renderActivity() {
    const root = $("#agentPlanDrawerActivity");
    if (!root) return;
    const repeatedPlanningUpdates = new Set();
    const events = activityEvents.slice(-80).reverse().filter((event) => {
      if (String(event?.type || "") === "plan.created") {
        repeatedPlanningUpdates.clear();
        return true;
      }
      if (String(event?.type || "") !== "agent.message_update") return true;
      const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
      const key = `${String(payload.title || "")}\n${String(payload.detail || "")}`;
      if (repeatedPlanningUpdates.has(key)) return false;
      repeatedPlanningUpdates.add(key);
      return true;
    });
    if (!events.length) {
      root.innerHTML = '<div class="agent-activity-empty"><strong>还没有活动记录</strong><p>计划开始后，规划、执行和确认记录会显示在这里。</p></div>';
      return;
    }
    root.innerHTML = `<ol class="agent-activity-list">${events.map((event) => {
      const [title, detail] = activityCopy(event);
      const time = event.createdAt ? new Date(event.createdAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : "";
      return `<li><time>${escapeHtml(time)}</time><span aria-hidden="true"></span><div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p></div></li>`;
    }).join("")}</ol>`;
  }

  function activityEventShouldSync(type) {
    return [
      "plan.approved",
      "plan.completed",
      "preview.ready",
      "plan.replan_skipped",
      "plan.no_result",
      "plan.failed",
      "plan.cancelled",
      "plan.replanned",
      "step.completed",
      "step.failed",
      "step.skipped",
      "action.required",
      "action.resolved",
    ].includes(String(type || ""));
  }

  function scheduleAgentWorkspaceSync(delay = 180) {
    global.clearTimeout(activityRefreshTimer);
    activityRefreshTimer = global.setTimeout(async () => {
      activityRefreshTimer = null;
      if (!activePlan?.id) {
        global.ClipTalkRefreshCurrentJob?.();
        return;
      }
      clearTimeout(pollTimer);
      try {
        await refreshPlan();
      } finally {
        // Agent events are the earliest signal that outputs, handoff state, or
        // action-required metadata changed. Refresh the shared job snapshot too
        // so the main player can pick up the generated preview without a page
        // reload.
        global.ClipTalkRefreshCurrentJob?.();
      }
    }, Math.max(0, Number(delay) || 0));
  }

  function subscribeActivity(workspaceId) {
    const id = String(workspaceId || "");
    if (!id || (activityWorkspaceId === id && activitySource)) return;
    activitySource?.close();
    activityWorkspaceId = id;
    activityEvents = [];
    const source = new EventSource(`/api/agent/workspaces/${encodeURIComponent(id)}/events?after=0`);
    activitySource = source;
    const eventNames = ["workspace.created", "agent.message_update", "plan.created", "plan.confirmation_required", "plan.approved", "plan.completed", "preview.ready", "plan.replan_skipped", "plan.no_result", "plan.failed", "plan.cancelled", "plan.replanned", "step.started", "step.completed", "step.failed", "step.skipped", "action.required", "action.resolved"];
    eventNames.forEach((name) => source.addEventListener(name, (message) => {
      try {
        if (activitySource !== source || activityWorkspaceId !== id) return;
        const event = JSON.parse(message.data);
        if (activityEvents.some((item) => Number(item.sequence) === Number(event.sequence))) return;
        activityEvents.push(event);
        if (activityEvents.length > 200) activityEvents.shift();
        renderActivity();
        if (activityEventShouldSync(name)) scheduleAgentWorkspaceSync();
      } catch { /* Ignore malformed history rows without breaking the plan. */ }
    }));
    source.onopen = () => {
      if (activitySource === source && activePlan && ["running", "approved", "action_required"].includes(activePlan.status)) {
        clearTimeout(pollTimer);
        pollTimer = global.setTimeout(refreshPlan, 0);
      }
    };
    source.onerror = () => { if (activitySource === source && source.readyState === EventSource.CLOSED) activitySource = null; };
  }

  function setPlanDrawerTab(tab) {
    planDrawerTab = tab === "activity" ? "activity" : "plan";
    document.querySelectorAll("[data-agent-drawer-tab]").forEach((button) => {
      const active = button.dataset.agentDrawerTab === planDrawerTab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll("[data-agent-drawer-panel]").forEach((panel) => panel.classList.toggle("hidden", panel.dataset.agentDrawerPanel !== planDrawerTab));
  }

  function ensurePlanDrawerPortal() {
    const drawer = $("#agentPlanDrawer");
    const scrim = $("#agentPlanDrawerScrim");
    if (!drawer || !document.body) return drawer;
    // The assistant rail intentionally clips its own scrolling content. Keep
    // this workspace-wide dialog at body level so it cannot be clipped or
    // painted underneath the preview and review columns.
    if (scrim?.parentElement !== document.body) document.body.append(scrim);
    if (drawer.parentElement !== document.body) document.body.append(drawer);
    return drawer;
  }

  function openPlanDrawer(event) {
    const drawer = ensurePlanDrawerPortal();
    if (!drawer) return;
    if (global.ClipTalkPrepareWorkspaceOverlay?.("agentPlan") === false) return;
    global.clearTimeout(planDrawerCloseTimer);
    planDrawerCloseTimer = null;
    planDrawerReturnFocus = event?.currentTarget || document.activeElement;
    const requestedTab = event?.currentTarget?.dataset?.agentPlanOpen;
    if (requestedTab === "plan" || requestedTab === "activity") planDrawerTab = requestedTab;
    const panel = document.querySelector(".chat-panel")?.getBoundingClientRect();
    if (panel && global.innerWidth > 760) {
      drawer.style.setProperty("--agent-drawer-left", `${Math.round(panel.right - 1)}px`);
      drawer.style.setProperty("--agent-drawer-top", `${Math.round(panel.top)}px`);
      drawer.style.setProperty("--agent-drawer-height", `${Math.round(panel.height)}px`);
    }
    drawer.classList.remove("hidden");
    drawer.inert = false;
    drawer.dataset.overlayState = "opening";
    drawer.setAttribute("aria-hidden", "false");
    const scrim = $("#agentPlanDrawerScrim");
    scrim?.classList.remove("hidden");
    setPlanDrawerTab(planDrawerTab);
    planDrawerReleaseFocus?.(false);
    planDrawerReleaseFocus = global.ClipTalkActivateModalFocus?.(drawer, {
      initialFocus: drawer.querySelector("#agentPlanDrawerClose"),
      additionalActive: [scrim].filter(Boolean),
      restoreFocus: false,
    }) || null;
    requestAnimationFrame(() => {
      drawer.classList.add("open");
      drawer.dataset.overlayState = "open";
    });
    drawer.querySelector("#agentPlanDrawerClose")?.focus();
  }

  function closePlanDrawer({ restoreFocus = true } = {}) {
    const drawer = $("#agentPlanDrawer");
    if (!drawer || drawer.classList.contains("hidden")) return;
    drawer.classList.remove("open");
    drawer.dataset.overlayState = "closing";
    $("#agentPlanDrawerScrim")?.classList.add("hidden");
    planDrawerReleaseFocus?.(false);
    planDrawerReleaseFocus = null;
    global.clearTimeout(planDrawerCloseTimer);
    planDrawerCloseTimer = global.setTimeout(() => {
      drawer.classList.add("hidden");
      drawer.inert = true;
      drawer.dataset.overlayState = "closed";
      drawer.setAttribute("aria-hidden", "true");
      if (restoreFocus) planDrawerReturnFocus?.focus?.();
      planDrawerReturnFocus = null;
      planDrawerCloseTimer = null;
    }, 190);
  }

  global.ClipTalkCloseAgentPlanDrawer = closePlanDrawer;

  function reset() {
    viewGeneration += 1;
    retryCount = 0;
    for (const request of pendingRequests) request.abort();
    pendingRequests.clear();
    const input = $("#chatInput");
    if (input) input.disabled = false;
    const send = $("#sendButton");
    if (send) send.disabled = false;
    clearTimeout(pollTimer);
    pollTimer = null;
    global.clearTimeout(activityRefreshTimer);
    activityRefreshTimer = null;
    activitySource?.close();
    activitySource = null;
    activityWorkspaceId = "";
    activityEvents = [];
    activePlan = null;
    activeWorkspace = null;
    retrySubmission = null;
    $("#assistantPendingChanges")?.remove();
    planDrawerReturnFocus = null;
    workspaceRestoreByJob.clear();
    document.querySelector(".chat-panel")?.classList.remove("agent-plan-active");
    const dock = $("#agentPlanDock");
    if (dock) {
      dock.classList.add("hidden");
      dock.removeAttribute("data-status");
      dock.removeAttribute("data-tone");
      dock.removeAttribute("data-plan-surface");
      dock.innerHTML = "";
    }
    const drawer = $("#agentPlanDrawer");
    global.clearTimeout(planDrawerCloseTimer);
    planDrawerCloseTimer = null;
    planDrawerReleaseFocus?.(false);
    planDrawerReleaseFocus = null;
    if (drawer) {
      drawer.classList.remove("open");
      drawer.classList.add("hidden");
      drawer.inert = true;
      drawer.setAttribute("aria-hidden", "true");
      drawer.removeAttribute("data-plan-surface");
    }
    $("#agentPlanDrawerScrim")?.classList.add("hidden");
    const drawerPlan = $("#agentPlanDrawerPlan");
    if (drawerPlan) drawerPlan.innerHTML = "";
    const drawerActivity = $("#agentPlanDrawerActivity");
    if (drawerActivity) drawerActivity.innerHTML = "";
    const drawerFooter = $("#agentPlanDrawerFooter");
    if (drawerFooter) drawerFooter.innerHTML = "";
  }

  async function refreshPlan() {
    if (!activePlan?.id) return;
    const context = owner();
    const planId = activePlan.id;
    try {
      const result = await api.requestJson(`/api/agent/plans/${encodeURIComponent(planId)}`);
      if (!ownsView(context) || activePlan?.id !== planId) return;
      retryCount = 0;
      renderPlan(result.plan);
      const handoff = planHandoff(result.plan);
      if (handoff?.id && String(handoff.id) !== currentJobId()) global.ClipTalkSwitchWorkspaceJob?.(handoff);
      if (["running", "approved"].includes(result.plan.status)) {
        clearTimeout(pollTimer);
        pollTimer = global.setTimeout(refreshPlan, 1200);
      } else {
        clearTimeout(pollTimer);
        global.ClipTalkRefreshCurrentJob?.();
      }
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      if (!ownsView(context) || activePlan?.id !== planId) return;
      const retryable = !error.status || error.status >= 500 || error.status === 429;
      let notice = $("#agentConnectionState");
      if (!notice) {
        notice = document.createElement("p");
        notice.id = "agentConnectionState";
        notice.setAttribute("role", "status");
        $("#agentPlanDock")?.append(notice);
      }
      notice.textContent = retryable ? "连接中断，正在重连。后台任务会继续执行。" : "暂时无法读取计划，请刷新任务状态。";
      clearTimeout(pollTimer);
      if (retryable) pollTimer = global.setTimeout(refreshPlan, Math.min(15000, 1200 * (2 ** retryCount++)));
    }
  }

  function newestPlan(plans, activePlanId = "") {
    const items = Array.isArray(plans) ? plans : [];
    return items.find((plan) => String(plan?.id || "") === String(activePlanId || ""))
      || items.slice().sort((left, right) => String(right?.createdAt || right?.updatedAt || "").localeCompare(String(left?.createdAt || left?.updatedAt || "")))[0]
      || null;
  }

  function renderPlanningStatus(workspace) {
    const dock = $("#agentPlanDock");
    if (!dock) return;
    const progress = workspace?.planningProgress && typeof workspace.planningProgress === "object"
      ? workspace.planningProgress : {};
    const title = String(progress.title || "正在生成可确认的剪辑计划");
    const detail = String(progress.detail || "正在核对目标、素材范围、可用能力和需要你确认的边界。");
    const elapsed = planningElapsed(workspace);
    const elapsedLabel = elapsed === "刚刚开始" ? elapsed : `已用 ${elapsed}`;
    const phase = String(progress.phase || "skill_selected");
    document.querySelector(".chat-panel")?.classList.add("agent-plan-active");
    dock.classList.remove("hidden");
    dock.dataset.status = "planning";
    dock.dataset.tone = "running";
    const planningSurface = String(workspace?.planningSurface || "agent") === "editor" ? "editor" : "agent";
    dock.dataset.planSurface = planningSurface;
    $("#agentPlanDrawer")?.setAttribute("data-plan-surface", planningSurface);
    const phaseLabels = {
      skill_selected: "选择剪辑方式",
      context_loading: "读取任务状态",
      context_ready: "核对素材范围",
      decomposing_goal: "拆解剪辑目标",
      validating_plan: "确认执行依赖",
      plan_ready: "等待确认计划",
    };
    dock.innerHTML = `<header><div class="agent-plan-dock-brand"><img src="/static/assets/cliptalk-director-icon.png?v=20260812-1" alt="" aria-hidden="true" /><div><small>剪辑计划</small><strong>正在生成计划</strong><span><i aria-hidden="true"></i>确认前不会分析或渲染</span></div></div><b class="agent-planning-live"><i aria-hidden="true"></i>正在生成</b></header>${planControlMarkup({
      goal: "等待确认剪辑目标",
      stage: phaseLabels[phase] || title,
      next: detail,
      meta: elapsedLabel,
    })}${planningFlowMarkup(phase, false, title, detail)}<footer><span>计划生成中</span><button type="button" class="agent-plan-text-action" data-agent-plan-open="activity">查看活动</button></footer>`;
    bindPlanActions(dock);
    $("#agentPlanDrawerKicker").textContent = `正在生成 · ${elapsed}`;
    $("#agentPlanDrawerTitle").textContent = "智能剪辑计划";
    $("#agentPlanDrawerPlan").innerHTML = `<div class="agent-plan-drawer-loading"><header><strong>${escapeHtml(title)}</strong><time>${escapeHtml(elapsed)}</time></header>${planningFlowMarkup(phase, true, title, detail)}<small>这里只展示可核验的计划状态。计划生成前不会调用视频分析或渲染。</small></div>`;
    $("#agentPlanDrawerFooter").innerHTML = "";
    subscribeActivity(workspace?.id);
  }

  async function resumeForJob(job) {
    const jobId = String(job?.id || "");
    const workspaceId = String(job?.agent?.workspaceId || "");
    if (isAgentInstructionDraft(job)) {
      activePlan = null;
      activeWorkspace = null;
      workspaceRestoreByJob.delete(jobId);
      document.querySelector(".chat-panel")?.classList.remove("agent-plan-active");
      $("#agentPlanDock")?.classList.add("hidden");
      closePlanDrawer();
      return null;
    }
    const isAgentEntry = String(job?.status || "") === "awaiting_agent_plan"
      || (String(job?.request?.entryWorkflow || "") === "agent" && Boolean(workspaceId || job?.agent?.planId));
    if (!jobId || (!workspaceId && !isAgentEntry)) {
      document.querySelector(".chat-panel")?.classList.remove("agent-plan-active");
      $("#agentPlanDock")?.classList.add("hidden");
      closePlanDrawer();
      return null;
    }
    // A pre-recovery build could hand a speaker task to an empty generic
    // content-search child.  If that child finished with neither candidates
    // nor output while its parent now has an active recovery plan, keep the
    // user on the parent—the only task that can actually continue editing.
    const parentJobId = String(job?.parentJobId || "");
    const childPlanFinished = ["preview_ready", "completed"].includes(String(job?.agent?.status || ""));
    const childIsEmpty = Number(job?.candidateCount || 0) === 0 && Number(job?.outputCount || 0) === 0;
    if (parentJobId && childPlanFinished && childIsEmpty) {
      try {
        const parentResult = await api.requestJson(`/api/jobs/${encodeURIComponent(parentJobId)}`);
        const parent = parentResult?.job;
        const parentAgentStatus = String(parent?.agent?.status || "");
        const parentCanContinue = ["approved", "running", "action_required"].includes(parentAgentStatus);
        if (
          parent?.id
          && parentCanContinue
          && String(parent?.agent?.workspaceId || "")
          && String(parent?.agent?.workspaceId || "") !== workspaceId
        ) {
          global.ClipTalkSwitchWorkspaceJob?.(parent);
          return null;
        }
      } catch {
        // A missing historical parent must not prevent the child task from
        // rendering normally.
      }
    }
    const restoreKey = `${workspaceId}:${job?.agent?.planId || ""}:${job?.revision || ""}:${job?.presentation?.key || ""}`;
    if (workspaceRestoreByJob.get(jobId) === restoreKey) return activePlan;
    workspaceRestoreByJob.set(jobId, restoreKey);
    try {
      const path = workspaceId
        ? `/api/agent/workspaces/${encodeURIComponent(workspaceId)}`
        : `/api/agent/workspaces/by-job/${encodeURIComponent(jobId)}`;
      const detail = await api.requestJson(path);
      if (currentJobId() !== jobId) return null;
      const workspace = detail.workspace;
      if (!workspace?.id) return null;
      workspaceByJob.set(String(workspace.jobId || jobId), workspace);
      if (String(workspace.sourceJobId || "") === jobId) workspaceByJob.set(jobId, workspace);
      activeWorkspace = workspace;
      restorePlanMessages(detail);
      global.ClipTalkRenderAssistantHistory?.();
      renderPendingChanges();
      const plan = newestPlan(detail.plans, workspace.activePlanId || job?.agent?.planId);
      if (!plan) {
        if (String(workspace.status || "") === "planning" || workspace.planningRequestId) {
          renderPlanningStatus(workspace);
          clearTimeout(pollTimer);
          pollTimer = global.setTimeout(() => {
            workspaceRestoreByJob.delete(jobId);
            resumeForJob(job);
          }, 1800);
        }
        return null;
      }
      renderPlan(plan);
      const handoff = planHandoff(plan);
      if (handoff?.id && String(handoff.id) !== currentJobId()) global.ClipTalkSwitchWorkspaceJob?.(handoff);
      clearTimeout(pollTimer);
      if (["approved", "running"].includes(String(plan.status || ""))) {
        pollTimer = global.setTimeout(refreshPlan, 900);
      }
      return plan;
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      // A just-created task can briefly be restored before its workspace is
      // persisted. Keep the task UI usable and allow the next job revision to
      // retry; only surface real errors after an existing workspace failed.
      workspaceRestoreByJob.delete(jobId);
      if (workspaceId) global.showToast?.(error.message || "恢复 Agent 计划失败", "error");
      return null;
    }
  }

  async function confirmPlan(event) {
    const button = event.currentTarget;
    if (!activePlan || button.disabled) return;
    button.disabled = true;
    button.textContent = "正在启动…";
    try {
      const result = await api.requestJson(`/api/agent/plans/${encodeURIComponent(activePlan.id)}/confirm`, {
        method: "POST", body: { planHash: activePlan.planHash },
      });
      renderPlan(result.plan);
      global.ClipTalkRefreshCurrentJob?.();
      clearTimeout(pollTimer);
      pollTimer = global.setTimeout(refreshPlan, 700);
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      button.disabled = false;
      button.textContent = "确认并执行";
      global.showToast?.(error.message || "计划启动失败", "error");
    }
  }

  async function cancelPlan(event) {
    const button = event.currentTarget;
    if (!activePlan || button.disabled) return;
    button.disabled = true;
    try {
      const result = await api.requestJson(`/api/agent/plans/${encodeURIComponent(activePlan.id)}/cancel`, { method: "POST" });
      renderPlan(result.plan);
      global.ClipTalkRefreshCurrentJob?.();
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      button.disabled = false;
      global.showToast?.(error.message || "取消计划失败", "error");
    }
  }

  function openPlanRevision() {
    openPlanDrawer();
    setPlanDrawerTab("plan");
    const editor = $("#agentPlanDrawer .agent-plan-revision");
    if (!editor) return;
    editor.hidden = false;
    editor.querySelector("[data-agent-plan-revision-input]")?.focus();
  }

  function closePlanRevision() {
    const editor = $("#agentPlanDrawer .agent-plan-revision");
    if (editor) editor.hidden = true;
  }

  async function submitPlanRevision(event) {
    const button = event.currentTarget;
    const editor = button.closest(".agent-plan-revision");
    const input = editor?.querySelector("[data-agent-plan-revision-input]");
    const revision = String(input?.value || "").trim();
    const plan = activePlan;
    if (!plan || button.disabled) return;
    if (!revision) {
      global.showToast?.("请说明希望如何修改这份计划");
      input?.focus();
      return;
    }
    button.disabled = true;
    button.textContent = "正在生成修改方案…";
    try {
      // Replacement is server-owned: retain the old plan if planning fails.
      const revised = await submitGoal(revision, {
        visibleGoal: `修改当前规划：${revision}`,
      });
      if (!revised) return;
      global.ClipTalkRefreshCurrentJob?.();
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      button.disabled = false;
      button.textContent = "生成修改后的计划";
      global.showToast?.(error.message || "无法生成修改后的计划", "error");
    }
  }

  async function resolveAction(event, approved) {
    const button = event.currentTarget;
    if (!activePlan || button.disabled) return;
    let value = {};
    if (approved) {
      try {
        value = actionResolutionValue();
      } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
        global.showToast?.(error.message || "请先完成审核选择", "error");
        return;
      }
    }
    button.disabled = true;
    try {
      const result = await api.requestJson(`/api/agent/plans/${encodeURIComponent(activePlan.id)}/actions/resolve`, {
        method: "POST", body: { approved, value },
      });
      renderPlan(result.plan);
      global.ClipTalkRefreshCurrentJob?.();
      if (approved) pollTimer = global.setTimeout(refreshPlan, 700);
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      button.disabled = false;
      global.showToast?.(error.message || "确认操作失败", "error");
    }
  }

  async function confirmCoverTimelineSelection({ variantId, contentHash = "" } = {}) {
    const step = planProgress(activePlan).current;
    const job = global.ClipTalkCurrentJobSnapshot?.();
    if (!activePlan || String(activePlan.status || "") !== "action_required" || String(step?.tool || "") !== "review_cover_variants") {
      throw new Error("当前计划不在封面审核步骤");
    }
    const variant = (job?.coverDraft?.variants || []).find((item) => String(item?.variantId || "") === String(variantId || ""));
    if (!job?.id || !step?.id || !variant) throw new Error("封面草稿与当前计划不匹配");
    const reviewError = coverVariantReviewError(activePlan, variant);
    if (reviewError) throw new Error(`${reviewError}，请修改要求并重新生成候选`);
    const value = {
      context: {
        jobId: String(job.id), stepId: String(step.id),
        jobRevision: Number(job.revision || 0), source: "cover_timeline",
      },
      selection: {
        kind: "cover_variant", variantIds: [String(variantId)],
        contentHash: String(contentHash || variant.contentHash || ""),
      },
    };
    const result = await api.requestJson(`/api/agent/plans/${encodeURIComponent(activePlan.id)}/actions/resolve`, {
      method: "POST", body: { approved: true, value },
    });
    renderPlan(result.plan);
    global.ClipTalkRefreshCurrentJob?.();
    clearTimeout(pollTimer);
    pollTimer = global.setTimeout(refreshPlan, 700);
    return result.plan;
  }

  global.ClipTalkConfirmCoverTimelineSelection = confirmCoverTimelineSelection;

  async function openTimelineAction(event) {
    const button = event.currentTarget;
    const step = planProgress(activePlan).current;
    const result = step?.result && typeof step.result === "object" ? step.result : {};
    if (!step || !["propose_timeline_edit", "confirm_timeline_edit", "prepare_subtitle_review"].includes(step.tool) || button.disabled) return;
    if (!result.sessionId) {
      if (step.tool !== "propose_timeline_edit") {
        global.showToast?.("Agent 尚未生成可审核时间线；请确认素材分析已完成后重试当前步骤", "error");
        return;
      }
      button.disabled = true;
      button.textContent = "正在生成…";
      try {
        const retried = await api.requestJson(`/api/agent/plans/${encodeURIComponent(activePlan.id)}/actions/retry`, {
          method: "POST",
        });
        renderPlan(retried.plan);
        global.ClipTalkRefreshCurrentJob?.();
        pollTimer = global.setTimeout(refreshPlan, 700);
        global.showToast?.("正在从高光候选重新生成待审核时间线", "success");
      } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
        button.disabled = false;
        button.textContent = "重新生成草案";
        global.showToast?.(error.message || "无法重新生成时间线草案", "error");
      }
      return;
    }
    const subtitleReview = step.tool === "prepare_subtitle_review";
    if (subtitleReview && typeof global.ClipTalkOpenAgentSubtitleReview !== "function") {
      global.showToast?.("字幕校对工具尚未加载，请刷新页面后重试", "error");
      return;
    }
    if (!subtitleReview && typeof global.ClipTalkOpenAgentTimeline !== "function") {
      global.showToast?.("精剪时间线尚未加载，请刷新页面后重试", "error");
      return;
    }
    button.disabled = true;
    button.textContent = "正在打开…";
    try {
      const opened = subtitleReview
        ? await global.ClipTalkOpenAgentSubtitleReview({ sessionId: String(result.sessionId) })
        : await global.ClipTalkOpenAgentTimeline({
          sessionId: String(result.sessionId),
          instruction: step.tool === "propose_timeline_edit" ? String(step.arguments?.instruction || "") : "",
          variantCount: Number(step.arguments?.variantCount || 1),
          reviewPendingProposal: step.tool === "confirm_timeline_edit",
        });
      if (!opened) throw new Error(subtitleReview ? "字幕校对没有完成" : "精剪时间线没有打开，请刷新当前任务后重试");
      if (subtitleReview) closePlanDrawer();
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      global.showToast?.(error.message || "无法打开精剪时间线", "error");
    } finally {
      button.disabled = false;
      button.textContent = step.tool === "confirm_timeline_edit" ? "打开并审核草案"
        : subtitleReview ? "生成并校对字幕" : "打开精剪时间线";
    }
  }

  function actionResolutionValue() {
    const step = planProgress(activePlan).current;
    const job = global.ClipTalkCurrentJobSnapshot?.();
    if (!step?.id || !job?.id) throw new Error("请先打开此计划关联的素材任务");
    const context = {
      jobId: String(job.id), stepId: String(step.id),
      jobRevision: Number(job.revision || 0), source: "review_panel",
    };
    if (step.tool === "select_people") {
      const target = job.request?.contentSearchPersonTarget || job.contentSearchPersonTarget || job.contentSearch?.intent?.personTarget || {};
      const personIds = Array.isArray(target.personIds) ? target.personIds.map(String).filter(Boolean) : [];
      if (!personIds.length) throw new Error("请先在人物面板选择要保留的人物，再继续此计划");
      return { context, selection: { kind: "people", personIds } };
    }
    if (step.tool === "select_speakers") {
      const speakerRefs = [
        ...(job.contentSearch?.selectedSpeakerRefs || []),
        ...(job.contentSearch?.intent?.speakerRefs || []),
      ].map(String).filter(Boolean);
      if (!speakerRefs.length) throw new Error("请先在说话人面板选择要保留的声音，再继续此计划");
      return { context, selection: { kind: "speakers", speakerRefs } };
    }
    if (step.tool === "review_content_evidence" || step.result?.action === "content_evidence_review") {
      const search = job.contentSearch || {};
      const draft = search.reviewDraft?.searchId === search.id ? search.reviewDraft : {};
      const matchIds = (draft.orderedMatchIds || draft.selectedMatchIds || search.confirmedMatchIds || search.defaultSelectedIds || [])
        .map(String).filter(Boolean);
      if (!search.id || !matchIds.length) {
        throw new Error("请先在内容候选面板勾选并保存要用于组合的片段，再继续此计划");
      }
      return { context, selection: { kind: "content_evidence", searchId: String(search.id), matchIds } };
    }
    if (step.tool === "propose_timeline_edit") {
      const result = step.result && typeof step.result === "object" ? step.result : {};
      const sessionId = String(result.sessionId || job.activeEditSessionId || "");
      const session = (job.editSessions || []).find((item) => String(item?.id || "") === sessionId);
      const proposalId = String(result.proposalId || session?.pendingProposal?.id || "");
      if (
        !sessionId || !session || !proposalId
        || String(session.pendingProposal?.id || "") !== proposalId
        || String(session.pendingProposal?.status || "") !== "pending"
      ) {
        throw new Error("请先在精剪时间线生成待审核的时间线草案，再继续 Agent 计划");
      }
      return { context, selection: { kind: "timeline_proposal", editSessionId: sessionId, proposalId } };
    }
    if (step.tool === "confirm_timeline_edit") {
      const result = step.result && typeof step.result === "object" ? step.result : {};
      const sessionId = String(result.sessionId || job.activeEditSessionId || "");
      const session = (job.editSessions || []).find((item) => String(item?.id || "") === sessionId);
      const revision = Number(session?.revision || 0);
      if (!sessionId || !session || !Number.isInteger(revision) || revision < 1 || session.pendingProposal) {
        throw new Error("请先在精剪时间线应用并保存审核后的草案，再继续 Agent 计划");
      }
      return { context, selection: { kind: "timeline_confirmation", editSessionId: sessionId, revision } };
    }
    if (step.tool === "prepare_subtitle_review") {
      const sessionId = String(job.activeEditSessionId || "");
      const session = (job.editSessions || []).find((item) => String(item?.id || "") === sessionId);
      const subtitleDraftId = String(session?.subtitleDraftId || "");
      if (!sessionId || !session || !session.subtitleEnabled || !subtitleDraftId) {
        throw new Error("请先在精剪时间线建立并确认字幕草稿，再继续此计划");
      }
      return { context, selection: { kind: "subtitle_review", editSessionId: sessionId, subtitleDraftId } };
    }
    if (step.tool === "review_cover_variants") {
      const variantId = String(job.coverTimelineDraft?.activeVariantId || job.coverDraft?.selectedVariantId || "");
      const variant = (job.coverDraft?.variants || []).find((item) => String(item?.variantId || "") === variantId);
      if (!variantId || !variant) throw new Error("请先在封面时间轴中选择一个封面草稿");
      const reviewError = coverVariantReviewError(activePlan, variant);
      if (reviewError) throw new Error(`${reviewError}，请修改要求并重新生成候选`);
      return {
        context,
        selection: {
          kind: "cover_variant", variantIds: [variantId],
          contentHash: String(variant.contentHash || ""),
        },
      };
    }
    return { context, review: { kind: "review", revision: Number(job.revision || 0) } };
  }

  async function submitGoal(text, options = {}) {
    const context = owner();
    const streamController = new AbortController();
    pendingRequests.add(streamController);
    const goal = String(text || "").trim();
    const visibleGoal = String(options.visibleGoal || goal).trim();
    const capturedContext = JSON.parse(JSON.stringify(options.uiContext || global.ClipTalkCollectAssistantContext?.() || {}));
    const isConfirmation = /^(?:可以|好的?|继续|确认|开始|ok|yes)[。！!\s]*$/i.test(goal);
    let confirmationValue = null;
    if (isConfirmation && activePlan) {
      capturedContext.confirmationHash = activePlan.planHash;
      if (activePlan.status === "action_required") {
        try { confirmationValue = actionResolutionValue(); } catch (_) { /* Server will ask for the missing review. */ }
      }
    }
    if (!goal) {
      global.showToast?.("请描述你想得到的剪辑结果");
      pendingRequests.delete(streamController);
      return true;
    }
    const input = $("#chatInput");
    const send = $("#sendButton");
    if (input) {
      // A submitted instruction belongs to the conversation immediately. Do
      // not leave a disabled copy in the composer for the whole planning
      // request, which can take several seconds and makes the send action look
      // as though it did not happen. Restore it only when planning fails so
      // the user can retry without retyping.
      input.value = "";
      input.disabled = true;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (send) send.disabled = true;
    appendMessage("user", visibleGoal, "agent-goal");
    const planningMessage = appendMessage("assistant", "正在核对你的意思和引用范围；询问不会修改视频，剪辑方案确认后才执行。", "agent-planning");
    const planningTrace = createPlanningTrace(visibleGoal);
    const updatePlanningMessage = (text) => planningMessage?.querySelector("p")?.replaceChildren(text);
    try {
      const workspace = await ensureWorkspace();
      const skillId = String(options.skillId ?? $("#agentSkillSelect")?.value ?? "") || null;
      const executionMode = String(options.executionMode ?? $("#agentExecutionMode")?.value ?? "autonomous_review");
      const uiContext = capturedContext;
      const signature = JSON.stringify({ goal, uiContext, workspaceId: workspace.id });
      const clientMessageId = retrySubmission?.signature === signature ? retrySubmission.id : (global.crypto?.randomUUID?.() || `message_${Date.now()}_${Math.random().toString(36).slice(2)}`);
      retrySubmission = { signature, id: clientMessageId };
      const response = await api.requestResponse(`/api/agent/workspaces/${encodeURIComponent(workspace.id)}/messages/stream`, {
        method: "POST",
        signal: streamController.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: goal, skillId, executionMode, clientMessageId, uiContext, replyToActionId: activePlan?.id || null, ...(confirmationValue ? { confirmationValue } : {}) }),
      });
      if (!response.ok) throw await api.createResponseError(response);
      // prepare_plan_request() has already reserved planning on the server
      // before the streaming response starts. Refresh the shared task state
      // immediately, rather than waiting for the plan to finish.
      global.ClipTalkRefreshCurrentJob?.();
      const reader = response.body?.getReader();
      if (!reader) throw new Error("浏览器不支持 Agent 流式响应");
      const decoder = new TextDecoder();
      let buffer = "";
      let result = null;
      while (true) {
        const chunk = await reader.read();
        if (!ownsView(context)) { await reader.cancel(); return false; }
        buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
        const records = buffer.split("\n\n");
        buffer = records.pop() || "";
        for (const record of records) {
          const eventName = record.split("\n").find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
          const dataText = record.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
          if (!dataText) continue;
          const value = JSON.parse(dataText);
          if (eventName === "plan") {
            planningTrace.advance("plan_ready");
            result = value;
          }
          else if (eventName === "assistant.result") result = value;
          else if (eventName === "error") throw new Error(value.message || "Agent 规划失败");
          else if (eventName === "planning.progress") {
            planningTrace.advance(value.phase, value.detail, value.title);
            updatePlanningMessage(value.title || "正在生成执行计划…");
          }
          else if (eventName === "message.text_delta") {
            planningTrace.advance("decomposing_goal", "正在把目标整理成可确认的剪辑步骤。");
            updatePlanningMessage("正在按主题组织剪辑结构…");
          } else if (eventName === "message.toolcall" || eventName === "tool.started") {
            planningTrace.advance("validating_plan", "正在校验计划步骤、工具和人工确认点。");
            updatePlanningMessage("正在检查可用工具与步骤依赖…");
          } else if (eventName === "tool.completed") {
            planningTrace.advance("validating_plan", "计划校验完成，正在提交待确认的步骤。");
            updatePlanningMessage("已完成计划校验，正在整理可确认的执行步骤…");
          } else if (eventName === "message.thinking") {
            planningTrace.advance("decomposing_goal");
            updatePlanningMessage("正在拆解目标、素材范围与确认点…");
          }
        }
        if (chunk.done) break;
      }
      if (!result?.action && !result?.plan) throw new Error("响应中断，请重试；相同消息不会重复创建计划");
      if (input) input.value = "";
      if (!ownsView(context)) return false;
      if (result.plan) {
        renderPlan(result.plan);
        if (["running", "approved"].includes(result.plan.status)) {
          clearTimeout(pollTimer);
          pollTimer = global.setTimeout(refreshPlan, 700);
        }
      }
      updatePlanningMessage(result.message || result.warning || "计划已准备好。请确认范围后开始执行。");
      planningMessage.dataset.kind = "agent-plan-ready";
      retrySubmission = null;
      if (result.retryable && input) input.value = visibleGoal;
      try {
        await refreshConversation();
      } catch (error) {
        if (error.name === "StaleWorkspaceError") return false;
        global.showToast?.("本条要求已保存，对话记录暂未刷新。可稍后重新打开任务。", "warning");
      }
    } catch (error) {
      if (!ownsView(context) || error.name === "StaleWorkspaceError") return false;
      if (input && !input.value) {
        input.value = visibleGoal;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      appendMessage("assistant", error.message || "Agent 规划失败。", "agent-error");
      global.showToast?.(error.message || "Agent 规划失败", "error");
      return false;
    } finally {
      pendingRequests.delete(streamController);
      if (ownsView(context)) {
        if (input) input.disabled = false;
        if (send) send.disabled = false;
        input?.focus();
      }
    }
    return true;
  }

  async function loadSkills() {
    const selects = [...document.querySelectorAll("#agentSkillSelect, #briefAgentSkillSelect")];
    if (!selects.length) return;
    try {
      const result = await api.requestJson("/api/agent/skills");
      const enabled = (result.skills || []).filter((skill) => skill.status === "enabled");
      const options = `<option value="">自动选择</option>${enabled.map((skill) => `<option value="${escapeHtml(skill.id)}">${escapeHtml(skillOptionLabel(skill))}</option>`).join("")}`;
      selects.forEach((select) => {
        const previous = select.value;
        select.innerHTML = options;
        if ([...select.options].some((item) => item.value === previous)) select.value = previous;
      });
      syncSkillMenuLabel();
    } catch {
      selects.forEach((select) => { select.innerHTML = '<option value="">Skill 服务不可用</option>'; });
    }
  }

  function syncSkillMenuLabel() {
    const select = $("#agentSkillSelect");
    const button = $("#agentSkillMenuButton");
    if (!select || !button) return;
    const label = "执行设置";
    const meta = select.value ? "已指定" : "自动";
    button.innerHTML = `<span>${escapeHtml(label)}</span><small>${escapeHtml(meta)}</small>`;
    button.title = select.value
      ? `Skill：${String(select.selectedOptions?.[0]?.textContent || "已指定").trim()}`
      : "自动选择 Skill 和执行方式；点击调整";
  }

  function closeSkillMenu() {
    $("#agentSkillMenu")?.classList.add("hidden");
    $("#agentSkillMenuButton")?.setAttribute("aria-expanded", "false");
  }

  function toggleSkillMenu() {
    const menu = $("#agentSkillMenu");
    const button = $("#agentSkillMenuButton");
    if (!menu || !button) return;
    const opening = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !opening);
    button.setAttribute("aria-expanded", String(opening));
    if (opening) menu.querySelector("select")?.focus();
  }

  function selectedAgentProvider() {
    return agentProviders.find((item) => item.id === $("#agentProvider")?.value) || null;
  }

  function renderAgentModels(selected = "") {
    const select = $("#agentModel");
    if (!select) return;
    const models = [...discoveredAgentModels];
    if (selected && !models.some((item) => item.id === selected)) models.unshift({ id: selected });
    select.innerHTML = `<option value="">选择模型</option>${models.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === selected ? "selected" : ""}>${escapeHtml(item.id)}</option>`).join("")}`;
  }

  let agentSettingsBaseline = null;
  let agentSettingsBusy = false;
  let effectiveAgentModel = null;
  let effectiveProbeBusy = false;
  let effectiveProbeResult = null;
  let effectiveRefreshSequence = 0;
  const effectiveIdentity = model => JSON.stringify([model?.source, model?.provider, model?.name, model?.configured]);
  function modelSettingsDirty() {
    return Boolean(document.querySelector('#settingsPanel form[data-dirty="true"]'));
  }
  function renderEffectiveAgent() {
    const model = effectiveAgentModel;
    const configured = Boolean(model?.configured);
    const dirty = modelSettingsDirty();
    const ready = global.ClipTalkSetupStatus?.steps?.find(step => step.id === "agent")?.status === "ready";
    const result = effectiveProbeResult?.identity === effectiveIdentity(model) ? effectiveProbeResult : null;
    const passed = ready && result?.passed !== false;
    const status = effectiveProbeBusy ? "正在测试工具调用…" : result?.error || (passed ? "工具调用测试已通过" : configured ? "模型已配置，尚未通过工具调用测试" : "请先配置剪辑规划模型，或展开下方独立模型配置");
    if ($("#agentEffectiveModel")) $("#agentEffectiveModel").textContent = model
      ? `${model.source === "llm_fallback" ? "复用剪辑规划模型" : configured ? "使用独立模型" : "未配置模型"}${model.name ? ` · ${model.name}` : ""}` : "暂时无法读取当前模型，请重新检查";
    if ($("#agentEffectiveStatus")) $("#agentEffectiveStatus").textContent = status;
    if ($("#agentSettingsState")) $("#agentSettingsState").textContent = effectiveProbeBusy ? "正在测试" : configured ? `${model.source === "llm_fallback" ? "复用模型" : "独立模型"} · ${passed ? "已通过测试" : "待测试"}` : "需要配置";
    if ($("#agentEffectiveHint")) $("#agentEffectiveHint").textContent = dirty
      ? "存在未保存的模型配置。请先保存或放弃修改，再测试当前生效模型。"
      : "测试会调用当前已保存的模型，可能产生少量服务商费用；不会修改配置或开始剪辑。";
    for (const id of ["#testEffectiveAgent", "#probeEffectiveAgent"]) {
      const button = $(id);
      if (!button) continue;
      button.classList.remove("hidden");
      button.disabled = effectiveProbeBusy || agentSettingsBusy || dirty || !configured;
      button.textContent = effectiveProbeBusy ? "正在测试工具调用…" : passed ? "重新测试工具调用" : "测试工具调用";
      button.title = dirty ? "请先保存或放弃模型配置修改" : "测试当前生效模型的工具调用能力，不更改配置";
    }
  }
  async function refreshEffectiveAgent() {
    const sequence = ++effectiveRefreshSequence;
    try {
      const health = await api.requestJson("/api/agent/health");
      if (sequence !== effectiveRefreshSequence) return;
      const model = health?.model || null;
      if (effectiveIdentity(model) !== effectiveIdentity(effectiveAgentModel)) effectiveProbeResult = null;
      effectiveAgentModel = model;
    } catch {
      if (sequence !== effectiveRefreshSequence) return;
      effectiveAgentModel = null;
      effectiveProbeResult = null;
    }
    renderEffectiveAgent();
  }
  async function probeEffectiveAgent() {
    if (effectiveProbeBusy || agentSettingsBusy) return;
    if (modelSettingsDirty()) return void global.showToast?.("请先保存或放弃模型配置修改，再测试当前生效模型");
    if (!effectiveAgentModel?.configured) return void global.showToast?.("请先配置可用的剪辑规划模型或独立 Agent 模型");
    effectiveProbeBusy = true;
    effectiveProbeResult = null;
    renderEffectiveAgent();
    const identity = effectiveIdentity(effectiveAgentModel);
    try {
      const result = await api.requestJson("/api/settings/agent/probe-effective", { method: "POST" });
      if (result?.toolCalling !== true) throw new Error("模型未通过工具调用测试");
      const readiness = await global.refreshSetupReadiness?.();
      await refreshEffectiveAgent();
      if (identity !== effectiveIdentity(effectiveAgentModel)) throw new Error("生效模型已变化，请重新测试当前模型");
      if (readiness?.steps?.find(step => step.id === "agent")?.status !== "ready") throw new Error("测试已返回，但当前模型的验证状态尚未确认，请重新检查");
      effectiveProbeResult = { identity, passed: true };
      global.showToast?.("当前模型已通过工具调用测试", "success");
    } catch (error) {
      await global.refreshSetupReadiness?.();
      effectiveProbeResult = { identity, passed: false, error: error.message || "工具调用测试失败，请重试" };
      global.showToast?.(effectiveProbeResult.error, "error");
      global.setModelSettingsRole?.("agent");
    } finally {
      effectiveProbeBusy = false;
      renderEffectiveAgent();
    }
  }
  function agentSettingsSignature() {
    const { verifiedAt: _verifiedAt, ...payload } = agentSettingsPayload();
    return JSON.stringify(payload);
  }
  function syncAgentSettingsDirty() {
    const dirty = agentSettingsBaseline !== null && agentSettingsSignature() !== agentSettingsBaseline;
    const form = $("#agentSettingsForm");
    if (form) form.dataset.dirty = String(dirty);
    form?.querySelector(".settings-save-bar")?.classList.toggle("hidden", !dirty && !agentSettingsBusy);
    if ($("#agentDirtyState")) $("#agentDirtyState").textContent = agentSettingsBusy ? "正在验证并保存" : dirty ? "有未保存修改" : "所有修改已保存";
    if ($("#saveAgentSettings")) $("#saveAgentSettings").disabled = agentSettingsBusy || !dirty;
    if ($("#discardAgentSettings")) $("#discardAgentSettings").disabled = agentSettingsBusy || !dirty;
    renderEffectiveAgent();
  }
  async function loadAgentSettings() {
    const form = $("#agentSettingsForm");
    if (!form || agentSettingsBusy || form.dataset.dirty === "true") return;
    if (agentSettingsBaseline === null) agentSettingsBaseline = agentSettingsSignature();
    try {
      const [state, health] = await Promise.all([
        api.requestJson("/api/settings/agent"),
        api.requestJson("/api/agent/health").catch(() => ({})),
      ]);
      if (form.dataset.dirty === "true" || agentSettingsBusy) return;
      agentProviders = state.providers || [];
      const provider = agentProviders.find((item) => item.active) || agentProviders[0];
      const providerSelect = $("#agentProvider");
      providerSelect.innerHTML = agentProviders.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === provider?.id ? "selected" : ""}>${escapeHtml(item.label || item.id)}</option>`).join("");
      $("#agentBaseUrl").value = provider?.baseUrl || "";
      $("#agentThinkingType").value = provider?.thinkingType || "enabled";
      const fallbackModel = health?.model?.source === "llm_fallback" ? health.model : null;
      effectiveAgentModel = health?.model || null;
      const independent = $("#agentIndependentSettings");
      if (independent) independent.open = !fallbackModel;
      $("#agentKeyHint").textContent = provider?.keyConfigured
        ? `已保存：${provider.keyHint}`
        : fallbackModel ? `未单独配置；当前复用文本模型 ${fallbackModel.name}` : "尚未保存密钥";
      discoveredAgentModels = provider?.models || [];
      renderAgentModels(provider?.model || "");
      $("#agentSettingsState").textContent = provider?.configured
        ? "已配置" : fallbackModel ? "复用文本模型" : "需要配置";
      $("#agentApiKey").value = "";
      agentSettingsBaseline = agentSettingsSignature();
      syncAgentSettingsDirty();
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      $("#agentSettingsState").textContent = error.message || "读取失败";
    }
  }

  function agentSettingsPayload() {
    return {
      provider: String($("#agentProvider")?.value || ""),
      apiKey: String($("#agentApiKey")?.value || ""),
      model: String($("#agentModel")?.value || ""),
      baseUrl: String($("#agentBaseUrl")?.value || ""),
      thinkingType: String($("#agentThinkingType")?.value || "enabled"),
      models: discoveredAgentModels,
      verifiedAt: new Date().toISOString(),
    };
  }

  async function discoverAgentModels(event) {
    const button = event.currentTarget;
    button.disabled = true;
    $("#agentProbeStatus").textContent = "正在读取模型…";
    try {
      const payload = agentSettingsPayload();
      const signature = agentSettingsSignature();
      const result = await api.requestJson("/api/settings/agent/discover", {
        method: "POST", body: { provider: payload.provider, apiKey: payload.apiKey, baseUrl: payload.baseUrl },
      });
      if (agentSettingsSignature() !== signature) return void global.showToast?.("连接配置已改变，请重新读取模型");
      discoveredAgentModels = result.models || [];
      renderAgentModels(discoveredAgentModels[0]?.id || "");
      syncAgentSettingsDirty();
      $("#agentProbeStatus").textContent = `已读取 ${discoveredAgentModels.length} 个模型；尚未测试工具调用`;
      $("#agentKeyHint").textContent = result.keyHint || "连接成功，模型列表已读取";
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      $("#agentProbeStatus").textContent = error.message || "连接失败";
    } finally {
      button.disabled = false;
    }
  }

  async function saveAgentSettings(event) {
    event.preventDefault();
    if (agentSettingsBusy || effectiveProbeBusy) return;
    const button = $("#saveAgentSettings");
    const payload = agentSettingsPayload();
    if (!payload.provider || !payload.model || !payload.baseUrl) return void global.showToast?.("请先完成 Agent 连接和模型选择");
    agentSettingsBusy = true;
    syncAgentSettingsDirty();
    $("#agentSettingsForm").querySelectorAll("input, select, button").forEach(node => { node.disabled = true; });
    button.disabled = true;
    button.textContent = "正在执行 Tool Calling 探测…";
    $("#agentProbeStatus").textContent = "Pi 正在要求模型调用探测工具";
    try {
      const probe = await api.requestJson("/api/settings/agent/probe", { method: "POST", body: payload });
      if (!probe.toolCalling) throw new Error("模型未通过 Tool Calling 探测");
      await api.requestJson("/api/settings/agent", { method: "POST", body: payload });
      $("#agentApiKey").value = "";
      $("#agentProbeStatus").textContent = `Tool Calling 已通过 · Pi ${probe.piVersion}`;
      $("#agentSettingsState").textContent = "已验证并保存";
      agentSettingsBaseline = agentSettingsSignature();
      global.showToast?.("Agent 模型已验证并保存", "success");
      effectiveProbeResult = null;
      await global.refreshSetupReadiness?.();
      await refreshEffectiveAgent();
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      $("#agentProbeStatus").textContent = error.message || "探测失败";
      global.showToast?.(error.message || "Agent 模型探测失败", "error");
    } finally {
      agentSettingsBusy = false;
      $("#agentSettingsForm").querySelectorAll("input, select, button").forEach(node => { node.disabled = false; });
      button.textContent = "验证并保存更改";
      syncAgentSettingsDirty();
    }
  }

  function registrySkillMarkup(skill) {
    const canEnable = ["draft", "validated", "disabled"].includes(skill.status);
    return `<article class="agent-registry-item"><header><div><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.version)} · ${escapeHtml(skill.source)}</small></div><b>${escapeHtml(skill.status)}</b></header><p>${escapeHtml(skill.description)}</p><footer>${canEnable ? `<button type="button" data-enable-skill="${escapeHtml(skill.id)}" data-skill-hash="${escapeHtml(skill.contentHash)}">审核并启用</button>` : `<button type="button" data-disable-skill="${escapeHtml(skill.id)}">禁用</button>`}</footer></article>`;
  }

  function registryPluginMarkup(plugin) {
    const activation = `<label class="agent-plugin-trust"><input type="checkbox" data-trust-plugin="${escapeHtml(plugin.id)}"><span>我已审核来源，理解此 Plugin 拥有宿主权限并信任它</span></label><button class="danger" type="button" data-activate-plugin="${escapeHtml(plugin.id)}" data-plugin-hash="${escapeHtml(plugin.contentHash)}" disabled>启用 Plugin</button>`;
    return `<article class="agent-registry-item plugin"><header><div><strong>${escapeHtml(plugin.id)}</strong><small>${escapeHtml(plugin.version || "未标版本")} · ${escapeHtml(plugin.source)}</small></div><b>${escapeHtml(plugin.status)}</b></header><p>${escapeHtml(plugin.warning || "受信任 Plugin 在 Agent 进程内运行。")}</p><small>工具：${escapeHtml((plugin.tools || []).map((tool) => tool.name).join("、") || "无")}</small><footer>${plugin.status === "enabled" ? `<button type="button" data-disable-plugin="${escapeHtml(plugin.id)}">禁用</button>` : activation}</footer></article>`;
  }

  async function renderRegistry() {
    const root = $("#agentRegistryContent");
    if (!root) return;
    root.innerHTML = '<p class="agent-registry-loading">正在读取能力目录…</p>';
    try {
      if (registryTab === "skills") {
        const result = await api.requestJson("/api/agent/skills");
        root.innerHTML = `<section class="agent-registry-create"><label><span>用自然语言生成 Skill 草稿</span><textarea id="agentSkillPrompt" rows="3" placeholder="例如：把课程视频按知识点分章，保留完整解释并生成字幕预览"></textarea></label><button type="button" data-generate-skill>生成并模拟规划</button><label class="agent-package-upload"><span>安装标准 Skill ZIP</span><input type="file" accept=".zip" data-upload-skill></label></section><div class="agent-registry-list">${(result.skills || []).map(registrySkillMarkup).join("")}</div>`;
      } else {
        const result = await api.requestJson("/api/agent/plugins");
        root.innerHTML = `<aside class="agent-plugin-warning"><strong>Plugin 是受信任代码</strong><p>启用后可访问 Agent 进程的宿主权限。只安装你已审核且信任的包。</p></aside><label class="agent-package-upload"><span>检查 Plugin ZIP</span><input type="file" accept=".zip" data-upload-plugin></label><div class="agent-registry-list">${(result.plugins || []).map(registryPluginMarkup).join("")}</div>`;
      }
      bindRegistryActions(root);
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      root.innerHTML = `<p class="agent-registry-error">${escapeHtml(error.message || "能力目录读取失败")}</p>`;
    }
  }

  async function uploadPackage(input, endpoint) {
    const file = input.files?.[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    input.disabled = true;
    try {
      const response = await api.request(endpoint, { method: "POST", body });
      if (!response.ok) throw await api.createResponseError(response);
      await renderRegistry();
      await loadSkills();
    } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
      global.showToast?.(error.message || "包上传失败", "error");
      input.disabled = false;
    }
  }

  function bindRegistryActions(root) {
    root.querySelector("[data-generate-skill]")?.addEventListener("click", async (event) => {
      const request = String($("#agentSkillPrompt")?.value || "").trim();
      if (request.length < 10) return void global.showToast?.("请更具体地描述 Skill 的任务与输出");
      event.currentTarget.disabled = true;
      event.currentTarget.textContent = "生成与模拟中…";
      try {
        await api.requestJson("/api/agent/skills/generate", { method: "POST", body: { request } });
        await renderRegistry();
      } catch (error) {
      if (error.name === "StaleWorkspaceError") return;
        event.currentTarget.disabled = false;
        event.currentTarget.textContent = "生成并模拟规划";
        global.showToast?.(error.message || "Skill 生成失败", "error");
      }
    });
    root.querySelector("[data-upload-skill]")?.addEventListener("change", (event) => uploadPackage(event.currentTarget, "/api/agent/skills/install"));
    root.querySelector("[data-upload-plugin]")?.addEventListener("change", (event) => uploadPackage(event.currentTarget, "/api/agent/plugins/inspect"));
    root.querySelectorAll("[data-enable-skill]").forEach((button) => button.addEventListener("click", async () => {
      await api.requestJson(`/api/agent/skills/${encodeURIComponent(button.dataset.enableSkill)}/enable`, { method: "POST", body: { contentHash: button.dataset.skillHash } });
      await renderRegistry();
      await loadSkills();
    }));
    root.querySelectorAll("[data-disable-skill]").forEach((button) => button.addEventListener("click", async () => {
      await api.requestJson(`/api/agent/skills/${encodeURIComponent(button.dataset.disableSkill)}/disable`, { method: "POST" });
      await renderRegistry();
      await loadSkills();
    }));
    root.querySelectorAll("[data-trust-plugin]").forEach((checkbox) => checkbox.addEventListener("change", () => {
      const button = root.querySelector(`[data-activate-plugin="${CSS.escape(checkbox.dataset.trustPlugin)}"]`);
      if (button) button.disabled = !checkbox.checked;
    }));
    root.querySelectorAll("[data-activate-plugin]").forEach((button) => button.addEventListener("click", async () => {
      const checkbox = root.querySelector(`[data-trust-plugin="${CSS.escape(button.dataset.activatePlugin)}"]`);
      if (!checkbox?.checked) return;
      await api.requestJson(`/api/agent/plugins/${encodeURIComponent(button.dataset.activatePlugin)}/activate`, { method: "POST", body: { contentHash: button.dataset.pluginHash, trusted: true } });
      await renderRegistry();
    }));
    root.querySelectorAll("[data-disable-plugin]").forEach((button) => button.addEventListener("click", async () => {
      await api.requestJson(`/api/agent/plugins/${encodeURIComponent(button.dataset.disablePlugin)}/disable`, { method: "POST" });
      await renderRegistry();
    }));
  }

  function openRegistry() {
    const dialog = $("#agentRegistryDialog");
    if (!dialog) return;
    dialog.showModal();
    renderRegistry();
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensurePlanDrawerPortal();
    $("#agentRegistryButton")?.addEventListener("click", openRegistry);
    $("#agentSkillMenuButton")?.addEventListener("click", toggleSkillMenu);
    $("#agentSkillSelect")?.addEventListener("change", () => { syncSkillMenuLabel(); closeSkillMenu(); });
    $("#agentPlanDrawerClose")?.addEventListener("click", closePlanDrawer);
    $("#agentPlanDrawerScrim")?.addEventListener("click", closePlanDrawer);
    document.querySelectorAll("[data-agent-drawer-tab]").forEach((button) => button.addEventListener("click", () => setPlanDrawerTab(button.dataset.agentDrawerTab)));
    $("#agentPlanDrawer")?.addEventListener("keydown", (event) => {
      if (event.key === "Escape") return void closePlanDrawer();
      if (event.key !== "Tab") return;
      const focusable = [...event.currentTarget.querySelectorAll("button:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex='-1'])")].filter((node) => !node.closest(".hidden") && !node.hidden);
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".agent-skill-row")) closeSkillMenu();
    });
    document.querySelectorAll("[data-agent-registry-tab]").forEach((button) => button.addEventListener("click", () => {
      registryTab = button.dataset.agentRegistryTab;
      document.querySelectorAll("[data-agent-registry-tab]").forEach((item) => item.classList.toggle("active", item === button));
      renderRegistry();
    }));
    loadSkills();
    loadAgentSettings();
    $("#settingsButton")?.addEventListener("click", loadAgentSettings);
    $("#testEffectiveAgent")?.addEventListener("click", probeEffectiveAgent);
    global.addEventListener("cliptalk:setup-status", () => {
      void refreshEffectiveAgent();
    });
    for (const event of ["input", "change"]) document.querySelector('#settingsPanel')?.addEventListener(event, () => queueMicrotask(renderEffectiveAgent));
    $("#discoverAgentModels")?.addEventListener("click", discoverAgentModels);
    $("#agentSettingsForm")?.addEventListener("submit", saveAgentSettings);
    $("#agentSettingsForm")?.addEventListener("input", syncAgentSettingsDirty);
    $("#agentSettingsForm")?.addEventListener("change", syncAgentSettingsDirty);
    $("#discardAgentSettings")?.addEventListener("click", () => {
      if (agentSettingsBusy || !agentSettingsBaseline) return;
      const saved = JSON.parse(agentSettingsBaseline);
      $("#agentProvider").value = saved.provider;
      $("#agentBaseUrl").value = saved.baseUrl;
      $("#agentApiKey").value = saved.apiKey;
      $("#agentThinkingType").value = saved.thinkingType;
      discoveredAgentModels = saved.models;
      renderAgentModels(saved.model);
      syncAgentSettingsDirty();
    });
    $("#agentProvider")?.addEventListener("change", () => {
      const provider = selectedAgentProvider();
      if (provider) {
        $("#agentBaseUrl").value = provider.baseUrl || "";
        discoveredAgentModels = provider.models || [];
        renderAgentModels(provider.model || "");
        $("#agentKeyHint").textContent = provider.keyConfigured ? `已保存：${provider.keyHint}` : "尚未保存密钥";
      }
    });
  });

  global.ClipTalkAgentWorkspace = Object.freeze({
    submitGoal, resumeForJob, loadSkills, openRegistry, reset, conversationMessages, previewPriority,
  });
  global.ClipTalkAgentSettings = Object.freeze({ probeEffectiveAgent, refreshEffectiveAgent, renderEffectiveAgent });
})(window);
