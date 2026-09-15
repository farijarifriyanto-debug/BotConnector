import test from 'node:test';
import assert from 'node:assert/strict';
import { execCommand } from '../lib/commands.mjs';

test('perintah tak dikenal jujur', async () => {
  const r = await execCommand({ cmd: 'menu', args: [] });
  assert.equal(r[0].role, 'error');
});

test('help dan kosong', async () => {
  assert.ok((await execCommand({ cmd: 'help', args: [] }))[0].text.includes('/switch'));
  assert.deepEqual(await execCommand({ cmd: '', args: [] }), []);
});

test('switch tanpa nama meminta picker', async () => {
  assert.deepEqual(await execCommand({ cmd: 'switch', args: [] }), [{ role: 'picker' }]);
});
