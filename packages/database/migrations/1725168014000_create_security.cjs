/**
 * Migration: Security schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'security', name: 'capabilities' },
    {
      id: { type: 'text', primaryKey: true },
      domain: {
        type: 'text',
        notNull: true,
        check: "domain IN ('filesystem','runtime','browser','database','deployment','design','research')",
      },
      effect: {
        type: 'text',
        notNull: true,
        check: "effect IN ('read','write','execute','destructive')",
      },
      approval: {
        type: 'text',
        notNull: true,
        check: "approval IN ('automatic','policy','explicit')",
      },
    }
  );

  pgm.createTable(
    { schema: 'security', name: 'agent_roles' },
    {
      id: { type: 'text', primaryKey: true },
      name: { type: 'text', notNull: true, unique: true },
      description: { type: 'text' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'security', name: 'agent_role_capabilities' },
    {
      id: { type: 'text', primaryKey: true },
      agent_role_id: { type: 'text', notNull: true, references: 'security.agent_roles(id)' },
      capability_id: { type: 'text', notNull: true, references: 'security.capabilities(id)' },
    }
  );

  pgm.createTable(
    { schema: 'security', name: 'agent_run_capabilities' },
    {
      id: { type: 'text', primaryKey: true },
      agent_run_id: { type: 'text', notNull: true, references: 'ai.agent_runs(id)' },
      capability_id: { type: 'text', notNull: true, references: 'security.capabilities(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      granted: { type: 'boolean', notNull: true, default: false },
      approval_reference: { type: 'text' },
    }
  );

  pgm.createTable(
    { schema: 'security', name: 'secret_bindings' },
    {
      id: { type: 'text', primaryKey: true },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      project_id: { type: 'text', references: 'core.projects(id)' },
      secret_name: { type: 'text', notNull: true },
      secret_reference: { type: 'text', notNull: true },
      provider: { type: 'text', notNull: true },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'security', name: 'secret_bindings' });
  pgm.dropTable({ schema: 'security', name: 'agent_run_capabilities' });
  pgm.dropTable({ schema: 'security', name: 'agent_role_capabilities' });
  pgm.dropTable({ schema: 'security', name: 'agent_roles' });
  pgm.dropTable({ schema: 'security', name: 'capabilities' });
};
