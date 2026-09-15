// Perintah POC dalam satu sumber kebenaran — dipakai CLI, TUI ANSI, dan TUI OpenTUI.
// Kembalikan array {role:'agent'|'error'|'picker', text?}. 'picker' = minta UI
// membuka pemilih profil (datanya diambil UI via liveStatus dari slots.mjs).
import { liveStatus, switchProfile, addProfile, removeProfile } from './slots.mjs';
import { detectHardware, assessFit } from './hardware.mjs';
import { loadCatalog, validateCatalog, listProbed } from './mcp.mjs';
import { detectTools } from './launcher.mjs';

export async function execCommand({ cmd, args }) {
  switch (cmd) {
    case 'hw': {
      const hw = await detectHardware();
      const fit = assessFit({ kind: 'local', minRamGb: 8, recRamGb: 16, recVramGb: 6 }, hw);
      return [{ role: 'agent', text: `Hardware  ${hw.platform}/${hw.arch} · ${hw.cpu} ×${hw.logicalCores}\nRAM ${hw.ramGb} GB (bebas ${hw.freeRamGb} GB) · VRAMmax ${hw.vramGb} GB${hw.override ? ' · override' : ''}\nFit  ${fit.level} (${fit.label}) [${fit.confidence}] — ${fit.reason}` }];
    }
    case 'ps':
    case 'profiles': {
      const st = await liveStatus();
      if (!st.profiles.length) return [{ role: 'agent', text: 'Belum ada profil. /add <nama> <url>' }];
      return [{ role: 'agent', text: st.profiles.map((p) => `${p.active ? '●' : '○'} ${p.name}  ${p.baseUrl}  ${p.up ? `UP ${p.status}` : `DOWN ${p.error || '?'}`}`).join('\n') }];
    }
    case 'switch': {
      if (!args[0]) return [{ role: 'picker' }];
      const r = await switchProfile(args[0]);
      return [{ role: 'agent', text: `Aktif: ${r.active} (health UP ${r.health.status})` }];
    }
    case 'add': {
      if (args.length < 2) return [{ role: 'agent', text: 'Pakai: /add <nama> <url>  (url wajib localhost)' }];
      const p = await addProfile(args[0], args[1]);
      return [{ role: 'agent', text: `Terdaftar: ${p.name} → ${p.baseUrl}` }];
    }
    case 'rm':
    case 'unload': {
      if (!args[0]) return [{ role: 'agent', text: 'Pakai: /rm <nama>' }];
      await removeProfile(args[0]);
      return [{ role: 'agent', text: `Dihapus: ${args[0]}` }];
    }
    case 'mcp': {
      const servers = await loadCatalog();
      const errs = validateCatalog(servers);
      if (errs.length) return [{ role: 'error', text: 'Katalog rusak: ' + errs.join('; ') }];
      return [{ role: 'agent', text: (await listProbed()).map((r) => `${r.probe.toolOnPath ? '+' : 'x'} ${r.id} [${r.license}] ${r.probe.note}`).join('\n') }];
    }
    case 'launch':
      return [{ role: 'agent', text: detectTools().map((t) => `${t.detected === null ? '-' : t.detected ? '+' : 'x'} ${t.id} :: ${t.config}`).join('\n') }];
    case 'cloud': {
      const oc = await import('./ollama-cloud.mjs');
      const a = args[0] || 'status';
      const usage = 'Pakai: /cloud status | models | chat <model> <prompt>';
      try {
        if (a === 'status') {
          const ks = oc.keyStatus();
          if (!ks.configured) return [{ role: 'error', text: 'OLLAMA_API_KEY belum diset. Buat di https://ollama.com/settings/keys lalu export.' }];
          const m = await oc.listModels();
          return [{ role: 'agent', text: `OK: key valid, ${m.length} model terlihat di ollama.com.` }];
        }
        if (a === 'models') {
          const m = await oc.listModels();
          return [{ role: 'agent', text: m.length ? m.map((x) => `${x.name}  ${(x.size / 1073741824).toFixed(1)}GB`).join('\n') : '(kosong)' }];
        }
        if (a === 'chat') {
          const model = args[1] || '';
          const prompt = args.slice(2).join(' ');
          if (!model || !prompt) return [{ role: 'agent', text: usage }];
          const r = await oc.chat(model, [{ role: 'user', content: prompt }]);
          return [{ role: 'agent', text: `[${r.model}]\n${r.content}` }];
        }
        return [{ role: 'agent', text: usage }];
      } catch (e) { return [{ role: 'error', text: e.message }]; }
    }
    case 'help':
      return [{ role: 'agent', text: '/hw — hardware+fit\n/ps — profil+health\n/switch [nama] — tanpa nama buka picker\n/add <nama> <url> — daftar localhost\n/rm <nama> — hapus\n/mcp — katalog+probe\n/launch — coding tools\n/cloud status|models|chat <model> <prompt> — Ollama Cloud\n/quit — keluar' }];
    case '':
      return [];
    default:
      return [{ role: 'error', text: `Tidak dikenal: ${cmd}. /help untuk daftar.` }];
  }
}
