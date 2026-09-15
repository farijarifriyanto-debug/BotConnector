import test from 'node:test';
import assert from 'node:assert/strict';
import {  detectTools, toolCatalog  } from '../lib/launcher.mjs';

test('katalog 5 tool, preview selalu localhost', () => {
  const rows = detectTools();
  assert.equal(rows.length, 5);
  for (const t of rows) {
    assert.ok(['boolean', 'object'].includes(typeof t.detected) || t.detected === null);
    assert.match(JSON.stringify(t.preview), /127\.0\.0\.1/);
  }
  assert.deepEqual(toolCatalog().map((t) => t.id), ['opencode', 'claude-code', 'codex', 'cline', 'gemini-cli']);
});
