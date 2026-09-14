import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const project = path.dirname(root);
const pkg = JSON.parse(fs.readFileSync(path.join(project, 'package.json'), 'utf8'));
const checks = [];
const check = (name, ok, detail = '') => {
  checks.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
};

check('PACKAGE_NAME', pkg.name === 'botconnector-ai', pkg.name);
check('VERSION', pkg.version === '0.5.0-beta1', pkg.version);
check('NOT_PRIVATE', pkg.private !== true);
check('CLI_BIN', pkg.bin?.botconnector === 'bin/botconnector.mjs', pkg.bin?.botconnector || 'missing');
check('LICENSE', pkg.license === 'MIT' && fs.existsSync(path.join(project, 'LICENSE')), pkg.license || 'missing');
check('METADATA', Boolean(pkg.description && pkg.repository && pkg.homepage && pkg.bugs && pkg.author && pkg.engines?.node && Array.isArray(pkg.keywords)));
check('FILES_WHITELIST', Array.isArray(pkg.files) && pkg.files.length > 0 && !pkg.files.some((entry) => /(?:tests|fixtures|checkpoints|backup|\.env)/i.test(entry)));

const version = spawnSync(process.execPath, [path.join(project, pkg.bin.botconnector), '--version'], { encoding: 'utf8', windowsHide: true });
check('VERSION_OUTPUT', version.status === 0 && version.stdout.trim() === `botconnector ${pkg.version}`, version.stdout.trim());

const npmCli = process.env.npm_execpath || path.join(path.dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js');
const pack = spawnSync(process.execPath, [npmCli, 'pack', '--dry-run', '--json'], { cwd: project, encoding: 'utf8', windowsHide: true });
let packRows = [];
try { packRows = JSON.parse(pack.stdout); } catch {}
const packed = packRows[0]?.files || [];
const packedPaths = packed.map((entry) => entry.path);
const forbidden = packedPaths.filter((entry) => /(?:^|\/)(?:tests?|fixtures?|checkpoints?|backups?)(?:\/|$)|(?:\.env|\.bak|\.log)$/i.test(entry));
check('PACK_DRY_RUN', pack.status === 0 && packedPaths.includes('package.json') && packedPaths.includes('bin/botconnector.mjs') && forbidden.length === 0, forbidden.length ? `forbidden: ${forbidden.join(', ')}` : `${packedPaths.length} files`);

const failed = checks.filter((item) => !item.ok);
if (failed.length) process.exit(1);
