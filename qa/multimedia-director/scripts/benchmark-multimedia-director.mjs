#!/usr/bin/env node
// Offline contract tests only. Not an image-grounding or artistic-quality judge.
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export const SCHEMA = 'botconnector.multimedia-director.v1';
export const TASKS = new Set(['product_photo', 'ad_creative', 'storyboard', 'video_direction']);
const text = value => typeof value === 'string' ? value.trim() : '';
const populated = value => Array.isArray(value) && value.length > 0 && value.every(item => text(item).length > 0);
const normalized = value => text(value).toLocaleLowerCase('id').replace(/\s+/g, ' ');
const ratio = (n, d) => d ? Number((n / d).toFixed(4)) : null;

export function inspectDirectorOutput(reference, submitted) {
  const issues = [];
  let response;
  try { response = typeof submitted === 'string' ? JSON.parse(submitted) : submitted; }
  catch { return { valid: false, issues: ['invalid_json'], factsRecall: null, forbiddenHit: null }; }
  if (!response || Array.isArray(response) || typeof response !== 'object') {
    return { valid: false, issues: ['invalid_object'], factsRecall: null, forbiddenHit: null };
  }
  if (response.schema !== SCHEMA) issues.push('schema_mismatch');
  if (response.task !== reference.task || !TASKS.has(response.task)) issues.push('task_mismatch');
  if (!response.visual || !populated(response.visual.observed_facts) ||
      !Array.isArray(response.visual.unknowns) ||
      response.visual.unknowns.some(value => !text(value))) issues.push('visual_contract');
  if (!populated(response.preservation_rules)) issues.push('preservation_rules');
  if (['product_photo', 'ad_creative'].includes(reference.task)) {
    const concepts = response.concepts;
    if (!Array.isArray(concepts) || concepts.length !== 3 ||
        concepts.some(c => !text(c?.scene) || !text(c?.tagline) || !text(c?.mood) || !text(c?.title)) ||
        new Set((concepts || []).map(c => normalized(c?.scene))).size !== 3) issues.push('concepts_contract');
  } else {
    const shots = response.shots;
    if (!Array.isArray(shots) || shots.length < 2 || shots.length > 24 ||
        shots.some(s => !text(s?.camera) || !text(s?.action) || !text(s?.subject_lock) ||
          !Number.isFinite(s?.duration_seconds) || s.duration_seconds <= 0 || s.duration_seconds > 10))
      issues.push('shots_contract');
  }
  // Do not credit an observed fact simply because it occurs in "unknowns",
  // preservation warnings, JSON keys, or a creative concept. This remains
  // a lexical proxy, NOT a measurement of image grounding.
  const facts = Array.isArray(response.visual?.observed_facts)
    ? response.visual.observed_facts.filter(value => text(value)) : [];
  const required = Array.isArray(reference.required_terms) ? reference.required_terms : [];
  const forbidden = Array.isArray(reference.forbidden_terms) ? reference.forbidden_terms : [];
  const asserted = [...facts];
  if (['product_photo', 'ad_creative'].includes(reference.task) && Array.isArray(response.concepts)) {
    for (const concept of response.concepts) {
      asserted.push(concept?.title, concept?.scene, concept?.mood, concept?.tagline);
    }
  }
  if (['storyboard', 'video_direction'].includes(reference.task) && Array.isArray(response.shots)) {
    for (const shot of response.shots) {
      asserted.push(shot?.action, shot?.subject_lock, shot?.camera);
    }
  }
  const requiredNormalized = required.map(normalized).filter(Boolean);
  const forbiddenNormalized = forbidden.map(normalized).filter(Boolean);
  const factsRecall = ratio(
    requiredNormalized.filter(term => facts.some(fact => normalized(fact).includes(term))).length,
    requiredNormalized.length
  );
  // Unknowns and explicit preservation prohibitions are not assertions.
  // Negation inside assertions is still a known limitation of lexical checks.
  const forbiddenHit = forbiddenNormalized.some(term =>
    asserted.some(phrase => normalized(phrase).includes(term)));
  if (forbiddenHit) issues.push('forbidden_term');
  return { valid: issues.length === 0, issues, factsRecall, forbiddenHit };
}

export function scorePredictions(referenceCases, predictions) {
  const ids = new Set();
  const predictionMap = new Map();
  for (const p of predictions) {
    if (!text(p?.id) || predictionMap.has(p.id)) throw new Error('Prediction id missing or duplicated.');
    for (const field of ['latency_ms', 'cost_usd']) {
      if (p[field] != null && (!Number.isFinite(p[field]) || p[field] < 0))
        throw new Error('Invalid prediction telemetry: ' + field);
    }
    predictionMap.set(p.id, p);
  }
  const rows = [];
  for (const r of referenceCases) {
    if (!text(r?.id) || ids.has(r.id) || !TASKS.has(r.task)) throw new Error('Reference id/task missing or duplicated.');
    ids.add(r.id);
    const p = predictionMap.get(r.id);
    const checked = p ? inspectDirectorOutput(r, p.response) :
      { valid:false, issues:['missing_prediction'], factsRecall:null, forbiddenHit:null };
    // A real-image reference must be compared only to a prediction bound
    // to that SAME original image. A SHA match alone does not grant rights.
    if (p && r.image_sha256 &&
        (!/^[a-f0-9]{64}$/i.test(r.image_sha256) ||
         p.image_sha256?.toLowerCase() !== r.image_sha256.toLowerCase())) {
      checked.issues.push('image_sha256_mismatch');
      checked.valid = false;
    }
    rows.push({
      id:r.id, task:r.task, model_id:p?.model_id || null, valid:checked.valid,
      issues:checked.issues, facts_recall_keyword_proxy:checked.factsRecall,
      forbidden_keyword_hit:checked.forbiddenHit,
      latency_ms:Number.isFinite(p?.latency_ms)?p.latency_ms:null,
      cost_usd:Number.isFinite(p?.cost_usd)?p.cost_usd:null,
      human_visual_review:'required'
    });
  }
  for (const id of predictionMap.keys()) {
    if (!ids.has(id)) throw new Error('Unexpected prediction id: ' + id);
  }
  const latencies = rows.map(x => x.latency_ms).filter(x => x !== null).sort((a,b) => a-b);
  const costs = rows.map(x => x.cost_usd).filter(x => x !== null);
  const recalls = rows.map(x => x.facts_recall_keyword_proxy).filter(x => x !== null);
  const summary = {
    sample_count:rows.length,
    image_sha256_mismatch_count:rows.filter(x=>x.issues.includes('image_sha256_mismatch')).length,
    latency_samples:latencies.length,
    cost_samples:costs.length,
    contract_pass_rate:ratio(rows.filter(x=>x.valid).length,rows.length),
    forbidden_keyword_hit_rate:ratio(rows.filter(x=>x.forbidden_keyword_hit).length,rows.length),
    keyword_recall_mean:recalls.length ? Number((recalls.reduce((a,b)=>a+b,0)/recalls.length).toFixed(4)) : null,
    latency_p95_ms:latencies.length ? latencies[Math.ceil(latencies.length*.95)-1] : null,
    measured_cost_usd:costs.length ? Number(costs.reduce((a,b)=>a+b,0).toFixed(6)) : null,
    human_visual_review:'not_performed',
    note:'Facts recall checks observed_facts only; lexical assertion checks are not truth or negation judges. Timings/costs are unverified prediction metadata. Independent human image review and measured runtime are required.'
  };
  return {schema:'botconnector.multimedia-director-benchmark.v1',summary,rows};
}

export function readJsonl(path) {
  return readFileSync(path,'utf8').split(/\r?\n/).map(x=>x.trim()).filter(Boolean).map((line,index)=>{
    try { return JSON.parse(line); }
    catch { throw new Error('Invalid JSONL at ' + String(path) + ':' + (index+1)); }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [referencesPath, predictionsPath, reportPath] = process.argv.slice(2);
  if (!referencesPath || !predictionsPath) {
    console.error('Usage: node scripts/benchmark-multimedia-director.mjs references.jsonl predictions.jsonl [report.json]');
    process.exitCode = 2;
  } else {
    try {
      const report = scorePredictions(readJsonl(referencesPath), readJsonl(predictionsPath));
      const output = JSON.stringify(report,null,2)+'\n';
      if (reportPath) writeFileSync(reportPath,output,{flag:'wx'});
      else process.stdout.write(output);
      if (report.summary.contract_pass_rate !== 1) process.exitCode = 1;
    } catch (error) { console.error(error.message); process.exitCode = 2; }
  }
}
