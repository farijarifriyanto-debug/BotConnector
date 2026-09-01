/**
 * Migration: Phase 4 correction — Durable event stream and outbox primitives
 *
 * Controlled additive correction to support the locked Phase 4 event/realtime
 * backbone. Does not modify, remove, or rename any existing Phase-2 column.
 *
 * 1. event.domain_events — canonical durable immutable event store:
 *    adds additive columns required for project-scoped replay and traceability:
 *      sequence bigint        (project-scoped deterministic order)
 *      event_version integer  (contract version of the event payload)
 *      correlation_id text
 *      causation_id text
 *      actor_type / actor_id
 *      timestamp timestamptz  (event occurrence time)
 *    New unique invariant: (workspace_id, project_id, sequence).
 *    New unique target for outbox composite FK: (workspace_id, project_id, id).
 *
 * 2. event.project_sequences — minimal dedicated atomic sequence allocator,
 *    one row per (workspace_id, project_id), bigint state. Allocation is an
 *    atomic INSERT ... ON CONFLICT ... DO UPDATE ... RETURNING inside the same
 *    transaction that writes the domain event + outbox row. Sequence starts at
 *    1 (0 reserved as "before first event" sentinel position).
 *
 * 3. event.outbox — transient-delivery bookkeeping persisted durably:
 *    references the canonical domain event (no full payload duplication),
 *    carries delivery state (dispatched_at, attempt_count, next_attempt_at,
 *    last_error) and restart-safe claim/lease state (lease_token,
 *    lease_expires_at). At-least-once semantics; NOT the replay source.
 *
 * Security: new tenant tables follow Phase-2 baseline — ENABLE + FORCE ROW
 * LEVEL SECURITY, tenant_isolation policy, composite tenant FKs, and grants to
 * application_role (NOSUPERUSER, NOBYPASSRLS). No global BYPASSRLS role.
 */

exports.up = (pgm) => {
  // 1. Additive columns on event.domain_events
  pgm.addColumns({ schema: 'event', name: 'domain_events' }, {
    sequence: { type: 'bigint', notNull: true, default: 0 },
    event_version: { type: 'integer', notNull: true, default: 1 },
    correlation_id: { type: 'text', notNull: true, default: '' },
    causation_id: { type: 'text' },
    actor_type: {
      type: 'text',
      notNull: true,
      default: 'system',
      check: "actor_type IN ('user','agent','system')",
    },
    actor_id: { type: 'text', notNull: true, default: '' },
    timestamp: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
  });

  // Unique durable invariant: (workspace_id, project_id, sequence)
  // This unique constraint index also serves project replay ordering.
  pgm.addConstraint(
    { schema: 'event', name: 'domain_events' },
    'domain_events_workspace_project_sequence_unique',
    { unique: ['workspace_id', 'project_id', 'sequence'] }
  );

  // Unique target so event.outbox can use a genuine composite tenant FK to the
  // canonical durable event.
  pgm.addConstraint(
    { schema: 'event', name: 'domain_events' },
    'domain_events_workspace_project_id_unique',
    { unique: ['workspace_id', 'project_id', 'id'] }
  );

  // 2. Atomic project sequence allocator
  pgm.createTable(
    { schema: 'event', name: 'project_sequences' },
    {
      workspace_id: { type: 'text', notNull: true },
      project_id: { type: 'text', notNull: true },
      current_value: { type: 'bigint', notNull: true, default: 1 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );
  pgm.addConstraint(
    { schema: 'event', name: 'project_sequences' },
    'project_sequences_pk',
    { primaryKey: ['workspace_id', 'project_id'] }
  );
  pgm.sql(`
    ALTER TABLE event.project_sequences
      ADD CONSTRAINT project_sequences_workspace_fkey
      FOREIGN KEY (workspace_id) REFERENCES core.workspaces(id) ON DELETE RESTRICT
  `);
  pgm.sql(`
    ALTER TABLE event.project_sequences
      ADD CONSTRAINT project_sequences_workspace_project_fkey
      FOREIGN KEY (workspace_id, project_id)
      REFERENCES core.projects(workspace_id, id) ON DELETE RESTRICT
  `);

  // 3. Durable outbox bookkeeping (NOT the canonical replay store)
  pgm.createTable(
    { schema: 'event', name: 'outbox' },
    {
      id: { type: 'text', primaryKey: true },
      workspace_id: { type: 'text', notNull: true },
      project_id: { type: 'text', notNull: true },
      event_id: { type: 'text', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      dispatched_at: { type: 'timestamptz' },
      attempt_count: { type: 'integer', notNull: true, default: 0 },
      next_attempt_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      last_error: { type: 'text' },
      lease_token: { type: 'text' },
      lease_expires_at: { type: 'timestamptz' },
    }
  );
  pgm.sql(`
    ALTER TABLE event.outbox
      ADD CONSTRAINT outbox_workspace_fkey
      FOREIGN KEY (workspace_id) REFERENCES core.workspaces(id) ON DELETE RESTRICT
  `);
  pgm.sql(`
    ALTER TABLE event.outbox
      ADD CONSTRAINT outbox_workspace_project_fkey
      FOREIGN KEY (workspace_id, project_id)
      REFERENCES core.projects(workspace_id, id) ON DELETE RESTRICT
  `);
  // Genuine composite tenant FK to the canonical durable event
  pgm.sql(`
    ALTER TABLE event.outbox
      ADD CONSTRAINT outbox_event_workspace_project_fkey
      FOREIGN KEY (workspace_id, project_id, event_id)
      REFERENCES event.domain_events(workspace_id, project_id, id) ON DELETE RESTRICT
  `);

  // Pending outbox claim index. The predicate is a stable boolean
  // (dispatched_at IS NULL) — no volatile now() in the predicate.
  pgm.sql(`
    CREATE INDEX idx_outbox_pending_claim
      ON event.outbox (next_attempt_at, created_at)
      WHERE dispatched_at IS NULL
  `);
  // Replay lookup helper (workspace-scoped, RLS also filters by workspace_id)
  pgm.sql(`
    CREATE INDEX idx_outbox_workspace_project
      ON event.outbox (workspace_id, project_id)
  `);

  // RLS baseline for the two new tenant tables
  for (const table of ['project_sequences', 'outbox']) {
    pgm.sql(`ALTER TABLE event.${table} ENABLE ROW LEVEL SECURITY`);
    pgm.sql(`ALTER TABLE event.${table} FORCE ROW LEVEL SECURITY`);
    pgm.sql(`
      CREATE POLICY tenant_isolation ON event.${table}
        USING (workspace_id = security.current_workspace_id())
        WITH CHECK (workspace_id = security.current_workspace_id())
    `);
  }

  // Grants to application_role (NOSUPERUSER, NOBYPASSRLS). Explicit for clarity;
  // ALTER DEFAULT PRIVILEGES already covers future tables in the event schema.
  pgm.sql(`
    GRANT SELECT, INSERT, UPDATE, DELETE
      ON event.domain_events, event.project_sequences, event.outbox
      TO application_role
  `);
};

exports.down = (pgm) => {
  pgm.sql('DROP INDEX IF EXISTS event.idx_outbox_workspace_project');
  pgm.sql('DROP INDEX IF EXISTS event.idx_outbox_pending_claim');
  pgm.dropTable({ schema: 'event', name: 'outbox' });
  pgm.dropTable({ schema: 'event', name: 'project_sequences' });
  pgm.sql('ALTER TABLE event.domain_events DROP CONSTRAINT IF EXISTS domain_events_workspace_project_id_unique');
  pgm.sql('ALTER TABLE event.domain_events DROP CONSTRAINT IF EXISTS domain_events_workspace_project_sequence_unique');
  pgm.dropColumns({ schema: 'event', name: 'domain_events' }, [
    'sequence',
    'event_version',
    'correlation_id',
    'causation_id',
    'actor_type',
    'actor_id',
    'timestamp',
  ]);
};
