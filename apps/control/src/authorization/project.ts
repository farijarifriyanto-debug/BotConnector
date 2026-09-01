import { withTenantTransaction } from '../db/tenant.js';

export async function projectBelongsToWorkspace(
  projectId: string,
  workspaceId: string,
): Promise<boolean> {
  return withTenantTransaction(workspaceId, async (tx) => {
    const result = await tx.client.query(
      'SELECT 1 FROM core.projects WHERE id = $1 AND workspace_id = $2 LIMIT 1',
      [projectId, workspaceId],
    );
    return result.rowCount === 1;
  });
}

export async function projectIdsForWorkspace(workspaceId: string): Promise<Set<string>> {
  return withTenantTransaction(workspaceId, async (tx) => {
    const result = await tx.client.query(
      'SELECT id FROM core.projects WHERE workspace_id = $1',
      [workspaceId],
    );
    return new Set(result.rows.map((row: { id: string }) => row.id));
  });
}
