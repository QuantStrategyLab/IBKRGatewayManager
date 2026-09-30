'use strict';

const rawStdoutWrite = process.stdout.write.bind(process.stdout);
const rawStderrWrite = process.stderr.write.bind(process.stderr);
let stdoutRemainder = '';

function callbackFrom(encoding, callback) {
  if (typeof encoding === 'function') return encoding;
  return typeof callback === 'function' ? callback : null;
}

function acceptedMaskCommands(value, flush = false) {
  stdoutRemainder += value;
  let output = '';
  while (true) {
    const newline = stdoutRemainder.indexOf('\n');
    if (newline < 0) break;
    const line = stdoutRemainder.slice(0, newline + 1);
    stdoutRemainder = stdoutRemainder.slice(newline + 1);
    if (line.startsWith('::add-mask::')) output += line;
  }
  if (flush && stdoutRemainder.startsWith('::add-mask::')) output += `${stdoutRemainder}\n`;
  if (flush) stdoutRemainder = '';
  return output;
}

process.stdout.write = function filteredStdoutWrite(chunk, encoding, callback) {
  const done = callbackFrom(encoding, callback);
  const text = Buffer.isBuffer(chunk) || chunk instanceof Uint8Array
    ? Buffer.from(chunk).toString(typeof encoding === 'string' ? encoding : 'utf8')
    : String(chunk);
  const allowed = acceptedMaskCommands(text);
  if (!allowed) {
    if (done) process.nextTick(done);
    return true;
  }
  return rawStdoutWrite(allowed, 'utf8', done || undefined);
};

process.stderr.write = function filteredStderrWrite(chunk, encoding, callback) {
  const done = callbackFrom(encoding, callback);
  if (done) process.nextTick(done);
  return true;
};

process.on('uncaughtException', () => {
  if (process.exitCode === undefined || process.exitCode === 0) process.exitCode = 1;
});

process.on('unhandledRejection', () => {
  if (process.exitCode === undefined || process.exitCode === 0) process.exitCode = 1;
});

process.on('exit', (code) => {
  const pendingMask = acceptedMaskCommands('', true);
  if (pendingMask) rawStdoutWrite(pendingMask);
  if (code !== 0) rawStderrWrite('GCP_AUTH_ACTION_STATUS=failed\n');
});
