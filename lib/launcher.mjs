// POC 4: coding-tool launcher detection (cc-switch idea, CLI-native).
// Scope POC: deteksi + preview config saja. --apply sengaja TIDAK ada
// (menulis config orang lain dari POC adalah perilaku yang salah).
import { execFileSync } from 'node:child_process';
import { onPath } from './mcp.mjs';

const BASE = 'http://127.0.0.1:11435';

export function toolCatalog() {
  return [
    {
      id: 'opencode', bin: 'opencode',
      config: 'opencode.json (blok provider)',
      preview: { provider: { 'botconnector-local': { options: { baseURL: `${BASE}/v1`, apiKey: 'local' } } } },
    },
    {
      id: 'claude-code', bin: 'claude',
      config: 'ANTHROPIC_BASE_URL (manual, eksperimental)',
      preview: { ANTHROPIC_BASE_URL: BASE, note: 'butuh /v1/messages di runtime; smoke-test manual wajib' },
    },
    {
      id: 'codex', bin: 'codex',
      config: '~/.codex/config.toml (manual)',
      preview: { model_provider: 'botconnector-local', base_url: `${BASE}/v1` },
    },
    {
      id: 'cline', bin: null,
      config: 'VS Code settings cline.* (manual)',
      preview: { 'cline.apiProvider': 'openai-compatible', 'cline.baseUrl': `${BASE}/v1` },
    },
    {
      id: 'gemini-cli', bin: 'gemini',
      config: 'env GEMINI_BASE_URL (manual, eksperimental)',
      preview: { GEMINI_BASE_URL: BASE, note: 'kompatibilitas tidak dijamin; smoke-test manual wajib' },
    },
  ];
}

export function detectTools() {
  return toolCatalog().map((t) => ({ ...t, detected: t.bin ? onPath(t.bin) : null }));
}
