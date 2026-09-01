/**
 * Migration: Deploy schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'deploy', name: 'deployments' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      artifact_id: { type: 'text', notNull: true, references: 'core.artifacts(id)' },
      artifact_version_id: { type: 'text', notNull: true, references: 'core.artifact_versions(id)' },
      environment: { type: 'text', notNull: true },
      state: {
        type: 'text',
        notNull: true,
        check: "state IN ('planned','running','succeeded','failed','cancelled')",
      },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'deploy', name: 'deployments' });
};
