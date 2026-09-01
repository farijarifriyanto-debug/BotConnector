/**
 * Phase 4 controlled correction — Durable event stream and outbox primitives
 * PostgreSQL verification on a fresh disposable database.
 */
import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import pg from 'pg';

const DATABASE_URL =
  process.env.DATABASE_URL || 'postgres://postgres:phase2test@localhost/botconnector_phase4_test';

let adminPool;

before(async () => {
  adminPool = new pg.Pool({ connectionString: DATABASE_URL });
  // Reset test-scoped event state so the suite is repeatable on a reused DB.
  await adminPool.query(
    `DELETE FROM event.outbox WHERE workspace_id IN ('ws-ea','ws-eb')`
  );
  await adminPool.query(
    `DELETE FROM event.domain_events WHERE workspace_id IN ('ws-ea','ws-eb')`
  );
  await adminPool.query(
    `DELETE FROM event.project_sequences WHERE workspace_id IN ('ws-ea','ws-eb')`
  );
  await adminPool.query(
    `INSERT INTO iam.users (id, email, display_name) VALUES ('user-1', 'a@test.com', 'User A') ON CONFLICT DO NOTHING`
  );
  await adminPool.query(
    `INSERT INTO iam.users (id, email, display_name) VALUES ('user-2', 'b@test.com', 'User B') ON CONFLICT DO NOTHING`
  );
  await adminPool.query(
    `DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'application_role') THEN EXECUTE 'CREATE ROLE application_role'; END IF; END $$`
  );
  await adminPool.query(`GRANT application_role TO postgres`);

  await adminPool.query(
    `INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-ea', 'Event A', 'user-1') ON CONFLICT DO NOTHING`
  );
  await adminPool.query(
    `INSERT INTO core.workspaces (id, name, owner_id) VALUES ('ws-eb', 'Event B', 'user-2') ON CONFLICT DO NOTHING`
  );
  await adminPool.query(
    `INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-ea', 'ws-ea', 'Project A') ON CONFLICT DO NOTHING`
  );
  await adminPool.query(
    `INSERT INTO core.projects (id, workspace_id, name) VALUES ('proj-eb', 'ws-eb', 'Project B') ON CONFLICT DO NOTHING`
  );
});

after(async () => {
  await adminPool.query(`REVOKE application_role FROM postgres`);
  await adminPool?.end();
});

/** Run work inside a trusted workspace transaction under application_role. */
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

/** Atomic project sequence allocator (the exact production pattern). */
function allocateSequence(client, wsId, projectId) {
  return client.query(
    `INSERT INTO event.project_sequences (workspace_id, project_id, current_value)
     VALUES ($1, $2, 1)
     ON CONFLICT (workspace_id, project_id)
     DO UPDATE SET current_value = event.project_sequences.current_value + 1, updated_at = now()
     RETURNING current_value`,
    [wsId, projectId]
  );
}

describe('Phase 4 correction: schema presence', () => {
  it('1. event.domain_events has additive durable-stream columns', async () => {
    const { rows } = await adminPool.query(
      `SELECT column_name, data_type FROM information_schema.columns
       WHERE table_schema = 'event' AND table_name = 'domain_events'
       ORDER BY ordinal_position`
    );
    const cols = Object.fromEntries(rows.map((r) => [r.column_name, r.data_type]));
    for (const c of [
      'sequence', 'event_version', 'correlation_id', 'causation_id',
      'actor_type', 'actor_id', 'timestamp',
    ]) {
      assert.ok(c in cols, `missing domain_events.${c}`);
    }
    assert.equal(cols.sequence, 'bigint');
    assert.equal(cols.event_version, 'integer');
  });

  it('2. original Phase-2 domain_events columns preserved', async () => {
    const { rows } = await adminPool.query(
      `SELECT column_name FROM information_schema.columns
       WHERE table_schema = 'event' AND table_name = 'domain_events'`
    );
    const cols = rows.map((r) => r.column_name);
    for (const c of ['id', 'project_id', 'workspace_id', 'event_type', 'aggregate_type', 'aggregate_id', 'payload', 'metadata', 'created_at']) {
      assert.ok(cols.includes(c), `Phase-2 column removed: ${c}`);
    }
  });

  it('3. event.project_sequences allocator exists with bigint state', async () => {
    const { rows } = await adminPool.query(
      `SELECT column_name, data_type FROM information_schema.columns
       WHERE table_schema = 'event' AND table_name = 'project_sequences'`
    );
    const cols = Object.fromEntries(rows.map((r) => [r.column_name, r.data_type]));
    assert.equal(cols.current_value, 'bigint');
    assert.ok('workspace_id' in cols && 'project_id' in cols);
  });

  it('4. event.outbox exists with delivery + lease state', async () => {
    const { rows } = await adminPool.query(
      `SELECT column_name FROM information_schema.columns
       WHERE table_schema = 'event' AND table_name = 'outbox'`
    );
    const cols = rows.map((r) => r.column_name);
    for (const c of [
      'id', 'workspace_id', 'project_id', 'event_id', 'created_at',
      'dispatched_at', 'attempt_count', 'next_attempt_at', 'last_error',
      'lease_token', 'lease_expires_at',
    ]) {
      assert.ok(cols.includes(c), `missing outbox.${c}`);
    }
  });

  it('5. unique (workspace_id, project_id, sequence) on domain_events', async () => {
    const { rows } = await adminPool.query(
      `SELECT conname FROM pg_constraint
       WHERE conrelid = 'event.domain_events'::regclass
         AND contype = 'u' AND conname = 'domain_events_workspace_project_sequence_unique'`
    );
    assert.equal(rows.length, 1);
  });

  it('6. new tenant tables are RLS-enabled and FORCE RLS', async () => {
    const { rows } = await adminPool.query(
      `SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
       FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'event' AND c.relname IN ('project_sequences', 'outbox')`
    );
    assert.equal(rows.length, 2);
    for (const r of rows) {
      assert.equal(r.relrowsecurity, true, `${r.relname} not RLS enabled`);
      assert.equal(r.relforcerowsecurity, true, `${r.relname} not FORCE RLS`);
    }
  });

  it('7. application_role has no BYPASSRLS and is not owner of new tables', async () => {
    const { rows } = await adminPool.query(
      `SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname = 'application_role'`
    );
    assert.equal(rows[0].rolbypassrls, false);
    const { rows: owners } = await adminPool.query(
      `SELECT t.tablename, t.tableowner AS owner
       FROM pg_tables t WHERE t.schemaname = 'event' AND t.tablename IN ('project_sequences','outbox')`
    );
    for (const o of owners) {
      assert.notEqual(o.owner, 'application_role', `${o.tablename} owned by application_role`);
    }
  });
});

describe('Phase 4 correction: sequence allocator', () => {
  it('8. allocation is monotonic and starts at 1', async () => {
    const seqs = [];
    for (let i = 0; i < 3; i++) {
      const v = await asApp('ws-ea', async (c) => {
        const r = await allocateSequence(c, 'ws-ea', 'proj-ea');
        return Number(r.rows[0].current_value);
      });
      seqs.push(v);
    }
    assert.deepEqual(seqs, [1, 2, 3]);
  });

  it('9. allocation is concurrent-safe (no duplicate sequences)', async () => {
    const N = 10;
    const results = await Promise.all(
      Array.from({ length: N }, () =>
        asApp('ws-ea', async (c) => {
          const r = await allocateSequence(c, 'ws-ea', 'proj-ea');
          return Number(r.rows[0].current_value);
        })
      )
    );
    const unique = new Set(results);
    assert.equal(unique.size, N, `duplicate sequence allocated: ${results}`);
    assert.equal(Math.max(...results) - Math.min(...results) + 1, N);
  });

  it('10. allocator is isolated per project', async () => {
    const a = await asApp('ws-ea', async (c) => Number((await allocateSequence(c, 'ws-ea', 'proj-ea')).rows[0].current_value));
    const b = await asApp('ws-eb', async (c) => Number((await allocateSequence(c, 'ws-eb', 'proj-eb')).rows[0].current_value));
    // b starts fresh at 1 regardless of project A counter state
    assert.equal(b, 1);
    assert.ok(a >= 1);
  });
});

describe('Phase 4 correction: durable event + outbox transaction', () => {
  const event = {
    id: 'evt-commit-1',
    workspace_id: 'ws-ea',
    project_id: 'proj-ea',
    event_type: 'project.updated',
    aggregate_type: 'project',
    aggregate_id: 'proj-ea',
    payload: { name: 'x' },
    event_version: 1,
    correlation_id: 'corr-1',
    causation_id: 'cause-1',
    actor_type: 'system',
    actor_id: 'control-plane',
    timestamp: new Date().toISOString(),
  };

  async function writeEvent(client, evt, outboxId) {
    const seq = await allocateSequence(client, evt.workspace_id, evt.project_id);
    const sequence = seq.rows[0].current_value;
    await client.query(
      `INSERT INTO event.domain_events
         (id, workspace_id, project_id, event_type, aggregate_type, aggregate_id,
          payload, sequence, event_version, correlation_id, causation_id,
          actor_type, actor_id, timestamp)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`,
      [evt.id, evt.workspace_id, evt.project_id, evt.event_type, evt.aggregate_type,
        evt.aggregate_id, evt.payload, sequence, evt.event_version, evt.correlation_id,
        evt.causation_id, evt.actor_type, evt.actor_id, evt.timestamp]
    );
    await client.query(
      `INSERT INTO event.outbox (id, workspace_id, project_id, event_id)
       VALUES ($1,$2,$3,$4)`,
      [outboxId, evt.workspace_id, evt.project_id, evt.id]
    );
    return sequence;
  }

  it('11. transactional commit persists event + outbox together', async () => {
    await asApp('ws-ea', async (c) => {
      await writeEvent(c, event, 'outbox-commit-1');
    });
    const evt = await adminPool.query(
      `SELECT sequence, correlation_id, causation_id, actor_type, actor_id, event_version
       FROM event.domain_events WHERE id = 'evt-commit-1'`
    );
    assert.equal(evt.rows.length, 1);
    assert.equal(evt.rows[0].correlation_id, 'corr-1');
    assert.equal(evt.rows[0].causation_id, 'cause-1');
    assert.equal(evt.rows[0].actor_type, 'system');
    assert.equal(evt.rows[0].event_version, 1);
    assert.ok(evt.rows[0].sequence >= 1);
    const out = await adminPool.query(
      `SELECT event_id, dispatched_at, attempt_count, lease_token FROM event.outbox WHERE id = 'outbox-commit-1'`
    );
    assert.equal(out.rows.length, 1);
    assert.equal(out.rows[0].event_id, 'evt-commit-1');
    assert.equal(out.rows[0].dispatched_at, null);
    assert.equal(out.rows[0].attempt_count, 0);
    assert.equal(out.rows[0].lease_token, null);
  });

  it('12. rollback leaves no durable phantom event/outbox', async () => {
    const rollbackEvent = { ...event, id: 'evt-rollback-1', correlation_id: 'corr-2' };
    let thrown = null;
    try {
      await asApp('ws-ea', async (c) => {
        await writeEvent(c, rollbackEvent, 'outbox-rollback-1');
        throw new Error('force rollback');
      });
    } catch (e) {
      thrown = e;
    }
    assert.ok(thrown);
    const evt = await adminPool.query(
      `SELECT id FROM event.domain_events WHERE id = 'evt-rollback-1'`
    );
    const out = await adminPool.query(
      `SELECT id FROM event.outbox WHERE id = 'outbox-rollback-1'`
    );
    const seq = await adminPool.query(
      `SELECT workspace_id FROM event.project_sequences WHERE workspace_id='ws-ea' AND project_id='proj-ea'`
    );
    assert.equal(evt.rows.length, 0, 'phantom domain event after rollback');
    assert.equal(out.rows.length, 0, 'phantom outbox row after rollback');
    assert.equal(seq.rows.length, 1, 'allocator row should still exist (state not rolled back to zero)');
  });

  it('13. duplicate project sequence rejected', async () => {
    const e1 = { ...event, id: 'evt-dup-1', correlation_id: 'c1' };
    const e2 = { ...event, id: 'evt-dup-2', correlation_id: 'c2' };
    let seq = null;
    await asApp('ws-ea', async (c) => {
      seq = await writeEvent(c, e1, 'outbox-dup-1');
    });
    await assert.rejects(
      asApp('ws-ea', async (c) => {
        await clientInsertSameSequence(c, e2, seq, 'outbox-dup-2');
      }),
      /unique/i
    );
  });
});

async function clientInsertSameSequence(client, evt, sequence, outboxId) {
  await client.query(
    `INSERT INTO event.domain_events
       (id, workspace_id, project_id, event_type, aggregate_type, aggregate_id,
        payload, sequence, event_version, correlation_id, causation_id,
        actor_type, actor_id, timestamp)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`,
    [evt.id, evt.workspace_id, evt.project_id, evt.event_type, evt.aggregate_type,
      evt.aggregate_id, evt.payload, sequence, evt.event_version, evt.correlation_id,
      evt.causation_id, evt.actor_type, evt.actor_id, evt.timestamp]
  );
  await client.query(
    `INSERT INTO event.outbox (id, workspace_id, project_id, event_id)
     VALUES ($1,$2,$3,$4)`,
    [outboxId, evt.workspace_id, evt.project_id, evt.id]
  );
}

describe('Phase 4 correction: RLS on new tables', () => {
  it('14. cross-tenant outbox insert blocked under application_role', async () => {
    await assert.rejects(
      asApp('ws-ea', async (c) => {
        await c.query(
          `INSERT INTO event.outbox (id, workspace_id, project_id, event_id)
           VALUES ('outbox-cross-1', 'ws-eb', 'proj-eb', 'evt-x')`
        );
      }),
      /row.?level.?security|permission/i
    );
  });

  it('15. cross-tenant sequence allocator blocked under application_role', async () => {
    await assert.rejects(
      asApp('ws-ea', async (c) => {
        await c.query(
          `INSERT INTO event.project_sequences (workspace_id, project_id, current_value)
           VALUES ('ws-eb', 'proj-eb', 1)`
        );
      }),
      /row.?level.?security|permission/i
    );
  });

  it('16. cross-tenant replay SELECT blocked under application_role', async () => {
    // Seed one durable event in ws-eb first
    await adminPool.query(
      `INSERT INTO event.project_sequences (workspace_id, project_id, current_value)
       VALUES ('ws-eb', 'proj-eb', 1) ON CONFLICT DO NOTHING`
    );
    await adminPool.query(
      `INSERT INTO event.domain_events
         (id, workspace_id, project_id, event_type, aggregate_type, aggregate_id,
          payload, sequence, event_version, correlation_id, causation_id,
          actor_type, actor_id, timestamp)
       VALUES ('evt-wsb-1', 'ws-eb', 'proj-eb', 'phase.updated', 'phase', 'ph-1',
               '{}', 1, 1, 'corr-wsb', NULL, 'system', 'svc', now())`
    );
    const result = await asApp('ws-ea', async (c) => {
      return (await c.query(`SELECT id FROM event.domain_events WHERE workspace_id = 'ws-eb'`)).rows;
    });
    assert.equal(result.length, 0, 'cross-tenant durable event leaked');
  });
});
