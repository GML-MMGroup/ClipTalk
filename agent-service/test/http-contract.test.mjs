import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { once } from 'node:events';
import test from 'node:test';

const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));
const close = server => new Promise(resolve => server.close(resolve));

test('real Pi service preserves planning-only tools, validates input and streams results', { timeout: 45000 }, async t => {
  const temp = await mkdtemp(join(tmpdir(), 'cliptalk-agent-contract-'));
  let calls = [];
  let malformed = false;
  const provider = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    calls.push(body);
    const finished = body.messages.some(message => message.role === 'tool');
    const args = malformed ? { strategy: {} } : { summary: '检索并审核候选', strategy: { searchQuery: '续航', preserveContext: true } };
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const chunk = (delta, finish_reason = null) => response.write(`data: ${JSON.stringify({ id: 'chat_test', object: 'chat.completion.chunk', created: 1, model: 'test', choices: [{ index: 0, delta, finish_reason }] })}\n\n`);
    if (finished) { chunk({ role: 'assistant', content: '计划已提交' }); chunk({}, 'stop'); }
    else {
      chunk({ role: 'assistant', tool_calls: [{ index: 0, id: 'call_plan', type: 'function', function: { name: 'submit_plan', arguments: JSON.stringify(args) } }] });
      chunk({}, 'tool_calls');
    }
    response.end('data: [DONE]\n\n');
  });
  const modelPort = await listen(provider);
  const reservation = createServer();
  const port = await listen(reservation);
  await close(reservation);
  const child = spawn(process.execPath, ['server.mjs'], {
    cwd: resolve(import.meta.dirname, '..'),
    env: { ...process.env, CLIPTALK_AGENT_HOST: '127.0.0.1', CLIPTALK_AGENT_PORT: String(port), HIGHLIGHT_DATA_ROOT: temp },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stderr = '';
  child.stderr.on('data', data => { stderr += data; });
  const base = `http://127.0.0.1:${port}`;
  const payload = () => ({ workspaceId: 'ws_test', goal: '找出续航相关内容', skill: { id: 'test', markdown: '# Test\nPlan only.' }, toolCatalog: [], profile: { managed: true, kind: 'content' }, model: { apiKey: 'local-test-only', model: 'test', baseUrl: `http://127.0.0.1:${modelPort}/v1`, thinkingType: 'disabled' } });
  const post = (path, value) => fetch(base + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
  try {
    await Promise.race([
      once(child.stdout, 'data'),
      once(child, 'exit').then(() => { throw new Error(`Service failed to start: ${stderr}`); }),
      new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('Service startup timeout')), 15000); timer.unref(); }),
    ]);
    await t.test('invalid JSON shape is rejected', async () => {
      assert.equal((await post('/v1/plan', [])).status, 400);
      assert.equal((await post('/v1/plan', {})).status, 400);
    });
    await t.test('a plan requires real submit_plan tool calling', async () => {
      calls = [];
      const response = await post('/v1/plan', payload());
      const result = await response.json();
      assert.equal(response.status, 200, JSON.stringify(result));
      assert.equal(result.plan.strategy.searchQuery, '续航');
      assert.ok(calls.length > 0);
      for (const call of calls) assert.deepEqual(call.tools.map(tool => tool.function.name), ['submit_plan']);
    });
    await t.test('SSE emits progress and exactly one final plan', async () => {
      const response = await post('/v1/plan/stream', { ...payload(), workspaceId: 'ws_stream' });
      assert.match(response.headers.get('content-type'), /text\/event-stream/);
      const text = await response.text();
      assert.match(text, /event: planning.progress/);
      assert.equal((text.match(/event: plan\n/g) || []).length, 1);
      assert.doesNotMatch(text, /event: error/);
    });
    await t.test('invalid tool arguments cannot become a successful plan', async () => {
      malformed = true;
      const response = await post('/v1/plan', { ...payload(), workspaceId: 'ws_invalid' });
      assert.equal(response.status, 400);
      assert.match((await response.json()).message, /submit_plan/);
      malformed = false;
    });
    await t.test('stream failures use the error event contract', async () => {
      const response = await post('/v1/plan/stream', {});
      const text = await response.text();
      assert.match(text, /event: error\ndata: .*message/);
      assert.doesNotMatch(text, /event: plan\n/);
    });
    await t.test('uninstalled plugin tools cannot execute', async () => {
      const response = await post('/v1/tools/execute', { pluginId: 'missing', tool: 'missing' });
      assert.equal(response.status, 400);
    });
  } finally {
    child.kill('SIGTERM');
    if (child.exitCode === null) await once(child, 'exit');
    await close(provider);
    await rm(temp, { recursive: true, force: true });
  }
});
