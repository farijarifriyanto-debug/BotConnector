// Interactive TUI shell — canonical integration. Alternate screen, raw
// keypress events (no polling), human-friendly tool activity, permission
// gates, real first-run setup, real session persistence, real settings
// through canonical Store, real runtime start/stop through canonical
// ownership lock. Terminal-native, single Node process.
'use strict';
const path = require('path');
const readline = require('readline');
const state = require('../state.cjs');
const views = require('./views.cjs');
const loop = require('../agent/loop.cjs');
const tools = require('../agent/tools.cjs');
const ctxGuard = require('../agent/context.cjs');
const local = require('../agent/local.cjs');
const modelSource = require('./model-source.cjs');
const firstRun = require('./first-run.cjs');
const doctorMod = require('../doctor.cjs');
const sessions = require('../sessions.cjs');
const projects = require('../projects.cjs');
const { scanInstalled } = require('../runtime/installed.cjs');
const llama = require('../runtime/llama.cjs');
const { readOwnership, statePath, pidAlive, releaseOwnership } = require('../runtime/ownership.cjs');

const ALT_ON = '\x1b[?1049h\x1b[H';
const ALT_OFF = '\x1b[?1049l';
const CLEAR = '\x1b[2J\x1b[H';

async function runTui(opts = {}) {
  const s = state.load();
  s.input = '';
  s.workspace = opts.workspace || opts.cwd || process.cwd();
  s.project = path.basename(s.workspace) || s.workspace;
  let debug = opts.debug || process.argv.includes('--debug') || s.settings.debugMode;
  const log = (...a) => { if (debug) require('fs').appendFileSync('botconnector-debug.log', a.join(' ') + '\n'); };

  projects.touch(s.workspace);
  let sess = await sessions.create({ project: s.project, model: s.model, mode: s.mode });

  let pendingWarning = null;
  const g = ctxGuard.guard({ nCtx: s.runtime.nCtx, plannedUserTokens: 3000 });
  if (!g.ok) pendingWarning = g.warning;

  const out = process.stdout;
  const canRaw = out.isTTY && process.stdin.isTTY;
  if (!canRaw) {
    console.log(views.home(s));
    if (pendingWarning) console.log(pendingWarning);
    return;
  }
  process.stdout.write(ALT_ON);
  const restore = () => process.stdout.write(ALT_OFF);
  process.on('exit', restore);
  process.on('SIGINT', () => { restore(); process.exit(0); });

  let activity = [];
  let answer = '';
  let overlay = null;
  let pickerState = null;
  let approvalReq = null, approvalResolve = null;
  let diffFull = false;
  let doctorResult = null, doctorDetails = false;
  let statusExtra = {};
  let errorState = null;
  let pendingGuard = null;
  let ctxFullShown = false;
  let firstRunHw = null, firstRunRec = null, firstRunResolved = null, firstRunError = null;
  let firstRunProgressState = { pct: 0, downloadedBytes: 0, totalBytes: 0, status: '' };
  let firstRunJobId = null;
  let runtimeStoppedInfo = null;
  const taskSession = { approveAll: false };
  let generating = false, genAbort = null;

  const draw = () => {
    let screen;
    if (overlay === 'picker') screen = views.picker(s, pickerState);
    else if (overlay === 'project-browse') screen = renderProjectBrowse();
    else if (overlay === 'settings-edit') screen = renderSettingsEdit();
    else if (overlay === 'approve-diff' && approvalReq) screen = views.approvalDetail(s, approvalReq.title, approvalReq.detail, false, { proposal: approvalReq.proposal, full: diffFull });
    else if (overlay === 'approve-command' && approvalReq) screen = views.approvalDetail(s, approvalReq.title, approvalReq.detail, true);
    else if (overlay === 'context-needs-larger') screen = views.contextNeedsLarger(s, pendingGuard, recommendCtxK(pendingGuard.required));
    else if (overlay === 'context-full') screen = views.contextGettingFull(s);
    else if (overlay === 'doctor') screen = views.doctorSummary(s, doctorResult || {}, { details: doctorDetails });
    else if (overlay === 'settings') screen = views.settingsView(s);
    else if (overlay === 'status') screen = views.statusView(s, statusExtra);
    else if (overlay === 'error') screen = views.errorView(s, errorState);
    else if (overlay === 'runtime-stopped') screen = renderRuntimeStopped();
    else if (overlay === 'first-run-recommend') screen = renderFirstRunRecommend();
    else if (overlay === 'first-run-progress') screen = renderFirstRunProgress();
    else if (overlay === 'first-run-done') screen = renderFirstRunDone();
    else if (overlay === 'first-run-failed') screen = views.firstRunFailed(s, firstRunError);
    else screen = views.home(s, activity, answer, { debug });
    out.write(CLEAR + screen);
  };

  function renderProjectBrowse() {
    return ['', '  Open project', '', '  Enter a folder path:', '', '  > ' + s.input, '', '  Enter confirm · Esc cancel', '', '  ' + views.statusBar(s)].join('\n');
  }

  function renderSettingsEdit() {
    return [
      '', '  Change a setting',
      '', '  theme <auto|dark|light>   language <system|en|id>   context <auto|manual>   debug <on|off>',
      '', '  > ' + s.input,
      '', '  Enter apply · Esc cancel',
      '', '  ' + views.statusBar(s),
    ].join('\n');
  }

  function renderRuntimeStopped() {
    const L = ['', '  Local AI is stopped.', ''];
    if (runtimeStoppedInfo && runtimeStoppedInfo.busyOwner) L.push(`  Owned by ${runtimeStoppedInfo.busyOwner} — stop it there first.`, '');
    L.push('  [S] Start    [M] Change model    [D] Details    [Esc] Close');
    L.push('', '  ' + views.statusBar(s));
    return L.join('\n');
  }

  function renderFirstRunRecommend() {
    if (!firstRunRec || !firstRunRec.recommendation) {
      return ['', '  No suitable local model found for this hardware.', '', '  [N] Use cloud instead    [Esc] Cancel', '', '  ' + views.statusBar(s)].join('\n');
    }
    const m = firstRunRec.recommendation.model;
    const hw = firstRunRec.hardware;
    const sizeNote = firstRunResolved ? `~${firstRunResolved.group.size ? (firstRunResolved.group.size / 1e9).toFixed(1) + 'GB' : m.download_size_gb + 'GB'}` : `~${m.download_size_gb}GB (checking exact size…)`;
    return [
      '', '  Recommended for your machine',
      '', `  ${m.name}  (${sizeNote})`,
      `  ${m.category} · ${firstRunRec.recommendation.fit.label}`,
      `  Detected: ${hw.ramGb}GB RAM · ${hw.cpu.trim()}${hw.nvidia.length ? ' · ' + hw.nvidia[0].name : ''}`,
      `  Acceleration: ${hw.nvidia.length ? 'CUDA (NVIDIA)' : 'Vulkan (auto-selected if available, else CPU)'}`,
      '', '  This downloads once, to your BotConnector models folder. Nothing downloads until you approve.',
      '', '  [Y] Download    [A] See alternatives    [N] Use cloud instead    [Esc] Cancel',
      '', '  ' + views.statusBar(s),
    ].join('\n');
  }

  function renderFirstRunProgress() {
    const p = firstRunProgressState;
    const pct = p.pct || (p.totalBytes ? Math.round((p.downloadedBytes / p.totalBytes) * 100) : 0);
    const fmtB = (n) => !n ? '0MB' : (n / 1e9 >= 1 ? (n / 1e9).toFixed(1) + 'GB' : Math.round(n / 1e6) + 'MB');
    return [
      '', `  ${p.status === 'installing-runtime' ? 'Installing runtime…' : `Downloading ${firstRunRec.recommendation.model.name}… ${pct}%`}`,
      '', '  ' + '█'.repeat(Math.round(pct / 100 * 30)) + '░'.repeat(30 - Math.round(pct / 100 * 30)),
      p.status !== 'installing-runtime' ? `  ${fmtB(p.downloadedBytes)} / ${fmtB(p.totalBytes)}` : `  ${p.note || ''}`,
      '', '  Esc cancel',
      '', '  ' + views.statusBar(s),
    ].join('\n');
  }

  function renderFirstRunDone() {
    return [
      '', '  Model ready — starting chat…',
      '', `  ${firstRunRec.recommendation.model.name}`,
      '', '  Enter continue',
      '', '  ' + views.statusBar(s),
    ].join('\n');
  }

  function recommendCtxK(requiredTokens) {
    const tiers = [4, 8, 16, 32, 64];
    const needK = (requiredTokens || 0) / 1024;
    return tiers.find((k) => k >= needK) || Math.ceil(needK);
  }

  function relTime(ts) {
    const diff = Date.now() - ts;
    const m = Math.floor(diff / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return m + 'm ago';
    const h = Math.floor(m / 60);
    if (h < 24) return h + 'h ago';
    return Math.floor(h / 24) + 'd ago';
  }

  function applyFilter(ps) {
    const f = (ps.filter || '').toLowerCase();
    ps.filtered = !f ? ps.items : ps.items.filter((it) => (it.label + ' ' + (it.provider || '')).toLowerCase().includes(f));
    if (ps.index >= ps.filtered.length) ps.index = Math.max(0, ps.filtered.length - 1);
  }

  async function persistSettings() { await state.save(s); }

  function setMode(newMode) {
    if (s.mode === newMode) { draw(); return; }
    s.mode = newMode;
    persistSettings();
    activity.push(`✓ Switched to ${newMode} mode`);
    draw();
  }

  function showPermissionsInfo() {
    answer = `Approval: ${s.approval} · Shift+Tab toggles ask ↔ full-auto (full-auto is explicit opt-in).`;
    draw();
  }

  async function doNew() {
    activity = []; answer = ''; s.usedTokens = 0; ctxFullShown = false;
    sess = await sessions.create({ project: s.project, model: s.model, mode: s.mode });
    draw();
  }

  function maybeShowContextFull() {
    const pct = (s.usedTokens || 0) / (s.runtime.nCtx || 1);
    if (pct >= 0.8 && !ctxFullShown && overlay === null) {
      ctxFullShown = true;
      overlay = 'context-full';
    }
  }

  function showError(err) {
    errorState = Object.assign({ showDetails: false }, err);
    overlay = 'error';
    draw();
  }

  function setProject(p) {
    s.workspace = p;
    s.project = path.basename(p) || p;
    projects.touch(p);
    activity.push(`✓ Project: ${s.project}`);
  }

  function openPalette() {
    pickerState = {
      kind: 'palette', title: 'Command Palette', showFilter: true, filter: '', index: 0,
      items: PALETTE_ACTIONS.map((a) => ({ label: a.label, detail: a.shortcut, _action: a })),
      hint: 'Type to search · Up/Down move · Enter run · Esc cancel',
    };
    applyFilter(pickerState);
    overlay = 'picker'; draw();
  }

  async function openModelPicker() {
    pickerState = { kind: 'model', title: 'Select model', index: 0, items: [{ label: 'Loading…', disabled: true }], hint: 'Up/Down move · Enter select · Esc cancel' };
    applyFilter(pickerState);
    overlay = 'picker'; draw();
    const mine = pickerState;
    const { items } = await modelSource.listModels(s);
    if (pickerState !== mine) return;
    mine.items = items.concat([{ label: 'Find more models…', detail: 'Search Hugging Face (botconnector models search)', disabled: false, _findMore: true }]);
    applyFilter(mine);
    if (overlay === 'picker' && pickerState === mine) draw();
  }

  function openProjectPicker() {
    const recent = projects.load().filter((p) => p.path !== s.workspace);
    pickerState = {
      kind: 'project', title: 'Open project', index: 0,
      items: [
        { label: 'Current folder', detail: s.workspace, provider: 'Current', active: true, _action: { type: 'set', path: s.workspace } },
        ...recent.map((p) => ({ label: p.name, detail: p.path, provider: 'Recent', _action: { type: 'set', path: p.path } })),
        { label: 'Browse / enter a path…', _action: { type: 'browse' } },
      ],
      hint: 'Up/Down move · Enter open · Esc cancel',
    };
    applyFilter(pickerState);
    overlay = 'picker'; draw();
  }

  function openSessions() {
    const list = sessions.list();
    pickerState = {
      kind: 'sessions', title: 'Sessions', index: 0,
      items: list.length
        ? list.map((sx) => ({ label: sx.title, provider: sx.project, status: relTime(sx.lastUsed), detail: `${sx.messageCount} messages · model: ${(sx.model && sx.model.name) || '—'}`, _action: sx.id }))
        : [{ label: 'No sessions yet', disabled: true }],
      hint: list.length ? 'Enter resume · Del delete · Esc close' : 'Esc close',
    };
    applyFilter(pickerState);
    overlay = 'picker'; draw();
  }

  function openSettings() { overlay = 'settings'; draw(); }

  async function openDoctor(showDetails) {
    doctorDetails = !!showDetails;
    overlay = 'doctor'; doctorResult = doctorResult || {}; draw();
    doctorResult = await doctorMod.check(s);
    if (overlay === 'doctor') draw();
  }

  async function openStatus() {
    overlay = 'status'; draw();
    const resolved = await local.resolveEndpoint().catch(() => ({ endpoint: local.DEFAULT_ENDPOINT }));
    const probe = await local.discoverLocalModel({ endpoint: resolved.endpoint, timeoutMs: 1200 }).catch(() => ({ ok: false }));
    statusExtra = { provider: s.model.provider, modelId: probe.ok ? probe.id : s.modelId, endpoint: resolved.endpoint };
    if (overlay === 'status') draw();
  }

  const PALETTE_ACTIONS = [
    { label: 'New session', shortcut: '/new', run: () => doNew() },
    { label: 'Change model', shortcut: '/model', run: () => openModelPicker() },
    { label: 'Open project', shortcut: '/project', run: () => openProjectPicker() },
    { label: 'Plan mode', shortcut: 'Tab', run: () => setMode('Plan') },
    { label: 'Act mode', shortcut: 'Tab', run: () => setMode('Act') },
    { label: 'Permissions', shortcut: 'Shift+Tab', run: () => showPermissionsInfo() },
    { label: 'Sessions', shortcut: '/sessions', run: () => openSessions() },
    { label: 'Settings', shortcut: '/settings', run: () => openSettings() },
    { label: 'Status', shortcut: '/status', run: () => openStatus() },
    { label: 'Doctor', shortcut: '/doctor', run: () => openDoctor(false) },
    { label: 'Exit', shortcut: 'Ctrl+C', run: () => { restore(); process.exit(0); } },
  ];

  async function handlePickerSelect(ps, it) {
    if (ps.kind === 'palette') { overlay = null; draw(); it._action && it._action.run(); return; }

    if (ps.kind === 'model') {
      if (it._findMore) {
        overlay = null;
        answer = 'Search more models from a terminal: botconnector models search "<query>" — then botconnector get <repo>@QUANT, or pick it here next time it’s installed.';
        draw();
        return;
      }
      if (it.kind === 'local' && it.selectable) {
        s.model = { name: it.label, locality: 'Local', backend: s.runtime.backend, provider: 'llama.cpp', cost: '$0.00' };
        s.modelId = it.modelPath;
      } else if (it.kind === 'ollama') {
        s.model = { name: it.label, locality: 'Local', backend: 'Ollama', provider: 'Ollama', cost: '$0.00' };
        s.modelId = it.id;
      } else if (it.kind === 'cloud') {
        s.model = { name: '<model>', locality: 'Cloud', backend: 'remote', provider: '<provider>', cost: '$...' };
        s.modelId = null;
      } else { overlay = null; draw(); return; }
      await persistSettings();
      activity.push(`✓ Model: ${s.model.name}`);
      overlay = null; draw();
      return;
    }

    if (ps.kind === 'project') {
      overlay = null;
      if (it._action.type === 'browse') { overlay = 'project-browse'; s.input = ''; draw(); return; }
      setProject(it._action.path);
      draw();
      return;
    }

    if (ps.kind === 'sessions') {
      overlay = null;
      const loaded = sessions.load(it._action);
      if (loaded) {
        sess = loaded;
        s.project = loaded.project || s.project;
        if (loaded.model) s.model = loaded.model;
        if (loaded.mode) s.mode = loaded.mode;
        activity = [];
        answer = loaded.messages.length ? `Resumed "${loaded.title}" (${loaded.messages.length} messages).` : '';
      }
      draw();
      return;
    }

    overlay = null; draw();
  }

  async function beginFirstRunRecommend() {
    firstRunRec = await firstRun.recommend();
    firstRunResolved = null;
    overlay = 'first-run-recommend'; draw();
    if (firstRunRec.recommendation) {
      try { firstRunResolved = await firstRun.resolveDownloadable(firstRunRec.recommendation.model, firstRunRec.hardware); }
      catch (e) { firstRunResolved = null; }
      if (overlay === 'first-run-recommend') draw();
    }
  }

  function startFirstRunDownload() {
    if (!firstRunResolved) { firstRunError = 'Could not resolve a downloadable file for this model.'; overlay = 'first-run-failed'; draw(); return; }
    overlay = 'first-run-progress';
    firstRunProgressState = { pct: 0, downloadedBytes: 0, totalBytes: firstRunResolved.group.size, status: 'downloading' };
    draw();
    const dm = firstRun.makeDownloader({
      store: s.store,
      emit: (channel, payload) => {
        if (channel !== 'download:progress' || payload.id !== firstRunJobId) return;
        firstRunProgressState = { pct: payload.totalBytes ? Math.round((payload.downloadedBytes / payload.totalBytes) * 100) : 0, downloadedBytes: payload.downloadedBytes, totalBytes: payload.totalBytes, status: payload.status };
        if (overlay === 'first-run-progress') draw();
        if (payload.status === 'completed') afterDownloadComplete().catch((e) => { firstRunError = e.message; overlay = 'first-run-failed'; draw(); });
        else if (payload.status === 'failed') { firstRunError = payload.error || 'Download failed'; overlay = 'first-run-failed'; draw(); }
        else if (payload.status === 'cancelled') { overlay = null; draw(); }
      },
    });
    dm.start({ repoId: firstRunResolved.repoId, group: firstRunResolved.group, metadata: { capabilities: firstRunResolved.details.capabilities, pipeline_tag: firstRunResolved.details.pipeline_tag } })
      .then((job) => { firstRunJobId = job.id; });
    firstRunDownloadManager = dm;
  }
  let firstRunDownloadManager = null;

  async function afterDownloadComplete() {
    firstRunProgressState = { ...firstRunProgressState, status: 'installing-runtime', note: 'Setting up the local runtime…' };
    draw();
    const rt = await firstRun.ensureRuntimeInstalled({
      userDataDir: state.userDataDir(), backend: s.runtime.backend,
      emit: (ch, p) => { if (ch === 'runtime:install-progress') { firstRunProgressState = { ...firstRunProgressState, note: p.status || '' }; if (overlay === 'first-run-progress') draw(); } },
    });
    const installed = await scanInstalled(s.store.get('modelsDir'));
    const picked = installed.find((m) => m.repoId === firstRunResolved.repoId) || installed[installed.length - 1];
    const backend = rt.backend || (s.runtime.backend === 'auto' ? 'vulkan' : s.runtime.backend);
    const started = await firstRun.startRuntime({ binary: rt.binary, modelPath: picked.path, projector: picked.projector, backend, context: 8192, port: 11435 });
    s.runtime.backend = backend;
    await persistSettings();
    let ready = false;
    for (let i = 0; i < 45 && !ready; i++) {
      const r = await local.discoverLocalModel({ endpoint: 'http://127.0.0.1:11435/v1', timeoutMs: 2000 });
      if (r.ok) { ready = true; s.model = { name: r.friendly, locality: 'Local', backend, provider: 'llama.cpp', cost: '$0.00' }; s.modelId = r.id; if (r.nCtx) s.runtime.nCtx = r.nCtx; }
      else await new Promise((res) => setTimeout(res, 1500));
    }
    s.firstRunDone = true;
    await persistSettings();
    overlay = ready ? 'first-run-done' : 'first-run-failed';
    if (!ready) firstRunError = 'Runtime installed but did not become ready in time.';
    draw();
  }

  async function tryStartLastRuntime() {
    overlay = 'first-run-progress';
    firstRunRec = firstRunRec || { recommendation: { model: { name: s.model.name || 'local model' } } };
    firstRunProgressState = { status: 'installing-runtime', note: 'Checking managed runtime…' };
    draw();
    try {
      const owner = await readOwnership(statePath());
      if (owner && pidAlive(owner.childPid != null ? owner.childPid : owner.ownerPid) && owner.ownerType && owner.ownerType !== 'cli-tui') {
        runtimeStoppedInfo = { busyOwner: owner.ownerType };
        overlay = 'runtime-stopped'; draw(); return;
      }
      const installed = await scanInstalled(s.store.get('modelsDir'));
      const picked = installed.find((m) => m.path === s.modelId) || installed[0];
      if (!picked) { overlay = null; await openModelPicker(); answer = 'No local model installed yet — pick "Find more models…" or use /get from a terminal.'; draw(); return; }
      const rt = await firstRun.ensureRuntimeInstalled({ userDataDir: state.userDataDir(), backend: s.runtime.backend, emit: () => {} });
      const backend = rt.backend || (s.runtime.backend === 'auto' ? 'vulkan' : s.runtime.backend);
      await firstRun.startRuntime({ binary: rt.binary, modelPath: picked.path, projector: picked.projector, backend, context: s.runtime.nCtx || 8192, port: 11435 });
      let ready = false;
      for (let i = 0; i < 45 && !ready; i++) {
        const r = await local.discoverLocalModel({ endpoint: 'http://127.0.0.1:11435/v1', timeoutMs: 2000 });
        if (r.ok) { ready = true; s.model = { name: r.friendly, locality: 'Local', backend, provider: 'llama.cpp', cost: '$0.00' }; s.modelId = r.id; if (r.nCtx) s.runtime.nCtx = r.nCtx; }
        else await new Promise((res) => setTimeout(res, 1500));
      }
      overlay = null;
      activity.push(ready ? `✓ Local runtime started (${backend})` : '○ Runtime did not become ready in time');
      await persistSettings();
      draw();
    } catch (e) {
      showError({ title: 'Could not start the local runtime.', body: 'See details for the exact error.', actions: ['Choose another model'], raw: e.message, onAction: (n) => { overlay = null; if (n === 1) openModelPicker(); else draw(); } });
    }
  }

  readline.emitKeypressEvents(process.stdin);
  process.stdin.setRawMode(true);
  process.stdin.resume();

  if (!s.firstRunDone) {
    const resolved = await local.resolveEndpoint();
    const probe = await local.discoverLocalModel({ endpoint: resolved.endpoint, timeoutMs: 1200 });
    const installed = await scanInstalled(s.store.get('modelsDir')).catch(() => []);
    if (!probe.ok && installed.length === 0) {
      pickerState = views.firstRunWelcome();
      applyFilter(pickerState);
      pickerState.kind = 'first-run';
      overlay = 'picker';
    } else {
      s.firstRunDone = true; await persistSettings();
    }
  }
  if (overlay === null && pendingWarning) { pendingGuard = g; overlay = 'context-needs-larger'; }
  draw();

  const pushActivity = (t) => { activity.push(t.text || t); if (!debug) activity = activity.slice(-8); draw(); };

  const submit = async () => {
    const prompt = s.input.trim(); s.input = '';
    if (!prompt) { draw(); return; }
    if (prompt.startsWith('/')) return slash(prompt);
    if (prompt.startsWith('@')) { activity.push(`● Reading ${prompt.slice(1)}`); draw(); return; }
    activity.push('● Contacting local runtime…'); draw();
    const resolved = await local.resolveEndpoint();
    const found = await local.discoverLocalModel({ endpoint: resolved.endpoint, timeoutMs: 5000 });
    if (!found.ok) {
      activity.pop();
      runtimeStoppedInfo = null;
      overlay = 'runtime-stopped';
      draw();
      return;
    }
    s.model = { name: found.friendly, locality: s.model.locality === 'Local' ? 'Local' : s.model.locality, backend: resolved.ownerType ? (statusExtra.backend || s.runtime.backend) : s.runtime.backend, provider: 'llama.cpp', cost: '$0.00' };
    s.modelId = found.id;
    if (found.nCtx) s.runtime.nCtx = found.nCtx;
    const need = ctxGuard.guard({ nCtx: s.runtime.nCtx, plannedUserTokens: ctxGuard.estimateTokens(prompt) });
    if (!need.ok && !s.contextBumpAcked[found.id]) {
      pendingGuard = need; overlay = 'context-needs-larger'; draw(); return;
    }
    generating = true;
    genAbort = new AbortController();
    answer = '';
    activity.push(`● Streaming from ${found.friendly}… (Esc cancels)`); draw();
    const history = sessions.historyFor(sess);
    const r = await loop.runTurn({
      prompt, mode: s.mode, approval: s.approval, model: s.model,
      tools, cwd: process.cwd(), workspace: s.workspace, onEvent: pushActivity,
      localCtx: { endpoint: found.endpoint, modelId: found.id, friendly: found.friendly },
      signal: genAbort.signal,
      debugLog: debug ? log : null,
      session: taskSession,
      history,
      onToken: (t) => { answer += t; draw(); },
      onApproval: (req) => new Promise((resolve) => {
        approvalReq = req; approvalResolve = resolve; diffFull = false;
        overlay = req.kind === 'command' ? 'approve-command' : 'approve-diff';
        draw();
      }),
    });
    generating = false; genAbort = null;
    s.usedTokens += ctxGuard.estimateTokens(prompt) + ctxGuard.estimateTokens(r.answer || '');
    if (r.cancelled) {
      answer = r.answer || '(cancelled)';
    } else if (r.failed) {
      showError({
        title: 'Local inference failed.', body: 'The local model could not complete this request.',
        actions: ['Retry'], raw: r.answer,
        onAction: (n) => { overlay = null; if (n === 1) { s.input = prompt; submit(); } else draw(); },
      });
    } else {
      if (!r.streamed) answer = r.answer;
      activity.push('✓ Response ready');
    }
    await sessions.recordTurn(sess, { prompt, answer: r.answer, project: s.project, model: s.model, mode: s.mode });
    maybeShowContextFull();
    await persistSettings(); draw();
  };

  const slash = async (cmd) => {
    const parts = cmd.split(/\s+/);
    const name = parts[0];
    switch (name) {
      case '/exit': restore(); process.exit(0); break;
      case '/clear': activity = []; answer = ''; draw(); break;
      case '/new': await doNew(); break;
      case '/model': await openModelPicker(); break;
      case '/project': openProjectPicker(); break;
      case '/sessions': openSessions(); break;
      case '/settings':
        if (parts.length >= 3) await applySettingCommand(parts[1], parts.slice(2).join(' '));
        else openSettings();
        break;
      case '/status': await openStatus(); break;
      case '/doctor': await openDoctor(false); break;
      case '/details': await openDoctor(true); break;
      case '/context': answer = `Context ${Math.round(((s.usedTokens || 0) / (s.runtime.nCtx || 1)) * 100)}% · runtime n_ctx=${s.runtime.nCtx}`; draw(); break;
      case '/permissions': showPermissionsInfo(); break;
      case '/mcp': answer = 'MCP servers are configured via the Desktop app (Settings → MCP) — shared with this TUI.'; draw(); break;
      case '/debug': debug = !debug; s.settings.debugMode = debug; await persistSettings(); answer = 'Debug mode: ' + (debug ? 'on' : 'off'); draw(); break;
      default: answer = 'Unknown command ' + name + ' — press Ctrl+P for the command palette.'; draw();
    }
    log('slash', cmd);
  };

  async function applySettingCommand(key, value) {
    value = String(value || '').trim();
    const ok = (msg) => { answer = '✓ ' + msg; draw(); };
    const bad = (msg) => { answer = '✗ ' + msg; draw(); };
    if (key === 'theme') { if (!['auto', 'dark', 'light'].includes(value)) return bad('theme must be auto|dark|light'); s.settings.theme = value; await persistSettings(); return ok('theme set to ' + value); }
    if (key === 'language') { if (!['system', 'en', 'id'].includes(value)) return bad('language must be system|en|id'); s.settings.language = value; await persistSettings(); return ok('language set to ' + value); }
    if (key === 'context') { if (!['auto', 'manual'].includes(value)) return bad('context must be auto|manual'); s.settings.contextPreference = value; await persistSettings(); return ok('context preference set to ' + value); }
    if (key === 'debug') { if (!['on', 'off'].includes(value)) return bad('debug must be on|off'); s.settings.debugMode = value === 'on'; debug = s.settings.debugMode; await persistSettings(); return ok('debug ' + value); }
    if (key === 'approval') { if (!['ask', 'full-auto'].includes(value)) return bad('approval must be ask|full-auto'); s.approval = value; s.settings.approvalBehavior = value; await persistSettings(); return ok('approval set to ' + value); }
    return bad('unknown setting: ' + key);
  }

  process.stdin.on('keypress', async (ch, k = {}) => {
    log('key', JSON.stringify(k));

    if (overlay === 'picker') {
      const ps = pickerState;
      if (k.name === 'escape') { overlay = null; draw(); return; }
      if (k.name === 'up') { ps.index = Math.max(0, ps.index - 1); draw(); return; }
      if (k.name === 'down') { ps.index = Math.min(Math.max(0, ps.filtered.length - 1), ps.index + 1); draw(); return; }
      if (ps.kind === 'sessions' && k.name === 'delete') {
        const it = ps.filtered[ps.index];
        if (it && it._action) { await sessions.remove(it._action); openSessions(); }
        return;
      }
      if (k.name === 'return') {
        const it = ps.filtered[ps.index];
        if (ps.kind === 'first-run') {
          overlay = null;
          if (/recommended/i.test(it.label)) await beginFirstRunRecommend();
          else if (/another model/i.test(it.label)) await openModelPicker();
          else { s.firstRunDone = true; await persistSettings(); s.model = { name: '<model>', locality: 'Cloud', backend: 'remote', provider: '<provider>', cost: '$...' }; draw(); }
          return;
        }
        if (ps.kind === 'first-run-alt') {
          if (!it || !it._model) { overlay = 'first-run-recommend'; draw(); return; }
          firstRunRec = { ...firstRunRec, recommendation: { model: it._model, fit: { label: it.provider } } };
          overlay = 'first-run-recommend'; draw();
          firstRun.resolveDownloadable(it._model, firstRunRec.hardware)
            .then((resolved) => { firstRunResolved = resolved; if (overlay === 'first-run-recommend') draw(); })
            .catch(() => { firstRunResolved = null; });
          return;
        }
        if (!it || it.disabled) { draw(); return; }
        await handlePickerSelect(ps, it);
        return;
      }
      if (ps.showFilter) {
        if (k.name === 'backspace') { ps.filter = (ps.filter || '').slice(0, -1); applyFilter(ps); draw(); return; }
        if (ch && ch.length === 1 && !k.ctrl && !k.meta) { ps.filter = (ps.filter || '') + ch; applyFilter(ps); draw(); return; }
      }
      return;
    }

    if (overlay === 'project-browse') {
      if (k.name === 'escape') { overlay = null; s.input = ''; draw(); return; }
      if (k.name === 'return') {
        const p = s.input.trim(); s.input = '';
        const fs2 = require('fs');
        try {
          const st = fs2.statSync(p);
          if (st.isDirectory()) { setProject(p); overlay = null; }
          else showError({ title: 'Not a folder', body: p, actions: [] });
        } catch (e) { showError({ title: 'Folder not found', body: p, actions: [], raw: e.message }); }
        draw();
        return;
      }
      if (k.name === 'backspace') { s.input = s.input.slice(0, -1); draw(); return; }
      if (ch && ch.length === 1 && !k.ctrl && !k.meta) { s.input += ch; draw(); return; }
      return;
    }

    if (overlay === 'settings-edit') {
      if (k.name === 'escape') { overlay = null; s.input = ''; draw(); return; }
      if (k.name === 'return') {
        const [key, ...rest] = s.input.trim().split(/\s+/); s.input = ''; overlay = null;
        if (key) await applySettingCommand(key, rest.join(' '));
        else draw();
        return;
      }
      if (k.name === 'backspace') { s.input = s.input.slice(0, -1); draw(); return; }
      if (ch && ch.length === 1 && !k.ctrl && !k.meta) { s.input += ch; draw(); return; }
      return;
    }

    if (overlay === 'approve-diff' || overlay === 'approve-command') {
      const c = (ch || '').toLowerCase();
      const done = (verdict) => {
        const res = approvalResolve; approvalReq = null; approvalResolve = null; overlay = null; diffFull = false;
        activity.push(verdict.approved ? (verdict.approveAll ? '✓ Approved (all remaining this task)' : '✓ Approved') : '✗ Rejected — nothing changed.');
        draw();
        res(verdict);
      };
      if (overlay === 'approve-diff' && c === 'v') { diffFull = !diffFull; draw(); return; }
      if (k.name === 'escape' || c === 'n') done({ approved: false });
      else if (ch === 'A') done({ approved: true, approveAll: true });
      else if (k.name === 'return' || c === 'y') done({ approved: true });
      return;
    }

    if (overlay === 'context-needs-larger') {
      const c = (ch || '').toLowerCase();
      const modelKey = s.modelId || 'default';
      if (c === 'r') {
        const recK = recommendCtxK(pendingGuard.required);
        overlay = null; draw();
        try {
          const owner = await readOwnership(statePath());
          if (owner && pidAlive(owner.childPid != null ? owner.childPid : owner.ownerPid) && owner.ownerType !== 'cli-tui') {
            answer = `Local AI's context is managed by ${owner.ownerType} — open it there to increase context to ${recK}K.`;
          } else {
            const installed = await scanInstalled(s.store.get('modelsDir'));
            const picked = installed.find((m) => m.path === s.modelId) || installed[0];
            if (picked && owner) {
              if (llama.status().running) llama.stopLlama();
              await releaseOwnership(statePath()).catch(() => {});
              const rt = await firstRun.ensureRuntimeInstalled({ userDataDir: state.userDataDir(), backend: s.runtime.backend, emit: () => {} });
              await firstRun.startRuntime({ binary: rt.binary, modelPath: picked.path, projector: picked.projector, backend: owner.backend || 'vulkan', context: recK * 1024, port: 11435 });
              answer = `Restarted with ${recK}K context.`;
              s.runtime.nCtx = recK * 1024;
            } else {
              answer = `Restart BotConnector's local runtime with ${recK}K context (Desktop: Runtime settings, or CLI: botconnector server start <model> --ctx ${recK * 1024}).`;
            }
          }
        } catch (e) { answer = 'Could not restart automatically: ' + e.message; }
        s.contextBumpAcked[modelKey] = true; await persistSettings(); draw(); return;
      }
      if (c === 'c') { s.contextBumpAcked[modelKey] = true; overlay = null; await persistSettings(); draw(); return; }
      if (k.name === 'escape') { overlay = null; draw(); return; }
      return;
    }

    if (overlay === 'context-full') {
      const c = (ch || '').toLowerCase();
      if (c === 'c') { s.usedTokens = 0; ctxFullShown = false; overlay = null; activity.push('✓ Context reset'); await persistSettings(); draw(); return; }
      if (c === 'n') { await doNew(); overlay = null; draw(); return; }
      if (k.name === 'escape') { overlay = null; draw(); return; }
      return;
    }

    if (overlay === 'doctor') {
      const c = (ch || '').toLowerCase();
      if (c === 'd') { doctorDetails = !doctorDetails; draw(); return; }
      if (k.name === 'escape') { overlay = null; draw(); return; }
      return;
    }

    if (overlay === 'settings' || overlay === 'status') {
      if (k.name === 'escape') { overlay = null; draw(); return; }
      if (overlay === 'settings' && (ch || '').toLowerCase() === 'e') { overlay = 'settings-edit'; s.input = ''; draw(); return; }
      return;
    }

    if (overlay === 'error') {
      const c = (ch || '').toLowerCase();
      const n = ch && /[1-9]/.test(ch) ? Number(ch) : null;
      if (c === 'd') { errorState.showDetails = !errorState.showDetails; draw(); return; }
      if (k.name === 'escape') { overlay = null; draw(); return; }
      if (n && errorState.onAction) { errorState.onAction(n); return; }
      return;
    }

    if (overlay === 'runtime-stopped') {
      const c = (ch || '').toLowerCase();
      if (c === 's') { await tryStartLastRuntime(); return; }
      if (c === 'm') { overlay = null; await openModelPicker(); return; }
      if (c === 'd') { overlay = null; await openDoctor(true); return; }
      if (k.name === 'escape') { overlay = null; draw(); return; }
      return;
    }

    if (overlay === 'first-run-recommend') {
      const c = (ch || '').toLowerCase();
      if (c === 'y') { startFirstRunDownload(); return; }
      if (c === 'a' && firstRunRec.alternatives.length) {
        pickerState = {
          kind: 'first-run-alt', title: 'Alternatives', index: 0,
          items: firstRunRec.alternatives.map((a) => ({ label: a.model.name, provider: a.fit.label, status: `${a.model.download_size_gb}GB`, _model: a.model })),
          hint: 'Enter select · Esc back',
        };
        applyFilter(pickerState);
        overlay = 'picker'; draw();
        return;
      }
      if (c === 'n' || k.name === 'escape') { overlay = null; s.firstRunDone = true; await persistSettings(); s.model = { name: '<model>', locality: 'Cloud', backend: 'remote', provider: '<provider>', cost: '$...' }; draw(); return; }
      return;
    }
    if (overlay === 'first-run-progress') {
      if (k.name === 'escape') { if (firstRunDownloadManager && firstRunJobId) firstRunDownloadManager.cancel(firstRunJobId); overlay = null; draw(); return; }
      return;
    }
    if (overlay === 'first-run-done') {
      if (k.name === 'return' || k.name === 'escape') { overlay = null; draw(); return; }
      return;
    }
    if (overlay === 'first-run-failed') {
      const c = (ch || '').toLowerCase();
      if (c === 'r') { overlay = 'first-run-recommend'; draw(); return; }
      if (k.name === 'escape') { overlay = null; s.firstRunDone = true; await persistSettings(); draw(); return; }
      return;
    }

    if (k.ctrl && k.name === 'c') { restore(); process.exit(0); }
    else if (k.name === 'return') await submit();
    else if (k.name === 'escape') {
      if (generating && genAbort) { genAbort.abort(); activity.push('○ Cancelling… (runtime untouched)'); draw(); }
      else { s.input = ''; draw(); }
    }
    else if (k.name === 'tab' && k.shift) {
      s.approval = s.approval === 'ask' ? 'full-auto' : 'ask';
      s.settings.approvalBehavior = s.approval;
      activity.push(`✓ Approval: ${s.approval}` + (s.approval === 'full-auto' ? ' (explicit opt-in — recorded)' : ''));
      await persistSettings(); draw();
    }
    else if (k.name === 'tab') { setMode(s.mode === 'Plan' ? 'Act' : 'Plan'); }
    else if (k.ctrl && k.name === 'p') { openPalette(); }
    else if (k.name === 'backspace') { s.input = s.input.slice(0, -1); draw(); }
    else if (ch === '/' && !s.input) { openPalette(); }
    else if (ch && ch.length === 1 && !k.ctrl && !k.meta) { s.input += ch; draw(); }
  });
}

module.exports = { runTui };
