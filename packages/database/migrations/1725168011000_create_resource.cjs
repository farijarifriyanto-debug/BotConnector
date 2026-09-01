/**
 * Migration: Resource schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'resource', name: 'resources' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      content_hash: { type: 'text', notNull: true },
      object_key: { type: 'text', notNull: true },
      mime_type: { type: 'text', notNull: true },
      byte_size: { type: 'bigint', notNull: true },
      retention_policy: { type: 'text' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      expires_at: { type: 'timestamptz' },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'resource', name: 'resources' });
};
