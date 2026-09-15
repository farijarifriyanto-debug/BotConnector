import test from 'node:test';
import assert from 'node:assert/strict';
import { parseLine, filterSlash, SLASH, wrap, visibleLen } from '../lib/tui.mjs';

test('parseLine: slash, spasi, kosong', () => {
  assert.deepEqual(parseLine('/switch model-a'), { cmd: 'switch', args: ['model-a'] });
  assert.deepEqual(parseLine('  /HW  '), { cmd: 'hw', args: [] });
  assert.deepEqual(parseLine(''), { cmd: '', args: [] });
  assert.deepEqual(parseLine('/add a http://127.0.0.1:1'), { cmd: 'add', args: ['a', 'http://127.0.0.1:1'] });
});

test('filterSlash: prefix dan semua perintah terdaftar', () => {
  assert.ok(SLASH.length >= 8);
  assert.ok(filterSlash('/s').some((s) => s.name === '/switch'));
  assert.equal(filterSlash('/zzz').length, 0);
  assert.equal(filterSlash('').length, SLASH.length);
});

test('wrap: tidak ada baris melebihi lebar (ANSI tidak dihitung)', () => {
  const rows = wrap('\x1b[38;5;75m/hw\x1b[0m — ringkasan hardware + skor fit yang panjang sekali', 20);
  assert.ok(rows.length > 1);
  for (const r of rows) assert.ok(visibleLen(r) <= 20, r);
});
