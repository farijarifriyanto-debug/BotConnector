/**
 * Migration: Tenant-safe FK validation via triggers
 * Prevents cross-tenant project references at database level
 */
exports.up = (pgm) => {
  // Create trigger function for workspace-project consistency
  pgm.sql(`
    CREATE OR REPLACE FUNCTION enforce_workspace_project_consistency()
    RETURNS TRIGGER AS $$
    DECLARE
      project_workspace_id text;
    BEGIN
      SELECT workspace_id INTO project_workspace_id
      FROM core.projects WHERE id = NEW.project_id;

      IF project_workspace_id IS NULL THEN
        RAISE EXCEPTION 'Referenced project % does not exist', NEW.project_id;
      END IF;

      IF project_workspace_id != NEW.workspace_id THEN
        RAISE EXCEPTION 'Cross-tenant reference blocked: project % belongs to workspace %, not %',
          NEW.project_id, project_workspace_id, NEW.workspace_id;
      END IF;

      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql SECURITY DEFINER;
  `);

  // Apply trigger to all tables with (project_id, workspace_id) pattern
  const tables = [
    { schema: 'core', table: 'artifacts' },
    { schema: 'core', table: 'artifact_versions' },
    { schema: 'core', table: 'checkpoints' },
    { schema: 'work', table: 'phases' },
    { schema: 'work', table: 'tasks' },
    { schema: 'work', table: 'task_dependencies' },
    { schema: 'work', table: 'focus_locks' },
    { schema: 'work', table: 'backlog_items' },
    { schema: 'work', table: 'acceptance_contracts' },
    { schema: 'design', table: 'design_systems' },
    { schema: 'design', table: 'design_tokens' },
    { schema: 'design', table: 'design_decisions' },
    { schema: 'design', table: 'canvases' },
    { schema: 'design', table: 'frames' },
    { schema: 'memory', table: 'project_memory_revisions' },
    { schema: 'ai', table: 'model_routes' },
    { schema: 'ai', table: 'generation_runs' },
    { schema: 'ai', table: 'steering_events' },
    { schema: 'ai', table: 'render_transactions' },
    { schema: 'ai', table: 'agent_runs' },
    { schema: 'ai', table: 'context_snapshots' },
    { schema: 'change', table: 'changesets' },
    { schema: 'validation', table: 'validation_runs' },
    { schema: 'validation', table: 'repair_runs' },
    { schema: 'build', table: 'artifact_builds' },
    { schema: 'resource', table: 'resources' },
    { schema: 'deploy', table: 'deployments' },
    { schema: 'event', table: 'generation_events' },
    { schema: 'event', table: 'domain_events' },
  ];

  for (const { schema, table } of tables) {
    pgm.sql(`
      CREATE TRIGGER trg_enforce_workspace_project_${schema}_${table}
        BEFORE INSERT OR UPDATE OF project_id ON ${schema}.${table}
        FOR EACH ROW
        WHEN (NEW.project_id IS NOT NULL)
        EXECUTE FUNCTION enforce_workspace_project_consistency()
    `);
  }
};

exports.down = (pgm) => {
  const tables = [
    { schema: 'event', table: 'domain_events' },
    { schema: 'event', table: 'generation_events' },
    { schema: 'deploy', table: 'deployments' },
    { schema: 'resource', table: 'resources' },
    { schema: 'build', table: 'artifact_builds' },
    { schema: 'validation', table: 'repair_runs' },
    { schema: 'validation', table: 'validation_runs' },
    { schema: 'change', table: 'changesets' },
    { schema: 'ai', table: 'context_snapshots' },
    { schema: 'ai', table: 'agent_runs' },
    { schema: 'ai', table: 'render_transactions' },
    { schema: 'ai', table: 'steering_events' },
    { schema: 'ai', table: 'generation_runs' },
    { schema: 'ai', table: 'model_routes' },
    { schema: 'memory', table: 'project_memory_revisions' },
    { schema: 'design', table: 'frames' },
    { schema: 'design', table: 'canvases' },
    { schema: 'design', table: 'design_decisions' },
    { schema: 'design', table: 'design_tokens' },
    { schema: 'design', table: 'design_systems' },
    { schema: 'work', table: 'acceptance_contracts' },
    { schema: 'work', table: 'backlog_items' },
    { schema: 'work', table: 'focus_locks' },
    { schema: 'work', table: 'task_dependencies' },
    { schema: 'work', table: 'tasks' },
    { schema: 'work', table: 'phases' },
    { schema: 'core', table: 'checkpoints' },
    { schema: 'core', table: 'artifact_versions' },
    { schema: 'core', table: 'artifacts' },
  ];

  for (const { schema, table } of tables) {
    pgm.sql(`DROP TRIGGER IF EXISTS trg_enforce_workspace_project_${schema}_${table} ON ${schema}.${table}`);
  }
  pgm.sql(`DROP FUNCTION IF EXISTS enforce_workspace_project_consistency`);
};
