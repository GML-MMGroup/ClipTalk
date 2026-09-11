#!/usr/bin/env node
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

function readArgs(argv) {
  const values = {};
  for (let index = 2; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) continue;
    const name = key.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      values[name] = "true";
    } else {
      values[name] = next;
      index += 1;
    }
  }
  return values;
}

const args = readArgs(process.argv);
if (args.help || !args.html || !args.frames) {
  console.log("Usage: render_html_motion.mjs --html page.html --frames out/frames --width 1080 --height 1920 --duration 1.5 --fps 24");
  process.exit(args.help ? 0 : 2);
}

const html = resolve(args.html);
const frames = resolve(args.frames);
const width = Math.max(64, Number.parseInt(args.width || "1080", 10));
const height = Math.max(64, Number.parseInt(args.height || "1920", 10));
const duration = Math.max(0.1, Number.parseFloat(args.duration || "1"));
const fps = Math.max(1, Math.min(60, Number.parseInt(args.fps || "24", 10)));
const frameCount = Math.max(1, Math.ceil(duration * fps));

await mkdir(frames, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 1,
    colorScheme: "dark",
  });
  await page.goto(pathToFileURL(html).href, { waitUntil: "networkidle" });
  for (let frame = 0; frame < frameCount; frame += 1) {
    const time = frame / fps;
    const progress = frameCount <= 1 ? 1 : frame / (frameCount - 1);
    await page.evaluate(
      (payload) => {
        window.__cliptalkFrame = payload;
        document.documentElement.style.setProperty("--frame", String(payload.frame));
        document.documentElement.style.setProperty("--time", String(payload.time));
        document.documentElement.style.setProperty("--progress", String(payload.progress));
        if (typeof window.__cliptalkSetFrame === "function") {
          window.__cliptalkSetFrame(payload);
        }
      },
      { frame, time, progress, duration, fps },
    );
    await page.screenshot({
      path: `${frames}/frame-${String(frame + 1).padStart(6, "0")}.png`,
      type: "png",
      animations: "disabled",
    });
  }
} finally {
  await browser.close();
}
