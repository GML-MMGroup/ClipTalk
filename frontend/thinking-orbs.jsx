import React from "react";
import { createRoot } from "react-dom/client";
import { ThinkingOrb } from "thinking-orbs";

const roots = new Map();
const validStates = new Set(["working", "searching", "solving", "listening", "composing", "shaping"]);

function readOptions(element, overrides = {}) {
  const requestedState = overrides.state || element.dataset.orbState || "working";
  return {
    state: validStates.has(requestedState) ? requestedState : "working",
    size: Number(overrides.size || element.dataset.orbSize) === 64 ? 64 : 20,
    speed: Number(overrides.speed || element.dataset.orbSpeed || 1),
    theme: overrides.theme || element.dataset.orbTheme || "light",
    paused: Boolean(overrides.paused),
    "aria-label": overrides.label || element.dataset.orbLabel || "AI 正在处理",
  };
}

function render(element, options = {}) {
  if (!element) return;
  let root = roots.get(element);
  if (!root) {
    root = createRoot(element);
    roots.set(element, root);
  }
  root.render(<ThinkingOrb {...readOptions(element, options)} />);
}

function clear(element) {
  const root = roots.get(element);
  if (!root) return;
  root.unmount();
  roots.delete(element);
}

function sync(scope = document) {
  scope.querySelectorAll?.("[data-thinking-orb]").forEach((element) => {
    if (element.classList.contains("hidden") || element.dataset.orbActive === "false") clear(element);
    else render(element);
  });
  for (const [element] of roots) {
    if (!element.isConnected) clear(element);
  }
}

const observer = new MutationObserver(() => sync());
observer.observe(document.documentElement, { childList: true, subtree: true });

window.ThinkingOrbsBridge = { render, clear, sync };
sync();
