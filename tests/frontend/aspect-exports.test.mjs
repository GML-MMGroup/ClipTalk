import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '../..');

async function exportPanelHtml() {
  const html = await readFile(resolve(root, 'static/index.html'), 'utf8');
  return html.split('data-secondary-inspector-panel="export"')[1]?.split('</section>')[0] || '';
}

test('the export panel offers one checkbox per delivery aspect', async () => {
  const section = await exportPanelHtml();
  assert.notEqual(section, '', 'export panel must exist');
  for (const aspect of ['9:16', '1:1', '16:9']) {
    assert.match(section, new RegExp(`data-aspect-export value="${aspect}"`), `缺少 ${aspect} 选项`);
  }
});

test('exporting a version forwards the checked aspects', async () => {
  const source = await readFile(resolve(root, 'static/app.js'), 'utf8');
  assert.match(source, /\[data-aspect-export\]:checked/, '没有读取勾选的画幅');
  assert.match(source, /acknowledgedWarningCodes: risk\.warningCodes, aspectExports/, '导出请求没有带上画幅');
  assert.match(source, /aspectExports\.length \? `同时导出/, '确认弹窗没有说明额外画幅');
});
