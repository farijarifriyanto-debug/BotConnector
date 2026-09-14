// Pure view renderers — no I/O, no timers. Used by the live TUI AND the
// acceptance snapshots. Every screen ends with the same compact status bar
// so the model/project/context picture never disappears.
'use strict';
const theme = require('./theme.cjs');
const layout = require('./layout.cjs');
const activityMod = require('./activity.cjs');
const doctor = require('../doctor.cjs');

function fmtBytes(n) {
  if (!n && n !== 0) return '';
  const gb = n / 1e9;
  return gb >= 1 ? `${gb.toFixed(gb >= 10 ? 0 : 1)}GB` : `${Math.round(n / 1e6)}MB`;
}

function friendlyProject(s) {
  return s.project || (s.workspace ? s.workspace.split(/[\\/]/).pop() : 'workspace');
}

function accelLabel(m) {
  if (m.locality !== 'Local') return '';
  return m.backend && /vulkan|cuda|rocm|gpu|metal/i.test(m.backend) ? 'GPU' : 'CPU';
}

// ---- status bar: one compact line, no duplicate fields, responsive ----
function statusBar(s) {
  const m = s.model;
  const pct = Math.max(0, Math.min(999, Math.round(((s.usedTokens || 0) / (s.runtime.nCtx || 1)) * 100)));
  const modelSeg = m.locality === 'Local'
    ? `${m.name} · Local${accelLabel(m) ? ' ' + accelLabel(m) : ''}`
    : `${m.name} · Cloud`;
  if (layout.isNarrow())
    return layout.truncate(`${modelSeg} · ${s.mode} · ${pct}%`, layout.width() - 2);
  const projectSeg = `${friendlyProject(s)} · ${s.mode}`;
  return [modelSeg, projectSeg, `Context ${pct}%`].join('     ');
}

function hintLine(s) {
  if (layout.isNarrow()) return '/ commands · Ctrl+P menu';
  return '/model  /project  /new  /settings     Ctrl+P more     Tab Plan/Act';
}

function wrapText(text, w) {
  w = Math.max(20, w);
  const out = [];
  for (const para of String(text == null ? '' : text).split('\n')) {
    if (!para) { out.push(''); continue; }
    let line = '';
    for (const word of para.split(' ')) {
      const next = line ? line + ' ' + word : word;
      if (next.length > w) { if (line) out.push(line); line = word; }
      else line = next;
    }
    if (line) out.push(line);
  }
  return out;
}

// ---- home ----
function home(s, activity = [], answer = '', opts = {}) {
  const L = [''];
  L.push('  ' + theme.bold('BotConnector AI'));
  L.push('');
  const lines = activityMod.humanize(activity, { debug: opts.debug || (s.settings && s.settings.debugMode) });
  if (!lines.length && !answer) {
    L.push('  What do you want to build?');
    L.push('');
  } else {
    for (const a of lines.slice(-8)) L.push('  ' + a);
    if (answer) {
      L.push('');
      for (const line of wrapText(answer, layout.width() - 4)) L.push('  ' + line);
    }
    L.push('');
  }
  const idle = !lines.length && !answer;
  const placeholder = idle ? theme.dim('Ask anything…') : '';
  L.push('  > ' + (s.input || placeholder));
  L.push('');
  L.push('  ' + statusBar(s));
  L.push('  ' + hintLine(s));
  return L.join('\n');
}

// ---- generic list picker (model / project / palette / sessions) ----
function picker(s, p) {
  const items = p.filtered || p.items || [];
  const L = ['', '  ' + theme.bold(p.title)];
  if (p.showFilter) L.push('  ' + theme.dim('Search: ') + (p.filter || theme.dim('type to filter')));
  L.push('');
  if (!items.length) L.push('  ' + theme.dim('No matches'));
  items.forEach((it, i) => {
    const cursor = i === p.index ? '›' : ' ';
    const mark = it.active ? '●' : ' ';
    const left = `${cursor} ${mark} ${it.label}`;
    const right = [it.provider, it.status].filter(Boolean).join('   ');
    L.push('  ' + layout.spread(left, right, layout.width() - 2));
    if (it.detail && i === p.index) L.push('      ' + theme.dim(it.detail));
  });
  L.push('');
  L.push('  ' + (p.hint || 'Up/Down move · Enter select · Esc cancel'));
  L.push('');
  L.push('  ' + statusBar(s));
  return L.join('\n');
}

// ---- approvals: diff / create / delete / rename / command ----
function renderDiffLines(body) {
  const out = [];
  for (const l of String(body || '').split('\n')) {
    if (l.startsWith('--- a/') || l.startsWith('+++ b/')) continue;
    if (/^\(-?\d+ \/ \+?\d+ lines\)$/.test(l) || /more diff lines\)$/.test(l)) { out.push(theme.dim(l)); continue; }
    if (l.startsWith('-')) out.push(theme.red(l));
    else if (l.startsWith('+')) out.push(theme.green(l));
    else out.push(theme.dim(l));
  }
  return out;
}

function fullDiffBody(proposal) {
  if (!proposal || !proposal.diff || !proposal.diff.hunks) return null;
  return proposal.diff.hunks.map((h) => `${h.t} ${h.text}`).join('\n');
}

function parseCommandBody(body) {
  const cmdM = String(body || '').match(/Command:\n([^\n]*)/);
  const cwdM = String(body || '').match(/Working directory:\n([^\n]*)/);
  const dangerM = String(body || '').match(/⚠[^\n]*/);
  return { cmd: cmdM ? cmdM[1] : '', cwd: cwdM ? cwdM[1] : '', danger: dangerM ? dangerM[0] : null };
}

// title/body come straight from the agent loop's approval request — this is
// the presentation boundary that turns them into the boxed approval UX.
function approvalDetail(s, title, body, isCommand, opts = {}) {
  const L = [''];
  if (isCommand) {
    const { cmd, cwd, danger } = parseCommandBody(body);
    L.push('  BotConnector wants to run:');
    L.push('');
    L.push('    ' + theme.bold(cmd || title));
    L.push('');
    L.push('  in ' + (cwd || friendlyProject(s)));
    if (danger) {
      L.push('');
      L.push('  ' + theme.red(theme.bold('⚠ ' + danger.replace(/^⚠\s*/, ''))));
      L.push('  ' + theme.red('This looks destructive — read carefully before running.'));
    }
    L.push('');
    L.push('  [Y] Run    [N] Cancel    [A] Run all remaining this task');
  } else if (/^--- a\//m.test(body || '')) {
    const useFull = opts.full && fullDiffBody(opts.proposal);
    L.push('  ' + theme.bold((opts.proposal && opts.proposal.path) || title.replace(/^Proposed \w+:\s*/, '')));
    L.push('');
    for (const l of renderDiffLines(useFull || body)) L.push('  ' + l);
    L.push('');
    L.push('  Apply this change?');
    L.push('');
    L.push(opts.full
      ? '  [Y] Apply    [N] Reject    [V] Compact view'
      : '  [Y] Apply    [N] Reject    [V] View full diff');
  } else if (/^Create /.test(body || '')) {
    const [header, ...rest] = String(body).split('\n\n');
    L.push('  ' + theme.bold(header));
    L.push('');
    for (const l of rest.join('\n\n').split('\n').slice(0, 20)) L.push('  ' + theme.green('+ ' + l));
    L.push('');
    L.push('  Create this file?');
    L.push('');
    L.push('  [Y] Apply    [N] Reject    [A] Approve all remaining this task');
  } else {
    L.push('  ' + theme.bold(title));
    L.push('');
    for (const l of String(body || '').split('\n')) L.push('  ' + l);
    L.push('');
    L.push('  [Y] Apply    [N] Reject    [A] Approve all remaining this task');
  }
  L.push('');
  L.push('  ' + theme.dim('(nothing changes until you approve)'));
  L.push('');
  L.push('  ' + statusBar(s));
  return L.join('\n');
}

// ---- context ----
function contextNeedsLarger(s, g, recommendedK) {
  const currentK = Math.round((g.nCtx / 1024) * 10) / 10;
  return [
    '',
    '  This model needs a larger working context for agent tasks.',
    '',
    `  Current: ${currentK}K   Recommended: ${recommendedK}K`,
    '',
    '  [R] How to get more context   [C] Continue anyway   [Esc] Cancel',
    '  (won\'t ask again for this model)',
    '',
    '  ' + statusBar(s),
  ].join('\n');
}

function contextGettingFull(s) {
  return [
    '',
    '  Context is getting full.',
    '  BotConnector can reset the working context for this session.',
    '',
    '  [C] Compact    [N] New session    [Esc] Dismiss',
    '',
    '  ' + statusBar(s),
  ].join('\n');
}

// ---- doctor ----
function doctorSummary(s, r, opts = {}) {
  const L = ['', '  ' + theme.bold('Doctor')];
  L.push('');
  for (const line of doctor.summaryLines(r)) {
    if (!line) { L.push(''); continue; }
    const ok = line.startsWith('✓');
    L.push('  ' + (ok ? theme.green(line) : line.startsWith('✗') ? theme.red(line) : line));
  }
  L.push('');
  if (opts.details) {
    L.push('  ' + theme.dim('Details'));
    for (const l of doctor.detailLines(r)) L.push('  ' + theme.dim(l));
    L.push('');
  } else {
    L.push('  ' + theme.dim('/details for exact runtime/model identifiers'));
  }
  L.push('  Esc close');
  L.push('');
  L.push('  ' + statusBar(s));
  return L.join('\n');
}

// ---- settings ----
function settingsView(s) {
  const st = s.settings;
  const rows = [
    ['Default model', s.model.name],
    ['Local runtime', s.runtime.backend],
    ['Context preference', st.contextPreference],
    ['Approval behavior', st.approvalBehavior],
    ['Language', st.language],
    ['Theme', st.theme],
    ['Debug mode', st.debugMode ? 'on' : 'off'],
  ];
  const L = ['', '  ' + theme.bold('Settings')];
  L.push('');
  for (const [k, v] of rows) L.push('  ' + layout.spread(k, String(v), layout.width() - 2));
  L.push('');
  L.push('  ' + theme.dim('Tab: Plan/Act · Shift+Tab: approval · /model: default model · /debug: toggle debug'));
  L.push('  Esc close');
  L.push('');
  L.push('  ' + statusBar(s));
  return L.join('\n');
}

// ---- status (live session picture; /status) ----
function statusView(s, extra = {}) {
  const row = (k, v) => '  ' + layout.spread(k, String(v == null ? '—' : v), layout.width() - 2);
  const L = ['', '  ' + theme.bold('Status'), ''];
  L.push(row('Model', s.model.name));
  L.push(row('Provider', s.model.locality === 'Local' ? (extra.provider || s.model.provider) : s.model.provider));
  L.push(row('Project', friendlyProject(s)));
  L.push(row('Mode', s.mode));
  L.push(row('Approval', s.approval));
  L.push(row('Context', `${s.usedTokens || 0} / ${s.runtime.nCtx} tokens`));
  if (extra.modelId) L.push(row('Model id', extra.modelId));
  if (extra.endpoint) L.push(row('Endpoint', extra.endpoint));
  L.push('');
  L.push('  Esc close');
  L.push('');
  L.push('  ' + statusBar(s));
  return L.join('\n');
}

// ---- errors: actionable, with raw detail on demand ----
function errorView(s, err) {
  const L = ['', '  ' + theme.bold(err.title)];
  L.push('');
  if (err.body) for (const l of String(err.body).split('\n')) L.push('  ' + l);
  L.push('');
  const actions = (err.actions || []).map((a, i) => `[${i + 1}] ${a}`).join('    ');
  L.push('  ' + actions + (actions ? '    ' : '') + '[D] Details');
  if (err.showDetails && err.raw) {
    L.push('');
    for (const l of String(err.raw).split('\n')) L.push('  ' + theme.dim(l));
  }
  L.push('');
  L.push('  ' + statusBar(s));
  return L.join('\n');
}

// ---- first run ----
function firstRunWelcome() {
  return {
    title: 'Welcome to BotConnector AI — set up your local AI',
    items: [
      { label: 'Use recommended model', detail: 'Auto-detects your hardware and downloads a small starter model' },
      { label: 'Choose another model', detail: 'Browse BotConnector Local / Ollama / Cloud' },
      { label: 'Use cloud', detail: 'Skip local setup for now' },
    ],
    index: 0,
    hint: 'Up/Down move · Enter select · Esc skip for now',
  };
}

function firstRunRecommend(s, hw, rec, bytes) {
  return [
    '', '  ' + theme.bold('Recommended for your machine'),
    '',
    `  ${rec.name}  (~${fmtBytes(bytes || rec.approxBytes)})`,
    `  Detected: ${hw.totalRamGB}GB RAM · ${hw.cores || '?'} cores · ${hw.platform}`,
    '',
    '  This downloads once, to your BotConnector models folder.',
    '  Nothing downloads until you approve.',
    '',
    '  [Y] Download    [N] Back',
    '',
    '  ' + statusBar(s),
  ].join('\n');
}

function firstRunProgress(s, rec, progress) {
  const pct = progress.pct || 0;
  return [
    '', `  Downloading ${rec.name}… ${pct}%`,
    '',
    '  ' + layout.bar(pct, 30),
    `  ${fmtBytes(progress.receivedBytes)} / ${fmtBytes(progress.totalBytes)}`,
    '',
    '  Esc cancel',
    '',
    '  ' + statusBar(s),
  ].join('\n');
}

function firstRunDone(s, rec, destPath) {
  return [
    '', '  ' + theme.green('✓ Downloaded'),
    '',
    `  ${rec.name}`,
    `  Saved to ${destPath}`,
    '',
    '  BotConnector\'s local runtime will use this the next time it loads a model.',
    '',
    '  Enter continue',
    '',
    '  ' + statusBar(s),
  ].join('\n');
}

function firstRunFailed(s, reason) {
  return [
    '', '  ' + theme.red('Download failed'),
    '',
    '  ' + reason,
    '',
    '  [R] Retry    [Esc] Back',
    '',
    '  ' + statusBar(s),
  ].join('\n');
}

module.exports = {
  home, statusBar, picker, approvalDetail,
  contextNeedsLarger, contextGettingFull,
  doctorSummary, settingsView, statusView, errorView,
  firstRunWelcome, firstRunRecommend, firstRunProgress, firstRunDone, firstRunFailed,
  fmtBytes, wrapText, friendlyProject,
};
