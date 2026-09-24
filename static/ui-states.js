/**
 * ClipTalk 统一界面状态原语
 *
 * 背景：空状态曾散落在 app.js / app-shell.js / agent-workspace.js 三处，
 *   使用 6 种 CSS 类（rail-empty / agent-activity-empty / app-sidebar-empty /
 *   app-library-empty / current-person-empty / voice-profile-empty），
 *   且存在两套语气（「暂无…」与「还没有…」），20 处里仅 1 处给了引导动作。
 * 加载态同样各自实现（17 种），而 generative-loaders 已提供同类能力。
 *
 * 本文件是空状态 / 加载态 / 受管轮询的唯一出口。
 *
 * 约束（来自 tools/audit_frontend_ownership.py，改前务必重读）：
 *   - 生产 CSS 数量上限 12 且当前已超限 → 本文件不新增 CSS 文件，
 *     .ct-empty / .ct-loading 基础类写在 app-shell.css 末尾。
 *   - 禁止出现 ct-v4- / ct-workbench-v4 / ct-faithful-v3 / data-ct-ui 等退役选择器。
 *   - 禁止在非 cliptalk-tokens.css 中定义 --ct-canvas 等色板 token。
 */
(function (global) {
  "use strict";

  var ESCAPE_MAP = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  };

  /** 仅用于文本节点与属性值；不要传给已经含标签的字符串。 */
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return ESCAPE_MAP[ch];
    });
  }

  // 只允许无值的布尔型 data 属性，避免拼接出属性注入
  var SAFE_ATTR = /^[a-zA-Z-][a-zA-Z0-9-]*$/;

  /**
   * 统一空状态。
   *
   * @param {object} options
   * @param {string} options.title         主文案（必填，统一用「还没有…」语气）
   * @param {string} [options.hint]        说明 / 下一步引导（强烈建议填写）
   * @param {string} [options.actionLabel] 引导动作文案
   * @param {string} [options.actionAttr]  动作按钮的 data-* 属性名，仅支持无值形式
   * @param {string} [options.icon]        可选图标字符
   * @param {string} [options.className]   附加的局部修饰类（保留原有布局差异）
   * @param {"block"|"inline"} [options.variant="block"]
   * @returns {string} HTML 字符串；title 为空时返回空串
   */
  function emptyStateHtml(options) {
    var opts = options || {};
    var title = String(opts.title || "").trim();
    if (!title) return "";

    var variant = opts.variant === "inline" ? " ct-empty--inline" : "";
    var extra = opts.className ? " " + String(opts.className) : "";
    var parts = ['<div class="ct-empty' + variant + extra + '" role="status">'];

    if (opts.icon) {
      parts.push('<span class="ct-empty__icon" aria-hidden="true">' + escapeHtml(opts.icon) + "</span>");
    }
    parts.push("<strong>" + escapeHtml(title) + "</strong>");
    if (opts.hint) {
      parts.push("<p>" + escapeHtml(opts.hint) + "</p>");
    }
    if (opts.actionLabel && opts.actionAttr && SAFE_ATTR.test(opts.actionAttr)) {
      parts.push(
        '<button type="button" class="ct-empty__action" ' +
          opts.actionAttr +
          ">" +
          escapeHtml(opts.actionLabel) +
          "</button>"
      );
    }
    parts.push("</div>");
    return parts.join("");
  }

  /**
   * 统一加载态。
   *
   * @param {object} options
   * @param {string} [options.label="加载中"]
   * @param {string} [options.hint]      次要说明
   * @param {number} [options.rows=3]    骨架条数量（1–6）
   * @param {boolean} [options.skeleton=true] 是否渲染骨架条
   * @param {string} [options.className] 附加的局部修饰类
   * @returns {string} HTML 字符串
   */
  function loadingStateHtml(options) {
    var opts = options || {};
    var label = String(opts.label || "加载中").trim();
    var extra = opts.className ? " " + String(opts.className) : "";
    var parts = ['<div class="ct-loading' + extra + '" role="status" aria-live="polite">'];

    parts.push("<strong>" + escapeHtml(label) + "</strong>");
    if (opts.skeleton !== false) {
      // 注意：不能用 Number(opts.rows) || 3 —— 显式传入 0 会被当成「未指定」
      var requested = Number(opts.rows);
      var rows = Number.isFinite(requested)
        ? Math.max(1, Math.min(6, Math.round(requested)))
        : 3;
      var bars = "";
      for (var i = 0; i < rows; i += 1) {
        bars += '<span class="ct-loading__bar" style="--ct-loading-index:' + i + '"></span>';
      }
      parts.push('<div class="ct-loading__bars" aria-hidden="true">' + bars + "</div>");
    }
    if (opts.hint) {
      parts.push("<p>" + escapeHtml(opts.hint) + "</p>");
    }
    parts.push("</div>");
    return parts.join("");
  }

  /**
   * 受管轮询。
   *
   * 解决原先裸 setInterval 的两个问题：
   *   1. 页面切到后台仍持续发请求（loadHealth / loadServiceState 均无可见性判断）；
   *   2. 没有句柄，无法停止。
   * 行为：隐藏时跳过本次执行；重新可见时立刻补一次。
   *
   * @param {Function} fn         轮询任务，可返回 Promise
   * @param {number} intervalMs   间隔毫秒
   * @param {object} [options]
   * @param {Function} [options.onError]
   * @returns {{stop: Function, refresh: Function, interval: number}}
   */
  function createPolling(fn, intervalMs, options) {
    var opts = options || {};
    var timer = null;
    var stopped = false;
    var inFlight = false;

    function tick() {
      if (stopped || (global.document && global.document.hidden)) return;
      if (inFlight) return; // 上一次还没回来，不叠请求
      inFlight = true;
      try {
        var result = fn();
        if (result && typeof result.then === "function") {
          result.then(clear, fail);
        } else {
          clear();
        }
      } catch (error) {
        fail(error);
      }
    }

    function clear() {
      inFlight = false;
    }

    function fail(error) {
      inFlight = false;
      if (typeof opts.onError === "function") opts.onError(error);
    }

    function onVisibility() {
      if (global.document && !global.document.hidden) tick();
    }

    timer = global.setInterval(tick, intervalMs);
    if (global.document) {
      global.document.addEventListener("visibilitychange", onVisibility);
    }

    return {
      interval: intervalMs,
      refresh: tick,
      stop: function () {
        stopped = true;
        if (timer !== null) {
          global.clearInterval(timer);
          timer = null;
        }
        if (global.document) {
          global.document.removeEventListener("visibilitychange", onVisibility);
        }
      }
    };
  }

  global.ClipTalkUIStates = {
    escapeHtml: escapeHtml,
    emptyStateHtml: emptyStateHtml,
    loadingStateHtml: loadingStateHtml,
    createPolling: createPolling
  };
})(window);
