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

test('/cloud tanpa key: status tetap jawab (tags publik), chat menolak', async () => {
  const saved = process.env.OLLAMA_API_KEY;
  delete process.env.OLLAMA_API_KEY;
  try {
    const r = await execCommand({ cmd: 'cloud', args: ['chat', 'm', 'hi'] });
    assert.equal(r[0].role, 'error');
  } finally { if (saved) process.env.OLLAMA_API_KEY = saved; }
});
