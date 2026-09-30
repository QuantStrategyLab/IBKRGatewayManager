'use strict';

function parseProtectedGatewayIndex(raw) {
  if (typeof raw !== 'string' || !/^\s*\{\s*"target_index"\s*:\s*(0|[1-3])\s*\}\s*$/.test(raw)) {
    return undefined;
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return undefined;
  }
  if (!payload || Array.isArray(payload) || Object.keys(payload).length !== 1 ||
      !Object.hasOwn(payload, 'target_index') || !Number.isInteger(payload.target_index) ||
      payload.target_index < 0 || payload.target_index > 3) {
    return undefined;
  }
  return payload.target_index;
}

module.exports = { parseProtectedGatewayIndex };
