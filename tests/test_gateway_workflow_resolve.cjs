'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..');
const workflowPath = path.join(repoRoot, '.github', 'workflows', 'read-only-vm-metadata-diagnostic.yml');
const workflow = fs.readFileSync(workflowPath, 'utf8');
const resolveBlock = workflow.slice(workflow.indexOf('name: Resolve one gateway target'));
const scriptStart = resolveBlock.indexOf('script: |');
assert.notEqual(scriptStart, -1);
const scriptLines = resolveBlock.slice(scriptStart + 'script: |'.length).replace(/^\n/, '').split('\n');
const resolveScriptLines = [];
for (const line of scriptLines) {
  if (line.trim() && !line.startsWith('            ')) break;
  resolveScriptLines.push(line.startsWith('            ') ? line.slice(12) : '');
}
const resolveScript = resolveScriptLines.join('\n');
assert.ok(workflow.includes('  resolve:\n    runs-on: ubuntu-latest\n    permissions:\n      contents: read\n'));
assert.match(resolveBlock, /uses: actions\/checkout@v6\n\s+with:\n\s+persist-credentials: false/);
const ordinarySetup = workflow.slice(workflow.indexOf('- name: Set up gcloud\n'), workflow.indexOf('- name: Set up gcloud for passive inspection\n'));
assert.match(ordinarySetup, /if: \$\{\{ !inputs\.inspect_connections \}\}/);
assert.doesNotMatch(ordinarySetup, /NODE_OPTIONS/);
const inspectedSetup = workflow.slice(workflow.indexOf('- name: Set up gcloud for passive inspection\n'), workflow.indexOf('- name: Stop if protected cloud access is unavailable\n'));
assert.match(inspectedSetup, /if: \$\{\{ inputs\.inspect_connections && steps\.auth_filtered\.outcome == 'success' \}\}/);
assert.match(inspectedSetup, /NODE_OPTIONS: --require=\$\{\{ github\.workspace \}\}\/scripts\/filter_github_action_auth_logs\.cjs/);
assert.match(workflow, /steps\.gcloud_setup_filtered\.outcome != 'success'/);

const targets = Array.from({ length: 4 }, (_, index) => ({
  name: `gateway-${index}`,
  gcp_project_id: `mock-project-${index}`,
  gcp_workload_identity_provider: `mock-provider-${index}`,
  gcp_workload_identity_service_account: `mock-service-${index}`,
  gce_instance_name: `mock-gateway-${index}`,
  gce_zone: 'us-central1-a',
  gce_user: 'mock-user',
  ssh_private_key_secret_name: 'mock-ssh-key',
  container_name: `mock-container-${index}`,
  mode: index === 2 ? 'live' : 'paper',
}));

function runResolve(envValues) {
  const originalEnv = { ...process.env };
  for (const key of [
    'GITHUB_WORKSPACE', 'MATCH_CURRENT_GATEWAY', 'INSPECT_CONNECTIONS', 'MATCH_TARGETS_JSON',
    'MATCHED_INDEX', 'LEGACY_TARGETS_JSON', 'SELECTED_TARGET',
  ]) delete process.env[key];
  Object.assign(process.env, { GITHUB_WORKSPACE: repoRoot }, envValues);
  const result = { outputs: {}, failure: null };
  const core = {
    setOutput(name, value) { result.outputs[name] = value; },
    setFailed(message) { result.failure = message; },
  };
  try {
    new Function('core', 'require', resolveScript)(core, require);
  } finally {
    for (const key of Object.keys(process.env)) {
      if (!(key in originalEnv)) delete process.env[key];
    }
    Object.assign(process.env, originalEnv);
  }
  return result;
}

const legacy = runResolve({
  MATCH_CURRENT_GATEWAY: 'false',
  INSPECT_CONNECTIONS: 'false',
  LEGACY_TARGETS_JSON: JSON.stringify(Object.fromEntries(targets.map(({ name, ...target }) => [name, target]))),
  SELECTED_TARGET: 'gateway-2',
});
assert.equal(legacy.failure, null);
const legacyMatrix = JSON.parse(legacy.outputs.matrix).include;
assert.equal(legacyMatrix.length, 1);
assert.equal(legacyMatrix[0].target_index, 2);
assert.match(legacyMatrix[0].target_digest, /^[a-f0-9]{64}$/);

const matchOnly = runResolve({
  MATCH_CURRENT_GATEWAY: 'true',
  INSPECT_CONNECTIONS: 'false',
  MATCH_TARGETS_JSON: JSON.stringify(targets),
});
assert.equal(matchOnly.failure, null);
assert.deepEqual(JSON.parse(matchOnly.outputs.matrix).include.map((item) => item.target_index), [0, 1, 2, 3]);

const inspect = runResolve({
  MATCH_CURRENT_GATEWAY: 'true',
  INSPECT_CONNECTIONS: 'true',
  MATCH_TARGETS_JSON: JSON.stringify(targets),
  MATCHED_INDEX: '{"target_index":2}',
});
assert.equal(inspect.failure, null);
assert.deepEqual(JSON.parse(inspect.outputs.matrix).include, [{ target_index: 2, inspect_connections: true }]);

const badBinding = runResolve({
  MATCH_CURRENT_GATEWAY: 'false',
  INSPECT_CONNECTIONS: 'true',
  LEGACY_TARGETS_JSON: JSON.stringify(targets),
});
assert.equal(badBinding.failure, 'Connection inspection requires protected current-gateway matching');

console.log('PASS: actual workflow resolve step loads parser and preserves legacy/match/inspect routing');
