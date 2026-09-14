// Assembles the Portable Web App deliverable: builds the web UI, the SEA
// core, and the native launcher (in that dependency order), stages them
// under dist-portable/ with their FINAL names, and zips the result. Nothing
// else goes in the zip — no installer, no wizard, no node_modules, no
// source tree, matching the explicit "just the two exes + a short README"
// scope for this POC.
import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import yazl from 'yazl';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const STAGE = path.join(ROOT, 'dist-portable');
// Pass a version string as the first CLI arg to override, e.g.:
//   node scripts/build-portable.mjs v0.5.0-beta1
// Defaults to package.json's version so this never silently drifts from it
// (bin/botconnector.mjs's --version and desktop/index.html's badge are the
// other two places this same version is asserted — see VERSION_CONSISTENCY
// in the RC acceptance report).
const PKG_VERSION = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')).version;
const VERSION = process.argv[2] || `v${PKG_VERSION}`;
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

const README = `BotConnector AI (${VERSION})

1. Extract this ZIP.
2. Double-click BotConnector.exe.
3. BotConnector opens in your default browser.

No installation is required. Keep BotConnector.exe and
botconnector-core.exe together in the same folder.

Data is stored in your Windows user profile, under
%LOCALAPPDATA%\\BotConnector AI\\ — nothing is written beside these files.

To stop BotConnector: click "Quit BotConnector" in the app's sidebar.

If Windows shows a security warning for this beta, verify that you
downloaded the file from the official BotConnector source before
continuing. Do not disable Windows Defender or SmartScreen to get past it.
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

console.log('[4/4] writing SHA256SUMS.txt...');
const hash = crypto.createHash('sha256').update(fs.readFileSync(ZIP_PATH)).digest('hex');
const sumsPath = path.join(ROOT, `BotConnector-Portable-${VERSION}.zip.sha256`);
fs.writeFileSync(sumsPath, `${hash}  BotConnector-Portable-${VERSION}.zip\n`);

const sizeMb = (fs.statSync(ZIP_PATH).size / 1e6).toFixed(1);
console.log(`\nDone.`);
console.log(`Artifact: ${ZIP_PATH} (${sizeMb} MB)`);
console.log(`Checksum: ${sumsPath}`);
console.log(`SHA256:   ${hash}`);
console.log(`Staged folder (unzipped, for quick local testing): ${STAGE}`);
