import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { marked } from "marked";
import octicons from "@primer/octicons";

const toolDirectory = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(toolDirectory, "..");
const sourcePath = resolve(projectRoot, "README_zh.md");
const outputPath = resolve(projectRoot, "README_zh-preview.html");
const indexPath = resolve(projectRoot, "index.html");
const assetDirectory = resolve(projectRoot, "readme-preview-assets");

const markdown = await readFile(sourcePath, "utf8");
const slugCounts = new Map();
const githubMark = octicons["mark-github"].toSVG({ width: 32, height: 32, class: "gh-logo" });

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function plainText(tokens = []) {
  return tokens.map((token) => {
    if (token.tokens) return plainText(token.tokens);
    return token.text || token.raw || "";
  }).join("").replace(/<[^>]+>/g, "").trim();
}

function githubSlug(value) {
  const base = value
    .toLowerCase()
    .replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}\uFE0F]/gu, "")
    .replace(/[^\p{Letter}\p{Number}\s_-]/gu, "")
    .trim()
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-") || "section";
  const seen = slugCounts.get(base) || 0;
  slugCounts.set(base, seen + 1);
  return seen ? `${base}-${seen}` : base;
}

const renderer = new marked.Renderer();
renderer.heading = function heading({ tokens, depth }) {
  const label = plainText(tokens);
  const id = githubSlug(label);
  const content = this.parser.parseInline(tokens);
  return `<h${depth} id="${escapeHtml(id)}" class="heading-element"><a class="anchor" href="#${escapeHtml(id)}" aria-label="Permalink: ${escapeHtml(label)}">#</a>${content}</h${depth}>\n`;
};
renderer.code = function code({ text, lang }) {
  const language = String(lang || "").trim().split(/\s+/)[0];
  if (language === "mermaid") {
    return `<div class="mermaid" aria-label="流程图">${escapeHtml(text)}</div>\n`;
  }
  const className = language ? ` class="language-${escapeHtml(language)}"` : "";
  return `<pre><code${className}>${escapeHtml(text)}</code></pre>\n`;
};

let article = marked.parse(markdown, {
  gfm: true,
  breaks: false,
  renderer,
});

const previewImages = [
  ["完成.png", "workspace-complete.png"],
  ["上传视频-对话需求.png", "brief-confirmation.png"],
  ["中间过程.png", "sensevoice-analysis.png"],
  ["中间过程2.png", "vlm-overview.png"],
  ["中间过程3.png", "vlm-refinement.png"],
  ["事件解释.png", "event-evidence.png"],
  ["时间线.png", "event-timeline.png"],
  ["分析完成.png", "automatic-composition.png"],
];

await mkdir(assetDirectory, { recursive: true });
for (const [sourceName, previewName] of previewImages) {
  await copyFile(resolve(projectRoot, "photo", sourceName), resolve(assetDirectory, previewName));
  article = article.replaceAll(`./photo/${sourceName}`, `./readme-preview-assets/${previewName}`);
}

article = article
  .replace('<img src="./readme-preview-assets/workspace-complete.png"', '<img fetchpriority="high" src="./readme-preview-assets/workspace-complete.png"')
  .replaceAll('<img src="./readme-preview-assets/', '<img loading="lazy" src="./readme-preview-assets/');

article = article
  .replace(/<blockquote>\s*<p>\[!(IMPORTANT|NOTE|WARNING|TIP|CAUTION)\]\s*\n?([\s\S]*?)<\/p>\s*<\/blockquote>/g, (_match, kind, body) => {
    const labels = { IMPORTANT: "Important", NOTE: "Note", WARNING: "Warning", TIP: "Tip", CAUTION: "Caution" };
    return `<div class="markdown-alert markdown-alert-${kind.toLowerCase()}"><p class="markdown-alert-title">${labels[kind]}</p><p>${body.trim()}</p></div>`;
  })
  .replaceAll("<table>", '<div class="table-wrapper"><table>')
  .replaceAll("</table>", "</table></div>");

const sourceEscaped = escapeHtml(markdown);
const generatedAt = new Intl.DateTimeFormat("zh-CN", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
}).format(new Date());

const html = `<!doctype html>
<html lang="zh-CN" data-color-mode="auto" data-light-theme="light" data-dark-theme="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="light dark" />
    <meta name="description" content="ClipTalk README_zh.md GitHub-style preview" />
    <title>ClipTalk / README_zh.md</title>
    <link rel="stylesheet" href="./node_modules/@primer/css/dist/primer.css" />
    <style>
      :root { --preview-width: 1280px; }
      * { box-sizing: border-box; }
      html { scroll-padding-top: 128px; }
      body { min-width: 320px; margin: 0; color: var(--fgColor-default); background: var(--bgColor-default); }
      a { color: var(--fgColor-accent); }
      .gh-global {
        position: sticky; top: 0; z-index: 30; min-height: 64px; padding: 12px 24px;
        display: flex; align-items: center; gap: 16px; color: #f0f6fc; background: #25292e;
      }
      .gh-mark { width: 38px; height: 38px; display: grid; place-items: center; color: #f0f6fc; text-decoration: none; }
      .gh-mark .gh-logo { width: 32px; height: 32px; fill: currentColor; }
      .gh-search { width: min(360px, 28vw); min-height: 34px; padding: 6px 12px; border: 1px solid #57606a; border-radius: 6px; color: #8c959f; background: #25292e; }
      .gh-global nav { margin-left: auto; display: flex; align-items: center; gap: 10px; }
      .gh-global nav a { color: #f0f6fc; font-weight: 600; text-decoration: none; }
      .repo-header { border-bottom: 1px solid var(--borderColor-default); background: var(--bgColor-muted); }
      .repo-identity { max-width: var(--preview-width); margin: auto; padding: 17px 24px 10px; display: flex; align-items: center; gap: 8px; font-size: 20px; }
      .repo-identity a { font-weight: 600; text-decoration: none; }
      .repo-identity .visibility { margin-left: 6px; padding: 2px 8px; border: 1px solid var(--borderColor-default); border-radius: 999px; color: var(--fgColor-muted); font-size: 12px; font-weight: 500; }
      .repo-nav { max-width: var(--preview-width); margin: auto; padding: 0 16px; display: flex; gap: 4px; overflow-x: auto; }
      .repo-nav a { position: relative; flex: none; padding: 10px 12px 12px; color: var(--fgColor-default); text-decoration: none; }
      .repo-nav a.active { font-weight: 600; }
      .repo-nav a.active::after { content: ""; position: absolute; right: 8px; bottom: 0; left: 8px; height: 2px; border-radius: 2px; background: #fd8c73; }
      .page { max-width: var(--preview-width); margin: 0 auto; padding: 24px; }
      .file-path { margin-bottom: 16px; display: flex; align-items: center; gap: 7px; color: var(--fgColor-muted); font-size: 14px; }
      .file-path a { font-weight: 600; text-decoration: none; }
      .file-shell { overflow: hidden; border: 1px solid var(--borderColor-default); border-radius: 6px; background: var(--bgColor-default); }
      .file-toolbar { min-height: 48px; padding: 8px 12px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--borderColor-default); background: var(--bgColor-muted); }
      .file-toolbar strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .file-toolbar small { color: var(--fgColor-muted); }
      .view-tabs { margin-left: auto; display: flex; align-items: center; }
      .view-tabs button { min-height: 32px; padding: 5px 12px; border: 1px solid var(--borderColor-default); color: var(--fgColor-default); background: var(--button-default-bgColor-rest); font-weight: 600; cursor: pointer; }
      .view-tabs button:first-child { border-radius: 6px 0 0 6px; }
      .view-tabs button:last-child { margin-left: -1px; border-radius: 0 6px 6px 0; }
      .view-tabs button[aria-selected="true"] { position: relative; z-index: 1; border-color: var(--borderColor-accent-emphasis); color: var(--fgColor-accent); background: var(--bgColor-accent-muted); }
      .readme-frame { padding: clamp(24px, 5vw, 64px); }
      .markdown-body { max-width: 1012px; margin: 0 auto; color: var(--fgColor-default); background: transparent; }
      .markdown-body > div[align="center"]:first-child { margin-bottom: 24px; }
      .markdown-body img { height: auto; border-radius: 6px; }
      .markdown-body .heading-element { position: relative; }
      .markdown-body .anchor { position: absolute; right: 100%; width: 28px; padding-right: 8px; color: var(--fgColor-accent); font-weight: 400; text-align: right; text-decoration: none; opacity: 0; }
      .markdown-body .heading-element:hover .anchor, .markdown-body .anchor:focus-visible { opacity: 1; }
      .markdown-body .table-wrapper { width: 100%; overflow-x: auto; }
      .markdown-body .table-wrapper table { display: table; width: max-content; min-width: 100%; }
      .markdown-body .markdown-alert { padding: 8px 16px; border-left: 4px solid var(--borderColor-accent-emphasis); }
      .markdown-body .markdown-alert-title { margin-bottom: 4px; color: var(--fgColor-accent); font-weight: 600; }
      .markdown-body .markdown-alert-note { border-left-color: var(--borderColor-accent-emphasis); }
      .markdown-body .markdown-alert-important { border-left-color: var(--borderColor-done-emphasis); }
      .markdown-body .markdown-alert-important .markdown-alert-title { color: var(--fgColor-done); }
      .markdown-body .mermaid { margin: 16px 0; padding: 20px; overflow-x: auto; border: 1px solid var(--borderColor-default); border-radius: 6px; text-align: center; background: var(--bgColor-muted); }
      .source-view { display: none; margin: 0; padding: 24px; overflow: auto; border: 0; border-radius: 0; color: var(--fgColor-default); background: var(--bgColor-default); font: 13px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre; }
      .file-shell[data-view="source"] .readme-frame { display: none; }
      .file-shell[data-view="source"] .source-view { display: block; }
      .preview-footer { padding: 24px; color: var(--fgColor-muted); font-size: 12px; text-align: center; }
      @media (max-width: 760px) {
        .gh-global { padding: 10px 16px; }
        .gh-search, .gh-global nav { display: none; }
        .repo-identity { padding-inline: 16px; font-size: 17px; }
        .page { padding: 16px 0; }
        .file-path { padding-inline: 16px; }
        .file-shell { border-right: 0; border-left: 0; border-radius: 0; }
        .file-toolbar small { display: none; }
        .readme-frame { padding: 24px 20px; }
        .markdown-body .anchor { display: none; }
      }
      @media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
    </style>
  </head>
  <body>
    <header class="gh-global">
      <a class="gh-mark" href="https://github.com/GML-MMGroup/ClipTalk" aria-label="GitHub repository">${githubMark}</a>
      <div class="gh-search">Type / to search</div>
      <nav aria-label="Global navigation"><a href="https://github.com/pulls">Pull requests</a><a href="https://github.com/issues">Issues</a></nav>
    </header>
    <section class="repo-header">
      <div class="repo-identity"><a href="https://github.com/GML-MMGroup">GML-MMGroup</a><span>/</span><a href="https://github.com/GML-MMGroup/ClipTalk">ClipTalk</a><span class="visibility">Public</span></div>
      <nav class="repo-nav" aria-label="Repository navigation"><a class="active" href="#">Code</a><a href="#">Issues</a><a href="#">Pull requests</a><a href="#">Actions</a><a href="#">Projects</a><a href="#">Security</a><a href="#">Insights</a></nav>
    </section>
    <main class="page">
      <div class="file-path"><a href="https://github.com/GML-MMGroup/ClipTalk">ClipTalk</a><span>/</span><strong>README_zh.md</strong></div>
      <section class="file-shell" id="fileShell" data-view="preview">
        <header class="file-toolbar"><strong>README_zh.md</strong><small>GitHub-style local preview</small><div class="view-tabs" role="tablist" aria-label="README view"><button id="previewTab" type="button" role="tab" aria-selected="true">Preview</button><button id="sourceTab" type="button" role="tab" aria-selected="false">Code</button></div></header>
        <div class="readme-frame"><article class="markdown-body entry-content container-lg">${article}</article></div>
        <pre class="source-view" id="sourceView"><code>${sourceEscaped}</code></pre>
      </section>
      <footer class="preview-footer">由 README_zh.md 生成 · ${escapeHtml(generatedAt)} UTC</footer>
    </main>
    <script>
      const shell = document.getElementById("fileShell");
      const previewTab = document.getElementById("previewTab");
      const sourceTab = document.getElementById("sourceTab");
      function setView(view) {
        shell.dataset.view = view;
        previewTab.setAttribute("aria-selected", String(view === "preview"));
        sourceTab.setAttribute("aria-selected", String(view === "source"));
      }
      previewTab.addEventListener("click", () => setView("preview"));
      sourceTab.addEventListener("click", () => setView("source"));
    </script>
    <script type="module">
      import mermaid from "./node_modules/mermaid/dist/mermaid.esm.min.mjs";
      const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      mermaid.initialize({ startOnLoad: true, securityLevel: "strict", theme: dark ? "dark" : "neutral" });
    </script>
  </body>
</html>`;

await writeFile(outputPath, html, "utf8");
await writeFile(indexPath, html, "utf8");
console.log(`Generated ${outputPath}`);
console.log(`Generated ${indexPath} as the preview server entry`);
