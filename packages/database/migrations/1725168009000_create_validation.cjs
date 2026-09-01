/**
 * Migration: Validation schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'validation', name: 'validation_runs' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      changeset_id: { type: 'text', notNull: true, references: 'change.changesets(id)' },
      outcome: {
        type: 'text',
        notNull: true,
        check: "outcome IN ('pass','fail')",
      },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'validation', name: 'validation_stage_results' },
    {
      id: { type: 'text', primaryKey: true },
      validation_run_id: { type: 'text', notNull: true, references: 'validation.validation_runs(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      stage: {
        type: 'text',
        notNull: true,
        check: "stage IN ('parse','typecheck','build','runtime','browser','console','accessibility','regression')",
      },
      outcome: {
        type: 'text',
        notNull: true,
        check: "outcome IN ('pass','fail','skipped')",
      },
      duration_ms: { type: 'integer', notNull: true, default: 0 },
      message: { type: 'text' },
    }
  );

  pgm.createTable(
    { schema: 'validation', name: 'failure_signatures' },
    {
      id: { type: 'text', primaryKey: true },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      stage: {
        type: 'text',
        notNull: true,
        check: "stage IN ('parse','typecheck','build','runtime','browser','console','accessibility','regression')",
      },
      code: { type: 'text', notNull: true },
      fingerprint: { type: 'text', notNull: true },
      message: { type: 'text', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'validation', name: 'validation_failures' },
    {
      id: { type: 'text', primaryKey: true },
      validation_run_id: { type: 'text', notNull: true, references: 'validation.validation_runs(id)' },
      failure_signature_id: { type: 'text', notNull: true, references: 'validation.failure_signatures(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
    }
  );

  pgm.createTable(
    { schema: 'validation', name: 'repair_runs' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      failure_signature_id: { type: 'text', notNull: true, references: 'validation.failure_signatures(id)' },
      changeset_id: { type: 'text', references: 'change.changesets(id)' },
      state: {
        type: 'text',
        notNull: true,
        check: "state IN ('queued','running','completed','failed')",
      },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      started_at: { type: 'timestamptz' },
      ended_at: { type: 'timestamptz' },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'validation', name: 'repair_runs' });
  pgm.dropTable({ schema: 'validation', name: 'validation_failures' });
  pgm.dropTable({ schema: 'validation', name: 'failure_signatures' });
  pgm.dropTable({ schema: 'validation', name: 'validation_stage_results' });
  pgm.dropTable({ schema: 'validation', name: 'validation_runs' });
};
