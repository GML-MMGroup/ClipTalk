import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { resolve, extname } from 'node:path';
import { chromium } from 'playwright';

const root = resolve(import.meta.dirname, '../..');
const copySource = await readFile(resolve(root, 'static/ui-copy.js'), 'utf8');
const controller = await readFile(resolve(root, 'static/workspace-controller.js'), 'utf8');
const context = vm.createContext({ window: {} });
vm.runInContext(copySource, context);
const copy = context.window.ClipTalkCopy;

test('task identity favors a specific objective and respects a custom name', () => {
  const job = { id: 'task_123456', filename: '小米产品.mp4', brief: { objective: '内容检索' }, request: { contentInstruction: '保留汽车展示，剪成竖屏' } };
  assert.equal(copy.taskTitle(job), '保留汽车展示，剪成竖屏');
  assert.equal(copy.taskTitle(job, '发布用终稿'), '发布用终稿');
  assert.equal(copy.taskTitle({ id: 'task_123456', filename: 'a'.repeat(32) + '.mp4' }), '未命名任务 · 123456');
});

test('output quality never infers a pass from generation or another plan', () => {
  assert.equal(copy.outputQuality({}, {}).label, '未检查');
  assert.equal(copy.outputQuality({ qualityStatus: 'passed' }, { qualityStatus: 'needs_review' }).label, '有提醒待检查');
  assert.equal(copy.outputQuality({}, { qualityStatus: 'failed' }).label, '检查未通过');
});

test('subsecond source ranges retain precision and reject invalid ranges', () => {
  const start = controller.indexOf('  function segmentRangeLabel(');
  const end = controller.indexOf('\n  function segmentDisplayTitle', start);
  const ctx = vm.createContext({});
  vm.runInContext(controller.slice(start, end), ctx);
  assert.equal(ctx.segmentRangeLabel({ start: 0, end: .61 }), '0:00.00–0:00.61 · 0.61 秒');
  assert.equal(ctx.segmentRangeLabel({ start: 59.999, end: 61.2 }), '1:00.00–1:01.20 · 1.20 秒');
  for (const segment of [{}, { start: 0 }, { start: 1, end: 0 }, { start: -1, end: 2 }, { start: null, end: 2 }, { start: 'x', end: 1 }]) assert.equal(ctx.segmentRangeLabel(segment), '');
});

async function serve(job) {
  const server = createServer(async (req, res) => {
    const path = new URL(req.url, 'http://localhost').pathname;
    if (path.startsWith('/api/')) {
      const payload = path === '/api/health' ? { ok: true, ffmpeg: true, ffprobe: true, visionConfigured: true, uiContractVersion: 2 }
        : path === '/api/setup/status' ? { complete: true, canCreateTask: true, canUseAgent: true, steps: [] }
        : path === '/api/jobs' ? { jobs: [job] }
        : path === `/api/jobs/${job.id}` || path === `/api/jobs/${job.id}/status` ? { job }
        : { workspaces: [], providers: [], skills: [], outputs: [] };
      res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(payload)); return;
    }
    const file = resolve(root, 'static', path === '/' ? 'index.html' : path.replace(/^\/static\//, ''));
    if (!file.startsWith(resolve(root, 'static') + '/')) { res.writeHead(404); res.end(); return; }
    try { res.setHeader('Content-Type', ({ '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png' })[extname(file)] || 'application/octet-stream'); res.end(await readFile(file)); }
    catch { res.writeHead(404); res.end(); }
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  return { url: `http://127.0.0.1:${server.address().port}`, close: () => new Promise(r => server.close(r)) };
}

test('delivery, menu and compact review remain usable across versions and themes', async () => {
  const output = (name, segments, qualityStatus) => ({ filename: name, title: name, duration: 10, width: 1024, height: 576,
    videoUrl: '/test-missing.mp4', previewUrl: '/test-missing.mp4', downloadUrl: `/files/${name}`, segments, qualityStatus });
  const job = { id: 'ux_task', filename: '素材.mp4', status: 'completed', taskMode: 'content_extract', messages: [], candidates: [], eventGroups: [],
    videoInfo: { duration: 30, width: 1024, height: 576 }, presentation: { key: 'exported', label: '正式成片已生成', journeyStage: 4 },
    outputVersions: [
      { id: 'v1', number: 1, outputs: [output('v1.mp4', [{ start: 0, end: .61, title: '匹配用户内容检索要求' }, { start: 4, end: 3 }], 'needs_review')] },
      { id: 'v2', number: 2, outputs: [output('v2.mp4', [{ start: 2, end: 5, title: '汽车展示' }], 'passed')] },
    ], outputs: [],
  };
  const server = await serve(job), browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
    page.setDefaultTimeout(7000);
    const errors = [], writes = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', route => { if (!['GET', 'HEAD'].includes(route.request().method())) { writes.push(route.request().url()); return route.abort(); } return route.continue(); });
    await page.goto(`${server.url}/#job=${job.id}`);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === 'ux_task');
    await page.evaluate(() => selectOutput('v1.mp4', false));
    await page.waitForFunction(() => document.querySelector('#downloadButton')?.parentElement.classList.contains('asset-actions'));
    assert.ok(await page.locator('#downloadButton').isVisible());
    assert.equal(await page.locator('#downloadButton').getAttribute('href'), '/files/v1.mp4');
    await page.locator('#reviewMoreActions summary').click();
    assert.ok((await page.locator('[data-ct-v4-replace] svg').boundingBox()).width <= 20);
    await page.keyboard.press('Escape');
    assert.ok(await page.locator('#reviewMoreActions summary').evaluate(n => n === document.activeElement));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.querySelector('#timelinePanel')?.dataset.compactFolded === 'true');
    assert.equal(await page.locator('#timelineViewport').isVisible(), false);
    assert.equal(await page.locator('.timeline-toolbar').isVisible(), false);
    await page.locator('#ctCompactTimelineToggle').click();
    assert.ok(await page.locator('#timelineViewport').isVisible());
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.waitForTimeout(100);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.querySelector('#timelinePanel')?.dataset.compactFolded === 'false');
    await page.locator('button[data-ct-compact-view="review"]').click();
    assert.match(await page.locator('#ctV4CandidatePreview').innerText(), /0:00.00–0:00.61/);
    assert.ok(await page.locator('[data-ct-v4-adopted-segment="1"]').isDisabled());
    assert.match(await page.locator('.ct-v4-quality-details').innerText(), /有提醒待检查/);
    assert.ok(await page.locator('[data-ct-version-deliver]').isVisible());
    await page.evaluate(() => selectOutput('v2.mp4', false));
    await page.locator('button[data-ct-compact-view="review"]').click();
    await page.waitForFunction(() => document.querySelector('.ct-v4-quality-details summary')?.textContent.includes('检查通过'));
    assert.equal(await page.locator('#downloadButton').getAttribute('href'), '/files/v2.mp4');
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => window.ClipTalkTheme.apply(t), theme);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    assert.deepEqual(errors, []); assert.deepEqual(writes, []);
  } finally { await browser.close(); await server.close(); }
});

test('missing base output offers a draft-only recovery without search or submission', async () => {
  const reason = { code: 'missing_base_output', label: '需要先生成基础成片', message: '动态片头需要当前任务已有成片。',
    hint: '先描述基础成片要保留的内容并提交剪辑，再继续当前操作。不会自动提交。', actionKey: 'revise_instruction', actionLabel: '补充基础成片要求' };
  const plan = { id: 'p', workspaceId: 'ws', goal: '添加动态片头', status: 'no_result', terminalReason: reason,
    steps: [{ id: 'inspect', title: '检查当前成片', tool: 'inspect_workspace', status: 'completed', outcome: 'no_result',
      result: { terminalStatus: 'no_result', artifact: { kind: 'precondition_missing', message: reason.message } } }] };
  const job = { id: 'recovery', filename: '素材.mp4', status: 'completed', stage: 'agent_no_result', taskMode: 'content_extract', instructionSubmitted: true,
    messages: [], agent: { workspaceId: 'ws', planId: 'p', status: 'no_result' },
    presentation: { key: 'no_result', group: 'no_result', label: reason.label, terminalReason: reason, journeyStage: 2 } };
  const server = await serve(job), browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 768 } }), writes = [], errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', route => {
      if (!['GET', 'HEAD'].includes(route.request().method())) { writes.push(route.request().url()); return route.abort(); }
      if (route.request().url().includes('/api/agent/')) return route.fulfill({ json: { workspace: { id: 'ws', jobId: job.id, activePlanId: 'p' }, plans: [plan], plan } });
      return route.continue();
    });
    await page.goto(`${server.url}/#job=${job.id}`);
    const recovery = page.getByRole('button', { name: reason.actionLabel, exact: true }).first();
    await recovery.waitFor({ timeout: 7000 });
    await page.locator('#chatInput').fill('我已经写好的基础剪辑要求');
    await recovery.click();
    assert.equal(await page.locator('#chatInput').inputValue(), '我已经写好的基础剪辑要求');
    assert.equal(await page.locator('#chatInput').evaluate(n => n === document.activeElement), true);
    assert.equal(await page.getByRole('button', { name: '重新检索内容', exact: true }).count(), 0);
    assert.deepEqual(writes, []); assert.deepEqual(errors, []);
  } finally { await browser.close(); await server.close(); }
});
