'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

function temp(prefix) { return fs.mkdtempSync(path.join(os.tmpdir(), prefix)); }

test('TIMELINE_REAL_MESSAGES + LONG_SESSION + RENAME_PERSIST', async () => {
  const data = temp('botconnector-session-'); process.env.BOTCONNECTOR_USERDATA = data;
  const sessions = require('../sessions.cjs');
  const sess = await sessions.create({ project: 'demo', model: { name: 'Auto' }, mode: 'Plan' });
  for (let i = 0; i < 60; i++) await sessions.recordTurn(sess, { prompt: `question ${i}`, answer: `answer ${i}`, project: 'demo', model: sess.model, mode: 'Plan' });
  assert.equal(sessions.timeline(sess).length, 120);
  assert.ok(sessions.timeline(sess).every((m) => m.id));
  await sessions.rename(sess, 'provider registry debug');
  assert.equal(sessions.load(sess.id).title, 'provider registry debug');
});

test('FORK_AT_MESSAGE + PARENT_UNCHANGED + LINEAGE', async () => {
  const data = temp('botconnector-fork-'); process.env.BOTCONNECTOR_USERDATA = data;
  const sessions = require('../sessions.cjs');
  const parent = await sessions.create({ project: 'demo', model: { name: 'Auto' }, mode: 'Act' });
  await sessions.recordTurn(parent, { prompt: 'one', answer: 'two', project: 'demo', model: parent.model, mode: 'Act' });
  await sessions.recordTurn(parent, { prompt: 'three', answer: 'four', project: 'demo', model: parent.model, mode: 'Act' });
  const boundary = parent.messages[1].id;
  const child = await sessions.fork(parent, boundary);
  assert.equal(child.parentSessionId, parent.id); assert.equal(child.forkedFromMessageId, boundary);
  assert.equal(child.messages.length, 2); assert.equal(sessions.load(parent.id).messages.length, 4);
});

test('COPY_SAFE_TRANSCRIPT + EXPORT_MARKDOWN + SANITIZED_JSON', async () => {
  const data = temp('botconnector-export-'); process.env.BOTCONNECTOR_USERDATA = data;
  const sessions = require('../sessions.cjs');
  const sess = await sessions.create({ project: 'demo', model: { name: 'Auto' }, mode: 'Plan' });
  await sessions.recordTurn(sess, { prompt: 'hello', answer: 'token=should-not-be-an-internal-dump', project: 'demo', model: sess.model, mode: 'Plan' });
  assert.match(sessions.markdown(sess), /^# hello/m);
  const out = await sessions.exportSession(sess, 'sanitized-json', data);
  const json = JSON.parse(fs.readFileSync(out, 'utf8'));
  assert.ok(json.messages); assert.equal(json.apiKey, undefined);
  assert.equal(sessions.safeJson({ ...sess, apiKey: 'secret' }, true).apiKey, undefined);
});

test('COMPACT_REAL_SUMMARY retains timeline and creates context summary', async () => {
  const data = temp('botconnector-compact-'); process.env.BOTCONNECTOR_USERDATA = data;
  const sessions = require('../sessions.cjs');
  const sess = await sessions.create({ project: 'demo', model: { name: 'Auto' }, mode: 'Plan' });
  for (let i = 0; i < 10; i++) await sessions.recordTurn(sess, { prompt: `decision ${i} TODO file${i}.js`, answer: `result ${i}`, project: 'demo', model: sess.model, mode: 'Plan' });
  const result = await sessions.compact(sess, { keep: 4 });
  assert.equal(result.ok, true); assert.ok(sess.compaction.summary.includes('Goals'));
  assert.equal(sessions.timeline(sess).length, 20); assert.ok(sessions.historyFor(sess)[0].role === 'system');
});

test('UNDO_JOURNAL_SAFE + EXTERNAL_CONFLICT_REFUSED + REDO_SAFE', async () => {
  const data = temp('botconnector-journal-'); process.env.BOTCONNECTOR_USERDATA = data;
  const journal = require('../agent/journal.cjs'); const workspace = temp('botconnector-workspace-');
  const file = path.join(workspace, 'a.txt'); fs.writeFileSync(file, 'after');
  await journal.record({ files: [{ path: 'a.txt', beforeExists: true, afterExists: true, before: Buffer.from('before'), after: Buffer.from('after') }] }, { workspace, sessionId: 's' });
  let result = await journal.undo({ workspace, sessionId: 's' }); assert.equal(result.ok, true); assert.equal(fs.readFileSync(file, 'utf8'), 'before');
  result = await journal.redo({ workspace, sessionId: 's' }); assert.equal(result.ok, true); assert.equal(fs.readFileSync(file, 'utf8'), 'after');
  fs.writeFileSync(file, 'external');
  await journal.record({ files: [{ path: 'a.txt', beforeExists: true, afterExists: true, before: Buffer.from('after'), after: Buffer.from('bot') }] }, { workspace, sessionId: 's' });
  result = await journal.undo({ workspace, sessionId: 's' }); assert.equal(result.conflict, true); assert.match(result.reason, /EXTERNAL_CONFLICT_REFUSED/);
});
