/**
 * Migration: Ops schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'ops', name: 'idempotency_keys' },
    {
      id: { type: 'text', primaryKey: true },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      operation: { type: 'text', notNull: true },
      result: { type: 'jsonb' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      expires_at: { type: 'timestamptz', notNull: true },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'ops', name: 'idempotency_keys' });
};
