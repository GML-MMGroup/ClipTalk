/* ClipTalk × OpenUI：宿主侧桥接层
 *
 * 职责：
 *   1. 提供 window.ClipTalkOpenUI，默认关闭 —— 关闭时页面行为与接入前完全一致
 *   2. 懒加载 iframe 沙箱：未开启时绝不请求 3.6MB 的 bundle
 *   3. 把宿主结构化数据转译后送进沙箱，并把沙箱高度/主题同步回来
 *
 * 开启方式：URL 加 ?openui=1，或在控制台执行 ClipTalkOpenUI.enable()
 */
(function (global) {
  "use strict";

  var CHANNEL = "cliptalk-openui";
  var SANDBOX_URL = "/static/openui-sandbox.html?v=20260917-openui-1";

  // 从 cliptalk-tokens.css 同步给沙箱的变量（保持视觉一致）
  var THEME_TOKENS = [
    "--ct-canvas",
    "--ct-panel",
    "--ct-raised",
    "--ct-border",
    "--ct-text",
    "--ct-text-secondary",
    "--ct-text-muted",
    "--ct-primary",
    "--ct-on-primary",
    "--ct-selected",
  ];

  var state = {
    enabled: false,
    frame: null,
    mount: null,
    ready: false,
    pending: null,
  };

  function urlFlag() {
    try {
      var value = new URLSearchParams(global.location.search).get("openui");
      if (value === "1") return true;
      if (value === "0") return false;
    } catch (error) {
      /* location 不可用时按默认关闭处理 */
    }
    return false;
  }

  function collectTokens() {
    var tokens = {};
    try {
      var computed = global.getComputedStyle(document.documentElement);
      THEME_TOKENS.forEach(function (name) {
        var value = computed.getPropertyValue(name);
        if (value) tokens[name] = value.trim();
      });
    } catch (error) {
      /* 取不到就不同步，沙箱用自己的默认样式 */
    }
    return tokens;
  }

  function post(message) {
    if (!state.frame || !state.frame.contentWindow) return;
    message.channel = CHANNEL;
    state.frame.contentWindow.postMessage(message, global.location.origin);
  }

  function ensureFrame(mount) {
    if (state.frame && state.mount === mount && state.frame.isConnected) return state.frame;
    if (!mount) return null;
    state.mount = mount;
    state.ready = false;
    mount.textContent = "";
    var frame = document.createElement("iframe");
    frame.src = SANDBOX_URL;
    frame.title = "ClipTalk 活动记录";
    frame.setAttribute("scrolling", "no");
    frame.style.cssText = "width:100%;border:0;display:block;min-height:64px;color-scheme:normal;";
    mount.appendChild(frame);
    state.frame = frame;
    return frame;
  }

  global.addEventListener("message", function (event) {
    if (event.origin !== global.location.origin) return;
    var data = event.data || {};
    if (data.channel !== CHANNEL) return;

    if (data.type === "ready") {
      state.ready = true;
      post({ type: "theme", tokens: collectTokens() });
      if (state.pending) {
        post(state.pending);
        state.pending = null;
      }
    } else if (data.type === "height") {
      if (state.frame && data.height) state.frame.style.height = data.height + 8 + "px";
    }
    // data.type === "action" 预留：目前活动流无交互，后续接剪辑计划卡时在此分发
  });

  function sendCode(code) {
    if (state.ready) post({ type: "render", code: code });
    else state.pending = { type: "render", code: code };
  }

  var api = {
    get enabled() {
      return state.enabled;
    },

    enable: function () {
      state.enabled = true;
      return this;
    },

    disable: function () {
      state.enabled = false;
      if (state.frame && state.frame.parentNode) state.frame.parentNode.removeChild(state.frame);
      state.frame = null;
      state.mount = null;
      return this;
    },

    /* 渲染活动流。返回 true 表示已接管渲染，false 表示宿主应走原生 innerHTML 路径 */
    renderActivity: function (mount, items) {
      if (!state.enabled) return false;
      try {
        var adapter = global.ClipTalkOpenUIAdapter;
        if (!adapter) return false;
        if (!ensureFrame(mount)) return false;
        sendCode(adapter.activityToOpenUILang(items));
        return true;
      } catch (error) {
        return false;
      }
    },
  };

  // 主题切换时同步给沙箱，避免明暗不一致
  if (typeof MutationObserver === "function") {
    new MutationObserver(function () {
      if (state.enabled) post({ type: "theme", tokens: collectTokens() });
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }

  state.enabled = urlFlag();
  if (state.enabled && global.console) {
    global.console.info("[ClipTalk] OpenUI 渲染已开启（?openui=1）；执行 ClipTalkOpenUI.disable() 可关闭");
  }

  global.ClipTalkOpenUI = api;
})(window);
