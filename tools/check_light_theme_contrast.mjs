#!/usr/bin/env node
import { writeFile } from "node:fs/promises";
import { chromium } from "playwright";

function readArgs(argv) {
  const values = {};
  for (let index = 2; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) continue;
    const name = key.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) values[name] = true;
    else {
      values[name] = next;
      index += 1;
    }
  }
  return values;
}

function parseColor(value) {
  const match = String(value || "").match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
  if (!match) return null;
  return {
    r: Number(match[1]),
    g: Number(match[2]),
    b: Number(match[3]),
    a: match[4] === undefined ? 1 : Number(match[4]),
    raw: value,
  };
}

function blend(top, bottom) {
  const topAlpha = Number.isFinite(top.a) ? top.a : 1;
  const bottomAlpha = Number.isFinite(bottom.a) ? bottom.a : 1;
  const alpha = topAlpha + bottomAlpha * (1 - topAlpha);
  if (alpha <= 0) return { r: 255, g: 255, b: 255, a: 1 };
  return {
    r: Math.round((top.r * topAlpha + bottom.r * bottomAlpha * (1 - topAlpha)) / alpha),
    g: Math.round((top.g * topAlpha + bottom.g * bottomAlpha * (1 - topAlpha)) / alpha),
    b: Math.round((top.b * topAlpha + bottom.b * bottomAlpha * (1 - topAlpha)) / alpha),
    a: alpha,
  };
}

function luminance(color) {
  const channel = (value) => {
    const normalized = value / 255;
    return normalized <= 0.03928
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
}

function contrastRatio(foreground, background) {
  const fg = foreground.a < 1 ? blend(foreground, background) : foreground;
  const light = Math.max(luminance(fg), luminance(background));
  const dark = Math.min(luminance(fg), luminance(background));
  return (light + 0.05) / (dark + 0.05);
}

function colorString(color) {
  return `rgb(${color.r}, ${color.g}, ${color.b})`;
}

async function setupClipTalkWorkspace(page, theme) {
  await page.evaluate((themeName) => {
    document.documentElement.dataset.theme = themeName;
    document.body.classList.add("ct-workbench-v4");
    document.body.dataset.shellMode = "workspace";
    document.body.dataset.shellView = "workspace";
    const workspace = document.querySelector("#workspace");
    workspace?.classList.remove("home-mode");
    workspace?.classList.add("new-task-workbench", "director-merged");
    const chatInput = document.querySelector("#chatInput");
    if (chatInput) chatInput.disabled = false;
    const sendButton = document.querySelector("#sendButton");
    if (sendButton) sendButton.disabled = false;
    const suggestion = document.querySelector("#composerSuggestion");
    if (suggestion) {
      suggestion.classList.remove("hidden");
      suggestion.textContent = "试试：“找出所有汽车相关画面，合成竖屏视频，并在顶部添加对应字幕。”";
    }
  }, theme);
}

function usage() {
  return `Usage: node tools/check_light_theme_contrast.mjs [options]

Options:
  --url URL              Page to audit. Default: http://127.0.0.1:5191/
  --min NUMBER           Minimum contrast ratio. Default: 4.5
  --width NUMBER         Viewport width. Default: 1600
  --height NUMBER        Viewport height. Default: 950
  --selector SELECTOR    Elements to hover and audit.
  --no-workspace         Do not force the ClipTalk workspace state.
  --view VIEW            Read-only view: editor, cover, settings, library.
  --include-offscreen    Include offscreen elements.
  --report PATH          Write full JSON report.
`;
}

const args = readArgs(process.argv);
if (args.help) {
  console.log(usage());
  process.exit(0);
}

const url = String(args.url || "http://127.0.0.1:5191/");
const minimum = Number.parseFloat(String(args.min || "4.5"));
const width = Math.max(320, Number.parseInt(String(args.width || "1600"), 10));
const height = Math.max(320, Number.parseInt(String(args.height || "950"), 10));
const selector = String(args.selector || 'button,a,summary,select,input,textarea,p,small,label,h1,h2,h3,strong,span,[role="button"]');
const theme = "light";

if (!Number.isFinite(minimum) || minimum <= 0) {
  console.error("--min must be a positive number.");
  process.exit(2);
}

const browser = await chromium.launch({ headless: true });
let result;
try {
  const page = await browser.newPage({ viewport: { width, height }, colorScheme: theme });
  await page.route('**/api/**', route => route.request().method() === 'GET' ? route.continue() : route.abort());
  await page.addInitScript((themeName) => {
    localStorage.setItem("cliptalk-theme", themeName);
    localStorage.setItem("theme", themeName);
    document.documentElement.dataset.theme = themeName;
  }, theme);
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20_000 });
  await page.waitForFunction(() => typeof window.ClipTalkTheme?.apply === "function" && window.ClipTalkAppShell, null, { timeout: 20_000 });
  const jobId = new URL(url).hash.match(/(?:^#|&)job=([^&]+)/)?.[1];
  if (jobId) await page.waitForFunction(id => window.ClipTalkCurrentJobId?.() === id, decodeURIComponent(jobId));
  else await page.waitForFunction(() => document.querySelector('#homeView')?.dataset.homeState !== 'loading');
  if (args.view) {
    await page.evaluate(async view => {
      if (view === 'editor') {
        const job = window.ClipTalkCurrentJobSnapshot?.();
        const sessionId = job?.activeEditSessionId || job?.editSessions?.[0]?.id;
        if (!sessionId) throw new Error('No existing edit session to inspect');
        await window.ClipTalkOpenAgentTimeline({ sessionId, reviewPendingProposal: true });
      } else if (view === 'cover') {
        if (!window.ClipTalkOpenCoverTimeline?.()) throw new Error('No cover candidates to inspect');
      } else if (view === 'settings' || view === 'library') {
        window.ClipTalkAppShell.showView(view, { route: false });
      } else throw new Error('Unsupported view');
    }, args.view);
    await page.waitForTimeout(400);
  } else if (!args["no-workspace"]) await setupClipTalkWorkspace(page, theme);

  const elements = await page.$$(selector);
  const checked = [];
  const failures = [];
  const unmeasured = [];
  for (const element of elements) {
    const metadata = await element.evaluate((node, includeOffscreen) => {
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      const directText = [...node.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join(' ');
      const text = String(directText || (node.matches('button,a,summary,select,input,textarea') && !node.querySelector('.sr-only') ? node.textContent || node.value : "") || "")
        .trim()
        .replace(/\s+/g, " ");
      const visible = rect.width > 1
        && rect.height > 1
        && style.visibility !== "hidden"
        && style.display !== "none"
        && !node.closest('[inert],[aria-hidden="true"],.sr-only')
        && (includeOffscreen || (rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight));
      return {
        id: node.id || "",
        tag: node.tagName.toLowerCase(),
        className: String(node.className || ""),
        text: text.slice(0, 100),
        visible,
        disabled: Boolean(node.closest(':disabled,[aria-disabled="true"]')),
        large: parseFloat(style.fontSize) >= 24 || (parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700),
        interactive: node.matches('button,a,summary,select,[role="button"]'),
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      };
    }, Boolean(args["include-offscreen"]));
    if (!metadata.visible || metadata.disabled || !metadata.text) continue;

    if (metadata.interactive) {
      await element.hover({ timeout: 500 }).catch(() => {});
      await page.waitForTimeout(25);
    }
    const styles = await element.evaluate((node) => {
      const backgroundLayers = [];
      let imageBackground = false;
      for (let current = node; current; current = current.parentElement) {
        const color = getComputedStyle(current).backgroundColor;
        if (getComputedStyle(current).backgroundImage !== 'none') imageBackground = true;
        if (color && color !== "transparent") backgroundLayers.push(color);
      }
      backgroundLayers.push(getComputedStyle(document.documentElement).backgroundColor || "rgb(255, 255, 255)");
      const style = getComputedStyle(node);
      return {
        color: style.color,
        backgroundColor: style.backgroundColor,
        borderColor: style.borderColor,
        backgroundLayers,
        imageBackground,
      };
    });
    if (styles.imageBackground) { unmeasured.push(metadata); continue; }

    let background = { r: 255, g: 255, b: 255, a: 1 };
    for (const layer of styles.backgroundLayers.toReversed()) {
      const color = parseColor(layer);
      if (color) background = blend(color, background);
    }
    const foreground = parseColor(styles.color);
    if (!foreground) continue;
    const contrast = contrastRatio(foreground, background);
    const entry = {
      ...metadata,
      color: styles.color,
      effectiveBackground: colorString(background),
      ownBackground: styles.backgroundColor,
      borderColor: styles.borderColor,
      contrast: Number(contrast.toFixed(2)),
    };
    checked.push(entry);
    if (contrast < (metadata.large ? Math.min(3, minimum) : minimum)) failures.push(entry);
  }
  result = { url, theme, minimum, checked: checked.length, failures, unmeasured: unmeasured.length };
} finally {
  await browser.close();
}

if (args.report) await writeFile(String(args.report), `${JSON.stringify(result, null, 2)}\n`);

console.log(JSON.stringify({
  url: result.url,
  theme: result.theme,
  minimum: result.minimum,
  checked: result.checked,
  failures: result.failures.length,
  unmeasured: result.unmeasured,
}, null, 2));

if (result.failures.length) {
  for (const failure of result.failures) {
    console.error(`${failure.contrast.toFixed(2)} ${failure.tag}${failure.id ? `#${failure.id}` : ""} ${failure.text}`);
  }
  process.exitCode = 1;
}
