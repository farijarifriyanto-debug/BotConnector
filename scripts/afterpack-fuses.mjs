import path from 'node:path';
import fs from 'node:fs';
import { flipFuses, FuseVersion, FuseV1Options } from '@electron/fuses';

export default async function afterPack(context) {
  const { appOutDir, electronPlatformName } = context;
  if (electronPlatformName !== 'win32') return;

  // Find the main GUI .exe specifically — electron-builder names it after
  // productName. Do NOT use a generic "first .exe found" glob: the CLI's
  // botconnector.exe (a separate, unrelated Node SEA — see extraFiles in
  // package.json) also lands in this same directory, and fusing the wrong
  // binary here would either silently skip hardening the real GUI exe or
  // corrupt the unrelated CLI exe.
  const exeName = `${context.packager.appInfo.productFilename}.exe`;
  if (!fs.existsSync(path.join(appOutDir, exeName)))
    throw new Error(`Expected GUI executable not found: ${exeName} in ${appOutDir}`);
  const exePath = path.join(appOutDir, exeName);

  console.log(`[afterPack] injecting fuses into ${exePath}`);

  const numSentinels = await flipFuses(exePath, {
    version: FuseVersion.V1,
    [FuseV1Options.RunAsNode]: false,
    [FuseV1Options.EnableCookieEncryption]: true,
    [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
    [FuseV1Options.EnableNodeCliInspectArguments]: false,
    [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
    [FuseV1Options.OnlyLoadAppFromAsar]: true,
    [FuseV1Options.LoadBrowserProcessSpecificV8Snapshot]: false,
    [FuseV1Options.GrantFileProtocolExtraPrivileges]: false,
    [FuseV1Options.WasmTrapHandlers]: true,
  });

  console.log(`[afterPack] fuses written: ${numSentinels} sentinel(s) patched`);
}
