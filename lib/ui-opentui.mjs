// TUI di atas @opentui/core — stack yang sama dengan opencode
// (packages/tui memakai @opentui/core + @opentui/solid).
// Layout ala rute home opencode: header | pesan | input berbingkai | statusbar,
// dengan overlay Select untuk picker profil dan Box untuk help.
// Dijalankan dengan bun:  bun bin/poc-ui.mjs
import { createCliRenderer, BoxRenderable, TextRenderable, SelectRenderable, SelectRenderableEvents } from '@opentui/core';
import { parseLine, filterSlash, SLASH, wrap } from './tui.mjs';
import { execCommand } from './commands.mjs';
import { liveStatus, switchProfile } from './slots.mjs';
import { detectHardware } from './hardware.mjs';
import { loadCatalog } from './mcp.mjs';
import { detectTools } from './launcher.mjs';

const T = {
  accent: '#4DA3FF',
  green: '#7FDB8A',
  red: '#F26D6D',
  yellow: '#E5C07B',
  muted: '#8A8A8A',
  text: '#E8E8E8',
  user: '#B48CFF',
  border: '#3A3A3A',
};

export async function runUi() {
  const renderer = await createCliRenderer({ exitOnCtrlC: true, targetFps: 30 });

  const root = new BoxRenderable(renderer, { flexDirection: 'column', flexGrow: 1 });
  const header = new TextRenderable(renderer, { content: '● botconnector-poc', fg: T.accent });
  const msgBox = new BoxRenderable(renderer, { flexDirection: 'column', flexGrow: 1, paddingLeft: 1, paddingRight: 1, overflow: 'hidden' });
  const slashBox = new BoxRenderable(renderer, { flexDirection: 'column', paddingLeft: 3 });
  const inputBox = new BoxRenderable(renderer, {
    borderStyle: 'rounded', borderColor: T.border, title: 'perintah', titleAlignment: 'left',
    paddingLeft: 1, paddingRight: 1, height: 3,
  });
  const inputText = new TextRenderable(renderer, { content: '' });
  const statusBar = new TextRenderable(renderer, { content: '', fg: T.muted });
  inputBox.add(inputText);
  root.add(header);
  root.add(msgBox);
  root.add(slashBox);
  root.add(inputBox);
  root.add(statusBar);
  renderer.root.add(root);

  const msgs = []; // {role, text}
  let profiles = [];
  let mcpCount = 0;
  let toolCount = 0;
  let hwLine = '';
  let input = '';
  let cursor = 0;
  let history = [];
  let histIdx = -1;
  let menuIdx = 0;
  let busy = false;
  let scroll = 0;
  let mode = 'input'; // input | select | help
  let selectNode = null;

  async function refreshMeta() {
    try {
      const hw = await detectHardware();
      hwLine = `${hw.platform}/${hw.arch} · RAM ${hw.ramGb}GB · VRAM ${hw.vramGb}GB`;
    } catch { hwLine = ''; }
    try { profiles = (await liveStatus()).profiles; } catch { profiles = []; }
    try { mcpCount = (await loadCatalog()).length; } catch { mcpCount = 0; }
    try { toolCount = detectTools().filter((t) => t.detected).length; } catch { toolCount = 0; }
  }
  await refreshMeta();
  msgs.push({ role: 'agent', text: 'Selamat datang. /help untuk perintah. /switch (tanpa nama) membuka picker profil.' });

  const msgKids = [];
  const slashKids = [];
  function clearKids(box, arr) {
    for (const k of arr.splice(0)) { try { box.remove(k); } catch { /* abaikan */ } }
  }
  const termW = () => renderer.terminal?.width || 80;

  function paint() {
    const W = termW();
    header.content = `● botconnector-poc  ${hwLine}`;
    // pesan: bungkus manual per lebar, tampilkan ekor
    const bodyH = Math.max(4, (renderer.terminal?.height || 24) - 10);
    const flat = [];
    for (const m of msgs) {
      if (m.role === 'user') for (const l of wrap(m.text, W - 6)) flat.push({ fg: T.user, text: '❯ ' + l });
      else if (m.role === 'error') for (const l of wrap(m.text, W - 6)) flat.push({ fg: T.red, text: '✖ ' + l });
      else for (const l of wrap(m.text, W - 4)) flat.push({ fg: T.text, text: l });
      flat.push({ fg: T.text, text: '' });
    }
    if (flat.length && flat[flat.length - 1].text === '') flat.pop();
    const maxScroll = Math.max(0, flat.length - bodyH);
    scroll = Math.min(scroll, maxScroll);
    const slice = flat.slice(Math.max(0, flat.length - bodyH - scroll), flat.length - scroll || undefined);
    // bangun ulang anak msgBox
    clearKids(msgBox, msgKids);
    for (const l of slice.slice(-bodyH)) { const n = new TextRenderable(renderer, { content: l.text, fg: l.fg }); msgKids.push(n); msgBox.add(n); }
    // popup slash
    clearKids(slashBox, slashKids);
    if (mode === 'input' && input.startsWith('/')) {
      const items = filterSlash(input.split(/\s+/)[0]).slice(0, 6);
      items.forEach((s, i) => {
        const n = new TextRenderable(renderer, {
          content: `${i === (menuIdx % Math.max(1, items.length)) ? '>' : ' '} ${s.name}  ${s.desc}`,
          fg: i === (menuIdx % Math.max(1, items.length)) ? T.green : T.muted,
        });
        slashKids.push(n); slashBox.add(n);
      });
    }
    const shown = input.slice(0, cursor) + '▌' + input.slice(cursor);
    inputText.content = shown;
    inputBox.title = busy ? 'bekerja…' : 'perintah '; // lebar tetap: title dinamis menyisakan sel basi
    const active = profiles.find((p) => p.active);
    statusBar.content = `Enter kirim · / menu · Tab pilih · Esc keluar · aktif:${active ? active.name : '-'} mcp:${mcpCount} tools:${toolCount}${scroll ? ` +${scroll}` : ''}`;
  }

  async function streamAgent(text) {
    const m = { role: 'agent', text: '' };
    msgs.push(m);
    for (const ch of String(text).match(/[\s\S]{1,120}/g) || []) {
      m.text += ch;
      paint();
      await new Promise((r) => setTimeout(r, 15));
    }
  }

  function openPicker() {
    if (!profiles.length) { msgs.push({ role: 'agent', text: 'Belum ada profil. /add <nama> <url>' }); paint(); return; }
    mode = 'select';
    const box = new BoxRenderable(renderer, {
      borderStyle: 'rounded', borderColor: T.accent, title: 'pilih profil (Enter aktifkan, Esc batal)',
      width: 60, height: Math.min(12, profiles.length + 4), padding: 1,
    });
    selectNode = new SelectRenderable(renderer, {
      id: 'profile-picker',
      width: 54, height: profiles.length + 1,
      options: profiles.map((p) => ({ name: `${p.active ? '●' : '○'} ${p.name}`, description: `${p.baseUrl} · ${p.up ? 'UP' : 'DOWN'}` })),
    });
    selectNode.on(SelectRenderableEvents.ITEM_SELECTED, async (index) => {
      const pick = profiles[index];
      closeOverlay();
      if (!pick) return;
      busy = true; paint();
      try {
        const r = await switchProfile(pick.name);
        msgs.push({ role: 'agent', text: `Aktif: ${r.active} (health UP ${r.health.status})` });
        await refreshMeta();
      } catch (e) { msgs.push({ role: 'error', text: e.message }); }
      busy = false; paint();
    });
    box.add(selectNode);
    root.add(box);
    selectNode.focus();
    paint();
  }

  function openHelp() {
    mode = 'help';
    const box = new BoxRenderable(renderer, {
      borderStyle: 'rounded', borderColor: T.accent, title: 'bantuan',
      width: 64, height: SLASH.length + 8, padding: 1, flexDirection: 'column',
    });
    box.add(new TextRenderable(renderer, {
      content: 'Enter kirim · Esc tutup/keluar · Tab lengkapi slash\nUp/Down riwayat & menu · /switch tanpa nama = picker' + '\n\n' + SLASH.map((s) => `${s.name} — ${s.desc}`).join('\n'),
      fg: T.text,
    }));
    box._helpBox = true;
    root.add(box);
    paint();
  }

  function closeOverlay() {
    mode = 'input';
    // hapus box overlay terakhir (picker/help)
    const kids = [...(root.children || [])];
    for (let i = kids.length - 1; i >= 0; i--) {
      const k = kids[i];
      if (k !== header && k !== msgBox && k !== slashBox && k !== inputBox && k !== statusBar) {
        try { root.remove?.(k); } catch { /* abaikan */ }
        break;
      }
    }
    selectNode = null;
    paint();
  }

  async function submit() {
    const line = input.trim();
    input = ''; cursor = 0; menuIdx = 0; scroll = 0;
    if (!line) { paint(); return; }
    history.push(line); histIdx = -1;
    const { cmd, args } = parseLine(line);
    if (cmd === 'quit' || cmd === 'exit' || cmd === 'q') { renderer.destroy(); process.exit(0); }
    msgs.push({ role: 'user', text: line });
    if (msgs.length > 200) msgs.splice(0, msgs.length - 200);
    busy = true; paint();
    try {
      for (const r of await execCommand({ cmd, args })) {
        if (r.role === 'picker') openPicker();
        else if (r.role === 'error') msgs.push(r);
        else await streamAgent(r.text);
      }
      await refreshMeta();
    } catch (e) { msgs.push({ role: 'error', text: e.message }); }
    busy = false; paint();
  }

  function completeSlash() {
    const items = filterSlash(input.split(/\s+/)[0]);
    if (items.length) { input = items[menuIdx % items.length].name + ' '; cursor = input.length; menuIdx = 0; }
  }

  renderer.keyInput.on('keypress', async (key) => {
    const name = key.name || '';
    if (name === 'escape') {
      if (mode !== 'input') closeOverlay();
      else { renderer.destroy(); process.exit(0); }
      return;
    }
    if (mode === 'help') { closeOverlay(); return; }
    if (mode === 'select') return; // navigasi milik Select
    if (busy) return;
    if (name === 'enter' || name === 'return' || name === 'linefeed') { await submit(); return; }
    if (name === 'backspace') {
      if (cursor > 0) { input = input.slice(0, cursor - 1) + input.slice(cursor); cursor--; menuIdx = 0; }
      paint(); return;
    }
    if (name === 'up' || name === 'down') {
      const dir = name === 'down' ? 1 : -1;
      if (input.startsWith('/')) {
        const n = filterSlash(input.split(/\s+/)[0]).length || 1;
        menuIdx = (menuIdx + dir + n) % n;
      } else if (history.length) {
        histIdx = histIdx === -1 ? history.length - 1 : Math.min(history.length - 1, Math.max(0, histIdx + dir));
        input = history[histIdx] || ''; cursor = input.length;
      }
      paint(); return;
    }
    if (name === 'left') { if (cursor > 0) cursor--; paint(); return; }
    if (name === 'right') { if (cursor < input.length) cursor++; paint(); return; }
    if (name === 'tab') { completeSlash(); paint(); return; }
    if (key.text && key.text.length === 1 && key.text >= ' ' && !key.ctrl && !key.meta) {
      input = input.slice(0, cursor) + key.text + input.slice(cursor); cursor++; menuIdx = 0;
      paint();
    } else if (typeof name === 'string' && name.length === 1 && name >= ' ' && !key.ctrl && !key.meta) {
      input = input.slice(0, cursor) + name + input.slice(cursor); cursor++; menuIdx = 0;
      paint();
    }
  });

  paint();
  await new Promise(() => {});
}
