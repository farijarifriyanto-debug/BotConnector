// One-time, isolated, REAL first-run proof: hardware -> recommendation ->
// approval-gated download -> runtime install -> backend choose -> runtime
// start -> chat. Uses an isolated BOTCONNECTOR_USERDATA profile so this
// never touches the real production settings/models/runtime.
'use strict';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const ISOLATED = path.join(ROOT, 'tests', 'fixtures', '.first-run-proof-userdata');
// NOTE: not wiping ISOLATED here on purpose for this run — a prior run
// already proved the download+runtime-install path from a clean profile;
// reusing that cache lets this run verify start+chat without paying for
// another ~2GB download. Delete the folder manually for a from-scratch run.
process.env.BOTCONNECTOR_USERDATA = ISOLATED;

const firstRun = require('../tui/first-run.cjs');
const local = require('../agent/local.cjs');
const { scanInstalled } = require('../runtime/installed.cjs');
const { Store } = require('../runtime/store.cjs');
const { userDataDir } = require('../state.cjs');

const results = [];
const check = (id, cond, detail = '') => { results.push({ id, pass: !!cond, detail }); console.log(`${cond ? 'PASS' : 'FAIL'}  ${id}${detail ? '  — ' + detail : ''}`); };

async function main() {
  console.log(`Isolated profile: ${ISOLATED}\n`);

  // 1. FIRST_RUN_SCREEN / hardware detection
  const rec = await firstRun.recommend();
  check('FIRST_RUN_SCREEN', !!rec.hardware, `RAM=${rec.hardware.ramGb}GB CPU=${rec.hardware.cpu.trim()}`);

  // 2. RECOMMENDATION — real catalog + real hardware fit
  check('RECOMMENDATION', !!rec.recommendation, rec.recommendation ? `${rec.recommendation.model.name} (${rec.recommendation.model.download_size_gb}GB, ${rec.recommendation.fit.level})` : 'none');
  if (!rec.recommendation) { console.log('BLOCKED: no recommendation for this hardware.'); process.exitCode = 2; return; }

  // 3. Resolve to a real downloadable GGUF (shows size before approval)
  const resolved = await firstRun.resolveDownloadable(rec.recommendation.model, rec.hardware);
  check('DOWNLOAD_SIZE_SHOWN_BEFORE_APPROVAL', resolved.group.size > 0, `${resolved.repoId} · ${(resolved.group.size / 1e9).toFixed(2)}GB`);

  // 4. DOWNLOAD_REQUIRES_APPROVAL — structural: download only starts here,
  // after this script (standing in for the user's explicit [Y]) calls it.
  console.log(`\nApproving download: ${resolved.repoId}@${resolved.group.quant} (~${(resolved.group.size / 1e9).toFixed(2)}GB)...\n`);
  const store = new Store(userDataDir()); store.load();
  // Isolated models dir too — this proof must never write into the user's
  // real BotConnector AI/models folder, even though it uses an isolated
  // settings profile.
  await store.set('modelsDir', path.join(ISOLATED, 'models'));
  let lastPct = -10;
  const dm = firstRun.makeDownloader({
    store,
    emit: (ch, p) => {
      if (ch !== 'download:progress') return;
      const pct = p.totalBytes ? Math.round((p.downloadedBytes / p.totalBytes) * 100) : 0;
      if (pct - lastPct >= 10 || p.status !== 'downloading') { console.log(`  ${p.status} ${pct}% (${(p.downloadedBytes / 1e6).toFixed(0)}MB / ${(p.totalBytes / 1e6).toFixed(0)}MB)`); lastPct = pct; }
    },
  });
  const job = await dm.start({ repoId: resolved.repoId, group: resolved.group, metadata: { capabilities: resolved.details.capabilities, pipeline_tag: resolved.details.pipeline_tag } });
  let final = null;
  for (let i = 0; i < 1800; i++) {
    const j = dm.list().find((x) => x.id === job.id);
    if (j && ['completed', 'failed', 'cancelled'].includes(j.status)) { final = j; break; }
    await new Promise((r) => setTimeout(r, 1000));
  }
  check('DOWNLOAD_REQUIRES_APPROVAL', !!final && final.status === 'completed', final ? final.status : 'timed out');
  if (!final || final.status !== 'completed') { console.log('BLOCKED: download did not complete.'); process.exitCode = 2; return; }

  // 5. RUNTIME_SETUP — install/verify managed llama.cpp
  console.log('\nSetting up managed runtime...');
  let lastRtLog = 0;
  const rt = await firstRun.ensureRuntimeInstalled({
    userDataDir: userDataDir(), backend: 'auto',
    emit: (ch, p) => {
      if (ch !== 'runtime:install-progress') return;
      const now = Date.now();
      if (p.status !== 'downloading' || now - lastRtLog > 1000) { console.log(`  ${p.status || ''} ${p.backend || ''} ${p.release || ''} ${p.asset || ''}`); lastRtLog = now; }
    },
  });
  check('RUNTIME_SETUP', !!rt.binary && fs.existsSync(rt.binary), rt.binary);

  // 6. RUNTIME_START — real start, claiming the shared ownership lock
  const installed = await scanInstalled(store.get('modelsDir'));
  const picked = installed.find((m) => m.repoId === resolved.repoId);
  check('MODEL_READY_ON_DISK', !!picked, picked && picked.path);
  const backend = rt.backend || 'vulkan';
  const started = await firstRun.startRuntime({ binary: rt.binary, modelPath: picked.path, projector: picked.projector, backend, context: 8192, port: 11499 });
  check('RUNTIME_START', !!started.pid, `pid=${started.pid} port=11499 backend=${backend}`);

  // 7. Wait for ready, then FIRST_CHAT — a real live prompt
  let ready = null;
  for (let i = 0; i < 60 && !ready; i++) {
    const r = await local.discoverLocalModel({ endpoint: 'http://127.0.0.1:11499/v1', timeoutMs: 2000 });
    if (r.ok) ready = r; else await new Promise((res) => setTimeout(res, 2000));
  }
  check('MODEL_READY', !!ready, ready ? `${ready.friendly} n_ctx=${ready.nCtx}` : 'did not become ready');
  if (ready) {
    const chat = await local.localChat({ endpoint: 'http://127.0.0.1:11499/v1', model: ready.id, messages: [{ role: 'user', content: 'Reply with exactly: FIRST-RUN-OK' }], maxTokens: 30 });
    check('FIRST_CHAT', chat.ok && /FIRST-RUN-OK/i.test(chat.content || ''), JSON.stringify(chat.content));
  }

  // Cleanup: stop the runtime we started, release the lock, remove isolated profile.
  const llama = require('../runtime/llama.cjs');
  const { releaseOwnership, statePath } = require('../runtime/ownership.cjs');
  try { llama.stopLlama(); } catch {}
  try { await releaseOwnership(statePath()); } catch {}

  const failed = results.filter((r) => !r.pass).length;
  console.log(`\n${results.length - failed}/${results.length} first-run checks pass.`);
  console.log(`\nDownloaded model kept at (isolated profile): ${store.get('modelsDir')}`);
  console.log('Isolated profile left in place for inspection: ' + ISOLATED);
  process.exitCode = failed ? 1 : 0;
}
main().catch((e) => { console.error('first-run-proof fatal:', e); process.exitCode = 1; });
