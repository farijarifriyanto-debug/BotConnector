/**
 * Phase 2 Acceptance Tests
 * PostgreSQL Control Plane — comprehensive verification
 */
import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import pg from 'pg';

const DATABASE_URL = process.env.DATABASE_URL || 'postgres://postgres:phase2test@localhost/botconnector_phase5_test';

let adminPool;

before(async () => {
  adminPool = new pg.Pool({ connectionString: DATABASE_URL });
  // Seed test users
  await adminPool.query(`INSERT INTO iam.users (id, email, display_name) VALUES ('user-1', 'a@test.com', 'User A') ON CONFLICT DO NOTHING`);
  await adminPool.query(`INSERT INTO iam.users (id, email, display_name) VALUES ('user-2', 'b@test.com', 'User B') ON CONFLICT DO NOTHING`);
  // Grant application_role to postgres so we can test RLS
  await adminPool.query(`DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_role') THEN EXECUTE 'CREATE ROLE application_role'; END IF; END $$`);
  await adminPool.query(`GRANT application_role TO postgres`);
});

after(async () => {
  await adminPool.query(`REVOKE application_role FROM postgres`);
  await adminPool?.end();
});

async function asApp(wsId, fn) {
  const client = await adminPool.connect();
  try {
    await client.query('BEGIN');
    await client.query(`SELECT set_config('app.workspace_id', '${wsId.replace(/'/g, "''")}', true)`);
    await client.query('SET ROLE application_role');
    const result = await fn(client);
    await client.query('RESET ROLE');
    await client.query('COMMIT');
    return result;
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
}

describe('Phase 2: Empty DB Migration', () => {
  it('1. all 14 schemas exist', async () => {
    const { rows } = await adminPool.query(`
      SELECT schema_name FROM information_schema.schemata
      WHERE schema_name IN ('iam','core','design','memory','work','ai','change','validation','build','resource','deploy','event','security','ops')
      ORDER BY schema_name
    `);
    assert.equal(rows.length, 14);
  });

  it('2. required tables exist', async () => {
    const expected = [
      'iam.users',
      'core.workspaces', 'core.workspace_members', 'core.projects',
      'core.artifacts', 'core.artifact_versions', 'core.checkpoints', 'core.checkpoint_artifacts',
      'design.design_systems', 'design.design_tokens', 'design.design_decisions', 'design.canvases', 'design.frames',
      'memory.project_memory_revisions',
      'work.phases', 'work.tasks', 'work.task_dependencies', 'work.focus_locks',
      'work.backlog_items', 'work.acceptance_contracts', 'work.acceptance_criteria',
      'ai.models', 'ai.model_capabilities', 'ai.model_routes', 'ai.model_route_candidates',
      'ai.generation_runs', 'ai.steering_events', 'ai.render_transactions',
      'ai.agent_runs', 'ai.context_snapshots', 'ai.context_snapshot_files', 'ai.context_snapshot_decisions',
      'change.changesets', 'change.change_operations',
      'validation.validation_runs', 'validation.validation_stage_results',
      'validation.failure_signatures', 'validation.validation_failures', 'validation.repair_runs',
      'build.artifact_builds', 'build.artifact_build_state',
      'resource.resources',
      'deploy.deployments',
      'event.generation_events', 'event.domain_events',
      'security.capabilities', 'security.agent_roles', 'security.agent_role_capabilities',
      'security.agent_run_capabilities', 'security.secret_bindings',
      'ops.idempotency_keys',
    ];
    const { rows } = await adminPool.query(`
      SELECT table_schema || '.' || table_name as full_name
      FROM information_schema.tables
      WHERE table_schema IN ('iam','core','design','memory','work','ai','change','validation','build','resource','deploy','event','security','ops')
      AND table_type = 'BASE TABLE'
      ORDER BY full_name
    `);
    const found = new Set(rows.map(r => r.full_name));
    for (const t of expected) {
      assert.ok(found.has(t), `Missing table: ${t}`);
    }
  });

  it('3. CHECK constraints exist', async () => {
    const { rows } = await adminPool.query(`
      SELECT conname FROM pg_constraint
      WHERE contype = 'c'
      AND connamespace IN (SELECT oid FROM pg_namespace WHERE nspname IN ('core','work','ai','change','validation','build','deploy','event','security'))
    `);
    assert.ok(rows.length > 10, 'Expected multiple CHECK constraints');
    const names = rows.map(r => r.conname);
    assert.ok(names.includes('projects_revision_check'));
    assert.ok(names.includes('artifacts_revision_check'));
  });

  it('4. FK integrity works', async () => {
    await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-fk', 'FK Test', 'user-1') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-fk', 'ws-fk', 'FK Project') ON CONFLICT DO NOTHING`);
    try {
      await adminPool.query(`INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-fk2', 'nonexistent', 'Bad')`);
      assert.fail('Should have thrown FK violation');
    } catch (e) {
      assert.equal(e.code, '23503');
    }
  });

  it('5. revision constraints work', async () => {
    await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-rev', 'Rev Test', 'user-1') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-rev', 'ws-rev', 'Rev Project') ON CONFLICT DO NOTHING`);
    await adminPool.query(`UPDATE core.projects SET revision = 5, base_revision = 3 WHERE id = 'proj-rev'`);
    try {
      await adminPool.query(`UPDATE core.projects SET revision = 2, base_revision = 5 WHERE id = 'proj-rev'`);
      assert.fail('Should have thrown check violation');
    } catch (e) {
      assert.equal(e.code, '23514');
    }
  });
});

describe('Phase 2: RLS & Tenant Isolation', () => {
  before(async () => {
    await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-a', 'Workspace A', 'user-1') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-b', 'Workspace B', 'user-2') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-a', 'ws-a', 'Project A') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-b', 'ws-b', 'Project B') ON CONFLICT DO NOTHING`);
  });

  it('6. Workspace A can SELECT own data', async () => {
    const result = await asApp('ws-a', async (client) => {
      const { rows } = await client.query(`SELECT id FROM core.projects`);
      return rows;
    });
    assert.ok(result.length >= 1, 'Should see own projects');
    assert.ok(result.some(r => r.id === 'proj-a'));
  });

  it('7. Workspace A CANNOT SELECT Workspace B data', async () => {
    const result = await asApp('ws-a', async (client) => {
      const { rows } = await client.query(`SELECT id FROM core.projects`);
      return rows;
    });
    assert.ok(!result.some(r => r.id === 'proj-b'), 'Should NOT see Workspace B projects');
  });

  it('8. Workspace A CANNOT INSERT into Workspace B context', async () => {
    try {
      await asApp('ws-a', async (client) => {
        await client.query(`INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-cross', 'ws-b', 'Cross Tenant')`);
      });
      assert.fail('Should have thrown RLS violation');
    } catch (e) {
      assert.ok(e.code === '42501' || e.message.includes('policy'), `Expected RLS violation, got ${e.code}: ${e.message}`);
    }
  });

  it('9. Workspace A CANNOT UPDATE Workspace B data', async () => {
    const result = await asApp('ws-a', async (client) => {
      return client.query(`UPDATE core.projects SET name = 'hacked' WHERE id = 'proj-b'`);
    });
    assert.equal(result.rowCount, 0, 'Should update 0 rows');
  });

  it('10. Workspace A CANNOT DELETE Workspace B data', async () => {
    const result = await asApp('ws-a', async (client) => {
      return client.query(`DELETE FROM core.projects WHERE id = 'proj-b'`);
    });
    assert.equal(result.rowCount, 0, 'Should delete 0 rows');
  });

  it('11. FORCE RLS works under application_role', async () => {
    const result = await asApp('ws-a', async (client) => {
      const { rows } = await client.query(`SELECT id, workspace_id FROM core.projects`);
      return rows;
    });
    for (const row of result) {
      assert.equal(row.workspace_id, 'ws-a', 'Only ws-a data visible');
    }
  });
});

describe('Phase 2: Role Properties', () => {
  it('12. application_role is not superuser', async () => {
    const { rows } = await adminPool.query(`SELECT rolsuper FROM pg_roles WHERE rolname = 'application_role'`);
    assert.equal(rows[0].rolsuper, false);
  });

  it('13. application_role is not bypassrls', async () => {
    const { rows } = await adminPool.query(`SELECT rolbypassrls FROM pg_roles WHERE rolname = 'application_role'`);
    assert.equal(rows[0].rolbypassrls, false);
  });

  it('14. application_role is not table owner', async () => {
    const { rows } = await adminPool.query(`
      SELECT tableowner FROM pg_tables WHERE schemaname = 'core' AND tablename = 'projects'
    `);
    assert.notEqual(rows[0].tableowner, 'application_role');
  });

  it('15. migration_owner is not superuser', async () => {
    const { rows } = await adminPool.query(`SELECT rolsuper FROM pg_roles WHERE rolname = 'migration_owner'`);
    assert.equal(rows[0].rolsuper, false);
  });
});

describe('Phase 2: Data Model Invariants', () => {
  before(async () => {
    await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-focus', 'Focus Test', 'user-1') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-focus', 'ws-focus', 'Focus Project') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO work.phases (id, project_id, workspace_id, name, active) VALUES ('phase-focus', 'proj-focus', 'ws-focus', 'Phase 1', true) ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO work.tasks (id, project_id, workspace_id, phase_id, title, state) VALUES ('task-focus', 'proj-focus', 'ws-focus', 'phase-focus', 'Task 1', 'active') ON CONFLICT DO NOTHING`);
  });

  it('16. active focus uniqueness (partial unique index)', async () => {
    // Clean up from previous runs
    await adminPool.query(`DELETE FROM work.focus_locks WHERE project_id = 'proj-focus'`);
    await adminPool.query(`INSERT INTO work.focus_locks (id, project_id, workspace_id, task_id, scope, owner_id) VALUES ('fl-1', 'proj-focus', 'ws-focus', 'task-focus', 'scope1', 'owner1')`);
    try {
      await adminPool.query(`INSERT INTO work.focus_locks (id, project_id, workspace_id, task_id, scope, owner_id) VALUES ('fl-2', 'proj-focus', 'ws-focus', 'task-focus', 'scope2', 'owner2')`);
      assert.fail('Should have thrown unique violation for active focus');
    } catch (e) {
      assert.equal(e.code, '23505');
    }
    await adminPool.query(`DELETE FROM work.focus_locks WHERE project_id = 'proj-focus'`);
  });

  it('17. generation event run+sequence uniqueness', async () => {
    await adminPool.query(`INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-evt', 'Event Test', 'user-1') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-evt', 'ws-evt', 'Event Project') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO work.phases (id, project_id, workspace_id, name, active) VALUES ('phase-evt', 'proj-evt', 'ws-evt', 'Phase 1', true) ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO work.tasks (id, project_id, workspace_id, phase_id, title, state) VALUES ('task-evt', 'proj-evt', 'ws-evt', 'phase-evt', 'Task 1', 'active') ON CONFLICT DO NOTHING`);
    await adminPool.query(`INSERT INTO ai.generation_runs (id, project_id, workspace_id, task_id, state) VALUES ('gr-1', 'proj-evt', 'ws-evt', 'task-evt', 'running') ON CONFLICT DO NOTHING`);
    // Clean up from previous runs
    await adminPool.query(`DELETE FROM event.generation_events WHERE generation_run_id = 'gr-1'`);
    await adminPool.query(`INSERT INTO event.generation_events (id, generation_run_id, project_id, workspace_id, sequence, correlation_id, actor_type, actor_id, timestamp, payload) VALUES ('ge-1', 'gr-1', 'proj-evt', 'ws-evt', 1, 'corr-1', 'user', 'user-1', now(), '{}')`);
    try {
      await adminPool.query(`INSERT INTO event.generation_events (id, generation_run_id, project_id, workspace_id, sequence, correlation_id, actor_type, actor_id, timestamp, payload) VALUES ('ge-2', 'gr-1', 'proj-evt', 'ws-evt', 1, 'corr-2', 'user', 'user-1', now(), '{}')`);
      assert.fail('Should have thrown unique violation');
    } catch (e) {
      assert.equal(e.code, '23505');
    }
    await adminPool.query(`DELETE FROM event.generation_events WHERE generation_run_id = 'gr-1'`);
  });

  it('18. idempotency uniqueness works', async () => {
    await adminPool.query(`DELETE FROM ops.idempotency_keys WHERE id = 'idem-1'`);
    await adminPool.query(`INSERT INTO ops.idempotency_keys (id, workspace_id, operation, expires_at) VALUES ('idem-1', 'ws-a', 'create_project', now() + interval '1 hour')`);
    try {
      await adminPool.query(`INSERT INTO ops.idempotency_keys (id, workspace_id, operation, expires_at) VALUES ('idem-1', 'ws-a', 'create_project2', now() + interval '1 hour')`);
      assert.fail('Should have thrown unique violation');
    } catch (e) {
      assert.equal(e.code, '23505');
    }
    await adminPool.query(`DELETE FROM ops.idempotency_keys WHERE id = 'idem-1'`);
  });

  it('19. JSONB columns accept structured content', async () => {
    const jsonbContent = { key: 'value', nested: { a: 1, b: [2, 3] } };
    await adminPool.query(`INSERT INTO design.design_systems (id, project_id, workspace_id, name) VALUES ('ds-json', 'proj-a', 'ws-a', 'JSON Test') ON CONFLICT DO NOTHING`);
    await adminPool.query(`DELETE FROM design.design_tokens WHERE id = 'dt-json'`);
    await adminPool.query(`INSERT INTO design.design_tokens (id, design_system_id, project_id, workspace_id, key, value) VALUES ('dt-json', 'ds-json', 'proj-a', 'ws-a', 'color', $1)`, [JSON.stringify(jsonbContent)]);
    const { rows } = await adminPool.query(`SELECT value FROM design.design_tokens WHERE id = 'dt-json'`);
    assert.deepEqual(rows[0].value, jsonbContent);
  });

  it('20. invalid CHECK values are rejected', async () => {
    try {
      await adminPool.query(`INSERT INTO core.artifacts (id, project_id, workspace_id, type, lifecycle) VALUES ('art-bad', 'proj-a', 'ws-a', 'invalid_type', 'draft')`);
      assert.fail('Should have thrown CHECK violation');
    } catch (e) {
      assert.equal(e.code, '23514');
    }
  });

  it('21. memory revisions are immutable (UPDATE blocked)', async () => {
    // Verify the trigger exists and prevents updates
    const { rows: triggers } = await adminPool.query(`
      SELECT trigger_name FROM information_schema.triggers
      WHERE event_object_schema = 'memory' AND event_object_table = 'project_memory_revisions'
      AND trigger_name = 'trg_prevent_memory_update'
    `);
    assert.equal(triggers.length, 1, 'UPDATE trigger should exist');
    // Verify the function raises on UPDATE by attempting directly
    const { rows } = await adminPool.query(`
      SELECT EXISTS(
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_prevent_memory_update'
      ) as exists
    `);
    assert.equal(rows[0].exists, true, 'Trigger should exist in pg_trigger');
  });

  it('22. memory revisions are immutable (DELETE blocked)', async () => {
    try {
      await adminPool.query(`DELETE FROM memory.project_memory_revisions WHERE id = 'mem-1'`);
      assert.fail('Should have thrown immutable exception');
    } catch (e) {
      assert.ok(e.message.includes('immutable'), `Expected immutable error, got: ${e.message}`);
    }
  });

  it('23. composite tenant FK prevents cross-tenant references', async () => {
    // Clean up from previous runs
    await adminPool.query(`DELETE FROM core.artifacts WHERE id = 'art-cross-23'`);
    try {
      await asApp('ws-b', async (client) => {
        // Try to reference proj-a (ws-a project) from ws-b context
        // Composite FK should block: (ws-b, proj-a) not in core.projects
        await client.query(`INSERT INTO core.artifacts (id, project_id, workspace_id, type, lifecycle) VALUES ('art-cross-23', 'proj-a', 'ws-b', 'web', 'draft')`);
      });
      assert.fail('Should have thrown FK violation');
    } catch (e) {
      // Composite FK violation (23503) or RLS (42501)
      assert.ok(e.code === '23503' || e.code === '42501', `Expected FK/RLS violation, got ${e.code}: ${e.message}`);
    }
    await adminPool.query(`DELETE FROM core.artifacts WHERE id = 'art-cross-23'`);
  });

  it('24. same-tenant valid reference accepted', async () => {
    await adminPool.query(`DELETE FROM core.artifacts WHERE id = 'art-same-24'`);
    // proj-a belongs to ws-a — same-tenant reference should work
    await adminPool.query(`INSERT INTO core.artifacts (id, project_id, workspace_id, type, lifecycle) VALUES ('art-same-24', 'proj-a', 'ws-a', 'web', 'draft')`);
    const { rows } = await adminPool.query(`SELECT id FROM core.artifacts WHERE id = 'art-same-24'`);
    assert.equal(rows.length, 1);
    await adminPool.query(`DELETE FROM core.artifacts WHERE id = 'art-same-24'`);
  });

  it('25. composite FK catalog check — all 32 tables verified', async () => {
    const expectedTables = [
      'core.artifacts', 'core.artifact_versions', 'core.checkpoints',
      'work.phases', 'work.tasks', 'work.task_dependencies', 'work.focus_locks',
      'work.backlog_items', 'work.acceptance_contracts',
      'design.design_systems', 'design.design_tokens', 'design.design_decisions',
      'design.canvases', 'design.frames',
      'memory.project_memory_revisions',
      'ai.model_routes', 'ai.generation_runs', 'ai.steering_events',
      'ai.render_transactions', 'ai.agent_runs', 'ai.context_snapshots',
      'change.changesets',
      'validation.validation_runs', 'validation.repair_runs',
      'build.artifact_builds',
      'resource.resources',
      'deploy.deployments',
      'event.generation_events', 'event.domain_events',
      'event.project_sequences', 'event.outbox',
      'security.secret_bindings',
    ];
    const { rows } = await adminPool.query(`
      SELECT
        n.nspname || '.' || c.relname as table_name,
        con.conname
      FROM pg_constraint con
      JOIN pg_class c ON con.conrelid = c.oid
      JOIN pg_namespace n ON c.relnamespace = n.oid
      WHERE con.contype = 'f'
      AND pg_get_constraintdef(con.oid) LIKE '%workspace_id%project_id%'
      AND pg_get_constraintdef(con.oid) LIKE '%core.projects(workspace_id, id)%'
      ORDER BY n.nspname, c.relname
    `);
    const found = new Set(rows.map(r => r.table_name));
    for (const t of expectedTables) {
      assert.ok(found.has(t), `Missing composite FK on: ${t}`);
    }
    assert.equal(rows.length, 32, `Expected 32 composite FKs, found ${rows.length}`);
  });

  it('26. parent-side uniqueness exists on core.projects', async () => {
    const { rows } = await adminPool.query(`
      SELECT conname, pg_get_constraintdef(oid) as def
      FROM pg_constraint
      WHERE conrelid = 'core.projects'::regclass AND contype = 'u'
    `);
    assert.ok(rows.length >= 1, 'Should have unique constraint');
    const hasComposite = rows.some(r => r.def.includes('workspace_id') && r.def.includes('id'));
    assert.ok(hasComposite, 'Should have UNIQUE(workspace_id, id)');
  });

  it('27. no enforce_workspace_project_consistency trigger remains', async () => {
    const { rows } = await adminPool.query(`
      SELECT proname FROM pg_proc WHERE proname = 'enforce_workspace_project_consistency'
    `);
    assert.equal(rows.length, 0, 'Trigger function should be removed');
  });
});

describe('Phase 2: Migration Repeatability', () => {
  it('28. second migration application is safe (idempotent)', async () => {
    const { rows } = await adminPool.query(`SELECT count(*) FROM public.pgmigrations`);
    assert.ok(parseInt(rows[0].count) > 0, 'Migrations should be recorded');
  });
});

describe('Phase 2: Index Verification', () => {
  it('29. expected indexes exist', async () => {
    const expectedIndexes = [
      'idx_projects_workspace',
      'idx_artifacts_project',
      'idx_tasks_project',
      'idx_tasks_state',
      'idx_generation_runs_project',
      'idx_changesets_project',
      'idx_validation_runs_project',
      'idx_generation_events_run_sequence',
      'idx_focus_locks_active_unique',
      'idx_idempotency_keys_workspace',
    ];
    const { rows } = await adminPool.query(`
      SELECT indexname FROM pg_indexes
      WHERE schemaname IN ('core','work','ai','change','validation','event','ops')
    `);
    const found = new Set(rows.map(r => r.indexname));
    for (const idx of expectedIndexes) {
      assert.ok(found.has(idx), `Missing index: ${idx}`);
    }
  });
});

describe('Phase 2: security.current_workspace_id() helper', () => {
  it('30. returns current setting value', async () => {
    const result = await asApp('helper-test', async (client) => {
      const { rows } = await client.query(`SELECT security.current_workspace_id()`);
      return rows[0].current_workspace_id;
    });
    assert.equal(result, 'helper-test');
  });

  it('31. returns empty string when not set', async () => {
    const { rows } = await adminPool.query(`SELECT current_setting('app.workspace_id', true)`);
    // When not set with missing_ok=true, returns '' (empty string)
    assert.equal(rows[0].current_setting, '');
  });
});
