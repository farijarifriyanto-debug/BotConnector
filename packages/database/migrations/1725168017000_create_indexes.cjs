/**
 * Migration: Indexes based on access patterns and foreign keys
 */
exports.up = (pgm) => {
  // Core indexes
  pgm.createIndex({ schema: 'core', name: 'projects' }, ['workspace_id'], { name: 'idx_projects_workspace' });
  pgm.createIndex({ schema: 'core', name: 'workspace_members' }, ['workspace_id'], { name: 'idx_workspace_members_workspace' });
  pgm.createIndex({ schema: 'core', name: 'workspace_members' }, ['user_id'], { name: 'idx_workspace_members_user' });
  pgm.createIndex({ schema: 'core', name: 'artifacts' }, ['project_id'], { name: 'idx_artifacts_project' });
  pgm.createIndex({ schema: 'core', name: 'artifacts' }, ['workspace_id'], { name: 'idx_artifacts_workspace' });
  pgm.createIndex({ schema: 'core', name: 'artifact_versions' }, ['artifact_id'], { name: 'idx_artifact_versions_artifact' });
  pgm.createIndex({ schema: 'core', name: 'artifact_versions' }, ['project_id'], { name: 'idx_artifact_versions_project' });
  pgm.createIndex({ schema: 'core', name: 'checkpoints' }, ['project_id'], { name: 'idx_checkpoints_project' });
  pgm.createIndex({ schema: 'core', name: 'checkpoint_artifacts' }, ['checkpoint_id'], { name: 'idx_checkpoint_artifacts_checkpoint' });

  // Work indexes
  pgm.createIndex({ schema: 'work', name: 'phases' }, ['project_id'], { name: 'idx_phases_project' });
  pgm.createIndex({ schema: 'work', name: 'tasks' }, ['project_id'], { name: 'idx_tasks_project' });
  pgm.createIndex({ schema: 'work', name: 'tasks' }, ['phase_id'], { name: 'idx_tasks_phase' });
  pgm.createIndex({ schema: 'work', name: 'tasks' }, ['state'], { name: 'idx_tasks_state' });
  pgm.createIndex({ schema: 'work', name: 'task_dependencies' }, ['task_id'], { name: 'idx_task_dependencies_task' });
  pgm.createIndex({ schema: 'work', name: 'task_dependencies' }, ['depends_on_task_id'], { name: 'idx_task_dependencies_depends' });
  pgm.createIndex({ schema: 'work', name: 'backlog_items' }, ['project_id'], { name: 'idx_backlog_items_project' });
  pgm.createIndex({ schema: 'work', name: 'acceptance_contracts' }, ['task_id'], { name: 'idx_acceptance_contracts_task' });
  pgm.createIndex({ schema: 'work', name: 'acceptance_criteria' }, ['acceptance_contract_id'], { name: 'idx_acceptance_criteria_contract' });

  // AI indexes
  pgm.createIndex({ schema: 'ai', name: 'model_routes' }, ['project_id'], { name: 'idx_model_routes_project' });
  pgm.createIndex({ schema: 'ai', name: 'model_route_candidates' }, ['model_route_id'], { name: 'idx_model_route_candidates_route' });
  pgm.createIndex({ schema: 'ai', name: 'generation_runs' }, ['project_id'], { name: 'idx_generation_runs_project' });
  pgm.createIndex({ schema: 'ai', name: 'generation_runs' }, ['task_id'], { name: 'idx_generation_runs_task' });
  pgm.createIndex({ schema: 'ai', name: 'steering_events' }, ['generation_run_id'], { name: 'idx_steering_events_run' });
  pgm.createIndex({ schema: 'ai', name: 'render_transactions' }, ['generation_run_id'], { name: 'idx_render_transactions_run' });
  pgm.createIndex({ schema: 'ai', name: 'agent_runs' }, ['project_id'], { name: 'idx_agent_runs_project' });
  pgm.createIndex({ schema: 'ai', name: 'agent_runs' }, ['task_id'], { name: 'idx_agent_runs_task' });
  pgm.createIndex({ schema: 'ai', name: 'context_snapshots' }, ['project_id'], { name: 'idx_context_snapshots_project' });
  pgm.createIndex({ schema: 'ai', name: 'context_snapshot_files' }, ['context_snapshot_id'], { name: 'idx_context_snapshot_files_snapshot' });
  pgm.createIndex({ schema: 'ai', name: 'context_snapshot_decisions' }, ['context_snapshot_id'], { name: 'idx_context_snapshot_decisions_snapshot' });

  // Change indexes
  pgm.createIndex({ schema: 'change', name: 'changesets' }, ['project_id'], { name: 'idx_changesets_project' });
  pgm.createIndex({ schema: 'change', name: 'changesets' }, ['task_id'], { name: 'idx_changesets_task' });
  pgm.createIndex({ schema: 'change', name: 'change_operations' }, ['changeset_id'], { name: 'idx_change_operations_changeset' });

  // Validation indexes
  pgm.createIndex({ schema: 'validation', name: 'validation_runs' }, ['project_id'], { name: 'idx_validation_runs_project' });
  pgm.createIndex({ schema: 'validation', name: 'validation_runs' }, ['changeset_id'], { name: 'idx_validation_runs_changeset' });
  pgm.createIndex({ schema: 'validation', name: 'validation_stage_results' }, ['validation_run_id'], { name: 'idx_validation_stage_results_run' });
  pgm.createIndex({ schema: 'validation', name: 'validation_failures' }, ['validation_run_id'], { name: 'idx_validation_failures_run' });
  pgm.createIndex({ schema: 'validation', name: 'repair_runs' }, ['project_id'], { name: 'idx_repair_runs_project' });

  // Build indexes
  pgm.createIndex({ schema: 'build', name: 'artifact_builds' }, ['artifact_id'], { name: 'idx_artifact_builds_artifact' });
  pgm.createIndex({ schema: 'build', name: 'artifact_build_state' }, ['artifact_id'], { name: 'idx_artifact_build_state_artifact' });

  // Resource indexes
  pgm.createIndex({ schema: 'resource', name: 'resources' }, ['project_id'], { name: 'idx_resources_project' });
  pgm.createIndex({ schema: 'resource', name: 'resources' }, ['content_hash'], { name: 'idx_resources_content_hash' });

  // Deploy indexes
  pgm.createIndex({ schema: 'deploy', name: 'deployments' }, ['project_id'], { name: 'idx_deployments_project' });
  pgm.createIndex({ schema: 'deploy', name: 'deployments' }, ['artifact_id'], { name: 'idx_deployments_artifact' });

  // Event indexes
  pgm.createIndex({ schema: 'event', name: 'generation_events' }, ['project_id'], { name: 'idx_generation_events_project' });
  pgm.createIndex({ schema: 'event', name: 'domain_events' }, ['project_id'], { name: 'idx_domain_events_project' });
  pgm.createIndex({ schema: 'event', name: 'domain_events' }, ['aggregate_type', 'aggregate_id'], { name: 'idx_domain_events_aggregate' });

  // Security indexes
  pgm.createIndex({ schema: 'security', name: 'agent_run_capabilities' }, ['agent_run_id'], { name: 'idx_agent_run_capabilities_run' });
  pgm.createIndex({ schema: 'security', name: 'secret_bindings' }, ['workspace_id'], { name: 'idx_secret_bindings_workspace' });

  // Ops indexes
  pgm.createIndex({ schema: 'ops', name: 'idempotency_keys' }, ['workspace_id'], { name: 'idx_idempotency_keys_workspace' });
  pgm.createIndex({ schema: 'ops', name: 'idempotency_keys' }, ['expires_at'], { name: 'idx_idempotency_keys_expires' });

  // Design indexes
  pgm.createIndex({ schema: 'design', name: 'design_systems' }, ['project_id'], { name: 'idx_design_systems_project' });
  pgm.createIndex({ schema: 'design', name: 'design_tokens' }, ['design_system_id'], { name: 'idx_design_tokens_system' });
  pgm.createIndex({ schema: 'design', name: 'design_decisions' }, ['project_id'], { name: 'idx_design_decisions_project' });
  pgm.createIndex({ schema: 'design', name: 'canvases' }, ['project_id'], { name: 'idx_canvases_project' });
  pgm.createIndex({ schema: 'design', name: 'frames' }, ['canvas_id'], { name: 'idx_frames_canvas' });

  // Memory indexes
  pgm.createIndex({ schema: 'memory', name: 'project_memory_revisions' }, ['project_id'], { name: 'idx_project_memory_revisions_project' });
};

exports.down = (pgm) => {
  const indexes = [
    'idx_project_memory_revisions_project',
    'idx_frames_canvas', 'idx_canvases_project', 'idx_design_decisions_project',
    'idx_design_tokens_system', 'idx_design_systems_project',
    'idx_idempotency_keys_expires', 'idx_idempotency_keys_workspace',
    'idx_secret_bindings_workspace', 'idx_agent_run_capabilities_run',
    'idx_domain_events_aggregate', 'idx_domain_events_project',
    'idx_generation_events_project',
    'idx_deployments_artifact', 'idx_deployments_project',
    'idx_resources_content_hash', 'idx_resources_project',
    'idx_artifact_build_state_artifact', 'idx_artifact_builds_artifact',
    'idx_repair_runs_project',
    'idx_validation_failures_run', 'idx_validation_stage_results_run',
    'idx_validation_runs_changeset', 'idx_validation_runs_project',
    'idx_change_operations_changeset', 'idx_changesets_task', 'idx_changesets_project',
    'idx_context_snapshot_decisions_snapshot', 'idx_context_snapshot_files_snapshot',
    'idx_context_snapshots_project',
    'idx_agent_runs_task', 'idx_agent_runs_project',
    'idx_render_transactions_run', 'idx_steering_events_run',
    'idx_generation_runs_task', 'idx_generation_runs_project',
    'idx_model_route_candidates_route', 'idx_model_routes_project',
    'idx_acceptance_criteria_contract', 'idx_acceptance_contracts_task',
    'idx_backlog_items_project',
    'idx_task_dependencies_depends', 'idx_task_dependencies_task',
    'idx_tasks_state', 'idx_tasks_phase', 'idx_tasks_project',
    'idx_phases_project',
    'idx_checkpoint_artifacts_checkpoint', 'idx_checkpoints_project',
    'idx_artifact_versions_project', 'idx_artifact_versions_artifact',
    'idx_artifacts_workspace', 'idx_artifacts_project',
    'idx_workspace_members_user', 'idx_workspace_members_workspace',
    'idx_projects_workspace',
  ];
  for (const idx of indexes) {
    pgm.sql(`DROP INDEX IF EXISTS ${idx.split('_')[0]}.${idx}`);
  }
};
