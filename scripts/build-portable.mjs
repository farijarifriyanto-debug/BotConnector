// Assembles the Portable Web App deliverable: builds the web UI, the SEA
// core, and the native launcher (in that dependency order), stages them
// under dist-portable/ with their FINAL names, and zips the result. Nothing
// else goes in the zip — no installer, no wizard, no node_modules, no
// source tree, matching the explicit "just the two exes + a short README"
// scope for this POC.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import yazl from 'yazl';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const STAGE = path.join(ROOT, 'dist-portable');
const VERSION = 'v0.5-poc';
const ZIP_PATH = path.join(ROOT, `BotConnector-Portable-${VERSION}.zip`);

console.log('[1/4] building web UI, SEA core, and native launcher...');
for (const script of ['build-web.mjs', 'build-sea.mjs', 'build-launcher.mjs']) {
  execFileSync(process.execPath, [path.join(ROOT, 'scripts', script)], { cwd: ROOT, stdio: 'inherit' });
}

console.log('[2/4] staging dist-portable/ with final names...');
fs.rmSync(STAGE, { recursive: true, force: true });
fs.mkdirSync(STAGE, { recursive: true });
// Final names differ from the build-staging names in dist-sea/ specifically
// to dodge the case-insensitive-filesystem collision documented in
// scripts/build-launcher.mjs (BotConnector.exe / botconnector.exe would be
// the same file on NTFS) — dist-portable/ never holds both spellings.
fs.copyFileSync(path.join(ROOT, 'dist-sea', 'botconnector.exe'), path.join(STAGE, 'botconnector-core.exe'));
fs.copyFileSync(path.join(ROOT, 'dist-sea', 'botconnector-launcher.exe'), path.join(STAGE, 'BotConnector.exe'));

const README = `BotConnector AI — Portable (${VERSION})
========================================

This is a portable, no-install build. It runs entirely from this folder
and writes its settings under %LOCALAPPDATA%\\BotConnector AI\\ — it never
writes anything beside these two files, and it needs no administrator
rights, no registry changes, and no Program Files entry.

To run:
  Double-click BotConnector.exe

What happens:
  BotConnector.exe silently starts botconnector-core.exe, which runs a
  small local web server on 127.0.0.1 (localhost only — nothing is ever
  exposed to your network) and then opens the app in your default browser.
  Running BotConnector.exe again while it's already open will just open a
  new browser tab to the running instance instead of starting a second one.

To stop:
  Close the browser tab and end the "botconnector-core" process from Task
  Manager, or simply sign out / restart — nothing is installed as a
  background service and nothing needs manual cleanup.

Keep both files together
  BotConnector.exe needs botconnector-core.exe in the same folder.

This is a proof-of-concept build (v0.5-poc). The full-featured Electron
desktop app remains available separately; this portable build is an
alternate, lighter-weight way to run the same local + cloud AI runtime
through your browser instead of a bundled app window.
`;
fs.writeFileSync(path.join(STAGE, 'README.txt'), README);

console.log('[3/4] zipping...');
await new Promise((resolve, reject) => {
  const zipfile = new yazl.ZipFile();
  for (const name of fs.readdirSync(STAGE)) {
    zipfile.addFile(path.join(STAGE, name), `BotConnector-Portable/${name}`);
  }
  zipfile.outputStream.pipe(fs.createWriteStream(ZIP_PATH)).on('close', resolve).on('error', reject);
  zipfile.end();
});

console.log('[4/4] done.');
const sizeMb = (fs.statSync(ZIP_PATH).size / 1e6).toFixed(1);
console.log(`Artifact: ${ZIP_PATH} (${sizeMb} MB)`);
console.log(`Staged folder (unzipped, for quick local testing): ${STAGE}`);
