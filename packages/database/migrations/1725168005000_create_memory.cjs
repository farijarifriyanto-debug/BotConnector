/**
 * Migration: Memory schema tables
 * memory.project_memory_revisions - Immutable memory revisions
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'memory', name: 'project_memory_revisions' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      entries: { type: 'jsonb', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  // Memory revisions are immutable: prevent UPDATE and DELETE
  pgm.sql(`
    CREATE OR REPLACE FUNCTION prevent_memory_mutation()
    RETURNS TRIGGER AS $$
    BEGIN
      RAISE EXCEPTION 'Memory revisions are immutable';
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_prevent_memory_update
      BEFORE UPDATE ON memory.project_memory_revisions
      FOR EACH ROW EXECUTE FUNCTION prevent_memory_mutation();

    CREATE TRIGGER trg_prevent_memory_delete
      BEFORE DELETE ON memory.project_memory_revisions
      FOR EACH ROW EXECUTE FUNCTION prevent_memory_mutation();
  `);
};

exports.down = (pgm) => {
  pgm.sql('DROP TRIGGER IF EXISTS trg_prevent_memory_delete ON memory.project_memory_revisions');
  pgm.sql('DROP TRIGGER IF EXISTS trg_prevent_memory_update ON memory.project_memory_revisions');
  pgm.sql('DROP FUNCTION IF EXISTS prevent_memory_mutation');
  pgm.dropTable({ schema: 'memory', name: 'project_memory_revisions' });
};
