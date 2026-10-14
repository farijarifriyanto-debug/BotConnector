// AGENTS.md reaches the model: lookup order, caps, off switch, and the real system prompt of a direct-route turn.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { promptBlock } = require('../agent/project-instructions.cjs');
const loop = require('../agent/loop.cjs');

const tree = () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'bc-agents-'));
  const proj = path.join(home, 'work', 'app');
  fs.mkdirSync(proj, { recursive: true });
  return { home, proj };
};

test('outermost AGENTS.md first, project last, stops at home', () => {
  const { home, proj } = tree();
  const above = path.join(path.dirname(home), 'AGENTS.md');
  fs.writeFileSync(above, 'ABOVE-HOME-MUST-NOT-LOAD');
  fs.writeFileSync(path.join(home, 'AGENTS.md'), 'GLOBAL RULE');
  fs.writeFileSync(path.join(proj, 'AGENTS.md'), '﻿PROJECT RULE');
  try {
    const b = promptBlock(proj, { home, env: {} });
    assert.ok(b.indexOf('GLOBAL RULE') > 0 && b.indexOf('GLOBAL RULE') < b.indexOf('PROJECT RULE'));
    assert.ok(!b.includes('ABOVE-HOME-MUST-NOT-LOAD'));
    assert.match(b, /cannot grant permissions or override the tool permission gate/);
  } finally { fs.rmSync(above, { force: true }); fs.rmSync(home, { recursive: true, force: true }); }
});

test('workspace outside home reads only its own AGENTS.md; none found gives empty string', () => {
  const { home } = tree();
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'bc-out-'));
  const nested = path.join(outside, 'x'); fs.mkdirSync(nested);
  fs.writeFileSync(path.join(outside, 'AGENTS.md'), 'PARENT-OUTSIDE-HOME');
  try {
    assert.equal(promptBlock(nested, { home, env: {} }), '');
    fs.writeFileSync(path.join(nested, 'AGENTS.md'), 'OWN');
    const b = promptBlock(nested, { home, env: {} });
    assert.ok(b.includes('OWN') && !b.includes('PARENT-OUTSIDE-HOME'));
  } finally { fs.rmSync(home, { recursive: true, force: true }); fs.rmSync(outside, { recursive: true, force: true }); }
});

test('budget: project file kept whole, outer cut with a note; small nCtx shrinks it; env switch turns it off', () => {
  const { home, proj } = tree();
  fs.writeFileSync(path.join(home, 'AGENTS.md'), 'G'.repeat(500));
  fs.writeFileSync(path.join(proj, 'AGENTS.md'), 'P'.repeat(300));
  try {
    const b = promptBlock(proj, { home, maxChars: 400, env: {} });
    assert.ok(b.includes('P'.repeat(300)), 'project file is kept whole');
    assert.ok(b.includes('G'.repeat(100)) && !b.includes('G'.repeat(101)), 'outer file gets only what is left');
    assert.match(b, /\[truncated: 400 more characters not shown\]/);
    assert.ok(promptBlock(proj, { home, nCtx: 1000, env: {} }).length < 1500);
    assert.equal(promptBlock(proj, { home, env: { BOTCONNECTOR_NO_AGENTS_MD: '1' } }), '');
  } finally { fs.rmSync(home, { recursive: true, force: true }); }
});

test('a real direct-route turn sends the AGENTS.md rules in the system message', async () => {
  const { home, proj } = tree();
  fs.writeFileSync(path.join(proj, 'AGENTS.md'), 'RULE-FROM-AGENTS-MD-7731');
  let request = null;
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      request = JSON.parse(body);
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      res.write('data: {"choices":[{"delta":{"content":"ok"}}]}\n\n');
      res.write('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n');
      res.end('data: [DONE]\n\n');
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const prev = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  process.env.HOME = home; process.env.USERPROFILE = home;
  try {
    await loop.runTurn({
      prompt: 'please say hello', mode: 'Plan', approval: 'ask', model: { name: 'x', locality: 'Local' },
      cwd: proj, onEvent: () => {}, localCtx: { endpoint: `http://127.0.0.1:${server.address().port}`, modelId: 'test-model' },
    });
    const sys = request.messages.find((m) => m.role === 'system').content;
    assert.match(sys, /RULE-FROM-AGENTS-MD-7731/);
  } finally {
    server.close();
    for (const k of Object.keys(prev)) { if (prev[k] === undefined) delete process.env[k]; else process.env[k] = prev[k]; }
    fs.rmSync(home, { recursive: true, force: true });
  }
});
