import test from 'node:test';
import assert from 'node:assert/strict';
import {  loadCatalog, validateCatalog, probeEntry, onPath  } from '../lib/mcp.mjs';

test('katalog bawaan valid', async () => {
  const servers = await loadCatalog();
  assert.ok(servers.length >= 3);
  assert.deepEqual(validateCatalog(servers), []);
});

test('validator menangkap id duplikat, transport liar, license kosong', () => {
  const bad = [
    { id: 'a', repo: 'x/y', transport: 'stdio', runtime: { tool: 'npx', package: 'p' }, license: 'MIT' },
    { id: 'a', repo: 'x/y', transport: 'sse', runtime: { tool: 'npx', package: 'p' }, license: '' },
  ];
  const errs = validateCatalog(bad);
  assert.ok(errs.some((e) => /duplikat/.test(e)));
  assert.ok(errs.some((e) => /stdio/.test(e)));
  assert.ok(errs.some((e) => /license/.test(e)));
});

test('probe jujur: tool tak ada => tidak runnable', () => {
  const r = probeEntry({ id: 'x', runtime: { tool: 'bin-yang-pasti-tidak-ada-xyz', package: 'p' }, license: 'MIT', install: 'n/a' });
  assert.equal(r.toolOnPath, false);
  assert.equal(r.runnableHere, false);
  assert.match(r.note, /tidak ada di PATH/);
});

test('onPath menemukan node itu sendiri', () => {
  assert.equal(onPath('node'), true);
  assert.equal(onPath('bin-yang-pasti-tidak-ada-xyz'), false);
});
