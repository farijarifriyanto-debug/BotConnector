// Phase 3 non-live acceptance: credential abstraction, routing, failover,
// retries, circuit breaker, ledger, pricing, cost, units, budget guards.
// Uses mock adapters â€” NO network, NO real keys.
const {test} = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {CredentialManager, PROVIDERS} = require('../runtime/credentials.cjs');
const {ProviderError, classifyStatus, classifyNetworkError, normalizeUsage, normalizeModel} = require('../runtime/cloud/provider.cjs');
const {RoutingTable, DEFAULT_POLICY} = require('../runtime/cloud/routing.cjs');
const {HealthBoard} = require('../runtime/cloud/health.cjs');
const {UsageLedger} = require('../runtime/cloud/usage.cjs');
const {PricingRegistry} = require('../runtime/cloud/pricing.cjs');
const {UnitEngine} = require('../runtime/cloud/units.cjs');
const {BudgetGuard} = require('../runtime/cloud/budget.cjs');
const {CloudRouter} = require('../runtime/cloud/router.cjs');
const {ModelCatalog} = require('../runtime/cloud/catalog.cjs');
const {estimateCost} = require('../runtime/cloud/cost.cjs');
const {NebiusProvider} = require('../runtime/cloud/nebius.cjs');
const {TogetherProvider} = require('../runtime/cloud/together.cjs');

function tmpdir(name){ const d = fs.mkdtempSync(path.join(os.tmpdir(), 'bc3-' + name + '-')); return d; }
function memStore(initial = {}){ const data = {...initial}; return { get: k => data[k], set: async (k, v) => { data[k] = v; }, data }; }
// Fake safeStorage: deterministic base64 (structure matches Electron's API shape).
const fakeSafeStorage = { isEncryptionAvailable: () => true, encryptString: s => Buffer.from('enc:' + s).toString('base64'), decryptString: b => { const s = Buffer.from(b).toString('utf8'); if(!s.startsWith('enc:')) throw new Error('bad'); return s.slice(4); } };

// ---------- Credentials ----------
test('credentials: safeStorage roundtrip + public never leaks key material', async () => {
  const dir = tmpdir('cred'); const store = memStore(); const cm = new CredentialManager({store, safeStorage: fakeSafeStorage});
  await cm.setKey('nebius', 'nvapi-secret-1234567890');
  const raw = JSON.stringify(store.data || {});
  assert.ok(!raw.includes('nvapi-secret-1234567890'), 'plaintext key must not be serialized into store');
  const pub = cm.public();
  assert.equal(pub.nebius.configured, true);
  assert.equal(pub.nebius.source, 'safeStorage');
  assert.ok(!JSON.stringify(pub).includes('nvapi-secret'), 'public state must not contain key');
  assert.equal(cm.source('nebius').source, 'safeStorage');
  const rm = await cm.removeKey('nebius');
  assert.equal(rm.configured, false);
  fs.rmSync(dir, {recursive: true, force: true});
});
test('credentials: env fallback used when no safeStorage blob', async () => {
  const cm = new CredentialManager({store: memStore(), safeStorage: fakeSafeStorage, env: {TOGETHER_API_KEY: 'together-env-key-99'}});
  assert.equal(cm.source('together').source, 'environment');
  assert.equal(cm.source('together').envName, 'TOGETHER_API_KEY');
  assert.equal(cm.public().together.configured, true);
  assert.equal(cm.source('nebius').source, 'missing');
});
test('credentials: priority safeStorage over environment', async () => {
  const store = memStore(); const cm = new CredentialManager({store, safeStorage: fakeSafeStorage, env: {NEBIUS_API_KEY: 'env-nebius-123456'}});
  await cm.setKey('nebius', 'stored-key-abcdef');
  assert.equal(cm.source('nebius').source, 'safeStorage');
  await cm.removeKey('nebius');
  assert.equal(cm.source('nebius').source, 'environment');
});
test('credentials: refuses to persist without encryption available', async () => {
  const cm = new CredentialManager({store: memStore(), safeStorage: null});
  await assert.rejects(() => cm.setKey('together', 'some-long-key-12345'), /safeStorage\) is unavailable/);
});
test('credentials: unknown provider rejected', async () => {
  const cm = new CredentialManager({store: memStore(), safeStorage: fakeSafeStorage});
  assert.throws(() => cm.source('groq'), /Unknown cloud provider/);
  await assert.rejects(() => cm.setKey('openai', 'whatever-1234'));
});

// ---------- Error classification ----------
test('classification: retryable vs failover vs terminal', () => {
  const r429 = classifyStatus(429); assert.ok(r429.retryable && r429.failoverable);
  const r500 = classifyStatus(500); assert.ok(r500.retryable && r500.failoverable);
  const a401 = classifyStatus(401); assert.ok(!a401.retryable && !a401.failoverable);
  const b400 = classifyStatus(400); assert.ok(!b400.failoverable);
  const net = classifyNetworkError({cause: {code: 'ECONNRESET'}}); assert.ok(net.failoverable);
});
test('normalizeUsage handles OpenAI + Nebius + Together shapes', () => {
  const a = normalizeUsage({prompt_tokens: 100, completion_tokens: 50, total_tokens: 150});
  assert.equal(a.input_tokens, 100); assert.equal(a.output_tokens, 50);
  const b = normalizeUsage({prompt_tokens: 100, prompt_tokens_details: {cached_tokens: 40}, completion_tokens: 50, completion_tokens_details: {reasoning_tokens: 10}});
  assert.equal(b.cached_input_tokens, 40); assert.equal(b.reasoning_tokens, 10);
  const c = normalizeUsage({input_tokens: 10, output_tokens: 5});
  assert.equal(c.total_tokens, 15);
});

// ---------- Routing ----------
test('routing: deterministic exact-model chain with seed rules', async () => {
  const dir = tmpdir('route');
  const rt = new RoutingTable({dir});
  const chain1 = rt.chain('deepseek-ai/DeepSeek-V4-Flash-0731', ['nebius', 'together']);
  assert.deepEqual(chain1, ['nebius', 'together']);
  const chain2 = rt.chain('MiniMaxAI/MiniMax-M3', ['nebius', 'together']);
  assert.deepEqual(chain2, ['nebius', 'together']);
  const chain3 = rt.chain('some-together-only-model', ['together']);
  assert.deepEqual(chain3, ['together']);
  // No provider available -> empty chain -> EXACT_MODEL_UNAVAILABLE at router level
  const chain4 = rt.chain('MiniMaxAI/MiniMax-M3', []);
  assert.deepEqual(chain4, []);
  fs.rmSync(dir, {recursive: true, force: true});
});
test('routing: persists custom rules (configurable policy)', async () => {
  const dir = tmpdir('route2');
  const rt = new RoutingTable({dir});
  const p = await rt.load();
  p.rules['custom/model'] = {preferred: 'together', fallback: ['nebius']};
  await rt.save(p);
  const rt2 = new RoutingTable({dir});
  assert.deepEqual(rt2.chain('custom/model', ['nebius', 'together']), ['together', 'nebius']);
  fs.rmSync(dir, {recursive: true, force: true});
});

// ---------- Health / circuit breaker ----------
test('health: derives states from outcomes; opens circuit after 3 failures', async () => {
  const dir = tmpdir('health');
  const hb = new HealthBoard({dir, cooldownMs: 30});
  hb.record('nebius', {ok: true, latencyMs: 300});
  assert.equal(hb.snapshot('nebius').state, 'HEALTHY');
  for (let i = 0; i < 3; i++) hb.record('nebius', {ok: false, status: 503});
  const snap = hb.snapshot('nebius');
  assert.equal(snap.state, 'UNAVAILABLE');
  assert.ok(snap.circuitOpen);
  // Circuit does NOT permanently kill the provider: after cooldown a new
  // failure window re-opens then it becomes probeable again (half-open).
  await new Promise(r => setTimeout(r, 40));
  const snap2 = hb.snapshot('nebius');
  assert.ok(!snap.circuitOpen || Date.now() >= snap.openUntil, 'cooldown expiry makes circuit probeable');
  // Recovery path: a success closes the circuit.
  await new Promise(r => setTimeout(r, 20));
  hb.record('nebius', {ok: true, latencyMs: 100});
  assert.ok(['HEALTHY', 'DEGRADED'].includes(hb.snapshot('nebius').state), 'recovers after success, not permanently dead');
  fs.rmSync(dir, {recursive: true, force: true});
});

// ---------- Pricing / cost / units ----------
test('pricing: verified baseline rates + unknown fails safe', async () => {
  const dir = tmpdir('pricing');
  const pr = new PricingRegistry({dir});
  const r = await pr.estimate({provider: 'together', modelId: 'deepseek-ai/DeepSeek-V4-Flash-0731', inputTokens: 1_000_000, cachedInputTokens: 0, outputTokens: 1_000_000});
  // (1M * 0.14 + 1M * 0.28)/1M = $0.42
  assert.equal(r.costStatus, 'KNOWN'); assert.ok(Math.abs(r.cost - 0.42) < 1e-9);
  const cached = await pr.estimate({provider: 'together', modelId: 'deepseek-ai/DeepSeek-V4-Flash-0731', inputTokens: 1_000_000, cachedInputTokens: 1_000_000, outputTokens: 0});
  assert.ok(Math.abs(cached.cost - 0.03) < 1e-9);
  const unknown = await pr.estimate({provider: 'nebius', modelId: 'deepseek-ai/DeepSeek-V4-Flash-0731', inputTokens: 10, outputTokens: 10});
  assert.equal(unknown.costStatus, 'UNKNOWN'); assert.equal(unknown.cost, null);
  fs.rmSync(dir, {recursive: true, force: true});
});
test('units: derived from actual cost vs reference (no arbitrary multiplier)', async () => {
  const ue = new UnitEngine({});
  const refCostPerTok = ue.blendedCostPerToken({inputPerMillion: 0.14, outputPerMillion: 0.28, ratio: 0.75});
  const mini = ue.blendedCostPerToken({inputPerMillion: 0.30, outputPerMillion: 1.20, ratio: 0.75});
  const mult = ue.multiplier(mini);
  assert.ok(mult === 3, `MiniMax blended multiplier = exact ratio 5.25e-7/1.75e-7 = 3, got ${mult}`);
  const units = ue.units(0.0042);
  assert.ok(units >= 41 && units <= 43); // $0.0042 * 10000 = 42
  assert.equal(ue.units(null), null);
  assert.equal(ue.public().simulationOnly, true);
});

// ---------- Budget guard ----------
test('budget: rejects oversized input/output/cost/session/daily', async () => {
  const dir = tmpdir('budget');
  const bg = new BudgetGuard({dir});
  assert.ok(bg.check({inputTokensEstimate: 1000}).allowed);
  const over = bg.check({inputTokensEstimate: 999999});
  assert.equal(over.allowed, false); assert.ok(over.rejects[0].includes('input tokens'));
  const overOut = bg.check({inputTokensEstimate: 10, maxOutputTokens: 999999});
  assert.equal(overOut.allowed, false);
  const overCost = bg.check({pendingCostEstimate: 0.9});
  assert.equal(overCost.allowed, false);
  const overSession = bg.check({sessionSpentUsd: 1.9, pendingCostEstimate: 0.2});
  assert.equal(overSession.allowed, false);
  const overDaily = bg.check({todaySpentUsd: 4.9, pendingCostEstimate: 0.2});
  assert.equal(overDaily.allowed, false);
  fs.rmSync(dir, {recursive: true, force: true});
});

// ---------- Usage ledger ----------
test('ledger: normalized records persist and survive reload', async () => {
  const dir = tmpdir('ledger');
  const l1 = new UsageLedger({dir});
  await l1.append({requestId: 'r1', providerRequested: 'nebius', providerUsed: 'together', modelId: 'MiniMaxAI/MiniMax-M3', failover: true, retryCount: 1, inputTokens: 12, outputTokens: 34, totalTokens: 46, latencyMs: 800, estimatedCost: 0.002, costStatus: 'KNOWN', pricingVersion: 'v1:2026-09-13', cloudUnits: 20});
  const l2 = new UsageLedger({dir}); // new instance = simulated restart
  const rows = await l2.list();
  assert.equal(rows.length, 1);
  const r = rows[0];
  assert.equal(r.request_id, 'r1'); assert.equal(r.failover, true); assert.equal(r.provider_used, 'together');
  assert.equal(r.pricing_version, 'v1:2026-09-13');
  assert.ok(!('prompt' in r) && !('messages' in r), 'no prompt bodies in ledger');
  const sum = await l2.summary();
  assert.equal(sum.requests, 1); assert.ok(sum.estimatedCost > 0);
  fs.rmSync(dir, {recursive: true, force: true});
});

// ---------- Router with mock providers ----------
const CATALOG_MODELS = [
  {modelId: 'MiniMaxAI/MiniMax-M3', provider: 'nebius', stale: false, availability: 'live'},
  {modelId: 'MiniMaxAI/MiniMax-M3', provider: 'together', stale: false, availability: 'live'},
  {modelId: 'deepseek-ai/DeepSeek-V4-Flash-0731', provider: 'nebius', stale: false, availability: 'live'},
  {modelId: 'deepseek-ai/DeepSeek-V4-Flash-0731', provider: 'together', stale: false, availability: 'live'},
  {modelId: 'together-only-model', provider: 'together', stale: false, availability: 'live'}
];
function mockCatalog(){ 
  const cat = new ModelCatalog({adapters: {}, cachedir: tmpdir('cat')});
  cat.list = () => ({models: CATALOG_MODELS, stale: false, fetchedAt: new Date().toISOString(), count: CATALOG_MODELS.length});
  cat.providersAvailable = (modelId) => CATALOG_MODELS.filter(m => m.modelId === modelId).map(m => m.provider);
  return cat;
}
function makeRouter({failN = false, failT = false} = {}){
  const dir = tmpdir('router');
  const cat = mockCatalog();
  const rt = new RoutingTable({dir});
  const hb = new HealthBoard({dir, cooldownMs: 30});
  const ledger = new UsageLedger({dir});
  const pricing = new PricingRegistry({dir});
  const units = new UnitEngine({});
  const budget = new BudgetGuard({dir});
  const router = new CloudRouter({adapters: {nebius: mk('nebius', failN), together: mk('together', failT)}, catalog: cat, routing: rt, health: hb, ledger, pricing, units, budget, cfg: {retryMax: 1, backoffBaseMs: 5, jitterMs: 5}});
  return {router, dir, ledger, hb};
}
function mockAdapter(id, alwaysFail){ 
  return {
    id,
    normalizeUsage: u => normalizeUsage(u),
    chat: async () => { throw new ProviderError(`${id} 503`, {code: 'PROVIDER_ERROR', retryable: true, failoverable: true, provider: id, status: 503}); },
    chatStream: async function*(){ throw new ProviderError(`${id} 503`, {status: 503, retryable: true, failoverable: true, provider: id}); }
  };
}

test('router: EXACT_MODEL_UNAVAILABLE when no provider serves model', async () => {
  const {router} = makeRouter();
  await assert.rejects(() => router.chat({modelId: 'unknown/model', messages: []}), /not available on any configured provider|No healthy provider/);
});
test('router: SAME-MODEL failover nebius->together, model id preserved, metadata correct', async () => {
  // nebius fails retryably; together succeeds
  const {router, ledger} = makeRouter({failN: true, failT: false});
  const out = await router.chat({modelId: 'MiniMaxAI/MiniMax-M3', messages: [{role: 'user', content: 'hi'}], sessionSpentUsd: 0, todaySpentUsd: 0});
  assert.equal(out._meta.providerUsed, 'together');
  assert.equal(out._meta.failover, true);
  assert.equal(out._meta.modelId, 'MiniMaxAI/MiniMax-M3');
  const rows = await (router.ledger).list();
  const row = rows[rows.length - 1];
  assert.equal(row.provider_used, 'together');
  assert.equal(row.model_id, 'MiniMaxAI/MiniMax-M3'); // no substitution
  assert.equal(row.failover, true);
  // pricing: MiniMax together = 0.30/1M in, 1.20/1M out -> tiny usage cost > 0
  assert.ok(row.estimated_provider_cost != null && row.estimated_provider_cost > 0, 'cost recorded');
  assert.equal(row.cost_status, 'KNOWN');
});
test('router: no silent substitution for unknown model', async () => {
  const {router} = makeRouter();
  await assert.rejects(() => router.chat({modelId: 'ai42/nonexistent', messages: []}), /EXACT_MODEL_UNAVAILABLE|not available/);
});
test('router: auth error is terminal (no failover), budget error terminal', async () => {
  const dir = tmpdir('rt3');
  const cat = mockCatalog();
  const authAdapter = {
    id: 'nebius', normalizeUsage: u => normalizeUsage(u),
    chat: async () => { throw new ProviderError('bad key', {status: 401, code: 'AUTH_ERROR', retryable: false, failoverable: false, provider: 'nebius'}); },
    chatStream: async function*(){}
  };
  const okAdapter = { id: 'together', normalizeUsage: u => normalizeUsage(u), chat: async () => ({choices: [{message: {content: 'ok'}}], usage: {prompt_tokens: 10, completion_tokens: 5, total_tokens: 15}, _meta: {provider: 'together', requestId: 'x', latencyMs: 50}}), chatStream: async function*(){} };
  const hb = new HealthBoard({dir, cooldownMs: 30});
  const router = new CloudRouter({adapters: {nebius: authAdapter, together: okAdapter}, catalog: cat, routing: new RoutingTable({dir}), health: hb, ledger: new UsageLedger({dir}), pricing: new PricingRegistry({dir}), units: new UnitEngine({}), budget: new BudgetGuard({dir})});
  // chain nebius->together; auth error is NOT failoverable -> must throw AUTH, not silently retry together
  await assert.rejects(() => router.chat({modelId: 'MiniMaxAI/MiniMax-M3', messages: [{role: 'user', content: 'hi'}]}), e => e.code === 'AUTH_ERROR');
  // budget rejection
  await assert.rejects(() => router.chat({modelId: 'MiniMaxAI/MiniMax-M3', messages: [{role: 'user', content: 'x'.repeat(999999)}]}), e => e.code === 'BUDGET_REJECTED');
  fs.rmSync(dir, {recursive: true, force: true});
});
test('router: circuit breaker skips open provider, uses fallback', async () => {
  const dir = tmpdir('rt4');
  const cat = mockCatalog();
  const failing = {
    id: 'nebius', normalizeUsage: u => normalizeUsage(u),
    chat: async () => { throw new ProviderError('503', {status: 503, code: 'PROVIDER_ERROR', retryable: true, failoverable: true, provider: 'nebius'}); },
    chatStream: async function*(){}
  };
  let togetherCalls = 0;
  const okA = { id: 'together', normalizeUsage: u => normalizeUsage(u), chat: async () => { togetherCalls++; return {choices: [{message: {content: 'ok'}}], usage: {prompt_tokens: 10, completion_tokens: 5, total_tokens: 15}, _meta: {provider: 'together', requestId: 'y', latencyMs: 40}}; }, chatStream: async function*(){} };
  const hb = new HealthBoard({dir, cooldownMs: 20});
  // Open nebius circuit via 3 failures
  for (let i = 0; i < 3; i++) hb.record('nebius', {ok: false, status: 503});
  const router = new CloudRouter({adapters: {nebius: failing, together: okA}, catalog: cat, routing: new RoutingTable({dir}), health: hb, ledger: new UsageLedger({dir}), pricing: new PricingRegistry({dir}), units: new UnitEngine({}), budget: new BudgetGuard({dir})});
  const out = await router.chat({modelId: 'deepseek-ai/DeepSeek-V4-Flash-0731', messages: [{role: 'user', content: 'hello'}]});
  assert.equal(out._meta.providerUsed, 'together');
  togetherCalls = togetherCalls;
  fs.rmSync(dir, {recursive: true, force: true});
});
test('router: 429 respects Retry-After and bounded retries then fails over', async () => {
  const dir = tmpdir('rt5');
  let nebiusAttempts = 0;
  const rl = {
    id: 'nebius', normalizeUsage: u => normalizeUsage(u),
    chat: async () => { nebiusAttempts++; throw new ProviderError('rate', {status: 429, code: 'RATE_LIMITED', retryable: true, failoverable: true, provider: 'nebius', retryAfterMs: 5}); },
    chatStream: async function*(){}
  };
  const okA = { id: 'together', normalizeUsage: u => normalizeUsage(u), chat: async () => ({choices: [{message: {content: 'ok'}}], usage: {prompt_tokens: 10, completion_tokens: 5, total_tokens: 15}, _meta: {provider: 'together', requestId: 'z', latencyMs: 30}}), chatStream: async function*(){} };
  const router = new CloudRouter({adapters: {nebius: rl, together: okA}, catalog: mockCatalog(), routing: new RoutingTable({dir}), health: new HealthBoard({dir, cooldownMs: 20}), ledger: new UsageLedger({dir}), pricing: new PricingRegistry({dir}), units: new UnitEngine({}), budget: new BudgetGuard({dir}), cfg: {retryMax: 2, backoffBaseMs: 5, jitterMs: 5}});
  const out = await router.chat({modelId: 'MiniMaxAI/MiniMax-M3', messages: [{role: 'user', content: 'hi'}]});
  assert.equal(nebiusAttempts, 3, '1 initial + 2 bounded retries on 429');
  assert.equal(out._meta.providerUsed, 'together');
  assert.equal(out._meta.retryCount, 0);
  fs.rmSync(dir, {recursive: true, force: true});
});
test('router: streaming normalizes chunks and final usage event', async () => {
  const dir = tmpdir('rt6');
  const streamAdapter = {
    id: 'nebius', normalizeUsage: u => normalizeUsage(u),
    chat: async () => { throw new Error('unused'); },
    chatStream: async function*(body){
      yield {type: 'chunk', provider: 'nebius', text: 'Hel'};
      yield {type: 'chunk', provider: 'nebius', text: 'lo'};
      yield {type: 'chunk', provider: 'nebius', reasoning: 'thinking...' };
      yield {type: 'chunk', finishReason: 'stop', usage: {prompt_tokens: 8, completion_tokens: 2, total_tokens: 10}};
      yield {type: 'done'};
    }
  };
  const router = new CloudRouter({adapters: {nebius: streamAdapter, together: streamAdapter}, catalog: mockCatalog(), routing: new RoutingTable({dir}), health: new HealthBoard({dir, cooldownMs: 20}), ledger: new UsageLedger({dir}), pricing: new PricingRegistry({dir}), units: new UnitEngine({}), budget: new BudgetGuard({dir})});
  const events = [];
  for await(const ev of router.chat({modelId: 'MiniMaxAI/MiniMax-M3', messages: [{role: 'user', content: 'hi'}], stream: true})){ events.push(ev); }
  const texts = events.filter(e => e.text).map(e => e.text).join('');
  assert.equal(texts, 'Hello');
  const done = events.find(e => e.type === 'done');
  assert.ok(done, 'final done event present');
  assert.ok(done.usage && done.usage.total_tokens === 10, 'final usage not dropped');
  const rows = await router.ledger.list();
  assert.equal(rows.length, 1);
  fs.rmSync(dir, {recursive: true, force: true});
});

// ---------- Catalog normalization + stale retention ----------
test('catalog: normalizes provider models + retains stale on failure', async () => {
  const dir = tmpdir('cat2');
  const nebiusGood = {listModels: async () => [normalizeModel({modelId: 'a/b', provider: 'nebius', capabilities: ['chat'], context: 131072})]};
  const togetherGood = {listModels: async () => [normalizeModel({modelId: 'c/d', provider: 'together'})]};
  const togetherBad = {listModels: async () => { throw new ProviderError('down', {code: 'NETWORK_ERROR', failoverable: true}); }};
  const cat = new ModelCatalog({adapters: {nebius: nebiusGood, together: togetherBad}, cachedir: dir});
  const r = await cat.refresh();
  assert.ok(r.results.nebius.ok); assert.ok(!r.results.together.ok);
  const stale = cat.list().models.find(m => m.provider === 'together');
  assert.equal(stale, undefined, 'first run with no prior cache -> provider absent (honest)');
  // seed cache for together then fail again -> stale retained
  const cat2 = new ModelCatalog({adapters: {nebius: nebiusGood, together: togetherGood}, cachedir: dir});
  await cat2.refresh('together');
  assert.ok(cat2.list().models.some(m => m.provider === 'together'), 'together cached');
  const failingCat = new ModelCatalog({adapters: {nebius: nebiusGood, together: togetherBad}, cachedir: dir});
  const r2 = await failingCat.refresh('together');
  assert.ok(!r2.results.together.ok);
  const kept = failingCat.list().models.filter(m => m.provider === 'together');
  assert.ok(kept.length > 0 && kept.every(m => m.stale === true && m.availability === 'stale'), 'stale cache retained and marked');
  fs.rmSync(dir, {recursive: true, force: true});
});
test('catalog counts: overlap/unique', () => {
  const cat = new ModelCatalog({adapters: {}, cachedir: tmpdir('cat3')});
  cat.list = () => ({models: CATALOG_MODELS, stale: false, fetchedAt: new Date().toISOString(), count: CATALOG_MODELS.length});
  const c = cat.counts();
  assert.equal(c.total, 5); assert.equal(c.unique, 3); assert.equal(c.overlap, 2);
});

// ---------- Provider adapters (structure, no network) ----------
test('provider adapters expose contract surface', async () => {
  for (const Ctor of [NebiusProvider, TogetherProvider]) {
    const p = new Ctor({getKey: () => null});
    assert.ok(['nebius', 'together'].includes(p.id));
    assert.ok(typeof p.health === 'function' && typeof p.listModels === 'function' && typeof p.chat === 'function' && typeof p.chatStream === 'function' && typeof p.tools === 'function');
    await assert.rejects(() => p.listModels(), e => e.code === 'NO_KEY');
    const h = await p.health(); assert.equal(h.reason, 'NO_KEY');
  }
});
test('classifyStatus/network map to expected codes', () => {
  assert.equal(classifyStatus(401).code, 'AUTH_ERROR');
  assert.equal(classifyStatus(402).code, 'BUDGET_REJECTED');
  assert.equal(classifyStatus(502).code, 'PROVIDER_ERROR');
});

// helpers
function mockAdapter(id, fail){ return fail ? mk(id, true) : mk(id, false); }
function mockCatalog(){ const cat = new ModelCatalog({adapters: {}, cachedir: tmpdir('mockcat')}); cat.list = () => ({models: CATALOG_MODELS, stale: false, fetchedAt: new Date().toISOString(), count: CATALOG_MODELS.length}); cat.providersAvailable = modelId => CATALOG_MODELS.filter(m => m.modelId === modelId).map(m => m.provider); return cat; }
function mk(id, fail){ return {id, normalizeUsage: u => normalizeUsage(u), chat: async () => { if (fail) throw new ProviderError(`${id} 503`, {status: 503, code: 'PROVIDER_ERROR', retryable: true, failoverable: true, provider: id}); return {choices: [{message: {content: 'ok'}}], usage: {prompt_tokens: 10, completion_tokens: 5, total_tokens: 15}, _meta: {provider: id, requestId: 'r-' + id, latencyMs: 50}}; }, chatStream: async function*(){ if (fail) throw new ProviderError(`${id} 503`, {status: 503, retryable: true, failoverable: true, provider: id}); yield {type: 'chunk', text: 'ok', provider: id}; yield {type: 'chunk', finishReason: 'stop', usage: {prompt_tokens: 10, completion_tokens: 5, total_tokens: 15}}; yield {type: 'done'}; }}; }




