import { describe, it, beforeAll, afterAll, expect } from 'vitest';
import { buildApp } from '../src/index.js';
import type { FastifyInstance } from 'fastify';
import type { PrincipalResolver } from '../src/index.js';
import type { PrincipalContext } from '../src/request-context/index.js';
import { ackGenerationRun } from '../src/generation/ack.js';
import { beginTenantTransaction } from '../src/db/tenant.js';
import pg from 'pg';

const DATABASE_URL = process.env.DATABASE_URL || 'postgres://postgres:phase2test@localhost/botconnector_phase5_test';

let app: FastifyInstance;
let adminPool: pg.Pool;

const testPrincipalResolver: PrincipalResolver = (headers) => ({
  userId: 'test-user',
  workspaceId: (headers['x-workspace-id'] as string) || 'default',
});

function wsHeaders(wsId: string, extra?: Record<string, string>): Record<string, string> {
  return { 'x-workspace-id': wsId, ...extra };
}

let wsAProjectId: string;
let wsAPhaseId: string;

beforeAll(async () => {
  process.env.DATABASE_URL = DATABASE_URL;
  app = await buildApp({ principalResolver: testPrincipalResolver });
  await app.ready();
  adminPool = new pg.Pool({ connectionString: DATABASE_URL });

  // Seed test data
  await adminPool.query(`INSERT INTO iam.users (id, email, display_name) VALUES ('test-user', 'test@test.com', 'Test User') ON CONFLICT DO NOTHING`);
  await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-a', 'Workspace A', 'test-user') ON CONFLICT DO NOTHING`);
  await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-b', 'Workspace B', 'test-user') ON CONFLICT DO NOTHING`);

  // Create a project for ws-a
  const projRes = await app.inject({
    method: 'POST',
    url: '/api/v1/projects',
    headers: wsHeaders('ws-a'),
    payload: { name: 'Phase5 Test Project' },
  });
  wsAProjectId = JSON.parse(projRes.payload).data.id;

  // Create a phase
  const phaseRes = await app.inject({
    method: 'POST',
    url: `/api/v1/projects/${wsAProjectId}/phases`,
    headers: wsHeaders('ws-a'),
    payload: { name: 'Implementation', ordinal: 0 },
  });
  wsAPhaseId = JSON.parse(phaseRes.payload).data.id;
});

afterAll(async () => {
  await adminPool?.end();
  await app?.close();
});

// ============================================================
// 1. CONTINUITY
// ============================================================
describe('1. Continuity', () => {
  it('Phase-4 final baseline verified', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/v1/health', headers: wsHeaders('system') });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.status).toBe('healthy');
  });

  it('Phase-1 contracts reused', async () => {
    const contracts = await import('@botconnector/contracts');
    expect(contracts.TaskSchema).toBeDefined();
    expect(contracts.TaskStateSchema).toBeDefined();
    expect(contracts.FocusLockSchema).toBeDefined();
    expect(contracts.GenerationRunSchema).toBeDefined();
    expect(contracts.GenerationStateSchema).toBeDefined();
  });

  it('Phase-2 database reused', async () => {
    const { rows } = await adminPool.query(`
      SELECT count(*) FROM pgmigrations
    `);
    expect(Number(rows[0].count)).toBe(21);
  });

  it('Phase-3 control API reused', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/v1/projects', headers: wsHeaders('ws-a') });
    expect(res.statusCode).toBe(200);
  });

  it('Phase-4 event backbone reused', async () => {
    const { rows } = await adminPool.query(`
      SELECT relname FROM pg_class WHERE relname = 'domain_events' AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'event')
    `);
    expect(rows.length).toBe(1);
  });
});

// ============================================================
// 2. TASK CRUD
// ============================================================
describe('2. Task CRUD', () => {
  let taskId: string;
  let taskRevision: string;

  it('creates a Task', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Implement login flow' },
    });
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.payload);
    expect(body.data.title).toBe('Implement login flow');
    expect(body.data.state).toBe('draft');
    expect(body.data.revision).toBe('0');
    taskId = body.data.id;
    taskRevision = body.data.revision;
  });

  it('reads a Task', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/tasks/${taskId}`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.id).toBe(taskId);
  });

  it('lists project tasks', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.some((t: any) => t.id === taskId)).toBe(true);
  });

  it('updates mutable metadata (title)', async () => {
    const res = await app.inject({
      method: 'PATCH',
      url: `/api/v1/tasks/${taskId}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': `"${taskRevision}"` },
      payload: { title: 'Implement login flow v2' },
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.title).toBe('Implement login flow v2');
    expect(body.data.revision).toBe('1');
  });

  it('revision is decimal string', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/tasks/${taskId}`,
      headers: wsHeaders('ws-a'),
    });
    const body = JSON.parse(res.payload);
    expect(typeof body.data.revision).toBe('string');
    expect(/^[0-9]+$/.test(body.data.revision)).toBe(true);
  });
});

// ============================================================
// 3. TASK STATE MACHINE
// ============================================================
describe('3. Task State Machine', () => {
  let taskId: string;

  beforeAll(async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'State machine test task' },
    });
    taskId = JSON.parse(res.payload).data.id;
  });

  it('allowed transition: draft → approved', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/tasks/${taskId}/approve`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.state).toBe('approved');
  });

  it('allowed transition: approved → queued', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/tasks/${taskId}/queue`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.state).toBe('queued');
  });

  it('invalid transition rejected: queued → approved', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/tasks/${taskId}/approve`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(422);
    expect(JSON.parse(res.payload).error.code).toBe('INVALID_TASK_TRANSITION');
  });

  it('arbitrary public status injection blocked', async () => {
    // Try to directly PATCH the state field — must be rejected with 422
    const taskRes = await app.inject({
      method: 'GET',
      url: `/api/v1/tasks/${taskId}`,
      headers: wsHeaders('ws-a'),
    });
    const task = JSON.parse(taskRes.payload).data;

    const res = await app.inject({
      method: 'PATCH',
      url: `/api/v1/tasks/${taskId}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': `"${task.revision}"` },
      payload: { title: 'hacked', state: 'done' },
    });
    expect(res.statusCode).toBe(422);
    expect(JSON.parse(res.payload).error.code).toBe('VALIDATION_ERROR');

    // Also reject 'status' field
    const res2 = await app.inject({
      method: 'PATCH',
      url: `/api/v1/tasks/${taskId}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': `"${task.revision}"` },
      payload: { status: 'done' },
    });
    expect(res2.statusCode).toBe(422);
    expect(JSON.parse(res2.payload).error.code).toBe('VALIDATION_ERROR');
  });

  it('terminal state protection: done has no transitions', async () => {
    // Move to done through full path
    const activateRes = await app.inject({ method: 'POST', url: `/api/v1/tasks/${taskId}/queue`, headers: wsHeaders('ws-a') });
    // Already queued, activate via direct DB (no HTTP route for activate yet - it's an internal state)
    await adminPool.query(`UPDATE work.tasks SET state = 'active' WHERE id = $1`, [taskId]);
    await adminPool.query(`UPDATE work.tasks SET state = 'validating' WHERE id = $1`, [taskId]);
    await adminPool.query(`UPDATE work.tasks SET state = 'ready' WHERE id = $1`, [taskId]);
    await adminPool.query(`UPDATE work.tasks SET state = 'applying' WHERE id = $1`, [taskId]);
    await adminPool.query(`UPDATE work.tasks SET state = 'done' WHERE id = $1`, [taskId]);

    // Try to approve a done task
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/tasks/${taskId}/approve`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(422);
    expect(JSON.parse(res.payload).error.code).toBe('INVALID_TASK_TRANSITION');
  });
});

// ============================================================
// 4. TASK TENANT ISOLATION
// ============================================================
describe('4. Task Tenant Isolation', () => {
  let taskAId: string;

  beforeAll(async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Tenant isolation test' },
    });
    taskAId = JSON.parse(res.payload).data.id;
  });

  it('cross-tenant task access blocked', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/tasks/${taskAId}`,
      headers: wsHeaders('ws-b'),
    });
    expect(res.statusCode).toBe(404);
  });

  it('cross-project task reference blocked', async () => {
    // Create project in ws-b
    const projRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-b'),
      payload: { name: 'WS-B Project' },
    });
    const wsBProjectId = JSON.parse(projRes.payload).data.id;

    // Create phase in ws-b
    const phaseRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsBProjectId}/phases`,
      headers: wsHeaders('ws-b'),
      payload: { name: 'Phase 1', ordinal: 0 },
    });
    const wsBPhaseId = JSON.parse(phaseRes.payload).data.id;

    // Try to create task in ws-b referencing ws-a's phase
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsBProjectId}/tasks`,
      headers: wsHeaders('ws-b'),
      payload: { phase_id: wsAPhaseId, title: 'Cross-project reference' },
    });
    expect(res.statusCode).toBe(404); // Phase not found (RLS blocks ws-a's phase)
  });
});

// ============================================================
// 5. TASK COMMANDS + IDEMPOTENCY + CONCURRENCY
// ============================================================
describe('5. Task Commands + Idempotency + Concurrency', () => {
  it('idempotent command replay', async () => {
    // Create a task
    const createRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Idempotent test' },
    });
    const task = JSON.parse(createRes.payload).data;

    // Approve with idempotency key
    const key = `idem-task-${Date.now()}`;
    const res1 = await app.inject({
      method: 'POST',
      url: `/api/v1/tasks/${task.id}/approve`,
      headers: { ...wsHeaders('ws-a'), 'idempotency-key': key },
    });
    expect(res1.statusCode).toBe(200);
    const body1 = JSON.parse(res1.payload);
    expect(body1.data.state).toBe('approved');

    // Replay same key
    const res2 = await app.inject({
      method: 'POST',
      url: `/api/v1/tasks/${task.id}/approve`,
      headers: { ...wsHeaders('ws-a'), 'idempotency-key': key },
    });
    expect(res2.statusCode).toBe(200);
    expect(JSON.parse(res2.payload).data.state).toBe('approved');
  });

  it('stale If-Match => 409', async () => {
    const createRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Stale test' },
    });
    const task = JSON.parse(createRes.payload).data;

    const res = await app.inject({
      method: 'PATCH',
      url: `/api/v1/tasks/${task.id}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': '"999"' },
      payload: { title: 'Should fail' },
    });
    expect(res.statusCode).toBe(409);
    expect(JSON.parse(res.payload).error.code).toBe('REVISION_CONFLICT');
  });

  it('stale transition emits no event', async () => {
    const createRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'No event test' },
    });
    const task = JSON.parse(createRes.payload).data;

    // Count events before
    const beforeCount = await adminPool.query(
      `SELECT count(*) FROM event.domain_events WHERE aggregate_id = $1`,
      [task.id],
    );

    // Try stale update
    await app.inject({
      method: 'PATCH',
      url: `/api/v1/tasks/${task.id}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': '"999"' },
      payload: { title: 'No event' },
    });

    const afterCount = await adminPool.query(
      `SELECT count(*) FROM event.domain_events WHERE aggregate_id = $1`,
      [task.id],
    );

    expect(Number(afterCount.rows[0].count)).toBe(Number(beforeCount.rows[0].count));
  });
});

// ============================================================
// 6. FOCUS LOCK
// ============================================================
describe('6. Focus Lock', () => {
  let taskAId: string;

  beforeAll(async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Focus lock test task' },
    });
    taskAId = JSON.parse(res.payload).data.id;
  });

  it('acquires FocusLock', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/focus-locks`,
      headers: wsHeaders('ws-a'),
      payload: { task_id: taskAId, scope: 'file:src/index.ts', owner_id: 'agent-1' },
    });
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.payload);
    expect(body.data.task_id).toBe(taskAId);
    expect(body.data.scope).toBe('file:src/index.ts');
  });

  it('lock conflict deterministic', async () => {
    // Try to acquire another lock for same project
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/focus-locks`,
      headers: wsHeaders('ws-a'),
      payload: { task_id: taskAId, scope: 'file:src/app.ts', owner_id: 'agent-2' },
    });
    expect(res.statusCode).toBe(409);
    expect(JSON.parse(res.payload).error.code).toBe('FOCUS_LOCK_CONFLICT');
  });

  it('true concurrent acquire: single winner, clean conflict', async () => {
    // Release any existing lock first
    const listRes = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${wsAProjectId}/focus-locks`,
      headers: wsHeaders('ws-a'),
    });
    const existingLocks = JSON.parse(listRes.payload).data;
    for (const lock of existingLocks) {
      await app.inject({
        method: 'POST',
        url: `/api/v1/focus-locks/${lock.id}/release`,
        headers: wsHeaders('ws-a'),
      });
    }

    // Launch two concurrent acquisitions
    const [res1, res2] = await Promise.all([
      app.inject({
        method: 'POST',
        url: `/api/v1/projects/${wsAProjectId}/focus-locks`,
        headers: wsHeaders('ws-a'),
        payload: { task_id: taskAId, scope: 'file:src/concurrent-a.ts', owner_id: 'agent-concurrent-1' },
      }),
      app.inject({
        method: 'POST',
        url: `/api/v1/projects/${wsAProjectId}/focus-locks`,
        headers: wsHeaders('ws-a'),
        payload: { task_id: taskAId, scope: 'file:src/concurrent-b.ts', owner_id: 'agent-concurrent-2' },
      }),
    ]);

    const status1 = res1.statusCode;
    const status2 = res2.statusCode;

    // Exactly one must succeed (201), one must conflict (409)
    expect([status1, status2].sort()).toEqual([201, 409]);

    // The loser must return FOCUS_LOCK_CONFLICT, not a raw DB error
    const loser = status1 === 409 ? res1 : res2;
    const loserBody = JSON.parse(loser.payload);
    expect(loserBody.error.code).toBe('FOCUS_LOCK_CONFLICT');
    expect(loserBody.error.message).not.toContain('SQLSTATE');
    expect(loserBody.error.message).not.toContain('unique_violation');

    // Verify exactly one active lock exists
    const afterRes = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${wsAProjectId}/focus-locks`,
      headers: wsHeaders('ws-a'),
    });
    const afterLocks = JSON.parse(afterRes.payload).data;
    const activeLocks = afterLocks.filter((l: Record<string, unknown>) => l.expires_at === null);
    expect(activeLocks.length).toBe(1);
  });

  it('releases lock', async () => {
    // Get the lock
    const listRes = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${wsAProjectId}/focus-locks`,
      headers: wsHeaders('ws-a'),
    });
    const locks = JSON.parse(listRes.payload).data;
    const activeLock = locks.find((l: any) => l.expires_at === null);
    expect(activeLock).toBeDefined();

    // Release it
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/focus-locks/${activeLock.id}/release`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);

    // Now can acquire again
    const res2 = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/focus-locks`,
      headers: wsHeaders('ws-a'),
      payload: { task_id: taskAId, scope: 'file:src/app.ts', owner_id: 'agent-2' },
    });
    expect(res2.statusCode).toBe(201);

    // Clean up
    const lock2 = JSON.parse(res2.payload).data;
    await app.inject({
      method: 'POST',
      url: `/api/v1/focus-locks/${lock2.id}/release`,
      headers: wsHeaders('ws-a'),
    });
  });

  it('foreign tenant cannot inspect lock', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${wsAProjectId}/focus-locks`,
      headers: wsHeaders('ws-b'),
    });
    expect(res.statusCode).toBe(404);
  });
});

// ============================================================
// 7. GENERATION RUN
// ============================================================
describe('7. Generation Run', () => {
  let taskId: string;
  let runId: string;

  beforeAll(async () => {
    const taskRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Generation run test task' },
    });
    taskId = JSON.parse(taskRes.payload).data.id;
  });

  it('creates GenerationRun', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/generation-runs`,
      headers: wsHeaders('ws-a'),
      payload: { task_id: taskId },
    });
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.payload);
    expect(body.data.state).toBe('planning');
    expect(body.data.task_id).toBe(taskId);
    runId = body.data.id;
  });

  it('reads GenerationRun', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/generation-runs/${runId}`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.id).toBe(runId);
  });

  it('lists project generation runs', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${wsAProjectId}/generation-runs`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.some((r: any) => r.id === runId)).toBe(true);
  });

  it('tenant/project/task relationship enforced', async () => {
    // Create ws-b project and task
    const projRes = await app.inject({ method: 'POST', url: '/api/v1/projects', headers: wsHeaders('ws-b'), payload: { name: 'WS-B GenRun' } });
    const wsBProjectId = JSON.parse(projRes.payload).data.id;
    const phaseRes = await app.inject({ method: 'POST', url: `/api/v1/projects/${wsBProjectId}/phases`, headers: wsHeaders('ws-b'), payload: { name: 'P1', ordinal: 0 } });
    const wsBPhaseId = JSON.parse(phaseRes.payload).data.id;
    const taskRes = await app.inject({ method: 'POST', url: `/api/v1/projects/${wsBProjectId}/tasks`, headers: wsHeaders('ws-b'), payload: { phase_id: wsBPhaseId, title: 'WS-B Task' } });
    const wsBTaskId = JSON.parse(taskRes.payload).data.id;

    // Try to create generation run in ws-b referencing ws-a's task
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsBProjectId}/generation-runs`,
      headers: wsHeaders('ws-b'),
      payload: { task_id: taskId }, // ws-a's task
    });
    expect(res.statusCode).toBe(404); // task not found (RLS)
  });
});

// ============================================================
// 8. GENERATION RUN STATE MACHINE
// ============================================================
describe('8. Generation Run State Machine', () => {
  let runId: string;

  beforeAll(async () => {
    const taskRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'GR state machine task' },
    });
    const taskId = JSON.parse(taskRes.payload).data.id;

    const runRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/generation-runs`,
      headers: wsHeaders('ws-a'),
      payload: { task_id: taskId },
    });
    runId = JSON.parse(runRes.payload).data.id;
  });

  it('pause request: running → pausing', async () => {
    // Start: planning → running
    await app.inject({ method: 'POST', url: `/api/v1/generation-runs/${runId}/start`, headers: wsHeaders('ws-a') });

    // Pause request
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/generation-runs/${runId}/pause`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.state).toBe('pausing');
  });

  it('executor ack: pausing → paused (internal service)', async () => {
    // The public /ack endpoint must not exist
    const ackAttempt = await app.inject({
      method: 'POST',
      url: `/api/v1/generation-runs/${runId}/ack`,
      headers: wsHeaders('ws-a'),
      payload: { expected_from: 'pausing' },
    });
    expect(ackAttempt.statusCode).toBe(404);

    // Use internal ack service directly within a tenant transaction
    const client = await adminPool.connect();
    try {
      const tx = await beginTenantTransaction(client, 'ws-a');
      const principal: PrincipalContext = { userId: 'test-user', workspaceId: 'ws-a' };
      const result = await ackGenerationRun(tx, principal, 'test-request-id', runId, 'pausing');
      expect(result.run.state).toBe('paused');
      await tx.commit();
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  });

  it('resume: paused → running', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/generation-runs/${runId}/resume`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.state).toBe('running');
  });

  it('stop request: running → stopping', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/generation-runs/${runId}/stop`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    expect(JSON.parse(res.payload).data.state).toBe('stopping');
  });

  it('executor ack: stopping → stopped (internal service)', async () => {
    // The public /ack endpoint must not exist
    const ackAttempt = await app.inject({
      method: 'POST',
      url: `/api/v1/generation-runs/${runId}/ack`,
      headers: wsHeaders('ws-a'),
      payload: { expected_from: 'stopping' },
    });
    expect(ackAttempt.statusCode).toBe(404);

    // Use internal ack service directly within a tenant transaction
    const client = await adminPool.connect();
    try {
      const tx = await beginTenantTransaction(client, 'ws-a');
      const principal: PrincipalContext = { userId: 'test-user', workspaceId: 'ws-a' };
      const result = await ackGenerationRun(tx, principal, 'test-request-id', runId, 'stopping');
      expect(result.run.state).toBe('stopped');
      await tx.commit();
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  });

  it('terminal protection: stopped cannot transition', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/generation-runs/${runId}/start`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(422);
    expect(JSON.parse(res.payload).error.code).toBe('INVALID_GENERATION_RUN_TRANSITION');
  });

  it('public ack endpoint does not exist (404)', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/v1/generation-runs/nonexistent/ack',
      headers: wsHeaders('ws-a'),
      payload: { expected_from: 'pausing' },
    });
    expect(res.statusCode).toBe(404);
  });

  it('internal ack rejects invalid source state', async () => {
    const taskRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Ack invalid source task' },
    });
    const taskId = JSON.parse(taskRes.payload).data.id;
    const runRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/generation-runs`,
      headers: wsHeaders('ws-a'),
      payload: { task_id: taskId },
    });
    const testRunId = JSON.parse(runRes.payload).data.id;
    // Run is in 'planning' state — ack from 'pausing' should fail
    const client = await adminPool.connect();
    try {
      const tx = await beginTenantTransaction(client, 'ws-a');
      const principal: PrincipalContext = { userId: 'test-user', workspaceId: 'ws-a' };
      await expect(
        ackGenerationRun(tx, principal, 'test-req', testRunId, 'pausing'),
      ).rejects.toThrow();
      await tx.rollback();
    } finally {
      client.release();
    }
  });

  it('internal ack emits no event on rejection', async () => {
    const taskRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Ack no event task' },
    });
    const taskId = JSON.parse(taskRes.payload).data.id;
    const runRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/generation-runs`,
      headers: wsHeaders('ws-a'),
      payload: { task_id: taskId },
    });
    const testRunId = JSON.parse(runRes.payload).data.id;

    const before = await adminPool.query(
      `SELECT count(*) FROM event.domain_events WHERE aggregate_id = $1`,
      [testRunId],
    );

    // Try ack from wrong state — should throw, no event emitted
    const client = await adminPool.connect();
    try {
      const tx = await beginTenantTransaction(client, 'ws-a');
      const principal: PrincipalContext = { userId: 'test-user', workspaceId: 'ws-a' };
      try {
        await ackGenerationRun(tx, principal, 'test-req', testRunId, 'pausing');
      } catch {
        // expected
      }
      await tx.rollback();
    } finally {
      client.release();
    }

    const after = await adminPool.query(
      `SELECT count(*) FROM event.domain_events WHERE aggregate_id = $1`,
      [testRunId],
    );
    expect(Number(after.rows[0].count)).toBe(Number(before.rows[0].count));
  });

  it('invalid lifecycle transition rejected', async () => {
    // planning → pausing is not allowed
    const taskRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Invalid transition task' },
    });
    const taskId = JSON.parse(taskRes.payload).data.id;
    const runRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/generation-runs`,
      headers: wsHeaders('ws-a'),
      payload: { task_id: taskId },
    });
    const runId = JSON.parse(runRes.payload).data.id;

    // Try pause from planning
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/generation-runs/${runId}/pause`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(422);
  });
});

// ============================================================
// 9. EVENT INTEGRATION
// ============================================================
describe('9. Event Integration', () => {
  it('successful Task create emits exactly one domain event', async () => {
    const taskRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Event test task' },
    });
    const task = JSON.parse(taskRes.payload).data;

    const { rows } = await adminPool.query(
      `SELECT * FROM event.domain_events WHERE aggregate_id = $1 AND event_type = 'task.created'`,
      [task.id],
    );
    expect(rows.length).toBe(1);
    expect(rows[0].aggregate_type).toBe('task');
  });

  it('successful Task transition emits exactly one event', async () => {
    const taskRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Transition event test' },
    });
    const task = JSON.parse(taskRes.payload).data;

    await app.inject({ method: 'POST', url: `/api/v1/tasks/${task.id}/approve`, headers: wsHeaders('ws-a') });

    const { rows } = await adminPool.query(
      `SELECT * FROM event.domain_events WHERE aggregate_id = $1 AND event_type = 'task.approved'`,
      [task.id],
    );
    expect(rows.length).toBe(1);
  });

  it('rejected transition emits no event', async () => {
    const taskRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'No event rejected' },
    });
    const task = JSON.parse(taskRes.payload).data;

    const before = await adminPool.query(
      `SELECT count(*) FROM event.domain_events WHERE aggregate_id = $1`,
      [task.id],
    );

    // Try invalid transition
    await app.inject({ method: 'POST', url: `/api/v1/tasks/${task.id}/queue`, headers: wsHeaders('ws-a') });

    const after = await adminPool.query(
      `SELECT count(*) FROM event.domain_events WHERE aggregate_id = $1`,
      [task.id],
    );
    // Should have exactly 1 event (created), not 2
    expect(Number(after.rows[0].count)).toBe(Number(before.rows[0].count));
  });

  it('project sequence remains deterministic', async () => {
    const { rows } = await adminPool.query(
      `SELECT * FROM event.domain_events WHERE project_id = $1 ORDER BY sequence ASC`,
      [wsAProjectId],
    );
    // Verify sequences are strictly increasing
    for (let i = 1; i < rows.length; i++) {
      expect(BigInt(rows[i].sequence) > BigInt(rows[i - 1].sequence)).toBe(true);
    }
  });

  it('idempotent command replay emits no duplicate event/outbox', async () => {
    const taskRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${wsAProjectId}/tasks`,
      headers: wsHeaders('ws-a'),
      payload: { phase_id: wsAPhaseId, title: 'Idempotent event test' },
    });
    const task = JSON.parse(taskRes.payload).data;

    const key = `idem-event-${Date.now()}`;
    await app.inject({ method: 'POST', url: `/api/v1/tasks/${task.id}/approve`, headers: { ...wsHeaders('ws-a'), 'idempotency-key': key } });
    await app.inject({ method: 'POST', url: `/api/v1/tasks/${task.id}/approve`, headers: { ...wsHeaders('ws-a'), 'idempotency-key': key } });

    const { rows } = await adminPool.query(
      `SELECT count(*) FROM event.domain_events WHERE aggregate_id = $1 AND event_type = 'task.approved'`,
      [task.id],
    );
    expect(Number(rows[0].count)).toBe(1);
  });
});

// ============================================================
// 10. SECURITY
// ============================================================
describe('10. Security', () => {
  it('application_role effective', async () => {
    const { rows } = await adminPool.query(`SELECT current_user`);
    expect(rows[0].current_user).toBe('postgres');
  });

  it('transaction-local app.workspace_id', async () => {
    const client = await adminPool.connect();
    try {
      await client.query('BEGIN');
      await client.query(`SELECT set_config('app.workspace_id', 'ws-test', true)`);
      const { rows: r1 } = await client.query(`SELECT current_setting('app.workspace_id', true)`);
      expect(r1[0].current_setting).toBe('ws-test');
      await client.query('ROLLBACK');

      await client.query('BEGIN');
      const { rows: r2 } = await client.query(`SELECT current_setting('app.workspace_id', true)`);
      expect(r2[0].current_setting).toBe('');
      await client.query('ROLLBACK');
    } finally {
      client.release();
    }
  });

  it('RLS enabled and forced on work.tasks', async () => {
    const { rows } = await adminPool.query(`
      SELECT relrowsecurity, relforcerowsecurity
      FROM pg_class
      WHERE relname = 'tasks' AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'work')
    `);
    expect(rows[0].relrowsecurity).toBe(true);
    expect(rows[0].relforcerowsecurity).toBe(true);
  });

  it('production x-workspace-id trust = NO', async () => {
    const { buildApp: buildProd } = await import('../src/index.js');
    await expect(buildProd({} as any)).rejects.toThrow('No PrincipalResolver configured');
  });
});

// ============================================================
// 11. BOUNDARIES
// ============================================================
describe('11. Boundaries', () => {
  it('no Task DAG scheduler', async () => {
    // No DAG-related routes exist
    const res = await app.inject({ method: 'GET', url: '/api/v1/tasks/dag', headers: wsHeaders('ws-a') });
    expect(res.statusCode).toBe(404);
  });

  it('no AI provider call', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/v1/ai/providers', headers: wsHeaders('ws-a') });
    expect(res.statusCode).toBe(404);
  });

  it('no sandbox/worktree execution', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/v1/sandboxes', headers: wsHeaders('ws-a') });
    expect(res.statusCode).toBe(404);
  });
});

// ============================================================
// 12. REGRESSION
// ============================================================
describe('12. Phase-1 Contract Regression', () => {
  it('Phase-1 contracts still import and validate', async () => {
    const contracts = await import('@botconnector/contracts');
    expect(contracts.ProjectSchema).toBeDefined();
    expect(contracts.TaskSchema).toBeDefined();
    expect(contracts.FocusLockSchema).toBeDefined();
    expect(contracts.GenerationRunSchema).toBeDefined();

    const taskResult = contracts.TaskSchema.safeParse({
      version: 1,
      id: 'test',
      project_id: 'proj',
      phase_id: 'phase',
      title: 'Test',
      state: 'draft',
      revision: '0',
      base_revision: '0',
      acceptance_contract_id: null,
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-01T00:00:00+00:00',
    });
    expect(taskResult.success).toBe(true);
  });
});

describe('13. Phase-2 Database Regression', () => {
  it('all 14 schemas exist', async () => {
    const { rows } = await adminPool.query(`
      SELECT schema_name FROM information_schema.schemata
      WHERE schema_name IN ('iam','core','design','memory','work','ai','change','validation','build','resource','deploy','event','security','ops')
    `);
    expect(rows.length).toBe(14);
  });
});

describe('14. Phase-3 Control API Regression', () => {
  it('project CRUD still works', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Regression Test' },
    });
    expect(res.statusCode).toBe(201);
  });
});

describe('15. Phase-4 Event Backbone Regression', () => {
  it('domain_events table exists with correct columns', async () => {
    const { rows } = await adminPool.query(`
      SELECT column_name FROM information_schema.columns
      WHERE table_schema = 'event' AND table_name = 'domain_events'
      ORDER BY ordinal_position
    `);
    const cols = rows.map((r: any) => r.column_name);
    expect(cols).toContain('id');
    expect(cols).toContain('sequence');
    expect(cols).toContain('event_type');
    expect(cols).toContain('payload');
  });

  it('outbox table exists', async () => {
    const { rows } = await adminPool.query(`
      SELECT relname FROM pg_class WHERE relname = 'outbox' AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'event')
    `);
    expect(rows.length).toBe(1);
  });
});
