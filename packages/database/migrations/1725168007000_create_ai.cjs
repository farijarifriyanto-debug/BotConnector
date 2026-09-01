/**
 * Migration: AI schema tables
 */
exports.up = (pgm) => {
  pgm.createTable(
    { schema: 'ai', name: 'models' },
    {
      id: { type: 'text', primaryKey: true },
      provider: { type: 'text', notNull: true },
      model_name: { type: 'text', notNull: true },
      display_name: { type: 'text' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'model_capabilities' },
    {
      id: { type: 'text', primaryKey: true },
      model_id: { type: 'text', notNull: true, references: 'ai.models(id)' },
      capability: { type: 'text', notNull: true },
      max_tokens: { type: 'integer' },
      supports_vision: { type: 'boolean', default: false },
      supports_function_calling: { type: 'boolean', default: false },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'model_routes' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      selected_candidate_id: { type: 'text' },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'model_route_candidates' },
    {
      id: { type: 'text', primaryKey: true },
      model_route_id: { type: 'text', notNull: true, references: 'ai.model_routes(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      provider: { type: 'text', notNull: true },
      model: { type: 'text', notNull: true },
      priority: { type: 'integer', notNull: true, default: 0 },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'generation_runs' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      state: {
        type: 'text',
        notNull: true,
        check: "state IN ('planning','running','pausing','paused','stopping','stopped','validating','repairing','completed','failed')",
      },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      started_at: { type: 'timestamptz' },
      ended_at: { type: 'timestamptz' },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'steering_events' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      generation_run_id: { type: 'text', notNull: true, references: 'ai.generation_runs(id)' },
      control: {
        type: 'text',
        notNull: true,
        check: "control IN ('current','global_rule','future_requirement','pause','resume','stop','reject','regenerate')",
      },
      priority: {
        type: 'text',
        notNull: true,
        check: "priority IN ('immediate','safe_point','queued')",
      },
      instruction: { type: 'text' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'render_transactions' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      generation_run_id: { type: 'text', notNull: true, references: 'ai.generation_runs(id)' },
      state: {
        type: 'text',
        notNull: true,
        check: "state IN ('open','validating','committed','rejected')",
      },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      candidate_revision: { type: 'text', notNull: true },
      last_known_good_revision: { type: 'text' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
      updated_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'agent_runs' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      role: {
        type: 'text',
        notNull: true,
        check: "role IN ('planner','designer','coder','researcher','tester','repairer','merger')",
      },
      state: {
        type: 'text',
        notNull: true,
        check: "state IN ('planned','running','completed','failed','cancelled')",
      },
      context_snapshot_id: { type: 'text', notNull: true },
      model_route_id: { type: 'text', notNull: true },
      revision: { type: 'bigint', notNull: true, default: 0 },
      base_revision: { type: 'bigint', notNull: true, default: 0 },
      started_at: { type: 'timestamptz' },
      ended_at: { type: 'timestamptz' },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'context_snapshots' },
    {
      id: { type: 'text', primaryKey: true },
      project_id: { type: 'text', notNull: true, references: 'core.projects(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      task_id: { type: 'text', notNull: true, references: 'work.tasks(id)' },
      project_revision: { type: 'integer', notNull: true },
      checkpoint_id: { type: 'text' },
      resource_refs: { type: 'jsonb', notNull: true, default: '[]' },
      created_at: { type: 'timestamptz', notNull: true, default: pgm.func('now()') },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'context_snapshot_files' },
    {
      id: { type: 'text', primaryKey: true },
      context_snapshot_id: { type: 'text', notNull: true, references: 'ai.context_snapshots(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      file_path: { type: 'text', notNull: true },
      content_hash: { type: 'text', notNull: true },
    }
  );

  pgm.createTable(
    { schema: 'ai', name: 'context_snapshot_decisions' },
    {
      id: { type: 'text', primaryKey: true },
      context_snapshot_id: { type: 'text', notNull: true, references: 'ai.context_snapshots(id)' },
      workspace_id: { type: 'text', notNull: true, references: 'core.workspaces(id)' },
      decision_id: { type: 'text', notNull: true },
    }
  );
};

exports.down = (pgm) => {
  pgm.dropTable({ schema: 'ai', name: 'context_snapshot_decisions' });
  pgm.dropTable({ schema: 'ai', name: 'context_snapshot_files' });
  pgm.dropTable({ schema: 'ai', name: 'context_snapshots' });
  pgm.dropTable({ schema: 'ai', name: 'agent_runs' });
  pgm.dropTable({ schema: 'ai', name: 'render_transactions' });
  pgm.dropTable({ schema: 'ai', name: 'steering_events' });
  pgm.dropTable({ schema: 'ai', name: 'generation_runs' });
  pgm.dropTable({ schema: 'ai', name: 'model_route_candidates' });
  pgm.dropTable({ schema: 'ai', name: 'model_routes' });
  pgm.dropTable({ schema: 'ai', name: 'model_capabilities' });
  pgm.dropTable({ schema: 'ai', name: 'models' });
};
