'use strict';

const assert = require('node:assert/strict');
const { parseProtectedGatewayIndex } = require('../scripts/parse_protected_gateway_index.cjs');

for (let index = 0; index <= 3; index += 1) {
  assert.equal(parseProtectedGatewayIndex(`{"target_index":${index}}`), index);
}
assert.equal(parseProtectedGatewayIndex(' { "target_index" : 2 } '), 2);

for (const invalid of [
  '',
  '0',
  '2',
  '{"target_index":4}',
  '{"target_index":-1}',
  '{"target_index":1.5}',
  '{"target_index":"1"}',
  '{"target_index":1,"target_index":2}',
  '{"target_index":1,"extra":true}',
  '{"index":1}',
  '{"target_index":01}',
  'not-json',
]) {
  assert.equal(parseProtectedGatewayIndex(invalid), undefined, `accepted invalid payload: ${invalid}`);
}

console.log('PASS: protected matched-index payload is strict JSON with one index in 0..3');
