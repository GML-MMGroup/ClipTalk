/** Audit declarations that cannot win in the production stylesheet order.
 * Only identical selectors, properties and conditional contexts are compared.
 * Specificity guesses, selector-coverage guesses and unused-selector purges are
 * deliberately excluded: workflow states are generated at runtime.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import postcss from "postcss";
import { chromium } from "playwright";

export function pruneCascade(files, supports = () => true) {
  const seen = new Map();
  const removed = [];
  for (const file of [...files].reverse()) {
    const rules = [];
    file.root.walkRules(rule => rules.push(rule));
    for (const rule of rules.reverse()) {
      let parent = rule.parent;
      const scope = [];
      let excluded = false;
      while (parent && parent.type !== "root") {
        // Layer ordering, scoped specificity and nested selectors need a
        // different proof. Keep them intact, along with animation keyframes.
        if (parent.type !== "atrule" || !["media", "supports", "container"].includes(parent.name)) {
          excluded = true;
          break;
        }
        scope.unshift([parent.name, parent.params]);
        parent = parent.parent;
      }
      if (excluded) continue;
      const selectors = postcss.list.comma(rule.selector).map(value => value.trim());
      for (const declaration of [...rule.nodes].reverse()) {
        if (declaration.type !== "decl") continue;
        const { prop, value, important } = declaration;
        if (/revert|-(?:webkit|moz|ms|o)-/i.test(value) || /^-(?!-)/.test(prop) || !supports(prop, value)) continue;
        const keys = selectors.map(selector => JSON.stringify([scope, selector, prop]));
        if (keys.every(key => seen.has(key) && (!important || seen.get(key).important))) {
          removed.push({
            file: file.name, line: declaration.source?.start.line,
            selector: rule.selector, property: prop, value,
            replacedBy: [...new Set(keys.map(key => seen.get(key).file))],
          });
          declaration.remove();
        } else {
          for (const key of keys) {
            if (!seen.has(key) || important && !seen.get(key).important) seen.set(key, { important, file: file.name });
          }
        }
      }
    }
    file.root.walkRules(rule => { if (!rule.nodes.length) rule.remove(); });
    // Remove only empty conditional wrappers, never declarations such as
    // @layer order statements or @font-face/@property descriptors.
    file.root.walkAtRules(rule => {
      if (["media", "supports", "container"].includes(rule.name) && rule.nodes && !rule.nodes.length) rule.remove();
    });
  }
  return removed;
}

export async function audit({ root, write = false, report = null }) {
  const html = fs.readFileSync(path.join(root, "static/index.html"), "utf8");
  const names = [...html.matchAll(/href="\/static\/([^"?]+\.css)/g)].map(match => match[1]);
  const files = names.map(name => {
    const source = fs.readFileSync(path.join(root, "static", name), "utf8");
    return { name, source, root: postcss.parse(source, { from: name }) };
  });
  const values = new Map();
  for (const file of files) file.root.walkDecls(declaration => values.set(JSON.stringify([declaration.prop, declaration.value]), [declaration.prop, declaration.value]));
  const browser = await chromium.launch({ headless: true });
  let accepted;
  try {
    const page = await browser.newPage();
    accepted = new Set(await page.evaluate(pairs => pairs.filter(([prop, value]) => CSS.supports(prop, value)).map(pair => JSON.stringify(pair)), [...values.values()]));
  } finally { await browser.close(); }
  const removed = pruneCascade(files, (prop, value) => accepted.has(JSON.stringify([prop, value])));
  const byFile = files.map(file => ({
    file: file.name,
    removedDeclarations: removed.filter(item => item.file === file.name).length,
    bytesBefore: Buffer.byteLength(file.source),
    bytesAfter: Buffer.byteLength(file.root.toString()),
  }));
  if (write) for (const file of files) {
    const source = file.root.toString();
    if (source !== file.source) fs.writeFileSync(path.join(root, "static", file.name), source);
  }
  if (report) fs.writeFileSync(report, JSON.stringify({ byFile, removed }, null, 2) + "\n");
  return { removedDeclarations: removed.length, savedBytes: byFile.reduce((sum, file) => sum + file.bytesBefore - file.bytesAfter, 0), byFile };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const reportIndex = process.argv.indexOf("--report");
  const result = await audit({ root, write: process.argv.includes("--write"), report: reportIndex >= 0 ? process.argv[reportIndex + 1] : null });
  console.log(JSON.stringify(result, null, 2));
  if (process.argv.includes("--check") && result.removedDeclarations) process.exitCode = 1;
}
