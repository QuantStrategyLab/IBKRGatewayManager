'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..');
const preload = path.join(repoRoot, 'scripts', 'filter_github_action_auth_logs.cjs');
const syntheticCode = [
  "process.stdout.write('raw sdk diagnostic synthetic-token\\n');",
  "process.stdout.write('::add-mask::synthetic-token\\n');",
  "process.stdout.write('::error::raw sdk setup failure synthetic-token\\n');",
  "console.error('raw sdk error synthetic-token');",
].join('\n');

function run(code, nodeOptions, extraEnv = {}) {
  const env = { ...process.env };
  if (nodeOptions === undefined) delete env.NODE_OPTIONS;
  else env.NODE_OPTIONS = nodeOptions;
  Object.assign(env, extraEnv);
  return spawnSync(process.execPath, ['-e', code], { encoding: 'utf8', env });
}

const defaultResult = run(`${syntheticCode}\nprocess.exitCode = 0;`);
assert.equal(defaultResult.status, 0);
assert.match(defaultResult.stdout, /raw sdk diagnostic synthetic-token/);
assert.match(defaultResult.stdout, /::add-mask::synthetic-token/);
assert.match(defaultResult.stderr, /raw sdk error synthetic-token/);

const filteredSuccess = run(`${syntheticCode}\nprocess.exitCode = 0;`, `--require=${preload}`);
assert.equal(filteredSuccess.status, 0);
assert.equal(filteredSuccess.stdout, '::add-mask::synthetic-token\n');
assert.equal(filteredSuccess.stderr, '');

const filteredFailure = run(`${syntheticCode}\nprocess.exitCode = 17;`, `--require=${preload}`);
assert.equal(filteredFailure.status, 17);
assert.equal(filteredFailure.stdout, '::add-mask::synthetic-token\n');
assert.equal(filteredFailure.stderr, 'GCP_AUTH_ACTION_STATUS=failed\n');
assert.doesNotMatch(filteredFailure.stderr, /raw sdk|synthetic-token/);

const filteredThrow = run("throw new Error('synthetic-token');", `--require=${preload}`);
assert.notEqual(filteredThrow.status, 0);
assert.equal(filteredThrow.stdout, '');
assert.equal(filteredThrow.stderr, 'GCP_AUTH_ACTION_STATUS=failed\n');

const filteredRejection = run("Promise.reject(new Error('synthetic-rejection-token'));", `--require=${preload}`);
assert.notEqual(filteredRejection.status, 0);
assert.equal(filteredRejection.stdout, '');
assert.equal(filteredRejection.stderr, 'GCP_AUTH_ACTION_STATUS=failed\n');

const fileCommandDir = fs.mkdtempSync(path.join(os.tmpdir(), 'gateway-auth-filter-'));
const envFile = path.join(fileCommandDir, 'env');
const outputFile = path.join(fileCommandDir, 'output');
const pathFile = path.join(fileCommandDir, 'path');
for (const filename of [envFile, outputFile, pathFile]) fs.writeFileSync(filename, '');
const fileCommands = run([
  "const fs = require('node:fs');",
  "fs.appendFileSync(process.env.GITHUB_ENV, 'FILTER_TEST_ENV=present\\n');",
  "fs.appendFileSync(process.env.GITHUB_OUTPUT, 'filter_test_output=present\\n');",
  "fs.appendFileSync(process.env.GITHUB_PATH, '/tmp/filter-test-bin\\n');",
  "process.stdout.write('ordinary tool setup log\\n');",
].join('\n'), `--require=${preload}`, {
  GITHUB_ENV: envFile,
  GITHUB_OUTPUT: outputFile,
  GITHUB_PATH: pathFile,
});
assert.equal(fileCommands.status, 0);
assert.equal(fileCommands.stdout, '');
assert.equal(fs.readFileSync(envFile, 'utf8'), 'FILTER_TEST_ENV=present\n');
assert.equal(fs.readFileSync(outputFile, 'utf8'), 'filter_test_output=present\n');
assert.equal(fs.readFileSync(pathFile, 'utf8'), '/tmp/filter-test-bin\n');
fs.rmSync(fileCommandDir, { recursive: true, force: true });

console.log('PASS: auth action log filter preserves add-mask, fixed failure status, and default behavior');
