/**
 * Migration: Change schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'change', name: 'changesets' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      state: {
        type: 'text',
        notNull: true,
        check: "state IN ('proposed','approved','applying','applied','rejected','rolled_back')",
      },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'change', name: 'change_operations' },
    {
      id: { type: 'text', primaryKey: true },
      changeset_id: { type: 'text', notNull: true, references: 'change.changesets(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      kind: {
        type: 'text',
        notNull: true,
        check: "kind IN ('create_file','update_file','delete_file','move_file')",
      },
      path: { type: 'text', notNull: true },
      destination_path: { type: 'text' },
      content: { type: 'text' },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'change', name: 'change_operations' });
  pgm.dropTable({ schema: 'change', name: 'changesets' });
};
