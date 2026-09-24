import assert from "node:assert/strict";
import test from "node:test";
import postcss from "postcss";
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { audit, pruneCascade } from "../../tools/audit_css_cascade.mjs";

function clean(sources, supports) {
  const files = sources.map((source, i) => ({ name: `${i}.css`, root: postcss.parse(source) }));
  const removed = pruneCascade(files, supports);
  return { removed, files, css: files.map(file => file.root.toString()).join("\n") };
}

test("production stylesheets contain no shadowed duplicate declarations", async () => {
  const result = await audit({ root: fileURLToPath(new URL("../../", import.meta.url)) });
  assert.equal(result.removedDeclarations, 0,
    JSON.stringify(result.byFile.filter(file => file.removedDeclarations > 0)));
});

test("cascade pruning removes only declarations shadowed for every selector", () => {
  const result = clean([".a,.b { color:red; padding:4px } .a {color:blue}", ".a,.b {padding:8px}"]);
  assert.equal(result.removed.length, 1);
  assert.equal(result.removed[0].property, "padding");
  assert.match(result.css, /color:red/);
});
test("later normal declarations cannot replace important values", () => {
  assert.equal(clean([".a{color:red!important}.a{color:blue}"]).removed.length, 0);
  assert.equal(clean([".a{color:red}.a{color:blue!important}"]).removed.length, 1);
  assert.equal(clean([".a{color:red!important}.a{color:blue!important}"]).removed.length, 1);
});
test("conditional rules retain their own contexts", () => {
  const value = clean([".a{color:red}@media(max-width:600px){.a{color:blue}}@media(min-width:800px){.a{color:green}}"]);
  assert.equal(value.removed.length, 0);
  assert.equal(clean(["@media(max-width:600px){.a{color:red}.a{color:blue}}"]).removed.length, 1);
});
test("animation, layer, scope and nested-selector semantics remain untouched", () => {
  for (const source of ["@keyframes a{0%{opacity:0}0%{opacity:1}}", "@layer a{.x{color:red}.x{color:blue}}", "@scope (.a){.x{color:red}.x{color:blue}}", ".a{& .x{color:red}& .x{color:blue}}"])
    assert.equal(clean([source]).removed.length, 0);
});
test("unsupported values and vendor fallbacks do not prove redundancy", () => {
  assert.equal(clean([".a{display:block}.a{display:future-layout}"], (_prop, value) => value !== "future-layout").removed.length, 0);
  assert.equal(clean([".a{display:-webkit-box;display:flex}"]).removed.length, 0);
});
test("commas inside functional selectors are not treated as selector separators", () => {
  const result = clean([":is(.a,.b){color:red}:is(.a,.b){color:blue}"]);
  assert.equal(result.removed.length, 1);
  assert.match(result.css, /:is\(\.a,.b\)/);
});
test("cleanup is idempotent and does not guess shorthand coverage", () => {
  const result = clean([".a{margin:8px;color:red}.a{margin-left:2px;color:blue}"]);
  assert.match(result.css, /margin:8px/);
  assert.equal(pruneCascade(result.files).length, 0);
});
test("the browser computes the same styles before and after safe pruning", async () => {
  const source = ".a,.b{color:red;padding:8px;border:1px solid blue}.a{color:blue}.a,.b{padding:4px!important}.a{padding:10px}@media(min-width:600px){.b{margin:2px}.b{margin:4px}}";
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const snapshot = async css => {
      await page.setContent(`<style>${css}</style><div class="a">A</div><div class="b">B</div>`);
      return page.evaluate(() => [...document.querySelectorAll("div")].map(node => {
        const style = getComputedStyle(node);
        return [style.color, style.padding, style.margin, style.border];
      }));
    };
    assert.deepEqual(await snapshot(clean([source]).css), await snapshot(source));
  } finally { await browser.close(); }
});
