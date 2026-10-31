import test from 'node:test';
import assert from 'node:assert/strict';
import { readJsonl, inspectDirectorOutput, scorePredictions } from '../scripts/benchmark-multimedia-director.mjs';

const r = readJsonl(new URL('./fixtures/multimedia-director-synthetic.jsonl', import.meta.url));
const p = readJsonl(new URL('./fixtures/multimedia-director-synthetic-predictions.jsonl', import.meta.url));

test('synthetic examples satisfy the offline contract', () => {
  const result = scorePredictions(r,p);
  assert.equal(result.summary.sample_count,2);
  assert.equal(result.summary.contract_pass_rate,1);
  assert.equal(result.summary.keyword_recall_mean,1);
  assert.equal(result.summary.human_visual_review,'not_performed');
});
test('reject malformed JSON instead of manufacturing creative concepts', () => {
  assert.deepEqual(inspectDirectorOutput(r[0],'{"concepts":[').issues,['invalid_json']);
});
test('detect duplicate scenes', () => {
  const altered = structuredClone(p[0].response);
  altered.concepts[1].scene = altered.concepts[0].scene;
  assert.ok(inspectDirectorOutput(r[0],altered).issues.includes('concepts_contract'));
});
test('reject unsupported long clips and forbidden words', () => {
  const altered = structuredClone(p[1].response);
  altered.shots[0].duration_seconds = 20;
  altered.shots[0].action = 'wajah berubah';
  const issues = inspectDirectorOutput(r[1],altered).issues;
  assert.ok(issues.includes('shots_contract'));
  assert.ok(issues.includes('forbidden_term'));
});
test('missing predictions and repeated ids fail closed', () => {
  assert.equal(scorePredictions(r,[p[0]]).summary.contract_pass_rate,0.5);
  assert.throws(()=>scorePredictions(r,[p[0],p[0]]),/duplicated/);
});

test('observation recall ignores unknowns, preservation warnings and creative copy', () => {
  const alt = structuredClone(p[0].response);
  alt.visual.observed_facts = ['Botol tanpa keterangan warna yang pasti'];
  alt.visual.unknowns = ['Warna botol biru belum dapat dipastikan'];
  alt.preservation_rules = ['Jangan hilangkan label asli', 'Jangan menciptakan diskon 90%'];
  alt.concepts[0].scene = 'studio menampilkan tulisan botol biru di latar';
  const checked = inspectDirectorOutput(r[0], alt);
  assert.equal(checked.factsRecall, 0);
  assert.equal(checked.forbiddenHit, false);
  assert.equal(checked.valid, true); // contract valid is NOT visual truth
});

test('forbidden assertions inside model concept copy remain detectable', () => {
  const alt = structuredClone(p[0].response);
  alt.concepts[2].tagline = 'diskon 90% tanpa sumber';
  const checked = inspectDirectorOutput(r[0], alt);
  assert.equal(checked.forbiddenHit, true);
  assert.ok(checked.issues.includes('forbidden_term'));
});

test('empty visual facts and blank unknowns cannot pass contract', () => {
  const alt = structuredClone(p[0].response);
  alt.visual.observed_facts = [];
  assert.ok(inspectDirectorOutput(r[0], alt).issues.includes('visual_contract'));
  alt.visual.observed_facts = ['detail teramati'];
  alt.visual.unknowns = [' '];
  assert.ok(inspectDirectorOutput(r[0], alt).issues.includes('visual_contract'));
});

test('real-image benchmark predictions require matching source SHA256', () => {
  const actual = [{...r[0], image_sha256:'a'.repeat(64)}];
  const mismatched = [{...p[0], image_sha256:'b'.repeat(64)}];
  const report = scorePredictions(actual, mismatched);
  assert.equal(report.summary.image_sha256_mismatch_count, 1);
  assert.equal(report.summary.contract_pass_rate, 0);
  assert.ok(report.rows[0].issues.includes('image_sha256_mismatch'));
  const good = scorePredictions(actual, [{...p[0], image_sha256:'A'.repeat(64)}]);
  assert.equal(good.summary.image_sha256_mismatch_count, 0);
  assert.equal(good.summary.contract_pass_rate, 1);
});

test('reject unknown prediction ids and physically invalid reported metrics', () => {
  assert.throws(() => scorePredictions(r, [...p, {id:'unknown',response:p[0].response}]), /Unexpected prediction id/);
  assert.throws(() => scorePredictions(r, [{...p[0],latency_ms:-1},p[1]]), /Invalid prediction telemetry/);
  assert.throws(() => scorePredictions(r, [{...p[0],cost_usd:'0.1'},p[1]]), /Invalid prediction telemetry/);
});

test('missing real-image SHA binding cannot claim a valid contract', () => {
  const actual = [{...r[0],image_sha256:'a'.repeat(64)}];
  const report = scorePredictions(actual, [p[0]]);
  assert.equal(report.summary.contract_pass_rate, 0);
  assert.ok(report.rows[0].issues.includes('image_sha256_mismatch'));
});
