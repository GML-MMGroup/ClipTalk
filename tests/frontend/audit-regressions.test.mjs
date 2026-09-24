import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, resolve } from 'node:path';
import test from 'node:test';
import { chromium } from 'playwright';

const root = resolve(import.meta.dirname, '../..');
const agentSource = await readFile(resolve(root, 'static/agent-workspace.js'), 'utf8');
const apiSource = await readFile(resolve(root, 'static/api-client.js'), 'utf8');
const plan = { id: 'plan_A', workspaceId: 'ws_A', status: 'awaiting_confirmation', summary: 'A任务目标', steps: [{ id: 'step_A', tool: 'inspect_workspace', title: '检查A视频', status: 'pending' }] };

async function isolatedPage(run) {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.setContent('<section class="chat-panel"><div id="chatMessages"></div><textarea id="chatInput"></textarea><button id="sendButton">发送</button><div id="agentPlanDock" class="hidden"></div></section>');
    await page.evaluate(() => {
      window.job = 'job_A';
      window.ClipTalkCurrentJobId = () => window.job;
      window.showToast = () => {};
      window.EventSource = class { addEventListener() {} close() {} };
    });
    await run(page);
  } finally { await browser.close(); }
}

for (const outcome of ['success', 'error']) {
  test(`late ${outcome} from A leaves B's plan and composer intact`, async () => isolatedPage(async page => {
    await page.evaluate(({ plan, outcome }) => {
      window.ClipTalkApi = {
        requestJson: async () => ({ workspace: { id: 'ws_A', jobId: 'job_A' } }),
        requestResponse: () => new Promise(resolve => {
          window.release = () => resolve(new Response(`event: ${outcome === 'success' ? 'plan' : 'error'}\ndata: ${JSON.stringify(outcome === 'success' ? { plan } : { message: 'A任务失败' })}\n\n`));
        }),
      };
    }, { plan, outcome });
    await page.addScriptTag({ content: agentSource });
    await page.evaluate(() => { window.pending = window.ClipTalkAgentWorkspace.submitGoal('A任务目标'); });
    await page.waitForFunction(() => !!window.release);
    await page.evaluate(() => {
      window.job = 'job_B';
      window.ClipTalkAgentWorkspace.reset();
      document.querySelector('#chatMessages').textContent = 'B任务对话';
      document.querySelector('#chatInput').value = 'B未发送的草稿';
      window.release();
    });
    await page.evaluate(() => window.pending);
    assert.equal(await page.locator('#chatInput').inputValue(), 'B未发送的草稿');
    assert.equal(await page.locator('#chatMessages').textContent(), 'B任务对话');
    assert.equal(await page.locator('#agentPlanDock').textContent(), '');
    assert.equal(await page.locator('#chatInput').isDisabled(), false);
  }));
}

test('an interrupted poll reconnects and consumes the final snapshot', async () => isolatedPage(async page => {
  await page.evaluate(plan => {
    window.polls = 0;
    window.ClipTalkApi = { requestJson: async path => {
      if (path.includes('/plans/')) {
        if (++window.polls === 1) throw new Error('network unavailable');
        return { plan: { ...plan, status: 'preview_ready', steps: plan.steps.map(s => ({ ...s, status: 'completed' })) } };
      }
      return { workspace: { id: 'ws_A', jobId: 'job_A', activePlanId: plan.id }, plans: [{ ...plan, status: 'running' }] };
    } };
  }, plan);
  await page.addScriptTag({ content: agentSource });
  await page.evaluate(() => window.ClipTalkAgentWorkspace.resumeForJob({ id: 'job_A', status: 'awaiting_agent_plan', agent: { workspaceId: 'ws_A' } }));
  await page.waitForFunction(() => document.querySelector('#agentConnectionState')?.textContent.includes('正在重连'));
  await page.waitForFunction(() => document.querySelector('#agentPlanDock').dataset.status === 'preview_ready');
  assert.equal(await page.evaluate(() => window.polls), 2);
  assert.equal(await page.locator('#agentConnectionState').count(), 0);
}));

test('terminal plan cards expose the current result and make cancellation recoverable', async () => isolatedPage(async page => {
  await page.evaluate(plan => {
    window.snapshot = { id: 'job_A', status: 'completed', agent: { workspaceId: 'ws_A', planId: plan.id }, presentation: { key: 'exported' } };
    window.fixturePlan = { ...plan, status: 'completed', goal: '保留核心回答', steps: plan.steps.map(s => ({ ...s, status: 'completed' })) };
    window.ClipTalkCurrentJobSnapshot = () => window.snapshot;
    window.ClipTalkOrderedJobOutputs = () => [{ item: { filename: 'final.mp4', duration: 12, displayTitle: '访谈精华', capabilities: { canEdit: true } }, version: { number: 2 } }];
    window.actions = [];
    window.ClipTalkVersionAction = (filename, action) => window.actions.push({ filename, action });
    window.setChatInputDraft = text => { document.querySelector('#chatInput').value = text; };
    window.ClipTalkApi = { requestJson: async () => ({ workspace: { id: 'ws_A', jobId: 'job_A', activePlanId: plan.id }, plans: [window.fixturePlan] }) };
  }, plan);
  await page.addScriptTag({ content: agentSource });
  await page.evaluate(() => window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot));
  assert.match(await page.locator('#agentPlanDock').innerText(), /成片已生成/);
  assert.match(await page.locator('.assistant-result-summary').innerText(), /V2.*12\.0 秒.*访谈精华/);
  assert.equal(await page.locator('#agentPlanDock details').evaluate(n => n.open), false);
  await page.getByRole('button', { name: '播放成片', exact: true }).click();
  assert.deepEqual(await page.evaluate(() => window.actions), [{ filename: 'final.mp4', action: 'preview' }]);
  await page.evaluate(async () => {
    window.fixturePlan.status = 'cancelled';
    window.snapshot.presentation.key = 'cancelled';
    window.snapshot.revision = 2;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot);
  });
  await page.getByRole('button', { name: '修改要求重新规划', exact: true }).click();
  assert.equal(await page.locator('#chatInput').inputValue(), '保留核心回答');
  assert.equal(await page.locator('#chatInput').evaluate(n => n === document.activeElement), true);
  assert.equal(await page.locator('[data-result-action]').count(), 0);
  await page.evaluate(async () => {
    window.fixturePlan.status = 'awaiting_confirmation';
    window.snapshot.presentation.key = 'exported';
    window.snapshot.revision = 3;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot);
  });
  assert.equal(await page.getByRole('button', { name: '确认并开始', exact: true }).count(), 1, 'An older completed output must not hide a new plan awaiting confirmation');
}));

test('warning plan exposes bound full playback, with export delegated to the player', async () => isolatedPage(async page => {
  await page.evaluate(plan => {
    window.artifact = { kind: 'social_reframe_preview', filename: 'portrait.mp4', revision: 3, reframe: { aspect: '9:16' }, duration: 50, previewUrl: '/portrait.mp4' };
    window.fixturePlan = { ...plan, status: 'preview_ready', steps: [
      { id: 'preview', tool: 'render_social_preview', status: 'completed', result: { artifact: { kind: 'social_reframe_preview', output: window.artifact } } },
      { id: 'qc', tool: 'delivery_qc', status: 'completed', result: { artifact: { kind: 'delivery_qc_report', passed: false, reports: [{ issues: [{ severity: 'warning', message: '请检查衔接', evidence: { ranges: [{ start: 36, end: 40 }] } }] }] } } },
    ] };
    window.snapshot = { id: 'job_A', agent: { workspaceId: 'ws_A', planId: plan.id }, presentation: { key: 'preview_review' } };
    window.ClipTalkCurrentJobSnapshot = () => window.snapshot;
    window.opened = []; window.exported = [];
    window.ClipTalkOpenAgentPreview = preview => { window.opened.push(preview); };
    window.ClipTalkExportAgentReviewPreview = preview => { window.exported.push(preview); };
    window.ClipTalkApi = { requestJson: async () => ({ workspace: { id: 'ws_A', jobId: 'job_A', activePlanId: plan.id }, plans: [window.fixturePlan] }) };
  }, plan);
  await page.addScriptTag({ content: agentSource });
  await page.evaluate(() => window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot));
  await page.locator('#agentPlanDock footer button.primary[data-agent-review-open]').click();
  assert.equal(await page.evaluate(() => window.opened[0].filename), 'portrait.mp4');
  assert.equal(await page.locator('[data-qc-start="36"]').count(), 1);
  assert.equal(await page.locator('#agentPlanDock [data-agent-preview-export]').count(), 0);
  assert.equal(await page.evaluate(() => window.opened[0].revision), 3);
  assert.equal(await page.evaluate(() => window.exported.length), 0);
}));

test('quality review groups legacy warnings, distinguishes uncertainty and binds the exact inspected version', async () => isolatedPage(async page => {
  await page.evaluate(plan => {
    const legacy = { code: 'content_render_sample_unverified', severity: 'warning', message: '成片抽检发现未满足或无法确认原要求的画面，请检查问题片段。', evidence: { ranges: [{ start: 0, end: 21.88 }] } };
    window.fixturePlan = { ...plan, status: 'preview_ready', steps: [
      { id: 'preview', tool: 'render_review_preview', status: 'completed', result: { artifact: { kind: 'review_preview', sessionId: 's1', filename: 'landscape.mp4', previewUrl: '/landscape.mp4' } } },
      { id: 'portrait', tool: 'render_social_preview', status: 'completed', result: { artifact: { kind: 'social_reframe_preview', output: { filename: 'portrait.mp4', previewUrl: '/portrait.mp4', reframe: { aspect: '9:16' } } } } },
      { id: 'qc', tool: 'run_delivery_qc', status: 'completed', result: { artifact: { kind: 'delivery_qc_report', passed: false, reports: [
        { filename: 'landscape.mp4', issues: [legacy, structuredClone(legacy), { ...legacy, evidence: { ranges: [{ start: 21.88, end: 23.88 }] } }] },
      ] } } },
    ] };
    window.snapshot = { id: 'job_A', agent: { workspaceId: 'ws_A', planId: plan.id } };
    window.ClipTalkCurrentJobSnapshot = () => window.snapshot;
    window.opened = [];
    window.ClipTalkOpenAgentPreview = preview => window.opened.push(preview);
    window.ClipTalkApi = { requestJson: async () => ({ workspace: { id: 'ws_A', jobId: 'job_A', activePlanId: plan.id }, plans: [window.fixturePlan] }) };
  }, plan);
  await page.addScriptTag({ content: agentSource });
  await page.evaluate(() => window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot));
  const qc = page.locator('#agentPlanDock .agent-qc-summary');
  assert.equal(await qc.locator('[data-qc-status="unknown"]').count(), 2);
  assert.equal(await qc.locator(':scope > strong').textContent(), '2 段内容无法自动确认');
  assert.doesNotMatch(await qc.innerText(), /成片抽检发现未满足/);
  assert.match(await qc.innerText(), /自动检查无法判断（2 段）/);
  assert.match(await qc.innerText(), /不代表内容有误/);
  assert.equal(await qc.locator('.agent-qc-uncertain').evaluate(node => node.open), false);
  await qc.locator('.agent-qc-uncertain > summary').click();
  await qc.locator('[data-qc-start="21.88"]').click();
  assert.equal(await page.evaluate(() => window.opened.at(-1).filename), 'landscape.mp4');
  await page.evaluate(async () => {
    const report = window.fixturePlan.steps.at(-1).result.artifact.reports[0];
    const legacy = (start, end) => ({ code: 'content_render_sample_unverified', severity: 'warning',
      message: '成片抽检发现未满足或无法确认原要求的画面，请检查问题片段。', evidence: { ranges: [{ start, end }] } });
    report.issues = [
      { code: 'freeze_frames', severity: 'warning', message: '检测到持续静止画面', evidence: { ranges: [{ start: 17.77, end: 20.33 }] } },
      legacy(0, 31.33), legacy(33.3, 147.47),
    ];
    window.snapshot.revision = 1.5;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot);
  });
  assert.equal(await qc.locator(':scope > strong').textContent(), '1 个质量提醒，另有 2 段无法自动确认');
  assert.match(await qc.locator('.agent-qc-issues').innerText(), /检测到持续静止画面/);
  assert.equal(await qc.locator('.agent-qc-uncertain').evaluate(node => node.open), false);
  await page.evaluate(async () => {
    const report = window.fixturePlan.steps.at(-1).result.artifact.reports[0];
    report.goalCoverage = { requirements: [{ requirement: '核心卖点', status: 'supported' }] };
    report.aspectCheck = { expectedAspect: '9:16', status: 'mismatch' };
    report.issues = [
      { code: 'delivery_aspect_mismatch', severity: 'error', status: 'mismatch', message: '视频画幅不符：要求 9:16，实际 960×540', evidence: { reason: '封面尺寸不能代替视频画幅。' } },
      { code: 'content_render_sample_uncertain', severity: 'warning', status: 'unknown', message: '片段内容尚无法确认', evidence: { reason: '暗场不能确认换新过程。', ranges: [{ start: 10, end: 16 }], observations: [{ outputTime: 10.94, verdict: null, reason: '抽样画面较暗。' }] } },
      { code: 'content_render_sample_unavailable', severity: 'warning', status: 'unavailable', message: '内容抽检未完成' },
    ];
    window.snapshot.revision = 2;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot);
  });
  assert.equal(await qc.locator(':scope > strong').textContent(), '1 项需要修改，1 个质量提醒，1 项检查未完成');
  assert.equal(await qc.locator('[data-qc-status="mismatch"]').count(), 1);
  await qc.locator('.agent-qc-checks summary').click();
  assert.match(await qc.innerText(), /核心卖点.*抽样支持/s);
  assert.equal(await page.locator('[data-agent-plan-retry-failed]').count(), 0, 'Do not promise an unsupported automatic repair');
  await page.evaluate(async () => {
    window.fixturePlan.steps.at(-1).result.artifact.repair = { available: true, replayFromTool: 'render_social_preview', label: '重新生成画幅预览' };
    window.snapshot.revision++;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot);
  });
  assert.match(await page.locator('#agentPlanDock [data-agent-plan-retry-failed]').innerText(), /重新生成画幅预览/);
  await qc.locator('[data-qc-status="unknown"] details summary').click();
  await qc.locator('[data-qc-start="10.94"]').click();
  assert.equal(await page.evaluate(() => window.opened.at(-1).filename), 'landscape.mp4');
  const index = await readFile(resolve(root, 'static/index.html'), 'utf8');
  const styles = await Promise.all([...index.matchAll(/href="\/static\/([^"?]+\.css)/g)].map(match => readFile(resolve(root, 'static', match[1]), 'utf8')));
  await page.addStyleTag({ content: styles.join('\n') });
  await page.evaluate(() => { document.body.className = 'ct-workbench-v4'; document.body.dataset.shellMode = 'workspace'; });
  for (const theme of ['light', 'dark']) for (const width of [520, 390]) {
    await page.setViewportSize({ width, height: 1200 });
    await page.evaluate(value => { document.documentElement.dataset.theme = value; document.body.dataset.theme = value; }, theme);
    assert.equal(await qc.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await qc.locator('.agent-qc-scope').evaluate(node => getComputedStyle(node).color), theme === 'light' ? 'rgb(67, 83, 75)' : 'rgb(210, 220, 215)');
    await qc.screenshot({ path: `test-results/quality-review-${width}-${theme}.png` });
  }
}));

test('sticky action uses evidence review rather than disabled continue and clears resolved changes', async () => isolatedPage(async page => {
  await page.addScriptTag({ content: await readFile(resolve(root, 'static/chat-stream.js'), 'utf8') });
  await page.evaluate(plan => {
    window.snapshot = { id: 'job_A', status: 'awaiting_agent_plan', agent: { workspaceId: 'ws_A' }, contentSearch: { candidates: [], reviewDraft: { selectedMatchIds: [] } } };
    window.fixture = { workspace: { id: 'ws_A', jobId: 'job_A', activePlanId: plan.id, pendingChanges: [{ text: '缩短片头', status: 'queued' }] }, plans: [{ ...plan, status: 'action_required', steps: [{ id: 'evidence', tool: 'review_content_evidence', status: 'action_required', result: { action: 'content_evidence_review' } }] }] };
    window.ClipTalkCurrentJobSnapshot = () => window.snapshot;
    window.ClipTalkApi = { requestJson: async () => window.fixture };
    window.openedEvidence = 0;
    window.ClipTalkOpenContentEvidence = () => { window.openedEvidence++; };
  }, plan);
  await page.addScriptTag({ content: agentSource });
  await page.evaluate(() => window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot));
  assert.equal(await page.locator('#csActionBar [data-cs-action="primary"]').textContent(), '查看待核对片段');
  assert.equal(await page.locator('#csStreamHost [data-agent-action-resolve]').count(), 0);
  assert.equal(await page.locator('[data-cs-id="plan:plan_A"] .cs-card-body').getAttribute('aria-busy'), null);
  await page.locator('#csActionBar [data-cs-action="primary"]').click();
  assert.equal(await page.evaluate(() => window.openedEvidence), 1);
  assert.equal(await page.locator('[data-cs-id="pending:ws_A"]').count(), 1);
  await page.evaluate(async () => {
    window.fixture.workspace.pendingChanges = [];
    window.snapshot.revision = 2;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot);
  });
  assert.equal(await page.locator('[data-cs-id="pending:ws_A"]').count(), 0);
  assert.equal(await page.evaluate(() => window.ClipTalkChatStream._pendingActions().some(x => x.id === 'pending:ws_A')), false);
  await page.evaluate(async () => {
    window.fixture.plans[0].executionMode = 'autonomous_review';
    window.fixture.plans[0].steps = [{ id: 'subtitle', tool: 'prepare_subtitle_review', status: 'action_required', result: {} }];
    window.snapshot.revision = 3;
    await window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot);
  });
  assert.equal(await page.locator('#csActionBar [data-cs-action="primary"]').isDisabled(), true);
  assert.match(await page.locator('#csActionBar [data-cs-action-reason]').textContent(), /请先|正在/);
}));

test('plan confirmation has one conversation action, locks during request and retries after failure', async () => isolatedPage(async page => {
  await page.addScriptTag({ content: await readFile(resolve(root, 'static/chat-stream.js'), 'utf8') });
  await page.evaluate(plan => {
    window.snapshot = { id: 'job_A', agent: { workspaceId: 'ws_A' } };
    window.fixturePlan = { ...plan, planHash: 'hash_A', steps: [
      { id: 'video', tool: 'render_review_preview', status: 'pending' },
      { id: 'cover', tool: 'confirm_cover', status: 'pending' },
    ] };
    window.ClipTalkCurrentJobSnapshot = () => window.snapshot;
    window.confirmCalls = [];
    window.ClipTalkApi = { requestJson: async (path, options) => {
      if (path.endsWith('/confirm')) {
        window.confirmCalls.push(options.body);
        return new Promise((resolve, reject) => {
          window.failConfirm = () => reject(new Error('网络中断，请重试'));
          window.finishConfirm = () => resolve({ plan: { ...window.fixturePlan, status: 'running' } });
        });
      }
      return { workspace: { id: 'ws_A', jobId: 'job_A', activePlanId: plan.id }, plans: [window.fixturePlan] };
    } };
  }, plan);
  await page.addScriptTag({ content: agentSource });
  await page.evaluate(() => window.ClipTalkAgentWorkspace.resumeForJob(window.snapshot));
  const primary = page.locator('#csActionBar [data-cs-action="primary"]');
  assert.equal(await page.locator('#csStreamHost [data-agent-plan-confirm]').count(), 0);
  assert.equal(await page.locator('#csStreamHost [data-agent-plan-revise]').count(), 0);
  assert.equal(await page.locator('#csActionBar [data-cs-action-summary]').textContent(), '方案待确认');
  assert.equal(await page.locator('#csActionBar [data-cs-action="view"]').isVisible(), false);
  assert.equal(await page.locator('#csActionBar [data-cs-action-eyebrow]').isVisible(), false);
  await page.locator('#csStreamHost .assistant-plan-summary > summary').click();
  await page.waitForFunction(() => document.querySelector('#csActionBar [data-cs-action="view"]').textContent === '展开方案');
  await page.locator('#csActionBar [data-cs-action="view"]').click();
  await page.waitForFunction(() => document.querySelector('#csActionBar [data-cs-action="view"]').hidden);
  assert.equal(await page.locator('#csStreamHost .assistant-plan-summary').evaluate(n => n.open), true);
  assert.deepEqual(await page.locator('#csStreamHost .delivery-checklist strong').allTextContents(), ['待生成', '待生成']);
  assert.equal(await primary.textContent(), '确认并开始');
  await primary.click();
  assert.equal(await primary.textContent(), '正在启动…');
  assert.equal(await primary.isDisabled(), true);
  await page.evaluate(() => {
    window.ClipTalkChatStream._pendingActions()[0].onPrimary();
    document.querySelector('#agentPlanDrawerFooter [data-agent-plan-confirm]')?.click();
  });
  assert.equal(await page.evaluate(() => window.confirmCalls.length), 1);
  await page.evaluate(() => window.failConfirm());
  await page.waitForFunction(() => !document.querySelector('#csActionBar [data-cs-action="primary"]').disabled);
  assert.equal(await primary.textContent(), '确认并开始');
  assert.match(await page.locator('#csStreamHost [data-agent-operation-message]').textContent(), /网络中断/);
  await primary.click();
  assert.equal(await page.evaluate(() => window.confirmCalls.length), 2);
  await page.evaluate(() => window.finishConfirm());
  await page.waitForFunction(() => document.querySelector('#csActionBar').hidden);
  assert.equal(await page.evaluate(() => window.ClipTalkAgentWorkspace.confirmationState()), null);
  assert.deepEqual(await page.evaluate(() => window.confirmCalls), [{ planHash: 'hash_A' }, { planHash: 'hash_A' }]);
}));

test('Escape settles authentication and permits a fresh attempt', async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route('http://auth.test/**', r => r.fulfill({ contentType: 'text/html; charset=utf-8', body: '<dialog id="accessTokenDialog"><form><input><button>确定</button><button type="button" data-auth-cancel>取消</button></form></dialog>' }));
    await page.goto('http://auth.test');
    await page.evaluate(() => { window.fetch = async () => new Response('{"detail":"unauthorized"}', { status: 401 }); });
    await page.addScriptTag({ content: apiSource });
    await page.evaluate(() => { window.settled = false; window.ClipTalkApi.request('/api/test').catch(() => { window.settled = true; }); });
    await page.waitForFunction(() => document.querySelector('dialog').open);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => window.settled);
    await page.evaluate(() => { window.ClipTalkApi.request('/api/test').catch(() => {}); });
    await page.waitForFunction(() => document.querySelector('dialog').open);
    await page.getByText('取消', { exact: true }).click();
  } finally { await browser.close(); }
});

async function staticApp(job = null) {
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://localhost').pathname;
    if (path.startsWith('/api/')) {
      response.setHeader('Content-Type', 'application/json');
      const value = path === '/api/health' ? { uiContractVersion: 2, ok: true, ffmpeg: true, ffprobe: true, visionConfigured: true, capabilityStatus: 'degraded', capabilityLabel: '部分功能不可用', capabilityIssues: ['语音识别不可用'] }
        : path === '/api/setup/status' ? { complete: true, canCreateTask: true, canUseAgent: true, steps: [] }
        : job && path === `/api/jobs/${job.id}` ? { job }
        : job && path === `/api/jobs/${job.id}/status` ? { job }
        : path === '/api/jobs' ? { jobs: job ? [job] : [{ id: 'cancelled', filename: '产品.mp4', status: 'cancelled', presentation: { schemaVersion: 2, key: 'cancelled', group: 'cancelled', label: '已取消' } }] }
        : { providers: [], skills: [], outputs: [], workspaces: [] };
      response.end(JSON.stringify(value)); return;
    }
    const file = resolve(root, 'static', path === '/' ? 'index.html' : path.replace(/^\/static\//, ''));
    if (!file.startsWith(resolve(root, 'static') + '/')) { response.writeHead(404); response.end(); return; }
    try {
      response.setHeader('Content-Type', ({ '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.woff2': 'font/woff2', '.png': 'image/png' })[extname(file)] || 'application/octet-stream');
      response.end(await readFile(file));
    } catch { response.writeHead(404); response.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { url: `http://127.0.0.1:${server.address().port}`, close: () => new Promise(resolve => server.close(resolve)) };
}

test('streamed confirmation overrides lagging planning chrome in the real workspace', async () => {
  const job = { id: 'job_A', filename: '产品.mp4', status: 'awaiting_agent_plan', instructionSubmitted: true,
    agent: { workspaceId: 'ws_A', planId: 'plan_A', status: 'awaiting_confirmation' },
    presentation: { schemaVersion: 3, key: 'plan_planning', label: '正在生成剪辑计划', running: true, journeyStage: 1 } };
  const server = await staticApp(job);
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.route('**/api/agent/workspaces/ws_A', route => route.fulfill({ json: {
      workspace: { id: 'ws_A', jobId: job.id, activePlanId: plan.id }, plans: [{ ...plan, steps: [
        { id: 'video', tool: 'render_review_preview', status: 'pending' },
        { id: 'cover', tool: 'confirm_cover', status: 'pending' },
      ] }],
    } }));
    await page.goto(server.url, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => openHomeTask('job_A'));
    await page.waitForFunction(() => document.querySelector('#ctTaskJourney .ct-journey-summary strong')?.textContent === '等待确认计划');
    for (const theme of ['light', 'dark']) {
      await page.evaluate(value => window.ClipTalkTheme.apply(value), theme);
      assert.equal(await page.getByRole('button', { name: '确认并开始', exact: true }).count(), 1);
      assert.equal(await page.locator('#csStreamHost [data-agent-plan-confirm]').count(), 0);
      assert.equal(await page.locator('#csStreamHost [data-agent-plan-revise]').count(), 0);
      const bounds = await page.evaluate(() => {
        const rect = id => { const r = document.querySelector(id).getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; };
        return { chat: rect('#chatMessages'), bar: rect('#csActionBar'), form: rect('#chatForm') };
      });
      assert.ok(bounds.chat.bottom <= bounds.bar.top + 1, 'Actions must follow the scrollable conversation');
      assert.ok(bounds.bar.bottom <= bounds.form.top + 1, 'Actions must not overlap the composer');
      assert.deepEqual(await page.locator('#csStreamHost .delivery-checklist strong').allTextContents(), ['待生成', '待生成']);
      await page.screenshot({ path: `test-results/single-confirm-${theme}.png` });
    }
    const stationary = await page.evaluate(() => {
      const messages = document.querySelector('#chatMessages');
      const filler = document.createElement('div');
      filler.style.height = '1800px';
      messages.append(filler);
      const bar = document.querySelector('#csActionBar');
      const before = bar.getBoundingClientRect().top;
      messages.scrollTop = messages.scrollHeight;
      const after = bar.getBoundingClientRect().top;
      filler.remove();
      return Math.abs(after - before) < 1;
    });
    assert.ok(stationary, 'Scrolling a long plan must not move the bottom confirmation controls');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('button[data-ct-compact-view="assistant"]').click();
    assert.equal(await page.getByRole('button', { name: '确认并开始', exact: true }).count(), 1);
    assert.equal(await page.locator('#csActionBar').evaluate(n => n.scrollWidth <= n.clientWidth + 1), true);
    await page.locator('button[data-ct-compact-view="preview"]').click();
    assert.equal(await page.getByRole('button', { name: '确认并开始', exact: true }).count(), 1);
    assert.equal(await page.locator('#csMobileActionBar [data-mobile-primary]').isVisible(), true);
  } finally { await browser.close(); await server.close(); }
});

test('running Agent owns one honest progress card and stops the whole plan with retry', async () => {
  const job = { id: 'job_A', filename: '产品.mp4', status: 'awaiting_agent_plan', stage: 'agent_plan_running', taskMode: 'content_extract', instructionSubmitted: true,
    messages: [{ id: 'notice', role: 'assistant', kind: 'notice', text: '已整理本次要求，请核对后开始执行。' }],
    agent: { workspaceId: 'ws_A', planId: 'plan_A', status: 'running', currentStepTool: 'search_content' },
    execution: { schemaVersion: 1, status: 'running', active: true, operation: 'content_search', capabilities: { canCancel: true } },
    presentation: { schemaVersion: 3, key: 'running', label: '正在生成按需执行计划', running: true, journeyStage: 2 },
    progressFacts: { stage: { mode: 'indeterminate', fraction: .99, label: '建立画面索引' },
      activity: { detail: '正在生成按需执行计划', model: '系统' }, timing: {
        processingElapsedSeconds: 15, processingActiveSince: new Date().toISOString(), processingTimingVersion: 1,
      } } };
  let fixture = { ...plan, status: 'running', steps: [
    { id: 'search', tool: 'search_content', title: '提取指定主题的 Hook 证据', status: 'waiting_operation' },
    { id: 'video', tool: 'render_review_preview', status: 'pending' },
    { id: 'cover', tool: 'confirm_cover', status: 'pending' },
  ] };
  const server = await staticApp(job);
  const browser = await chromium.launch();
  let releaseCancel, calls = 0;
  const writes = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() === 'POST') writes.push(path);
      if (path.endsWith('/plans/plan_A/cancel')) {
        calls++;
        await new Promise(resolve => { releaseCancel = resolve; });
        if (calls === 1) return route.fulfill({ status: 503, json: { detail: '停止失败，请重试' } });
        fixture = { ...fixture, status: 'cancelled', steps: fixture.steps.map(s => ({ ...s, status: 'cancelled' })) };
        return route.fulfill({ json: { plan: fixture } });
      }
      if (path === '/api/agent/plans/plan_A') return route.fulfill({ json: { plan: fixture } });
      if (path === '/api/agent/workspaces/ws_A') return route.fulfill({ json: { workspace: { id: 'ws_A', jobId: job.id, activePlanId: plan.id }, plans: [fixture] } });
      return route.continue();
    });
    await page.goto(server.url, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => openHomeTask('job_A'));
    const card = page.locator('#csStreamHost [data-agent-execution]');
    await card.waitFor();
    assert.equal(await page.locator('#inlineAnalysisProgress').count(), 0);
    assert.equal(await page.locator('#ctTaskJourney .ct-journey-summary strong').textContent(), '分析素材');
    assert.equal(await card.locator('strong').textContent(), '正在寻找适合开场的片段');
    // The display keeps ticking in real time, so a busy full-suite run may
    // cross the next second between opening the card and reading its text.
    assert.match(await card.innerText(), /已用时 0:1[56]/);
    await page.waitForFunction(() => document.querySelector('[data-agent-execution-elapsed]')?.textContent.includes('0:16'));
    assert.equal(await card.locator('progress').isVisible(), false);
    const track = card.locator('.agent-execution-track');
    await card.locator('.agent-execution-loader .il-loader').waitFor();
    assert.equal(await track.isVisible(), true);
    assert.equal(await track.getAttribute('data-execution-mode'), 'indeterminate');
    assert.equal(await track.locator('i').evaluate(el => getComputedStyle(el).animationName), 'ct-execution-scan');
    assert.equal(await track.locator('i').evaluate(el => el.getBoundingClientRect().height >= 4 && getComputedStyle(el).backgroundColor !== 'rgba(0, 0, 0, 0)'), true);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await track.locator('i').evaluate(el => getComputedStyle(el).animationName), 'none');
    assert.equal(await card.locator('.agent-execution-loader').evaluate(el => [...el.querySelectorAll('*')].every(node => getComputedStyle(node).animationName === 'none')), true);
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.evaluate(() => { window.testExecutionNode = document.querySelector('[data-agent-execution]'); });
    job.progressFacts.timing.processingElapsedSeconds = 18;
    job.progressFacts.timing.processingActiveSince = new Date().toISOString();
    job.revision = 2;
    await page.evaluate(async job => { renderJob(job); await window.ClipTalkAgentWorkspace.resumeForJob(job); }, job);
    assert.equal(await card.evaluate(el => el === window.testExecutionNode), true, 'Polling must preserve the animated card');
    assert.match(await card.innerText(), /已用时 0:18/);
    assert.equal(await page.locator('#csStreamHost .agent-cover-status').count(), 0);
    assert.match(await card.innerText(), /后续：生成样片、制作封面/);
    assert.doesNotMatch(await card.innerText(), /Hook|系统|暂无法估算|按需执行计划/);
    assert.equal(await page.locator('[data-conversation-key="message:notice"] details').count(), 1);
    for (const theme of ['light', 'dark']) {
      await page.evaluate(value => window.ClipTalkTheme.apply(value), theme);
      assert.equal(await page.getByRole('button', { name: '停止任务', exact: true }).count(), 1);
      await page.screenshot({ path: `test-results/agent-running-${theme}.png` });
    }
    job.progressFacts.stage = { mode: 'determinate', fraction: .3, completed: 12, total: 40, unit: '段' };
    await page.evaluate(job => renderJob(job), job);
    await page.waitForFunction(() => document.querySelector('[data-agent-execution-count]')?.textContent.includes('12/40'));
    assert.equal(await card.locator('progress').getAttribute('value'), '0.3');
    assert.equal(await track.getAttribute('data-execution-mode'), 'determinate');
    assert.equal(await track.evaluate(el => el.style.getPropertyValue('--execution-fraction')), '0.3');
    assert.equal(await track.locator('i').evaluate(el => getComputedStyle(el).transitionProperty), 'transform');
    assert.equal(await track.locator('i').evaluate(el => getComputedStyle(el).animationName), 'none');
    fixture.steps[0].status = 'completed';
    fixture.steps[1].status = 'waiting_operation';
    job.revision = 3;
    job.execution.operation = 'render';
    job.agent.currentStepTool = 'render_review_preview';
    job.progressFacts.stage = { mode: 'indeterminate' };
    await page.evaluate(job => renderJob(job), job);
    await page.waitForFunction(() => document.querySelector('#csStreamHost [data-agent-execution]')?.dataset.executionStep === 'video');
    assert.equal(await card.locator('strong').textContent(), '正在生成可预览的视频');
    assert.equal(await card.locator('.agent-execution-heading').evaluate(el => getComputedStyle(el).animationName), 'ct-execution-stage-in');
    assert.equal(await track.getAttribute('data-execution-mode'), 'indeterminate');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('button[data-ct-compact-view="assistant"]').click();
    assert.equal(await page.getByRole('button', { name: '停止任务', exact: true }).count(), 1);
    const stop = card.locator('[data-agent-plan-cancel]');
    await stop.click();
    assert.equal(await stop.isDisabled(), true);
    assert.equal(await card.getAttribute('data-motion-state'), 'stopping');
    assert.equal(await card.locator('.agent-execution-loader').getAttribute('data-loader-active'), 'false');
    assert.equal(await track.locator('i').evaluate(el => getComputedStyle(el).animationPlayState), 'paused');
    await stop.evaluate(button => button.click());
    await page.waitForTimeout(100);
    assert.equal(calls, 1);
    releaseCancel();
    await page.waitForFunction(() => !document.querySelector('#csStreamHost [data-agent-plan-cancel]')?.disabled);
    assert.match(await card.locator('[data-agent-operation-message]').textContent(), /停止失败/);
    assert.equal(await card.getAttribute('data-motion-state'), 'running');
    await stop.click();
    await page.waitForTimeout(100);
    releaseCancel();
    await page.waitForFunction(() => !document.querySelector('#csStreamHost [data-agent-execution]'));
    assert.equal(await page.locator('#inlineAnalysisProgress').count(), 0);
    assert.deepEqual(writes, ['/api/agent/plans/plan_A/cancel', '/api/agent/plans/plan_A/cancel']);
    assert.deepEqual(errors, []);
  } finally { releaseCancel?.(); await browser.close(); await server.close(); }
});

test('candidate select-all is a leading tri-state checkbox, preserves failures and empty drafts', async () => {
  const candidates = ['a', 'b', 'c', 'rejected'].map((id, index) => ({ id, title: `产品片段 ${index + 1}`,
    start: index * 10, end: index * 10 + 5, duration: 5, confidenceTier: 'reliable',
    reviewStatus: id === 'rejected' ? 'rejected' : 'confirmed' }));
  const job = { id: 'job_selection', filename: '产品.mp4', status: 'awaiting_content_confirmation',
    taskMode: 'content_extract', workflowKind: 'content_search', stage: 'content_confirmation',
    presentation: { schemaVersion: 4, key: 'content_review', group: 'action_required', label: '核对片段', journeyStage: 3, primaryActionKey: 'review_content' },
    messages: [{ id: 'selection_result', role: 'assistant', kind: 'content-search', contentSearchId: 'search_selection', text: '检索完成' }],
    instructionSubmitted: true, videoInfo: { duration: 90, has_audio: false },
    contentSearch: { id: 'search_selection', status: 'review_required', resultMode: 'top_k',
      instruction: '产品片段', candidates, defaultSelectedIds: ['a', 'b', 'c'] } };
  const server = await staticApp(job);
  const browser = await chromium.launch();
  let releaseBulk, calls = 0;
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/content-search/bulk-keep') || path.endsWith('/content-search/feedback')) throw new Error('Selection must not approve candidates');
      if (path.endsWith('/content-search/review-draft')) {
        const draft = route.request().postDataJSON();
        if (draft.selectedMatchIds.length === 3) {
          calls++;
          assert.deepEqual(draft.selectedMatchIds, ['a', 'b', 'c']);
          await new Promise(resolve => { releaseBulk = resolve; });
          if (calls === 1) return route.fulfill({ status: 503, json: { detail: '测试重试' } });
        }
        job.contentSearch.reviewDraft = draft;
        job.contentSearch.defaultSelectedIds = draft.selectedMatchIds;
        return route.fulfill({ json: { reviewDraft: draft } });
      }
      return route.continue();
    });
    await page.goto(server.url, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => openHomeTask('job_selection'));
    // Exercise the same conversation review card used by the Agent. Legacy
    // task opening otherwise moves this card into the separate review rail.
    await page.evaluate(value => { currentJob = value; renderConversation(value); }, job);
    const review = page.locator('#chatMessages .content-search-review[data-content-search-id="search_selection"]');
    const all = review.locator('input[data-content-select]');
    const first = review.locator('input[data-content-match][value="a"]');
    await all.waitFor();
    assert.equal(await all.isChecked(), true);
    assert.equal(await review.locator('.content-exhaustive-controls-bottom').count(), 0);
    assert.equal(await review.locator('[data-content-select-count]').textContent(), '已选 3 / 3 段');
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      if (width === 390) await page.locator('[data-ct-compact-view="assistant"]').click();
      for (const theme of ['light', 'dark']) {
        await page.evaluate(value => window.ClipTalkTheme.apply(value), theme);
        await all.scrollIntoViewIfNeeded();
        await page.waitForTimeout(350);
        assert.equal(await review.evaluate(root => {
          const toolbar = root.querySelector('.content-selection-toolbar').getBoundingClientRect();
          const list = root.querySelector('.content-match-list').getBoundingClientRect();
          return toolbar.bottom <= list.top + 1 && toolbar.width <= root.clientWidth + 1;
        }), true);
        await page.screenshot({ path: `test-results/candidate-selection-${width}-${theme}.png` });
      }
    }
    await first.uncheck();
    assert.equal(await all.evaluate(input => input.indeterminate), true);
    assert.equal(await review.locator('[data-content-select-count]').textContent(), '已选 2 / 3 段');
    await all.check();
    assert.equal(await all.isDisabled(), true);
    assert.equal(await review.locator('[data-confirm-content]').isDisabled(), true);
    await page.waitForTimeout(100);
    releaseBulk();
    await page.waitForFunction(() => !document.querySelector('#chatMessages input[data-content-select]')?.disabled);
    assert.equal(await all.evaluate(input => input.indeterminate), true);
    assert.equal(await first.isChecked(), false);
    assert.equal(await review.locator('input[data-content-match]:checked').count(), 2);
    await all.check();
    await page.waitForTimeout(100);
    releaseBulk();
    await page.waitForFunction(() => !document.querySelector('#chatMessages input[data-content-select]')?.disabled);
    assert.equal(await all.isChecked(), true);
    await all.focus();
    await page.keyboard.press('Space');
    assert.equal(await all.isChecked(), false);
    assert.equal(await review.locator('input[data-content-match]:checked').count(), 0);
    assert.equal(await review.locator('[data-confirm-content]').isDisabled(), true);
    await page.waitForTimeout(400);
    assert.deepEqual(job.contentSearch.reviewDraft.selectedMatchIds, []);
    await page.evaluate(value => { currentJob = value; renderConversation(value); }, job);
    assert.equal(await all.isChecked(), false);
    assert.equal(await review.locator('input[data-content-match]:checked').count(), 0);
    assert.equal(calls, 2);
    assert.deepEqual(errors, []);
  } finally { releaseBulk?.(); await browser.close(); await server.close(); }
});

test('Agent content review separates selection, explicit range confirmation and plan continuation', async () => {
  const verified = (start, end) => ({ version: 'content-contract-v1', status: 'human_confirmed', verifiedRange: [start, end] });
  const job = { id: 'review_job', revision: 1, filename: '产品.mp4', taskMode: 'content_extract', workflowKind: 'content_search',
    status: 'awaiting_content_confirmation', stage: 'content_confirmation', instructionSubmitted: true,
    videoInfo: { duration: 90, width: 1280, height: 720, has_audio: false },
    presentation: { schemaVersion: 4, key: 'content_review', label: '核对片段', journeyStage: 3 },
    agent: { workspaceId: 'review_ws', planId: 'review_plan', status: 'action_required' },
    messages: [{ id: 'result', kind: 'content-search', role: 'assistant', contentSearchId: 'review_search', text: '片段已就绪' }],
    contentSearch: { id: 'review_search', resultMode: 'top_k', status: 'review_required', defaultSelectedIds: ['b'], candidates: [
      { id: 'a', title: '空调核心卖点', start: 10, end: 15, duration: 5, confidenceTier: 'reliable', reviewStatus: 'pending', requiresReview: true,
        subjectDescription: '白色空调', subjectStatus: 'unverified' },
      { id: 'b', title: '冰箱新老替换', start: 20, end: 25, duration: 5, confidenceTier: 'reliable', reviewStatus: 'confirmed', boundaryVerification: verified(20, 25) },
    ] } };
  let fixture = { id: 'review_plan', workspaceId: 'review_ws', status: 'action_required', steps: [
    { id: 'evidence', tool: 'review_content_evidence', status: 'action_required', result: { action: 'content_evidence_review' } },
    { id: 'render', tool: 'render_review_preview', status: 'pending' },
  ] };
  const server = await staticApp(job);
  const browser = await chromium.launch();
  const writes = [], errors = [];
  let feedbackCalls = 0, resolveCalls = 0, failSave = false, releaseResolve;
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      const method = route.request().method();
      if (['POST', 'PATCH'].includes(method)) writes.push(path);
      if (path === '/api/agent/workspaces/review_ws') return route.fulfill({ json: { workspace: { id: 'review_ws', jobId: job.id, activePlanId: fixture.id }, plans: [fixture] } });
      if (path === '/api/agent/plans/review_plan') return route.fulfill({ json: { plan: fixture } });
      if (path.endsWith('/review-draft')) {
        if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { detail: '保存暂不可用' } }); }
        const draft = route.request().postDataJSON();
        job.contentSearch.reviewDraft = draft;
        job.contentSearch.defaultSelectedIds = draft.selectedMatchIds;
        return route.fulfill({ json: { reviewDraft: draft } });
      }
      if (path.endsWith('/feedback')) {
        feedbackCalls++;
        assert.equal(route.request().postDataJSON().verdict, 'review_keep');
        if (feedbackCalls === 1) return route.fulfill({ status: 503, json: { detail: '核对保存暂不可用' } });
        job.contentSearch.candidates[0].boundaryVerification = verified(10, 15);
        job.contentSearch.candidates[0].reviewStatus = 'kept';
        job.contentSearch.candidates[0].requiresReview = false;
        job.revision++;
        return route.fulfill({ json: { job } });
      }
      if (path.endsWith('/actions/resolve')) {
        resolveCalls++;
        const payload = route.request().postDataJSON();
        assert.equal(payload.value.context.stepId, 'evidence');
        assert.deepEqual(new Set(payload.value.selection.matchIds), new Set(['a', 'b']));
        await new Promise(resolve => { releaseResolve = resolve; });
        fixture = { ...fixture, status: 'running', steps: fixture.steps.map(s => ({ ...s, status: s.id === 'evidence' ? 'completed' : 'running' })) };
        job.status = 'running'; job.revision++;
        return route.fulfill({ json: { plan: fixture } });
      }
      return route.continue();
    });
    await page.goto(server.url, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => openHomeTask('review_job'));
    await page.waitForFunction(() => !!window.ClipTalkAgentWorkspace.contentReviewContext());
    await page.evaluate(value => { currentJob = value; renderConversation(value); }, job);
    assert.deepEqual(await page.evaluate(() => {
      const match = currentJob.contentSearch.candidates[1];
      return [
        contentRangeVerified(match),
        contentRangeVerified({ ...match, end: match.end + 1 }),
        contentRangeVerified({ ...match, boundaryVerification: { ...match.boundaryVerification, version: 'old' } }),
        contentRangeVerified(match, { contentContract: { fingerprint: 'different-source' } }),
      ];
    }), [true, false, false, false]);
    const review = page.locator('.content-search-review:has([data-confirm-content])');
    const confirm = review.locator('[data-confirm-content]');
    assert.equal(await confirm.textContent(), '保存选择并继续');
    assert.equal(await review.locator('.content-generation-settings').isVisible(), false);
    await review.locator('[data-content-select]').check();
    await page.waitForFunction(() => !document.querySelector('.content-search-review[data-agent-content-review="true"]')?.dataset.selectionBusy);
    assert.equal(feedbackCalls, 0);
    assert.equal(await confirm.textContent(), '还有 1 段待核对');
    assert.equal(await confirm.isDisabled(), true);
    assert.match(await review.innerText(), /对象匹配待核对：白色空调/);
    assert.equal(await review.locator('[data-content-match][value="a"]').getAttribute('data-content-review-status'), 'pending');
    for (const theme of ['light', 'dark']) {
      await page.evaluate(value => window.ClipTalkTheme.apply(value), theme);
      await page.waitForTimeout(350);
      assert.equal(await review.locator('.content-subject-hint').evaluate(node => getComputedStyle(node).color),
        theme === 'light' ? 'rgb(67, 83, 75)' : 'rgb(183, 200, 192)');
      await review.screenshot({ path: `test-results/content-review-${theme}.png` });
    }
    await review.locator('[data-content-review-next]').click();
    const editor = page.locator('#contentBoundaryInspector [data-content-boundary-editor="a"]');
    await editor.waitFor();
    await page.evaluate(() => {
      window.reviewToasts = [];
      window.showToast = message => window.reviewToasts.push(message);
      window.reviewEditor = document.querySelector('#contentBoundaryInspector [data-content-boundary-editor="a"]');
    });
    await editor.locator('[data-boundary-value="start"]').fill('10.5');
    await editor.locator('[data-boundary-value="start"]').dispatchEvent('change');
    await review.locator('[data-content-review-next]').click();
    assert.deepEqual(await page.evaluate(() => window.reviewToasts), [], 'Reopening the displayed editor must not claim it is unready');
    assert.equal(await editor.evaluate(el => el === window.reviewEditor), true);
    assert.equal(await editor.locator('[data-boundary-value="start"]').inputValue(), '10.5', 'Repeated entry preserves unsaved boundaries');
    await review.locator('[data-content-boundary-open="a"]').click();
    assert.deepEqual(await page.evaluate(() => window.reviewToasts), [], 'The per-clip entry also reuses the portaled editor');
    assert.equal(await editor.locator('[data-boundary-value="start"]').inputValue(), '10.5');
    await page.evaluate(() => closeContentBoundaryTimelineEdit({ restorePreview: false }));
    assert.equal(await review.locator('[data-content-match-row="a"] [data-content-boundary-editor="a"]').count(), 1, 'Closing returns the editor to its original row');
    await review.locator('[data-content-review-next]').click();
    await editor.waitFor();
    const save = editor.locator('[data-boundary-save]');
    assert.equal(await save.textContent(), '已核对，保留');
    await save.click();
    await page.waitForFunction(() => [...document.querySelectorAll('[data-boundary-error]')].some(node => node.textContent.includes('确认失败')));
    assert.equal(await save.isDisabled(), false);
    assert.equal(resolveCalls, 0);
    await save.click();
    await page.waitForFunction(() => [...document.querySelectorAll('[data-confirm-content]')].some(button => button.textContent === '保存选择并继续' && !button.disabled));
    assert.equal(job.contentSearch.candidates[0].subjectStatus, 'unverified');
    failSave = true;
    await confirm.click();
    await page.waitForFunction(() => [...document.querySelectorAll('[data-content-action-hint]')].some(node => node.textContent.includes('保存失败')));
    assert.equal(resolveCalls, 0);
    await confirm.click();
    await page.waitForTimeout(150);
    assert.equal(await confirm.isDisabled(), true);
    assert.equal(await review.locator('[data-content-match][value="a"]').isDisabled(), true);
    await confirm.evaluate(button => button.click());
    assert.equal(resolveCalls, 1);
    releaseResolve();
    await page.waitForFunction(() => window.ClipTalkAgentWorkspace.progressOwner()?.status === 'running');
    assert.equal(resolveCalls, 1);
    assert.equal(writes.some(path => path.endsWith('/bulk-keep') || path.endsWith('/content-search/confirm')), false);
    assert.deepEqual(errors, []);
  } finally { releaseResolve?.(); await browser.close(); await server.close(); }
});

test('filtered drawer selection preserves other clips and independent generation keeps its risk gate', async () => {
  const job = { id: 'drawer_job', revision: 1, filename: '产品.mp4', status: 'awaiting_content_confirmation', stage: 'content_confirmation',
    taskMode: 'content_extract', workflowKind: 'content_search', videoInfo: { duration: 90, has_audio: false },
    messages: [{ id: 'result', role: 'assistant', kind: 'content-search', contentSearchId: 'drawer_search', text: '片段就绪' }],
    contentSearch: { id: 'drawer_search', status: 'review_required', resultMode: 'top_k', defaultSelectedIds: ['b'], candidates: [
      { id: 'a', title: '空调', start: 10, end: 15, duration: 5, confidenceTier: 'reliable', reviewStatus: 'pending' },
      { id: 'b', title: '冰箱', start: 20, end: 25, duration: 5, confidenceTier: 'reliable', reviewStatus: 'confirmed' },
      { id: 'c', title: '已排除', start: 30, end: 35, duration: 5, reviewStatus: 'rejected' },
    ] } };
  const server = await staticApp(job), browser = await chromium.launch();
  let generated = 0, failSave = false;
  const writes = [], errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (['POST', 'PATCH'].includes(route.request().method())) writes.push(path);
      if (path.endsWith('/review-draft')) {
        if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { detail: '保存失败' } }); }
        const draft = route.request().postDataJSON(); job.contentSearch.reviewDraft = draft;
        job.contentSearch.defaultSelectedIds = draft.selectedMatchIds;
        return route.fulfill({ json: { reviewDraft: draft } });
      }
      if (path.endsWith('/content-search/confirm')) {
        generated++;
        assert.equal(route.request().postDataJSON().acknowledgeUnverified, true);
        assert.deepEqual(route.request().postDataJSON().matchIds, ['b']);
        job.status = 'running'; job.revision++;
        return route.fulfill({ json: { job } });
      }
      return route.continue();
    });
    await page.goto(server.url, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => openHomeTask('drawer_job'));
    await page.evaluate(value => { currentJob = value; renderConversation(value); openCandidateDrawer(); }, job);
    await page.locator('#candidateDrawerSearch').fill('空调');
    const toggle = page.locator('[data-drawer-content-toggle]');
    await toggle.check();
    await page.waitForTimeout(400);
    assert.deepEqual(new Set(job.contentSearch.reviewDraft.selectedMatchIds), new Set(['a', 'b']));
    assert.equal(job.contentSearch.candidates[0].reviewStatus, 'pending');
    await toggle.uncheck();
    await page.waitForTimeout(400);
    assert.deepEqual(job.contentSearch.reviewDraft.selectedMatchIds, ['b']);
    await page.evaluate(() => {
      closeCandidateDrawer(); window.confirmationPrompts = [];
      requestActionConfirmation = async options => { window.confirmationPrompts.push(options); return true; };
    });
    const confirm = page.locator('.content-search-review [data-confirm-content]');
    failSave = true;
    await confirm.click();
    await page.waitForTimeout(200);
    assert.equal(generated, 0);
    assert.equal(await page.evaluate(() => window.confirmationPrompts.length), 1);
    await confirm.click();
    await page.waitForFunction(() => window.ClipTalkCurrentJobSnapshot()?.status === 'running');
    assert.equal(generated, 1);
    assert.match(await page.evaluate(() => window.confirmationPrompts[0].warning), /尚未核验/);
    assert.equal(writes.some(path => /bulk-keep|feedback|actions\/resolve/.test(path)), false);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); await server.close(); }
});

test('home groups never leak overflow tasks into recent and group links filter the full list', async () => {
  const server = await staticApp();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const groups = ['action_required', 'failed', 'no_result', 'action_required', 'failed', 'active', 'agent_planning', 'active', 'agent_planning', 'active', 'completed', 'draft', 'cancelled'];
    const jobs = groups.map((group, i) => ({ id: `group_${i}`, filename: `任务${i}.mp4`, status: group,
      updatedAt: `2026-09-${String(i + 1).padStart(2, '0')}T10:00:00Z`,
      presentation: { schemaVersion: 4, key: group, group, label: group } }));
    await page.route('**/api/jobs?*', route => route.fulfill({ json: { jobs } }));
    await page.route('**/api/jobs', route => route.fulfill({ json: { jobs } }));
    await page.goto(server.url, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelectorAll('[data-home-group]').length === 3);
    for (const [key, count] of [['attention', 5], ['running', 5], ['recent', 3]]) {
      const group = page.locator(`[data-home-group="${key}"]`);
      assert.equal(await group.locator('.shell-task-card').count(), Math.min(4, count));
      assert.match(await group.locator('header').textContent(), new RegExp(`· ${count}`));
    }
    assert.deepEqual(await page.locator('[data-home-group="recent"] .shell-task-card').evaluateAll(nodes => nodes.map(n => n.dataset.shellJob)), ['group_12', 'group_11', 'group_10']);
    await page.locator('[data-home-history="attention"]').click();
    await page.waitForFunction(() => document.querySelectorAll('#sidebarHistoryList .shell-task-card').length === 5);
    assert.deepEqual(new Set(await page.locator('#sidebarHistoryList .shell-task-card').evaluateAll(nodes => nodes.map(n => n.dataset.statusGroup))), new Set(['action_required', 'failed', 'no_result']));
    await page.locator('#sidebarGroupNotice').click();
    await page.waitForFunction(() => document.querySelectorAll('#sidebarHistoryList .shell-task-card').length === 13);
  } finally { await browser.close(); await server.close(); }
});

test('long clip titles and thumbnail columns fit their container in both themes', async () => {
  const server = await staticApp();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(server.url, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => typeof contentSearchReviewMarkup === 'function');
    await page.evaluate(async () => {
      const title = '介绍产品价格并比较不同配置的使用场景与选择建议，同时保留讲解者完整观点和前后文';
      const search = { id: 'layout', resultMode: 'top_k', status: 'review_required', instruction: '产品价格',
        executionPlan: { allowedCapabilities: ['visual'] }, defaultSelectedIds: ['clip'],
        candidates: [{ id: 'clip', title, start: 1, end: 8, duration: 7, confidence: .9, confidenceTier: 'reliable', reviewStatus: 'confirmed', matchedEvidence: '产品定价介绍' }] };
      const host = document.createElement('section');
      host.id = 'uxClipFixture';
      host.style.cssText = 'position:fixed;inset:105px auto auto 8px;width:300px;max-height:calc(100vh - 115px);overflow:auto;z-index:1000;background:var(--ct-panel);';
      const job = { id: 'layout', filename: '产品介绍.mp4', status: 'awaiting_content_confirmation', taskMode: 'content_extract', videoInfo: { duration: 60 }, contentSearch: search };
      await window.ClipTalkSwitchWorkspaceJob(job);
      window.ClipTalkAppShell.showView('workspace', { route: false });
      document.querySelector('#workspace').classList.remove('home-mode');
      document.body.classList.add('ct-workbench-v4');
      host.innerHTML = contentSearchReviewMarkup(job);
      document.querySelector('#chatMessages').append(host);
      const thumb = host.querySelector('.content-match-thumb');
      thumb.removeAttribute('data-content-match-thumb-pending');
      thumb.style.background = '#76917c';
    });
    for (const width of [390, 768, 1280, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.waitForTimeout(100);
      await page.evaluate(() => document.querySelector('[data-ct-compact-view="assistant"]')?.click());
      for (const theme of ['light', 'dark']) {
        await page.evaluate(theme => window.ClipTalkTheme.apply(theme), theme);
        await page.waitForTimeout(350);
        for (const containerWidth of [300, Math.min(480, width - 24)]) {
          await page.locator('#uxClipFixture').evaluate((node, value) => { node.style.width = `${value}px`; }, containerWidth);
          const sizes = await page.locator('#uxClipFixture .content-match-row').evaluate(node => {
            const thumb = node.querySelector('.content-match-thumb').getBoundingClientRect();
            return { overflow: node.scrollWidth - node.clientWidth, copy: node.querySelector('.content-match-copy').getBoundingClientRect().width, thumb: [thumb.width, thumb.height] };
          });
          assert.ok(sizes.overflow <= 1, JSON.stringify({ width, theme, containerWidth, sizes }));
          assert.ok(sizes.copy >= 150, JSON.stringify({ width, theme, sizes }));
          assert.deepEqual(sizes.thumb, [112, 63]);
          if (theme === 'light') {
            const colors = await page.locator('#uxClipFixture').evaluate(node => ({
              foreground: getComputedStyle(node.querySelector('.content-match-full-title p')).color,
              background: getComputedStyle(node.querySelector('.content-match-row')).backgroundColor,
            }));
            assert.ok(contrast(colors.foreground, colors.background) >= 4.5, JSON.stringify(colors));
          }
        }
      }
    }
    await page.locator('#uxClipFixture .content-match-full-title summary').click();
    assert.match(await page.locator('#uxClipFixture .content-match-full-title p').innerText(), /完整观点和前后文/);
    if (process.env.CLIPTALK_UX_CAPTURE) {
      await page.setViewportSize({ width: 390, height: 900 });
      await page.evaluate(() => document.querySelector('[data-ct-compact-view="assistant"]')?.click());
      await page.locator('#uxClipFixture').evaluate(node => { node.style.width = '350px'; });
      for (const theme of ['light', 'dark']) {
        await page.evaluate(theme => window.ClipTalkTheme.apply(theme), theme);
        await page.waitForTimeout(350);
        await page.locator('#uxClipFixture').screenshot({ path: `/tmp/cliptalk-ux-clips-${theme}.png` });
      }
    }
  } finally { await browser.close(); await server.close(); }
});

test('reused Agent model has a direct shared probe, retry and dirty-configuration guard', async () => {
  const server = await staticApp(); const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    let verified = false; let release; let attempt = 0;
    const writes = [];
    page.on('request', request => { if (request.method() === 'POST') writes.push(new URL(request.url()).pathname); });
    await page.route('**/api/agent/health', r => r.fulfill({ json: { status: 'ok', model: { configured: true, source: 'llm_fallback', name: 'shared-model', provider: 'test' } } }));
    await page.route('**/api/setup/status', r => r.fulfill({ json: { complete: verified, canCreateTask: true, canUseAgent: verified, steps: [{ id: 'planner', status: 'ready' }, { id: 'agent', status: verified ? 'ready' : 'required' }] } }));
    await page.route('**/api/settings/agent/probe-effective', async r => {
      attempt++;
      if (attempt === 1) await new Promise(resolve => { release = resolve; });
      if (attempt === 2) { verified = false; return r.fulfill({ status: 400, json: { detail: '服务商拒绝工具调用，请检查模型支持情况' } }); }
      verified = true;
      return r.fulfill({ json: { toolCalling: true, piVersion: 'test' } });
    });
    await page.goto(server.url + '/#view=settings');
    await page.locator('[data-model-role="agent"]').click();
    await page.waitForFunction(() => document.querySelector('#agentEffectiveModel').textContent.includes('shared-model'));
    assert.equal(attempt, 0, 'Loading settings never calls the model');
    assert.equal(await page.locator('#agentIndependentSettings').evaluate(n => n.open), false);
    const direct = page.locator('#testEffectiveAgent');
    assert.equal(await direct.isEnabled(), true);
    await direct.click();
    await page.waitForFunction(() => document.querySelector('#probeEffectiveAgent').disabled);
    await page.evaluate(() => { void window.ClipTalkAgentSettings.probeEffectiveAgent(); });
    assert.equal(attempt, 1, 'The two entry points share one in-flight request');
    release();
    await page.waitForFunction(() => document.querySelector('#agentEffectiveStatus').textContent === '工具调用测试已通过');
    assert.match(await page.locator('#agentSettingsState').innerText(), /复用模型.*已通过测试/);
    assert.equal(await direct.innerText(), '重新测试工具调用');
    assert.equal(await page.locator('#probeEffectiveAgent').innerText(), '重新测试工具调用');
    await page.locator('#probeEffectiveAgent').click();
    await page.waitForFunction(() => document.querySelector('#agentEffectiveStatus').textContent.includes('服务商拒绝'));
    assert.equal(await page.evaluate(() => window.ClipTalkSetupStatus.canUseAgent), false);
    assert.equal(await direct.isEnabled(), true);
    await direct.click();
    await page.waitForFunction(() => document.querySelector('#agentEffectiveStatus').textContent === '工具调用测试已通过');
    await page.locator('#agentIndependentSettings summary').click();
    await page.locator('#agentBaseUrl').fill('https://unsaved.example/v1');
    assert.equal(await direct.isDisabled(), true);
    assert.equal(await page.locator('#probeEffectiveAgent').isDisabled(), true);
    assert.match(await page.locator('#agentEffectiveHint').innerText(), /未保存/);
    await page.locator('#discardAgentSettings').click();
    assert.equal(await direct.isEnabled(), true);
    assert.deepEqual(writes, Array(3).fill('/api/settings/agent/probe-effective'));
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => window.ClipTalkTheme.apply(theme), theme);
      await page.waitForTimeout(550);
      const colors = await page.locator('.agent-effective-model p, #testEffectiveAgent, #setupReadinessTitle, #setupReadinessSummary, #setupReadinessSteps b, #setupReadinessSteps small').evaluateAll(nodes => nodes.map(node => {
        let parent = node, background;
        while (parent) { background = getComputedStyle(parent).backgroundColor; if (/^rgb\(/.test(background)) break; parent = parent.parentElement; }
        return { foreground: getComputedStyle(node).color, background };
      }));
      for (const color of colors) assert.ok(contrast(color.foreground, color.background) >= 4.5, JSON.stringify({ theme, color }));
    }
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  } finally { await browser.close(); await server.close(); }
});

test('late model discovery never overwrites a different connection configuration', async () => {
  const server = await staticApp(); const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(server.url + '/#view=settings');
    for (const role of ['vision', 'llm']) for (const status of [200, 400]) {
      let release;
      await page.route(`**/api/settings/${role}/discover`, async r => {
        await new Promise(resolve => { release = resolve; });
        await r.fulfill({ status, json: status === 200 ? { models: [{ id: 'obsolete-model' }], verifiedAt: 'old-test' } : { detail: 'obsolete failure' } });
      });
      await page.evaluate(role => {
        const settings = { activeProvider: 'test', providers: [{ id: 'test', keyConfigured: true, model: 'current-model' }] };
        if (role === 'vision') { visionSettingsState = settings; selectedVisionProvider = 'test'; }
        else { llmSettingsState = settings; selectedLlmProvider = 'test'; selectedLlmMode = 'independent'; }
        document.querySelector(`#${role}BaseUrl`).value = 'https://old.example/v1';
        document.querySelector(`#${role}ApiKey`).value = '';
        window.pendingDiscovery = role === 'vision' ? discoverAvailableVisionModels() : discoverAvailableLlmModels();
      }, role);
      while (!release) await new Promise(resolve => setTimeout(resolve, 10));
      await page.evaluate(role => {
        document.querySelector(`#${role}BaseUrl`).value = 'https://new.example/v1';
        if (role === 'vision') visionDiscoveredModels = [{ id: 'new-model' }];
        else llmDiscoveredModels = [{ id: 'new-model' }];
      }, role);
      release();
      await page.evaluate(() => window.pendingDiscovery);
      assert.deepEqual(await page.evaluate(role => role === 'vision' ? visionDiscoveredModels : llmDiscoveredModels, role), [{ id: 'new-model' }]);
      assert.match(await page.locator(`#${role}ConnectionStatus`).textContent(), /配置已变化/);
      await page.unroute(`**/api/settings/${role}/discover`);
    }
  } finally { await browser.close(); await server.close(); }
});

test('default TalkNet capability is explicit, retryable and readable in both themes', async () => {
  const server = await staticApp();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    let checks = 0;
    let release;
    await page.route('**/api/capabilities/local', async route => {
      checks++;
      if (checks === 1) {
        await new Promise(resolve => { release = resolve; });
        await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"unavailable"}' });
      } else {
        await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ talknet: { status: 'available', label: '可用', device: 'cpu', detail: '环境检查通过，当前使用 CPU，长视频可能较慢。' } }) });
      }
    });
    await page.goto(server.url);
    await page.locator('#settingsButton').click();
    await page.locator('[data-model-role="system"]').click();
    await page.locator('#checkLocalCapabilities').waitFor({ state: 'visible' });
    assert.equal(checks, 0, 'Opening settings must not run model probes or installs');
    await page.locator('#checkLocalCapabilities').click();
    await page.waitForFunction(() => document.querySelector('#checkLocalCapabilities').disabled);
    assert.match(await page.locator('#localCapabilityStatus').innerText(), /正在检查/);
    while (!release) await new Promise(resolve => setTimeout(resolve, 10));
    release();
    await page.waitForFunction(() => !document.querySelector('#checkLocalCapabilities').disabled);
    assert.match(await page.locator('#localCapabilityStatus').innerText(), /检查未完成/);
    await page.locator('#checkLocalCapabilities').click();
    await page.waitForFunction(() => document.querySelector('#localCapabilities').dataset.status === 'available');
    assert.match(await page.locator('#localCapabilityDetail').innerText(), /CPU.*较慢/);
    await page.locator('#localCapabilities summary').click();
    assert.match(await page.locator('#localCapabilities').innerText(), /python3 tools\/setup.py/);
    for (const theme of ['light', 'dark']) {
      await page.evaluate(value => window.ClipTalkTheme.apply(value), theme);
      await page.waitForTimeout(650);
      const colors = await page.locator('#localCapabilities p, #localCapabilities code, #checkLocalCapabilities').evaluateAll(nodes => nodes.map(node => {
        let parent = node, background;
        while (parent) { background = getComputedStyle(parent).backgroundColor; if (/^rgb\(/.test(background)) break; parent = parent.parentElement; }
        return { tag: node.tagName, id: node.id, text: node.textContent.slice(0, 60), foreground: getComputedStyle(node).color, background, backgroundOwner: parent?.className };
      }));
      for (const color of colors) assert.ok(contrast(color.foreground, color.background) >= 4.5, JSON.stringify({ theme, ...color }));
    }
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  } finally { await browser.close(); await server.close(); }
});

test('settings capabilities have a stable dedicated tab at wide and narrow widths', async () => {
  const server = await staticApp(); const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(server.url + '/#view=settings');
    await page.locator('[data-model-role="system"]').click();
    await page.locator('#localCapabilities').waitFor({ state: 'visible' });
    for (const width of [1920, 1440, 1280, 760, 390]) {
      await page.setViewportSize({ width, height: 948 });
      for (const theme of ['light', 'dark']) {
        await page.evaluate(theme => window.ClipTalkTheme.apply(theme), theme);
        await page.locator('[data-model-role="system"]').click();
        for (const expanded of [false, true]) {
          const layout = await page.evaluate((expanded) => {
            document.querySelector('#localCapabilities details').open = expanded;
            document.querySelector('.runtime-settings-summary').open = expanded;
            const bounds = selector => {
              const r = document.querySelector(selector).getBoundingClientRect();
              return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width };
            };
            return { view: bounds('[data-model-view="system"]'), local: bounds('#localCapabilities'), runtime: bounds('.runtime-settings-summary'), pageWidth: document.documentElement.scrollWidth, width: innerWidth };
          }, expanded);
          for (const card of [layout.local, layout.runtime]) {
            assert.ok(card.left >= layout.view.left, JSON.stringify({ width, theme, expanded, layout }));
            assert.ok(card.right <= layout.view.right, JSON.stringify({ width, theme, expanded, layout }));
          }
          assert.ok(layout.runtime.top >= layout.local.bottom, 'Expanded cards must not overlap');
          assert.ok(layout.pageWidth <= layout.width, 'Settings must not cause horizontal page overflow');
        }
      }
    }

    await page.setViewportSize({ width: 1440, height: 700 });
    await page.locator('[data-model-role="vision"]').click();
    const scrollMemory = await page.evaluate(async () => {
      const panel = document.querySelector('#settingsPanel');
      panel.scrollTop = 520;
      const expected = panel.scrollTop;
      setModelSettingsRole('system');
      await new Promise(requestAnimationFrame);
      panel.scrollTop = 80;
      setModelSettingsRole('vision');
      await new Promise(requestAnimationFrame);
      return { expected, restored: panel.scrollTop };
    });
    assert.ok(scrollMemory.expected > 0);
    assert.equal(scrollMemory.restored, scrollMemory.expected);
  } finally { await browser.close(); await server.close(); }
});

test('global sidebar controls keep the same geometry across task, library and settings views', async () => {
  const server = await staticApp(); const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(server.url);
    const geometry = () => page.evaluate(() => {
      const bounds = (selector) => {
        const rect = document.querySelector(selector).getBoundingClientRect();
        return [rect.x, rect.y, rect.width, rect.height].map(value => Math.round(value));
      };
      return {
        rail: bounds('#appSidebar'),
        brand: bounds('.app-sidebar-brand button'),
        newTask: bounds('#sidebarNewTask'),
        tasks: bounds('#sidebarHistoryToggle'),
        outputs: bounds('.app-sidebar-outputs'),
        theme: bounds('#themeToggle'),
        settings: bounds('#settingsButton'),
      };
    });

    await page.locator('#sidebarNewTask').click();
    await page.waitForFunction(() => document.body.dataset.shellView === 'workspace');
    const task = await geometry();
    await page.locator('.app-sidebar-outputs').click();
    await page.waitForFunction(() => document.body.dataset.shellView === 'library');
    const library = await geometry();
    await page.locator('#settingsButton').click();
    await page.waitForFunction(() => document.body.dataset.shellView === 'settings');
    const settings = await geometry();

    const { rail: taskRail, ...taskControls } = task;
    const { rail: libraryRail, ...libraryControls } = library;
    const { rail: settingsRail, ...settingsControls } = settings;
    assert.deepEqual(libraryControls, taskControls);
    assert.deepEqual(settingsControls, taskControls);
    assert.deepEqual(taskControls.newTask, [18, 148, 48, 52]);
    assert.deepEqual(taskRail, [0, 0, 84, 900]);
    assert.deepEqual(libraryRail, [0, 0, 84, 900]);
    assert.deepEqual(settingsRail, [0, 0, 84, 900]);
  } finally { await browser.close(); await server.close(); }
});

test('settings toast clears the dirty save bar instead of covering it', async () => {
  const server = await staticApp(); const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(server.url + '/#view=settings');
    const overlap = await page.evaluate(() => {
      const bar = document.querySelector('#visionSettingsForm .settings-save-bar');
      bar.classList.remove('hidden');
      const toast = document.createElement('div');
      toast.className = 'toast';
      toast.textContent = '设置保存失败，请重试';
      document.querySelector('#toastRegion').append(toast);
      const a = bar.getBoundingClientRect();
      const b = toast.getBoundingClientRect();
      const width = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
      const height = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
      return { area: width * height, barTop: a.top, toastBottom: b.bottom };
    });
    assert.equal(overlap.area, 0);
    assert.ok(overlap.toastBottom < overlap.barTop);
  } finally { await browser.close(); await server.close(); }
});

test('cover review focuses the editor and disables every source-mismatched candidate', async () => {
  const variants = ['source_clean', 'source_editorial', 'source_cinematic'].map((direction, index) => ({
    variantId: `cover_${index}`, direction, previewUrl: '/missing-cover.jpg', contentHash: `sha256:${index}`,
    sourceTime: 543 + index, subjectVerification: { subject: '雷军', personDetected: true, status: 'identity_unverified' },
  }));
  const output = { filename: 'sample.mp4', title: '审核样片', duration: 96, width: 540, height: 960, previewOnly: true,
    videoUrl: '/missing.mp4', previewUrl: '/missing.mp4', segments: [{ start: 0, end: 12 }] };
  const job = { id: 'cover_focus', filename: '小米产品.mp4', status: 'completed', taskMode: 'content_extract',
    videoInfo: { duration: 600, width: 1024, height: 576 }, messages: [], candidates: [], eventGroups: [],
    presentation: { schemaVersion: 4, key: 'preview_review', group: 'action_required', label: '封面待确认', journeyStage: 3 },
    coverDraft: { jobId: 'cover_focus', status: 'review_ready', subject: '雷军', requestedSourceTime: 54,
      selectedVariantId: 'cover_0', variants },
    coverTimelineDraft: { activeVariantId: 'cover_0', variants: Object.fromEntries(variants.map(item => [item.variantId, { duration: 1 }])) },
    outputVersions: [{ id: 'preview', number: 1, previewOnly: true, outputs: [output] }], outputs: [],
  };
  const server = await staticApp(job); const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(`${server.url}/#job=${job.id}`);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === 'cover_focus');
    assert.equal(await page.evaluate(() => window.ClipTalkOpenCoverTimeline()), true);
    await page.waitForFunction(() => document.body.dataset.ctCoverEditorOpen === 'true');
    const state = await page.evaluate(() => ({
      stageDisplay: getComputedStyle(document.querySelector('#reviewStage')).display,
      railDisplay: getComputedStyle(document.querySelector('#reviewRail')).display,
      confirmPresent: Boolean(document.querySelector('[data-cover-timeline-confirm]')),
      emptyTitle: document.querySelector('.timeline-cover-empty h3')?.textContent,
      retryLabel: document.querySelector('[data-cover-timeline-retry]')?.textContent,
      revisePresent: Boolean(document.querySelector('[data-cover-timeline-revise]')),
      requirement: document.querySelector('.timeline-cover-empty p')?.textContent,
      editorEmpty: !document.querySelector('#timelineCoverEditor')?.childElementCount,
      dockDisplay: getComputedStyle(document.querySelector('#reviewActionDock')).display,
      emptyWidth: document.querySelector('.timeline-cover-empty')?.getBoundingClientRect().width,
      overflow: document.documentElement.scrollWidth > innerWidth,
    }));
    assert.equal(state.stageDisplay, 'none', JSON.stringify(state));
    assert.equal(state.railDisplay, 'none');
    assert.equal(state.confirmPresent, false);
    assert.equal(state.emptyTitle, '没有找到符合要求的封面');
    assert.match(state.retryLabel, /00:54.*取帧/);
    assert.equal(state.revisePresent, true);
    assert.match(state.requirement, /来源 00:54.*雷军/);
    assert.equal(state.editorEmpty, true);
    assert.equal(state.dockDisplay, 'none');
    assert.ok(state.emptyWidth >= 500, JSON.stringify(state));
    assert.equal(state.overflow, false);
    const geometry = await page.locator('#timelineCoverTrack').evaluate(n => ({ height: n.clientHeight, content: n.scrollHeight }));
    assert.ok(geometry.height >= geometry.content - 2, JSON.stringify(geometry));
    await page.locator('[data-cover-timeline-retry]').click({ trial: true });
    await page.evaluate(() => {
      window.__coverGoalRevised = false;
      window.__coverCandidatesRetried = false;
      window.ClipTalkEditCoverRequirement = () => { window.__coverGoalRevised = true; return true; };
      window.ClipTalkRetryCoverCandidates = async () => { window.__coverCandidatesRetried = true; };
    });
    await page.click('[data-cover-timeline-retry]');
    assert.equal(await page.evaluate(() => window.__coverCandidatesRetried), true);
    await page.click('[data-cover-timeline-revise]');
    assert.equal(await page.evaluate(() => window.__coverGoalRevised), true);
    job.coverDraft.variants[0].sourceTime = 54;
    await page.reload();
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === 'cover_focus');
    assert.equal(await page.evaluate(() => window.ClipTalkOpenCoverTimeline()), true);
    await page.waitForSelector('[data-cover-timeline-open-preview]');
    let popupOpened = false;
    page.once('popup', () => { popupOpened = true; });
    await page.click('[data-cover-timeline-open-preview]');
    await page.waitForSelector('#coverImagePreview:not(.hidden)');
    assert.match(await page.getAttribute('#coverImagePreviewImage', 'src'), /missing-cover\.jpg/);
    assert.equal(popupOpened, false);
    await page.keyboard.press('Escape');
    assert.equal(await page.getAttribute('#coverImagePreview', 'aria-hidden'), 'true');
  } finally { await browser.close(); await server.close(); }
});

test('opening a legacy landscape sample shows real tracks and a reachable toggle without internal navigation', async () => {
  const job = { id: 'legacy_sample_tracks', filename: '素材.mp4', status: 'awaiting_agent_plan', taskMode: 'highlight',
    videoInfo: { duration: 120, width: 1920, height: 1080, has_audio: true }, messages: [], candidates: [], eventGroups: [],
    agent: { workspaceId: 'ws_tracks', planId: 'plan_tracks', status: 'preview_ready' },
    editSessions: [{ id: 'session_tracks', jobId: 'legacy_sample_tracks', revision: 1, previewRevision: 1,
      clips: [{ id: 'a', sourceStart: 10, sourceEnd: 16, title: '第一段' }, { id: 'b', sourceStart: 40, sourceEnd: 46, title: '第二段' }] }],
  };
  const preview = { kind: 'review_preview', sessionId: 'session_tracks', revision: 1, duration: 12,
    title: '审核样片', previewUrl: '/missing.mp4', previewOnly: true };
  const server = await staticApp(job); const browser = await chromium.launch();
  try {
    for (const [width, height] of [[1920, 950], [1366, 768], [390, 844]]) {
      const page = await browser.newPage({ viewport: { width, height } });
      await page.route('**/api/agent/workspaces/ws_tracks', r => r.fulfill({ json: {
        workspace: { id: 'ws_tracks', jobId: job.id, activePlanId: 'plan_tracks' },
        plans: [{ id: 'plan_tracks', workspaceId: 'ws_tracks', status: 'preview_ready', steps: [{ id: 'render',
          tool: 'render_review_preview', status: 'completed', result: { artifact: { kind: 'review_preview_batch', previews: [preview] } } }] }],
      } }));
      await page.route('**/waveform', r => r.fulfill({ json: { schemaVersion: 3, duration: 120, hasAudio: true,
        rms: Array(64).fill(.4), minimums: Array(64).fill(-.5), maximums: Array(64).fill(.5) } }));
      await page.route('**/timeline-assets', r => r.fulfill({ json: { ready: true, spriteUrl: '/fixture-sprite.svg',
        sprite: { spriteWidth: 160, spriteHeight: 90, tileWidth: 80, tileHeight: 45,
          items: [10, 16, 40, 46].map((time, index) => ({ index, time, column: index % 2, row: Math.floor(index / 2) })) } } }));
      await page.route('**/fixture-sprite.svg', r => r.fulfill({ contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="#637f6b"/></svg>' }));
      await page.goto(`${server.url}/#job=${job.id}`);
      if (width < 900) await page.locator('#ctCompactWorkspaceNav [data-ct-compact-view="preview"]').click();
      await page.waitForFunction(() => document.querySelectorAll('#timelineThumbnails [data-source-frame-time]').length > 0 && waveformData?.rms?.length);
      assert.equal(await page.locator('#timelinePanel').isVisible(), true);
      assert.equal(await page.locator('#portraitPrecisionToggle').isVisible(), true);
      assert.equal(await page.locator('#portraitPrecisionToggle').evaluate(node => node.parentElement?.classList.contains('timeline-review-controls')), true);
      const playerFit = await page.evaluate(() => {
        const stage = document.querySelector('#reviewStage').getBoundingClientRect();
        const frame = document.querySelector('#mediaFrame').getBoundingClientRect();
        const controls = document.querySelector('.player-controls').getBoundingClientRect();
        const items = [...document.querySelectorAll('.player-controls > *')]
          .filter(node => getComputedStyle(node).display !== 'none')
          .map(node => node.getBoundingClientRect());
        return {
          frameRatio: frame.width / stage.width,
          stageBackground: getComputedStyle(document.querySelector('#reviewStage')).backgroundColor,
          controlsContained: items.every(rect => rect.left >= controls.left - 1 && rect.right <= controls.right + 1),
        };
      });
      assert.ok(playerFit.frameRatio >= .68, `Video should use the available stage: ${playerFit.frameRatio}`);
      assert.equal(playerFit.stageBackground, 'rgb(28, 33, 31)');
      assert.equal(playerFit.controlsContained, true);
      assert.equal(await page.locator('#reviewTimelineResizer').isVisible(), width >= 901);
      assert.equal(await page.locator('#timelineThumbnails .output-gap').count(), 0);
      assert.equal(await page.evaluate(() => currentOutput.segments.length), 2);
      assert.ok(Math.abs(await page.evaluate(() => compositionSourceTimeAtOutputTime(currentOutput, 7)) - 41) < .001);
      assert.equal(await page.locator('#videoViewSelect option:checked').innerText(), '审核样片 1');
      assert.equal(await page.locator('#timelineWaveMode').getAttribute('aria-pressed'), 'true');
      assert.equal(await page.locator('#timelineFrameMode').getAttribute('aria-pressed'), 'true');
      assert.equal(await page.locator('.timeline-shot-marker.active').count(), 0, 'Loading an output must not select every shot');
      const laneGeometry = await page.evaluate(() => ['.timeline-label', '.timeline-shot-marker'].map(selector => {
        const rows = [...document.querySelectorAll(selector)].map(node => node.getBoundingClientRect()).sort((a, b) => a.left - b.left);
        return {
          fits: rows.every((rect, index) => !index || rect.left >= rows[index - 1].right - 1),
          rows: rows.map(({ left, right, width }) => ({ left, right, width })),
        };
      }));
      assert.deepEqual(laneGeometry.map((lane) => lane.fits), [true, true], `Sequential event and shot cards must not overlap at ${width}px: ${JSON.stringify(laneGeometry)}`);
      assert.equal(await page.locator('#timelinePlayheadLabel').innerText(), '00:10.0');
      assert.doesNotMatch(await page.locator('#timelinePanel > footer').innerText(), /成片事件|播放顺序|音频波形/);
      const visibleRelations = await page.locator('.timeline-event-curve').evaluateAll(nodes => nodes.filter(node => Number(getComputedStyle(node).opacity) > 0).length);
      assert.ok(visibleRelations <= 1, `Only the playing relationship may be visible by default: ${visibleRelations}`);
      if (await page.locator('.timeline-label').count() > 1) {
        const relationKey = await page.locator('.timeline-label').nth(1).getAttribute('data-timeline-relation');
        await page.locator('.timeline-label').nth(1).hover();
        assert.ok(await page.locator(`.timeline-event-curve[data-timeline-relation="${relationKey}"]`).evaluateAll(nodes => nodes.every(node => Number(getComputedStyle(node).opacity) > 0)));
      }
      await page.locator('#timelineWaveMode').click();
      assert.equal(await page.locator('#waveformCanvas').isVisible(), false);
      assert.equal(await page.locator('#timelineThumbnails').isVisible(), true);
      await page.locator('#timelineFrameMode').click();
      assert.equal(await page.locator('#timelineThumbnails').isVisible(), false);
      assert.equal(await page.locator('#timelineSceneCuts').isVisible(), true, 'Cut markers remain an independent layer');
      await page.locator('#timelineWaveMode').click();
      await page.locator('#timelineFrameMode').click();
      await page.locator('#timelineZoomIn').click();
      assert.notEqual(await page.locator('#timelineZoomLevel').innerText(), '100%');
      const viewStart = await page.evaluate(() => timelineViewRange().start);
      await page.locator('#timelineOverview').press('ArrowRight');
      assert.ok(await page.evaluate(() => timelineViewRange().start) > viewStart);
      await page.locator('#timelineFit').click();
      assert.equal(await page.locator('#timelineZoomLevel').innerText(), '100%');
      for (const theme of ['light', 'dark']) {
        await page.evaluate(theme => ClipTalkTheme.apply(theme), theme);
        await page.waitForFunction(() => document.querySelector('#timelineViewport').getBoundingClientRect().height >= 195);
        assert.equal(await page.locator('#waveformCanvas').isVisible(), true);
        const paintedRows = await page.locator('#waveformCanvas').evaluate(canvas => {
          const { data } = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
          const rows = new Set();
          for (let i = 0; i < data.length; i += 4) if (data[i + 3] > 128) rows.add(Math.floor(i / 4 / canvas.width));
          return rows.size;
        });
        assert.ok(paintedRows > 8, `Actual waveform, not just a flat guide: ${paintedRows}`);
      }
      if (width >= 901) {
        const divider = await page.locator('#reviewTimelineResizer').boundingBox();
        const before = await page.locator('#timelinePanel').evaluate(node => node.getBoundingClientRect().height);
        await page.mouse.move(divider.x + divider.width / 2, divider.y + divider.height / 2);
        await page.mouse.down();
        await page.mouse.move(divider.x + divider.width / 2, divider.y - 36, { steps: 4 });
        await page.mouse.up();
        const after = await page.locator('#timelinePanel').evaluate(node => node.getBoundingClientRect().height);
        assert.ok(after >= before + 28, `Dragging upward should enlarge the timeline: ${before} -> ${after}`);
        await page.locator('#reviewTimelineResizer').dblclick();
        assert.equal(await page.locator('#reviewView').evaluate(node => node.style.getPropertyValue('--review-timeline-height')), '');
      }
      await page.locator('#portraitPrecisionToggle').click();
      assert.equal(await page.locator('#timelinePanel').isVisible(), false);
      await page.evaluate(async () => { renderJob(currentJob); await ClipTalkAgentWorkspace.resumeForJob(currentJob); });
      assert.equal(await page.locator('#timelinePanel').isVisible(), false, 'Polling preserves a deliberate collapse');
      await page.locator('#portraitPrecisionToggle').click();
      assert.equal(await page.locator('#timelinePanel').isVisible(), true);
      // An older preview must not use a newer, edited session's source ranges.
      await page.evaluate(async preview => {
        currentJob.editSessions[0].revision = 2;
        currentJob.agentPreviewOutputs = [];
        await ClipTalkOpenAgentPreview({ ...preview, filename: 'stale.mp4', autoplay: false, silent: true });
      }, preview);
      assert.equal(await page.evaluate(() => currentOutput.segments.length), 0);
      await page.close();
    }
  } finally { await browser.close(); await server.close(); }
});

test('pending covers never hide the ordinary timeline and closing cover review restores media tracks', async () => {
  const job = { id: 'cover_timeline_modes', filename: '素材.mp4', status: 'completed', taskMode: 'content_extract',
    videoInfo: { duration: 120, width: 1920, height: 1080, has_audio: true }, messages: [], candidates: [], eventGroups: [],
    coverDraft: { jobId: 'cover_timeline_modes', status: 'review_ready', selectedVariantId: 'cover_one',
      variants: [{ variantId: 'cover_one', direction: 'source_clean', sourceTime: 10, previewUrl: '/fixture-sprite.svg', contentHash: 'sha256:test' }] },
    outputVersions: [{ id: 'sample', number: 1, previewOnly: true, outputs: [{ filename: 'sample.mp4', previewOnly: true,
      title: '样片', duration: 12, width: 540, height: 960, previewUrl: '/missing.mp4', videoUrl: '/missing.mp4',
      segments: [{ start: 0, end: 12 }] }] }],
  };
  const server = await staticApp(job); const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route('**/waveform', r => r.fulfill({ json: { schemaVersion: 3, duration: 120, hasAudio: true,
      rms: Array(64).fill(.4), minimums: Array(64).fill(-.5), maximums: Array(64).fill(.5) } }));
    await page.route('**/timeline-assets', r => r.fulfill({ json: { ready: true, spriteUrl: '/fixture-sprite.svg',
      sprite: { spriteWidth: 160, spriteHeight: 90, tileWidth: 80, tileHeight: 45,
        items: [0, 4, 8, 12].map((time, index) => ({ index, time, column: index % 2, row: Math.floor(index / 2) })) } } }));
    await page.route('**/fixture-sprite.svg', r => r.fulfill({ contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="#637f6b"/></svg>' }));
    await page.goto(`${server.url}/#job=${job.id}`);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === 'cover_timeline_modes' && waveformData?.rms?.length && timelineAssets?.sprite?.items?.length);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      if (width === 390) await page.locator('#ctCompactWorkspaceNav [data-ct-compact-view="preview"]').click();
      for (const theme of ['light', 'dark']) {
        await page.evaluate(t => window.ClipTalkTheme.apply(t), theme);
        for (const status of ['review_ready', 'auto_selected', 'candidates_ready', 'approved']) {
          await page.evaluate(status => { currentJob.coverDraft.status = status; setReviewLowerPanelMode('timeline'); updateTimeline(); }, status);
          assert.equal(await page.locator('body').getAttribute('data-ct-cover-editor-open'), 'false', `${width}/${theme}/${status}: ordinary timeline must not enter cover mode`);
          assert.equal(await page.locator('#timelineCoverTrack').isVisible(), false);
          await page.waitForFunction(() => document.querySelector('#timelineViewport').getBoundingClientRect().height >= 220);
          assert.equal(await page.locator('#waveformCanvas').isVisible(), true);
          assert.ok(await page.locator('#timelineThumbnails [data-timeline-frame-time]').count() > 0);
          const tracks = await page.evaluate(() => {
            const viewport = document.querySelector('#timelineViewport').getBoundingClientRect();
            const thumbnails = document.querySelector('#timelineThumbnails').getBoundingClientRect();
            const audio = document.querySelector('#timelineTrackLabels [data-track-kind="audio"]').getBoundingClientRect();
            return { top: viewport.top, bottom: viewport.bottom, thumbnailTop: thumbnails.top,
              thumbnailBottom: thumbnails.bottom, audioBottom: audio.bottom };
          });
          assert.ok(tracks.thumbnailTop >= tracks.top && tracks.thumbnailBottom <= tracks.bottom + 1, JSON.stringify(tracks));
          assert.ok(tracks.audioBottom <= tracks.bottom + 1, JSON.stringify(tracks));
          await page.evaluate(() => { ClipTalkOpenCoverTimeline(); updateTimeline(); });
          assert.equal(await page.locator('body').getAttribute('data-ct-cover-editor-open'), 'true');
          assert.equal(await page.locator('#timelineViewport').isVisible(), false);
          await page.locator('#coverReviewBack').click();
          assert.equal(await page.evaluate(() => reviewLowerPanelMode), 'timeline');
          assert.equal(await page.locator('body').getAttribute('data-ct-cover-editor-open'), 'false');
          assert.equal(await page.locator('#timelineViewport').isVisible(), true);
          assert.equal(await page.locator('#waveformCanvas').isVisible(), true);
          await page.evaluate(() => { ClipTalkOpenCoverTimeline(); setReviewLowerPanelMode('timeline'); });
          assert.equal(await page.locator('body').getAttribute('data-ct-cover-editor-open'), 'false', 'Explicit timeline navigation must exit cover mode');
        }
      }
    }
    await page.evaluate(() => { setReviewLowerPanelMode('collapsed'); ClipTalkOpenCoverTimeline(); });
    await page.locator('#coverReviewBack').click();
    assert.equal(await page.evaluate(() => reviewLowerPanelMode), 'collapsed');
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.evaluate(() => { showSource({ autoplay: false }); setReviewLowerPanelMode('timeline'); });
    await page.waitForFunction(() => document.querySelector('#timelineViewport').getBoundingClientRect().height >= 195);
    const sourceTracks = await page.evaluate(() => {
      const panel = document.querySelector('#timelinePanel').getBoundingClientRect();
      const audio = document.querySelector('#timelineTrackLabels [data-track-kind="audio"]').getBoundingClientRect();
      return { panelBottom: panel.bottom, audioBottom: audio.bottom };
    });
    assert.ok(sourceTracks.audioBottom <= sourceTracks.panelBottom, JSON.stringify(sourceTracks));
  } finally { await browser.close(); await server.close(); }
});

test('unified library displays all finals, keeps copies explicitly and confirms the last copy', async () => {
  const server = await staticApp(); const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const rows = [{ jobId: 'one', filename: 'final.mp4', displayTitle: '访谈精华', versionNumber: 1, duration: 12, videoUrl: '/missing.mp4', downloadUrl: '/missing.mp4?download=1', sourceTaskAvailable: true, sourceFileAvailable: true, canKeep: true, kept: false },
      { jobId: 'orphan', filename: 'saved.mp4', displayTitle: '独立保留成片', versionNumber: 2, duration: 8, videoUrl: '/missing.mp4', downloadUrl: '/missing.mp4?download=1', sourceTaskAvailable: false, sourceFileAvailable: false, kept: true }];
    const mutations = [];
    await page.route('**/api/library/outputs', r => r.fulfill({ json: { outputs: rows } }));
    await page.route('**/api/jobs/one/outputs/final.mp4/keep', async r => {
      mutations.push({ method: r.request().method(), body: r.request().postDataJSON() }); rows[0].kept = true;
      await r.fulfill({ json: { ok: true } });
    });
    await page.goto(server.url + '/#view=library');
    await page.locator('.app-library-item').first().waitFor();
    assert.equal(await page.locator('.app-library-item').count(), 2);
    assert.equal(await page.locator('#sidebarOutputCount').innerText(), '2');
    await page.locator('.app-library-item').first().locator('summary').click();
    await page.getByRole('button', { name: '长期保留', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.app-library-item').textContent.includes('已长期保留'));
    assert.deepEqual(mutations, [{ method: 'POST', body: { kept: true } }]);
    await page.locator('.app-library-item').last().locator('summary').click();
    await page.getByRole('button', { name: '删除独立副本', exact: true }).click();
    await page.locator('#actionConfirm').waitFor({ state: 'visible' });
    assert.match(await page.locator('#actionConfirm').innerText(), /最后可用副本/);
    assert.match(await page.locator('#actionConfirm').innerText(), /无法撤销/);
    await page.locator('#actionConfirmCancel').click();
    assert.equal(mutations.length, 1);
  } finally { await browser.close(); await server.close(); }
});

test('long output libraries scroll inside the viewport and keep service status out of the rail', async () => {
  const server = await staticApp(); const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 620 } });
    const outputs = Array.from({ length: 10 }, (_, index) => ({
      jobId: `library-${index}`,
      filename: `final-${index}.mp4`,
      displayTitle: `成片 ${index + 1}`,
      versionNumber: index + 1,
      duration: 12 + index,
      videoUrl: '/missing.mp4',
      downloadUrl: '/missing.mp4?download=1',
      sourceTaskAvailable: true,
      sourceFileAvailable: true,
      canKeep: true,
      kept: false,
    }));
    await page.route('**/api/library/outputs', route => route.fulfill({ json: { outputs } }));
    await page.goto(server.url + '/#view=library');
    await page.locator('.app-library-item').last().waitFor();

    const before = await page.locator('#libraryView').evaluate(node => ({
      top: node.scrollTop,
      clientHeight: node.clientHeight,
      scrollHeight: node.scrollHeight,
      overflowY: getComputedStyle(node).overflowY,
      viewportHeight: innerHeight,
    }));
    assert.equal(before.clientHeight, before.viewportHeight);
    assert.ok(before.scrollHeight > before.clientHeight);
    assert.equal(before.overflowY, 'auto');

    await page.locator('#libraryView').hover({ position: { x: 500, y: 400 } });
    await page.mouse.wheel(0, 700);
    await page.waitForFunction(() => document.querySelector('#libraryView').scrollTop > 0);
    assert.equal(await page.locator('#engineState').isVisible(), false);
    assert.deepEqual(await page.locator('.app-sidebar-primary > .app-sidebar-action').evaluateAll(nodes => nodes
      .filter(node => getComputedStyle(node).display !== 'none')
      .map(node => node.querySelector('span')?.textContent || '')), ['新建', '任务', '成片']);

    await page.setViewportSize({ width: 390, height: 700 });
    await page.locator('#libraryView').evaluate(node => { node.scrollTop = 0; });
    await page.waitForFunction(() => Math.abs(document.querySelector('#libraryView').getBoundingClientRect().left) < 1);
    const mobile = await page.evaluate(() => {
      const pageBounds = document.querySelector('#libraryView').getBoundingClientRect();
      const cardBounds = document.querySelector('.app-library-item').getBoundingClientRect();
      const mediaBounds = document.querySelector('.app-library-media').getBoundingClientRect();
      return {
        pageLeft: pageBounds.left,
        pageRight: pageBounds.right,
        pageHeight: pageBounds.height,
        cardLeft: cardBounds.left,
        cardRight: cardBounds.right,
        mediaLeft: mediaBounds.left,
        mediaRight: mediaBounds.right,
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
      };
    });
    assert.ok(Math.abs(mobile.pageLeft) < 1);
    assert.ok(Math.abs(mobile.pageRight - mobile.viewportWidth) < 1);
    assert.equal(mobile.pageHeight, mobile.viewportHeight);
    assert.ok(mobile.mediaLeft >= mobile.cardLeft && mobile.mediaRight <= mobile.cardRight);
    assert.ok(mobile.documentWidth <= mobile.viewportWidth);
  } finally { await browser.close(); await server.close(); }
});

test('new-task intro and upload target share one balanced visual group', async () => {
  const server = await staticApp(); const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1912, height: 948 } });
    await page.goto(server.url);
    await page.locator('#sidebarNewTask').click();
    await page.locator('#uploadView.new-task-upload').waitFor({ state: 'visible' });

    for (const theme of ['light', 'dark']) {
      await page.evaluate(value => window.ClipTalkTheme.apply(value), theme);
      await page.waitForTimeout(220);
      const layout = await page.evaluate(() => {
        const bounds = selector => {
          const node = document.querySelector(selector);
          const rect = node.getBoundingClientRect();
          return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height };
        };
        const canvas = bounds('#uploadView');
        const intro = bounds('#uploadView > .intro');
        const card = bounds('#uploadForm');
        const title = document.querySelector('#uploadView > .intro h1');
        const instruction = document.querySelector('#dropZone strong');
        const rgb = selector => (getComputedStyle(document.querySelector(selector)).backgroundColor.match(/[\d.]+/g) || [])
          .slice(0, 3).map(Number);
        const titleColor = getComputedStyle(title).color;
        return {
          canvas,
          intro,
          card,
          palette: {
            topbar: rgb('#ctV4Topbar'),
            workspace: rgb('#workspace'),
            assistant: rgb('#assistantPanel'),
            review: rgb('.review-panel'),
            dropZone: rgb('#dropZone'),
            titleColor,
          },
          titleSize: parseFloat(getComputedStyle(title).fontSize),
          instructionSize: parseFloat(getComputedStyle(instruction).fontSize),
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: innerWidth,
        };
      });
      const groupCenter = (layout.intro.left + layout.card.right) / 2;
      const canvasCenter = (layout.canvas.left + layout.canvas.right) / 2;
      const introCenterY = (layout.intro.top + layout.intro.bottom) / 2;
      const cardCenterY = (layout.card.top + layout.card.bottom) / 2;
      assert.ok(Math.abs(groupCenter - canvasCenter) < 1, JSON.stringify({ theme, layout }));
      assert.ok(Math.abs(introCenterY - cardCenterY) < 1, JSON.stringify({ theme, layout }));
      assert.ok(layout.intro.width / layout.card.width >= 1.02);
      assert.ok(layout.intro.width / layout.card.width <= 1.18);
      assert.ok(layout.card.height / layout.intro.height >= 1.05);
      assert.ok(layout.card.height / layout.intro.height <= 1.48);
      assert.ok(layout.titleSize >= 32);
      assert.ok(layout.titleSize <= 37);
      assert.ok(layout.instructionSize >= 14);
      assert.ok(layout.documentWidth <= layout.viewportWidth);
      if (theme === 'dark') {
        assert.deepEqual(layout.palette.topbar, [17, 25, 23]);
        assert.deepEqual(layout.palette.workspace, [17, 25, 23]);
        assert.deepEqual(layout.palette.assistant, [25, 37, 35]);
        assert.deepEqual(layout.palette.review, [17, 25, 23]);
        assert.deepEqual(layout.palette.dropZone, [22, 33, 31]);
        assert.match(layout.palette.titleColor, /rgb\(219, 232, 223\)/);
      }
    }
  } finally { await browser.close(); await server.close(); }
});

test('review entry selects the sample, honors explicit versions and preserves manual media on refresh', async () => {
  const output = (filename, previewOnly = false) => ({ filename, previewOnly, title: filename, duration: 12, width: 540, height: 960, videoUrl: '/missing.mp4', previewUrl: '/missing.mp4', downloadUrl: '/missing.mp4', segments: [{ start: 0, end: 12 }] });
  const job = { id: 'media_binding', filename: '素材.mp4', taskMode: 'content_extract', status: 'awaiting_content_confirmation', videoInfo: { duration: 30, width: 1920, height: 1080 }, messages: [], candidates: [], eventGroups: [],
    presentation: { schemaVersion: 4, key: 'preview_review', group: 'action_required', label: '审核样片待确认', journeyStage: 3 },
    outputVersions: [{ id: 'v1', number: 1, outputs: [output('final.mp4')] }, { id: 'sample', number: 2, previewOnly: true, outputs: [output('sample.mp4', true)] }] };
  const server = await staticApp(job); const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(server.url + '/#job=' + job.id);
    await page.waitForFunction(() => window.ClipTalkCurrentOutputSnapshot?.().output?.filename === 'sample.mp4');
    assert.equal(await page.locator('#mainVideo').evaluate(v => v.paused), true);
    await page.evaluate(() => window.showSource({ autoplay: false }));
    await page.evaluate(job => window.renderJob({ ...job, contentUiRevision: 'changed' }), job);
    assert.equal(await page.evaluate(() => window.ClipTalkCurrentOutputSnapshot().mediaKind), 'source');
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => window.ClipTalkTheme.apply(theme), theme); await page.waitForTimeout(550);
      const badge = await page.locator('#viewerBadge').evaluate(n => getComputedStyle(n).color);
      assert.equal(badge, 'rgb(245, 247, 244)', 'On-media labels must not inherit light-theme body text');
    }
    await page.goto(server.url + '/#job=' + job.id + '&output=final.mp4');
    await page.waitForFunction(() => window.ClipTalkCurrentOutputSnapshot?.().output?.filename === 'final.mp4');
  } finally { await browser.close(); await server.close(); }
});

test('unknown readiness blocks new AI actions and distinguishes old backend from network failure', async () => {
  const server = await staticApp(); const browser = await chromium.launch();
  try {
    const page = await browser.newPage(); let checks = 0;
    await page.route('**/api/setup/status', r => { checks++; return r.fulfill({ status: 404, json: { detail: 'Not Found' } }); });
    await page.goto(server.url);
    await page.locator('#settingsButton').click();
    await page.waitForFunction(() => document.querySelector('#setupReadinessTitle').textContent === '服务需更新');
    assert.equal(await page.evaluate(() => window.requireSetupCapability('agent')), false);
    assert.ok(checks >= 2);
    await page.unroute('**/api/setup/status');
    await page.route('**/api/setup/status', r => r.abort());
    await page.locator('#refreshSetupReadiness').click();
    await page.waitForFunction(() => document.querySelector('#setupReadinessTitle').textContent === '能力检查失败');
    assert.equal(await page.evaluate(() => window.ClipTalkSetupStatus), null);
  } finally { await browser.close(); await server.close(); }
});

test('subtitle review preserves edits, binds source time, and gates confirmation throughout saves', async () => {
  const job = { id: 'subtitle_journey', filename: 'source.mp4', status: 'completed', previewUrl: '/source.mp4',
    videoInfo: { duration: 120, width: 1920, height: 1080, has_audio: true }, messages: [], candidates: [], eventGroups: [] };
  const draft = { id: 'sub_fixture', revision: 1, status: 'draft', sourceSubtitleAcknowledged: false,
    globalStyle: { fontSizeRatio: .04, horizontal: 'center', vertical: 'bottom' },
    cues: [{ id: 'a', outputIndex: 0, start: 0, end: 4, sourceStart: 54, sourceEnd: 62, text: '第一句，用于校对。' },
      { id: 'b', outputIndex: 1, start: 0, end: 3, sourceStart: 90, sourceEnd: 93, text: '第二条成片字幕' }] };
  const server = await staticApp(job); const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    let saves = 0, failSave = false;
    await page.route('**/subtitle-drafts', r => r.fulfill({ json: { draft } }));
    await page.route('**/subtitle-drafts/sub_fixture', r => {
      saves++;
      if (failSave) return r.fulfill({ status: 500, json: { detail: '测试保存失败' } });
      const body = r.request().postDataJSON();
      return r.fulfill({ json: { draft: { ...draft, ...body, revision: saves + 1, status: body.confirmed ? 'confirmed' : 'draft' } } });
    });
    await page.goto(server.url + '/#job=' + job.id);
    await page.waitForFunction(() => window.ClipTalkCurrentJobId?.() === 'subtitle_journey');
    await page.evaluate(() => { window.reviewResult = 'pending'; reviewSubtitlesBeforeRender([{ segments: [{ start: 54, end: 62, playbackRate: 2 }] }], 'clean', { purpose: 'edit' }).then(r => { window.reviewResult = r; }); });
    await page.waitForSelector('#subtitleReview:not(.hidden)');
    assert.equal(await page.locator('#subtitleConfirmButton').isDisabled(), true);
    assert.equal(await page.locator('#subtitleConfirmButton').textContent(), '确认并返回编辑');
    assert.match(await page.locator('#subtitleReviewVideo').getAttribute('src'), /source\.mp4/);
    assert.equal(await page.locator('#subtitleReviewVideo').evaluate(v => v.muted), false);
    assert.equal(await page.locator('#subtitleReviewVideo').evaluate(v => v.controls), true);
    assert.equal(await page.locator('[data-subtitle-cue]').count(), 1);
    await page.locator('[data-cue-split]').click();
    assert.deepEqual(await page.evaluate(() => subtitleReviewDraft.cues.slice(0, 2).map(c => [c.start, c.end, c.sourceStart, c.sourceEnd])), [[0, 2, 54, 58], [2, 4, 58, 62]]);
    await page.locator('#subtitleUndoButton').click();
    assert.equal(await page.locator('[data-subtitle-cue]').count(), 1);
    await page.locator('[data-cue-text]').fill('保留这次修改');
    await page.locator('#subtitleOutputSelect').selectOption('1');
    assert.equal(await page.locator('[data-cue-text]').inputValue(), '第二条成片字幕');
    await page.locator('#subtitleOutputSelect').selectOption('0');
    assert.equal(await page.locator('[data-cue-text]').inputValue(), '保留这次修改');
    await page.locator('#subtitleSaveButton').click();
    await page.waitForFunction(() => document.querySelector('#subtitleSaveState').textContent.includes('草稿已保存'));
    assert.equal(await page.locator('#subtitleConfirmButton').isDisabled(), true);
    await page.locator('#subtitleSourceAck').check();
    assert.equal(await page.locator('#subtitleConfirmButton').isDisabled(), false);
    await page.locator('[data-cue-text]').fill('尚未保存的修改');
    await page.keyboard.press('Escape');
    await page.waitForSelector('#subtitleExitChoices:not(.hidden)');
    assert.equal(await page.evaluate(() => window.reviewResult), 'pending');
    failSave = true;
    await page.locator('#subtitleSaveExit').click();
    await page.waitForFunction(() => document.querySelector('#subtitleReviewError').textContent.includes('测试保存失败'));
    assert.equal(await page.locator('[data-cue-text]').inputValue(), '尚未保存的修改');
    await page.locator('#subtitleKeepEditing').click();
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const theme of ['light', 'dark']) {
        await page.evaluate(t => window.ClipTalkTheme.apply(t), theme);
        const bounds = await page.locator('.subtitle-review-panel').evaluate(n => ({ left: n.getBoundingClientRect().left, right: n.getBoundingClientRect().right, viewport: innerWidth }));
        assert.ok(bounds.left >= -1 && bounds.right <= bounds.viewport + 1, JSON.stringify(bounds));
        await page.locator('#subtitleConfirmButton').click({ trial: true });
      }
    }
    await page.keyboard.press('Escape');
    await page.locator('#subtitleDiscardExit').click();
    await page.waitForFunction(() => window.reviewResult === null);
  } finally { await browser.close(); await server.close(); }
});

function contrast(foreground, background) {
  const luminance = color => {
    const rgb = color.match(/[\d.]+/g).slice(0, 3).map(Number).map(c => c / 255).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  };
  const a = luminance(foreground), b = luminance(background);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}

test('full application keeps output selection, readable themes and usable mobile navigation', async () => {
  const output = (filename, width, height) => ({ filename, title: filename, duration: 10, width, height,
    videoUrl: '/missing-test-video.mp4', previewUrl: '/missing-test-video.mp4', downloadUrl: '/missing-test-video.mp4', segments: [{ start: 1, end: 11 }] });
  const job = { id: 'job_ui_consistency', filename: '横屏源素材.mp4', status: 'completed', taskMode: 'highlight',
    videoInfo: { duration: 30, width: 1024, height: 576 }, messages: [], candidates: [], eventGroups: [],
    presentation: { schemaVersion: 4, key: 'exported', group: 'completed', label: '正式视频已生成', journeyStage: 4 },
    projectSettings: { outputAspect: '9:16', outputFit: 'crop' },
    editSessions: [{ id: 'session_ui', revision: 2, previewRevision: 1, previewStatus: 'stale', duration: 999,
      preflight: { ready: true, issues: [{ severity: 'warning', message: '请试听声音衔接' }] },
      clips: [{ id: 'clip1', title: '变速镜头', sourceStart: 0, sourceEnd: 8, playbackRate: .5 },
        { id: 'clip2', title: '衔接镜头', sourceStart: 12, sourceEnd: 16, playbackRate: 2, transitionIn: { type: 'dissolve', duration: .3 } }] }],
    outputVersions: [{ id: 'v1', number: 1, outputs: [output('v1.mp4', 1024, 576)] },
      { id: 'v2', number: 2, outputs: [output('v2.mp4', 540, 960)] },
      { id: 'sample', number: 3, previewOnly: true, outputs: [{ ...output('sample.mp4'), previewOnly: true }] }], outputs: [],
  };
  const server = await staticApp(job);
  const browser = await chromium.launch();
  try {
    for (const width of [1920, 1440, 1366, 1280, 1024, 768, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(6000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`${server.url}/#job=${job.id}`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => window.ClipTalkCurrentJobId?.());
      await page.waitForTimeout(350);
      assert.equal(await page.locator('#timelinePanel').isVisible(), true, 'Ready source tracks stay visible beside generated versions');
      assert.equal(await page.locator('#timelineTitle').innerText(), '源片时间轴');
      assert.equal(await page.locator('body').getAttribute('data-precision-editing'), 'false');
      await page.evaluate(() => window.ClipTalkWorkspaceController.openRail('materials'));
      await page.waitForFunction(() => document.querySelector('#ctV4MaterialsSummary')?.dataset.outputFilename === 'v2.mp4');
      await page.evaluate(() => {
        const card = document.createElement('article');
        card.id = 'legacyResultContrast';
        card.className = 'auto-compose-result-card compact';
        card.innerHTML = '<strong>正式视频已生成</strong><p>旧任务结果继续保留</p>';
        document.querySelector('#chatMessages').append(card);
        document.querySelector('#chatMessages').insertAdjacentHTML('beforeend', '<article class="chat-message assistant" id="assistantBubbleContrast"><div class="bubble"><small>剪辑助手</small><p>样片已准备好，请检查衔接。</p></div></article><article class="chat-message user" id="userBubbleContrast"><div class="bubble"><small>你</small><p>保留核心回答。</p></div></article>');
      });
      if (width <= 760) {
        assert.equal(await page.locator('#appSidebar').isVisible(), false);
        await page.locator('#mobileNavigationToggle').click();
        assert.equal(await page.locator('#appSidebar').isVisible(), true);
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#appSidebar').isVisible(), false);
      }
      for (const theme of ['light', 'dark']) {
        await page.evaluate(value => { window.ClipTalkTheme.apply(value); window.ClipTalkWorkspaceController.openRail('project'); }, theme);
        await page.waitForTimeout(650);
        const colors = await page.evaluate(() => ['#timelineTitle', '#playerRate', '#ctV4ProjectPanel > header strong', '#ctV4ReframeFit', '#legacyResultContrast strong', '#legacyResultContrast p', '#agentSkillMenuButton small', '#secondaryEditCurrentButton', '#sidebarHistoryToggle', '[data-ct-source-expand]', '[data-ct-v4-open-versions]', '#ctV4GenerateAspect', '[data-ct-v4-replace]'].map(selector => {
          const node = document.querySelector(selector), style = getComputedStyle(node);
          let parent = node, background;
          while (parent) { background = getComputedStyle(parent).backgroundColor; if (/rgb\(/.test(background)) break; parent = parent.parentElement; }
          return { selector, foreground: style.color, background };
        }));
        for (const color of colors) assert.ok(contrast(color.foreground, color.background) >= 4.5, JSON.stringify({ width, theme, ...color }));
        const bubbles = await page.locator('#assistantBubbleContrast .bubble, #userBubbleContrast .bubble').evaluateAll(nodes => nodes.flatMap(node => [...node.querySelectorAll('small, p')].map(text => ({ foreground: getComputedStyle(text).color, background: getComputedStyle(node).backgroundColor }))));
        for (const color of bubbles) assert.ok(contrast(color.foreground, color.background) >= 4.5, JSON.stringify({ width, theme, bubble: color }));
        const fit = page.locator('#ctV4ReframeFit');
        assert.equal(await fit.inputValue(), 'crop');
        assert.equal(await fit.evaluate(node => getComputedStyle(node).backgroundRepeat), 'no-repeat');
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      }
      await page.evaluate(() => window.ClipTalkWorkspaceController.openRail('materials'));
      await page.locator('[data-ct-v4-open-versions]').click();
      assert.equal(await page.locator('#ctV4VersionList .clip-version-entry').count(), 3);
      await page.locator('#ctV4VersionList [data-auto-output="v1.mp4"]').click();
      // Playback switches compact layouts to the preview pane. Reopen the
      // material pane before interacting with its version-list controls.
      await page.evaluate(() => window.ClipTalkWorkspaceController.openRail('materials'));
      await page.locator('[data-ct-versions-back]').click();
      // Source card is hidden by the rail-slimming pass. Replay exactly what the
      // old inline preview button did (value + change event), independent of the
      // select's responsive visibility across the width loop.
      await page.evaluate(() => {
        const select = document.querySelector('#videoViewSelect');
        select.value = 'source';
        select.dispatchEvent(new Event('change', { bubbles: true }));
      });
      assert.equal(await page.locator('#ctV4MaterialsSummary').getAttribute('data-output-filename'), 'v1.mp4');
      await page.evaluate(() => window.ClipTalkVersionAction('sample.mp4', 'preview'));
      await page.waitForFunction(() => document.querySelector('#ctV4MaterialsSummary').dataset.outputFilename === 'sample.mp4');
      assert.doesNotMatch(await page.locator('#ctV4DeliveryChecks').innerText(), /待检测|尺寸待检测/);
      assert.doesNotMatch(await page.locator('#ctV4DeliveryChecks').innerText(), /竖屏/);
      assert.equal(await page.locator('[data-ct-v4-export]').count(), 0);
      assert.equal(await page.locator('#finalizePreviewButton').innerText(), '导出成片');
      assert.equal(await page.locator('#finalizePreviewButton').evaluate(node => node.classList.contains('hidden')), false);
      if (width <= 800) {
        await page.locator('#ctCompactWorkspaceNav [data-ct-compact-view="preview"]').click();
        const geometry = await page.evaluate(() => {
          const nav = document.querySelector('#ctCompactWorkspaceNav').getBoundingClientRect();
          const header = document.querySelector('.review-header').getBoundingClientRect();
          const stage = document.querySelector('#reviewStage').getBoundingClientRect();
          return { navBottom: nav.bottom, headerTop: header.top, headerBottom: header.bottom, stageTop: stage.top };
        });
        assert.ok(geometry.headerTop >= geometry.navBottom, JSON.stringify(geometry));
        assert.ok(geometry.stageTop >= geometry.headerBottom - 1, JSON.stringify(geometry));
      }
      if (width > 1024) assert.equal(await page.locator('#finalizePreviewButton').isVisible(), true);
      assert.match(await page.locator('#downloadButton').textContent(), /下载 V\d+ 审核样片/);
      if (width >= 1024) {
        await page.evaluate(() => window.ClipTalkOpenAgentTimeline({ sessionId: 'session_ui', reviewPendingProposal: true }));
        await page.locator('[data-secondary-inspector-tab="export"]').click();
        assert.equal(await page.locator('#secondaryEditorExport').isDisabled(), true, 'Stale samples cannot be exported');
        assert.match(await page.locator('#secondaryEditorPreflight').innerText(), /时间线检查有提醒/);
        assert.match(await page.locator('#secondaryEditorPreflight').innerText(), /00:17\.70/);
        assert.doesNotMatch(await page.locator('#secondaryEditorPreflight').innerText(), /999/);
        for (const theme of ['light', 'dark']) {
          await page.evaluate(value => window.ClipTalkTheme.apply(value), theme);
          await page.waitForTimeout(650);
          const textColors = await page.locator('.secondary-timeline-clip :is(strong, small, em)').evaluateAll(nodes => nodes.map(node => ({ fg: getComputedStyle(node).color, bg: getComputedStyle(node).backgroundColor })));
          for (const colors of textColors) assert.ok(contrast(colors.fg, colors.bg) >= 4.5, JSON.stringify({ width, theme, colors }));
        }
      }
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); await server.close(); }
});

test('fresh entry uses the real stylesheet chain without clipping or leaked navigation', async () => {
  const server = await staticApp();
  const browser = await chromium.launch();
  try {
    for (const [width, height] of [[1920, 1080], [1440, 900], [1366, 768], [1024, 768], [390, 844]]) {
      const page = await browser.newPage({ viewport: { width, height } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(server.url);
      await page.waitForFunction(() => document.querySelector('#homeView').dataset.homeState === 'ready');
      assert.equal(await page.locator('#ctCompactWorkspaceNav').isVisible(), false);
      assert.equal(await page.locator('#sidebarHistoryList .shell-task-card[data-status-group="cancelled"]').count(), 1, 'Cancelled tasks remain accessible in recent history');
      assert.equal(await page.locator('#sidebarHistoryList .shell-task-card[data-status-group="active"]').count(), 0);
      assert.match(await page.locator('#engineState').innerText(), /部分功能不可用/);
      if (width <= 760) await page.locator('#mobileNavigationToggle').click();
      await page.locator('#sidebarNewTask').click();
      await page.waitForFunction(() => document.body.classList.contains('ct-workbench-v4'));
      if (width >= 1280) {
        const assistant = page.locator('#assistantPanel');
        assert.equal(Math.round((await assistant.boundingBox()).width), 430);
        const handle = page.locator('.panel-resizer-left');
        await handle.focus();
        await page.keyboard.press('ArrowRight');
        assert.equal(Math.round((await assistant.boundingBox()).width), 446);
        assert.equal(await page.evaluate(() => localStorage.getItem('cliptalk-new-task-assistant-width:v1')), '446');
        await page.keyboard.press('Home');
        assert.equal(Math.round((await assistant.boundingBox()).width), 380);
      }
      const bounds = await page.locator('#uploadView, #uploadView>.intro, #uploadForm').evaluateAll(es => es.map(e => e.getBoundingClientRect().toJSON()));
      assert.ok(bounds[1].left >= bounds[0].left && bounds[2].right <= bounds[0].right + 1, JSON.stringify({ width, bounds }));
      const workspace = await page.locator('#workspace').boundingBox();
      assert.ok(workspace.y + workspace.height <= height + 1, JSON.stringify({ width, workspace }));
      await page.locator('#dropZone').scrollIntoViewIfNeeded();
      assert.ok(await page.locator('#dropZone').isVisible());
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); await server.close(); }
});
