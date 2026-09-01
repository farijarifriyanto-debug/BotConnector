/**
 * Migration: Phase 2 Correction — Enforce composite tenant foreign keys
 *
 * Replaces single-column project_id FKs with genuine composite FKs:
 *   FOREIGN KEY (workspace_id, project_id) REFERENCES core.projects(workspace_id, id)
 *
 * Requires parent-side UNIQUE(workspace_id, id) on core.projects.
 * Removes redundant enforce_workspace_project_consistency() trigger function.
 */
exports.up = (pgm) => {
  // 1. Add composite unique constraint on core.projects for FK target
  pgm.addConstraint({ schema: 'core', name: 'projects' }, 'projects_workspace_id_unique', {
    unique: ['workspace_id', 'id'],
  });

  // 2. All tables that need composite FK replacement
  const tables = [
    { schema: 'core', table: 'artifacts', oldFk: 'artifacts_project_id_fkey' },
    { schema: 'core', table: 'artifact_versions', oldFk: 'artifact_versions_project_id_fkey' },
    { schema: 'core', table: 'checkpoints', oldFk: 'checkpoints_project_id_fkey' },
    { schema: 'work', table: 'phases', oldFk: 'phases_project_id_fkey' },
    { schema: 'work', table: 'tasks', oldFk: 'tasks_project_id_fkey' },
    { schema: 'work', table: 'task_dependencies', oldFk: 'task_dependencies_project_id_fkey' },
    { schema: 'work', table: 'focus_locks', oldFk: 'focus_locks_project_id_fkey' },
    { schema: 'work', table: 'backlog_items', oldFk: 'backlog_items_project_id_fkey' },
    { schema: 'work', table: 'acceptance_contracts', oldFk: 'acceptance_contracts_project_id_fkey' },
    { schema: 'design', table: 'design_systems', oldFk: 'design_systems_project_id_fkey' },
    { schema: 'design', table: 'design_tokens', oldFk: 'design_tokens_project_id_fkey' },
    { schema: 'design', table: 'design_decisions', oldFk: 'design_decisions_project_id_fkey' },
    { schema: 'design', table: 'canvases', oldFk: 'canvases_project_id_fkey' },
    { schema: 'design', table: 'frames', oldFk: 'frames_project_id_fkey' },
    { schema: 'memory', table: 'project_memory_revisions', oldFk: 'project_memory_revisions_project_id_fkey' },
    { schema: 'ai', table: 'model_routes', oldFk: 'model_routes_project_id_fkey' },
    { schema: 'ai', table: 'generation_runs', oldFk: 'generation_runs_project_id_fkey' },
    { schema: 'ai', table: 'steering_events', oldFk: 'steering_events_project_id_fkey' },
    { schema: 'ai', table: 'render_transactions', oldFk: 'render_transactions_project_id_fkey' },
    { schema: 'ai', table: 'agent_runs', oldFk: 'agent_runs_project_id_fkey' },
    { schema: 'ai', table: 'context_snapshots', oldFk: 'context_snapshots_project_id_fkey' },
    { schema: 'change', table: 'changesets', oldFk: 'changesets_project_id_fkey' },
    { schema: 'validation', table: 'validation_runs', oldFk: 'validation_runs_project_id_fkey' },
    { schema: 'validation', table: 'repair_runs', oldFk: 'repair_runs_project_id_fkey' },
    { schema: 'build', table: 'artifact_builds', oldFk: 'artifact_builds_project_id_fkey' },
    { schema: 'resource', table: 'resources', oldFk: 'resources_project_id_fkey' },
    { schema: 'deploy', table: 'deployments', oldFk: 'deployments_project_id_fkey' },
    { schema: 'event', table: 'generation_events', oldFk: 'generation_events_project_id_fkey' },
    { schema: 'event', table: 'domain_events', oldFk: 'domain_events_project_id_fkey' },
    { schema: 'security', table: 'secret_bindings', oldFk: 'secret_bindings_project_id_fkey' },
  ];

  for (const { schema, table, oldFk } of tables) {
    // Drop old single-column FK
    pgm.sql(`ALTER TABLE ${schema}.${table} DROP CONSTRAINT IF EXISTS ${oldFk}`);
    // Add composite FK
    pgm.sql(`
      ALTER TABLE ${schema}.${table} ADD CONSTRAINT ${table}_workspace_project_fkey
        FOREIGN KEY (workspace_id, project_id)
        REFERENCES core.projects(workspace_id, id)
        ON DELETE RESTRICT
    `);
  }

  // 3. Remove redundant trigger-based enforcement
  const triggerTables = [
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

  for (const { schema, table } of triggerTables) {
    pgm.sql(`DROP TRIGGER IF EXISTS trg_enforce_workspace_project_${schema}_${table} ON ${schema}.${table}`);
  }
  pgm.sql(`DROP FUNCTION IF EXISTS enforce_workspace_project_consistency`);
};

exports.down = (pgm) => {
  // Recreate trigger function
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

  // Restore single-column FKs and recreate triggers
  // (simplified — full rollback would mirror the up migration in reverse)
  pgm.sql(`ALTER TABLE core.projects DROP CONSTRAINT IF EXISTS projects_workspace_id_unique`);
};
