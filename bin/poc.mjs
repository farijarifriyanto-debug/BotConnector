// botconnector-poc CLI: proves the 4 designs with real local checks.
// Usage: node bin/poc.mjs <command> [--json]
import { addProfile, removeProfile, liveStatus, switchProfile, checkHealth } from '../lib/slots.mjs';
import { detectHardware, assessFit } from '../lib/hardware.mjs';
import { loadCatalog, validateCatalog, listProbed } from '../lib/mcp.mjs';
import { detectTools } from '../lib/launcher.mjs';
import readline from 'node:readline';

const rawArgs = process.argv.slice(2);
const json = rawArgs.includes('--json');
const out = (o) => console.log(typeof o === 'string' ? o : JSON.stringify(o, null, 2));
const fail = (m) => { console.error(json ? JSON.stringify({ ok: false, error: m }) : `Error: ${m}`); process.exit(1); };
const opt = (name, def) => { const i = rawArgs.indexOf('--' + name); return i >= 0 && rawArgs[i + 1] && !rawArgs[i + 1].startsWith('--') ? rawArgs[i + 1] : def; };

const HELP = `botconnector-poc — sandbox pembuktian (bukan produk)

  poc hw [--json]                        deteksi hardware + contoh skor fit
  poc profiles [--json]                  daftar profil + status /health asli
  poc profiles add <nama> --url <base>   daftar endpoint localhost
  poc profiles rm <nama>                 hapus profil
  poc switch <nama>                      aktifkan profil (wajib /health UP)
  poc unload <nama>                      = profiles rm (alias)
  poc ps [--json]                        = profiles (alias)
  poc mcp [--json]                       katalog MCP + probe PATH asli
  poc launch [--json]                    deteksi coding tool + preview config
  poc tui                                loop interaktif mini
  poc ui                                 TUI OpenTUI (stack opencode, butuh bun)
`;
const [cmd, sub] = rawArgs.filter((a) => !a.startsWith('--'));

if (!cmd || cmd === '--help' || cmd === 'help') { console.log(HELP); process.exit(0); }

if (cmd === 'ui') {
  console.log('Jalankan dengan bun:  bun bin/poc-ui.mjs');
  process.exit(0);
}

if (cmd === 'hw') {
  const hw = await detectHardware();
  const sample = { kind: 'local', minRamGb: 8, recRamGb: 16, recVramGb: 6 };
  out(json ? { hw, sampleFit: assessFit(sample, hw) } : [
    `platform : ${hw.platform}/${hw.arch}  cpu: ${hw.cpu} x${hw.logicalCores}`,
    `ram      : ${hw.ramGb} GB (bebas ${hw.freeRamGb} GB)${hw.override ? '  [override]' : ''}`,
    `nvidia   : ${hw.nvidia.length ? hw.nvidia.map((g) => `${g.name} ${g.memoryGb}GB`).join('; ') : '-'}`,
    `amd      : ${hw.amd.length ? hw.amd.map((g) => `${g.name}${g.memoryGb ? ` ${g.memoryGb}GB` : ' (vram tak diketahui)'}`).join('; ') : '-'}`,
    `intel    : ${hw.intel.length ? hw.intel.map((g) => g.name).join('; ') : '-'}`,
    `vramMax  : ${hw.vramGb} GB`,
    `contoh   : ${JSON.stringify(assessFit(sample, hw))}`,
  ].join('\n'));
  process.exit(0);
}

if (cmd === 'profiles' && (!sub || sub === 'add' || sub === 'rm')) {
  if (sub === 'add') {
    const name = rawArgs[2] || '';
    const url = opt('url', '');
    if (!name || !url) fail('profiles add <nama> --url http://127.0.0.1:PORT');
    try { out({ ok: true, profile: await addProfile(name, url) }); } catch (e) { fail(e.message); }
    process.exit(0);
  }
  if (sub === 'rm') {
    const name = rawArgs[2] || '';
    if (!name) fail('profiles rm <nama>');
    try { out(await removeProfile(name)); } catch (e) { fail(e.message); }
    process.exit(0);
  }
  const st = await liveStatus();
  out(json ? st : (!st.profiles.length ? 'Belum ada profil. Tambah: poc profiles add <nama> --url http://127.0.0.1:PORT'
    : st.profiles.map((p) => `${p.active ? '*' : ' '} ${p.name}  ${p.baseUrl}  ${p.up ? `UP (${p.status})` : `DOWN (${p.error || '?'})`}`).join('\n')));
  process.exit(0);
}

if (cmd === 'switch') {
  if (!sub) fail('switch <nama>');
  try { out(await switchProfile(sub)); } catch (e) { fail(e.message); }
  process.exit(0);
}

if (cmd === 'unload' || cmd === 'ps') {
  if (cmd === 'unload') {
    if (!sub) fail('unload <nama>');
    try { out(await removeProfile(sub)); } catch (e) { fail(e.message); }
    process.exit(0);
  }
  const st = await liveStatus();
  out(json ? st : (!st.profiles.length ? 'Belum ada profil.'
    : st.profiles.map((p) => `${p.active ? '*' : ' '} ${p.name}  ${p.baseUrl}  ${p.up ? `UP (${p.status})` : `DOWN (${p.error || '?'})`}`).join('\n')));
  process.exit(0);
}

if (cmd === 'mcp') {
  const servers = await loadCatalog();
  const errors = validateCatalog(servers);
  if (errors.length) fail('katalog tidak valid: ' + errors.join('; '));
  const rows = await listProbed();
  out(json ? rows : rows.map((r) => `${r.probe.toolOnPath ? '+' : 'x'} ${r.id}  [${r.license}] via ${r.runtime.tool} :: ${r.probe.note}`).join('\n'));
  process.exit(0);
}

if (cmd === 'launch') {
  const rows = detectTools();
  out(json ? rows : rows.map((t) => `${t.detected === null ? '-' : t.detected ? '+' : 'x'} ${t.id}${t.bin ? ` (bin: ${t.bin})` : ' (plugin IDE)'} :: ${t.config}`).join('\n')
    + '\n\nPOC hanya preview; --apply tidak tersedia.');
  process.exit(0);
}

if (cmd === 'tui') {
  const { runTui, canFullScreen } = await import('../lib/tui.mjs');
  if (!canFullScreen()) { console.log('(bukan TTY: fallback loop sederhana)'); }
  else { await runTui(); process.exit(0); }
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: 'poc> ' });
  console.log('Perintah: hw | ps | switch <nama> | mcp | launch | quit');
  rl.prompt();
  rl.on('line', async (line) => {
    const [c, ...rest] = line.trim().split(/\s+/);
    try {
      if (c === 'quit' || c === 'exit') return rl.close();
      if (c === 'hw') console.log(JSON.stringify(await detectHardware()));
      else if (c === 'ps') console.log(JSON.stringify(await liveStatus(), null, 1));
      else if (c === 'switch' && rest[0]) console.log(JSON.stringify(await switchProfile(rest[0])));
      else if (c === 'mcp') console.log(JSON.stringify(await listProbed(), null, 1));
      else if (c === 'launch') console.log(JSON.stringify(detectTools(), null, 1));
      else if (c === 'health' && rest[0]) console.log(JSON.stringify(await checkHealth(rest[0])));
      else console.log('tidak dikenal. Coba: hw | ps | switch <nama> | mcp | launch | quit');
    } catch (e) { console.log('Error: ' + e.message); }
    rl.prompt();
  });
  rl.on('close', () => process.exit(0));
  await new Promise(() => {});
}

console.error(`unknown command: ${cmd}\n` + HELP);
process.exit(2);
