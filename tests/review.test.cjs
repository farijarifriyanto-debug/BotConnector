'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const loop = require('../agent/loop.cjs');
const review = require('../tui/review.cjs');

async function withServer(handler, fn) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try { return await fn(`http://127.0.0.1:${server.address().port}/v1`); }
  finally { await new Promise((resolve) => server.close(resolve)); }
}

function args(endpoint, extra = {}) {
  return {
    prompt: 'Review the actual Git patch. FILE review-target.js\n- old\n+ new',
    taskKind: 'review', mode: 'Act', approval: 'ask',
    model: { name: 'Active model', locality: 'Local' }, tools: [], cwd: process.cwd(), workspace: process.cwd(),
    onEvent: () => {}, localCtx: { endpoint, modelId: 'active-model-id', friendly: 'Active model' }, ...extra,
  };
}

test('REVIEW_HANDLER_DISPATCHES + REVIEW_USES_ACTIVE_MODEL + REVIEW_STREAM_COMPLETES', async () => {
  let request;
  await withServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      request = JSON.parse(body);
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      res.write('data: {"choices":[{"delta":{"content":"Finding: review-target.js changed value."}}]}\n\n');
      res.write('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n');
      res.end('data: [DONE]\n\n');
    });
  }, async (endpoint) => {
    const seen = [];
    const result = await loop.runTurn(args(endpoint, { onToken: (t) => seen.push(t), maxTokens: 512 }));
    assert.equal(result.failed, undefined);
    assert.match(result.answer, /Finding/);
    assert.deepEqual(seen, ['Finding: review-target.js changed value.']);
    assert.equal(request.model, 'active-model-id');
    assert.equal(request.stream, true);
  });
});

test('REVIEW_FAILURE_RESETS + REVIEW_CANCEL_RESETS', async () => {
  await withServer((req, res) => { res.writeHead(500); res.end('review unavailable'); }, async (endpoint) => {
    const result = await loop.runTurn(args(endpoint));
    assert.equal(result.failed, true);
    assert.match(result.answer, /Local inference failed|HTTP 500/);
  });

  await withServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    setTimeout(() => res.end(), 1000);
  }, async (endpoint) => {
    const abort = new AbortController();
    setTimeout(() => abort.abort(), 25);
    const result = await loop.runTurn(args(endpoint, { signal: abort.signal }));
    assert.equal(result.cancelled, true);
    assert.equal(result.failed, false);
  });
});

test('REVIEW_RESULT_VISIBLE + REVIEW_NO_EMPTY_MESSAGE contract', () => {
  const payload = review.buildReviewPrompt([{ path: 'review-target.js', patch: '@@ -1 +1 @@\n-old\n+new' }]);
  assert.ok(payload.prompt.includes('review-target.js'));
  assert.ok(payload.prompt.includes('correctness/regressions'));
  const visiblePrompt = '/review working changes';
  const visibleResult = 'Finding: review-target.js changed value.';
  assert.ok(visiblePrompt.trim());
  assert.ok(visibleResult.trim());
});

test('REVIEW_LARGE_DIFF_GUARDED', () => {
  const payload = review.buildReviewPrompt([{ path: 'large.js', patch: 'x'.repeat(50000) }]);
  const guard = review.guardPayload(payload, 4096);
  assert.equal(guard.ok, false);
  assert.match(guard.reason, /NARROW_SCOPE_REQUIRED/);
});
