import React from "react";
import { createRoot } from "react-dom/client";
import { BorderBeam } from "border-beam";

const records = new Map();
const validSizes = new Set(["sm", "md", "line", "pulse-inner", "pulse-outside"]);
const validColors = new Set(["colorful", "mono", "ocean", "sunset"]);
const validThemes = new Set(["dark", "light", "auto"]);
const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");

function numberInRange(value, fallback, min, max) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(min, Math.min(max, parsed)) : fallback;
}

function readOptions(element, overrides = {}) {
  const requestedSize = overrides.size || element.dataset.beamSize || "md";
  const requestedColor = overrides.colorVariant || overrides.color || element.dataset.beamColor || "sunset";
  const requestedTheme = overrides.theme || element.dataset.beamTheme || "dark";
  const dataActive = element.dataset.beamActive !== "false";
  return {
    size: validSizes.has(requestedSize) ? requestedSize : "md",
    colorVariant: validColors.has(requestedColor) ? requestedColor : "sunset",
    theme: validThemes.has(requestedTheme) ? requestedTheme : "dark",
    strength: numberInRange(overrides.strength ?? element.dataset.beamStrength, .35, 0, 1),
    duration: numberInRange(overrides.duration ?? element.dataset.beamDuration, 3.2, .7, 20),
    brightness: numberInRange(overrides.brightness ?? element.dataset.beamBrightness, 1.08, .3, 2),
    saturation: numberInRange(overrides.saturation ?? element.dataset.beamSaturation, .92, 0, 2),
    hueRange: numberInRange(overrides.hueRange ?? element.dataset.beamHueRange, 12, 0, 90),
    borderRadius: numberInRange(overrides.borderRadius ?? element.dataset.beamRadius, 12, 0, 80),
    active: Boolean(overrides.active ?? dataActive) && !Boolean(reducedMotion?.matches),
  };
}

function BeamLayer({ options }) {
  return (
    <BorderBeam
      {...options}
      className="vp-border-beam-overlay"
      aria-hidden="true"
    >
      <span className="vp-border-beam-surface" />
    </BorderBeam>
  );
}

function ensureRecord(element) {
  let record = records.get(element);
  if (record) return record;
  const mount = document.createElement("span");
  mount.className = "vp-border-beam-mount";
  mount.setAttribute("aria-hidden", "true");
  element.classList.add("vp-border-beam-host");
  element.prepend(mount);
  record = { mount, root: createRoot(mount) };
  records.set(element, record);
  return record;
}

function render(element, options = {}) {
  if (!element || element.dataset.beamFailed === "true") return false;
  try {
    const record = ensureRecord(element);
    record.root.render(<BeamLayer options={readOptions(element, options)} />);
    return true;
  } catch (error) {
    element.dataset.beamFailed = "true";
    console.warn("Border beam unavailable", error);
    return false;
  }
}

function update(element, options = {}) {
  if (!element) return false;
  if (options.size != null) element.dataset.beamSize = String(options.size);
  if (options.colorVariant != null || options.color != null) {
    element.dataset.beamColor = String(options.colorVariant ?? options.color);
  }
  if (options.theme != null) element.dataset.beamTheme = String(options.theme);
  if (options.strength != null) element.dataset.beamStrength = String(options.strength);
  if (options.duration != null) element.dataset.beamDuration = String(options.duration);
  if (options.brightness != null) element.dataset.beamBrightness = String(options.brightness);
  if (options.saturation != null) element.dataset.beamSaturation = String(options.saturation);
  if (options.hueRange != null) element.dataset.beamHueRange = String(options.hueRange);
  if (options.active != null) element.dataset.beamActive = String(Boolean(options.active));
  return render(element, options);
}

function clear(element) {
  if (!element) return;
  const record = records.get(element);
  if (record) {
    record.root.unmount();
    record.mount.remove();
    records.delete(element);
  }
  element.classList.remove("vp-border-beam-host");
}

function shouldRender(element) {
  return element.dataset.beamActive !== "false"
    && !element.classList.contains("hidden")
    && !element.closest(".hidden");
}

function sync(scope = document) {
  if (!scope) return;
  const elements = [];
  if (scope.matches?.("[data-border-beam]")) elements.push(scope);
  scope.querySelectorAll?.("[data-border-beam]").forEach((element) => elements.push(element));
  elements.forEach((element) => shouldRender(element) ? render(element) : clear(element));
  for (const [element] of records) {
    if (!element.isConnected || !element.matches("[data-border-beam]") || !shouldRender(element)) clear(element);
  }
}

let observerFrame = 0;
const observer = new MutationObserver((mutations) => {
  const scopes = new Set();
  mutations.forEach((mutation) => {
    if (mutation.type === "attributes") scopes.add(mutation.target);
    mutation.addedNodes?.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE) scopes.add(node);
    });
  });
  cancelAnimationFrame(observerFrame);
  observerFrame = requestAnimationFrame(() => scopes.forEach((scope) => sync(scope)));
});
observer.observe(document.documentElement, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ["class", "data-beam-active", "data-beam-size", "data-beam-strength", "data-beam-duration", "data-beam-brightness", "data-beam-saturation", "data-beam-hue-range"],
});

reducedMotion?.addEventListener?.("change", () => sync(document));
window.BorderBeamBridge = { render, update, clear, sync };
sync();
