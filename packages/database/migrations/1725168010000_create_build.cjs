/**
 * Migration: Build schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'build', name: 'artifact_builds' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      artifact_id: { type: 'text', notNull: true, references: 'core.artifacts(id)' },
      artifact_version_id: { type: 'text', references: 'core.artifact_versions(id)' },
      state: {
        type: 'text',
        notNull: true,
        check: "state IN ('pending','building','succeeded','failed','cancelled')",
      },
      build_output: { type: 'jsonb' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'build', name: 'artifact_build_state' },
    {
      id: { type: 'text', primaryKey: true },
      artifact_id: { type: 'text', notNull: true, references: 'core.artifacts(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      last_build_id: { type: 'text', references: 'build.artifact_builds(id)' },
      last_build_state: { type: 'text' },
      last_build_at: { type: 'timestamptz' },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'build', name: 'artifact_build_state' });
  pgm.dropTable({ schema: 'build', name: 'artifact_builds' });
};
