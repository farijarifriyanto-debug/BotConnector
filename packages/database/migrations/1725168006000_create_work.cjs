/**
 * Migration: Work schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'work', name: 'phases' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      ordinal: { type: 'integer', notNull: true, default: 0 },
      name: { type: 'text', notNull: true },
      active: { type: 'boolean', notNull: true, default: false },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'work', name: 'tasks' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      phase_id: { type: 'text', notNull: true, references: 'work.phases(id)' },
      title: { type: 'text', notNull: true },
      state: {
        type: 'text',
        notNull: true,
        check: "state IN ('draft','approved','queued','active','validating','ready','applying','done','cancelled','failed')",
      },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      acceptance_contract_id: { type: 'text' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'work', name: 'task_dependencies' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      depends_on_task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'work', name: 'focus_locks' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      scope: { type: 'text', notNull: true },
      owner_id: { type: 'text', notNull: true },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      acquired_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      expires_at: { type: 'timestamptz' },
    }
  );

  // Active focus uniqueness: only one active (non-expired) focus lock per project
  pgm.sql(`
    CREATE UNIQUE INDEX idx_focus_locks_active_unique
      ON work.focus_locks (project_id)
      WHERE expires_at IS NULL;
  `);

  pgm.createTable(
    { schema: 'work', name: 'backlog_items' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      title: { type: 'text', notNull: true },
      description: { type: 'text', notNull: true, default: '' },
      target_phase: { type: 'text' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'work', name: 'acceptance_contracts' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'work', name: 'acceptance_criteria' },
    {
      id: { type: 'text', primaryKey: true },
      acceptance_contract_id: { type: 'text', notNull: true, references: 'work.acceptance_contracts(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      description: { type: 'text', notNull: true },
      required: { type: 'boolean', notNull: true, default: true },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'work', name: 'acceptance_criteria' });
  pgm.dropTable({ schema: 'work', name: 'acceptance_contracts' });
  pgm.dropTable({ schema: 'work', name: 'backlog_items' });
  pgm.sql('DROP INDEX IF EXISTS work.idx_focus_locks_active_unique');
  pgm.dropTable({ schema: 'work', name: 'focus_locks' });
  pgm.dropTable({ schema: 'work', name: 'task_dependencies' });
  pgm.dropTable({ schema: 'work', name: 'tasks' });
  pgm.dropTable({ schema: 'work', name: 'phases' });
};
