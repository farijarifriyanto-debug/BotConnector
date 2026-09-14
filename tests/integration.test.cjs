'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const integrations = require('../registry/integrations.cjs');
const { createCommandRegistry } = require('../registry/commands.cjs');

function tempDir() { return fs.mkdtempSync(path.join(os.tmpdir(), 'botconnector-integration-')); }

test('INTEGRATION_REGISTRY exposes normalized entries and honest unverified candidates', () => {
  const registry = integrations.createIntegrationRegistry({ cwd: tempDir(), platform: 'win32', pathLookup: () => null });
  const rows = registry.list();
  assert.ok(rows.length >= 19);
  assert.ok(rows.some((row) => row.id === 'opencode' && row.protocol === 'OpenAI-compatible'));
  assert.ok(rows.some((row) => row.id === 'ollama'));
  assert.ok(registry.unverifiedCandidates().includes('NemoClaw'));
});

test('WINDOWS_EXECUTABLE_DETECTION and LINUX_EXECUTABLE_DETECTION use platform abstraction', () => {
  const def = integrations.DEFINITIONS.find((row) => row.id === 'opencode');
  const win = integrations.detectDefinition(def, { platform: 'win32', pathLookup: () => 'C:\\Tools\\opencode.exe' });
  const linux = integrations.detectDefinition(def, { platform: 'linux', pathLookup: () => '/usr/local/bin/opencode' });
  assert.equal(win.executable, 'C:\\Tools\\opencode.exe');
  assert.equal(linux.executable, '/usr/local/bin/opencode');
  assert.equal(integrations.detectDefinition(def, { platform: 'win32', pathLookup: () => null }).status, integrations.STATUS.NOT_INSTALLED);
});

test('INSTALLED_STATUS, NOT_INSTALLED_STATUS, and unsupported adapters are explicit', () => {
  const found = integrations.detectDefinition(integrations.DEFINITIONS.find((row) => row.id === 'opencode'), { platform: 'win32', pathLookup: () => 'opencode.exe' });
  assert.equal(found.status, integrations.STATUS.NEEDS_CONFIG);
  const unsupported = integrations.detectDefinition(integrations.DEFINITIONS.find((row) => row.id === 'terminal'), { platform: 'aix', pathLookup: () => null });
  assert.equal(unsupported.status, integrations.STATUS.UNSUPPORTED);
  const unknown = integrations.detectDefinition(integrations.DEFINITIONS.find((row) => row.id === 'cline-cli'), { platform: 'win32', pathLookup: () => 'cline.exe' });
  assert.equal(unknown.status, integrations.STATUS.UNKNOWN);
});

test('MODEL_REGISTRY_REUSED and AUTO_MODEL_ROUTING do not invent a provider model', () => {
  const registry = integrations.createIntegrationRegistry({ cwd: tempDir(), platform: process.platform, pathLookup: () => null });
  const models = [{ id: 'chat-a', capabilities: { chat: true, toolCalling: true } }, { id: 'embedding-only', capabilities: { chat: false } }];
  assert.deepEqual(registry.compatibleModels(models, 'opencode').map((row) => row.id), ['chat-a']);
  assert.deepEqual(integrations.resolveAutoModel({ requested: 'auto', store: { get: () => null } }), { requested: 'auto', id: 'local-model', mode: 'auto', source: 'BotConnector router' });
  assert.equal(integrations.resolveAutoModel({ requested: 'configured/cloud', store: { get: () => 'configured/cloud' } }).id, 'configured/cloud');
});

test('CONFIG_BACKUP and CONFIG_RESTORE preserve unrelated OpenCode configuration', async () => {
  const cwd = tempDir();
  const configPath = path.join(cwd, 'opencode.json');
  fs.writeFileSync(configPath, JSON.stringify({ keep: { value: 1 }, provider: { other: { token: 'secret-value' } } }, null, 2));
  const registry = integrations.createIntegrationRegistry({ cwd, platform: process.platform, pathLookup: () => 'opencode' });
  const result = await registry.configureOpenCode({ cwd, endpoint: 'http://127.0.0.1:11435', modelId: 'active-model', modelName: 'Active model' });
  assert.equal(result.ok, true);
  assert.equal(JSON.parse(fs.readFileSync(configPath, 'utf8')).keep.value, 1);
  assert.ok(JSON.parse(fs.readFileSync(configPath, 'utf8')).provider['botconnector-local']);
  assert.ok(fs.existsSync(result.backupPath));
  const restored = await registry.restoreIntegration({ id: 'opencode', cwd });
  assert.equal(restored.ok, true);
  const final = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  assert.equal(final.provider.other.token, 'secret-value');
  assert.equal(final.provider['botconnector-local'], undefined);
});

test('CONFIG_RESTORE refuses a user change after BotConnector configuration', async () => {
  const cwd = tempDir();
  const registry = integrations.createIntegrationRegistry({ cwd, platform: process.platform, pathLookup: () => 'opencode' });
  await registry.configureOpenCode({ cwd, endpoint: 'http://127.0.0.1:11435', modelId: 'active-model' });
  const file = path.join(cwd, 'opencode.json');
  const changed = JSON.parse(fs.readFileSync(file, 'utf8')); changed.provider['botconnector-local'].name = 'User changed'; fs.writeFileSync(file, JSON.stringify(changed));
  const restored = await registry.restoreIntegration({ id: 'opencode', cwd });
  assert.equal(restored.ok, false);
  assert.match(restored.reason, /refusing to overwrite user changes/i);
});

test('PROCESS_SCOPED_ENV, LAUNCH_WORKDIR, and LAUNCH_EXIT_PROPAGATION', async () => {
  const cwd = tempDir();
  const code = "process.exit(process.cwd() === process.argv[1] && process.env.BOTCONNECTOR_ENDPOINT === 'http://127.0.0.1:11435' ? 0 : 7)";
  const entry = { id: 'test-launch', name: 'Test launch', executable: process.execPath, launchable: true, adapter: null, configured: true };
  const result = await integrations.launchIntegration(entry, { cwd, args: ['-e', code, cwd], endpoint: 'http://127.0.0.1:11435', env: { ...process.env, BOTCONNECTOR_ENDPOINT: 'outside-value' } });
  assert.equal(result.ok, true);
  assert.equal(result.exitCode, 0);
});

test('COMMAND_REGISTRY_SINGLE_SOURCE, SLASH_USES_REGISTRY, and CTRL_P shared command', () => {
  const root = tempDir();
  const commands = createCommandRegistry({ workspace: root, gitAvailable: false, journalStatus: { canUndo: false, canRedo: false } });
  const launch = commands.resolve('/launch');
  assert.ok(launch);
  assert.equal(launch.handler, 'launch');
  assert.equal(commands.filter('launch')[0].id, 'launch');
  const app = fs.readFileSync(path.join(__dirname, '..', 'tui', 'app.cjs'), 'utf8');
  assert.match(app, /integrationRegistry\.list\(\)/);
  assert.doesNotMatch(app, /const\s+catalog\s*=\s*\{/);
});

test('CLI_LAUNCH_LIST and CLI_LAUNCH_JSON expose the same registry', () => {
  const root = path.join(__dirname, '..');
  const run = spawnSync(process.execPath, ['bin/botconnector.mjs', 'launch', '--list', '--json'], { cwd: root, encoding: 'utf8', timeout: 15000 });
  assert.equal(run.status, 0, run.stderr);
  const parsed = JSON.parse(run.stdout);
  assert.ok(parsed.integrations.some((row) => row.id === 'opencode'));
  assert.ok(parsed.integrations.some((row) => row.id === 'ollama'));
});

test('NO_SECRET_LOGGING keeps credentials out of adapter result text', async () => {
  const cwd = tempDir();
  const result = await integrations.configureOpenCode({ cwd, endpoint: 'http://127.0.0.1:11435', modelId: 'active-model' });
  assert.doesNotMatch(JSON.stringify(result), /secret|token|api.?key/i);
});
