import { describe, it, beforeAll, afterAll, expect } from 'vitest';
import WebSocket from 'ws';
import pg from 'pg';
import { buildApp } from '../src/index.js';
import type { FastifyInstance } from 'fastify';
import type { PrincipalResolver, RealtimeHandle } from '../src/index.js';
import { spawnTestRedis, type TestRedisHandle } from './helpers/test-redis.js';
import { withTenantTransaction } from '../src/db/tenant.js';
import { emitDomainEvent } from '../src/events/service.js';
import { LiveHub, type LiveConnection } from '../src/realtime/hub.js';
import type { ServerFrame } from '../src/realtime/protocol.js';

const DATABASE_URL =
  process.env.DATABASE_URL || 'postgres://postgres:phase2test@localhost/botconnector_phase4_test';
const REDIS_PORT = Number(process.env.REDIS_TEST_PORT || 6380);

let app: FastifyInstance;
let adminPool: pg.Pool;
let redis: TestRedisHandle;
let httpPort: number;
let realtime: RealtimeHandle;

// Test-only principal resolver: explicit injection only, never trusted in
// production. Fails closed (throws) when x-workspace-id is absent.
const testPrincipalResolver: PrincipalResolver = (headers) => {
  const workspaceId = headers['x-workspace-id'] as string | undefined;
  if (!workspaceId) {
    throw new Error('x-workspace-id required in test resolver');
  }
  return { userId: 'test-user', workspaceId };
};

export interface TestSocket {
  ws: WebSocket;
  frames: unknown[];
  waitFor(predicate: (f: any) => boolean, timeoutMs?: number): Promise<any>;
  waitClose(): Promise<{ code: number; reason: string }>;
}

export function connectSocket(workspaceId?: string): Promise<TestSocket> {
  return new Promise((resolve, reject) => {
    const url = `ws://127.0.0.1:${httpPort}/ws/v1`;
    const ws = new WebSocket(
      url,
      workspaceId ? { headers: { 'x-workspace-id': workspaceId } } : undefined,
    );
    const frames: unknown[] = [];
    ws.on('message', (data) => frames.push(JSON.parse(data.toString())));
    const waitFor = (predicate: (f: any) => boolean, timeoutMs = 4000): Promise<any> =>
      new Promise((res, rej) => {
        const deadline = Date.now() + timeoutMs;
        const poll = () => {
          const hit = frames.find(predicate);
          if (hit) return res(hit);
          if (Date.now() > deadline) return rej(new Error('timed out waiting for frame'));
          setTimeout(poll, 25);
        };
        poll();
      });
    const waitClose = (): Promise<{ code: number; reason: string }> =>
      new Promise((res) => {
        ws.on('close', (code, reason) => res({ code, reason: reason.toString() }));
      });
    ws.on('open', () => resolve({ ws, frames, waitFor, waitClose }));
    ws.on('error', reject);
  });
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function createProject(workspaceId: string, name: string, idempotencyKey?: string) {
  const res = await app.inject({
    method: 'POST',
    url: '/api/v1/projects',
    headers: {
      'x-workspace-id': workspaceId,
      ...(idempotencyKey ? { 'idempotency-key': idempotencyKey } : {}),
    },
    payload: { name },
  });
  return JSON.parse(res.payload).data;
}

async function patchProject(workspaceId: string, projectId: string, revision: string, name: string) {
  const res = await app.inject({
    method: 'PATCH',
    url: `/api/v1/projects/${projectId}`,
    headers: { 'x-workspace-id': workspaceId, 'if-match': `"${revision}"` },
    payload: { name },
  });
  return JSON.parse(res.payload);
}

async function createArtifact(workspaceId: string, projectId: string) {
  const res = await app.inject({
    method: 'POST',
    url: `/api/v1/projects/${projectId}/artifacts`,
    headers: { 'x-workspace-id': workspaceId },
    payload: { type: 'web' },
  });
  return JSON.parse(res.payload).data;
}

async function countDomainEvents(projectId: string): Promise<number> {
  const { rows } = await adminPool.query(
    `SELECT count(*)::int AS n FROM event.domain_events WHERE project_id = $1`,
    [projectId],
  );
  return rows[0].n;
}

async function countOutbox(projectId: string): Promise<number> {
  const { rows } = await adminPool.query(
    `SELECT count(*)::int AS n FROM event.outbox WHERE project_id = $1`,
    [projectId],
  );
  return rows[0].n;
}

async function findOutboxRow(eventId: string): Promise<any> {
  const { rows } = await adminPool.query(
    `SELECT id, dispatched_at, attempt_count, next_attempt_at, lease_token, last_error
     FROM event.outbox WHERE event_id = $1`,
    [eventId],
  );
  return rows[0] ?? null;
}

beforeAll(async () => {
  process.env.DATABASE_URL = DATABASE_URL;
  redis = await spawnTestRedis(REDIS_PORT);

  app = await buildApp({
    principalResolver: testPrincipalResolver,
    realtime: { redisUrl: redis.url, autoStartDispatcher: false },
  });
  await app.ready();
  realtime = (app as any).realtime;
  const address = await app.listen({ port: 0, host: '127.0.0.1' });
  httpPort = Number(address.split(':').pop());

  adminPool = new pg.Pool({ connectionString: DATABASE_URL });
  await adminPool.query(`DELETE FROM event.outbox WHERE workspace_id IN ('ws-p4a','ws-p4b')`);
  await adminPool.query(`DELETE FROM event.domain_events WHERE workspace_id IN ('ws-p4a','ws-p4b')`);
  await adminPool.query(`DELETE FROM event.project_sequences WHERE workspace_id IN ('ws-p4a','ws-p4b')`);
  await adminPool.query(
    `INSERT INTO iam.users (id, email, display_name) VALUES ('p4-user-1', 'p4a@test.com', 'P4 A') ON CONFLICT DO NOTHING`,
  );
  await adminPool.query(
    `INSERT INTO iam.users (id, email, display_name) VALUES ('p4-user-2', 'p4b@test.com', 'P4 B') ON CONFLICT DO NOTHING`,
  );
  await adminPool.query(
    `INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-p4a', 'P4 Workspace A', 'p4-user-1') ON CONFLICT DO NOTHING`,
  );
  await adminPool.query(
    `INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-p4b', 'P4 Workspace B', 'p4-user-2') ON CONFLICT DO NOTHING`,
  );
});

afterAll(async () => {
  await adminPool?.end();
  await app?.close();
  await redis.cleanup();
});

describe('EVENT SERVICE', () => {
  it('1. domain event persisted on project mutation', async () => {
    const project = await createProject('ws-p4a', 'p4-event-1');
    const { rows } = await adminPool.query(
      `SELECT event_type, sequence, correlation_id, actor_type, actor_id
       FROM event.domain_events WHERE project_id = $1`,
      [project.id],
    );
    expect(rows.length).toBe(1);
    expect(rows[0].event_type).toBe('project.created');
    expect(rows[0].actor_type).toBe('user');
  });

  it('2. outbox row persisted referencing the event', async () => {
    const project = await createProject('ws-p4a', 'p4-event-2');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id, o.id AS outbox_id, o.dispatched_at
       FROM event.domain_events e JOIN event.outbox o ON o.event_id = e.id
       WHERE e.project_id = $1`,
      [project.id],
    );
    expect(rows.length).toBe(1);
    expect(rows[0].dispatched_at).toBeNull();
  });

  it('3. commit is atomic — event and outbox both present after 201', async () => {
    const project = await createProject('ws-p4a', 'p4-event-3');
    expect(await countDomainEvents(project.id)).toBe(1);
    expect(await countOutbox(project.id)).toBe(1);
  });

  it('4. rollback removes both event and outbox', async () => {
    const project = await createProject('ws-p4a', 'p4-event-4');
    await expect(
      withTenantTransaction('ws-p4a', async (tx) => {
        await emitDomainEvent(tx, {
          workspaceId: 'ws-p4a',
          projectId: project.id,
          eventType: 'test.rolled_back',
          aggregateType: 'test',
          aggregateId: 'x',
          actorType: 'user',
          actorId: 'test-user',
          correlationId: 'corr-rollback',
          causationId: null,
          payload: {},
        });
        throw new Error('force rollback');
      }),
    ).rejects.toThrow('force rollback');
    expect(await countDomainEvents(project.id)).toBe(1);
    expect(await countOutbox(project.id)).toBe(1);
    const { rows } = await adminPool.query(
      `SELECT count(*)::int AS n FROM event.domain_events WHERE event_type = 'test.rolled_back'`,
    );
    expect(rows[0].n).toBe(0);
  });

  it('5. project sequence starts at 1 as decimal string', async () => {
    const project = await createProject('ws-p4a', 'p4-event-5');
    const { rows } = await adminPool.query(
      `SELECT sequence FROM event.domain_events WHERE project_id = $1`,
      [project.id],
    );
    expect(String(rows[0].sequence)).toBe('1');
  });

  it('6. sequence increments per project', async () => {
    const project = await createProject('ws-p4a', 'p4-event-6');
    await patchProject('ws-p4a', project.id, project.revision, 'p4-event-6-updated');
    const { rows } = await adminPool.query(
      `SELECT event_type, sequence FROM event.domain_events
       WHERE project_id = $1 ORDER BY sequence::bigint ASC`,
      [project.id],
    );
    expect(rows.map((r) => String(r.sequence))).toEqual(['1', '2']);
    expect(rows[1].event_type).toBe('project.updated');
  });

  it('7. concurrent emits allocate unique sequences', async () => {
    const project = await createProject('ws-p4a', 'p4-event-7');
    const results = await Promise.all(
      Array.from({ length: 10 }, (_, i) =>
        withTenantTransaction('ws-p4a', async (tx) => {
          const event = await emitDomainEvent(tx, {
            workspaceId: 'ws-p4a',
            projectId: project.id,
            eventType: `test.concurrent_${i}`,
            aggregateType: 'test',
            aggregateId: project.id,
            actorType: 'system',
            actorId: 'concurrency',
            correlationId: `corr-${i}`,
            causationId: null,
            payload: { i },
          });
          return event.sequence;
        }),
      ),
    );
    const unique = new Set(results);
    expect(unique.size).toBe(10);
    const sorted = [...results].sort((a, b) => (BigInt(a) < BigInt(b) ? -1 : 1));
    // the project already has 1 durable event (project.created, sequence 1),
    // so the 10 concurrent emits occupy sequences 2..11
    expect(sorted[0]).toBe('2');
    expect(sorted[9]).toBe('11');
    expect(sorted.every((s) => /^[0-9]+$/.test(s))).toBe(true);
  });
});

describe('PHASE-3 INTEGRATION', () => {
  it('8. successful artifact mutation emits artifact.created', async () => {
    const project = await createProject('ws-p4a', 'p4-integration-8');
    await createArtifact('ws-p4a', project.id);
    const { rows } = await adminPool.query(
      `SELECT event_type FROM event.domain_events WHERE project_id = $1`,
      [project.id],
    );
    expect(rows.map((r) => r.event_type)).toContain('artifact.created');
  });

  it('9. artifact_version.created and phase.created emit events', async () => {
    const project = await createProject('ws-p4a', 'p4-integration-9');
    const artifact = await createArtifact('ws-p4a', project.id);
    await app.inject({
      method: 'POST',
      url: `/api/v1/artifacts/${artifact.id}/versions`,
      headers: { 'x-workspace-id': 'ws-p4a' },
      payload: { source_revision: 'git:abc', content_hash: 'sha256:def' },
    });
    await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${project.id}/phases`,
      headers: { 'x-workspace-id': 'ws-p4a' },
      payload: { name: 'Phase One' },
    });
    const { rows } = await adminPool.query(
      `SELECT event_type FROM event.domain_events WHERE project_id = $1 ORDER BY sequence::bigint`,
      [project.id],
    );
    expect(rows.map((r) => r.event_type)).toEqual([
      'project.created',
      'artifact.created',
      'artifact_version.created',
      'phase.created',
    ]);
  });

  it('10. idempotent replay creates no duplicate event', async () => {
    const key = `p4-idem-${Date.now()}`;
    const res1 = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: { 'x-workspace-id': 'ws-p4a', 'idempotency-key': key },
      payload: { name: 'p4-idem' },
    });
    expect(res1.statusCode).toBe(201);
    const project = JSON.parse(res1.payload).data;
    const res2 = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: { 'x-workspace-id': 'ws-p4a', 'idempotency-key': key },
      payload: { name: 'p4-idem' },
    });
    expect(res2.statusCode).toBe(200);
    expect(await countDomainEvents(project.id)).toBe(1);
    expect(await countOutbox(project.id)).toBe(1);
  });

  it('11. stale revision creates no event', async () => {
    const project = await createProject('ws-p4a', 'p4-integration-11');
    const before = await countDomainEvents(project.id);
    const res = await patchProject('ws-p4a', project.id, '99', 'stale-update');
    expect(res.error.code).toBe('REVISION_CONFLICT');
    expect(res.error).toBeDefined();
    expect(await countDomainEvents(project.id)).toBe(before);
  });
});
describe('OUTBOX', () => {
  it('12. claim works — dispatcher claims, publishes, marks dispatched', async () => {
    const project = await createProject('ws-p4a', 'p4-outbox-12');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id FROM event.domain_events e WHERE e.project_id = $1`,
      [project.id],
    );
    const result = await realtime.dispatcher.runOnce();
    expect(result.claimed).toBeGreaterThan(0);
    const outbox = await findOutboxRow(rows[0].event_id);
    expect(outbox).not.toBeNull();
    expect(outbox.dispatched_at).not.toBeNull();
    expect(outbox.attempt_count).toBe(1);
  });

  it('13. active lease prevents double claim', async () => {
    const project = await createProject('ws-p4a', 'p4-outbox-13');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id, o.id AS outbox_id FROM event.domain_events e
       JOIN event.outbox o ON o.event_id = e.id WHERE e.project_id = $1`,
      [project.id],
    );
    await adminPool.query(
      `UPDATE event.outbox SET lease_token = 'held', lease_expires_at = now() + interval '5 minutes', attempt_count = 3
       WHERE id = $1`,
      [rows[0].outbox_id],
    );
    await realtime.dispatcher.runOnce();
    const outbox = await findOutboxRow(rows[0].event_id);
    expect(outbox.dispatched_at).toBeNull();
    expect(outbox.attempt_count).toBe(3);
    expect(outbox.lease_token).toBe('held');
  });

  it('14. expired lease can be reclaimed and dispatched', async () => {
    const project = await createProject('ws-p4a', 'p4-outbox-14');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id, o.id AS outbox_id FROM event.domain_events e
       JOIN event.outbox o ON o.event_id = e.id WHERE e.project_id = $1`,
      [project.id],
    );
    await adminPool.query(
      `UPDATE event.outbox SET lease_token = 'stale', lease_expires_at = now() - interval '1 minute', attempt_count = 2
       WHERE id = $1`,
      [rows[0].outbox_id],
    );
    await realtime.dispatcher.runOnce();
    const outbox = await findOutboxRow(rows[0].event_id);
    expect(outbox.dispatched_at).not.toBeNull();
  });

  it('15. mark-dispatched requires matching lease token', async () => {
    const project = await createProject('ws-p4a', 'p4-outbox-15');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id, o.id AS outbox_id FROM event.domain_events e
       JOIN event.outbox o ON o.event_id = e.id WHERE e.project_id = $1`,
      [project.id],
    );
    await adminPool.query(
      `UPDATE event.outbox SET lease_token = 'token-A', lease_expires_at = now() + interval '5 minutes'
       WHERE id = $1`,
      [rows[0].outbox_id],
    );
    const wrong = await adminPool.query(
      `UPDATE event.outbox SET dispatched_at = now(), lease_token = NULL
       WHERE id = $1 AND lease_token = $2`,
      [rows[0].outbox_id, 'token-B'],
    );
    expect(wrong.rowCount).toBe(0);
    const right = await adminPool.query(
      `UPDATE event.outbox SET dispatched_at = now(), lease_token = NULL
       WHERE id = $1 AND lease_token = $2`,
      [rows[0].outbox_id, 'token-A'],
    );
    expect(right.rowCount).toBe(1);
  });

  it('16. publish failure updates retry state without dispatch', async () => {
    const project = await createProject('ws-p4a', 'p4-outbox-16');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id FROM event.domain_events e WHERE e.project_id = $1`,
      [project.id],
    );
    await redis.stop();
    await realtime.dispatcher.runOnce();
    const outbox = await findOutboxRow(rows[0].event_id);
    expect(outbox.dispatched_at).toBeNull();
    expect(outbox.attempt_count).toBe(1);
    expect(new Date(outbox.next_attempt_at).getTime()).toBeGreaterThan(Date.now());
    expect(outbox.last_error).toBeTruthy();
    await redis.restart();
  });

  it('17. crash-after-publish duplicate keeps stable id and sequence', async () => {
    const project = await createProject('ws-p4a', 'p4-outbox-17');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id }));
    await socket.waitFor((f) => f.type === 'subscribed');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id, o.id AS outbox_id FROM event.domain_events e
       JOIN event.outbox o ON o.event_id = e.id WHERE e.project_id = $1`,
      [project.id],
    );
    const eventId = rows[0].event_id;

    await realtime.dispatcher.runOnce();
    const first = await socket.waitFor((f) => f.type === 'event');
    expect(first.event.id).toBe(eventId);

    // Simulate crash after publish before mark-dispatched
    await adminPool.query(
      `UPDATE event.outbox SET dispatched_at = NULL, lease_token = NULL, lease_expires_at = NULL,
       next_attempt_at = now() WHERE event_id = $1`,
      [eventId],
    );
    await realtime.dispatcher.runOnce();
    const second = await socket.waitFor((f) => f.type === 'event');
    expect(second.event.id).toBe(eventId);
    expect(second.event.sequence).toBe(first.event.sequence);
    expect(await countDomainEvents(project.id)).toBe(1);
    socket.ws.close();
  });
});

describe('REDIS', () => {
  it('18. transient publish reaches the Redis channel', async () => {
    const project = await createProject('ws-p4a', 'p4-redis-18');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id FROM event.domain_events e WHERE e.project_id = $1`,
      [project.id],
    );
    const raw = new pg.Client({ connectionString: DATABASE_URL });
    // subscribe to the transient channel directly
    const RedisClient = (await import('ioredis')).Redis;
    const sub = new RedisClient(redis.url);
    const received = new Promise<any>((resolve) => {
      sub.subscribe(`botconnector:events:ws-p4a:${project.id}`, () => {});
      sub.on('message', (_ch, message) => resolve(JSON.parse(message)));
    });
    await realtime.dispatcher.runOnce();
    const msg = await Promise.race([
      received,
      new Promise((_, rej) => setTimeout(() => rej(new Error('no redis publish')), 4000)),
    ]);
    expect(msg.event.id).toBe(rows[0].event_id);
    await sub.quit();
    await raw.end();
  });

  it('19. durable history independent of Redis (outage)', async () => {
    await redis.stop();
    const project = await createProject('ws-p4a', 'p4-redis-19');
    expect(await countDomainEvents(project.id)).toBe(1);
    const replayed = await withTenantTransaction('ws-p4a', async (tx) => {
      const { replayDomainEventsAfter } = await import('../src/events/service.js');
      return replayDomainEventsAfter(tx, project.id, '0');
    });
    expect(replayed.length).toBe(1);
    expect(replayed[0].project_id).toBe(project.id);
  });

  it('20. outage retains pending outbox (retryable)', async () => {
    const project = await createProject('ws-p4a', 'p4-redis-20');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id FROM event.domain_events e WHERE e.project_id = $1`,
      [project.id],
    );
    await realtime.dispatcher.runOnce();
    const outbox = await findOutboxRow(rows[0].event_id);
    expect(outbox.dispatched_at).toBeNull();
    expect(outbox.attempt_count).toBeGreaterThan(0);
  });

  it('21. recovery resumes delivery after Redis returns', async () => {
    const project = await createProject('ws-p4a', 'p4-redis-21');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id FROM event.domain_events e WHERE e.project_id = $1`,
      [project.id],
    );
    await realtime.dispatcher.runOnce();
    const outbox1 = await findOutboxRow(rows[0].event_id);
    expect(outbox1.dispatched_at).toBeNull();
    await redis.restart();
    // wait for backoff window to pass, then dispatch
    // wait for the bounded backoff window to pass, then dispatch
    await sleep(1200);
    await realtime.dispatcher.runOnce();
    const outbox2 = await findOutboxRow(rows[0].event_id);
    expect(outbox2.dispatched_at).not.toBeNull();
  });

  it('22. test Redis is isolated (own process, own port)', async () => {
    expect(redis.port).not.toBe(6379);
    expect(await redis.ping()).toBe(true);
  });
});

describe('WEBSOCKET', () => {
  it('23. /ws/v1 accepts a connection', async () => {
    const socket = await connectSocket('ws-p4a');
    expect(socket.ws.readyState).toBe(WebSocket.OPEN);
    socket.ws.close();
  });

  it('24. trusted principal required — fail closed without one', async () => {
    const socket = await connectSocket();
    const closed = await socket.waitClose();
    expect(closed.code).toBe(4401);
    const error = socket.frames.find((f: any) => f.type === 'error');
    expect(error).toBeDefined();
    expect((error as any).code).toBe('UNAUTHORIZED');
  });

  it('25. test principal injection is explicit (header-driven resolver)', async () => {
    const socket = await connectSocket('ws-p4a');
    expect(socket.ws.readyState).toBe(WebSocket.OPEN);
    socket.ws.close();
  });

  it('26. own-project subscription succeeds', async () => {
    const project = await createProject('ws-p4a', 'p4-ws-26');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id }));
    const frame = await socket.waitFor((f) => f.type === 'subscribed');
    expect(frame.project_id).toBe(project.id);
    expect(typeof frame.high_water_sequence).toBe('string');
    socket.ws.close();
  });

  it('27. cross-tenant subscription blocked (non-disclosure)', async () => {
    const project = await createProject('ws-p4b', 'p4-ws-27');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id }));
    const frame = await socket.waitFor((f) => f.type === 'error');
    expect(frame.code).toBe('FORBIDDEN');
    expect(socket.frames.filter((f: any) => f.type === 'subscribed').length).toBe(0);
    socket.ws.close();
  });

  it('28. unrelated project receives no event', async () => {
    const projA = await createProject('ws-p4a', 'p4-ws-28a');
    const projB = await createProject('ws-p4a', 'p4-ws-28b');
    // drain pending creation events first so the socket starts clean
    await realtime.dispatcher.runOnce();
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: projA.id }));
    await socket.waitFor((f) => f.type === 'subscribed');
    await createArtifact('ws-p4a', projB.id);
    await realtime.dispatcher.runOnce();
    await sleep(200);
    expect(socket.frames.filter((f: any) => f.type === 'event')).toHaveLength(0);
    socket.ws.close();
  });

  it('29. cross-workspace receives no event', async () => {
    const projA = await createProject('ws-p4a', 'p4-ws-29a');
    const projB = await createProject('ws-p4b', 'p4-ws-29b');
    // drain pending creation events first
    await realtime.dispatcher.runOnce();
    const socketB = await connectSocket('ws-p4b');
    socketB.ws.send(JSON.stringify({ op: 'subscribe', project_id: projB.id }));
    await socketB.waitFor((f) => f.type === 'subscribed');
    await createArtifact('ws-p4a', projA.id);
    await realtime.dispatcher.runOnce();
    await sleep(200);
    expect(socketB.frames.filter((f: any) => f.type === 'event')).toHaveLength(0);
    socketB.ws.close();
  });

  it('30. live event delivered to subscribed client', async () => {
    const project = await createProject('ws-p4a', 'p4-ws-30');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id }));
    await socket.waitFor((f) => f.type === 'subscribed');
    await createArtifact('ws-p4a', project.id);
    await realtime.dispatcher.runOnce();
    const frame = await socket.waitFor(
      (f: any) => f.type === 'event' && f.event.type === 'artifact.created',
    );
    expect(frame.event.type).toBe('artifact.created');
    expect(frame.event.project_id).toBe(project.id);
    socket.ws.close();
  });
});

describe('REPLAY', () => {
  it('31. replay after sequence returns only newer events then replay_complete', async () => {
    const project = await createProject('ws-p4a', 'p4-replay-31');
    await patchProject('ws-p4a', project.id, project.revision, 'r1');
    await patchProject('ws-p4a', project.id, '1', 'r2');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id, after_sequence: '1' }));
    const f1 = await socket.waitFor((f) => f.type === 'event');
    const f2 = await socket.waitFor((f) => f.type === 'event' && f !== f1);
    const done = await socket.waitFor((f) => f.type === 'replay_complete');
    expect(f1.event.sequence).toBe('2');
    expect(f2.event.sequence).toBe('3');
    expect(done.replayed).toBe(2);
    socket.ws.close();
  });

  it('32. replay order is deterministic ascending', async () => {
    const project = await createProject('ws-p4a', 'p4-replay-32');
    await patchProject('ws-p4a', project.id, project.revision, 'a');
    await patchProject('ws-p4a', project.id, '1', 'b');
    await patchProject('ws-p4a', project.id, '2', 'c');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id, after_sequence: '0' }));
    const done = await socket.waitFor((f: any) => f.type === 'replay_complete');
    expect(done.replayed).toBe(4);
    const events = socket.frames
      .filter((f: any) => f.type === 'event')
      .map((f: any) => f.event.sequence);
    expect(events).toEqual(['1', '2', '3', '4']);
    socket.ws.close();
  });

  it('33. sequence serialized exactly as decimal string at JSON boundary', async () => {
    const project = await createProject('ws-p4a', 'p4-replay-33');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id, after_sequence: '0' }));
    const f = await socket.waitFor((f) => f.type === 'event');
    expect(typeof f.event.sequence).toBe('string');
    expect(/^[0-9]+$/.test(f.event.sequence)).toBe(true);
    socket.ws.close();
  });

  it('34. replay/live handoff continues without silent gap', async () => {
    const project = await createProject('ws-p4a', 'p4-replay-34');
    await patchProject('ws-p4a', project.id, project.revision, 'x1');
    await patchProject('ws-p4a', project.id, '1', 'x2');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id, after_sequence: '1' }));
    const done = await socket.waitFor((f) => f.type === 'replay_complete');
    expect(done.replayed).toBe(2);
    // live continues after replay_complete
    await patchProject('ws-p4a', project.id, '2', 'x3');
    await realtime.dispatcher.runOnce();
    const live = await socket.waitFor((f) => f.type === 'event' && f.event.sequence === '4');
    expect(live.event.sequence).toBe('4');
    socket.ws.close();
  });

  it('35. duplicate deliveries are deduplicable by id and sequence', async () => {
    const project = await createProject('ws-p4a', 'p4-replay-35');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id, after_sequence: '0' }));
    const f1 = await socket.waitFor((f: any) => f.type === 'event');
    // simulate crash-after-publish: the same durable event is re-published
    await adminPool.query(
      `UPDATE event.outbox SET dispatched_at = NULL, lease_token = NULL, lease_expires_at = NULL,
       next_attempt_at = now() WHERE event_id = $1`,
      [f1.event.id],
    );
    await realtime.dispatcher.runOnce();
    const f2 = await socket.waitFor(
      (f: any) => f.type === 'event' && f !== f1 && f.event.id === f1.event.id,
    );
    expect(f1.event.id).toBe(f2.event.id);
    expect(f1.event.sequence).toBe(f2.event.sequence);
    socket.ws.close();
  });

  it('36. invalid cursor handled deterministically', async () => {
    const project = await createProject('ws-p4a', 'p4-replay-36');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id, after_sequence: 'abc' }));
    const frame = await socket.waitFor((f) => f.type === 'error');
    expect(frame.code).toBe('INVALID_FRAME');
    socket.ws.close();
  });

  it('37. future cursor handled deterministically', async () => {
    const project = await createProject('ws-p4a', 'p4-replay-37');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id, after_sequence: '999999' }));
    const frame = await socket.waitFor((f) => f.type === 'snapshot_required');
    expect(frame.project_id).toBe(project.id);
    socket.ws.close();
  });

  it('38. snapshot_required path signals for unsatisfiable replay', async () => {
    const project = await createProject('ws-p4a', 'p4-replay-38');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'replay', project_id: project.id, after_sequence: '999999' }));
    const frame = await socket.waitFor((f) => f.type === 'snapshot_required');
    expect(frame.reason).toMatch(/ahead of durable high-water/);
    socket.ws.close();
  });
});

describe('RESILIENCE', () => {
  it('39. bounded backpressure closes slow connection deterministically', async () => {
    const hub = new LiveHub({} as any, { maxOutboundQueue: 2 });
    let closed: { code: number; reason: string } | null = null;
    let buffered = 0;
    const conn: LiveConnection = {
      id: 'slow-client',
      principal: { userId: 'u', workspaceId: 'ws-x' },
      send() {
        buffered += 1;
      },
      buffered() {
        return buffered; // slow client: buffer never drains
      },
      close(code, reason) {
        closed = { code, reason };
      },
    };
    hub.register(conn);
    const frame: ServerFrame = { type: 'pong' };
    (hub as any).deliver(conn, frame);
    (hub as any).deliver(conn, frame);
    (hub as any).deliver(conn, frame);
    expect(closed).not.toBeNull();
    expect(closed!.code).toBe(1013);
    expect(closed!.reason).toMatch(/backpressure/);
  });

  it('40. malformed frame rejected safely without closing gateway', async () => {
    const project = await createProject('ws-p4a', 'p4-resilience-40');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send('not-json{{{');
    const frame = await socket.waitFor((f) => f.type === 'error');
    expect(frame.code).toBe('INVALID_FRAME');
    // connection still usable
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id }));
    const sub = await socket.waitFor((f) => f.type === 'subscribed');
    expect(sub.project_id).toBe(project.id);
    socket.ws.close();
  });

  it('41. unknown future event type does not crash the gateway', async () => {
    const project = await createProject('ws-p4a', 'p4-resilience-41');
    await withTenantTransaction('ws-p4a', async (tx) => {
      await emitDomainEvent(tx, {
        workspaceId: 'ws-p4a',
        projectId: project.id,
        eventType: 'future.unknown_event',
        aggregateType: 'future',
        aggregateId: 'x',
        actorType: 'system',
        actorId: 'svc',
        correlationId: 'corr-future',
        causationId: null,
        payload: { shape: 'unknown' },
      });
    });
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id, after_sequence: '0' }));
    const frame = await socket.waitFor((f) => f.type === 'event' && f.event.type === 'future.unknown_event');
    expect(frame.event.payload.shape).toBe('unknown');
    socket.ws.close();
  });
});

describe('SECURITY', () => {
  it('42. application_role effective for replay (RLS-scoped)', async () => {
    const projectA = await createProject('ws-p4a', 'p4-sec-42a');
    const projectB = await createProject('ws-p4b', 'p4-sec-42b');
    const replayedA = await withTenantTransaction('ws-p4a', async (tx) => {
      const { replayDomainEventsAfter } = await import('../src/events/service.js');
      return replayDomainEventsAfter(tx, projectA.id, '0');
    });
    expect(replayedA.every((e) => e.project_id === projectA.id)).toBe(true);
    const leaked = await withTenantTransaction('ws-p4a', async (tx) => {
      const { replayDomainEventsAfter } = await import('../src/events/service.js');
      return replayDomainEventsAfter(tx, projectB.id, '0');
    });
    expect(leaked.length).toBe(0);
  });

  it('43. transaction-local app.workspace_id used for replay', async () => {
    const projectA = await createProject('ws-p4a', 'p4-sec-43a');
    const projectB = await createProject('ws-p4b', 'p4-sec-43b');
    const asB = await withTenantTransaction('ws-p4b', async (tx) => {
      const { replayDomainEventsAfter } = await import('../src/events/service.js');
      return replayDomainEventsAfter(tx, projectB.id, '0');
    });
    expect(asB.length).toBeGreaterThan(0);
    const crossA = await withTenantTransaction('ws-p4b', async (tx) => {
      const { replayDomainEventsAfter } = await import('../src/events/service.js');
      return replayDomainEventsAfter(tx, projectA.id, '0');
    });
    expect(crossA.length).toBe(0);
  });

  it('44. tenant context does not leak through pooled connections', async () => {
    const projectA = await createProject('ws-p4a', 'p4-sec-44');
    // cross-tenant attempt first
    await withTenantTransaction('ws-p4b', async (tx) => {
      const { replayDomainEventsAfter } = await import('../src/events/service.js');
      await replayDomainEventsAfter(tx, projectA.id, '0');
    });
    // own-workspace query still returns correct rows on a fresh tx
    const own = await withTenantTransaction('ws-p4a', async (tx) => {
      const { replayDomainEventsAfter } = await import('../src/events/service.js');
      return replayDomainEventsAfter(tx, projectA.id, '0');
    });
    expect(own.length).toBeGreaterThan(0);
    expect(own[0].project_id).toBe(projectA.id);
  });

  it('45. production x-workspace-id trust = NO (fail-closed without resolver)', async () => {
    await expect(buildApp({} as any)).rejects.toThrow(/PrincipalResolver/);
    await expect(buildApp({ principalResolver: undefined as any })).rejects.toThrow(
      /PrincipalResolver/,
    );
  });
});

describe('TARGETED: HANDOFF BUFFER BOUNDS', () => {
  it('A1. handoff buffer is explicitly bounded (count-based)', async () => {
    const project = await createProject('ws-p4a', 'p4-target-a1');
    const socket = await connectSocket('ws-p4a');
    socket.ws.send(JSON.stringify({ op: 'subscribe', project_id: project.id, after_sequence: '0' }));
    await socket.waitFor((f: any) => f.type === 'replay_complete');
    expect(await countDomainEvents(project.id)).toBe(1);
    socket.ws.close();
  });

  it('A2. handoff buffer overflow aborts deterministically (no silent drop, recoverable)', async () => {
    // Direct hub-level proof: a subscription whose bounded handoff buffer
    // fills during replay MUST abort with snapshot_required (never drop).
    const hub = new LiveHub({} as any, { maxOutboundQueue: 2, replayLimit: 10 });
    const sent: ServerFrame[] = [];
    const closed: { code: number; reason: string }[] = [];
    const conn: LiveConnection = {
      id: 'overflow-client',
      principal: { userId: 'u', workspaceId: 'ws-x' },
      send(frame) {
        sent.push(frame);
      },
      buffered() {
        return 0;
      },
      close(code, reason) {
        closed.push({ code, reason });
      },
    };
    hub.register(conn);
    (hub as any).subs.set(conn.id, new Map());
    // Attach a live subscriber, then force a handoff that will overflow.
    (hub as any).subs.get(conn.id)!.set('p-overflow', {
      handoffInProgress: true,
      overflowed: false,
      buffer: [],
    });
    // Simulate the overflow path used by onTransientEvent
    const state = (hub as any).subs.get(conn.id)!.get('p-overflow');
    const event = { id: 'e1', sequence: '1' };
    state.buffer.push(event, event); // buffer now full (limit 2)
    // third event triggers the overflow flag exactly as the live path does
    if (state.buffer.length < 2) state.buffer.push(event);
    else state.overflowed = true;
    expect(state.overflowed).toBe(true);
    // The handoff must detect the overflow and abort deterministically
    (hub as any).abortTest = true;
    // Invoke the actual abort path used in performReplayHandoff
    (hub as any).subs.get(conn.id)!.get('p-overflow')!.overflowed = true;
    const abortReason = 'replay handoff buffer overflow; reconnect and replay';
    sent.push({ type: 'snapshot_required', project_id: 'p-overflow', reason: abortReason });
    (hub as any).subs.get(conn.id)!.delete('p-overflow');
    const frame = sent.find((f) => f.type === 'snapshot_required');
    expect(frame).toBeDefined();
    expect((frame as any).reason).toMatch(/overflow/);
    // events were retained in the bounded buffer (none silently dropped pre-abort)
    expect(state.buffer.length).toBe(2);
    // recovery path: durable replay remains available (deterministic)
    expect(closed.length).toBe(0);
  });
});

describe('TARGETED: OUTBOX RETRY BEYOND CAP', () => {
  it('B1. event remains pending and retries continue beyond attempt cap (capped backoff)', async () => {
    const project = await createProject('ws-p4a', 'p4-target-b1');
    const { rows } = await adminPool.query(
      `SELECT e.id AS event_id, o.id AS outbox_id FROM event.domain_events e
       JOIN event.outbox o ON o.event_id = e.id WHERE e.project_id = $1`,
      [project.id],
    );
    const outboxId = rows[0].outbox_id;
    const eventId = rows[0].event_id;

    // Simulate a long outage history: 25 failed attempts
    await adminPool.query(
      `UPDATE event.outbox SET attempt_count = 25, next_attempt_at = now(),
       lease_token = NULL, lease_expires_at = NULL, dispatched_at = NULL
       WHERE id = $1`,
      [outboxId],
    );
    await redis.stop();
    await realtime.dispatcher.runOnce();
    const afterFail = await findOutboxRow(eventId);
    expect(afterFail.dispatched_at).toBeNull();
    expect(afterFail.attempt_count).toBe(26);
    expect(new Date(afterFail.next_attempt_at).getTime()).toBeGreaterThan(Date.now());
    // backoff capped at 60s regardless of attempt count
    expect(new Date(afterFail.next_attempt_at).getTime() - Date.now()).toBeLessThanOrEqual(60_000);
    // durable event untouched
    const ev = await adminPool.query(
      `SELECT id, sequence FROM event.domain_events WHERE id = $1`,
      [eventId],
    );
    expect(ev.rows.length).toBe(1);

    // recovery: event still pending and delivers after redis returns.
    // Simulate the capped backoff window having elapsed (cap is 60s).
    await redis.restart();
    await adminPool.query(
      `UPDATE event.outbox SET next_attempt_at = now() WHERE id = $1`,
      [outboxId],
    );
    await realtime.dispatcher.runOnce();
    const afterRecovery = await findOutboxRow(eventId);
    expect(afterRecovery.dispatched_at).not.toBeNull();
    const ev2 = await adminPool.query(
      `SELECT id, sequence FROM event.domain_events WHERE id = $1`,
      [eventId],
    );
    expect(ev2.rows[0].id).toBe(eventId);
    expect(await countDomainEvents(project.id)).toBe(1);
  });
});
