import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const context = { window: {} };
vm.runInNewContext(readFileSync(new URL('../../static/workspace-state.js', import.meta.url), 'utf8'), context);
const state = context.window.ClipTalkWorkspaceState;
const plain = value => JSON.parse(JSON.stringify(value));

test('display time carries rounded seconds into minutes and hours', () => {
  for (const [value, expected] of [[0, '00:00.0'], [-3, '00:00.0'], [59.95, '01:00.0'],
    [539.97, '09:00.0'], [3599.95, '01:00:00.0'], [NaN, '00:00.0'], [Infinity, '00:00.0']]) {
    assert.equal(state.formatTime(value), expected);
  }
});

test('explicit handoffs form one logical task without merging same-name projects', () => {
  const jobs = [{ id: 'a', filename: '产品.mp4', latestHandoff: { toJobId: 'b' } },
    { id: 'b', filename: '产品.mp4', latestHandoff: { toJobId: 'c' } },
    { id: 'c', filename: '产品.mp4', status: 'completed' }, { id: 'd', filename: '产品.mp4' }];
  const before = JSON.stringify(jobs);
  const tasks = plain(state.logicalTasks(jobs));
  assert.equal(tasks.length, 2);
  assert.equal(tasks[0].id, 'c');
  assert.equal(tasks[0].openJobId, 'c');
  assert.deepEqual(tasks[0].executionHistory.map(j => j.id), ['a', 'b']);
  assert.equal(JSON.stringify(jobs), before, 'Display grouping never mutates stored jobs');
});

test('partial pages preserve tasks and cycles remain accessible', () => {
  const partial = state.logicalTasks([{ id: 'a', latestHandoff: { toJobId: 'b' } }]);
  assert.equal(partial.length, 1);
  assert.equal(partial[0].openJobId, 'b');
  const cycle = plain(state.logicalTasks([{ id: 'b', latestHandoff: { toJobId: 'a' } },
    { id: 'a', latestHandoff: { toJobId: 'b' } }]));
  assert.equal(cycle.length, 1);
  assert.equal(cycle[0].openJobId, 'a');
  assert.deepEqual(cycle[0].executionHistory.map(j => j.id), ['b']);
});

test('repeated page records are deduplicated by id', () => {
  assert.equal(state.logicalTasks([{ id: 'a' }, { id: 'a' }, { id: 'b' }]).length, 2);
});
