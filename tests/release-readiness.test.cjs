'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.join(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const cli = path.join(root, pkg.bin.botconnector);

function run(...args) {
  return spawnSync(process.execPath, [cli, ...args], { cwd: root, encoding: 'utf8', windowsHide: true });
}

test('public beta package identity and metadata are release-shaped', () => {
  assert.equal(pkg.name, 'botconnector-ai');
  assert.equal(pkg.version, '0.5.0-beta1');
  assert.notEqual(pkg.private, true);
  assert.equal(pkg.bin.botconnector, 'bin/botconnector.mjs');
  for (const field of ['description', 'license', 'repository', 'homepage', 'bugs', 'author', 'engines', 'keywords', 'files']) assert.ok(pkg[field], field);
  assert.equal(pkg.license, 'MIT');
  assert.ok(pkg.files.every((entry) => !/(?:tests|fixtures|checkpoints|backups)/i.test(entry)));
});

test('version output is stable and human-readable', () => {
  const result = run('--version');
  assert.equal(result.status, 0);
  assert.equal(result.stdout.trim(), 'botconnector 0.5.0-beta1');
});

test('global and subcommand help exit successfully', () => {
  const global = run('--help');
  assert.equal(global.status, 0);
  assert.match(global.stdout, /botconnector launch/);
  const sub = run('launch', '--help');
  assert.equal(sub.status, 0);
  assert.match(sub.stdout, /botconnector launch --list/);
});

test('unknown commands use a distinct nonzero exit code', () => {
  const result = run('not-a-command');
  assert.equal(result.status, 2);
  assert.match(result.stderr, /unknown command: not-a-command/);
});
