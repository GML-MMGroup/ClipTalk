import React from "react";
import { createRoot } from "react-dom/client";
import { ArrowRight, FilmSlate, PaperPlaneTilt } from "@phosphor-icons/react";

const roots = new Map();

function iconFor(name) {
  if (name === "send") {
    return <PaperPlaneTilt size={17} weight="bold" mirrored={false} aria-hidden="true" />;
  }
  if (name === "film-slate") {
    return <FilmSlate size={28} weight="duotone" mirrored={false} aria-hidden="true" />;
  }
  if (name === "arrow-right") {
    return <ArrowRight size={18} weight="bold" mirrored={false} aria-hidden="true" />;
  }
  return null;
}

function renderIcon(node) {
  if (!node || roots.has(node)) return;
  const icon = iconFor(node.dataset.uiIcon);
  if (!icon) return;
  const root = createRoot(node);
  root.render(icon);
  roots.set(node, root);
}

function sync(scope = document) {
  if (!scope) return;
  if (scope.matches?.("[data-ui-icon]")) renderIcon(scope);
  scope.querySelectorAll?.("[data-ui-icon]").forEach(renderIcon);
  for (const [node, root] of roots) {
    if (node.isConnected) continue;
    root.unmount();
    roots.delete(node);
  }
}

const observer = new MutationObserver((mutations) => {
  mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
    if (node.nodeType === Node.ELEMENT_NODE) sync(node);
  }));
});
observer.observe(document.documentElement, { childList: true, subtree: true });

window.UIIconsBridge = { sync };
sync(document);
