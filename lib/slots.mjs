// POC 1: profile registry with health-verified switching (llama-swap profiles idea).
// Localhost-only by design: baseUrl must be http(s)://127.0.0.1:<port> or localhost.
// Switching to a profile whose /health is DOWN is refused — no fake "active" state.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

export function statePath() {
  return process.env.POC_STATE || path.join(os.tmpdir(), 'botconnector-poc-state.json');
}

export async function loadState() {
  try {
    const raw = JSON.parse(await fsp.readFile(statePath(), 'utf8'));
    if (!raw || typeof raw !== 'object') return { profiles: {}, active: null };
    if (!raw.profiles || typeof raw.profiles !== 'object') raw.profiles = {};
    if (raw.active && !raw.profiles[raw.active]) raw.active = null;
    return raw;
  } catch {
    return { profiles: {}, active: null };
  }
}

async function saveState(s) {
  const file = statePath();
  const tmp = `${file}.tmp-${process.pid}-${Date.now()}`;
  await fsp.writeFile(tmp, JSON.stringify(s, null, 2), { mode: 0o600 });
  await fsp.rename(tmp, file);
}

const NAME_RE = /^[a-z0-9][a-z0-9-_]{0,40}$/i;

export function normalizeBaseUrl(raw) {
  const u = new URL(String(raw));
  if (!['http:', 'https:'].includes(u.protocol)) throw new Error('baseUrl must be http(s)');
  if (!['127.0.0.1', 'localhost', '::1'].includes(u.hostname)) {
    throw new Error('baseUrl must be localhost (127.0.0.1) only');
  }
  u.hash = '';
  u.search = '';
  return u.toString().replace(/\/$/, '');
}

export async function addProfile(name, baseUrl) {
  if (!NAME_RE.test(String(name || ''))) throw new Error('profile name: 1-41 chars, alphanumerik/dash/underscore');
  const s = await loadState();
  s.profiles[name] = { name, baseUrl: normalizeBaseUrl(baseUrl), addedAt: new Date().toISOString() };
  await saveState(s);
  return s.profiles[name];
}

export async function removeProfile(name) {
  const s = await loadState();
  if (!s.profiles[name]) throw new Error(`profile tidak dikenal: ${name}`);
  delete s.profiles[name];
  if (s.active === name) s.active = null;
  await saveState(s);
  return { ok: true, removed: name };
}

export async function checkHealth(baseUrl, timeoutMs = 3000) {
  try {
    const r = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(timeoutMs) });
    return { up: r.ok, status: r.status };
  } catch (e) {
    return { up: false, error: String(e.cause?.message || e.message) };
  }
}

export async function liveStatus() {
  const s = await loadState();
  const out = [];
  for (const p of Object.values(s.profiles)) {
    out.push({ ...p, active: s.active === p.name, ...(await checkHealth(p.baseUrl)) });
  }
  return { active: s.active, profiles: out };
}

export async function switchProfile(name) {
  const s = await loadState();
  const p = s.profiles[name];
  if (!p) throw new Error(`profile tidak dikenal: ${name} (lihat: poc profiles)`);
  const h = await checkHealth(p.baseUrl);
  if (!h.up) throw new Error(`profile ${name} menolak switch: /health DOWN (${h.error || 'HTTP ' + h.status})`);
  s.active = name;
  await saveState(s);
  return { ok: true, active: name, health: h };
}
