// Builds botconnector.exe as a Node.js Single Executable Application (SEA).
// This is the CLI/TUI's ONLY packaging mechanism — no Electron involved at
// all, so it cannot touch (or be confused with) the Desktop app's hardened
// fuses. The output is Node's own binary with one bundled script injected;
// it runs ONLY that fixed entrypoint, nothing else.
import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const OUT_DIR = path.join(ROOT, 'dist-sea');
const BUNDLE = path.join(OUT_DIR, 'bundle.cjs');
const BLOB = path.join(OUT_DIR, 'sea-prep.blob');
const SEA_CONFIG = path.join(OUT_DIR, 'sea-config.json');
// Windows -> botconnector.exe (PE), Linux -> botconnector (ELF, no
// extension). Never reuse one platform's SEA binary on the other — each
// embeds process.execPath's actual platform-native node binary.
const EXE = path.join(OUT_DIR, process.platform === 'win32' ? 'botconnector.exe' : 'botconnector');
const WEB_DIR = path.join(ROOT, 'dist', 'web');

fs.rmSync(OUT_DIR, { recursive: true, force: true });
fs.mkdirSync(OUT_DIR, { recursive: true });

if (!fs.existsSync(path.join(WEB_DIR, 'index.html'))) {
  console.error(`dist/web is missing (${WEB_DIR}). Run: npm run build:web (or use npm run build:sea, which does this first).`);
  process.exit(1);
}
// Auto-enumerate dist/web/** into the SEA's embedded asset table so the
// portable `botconnector ui` server can serve the web UI from inside the
// single exe, with no separate files shipped alongside it. Keys are
// "web/<relative-path>" — bin/botconnector.mjs's getAsset() strips the
// "web/" prefix when looking a path up, matching webui/server.cjs's
// getAsset(relativePath) contract.
function collectAssets(dir, base = '') {
  const assets = {};
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const rel = base ? `${base}/${entry.name}` : entry.name;
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) Object.assign(assets, collectAssets(abs, rel));
    else assets[`web/${rel}`] = abs;
  }
  return assets;
}
const webAssets = collectAssets(WEB_DIR);

console.log('[1/5] bundling bin/botconnector.mjs -> single CommonJS file...');
await build({
  entryPoints: [path.join(ROOT, 'bin', 'botconnector.mjs')],
  bundle: true,
  platform: 'node',
  target: 'node24',
  format: 'cjs',
  outfile: BUNDLE,
  // Nothing external: the whole dependency graph (agent/, tui/, runtime/,
  // yauzl, pend, registry/models.json) is inlined into one file so the
  // shipped executable needs no node_modules, no source checkout.
  external: [],
  minify: false,
  logLevel: 'info',
  // No import.meta.url shim needed: bin/botconnector.mjs uses only static
  // ESM imports now (no createRequire), and scripts/doctor.mjs guards its
  // own import.meta.url use defensively for exactly this bundled context.
});
console.log(`    bundle size: ${(fs.statSync(BUNDLE).size / 1e6).toFixed(2)}MB`);

console.log(`[2/5] writing sea-config.json (embedding ${Object.keys(webAssets).length} web UI assets from dist/web/)...`);
fs.writeFileSync(SEA_CONFIG, JSON.stringify({
  main: 'bundle.cjs',
  output: 'sea-prep.blob',
  disableExperimentalSEAWarning: true,
  useSnapshot: false,
  useCodeCache: false,
  // Security-critical: "none" makes Node IGNORE the NODE_OPTIONS env var
  // (and --node-options) entirely for this executable, so it can't be used
  // to inject an arbitrary --require into the CLI. Default is "env", which
  // does NOT block this — verified live (NODE_OPTIONS=--require=evil.js
  // executed injected code before this fix).
  execArgvExtension: 'none',
  assets: webAssets,
}, null, 2));

console.log('[3/5] generating SEA blob (node --experimental-sea-config)...');
execFileSync(process.execPath, ['--experimental-sea-config', 'sea-config.json'], { cwd: OUT_DIR, stdio: 'inherit' });

console.log(`[4/5] copying node runtime -> ${path.basename(EXE)}...`);
fs.copyFileSync(process.execPath, EXE);
if (process.platform === 'win32') { try { execFileSync('signtool', ['remove', '/s', EXE], { stdio: 'ignore' }); } catch { /* not signed yet on Windows, fine */ } }
else { try { fs.chmodSync(EXE, 0o755); } catch {} }

console.log('[5/5] injecting blob via postject...');
execFileSync(process.execPath, [
  path.join(ROOT, 'node_modules', 'postject', 'dist', 'cli.js'),
  EXE, 'NODE_SEA_BLOB', BLOB,
  '--sentinel-fuse', 'NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2',
], { stdio: 'inherit' });

console.log(`\nDone: ${EXE}`);
