(function () {
  "use strict";

  const request = window.ClipTalkApi?.request;
  if (!request) return;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const workflowLabels = {
    highlight: "智能高光",
    content_search: "内容探索",
    person_edit: "按人物剪辑",
    speaker_edit: "按说话人剪辑",
  };
  const activeStatuses = new Set(["briefing", "queued", "running", "cancelling", "rendering"]);
  const actionStatuses = new Set([
    "brief_confirmation", "awaiting_model_decision",
    "awaiting_confirmation", "awaiting_content_confirmation",
  ]);
  const state = {
    catalog: [],
    sidebarJobs: [],
    nextCursor: null,
    hasMore: false,
    filter: "all",
    query: "",
    outputs: [],
    libraryQuery: "",
    librarySort: "newest",
    view: "home",
    returnView: "home",
    loadingCatalog: false,
    loadingSidebar: false,
    loadingLibrary: false,
    searchTimer: null,
    deleteArm: null,
  };

  function workflowKind(job) {
    return String(job?.presentation?.workflowKind || job?.workflowKind || job?.request?.workflowKind || (
      job?.taskMode === "content_extract" ? "content_search" : "highlight"
    ));
  }

  function statusGroup(job) {
    const status = String(job?.status || "");
    const presentation = job?.presentation || {};
    if (["failed", "cancelled"].includes(status)) return "failed";
    if (presentation.actionRequired || presentation.state === "action_required" || actionStatuses.has(status)) return "action_required";
    if (status === "completed") return "completed";
    if (activeStatuses.has(status) || job?.execution?.active) return "active";
    return "other";
  }

  function statusText(job) {
    const presentation = job?.presentation || {};
    const action = presentation.primaryAction || presentation.actionRequired;
    const group = statusGroup(job);
    if (group === "action_required") return String(action?.title || action?.label || "等待你确认");
    if (group === "completed") return Number(job?.outputCount || 0) > 0 ? `已完成 · ${Number(job.outputCount)} 条成片` : "处理完成";
    if (group === "failed") return String(job?.status) === "cancelled" ? "已取消" : "处理失败";
    if (String(job?.status) === "queued") return "等待开始";
    if (group === "active") return String(job?.detail || "正在处理");
    return String(job?.detail || "等待继续");
  }

  function stagePosition(job) {
    if (statusGroup(job) === "completed") return 4;
    const presentation = job?.presentation || {};
    const phase = String(presentation.phase || "").toLowerCase();
    const phaseMap = {
      brief: 0,
      prepare: 0,
      preparation: 0,
      analysis: 1,
      search: 1,
      discovery: 1,
      review: 2,
      events: 2,
      edit: 2,
      compose: 3,
      render: 3,
      export: 3,
      complete: 4,
    };
    if (Number.isInteger(phaseMap[phase])) return phaseMap[phase];
    const steps = Array.isArray(presentation.steps) ? presentation.steps : [];
    if (steps.length) {
      if (steps.every((item) => item?.state === "complete")) return 4;
      const current = steps.findIndex((item) => item?.state === "current");
      const completed = steps.filter((item) => item?.state === "complete").length;
      const position = current >= 0 ? current : completed;
      return Math.min(3, Math.max(0, Math.floor(position / Math.max(1, steps.length) * 4)));
    }
    if (statusGroup(job) === "action_required") return 2;
    return 0;
  }

  function taskProgressMarkup(job) {
    if (statusGroup(job) !== "active") return "";
    const raw = Number(job?.progress);
    const fraction = Number.isFinite(raw)
      ? Math.max(0, Math.min(1, raw))
      : Math.max(0, Math.min(1, stagePosition(job) / 4));
    const percent = Math.round(fraction * 100);
    return `<span class="shell-task-progress" aria-label="任务进度 ${percent}%"><i><b style="width:${percent}%"></b></i><em>${percent}%</em></span>`;
  }

  function taskStateLabel(group) {
    if (group === "active") return "进行中";
    if (group === "action_required") return "待确认";
    if (group === "completed") return "已完成";
    if (group === "failed") return "未完成";
    return "已保存";
  }

  function taskCard(job, { home = false, deletable = true } = {}) {
    const group = statusGroup(job);
    const workflow = workflowLabels[workflowKind(job)] || "视频剪辑";
    const current = String(window.ClipTalkCurrentJobId?.() || "") === String(job?.id || "");
    const title = String(job?.filename || "未命名视频").replace(/\.[a-z0-9]{2,5}$/i, "");
    const updated = formatDate(job?.updatedAt || job?.createdAt).replace("保存时间未知", "更新时间未知");
    return `<article class="shell-task-card${current ? " is-current" : ""}${home ? " home-shell-task" : ""}" data-shell-job="${escapeHtml(job?.id)}" data-status-group="${group}">
      ${deletable && group !== "active" ? `<button class="shell-task-delete" type="button" data-shell-delete="${escapeHtml(job?.id)}" aria-label="删除任务" title="删除任务">×</button>` : ""}
      <button class="shell-task-open" type="button" data-shell-open="${escapeHtml(job?.id)}">
        <span class="shell-task-heading"><strong title="${escapeHtml(job?.filename || "未命名视频")}">${escapeHtml(title)}</strong><b class="shell-task-state">${escapeHtml(taskStateLabel(group))}</b></span>
        <small>${escapeHtml(workflow)}${current ? " · 当前任务" : ""}</small>
        <span class="shell-task-detail" title="${escapeHtml(statusText(job))}">${escapeHtml(statusText(job))}</span>
        <span class="shell-task-foot"><time>${escapeHtml(updated)}</time>${taskProgressMarkup(job)}</span>
      </button>
    </article>`;
  }

  function renderNavigationBadges() {
    const currentId = String(window.ClipTalkCurrentJobId?.() || "");
    const currentTask = $("#sidebarCurrentTask");
    const sidebar = $("#appSidebar");
    sidebar?.classList.toggle("has-current-task", Boolean(currentId));
    if (currentTask) {
      currentTask.disabled = !currentId;
      currentTask.title = currentId ? "返回当前任务" : "暂无当前任务";
      currentTask.setAttribute("aria-label", currentId ? "返回当前任务" : "当前没有已打开的任务");
    }
    const attention = state.catalog.filter((job) => ["active", "action_required"].includes(statusGroup(job))).length;
    const attentionCount = $("#sidebarAttentionCount");
    if (attentionCount) {
      attentionCount.textContent = String(attention);
      attentionCount.classList.toggle("hidden", !attention);
    }
    const outputTotal = state.catalog.reduce((sum, job) => sum + Number(job?.outputCount || 0), 0);
    const outputCount = $("#sidebarOutputCount");
    if (outputCount && !state.outputs.length) {
      outputCount.textContent = String(outputTotal);
      outputCount.classList.toggle("hidden", !outputTotal);
    }
  }

  function renderSidebar() {
    const root = $("#sidebarHistoryList");
    if (!root) return;
    const currentId = String(window.ClipTalkCurrentJobId?.() || "");
    const jobs = [...state.sidebarJobs].sort((left, right) => {
      if (String(left.id) === currentId) return -1;
      if (String(right.id) === currentId) return 1;
      return String(right.updatedAt || right.createdAt || "").localeCompare(String(left.updatedAt || left.createdAt || ""));
    });
    $("#sidebarTaskCount").textContent = String(jobs.length);
    root.innerHTML = jobs.length
      ? jobs.map((job) => taskCard(job)).join("")
      : `<div class="app-sidebar-empty">${state.query || state.filter !== "all" ? "没有符合条件的任务" : "还没有任务"}</div>`;
    $("#sidebarLoadMore")?.classList.toggle("hidden", !state.hasMore);
    renderNavigationBadges();
  }

  function renderHome() {
    const root = $("#homeTaskGrid");
    const home = $("#homeView");
    if (!root || !home) return;
    const relevant = state.catalog.filter((job) => ["active", "action_required"].includes(statusGroup(job))).slice(0, 4);
    const projectIds = new Set(state.catalog.map((job) => String(job.sourceProjectId || job.id)));
    const taskCount = $("#homeTaskCount");
    const assetCount = $("#homeAssetCount");
    const outputCount = $("#homeOutputCount");
    if (taskCount) taskCount.textContent = String(state.catalog.length);
    if (assetCount) assetCount.textContent = String(projectIds.size);
    if (outputCount) outputCount.textContent = String(state.catalog.reduce((sum, job) => sum + Number(job.outputCount || 0), 0));
    home.dataset.homeState = state.catalog.length ? "ready" : "empty";
    home.setAttribute("aria-busy", "false");
    root.innerHTML = relevant.length
      ? relevant.map((job) => taskCard(job, { home: true, deletable: false })).join("")
      : `<div class="home-current-empty"><div><strong>当前没有处理中的任务</strong><span>创建新任务后，进行中和待确认的内容会显示在这里。</span></div></div>`;
    renderNavigationBadges();
  }

  function catalogUrl({ cursor = null, filter = state.filter, query = state.query } = {}) {
    const params = new URLSearchParams({ limit: "30" });
    if (cursor) params.set("cursor", cursor);
    if (filter && filter !== "all") params.set("status", filter);
    if (query) params.set("q", query);
    return `/api/jobs?${params.toString()}`;
  }

  async function loadBaseCatalog() {
    if (state.loadingCatalog) return;
    state.loadingCatalog = true;
    try {
      // Keep the first catalog request on the long-standing endpoint shape.
      // The server already defaults to 30 records; query parameters are only
      // needed for filtered and subsequent pages.
      const response = await request("/api/jobs");
      state.catalog = Array.isArray(response?.jobs) ? response.jobs : [];
      if (state.filter === "all" && !state.query) {
        state.sidebarJobs = [...state.catalog];
        state.nextCursor = response?.nextCursor || null;
        state.hasMore = Boolean(response?.hasMore);
        renderSidebar();
      }
      renderHome();
    } catch (error) {
      const home = $("#homeView");
      const root = $("#homeTaskGrid");
      if (home) { home.dataset.homeState = "error"; home.setAttribute("aria-busy", "false"); }
      if (root) root.innerHTML = `<section class="home-current-empty home-error-card" role="status"><div><strong>最近任务暂时无法加载</strong><span>${escapeHtml(error?.message || "服务暂时不可用")}，你仍然可以创建新任务。</span></div><button type="button" data-home-retry data-shell-retry>重新加载</button></section>`;
    } finally {
      state.loadingCatalog = false;
    }
  }

  async function loadSidebarCatalog({ append = false } = {}) {
    if (state.loadingSidebar) return;
    state.loadingSidebar = true;
    const root = $("#sidebarHistoryList");
    if (!append && root) root.innerHTML = '<div class="app-sidebar-loading">正在读取历史任务</div>';
    try {
      const response = await request(catalogUrl({ cursor: append ? state.nextCursor : null }));
      const jobs = Array.isArray(response?.jobs) ? response.jobs : [];
      state.sidebarJobs = append ? [...state.sidebarJobs, ...jobs] : jobs;
      state.nextCursor = response?.nextCursor || null;
      state.hasMore = Boolean(response?.hasMore);
      renderSidebar();
    } catch (error) {
      if (root) root.innerHTML = `<div class="app-sidebar-error">历史任务读取失败<br>${escapeHtml(error?.message || "请稍后重试")}</div>`;
    } finally {
      state.loadingSidebar = false;
    }
  }

  async function refreshCatalog() {
    await loadBaseCatalog();
    if (state.filter !== "all" || state.query) await loadSidebarCatalog();
  }

  function syncCurrentJob(job) {
    if (!job?.id) return;
    const merge = (collection) => {
      const index = collection.findIndex((item) => String(item.id) === String(job.id));
      if (index >= 0) collection[index] = { ...collection[index], ...job };
      else collection.unshift(job);
    };
    merge(state.catalog);
    if (state.filter === "all" && !state.query) merge(state.sidebarJobs);
    renderSidebar();
    renderHome();
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds || 0)));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor(total % 3600 / 60);
    const remainder = total % 60;
    return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}` : `${minutes}:${String(remainder).padStart(2, "0")}`;
  }

  function formatDate(value) {
    const date = new Date(String(value || ""));
    if (Number.isNaN(date.getTime())) return "保存时间未知";
    return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
  }

  function renderLibrary() {
    const root = $("#libraryOutputList");
    if (!root) return;
    const returnButton = $("[data-library-return]");
    if (returnButton) returnButton.textContent = window.ClipTalkCurrentJobId?.() ? "返回当前任务" : "返回首页";
    const query = state.libraryQuery.toLocaleLowerCase();
    const filtered = state.outputs.filter((item) => !query || [item.title, item.displayName, item.sourceFilename, item.filename]
      .some((value) => String(value || "").toLocaleLowerCase().includes(query)));
    const sorted = [...filtered].sort((left, right) => {
      if (state.librarySort === "duration") return Number(right.duration || 0) - Number(left.duration || 0);
      const comparison = String(right.keptAt || right.createdAt || "").localeCompare(String(left.keptAt || left.createdAt || ""));
      return state.librarySort === "oldest" ? -comparison : comparison;
    });
    if (!sorted.length) {
      root.innerHTML = `<div class="app-library-empty">${state.outputs.length ? "没有符合条件的成片" : "还没有保存到成片库的版本"}</div>`;
      return;
    }
    root.innerHTML = sorted.map((item, index) => {
      const title = item.displayName || item.title || item.filename || "未命名成片";
      const version = Number(item.versionNumber || 1);
      const size = Number(item.sizeBytes || 0) / 1024 / 1024;
      return `<article class="app-library-item${index === 0 ? " featured" : ""}" data-library-key="${escapeHtml(`${item.jobId}/${item.filename}`)}">
        <div class="app-library-media"><video src="${escapeHtml(item.videoUrl)}" preload="metadata" muted playsinline aria-label="${escapeHtml(title)}预览"></video><span>${escapeHtml(formatDuration(item.duration))}</span></div>
        <div class="app-library-copy"><small>V${String(version).padStart(2, "0")} · 已保存版本</small><strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong><p>来自任务：${escapeHtml(item.sourceFilename || "原任务已清理")}</p><div class="app-library-meta"><span>${escapeHtml(formatDuration(item.duration))}</span><span>${escapeHtml(formatDate(item.keptAt || item.createdAt))}</span>${size ? `<span>${size.toFixed(1)} MB</span>` : ""}</div><div class="app-library-actions"><button class="primary" type="button" data-library-play>播放</button><a href="${escapeHtml(item.downloadUrl)}" download="${escapeHtml(item.downloadFilename || item.filename)}">下载</a><button class="danger" type="button" data-library-delete data-job-id="${escapeHtml(item.jobId)}" data-filename="${escapeHtml(item.filename)}">删除</button></div></div>
      </article>`;
    }).join("");
  }

  async function loadLibrary({ force = false } = {}) {
    if (state.loadingLibrary || (state.outputs.length && !force)) return;
    state.loadingLibrary = true;
    const root = $("#libraryOutputList");
    if (root) root.innerHTML = '<div class="app-library-loading" role="status">正在读取成片库</div>';
    try {
      const response = await request("/api/kept");
      state.outputs = Array.isArray(response?.outputs) ? response.outputs : [];
      const count = $("#sidebarOutputCount");
      if (count) { count.textContent = String(state.outputs.length); count.classList.toggle("hidden", !state.outputs.length); }
      renderLibrary();
    } catch (error) {
      if (root) root.innerHTML = `<div class="app-library-error">成片库读取失败：${escapeHtml(error?.message || "服务暂时不可用")}</div>`;
    } finally {
      state.loadingLibrary = false;
    }
  }

  function routeParams() {
    try { return new URLSearchParams(String(location.hash || "").replace(/^#/, "")); }
    catch { return new URLSearchParams(); }
  }

  function writeViewRoute(view, { push = false } = {}) {
    try {
      const url = new URL(location.href);
      const params = routeParams();
      if (["settings", "library"].includes(view)) params.set("view", view);
      else params.delete("view");
      url.hash = params.toString();
      history[push ? "pushState" : "replaceState"]({ ...(history.state || {}), shellView: view }, "", url.href);
    } catch { /* Embedded previews may not expose history. */ }
  }

  function updateNav(view) {
    $$('.app-sidebar [data-shell-view]').forEach((button) => {
      const active = button.dataset.shellView === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
  }

  function setSidebarMode(view) {
    const workspace = view === "workspace";
    document.body.dataset.shellMode = workspace ? "workspace" : "page";
  }

  function showView(view, { route = true, push = false } = {}) {
    const next = ["home", "workspace", "settings", "library"].includes(view) ? view : "home";
    if (next === "settings" && state.view !== "settings") {
      state.returnView = state.view;
    } else if (next === "library" && !["settings", "library"].includes(state.view)) {
      state.returnView = window.ClipTalkCurrentJobId?.() ? "workspace" : "home";
    }
    state.view = next;
    document.body.dataset.shellView = next;
    setSidebarMode(next);
    updateNav(next);
    renderNavigationBadges();
    const library = $("#libraryView");
    const settings = $("#settingsPanel");
    if (library) library.classList.toggle("hidden", next !== "library");
    if (settings) settings.classList.toggle("hidden", next !== "settings");
    if (next !== "settings") {
      $("#settingsBackdrop")?.classList.add("hidden");
      document.body.classList.remove("settings-open");
    }
    if (next === "library") void loadLibrary();
    if (next === "settings") {
      $("#settingsBackdrop")?.classList.add("hidden");
      document.body.classList.add("settings-open");
      if (settings) settings.scrollTop = 0;
      window.loadVisionSettings?.();
      window.loadLlmSettings?.();
    }
    if (route) writeViewRoute(next, { push });
  }

  function returnFromPage() {
    const fallback = window.ClipTalkCurrentJobId?.() ? "workspace" : "home";
    showView(state.returnView || fallback, { route: true });
  }

  function setHistoryDrawer(open, { restoreFocus = false } = {}) {
    const expanded = Boolean(open);
    const drawer = $("#sidebarHistoryDrawer");
    const toggle = $("#sidebarHistoryToggle");
    document.body.dataset.sidebarOverlay = String(expanded);
    drawer?.setAttribute("aria-hidden", String(!expanded));
    if (drawer) drawer.inert = !expanded;
    toggle?.setAttribute("aria-expanded", String(expanded));
    toggle?.classList.toggle("active", expanded);
    $("#appSidebarScrim")?.classList.toggle("hidden", !expanded);
    if (expanded) {
      window.requestAnimationFrame(() => $("#sidebarTaskSearch")?.focus());
      void refreshCatalog();
    } else if (restoreFocus) {
      toggle?.focus();
    }
  }

  async function openTask(jobId) {
    if (!jobId) return;
    try {
      await window.openHomeTask?.(jobId);
      showView("workspace", { route: false });
      setHistoryDrawer(false);
      renderSidebar();
    } catch (error) {
      window.showToast?.(`无法打开任务：${error?.message || "服务暂时不可用"}`);
    }
  }

  async function loadServiceState() {
    const button = $("#engineState");
    const label = $("#engineState span");
    try {
      const health = await request("/api/health");
      const ready = Boolean((health.visionConfigured ?? health.arkConfigured) && health.ffmpeg && health.ffprobe);
      button?.classList.toggle("offline", !ready);
      if (label) label.textContent = ready ? "服务正常" : "服务需配置";
      if (button) {
        button.title = ready ? "服务正常，点击查看运行环境" : "服务需要配置，点击查看详情";
        button.setAttribute("aria-label", button.title);
      }
    } catch {
      button?.classList.add("offline");
      if (label) label.textContent = "服务离线";
      if (button) {
        button.title = "服务离线，点击查看详情";
        button.setAttribute("aria-label", button.title);
      }
    }
  }

  document.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const viewButton = target.closest(".app-sidebar [data-shell-view]");
    if (viewButton) {
      const view = viewButton.dataset.shellView;
      if (view === "home") {
        window.resetWorkspace?.(true);
        showView("home", { route: true, push: true });
      } else if (view === "settings") {
        window.openSettings?.();
        showView("settings", { route: true, push: true });
      } else if (view === "workspace" && window.ClipTalkCurrentJobId?.()) {
        showView("workspace", { route: true, push: true });
      } else if (view === "library") showView("library", { route: true, push: true });
      setHistoryDrawer(false);
      return;
    }
    if (target.closest("#sidebarNewTask")) {
      window.openNewTaskFromHome?.();
      showView("workspace", { route: false });
      setHistoryDrawer(false);
      return;
    }
    if (target.closest("#sidebarHistoryToggle")) {
      setHistoryDrawer(document.body.dataset.sidebarOverlay !== "true", { restoreFocus: true });
      return;
    }
    if (target.closest("#sidebarHistoryClose") || target.closest("#appSidebarScrim")) { setHistoryDrawer(false, { restoreFocus: true }); return; }
    if (target.closest("[data-shell-retry]")) { await refreshCatalog(); return; }
    const filter = target.closest("[data-sidebar-filter]");
    if (filter) {
      state.filter = filter.dataset.sidebarFilter || "all";
      $$('[data-sidebar-filter]').forEach((button) => {
        const active = button === filter;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      await loadSidebarCatalog();
      return;
    }
    if (target.closest("#sidebarLoadMore")) { await loadSidebarCatalog({ append: true }); return; }
    const taskOpen = target.closest("[data-shell-open]");
    if (taskOpen) { await openTask(taskOpen.dataset.shellOpen); return; }
    const taskDelete = target.closest("[data-shell-delete]");
    if (taskDelete) {
      event.stopPropagation();
      await window.deleteHistoryJob?.(taskDelete.dataset.shellDelete);
      await refreshCatalog();
      return;
    }
    if (target.closest('[data-shell-action="status"]')) {
      window.openSettings?.();
      showView("settings", { route: true, push: true });
      const runtime = $("#settingsPanel .runtime-settings-summary");
      if (runtime) { runtime.open = true; window.setTimeout(() => runtime.scrollIntoView({ behavior: "smooth", block: "center" }), 60); }
      return;
    }
    if (target.closest("#settingsButton")) {
      showView("settings", { route: true, push: true });
      return;
    }
    if (target.closest("[data-library-return]")) { returnFromPage(); return; }
    const play = target.closest("[data-library-play]");
    if (play) {
      const video = $("video", play.closest(".app-library-item"));
      if (!video) return;
      if (video.paused) { video.muted = false; video.controls = true; await video.play().catch(() => {}); play.textContent = "暂停"; }
      else { video.pause(); play.textContent = "播放"; }
      return;
    }
    const deleteOutput = target.closest("[data-library-delete]");
    if (deleteOutput) {
      const key = `${deleteOutput.dataset.jobId}/${deleteOutput.dataset.filename}`;
      if (state.deleteArm !== key) {
        state.deleteArm = key;
        deleteOutput.classList.add("armed");
        deleteOutput.textContent = "再次点击确认";
        window.setTimeout(() => { if (state.deleteArm === key) { state.deleteArm = null; renderLibrary(); } }, 4200);
        return;
      }
      await request(`/api/kept/${encodeURIComponent(deleteOutput.dataset.jobId)}/${encodeURIComponent(deleteOutput.dataset.filename)}`, { method: "DELETE" });
      state.deleteArm = null;
      await loadLibrary({ force: true });
    }
  });

  $("#sidebarTaskSearch")?.addEventListener("input", (event) => {
    window.clearTimeout(state.searchTimer);
    state.query = String(event.currentTarget.value || "").trim();
    state.searchTimer = window.setTimeout(() => loadSidebarCatalog(), 260);
  });
  $("#librarySearch")?.addEventListener("input", (event) => { state.libraryQuery = String(event.currentTarget.value || "").trim(); renderLibrary(); });
  $("#librarySort")?.addEventListener("change", (event) => { state.librarySort = event.currentTarget.value; renderLibrary(); });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.dataset.sidebarOverlay === "true") {
      event.preventDefault();
      setHistoryDrawer(false, { restoreFocus: true });
      return;
    }
    if (event.key === "Tab" && document.body.dataset.sidebarOverlay === "true") {
      const drawer = $("#sidebarHistoryDrawer");
      const focusable = $$('button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])', drawer)
        .filter((node) => !node.hidden && getComputedStyle(node).display !== "none");
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  const studio = $("#workspace");
  const secondaryEditor = $("#secondaryEditor");
  const syncInferredView = () => {
    if (["settings", "library"].includes(state.view)) return;
    const workspaceOpen = !studio?.classList.contains("home-mode") || !secondaryEditor?.classList.contains("hidden");
    const inferred = workspaceOpen ? "workspace" : "home";
    if (inferred !== state.view) showView(inferred, { route: false });
  };
  if (studio) new MutationObserver(syncInferredView).observe(studio, { attributes: true, attributeFilter: ["class"] });
  if (secondaryEditor) new MutationObserver(syncInferredView).observe(secondaryEditor, { attributes: true, attributeFilter: ["class"] });

  window.addEventListener("popstate", () => {
    const params = routeParams();
    const routeView = params.get("view");
    if (["settings", "library"].includes(routeView)) return void showView(routeView, { route: false });
    const jobId = params.get("job");
    if (jobId && String(window.ClipTalkCurrentJobId?.() || "") !== jobId) void openTask(jobId);
    else if (!jobId) { window.resetWorkspace?.(true); showView("home", { route: false }); }
    else showView("workspace", { route: false });
  });

  window.ClipTalkAppShell = {
    refreshCatalog,
    loadHomeTasks: refreshCatalog,
    syncCurrentJob,
    showView,
    returnFromPage,
    loadLibrary,
  };

  const initialView = routeParams().get("view");
  showView(["settings", "library"].includes(initialView) ? initialView : "home", { route: false });
  void refreshCatalog();
  void loadLibrary();
  void loadServiceState();
  window.setInterval(() => {
    if (!document.hidden && (state.view === "home" || document.body.dataset.sidebarOverlay === "true")) void refreshCatalog();
  }, 15000);
  window.setInterval(loadServiceState, 30000);
})();
