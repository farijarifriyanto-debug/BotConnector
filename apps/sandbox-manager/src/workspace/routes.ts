import type { FastifyInstance } from 'fastify';
import type { WorkspaceManager, ExecutionWorkspace } from './manager.js';

export async function registerWorkspaceRoutes(
  app: FastifyInstance,
  workspaceManager: WorkspaceManager,
): Promise<void> {
  // CREATE workspace
  app.post<{
    Body: {
      project_id: string;
      task_id: string;
      repo_path: string;
      base_commit: string;
    };
  }>('/internal/v1/workspaces', async (request, reply) => {
    const { project_id, task_id, repo_path, base_commit } = request.body as {
      project_id: string;
      task_id: string;
      repo_path: string;
      base_commit: string;
    };

    if (!project_id || !task_id || !repo_path || !base_commit) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'Missing required fields' },
      });
      return;
    }

    const id = `ws-${project_id}-${task_id}-${Date.now()}`;
    const workspace = await workspaceManager.create({
      id,
      projectId: project_id,
      taskId: task_id,
      repoPath: repo_path,
      baseCommit: base_commit,
    });

    reply.code(201).send({ data: workspace });
  });

  // LIST workspaces
  app.get('/internal/v1/workspaces', async (_request, reply) => {
    const ids = await workspaceManager.list();
    reply.send({ data: ids });
  });

  // GET workspace
  app.get<{
    Params: { workspaceId: string };
  }>('/internal/v1/workspaces/:workspaceId', async (request, reply) => {
    const { workspaceId } = request.params;

    const exists = await workspaceManager.exists(workspaceId);
    if (!exists) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: `Workspace ${workspaceId} not found` },
      });
      return;
    }

    reply.send({ data: { id: workspaceId } });
  });

  // DESTROY workspace
  app.delete<{
    Params: { workspaceId: string };
  }>('/internal/v1/workspaces/:workspaceId', async (request, reply) => {
    const { workspaceId } = request.params;

    await workspaceManager.destroy(workspaceId);
    reply.send({ data: { destroyed: true } });
  });

  // GET workspace diff
  app.get<{
    Params: { workspaceId: string };
  }>('/internal/v1/workspaces/:workspaceId/diff', async (request, reply) => {
    const { workspaceId } = request.params;

    const exists = await workspaceManager.exists(workspaceId);
    if (!exists) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: `Workspace ${workspaceId} not found` },
      });
      return;
    }

    const diff = await workspaceManager.diff(workspaceId);
    reply.send({ data: { diff } });
  });

  // GET workspace status
  app.get<{
    Params: { workspaceId: string };
  }>('/internal/v1/workspaces/:workspaceId/status', async (request, reply) => {
    const { workspaceId } = request.params;

    const exists = await workspaceManager.exists(workspaceId);
    if (!exists) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: `Workspace ${workspaceId} not found` },
      });
      return;
    }

    const status = await workspaceManager.status(workspaceId);
    reply.send({ data: { status } });
  });
}
