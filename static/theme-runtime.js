(function () {
  "use strict";

  const storageKey = "cliptalk-color-theme-v1";
  const themes = new Set(["dark", "light"]);
  const defaultTheme = "light";
  const root = document.documentElement;

  function storedTheme() {
    try {
      const value = localStorage.getItem(storageKey);
      return themes.has(value) ? value : null;
    } catch {
      return null;
    }
  }

  function syncToggle(theme) {
    const button = document.querySelector("#themeToggle");
    if (!button) return;
    const dark = theme === "dark";
    const nextLabel = dark ? "浅色" : "深色";
    const label = button.querySelector("span");
    if (label) label.textContent = dark ? "深色" : "浅色";
    button.setAttribute("aria-pressed", String(dark));
    button.setAttribute("aria-label", `切换到${nextLabel}主题`);
    button.title = `切换到${nextLabel}主题`;
  }

  function applyTheme(theme, { persist = false } = {}) {
    const normalized = themes.has(theme) ? theme : defaultTheme;
    root.dataset.theme = normalized;
    root.style.colorScheme = normalized;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      normalized === "light" ? "#f3f3f0" : "#102625",
    );
    syncToggle(normalized);
    if (persist) {
      try { localStorage.setItem(storageKey, normalized); }
      catch { /* Theme persistence is optional. */ }
    }
    window.dispatchEvent(new CustomEvent("cliptalk:themechange", { detail: { theme: normalized } }));
    return normalized;
  }

  function toggleTheme() {
    return applyTheme(root.dataset.theme === "light" ? "dark" : "light", { persist: true });
  }

  applyTheme(storedTheme() || defaultTheme);
  window.ClipTalkTheme = { apply: applyTheme, current: () => root.dataset.theme || defaultTheme, toggle: toggleTheme };

  document.addEventListener("DOMContentLoaded", () => {
    syncToggle(root.dataset.theme || defaultTheme);
    document.querySelector("#themeToggle")?.addEventListener("click", toggleTheme);
  }, { once: true });
})();
