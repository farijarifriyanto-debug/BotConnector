// POC 4+: TUI fullscreen ala opencode untuk Linux (tanpa dependensi).
// Alternate screen + raw keypress + slash menu. Semua perintah mengeksekusi
// fungsi lib yang sama dengan CLI (tidak ada tombol mati).
import { liveStatus, switchProfile, addProfile, removeProfile } from './slots.mjs';
import { detectHardware, assessFit } from './hardware.mjs';
import { loadCatalog, validateCatalog, listProbed } from './mcp.mjs';
import { detectTools } from './launcher.mjs';

export function parseLine(line) {
  const parts = String(line || '').trim().split(/\s+/).filter(Boolean);
  return { cmd: (parts[0] || '').replace(/^\//, '').toLowerCase(), args: parts.slice(1) };
}

export const SLASH = [
  { name: '/hw', desc: 'ringkasan hardware + skor fit' },
  { name: '/ps', desc: 'profil + status /health asli' },
  { name: '/switch', desc: '/switch <nama> — aktifkan profil (wajib /health UP)' },
  { name: '/add', desc: '/add <nama> <url> — daftar endpoint localhost' },
  { name: '/rm', desc: '/rm <nama> — hapus profil' },
  { name: '/mcp', desc: 'katalog MCP + probe PATH' },
  { name: '/launch', desc: 'deteksi coding tool' },
  { name: '/help', desc: 'bantuan' },
  { name: '/quit', desc: 'keluar' },
];

export function filterSlash(prefix) {
  const p = String(prefix || '').toLowerCase();
  return SLASH.filter((s) => s.name.startsWith(p));
}

async function execParsed({ cmd, args }) {
  switch (cmd) {
    case 'hw': {
      const hw = await detectHardware();
      const fit = assessFit({ kind: 'local', minRamGb: 8, recRamGb: 16, recVramGb: 6 }, hw);
      return [
        `hw: ${hw.platform}/${hw.arch} ${hw.cpu} x${hw.logicalCores} | RAM ${hw.ramGb}GB | VRAMmax ${hw.vramGb}GB`,
        `fit: ${fit.level} (${fit.label}) [${fit.confidence}] — ${fit.reason}`,
      ];
    }
    case 'ps':
    case 'profiles': {
      const st = await liveStatus();
      if (!st.profiles.length) return ['Belum ada profil. /add <nama> <url>'];
      return st.profiles.map((p) => `${p.active ? '*' : ' '} ${p.name} ${p.baseUrl} ${p.up ? `UP(${p.status})` : `DOWN(${p.error || '?'})`}`);
    }
    case 'switch': {
      if (!args[0]) return ['Pakai: /switch <nama>'];
      const r = await switchProfile(args[0]);
      return [`Aktif: ${r.active} (health UP ${r.health.status})`];
    }
    case 'add': {
      if (args.length < 2) return ['Pakai: /add <nama> <url>  (url wajib localhost)'];
      const p = await addProfile(args[0], args[1]);
      return [`Terdaftar: ${p.name} → ${p.baseUrl}`];
    }
    case 'rm':
    case 'unload': {
      if (!args[0]) return ['Pakai: /rm <nama>'];
      await removeProfile(args[0]);
      return [`Dihapus: ${args[0]}`];
    }
    case 'mcp': {
      const servers = await loadCatalog();
      const errs = validateCatalog(servers);
      if (errs.length) return ['Katalog rusak: ' + errs.join('; ')];
      return (await listProbed()).map((r) => `${r.probe.toolOnPath ? '+' : 'x'} ${r.id} [${r.license}] ${r.probe.note}`);
    }
    case 'launch':
      return detectTools().map((t) => `${t.detected === null ? '-' : t.detected ? '+' : 'x'} ${t.id} :: ${t.config}`);
    case 'help':
      return SLASH.map((s) => `${s.name} — ${s.desc}`);
    case '':
      return [];
    default:
      return [`Tidak dikenal: ${cmd}. /help untuk daftar.`];
  }
}

const ALT_ON = '\x1b[?1049h\x1b[H';
const ALT_OFF = '\x1b[?1049l';
const HIDE = '\x1b[?25l';
const SHOW = '\x1b[?25h';
const CLEAR = '\x1b[2J\x1b[H';

export function canFullScreen() {
  return Boolean(process.stdout.isTTY && process.stdin.isTTY);
}

export async function runTui() {
  const lines = ['botconnector-poc — ketik /help untuk perintah, Esc keluar'];
  try {
    const hw = await detectHardware();
    const st = await liveStatus();
    lines.push(`hw: ${hw.platform}/${hw.arch} RAM ${hw.ramGb}GB VRAMmax ${hw.vramGb}GB | profil aktif: ${st.active || '-'}`);
  } catch (e) { lines.push('init: ' + e.message); }

  let input = '';
  let cursor = 0;
  let history = [];
  let histIdx = -1;
  let menuIdx = 0;
  let busy = false;

  const menuOpen = () => input.startsWith('/');
  const menuItems = () => filterSlash(input.split(/\s+/)[0]);

  function render() {
    const W = process.stdout.columns || 80;
    const H = process.stdout.rows || 24;
    let out = CLEAR;
    out += `botconnector-poc  ${new Date().toLocaleTimeString()}\n`;
    out += '─'.repeat(W) + '\n';
    const items = menuOpen() ? menuItems() : [];
    const menuH = menuOpen() ? Math.min(items.length, 6) + 1 : 0;
    const logH = Math.max(3, H - 5 - menuH);
    const tail = lines.slice(-500).slice(-logH);
    out += tail.map((l) => l.slice(0, W)).join('\n');
    out += '\n' + '─'.repeat(W) + '\n';
    if (menuOpen()) {
      out += items.slice(0, 6).map((s, i) => `${i === menuIdx ? '>' : ' '} ${s.name}  ${s.desc}`.slice(0, W)).join('\n') + '\n';
    }
    const prompt = 'poc> ';
    const before = input.slice(0, cursor);
    const after = input.slice(cursor);
    out += prompt + before + after + '\n';
    out += 'Enter kirim · / menu · Tab pilih · Up/Down riwayat · Esc keluar';
    process.stdout.write(out);
    const cx = prompt.length + before.length + 1;
    const cy = H - 1;
    process.stdout.write(`\x1b[${cy};${Math.min(cx, W)}H`);
  }

  process.stdout.write(ALT_ON + HIDE);
  const restore = () => process.stdout.write(SHOW + ALT_OFF);
  process.on('exit', restore);

  render();
  process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdin.setEncoding('utf8');

  const submit = async () => {
    const line = input.trim();
    input = ''; cursor = 0; menuIdx = 0;
    if (!line) { render(); return; }
    history.push(line); histIdx = -1;
    const { cmd, args } = parseLine(line);
    if (cmd === 'quit' || cmd === 'exit' || cmd === 'q') { cleanup(); process.exit(0); }
    lines.push('poc> ' + line);
    busy = true; render();
    try {
      lines.push(...(await execParsed({ cmd, args })));
    } catch (e) { lines.push('Error: ' + e.message); }
    busy = false; render();
  };

  const cleanup = () => {
    try { process.stdin.setRawMode(false); } catch { /* abaikan */ }
    process.stdin.pause();
    restore();
  };
  process.on('SIGINT', () => { cleanup(); process.exit(0); });

  // Tokenisasi chunk: satu chunk bisa berisi banyak tombol (paste/pty cepat).
  // Urutan escape dikenali utuh; ESC tunggal = tombol Esc.
  function tokenize(chunk) {
    const toks = [];
    let i = 0;
    while (i < chunk.length) {
      if (chunk[i] === '\x1b' && chunk[i + 1] === '[' && 'ABCD'.includes(chunk[i + 2])) {
        toks.push(chunk.slice(i, i + 3)); i += 3; continue;
      }
      toks.push(chunk[i]); i += 1;
    }
    return toks;
  }

  function handleKey(k) {
    if (busy && k !== '\x03') return;
    if (k === '\x03' || k === '\x04') { cleanup(); process.exit(0); } // Ctrl+C/D
    if (k === '\r') { submit(); return; }
    if (k === '\x7f') { // backspace
      if (cursor > 0) { input = input.slice(0, cursor - 1) + input.slice(cursor); cursor--; menuIdx = 0; }
      render(); return;
    }
    if (k === '\x1b') { // Esc (tunggal; sequence arrow datang sebagai satu chunk)
      if (menuOpen()) { input = ''; cursor = 0; render(); } else { cleanup(); process.exit(0); }
      return;
    }
    if (k === '\x1b[A' || k === '\x1b[B') { // Up/Down
      if (menuOpen()) {
        const n = menuItems().length || 1;
        menuIdx = k === '\x1b[B' ? (menuIdx + 1) % n : (menuIdx - 1 + n) % n;
      } else if (history.length) {
        if (histIdx === -1) histIdx = history.length - 1;
        else histIdx = k === '\x1b[A' ? Math.max(0, histIdx - 1) : Math.min(history.length - 1, histIdx + 1);
        input = history[histIdx] || ''; cursor = input.length;
      }
      render(); return;
    }
    if (k === '\x1b[C') { if (cursor < input.length) cursor++; render(); return; }
    if (k === '\x1b[D') { if (cursor > 0) cursor--; render(); return; }
    if (k === '\t') { // Tab: lengkapi dari menu
      if (menuOpen()) {
        const items = menuItems();
        if (items.length) { input = items[menuIdx % items.length].name + ' '; cursor = input.length; menuIdx = 0; }
      }
      render(); return;
    }
    if (k.length === 1 && k >= ' ' && k !== '\x7f') {
      input = input.slice(0, cursor) + k + input.slice(cursor); cursor++; menuIdx = 0;
      render(); return;
    }
    // Byte tak dikenal: abaikan aman
  }

  process.stdin.on('data', (chunk) => {
    for (const k of tokenize(String(chunk))) {
      if (k === '\x03' || k === '\x04') { cleanup(); process.exit(0); }
      handleKey(k);
      if (k === '\r') return; // submit() me-render ulang; sisa chunk diabaikan
    }
  });
  await new Promise(() => {});
}
