import { test } from 'node:test';
import assert from 'node:assert/strict';
import { add, multiply } from './math.js';

test('add sums two positive numbers', () => {
  assert.equal(add(2, 3), 5);
});

test('add sums a negative and a positive number', () => {
  assert.equal(add(-4, 10), 6);
});

test('add sums zeros', () => {
  assert.equal(add(0, 0), 0);
});

test('multiply multiplies two positive numbers', () => {
  assert.equal(multiply(4, 5), 20);
});

test('multiply by zero is zero', () => {
  assert.equal(multiply(7, 0), 0);
});

test('multiply with a negative number', () => {
  assert.equal(multiply(-3, 6), -18);
});
