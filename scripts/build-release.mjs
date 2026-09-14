// Builds the platform-native release artifact per the cross-platform
// architecture spec: dist/windows-x64/ or dist/linux-x64/, then a single
// archive (zip on Windows, tar.gz on Linux) with matching SHA256. Run this
// ON the target platform — a SEA binary embeds that platform's own node
// runtime and cannot be cross-built (see scripts/build-sea.mjs).
import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const win = process.platform === 'win32';
const PKG_VERSION = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')).version;
const VERSION = process.argv[2] || `v${PKG_VERSION}`;
const platformDir = win ? 'windows-x64' : 'linux-x64';
const STAGE = path.join(ROOT, 'dist', platformDir);
const artifactName = win ? `BotConnector-Windows-x64-${VERSION}.zip` : `BotConnector-Linux-x64-${VERSION}.tar.gz`;
const ARTIFACT_PATH = path.join(ROOT, artifactName);

console.log(`[1/4] building web UI + SEA core${win ? ' + native launcher' : ''} for ${platformDir}...`);
const buildSteps = win ? ['build-web.mjs', 'build-sea.mjs', 'build-launcher.mjs'] : ['build-web.mjs', 'build-sea.mjs'];
for (const script of buildSteps) {
  execFileSync(process.execPath, [path.join(ROOT, 'scripts', script)], { cwd: ROOT, stdio: 'inherit' });
}

console.log(`[2/4] staging dist/${platformDir}/...`);
fs.rmSync(STAGE, { recursive: true, force: true });
fs.mkdirSync(STAGE, { recursive: true });
if (win) {
  // Final names differ from the build-staging names in dist-sea/
  // specifically to dodge the case-insensitive-filesystem collision
  // documented in scripts/build-launcher.mjs.
  fs.copyFileSync(path.join(ROOT, 'dist-sea', 'botconnector.exe'), path.join(STAGE, 'botconnector-core.exe'));
  fs.copyFileSync(path.join(ROOT, 'dist-sea', 'botconnector-launcher.exe'), path.join(STAGE, 'BotConnector.exe'));
} else {
  // No separate launcher on Linux (per spec: `./botconnector` /
  // `botconnector ui` directly; an optional .desktop file is a later,
  // not-yet-built nicety) — just the one SEA binary.
  fs.copyFileSync(path.join(ROOT, 'dist-sea', 'botconnector'), path.join(STAGE, 'botconnector'));
  fs.chmodSync(path.join(STAGE, 'botconnector'), 0o755);
}

const README = win
  ? `BotConnector AI (${VERSION}) — Windows

1. Extract this ZIP.
2. Double-click BotConnector.exe.
3. BotConnector opens in your default browser.

No installation is required. Keep BotConnector.exe and
botconnector-core.exe together in the same folder.

Data is stored in your Windows user profile, under
%LOCALAPPDATA%\\BotConnector AI\\ — nothing is written beside these files.

To stop BotConnector: click "Quit BotConnector" in the app's sidebar.

To use the terminal client instead: botconnector-core.exe (or "botconnector"
once you put this folder on your PATH) — run with no arguments for the
Native Agent TUI, "doctor" for diagnostics, "ui" for the browser workspace,
"serve" to run the same backend headless, or "attach <url>" to attach a
terminal session to an already-running "ui"/"serve" backend so the browser
and terminal share one session.

If Windows shows a security warning for this beta, verify that you
downloaded the file from the official BotConnector source before
continuing. Do not disable Windows Defender or SmartScreen to get past it.
`
  : `BotConnector AI (${VERSION}) — Linux

1. Extract this archive: tar -xzf ${artifactName}
2. Run it: ./botconnector

That starts the Native Agent TUI directly in your terminal. No
installation, no Node.js/npm required on this machine.

Other commands:
  ./botconnector ui                  Web Agent Workspace: local server,
                                      opens your default browser
  ./botconnector serve               same backend as "ui", headless —
                                      for servers/CI/no display
  ./botconnector attach <url>        attach a terminal session to an
                                      already-running "ui"/"serve" backend,
                                      so the browser and terminal share one
                                      session
  ./botconnector doctor              environment/runtime diagnostics

To use "botconnector" from any directory, put this folder on your PATH,
e.g.: export PATH="$PATH:/path/to/this/folder"

Data is stored under $XDG_DATA_HOME/botconnector/ (or ~/.local/share/
botconnector/ if XDG_DATA_HOME is unset) — nothing is written beside this
binary. Everything binds to 127.0.0.1 only; nothing is exposed to your
network by default.
`;
fs.writeFileSync(path.join(STAGE, 'README.txt'), README);

console.log(`[3/4] packaging ${artifactName}...`);
fs.rmSync(ARTIFACT_PATH, { force: true });
if (win) {
  const yazl = (await import('yazl')).default;
  await new Promise((resolve, reject) => {
    const zipfile = new yazl.ZipFile();
    for (const name of fs.readdirSync(STAGE)) zipfile.addFile(path.join(STAGE, name), `BotConnector/${name}`);
    zipfile.outputStream.pipe(fs.createWriteStream(ARTIFACT_PATH)).on('close', resolve).on('error', reject);
    zipfile.end();
  });
} else {
  // Packaging (not extracting) files this script itself just wrote — none
  // of extractTarGzSecure's untrusted-input hardening applies here, so the
  // system's own tar is the right tool rather than hand-rolling a writer.
  execFileSync('tar', ['-czf', ARTIFACT_PATH, '-C', path.dirname(STAGE), platformDir], { stdio: 'inherit' });
}

console.log('[4/4] writing SHA256 checksum...');
const hash = crypto.createHash('sha256').update(fs.readFileSync(ARTIFACT_PATH)).digest('hex');
const sumsPath = `${ARTIFACT_PATH}.sha256`;
fs.writeFileSync(sumsPath, `${hash}  ${artifactName}\n`);

const sizeMb = (fs.statSync(ARTIFACT_PATH).size / 1e6).toFixed(1);
console.log(`\nDone.`);
console.log(`Artifact: ${ARTIFACT_PATH} (${sizeMb} MB)`);
console.log(`Checksum: ${sumsPath}`);
console.log(`SHA256:   ${hash}`);
console.log(`Staged folder: ${STAGE}`);
