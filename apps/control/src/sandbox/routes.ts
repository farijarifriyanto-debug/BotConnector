import type { FastifyInstance } from 'fastify';
import type { SandboxManagerClient } from '../sandbox-manager/client.js';
import type { PrincipalResolver } from '../index.js';
import { projectBelongsToWorkspace } from '../authorization/project.js';

export async function registerSandboxRoutes(
  app: FastifyInstance,
  sandboxClient: SandboxManagerClient,
  resolvePrincipal: PrincipalResolver,
): Promise<void> {
  // CREATE sandbox
  app.post<{
    Params: { projectId: string };
    Body: {
      workspace_id: string;
      task_id: string;
      profile?: string;
    };
  }>('/api/v1/projects/:projectId/sandboxes', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const { projectId } = request.params;
    const { workspace_id, task_id, profile } = request.body as {
      workspace_id: string;
      task_id: string;
      profile?: string;
    };

    if (!workspace_id || !task_id) {
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
      const workspace = await sandboxClient.getWorkspace(workspace_id);
      if (workspace.projectId !== projectId || workspace.taskId !== task_id) {
        reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Workspace not found' } });
        return;
      }

      const sandbox = await sandboxClient.createSandbox({
        workspaceId: workspace_id,
        projectId,
        taskId: task_id,
        profile,
      });

      reply.code(201).send({ data: sandbox });
    } catch (err) {
      reply.code(500).send({
        error: { code: 'SANDBOX_MANAGER_ERROR', message: (err as Error).message },
      });
    }
  });

  // LIST sandboxes for project
  app.get<{
    Params: { projectId: string };
  }>('/api/v1/projects/:projectId/sandboxes', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    if (!(await projectBelongsToWorkspace(request.params.projectId, principal.workspaceId))) {
      reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Project not found' } });
      return;
    }
    // Sandbox listing is internal - return empty for now
    reply.send({ data: [] });
  });

  // GET sandbox
  app.get<{
    Params: { sandboxId: string };
  }>('/api/v1/sandboxes/:sandboxId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const { sandboxId } = request.params;

    try {
      const sandbox = await sandboxClient.getSandbox(sandboxId);
      if (!(await projectBelongsToWorkspace(sandbox.projectId, principal.workspaceId))) {
        reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Sandbox not found' } });
        return;
      }
      reply.send({ data: sandbox });
    } catch (err) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: (err as Error).message },
      });
    }
  });

  // NO PUBLIC EXEC ENDPOINT — command execution is INTERNAL-ONLY (sandbox manager)
  // The /api/v1/sandboxes/:sandboxId/exec route has been intentionally removed.
  // Public/browser callers must NEVER be able to execute arbitrary commands.
  // Execution is only possible via internal API (authenticated Bearer token, 127.0.0.1).

  // STOP sandbox
  app.post<{
    Params: { sandboxId: string };
  }>('/api/v1/sandboxes/:sandboxId/stop', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const { sandboxId } = request.params;

    try {
      const sandbox = await sandboxClient.getSandbox(sandboxId);
      if (!(await projectBelongsToWorkspace(sandbox.projectId, principal.workspaceId))) {
        reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Sandbox not found' } });
        return;
      }
      await sandboxClient.stopSandbox(sandboxId);
      reply.send({ data: { stopped: true } });
    } catch (err) {
      reply.code(500).send({
        error: { code: 'SANDBOX_MANAGER_ERROR', message: (err as Error).message },
      });
    }
  });

  // DESTROY sandbox
  app.delete<{
    Params: { sandboxId: string };
  }>('/api/v1/sandboxes/:sandboxId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const { sandboxId } = request.params;

    try {
      const sandbox = await sandboxClient.getSandbox(sandboxId);
      if (!(await projectBelongsToWorkspace(sandbox.projectId, principal.workspaceId))) {
        reply.code(404).send({ error: { code: 'NOT_FOUND', message: 'Sandbox not found' } });
        return;
      }
      await sandboxClient.destroySandbox(sandboxId);
      reply.send({ data: { destroyed: true } });
    } catch (err) {
      reply.code(500).send({
        error: { code: 'SANDBOX_MANAGER_ERROR', message: (err as Error).message },
      });
    }
  });
}
