const { describe, it } = require('node:test');
const assert = require('node:assert');
const { add, multiply } = require('./calculator.js');

describe('add', () => {
  it('should add two positive numbers', () => {
    assert.strictEqual(add(2, 3), 5);
  });

  it('should handle negative numbers', () => {
    assert.strictEqual(add(-1, -4), -5);
  });

  it('should return the same number when adding zero', () => {
    assert.strictEqual(add(7, 0), 7);
  });
});

describe('multiply', () => {
  it('should multiply two positive numbers', () => {
    assert.strictEqual(multiply(4, 5), 20);
  });

  it('should return zero when multiplying by zero', () => {
    assert.strictEqual(multiply(9, 0), 0);
  });

  it('should handle negative numbers', () => {
    assert.strictEqual(multiply(-3, 6), -18);
  });
});
