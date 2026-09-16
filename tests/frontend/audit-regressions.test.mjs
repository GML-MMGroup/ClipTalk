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

test('warning previews expose full playback and export the exact bound artifact', async () => isolatedPage(async page => {
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
  await page.getByRole('button', { name: '播放完整样片', exact: true }).click();
  assert.equal(await page.evaluate(() => window.opened[0].filename), 'portrait.mp4');
  assert.equal(await page.locator('[data-qc-start="36"]').count(), 1);
  const button = page.getByRole('button', { name: '生成成片', exact: true });
  await button.click();
  assert.equal(await page.evaluate(() => window.exported[0].revision), 3);
  assert.equal(await button.getAttribute('data-export-plan'), 'plan_A');
  await page.evaluate(() => { window.artifact.revision = 4; });
  await button.click();
  assert.equal(await page.evaluate(() => window.exported.length), 1, 'A stale button must not export a newer revision silently');
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
    await page.evaluate(() => {
      window.__coverGoalRevised = false;
      window.__coverCandidatesRetried = false;
      window.ClipTalkReviseAgentGoal = () => { window.__coverGoalRevised = true; return true; };
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
    for (const width of [1920, 1440, 1366, 1024, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(6000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`${server.url}/#job=${job.id}`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => window.ClipTalkCurrentJobId?.());
      await page.waitForTimeout(350);
      assert.equal(await page.locator('#timelinePanel').isVisible(), false, 'Media data arriving must not expand the timeline');
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
        const colors = await page.evaluate(() => ['#timelineTitle', '#playerRate', '#ctV4ProjectPanel > header strong', '#ctV4ReframeFit', '#legacyResultContrast strong', '#legacyResultContrast p', '#agentSkillMenuButton span', '#agentSkillMenuButton small', '#secondaryEditCurrentButton', '#sidebarHistoryToggle', '[data-ct-source-expand]', '[data-ct-v4-open-versions]', '#ctV4GenerateAspect', '[data-ct-v4-replace]'].map(selector => {
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
      await page.locator('[data-ct-versions-back]').click();
      await page.locator('[data-ct-v4-preview-source]').click();
      assert.equal(await page.locator('#ctV4MaterialsSummary').getAttribute('data-output-filename'), 'v1.mp4');
      await page.evaluate(() => window.ClipTalkVersionAction('sample.mp4', 'preview'));
      await page.waitForFunction(() => document.querySelector('#ctV4MaterialsSummary').dataset.outputFilename === 'sample.mp4');
      assert.doesNotMatch(await page.locator('#ctV4DeliveryChecks').innerText(), /待检测|尺寸待检测/);
      assert.doesNotMatch(await page.locator('#ctV4DeliveryChecks').innerText(), /竖屏/);
      assert.equal(await page.locator('[data-ct-v4-export]').count(), 0);
      assert.equal(await page.locator('#finalizePreviewButton').innerText(), '生成成片');
      assert.equal(await page.locator('#finalizePreviewButton').evaluate(node => node.classList.contains('hidden')), false);
      if (width > 1024) assert.equal(await page.locator('#finalizePreviewButton').isVisible(), true);
      assert.match(await page.locator('#downloadButton').innerText(), /下载 V\d+ 审核样片/);
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
      assert.equal(await page.locator('#homeTaskGrid .shell-task-card[data-status-group="cancelled"]').count(), 1, 'Cancelled tasks remain accessible in recent history');
      assert.equal(await page.locator('#homeTaskGrid .shell-task-card[data-status-group="active"]').count(), 0);
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
