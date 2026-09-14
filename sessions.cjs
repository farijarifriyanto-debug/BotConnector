// Real session persistence: one JSON file per session under canonical's
// userData directory (sibling to settings.json/cloud/, same storage root
// the Desktop app and CLI already use — no separate config location).
// Stores conversation messages + project/model/mode so /sessions can really
// resume, not just browse. Never stores secrets/tool credentials.
'use strict';
const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');
const crypto = require('crypto');
const { userDataDir } = require('./state.cjs');

function dir() {
  const d = path.join(userDataDir(), 'sessions');
  fs.mkdirSync(d, { recursive: true });
  return d;
}

function file(id) { return path.join(dir(), `${id}.json`); }
function newId() { return crypto.randomBytes(6).toString('hex'); }

function titleFrom(prompt) {
  const t = String(prompt || '').replace(/\s+/g, ' ').trim();
  return t ? (t.length > 48 ? t.slice(0, 47) + '…' : t) : 'New session';
}

// Index: lightweight metadata only (no message bodies) for the /sessions list.
function list() {
  let names = [];
  try { names = fs.readdirSync(dir()).filter((f) => f.endsWith('.json')); } catch { return []; }
  const rows = [];
  for (const name of names) {
    try {
      const raw = JSON.parse(fs.readFileSync(path.join(dir(), name), 'utf8'));
      rows.push({
        id: raw.id, title: raw.title, project: raw.project, model: raw.model,
        mode: raw.mode, lastUsed: raw.lastUsed, createdAt: raw.createdAt,
        messageCount: (raw.messages || []).length,
      });
    } catch { /* skip corrupt/partial file */ }
  }
  return rows.sort((a, b) => b.lastUsed - a.lastUsed);
}

function load(id) {
  try { return JSON.parse(fs.readFileSync(file(id), 'utf8')); } catch { return null; }
}

async function save(sess) { await fsp.writeFile(file(sess.id), JSON.stringify(sess, null, 2)); }

async function create({ project, model, mode }) {
  const now = Date.now();
  const sess = { id: newId(), title: 'New session', project, model, mode, messages: [], summary: null, createdAt: now, lastUsed: now };
  await save(sess);
  return sess;
}

// Appends one user/assistant turn and refreshes metadata; title is derived
// from the first user prompt only.
async function recordTurn(sess, { prompt, answer, project, model, mode }) {
  if (sess.title === 'New session' && prompt) sess.title = titleFrom(prompt);
  if (prompt) sess.messages.push({ role: 'user', content: prompt, at: Date.now() });
  if (answer != null) sess.messages.push({ role: 'assistant', content: answer, at: Date.now() });
  sess.project = project; sess.model = model; sess.mode = mode;
  sess.lastUsed = Date.now();
  // Bound file growth — keep the working window the loop actually reuses,
  // plus a running compacted note of what was dropped.
  const MAX_MESSAGES = 40;
  if (sess.messages.length > MAX_MESSAGES) {
    const dropped = sess.messages.length - MAX_MESSAGES;
    sess.summary = `${sess.summary ? sess.summary + ' ' : ''}(+${dropped} earlier message(s) trimmed)`;
    sess.messages = sess.messages.slice(-MAX_MESSAGES);
  }
  await save(sess);
  return sess;
}

// Returns the {role,content} history the agent loop should replay, in the
// shape runTurn/runTask's new `history` param expects.
function historyFor(sess) {
  return (sess.messages || []).map((m) => ({ role: m.role, content: m.content }));
}

async function remove(id) { try { await fsp.rm(file(id), { force: true }); return true; } catch { return false; } }

module.exports = { list, load, save, create, recordTurn, remove, historyFor, titleFrom, newId, dir };
