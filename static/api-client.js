(function createClipTalkApi(global) {
  const storageKey = "cliptalk_access_token";
  const sessionKey = "cliptalk_browser_session";
  let sessionAccessToken = global.sessionStorage.getItem(storageKey) || "";
  let browserSession = global.sessionStorage.getItem(sessionKey) || "";

  if (!browserSession) {
    browserSession = global.crypto?.randomUUID?.() || `session_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    global.sessionStorage.setItem(sessionKey, browserSession);
  }

  class ApiError extends Error {
    constructor(message, { status = 0, code = "request_failed", detail = null } = {}) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
      this.detail = detail;
    }
  }

  let accessTokenPrompt = null;
  function requestAccessToken() {
    if (accessTokenPrompt) return accessTokenPrompt;
    const dialog = global.document.querySelector("#accessTokenDialog");
    const form = dialog?.querySelector("form");
    const input = dialog?.querySelector("input");
    const cancel = dialog?.querySelector("[data-auth-cancel]");
    if (!dialog || !form || !input || typeof dialog.showModal !== "function") {
      return Promise.resolve(global.prompt("此 ClipTalk 服务需要访问令牌：")?.trim() || "");
    }
    accessTokenPrompt = new Promise((resolve) => {
      const finish = (value) => {
        form.removeEventListener("submit", submit);
        cancel?.removeEventListener("click", dismiss);
        dialog.close();
        accessTokenPrompt = null;
        resolve(value);
      };
      const submit = (event) => { event.preventDefault(); finish(input.value.trim()); };
      const dismiss = () => finish("");
      form.addEventListener("submit", submit);
      cancel?.addEventListener("click", dismiss);
      input.value = "";
      dialog.showModal();
      global.requestAnimationFrame(() => input.focus());
    });
    return accessTokenPrompt;
  }

  function requestHeaders(options = {}) {
    const headers = new Headers(options.headers || {});
    const body = options.body;
    if (
      !headers.has("Content-Type")
      && typeof body === "string"
      && /^[\[{]/.test(body.trim())
    ) {
      headers.set("Content-Type", "application/json");
    }
    if (sessionAccessToken) headers.set("X-Highlight-Token", sessionAccessToken);
    headers.set("X-ClipTalk-Session", browserSession);
    return headers;
  }

  async function authenticateAndRetry(path, options, allowTokenPrompt) {
    let response;
    try {
      response = await fetch(path, {
        ...options,
        headers: requestHeaders(options),
        credentials: "same-origin",
      });
    } catch (error) {
      throw new ApiError(error?.message || "网络连接失败", { status: 0, code: "network_error" });
    }
    if (response.status === 401 && allowTokenPrompt) {
      global.sessionStorage.removeItem(storageKey);
      sessionAccessToken = "";
      const supplied = await requestAccessToken();
      if (supplied) {
        sessionAccessToken = supplied;
        global.sessionStorage.setItem(storageKey, supplied);
        return authenticateAndRetry(path, options, false);
      }
    }
    return response;
  }

  async function errorFromResponse(response) {
    const body = await response.json().catch(() => ({}));
    const detail = body?.detail ?? body?.error ?? null;
    const message = typeof detail === "object"
      ? detail?.message || detail?.detail || `请求失败（${response.status}）`
      : detail || `请求失败（${response.status}）`;
    const code = typeof detail === "object"
      ? detail?.code || body?.code || "request_failed"
      : body?.code || "request_failed";
    return new ApiError(message, { status: response.status, code, detail });
  }

  async function request(path, options = {}, allowTokenPrompt = true) {
    const response = await authenticateAndRetry(path, options, allowTokenPrompt);
    if (!response.ok) throw await errorFromResponse(response);
    return response.json().catch(() => ({}));
  }

  async function requestJson(path, options = {}, allowTokenPrompt = true) {
    const headers = new Headers(options.headers || {});
    headers.set("Content-Type", "application/json");
    const body = typeof options.body === "string"
      ? options.body
      : JSON.stringify(options.body ?? {});
    return request(path, { ...options, headers, body }, allowTokenPrompt);
  }

  async function requestBlob(path, options = {}, allowTokenPrompt = true) {
    const response = await authenticateAndRetry(path, options, allowTokenPrompt);
    if (!response.ok) throw await errorFromResponse(response);
    return response.blob();
  }

  function clearAccessToken() {
    sessionAccessToken = "";
    global.sessionStorage.removeItem(storageKey);
  }

  global.ClipTalkApi = Object.freeze({ request, requestJson, requestBlob, clearAccessToken, ApiError });
})(window);
