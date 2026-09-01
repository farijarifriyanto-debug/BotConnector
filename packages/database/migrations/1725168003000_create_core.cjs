/**
 * Migration: Core schema tables
 * core.workspaces - Tenant boundary
 * core.workspace_members - User-workspace membership
 * core.projects - Root aggregate
 * core.artifacts - Artifact manifests
 * core.artifact_versions - Version history
 * core.checkpoints - Project checkpoints
 * core.checkpoint_artifacts - Checkpoint-artifact junction
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'core', name: 'workspaces' },
    {
      id: { type: 'text', primaryKey: true },
      name: { type: 'text', notNull: true },
      owner_id: { type: 'text', notNull: true, references: 'iam.users(id)' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'core', name: 'workspace_members' },
    {
      id: { type: 'text', primaryKey: true },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      user_id: { type: 'text', notNull: true, references: 'iam.users(id)' },
      role: { type: 'text', notNull: true, default: 'member' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'core', name: 'projects' },
    {
      id: { type: 'text', primaryKey: true },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      name: { type: 'text', notNull: true },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.addConstraint({ schema: 'core', name: 'projects' }, 'projects_revision_check', {
    check: 'base_revision <= revision',
  });

  pgm.createTable(
    { schema: 'core', name: 'artifacts' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      type: {
        type: 'text',
        notNull: true,
        check: "type IN ('web','mobile','design','presentation','document','spreadsheet','visualization','animation')",
      },
      lifecycle: {
        type: 'text',
        notNull: true,
        check: "lifecycle IN ('draft','generating','valid','ready','published','archived')",
      },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      current_version_id: { type: 'text' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.addConstraint({ schema: 'core', name: 'artifacts' }, 'artifacts_revision_check', {
    check: 'base_revision <= revision',
  });

  pgm.createTable(
    { schema: 'core', name: 'artifact_versions' },
    {
      id: { type: 'text', primaryKey: true },
      artifact_id: { type: 'text', notNull: true, references: 'core.artifacts(id)' },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      sequence: { type: 'integer', notNull: true },
      source_revision: { type: 'text', notNull: true },
      content_hash: { type: 'text', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'core', name: 'checkpoints' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      source_revision: { type: 'text', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.addConstraint({ schema: 'core', name: 'checkpoints' }, 'checkpoints_revision_check', {
    check: 'base_revision <= revision',
  });

  pgm.createTable(
    { schema: 'core', name: 'checkpoint_artifacts' },
    {
      id: { type: 'text', primaryKey: true },
      checkpoint_id: { type: 'text', notNull: true, references: 'core.checkpoints(id)' },
      artifact_version_id: { type: 'text', notNull: true, references: 'core.artifact_versions(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'core', name: 'checkpoint_artifacts' });
  pgm.dropTable({ schema: 'core', name: 'checkpoints' });
  pgm.dropTable({ schema: 'core', name: 'artifact_versions' });
  pgm.dropTable({ schema: 'core', name: 'artifacts' });
  pgm.dropTable({ schema: 'core', name: 'projects' });
  pgm.dropTable({ schema: 'core', name: 'workspace_members' });
  pgm.dropTable({ schema: 'core', name: 'workspaces' });
};
