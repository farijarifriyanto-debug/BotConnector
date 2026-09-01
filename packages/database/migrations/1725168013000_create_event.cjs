/**
 * Migration: Event schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'event', name: 'generation_events' },
    {
      id: { type: 'text', primaryKey: true },
      generation_run_id: { type: 'text', notNull: true, references: 'ai.generation_runs(id)' },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      sequence: { type: 'integer', notNull: true },
      correlation_id: { type: 'text', notNull: true },
      causation_id: { type: 'text' },
      actor_type: {
        type: 'text',
        notNull: true,
        check: "actor_type IN ('user','agent','system')",
      },
      actor_id: { type: 'text', notNull: true },
      timestamp: { type: 'timestamptz', notNull: true },
      payload: { type: 'jsonb', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  // Uniqueness: generation_run + sequence must be unique
  pgm.sql(`
    CREATE UNIQUE INDEX idx_generation_events_run_sequence
      ON event.generation_events (generation_run_id, sequence);
  `);

  pgm.createTable(
    { schema: 'event', name: 'domain_events' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      event_type: { type: 'text', notNull: true },
      aggregate_type: { type: 'text', notNull: true },
      aggregate_id: { type: 'text', notNull: true },
      payload: { type: 'jsonb', notNull: true },
      metadata: { type: 'jsonb' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'event', name: 'domain_events' });
  pgm.sql('DROP INDEX IF EXISTS event.idx_generation_events_run_sequence');
  pgm.dropTable({ schema: 'event', name: 'generation_events' });
};
