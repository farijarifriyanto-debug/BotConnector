import { getCurrentFuseWire, FuseV1Options } from '@electron/fuses';

const wire = await getCurrentFuseWire('dist/win-unpacked/BotConnector AI.exe');
console.log('fuse version:', wire.version);
const checks = [
  [FuseV1Options.RunAsNode, 'RunAsNode', false],
  [FuseV1Options.EnableCookieEncryption, 'EnableCookieEncryption', true],
  [FuseV1Options.EnableNodeOptionsEnvironmentVariable, 'EnableNodeOptionsEnvironmentVariable', false],
  [FuseV1Options.EnableNodeCliInspectArguments, 'EnableNodeCliInspectArguments', false],
  [FuseV1Options.EnableEmbeddedAsarIntegrityValidation, 'EnableEmbeddedAsarIntegrityValidation', true],
  [FuseV1Options.OnlyLoadAppFromAsar, 'OnlyLoadAppFromAsar', true],
  [FuseV1Options.LoadBrowserProcessSpecificV8Snapshot, 'LoadBrowserProcessSpecificV8Snapshot', false],
  [FuseV1Options.GrantFileProtocolExtraPrivileges, 'GrantFileProtocolExtraPrivileges', false],
  [FuseV1Options.WasmTrapHandlers, 'WasmTrapHandlers', true],
];
let pass = 0, fail = 0;
for (const [idx, name, expectedEnabled] of checks) {
  const raw = wire[idx];
  // raw wire bytes: 48=DISABLE, 49=ENABLE
  const enabled = raw === 49;
  const disabled = raw === 48;
  const state = disabled ? 'DISABLED' : enabled ? 'ENABLED' : 'UNKNOWN(' + raw + ')';
  const ok = enabled === expectedEnabled;
  console.log((ok ? 'OK' : 'FAIL') + ' ' + name + ': ' + state + ' (expected ' + (expectedEnabled ? 'ENABLED' : 'DISABLED') + ')');
  if (ok) pass++; else fail++;
}
console.log('\nResult: ' + pass + '/9 passed, ' + fail + '/9 failed');
if (fail > 0) process.exit(1);
