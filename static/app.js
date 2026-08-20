const $ = (selector) => {
  const node = document.querySelector(selector);
  return node || (selector === "#chatMessages" ? ensureChatMessages() : null);
};
const api = window.ClipTalkApi.request;
const apiBlob = window.ClipTalkApi.requestBlob;
function ensureChatMessages() {
  let root = document.querySelector("#chatMessages");
  if (root) return root;
  const panel = $(".chat-panel") || document.body;
  root = document.createElement("section");
  root.id = "chatMessages";
  root.className = "chat-messages";
  root.setAttribute("aria-live", "polite");
  panel.prepend(root);
  return root;
}
function syncThinkingOrbs(root = document) {
  if (!root) return;
  window.ThinkingOrbsBridge?.sync(root);
}
function syncGenerativeLoaders(root = document) {
  if (!root) return;
  try { window.GenerativeLoadersBridge?.sync(root); }
  catch (error) { console.warn("Generative loader sync skipped", error); }
}
function renderGenerativeLoader(element, options = {}) {
  if (!element) return false;
  try { return window.GenerativeLoadersBridge?.render(element, options) !== false; }
  catch (error) { console.warn("Generative loader render skipped", error); return false; }
}
function updateGenerativeLoader(element, options = {}) {
  if (!element) return false;
  try { return window.GenerativeLoadersBridge?.update(element, options) !== false; }
  catch (error) { console.warn("Generative loader update skipped", error); return false; }
}
function clearGenerativeLoader(element, options = {}) {
  if (!element) return;
  try { window.GenerativeLoadersBridge?.clear(element, options); }
  catch (error) { console.warn("Generative loader cleanup skipped", error); }
}
function syncBorderBeams(root = document) {
  if (!root) return;
  try { window.BorderBeamBridge?.sync(root); }
  catch (error) { console.warn("Border beam sync skipped", error); }
}
function updateBorderBeam(element, options = {}) {
  if (!element) return false;
  try { return window.BorderBeamBridge?.update(element, options) !== false; }
  catch (error) { console.warn("Border beam update skipped", error); return false; }
}
function clearBorderBeam(element) {
  if (!element) return;
  try { window.BorderBeamBridge?.clear(element); }
  catch (error) { console.warn("Border beam cleanup skipped", error); }
}
function setGenerativeInlineStatus(target, message = "", tone = "neutral", variant = "glyph") {
  const node = typeof target === "string" ? $(target) : target;
  if (!node) return;
  node.classList.add("generative-inline-status");
  let motion = node.querySelector(".generative-inline-motion");
  let label = node.querySelector(".generative-status-label");
  if (!motion || !label) {
    clearGenerativeLoader(motion);
    node.textContent = "";
    motion = document.createElement("span");
    motion.className = "generative-inline-motion hidden";
    motion.dataset.generativeLoader = "inline";
    motion.dataset.loaderSize = "15";
    label = document.createElement("b");
    label.className = "generative-status-label";
    node.append(motion, label);
  }
  label.textContent = message;
  node.dataset.tone = tone;
  node.classList.toggle("hidden", !message);
  const loading = tone === "loading" && Boolean(message);
  motion.dataset.loaderVariant = variant;
  motion.dataset.loaderLabel = message || "正在处理";
  motion.dataset.loaderActive = String(loading);
  motion.classList.toggle("hidden", !loading);
  if (loading) renderGenerativeLoader(motion, { kind: "inline", variant, size: 15, label: message });
  else clearGenerativeLoader(motion);
}
let toastTimer = null;
function showToast(message, tone = "error") {
  const region = $("#toastRegion");
  if (!region) return;
  clearTimeout(toastTimer);
  region.innerHTML = `<div class="toast ${tone}"><span>${escapeHtml(message)}</span><button type="button" aria-label="关闭提示">×</button></div>`;
  const toast = region.querySelector(".toast");
  toast.querySelector("button")?.addEventListener("click", () => { region.innerHTML = ""; });
  toastTimer = setTimeout(() => { region.innerHTML = ""; }, 5200);
}

function updateComposerBeam() {
  const shell = $(".chat-input-shell");
  const input = $("#chatInput");
  if (!shell || !input) return;
  const sending = shell.classList.contains("is-sending");
  const focused = document.activeElement === input;
  const hasText = Boolean(input.value.trim());
  const disabled = input.disabled;
  const sendButton = $("#sendButton");
  shell.classList.toggle("has-text", hasText);
  shell.classList.toggle("is-focused", focused);
  shell.classList.toggle("is-disabled", disabled);
  if (sendButton) sendButton.disabled = disabled || sending || actionBusy || !hasText;
  // The composer intentionally uses the full rotating bloom from the Border
  // Beam homepage. Output-version buttons keep the compact edge tracer so the
  // two interactions communicate different states.
  updateBorderBeam(shell, sending
    ? { size: "md", color: "ocean", strength: .96, duration: 1.35, brightness: 1.38, saturation: 1.15, hueRange: 30, active: true }
    : focused
      ? { size: "md", color: "ocean", strength: .86, duration: 1.9, brightness: 1.32, saturation: 1.1, hueRange: 28, active: true }
      : hasText
        ? { size: "md", color: "ocean", strength: .72, duration: 2.7, brightness: 1.24, saturation: 1.04, hueRange: 24, active: true }
        : { size: "md", color: "ocean", strength: disabled ? .32 : .56, duration: disabled ? 5.2 : 3.8, brightness: disabled ? 1.12 : 1.18, saturation: disabled ? .94 : 1, hueRange: disabled ? 20 : 22, active: true });
}

function setComposerSending(sending) {
  const shell = $(".chat-input-shell");
  if (!shell) return;
  shell.classList.toggle("is-sending", Boolean(sending));
  updateComposerBeam();
}

function outputBeamKey(jobId, node) {
  return `${String(jobId || "unknown")}:${String(node?.dataset.autoVersion || node?.dataset.autoOutput || "")}`;
}

function setOutputVersionBeamSelection(selectedNode = null) {
  document.querySelectorAll(".auto-version-button").forEach((node) => {
    const selected = node === selectedNode
      || (!selectedNode && currentOutput?.filename && node.dataset.autoOutput === currentOutput.filename);
    node.classList.toggle("beam-selected", Boolean(selected));
    // On compact buttons the package mask can fall back to a solid fill in
    // Chromium. Remove any stale mount and use the border-only CSS effect.
    clearBorderBeam(node);
  });
}

function clearOutputVersionSelectionState() {
  document.querySelectorAll(".auto-version-button").forEach((node) => {
    const arrivalTimer = borderBeamArrivalTimers.get(node);
    if (arrivalTimer) window.clearTimeout(arrivalTimer);
    borderBeamArrivalTimers.delete(node);
    node.classList.remove("active", "beam-selected", "beam-arriving");
    clearBorderBeam(node);
  });
}

function syncOutputVersionBeams(job = currentJob, root = document) {
  if (!job || !root) return;
  const nodes = [...root.querySelectorAll?.(".auto-version-button") || []];
  const jobId = String(job.id || "");
  const firstObservation = !borderBeamSeenOutputJobs.has(jobId);
  const newlyObserved = [];
  nodes.forEach((node) => {
    const key = outputBeamKey(jobId, node);
    const selected = currentOutput?.filename && node.dataset.autoOutput === currentOutput.filename;
    if (!borderBeamSeenOutputs.has(key)) {
      borderBeamSeenOutputs.add(key);
      if (!firstObservation) newlyObserved.push(node);
    }
    // Selection is derived from the media currently shown in the player.
    // Toggling instead of only adding prevents a source-preview switch from
    // leaving a stale output card highlighted after the conversation reruns.
    node.classList.toggle("active", Boolean(selected));
  });
  // A batch can expose several versions at the same moment. Highlight only
  // the newest one; animating every card at once looks like a rendering bug
  // and destroys the comparison labels.
  const arrivingNode = newlyObserved[newlyObserved.length - 1];
  if (arrivingNode) {
    arrivingNode.classList.add("beam-arriving");
    const previousTimer = borderBeamArrivalTimers.get(arrivingNode);
    if (previousTimer) window.clearTimeout(previousTimer);
    const timer = window.setTimeout(() => {
      if (!arrivingNode.isConnected) return;
      arrivingNode.classList.remove("beam-arriving");
      borderBeamArrivalTimers.delete(arrivingNode);
      setOutputVersionBeamSelection(arrivingNode.classList.contains("active") ? arrivingNode : null);
    }, 3200);
    borderBeamArrivalTimers.set(arrivingNode, timer);
  }
  borderBeamSeenOutputJobs.add(jobId);
  setOutputVersionBeamSelection(nodes.find((node) => node.classList.contains("active")) || null);
}
const uploadForm = $("#uploadForm");
const videoInput = $("#videoInput");
const chatForm = $("#chatForm");
const chatInput = $("#chatInput");
const mainVideo = $("#mainVideo");
const timelinePanel = $("#timelinePanel");
const timelineViewport = $("#timelineViewport");
const timelineTrackContent = $("#timelineTrackContent");
const waveformCanvas = $("#waveformCanvas");
const viewerShell = $("#viewerShell");
const mediaFrame = $("#mediaFrame");
const localPreviewPanel = $("#localPreviewPanel");
let currentJob = null;
let currentOutput = null;
let currentCandidate = null;
let currentEventGroup = null;
let currentEventSegment = null;
let pollTimer = null;
let elapsedTicker = null;
let pollFailureDelay = 2500;
let sourcePreviewPollTimer = null;
let localPreviewUrl = null;
let actionBusy = false;
let contentReviewDraftTimer = null;
let contentReviewDraftGeneration = 0;
let contentBasketSaveTimer = null;
let contentBasketSaveGeneration = 0;
let speakerConfirmationBusy = false;
const expandedContentSearchIds = new Set();
const contentSearchDetailCache = new Map();
const contentSearchFilterState = new Map();
const borderBeamSeenOutputJobs = new Set();
const borderBeamSeenOutputs = new Set();
const borderBeamArrivalTimers = new WeakMap();
let fragmentDownloadBusy = false;
let candidatePreviewEnd = null;
let candidatePreviewToken = 0;
let contentEvidenceRequestToken = 0;
let sourcePreviewRetryToken = 0;
let playbackRequestToken = 0;
let mainVideoAutoplayToken = 0;
let browserFallbackAttempts = new Set();
let viewerMediaKind = "source";
let waveformJobId = null;
let waveformData = null;
let waveformRequestToken = 0;
let waveformRetryAt = 0;
let timelineAssetsJobId = null;
let timelineAssetsLoadingJobId = null;
let timelineAssets = null;
let timelineAssetsRetryAt = 0;
let timelineTranscript = [];
let transcriptLoadingJobId = null;
let timelineTranscriptJobId = null;
let transcriptRetryAt = 0;
let timelineViewStart = 0;
let timelineViewEnd = 0;
let timelineCoordinateSpace = "output";
let timelineReviewFollow = false;
let timelineSnapEnabled = true;
let timelineFrame = null;
let boundaryDrag = null;
let timelineRangeDrag = null;
let timelinePanDrag = null;
let timelinePanFrame = null;
let timelineOverviewDrag = null;
let timelinePointerInside = false;
let timelineSpaceHeld = false;
let timelineSpaceDidPan = false;
let timelineSuppressClickUntil = 0;
let pendingTimelineSelection = null;
let pendingTimelineOriginal = null;
let timelineManualSelectMode = false;
let timelineVisualMode = "waveform";
let timelineCutsVisible = true;
let timelineSpeakerFilter = "all";
let timelineMediaRenderKey = "";
let waveformRenderKey = "";
let timelineResizeTimer = null;
let timelineResizeFrame = null;
let timelineLabelLayoutWidth = 0;
let timelineLabelLayoutHeight = 0;
let timelineFrameSelectionTime = null;
let mediaFitFrame = null;
let mediaLayoutObserver = null;
let outputAssemblyMode = "single_reel";
let pendingSegmentSelections = new Map();
let timelineChatSelections = [];
let eventGroupSelectionOrder = [];
let ignoredChatContextKeys = new Set();
let activeProposalSourceRange = null;
let autoPlanScope = "selected_only";
let autoAdvanceCandidates = true;
let candidateReviewSort = "score";
let locallyExcludedCandidates = new Set();
let currentJobRevision = "";
let lastHealth = null;
let visionSettingsState = null;
let selectedVisionProvider = "";
let visionDiscoveredModels = [];
let visionVerifiedAt = null;
let visionSettingsBusy = false;
let llmSettingsState = null;
let selectedLlmProvider = "";
let llmDiscoveredModels = [];
let llmVerifiedAt = null;
let llmSettingsBusy = false;
let selectedLlmMode = "reuse_vision";
const studio = $(".studio");
const panelLayoutStorageKey = "vlm-highlight-panel-layout-v2";
const timelineLayerStorageKey = "vlm-highlight-timeline-layers-v1";
const currentJobStorageKey = "vlm-highlight-current-job-v1";
const reviewLayoutStorageKey = "cliptalk-review-layout-v1";
const portraitVideoWidthStorageKey = "cliptalk-portrait-video-width-v1";
let recommendedReviewLayout = "landscape";
let directorStage = "conversation";
let openingHomeTaskId = null;
let restoringHistory = false;
// Invalidates in-flight restore/open/poll requests when the user starts or
// opens a different task. A late response must never replace the active task.
let workspaceGeneration = 0;
let activeChatController = null;
// A user-initiated return to the home dashboard must win over an in-flight
// history restore request.  Otherwise loadHistory() can reopen a running task
// immediately after resetWorkspace() clears it.
let homeNavigationRequested = false;
window.alert = (message) => showToast(message);

let subtitleReviewDraft = null;
let subtitleReviewResolver = null;
let subtitleReviewActiveCueId = null;
let subtitleReviewBusy = false;

function subtitleCueId() {
  return `cue_local_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
}

function markSubtitleDraftChanged() {
  if (!subtitleReviewDraft) return;
  subtitleReviewDraft.status = "draft";
  subtitleReviewDraft.confirmedAt = null;
  const state = $("#subtitleSaveState");
  if (state) state.textContent = "有未确认修改";
}

function subtitlePositionLabel(style = {}) {
  const horizontal = ({ left: "左", center: "居中", right: "右" })[style.horizontal] || "居中";
  const vertical = ({ top: "顶部", middle: "中央", bottom: "底部" })[style.vertical] || "底部";
  return `${vertical}${horizontal}`;
}

function activeSubtitleCue() {
  return subtitleReviewDraft?.cues?.find((cue) => cue.id === subtitleReviewActiveCueId) || subtitleReviewDraft?.cues?.[0] || null;
}

function updateSubtitlePreview() {
  const cue = activeSubtitleCue();
  const text = $("#subtitlePreviewText");
  const stage = $("#subtitlePreviewStage");
  if (!text || !stage || !subtitleReviewDraft) return;
  if (cue && subtitleReviewActiveCueId !== cue.id) subtitleReviewActiveCueId = cue.id;
  const style = subtitleReviewDraft.cueStyleOverrides?.[cue?.id] || subtitleReviewDraft.globalStyle || {};
  const horizontalBase = ({ left: 5, center: 50, right: 95 })[style.horizontal] ?? 50;
  const verticalBase = ({ top: 5, middle: 50, bottom: 95 })[style.vertical] ?? 95;
  const left = Math.max(5, Math.min(95, horizontalBase + Number(style.offsetXRatio || 0) * 100));
  const top = Math.max(5, Math.min(95, verticalBase + Number(style.offsetYRatio || 0) * 100));
  text.textContent = cue?.text || "（空字幕不会烧录）";
  text.style.left = `${left}%`;
  text.style.top = `${top}%`;
  text.style.fontSize = `${Math.max(14, stage.clientHeight * Number(style.fontSizeRatio || .04))}px`;
  text.style.transform = `translate(${style.horizontal === "left" ? "0" : style.horizontal === "right" ? "-100%" : "-50%"},${style.vertical === "top" ? "0" : style.vertical === "bottom" ? "-100%" : "-50%"})`;
  const summary = $("#subtitleStyleSummary");
  if (summary) summary.textContent = `字号 ${(Number(style.fontSizeRatio || .04) * 100).toFixed(1)}% · ${subtitlePositionLabel(style)}${subtitleReviewDraft.cueStyleOverrides?.[cue?.id] ? " · 本条单独设置" : " · 全部字幕"}`;
  const video = $("#subtitleReviewVideo");
  if (cue && video && Number.isFinite(Number(cue.sourceStart))) {
    const seek = () => { try { video.currentTime = Math.max(0, Number(cue.sourceStart)); } catch (_) {} };
    if (video.readyState >= 1) seek(); else video.addEventListener("loadedmetadata", seek, { once: true });
  }
}

function renderSubtitleCueList() {
  const list = $("#subtitleCueList");
  if (!list || !subtitleReviewDraft) return;
  const cues = subtitleReviewDraft.cues || [];
  if (subtitleReviewActiveCueId && !cues.some((cue) => cue.id === subtitleReviewActiveCueId)) subtitleReviewActiveCueId = cues[0]?.id || null;
  const count = $("#subtitleCueCount");
  if (count) count.textContent = `${cues.length} 条字幕${new Set(cues.map((cue) => cue.outputIndex)).size > 1 ? ` · ${new Set(cues.map((cue) => cue.outputIndex)).size} 条成片` : ""}`;
  list.innerHTML = cues.length ? cues.map((cue, index) => `
    <article class="subtitle-cue ${cue.id === subtitleReviewActiveCueId ? "is-active" : ""}" data-subtitle-cue="${escapeHtml(cue.id)}">
      <div class="subtitle-cue-head"><span class="subtitle-cue-index">${String(index + 1).padStart(2, "0")}${Number(cue.outputIndex || 0) ? ` · 成片 ${Number(cue.outputIndex) + 1}` : ""}</span><label class="subtitle-cue-time"><input data-cue-start type="number" min="0" step="0.01" value="${Number(cue.start || 0).toFixed(2)}"><span>→</span><input data-cue-end type="number" min="0" step="0.01" value="${Number(cue.end || 0).toFixed(2)}"><span>秒</span></label></div>
      <textarea data-cue-text maxlength="500" aria-label="字幕文字">${escapeHtml(cue.text || "")}</textarea>
      ${cue.suggestionStatus === "pending" ? `<div class="subtitle-suggestion"><strong>AI 文字建议（未应用）</strong><span>${escapeHtml(cue.suggestedText || "")}</span><small>${escapeHtml(cue.suggestionReason || "仅根据相邻文字上下文")}</small><div class="subtitle-suggestion-actions"><button type="button" data-cue-accept>接受</button><button type="button" data-cue-ignore>忽略</button></div></div>` : ""}
      <div class="subtitle-cue-actions"><button type="button" data-cue-play>试听定位</button><button type="button" data-cue-split>拆分</button><button type="button" data-cue-merge>与下一条合并</button><button type="button" data-cue-delete>删除</button></div>
    </article>`).join("") : `<p class="subtitle-ai-notice">当前没有字幕条目。可返回并选择不添加字幕。</p>`;
  list.querySelectorAll("[data-subtitle-cue]").forEach((card) => {
    const cue = cues.find((item) => item.id === card.dataset.subtitleCue);
    if (!cue) return;
    card.addEventListener("click", () => {
      subtitleReviewActiveCueId = cue.id;
      list.querySelectorAll(".subtitle-cue").forEach((node) => node.classList.toggle("is-active", node === card));
      updateSubtitlePreview();
    });
    card.querySelector("[data-cue-text]")?.addEventListener("input", (event) => {
      cue.text = event.target.value;
      if (cue.suggestionStatus === "pending") cue.suggestionStatus = "ignored";
      markSubtitleDraftChanged(); updateSubtitlePreview();
    });
    [["[data-cue-start]", "start"], ["[data-cue-end]", "end"]].forEach(([selector, key]) => card.querySelector(selector)?.addEventListener("change", (event) => {
      cue[key] = Number(event.target.value); markSubtitleDraftChanged();
    }));
    card.querySelector("[data-cue-play]")?.addEventListener("click", () => {
      showSource({ autoplay: false }); seekSourceTime(Number(cue.sourceStart ?? 0));
      const video = $("#subtitleReviewVideo"); if (video) { video.currentTime = Math.max(0, Number(cue.sourceStart ?? 0)); video.play().catch(() => {}); }
    });
    card.querySelector("[data-cue-accept]")?.addEventListener("click", () => {
      cue.text = cue.suggestedText || cue.text; cue.suggestionStatus = "accepted"; markSubtitleDraftChanged(); renderSubtitleCueList(); updateSubtitlePreview();
    });
    card.querySelector("[data-cue-ignore]")?.addEventListener("click", () => {
      cue.suggestionStatus = "ignored"; markSubtitleDraftChanged(); renderSubtitleCueList();
    });
    card.querySelector("[data-cue-delete]")?.addEventListener("click", () => {
      subtitleReviewDraft.cues = cues.filter((item) => item.id !== cue.id); markSubtitleDraftChanged(); renderSubtitleCueList(); updateSubtitlePreview();
    });
    card.querySelector("[data-cue-split]")?.addEventListener("click", () => {
      const duration = Number(cue.end) - Number(cue.start); if (duration < .2) return void showToast("这条字幕太短，无法继续拆分");
      const middle = Number(cue.start) + duration / 2;
      const textValue = String(cue.text || "");
      let textBreak = Math.floor(textValue.length / 2);
      for (let offset = 0; offset < textValue.length / 2; offset += 1) { const candidate = [textBreak + offset, textBreak - offset].find((value) => /[，。！？、；\s]/.test(textValue[value] || "")); if (candidate !== undefined) { textBreak = candidate + 1; break; } }
      const second = { ...cue, id: subtitleCueId(), start: Number(middle.toFixed(3)), text: textValue.slice(textBreak).trim(), originalText: textValue.slice(textBreak).trim(), suggestionStatus: "none", suggestedText: null };
      cue.end = Number(middle.toFixed(3)); cue.text = textValue.slice(0, textBreak).trim(); cue.suggestionStatus = "none";
      subtitleReviewDraft.cues.splice(cues.indexOf(cue) + 1, 0, second); markSubtitleDraftChanged(); renderSubtitleCueList();
    });
    card.querySelector("[data-cue-merge]")?.addEventListener("click", () => {
      const index = cues.indexOf(cue); const next = cues[index + 1];
      if (!next || Number(next.outputIndex || 0) !== Number(cue.outputIndex || 0)) return void showToast("没有可合并的下一条字幕");
      cue.end = Math.max(Number(cue.end), Number(next.end)); cue.text = [cue.text, next.text].filter(Boolean).join(" "); cue.suggestionStatus = "none";
      subtitleReviewDraft.cues.splice(index + 1, 1); markSubtitleDraftChanged(); renderSubtitleCueList(); updateSubtitlePreview();
    });
  });
  updateSubtitlePreview();
}

function setSubtitleReviewBusy(busy, label = "") {
  subtitleReviewBusy = Boolean(busy);
  $("#subtitleReview")?.querySelectorAll("button,input,textarea").forEach((node) => { node.disabled = subtitleReviewBusy; });
  const state = $("#subtitleSaveState"); if (state && label) state.textContent = label;
}

async function saveSubtitleReviewDraft(confirmed = false) {
  if (!currentJob || !subtitleReviewDraft || subtitleReviewBusy) return null;
  setSubtitleReviewBusy(true, confirmed ? "正在确认字幕…" : "正在保存…");
  try {
    const payload = await api(`/api/jobs/${encodeURIComponent(currentJob.id)}/subtitle-drafts/${encodeURIComponent(subtitleReviewDraft.id)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision: subtitleReviewDraft.revision, cues: subtitleReviewDraft.cues, globalStyle: subtitleReviewDraft.globalStyle, cueStyleOverrides: subtitleReviewDraft.cueStyleOverrides || {}, confirmed, sourceSubtitleAcknowledged: Boolean($("#subtitleSourceAck")?.checked) }),
    });
    subtitleReviewDraft = payload.draft;
    const sourceAck = $("#subtitleSourceAck"); if (sourceAck) sourceAck.checked = Boolean(subtitleReviewDraft.sourceSubtitleAcknowledged);
    const confirmButton = $("#subtitleConfirmButton"); if (confirmButton) confirmButton.disabled = !sourceAck?.checked;
    const state = $("#subtitleSaveState"); if (state) state.textContent = confirmed ? "字幕已确认" : "草稿已保存，仍需确认";
    renderSubtitleCueList();
    return subtitleReviewDraft;
  } catch (error) { showToast(error.message); return null; }
  finally { setSubtitleReviewBusy(false); }
}

function closeSubtitleReview(result = null) {
  $("#subtitleReview")?.classList.add("hidden");
  $("#subtitleReviewVideo")?.pause();
  const resolve = subtitleReviewResolver; subtitleReviewResolver = null;
  if (resolve) resolve(result);
}

async function reviewSubtitlesBeforeRender(outputs, subtitleStyle = "clean") {
  if (!currentJob || subtitleReviewBusy) return null;
  setSubtitleReviewBusy(true, "正在建立字幕草稿…");
  try {
    const payload = await api(`/api/jobs/${encodeURIComponent(currentJob.id)}/subtitle-drafts`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ outputs, subtitleStyle }),
    });
    subtitleReviewDraft = payload.draft;
    subtitleReviewActiveCueId = subtitleReviewDraft.cues?.[0]?.id || null;
    const review = $("#subtitleReview"); review?.classList.remove("hidden");
    const sourceAck = $("#subtitleSourceAck"); if (sourceAck) sourceAck.checked = Boolean(subtitleReviewDraft.sourceSubtitleAcknowledged);
    const confirmButton = $("#subtitleConfirmButton"); if (confirmButton) confirmButton.disabled = !sourceAck?.checked;
    const video = $("#subtitleReviewVideo");
    if (video && mainVideo?.currentSrc) { video.src = mainVideo.currentSrc; video.load(); }
    const state = $("#subtitleSaveState"); if (state) state.textContent = "识别草稿待人工确认";
    renderSubtitleCueList();
    setSubtitleReviewBusy(false);
    return await new Promise((resolve) => { subtitleReviewResolver = resolve; });
  } catch (error) { showToast(error.message); return null; }
  finally { setSubtitleReviewBusy(false); }
}

async function applySubtitleStyleCommand(command) {
  if (!currentJob || !subtitleReviewDraft || subtitleReviewBusy) return;
  const status = $("#subtitleCommandStatus"); if (status) status.textContent = "正在理解命令…";
  setSubtitleReviewBusy(true);
  try {
    const payload = await api(`/api/jobs/${encodeURIComponent(currentJob.id)}/subtitle-drafts/${encodeURIComponent(subtitleReviewDraft.id)}/style-command`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: command, cueId: subtitleReviewActiveCueId }),
    });
    const proposal = payload.proposal;
    if (proposal.scope === "cue" && proposal.cueId) subtitleReviewDraft.cueStyleOverrides = { ...(subtitleReviewDraft.cueStyleOverrides || {}), [proposal.cueId]: proposal.style };
    else subtitleReviewDraft.globalStyle = proposal.style;
    markSubtitleDraftChanged(); updateSubtitlePreview();
    if (status) status.textContent = `${proposal.summary} · ${proposal.scope === "cue" ? "仅当前字幕" : "已应用到全部字幕"}`;
  } catch (error) { if (status) status.textContent = error.message; }
  finally { setSubtitleReviewBusy(false); }
}

$("#subtitleReview")?.querySelectorAll("[data-subtitle-close]").forEach((button) => button.addEventListener("click", () => closeSubtitleReview(null)));
$("#subtitleSaveButton")?.addEventListener("click", () => saveSubtitleReviewDraft(false));
$("#subtitleConfirmButton")?.addEventListener("click", async () => { const draft = await saveSubtitleReviewDraft(true); if (draft) closeSubtitleReview(draft); });
$("#subtitleSourceAck")?.addEventListener("change", (event) => {
  const checked = Boolean(event.currentTarget?.checked);
  const button = $("#subtitleConfirmButton"); if (button) button.disabled = !checked;
  const state = $("#subtitleSaveState"); if (state && !checked) state.textContent = "请先确认原视频字幕状态";
});
$("#subtitleSuggestButton")?.addEventListener("click", async () => {
  if (!subtitleReviewDraft || subtitleReviewBusy) return;
  if (!await saveSubtitleReviewDraft(false)) return;
  setSubtitleReviewBusy(true, "AI 正在检查文字上下文…");
  try {
    const payload = await api(`/api/jobs/${encodeURIComponent(currentJob.id)}/subtitle-drafts/${encodeURIComponent(subtitleReviewDraft.id)}/suggestions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    subtitleReviewDraft = payload.draft; renderSubtitleCueList();
    $("#subtitleSaveState").textContent = payload.suggestionCount ? `发现 ${payload.suggestionCount} 条待处理建议` : "未发现有把握的文字问题";
  } catch (error) { showToast(error.message); }
  finally { setSubtitleReviewBusy(false); }
});
$("#subtitleCommandForm")?.addEventListener("submit", (event) => { event.preventDefault(); const input = $("#subtitleCommandInput"); const value = input?.value.trim(); if (value) applySubtitleStyleCommand(value); });
$("#subtitleReview")?.querySelectorAll("[data-subtitle-command]").forEach((button) => button.addEventListener("click", () => applySubtitleStyleCommand(button.dataset.subtitleCommand)));

function captureJobAction(job = currentJob) {
  return { generation: workspaceGeneration, jobId: String(job?.id || "") };
}

function jobActionStillCurrent(token) {
  return Boolean(token)
    && token.generation === workspaceGeneration
    && !homeNavigationRequested
    && (!token.jobId || String(currentJob?.id || "") === token.jobId);
}

function commitJobAction(job, token) {
  if (!job?.id || !jobActionStillCurrent(token)) return false;
  if (token.jobId && String(job.id) !== token.jobId) return false;
  renderJob(job);
  return true;
}

function invalidateWorkspaceRequests() {
  workspaceGeneration += 1;
  contentEvidenceRequestToken += 1;
  activeChatController?.abort();
  activeChatController = null;
  clearTimeout(pollTimer);
  pollTimer = null;
  actionBusy = false;
}

function routeJobId() {
  try {
    const hash = String(window.location.hash || "").replace(/^#/, "");
    if (!hash) return null;
    return new URLSearchParams(hash).get("job") || null;
  } catch {
    return null;
  }
}

function setRouteJobId(jobId = null) {
  try {
    const url = new URL(window.location.href);
    if (jobId) {
      url.hash = `job=${encodeURIComponent(String(jobId))}`;
    } else if (routeJobId()) {
      url.hash = "";
    }
    window.history.replaceState(window.history.state, "", url.href);
  } catch { /* URL/history may be unavailable in embedded previews */ }
}

function rememberCurrentJob(job) {
  if (!job?.id) return;
  try { localStorage.setItem(currentJobStorageKey, String(job.id)); } catch { /* storage may be disabled */ }
  try { sessionStorage.setItem(currentJobStorageKey, String(job.id)); } catch { /* storage may be disabled */ }
  // The URL is tab-local and therefore wins over a shared localStorage value
  // when more than one task is open in the browser.
  setRouteJobId(job.id);
}

function forgetCurrentJob() {
  try { localStorage.removeItem(currentJobStorageKey); } catch { /* storage may be disabled */ }
  try { sessionStorage.removeItem(currentJobStorageKey); } catch { /* storage may be disabled */ }
  setRouteJobId(null);
}

function storedCurrentJobId() {
  try {
    return sessionStorage.getItem(currentJobStorageKey)
      || localStorage.getItem(currentJobStorageKey)
      || null;
  } catch {
    try { return sessionStorage.getItem(currentJobStorageKey) || null; } catch { return null; }
  }
}

function storedReviewLayout(jobId = currentJob?.id) {
  if (!jobId) return null;
  try {
    const saved = JSON.parse(localStorage.getItem(reviewLayoutStorageKey) || "{}");
    const value = String(saved?.[String(jobId)] || "");
    return ["landscape", "portrait"].includes(value) ? value : null;
  } catch {
    return null;
  }
}

function rememberReviewLayout(layout, jobId = currentJob?.id) {
  if (!jobId || !["landscape", "portrait"].includes(layout)) return;
  let preferences = {};
  try {
    const saved = JSON.parse(localStorage.getItem(reviewLayoutStorageKey) || "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved)) preferences = saved;
  } catch { /* replace malformed legacy data below */ }
  preferences[String(jobId)] = layout;
  try { localStorage.setItem(reviewLayoutStorageKey, JSON.stringify(preferences)); }
  catch { /* storage may be disabled */ }
}

function storedPortraitVideoWidth(jobId = currentJob?.id) {
  if (!jobId) return null;
  try {
    const saved = JSON.parse(localStorage.getItem(portraitVideoWidthStorageKey) || "{}");
    const width = Number(saved?.[String(jobId)]);
    return Number.isFinite(width) && width > 0 ? width : null;
  } catch {
    return null;
  }
}

function rememberPortraitVideoWidth(width, jobId = currentJob?.id) {
  if (!jobId || !Number.isFinite(Number(width))) return;
  let preferences = {};
  try {
    const saved = JSON.parse(localStorage.getItem(portraitVideoWidthStorageKey) || "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved)) preferences = saved;
  } catch { /* replace malformed legacy data below */ }
  preferences[String(jobId)] = Math.round(Number(width));
  try { localStorage.setItem(portraitVideoWidthStorageKey, JSON.stringify(preferences)); }
  catch { /* storage may be disabled */ }
}

function forgetPortraitVideoWidth(jobId = currentJob?.id) {
  if (!jobId) return;
  try {
    const saved = JSON.parse(localStorage.getItem(portraitVideoWidthStorageKey) || "{}");
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return;
    delete saved[String(jobId)];
    localStorage.setItem(portraitVideoWidthStorageKey, JSON.stringify(saved));
  } catch { /* storage may be disabled */ }
}

function portraitVideoWidthLimits() {
  const reviewView = $("#reviewView");
  const available = Math.max(0, reviewView?.clientWidth || 0);
  const minimum = Math.min(280, Math.max(220, Math.round(available * .28)));
  const leftMinimum = Math.min(440, Math.max(320, Math.round(available * .38)));
  const maximum = Math.max(minimum, Math.min(640, available - leftMinimum - 22));
  const fallback = Math.max(minimum, Math.min(maximum, Math.round(Math.min(440, available * .34))));
  return { minimum, maximum, fallback };
}

function setPortraitVideoWidth(value, { persist = false } = {}) {
  const reviewView = $("#reviewView");
  const handle = $("#portraitVideoResizer");
  if (!reviewView || !handle) return 0;
  const { minimum, maximum, fallback } = portraitVideoWidthLimits();
  const requested = Number(value);
  const width = Math.round(Math.max(minimum, Math.min(maximum, Number.isFinite(requested) ? requested : fallback)));
  reviewView.style.setProperty("--portrait-video-width", `${width}px`);
  reviewView.dataset.portraitVideoWidth = String(width);
  handle.setAttribute("aria-valuemin", String(minimum));
  handle.setAttribute("aria-valuemax", String(maximum));
  handle.setAttribute("aria-valuenow", String(width));
  if (persist) rememberPortraitVideoWidth(width);
  scheduleMediaFrameFit(true);
  return width;
}

function restorePortraitVideoWidth() {
  const saved = storedPortraitVideoWidth();
  return setPortraitVideoWidth(saved ?? portraitVideoWidthLimits().fallback);
}

function updateReviewLayoutControls(layout) {
  document.querySelectorAll("#reviewLayoutSwitch [data-review-layout-mode]").forEach((button) => {
    const active = button.dataset.reviewLayoutMode === layout;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function setReviewLayout(layout, { persist = false } = {}) {
  const normalized = layout === "portrait" ? "portrait" : "landscape";
  const reviewView = $("#reviewView");
  if (reviewView) reviewView.dataset.reviewLayout = normalized;
  updateReviewLayoutControls(normalized);
  if (persist) rememberReviewLayout(normalized);
  if (normalized === "portrait") restorePortraitVideoWidth();
  scheduleTimelineResizeRender(true);
  scheduleMediaFrameFit(true);
  return normalized;
}

function syncReviewLayoutForMedia(aspect) {
  recommendedReviewLayout = Number(aspect) < .82 ? "portrait" : "landscape";
  setReviewLayout(storedReviewLayout() || recommendedReviewLayout);
}

document.querySelectorAll("#reviewLayoutSwitch [data-review-layout-mode]").forEach((button) => {
  button.addEventListener("click", () => setReviewLayout(button.dataset.reviewLayoutMode, { persist: true }));
});

function setDirectorWorkspaceEmpty(visible) {
  const empty = $(".director-workspace-empty");
  if (!empty) return;
  empty.classList.toggle("hidden", !visible);
  // Keep this explicit as a guard against legacy theme rules or stale layout
  // classes making the onboarding placeholder reappear over a real task.
  empty.style.display = visible ? "" : "none";
}

function setupDirectorWorkspace() {
  const host = $("#chatStageHost");
  const rail = $(".review-rail");
  if (!host || !rail || !studio || host.dataset.ready === "true") return;
  // Keep every task-stage surface in one persistent host.  In particular the
  // progress console must not remain in the rail while the chat renderer
  // rebuilds #chatMessages; otherwise it is removed and re-inserted on every
  // poll, which looks like a flicker.
  ["jobStatus", "railBody", "clipSection", "railOutput"].forEach((id) => {
    const node = document.getElementById(id);
    if (node) host.append(node);
  });
  host.dataset.ready = "true";
  studio.classList.add("director-merged");
  rail.classList.add("merged-review-rail");
  $(".panel-resizer-right")?.classList.add("hidden");
  setDirectorStage("conversation");
}

function placeAnalysisConsole(inConversation = false) {
  const status = $("#jobStatus");
  const host = $("#chatStageHost");
  const messages = $("#chatMessages");
  if (!status || !messages) return;
  // Keep the legacy console mounted so shared update functions can still write
  // progress facts, but use #inlineAnalysisProgress as the visible pipeline
  // surface. The legacy node remains visible only when it contains the model
  // decision buttons that the user must be able to click.
  host?.classList.remove("hidden", "director-stage-hidden");
  host?.style.removeProperty("display");
  if (status.parentElement !== messages) messages.append(status);
  const showDecisionPanel = currentJob?.status === "awaiting_model_decision";
  status.classList.toggle("hidden", !showDecisionPanel);
  status.classList.toggle("pipeline-active", showDecisionPanel);
  status.hidden = !showDecisionPanel;
  if (showDecisionPanel) status.style.removeProperty("display");
  else status.style.display = "none";
  status.setAttribute("aria-hidden", showDecisionPanel ? "false" : "true");
}

// Keep one source of truth for pipeline states. The inline conversation
// progress card and the polling loop must agree about which states are still
// active; otherwise a running job can lose its progress card between polls.
const ACTIVE_JOB_STATUSES = new Set([
  "briefing",
  "queued",
  "running",
  "processing",
  "analyzing",
  "cancelling",
  "awaiting_model_decision",
]);

function isActiveJobStatus(status) {
  return ACTIVE_JOB_STATUSES.has(String(status || ""));
}

function isPipelineRunningStatus(status) {
  const value = String(status || "");
  return isActiveJobStatus(value) && !["briefing", "queued", "cancelling", "awaiting_model_decision"].includes(value);
}

function jobNeedsPolling(job = currentJob) {
  return isActiveJobStatus(job?.status) || ["queued", "running"].includes(String(job?.autoComposition?.status || ""));
}

function jobPollDelay(job = currentJob) {
  const stage = String(job?.stage || "");
  if (stage === "speech_recognition" || stage === "speech_analysis" || stage === "audio_analysis") return 1800;
  if (stage === "coarse_vlm" || stage === "refine_vlm" || stage === "event_director") return 1500;
  if (["queued", "running"].includes(String(job?.autoComposition?.status || ""))) return 1600;
  return 1400;
}

function analysisConsoleVisible(job) {
  return ["briefing", "queued", "running", "processing", "analyzing", "cancelling"].includes(String(job?.status || ""));
}

function setDirectorStage(stage = "conversation") {
  directorStage = ["conversation", "analysis", "events", "compose"].includes(stage) ? stage : "conversation";
  updateDirectorFlow(currentJob);
  const messages = $("#chatMessages");
  const composer = $("#chatForm");
  const body = $("#railBody");
  const output = $("#railOutput");
  const clips = $("#clipSection");
  setDirectorWorkspaceEmpty(!currentJob);
  if (!body || !output || !clips) return;
  // Keep the conversation mounted while analysis, rendering, and completed
  // results are visible. Progress and the final handoff belong in the dialog;
  // switching to the compose stage must not make the chat disappear.
  const conversationVisible = directorStage === "conversation"
    || ["queued", "running", "cancelling", "completed"].includes(String(currentJob?.status || ""));
  // Conversation, review controls and composition controls share one scroll
  // surface. Stages only decide which controls are expanded in that stream.
  messages?.classList.remove("director-stage-hidden");
  composer?.classList.remove("director-stage-hidden");
  body.classList.toggle("director-stage-hidden", directorStage !== "events");
  output.classList.toggle("director-stage-hidden", directorStage !== "compose");
  clips.classList.toggle("director-stage-hidden", directorStage !== "compose");
  renderDirectorContext(currentJob);
}

function directorFlowStage(job = currentJob) {
  if (!job) return "brief";
  if (String(job.taskMode || "") === "content_extract" && job.workflow?.phase) {
    const contentPhases = { prepare: "brief", search: "analysis", review: "events", render: "compose", complete: "compose" };
    return contentPhases[String(job.workflow.phase)] || "analysis";
  }
  if (["briefing", "brief_confirmation"].includes(job.status)) return "brief";
  const compositionStage = ["edit_planning", "edit_planning_complete", "rendering", "render", "auto_composition"].includes(String(job.stage || ""));
  const autoCompositionStatus = String(job.autoComposition?.status || "");
  const hasOutputs = jobOutputCount(job) > 0;
  // Event review deliberately remains available after automatic rendering, so
  // the backend can keep the job in awaiting_confirmation.  The visible flow
  // must follow the actual render/output state instead of treating every such
  // job as if analysis were still in progress.
  if (job.status === "completed" || compositionStage || ["queued", "running", "completed"].includes(autoCompositionStatus)) return "compose";
  if (["queued", "running", "cancelling", "awaiting_model_decision"].includes(job.status)) return "analysis";
  if (job.status === "awaiting_confirmation") return hasOutputs ? "compose" : "events";
  if (job.status === "awaiting_content_confirmation") return "events";
  if (["cancelled", "failed"].includes(job.status)) return "analysis";
  return "brief";
}

function compositionIsComplete(job = currentJob) {
  if (!job) return false;
  if (job.status === "completed") return true;
  return job.autoComposition?.status === "completed" && jobOutputCount(job) > 0;
}

function updateDirectorFlow(job = currentJob) {
  const internalStage = directorFlowStage(job);
  const current = internalStage;
  const order = ["brief", "analysis", "events", "compose"];
  const position = order.indexOf(current);
  const finished = current === "compose" && compositionIsComplete(job);
  document.querySelectorAll("[data-director-flow]").forEach((step) => {
    const index = order.indexOf(step.dataset.directorFlow);
    const isCurrent = step.dataset.directorFlow === current;
    step.classList.toggle("current", isCurrent);
    step.classList.toggle("complete", index >= 0 && (index < position || (finished && index === position)));
    step.classList.toggle("upcoming", index > position);
    if (isCurrent) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  });
}

function taskModePresentation(job = currentJob) {
  const content = String(job?.taskMode || "highlight") === "content_extract";
  return content
    ? {
        key: "content_extract",
        label: "内容探索",
        phaseLabels: { brief: "需求确认", analysis: "内容探索", events: "片段确认", compose: "确认生成" },
        nav: [
          ["准备", "描述要查找的内容"],
          ["内容探索", "识别并检索目标内容"],
          ["片段确认", "预览并选择匹配片段"],
          ["生成结果", "合成、预览并下载"],
        ],
      }
    : {
        key: "highlight",
        label: "高光发现",
        phaseLabels: { brief: "需求确认", analysis: "高光发现", events: "事件审核", compose: "生成版本" },
        nav: [
          ["准备", "确认要求并准备媒体"],
          ["高光发现", "发现并组织精彩事件"],
          ["事件审核", "确认事件与内部镜头"],
          ["生成版本", "合成、预览并下载"],
        ],
      };
}

function updateTaskModeNavigation(job = currentJob) {
  const presentation = taskModePresentation(job);
  const nav = $("#directorStageNav");
  if (!nav) return;
  nav.setAttribute("aria-label", `${presentation.label}流程`);
  nav.querySelectorAll("[data-director-flow]").forEach((step, index) => {
    const [label, detail] = presentation.nav[index] || presentation.nav.at(-1);
    const strong = step.querySelector("strong");
    const small = step.querySelector("small");
    if (strong) strong.textContent = label;
    if (small) small.textContent = detail;
  });
}

function renderDirectorContext(job = currentJob) {
  const summary = $("#directorContextSummary");
  if (!summary) return;
  if (!job || directorStage === "conversation") {
    summary.classList.add("hidden");
    summary.innerHTML = "";
    return;
  }
  if (String(job.taskMode || "") === "content_extract") {
    const search = job.contentSearch || {};
    const query = search.intent?.query || search.instruction || job.request?.contentInstruction || "按描述查找内容";
    const scope = search.intent?.searchScope || search.retrievalStats?.searchScope || {};
    const scopeText = Number(scope.end) > Number(scope.start)
      ? `${formatTime(scope.start)} → ${formatTime(scope.end)}`
      : "整个源视频";
    const resultMode = String(search.resultMode || search.queryPlan?.result?.mode || "top_k") === "exhaustive" ? "全部匹配" : "最相关片段";
    summary.innerHTML = `<div><small>当前查找条件</small><strong>${escapeHtml(query)}</strong></div><span>范围：${escapeHtml(scopeText)}</span><span>结果：${escapeHtml(resultMode)}</span><span>边界以真实索引证据为准</span>`;
    summary.classList.remove("hidden");
    return;
  }
  const brief = job.brief || {};
  const focus = (brief.focus || []).filter(Boolean).join("、") || "综合判断";
  const target = Number(brief.targetDurationSeconds || job.totalTargetSeconds || 0);
  const subtitle = brief.subtitlePreference === "burn" ? "添加字幕" : "不加字幕";
  summary.innerHTML = `<div><small>当前剪辑需求</small><strong>${escapeHtml(brief.objective || "事件高光合集")}</strong></div><span>重点：${escapeHtml(focus)}</span><span>${target ? `单条目标 ${target.toFixed(1)} 秒` : "单条时长由 AI 推荐"}</span><span>${escapeHtml(subtitle)}</span>`;
  summary.classList.remove("hidden");
}

function renderDirectorTaskSummary(job = currentJob) {
  const summary = $("#directorTaskSummary");
  if (!summary) return;
  if (!job) {
    summary.innerHTML = `<strong>等待创建任务</strong><span>上传视频后，AI 会先确认你的剪辑目标。</span>`;
    updateTaskModeNavigation(null);
    return;
  }
  const presentation = taskModePresentation(job);
  updateTaskModeNavigation(job);
  const brief = job.brief || {};
  const objective = brief.objective || job.request?.objective || "事件高光合集";
  const duration = Number(job.videoInfo?.duration || 0);
  const target = Number(brief.targetDurationSeconds || job.totalTargetSeconds || 0);
  const outputCount = jobOutputCount(job);
  const compositionComplete = compositionIsComplete(job);
  const contentMode = presentation.key === "content_extract";
  const status = compositionComplete
    ? (contentMode ? `${outputCount} 个内容视频版本已完成` : `${outputCount} 个成片版本已完成${job.status === "awaiting_confirmation" ? " · 事件和镜头均可单独下载" : ""}`)
    : job.status === "awaiting_content_confirmation" ? "内容候选已就绪 · 待确认"
      : job.status === "awaiting_confirmation" ? "事件已就绪 · 待审核"
      : job.status === "completed" ? (contentMode ? "内容视频已完成" : "成片已完成") : job.detail || "任务进行中";
  const flowStage = directorFlowStage(job);
  summary.innerHTML = `<div class="director-task-heading"><span class="task-mode-badge ${presentation.key}">${presentation.label}</span><small>当前阶段 · ${presentation.phaseLabels[flowStage] || "处理中"}</small></div><strong title="${escapeHtml(job.filename || objective)}">${escapeHtml(job.filename || objective)}</strong><p>${escapeHtml(status)}</p><div class="director-task-facts"><span>${duration ? `源视频 ${formatClock(duration)}` : "源视频待准备"}</span>${target && presentation.key === "highlight" ? `<span>目标 ${target.toFixed(1)} 秒</span>` : ""}</div>`;
}

function renderReviewStatus(job = currentJob) {
  const node = $("#reviewStatus");
  if (!node) return;
  const modeBadge = $("#reviewTaskMode");
  if (modeBadge) {
    const presentation = taskModePresentation(job);
    modeBadge.textContent = presentation.label;
    modeBadge.classList.toggle("content_extract", presentation.key === "content_extract");
    modeBadge.classList.toggle("highlight", presentation.key === "highlight");
    modeBadge.classList.toggle("hidden", !job);
  }
  const stageLabels = {
    starting: "读取素材",
    probing: "读取素材",
    audio_analysis: "理解声音",
    speech_recognition: "理解对白",
    speech_analysis: "分析语音",
    content_transcription: "识别对白",
    content_sampling: "准备画面检索",
    content_indexing: "准备所需索引",
    content_recognition: "建立所需索引",
    content_index_ready: "索引已就绪",
    content_search: "搜索内容",
    content_active_speaker: "识别说话人物",
    content_refinement: "精修边界",
    content_search_ready: "等待确认",
    sampling: "粗看全片",
    coarse_vlm: "粗看全片",
    refine_vlm: "精修镜头",
    event_grouping: "事件编排",
    event_director: "事件编排",
    rendering: "生成成片",
    auto_composition: "生成成片",
  };
  const active = isActiveJobStatus(job?.status);
  const outputCount = jobOutputCount(job);
  const compositionComplete = compositionIsComplete(job);
  const contentMode = String(job?.taskMode || "") === "content_extract";
  const label = !job ? "等待分析"
    : compositionComplete ? `${outputCount} 个${contentMode ? "内容视频" : "成片"}已完成`
      : active ? `AI 分析 · ${stageLabels[String(job.stage || "")] || "处理中"}`
      : job.status === "awaiting_content_confirmation" ? "等待确认内容片段"
        : job.status === "awaiting_confirmation" ? "等待审核"
        : job.status === "completed" ? "已完成"
          : job.status === "failed" ? "分析失败" : "已停止";
  node.textContent = label;
  node.classList.toggle("active", active && !compositionComplete);
  node.classList.toggle("complete", compositionComplete);
}

try {
  const savedTimelineLayers = JSON.parse(localStorage.getItem(timelineLayerStorageKey) || "null");
  if (savedTimelineLayers) {
    timelineCutsVisible = savedTimelineLayers.cuts !== false;
  }
} catch { /* storage may be disabled */ }

function panelLayoutDefaults() {
  return window.innerWidth <= 1380 ? { left: 380, right: 300 } : { left: 400, right: 350 };
}

function panelMinimumCenterWidth() {
  return window.innerWidth <= 1380 ? 500 : 560;
}

function setPanelWidth(side, value) {
  const rounded = Math.round(Number(value));
  const minimum = side === "left" ? 300 : 280;
  const mergedLeft = side === "left" && studio?.classList.contains("director-merged") && !studio?.classList.contains("home-mode");
  const maximum = mergedLeft ? 760 : 620;
  const width = Math.max(minimum, Math.min(maximum, rounded || panelLayoutDefaults()[side]));
  studio?.style.setProperty(side === "left" ? "--chat-panel-width" : "--rail-panel-width", `${width}px`);
  const handle = $(`[data-panel-resizer="${side}"]`);
  handle?.setAttribute("aria-valuemin", String(minimum));
  handle?.setAttribute("aria-valuemax", String(maximum));
  handle?.setAttribute("aria-valuenow", String(width));
  return width;
}

function currentPanelLayout() {
  const merged = studio?.classList.contains("director-merged") && !studio?.classList.contains("home-mode");
  const chatPanel = $(".chat-panel");
  const reviewRail = $(".review-rail");
  return {
    left: chatPanel ? Math.round(chatPanel.getBoundingClientRect().width) : panelLayoutDefaults().left,
    right: merged ? 0 : reviewRail ? Math.round(reviewRail.getBoundingClientRect().width) : panelLayoutDefaults().right,
  };
}

function savePanelLayout() {
  try { localStorage.setItem(panelLayoutStorageKey, JSON.stringify(currentPanelLayout())); } catch { /* storage may be disabled */ }
}

function restorePanelLayout() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(panelLayoutStorageKey) || "null"); } catch { saved = null; }
  const defaults = panelLayoutDefaults();
  setPanelWidth("left", saved?.left || defaults.left);
  setPanelWidth("right", saved?.right || defaults.right);
}

function availableSidePanelWidth() {
  if (!studio) return 0;
  const styles = getComputedStyle(studio);
  const horizontalPadding = parseFloat(styles.paddingLeft) + parseFloat(styles.paddingRight);
  const columnGap = parseFloat(styles.columnGap) || 0;
  const merged = studio?.classList.contains("director-merged") && !studio?.classList.contains("home-mode");
  const handles = [...document.querySelectorAll(".panel-resizer")]
    .reduce((total, handle) => total + handle.getBoundingClientRect().width, 0);
  const centerMin = panelMinimumCenterWidth();
  const available = studio.clientWidth - horizontalPadding - handles - (merged ? columnGap * 2 : columnGap * 4) - centerMin;
  return merged ? Math.max(300, available) : Math.max(580, available);
}

function maximumPanelWidth(side, currentWidth) {
  const merged = studio?.classList.contains("director-merged") && !studio?.classList.contains("home-mode");
  if (merged && side === "left") return Math.min(760, availableSidePanelWidth());
  const other = currentPanelLayout()[side === "left" ? "right" : "left"];
  return Math.min(620, availableSidePanelWidth() - other);
}

function clampPanelLayoutToViewport() {
  if (window.innerWidth <= 760) return;
  let { left, right } = currentPanelLayout();
  const available = availableSidePanelWidth();
  const overflow = left + right - available;
  if (overflow <= 0) return;
  const leftCapacity = Math.max(0, left - 300);
  const rightCapacity = Math.max(0, right - 280);
  const capacity = leftCapacity + rightCapacity || 1;
  left -= overflow * leftCapacity / capacity;
  right -= overflow * rightCapacity / capacity;
  setPanelWidth("left", left);
  setPanelWidth("right", right);
  savePanelLayout();
}

function bindPanelResizers() {
  document.querySelectorAll("[data-panel-resizer]").forEach((handle) => {
    const side = handle.dataset.panelResizer;
    handle.addEventListener("pointerdown", (event) => {
      if (window.innerWidth <= 760 || event.button !== 0) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = currentPanelLayout()[side];
      const maximum = maximumPanelWidth(side, startWidth);
      let pendingWidth = startWidth;
      let resizeFrame = null;
      handle.classList.add("dragging");
      document.body.classList.add("panel-resizing");
      handle.setPointerCapture?.(event.pointerId);
      const applyPendingWidth = () => {
        resizeFrame = null;
        setPanelWidth(side, pendingWidth);
      };
      const move = (moveEvent) => {
        const delta = moveEvent.clientX - startX;
        const next = side === "left" ? startWidth + delta : startWidth - delta;
        pendingWidth = Math.min(maximum, next);
        if (resizeFrame === null) resizeFrame = requestAnimationFrame(applyPendingWidth);
      };
      const finish = () => {
        if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
        applyPendingWidth();
        handle.classList.remove("dragging");
        document.body.classList.remove("panel-resizing");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", finish);
        handle.removeEventListener("pointercancel", finish);
        savePanelLayout();
        scheduleTimelineResizeRender(true);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", finish);
      handle.addEventListener("pointercancel", finish);
    });
    handle.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key) || window.innerWidth <= 760) return;
      event.preventDefault();
      const current = currentPanelLayout()[side];
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const delta = side === "left" ? direction * 16 : direction * -16;
      setPanelWidth(side, Math.min(maximumPanelWidth(side, current), current + delta));
      savePanelLayout();
    });
    handle.addEventListener("dblclick", () => {
      setPanelWidth(side, panelLayoutDefaults()[side]);
      savePanelLayout();
    });
  });
}

function bindTimelineResizer() {
  const handle = $("#timelineResizer");
  const reviewView = $("#reviewView");
  if (!handle || !reviewView || handle.dataset.bound === "true") return;
  handle.dataset.bound = "true";
  const limits = () => {
    const viewHeight = reviewView.getBoundingClientRect().height;
    const minTimeline = 180;
    const minViewer = 220;
    return { min: minTimeline, max: Math.max(minTimeline, viewHeight - minViewer - 95) };
  };
  const setHeight = (value) => {
    const { min, max } = limits();
    const height = Math.round(Math.max(min, Math.min(max, Number(value) || min)));
    reviewView.dataset.timelineHeight = String(height);
    reviewView.style.setProperty("--timeline-track-height", `${height}px`);
    reviewView.style.removeProperty("--viewer-track-height");
    reviewView.style.removeProperty("grid-template-rows");
    $("#viewerShell")?.style.removeProperty("height");
    $("#timelinePanel")?.style.removeProperty("height");
    handle.setAttribute("aria-valuemin", String(min));
    handle.setAttribute("aria-valuemax", String(max));
    handle.setAttribute("aria-valuenow", String(height));
    scheduleTimelineResizeRender(true);
    scheduleMediaFrameFit(true);
    return height;
  };
  handle.addEventListener("pointerdown", (event) => {
    if (window.innerWidth <= 760 || event.button !== 0) return;
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = Math.round($("#timelinePanel")?.getBoundingClientRect().height || 240);
    handle.classList.add("dragging");
    document.body.classList.add("timeline-resizing");
    handle.setPointerCapture?.(event.pointerId);
    const move = (moveEvent) => setHeight(startHeight - (moveEvent.clientY - startY));
    const finish = () => {
      handle.classList.remove("dragging");
      document.body.classList.remove("timeline-resizing");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  });
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowUp", "ArrowDown"].includes(event.key) || window.innerWidth <= 760) return;
    event.preventDefault();
    const current = Math.round($("#timelinePanel")?.getBoundingClientRect().height || 240);
    setHeight(current + (event.key === "ArrowUp" ? 16 : -16));
  });
  handle.addEventListener("dblclick", () => {
    delete reviewView.dataset.timelineHeight;
    reviewView.style.removeProperty("--timeline-track-height");
    reviewView.style.removeProperty("--viewer-track-height");
    reviewView.style.removeProperty("grid-template-rows");
    $("#viewerShell")?.style.removeProperty("height");
    $("#timelinePanel")?.style.removeProperty("height");
    scheduleTimelineResizeRender(true);
    scheduleMediaFrameFit(true);
  });
  window.addEventListener("resize", () => {
    if (reviewView.dataset.timelineHeight) setHeight(Number(reviewView.dataset.timelineHeight));
  });
}

function bindPortraitVideoResizer() {
  const handle = $("#portraitVideoResizer");
  const reviewView = $("#reviewView");
  if (!handle || !reviewView || handle.dataset.bound === "true") return;
  handle.dataset.bound = "true";
  handle.addEventListener("pointerdown", (event) => {
    if (window.innerWidth <= 900 || reviewView.dataset.reviewLayout !== "portrait" || event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = Math.round($("#viewerShell")?.getBoundingClientRect().width || restorePortraitVideoWidth());
    let pendingWidth = startWidth;
    let resizeFrame = null;
    handle.classList.add("dragging");
    document.body.classList.add("portrait-video-resizing");
    handle.setPointerCapture?.(event.pointerId);
    const applyPendingWidth = () => {
      resizeFrame = null;
      setPortraitVideoWidth(pendingWidth);
    };
    const move = (moveEvent) => {
      pendingWidth = startWidth - (moveEvent.clientX - startX);
      if (resizeFrame === null) resizeFrame = requestAnimationFrame(applyPendingWidth);
    };
    const finish = () => {
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      const width = setPortraitVideoWidth(pendingWidth, { persist: true });
      handle.classList.remove("dragging");
      document.body.classList.remove("portrait-video-resizing");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      if (width) scheduleTimelineResizeRender(true);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  });
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key) || window.innerWidth <= 900 || reviewView.dataset.reviewLayout !== "portrait") return;
    event.preventDefault();
    const current = Number(reviewView.dataset.portraitVideoWidth) || restorePortraitVideoWidth();
    const width = setPortraitVideoWidth(current + (event.key === "ArrowLeft" ? 16 : -16), { persist: true });
    if (width) scheduleTimelineResizeRender(true);
  });
  handle.addEventListener("dblclick", () => {
    if (reviewView.dataset.reviewLayout !== "portrait") return;
    forgetPortraitVideoWidth();
    reviewView.style.removeProperty("--portrait-video-width");
    delete reviewView.dataset.portraitVideoWidth;
    restorePortraitVideoWidth();
    scheduleTimelineResizeRender(true);
  });
  window.addEventListener("resize", () => {
    if (reviewView.dataset.reviewLayout === "portrait") restorePortraitVideoWidth();
  });
}

restorePanelLayout();
bindPanelResizers();
bindTimelineResizer();
bindPortraitVideoResizer();
requestAnimationFrame(clampPanelLayoutToViewport);
window.addEventListener("resize", clampPanelLayoutToViewport);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function applyMediaAspect(container, width, height) {
  if (!container) return;
  const mediaWidth = Number(width || 0);
  const mediaHeight = Number(height || 0);
  if (mediaWidth <= 0 || mediaHeight <= 0) return;
  const aspect = mediaWidth / mediaHeight;
  container.style.setProperty("--media-aspect", String(aspect));
  container.dataset.mediaAspect = `${mediaWidth} / ${mediaHeight}`;
  container.classList.toggle("portrait", aspect < .82);
  container.classList.toggle("square", aspect >= .82 && aspect <= 1.18);
  if (container === viewerShell) {
    syncReviewLayoutForMedia(aspect);
    scheduleMediaFrameFit(true);
  }
}

function activeMediaAspect() {
  const stored = String(viewerShell?.dataset.mediaAspect || "").split("/").map(Number);
  if (stored.length === 2 && stored[0] > 0 && stored[1] > 0) return stored[0] / stored[1];
  const decodedWidth = Number(mainVideo?.videoWidth || 0);
  const decodedHeight = Number(mainVideo?.videoHeight || 0);
  if (decodedWidth > 0 && decodedHeight > 0) return decodedWidth / decodedHeight;
  const jobWidth = Number(currentJob?.videoInfo?.width || 0);
  const jobHeight = Number(currentJob?.videoInfo?.height || 0);
  if (jobWidth > 0 && jobHeight > 0) return jobWidth / jobHeight;
  return 16 / 9;
}

function fitMediaFrame() {
  if (!viewerShell || !mediaFrame || viewerShell.offsetParent === null && document.fullscreenElement !== viewerShell) return;
  const availableWidth = Math.max(0, viewerShell.clientWidth);
  const availableHeight = Math.max(0, viewerShell.clientHeight);
  if (availableWidth < 2 || availableHeight < 2) return;
  const aspect = Math.max(.2, Math.min(5, activeMediaAspect()));
  let width = Math.min(availableWidth, availableHeight * aspect);
  let height = width / aspect;
  if (height > availableHeight) {
    height = availableHeight;
    width = height * aspect;
  }
  width = Math.max(1, Math.floor(width));
  height = Math.max(1, Math.floor(height));
  const fitKey = `${width}x${height}@${aspect.toFixed(6)}`;
  if (mediaFrame.dataset.fitKey !== fitKey) {
    mediaFrame.dataset.fitKey = fitKey;
    mediaFrame.style.width = `${width}px`;
    mediaFrame.style.height = `${height}px`;
    mediaFrame.style.setProperty("--decoded-media-aspect", String(aspect));
  }
  syncEvidencePlacement();
}

function scheduleMediaFrameFit(force = false) {
  if (force && mediaFitFrame !== null) {
    cancelAnimationFrame(mediaFitFrame);
    mediaFitFrame = null;
  }
  if (mediaFitFrame !== null) return;
  mediaFitFrame = requestAnimationFrame(() => {
    mediaFitFrame = null;
    fitMediaFrame();
  });
}

function syncTimelineVisibilityLayout() {
  const reviewView = $("#reviewView");
  if (!reviewView) return;
  const hidden = !timelinePanel || timelinePanel.classList.contains("hidden");
  reviewView.classList.toggle("timeline-hidden", hidden);
  scheduleMediaFrameFit(true);
}

function syncEvidencePlacement() {
  const evidence = $("#evidencePanel");
  if (!evidence) return;
  // Evidence now owns a stable column beside the player. Clear the legacy
  // pillar-box/overlay state so media aspect changes never move it over video.
  evidence.classList.remove(
    "evidence-in-gutter",
    "evidence-gutter-left",
    "evidence-gutter-right",
    "evidence-compact",
    "evidence-expanded",
  );
  evidence.style.removeProperty("--evidence-frame-top");
  evidence.style.removeProperty("--evidence-frame-height");
  evidence.style.removeProperty("--evidence-gutter-width");
}

function bindAdaptiveMediaLayout() {
  if (!viewerShell || !mediaFrame) return;
  if (window.ResizeObserver) {
    mediaLayoutObserver?.disconnect();
    mediaLayoutObserver = new ResizeObserver(() => scheduleMediaFrameFit());
    mediaLayoutObserver.observe(viewerShell);
    const reviewStage = $("#reviewStage");
    if (reviewStage) mediaLayoutObserver.observe(reviewStage);
    const reviewView = $("#reviewView");
    if (reviewView) mediaLayoutObserver.observe(reviewView);
  }
  if (timelinePanel && window.MutationObserver) {
    new MutationObserver(syncTimelineVisibilityLayout).observe(timelinePanel, { attributes: true, attributeFilter: ["class"] });
  }
  const evidence = $("#evidencePanel");
  if (evidence && window.MutationObserver) {
    new MutationObserver(() => scheduleMediaFrameFit()).observe(evidence, { attributes: true, attributeFilter: ["class"] });
  }
  syncTimelineVisibilityLayout();
  scheduleMediaFrameFit(true);
}

bindAdaptiveMediaLayout();

function sourcePreviewUrl(job = currentJob) {
  if (!job) return "";
  const base = String(job.previewUrl || job.sourceUrl || "").trim();
  if (!base || base === "undefined" || base === "null") return "";
  const separator = base.includes("?") ? "&" : "?";
  const assetState = job.previewReady ? "proxy" : "source";
  return `${base}${separator}asset=${assetState}&v=${encodeURIComponent(job.updatedAt || "latest")}`;
}

function stopSourcePreviewPolling() {
  clearTimeout(sourcePreviewPollTimer);
  sourcePreviewPollTimer = null;
}

function switchToReadySourcePreview() {
  if (!currentJob?.previewReady || !["source", "candidate", "segment"].includes(viewerMediaKind)) return;
  const resumeTime = Number(mainVideo.currentTime || 0);
  const wasPlaying = !mainVideo.paused;
  clearPlayerNotice();
  mainVideo.addEventListener("loadedmetadata", () => {
    mainVideo.currentTime = Math.min(Math.max(0, mainVideo.duration - .05), resumeTime);
    if (wasPlaying) safePlay();
  }, { once: true });
  setMainVideoSource(sourcePreviewUrl(currentJob));
}

function beginSourcePreviewPolling(job = currentJob, force = false) {
  stopSourcePreviewPolling();
  if (!job || job.previewReady) return;
  if (!force && isActiveJobStatus(job.status)) return;
  const jobId = job.id;
  job.previewPreparing = true;
  const poll = async () => {
    if (currentJob?.id !== jobId || !["source", "candidate", "segment"].includes(viewerMediaKind)) return;
    try {
      const state = await api(`/api/jobs/${jobId}/preview-status`);
      if (currentJob?.id !== jobId) return;
      currentJob.previewReady = Boolean(state.ready);
      currentJob.previewPreparing = Boolean(state.preparing);
      if (state.ready) {
        switchToReadySourcePreview();
        return;
      }
      if (state.error) {
        showPlayerNotice(`兼容播放代理生成失败：${state.error}`);
        return;
      }
    } catch { /* source playback can continue while the optional proxy retries */ }
    sourcePreviewPollTimer = setTimeout(poll, 2500);
  };
  sourcePreviewPollTimer = setTimeout(poll, 800);
}

function clearPlayerNotice() {
  $("#playerNotice")?.classList.add("hidden");
  $("#playerNotice p") && ($("#playerNotice p").textContent = "");
  const loader = $("#playerMediaLoader");
  if (loader) {
    loader.dataset.loaderActive = "false";
    loader.classList.add("hidden");
    clearGenerativeLoader(loader);
  }
}

function showPlayerNotice(message, title = "视频暂时无法播放") {
  const notice = $("#playerNotice");
  if (!notice) return;
  $("#playerNotice strong") && ($("#playerNotice strong").textContent = title);
  $("#playerNotice p") && ($("#playerNotice p").textContent = message);
  const loading = /正在|准备|等待.+(?:生成|完成)|切换.+代理|恢复.+预览/.test(`${title} ${message}`);
  const loader = $("#playerMediaLoader");
  if (loader) {
    loader.dataset.loaderActive = String(loading);
    loader.classList.toggle("hidden", !loading);
    if (loading) renderGenerativeLoader(loader, { kind: "image", variant: "scan", size: 84, radius: 12, label: title });
    else clearGenerativeLoader(loader);
  }
  notice.classList.remove("hidden");
}

function mediaSourceIdentity(value) {
  const source = String(value || "").trim();
  if (!source) return "";
  try {
    const url = new URL(source, window.location.href);
    // `v` only busts browser cache. A new job heartbeat used to change this
    // value and reload the exact same MP4 while it was already playing.
    url.searchParams.delete("v");
    return `${url.origin}${url.pathname}${url.search}`;
  } catch {
    return source.replace(/([?&])v=[^&]*/g, "$1").replace(/[?&]$/, "");
  }
}

function setMainVideoSource(source, { force = false } = {}) {
  if (!mainVideo) return false;
  const nextSource = String(source || "").trim();
  if (!nextSource) {
    if (mainVideo.getAttribute("src")) {
      playbackRequestToken += 1;
      mainVideoAutoplayToken += 1;
      mainVideo.removeAttribute("src");
      mainVideo.load();
      return true;
    }
    return false;
  }
  const currentSource = mainVideo.getAttribute("src") || mainVideo.currentSrc || "";
  if (!force && mediaSourceIdentity(currentSource) === mediaSourceIdentity(nextSource)) return false;
  playbackRequestToken += 1;
  mainVideoAutoplayToken += 1;
  mainVideo.src = nextSource;
  return true;
}

function browserFallbackForCurrentMedia() {
  if (!currentJob) return null;
  if (viewerMediaKind === "output" && currentOutput?.filename) {
    return {
      key: `${currentJob.id}:output:${currentOutput.filename}`,
      url: `/api/jobs/${currentJob.id}/outputs/${encodeURIComponent(currentOutput.filename)}/browser-preview`,
      label: "正在生成通用格式的成片预览…",
    };
  }
  if (["source", "candidate", "segment"].includes(viewerMediaKind)) {
    return {
      key: `${currentJob.id}:source`,
      url: `/api/jobs/${currentJob.id}/browser-preview`,
      label: "当前浏览器不支持 H.264，正在生成通用 WebM 预览…",
    };
  }
  return null;
}

async function safePlay({ allowMutedFallback = false } = {}) {
  const requestToken = ++playbackRequestToken;
  clearPlayerNotice();
  try {
    const pending = mainVideo.play();
    if (pending && typeof pending.then === "function") await pending;
    if (requestToken !== playbackRequestToken || mainVideo.paused) return false;
    return true;
  } catch (error) {
    // Changing source or pausing while play() is still pending is a normal
    // media lifecycle race, not a playback failure.  Do not show a scary
    // reload notice for the browser's AbortError in that case.
    const interrupted = error?.name === "AbortError"
      || /play\(\).*pause|interrupted by a call to pause/i.test(String(error?.message || ""));
    if (interrupted || requestToken !== playbackRequestToken) return false;
    const blocked = error?.name === "NotAllowedError";
    if (blocked && allowMutedFallback && !mainVideo.muted) {
      // Browsers generally reject programmatic playback with audio after the
      // upload request has crossed an async boundary. Start muted instead of
      // leaving a newly imported video looking broken; the player control
      // makes the muted state explicit and lets the user restore audio.
      mainVideo.muted = true;
      updatePlayerChrome();
      try {
        const retry = mainVideo.play();
        if (retry && typeof retry.then === "function") await retry;
        return requestToken === playbackRequestToken && !mainVideo.paused;
      } catch (retryError) {
        if (retryError?.name === "AbortError" || requestToken !== playbackRequestToken) return false;
      }
    }
    showPlayerNotice(
      blocked ? "浏览器阻止了带声音的自动播放，请点击“重新加载”或播放按钮继续。" : `浏览器未能开始播放：${error?.message || "未知媒体错误"}`,
      blocked ? "需要手动确认播放" : "视频播放失败",
    );
    return false;
  }
}

function requestMainVideoAutoplay() {
  if (!mainVideo?.getAttribute("src")) return;
  const autoplayToken = ++mainVideoAutoplayToken;
  const playWhenReady = () => {
    if (autoplayToken !== mainVideoAutoplayToken || !mainVideo.getAttribute("src")) return;
    safePlay({ allowMutedFallback: true });
  };
  if (mainVideo.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
    playWhenReady();
  } else {
    mainVideo.addEventListener("canplay", playWhenReady, { once: true });
  }
}

async function autoplayLocalPreview(video) {
  if (!video?.src) return;
  video.muted = false;
  try {
    const pending = video.play();
    if (pending && typeof pending.then === "function") await pending;
  } catch (error) {
    if (error?.name !== "NotAllowedError") return;
    // The file picker normally provides a user gesture, but stricter browser
    // policies may still require muted autoplay.
    video.muted = true;
    try { await video.play(); } catch { /* native controls remain available */ }
  }
}

function formatTime(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor(value % 3600 / 60);
  const rest = (value % 60).toFixed(1).padStart(4, "0");
  return hours
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${rest}`
    : `${String(minutes).padStart(2, "0")}:${rest}`;
}

function formatClock(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor(value % 3600 / 60);
  const rest = String(value % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

function progressContract(job = currentJob) {
  const facts = job?.progressFacts && typeof job.progressFacts === "object" ? job.progressFacts : {};
  const workflow = facts.workflow && typeof facts.workflow === "object" ? facts.workflow : {};
  const stage = facts.stage && typeof facts.stage === "object" ? facts.stage : {};
  const timing = facts.timing && typeof facts.timing === "object" ? facts.timing : {};
  const activity = facts.activity && typeof facts.activity === "object" ? facts.activity : {};
  return { workflow, stage, timing, activity };
}

function processingElapsedSeconds(job = currentJob) {
  if (!job) return 0;
  const timing = progressContract(job).timing;
  const hasPersistedTiming = timing.processingTimingVersion != null || job.processingTimingVersion != null;
  if (!hasPersistedTiming && !isPipelineRunningStatus(job.status)) return null;
  const persisted = Number(timing.processingElapsedSeconds ?? job.processingElapsedSeconds ?? 0);
  const base = Number.isFinite(persisted) ? Math.max(0, persisted) : 0;
  if (!isPipelineRunningStatus(job.status)) return base;
  const activeSince = Date.parse(String(timing.processingActiveSince || job.processingActiveSince || ""));
  return Number.isFinite(activeSince)
    ? base + Math.max(0, (Date.now() - activeSince) / 1000)
    : base;
}

function processingElapsedLabel(job = currentJob) {
  const seconds = processingElapsedSeconds(job);
  if (seconds == null) return "处理用时不可用";
  const elapsed = formatClock(seconds);
  return isPipelineRunningStatus(job?.status) ? `正在处理 ${elapsed}` : `处理用时 ${elapsed}`;
}

function workflowProgress(job = currentJob) {
  const raw = progressContract(job).workflow.fraction;
  const fallback = job?.progress;
  const value = Number(raw === null || raw === undefined ? fallback : raw);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
}

function stageDisplayMode(job = currentJob) {
  const contractMode = String(progressContract(job).stage.mode || "");
  if (["determinate", "indeterminate", "finalizing", "completed"].includes(contractMode)) return contractMode;
  const legacyMode = String(job?.progressMode || "");
  if (legacyMode === "determinate") return "determinate";
  if (String(job?.etaMode || "") === "finalizing" || String(job?.etaMode || "") === "quality_check") return "finalizing";
  if (legacyMode === "completed" || job?.status === "completed") return "completed";
  return "indeterminate";
}

function progressEtaText(job, waiting = false) {
  if (job?.status === "queued") return "等待队列，不计入处理用时";
  if (job?.status === "cancelling") return "停止请求已提交，正在收尾";
  if (job?.status === "awaiting_model_decision") return "等待你选择重试、降级继续或取消";
  const timing = progressContract(job).timing;
  const rawEta = timing.etaSeconds ?? job?.etaSeconds;
  const eta = Number(rawEta);
  const etaMode = String(timing.etaMode || job?.etaMode || "");
  if (stageDisplayMode(job) === "completed" && job?.status === "running") return "正在进入下一阶段";
  if (etaMode === "finalizing") return "正在整理标点、情绪和说话人";
  if (etaMode === "unavailable") return "本阶段耗时取决于模型响应";
  if (etaMode === "encoding") return "FFmpeg 实时编码中";
  if (etaMode === "quality_check") return "正在检查视频完整性";
  if (rawEta !== null && rawEta !== undefined && Number.isFinite(eta)) {
    const lastUpdate = Date.parse(String(timing.lastProgressAt || job?.lastProgressAt || job?.updatedAt || ""));
    const liveEta = Number.isFinite(lastUpdate) && isPipelineRunningStatus(job?.status)
      ? Math.max(0, eta - (Date.now() - lastUpdate) / 1000)
      : Math.max(0, eta);
    if (liveEta < 1) return etaMode === "stage_average" ? "本阶段即将完成" : "即将进入下一阶段";
    return `${etaMode === "stage_average" ? "本阶段约" : "预计剩余约"} ${formatClock(liveEta)}`;
  }
  const stage = progressContract(job).stage;
  const completed = Number(stage.completed ?? job?.stageCompleted);
  const total = Number(stage.total ?? job?.stageTotal);
  if (Number.isFinite(completed) && Number.isFinite(total) && total > 0) {
    const unit = String(stage.unit || job?.stageUnit || "项");
    if (completed >= total) return "本项计数已完成 · 正在进入下一步";
    if (completed > 0) return "正在采集本阶段耗时";
    const firstResult = unit === "%" ? "首个进度样本" : `首${unit}`;
    return `等待${firstResult}结果`;
  }
  return waiting ? "模型处理中 · 暂无耗时样本" : "等待当前阶段结果";
}

function stageProgressFact(job, fallbackPercent = 0, waiting = false) {
  if (job?.status === "queued") return "尚未开始处理";
  if (job?.status === "cancelling") return "正在停止当前任务";
  if (job?.status === "awaiting_model_decision") return "等待处理模型阶段";
  const { stage, timing } = progressContract(job);
  const etaMode = String(timing.etaMode || job?.etaMode || "");
  const mode = stageDisplayMode(job);
  if (etaMode === "encoding") return `编码 ${fallbackPercent}%`;
  if (etaMode === "quality_check") return "正在检查成片";
  if (mode === "completed") return "当前阶段已完成";
  const completed = Number(stage.completed ?? job?.stageCompleted);
  const total = Number(stage.total ?? job?.stageTotal);
  if (mode === "finalizing") {
    if (Number.isFinite(completed) && Number.isFinite(total) && total > 0) {
      const unit = String(stage.unit || job?.stageUnit || "项");
      return `已处理 ${completed}/${total} ${unit} · 正在整理结果`;
    }
    return "正在整理结果";
  }
  if (Number.isFinite(completed) && Number.isFinite(total) && total > 0) {
    const unit = String(stage.unit || job?.stageUnit || "项");
    return unit === "%" ? `已处理 ${completed}%` : `已完成 ${completed}/${total} ${unit}`;
  }
  return waiting ? "模型处理中 · 暂无可靠百分比" : `阶段 ${fallbackPercent}%`;
}

function measuredStageProgress(job) {
  const contract = progressContract(job).stage;
  const raw = contract.fraction ?? job?.stageProgress;
  if (raw === null || raw === undefined || raw === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : null;
}

function stageProgressIsDeterminate(job) {
  if (stageDisplayMode(job) !== "determinate") return false;
  const stage = progressContract(job).stage;
  const total = Number(stage.total ?? job?.stageTotal);
  const seconds = Number(stage.totalSeconds ?? job?.stageTotalSeconds);
  return measuredStageProgress(job) !== null
    && ((Number.isFinite(total) && total > 0) || (Number.isFinite(seconds) && seconds > 0));
}

const speechEmotionLabels = {
  happy: "开心", sad: "悲伤", angry: "愤怒", fearful: "紧张",
  disgusted: "厌恶", surprised: "惊讶", neutral: "中性", unknown: "未知情绪",
};
const speechEventLabels = {
  applause: "掌声", laughter: "笑声", cry: "哭声", cough: "咳嗽",
  sneeze: "喷嚏", breath: "呼吸", bgm: "背景音乐", speech: "对白",
};

function audioEvidenceLabels(evidence) {
  if (!evidence) return [];
  return [
    ...(evidence.speakers || []),
    ...(evidence.emotions || []).map((item) => speechEmotionLabels[item] || item),
    ...(evidence.audioEvents || []).map((item) => speechEventLabels[item] || item),
  ].filter(Boolean).slice(0, 5);
}

function audioEvidenceMarkup(evidence) {
  const labels = audioEvidenceLabels(evidence);
  return labels.length ? `<em class="speech-evidence">${labels.map((item) => `<i>${escapeHtml(item)}</i>`).join("")}</em>` : "";
}

function saveTimelineLayerPreferences() {
  try {
    localStorage.setItem(timelineLayerStorageKey, JSON.stringify({
      cuts: timelineCutsVisible,
    }));
  } catch { /* storage may be disabled */ }
}

function updateTimelineLayerButtons() {
  const cutsButton = $("#timelineCutsToggle");
  cutsButton?.classList.toggle("active", timelineCutsVisible);
  cutsButton?.setAttribute("aria-pressed", String(timelineCutsVisible));
}

function itemSpeakers(item) {
  const evidence = item?.audioEvidence || {};
  const speakers = Array.isArray(evidence.speakers) ? evidence.speakers : (evidence.speakers ? [evidence.speakers] : []);
  const turns = Array.isArray(evidence.speakerTurns) ? evidence.speakerTurns : [];
  return [...new Set([...speakers, ...turns.map((turn) => turn?.speaker), item?.speaker].filter(Boolean).map(String))];
}

function seekTimeline(second) {
  const value = Math.max(0, Number(second) || 0);
  if (currentJob) setTimelineView(Math.max(0, value - 20), value + 20);
  if (timelineOutputAxisActive()) {
    seekCurrentMediaTime(value, { autoplay: false });
    return;
  }
  if (viewerMediaKind === "output") showSource();
  if (mainVideo.readyState >= 1) mainVideo.currentTime = Math.min(Math.max(0, mainVideo.duration - 0.05), value);
  else mainVideo.addEventListener("loadedmetadata", () => { mainVideo.currentTime = value; }, { once: true });
  updateTimelinePlayhead();
}

function compositionTransitionOverlap(segments, index) {
  if (!Array.isArray(segments) || index <= 0 || index >= segments.length) return 0;
  const current = segments[index] || {};
  const transition = current.transitionIn || {};
  if (!["dissolve", "fade_black"].includes(transition.type)) return 0;
  const previous = segments[index - 1] || {};
  const previousDuration = segmentOutputDuration(previous);
  const currentDuration = segmentOutputDuration(current);
  if (!previousDuration || !currentDuration) return 0;
  const requested = Math.max(.08, Number(transition.duration) || .18);
  return Math.max(0, Math.min(.4, requested, previousDuration / 3, currentDuration / 3));
}

function segmentOutputDuration(segment) {
  const sourceStart = Math.max(0, Number(segment?.start) || 0);
  const sourceEnd = Math.max(sourceStart, Number(segment?.end) || sourceStart);
  const removed = (Array.isArray(segment?.silenceCuts) ? segment.silenceCuts : []).reduce((sum, item) => {
    const start = Math.max(sourceStart, Number(item?.start) || sourceStart);
    const end = Math.min(sourceEnd, Number(item?.end) || start);
    const retained = Math.max(0, Math.min(end - start, Number(item?.retained) || 0));
    return sum + Math.max(0, end - start - retained);
  }, 0);
  return Math.max(0, sourceEnd - sourceStart - removed) / Math.max(1, Number(segment?.playbackRate) || 1);
}

function segmentOutputOffsetForSource(segment, sourceTime) {
  const start = Math.max(0, Number(segment?.start) || 0);
  const end = Math.max(start, Number(segment?.end) || start);
  const target = Math.max(start, Math.min(end, Number(sourceTime) || start));
  const removedBefore = (Array.isArray(segment?.silenceCuts) ? segment.silenceCuts : []).reduce((sum, item) => {
    const left = Math.max(start, Number(item?.start) || start);
    const right = Math.min(target, Number(item?.end) || left);
    const retained = Math.max(0, Math.min(right - left, Number(item?.retained) || 0));
    return sum + Math.max(0, right - left - retained);
  }, 0);
  return Math.max(0, target - start - removedBefore) / Math.max(1, Number(segment?.playbackRate) || 1);
}

function compositionSchedule(composed) {
  const segments = Array.isArray(composed?.segments) ? composed.segments : [];
  let composedEnd = 0;
  return segments.map((segment, index) => {
    const sourceStart = Math.max(0, Number(segment.start) || 0);
    const sourceEnd = Math.max(sourceStart, Number(segment.end) || sourceStart);
    const sourceDuration = Math.max(0, sourceEnd - sourceStart);
    const overlap = compositionTransitionOverlap(segments, index);
    const outputStart = Math.max(0, composedEnd - overlap);
    const outputDuration = segmentOutputDuration(segment);
    const outputEnd = outputStart + outputDuration;
    composedEnd = outputEnd;
    return { segment, index, sourceStart, sourceEnd, sourceDuration, outputDuration, overlap, outputStart, outputEnd };
  });
}

function compositionTimeForSource(composed, segmentIndex, sourceTime) {
  const entry = compositionSchedule(composed)[Number(segmentIndex)];
  if (!entry) return 0;
  return entry.outputStart + segmentOutputOffsetForSource(entry.segment, sourceTime);
}

function compositionSourceTimeAtOutputTime(composed, outputTime) {
  const schedule = compositionSchedule(composed);
  const time = Math.max(0, Number(outputTime) || 0);
  // During a dissolve both ranges are visible. Prefer the incoming segment so
  // the source marker follows the image that is taking over the frame.
  const entry = [...schedule].reverse().find((item) => time >= item.outputStart - .001)
    || schedule[0];
  if (!entry) return 0;
  const targetOffset = Math.max(0, Math.min(entry.outputDuration, time - entry.outputStart));
  let low = entry.sourceStart;
  let high = entry.sourceEnd;
  // Silence removal and playback-rate changes make the mapping piecewise.
  // Invert the existing monotonic source->output mapping instead of assuming
  // one output second always equals one source second.
  for (let iteration = 0; iteration < 24; iteration += 1) {
    const middle = (low + high) / 2;
    if (segmentOutputOffsetForSource(entry.segment, middle) < targetOffset) low = middle;
    else high = middle;
  }
  return Math.max(entry.sourceStart, Math.min(entry.sourceEnd, (low + high) / 2));
}

function seekCurrentMediaTime(second, { autoplay = true } = {}) {
  const target = Math.max(0, Number(second) || 0);
  const requestedSource = mediaSourceIdentity(mainVideo?.getAttribute("src") || mainVideo?.currentSrc || "");
  const apply = () => {
    const activeSource = mediaSourceIdentity(mainVideo?.getAttribute("src") || mainVideo?.currentSrc || "");
    if (requestedSource && activeSource && requestedSource !== activeSource) return;
    const duration = Number(mainVideo.duration);
    const bounded = Number.isFinite(duration) && duration > 0
      ? Math.min(Math.max(0, duration - .05), target)
      : target;
    mainVideo.currentTime = bounded;
    updateTimelinePlayhead();
    if (autoplay) safePlay();
  };
  if (mainVideo.readyState >= 1) apply();
  else mainVideo.addEventListener("loadedmetadata", apply, { once: true });
}

function seekComposedMedia(composed, segmentIndex, sourceTime, kind = "output") {
  const entry = compositionSchedule(composed)[Number(segmentIndex)];
  if (!entry) return;
  const sourceTarget = Math.max(entry.sourceStart, Math.min(entry.sourceEnd, Number(sourceTime) || entry.sourceStart));
  const outputTarget = compositionTimeForSource(composed, entry.index, sourceTarget);
  if (currentJob) {
    const timelineTarget = timelineOutputAxisActive() ? outputTarget : sourceTarget;
    setTimelineView(Math.max(0, timelineTarget - 20), timelineTarget + 20);
  }
  if (kind === "event") {
    const sameEvent = viewerMediaKind === "event" && currentEventGroup
      && String(currentEventGroup.id || "") === String(composed?.id || "");
    if (sameEvent) seekCurrentMediaTime(outputTarget);
    else previewEventGroup(composed, { seekTime: outputTarget });
    return;
  }
  const sameOutput = viewerMediaKind === "output" && currentOutput
    && String(currentOutput.filename || "") === String(composed?.filename || "");
  if (sameOutput) seekCurrentMediaTime(outputTarget);
  else selectOutput(composed.filename, true, outputTarget);
}

function speakerMatches(item) {
  return timelineSpeakerFilter === "all" || itemSpeakers(item).includes(timelineSpeakerFilter);
}

function updateSpeakerFilterOptions(job = currentJob) {
  const select = $("#speakerFilter");
  if (!select || !job) return;
  const speakers = new Set();
  (job.candidates || []).forEach((item) => itemSpeakers(item).forEach((speaker) => speakers.add(speaker)));
  (job.eventGroups || []).forEach((group) => (group.segments || []).forEach((item) => itemSpeakers(item).forEach((speaker) => speakers.add(speaker))));
  (timelineTranscript || []).forEach((item) => item.speaker && speakers.add(String(item.speaker)));
  const values = ["all", ...[...speakers].sort()];
  if (!values.includes(timelineSpeakerFilter)) timelineSpeakerFilter = "all";
  select.innerHTML = values.map((value) => `<option value="${escapeHtml(value)}">${value === "all" ? "全部" : escapeHtml(value)}</option>`).join("");
  select.value = timelineSpeakerFilter;
}

function renderTimelineInsights(job = currentJob) {
  const panel = $("#timelineInsights");
  const list = $("#timelineInsightsList");
  if (!panel || !list || !job) return;
  const insights = [];
  const contentMode = String(job.taskMode || "") === "content_extract";
  (job.eventGroups || []).filter((group) => group.assemblyStrategy !== "manual" && !/时间轴选区高光|用户从时间轴创建/.test(String(group.title || group.summary || ""))).forEach((group) => {
    const first = group.segments?.[0];
    if (first) insights.push({ type: contentMode ? "内容片段" : "事件编排", title: group.title, reason: group.summary, score: group.score, start: first.start, end: group.segments[group.segments.length - 1]?.end || first.end, _speakers: group.segments.flatMap(itemSpeakers) });
  });
  (job.candidates || []).forEach((candidate) => insights.push({ type: contentMode ? "匹配候选" : "高光候选", title: candidate.title, reason: candidate.reason, score: candidate.score, start: candidate.start, end: candidate.end, _speakers: itemSpeakers(candidate) }));
  const visible = insights.filter((item) => timelineSpeakerFilter === "all" || item._speakers?.includes(timelineSpeakerFilter)).slice(0, 10);
  panel.classList.toggle("hidden", !visible.length);
  const count = $("#timelineInsightsCount");
  if (count) count.textContent = `${visible.length} 项`;
  list.innerHTML = visible.map((item) => `<button type="button" class="timeline-insight" data-insight-start="${Number(item.start) || 0}" data-insight-end="${Number(item.end) || 0}"><span>${escapeHtml(item.type)}</span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.reason || "模型根据多模态证据判定")}</small><b>${Math.round(Number(item.score) || 0)}</b></button>`).join("");
  list?.querySelectorAll("[data-insight-start]").forEach((button) => button.addEventListener("click", () => seekTimeline(Number(button.dataset.insightStart))));
}

function taskWorkflowForJob(job = currentJob) {
  const contentMode = String(job?.taskMode || "highlight") === "content_extract";
  const stage = String(job?.stage || "queued");
  const status = String(job?.status || "");
  const publicSteps = contentMode && Array.isArray(job?.workflow?.steps) ? job.workflow.steps : [];
  if (publicSteps.length) {
    const currentIndex = publicSteps.findIndex((item) => item.state === "current");
    const complete = publicSteps.every((item) => item.state === "complete");
    return {
      contentMode,
      stepItems: publicSteps,
      steps: publicSteps.map((item) => item.label),
      currentIndex: currentIndex >= 0 ? currentIndex : (complete ? publicSteps.length : 0),
      complete,
    };
  }
  const steps = contentMode
    ? ["读取素材", "识别对白", "建立轻量索引", "搜索内容", "局部画面复检", "等待确认"]
    : ["读取素材", "理解视听内容", "发现候选", "精修镜头", "组织事件", "生成版本"];
  const contentStageIndex = {
    queued: 0, starting: 0, probing: 0,
    audio_analysis: 1, speech_recognition: 1, speech_analysis: 1, content_transcription: 1,
    content_sampling: 2, content_indexing: 2, content_recognition: 2,
    content_index_ready: 3, content_search: 3,
    content_active_speaker: 3,
    content_refinement: 4,
    content_search_ready: 5, awaiting_content_confirmation: 5,
    rendering: 6, render: 6, completed: 6,
  };
  const highlightStageIndex = {
    queued: 0, starting: 0, probing: 0,
    audio_analysis: 1, speech_recognition: 1, speech_analysis: 1,
    sampling: 2, content_classification: 2, coarse_vlm: 2,
    refine_vlm: 3,
    event_grouping: 4, event_director: 4,
    edit_planning: 5, edit_planning_complete: 5, rendering: 5, render: 5,
    auto_composition: 5, awaiting_confirmation: 5, completed: 6,
  };
  let currentIndex = (contentMode ? contentStageIndex : highlightStageIndex)[stage];
  if (currentIndex === undefined) currentIndex = 0;
  if (contentMode && status === "awaiting_content_confirmation") currentIndex = 5;
  if (!contentMode && status === "awaiting_confirmation") currentIndex = 5;
  if (status === "completed") currentIndex = steps.length;
  return { contentMode, steps, currentIndex, complete: currentIndex >= steps.length };
}

function workflowStepDetails(job, workflow) {
  const recognition = job?.recognition || {};
  const counts = recognition.counts || {};
  const search = job?.contentSearch || {};
  if (workflow.contentMode) {
    const scan = search.scanProgress || {};
    const searchDetail = Number(scan.totalBatches || 0) > 0
      ? `${Number(scan.processedBatches || 0)}/${Number(scan.totalBatches)} 批 · 暂找到 ${Number(scan.provisionalCandidateCount || 0)} 段`
      : `${Number(search.retrievalStats?.localRecallCount || 0)} 条索引召回`;
    if (workflow.stepItems?.length) {
      const details = {
        source: `媒体 ${job?.filename || "当前视频"}`,
        capability_speech: `${Number(counts.speech || job?.transcript?.length || 0)} 个对白单元`,
        capability_visual: `${Number(counts.shots || 0)} 个镜头画面`,
        capability_ocr: `${Number(counts.ocr || 0)} 条屏幕文字`,
        capability_audio: `${Number(counts.audio || 0)} 条声音证据`,
        capability_person: `${Number(counts.persons || 0)} 个人物轨迹`,
        search: searchDetail,
        review: `${Number(search.candidateCount || search.candidates?.length || 0)} 个匹配片段`,
        render: `${jobOutputCount(job)} 个内容视频版本`,
      };
      return workflow.stepItems.map((item) => details[item.id] || "按需执行");
    }
    return [`媒体 ${job?.filename || "当前视频"}`, searchDetail, `${Number(search.candidateCount || search.candidates?.length || 0)} 个候选待确认`];
  }
  const outputCount = jobOutputCount(job);
  return [
    `媒体 ${job?.filename || "当前视频"}`,
    `${job?.speechAnalysis?.segments?.length || job?.transcript?.length || 0} 个视听片段`,
    `${job?.candidates?.length || 0} 个候选`,
    `${job?.candidates?.length || 0} 个精修镜头`,
    `${job?.eventGroups?.length || 0} 个事件`,
    `${outputCount} 个版本`,
  ];
}

function renderAnalysisActivity(job = currentJob) {
  const body = $("#analysisActivityBody");
  const summary = $("#analysisActivitySummary");
  if (!body || !summary || !job) return;
  const stage = String(job.stage || "");
  const workflow = taskWorkflowForJob(job);
  const details = workflowStepDetails(job, workflow);
  const steps = workflow.steps.map((label, index) => [label, workflow.complete || index < workflow.currentIndex, details[index]]);
  const done = steps.filter((step) => step[1]).length;
  summary.textContent = job.error ? "出现错误" : `${done}/${steps.length} 已完成`;
  body.innerHTML = `<div class="activity-current">${escapeHtml(job.detail || stage || "等待任务数据")}</div>${steps.map(([label, complete, detail], index) => {
    const current = !workflow.complete && index === workflow.currentIndex;
    const failed = Boolean(job.error) && current;
    return `<div class="activity-step ${complete ? "done" : current ? "current" : failed ? "failed" : "waiting"}"><i>${complete ? "✓" : current ? "•" : "·"}</i><span><b>${label}</b><small>${detail}</small></span></div>`;
  }).join("")}${job.error ? `<div class="activity-error">${escapeHtml(job.error)}</div>` : ""}`;
}

function analysisPhase(stage, status) {
  if (status === "completed") return 3;
  if (["rendering", "render", "edit_planning", "auto_composition"].includes(stage)) return 2;
  if (["audio_analysis", "speech_recognition", "speech_analysis", "content_transcription", "content_sampling", "content_indexing", "content_recognition", "content_index_ready", "content_search", "content_active_speaker", "content_refinement", "content_search_ready", "content_classification", "coarse_vlm", "sampling", "refine_vlm", "event_grouping", "event_director", "awaiting_confirmation"].includes(stage)) return 1;
  return 0;
}

function thinkingConfigForJob(job) {
  if (!job) return null;
  if (["briefing", "brief_confirmation"].includes(job.status)) {
    return { state: "composing", label: "正在整理剪辑需求，等待确认后开始分析" };
  }
  if (job.status === "cancelling") {
    return { state: "solving", label: "正在停止当前分析任务" };
  }
  if (job.status === "awaiting_model_decision") {
    return { state: "solving", label: "模型阶段需要选择重试或降级" };
  }
  if (job.status !== "running") return null;
  const stage = String(job.stage || "");
  if (["queued", "starting", "probing"].includes(stage)) {
    return { state: "connecting", label: "正在读取素材并准备分析环境" };
  }
  if (stage === "audio_analysis") {
    return { state: "listening", label: "正在分析音频、语音能量与声音事件" };
  }
  if (["speech_recognition", "speech_analysis"].includes(stage)) {
    return { state: "listening", label: "正在理解对白、情绪与声音事件" };
  }
  if (stage === "content_transcription") {
    return { state: "listening", label: "正在建立可检索的对白与匿名说话人索引" };
  }
  if (["content_sampling", "content_indexing", "content_recognition"].includes(stage)) {
    return { state: "searching", label: stage === "content_recognition" ? "正在建立本次检索需要的内容索引" : "正在准备本次检索需要的素材证据" };
  }
  if (["content_index_ready", "content_search", "content_active_speaker", "content_refinement"].includes(stage)) {
    return { state: "solving", label: "正在执行本次所需分析、检索证据并精修匹配边界" };
  }
  if (["sampling", "content_classification", "coarse_vlm"].includes(stage)) {
    return { state: "searching", label: stage === "content_classification" ? "正在识别内容类型与叙事结构" : "正在通看全片并寻找精彩瞬间" };
  }
  if (stage === "refine_vlm") {
    return { state: "solving", label: "正在判断候选价值并精修镜头边界" };
  }
  if (["event_grouping", "event_director"].includes(stage)) {
    return { state: "shaping", label: "正在把精彩镜头编排成事件高光" };
  }
  if (["rendering", "render"].includes(stage)) {
    return { state: "composing", label: String(job.taskMode || "") === "content_extract" ? "正在合成已确认内容并检查输出" : "正在合成高光成片并检查输出" };
  }
  if (stage === "edit_planning") {
    return { state: "solving", label: "LLM 正在设计局部镜头、叙事结构与排列顺序" };
  }
  return null;
}

function updatePipelineThinkingOrb(job) {
  const element = $("#pipelineThinkingOrb");
  if (!element) return;
  const config = thinkingConfigForJob(job);
  element.classList.toggle("hidden", !config);
  if (!config) {
    window.ThinkingOrbsBridge?.clear(element);
    return;
  }
  element.dataset.orbState = config.state;
  element.dataset.orbLabel = config.label;
  window.ThinkingOrbsBridge?.render(element, { ...config, size: 40, theme: "light" });
}

function updateDirectorThinkingOrb(job = currentJob) {
  const element = $("#directorThinkingOrb");
  if (!element) return;
  const active = thinkingConfigForJob(job);
  const config = active || (job?.status === "briefing"
    ? { state: "composing", label: "正在理解剪辑需求" }
    : { state: "shaping", label: job ? "等待下一步操作" : "等待素材" });
  element.dataset.orbState = config.state;
  element.dataset.orbLabel = config.label;
  window.ThinkingOrbsBridge?.render(element, { ...config, size: 30, theme: "light" });
}

function updateAnalysisConsole(job) {
  const percent = Math.round((Number(job.progress) || 0) * 100);
  const detailMatch = String(job.detail || "").match(/(\d+(?:\.\d+)?)\s*%/);
  const rawStageProgress = measuredStageProgress(job);
  const stageFraction = rawStageProgress !== null
    ? rawStageProgress
    : detailMatch ? Number(detailMatch[1]) / 100 : 0;
  const stagePercent = Math.round(Math.max(0, Math.min(1, stageFraction)) * 100);
  const rendering = job.status === "running" && ["rendering", "render"].includes(String(job.stage || ""));
  const activePipeline = isPipelineRunningStatus(job.status);
  const determinate = stageProgressIsDeterminate(job);
  const waiting = activePipeline && !determinate;
  updateJobElapsedClock(job);
  const progressOrb = $("#progressOrb");
  progressOrb?.style.setProperty("--progress", `${percent}%`);
  progressOrb?.classList.toggle("rendering-mode", rendering);
  // Keep the orb alive during every active analysis stage. Previously only
  // rendering rotated it, so refine_vlm (for example 52%) looked frozen even
  // while the worker was advancing through candidates.
  progressOrb?.classList.toggle("active-mode", activePipeline && !rendering);
  const activeEarlyStage = ["queued", "starting", "probing", "audio_analysis", "speech_recognition", "speech_analysis"].includes(String(job.stage || ""));
  const percentElement = $("#jobPercent");
  if (percentElement) percentElement.textContent = rendering
    ? `合成中 · ${stagePercent}%`
    : waiting
      ? "处理中"
      : job.status === "running" && activeEarlyStage
      ? `总体 ${percent}% · 阶段 ${stagePercent}%`
      : `${percent}%`;
  $("#jobProgress")?.classList.toggle("indeterminate", waiting || rendering);
  $("#jobProgress")?.classList.toggle("active", activePipeline);
  $("#jobProgress")?.classList.toggle("waiting", waiting);
  const stageProgressElement = $("#jobStageProgress");
  if (stageProgressElement) {
    const countText = stageProgressFact(job, stagePercent, waiting);
    const completedSeconds = Number(job.stageCompletedSeconds);
    const totalSeconds = Number(job.stageTotalSeconds);
    stageProgressElement.textContent = Number.isFinite(completedSeconds) && Number.isFinite(totalSeconds) && totalSeconds > 0
      ? `${countText} · ${completedSeconds.toFixed(1)} / ${totalSeconds.toFixed(1)} 秒`
      : countText;
  }
  const modelElement = $("#jobModel");
  if (modelElement) modelElement.textContent = job.model || "系统";
  const etaElement = $("#jobEta");
  if (etaElement) etaElement.textContent = progressEtaText(job, waiting);
  if ($("#jobDetail")) $("#jobDetail").textContent = job.currentAction || job.detail || job.stage || "准备中";
  $("#jobStatus")?.classList.toggle("waiting-mode", waiting);
  const workflow = taskWorkflowForJob(job);
  const stageList = $("#jobStageList");
  if (stageList) {
    const signature = `${workflow.contentMode ? "content" : "highlight"}:${workflow.steps.join("|")}`;
    if (stageList.dataset.workflowSignature !== signature) {
      stageList.dataset.workflowSignature = signature;
      stageList.innerHTML = workflow.steps.map((label) => `<li><i></i><span>${label}</span></li>`).join("");
    }
    stageList.querySelectorAll("li").forEach((item, index) => {
      item.classList.toggle("done", workflow.complete || index < workflow.currentIndex);
      item.classList.toggle("current", !workflow.complete && index === workflow.currentIndex && !["failed", "cancelled", "awaiting_model_decision"].includes(job.status));
    });
  }
  updatePipelineThinkingOrb(job);
}

function updateJobElapsedClock(job = currentJob) {
  const elapsedElement = $("#jobElapsed");
  if (!elapsedElement || !job) return;
  elapsedElement.textContent = processingElapsedLabel(job);
}

function renderAnalysisDecision(job) {
  const container = $("#analysisDecision");
  const consolePanel = $("#jobStatus");
  if (!container || !consolePanel) return;
  const pending = job.status === "awaiting_model_decision" ? job.pendingDecision : null;
  consolePanel.classList.toggle("decision-mode", Boolean(pending));
  container.classList.toggle("hidden", !pending);
  if (!pending) {
    container.innerHTML = "";
    return;
  }
  const speechStage = pending.stage === "speech_analysis";
  const reason = String(pending.error || "当前阶段没有返回可用结果");
  const retryLabel = speechStage ? "重试语音分析" : "重试当前阶段";
  const fallbackLabel = speechStage ? "继续视觉分析" : "降级继续";
  const fallbackTitle = speechStage
    ? "跳过语音辅助，继续使用视觉模型完成高光分析"
    : "使用当前阶段的降级规则继续分析";
  const guidance = speechStage
    ? "语音仅用于辅助判断，不影响继续进行视觉高光分析。"
    : "已完成的画面和分析检查点均已保留。";
  const actions = speechStage
    ? `<button type="button" class="primary" data-model-decision="fallback" title="${escapeHtml(fallbackTitle)}">${fallbackLabel}</button><button type="button" data-model-decision="retry">${retryLabel}</button>`
    : `<button type="button" class="primary" data-model-decision="retry">${retryLabel}</button><button type="button" class="warning" data-model-decision="fallback" title="${escapeHtml(fallbackTitle)}">${fallbackLabel}</button>`;
  container.innerHTML = `<p><b>${escapeHtml(pending.stageLabel || "模型阶段")}未完成。</b> ${guidance}</p><small class="analysis-decision-reason"><b>原因</b>${escapeHtml(reason)}</small>${actions}<button type="button" data-model-decision="cancel">取消任务</button>`;
  container?.querySelectorAll("[data-model-decision]").forEach((button) => button.addEventListener("click", () => resolveModelDecision(button.dataset.modelDecision)));
}

async function resolveModelDecision(action) {
  const interrupted = currentJob?.status === "failed" && currentJob?.stage === "interrupted";
  if (!currentJob || (currentJob.status !== "awaiting_model_decision" && !interrupted) || actionBusy) return;
  const actionToken = captureJobAction();
  const pending = currentJob.pendingDecision || {};
  const speechStage = pending.stage === "speech_analysis";
  const labels = {
    retry: speechStage ? "重新运行语音分析？" : "重试当前模型阶段？",
    fallback: speechStage ? "跳过语音辅助，继续视觉分析？" : "按降级规则继续？",
    cancel: "取消当前任务？",
  };
  const details = [
    pending.error ? `失败原因：${pending.error}` : "当前阶段没有返回可用结果",
    "已完成的画面和分析检查点会保留",
    speechStage && action === "fallback"
      ? "视觉模型会继续分析画面；本次结果不使用对白、情绪、声音事件和说话人信息"
      : "当前操作只影响未完成阶段",
  ];
  if (!await requestActionConfirmation({ title: "分析阶段需要处理", summary: labels[action], details })) return;
  actionBusy = true;
  $("#analysisDecision")?.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/analysis-decision`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }),
    });
    if (!commitJobAction(job, actionToken)) return;
    if (jobNeedsPolling(job)) pollJob();
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

function updatePlayerChrome() {
  const duration = Number(mainVideo.duration || 0);
  const current = Number(mainVideo.currentTime || 0);
  const play = $("#playerPlay");
  const previous = $("#playerPrevious");
  const next = $("#playerNext");
  const mute = $("#playerMute");
  const fullscreen = $("#playerFullscreen");
  const viewerShell = $("#viewerShell");
  const clock = $("#playerClock");
  const seek = $("#playerSeek");
  const segmentNavigationAvailable = Boolean(currentJob?.candidates?.length);
  const playbackAvailable = Boolean(currentJob && (mainVideo.currentSrc || mainVideo.src));
  if (play) {
    const playing = !mainVideo.paused;
    play.dataset.state = playing ? "playing" : "paused";
    play.dataset.tooltip = playing ? "暂停" : "播放";
    play.setAttribute("aria-label", playing ? "暂停" : "播放");
    play.disabled = !playbackAvailable;
    play.setAttribute("aria-disabled", String(!playbackAvailable));
    play.textContent = "";
  }
  [previous, next].forEach((button) => {
    if (!button) return;
    button.disabled = !segmentNavigationAvailable;
    button.setAttribute("aria-disabled", String(!segmentNavigationAvailable));
  });
  if (mute) {
    const muted = mainVideo.muted || mainVideo.volume === 0;
    mute.dataset.state = muted ? "muted" : "on";
    mute.dataset.tooltip = muted ? "取消静音" : "静音";
    mute.setAttribute("aria-label", muted ? "取消静音" : "静音");
    mute.setAttribute("aria-pressed", String(muted));
  }
  if (fullscreen) {
    const active = Boolean(viewerShell && document.fullscreenElement === viewerShell);
    fullscreen.dataset.state = active ? "exit" : "enter";
    fullscreen.dataset.tooltip = active ? "退出全屏" : "进入全屏";
    fullscreen.setAttribute("aria-label", active ? "退出全屏" : "进入全屏");
    fullscreen.setAttribute("aria-pressed", String(active));
  }
  if (clock) clock.textContent = `${formatClock(current)} / ${formatClock(duration)}`;
  if (seek) seek.value = duration > 0 ? String(Math.round(current / duration * 1000)) : "0";
}

function timelineDurationValue() {
  if (timelineOutputAxisActive()) return timelineOutputDurationValue(currentOutput);
  return Number(waveformData?.duration || currentJob?.videoInfo?.duration || mainVideo.duration || 0);
}

function timelineOutputDurationValue(output = currentOutput) {
  if (!output?.segments?.length) return Number(output?.duration || 0);
  const schedule = compositionSchedule(output);
  return Number(output.duration) || Number(schedule.at(-1)?.outputEnd || 0);
}

function timelineHasOutputComparison() {
  return Boolean(viewerMediaKind === "output" && currentOutput?.segments?.length);
}

function timelineOutputAxisActive() {
  return Boolean(timelineHasOutputComparison() && timelineCoordinateSpace === "output");
}

function setTimelineCoordinateSpace(space) {
  const next = space === "source" ? "source" : "output";
  if (!timelineHasOutputComparison()) return;
  timelineCoordinateSpace = next;
  timelineReviewFollow = false;
  timelineFrameSelectionTime = null;
  timelineViewStart = 0;
  timelineViewEnd = next === "output"
    ? timelineOutputDurationValue(currentOutput)
    : Number(waveformData?.duration || currentJob?.videoInfo?.duration || 0);
  timelineMediaRenderKey = "";
  waveformRenderKey = "";
  updateTimeline();
}

function timelineViewRange() {
  const duration = timelineDurationValue();
  const start = Math.max(0, Math.min(duration, timelineViewStart || 0));
  const end = Math.max(start, Math.min(duration, timelineViewEnd || duration));
  return { start, end: end > start ? end : duration, duration: Math.max(0.001, (end > start ? end : duration) - start) };
}

function timelinePercentInView(second) {
  const view = timelineViewRange();
  return (Number(second) - view.start) / view.duration * 100;
}

function clampTimelineValue(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, Number(value) || 0));
}

function timelineDensityProfile(viewportHeight, detailMode) {
  const height = Math.max(190, Number(viewportHeight) || 260);
  const compact = height < 250;
  const expanded = height >= 360;
  return {
    name: compact ? "compact" : expanded ? "expanded" : "standard",
    maximumLabelLanes: compact ? 1 : 2,
    // Shot cards keep their source-time centre. Dense cards may only move to
    // another vertical lane; they are never pushed left or right away from
    // the frame range they describe.
    maximumShotLanes: compact ? 1 : (expanded ? 3 : 2),
    labelLaneHeight: compact ? 32 : expanded ? 40 : 36,
    relationHeight: compact ? 10 : expanded ? 14 : 12,
    shotLaneHeight: compact ? 34 : expanded ? 44 : 40,
    pictureMinimum: compact ? 40 : expanded ? 56 : 48,
    pictureMaximum: compact ? 52 : expanded ? 80 : 68,
    audioMinimum: compact ? 48 : expanded ? 72 : 58,
    audioMaximum: compact ? 64 : expanded ? 112 : 88,
    rulerHeight: 22,
  };
}

function timelineTrackLayout(viewportHeight, detailMode, labelLanes = 1, shotLanes = 1, layoutKind = "hierarchy") {
  const height = Math.max(190, Number(viewportHeight) || 260);
  const profile = timelineDensityProfile(height, detailMode);
  const singleContentRow = layoutKind === "content-review";
  const pictureHeight = clampTimelineValue(
    Math.round(height * (singleContentRow ? .29 : .2)),
    profile.pictureMinimum,
    singleContentRow ? Math.round(profile.pictureMaximum * 1.6) : profile.pictureMaximum,
  );
  // Audio carries real waveform and speech-energy evidence, so it receives a
  // full quarter of the review surface. Event and shot hierarchy stays
  // readable but no longer consumes nearly two thirds of the timeline.
  const audioHeight = clampTimelineValue(
    Math.round(height * (singleContentRow ? .34 : .26)),
    profile.audioMinimum,
    singleContentRow ? Math.round(profile.audioMaximum * 1.7) : profile.audioMaximum,
  );
  const hierarchyHeight = Math.max(singleContentRow ? 70 : 96, height - pictureHeight - audioHeight);
  const eventRowHeight = singleContentRow ? hierarchyHeight : Math.round(hierarchyHeight * .55);
  const shotRowHeight = singleContentRow ? 0 : hierarchyHeight - eventRowHeight;
  const eventLabelsHeight = Math.max(32, eventRowHeight - (singleContentRow ? 4 : profile.relationHeight));
  const labelLaneHeight = eventLabelsHeight / Math.max(1, labelLanes);
  const shotLaneHeight = singleContentRow ? 0 : Math.max(28, (shotRowHeight - 4) / Math.max(1, shotLanes));
  const eventCardHeight = clampTimelineValue(labelLaneHeight - 8, 32, 44);
  const shotCardHeight = singleContentRow ? 0 : clampTimelineValue(shotLaneHeight - 8, 24, 36);
  return {
    ...profile,
    height,
    eventLabelsHeight,
    labelLaneHeight,
    shotLaneHeight,
    eventCardHeight,
    shotCardHeight,
    eventRowHeight,
    shotRowHeight,
    pictureTop: eventRowHeight + shotRowHeight,
    pictureHeight,
    audioTop: eventRowHeight + shotRowHeight + pictureHeight,
    audioHeight,
  };
}

function currentTimelineLinkedIntervals() {
  const normalize = (item) => {
    const start = Number(item?.start);
    const end = Number(item?.end);
    return Number.isFinite(start) && Number.isFinite(end) && end > start ? { start, end } : null;
  };
  if (currentEventSegment) return [normalize(currentEventSegment)].filter(Boolean);
  if (currentCandidate) return [normalize(currentCandidate)].filter(Boolean);
  if (currentEventGroup?.segments?.length) return currentEventGroup.segments.map(normalize).filter(Boolean);
  if (currentOutput?.segments?.length) {
    if (timelineOutputAxisActive()) {
      return compositionSchedule(currentOutput).map((entry) => ({ start: entry.outputStart, end: entry.outputEnd }));
    }
    return currentOutput.segments.map(normalize).filter(Boolean);
  }
  return [];
}

function timelineEventSegmentAtTime(time) {
  const value = Number(time);
  if (!Number.isFinite(value) || !currentJob?.eventGroups?.length) return null;
  const matches = timelineEventDisplayModel(currentJob).groups.flatMap((group) =>
    (group.segments || []).filter((segment) => value >= Number(segment.start) && value <= Number(segment.end))
      .map((segment) => ({ group, segment })),
  );
  return matches.sort((left, right) =>
    (Number(left.segment.end) - Number(left.segment.start)) - (Number(right.segment.end) - Number(right.segment.start)),
  )[0] || null;
}

function timelineAbsoluteTime() {
  if (timelineOutputAxisActive()) return Number(mainVideo.currentTime || 0);
  const composed = viewerMediaKind === "event" ? currentEventGroup : viewerMediaKind === "output" ? currentOutput : null;
  if (composed?.segments?.length) {
    return compositionSourceTimeAtOutputTime(composed, Number(mainVideo.currentTime || 0));
  }
  if (viewerMediaKind === "output" && currentOutput) return Number(currentOutput.start) + Number(mainVideo.currentTime || 0);
  return Number(mainVideo.currentTime || 0);
}

function drawWaveform(force = false) {
  const trackContent = timelineTrackContent || timelineViewport;
  if (!trackContent || !waveformCanvas || timelinePanel?.classList.contains("hidden")) return;
  const bounds = trackContent.getBoundingClientRect();
  if (!bounds.width) return;
  const ratio = window.devicePixelRatio || 1;
  const view = timelineViewRange();
  const renderKey = [
    waveformJobId, Math.round(bounds.width), Math.round(bounds.height), ratio,
    view.start.toFixed(3), view.end.toFixed(3), timelineVisualMode,
    viewerMediaKind, currentOutput?.filename || "", timelineCoordinateSpace,
    waveformData?.schemaVersion || 0,
    waveformData?.minimums?.length || waveformData?.peaks?.length || 0,
  ].join("|");
  if (!force && waveformRenderKey === renderKey) return;
  waveformRenderKey = renderKey;
  waveformCanvas.width = Math.round(bounds.width * ratio);
  waveformCanvas.height = Math.round(bounds.height * ratio);
  const context = waveformCanvas.getContext("2d");
  if (!context) return;
  context.scale(ratio, ratio);
  context.clearRect(0, 0, bounds.width, bounds.height);
  const minimums = waveformData?.minimums || [];
  const maximums = waveformData?.maximums || [];
  const legacyPeaks = waveformData?.peaks || [];
  const sampleCount = minimums.length && minimums.length === maximums.length ? minimums.length : legacyPeaks.length;
  const timelineStyle = timelineViewport ? getComputedStyle(timelineViewport) : null;
  const cssPixels = (name, fallback) => {
    const parsed = Number.parseFloat(timelineStyle?.getPropertyValue(name) || "");
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const fallbackLayout = timelineTrackLayout(
    bounds.height,
    timelineViewport?.dataset.timelineMode === "detail",
    Math.max(1, Number(timelineViewport?.dataset.eventLabelLanes || 1)),
    Math.max(1, Number(timelineViewport?.dataset.shotMarkerLanes || 1)),
    timelineViewport?.dataset.trackLayout || "hierarchy",
  );
  // The waveform uses the exact same track geometry as labels, shots and
  // thumbnails. This avoids the previous duplicate constants drifting apart
  // after the user resized the video/timeline split.
  const audioRegionTop = cssPixels("--timeline-audio-track-top", fallbackLayout.audioTop);
  const rulerHeight = cssPixels("--timeline-ruler-height", fallbackLayout.rulerHeight);
  const audioRegionBottom = Math.max(audioRegionTop + 12, bounds.height - rulerHeight);
  const audioRegionHeight = Math.max(12, audioRegionBottom - audioRegionTop);
  const waveformHeight = Math.min(96, Math.max(20, audioRegionHeight - 8));
  const waveformTop = audioRegionTop + Math.max(0, (audioRegionHeight - waveformHeight) / 2);
  const waveformBottom = waveformTop + waveformHeight;
  const center = (waveformTop + waveformBottom) / 2;
  const amplitude = Math.max(4, waveformHeight / 2 - 3);
  if (!timelineOutputAxisActive()) {
    context.fillStyle = "#46545a";
    context.fillRect(0, center - 0.5, bounds.width, 1);
    context.fillRect(0, waveformTop, bounds.width, 1);
    context.fillRect(0, waveformBottom, bounds.width, 1);
  }
  if (sampleCount && !timelineOutputAxisActive()) {
    const fullDuration = timelineDurationValue();
    const comparisonIntervals = viewerMediaKind === "output" && currentOutput?.segments?.length
      ? currentTimelineLinkedIntervals()
      : [];
    const visibleFrom = Math.max(0, Math.floor(view.start / fullDuration * sampleCount));
    const visibleTo = Math.min(sampleCount, Math.ceil(view.end / fullDuration * sampleCount));
    const visibleLength = Math.max(1, visibleTo - visibleFrom);
    const columns = Math.max(1, Math.min(Math.floor(bounds.width), visibleLength));
    const normalization = Math.max(.04, Number(waveformData?.normalizationPeak) ||
      legacyPeaks.reduce((peak, value) => Math.max(peak, Number(value) || 0), 0) ||
      maximums.reduce((peak, value, index) => Math.max(peak, Math.abs(Number(value) || 0), Math.abs(Number(minimums[index]) || 0)), 0));
    for (let column = 0; column < columns; column += 1) {
      const from = visibleFrom + Math.floor(column / columns * visibleLength);
      const to = Math.max(from + 1, visibleFrom + Math.floor((column + 1) / columns * visibleLength));
      let minimum = 0;
      let maximum = 0;
      for (let index = from; index < Math.min(to, sampleCount); index += 1) {
        if (minimums.length) {
          minimum = Math.min(minimum, Number(minimums[index]) || 0);
          maximum = Math.max(maximum, Number(maximums[index]) || 0);
        } else {
          const peak = Number(legacyPeaks[index]) || 0;
          minimum = Math.min(minimum, -peak);
          maximum = Math.max(maximum, peak);
        }
      }
      const upper = center - Math.min(1, maximum / normalization) * amplitude;
      const lower = center - Math.max(-1, minimum / normalization) * amplitude;
      const x = column / columns * bounds.width;
      const width = Math.max(1, bounds.width / columns + .15);
      const columnTime = view.start + (column + .5) / columns * view.duration;
      const usedByOutput = !comparisonIntervals.length || comparisonIntervals.some((range) =>
        columnTime >= range.start && columnTime <= range.end,
      );
      context.fillStyle = usedByOutput ? "#b88a4a" : "rgba(111, 122, 126, .28)";
      context.fillRect(x, upper, width, Math.max(1, lower - upper));
    }
  }
  const duration = timelineDurationValue();
  if (duration > 0) {
    const view = timelineViewRange();
    const targetTicks = Math.max(4, Math.min(10, Math.floor(bounds.width / 90)));
    const rawStep = view.duration / targetTicks;
    const magnitude = 10 ** Math.floor(Math.log10(Math.max(.001, rawStep)));
    const normalizedStep = rawStep / magnitude;
    const niceFactor = normalizedStep <= 1 ? 1 : normalizedStep <= 2 ? 2 : normalizedStep <= 5 ? 5 : 10;
    const tickStep = niceFactor * magnitude;
    const firstTick = Math.ceil((view.start - .0001) / tickStep) * tickStep;
    context.fillStyle = "#68777e";
    context.font = "600 12px ui-monospace, SFMono-Regular, Menlo, monospace";
    for (let tick = firstTick; tick <= view.end + .0001; tick += tickStep) {
      const cleanTick = Math.round(tick * 1000) / 1000;
      const x = (cleanTick - view.start) / view.duration * bounds.width;
      context.fillRect(Math.round(x), bounds.height - 13, 1, 4);
      const label = formatTime(cleanTick);
      const measured = context.measureText(label).width;
      context.fillText(label, Math.max(2, Math.min(bounds.width - measured - 2, x - measured / 2)), bounds.height - 2);
    }
  }
}

function updateTimelinePlayhead() {
  if (!timelinePanel && !$("#timelineCurrent") && !$("#timelinePlayhead")) return;
  const duration = timelineDurationValue();
  const value = Math.max(0, Math.min(duration || 0, timelineAbsoluteTime()));
  const view = timelineViewRange();
  const current = $("#timelineCurrent");
  const playhead = $("#timelinePlayhead");
  const overviewPlayhead = $("#timelineOverviewPlayhead");
  const locateButton = $("#timelineLocatePlayhead");
  const outsideView = duration > 0 && (value < view.start || value > view.end);
  if (current) current.textContent = formatTime(value);
  if (playhead) playhead.style.left = duration > 0 ? `${timelinePercentInView(value)}%` : "0%";
  playhead?.classList.toggle("hidden", outsideView);
  if (overviewPlayhead) overviewPlayhead.style.left = duration > 0 ? `${value / duration * 100}%` : "0%";
  locateButton?.classList.toggle("hidden", !outsideView);
  if (locateButton && outsideView) {
    locateButton.textContent = `回到播放头 ${formatTime(value)}`;
    locateButton.title = `播放位置 ${formatTime(value)} 不在当前浏览范围内`;
  }
  timelineViewport?.classList.toggle("playhead-outside", outsideView);
  const visibleFrames = [...document.querySelectorAll("#timelineThumbnails [data-timeline-frame-time]")];
  visibleFrames.forEach((frame) => frame.classList.remove("playback-current"));
  if (!outsideView && visibleFrames.length) {
    const nearest = visibleFrames.reduce((best, frame) =>
      Math.abs(Number(frame.dataset.timelineFrameTime) - value) < Math.abs(Number(best.dataset.timelineFrameTime) - value) ? frame : best,
    );
    nearest?.classList.add("playback-current");
  }
  const outputSchedule = viewerMediaKind === "output" && currentOutput?.segments?.length
    ? compositionSchedule(currentOutput)
    : [];
  const outputTime = Number(mainVideo.currentTime || 0);
  const playingEntry = [...outputSchedule].reverse().find((entry) =>
    outputTime >= entry.outputStart - .001 && outputTime <= entry.outputEnd + .001,
  ) || null;
  timelineTrackContent?.querySelectorAll("[data-output-segment-index]").forEach((element) => {
    element.classList.toggle("playback-active", Boolean(
      playingEntry && Number(element.dataset.outputSegmentIndex) === Number(playingEntry.index),
    ));
  });
}

function updateTimelineSelection() {
  const duration = timelineDurationValue();
  const selection = $("#timelineSelection");
  const actions = $("#timelineSelectionActions");
  const summary = $("#timelineSelectionSummary");
  const confirmButton = $("#timelineSelectionConfirm");
  const cancelButton = $("#timelineSelectionCancel");
  const startInput = $("#timelineSelectionStartInput");
  const endInput = $("#timelineSelectionEndInput");
  if (!selection) return;
  const manualSelection = currentJob?.manualSelection;
  const manualEvent = currentEventGroup?.assemblyStrategy === "manual";
  const manualSourceItem = manualSelection || (currentCandidate?.manual ? currentCandidate : null) || (manualEvent ? currentEventSegment : null) || (currentEventSegment?.manual ? currentEventSegment : null);
  const item = currentEventSegment || currentCandidate || (!currentOutput?.segments?.length ? currentOutput : null) || manualSelection;
  const manual = Boolean(manualSourceItem && !currentOutput && (!currentEventSegment || currentEventSegment.manual || manualEvent) && (!currentCandidate || currentCandidate.manual));
  const view = timelineViewRange();
  // Normal event and shot selection is already expressed inside its own
  // track. Reserve the cross-track overlay for an editable manual range so
  // event state never washes over thumbnails or the audio waveform.
  if (!manual || !item || duration <= 0 || Number(item.end) <= view.start || Number(item.start) >= view.end) {
    selection.classList.add("hidden");
    actions?.classList.add("hidden");
    return;
  }
  selection.classList.remove("hidden");
  selection.classList.toggle("manual", Boolean(manualSelection && !currentEventSegment && !currentCandidate && !currentOutput));
  selection.style.left = `${timelinePercentInView(item.start)}%`;
  selection.style.width = `${Math.max(0, Number(item.end) - Number(item.start)) / view.duration * 100}%`;
  const manualBoundaryEditable = Boolean(manual && pendingTimelineSelection && ["awaiting_confirmation", "completed"].includes(currentJob?.status));
  selection.classList.toggle("readonly", !manualBoundaryEditable);
  selection.classList.toggle("boundary-editable", manualBoundaryEditable);
  if (manual) {
    // Manual source selections are input state, but remain visible so the
    // user can inspect and fine-tune the exact range before confirming it.
    selection.classList.remove("hidden");
    selection.classList.add("manual");
    actions?.classList.remove("hidden");
    actions?.classList.toggle("selection-confirmed", !pendingTimelineSelection);
    if (confirmButton) confirmButton.disabled = !pendingTimelineSelection;
    if (cancelButton) cancelButton.disabled = !pendingTimelineSelection;
    if (startInput) startInput.disabled = !pendingTimelineSelection;
    if (endInput) endInput.disabled = !pendingTimelineSelection;
    if (startInput && document.activeElement !== startInput) startInput.value = Number(manualSourceItem.start).toFixed(2);
    if (endInput && document.activeElement !== endInput) endInput.value = Number(manualSourceItem.end).toFixed(2);
    if (summary) summary.textContent = `${pendingTimelineSelection ? "待确认 · " : ""}${formatTime(manualSourceItem.start)} → ${formatTime(manualSourceItem.end)} · ${Number(manualSourceItem.end - manualSourceItem.start).toFixed(1)} 秒`;
    return;
  }
  actions?.classList.toggle("hidden", !manual);
  if (manual && summary) summary.textContent = `${formatTime(manualSelection.start)} → ${formatTime(manualSelection.end)} · ${Number(manualSelection.end - manualSelection.start).toFixed(1)} 秒`;
}

function setTimelineView(start, end, { keepReviewFocus = false } = {}) {
  const duration = timelineDurationValue();
  if (duration <= 0) return;
  if (!keepReviewFocus) timelineReviewFollow = false;
  const minimum = Math.min(2, duration);
  let span = Math.max(minimum, Math.min(duration, Number(end) - Number(start)));
  let nextStart = Math.max(0, Math.min(duration - span, Number(start)));
  timelineViewStart = nextStart;
  timelineViewEnd = nextStart + span;
  updateTimeline();
}

function zoomTimeline(factor, center = timelineAbsoluteTime()) {
  const view = timelineViewRange();
  const duration = timelineDurationValue();
  const span = Math.max(2, Math.min(duration, view.duration * factor));
  const ratio = Math.max(0, Math.min(1, (center - view.start) / view.duration));
  setTimelineView(center - span * ratio, center + span * (1 - ratio));
}

function timelineCanPan() {
  const duration = timelineDurationValue();
  const view = timelineViewRange();
  return duration > 0 && view.duration < duration - .01;
}

function applyPendingTimelinePan() {
  timelinePanFrame = null;
  const drag = timelinePanDrag;
  if (!drag || drag.pendingStart == null) return;
  const nextStart = drag.pendingStart;
  drag.pendingStart = null;
  setTimelineView(nextStart, nextStart + drag.viewDuration);
}

function moveTimelinePan(event) {
  const drag = timelinePanDrag;
  if (!drag) return;
  const delta = event.clientX - drag.startX;
  if (Math.abs(delta) >= 4) drag.moved = true;
  if (!drag.moved) return;
  event.preventDefault();
  const shift = -delta / Math.max(1, drag.width) * drag.viewDuration;
  drag.pendingStart = drag.viewStart + shift;
  timelineSpaceDidPan = timelineSpaceDidPan || drag.spaceMode;
  if (timelinePanFrame === null) timelinePanFrame = requestAnimationFrame(applyPendingTimelinePan);
}

function finishTimelinePan(event, cancelled = false) {
  const drag = timelinePanDrag;
  if (!drag) return;
  if (timelinePanFrame !== null) {
    cancelAnimationFrame(timelinePanFrame);
    timelinePanFrame = null;
    applyPendingTimelinePan();
  }
  timelinePanDrag = null;
  document.removeEventListener("pointermove", moveTimelinePan);
  document.removeEventListener("pointerup", finishTimelinePan);
  document.removeEventListener("pointercancel", cancelTimelinePan);
  timelineViewport?.classList.remove("panning");
  document.body.classList.remove("timeline-panning");
  if (drag.moved) timelineSuppressClickUntil = Date.now() + 300;
  if (!cancelled && !drag.moved && drag.allowSeek && event) activateTimelinePoint(event);
}

function cancelTimelinePan(event) {
  finishTimelinePan(event, true);
}

function beginTimelinePan(event, { allowSeek = false, spaceMode = false } = {}) {
  if (!timelineViewport || !currentJob || ![0, 1].includes(event.button)) return;
  const trackContent = timelineTrackContent || timelineViewport;
  const bounds = trackContent.getBoundingClientRect();
  const view = timelineViewRange();
  event.preventDefault();
  timelinePanDrag = {
    startX: event.clientX,
    width: Math.max(1, bounds.width),
    viewStart: view.start,
    viewDuration: view.duration,
    pendingStart: null,
    moved: false,
    allowSeek,
    spaceMode,
  };
  timelineViewport.classList.add("panning");
  document.body.classList.add("timeline-panning");
  document.addEventListener("pointermove", moveTimelinePan);
  document.addEventListener("pointerup", finishTimelinePan);
  document.addEventListener("pointercancel", cancelTimelinePan);
}

function moveTimelineOverview(event) {
  const drag = timelineOverviewDrag;
  if (!drag) return;
  const delta = event.clientX - drag.startX;
  if (Math.abs(delta) >= 3) drag.moved = true;
  if (!drag.moved) return;
  event.preventDefault();
  const shift = delta / Math.max(1, drag.width) * drag.totalDuration;
  setTimelineView(drag.viewStart + shift, drag.viewStart + shift + drag.viewDuration);
}

function finishTimelineOverview(event, cancelled = false) {
  const drag = timelineOverviewDrag;
  if (!drag) return;
  timelineOverviewDrag = null;
  document.removeEventListener("pointermove", moveTimelineOverview);
  document.removeEventListener("pointerup", finishTimelineOverview);
  document.removeEventListener("pointercancel", cancelTimelineOverview);
  $("#timelineOverview")?.classList.remove("dragging");
  document.body.classList.remove("timeline-panning");
  if (cancelled || drag.moved || drag.startedOnWindow || !event) return;
  const center = Math.max(0, Math.min(1, (event.clientX - drag.left) / Math.max(1, drag.width))) * drag.totalDuration;
  setTimelineView(center - drag.viewDuration / 2, center + drag.viewDuration / 2);
}

function cancelTimelineOverview(event) {
  finishTimelineOverview(event, true);
}

function beginTimelineOverview(event) {
  if (event.button !== 0 || !timelineCanPan()) return;
  const overview = event.currentTarget;
  const bounds = overview.getBoundingClientRect();
  const view = timelineViewRange();
  const windowElement = $("#timelineViewWindow");
  const startedOnWindow = Boolean(event.target === windowElement || event.target.closest?.("#timelineViewWindow"));
  event.preventDefault();
  if (!startedOnWindow) {
    const center = Math.max(0, Math.min(1, (event.clientX - bounds.left) / Math.max(1, bounds.width))) * timelineDurationValue();
    setTimelineView(center - view.duration / 2, center + view.duration / 2);
  }
  const nextView = timelineViewRange();
  timelineOverviewDrag = {
    startX: event.clientX,
    left: bounds.left,
    width: Math.max(1, bounds.width),
    totalDuration: timelineDurationValue(),
    viewStart: nextView.start,
    viewDuration: nextView.duration,
    startedOnWindow,
    moved: false,
  };
  overview.classList.add("dragging");
  document.body.classList.add("timeline-panning");
  document.addEventListener("pointermove", moveTimelineOverview);
  document.addEventListener("pointerup", finishTimelineOverview);
  document.addEventListener("pointercancel", cancelTimelineOverview);
}

function currentTimelineReviewRange() {
  if (currentEventSegment) {
    return {
      start: Number(currentEventSegment.start) || 0,
      end: Number(currentEventSegment.end) || Number(currentEventSegment.start) || 0,
    };
  }
  const segments = currentEventGroup?.segments || [];
  if (segments.length) {
    const intervals = timelineMergedIntervals(currentEventGroup);
    const fullStart = intervals[0]?.start ?? Math.min(...segments.map((item) => Number(item.start) || 0));
    const fullEnd = intervals.at(-1)?.end ?? Math.max(...segments.map((item) => Number(item.end) || 0));
    const contentDuration = timelineIntervalDuration(intervals);
    // A single viewport cannot truthfully represent shots separated by a long
    // empty gap. Focus the interval nearest the current composed-event play
    // position; the overview strip still shows every source interval.
    if (intervals.length > 1 && fullEnd - fullStart > Math.max(120, contentDuration * 4)) {
      const anchor = timelineAbsoluteTime();
      return intervals.reduce((nearest, interval) => {
        const distance = anchor < interval.start ? interval.start - anchor : anchor > interval.end ? anchor - interval.end : 0;
        return !nearest || distance < nearest.distance ? { ...interval, distance } : nearest;
      }, null);
    }
    return {
      start: fullStart,
      end: fullEnd,
    };
  }
  if (currentCandidate) {
    return { start: Number(currentCandidate.start) || 0, end: Number(currentCandidate.end) || Number(currentCandidate.start) || 0 };
  }
  if (currentOutput?.segments?.length) {
    const intervals = timelineMergedIntervals(currentOutput);
    const fullStart = intervals[0]?.start ?? 0;
    const fullEnd = intervals.at(-1)?.end ?? fullStart;
    const contentDuration = timelineIntervalDuration(intervals);
    // A composed video can jump between distant source ranges. When those
    // ranges cannot be read together at a useful scale, focus the source
    // interval that corresponds to the segment currently playing.
    if (intervals.length > 1 && fullEnd - fullStart > Math.max(120, contentDuration * 4)) {
      const anchor = timelineAbsoluteTime();
      return intervals.reduce((nearest, interval) => {
        const distance = anchor < interval.start ? interval.start - anchor : anchor > interval.end ? anchor - interval.end : 0;
        return !nearest || distance < nearest.distance ? { ...interval, distance } : nearest;
      }, null);
    }
    return { start: fullStart, end: fullEnd };
  }
  return null;
}

function isManualTimelineEventGroup(group) {
  return group?.assemblyStrategy === "manual"
    || /时间轴选区高光|用户从时间轴创建/.test(String(group?.title || ""))
    || /用户从时间轴创建/.test(String(group?.summary || ""));
}

function timelineMergedIntervals(group) {
  const ranges = (group?.segments || [])
    .map((segment) => ({ start: Number(segment.start) || 0, end: Number(segment.end) || Number(segment.start) || 0 }))
    .filter((range) => range.end > range.start)
    .sort((left, right) => left.start - right.start);
  return ranges.reduce((merged, range) => {
    const previous = merged.at(-1);
    if (!previous || range.start > previous.end + .05) merged.push({ ...range });
    else previous.end = Math.max(previous.end, range.end);
    return merged;
  }, []);
}

function timelineIntervalDuration(intervals) {
  return intervals.reduce((sum, range) => sum + Math.max(0, range.end - range.start), 0);
}

function timelineIntervalIntersection(left, right) {
  let total = 0;
  let leftIndex = 0;
  let rightIndex = 0;
  while (leftIndex < left.length && rightIndex < right.length) {
    const overlap = Math.min(left[leftIndex].end, right[rightIndex].end) - Math.max(left[leftIndex].start, right[rightIndex].start);
    if (overlap > 0) total += overlap;
    if (left[leftIndex].end <= right[rightIndex].end) leftIndex += 1;
    else rightIndex += 1;
  }
  return total;
}

function timelineTitleTokens(value) {
  const normalized = String(value || "").toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
  if (!normalized) return new Set();
  if (normalized.length < 2) return new Set([normalized]);
  return new Set(Array.from({ length: normalized.length - 1 }, (_, index) => normalized.slice(index, index + 2)));
}

function timelineTitleSimilarity(left, right) {
  const leftTokens = timelineTitleTokens(left);
  const rightTokens = timelineTitleTokens(right);
  if (!leftTokens.size || !rightTokens.size) return 0;
  let intersection = 0;
  leftTokens.forEach((token) => { if (rightTokens.has(token)) intersection += 1; });
  return intersection / Math.max(1, new Set([...leftTokens, ...rightTokens]).size);
}

function timelineGroupsOverlap(left, right) {
  const leftIntervals = timelineMergedIntervals(left);
  const rightIntervals = timelineMergedIntervals(right);
  const shorterDuration = Math.min(timelineIntervalDuration(leftIntervals), timelineIntervalDuration(rightIntervals));
  if (!shorterDuration) return 0;
  return timelineIntervalIntersection(leftIntervals, rightIntervals) / shorterDuration;
}

function timelineGroupsAreDisplayDuplicates(left, right) {
  const coverage = timelineGroupsOverlap(left, right);
  if (coverage >= .96) return true;
  return coverage >= .82 && timelineTitleSimilarity(left?.title, right?.title) >= .22;
}

function timelineRangesOverlap(left, right) {
  const start = Math.max(Number(left?.start) || 0, Number(right?.start) || 0);
  const end = Math.min(Number(left?.end) || 0, Number(right?.end) || 0);
  return Math.max(0, end - start);
}

function timelineOutputUsesGroup(output, group) {
  if (!output?.segments?.length || !group) return false;
  const groupId = String(group.id || "");
  const groupSegments = Array.isArray(group.segments) ? group.segments : [];
  const groupSegmentIds = new Set(groupSegments.flatMap((segment) =>
    [segment.id, segment.candidateId].filter(Boolean).map(String),
  ));
  const candidateIndices = new Set(groupSegments
    .map((segment) => Number(segment.candidateIndex ?? segment.index))
    .filter(Number.isFinite));
  const groupTitle = String(group.title || "");
  return output.segments.some((segment) => {
    const explicitGroupIds = [segment.groupId, segment.chapterId, segment.eventGroupId]
      .filter(Boolean).map(String);
    if (groupId && explicitGroupIds.includes(groupId)) return true;
    if ([segment.id, segment.candidateId].filter(Boolean).map(String).some((id) => groupSegmentIds.has(id))) return true;
    const candidateIndex = Number(segment.candidateIndex ?? segment.index);
    if (Number.isFinite(candidateIndex) && candidateIndices.has(candidateIndex)) return true;
    const segmentDuration = Math.max(.001, Number(segment.end) - Number(segment.start));
    const overlap = groupSegments.reduce((maximum, sourceSegment) =>
      Math.max(maximum, timelineRangesOverlap(segment, sourceSegment)), 0);
    if (overlap / segmentDuration >= .45) return true;
    return Boolean(groupTitle && segment.chapterTitle
      && timelineTitleSimilarity(groupTitle, segment.chapterTitle) >= .58);
  });
}

function timelineOutputComparisonModel(job = currentJob, output = currentOutput) {
  if (!job || !output?.segments?.length) return null;
  const eventDisplay = timelineEventDisplayModel(job);
  const usedGroupIds = new Set(eventDisplay.entries
    .filter((entry) => entry.groups.some((group) => timelineOutputUsesGroup(output, group)))
    .map((entry) => String(entry.group.id)));
  const schedule = compositionSchedule(output);
  const outputSegments = schedule.map((entry) => ({
    ...entry.segment,
    _output: output,
    _outputSegmentIndex: entry.index,
    _compositionOrder: entry.index + 1,
    _outputStart: entry.outputStart,
    _outputEnd: entry.outputEnd,
    filename: output.filename,
  }));
  return { eventDisplay, usedGroupIds, schedule, outputSegments };
}

function timelineEventDisplayModel(job = currentJob) {
  const recommendedIds = new Set((job?.recommendedGroupIds || []).map(String));
  const sourceGroups = (job?.eventGroups || [])
    .filter((group) => !isManualTimelineEventGroup(group))
    .sort((left, right) => {
      const leftStart = timelineMergedIntervals(left)[0]?.start ?? (Number(left.start) || 0);
      const rightStart = timelineMergedIntervals(right)[0]?.start ?? (Number(right.start) || 0);
      return leftStart - rightStart;
    });
  const buckets = [];
  sourceGroups.forEach((group) => {
    const bucket = buckets.find((candidate) => candidate.groups.some((item) => timelineGroupsAreDisplayDuplicates(item, group)));
    if (bucket) bucket.groups.push(group);
    else buckets.push({ groups: [group] });
  });
  const entries = buckets.map((bucket) => {
    const groups = [...bucket.groups].sort((left, right) => {
      const recommendation = Number(recommendedIds.has(String(right.id))) - Number(recommendedIds.has(String(left.id)));
      if (recommendation) return recommendation;
      const score = Number(right.score || 0) - Number(left.score || 0);
      if (score) return score;
      return Number(right.segments?.length || 0) - Number(left.segments?.length || 0);
    });
    const group = groups[0];
    return {
      group,
      groups,
      aliasIds: new Set(groups.map((item) => String(item.id))),
      recommended: groups.some((item) => recommendedIds.has(String(item.id))),
      duplicateCount: Math.max(0, groups.length - 1),
    };
  }).sort((left, right) => (timelineMergedIntervals(left.group)[0]?.start || 0) - (timelineMergedIntervals(right.group)[0]?.start || 0));
  const aliasToCanonical = new Map();
  entries.forEach((entry) => entry.aliasIds.forEach((id) => aliasToCanonical.set(id, String(entry.group.id))));
  return {
    entries,
    groups: entries.map((entry) => entry.group),
    aliasToCanonical,
    recommendedIds: new Set(entries.filter((entry) => entry.recommended).map((entry) => String(entry.group.id))),
    duplicateCount: entries.reduce((sum, entry) => sum + entry.duplicateCount, 0),
  };
}

function normalizedTimelineShotRole(item) {
  const raw = String(item?.role || "").trim();
  const normalized = raw.toLowerCase();
  const priorities = [
    [/高潮|climax/, "高潮"],
    [/反应|reaction/, "反应"],
    [/结果|结尾|收束|result|ending/, "结果"],
    [/发展|development/, "发展"],
    [/铺垫|上下文|context/, "铺垫"],
    [/建立|开场|核心镜头|opening|hook/, "建立"],
  ];
  return priorities.find(([pattern]) => pattern.test(normalized))?.[1] || "镜头";
}

function timelineEventSequenceNumber(group) {
  if (!group) return 0;
  const display = timelineEventDisplayModel(currentJob);
  const canonicalId = display.aliasToCanonical.get(String(group.id)) || String(group.id);
  return display.entries.findIndex((entry) => String(entry.group.id) === canonicalId) + 1;
}

function timelinePresentationModel(job = currentJob, outputComparison = null) {
  const contentMode = String(job?.taskMode || "") === "content_extract";
  const comparingOutput = Boolean(outputComparison);
  if (comparingOutput) {
    const outputAxis = timelineCoordinateSpace === "output";
    return {
      contentMode,
      layoutKind: outputAxis ? "composed-output" : "composed-source",
      title: outputAxis ? "成片时间轴" : "源片对照",
      trackLabels: outputAxis ? ["成片顺序"] : ["采用位置", "源画面", "源音频"],
      hint: outputAxis ? "按最终播放顺序连续展示" : "查看每个成片片段在源视频中的位置",
      emptyTitle: outputAxis ? "选择成片片段" : "选择采用位置",
      emptyReason: outputAxis ? "点击片段可从对应成片位置预览。" : "点击编号片段可回看它在源视频中的位置。",
      ariaLabel: outputAxis ? "成片时间轴" : "源片位置对照时间轴",
    };
  }
  if (!contentMode) {
    return {
      contentMode: false,
      layoutKind: "hierarchy",
      title: "智能剪辑时间线",
      trackLabels: ["事件", "镜头", "画面", "音频"],
      hint: "点击事件查看内容说明",
      emptyTitle: "选择事件或镜头",
      emptyReason: "点击下方时间轴中的事件或镜头，在这里查看内容说明、时间范围和判断依据。",
      ariaLabel: "视频审核时间轴",
    };
  }
  return {
    contentMode: true,
    layoutKind: "content-review",
    title: "内容检索时间轴",
    trackLabels: ["匹配片段", "画面", "音频"],
    hint: "点击匹配片段查看内容与证据",
    emptyTitle: "选择匹配片段",
    emptyReason: "点击下方时间轴中的匹配片段，在这里查看时间范围、命中内容和判断证据。",
    ariaLabel: "内容检索时间轴",
  };
}

function applyTimelinePresentation(presentation) {
  const title = $("#timelineTitle");
  const labels = $("#timelineTrackLabels");
  if (title) title.textContent = presentation.title;
  if (labels) labels.innerHTML = presentation.trackLabels.map((label) => `<span>${escapeHtml(label)}</span>`).join("");
  if (timelinePanel) timelinePanel.setAttribute("aria-label", presentation.ariaLabel);
  if (timelineViewport) timelineViewport.dataset.trackLayout = presentation.layoutKind;
  if ($("#timelineHint")) $("#timelineHint").textContent = presentation.hint;
  if ($("#evidencePanel")?.classList.contains("evidence-placeholder")) {
    if ($("#clipTitle")) $("#clipTitle").textContent = presentation.emptyTitle;
    if ($("#clipReason")) $("#clipReason").textContent = presentation.emptyReason;
  }
}

function renderTimelineEventSummary() {
  const root = $("#timelineEventSummary");
  const titleNode = $("#timelineEventSummaryTitle");
  const textNode = $("#timelineEventSummaryText");
  const timeNode = $("#timelineEventSummaryTime");
  const typeNode = $("#timelineEventSummaryType");
  const focusButton = $("#timelineFocusReview");
  if (!root || !titleNode || !textNode || !timeNode || !typeNode) return;

  let title = "";
  let detail = "";
  let start = 0;
  let end = 0;
  let type = "当前事件";
  const currentEventNumber = timelineEventSequenceNumber(currentEventGroup);
  const contentMode = String(currentJob?.taskMode || "") === "content_extract";
  const groupPrefix = contentMode ? "片段 P" : "事件 E";
  const currentEventRecommended = currentEventGroup
    ? (currentJob?.recommendedGroupIds || []).map(String).includes(String(currentEventGroup.id))
    : false;
  if (currentOutput?.segments?.length) {
    const schedule = compositionSchedule(currentOutput);
    const located = locateJobOutput(currentOutput.filename);
    const presentation = located ? autoVersionPresentation(currentJob, located.version) : {};
    title = String(currentOutput.displayTitle || presentation.displayName || currentOutput.title || (contentMode ? "内容视频" : "高光成片"));
    detail = schedule.map((entry, index) =>
      `${String(index + 1).padStart(2, "0")} ${contentMode ? String(entry.segment.chapterTitle || entry.segment.title || "匹配片段") : normalizedTimelineShotRole(entry.segment)}`,
    ).join(" → ");
    start = schedule.length ? Math.min(...schedule.map((entry) => entry.sourceStart)) : 0;
    end = schedule.length ? Math.max(...schedule.map((entry) => entry.sourceEnd)) : start;
    type = `${presentation.sourceLabel || (contentMode ? "内容视频" : "AI 成片")} · ${timelineOutputAxisActive() ? "成片时间轴" : "源片对照"}`;
  } else if (currentEventSegment && currentEventGroup) {
    const role = String(currentEventSegment.role || "精彩镜头");
    title = `${currentEventGroup.title} · ${role}`;
    detail = String(currentEventSegment.reason || currentEventGroup.summary || "该事件中的精彩镜头");
    start = Number(currentEventSegment.start) || 0;
    end = Number(currentEventSegment.end) || start;
    type = `${currentEventNumber ? `${groupPrefix}${currentEventNumber} · ` : ""}${contentMode ? "当前内容片段" : "当前镜头"}${currentEventRecommended && !contentMode ? " · AI 推荐" : ""}`;
  } else if (currentEventGroup) {
    title = String(currentEventGroup.title || (contentMode ? "匹配片段" : "精彩事件"));
    detail = String(currentEventGroup.summary || currentEventGroup.reason || (contentMode ? "点击片段可继续查看对应依据" : "点击事件镜头可继续查看对应依据"));
    const segments = currentEventGroup.segments || [];
    start = segments.length ? Math.min(...segments.map((item) => Number(item.start) || 0)) : Number(currentEventGroup.start) || 0;
    end = segments.length ? Math.max(...segments.map((item) => Number(item.end) || 0)) : Number(currentEventGroup.end) || start;
    type = `${currentEventNumber ? `${groupPrefix}${currentEventNumber} · ` : ""}${segments.length} 个${contentMode ? "内容片段" : "镜头"}${contentMode ? "" : (currentEventRecommended ? " · AI 推荐" : " · 备选")}`;
  } else if (currentCandidate) {
    title = String(currentCandidate.title || (contentMode ? "匹配片段" : "精彩镜头"));
    detail = String(currentCandidate.reason || currentCandidate.summary || currentCandidate.matchedEvidence || (contentMode ? "与检索要求匹配的内容片段" : "视觉模型发现的精彩镜头"));
    start = Number(currentCandidate.start) || 0;
    end = Number(currentCandidate.end) || start;
    type = contentMode ? "当前匹配片段" : "当前候选镜头";
  }

  const visible = Boolean(title);
  root.classList.toggle("hidden", !visible);
  root.classList.toggle("output-summary", Boolean(currentOutput?.segments?.length));
  if (focusButton) focusButton.disabled = !visible;
  if (!visible) return;
  typeNode.textContent = type;
  titleNode.textContent = title;
  if (currentOutput?.segments?.length) {
    const schedule = compositionSchedule(currentOutput);
    textNode.textContent = timelineOutputAxisActive()
      ? `${schedule.length} 个片段按最终播放顺序连续衔接，播放头与上方播放器使用同一成片时间。`
      : `编号表示最终播放顺序；片段位置表示它在源视频中的原始时间。`;
  } else {
    textNode.textContent = detail;
  }
  if (currentOutput?.segments?.length) {
    const schedule = compositionSchedule(currentOutput);
    const outputDuration = Number(currentOutput.duration)
      || Number(schedule.at(-1)?.outputEnd || 0);
    timeNode.textContent = contentMode
      ? `${schedule.length} 个片段 · 内容视频 ${outputDuration.toFixed(1)} 秒`
      : `${schedule.length} 个镜头 · 成片 ${outputDuration.toFixed(1)} 秒`;
    timeNode.title = `源视频覆盖 ${formatTime(start)} → ${formatTime(end)}；编号表示最终播放顺序`;
  } else if (currentEventGroup && !currentEventSegment) {
    const segments = currentEventGroup.segments || [];
    const contentDuration = segments.reduce((sum, segment) => sum + Math.max(0, Number(segment.duration || (Number(segment.end) - Number(segment.start)) || 0)), 0);
    timeNode.textContent = `${segments.length} 个${contentMode ? "片段" : "镜头"} · 有效内容 ${contentDuration.toFixed(1)} 秒`;
    timeNode.title = segments.length ? `源视频范围 ${formatTime(start)} → ${formatTime(end)}` : "";
  } else {
    timeNode.textContent = `${formatTime(start)} → ${formatTime(end)} · ${Math.max(0, end - start).toFixed(1)} 秒`;
    timeNode.removeAttribute("title");
  }
}

function updateTimelineReviewControls() {
  const duration = timelineDurationValue();
  const view = timelineViewRange();
  const fitButton = $("#timelineFitReview");
  const focusButton = $("#timelineFocusReview");
  const outputComparison = timelineHasOutputComparison();
  const coordinateSwitch = $("#timelineCoordinateSwitch");
  const outputAxisButton = $("#timelineOutputAxis");
  const sourceAxisButton = $("#timelineSourceAxis");
  const clockLabel = $("#timelineClockLabel");
  const reviewRange = currentTimelineReviewRange();
  if (!reviewRange) timelineReviewFollow = false;
  const fullView = duration <= 0 || view.duration >= duration - .25;
  const focusActive = Boolean(timelineReviewFollow && reviewRange && !fullView);
  const eventNumber = timelineEventSequenceNumber(currentEventGroup);
  const contentMode = String(currentJob?.taskMode || "") === "content_extract";
  const focusTarget = currentOutput?.segments?.length
    ? (contentMode ? "当前版本" : "当前成片")
    : contentMode
      ? (currentEventSegment || currentCandidate || eventNumber ? "当前片段" : "匹配片段")
      : currentEventSegment ? "当前镜头" : eventNumber ? `E${eventNumber}` : currentCandidate ? "当前镜头" : "当前事件";
  fitButton?.classList.toggle("active", fullView);
  coordinateSwitch?.classList.toggle("hidden", !outputComparison);
  outputAxisButton?.classList.toggle("active", outputComparison && timelineCoordinateSpace === "output");
  sourceAxisButton?.classList.toggle("active", outputComparison && timelineCoordinateSpace === "source");
  outputAxisButton?.setAttribute("aria-pressed", String(outputComparison && timelineCoordinateSpace === "output"));
  sourceAxisButton?.setAttribute("aria-pressed", String(outputComparison && timelineCoordinateSpace === "source"));
  if (clockLabel) clockLabel.textContent = timelineOutputAxisActive() ? "成片" : "源片";
  fitButton?.setAttribute("aria-pressed", String(fullView));
  focusButton?.classList.toggle("active", focusActive);
  focusButton?.setAttribute("aria-pressed", String(focusActive));
  if (focusButton) {
    focusButton.classList.toggle("hidden", outputComparison);
    focusButton.disabled = outputComparison || !reviewRange;
    focusButton.textContent = focusActive ? `已聚焦 ${focusTarget}` : `聚焦 ${focusTarget}`;
  }
  timelineViewport?.classList.toggle("timeline-zoomed", !fullView);
  timelineViewport?.classList.toggle("manual-select-mode", timelineManualSelectMode);
  $("#timelineOverview")?.classList.toggle("timeline-zoomed", !fullView);
  if (timelineViewport) {
    timelineViewport.title = timelineManualSelectMode
      ? "拖动生成选区；按住空格拖动或使用中键可左右移动"
      : contentMode
        ? fullView
          ? (currentOutput ? (timelineOutputAxisActive() ? "点击片段从成片时间预览" : "编号表示成片顺序，位置表示源片时间") : "点击匹配片段查看；需要时使用“聚焦”按钮放大")
          : "点击匹配片段预览；时间轴缩放与移动由你控制"
        : fullView ? (currentOutput ? "点击成片镜头可从对应位置预览；需要时聚焦当前成片" : "点击事件查看；需要时使用“聚焦”按钮放大")
        : "点击事件或镜头预览；时间轴缩放与移动由你控制";
  }
  if (!pendingTimelineSelection) {
    const hint = $("#timelineHint");
    if (hint) hint.textContent = timelineManualSelectMode
      ? "拖动生成选区，按住空格拖动可平移"
      : contentMode
        ? fullView
          ? (currentOutput ? (timelineOutputAxisActive() ? "成片时间与播放器同步" : "编号表示成片顺序，位置表示源片时间") : "点击匹配片段查看证据，使用“聚焦”按钮放大")
          : "点击片段预览，拖动左右移动"
        : fullView ? (currentOutput ? "源事件为对照底图；编号镜头按成片顺序播放" : "点击事件查看，使用“聚焦”按钮放大")
        : "点击预览，拖动左右移动";
  }
}

function focusCurrentTimelineReview() {
  const range = currentTimelineReviewRange();
  const duration = timelineDurationValue();
  if (!range || duration <= 0) return;
  timelineReviewFollow = true;
  const contentSpan = Math.max(1, range.end - range.start);
  const span = Math.min(duration, Math.max(30, contentSpan * 1.55));
  const center = (range.start + range.end) / 2;
  setTimelineView(center - span / 2, center + span / 2, { keepReviewFocus: true });
}

function refreshTimelineAfterReviewSelection() {
  // Selecting or previewing an event/shot must never change the user's zoom
  // window. Only the explicit focus control is allowed to reframe the axis.
  timelineReviewFollow = false;
  updateTimeline();
}

function renderTimelineOverview(items) {
  const duration = timelineDurationValue();
  const view = timelineViewRange();
  const clips = $("#timelineOverviewClips");
  const windowElement = $("#timelineViewWindow");
  if (!clips || !windowElement) return;
  if (duration <= 0) {
    clips.innerHTML = "";
    return;
  }
  const recommendedGroups = new Set((currentJob?.recommendedGroupIds || []).map(String));
  const recommendedCandidates = new Set((currentJob?.recommendedIndices || []).map(Number));
  clips.innerHTML = duration > 0 ? items.map((item) =>
    `<i class="timeline-overview-clip${item.filename ? " output" : ""}${item._comparisonSource ? (item._usedInOutput ? " used-in-output" : " unused-in-output") : ""}${item._group && recommendedGroups.has(String(item._group.id)) || !item._group && recommendedCandidates.has(Number(item.index)) ? " recommended" : ""}" style="left:${Number(item.start) / duration * 100}%;width:${Math.max(.15, (Number(item.end) - Number(item.start)) / duration * 100)}%"></i>`
  ).join("") : "";
  windowElement.className = "timeline-view-window";
  windowElement.style.left = `${view.start / duration * 100}%`;
  windowElement.style.width = `${view.duration / duration * 100}%`;
}

function composedTimelineDisplayItems(outputComparison) {
  const outputAxis = timelineOutputAxisActive();
  return outputComparison.schedule.map((entry, index) => ({
    ...entry.segment,
    _output: currentOutput,
    _outputSegmentIndex: entry.index,
    _compositionOrder: index + 1,
    _sourceStart: entry.sourceStart,
    _sourceEnd: entry.sourceEnd,
    _outputStart: entry.outputStart,
    _outputEnd: entry.outputEnd,
    start: outputAxis ? entry.outputStart : entry.sourceStart,
    end: outputAxis ? entry.outputEnd : entry.sourceEnd,
    filename: currentOutput?.filename,
  }));
}

function assignComposedTimelineLanes(items, outputAxis) {
  if (outputAxis) {
    items.forEach((item) => { item._timelineLane = 0; });
    return 1;
  }
  const laneEnds = [];
  [...items].sort((left, right) => Number(left.start) - Number(right.start)).forEach((item) => {
    const start = Number(item.start) || 0;
    let lane = laneEnds.findIndex((end) => start >= end - .001);
    if (lane < 0) lane = laneEnds.length;
    item._timelineLane = lane;
    laneEnds[lane] = Math.max(Number(item.end) || start, Number(laneEnds[lane]) || 0);
  });
  return Math.max(1, laneEnds.length);
}

function renderComposedTimeline(outputComparison, presentation) {
  const outputAxis = timelineOutputAxisActive();
  const duration = timelineDurationValue();
  const view = timelineViewRange();
  const items = composedTimelineDisplayItems(outputComparison);
  const laneCount = assignComposedTimelineLanes(items, outputAxis);
  const sequenceHeight = outputAxis ? 112 : Math.max(64, laneCount * 42 + 16);
  const labels = $("#timelineLabels");
  const relations = $("#timelineEventRelations");
  const clips = $("#timelineClips");
  const markers = $("#timelineShotMarkers");
  const linkedRanges = $("#timelineLinkedRanges");
  const thumbnails = $("#timelineThumbnails");
  const cuts = $("#timelineSceneCuts");

  timelineViewport?.setAttribute("data-coordinate-space", outputAxis ? "output" : "source");
  timelineViewport?.setAttribute("data-timeline-mode", view.duration >= duration - .25 ? "overview" : "detail");
  timelineViewport?.setAttribute("data-event-label-lanes", String(laneCount));
  timelineViewport?.style.setProperty("--timeline-sequence-height", `${sequenceHeight}px`);
  timelineViewport?.style.setProperty("--timeline-picture-track-top", `${sequenceHeight}px`);
  timelineViewport?.style.setProperty("--timeline-picture-track-height", outputAxis ? "0px" : "58px");
  timelineViewport?.style.setProperty("--timeline-audio-track-top", `${sequenceHeight + (outputAxis ? 0 : 58)}px`);
  timelineViewport?.style.setProperty("--timeline-audio-track-height", outputAxis ? "0px" : "74px");
  timelineViewport?.style.setProperty("--timeline-ruler-height", "24px");
  timelineViewport?.style.setProperty("--timeline-review-min-height", outputAxis ? "142px" : `${Math.max(220, sequenceHeight + 132)}px`);

  if (relations) relations.innerHTML = "";
  if (clips) clips.innerHTML = "";
  if (markers) markers.innerHTML = "";
  if (linkedRanges) linkedRanges.innerHTML = "";
  if (labels) {
    labels.innerHTML = items.map((item) => {
      if (Number(item.end) <= view.start || Number(item.start) >= view.end) return "";
      const visibleStart = Math.max(view.start, Number(item.start) || 0);
      const visibleEnd = Math.min(view.end, Number(item.end) || visibleStart);
      const left = Math.max(0, timelinePercentInView(visibleStart));
      const width = Math.max(.12, (visibleEnd - visibleStart) / view.duration * 100);
      const index = Number(item._outputSegmentIndex);
      const order = String(Number(item._compositionOrder)).padStart(2, "0");
      const title = String(item.chapterTitle || item.title || item.role || `片段 ${order}`);
      const axisRange = `${formatTime(item.start)} → ${formatTime(item.end)}`;
      const sourceRange = `${formatTime(item._sourceStart)} → ${formatTime(item._sourceEnd)}`;
      const outputRange = `${formatTime(item._outputStart)} → ${formatTime(item._outputEnd)}`;
      const tooltip = outputAxis
        ? `成片顺序 ${order} · ${title} · 成片 ${outputRange} · 源片 ${sourceRange}`
        : `成片顺序 ${order} · ${title} · 源片 ${sourceRange} · 成片 ${outputRange}`;
      return `<button type="button" class="timeline-sequence-segment" data-output-segment-index="${index}" style="left:${left}%;width:${width}%;--timeline-sequence-lane:${Number(item._timelineLane || 0)}" title="${escapeHtml(tooltip)}" aria-label="${escapeHtml(tooltip)}"><b>${order}</b><span>${escapeHtml(title)}</span><small>${escapeHtml(axisRange)}</small></button>`;
    }).join("");
    labels.querySelectorAll("[data-output-segment-index]").forEach((button) => button.addEventListener("click", (event) => {
      event.stopPropagation();
      const entry = outputComparison.schedule[Number(button.dataset.outputSegmentIndex)];
      if (entry) seekComposedMedia(currentOutput, entry.index, entry.sourceStart, "output");
    }));
  }

  if (outputAxis) {
    if (thumbnails) thumbnails.innerHTML = "";
    if (cuts) cuts.innerHTML = "";
  } else {
    renderTimelineMediaAssets(true);
  }
  renderTimelineOverview(items);
  updateTimelineSelection();
  updateTimelinePlayhead();
  updateSpeakerFilterOptions(currentJob);
  renderTimelineInsights(currentJob);
  drawWaveform(true);
  renderTimelineEventSummary();
  updateTimelineReviewControls();
  renderTimelineProposalPreview(currentJob);
}

function downsampleTimelinePoints(points, view, minimumPixelGap) {
  const trackContent = timelineTrackContent || timelineViewport;
  const width = Math.max(1, trackContent?.clientWidth || 1);
  let previousX = -Infinity;
  return points.filter((time) => {
    const x = (Number(time) - view.start) / view.duration * width;
    if (x - previousX < minimumPixelGap) return false;
    previousX = x;
    return true;
  });
}

function renderTimelineMediaAssets(force = false) {
  const track = $("#timelineThumbnails");
  const cuts = $("#timelineSceneCuts");
  const trackContent = timelineTrackContent || timelineViewport;
  if (!trackContent || !track || !cuts) return;
  const sprite = timelineAssets?.sprite;
  const view = timelineViewRange();
  const renderKey = [
    currentJob?.id, Math.round(trackContent.clientWidth), Math.round(trackContent.clientHeight),
    view.start.toFixed(3), view.end.toFixed(3), timelineVisualMode,
    timelineCutsVisible, timelineAssets?.spriteUrl || "",
    sprite?.items?.length || 0, timelineAssets?.sceneCuts?.length || 0,
    currentEventGroup?.id || "", currentEventSegment?.id || "", currentCandidate?.index ?? "",
    currentOutput?.filename || "", timelineCoordinateSpace, Number.isFinite(timelineFrameSelectionTime) ? timelineFrameSelectionTime.toFixed(3) : "",
  ].join("|");
  if (!force && timelineMediaRenderKey === renderKey) return;
  timelineMediaRenderKey = renderKey;
  if (!sprite?.items?.length || !timelineAssets?.spriteUrl) {
    const loading = $("#timelineThumbnailState")?.dataset.tone === "loading";
    track.innerHTML = loading ? '<span class="timeline-media-loader" data-generative-loader="image" data-loader-variant="tiles" data-loader-size="100%" data-loader-radius="6" data-loader-label="正在生成时间轴缩略图"></span>' : "";
    if (loading) syncGenerativeLoaders(track);
  } else {
    const displayHeight = Math.max(32, Math.round((track.getBoundingClientRect().height || 43) - 8));
    const scale = displayHeight / Number(sprite.tileHeight);
    const displayWidth = Number(sprite.tileWidth) * scale;
    const desired = Math.max(1, Math.min(sprite.items.length, Math.ceil(trackContent.clientWidth / (displayWidth + 2))));
    const selected = [];
    const selectedIndices = new Set();
    for (let index = 0; index < desired; index += 1) {
      const target = view.start + view.duration * (index + 0.5) / desired;
      const item = sprite.items.reduce((best, current) =>
        Math.abs(Number(current.time) - target) < Math.abs(Number(best.time) - target) ? current : best
      );
      if (!selectedIndices.has(item.index)) {
        selectedIndices.add(item.index);
        selected.push(item);
      }
    }
    const linkedIntervals = currentTimelineLinkedIntervals();
    track.innerHTML = selected.map((item) => {
      const isPartial = Boolean(timelineAssets?.partial);
      const quality = isPartial ? "" : item.black ? "black-frame" : item.blurred ? "blurred-frame" : "";
      const faces = isPartial ? 0 : Number(item.faces || 0);
      const frameTime = Number(item.time) || 0;
      const linked = linkedIntervals.some((range) => frameTime >= range.start && frameTime <= range.end);
      const selectedFrame = Number.isFinite(timelineFrameSelectionTime) && Math.abs(frameTime - timelineFrameSelectionTime) < .05;
      const hint = isPartial ? "时间轴关键帧正在补充" : item.black ? "疑似黑帧" : item.blurred ? "画面清晰度较低" : `动作强度 ${Math.round(Number(item.motion || 0) * 100)}`;
      const classes = ["timeline-thumbnail", quality, faces ? "face-frame" : "", linked ? "linked" : "", selectedFrame ? "selected-frame" : ""].filter(Boolean).join(" ");
      return `<button type="button" class="${classes}" data-timeline-frame-time="${frameTime}" data-faces="${faces || ""}" aria-label="预览 ${formatTime(frameTime)} 的画面" title="${formatTime(frameTime)} · ${hint}${faces ? ` · 检测到 ${faces} 张人脸` : ""}" style="--motion:${Math.min(1, Number(item.motion || 0) * 4)};width:${displayWidth}px;height:${displayHeight}px;background-image:url('${timelineAssets.spriteUrl}');background-size:${Number(sprite.spriteWidth) * scale}px ${Number(sprite.spriteHeight) * scale}px;background-position:${-Number(item.column) * Number(sprite.tileWidth) * scale}px ${-Number(item.row) * Number(sprite.tileHeight) * scale}px"></button>`;
    }).join("");
    track.querySelectorAll("[data-timeline-frame-time]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const time = Number(button.dataset.timelineFrameTime || 0);
      timelineFrameSelectionTime = time;
      const match = timelineEventSegmentAtTime(time);
      if (match) previewEventSegment(match.group, match.segment);
      else {
        showSource();
        seekSourceTime(time);
        renderTimelineEventSummary();
      }
      renderTimelineMediaAssets(true);
    }));
  }
  const visibleCuts = (timelineAssets?.sceneCuts || [])
    .filter((time) => Number(time) >= view.start && Number(time) <= view.end);
  const cutGap = view.duration / Math.max(1, trackContent.clientWidth) > .32 ? 10 : 3;
  cuts.innerHTML = timelineCutsVisible ? downsampleTimelinePoints(visibleCuts, view, cutGap)
    .map((time) => `<i class="timeline-scene-cut" style="left:${timelinePercentInView(time)}%"></i>`)
    .join("") : "";
  cuts.classList.toggle("layer-hidden", !timelineCutsVisible);
  updateTimelinePlayhead();
}

function setTimelineThumbnailState(message = "", tone = "") {
  const state = $("#timelineThumbnailState");
  if (!state) return;
  setGenerativeInlineStatus(state, message, tone || "neutral", "glyph");
}

function setWaveformState(message = "", tone = "neutral") {
  setGenerativeInlineStatus("#waveformState", message, tone, "signal");
}

async function loadTimelineTranscript(job) {
  if (!job || transcriptLoadingJobId === job.id || timelineTranscriptJobId === job.id || Date.now() < transcriptRetryAt) return;
  transcriptLoadingJobId = job.id;
  try {
    const data = await api(`/api/jobs/${job.id}/transcript`);
    if (currentJob?.id === job.id) {
      timelineTranscript = data.segments || [];
      if (data.available) {
        timelineTranscriptJobId = job.id;
        transcriptRetryAt = 0;
      } else {
        transcriptRetryAt = Date.now() + 5000;
      }
      if (currentCandidate) renderClipEvidence(currentCandidate, "candidate");
      else if (currentEventSegment) renderClipEvidence(currentEventSegment, "segment");
      else if (currentEventGroup) renderClipEvidence(currentEventGroup, "event");
      const contentSearchRoot = document.querySelector(".content-search-review");
      if (contentSearchRoot) syncContentSearchSubtitleControls(contentSearchRoot, currentJob);
    }
  } catch {
    if (currentJob?.id === job.id) {
      timelineTranscript = [];
      timelineTranscriptJobId = null;
      transcriptRetryAt = Date.now() + 5000;
    }
  } finally {
    if (transcriptLoadingJobId === job.id) transcriptLoadingJobId = null;
  }
}

async function loadTimelineAssets(job) {
  if (!job || timelineAssetsLoadingJobId === job.id || Date.now() < timelineAssetsRetryAt) return;
  if (timelineAssetsJobId === job.id && timelineAssets && !timelineAssets.generating && !timelineAssets.retryable) return;
  timelineAssetsLoadingJobId = job.id;
  if (timelineAssetsJobId !== job.id) timelineAssets = null;
  try {
    const data = await api(`/api/jobs/${job.id}/timeline-assets`);
    if (currentJob?.id !== job.id) return;
    if (data.ready === false) {
      const failed = Boolean(data.generationError);
      const delay = failed ? Math.max(3000, Number(data.retryAfterSeconds || 10) * 1000) : 1000;
      timelineAssetsRetryAt = Date.now() + delay;
      setTimelineThumbnailState(
        failed ? "画面缩略图生成失败，稍后自动重试" : "正在准备画面缩略图…",
        failed ? "error" : "loading",
      );
      renderTimelineMediaAssets(true);
      window.setTimeout(() => {
        if (currentJob?.id === job.id) updateTimeline();
      }, delay + 50);
      return;
    }
    timelineAssetsJobId = job.id;
    timelineAssets = data;
    const failed = Boolean(data.generationError);
    const delay = failed ? 10000 : 1000;
    timelineAssetsRetryAt = data.generating || data.retryable ? Date.now() + delay : 0;
    if (data.partial) {
      const count = Number(data.frameCount || data.sprite?.items?.length || 0);
      const target = Number(data.frameTarget || 0);
      setTimelineThumbnailState(
        failed ? `已显示 ${count} 张画面，后续生成失败，稍后重试` : `正在补充画面 ${count}${target ? ` / ${target}` : ""}`,
        failed ? "error" : "loading",
      );
    } else {
      setTimelineThumbnailState("");
    }
    updateTimeline();
    if ($("#candidateDrawer")?.classList.contains("open")) renderCandidateDrawer(job);
    if (data.generating || data.retryable) {
      window.setTimeout(() => {
        if (currentJob?.id === job.id) updateTimeline();
      }, delay + 50);
    }
  } catch {
    if (currentJob?.id === job.id) {
      timelineAssetsRetryAt = Date.now() + 2500;
      setTimelineThumbnailState("暂时无法读取画面，正在重试", "error");
      window.setTimeout(() => {
        if (currentJob?.id === job.id) updateTimeline();
      }, 2550);
    }
  } finally {
    if (timelineAssetsLoadingJobId === job.id) timelineAssetsLoadingJobId = null;
  }
}

function renderTimelineProposalPreview(job = currentJob) {
  const track = $("#timelineProposalTrack");
  const outputsRoot = $("#timelineProposalOutputs");
  const sourceRoot = $("#timelineProposalPreview");
  if (!track || !outputsRoot || !sourceRoot) return;
  const proposal = job?.pendingEditProposal;
  const pending = proposal?.status === "pending";
  const preview = pending && proposal.preview && typeof proposal.preview === "object" ? proposal.preview : {};
  let outputs = Array.isArray(preview.outputs) ? preview.outputs.filter((output) => Array.isArray(output?.schedule) && output.schedule.length) : [];
  if (!outputs.length && Array.isArray(preview.schedule) && preview.schedule.length) {
    outputs = [{ id: "proposal_reel", label: "提案成片", duration: Number(preview.totalOutputDuration || preview.durationAfter || 0), schedule: preview.schedule }];
  }
  // Jobs created by the previous proposal schema only carry source ranges.
  // Present them as a simple sequential strip instead of dropping the track.
  if (!outputs.length && Array.isArray(preview.ranges) && preview.ranges.length) {
    let cursor = 0;
    const schedule = preview.ranges.map((range, index) => {
      const duration = Math.max(.1, Number(range.end) - Number(range.start));
      const entry = {
        objectId: String(range.id || index), objectType: String(range.targetType || "segment"), groupId: "",
        label: range.label || `片段 ${index + 1}`, state: range.state || "adjusted",
        sourceStart: Number(range.start) || 0, sourceEnd: Number(range.end) || 0,
        outputStart: cursor, outputEnd: cursor + duration, effectiveDuration: duration,
        transitionOverlap: 0, order: index + 1, outputId: "legacy_proposal",
      };
      cursor += duration;
      return entry;
    });
    outputs = [{ id: "legacy_proposal", label: "提案片段", duration: cursor, schedule }];
  }
  track.classList.toggle("hidden", !pending || !outputs.length);
  if ($("#timelineProposalTitle")) $("#timelineProposalTitle").textContent = proposal?.title || "剪辑编排预览";
  if ($("#timelineProposalDuration")) $("#timelineProposalDuration").textContent = `${outputs.length > 1 ? `${outputs.length} 条 · ` : ""}${formatTime(Number(preview.totalOutputDuration || outputs.reduce((sum, output) => sum + Number(output.duration || 0), 0)))}`;
  outputsRoot.innerHTML = pending ? outputs.map((output, outputIndex) => {
    const duration = Math.max(.001, Number(output.duration) || Math.max(...output.schedule.map((entry) => Number(entry.outputEnd) || 0), .001));
    const blocks = output.schedule.map((entry, index) => {
      const start = Math.max(0, Number(entry.outputStart) || 0);
      const end = Math.max(start, Number(entry.outputEnd) || start);
      const left = start / duration * 100;
      const width = Math.max(.65, (end - start) / duration * 100);
      const state = String(entry.state || "unchanged");
      const speed = Number(entry.playbackRate || 1);
      const technique = [speed !== 1 ? `${speed}×` : "", Number(entry.transitionOverlap || 0) > 0 ? `${entry.transitionType === "fade_black" ? "淡黑" : "叠化"} ${Number(entry.transitionOverlap).toFixed(1)}s` : ""].filter(Boolean).join(" · ");
      const title = [`镜头 ${index + 1}`, entry.label, `成片 ${formatTime(start)}→${formatTime(end)}`, `源 ${formatTime(entry.sourceStart)}→${formatTime(entry.sourceEnd)}`, technique].filter(Boolean).join(" · ");
      return `<button type="button" class="proposal-schedule-block state-${escapeHtml(state)}${activeProposalSourceRange?.proposalId === proposal.id && activeProposalSourceRange?.outputId === String(output.id) && Number(activeProposalSourceRange?.index) === index ? " active" : ""}" data-proposal-output="${escapeHtml(String(output.id || outputIndex))}" data-proposal-index="${index}" style="left:${left}%;width:${width}%" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"><b>${String(index + 1).padStart(2, "0")}</b><span>${escapeHtml(entry.label || `镜头 ${index + 1}`)}</span>${technique ? `<em>${escapeHtml(technique)}</em>` : ""}</button>`;
    }).join("");
    return `<div class="proposal-output-row" data-proposal-output-row="${escapeHtml(String(output.id || outputIndex))}"><div class="proposal-output-label"><b>${escapeHtml(outputs.length > 1 ? `输出 ${outputIndex + 1}` : "成片顺序")}</b><span>${escapeHtml(output.label || "提案成片")} · ${formatTime(duration)}</span></div><div class="proposal-output-line"><i aria-hidden="true"></i>${blocks}</div></div>`;
  }).join("") : "";
  outputsRoot.querySelectorAll("[data-proposal-index]").forEach((button) => button.addEventListener("click", () => {
    const output = outputs.find((item, index) => String(item.id || index) === String(button.dataset.proposalOutput));
    const index = Number(button.dataset.proposalIndex);
    const entry = output?.schedule?.[index];
    if (!entry) return;
    activeProposalSourceRange = {
      proposalId: String(proposal.id || ""), outputId: String(output.id || ""), index,
      start: Number(entry.sourceStart) || 0, end: Number(entry.sourceEnd) || Number(entry.sourceStart) || 0,
    };
    showSource({ autoplay: false });
    candidatePreviewEnd = Number(entry.sourceEnd) || null;
    const padding = Math.max(3, Math.min(12, (Number(entry.sourceEnd) - Number(entry.sourceStart)) * 1.2));
    setTimelineView(Math.max(0, Number(entry.sourceStart) - padding), Number(entry.sourceEnd) + padding);
    seekSourceTime(Number(entry.sourceStart) || 0);
    updateTimeline();
  }));

  const active = pending && activeProposalSourceRange?.proposalId === String(proposal?.id || "") ? activeProposalSourceRange : null;
  const view = timelineViewRange();
  const visible = active && Number(active.end) > view.start && Number(active.start) < view.end;
  sourceRoot.classList.toggle("hidden", !visible);
  sourceRoot.setAttribute("aria-hidden", String(!visible));
  if (!visible) {
    sourceRoot.innerHTML = "";
  } else {
    const start = Math.max(view.start, Number(active.start) || 0);
    const end = Math.min(view.end, Number(active.end) || start);
    sourceRoot.innerHTML = `<i class="proposal-source-highlight" style="left:${timelinePercentInView(start)}%;width:${Math.max(.35, (end - start) / view.duration * 100)}%"><span>提案镜头来源</span></i>`;
  }
}

function updateTimeline() {
  if (!timelinePanel) return;
  if (!currentJob) {
    timelinePanel.classList.add("hidden");
    return;
  }
  timelinePanel.classList.remove("hidden");
  const duration = timelineDurationValue();
  const contentMode = String(currentJob.taskMode || "") === "content_extract";
  const durationNode = $("#timelineDuration");
  if (durationNode) durationNode.textContent = formatTime(duration);
  const eventDisplay = timelineEventDisplayModel(currentJob);
  const displayEventGroups = eventDisplay.groups;
  const outputComparison = viewerMediaKind === "output" && currentOutput?.segments?.length
    ? timelineOutputComparisonModel(currentJob, currentOutput)
    : null;
  const timelinePresentation = timelinePresentationModel(currentJob, outputComparison);
  const contentReviewSingleLayer = timelinePresentation.layoutKind === "content-review";
  applyTimelinePresentation(timelinePresentation);
  timelineViewport?.classList.toggle("output-comparison-mode", Boolean(outputComparison));
  timelinePanel?.classList.toggle("output-comparison-mode", Boolean(outputComparison));
  const legendItems = [...timelinePanel.querySelectorAll(":scope > footer > span")].slice(0, 4);
  const legendLabels = outputComparison
    ? (timelineOutputAxisActive()
        ? ["成片片段", "播放顺序", "当前播放", "播放位置"]
        : ["采用片段", "成片顺序", "当前播放", "源片位置"])
    : (contentMode ? ["匹配片段", "已选片段", "当前预览", "播放位置"] : ["事件镜头", "AI 推荐", "当前选中", "播放位置"]);
  legendItems.forEach((node, index) => {
    const textNode = [...node.childNodes].find((child) => child.nodeType === 3);
    if (textNode) textNode.textContent = legendLabels[index];
  });
  if (outputComparison) {
    renderComposedTimeline(outputComparison, timelinePresentation);
    return;
  }
  let items;
  if (outputComparison && displayEventGroups.length) {
    // Source events remain as a quiet comparison layer. Only the currently
    // selected output contributes shot blocks; older versions must never be
    // stacked into the same timeline.
    const sourceEvents = displayEventGroups.flatMap((group) => (group.segments || []).map((segment) => ({
      ...segment,
      _group: group,
      _sourceEvent: true,
      _comparisonSource: true,
      _usedInOutput: outputComparison.usedGroupIds.has(String(group.id)),
    })));
    items = [...sourceEvents, ...outputComparison.outputSegments];
  } else if (outputComparison) {
    items = [...outputComparison.outputSegments];
  } else if (viewerMediaKind === "candidate" && currentCandidate) {
    items = currentJob.candidates || [];
  } else if (currentJob.status === "awaiting_content_confirmation") {
    items = (currentJob.contentSearch?.candidates || []).map((item, index) => ({ ...item, index }));
  } else if (currentJob.status === "awaiting_confirmation" && currentJob.eventGroups?.length) {
    items = displayEventGroups.flatMap((group) => group.segments.map((segment) => ({ ...segment, _group: group })));
  } else if (currentJob.status === "awaiting_confirmation") {
    const excluded = new Set((currentJob.reviewExcludedCandidates || []).map((index) => Number(index)));
    items = (currentJob.candidates || []).filter((candidate) => !excluded.has(Number(candidate.index)));
  } else if (currentJob.eventGroups?.length) {
    items = displayEventGroups.flatMap((group) => (group.segments || []).map((segment) => ({
      ...segment, _group: group, _sourceEvent: true,
    })));
  } else {
    items = currentOutput?.segments?.length
      ? compositionSchedule(currentOutput).map((entry) => ({
        ...entry.segment,
        _output: currentOutput,
        _outputSegmentIndex: entry.index,
        _compositionOrder: entry.index + 1,
        filename: currentOutput.filename,
      }))
      : [];
  // A manually dragged source range is an input selection, not an additional
  // highlight layer. Keep it in state/chat, but do not render it over the
  // original event/candidate timeline.
  }
  items = items.filter((item) => !item.manual).filter(speakerMatches);
  // Event groups are stored in recommendation/priority order, not source-time
  // order. A review timeline must read left-to-right, so use chronological
  // order for display and derive stable 1..N shot numbers from that order.
  items = [...items].sort((left, right) => {
    const time = Number(left.start) - Number(right.start);
    if (Math.abs(time) > .001) return time;
    if (Boolean(left._output) !== Boolean(right._output)) return left._output ? 1 : -1;
    return Number(left.end) - Number(right.end);
  });
  const view = timelineViewRange();
  const recommended = new Set(currentJob.recommendedIndices || []);
  const selectedContentMatches = new Set(
    (currentJob.contentSearch?.defaultSelectedIds || currentJob.contentSearch?.reviewDraft?.selectedMatchIds || []).map(String),
  );
  const recommendedEventIds = eventDisplay.recommendedIds;
  const chronologicalEventGroups = displayEventGroups;
  const eventSequence = new Map(chronologicalEventGroups.map((group, index) => [String(group.id), index + 1]));
  const timelineRelationForItem = (item, position = 0) => {
    const directEventNumber = Number(eventSequence.get(String(item?._group?.id || "")) || 0);
    if (directEventNumber) return { eventNumber: directEventNumber, relationKey: `event-${directEventNumber}` };
    if (item?._output) {
      const relatedEventIndex = eventDisplay.entries.findIndex((entry) =>
        entry.groups.some((group) => timelineOutputUsesGroup({ segments: [item] }, group)),
      );
      if (relatedEventIndex >= 0) {
        const eventNumber = relatedEventIndex + 1;
        return { eventNumber, relationKey: `event-${eventNumber}` };
      }
    }
    if (currentJob.status === "awaiting_confirmation") {
      return { eventNumber: 0, relationKey: `candidate-${position + 1}` };
    }
    return { eventNumber: 0, relationKey: "" };
  };
  const activeCanonicalEventId = eventDisplay.aliasToCanonical.get(String(currentEventGroup?.id || "")) || String(currentEventGroup?.id || "");
  const timelineItemIsActive = (item) => Boolean(
    currentEventSegment?.id != null && item?.id != null && String(currentEventSegment.id) === String(item.id)
    || currentCandidate?.index != null && item?.index != null && Number(currentCandidate.index) === Number(item.index)
    || contentMode && currentCandidate?.id != null && item?.id != null && String(currentCandidate.id) === String(item.id)
    || currentOutput?.filename && item?.filename && String(currentOutput.filename) === String(item.filename)
  );
  const timelineItemTitle = (item, position = 0) => {
    if (!item) return `镜头 ${position + 1}`;
    // Planned montage segments carry the original event/chapter title. Keep it
    // visible on the timeline instead of replacing it with the LLM role
    // (development/climax/etc.).
    if (item._group?.title) return item._group.title;
    if (item.chapterTitle) return item.chapterTitle;
    if (item.title) return item.title;
    const roleTitles = {
      hook: "开场", context: "上下文", development: "发展",
      climax: "高潮", reaction: "人物反应", result: "结尾",
      opening: "开场", ending: "结尾",
    };
    return roleTitles[String(item.role || "").toLowerCase()] || item.role || `镜头 ${position + 1}`;
  };
  const timelineShotRole = normalizedTimelineShotRole;
  const timelineShotCaption = (item) => {
    const candidateIndex = Number(item?.candidateIndex ?? item?.index);
    const candidate = Number.isFinite(candidateIndex)
      ? (currentJob.candidates || []).find((entry) => Number(entry.index) === candidateIndex)
      : null;
    return String(
      candidate?.title || item?.title || (contentMode ? item?.chapterTitle || item?._group?.title : "")
      || timelineShotRole(item) || (contentMode ? "匹配片段" : "镜头"),
    ).trim();
  };
  const labels = $("#timelineLabels");
  const trackWidth = Math.max(320, Math.round(timelineTrackContent?.getBoundingClientRect().width || timelineViewport?.getBoundingClientRect().width || 1000));
  const viewportHeight = Math.max(190, Math.round(timelineViewport?.getBoundingClientRect().height || 260));
  timelineLabelLayoutWidth = trackWidth;
  timelineLabelLayoutHeight = viewportHeight;
  const isFullTimelineView = view.duration >= duration - .25;
  const pixelsPerSecond = trackWidth / Math.max(.001, view.duration);
  const timelineDetailMode = !isFullTimelineView && (timelineReviewFollow || view.duration <= 180 || pixelsPerSecond >= 4);
  const densityProfile = timelineDensityProfile(viewportHeight, timelineDetailMode);
  let labelLaneHeight = densityProfile.labelLaneHeight;
  let shotLaneHeight = densityProfile.shotLaneHeight;
  const labelEntries = duration > 0 ? items.map((item, position) => {
    const groupSegments = item._group?.segments || [];
    const groupIntervals = groupSegments.length ? timelineMergedIntervals(item._group) : [{ start: Number(item.start) || 0, end: Number(item.end) || Number(item.start) || 0 }];
    const visibleIntervals = groupIntervals.filter((range) => range.end > view.start && range.start < view.end);
    const groupStart = groupIntervals[0]?.start ?? (Number(item.start) || 0);
    const groupEnd = groupIntervals.at(-1)?.end ?? (Number(item.end) || groupStart);
    if (groupEnd <= view.start || groupStart >= view.end) return null;
    const sourceFirstSegment = [...groupSegments].sort((left, right) => Number(left.start) - Number(right.start))[0];
    if (item._group && String(sourceFirstSegment?.id || "") !== String(item.id || "")) return null;
    // Once an event layer exists, rendered output segments stay in the shot
    // row. Repeating their role labels in the event row produces duplicate,
    // overlapping callouts and hides the original event titles.
    if (currentJob.eventGroups?.length && item._output && !item._group) return null;
    const title = timelineItemTitle(item, position);
    const labelEnd = groupEnd;
    const detail = item._group?.summary || item.summary || item.reason || "";
    const characterCount = Array.from(String(title)).length;
    const contentMatchId = String(item._group?.contentMatchId || item.candidateId || item.id || "");
    const isRecommendedEvent = contentMode
      ? (item._group
          ? recommendedEventIds.has(String(item._group.id)) || selectedContentMatches.has(contentMatchId)
          : selectedContentMatches.has(contentMatchId))
      : item._group
        ? recommendedEventIds.has(String(item._group.id))
        : recommended.has(Number(item.index));
    const eventNumber = item._group ? Number(eventSequence.get(String(item._group.id)) || 0) : 0;
    const relationKey = eventNumber ? `event-${eventNumber}` : `candidate-${position + 1}`;
    const duplicateCount = item._group
      ? Number(eventDisplay.entries.find((entry) => String(entry.group.id) === String(item._group.id))?.duplicateCount || 0)
      : 0;
    const minimumWidth = timelineDetailMode ? 200 : 132;
    const maximumWidth = timelineDetailMode ? 420 : 300;
    const width = Math.min(maximumWidth, Math.max(minimumWidth, characterCount * 13 + 72 + (isRecommendedEvent ? 34 : 0)));
    const scopeFragments = visibleIntervals.map((range) => ({
      left: Math.max(0, timelinePercentInView(Math.max(view.start, range.start))),
      width: Math.max(.25, (Math.min(view.end, range.end) - Math.max(view.start, range.start)) / view.duration * 100),
    }));
    const scopeLeft = Math.min(...scopeFragments.map((fragment) => fragment.left));
    const scopeRight = Math.max(...scopeFragments.map((fragment) => fragment.left + fragment.width));
    const anchor = Math.max(0, Math.min(trackWidth, (scopeLeft + scopeRight) / 200 * trackWidth));
    const left = Math.max(0, Math.min(trackWidth - Math.min(width, trackWidth), anchor - width / 2));
    const active = item._group
      ? activeCanonicalEventId === String(item._group.id || "")
      : Number(currentCandidate?.index) === Number(item.index);
    const usedInOutput = Boolean(outputComparison && item._group
      && outputComparison.usedGroupIds.has(String(item._group.id)));
    return {
      item, position, title, detail, labelEnd, width: Math.min(width, trackWidth), anchor, left, active,
      eventNumber, relationKey, isRecommendedEvent, usedInOutput, duplicateCount, groupStart, groupEnd, scopeLeft, scopeRight,
      scopeFragments,
      shotCount: groupSegments.length || 1,
      eventDuration: groupSegments.reduce((sum, segment) => sum + Math.max(0, Number(segment.duration || (Number(segment.end) - Number(segment.start)) || 0)), 0),
    };
  }).filter(Boolean).sort((left, right) => Number(left.item.start) - Number(right.item.start)) : [];

  const maximumLabelLanes = densityProfile.maximumLabelLanes;
  const laneEnds = [];
  labelEntries.forEach((entry) => {
    const place = () => {
      let best = null;
      for (let lane = 0; lane < maximumLabelLanes; lane += 1) {
        const occupied = Number(laneEnds[lane] || -6);
        const left = Math.max(entry.left, occupied + 6);
        if (left + entry.width > trackWidth) continue;
        const shift = Math.abs(left - entry.left);
        if (!best || shift < best.shift) best = { lane, left, shift };
      }
      return best;
    };
    let placement = place();
    if (!placement && !timelineDetailMode) {
      entry.narrow = true;
      entry.width = 72;
      entry.left = Math.max(0, Math.min(trackWidth - entry.width, entry.anchor - entry.width / 2));
      placement = place();
    }
    if (!placement && !timelineDetailMode) {
      entry.narrow = false;
      entry.compact = true;
      entry.width = 42;
      entry.left = Math.max(0, Math.min(trackWidth - entry.width, entry.anchor - entry.width / 2));
      placement = place();
    }
    if (!placement) {
      const lane = laneEnds.length < maximumLabelLanes ? laneEnds.length : laneEnds.indexOf(Math.min(...laneEnds));
      placement = { lane: Math.max(0, lane), left: Math.max(0, Math.min(trackWidth - entry.width, entry.left)), shift: 0 };
    }
    entry.lane = placement.lane;
    entry.left = placement.left;
    laneEnds[entry.lane] = Math.max(laneEnds[entry.lane] || 0, entry.left + entry.width);
  });
  const labelLanes = Math.max(1, Math.min(maximumLabelLanes, laneEnds.length || 1));
  const hasSourceReviewItems = items.some((item) => !item._output);
  const numberedShots = contentReviewSingleLayer
    ? []
    : outputComparison
    ? items.filter((item) => item._output)
    : items.filter((item) => !hasSourceReviewItems || !item._output);
  numberedShots.forEach((item, index) => {
    item._timelineShotNumber = Number(item._compositionOrder || index + 1);
    item._timelineShotAnchor = Math.max(0, Math.min(trackWidth, timelinePercentInView(item.start) / 100 * trackWidth));
    item._timelineShotMarkerText = String(item._timelineShotNumber).padStart(2, "0");
    item._timelineShotMarkerRole = timelineShotCaption(item);
    item._timelineShotClusterCount = 0;
    item._timelineShotMarkerHidden = false;
  });

  const shotLaneIntervals = Array.from({ length: densityProfile.maximumShotLanes }, () => []);
  numberedShots.forEach((item) => {
    const markerText = String(item._timelineShotMarkerText || item._timelineShotNumber || "");
    const markerRole = String(item._timelineShotMarkerRole || "镜头");
    const badgeWidth = Math.min(trackWidth, Math.min(210, Math.max(112, markerText.length * 10.5 + Array.from(markerRole).length * 12 + 38)));
    const visibleStart = Math.max(view.start, Number(item.start) || 0);
    const visibleEnd = Math.min(view.end, Number(item.end) || visibleStart);
    const rangeStart = Math.max(0, Math.min(trackWidth, timelinePercentInView(visibleStart) / 100 * trackWidth));
    const rangeEnd = Math.max(rangeStart, Math.min(trackWidth, timelinePercentInView(visibleEnd) / 100 * trackWidth));
    const anchor = Math.max(0, Math.min(trackWidth, (rangeStart + rangeEnd) / 2));
    // Preserve the temporal centre. Clamping happens only at viewport edges;
    // the SVG anchor line below points back to the exact source-time centre.
    const badgeLeft = Math.max(0, Math.min(trackWidth - badgeWidth, anchor - badgeWidth / 2));
    const badgeRight = badgeLeft + badgeWidth;
    const laneScores = shotLaneIntervals.map((intervals) => intervals.reduce((score, interval) => (
      score + Math.max(0, Math.min(badgeRight, interval.right) - Math.max(badgeLeft, interval.left))
    ), 0));
    let lane = laneScores.findIndex((score) => score === 0);
    if (lane < 0) lane = laneScores.indexOf(Math.min(...laneScores));
    item._timelineShotLane = Math.max(0, lane);
    item._timelineShotBadgeLeft = badgeLeft;
    item._timelineShotBadgeWidth = badgeWidth;
    item._timelineShotMarkerTarget = anchor;
    item._timelineShotRangeStart = rangeStart;
    item._timelineShotRangeEnd = rangeEnd;
    shotLaneIntervals[item._timelineShotLane].push({ left: badgeLeft, right: badgeRight });
  });
  const usedShotLanes = numberedShots.length
    ? Math.max(...numberedShots.map((item) => Number(item._timelineShotLane || 0))) + 1
    : 1;
  const shotLanes = Math.max(1, Math.min(densityProfile.maximumShotLanes, usedShotLanes));
  const layout = timelineTrackLayout(
    viewportHeight, timelineDetailMode, labelLanes, shotLanes, timelinePresentation.layoutKind,
  );
  labelLaneHeight = layout.labelLaneHeight;
  shotLaneHeight = layout.shotLaneHeight;
  const relationLaneHeight = layout.relationHeight;
  const eventTrackHeight = layout.eventRowHeight + layout.shotRowHeight;
  timelineViewport?.style.setProperty("--timeline-event-label-lanes", String(labelLanes));
  timelineViewport?.style.setProperty("--timeline-event-labels-height", `${layout.eventLabelsHeight}px`);
  timelineViewport?.style.setProperty("--timeline-event-card-height", `${layout.eventCardHeight}px`);
  timelineViewport?.style.setProperty("--timeline-event-row-height", `${layout.eventRowHeight}px`);
  timelineViewport?.style.setProperty("--timeline-event-relations-height", `${relationLaneHeight}px`);
  timelineViewport?.style.setProperty("--timeline-shot-track-height", `${layout.shotRowHeight}px`);
  timelineViewport?.style.setProperty("--timeline-shot-card-height", `${layout.shotCardHeight}px`);
  timelineViewport?.style.setProperty("--timeline-event-track-height", `${eventTrackHeight}px`);
  timelineViewport?.style.setProperty("--timeline-picture-track-top", `${layout.pictureTop}px`);
  timelineViewport?.style.setProperty("--timeline-picture-track-height", `${layout.pictureHeight}px`);
  timelineViewport?.style.setProperty("--timeline-audio-track-top", `${layout.audioTop}px`);
  timelineViewport?.style.setProperty("--timeline-audio-track-height", `${layout.audioHeight}px`);
  timelineViewport?.style.setProperty("--timeline-ruler-height", `${layout.rulerHeight}px`);
  timelineViewport?.style.setProperty("--timeline-review-min-height", "190px");
  timelineViewport?.setAttribute("data-event-label-lanes", String(labelLanes));
  timelineViewport?.setAttribute("data-event-relation-height", String(relationLaneHeight));
  timelineViewport?.setAttribute("data-shot-marker-lanes", String(shotLanes));
  timelineViewport?.setAttribute("data-timeline-mode", timelineDetailMode ? "detail" : "overview");
  timelineViewport?.setAttribute("data-timeline-density", layout.name);
  const relations = $("#timelineEventRelations");
  if (relations) {
    relations.setAttribute("viewBox", `0 0 ${trackWidth} ${viewportHeight}`);
    relations.setAttribute("width", String(trackWidth));
    relations.setAttribute("height", String(viewportHeight));
    const relationTargets = numberedShots.map((item) => {
      const position = items.indexOf(item);
      const relation = timelineRelationForItem(item, position);
      if (Number(item.end) <= view.start || Number(item.start) >= view.end) return null;
      const shotLane = Number(item._timelineShotLane || 0);
      const shotTop = layout.eventRowHeight + shotLane * shotLaneHeight + Math.max(2, (shotLaneHeight - layout.shotCardHeight) / 2);
      const markerCenter = Number(item._timelineShotBadgeLeft || 0) + Number(item._timelineShotBadgeWidth || 0) / 2;
      return {
        item,
        position,
        relationKey: relation.relationKey,
        x: Math.max(0, Math.min(trackWidth, markerCenter)),
        y: shotTop,
        lineY: Math.min(layout.eventRowHeight + layout.shotRowHeight - 3, shotTop + layout.shotCardHeight + 3),
        rangeStart: Number(item._timelineShotRangeStart || 0),
        rangeEnd: Number(item._timelineShotRangeEnd || 0),
      };
    }).filter(Boolean);
    const bandMarkup = contentReviewSingleLayer ? "" : labelEntries.flatMap((entry) => {
      const stateClasses = `${entry.isRecommendedEvent ? " recommended" : ""}${entry.active ? " active" : ""}${outputComparison ? (entry.usedInOutput ? " used-in-output" : " unused-in-output") : ""}`;
      return entry.scopeFragments.map((fragment) => {
        const x = fragment.left / 100 * trackWidth;
        const width = Math.max(3, fragment.width / 100 * trackWidth);
        return `<rect class="timeline-event-band${stateClasses}" data-timeline-relation="${entry.relationKey}" x="${x.toFixed(2)}" y="${layout.eventRowHeight.toFixed(2)}" width="${width.toFixed(2)}" height="${layout.shotRowHeight.toFixed(2)}" rx="6" ry="6"></rect>`;
      });
    }).join("");
    const shotRangeMarkup = relationTargets.map((target) => {
      const parentEntry = labelEntries.find((entry) => entry.relationKey === target.relationKey);
      const isActive = timelineItemIsActive(target.item);
      const stateClasses = `${parentEntry?.isRecommendedEvent ? " recommended" : ""}${isActive ? " active" : ""}${outputComparison && target.item._output ? " used-in-output" : ""}`;
      const start = Math.max(0, Math.min(trackWidth, target.rangeStart));
      const end = Math.max(start, Math.min(trackWidth, target.rangeEnd));
      const markerTarget = Math.max(start, Math.min(end || start, Number(target.item._timelineShotMarkerTarget || target.x)));
      return `<g class="timeline-shot-range${stateClasses}"${target.relationKey ? ` data-timeline-relation="${target.relationKey}"` : ""}><line class="timeline-shot-range-line" x1="${start.toFixed(2)}" y1="${target.lineY.toFixed(2)}" x2="${end.toFixed(2)}" y2="${target.lineY.toFixed(2)}"></line><line class="timeline-shot-centre-guide" x1="${target.x.toFixed(2)}" y1="${(target.y + layout.shotCardHeight).toFixed(2)}" x2="${markerTarget.toFixed(2)}" y2="${target.lineY.toFixed(2)}"></line><circle class="timeline-shot-range-end start" cx="${start.toFixed(2)}" cy="${target.lineY.toFixed(2)}" r="2.5"></circle><circle class="timeline-shot-range-end end" cx="${end.toFixed(2)}" cy="${target.lineY.toFixed(2)}" r="2.5"></circle></g>`;
    }).join("");
    const curveMarkup = contentMode ? "" : labelEntries.flatMap((entry) => {
      const stateClasses = `${entry.isRecommendedEvent ? " recommended" : ""}${entry.active ? " active" : ""}${outputComparison ? (entry.usedInOutput ? " used-in-output" : " unused-in-output") : ""}`;
      const labelTop = Math.max(0, entry.lane * labelLaneHeight + Math.max(0, (labelLaneHeight - layout.eventCardHeight) / 2) - 4);
      const startX = Math.max(0, Math.min(trackWidth, entry.left + entry.width / 2));
      const startY = labelTop + layout.eventCardHeight;
      return relationTargets.filter((target) => target.relationKey === entry.relationKey).map((target) => {
        const verticalGap = Math.max(8, target.y - startY);
        const bend = Math.max(8, Math.min(34, verticalGap * .52));
        const path = `M ${startX.toFixed(2)} ${startY.toFixed(2)} C ${startX.toFixed(2)} ${(startY + bend).toFixed(2)}, ${target.x.toFixed(2)} ${(target.y - bend).toFixed(2)}, ${target.x.toFixed(2)} ${target.y.toFixed(2)}`;
        return `<path class="timeline-event-curve${stateClasses}" data-timeline-relation="${entry.relationKey}" d="${path}"></path>`;
      });
    }).join("");
    const connectionPointMarkup = contentMode ? "" : labelEntries.flatMap((entry) => {
      const targets = relationTargets.filter((target) => target.relationKey === entry.relationKey);
      if (!targets.length) return [];
      const stateClasses = `${entry.isRecommendedEvent ? " recommended" : ""}${entry.active ? " active" : ""}${outputComparison ? (entry.usedInOutput ? " used-in-output" : " unused-in-output") : ""}`;
      const labelTop = Math.max(0, entry.lane * labelLaneHeight + Math.max(0, (labelLaneHeight - layout.eventCardHeight) / 2) - 4);
      const startX = Math.max(0, Math.min(trackWidth, entry.left + entry.width / 2));
      const startY = labelTop + layout.eventCardHeight;
      const eventPoint = `<circle class="timeline-connection-point event-point${stateClasses}" data-timeline-relation="${entry.relationKey}" cx="${startX.toFixed(2)}" cy="${startY.toFixed(2)}" r="3.6"></circle>`;
      const shotPoints = targets.map((target) => `<circle class="timeline-connection-point shot-point${stateClasses}" data-timeline-relation="${entry.relationKey}" cx="${target.x.toFixed(2)}" cy="${target.y.toFixed(2)}" r="3.2"></circle>`);
      return [eventPoint, ...shotPoints];
    }).join("");
    relations.innerHTML = `${bandMarkup}${shotRangeMarkup}${curveMarkup}${connectionPointMarkup}`;
  }
  const linkedRanges = $("#timelineLinkedRanges");
  if (linkedRanges) {
    const linkedKind = currentOutput?.segments?.length ? "output" : currentEventSegment || currentCandidate ? "shot" : "event";
    linkedRanges.innerHTML = currentTimelineLinkedIntervals()
      .filter((range) => range.end > view.start && range.start < view.end)
      .map((range, index) => {
        const start = Math.max(view.start, range.start);
        const end = Math.min(view.end, range.end);
        return `<i class="timeline-linked-range ${linkedKind}"${linkedKind === "output" ? ` data-output-segment-index="${index}"` : ""} style="left:${timelinePercentInView(start)}%;width:${Math.max(.2, (end - start) / view.duration * 100)}%"></i>`;
      }).join("");
  }
  if (labels) labels.innerHTML = labelEntries.map((entry) => {
    const anchorOffset = Math.max(8, Math.min(entry.width - 8, entry.anchor - entry.left));
    const range = `${formatTime(entry.groupStart)} → ${formatTime(entry.groupEnd)}`;
    const sequenceLabel = contentMode
      ? `P${String(entry.eventNumber || entry.position + 1).padStart(2, "0")}`
      : entry.eventNumber ? `E${entry.eventNumber}` : `C${entry.position + 1}`;
    const kindLabel = contentMode
      ? `匹配片段 ${sequenceLabel}`
      : entry.eventNumber ? `事件 ${sequenceLabel}` : `候选 ${sequenceLabel}`;
    const duplicateFact = entry.duplicateCount ? `已折叠 ${entry.duplicateCount} 个重复分析结果` : "";
    const labelTop = entry.lane * labelLaneHeight + Math.max(0, (labelLaneHeight - layout.eventCardHeight) / 2) - 4;
    const comparisonClass = outputComparison ? (entry.usedInOutput ? " used-in-output" : " unused-in-output") : "";
    const statusBadge = outputComparison
      ? (entry.usedInOutput && !entry.compact && !entry.narrow ? "<em>已采用</em>" : "")
      : (entry.isRecommendedEvent && !entry.compact && !entry.narrow ? `<em>${contentMode ? "已选" : "推荐"}</em>` : "");
    const countFact = contentMode ? "" : `${entry.shotCount} 个镜头`;
    return `<button type="button" class="timeline-label${contentMode ? " content-match" : ""}${entry.narrow ? " narrow" : ""}${entry.compact ? " compact" : ""}${entry.isRecommendedEvent ? " recommended" : ""}${entry.active ? " active" : ""}${comparisonClass}" data-timeline-label-position="${entry.position}" data-timeline-relation="${entry.relationKey}" style="--timeline-label-left:${entry.left}px;--timeline-label-width:${entry.width}px;--timeline-label-top:${Math.max(0, labelTop)}px;--timeline-label-anchor:${anchorOffset}px" title="${escapeHtml([kindLabel, entry.title, countFact, outputComparison ? (entry.usedInOutput ? `当前${contentMode ? "内容视频" : "成片"}已采用` : `当前${contentMode ? "内容视频" : "成片"}未采用`) : "", range, duplicateFact, entry.detail].filter(Boolean).join(" · "))}" aria-label="${escapeHtml([kindLabel, entry.title, outputComparison ? (entry.usedInOutput ? "当前版本已采用" : "当前版本未采用") : (entry.isRecommendedEvent ? (contentMode ? "已选" : "AI 推荐") : "备选"), duplicateFact, entry.detail].filter(Boolean).join("，"))}"><b>${sequenceLabel}</b><span>${escapeHtml(entry.title)}</span>${statusBadge}</button>`;
  }).join("");
  const highlightTimelineRelation = (relationKey, highlighted) => {
    timelineTrackContent?.querySelectorAll("[data-timeline-relation]").forEach((element) => {
      element.classList.toggle("relation-hover", Boolean(highlighted && element.dataset.timelineRelation === relationKey));
    });
  };
  const bindTimelineRelationHover = (root) => root?.querySelectorAll("[data-timeline-relation]").forEach((button) => {
    const toggle = (active) => highlightTimelineRelation(button.dataset.timelineRelation, active);
    button.addEventListener("pointerenter", () => toggle(true));
    button.addEventListener("pointerleave", () => toggle(false));
    button.addEventListener("focus", () => toggle(true));
    button.addEventListener("blur", () => toggle(false));
  });
  labels?.querySelectorAll("[data-timeline-label-position]").forEach((button) => button.addEventListener("click", () => {
    const item = items[Number(button.dataset.timelineLabelPosition)];
    timelineFrameSelectionTime = null;
    if (contentMode && !item?._group && !item?._output) previewContentMatch(item);
    else if (item?._group) contentMode ? previewEventSegment(item._group, item) : previewEventGroup(item._group);
    else if (item?._output) seekComposedMedia(item._output, Number(item._outputSegmentIndex), Number(item.start), "output");
    else if (currentJob.status === "awaiting_confirmation") previewCandidate(Number(item.index));
    else if (item?.filename) selectOutput(item.filename, true);
    else seekTimeline(Number(item?.start || 0));
  }));
  bindTimelineRelationHover(labels);
  const clips = $("#timelineClips");
  if (clips) clips.innerHTML = duration > 0 && !contentReviewSingleLayer ? items.map((item, position) => {
    if (outputComparison && !item._output) return "";
    const isCandidate = currentJob.status === "awaiting_confirmation";
    const active = timelineItemIsActive(item);
    const groupActive = Boolean(item._group && activeCanonicalEventId === String(item._group.id || ""));
    const candidateRecommended = !item._group && recommended.has(item.index);
    const classes = ["timeline-clip", item._sourceEvent ? "source-event" : (isCandidate ? "candidate" : "output"), outputComparison && item._output ? "comparison-output-shot" : "", candidateRecommended ? "recommended" : "", groupActive ? "group-active" : "", active ? "active" : ""].filter(Boolean).join(" ");
    if (Number(item.end) <= view.start || Number(item.start) >= view.end) return "";
    const shotCaption = timelineShotCaption(item);
    const clipTitle = [item._group?.title || item.chapterTitle || item.title, shotCaption, item.role || "精彩镜头"].filter(Boolean).join(" · ");
    const clipDescription = item.reason || item.summary || item._group?.summary || "";
    const shotNumber = Number(item._timelineShotNumber || 0);
    const shotLane = Number(item._timelineShotLane || 0);
    const clipTop = layout.eventRowHeight + shotLane * shotLaneHeight + Math.max(2, (shotLaneHeight - layout.shotCardHeight) / 2);
    const { eventNumber, relationKey } = timelineRelationForItem(item, position);
    const outputSegmentAttribute = item._output ? ` data-output-segment-index="${Number(item._outputSegmentIndex)}"` : "";
    return `<button type="button" class="${classes}" data-timeline-position="${position}"${outputSegmentAttribute} data-event-sequence="${eventNumber || ""}"${relationKey ? ` data-timeline-relation="${relationKey}"` : ""} style="left:${timelinePercentInView(item.start)}%;width:${Math.max(.2, (Number(item.end) - Number(item.start)) / view.duration * 100)}%;--timeline-clip-top:${clipTop}px" title="${escapeHtml([outputComparison ? `${contentMode ? "内容视频" : "成片"}顺序 ${String(shotNumber).padStart(2, "0")}` : (eventNumber ? `${contentMode ? "片段 P" : "事件 E"}${eventNumber}` : ""), clipTitle, `${formatTime(item.start)} → ${formatTime(item.end)}`, clipDescription].filter(Boolean).join(" · "))}" aria-label="${escapeHtml([outputComparison ? `${contentMode ? "内容视频" : "成片"}顺序 ${shotNumber}` : (eventNumber ? `${contentMode ? "片段 P" : "事件 E"}${eventNumber}` : ""), clipTitle, clipDescription].filter(Boolean).join("，"))}"></button>`;
  }).join("") : "";
  clips?.querySelectorAll("[data-timeline-position]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    const item = items[Number(button.dataset.timelinePosition)];
    timelineFrameSelectionTime = null;
    if (item._group) previewEventSegment(item._group, item);
    else if (item?._output) seekComposedMedia(item._output, Number(item._outputSegmentIndex), Number(item.start), "output");
    else if (currentJob.status === "awaiting_confirmation") previewCandidate(Number(item.index));
    else selectOutput(item.filename, true);
  }));
  bindTimelineRelationHover(clips);
  const markers = $("#timelineShotMarkers");
  if (markers) markers.innerHTML = duration > 0 && !contentReviewSingleLayer ? items.map((item, position) => {
    if (outputComparison && !item._output) return "";
    const shotNumber = Number(item._timelineShotNumber || 0);
    const showMarker = shotNumber && Number(item.end) > view.start && Number(item.start) < view.end;
    if (!showMarker) return "";
    const { eventNumber, relationKey } = timelineRelationForItem(item, position);
    const active = timelineItemIsActive(item);
    const groupActive = Boolean(item._group && activeCanonicalEventId === String(item._group.id || ""));
    const markerText = String(item._timelineShotMarkerText || shotNumber);
    const markerRole = String(item._timelineShotMarkerRole || timelineShotRole(item));
    const markerWidth = Number(item._timelineShotBadgeWidth || 112);
    const markerTop = layout.eventRowHeight + Number(item._timelineShotLane || 0) * shotLaneHeight + Math.max(2, (shotLaneHeight - layout.shotCardHeight) / 2);
    const markerClasses = ["timeline-shot-marker", outputComparison && item._output ? "comparison-output-shot" : "", groupActive ? "group-active" : "", active ? "active" : ""].filter(Boolean).join(" ");
    const visibleMarkerNumber = `${contentMode ? (outputComparison ? "顺序" : "片段") : "镜头"} ${markerText}`;
    const markerContent = `<b>${escapeHtml(visibleMarkerNumber)}</b><em>${escapeHtml(markerRole)}</em>`;
    const title = [eventNumber ? `${contentMode ? "片段 P" : "事件 E"}${eventNumber}` : "", `${contentMode ? "内容片段" : "镜头"} ${shotNumber}`, markerRole, `${formatTime(item.start)} → ${formatTime(item.end)}`, item.reason || item.summary || item._group?.summary || ""].filter(Boolean).join(" · ");
    return `<button type="button" class="${markerClasses}" data-timeline-marker-position="${position}"${item._output ? ` data-output-segment-index="${Number(item._outputSegmentIndex)}"` : ""}${relationKey ? ` data-timeline-relation="${relationKey}"` : ""} style="--timeline-shot-marker-left:${Number(item._timelineShotBadgeLeft || 0)}px;--timeline-shot-marker-top:${markerTop}px;--timeline-shot-marker-width:${markerWidth}px;--timeline-shot-anchor-offset:${Number(item._timelineShotMarkerTarget || 0) - Number(item._timelineShotBadgeLeft || 0)}px" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">${markerContent}</button>`;
  }).join("") : "";
  markers?.querySelectorAll("[data-timeline-marker-position]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    const item = items[Number(button.dataset.timelineMarkerPosition)];
    timelineFrameSelectionTime = null;
    if (item?._group) previewEventSegment(item._group, item);
    else if (item?._output) seekComposedMedia(item._output, Number(item._outputSegmentIndex), Number(item.start), "output");
    else if (currentJob.status === "awaiting_confirmation") previewCandidate(Number(item.index));
    else if (item?.filename) selectOutput(item.filename, true);
    else seekTimeline(Number(item?.start || 0));
  }));
  bindTimelineRelationHover(markers);
  updateTimelineSelection();
  updateTimelinePlayhead();
  renderTimelineOverview(items);
  updateSpeakerFilterOptions(currentJob);
  renderTimelineInsights(currentJob);
  renderTimelineMediaAssets();
  drawWaveform();
  renderTimelineEventSummary();
  updateTimelineReviewControls();
  renderTimelineProposalPreview(currentJob);
}

async function loadWaveform(job) {
  if (!job || waveformJobId === job.id || Date.now() < waveformRetryAt) return;
  waveformJobId = job.id;
  waveformData = job.videoInfo ? { duration: Number(job.videoInfo.duration), hasAudio: job.videoInfo.has_audio, peaks: [], rms: [] } : null;
  const token = ++waveformRequestToken;
  setWaveformState("正在准备音频波形…", "loading");
  const slowNotice = window.setTimeout(() => {
    if (token === waveformRequestToken && currentJob?.id === job.id) {
      setWaveformState("仍在准备音频波形，长视频需要更多时间", "loading");
    }
  }, 12000);
  updateTimeline();
  try {
    const data = await api(`/api/jobs/${job.id}/waveform`);
    if (token !== waveformRequestToken || currentJob?.id !== job.id) return;
    waveformData = data;
    waveformRetryAt = 0;
    if (!timelineViewEnd) timelineViewEnd = Number(data.duration);
    setWaveformState(data.hasAudio ? "音频波形" : "源视频没有音轨", "success");
    updateTimeline();
  } catch (error) {
    if (token !== waveformRequestToken) return;
    if (currentJob?.id === job.id) {
      waveformJobId = null;
      waveformRetryAt = Date.now() + 5000;
    }
    setWaveformState(`波形不可用：${error.message}`, "error");
    updateTimeline();
  } finally {
    window.clearTimeout(slowNotice);
  }
}

function requestActionConfirmation({ title, summary, details = [], warning = "", confirmLabel = "确认执行", orderMode = null, orderItems = [], showOrderOptions = false, selectionItems = [], onDraftChange = null }) {
  return new Promise((resolve) => {
    const modal = $("#actionConfirm");
    if (!modal) return resolve(window.confirm(`${title}\n\n${summary}`));
    $("#actionConfirmTitle").textContent = title;
    $("#actionConfirmSummary").textContent = summary;
    $("#actionConfirmDetails").innerHTML = details.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    $("#actionConfirmWarning").textContent = warning;
    const orderWrap = $("#actionConfirmOrderWrap");
    const orderSelect = $("#actionConfirmOrder");
    const orderHint = $("#actionConfirmOrderHint");
    const orderList = $("#actionConfirmOrderList");
    const selectionList = $("#actionConfirmSelectionList");
    let mutableOrder = orderItems.map((item) => ({ ...item }));
    const orderHints = {
      selection: "按照你当前勾选/加入选区的先后合成，不会自动调换。",
      source: "按镜头在源视频中的时间先后排序，适合纪实、访谈和过程记录。",
      llm_recommend: "LLM 只推荐排列顺序，不会增加、删除或改变任何镜头起止点；完成后还会再次请你确认。",
    };
    orderWrap?.classList.toggle("content-order-enabled", Boolean(orderMode && showOrderOptions));
    orderWrap?.classList.toggle("hidden", !orderMode || !showOrderOptions);
    orderList?.classList.toggle("hidden", !orderItems.length);
    if (selectionList) {
      selectionList.classList.toggle("hidden", !selectionItems.length);
      selectionList.innerHTML = selectionItems.map((item, index) => `<label class="${item.disabled ? "disabled" : ""}"><input type="checkbox" data-confirm-selection="${index}" value="${escapeHtml(item.value)}" ${item.checked && !item.disabled ? "checked" : ""} ${item.disabled ? "disabled" : ""}><span><b>${escapeHtml(item.label)}</b><small>${escapeHtml(item.meta || (item.disabled ? "当前不可保留" : "正式成片"))}</small></span></label>`).join("");
    }
    const renderOrderList = () => {
      if (!orderList) return;
      const selectedMode = orderSelect?.value || orderMode;
      const editable = selectedMode === "selection";
      const heading = editable ? "可手动调整镜头顺序" : selectedMode === "llm_recommend" ? "已选镜头 · LLM 推荐后再次确认" : "已选镜头 · 将按源时间排序";
      orderList.innerHTML = `<small>${heading}</small>${mutableOrder.map((item, index) => `<div><b>${index + 1}</b><span>${escapeHtml(item.label || item.title || `镜头 ${index + 1}`)}<em>${escapeHtml(item.meta || "")}</em></span>${editable ? `<button type="button" data-order-up="${index}" ${index === 0 ? "disabled" : ""}>↑</button><button type="button" data-order-down="${index}" ${index === mutableOrder.length - 1 ? "disabled" : ""}>↓</button>` : ""}</div>`).join("")}`;
      orderList?.querySelectorAll("[data-order-up]").forEach((button) => button.addEventListener("click", () => { const index = Number(button.dataset.orderUp); [mutableOrder[index - 1], mutableOrder[index]] = [mutableOrder[index], mutableOrder[index - 1]]; renderOrderList(); onDraftChange?.({ orderMode: orderSelect?.value || orderMode, orderedItems: mutableOrder }); }));
      orderList?.querySelectorAll("[data-order-down]").forEach((button) => button.addEventListener("click", () => { const index = Number(button.dataset.orderDown); [mutableOrder[index], mutableOrder[index + 1]] = [mutableOrder[index + 1], mutableOrder[index]]; renderOrderList(); onDraftChange?.({ orderMode: orderSelect?.value || orderMode, orderedItems: mutableOrder }); }));
    };
    if (orderSelect && orderMode) orderSelect.value = orderMode;
    renderOrderList();
    if (orderHint) orderHint.textContent = orderHints[orderSelect?.value || orderMode] || "";
    const confirmButton = $("#actionConfirmOk");
    confirmButton.textContent = confirmLabel;
    const syncSelectionState = () => {
      if (selectionItems.length) confirmButton.disabled = !selectionList?.querySelector("input:not(:disabled):checked");
      else confirmButton.disabled = false;
    };
    selectionList?.querySelectorAll("input").forEach((input) => input.addEventListener("change", syncSelectionState));
    syncSelectionState();
    modal.classList.remove("hidden");
    const finish = (value) => { modal.classList.add("hidden"); cleanup(); resolve(value); };
    const cleanup = () => {
      $("#actionConfirmOk").removeEventListener("click", onOk);
      $("#actionConfirmCancel").removeEventListener("click", onCancel);
      $("#actionConfirmClose").removeEventListener("click", onCancel);
      orderSelect?.removeEventListener("change", onOrderChange);
      selectionList?.querySelectorAll("input").forEach((input) => input.removeEventListener("change", syncSelectionState));
      confirmButton.disabled = false;
      document.removeEventListener("keydown", onKey);
    };
    const onOk = () => {
      if (selectionItems.length) {
        const selectedValues = [...selectionList.querySelectorAll("input:not(:disabled):checked")].map((input) => input.value);
        if (!selectedValues.length) return;
        return finish({ confirmed: true, selectedValues });
      }
      return finish(orderMode ? { confirmed: true, orderMode: orderSelect?.value || orderMode, orderedItems: mutableOrder } : true);
    };
    const onCancel = () => finish(false);
    const onOrderChange = () => {
      if (orderHint) orderHint.textContent = orderHints[orderSelect?.value || orderMode] || "";
      renderOrderList();
      onDraftChange?.({ orderMode: orderSelect?.value || orderMode, orderedItems: mutableOrder });
    };
    const onKey = (event) => { if (event.key === "Escape") finish(false); };
    $("#actionConfirmOk").addEventListener("click", onOk);
    $("#actionConfirmCancel").addEventListener("click", onCancel);
    $("#actionConfirmClose").addEventListener("click", onCancel);
    orderSelect?.addEventListener("change", onOrderChange);
    document.addEventListener("keydown", onKey);
  });
}

function describeEditCommand(value) {
  let total = value.match(/(?:整批|总时长|(?:单条)?成片(?:总|目标)?时长).*?(\d+(?:\.\d+)?)\s*(?:秒|s)/i);
  if (total) return `把单条成片目标调整为 ${total[1]} 秒，并重新分配各事件的镜头时长`;
  let match = value.match(/选中(?:的)?(?:片段|区间)?.*?(?:扩大|扩展)\s*(\d+(?:\.\d+)?)\s*(?:秒|s)/i);
  if (match) return `将当前时间轴选区总时长增加 ${match[1]} 秒（开头和结尾各扩展 ${Number(match[1]) / 2} 秒）`;
  match = value.match(/第\s*([一二两三四五六七八\d]+)\s*条.*?(增加|延长|缩短|减少).*?(\d+(?:\.\d+)?)\s*(?:秒|s)/i);
  if (match) return `调整第 ${match[1]} 条候选：${match[2]} ${match[3]} 秒`;
  match = value.match(/(?:删除|移除).*?第\s*([一二两三四五六七八\d]+)\s*条/);
  if (match) return `从候选列表删除第 ${match[1]} 条`;
  match = value.match(/(?:复制|拷贝).*?第\s*([一二两三四五六七八\d]+)\s*条/);
  if (match) return `复制第 ${match[1]} 条候选，副本默认不勾选`;
  match = value.match(/第\s*([一二两三四五六七八\d]+)\s*条.*?(?:拆分|拆成|分成)/);
  if (match) return `将第 ${match[1]} 条候选从中点拆成两个独立候选`;
  match = value.match(/合并第\s*([一二两三四五六七八\d]+)\s*条(?:和|与|、)第?\s*([一二两三四五六七八\d]+)\s*条/);
  if (match) return `合并第 ${match[1]} 条与第 ${match[2]} 条；中间间隔也会包含在新片段内`;
  match = value.match(/第\s*([一二两三四五六七八\d]+)\s*条.*?(?:移到|移动到)第\s*([一二两三四五六七八\d]+)\s*条/);
  if (match) return `将第 ${match[1]} 条移动到第 ${match[2]} 条的位置`;
  match = value.match(/第\s*([一二两三四五六七八\d]+)\s*条.*?(?:命名为|取名为|改名为|叫做|名称为)\s*(.+)$/);
  if (match) return `把第 ${match[1]} 条候选命名为“${match[2].trim()}”`;
  if (/裁剪.*选中|选中.*裁剪/.test(value)) return "只按当前手动选区开始裁剪并生成视频";
  const named = currentJob?.candidates?.find((item) => item.title && value.includes(item.title));
  if (named && /(?:删除|移除|去掉|不要)/.test(value)) return `从候选列表删除“${named.title}”`;
  if (named && /(?:复制|拷贝)/.test(value)) return `复制候选“${named.title}”，副本默认不勾选`;
  if (named && /(?:拆分|拆成|分成)/.test(value)) return `将候选“${named.title}”拆成两个独立候选`;
  return null;
}

function setDirectorState(text, running = false) {
  const state = $("#directorState");
  const dot = $("#directorDot");
  if (state) state.textContent = text;
  dot?.classList.toggle("running", running);
}

function directorStatusForJob(job = currentJob) {
  return displayStatusForJob(job);
}

function jobOutputVersionCount(job = currentJob) {
  return jobOutputVersions(job).filter((version) => (version.outputs || []).length > 0).length;
}

function jobResultSummary(job = currentJob) {
  const outputCount = jobOutputCount(job);
  if (!outputCount) return "";
  const contentMode = String(job?.taskMode || "") === "content_extract";
  const versionCount = jobOutputVersionCount(job);
  if (contentMode) return `${outputCount} 条内容视频`;
  return `${versionCount} 个版本${outputCount !== versionCount ? ` · ${outputCount} 条视频` : ""}`;
}

function displayStatusForJob(job = currentJob) {
  if (!job) return { text: "等待素材", running: false, className: "empty" };
  const status = String(job.status || "");
  const result = jobResultSummary(job);
  const suffix = result ? ` · ${result}` : "";
  if (status === "failed") return { text: `处理失败${result ? ` · 已保留 ${result}` : ""}`, running: false, className: "failed" };
  if (status === "cancelled") return { text: `已取消${suffix}`, running: false, className: "cancelled" };
  if (status === "cancelling") return { text: `正在停止${suffix}`, running: false, className: "cancelling" };
  if (status === "awaiting_model_decision") return { text: "等待你处理模型阶段", running: false, className: "awaiting-model-decision" };
  if (status === "brief_confirmation") return { text: "等待你确认需求", running: false, className: "brief-confirmation" };
  if (status === "awaiting_content_confirmation") return { text: `等待确认内容片段${suffix}`, running: false, className: "awaiting-content-confirmation" };
  if (status === "awaiting_confirmation") return { text: `等待确认高光${suffix}`, running: false, className: "awaiting-confirmation" };
  if (status === "completed") return { text: `已完成${suffix}`, running: false, className: "completed" };
  if (status === "briefing") return { text: "正在理解需求", running: false, className: "briefing" };
  if (status === "queued") return { text: `排队中 · 尚未开始处理${suffix}`, running: false, className: "queued" };

  const autoCompositionStatus = String(job.autoComposition?.status || "");
  if (["queued", "running"].includes(autoCompositionStatus)) {
    const completed = Math.max(0, Number(job.autoComposition?.completedVersions) || 0);
    const total = Math.max(0, Number(job.autoComposition?.totalVersions) || 0);
    return {
      text: total > 0 ? `正在生成成片 · 已完成 ${Math.min(completed, total)}/${total} 个` : "正在生成成片",
      running: true,
      className: "running",
    };
  }
  const rendering = ["rendering", "render", "edit_planning", "auto_composition"].includes(String(job.stage || ""));
  return { text: rendering ? "正在生成成片" : "正在处理", running: isPipelineRunningStatus(status), className: "running" };
}

function updateDirectorState(job = currentJob) {
  const status = directorStatusForJob(job);
  setDirectorState(status.text, status.running);
}

function thinkingMessageMarkup(config, job = null) {
  if (!config) return "";
  const roleLabel = taskModePresentation(job).key === "content_extract" ? "内容探索助手" : "高光发现助手";
  return `<article class="chat-message assistant thinking-message" role="status">
    <span class="avatar thinking-avatar"><span class="thinking-orb-slot" data-thinking-orb data-orb-state="${escapeHtml(config.state)}" data-orb-size="30" data-orb-theme="light" data-orb-label="${escapeHtml(config.label)}"></span></span>
    <div class="bubble" data-border-beam data-beam-size="pulse-inner" data-beam-color="sunset" data-beam-theme="dark" data-beam-strength="0.58" data-beam-duration="2.25" data-beam-brightness="1.18" data-beam-saturation="1" data-beam-hue-range="16" data-beam-radius="13"><small>${roleLabel}</small><p>${escapeHtml(config.label)}</p></div>
  </article>`;
}

function compactConversationMessages(messages = []) {
  const compacted = [];
  const retryKinds = new Set(["retry", "notice"]);
  messages.forEach((message) => {
    const text = String(message?.text || "").trim();
    const kind = String(message?.kind || "");
    const previous = compacted[compacted.length - 1];
    const sameTurn = String(previous?.conversationTurnId || "") === String(message?.conversationTurnId || "");
    if (previous && retryKinds.has(kind) && sameTurn
      && String(previous.role || "") === String(message?.role || "")
      && String(previous.kind || "") === kind
      && String(previous.text || "").trim() === text) {
      previous.repeatCount = Number(previous.repeatCount || 1) + 1;
      previous.lastCreatedAt = message.createdAt || previous.lastCreatedAt;
      return;
    }
    const next = { ...message, repeatCount: 1 };
    compacted.push(next);
  });
  return compacted;
}

function analysisActivityLoader(job = {}) {
  const status = String(job.status || "");
  if (status === "queued") return { variant: "orbit", label: "等待后台开始处理" };
  if (status === "cancelling") return { variant: "orbit", label: "正在停止当前任务" };
  const context = [job.stage, job.detail, job.currentAction, job.model]
    .filter(Boolean).join(" ").toLowerCase();
  if (/(?:sensevoice|speech|audio|语音|音频|对白|声音)/.test(context)) {
    return { variant: "signal", label: "正在分析语音和声音信号" };
  }
  if (/(?:ffmpeg|render|compose|output|渲染|合成|生成成片|编码)/.test(context)) {
    return { variant: "rotor", label: "正在渲染高光成片" };
  }
  if (/(?:vlm|vision|visual|视觉|候选|镜头|画面|模型响应)/.test(context)) {
    return { variant: "matrix", label: "视觉模型正在处理候选画面" };
  }
  if (/(?:llm|plan|planning|编排|规划|叙事|结构)/.test(context)) {
    return { variant: "aperture", label: "正在规划高光叙事结构" };
  }
  return { variant: "orbit", label: "AI 分析流程正在运行" };
}

function inlineAnalysisProgressMarkup(job) {
  const contract = progressContract(job);
  const percent = Math.round(workflowProgress(job) * 100);
  const detail = contract.activity.detail || job?.currentAction || job?.detail || job?.stage || "准备分析";
  const rawStageProgress = measuredStageProgress(job);
  const stageFraction = rawStageProgress !== null ? rawStageProgress : 0;
  const stagePercent = Math.round(Math.max(0, Math.min(1, stageFraction)) * 100);
  const elapsedSeconds = processingElapsedSeconds(job);
  const workflow = taskWorkflowForJob(job);
  const phaseIndex = workflow.currentIndex;
  const phaseItems = workflow.steps;
  const stageMode = stageDisplayMode(job);
  const waiting = (isPipelineRunningStatus(job?.status) || job?.status === "briefing")
    && !["determinate", "completed"].includes(stageMode);
  const stageFact = stageProgressFact(job, stagePercent, waiting);
  const activity = analysisActivityLoader(job);
  const stageLabel = contract.stage.label || "当前阶段";
  const model = contract.activity.model || job?.model || "系统";
  const stageBarPercent = stageMode === "completed" ? 100 : stagePercent;
  const cancelling = String(job?.status || "") === "cancelling";
  const activityRunning = isPipelineRunningStatus(job?.status) || job?.status === "briefing";
  const actionLabel = cancelling ? "正在停止…" : job?.status === "queued" ? "等待处理" : "停止分析";
  return `<section id="inlineAnalysisProgress" class="inline-analysis-progress stage-${stageMode}${waiting ? " indeterminate" : ""}" data-stage-mode="${stageMode}" data-border-beam data-beam-size="pulse-inner" data-beam-color="sunset" data-beam-theme="dark" data-beam-strength="0.84" data-beam-duration="2.05" data-beam-brightness="1.42" data-beam-saturation="1.06" data-beam-hue-range="14" data-beam-radius="13" aria-label="AI 分析进度" aria-busy="${activityRunning}"><div class="inline-progress-orb"><span>流程</span><b data-inline-percent>${percent}%</b></div><div class="inline-progress-copy"><div class="inline-workflow-head"><span>流程完成度</span><b data-inline-workflow-percent>${percent}%</b></div><i class="inline-progress-track inline-workflow-track"><b data-inline-bar style="width:${percent}%"></b></i><div class="inline-current-stage"><div class="inline-progress-heading"><span class="inline-progress-activity" data-inline-activity data-generative-loader="inline" data-loader-active="${activityRunning}" data-loader-variant="${activity.variant}" data-loader-size="46" data-loader-speed="1.08" data-loader-label="${escapeHtml(activity.label)}"></span><div><small data-inline-stage-label>当前阶段 · ${escapeHtml(stageLabel)}</small><strong data-inline-detail>${escapeHtml(detail)}</strong></div></div><div class="inline-progress-meta"><span data-inline-stage-progress>${escapeHtml(stageFact)}</span><span data-inline-model>${escapeHtml(model)}</span><span data-inline-elapsed>${processingElapsedLabel(job)}</span><span data-inline-eta>${escapeHtml(progressEtaText(job, waiting))}</span></div><i class="inline-stage-progress-track" aria-hidden="true"><b data-inline-stage-bar style="width:${stageBarPercent}%"></b></i></div></div><ol class="inline-stage-chain">${phaseItems.map((label, index) => `<li class="${workflow.complete || index < phaseIndex ? "done" : index === phaseIndex ? "current" : ""}">${label}</li>`).join("")}</ol><button type="button" class="inline-progress-cancel" data-inline-cancel${cancelling || job?.status === "queued" ? " disabled" : ""}>${actionLabel}</button></section>`;
}

function autoCompositionVersionFacts(job) {
  const state = job?.autoComposition || {};
  const stateVersions = Array.isArray(state.versions) ? state.versions.length : 0;
  const savedAutoVersions = jobOutputVersions(job).filter((version) =>
    ["vlm", "narrative", "emotion", "information", "review_repair"].includes(String(version?.strategyKey || ""))
  ).length;
  const explicitCompleted = Number(state.completedVersions);
  const completed = Math.max(0, Number.isFinite(explicitCompleted) ? explicitCompleted : 0, stateVersions, savedAutoVersions);
  const configuredTotal = Number(job?.request?.autoVariantCount);
  const explicitTotal = Number(state.totalVersions);
  const authoritativeTotal = Number.isFinite(explicitTotal) && explicitTotal > 0
    ? explicitTotal
    : Number.isFinite(configuredTotal) && configuredTotal > 0 ? configuredTotal : 1;
  const total = Math.max(
    completed,
    authoritativeTotal,
    1,
  );
  const reportedProgress = Number(state.progress);
  const reviewPhases = ["review_vlm", "review_llm", "repair_render", "review_compare"];
  const reviewProgress = Math.max(0, Math.min(1, Number(state.reviewProgress) || 0));
  const ratio = state.status === "completed"
    ? 1
    : reviewPhases.includes(String(state.phase || ""))
      ? Math.min(.99, .85 + reviewProgress * .14)
      : Math.max(
        completed / total,
        Number.isFinite(reportedProgress) ? reportedProgress : 0,
      );
  const currentVersionProgress = Math.round(Math.max(0, Math.min(1, Number(state.currentVersionProgress) || 0)) * 100);
  return {
    completed,
    total,
    currentVersionProgress,
    percent: Math.round(Math.max(0, Math.min(1, ratio)) * 100),
  };
}

function autoCompositionProgressHint(job, facts) {
  const state = job?.autoComposition || {};
  const currentVersion = Math.max(1, Number(state.currentVersion) || facts.completed + 1);
  if (state.status === "queued") return `等待生成第 ${currentVersion}/${facts.total} 个版本`;
  if (state.phase === "llm_plan") return `已完成 ${facts.completed}/${facts.total} 个版本，正在规划后续剪辑版本`;
  if (state.phase === "quality_check") {
    return `已完成 ${facts.completed}/${facts.total} 个版本，正在检查第 ${currentVersion} 个版本的可播放性`;
  }
  if (state.phase === "review_vlm") return `正在检查动态成片、真实音轨和剪切点 · 审片 ${Math.round((Number(state.reviewProgress) || 0) * 100)}%`;
  if (state.phase === "review_llm") return `正在校准故事、节奏、声音连续性和目标匹配 · 审片 ${Math.round((Number(state.reviewProgress) || 0) * 100)}%`;
  if (state.phase === "repair_render") return "已保留初版，正在生成一轮局部返修样片";
  if (state.phase === "review_compare") return "正在复审返修版并与初版比较";
  const renderedSeconds = Number(state.renderedSeconds);
  const renderTotalSeconds = Number(state.renderTotalSeconds);
  const renderFact = Number.isFinite(renderedSeconds) && Number.isFinite(renderTotalSeconds) && renderTotalSeconds > 0
    ? `已处理 ${formatTime(renderedSeconds)} / ${formatTime(renderTotalSeconds)}`
    : `当前版本 ${facts.currentVersionProgress}%`;
  return `已完成 ${facts.completed}/${facts.total} 个版本，${renderFact}`;
}

function autoCompositionProgressMarkup(job) {
  const state = job?.autoComposition || {};
  const detail = state.detail || "自动成片在后台生成";
  const facts = autoCompositionVersionFacts(job);
  const { percent } = facts;
  const reviewing = ["review_vlm", "review_llm", "repair_render", "review_compare"].includes(String(state.phase || ""));
  const stateLabel = state.status === "queued" ? "等待后台启动" : reviewing ? "成片审片" : "后台运行";
  const versionHint = autoCompositionProgressHint(job, facts);
  return `<section class="auto-compose-progress" data-border-beam data-beam-size="pulse-inner" data-beam-color="sunset" data-beam-theme="dark" data-beam-strength="0.88" data-beam-duration="1.85" data-beam-brightness="1.46" data-beam-saturation="1.08" data-beam-hue-range="14" data-beam-radius="11" role="progressbar" aria-label="自动成片进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><div class="auto-compose-progress-head"><span class="thinking-orb-slot" data-thinking-orb data-orb-state="composing" data-orb-size="24" data-orb-theme="light" data-orb-label="自动成片"></span><div><small>AI 自动成片 · ${stateLabel}</small><strong data-auto-compose-detail>${escapeHtml(detail)}</strong></div><b data-auto-compose-count>${percent}%</b></div><div class="auto-compose-progress-track"><i data-auto-compose-bar style="width:${percent}%"></i></div><p data-auto-compose-versions>${escapeHtml(versionHint)}</p></section>`;
}

function updateAutoCompositionProgress(job = currentJob) {
  const panel = document.querySelector(".auto-compose-progress");
  if (!panel || !job?.autoComposition) return;
  const state = job.autoComposition;
  const facts = autoCompositionVersionFacts(job);
  const { percent } = facts;
  const countNode = panel.querySelector("[data-auto-compose-count]");
  const detailNode = panel.querySelector("[data-auto-compose-detail]");
  const bar = panel.querySelector("[data-auto-compose-bar]");
  const versionNode = panel.querySelector("[data-auto-compose-versions]");
  if (countNode) countNode.textContent = `${percent}%`;
  if (detailNode) detailNode.textContent = state.detail || "自动成片在后台生成";
  if (bar) bar.style.width = `${percent}%`;
  if (versionNode) versionNode.textContent = autoCompositionProgressHint(job, facts);
  panel.setAttribute("aria-valuenow", String(percent));
}

function updateInlineAnalysisProgress(job = currentJob) {
  const panel = $("#inlineAnalysisProgress");
  if (!panel || !job) return;
  const contract = progressContract(job);
  const percent = Math.round(workflowProgress(job) * 100);
  const detail = contract.activity.detail || job.currentAction || job.detail || job.stage || "准备分析";
  const rawStageProgress = measuredStageProgress(job);
  const stageFraction = rawStageProgress !== null ? rawStageProgress : 0;
  const stagePercent = Math.round(Math.max(0, Math.min(1, stageFraction)) * 100);
  const percentNode = panel.querySelector("[data-inline-percent]");
  const workflowPercentNode = panel.querySelector("[data-inline-workflow-percent]");
  const detailNode = panel.querySelector("[data-inline-detail]");
  const stageLabelNode = panel.querySelector("[data-inline-stage-label]");
  const stageProgressNode = panel.querySelector("[data-inline-stage-progress]");
  const modelNode = panel.querySelector("[data-inline-model]");
  const etaNode = panel.querySelector("[data-inline-eta]");
  const bar = panel.querySelector("[data-inline-bar]");
  const stageBar = panel.querySelector("[data-inline-stage-bar]");
  const activityNode = panel.querySelector("[data-inline-activity]");
  const orb = panel.querySelector(".inline-progress-orb");
  if (orb) orb.style.setProperty("--inline-progress", `${percent}%`);
  if (percentNode) percentNode.textContent = `${percent}%`;
  if (workflowPercentNode) workflowPercentNode.textContent = `${percent}%`;
  if (detailNode) detailNode.textContent = detail;
  if (stageLabelNode) stageLabelNode.textContent = `当前阶段 · ${contract.stage.label || "处理中"}`;
  const stageMode = stageDisplayMode(job);
  const waiting = (isPipelineRunningStatus(job.status) || job.status === "briefing")
    && !["determinate", "completed"].includes(stageMode);
  panel.classList.toggle("indeterminate", waiting);
  panel.classList.toggle("stage-indeterminate", stageMode === "indeterminate");
  panel.classList.toggle("stage-finalizing", stageMode === "finalizing");
  panel.classList.toggle("stage-determinate", stageMode === "determinate");
  panel.classList.toggle("stage-completed", stageMode === "completed");
  panel.dataset.stageMode = stageMode;
  panel.setAttribute("aria-busy", String(waiting));
  if (stageProgressNode) stageProgressNode.textContent = stageProgressFact(job, stagePercent, waiting);
  if (modelNode) modelNode.textContent = contract.activity.model || job.model || "系统";
  if (etaNode) etaNode.textContent = progressEtaText(job, waiting);
  if (bar) bar.style.width = `${percent}%`;
  if (stageBar) stageBar.style.width = `${stageMode === "completed" ? 100 : stagePercent}%`;
  if (activityNode) {
    const activity = analysisActivityLoader(job);
    const activityRunning = isPipelineRunningStatus(job.status) || job.status === "briefing";
    activityNode.dataset.loaderActive = String(activityRunning);
    activityNode.classList.toggle("hidden", !activityRunning);
    const changed = activityNode.dataset.loaderVariant !== activity.variant || activityNode.dataset.loaderLabel !== activity.label;
    if (changed) {
      activityNode.dataset.loaderVariant = activity.variant;
      activityNode.dataset.loaderLabel = activity.label;
    }
    if (changed || !activityNode.firstElementChild) {
      renderGenerativeLoader(activityNode, { kind: "inline", variant: activity.variant, size: 46, speed: .9, label: activity.label });
    }
  }
  const elapsed = panel.querySelector("[data-inline-elapsed]");
  if (elapsed) elapsed.textContent = processingElapsedLabel(job);
  const workflow = taskWorkflowForJob(job);
  const phaseIndex = workflow.currentIndex;
  panel.querySelectorAll(".inline-stage-chain li").forEach((item, index) => {
    item.classList.toggle("done", workflow.complete || index < phaseIndex);
    item.classList.toggle("current", !workflow.complete && index === phaseIndex);
  });
}

function commandThinkingConfig(value) {
  if (/(?:合成|组合|编排|章节|顺序|移动|合并|拆分|总时长|重新平衡)/.test(value)) {
    return { state: "shaping", label: "正在重新编排镜头与事件结构" };
  }
  if (/(?:换掉|替换|调整|增加|延长|缩短|删除|复制|命名|改名|裁剪|选区)/.test(value)) {
    return { state: "solving", label: "正在理解修改要求并检查时间边界" };
  }
  return { state: "composing", label: "正在理解你的要求" };
}

function appendTransientThinking(value) {
  const container = $("#chatMessages");
  if (!container) return [];
  const config = commandThinkingConfig(value);
  container.insertAdjacentHTML("beforeend", `<article class="chat-message user transient-message"><span class="avatar">你</span><div class="bubble"><small>你</small><p>${escapeHtml(value)}</p></div></article>${thinkingMessageMarkup(config)}`);
  const nodes = [...container.querySelectorAll(".transient-message, .thinking-message")].slice(-2);
  syncThinkingOrbs(container);
  container.scrollTop = container.scrollHeight;
  return nodes;
}

function initialConversation() {
  ensureChatMessages().innerHTML = `
    <article class="chat-message assistant"><span class="avatar">AI</span><div class="bubble"><small>视频剪辑助手</small><p>请先上传视频。之后可以选择让 AI 发现高光，或按描述搜索指定内容。</p></div></article>`;
}

function recommendedEventCountForDuration(rawSeconds) {
  const seconds = Number(rawSeconds);
  if (!Number.isFinite(seconds) || seconds <= 0) return 5;
  if (seconds < 45) return 3;
  if (seconds <= 75) return 5;
  return 6;
}

function contentScopeBaseRange(kind, duration) {
  const total = Math.max(0, Number(duration) || 0);
  const edge = Math.min(total * .15, 600);
  const ranges = {
    all: [0, total], opening: [0, edge], front_half: [0, total * .5],
    middle: [total * .25, total * .75], back_half: [total * .5, total],
    ending: [Math.max(0, total - edge), total],
  };
  return ranges[kind] || null;
}

function contentClockSeconds(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  if (text.includes(":")) {
    const parts = text.split(":").map(Number);
    if (parts.some((item) => !Number.isFinite(item))) return null;
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  const hours = Number(text.match(/(\d+(?:\.\d+)?)\s*小时/)?.[1] || 0);
  const minutes = Number(text.match(/(\d+(?:\.\d+)?)\s*(?:分钟|分)/)?.[1] || 0);
  const seconds = Number(text.match(/(\d+(?:\.\d+)?)\s*秒/)?.[1] || 0);
  return hours || minutes || seconds ? hours * 3600 + minutes * 60 + seconds : null;
}

function contentTextRange(text, duration) {
  const value = String(text || "");
  const total = Math.max(0, Number(duration) || 0);
  const token = "(\\d{1,2}:\\d{2}(?::\\d{2}(?:\\.\\d+)?)?|\\d+(?:\\.\\d+)?\\s*(?:小时|分钟|分|秒))";
  let match = value.match(new RegExp(`${token}\\s*(?:到|至|[-~～])\\s*${token}`, "i"));
  if (match) {
    const start = contentClockSeconds(match[1]);
    const end = contentClockSeconds(match[2]);
    if (start !== null && end !== null && end > start) return [Math.max(0, start), Math.min(total, end)];
  }
  match = value.match(new RegExp(`(?:最后|末尾|结尾)\\s*${token}`, "i"));
  if (match) { const span = contentClockSeconds(match[1]); if (span !== null) return [Math.max(0, total - span), total]; }
  match = value.match(new RegExp(`(?:开头|开始|最前)\\s*${token}`, "i"));
  if (match) { const span = contentClockSeconds(match[1]); if (span !== null) return [0, Math.min(total, span)]; }
  match = value.match(new RegExp(`${token}\\s*(?:附近|左右|前后)`, "i"));
  if (match) { const center = contentClockSeconds(match[1]); if (center !== null) return [Math.max(0, center - 120), Math.min(total, center + 120)]; }
  if (/前半段|前一半/.test(value)) return [0, total * .5];
  if (/后半段|后一半/.test(value)) return [total * .5, total];
  if (/(?:视频)?中间|中段/.test(value)) return [total * .25, total * .75];
  if (/(?:视频)?开头|片头/.test(value)) return contentScopeBaseRange("opening", total);
  if (/(?:视频)?结尾|片尾/.test(value)) return contentScopeBaseRange("ending", total);
  return null;
}

function activeContentEvidencePlan() {
  const selected = $("#contentEvidenceQuestion [data-content-evidence-mode].active");
  if (selected) {
    const mode = selected.dataset.contentEvidenceMode;
    const capabilities = {
      speech: ["speech"], screen_text: ["ocr"], visual: ["visual"],
      person: ["person"], sound: ["audio"],
    }[mode] || [];
    return { mode, capabilities, source: "advanced_user_override" };
  }
  // Empty means that the backend should compile the natural-language request
  // and authorize every indispensable evidence source automatically.
  return null;
}

function activeContentSearchOptions() {
  const duration = Math.max(0, Number($("#localPreviewVideo")?.duration) || 0);
  const kind = $("#chatMessages [data-content-scope].active")?.dataset.contentScope || "all";
  const customStart = kind === "custom" ? contentClockSeconds($("#contentScopeStartText")?.value) : null;
  const customEnd = kind === "custom" ? contentClockSeconds($("#contentScopeEndText")?.value) : null;
  const start = Math.max(0, customStart == null ? Number($("#contentScopeStart")?.value) || 0 : customStart);
  const end = Math.min(duration, customEnd == null ? Number($("#contentScopeEnd")?.value) || duration : customEnd);
  return {
    duration, kind, start, end,
    limit: Number($("#chatMessages [data-content-limit].active")?.dataset.contentLimit || 12),
    boundary: $("#chatMessages [data-content-boundary].active")?.dataset.contentBoundary || "complete",
    autoGenerate: Boolean($("#contentAutoGenerate")?.checked),
    exclusions: $("#contentExclusions")?.value?.trim() || "",
    evidence: activeContentEvidencePlan(),
  };
}

function syncContentSearchPreflight({ resetRange = false } = {}) {
  const localVideo = $("#localPreviewVideo");
  const duration = Math.max(0, Number(localVideo?.duration) || 0);
  const startInput = $("#contentScopeStart");
  const endInput = $("#contentScopeEnd");
  if (!startInput || !endInput) return;
  startInput.max = String(duration || 1);
  endInput.max = String(duration || 1);
  const activeScope = $("#chatMessages [data-content-scope].active")?.dataset.contentScope || "all";
  const base = contentScopeBaseRange(activeScope, duration);
  if (resetRange || base) {
    const [baseStart, baseEnd] = base || [Number(startInput.value) || 0, Number(endInput.value) || duration];
    startInput.value = String(baseStart);
    endInput.value = String(baseEnd);
  }
  let start = Math.max(0, Math.min(duration, Number(startInput.value) || 0));
  let end = Math.max(0, Math.min(duration, Number(endInput.value) || duration));
  if (start > end - .2) {
    if (document.activeElement === startInput) start = Math.max(0, end - .2);
    else end = Math.min(duration, start + .2);
    startInput.value = String(start);
    endInput.value = String(end);
  }
  const startText = $("#contentScopeStartText");
  const endText = $("#contentScopeEndText");
  if (startText && document.activeElement !== startText) startText.value = formatTime(start);
  if (endText && document.activeElement !== endText) endText.value = formatTime(end);
  const textRange = contentTextRange($("#briefContentInstruction")?.value, duration);
  const shownStart = textRange ? Math.max(start, textRange[0]) : start;
  const shownEnd = textRange ? Math.min(end, textRange[1]) : end;
  const conflict = shownEnd <= shownStart;
  const fill = $("#contentScopeFill");
  if (fill) {
    fill.style.left = `${duration ? shownStart / duration * 100 : 0}%`;
    fill.style.width = `${duration && !conflict ? Math.max(.3, (shownEnd - shownStart) / duration * 100) : 0}%`;
  }
  if ($("#contentScopeStartLabel")) $("#contentScopeStartLabel").textContent = formatTime(shownStart);
  if ($("#contentScopeEndLabel")) $("#contentScopeEndLabel").textContent = formatTime(shownEnd);
  const scopeDuration = Math.max(0, shownEnd - shownStart);
  if ($("#contentScopeDurationLabel")) $("#contentScopeDurationLabel").textContent = conflict ? "时间条件冲突" : `${formatTime(scopeDuration)} 范围`;
  const file = videoInput.files[0];
  if ($("#contentMaterialFacts") && file) {
    const orientation = localVideo?.videoWidth && localVideo?.videoHeight
      ? (localVideo.videoHeight > localVideo.videoWidth ? "竖屏" : localVideo.videoHeight === localVideo.videoWidth ? "方形" : "横屏")
      : "读取中";
    const resolution = localVideo?.videoWidth ? `${localVideo.videoWidth}×${localVideo.videoHeight}` : "分辨率读取中";
    $("#contentMaterialFacts").textContent = `${formatTime(duration)}，${resolution}，${orientation}，${(file.size / 1024 / 1024).toFixed(1)} MB`;
  }
  const fraction = duration ? scopeDuration / duration : 1;
  const cost = fraction <= .25 ? "较低" : fraction <= .60 ? "中等" : "较高";
  if ($("#contentSearchCost")) $("#contentSearchCost").textContent = conflict
    ? "文字时间与位置选项没有交集，请调整范围"
    : `扫描 ${formatTime(scopeDuration)}，约占全片 ${Math.round(fraction * 100)}%，检索成本${cost}`;
  const query = $("#briefContentInstruction")?.value.trim() || "你描述的内容";
  if ($("#contentEvidencePlan")) $("#contentEvidencePlan").innerHTML =
    `<span>系统自动判断</span><b>根据描述组合必要的音画证据</b><small>无需选择对白、文字、画面、人物或声音；只有检索含义存在歧义时才会询问</small>`;
  const limitLabel = activeContentSearchOptions().limit === 12 ? "全部可靠结果" : `最多 ${activeContentSearchOptions().limit} 段`;
  const boundaryLabel = ({ exact: "匹配时刻", complete: "完整句子或动作", context: "完整内容并保留前后 2 秒" })[activeContentSearchOptions().boundary];
  if ($("#contentQueryPreview")) $("#contentQueryPreview").textContent = conflict
    ? "当前时间条件互相冲突，调整后才能开始检索。"
    : `将在 ${formatTime(shownStart)} 到 ${formatTime(shownEnd)} 查找“${query}”，返回${limitLabel}，保留${boundaryLabel}。`;
  $(".content-query-preview")?.classList.toggle("conflict", conflict);
}

function showBriefCard(file) {
  ensureChatMessages().innerHTML = `
    <article class="chat-message user"><span class="avatar">你</span><div class="bubble"><small>你</small><p>已选择 ${escapeHtml(file.name)}</p></div></article>
    <article class="chat-message assistant brief-message"><span class="avatar">AI</span><div class="brief-wrap">
      <div class="bubble"><small>视频剪辑助手</small><p>视频已就绪。不确定哪段精彩，可以让 AI 通看全片；已经知道要找什么，可以直接搜索内容。</p></div>
      <section class="brief-card brief-card-redesign">
        <header class="brief-card-header"><div><small>剪辑目标</small><strong>这次想怎么剪？</strong><p>先选成片方向，其他要求都可以稍后调整。</p></div><span class="brief-ready-badge">视频已就绪</span></header>
        <section class="brief-section brief-task-section"><div class="brief-section-heading"><b>1</b><div><strong>任务模式</strong><small>两种模式目标不同，后续流程也会分别展示</small></div></div><div class="brief-choice-grid"><button type="button" class="brief-choice active" data-task-mode="highlight"><b>高光发现</b><span>不知道具体片段？让 AI 通看全片，发现精彩事件并生成多个版本。</span></button><button type="button" class="brief-choice" data-task-mode="content_extract"><b>内容探索</b><span>知道想找什么？搜索对白、人物、屏幕文字、动作、场景和声音。</span></button></div></section>
        <section class="brief-section brief-storage-section"><div class="brief-section-heading"><b>存</b><div><strong>任务保留方式</strong><small>一次性任务会在你确认成片后清理源素材和工程缓存</small></div></div><div class="brief-choice-grid"><button type="button" class="brief-choice active" data-storage-mode="editable"><b>保留可编辑工程</b><span>默认选项。保留素材、时间线和分析结果，之后可以继续修改。</span></button><button type="button" class="brief-choice" data-storage-mode="one_off"><b>一次性使用</b><span>成片确认后单独保存 MP4，再由你确认清理工程占用。</span></button></div></section>
        <section id="contentInstructionSection" class="brief-section brief-content-only hidden"><div class="brief-section-heading"><b>2</b><div><strong>要截取什么？</strong><small>先限定范围，再从对白和真实画面中查找</small></div></div>
          <div class="content-material-overview"><div><strong>素材概况</strong><span id="contentMaterialFacts">正在读取视频信息</span></div><div><strong>严格按需</strong><span>只运行本次查找需要的能力，未找到时先询问再扩展</span></div></div>
          <label class="brief-theme"><span>内容描述</span><textarea id="briefContentInstruction" maxlength="500" rows="3" placeholder="例如：找出后半段 Speaker 1 介绍离线功能的完整发言"></textarea><small class="brief-field-help">可以描述对白、屏幕文字、匿名人物、动作、场景、物体或声音，也可以直接写“10 分钟附近”。</small></label>
          <div id="contentEvidencePlan" class="content-query-preview"><span>系统自动判断</span><b>根据描述组合必要的音画证据</b><small>无需选择技术能力；只有检索含义存在歧义时才会询问</small></div>
          <div class="content-search-conditions">
            <div class="content-condition-row"><span>大概位置</span><div class="content-condition-options content-scope-options"><button type="button" class="active" data-content-scope="all">全片</button><button type="button" data-content-scope="opening">开头</button><button type="button" data-content-scope="front_half">前半段</button><button type="button" data-content-scope="middle">中间</button><button type="button" data-content-scope="back_half">后半段</button><button type="button" data-content-scope="ending">结尾</button><button type="button" data-content-scope="custom">自定义</button></div></div>
            <div class="content-scope-timeline" aria-label="内容检索时间范围"><div class="content-scope-track"><i id="contentScopeFill"></i></div><input id="contentScopeStart" type="range" min="0" max="1" step="0.1" value="0" aria-label="检索开始时间"><input id="contentScopeEnd" type="range" min="0" max="1" step="0.1" value="1" aria-label="检索结束时间"><footer><span id="contentScopeStartLabel">00:00.0</span><b id="contentScopeDurationLabel">全片</b><span id="contentScopeEndLabel">00:00.0</span></footer><div id="contentScopeCustomFields" class="content-scope-custom-fields hidden"><label>开始 <input id="contentScopeStartText" type="text" inputmode="decimal" placeholder="00:00.0"></label><label>结束 <input id="contentScopeEndText" type="text" inputmode="decimal" placeholder="02:00.0"></label><small>支持 90、01:30、1 分 30 秒</small></div></div>
            <div class="content-condition-row"><span>返回数量</span><div class="content-condition-options"><button type="button" data-content-limit="1">最相关 1 段</button><button type="button" data-content-limit="3">前 3 段</button><button type="button" class="active" data-content-limit="12">全部可靠结果</button></div></div>
            <div class="content-condition-row"><span>片段边界</span><div class="content-condition-options"><button type="button" data-content-boundary="exact">匹配时刻</button><button type="button" class="active" data-content-boundary="complete">完整句子或动作</button><button type="button" data-content-boundary="context">前后保留 2 秒</button></div></div>
            <div class="content-query-preview"><small>本次检索</small><p id="contentQueryPreview">将在全片查找你描述的内容，返回全部可靠结果，并保留完整片段。</p><span id="contentSearchCost">扫描全片，检索成本较高</span></div>
          </div>
          <details class="content-more-conditions"><summary>更多条件 <span>排除内容和自动生成</span></summary><div><label><span>排除内容</span><input id="contentExclusions" maxlength="300" placeholder="例如：片头、重复画面、Speaker 2"><small class="brief-field-help">用逗号分隔，只影响内容检索，不改变源视频。</small></label><label class="content-auto-generate"><input id="contentAutoGenerate" type="checkbox"><span><strong>可靠结果直接生成</strong><small>低置信度或边界不确定时仍会先让你确认。</small></span></label></div></details>
        </section>
        <section class="brief-section brief-intent-section brief-highlight-only"><div class="brief-section-heading"><b>2</b><div><strong>成片方式</strong><small>AI 会先找出真实事件，再组合成高光成片</small></div></div><div class="brief-choice-grid"><button type="button" class="brief-choice active" data-brief-mode="auto"><b>AI 自动发现</b><span>由 AI 推荐合理的事件数量和时长</span></button><button type="button" class="brief-choice" data-brief-mode="specified"><b>设置事件上限</b><span>最多推荐指定数量，不会为了凑数降低质量</span></button></div><p class="brief-mode-note">先发现真实视觉事件，再推荐合理数量和各自时长，不凑数。</p><div id="briefExplicitFields" class="brief-fields brief-inline-field hidden"><label><span>最多推荐几个事件</span><div><input id="briefCount" type="number" min="1" max="8" value="5"><b>个</b></div><small class="brief-field-help">系统会结合目标时长设置默认上限；高质量事件不足时不会凑数。</small></label></div></section>
        <section class="brief-section brief-goal-section brief-highlight-only"><div class="brief-section-heading"><b>3</b><div><strong>成片要求</strong><small>可选，不填则由 AI 综合判断</small></div></div><div class="brief-goal-grid"><label class="brief-theme"><span>单条成片目标时长</span><div class="brief-input-with-unit"><input id="briefTotalDuration" type="number" min="4" max="86400" step="0.1" value="60" placeholder="AI 推荐"><b>秒</b></div><small class="brief-field-help">每个自动成片版本都会参考该时长；实际时长会随素材完整性浮动。</small></label><label class="brief-theme"><span>重点关注</span><input id="briefTheme" maxlength="500" placeholder="例如：人物反应、动作高潮"><small class="brief-field-help">用于候选排序；留空则综合判断。</small></label></div><div class="brief-chips duration-chips"><small>时长</small><button type="button" data-total-duration="30">30 秒</button><button type="button" class="active" data-total-duration="60">60 秒</button><button type="button" data-total-duration="90">90 秒</button><button type="button" data-total-duration="">AI 推荐</button></div><div class="brief-chips"><small>重点</small><button type="button" data-brief-theme="人物反应">人物反应</button><button type="button" data-brief-theme="动作高潮">动作高潮</button><button type="button" data-brief-theme="视觉冲击">视觉冲击</button><button type="button" data-brief-theme="">综合判断</button></div></section>
        <section class="brief-section brief-analysis-section brief-highlight-only"><div class="brief-section-heading"><b>4</b><div><strong>分析信号</strong><small>有对白或环境声时推荐视听综合</small></div></div><div class="brief-segmented"><button type="button" data-analysis-mode="visual">纯视觉</button><button type="button" class="active" data-analysis-mode="audiovisual">视听综合 · SenseVoice</button></div></section>
        <section class="brief-section brief-technique-section brief-highlight-only"><div class="brief-section-heading"><b>5</b><div><strong>剪辑策略</strong><small>决定如何压缩节奏和衔接镜头，不改变你选择的内容</small></div></div><div class="brief-technique-presets"><button type="button" class="active" data-technique-preset="auto"><b>AI 自适应</b><span>按语音、动作和事件关系克制使用剪辑手法</span></button><button type="button" data-technique-preset="natural"><b>自然连贯</b><span>少变速、少转场，优先完整表达</span></button><button type="button" data-technique-preset="tight"><b>紧凑高光</b><span>压缩停顿和无对白过程，保持可理解</span></button><button type="button" data-technique-preset="attraction"><b>吸引力优先</b><span>允许更强节奏，但对白和高潮仍受保护</span></button></div><details class="brief-technique-options"><summary>可使用的剪辑手法</summary><div class="brief-technique-toggles"><label><input type="checkbox" data-technique-option="allowSpeed" checked>安全变速</label><label><input type="checkbox" data-technique-option="allowTransitions" checked>语义转场</label><label><input type="checkbox" data-technique-option="allowAudioBridges" checked>声音桥接</label><label><input type="checkbox" data-technique-option="allowCutaways" checked>反应/细节插入镜头</label><label><input type="checkbox" data-technique-option="allowSilenceCompression" checked>压缩无语义停顿</label><label><input type="checkbox" data-technique-option="allowColdOpen">结果前置开场</label></div><p>AI 只在证据允许时使用；手动选择的镜头不会因目标时长不足被自动删除。</p></details></section>
        <details class="brief-advanced-options"><summary>高级分析选项 <span>默认设置适合大多数视频</span></summary><div class="brief-advanced-body"><div class="brief-mode brief-cache-mode"><span>分析策略</span><div><button type="button" class="active" data-cache-policy="refresh">重新分析</button><button type="button" data-cache-policy="reuse">复用缓存</button></div><small class="brief-field-help">只有视频和剪辑要求都没有变化时，才建议复用缓存。</small></div><p class="brief-cache-note">默认重新调用视觉模型；源文件、波形和播放代理仍会复用。</p><div class="brief-mode brief-variant-mode"><span>自动成片版本</span><div><button type="button" data-auto-variants="1">1 版</button><button type="button" data-auto-variants="2">2 版</button><button type="button" class="active" data-auto-variants="3">3 版</button><button type="button" data-auto-variants="4">4 版</button></div><small class="brief-field-help">包含 1 个完整事件版，其余版本由剪辑规划模型按不同策略重新编排。</small></div></div></details>
        <div class="brief-fields brief-production-fields brief-advanced-hidden"><label><span>字幕（推荐）</span><select id="briefSubtitleMode"><option value="none" selected>不添加字幕</option><option value="ask">稍后确认</option><option value="burn">添加字幕</option><option value="custom">自定义</option></select><small class="brief-field-help">字幕设置已移至成片阶段的高级设置。</small><input class="brief-custom-input hidden" id="briefSubtitleCustom" placeholder="例如：只添加重点对白字幕"></label><label><span>剪辑方式（推荐）</span><select id="briefEditMode"><option value="ai_plan" selected>AI 智能规划</option><option value="recommend_review">AI 推荐后我审核</option><option value="manual">我手动选择镜头</option><option value="custom">自定义</option></select><small class="brief-field-help">剪辑方式由当前时间轴和事件审核流程统一处理。</small><input class="brief-custom-input hidden" id="briefEditCustom" placeholder="例如：先给我 3 个版本再选择"></label></div>
        <label class="brief-theme brief-advanced-hidden"><span>成片结构</span><select id="briefStructure"><option value="auto" selected>由 AI 根据素材决定</option><option value="hook_story_result">连贯叙事（素材具备时）</option><option value="montage">节奏剪辑，优先连续精彩瞬间</option><option value="custom">自定义</option></select><small class="brief-field-help">自动模式会按素材完整性决定结构，不会为了补齐固定段落加入低价值镜头。</small><input class="brief-custom-input hidden" id="briefStructureCustom" placeholder="例如：先展示结果，再补充关键过程"></label>
        <footer class="brief-submit-row"><span id="briefSubmitHint">确认后会分析素材，并在后台自动生成成片版本</span><button id="startAnalysisButton" class="brief-submit" type="button"><span>开始分析并自动生成成片</span><b>→</b></button></footer>
      </section>
    </div></article>`;
  let briefCountTouched = false;
  const briefCountInput = $("#briefCount");
  const briefTotalDurationInput = $("#briefTotalDuration");
  const syncRecommendedBriefCount = () => {
    if (briefCountTouched || !briefCountInput) return;
    briefCountInput.value = String(recommendedEventCountForDuration(briefTotalDurationInput?.value));
  };
  briefCountInput?.addEventListener("input", () => { briefCountTouched = true; });
  briefCountInput?.addEventListener("change", () => { briefCountTouched = true; });
  briefTotalDurationInput?.addEventListener("input", syncRecommendedBriefCount);
  briefTotalDurationInput?.addEventListener("change", syncRecommendedBriefCount);
  syncRecommendedBriefCount();
  const syncTaskMode = (mode) => {
    const contentMode = mode === "content_extract";
    $("#chatMessages")?.querySelectorAll(".brief-content-only").forEach((node) => node.classList.toggle("hidden", !contentMode));
    $("#chatMessages")?.querySelectorAll(".brief-highlight-only, .brief-advanced-options, .brief-production-fields, .brief-card > .brief-advanced-hidden").forEach((node) => node.classList.toggle("hidden", contentMode));
    if ($("#briefSubmitHint")) $("#briefSubmitHint").textContent = contentMode
      ? "先确认查找依据，只运行本次需要的能力；候选确认后才会生成视频"
      : "确认后会分析素材，并在后台自动生成成片版本";
    if ($("#startAnalysisButton span")) $("#startAnalysisButton span").textContent = contentMode
      ? "上传并查找内容"
      : "开始分析并自动生成成片";
  };
  $("#chatMessages")?.querySelectorAll("[data-task-mode]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-task-mode]").forEach((item) => item.classList.toggle("active", item === button));
    syncTaskMode(button.dataset.taskMode || "highlight");
  }));
  $("#chatMessages")?.querySelectorAll("[data-storage-mode]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-storage-mode]").forEach((item) => item.classList.toggle("active", item === button));
  }));
  $("#chatMessages")?.querySelectorAll("[data-content-scope]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-content-scope]").forEach((item) => item.classList.toggle("active", item === button));
    $("#contentScopeCustomFields")?.classList.toggle("hidden", button.dataset.contentScope !== "custom");
    $(".content-scope-timeline")?.classList.toggle("is-custom", button.dataset.contentScope === "custom");
    syncContentSearchPreflight({ resetRange: button.dataset.contentScope !== "custom" });
  }));
  [$("#contentScopeStart"), $("#contentScopeEnd")].forEach((input) => input?.addEventListener("input", () => {
    $("#chatMessages")?.querySelectorAll("[data-content-scope]").forEach((item) => item.classList.toggle("active", item.dataset.contentScope === "custom"));
    $("#contentScopeCustomFields")?.classList.remove("hidden");
    $(".content-scope-timeline")?.classList.add("is-custom");
    syncContentSearchPreflight();
  }));
  [$("#contentScopeStartText"), $("#contentScopeEndText")].forEach((input) => input?.addEventListener("change", () => {
    const seconds = contentClockSeconds(input.value);
    const duration = Math.max(0, Number($("#localPreviewVideo")?.duration) || 0);
    if (seconds == null || seconds < 0 || seconds > duration) return void showToast("自定义时间必须在视频范围内，例如 01:30");
    if (input.id === "contentScopeStartText") $("#contentScopeStart").value = String(seconds);
    else $("#contentScopeEnd").value = String(seconds);
    syncContentSearchPreflight();
  }));
  $("#chatMessages")?.querySelectorAll("[data-content-limit]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-content-limit]").forEach((item) => item.classList.toggle("active", item === button));
    syncContentSearchPreflight();
  }));
  $("#chatMessages")?.querySelectorAll("[data-content-boundary]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-content-boundary]").forEach((item) => item.classList.toggle("active", item === button));
    syncContentSearchPreflight();
  }));
  [$("#briefContentInstruction"), $("#contentExclusions"), $("#contentAutoGenerate")].forEach((input) => input?.addEventListener("input", () => syncContentSearchPreflight()));
  $("#chatMessages")?.querySelectorAll("[data-brief-mode]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-brief-mode]").forEach((item) => item.classList.toggle("active", item === button));
    const automatic = button.dataset.briefMode === "auto";
    $("#briefExplicitFields")?.classList.toggle("hidden", automatic);
    if (!automatic) syncRecommendedBriefCount();
    $(".brief-mode-note").textContent = automatic
      ? "先发现真实视觉事件，再推荐合理数量和各自时长，不凑数。"
      : "最多推荐这个数量的高质量事件；如果素材不足，不会强行补足。";
    $("#startAnalysisButton span").textContent = "开始分析并自动生成成片";
  }));
  $("#chatMessages")?.querySelectorAll("[data-brief-theme]").forEach((button) => button.addEventListener("click", () => {
    $("#briefTheme").value = button.dataset.briefTheme;
    $("#chatMessages")?.querySelectorAll("[data-brief-theme]").forEach((item) => item.classList.toggle("active", item === button));
  }));
  $("#chatMessages")?.querySelectorAll("[data-analysis-mode]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-analysis-mode]").forEach((item) => item.classList.toggle("active", item === button));
  }));
  $("#chatMessages")?.querySelectorAll("[data-cache-policy]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-cache-policy]").forEach((item) => item.classList.toggle("active", item === button));
    $(".brief-cache-note").textContent = button.dataset.cachePolicy === "reuse"
      ? "相同视频、要求和模型命中时直接读取已有候选，不产生新的 VLM 调用。"
      : "重新调用 VLM 发现和精修候选；源文件、波形和播放代理仍会复用。";
  }));
  $("#chatMessages")?.querySelectorAll("[data-auto-variants]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-auto-variants]").forEach((item) => item.classList.toggle("active", item === button));
  }));
  $("#chatMessages")?.querySelectorAll("[data-technique-preset]").forEach((button) => button.addEventListener("click", () => {
    $("#chatMessages")?.querySelectorAll("[data-technique-preset]").forEach((item) => item.classList.toggle("active", item === button));
  }));
  $("#chatMessages")?.querySelectorAll("[data-total-duration]").forEach((button) => button.addEventListener("click", () => {
    $("#briefTotalDuration").value = button.dataset.totalDuration;
    $("#chatMessages")?.querySelectorAll("[data-total-duration]").forEach((item) => item.classList.toggle("active", item === button));
    syncRecommendedBriefCount();
  }));
  [["#briefSubtitleMode", "#briefSubtitleCustom"], ["#briefEditMode", "#briefEditCustom"], ["#briefStructure", "#briefStructureCustom"]].forEach(([select, input]) => {
    $(select)?.addEventListener("change", () => $(input)?.classList.toggle("hidden", $(select).value !== "custom"));
  });
  $("#startAnalysisButton").addEventListener("click", createJobFromBrief);
  syncContentSearchPreflight({ resetRange: true });
  // The brief is the next action after upload. Keep it at the top of the
  // conversation viewport so users never have to scroll back up to find it.
  const briefCard = $("#chatMessages .brief-card");
  const chat = $("#chatMessages");
  if (briefCard && chat) {
    requestAnimationFrame(() => {
      chat.scrollTop = Math.max(0, briefCard.offsetTop - 12);
      briefCard.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
}

async function createJobFromBrief() {
  if (!videoInput.files.length || actionBusy) return;
  const createGeneration = workspaceGeneration;
  const taskMode = $("#chatMessages [data-task-mode].active")?.dataset.taskMode || "highlight";
  const storageMode = $("#chatMessages [data-storage-mode].active")?.dataset.storageMode || "editable";
  const contentInstruction = $("#briefContentInstruction")?.value.trim() || "";
  const contentSearchOptions = activeContentSearchOptions();
  const automatic = $("#chatMessages [data-brief-mode].active")?.dataset.briefMode === "auto";
  const count = automatic ? "auto" : Number($("#briefCount").value);
  const rawTotalDuration = $("#briefTotalDuration").value.trim();
  const targetSeconds = rawTotalDuration ? Number(rawTotalDuration) : "auto";
  const theme = $("#briefTheme").value.trim();
  const subtitleChoice = $("#briefSubtitleMode").value;
  const editChoice = $("#briefEditMode").value;
  const structureChoice = $("#briefStructure").value;
  const subtitleMode = subtitleChoice === "custom" ? ($("#briefSubtitleCustom").value.trim() || "none") : subtitleChoice;
  const editMode = editChoice === "custom" ? ($("#briefEditCustom").value.trim() || "ai_plan") : editChoice;
  const structure = structureChoice === "custom" ? ($("#briefStructureCustom").value.trim() || "auto") : structureChoice;
  const requestTheme = [theme, `字幕策略：${subtitleMode}`, `剪辑方式：${editMode}`, `成片结构：${structure}`].filter(Boolean).join("；");
  const analysisMode = $("#chatMessages [data-analysis-mode].active")?.dataset.analysisMode || "audiovisual";
  const forceReanalyze = $("#chatMessages [data-cache-policy].active")?.dataset.cachePolicy !== "reuse";
  const autoVariantCount = Number($("#chatMessages [data-auto-variants].active")?.dataset.autoVariants || 3);
  const techniquePreset = $("#chatMessages [data-technique-preset].active")?.dataset.techniquePreset || "auto";
  const techniqueOption = (name) => Boolean($(`#chatMessages [data-technique-option="${name}"]`)?.checked);
  if (taskMode === "content_extract" && !contentInstruction) return void window.alert("请先描述要从视频中截取的内容");
  if (taskMode === "content_extract") {
    const textRange = contentTextRange(contentInstruction, contentSearchOptions.duration);
    const effectiveStart = textRange ? Math.max(contentSearchOptions.start, textRange[0]) : contentSearchOptions.start;
    const effectiveEnd = textRange ? Math.min(contentSearchOptions.end, textRange[1]) : contentSearchOptions.end;
    if (effectiveEnd <= effectiveStart) return void window.alert("文字中的时间条件与选择的位置没有交集，请调整后再检索");
    if (contentSearchOptions.duration > 600 && effectiveEnd - effectiveStart >= contentSearchOptions.duration - .2) {
      const confirmed = await requestActionConfirmation({
        title: "确认检索全片",
        summary: `当前视频长 ${formatTime(contentSearchOptions.duration)}，全片检索会处理更多索引证据。`,
        details: ["可以返回上方选择前半段、后半段或自定义范围", "系统会根据描述自动选择必要的识别能力"],
      });
      if (!confirmed) return;
    }
  }
  if (!automatic && (!Number.isInteger(count) || count < 1 || count > 8)) return void window.alert("事件上限必须为 1–8 个");
  if (targetSeconds !== "auto" && (!Number.isFinite(targetSeconds) || targetSeconds < 4)) return void window.alert("单条成片目标时长必须大于等于 4 秒");
  const button = $("#startAnalysisButton");
  actionBusy = true;
  button.disabled = true;
  button.querySelector("span").textContent = "正在上传视频…";
  const form = new FormData();
  form.append("video", videoInput.files[0]);
  form.append("expected_size_bytes", String(videoInput.files[0].size));
  form.append("task_mode", taskMode);
  form.append("storage_mode", storageMode);
  form.append("instruction", contentInstruction);
  form.append("count", String(taskMode === "content_extract" ? "auto" : count));
  form.append("target_seconds", String(taskMode === "content_extract" ? "auto" : targetSeconds));
  form.append("total_target_seconds", String(taskMode === "content_extract" ? "auto" : targetSeconds));
  form.append("theme", requestTheme);
  form.append("analysis_mode", analysisMode);
  form.append("recognition_profile", "auto");
  form.append("force_reanalyze", String(forceReanalyze));
  form.append("subtitle_mode", subtitleMode);
  form.append("edit_mode", editMode);
  form.append("structure", structure);
  form.append("auto_variant_count", String(autoVariantCount));
  form.append("technique_preset", techniquePreset);
  form.append("allow_speed", String(techniqueOption("allowSpeed")));
  form.append("allow_transitions", String(techniqueOption("allowTransitions")));
  form.append("allow_audio_bridges", String(techniqueOption("allowAudioBridges")));
  form.append("allow_cutaways", String(techniqueOption("allowCutaways")));
  form.append("allow_silence_compression", String(techniqueOption("allowSilenceCompression")));
  form.append("allow_cold_open", String(techniqueOption("allowColdOpen")));
  form.append("search_scope_kind", taskMode === "content_extract" ? contentSearchOptions.kind : "all");
  form.append("search_scope_start", taskMode === "content_extract" ? String(contentSearchOptions.start) : "");
  form.append("search_scope_end", taskMode === "content_extract" ? String(contentSearchOptions.end) : "");
  form.append("search_result_limit", taskMode === "content_extract" ? String(contentSearchOptions.limit) : "3");
  form.append("search_boundary_mode", taskMode === "content_extract" ? contentSearchOptions.boundary : "complete");
  form.append("content_auto_generate", String(taskMode === "content_extract" && contentSearchOptions.autoGenerate));
  form.append("content_exclusions", taskMode === "content_extract" ? contentSearchOptions.exclusions : "");
  form.append("search_evidence_mode", taskMode === "content_extract" ? contentSearchOptions.evidence?.mode || "" : "");
  form.append("search_allowed_capabilities", taskMode === "content_extract" ? (contentSearchOptions.evidence?.capabilities || []).join(",") : "");
  try {
    const { job } = await api("/api/jobs", { method: "POST", body: form });
    // The user may have returned home or started another task while the
    // upload was in flight. Never let that old upload reopen itself.
    if (createGeneration !== workspaceGeneration || !homeNavigationRequested) return;
    homeNavigationRequested = false;
    renderJob(job);
    pollJob();
  } catch (error) {
    if (createGeneration !== workspaceGeneration) return;
    window.alert(error.message);
    button.disabled = false;
    button.querySelector("span").textContent = taskMode === "content_extract" ? "上传并查找内容" : "开始分析并自动生成成片";
  } finally {
    if (createGeneration === workspaceGeneration) actionBusy = false;
  }
}

function candidateReviewLabels(candidate) {
  const labels = [];
  const evidenceCount = Array.isArray(candidate?.evidence) ? candidate.evidence.length : 0;
  const audio = candidate?.audioEvidence || {};
  if (evidenceCount) labels.push(`画面 ${evidenceCount}`);
  if (audio.transcriptExcerpt || audio.speakerTurns?.length) labels.push("对白");
  if (audio.audioEvents?.length) labels.push("声音");
  if (Number(candidate?.score || 0) < 70 || !evidenceCount) labels.push("优先复核");
  return labels;
}

function sortedCandidatesForReview(job) {
  const candidates = [...(job?.candidates || [])].filter(speakerMatches);
  if (candidateReviewSort === "time") return candidates.sort((left, right) => Number(left.start) - Number(right.start));
  if (candidateReviewSort === "review") return candidates.sort((left, right) => {
    const risk = (item) => Number(item.score || 0) < 70 || !item.evidence?.length ? 0 : 1;
    return risk(left) - risk(right) || Number(left.start) - Number(right.start);
  });
  return candidates.sort((left, right) => Number(right.score || 0) - Number(left.score || 0) || Number(left.start) - Number(right.start));
}

function timelineSegmentsMatch(left = [], right = [], tolerance = 0.12) {
  if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) return false;
  return left.every((segment, index) => {
    const other = right[index];
    if (!other) return false;
    return Math.abs(Number(segment.start) - Number(other.start)) <= tolerance
      && Math.abs(Number(segment.end) - Number(other.end)) <= tolerance;
  });
}

function timelineEditedAfterLatestOutput(job, generatedVersions = []) {
  const edits = Array.isArray(job?.timelineUndo) ? job.timelineUndo : [];
  if (!edits.length || !generatedVersions.length) return false;
  const latestOutputTime = generatedVersions.reduce((latest, version) => {
    const timestamps = [version?.createdAt, ...(version?.outputs || []).map((output) => output?.versionCreatedAt)]
      .map((value) => Date.parse(String(value || "")))
      .filter(Number.isFinite);
    return Math.max(latest, ...timestamps, 0);
  }, 0);
  if (!latestOutputTime) return false;
  return edits.some((edit) => {
    const editTime = Date.parse(String(edit?.createdAt || ""));
    return Number.isFinite(editTime) && editTime > latestOutputTime;
  });
}

function contentMatchTypeLabel(match = {}) {
  const labels = { speech: "对白", visual: "画面", ocr: "屏幕文字", audio: "声音", person: "匿名人物", audiovisual: "多模态", spoken_question: "口头问题", screen_question: "画面问题", audiovisual_question: "音画问题" };
  const evidenceType = String(match.evidenceType || "").toLowerCase();
  if (labels[evidenceType]) return labels[evidenceType];
  const modalities = [...new Set((match.matchedModalities || []).map((value) => String(value).toLowerCase()).filter(Boolean))];
  if (modalities.length > 1) return "多模态";
  return labels[modalities[0]] || "画面";
}

function contentQuestionSourceKey(match = {}) {
  const source = String(match.questionSource || "").toLowerCase();
  if (source === "spoken" || source === "screen" || source === "both") return source;
  const sources = [...new Set((match.questionSources || []).map((value) => String(value).toLowerCase()))];
  return sources.includes("spoken") && sources.includes("screen") ? "both" : sources[0] || "";
}

function contentQuestionSourceLabel(source = "") {
  return ({ spoken: "口头提问", screen: "画面问题", both: "口头 + 画面" })[String(source).toLowerCase()] || "";
}

function contentMatchMethodLabel(match = {}) {
  const method = String(match.matchType || "").toLowerCase();
  const labels = {
    exact_quote: "对白原句匹配",
    semantic_speech: "对白语义匹配",
    lexical_speech: "对白关键词匹配",
    visual_semantic: "画面语义匹配",
    visual_refined: "连续画面复核",
    visual_dense_fallback: "局部逐帧复检",
    ocr_text: "屏幕文字匹配",
    audio_event: "声音事件匹配",
    anonymous_person: "匿名人物轨迹匹配",
    labeled_person_speaking: "已标记人物发言复核",
    dialogue_response_block: "问答图完整回答",
    screen_question: "画面问题 OCR 识别",
    dialogue_role_turn: "对话角色轮次",
    predicate_match: "原子条件证据匹配",
    multi_predicate: "多条件时间约束匹配",
    multi_evidence: "多类证据交叉匹配",
  };
  return labels[method] || `${contentMatchTypeLabel(match)}证据匹配`;
}

function contentBoundarySourceLabel(source = "") {
  const normalized = String(source || "").toLowerCase();
  const withContext = normalized.endsWith("_with_context");
  const base = withContext ? normalized.slice(0, -"_with_context".length) : normalized;
  const labels = {
    word_timestamps: "字词时间戳",
    grounded_segments: "对白片段定位",
    speech_sentences: "完整句子边界",
    speech_aligned: "对白时间轴",
    visual: "画面窗口",
    visual_window: "画面窗口",
    visual_dense_frames: "连续画面复核",
    targeted_dense_frames: "局部画面复检",
    ocr_stable_range: "文字稳定区间",
    screen_question_card_shot: "问题卡完整镜头",
    screen_question_readable_window: "问题文字可读区间",
    question_evidence_union: "音画问题证据合并",
    audio_window: "声音事件窗口",
    person_track: "匿名人物轨迹",
    grounding_dino_evidence: "画面目标定位",
    speaker_turn_with_visual_verification: "说话人轮次与连续画面复核",
    direct_active_speaker_visual: "人物近景口型与语音活动交叉定位",
    active_speaker_asd: "本地视听主动说话人逐帧定位",
    active_speaker_asd_refined: "候选级主动说话人精修",
    person_track_feedback_refined: "人物逐帧轨迹反馈精修",
    dialogue_word_timestamps: "完整回答词级边界",
    dialogue_turn_timestamps: "完整回答轮次边界",
    dialogue_word_alignment_refined: "反馈后词级边界精修",
    predicate_temporal_join: "条件时间关系连接",
    merged_evidence: "多类证据合并",
    user_manual_trim: "人工调整",
    user_boundary_feedback: "用户反馈",
    feedback_sentence_retry: "句子边界复检",
  };
  const label = labels[base] || "索引证据窗口";
  return withContext ? `${label}并保留上下文` : label;
}

function contentPersonLabelingMarkup(job, targetState = {}, allowTargetSelection = false) {
  const persons = Array.isArray(job?.contentIndex?.persons) ? job.contentIndex.persons : [];
  // A content index may contain person clusters for many unrelated queries.
  // Do not expose those cards for topic, dialogue, or question searches unless
  // the current query explicitly requires a person target.
  if (!persons.length || !allowTargetSelection) return "";
  const normalizedTarget = typeof targetState === "string"
    ? { personIds: targetState ? [targetState] : [], matchMode: "any" }
    : (targetState || {});
  const targetPersonIds = new Set((normalizedTarget.personIds || []).map(String));
  const speaking = String(normalizedTarget.activity || "") === "speaking";
  const inferredMode = normalizedTarget.matchMode || "any";
  const anyLabel = speaking ? "任一人发言" : "任一人物出现";
  const allLabel = speaking ? "所有人都发言（同一对话）" : "所有人物同时出现";
  const history = Array.isArray(job?.contentPersonTargetHistory) ? job.contentPersonTargetHistory.slice(-8).reverse() : [];
  const historyMarkup = history.length ? `<div class="content-person-history"><strong>已确认人物</strong>${history.map((item) => {
    const ids = (item.personIds || []).map(String).filter(Boolean);
    const labels = (item.labels || ids).filter(Boolean);
    return `<div class="content-person-history-row"><span>${escapeHtml(labels.join("、"))}<small>${item.matchMode === "all" ? "同一对话中全部发言" : "任一人物"}</small></span><button type="button" data-person-history-target="${escapeHtml(ids.join(","))}" data-person-history-mode="${escapeHtml(item.matchMode || "any")}">再次探索</button></div>`;
  }).join("")}</div>` : "";
  return `<details class="content-person-panel" data-person-target-panel data-person-target-activity="${speaking ? "speaking" : "appearance"}" ${targetPersonIds.size ? "" : "open"}>
    <summary><span>确认视频中的人物</span><small>${persons.length} 个画面人物簇 · 可能包含同一人物的重复卡片</small></summary>
    <div class="content-person-grid">${persons.map((person) => {
      const isTarget = targetPersonIds.has(String(person.id || ""));
      const speaker = person.primarySpeaker
        ? `${escapeHtml(person.primarySpeaker)} · ${Math.round(Number(person.speakerConfidence || 0) * 100)}%${person.speakerReviewRequired ? " · 需复核" : ""}`
        : "尚未关联说话人";
      return `<article class="content-person-card${isTarget ? " target" : ""}" data-content-person="${escapeHtml(person.id)}"${isTarget ? ' data-content-person-target-state="true"' : ""}>
        <button type="button" class="content-person-preview" data-person-preview="${escapeHtml(person.id)}" data-person-preview-time="${escapeHtml(person.representativeTime ?? 0)}" aria-label="预览${escapeHtml(person.label || person.defaultLabel || "匿名人物")}的代表画面"><img src="${escapeHtml(person.thumbnailUrl || "")}" alt="${escapeHtml(person.label || person.defaultLabel || "匿名人物")}" loading="lazy"><em>预览</em></button>
        <div><small>${isTarget ? "本次检索人物 · " : ""}${escapeHtml(person.defaultLabel || person.id)}</small><strong>${escapeHtml(person.label || person.defaultLabel || person.id)}${isTarget ? " · 已选择" : ""}</strong><span>${speaker}</span></div>
        <div class="content-person-actions">${allowTargetSelection ? `<label class="content-person-choice"><input type="checkbox" data-person-target value="${escapeHtml(person.id)}" ${isTarget ? "checked" : ""}><span>${isTarget ? "已选择" : "选择人物"}</span></label>` : ""}<button type="button" data-person-label="${escapeHtml(person.id)}" data-person-current-label="${escapeHtml(person.label || "")}">${person.userLabeled ? "修改标签" : "添加标签（可选）"}</button></div>
      </article>`;
    }).join("")}</div>${allowTargetSelection ? `<div class="content-person-target-controls" data-person-target-controls data-selection-count="${targetPersonIds.size}">
      <div><strong data-person-selection-summary>已选 ${targetPersonIds.size} 人</strong><small>${speaking ? "选择发言匹配方式" : "选择画面匹配方式"}</small></div>
      <div class="content-person-match-modes" role="radiogroup" aria-label="人物匹配方式">
        <label><input type="radio" name="content-person-match-mode" data-person-match-mode value="any" ${inferredMode === "any" ? "checked" : ""}><span>${anyLabel}</span></label>
        <label><input type="radio" name="content-person-match-mode" data-person-match-mode value="all" ${inferredMode === "all" ? "checked" : ""}><span>${allLabel}</span></label>
      </div>
      <button type="button" class="primary" data-person-target-confirm>确认并开始检索</button>
    </div>` : ""}
    ${historyMarkup}<p>${allowTargetSelection ? "可选择一个或多个人物；选择两人并使用“所有人都发言（同一对话）”可查找两人对话。添加项目内标签是可选操作。" : ""} 建议使用项目内标签或匿名编号。系统不会把外观推断当成真实身份或性别事实。</p>
  </details>`;
}

function contentFlowMarkup({ search = {}, candidates = [], personRequested = false, targetState = {}, reviewDraft = {} } = {}) {
  const hasTarget = Array.isArray(targetState.personIds) && targetState.personIds.length > 0;
  const hasCandidates = candidates.length > 0;
  const reliableCount = candidates.filter((item) => String(item.confidenceTier || (item.requiresReview ? "possible" : "reliable")) === "reliable").length;
  const possibleCount = Math.max(0, candidates.length - reliableCount);
  const selectedCount = Array.isArray(reviewDraft.selectedMatchIds) ? reviewDraft.selectedMatchIds.length : 0;
  const complete = search.completeness?.status === "complete";
  const subtitleReady = Boolean(reviewDraft.subtitleDraftId || reviewDraft.subtitleEnabled === false);
  const steps = [
    ["条件", "done", "检索条件已记录"],
    ["人物", personRequested ? (hasTarget ? "done" : "active") : "done", personRequested ? (hasTarget ? "目标人物已确认" : "请选择一个或多个人物") : "无需单独确认人物"],
    ["片段", hasCandidates ? "active" : "pending", hasCandidates ? `已找到 ${reliableCount} 个可靠片段${possibleCount ? `，另有 ${possibleCount} 个可能相关` : ""}` : "等待检索结果"],
    ["字幕", subtitleReady ? "done" : "pending", subtitleReady ? "字幕状态已确认" : "生成时可选择字幕校对"],
    ["导出", complete || hasCandidates ? "active" : "pending", complete ? "完整性检查通过" : hasCandidates ? "确认选择后生成" : "等待候选片段"],
  ];
  const next = steps.find(([, state]) => state === "active") || steps.find(([, state]) => state === "pending");
  return `<section class="content-flow-strip" aria-label="内容检索流程"><div class="content-flow-steps">${steps.map(([label, state, detail], index) => `<div class="content-flow-step ${state}"><b>${index + 1}</b><span>${label}</span><small>${detail}</small></div>`).join("")}</div>${next ? `<p class="content-flow-next"><span class="content-flow-next-label">下一步</span>${escapeHtml(next[2])}${selectedCount ? ` · 当前已选 ${selectedCount} 段` : ""}</p>` : ""}</section>`;
}

function formatSearchElapsed(milliseconds) {
  const value = Math.max(0, Number(milliseconds) || 0);
  if (value < 1000) return value > 0 ? "不到 1 秒" : "即时完成";
  return `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)} 秒`;
}

function contentSearchReviewMarkup(job, search = job.contentSearch || {}, { historicalExpanded = false } = {}) {
  const isCurrentSearch = !search?.id || String(search.id) === String(job?.contentSearch?.id || "");
  const historicalSearchClass = isCurrentSearch ? "" : ` historical${historicalExpanded ? "" : " collapsed"}`;
  const historicalSearchToggle = isCurrentSearch
    ? ""
    : `<button type="button" class="content-history-toggle" data-content-search-history-toggle aria-expanded="false">展开历史检索详情</button>`;
  const candidates = Array.isArray(search.candidates) ? search.candidates : [];
  const reliableCandidates = candidates.filter((match) => String(match.confidenceTier || (match.requiresReview ? "possible" : "reliable")) === "reliable");
  const possibleCandidates = candidates.filter((match) => String(match.confidenceTier || (match.requiresReview ? "possible" : "reliable")) !== "reliable");
  const reliableCount = reliableCandidates.length;
  const possibleCount = possibleCandidates.length;
  const questionSourceCounts = candidates.reduce((counts, match) => {
    const source = contentQuestionSourceKey(match);
    if (source) counts[source] = (counts[source] || 0) + 1;
    return counts;
  }, {});
  const hasQuestionSources = Object.keys(questionSourceCounts).length > 0;
  const localFilterState = contentSearchFilterState.get(`${job?.id || ""}:${search?.id || ""}`) || {};
  const questionSourceFilter = String(localFilterState.questionSource || "all");
  const boundaryRetryIds = new Set((job.contentSearchFeedback?.boundaryRetryMatchIds || search.feedback?.boundaryRetryMatchIds || []).map(String));
  const reviewDraft = search.reviewDraft && search.id && search.reviewDraft.searchId === search.id
    ? search.reviewDraft : {};
  const defaults = new Set((reviewDraft.selectedMatchIds || search.defaultSelectedIds || []).map(String));
  const selectableCandidates = candidates.filter((match) => {
    const status = String(match.reviewStatus || (match.requiresReview ? "pending" : "confirmed"));
    return status !== "rejected";
  });
  const allSelectableSelected = selectableCandidates.length > 0
    && selectableCandidates.every((match) => defaults.has(String(match.id)));
  const bulkControlsMarkup = candidates.length ? `<div class="content-exhaustive-controls content-exhaustive-controls-bottom"><span>选择片段${candidates.length > 50 ? ` · 首屏显示 50 段，共 ${candidates.length} 段` : ""}</span><button type="button" data-content-select="toggle" aria-pressed="${allSelectableSelected ? "true" : "false"}">${allSelectableSelected ? "取消全部" : "选择全部"}</button></div>` : "";
  const questionSourceControls = hasQuestionSources ? `<label class="content-question-source-filter"><span>问题来源</span><select data-content-question-source><option value="all" ${questionSourceFilter === "all" ? "selected" : ""}>全部（${Object.values(questionSourceCounts).reduce((sum, value) => sum + value, 0)}）</option><option value="spoken" ${questionSourceFilter === "spoken" ? "selected" : ""}>口头提问（${questionSourceCounts.spoken || 0}）</option><option value="screen" ${questionSourceFilter === "screen" ? "selected" : ""}>画面问题（${questionSourceCounts.screen || 0}）</option><option value="both" ${questionSourceFilter === "both" ? "selected" : ""}>口头 + 画面（${questionSourceCounts.both || 0}）</option></select></label>` : "";
  const draftOutputMode = String(reviewDraft.outputMode || "single_reel");
  const draftOrderMode = String(reviewDraft.orderMode || "source");
  const stats = search.retrievalStats || {};
  const exhaustive = String(search.resultMode || search.queryPlan?.result?.mode || "top_k") === "exhaustive";
  const coverageComplete = Boolean(search.coverageComplete ?? stats.coverageComplete);
  const completeness = search.completeness && typeof search.completeness === "object" ? search.completeness : {};
  const completenessStatus = String(completeness.status || (coverageComplete ? "complete" : "incomplete"));
  const strictComplete = !exhaustive || completenessStatus === "complete";
  const pendingCount = Number(completeness.pendingCount || 0);
  const scanProgress = search.scanProgress || stats.scanProgress || {};
  const legacyVisualProgress = Number(stats.strictVisualExpectedFrames || 0) > 0
    ? Number(stats.strictVisualVerifiedFrames || 0) / Number(stats.strictVisualExpectedFrames || 1) * 100
    : 0;
  const coveredPercent = Math.max(0, Math.min(100, Number(scanProgress.coveredPercent ?? (coverageComplete ? 100 : legacyVisualProgress))));
  const occurrenceCount = Number(completeness.occurrenceCount ?? candidates.length);
  const clipCount = Number(completeness.clipCount ?? candidates.length);
  const exhaustiveTitle = completenessStatus === "complete"
    ? `检索覆盖完成 · 找到 ${occurrenceCount} 处证据，整理为 ${clipCount} 段`
    : `全范围扫描未完成 · 当前覆盖 ${coveredPercent.toFixed(1)}%`;
  const completenessRows = [
    ...(Array.isArray(completeness.channels) ? completeness.channels : []),
    ...(possibleCount ? [{ id: "possible_results", label: "可能相关（可选）", complete: true, detail: `${possibleCount} 个内容段已折叠，不影响继续生成` }] : []),
    ...(completeness.expectedOccurrenceCount == null ? [] : [{
      id: "expected_count", label: `明确预期至少 ${Number(completeness.expectedOccurrenceCount)} 处`,
      complete: Boolean(completeness.expectedCountSatisfied), detail: `当前检出 ${occurrenceCount} 处`,
    }]),
  ];
  const completenessMarkup = exhaustive ? `<section class="content-completeness ${escapeHtml(completenessStatus)}"><div><strong>完整性报告</strong><span>“处”是检出的独立证据，“段”是合并相邻证据后的输出片段。</span></div><ul>${completenessRows.map((item) => `<li class="${item.complete ? "complete" : "incomplete"}"><b>${item.complete ? "✓" : "!"}</b><span><strong>${escapeHtml(item.label || "检查项")}</strong><small>${escapeHtml(item.detail || "")}</small></span></li>`).join("")}</ul>${(completeness.warnings || []).length ? `<p>${completeness.warnings.map(escapeHtml).join(" ")}</p>` : ""}</section>` : "";
  const evidenceHitCount = Number(stats.evidenceHitCount ?? stats.localRecallCount ?? 0);
  const semanticBatchText = Number(stats.semanticBatchCount || 0) > 1
    ? ` · 语义复核 ${Number(stats.semanticBatchesCompleted || 0)}/${Number(stats.semanticBatchCount || 0)} 批`
    : "";
  const statsText = stats.cacheHit
    ? `已复用上次检索结果 · ${formatSearchElapsed(stats.totalMilliseconds)}`
    : `已引用 ${evidenceHitCount} 条索引证据${semanticBatchText} · ${formatSearchElapsed(stats.totalMilliseconds)}`;
  const calls = stats.callBreakdown || {};
  const callRows = [
    ["意图理解", calls.intent], ["文本语义复核", calls.textRerank], ["候选画面复核", calls.visionVerify],
  ].filter(([, value]) => value && Number(value.used || 0) > 0);
  const modelTraceMarkup = `<details class="content-model-trace"><summary>本次模型调用 ${callRows.reduce((sum, [, value]) => sum + Number(value.used || 0), 0)} 次</summary><div>${callRows.length ? callRows.map(([label, value]) => `<span><b>${escapeHtml(label)}</b><small>${Number(value.used || 0)}/${Number(value.limit || 0)} · ${escapeHtml(value.reason || "按需调用")}</small></span>`).join("") : "<span><b>未调用远程模型</b><small>复用状态或本地索引完成</small></span>"}</div></details>`;
  const scope = search.intent?.searchScope || stats.searchScope || {};
  const scopeMarkup = Number(scope.end) > Number(scope.start)
    ? `<p class="content-search-scope">检索范围 ${formatTime(scope.start)} → ${formatTime(scope.end)}，范围长度 ${formatTime(Number(scope.end) - Number(scope.start))}${scope.source === "intersection" ? "，已取时间条件交集" : ""}</p>`
    : "";
  const historyMarkup = "";
  const recognition = job.recognition || {};
  const counts = recognition.counts || {};
  const coverage = recognition.modalityCoverage || {};
  const coverageLabels = [["speech", "对白"], ["visual", "画面"], ["ocr", "屏幕文字"], ["audio", "声音"], ["person", "匿名人物"]]
    .filter(([key]) => coverage[key]).map(([, label]) => label);
  const degradedCount = Array.isArray(recognition.degradedReasons) ? recognition.degradedReasons.length : 0;
  const recognitionMarkup = Number(recognition.schemaVersion || 0) >= 4 ? `<div class="recognition-coverage"><span>识别范围</span>${coverageLabels.map((label) => `<b>${label}</b>`).join("")}<small>${Number(counts.shots || 0)} 个镜头 · ${Number(counts.ocr || 0)} 条屏幕文字 · ${Number(counts.persons || 0)} 个匿名人物${degradedCount ? ` · ${degradedCount} 项能力未启用` : ""}</small></div>` : "";
  const execution = search.executionPlan || search.intent?.executionPlan || {};
  const queryPredicates = search.queryPlan?.predicates || search.intent?.queryPlan?.predicates || search.intent?.predicates || [];
  const questionPredicate = queryPredicates.find((predicate) => String(predicate?.kind || "") === "question.evidence");
  const dialoguePredicate = questionPredicate
    ? null
    : queryPredicates.find((predicate) => String(predicate?.kind || "") === "speech.dialogue_role");
  const questionOnlyQuery = Boolean(questionPredicate);
  const capabilityLabels = questionOnlyQuery
    ? { speech: "口头问题", visual: "画面", ocr: "画面问题", audio: "声音", person: "人物轨迹" }
    : { speech: "对白", visual: "画面", ocr: "屏幕文字", audio: "声音", person: "人物轨迹" };
  const personCapabilityRequested = queryPredicates.some((predicate) =>
    ["person.speaking", "person.appearance"].includes(String(predicate?.kind || ""))
    || String(predicate?.subjectPersonRef || predicate?.subjectPersonId || predicate?.personRef || "").trim(),
  ) || ["person_target", "active_speaker_link"].includes(String(search.clarification?.kind || ""));
  const allowedCapabilities = Array.isArray(execution.allowedCapabilities) ? execution.allowedCapabilities : [];
  const executionWarnings = Array.isArray(execution.warnings) ? execution.warnings.filter(Boolean) : [];
  const warningMarkup = executionWarnings.length ? `<div class="content-coverage-warning"><strong>覆盖提醒</strong><p>${executionWarnings.map(escapeHtml).join(" ")}</p></div>` : "";
  const personOperation = execution.operations?.["person.track_face"] || {};
  const personSampling = job.contentIndex?.personSampling || {};
  const personCoverageMarkup = allowedCapabilities.includes("person") && personCapabilityRequested && (
    Number(personSampling.requestedFrameCount || 0) > 0 || Number(personOperation.sampleCount || 0) > 0
  ) ? `<small>人物扫描 ${Number(personSampling.extractedFrameCount || personOperation.sampleCount || 0)}/${Number(personSampling.requestedFrameCount || personOperation.sampleCount || 0)} 帧 · 最大间隔 ${formatTime(Number(personOperation.maximumSampleGapUs || 0) / 1000000)} · ${personOperation.coverageComplete ? "已覆盖全范围" : "仍有不确定区间"}</small>` : "";
  const executionHint = !allowedCapabilities.length
    ? "系统正在把描述编译为可执行的查找条件"
    : personCapabilityRequested && allowedCapabilities.includes("person")
      ? "已根据检索条件选择必要证据；本次人物检索使用连续轨迹扫描"
      : questionOnlyQuery
        ? "只检查本次问题检索需要的证据来源"
        : "只运行上方列出的查找依据";
  const executionMarkup = `<div class="recognition-coverage"><span>系统自动选择的查找依据</span>${allowedCapabilities.length ? allowedCapabilities.map((value) => `<b>${escapeHtml(capabilityLabels[value] || value)}</b>`).join("") : "<b>正在理解</b>"}<small>${executionHint}</small>${personCoverageMarkup}</div>${warningMarkup}`;
  const questionInterpretation = questionPredicate
    ? `<p class="content-search-scope">问题检索：${String(questionPredicate.source || questionPredicate.questionSource || "all") === "spoken" ? "只查口头提问" : String(questionPredicate.source || questionPredicate.questionSource || "all") === "screen" ? "只查画面问题" : "口头提问 + 画面问题"}；只输出问题片段，不包含回答</p>`
    : "";
  const dialogueMode = String(search.dialogueMode || dialoguePredicate?.dialogueMode || (dialoguePredicate?.includePrompt ? "qa_pair" : dialoguePredicate?.role === "questioner" ? "question_only" : "answer_only"));
  const dialogueInterpretation = dialoguePredicate
    ? `<p class="content-search-scope">系统理解：${dialoguePredicate.role === "answerer" ? "回答者的完整回答" : "指定对话角色的发言"}${dialoguePredicate.includePrompt ? "，包含前置提问" : "，不包含前置提问"}${String(dialoguePredicate.interruptionPolicy || "") === "bridge_backchannel" ? "；短附和保持回答连续" : ""}</p>`
    : "";
  const dialogueModeMarkup = dialoguePredicate && isCurrentSearch ? `<label class="content-dialogue-mode"><span>问答结果</span><select data-content-dialogue-mode><option value="qa_pair" ${dialogueMode === "qa_pair" ? "selected" : ""}>完整问答</option><option value="question_only" ${dialogueMode === "question_only" ? "selected" : ""}>仅问题</option><option value="answer_only" ${dialogueMode === "answer_only" ? "selected" : ""}>仅回答</option><option value="qa_split" ${dialogueMode === "qa_split" ? "selected" : ""}>问题/回答拆分</option></select><small>切换只重新整理对话图，不重新扫描视频</small></label>` : "";
  const searchClarification = search.clarification && typeof search.clarification === "object" ? search.clarification : null;
  const plannedTarget = search.queryPlan?.personTarget || search.intent?.queryPlan?.personTarget || search.intent?.personTarget;
  const persistedTarget = job.request?.contentSearchPersonTarget || job.contentSearchPersonTarget;
  const legacyTargetPersonId = String(
    (searchClarification?.options || []).find((option) => option?.personId)?.personId
    || search.queryPlan?.predicates?.find((predicate) => predicate?.personId)?.personId
    || search.intent?.queryPlan?.predicates?.find((predicate) => predicate?.personId)?.personId
    || job.contentSearchTargetPersonId || job.request?.contentSearchTargetPersonId || "",
  );
  const targetState = plannedTarget || persistedTarget || {
    personIds: legacyTargetPersonId ? [legacyTargetPersonId] : [], matchMode: legacyTargetPersonId ? "any" : "",
  };
  const clarificationPersonId = String(
    (searchClarification?.options || []).find((option) => option?.personId)?.personId || "",
  );
  const targetPersonId = String(
    (searchClarification?.kind === "active_speaker_link" ? clarificationPersonId : "")
    || (targetState.personIds || [])[0] || legacyTargetPersonId || "",
  );
  const personPredicates = [
    ...(search.queryPlan?.predicates || []),
    ...(search.intent?.queryPlan?.predicates || []),
    ...(search.intent?.predicates || []),
  ];
  const personRequested = personPredicates.some((predicate) => ["person.speaking", "person.appearance"].includes(String(predicate?.kind || ""))
      || String(predicate?.subjectPersonRef || predicate?.subjectPersonId || predicate?.personRef || "").trim())
    || (Array.isArray(search.intent?.personRefs) && search.intent.personRefs.length > 0)
    || Boolean((searchClarification?.kind || "") === "person_target")
    || Boolean((searchClarification?.kind || "") === "active_speaker_link");
  const personMarkup = contentPersonLabelingMarkup(job, targetState, personRequested);
  if (!candidates.length) {
    const clarification = searchClarification;
    const scanState = String(search.scanProgress?.state || "");
    const activelyScanning = ["indexing", "scanning"].includes(String(search.status || "")) || scanState === "scanning";
    const activeScanPercent = Math.max(0, Math.min(100, Number(search.scanProgress?.coveredPercent || 0)));
    const indexedPersons = Array.isArray(job?.contentIndex?.persons) ? job.contentIndex.persons : [];
    const planPredicates = search.queryPlan?.predicates || search.intent?.queryPlan?.predicates || search.intent?.predicates || [];
    const needsPersonConfirmation = personRequested && indexedPersons.length > 0
      && !indexedPersons.some((person) => person?.userLabeled)
      && planPredicates.some((predicate) => String(predicate?.kind || "").startsWith("person.") && !predicate?.personId);
    const targetPerson = indexedPersons.find((person) => String(person?.id || "") === targetPersonId);
    const speakerLinkGuidance = clarification?.kind === "active_speaker_link" && targetPerson
      ? `本次目标是“${targetPerson.label || targetPerson.defaultLabel || targetPerson.id}”。${targetPerson.userLabeled ? "项目内标签已经生效" : "当前使用匿名人物编号，无需先修改名称"}。系统已先尝试音画口型匹配，但证据仍不足；下面的人工关联仅是兜底步骤。请预览音画后确认对应的音频 Speaker。`
      : "";
    const guidance = activelyScanning
      ? "可靠结果会在证据验证完成后出现。扫描期间可以离开当前页面，任务进度会保留。"
      : speakerLinkGuidance || clarification?.message || search.clarification || (needsPersonConfirmation
      ? "人物、对白和画面索引已经完成，但系统还不能可靠判断哪些人物卡是目标。请选择一个或多个人物、确认匹配方式后开始检索；添加项目内标签是可选操作。"
      : scope.isNarrow ? "当前范围内没有可靠匹配。可以修改描述，或扩大范围后重新查找。" : "当前已授权的证据中没有可靠匹配。可以换一个更具体的描述重新查找。");
    const clarificationOptions = Array.isArray(clarification?.options) ? clarification.options : [];
    const speakerCount = new Set(clarificationOptions.map((option) => String(option?.speakerRef || "")).filter(Boolean)).size;
    const targetPersonLabel = targetPerson?.label || targetPerson?.defaultLabel || targetPerson?.id || "目标人物";
    const speakerExplanation = clarification?.kind === "active_speaker_link"
      ? `<div class="content-speaker-explanation"><div><b>画面人物簇 ${indexedPersons.length} 个</b><span>逐字稿 Speaker ${speakerCount} 组</span></div><p>这两种分组不等于真实人数。画面簇包含未说话和背景人物；Speaker 只是逐字稿中的发言分组，也可能把同一个人拆开。请以预览的音画内容为准。</p></div>`
      : "";
    const clarificationButtons = clarification?.kind === "active_speaker_link"
      ? `${speakerExplanation}${clarificationOptions.map((option) => `<article class="content-speaker-option"><div><strong>音频 ${escapeHtml(option.speakerRef || "Speaker")}</strong><small>${formatTime(option.start)} → ${formatTime(option.end)}</small><p>${escapeHtml(option.transcript || "该时间段没有可展示的对白")}</p></div><div><button type="button" data-content-speaker-preview="${escapeHtml(option.id || "")}" data-content-preview-start="${escapeHtml(option.start ?? 0)}" data-content-preview-end="${escapeHtml(option.end ?? option.start ?? 0)}" data-content-preview-speaker="${escapeHtml(option.speakerRef || "Speaker")}">预览音画</button><button type="button" class="primary" data-content-speaker-confirm="${escapeHtml(option.speakerRef || "")}" data-content-person-id="${escapeHtml(option.personId || "")}">确认 ${escapeHtml(targetPersonLabel)} 对应 ${escapeHtml(option.speakerRef || "Speaker")}</button></div></article>`).join("")}`
      : clarificationOptions.map((option) => `<button type="button" class="content-evidence-option${option.recommended ? " primary" : ""}${option.disabled ? " unavailable" : ""}" ${option.disabled ? "disabled aria-disabled=\"true\"" : `data-content-evidence-choice="${escapeHtml(option.id || "")}" data-content-evidence-mode="${escapeHtml(option.evidenceMode || option.id || "")}" data-content-capabilities="${escapeHtml((option.capabilities || []).join(","))}" data-content-instruction="${escapeHtml(option.instruction || "")}"`} title="${escapeHtml(option.disabledReason || "")}"><span>${escapeHtml(option.label || "继续")}</span>${option.disabledReason ? `<small>${escapeHtml(option.disabledReason)}</small>` : ""}</button>`).join("");
    const capabilityAlternativeHint = clarification?.kind === "evidence_type" && clarification?.alternativeHint
      ? `<p class="content-capability-alternative">${escapeHtml(clarification.alternativeHint)}</p>`
      : "";
    const expansionButtons = (search.expansionOptions || []).map((option) => `<button type="button" data-content-expansion="${escapeHtml(option.id || "")}">${escapeHtml(option.label || "继续检索")}</button>`).join("");
    const denseButton = allowedCapabilities.includes("visual") && search.status !== "needs_clarification" ? '<button type="button" data-content-feedback="missed_content">加密画面采样</button>' : "";
    return `<article class="chat-message assistant content-search-message" data-conversation-key="search:${escapeHtml(search.id || "")}"><span class="avatar">AI</span><div class="recommendation-wrap"><section class="content-search-review empty${historicalSearchClass}" data-content-search-id="${escapeHtml(search.id || "")}">${isCurrentSearch ? contentFlowMarkup({ search, candidates, personRequested, targetState, reviewDraft }) : ""}<header><div><small>${isCurrentSearch ? "内容探索" : "历史检索"}</small><strong>${activelyScanning ? `全范围扫描中 · ${activeScanPercent.toFixed(1)}%` : search.status === "needs_clarification" ? escapeHtml(clarification?.question || "需要确认查找依据") : needsPersonConfirmation ? "请确认目标人物" : "没有可靠匹配"}</strong><p>${escapeHtml(statsText)}</p>${dialogueInterpretation}${scopeMarkup}${executionMarkup}${modelTraceMarkup}${historicalSearchToggle}</div></header>${isCurrentSearch ? personMarkup : ""}<p>${escapeHtml(guidance)}</p>${isCurrentSearch && !activelyScanning ? `<div class="content-search-secondary">${search.status === "needs_clarification" ? clarificationButtons : `${expansionButtons}${denseButton}`}</div>${capabilityAlternativeHint}` : !isCurrentSearch ? `<footer class="content-history-actions"><button type="button" data-content-search-restore="${escapeHtml(search.id || "")}">恢复为当前检索并编辑</button></footer>` : ""}${historyMarkup}</section></div></article>`;
  }
  const recoveryMarkup = allowedCapabilities.includes("visual") && (!exhaustive || !coverageComplete)
    ? `<details class="content-search-recovery"${exhaustive && !coverageComplete ? " open" : ""}><summary>${exhaustive ? "扫描尚未完整，继续查找" : "还没找到想要的画面？"}</summary><div><p>${exhaustive ? "当前结果尚未覆盖完整检索范围，可以提高相关时间区域的画面采样密度。" : "仅在你认为结果确有遗漏时使用；系统会对最相关的时间区域重新进行密集画面分析。"}</p><button type="button" data-content-feedback="missed_content">加密补检可能遗漏的画面</button></div></details>`
    : "";
  const possibleToggleMarkup = possibleCount
    ? `<button type="button" class="content-possible-toggle" data-content-show-possible aria-expanded="true"><span>收起可能相关</span><b>${possibleCount} 个内容段</b><small>证据较弱，默认展示但不会自动选中</small></button>`
    : "";
  return `<article class="chat-message assistant content-search-message" data-conversation-key="search:${escapeHtml(search.id || "")}"><span class="avatar">AI</span><div class="recommendation-wrap">
    <section class="content-search-review${historicalSearchClass}" data-content-search-id="${escapeHtml(search.id || "")}">
      ${isCurrentSearch ? contentFlowMarkup({ search, candidates, personRequested, targetState, reviewDraft }) : ""}
      <header><div><small>${isCurrentSearch ? "内容探索 · 选择片段" : "历史检索 · 选择片段"}</small><strong>${exhaustive ? exhaustiveTitle : "相关片段检索完成"} · ${reliableCount} 个可靠内容段${possibleCount ? `，${possibleCount} 个可能相关` : ""}</strong><p>${escapeHtml(search.intent?.query || search.instruction || "")}</p><p class="content-search-stats">${escapeHtml(statsText)}${exhaustive ? ` · ${strictComplete ? "检索覆盖已完成" : "当前为部分覆盖结果"}` : ""}</p>${questionInterpretation}${dialogueInterpretation}${dialogueModeMarkup}${scopeMarkup}${executionMarkup}${modelTraceMarkup}${historicalSearchToggle}</div><b>选择后生成</b></header>
      ${isCurrentSearch ? personMarkup : ""}
      ${completenessMarkup}
      ${questionSourceControls}
      ${possibleToggleMarkup}
      <div class="content-match-list">${candidates.map((match, index) => {
        const reviewStatus = String(match.reviewStatus || (match.requiresReview ? "pending" : "confirmed"));
        const pending = reviewStatus === "pending";
        const rejected = reviewStatus === "rejected";
        const checked = !pending && !rejected
          && (defaults.has(String(match.id)) || (!exhaustive && !defaults.size && index < 3));
        const evidence = match.transcriptExcerpt || match.matchedEvidence || match.reason || "画面索引匹配";
        const type = contentMatchTypeLabel(match);
        const matchScore = Math.round(Number.isFinite(Number(match.score)) ? Number(match.score) : Number(match.confidence || 0) * 100);
        const methodLabel = contentMatchMethodLabel(match);
        const boundaryLabel = contentBoundarySourceLabel(match.boundarySource);
        const evidenceKinds = [...new Set((match.matchedModalities || [match.evidenceType]).filter(Boolean))];
        const evidenceCount = Array.isArray(match.evidenceRefs) ? match.evidenceRefs.length : 0;
        const matchedPeople = [...new Set((match.matchedPersonLabels || match.matchedPersonIds || []).filter(Boolean))];
        const questionSource = contentQuestionSourceKey(match);
        const questionSourceChip = questionSource ? `<i class="question-source">${escapeHtml(contentQuestionSourceLabel(questionSource))}</i>` : "";
        const subjectStatusLabels = { verified: "对象已验证", contextual: "对象语境支持", unverified: "对象未验证", ignored: "未使用对象约束" };
        const subjectChip = match.subjectDescription
          ? `<i class="subject-${escapeHtml(String(match.subjectStatus || "unverified"))}" title="${escapeHtml((subjectStatusLabels[String(match.subjectStatus || "unverified")] || "对象证据") + "：" + String(match.subjectDescription))}">${escapeHtml(subjectStatusLabels[String(match.subjectStatus || "unverified")] || "对象证据")}</i>`
          : "";
        const evidenceChips = `<span class="content-evidence-chips">${questionSourceChip}${subjectChip}${matchedPeople.map((value) => `<i class="person">${escapeHtml(value)}</i>`).join("")}${evidenceKinds.map((value) => `<i>${escapeHtml(({speech:"对白",visual:"画面",ocr:"屏幕文字",audio:"声音",person:"匿名人物"})[String(value).toLowerCase()] || value)}</i>`).join("")}<button type="button" class="content-evidence-count" data-content-evidence="${escapeHtml(match.id)}">${evidenceCount ? `查看证据（${evidenceCount}）` : "查看相关证据"}</button></span>`;
        const inputId = `content-match-${String(search.id || "search").replace(/[^a-zA-Z0-9_-]/g, "-")}-${index}`;
        const reviewReasons = (Array.isArray(match.reviewReasons) ? match.reviewReasons : []).filter(Boolean);
        const transcriptIsContext = (match.speechUnits || []).some((unit) => Number(unit.start) < Number(match.start) - .5 || Number(unit.end) > Number(match.end) + .5);
        const evidenceLabel = transcriptIsContext && match.transcriptExcerpt ? "相邻对白上下文" : "匹配证据";
        const boundaryQueued = boundaryRetryIds.has(String(match.id));
        const canAdjustBoundary = isCurrentSearch && !rejected;
        const adjustBoundaryButton = canAdjustBoundary
          ? `<button type="button" data-content-boundary-open="${escapeHtml(match.id)}">调整边界</button>`
          : "";
        const reviewButtons = !isCurrentSearch ? "" : boundaryQueued
          ? `<span class="content-feedback-pending">自动重新识别中</span>`
          : pending
          ? `${adjustBoundaryButton}<button type="button" data-content-feedback="review_reject" data-content-match-id="${escapeHtml(match.id)}">排除此片段</button>`
          : rejected
            ? `<button type="button" data-content-feedback="review_keep" data-content-match-id="${escapeHtml(match.id)}">恢复并保留</button>`
            : `<button type="button" data-content-feedback="not_relevant" data-content-match-id="${escapeHtml(match.id)}">不相关</button>${adjustBoundaryButton}`;
        const boundaryEditor = canAdjustBoundary ? `<section class="content-boundary-editor hidden" data-content-boundary-editor="${escapeHtml(match.id)}" data-boundary-start="${Number(match.start) || 0}" data-boundary-end="${Number(match.end) || 0}"><header><div><strong>手动调整片段边界</strong><small>逐帧微调，保存后立即用于生成，不会重新扫描视频。</small></div><b data-boundary-summary>${formatTime(match.start)} → ${formatTime(match.end)}</b></header><div class="content-boundary-edges"><fieldset><legend>开头 <span data-boundary-start-label>${formatTime(match.start)}</span></legend><div class="content-boundary-nudges"><button type="button" data-boundary-adjust="start:-frame">多保留 1 帧</button><button type="button" data-boundary-adjust="start:frame">少保留 1 帧</button><button type="button" data-boundary-adjust="start:-0.1">往前 0.1 秒</button><button type="button" data-boundary-adjust="start:0.1">往后 0.1 秒</button></div><button type="button" class="content-boundary-playhead" data-boundary-playhead="start">把当前播放位置设为开头</button></fieldset><fieldset><legend>结尾 <span data-boundary-end-label>${formatTime(match.end)}</span></legend><div class="content-boundary-nudges"><button type="button" data-boundary-adjust="end:-frame">少保留 1 帧</button><button type="button" data-boundary-adjust="end:frame">多保留 1 帧</button><button type="button" data-boundary-adjust="end:-0.1">往前 0.1 秒</button><button type="button" data-boundary-adjust="end:0.1">往后 0.1 秒</button></div><button type="button" class="content-boundary-playhead" data-boundary-playhead="end">把当前播放位置设为结尾</button></fieldset></div><footer><span data-boundary-frame-rate>正在读取源视频帧率…</span><div><button type="button" data-boundary-preview>预览调整结果</button><button type="button" data-boundary-auto>自动重新识别</button>${match.manualBoundary ? `<button type="button" data-boundary-reset>恢复自动边界</button>` : ""}<button type="button" data-boundary-cancel>取消</button><button type="button" class="primary" data-boundary-save>保存边界</button></div></footer></section>` : "";
        const confidenceTier = String(match.confidenceTier || (pending ? "possible" : "reliable"));
        const highConfidence = confidenceTier === "reliable" && !rejected;
        return `<article class="content-match-row${pending ? " review-pending" : ""}${rejected ? " review-rejected" : ""}${confidenceTier === "possible" ? " content-candidate-possible" : ""}${index >= 50 ? " content-candidate-overflow hidden" : ""}" data-content-match-row="${escapeHtml(match.id)}" data-content-question-source="${escapeHtml(questionSource || "other")}" data-content-reliable="${highConfidence ? "true" : "false"}"><div class="content-match-main"><input id="${inputId}" type="checkbox" data-content-match data-content-review-status="${escapeHtml(reviewStatus)}" value="${escapeHtml(match.id)}" ${checked ? "checked" : ""} ${rejected ? "disabled" : ""} aria-label="选择${escapeHtml(match.title || `匹配片段 ${index + 1}`)}"><div class="content-match-copy"><div class="content-match-title"><label for="${inputId}"><strong>${escapeHtml(match.title || `匹配片段 ${index + 1}`)}</strong>${rejected ? `<i>已排除</i>` : ""}</label><b class="confidence-${escapeHtml(confidenceTier)}" title="按可定位证据强度分层，不是统计概率">${confidenceTier === "reliable" ? "可靠" : "可能相关"}</b></div><p class="content-match-meta">${formatTime(match.start)} → ${formatTime(match.end)}<span>·</span>${Number(match.duration || 0).toFixed(1)} 秒<span>·</span>${type}${match.speaker ? `<span>·</span>${escapeHtml(match.speaker)}` : ""}</p>${evidenceChips}<p class="content-match-diagnostics">${escapeHtml(methodLabel)}<span>·</span>边界：${escapeHtml(boundaryLabel)}</p>${reviewReasons.length ? `<p class="content-match-review-reasons">判断依据：${reviewReasons.map(escapeHtml).join("；")}</p>` : ""}<p class="content-match-evidence"><small>${evidenceLabel}</small>${escapeHtml(evidence)}</p></div></div><div class="content-match-buttons" aria-label="片段操作"><button type="button" class="content-match-preview" data-content-preview="${escapeHtml(match.id)}">预览</button>${reviewButtons}</div>${boundaryEditor}</article>`;
      }).join("")}</div>${candidates.length > 50 ? `<button type="button" class="content-show-more" data-content-show-more>再显示 50 段</button>` : ""}
      ${bulkControlsMarkup}
      ${historyMarkup}
      ${isCurrentSearch ? `<footer class="content-search-actions"><div class="content-selection-summary" data-content-selection-summary></div><div class="content-output-controls"><label><span>输出方式</span><select data-content-output-mode><option value="single_reel" ${draftOutputMode === "single_reel" ? "selected" : ""}>合成一条视频</option><option value="separate_events" ${draftOutputMode === "separate_events" ? "selected" : ""}>每段分别导出</option></select></label><label data-content-order-wrap><span>合成顺序</span><select data-content-order-mode><option value="source" ${draftOrderMode === "source" ? "selected" : ""}>按源视频时间</option><option value="selection" ${draftOrderMode === "selection" ? "selected" : ""}>自定义排列</option><option value="llm_recommend" ${draftOrderMode === "llm_recommend" ? "selected" : ""}>LLM 推荐顺序</option></select></label><small data-content-order-hint>保持源视频中的时间先后，适合过程记录和访谈。</small></div><label class="content-subtitle-toggle"><input type="checkbox" data-content-subtitle ${reviewDraft.subtitleEnabled ? "checked" : ""}><span><b>添加 AI 字幕</b><small data-content-subtitle-status>正在检查所选片段的对白…</small></span></label><div class="content-search-submit-actions"><button type="button" data-content-basket-add>加入合并生成</button><button type="button" class="primary" data-confirm-content>仅生成本次检索</button></div></footer>${recoveryMarkup}` : `<footer class="content-history-actions"><span>勾选只影响这次检索，不会自动加入待合并片段</span><button type="button" data-content-basket-add>加入合并生成</button><button type="button" data-content-search-restore="${escapeHtml(search.id || "")}">恢复为当前检索并编辑</button></footer>`}
      <p class="content-search-safety">人物仅使用画面描述或匿名 Speaker 标签，不进行实名识别。也可以直接在对话中输入新要求继续检索。</p>
    </section></div></article>`;
}

function contentOutputResultMarkup(job, selectedVersions = null, { historical = false } = {}) {
  if (taskModePresentation(job).key !== "content_extract") return "";
  const versions = (selectedVersions || jobOutputVersions(job)).filter((version) => (version.outputs || []).length);
  if (!versions.length) return "";
  const buttons = versions.flatMap((version) => (version.outputs || []).map((output, outputIndex) => {
    const versionLabel = `V${Number(version.number || 1)}`;
    const separate = String(version.outputMode || job.outputMode || "single_reel") !== "single_reel" || (version.outputs || []).length > 1;
    const label = separate ? `${versionLabel} · 内容片段 ${outputIndex + 1}` : `${versionLabel} · 内容视频`;
    const segmentCount = Number(output.segmentCount || output.segments?.length || 0);
    const sourceQuery = String(version.contentSearchInstruction || version.sourceLabel || "").trim();
    return `<button type="button" class="auto-version-button" data-auto-output="${escapeHtml(output.filename || "")}" data-auto-version="${escapeHtml(version.id || versionLabel)}"><span>${escapeHtml(label)} <em>人工确认</em></span><small>${sourceQuery ? `${escapeHtml(sourceQuery)} · ` : ""}${segmentCount ? `${segmentCount} 个已确认片段 · ` : ""}${Number(output.duration || 0).toFixed(1)} 秒 · 点击预览</small></button>`;
  }));
  return `<section class="auto-compose-result-card content-output-result-card${historical ? " historical" : ""}"><strong>${historical ? "以前生成的内容视频" : "内容视频已生成"} · ${versions.length} 个版本</strong><p>${historical ? "这些版本来自之前确认的片段，不会随本次新检索自动改变。" : "视频只包含你审核确认的时间范围。"} 点击版本即可在播放器中预览，也可以下载高清 MP4。</p><div>${buttons.join("")}</div></section>`;
}

function contentOutputVersionsForSearch(job, searchId) {
  return jobOutputVersions(job).filter((version) => String(version.contentSearchId || version.searchId || "") === String(searchId || "") && (version.outputs || []).length);
}

function contentSearchRecordsForJob(job = currentJob) {
  const records = Array.isArray(job?.contentSearchRecords) ? job.contentSearchRecords : [];
  const source = records.length ? records : (job?.contentSearch ? [job.contentSearch] : []);
  return source.map((record) => {
    const cached = contentSearchDetailCache.get(`${job?.id || ""}:${record?.id || ""}`);
    return cached ? { ...record, ...cached, candidateDetailsLoaded: true } : record;
  });
}

function contentSearchHistorySummaryMarkup(search) {
  const count = Number(search?.candidateCount ?? search?.candidates?.length ?? 0);
  const created = search?.createdAt ? new Date(search.createdAt) : null;
  const time = created && Number.isFinite(created.getTime())
    ? created.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "早期记录";
  const status = String(search?.status || "");
  const statusLabel = status === "needs_clarification" ? "等待确认"
    : status === "confirmed" ? "已生成过"
      : status === "queued" || status === "indexing" ? "未完成"
        : count ? `${count} 段` : "无匹配";
  return `<article class="chat-message assistant content-search-message content-search-history-message" data-conversation-key="search:${escapeHtml(search?.id || "")}"><div class="recommendation-wrap"><section class="content-search-history-summary" data-content-search-id="${escapeHtml(search?.id || "")}"><button type="button" data-content-history-open="${escapeHtml(search?.id || "")}" aria-expanded="false"><span><small>${escapeHtml(time)} · 历史检索</small><strong>${escapeHtml(search?.intent?.query || search?.instruction || "未命名检索")}</strong></span><b>${escapeHtml(statusLabel)}</b><em>展开</em></button></section></div></article>`;
}

function contentBasketItems(job = currentJob) {
  const basket = job?.contentSelectionBasket;
  if (basket?.entryMode !== "explicit") return [];
  return Array.isArray(basket.items) ? basket.items : [];
}

function contentBasketHas(job, searchId, matchId) {
  return contentBasketItems(job).some((item) => String(item.searchId) === String(searchId) && String(item.matchId) === String(matchId));
}

function setContentBasketLocal(job, searchId, matchId, selected, candidate = null) {
  const items = [...contentBasketItems(job)];
  const index = items.findIndex((item) => String(item.searchId) === String(searchId) && String(item.matchId) === String(matchId));
  if (selected && index < 0) items.push({
    searchId: String(searchId), matchId: String(matchId), title: candidate?.title || "匹配片段",
    start: Number(candidate?.start) || 0, end: Number(candidate?.end) || 0,
    duration: Math.max(0, Number(candidate?.end) - Number(candidate?.start)),
    sourceQuery: contentSearchRecordsForJob(job).find((item) => String(item.id) === String(searchId))?.instruction || "检索",
  });
  if (!selected && index >= 0) items.splice(index, 1);
  job.contentSelectionBasket = {
    ...(job.contentSelectionBasket || {}),
    schemaVersion: "content-selection-basket-v2", entryMode: "explicit", initialized: true, items,
  };
  renderContentSelectionBasket(job);
  syncVisibleContentBasketAddButtons(job);
  scheduleContentBasketSave(job);
}

function syncContentBasketAddButton(root, job = currentJob, searchId = "") {
  const button = root?.querySelector?.("[data-content-basket-add]");
  if (!button) return;
  const selectedIds = [...root.querySelectorAll("[data-content-match]:checked:not(:disabled)")].map((input) => String(input.value));
  const newCount = selectedIds.filter((matchId) => !contentBasketHas(job, searchId, matchId)).length;
  button.disabled = !selectedIds.length || !newCount;
  button.textContent = !selectedIds.length
    ? "选择片段后加入合并生成"
    : newCount
      ? `加入合并生成 · ${newCount} 段`
      : "所选已加入待合并片段";
}

function syncVisibleContentBasketAddButtons(job = currentJob) {
  document.querySelectorAll(".content-search-review[data-content-search-id]").forEach((root) => {
    syncContentBasketAddButton(root, job, String(root.dataset.contentSearchId || ""));
  });
}

function addSelectedContentToBasket(root, job, searchId, findMatch) {
  const selectedInputs = [...root.querySelectorAll("[data-content-match]:checked:not(:disabled)")];
  if (!selectedInputs.length) {
    showToast("请先选择要加入合并生成的片段");
    return;
  }
  const items = [...contentBasketItems(job)];
  let added = 0;
  selectedInputs.forEach((input) => {
    const matchId = String(input.value || "");
    if (!matchId || items.some((item) => String(item.searchId) === String(searchId) && String(item.matchId) === matchId)) return;
    const candidate = findMatch(matchId);
    if (!candidate) return;
    items.push({
      searchId: String(searchId), matchId, title: candidate.title || "匹配片段",
      start: Number(candidate.start) || 0, end: Number(candidate.end) || 0,
      duration: Math.max(0, Number(candidate.end) - Number(candidate.start)),
      sourceQuery: contentSearchRecordsForJob(job).find((item) => String(item.id) === String(searchId))?.instruction || "检索",
    });
    added += 1;
  });
  if (!added) {
    showToast("所选片段已在待合并片段中");
    syncContentBasketAddButton(root, job, searchId);
    return;
  }
  job.contentSelectionBasket = {
    ...(job.contentSelectionBasket || {}),
    schemaVersion: "content-selection-basket-v2", entryMode: "explicit", initialized: true, items,
  };
  renderContentSelectionBasket(job);
  syncVisibleContentBasketAddButtons(job);
  scheduleContentBasketSave(job);
  showToast(`已明确加入 ${added} 段；普通勾选不会自动进入待合并片段`);
}

function scheduleContentBasketSave(job = currentJob) {
  window.clearTimeout(contentBasketSaveTimer);
  const generation = ++contentBasketSaveGeneration;
  contentBasketSaveTimer = window.setTimeout(async () => {
    if (!job?.id || generation !== contentBasketSaveGeneration) return;
    const basket = job.contentSelectionBasket || {};
    try {
      const response = await api(`/api/jobs/${encodeURIComponent(job.id)}/content-search/basket`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision: Number.isFinite(Number(basket.revision)) ? Number(basket.revision) : null,
          items: (basket.items || []).map(({ searchId, matchId }) => ({ searchId, matchId })),
        }),
      });
      if (currentJob?.id !== job.id || generation !== contentBasketSaveGeneration) return;
      currentJob.contentSelectionBasket = response.basket;
      renderContentSelectionBasket(currentJob);
      syncVisibleContentBasketAddButtons(currentJob);
    } catch (error) {
      if (generation === contentBasketSaveGeneration) showToast(`待合并片段保存失败：${error.message}`);
    }
  }, 180);
}

function renderContentSelectionBasket(job = currentJob) {
  const root = $("#contentSelectionBasket");
  if (!root) return;
  const visible = taskModePresentation(job || {}).key === "content_extract";
  const items = visible ? contentBasketItems(job) : [];
  root.classList.toggle("hidden", !visible || !items.length);
  if (!visible || !items.length) { root.innerHTML = ""; return; }
  const duration = items.reduce((sum, item) => sum + Math.max(0, Number(item.duration) || Number(item.end) - Number(item.start) || 0), 0);
  const sources = new Set(items.map((item) => String(item.sourceQuery || "")).filter(Boolean)).size;
  root.innerHTML = `<details class="content-basket-details"><summary><span class="content-basket-copy"><small>待合并片段</small><strong>${items.length} 段 · ${duration.toFixed(1)} 秒</strong><span>手动加入 · 来自 ${sources || 1} 次检索 · 生成成功后清空</span></span><em>查看明细</em></summary><ol>${items.map((item) => `<li><span><small>${escapeHtml(item.sourceQuery || "检索")}</small><strong>${escapeHtml(item.title || "匹配片段")}</strong><em>${formatTime(item.start)} → ${formatTime(item.end)} · ${Math.max(0, Number(item.duration) || Number(item.end) - Number(item.start) || 0).toFixed(1)} 秒</em></span><button type="button" data-content-basket-remove data-search-id="${escapeHtml(item.searchId || "")}" data-match-id="${escapeHtml(item.matchId || "")}">移出</button></li>`).join("")}</ol></details><div class="content-basket-actions"><button type="button" data-content-basket-clear>清空</button><button type="button" class="primary" data-content-basket-confirm>生成合并视频</button></div>`;
  const details = root.querySelector(".content-basket-details");
  details?.addEventListener("toggle", () => {
    const label = details.querySelector("summary > em");
    if (label) label.textContent = details.open ? "收起明细" : "查看明细";
  });
  root.querySelectorAll("[data-content-basket-remove]").forEach((button) => button.addEventListener("click", () => {
    setContentBasketLocal(job, button.dataset.searchId, button.dataset.matchId, false);
  }));
  root.querySelector("[data-content-basket-clear]")?.addEventListener("click", () => {
    job.contentSelectionBasket = {
      ...(job.contentSelectionBasket || {}),
      schemaVersion: "content-selection-basket-v2", entryMode: "explicit", initialized: true, items: [],
    };
    renderContentSelectionBasket(job);
    syncVisibleContentBasketAddButtons(job);
    scheduleContentBasketSave(job);
  });
  root.querySelector("[data-content-basket-confirm]")?.addEventListener("click", () => confirmContentSelectionBasket(job));
}

function conversationMessageMarkup(message, assistantRoleLabel) {
  const role = message.role === "user" ? "user" : message.kind === "error" ? "error" : "assistant";
  const repeatLabel = Number(message.repeatCount || 1) > 1 ? `<em class="message-repeat">重复 ${message.repeatCount} 次</em>` : "";
  return `<article class="chat-message ${role}" data-conversation-key="message:${escapeHtml(message.id || "")}"><span class="avatar">${role === "user" ? "你" : "AI"}</span><div class="bubble"><small>${role === "user" ? "你" : assistantRoleLabel}${repeatLabel}</small><p>${escapeHtml(message.text)}</p></div></article>`;
}

function normalizedConversationInstruction(value) {
  return String(value || "").toLowerCase().replace(/[\s，。！？：；、“”‘’]/g, "");
}

function contentSearchPlacement(messages, records) {
  const placements = new Map();
  const unresolved = [];
  const usedUsers = new Set();
  const add = (index, search) => placements.set(index, [...(placements.get(index) || []), search]);
  [...records].sort((left, right) => String(left?.createdAt || "").localeCompare(String(right?.createdAt || ""))).forEach((search) => {
    const linkedIndices = messages.map((message, index) => String(message.contentSearchId || "") === String(search?.id || "") ? index : -1).filter((index) => index >= 0);
    const resultIndex = [...linkedIndices].reverse().find((index) => messages[index]?.role !== "user" && messages[index]?.kind === "content-search");
    let anchor = resultIndex ?? linkedIndices[linkedIndices.length - 1] ?? -1;
    if (anchor < 0 && search?.conversationTurnId) {
      anchor = messages.map((message) => String(message.conversationTurnId || "")).lastIndexOf(String(search.conversationTurnId));
    }
    if (anchor < 0 && search?.createdAt) {
      const searchTime = Date.parse(String(search.createdAt));
      const wanted = normalizedConversationInstruction(search?.instruction);
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index];
        if (message.role !== "user" || usedUsers.has(index)) continue;
        const messageTime = Date.parse(String(message.createdAt || ""));
        const text = normalizedConversationInstruction(message.text);
        if (Number.isFinite(searchTime) && Number.isFinite(messageTime) && messageTime > searchTime) continue;
        if (wanted && !text.includes(wanted) && !wanted.includes(text)) continue;
        anchor = index;
        usedUsers.add(index);
        while (anchor + 1 < messages.length && messages[anchor + 1].role !== "user") anchor += 1;
        break;
      }
    }
    if (anchor < 0) unresolved.push(search);
    else add(anchor, search);
  });
  return { placements, unresolved };
}

function conversationTimelineMarkup(job, messages, assistantRoleLabel) {
  const records = contentSearchRecordsForJob(job);
  const { placements, unresolved } = contentSearchPlacement(messages, records);
  const currentId = String(job?.contentSearch?.id || "");
  const searchMarkup = (search) => {
    const current = String(search?.id || "") === currentId;
    const card = !current && !expandedContentSearchIds.has(String(search?.id || ""))
      ? contentSearchHistorySummaryMarkup(search)
      : contentSearchReviewMarkup(job, search, { historicalExpanded: !current });
    const versions = contentOutputVersionsForSearch(job, search?.id);
    return `${card}${versions.length ? contentOutputResultMarkup(job, versions, { historical: !current }) : ""}`;
  };
  const parts = [];
  if (unresolved.length) {
    parts.push(`<article class="chat-message assistant content-early-history" data-conversation-key="early-history"><div class="recommendation-wrap"><details><summary>早期历史 · ${unresolved.length} 条未能可靠归位的检索记录</summary><div>${unresolved.map(searchMarkup).join("")}</div></details></div></article>`);
  }
  messages.forEach((message, index) => {
    parts.push(conversationMessageMarkup(message, assistantRoleLabel));
    (placements.get(index) || []).forEach((search) => parts.push(searchMarkup(search)));
  });
  const placedIds = new Set([...placements.values()].flat().map((search) => String(search?.id || "")));
  unresolved.forEach((search) => placedIds.add(String(search?.id || "")));
  records.filter((search) => !placedIds.has(String(search?.id || ""))).forEach((search) => parts.push(searchMarkup(search)));
  const legacyVersions = jobOutputVersions(job).filter((version) => !version.contentSearchId && !version.searchId && (version.outputs || []).length);
  if (legacyVersions.length) parts.push(`<article class="chat-message assistant content-search-message" data-conversation-key="legacy-content-outputs"><div class="recommendation-wrap">${contentOutputResultMarkup(job, legacyVersions, { historical: true })}</div></article>`);
  return parts.join("");
}

function contentSearchForRoot(root, job = currentJob) {
  const searchId = String(root?.dataset?.contentSearchId || "");
  return contentSearchRecordsForJob(job).find((item) => String(item?.id || "") === searchId)
    || (searchId && String(job?.contentSearch?.id || "") === searchId ? job.contentSearch : null)
    || job?.contentSearch
    || {};
}

function contentSearchJobForRoot(root, job = currentJob) {
  return { ...job, contentSearch: contentSearchForRoot(root, job) };
}

async function ensureContentSearchDetails(searchId, job = currentJob) {
  const record = contentSearchRecordsForJob(job).find((item) => String(item?.id || "") === String(searchId));
  if (!record || record.candidateDetailsLoaded !== false) return record;
  const payload = await api(`/api/jobs/${encodeURIComponent(job.id)}/content-search/history/${encodeURIComponent(searchId)}`);
  const detail = payload.search || {};
  const target = contentSearchRecordsForJob(currentJob).find((item) => String(item?.id || "") === String(searchId));
  if (target) Object.assign(target, detail, { candidateDetailsLoaded: true });
  return target || detail;
}

function collectContentReviewDraft(root, job = currentJob, overrides = {}) {
  const search = job?.contentSearch || {};
  const previous = search.reviewDraft?.searchId === search.id ? search.reviewDraft : {};
  const selectedMatchIds = [...root.querySelectorAll("[data-content-match]:checked")].map((input) => String(input.value));
  const selectedSet = new Set(selectedMatchIds);
  let orderedMatchIds = Array.isArray(overrides.orderedMatchIds)
    ? overrides.orderedMatchIds.map(String).filter((id) => selectedSet.has(id))
    : (previous.orderedMatchIds || []).map(String).filter((id) => selectedSet.has(id));
  orderedMatchIds = [...new Set([...orderedMatchIds, ...selectedMatchIds])];
  return {
    searchId: String(search.id || ""), selectedMatchIds, orderedMatchIds,
    outputMode: String(overrides.outputMode || root.querySelector("[data-content-output-mode]")?.value || previous.outputMode || "single_reel"),
    orderMode: String(overrides.orderMode || root.querySelector("[data-content-order-mode]")?.value || previous.orderMode || "source"),
    subtitleEnabled: Boolean(root.querySelector("[data-content-subtitle]")?.checked),
    subtitleStyle: String(previous.subtitleStyle || "clean"),
  };
}

async function saveContentReviewDraft(root, job = currentJob, overrides = {}) {
  if (!root || !job?.id || !job.contentSearch?.id) return false;
  const draft = collectContentReviewDraft(root, job, overrides);
  const generation = ++contentReviewDraftGeneration;
  try {
    const response = await api(`/api/jobs/${encodeURIComponent(job.id)}/content-search/review-draft`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft),
    });
    if (generation !== contentReviewDraftGeneration || currentJob?.id !== job.id) return false;
    const target = contentSearchRecordsForJob(currentJob).find((item) => String(item?.id || "") === draft.searchId);
    if (target) {
      target.reviewDraft = response.reviewDraft;
      target.defaultSelectedIds = [...response.reviewDraft.selectedMatchIds];
    }
    return true;
  } catch (error) {
    if (generation === contentReviewDraftGeneration && currentJob?.id === job.id) showToast(`选择草稿保存失败：${error.message}`);
    return false;
  }
}

function scheduleContentReviewDraftSave(root, job = currentJob, overrides = {}) {
  window.clearTimeout(contentReviewDraftTimer);
  contentReviewDraftTimer = window.setTimeout(() => saveContentReviewDraft(root, job, overrides), 220);
}

function syncContentSearchSelectionSummary(root, job = currentJob) {
  if (!root) return;
  const selected = [...root.querySelectorAll("[data-content-match]:checked")];
  const ids = new Set(selected.map((input) => String(input.value)));
  const matches = (job?.contentSearch?.candidates || []).filter((item) => ids.has(String(item.id)));
  const duration = matches.reduce((sum, item) => sum + Math.max(0, Number(item.duration) || Number(item.end) - Number(item.start) || 0), 0);
  const summary = root.querySelector("[data-content-selection-summary]");
  const exhaustive = String(job?.contentSearch?.resultMode || "top_k") === "exhaustive";
  const completeness = job?.contentSearch?.completeness || {};
  const strictComplete = !exhaustive || completeness.status === "complete";
  const pendingCount = Number(completeness.pendingCount || 0);
  const gateMessage = !strictComplete
    ? pendingCount
      ? ` · 还有 ${pendingCount} 项需复核`
      : " · 尚未证明找全，可确认风险后生成"
    : selected.length ? " · 确认后才会生成" : " · 请至少选择一段";
  if (summary) summary.innerHTML = `<strong>已选 ${selected.length} 段</strong><span>预计 ${duration.toFixed(1)} 秒${gateMessage}</span>`;
  const confirm = root.querySelector("[data-confirm-content]");
  if (confirm && !actionBusy) {
    confirm.disabled = selected.length === 0;
    confirm.title = pendingCount
      ? `点击查看尚未处理的 ${pendingCount} 个候选`
      : strictComplete ? "" : "点击后可确认接受可能遗漏，并按当前已选片段生成";
  }
}

function syncContentSearchOutputControls(root) {
  const output = root.querySelector("[data-content-output-mode]");
  const order = root.querySelector("[data-content-order-mode]");
  const wrap = root.querySelector("[data-content-order-wrap]");
  const hint = root.querySelector("[data-content-order-hint]");
  if (!output || !order || !wrap || !hint) return;
  const separate = output.value === "separate_events";
  wrap.classList.toggle("hidden", separate);
  order.disabled = separate;
  const hints = {
    source: "保持源视频中的时间先后，适合过程记录和访谈。",
    selection: "确认时可逐项上移或下移，系统严格采用你的排列。",
    llm_recommend: "LLM 只推荐顺序，不会增删片段或修改任何起止点；推荐后还需再次确认。",
  };
  hint.textContent = separate ? "每个片段独立输出，不涉及合成顺序。" : hints[order.value] || hints.source;
  syncContentSearchSelectionSummary(root, currentJob);
}

function contentSearchSubtitleAvailability(root, job = currentJob) {
  const selectedIds = new Set(
    [...root.querySelectorAll("[data-content-match]:checked")].map((input) => String(input.value)),
  );
  const candidates = (job?.contentSearch?.candidates || []).filter((item) => selectedIds.has(String(item.id)));
  const ranges = candidates.map((item) => ({ start: Number(item.start) || 0, end: Number(item.end) || 0 }));
  if (job?.videoInfo?.has_audio === false) {
    return { available: false, count: 0, message: "源视频没有音轨，无需添加字幕。" };
  }
  const directSegments = Array.isArray(job?.speechAnalysis?.segments) ? job.speechAnalysis.segments : [];
  const loadedSegments = timelineTranscriptJobId === job?.id && Array.isArray(timelineTranscript) ? timelineTranscript : [];
  const candidateSegments = candidates.flatMap((item) => Array.isArray(item.speechUnits) ? item.speechUnits : []);
  const transcript = [...directSegments, ...loadedSegments, ...candidateSegments];
  const seen = new Set();
  const matching = transcript.filter((segment) => {
    const text = String(segment?.text || "").trim();
    const start = Number(segment?.start);
    const end = Number(segment?.end);
    const key = `${start}:${end}:${text}`;
    if (seen.has(key) || !/[\p{L}\p{N}]/u.test(text) || !Number.isFinite(start) || !Number.isFinite(end)) return false;
    seen.add(key);
    return ranges.some((range) => Math.min(range.end, end) - Math.max(range.start, start) >= .08);
  });
  if (matching.length) {
    return { available: true, count: matching.length, message: `所选片段检测到 ${matching.length} 段可转写对白。` };
  }
  const speechAnalyzed = Array.isArray(job?.speechAnalysis?.segments)
    || Boolean(job?.speechAnalysis?.status)
    || (job?.recognition?.attemptedModalities || []).includes("speech")
    || (job?.recognition?.completedModalities || []).includes("speech");
  return {
    available: false,
    count: 0,
    message: speechAnalyzed || transcript.length
      ? "所选片段没有可转写对白，无需添加字幕。"
      : "当前检索没有对白转写，无法添加 AI 字幕。",
  };
}

function syncContentSearchSubtitleControls(root, job = currentJob) {
  const input = root?.querySelector("[data-content-subtitle]");
  const status = root?.querySelector("[data-content-subtitle-status]");
  const label = input?.closest(".content-subtitle-toggle");
  if (!input || !status || !label) return;
  const availability = contentSearchSubtitleAvailability(root, job);
  input.disabled = !availability.available;
  if (!availability.available) input.checked = false;
  label.classList.toggle("unavailable", !availability.available);
  status.textContent = availability.message;
  label.title = availability.message;
}

function chatUiContextEntries() {
  if (!currentJob) return [];
  const contentMode = taskModePresentation(currentJob).key === "content_extract";
  const chatRoot = $("#chatMessages");
  const contentMatchRefs = contentMode ? contentBasketItems(currentJob).map(({ searchId, matchId }) => ({ searchId, matchId })) : [];
  const eventGroupIds = [...(chatRoot?.querySelectorAll(".event-group-check:checked") || [])].map((input) => String(input.value));
  const eventSegmentIds = [...(chatRoot?.querySelectorAll(".rail-segment-check:checked") || [])].map((input) => ({
    groupId: String(input.dataset.groupId || input.closest("[data-event-group]")?.dataset.eventGroup || ""),
    segmentId: String(input.value || input.dataset.segmentId || ""),
  })).filter((item) => item.segmentId);
  const viewer = {
    kind: viewerMediaKind,
    ...(currentCandidate?.index != null ? { candidateIndex: Number(currentCandidate.index) } : {}),
    ...(currentEventGroup?.id ? { groupId: String(currentEventGroup.id) } : {}),
    ...(currentEventSegment?.id ? { segmentId: String(currentEventSegment.id) } : {}),
    ...(currentOutput?.filename ? { outputFilename: String(currentOutput.filename) } : {}),
  };
  const viewerLabels = {
    source: "正在看源视频", candidate: "正在预览高光候选", event: "正在预览事件",
    segment: "正在预览镜头", output: contentMode ? "正在预览内容视频" : "正在预览成片", content: "正在预览检索片段",
  };
  const selection = currentJob.manualSelection || pendingTimelineSelection;
  return [
    contentMode ? null : { key: "playhead", label: `播放头 ${formatTime(timelineAbsoluteTime())}`, value: { playheadSeconds: timelineAbsoluteTime() } },
    contentMode ? null : { key: "viewer", label: viewerLabels[viewerMediaKind] || "当前预览对象", value: { viewer } },
    contentMatchRefs.length ? { key: "contentMatches", label: `待合并片段已有 ${contentMatchRefs.length} 段`, value: { selected: { contentMatchRefs, contentMatchIds: contentMatchRefs.map((item) => item.matchId) } } } : null,
    eventGroupIds.length ? { key: "eventGroups", label: `已勾选 ${eventGroupIds.length} 个事件`, value: { selected: { eventGroupIds } } } : null,
    eventSegmentIds.length ? { key: "eventSegments", label: `已勾选 ${eventSegmentIds.length} 个镜头`, value: { selected: { eventSegmentIds } } } : null,
    selection ? { key: "timelineSelection", label: `时间选区 ${formatTime(selection.start)}–${formatTime(selection.end)}`, value: { timelineSelection: { start: Number(selection.start), end: Number(selection.end) } } } : null,
    timelineChatSelections.length ? { key: "timelineSelections", label: `待发送 ${timelineChatSelections.length} 个时间段`, value: { timelineSelections: timelineChatSelections.map((item) => ({ ...item })) } } : null,
    contentMode ? null : { key: "composition", label: outputAssemblyMode === "separate_events" ? "分别导出" : "合成一条", value: { composition: { outputMode: outputAssemblyMode, orderMode: "selection" } } },
  ].filter(Boolean);
}

function collectChatUiContext() {
  const result = {};
  chatUiContextEntries().forEach((entry) => {
    if (ignoredChatContextKeys.has(entry.key)) return;
    Object.entries(entry.value).forEach(([key, value]) => {
      if (key === "selected") result.selected = { ...(result.selected || {}), ...value };
      else result[key] = value;
    });
  });
  return result;
}

function renderChatContextBar() {
  const bar = $("#chatContextBar");
  if (!bar) return;
  const entries = chatUiContextEntries().filter((entry) => !ignoredChatContextKeys.has(entry.key));
  bar.classList.toggle("hidden", !currentJob || !entries.length);
  bar.innerHTML = entries.length
    ? `<small>本次会附带</small>${entries.map((entry) => `<button type="button" data-remove-chat-context="${escapeHtml(entry.key)}" title="不在下一条消息中附带这项">${escapeHtml(entry.label)}<span aria-hidden="true">×</span></button>`).join("")}`
    : "";
  bar.querySelectorAll("[data-remove-chat-context]").forEach((button) => button.addEventListener("click", () => {
    ignoredChatContextKeys.add(button.dataset.removeChatContext);
    renderChatContextBar();
  }));
}

function editProposalMarkup(proposal) {
  if (!proposal || proposal.status !== "pending") return "";
  const preview = proposal.preview || {};
  const before = Number(preview.durationBefore || 0);
  const after = Number(preview.durationAfter || 0);
  const durationFact = before || after
    ? `<span>预计时长 ${before.toFixed(1)}s → ${after.toFixed(1)}s</span>`
    : "";
  const changes = (proposal.changes || []).slice(0, 8);
  return `<article class="chat-message assistant edit-proposal-message"><span class="avatar">AI</span><section class="edit-proposal-card" data-edit-proposal="${escapeHtml(proposal.id || "")}">
    <header><div><small>AI 剪辑提案 · 尚未应用</small><strong>${escapeHtml(proposal.title || "剪辑修改")}</strong></div><b>预览</b></header>
    <p>${escapeHtml(proposal.summary || "请检查这些修改，确认后才会写入正式时间轴。")}</p>
    <div class="edit-proposal-facts">${durationFact}<span>${changes.length} 项修改</span></div>
    ${changes.length ? `<ul>${changes.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
    <p class="edit-proposal-warning">虚线范围是临时时间线预览；取消不会改变现有剪辑。</p>
    <footer><button type="button" class="primary" data-apply-edit-proposal>确认应用</button><button type="button" data-modify-edit-proposal>继续修改</button><button type="button" data-cancel-edit-proposal>取消提案</button></footer>
  </section></article>`;
}

async function resolveEditProposal(action) {
  const proposal = currentJob?.pendingEditProposal;
  if (!proposal?.id || actionBusy) return;
  if (action === "modify") {
    chatInput.value = `修改这个提案：`;
    chatInput.focus();
    chatInput.setSelectionRange(chatInput.value.length, chatInput.value.length);
    return;
  }
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const endpoint = `/api/jobs/${encodeURIComponent(actionToken.jobId)}/edit-proposals/${encodeURIComponent(proposal.id)}${action === "apply" ? "/apply" : ""}`;
    const { job } = await api(endpoint, { method: action === "apply" ? "POST" : "DELETE" });
    if (!commitJobAction(job, actionToken)) return;
    if (jobNeedsPolling(job)) pollJob();
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

function renderConversation(job) {
  const messagesEl = ensureChatMessages();
  // Scope event binding to the DOM root that was just rendered. Opening a
  // home task can overlap with a conversation refresh; querying the global
  // selector again during that handoff could return null and abort rendering.
  const chatRoot = messagesEl;
  const hadConversation = Boolean(chatRoot.querySelector("[data-conversation-key], .chat-message, .content-search-review"));
  const distanceFromBottom = chatRoot.scrollHeight - chatRoot.scrollTop - chatRoot.clientHeight;
  const keepPinnedToBottom = !hadConversation || distanceFromBottom < 56;
  const anchorNode = [...chatRoot.querySelectorAll("[data-conversation-key]")]
    .find((node) => node.getBoundingClientRect().bottom >= chatRoot.getBoundingClientRect().top + 1);
  const scrollAnchor = anchorNode
    ? { key: anchorNode.dataset.conversationKey, offset: anchorNode.getBoundingClientRect().top - chatRoot.getBoundingClientRect().top }
    : null;
  const previousScrollTop = chatRoot.scrollTop;
  let stageHost = $("#chatStageHost");
  if (!stageHost) {
    stageHost = document.createElement("div");
    stageHost.id = "chatStageHost";
    stageHost.className = "chat-stage-host";
    stageHost.setAttribute("aria-live", "polite");
    messagesEl.append(stageHost);
  }
  const stageNodes = stageHost ? [...stageHost.children] : [];
  // Preserve the live progress node while replacing conversation markup. It
  // may currently be a direct child of #chatMessages (during analysis), so
  // innerHTML would otherwise detach it and the next poll could no longer
  // find #jobStatus.
  const preservedAnalysisConsole = document.getElementById("jobStatus");
  const messages = compactConversationMessages(job.messages || []);
  const assistantRoleLabel = taskModePresentation(job).key === "content_extract" ? "内容探索助手" : "高光发现助手";
  const contentMode = taskModePresentation(job).key === "content_extract";
  // Older jobs were created before pendingSelectionGroupIds was persisted.
  // Infer the latest manual timeline group from the confirmation notice so a
  // refresh still shows only the clips the user just selected.
  const manualGroups = (job.eventGroups || []).filter((group) => group.assemblyStrategy === "manual");
  const latestSelectionNotice = [...messages].reverse().find((message) => message.role === "assistant" && /已准备好你选中的多个时间轴片段|已找到相同的时间轴选区/.test(String(message.text || "")));
  const inferredPendingSelectionGroupIds = job.pendingSelectionGroupIds?.length
    ? job.pendingSelectionGroupIds.map(String)
    : (latestSelectionNotice && manualGroups.length
      ? [String(manualGroups[manualGroups.length - 1].id)]
      : []);
  let eventTimelineSummary = null;
  let html = contentMode
    ? conversationTimelineMarkup(job, messages, assistantRoleLabel)
    : messages.map((message) => conversationMessageMarkup(message, assistantRoleLabel)).join("");
  html += editProposalMarkup(job.pendingEditProposal);
  if (job.status === "brief_confirmation") {
    const brief = job.brief || {};
    html += `<article class="chat-message assistant brief-confirmation-message"><span class="avatar">AI</span><div class="brief-wrap"><div class="bubble"><small>高光导演 · 需求简报待确认</small><p>我先把你的要求整理成了下面这份简报。现在还没有开始视觉分析，请先检查并修改；确认后才会调用 VLM。</p></div>${briefEditorMarkup(brief, "chat")}</div></article>`;
  } else if (!contentMode && job.status === "awaiting_confirmation" && job.eventGroups?.length) {
    const pendingSelection = inferredPendingSelectionGroupIds.length > 0;
    const eventGroupsForReview = pendingSelection
      ? job.eventGroups.filter((group) => inferredPendingSelectionGroupIds.includes(String(group.id)))
      : job.eventGroups.filter((group) => group.assemblyStrategy !== "manual");
    const recommended = new Set(pendingSelection ? inferredPendingSelectionGroupIds : (job.recommendedGroupIds || []));
    const target = Number(job.totalTargetSeconds || job.request?.totalTargetSeconds || 0);
    const visibleGroupIds = new Set(eventGroupsForReview.map((group) => String(group.id)));
    const visibleRecommended = [...recommended].filter((id) => visibleGroupIds.has(String(id)));
    const timelineSegmentCount = eventGroupsForReview.reduce((sum, group) => sum + (group.segments || []).length, 0);
    const groupedCandidateCount = new Set(eventGroupsForReview.flatMap((group) =>
      (group.availableSegments || group.segments || []).map((segment) => String(segment.candidateIndex ?? segment.id))
    )).size;
    const refinedCandidateCount = Number(job.candidates?.length || 0) || groupedCandidateCount || timelineSegmentCount;
    const currentTimelineGroups = visibleRecommended
      .map((id) => eventGroupsForReview.find((group) => String(group.id) === String(id)))
      .filter(Boolean);
    const currentTimelineSegments = currentTimelineGroups.flatMap((group) => group.segments || []);
    const generatedVersions = jobOutputVersions(job).filter((version) => (version.outputs || []).length);
    const generatedOutputs = generatedVersions.flatMap((version) => version.outputs || []);
    const timelineEditedSinceOutput = timelineEditedAfterLatestOutput(job, generatedVersions);
    const timelineHasMatchingOutput = generatedOutputs.some((output) => timelineSegmentsMatch(currentTimelineSegments, output.segments || []));
    const timelineHasUnrenderedChanges = !pendingSelection
      && currentTimelineSegments.length > 0
      && generatedOutputs.length > 0
      && !timelineHasMatchingOutput;
    const allocated = pendingSelection
      ? eventGroupsForReview.reduce((sum, group) => sum + (group.segments || []).reduce((inner, segment) => inner + Number(segment.duration || (Number(segment.end) - Number(segment.start)) || 0), 0), 0)
      : currentTimelineSegments.reduce((sum, segment) => sum + Number(segment.duration || (Number(segment.end) - Number(segment.start)) || 0), 0);
    eventTimelineSummary = {
      allocated,
      generatedVersionCount: generatedVersions.length,
      groupIds: currentTimelineGroups.map((group) => group.id),
      pendingSelection,
      timelineEditedSinceOutput,
      timelineHasUnrenderedChanges,
      timelineSegmentCount,
      visibleRecommendedCount: visibleRecommended.length,
    };
    const budgetClass = target && Math.abs(allocated - target) > target * Number(job.durationTolerance || .1) ? " over" : "";
    html += `<article class="chat-message assistant recommendation-message"><span class="avatar">AI</span><div class="recommendation-wrap">
      <section class="recommendation-card event-recommendation">
        <header><div><small>${pendingSelection ? "已选时间轴片段" : "VLM 精修与事件归组"}</small><strong>${pendingSelection ? `已准备 ${timelineSegmentCount} 个镜头` : `精修保留 ${refinedCandidateCount} 个候选镜头 · 归并为 ${eventGroupsForReview.length} 个事件`}</strong></div><b>${pendingSelection ? "待确认顺序" : `推荐 ${visibleRecommended.length} 个事件`}</b></header>
        <div class="duration-budget${budgetClass}"><span><b>${pendingSelection ? "已选片段" : timelineEditedSinceOutput ? "当前时间轴" : "推荐成片"} ${allocated.toFixed(1)} 秒</b>${target ? ` / 单条目标 ${target.toFixed(1)} 秒` : " · AI 推荐"}</span><i><b style="width:${target ? Math.min(100, allocated / target * 100) : 100}%"></b></i></div>
        <p>${pendingSelection ? "这些是你刚从时间轴选中的片段。可以逐个预览并调整顺序，确认无误后直接合成；不会自动带入其他事件。" : timelineHasUnrenderedChanges ? (timelineEditedSinceOutput ? `时间轴已修改；现有 ${generatedVersions.length} 个成片版本仍基于修改前的方案，生成新版本后才会得到当前 ${allocated.toFixed(1)} 秒内容。` : `当前 ${generatedVersions.length} 个成片版本都没有包含上方 ${allocated.toFixed(1)} 秒推荐时间轴；可补充生成对应版本。`) : `当前时间轴展示 ${timelineSegmentCount} 个事件镜头；系统已选择 ${visibleRecommended.length} 个事件用于成片。可点击时间轴预览，满意后直接生成。`}</p>
        ${timelineHasUnrenderedChanges ? `<div class="timeline-render-pending"><span><strong>${timelineEditedSinceOutput ? "当前修改尚未生成" : "推荐时间轴尚未生成"}</strong><small>已有版本不会被覆盖，将新增一个完整对应当前时间轴的版本</small></span><button type="button" data-render-current-timeline>${timelineEditedSinceOutput ? "生成当前时间轴版本" : "生成推荐时间轴版本"}</button></div>` : ""}<div class="review-selection-summary" data-selection-summary>正在计算选择结果…</div>
        <div class="event-group-list">${eventGroupsForReview.map((group, groupIndex) => `<article class="event-group-row${recommended.has(group.id) ? " recommended" : ""}" data-event-group="${escapeHtml(group.id)}">
          <header><input class="event-group-check" type="checkbox" value="${escapeHtml(group.id)}" ${recommended.has(group.id) ? "checked" : ""}><span><strong>${escapeHtml(group.title)}</strong><small>${group.segments.length} 个镜头 · ${Number(group.actualDuration).toFixed(1)} 秒</small></span><b>${Math.round(group.score)}</b><button type="button" class="add-selection-event" ${job.manualSelection ? "" : "disabled"}>加选区</button><button type="button" class="rename-event">命名</button><button type="button" class="preview-event">组合预览</button></header>
          <p>${escapeHtml(group.summary)}</p>
          <details ${groupIndex === 0 ? "open" : ""}><summary>展开事件镜头</summary><div class="event-segments">${group.segments.map((segment, segmentIndex) => `<div class="event-segment" data-segment-id="${escapeHtml(segment.id)}"><span><b>${segmentIndex + 1}. ${escapeHtml(segment.role)}</b><small>${formatTime(segment.start)} → ${formatTime(segment.end)} · ${Number(segment.duration).toFixed(1)} 秒 · ${segment.transitionIn?.type === "dissolve" ? "短叠化" : "硬切"}</small></span><button type="button" class="preview-segment">看</button><button type="button" class="move-segment-up" ${segmentIndex === 0 ? "disabled" : ""}>↑</button><button type="button" class="move-segment-down" ${segmentIndex === group.segments.length - 1 ? "disabled" : ""}>↓</button><button type="button" class="move-segment-group">移</button><button type="button" class="delete-segment">删</button></div>`).join("")}</div></details>
        </article>`).join("")}</div>
        <div class="recommendation-actions"><button type="button" class="confirm-event-groups primary">将已选事件合成 1 条</button><button type="button" class="confirm-all-events">将全部事件合成 1 条</button><button type="button" class="export-event-groups">分别导出已选事件</button>${target ? `<button type="button" class="rebalance-budget">调整到约 ${target.toFixed(0)} 秒</button>` : ""}<button type="button" class="create-event-from-selection" ${job.manualSelection ? "" : "disabled"}>用选区新建事件</button></div>
      </section></div></article>`;
  } else if (job.status === "awaiting_confirmation" && job.candidates?.length) {
    const recommended = new Set(job.recommendedIndices || []);
    const reviewCandidates = sortedCandidatesForReview(job);
    html += `<article class="chat-message assistant recommendation-message"><span class="avatar">AI</span><div class="recommendation-wrap">
      <section class="recommendation-card">
        <header><div><small>智能推荐</small><strong>发现 ${job.candidates.length} 个有效候选</strong></div><b>推荐 ${recommended.size} 条</b></header>
        <p>${job.analysisCacheHit ? "已复用相同视频和要求的分析缓存，无需重复调用模型。" : "每条时长来自各自视觉事件边界。"} 已默认勾选综合评分较高的推荐项，你可以调整选择后再裁剪。</p><div class="review-selection-summary" data-selection-summary>正在计算选择结果…</div>
    <div class="candidate-review-toolbar"><span>审核排序</span><button type="button" data-candidate-sort="score" class="${candidateReviewSort === "score" ? "active" : ""}">评分</button><button type="button" data-candidate-sort="time" class="${candidateReviewSort === "time" ? "active" : ""}">时间</button><button type="button" data-candidate-sort="review" class="${candidateReviewSort === "review" ? "active" : ""}">优先复核</button><em>N/P 切换高光 · R 排除 · Enter 确认</em></div>
        <div class="candidate-list">${reviewCandidates.map((candidate) => { const selected = recommended.has(candidate.index) && !locallyExcludedCandidates.has(Number(candidate.index)); return `<div class="candidate-row${selected ? " recommended" : ""}${locallyExcludedCandidates.has(Number(candidate.index)) ? " excluded" : ""}" data-candidate-row="${candidate.index}"><label><input type="checkbox" value="${candidate.index}" ${selected ? "checked" : ""}><span><strong>${escapeHtml(candidate.title)}</strong><small>${formatTime(candidate.start)} → ${formatTime(candidate.end)} · ${Number(candidate.duration).toFixed(1)} 秒${candidateReviewLabels(candidate).length ? ` · ${candidateReviewLabels(candidate).join(" · ")}` : ""}</small></span><b>${Math.round(candidate.score)}</b></label><button type="button" class="rename-candidate" data-candidate-index="${candidate.index}">命名</button><button type="button" class="candidate-menu" data-candidate-index="${candidate.index}">操作</button><button type="button" class="preview-candidate" data-candidate-index="${candidate.index}">预览</button></div>`; }).join("")}</div>
        <div class="recommendation-actions"><button type="button" class="confirm-selected primary">生成所选片段</button><button type="button" class="confirm-all">全部生成</button>${job.candidates.length > 3 ? '<button type="button" class="confirm-top3">只生成评分前 3</button>' : ""}</div>
      </section>
    </div></article>`;
  } else if (job.status === "awaiting_confirmation" && job.manualSelection) {
    const selection = job.manualSelection;
    html += `<article class="chat-message assistant recommendation-message"><span class="avatar">AI</span><div class="recommendation-wrap"><section class="recommendation-card manual-selection-card"><header><div><small>手动时间段</small><strong>${formatTime(selection.start)} → ${formatTime(selection.end)}</strong></div><b>${Number(selection.duration || selection.end - selection.start).toFixed(1)} 秒</b></header><p>这是你从源视频时间轴直接选中的范围，不依赖 AI 高光候选，可以直接合成为成片。</p><div class="recommendation-actions"><button type="button" class="confirm-manual-selection primary">合成这个时间段</button></div></section></div></article>`;
  }
  const hasGeneratedOutputs = Boolean((job.outputs || []).length || (job.outputVersions || []).some((version) => (version.outputs || []).length));
  const autoCompositionComplete = job.autoComposition?.status === "completed";
  const autoCompositionRunning = ["queued", "running"].includes(String(job.autoComposition?.status || ""));
  if (job.status === "awaiting_confirmation" && autoCompositionRunning) {
    html += `<article class="chat-message assistant auto-compose-progress-message"><span class="avatar thinking-avatar"><span class="thinking-orb-slot" data-thinking-orb data-orb-state="composing" data-orb-size="30" data-orb-theme="light" data-orb-label="自动成片"></span></span><div class="recommendation-wrap">${autoCompositionProgressMarkup(job)}</div></article>`;
  }
  if (job.autoComposition?.status === "partial" && hasGeneratedOutputs) {
    const facts = autoCompositionVersionFacts(job);
    html += `<article class="chat-message assistant auto-compose-partial-message"><span class="avatar">AI</span><div class="recommendation-wrap"><section class="auto-compose-partial"><small>AI 自动成片 · 部分完成</small><strong>已生成 ${facts.completed} 个可播放版本</strong><p>其他剪辑版本生成失败，已有成片仍可正常预览和下载。${job.autoComposition.error ? ` 原因：${escapeHtml(job.autoComposition.error)}` : ""}</p></section></div></article>`;
  }
  if (contentMode && hasGeneratedOutputs && !job.pendingSelectionGroupIds?.length && !contentSearchRecordsForJob(job).length) html += contentOutputResultMarkup(job);
  if (["completed", "awaiting_confirmation"].includes(job.status) && hasGeneratedOutputs && !job.pendingSelectionGroupIds?.length && !autoCompositionComplete) {
    const rerunCount = String(job.request?.count).toLowerCase() === "auto"
      ? (job.confirmedGroupIds?.length || job.recommendedCount || jobOutputCount(job))
      : job.request.count;
    const quickActions = [
      autoCompositionRunning || contentMode ? "" : `<button type="button" data-reedit-job>返回事件审核</button>`,
      job.status === "completed" ? (contentMode
        ? '<button type="button" data-content-edit-query>修改查找条件</button>'
        : `<button type="button" data-prompt="尝试避开刚才的区间，再生成 ${rerunCount} 条">尝试生成不同片段</button>`)
        : "",
    ].filter(Boolean).join("");
    html += quickActions ? `<div class="quick-actions">${quickActions}</div>` : "";
    if (job.status === "completed") {
      html += `<section class="completed-dialog-actions"><strong>${contentMode ? "需要调整这条内容视频？" : "需要调整这条成片？"}</strong><p>${contentMode ? "重新选择已检索到的内容片段后，可以生成一个新版本。" : "返回事件审核重新选择镜头后，可以生成一个新的成片版本。"}</p><div><button type="button" data-reedit-job>${contentMode ? "重新选择内容片段" : "返回事件审核"}</button></div></section>`;
    }
  }
  if (autoCompositionComplete && hasGeneratedOutputs) {
    const fallbackAutoMeta = (index, label = "") => {
      if (/审片优化|review_repair/i.test(String(label))) return { displayName: "AI 审片优化版", sourceLabel: "成片审片", strategyDescription: "观看实际成片后完成局部返修" };
      if (index === 0 || /VLM/i.test(String(label))) return { displayName: "完整事件版", sourceLabel: "视觉推荐", strategyDescription: "保留事件完整过程" };
      if (/情绪/.test(String(label))) return { displayName: "情绪集中版", sourceLabel: "剪辑规划", strategyDescription: "优先保留情绪高点" };
      if (/信息|密度/.test(String(label))) return { displayName: "信息精简版", sourceLabel: "剪辑规划", strategyDescription: "优先保留关键信息" };
      return { displayName: "节奏连贯版", sourceLabel: "剪辑规划", strategyDescription: "强化镜头前后衔接" };
    };
    const autoVersions = (job.autoComposition?.versions || ["完整事件版", "剪辑规划版"]).map((item, index) => {
      const raw = typeof item === "string" ? fallbackAutoMeta(index, item) : item;
      return { ...fallbackAutoMeta(index, raw?.label || raw?.displayName || ""), ...(raw || {}) };
    });
    const automaticKeys = new Set(["vlm", "narrative", "emotion", "information", "review_repair"]);
    const allGeneratedVersions = jobOutputVersions(job).filter((version) => (version.outputs || []).length);
    const automaticGeneratedVersions = allGeneratedVersions.filter((version) =>
      version.previewOnly || automaticKeys.has(String(version.strategyKey || ""))
    );
    const generatedVersions = (automaticGeneratedVersions.length ? automaticGeneratedVersions : allGeneratedVersions)
      .sort((left, right) => Number(left.number || 0) - Number(right.number || 0));
    const versionButtons = autoVersions.map((meta, index) => {
      const version = generatedVersions[index];
      const output = version?.outputs?.[0];
      const review = version?.reviewReport || output?.reviewReport || {};
      const reviewFact = review.status === "completed"
        ? ` · 审片 ${Number(review.overallScore || 0).toFixed(0)} 分${review.reviewDepth === "screened" ? "（快速筛查）" : ""}`
        : "";
      return output
        ? `<button type="button" class="auto-version-button${version.recommended ? " recommended" : ""}" data-auto-output="${escapeHtml(output.filename)}" data-auto-version="${escapeHtml(version.id || `v${index + 1}`)}"><span>${escapeHtml(meta.displayName)} <em>${escapeHtml(meta.sourceLabel)}</em>${version.recommended ? " <b>AI 推荐</b>" : ""}</span><small>${escapeHtml(version.recommendationReason || meta.strategyDescription)} · ${Number(output.duration || 0).toFixed(1)} 秒${reviewFact} · 点击预览</small></button>`
        : `<span class="auto-version-unavailable">${escapeHtml(meta.displayName)} <em>${escapeHtml(meta.sourceLabel)}</em></span>`;
    });
    generatedVersions.slice(autoVersions.length).forEach((version) => {
      const output = version.outputs?.[0];
      if (!output) return;
      const meta = autoVersionPresentation(job, version);
      versionButtons.push(`<button type="button" class="auto-version-button" data-auto-output="${escapeHtml(output.filename)}" data-auto-version="${escapeHtml(version.id || `v${version.number}`)}"><span>${escapeHtml(meta.displayName)} <em>${escapeHtml(meta.sourceLabel)}</em></span><small>${escapeHtml(meta.strategyDescription)} · ${Number(output.duration || 0).toFixed(1)} 秒 · 点击预览</small></button>`);
    });
    const hasUnrenderedTimeline = Boolean(eventTimelineSummary?.timelineHasUnrenderedChanges);
    const duplicatePlansSkipped = Math.max(0, Number(job.autoComposition?.duplicatePlansSkipped) || 0);
    const duplicatePlansReplaced = Math.max(0, Number(job.autoComposition?.duplicatePlansReplaced) || 0);
    const dedupeDescription = duplicatePlansReplaced
      ? `检测到 ${duplicatePlansReplaced} 个方案与已有成片重复，已自动改用其他高分事件；当前保留 ${generatedVersions.length} 个内容不同的版本。`
      : duplicatePlansSkipped
        ? `AI 原计划生成 ${generatedVersions.length + duplicatePlansSkipped} 个版本，其中 ${duplicatePlansSkipped} 个与已有成片重复，已自动合并；当前保留 ${generatedVersions.length} 个不同版本。`
      : "";
    const previewVersionCount = generatedVersions.filter((version) => version.previewOnly || version.outputs?.some((output) => output.previewOnly)).length;
    const resultTitle = hasUnrenderedTimeline
      ? `已有 AI 样片 · ${generatedVersions.length} 个版本`
      : previewVersionCount
        ? `AI 可审核样片 · ${previewVersionCount} 个不同版本`
        : `成片已生成 · ${generatedVersions.length} 个不同版本`;
    const resultDescription = hasUnrenderedTimeline
      ? (eventTimelineSummary?.timelineEditedSinceOutput
        ? `这些版本基于修改前的时间轴，不包含当前 ${eventTimelineSummary.allocated.toFixed(1)} 秒调整；请先生成当前时间轴版本。${dedupeDescription ? ` ${dedupeDescription}` : ""}`
        : `这些版本均不对应上方 ${eventTimelineSummary.allocated.toFixed(1)} 秒推荐时间轴；请先生成推荐时间轴版本。${dedupeDescription ? ` ${dedupeDescription}` : ""}`)
      : `${dedupeDescription || "AI 已根据画面、声音、对白和情绪线索生成多种剪辑版本。"} 点击版本预览比较；审核样片可直接下载，选定后也可按源分辨率导出高清成片。`;
    html += `<section class="auto-compose-result-card${hasUnrenderedTimeline ? " timeline-stale" : ""}"><strong>${resultTitle}</strong><p>${resultDescription}</p><div>${versionButtons.join("")}</div></section>`;
  }
  if (["cancelled", "failed"].includes(job.status)) {
    const sourceIncomplete = job.failureCode === "source_incomplete";
    const contentFailure = taskModePresentation(job).key === "content_extract";
    html += `<section class="retry-analysis-card" data-border-beam data-beam-size="pulse-inner" data-beam-color="sunset" data-beam-theme="dark" data-beam-strength="0.52" data-beam-duration="2.5" data-beam-brightness="1.18" data-beam-saturation="1" data-beam-hue-range="14" data-beam-radius="10"><strong>${sourceIncomplete ? "源视频文件不完整" : job.status === "cancelled" ? "任务已取消" : contentFailure ? "内容检索未完成" : "任务分析失败"}</strong><p>${sourceIncomplete ? "当前文件无法覆盖完整时间轴，不能继续复用。请返回全部任务并重新上传完整的原始视频。" : contentFailure ? "将保留当前检索条件、人物选择和可复用索引，从内容检索阶段继续。" : "可以沿用当前已确认的剪辑要求重新分析，不需要重新上传视频。"}</p><button type="button" class="${sourceIncomplete ? "return-home-from-failure" : "reanalyze-job"}">${sourceIncomplete ? "返回并重新上传" : contentFailure ? "↻ 恢复内容检索" : "↻ 重新分析"}</button></section>`;
  }
  if (analysisConsoleVisible(job)) html += inlineAnalysisProgressMarkup(job);
  // The inline progress card already communicates the current stage while a
  // pipeline is active. Avoid rendering a second, lower-priority thinking
  // bubble underneath it.
  if (!analysisConsoleVisible(job)) html += thinkingMessageMarkup(thinkingConfigForJob(job), job);
  // Keep the stage host node stable. Replacing it on every poll invalidated
  // listeners and briefly left moved rail nodes detached from the document.
  messagesEl.innerHTML = html;
  messagesEl.append(stageHost);
  stageNodes.forEach((node) => stageHost.append(node));
  if (preservedAnalysisConsole && preservedAnalysisConsole.parentElement !== messagesEl) {
    messagesEl.append(preservedAnalysisConsole);
  }
  // This progress surface is rebuilt from streamed job state. Mount its
  // activity loader synchronously instead of waiting for a DOM observer.
  syncGenerativeLoaders(messagesEl);
  syncOutputVersionBeams(job, messagesEl);
  syncBorderBeams(messagesEl);
  messagesEl.querySelector("[data-inline-cancel]")?.addEventListener("click", cancelCurrentJob);
  messagesEl.querySelector("[data-apply-edit-proposal]")?.addEventListener("click", () => resolveEditProposal("apply"));
  messagesEl.querySelector("[data-modify-edit-proposal]")?.addEventListener("click", () => resolveEditProposal("modify"));
  messagesEl.querySelector("[data-cancel-edit-proposal]")?.addEventListener("click", () => resolveEditProposal("cancel"));
  updateInlineAnalysisProgress(job);
  messagesEl.querySelectorAll(".content-search-review").forEach((contentSearchRoot) => {
    const scopedJob = contentSearchJobForRoot(contentSearchRoot, job);
    const searchId = String(scopedJob.contentSearch?.id || "");
    const findMatch = (id) => (scopedJob.contentSearch?.candidates || []).find((item) => String(item.id) === String(id));
    contentSearchRoot.querySelectorAll("[data-content-preview]").forEach((button) => button.addEventListener("click", async () => {
      const detailed = await ensureContentSearchDetails(searchId, job).catch((error) => {
        showToast(`读取历史检索详情失败：${error.message}`);
        return scopedJob.contentSearch;
      });
      previewContentMatch((detailed?.candidates || []).find((item) => String(item.id) === String(button.dataset.contentPreview)));
    }));
    contentSearchRoot.querySelectorAll("[data-content-evidence]").forEach((button) => {
      const openEvidence = async (event) => {
        if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        event.stopPropagation();
        const detailed = await ensureContentSearchDetails(searchId, job).catch((error) => {
          showToast(`读取历史检索详情失败：${error.message}`);
          return scopedJob.contentSearch;
        });
        previewContentMatch((detailed?.candidates || []).find((item) => String(item.id) === String(button.dataset.contentEvidence)), { autoplay: false });
      };
      button.addEventListener("click", openEvidence);
      button.addEventListener("keydown", openEvidence);
    });
    wireContentBoundaryEditors(contentSearchRoot, scopedJob);
    contentSearchRoot.querySelector("[data-content-output-mode]")?.addEventListener("change", () => {
      syncContentSearchOutputControls(contentSearchRoot);
      scheduleContentReviewDraftSave(contentSearchRoot, scopedJob);
    });
    const questionSourceSelect = contentSearchRoot.querySelector("[data-content-question-source]");
    const applyQuestionSourceFilter = () => {
      const source = String(questionSourceSelect?.value || "all");
      contentSearchFilterState.set(`${job?.id || ""}:${searchId}`, { questionSource: source });
      contentSearchRoot.querySelectorAll("[data-content-match-row]").forEach((row) => {
        row.hidden = source !== "all" && String(row.dataset.contentQuestionSource || "other") !== source;
      });
    };
    questionSourceSelect?.addEventListener("change", applyQuestionSourceFilter);
    if (questionSourceSelect) applyQuestionSourceFilter();
    contentSearchRoot.querySelector("[data-content-dialogue-mode]")?.addEventListener("change", async (event) => {
      const select = event.currentTarget;
      const previous = select.dataset.previousValue || select.value;
      select.dataset.previousValue = select.value;
      select.disabled = true;
      try {
        const response = await api(`/api/jobs/${encodeURIComponent(job.id)}/content-search/dialogue-mode`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ searchId, dialogueMode: select.value }),
        });
        if (response?.job) {
          currentJob = response.job;
          renderJob(currentJob);
        }
      } catch (error) {
        select.value = previous;
        showToast(`问答模式切换失败：${error.message}`);
      } finally {
        select.disabled = false;
      }
    });
    contentSearchRoot.querySelector("[data-content-order-mode]")?.addEventListener("change", () => {
      syncContentSearchOutputControls(contentSearchRoot);
      scheduleContentReviewDraftSave(contentSearchRoot, scopedJob);
    });
    contentSearchRoot.querySelector("[data-content-subtitle]")?.addEventListener("change", () => {
      syncContentSearchSubtitleControls(contentSearchRoot, scopedJob);
      scheduleContentReviewDraftSave(contentSearchRoot, scopedJob);
    });
    contentSearchRoot.querySelectorAll("[data-content-match]").forEach((input) => input.addEventListener("change", async () => {
      if (input.dataset.contentReviewStatus === "pending") {
        if (!input.checked) return;
        input.disabled = true;
        const saved = await sendContentSearchFeedback("review_keep", input.value, findMatch(input.value), { skipConfirmation: true, searchId });
        if (!saved && input.isConnected) {
          input.checked = false;
          input.disabled = false;
        }
        if (saved) syncContentBasketAddButton(contentSearchRoot, currentJob, searchId);
        return;
      }
      syncContentSearchSubtitleControls(contentSearchRoot, scopedJob);
      syncContentSearchSelectionSummary(contentSearchRoot, scopedJob);
      syncContentBasketAddButton(contentSearchRoot, currentJob, searchId);
      renderChatContextBar();
      if (String(searchId) === String(currentJob?.contentSearch?.id || "")) scheduleContentReviewDraftSave(contentSearchRoot, scopedJob);
    }));
    syncContentSearchOutputControls(contentSearchRoot);
    syncContentSearchSubtitleControls(contentSearchRoot, scopedJob);
    syncContentBasketAddButton(contentSearchRoot, currentJob, searchId);
    contentSearchRoot.querySelectorAll("[data-content-select]").forEach((button) => button.addEventListener("click", async () => {
      if (button.dataset.contentSelect === "toggle") {
        const next = button.getAttribute("aria-pressed") !== "true";
        const inputs = [...contentSearchRoot.querySelectorAll("[data-content-match]")]
          .filter((input) => !input.disabled);
        inputs.forEach((input) => { input.checked = next; });
        button.setAttribute("aria-pressed", String(next));
        button.textContent = next ? "取消全部" : "选择全部";
        if (next) {
          button.disabled = true;
          try {
            const response = await api(`/api/jobs/${encodeURIComponent(job.id)}/content-search/bulk-keep`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ searchId, matchIds: inputs.map((input) => input.value) }),
            });
            const liveSearch = contentSearchForRoot(contentSearchRoot, currentJob);
            scopedJob.contentSearch = liveSearch;
            const keptIds = new Set(inputs.map((input) => String(input.value)));
            (liveSearch.candidates || []).forEach((match) => {
              if (!keptIds.has(String(match.id))) return;
              match.reviewStatus = "kept";
              match.requiresReview = false;
              match.selected = true;
            });
            inputs.forEach((input) => {
              if (input.dataset.contentReviewStatus !== "pending") return;
              input.dataset.contentReviewStatus = "kept";
              input.setAttribute("aria-label", `选择${input.getAttribute("aria-label")?.replace(/^勾选并保留/, "") || "片段"}`);
              const row = input.closest("[data-content-match-row]");
              row?.classList.remove("review-pending");
              row?.querySelector(".content-match-title label i")?.remove();
            });
            syncContentSearchSubtitleControls(contentSearchRoot, scopedJob);
            syncContentSearchSelectionSummary(contentSearchRoot, scopedJob);
            syncContentBasketAddButton(contentSearchRoot, currentJob, searchId);
            renderChatContextBar();
          } catch (error) {
            inputs.forEach((input) => { input.checked = false; });
            button.setAttribute("aria-pressed", "false");
            button.textContent = "选择全部";
            showToast(`批量选择失败：${error.message || "服务暂时不可用"}`);
          } finally {
            if (button.isConnected) button.disabled = false;
          }
          return;
        }
      }
      syncContentSearchSubtitleControls(contentSearchRoot, scopedJob);
      syncContentSearchSelectionSummary(contentSearchRoot, scopedJob);
      syncContentBasketAddButton(contentSearchRoot, currentJob, searchId);
      renderChatContextBar();
      if (String(searchId) === String(currentJob?.contentSearch?.id || "")) scheduleContentReviewDraftSave(contentSearchRoot, scopedJob);
    }));
    contentSearchRoot.querySelector("[data-content-show-more]")?.addEventListener("click", (event) => {
      const hidden = [...contentSearchRoot.querySelectorAll(".content-candidate-overflow.hidden")];
      hidden.slice(0, 50).forEach((row) => row.classList.remove("hidden"));
      if (hidden.length <= 50) event.currentTarget.remove();
    });
    contentSearchRoot.querySelector("[data-content-show-possible]")?.addEventListener("click", (event) => {
      const button = event.currentTarget;
      const expanded = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(expanded));
      contentSearchRoot.querySelectorAll(".content-candidate-possible").forEach((row) => {
        row.classList.toggle("hidden", !expanded);
      });
      const label = button.querySelector("span");
      if (label) label.textContent = expanded ? "收起可能相关" : "可能相关";
    });
    contentSearchRoot.querySelector("[data-content-basket-add]")?.addEventListener("click", () => {
      addSelectedContentToBasket(contentSearchRoot, currentJob, searchId, findMatch);
    });
    contentSearchRoot.querySelector("[data-confirm-content]")?.addEventListener("click", () => confirmContentSearch(contentSearchRoot, scopedJob));
  });
  messagesEl.querySelectorAll("[data-content-feedback]").forEach((button) => button.addEventListener("click", () => {
    const matchId = button.dataset.contentMatchId || null;
    const root = button.closest(".content-search-review");
    const scopedJob = contentSearchJobForRoot(root, job);
    const match = scopedJob.contentSearch?.candidates?.find((item) => String(item.id) === String(matchId));
    sendContentSearchFeedback(button.dataset.contentFeedback, matchId, match, { searchId: scopedJob.contentSearch?.id });
  }));
  messagesEl.querySelectorAll("[data-content-history-open]").forEach((button) => button.addEventListener("click", async () => {
    const searchId = String(button.dataset.contentHistoryOpen || "");
    if (!searchId) return;
    button.disabled = true;
    try {
      const detail = await ensureContentSearchDetails(searchId, job);
      contentSearchDetailCache.set(`${job.id}:${searchId}`, { ...detail, candidateDetailsLoaded: true });
      expandedContentSearchIds.add(searchId);
      renderConversation(currentJob || job);
    } catch (error) {
      button.disabled = false;
      showToast(`读取历史检索详情失败：${error.message}`);
    }
  }));
  messagesEl.querySelectorAll("[data-content-search-history-toggle]").forEach((button) => button.addEventListener("click", () => {
    const card = button.closest(".content-search-review");
    const searchId = String(card?.dataset?.contentSearchId || "");
    if (!searchId) return;
    expandedContentSearchIds.delete(searchId);
    renderConversation(currentJob || job);
  }));
  messagesEl.querySelectorAll("[data-content-search-restore]").forEach((button) => button.addEventListener("click", () => restoreContentSearch(button.dataset.contentSearchRestore)));
  messagesEl.querySelectorAll("[data-person-label]").forEach((button) => button.addEventListener("click", () => {
    updateContentPersonLabel(button.dataset.personLabel, button.dataset.personCurrentLabel || "");
  }));
  messagesEl.querySelectorAll("[data-person-target]").forEach((input) => input.addEventListener("change", () => {
    syncContentPersonTargetControls(input.closest("[data-person-target-panel]"));
  }));
  messagesEl.querySelectorAll("[data-person-match-mode]").forEach((input) => input.addEventListener("change", () => {
    syncContentPersonTargetControls(input.closest("[data-person-target-panel]"));
  }));
  messagesEl.querySelector("[data-person-target-confirm]")?.addEventListener("click", (event) => {
    const panel = event.currentTarget.closest("[data-person-target-panel]");
    const personIds = [...panel.querySelectorAll("[data-person-target]:checked")].map((input) => input.value);
    const matchMode = panel.querySelector("[data-person-match-mode]:checked")?.value || (personIds.length === 1 ? "any" : "");
    if (!personIds.length) return void showToast("请至少选择一个人物");
    if (!matchMode) return void showToast("请选择多人匹配方式");
    selectContentPersonTarget(personIds, matchMode, event.currentTarget);
  });
  messagesEl.querySelectorAll("[data-person-target-panel]").forEach((panel) => syncContentPersonTargetControls(panel, { initial: true }));
  messagesEl.querySelectorAll("[data-person-history-target]").forEach((button) => button.addEventListener("click", () => {
    const personIds = String(button.dataset.personHistoryTarget || "").split(",").filter(Boolean);
    selectContentPersonTarget(personIds, button.dataset.personHistoryMode || "any", button);
  }));
  messagesEl.querySelectorAll("[data-person-preview]").forEach((button) => button.addEventListener("click", () => {
    const person = job.contentIndex?.persons?.find((item) => String(item.id) === String(button.dataset.personPreview));
    const time = Number(button.dataset.personPreviewTime || person?.representativeTime || 0);
    showSource({ autoplay: false });
    viewerMediaKind = "source";
    seekSourceTime(time);
    showToast(`已定位到${person?.label || person?.defaultLabel || "人物"}的代表画面`);
  }));
  messagesEl.querySelectorAll(".content-person-preview img").forEach((image) => image.addEventListener("error", () => {
    image.closest(".content-person-preview")?.classList.add("thumbnail-unavailable");
    image.remove();
  }, { once: true }));
  messagesEl.querySelectorAll("[data-content-evidence-choice]").forEach((button) => button.addEventListener("click", () => {
    const instruction = String(button.dataset.contentInstruction || job.contentSearch?.instruction || job.request?.contentInstruction || "继续当前检索");
    const capabilities = String(button.dataset.contentCapabilities || "").split(",").filter(Boolean);
    sendChat(instruction, {
      evidenceMode: button.dataset.contentEvidenceMode || button.dataset.contentEvidenceChoice,
      allowedCapabilities: capabilities,
    });
  }));
  messagesEl.querySelectorAll("[data-content-speaker-preview]").forEach((button) => button.addEventListener("click", () => {
    showToast(`正在预览 ${button.dataset.contentPreviewSpeaker || "Speaker 候选"}`);
    previewContentMatch({
      id: button.dataset.contentSpeakerPreview,
      title: button.dataset.contentPreviewSpeaker || "Speaker 候选",
      start: Number(button.dataset.contentPreviewStart || 0),
      end: Number(button.dataset.contentPreviewEnd || button.dataset.contentPreviewStart || 0),
      evidenceType: "speech",
    });
  }));
  messagesEl.querySelectorAll("[data-content-speaker-confirm]").forEach((button) => button.addEventListener("click", () => {
    confirmContentPersonSpeaker(button.dataset.personId, button.dataset.contentSpeakerConfirm, button);
  }));
  messagesEl.querySelectorAll("[data-content-expansion]").forEach((button) => button.addEventListener("click", () => {
    const option = job.contentSearch?.expansionOptions?.find((item) => String(item.id) === String(button.dataset.contentExpansion));
    if (!option) return;
    const instruction = String(job.contentSearch?.instruction || job.request?.contentInstruction || "继续当前检索");
    const currentCapabilities = job.contentSearch?.executionPlan?.allowedCapabilities || job.request?.contentAllowedCapabilities || [];
    const capabilities = [...new Set([...currentCapabilities, ...(option.addCapabilities || [])])];
    const payload = {
      evidenceMode: capabilities.length > 1 ? "mixed" : (job.contentSearch?.executionPlan?.evidenceMode || job.request?.contentEvidenceMode),
      allowedCapabilities: capabilities,
    };
    if (option.scopeKind === "all") Object.assign(payload, {
      searchScopeKind: "all", searchScopeStart: 0,
      searchScopeEnd: Number(job.videoInfo?.duration || 0) || null,
    });
    sendChat(instruction, payload);
  }));
  messagesEl.querySelector("[data-content-expand]")?.addEventListener("click", () => {
    const instruction = String(job.contentSearch?.instruction || job.request?.contentInstruction || "重新查找相关内容");
    sendChat(instruction, {
      searchScopeKind: "all", searchScopeStart: 0,
      searchScopeEnd: Number(job.videoInfo?.duration || 0) || null,
      evidenceMode: job.contentSearch?.executionPlan?.evidenceMode || job.request?.contentEvidenceMode,
      allowedCapabilities: job.contentSearch?.executionPlan?.allowedCapabilities || job.request?.contentAllowedCapabilities,
    });
  });
  messagesEl.querySelector("[data-content-continue]")?.addEventListener("click", () => {
    sendChat(String(job.contentSearch?.instruction || job.request?.contentInstruction || "继续当前检索"), {
      evidenceMode: job.contentSearch?.executionPlan?.evidenceMode || job.request?.contentEvidenceMode,
      allowedCapabilities: job.contentSearch?.executionPlan?.allowedCapabilities || job.request?.contentAllowedCapabilities,
    });
  });
  messagesEl.querySelectorAll("[data-auto-output]").forEach((button) => button.addEventListener("click", () => {
    const filename = button.dataset.autoOutput;
    if (!filename) return;
    messagesEl.querySelectorAll(".auto-version-button").forEach((item) => item.classList.toggle("active", item === button));
    setOutputVersionBeamSelection(button);
    selectOutput(filename, true);
  }));
  const chatComposeButton = $("#chatComposeButton");
  const chatComposeRecommendedButton = $("#chatComposeRecommendedButton");
  const chatComposePlanButton = $("#chatComposePlanButton");
  const chatComposeSubtitle = $("#chatComposeSubtitleMode");
  const canChatCompose = job.status === "awaiting_confirmation" && Boolean(job.eventGroups?.length || job.candidates?.length || job.manualSelection);
  chatComposeButton?.classList.toggle("hidden", !canChatCompose);
  chatComposeRecommendedButton?.classList.toggle("hidden", !canChatCompose || chatInput?.dataset.timelineCompose !== "true");
  chatComposePlanButton?.classList.toggle("hidden", !canChatCompose || !job.eventGroups?.length);
  if (chatComposeButton && chatInput?.dataset.timelineCompose !== "true") chatComposeButton.textContent = "✦ 合成所选片段";
  chatComposeSubtitle?.classList.toggle("hidden", true);
  if (chatComposeButton) chatComposeButton.onclick = () => {
    if (job.manualSelection && (!job.eventGroups?.length && !job.candidates?.length || chatInput?.dataset.timelineCompose === "true")) {
      if (chatInput?.dataset.timelineCompose !== "true") fillChatWithTimelineSelection(job.manualSelection);
      sendChat();
      return;
    }
    const savedSubtitleMode = String(job.brief?.subtitlePreference || job.request?.subtitleMode || "none");
    const subtitleMode = savedSubtitleMode === "ask" ? "none" : savedSubtitleMode;
    if (job.eventGroups?.length) {
      const ids = job.recommendedGroupIds?.length ? job.recommendedGroupIds : job.eventGroups.map((group) => group.id);
      confirmEventGroups(ids, "single_reel", null, subtitleMode);
    } else {
      const indices = job.recommendedIndices?.length ? job.recommendedIndices : job.candidates.map((candidate) => candidate.index);
      confirmCandidates(indices, "single_reel");
    }
  };
  if (chatComposeRecommendedButton) chatComposeRecommendedButton.onclick = () => {
    const savedSubtitleMode = String(job.brief?.subtitlePreference || job.request?.subtitleMode || "none");
    const subtitleMode = savedSubtitleMode === "ask" ? "none" : savedSubtitleMode;
    if (job.eventGroups?.length) {
      const ids = job.recommendedGroupIds?.length ? job.recommendedGroupIds : job.eventGroups.map((group) => group.id);
      confirmEventGroups(ids, "single_reel", null, subtitleMode);
    } else {
      const indices = job.recommendedIndices?.length ? job.recommendedIndices : job.candidates.map((candidate) => candidate.index);
      confirmCandidates(indices, "single_reel");
    }
  };
  if (chatComposePlanButton) chatComposePlanButton.onclick = () => setDirectorStage("compose");
  if (job.status === "awaiting_confirmation" && job.eventGroups?.length) {
    const card = chatRoot.querySelector(".event-recommendation");
    if (card) {
      card?.querySelectorAll(".event-group-list, .recommendation-actions, .review-selection-summary").forEach((node) => node.remove());
      const paragraph = card.querySelector(":scope > p");
      if (paragraph && eventTimelineSummary) paragraph.textContent = eventTimelineSummary.pendingSelection
        ? "已记录你从时间轴选中的片段。可以逐个预览并调整顺序，确认无误后直接合成。"
        : eventTimelineSummary.timelineHasUnrenderedChanges
          ? (eventTimelineSummary.timelineEditedSinceOutput
            ? `时间轴已修改；现有 ${eventTimelineSummary.generatedVersionCount} 个成片版本仍基于修改前方案。生成新版本后才会得到当前 ${eventTimelineSummary.allocated.toFixed(1)} 秒内容。`
            : `当前 ${eventTimelineSummary.generatedVersionCount} 个成片版本都没有包含上方 ${eventTimelineSummary.allocated.toFixed(1)} 秒推荐时间轴；可补充生成对应版本。`)
          : `当前时间轴展示 ${eventTimelineSummary.timelineSegmentCount} 个事件镜头；系统已选择 ${eventTimelineSummary.visibleRecommendedCount} 个事件用于成片。可点击时间轴预览，满意后直接生成。`;
    }
  }
  normalizeSegmentActionLabels(chatRoot);
  syncThinkingOrbs(chatRoot);
  // The message list is replaced on every poll. A second frame makes the
  // canvas mount reliable even when the deferred orb bundle finishes one
  // frame after the conversation render.
  requestAnimationFrame(() => syncThinkingOrbs(chatRoot));
  chatRoot.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => sendChat(button.dataset.prompt)));
  chatRoot.querySelectorAll("[data-content-edit-query]").forEach((button) => button.addEventListener("click", () => {
    chatInput.value = "";
    chatInput.placeholder = "输入新的查找条件，例如：找到蓝色衣服的人说话的片段";
    chatInput.focus();
  }));
  chatRoot.querySelectorAll("[data-candidate-sort]").forEach((button) => button.addEventListener("click", () => {
    candidateReviewSort = button.dataset.candidateSort || "score";
    renderConversation(currentJob);
  }));
  chatRoot.querySelectorAll(".candidate-list input[type=\"checkbox\"]").forEach((input) => input.addEventListener("change", () => {
    const index = Number(input.value);
    if (input.checked) locallyExcludedCandidates.delete(index);
    else locallyExcludedCandidates.add(index);
    input.closest(".candidate-row")?.classList.toggle("excluded", !input.checked);
    persistReviewExclusions();
    updateReviewSelectionSummary(chatRoot);
  }));
  chatRoot.querySelectorAll("[data-reedit-job]").forEach((button) => button.addEventListener("click", reopenCurrentJobForEditing));
  chatRoot.querySelector("[data-render-current-timeline]")?.addEventListener("click", () => {
    if (!eventTimelineSummary?.groupIds?.length) return void window.alert("当前时间轴没有可生成的事件镜头");
    const savedSubtitleMode = String(job.brief?.subtitlePreference || job.request?.subtitleMode || "none");
    const subtitleMode = savedSubtitleMode === "ask" ? "none" : savedSubtitleMode;
    confirmEventGroups(eventTimelineSummary.groupIds, "single_reel", null, subtitleMode);
  });
  chatRoot.querySelector(".reanalyze-job")?.addEventListener("click", () => reanalyzeJob(job));
  chatRoot.querySelector(".inline-cancel")?.addEventListener("click", cancelCurrentJob);
  bindBriefEditor(job, chatRoot);
  chatRoot.querySelector(".confirm-event-groups")?.addEventListener("click", () => {
    const checked = new Set([...chatRoot.querySelectorAll(".event-group-check:checked")].map((input) => input.value));
    const ids = [...eventGroupSelectionOrder.filter((id) => checked.has(String(id))), ...[...checked].filter((id) => !eventGroupSelectionOrder.includes(id))];
    confirmEventGroups(ids, "single_reel");
  });
  chatRoot.querySelector(".confirm-all-events")?.addEventListener("click", () => confirmEventGroups(job.eventGroups.map((group) => group.id), "single_reel"));
  chatRoot.querySelector(".export-event-groups")?.addEventListener("click", () => {
    const checked = new Set([...chatRoot.querySelectorAll(".event-group-check:checked")].map((input) => input.value));
    const ids = [...eventGroupSelectionOrder.filter((id) => checked.has(String(id))), ...[...checked].filter((id) => !eventGroupSelectionOrder.includes(id))];
    confirmEventGroups(ids, "separate_events");
  });
  chatRoot.querySelector(".create-event-from-selection")?.addEventListener("click", createEventFromSelection);
  chatRoot.querySelector(".confirm-manual-selection")?.addEventListener("click", () => {
    if (!currentJob?.manualSelection) return;
    if (chatInput?.dataset.timelineCompose !== "true") fillChatWithTimelineSelection(currentJob.manualSelection);
    sendChat();
  });
  chatRoot.querySelector(".rebalance-budget")?.addEventListener("click", () => sendChat(`单条成片目标时长调整为 ${Number(job.totalTargetSeconds || job.request?.totalTargetSeconds)} 秒`));
  chatRoot.querySelectorAll(".event-group-row").forEach((row) => {
    const group = job.eventGroups?.find((item) => item.id === row.dataset.eventGroup);
    if (!group) return;
    row.querySelector(".preview-event")?.addEventListener("click", () => previewEventGroup(group));
    row.querySelector(".rename-event")?.addEventListener("click", () => renameEventGroup(group));
    row.querySelector(".add-selection-event")?.addEventListener("click", () => addSelectionToEventGroup(group));
    row.querySelectorAll(".event-segment").forEach((segmentRow, segmentIndex) => {
      const segment = group.segments.find((item) => item.id === segmentRow.dataset.segmentId);
      segmentRow.querySelector(".preview-segment")?.addEventListener("click", () => previewEventSegment(group, segment));
      segmentRow.querySelector(".delete-segment")?.addEventListener("click", () => deleteEventSegment(group, segment));
      segmentRow.querySelector(".move-segment-up")?.addEventListener("click", () => reorderEventSegment(group, segmentIndex, segmentIndex - 1));
      segmentRow.querySelector(".move-segment-down")?.addEventListener("click", () => reorderEventSegment(group, segmentIndex, segmentIndex + 1));
      segmentRow.querySelector(".move-segment-group")?.addEventListener("click", () => moveEventSegment(group, segment));
    });
  });
  chatRoot.querySelectorAll(".event-group-check").forEach((input) => input.addEventListener("change", () => { recordEventGroupSelection(input.value, input.checked); updateReviewSelectionSummary(chatRoot); renderChatContextBar(); }));
  updateReviewSelectionSummary(chatRoot);
  chatRoot.querySelector(".confirm-selected")?.addEventListener("click", () => {
    const indices = [...chatRoot.querySelectorAll(".candidate-list input:checked")].map((input) => Number(input.value));
    confirmCandidates(indices);
  });
  chatRoot.querySelector(".confirm-all")?.addEventListener("click", () => confirmCandidates(job.candidates.map((candidate) => candidate.index)));
  chatRoot.querySelector(".confirm-top3")?.addEventListener("click", () => {
    const indices = [...job.candidates].sort((left, right) => right.score - left.score).slice(0, 3).map((candidate) => candidate.index);
    confirmCandidates(indices);
  });
  chatRoot.querySelectorAll(".preview-candidate").forEach((button) => button.addEventListener("click", () => previewCandidate(Number(button.dataset.candidateIndex))));
  chatRoot.querySelectorAll(".rename-candidate").forEach((button) => button.addEventListener("click", () => {
    const index = Number(button.dataset.candidateIndex);
    const candidate = job.candidates.find((item) => Number(item.index) === index);
    const title = window.prompt("输入候选名称", candidate?.title || "");
    if (title?.trim() && title.trim() !== candidate?.title) sendChat(`第 ${index + 1} 条改名为${title.trim()}`);
  }));
  chatRoot.querySelectorAll(".candidate-menu").forEach((button) => button.addEventListener("click", () => {
    const index = Number(button.dataset.candidateIndex);
    const choice = window.prompt("输入操作：删除、复制、拆分，或“移动到第 2 条”", "复制");
    if (!choice?.trim()) return;
    const action = choice.trim();
    if (/^删除$/.test(action)) sendChat(`删除第 ${index + 1} 条`);
    else if (/^复制$/.test(action)) sendChat(`复制第 ${index + 1} 条`);
    else if (/^拆分$/.test(action)) sendChat(`把第 ${index + 1} 条拆成两段`);
    else if (/移动到第\s*[一二两三四五六七八\d]+\s*条/.test(action)) sendChat(`把第 ${index + 1} 条${action}`);
    else window.alert("支持：删除、复制、拆分、移动到第 N 条；合并两个候选可直接在对话中输入。 ");
  }));
  if (keepPinnedToBottom) {
    chatRoot.scrollTop = chatRoot.scrollHeight;
  } else if (scrollAnchor) {
    const restored = [...chatRoot.querySelectorAll("[data-conversation-key]")]
      .find((node) => node.dataset.conversationKey === scrollAnchor.key);
    if (restored) chatRoot.scrollTop += restored.getBoundingClientRect().top - chatRoot.getBoundingClientRect().top - scrollAnchor.offset;
    else chatRoot.scrollTop = Math.min(previousScrollTop, Math.max(0, chatRoot.scrollHeight - chatRoot.clientHeight));
  } else {
    chatRoot.scrollTop = Math.min(previousScrollTop, Math.max(0, chatRoot.scrollHeight - chatRoot.clientHeight));
  }
  renderChatContextBar();
  renderContentSelectionBasket(job);
}

async function reanalyzeJob(job) {
  if (!job || actionBusy || !["cancelled", "failed"].includes(job.status)) return;
  if (!await requestActionConfirmation({ title: "重新分析当前视频", summary: "将沿用已确认的剪辑要求重新调用视觉模型。", details: ["不需要重新上传视频", "会清空本次未完成的候选结果", "已有独立成片版本不会被覆盖"] })) return;
  const actionToken = captureJobAction(job);
  actionBusy = true;
  try {
    const { job: updated } = await api(`/api/jobs/${encodeURIComponent(job.id)}/reanalyze`, { method: "POST" });
    if (!commitJobAction(updated, actionToken)) return;
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

function renderEvidencePlaceholder({ time, title, reason } = {}) {
  const evidence = $("#evidencePanel");
  if (!evidence) return;
  const job = currentJob;
  const groupCount = Number(job?.eventGroups?.length || 0);
  const candidateCount = Number(job?.candidates?.length || 0);
  const outputCount = jobOutputCount(job);
  const running = isPipelineRunningStatus(job?.status);
  const defaultTime = running
    ? "AI 分析中"
    : groupCount || candidateCount
      ? "时间轴已就绪"
      : outputCount
        ? `${outputCount} 个成片版本`
        : "审核说明";
  const defaultTitle = running ? "正在发现事件与镜头" : "选择事件或镜头";
  const defaultReason = running
    ? "分析结果会逐步出现在下方时间轴。完成后点击事件或镜头，即可在这里查看说明和判断依据。"
    : groupCount || candidateCount
      ? `下方时间轴已展示 ${groupCount || candidateCount} 个可审核项目。点击事件或镜头查看详情，只有选择“缩放到当前事件”才会改变时间轴范围。`
      : outputCount
        ? "可从播放器顶部选择成片预览，也可以回到源视频继续查看时间轴。"
        : "点击下方时间轴中的事件或镜头，在这里查看内容说明、时间范围和判断依据。";
  evidence.classList.remove(
    "hidden",
    "candidate-mode",
    "montage-mode",
    "output-mode",
    "evidence-in-gutter",
    "evidence-gutter-left",
    "evidence-gutter-right",
    "evidence-compact",
    "evidence-expanded",
  );
  evidence.classList.add("evidence-placeholder");
  $("#clipTime").textContent = time || defaultTime;
  $("#clipTitle").textContent = title || defaultTitle;
  $("#clipScore").textContent = "";
  $("#clipReason").textContent = reason || defaultReason;
  const transcript = $("#clipTranscript");
  if (transcript) {
    transcript.innerHTML = "";
    transcript.classList.add("hidden");
  }
  if ($("#clipEvidenceMeta")) $("#clipEvidenceMeta").innerHTML = "";
  if ($("#clipEvidence")) $("#clipEvidence").innerHTML = "";
  if ($("#outputExplanation")) {
    $("#outputExplanation").innerHTML = "";
    $("#outputExplanation").classList.add("hidden");
  }
  $("#addToChatButton")?.classList.add("hidden");
  $("#keepButton")?.classList.add("hidden");
  $("#replaceButton")?.classList.add("hidden");
  syncEvidencePlacement();
}

function showSource({ autoplay = true } = {}) {
  if (!currentJob) return;
  sourcePreviewRetryToken = 0;
  candidatePreviewToken += 1;
  currentOutput = null;
  currentCandidate = null;
  currentEventGroup = null;
  currentEventSegment = null;
  candidatePreviewEnd = null;
  viewerMediaKind = "source";
  clearOutputVersionSelectionState();
  clearPlayerNotice();
  applyMediaAspect(viewerShell, currentJob.videoInfo?.width, currentJob.videoInfo?.height);
  const sourceUrl = sourcePreviewUrl();
  if (!sourceUrl) {
    setMainVideoSource("");
    showPlayerNotice("当前任务暂时没有可用的源视频地址");
  } else {
    setMainVideoSource(sourceUrl);
    if (autoplay) requestMainVideoAutoplay();
  }
  beginSourcePreviewPolling();
  $("#viewerBadge").textContent = "源视频";
  renderOutputPreviewSelector(currentJob);
  $("#reviewKicker").textContent = "SOURCE VIDEO";
  $("#reviewTitle").textContent = currentJob.filename;
  $("#downloadButton")?.classList.add("hidden");
  $("#finalizePreviewButton")?.classList.add("hidden");
  syncOneOffFinalizeAction(currentJob);
  $("#subtitleButton")?.classList.add("hidden");
  $("#keepButton")?.classList.add("hidden");
  $("#replaceButton")?.classList.add("hidden");
  $("#subtitleButton")?.classList.add("hidden");
  renderEvidencePlaceholder();
  document.querySelectorAll(".candidate-row").forEach((row) => row.classList.remove("previewing"));
  document.querySelectorAll(".clip-card").forEach((card) => card.classList.remove("active"));
  updateTimeline();
  syncReviewSelectionClasses();
}

function jobOutputVersions(job = currentJob) {
  if (!job) return [];
  if (job.outputVersions?.length) return [...job.outputVersions].sort((a, b) => Number(b.number || 0) - Number(a.number || 0));
  if (!job.outputs?.length) return [];
  return [{ id: "v001", number: 1, createdAt: job.updatedAt, outputMode: job.outputMode, outputs: job.outputs }];
}

function jobOutputCount(job = currentJob) {
  const explicitCount = job?.outputCount;
  // Number(null) is 0. Treat an absent count as absent instead of allowing it
  // to hide outputVersions that are already persisted on the job.
  if (explicitCount !== null && explicitCount !== undefined && explicitCount !== "" && Number.isFinite(Number(explicitCount))) {
    return Number(explicitCount);
  }
  return jobOutputVersions(job).reduce((count, version) => count + (version.outputs || []).length, 0);
}

function autoVersionPresentation(job, version) {
  if (version?.displayName) {
    return {
      displayName: version.displayName,
      sourceLabel: version.sourceLabel || (version.masterReady ? "高清成片" : "AI 样片"),
      strategyDescription: version.strategyDescription || "保留该版本已确认的剪辑方案",
    };
  }
  const legacyFormalTitle = String(version?.outputs?.[0]?.title || "");
  if (/正式导出/.test(legacyFormalTitle)) {
    return {
      displayName: legacyFormalTitle.replace(/\s*[·｜|]\s*正式导出.*$/, "").trim() || "高清成片",
      sourceLabel: "高清导出",
      strategyDescription: "按已确认样片的镜头与顺序进行高清渲染",
    };
  }
  const index = Math.max(0, Number(version?.number || 1) - 1);
  const automaticVersions = Array.isArray(job?.autoComposition?.versions) ? job.autoComposition.versions : [];
  const raw = automaticVersions[index];
  if (raw && typeof raw === "object" && raw.displayName) return raw;
  if (automaticVersions.length && index >= automaticVersions.length) {
    return { displayName: "当前时间轴", sourceLabel: "手动生成", strategyDescription: "按当前审核时间轴生成" };
  }
  const label = typeof raw === "string" ? raw : "";
  if (index === 0 || /VLM/i.test(label)) return { displayName: "完整事件版", sourceLabel: "视觉推荐", strategyDescription: "保留事件完整过程" };
  if (/情绪/.test(label)) return { displayName: "情绪集中版", sourceLabel: "剪辑规划", strategyDescription: "优先保留情绪高点" };
  if (/信息|密度/.test(label)) return { displayName: "信息精简版", sourceLabel: "剪辑规划", strategyDescription: "优先保留关键信息" };
  return { displayName: "节奏连贯版", sourceLabel: "剪辑规划", strategyDescription: "强化镜头前后衔接" };
}

function currentVersionOutputs(job = currentJob) {
  const versions = jobOutputVersions(job);
  const currentId = String(job?.currentOutputVersionId || versions[0]?.id || "");
  return (versions.find((version) => String(version.id) === currentId) || versions[0])?.outputs || [];
}

function orderedJobOutputs(job = currentJob) {
  return [...jobOutputVersions(job)]
    .sort((left, right) => Number(left.number || 0) - Number(right.number || 0))
    .flatMap((version) => (version.outputs || []).map((item) => ({ item, version })));
}

function renderOutputPreviewSelector(job = currentJob) {
  const select = $("#videoViewSelect");
  if (!select) return;
  const outputs = orderedJobOutputs(job);
  if (!job) {
    select.classList.add("hidden");
    select.innerHTML = "";
    return;
  }
  const outputOptions = outputs.map(({ item, version }, index) => {
    const presentation = autoVersionPresentation(job, version);
    const strategyName = item.displayName || presentation.displayName || item.title;
    const label = `成片 ${index + 1}${strategyName ? ` · ${strategyName}` : ""}`;
    return `<option value="${escapeHtml(item.filename)}">${escapeHtml(label)}</option>`;
  }).join("");
  select.innerHTML = `<option value="source">源视频</option>${outputOptions}`;
  const selected = viewerMediaKind === "output" ? currentOutput?.filename : "source";
  select.value = selected && outputs.some(({ item }) => item.filename === selected) ? selected : "source";
  select.classList.remove("hidden");
}

function locateJobOutput(filename, job = currentJob) {
  for (const version of jobOutputVersions(job)) {
    const output = (version.outputs || []).find((item) => item.filename === filename);
    if (output) return { output, version };
  }
  return null;
}

function transcriptForItem(item) {
  if (!item || !Array.isArray(timelineTranscript) || !timelineTranscript.length) return [];
  const start = Number(item.start) || 0;
  const end = Number(item.end) || start;
  return timelineTranscript
    .filter((segment) => Number(segment.end) > start && Number(segment.start) < end)
    .sort((left, right) => Number(left.start) - Number(right.start));
}

function sourceEventContextForSegment(segment) {
  if (!segment || !currentJob?.eventGroups?.length) return null;
  const segmentId = String(segment.id || "");
  const candidateIndex = Number(segment.candidateIndex ?? segment.index);
  const sourceStart = Number(segment.start);
  const sourceEnd = Number(segment.end);
  for (const group of currentJob.eventGroups) {
    const match = (group.segments || []).find((candidate) => {
      if (segmentId && String(candidate.id || "") === segmentId) return true;
      const sameCandidate = Number.isFinite(candidateIndex)
        && Number(candidate.candidateIndex ?? candidate.index) === candidateIndex;
      const sameRange = Math.abs(Number(candidate.start) - sourceStart) < .05
        && Math.abs(Number(candidate.end) - sourceEnd) < .05;
      return sameCandidate && sameRange;
    });
    if (match) return { group, segment: match };
  }
  return null;
}

function previewCompositionSourceSegment(composed, segmentIndex, sourceTime) {
  const segment = composed?.segments?.[Number(segmentIndex)];
  if (!segment) return;
  const isEventGroup = (currentJob?.eventGroups || []).some((group) => String(group.id || "") === String(composed?.id || ""));
  const context = isEventGroup
    ? { group: composed, segment }
    : sourceEventContextForSegment(segment);
  previewEventSegment(context?.group || null, context?.segment || segment, { seekTime: sourceTime });
}

function renderClipTranscript(item, kind = "candidate") {
  const root = $("#clipTranscript");
  if (!root) return;
  const composed = kind === "event" || kind === "output";
  const segments = composed
    ? (item?.segments || []).flatMap((sourceSegment, composedIndex) => transcriptForItem(sourceSegment)
      .map((segment) => ({ segment, composedIndex })))
    : transcriptForItem(item).map((segment) => ({ segment, composedIndex: null }));
  const unique = [];
  const seen = new Set();
  segments.forEach((entry) => {
    const segment = entry.segment;
    const key = `${entry.composedIndex ?? "source"}:${Number(segment.start).toFixed(3)}:${Number(segment.end).toFixed(3)}`;
    if (!seen.has(key)) { seen.add(key); unique.push(entry); }
  });
  if (!unique.length) {
    root.classList.add("hidden");
    root.innerHTML = "";
    return;
  }
  root.classList.remove("hidden");
  root.innerHTML = `<header><strong>对应转写</strong><span>${unique.length} 段 · 点击定位</span></header>${unique.slice(0, 12).map((entry) => {
    const segment = entry.segment;
    const sourceStart = Number(segment.start) || 0;
    const sourceEnd = Number(segment.end) || sourceStart;
    const displayStart = composed ? compositionTimeForSource(item, entry.composedIndex, sourceStart) : sourceStart;
    const displayEnd = composed ? compositionTimeForSource(item, entry.composedIndex, sourceEnd) : sourceEnd;
    const timePrefix = kind === "output" ? "成片 " : kind === "event" ? "组合 " : "";
    const primaryAttributes = composed
      ? `data-composed-segment="${entry.composedIndex}" data-composed-source-time="${sourceStart}"`
      : `data-transcript-seek="${sourceStart}"`;
    const sourceAction = composed ? `<button type="button" class="clip-source-link" data-source-segment="${entry.composedIndex}" data-source-time="${sourceStart}" title="在源视频中查看 ${formatTime(sourceStart)} → ${formatTime(sourceEnd)}" aria-label="在源视频中查看该段转写">源片段</button>` : "";
    return `<div class="clip-transcript-row">
      <button type="button" class="clip-transcript-line" ${primaryAttributes}>
        <small>${timePrefix}${formatTime(displayStart)} → ${formatTime(displayEnd)}${segment.speaker ? ` · ${escapeHtml(segment.speaker)}` : ""}</small>
        <span class="clip-transcript-copy">${escapeHtml(segment.text || "声音片段")}</span>
      </button>${sourceAction}
    </div>`;
  }).join("")}`;
  root?.querySelectorAll("[data-transcript-seek]").forEach((button) => button.addEventListener("click", () => seekTimeline(Number(button.dataset.transcriptSeek))));
  root?.querySelectorAll("[data-composed-segment]").forEach((button) => button.addEventListener("click", () => {
    seekComposedMedia(item, Number(button.dataset.composedSegment), Number(button.dataset.composedSourceTime), kind);
  }));
  root?.querySelectorAll("[data-source-segment]").forEach((button) => button.addEventListener("click", () => {
    previewCompositionSourceSegment(item, Number(button.dataset.sourceSegment), Number(button.dataset.sourceTime));
  }));
}

function fallbackOutputEditingExplanation(item = {}, version = null) {
  const segments = Array.isArray(item.segments) ? item.segments : [];
  const target = Number(item.targetSeconds);
  const actual = Number(item.duration || item.effectiveDuration || 0);
  const sourceOrdered = segments.every((segment, index) => !index || Number(segments[index - 1].start || 0) <= Number(segment.start || 0));
  const storyPath = [...new Set(segments.map((segment) => segment.storyFunction || segment.role || "精彩镜头"))];
  const review = version?.reviewReport || item.reviewReport || {};
  const quality = item.qualityReport || {};
  return {
    title: "为什么这样剪",
    summary: item.editorialNarrative || item.reason || `本版由 ${segments.length} 个不重复镜头组成，优先保证事件和表达完整。`,
    strategy: {
      name: item.displayName || version?.displayName || item.title || "高光成片",
      description: item.strategyDescription || version?.strategyDescription || "保留真实精彩内容",
    },
    intent: { focus: currentJob?.brief?.focus || [], include: currentJob?.brief?.includeRules || [], exclude: currentJob?.brief?.excludeRules || [] },
    selection: { eventCount: Number(item.eventCount || item.chapterCount || 0), shotCount: segments.length, eventTitles: [], reason: "优先保留与用户重点匹配、且可以形成完整表达的镜头。" },
    ordering: { label: sourceOrdered ? "按源视频时间顺序" : "按 AI 叙事顺序", reason: sourceOrdered ? "保持原视频的因果与时间关系。" : "依据事件职责和情绪递进重新排列。", storyPath },
    boundaries: { adjustmentCount: Number(item.boundaryAdjustments?.length || 0), reason: item.boundaryAdjustments?.length ? "已按完整对白、动作或自然停顿校正边界。" : "使用模型精修并经本地验证的自然边界。" },
    techniques: { summary: "根据镜头内容决定原速、硬切、转场和声音衔接；完整对白与高潮默认保持原速。" },
    duration: { targetSeconds: Number.isFinite(target) && target > 0 ? target : null, actualSeconds: actual, statusLabel: item.durationStatus === "under_target" ? "短于目标" : item.durationStatus === "over_target" ? "长于目标" : "已进入目标区间", reason: item.durationDeviationReason || "优先保证表达完整。" },
    omissions: item.eventReductionReason ? [item.eventReductionReason] : ["没有使用重复或低价值拖尾强行凑时长。"],
    quality: { score: review.overallScore ?? quality.score, summary: review.summary || (quality.passed === false ? "仍有需要复核的项目。" : "已通过剪辑时间线与渲染文件检查。"), recommended: Boolean(version?.recommended), recommendationReason: version?.recommendationReason || "" },
  };
}

function renderOutputEditingExplanation(item, version = null) {
  const root = $("#outputExplanation");
  if (!root) return;
  if (!item) {
    root.innerHTML = "";
    root.classList.add("hidden");
    return;
  }
  const explanation = item.editingExplanation || fallbackOutputEditingExplanation(item, version);
  const selection = explanation.selection || {};
  const ordering = explanation.ordering || {};
  const timing = explanation.duration || {};
  const boundaries = explanation.boundaries || {};
  const quality = explanation.quality || {};
  const intent = explanation.intent || {};
  const eventNames = (selection.eventTitles || []).filter(Boolean);
  const focus = (intent.focus || []).filter(Boolean);
  const requirements = [
    ...(intent.include || []).map((value) => `保留 ${value}`),
    ...(intent.exclude || []).map((value) => `排除 ${value}`),
  ];
  const qualityScore = Number(quality.score);
  const qualityLabel = Number.isFinite(qualityScore) ? `${Math.round(qualityScore)}/100` : "已检查";
  const targetLabel = timing.targetSeconds
    ? `${Number(timing.actualSeconds || 0).toFixed(1)} 秒 / 目标 ${Number(timing.targetSeconds).toFixed(1)} 秒`
    : `${Number(timing.actualSeconds || 0).toFixed(1)} 秒 / 自动时长`;
  const omissions = (explanation.omissions || []).filter(Boolean);
  root.innerHTML = `
    <header class="output-explanation-head">
      <div><small>AI EDIT DECISION</small><strong>${escapeHtml(explanation.title || "为什么这样剪")}</strong></div>
      <span>${quality.recommended ? "AI 推荐 · " : ""}依据可追溯</span>
    </header>
    <p class="output-explanation-summary">${escapeHtml(explanation.summary || "根据已验证的画面、声音和用户要求生成。")}</p>
    <div class="output-decision-ledger">
      <section><small>选片</small><strong>${Number(selection.eventCount || 0)} 个事件 · ${Number(selection.shotCount || 0)} 个镜头</strong><p>${escapeHtml(eventNames.length ? eventNames.slice(0, 3).join("、") : selection.reason || "保留高价值且不重复的镜头")}</p></section>
      <section><small>顺序</small><strong>${escapeHtml(ordering.label || "按当前剪辑顺序")}</strong><p>${escapeHtml((ordering.storyPath || []).length ? ordering.storyPath.join(" → ") : ordering.reason || "保持叙事关系")}</p></section>
      <section><small>时长</small><strong>${escapeHtml(targetLabel)}</strong><p>${escapeHtml(`${timing.statusLabel || "已校验"}。${timing.reason || "优先保证表达完整。"}`)}</p></section>
      <section><small>边界与手法</small><strong>${Number(boundaries.adjustmentCount || 0)} 处安全校正</strong><p>${escapeHtml(explanation.techniques?.summary || boundaries.reason || "使用自然切点")}</p></section>
    </div>
    ${(focus.length || requirements.length) ? `<div class="output-intent-line"><small>对应需求</small><span>${[...focus.map((value) => `重点 ${value}`), ...requirements].slice(0, 8).map((value) => `<b>${escapeHtml(value)}</b>`).join("")}</span></div>` : ""}
    <details class="output-explanation-audit">
      <summary><span>取舍与质检</span><b>${escapeHtml(qualityLabel)}</b><em>展开查看</em></summary>
      <div><p>${escapeHtml(quality.recommendationReason || quality.summary || "已完成成片检查。")}</p>${omissions.length ? `<ul>${omissions.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>` : ""}</div>
    </details>
    <p class="output-explanation-footnote">下方逐镜头列表会说明每段的职责与保留原因；点击镜头可直接定位成片，点击“源片段”可回看原视频。</p>`;
  root.classList.remove("hidden");
}

function renderClipEvidence(item, kind = "candidate", version = null) {
  const meta = $("#clipEvidenceMeta");
  const list = $("#clipEvidence");
  if (!meta || !list) return;
  renderOutputEditingExplanation(kind === "output" ? item : null, version);
  renderClipTranscript(item, kind);
  const evidence = item?.audioEvidence || {};
  const chips = [];
  if (kind !== "output") chips.push(`判断依据 ${(item?.evidence || []).length} 项`);
  if (evidence.transcriptExcerpt || evidence.speakerTurns?.length) chips.push("SenseVoice 已对齐");
  itemSpeakers(item).forEach((speaker) => chips.push(`说话人 ${speaker}`));
  (evidence.emotions || []).slice(0, 2).forEach((emotion) => chips.push(`情绪 ${emotion}`));
  (evidence.audioEvents || []).slice(0, 2).forEach((event) => chips.push(`声音 ${event}`));
  if (kind === "candidate" || kind === "event" || kind === "segment") chips.push("尚未写入成片");
  if (kind === "output" && version) chips.push(`版本 V${Number(version.number || 1)}`);
  if (kind === "output" && item?.sourceDuration) chips.push(`源片段 ${Number(item.sourceDuration).toFixed(1)} 秒 → 成片 ${Number(item.effectiveDuration || item.duration || 0).toFixed(1)} 秒`);
  if (kind === "output" && item?.cutaways?.length) chips.push(`插入镜头 ${item.cutaways.length} 个`);
  meta.innerHTML = chips.map((chip) => `<span>${escapeHtml(chip)}</span>`).join("");
  if ((kind === "event" || kind === "output") && item.segments?.length) {
    const timePrefix = kind === "output" ? "成片 " : "组合 ";
    const schedule = compositionSchedule(item);
    list.innerHTML = schedule.map((entry, index) => {
      const segment = entry.segment;
      const sourceRange = `${formatTime(entry.sourceStart)} → ${formatTime(entry.sourceEnd)}`;
      const rate = Number(segment.playbackRate || 1);
      const transition = segment.transitionIn?.type === "fade_black" ? "淡黑" : segment.transitionIn?.type === "dissolve" ? "叠化" : "硬切";
      const bridge = segment.audioBridge?.type === "j_cut" ? "J-cut" : segment.audioBridge?.type === "l_cut" ? "L-cut" : "同步音画";
      return `<li class="evidence-item-row"><button type="button" class="evidence-main-button" data-composed-segment="${index}" data-composed-source-time="${entry.sourceStart}"><span class="evidence-item-index">${String(index + 1).padStart(2, "0")}</span><span class="evidence-item-content"><strong>${escapeHtml(segment.storyFunction || segment.role || "精彩镜头")}</strong><small>${timePrefix}${formatTime(entry.outputStart)} → ${formatTime(entry.outputEnd)} · ${rate.toFixed(rate === 1 ? 0 : 2)}× · ${transition} · ${bridge}</small>${segment.reason ? `<em>${escapeHtml(segment.reason)}</em>` : ""}</span></button><button type="button" class="clip-source-link" data-source-segment="${index}" data-source-time="${entry.sourceStart}" title="在源视频中查看 ${sourceRange}" aria-label="在源视频中查看${escapeHtml(segment.role || `镜头 ${index + 1}`)}">源片段</button></li>`;
    }).join("");
  } else {
    list.innerHTML = (item?.evidence || []).map((text, index) => `<li><button type="button" class="evidence-main-button" data-evidence-seek="${Number(item.start) || 0}"><small class="evidence-source-label">画面证据 ${String(index + 1).padStart(2, "0")}</small><span class="evidence-item-copy">${escapeHtml(text)}</span></button></li>`).join("");
  }
  list?.querySelectorAll("[data-evidence-seek]").forEach((button) => button.addEventListener("click", () => seekTimeline(Number(button.dataset.evidenceSeek))));
  list?.querySelectorAll("[data-composed-segment]").forEach((button) => button.addEventListener("click", () => {
    seekComposedMedia(item, Number(button.dataset.composedSegment), Number(button.dataset.composedSourceTime), kind);
  }));
  list?.querySelectorAll("[data-source-segment]").forEach((button) => button.addEventListener("click", () => {
    previewCompositionSourceSegment(item, Number(button.dataset.sourceSegment), Number(button.dataset.sourceTime));
  }));
}

async function downloadVideoAsset(url, filename) {
  if (fragmentDownloadBusy) return;
  fragmentDownloadBusy = true;
  const button = $("#keepButton");
  const previousLabel = button?.textContent || "下载该片段";
  if (button) button.textContent = "正在准备下载…";
  try {
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) throw new Error(`片段下载失败（${response.status}）`);
    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = filename || "高光片段.mp4";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  } catch (error) {
    window.alert(error.message || "片段下载失败");
  } finally {
    fragmentDownloadBusy = false;
    if (button) button.textContent = (currentCandidate || currentEventSegment || currentEventGroup) ? "下载该片段" : previousLabel;
  }
}

function downloadCurrentFragment() {
  if (!currentJob) return;
  if (currentEventGroup && !currentEventSegment) {
    const title = currentEventGroup.title || "事件高光";
    return downloadVideoAsset(
      `/api/jobs/${currentJob.id}/event-groups/${encodeURIComponent(currentEventGroup.id)}/preview?download=1`,
      `${title}.mp4`,
    );
  }
  const item = currentEventSegment || currentCandidate;
  if (!item) return;
  const start = Number(item.start);
  const end = Number(item.end);
  const title = currentEventSegment
    ? `${currentEventGroup?.title || "事件"}-${item.role || "精彩镜头"}`
    : (item.title || "高光片段");
  const url = `/api/jobs/${currentJob.id}/fragment?start=${encodeURIComponent(start.toFixed(3))}&end=${encodeURIComponent(end.toFixed(3))}&title=${encodeURIComponent(title)}`;
  downloadVideoAsset(url, `${title}.mp4`);
}

function oneOffOutputEntries(job = currentJob) {
  return orderedJobOutputs(job).map(({ item, version }, index) => {
    const presentation = autoVersionPresentation(job, version);
    const previewOnly = Boolean(item.previewOnly || version.previewOnly);
    return {
      item,
      version,
      previewOnly,
      label: item.displayTitle || presentation.displayName || item.title || `成片 ${index + 1}`,
    };
  });
}

function syncOneOffFinalizeAction(job = currentJob) {
  const button = $("#finalizeOneOffButton");
  if (!button) return;
  const entries = job ? oneOffOutputEntries(job) : [];
  const visible = job?.storageMode === "one_off" && entries.length > 0 && !isActiveJobStatus(job.status);
  button.classList.toggle("hidden", !visible);
  if (visible) {
    const formalCount = entries.filter((entry) => !entry.previewOnly).length;
    button.textContent = formalCount ? "保存成片并清理素材" : "成片需先导出高清";
    button.title = formalCount ? "选择要保存的正式成片，然后清理一次性工程" : "审核样片不能作为最终文件，请先导出高清成片";
    button.onclick = finalizeOneOffTask;
  } else {
    button.onclick = null;
  }
}

async function finalizeOneOffTask() {
  if (!currentJob || currentJob.storageMode !== "one_off" || actionBusy) return;
  const entries = oneOffOutputEntries();
  if (!entries.length) return void showToast("当前还没有可保留的成片");
  const currentFilename = String(currentOutput?.filename || "");
  const formalEntries = entries.filter((entry) => !entry.previewOnly);
  const defaultFilename = formalEntries.some((entry) => entry.item.filename === currentFilename)
    ? currentFilename
    : String(formalEntries[0]?.item.filename || "");
  const confirmation = await requestActionConfirmation({
    title: "保存正式成片并清理一次性任务",
    summary: "勾选要保存的高清 MP4。成片副本保存成功后，源视频、时间线、分析结果和其他输出将被删除。",
    details: ["保存的 MP4 不依赖原工程", "字幕草稿不会单独保存", "清理后任务无法继续编辑"],
    warning: formalEntries.length ? "这是不可恢复的工程清理操作。" : "当前只有审核样片，请先导出高清成片。",
    confirmLabel: "保存并清理",
    selectionItems: entries.map((entry) => ({
      value: entry.item.filename,
      label: entry.label,
      meta: entry.previewOnly
        ? "审核样片不可保留 · 请先选择该版本并导出高清成片"
        : `${Number(entry.item.duration || 0).toFixed(1)} 秒 · 高清 MP4`,
      disabled: entry.previewOnly,
      checked: entry.item.filename === defaultFilename,
    })),
  });
  if (!confirmation?.confirmed || !confirmation.selectedValues?.length) return;
  const jobId = String(currentJob.id);
  actionBusy = true;
  syncOneOffFinalizeAction();
  try {
    const result = await api(`/api/jobs/${encodeURIComponent(jobId)}/finalize-one-off`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filenames: confirmation.selectedValues }),
    });
    resetWorkspace();
    await loadHomeTasks();
    showToast(`已保存 ${result.keptOutputs?.length || confirmation.selectedValues.length} 条正式成片，并清理一次性工程`, "success");
  } catch (error) {
    window.alert(error.message || "一次性任务清理失败");
  } finally {
    actionBusy = false;
    syncOneOffFinalizeAction();
  }
}

function selectOutput(filename, autoplay = false, seekTime = null) {
  if (!currentJob) return;
  const located = locateJobOutput(filename);
  if (!located) return;
  const { output, version } = located;
  candidatePreviewToken += 1;
  currentOutput = output;
  currentCandidate = null;
  currentEventGroup = null;
  currentEventSegment = null;
  candidatePreviewEnd = null;
  viewerMediaKind = "output";
  timelineCoordinateSpace = "output";
  timelineViewStart = 0;
  timelineViewEnd = timelineOutputDurationValue(output);
  timelineReviewFollow = false;
  timelineMediaRenderKey = "";
  waveformRenderKey = "";
  stopSourcePreviewPolling();
  const cacheKey = encodeURIComponent(output.versionCreatedAt || version.createdAt || output.filename || "output");
  clearPlayerNotice();
  applyMediaAspect(viewerShell, currentJob.videoInfo?.width, currentJob.videoInfo?.height);
  const outputUrl = String(output.previewUrl || output.videoUrl || "").trim();
  if (!outputUrl || outputUrl === "undefined" || outputUrl === "null") {
    setMainVideoSource("");
    showPlayerNotice("当前成片暂时没有可用的预览地址");
  } else {
    const separator = outputUrl.includes("?") ? "&" : "?";
    setMainVideoSource(`${outputUrl}${separator}v=${cacheKey}`);
  }
  const outputNumber = orderedJobOutputs(currentJob).findIndex(({ item }) => item.filename === filename) + 1;
  const presentation = autoVersionPresentation(currentJob, version);
  const displayTitle = output.displayTitle || (currentJob.autoComposition?.status === "completed" && presentation.displayName
    ? `${presentation.displayName} · ${presentation.sourceLabel || "AI"}`
    : output.title);
  const contentMode = taskModePresentation(currentJob).key === "content_extract";
  $("#viewerBadge").textContent = contentMode ? (outputNumber > 0 ? `内容视频 ${outputNumber}` : "内容视频") : (outputNumber > 0 ? `成片 ${outputNumber}` : "成片");
  renderOutputPreviewSelector(currentJob);
  $("#reviewKicker").textContent = contentMode ? "CONTENT PREVIEW" : "HIGHLIGHT PREVIEW";
  $("#reviewTitle").textContent = displayTitle;
  const download = $("#downloadButton");
  const previewOnly = Boolean(output.previewOnly || version.previewOnly);
  download.href = output.downloadUrl;
  download.classList.remove("hidden");
  download.textContent = previewOnly ? "下载审核样片" : "下载高清 MP4";
  download.title = previewOnly ? "直接下载当前低分辨率审核样片" : "下载当前版本的高清成片";
  const finalize = $("#finalizePreviewButton");
  finalize?.classList.toggle("hidden", !previewOnly);
  if (finalize) {
    finalize.onclick = () => finalizePreviewVersion(version, output);
    finalize.textContent = "导出高清成片";
  }
  syncOneOffFinalizeAction(currentJob);
  const subtitle = $("#subtitleButton");
  subtitle.dataset.subtitleUrl = `/api/jobs/${currentJob.id}/outputs/${encodeURIComponent(output.filename)}/subtitles?format=srt`;
  // Keep the subtitle download independent from the MP4 link.  Some browsers
  // reuse the previous attachment name when an anchor is updated in place;
  // setting an explicit .srt filename makes the downloaded file unambiguous.
  subtitle.dataset.downloadName = `${String(output.downloadFilename || output.filename).replace(/\.[^.]+$/, "")}.srt`;
  subtitle.onclick = async (event) => {
    event.preventDefault();
    if (subtitle.dataset.downloading === "true") return;
    subtitle.dataset.downloading = "true";
    const originalLabel = subtitle.textContent;
    subtitle.textContent = "正在准备 SRT…";
    try {
      const response = await fetch(subtitle.dataset.subtitleUrl, { credentials: "same-origin" });
      if (!response.ok) throw new Error(`字幕下载失败（${response.status}）`);
      const content = await response.text();
      const blob = new Blob([content], { type: "application/x-subrip;charset=utf-8" });
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = subtitle.dataset.downloadName || "subtitles.srt";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
    } catch (error) {
      window.alert(error.message || "字幕下载失败");
    } finally {
      subtitle.dataset.downloading = "false";
      subtitle.textContent = originalLabel;
    }
  };
  // 字幕下载暂时不在界面展示，保留生成逻辑以便后续重新启用。
  subtitle.classList.add("hidden");
  subtitle.textContent = "下载字幕 SRT";
  $("#evidencePanel")?.classList.remove("hidden");
  $("#evidencePanel")?.classList.remove("evidence-placeholder");
  $("#evidencePanel")?.classList.remove("candidate-mode");
  $("#evidencePanel")?.classList.toggle("montage-mode", Boolean(output.segments?.length));
  $("#evidencePanel")?.classList.add("output-mode");
  $("#clipTime").textContent = output.segments?.length
    ? `${output.segments.length} 个${contentMode ? "内容片段" : "镜头"} · ${contentMode ? "视频" : "成片"} ${Number(output.duration).toFixed(1)} 秒`
    : `${formatTime(output.start)} → ${formatTime(output.end)} · ${Number(output.duration).toFixed(1)} 秒`;
  $("#clipTitle").textContent = output.segments?.length ? (contentMode ? "内容视频结构" : "成片结构") : displayTitle;
  const qualityScore = Number(
    version?.reviewReport?.overallScore
      ?? output.reviewReport?.overallScore
      ?? output.qualityReport?.score
      ?? output.score,
  );
  $("#clipScore").textContent = Number.isFinite(qualityScore) ? `${Math.round(qualityScore)}/100` : "已质检";
  $("#clipReason").textContent = output.reason;
  renderClipEvidence(output, "output", version);
  // Versioning and archival are separate concepts.  A rendered output is
  // already part of V1/V2; this button only creates/removes an extra copy.
  // The legacy keep-library action was removed from the UI. Downloads remain
  // available through the dedicated MP4 button.
  $("#keepButton")?.classList.add("hidden");
  $("#replaceButton")?.classList.add("hidden");
  $("#replaceButton").disabled = false;
  $("#replaceButton").title = "";
  document.querySelectorAll(".clip-card").forEach((card) => card.classList.toggle("active", card.dataset.filename === filename));
  const selectedAutoVersion = [...document.querySelectorAll(".auto-version-button")]
    .find((button) => button.dataset.autoOutput === filename) || null;
  document.querySelectorAll(".auto-version-button").forEach((button) => button.classList.toggle("active", button === selectedAutoVersion));
  setOutputVersionBeamSelection(selectedAutoVersion);
  timelineViewport?.classList.remove("output-version-switching");
  if (timelineViewport) {
    // Restart a short, low-amplitude transition so a version switch is
    // perceptible without changing the user's zoom window.
    void timelineViewport.offsetWidth;
    timelineViewport.classList.add("output-version-switching");
    window.setTimeout(() => timelineViewport?.classList.remove("output-version-switching"), 220);
  }
  updateTimeline();
  syncReviewSelectionClasses();
  if (seekTime !== null && Number.isFinite(Number(seekTime))) seekCurrentMediaTime(Number(seekTime), { autoplay });
  else if (autoplay) safePlay();
}

async function finalizePreviewVersion(version, output = null) {
  if (!currentJob || !version?.id || actionBusy) return;
  const subtitleMode = $("#subtitleMode")?.value || (output?.subtitleMode === "burn" ? "burn" : "none");
  const subtitleStyle = $("#subtitleStyle")?.value || output?.subtitleStyle || "clean";
  if (!await requestActionConfirmation({ title: "导出当前版本的高清成片", summary: "将锁定当前样片的镜头、顺序、变速、转场和声音衔接，并按源分辨率重新渲染。", details: ["仍属于当前版本，不会新增“当前时间轴版本”", "审核样片仍可保留和下载", "不会重新调用 VLM 或 LLM"] })) return;
  let subtitleDraftId = null;
  if (subtitleMode === "burn") {
    if (!output?.segments?.length) return void showToast("当前样片缺少可校对的时间线");
    const draft = await reviewSubtitlesBeforeRender([{ segments: output.segments }], subtitleStyle);
    if (!draft) return;
    subtitleDraftId = draft.id;
  }
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/output-versions/${encodeURIComponent(version.id)}/finalize`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ subtitleMode, subtitleStyle, subtitleDraftId }),
    });
    if (!commitJobAction(job, actionToken)) return;
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

function previewCandidate(index, { showEvidence = true } = {}) {
  if (!currentJob || !["awaiting_confirmation", "completed"].includes(currentJob.status)) return;
  const candidate = currentJob.candidates?.find((item) => item.index === index);
  if (!candidate) return;
  const previewToken = ++candidatePreviewToken;
  sourcePreviewRetryToken = 0;
  const needsSource = viewerMediaKind === "output" || !mainVideo.getAttribute("src");
  currentOutput = null;
  currentCandidate = candidate;
  currentEventGroup = null;
  currentEventSegment = null;
  candidatePreviewEnd = Number(candidate.end);
  viewerMediaKind = "candidate";
  clearOutputVersionSelectionState();
  beginSourcePreviewPolling();
  $("#viewerBadge").textContent = `候选 ${index + 1}`;
  $("#reviewKicker").textContent = "CANDIDATE PREVIEW";
  $("#reviewTitle").textContent = candidate.title;
  $("#downloadButton")?.classList.add("hidden");
  $("#finalizePreviewButton")?.classList.add("hidden");
  syncOneOffFinalizeAction(currentJob);
  $("#subtitleButton")?.classList.add("hidden");
  if (showEvidence) {
    $("#evidencePanel")?.classList.remove("hidden", "evidence-placeholder");
    $("#evidencePanel")?.classList.add("candidate-mode");
    $("#evidencePanel")?.classList.remove("montage-mode", "output-mode");
    $("#addToChatButton")?.classList.add("hidden");
    $("#clipTime").textContent = `${formatTime(candidate.start)} → ${formatTime(candidate.end)} · ${Number(candidate.duration).toFixed(1)} 秒`;
    $("#clipTitle").textContent = candidate.title;
    $("#clipScore").textContent = `${Math.round(candidate.score)}/100`;
    $("#clipReason").textContent = candidate.reason;
    $("#keepButton")?.classList.remove("hidden");
    $("#keepButton").textContent = "下载该片段";
    $("#replaceButton")?.classList.remove("hidden");
    $("#replaceButton").textContent = "删除片段";
    renderClipEvidence(candidate, "candidate");
  }
  document.querySelectorAll(".candidate-row").forEach((row) => row.classList.toggle("previewing", Number(row.dataset.candidateRow) === index));
  const playRange = () => {
    if (previewToken !== candidatePreviewToken) return;
    const start = Math.max(0, Number(candidate.start));
    mainVideo.pause();
    $("#viewerBadge").textContent = `候选 ${index + 1} · 正在定位`;
    const playAfterSeek = () => {
      if (previewToken !== candidatePreviewToken) return;
      $("#viewerBadge").textContent = `候选 ${index + 1}`;
      safePlay();
    };
    mainVideo.addEventListener("seeked", playAfterSeek, { once: true });
    mainVideo.currentTime = Math.min(Math.max(0, mainVideo.duration - 0.05), start);
    if (Math.abs(mainVideo.currentTime - start) < 0.04) {
      mainVideo.removeEventListener("seeked", playAfterSeek);
      playAfterSeek();
    }
  };
  if (needsSource) {
    clearPlayerNotice();
    setMainVideoSource(sourcePreviewUrl());
    beginSourcePreviewPolling();
    mainVideo.addEventListener("loadedmetadata", playRange, { once: true });
  } else if (mainVideo.readyState >= 1) {
    playRange();
  } else {
    mainVideo.addEventListener("loadedmetadata", playRange, { once: true });
  }
  refreshTimelineAfterReviewSelection();
  syncReviewSelectionClasses();
}

function previewEventGroup(group, { seekTime = null, autoplay = true } = {}) {
  if (!currentJob || !group) return;
  candidatePreviewToken += 1;
  currentOutput = null;
  currentCandidate = null;
  currentEventSegment = null;
  currentEventGroup = group;
  candidatePreviewEnd = null;
  viewerMediaKind = "event";
  clearOutputVersionSelectionState();
  stopSourcePreviewPolling();
  clearPlayerNotice();
  setMainVideoSource(`/api/jobs/${currentJob.id}/event-groups/${encodeURIComponent(group.id)}/preview?v=${encodeURIComponent(group.updatedAt || group.id)}`);
  $("#viewerBadge").textContent = `事件组合 · ${group.segments.length} 个镜头`;
  $("#reviewKicker").textContent = "COMPOSED EVENT PREVIEW";
  $("#reviewTitle").textContent = group.title;
  $("#downloadButton")?.classList.add("hidden");
  $("#finalizePreviewButton")?.classList.add("hidden");
  $("#evidencePanel")?.classList.remove("hidden");
  $("#evidencePanel")?.classList.remove("evidence-placeholder");
  $("#evidencePanel")?.classList.add("candidate-mode");
  $("#evidencePanel")?.classList.remove("montage-mode");
  $("#evidencePanel")?.classList.remove("output-mode");
  $("#addToChatButton")?.classList.add("hidden");
  $("#clipTime").textContent = `${group.segments.length} 个镜头 · ${Number(group.actualDuration).toFixed(1)} 秒`;
  $("#clipTitle").textContent = group.title;
  $("#clipScore").textContent = `${Math.round(group.score)}/100`;
  $("#clipReason").textContent = group.summary;
  $("#keepButton")?.classList.remove("hidden");
  $("#keepButton").textContent = "下载该片段";
  $("#replaceButton")?.classList.add("hidden");
  renderClipEvidence(group, "event");
  refreshTimelineAfterReviewSelection();
  syncReviewSelectionClasses();
  if (seekTime !== null && Number.isFinite(Number(seekTime))) seekCurrentMediaTime(Number(seekTime), { autoplay });
  else if (autoplay) safePlay();
}

function previewEventSegment(group, segment, { seekTime = null } = {}) {
  if (!currentJob || !segment) return;
  const contentMode = String(currentJob.taskMode || "") === "content_extract";
  sourcePreviewRetryToken = 0;
  currentEventGroup = group;
  currentEventSegment = segment;
  currentCandidate = null;
  currentOutput = null;
  clearOutputVersionSelectionState();
  viewerMediaKind = "segment";
  beginSourcePreviewPolling();
  candidatePreviewEnd = Number(segment.end);
  const target = Number.isFinite(Number(seekTime)) ? Number(seekTime) : Number(segment.start);
  if (!mainVideo.src.includes(`/api/jobs/${currentJob.id}/preview`)) {
    clearPlayerNotice();
    setMainVideoSource(sourcePreviewUrl());
    beginSourcePreviewPolling();
  }
  seekCurrentMediaTime(Math.max(Number(segment.start) || 0, Math.min(Number(segment.end) || target, target)));
  const groupTitle = group?.title || segment.chapterTitle || "成片镜头";
  $("#viewerBadge").textContent = `${groupTitle} · 源片段`;
  $("#reviewKicker").textContent = contentMode ? "CONTENT SOURCE MATCH" : "SOURCE EVENT SHOT";
  $("#reviewTitle").textContent = contentMode ? groupTitle : segment.role || segment.title || "源片段";
  $("#evidencePanel")?.classList.remove("hidden");
  $("#evidencePanel")?.classList.remove("evidence-placeholder");
  $("#evidencePanel")?.classList.add("candidate-mode");
  $("#evidencePanel")?.classList.remove("montage-mode", "output-mode");
  $("#addToChatButton")?.classList.add("hidden");
  $("#finalizePreviewButton")?.classList.add("hidden");
  const segmentDuration = Math.max(0, Number(segment.duration) || Number(segment.end) - Number(segment.start));
  $("#clipTime").textContent = `源视频 ${formatTime(segment.start)} → ${formatTime(segment.end)} · ${segmentDuration.toFixed(1)} 秒`;
  $("#clipTitle").textContent = contentMode ? groupTitle : segment.role || segment.title || "源片段";
  $("#clipScore").textContent = `${Math.round(segment.score || 0)}/100`;
  $("#clipReason").textContent = segment.reason || (contentMode ? "当前内容视频采用的源片段" : "事件组中的精彩镜头");
  $("#keepButton")?.classList.remove("hidden");
  $("#keepButton").textContent = "下载该片段";
  $("#replaceButton")?.classList.toggle("hidden", !group || contentMode);
  $("#replaceButton").textContent = "删除片段";
  renderClipEvidence(segment, "segment");
  refreshTimelineAfterReviewSelection();
  syncReviewSelectionClasses();
}

async function renameEventGroup(group) {
  const title = window.prompt("输入事件高光名称", group.title || "");
  if (!title?.trim() || title.trim() === group.title) return;
  const actionToken = captureJobAction();
  if (!jobActionStillCurrent(actionToken)) return;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/event-groups/${encodeURIComponent(group.id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim() }),
    });
    commitJobAction(job, actionToken);
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
}

async function addSelectionToEventGroup(group) {
  const selection = currentJob?.manualSelection;
  if (!selection) return void window.alert("请先在源视频时间轴上拖动选择一个范围");
  const actionToken = captureJobAction();
  if (!jobActionStillCurrent(actionToken)) return;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/event-groups/${encodeURIComponent(group.id)}/segments`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start: selection.start, end: selection.end, role: selection.title || "用户补充镜头" }),
    });
    if (!jobActionStillCurrent(actionToken)) return;
    currentEventGroup = group;
    commitJobAction(job, actionToken);
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
}

async function createEventFromSelection() {
  const selection = currentJob?.manualSelection;
  if (!selection) return void window.alert("请先在源视频时间轴上拖动选择一个范围");
  const title = window.prompt("输入新事件名称", selection.title || "手动事件高光");
  if (!title?.trim()) return;
  const actionToken = captureJobAction();
  if (!jobActionStillCurrent(actionToken)) return;
  try {
    const { job, groupId } = await api(`/api/jobs/${actionToken.jobId}/event-groups`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start: selection.start, end: selection.end, title: title.trim() }),
    });
    if (!jobActionStillCurrent(actionToken)) return;
    currentEventGroup = job.eventGroups.find((item) => item.id === groupId) || null;
    commitJobAction(job, actionToken);
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
}

async function deleteEventSegment(group, segment) {
  if (!window.confirm(`从“${group.title}”删除镜头“${segment.role}”？`)) return;
  const actionToken = captureJobAction();
  if (!jobActionStillCurrent(actionToken)) return;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/event-groups/${encodeURIComponent(group.id)}/segments/${encodeURIComponent(segment.id)}`, { method: "DELETE" });
    if (!jobActionStillCurrent(actionToken)) return;
    currentEventSegment = null;
    commitJobAction(job, actionToken);
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
}

async function deleteTimelineItem() {
  if (!currentJob || actionBusy) return;
  if (currentEventGroup && currentEventSegment) {
    return deleteEventSegment(currentEventGroup, currentEventSegment);
  }
  if (!currentCandidate) return;
  if (!window.confirm(`删除“${currentCandidate.title}”？对应时间轴片段、缩略图和波形标记会一起移除。`)) return;
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const excluded = new Set(locallyExcludedCandidates);
    excluded.add(Number(currentCandidate.index));
    const { job } = await api(`/api/jobs/${actionToken.jobId}/review-exclusions`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ indices: [...excluded] }),
    });
    if (!jobActionStillCurrent(actionToken)) return;
    locallyExcludedCandidates = excluded;
    currentCandidate = null;
    currentEventSegment = null;
    commitJobAction(job, actionToken);
    showSource();
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

async function reorderEventSegment(group, from, to) {
  if (to < 0 || to >= group.segments.length) return;
  const ids = group.segments.map((item) => item.id);
  const [moved] = ids.splice(from, 1);
  ids.splice(to, 0, moved);
  const actionToken = captureJobAction();
  if (!jobActionStillCurrent(actionToken)) return;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/event-groups/${encodeURIComponent(group.id)}/segments/reorder`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ segmentIds: ids }),
    });
    commitJobAction(job, actionToken);
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
}

async function moveEventSegment(group, segment) {
  const destinations = currentJob.eventGroups.filter((item) => item.id !== group.id);
  if (!destinations.length) return void window.alert("当前没有其他事件组");
  const listing = destinations.map((item, index) => `${index + 1}. ${item.title}`).join("\n");
  const choice = Number(window.prompt(`移动到哪个事件？\n${listing}`, "1"));
  if (!Number.isInteger(choice) || choice < 1 || choice > destinations.length) return;
  const actionToken = captureJobAction();
  if (!jobActionStillCurrent(actionToken)) return;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/event-groups/${encodeURIComponent(group.id)}/segments/${encodeURIComponent(segment.id)}/move`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ destinationGroupId: destinations[choice - 1].id }),
    });
    if (!jobActionStillCurrent(actionToken)) return;
    currentEventGroup = destinations[choice - 1];
    currentEventSegment = null;
    commitJobAction(job, actionToken);
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
}

function refreshAdjustedCandidate(lightweight = false) {
  if (!currentCandidate) return;
  currentCandidate.duration = Math.max(0, Number(currentCandidate.end) - Number(currentCandidate.start));
  candidatePreviewEnd = Number(currentCandidate.end);
  const row = document.querySelector(`[data-candidate-row="${currentCandidate.index}"]`);
  if (row) {
    const detail = row.querySelector("small");
    if (detail) detail.textContent = `${formatTime(currentCandidate.start)} → ${formatTime(currentCandidate.end)} · ${Number(currentCandidate.duration).toFixed(1)} 秒`;
  }
  $("#clipTime").textContent = `${formatTime(currentCandidate.start)} → ${formatTime(currentCandidate.end)} · ${Number(currentCandidate.duration).toFixed(1)} 秒`;
  if (lightweight) updateTimelineSelection();
  else updateTimeline();
}

function refreshEventSegment(lightweight = false) {
  if (!currentEventSegment) return;
  currentEventSegment.duration = Math.max(0, Number(currentEventSegment.end) - Number(currentEventSegment.start));
  candidatePreviewEnd = Number(currentEventSegment.end);
  $("#clipTime").textContent = `${formatTime(currentEventSegment.start)} → ${formatTime(currentEventSegment.end)} · ${Number(currentEventSegment.duration).toFixed(1)} 秒`;
  if (lightweight) updateTimelineSelection();
  else updateTimeline();
}

function refreshManualSelection(lightweight = false) {
  const selection = currentJob?.manualSelection;
  if (!selection) return;
  selection.duration = Math.max(0, Number(selection.end) - Number(selection.start));
  candidatePreviewEnd = null;
  const name = selection.title ? `${selection.title} · ` : "";
  $("#viewerBadge").textContent = `${selection.title || "手动选区"} · ${Number(selection.duration).toFixed(1)} 秒`;
  $("#timelineHint").textContent = `${name}${formatTime(selection.start)} → ${formatTime(selection.end)}；可在对话中命名或处理`;
  if (lightweight) updateTimelineSelection();
  else updateTimeline();
}

function fillChatWithTimelineSelection(selection = currentJob?.manualSelection) {
  if (!selection || !chatInput) return;
  const selections = timelineChatSelections.length ? timelineChatSelections : [selection];
  const ranges = selections.map((item) => `${formatTime(Number(item.start) || 0)} → ${formatTime(Number(item.end) || 0)}`).join("、");
  chatInput.value = `合成时间轴选中的 ${selections.length} 个片段（${ranges}）`;
  chatInput.dataset.timelineCompose = "true";
  const composeButton = $("#chatComposeButton");
  if (composeButton) composeButton.textContent = `✦ 合成已选 ${selections.length} 段`;
  chatInput.dispatchEvent(new Event("input", { bubbles: true }));
  chatInput.focus();
}

async function selectTimelineItemForChat(item) {
  if (!currentJob || !["awaiting_confirmation", "completed"].includes(currentJob.status) || !item) return;
  const actionToken = captureJobAction();
  if (currentJob.status === "completed") {
    if (actionBusy) return;
    actionBusy = true;
    try {
      const { job } = await api(`/api/jobs/${actionToken.jobId}/reedit`, { method: "POST" });
      if (!jobActionStillCurrent(actionToken)) return;
      currentOutput = null;
      commitJobAction(job, actionToken);
    } catch (error) {
      if (jobActionStillCurrent(actionToken)) window.alert(error.message);
      return;
    } finally {
      if (jobActionStillCurrent(actionToken)) actionBusy = false;
    }
  }
  const start = Number(item.start);
  const end = Number(item.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end - start < 1) return;
  try {
    const result = await api(`/api/jobs/${actionToken.jobId}/selection`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start, end }),
    });
    if (!jobActionStillCurrent(actionToken)) return;
    currentJob.manualSelection = result.selection;
    timelineChatSelections = [...timelineChatSelections.filter((entry) => Math.abs(Number(entry.start) - start) > .05 || Math.abs(Number(entry.end) - end) > .05), result.selection];
    fillChatWithTimelineSelection(result.selection);
    refreshManualSelection(true);
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) console.warn("无法保存时间轴选区", error);
  }
}

function snapTimelineBoundary(value) {
  const rms = waveformData?.rms || [];
  const duration = timelineDurationValue();
  if (!timelineSnapEnabled || !waveformData?.hasAudio || !rms.length || duration <= 0) return value;
  const silencePoints = (waveformData.silences || []).map((item) => (Number(item.start) + Number(item.end)) / 2);
  const nearbySilence = silencePoints
    .map((time) => ({ time, distance: Math.abs(time - value) }))
    .filter((item) => item.distance <= 2.0)
    .sort((left, right) => left.distance - right.distance)[0];
  if (nearbySilence) return Math.round(nearbySilence.time * 1000) / 1000;
  const centerIndex = Math.round(Number(value) / duration * (rms.length - 1));
  const radius = Math.max(2, Math.round(2 / duration * rms.length));
  const local = rms.slice(Math.max(0, centerIndex - radius), Math.min(rms.length, centerIndex + radius + 1));
  const sorted = [...local].sort((left, right) => left - right);
  const threshold = Math.max(0.006, Number(sorted[Math.floor(sorted.length * 0.3)] || 0));
  let bestIndex = centerIndex;
  let bestCost = Infinity;
  for (let index = Math.max(0, centerIndex - radius); index <= Math.min(rms.length - 1, centerIndex + radius); index += 1) {
    const level = Number(rms[index]) || 0;
    if (level > threshold * 1.35) continue;
    const time = index / Math.max(1, rms.length - 1) * duration;
    const cost = Math.abs(time - value) + level / Math.max(threshold, .001) * .08;
    if (cost < bestCost) {
      bestCost = cost;
      bestIndex = index;
    }
  }
  return Math.round(bestIndex / Math.max(1, rms.length - 1) * duration * 1000) / 1000;
}

function moveBoundary(event) {
  if (!boundaryDrag) return;
  const target = boundaryDrag.target;
  const duration = timelineDurationValue();
  const value = timelineTimeFromPointer(event);
  if (boundaryDrag.boundary === "start") target.start = Math.min(Number(target.end) - 1, value);
  else target.end = Math.max(Number(target.start) + 1, value);
  target.start = Math.round(Math.max(0, target.start) * 20) / 20;
  target.end = Math.round(Math.min(duration, target.end) * 20) / 20;
  refreshManualSelection(true);
}

function finishBoundaryDrag() {
  if (!boundaryDrag || !currentJob) return;
  const drag = boundaryDrag;
  const target = drag.target;
  boundaryDrag = null;
  document.removeEventListener("pointermove", moveBoundary);
  document.removeEventListener("pointerup", finishBoundaryDrag);
  if (!pendingTimelineSelection) {
    Object.assign(target, drag.original);
    refreshManualSelection();
    return;
  }
  const snapped = snapTimelineBoundary(Number(target[drag.boundary]));
  if (drag.boundary === "start") target.start = Math.min(Number(target.end) - 1, snapped);
  else target.end = Math.max(Number(target.start) + 1, snapped);
  pendingTimelineSelection = { start: Number(target.start), end: Number(target.end), duration: Number(target.end) - Number(target.start) };
  refreshManualSelection();
  $("#timelineHint").textContent = "手动选区已微调，请确认后再保存或合成";
}

function beginBoundaryDrag(event, boundary) {
  // Existing AI candidates and event segments are review-only on the
  // timeline. Boundary handles are reserved for a new manual range before
  // the user confirms it.
  if (!pendingTimelineSelection || !currentJob?.manualSelection || !["awaiting_confirmation", "completed"].includes(currentJob.status)) return;
  const target = currentJob.manualSelection;
  event.preventDefault();
  event.stopPropagation();
  boundaryDrag = {
    boundary,
    target,
    kind: "manual",
    original: { start: Number(target.start), end: Number(target.end), duration: Number(target.duration) },
  };
  document.addEventListener("pointermove", moveBoundary);
  document.addEventListener("pointerup", finishBoundaryDrag, { once: true });
}

function timelineTimeFromPointer(event) {
  const trackContent = timelineTrackContent || timelineViewport;
  const bounds = trackContent.getBoundingClientRect();
  const view = timelineViewRange();
  return Math.max(0, Math.min(
    timelineDurationValue(),
    view.start + (event.clientX - bounds.left) / Math.max(1, bounds.width) * view.duration,
  ));
}

function activateTimelinePoint(event) {
  const time = timelineTimeFromPointer(event);
  const trackContent = timelineTrackContent || timelineViewport;
  const bounds = trackContent?.getBoundingClientRect();
  const timelineStyle = timelineViewport ? getComputedStyle(timelineViewport) : null;
  const audioTop = Number.parseFloat(timelineStyle?.getPropertyValue("--timeline-audio-track-top") || "") || Math.max(0, Number(bounds?.height || 0) * .7);
  const clickedAudio = Boolean(bounds && event.clientY - bounds.top >= audioTop);
  if (!clickedAudio) {
    seekSourceTime(time);
    return;
  }
  timelineFrameSelectionTime = null;
  const match = timelineEventSegmentAtTime(time);
  if (match) previewEventSegment(match.group, match.segment);
  else {
    showSource();
    seekSourceTime(time);
    updateTimeline();
  }
}

function moveTimelineRange(event) {
  if (!timelineRangeDrag || !currentJob) return;
  if (Math.abs(event.clientX - timelineRangeDrag.startX) >= 4) timelineRangeDrag.moved = true;
  if (!timelineRangeDrag.moved) return;
  const value = timelineTimeFromPointer(event);
  currentJob.manualSelection = {
    start: Math.round(Math.min(timelineRangeDrag.anchor, value) * 20) / 20,
    end: Math.round(Math.max(timelineRangeDrag.anchor, value) * 20) / 20,
  };
  currentJob.manualSelection.duration = currentJob.manualSelection.end - currentJob.manualSelection.start;
  refreshManualSelection(true);
}

async function finishTimelineRange(event) {
  if (!timelineRangeDrag || !currentJob) return;
  const drag = timelineRangeDrag;
  timelineRangeDrag = null;
  document.removeEventListener("pointermove", moveTimelineRange);
  document.removeEventListener("pointerup", finishTimelineRange);
  if (!drag.moved) {
    seekSourceTime(timelineTimeFromPointer(event));
    return;
  }
  const selection = currentJob.manualSelection;
  if (selection.end - selection.start < 1) {
    selection.end = Math.min(timelineDurationValue(), selection.start + 1);
    selection.start = Math.max(0, selection.end - 1);
  }
  selection.start = snapTimelineBoundary(selection.start);
  selection.end = snapTimelineBoundary(selection.end);
  if (selection.end - selection.start < 1) selection.end = Math.min(timelineDurationValue(), selection.start + 1);
  pendingTimelineOriginal = drag.original ? { ...drag.original } : null;
  pendingTimelineSelection = { start: selection.start, end: selection.end, duration: selection.end - selection.start };
  refreshManualSelection();
  $("#timelineHint").textContent = "选区尚未保存：可拖动两端微调，确认后再合成";
}

async function confirmPendingTimelineSelection() {
  if (!pendingTimelineSelection || !currentJob) return true;
  try {
    const result = await api(`/api/jobs/${currentJob.id}/selection`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start: pendingTimelineSelection.start, end: pendingTimelineSelection.end }),
    });
    currentJob.manualSelection = result.selection;
    pendingTimelineSelection = null;
    pendingTimelineOriginal = null;
    timelineChatSelections = [...timelineChatSelections.filter((entry) => Math.abs(Number(entry.start) - Number(result.selection.start)) > .05 || Math.abs(Number(entry.end) - Number(result.selection.end)) > .05), result.selection];
    refreshManualSelection();
    chatInput.placeholder = "已确认时间段，可直接合成或在对话中继续编辑";
    fillChatWithTimelineSelection(result.selection);
    return true;
  } catch (error) {
    window.alert(error.message);
    return false;
  }
}

function cancelPendingTimelineSelection() {
  if (!pendingTimelineSelection) return;
  if (pendingTimelineOriginal) currentJob.manualSelection = { ...pendingTimelineOriginal };
  else delete currentJob.manualSelection;
  pendingTimelineSelection = null;
  pendingTimelineOriginal = null;
  updateTimeline();
  $("#timelineHint").textContent = "已取消本次手动选区";
}

function updatePendingTimelineBoundary(boundary, rawValue) {
  if (!pendingTimelineSelection || !currentJob) return;
  const duration = timelineDurationValue();
  const value = Number(rawValue);
  if (!Number.isFinite(value)) return;
  const next = { ...pendingTimelineSelection };
  if (boundary === "start") next.start = Math.max(0, Math.min(value, duration));
  else next.end = Math.max(0, Math.min(value, duration));
  if (next.end - next.start < 1) {
    window.alert("手动选区必须至少保留 1 秒");
    updateTimelineSelection();
    return;
  }
  next.duration = next.end - next.start;
  pendingTimelineSelection = next;
  currentJob.manualSelection = { ...next };
  refreshManualSelection();
  $("#timelineHint").textContent = "时间已调整：确认选区后会填入对话框";
}

function beginTimelineRange(event) {
  if (!currentJob) return;
  if (!timelineManualSelectMode) {
    activateTimelinePoint(event);
    return;
  }
  if (!["awaiting_confirmation", "completed"].includes(currentJob.status)) {
    window.alert("请等待视频分析完成，进入候选审核后再选择时间段");
    seekSourceTime(timelineTimeFromPointer(event));
    return;
  }
  event.preventDefault();
  if (["output", "event"].includes(viewerMediaKind)) {
    const activeGroup = currentEventGroup;
    showSource();
    currentEventGroup = activeGroup;
  }
  currentOutput = null;
  currentCandidate = null;
  currentEventSegment = null;
  candidatePreviewEnd = null;
  renderEvidencePlaceholder({
    time: "手动选区",
    title: "拖动生成选区",
    reason: "在时间轴上拖出范围后，可以继续微调两端；确认选区后才会加入剪辑对话。",
  });
  document.querySelectorAll(".candidate-row").forEach((row) => row.classList.remove("previewing"));
  timelineRangeDrag = {
    anchor: timelineTimeFromPointer(event),
    startX: event.clientX,
    moved: false,
    original: currentJob.manualSelection ? { ...currentJob.manualSelection } : null,
  };
  document.addEventListener("pointermove", moveTimelineRange);
  document.addEventListener("pointerup", finishTimelineRange, { once: true });
}

function seekSourceTime(second) {
  const value = Math.max(0, Math.min(timelineDurationValue(), Number(second) || 0));
  const seek = () => {
    mainVideo.currentTime = Math.min(Math.max(0, mainVideo.duration - 0.05), value);
    updateTimelinePlayhead();
  };
  if (viewerMediaKind === "output") {
    showSource();
    mainVideo.addEventListener("loadedmetadata", seek, { once: true });
  } else if (mainVideo.readyState >= 1) {
    seek();
  } else {
    mainVideo.addEventListener("loadedmetadata", seek, { once: true });
  }
  if (currentCandidate) candidatePreviewEnd = value <= Number(currentCandidate.end) ? Number(currentCandidate.end) : null;
}

function candidateThumbnailStyle(candidate) {
  const sprite = timelineAssets?.sprite;
  if (!sprite?.items?.length || !timelineAssets?.spriteUrl) return "";
  const target = (Number(candidate.start) + Number(candidate.end)) / 2;
  const item = sprite.items.reduce((best, current) =>
    Math.abs(Number(current.time) - target) < Math.abs(Number(best.time) - target) ? current : best
  );
  const scale = 52 / Math.max(1, Number(sprite.tileHeight));
  return [
    `background-image:url('${timelineAssets.spriteUrl}')`,
    `background-size:${Number(sprite.spriteWidth) * scale}px ${Number(sprite.spriteHeight) * scale}px`,
    `background-position:${-Number(item.column) * Number(sprite.tileWidth) * scale}px ${-Number(item.row) * Number(sprite.tileHeight) * scale}px`,
  ].join(";");
}

function closeCandidateDrawer() {
  $("#candidateDrawer")?.classList.remove("open");
  $("#candidateDrawer")?.setAttribute("aria-hidden", "true");
  $("#drawerBackdrop")?.classList.add("hidden");
}

function renderCandidateDrawer(job) {
  const query = String($("#candidateDrawerSearch")?.value || "").trim().toLowerCase();
  const candidates = (job?.candidates || []).filter((candidate) => !query || [candidate.title, candidate.reason, candidate.audioEvidence?.transcriptExcerpt, ...itemSpeakers(candidate)].filter(Boolean).join(" ").toLowerCase().includes(query));
  const selectedGroups = new Set(job.recommendedGroupIds || []);
  const selectedCandidateIndices = new Set((job.eventGroups || [])
    .filter((group) => selectedGroups.has(group.id))
    .flatMap((group) => group.segments || [])
    .map((segment) => Number(segment.candidateIndex))
    .filter(Number.isFinite));
  const drawerList = $("#candidateDrawerList");
  if (!drawerList) return;
  const canReselect = job.status === "awaiting_confirmation" && Boolean(candidates.length);
  const drawerTitle = $("#candidateDrawerTitle");
  if (drawerTitle) drawerTitle.textContent = `精彩镜头候选（${candidates.length}）`;
  drawerList.innerHTML = candidates.length ? `${canReselect ? `<div class="drawer-batch-actions"><span>已选 <b>${selectedCandidateIndices.size}</b> 个镜头</span><button type="button" class="drawer-create-event" ${selectedCandidateIndices.size ? "" : "disabled"}>用所选镜头新建事件</button></div>` : ""}${candidates.map((candidate, index) => `
    <article class="drawer-candidate${canReselect ? " selectable" : ""}${currentCandidate?.index === candidate.index ? " active" : ""}" data-drawer-candidate="${candidate.index}">
      ${canReselect ? `<input class="drawer-candidate-check" type="checkbox" value="${candidate.index}" ${selectedCandidateIndices.has(Number(candidate.index)) ? "checked" : ""} aria-label="选择第 ${index + 1} 个镜头">` : ""}
      <div class="candidate-thumb" style="${candidateThumbnailStyle(candidate)}"><span>${formatTime(candidate.start)}</span></div>
      <div class="drawer-candidate-copy"><span><strong>${index + 1}. ${escapeHtml(candidate.title)}</strong><b>${Math.round(candidate.score)}</b></span>
        <small>${formatTime(candidate.start)} → ${formatTime(candidate.end)} · ${Number(candidate.duration).toFixed(1)} 秒</small>
        ${audioEvidenceMarkup(candidate.audioEvidence)}
        <div class="drawer-candidate-actions"><button type="button" class="drawer-preview">预览源镜头</button><button type="button" class="drawer-add" ${job.status === "awaiting_confirmation" && job.eventGroups?.length ? "" : "disabled"}>加入事件</button></div>
      </div>
    </article>`).join("")}` : '<div class="rail-empty"><strong>暂无可用镜头</strong><p>模型完成精修后会在这里展示候选池。</p></div>';
  drawerList?.querySelectorAll("[data-drawer-candidate]").forEach((row) => {
    const candidate = candidates.find((item) => Number(item.index) === Number(row.dataset.drawerCandidate));
    row.querySelector(".drawer-preview")?.addEventListener("click", () => previewCandidate(Number(candidate.index)));
    row.querySelector(".drawer-add")?.addEventListener("click", () => addCandidateToEvent(candidate));
  });
  const updateBatchSelection = () => {
    const count = drawerList.querySelectorAll(".drawer-candidate-check:checked").length;
    const action = drawerList.querySelector(".drawer-create-event");
    const label = drawerList.querySelector(".drawer-batch-actions span b");
    if (label) label.textContent = String(count);
    if (action) action.disabled = !count;
  };
  drawerList?.querySelectorAll(".drawer-candidate-check").forEach((input) => input.addEventListener("change", updateBatchSelection));
  drawerList.querySelector(".drawer-create-event")?.addEventListener("click", createEventFromCandidateSelection);
  if ($("#candidateDrawerSearch")) $("#candidateDrawerSearch").oninput = () => renderCandidateDrawer(currentJob);
}

function openCandidateDrawer() {
  if (String(currentJob?.taskMode || "") === "content_extract") {
    setDirectorStage("events");
    $("#chatMessages .content-search-message")?.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  if (!currentJob?.candidates?.length) return;
  renderCandidateDrawer(currentJob);
  $("#drawerBackdrop")?.classList.remove("hidden");
  $("#candidateDrawer")?.classList.add("open");
  $("#candidateDrawer")?.setAttribute("aria-hidden", "false");
}

async function addCandidateToEvent(candidate) {
  const groups = currentJob?.eventGroups || [];
  if (!groups.length) return;
  const listing = groups.map((group, index) => `${index + 1}. ${group.title}`).join("\n");
  const choice = Number(window.prompt(`将“${candidate.title}”加入哪个事件？\n${listing}`, "1"));
  if (!Number.isInteger(choice) || choice < 1 || choice > groups.length) return;
  const group = groups[choice - 1];
  const actionToken = captureJobAction();
  if (!jobActionStillCurrent(actionToken)) return;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/event-groups/${encodeURIComponent(group.id)}/segments`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start: candidate.start, end: candidate.end, role: candidate.title || "候选补充镜头" }),
    });
    if (!jobActionStillCurrent(actionToken)) return;
    currentEventGroup = job.eventGroups.find((item) => item.id === group.id) || null;
    closeCandidateDrawer();
    setDirectorStage("events");
    commitJobAction(job, actionToken);
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
}

async function createEventFromCandidateSelection() {
  if (!currentJob || currentJob.status !== "awaiting_confirmation" || actionBusy) return;
  const indices = [...$("#candidateDrawerList")?.querySelectorAll(".drawer-candidate-check:checked") || []].map((input) => Number(input.value));
  if (!indices.length) return void window.alert("请至少选择一个镜头候选");
  const title = window.prompt("为这组镜头命名", "重新编排高光");
  if (title === null) return;
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job, groupId } = await api(`/api/jobs/${actionToken.jobId}/event-groups/from-candidates`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ indices, title: title.trim() || "重新编排高光" }),
    });
    if (!jobActionStillCurrent(actionToken)) return;
    currentEventGroup = job.eventGroups.find((group) => group.id === groupId) || null;
    currentEventSegment = null;
    closeCandidateDrawer();
    setDirectorStage("events");
    commitJobAction(job, actionToken);
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

function selectedRailGroupIds() {
  const checked = new Set([...$("#railBody")?.querySelectorAll(".rail-event-check:checked") || []].map((input) => input.value));
  const ordered = eventGroupSelectionOrder.filter((id) => checked.has(String(id)));
  const remaining = [...checked].filter((id) => !ordered.includes(id));
  return [...ordered, ...remaining];
}

function recordEventGroupSelection(id, checked) {
  const value = String(id);
  eventGroupSelectionOrder = eventGroupSelectionOrder.filter((item) => item !== value);
  if (checked) eventGroupSelectionOrder.push(value);
}

function selectedSegmentIdsForGroup(group) {
  if (!group) return [];
  const saved = pendingSegmentSelections.get(String(group.id));
  return saved ? [...saved] : (group.segments || []).map((segment) => String(segment.id));
}

function selectedGroupsWithSegments(job) {
  return (job.eventGroups || []).filter((group) => selectedRailGroupIds().includes(String(group.id))).map((group) => ({
    ...group,
    segments: (group.segments || []).filter((segment) => selectedSegmentIdsForGroup(group).includes(String(segment.id))),
  })).filter((group) => group.segments.length);
}

async function saveSegmentTechnique(group, segment, values) {
  if (!currentJob || actionBusy) return;
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/event-groups/${encodeURIComponent(group.id)}/segments/${encodeURIComponent(segment.id)}/technique`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values),
    });
    if (!commitJobAction(job, actionToken)) return;
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

function bindRailEventActions(job) {
  const railBody = $("#railBody");
  if (!railBody) return;
  normalizeSegmentActionLabels(railBody);
  railBody.querySelectorAll(".event-group-row").forEach((row) => {
    const group = job.eventGroups.find((item) => item.id === row.dataset.eventGroup);
    if (!group) return;
    row.querySelector(".preview-event")?.addEventListener("click", () => previewEventGroup(group));
    row.querySelector(".rename-event")?.addEventListener("click", () => renameEventGroup(group));
    row.querySelector(".add-selection-event")?.addEventListener("click", () => addSelectionToEventGroup(group));
    row.querySelectorAll(".event-segment").forEach((segmentRow, segmentIndex) => {
      const segment = group.segments.find((item) => item.id === segmentRow.dataset.segmentId);
      segmentRow.querySelector(".preview-segment")?.addEventListener("click", () => previewEventSegment(group, segment));
      segmentRow.querySelector(".delete-segment")?.addEventListener("click", () => deleteEventSegment(group, segment));
      segmentRow.querySelector(".move-segment-up")?.addEventListener("click", () => reorderEventSegment(group, segmentIndex, segmentIndex - 1));
      segmentRow.querySelector(".move-segment-down")?.addEventListener("click", () => reorderEventSegment(group, segmentIndex, segmentIndex + 1));
      segmentRow.querySelector(".move-segment-group")?.addEventListener("click", () => moveEventSegment(group, segment));
      segmentRow.querySelector(".segment-speed")?.addEventListener("change", (event) => saveSegmentTechnique(group, segment, { playbackRate: Number(event.target.value), speedLocked: true }));
      segmentRow.querySelector(".segment-transition")?.addEventListener("change", (event) => saveSegmentTechnique(group, segment, { transitionType: event.target.value, transitionLocked: true }));
      segmentRow.querySelector(".segment-bridge")?.addEventListener("change", (event) => saveSegmentTechnique(group, segment, { audioBridgeType: event.target.value, audioBridgeLocked: true }));
    });
  });
  const refreshEventReviewCta = () => {
    const footer = railBody.querySelector(".event-review-next");
    if (!footer) return;
    const count = railBody.querySelectorAll(".rail-event-check:checked").length;
    const countNode = footer.querySelector("[data-selected-event-count]");
    const button = footer.querySelector(".open-compose-stage");
    if (countNode) countNode.textContent = String(count);
    if (button) button.disabled = count === 0;
  };
  railBody.querySelectorAll(".rail-event-check").forEach((input) => input.addEventListener("change", () => {
    recordEventGroupSelection(input.value, input.checked);
    const group = job.eventGroups.find((item) => String(item.id) === String(input.value));
    if (group) pendingSegmentSelections.set(String(group.id), input.checked ? new Set((group.segments || []).map((segment) => String(segment.id))) : new Set());
    renderRailOutput(job);
    refreshEventReviewCta();
  }));
  railBody.querySelectorAll(".rail-segment-check").forEach((input) => input.addEventListener("change", () => {
    const group = job.eventGroups.find((item) => String(item.id) === String(input.dataset.groupId));
    if (!group) return;
    const selected = new Set(selectedSegmentIdsForGroup(group));
    if (input.checked) selected.add(String(input.value)); else selected.delete(String(input.value));
    pendingSegmentSelections.set(String(group.id), selected);
    const eventCheck = railBody.querySelector(`.rail-event-check[value="${CSS.escape(String(group.id))}"]`);
    if (eventCheck) eventCheck.checked = selected.size > 0;
    renderRailOutput(job);
    refreshEventReviewCta();
  }));
  refreshEventReviewCta();
}

function renderRailOutput(job) {
  const output = $("#railOutput");
  if (!output) return;
  if (job.status !== "awaiting_confirmation" || !job.eventGroups?.length) {
    output.classList.add("hidden");
    return;
  }
  const ids = selectedRailGroupIds();
  const selected = selectedGroupsWithSegments(job);
  const total = selected.reduce((sum, group) => sum + group.segments.reduce((inner, segment) => inner + Number(segment.duration || (Number(segment.end) - Number(segment.start)) || 0), 0), 0);
  const segmentCount = selected.reduce((sum, group) => sum + group.segments.length, 0);
  const info = job.videoInfo || {};
  const singleReel = outputAssemblyMode === "single_reel";
  const savedSubtitleMode = String(job.brief?.subtitlePreference || job.request?.subtitleMode || "none");
  const briefSubtitle = savedSubtitleMode === "burn" ? "burn" : "none";
  const savedSubtitleStyle = String(job.brief?.subtitleStyle || job.request?.subtitleStyle || "clean");
  const briefSubtitleStyle = ["clean", "bold", "social"].includes(savedSubtitleStyle) ? savedSubtitleStyle : "clean";
  output.classList.remove("hidden");
  output.innerHTML = `<section class="composition-workbench">
      <header class="composition-header"><div><small>FINAL COMPOSE</small><strong>生成高光成片</strong></div><span>${selected.length} 个事件 · ${segmentCount} 个镜头</span></header>
      <div class="composition-selection"><div><b>当前选择</b><span>${total.toFixed(1)} 秒${job.totalTargetSeconds ? ` · 单条目标 ${Number(job.totalTargetSeconds).toFixed(1)} 秒` : " · 当前推荐总时长"}</span></div><button type="button" class="back-to-events">返回事件审核</button></div>
      <section class="composition-step"><div class="composition-step-title"><b>1</b><div><strong>成片形式</strong><small>将已选事件合成一条视频，或分别导出</small></div></div><div class="output-mode-switch" role="group" aria-label="成片形式"><button type="button" data-output-mode="single_reel" class="${singleReel ? "active" : ""}">已选事件合成 1 条</button><button type="button" data-output-mode="separate_events" class="${singleReel ? "" : "active"}">分别导出已选事件</button></div></section>
      <section class="composition-step"><div class="composition-step-title"><b>2</b><div><strong>按当前选择生成</strong><small>保持时间轴和事件审核中的镜头顺序</small></div></div><div class="manual-mode-note"><strong>${singleReel ? "生成一条成片" : "分别导出已选事件"}</strong><span>${singleReel ? "不改变镜头顺序，直接合成。" : "每个已选事件导出为一条视频。"}</span><button type="button" class="generate-events" ${selected.length ? "" : "disabled"}>${singleReel ? "生成成片" : `导出 ${selected.length} 个事件`}</button></div></section>
      <details class="composition-step advanced-output"><summary><span class="composition-step-title"><b>3</b><span><strong>高级输出设置</strong><small>字幕、格式和画面规格</small></span></span></summary><div class="output-specs"><div><span>格式</span><b>MP4 · H.264</b></div><div><span>分辨率</span><b>${info.width && info.height ? `${info.width}×${info.height}` : "保持源画面"}</b></div><div><span>码率</span><b>自动设置</b></div><label class="subtitle-output-option"><span>字幕</span><select id="subtitleMode"><option value="none" ${briefSubtitle === "none" ? "selected" : ""}>不添加字幕</option><option value="burn" ${briefSubtitle === "burn" ? "selected" : ""}>添加 AI 字幕</option></select></label><label class="subtitle-output-option subtitle-style-option ${briefSubtitle === "burn" ? "" : "hidden"}"><span>样式</span><select id="subtitleStyle"><option value="clean" ${briefSubtitleStyle === "clean" ? "selected" : ""}>简洁 · 白字描边</option><option value="bold" ${briefSubtitleStyle === "bold" ? "selected" : ""}>醒目 · 加粗亮色</option><option value="social" ${briefSubtitleStyle === "social" ? "selected" : ""}>短视频 · 大字底框</option></select></label><small class="subtitle-warning ${briefSubtitle === "burn" ? "" : "hidden"}">源视频已有画面字幕时请保持“不添加字幕”，否则可能出现双字幕。</small></div></details>
      ${job.reediting && job.outputs?.length ? '<button type="button" class="cancel-reedit">返回上一次结果</button>' : ""}
    </section>`;
  output?.querySelectorAll("[data-output-mode]").forEach((button) => button.addEventListener("click", () => {
    outputAssemblyMode = button.dataset.outputMode;
    renderRailOutput(job);
  }));
  output.querySelector("#subtitleMode")?.addEventListener("change", (event) => {
    const enabled = event.target.value === "burn";
    output.querySelector(".subtitle-style-option")?.classList.toggle("hidden", !enabled);
    output.querySelector(".subtitle-warning")?.classList.toggle("hidden", !enabled);
  });
  output.querySelector(".back-to-events")?.addEventListener("click", () => setDirectorStage("events"));
  output.querySelector(".generate-events")?.addEventListener("click", () => {
    const subtitleMode = output.querySelector("#subtitleMode")?.value || "none";
    const subtitleStyle = output.querySelector("#subtitleStyle")?.value || "clean";
    confirmEventGroups(selectedRailGroupIds(), outputAssemblyMode, Object.fromEntries([...pendingSegmentSelections].map(([id, values]) => [id, [...values]])), subtitleMode, subtitleStyle);
  });
  output.querySelector(".cancel-reedit")?.addEventListener("click", cancelCurrentJobReediting);
}

async function requestAutoPlans(job, scope = "selected_only", variantCount = 3, groupIdsOverride = null, skipConfirmation = false) {
  if (!job || actionBusy) return;
  const editMode = String(job.brief?.editMode || job.request?.editMode || "ai_plan");
  if (!skipConfirmation && editMode === "manual") return void window.alert("当前为手动剪辑，请直接在时间轴和事件审核中选择镜头。");
  if (!skipConfirmation && editMode === "recommend_review") return void window.alert("当前为 AI 推荐后审核，请先审核候选事件，再直接合成。");
  const groupIds = groupIdsOverride?.length ? [...groupIdsOverride] : selectedRailGroupIds();
  const segmentIds = Object.fromEntries([...pendingSegmentSelections].map(([id, values]) => [id, [...values]]));
  if (!groupIds.length) return void window.alert("请至少选择一个事件高光");
  if (!skipConfirmation && !await requestActionConfirmation({ title: "AI 智能规划剪辑方案", summary: `将生成 ${variantCount} 个不同的局部镜头与叙事编排方案。`, details: [scope === "all_pool" ? "当前选择优先，必要时从全候选池补充" : "只在当前选择内重新编排", "每个候选只保留必要的小段", "先审核方案，确认后才渲染"] })) return;
  const actionToken = captureJobAction(job);
  if (!jobActionStillCurrent(actionToken)) return;
  setDirectorStage("compose");
  actionBusy = true;
  try {
    const { job: updated } = await api(`/api/jobs/${job.id}/auto-plans`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope, groupIds, segmentIds, targetSeconds: Number(job.totalTargetSeconds || job.request?.totalTargetSeconds || 0) || null, structure: job.brief?.structure || job.request?.structure || "auto", variantCount: Math.max(1, Math.min(5, Number(variantCount) || 3)), techniquePolicy: job.brief?.techniquePolicy || job.request?.techniquePolicy || { preset: "auto" } }) });
    if (!jobActionStillCurrent(actionToken)) return;
    currentEventGroup = null;
    currentEventSegment = null;
    commitJobAction(updated, actionToken);
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

async function requestLlmOrder(job, groupIds, segmentIds = null) {
  if (!job || actionBusy) return;
  const actionToken = captureJobAction(job);
  if (!jobActionStillCurrent(actionToken)) return;
  actionBusy = true;
  setDirectorStage("conversation");
  try {
    const { job: updated } = await api(`/api/jobs/${job.id}/llm-order`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ groupIds, segmentIds }) });
    if (!commitJobAction(updated, actionToken)) return;
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

async function renderAutoPlan(job, planId) {
  if (!job || !planId || actionBusy) return;
  const subtitleMode = $("#subtitleMode")?.value || "none";
  const subtitleStyle = $("#subtitleStyle")?.value || "clean";
  if (!await requestActionConfirmation({ title: "确认生成此剪辑方案", summary: "系统将按照方案中的局部起止点和镜头顺序渲染成片。", details: ["不会重新分析视频", "原有成片版本不会被覆盖", "生成后可继续重新规划"] })) return;
  let subtitleDraftId = null;
  if (subtitleMode === "burn") {
    const plan = (job.autoPlans || []).find((item) => String(item.id) === String(planId));
    if (!plan?.sequence?.length) return void showToast("当前方案没有可校对的剪辑时间线");
    const draft = await reviewSubtitlesBeforeRender([{ segments: plan.sequence }], subtitleStyle);
    if (!draft) return;
    subtitleDraftId = draft.id;
  }
  const actionToken = captureJobAction(job);
  if (!jobActionStillCurrent(actionToken)) return;
  setDirectorStage("compose");
  actionBusy = true;
  try {
    const { job: updated } = await api(`/api/jobs/${job.id}/auto-plans/${encodeURIComponent(planId)}/render`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ planId, subtitleMode, subtitleStyle, subtitleDraftId }) });
    if (!commitJobAction(updated, actionToken)) return;
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

function renderReviewRail(job) {
  const body = $("#railBody");
  const openCandidates = $("#openCandidateDrawer");
  if (!body || !openCandidates) return;
  const railTitle = $("#railTitle");
  const contentMode = taskModePresentation(job).key === "content_extract";
  const setRailTitle = (value) => { if (railTitle) railTitle.textContent = value; };
  const contentCandidates = Array.isArray(job.contentSearch?.candidates) ? job.contentSearch.candidates : [];
  openCandidates.disabled = !(job.candidates?.length || contentCandidates.length);
  openCandidates.textContent = contentMode ? "查看匹配片段" : "镜头候选";
  const hasGeneratedOutputs = Boolean(
    (job.outputs || []).length
    || (job.outputVersions || []).some((version) => (version.outputs || []).length),
  );
  if (job.status === "briefing") {
    setRailTitle("理解需求");
    body.innerHTML = `<div class="rail-empty"><span class="empty-thinking-orb" data-thinking-orb data-orb-state="composing" data-orb-size="64" data-orb-theme="light" data-orb-label="正在理解剪辑需求"></span><strong>正在理解剪辑需求</strong><p>${escapeHtml(job.detail || "LLM 正在整理目标、重点和限制")}</p></div>`;
    syncThinkingOrbs(body);
    $("#railOutput")?.classList.add("hidden");
    return;
  }
  if (job.status === "brief_confirmation") {
    const brief = job.brief || {};
    setRailTitle("需求确认");
    body.innerHTML = `<div class="rail-section-title"><strong>AI 剪辑需求简报</strong><b>等待确认</b></div><p class="rail-summary">请在 AI 高光导演的需求简报卡中修改并保存；确认后才会调用视觉模型。</p><section class="brief-review-card"><dl><div><dt>剪辑目标</dt><dd>${escapeHtml(brief.objective || "事件高光合集")}</dd></div><div><dt>单条成片目标</dt><dd>${brief.targetDurationSeconds ? `${Number(brief.targetDurationSeconds).toFixed(1)} 秒` : "AI 推荐"}</dd></div><div><dt>关注重点</dt><dd>${escapeHtml((brief.focus || ["综合判断"]).join("、"))}</dd></div><div><dt>风格节奏</dt><dd>${escapeHtml([brief.style?.pace, brief.style?.tone].filter(Boolean).join(" · ") || "纪实自然")}</dd></div></dl><button type="button" class="confirm-brief-button" data-focus-brief>编辑并确认简报</button></section>`;
    body.querySelector("[data-focus-brief]")?.addEventListener("click", () => $("#chatMessages .brief-editor")?.scrollIntoView({ behavior: "smooth", block: "center" }));
    $("#railOutput")?.classList.add("hidden");
    return;
  }
  if (job.status === "awaiting_model_decision") {
    setRailTitle("等待处理");
    const candidates = job.candidates || [];
    body.innerHTML = `<div class="rail-section-title"><strong>${candidates.length ? `已精修候选（${candidates.length}）` : "候选审核区"}</strong><b>检查点已保存</b></div><p class="rail-summary">请在分析进度卡中选择重试、降级继续或取消。${candidates.length ? "这些精修结果不会因重试而丢失。" : "完成当前阶段后会继续发现候选。"}</p>${candidates.length
      ? `<div class="paused-candidate-list">${candidates.map((candidate, index) => `<article><span><b>${index + 1}. ${escapeHtml(candidate.title)}</b><small>${formatTime(candidate.start)} → ${formatTime(candidate.end)} · ${Number(candidate.duration).toFixed(1)} 秒</small></span><em>${Math.round(candidate.score)}</em></article>`).join("")}</div>`
      : `<div class="rail-skeleton-list" aria-hidden="true">${Array.from({ length: 3 }, () => `<i><span></span><b></b><em></em></i>`).join("")}</div>`}`;
    $("#railOutput")?.classList.add("hidden");
    return;
  }
  if (["queued", "running", "cancelling"].includes(job.status)) {
    setRailTitle(contentMode ? "内容检索" : "实时分析");
    body.innerHTML = `<div class="rail-section-title"><strong>${contentMode ? "正在检索内容" : "候选审核区"}</strong><b>${contentMode ? "完成后确认" : "分析后显示"}</b></div>
      <p class="rail-summary">${contentMode ? `新的匹配片段会在检索完成后显示。${hasGeneratedOutputs ? "已有内容视频仍可在对话框中点击预览。" : ""}` : "候选镜头与高光事件整理完成后将在这里出现。"}</p>
      <div class="rail-skeleton-list" aria-hidden="true">${Array.from({ length: 4 }, () => `<i><span></span><b></b><em></em></i>`).join("")}</div>`;
    $("#railOutput")?.classList.add("hidden");
    return;
  }
  if (contentMode && job.status === "awaiting_content_confirmation") {
    const warning = job.workflow?.actionRequired;
    const selectedCount = Number(job.contentSearch?.defaultSelectedIds?.length || 0);
    setRailTitle("片段确认");
    body.innerHTML = `<div class="rail-section-title"><strong>${contentCandidates.length ? "检索结果 · 选择片段" : escapeHtml(warning?.title || "需要补充确认")}</strong><b>${contentCandidates.length} 个匹配片段</b></div><p class="rail-summary">${contentCandidates.length ? `请在对话框中逐段预览并选择；当前默认选中 ${selectedCount} 段。选择完成后即可生成新视频。` : escapeHtml(warning?.message || "请在对话框中确认人物、Speaker 或查找依据后继续。")} ${hasGeneratedOutputs ? "以前生成的内容视频仍可预览和下载。" : ""}</p><button type="button" class="focus-content-review">${contentCandidates.length ? "前往片段选择" : "前往处理"}</button>`;
    body.querySelector(".focus-content-review")?.addEventListener("click", () => {
      setDirectorStage("events");
      $("#chatMessages .content-search-message")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    $("#railOutput")?.classList.add("hidden");
    return;
  }
  // A rendered version is the primary result, even when the backend keeps the
  // job in awaiting_confirmation so the source event pool remains reusable.
  // Do not show an empty compose form (0 events / 0 clips) underneath it.
  if (hasGeneratedOutputs && job.status === "awaiting_confirmation") {
    setRailTitle("生成结果");
    const autoVersionCount = Number(job.autoComposition?.versions?.length || 0);
    body.innerHTML = contentMode
      ? `<div class="rail-section-title"><strong>内容视频已生成</strong><b>可继续调整</b></div><p class="rail-summary">当前内容视频版本已记录在任务中，源视频保持不变。可在对话框中点击版本预览；需要调整时返回内容片段确认。</p><button type="button" class="reedit-job-button">返回片段确认</button>`
      : `<div class="rail-section-title"><strong>高光成片已生成</strong><b>${job.autoComposition?.status === "completed" ? `${autoVersionCount} 个自动版本` : "可继续调整"}</b></div><p class="rail-summary">当前成片版本已记录在任务中，源视频保持不变。${job.autoComposition?.status === "completed" ? `已生成 ${autoVersionCount} 个自动版本，请在播放器顶部的预览菜单中比较。` : "需要更换镜头时，可返回事件审核继续调整。"}</p>${job.autoComposition?.status === "completed" ? "" : '<button type="button" class="reedit-job-button">返回事件审核</button>'}`;
    body.querySelector(".reedit-job-button")?.addEventListener("click", reopenCurrentJobForEditing);
    $("#railOutput")?.classList.add("hidden");
    return;
  }
  if (job.status === "awaiting_confirmation" && job.eventGroups?.length) {
    const recommended = new Set(job.recommendedGroupIds || []);
    const target = Number(job.totalTargetSeconds || job.request?.totalTargetSeconds || 0);
    const allocated = Number(job.allocatedTotalSeconds || 0);
    const tolerance = Number(job.durationTolerance || .1);
    const over = target && Math.abs(allocated - target) > target * tolerance;
    const theme = String(job.request?.theme || "综合判断").split(/[，,、\s]+/).filter(Boolean).slice(0, 4);
    const profile = job.contentProfile || {};
    setRailTitle(`事件高光（${job.eventGroups.length}）`);
    body.innerHTML = `<div class="rail-section-title"><strong>高光事件</strong><b>推荐 ${recommended.size} 个事件</b></div>
      <p class="rail-summary">每个高光事件包含一组相关镜头。选择多个事件后，可以合成一条视频，也可以分别导出。</p>
      <div class="duration-budget${over ? " over" : ""}"><span><b>${allocated.toFixed(1)} 秒</b><em>${target ? `目标 ${target.toFixed(1)} 秒` : "当前推荐总时长"}</em></span><i><b style="width:${target ? Math.min(100, allocated / target * 100) : 100}%"></b></i></div>
      <div class="event-group-list">${job.eventGroups.map((group, groupIndex) => `<article class="event-group-row${recommended.has(group.id) ? " recommended" : ""}${currentEventGroup?.id === group.id ? " active" : ""}" data-event-group="${escapeHtml(group.id)}">
        <header><input class="rail-event-check" type="checkbox" value="${escapeHtml(group.id)}" ${recommended.has(group.id) ? "checked" : ""}><span><strong>${escapeHtml(group.title)}</strong><small>${group.segments.length} 个镜头 · ${Number(group.actualDuration).toFixed(1)} 秒</small></span><b>${Math.round(group.score)}</b></header>
        <p>${escapeHtml(group.summary)}</p><div class="event-group-actions"><button class="preview-event" type="button">组合预览</button><button class="rename-event" type="button">命名</button><button class="add-selection-event" type="button" ${job.manualSelection ? "" : "disabled"}>加入选区</button></div>
        <details ${currentEventGroup?.id === group.id || groupIndex === 0 ? "open" : ""}><summary>事件镜头 · ${selectedSegmentIdsForGroup(group).length}/${group.segments.length} 个已选</summary><div class="event-segments">${group.segments.map((segment, segmentIndex) => `<div class="event-segment${currentEventSegment?.id === segment.id ? " active" : ""}" data-segment-id="${escapeHtml(segment.id)}"><input class="rail-segment-check" data-group-id="${escapeHtml(group.id)}" type="checkbox" value="${escapeHtml(segment.id)}" ${selectedSegmentIdsForGroup(group).includes(String(segment.id)) ? "checked" : ""} aria-label="选择${escapeHtml(segment.role || "镜头")}"><span><b>${segmentIndex + 1}. ${escapeHtml(segment.role)}</b><small>${formatTime(segment.start)} → ${formatTime(segment.end)} · 输出约 ${Number(segment.effectiveDuration || segment.duration || (Number(segment.end) - Number(segment.start))).toFixed(1)} 秒</small>${audioEvidenceMarkup(segment.audioEvidence)}<span class="segment-technique-controls"><label>速度<select class="segment-speed"><option value="1" ${Number(segment.playbackRate || 1) === 1 ? "selected" : ""}>1×</option><option value="1.1" ${Number(segment.playbackRate) === 1.1 ? "selected" : ""}>1.1×</option><option value="1.25" ${Number(segment.playbackRate) === 1.25 ? "selected" : ""}>1.25×</option><option value="1.5" ${Number(segment.playbackRate) === 1.5 ? "selected" : ""}>1.5×</option></select></label><label>转场<select class="segment-transition"><option value="cut" ${(segment.transitionIn?.type || "cut") === "cut" ? "selected" : ""}>硬切</option><option value="dissolve" ${segment.transitionIn?.type === "dissolve" ? "selected" : ""}>短叠化</option><option value="fade_black" ${segment.transitionIn?.type === "fade_black" ? "selected" : ""}>淡黑</option></select></label><label>声音<select class="segment-bridge"><option value="none" ${(segment.audioBridge?.type || "none") === "none" ? "selected" : ""}>同步</option><option value="j_cut" ${segment.audioBridge?.type === "j_cut" ? "selected" : ""}>J-cut</option><option value="l_cut" ${segment.audioBridge?.type === "l_cut" ? "selected" : ""}>L-cut</option></select></label></span></span><button class="preview-segment" type="button">看</button><button class="move-segment-up" type="button" ${segmentIndex === 0 ? "disabled" : ""}>↑</button><button class="move-segment-down" type="button" ${segmentIndex === group.segments.length - 1 ? "disabled" : ""}>↓</button><button class="move-segment-group" type="button">移</button><button class="delete-segment" type="button">删</button></div>`).join("")}</div></details>
      </article>`).join("")}</div>
      <section class="analysis-tags"><strong>本次分析依据${job.directorDegraded ? " · 事件归组已降级" : ""}${job.speechAnalysis?.degraded ? " · 语音已降级" : ""}</strong><div><span>${job.request?.analysisMode === "audiovisual" ? "视听综合" : "纯视觉"}</span>${job.speechAnalysis?.status === "ready" ? `<span>SenseVoice · ${Number(job.speechAnalysis.segments || 0)} 段</span>` : ""}${job.speechAnalysis?.diarization ? `<span>说话人分段</span>` : ""}${profile.primaryType ? `<span>${escapeHtml(profile.primaryType)}</span>` : ""}${profile.narrativeMode ? `<span>${escapeHtml(profile.narrativeMode)}</span>` : ""}${(theme.length ? theme : ["综合判断"]).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div></section>
      <footer class="event-review-next"><span><b data-selected-event-count>${recommended.size}</b> 个事件已选 · 可继续调整镜头</span><button type="button" class="open-compose-stage" ${recommended.size ? "" : "disabled"}>继续生成成片</button></footer>`;
    bindRailEventActions(job);
    body.querySelector(".open-compose-stage")?.addEventListener("click", () => setDirectorStage("compose"));
    renderRailOutput(job);
    return;
  }
  if (job.status === "awaiting_confirmation" && job.candidates?.length) {
    const recommended = new Set(job.recommendedIndices || []);
    setRailTitle(`历史候选（${job.candidates.length}）`);
    body.innerHTML = `<div class="rail-section-title"><strong>单镜头候选</strong><b>兼容旧任务</b></div>
      <p class="rail-summary">该任务创建于事件编排功能上线前，可继续按原候选生成；新任务会自动使用多镜头事件成片。</p>
      <div class="legacy-candidate-list">${job.candidates.map((candidate, index) => `<label class="legacy-candidate-row"><input type="checkbox" value="${candidate.index}" ${recommended.has(candidate.index) ? "checked" : ""}><span><strong>${index + 1}. ${escapeHtml(candidate.title)}</strong><small>${formatTime(candidate.start)} → ${formatTime(candidate.end)} · ${Number(candidate.duration).toFixed(1)} 秒</small></span><b>${Math.round(candidate.score)}</b><button type="button" data-legacy-preview="${candidate.index}">预览</button></label>`).join("")}</div>`;
  body?.querySelectorAll("[data-legacy-preview]").forEach((button) => button.addEventListener("click", (event) => {
      event.preventDefault();
      previewCandidate(Number(button.dataset.legacyPreview));
    }));
    const output = $("#railOutput");
    if (!output) return;
    output.classList.remove("hidden");
    const updateLegacyOutput = () => {
      const indices = [...(body?.querySelectorAll(".legacy-candidate-row input:checked") || [])].map((input) => Number(input.value));
      const selected = job.candidates.filter((candidate) => indices.includes(Number(candidate.index)));
      output.innerHTML = `<div class="output-title"><strong>输出设置</strong><span>兼容旧任务</span></div><div class="output-specs"><div><span>格式</span><b>MP4 · H.264</b></div><div><span>分辨率</span><b>保持源画面</b></div><div><span>输出</span><b>1 条成片 · ${selected.length} 个镜头</b></div></div><button type="button" class="generate-events" ${indices.length ? "" : "disabled"}>✦ 合成 1 条高光成片</button>`;
      output.querySelector(".generate-events")?.addEventListener("click", () => confirmCandidates(indices, "single_reel"));
    };
    body?.querySelectorAll(".legacy-candidate-row input").forEach((input) => input.addEventListener("change", updateLegacyOutput));
    updateLegacyOutput();
    return;
  }
  if (job.status === "completed") {
    setRailTitle(`生成结果（${job.outputs?.length || 0}）`);
    const autoDone = job.autoComposition?.status === "completed";
    const autoVersionCount = Number(job.autoComposition?.versions?.length || 0);
    body.innerHTML = `<div class="rail-section-title"><strong>${contentMode ? "内容视频与技术检查完成" : "渲染与技术检查完成"}</strong><b>${autoDone ? `${autoVersionCount} 个版本已完成` : "已完成"}</b></div><p class="rail-summary">${autoDone ? `已生成 ${autoVersionCount} 个自动版本，源视频保持不变。` : contentMode ? "视频仅包含已确认的内容片段。需要调整时，可以返回片段确认并生成新版本。" : "如需调整，可以返回现有候选，重新选择事件和镜头后再次合成；不会重复调用视觉模型。"}</p>${autoDone ? "" : `<button type="button" class="reedit-job-button">${contentMode ? "返回片段确认" : "返回事件审核"}</button>`}`;
    body.querySelector(".reedit-job-button")?.addEventListener("click", reopenCurrentJobForEditing);
    $("#railOutput")?.classList.add("hidden");
    return;
  }
  setRailTitle(job.status === "failed" ? "分析失败" : "任务已停止");
  const interrupted = job.status === "failed" && job.stage === "interrupted";
  const resumeLabel = job.resumeAvailable ? "↻ 从检查点恢复分析" : "↻ 使用原素材重新分析";
  const resumeHint = job.resumeAvailable ? "已保存的媒体、波形和阶段检查点会优先复用。" : "未找到阶段检查点，将复用已上传的原素材。";
  body.innerHTML = `<div class="rail-empty"><span class="empty-thinking-orb" data-thinking-orb data-orb-state="shaping" data-orb-size="64" data-orb-theme="light" data-orb-label="任务未完成"></span><strong>${escapeHtml(job.detail || "任务未完成")}</strong><p>${escapeHtml(job.error || "返回全部任务后，可新建任务并重新选择素材。")}</p>${interrupted ? `<button type="button" class="primary resume-interrupted-job">${resumeLabel}</button><small class="rail-summary">${resumeHint}</small>` : '<button type="button" class="primary return-home-from-failure">返回全部任务</button>'}</div>`;
  body.querySelector(".resume-interrupted-job")?.addEventListener("click", () => resolveModelDecision("retry"));
  body.querySelector(".return-home-from-failure")?.addEventListener("click", () => resetWorkspace());
  $("#railOutput")?.classList.add("hidden");
}

function syncReviewSelectionClasses() {
  document.querySelectorAll(".event-group-row").forEach((row) => row.classList.toggle("active", row.dataset.eventGroup === currentEventGroup?.id));
  document.querySelectorAll(".event-segment").forEach((row) => row.classList.toggle("active", row.dataset.segmentId === currentEventSegment?.id));
  document.querySelectorAll(".drawer-candidate").forEach((row) => row.classList.toggle("active", Number(row.dataset.drawerCandidate) === Number(currentCandidate?.index)));
}

function renderOutputs(job) {
  const versions = jobOutputVersions(job);
  const outputs = versions.flatMap((version) => version.outputs || []);
  $("#clipSection")?.classList.add("hidden");
  if (!outputs.length) {
    renderOutputPreviewSelector(job);
    showSource();
    return;
  }
  renderOutputPreviewSelector(job);
  const preferred = currentOutput && outputs.some((item) => item.filename === currentOutput.filename)
    ? currentOutput.filename
    : outputs[0].filename;
  selectOutput(preferred);
}

function jobRenderRevision(job) {
  // The server revision advances for every progress heartbeat so polling can
  // be cheap and race-safe. DOM reconstruction is intentionally keyed only
  // to structural changes; same-stage percent updates use the live progress
  // updater below and no longer replace the conversation/timeline tree.
  const outputs = jobOutputVersions(job).flatMap((version) => version.outputs || []);
  return JSON.stringify({
    id: job?.id,
    status: job?.status,
    stage: job?.stage,
    error: job?.error,
    pendingDecision: job?.pendingDecision?.stage,
    previewReady: job?.previewReady,
    previewPreparing: job?.previewPreparing,
    candidateCount: job?.candidates?.length || 0,
    eventGroupCount: job?.eventGroups?.length || 0,
    pendingSelectionGroupIds: job?.pendingSelectionGroupIds || [],
    editProposal: [job?.pendingEditProposal?.id || "", job?.pendingEditProposal?.status || ""],
    outputVersionId: job?.currentOutputVersionId,
    autoComposition: [job?.autoComposition?.status, job?.autoComposition?.phase, job?.autoComposition?.versions?.length || 0],
    outputs: outputs.map((item) => [item.filename, item.previewReady, item.kept]),
    messageCount: job?.messages?.length || 0,
    contentUiRevision: job?.contentUiRevision || "",
  });
}

async function activateOutputVersion(versionId) {
  if (!currentJob || actionBusy) return;
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/output-versions/${encodeURIComponent(versionId)}/activate`, { method: "POST" });
    if (!jobActionStillCurrent(actionToken)) return;
    currentOutput = null;
    commitJobAction(job, actionToken);
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

async function deleteOutputVersion(versionId) {
  if (!currentJob || actionBusy) return;
  const version = jobOutputVersions().find((item) => String(item.id) === String(versionId));
  if (!version || !window.confirm(`确定删除 V${Number(version.number || 1)}？保留库中的独立副本不会被删除。`)) return;
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/output-versions/${encodeURIComponent(versionId)}`, { method: "DELETE" });
    if (!jobActionStillCurrent(actionToken)) return;
    currentOutput = null;
    commitJobAction(job, actionToken);
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

function renderJob(job) {
  // A home "new task" action owns the workspace until the next upload is
  // submitted. Ignore any late history/poll response from the previous task;
  // otherwise its conversation can be painted back over the empty composer.
  if (!job?.id) return;
  if (homeNavigationRequested && !restoringHistory) return;
  // A response for another task is stale even when the user is no longer on
  // the home screen (for example, task A finishes after task B was opened).
  if (!restoringHistory && currentJob && String(currentJob.id) !== String(job.id)) return;
  rememberCurrentJob(job);
  const previousId = currentJob?.id;
  setDirectorWorkspaceEmpty(false);
  const revision = jobRenderRevision(job);
  if (previousId === job?.id && currentJobRevision === revision) {
    currentJob = job;
    syncOneOffFinalizeAction(job);
    renderReviewStatus(job);
    renderDirectorTaskSummary(job);
    // Progress updates can arrive without a DOM revision (for example while
    // the worker is reporting the same stage). Keep the live console visible
    // and refresh its text/percent on every poll instead of waiting for a
    // browser reload to rebuild the page.
    const live = isPipelineRunningStatus(job.status);
    const decision = job.status === "awaiting_model_decision";
    const progressVisible = analysisConsoleVisible(job);
    const cancellable = isActiveJobStatus(job.status) || ["brief_confirmation", "awaiting_confirmation", "awaiting_content_confirmation"].includes(String(job.status || ""));
    updateDirectorState(job);
    updateDirectorThinkingOrb(job);
    updateDirectorFlow(job);
    if (live && directorStage === "conversation") setDirectorStage("analysis");
    placeAnalysisConsole(progressVisible);
    const cancelButton = $("#cancelButton");
    cancelButton?.classList.toggle("hidden", !cancellable);
    if (cancelButton) cancelButton.textContent = live ? "停止分析" : "取消任务";
    if ($("#jobDetail")) $("#jobDetail").textContent = job.detail || job.stage || "准备中";
    if ($("#jobPercent")) $("#jobPercent").textContent = `${Math.round((Number(job.progress) || 0) * 100)}%`;
    $("#jobProgress")?.style.setProperty("width", `${Math.round((Number(job.progress) || 0) * 100)}%`);
    updateAnalysisConsole(job);
    updateInlineAnalysisProgress(job);
    updateAutoCompositionProgress(job);
    // Resource endpoints can become ready without changing the public job
    // revision. Keep their lightweight retry loops alive even when the DOM
    // itself does not need to be rebuilt.
    loadWaveform(job);
    loadTimelineAssets(job);
    const reviewReady = ["brief_confirmation", "awaiting_confirmation", "awaiting_content_confirmation", "awaiting_model_decision", "completed"].includes(job.status);
    const transcriptPendingStages = new Set(["queued", "starting", "probing", "audio_analysis", "speech_recognition"]);
    const transcriptMayBeReady = reviewReady || !transcriptPendingStages.has(String(job.stage || ""));
    if (transcriptMayBeReady && waveformData?.hasAudio !== false) loadTimelineTranscript(job);
    return;
  }
  currentJobRevision = revision;
  const previousPreviewReady = Boolean(currentJob?.previewReady);
  const activeGroupId = currentEventGroup?.id;
  const activeSegmentId = currentEventSegment?.id;
  const activeCandidateIndex = currentCandidate?.index;
  currentJob = job;
  syncOneOffFinalizeAction(job);
  updatePlayerChrome();
  renderReviewStatus(job);
  renderDirectorTaskSummary(job);
  updateDirectorFlow(job);
  applyMediaAspect(viewerShell, job.videoInfo?.width, job.videoInfo?.height);
  currentEventGroup = activeGroupId ? job.eventGroups?.find((item) => item.id === activeGroupId) || null : null;
  currentEventSegment = activeSegmentId && currentEventGroup
    ? currentEventGroup.segments.find((item) => item.id === activeSegmentId) || null
    : null;
  currentCandidate = activeCandidateIndex === undefined ? currentCandidate : (job.candidates || []).find((item) => Number(item.index) === Number(activeCandidateIndex)) || null;
  if (previousId !== job.id) {
    expandedContentSearchIds.clear();
    contentSearchDetailCache.clear();
    contentSearchFilterState.clear();
    cancelTimelinePan(null);
    cancelTimelineOverview(null);
    currentJobRevision = revision;
    currentOutput = null;
    viewerMediaKind = "source";
    currentCandidate = null;
    currentEventGroup = null;
    currentEventSegment = null;
    timelineFrameSelectionTime = null;
    pendingTimelineSelection = null;
    pendingTimelineOriginal = null;
    timelineManualSelectMode = false;
    locallyExcludedCandidates = new Set((job.reviewExcludedCandidates || []).map((index) => Number(index)));
    outputAssemblyMode = "single_reel";
    pendingSegmentSelections = new Map();
    timelineChatSelections = [];
    eventGroupSelectionOrder = [];
    ignoredChatContextKeys = new Set();
    activeProposalSourceRange = null;
    timelineViewStart = 0;
    timelineViewEnd = Number(job.videoInfo?.duration || 0);
    timelineCoordinateSpace = "output";
    timelineReviewFollow = false;
    timelineAssetsJobId = null;
    timelineAssetsLoadingJobId = null;
    timelineAssets = null;
    timelineAssetsRetryAt = 0;
    timelineTranscript = [];
    transcriptLoadingJobId = null;
    timelineTranscriptJobId = null;
    transcriptRetryAt = 0;
    timelineMediaRenderKey = "";
    waveformRenderKey = "";
    waveformRetryAt = 0;
  }
  if (previousId === job.id && job.previewReady && !previousPreviewReady && ["source", "candidate", "segment"].includes(viewerMediaKind)) {
    const resumeTime = Number(mainVideo.currentTime || 0);
    const wasPlaying = !mainVideo.paused;
    clearPlayerNotice();
    mainVideo.addEventListener("loadedmetadata", () => {
      mainVideo.currentTime = Math.min(Math.max(0, mainVideo.duration - .05), resumeTime);
      if (wasPlaying) safePlay();
    }, { once: true });
    setMainVideoSource(sourcePreviewUrl(job));
  }
  const reviewReady = ["brief_confirmation", "awaiting_confirmation", "awaiting_content_confirmation", "awaiting_model_decision", "completed"].includes(job.status);
  // Waveform and frame thumbnails describe the source, so they are useful while
  // analysis is still running. Candidate overlays remain unavailable until the
  // model has produced them, but the base timeline should never stay blank.
  loadWaveform(job);
  loadTimelineAssets(job);
  const transcriptPendingStages = new Set(["queued", "starting", "probing", "audio_analysis", "speech_recognition"]);
  const transcriptMayBeReady = reviewReady || !transcriptPendingStages.has(String(job.stage || ""));
  if (transcriptMayBeReady && waveformData?.hasAudio !== false) loadTimelineTranscript(job);
  $("#uploadView")?.classList.add("hidden");
  $("#reviewView")?.classList.remove("hidden");
  // ResizeObserver does not fire reliably when a whole grid changes from
  // display:none in every Chromium build. Fit explicitly on workspace entry
  // so the media canvas can never remain at its empty intrinsic size (0×0).
  scheduleMediaFrameFit(true);
  chatInput.disabled = false;
  const interactionKind = String(job.contentSearch?.interactionState?.kind || "");
  chatInput.placeholder = taskModePresentation(job).key === "content_extract"
    ? interactionKind === "person_target" ? "回复人物 A、人物 B，或输入新的查找条件"
      : interactionKind === "speaker_link" ? "回复 Speaker 编号，或点击上方选项确认"
        : interactionKind === "capability_confirmation" ? "回复“确认”启用新增分析，或修改查找条件"
          : "描述要找的内容，或和 AI 讨论如何剪辑……"
    : "请输入指令或补充需求……";
  $("#sendButton").disabled = false;
  updateComposerBeam();
  const running = isPipelineRunningStatus(job.status);
  const briefing = job.status === "briefing";
  const awaitingDecision = job.status === "awaiting_model_decision";
  updateDirectorState(job);
  updateDirectorThinkingOrb(job);
  // renderConversation replaces its message list, so move the console after
  // the conversation has been rendered and keep it in the same visual flow.
  renderConversation(job);
  // Failed/interrupted jobs must keep the review rail visible so the user can
  // access recovery actions such as “从中断处恢复分析”. Only active pipeline
  // work and explicit model decisions take over the rail.
  const cancellable = isActiveJobStatus(job.status) || ["brief_confirmation", "awaiting_confirmation", "awaiting_content_confirmation"].includes(job.status);
  const pipelineVisible = running || awaitingDecision;
  const progressVisible = analysisConsoleVisible(job);
  const compositionRunning = running && ["rendering", "edit_planning", "auto_composition"].includes(String(job.stage || "")) && directorStage === "compose";
  if (briefing) setDirectorStage("conversation");
  else if (awaitingDecision) setDirectorStage("analysis");
  else if (compositionRunning) setDirectorStage("compose");
  else if (running) setDirectorStage("analysis");
  else if (["awaiting_confirmation", "awaiting_content_confirmation"].includes(job.status)) setDirectorStage("conversation");
  else if (job.status === "completed") setDirectorStage("compose");
  else if (["cancelled", "failed"].includes(job.status)) setDirectorStage("conversation");
  placeAnalysisConsole(progressVisible);
  $(".review-rail")?.classList.toggle("pipeline-mode", pipelineVisible);
  if ($("#jobDetail")) $("#jobDetail").textContent = job.detail || job.stage;
  if ($("#jobPercent")) $("#jobPercent").textContent = `${Math.round((job.progress || 0) * 100)}%`;
  $("#jobProgress")?.style.setProperty("width", `${Math.round((job.progress || 0) * 100)}%`);
  updateAnalysisConsole(job);
  updateInlineAnalysisProgress(job);
  renderAnalysisDecision(job);
  const cancelButton = $("#cancelButton");
  cancelButton?.classList.toggle("hidden", !cancellable);
  if (cancelButton) cancelButton.textContent = running ? "停止分析" : "取消任务";
  if ($("#jobError")) $("#jobError").textContent = job.error || "";
  $("#jobError")?.classList.toggle("hidden", !job.error);
  if ($("#assetDuration")) $("#assetDuration").textContent = `时长 ${formatClock(job.videoInfo?.duration || 0)}`;
  if ($("#assetResolution")) $("#assetResolution").textContent = job.videoInfo?.width && job.videoInfo?.height
    ? `分辨率 ${job.videoInfo.width}×${job.videoInfo.height}` : "分辨率 --";
  renderReviewRail(job);
  syncThinkingOrbs($("#railBody"));
  if (jobOutputCount(job)) renderOutputs(job);
  else {
    $("#clipSection")?.classList.add("hidden");
    if (previousId !== job.id || !mainVideo.src) showSource();
  }
  updateTimeline();
  if (!jobNeedsPolling(job) && !briefing && !restoringHistory) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

async function pollJob() {
  if (!currentJob) return;
  const polledJobId = String(currentJob.id);
  clearTimeout(pollTimer);
  pollTimer = null;
  if (document.hidden) {
    pollTimer = window.setTimeout(pollJob, 6000);
    return;
  }
  try {
    const knownRevision = Number(currentJob?.revision || 0);
    const response = await api(`/api/jobs/${encodeURIComponent(polledJobId)}/status?revision=${knownRevision}`);
    if (!currentJob || String(currentJob.id) !== polledJobId) return;
    pollFailureDelay = 2500;
    if (!response.changed) {
      if (jobNeedsPolling(currentJob)) pollTimer = setTimeout(pollJob, jobPollDelay(currentJob));
      return;
    }
    const snapshot = response.job || {};
    const needsFullRefresh = Number(snapshot.candidateCount || 0) !== Number(currentJob.candidates?.length || 0)
      || Number(snapshot.eventGroupCount || 0) !== Number(currentJob.eventGroups?.length || 0)
      || Number(snapshot.outputVersionCount || 0) !== Number(currentJob.outputVersions?.length || 0)
      || String(snapshot.contentUiRevision || "") !== String(currentJob.contentUiRevision || "")
      || Boolean(snapshot.pendingDecision) !== Boolean(currentJob.pendingDecision)
      || (!["briefing", "queued", "running", "cancelling"].includes(String(snapshot.status || ""))
        && String(snapshot.status || "") !== String(currentJob.status || ""));
    let job;
    if (needsFullRefresh) {
      ({ job } = await api(`/api/jobs/${encodeURIComponent(polledJobId)}`));
      if (!currentJob || String(currentJob.id) !== polledJobId) return;
    } else {
      job = { ...currentJob, ...snapshot, autoComposition: { ...(currentJob.autoComposition || {}), ...(snapshot.autoComposition || {}) } };
    }
    renderJob(job);
    if (jobNeedsPolling(job)) pollTimer = setTimeout(pollJob, job.status === "briefing" ? 1400 : jobPollDelay(job));
  } catch (error) {
    const errorNode = $("#jobError");
    if (errorNode) {
      errorNode.textContent = error.message;
      errorNode.classList.remove("hidden");
    }
    pollTimer = setTimeout(pollJob, pollFailureDelay);
    pollFailureDelay = Math.min(10000, Math.round(pollFailureDelay * 1.5));
  }
}

async function confirmCandidates(indices, outputMode = "single_reel") {
  if (!currentJob || currentJob.status !== "awaiting_confirmation" || actionBusy) return;
  if (!indices.length) return void window.alert("请至少选择一个高光候选");
  const selected = indices.map((index) => currentJob.candidates?.find((candidate) => Number(candidate.index) === Number(index))).filter(Boolean);
  const total = selected.reduce((sum, item) => sum + Number(item.duration || (Number(item.end) - Number(item.start)) || 0), 0);
  const confirmation = await requestActionConfirmation({
    title: "合成候选高光",
    summary: `将把 ${selected.length} 个候选镜头按当前顺序合成为 1 条高光视频，预计 ${total.toFixed(1)} 秒。`,
    details: [`来源：${currentJob.filename || "当前视频"}`],
    orderMode: "selection",
    orderItems: selected.map((item) => ({ id: String(item.index), label: item.title || `候选 ${Number(item.index) + 1}`, meta: `${formatTime(item.start)}→${formatTime(item.end)}` })),
  });
  if (!confirmation) return;
  const orderMode = typeof confirmation === "object" ? confirmation.orderMode : "selection";
  if (typeof confirmation === "object" && confirmation.orderedItems?.length) indices = confirmation.orderedItems.map((item) => Number(item.id));
  if (orderMode === "llm_recommend") {
    return void window.alert("剪辑规划模型需要高光事件数据才能推荐顺序；当前候选会按你调整后的顺序合成。可先进入事件审核，再使用顺序推荐。");
  }
  if (orderMode === "ai_plan") {
    setDirectorStage("compose");
    return;
  }
  let subtitleDraftId = null;
  if (subtitleMode === "burn") {
    try {
      let outputs = [];
      if (outputMode === "single_reel") {
        const response = await api(`/api/jobs/${currentJob.id}/technique-plan`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ groupIds, segmentIds, targetSeconds: target || null, orderMode, techniquePolicy, manualSelection: true }),
        });
        outputs = [{ segments: response.plan?.segments || [] }];
      } else {
        for (const groupId of groupIds) {
          const response = await api(`/api/jobs/${currentJob.id}/technique-plan`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ groupIds: [groupId], segmentIds: segmentIds?.[groupId] ? { [groupId]: segmentIds[groupId] } : null, targetSeconds: target || null, orderMode: "selection", techniquePolicy, manualSelection: true }),
          });
          outputs.push({ segments: response.plan?.segments || [] });
        }
      }
      const draft = await reviewSubtitlesBeforeRender(outputs, subtitleStyle);
      if (!draft) return;
      subtitleDraftId = draft.id;
    } catch (error) { return void showToast(error.message); }
  }
  const actionToken = captureJobAction();
  if (!jobActionStillCurrent(actionToken)) return;
  setDirectorStage("compose");
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ indices, outputMode, orderMode }),
    });
    if (!commitJobAction(job, actionToken)) return;
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

function recognitionEvidenceKind(item = {}) {
  const value = String(item.modality || item.evidenceKind || "visual").toLowerCase();
  const labels = {
    speech: "对白", speechunits: "对白", visual: "画面", visualunits: "画面",
    ocr: "屏幕文字", ocrunits: "屏幕文字", audio: "声音", audiounits: "声音",
    person: "匿名人物", persons: "匿名人物", track: "人物轨迹", persontracks: "人物轨迹",
    shot: "镜头", shots: "镜头",
  };
  return labels[value] || "内容证据";
}

function recognitionEvidenceCopy(item = {}) {
  const values = [
    item.text, item.summary, item.title, item.label,
    ...(item.visibleText || []), ...(item.entities || []), ...(item.actions || []),
    ...(item.labels || []), ...(item.personLabels || []), ...(item.audioEvents || []),
  ].map((value) => String(value || "").trim()).filter(Boolean);
  return [...new Set(values)].join(" · ") || `${recognitionEvidenceKind(item)}已在该时间范围内检出`;
}

function contentMatchEvidenceShell(match) {
  $("#evidencePanel")?.classList.remove("hidden", "evidence-placeholder", "output-mode", "montage-mode");
  $("#evidencePanel")?.classList.add("candidate-mode");
  $("#clipTime").textContent = `${formatTime(match.start)} → ${formatTime(match.end)} · ${Number(match.duration || 0).toFixed(1)} 秒`;
  $("#clipTitle").textContent = match.title || "匹配内容";
  $("#clipScore").textContent = `${Math.round(Number(match.score || 0))}/100`;
  $("#clipReason").textContent = match.reason || match.matchedEvidence || "内容索引匹配";
  $("#outputExplanation")?.classList.add("hidden");
  const transcript = $("#clipTranscript");
  const excerpt = String(match.transcriptExcerpt || "").trim();
  const transcriptIsContext = (match.speechUnits || []).some((unit) => Number(unit.start) < Number(match.start) - .5 || Number(unit.end) > Number(match.end) + .5);
  if (transcript) {
    transcript.innerHTML = excerpt ? `<small>${transcriptIsContext ? "相邻对白上下文" : "对白证据"}</small><p>${escapeHtml(excerpt)}</p>` : "";
    transcript.classList.toggle("hidden", !excerpt);
  }
  const modalities = [...new Set((match.matchedModalities || [match.evidenceType]).filter(Boolean))];
  if ($("#clipEvidenceMeta")) $("#clipEvidenceMeta").innerHTML = [
    `<span>类型 ${escapeHtml(contentMatchTypeLabel(match))}</span>`,
    ...modalities.map((value) => `<span>${escapeHtml(({ speech: "对白", visual: "画面", ocr: "屏幕文字", audio: "声音", person: "匿名人物" })[value] || value)}</span>`),
  ].join("");
  if ($("#clipEvidence")) $("#clipEvidence").innerHTML = `<li class="content-evidence-loading"><span>正在读取该片段的识别证据…</span></li>`;
  $("#addToChatButton")?.classList.add("hidden");
  $("#keepButton")?.classList.add("hidden");
  $("#replaceButton")?.classList.add("hidden");
}

async function loadContentMatchEvidence(match) {
  if (!currentJob || !match) return;
  const requestToken = ++contentEvidenceRequestToken;
  const jobId = String(currentJob.id);
  const params = new URLSearchParams({
    start: String(Math.max(0, Number(match.start) || 0)),
    end: String(Math.max(Number(match.start) || 0, Number(match.end) || 0)),
    limit: "200",
  });
  try {
    const payload = await api(`/api/jobs/${encodeURIComponent(jobId)}/recognition?${params}`);
    if (requestToken !== contentEvidenceRequestToken || String(currentJob?.id || "") !== jobId) return;
    const allEvidence = Array.isArray(payload.evidence) ? payload.evidence : [];
    const referenced = new Set((match.evidenceRefs || []).map((item) => String(item?.id || item)).filter(Boolean));
    const evidence = (referenced.size
      ? allEvidence.filter((item) => referenced.has(String(item.id)))
      : allEvidence).slice(0, referenced.size ? Math.max(1, referenced.size) : 40);
    const kindCounts = evidence.reduce((counts, item) => {
      const label = recognitionEvidenceKind(item);
      counts[label] = Number(counts[label] || 0) + 1;
      return counts;
    }, {});
    const meta = $("#clipEvidenceMeta");
    if (meta) meta.innerHTML = [
      `<span>检索类型 ${escapeHtml(contentMatchTypeLabel(match))}</span>`,
      referenced.size ? `<span>候选引用 ${referenced.size} 条</span>` : "",
      ...Object.entries(kindCounts).map(([label, count]) => `<span>${escapeHtml(label)} ${count}</span>`),
      payload.truncated ? `<span>仅显示前 ${evidence.length} 条</span>` : "",
    ].join("");
    const list = $("#clipEvidence");
    if (!list) return;
    list.innerHTML = evidence.length ? evidence.map((item, index) => {
      const start = Number(item.start ?? item.time ?? match.start) || 0;
      const end = Number(item.end ?? item.time ?? start) || start;
      const range = end > start + .01 ? `${formatTime(start)} → ${formatTime(end)}` : formatTime(start);
      return `<li><button type="button" class="evidence-main-button" data-content-evidence-time="${start}"><small class="evidence-source-label">${escapeHtml(recognitionEvidenceKind(item))} ${String(index + 1).padStart(2, "0")} · ${range}</small><span class="evidence-item-copy">${escapeHtml(recognitionEvidenceCopy(item))}</span></button></li>`;
    }).join("") : `<li class="content-evidence-empty"><span>这个片段有检索匹配，但当前识别范围内没有更多可展开的明细。</span></li>`;
    list.querySelectorAll("[data-content-evidence-time]").forEach((button) => button.addEventListener("click", () => seekSourceTime(Number(button.dataset.contentEvidenceTime))));
  } catch (error) {
    if (requestToken !== contentEvidenceRequestToken || String(currentJob?.id || "") !== jobId) return;
    if ($("#clipEvidence")) $("#clipEvidence").innerHTML = `<li class="content-evidence-empty"><span>${escapeHtml(error.message || "详细证据读取失败")}</span></li>`;
  }
}

function previewContentMatch(match, { autoplay = true, loadEvidence = true } = {}) {
  if (!currentJob || !match) return;
  showSource({ autoplay });
  currentOutput = null;
  currentEventGroup = null;
  currentEventSegment = null;
  currentCandidate = match;
  const start = Math.max(0, Number(match.start) || 0);
  const end = Math.max(start, Number(match.end) || start);
  candidatePreviewEnd = Math.max(start, end - 0.008);
  viewerMediaKind = "segment";
  $("#viewerBadge").textContent = "内容匹配预览";
  $("#reviewKicker").textContent = "CONTENT MATCH";
  $("#reviewTitle").textContent = match.title || "匹配内容";
  contentMatchEvidenceShell(match);
  if (loadEvidence) loadContentMatchEvidence(match);
  if (autoplay) mainVideo.addEventListener("seeked", () => safePlay(), { once: true });
  else mainVideo.pause();
  seekSourceTime(start);
  refreshTimelineAfterReviewSelection();
  syncReviewSelectionClasses();
}

function contentBoundaryFrameRate(job = currentJob) {
  const value = Number(job?.videoInfo?.frame_rate || job?.videoInfo?.frameRate || 0);
  return Number.isFinite(value) && value >= 1 && value <= 240 ? value : 30;
}

function contentBoundaryDraft(editor, match) {
  const fallbackStart = Number(match?.start) || 0;
  const fallbackEnd = Number(match?.end) || fallbackStart;
  return {
    ...match,
    start: Number.isFinite(Number(editor?.dataset.boundaryStart)) ? Number(editor.dataset.boundaryStart) : fallbackStart,
    end: Number.isFinite(Number(editor?.dataset.boundaryEnd)) ? Number(editor.dataset.boundaryEnd) : fallbackEnd,
  };
}

function syncContentBoundaryEditor(editor, scopedJob, match, { seekEdge = "" } = {}) {
  if (!editor || !match) return;
  const fps = contentBoundaryFrameRate(scopedJob);
  const frame = 1 / fps;
  const duration = Number(scopedJob?.videoInfo?.duration || currentJob?.videoInfo?.duration || 0);
  let start = Math.max(0, Number(editor.dataset.boundaryStart) || 0);
  let end = Math.max(start + frame, Number(editor.dataset.boundaryEnd) || start + frame);
  if (duration > 0) {
    end = Math.min(duration, end);
    start = Math.min(start, Math.max(0, end - frame));
  }
  start = Math.round(start * 1e6) / 1e6;
  end = Math.round(end * 1e6) / 1e6;
  editor.dataset.boundaryStart = String(start);
  editor.dataset.boundaryEnd = String(end);
  editor.querySelector("[data-boundary-start-label]").textContent = formatTime(start);
  editor.querySelector("[data-boundary-end-label]").textContent = formatTime(end);
  editor.querySelector("[data-boundary-summary]").textContent = `${formatTime(start)} → ${formatTime(end)} · ${(end - start).toFixed(2)} 秒`;
  editor.querySelector("[data-boundary-frame-rate]").textContent = `${fps.toFixed(Math.abs(fps - Math.round(fps)) < .001 ? 0 : 2)} fps · 1 帧约 ${(frame * 1000).toFixed(1)} ms`;
  const draft = { ...match, start, end, duration: end - start, title: `${match.title || "匹配内容"} · 边界预览` };
  previewContentMatch(draft, { autoplay: false, loadEvidence: false });
  if (seekEdge === "end") seekSourceTime(Math.max(start, end - frame));
}

async function saveContentBoundary(scopedJob, match, editor, operation = "save") {
  if (!currentJob || !scopedJob?.contentSearch?.id || actionBusy) return;
  const draft = contentBoundaryDraft(editor, match);
  const actionToken = captureJobAction();
  actionBusy = true;
  editor.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const { job } = await api(`/api/jobs/${encodeURIComponent(actionToken.jobId)}/content-search/boundary`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        searchId: scopedJob.contentSearch.id,
        matchId: match.id,
        operation,
        ...(operation === "save" ? { start: draft.start, end: draft.end } : {}),
      }),
    });
    if (!commitJobAction(job, actionToken)) return;
    showToast(operation === "reset" ? "已恢复系统识别的原始边界" : "片段边界已保存", "success");
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) showToast(`边界保存失败：${error.message}`);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

function wireContentBoundaryEditors(root, scopedJob) {
  root.querySelectorAll("[data-content-boundary-open]").forEach((button) => button.addEventListener("click", () => {
    const matchId = String(button.dataset.contentBoundaryOpen || "");
    const match = (scopedJob.contentSearch?.candidates || []).find((item) => String(item.id) === matchId);
    const editor = root.querySelector(`[data-content-boundary-editor="${CSS.escape(matchId)}"]`);
    if (!match || !editor) return;
    root.querySelectorAll("[data-content-boundary-editor]").forEach((item) => item.classList.add("hidden"));
    editor.dataset.boundaryStart = String(Number(match.start) || 0);
    editor.dataset.boundaryEnd = String(Number(match.end) || Number(match.start) || 0);
    editor.classList.remove("hidden");
    syncContentBoundaryEditor(editor, scopedJob, match, { seekEdge: "start" });
  }));
  root.querySelectorAll("[data-content-boundary-editor]").forEach((editor) => {
    const matchId = String(editor.dataset.contentBoundaryEditor || "");
    const match = (scopedJob.contentSearch?.candidates || []).find((item) => String(item.id) === matchId);
    if (!match) return;
    editor.querySelectorAll("[data-boundary-adjust]").forEach((button) => button.addEventListener("click", () => {
      const [edge, amountText] = String(button.dataset.boundaryAdjust || "").split(":");
      const frame = 1 / contentBoundaryFrameRate(scopedJob);
      const amount = amountText === "frame" ? frame : amountText === "-frame" ? -frame : Number(amountText);
      if (!Number.isFinite(amount) || !["start", "end"].includes(edge)) return;
      editor.dataset[edge === "start" ? "boundaryStart" : "boundaryEnd"] = String(
        Number(editor.dataset[edge === "start" ? "boundaryStart" : "boundaryEnd"]) + amount,
      );
      syncContentBoundaryEditor(editor, scopedJob, match, { seekEdge: edge });
    }));
    editor.querySelectorAll("[data-boundary-playhead]").forEach((button) => button.addEventListener("click", () => {
      const edge = String(button.dataset.boundaryPlayhead || "");
      if (!["start", "end"].includes(edge)) return;
      editor.dataset[edge === "start" ? "boundaryStart" : "boundaryEnd"] = String(timelineAbsoluteTime());
      syncContentBoundaryEditor(editor, scopedJob, match, { seekEdge: edge });
    }));
    editor.querySelector("[data-boundary-preview]")?.addEventListener("click", () => {
      const draft = contentBoundaryDraft(editor, match);
      previewContentMatch({ ...draft, duration: draft.end - draft.start }, { autoplay: true });
    });
    editor.querySelector("[data-boundary-cancel]")?.addEventListener("click", () => {
      editor.classList.add("hidden");
      previewContentMatch(match, { autoplay: false });
    });
    editor.querySelector("[data-boundary-save]")?.addEventListener("click", () => saveContentBoundary(scopedJob, match, editor));
    editor.querySelector("[data-boundary-reset]")?.addEventListener("click", () => saveContentBoundary(scopedJob, match, editor, "reset"));
    editor.querySelector("[data-boundary-auto]")?.addEventListener("click", () => {
      sendContentSearchFeedback("boundary_incorrect", match.id, match, { searchId: scopedJob.contentSearch.id });
    });
  });
}

async function sendContentSearchFeedback(verdict, matchId = null, match = null, { skipConfirmation = false, searchId = null } = {}) {
  if (!currentJob || actionBusy) return false;
  const labels = {
    not_relevant: "确认将这条标记为不相关，并从当前候选移除？",
    boundary_incorrect: "确认让系统自动重新识别这个片段的边界？这可能需要较长时间；如果只需前后移动几帧，请使用“调整边界”。",
    missed_content: "确认在当前检索最相关的两个时间区域提高画面采样密度？这会重新运行局部视觉分析。",
    review_keep: "确认保留这个不确定候选？它会计入最终结果。",
    review_reject: "确认排除这个不确定候选？它会保留在完整性记录中，但不会生成。",
  };
  if (!skipConfirmation && !await requestActionConfirmation({ title: "内容检索反馈", summary: labels[verdict] || "提交反馈？", details: [] })) return false;
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/content-search/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        searchId, verdict, matchId,
        evidenceIds: (match?.evidenceRefs || []).map((item) => item.id).filter(Boolean),
      }),
    });
    if (!commitJobAction(job, actionToken)) return;
    if (jobNeedsPolling(job)) pollJob();
    return true;
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
  return false;
}

async function restoreContentSearch(searchId) {
  if (!currentJob || !searchId || actionBusy) return;
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/content-search/history/${encodeURIComponent(searchId)}/restore`, { method: "POST" });
    commitJobAction(job, actionToken);
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

async function updateContentPersonLabel(personId, currentLabel = "") {
  if (!currentJob || !personId || actionBusy) return;
  const label = window.prompt(
    "为这个匿名人物添加项目内标签（例如：男主持人、女嘉宾、黑衣讲解员）",
    currentLabel,
  );
  if (label === null) return;
  const normalized = String(label).trim().replace(/\s+/g, " ");
  if (!normalized) return void window.alert("人物标签不能为空");
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const response = await api(
      `/api/jobs/${actionToken.jobId}/content-search/persons/${encodeURIComponent(personId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: normalized }),
      },
    );
    commitJobAction(response.job, actionToken);
    showToast(`已保存人物标签“${normalized}”`);
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

function syncContentPersonTargetControls(panel, { initial = false } = {}) {
  if (!panel) return;
  const controls = panel.querySelector("[data-person-target-controls]");
  if (!controls) return;
  const selected = [...panel.querySelectorAll("[data-person-target]:checked")];
  const previousCount = Number(controls.dataset.selectionCount || 0);
  const modes = [...panel.querySelectorAll("[data-person-match-mode]")];
  if (selected.length === 1) {
    const any = modes.find((input) => input.value === "any");
    if (any && !modes.some((input) => input.checked)) {
      any.checked = true;
      controls.dataset.autoSingleMode = "true";
    }
  } else if (!initial && selected.length > 1 && previousCount < 2 && controls.dataset.autoSingleMode === "true") {
    modes.forEach((input) => { input.checked = false; });
    delete controls.dataset.autoSingleMode;
  }
  controls.dataset.selectionCount = String(selected.length);
  panel.querySelectorAll(".content-person-card").forEach((card) => {
    const input = card.querySelector("[data-person-target]");
    card.classList.toggle("target", Boolean(input?.checked));
    const choiceText = card.querySelector(".content-person-choice span");
    if (choiceText) choiceText.textContent = input?.checked ? "已选择" : "选择人物";
  });
  const summary = controls.querySelector("[data-person-selection-summary]");
  if (summary) summary.textContent = `已选 ${selected.length} 人`;
  const confirm = controls.querySelector("[data-person-target-confirm]");
  const hasMode = selected.length === 1 || modes.some((input) => input.checked);
  if (confirm) confirm.disabled = !selected.length || !hasMode || actionBusy;
}

async function selectContentPersonTarget(personIds, matchMode = "any", triggerButton = null) {
  const normalizedIds = Array.isArray(personIds) ? personIds.map(String).filter(Boolean) : [String(personIds || "")].filter(Boolean);
  if (!currentJob || !normalizedIds.length || actionBusy) return;
  const actionToken = captureJobAction();
  const messagesEl = ensureChatMessages();
  const targetButtons = [...messagesEl.querySelectorAll("[data-person-target], [data-person-target-confirm]")];
  const previousLabels = new Map(targetButtons.map((button) => [button, button.textContent]));
  actionBusy = true;
  targetButtons.forEach((button) => { button.disabled = true; });
  if (triggerButton) {
    triggerButton.setAttribute("aria-busy", "true");
    triggerButton.textContent = "正在确认…";
  }
  try {
    const response = await api(`/api/jobs/${actionToken.jobId}/content-search/target-person`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ personIds: normalizedIds, matchMode }),
    });
    if (!commitJobAction(response.job, actionToken)) return;
    showToast(`已确认 ${normalizedIds.length} 个目标人物，正在执行原检索条件`);
    if (jobNeedsPolling(response.job)) pollJob();
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    targetButtons.forEach((button) => {
      if (!button.isConnected) return;
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = previousLabels.get(button) || button.textContent;
    });
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

async function confirmContentPersonSpeaker(personId, speakerRef, triggerButton = null) {
  if (!currentJob || !personId || !speakerRef) {
    showToast("缺少人物或 Speaker 信息，请刷新后重试");
    return;
  }
  if (speakerConfirmationBusy) {
    showToast("正在处理上一次 Speaker 确认，请稍候");
    return;
  }
  const actionToken = captureJobAction();
  const messagesEl = ensureChatMessages();
  speakerConfirmationBusy = true;
  const confirmationButtons = [...messagesEl.querySelectorAll("[data-content-speaker-confirm]")];
  const previousLabels = new Map(confirmationButtons.map((button) => [button, button.textContent]));
  confirmationButtons.forEach((button) => { button.disabled = true; });
  if (triggerButton) {
    triggerButton.setAttribute("aria-busy", "true");
    triggerButton.textContent = `正在确认 ${speakerRef}…`;
  }
  try {
    showToast(`正在提交人物与 ${speakerRef} 的关联…`);
    const response = await api(`/api/jobs/${actionToken.jobId}/content-search/confirm-speaker`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ personId, speakerRef }),
    });
    if (!commitJobAction(response.job, actionToken)) {
      showToast("任务状态已经更新，请在最新结果中重新确认");
      return;
    }
    showToast(`已关联 ${speakerRef}，正在按完整对白时间轴检索`);
    if (jobNeedsPolling(response.job)) pollJob();
  } catch (error) {
    showToast(`Speaker 确认失败：${error.message}`);
  } finally {
    speakerConfirmationBusy = false;
    confirmationButtons.forEach((button) => {
      if (!button.isConnected) return;
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = previousLabels.get(button) || button.textContent;
    });
  }
}

async function confirmContentSearch(root, reviewJob = currentJob) {
  if (!currentJob || ["running", "rendering", "cancelling"].includes(String(currentJob.status || "")) || actionBusy) return;
  const search = reviewJob?.contentSearch || {};
  const completeness = search.completeness || {};
  const exhaustiveIncomplete = String(search.resultMode || "") === "exhaustive"
    && completeness.status !== "complete";
  const pending = Number(completeness.pendingCount || 0);
  if (exhaustiveIncomplete && pending) return void window.alert(
    `还有 ${pending} 个不确定候选需要逐项“保留”或“排除”。处理完后即可生成。`,
  );
  const matchIds = [...root.querySelectorAll("[data-content-match]:checked")].map((input) => input.value);
  if (!matchIds.length) return void window.alert("请至少选择一个匹配片段");
  const outputMode = root.querySelector("[data-content-output-mode]")?.value || "single_reel";
  const requestedOrderMode = outputMode === "single_reel"
    ? root.querySelector("[data-content-order-mode]")?.value || "source"
    : "source";
  const selectedLookup = new Map(
    (search.candidates || [])
      .filter((item) => matchIds.includes(String(item.id)))
      .map((item) => [String(item.id), item]),
  );
  const savedOrder = (search.reviewDraft?.orderedMatchIds || []).map(String);
  const initialOrder = [...savedOrder.filter((id) => selectedLookup.has(id)), ...matchIds.filter((id) => !savedOrder.includes(id))];
  const matches = initialOrder.map((id) => selectedLookup.get(id)).filter(Boolean);
  const total = matches.reduce((sum, item) => sum + Number(item.duration || 0), 0);
  const orderItems = matches.map((item, index) => ({
    id: String(item.id),
    label: item.title || `匹配片段 ${index + 1}`,
    meta: `${formatTime(item.start)}→${formatTime(item.end)} · ${Number(item.duration || 0).toFixed(1)} 秒`,
  }));
  const orderLabels = {
    source: "按源视频时间排列",
    selection: "由你自定义排列",
    llm_recommend: "先由 LLM 推荐，再由你确认",
  };
  const confirmation = await requestActionConfirmation({
    title: outputMode === "single_reel" ? "确认生成内容合集" : "确认分别导出内容",
    summary: outputMode === "single_reel"
      ? `将把 ${matches.length} 个已审核片段合成一条，约 ${total.toFixed(1)} 秒；${orderLabels[requestedOrderMode] || orderLabels.source}。`
      : `将把 ${matches.length} 个已审核片段分别导出。`,
    details: matches.map((item, index) => `${index + 1}. ${formatTime(item.start)}→${formatTime(item.end)} · ${item.title || "匹配内容"}`),
    orderMode: outputMode === "single_reel" ? requestedOrderMode : null,
    orderItems: outputMode === "single_reel" ? orderItems : [],
    showOrderOptions: outputMode === "single_reel",
    warning: exhaustiveIncomplete
      ? "完整性检查尚未通过：全范围覆盖或独立语义复核未完成，当前选择可能遗漏其他符合条件的片段。继续只会生成你现在勾选的内容，不会标记为“已找全”。"
      : "",
    confirmLabel: exhaustiveIncomplete ? "接受可能遗漏并生成" : "确认并生成",
    onDraftChange: ({ orderMode: nextOrderMode, orderedItems }) => scheduleContentReviewDraftSave(root, reviewJob, {
      orderMode: nextOrderMode,
      orderedMatchIds: orderedItems.map((item) => String(item.id)),
    }),
  });
  if (!confirmation) return;
  let orderMode = outputMode === "single_reel" && typeof confirmation === "object"
    ? confirmation.orderMode
    : "source";
  let orderedMatchIds = typeof confirmation === "object" && confirmation.orderedItems?.length
    ? confirmation.orderedItems.map((item) => String(item.id))
    : matchIds;
  let orderReason = "";
  await saveContentReviewDraft(root, reviewJob, { orderMode, orderedMatchIds });

  if (orderMode === "llm_recommend") {
    const recommendationToken = captureJobAction();
    const confirmButton = root.querySelector("[data-confirm-content]");
    const previousLabel = confirmButton?.textContent || "确认所选并生成";
    actionBusy = true;
    if (confirmButton) {
      confirmButton.disabled = true;
      confirmButton.textContent = "LLM 正在推荐顺序…";
    }
    try {
      const recommendation = await api(`/api/jobs/${recommendationToken.jobId}/content-search/order-recommendation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          searchId: search.id,
          matchIds: orderedMatchIds,
        }),
      });
      if (!jobActionStillCurrent(recommendationToken)) return;
      orderedMatchIds = Array.isArray(recommendation.orderedMatchIds)
        ? recommendation.orderedMatchIds.map(String)
        : orderedMatchIds;
      orderReason = String(recommendation.reason || "");
      const matchLookup = new Map(matches.map((item) => [String(item.id), item]));
      const recommendationConfirmed = await requestActionConfirmation({
        title: "确认 LLM 推荐顺序",
        summary: "LLM 只调整片段排列，不会增删片段，也不会修改任何起止点。",
        details: orderedMatchIds.map((id, index) => {
          const item = matchLookup.get(id);
          return `${index + 1}. ${item?.title || "匹配内容"} · ${formatTime(item?.start)}→${formatTime(item?.end)}`;
        }),
        warning: orderReason ? `推荐理由：${orderReason}` : "",
        confirmLabel: "按此顺序生成",
      });
      if (!recommendationConfirmed) return;
      orderMode = "ai_plan";
    } catch (error) {
      if (jobActionStillCurrent(recommendationToken)) showToast(error.message);
      return;
    } finally {
      actionBusy = false;
      if (confirmButton && jobActionStillCurrent(recommendationToken)) {
        confirmButton.disabled = false;
        confirmButton.textContent = previousLabel;
      }
    }
  }

  const subtitleMode = root.querySelector("[data-content-subtitle]")?.checked ? "burn" : "none";
  let subtitleDraftId = null;
  if (subtitleMode === "burn") {
    const matchLookup = new Map(matches.map((item) => [String(item.id), item]));
    const orderedMatches = orderedMatchIds.map((id) => matchLookup.get(String(id))).filter(Boolean);
    const subtitleSegments = orderedMatches.map((item) => ({ start: Number(item.start), end: Number(item.end), playbackRate: 1, transitionIn: { type: "cut", duration: 0 } }));
    const outputs = outputMode === "single_reel"
      ? [{ segments: subtitleSegments }]
      : subtitleSegments.map((segment) => ({ segments: [segment] }));
    const draft = await reviewSubtitlesBeforeRender(outputs, "clean");
    if (!draft) return;
    subtitleDraftId = draft.id;
  }

  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/content-search/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        searchId: search.id,
        matchIds: orderedMatchIds,
        outputMode,
        orderMode,
        orderReason,
        subtitleMode,
        subtitleStyle: "clean",
        subtitleDraftId,
        acknowledgeIncomplete: exhaustiveIncomplete,
      }),
    });
    if (!commitJobAction(job, actionToken)) return;
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

async function confirmContentSelectionBasket(job = currentJob, acknowledgements = {}) {
  const items = contentBasketItems(job);
  if (!job?.id || !items.length || actionBusy) return;
  const duration = items.reduce((sum, item) => sum + Math.max(0, Number(item.duration) || Number(item.end) - Number(item.start) || 0), 0);
  const confirmed = await requestActionConfirmation({
    title: "生成合并视频",
    summary: `将待合并片段中的 ${items.length} 段按源视频时间合成一条视频，约 ${duration.toFixed(1)} 秒。生成成功后会清空；如果生成失败，选择会继续保留。`,
    details: items.map((item, index) => `${index + 1}. ${item.sourceQuery || "检索"} · ${formatTime(item.start)}→${formatTime(item.end)} · ${item.title || "匹配片段"}`),
    confirmLabel: "确认生成合并视频",
  });
  if (!confirmed) return;
  const actionToken = captureJobAction(job);
  actionBusy = true;
  try {
    const { job: updated } = await api(`/api/jobs/${encodeURIComponent(job.id)}/content-search/basket/confirm`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ outputMode: "single_reel", orderMode: "source", subtitleMode: "none", ...acknowledgements }),
    });
    if (!commitJobAction(updated, actionToken)) return;
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) {
    if (!jobActionStillCurrent(actionToken)) return;
    const message = String(error.message || "");
    if (/时间重叠/.test(message) && !acknowledgements.acknowledgeOverlap) {
      const allow = await requestActionConfirmation({ title: "片段时间存在重叠", summary: message, details: ["系统不会静默合并或删除任何已选片段。"], confirmLabel: "保留重叠并生成" });
      if (allow) { actionBusy = false; return confirmContentSelectionBasket(job, { ...acknowledgements, acknowledgeOverlap: true }); }
    }
    if (/尚未证明找全|可能遗漏/.test(message) && !acknowledgements.acknowledgeIncomplete) {
      const allow = await requestActionConfirmation({ title: "检索完整性未确认", summary: message, details: ["只生成已经明确加入待合并片段的内容。"], confirmLabel: "接受可能遗漏并生成" });
      if (allow) { actionBusy = false; return confirmContentSelectionBasket(job, { ...acknowledgements, acknowledgeIncomplete: true }); }
    }
    window.alert(message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

async function reopenCurrentJobForEditing() {
  const hasOutputs = Boolean(
    (currentJob?.outputs || []).length
    || (currentJob?.outputVersions || []).some((version) => (version.outputs || []).length),
  );
  const canReedit = currentJob && (currentJob.status === "completed" || (currentJob.status === "awaiting_confirmation" && hasOutputs));
  if (!canReedit || actionBusy) return;
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/reedit`, { method: "POST" });
    if (!jobActionStillCurrent(actionToken)) return;
    currentOutput = null;
    currentEventGroup = null;
    currentEventSegment = null;
    setDirectorStage("events");
    commitJobAction(job, actionToken);
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

async function cancelCurrentJobReediting() {
  if (!currentJob?.reediting || actionBusy) return;
  const actionToken = captureJobAction();
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/reedit/cancel`, { method: "POST" });
    if (!jobActionStillCurrent(actionToken)) return;
    closeCandidateDrawer();
    commitJobAction(job, actionToken);
  } catch (error) {
    if (jobActionStillCurrent(actionToken)) window.alert(error.message);
  } finally {
    if (jobActionStillCurrent(actionToken)) actionBusy = false;
  }
}

async function confirmEventGroups(groupIds, outputMode = "single_reel", segmentIds = null, subtitleMode = "none", subtitleStyle = "clean") {
  if (!currentJob || currentJob.status !== "awaiting_confirmation" || actionBusy) return;
  if (!groupIds.length) return void window.alert("请至少选择一个事件高光");
  const selected = currentJob.eventGroups.filter((group) => groupIds.includes(group.id)).map((group) => ({
    ...group,
    segments: (group.segments || []).filter((segment) => !segmentIds?.[group.id] || segmentIds[group.id].includes(String(segment.id))),
  })).filter((group) => group.segments.length);
  if (selected.length !== groupIds.length) return void window.alert("每个已选事件至少需要保留一个镜头");
  const total = selected.reduce((sum, group) => sum + group.segments.reduce((inner, segment) => inner + Number(segment.duration || (Number(segment.end) - Number(segment.start)) || 0), 0), 0);
  const target = Number(currentJob.totalTargetSeconds || currentJob.request?.totalTargetSeconds || 0);
  const techniquePolicy = currentJob.brief?.techniquePolicy || currentJob.request?.techniquePolicy || { preset: "auto" };
  let techniquePlan = null;
  try {
    const response = await api(`/api/jobs/${currentJob.id}/technique-plan`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ groupIds, segmentIds, targetSeconds: target || null, orderMode: "selection", techniquePolicy, manualSelection: true }),
    });
    techniquePlan = response.plan;
  } catch (error) {
    return void window.alert(`剪辑手法预检失败：${error.message}`);
  }
  const effectiveTotal = Number(techniquePlan?.effectiveDuration ?? total);
  const outside = techniquePlan?.durationStatus === "over_target" || (target && Math.abs(effectiveTotal - target) > Math.max(4, target * Number(currentJob.durationTolerance || .1)));
  const warning = outside ? `安全精剪后仍为 ${effectiveTotal.toFixed(1)} 秒，超过目标 ${target.toFixed(1)} 秒。系统不会擅自删除你选中的镜头；继续即表示接受本次超时。` : "";
  const segmentCount = selected.reduce((sum, group) => sum + group.segments.length, 0);
  const description = outputMode === "single_reel"
    ? `将把 ${selected.length} 个高光事件、${segmentCount} 个镜头按当前顺序合成为 1 条视频：源片段 ${total.toFixed(1)} 秒，精剪后约 ${effectiveTotal.toFixed(1)} 秒。`
    : `将把 ${selected.length} 个已选事件分别导出为 ${selected.length} 条视频，共 ${segmentCount} 个镜头。`;
  const orderPreview = selected.flatMap((group) => (group.segments || []).map((segment) => `${formatTime(segment.start)}→${formatTime(segment.end)}`)).join("、");
  const orderItems = selected.flatMap((group) => group.segments.map((segment, index) => ({ id: `${group.id}::${segment.id}`, label: `${group.title || "未命名事件"} · 镜头 ${index + 1}`, meta: `${formatTime(segment.start)}→${formatTime(segment.end)}` })));
  const techniqueFacts = (techniquePlan?.segments || []).map((segment, index) => {
    const rate = Number(segment.playbackRate || 1);
    const transition = segment.transitionIn?.type === "fade_black" ? "淡黑" : segment.transitionIn?.type === "dissolve" ? "叠化" : "硬切";
    const bridge = segment.audioBridge?.type === "j_cut" ? "J-cut" : segment.audioBridge?.type === "l_cut" ? "L-cut" : "同步音画";
    return `镜头 ${index + 1} · ${rate.toFixed(rate === 1 ? 0 : 2)}× · ${transition} · ${bridge}`;
  });
  const confirmation = await requestActionConfirmation({ title: outputMode === "single_reel" ? "确认精剪并合成" : "分别导出事件片段", summary: description, details: [`来源：${currentJob.filename || "当前视频"}`, `剪辑策略：${({ auto: "AI 自适应", natural: "自然连贯", tight: "紧凑高光", attraction: "吸引力优先" })[techniquePlan?.techniquePolicy?.preset] || "AI 自适应"}`, `当前排列：${orderPreview || "暂无镜头"}`, ...techniqueFacts.slice(0, 8), ...(techniquePlan?.cutaways?.length ? [`插入镜头：${techniquePlan.cutaways.length} 个（保留主音轨）`] : [])], warning: warning.trim(), orderMode: outputMode === "single_reel" ? "selection" : null, orderItems });
  if (!confirmation) return;
  const orderMode = typeof confirmation === "object" ? confirmation.orderMode : "selection";
  if (typeof confirmation === "object" && confirmation.orderedItems?.length) {
    const orderedGroups = [];
    const orderedSegments = {};
    confirmation.orderedItems.forEach((item) => {
      const [groupId, segmentId] = String(item.id).split("::");
      if (!groupId || !segmentId) return;
      if (!orderedSegments[groupId]) { orderedSegments[groupId] = []; orderedGroups.push(groupId); }
      orderedSegments[groupId].push(segmentId);
    });
    if (orderedGroups.length) { groupIds = orderedGroups; segmentIds = { ...(segmentIds || {}), ...orderedSegments }; }
  }
  if (orderMode === "llm_recommend") {
    requestLlmOrder(currentJob, groupIds, segmentIds);
    return;
  }
  if (orderMode === "ai_plan") {
    setDirectorStage("compose");
    return;
  }
  const actionToken = captureJobAction();
  if (!jobActionStillCurrent(actionToken)) return;
  // Composition is conversational: keep the left AI director visible while
  // rendering and report progress there instead of opening a second form.
  setDirectorStage("conversation");
  actionBusy = true;
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/confirm`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ groupIds, segmentIds, outputMode, subtitleMode, subtitleStyle, subtitleDraftId, orderMode, techniquePolicy, acceptOvertime: Boolean(outside) }),
    });
    currentEventGroup = null;
    currentEventSegment = null;
    if (!commitJobAction(job, actionToken)) return;
    clearTimeout(pollTimer);
    pollJob();
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

async function sendChat(text, contentOptions = null) {
  const value = String(text || chatInput.value).trim();
  if (!currentJob || !value || actionBusy) return;
  const actionToken = captureJobAction();
  if (pendingTimelineSelection && !await confirmPendingTimelineSelection()) return;
  if (!jobActionStillCurrent(actionToken)) return;
  const timelineCompose = chatInput.dataset.timelineCompose === "true";
  const subtitleMode = timelineCompose ? ($("#chatComposeSubtitleMode")?.value || "none") : null;
  const selectedTimelineSelections = timelineChatSelections.map((entry) => ({ ...entry }));
  const uiContext = collectChatUiContext();
  actionBusy = true;
  setComposerSending(true);
  chatInput.value = "";
  timelineChatSelections = [];
  delete chatInput.dataset.timelineCompose;
  ignoredChatContextKeys = new Set();
  renderChatContextBar();
  $("#sendButton").disabled = true;
  activeChatController?.abort();
  const chatController = new AbortController();
  activeChatController = chatController;
  let transientNodes = [];
  let streamNode = null;
  let streamMessage = null;
  let streamText = "";
  const thinkingTimer = window.setTimeout(() => { transientNodes = appendTransientThinking(value); }, 180);
  try {
    const response = await fetch(`/api/jobs/${currentJob.id}/messages/stream`, {
      method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      signal: chatController.signal,
      body: JSON.stringify({
        text: value,
        uiContext,
        ...(subtitleMode ? { subtitleMode } : {}),
        ...(timelineCompose && selectedTimelineSelections.length ? { selections: selectedTimelineSelections } : {}),
        ...(timelineCompose && selectedTimelineSelections.length ? { orderMode: "selection" } : {}),
        ...(contentOptions || {}),
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `请求失败（${response.status}）`);
    }
    if (!response.body) throw new Error("浏览器不支持流式响应");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalResult = null;
    const consume = (block) => {
      const lines = block.split(/\r?\n/);
      const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const dataLine = lines.find((line) => line.startsWith("data:"));
      if (!dataLine) return;
      const data = JSON.parse(dataLine.slice(5).trim() || "{}");
      if (!jobActionStillCurrent(actionToken)) return;
      if (event === "delta") {
        if (!streamNode) {
          transientNodes.forEach((node) => node.remove());
          transientNodes = [];
          const streamingRole = taskModePresentation(currentJob).key === "content_extract" ? "内容探索助手" : "高光发现助手";
          $("#chatMessages").insertAdjacentHTML("beforeend", `<article class="chat-message assistant streaming-answer"><span class="avatar">AI</span><div class="bubble"><small>${streamingRole}</small><p><span class="stream-text-loader" data-generative-loader="text" data-loader-variant="cascade" data-loader-speed="1.15" data-loader-label="AI 正在输出回答"></span></p></div></article>`);
          streamMessage = $("#chatMessages .streaming-answer:last-child");
          streamNode = streamMessage?.querySelector(".stream-text-loader");
        }
        streamText += String(data.text || "");
        if (window.GenerativeLoadersBridge) {
          const rendered = updateGenerativeLoader(streamNode, {
            kind: "text", variant: "cascade", speed: 1.15, text: streamText,
            label: "AI 正在输出回答",
          });
          if (!rendered && streamNode) {
            clearGenerativeLoader(streamNode);
            streamNode.removeAttribute("data-generative-loader");
            streamNode.textContent = streamText;
          }
        } else if (streamNode) streamNode.textContent = streamText;
        $("#chatMessages").scrollTop = $("#chatMessages").scrollHeight;
      } else if (event === "done") {
        finalResult = data;
      }
    };
    while (true) {
      const { value: chunk, done } = await reader.read();
      buffer += decoder.decode(chunk || new Uint8Array(), { stream: !done });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || "";
      blocks.forEach(consume);
      if (done) break;
    }
    if (buffer.trim()) consume(buffer);
    if (!finalResult?.job) throw new Error("流式回答未返回完整任务状态");
    if (!jobActionStillCurrent(actionToken)) return;
    if (streamNode) {
      streamNode.dataset.loaderText = streamText;
      clearGenerativeLoader(streamNode, { preserveText: true });
      if (!window.GenerativeLoadersBridge) streamNode.textContent = streamText;
      streamNode.removeAttribute("data-generative-loader");
      streamMessage?.classList.remove("streaming-answer");
    }
    const { action, job } = finalResult;
    if (action === "selection-ready-event" && finalResult.groupIds?.length) {
      // Limit the next confirmation card to the clips just selected on the
      // timeline; the complete event pool remains available for later edits.
      job.pendingSelectionGroupIds = finalResult.groupIds.map(String);
    }
    if (action === "derived") currentOutput = null;
    commitJobAction(job, actionToken);
    clearTimeout(pollTimer);
    if (action === "selection-ready" && Number.isInteger(Number(finalResult.position))) {
      // The user asked to compose a manually selected range. Pause here so
      // the confirmation card can expose manual ordering and LLM ordering;
      // do not silently start rendering with an implicit order.
      actionBusy = false;
      await confirmCandidates([Number(finalResult.position)], "single_reel");
      return;
    }
    if (action === "selection-ready-event" && finalResult.groupIds?.length) {
      actionBusy = false;
      return;
    }
    if (jobNeedsPolling(job)) pollJob();
  } catch (error) {
    if (streamNode && streamText) {
      streamNode.dataset.loaderText = streamText;
      clearGenerativeLoader(streamNode, { preserveText: true });
      if (!window.GenerativeLoadersBridge) streamNode.textContent = streamText;
      streamNode.removeAttribute("data-generative-loader");
      streamMessage?.classList.remove("streaming-answer");
    }
    if (jobActionStillCurrent(actionToken) && error.name !== "AbortError") window.alert(error.message);
  } finally {
    window.clearTimeout(thinkingTimer);
    if (activeChatController === chatController) activeChatController = null;
    transientNodes.forEach((node) => node.remove());
    if (jobActionStillCurrent(actionToken)) {
      actionBusy = false;
      $("#sendButton").disabled = false;
      setComposerSending(false);
      chatInput.focus();
    }
  }
}

async function confirmBrief(job) {
  if (!job || job.status !== "brief_confirmation" || actionBusy) return;
  const brief = collectBriefFromEditor($("#chatMessages"), job.brief || {});
  if (!brief.objective?.trim()) { window.alert("请先填写剪辑目标"); return; }
  const actionToken = captureJobAction(job);
  actionBusy = true;
  try {
    const { job: updated } = await api(`/api/jobs/${actionToken.jobId}/brief/confirm`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ brief, confirmed: true }),
    });
    if (!commitJobAction(updated, actionToken)) return;
    pollJob();
  } catch (error) { if (jobActionStillCurrent(actionToken)) window.alert(error.message); }
  finally { if (jobActionStillCurrent(actionToken)) actionBusy = false; }
}

function briefEditorMarkup(brief = {}, context = "chat") {
  const style = brief.style || {};
  const list = (value) => Array.isArray(value) ? value.join("、") : String(value || "");
  const field = (name) => `${context}-${name}`;
  return `<section class="brief-editor" data-brief-editor>
    <header><div><small>AI 生成 · 可编辑草稿</small><strong>请确认这是不是你真正想剪的内容</strong></div><span>未确认</span></header>
    <div class="brief-editor-grid">
      <label><span>剪辑目标</span><input data-brief-field="objective" id="${field("objective")}" value="${escapeHtml(brief.objective || "事件高光合集")}" placeholder="例如：把人物反应剪成一条高光成片"></label>
      <label><span>目标总时长（秒）</span><input data-brief-field="targetDurationSeconds" id="${field("duration")}" type="number" min="0" step="1" value="${brief.targetDurationSeconds ? Number(brief.targetDurationSeconds) : ""}" placeholder="留空由 AI 推荐"></label>
      <label class="brief-editor-wide"><span>叙事目标</span><textarea data-brief-field="narrativeGoal" id="${field("narrative")}" rows="2" placeholder="希望观众看完后理解什么">${escapeHtml(brief.narrativeGoal || "")}</textarea></label>
      <label><span>重点关注</span><input data-brief-field="focus" id="${field("focus")}" value="${escapeHtml(list(brief.focus))}" placeholder="人物反应、情绪变化"></label>
      <label><span>希望保留</span><input data-brief-field="includeRules" id="${field("include")}" value="${escapeHtml(list(brief.includeRules))}" placeholder="关键事件、完整表达"></label>
      <label><span>排除内容</span><input data-brief-field="excludeRules" id="${field("exclude")}" value="${escapeHtml(list(brief.excludeRules))}" placeholder="重复镜头、片头广告"></label>
      <label><span>剪辑节奏</span><select data-brief-field="pace" id="${field("pace")}"><option value="natural" ${style.pace === "natural" ? "selected" : ""}>自然纪实</option><option value="tight" ${style.pace === "tight" ? "selected" : ""}>紧凑</option><option value="fast" ${style.pace === "fast" ? "selected" : ""}>快节奏</option></select></label>
      <label><span>视觉风格</span><select data-brief-field="tone" id="${field("tone")}"><option value="documentary" ${style.tone === "documentary" ? "selected" : ""}>纪实自然</option><option value="cinematic" ${style.tone === "cinematic" ? "selected" : ""}>电影感</option><option value="emotional" ${style.tone === "emotional" ? "selected" : ""}>情绪优先</option></select></label>
      <label class="brief-editor-wide"><span>剪辑策略</span><select data-brief-field="techniquePreset" id="${field("technique")}"><option value="auto" ${!brief.techniquePolicy?.preset || brief.techniquePolicy?.preset === "auto" ? "selected" : ""}>AI 自适应</option><option value="natural" ${brief.techniquePolicy?.preset === "natural" ? "selected" : ""}>自然连贯</option><option value="tight" ${brief.techniquePolicy?.preset === "tight" ? "selected" : ""}>紧凑高光</option><option value="attraction" ${brief.techniquePolicy?.preset === "attraction" ? "selected" : ""}>吸引力优先</option></select><small>只调整节奏和衔接；不会擅自删除你手动选择的镜头。</small></label>
      <label class="brief-advanced-hidden"><span>字幕策略</span><select data-brief-field="subtitlePreference" id="${field("subtitle")}"><option value="none" ${!brief.subtitlePreference || brief.subtitlePreference === "none" ? "selected" : ""}>不添加字幕</option><option value="ask" ${brief.subtitlePreference === "ask" ? "selected" : ""}>稍后确认</option><option value="burn" ${brief.subtitlePreference === "burn" ? "selected" : ""}>添加字幕</option><option value="custom" ${brief.subtitlePreference && !["ask", "burn", "none"].includes(brief.subtitlePreference) ? "selected" : ""}>自定义</option></select><input class="brief-custom-input ${brief.subtitlePreference && !["ask", "burn", "none"].includes(brief.subtitlePreference) ? "" : "hidden"}" data-brief-custom="subtitlePreference" value="${brief.subtitlePreference && !["ask", "burn", "none"].includes(brief.subtitlePreference) ? escapeHtml(brief.subtitlePreference) : ""}" placeholder="例如：只添加重点对白"></label>
      <label class="brief-advanced-hidden"><span>剪辑方式</span><select data-brief-field="editMode" id="${field("edit")}"><option value="ai_plan" ${!brief.editMode || brief.editMode === "ai_plan" ? "selected" : ""}>AI 智能规划</option><option value="recommend_review" ${brief.editMode === "recommend_review" ? "selected" : ""}>AI 推荐后我审核</option><option value="manual" ${brief.editMode === "manual" ? "selected" : ""}>我手动选择镜头</option><option value="custom" ${brief.editMode && !["ai_plan", "recommend_review", "manual"].includes(brief.editMode) ? "selected" : ""}>自定义</option></select><input class="brief-custom-input ${brief.editMode && !["ai_plan", "recommend_review", "manual"].includes(brief.editMode) ? "" : "hidden"}" data-brief-custom="editMode" value="${brief.editMode && !["ai_plan", "recommend_review", "manual"].includes(brief.editMode) ? escapeHtml(brief.editMode) : ""}" placeholder="例如：先生成 3 个版本"></label>
      <label class="brief-editor-wide brief-advanced-hidden"><span>成片结构</span><select data-brief-field="structure" id="${field("structure")}"><option value="auto" ${!brief.structure || brief.structure === "auto" ? "selected" : ""}>由 AI 根据事件完整性决定</option><option value="hook_story_result" ${brief.structure === "hook_story_result" ? "selected" : ""}>开场 → 发展 → 高潮 → 结尾</option><option value="montage" ${brief.structure === "montage" ? "selected" : ""}>节奏蒙太奇，优先连续精彩瞬间</option><option value="custom" ${brief.structure && !["auto", "hook_story_result", "montage"].includes(brief.structure) ? "selected" : ""}>自定义</option></select><input class="brief-custom-input ${brief.structure && !["auto", "hook_story_result", "montage"].includes(brief.structure) ? "" : "hidden"}" data-brief-custom="structure" value="${brief.structure && !["auto", "hook_story_result", "montage"].includes(brief.structure) ? escapeHtml(brief.structure) : ""}" placeholder="例如：先冲突后解释，最后用人物反应结束"></label>
    </div>
    <p class="brief-editor-hint">用逗号或顿号分隔多个重点。保存只更新草稿，不会开始分析；点击“确认简报并开始分析”后，这些要求会用于高光发现和成片编排。目标时长按单个成片版本计算；素材不足时会明确提示，不会用重复或低价值画面硬凑。</p>
    <div class="brief-editor-actions"><button type="button" class="brief-reset-button" data-brief-reset>恢复 AI 建议</button><button type="button" class="brief-save-button" data-brief-save>保存修改</button><button type="button" class="confirm-brief-button" data-brief-confirm>确认简报并开始分析</button></div>
  </section>`;
}

function collectBriefFromEditor(root, fallback = {}) {
  const value = (name, defaultValue = "") => root?.querySelector(`[data-brief-field="${name}"]`)?.value ?? defaultValue;
  const split = (name) => value(name).split(/[，,、\n]/).map((item) => item.trim()).filter(Boolean);
  const customValue = (name, selected) => selected === "custom" ? (root?.querySelector(`[data-brief-custom="${name}"]`)?.value?.trim() || "ask") : selected;
  const subtitlePreference = customValue("subtitlePreference", value("subtitlePreference", fallback.subtitlePreference || "none"));
  const editMode = customValue("editMode", value("editMode", fallback.editMode || "ai_plan"));
  const structure = customValue("structure", value("structure", fallback.structure || "auto"));
  return { ...fallback, objective: value("objective", fallback.objective || "事件高光合集").trim(), narrativeGoal: value("narrativeGoal", fallback.narrativeGoal || "").trim(), targetDurationSeconds: Number(value("targetDurationSeconds")) || null, focus: split("focus"), includeRules: split("includeRules"), excludeRules: split("excludeRules"), subtitlePreference, editMode, structure, techniquePolicy: { ...(fallback.techniquePolicy || {}), preset: value("techniquePreset", fallback.techniquePolicy?.preset || "auto") }, style: { ...(fallback.style || {}), pace: value("pace", fallback.style?.pace || "natural"), tone: value("tone", fallback.style?.tone || "documentary") } };
}

function bindBriefEditor(job, root) {
  const editor = root?.querySelector("[data-brief-editor]");
  if (!editor) return;
  editor?.querySelectorAll("[data-brief-field]").forEach((select) => select.addEventListener("change", () => {
    const custom = editor.querySelector(`[data-brief-custom="${select.dataset.briefField}"]`);
    if (custom) custom.classList.toggle("hidden", select.value !== "custom");
  }));
  editor.querySelector("[data-brief-confirm]")?.addEventListener("click", () => confirmBrief(job));
  editor.querySelector("[data-brief-save]")?.addEventListener("click", async () => {
    const brief = collectBriefFromEditor(root, job.brief || {});
    if (!brief.objective) { window.alert("请先填写剪辑目标"); return; }
    // Keep the draft local while the current server process is running. This
    // deliberately does not call the confirm endpoint, so saving can never
    // accidentally start VLM analysis.
    renderJob({ ...job, brief, briefStatus: "draft", detail: "需求简报已保存，等待确认" });
  });
  editor.querySelector("[data-brief-reset]")?.addEventListener("click", () => { renderJob({ ...job, brief: job.brief || {} }); });
}

async function cancelCurrentJob() {
  if (!currentJob || !(isActiveJobStatus(currentJob.status) || ["brief_confirmation", "awaiting_confirmation", "awaiting_content_confirmation"].includes(currentJob.status))) return;
  const actionToken = captureJobAction();
  const buttons = [...document.querySelectorAll("[data-inline-cancel], #cancelButton")];
  buttons.forEach((button) => { button.disabled = true; button.textContent = "正在停止…"; });
  try {
    const { job } = await api(`/api/jobs/${actionToken.jobId}/cancel`, { method: "POST" });
    if (!commitJobAction(job, actionToken)) return;
    if (jobNeedsPolling(job)) pollJob();
  } catch (error) {
    buttons.forEach((button) => { button.disabled = false; button.textContent = "停止分析"; });
    showToast(`停止失败：${error.message || error}`, "error");
  }
}

function historyJobStatusText(job) {
  return displayStatusForJob(job).text;
}

async function loadHistory() {
  try {
    const historyList = $("#historyList");
    const keptList = $("#keptList");
    if (!historyList || !keptList) return;
    const [{ jobs }, keptResponse] = await Promise.all([
      api("/api/jobs"),
      lastHealth?.keptLibrary ? api("/api/kept").catch(() => ({ outputs: [] })) : Promise.resolve({ outputs: [] }),
    ]);
    // Restore unfinished and user-action states after a browser refresh. A
    // pending confirmation must not disappear back into the home screen.
    if (!currentJob && !homeNavigationRequested) {
      const savedJobId = storedCurrentJobId();
      const routedJobId = routeJobId();
      const requestedJobId = routedJobId || savedJobId;
      let activeJob = requestedJobId
        ? jobs.find((item) => String(item.id) === String(requestedJobId))
        : jobs.find((item) => ["briefing", "brief_confirmation", "queued", "running", "cancelling", "awaiting_model_decision", "awaiting_confirmation", "awaiting_content_confirmation"].includes(item.status));
      // The history endpoint intentionally returns a bounded list. If the
      // requested task is older than that list, verify it directly instead of
      // silently falling back to another unfinished task.
      if (requestedJobId && !activeJob) {
        const direct = await api(`/api/jobs/${encodeURIComponent(requestedJobId)}`).catch(() => null);
        activeJob = direct?.job || null;
      }
      if (requestedJobId && !activeJob) {
        forgetCurrentJob();
      }
      if (activeJob) {
        const opened = activeJob.id && activeJob.filename
          ? await api(`/api/jobs/${encodeURIComponent(activeJob.id)}`)
          : { job: activeJob };
        // The user may click Home while the restore request is in flight.
        if (!currentJob && !homeNavigationRequested) {
          restoringHistory = true;
          try {
            renderJob(opened.job);
          } finally {
            restoringHistory = false;
          }
          if (jobNeedsPolling(opened.job)) pollJob();
          studio?.classList.remove("home-mode");
          $("#homeView")?.classList.add("hidden");
        }
      }
    }
    historyList.innerHTML = jobs.length ? jobs.map((job) => `
      <article class="history-row"><button type="button" data-history-open="${escapeHtml(job.id)}"><i class="${job.status}"></i><span><strong>${escapeHtml(job.filename)}</strong><small>${escapeHtml(job.detail)}</small></span><b>${historyJobStatusText(job)}</b></button><button type="button" class="history-delete" data-history-delete="${escapeHtml(job.id)}" title="删除任务历史">删除</button></article>`).join("") : '<p class="empty">暂无任务</p>';
    historyList?.querySelectorAll("[data-history-open]").forEach((button) => button.addEventListener("click", async () => {
      const generation = workspaceGeneration;
      const { job } = await api(`/api/jobs/${button.dataset.historyOpen}`);
      if (generation !== workspaceGeneration || homeNavigationRequested) return;
      currentOutput = null;
      renderJob(job);
      $("#historyPanel")?.classList.add("hidden");
      if (jobNeedsPolling(job)) pollJob();
    }));
    historyList?.querySelectorAll("[data-history-delete]").forEach((button) => button.addEventListener("click", () => deleteHistoryJob(button.dataset.historyDelete)));
    const kept = keptResponse.outputs || [];
    keptList.innerHTML = kept.length ? kept.map((item) => `<article class="kept-card">
      <strong>${escapeHtml(item.title)}</strong>
      <small>${escapeHtml(item.sourceFilename || "原任务已删除")} · ${Number(item.duration || 0).toFixed(1)} 秒 · ${(Number(item.sizeBytes || 0) / 1024 / 1024).toFixed(1)} MB</small>
      <div><a href="${escapeHtml(item.videoUrl)}" target="_blank" rel="noopener">播放</a><a class="download" href="${escapeHtml(item.downloadUrl)}">下载</a><button type="button" data-delete-kept data-job-id="${escapeHtml(item.jobId)}" data-filename="${escapeHtml(item.filename)}">删除</button></div>
    </article>`).join("") : '<p class="empty">暂无独立成片副本</p>';
    $("#keptList")?.querySelectorAll("[data-delete-kept]").forEach((button) => button.addEventListener("click", async () => {
      if (!window.confirm(`确定从保留库移除“${button.dataset.filename}”吗？`)) return;
      await api(`/api/kept/${encodeURIComponent(button.dataset.jobId)}/${encodeURIComponent(button.dataset.filename)}`, { method: "DELETE" });
      loadHistory();
    }));
  } catch (error) {
    const historyRoot = $("#historyList");
    if (historyRoot) {
      historyRoot.innerHTML = `<div class="history-load-error"><p class="empty">${escapeHtml(error.message)}</p><button type="button" class="primary history-retry">重新加载</button></div>`;
      historyRoot.querySelector(".history-retry")?.addEventListener("click", loadHistory);
    }
  }
}

async function deleteHistoryJob(jobId) {
  const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`).catch(() => null);
  if (!job?.job) return;
  const status = job.job.status;
  if (isActiveJobStatus(status)) return void window.alert("任务正在运行，请先取消任务后再删除。");
  if (!await requestActionConfirmation({ title: "删除任务历史", summary: `将删除“${job.job.filename || "当前任务"}”及其源文件、分析缓存和任务内成片。`, details: ["此前另存的独立 MP4 副本不会被删除", "删除后无法恢复"] , confirmLabel: "确认删除" })) return;
  try {
    const intent = await api(`/api/jobs/${encodeURIComponent(jobId)}/delete-intent`, { method: "POST" });
    await api(`/api/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision: intent.revision, deleteIntent: intent.deleteIntent }),
    });
    if (currentJob?.id === jobId) resetWorkspace();
    loadHistory();
  } catch (error) { window.alert(error.message); }
}

function switchHistoryTab(tab) {
  const kept = tab === "kept" && Boolean(lastHealth?.keptLibrary);
  $("#historyList")?.classList.toggle("hidden", kept);
  $("#keptList")?.classList.toggle("hidden", !kept);
  document.querySelectorAll("[data-history-tab]").forEach((button) => button.classList.toggle("active", button.dataset.historyTab === (kept ? "kept" : "jobs")));
}

// Task restoration remains available after removing the history/keep UI. It
// is deliberately private to startup and never renders a task list.
async function restoreCurrentJob() {
  if (currentJob || homeNavigationRequested) return;
  const generation = workspaceGeneration;
  const response = await api("/api/jobs").catch(() => ({ jobs: [] }));
  if (generation !== workspaceGeneration || currentJob || homeNavigationRequested) return;
  const jobs = response.jobs || [];
  const savedJobId = storedCurrentJobId();
  const requestedJobId = routeJobId() || savedJobId;
  // Only restore a task when this tab explicitly remembered one.  Falling
  // back to the first unfinished task makes a newly-created workspace jump
  // into an unrelated task after a refresh or a late API response.
  let activeJob = requestedJobId
    ? jobs.find((item) => String(item.id) === String(requestedJobId))
    : null;
  if (requestedJobId && !activeJob) {
    const direct = await api(`/api/jobs/${encodeURIComponent(requestedJobId)}`).catch(() => null);
    activeJob = direct?.job || null;
  }
  if (requestedJobId && !activeJob) {
    // Do not retry a deleted/invalid task id on every refresh.
    forgetCurrentJob();
  }
  if (!activeJob || generation !== workspaceGeneration || homeNavigationRequested) return;
  const opened = await api(`/api/jobs/${encodeURIComponent(activeJob.id)}`).catch(() => ({ job: activeJob }));
  if (currentJob || generation !== workspaceGeneration || homeNavigationRequested) return;
  restoringHistory = true;
  try { renderJob(opened.job); } finally { restoringHistory = false; }
  if (jobNeedsPolling(opened.job)) pollJob();
  studio?.classList.remove("home-mode");
  $("#homeView")?.classList.add("hidden");
}

function jumpToAdjacentMoment(direction) {
  const candidates = [...(currentJob?.candidates || [])].sort((left, right) => Number(left.start) - Number(right.start));
  if (!candidates.length) return;
  const now = timelineAbsoluteTime();
  let candidate;
  if (direction > 0) candidate = candidates.find((item) => Number(item.start) > now + .35) || candidates[0];
  else candidate = [...candidates].reverse().find((item) => Number(item.start) < now - .35) || candidates.at(-1);
  previewCandidate(Number(candidate.index), { showEvidence: false });
}

function adjacentCandidate(direction) {
  const candidates = [...(currentJob?.candidates || [])].sort((left, right) => Number(left.start) - Number(right.start));
  if (!candidates.length) return null;
  const currentIndex = currentCandidate ? candidates.findIndex((item) => Number(item.index) === Number(currentCandidate.index)) : -1;
  const nextIndex = currentIndex < 0 ? (direction > 0 ? 0 : candidates.length - 1) : currentIndex + direction;
  return nextIndex >= 0 && nextIndex < candidates.length ? candidates[nextIndex] : null;
}

function setCandidateChecked(index, checked) {
  const input = document.querySelector(`.candidate-list input[type="checkbox"][value="${CSS.escape(String(index))}"]`)
    || document.querySelector(`.legacy-candidate-row input[type="checkbox"][value="${CSS.escape(String(index))}"]`);
  if (!input) return false;
  input.checked = checked;
  input.closest(".candidate-row,.legacy-candidate-row")?.classList.toggle("excluded", !checked);
  return true;
}

function reviewSelectionKeys() {
  if (!currentJob) return { type: "none", values: [] };
  if (currentJob.eventGroups?.length) {
    return { type: "groups", values: [...document.querySelectorAll(".event-group-check:checked,.rail-event-check:checked")].map((input) => input.value) };
  }
  return { type: "candidates", values: [...document.querySelectorAll(".candidate-list input:checked,.legacy-candidate-row input:checked")].map((input) => Number(input.value)) };
}

function updateReviewSelectionSummary(root = document) {
  const summary = root.querySelector?.("[data-selection-summary]");
  if (!summary) return;
  const groupInputs = [...root.querySelectorAll(".event-group-check:checked,.rail-event-check:checked")];
  const candidateInputs = [...root.querySelectorAll(".candidate-list input:checked,.legacy-candidate-row input:checked")];
  if (groupInputs.length) {
    const selectedGroups = groupInputs.map((input) => currentJob?.eventGroups?.find((group) => String(group.id) === String(input.value))).filter(Boolean);
    const duration = selectedGroups.reduce((sum, group) => sum + Number(group.actualDuration || 0), 0);
    summary.innerHTML = `已选 <b>${selectedGroups.length}</b> 个事件 · 预计 <b>${duration.toFixed(1)} 秒</b>`;
  } else if (candidateInputs.length || root.querySelector(".candidate-list")) {
    const selected = candidateInputs.map((input) => currentJob?.candidates?.find((candidate) => Number(candidate.index) === Number(input.value))).filter(Boolean);
    const duration = selected.reduce((sum, candidate) => sum + Number(candidate.duration || 0), 0);
    summary.innerHTML = `已选 <b>${selected.length}</b> 个镜头 · 预计 <b>${duration.toFixed(1)} 秒</b>`;
  }
}

function normalizeSegmentActionLabels(root = document) {
  root.querySelectorAll?.(".preview-segment").forEach((button) => { button.textContent = "预览"; button.title = "预览镜头"; });
  root.querySelectorAll?.(".move-segment-up").forEach((button) => { button.textContent = "上移"; button.title = "上移镜头"; });
  root.querySelectorAll?.(".move-segment-down").forEach((button) => { button.textContent = "下移"; button.title = "下移镜头"; });
  root.querySelectorAll?.(".move-segment-group").forEach((button) => { button.textContent = "移动"; button.title = "移动到其他事件"; });
  root.querySelectorAll?.(".delete-segment").forEach((button) => { button.textContent = "删除"; button.title = "删除镜头"; });
}

let reviewExclusionsPersistTimer = null;
function persistReviewExclusions() {
  if (!currentJob?.id || !["awaiting_confirmation", "completed"].includes(currentJob.status)) return;
  const actionToken = captureJobAction();
  const jobId = actionToken.jobId;
  const indices = [...locallyExcludedCandidates];
  clearTimeout(reviewExclusionsPersistTimer);
  reviewExclusionsPersistTimer = setTimeout(() => {
    if (!jobActionStillCurrent(actionToken)) return;
    api(`/api/jobs/${jobId}/review-exclusions`, {
      method: "POST",
      body: JSON.stringify({ indices }),
    }).catch(() => {});
  }, 180);
}

function confirmCurrentReviewSelection() {
  const selection = reviewSelectionKeys();
  if (selection.type === "groups") return confirmEventGroups([...new Set(selection.values)], "single_reel");
  if (selection.type === "candidates") return confirmCandidates([...new Set(selection.values)]);
  return null;
}

function excludeCurrentCandidate() {
  if (!currentCandidate || currentJob?.status !== "awaiting_confirmation") return;
  if (setCandidateChecked(currentCandidate.index, false)) {
    locallyExcludedCandidates.add(Number(currentCandidate.index));
    persistReviewExclusions();
    document.querySelector(`[data-candidate-row="${CSS.escape(String(currentCandidate.index))}"]`)?.classList.add("excluded");
    $("#timelineHint").textContent = `已排除候选 ${Number(currentCandidate.index) + 1}；按 N 继续查看下一条`;
  }
}

function renderHomeTaskCard(job) {
  const outputCount = jobOutputCount(job);
  const hasGeneratedOutputs = outputCount > 0;
  const displayStatus = displayStatusForJob(job);
  const status = displayStatus.text;
  const statusClass = `${displayStatus.className}${hasGeneratedOutputs ? " generated" : ""}`;
  const explicitEventCount = Number(job.eventGroupCount || 0);
  const explicitCandidateCount = Number(job.candidateCount || 0);
  const contentMode = String(job.taskMode || "") === "content_extract";
  const isEventJob = !contentMode && (explicitEventCount > 0 || (Array.isArray(job.eventGroups) && job.eventGroups.length > 0));
  const candidateCount = contentMode ? explicitCandidateCount : isEventJob ? (explicitEventCount || job.eventGroups.length) : (explicitCandidateCount || (Array.isArray(job.candidates) ? job.candidates.length : 0));
  const candidateLabel = contentMode ? "个匹配片段" : isEventJob ? "个事件" : "个候选";
  const updated = job.updatedAt ? new Date(job.updatedAt).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "刚刚";
  const width = Number(job.videoInfo?.width || 0);
  const height = Number(job.videoInfo?.height || 0);
  const orientation = width > 0 && height > 0 ? width / height : 16 / 9;
  const orientationClass = orientation > 1.25 ? " landscape" : orientation < .82 ? " portrait" : " square";
  const thumbnailState = String(job.thumbnailStatus || (job.thumbnailReady ? "ready" : "pending"));
  const thumbnailLabel = thumbnailState === "ready" ? "视频封面" : thumbnailState === "failed" ? "封面需要重新生成" : "正在准备视频封面";
  const thumbnailUrl = job.thumbnailUrl || `/api/jobs/${encodeURIComponent(job.id)}/thumbnail`;
  return `<article class="home-task-card" data-home-task="${escapeHtml(job.id)}" tabindex="0" role="link" aria-label="打开任务 ${escapeHtml(job.filename || "未命名任务")}，${escapeHtml(status)}"><div class="home-task-cover${orientationClass}" data-thumbnail-state="${escapeHtml(thumbnailState)}"><span class="home-cover-loader" data-generative-loader="image" data-loader-variant="resolution" data-loader-size="100%" data-loader-radius="10" data-loader-label="${escapeHtml(thumbnailLabel)}"></span><img data-task-thumbnail data-thumbnail-url="${escapeHtml(thumbnailUrl)}" data-thumbnail-status="${escapeHtml(thumbnailState)}" alt="${escapeHtml(job.filename || "视频封面")}" loading="lazy"><button type="button" class="home-thumbnail-retry hidden" data-thumbnail-retry>重新生成</button><span class="home-task-status ${escapeHtml(statusClass)}">${escapeHtml(status)}</span></div><div class="home-task-body"><strong title="${escapeHtml(job.filename || "未命名任务")}">${escapeHtml(job.filename || "未命名任务")}</strong><small>${hasGeneratedOutputs ? `已有${contentMode ? "内容视频" : "成片"} · 可继续调整` : `最近编辑于 ${escapeHtml(updated)}`}</small><div class="home-task-meta"><span>${candidateCount} ${candidateLabel}</span><span>${outputCount} 条${contentMode ? "内容视频" : "输出视频"}</span></div><div class="home-task-actions"><button type="button" class="home-task-delete" data-home-delete="${escapeHtml(job.id)}" title="删除任务">删除任务</button></div></div></article>`;
}

function openNewTaskFromHome() {
  // Switch immediately so a stale panel state can never make the click look
  // inert. Workspace cleanup is best-effort and must not block the upload UI.
  // Keep restoration blocked until the new upload has been submitted. An
  // older /api/jobs request may still resolve after this click; it must not
  // render the previous task over the empty new-task workspace.
  homeNavigationRequested = true;
  studio?.classList.remove("home-mode");
  $("#homeView")?.classList.add("hidden");
  $("#uploadView")?.classList.remove("hidden");
  try {
    resetWorkspace(false, true);
    // Keep this explicit even if a legacy optional panel throws during
    // cleanup; the new-task screen must never retain the previous dialogue.
    initialConversation();
    homeNavigationRequested = true;
  } catch (error) {
    console.warn("Failed to fully reset the workspace before a new task", error);
    initialConversation();
    homeNavigationRequested = true;
    $("#homeView")?.classList.add("hidden");
    $("#uploadView")?.classList.remove("hidden");
  }
}

async function openHomeTask(jobId) {
  if (!jobId || openingHomeTaskId) return;
  invalidateWorkspaceRequests();
  const generation = workspaceGeneration;
  homeNavigationRequested = false;
  openingHomeTaskId = String(jobId);
  try {
    const { job } = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (generation !== workspaceGeneration) return;
    renderJob(job);
    studio?.classList.remove("home-mode");
    $("#homeView")?.classList.add("hidden");
  } catch (error) {
    showToast(`无法打开任务：${error.message || "服务暂时不可用"}`);
  } finally {
    openingHomeTaskId = null;
  }
}

// Use delegation so the initial placeholder card works before /api/jobs
// finishes, and the refreshed card after task loading works identically.
document.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest("[data-home-create]")) {
    event.preventDefault();
    event.stopPropagation();
    openNewTaskFromHome();
    return;
  }
  const card = target?.closest("[data-home-task]");
  if (card && !target.closest("[data-home-delete]")) {
    event.preventDefault();
    event.stopPropagation();
    openHomeTask(card.dataset.homeTask);
  }
});

let staleHomeTasksRefreshTimer = null;

function setHomeThumbnailState(image, state, message = "", retryable = false) {
  const cover = image?.parentElement;
  if (!cover) return;
  const loader = cover.querySelector(".home-cover-loader");
  const retry = cover.querySelector("[data-thumbnail-retry]");
  const loading = state === "pending";
  cover.dataset.thumbnailState = state;
  cover.dataset.thumbnailMessage = message;
  cover.classList.toggle("thumbnail-unavailable", ["failed", "source_missing", "auth_failed", "network_failed"].includes(state));
  image.classList.toggle("ready", state === "ready");
  if (loader) {
    loader.dataset.loaderActive = String(loading);
    loader.classList.toggle("hidden", !loading);
    if (!loading) clearGenerativeLoader(loader);
  }
  if (retry) {
    retry.classList.toggle("hidden", !retryable);
    retry.textContent = state === "failed" ? "重新生成" : "重新检查";
  }
  if (message) cover.setAttribute("title", message);
  else cover.removeAttribute("title");
}

function refreshAfterStaleHomeTask() {
  window.clearTimeout(staleHomeTasksRefreshTimer);
  staleHomeTasksRefreshTimer = window.setTimeout(() => loadHomeTasks(), 300);
}

async function loadHomeTaskThumbnail(image, { forceRetry = false } = {}) {
  const card = image?.closest("[data-home-task]");
  const jobId = card?.dataset.homeTask;
  const url = image?.dataset.thumbnailUrl;
  if (!jobId || !url) return;
  if (image.dataset.thumbnailLoading === "true") return;
  image.dataset.thumbnailLoading = "true";
  const retry = image.parentElement?.querySelector("[data-thumbnail-retry]");
  if (retry) retry.onclick = async (event) => {
    event.preventDefault();
    event.stopPropagation();
    image.dataset.thumbnailLoading = "false";
    try {
      setHomeThumbnailState(image, "pending", "正在重新生成视频封面");
      await api(`/api/jobs/${encodeURIComponent(jobId)}/thumbnail/retry`, { method: "POST" });
      await loadHomeTaskThumbnail(image, { forceRetry: true });
    } catch (error) {
      setHomeThumbnailState(image, error?.code === "thumbnail_source_missing" ? "source_missing" : "failed", error?.message || "封面重新生成失败", error?.code !== "thumbnail_source_missing");
    }
  };

  const initialStatus = forceRetry ? "pending" : String(image.dataset.thumbnailStatus || "pending");
  if (initialStatus === "source_missing") {
    setHomeThumbnailState(image, "source_missing", "源视频已丢失，无法生成封面");
    image.dataset.thumbnailLoading = "false";
    return;
  }
  if (initialStatus === "failed") {
    setHomeThumbnailState(image, "failed", "视频开头没有可解码的非黑画面", true);
    image.dataset.thumbnailLoading = "false";
    return;
  }

  setHomeThumbnailState(image, "pending", "正在查找首个可用画面");
  const delays = [0, 1000, 3000, 10000];
  let lastError = null;
  for (const delay of delays) {
    if (!image.isConnected) break;
    if (delay) await new Promise((resolve) => window.setTimeout(resolve, delay));
    try {
      const blob = await apiBlob(url);
      if (!blob.size || !String(blob.type || "").startsWith("image/")) {
        const invalid = new Error("服务未返回有效的封面图像");
        invalid.code = "thumbnail_invalid_response";
        throw invalid;
      }
      const objectUrl = URL.createObjectURL(blob);
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error("封面图像无法显示"));
        image.src = objectUrl;
      });
      URL.revokeObjectURL(objectUrl);
      setHomeThumbnailState(image, "ready");
      image.dataset.thumbnailLoading = "false";
      return;
    } catch (error) {
      lastError = error;
      if (error?.code === "job_not_found") {
        card.remove();
        refreshAfterStaleHomeTask();
        image.dataset.thumbnailLoading = "false";
        return;
      }
      if (!["thumbnail_pending", "thumbnail_temporary_failure", "network_error"].includes(error?.code)) break;
    }
  }

  const code = lastError?.code || "thumbnail_temporary_failure";
  if (code === "thumbnail_source_missing") {
    setHomeThumbnailState(image, "source_missing", "源视频已丢失，无法生成封面");
  } else if (code === "thumbnail_decode_failed") {
    setHomeThumbnailState(image, "failed", lastError?.message || "视频开头没有可用画面", true);
  } else if (lastError?.status === 401) {
    setHomeThumbnailState(image, "auth_failed", "访问令牌无效，无法读取封面", true);
  } else if (code === "network_error") {
    setHomeThumbnailState(image, "network_failed", "网络暂不可用，封面会在重试后恢复", true);
  } else {
    setHomeThumbnailState(image, "failed", lastError?.message || "封面仍在生成，可稍后重新检查", true);
  }
  image.dataset.thumbnailLoading = "false";
}

async function loadHomeTasks() {
  const grid = $("#homeTaskGrid");
  if (!grid) return;
  try {
    const response = await Promise.race([
      api("/api/jobs"),
      new Promise((_, reject) => window.setTimeout(() => reject(new Error("读取任务列表超时")), 8000)),
    ]);
    const jobs = Array.isArray(response?.jobs) ? response.jobs : [];
    const taskCount = $("#homeTaskCount");
    const assetCount = $("#homeAssetCount");
    const outputCount = $("#homeOutputCount");
    if (taskCount) taskCount.textContent = String(jobs.length);
    if (assetCount) assetCount.textContent = String(jobs.length);
    if (outputCount) outputCount.textContent = String(jobs.reduce((sum, job) => sum + jobOutputCount(job), 0));
    const cards = jobs.map((job) => {
      try { return renderHomeTaskCard(job); } catch (error) { console.error("任务卡渲染失败", job?.id, error); return ""; }
    }).join("");
    grid.innerHTML = `<article class="home-create-card"><button type="button" data-home-create><span>＋</span><strong>创建新任务</strong><small>拖入视频或点击选择素材</small></button><p>AI 会先理解需求，再开始视觉分析。</p></article>${cards || `<div class="home-empty"><strong>还没有可显示的任务</strong><p>创建新任务，让 AI 从真实视频中发现精彩瞬间。</p></div>`}`;
    grid.querySelector("[data-home-create]")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openNewTaskFromHome();
    });
    grid.querySelectorAll("[data-task-thumbnail]").forEach((image) => loadHomeTaskThumbnail(image));
    syncGenerativeLoaders(grid);
    grid.querySelectorAll("[data-home-task]").forEach((card) => {
      const open = async () => {
        await openHomeTask(card.dataset.homeTask);
      };
      card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
    });
    grid.querySelectorAll("[data-home-delete]").forEach((button) => button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await deleteHistoryJob(button.dataset.homeDelete);
      loadHomeTasks();
    }));
  } catch (error) {
    const homeGrid = $("#homeTaskGrid");
    if (homeGrid) homeGrid.innerHTML = `<article class="home-create-card"><button type="button" data-home-create><span>＋</span><strong>创建新任务</strong><small>拖入视频或点击选择素材</small></button><p>最近任务暂时无法读取：${escapeHtml(error.message)}</p></article>`;
  }
}

function resetWorkspace(showHome = true, clearSavedJob = showHome) {
  // Switch the top-level view before any cleanup work.  Cleanup is best-effort
  // because legacy tasks may lack optional DOM/resource data; a missing node
  // must never make the Home button appear inert.
  invalidateWorkspaceRequests();
  homeNavigationRequested = Boolean(showHome);
  if (clearSavedJob) forgetCurrentJob();
  if (showHome) {
    studio?.classList.add("home-mode");
    $("#homeView")?.classList.remove("hidden");
  } else {
    studio?.classList.remove("home-mode");
    $("#homeView")?.classList.add("hidden");
  }
  // Clear the conversation before optional media/timeline cleanup. This
  // makes a new task visually empty even when an older task lacks a legacy
  // DOM node and a later cleanup step has to be skipped.
  initialConversation();
  stopSourcePreviewPolling();
  currentJob = null;
  syncOneOffFinalizeAction(null);
  currentJobRevision = "";
  renderReviewStatus(null);
  renderDirectorTaskSummary(null);
  updateDirectorFlow(null);
  currentOutput = null;
  currentCandidate = null;
  currentEventGroup = null;
  currentEventSegment = null;
  outputAssemblyMode = "single_reel";
  candidatePreviewEnd = null;
  viewerMediaKind = "source";
  waveformJobId = null;
  waveformData = null;
  waveformRetryAt = 0;
  waveformRequestToken += 1;
  timelineAssetsJobId = null;
  timelineAssetsLoadingJobId = null;
  timelineAssets = null;
  timelineAssetsRetryAt = 0;
  timelineTranscript = [];
  transcriptLoadingJobId = null;
  timelineTranscriptJobId = null;
  transcriptRetryAt = 0;
  timelineMediaRenderKey = "";
  waveformRenderKey = "";
  timelineFrameSelectionTime = null;
  browserFallbackAttempts = new Set();
  timelineViewStart = 0;
  timelineViewEnd = 0;
  timelineCoordinateSpace = "output";
  timelineReviewFollow = false;
  boundaryDrag = null;
  timelineRangeDrag = null;
  cancelTimelinePan(null);
  cancelTimelineOverview(null);
  timelineSpaceHeld = false;
  timelineSpaceDidPan = false;
  timelineViewport?.classList.remove("pan-ready", "panning", "manual-select-mode");
  $("#timelineOverview")?.classList.remove("dragging");
  document.body.classList.remove("timeline-panning");
  pendingTimelineSelection = null;
  pendingTimelineOriginal = null;
  timelineManualSelectMode = false;
  document.removeEventListener("pointermove", moveBoundary);
  document.removeEventListener("pointerup", finishBoundaryDrag);
  document.removeEventListener("pointermove", moveTimelineRange);
  document.removeEventListener("pointerup", finishTimelineRange);
  fragmentDownloadBusy = false;
  clearTimeout(reviewExclusionsPersistTimer);
  reviewExclusionsPersistTimer = null;
  uploadForm?.reset();
  const fileLabel = $("#fileLabel");
  if (fileLabel) fileLabel.textContent = "拖入视频，或点击选择";
  $("#uploadView")?.classList.remove("has-source");
  $("#dropZone")?.classList.remove("has-file");
  $("#localPreviewPanel")?.classList.add("hidden");
  localPreviewPanel?.classList.remove("portrait", "square");
  localPreviewPanel?.style.removeProperty("--media-aspect");
  const localPreviewVideo = $("#localPreviewVideo");
  localPreviewVideo?.removeAttribute("src");
  localPreviewVideo?.load();
  if (localPreviewUrl) URL.revokeObjectURL(localPreviewUrl);
  localPreviewUrl = null;
  $("#uploadView")?.classList.remove("hidden");
  $("#reviewView")?.classList.add("hidden");
  $("#reviewView")?.removeAttribute("data-review-layout");
  recommendedReviewLayout = "landscape";
  updateReviewLayoutControls("landscape");
  setDirectorWorkspaceEmpty(true);
  $("#keepButton")?.classList.add("hidden");
  if (chatInput) chatInput.value = "";
  if (chatInput) chatInput.disabled = true;
  const sendButton = $("#sendButton");
  if (sendButton) sendButton.disabled = true;
  setDirectorState("等待素材");
  updateDirectorThinkingOrb(null);
  mainVideo?.removeAttribute("src");
  mainVideoAutoplayToken += 1;
  mainVideo?.load();
  viewerShell?.classList.remove("portrait", "square");
  viewerShell?.style.setProperty("--media-aspect", "1.90476");
  if (viewerShell) viewerShell.dataset.mediaAspect = "16 / 9";
  if (mediaFrame) {
    delete mediaFrame.dataset.fitKey;
    mediaFrame.style.removeProperty("--decoded-media-aspect");
  }
  scheduleMediaFrameFit(true);
  clearPlayerNotice();
  timelinePanel?.classList.add("hidden");
  $("#timelineManualSelectToggle")?.classList.remove("active");
  $("#timelineManualSelectToggle")?.setAttribute("aria-pressed", "false");
  $("#jobStatus")?.classList.add("hidden");
  $(".review-rail")?.classList.remove("pipeline-mode");
  $("#clipSection")?.classList.add("hidden");
  $("#railOutput")?.classList.add("hidden");
  const railTitle = $("#railTitle");
  if (railTitle) railTitle.textContent = "审核结果";
  const railBody = $("#railBody");
  if (railBody) {
    railBody.innerHTML = '<div class="rail-empty"><span class="empty-thinking-orb" data-thinking-orb data-orb-state="shaping" data-orb-size="64" data-orb-theme="light" data-orb-label="等待分析任务"></span><strong>等待分析任务</strong><p>上传素材后，这里会显示事件高光、内部镜头与输出状态。</p></div>';
    syncThinkingOrbs(railBody);
  }
  $("#openCandidateDrawer")?.setAttribute("disabled", "true");
  closeCandidateDrawer();
  updatePlayerChrome();
  initialConversation();
  setDirectorStage("conversation");
  if (showHome) {
    studio?.classList.add("home-mode");
    $("#homeView")?.classList.remove("hidden");
    loadHomeTasks();
  }
}

videoInput.addEventListener("change", () => {
  const file = videoInput.files[0];
  $("#fileLabel").textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB` : "拖入视频，或点击选择";
  if (localPreviewUrl) URL.revokeObjectURL(localPreviewUrl);
  if (file) {
    localPreviewUrl = URL.createObjectURL(file);
    const localVideo = $("#localPreviewVideo");
    localVideo.src = localPreviewUrl;
    autoplayLocalPreview(localVideo);
    $("#localPreviewPanel")?.classList.remove("hidden");
    $("#uploadView")?.classList.add("has-source");
    $("#dropZone")?.classList.add("has-file");
    setDirectorState("等待确认");
    showBriefCard(file);
  } else {
    resetWorkspace();
  }
});

$("#localPreviewVideo").addEventListener("loadedmetadata", (event) => {
  applyMediaAspect(localPreviewPanel, event.currentTarget.videoWidth, event.currentTarget.videoHeight);
  syncContentSearchPreflight({ resetRange: true });
});
[
  [["dragenter", "dragover"], true],
  [["dragleave", "drop"], false],
].forEach(([names, active]) => names.forEach((name) => $("#dropZone")?.addEventListener(name, () => $("#dropZone")?.classList.toggle("dragging", active))));

chatForm.addEventListener("submit", (event) => { event.preventDefault(); sendChat(); });
chatInput.addEventListener("input", updateComposerBeam);
chatInput.addEventListener("focus", updateComposerBeam);
chatInput.addEventListener("blur", updateComposerBeam);
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChat(); }
});
mainVideo.addEventListener("timeupdate", () => {
  updateTimelinePlayhead();
  updatePlayerChrome();
  if (candidatePreviewEnd !== null && mainVideo.currentTime >= candidatePreviewEnd) {
    mainVideo.pause();
    mainVideo.currentTime = Math.max(0, candidatePreviewEnd);
    if (autoAdvanceCandidates && currentCandidate && viewerMediaKind === "candidate") {
      const finishedIndex = Number(currentCandidate.index);
      const next = adjacentCandidate(1);
      candidatePreviewEnd = null;
      if (next) window.setTimeout(() => {
        if (Number(currentCandidate?.index) === finishedIndex && viewerMediaKind === "candidate") previewCandidate(Number(next.index));
      }, 180);
    }
  }
});
mainVideo.addEventListener("loadedmetadata", () => {
  applyMediaAspect(viewerShell, mainVideo.videoWidth, mainVideo.videoHeight);
  mainVideo.style.setProperty("--decoded-media-aspect", `${mainVideo.videoWidth} / ${mainVideo.videoHeight}`);
  clearPlayerNotice();
  updateTimeline();
  updatePlayerChrome();
});
mainVideo.addEventListener("error", () => {
  const code = Number(mainVideo.error?.code || 0);
  const messages = {
    1: "视频加载被中止，请重新加载。",
    2: "读取视频数据失败，请检查网络后重试。",
    3: "浏览器暂时无法解码原始视频；兼容播放版本可能仍在生成。",
    4: "浏览器不支持当前视频编码或尺寸；请等待兼容播放代理生成完成。",
  };
  const browserFallback = [3, 4].includes(code) ? browserFallbackForCurrentMedia() : null;
  if (browserFallback && !browserFallbackAttempts.has(browserFallback.key)) {
    browserFallbackAttempts.add(browserFallback.key);
    showPlayerNotice(browserFallback.label, "正在准备兼容播放版本");
    setMainVideoSource(`${browserFallback.url}?v=${encodeURIComponent(currentJob?.updatedAt || "latest")}`, { force: true });
    mainVideo.load();
    return;
  }
  if (currentJob && ["source", "candidate", "segment"].includes(viewerMediaKind) && currentJob.previewReady && sourcePreviewRetryToken < 1) {
    sourcePreviewRetryToken += 1;
    const retryUrl = `${sourcePreviewUrl(currentJob)}&retry=${Date.now()}`;
    showPlayerNotice("正在切换兼容播放代理并重新加载…", "正在恢复视频预览");
    setMainVideoSource(retryUrl, { force: true });
    mainVideo.load();
    return;
  }
  if (currentJob && ["source", "candidate", "segment"].includes(viewerMediaKind) && !currentJob.previewReady) {
    beginSourcePreviewPolling(currentJob, true);
  }
  const proxyHint = currentJob?.previewPreparing ? " 当前正在后台生成兼容播放版本。" : "";
  showPlayerNotice(`${messages[code] || "浏览器返回了未知媒体错误。"}${proxyHint}`);
});
mainVideo.addEventListener("seeking", updateTimelinePlayhead);
mainVideo.addEventListener("play", () => {
  updatePlayerChrome();
  cancelAnimationFrame(timelineFrame);
  const tick = () => {
    updateTimelinePlayhead();
    if (!mainVideo.paused && !mainVideo.ended) timelineFrame = requestAnimationFrame(tick);
  };
  timelineFrame = requestAnimationFrame(tick);
});
mainVideo.addEventListener("pause", () => {
  playbackRequestToken += 1;
  cancelAnimationFrame(timelineFrame);
  updateTimelinePlayhead();
  updatePlayerChrome();
});
mainVideo.addEventListener("ended", updatePlayerChrome);
mainVideo.addEventListener("click", () => mainVideo.paused ? safePlay() : mainVideo.pause());
$("#playerPlay").addEventListener("click", () => mainVideo.paused ? safePlay() : mainVideo.pause());
$("#playerRetry").addEventListener("click", () => {
  const resumeTime = Number(mainVideo.currentTime || 0);
  const source = mainVideo.currentSrc || mainVideo.src || sourcePreviewUrl();
  clearPlayerNotice();
  mainVideo.addEventListener("loadedmetadata", () => {
    mainVideo.currentTime = Math.min(Math.max(0, mainVideo.duration - .05), resumeTime);
    safePlay();
  }, { once: true });
  setMainVideoSource(source, { force: true });
  mainVideo.load();
});
$("#playerPrevious").addEventListener("click", () => jumpToAdjacentMoment(-1));
$("#playerNext").addEventListener("click", () => jumpToAdjacentMoment(1));
$("#playerMute").addEventListener("click", () => { mainVideo.muted = !mainVideo.muted; updatePlayerChrome(); });
$("#playerVolume").addEventListener("input", (event) => {
  mainVideo.volume = Number(event.currentTarget.value);
  mainVideo.muted = mainVideo.volume === 0;
  updatePlayerChrome();
});
$("#playerSeek").addEventListener("input", (event) => {
  if (!Number.isFinite(mainVideo.duration)) return;
  candidatePreviewEnd = null;
  mainVideo.currentTime = Number(event.currentTarget.value) / 1000 * mainVideo.duration;
});
$("#playerRate").addEventListener("click", (event) => {
  const rates = [.75, 1, 1.25, 1.5, 2];
  const current = rates.indexOf(mainVideo.playbackRate);
  mainVideo.playbackRate = rates[(current + 1) % rates.length];
  event.currentTarget.textContent = `${mainVideo.playbackRate.toFixed(mainVideo.playbackRate % 1 ? 2 : 1)}×`;
});
$("#playerFullscreen").addEventListener("click", async () => {
  const viewerShell = $("#viewerShell");
  if (!viewerShell) return;
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen?.();
    } else {
      await viewerShell.requestFullscreen?.();
    }
  } catch (error) {
    console.warn("无法切换全屏状态", error);
  } finally {
    updatePlayerChrome();
  }
});
document.addEventListener("fullscreenchange", () => {
  updatePlayerChrome();
  scheduleMediaFrameFit(true);
});
document.addEventListener("keydown", (event) => {
  if (event.target.matches("input,textarea,select,button")) return;
  const key = event.key.toLowerCase();
  if (event.code === "Space" && timelinePointerInside) {
    event.preventDefault();
    if (!event.repeat) {
      timelineSpaceHeld = true;
      timelineSpaceDidPan = false;
      timelineViewport?.classList.add("pan-ready");
    }
    return;
  }
  if (event.code === "Space" || key === "k") { event.preventDefault(); $("#playerPlay").click(); return; }
  if (key === "j" || event.key === "ArrowLeft") {
    event.preventDefault();
    mainVideo.currentTime = Math.max(0, (mainVideo.currentTime || 0) - (key === "j" ? 1 : 5));
    updateTimelinePlayhead();
    return;
  }
  if (key === "l" || event.key === "ArrowRight") {
    event.preventDefault();
    mainVideo.currentTime = Math.min(mainVideo.duration || timelineDurationValue(), (mainVideo.currentTime || 0) + (key === "l" ? 1 : 5));
    updateTimelinePlayhead();
    return;
  }
  if (key === "n" || key === "p") {
    event.preventDefault();
    const next = adjacentCandidate(key === "n" ? 1 : -1);
    if (next) previewCandidate(Number(next.index));
    return;
  }
  if (key === "r") {
    event.preventDefault();
    excludeCurrentCandidate();
    return;
  }
  if (key === "a") {
    event.preventDefault();
    autoAdvanceCandidates = !autoAdvanceCandidates;
    $("#timelineHint").textContent = `自动跳转下一段：${autoAdvanceCandidates ? "开" : "关"} · N/P 切换高光 · R 排除 · Enter 确认`;
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    confirmCurrentReviewSelection();
  }
});
document.addEventListener("keyup", (event) => {
  if (event.code !== "Space" || !timelineSpaceHeld) return;
  event.preventDefault();
  const shouldTogglePlayback = !timelineSpaceDidPan && !timelinePanDrag;
  timelineSpaceHeld = false;
  timelineSpaceDidPan = false;
  timelineViewport?.classList.remove("pan-ready");
  if (shouldTogglePlayback) $("#playerPlay")?.click();
});
timelineViewport?.addEventListener("pointerdown", (event) => {
  const trackContent = timelineTrackContent || timelineViewport;
  if (trackContent && event.clientX < trackContent.getBoundingClientRect().left) return;
  const forcePan = event.button === 1 || (event.button === 0 && timelineSpaceHeld);
  if (forcePan) {
    if (timelineCanPan()) beginTimelinePan(event, { allowSeek: false, spaceMode: timelineSpaceHeld });
    return;
  }
  if (event.target.closest(".timeline-handle,.timeline-label,.timeline-clip,.timeline-shot-marker,.timeline-thumbnail,.timeline-selection")) return;
  if (!timelineManualSelectMode && event.button === 0) {
    if (timelineCanPan()) beginTimelinePan(event, { allowSeek: true });
    else beginTimelineRange(event);
    return;
  }
  if (event.button === 0) beginTimelineRange(event);
});
timelineViewport?.addEventListener("pointerenter", () => { timelinePointerInside = true; });
timelineViewport?.addEventListener("pointerleave", () => { timelinePointerInside = false; });
timelineViewport?.addEventListener("auxclick", (event) => { if (event.button === 1) event.preventDefault(); });
timelineViewport?.addEventListener("click", (event) => {
  if (Date.now() >= timelineSuppressClickUntil) return;
  event.preventDefault();
  event.stopImmediatePropagation();
}, true);
$("#timelineManualSelectToggle")?.addEventListener("click", async () => {
  if (!currentJob) return;
  if (!["awaiting_confirmation", "completed"].includes(currentJob.status)) {
    window.alert("请等待视频分析完成后再选择时间段");
    return;
  }
  timelineManualSelectMode = !timelineManualSelectMode;
  const button = $("#timelineManualSelectToggle");
  button?.classList.toggle("active", timelineManualSelectMode);
  button?.setAttribute("aria-pressed", String(timelineManualSelectMode));
  timelineViewport?.classList.toggle("manual-select-mode", timelineManualSelectMode);
  $("#timelineHint").textContent = timelineManualSelectMode
    ? "拖动生成选区，按住空格拖动可平移"
    : timelineCanPan() ? "拖动左右移动，单击定位" : "滚轮放大，单击定位";
  if (timelineManualSelectMode) timelineViewport?.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
$("#timelineSelection .timeline-handle.start")?.addEventListener("pointerdown", (event) => beginBoundaryDrag(event, "start"));
$("#timelineSelection .timeline-handle.end")?.addEventListener("pointerdown", (event) => beginBoundaryDrag(event, "end"));
$("#timelineSelectionPreview")?.addEventListener("click", () => {
  const item = currentJob?.manualSelection;
  if (!item) return;
  showSource();
  seekSourceTime(Number(item.start));
  candidatePreviewEnd = Number(item.end);
  safePlay();
});
$("#timelineSelectionConfirm")?.addEventListener("click", () => { confirmPendingTimelineSelection(); });
$("#timelineSelectionCancel")?.addEventListener("click", cancelPendingTimelineSelection);
$("#timelineSelectionStartInput")?.addEventListener("change", (event) => updatePendingTimelineBoundary("start", event.currentTarget.value));
$("#timelineSelectionEndInput")?.addEventListener("change", (event) => updatePendingTimelineBoundary("end", event.currentTarget.value));
$("#timelineSelectionCompose")?.addEventListener("click", () => {
  const item = currentJob?.manualSelection;
  if (!item) return;
  const startCompose = async () => {
    if (!await confirmPendingTimelineSelection()) return;
    if (chatInput?.dataset.timelineCompose !== "true") fillChatWithTimelineSelection(currentJob.manualSelection);
    sendChat();
  };
  startCompose();
});
function scheduleTimelineResizeRender(force = false) {
  clearTimeout(timelineResizeTimer);
  if (document.body.classList.contains("panel-resizing")) {
    timelineResizeTimer = setTimeout(() => scheduleTimelineResizeRender(true), 120);
    return;
  }
  if (timelineResizeFrame !== null) cancelAnimationFrame(timelineResizeFrame);
  timelineResizeFrame = requestAnimationFrame(() => {
    timelineResizeFrame = null;
    scheduleMediaFrameFit();
    const nextLayoutBounds = (timelineTrackContent || timelineViewport)?.getBoundingClientRect();
    const nextLayoutWidth = Math.round(nextLayoutBounds?.width || 0);
    const nextLayoutHeight = Math.round(nextLayoutBounds?.height || 0);
    if (nextLayoutWidth && (
      Math.abs(nextLayoutWidth - timelineLabelLayoutWidth) > 2
      || Math.abs(nextLayoutHeight - timelineLabelLayoutHeight) > 2
    )) {
      timelineLabelLayoutWidth = nextLayoutWidth;
      timelineLabelLayoutHeight = nextLayoutHeight;
      updateTimeline();
      return;
    }
    drawWaveform(force);
    renderTimelineMediaAssets(force);
  });
}
if (timelineViewport && window.ResizeObserver) {
  const resizeObserver = new ResizeObserver(() => scheduleTimelineResizeRender());
  resizeObserver.observe(timelineViewport);
  if (timelineTrackContent) resizeObserver.observe(timelineTrackContent);
}
$("#timelineZoomIn")?.addEventListener("click", () => zoomTimeline(.5));
$("#timelineZoomOut")?.addEventListener("click", () => zoomTimeline(2));
$("#timelineZoomInReview")?.addEventListener("click", () => zoomTimeline(.5));
$("#timelineZoomOutReview")?.addEventListener("click", () => zoomTimeline(2));
$("#timelineFit")?.addEventListener("click", () => setTimelineView(0, timelineDurationValue()));
$("#timelineFitReview")?.addEventListener("click", () => setTimelineView(0, timelineDurationValue()));
$("#timelineFocusReview")?.addEventListener("click", focusCurrentTimelineReview);
$("#timelineOutputAxis")?.addEventListener("click", () => setTimelineCoordinateSpace("output"));
$("#timelineSourceAxis")?.addEventListener("click", () => setTimelineCoordinateSpace("source"));
$("#timelineLocatePlayhead")?.addEventListener("click", () => {
  const duration = timelineDurationValue();
  if (duration <= 0) return;
  const value = Math.max(0, Math.min(duration, timelineAbsoluteTime()));
  const view = timelineViewRange();
  const span = Math.min(duration, Math.max(30, view.duration));
  setTimelineView(value - span / 2, value + span / 2);
});
$("#timelineWaveMode")?.addEventListener("click", () => {
  timelineVisualMode = "waveform";
  timelineViewport.classList.add("waveform-mode");
  timelineViewport.classList.remove("frame-mode");
  $("#timelineWaveMode")?.classList.add("active");
  $("#timelineFrameMode")?.classList.remove("active");
  drawWaveform();
});
$("#timelineFrameMode")?.addEventListener("click", () => {
  timelineVisualMode = "frames";
  timelineViewport.classList.remove("waveform-mode");
  timelineViewport.classList.add("frame-mode");
  $("#timelineWaveMode")?.classList.remove("active");
  $("#timelineFrameMode")?.classList.add("active");
  drawWaveform(true);
  renderTimelineMediaAssets();
});
$("#timelineCutsToggle")?.addEventListener("click", () => {
  timelineCutsVisible = !timelineCutsVisible;
  saveTimelineLayerPreferences();
  updateTimelineLayerButtons();
  renderTimelineMediaAssets();
});
updateTimelineLayerButtons();
$("#speakerFilter")?.addEventListener("change", (event) => {
  timelineSpeakerFilter = event.target.value || "all";
  updateTimeline();
  if (currentJob) renderConversation(currentJob);
});
$("#timelineOverview")?.addEventListener("pointerdown", beginTimelineOverview);
timelineViewport?.addEventListener("wheel", (event) => {
  const horizontalGesture = Math.abs(event.deltaX) > Math.abs(event.deltaY);
  if (event.shiftKey || horizontalGesture) {
    if (timelineCanPan()) {
      event.preventDefault();
      const view = timelineViewRange();
      const delta = horizontalGesture ? event.deltaX : (event.deltaY || event.deltaX);
      const shift = view.duration * Math.sign(delta) * Math.min(.2, Math.max(.035, Math.abs(delta) / 700));
      setTimelineView(view.start + shift, view.end + shift);
    }
    return;
  }
  event.preventDefault();
  const center = timelineTimeFromPointer(event);
  zoomTimeline(event.deltaY > 0 ? 1.3 : .77, center);
}, { passive: false });
$("#cancelButton")?.addEventListener("click", cancelCurrentJob);
$("#videoViewSelect")?.addEventListener("change", (event) => {
  if (event.target.value === "source") return showSource();
  selectOutput(event.target.value, true);
});
$("#closeEvidenceButton")?.addEventListener("click", () => {
  renderEvidencePlaceholder();
});
$("#addToChatButton")?.addEventListener("click", () => {
  const item = currentEventSegment || currentCandidate || currentJob?.manualSelection;
  if (item) selectTimelineItemForChat(item);
});
$("#homeButton")?.addEventListener("click", () => resetWorkspace(true));
$("#openCandidateDrawer")?.addEventListener("click", openCandidateDrawer);
$("#closeCandidateDrawer")?.addEventListener("click", closeCandidateDrawer);
$("#drawerBackdrop")?.addEventListener("click", closeCandidateDrawer);
function setVisionConnectionStatus(message, tone = "neutral") {
  const node = $("#visionConnectionStatus");
  if (!node) return;
  setGenerativeInlineStatus(node, message, tone, "orbit");
}

function selectedVisionProviderRecord() {
  return visionSettingsState?.providers?.find((item) => item.id === selectedVisionProvider) || null;
}

function renderVisionModelOptions(preferredModel = "") {
  const select = $("#visionModelSelect");
  const count = $("#visionModelCount");
  if (!select) return;
  const record = selectedVisionProviderRecord();
  const models = visionDiscoveredModels.length ? visionDiscoveredModels : (record?.models || []);
  const unique = [];
  const seen = new Set();
  models.forEach((item) => {
    const id = String(item?.id || "").trim();
    if (!id || seen.has(id)) return;
    seen.add(id);
    unique.push({
      id,
      owner: String(item?.owner || ""),
      recommended: Boolean(item?.recommended),
      supportsVideo: item?.supportsVideo === true,
      supportsJson: item?.supportsJson,
      status: String(item?.status || ""),
    });
  });
  const currentModel = preferredModel || record?.model || "";
  if (currentModel && !seen.has(currentModel)) unique.unshift({ id: currentModel, owner: "", recommended: true, current: true });
  if (!unique.length) {
    select.innerHTML = '<option value="">验证连接后显示模型</option>';
    select.disabled = true;
    if (count) count.textContent = "等待验证";
    return;
  }
  const recommended = unique.filter((item) => item.recommended);
  const other = unique.filter((item) => !item.recommended);
  const options = (items) => items.map((item) => {
    const capability = item.supportsVideo ? "图像和视频" : "图像";
    const lifecycle = item.status === "Retiring" ? "，即将下线" : "";
    return `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)}（${capability}${lifecycle}${item.current ? "，当前" : ""}）</option>`;
  }).join("");
  select.innerHTML = `${recommended.length ? `<optgroup label="可用视觉模型">${options(recommended)}</optgroup>` : ""}${other.length ? `<optgroup label="需要注意">${options(other)}</optgroup>` : ""}`;
  select.disabled = false;
  select.value = unique.some((item) => item.id === currentModel) ? currentModel : (recommended[0]?.id || unique[0].id);
  if (count) count.textContent = `${unique.length} 个账号可见模型`;
}

function renderVisionProvider(providerId, { resetDiscovery = true } = {}) {
  const providers = visionSettingsState?.providers || [];
  const record = providers.find((item) => item.id === providerId) || providers[0];
  if (!record) return;
  selectedVisionProvider = record.id;
  if (resetDiscovery) {
    visionDiscoveredModels = [];
    visionVerifiedAt = null;
  }
  $("#visionProviderList")?.querySelectorAll("[data-vision-provider]").forEach((button) => {
    const active = button.dataset.visionProvider === record.id;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const apiKey = $("#visionApiKey");
  if (apiKey) {
    apiKey.value = "";
    apiKey.placeholder = record.keyConfigured ? `已保存 ${record.keyHint}` : "粘贴 API Key";
  }
  const keyHint = $("#visionKeyHint");
  if (keyHint) keyHint.textContent = record.keyConfigured
    ? `已配置 ${record.keyHint}，留空表示继续使用。完整密钥不会回显。`
    : "密钥保存在当前服务实例中，界面不会回显完整内容。";
  const baseUrl = $("#visionBaseUrl");
  if (baseUrl) {
    baseUrl.value = record.baseUrl || "";
    baseUrl.readOnly = !record.baseUrlEditable;
  }
  $("#visionBaseUrlField")?.classList.toggle("fixed", !record.baseUrlEditable);
  const thinking = $("#visionThinkingType");
  if (thinking) {
    thinking.value = record.thinkingType || "";
    thinking.disabled = !record.thinkingSupported;
  }
  const responseFormat = $("#visionResponseFormat");
  if (responseFormat) responseFormat.value = record.responseFormat === "none" ? "none" : "json_object";
  $("#visionManualModelField")?.classList.add("hidden");
  $("#visionModelManual").value = "";
  renderVisionModelOptions(record.model || "");
  setVisionConnectionStatus(record.verifiedAt
    ? `连接已验证，上次验证于 ${new Date(record.verifiedAt).toLocaleString("zh-CN")}`
    : record.keyConfigured ? "密钥已配置，可重新验证并刷新模型列表。" : "填写密钥后验证连接。",
  record.verifiedAt ? "success" : "neutral");
  const summary = $("#visionActiveSummary");
  if (summary) summary.textContent = record.active && record.configured ? `${record.name} / ${record.model}` : "选择服务并完成连接";
}

function renderVisionSettings(state) {
  visionSettingsState = state;
  const list = $("#visionProviderList");
  if (!list) return;
  list.innerHTML = (state.providers || []).map((item) => `<button type="button" role="tab" data-vision-provider="${escapeHtml(item.id)}"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.description)}</small><span>${item.configured ? "已配置" : "未配置"}</span></button>`).join("");
  list.querySelectorAll("[data-vision-provider]").forEach((button) => button.addEventListener("click", () => renderVisionProvider(button.dataset.visionProvider)));
  renderVisionProvider(state.activeProvider || state.providers?.[0]?.id);
}

async function loadVisionSettings() {
  setVisionConnectionStatus("正在读取模型配置。", "loading");
  try {
    renderVisionSettings(await api("/api/settings/vision"));
  } catch (error) {
    setVisionConnectionStatus(error.message, "error");
  }
}

function setVisionSettingsBusy(busy) {
  visionSettingsBusy = busy;
  ["#discoverVisionModels", "#saveVisionSettings"].forEach((selector) => {
    const button = $(selector);
    if (button) button.disabled = busy;
  });
}

async function discoverAvailableVisionModels() {
  if (visionSettingsBusy) return;
  const record = selectedVisionProviderRecord();
  if (!record) return;
  const apiKey = $("#visionApiKey")?.value.trim() || "";
  const baseUrl = $("#visionBaseUrl")?.value.trim() || "";
  if (!apiKey && !record.keyConfigured) return setVisionConnectionStatus("请先填写 API Key。", "error");
  if (!baseUrl) return setVisionConnectionStatus("请先填写接口地址。", "error");
  setVisionSettingsBusy(true);
  setVisionConnectionStatus("正在验证密钥并读取模型列表。", "loading");
  const button = $("#discoverVisionModels");
  if (button) button.textContent = "正在连接";
  try {
    const result = await api("/api/settings/vision/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: record.id, apiKey, baseUrl }),
    });
    visionDiscoveredModels = result.models || [];
    visionVerifiedAt = result.verifiedAt || null;
    renderVisionModelOptions(record.model || "");
    const recommended = visionDiscoveredModels.filter((item) => item.recommended).length;
    setVisionConnectionStatus(`连接成功，读取到 ${visionDiscoveredModels.length} 个账号可见模型，其中 ${recommended} 个优先列为视觉候选；尚未测试实际视觉能力。`, "success");
  } catch (error) {
    visionDiscoveredModels = [];
    visionVerifiedAt = null;
    setVisionConnectionStatus(error.message, "error");
  } finally {
    setVisionSettingsBusy(false);
    if (button) button.textContent = "验证连接并读取列表";
  }
}

async function saveVisionConfiguration(event) {
  event.preventDefault();
  if (visionSettingsBusy) return;
  const record = selectedVisionProviderRecord();
  if (!record) return;
  const apiKey = $("#visionApiKey")?.value.trim() || "";
  const manualVisible = !$("#visionManualModelField")?.classList.contains("hidden");
  const model = manualVisible ? $("#visionModelManual")?.value.trim() : $("#visionModelSelect")?.value.trim();
  const baseUrl = $("#visionBaseUrl")?.value.trim() || "";
  if (apiKey && !visionVerifiedAt && !manualVisible) return setVisionConnectionStatus("新密钥需要先验证连接，或改为手动填写模型 ID。", "error");
  if (!apiKey && !record.keyConfigured) return setVisionConnectionStatus("请填写并验证 API Key。", "error");
  if (!model) return setVisionConnectionStatus("请选择或填写视觉模型。", "error");
  setVisionSettingsBusy(true);
  setVisionConnectionStatus("正在保存配置。", "loading");
  try {
    const state = await api("/api/settings/vision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: record.id,
        apiKey,
        model,
        baseUrl,
        thinkingType: $("#visionThinkingType")?.value || "",
        responseFormat: $("#visionResponseFormat")?.value || "json_object",
        models: visionDiscoveredModels.length ? visionDiscoveredModels : (record.models || []),
        verifiedAt: visionVerifiedAt || record.verifiedAt || null,
      }),
    });
    renderVisionSettings(state);
    setVisionConnectionStatus("配置已保存，新建任务会使用这个视觉模型。", "success");
    showToast("视觉模型配置已保存", "success");
    loadHealth();
  } catch (error) {
    setVisionConnectionStatus(error.message, "error");
  } finally {
    setVisionSettingsBusy(false);
  }
}

function setLlmConnectionStatus(message, tone = "neutral") {
  const node = $("#llmConnectionStatus");
  if (!node) return;
  setGenerativeInlineStatus(node, message, tone, "orbit");
}

function selectedLlmProviderRecord() {
  return llmSettingsState?.providers?.find((item) => item.id === selectedLlmProvider) || null;
}

function renderLlmModelOptions(preferredModel = "") {
  const select = $("#llmModelSelect");
  const count = $("#llmModelCount");
  if (!select) return;
  const record = selectedLlmProviderRecord();
  const models = llmDiscoveredModels.length ? llmDiscoveredModels : (record?.models || []);
  const unique = [];
  const seen = new Set();
  models.forEach((item) => {
    const id = String(item?.id || "").trim();
    if (!id || seen.has(id)) return;
    seen.add(id);
    unique.push({
      id,
      owner: String(item?.owner || ""),
      recommended: Boolean(item?.recommended),
      supportsJson: item?.supportsJson,
      status: String(item?.status || ""),
    });
  });
  const currentModel = preferredModel || record?.model || "";
  if (currentModel && !seen.has(currentModel)) unique.unshift({ id: currentModel, owner: "", recommended: true, current: true });
  if (!unique.length) {
    select.innerHTML = '<option value="">验证连接后显示模型</option>';
    select.disabled = true;
    if (count) count.textContent = "等待验证";
    return;
  }
  const recommended = unique.filter((item) => item.recommended);
  const other = unique.filter((item) => !item.recommended);
  const options = (items) => items.map((item) => {
    const json = item.supportsJson === true ? "，支持 JSON" : "";
    const lifecycle = item.status === "Retiring" ? "，即将下线" : "";
    return `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)}（文本${json}${lifecycle}${item.current ? "，当前" : ""}）</option>`;
  }).join("");
  select.innerHTML = `${recommended.length ? `<optgroup label="推荐用于剪辑规划">${options(recommended)}</optgroup>` : ""}${other.length ? `<optgroup label="其他文本模型">${options(other)}</optgroup>` : ""}`;
  select.disabled = false;
  select.value = unique.some((item) => item.id === currentModel) ? currentModel : (recommended[0]?.id || unique[0].id);
  if (count) count.textContent = `${unique.length} 个账号可见模型`;
}

function renderLlmProvider(providerId, { resetDiscovery = true } = {}) {
  const providers = llmSettingsState?.providers || [];
  const record = providers.find((item) => item.id === providerId) || providers[0];
  if (!record) return;
  selectedLlmProvider = record.id;
  if (resetDiscovery) {
    llmDiscoveredModels = [];
    llmVerifiedAt = null;
  }
  $("#llmProviderList")?.querySelectorAll("[data-llm-provider]").forEach((button) => {
    const active = button.dataset.llmProvider === record.id;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const apiKey = $("#llmApiKey");
  if (apiKey) {
    apiKey.value = "";
    apiKey.placeholder = record.keyConfigured ? `已保存 ${record.keyHint}` : "粘贴 API Key";
  }
  const keyHint = $("#llmKeyHint");
  if (keyHint) keyHint.textContent = record.keyConfigured
    ? `已配置 ${record.keyHint}，留空表示继续使用。完整密钥不会回显。`
    : "密钥保存在当前服务实例中，界面不会回显完整内容。";
  const baseUrl = $("#llmBaseUrl");
  if (baseUrl) {
    baseUrl.value = record.baseUrl || "";
    baseUrl.readOnly = !record.baseUrlEditable;
  }
  $("#llmBaseUrlField")?.classList.toggle("fixed", !record.baseUrlEditable);
  const help = $("#llmBaseUrlHelp");
  if (help) help.textContent = record.protocol === "anthropic" ? "兼容接口填写 Messages API 的服务根地址。" : "兼容接口填写 Chat Completions 的服务根地址。";
  const thinking = $("#llmThinkingType");
  if (thinking) {
    thinking.value = record.thinkingType || "";
    thinking.disabled = !record.thinkingSupported;
  }
  const responseFormat = $("#llmResponseFormat");
  if (responseFormat) {
    responseFormat.value = record.responseFormat === "none" ? "none" : "json_object";
    responseFormat.disabled = record.protocol === "anthropic";
  }
  $("#llmManualModelField")?.classList.add("hidden");
  const manual = $("#llmModelManual");
  if (manual) manual.value = "";
  const manualToggle = $("#toggleManualLlmModel");
  if (manualToggle) manualToggle.textContent = "找不到模型？手动填写模型 ID";
  renderLlmModelOptions(record.model || "");
  setLlmConnectionStatus(record.verifiedAt
    ? `连接已验证，上次验证于 ${new Date(record.verifiedAt).toLocaleString("zh-CN")}`
    : record.keyConfigured ? "密钥已配置，可重新验证并刷新模型列表。" : "填写密钥后验证连接。",
  record.verifiedAt ? "success" : "neutral");
}

function setLlmMode(mode) {
  selectedLlmMode = mode === "independent" ? "independent" : "reuse_vision";
  document.querySelectorAll("[data-llm-mode]").forEach((button) => {
    const active = button.dataset.llmMode === selectedLlmMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-checked", String(active));
  });
  $("#llmIndependentSettings")?.classList.toggle("hidden", selectedLlmMode !== "independent");
  $("#llmReuseNotice")?.classList.toggle("hidden", selectedLlmMode !== "reuse_vision");
  const summary = $("#llmActiveSummary");
  const record = selectedLlmProviderRecord();
  if (summary) summary.textContent = selectedLlmMode === "reuse_vision"
    ? "跟随视觉分析模型"
    : record?.configured ? `${record.name} / ${record.model}` : "选择服务并完成连接";
}

function renderLlmSettings(state) {
  llmSettingsState = state;
  const list = $("#llmProviderList");
  if (!list) return;
  list.innerHTML = (state.providers || []).map((item) => `<button type="button" role="tab" data-llm-provider="${escapeHtml(item.id)}"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.description)}</small><span>${item.configured ? "已配置" : "未配置"}</span></button>`).join("");
  list.querySelectorAll("[data-llm-provider]").forEach((button) => button.addEventListener("click", () => renderLlmProvider(button.dataset.llmProvider)));
  renderLlmProvider(state.activeProvider || state.providers?.[0]?.id);
  setLlmMode(state.reuseVision ? "reuse_vision" : "independent");
}

async function loadLlmSettings() {
  setLlmConnectionStatus("正在读取模型配置。", "loading");
  try {
    renderLlmSettings(await api("/api/settings/llm"));
  } catch (error) {
    setLlmConnectionStatus(error.message, "error");
  }
}

function setLlmSettingsBusy(busy) {
  llmSettingsBusy = busy;
  ["#discoverLlmModels", "#saveLlmSettings"].forEach((selector) => {
    const button = $(selector);
    if (button) button.disabled = busy;
  });
}

async function discoverAvailableLlmModels() {
  if (llmSettingsBusy || selectedLlmMode !== "independent") return;
  const record = selectedLlmProviderRecord();
  if (!record) return;
  const apiKey = $("#llmApiKey")?.value.trim() || "";
  const baseUrl = $("#llmBaseUrl")?.value.trim() || "";
  if (!apiKey && !record.keyConfigured) return setLlmConnectionStatus("请先填写 API Key。", "error");
  if (!baseUrl) return setLlmConnectionStatus("请先填写接口地址。", "error");
  setLlmSettingsBusy(true);
  setLlmConnectionStatus("正在验证密钥并读取文本模型。", "loading");
  const button = $("#discoverLlmModels");
  if (button) button.textContent = "正在连接";
  try {
    const result = await api("/api/settings/llm/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: record.id, apiKey, baseUrl }),
    });
    llmDiscoveredModels = result.models || [];
    llmVerifiedAt = result.verifiedAt || null;
    renderLlmModelOptions(record.model || "");
    setLlmConnectionStatus(`连接成功，读取到 ${llmDiscoveredModels.length} 个账号可见文本模型；尚未测试实际规划能力。`, "success");
  } catch (error) {
    llmDiscoveredModels = [];
    llmVerifiedAt = null;
    setLlmConnectionStatus(error.message, "error");
  } finally {
    setLlmSettingsBusy(false);
    if (button) button.textContent = "验证连接并读取列表";
  }
}

async function saveLlmConfiguration(event) {
  event.preventDefault();
  if (llmSettingsBusy) return;
  if (selectedLlmMode === "reuse_vision") {
    setLlmSettingsBusy(true);
    try {
      renderLlmSettings(await api("/api/settings/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reuseVision: true }),
      }));
      showToast("剪辑规划将复用视觉模型配置", "success");
      loadHealth();
    } catch (error) {
      showToast(error.message);
    } finally {
      setLlmSettingsBusy(false);
    }
    return;
  }
  const record = selectedLlmProviderRecord();
  if (!record) return;
  const apiKey = $("#llmApiKey")?.value.trim() || "";
  const manualVisible = !$("#llmManualModelField")?.classList.contains("hidden");
  const model = manualVisible ? $("#llmModelManual")?.value.trim() : $("#llmModelSelect")?.value.trim();
  const baseUrl = $("#llmBaseUrl")?.value.trim() || "";
  if (apiKey && !llmVerifiedAt && !manualVisible) return setLlmConnectionStatus("新密钥需要先验证连接，或改为手动填写模型 ID。", "error");
  if (!apiKey && !record.keyConfigured) return setLlmConnectionStatus("请填写并验证 API Key。", "error");
  if (!model) return setLlmConnectionStatus("请选择或填写剪辑规划模型。", "error");
  setLlmSettingsBusy(true);
  setLlmConnectionStatus("正在保存配置。", "loading");
  try {
    const state = await api("/api/settings/llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reuseVision: false,
        provider: record.id,
        apiKey,
        model,
        baseUrl,
        thinkingType: $("#llmThinkingType")?.value || "",
        responseFormat: $("#llmResponseFormat")?.value || "none",
        models: llmDiscoveredModels.length ? llmDiscoveredModels : (record.models || []),
        verifiedAt: llmVerifiedAt || record.verifiedAt || null,
      }),
    });
    renderLlmSettings(state);
    setLlmConnectionStatus("配置已保存，新建任务会使用这个剪辑规划模型。", "success");
    showToast("剪辑规划模型配置已保存", "success");
    loadHealth();
  } catch (error) {
    setLlmConnectionStatus(error.message, "error");
  } finally {
    setLlmSettingsBusy(false);
  }
}

function setModelSettingsRole(role) {
  const selected = role === "llm" ? "llm" : "vision";
  document.querySelectorAll("[data-model-role]").forEach((button) => {
    const active = button.dataset.modelRole === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-model-view]").forEach((view) => view.classList.toggle("hidden", view.dataset.modelView !== selected));
}

function openSettings() {
  $("#settingsPanel")?.classList.remove("hidden");
  $("#settingsBackdrop")?.classList.remove("hidden");
  document.body.classList.add("settings-open");
  loadVisionSettings();
  loadLlmSettings();
}

function closeSettings() {
  $("#settingsPanel")?.classList.add("hidden");
  $("#settingsBackdrop")?.classList.add("hidden");
  document.body.classList.remove("settings-open");
}

$("#settingsButton")?.addEventListener("click", openSettings);
$("#engineState")?.addEventListener("click", openSettings);
$("#closeSettings")?.addEventListener("click", closeSettings);
$("#settingsBackdrop")?.addEventListener("click", closeSettings);
$("#discoverVisionModels")?.addEventListener("click", discoverAvailableVisionModels);
$("#visionSettingsForm")?.addEventListener("submit", saveVisionConfiguration);
document.querySelectorAll("[data-model-role]").forEach((button) => button.addEventListener("click", () => setModelSettingsRole(button.dataset.modelRole)));
document.querySelectorAll("[data-llm-mode]").forEach((button) => button.addEventListener("click", () => setLlmMode(button.dataset.llmMode)));
$("#discoverLlmModels")?.addEventListener("click", discoverAvailableLlmModels);
$("#llmSettingsForm")?.addEventListener("submit", saveLlmConfiguration);
$("#toggleVisionKey")?.addEventListener("click", () => {
  const input = $("#visionApiKey");
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
  $("#toggleVisionKey").textContent = input.type === "password" ? "显示" : "隐藏";
});
$("#toggleLlmKey")?.addEventListener("click", () => {
  const input = $("#llmApiKey");
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
  $("#toggleLlmKey").textContent = input.type === "password" ? "显示" : "隐藏";
});
$("#toggleManualVisionModel")?.addEventListener("click", () => {
  const field = $("#visionManualModelField");
  if (!field) return;
  field.classList.toggle("hidden");
  $("#toggleManualVisionModel").textContent = field.classList.contains("hidden") ? "找不到模型？手动填写模型 ID" : "返回模型列表";
  if (!field.classList.contains("hidden")) $("#visionModelManual")?.focus();
});
$("#toggleManualLlmModel")?.addEventListener("click", () => {
  const field = $("#llmManualModelField");
  if (!field) return;
  field.classList.toggle("hidden");
  $("#toggleManualLlmModel").textContent = field.classList.contains("hidden") ? "找不到模型？手动填写模型 ID" : "返回模型列表";
  if (!field.classList.contains("hidden")) $("#llmModelManual")?.focus();
});
$("#visionApiKey")?.addEventListener("input", () => { visionVerifiedAt = null; setVisionConnectionStatus("密钥已修改，请重新验证连接。", "neutral"); });
$("#visionBaseUrl")?.addEventListener("input", () => { visionVerifiedAt = null; setVisionConnectionStatus("接口地址已修改，请重新验证连接。", "neutral"); });
$("#llmApiKey")?.addEventListener("input", () => { llmVerifiedAt = null; setLlmConnectionStatus("密钥已修改，请重新验证连接。", "neutral"); });
$("#llmBaseUrl")?.addEventListener("input", () => { llmVerifiedAt = null; setLlmConnectionStatus("接口地址已修改，请重新验证连接。", "neutral"); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("#settingsPanel")?.classList.contains("hidden")) closeSettings(); });

$("#replaceButton")?.addEventListener("click", () => {
  if (currentCandidate || currentEventSegment) return void deleteTimelineItem();
});

$("#keepButton")?.addEventListener("click", () => {
  if (currentCandidate || currentEventSegment || currentEventGroup) downloadCurrentFragment();
});

async function loadHealth() {
  if (document.hidden) return;
  try {
    const health = await api("/api/health");
    lastHealth = health;
    const visionConfigured = health.visionConfigured ?? health.arkConfigured;
    const visionModel = health.visionModel || health.arkModel;
    const visionProvider = health.visionProviderLabel || "视觉模型接口";
    const llmModel = health.llmModel || "未配置";
    const llmProvider = health.llmUsesVision ? "复用视觉配置" : (health.llmProviderLabel || "剪辑规划接口");
    $("#engineState")?.classList.toggle("offline", !visionConfigured);
    const engineLabel = $("#engineState span");
    if (engineLabel) engineLabel.textContent = visionConfigured ? `视觉 · ${visionModel}　规划 · ${llmModel}` : "视觉模型未配置";
    const settingsModel = $("#settingsModel");
    if (settingsModel) settingsModel.textContent = visionConfigured ? `${visionModel} · ${visionProvider}` : "未配置";
    const settingsBackend = $("#settingsBackend");
    if (settingsBackend) settingsBackend.textContent = visionConfigured ? visionProvider : "未配置";
    const settingsLlm = $("#settingsLlmModel");
    if (settingsLlm) settingsLlm.textContent = health.llmConfigured ? `${llmModel} · ${llmProvider}` : "未配置";
    const settingsFfmpeg = $("#settingsFfmpeg");
    if (settingsFfmpeg) settingsFfmpeg.textContent = health.ffmpeg && health.ffprobe ? "FFmpeg 可用" : "不可用";
    const speechStatus = { ready: "已就绪", preparing: "后台准备中", failed: "准备失败", not_started: "等待准备" }[health.speechModelStatus] || health.speechModelStatus;
    const settingsSpeech = $("#settingsSpeech");
    if (settingsSpeech) settingsSpeech.textContent = `${health.senseVoiceModel || health.speechEngine} · ${speechStatus}`;
    const settingsSpeechDevice = $("#settingsSpeechDevice");
    if (settingsSpeechDevice) settingsSpeechDevice.textContent = health.speechDevice || "自动选择";
  } catch {
    lastHealth = null;
    $("#engineState")?.classList.add("offline");
    const engineLabel = $("#engineState span");
    if (engineLabel) engineLabel.textContent = "服务连接失败";
    ["#settingsModel", "#settingsLlmModel", "#settingsBackend", "#settingsFfmpeg", "#settingsSpeech", "#settingsSpeechDevice"].forEach((selector) => {
      const node = $(selector);
      if (node) node.textContent = selector === "#settingsFfmpeg" ? "未知" : selector === "#settingsSpeechDevice" ? "未知" : "服务连接失败";
    });
  }
}

loadHealth();
setInterval(loadHealth, 15000);
clearInterval(elapsedTicker);
elapsedTicker = setInterval(() => {
  if (currentJob) {
    updateJobElapsedClock(currentJob);
    const inlineElapsed = document.querySelector("[data-inline-elapsed]");
    if (inlineElapsed) {
      inlineElapsed.textContent = processingElapsedLabel(currentJob);
    }
    const etaText = progressEtaText(currentJob, !stageProgressIsDeterminate(currentJob));
    const consoleEta = $("#jobEta");
    const inlineEta = document.querySelector("[data-inline-eta]");
    if (consoleEta) consoleEta.textContent = etaText;
    if (inlineEta) inlineEta.textContent = etaText;
  }
}, 1000);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(pollTimer);
    pollTimer = null;
  } else if (currentJob && jobNeedsPolling(currentJob)) {
    pollJob();
  } else {
    loadHealth();
  }
});
setupDirectorWorkspace();
homeNavigationRequested = false;
// Reset transient DOM state without discarding the last opened task.  The
// history loader below uses that id to restore the same task after refresh.
try {
  resetWorkspace(true, false);
} catch (error) {
  // A legacy optional panel must not abort dashboard initialization.  The
  // home grid is still usable even if one transient workspace node is absent.
  console.error("工作区初始化失败，继续加载主页", error);
  studio?.classList.add("home-mode");
  $("#homeView")?.classList.remove("hidden");
}
homeNavigationRequested = false;
// Load the dashboard independently from task restoration. A restore request
// must never be allowed to prevent the recent-task cards from rendering. Keep
// a delayed retry as a safety net for browsers restoring a cached DOM shell.
window.setTimeout(loadHomeTasks, 0);
window.setTimeout(() => {
  const grid = $("#homeTaskGrid");
  if (grid?.querySelector(".home-loading-card")) loadHomeTasks();
}, 1200);
restoreCurrentJob();
syncThinkingOrbs(document);
syncBorderBeams(document);
updateComposerBeam();
