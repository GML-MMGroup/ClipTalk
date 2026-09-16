import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { chromium } from "playwright";

const html = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
const styles = [...html.matchAll(/href="\/static\/([^"?]+\.css)/g)]
  .map((match) => readFileSync(new URL(`../../static/${match[1]}`, import.meta.url), "utf8"))
  .join("\n");

test("hidden workbench and overlay roots never participate in layout", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    await page.setContent(`<style>${styles}</style><main id="workspace" class="studio"><section class="review-panel"><section id="reviewView" class="review-view hidden timeline-hidden"></section></section></main><aside id="candidateDrawer" class="candidate-drawer hidden" inert></aside>`);
    const state = await page.evaluate(() => ["reviewView", "candidateDrawer"].map((id) => {
      const node = document.getElementById(id);
      const rect = node.getBoundingClientRect();
      return { id, display: getComputedStyle(node).display, width: rect.width, height: rect.height };
    }));
    assert.deepEqual(state, [
      { id: "reviewView", display: "none", width: 0, height: 0 },
      { id: "candidateDrawer", display: "none", width: 0, height: 0 },
    ]);
  } finally { await browser.close(); }
});

test("global drawers, modals and notices follow one semantic layer order", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.setContent(`<style>${styles}</style><aside id="appSidebar"></aside><div id="drawerBackdrop"></div><aside id="candidateDrawer" class="candidate-drawer open"></aside><section id="secondaryEditor"></section><div id="actionConfirm"></div><div id="toastRegion" class="toast-region"></div>`);
    const layers = await page.evaluate(() => Object.fromEntries(["appSidebar", "drawerBackdrop", "candidateDrawer", "secondaryEditor", "actionConfirm", "toastRegion"].map((id) => [id, Number(getComputedStyle(document.getElementById(id)).zIndex)])));
    assert.ok(layers.appSidebar < layers.drawerBackdrop);
    assert.ok(layers.drawerBackdrop < layers.candidateDrawer);
    assert.ok(layers.candidateDrawer < layers.secondaryEditor);
    assert.ok(layers.secondaryEditor < layers.actionConfirm);
    assert.ok(layers.actionConfirm < layers.toastRegion);
  } finally { await browser.close(); }
});

test("panel roots declare closed accessibility state in the application shell", () => {
  assert.match(html, /id="candidateDrawer"[^>]*class="candidate-drawer hidden"[^>]*aria-modal="true"[^>]*aria-hidden="true"[^>]*inert/);
  assert.match(html, /id="secondaryEditor"[^>]*aria-hidden="true"[^>]*inert/);
  assert.match(html, /id="timelinePrecisionDrawer"[^>]*aria-hidden="true"[^>]*inert/);
  assert.match(html, /id="subtitleReview"[^>]*aria-hidden="true"/);
});
