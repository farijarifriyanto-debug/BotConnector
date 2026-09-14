// Fixture: native-agent-acceptance
// READTEST-11111
const assert = require('assert');
const math = require('./src/math');
assert.strictEqual(math.add(2, 3), 5);
if (typeof math.subtract === 'function') assert.strictEqual(math.subtract(5, 3), 2);
console.log('TESTS DONE');
