import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { resolve, extname } from 'node:path';
import { chromium } from 'playwright';

const root = resolve(import.meta.dirname, '../..');

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

const coverJob = (id, editSessions) => ({
  id, filename: '素材.mp4', status: 'completed', taskMode: 'highlight', messages: [], candidates: [],
  eventGroups: [], outputs: [], outputVersions: [], videoInfo: { duration: 30, width: 1024, height: 576 },
  presentation: { key: 'exported', label: '正式成片已生成', journeyStage: 4 },
  coverVersions: [{ id: 'cv1', variantId: 'v1' }], currentCoverVersionId: 'cv1',
  coverDraft: {
    jobId: id, approvedVariantId: 'v1',
    variants: [{ variantId: 'v1', previewUrl: '/cover.png', contentHash: 'hash1', direction: 'source_clean' }],
  },
  coverTimelineDraft: { activeVariantId: 'v1', variants: { v1: { duration: 2 } } },
  editSessions,
});

const baseSession = { id: 's1', revision: 3, status: 'draft', clips: [{ id: 'c1', sourceStart: 0, sourceEnd: 5, duration: 5 }] };

const sessionWithCover = {
  id: 's1', revision: 4, status: 'draft',
  clips: [
    { id: 'cc1', assetKind: 'image', title: '封面', duration: 2, sourceStart: 0, sourceEnd: 2 },
    { id: 'c1', sourceStart: 0, sourceEnd: 5, duration: 5 },
  ],
};

async function openCoverTrack(page, jobId) {
  await page.waitForFunction((id) => window.ClipTalkCurrentJobId?.() === id, jobId);
  await page.evaluate((id) => {
    coverReviewOpenJobId = id;
    reviewLowerPanelMode = 'timeline';
    renderTimelineCoverTrack(currentJob);
  }, jobId);
  await page.locator('#timelineCoverTrack').waitFor({ state: 'visible' });
}

test('cover editor inserts the saved cover as a timeline clip', async () => {
  const job = coverJob('cover_insert', [baseSession]);
  const server = await serve(job), browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(8000);
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', route => {
      const request = route.request();
      if (request.method() === 'PATCH' && request.url().includes('/edit-sessions/')) {
        return route.fulfill({ json: { session: sessionWithCover } });
      }
      return route.continue();
    });
    await page.goto(`${server.url}/#job=${job.id}`);
    await page.waitForFunction(() => document.querySelectorAll('link[rel="stylesheet"][media="print"]').length === 0);
    await openCoverTrack(page, job.id);

    const button = page.locator('#timelineCoverEditor [data-cover-timeline-insert]');
    await button.waitFor({ state: 'visible' });
    assert.equal((await button.innerText()).trim(), '插入到时间轴');
    assert.equal(await button.isDisabled(), false);

    const [response] = await Promise.all([
      page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes('/edit-sessions/s1')),
      button.click(),
    ]);
    const body = JSON.parse(response.request().postData());
    assert.equal(body.revision, 3);
    assert.equal(body.operation.type, 'insert_cover_clip');
    assert.equal(body.operation.duration, 2);
    assert.equal(body.operation.positionMode, 'start');

    // The panel repaints from the returned session and reports the inserted clip.
    await page.waitForFunction(
      () => document.querySelector('#timelineCoverEditor [data-cover-timeline-insert]')?.dataset.coverInserted === 'true',
    );
    assert.match(await page.locator('#timelineCoverEditor [data-cover-timeline-insert]').innerText(), /再插入一段封面/);
    assert.match(await page.locator('#timelineCoverDraftState').innerText(), /已在时间轴/);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); await server.close(); }
});

test('cover insert creates a timeline on demand when the task has a finished version', async () => {
  const job = coverJob('cover_autocreate', []);
  job.outputVersions = [{ id: 'version-1', number: 1, outputs: [{ filename: 'version-1.mp4', duration: 12 }] }];
  const server = await serve(job), browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(8000);
    const errors = [], posts = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', route => {
      const request = route.request();
      if (request.method() === 'POST' && request.url().includes('/edit-sessions')) {
        posts.push(JSON.parse(request.postData()));
        return route.fulfill({ json: { created: true, session: baseSession, job } });
      }
      if (request.method() === 'PATCH' && request.url().includes('/edit-sessions/')) {
        return route.fulfill({ json: { session: sessionWithCover } });
      }
      return route.continue();
    });
    await page.goto(`${server.url}/#job=${job.id}`);
    await page.waitForFunction(() => document.querySelectorAll('link[rel="stylesheet"][media="print"]').length === 0);
    await openCoverTrack(page, job.id);

    const button = page.locator('#timelineCoverEditor [data-cover-timeline-insert]');
    await button.waitFor({ state: 'visible' });
    assert.equal(await button.isDisabled(), false, 'button must not be disabled when a version exists');
    await button.click();
    await page.waitForFunction(
      () => document.querySelector('#timelineCoverEditor [data-cover-timeline-insert]')?.dataset.coverInserted === 'true',
    );
    // A timeline is created from the newest finished version before the insert.
    assert.deepEqual(posts, [{ baseVersionId: 'version-1', outputFilename: 'version-1.mp4' }]);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); await server.close(); }
});

test('cover insert follows the chosen timeline position', async () => {
  const job = coverJob('cover_position', [baseSession]);
  const server = await serve(job), browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(8000);
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', route => {
      if (route.request().method() === 'PATCH' && route.request().url().includes('/edit-sessions/')) {
        return route.fulfill({ json: { session: sessionWithCover } });
      }
      return route.continue();
    });
    await page.goto(`${server.url}/#job=${job.id}`);
    await page.waitForFunction(() => document.querySelectorAll('link[rel="stylesheet"][media="print"]').length === 0);
    await openCoverTrack(page, job.id);

    const select = page.locator('#timelineCoverEditor [data-cover-timeline-position]');
    await select.waitFor({ state: 'visible' });
    assert.deepEqual(await select.locator('option').allInnerTexts(), ['片头（最前）', '正片中间', '片尾（最后）']);
    assert.equal(await select.inputValue(), 'start');

    await select.selectOption('middle');
    const [response] = await Promise.all([
      page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes('/edit-sessions/s1')),
      page.locator('#timelineCoverEditor [data-cover-timeline-insert]').click(),
    ]);
    assert.equal(JSON.parse(response.request().postData()).operation.positionMode, 'middle');
    assert.deepEqual(errors, []);
  } finally { await browser.close(); await server.close(); }
});

test('cover insert carries the chosen intro animation', async () => {
  const job = coverJob('cover_anim', [baseSession]);
  const server = await serve(job), browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(8000);
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', route => {
      if (route.request().method() === 'PATCH' && route.request().url().includes('/edit-sessions/')) {
        return route.fulfill({ json: { session: sessionWithCover } });
      }
      return route.continue();
    });
    await page.goto(`${server.url}/#job=${job.id}`);
    await page.waitForFunction(() => document.querySelectorAll('link[rel="stylesheet"][media="print"]').length === 0);
    await openCoverTrack(page, job.id);

    const select = page.locator('#timelineCoverEditor [data-cover-timeline-animation]');
    await select.waitFor({ state: 'visible' });
    assert.deepEqual(await select.locator('option').allInnerTexts(), ['淡入（推荐）', '缓慢推近', '直接出现']);
    assert.equal(await select.inputValue(), 'fade');

    await select.selectOption('zoom');
    const [response] = await Promise.all([
      page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes('/edit-sessions/s1')),
      page.locator('#timelineCoverEditor [data-cover-timeline-insert]').click(),
    ]);
    const body = JSON.parse(response.request().postData());
    assert.equal(body.operation.type, 'insert_cover_clip');
    assert.equal(body.operation.animation, 'zoom');
    assert.deepEqual(errors, []);
  } finally { await browser.close(); await server.close(); }
});

test('changing the animation updates the cover clip already on the timeline', async () => {
  const job = coverJob('cover_anim_update', [sessionWithCover]);
  const server = await serve(job), browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(8000);
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', route => {
      if (route.request().method() === 'PATCH' && route.request().url().includes('/edit-sessions/')) {
        return route.fulfill({ json: { session: sessionWithCover } });
      }
      return route.continue();
    });
    await page.goto(`${server.url}/#job=${job.id}`);
    await page.waitForFunction(() => document.querySelectorAll('link[rel="stylesheet"][media="print"]').length === 0);
    await openCoverTrack(page, job.id);

    const select = page.locator('#timelineCoverEditor [data-cover-timeline-animation]');
    await select.waitFor({ state: 'visible' });
    const [response] = await Promise.all([
      page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes('/edit-sessions/s1')),
      select.selectOption('zoom'),
    ]);
    const body = JSON.parse(response.request().postData());
    assert.equal(body.operation.type, 'update_clip');
    assert.equal(body.operation.clipId, 'cc1');
    assert.equal(body.operation.coverAnimation, 'zoom');
    assert.deepEqual(errors, []);
  } finally { await browser.close(); await server.close(); }
});

test('cover insert stays disabled without a session and without a version', async () => {
  const job = coverJob('cover_nosession', []);
  const server = await serve(job), browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(8000);
    const errors = [], writes = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/**', route => {
      if (!['GET', 'HEAD'].includes(route.request().method())) { writes.push(route.request().url()); return route.abort(); }
      return route.continue();
    });
    await page.goto(`${server.url}/#job=${job.id}`);
    await page.waitForFunction(() => document.querySelectorAll('link[rel="stylesheet"][media="print"]').length === 0);
    await openCoverTrack(page, job.id);

    const disabled = page.locator('#timelineCoverEditor button[disabled]');
    await disabled.waitFor({ state: 'visible' });
    assert.equal((await disabled.innerText()).trim(), '插入到时间轴');
    assert.equal(await page.locator('#timelineCoverEditor [data-cover-timeline-insert]').count(), 0);
    await disabled.click({ force: true }).catch(() => {});
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); await server.close(); }
});
