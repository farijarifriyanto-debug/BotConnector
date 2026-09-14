// Builds dist/web/ — the exact same renderer that already works in
// `npm run desktop` (index.html, desktop.css, desktop.js, i18n.js), unchanged,
// plus one new file: web-bridge.js, which replaces Electron's
// contextBridge/ipcRenderer with plain fetch()/SSE calls against the new
// `botconnector ui` local HTTP server. desktop.js itself is never modified —
// it only ever talks to `window.botconnector`, and web-bridge.js supplies
// that same object with an HTTP transport instead of an IPC one.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const SRC = path.join(ROOT, 'desktop');
const OUT = path.join(ROOT, 'dist', 'web');

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

// Copied byte-for-byte: the same working renderer, no rewrite.
for (const file of ['desktop.css', 'desktop.js', 'i18n.js']) {
  fs.copyFileSync(path.join(SRC, file), path.join(OUT, file));
}

// index.html copied with exactly one insertion: web-bridge.js loaded before
// desktop.js so window.botconnector exists by the time desktop.js runs.
const html = fs.readFileSync(path.join(SRC, 'index.html'), 'utf8');
const marker = '<script src="desktop.js"></script>';
if (!html.includes(marker)) throw new Error('desktop/index.html: expected script tag not found, refusing to guess an injection point');
fs.writeFileSync(
  path.join(OUT, 'index.html'),
  html.replace(marker, `<script src="web-bridge.js"></script>\n${marker}`),
);

fs.copyFileSync(path.join(ROOT, 'scripts', 'web-bridge.js'), path.join(OUT, 'web-bridge.js'));

console.log(`Built dist/web/ from desktop/ (${fs.readdirSync(OUT).join(', ')})`);
