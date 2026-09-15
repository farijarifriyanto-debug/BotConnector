// POC TUI fullscreen ala opencode untuk Linux (tanpa dependensi).
// Layout: topbar | sidebar + pesan | kotak input | statusbar.
// Semua perintah mengeksekusi fungsi lib yang sama dengan CLI (tidak ada tombol mati).
import { liveStatus, switchProfile, addProfile, removeProfile } from './slots.mjs';
import { detectHardware, assessFit } from './hardware.mjs';
import { loadCatalog, validateCatalog, listProbed } from './mcp.mjs';
import { detectTools } from './launcher.mjs';
import { execCommand } from './commands.mjs';

export function parseLine(line) {
  const parts = String(line || '').trim().split(/\s+/).filter(Boolean);
  return { cmd: (parts[0] || '').replace(/^\//, '').toLowerCase(), args: parts.slice(1) };
}

export const SLASH = [
  { name: '/hw', desc: 'ringkasan hardware + skor fit' },
  { name: '/ps', desc: 'profil + status /health asli' },
  { name: '/switch', desc: '/switch [nama] — tanpa nama buka picker' },
  { name: '/add', desc: '/add <nama> <url> — daftar endpoint localhost' },
  { name: '/rm', desc: '/rm <nama> — hapus profil' },
  { name: '/mcp', desc: 'katalog MCP + probe PATH' },
  { name: '/launch', desc: 'deteksi coding tool' },
  { name: '/cloud', desc: '/cloud status|models|chat — Ollama Cloud' },
  { name: '/help', desc: 'bantuan' },
  { name: '/quit', desc: 'keluar' },
];

export function filterSlash(prefix) {
  const p = String(prefix || '').toLowerCase();
  return SLASH.filter((s) => s.name.startsWith(p));
}

// ---------- tema & gambar ----------
const C = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  border: '\x1b[38;5;238m',
  accent: '\x1b[38;5;75m',
  green: '\x1b[38;5;114m',
  red: '\x1b[38;5;203m',
  yellow: '\x1b[38;5;221m',
  muted: '\x1b[38;5;245m',
  text: '\x1b[38;5;252m',
  user: '\x1b[38;5;141m',
};

export function stripAnsi(s) {
  return String(s).replace(/\x1b\[[0-9;]*m/g, '');
}
export function visibleLen(s) {
  return stripAnsi(s).length;
}
export function padEndVis(s, w) {
  const n = w - visibleLen(s);
  return n > 0 ? s + ' '.repeat(n) : s;
}

// Bungkus kata per lebar tampak (kode ANSI tidak dihitung).
export function wrap(text, w) {
  const out = [];
  for (const raw of String(text).split('\n')) {
    const words = raw.split(/(\s+)/).filter((x) => x !== '');
    let line = '';
    const push = () => { out.push(line); line = ''; };
    if (!words.length) { out.push(''); continue; }
    for (const word of words) {
      const cand = line + word;
      if (visibleLen(cand) > w && line) { push(); if (/^\s+$/.test(word)) continue; line = word; }
      else line = cand;
      while (visibleLen(line) > w) {
        let cut = 0, vis = 0;
        const plain = stripAnsi(line);
        // potong paksa kata super panjang (tanpa ANSI di dalamnya secara praktis)
        for (const ch of plain) { if (vis >= w) break; vis++; cut += ch.length; }
        out.push(line.slice(0, cut));
        line = line.slice(cut);
        void plain;
      }
    }
    push();
  }
  return out;
}

function hline(w, left, mid, right, fill = '─') {
  return C.border + left + fill.repeat(Math.max(0, w - 2)) + right + C.reset;
}

export function canFullScreen() {
  return Boolean(process.stdout.isTTY && process.stdin.isTTY);
}

const ALT_ON = '\x1b[?1049h\x1b[H';
const ALT_OFF = '\x1b[?1049l';
const HIDE = '\x1b[?25l';
const SHOW = '\x1b[?25h';
const CLEAR = '\x1b[2J\x1b[H';

export async function runTui() {
  const msgs = []; // {role:'user'|'agent'|'error', text}
  let sidebar = [];
  let mcpCount = 0;
  let toolCount = 0;
  let showSide = (process.stdout.columns || 80) >= 96;
  let input = '';
  let cursor = 0;
  let history = [];
  let histIdx = -1;
  let menuIdx = 0;
  let busy = false;
  let overlay = null; // {type:'help'} | {type:'picker', items, idx}
  let scroll = 0; // 0 = ikuti bawah; >0 = geser ke atas sebanyak baris

  async function refreshSide() {
    try {
      const st = await liveStatus();
      sidebar = st.profiles.map((p) => ({ name: p.name, active: st.active === p.name, up: p.up }));
    } catch { sidebar = []; }
    try { mcpCount = (await loadCatalog()).length; } catch { mcpCount = 0; }
    try { toolCount = detectTools().filter((t) => t.detected).length; } catch { toolCount = 0; }
  }
  await refreshSide();

  let hwLine = '';
  try {
    const hw = await detectHardware();
    hwLine = `${hw.platform}/${hw.arch} · RAM ${hw.ramGb}GB · VRAM ${hw.vramGb}GB`;
  } catch (e) { hwLine = 'hw: ' + e.message; }
  msgs.push({ role: 'agent', text: `Selamat datang di ${C.bold}botconnector-poc${C.reset}. Ketik ${C.accent}/help${C.reset} untuk perintah, ${C.accent}?${C.reset} bantuan tombol.` });

  const menuOpen = () => !overlay && input.startsWith('/');
  const menuItems = () => filterSlash(input.split(/\s+/)[0]);

  function renderMsgLines(W) {
    const out = [];
    for (const m of msgs) {
      if (m.role === 'user') {
        for (const wl of wrap(m.text, W - 4)) out.push(`${C.user}❯${C.reset} ${C.text}${wl}${C.reset}`);
      } else if (m.role === 'error') {
        for (const wl of wrap(m.text, W - 4)) out.push(`${C.red}✖ ${wl}${C.reset}`);
      } else {
        for (const wl of wrap(m.text, W - 2)) out.push(wl || '');
      }
      out.push('');
    }
    if (out.length && out[out.length - 1] === '') out.pop();
    return out;
  }

  function render() {
    const W = process.stdout.columns || 80;
    const H = process.stdout.rows || 24;
    const sideW = showSide ? 26 : 0;
    const mainW = W - sideW;
    let out = CLEAR;

    // topbar
    out += `${C.bold}${C.accent}● botconnector-poc${C.reset}${C.dim}  ${hwLine}${C.reset}\n`;

    const inputH = 3;
    const statusH = 1;
    const bodyH = Math.max(4, H - 2 - inputH - statusH);
    const msgLines = renderMsgLines(mainW - 4);
    const viewH = bodyH;
    const maxScroll = Math.max(0, msgLines.length - viewH);
    if (scroll > maxScroll) scroll = maxScroll;
    const start = Math.max(0, msgLines.length - viewH - scroll);
    const visible = msgLines.slice(start, start + viewH);
    while (visible.length < viewH) visible.push('');

    const sideLines = [];
    if (showSide) {
      sideLines.push(`${C.bold}PROFIL${C.reset}`);
      if (!sidebar.length) sideLines.push(`${C.dim}(kosong)${C.reset}`);
      for (const p of sidebar.slice(0, Math.max(0, bodyH - 6))) {
        sideLines.push(`${p.active ? `${C.green}●` : `${C.muted}○`}${C.reset} ${padEndVis(p.name, 14)} ${p.up ? `${C.green}up${C.reset}` : `${C.red}dn${C.reset}`}`);
      }
      sideLines.push('');
      sideLines.push(`${C.bold}MCP${C.reset} ${mcpCount}  ${C.bold}TOOLS${C.reset} ${toolCount}`);
      while (sideLines.length < bodyH) sideLines.push('');
    }

    for (let r = 0; r < bodyH; r++) {
      const left = padEndVis(visible[r] || '', mainW - 2);
      if (showSide) out += ` ${left}${C.border}│${C.reset} ${padEndVis(sideLines[r] || '', sideW - 3)}\n`;
      else out += ` ${left}\n`;
    }

    // kotak input
    const title = busy ? ' bekerja… ' : ' perintah ';
    out += hline(mainW, '╭', '─', '╮') + '\n';
    const prompt = '❯ ';
    const maxIn = mainW - 4 - prompt.length;
    let shown = input;
    let curVis = cursor;
    if (visibleLen(input) > maxIn) {
      // geser agar kursor tampak
      let cut = Math.max(0, cursor - maxIn + 1);
      shown = '…' + input.slice(cut);
      curVis = cursor - cut + 1;
    }
    out += `${C.border}│${C.reset} ${C.muted}${prompt}${C.reset}${shown}${' '.repeat(Math.max(0, mainW - 4 - prompt.length - visibleLen(shown)))}${C.border}│${C.reset}\n`;
    out += hline(mainW, '╰', '─', '╯') + '\n';

    // statusbar
    const st = `${C.dim}Enter kirim · / menu · Tab pilih · ? bantuan · Esc keluar${scroll ? ` · scroll +${scroll}` : ''}${C.reset}`;
    out += padEndVis(st, W) + '\n';

    // overlay: slash menu / picker / help
    if (overlay?.type === 'help') {
      const rows = [
        `${C.bold}TOMBOL${C.reset}`,
        'Enter kirim · Esc tutup/keluar · Tab lengkapi slash',
        'Up/Down riwayat & navigasi menu · PgUp/PgDn geser pesan',
        'Ctrl+C keluar paksa · /switch (tanpa nama) buka picker profil',
        '', `${C.bold}PERINTAH${C.reset}`,
        ...SLASH.map((s) => `${C.accent}${s.name}${C.reset} — ${s.desc}`),
      ];
      out += overlayBox(W, H, rows);
    } else if (overlay?.type === 'picker') {
      const rows = [`${C.bold}PILIH PROFIL (Enter aktifkan, Esc batal)${C.reset}`, ''];
      overlay.items.forEach((p, i) => {
        rows.push(`${i === overlay.idx ? `${C.green}>` : ' '}${C.reset} ${p.active ? `${C.green}●` : '○'} ${C.bold}${p.name}${C.reset} ${C.dim}${p.baseUrl}${C.reset} ${p.up ? `${C.green}UP${C.reset}` : `${C.red}DOWN${C.reset}`}`);
      });
      out += overlayBox(W, H, rows);
    } else if (menuOpen()) {
      const items = menuItems().slice(0, 6);
      const rows = items.map((s, i) => `${i === (menuIdx % Math.max(1, items.length)) ? `${C.green}>` : ' '}${C.reset} ${C.accent}${s.name}${C.reset}  ${C.dim}${s.desc}${C.reset}`);
      if (rows.length) out += overlayBox(W, H, rows, true);
    }

    process.stdout.write(out);
    // kursor ke dalam kotak input
    const cx = 3 + prompt.length + curVis;
    const cy = H - statusH;
    process.stdout.write(`\x1b[${cy};${Math.min(cx, W)}H`);
  }

  function overlayBox(W, H, rows, bottom = false) {
    const w = Math.min(W - 6, Math.max(...rows.map((r) => visibleLen(r))) + 6);
    const x = W - w - 2;
    let s = '';
    rows.slice(0, H - 6).forEach((r) => {
      s += `\x1b[s\x1b[${1};${x}H${C.border}│${C.reset} ${padEndVis(r, w - 4)}${C.border}│${C.reset}\x1b[u`;
    });
    void bottom;
    return s;
  }

  process.stdout.write(ALT_ON + HIDE);
  const restore = () => process.stdout.write(SHOW + ALT_OFF);
  process.on('exit', restore);
  const cleanup = () => {
    try { process.stdin.setRawMode(false); } catch { /* abaikan */ }
    process.stdin.pause();
    restore();
  };
  process.on('SIGINT', () => { cleanup(); process.exit(0); });
  process.on('SIGWINCH', () => render());

  // streaming: konten nyata, ditampilkan bertahap
  async function streamAgent(text) {
    const m = { role: 'agent', text: '' };
    msgs.push(m);
    const chunks = String(text).match(/[\s\S]{1,120}/g) || [];
    for (const ch of chunks) {
      m.text += ch;
      render();
      await new Promise((r) => setTimeout(r, 15));
    }
  }

  async function submit() {
    const line = input.trim();
    input = ''; cursor = 0; menuIdx = 0; scroll = 0;
    if (overlay?.type === 'help') overlay = null;
    if (!line) { render(); return; }
    history.push(line); histIdx = -1;
    const { cmd, args } = parseLine(line);
    if (cmd === 'quit' || cmd === 'exit' || cmd === 'q') { cleanup(); process.exit(0); }
    msgs.push({ role: 'user', text: line });
    if (msgs.length > 200) msgs.splice(0, msgs.length - 200);
    busy = true; render();
    try {
      const res = await execCommand({ cmd, args });
      for (const r of res) {
        if (r.role === 'picker') {
          const st = await liveStatus();
          if (!st.profiles.length) { msgs.push({ role: 'agent', text: 'Belum ada profil. /add <nama> <url>' }); }
          else overlay = { type: 'picker', items: st.profiles, idx: Math.max(0, st.profiles.findIndex((p) => p.active)) };
        } else if (r.role === 'error') {
          msgs.push(r);
        } else {
          await streamAgent(r.text);
        }
      }
      await refreshSide();
    } catch (e) { msgs.push({ role: 'error', text: e.message }); }
    busy = false; render();
  }

  function tokenize(chunk) {
    const toks = [];
    let i = 0;
    while (i < chunk.length) {
      if (chunk[i] === '\x1b' && chunk[i + 1] === '[' && 'ABCD'.includes(chunk[i + 2])) {
        toks.push(chunk.slice(i, i + 3)); i += 3; continue;
      }
      if (chunk[i] === '\x1b' && chunk[i + 1] === '[' && (chunk[i + 2] === '5' || chunk[i + 2] === '6') && chunk[i + 3] === '~') {
        toks.push(chunk.slice(i, i + 4)); i += 4; continue; // PgUp \x1b[5~ / PgDn \x1b[6~
      }
      toks.push(chunk[i]); i += 1;
    }
    return toks;
  }

  async function handleKey(k) {
    if (busy && k !== '\x03') return;
    if (k === '\r') { await submit(); return; }
    if (k === '\x7f') {
      if (cursor > 0) { input = input.slice(0, cursor - 1) + input.slice(cursor); cursor--; menuIdx = 0; }
      render(); return;
    }
    if (k === '\x1b') {
      if (overlay) { overlay = null; render(); }
      else if (menuOpen()) { input = ''; cursor = 0; render(); }
      else { cleanup(); process.exit(0); }
      return;
    }
    if (k === '\x1b[A' || k === '\x1b[B') {
      const dir = k === '\x1b[B' ? 1 : -1;
      if (overlay?.type === 'picker') {
        const n = overlay.items.length || 1;
        overlay.idx = (overlay.idx + dir + n) % n;
      } else if (menuOpen()) {
        const n = menuItems().length || 1;
        menuIdx = (menuIdx + dir + n) % n;
      } else if (history.length) {
        if (histIdx === -1) histIdx = history.length - 1;
        else histIdx = Math.min(history.length - 1, Math.max(0, histIdx + dir));
        input = history[histIdx] || ''; cursor = input.length;
      }
      render(); return;
    }
    if (k === '\x1b[5~') { scroll += 5; render(); return; } // PgUp
    if (k === '\x1b[6~') { scroll = Math.max(0, scroll - 5); render(); return; } // PgDn
    if (k === '\x1b[C') { if (cursor < input.length) cursor++; render(); return; }
    if (k === '\x1b[D') { if (cursor > 0) cursor--; render(); return; }
    if (k === '\t') {
      if (overlay?.type === 'picker') { /* Enter untuk pilih */ }
      else if (menuOpen()) {
        const items = menuItems();
        if (items.length) { input = items[menuIdx % items.length].name + ' '; cursor = input.length; menuIdx = 0; }
      }
      render(); return;
    }
    if (k === '?' && !input && !overlay) { overlay = { type: 'help' }; render(); return; }
    if (overlay?.type === 'help') { overlay = null; render(); return; }
    if (k.length === 1 && k >= ' ' && k !== '\x7f') {
      input = input.slice(0, cursor) + k + input.slice(cursor); cursor++; menuIdx = 0;
      render(); return;
    }
  }

  render();
  process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', async (chunk) => {
    for (const k of tokenize(String(chunk))) {
      if (k === '\x03' || k === '\x04') { cleanup(); process.exit(0); }
      if (overlay?.type === 'picker') {
        if (k === '\x1b[A' || k === '\x1b[B') { await handleKey(k); continue; }
        if (k === '\r') {
          const pick = overlay.items[overlay.idx];
          overlay = null;
          if (pick) {
            busy = true; render();
            try {
              const r = await switchProfile(pick.name);
              msgs.push({ role: 'agent', text: `${C.green}Aktif: ${r.active}${C.reset} (health UP ${r.health.status})` });
              await refreshSide();
            } catch (e) { msgs.push({ role: 'error', text: e.message }); }
            busy = false;
          }
          render(); continue;
        }
        if (k === '\x1b' || k === '\x07') { overlay = null; render(); continue; }
        continue; // kunci lain diabaikan saat picker terbuka
      }
      await handleKey(k);
      if (k === '\r') return;
    }
  });
  await new Promise(() => {});
}
