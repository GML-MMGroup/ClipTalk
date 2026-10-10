import React from "react";
import { createRoot } from "react-dom/client";
import { ImageLoader, InlineLoader, TextLoader } from "generative-loaders";
import "generative-loaders/styles.css";
import { loaderLifecycle } from "./loader-lifecycle.js";

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

const segmenter = typeof Intl.Segmenter === "function" ? new Intl.Segmenter("zh", { granularity: "grapheme" }) : null;
function CascadeText({ text, paused, color }) {
  const host = React.useRef(null);
  const previous = React.useRef("");
  const characters = segmenter ? Array.from(segmenter.segment(text), item => item.segment) : Array.from(text);
  React.useLayoutEffect(() => {
    const old = previous.current;
    const start = text.startsWith(old) ? (segmenter ? Array.from(segmenter.segment(old)).length : Array.from(old).length) : 0;
    previous.current = text;
    const nodes = host.current?.children || [];
    if (paused) {
      for (const node of nodes) node.getAnimations?.().forEach(animation => animation.finish());
      return;
    }
    for (let index = start; index < nodes.length; index++) {
      if (!nodes[index].textContent.trim()) continue;
      nodes[index].animate?.([{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], {
        duration: 240, delay: Math.min(35, (index - start) * 5), fill: "backwards", easing: "cubic-bezier(.2,.75,.25,1)",
      });
    }
  }, [text, paused]);
  // Actual accessible text, without a live-region announcement per token.
  return <span ref={host} className="tl-loader vp-text-loader" data-variant="cascade" data-paused={String(paused)} aria-live="off" style={{ color, whiteSpace: "pre-wrap" }}>
    {characters.map((char, index) => <span key={index} className="tl-char" style={{ display: /\s/.test(char) ? "inline" : "inline-block" }}>{char}</span>)}
  </span>;
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function readOptions(element, overrides = {}) {
  const kind = overrides.kind || element.dataset.generativeLoader || "inline";
  const speed = numberOr(overrides.speed ?? element.dataset.loaderSpeed, 1);
  const color = overrides.color || element.dataset.loaderColor || "currentColor";
  const paused = Boolean(overrides.paused) || lifecycle.paused(element);
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
        "aria-label": String(overrides.text ?? element.dataset.loaderText ?? element.textContent ?? ""),
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
    lifecycle.track(element);
    let record = roots.get(element);
    const retainedOptions = { ...record?.options, ...options };
    const descriptor = readOptions(element, retainedOptions);
    if (record && record.kind !== descriptor.kind) {
      record.root.unmount();
      roots.delete(element);
      record = null;
    }
    if (!record) {
      record = { root: createRoot(element), kind: descriptor.kind };
      roots.set(element, record);
    }
    record.options = retainedOptions;
    const signature = JSON.stringify(descriptor);
    if (record.signature === signature) return true;
    record.signature = signature;
    const Component = descriptor.kind === "text" ? (descriptor.props.variant === "cascade" ? CascadeText : TextLoader) : descriptor.kind === "image" ? ImageLoader : InlineLoader;
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
  return render(element, options);
}

function clear(element, { preserveText = false } = {}) {
  if (!element) return;
  lifecycle.forget(element);
  const text = preserveText ? String(element.dataset.loaderText || "") : "";
  const record = roots.get(element);
  if (record) {
    record.root.unmount();
    roots.delete(element);
  }
  if (preserveText) element.textContent = text;
}

const lifecycle = loaderLifecycle({ selector: "[data-generative-loader]", activeAttribute: "data-loader-active", pausedAttribute: "data-loader-paused", render, clear });
const sync = lifecycle.sync;

window.GenerativeLoadersBridge = { render, update, clear, sync };
sync();
