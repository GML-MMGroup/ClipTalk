import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { resolve } from 'node:path';
import test from 'node:test';
import { chromium } from 'playwright';

const root = resolve(import.meta.dirname, '../..');
async function fixture(run) {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 900, height: 700 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<html data-theme="light"><body class="ct-workbench-v4"><main id="fixture"></main></body></html>');
    await page.addStyleTag({ content: await readFile(resolve(root, 'static/generative-loaders.css'), 'utf8') });
    await page.addStyleTag({ content: await readFile(resolve(root, 'static/workbench.css'), 'utf8') });
    await page.addScriptTag({ path: resolve(root, 'static/generative-loaders.js') });
    await page.addScriptTag({ path: resolve(root, 'static/thinking-orbs.js') });
    await run(page);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
}

test('loaders pause for hidden ancestors, inactive state, viewport and background, and clean up removed roots', async () => fixture(async page => {
  await page.evaluate(() => {
    const main = document.querySelector('#fixture');
    // Separate mutation batches must not overwrite each other's pending mounts.
    main.innerHTML = '<section id="container"><span id="a" data-generative-loader="inline" data-loader-variant="aperture"></span></section>';
    queueMicrotask(() => main.insertAdjacentHTML('beforeend', '<span id="b" data-generative-loader="inline"></span>'));
  });
  await page.waitForFunction(() => document.querySelectorAll('.il-loader').length === 2);
  const paused = value => page.waitForFunction(value => document.querySelector('#a .il-loader')?.dataset.paused === String(value), value);
  await paused(false);
  await page.locator('#container').evaluate(el => { el.hidden = true; });
  await paused(true);
  await page.locator('#container').evaluate(el => { el.hidden = false; });
  await paused(false);
  await page.locator('#a').evaluate(el => { el.dataset.loaderActive = 'false'; });
  await paused(true);
  await page.locator('#a').evaluate(el => { el.dataset.loaderActive = 'true'; });
  await paused(false);
  await page.locator('#container').evaluate(el => { el.style.marginTop = '1600px'; });
  await paused(true);
  await page.locator('#container').evaluate(el => { el.style.marginTop = '0px'; });
  await paused(false);
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: true }); document.dispatchEvent(new Event('visibilitychange')); });
  await paused(true);
  await page.evaluate(() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); });
  await paused(false);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await paused(true);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await paused(false);
  await page.evaluate(() => { window.detached = document.querySelector('#a'); window.detached.remove(); });
  await page.waitForFunction(() => window.detached.childElementCount === 0);
  assert.equal(await page.locator('#b .il-loader').count(), 1);
}));

test('streaming Chinese and mixed text stays readable without remounting received characters', async () => fixture(async page => {
  await page.evaluate(() => {
    const host = document.querySelector('#fixture');
    host.style.width = '280px';
    host.innerHTML = '<span id="text" class="stream-text-loader" data-generative-loader="text" data-loader-variant="cascade"></span>';
    window.GenerativeLoadersBridge.update(document.querySelector('#text'), { text: '已经找到适合开场的片段。' });
  });
  await page.waitForFunction(() => document.querySelector('#text .tl-char'));
  await page.evaluate(() => { window.firstCharacter = document.querySelector('#text .tl-char'); });
  const text = '已经找到适合开场的片段。接下来保留说话人 A 的完整回答，并检查字幕换行。'.repeat(5) + '\n第二行 ClipTalk 16:9 MP4 👩🏽‍💻';
  await page.evaluate(text => window.GenerativeLoadersBridge.update(document.querySelector('#text'), { text }), text);
  await page.waitForFunction(text => document.querySelector('#text .tl-loader')?.textContent === text, text);
  assert.equal(await page.evaluate(() => window.firstCharacter === document.querySelector('#text .tl-char')), true);
  assert.equal(await page.locator('#fixture').evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.waitForFunction(() => document.querySelector('#text .tl-loader')?.dataset.paused === 'true');
  await page.evaluate(() => {
    const el = document.querySelector('#text');
    window.GenerativeLoadersBridge.clear(el, { preserveText: true });
    el.removeAttribute('data-generative-loader');
  });
  assert.equal(await page.locator('#text').textContent(), text);
  await page.waitForTimeout(80);
  assert.equal(await page.locator('#text .tl-loader').count(), 0);
}));

test('result transitions happen once for live results and never replay restored results', async () => fixture(async page => {
  await page.locator('#fixture').evaluate(el => { el.innerHTML = '<section class="chat-panel"><div id="chatMessages"></div></section>'; });
  await page.addScriptTag({ path: resolve(root, 'static/chat-stream.js') });
  const data = await page.evaluate(() => {
    const stream = window.ClipTalkChatStream;
    let starts = 0;
    const original = Element.prototype.animate;
    Element.prototype.animate = function (...args) { starts++; return original.apply(this, args); };
    stream.emit({ id: 'live', kind: 'result', final: true, html: '已生成' });
    const first = starts;
    stream.emit({ id: 'live', kind: 'result', final: true, html: '已生成 · 更新详情' });
    stream.restore(() => stream.emit({ id: 'history', kind: 'result', final: true, html: '旧结果' }));
    stream.emit({ id: 'history', kind: 'result', final: true, html: '旧结果 · 更新详情' });
    return { first, starts };
  });
  assert.deepEqual(data, { first: 1, starts: 1 });
}));

test('small uploads report transfer completion before the server creates the task', async () => {
  let release;
  let receivedHeaders;
  const server = createServer(async (req, res) => {
    if (req.url === '/') { res.setHeader('Content-Type', 'text/html'); return res.end('<body></body>'); }
    if (req.url !== '/upload') { res.statusCode = 404; return res.end(); }
    receivedHeaders = req.headers;
    for await (const chunk of req) { void chunk; }
    release = () => { if (res.writableEnded) return; res.setHeader('Content-Type', 'application/json'); res.end('{"job":{"id":"created"}}'); };
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.addScriptTag({ path: resolve(root, 'static/api-client.js') });
    await page.evaluate(() => {
      window.fractions = [];
      const form = new FormData();
      form.append('file', new Blob([new Uint8Array(1024 * 1024)]), 'clip.mp4');
      window.pending = window.ClipTalkApi.request('/upload', { method: 'POST', body: form, onUploadProgress: value => window.fractions.push(value) }).then(value => { window.result = value; });
    });
    await page.waitForFunction(() => window.fractions.includes(1));
    assert.equal(await page.evaluate(() => window.result), undefined);
    assert.match(receivedHeaders['content-type'], /^multipart\/form-data; boundary=/);
    assert.ok(receivedHeaders['x-cliptalk-session']);
    release();
    await page.evaluate(() => window.pending);
    assert.equal(await page.evaluate(() => window.result.job.id), 'created');
  } finally { release?.(); await browser.close(); await new Promise(resolve => server.close(resolve)); }
});

test('cover generation preserves portrait ratio and stops on failure; decoded covers reveal once', async () => fixture(async page => {
  await page.locator('#fixture').evaluate(el => {
    el.innerHTML = '<section class="chat-panel"><div id="chatMessages"></div><textarea id="chatInput"></textarea><button id="sendButton">发送</button><div id="agentPlanDock" class="hidden"></div></section>';
    window.job = { id: 'motion-job', agent: { workspaceId: 'motion-ws', planId: 'motion-plan' }, coverVersions: [] };
    window.fixturePlan = { id: 'motion-plan', workspaceId: 'motion-ws', status: 'running', brief: { coverRequested: true, coverAspect: '9:16' }, steps: [{ id: 'cover', tool: 'confirm_cover', status: 'waiting_operation' }] };
    window.ClipTalkCurrentJobId = () => window.job.id;
    window.ClipTalkCurrentJobSnapshot = () => window.job;
    window.ClipTalkApi = { requestJson: async () => ({ workspace: { id: 'motion-ws', jobId: 'motion-job', activePlanId: 'motion-plan' }, plans: [window.fixturePlan], plan: window.fixturePlan }) };
    window.EventSource = class { addEventListener() {} close() {} };
  });
  await page.addScriptTag({ path: resolve(root, 'static/chat-stream.js') });
  await page.addScriptTag({ path: resolve(root, 'static/agent-workspace.js') });
  await page.evaluate(() => window.ClipTalkAgentWorkspace.resumeForJob(window.job));
  await page.waitForFunction(() => document.querySelector('.agent-cover-generating .iml-loader'));
  assert.equal(await page.locator('.agent-cover-generating').evaluate(el => getComputedStyle(el).aspectRatio), '9 / 16');
  await page.waitForFunction(() => document.querySelector('.agent-execution-loader .il-loader')?.dataset.paused === 'true');
  await page.evaluate(async () => {
    window.fixturePlan.status = 'failed';
    window.fixturePlan.steps[0].status = 'failed';
    window.job.revision = 2;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.job);
  });
  assert.equal(await page.locator('.agent-cover-generating').count(), 0);
  await page.route('https://motion.test/cover.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="90" height="160"><rect width="90" height="160" fill="green"/></svg>' }));
  await page.evaluate(async () => {
    window.fixturePlan.status = 'completed';
    window.fixturePlan.steps[0].status = 'completed';
    window.job.currentCoverVersionId = 'cover-1';
    window.job.coverVersions = [{ id: 'cover-1', previewUrl: 'https://motion.test/cover.svg', aspectRatio: '9:16' }];
    window.job.revision = 3;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.job);
  });
  await page.waitForFunction(() => document.querySelector('[data-cover-image-state]')?.dataset.coverImageState === 'ready');
  assert.equal(await page.locator('[data-cover-image-state]').evaluate(el => getComputedStyle(el).aspectRatio), '9 / 16');
  await page.route('https://motion.test/broken.jpg', route => route.fulfill({ contentType: 'image/jpeg', body: 'invalid image' }));
  await page.evaluate(async () => {
    window.job.coverVersions[0].previewUrl = 'https://motion.test/broken.jpg';
    window.job.revision = 4;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.job);
  });
  await page.waitForFunction(() => document.querySelector('[data-cover-image-state]')?.dataset.coverImageState === 'error');
  assert.equal(await page.locator('[data-cover-image-state]').getAttribute('aria-label'), '封面图片加载失败');
}));

test('Thinking Orbs keep their canvas, follow the theme and stop drawing when inactive', async () => fixture(async page => {
  await page.evaluate(() => {
    window.drawCalls = 0;
    const clear = CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.clearRect = function (...args) { window.drawCalls++; return clear.apply(this, args); };
    document.querySelector('#fixture').innerHTML = '<span id="orb" data-thinking-orb data-orb-size="20" data-orb-state="working"></span>';
  });
  await page.waitForFunction(() => window.drawCalls > 3);
  await page.locator('#orb').evaluate(el => { window.orbCanvas = el.querySelector('canvas'); el.dataset.orbActive = 'false'; });
  await page.waitForTimeout(100);
  const calls = await page.evaluate(() => window.drawCalls);
  await page.waitForTimeout(100);
  assert.equal(await page.evaluate(() => window.drawCalls), calls);
  const light = await page.locator('#orb canvas').evaluate(el => el.toDataURL());
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; window.dispatchEvent(new Event('cliptalk:themechange')); });
  await page.waitForTimeout(100);
  assert.notEqual(await page.locator('#orb canvas').evaluate(el => el.toDataURL()), light);
  assert.equal(await page.locator('#orb canvas').evaluate(el => el === window.orbCanvas), true);
  await page.locator('#orb').evaluate(el => { window.detachedOrb = el; el.remove(); });
  await page.waitForFunction(() => window.detachedOrb.childElementCount === 0);
}));
