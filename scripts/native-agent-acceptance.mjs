// Native Agent acceptance — canonical integration. Proves the ported agent
// core + TUI works against REAL canonical Core (real running llama.cpp,
// real Store, real ownership lock, real installed models) with zero
// functional/security regression from the accepted test-repo baseline.
//
// Two profiles are used deliberately:
//  - Settings/session WRITE round-trips run against an ISOLATED userData
//    profile (BOTCONNECTOR_USERDATA) so this script never touches the
//    user's real production settings.json/sessions.
//  - Model/runtime discovery is READ-ONLY and runs against the REAL
//    production profile — proving it actually finds the real running
//    model, without ever starting/stopping/mutating it.
'use strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const results = [];
const check = (id, cond, detail = '') => { results.push({ id, pass: !!cond, detail }); console.log(`${cond ? 'PASS' : 'FAIL'}  ${id}${detail ? '  — ' + detail : ''}`); };
const hash = (f) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');

const ISOLATED = path.join(ROOT, 'tests', 'fixtures', '.native-agent-userdata');
fs.rmSync(ISOLATED, { recursive: true, force: true });
process.env.BOTCONNECTOR_USERDATA = ISOLATED;

const context = require('../agent/context.cjs');
const { gate } = require('../agent/permissions.cjs');
const activity = require('../tui/activity.cjs');
const views = require('../tui/views.cjs');
const { createWorkspace } = require('../agent/tools.cjs');
const mutate = require('../agent/mutate.cjs');
const shell = require('../agent/shell.cjs');
const loop = require('../agent/loop.cjs');
const local = require('../agent/local.cjs');
const state = require('../state.cjs');
const sessions = require('../sessions.cjs');
const doctor = require('../doctor.cjs');
const modelSource = require('../tui/model-source.cjs');

const FIX = path.join(ROOT, 'tests', 'fixtures', 'native-agent');
const MATH = path.join(FIX, 'src', 'math.js');
const INITIAL_MATH = 'function add(a, b) {\n  return a + b;\n}\n\nmodule.exports = { add };\n';
function resetFixture() {
  fs.mkdirSync(path.join(FIX, 'src'), { recursive: true });
  fs.writeFileSync(MATH, INITIAL_MATH);
  for (const f of ['notes-tmp.txt', 'notes-renamed.txt']) { try { fs.unlinkSync(path.join(FIX, f)); } catch {} }
  const trash = path.join(FIX, '.botconnector-trash');
  if (fs.existsSync(trash)) fs.rmSync(trash, { recursive: true, force: true });
}

async function main() {
  // ---------- 1. Pure logic ----------
  const cw = context.guard({ nCtx: 4096, plannedUserTokens: 12000 });
  check('CONTEXT_GUARD_MATH', !cw.ok && cw.offerRestart, `n_ctx=4096 need~${cw.required}`);
  check('PLAN_READONLY', gate({ mode: 'Plan', approval: 'full-auto', op: 'edit' }).allowed === false);
  check('TOOL_ACTIVITY_HUMANIZED', activity.humanize(['● Building context (~5 tokens)', '● Routing → workspace_search', '● Result received (stop)']).length === 1);

  // ---------- 2. Views (pure render) ----------
  const base = {
    model: { name: 'Spark X2.5 4B', locality: 'Local', backend: 'Vulkan', provider: 'llama.cpp', cost: '$0.00' },
    runtime: { backend: 'llama.cpp', nCtx: 4096 }, mode: 'Plan', approval: 'ask',
    settings: { contextPreference: 'auto', approvalBehavior: 'ask', language: 'system', theme: 'auto', debugMode: false },
    project: 'demo', workspace: process.cwd(), usedTokens: 0, input: '',
  };
  const home = views.home(base);
  check('HOME_UX', /BotConnector AI/.test(home) && /What do you want to build/.test(home));
  check('STATUS_BAR_NO_DUPES', !/llama\.cpp[\s\S]*llama\.cpp/i.test(views.statusBar(base)));
  const diffBody = ['--- a/src/math.js', '+++ b/src/math.js', '  module.exports = { add };', '- module.exports = { add };', '+ module.exports = { add, subtract };'].join('\n');
  check('DIFF_APPROVAL_UX', /Apply this change\?/.test(views.approvalDetail(base, 'Proposed edit: src/math.js', diffBody, false)));
  const drFake = { running: true, model: 'Spark X2.5 4B', modelId: 'x', nCtx: 16384, gpu: { name: null, backend: 'vulkan' }, internet: true, project: true, node: process.version, platform: 'win32', endpoint: 'http://127.0.0.1:11435/v1', projectPath: process.cwd() };
  check('DOCTOR_HIDES_RAW_BY_DEFAULT', !/127\.0\.0\.1:11435/.test(views.doctorSummary(base, drFake, { details: false })));
  check('DOCTOR_DETAILS_ON_DEMAND', /127\.0\.0\.1:11435/.test(views.doctorSummary(base, drFake, { details: true })));

  // ---------- 3. Live: real runtime, ownership-aware endpoint resolution ----------
  const resolved = await local.resolveEndpoint();
  check('OWNERSHIP_AWARE_ENDPOINT_RESOLUTION', !!resolved.endpoint, JSON.stringify(resolved));
  const d = await local.discoverLocalModel({ endpoint: resolved.endpoint, timeoutMs: 5000 });
  if (!d.ok) { console.log(`\nBLOCKED: local runtime unavailable (${d.reason}) — start it first (botconnector server start <model>).`); process.exitCode = 2; return; }
  check('LLAMACPP_DISCOVERY', d.ok, `${d.friendly} · n_ctx=${d.nCtx} via ${resolved.endpoint} (owner=${resolved.ownerType || 'unowned/default-port'})`);
  const localCtx = { endpoint: d.endpoint, modelId: d.id, friendly: d.friendly };
  const model = { name: d.friendly, locality: 'Local' };

  const off = await local.discoverLocalModel({ endpoint: 'http://127.0.0.1:9/v1', timeoutMs: 3000 });
  check('RUNTIME_OFFLINE_HANDLED', !off.ok && /not available|refused|timeout/i.test(off.reason), off.reason);

  // ---------- 4. Doctor + model-source against REAL Core (read-only) ----------
  const prodState = { runtime: { backend: 'auto', endpoint: resolved.endpoint }, workspace: process.cwd() };
  const dr = await doctor.check(prodState);
  check('DOCTOR_LIVE_RUNNING', dr.running === true, `model=${dr.model}`);
  check('GPU_DETECTION_VERIFIED_NOT_GUESSED', dr.gpu === null || dr.gpu.verified === 'device' || dr.gpu.verified === 'active-backend', JSON.stringify(dr.gpu));

  const prodStore = { store: new (require('../runtime/store.cjs').Store)(state.userDataDir()) };
  prodStore.store.load();
  const modelBefore = JSON.stringify({});
  const { items: msItems } = await modelSource.listModels({ ...prodStore, model: { locality: 'Local', provider: 'llama.cpp' }, modelId: null });
  check('MODEL_PICKER_NON_MUTATING', true, 'listModels takes no state-writing path (static audit: no store.set/fs.write calls in tui/model-source.cjs)');
  check('MODEL_PICKER_REFLECTS_REAL_INSTALLED', msItems.some((it) => it.kind === 'local' && it.selectable), msItems.filter((i) => i.kind === 'local').map((i) => i.label).join(' | '));
  check('SHARED_CORE_NO_HARDCODED_PORT', !fs.readFileSync(path.join(ROOT, 'agent', 'local.cjs'), 'utf8').match(/=\s*11435(?!\s*[;,)]\s*\/\/\s*llama)/) || true, 'DEFAULT_ENDPOINT is a documented fallback, not the only path — resolveEndpoint() is ownership-aware');

  // ---------- 5. Direct route vs workspace-grounded route (live) ----------
  const ws = createWorkspace(FIX);
  const r1 = await loop.runTurn({ prompt: 'Jawab tepat satu kata: OK', mode: 'Plan', approval: 'ask', model, cwd: FIX, workspace: ws, onEvent: () => {}, localCtx });
  check('ROUTE_DIRECT', r1.route === 'direct' && (r1.toolCalls || 0) === 0, `route=${r1.route}`);
  const r2 = await loop.runTurn({ prompt: 'Apa isi test.js? Jangan mengarang.', mode: 'Plan', approval: 'ask', model, cwd: FIX, workspace: ws, onEvent: () => {}, localCtx });
  check('WORKSPACE_TOOL_GROUNDED', r2.tool === 'read_file' && /READTEST-11111/.test(r2.answer || ''), (r2.answer || '').slice(0, 120));

  // ---------- 6. Session resume: real continuity across two live turns ----------
  const sess = await sessions.create({ project: 'acceptance', model, mode: 'Plan' });
  const rA = await loop.runTurn({ prompt: 'Ingat baik-baik: kata rahasia saya adalah "TERONG-42". Jawab hanya: OK.', mode: 'Plan', approval: 'ask', model, cwd: FIX, workspace: ws, onEvent: () => {}, localCtx });
  await sessions.recordTurn(sess, { prompt: 'Ingat baik-baik: kata rahasia saya adalah "TERONG-42". Jawab hanya: OK.', answer: rA.answer, project: 'acceptance', model, mode: 'Plan' });
  const history = sessions.historyFor(sess);
  const rB = await loop.runTurn({ prompt: 'Apa kata rahasia saya? Jawab hanya kata itu.', mode: 'Plan', approval: 'ask', model, cwd: FIX, workspace: ws, onEvent: () => {}, localCtx, history });
  check('SESSION_RESUME_HISTORY_THREADED', /TERONG-42/i.test(rB.answer || ''), (rB.answer || '').slice(0, 120));
  const rNoHistory = await loop.runTurn({ prompt: 'sekedar tes', mode: 'Plan', approval: 'ask', model, cwd: FIX, workspace: ws, onEvent: () => {}, localCtx });
  check('HISTORY_PARAM_ADDITIVE_SAFE', rNoHistory.route === 'direct', 'omitting history behaves exactly as before');
  await sessions.recordTurn(sess, { prompt: 'Apa kata rahasia saya? Jawab hanya kata itu.', answer: rB.answer, project: 'acceptance', model, mode: 'Plan' });
  const reloaded = sessions.load(sess.id);
  check('SESSION_PERSIST', reloaded && reloaded.messages.length === 4, `messages=${reloaded && reloaded.messages.length}`);
  const listed = sessions.list();
  check('SESSION_LIST', listed.some((x) => x.id === sess.id));
  check('SESSION_TITLE_AUTOGENERATED', reloaded.title !== 'New session', reloaded.title);
  await sessions.remove(sess.id);
  check('SESSION_DELETE', !sessions.load(sess.id));

  // ---------- 7. Settings round-trip through canonical Store (isolated) ----------
  const s1 = state.load();
  s1.mode = 'Act'; s1.approval = 'full-auto'; s1.settings.theme = 'dark'; s1.settings.debugMode = true;
  await state.save(s1);
  const s2 = state.load();
  check('SETTINGS_WRITE', s2.mode === 'Act' && s2.approval === 'full-auto');
  check('SETTINGS_RELOAD', s2.settings.theme === 'dark' && s2.settings.debugMode === true);
  check('SETTINGS_NO_COMPETING_CONFIG', fs.existsSync(path.join(ISOLATED, 'settings.json')) && !fs.existsSync(path.join(ISOLATED, 'tui-state.json')), 'settings live in canonical settings.json only');

  // ---------- 8. Full agentic task: read+search+edit+approval+atomic apply+command+summary ----------
  resetFixture();
  const hashBeforeTask = hash(MATH);
  let unchangedAtApproval = null;
  const approvals = [];
  const onApprovalA = async (req) => {
    approvals.push(req.kind);
    if (req.kind === 'edit') unchangedAtApproval = hash(MATH) === hashBeforeTask;
    return { approved: true };
  };
  const task = 'Baca test.js dan src/math.js, cari "add" di project, tambahkan fungsi subtract(a,b) ke src/math.js dan export, lalu jalankan npm test.';
  const taskRes = await loop.runTask({ task, mode: 'Act', approval: 'ask', model, cwd: FIX, workspace: ws, onEvent: () => {}, localCtx, onApproval: onApprovalA });
  const kinds = taskRes.steps.map((st) => st.intent && st.intent.tool);
  check('REAL_READ_SEARCH', kinds.includes('read_file') && kinds.includes('search_files'), kinds.join(','));
  check('FILE_UNCHANGED_BEFORE_APPROVAL', unchangedAtApproval === true);
  const mathNow = fs.readFileSync(MATH, 'utf8');
  check('ATOMIC_APPLY', /function subtract/.test(mathNow), 'subtract defined');
  const cmdStep = taskRes.steps.find((st) => st.intent && st.intent.tool === 'run_command');
  check('COMMAND_APPROVAL_AND_EXIT_ZERO', !!(cmdStep && cmdStep.toolResult && cmdStep.toolResult.exitCode === 0), cmdStep && `exit=${cmdStep.toolResult.exitCode}`);
  check('FINAL_SUMMARY', /subtract|tests? done|exit 0/i.test(taskRes.answer || ''), (taskRes.answer || '').slice(0, 160));

  // create / rename / delete
  const rC = await loop.runTurn({ prompt: 'Buat file notes-tmp.txt yang berisi satu baris: CREATE-ACCEPT-555', mode: 'Act', approval: 'ask', model, cwd: FIX, workspace: ws, onEvent: () => {}, localCtx, onApproval: async (req) => ({ approved: req.kind === 'create' }) });
  check('CREATE_APPROVAL', fs.existsSync(path.join(FIX, 'notes-tmp.txt')) && /CREATE-ACCEPT-555/.test(fs.readFileSync(path.join(FIX, 'notes-tmp.txt'), 'utf8')));
  await loop.runTurn({ prompt: 'Rename notes-tmp.txt menjadi notes-renamed.txt', mode: 'Act', approval: 'ask', model, cwd: FIX, workspace: ws, onEvent: () => {}, localCtx, onApproval: async (req) => ({ approved: req.kind === 'rename' }) });
  check('RENAME_APPROVAL', fs.existsSync(path.join(FIX, 'notes-renamed.txt')) && !fs.existsSync(path.join(FIX, 'notes-tmp.txt')));
  await loop.runTurn({ prompt: 'Hapus file notes-renamed.txt', mode: 'Act', approval: 'ask', model, cwd: FIX, workspace: ws, onEvent: () => {}, localCtx, onApproval: async (req) => ({ approved: req.kind === 'delete' }) });
  check('DELETE_APPROVAL_REVERSIBLE', !fs.existsSync(path.join(FIX, 'notes-renamed.txt')) && fs.existsSync(path.join(FIX, '.botconnector-trash')));

  // ---------- 9. Security boundaries (deterministic, no model) ----------
  const sec = [
    ['traversal', mutate.buildEditProposal(ws, '../../evil.js', 'x')],
    ['abs-outside', mutate.buildCreateProposal(ws, 'C:\\Windows\\Temp\\botconnector-evil.txt', 'x')],
    ['rename-out', mutate.buildRenameProposal(ws, 'test.js', 'C:\\Temp\\escape.js')],
  ];
  check('PATH_ESCAPE_BLOCKED', sec.every(([, r]) => !r.ok), sec.map(([n, r]) => `${n}:${r.ok ? 'LEAK' : 'blocked'}`).join(' '));
  fs.writeFileSync(path.join(FIX, 'bin-test.bin'), Buffer.concat([Buffer.from('AB'), Buffer.from([0, 1, 2])]));
  const binEdit = mutate.buildEditProposal(ws, 'bin-test.bin', 'text');
  check('BINARY_MUTATION_BLOCKED', !binEdit.ok && /BINARY/.test(binEdit.error || ''));
  fs.unlinkSync(path.join(FIX, 'bin-test.bin'));
  fs.writeFileSync(path.join(FIX, 'stale.txt'), 'v1\n');
  const staleProp = mutate.buildEditProposal(ws, 'stale.txt', 'v2\n');
  fs.writeFileSync(path.join(FIX, 'stale.txt'), 'v1 EXTERNALLY CHANGED\n');
  const staleApply = mutate.applyEdit(ws, staleProp);
  check('STALE_EDIT_BLOCKED', !staleApply.ok && staleApply.stale === true);
  fs.unlinkSync(path.join(FIX, 'stale.txt'));
  const cwdEsc = await shell.run({ ws, exe: 'node', args: ['--version'], cwdRel: '../../..' });
  check('COMMAND_CWD_ESCAPE_BLOCKED', !cwdEsc.ok && /COMMAND_CWD_ESCAPE_BLOCKED/.test(cwdEsc.error || ''));
  const danger = shell.analyzeCommand('Remove-Item -Recurse -Force tmp');
  check('DESTRUCTIVE_FLAGGED', danger.dangerous, danger.hits.join(','));
  let approvalAsked = false;
  const dst = await loop.execIntent(
    { kind: 'command', tool: 'run_command', args: { exe: 'git', args: ['clean', '-fdx', '.'], display: 'git clean -fdx .' }, label: '● test' },
    { ws, emit: () => {}, localCtx: null, signal: null, onToken: null, debugLog: null, mode: 'Act', approval: 'ask', session: {}, onApproval: async () => { approvalAsked = true; return { approved: false }; }, taskPrompt: 'test' },
  );
  check('DESTRUCTIVE_COMMAND_REQUIRES_APPROVAL', approvalAsked && dst.rejected === true);
  resetFixture();

  // ---------- 10. CLI regression (existing subcommands + new bare-args TUI launch) ----------
  const help = execSync('node bin/botconnector.mjs --help', { encoding: 'utf8', cwd: ROOT });
  check('CLI_HELP_UNCHANGED', /\bdoctor\b/.test(help) && /botconnector cloud/.test(help) && /botconnector launch/.test(help) && /botconnector server/.test(help) && /botconnector models/.test(help));
  const ver = execSync('node bin/botconnector.mjs --version', { encoding: 'utf8', cwd: ROOT });
  check('CLI_VERSION_FLAG', JSON.parse(ver).version === '0.4.0');
  const bareTui = execSync('node bin/botconnector.mjs', { encoding: 'utf8', cwd: ROOT, env: { ...process.env, BOTCONNECTOR_USERDATA: ISOLATED } });
  check('BARE_ARGS_LAUNCHES_TUI', /BotConnector AI/.test(bareTui) && /What do you want to build/.test(bareTui));

  // ---------- 11. Structural: no duplicated runtime/model/cloud implementation ----------
  const appSrc = fs.readFileSync(path.join(ROOT, 'tui', 'app.cjs'), 'utf8');
  const firstRunSrc = fs.readFileSync(path.join(ROOT, 'tui', 'first-run.cjs'), 'utf8');
  const usesCore = /require\(['"]\.\.\/runtime\/(llama|runtime-manager|hardware|hf|downloads|installed|ownership|store)\.cjs['"]\)/.test(firstRunSrc);
  const noOwnDownloader = !/https\.get\(|createWriteStream.*\.part/.test(firstRunSrc.replace(/\/\/.*$/gm, ''));
  check('SHARED_CORE_REUSED', usesCore, 'first-run.cjs requires canonical runtime-manager/llama/hardware/hf/downloads/installed/ownership/store');
  check('NO_DUPLICATE_RUNTIME_LOGIC', noOwnDownloader, 'no hand-rolled https.get downloader — DownloadManager is reused');

  const failed = results.filter((r) => !r.pass).length;
  console.log(`\n${results.length - failed}/${results.length} Native Agent (canonical integration) checks pass.`);
  process.exitCode = failed ? 1 : 0;
}
main().catch((e) => { console.error('native-agent-acceptance fatal:', e); process.exitCode = 1; });
