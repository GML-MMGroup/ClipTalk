(function workspaceController() {
  "use strict";

  const body = document.body;
  const $ = (selector, root = document) => root?.querySelector?.(selector) || null;
  const $$ = (selector, root = document) => root?.querySelectorAll ? [...root.querySelectorAll(selector)] : [];

  const icons = {
    folder: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6.5h6l2 2h9v9.5a2 2 0 0 1-2 2h-15z"/><path d="M3.5 9h17"/></svg>',
    bell: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 16.5h11l-1.2-1.8V10a4.3 4.3 0 0 0-8.6 0v4.7z"/><path d="M10 19a2.2 2.2 0 0 0 4 0"/></svg>',
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="m8.5 12 2.2 2.2 4.8-5"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 8.5V4l-2 2a7.5 7.5 0 1 0 1.2 9"/><path d="M19 4h-4.5"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>',
    play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 9 6-9 6z"/></svg>',
    videoAdd: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="14" height="14" rx="2"/><path d="m17 9 4-2v10l-4-2zM7 12h6M10 9v6"/></svg>',
  };

  const assistantModeIcons = {
    highlight: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.5 2.8c.5 3.3-2.8 4.4-2.8 7.2 0 1.1.7 2 1.8 2.5-.2-2.1 1.4-3.1 2.4-4.5 2.2 1.8 3.6 4.2 3.2 7a6.2 6.2 0 0 1-12.3-.5c0-3.2 1.9-5.7 4.4-7.8-.1 2.2.6 3.5 1.5 4.2.1-3.6 2.9-5 1.8-8.1Z"/></svg>',
    content_search: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.8"/><path d="m15 15 4.5 4.5"/></svg>',
    person_edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.3"/><path d="M5.5 19c.7-4 3-6 6.5-6s5.8 2 6.5 6"/></svg>',
    speaker_edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="9" r="2.7"/><circle cx="16" cy="9" r="2.7"/><path d="M2.8 18c.4-3.3 2.2-5 5.2-5 1.7 0 3 .5 3.9 1.5M21.2 18c-.4-3.3-2.2-5-5.2-5-1.7 0-3 .5-3.9 1.5"/></svg>',
    sparkle: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5c.5 4.7 2.8 7 7.5 7.5-4.7.5-7 2.8-7.5 7.5-.5-4.7-2.8-7-7.5-7.5 4.7-.5 7-2.8 7.5-7.5Z"/><path d="M19 16.5c.2 1.7 1.1 2.6 2.8 2.8-1.7.2-2.6 1.1-2.8 2.7-.2-1.6-1.1-2.5-2.8-2.7 1.7-.2 2.6-1.1 2.8-2.8Z"/></svg>',
  };

  function setText(node, value) {
    if (node && node.textContent !== value) node.textContent = value;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));
  }

  function cleanDisplayText(value, fallback = "") {
    const text = String(value ?? "").trim();
    if (/^(?:|none|null|undefined|nan)$/i.test(text)) return fallback;
    const suffixCleaned = text.replace(/\s*[·｜|:/-]\s*(?:none|null|undefined|nan)\s*$/i, "").trim();
    if (!suffixCleaned) return fallback;
    if (suffixCleaned !== text && /^(?:agent\s*)?审核预览$/i.test(suffixCleaned)) return fallback;
    return suffixCleaned;
  }

  function projectTitle() {
    if ($("#workspace")?.classList.contains("new-task-workbench")) return "新任务";
    const storedTitle = projectPreferences().displayName;
    if (storedTitle) return storedTitle;
    const sourceTitle = cleanDisplayText(window.ClipTalkCurrentJobSnapshot?.()?.filename);
    if (sourceTitle) return sourceTitle;
    const reviewTitle = cleanDisplayText($("#reviewTitle")?.textContent);
    const summaryTitle = cleanDisplayText($("#directorTaskSummary strong")?.textContent);
    if (reviewTitle && !["源视频", "视频预览"].includes(reviewTitle)) return reviewTitle;
    if (summaryTitle && !/等待|创建/.test(summaryTitle)) return summaryTitle;
    return "未命名剪辑任务";
  }

  function projectPreferenceKey() {
    const id = currentJobId();
    return id ? `cliptalk-project-preferences-v1:${id}` : "";
  }

  function projectPreferences() {
    const key = projectPreferenceKey();
    if (!key) return {};
    try {
      const value = JSON.parse(localStorage.getItem(key) || "null");
      return value && typeof value === "object" ? value : {};
    } catch {
      return {};
    }
  }

  function saveProjectPreferences(patch) {
    const key = projectPreferenceKey();
    if (!key) return;
    const next = { ...projectPreferences(), ...patch };
    if (!String(next.displayName || "").trim()) delete next.displayName;
    try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* Optional UI preference. */ }
  }

  function currentJobId() {
    if (typeof window.ClipTalkCurrentJobId === "function") {
      return String(window.ClipTalkCurrentJobId() || "");
    }
    const source = $("#mainVideo")?.currentSrc || $("#mainVideo")?.src || "";
    return decodeURIComponent(source.match(/\/api\/jobs\/([^/]+)/)?.[1] || "");
  }

  function thumbnailUrl() {
    const id = currentJobId();
    return id ? `/api/jobs/${encodeURIComponent(id)}/thumbnail` : "";
  }

  let sourceThumbnailProbeJobId = "";
  let sourceThumbnailProbeTimer = 0;
  let sourceThumbnailReadyJobId = "";
  let sourceThumbnailFailedJobId = "";
  let sourceThumbnailObjectUrl = "";

  function sourceThumbnailState(job) {
    if (!job?.id) return "empty";
    if (sourceThumbnailReadyJobId === String(job.id)) return "ready";
    if (sourceThumbnailFailedJobId === String(job.id)) return "error";
    const status = String(job.thumbnailStatus || "").trim().toLowerCase();
    if (job.thumbnailReady === true || status === "ready") return "ready";
    if (["failed", "error", "source_missing"].includes(status) || job.thumbnailErrorCode) return "error";
    return "loading";
  }

  function clearSourceThumbnailProbe() {
    if (sourceThumbnailProbeTimer) window.clearTimeout(sourceThumbnailProbeTimer);
    sourceThumbnailProbeTimer = 0;
    sourceThumbnailProbeJobId = "";
  }

  function scheduleSourceThumbnailProbe(job, delay = 0) {
    const jobId = String(job?.id || "");
    if (!jobId || sourceThumbnailReadyJobId === jobId || sourceThumbnailFailedJobId === jobId) return;
    if (sourceThumbnailProbeJobId && sourceThumbnailProbeJobId !== jobId) clearSourceThumbnailProbe();
    if (sourceThumbnailProbeTimer || sourceThumbnailProbeJobId === jobId) return;
    sourceThumbnailProbeJobId = jobId;
    sourceThumbnailProbeTimer = window.setTimeout(async () => {
      sourceThumbnailProbeTimer = 0;
      try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/thumbnail`, { credentials: "same-origin" });
        if (!response.ok) {
          if ([404, 409, 425, 429, 503].includes(response.status)) throw new Error("thumbnail_pending");
          sourceThumbnailFailedJobId = jobId;
          sourceThumbnailProbeJobId = "";
          syncMaterialsSummary();
          return;
        }
        const blob = await response.blob();
        if (currentJobId() !== jobId) return;
        if (sourceThumbnailObjectUrl) URL.revokeObjectURL(sourceThumbnailObjectUrl);
        sourceThumbnailObjectUrl = URL.createObjectURL(blob);
        sourceThumbnailReadyJobId = jobId;
        sourceThumbnailFailedJobId = "";
        sourceThumbnailProbeJobId = "";
        syncMaterialsSummary();
      } catch {
        if (currentJobId() !== jobId) return;
        sourceThumbnailProbeJobId = "";
        scheduleSourceThumbnailProbe(job, 1400);
      }
    }, delay);
  }

  function compactDuration(seconds) {
    const value = Number(seconds || 0);
    if (!Number.isFinite(value) || value <= 0) return "";
    const minutes = Math.floor(value / 60);
    const remain = Math.round(value % 60).toString().padStart(2, "0");
    return minutes > 0 ? `${minutes}:${remain}` : `${value.toFixed(1)} 秒`;
  }

  function compactClock(seconds) {
    const value = Number(seconds || 0);
    if (!Number.isFinite(value) || value < 0) return "";
    const minutes = Math.floor(value / 60);
    const remain = Math.floor(value % 60).toString().padStart(2, "0");
    return `${minutes}:${remain}`;
  }

  function segmentRangeLabel(segment = {}) {
    const start = Number(segment.sourceStart ?? segment.start ?? segment.startTime ?? 0);
    const end = Number(segment.sourceEnd ?? segment.end ?? segment.endTime ?? 0);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return "";
    return `${compactClock(start)}–${compactClock(end)}`;
  }

  function currentTimelineAssets() {
    const snapshot = window.ClipTalkTimelineAssetsSnapshot?.();
    return snapshot?.jobId === currentJobId() ? snapshot.assets : null;
  }

  function applyAdoptedSegmentThumbnail(node, segment, assets) {
    if (!node) return;
    const sprite = assets?.sprite || {};
    const items = Array.isArray(sprite.items) ? sprite.items : [];
    const spriteUrl = String(assets?.spriteUrl || assets?.sprite_url || "");
    if (!items.length || !spriteUrl) {
      node.classList.add("is-loading");
      return;
    }
    const start = Number(segment.sourceStart ?? segment.start ?? segment.startTime ?? 0);
    const end = Number(segment.sourceEnd ?? segment.end ?? segment.endTime ?? start);
    const target = start + Math.max(0, end - start) * .5;
    const item = items.reduce((best, current) => (
      Math.abs(Number(current.time) - target) < Math.abs(Number(best.time) - target) ? current : best
    ));
    const columns = Math.max(1, Number(sprite.columns || 1));
    const rows = Math.max(1, Number(sprite.rows || 1));
    node.style.backgroundImage = `url("${spriteUrl.replaceAll('"', "%22")}")`;
    node.style.backgroundSize = `${columns * 100}% ${rows * 100}%`;
    node.style.backgroundPosition = `${columns > 1 ? (Number(item.column || 0) / (columns - 1)) * 100 : 0}% ${rows > 1 ? (Number(item.row || 0) / (rows - 1)) * 100 : 0}%`;
    node.classList.remove("is-loading");
  }

  const legacyLayoutStorageKeys = [
    "cliptalk-compact-workspace-view-v1",
    "vlm-highlight-panel-layout-v5",
    "cliptalk-review-layout-v1",
    "cliptalk-portrait-video-width-v1",
    "cliptalk-review-workbench-height-v1",
    "cliptalk-evidence-panel-width-v1",
    "cliptalk-secondary-editor-layout-v1",
  ];
  const legacyLayoutMigrationKey = "cliptalk-workbench-v4-legacy-layout-cleared-v1";
  const compactWorkspaceStorageKey = "cliptalk-workbench-v4-compact-view-v1";

  function migrateLegacyLayoutState() {
    try {
      if (localStorage.getItem(legacyLayoutMigrationKey) === "true") return;
      legacyLayoutStorageKeys.forEach((key) => localStorage.removeItem(key));
      localStorage.setItem(legacyLayoutMigrationKey, "true");
    } catch {
      /* Layout persistence is optional; ignore storage failures. */
    }
  }

  function clearLegacyVisualState(workflowKind = "") {
    delete body.dataset.ctRailExpanded;
    const reviewView = $("#reviewView");
    const usesContextualDeck = ["person_edit", "speaker_edit", "highlight"].includes(String(workflowKind));
    if (!usesContextualDeck) {
      reviewView?.classList.remove("lower-panel-deck", "workbench-visible", "workbench-output-mode", "workbench-contextual");
      if (reviewView?.dataset.lowerPanelMode && reviewView.dataset.lowerPanelMode !== "review") {
        reviewView.dataset.lowerPanelMode = "review";
      }
    }
  }

  function compactWorkspaceView() {
    const value = body.dataset.ctCompactView;
    if (["assistant", "preview", "review"].includes(value)) return value;
    try {
      const stored = localStorage.getItem(compactWorkspaceStorageKey);
      if (["assistant", "preview", "review"].includes(stored)) return stored;
    } catch {
      /* Compact view persistence is optional. */
    }
    return "preview";
  }

  function setCompactWorkspaceView(view, { persist = false, focus = false } = {}) {
    const next = ["assistant", "preview", "review"].includes(view) ? view : "preview";
    if (body.dataset.ctCompactView !== next) body.dataset.ctCompactView = next;
    $$("#ctCompactWorkspaceNav [data-ct-compact-view]").forEach((button) => {
      const active = button.dataset.ctCompactView === next;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      if (active && focus) button.focus();
    });
    if (persist) {
      try { localStorage.setItem(compactWorkspaceStorageKey, next); }
      catch { /* Compact view persistence is optional. */ }
    }
  }

  function ensureCompactWorkspaceNav() {
    const nav = $("#ctCompactWorkspaceNav");
    if (!nav) return;
    nav.hidden = window.innerWidth >= 1280;
    nav.inert = nav.hidden;
    if (nav.dataset.ctV4Bound !== "true") {
      nav.dataset.ctV4Bound = "true";
      nav.addEventListener("click", (event) => {
        const button = event.target.closest("[data-ct-compact-view]");
        if (button) setCompactWorkspaceView(button.dataset.ctCompactView, { persist: true });
      });
      nav.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        const buttons = $$("[data-ct-compact-view]", nav);
        if (!buttons.length) return;
        const current = Math.max(0, buttons.indexOf(document.activeElement));
        const index = event.key === "Home" ? 0
          : event.key === "End" ? buttons.length - 1
            : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
        event.preventDefault();
        setCompactWorkspaceView(buttons[index].dataset.ctCompactView, { persist: true, focus: true });
      });
    }
    setCompactWorkspaceView(compactWorkspaceView());
  }

  function ensureWorkbenchTimelinePlaceholder() {
    const reviewView = $("#reviewView");
    const timelinePanel = $("#timelinePanel");
    if (!reviewView || !timelinePanel || $("#ctTimelinePlaceholder")) return;
    const placeholder = document.createElement("section");
    placeholder.id = "ctTimelinePlaceholder";
    placeholder.className = "ct-timeline-placeholder";
    placeholder.dataset.ctV4 = "true";
    placeholder.setAttribute("aria-label", "源视频时间线等待内容");
    placeholder.innerHTML = `
      <header><strong>时间线</strong><span>提交要求后，镜头、声音与文字会在这里展开</span></header>
      <div class="ct-placeholder-ruler"><span>00:00</span><i></i><i></i><i></i><span>源片结束</span></div>
      <div class="ct-placeholder-track picture"><b>画面</b><span data-ct-source-strip><i></i><i></i><i></i><i></i><i></i></span></div>
      <div class="ct-placeholder-track audio"><b>音频</b><span aria-hidden="true"><canvas data-ct-source-waveform></canvas></span></div>
      <div class="ct-placeholder-track subtitle"><b>字幕</b><span><i></i><i></i><i></i></span></div>
      <div class="ct-placeholder-track overlay"><b>封面/文本</b><span><i></i></span></div>
      <em class="ct-placeholder-playhead" aria-hidden="true"></em>`;
    reviewView.insertBefore(placeholder, timelinePanel);
  }

  function ensureTopbar() {
    let bar = $("#ctV4Topbar");
    if (bar) return bar;
    bar = document.createElement("header");
    bar.id = "ctV4Topbar";
    bar.className = "ct-v4-topbar";
    bar.setAttribute("aria-label", "项目工具栏");
    bar.innerHTML = `
      <button class="ct-v4-brand" type="button" data-shell-view="home" aria-label="返回 ClipTalk 首页">
        <img src="/static/assets/cliptalk-director-icon.png?v=20260812-brand-unified-1" alt="" aria-hidden="true">
        <strong>ClipTalk</strong><span>用对话，剪出好视频</span>
      </button>
      <div class="ct-v4-project">
        <span class="ct-v4-project-icon">${icons.folder}</span>
        <i aria-hidden="true"></i>
        <button type="button" id="ctV4ProjectButton" aria-label="切换或管理剪辑任务" title="打开任务列表和任务操作"><b class="sr-only">项目</b><strong id="ctV4ProjectName">未命名剪辑任务</strong><span aria-hidden="true">⌄</span></button>
      </div>
      <div class="ct-v4-global-state">
        <span id="ctV4SaveState" class="ct-v4-save-state">${icons.check}<b>工程已保存</b></span>
        <button id="ctV4Notifications" type="button" aria-label="查看待处理事项" title="待处理事项">${icons.bell}<i class="hidden" aria-hidden="true"></i></button>
      </div>`;
    const workspace = $("#workspace");
    document.body.insertBefore(bar, workspace || document.body.firstChild);
    bar.querySelector("#ctV4ProjectButton")?.addEventListener("click", () => $("#sidebarHistoryToggle")?.click());
    bar.querySelector("#ctV4Notifications")?.addEventListener("click", () => {
      openTaskAttention();
    });
    return bar;
  }

  function ensureRailTabs() {
    const rail = $("#reviewRail");
    if (!rail) return;
    ensureReviewRailToggle(rail);
    let tabs = $("#ctV4RailTabs");
    if (!tabs) {
      tabs = document.createElement("nav");
      tabs.id = "ctV4RailTabs";
      tabs.className = "ct-v4-rail-tabs";
      tabs.setAttribute("role", "tablist");
      tabs.setAttribute("aria-label", "右侧工作区");
      tabs.innerHTML = `
        <button type="button" role="tab" data-ct-v4-rail="materials" aria-selected="true">素材与结果</button>
        <button type="button" role="tab" data-ct-v4-rail="properties" aria-selected="false" hidden>片段详情</button>
        <button type="button" role="tab" data-ct-v4-rail="project" aria-selected="false">项目设置</button>`;
      const header = rail.querySelector(":scope > .rail-header");
      rail.insertBefore(tabs, header?.nextSibling || rail.firstChild);
      tabs.addEventListener("click", (event) => {
        const button = event.target.closest("[data-ct-v4-rail]");
        if (button) setRailTab(button.dataset.ctV4Rail);
      });
    }
    ensureMaterialsSummary(rail, tabs);
    ensureSelectionBar(rail, tabs);
    ensurePropertiesPanel(rail, tabs);
    ensureEvidencePanelInRail(rail);
    ensureProjectPanel(rail);
  }

  function closeEvidenceDetails({ focus = false } = {}) {
    const returnTab = body.dataset.ctV4EvidenceReturnTab || "materials";
    delete body.dataset.ctV4EvidenceOpen;
    delete body.dataset.ctV4EvidenceReturnTab;
    setRailTab(returnTab);
    syncPropertiesPanel();
    if (focus) $("#ctV4SelectionBar [data-ct-v4-show-evidence]")?.focus({ preventScroll: true });
  }

  function openEvidenceDetails({ load = true } = {}) {
    const evidence = $("#evidencePanel");
    if (!evidence || evidence.classList.contains("evidence-placeholder")) return false;
    syncPropertiesPanel();
    setReviewRailExpanded(true, { persist: true });
    body.dataset.ctV4EvidenceReturnTab = body.dataset.ctV4RailTab || "materials";
    setRailTab("properties");
    body.dataset.ctV4EvidenceOpen = "true";
    syncPropertiesPanel();
    if (load) {
      Promise.resolve(window.ClipTalkLoadSelectedEvidence?.()).catch(() => {
        window.showToast?.("判断依据读取失败，请稍后重试");
      });
    }
    requestAnimationFrame(() => evidence.scrollTo?.({ top: 0, behavior: "smooth" }));
    return true;
  }

  function toggleEvidenceDetails() {
    if (body.dataset.ctV4EvidenceOpen === "true") closeEvidenceDetails();
    else openEvidenceDetails();
  }

  function selectedBoundaryEditorAvailable() {
    const boundary = $("#contentBoundaryEntryButton");
    return Boolean(boundary && !boundary.hidden && !boundary.disabled && !boundary.closest(".hidden"));
  }

  function openSelectedBoundaryEditor() {
    const boundary = $("#contentBoundaryEntryButton");
    if (selectedBoundaryEditorAvailable()) boundary.click();
    else window.showToast?.("请先在时间轴中选择一个可调整的事件或镜头");
  }

  function ensureSelectionBar(rail, tabs) {
    let bar = $("#ctV4SelectionBar");
    if (!bar) {
      bar = document.createElement("section");
      bar.id = "ctV4SelectionBar";
      bar.className = "ct-v4-selection-bar";
      bar.hidden = true;
      bar.setAttribute("aria-live", "polite");
      bar.innerHTML = `
        <span>已选</span>
        <div class="ct-v4-selection-copy"><strong id="ctV4SelectionTitle">当前时间线项目</strong><small id="ctV4SelectionMeta"></small></div>
        <div class="ct-v4-selection-actions"><button type="button" data-ct-v4-show-evidence>查看判断依据</button><button type="button" data-ct-v4-boundary-shortcut hidden>调整边界</button></div>`;
      bar.querySelector("[data-ct-v4-show-evidence]")?.addEventListener("click", toggleEvidenceDetails);
      bar.querySelector("[data-ct-v4-boundary-shortcut]")?.addEventListener("click", openSelectedBoundaryEditor);
    }
    if (bar.parentElement !== rail || bar.previousElementSibling !== tabs) tabs.insertAdjacentElement("afterend", bar);
  }

  function ensureEvidencePanelInRail(rail) {
    const evidence = $("#evidencePanel");
    const project = $("#ctV4ProjectPanel", rail);
    if (evidence && evidence.parentElement !== rail) rail.insertBefore(evidence, project || null);
    const resizer = $("#reviewEvidenceResizer");
    resizer?.classList.add("ct-v4-retired-evidence-resizer");
    const close = $("#closeEvidenceButton", evidence);
    if (close && close.dataset.ctV4Bound !== "true") {
      close.dataset.ctV4Bound = "true";
      close.setAttribute("aria-label", "收起判断依据");
      close.title = "收起判断依据";
      close.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeEvidenceDetails({ focus: true });
      }, true);
    }
  }

  function reviewRailStorageKey() {
    return `cliptalk-review-rail-expanded:v1:${currentJobId() || "new-task"}`;
  }

  function storedReviewRailPreference() {
    try {
      const value = localStorage.getItem(reviewRailStorageKey());
      return value == null ? null : value === "true";
    } catch {
      return null;
    }
  }

  function storedAssistantPreference() {
    const jobId = currentJobId() || "new-task";
    try {
      const value = localStorage.getItem(`cliptalk-assistant-expanded:v2:${jobId}`);
      return value == null ? null : value === "true";
    } catch {
      return null;
    }
  }

  function portraitDesktopActive() {
    return window.innerWidth >= 1280
      && body.dataset.shellMode === "workspace"
      && $("#reviewView")?.dataset.reviewLayout === "portrait";
  }

  function syncReviewRailToggle() {
    const workspace = $("#workspace");
    const toggle = $("#ctV4ReviewRailToggle");
    if (!workspace || !toggle) return;
    const open = !workspace.classList.contains("review-rail-collapsed");
    const activeTab = body.dataset.ctV4RailTab || "materials";
    const labels = { materials: "结果", properties: "详情", project: "项目" };
    const fullLabels = { materials: "素材与结果", properties: "片段详情", project: "项目设置" };
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "收起右侧面板" : `展开右侧面板，当前为${fullLabels[activeTab] || "素材与结果"}`);
    toggle.title = open ? "收起右侧面板" : `展开${fullLabels[activeTab] || "素材与结果"}`;
    setText(toggle.querySelector("span"), open ? "›" : "‹");
    setText(toggle.querySelector("b"), labels[activeTab] || "结果");
    const hasActivity = Boolean(
      Number.parseInt($("#reviewPanelCandidateCount")?.textContent || "0", 10)
      || $("#clipStrip")?.children.length
      || /待确认|需要|完成|失败/.test(`${$("#reviewStatus")?.textContent || ""} ${$("#directorState")?.textContent || ""}`)
    );
    toggle.classList.toggle("has-activity", hasActivity);
  }

  function setReviewRailExpanded(expanded, { persist = false, coordinate = true } = {}) {
    const workspace = $("#workspace");
    if (!workspace) return;
    const open = Boolean(expanded);
    const wasOpen = !workspace.classList.contains("review-rail-collapsed");
    workspace.classList.toggle("review-rail-collapsed", !open);
    if (persist) {
      try { localStorage.setItem(reviewRailStorageKey(), String(open)); }
      catch { /* Local panel preference is optional. */ }
    }
    if (open && persist && coordinate && window.innerWidth < 1600) {
      window.ClipTalkWorkspacePanels?.setAssistantExpanded?.(false, { persist: true });
    }
    syncReviewRailToggle();
    if (wasOpen !== open) requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }

  function syncPortraitPanels() {
    if (!portraitDesktopActive()) return false;
    const workspace = $("#workspace");
    const assistant = window.ClipTalkWorkspacePanels;
    if (!workspace || !assistant?.setAssistantExpanded) return false;
    const jobKey = currentJobId() || "new-task";
    if (workspace.dataset.portraitPanelsInitialized === jobKey) return true;
    workspace.dataset.portraitPanelsInitialized = jobKey;

    const assistantPreference = storedAssistantPreference();
    const railPreference = storedReviewRailPreference();
    if (assistantPreference !== null || railPreference !== null) {
      const assistantOpen = assistantPreference ?? !workspace.classList.contains("assistant-collapsed");
      let railOpen = railPreference ?? !workspace.classList.contains("review-rail-collapsed");
      if (assistantOpen && railOpen && window.innerWidth < 1600) railOpen = false;
      assistant.setAssistantExpanded(assistantOpen);
      setReviewRailExpanded(railOpen, { coordinate: false });
      return true;
    }

    // Viewing a completed portrait video must not hide the conversation.
    assistant.setAssistantExpanded(true);
    setReviewRailExpanded(false, { coordinate: false });
    return true;
  }

  function openReviewRail(tab = "materials") {
    setRailTab(tab);
    setReviewRailExpanded(true);
    setCompactWorkspaceView("review");
  }

  function ensureReviewRailToggle(rail) {
    let toggle = $("#ctV4ReviewRailToggle");
    if (!toggle) {
      toggle = document.createElement("button");
      toggle.id = "ctV4ReviewRailToggle";
      toggle.className = "ct-v4-review-rail-toggle";
      toggle.type = "button";
      toggle.innerHTML = '<span aria-hidden="true">›</span><b>结果</b><i aria-hidden="true"></i>';
      rail.prepend(toggle);
      toggle.addEventListener("click", () => {
        const workspace = $("#workspace");
        setReviewRailExpanded(workspace?.classList.contains("review-rail-collapsed"), { persist: true });
      });
    }
    const workspace = $("#workspace");
    const jobKey = currentJobId() || "new-task";
    if (workspace && workspace.dataset.ctV4ReviewRailJob !== jobKey) {
      workspace.dataset.ctV4ReviewRailJob = jobKey;
      const stored = storedReviewRailPreference();
      setReviewRailExpanded(stored ?? window.innerWidth >= 1600);
    } else {
      syncReviewRailToggle();
    }
  }

  function ensurePropertiesPanel(rail, tabs) {
    if ($("#ctV4PropertiesPanel")) return;
    const panel = document.createElement("section");
    panel.id = "ctV4PropertiesPanel";
    panel.className = "ct-v4-properties-panel";
    panel.setAttribute("role", "tabpanel");
    panel.innerHTML = `
      <header><small>当前选择</small><strong>片段详情</strong><p>核对当前时间范围、判断依据，并按需调整片段边界。</p></header>
      <article class="ct-v4-property-selection">
        <span id="ctV4PropertyType">未选择</span>
        <div><strong id="ctV4PropertyTitle">选择事件或镜头</strong><small id="ctV4PropertyMeta">选择后显示时间范围和可用操作</small></div>
        <button type="button" data-ct-v4-show-evidence disabled>查看判断依据</button>
      </article>
      <section class="ct-v4-property-actions" hidden>
        <header><strong>当前选择操作</strong><small id="ctV4PropertyAvailability"></small></header>
        <div>
          <button type="button" data-ct-v4-boundary><b>调整时间边界</b><small>精确调整当前选择的源片入点和出点</small></button>
        </div>
      </section>`;
    const evidence = $("#evidencePanel");
    rail.insertBefore(panel, evidence?.parentElement === rail ? evidence : null);
    panel.querySelector("[data-ct-v4-show-evidence]")?.addEventListener("click", toggleEvidenceDetails);
    panel.querySelector("[data-ct-v4-boundary]")?.addEventListener("click", openSelectedBoundaryEditor);
  }

  function ensureMaterialsSummary(rail, tabs) {
    if ($("#ctV4MaterialsSummary")) return;
    const section = document.createElement("section");
    section.id = "ctV4MaterialsSummary";
    section.className = "ct-v4-materials-summary";
    section.setAttribute("aria-label", "当前素材与结果概览");
    section.innerHTML = `
      <article class="ct-v4-context-card ct-v4-source-card">
        <header><span>1</span><strong>当前素材</strong><button type="button" data-ct-v4-replace>${icons.refresh}更换素材</button></header>
        <button type="button" class="ct-v4-source-preview" data-ct-v4-preview-source data-thumbnail-state="empty" aria-label="预览当前源视频">
          <img alt="" decoding="async">
          <span class="ct-v4-source-preview-state" role="status" aria-live="polite"><i aria-hidden="true"></i><b>等待素材</b><small>上传后生成预览缩略图</small></span>
          <em>源视频</em>
        </button>
        <strong id="ctV4SourceName">等待选择素材</strong><small id="ctV4SourceMeta">上传视频后显示媒体信息</small>
        <button type="button" data-ct-source-expand aria-expanded="false">展开素材预览</button>
      </article>
      <article class="ct-v4-context-card ct-v4-candidates-card">
        <header><span>2</span><strong>候选镜头</strong><button type="button" data-ct-v4-open-candidates><em data-ct-v4-candidate-action-label>查看全部</em> <b id="ctV4CandidateCount"></b>${icons.arrow}</button></header>
        <div id="ctV4CandidatePreview" class="ct-v4-candidate-preview"><i></i><i></i><i></i></div>
        <p id="ctV4CandidateState">提交剪辑要求后生成候选镜头</p>
      </article>
      <article class="ct-v4-context-card ct-v4-version-card">
        <header><span>3</span><strong>当前交付</strong><small id="ctV4VersionState">尚未生成</small></header>
        <div class="ct-v4-version-body"><figure class="ct-v4-version-preview is-placeholder"><img alt=""><span>${assistantModeIcons.sparkle}<em>尚无成片</em></span></figure><div><strong id="ctV4VersionName">等待生成版本</strong><small id="ctV4VersionMeta">确认候选后会保留可审看版本</small></div></div>
        <div id="ctV4DeliveryChecks" class="ct-v4-delivery-checks hidden" aria-label="当前版本交付检查"></div>
        <div class="ct-v4-version-secondary-actions"><button id="ctV4GenerateAspect" class="hidden" type="button">生成画幅审核版本</button><button type="button" data-ct-version-edit>编辑此版本</button></div>
        <footer><button type="button" data-ct-v4-preview-version>${icons.play}<span>播放</span></button><button type="button" data-ct-v4-open-versions aria-label="查看全部版本">全部版本</button></footer>
      </article>
      <section id="ctV4VersionList" hidden aria-label="版本列表"><header><button type="button" data-ct-versions-back>返回概览</button><strong>全部版本</strong></header><div data-ct-versions-host></div></section>`;
    rail.insertBefore(section, tabs.nextSibling);
    section.querySelector("[data-ct-source-expand]").addEventListener("click", (event) => {
      const card = event.currentTarget.closest(".ct-v4-source-card");
      const expanded = card.dataset.expanded !== "true";
      card.dataset.expanded = String(expanded);
      event.currentTarget.setAttribute("aria-expanded", String(expanded));
      event.currentTarget.textContent = expanded ? "收起素材预览" : "展开素材预览";
    });

    section.querySelector("[data-ct-v4-replace]")?.addEventListener("click", () => {
      const input = $("#videoInput");
      if (input && !input.disabled) input.click();
    });
    section.querySelector("[data-ct-v4-preview-source]")?.addEventListener("click", () => {
      const select = $("#videoViewSelect");
      if (select) {
        select.value = "source";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      $("#mainVideo")?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
    section.querySelector("[data-ct-v4-open-candidates]")?.addEventListener("click", () => {
      const card = $(".ct-v4-candidates-card", section);
      const host = $("#ctV4CandidatePreview", section);
      if (card?.classList.contains("is-adopted") && host) {
        host.dataset.expanded = host.dataset.expanded === "true" ? "false" : "true";
        delete host.dataset.signature;
        syncMaterialsSummary();
        return;
      }
      $("#openCandidateDrawer")?.click();
    });
    section.querySelector("[data-ct-v4-open-versions]")?.addEventListener("click", () => {
      const strip = $("#clipStrip");
      if (strip) $("[data-ct-versions-host]", section).append(strip);
      section.dataset.view = "versions";
      $("#ctV4VersionList").hidden = false;
      $("[data-ct-versions-back]", section).focus();
    });
    section.querySelector("[data-ct-versions-back]")?.addEventListener("click", () => {
      delete section.dataset.view;
      $("#ctV4VersionList").hidden = true;
      $("[data-ct-v4-open-versions]", section).focus();
    });
    section.querySelector("[data-ct-v4-preview-version]")?.addEventListener("click", () => {
      window.ClipTalkVersionAction?.(section.dataset.outputFilename, "preview");
    });
    section.querySelector("[data-ct-version-edit]")?.addEventListener("click", () => {
      Promise.resolve(window.ClipTalkVersionAction?.(section.dataset.outputFilename, "edit"))
        .catch((error) => window.showToast?.(error.message || "无法打开版本编辑"));
    });
    section.querySelector(".ct-v4-version-preview img")?.addEventListener("error", (event) => {
      const image = event.currentTarget;
      const preview = image.closest(".ct-v4-version-preview");
      image.dataset.failedSrc = image.getAttribute("src") || "";
      image.removeAttribute("src");
      image.alt = "";
      preview?.classList.add("is-placeholder");
      setText(preview?.querySelector("em"), "缩略图暂不可用");
    });
    section.querySelector("#ctV4GenerateAspect")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const aspect = String(window.ClipTalkCurrentJobSnapshot?.()?.projectSettings?.outputAspect || "source");
      button.disabled = true;
      try {
        await window.ClipTalkPlanOutputAspect?.(aspect, section.dataset.outputFilename, $("#ctV4ReframeFit")?.value || "blur");
      } catch (error) {
        window.showToast?.(error?.message || "画幅版本规划失败");
      } finally {
        button.disabled = false;
      }
    });
    const versionActions = $(".ct-v4-version-secondary-actions", section);
    const coverIntroAction = $("#coverIntroButton");
    if (versionActions && coverIntroAction) versionActions.append(coverIntroAction);
  }

  function ensureProjectPanel(rail) {
    if ($("#ctV4ProjectPanel")) return;
    const panel = document.createElement("section");
    panel.id = "ctV4ProjectPanel";
    panel.className = "ct-v4-project-panel";
    panel.setAttribute("role", "tabpanel");
    panel.innerHTML = `
      <header><small>当前任务</small><strong>项目设置</strong><p>设置任务标识与后续生成采用的成片画幅。</p></header>
      <section class="ct-v4-project-identity"><strong>任务信息</strong><p>本机显示名称只用于区分任务，不会修改源文件名。</p><label><span>本机显示名称</span><input id="ctV4ProjectDisplayName" type="text" maxlength="80" placeholder="输入任务显示名称"></label><dl><div><dt>源文件</dt><dd id="ctV4ProjectSourceName">尚未载入</dd></div><div><dt>媒体信息</dt><dd id="ctV4ProjectSourceMeta">等待读取</dd></div></dl></section>
      <section class="ct-v4-output-aspect"><strong>成片画幅</strong><p>用于后续生成与导出，不改变当前工作区的横向或竖向布局。</p><div class="ct-v4-segmented ct-v4-aspect-options" role="group" aria-label="成片画幅"><button type="button" data-ct-v4-output-aspect="source">跟随源片</button><button type="button" data-ct-v4-output-aspect="16:9">横屏 16:9</button><button type="button" data-ct-v4-output-aspect="9:16">竖屏 9:16</button></div><small id="ctV4OutputAspectStatus" class="ct-v4-setting-status">后续生成将保持源视频画幅。</small></section>`;
    panel.insertAdjacentHTML("beforeend", '<section class="ct-v4-reframe-fit"><label for="ctV4ReframeFit"><span>画幅适配方式</span><select id="ctV4ReframeFit"><option value="blur">完整保留画面 · 虚化背景补边</option><option value="crop">居中裁切填满 · 会裁去边缘</option></select></label><p>生成前会再次确认所选版本与处理方式。</p></section>');
    rail.append(panel);
    panel.addEventListener("click", async (event) => {
      const aspectButton = event.target.closest("[data-ct-v4-output-aspect]");
      if (aspectButton) {
        const buttons = $$("[data-ct-v4-output-aspect]", panel);
        buttons.forEach((button) => { button.disabled = true; });
        try {
          await window.ClipTalkUpdateProjectSettings?.({ outputAspect: aspectButton.dataset.ctV4OutputAspect });
        } catch (error) {
          window.showToast?.(error?.message || "成片画幅保存失败");
        } finally {
          buttons.forEach((button) => { button.disabled = false; });
          syncProjectControls();
        }
        return;
      }
    });
    $("#ctV4ProjectDisplayName")?.addEventListener("input", (event) => {
      saveProjectPreferences({ displayName: event.target.value.trim() });
      syncTopbar();
      window.dispatchEvent(new CustomEvent("cliptalk:project-name-changed"));
    });
    $("#ctV4ReframeFit")?.addEventListener("change", async (event) => {
      const select = event.currentTarget;
      select.disabled = true;
      try { await window.ClipTalkUpdateProjectSettings?.({ outputFit: select.value }); }
      catch (error) { window.showToast?.(error.message || "适配方式保存失败"); }
      finally { syncProjectControls(); }
    });
  }

  function ensureAssistantLayout() {
    const assistant = $("#assistantPanel");
    const messages = $("#chatMessages");
    const form = $("#chatForm");
    const picker = $("#quickWorkflowPicker");
    if (!assistant || !messages || !form || !picker) return;

    setText($(".director strong", assistant), "AI 剪辑助手");
    setText($("#ctAgentIntro", assistant), "和我对话，轻松完成视频创作");
    let quickStart = $("#ctV4AssistantQuickStart");
    if (!quickStart) {
      quickStart = document.createElement("section");
      quickStart.id = "ctV4AssistantQuickStart";
      quickStart.className = "ct-v4-assistant-quick-start";
      quickStart.setAttribute("aria-label", "选择处理方式");
      quickStart.innerHTML = '<header><strong>选择处理方式</strong></header>';
      assistant.insertBefore(quickStart, form);
    }
    if (picker.parentElement !== quickStart) quickStart.append(picker);
    quickStart.classList.toggle("hidden", picker.classList.contains("hidden"));

    const pickerHeading = $(":scope > header", picker);
    if (pickerHeading) pickerHeading.setAttribute("aria-hidden", "true");
    $$("[data-workflow-switch]", picker).forEach((card) => {
      const kind = card.dataset.workflowSwitch;
      const thumb = $(".legacy-workflow-thumb", card);
      if (thumb && thumb.dataset.ctV4Icon !== kind) {
        thumb.dataset.ctV4Icon = kind;
        thumb.innerHTML = assistantModeIcons[kind] || assistantModeIcons.sparkle;
      }
    });

    const realMessages = $$(":scope > .chat-message, :scope > .auto-compose-result-card", messages)
      .filter((node) => !node.classList.contains("ct-v4-welcome-message") && getComputedStyle(node).display !== "none");
    let welcome = $(":scope > .ct-v4-welcome-message", messages);
    if (!realMessages.length && currentJobId()) {
      if (!welcome) {
        welcome = document.createElement("article");
        welcome.className = "ct-v4-welcome-message";
        welcome.innerHTML = `<span>${assistantModeIcons.sparkle}</span><div><p>我已读取这段素材。告诉我想保留的内容、目标时长和重点，我会先整理镜头，再把候选结果交给你审核。</p><time>现在</time></div>`;
        messages.prepend(welcome);
      }
    } else {
      welcome?.remove();
    }
  }

  function setRailTab(tab) {
    const next = ["materials", "properties", "project"].includes(tab) ? tab : "materials";
    if (next !== "properties") {
      delete body.dataset.ctV4EvidenceOpen;
      if (body.dataset.ctV4EvidenceReturnTab === next) delete body.dataset.ctV4EvidenceReturnTab;
    }
    body.dataset.ctV4RailTab = next;
    $$("#ctV4RailTabs [data-ct-v4-rail]").forEach((button) => {
      const selected = button.dataset.ctV4Rail === next;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    if (next === "properties") syncPropertiesPanel();
    if (next === "project") syncProjectControls();
    syncReviewRailToggle();
  }

  function syncTopbar() {
    setText($("#ctV4ProjectName"), projectTitle());
    const projectButton = $("#ctV4ProjectButton");
    const creating = $("#workspace")?.classList.contains("new-task-workbench");
    if (projectButton) {
      projectButton.setAttribute("aria-label", creating ? "退出当前草稿并打开任务列表" : "切换剪辑任务");
      projectButton.title = creating ? "退出草稿并打开任务列表" : "打开任务列表";
    }
    const state = $("#ctV4SaveState");
    const editorVisible = $("#secondaryEditor") && !$("#secondaryEditor").classList.contains("hidden");
    const source = editorVisible ? $("#secondaryEditorSaveState")?.dataset.state : "saved";
    let label = editorVisible ? "精剪已保存" : "项目已载入";
    let tone = "saved";
    if (creating) { label = "草稿"; tone = "draft"; }
    else if (source === "error") { label = "保存失败"; tone = "error"; }
    else if (source === "saving") { label = "正在保存"; tone = "saving"; }
    else if (source === "draft") { label = "有未保存修改"; tone = "dirty"; }
    if (state) state.dataset.tone = tone;
    setText(state?.querySelector("b"), label);
    const attention = taskAttentionItems().length > 0;
    const notifications = $("#ctV4Notifications");
    notifications?.querySelector("i")?.classList.toggle("hidden", !attention);
    if (notifications) {
      notifications.disabled = !attention;
      notifications.setAttribute("aria-label", attention ? "查看任务待处理事项" : "当前没有待处理事项");
      notifications.title = attention ? "查看待处理事项" : "当前没有待处理事项";
    }
  }

  function taskAttentionItems() {
    const job = window.ClipTalkCurrentJobSnapshot?.();
    return job?.presentation?.attentionItems || [];
  }

  function openTaskAttention() {
    let dialog = $("#ctTaskAttention");
    if (!dialog) {
      dialog = document.createElement("dialog");
      dialog.id = "ctTaskAttention";
      dialog.className = "ct-task-dialog";
      dialog.setAttribute("aria-label", "待处理事项");
      document.body.append(dialog);
    }
    dialog.replaceChildren();
    const heading = document.createElement("h2");
    heading.textContent = "待处理事项";
    dialog.append(heading);
    const items = taskAttentionItems();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.textContent = "当前没有待处理事项";
      dialog.append(empty);
    }
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.label;
      button.onclick = () => {
        dialog.close();
        if (item.tab) openReviewRail(item.tab);
        else {
          const target = $(item.target) || $("#assistantPanel");
          target?.scrollIntoView({ block: "center", behavior: "smooth" });
          target?.setAttribute("tabindex", "-1");
          target?.focus({ preventScroll: true });
        }
      };
      dialog.append(button);
    }
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "关闭";
    close.onclick = () => dialog.close();
    dialog.append(close);
    if (!dialog.open) dialog.showModal();
  }

  function openDeliveryResult(filename) {
    const job = window.ClipTalkCurrentJobSnapshot?.();
    const entry = (window.ClipTalkOrderedJobOutputs?.(job) || []).find(({ item }) => item.filename === filename);
    if (!entry || entry.item.previewOnly || entry.version?.previewOnly) return;
    const { item, version } = entry;
    let dialog = $("#ctDeliveryResult");
    if (!dialog) {
      dialog = document.createElement("dialog");
      dialog.id = "ctDeliveryResult";
      dialog.className = "ct-task-dialog";
      dialog.setAttribute("aria-label", "导出完成");
      document.body.append(dialog);
    }
    dialog.replaceChildren();
    const heading = document.createElement("h2");
    heading.textContent = "导出完成";
    const identity = document.createElement("p");
    identity.textContent = `${version?.number ? `V${version.number} · ` : ""}${item.displayTitle || item.title || item.filename} · ${compactDuration(item.duration)} · ${item.width || "未知"}×${item.height || "未知"}`;
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    status.textContent = item.kept ? "已长期保留，可从“成片”页面再次下载。" : "正式文件已生成，尚未长期保留。下载保存到本地，入库保留独立副本。";
    dialog.append(heading, identity, status);
    for (const [action, label] of [["export", "下载 MP4"], ["keep", "长期保留"], ["edit", "继续编辑此版本"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = action === "keep" && item.kept ? "已长期保留" : label;
      button.disabled = (action === "keep" && Boolean(item.kept)) || (action === "edit" && !item.segments?.length);
      const capability = { keep: "canKeep", edit: "canEdit", export: "canDownload" }[action];
      button.disabled ||= item.capabilities?.[capability] === false;
      button.title = item.capabilities?.disabledReason?.[action === "export" ? "download" : action] || "";
      button.onclick = async () => {
        if (window.ClipTalkCurrentJobSnapshot?.()?.id !== job.id) {
          dialog.close();
          window.showToast?.("任务已切换，请从当前任务打开交付详情");
          return;
        }
        button.disabled = true;
        try {
          if (action === "edit") dialog.close();
          const result = await window.ClipTalkVersionAction?.(filename, action);
          if (action === "keep") {
            if (!result?.ok) throw new Error(result?.error || "保存未完成，请重试");
            if (window.ClipTalkCurrentJobSnapshot?.()?.id === job.id) openDeliveryResult(filename);
          }
        } catch (error) { status.textContent = error.message || "操作失败，请重试"; }
        finally { if (button.isConnected) button.disabled = false; }
      };
      dialog.append(button);
    }
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "返回工作区";
    close.onclick = () => dialog.close();
    dialog.append(close);
    if (!dialog.open) dialog.showModal();
  }

  function syncTaskJourney() {
    const job = window.ClipTalkCurrentJobSnapshot?.();
    const presentation = job?.presentation || {};
    const key = presentation.key || "home";
    const draftCapability = window.ClipTalkDraftCapabilitySnapshot?.() || {};
    const coverDraft = Boolean(draftCapability.active && draftCapability.optionId === "cover");
    const stages = coverDraft
      ? ["设置封面", "选择方案", "保存封面"]
      : ["素材与要求", "确认方案", "筛选与编排", "审核样片", "生成与交付"];
    const entries = window.ClipTalkOrderedJobOutputs?.(job) || [];
    const hasOutput = entries.length > 0;
    const active = Number.isInteger(presentation.journeyStage) ? Math.max(0, Math.min(stages.length - 1, presentation.journeyStage)) : job ? -1 : 0;
    const activeIndex = Math.max(0, active);
    const visibleStages = [...stages];
    if (!job) visibleStages[0] = "准备素材";
    else if (activeIndex === 0 && !coverDraft) visibleStages[0] = "补充剪辑要求";
    let nav = $("#ctTaskJourney");
    if (!nav) {
      nav = document.createElement("nav");
      nav.id = "ctTaskJourney";
      nav.setAttribute("aria-label", "剪辑流程");
      ($("#assistantPanel > .panel-header") || $("#assistantPanel"))?.append(nav);
    }
    const signature = `${job?.id || ""}:${job?.status || ""}:${key}:${activeIndex}:${hasOutput}:${draftCapability.optionId || ""}:${presentation.journeyDetail || ""}`;
    if (nav.dataset.signature === signature) return;
    const expanded = nav.dataset.expanded === "true";
    nav.dataset.signature = signature;
    nav.replaceChildren();
    nav.classList.toggle("is-new-task", !job);

    const summary = document.createElement("button");
    summary.type = "button";
    summary.className = "ct-journey-summary";
    summary.setAttribute("aria-controls", "ctTaskJourneyDetails");
    summary.setAttribute("aria-label", `查看处理流程，当前第 ${activeIndex + 1}/${stages.length} 步：${visibleStages[activeIndex]}`);
    const summaryCopy = document.createElement("span");
    summaryCopy.className = "ct-journey-summary-copy";
    const summaryStep = document.createElement("small");
    summaryStep.textContent = `${activeIndex + 1} / ${stages.length}`;
    const summaryTitle = document.createElement("strong");
    summaryTitle.textContent = visibleStages[activeIndex];
    summaryCopy.append(summaryStep, summaryTitle);
    const progress = document.createElement("progress");
    progress.max = stages.length;
    progress.value = activeIndex + 1;
    progress.setAttribute("aria-hidden", "true");
    const chevron = document.createElement("span");
    chevron.className = "ct-journey-chevron";
    chevron.setAttribute("aria-hidden", "true");
    chevron.textContent = "⌄";
    summary.append(summaryCopy, progress, chevron);

    const details = document.createElement("div");
    details.id = "ctTaskJourneyDetails";
    details.className = "ct-journey-details";
    const list = document.createElement("ol");
    visibleStages.forEach((label, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${index + 1} ${label}`;
      button.disabled = index > activeIndex;
      button.dataset.state = index < activeIndex ? "complete" : index === activeIndex ? "current" : "upcoming";
      if (index === activeIndex) button.setAttribute("aria-current", "step");
      button.onclick = () => {
        if (!job || index === 0) $("#chatForm")?.scrollIntoView({ block: "center", behavior: "smooth" });
        else if (index >= 3) openReviewRail("materials");
        else {
          $("#agentPlanDock")?.scrollIntoView({ block: "center", behavior: "smooth" });
        }
        nav.dataset.expanded = "false";
        summary.setAttribute("aria-expanded", "false");
        details.hidden = true;
      };
      item.append(button);
      list.append(item);
    });
    const status = document.createElement("p");
    status.textContent = !job
      ? "添加视频并描述需求，顺序不限"
      : activeIndex === 0
        ? "视频已添加，等待剪辑要求"
        : presentation.journeyDetail || "正在同步任务流程";
    details.append(list, status);
    const setExpanded = (next) => {
      nav.dataset.expanded = String(next);
      summary.setAttribute("aria-expanded", String(next));
      details.hidden = !next;
    };
    summary.onclick = () => setExpanded(nav.dataset.expanded !== "true");
    nav.append(summary, details);
    setExpanded(expanded);
  }

  function copyCandidateImages() {
    const host = $("#ctV4CandidatePreview");
    if (!host) return;
    const images = $$("#railBody img, #reviewWorkbench img, #candidateDrawer img")
      .filter((image) => image.currentSrc || image.src)
      .slice(0, 3);
    if (!images.length) {
      if (!host.querySelector("i")) host.innerHTML = "<i></i><i></i><i></i>";
      return;
    }
    const signature = images.map((image) => image.currentSrc || image.src).join("|");
    if (host.dataset.signature === signature) return;
    host.dataset.signature = signature;
    host.replaceChildren(...images.map((image, index) => {
      const copy = document.createElement("img");
      copy.src = image.currentSrc || image.src;
      copy.alt = `候选镜头 ${index + 1}`;
      return copy;
    }));
  }

  function syncMaterialsSummary() {
    const job = window.ClipTalkCurrentJobSnapshot?.();
    const draftCapability = window.ClipTalkDraftCapabilitySnapshot?.() || {};
    const coverDraft = Boolean(draftCapability.active && draftCapability.optionId === "cover");
    body.classList.toggle("ct-cover-draft-mode", coverDraft);
    const sourceTitle = cleanDisplayText(job?.filename, projectTitle());
    setText($("#ctV4SourceName"), sourceTitle);
    const duration = $("#assetDuration")?.textContent?.trim();
    const resolution = $("#assetResolution")?.textContent?.trim();
    setText($("#ctV4SourceMeta"), [duration, resolution].filter((value) => value && !/--/.test(value)).join(" · ") || "源视频已载入");
    const thumb = thumbnailUrl();
    const sourcePreview = $("#ctV4MaterialsSummary .ct-v4-source-preview");
    const sourceImage = sourcePreview?.querySelector("img");
    const sourceState = sourceThumbnailState(job);
    const sourceStateTitle = sourcePreview?.querySelector(".ct-v4-source-preview-state b");
    const sourceStateDetail = sourcePreview?.querySelector(".ct-v4-source-preview-state small");
    if (sourcePreview) sourcePreview.dataset.thumbnailState = sourceState;
    if (sourceState === "ready" && sourceImage && thumb) {
      const resolvedThumb = sourceThumbnailReadyJobId === String(job?.id) && sourceThumbnailObjectUrl
        ? sourceThumbnailObjectUrl
        : thumb;
      if (sourceImage.getAttribute("src") !== resolvedThumb) sourceImage.setAttribute("src", resolvedThumb);
      sourceImage.alt = `${sourceTitle || "当前源视频"}缩略图`;
      setText(sourceStateTitle, "缩略图已生成");
      setText(sourceStateDetail, "点击播放源视频");
    } else {
      sourceImage?.removeAttribute("src");
      if (sourceImage) sourceImage.alt = "";
      if (sourceState === "loading") {
        setText(sourceStateTitle, "正在生成缩略图");
        setText(sourceStateDetail, "完成后会自动显示");
        scheduleSourceThumbnailProbe(job);
      } else if (sourceState === "error") {
        setText(sourceStateTitle, "缩略图暂不可用");
        setText(sourceStateDetail, "仍可点击播放源视频");
      } else {
        setText(sourceStateTitle, "等待素材");
        setText(sourceStateDetail, "上传后生成预览缩略图");
      }
    }

    const outputSnapshot = window.ClipTalkCurrentOutputSnapshot?.() || {};
    const orderedOutputs = window.ClipTalkOrderedJobOutputs?.(job) || [];
    const currentOutput = outputSnapshot.output || null;
    const currentEntry = currentOutput
      ? orderedOutputs.find(({ item }) => String(item?.filename || "") === String(currentOutput.filename || ""))
      : null;
    const selectedEntry = currentEntry || window.ClipTalkSelectedJobOutput?.(job)
      || orderedOutputs.filter(({ item, version }) => !item.previewOnly && !version.previewOnly).at(-1) || orderedOutputs.at(-1) || null;
    const selectedOutput = selectedEntry?.item || currentOutput || null;
    const selectedVersion = selectedEntry?.version || null;
    const summary = $("#ctV4MaterialsSummary");
    if (summary) summary.dataset.outputFilename = selectedOutput?.filename || "";
    summary?.classList.toggle("cover-draft", coverDraft);
    const domVersionCount = $("#clipStrip")?.children.length || Math.max(0, ($("#clipVersionPicker")?.children.length || 1) - 1);
    const versionCount = orderedOutputs.length || domVersionCount;
    const previewOnly = Boolean(
      outputSnapshot.isReviewSample
      || selectedOutput?.previewOnly
      || selectedVersion?.previewOnly
      || String(selectedOutput?.outputKind || "").includes("review_preview")
    );
    const adoptedSegments = Array.isArray(selectedOutput?.segments) ? selectedOutput.segments : [];
    const candidateCount = Number.parseInt($("#reviewPanelCandidateCount")?.textContent || "0", 10) || 0;
    const workflowState = body.dataset.workspaceState || "";
    const candidateCard = $("#ctV4MaterialsSummary .ct-v4-candidates-card");
    const candidateHeader = candidateCard?.querySelector("header strong");
    const candidateAction = candidateCard?.querySelector("[data-ct-v4-open-candidates]");
    const candidateActionLabel = candidateAction?.querySelector("[data-ct-v4-candidate-action-label]");
    const candidateHost = $("#ctV4CandidatePreview");
    // The candidate summary describes the task result, not the media currently
    // loaded in the player. Keep the generated segment thumbnails available
    // when the user switches back to the source video.
    const adoptedMode = Boolean(adoptedSegments.length);
    if (adoptedMode) {
      const adoptedExpanded = candidateHost?.dataset.expanded === "true";
      const visibleSegments = adoptedExpanded ? adoptedSegments : adoptedSegments.slice(0, 3);
      const timelineAssetsSnapshot = currentTimelineAssets();
      const spriteSignature = `${timelineAssetsSnapshot?.spriteUrl || ""}:${timelineAssetsSnapshot?.sprite?.items?.length || 0}`;
      setText(candidateHeader, "已采用片段");
      setText($("#ctV4CandidateCount"), `(${adoptedSegments.length})`);
      setText(candidateActionLabel, adoptedExpanded ? "收起" : "查看全部");
      if (candidateAction) {
        candidateAction.disabled = false;
        candidateAction.hidden = adoptedSegments.length <= 3;
        candidateAction.setAttribute("aria-expanded", String(adoptedExpanded));
      }
      setText($("#ctV4CandidateState"), `当前${previewOnly ? "样片" : "成片"}采用 ${adoptedSegments.length} 个源视频片段；点击缩略图可跳回源片位置`);
      if (candidateHost) {
        const signature = visibleSegments.map((segment) => `${segment.title || segment.label || ""}:${segmentRangeLabel(segment)}`).join("|");
        if (candidateHost.dataset.signature !== `adopted:${adoptedExpanded}:${spriteSignature}:${signature}`) {
          candidateHost.dataset.signature = `adopted:${adoptedExpanded}:${spriteSignature}:${signature}`;
          candidateHost.classList.add("ct-v4-adopted-preview");
          candidateHost.classList.toggle("is-expanded", adoptedExpanded);
          candidateHost.innerHTML = visibleSegments.map((segment, index) => {
            const label = cleanDisplayText(segment.title || segment.label || segment.reason, `片段 ${index + 1}`);
            const range = segmentRangeLabel(segment);
            return `<button type="button" data-ct-v4-adopted-segment="${index}" aria-label="查看已采用片段 ${index + 1}：${escapeHtml(label)}"><span class="ct-v4-adopted-thumb is-loading"><b>P${String(index + 1).padStart(2, "0")}</b></span><span class="ct-v4-adopted-copy"><strong>${escapeHtml(label)}</strong><small>${escapeHtml(range || "源片位置")}</small></span></button>`;
          }).join("");
          candidateHost.querySelectorAll("[data-ct-v4-adopted-segment]").forEach((button) => {
            const segment = visibleSegments[Number(button.dataset.ctV4AdoptedSegment || 0)] || {};
            applyAdoptedSegmentThumbnail($(".ct-v4-adopted-thumb", button), segment, timelineAssetsSnapshot);
          });
        }
      }
      candidateHost?.querySelectorAll("[data-ct-v4-adopted-segment]").forEach((button) => {
        button.onclick = () => {
          const segment = visibleSegments[Number(button.dataset.ctV4AdoptedSegment || 0)] || {};
          const start = Number(segment.sourceStart ?? segment.start ?? segment.startTime ?? 0);
          if (Number.isFinite(start) && typeof window.ClipTalkSeekSourceTime === "function") {
            window.ClipTalkSeekSourceTime(start);
            $("#mainVideo")?.scrollIntoView({ block: "center", behavior: "smooth" });
            return;
          }
          const video = $("#mainVideo");
          if (Number.isFinite(start) && video) video.currentTime = Math.max(0, start);
          video?.scrollIntoView({ block: "center", behavior: "smooth" });
        };
      });
    } else {
      setText(candidateHeader, "候选镜头");
      setText($("#ctV4CandidateCount"), candidateCount ? `(${candidateCount})` : "");
      setText(candidateActionLabel, "查看全部");
      setText($("#ctV4CandidateState"), candidateCount
        ? `已发现 ${candidateCount} 个候选镜头，可继续审核或补充到结果中`
        : ["analysing", "analyzing", "processing", "running"].includes(workflowState)
          ? "正在分析视频并整理候选镜头"
          : "提交剪辑要求后生成候选镜头");
      candidateHost?.classList.remove("ct-v4-adopted-preview");
      candidateHost?.classList.remove("is-expanded");
      if (candidateHost) candidateHost.dataset.expanded = "false";
      copyCandidateImages();
      if (candidateAction) {
        candidateAction.hidden = false;
        candidateAction.disabled = !candidateCount;
        candidateAction.removeAttribute("aria-expanded");
      }
    }
    candidateCard?.classList.toggle("is-empty", Boolean(!candidateCount && !adoptedSegments.length && !["analysing", "analyzing", "processing", "running"].includes(workflowState)));
    candidateCard?.classList.toggle("is-adopted", adoptedMode);

    const formalEntries = orderedOutputs.filter(({ item, version }) => !item?.previewOnly && !version?.previewOnly);
    const formalVersionCount = new Set(formalEntries.map(({ item, version }) => (
      String(version?.id || item?.versionId || item?.filename || "")
    )).filter(Boolean)).size;
    const previewCount = orderedOutputs.filter(({ item, version }) => item?.previewOnly || version?.previewOnly || String(item?.outputKind || "").includes("review_preview")).length;
    const qualityStatus = String(selectedOutput?.qualityStatus || selectedVersion?.qualityStatus || "");
    const versionState = [
      formalVersionCount ? `${formalVersionCount} 个正式版本` : "",
      previewCount ? `${previewCount} 个审核样片` : "",
    ].filter(Boolean).join(" · ");
    setText($("#ctV4VersionState"), versionCount ? versionState || `${versionCount} 个版本` : coverDraft ? "等待生成" : "尚未生成");
    const reviewingSelection = ["content_review", "running", "plan_planning"].includes(job?.presentation?.key);
    const versionHeading = $(".ct-v4-version-card > header > strong");
    setText(versionHeading, coverDraft && !versionCount ? "封面结果" : reviewingSelection && versionCount ? "历史成片（本次未修改）" : "当前版本");
    setText($(".ct-v4-version-card > header > span"), coverDraft && !versionCount ? "2" : "3");
    const versionName = cleanDisplayText(selectedOutput?.displayTitle)
      || cleanDisplayText(selectedOutput?.title)
      || (previewOnly ? "审核样片已生成" : "当前成片版本");
    setText($("#ctV4VersionName"), versionCount ? `${selectedVersion?.number ? `V${selectedVersion.number} · ` : ""}${versionName}` : coverDraft ? "等待封面方案" : "等待生成版本");
    const outputMeta = [
      compactDuration(selectedOutput?.duration),
      selectedOutput?.clipCount ? `${selectedOutput.clipCount} 个镜头` : "",
      selectedOutput?.width && selectedOutput?.height ? `${selectedOutput.width}×${selectedOutput.height}` : "",
      previewOnly ? "审核样片 · 可生成成片" : "",
    ].filter(Boolean).join(" · ");
    setText($("#ctV4VersionMeta"), versionCount
      ? outputMeta || $("#clipSummary")?.textContent?.trim() || "点击播放或进入版本列表查看"
      : coverDraft ? "生成后可选择并保存为当前封面" : "确认候选后会保留可审看版本");
    const deliveryChecks = $("#ctV4DeliveryChecks");
    if (deliveryChecks) {
      const playing = window.ClipTalkCurrentOutputSnapshot?.();
      const video = $("#mainVideo");
      const matchesPlayer = playing?.output?.filename === selectedOutput?.filename && playing?.mediaKind === "output";
      const width = Number(selectedOutput?.width || (matchesPlayer && video?.videoWidth) || 0);
      const height = Number(selectedOutput?.height || (matchesPlayer && video?.videoHeight) || 0);
      const coverReady = !job?.coverNeedsRegeneration && Boolean(
        selectedOutput?.coverUrl
        || selectedOutput?.coverIntroAvailable
        || selectedOutput?.coverIncluded
        || selectedOutput?.introIncluded
        || selectedOutput?.coverIntro?.enabled
        || selectedOutput?.coverVersionId
      );
      const overlayVerification = selectedOutput?.overlayVerification || {};
      const subtitleReady = Boolean(
        overlayVerification?.applied
        && Number(overlayVerification?.renderPipelineVersion || 0) >= 2
        && Number(overlayVerification?.subtitleCueCount || 0) > 0
      );
      const describedAspect = String(
        selectedOutput?.reframe?.aspect || selectedOutput?.aspect || (selectedOutput?.socialReframe ? "9:16" : ""),
      ).trim();
      const ratio = width > 0 && height > 0 ? width / height : 0;
      const inferredAspect = ratio > 0
        ? (Math.abs(ratio - (9 / 16)) <= .03 ? "9:16"
          : Math.abs(ratio - (16 / 9)) <= .03 ? "16:9"
            : ratio < 1 ? "竖屏" : ratio > 1 ? "横屏" : "1:1")
        : describedAspect;
      const dimensions = width > 0 && height > 0 ? `${width}×${height}` : "";
      const subtitleRequested = subtitleReady || [
        selectedOutput?.subtitleMode,
        selectedVersion?.subtitleMode,
        job?.brief?.subtitlePreference,
      ].some((value) => ["burn", "burned", "embedded"].includes(String(value || "").toLowerCase()));
      const coverRequested = coverReady || Boolean(
        job?.coverNeedsRegeneration
        || job?.coverDraft
        || job?.coverVersions?.length
        || selectedVersion?.coverVersionId
      );
      const checks = [];
      if (inferredAspect || dimensions) checks.push({
        label: "画幅",
        value: [inferredAspect, dimensions].filter(Boolean).join(" · "),
        ok: true,
      });
      if (subtitleRequested) checks.push({ label: "字幕", value: subtitleReady ? "已烧录" : "待烧录", ok: subtitleReady });
      if (coverRequested) checks.push({
        label: "封面",
        value: coverReady ? "已合入" : job?.coverNeedsRegeneration ? "需更新" : "待合入",
        ok: coverReady,
      });
      if (previewOnly && ["passed", "warning", "failed"].includes(qualityStatus)) {
        checks.unshift({
          label: "质检",
          value: qualityStatus === "passed" ? "已通过" : qualityStatus === "warning" ? "待复核" : "未通过",
          ok: qualityStatus === "passed",
        });
      }
      deliveryChecks.innerHTML = checks.map((item) => `<span class="${item.ok ? "ok" : "warn"}"><b>${item.label}</b><em>${item.value}</em></span>`).join("");
      deliveryChecks.classList.toggle("hidden", !versionCount || !checks.length);
    }
    $("#ctV4MaterialsSummary")?.classList.toggle("has-versions", Boolean(versionCount));
    $("#ctV4MaterialsSummary")?.classList.toggle("has-review-sample", Boolean(previewOnly && versionCount));
    $("#ctV4MaterialsSummary")?.classList.toggle("sample-preview", Boolean(outputSnapshot.isReviewSample && versionCount));
    const versionPreview = $("#ctV4MaterialsSummary .ct-v4-version-preview");
    const versionImage = versionPreview?.querySelector("img");
    const selectedImage = selectedOutput?.coverUrl || selectedOutput?.thumbnailUrl || "";
    const imageUnavailable = !selectedImage || versionImage?.dataset.failedSrc === selectedImage;
    versionPreview?.classList.toggle("is-placeholder", !versionCount || imageUnavailable);
    setText(versionPreview?.querySelector("em"), versionCount ? "缩略图暂不可用" : coverDraft ? "尚无封面" : "尚无成片");
    if (versionImage) {
      if (versionCount && selectedImage && !imageUnavailable) {
        if (versionImage.getAttribute("src") !== selectedImage) {
          delete versionImage.dataset.failedSrc;
          versionImage.src = selectedImage;
        }
        versionImage.alt = `${versionName}缩略图`;
      } else {
        versionImage.removeAttribute("src");
        versionImage.alt = "";
      }
    }
    const previewAction = $("[data-ct-v4-preview-version]", $("#ctV4MaterialsSummary"));
    const versionSecondaryActions = $(".ct-v4-version-secondary-actions", $("#ctV4MaterialsSummary"));
    const librarySaveAction = $("#saveToLibraryButton");
    if (versionSecondaryActions && librarySaveAction && librarySaveAction.parentElement !== versionSecondaryActions) {
      versionSecondaryActions.append(librarySaveAction);
    }
    const editAction = $("[data-ct-version-edit]");
    if (editAction) {
      editAction.disabled = !selectedVersion?.id || !selectedOutput?.segments?.length || selectedOutput.capabilities?.canEdit === false;
      editAction.hidden = outputSnapshot.mediaKind === "output" && !$("#secondaryEditCurrentButton")?.classList.contains("hidden");
    }
    if (librarySaveAction && selectedOutput?.filename) {
      librarySaveAction.classList.toggle("hidden", previewOnly);
      librarySaveAction.disabled = previewOnly || Boolean(selectedOutput.kept) || librarySaveAction.dataset.saving === "true" || selectedOutput.capabilities?.canKeep === false;
      librarySaveAction.title = selectedOutput.capabilities?.disabledReason?.keep || "保存独立成片副本";
      setText(librarySaveAction, selectedOutput.kept ? "已长期保留" : "长期保留");
      librarySaveAction.onclick = () => window.ClipTalkVersionAction?.(selectedOutput.filename, "keep");
    }
    setText(previewAction?.querySelector("span"), previewOnly ? "播放样片" : "播放成片");
    if (previewAction) {
      previewAction.title = previewOnly ? "在播放器中预览当前审核样片" : "播放当前正式成片";
      previewAction.setAttribute("aria-label", previewAction.title);
    }
    [previewAction, $("[data-ct-v4-open-versions]", $("#ctV4MaterialsSummary"))].forEach((button) => {
      if (button) button.disabled = !versionCount;
    });
    syncReviewRailToggle();
  }

  function syncProjectControls() {
    const job = window.ClipTalkCurrentJobSnapshot?.() || {};
    const outputAspect = ["16:9", "9:16"].includes(String(job?.projectSettings?.outputAspect))
      ? String(job.projectSettings.outputAspect) : "source";
    $$("#ctV4ProjectPanel [data-ct-v4-output-aspect]").forEach((button) => {
      const active = button.dataset.ctV4OutputAspect === outputAspect;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const displayName = $("#ctV4ProjectDisplayName");
    const fit = $("#ctV4ReframeFit");
    if (fit) {
      fit.value = job.projectSettings?.outputFit === "crop" ? "crop" : "blur";
      fit.disabled = outputAspect === "source";
      fit.title = outputAspect === "source" ? "跟随源片时无需适配画幅" : "后续新建剪辑使用此方式；不改变已有版本";
    }
    if (displayName && document.activeElement !== displayName) displayName.value = projectPreferences().displayName || "";
    setText($("#ctV4ProjectSourceName"), cleanDisplayText(job?.filename, "尚未载入"));
    const duration = $("#assetDuration")?.textContent?.trim();
    const resolution = $("#assetResolution")?.textContent?.trim();
    const mediaMeta = [duration, resolution].filter((value) => value && !/--/.test(value)).join(" · ");
    setText($("#ctV4ProjectSourceMeta"), mediaMeta || "等待读取");
    const orderedOutputs = window.ClipTalkOrderedJobOutputs?.(job) || [];
    const selectedFilename = $("#ctV4MaterialsSummary")?.dataset.outputFilename;
    const aspectExists = outputAspect !== "source" && orderedOutputs.some(({ item }) => {
      if (item.filename !== selectedFilename) return false;
      if (item.reframe?.fit && item.reframe.fit !== (job.projectSettings?.outputFit || "blur")) return false;
      const width = Number(item?.width || 0);
      const height = Number(item?.height || 0);
      const described = String(item?.reframe?.aspect || item?.aspect || "");
      const ratio = width > 0 && height > 0 ? width / height : 0;
      const targetRatio = outputAspect === "9:16" ? 9 / 16 : 16 / 9;
      return ratio > 0 ? Math.abs(ratio - targetRatio) <= .025 : described === outputAspect;
    });
    const aspectStatus = $("#ctV4OutputAspectStatus");
    const generateAspect = $("#ctV4GenerateAspect");
    if (outputAspect === "source") {
      setText(aspectStatus, "后续生成将保持源视频画幅，不执行裁切或补边。");
    } else if (aspectExists) {
      setText(aspectStatus, `当前所选版本已是 ${outputAspect} 画幅，可在素材与结果中播放。`);
    } else if (orderedOutputs.length) {
      setText(aspectStatus, `设置已保存；现有成片不会自动修改。可在“素材与结果”的当前版本中生成 ${outputAspect} 审核版本。`);
    } else {
      setText(aspectStatus, `设置已保存，将在下一次生成成片时应用 ${outputAspect} 画幅。`);
    }
    if (generateAspect) {
      generateAspect.classList.toggle("hidden", outputAspect === "source" || aspectExists || !orderedOutputs.length);
      generateAspect.disabled = outputAspect === "source" || aspectExists || !orderedOutputs.length;
      setText(generateAspect, `生成 ${outputAspect} 审核版本`);
    }
  }

  function syncPropertiesPanel() {
    const evidence = $("#evidencePanel");
    const selected = Boolean(evidence && !evidence.classList.contains("evidence-placeholder"));
    const propertiesTab = $('#ctV4RailTabs [data-ct-v4-rail="properties"]');
    if (propertiesTab) {
      propertiesTab.hidden = !selected;
      propertiesTab.disabled = !selected;
      propertiesTab.setAttribute("aria-disabled", String(!selected));
    }
    const entity = selected
      ? evidence.classList.contains("output-mode") ? "成片版本"
        : evidence.classList.contains("montage-mode") ? "组合事件"
          : evidence.classList.contains("candidate-mode") ? "镜头 / 事件"
            : "时间线对象"
      : "未选择";
    setText($("#ctV4PropertyType"), entity);
    setText($("#ctV4PropertyTitle"), selected ? $("#clipTitle")?.textContent?.trim() || "当前选择" : "选择事件或镜头");
    setText($("#ctV4PropertyMeta"), selected ? $("#clipTime")?.textContent?.trim() || "查看下方判断依据" : "选择后显示时间范围和可用操作");
    const selectionTitle = selected ? $("#clipTitle")?.textContent?.trim() || "当前选择" : "";
    const selectionMeta = selected ? $("#clipTime")?.textContent?.trim() || "" : "";
    const selectionBar = $("#ctV4SelectionBar");
    const selectionKey = selected ? `${entity}:${selectionTitle}:${selectionMeta}` : "";
    const selectionChanged = Boolean(selectionBar && selected && selectionBar.dataset.selectionKey !== selectionKey);
    if (selectionBar && selectionBar.dataset.selectionKey !== selectionKey) {
      selectionBar.dataset.selectionKey = selectionKey;
      delete body.dataset.ctV4EvidenceOpen;
      delete body.dataset.ctV4EvidenceReturnTab;
    }
    if (selectionBar) selectionBar.hidden = !selected;
    setText($("#ctV4SelectionTitle"), selectionTitle || "当前时间线项目");
    setText($("#ctV4SelectionMeta"), selectionMeta);
    const evidenceOpen = selected && body.dataset.ctV4EvidenceOpen === "true";
    const boundaryEditing = evidence?.classList.contains("content-boundary-view");
    $$('[data-ct-v4-show-evidence]').forEach((button) => {
      button.disabled = !selected;
      button.setAttribute("aria-expanded", String(evidenceOpen));
      button.textContent = evidenceOpen
        ? boundaryEditing ? "收起边界调整" : "收起判断依据"
        : "查看判断依据";
    });
    if (!selected) {
      delete body.dataset.ctV4EvidenceOpen;
      delete body.dataset.ctV4EvidenceReturnTab;
    }
    const boundary = $("#contentBoundaryEntryButton");
    const boundaryAvailable = Boolean(selected && boundary && selectedBoundaryEditorAvailable());
    const propertyActions = $("#ctV4PropertiesPanel .ct-v4-property-actions");
    if (propertyActions) propertyActions.hidden = !boundaryAvailable;
    const boundaryAction = $("#ctV4PropertiesPanel [data-ct-v4-boundary]");
    if (boundaryAction) boundaryAction.disabled = !boundaryAvailable;
    const boundaryShortcut = $("#ctV4SelectionBar [data-ct-v4-boundary-shortcut]");
    if (boundaryShortcut) {
      boundaryShortcut.hidden = !boundaryAvailable;
      boundaryShortcut.disabled = !boundaryAvailable;
    }
    setText($("#ctV4PropertyAvailability"), boundaryAvailable ? "可直接调整" : "");
    if (!selected && body.dataset.ctV4RailTab === "properties") setRailTab("materials");
    if (selectionChanged) {
      requestAnimationFrame(() => {
        if (selectionBar?.dataset.selectionKey === selectionKey) openReviewRail("properties");
      });
    }
  }

  function syncSelectedEntity() {
    const evidence = $("#evidencePanel");
    let entity = "none";
    if (evidence && !evidence.classList.contains("evidence-placeholder")) entity = "clip";
    if (!$("#timelineCoverTrack")?.classList.contains("hidden")) entity = "cover";
    if (!$("#subtitleReview")?.classList.contains("hidden")) entity = "subtitle";
    body.dataset.ctSelectedEntity = entity;
  }

  function mountWorkbench() {
    const workspace = $("#workspace");
    const active = body.dataset.shellView === "workspace" && workspace && !workspace.classList.contains("home-mode");
    body.classList.toggle("ct-workbench-v4", Boolean(active));
    if (!active) {
      delete body.dataset.ctWorkflowKind;
      $("#ctV4Topbar")?.setAttribute("aria-hidden", "true");
      const nav = $("#ctCompactWorkspaceNav");
      if (nav) { nav.hidden = true; nav.inert = true; }
      return;
    }

    const activeJob = window.ClipTalkCurrentJobSnapshot?.() || null;
    const workflowKind = String(activeJob?.workflowKind || activeJob?.request?.workflowKind || "");
    if (workflowKind) body.dataset.ctWorkflowKind = workflowKind;
    else delete body.dataset.ctWorkflowKind;

    migrateLegacyLayoutState();
    clearLegacyVisualState(workflowKind);
    ensureWorkbenchTimelinePlaceholder();
    ensureCompactWorkspaceNav();
    const topbar = ensureTopbar();
    topbar.setAttribute("aria-hidden", "false");
    const sidebar = $("#appSidebar");
    const assistant = $("#assistantPanel");
    if (sidebar && workspace && sidebar.parentElement !== document.body) document.body.insertBefore(sidebar, workspace);
    ensureAssistantLayout();
    ensureRailTabs();
    syncPortraitPanels();
    setRailTab(body.dataset.ctV4RailTab || "materials");
    syncTopbar();
    syncTaskJourney();
    syncMaterialsSummary();
    syncProjectControls();
    syncSelectedEntity();
    syncPropertiesPanel();
    window.ClipTalkTimelinePresentation?.sync?.();
  }

  mountWorkbench();
  let frame = 0;
  const schedule = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      mountWorkbench();
    });
  };
  const observer = new MutationObserver(schedule);
  observer.observe(body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["class", "src", "data-shell-view", "data-workspace-state", "data-review-layout"],
  });
  window.addEventListener("resize", schedule, { passive: true });
  const publicController = {
    ...(window.ClipTalkWorkspaceController || {}),
    syncMaterialsSummary,
    syncProjectControls,
    openDeliveryResult,
    setRailExpanded: setReviewRailExpanded,
    syncPortraitPanels,
    openRail: openReviewRail,
    openEvidence: openEvidenceDetails,
    closeEvidence: closeEvidenceDetails,
    mount: mountWorkbench,
  };
  window.ClipTalkWorkspaceController = publicController;
  // One-release alias for cached pages and extensions that still use the old name.
  window.ClipTalkWorkbenchV4 = publicController;
})();
