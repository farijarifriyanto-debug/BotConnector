// Klien Ollama Cloud — API resmi langsung ke https://ollama.com/api
// (docs: docs.ollama.com/cloud, docs.ollama.com/api/authentication).
// Auth: header `Authorization: Bearer $OLLAMA_API_KEY`, key dari
// https://ollama.com/settings/keys. Key HANYA dari env, tidak pernah
// ditulis ke disk / log / output oleh modul ini.
export const CLOUD_BASE = 'https://ollama.com';

export function getKey() {
  return process.env.OLLAMA_API_KEY || null;
}

export function keyStatus() {
  return { configured: Boolean(getKey()), source: getKey() ? 'env:OLLAMA_API_KEY' : 'missing' };
}

export async function api(pathname, { method = 'GET', body, timeoutMs = 30000, auth = 'required', fetchImpl = fetch } = {}) {
  const key = getKey();
  // /api/tags publik (terbukti live: 200 tanpa key); chat/generate wajib key.
  if (!key && auth === 'required') throw new Error('OLLAMA_API_KEY belum diset. Buat di https://ollama.com/settings/keys lalu: export OLLAMA_API_KEY=...');
  let res;
  try {
    res = await fetchImpl(`${CLOUD_BASE}${pathname}`, {
      method,
      headers: { 'Content-Type': 'application/json', ...(key ? { Authorization: `Bearer ${key}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    throw new Error(`jaringan ke ollama.com gagal: ${e.cause?.message || e.message}`);
  }
  if (res.status === 401) throw new Error('API key ditolak (401). Periksa / cabut-ulang di https://ollama.com/settings/keys');
  if (!res.ok) {
    const t = await res.text().catch(() => '').then((s) => String(s).slice(0, 200));
    throw new Error(`ollama.com -> HTTP ${res.status}${t ? `: ${t}` : ''}`);
  }
  return res.json();
}

// GET /api/tags — publik, bisa tanpa key. Dipakai status sebagai probe.
export async function listModels(opts = {}) {
  const j = await api('/api/tags', { ...opts, auth: 'optional' });
  if (!Array.isArray(j.models)) throw new Error('respons /api/tags tak terduga (bukan array models)');
  return j.models;
}

// POST /api/chat non-stream — {model, messages:[{role,content}]}
export async function chat(model, messages, opts = {}) {
  if (!model) throw new Error('model wajib diisi (mis. gpt-oss:120b-cloud)');
  if (!Array.isArray(messages) || !messages.length) throw new Error('messages wajib array tak kosong');
  const j = await api('/api/chat', { ...opts, method: 'POST', body: { model, messages, stream: false } });
  return { model: j.model || model, content: j.message?.content ?? '', raw: j };
}

// POST /api/generate non-stream — {model, prompt}
export async function generate(model, prompt, opts = {}) {
  if (!model) throw new Error('model wajib diisi');
  if (!prompt) throw new Error('prompt wajib diisi');
  const j = await api('/api/generate', { ...opts, method: 'POST', body: { model, prompt, stream: false } });
  return { model: j.model || model, content: j.response ?? '', raw: j };
}
