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
