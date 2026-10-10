import React from "react";
import { createRoot } from "react-dom/client";
import { ThinkingOrb } from "thinking-orbs";
import { loaderLifecycle } from "./loader-lifecycle.js";

const roots = new Map();
const validStates = new Set(["working", "searching", "solving", "listening", "composing", "shaping"]);

function readOptions(element, overrides = {}) {
  const requestedState = overrides.state || element.dataset.orbState || "working";
  return {
    state: validStates.has(requestedState) ? requestedState : "working",
    size: Number(overrides.size || element.dataset.orbSize) === 64 ? 64 : 20,
    speed: Number(overrides.speed || element.dataset.orbSpeed || 1),
    theme: overrides.theme || document.documentElement.dataset.theme || "light",
    paused: Boolean(overrides.paused) || lifecycle.paused(element),
    "aria-label": overrides.label || element.dataset.orbLabel || "AI 正在处理",
  };
}

function render(element, options = {}) {
  if (!element) return;
  lifecycle.track(element);
  let record = roots.get(element);
  if (!record) {
    record = { root: createRoot(element) };
    roots.set(element, record);
  }
  record.options = { ...record.options, ...options };
  const props = readOptions(element, record.options);
  const signature = JSON.stringify(props);
  if (record.signature === signature) return;
  record.signature = signature;
  record.root.render(<ThinkingOrb {...props} />);
}

function clear(element) {
  lifecycle.forget(element);
  const record = roots.get(element);
  if (!record) return;
  record.root.unmount();
  roots.delete(element);
}

const lifecycle = loaderLifecycle({ selector: "[data-thinking-orb]", activeAttribute: "data-orb-active", pausedAttribute: "data-orb-paused", render, clear });
const sync = lifecycle.sync;

window.ThinkingOrbsBridge = { render, clear, sync };
sync();
