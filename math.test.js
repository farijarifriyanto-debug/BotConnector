import test from 'node:test';
import assert from 'node:assert';
import { add, multiply } from './math.js';

test('add returns sum of two positive numbers', () => {
  assert.strictEqual(add(2, 3), 5);
});

test('add returns sum with negative numbers', () => {
  assert.strictEqual(add(-1, -1), -2);
});

test('add returns zero when both inputs are zero', () => {
  assert.strictEqual(add(0, 0), 0);
});

test('multiply returns product of two positive numbers', () => {
  assert.strictEqual(multiply(4, 5), 20);
});

test('multiply returns negative product with one negative input', () => {
  assert.strictEqual(multiply(-3, 2), -6);
});

test('multiply returns zero when one input is zero', () => {
  assert.strictEqual(multiply(0, 100), 0);
});
