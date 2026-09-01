/**
 * Migration: Design schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'design', name: 'design_systems' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      name: { type: 'text', notNull: true },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'design', name: 'design_tokens' },
    {
      id: { type: 'text', primaryKey: true },
      design_system_id: { type: 'text', notNull: true, references: 'design.design_systems(id)' },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      key: { type: 'text', notNull: true },
      value: { type: 'jsonb', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'design', name: 'design_decisions' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text' },
      summary: { type: 'text', notNull: true },
      rationale: { type: 'text', notNull: true },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'design', name: 'canvases' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      artifact_id: { type: 'text', notNull: true, references: 'core.artifacts(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      root_node_id: { type: 'text', notNull: true },
      nodes: { type: 'jsonb', notNull: true },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'design', name: 'frames' },
    {
      id: { type: 'text', primaryKey: true },
      canvas_id: { type: 'text', notNull: true, references: 'design.canvases(id)' },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      node_id: { type: 'text', notNull: true },
      state: { type: 'jsonb', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'design', name: 'frames' });
  pgm.dropTable({ schema: 'design', name: 'canvases' });
  pgm.dropTable({ schema: 'design', name: 'design_decisions' });
  pgm.dropTable({ schema: 'design', name: 'design_tokens' });
  pgm.dropTable({ schema: 'design', name: 'design_systems' });
};
