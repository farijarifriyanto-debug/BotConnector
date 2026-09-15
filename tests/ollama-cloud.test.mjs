import test from 'node:test';
import assert from 'node:assert/strict';
import { getKey, keyStatus, listModels, chat, CLOUD_BASE } from '../lib/ollama-cloud.mjs';

const SAVED = process.env.OLLAMA_API_KEY;
const withKey = (fn) => async () => { process.env.OLLAMA_API_KEY = 'k-test'; try { await fn(); } finally { delete process.env.OLLAMA_API_KEY; } };
const withoutKey = (fn) => async () => { delete process.env.OLLAMA_API_KEY; try { await fn(); } finally { if (SAVED) process.env.OLLAMA_API_KEY = SAVED; } };

test('base resmi ollama.com', () => assert.equal(CLOUD_BASE, 'https://ollama.com'));

test('tanpa key: chat gagal sebelum request; tags tetap jalan (publik)', withoutKey(async () => {
  assert.equal(getKey(), null);
  assert.equal(keyStatus().configured, false);
  let called = false;
  await assert.rejects(() => chat('m', [{ role: 'user', content: 'hi' }], { fetchImpl: async () => { called = true; } }), /OLLAMA_API_KEY/);
  assert.equal(called, false);
  const stub = async () => ({ ok: true, status: 200, json: async () => ({ models: [] }) });
  assert.deepEqual(await listModels({ fetchImpl: stub }), []);
}));

test('dengan key: header Bearer + parse /api/tags', withKey(async () => {
  let seen = {};
  const stub = async (url, init) => {
    seen = { url, auth: init.headers.Authorization, method: init.method };
    return { ok: true, status: 200, json: async () => ({ models: [{ name: 'gpt-oss:120b-cloud', size: 1000 }] }) };
  };
  const models = await listModels({ fetchImpl: stub });
  assert.equal(models[0].name, 'gpt-oss:120b-cloud');
  assert.equal(seen.url, 'https://ollama.com/api/tags');
  assert.equal(seen.auth, 'Bearer k-test');
}));

test('401 diterjemahkan jadi pesan key', withKey(async () => {
  const stub = async () => ({ ok: false, status: 401, text: async () => 'unauthorized' });
  await assert.rejects(() => listModels({ fetchImpl: stub }), /ditolak/);
}));

test('chat parse content + validasi input', withKey(async () => {
  const stub = async (url, init) => ({
    ok: true, status: 200,
    json: async () => ({ model: 'gpt-oss:120b-cloud', message: { content: 'Biru karena Rayleigh.' } }),
  });
  const r = await chat('gpt-oss:120b-cloud', [{ role: 'user', content: 'Langit?' }], { fetchImpl: stub });
  assert.equal(r.content, 'Biru karena Rayleigh.');
  await assert.rejects(() => chat('', [{ role: 'user', content: 'x' }], { fetchImpl: stub }), /model wajib/);
}));
