import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
process.env.POC_STATE = path.join(os.tmpdir(), `poc-test-slots-${process.pid}.json`);
import http from 'node:http';
import {  addProfile, removeProfile, liveStatus, switchProfile, normalizeBaseUrl  } from '../lib/slots.mjs';

function stubServer(healthStatus = 200) {
  const srv = http.createServer((req, res) => {
    if (req.url === '/health') { res.writeHead(healthStatus); res.end('{}'); }
    else { res.writeHead(404); res.end(); }
  });
  return new Promise((resolve) => srv.listen(0, '127.0.0.1', () => resolve(srv)));
}
const baseOf = (srv) => `http://127.0.0.1:${srv.address().port}`;

test('menolak baseUrl non-localhost', async () => {
  assert.throws(() => normalizeBaseUrl('http://192.168.1.5:11435'), /localhost/);
  assert.throws(() => normalizeBaseUrl('https://example.com/'), /localhost/);
});

test('switch hanya ke profil yang /health-nya UP (bukti HTTP nyata)', async () => {
  const up = await stubServer(200);
  const down = await stubServer(500);
  try {
    await addProfile('nyata-up', baseOf(up));
    await addProfile('nyata-down', baseOf(down));
    const ok = await switchProfile('nyata-up');
    assert.equal(ok.active, 'nyata-up');
    await assert.rejects(() => switchProfile('nyata-down'), /DOWN/);
    await assert.rejects(() => switchProfile('tidak-ada'), /tidak dikenal/);
    const st = await liveStatus();
    assert.equal(st.active, 'nyata-up');
    assert.equal(st.profiles.find((p) => p.name === 'nyata-up').up, true);
    assert.equal(st.profiles.find((p) => p.name === 'nyata-down').up, false);
  } finally {
    await removeProfile('nyata-up').catch(() => {});
    await removeProfile('nyata-down').catch(() => {});
    up.close(); down.close();
  }
});

test('unload profil aktif mengosongkan active', async () => {
  const srv = await stubServer(200);
  try {
    await addProfile('sementara', baseOf(srv));
    await switchProfile('sementara');
    await removeProfile('sementara');
    assert.equal((await liveStatus()).active, null);
  } finally { srv.close(); }
});
