export default [
  {
    files: ["static/api-client.js", "static/app.js", "static/review-actions.js", "static/runtime-errors.js", "static/task-creation.js", "static/workspace-state.js"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "script",
      globals: {
        AbortController: "readonly", Blob: "readonly", CSS: "readonly", Element: "readonly",
        Error: "readonly", Event: "readonly", EventSource: "readonly", File: "readonly",
        FormData: "readonly", Headers: "readonly", HTMLMediaElement: "readonly", Map: "readonly",
        MutationObserver: "readonly", ResizeObserver: "readonly", Set: "readonly", TextDecoder: "readonly",
        URL: "readonly", URLSearchParams: "readonly", WebSocket: "readonly", alert: "readonly",
        cancelAnimationFrame: "readonly", clearInterval: "readonly", clearTimeout: "readonly",
        confirm: "readonly", console: "readonly", crypto: "readonly", document: "readonly",
        fetch: "readonly", getComputedStyle: "readonly", history: "readonly", localStorage: "readonly",
        location: "readonly", navigator: "readonly", performance: "readonly", prompt: "readonly",
        requestAnimationFrame: "readonly", sessionStorage: "readonly", setInterval: "readonly",
        setTimeout: "readonly", window: "readonly",
      },
    },
    rules: {
      "no-redeclare": "error",
      "no-undef": "error",
      "no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
];
