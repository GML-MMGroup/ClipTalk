/*!
 * chat-stream.js — 统一对话流（左侧面板唯一信息面）
 *
 * 设计目标（对应《ClipTalk左侧面板对话流改造方案》）：
 *   1. 所有事件以消息卡片形式进入 #chatMessages，最新在底，历史可回溯。
 *   2. 常驻物只有三样：header、输入框、条件性「待处理条」。
 *   3. 高频轮询不整体重绘：卡片按 id 幂等，内容未变化则完全不写 DOM。
 *
 * 关键实现约束：
 *   - renderConversation()（app.js）用 innerHTML 整体替换 #chatMessages。
 *     因此卡片必须活在一个持久宿主节点 #csStreamHost 内，由 app.js 在
 *     重绘后重新 append（沿用 #jobStatus 的既有保留模式），DOM 身份不丢。
 *   - 卡片 id 由业务主键决定（plan:<id> / compose:<jobId> / pending:<wsId>），
 *     同一 id 重复 emit = 更新而非追加，天然幂等，轮询不会堆积。
 *
 * 逃生阀：?legacyDock=1 恢复改造前的固定面板渲染。
 */
(function () {
  "use strict";

  var global = window;
  var MAX_CARDS = 60;
  var PIN_THRESHOLD = 56; // 与 appendMessage / renderConversation 保持一致的贴底阈值

  var host = null;
  var cards = []; // { id, kind, html, tone, final, createdAt, el, pendingHtml }
  var pendingActions = new Map(); // id -> { summary, primaryLabel, onPrimary, viewLabel, onView }
  var actionBarEl = null;
  var pillEl = null;
  var announcerEl = null;
  var unreadCount = 0;
  var scrollBound = false;
  var restoring = 0;
  var actionSource = null;
  var actionObserver = null;

  // Restoration is synchronous: later network events remain live messages.
  function restore(render) {
    var node = root();
    var top = node?.scrollTop || 0;
    restoring += 1;
    try { return render(); }
    finally {
      restoring -= 1;
      if (node) node.scrollTop = top;
    }
  }

  function legacyDockEnabled() {
    try {
      return new URLSearchParams(String(global.location?.search || "")).has("legacyDock");
    } catch (error) {
      return false;
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function root() {
    return document.querySelector("#chatMessages");
  }

  function panel() {
    return document.querySelector(".chat-panel") || root()?.parentElement || null;
  }

  /** 滚动容器到指定节点的距离是否处于「贴底」状态。 */
  function isPinned() {
    var node = root();
    if (!node) return true;
    return node.scrollHeight - node.scrollTop - node.clientHeight < PIN_THRESHOLD;
  }

  function scrollToBottom(behavior) {
    var node = root();
    if (!node) return;
    try {
      node.scrollTo({ top: node.scrollHeight, behavior: behavior || "smooth" });
    } catch (error) {
      node.scrollTop = node.scrollHeight;
    }
  }

  function ensureAnnouncer() {
    if (announcerEl?.isConnected) return announcerEl;
    announcerEl = document.getElementById("csAnnouncer");
    if (!announcerEl) {
      announcerEl = document.createElement("div");
      announcerEl.id = "csAnnouncer";
      announcerEl.className = "cs-announcer";
      announcerEl.setAttribute("role", "status");
      announcerEl.setAttribute("aria-live", "polite");
    }
    panel()?.append(announcerEl);
    return announcerEl;
  }

  function announce(text) {
    if (!text || restoring) return;
    var node = ensureAnnouncer();
    node.textContent = "";
    global.setTimeout(() => {
      node.textContent = String(text);
    }, 30);
  }

  function ensurePill() {
    if (pillEl?.isConnected) return pillEl;
    pillEl = document.getElementById("csUnreadPill");
    if (!pillEl) {
      pillEl = document.createElement("button");
      pillEl.id = "csUnreadPill";
      pillEl.type = "button";
      pillEl.className = "cs-unread-pill hidden";
      pillEl.addEventListener("click", () => {
        unreadCount = 0;
        syncPill();
        scrollToBottom("smooth");
      });
    }
    panel()?.append(pillEl);
    return pillEl;
  }

  function syncPill() {
    var pill = ensurePill();
    if (unreadCount <= 0) {
      pill.classList.add("hidden");
      pill.hidden = true;
      return;
    }
    pill.hidden = false;
    pill.classList.remove("hidden");
    pill.textContent = unreadCount > 99 ? "↓ 99+ 条新消息" : `↓ ${unreadCount} 条新消息`;
    pill.setAttribute("aria-label", `有 ${unreadCount} 条新消息，回到底部查看`);
  }

  function bindScroll() {
    var node = root();
    if (!node || scrollBound) return;
    scrollBound = true;
    node.addEventListener("scroll", () => {
      if (isPinned() && unreadCount) {
        unreadCount = 0;
        syncPill();
      }
    }, { passive: true });
  }

  /** 持久宿主：卡片全部挂在它下面，renderConversation 重绘后由 app.js 重新 append。 */
  function ensureHost() {
    if (host?.isConnected) return host;
    // 宿主被整体重绘摘掉时，必须复用内存里的原节点，否则会连同卡片一起丢失。
    if (!host) host = document.getElementById("csStreamHost");
    if (!host) {
      host = document.createElement("div");
      host.id = "csStreamHost";
      host.className = "cs-stream-host";
      host.setAttribute("aria-label", "Agent 执行动态");
    }
    var node = root();
    if (!node) return host;
    // 宿主已存在但被 innerHTML 摘掉时，重新挂回滚动容器末尾。
    if (host.parentElement !== node) node.append(host);
    return host;
  }

  function hostElement() {
    return ensureHost();
  }

  function findCard(id) {
    var key = String(id || "");
    return cards.find((card) => String(card.id) === key) || null;
  }

  function cardElement(id) {
    var card = findCard(id);
    if (card?.el?.isConnected) return card.el;
    var node = ensureHost().querySelector(`[data-cs-id="${cssEscape(String(id || ""))}"]`);
    return node || null;
  }

  function cssEscape(value) {
    return String(value).replaceAll('"', '\\"');
  }

  function cardShell(card) {
    var article = document.createElement("article");
    article.className = `chat-message assistant cs-card cs-kind-${String(card.kind || "system").replace(/[^a-z0-9_-]/gi, "-")}`;
    article.dataset.csId = String(card.id);
    article.dataset.csKind = String(card.kind || "system");
    if (card.tone) article.dataset.csTone = String(card.tone);
    if (card.final) article.dataset.csFinal = "true";
    article.innerHTML = `<span class="avatar" aria-hidden="true">AI</span><div class="bubble cs-card-body"${card.busy ? ' aria-busy="true"' : ""}>${card.html || ""}</div>`;
    card.el = article;
    return article;
  }

  /**
   * 写入卡片内容。两点保护：
   *   - 内容字符串未变化 → 完全不碰 DOM（轮询绝大多数情况走这条，零闪烁）。
   *   - 卡片内部有焦点 → 挂起到 blur 后再写，避免打断键盘操作。
   */
  function applyHtml(card, html) {
    if (!card.el) return;
    var body = card.el.querySelector(".cs-card-body");
    if (!body) return;
    if (card.renderedHtml === html) return;
    if (card.el.contains(document.activeElement)) {
      card.pendingHtml = html;
      return;
    }
    card.renderedHtml = html;
    body.innerHTML = html;
    if (typeof card.onRender === "function") {
      try {
        card.onRender(card.el);
      } catch (error) {
        // 渲染回调失败不应影响卡片本身
      }
    }
  }

  function trim() {
    while (cards.length > MAX_CARDS) {
      var victim = cards.find((card) => card.final) || cards[0];
      victim?.el?.remove();
      cards = cards.filter((card) => card !== victim);
    }
  }

  /**
   * 追加或更新一张卡片（按 id 幂等）。
   * @param {{id:string, kind:string, html:string, tone?:string, final?:boolean, announce?:string, kindLabel?:string}} options
   */
  function emit(options) {
    var payload = options && typeof options === "object" ? options : {};
    var id = String(payload.id || "");
    if (!id) return null;
    var node = root();
    if (!node) return null;
    var container = ensureHost();
    bindScroll();
    var html = String(payload.html || "");
    // 判断是否贴底必须发生在插入历史卡片之前；否则首次恢复较长历史会被误报为新消息。
    var pinnedBeforeInsert = isPinned();
    var existing = findCard(id);
    if (existing) {
      if (typeof payload.onRender === "function") existing.onRender = payload.onRender;
      existing.kind = String(payload.kind || existing.kind);
      existing.tone = payload.tone ?? existing.tone;
      existing.final = Boolean(payload.final ?? existing.final);
      existing.busy = Boolean(payload.busy ?? !existing.final);
      existing.html = html;
      if (existing.el) {
        existing.el.dataset.csKind = existing.kind;
        existing.el.className = `chat-message assistant cs-card cs-kind-${String(existing.kind || "system").replace(/[^a-z0-9_-]/gi, "-")}`;
        if (existing.tone) existing.el.dataset.csTone = existing.tone;
        else delete existing.el.dataset.csTone;
        if (existing.final) {
          existing.el.dataset.csFinal = "true";
          existing.el.querySelector(".cs-card-body")?.removeAttribute("aria-busy");
        } else {
          delete existing.el.dataset.csFinal;
        }
        if (existing.busy) existing.el.querySelector(".cs-card-body")?.setAttribute("aria-busy", "true");
        else existing.el.querySelector(".cs-card-body")?.removeAttribute("aria-busy");
      } else if (container) {
        container.append(cardShell(existing));
      }
      applyHtml(existing, html);
      if (payload.announce && existing.renderedHtml === html) announce(payload.announce);
      return existing.el;
    }
    var card = {
      id: id,
      kind: String(payload.kind || "system"),
      html: html,
      tone: payload.tone || "",
      final: Boolean(payload.final),
      busy: Boolean(payload.busy ?? !payload.final),
      createdAt: Date.now(),
      el: null,
      renderedHtml: null,
      pendingHtml: null,
      onRender: typeof payload.onRender === "function" ? payload.onRender : null,
    };
    cards.push(card);
    if (!container) return null;
    container.append(cardShell(card));
    card.renderedHtml = html;
    if (card.onRender) {
      try {
        card.onRender(card.el);
      } catch (error) {
        // 忽略回调异常
      }
    }
    trim();
    if (restoring || payload.historical) return card.el;
    if (payload.announce) announce(payload.announce);
    if (pinnedBeforeInsert) scrollToBottom("auto");
    else {
      unreadCount += 1;
      syncPill();
    }
    return card.el;
  }

  /**
   * 执行中卡片的定点更新（不改结构，只改字段文本/进度）。
   * @param {string} id
   * @param {Record<string, {text?:string, value?:number}>} fields
   */
  function liveUpdate(id, fields) {
    var el = cardElement(id);
    var card = findCard(id);
    if (!el || !card || !fields) return null;
    Object.keys(fields).forEach((name) => {
      var patch = fields[name] || {};
      var target = el.querySelector(`[data-cs-field="${cssEscape(name)}"]`);
      if (target) {
        if (patch.text !== undefined) target.textContent = String(patch.text);
        if (patch.value !== undefined) {
          target.setAttribute("data-cs-value", String(patch.value));
          var bar = target.querySelector("[data-cs-bar]");
          if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(patch.value) || 0))}%`;
          if (target.hasAttribute("role")) {
            target.setAttribute("aria-valuenow", String(patch.value));
            target.setAttribute("aria-busy", patch.value < 100 ? "true" : "false");
          }
        }
      }
    });
    return el;
  }

  function finalize(id) {
    var card = findCard(id);
    if (!card) return null;
    card.final = true;
    if (card.el) {
      card.el.dataset.csFinal = "true";
      card.el.querySelector(".cs-card-body")?.removeAttribute("aria-busy");
    }
    return card.el || null;
  }

  function remove(id) {
    var key = String(id || "");
    clearAction(key);
    var card = findCard(key);
    if (!card) return;
    card.el?.remove();
    cards = cards.filter((item) => item !== card);
  }

  function clear() {
    cards.forEach((card) => card.el?.remove());
    cards = [];
    if (host) host.innerHTML = "";
    pendingActions.clear();
    syncActionBar();
    unreadCount = 0;
    syncPill();
  }

  /* ---------------- 待处理操作条（Action Bar） ---------------- */

  function ensureActionBar() {
    if (actionBarEl?.isConnected) return actionBarEl;
    actionBarEl = document.getElementById("csActionBar");
    if (!actionBarEl) {
      actionBarEl = document.createElement("div");
      actionBarEl.id = "csActionBar";
      actionBarEl.className = "cs-action-bar hidden";
      actionBarEl.setAttribute("role", "region");
      actionBarEl.setAttribute("aria-label", "待处理操作");
    }
    var form = document.querySelector("#chatForm");
    var container = panel();
    if (form && container) container.insertBefore(actionBarEl, form);
    else container?.append(actionBarEl);
    return actionBarEl;
  }

  function currentAction() {
    var list = [...pendingActions.entries()];
    if (!list.length) return null;
    var [id, value] = list[list.length - 1];
    return { id: id, ...value, ...(value.source?.isConnected ? {
      primaryLabel: value.source.textContent,
      disabled: value.source.disabled,
      reason: value.source.disabled ? value.source.title || value.reason || "正在处理，请稍候" : "",
    } : {}) };
  }

  function syncActionBar() {
    var bar = ensureActionBar();
    var action = currentAction();
    syncMobileAction(action);
    if (actionSource !== (action?.source || null)) {
      actionObserver?.disconnect();
      actionSource = action?.source || null;
      if (actionSource) {
        actionObserver = new MutationObserver(syncActionBar);
        actionObserver.observe(actionSource, { attributes: true, childList: true, characterData: true, subtree: true });
      }
    }
    if (!action) {
      bar.classList.add("hidden");
      bar.hidden = true;
      delete bar.dataset.csId;
      return;
    }
    bar.hidden = false;
    bar.classList.remove("hidden");
    bar.dataset.csId = String(action.id);
    if (!bar.querySelector('[data-cs-action="primary"]')) {
      bar.innerHTML = `
      <span class="cs-action-dot" aria-hidden="true"></span>
      <span class="cs-action-copy"><small data-cs-action-eyebrow></small><strong data-cs-action-summary></strong><small data-cs-action-reason></small></span>
      <button type="button" class="cs-action-view" data-cs-action="view"></button>
      <button type="button" class="primary cs-action-primary" data-cs-action="primary"></button>
    `;
      bar.querySelector('[data-cs-action="view"]').addEventListener("click", () => {
        var current = currentAction();
        if (typeof current?.onView === "function") current.onView();
        else if (current) focusCard(current.id);
      });
      bar.querySelector('[data-cs-action="primary"]').addEventListener("click", () => {
        var current = currentAction();
        if (!current?.disabled && typeof current?.onPrimary === "function") current.onPrimary();
      });
    }
    const setText = (node, text) => { if (node.textContent !== text) node.textContent = text; };
    const eyebrow = bar.querySelector('[data-cs-action-eyebrow]');
    setText(eyebrow, String(action.eyebrow ?? "待确认事项"));
    eyebrow.hidden = !eyebrow.textContent;
    setText(bar.querySelector('[data-cs-action-summary]'), String(action.summary || ""));
    setText(bar.querySelector('[data-cs-action-reason]'), String(action.reason || ""));
    for (const [name, label] of [["view", action.viewLabel], ["primary", action.primaryLabel]]) {
      const button = bar.querySelector(`[data-cs-action="${name}"]`);
      setText(button, String(label || ""));
      button.hidden = !label;
      button.disabled = name === "primary" && Boolean(action.disabled);
      button.title = name === "primary" ? String(action.reason || "") : "";
    }
  }

  function syncMobileAction(action) {
    let bar = document.getElementById("csMobileActionBar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "csMobileActionBar";
      bar.setAttribute("role", "region");
      bar.setAttribute("aria-label", "当前任务下一步");
      bar.innerHTML = '<span><strong></strong><small></small></span><button type="button" data-mobile-view>详情</button><button type="button" class="primary" data-mobile-primary></button>';
      document.body.append(bar);
      bar.querySelector('[data-mobile-view]').onclick = () => {
        document.querySelector('button[data-ct-compact-view="assistant"]')?.click();
        currentAction()?.onView?.();
      };
      bar.querySelector('[data-mobile-primary]').onclick = () => {
        const current = currentAction();
        if (!current || current.disabled) return;
        current.onPrimary?.();
      };
    }
    bar.hidden = !action;
    if (!action) return;
    const write = (node, value) => { if (node.textContent !== value) node.textContent = value; };
    write(bar.querySelector('strong'), String(action.summary || "当前任务"));
    write(bar.querySelector('small'), String(action.reason || ""));
    const button = bar.querySelector('[data-mobile-primary]');
    write(button, String(action.primaryLabel || ""));
    button.hidden = !action.primaryLabel;
    button.disabled = Boolean(action.disabled);
  }

  /**
   * 登记一个待处理操作。同时只会展示最新登记的一个（业务上互斥）。
   */
  function action(options) {
    var payload = options && typeof options === "object" ? options : {};
    var id = String(payload.id || "");
    if (!id) return;
    pendingActions.set(id, payload);
    syncActionBar();
    if (payload.announce) announce(payload.announce);
  }

  function clearAction(id) {
    if (!pendingActions.delete(String(id || ""))) return;
    syncActionBar();
  }

  function clearActions() {
    pendingActions.clear();
    syncActionBar();
  }

  /** 定位到某张卡片（待处理条「查看」用）。 */
  function focusCard(id) {
    var el = cardElement(id);
    if (!el) return;
    // Only move the conversation, never its fixed workspace ancestors.
    var container = root();
    if (container && container.contains(el)) {
      var viewport = container.getBoundingClientRect();
      var card = el.getBoundingClientRect();
      var top = viewport.top + container.clientTop;
      var bottom = top + container.clientHeight;
      if (card.top < top || card.bottom > bottom) {
        var offset = card.height > container.clientHeight
          ? card.top - top
          : card.top < top ? card.top - top : card.bottom - bottom;
        container.scrollTo({
          top: container.scrollTop + offset,
          behavior: global.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
        });
      }
    }
    el.tabIndex = -1;
    el.focus({ preventScroll: true });
    el.classList.remove("cs-flash");
    // 强制回流以重启动画
    void el.offsetWidth;
    el.classList.add("cs-flash");
    global.setTimeout(() => el.classList.remove("cs-flash"), 1600);
    unreadCount = 0;
    syncPill();
  }

  /* ---------------- 焦点挂起内容的补写 ---------------- */

  document.addEventListener("focusout", () => {
    queueMicrotask(() => {
    cards.forEach((card) => {
      if (!card.pendingHtml) return;
      if (card.el?.contains(document.activeElement)) return;
      var html = card.pendingHtml;
      card.pendingHtml = null;
      applyHtml(card, html);
      card.renderedHtml = html;
    });
    });
  }, true);

  /* ---------------- 对外接口 ---------------- */

  global.ClipTalkChatStream = {
    emit: emit,
    restore: restore,
    liveUpdate: liveUpdate,
    finalize: finalize,
    remove: remove,
    clear: clear,
    action: action,
    clearAction: clearAction,
    clearActions: clearActions,
    focusCard: focusCard,
    announce: announce,
    hostElement: hostElement,
    cardElement: cardElement,
    isPinned: isPinned,
    scrollToBottom: scrollToBottom,
    legacyDockEnabled: legacyDockEnabled,
    // 测试/调试用
    _cards: () => cards.slice(),
    _pendingActions: () => [...pendingActions.values()],
  };
})();
