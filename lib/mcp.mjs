// POC 3: curated MCP catalog + availability probe (no network, no server spawn).
// Probe only checks the launcher binary (npx/node/uvx/docker/python3) on PATH
// and reports honestly whether the server can run HERE.
import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const HERE = path.dirname(fileURLToPath(import.meta.url));

export function onPath(bin) {
  try {
    execFileSync(process.platform === 'win32' ? 'where' : 'which', [bin], { stdio: 'ignore', windowsHide: true });
    return true;
  } catch {
    return false;
  }
}

export async function loadCatalog(file = path.join(HERE, '..', 'data', 'mcp-catalog.json')) {
  const raw = JSON.parse(await fsp.readFile(file, 'utf8'));
  if (!Array.isArray(raw.servers)) throw new Error('katalog rusak: servers bukan array');
  return raw.servers;
}

export function validateCatalog(servers) {
  const errors = [];
  const seen = new Set();
  for (const [i, s] of servers.entries()) {
    if (!s.id || seen.has(s.id)) errors.push(`[${i}] id duplikat/kosong: ${s.id}`);
    seen.add(s.id);
    if (!s.repo) errors.push(`[${s.id}] repo kosong`);
    if (s.transport !== 'stdio') errors.push(`[${s.id}] transport harus stdio (POC ini tidak demo SSE/HTTP)`);
    if (!s.runtime?.tool || !s.runtime?.package) errors.push(`[${s.id}] runtime.tool/package kosong`);
    if (!s.license) errors.push(`[${s.id}] license kosong (wajib dicatat)`);
  }
  return errors;
}

export function probeEntry(s) {
  const toolOk = onPath(s.runtime.tool);
  return {
    id: s.id,
    runtimeTool: s.runtime.tool,
    toolOnPath: toolOk,
    runnableHere: toolOk,
    license: s.license,
    note: toolOk ? s.install : `tidak bisa jalan di sini: '${s.runtime.tool}' tidak ada di PATH`,
  };
}

export async function listProbed() {
  const servers = await loadCatalog();
  return servers.map((s) => ({ ...s, probe: probeEntry(s) }));
}
