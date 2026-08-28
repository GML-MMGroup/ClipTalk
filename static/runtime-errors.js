(function installClipTalkRuntimeErrors(global) {
  const reported = new Map();
  const duplicateWindowMs = 60_000;

  function pathOnly(value) {
    try {
      const url = new URL(String(value || ""), global.location.href);
      return url.pathname;
    } catch {
      return "";
    }
  }

  function errorDetails(value) {
    if (value instanceof Error) {
      return {
        name: String(value.name || "Error"),
        message: String(value.message || ""),
        stack: String(value.stack || ""),
      };
    }
    return { name: "Error", message: String(value || "未知浏览器错误"), stack: "" };
  }

  function report(payload) {
    const key = `${payload.kind}|${payload.name}|${payload.message}|${payload.scriptPath}|${payload.line || 0}`;
    const now = Date.now();
    if (now - Number(reported.get(key) || 0) < duplicateWindowMs) return;
    reported.set(key, now);
    if (reported.size > 100) {
      for (const [entry, createdAt] of reported) {
        if (now - createdAt >= duplicateWindowMs) reported.delete(entry);
      }
    }
    global.ClipTalkApi?.requestJson("/api/client-errors", {
      method: "POST",
      body: {
        ...payload,
        pagePath: global.location.pathname,
        scriptPath: pathOnly(payload.scriptPath),
        jobId: String(global.ClipTalkCurrentJobId?.() || ""),
        build: "20260821-runtime-errors-1",
      },
    }, false).catch((error) => global.console?.warn?.("浏览器错误上报失败", error));
  }

  global.addEventListener("error", (event) => {
    if (!event.error && String(event.message || "") === "Script error.") return;
    const details = errorDetails(event.error || event.message);
    report({
      kind: "error",
      ...details,
      scriptPath: pathOnly(event.filename),
      line: Number(event.lineno) || null,
      column: Number(event.colno) || null,
    });
  });

  global.addEventListener("unhandledrejection", (event) => {
    report({ kind: "unhandledrejection", ...errorDetails(event.reason), scriptPath: "", line: null, column: null });
  });

  global.ClipTalkRuntimeErrors = Object.freeze({ report });
})(window);
