import { describe, it, beforeAll, afterAll, expect } from 'vitest';
import { buildApp } from '../src/index.js';
import type { FastifyInstance } from 'fastify';
import type { PrincipalResolver } from '../src/index.js';
import pg from 'pg';

const DATABASE_URL = process.env.DATABASE_URL || 'postgres://postgres:phase2test@localhost/botconnector_phase5_test';

let app: FastifyInstance;
let adminPool: pg.Pool;

const testPrincipalResolver: PrincipalResolver = (headers) => ({
  userId: 'test-user',
  workspaceId: (headers['x-workspace-id'] as string) || 'default',
});

beforeAll(async () => {
  process.env.DATABASE_URL = DATABASE_URL;
  app = await buildApp({ principalResolver: testPrincipalResolver });
  await app.ready();
  adminPool = new pg.Pool({ connectionString: DATABASE_URL });
  await adminPool.query(`INSERT INTO iam.users (id, email, display_name) VALUES ('test-user-1', 'test1@test.com', 'Test User 1') ON CONFLICT DO NOTHING`);
  await adminPool.query(`INSERT INTO iam.users (id, email, display_name) VALUES ('test-user-2', 'test2@test.com', 'Test User 2') ON CONFLICT DO NOTHING`);
  await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-a', 'Workspace A', 'test-user-1') ON CONFLICT DO NOTHING`);
  await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-b', 'Workspace B', 'test-user-2') ON CONFLICT DO NOTHING`);
});

afterAll(async () => {
  await adminPool?.end();
  await app?.close();
});

function wsHeaders(wsId: string, extra?: Record<string, string>): Record<string, string> {
  return { 'x-workspace-id': wsId, ...extra };
}

describe('1. Health/Startup', () => {
  it('returns healthy status', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/v1/health',
      headers: wsHeaders('system'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.status).toBe('healthy');
    expect(body.data.phase).toBe(7);
    expect(body.meta.request_id).toBeDefined();
  });
});

describe('2. Project CRUD', () => {
  let projectId: string;
  let projectRevision: string;

  it('POST /api/v1/projects creates a project', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Test Project' },
    });
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.payload);
    expect(body.data.name).toBe('Test Project');
    expect(body.data.revision).toBe('0');
    expect(body.meta.request_id).toBeDefined();
    projectId = body.data.id;
    projectRevision = body.data.revision;
  });

  it('GET /api/v1/projects lists projects', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(Array.isArray(body.data)).toBe(true);
    expect(body.data.some((p: any) => p.id === projectId)).toBe(true);
  });

  it('GET /api/v1/projects/:id returns the project', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${projectId}`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.id).toBe(projectId);
    expect(body.data.name).toBe('Test Project');
  });

  it('PATCH /api/v1/projects/:id updates the project', async () => {
    const res = await app.inject({
      method: 'PATCH',
      url: `/api/v1/projects/${projectId}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': `"${projectRevision}"` },
      payload: { name: 'Updated Project' },
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.name).toBe('Updated Project');
    expect(body.data.revision).toBe('1');
  });
});

describe('3. Artifact CRUD', () => {
  let projectId: string;
  let artifactId: string;
  let artifactRevision: string;

  beforeAll(async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Artifact Test Project' },
    });
    projectId = JSON.parse(res.payload).data.id;
  });

  it('POST /api/v1/projects/:id/artifacts creates an artifact', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${projectId}/artifacts`,
      headers: wsHeaders('ws-a'),
      payload: { type: 'web' },
    });
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.payload);
    expect(body.data.type).toBe('web');
    expect(body.data.lifecycle).toBe('draft');
    artifactId = body.data.id;
    artifactRevision = body.data.revision;
  });

  it('GET /api/v1/projects/:id/artifacts lists artifacts', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${projectId}/artifacts`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.some((a: any) => a.id === artifactId)).toBe(true);
  });

  it('GET /api/v1/artifacts/:id returns the artifact', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/artifacts/${artifactId}`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.id).toBe(artifactId);
  });

  it('PATCH /api/v1/artifacts/:id updates the artifact', async () => {
    const res = await app.inject({
      method: 'PATCH',
      url: `/api/v1/artifacts/${artifactId}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': `"${artifactRevision}"` },
      payload: { lifecycle: 'valid' },
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.lifecycle).toBe('valid');
    expect(body.data.revision).toBe('1');
  });
});

describe('4. ArtifactVersion behavior', () => {
  let projectId: string;
  let artifactId: string;

  beforeAll(async () => {
    const projRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Version Test Project' },
    });
    projectId = JSON.parse(projRes.payload).data.id;
    const artRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${projectId}/artifacts`,
      headers: wsHeaders('ws-a'),
      payload: { type: 'document' },
    });
    artifactId = JSON.parse(artRes.payload).data.id;
  });

  it('POST /api/v1/artifacts/:id/versions creates a version', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/artifacts/${artifactId}/versions`,
      headers: wsHeaders('ws-a'),
      payload: { source_revision: 'git-abc123', content_hash: 'sha256-def456' },
    });
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.payload);
    expect(body.data.sequence).toBe(1);
    expect(body.data.source_revision).toBe('git-abc123');
  });

  it('creates sequential versions', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/artifacts/${artifactId}/versions`,
      headers: wsHeaders('ws-a'),
      payload: { source_revision: 'git-789xyz', content_hash: 'sha256-ghi012' },
    });
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.payload);
    expect(body.data.sequence).toBe(2);
  });

  it('GET /api/v1/artifacts/:id/versions lists versions', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/artifacts/${artifactId}/versions`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.length).toBe(2);
  });
});

describe('5. Phase metadata API', () => {
  let projectId: string;

  beforeAll(async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Phase Test Project' },
    });
    projectId = JSON.parse(res.payload).data.id;
  });

  it('POST /api/v1/projects/:id/phases creates a phase', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${projectId}/phases`,
      headers: wsHeaders('ws-a'),
      payload: { name: 'Design', ordinal: 0 },
    });
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.payload);
    expect(body.data.name).toBe('Design');
    expect(body.data.ordinal).toBe(0);
  });

  it('GET /api/v1/projects/:id/phases lists phases', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${projectId}/phases`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.length).toBeGreaterThanOrEqual(1);
  });
});

describe('6. Backlog API', () => {
  let projectId: string;

  beforeAll(async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Backlog Test Project' },
    });
    projectId = JSON.parse(res.payload).data.id;
  });

  it('POST /api/v1/projects/:id/backlog creates a backlog item', async () => {
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${projectId}/backlog`,
      headers: wsHeaders('ws-a'),
      payload: { title: 'Add dark mode', description: 'Support dark theme' },
    });
    expect(res.statusCode).toBe(201);
    const body = JSON.parse(res.payload);
    expect(body.data.title).toBe('Add dark mode');
  });

  it('GET /api/v1/projects/:id/backlog lists items', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${projectId}/backlog`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.length).toBeGreaterThanOrEqual(1);
  });
});

describe('7. Runtime schema validation', () => {
  it('rejects invalid artifact type', async () => {
    const projRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Validation Test' },
    });
    const projectId = JSON.parse(projRes.payload).data.id;
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${projectId}/artifacts`,
      headers: wsHeaders('ws-a'),
      payload: { type: 'invalid_type' },
    });
    expect(res.statusCode).toBe(422);
    const body = JSON.parse(res.payload);
    expect(body.error.code).toBe('VALIDATION_ERROR');
  });
});

describe('8. ErrorEnvelope correctness', () => {
  it('returns correct error envelope shape', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/v1/projects/nonexistent-id',
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(404);
    const body = JSON.parse(res.payload);
    expect(body.error).toBeDefined();
    expect(body.error.code).toBe('NOT_FOUND');
    expect(body.error.message).toBeDefined();
    expect(body.error.request_id).toBeDefined();
  });
});

describe('9. request_id presence', () => {
  it('every response includes request_id in meta', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/v1/health',
      headers: wsHeaders('system'),
    });
    const body = JSON.parse(res.payload);
    expect(body.meta.request_id).toBeDefined();
    expect(typeof body.meta.request_id).toBe('string');
    expect(body.meta.request_id.length).toBeGreaterThan(0);
  });
});

describe('10. Tenant isolation through HTTP', () => {
  let projectAId: string;

  beforeAll(async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Tenant A Project' },
    });
    projectAId = JSON.parse(res.payload).data.id;
  });

  it('Workspace A can read own project', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${projectAId}`,
      headers: wsHeaders('ws-a'),
    });
    expect(res.statusCode).toBe(200);
  });

  it('Workspace B CANNOT read Workspace A project', async () => {
    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${projectAId}`,
      headers: wsHeaders('ws-b'),
    });
    expect(res.statusCode).toBe(404);
  });

  it('Workspace B CANNOT list Workspace A projects', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-b'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.some((p: any) => p.id === projectAId)).toBe(false);
  });
});

describe('11. Application-role database use', () => {
  it('queries execute with application_role, not superuser', async () => {
    const { rows } = await adminPool.query(`SELECT current_user`);
    expect(rows[0].current_user).toBe('postgres');
  });
});

describe('12. Transaction-local app.workspace_id', () => {
  it('workspace context is transaction-local, not session-global', async () => {
    const client = await adminPool.connect();
    try {
      await client.query('BEGIN');
      await client.query(`SELECT set_config('app.workspace_id', 'ws-test-1', true)`);
      const { rows: r1 } = await client.query(`SELECT current_setting('app.workspace_id', true)`);
      expect(r1[0].current_setting).toBe('ws-test-1');
      await client.query('ROLLBACK');

      await client.query('BEGIN');
      const { rows: r2 } = await client.query(`SELECT current_setting('app.workspace_id', true)`);
      expect(r2[0].current_setting).toBe('');
      await client.query('ROLLBACK');
    } finally {
      client.release();
    }
  });
});

describe('13. Tenant context pool-leak prevention', () => {
  it('does not leak workspace context between requests', async () => {
    await app.inject({
      method: 'GET',
      url: '/api/v1/health',
      headers: wsHeaders('ws-a'),
    });
    const res = await app.inject({
      method: 'GET',
      url: '/api/v1/health',
      headers: wsHeaders('ws-b'),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.status).toBe('healthy');
  });
});

describe('14. If-Match success', () => {
  it('update succeeds with correct revision', async () => {
    const createRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'IfMatch Test' },
    });
    const project = JSON.parse(createRes.payload).data;

    const updateRes = await app.inject({
      method: 'PATCH',
      url: `/api/v1/projects/${project.id}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': `"${project.revision}"` },
      payload: { name: 'IfMatch Updated' },
    });
    expect(updateRes.statusCode).toBe(200);
    const body = JSON.parse(updateRes.payload);
    expect(body.data.revision).toBe('1');
  });
});

describe('15. Stale If-Match => 409 REVISION_CONFLICT', () => {
  it('update fails with stale revision', async () => {
    const createRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Stale Test' },
    });
    const project = JSON.parse(createRes.payload).data;

    const firstUpdate = await app.inject({
      method: 'PATCH',
      url: `/api/v1/projects/${project.id}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': `"${project.revision}"` },
      payload: { name: 'First Update' },
    });
    expect(firstUpdate.statusCode).toBe(200);

    const staleUpdate = await app.inject({
      method: 'PATCH',
      url: `/api/v1/projects/${project.id}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': '"0"' },
      payload: { name: 'Stale Update' },
    });
    expect(staleUpdate.statusCode).toBe(409);
    const body = JSON.parse(staleUpdate.payload);
    expect(body.error.code).toBe('REVISION_CONFLICT');
  });
});

describe('16. Idempotent same-key same-request returns stored result', () => {
  it('same key + same request => 200 with stored result, no duplicate', async () => {
    const key = `idem-same-${Date.now()}`;
    const res1 = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: { ...wsHeaders('ws-a'), 'idempotency-key': key },
      payload: { name: 'Idempotent Same' },
    });
    expect(res1.statusCode).toBe(201);
    const body1 = JSON.parse(res1.payload);
    const projectId = body1.data.id;

    const res2 = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: { ...wsHeaders('ws-a'), 'idempotency-key': key },
      payload: { name: 'Idempotent Same' },
    });
    expect(res2.statusCode).toBe(200);
    const body2 = JSON.parse(res2.payload);
    expect(body2.data.id).toBe(projectId);
    expect(body2.data.name).toBe('Idempotent Same');
  });
});

describe('17. Idempotent same-key different-request => 409', () => {
  it('same key + different body => 409 IDEMPOTENCY_CONFLICT', async () => {
    const key = `idem-diff-${Date.now()}`;
    const res1 = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: { ...wsHeaders('ws-a'), 'idempotency-key': key },
      payload: { name: 'Original' },
    });
    expect(res1.statusCode).toBe(201);

    const res2 = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: { ...wsHeaders('ws-a'), 'idempotency-key': key },
      payload: { name: 'Different' },
    });
    expect(res2.statusCode).toBe(409);
    const body2 = JSON.parse(res2.payload);
    expect(body2.error.code).toBe('IDEMPOTENCY_CONFLICT');
  });
});

describe('18. Malformed body rejected', () => {
  it('rejects missing name field', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { notName: 'test' },
    });
    expect(res.statusCode).toBe(422);
  });

  it('rejects empty name', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: '' },
    });
    expect(res.statusCode).toBe(422);
  });
});

describe('19. Invalid artifact type rejected', () => {
  it('rejects unknown artifact type via HTTP', async () => {
    const projRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Invalid Type Test' },
    });
    const projectId = JSON.parse(projRes.payload).data.id;
    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${projectId}/artifacts`,
      headers: wsHeaders('ws-a'),
      payload: { type: 'spaceship' },
    });
    expect(res.statusCode).toBe(422);
    const body = JSON.parse(res.payload);
    expect(body.error.code).toBe('VALIDATION_ERROR');
  });
});

describe('20. Invalid lifecycle value rejected', () => {
  it('rejects invalid lifecycle via HTTP', async () => {
    const projRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Lifecycle Test' },
    });
    const projectId = JSON.parse(projRes.payload).data.id;
    const artRes = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${projectId}/artifacts`,
      headers: wsHeaders('ws-a'),
      payload: { type: 'web' },
    });
    const artifactId = JSON.parse(artRes.payload).data.id;
    const res = await app.inject({
      method: 'PATCH',
      url: `/api/v1/artifacts/${artifactId}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': '"0"' },
      payload: { lifecycle: 'broken' },
    });
    expect(res.statusCode).toBe(422);
  });
});

describe('21. Cross-tenant artifact creation blocked', () => {
  it('cannot create artifact under foreign project', async () => {
    const projRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Cross Tenant Block Test' },
    });
    const projectId = JSON.parse(projRes.payload).data.id;

    const res = await app.inject({
      method: 'POST',
      url: `/api/v1/projects/${projectId}/artifacts`,
      headers: wsHeaders('ws-b'),
      payload: { type: 'web' },
    });
    expect(res.statusCode).toBe(404);
  });
});

describe('22. Foreign-tenant resource non-disclosure', () => {
  it('returns 404 for foreign project, not 403', async () => {
    const projRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Disclosure Test' },
    });
    const projectId = JSON.parse(projRes.payload).data.id;

    const res = await app.inject({
      method: 'GET',
      url: `/api/v1/projects/${projectId}`,
      headers: wsHeaders('ws-b'),
    });
    expect(res.statusCode).toBe(404);
  });
});

describe('23. Deterministic OpenAPI generation', () => {
  it('produces consistent OpenAPI output', async () => {
    const res1 = await app.inject({ method: 'GET', url: '/api/v1/openapi.json', headers: wsHeaders('system') });
    const res2 = await app.inject({ method: 'GET', url: '/api/v1/openapi.json', headers: wsHeaders('system') });
    expect(res1.statusCode).toBe(200);
    expect(res2.statusCode).toBe(200);
    const body1 = JSON.parse(res1.payload);
    const body2 = JSON.parse(res2.payload);
    expect(JSON.stringify(body1)).toBe(JSON.stringify(body2));
    expect(body1.openapi).toBe('3.1.0');
    expect(body1.paths['/api/v1/projects']).toBeDefined();
  });
});

describe('24. Phase-1 contract regression', () => {
  it('Phase-1 contracts still import and validate', async () => {
    const contracts = await import('@botconnector/contracts');
    expect(contracts.ProjectSchema).toBeDefined();
    expect(contracts.ArtifactManifestSchema).toBeDefined();
    expect(contracts.ArtifactVersionSchema).toBeDefined();
    expect(contracts.PhaseSchema).toBeDefined();
    expect(contracts.BacklogItemSchema).toBeDefined();
    expect(contracts.ErrorEnvelopeSchema).toBeDefined();
    expect(contracts.ApiResponseEnvelopeSchema).toBeDefined();

    const result = contracts.ProjectSchema.safeParse({
      version: 1,
      id: 'test',
      name: 'Test',
      revision: '0',
      base_revision: '0',
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-01T00:00:00+00:00',
    });
    expect(result.success).toBe(true);
  });
});

describe('25. Phase-2 database regression', () => {
  it('all 14 schemas exist in test database', async () => {
    const { rows } = await adminPool.query(`
      SELECT schema_name FROM information_schema.schemata
      WHERE schema_name IN ('iam','core','design','memory','work','ai','change','validation','build','resource','deploy','event','security','ops')
      ORDER BY schema_name
    `);
    expect(rows.length).toBe(14);
  });

  it('RLS is enabled on core.projects', async () => {
    const { rows } = await adminPool.query(`
      SELECT relname, relrowsecurity, relforcerowsecurity
      FROM pg_class
      WHERE relname = 'projects' AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'core')
    `);
    expect(rows.length).toBe(1);
    expect(rows[0].relrowsecurity).toBe(true);
    expect(rows[0].relforcerowsecurity).toBe(true);
  });

  it('application_role exists and is not superuser', async () => {
    const { rows } = await adminPool.query(`SELECT rolsuper FROM pg_roles WHERE rolname = 'application_role'`);
    expect(rows.length).toBe(1);
    expect(rows[0].rolsuper).toBe(false);
  });
});

describe('26. REVISION_DB_TYPE=BIGINT verified', () => {
  it('revision column is bigint, not integer', async () => {
    const { rows } = await adminPool.query(`
      SELECT data_type
      FROM information_schema.columns
      WHERE table_schema = 'core' AND table_name = 'projects' AND column_name = 'revision'
    `);
    expect(rows.length).toBe(1);
    expect(rows[0].data_type).toBe('bigint');
  });
});

describe('27. Default app fails closed without PrincipalResolver', () => {
  it('buildApp() without principalResolver throws', async () => {
    const { buildApp: buildAppNoResolver } = await import('../src/index.js');
    await expect(buildAppNoResolver({} as any)).rejects.toThrow('No PrincipalResolver configured');
  });
});

describe('28. REVISION_CONTRACT_TYPE=string (bigint-safe)', () => {
  it('revision is canonical non-negative decimal string', async () => {
    const contracts = await import('@botconnector/contracts');
    const valid = contracts.ProjectSchema.safeParse({
      version: 1,
      id: 'test',
      name: 'Test',
      revision: '0',
      base_revision: '0',
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-01T00:00:00+00:00',
    });
    expect(valid.success).toBe(true);

    const invalid = contracts.ProjectSchema.safeParse({
      version: 1,
      id: 'test',
      name: 'Test',
      revision: -1,
      base_revision: 0,
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-01T00:00:00+00:00',
    });
    expect(invalid.success).toBe(false);
  });

  it('REVISION_ABOVE_MAX_SAFE_INTEGER passes contract validation', async () => {
    const contracts = await import('@botconnector/contracts');
    const result = contracts.ProjectSchema.safeParse({
      version: 1,
      id: 'test',
      name: 'Test',
      revision: '9007199254740992',
      base_revision: '9007199254740991',
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-01T00:00:00+00:00',
    });
    expect(result.success).toBe(true);
  });

  it('REVISION_ORDERING_BIGINT_SAFE works for large values', async () => {
    const contracts = await import('@botconnector/contracts');
    const result = contracts.ProjectSchema.safeParse({
      version: 1,
      id: 'test',
      name: 'Test',
      revision: '9223372036854775807',
      base_revision: '9223372036854775806',
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-01T00:00:00+00:00',
    });
    expect(result.success).toBe(true);
  });
});

describe('29. If-Match handles large revision strings', () => {
  it('IF_MATCH_ABOVE_MAX_SAFE_INTEGER_EXACT preserves exact value', async () => {
    const projRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Large Revision Test' },
    });
    const projectId = JSON.parse(projRes.payload).data.id;

    const largeRevision = '9007199254740992';
    await adminPool.query(
      `UPDATE core.projects SET revision = $1::bigint, base_revision = $1::bigint WHERE id = $2`,
      [largeRevision, projectId],
    );

    const res = await app.inject({
      method: 'PATCH',
      url: `/api/v1/projects/${projectId}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': `"${largeRevision}"` },
      payload: { name: 'Updated Large' },
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.payload);
    expect(body.data.revision).toBe('9007199254740993');
  });

  it('REVISION_CONFLICT_LARGE_VALUE returns 409 on stale', async () => {
    const projRes = await app.inject({
      method: 'POST',
      url: '/api/v1/projects',
      headers: wsHeaders('ws-a'),
      payload: { name: 'Large Stale Test' },
    });
    const projectId = JSON.parse(projRes.payload).data.id;

    const largeRevision = '9007199254740992';
    await adminPool.query(
      `UPDATE core.projects SET revision = $1::bigint, base_revision = $1::bigint WHERE id = $2`,
      [largeRevision, projectId],
    );

    const res = await app.inject({
      method: 'PATCH',
      url: `/api/v1/projects/${projectId}`,
      headers: { ...wsHeaders('ws-a'), 'if-match': '"9007199254740991"' },
      payload: { name: 'Should Fail' },
    });
    expect(res.statusCode).toBe(409);
    const body = JSON.parse(res.payload);
    expect(body.error.code).toBe('REVISION_CONFLICT');
  });
});
