import type { FastifyInstance } from 'fastify';
import type { SandboxManagerClient } from '../sandbox-manager/client.js';
import type { PrincipalResolver } from '../index.js';
import { projectBelongsToWorkspace } from '../authorization/project.js';

export async function registerWorkspaceRoutes(
  app: FastifyInstance,
  sandboxClient: SandboxManagerClient,
  resolvePrincipal: PrincipalResolver,
): Promise<void> {
  // CREATE execution workspace
  app.post<{
    Params: { projectId: string };
    Body: {
      task_id: string;
      repo_path: string;
      base_commit: string;
    };
  }>('/api/v1/projects/:projectId/workspaces', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const { projectId } = request.params;
    const { task_id, repo_path, base_commit } = request.body as {
      task_id: string;
      repo_path: string;
      base_commit: string;
    };

    if (!task_id || !repo_path || !base_commit) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'Missing required fields' },
      });
      return;
    }

    if (!(await projectBelongsToWorkspace(projectId, principal.workspaceId))) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: `Project ${projectId} not found` },
      });
      return;
    }

    try {
      const workspace = await sandboxClient.createWorkspace({
        projectId,
        taskId: task_id,
        repoPath: repo_path,
        baseCommit: base_commit,
      });

      reply.code(201).send({ data: workspace });
    } catch (err) {
      reply.code(500).send({
        error: { code: 'SANDBOX_MANAGER_ERROR', message: (err as Error).message },
      });
    }
  });

  // LIST workspaces for project
  app.get<{
    Params: { projectId: string };
  }>('/api/v1/projects/:projectId/workspaces', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    if (!(await projectBelongsToWorkspace(request.params.projectId, principal.workspaceId))) {
      reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Project not found' } });
      return;
    }
    // Workspace listing is internal - return empty for now
    reply.send({ data: [] });
  });

  // GET workspace
  app.get<{
    Params: { workspaceId: string };
  }>('/api/v1/workspaces/:workspaceId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const { workspaceId } = request.params;

    try {
      const workspace = await sandboxClient.getWorkspace(workspaceId);
      if (!(await projectBelongsToWorkspace(workspace.projectId, principal.workspaceId))) {
        reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Workspace not found' } });
        return;
      }
      reply.send({ data: workspace });
    } catch (err) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: (err as Error).message },
      });
    }
  });

  // DESTROY workspace
  app.delete<{
    Params: { workspaceId: string };
  }>('/api/v1/workspaces/:workspaceId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const { workspaceId } = request.params;

    try {
      const workspace = await sandboxClient.getWorkspace(workspaceId);
      if (!(await projectBelongsToWorkspace(workspace.projectId, principal.workspaceId))) {
        reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Workspace not found' } });
        return;
      }
      await sandboxClient.destroyWorkspace(workspaceId);
      reply.send({ data: { destroyed: true } });
    } catch (err) {
      reply.code(500).send({
        error: { code: 'SANDBOX_MANAGER_ERROR', message: (err as Error).message },
      });
    }
  });

  // GET workspace diff
  app.get<{
    Params: { workspaceId: string };
  }>('/api/v1/workspaces/:workspaceId/diff', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const { workspaceId } = request.params;

    try {
      const workspace = await sandboxClient.getWorkspace(workspaceId);
      if (!(await projectBelongsToWorkspace(workspace.projectId, principal.workspaceId))) {
        reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Workspace not found' } });
        return;
      }
      const diff = await sandboxClient.getWorkspaceDiff(workspaceId);
      reply.send({ data: { diff } });
    } catch (err) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: (err as Error).message },
      });
    }
  });
}
