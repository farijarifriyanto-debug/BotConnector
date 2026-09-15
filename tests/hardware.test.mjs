import test from 'node:test';
import assert from 'node:assert/strict';
import {  detectHardware, assessFit, maxKnownVram  } from '../lib/hardware.mjs';

const HW = { ramGb: 16, vramGb: 0, override: false, nvidia: [], amd: [], intel: [] };

test('cloud tidak menilai hardware', () => {
  assert.equal(assessFit({ kind: 'cloud' }, HW).level, 'cloud');
});

test('matriks skor: no/great/ok/warn', () => {
  assert.equal(assessFit({ kind: 'local', minRamGb: 32, recRamGb: 64, recVramGb: 24 }, HW).level, 'no');
  assert.equal(assessFit({ kind: 'local', minRamGb: 8, recRamGb: 16, recVramGb: 0 }, { ...HW, vramGb: 6 }).level, 'great');
  assert.equal(assessFit({ kind: 'local', minRamGb: 8, recRamGb: 16, recVramGb: 24 }, HW).level, 'ok');
  assert.equal(assessFit({ kind: 'local', minRamGb: 8, recRamGb: 32, recVramGb: 24 }, HW).level, 'warn');
});

test('confidence jujur: override vs estimated', () => {
  const req = { kind: 'local', minRamGb: 8, recRamGb: 16, recVramGb: 0 };
  assert.equal(assessFit(req, HW).confidence, 'estimated');
  assert.equal(assessFit(req, { ...HW, override: true }).confidence, 'override');
});

test('maxKnownVram mengabaikan null/tak diketahui', () => {
  const hw = { nvidia: [{ memoryGb: 8 }], amd: [{ memoryGb: null }], intel: [{ memoryGb: 0 }] };
  assert.equal(maxKnownVram(hw), 8);
  assert.equal(maxKnownVram({ nvidia: [], amd: [], intel: [] }), 0);
});

test('detectHardware tidak pernah throw dan bentuknya stabil', async () => {
  const hw = await detectHardware();
  assert.equal(typeof hw.ramGb, 'number');
  assert.ok(Array.isArray(hw.nvidia) && Array.isArray(hw.amd) && Array.isArray(hw.intel));
  assert.equal(typeof hw.vramGb, 'number');
});
