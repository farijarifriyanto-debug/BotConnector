// Native Windows file/folder pickers without Electron. The HTTP server runs
// locally with the same OS privileges the user has, so it can still show a
// real native dialog — it just does it by shelling out to a tiny inline
// PowerShell + WinForms script instead of asking a bundled Chromium to do it.
// Not portable to other OSes; this whole product is Windows-only today
// (llama.cpp Windows runtime, NSIS installer), so that is not a new limit.
const { execFile } = require('node:child_process');

function runPs(script) {
  return new Promise((resolve, reject) => {
    execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], { windowsHide: true, timeout: 120000 }, (err, stdout) => {
      if (err && err.killed) return reject(new Error('Dialog timed out'));
      resolve(String(stdout || '').trim());
    });
  });
}

async function pickFolder(title) {
  const t = String(title || 'Choose a folder').replace(/'/g, "''");
  const out = await runPs(`
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    $f = New-Object System.Windows.Forms.FolderBrowserDialog
    $f.Description = '${t}'
    if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }
  `);
  return out || null;
}

async function pickFile(title, filterName, extensions) {
  const t = String(title || 'Choose a file').replace(/'/g, "''");
  const fn = String(filterName || 'Files').replace(/'/g, "''");
  const exts = (Array.isArray(extensions) && extensions.length ? extensions : ['*']).map(e => `*.${e}`).join(';');
  const out = await runPs(`
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    $f = New-Object System.Windows.Forms.OpenFileDialog
    $f.Title = '${t}'
    $f.Filter = '${fn} (${exts})|${exts}'
    if ($f.ShowDialog() -eq 'OK') { Write-Output $f.FileName }
  `);
  return out || null;
}

module.exports = { pickFolder, pickFile };
