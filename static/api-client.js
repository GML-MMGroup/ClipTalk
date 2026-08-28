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
    constructor(message, {
      status = 0, code = "request_failed", detail = null,
      recoveryAction = "retry", requestId = "",
    } = {}) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
      this.detail = detail;
      this.recoveryAction = recoveryAction;
      this.requestId = requestId;
    }
  }

  const statusFallbacks = Object.freeze({
    400: "请求内容不完整，请检查后重试。",
    401: "访问凭证已失效，请重新验证。",
    404: "请求的任务或资源不存在，可能已被移动或删除。",
    409: "任务状态已经变化，请刷新后重试。",
    413: "上传内容超过允许大小。",
    422: "请求参数格式无效，请检查后重试。",
    429: "操作过于频繁，请稍后再试。",
    500: "服务暂时无法完成请求，请重试。",
    503: "处理服务暂时不可用，请稍后重试或检查模型设置。",
  });

  const recoveryLabels = Object.freeze({
    authenticate: "重新验证访问凭证",
    refresh: "刷新任务状态",
    refresh_and_retry: "刷新后重试",
    wait_and_retry: "稍后重试",
    check_input: "检查输入后重试",
    check_settings_or_retry: "检查模型设置或稍后重试",
    retry: "请重试",
  });

  function formatErrorMessage(error) {
    const message = String(error?.message || "请求失败");
    const recovery = recoveryLabels[error?.recoveryAction] || recoveryLabels.retry;
    const requestId = String(error?.requestId || "");
    return `${message}${recovery && !message.includes(recovery) ? ` · ${recovery}` : ""}${requestId ? ` · 请求编号 ${requestId}` : ""}`;
  }

  let accessTokenPrompt = null;
  function requestAccessToken() {
    if (accessTokenPrompt) return accessTokenPrompt;
    const dialog = global.document.querySelector("#accessTokenDialog");
    const form = dialog?.querySelector("form");
    const input = dialog?.querySelector("input");
    const cancel = dialog?.querySelector("[data-auth-cancel]");
    if (!dialog || !form || !input || typeof dialog.showModal !== "function") {
      return Promise.resolve("");
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
      const apiError = new ApiError(error?.message || "网络连接失败", {
        status: 0, code: "network_error", recoveryAction: "retry",
      });
      apiError.message = formatErrorMessage(apiError);
      throw apiError;
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

  function createResponseError(body = {}, status = 0, headerRequestId = "") {
    const structured = body?.error && typeof body.error === "object" ? body.error : null;
    const detail = structured || (body?.detail ?? null);
    const message = structured?.message
      || (typeof body?.detail === "object" ? body.detail?.message || body.detail?.detail : body?.detail)
      || statusFallbacks[status]
      || "请求失败，请稍后重试。";
    const code = structured?.code || body?.code
      || (typeof body?.detail === "object" ? body.detail?.code : "")
      || `http_${status}`;
    const recoveryAction = structured?.recoveryAction
      || (status === 409 ? "refresh_and_retry" : status === 429 ? "wait_and_retry" : "retry");
    const requestId = structured?.requestId || body?.requestId || headerRequestId || "";
    const error = new ApiError(message, {
      status, code, detail, recoveryAction, requestId,
    });
    error.message = formatErrorMessage(error);
    return error;
  }

  async function errorFromResponse(response) {
    const body = await response.json().catch(() => ({}));
    return createResponseError(body, response.status, response.headers.get("X-Request-ID") || "");
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

  global.ClipTalkApi = Object.freeze({
    request, requestJson, requestBlob, clearAccessToken, ApiError,
    createResponseError, formatErrorMessage, recoveryLabels,
  });
})(window);
