'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { createCommandRegistry } = require('../registry/commands.cjs');
const skillRegistry = require('../registry/skills.cjs');
const mcpRegistry = require('../registry/mcp.cjs');
const diffRegistry = require('../registry/diff.cjs');
const agentRegistry = require('../registry/agents.cjs');
const toolRegistry = require('../registry/tools.cjs');
const modelSource = require('../tui/model-source.cjs');
const views = require('../tui/views.cjs');

function temp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'botconnector-surface-')); }
function write(file, text) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, text); }

test('COMMAND_REGISTRY_SINGLE_SOURCE + SLASH/CTRL_P registry parity', () => {
  const registry = createCommandRegistry({ workspace: process.cwd(), gitAvailable: true });
  const all = registry.all();
  assert.ok(all.length >= 20);
  assert.equal(new Set(all.map((x) => x.slash)).size, all.length);
  assert.equal(registry.resolve('/models').id, 'model');
  assert.deepEqual(registry.filter('m').slice(0, 2).map((x) => x.slash), ['/model', '/mcp']);
  assert.deepEqual(new Set(registry.filter('').map((x) => x.slash)), new Set(registry.all().map((x) => x.slash)));
  assert.equal(registry.resolve('/summarize').id, 'compact');
  assert.equal(registry.resolve('/themes').id, 'theme');
  assert.equal(registry.resolve('/q').id, 'exit');
});

test('SKILL_DISCOVERY + project precedence', () => {
  const root = temp(); const home = temp();
  write(path.join(root, '.agents/skills/review/SKILL.md'), '---\nname: Project Review\ndescription: Review project code\n---\nProject body');
  write(path.join(home, '.agents/skills/review/SKILL.md'), '---\nname: Global Review\ndescription: Global body\n---\nGlobal body');
  write(path.join(home, '.claude/skills/tdd/SKILL.md'), '# TDD\nTest-driven implementation');
  const rows = skillRegistry.discover({ projectRoot: root, homeDir: home });
  assert.equal(rows.find((x) => x.id === 'review').name, 'Project Review');
  assert.equal(rows.find((x) => x.id === 'review').scope, 'project');
  assert.equal(rows.find((x) => x.id === 'tdd').scope, 'global');
  assert.equal(skillRegistry.readBody(rows.find((x) => x.id === 'review')).includes('Project body'), true);
});

test('CUSTOM_COMMAND_DISCOVERY is dynamic and metadata-only', () => {
  const root = temp();
  write(path.join(root, '.botconnector/commands/review.md'), '# Review changes\nReview the current changes carefully.');
  const command = createCommandRegistry({ workspace: root, gitAvailable: false }).resolve('/review');
  assert.equal(command.source, 'PROJECT_COMMAND');
  assert.equal(command.handler, 'project-command');
  assert.match(command.description, /Review/);
});

test('MCP_DYNAMIC_LIST + MCP_ZERO_STATE', () => {
  assert.deepEqual(mcpRegistry.listConfigured({ get: () => [] }), []);
  assert.equal(mcpRegistry.zeroState().empty, true);
  const rows = mcpRegistry.listConfigured({ get: () => [{ id: 'x', name: 'Dynamic', transport: 'stdio', command: 'node', enabled: true, allowedTools: ['read'] }] });
  assert.equal(rows[0].name, 'Dynamic');
  assert.equal(rows[0].toolsCount, 1);
});

test('DIFF_GIT_REPO + DIFF_NON_GIT_DISABLED', () => {
  assert.equal(diffRegistry.isGitRepository(process.cwd()), true);
  const result = diffRegistry.collect(temp());
  assert.equal(result.ok, false);
  assert.equal(result.error, 'Not a Git repository');
});

test('AGENT_DISCOVERY and TOOLS_REAL_ONLY', () => {
  const root = temp();
  write(path.join(root, '.agents/agents/review.md'), '# Review\nReview code changes');
  const agents = agentRegistry.discover({ projectRoot: root });
  assert.deepEqual(agents.slice(0, 2).map((x) => x.id), ['plan', 'act']);
  assert.equal(agents.find((x) => x.id === 'review').source, '.agents/agents');
  const tools = toolRegistry.discover({ mcp: [] });
  assert.ok(tools.some((x) => x.id === 'read_file'));
  assert.equal(tools.some((x) => x.name === 'web'), false);
});

test('MODEL_CAPABILITY_FILTER excludes embedding-only models', () => {
  assert.equal(modelSource.isChatCapableModel({ capabilities: { embeddings: true, chat: false } }), false);
  assert.equal(modelSource.isChatCapableModel({ capabilities: { embeddings: true, chat: true } }), true);
  assert.equal(modelSource.isChatCapableModel({ capabilities: { chat: true } }), true);
});

test('MODEL_REGISTRY exposes Auto routing entry', async () => {
  const modelSource = require('../tui/model-source.cjs');
  const fakeStore = { get: (key) => key === 'modelsDir' ? path.join(temp(), 'models') : [] };
  const listed = await modelSource.listModels({ store: fakeStore, model: { name: 'Auto', locality: 'Local', provider: 'routing' } });
  assert.equal(listed.items[0].id, '__auto__');
  assert.equal(listed.items[0].kind, 'auto');
});

test('AT_FILE_PICKER + SHELL_PREFIX registry affordances exist', () => {
  const registry = createCommandRegistry({ workspace: process.cwd(), gitAvailable: true });
  assert.equal(registry.resolve('/shell').handler, 'shell');
  assert.equal(registry.resolve('/tools').handler, 'tools');
  assert.ok(views.composerPopover({ items: [{ name: '/model', description: 'Change model' }], index: 0 }).some((line) => line.includes('/model')));
});

test('80X24 + 120X35 + 160X45 popover remains bounded', () => {
  const oldCols = process.stdout.columns, oldRows = process.stdout.rows;
  const s = { input: '/', mode: 'Plan', model: { name: 'Model', locality: 'Local', backend: 'cpu' }, runtime: { nCtx: 4096 }, usedTokens: 0, workspace: 'workspace', project: 'workspace' };
  const sess = { messages: [{ role: 'user', content: 'visible transcript' }] };
  try {
    for (const [cols, rows] of [[80, 24], [120, 35], [160, 45]]) {
      Object.defineProperty(process.stdout, 'columns', { value: cols, configurable: true });
      Object.defineProperty(process.stdout, 'rows', { value: rows, configurable: true });
      const lines = views.home(s, sess, [], '', { composerPopover: { title: 'Commands', items: [{ name: '/model', description: 'Change model' }], index: 0 } }).split('\n');
      assert.ok(lines.some((x) => x.includes('/model')));
      assert.ok(lines.some((x) => x.includes('visible transcript')));
      assert.ok(lines.length <= rows + 2);
    }
  } finally {
    Object.defineProperty(process.stdout, 'columns', { value: oldCols, configurable: true });
    Object.defineProperty(process.stdout, 'rows', { value: oldRows, configurable: true });
  }
});
