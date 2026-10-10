// Shared by the existing loader bundles; no additional production script.
export function loaderLifecycle({ selector, activeAttribute, pausedAttribute, render, clear }) {
  const tracked = new Set();
  const outside = new WeakMap();
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  let frame = 0;
  const candidates = new Set();
  const intersection = new IntersectionObserver(entries => {
    for (const entry of entries) {
      outside.set(entry.target, !entry.isIntersecting);
      if (tracked.has(entry.target)) render(entry.target);
    }
  });

  function track(element) {
    if (tracked.has(element)) return;
    tracked.add(element);
    intersection.observe(element);
  }

  function forget(element) {
    tracked.delete(element);
    intersection.unobserve(element);
    outside.delete(element);
  }

  function paused(element) {
    return document.hidden || reduced.matches || outside.get(element) === true
      || element.getAttribute(activeAttribute) === "false"
      || element.getAttribute(pausedAttribute) === "true"
      || Boolean(element.closest('[hidden], .hidden, [inert], [data-motion-state="stopping"], [data-motion-state="inactive"]'))
      || !element.getClientRects().length;
  }

  function sync(scope = document) {
    if (scope.matches?.(selector)) candidates.add(scope);
    scope.querySelectorAll?.(selector).forEach(element => candidates.add(element));
    for (const element of candidates) {
      if (element.isConnected && element.matches(selector)) render(element);
    }
    candidates.clear();
    for (const element of tracked) {
      if (!element.isConnected || !element.matches(selector)) clear(element);
      else render(element);
    }
  }

  function schedule() {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; sync(nullScope); });
  }
  const nullScope = {};
  const observer = new MutationObserver(mutations => {
    let changed = false;
    for (const mutation of mutations) {
      // React/Preact and animation frames inside a loader are not app changes.
      const owner = mutation.target.closest?.("[data-generative-loader], [data-thinking-orb]");
      if (owner && (owner !== mutation.target || mutation.type === "childList")) continue;
      changed = true;
      for (const node of mutation.addedNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        if (node.matches(selector)) candidates.add(node);
        node.querySelectorAll(selector).forEach(element => candidates.add(element));
      }
    }
    if (changed) schedule();
  });
  observer.observe(document.documentElement, {
    childList: true, subtree: true, attributes: true,
    attributeFilter: [activeAttribute, pausedAttribute, selector.slice(1, -1), "hidden", "inert", "class", "style", "data-motion-state", "data-theme"],
  });
  document.addEventListener("visibilitychange", () => sync(nullScope));
  window.addEventListener("cliptalk:themechange", () => sync(nullScope));
  reduced.addEventListener("change", () => sync(nullScope));
  return { track, forget, paused, sync };
}
