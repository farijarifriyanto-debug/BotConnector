// Compiles launcher/Launcher.cs -> dist-sea/BotConnector.exe using the C#
// compiler already present in every Windows install (.NET Framework's
// csc.exe — no Visual Studio, no extra SDK download, nothing to bundle).
// /target:winexe is what makes this a GUI-subsystem binary: Windows never
// allocates a console window for it, satisfying "no visible console" without
// any runtime console-hiding trickery.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const SRC = path.join(ROOT, 'launcher', 'Launcher.cs');
const OUT_DIR = path.join(ROOT, 'dist-sea');
// Named "-launcher" (not "BotConnector.exe") purely to stay in the SAME
// staging directory as botconnector.exe without colliding: NTFS is
// case-insensitive, so "BotConnector.exe" and "botconnector.exe" are the
// same file here and one build would silently overwrite the other's much
// larger output. scripts/build-portable.mjs renames this to the final
// "BotConnector.exe" only inside the separate dist-portable/ output folder,
// which never contains a same-named-except-case sibling.
const OUT = path.join(OUT_DIR, 'botconnector-launcher.exe');

function findCsc() {
  const candidates = [
    path.join(process.env.WINDIR || 'C:\\Windows', 'Microsoft.NET', 'Framework64', 'v4.0.30319', 'csc.exe'),
    path.join(process.env.WINDIR || 'C:\\Windows', 'Microsoft.NET', 'Framework', 'v4.0.30319', 'csc.exe'),
  ];
  for (const c of candidates) if (fs.existsSync(c)) return c;
  throw new Error('csc.exe (.NET Framework C# compiler) not found. Expected it under %WINDIR%\\Microsoft.NET\\Framework64\\v4.0.30319\\ — this ships with every Windows install; if it is truly missing, the portable launcher cannot be built on this machine.');
}

fs.mkdirSync(OUT_DIR, { recursive: true });
const csc = findCsc();
console.log(`[1/1] compiling launcher (${csc})...`);
execFileSync(csc, [
  '/nologo', '/target:winexe', '/platform:x64',
  '/reference:System.Windows.Forms.dll',
  `/out:${OUT}`,
  SRC,
], { stdio: 'inherit' });
console.log(`Done: ${OUT} (${(fs.statSync(OUT).size / 1024).toFixed(1)} KB)`);
