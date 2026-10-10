/* DOM 合同测试：把源码正则断言升级为真实浏览器断言。
 *
 * agent-contract / contracts / aspect-exports 里"元素存在"类的断言
 * （assert.match(html, /id="..."/)）在这里以真浏览器加载生产页面后
 * 直接查询 DOM 的方式验证；代码架构类契约（函数存在、API 调用路径）
 * 保留在原文件中，不在 DOM 层重复。
 */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { chromium } from "playwright";

const root = resolve(fileURLToPath(new URL("../../", import.meta.url)), "");

async function staticApp() {
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, "http://localhost").pathname;
    if (path.startsWith("/api/")) {
      response.setHeader("Content-Type", "application/json");
      const value = path === "/api/health" ? { uiContractVersion: 2, ok: true, ffmpeg: true, ffprobe: true, visionConfigured: true, capabilityStatus: "degraded", capabilityLabel: "部分功能不可用", capabilityIssues: ["语音识别不可用"] }
        : path === "/api/setup/status" ? { complete: true, canCreateTask: true, canUseAgent: true, steps: [] }
        : path === "/api/jobs" ? { jobs: [{ id: "cancelled", filename: "产品.mp4", status: "cancelled", presentation: { schemaVersion: 2, key: "cancelled", group: "cancelled", label: "已取消" } }] }
        : { providers: [], skills: [], outputs: [], workspaces: [] };
      response.end(JSON.stringify(value)); return;
    }
    const file = resolve(root, "static", path === "/" ? "index.html" : path.replace(/^\/static\//, ""));
    if (!file.startsWith(resolve(root, "static") + "/")) { response.writeHead(404); response.end(); return; }
    try {
      response.setHeader("Content-Type", ({ ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2", ".png": "image/png" })[extname(file)] || "application/octet-stream");
      response.end(await readFile(file));
    } catch { response.writeHead(404); response.end(); return; }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  return { url: `http://127.0.0.1:${server.address().port}`, close: () => new Promise(resolve => server.close(resolve)) };
}

test("the rendered home shell carries the Agent workspace chrome contract", async () => {
  const server = await staticApp();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const failures = [];
    page.on("requestfailed", request => failures.push(`${request.url()} ${request.failure()?.errorText}`));
    await page.goto(server.url);
    await page.waitForFunction(() => document.querySelectorAll('link[rel="stylesheet"][media="print"]').length === 0);
    await page.waitForFunction(() => document.querySelector("#homeView").dataset.homeState === "ready");

    for (const id of [
      "agentPlanDock", "agentPlanDrawer", "agentPlanDrawerActivity",
      "agentSkillMenuButton", "agentSkillSelect", "composerSuggestion",
      "chatLegacyModeButton", "agentSettingsForm", "inputPrompt",
      "coverDownloadButton", "packageDownloadButton", "coverIntroButton",
      "adjustCoverButton", "timelineCoverTrack",
    ]) {
      assert.equal(await page.locator(`#${id}`).count(), 1, `#${id} must exist exactly once in the live DOM`);
    }
    const menuTarget = await page.locator("#agentSkillMenuButton").getAttribute("aria-controls");
    assert.ok(menuTarget, "#agentSkillMenuButton must reference its menu");
    assert.equal(await page.locator(`#${menuTarget}`).count(), 1, "the referenced menu must exist in the DOM");

    // versioned asset references, verified against the real document
    const versioned = await page.evaluate(() => ({
      scripts: [...document.querySelectorAll("script[src]")].map(node => node.src).filter(src => src.includes("/static/")),
      styles: [...document.querySelectorAll('link[rel="stylesheet"]')].map(node => node.href),
    }));
    assert.ok(versioned.scripts.length >= 3, "the shell loads its scripts");
    for (const src of versioned.scripts) assert.match(src, /\?v=/, `unversioned script: ${src}`);
    for (const href of versioned.styles) assert.match(href, /\?v=/, `unversioned stylesheet: ${href}`);
    for (const name of ["styles.css", "workbench.css"]) {
      assert.ok(versioned.styles.some(href => href.includes(`/static/${name}`)), `${name} must stay on the production chain`);
    }

    // every static subresource actually loaded
    await page.waitForLoadState("networkidle");
    assert.deepEqual(failures, [], "no static asset may fail to load");
    await page.close();
  } finally { await browser.close(); await server.close(); }
});

test("the delivery export panel exposes one checkbox per aspect in the real DOM", async () => {
  const server = await staticApp();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(server.url);
    await page.waitForFunction(() => document.querySelectorAll('link[rel="stylesheet"][media="print"]').length === 0);

    const boxes = page.locator("[data-aspect-export]");
    assert.equal(await boxes.count(), 3, "one checkbox per delivery aspect");
    const values = await boxes.evaluateAll(nodes => nodes.map(node => String(node.value || "")));
    assert.deepEqual(values.sort(), ["16:9", "1:1", "9:16"]);
    assert.equal(await page.locator("[data-aspect-export]:checked").count(), 0, "aspects start unchecked");
    assert.equal(await page.locator("[data-aspect-export][value='9:16']").getAttribute("type"), "checkbox");
    await page.close();
  } finally { await browser.close(); await server.close(); }
});

test("agent settings surface keeps the Skills 与 Plugins section", async () => {
  const server = await staticApp();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(server.url);
    await page.waitForFunction(() => document.querySelectorAll('link[rel="stylesheet"][media="print"]').length === 0);
    assert.equal(await page.getByText("Skills 与 Plugins", { exact: true }).count(), 1);
    await page.close();
  } finally { await browser.close(); await server.close(); }
});
