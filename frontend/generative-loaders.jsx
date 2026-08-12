import React from "react";
import { createRoot } from "react-dom/client";
import { ImageLoader, InlineLoader, TextLoader } from "generative-loaders";
import "generative-loaders/styles.css";

const roots = new Map();
const textVariants = new Set([
  "decode", "typewriter", "skeleton", "cascade", "focus", "wipe", "flip", "redact",
  "line", "terminal", "wave", "dissolve", "slice", "tracking", "coalesce", "fragments",
]);
const inlineVariants = new Set([
  "glyph", "matrix", "orbit", "ripple", "signal", "spark", "rotor", "pixel-drift",
  "chomp", "snake", "fold", "gravity", "domino", "aperture",
]);
const imageVariants = new Set([
  "skeleton", "bands", "tiles", "scan", "pixel-grid", "resolution", "focus", "shutter", "contour",
]);

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function readOptions(element, overrides = {}) {
  const kind = overrides.kind || element.dataset.generativeLoader || "inline";
  const speed = numberOr(overrides.speed ?? element.dataset.loaderSpeed, 1);
  const color = overrides.color || element.dataset.loaderColor || "currentColor";
  const paused = overrides.paused ?? element.dataset.loaderPaused === "true";
  const label = overrides.label || element.dataset.loaderLabel || "AI 正在处理";
  if (kind === "text") {
    const variant = overrides.variant || element.dataset.loaderVariant || "cascade";
    return {
      kind,
      props: {
        text: String(overrides.text ?? element.dataset.loaderText ?? element.textContent ?? ""),
        variant: textVariants.has(variant) ? variant : "cascade",
        speed,
        color,
        paused,
        className: "vp-text-loader",
        "aria-label": label,
      },
    };
  }
  if (kind === "image") {
    const variant = overrides.variant || element.dataset.loaderVariant || "resolution";
    return {
      kind,
      props: {
        variant: imageVariants.has(variant) ? variant : "resolution",
        size: overrides.size || element.dataset.loaderSize || "100%",
        radius: overrides.radius || element.dataset.loaderRadius || "10px",
        speed,
        color,
        paused,
        className: "vp-image-loader",
        label,
      },
    };
  }
  const variant = overrides.variant || element.dataset.loaderVariant || "glyph";
  return {
    kind: "inline",
    props: {
      variant: inlineVariants.has(variant) ? variant : "glyph",
      size: overrides.size || element.dataset.loaderSize || 18,
      speed,
      color,
      paused,
      className: "vp-inline-loader",
      label: element.dataset.loaderAnnounce === "true" ? label : undefined,
    },
  };
}

function render(element, options = {}) {
  if (!element || element.dataset.loaderFailed === "true") return false;
  try {
    const descriptor = readOptions(element, options);
    let record = roots.get(element);
    if (record && record.kind !== descriptor.kind) {
      record.root.unmount();
      roots.delete(element);
      record = null;
    }
    if (!record) {
      record = { root: createRoot(element), kind: descriptor.kind };
      roots.set(element, record);
    }
    const Component = descriptor.kind === "text" ? TextLoader : descriptor.kind === "image" ? ImageLoader : InlineLoader;
    record.root.render(<Component {...descriptor.props} />);
    return true;
  } catch (error) {
    element.dataset.loaderFailed = "true";
    console.warn("Generative loader unavailable", error);
    return false;
  }
}

function update(element, options = {}) {
  if (!element) return;
  if (options.text != null) element.dataset.loaderText = String(options.text);
  if (options.label != null) element.dataset.loaderLabel = String(options.label);
  render(element, options);
}

function clear(element, { preserveText = false } = {}) {
  if (!element) return;
  const text = preserveText ? String(element.dataset.loaderText || "") : "";
  const record = roots.get(element);
  if (record) {
    record.root.unmount();
    roots.delete(element);
  }
  if (preserveText) element.textContent = text;
}

function sync(scope = document) {
  if (!scope) return;
  const elements = [];
  if (scope.matches?.("[data-generative-loader]")) elements.push(scope);
  scope.querySelectorAll?.("[data-generative-loader]").forEach((element) => elements.push(element));
  elements.forEach((element) => {
    if (element.classList.contains("hidden") || element.dataset.loaderActive === "false") clear(element);
    else render(element);
  });
  for (const [element] of roots) {
    if (!element.isConnected) clear(element);
  }
}

let observerFrame = 0;
const observer = new MutationObserver((mutations) => {
  const candidates = [];
  mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
    if (node.nodeType === Node.ELEMENT_NODE) candidates.push(node);
  }));
  if (!candidates.length) return;
  cancelAnimationFrame(observerFrame);
  observerFrame = requestAnimationFrame(() => candidates.forEach((node) => sync(node)));
});
observer.observe(document.documentElement, { childList: true, subtree: true });

window.GenerativeLoadersBridge = { render, update, clear, sync };
sync();
