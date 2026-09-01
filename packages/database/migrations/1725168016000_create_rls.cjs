/**
 * Migration: Row Level Security policies
 * Creates helper function and tenant isolation policies
 */
exports.up = (pgm) => {
  // Create app.workspace_id setting helper
  pgm.sql(`
    CREATE OR REPLACE FUNCTION security.current_workspace_id()
    RETURNS text
    LANGUAGE sql
    STABLE
    AS $$
      SELECT current_setting('app.workspace_id', true);
    $$;
  `);

  // All tenant-scoped tables that need RLS
  const tenantTables = [
    { schema: 'core', table: 'projects' },
    { schema: 'core', table: 'artifacts' },
    { schema: 'core', table: 'artifact_versions' },
    { schema: 'core', table: 'checkpoints' },
    { schema: 'core', table: 'checkpoint_artifacts' },
    { schema: 'core', table: 'workspace_members' },
    { schema: 'design', table: 'design_systems' },
    { schema: 'design', table: 'design_tokens' },
    { schema: 'design', table: 'design_decisions' },
    { schema: 'design', table: 'canvases' },
    { schema: 'design', table: 'frames' },
    { schema: 'memory', table: 'project_memory_revisions' },
    { schema: 'work', table: 'phases' },
    { schema: 'work', table: 'tasks' },
    { schema: 'work', table: 'task_dependencies' },
    { schema: 'work', table: 'focus_locks' },
    { schema: 'work', table: 'backlog_items' },
    { schema: 'work', table: 'acceptance_contracts' },
    { schema: 'work', table: 'acceptance_criteria' },
    { schema: 'ai', table: 'model_routes' },
    { schema: 'ai', table: 'model_route_candidates' },
    { schema: 'ai', table: 'generation_runs' },
    { schema: 'ai', table: 'steering_events' },
    { schema: 'ai', table: 'render_transactions' },
    { schema: 'ai', table: 'agent_runs' },
    { schema: 'ai', table: 'context_snapshots' },
    { schema: 'ai', table: 'context_snapshot_files' },
    { schema: 'ai', table: 'context_snapshot_decisions' },
    { schema: 'change', table: 'changesets' },
    { schema: 'change', table: 'change_operations' },
    { schema: 'validation', table: 'validation_runs' },
    { schema: 'validation', table: 'validation_stage_results' },
    { schema: 'validation', table: 'failure_signatures' },
    { schema: 'validation', table: 'validation_failures' },
    { schema: 'validation', table: 'repair_runs' },
    { schema: 'build', table: 'artifact_builds' },
    { schema: 'build', table: 'artifact_build_state' },
    { schema: 'resource', table: 'resources' },
    { schema: 'deploy', table: 'deployments' },
    { schema: 'event', table: 'generation_events' },
    { schema: 'event', table: 'domain_events' },
    { schema: 'security', table: 'agent_run_capabilities' },
    { schema: 'security', table: 'secret_bindings' },
    { schema: 'ops', table: 'idempotency_keys' },
  ];

  for (const { schema, table } of tenantTables) {
    // Enable RLS
    pgm.sql(`ALTER TABLE ${schema}.${table} ENABLE ROW LEVEL SECURITY`);
    pgm.sql(`ALTER TABLE ${schema}.${table} FORCE ROW LEVEL SECURITY`);

    // Create tenant isolation policy
    pgm.sql(`
      CREATE POLICY tenant_isolation ON ${schema}.${table}
        USING (workspace_id = security.current_workspace_id())
        WITH CHECK (workspace_id = security.current_workspace_id())
    `);
  }

  // iam.users is not workspace-scoped, use separate policy
  pgm.sql(`ALTER TABLE iam.users ENABLE ROW LEVEL SECURITY`);
  pgm.sql(`ALTER TABLE iam.users FORCE ROW LEVEL SECURITY`);
};

exports.down = (pgm) => {
  pgm.sql('DROP FUNCTION IF EXISTS security.current_workspace_id()');

  const tenantTables = [
    { schema: 'ops', table: 'idempotency_keys' },
    { schema: 'security', table: 'secret_bindings' },
    { schema: 'security', table: 'agent_run_capabilities' },
    { schema: 'event', table: 'domain_events' },
    { schema: 'event', table: 'generation_events' },
    { schema: 'deploy', table: 'deployments' },
    { schema: 'resource', table: 'resources' },
    { schema: 'build', table: 'artifact_build_state' },
    { schema: 'build', table: 'artifact_builds' },
    { schema: 'validation', table: 'repair_runs' },
    { schema: 'validation', table: 'validation_failures' },
    { schema: 'validation', table: 'failure_signatures' },
    { schema: 'validation', table: 'validation_stage_results' },
    { schema: 'validation', table: 'validation_runs' },
    { schema: 'change', table: 'change_operations' },
    { schema: 'change', table: 'changesets' },
    { schema: 'ai', table: 'context_snapshot_decisions' },
    { schema: 'ai', table: 'context_snapshot_files' },
    { schema: 'ai', table: 'context_snapshots' },
    { schema: 'ai', table: 'agent_runs' },
    { schema: 'ai', table: 'render_transactions' },
    { schema: 'ai', table: 'steering_events' },
    { schema: 'ai', table: 'generation_runs' },
    { schema: 'ai', table: 'model_route_candidates' },
    { schema: 'ai', table: 'model_routes' },
    { schema: 'work', table: 'acceptance_criteria' },
    { schema: 'work', table: 'acceptance_contracts' },
    { schema: 'work', table: 'backlog_items' },
    { schema: 'work', table: 'focus_locks' },
    { schema: 'work', table: 'task_dependencies' },
    { schema: 'work', table: 'tasks' },
    { schema: 'work', table: 'phases' },
    { schema: 'memory', table: 'project_memory_revisions' },
    { schema: 'design', table: 'frames' },
    { schema: 'design', table: 'canvases' },
    { schema: 'design', table: 'design_decisions' },
    { schema: 'design', table: 'design_tokens' },
    { schema: 'design', table: 'design_systems' },
    { schema: 'core', table: 'checkpoint_artifacts' },
    { schema: 'core', table: 'checkpoints' },
    { schema: 'core', table: 'artifact_versions' },
    { schema: 'core', table: 'artifacts' },
    { schema: 'core', table: 'workspace_members' },
    { schema: 'core', table: 'projects' },
  ];

  for (const { schema, table } of tenantTables) {
    pgm.sql(`DROP POLICY IF EXISTS tenant_isolation ON ${schema}.${table}`);
    pgm.sql(`ALTER TABLE ${schema}.${table} DISABLE ROW LEVEL SECURITY`);
  }
};
