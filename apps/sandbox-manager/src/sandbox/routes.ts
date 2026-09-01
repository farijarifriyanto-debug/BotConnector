import type { FastifyInstance } from 'fastify';
import type { SandboxManager } from './manager.js';
import { listProfiles } from './profiles.js';

export async function registerSandboxRoutes(
  app: FastifyInstance,
  sandboxManager: SandboxManager,
): Promise<void> {
  // CREATE sandbox
  app.post<{
    Body: {
      workspace_id: string;
      project_id: string;
      task_id: string;
      profile?: string;
    };
  }>('/internal/v1/sandboxes', async (request, reply) => {
    const { workspace_id, project_id, task_id, profile } = request.body as {
      workspace_id: string;
      project_id: string;
      task_id: string;
      profile?: string;
    };

    if (!workspace_id || !project_id || !task_id) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'Missing required fields' },
      });
      return;
    }

    const sandbox = await sandboxManager.createSandbox({
      workspaceId: workspace_id,
      projectId: project_id,
      taskId: task_id,
      profile,
    });

    reply.code(201).send({ data: sandbox });
  });

  // LIST sandboxes
  app.get('/internal/v1/sandboxes', async (_request, reply) => {
    const sandboxes = await sandboxManager.listSandboxes();
    reply.send({ data: sandboxes });
  });

  // GET sandbox
  app.get<{
    Params: { sandboxId: string };
  }>('/internal/v1/sandboxes/:sandboxId', async (request, reply) => {
    const { sandboxId } = request.params;

    const sandbox = await sandboxManager.getSandbox(sandboxId);
    if (!sandbox) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: `Sandbox ${sandboxId} not found` },
      });
      return;
    }

    reply.send({ data: sandbox });
  });

  // EXEC in sandbox
  app.post<{
    Params: { sandboxId: string };
    Body: {
      command: string[];
      timeout_ms?: number;
      work_dir?: string;
    };
  }>('/internal/v1/sandboxes/:sandboxId/exec', async (request, reply) => {
    const { sandboxId } = request.params;
    const { command, timeout_ms, work_dir } = request.body as {
      command: string[];
      timeout_ms?: number;
      work_dir?: string;
    };

    if (!command || !Array.isArray(command) || command.length === 0) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'command must be a non-empty array' },
      });
      return;
    }

    const result = await sandboxManager.exec(sandboxId, {
      command,
      timeoutMs: timeout_ms,
      workDir: work_dir,
    });

    reply.send({ data: result });
  });

  // STOP sandbox
  app.post<{
    Params: { sandboxId: string };
  }>('/internal/v1/sandboxes/:sandboxId/stop', async (request, reply) => {
    const { sandboxId } = request.params;

    await sandboxManager.stopSandbox(sandboxId);
    reply.send({ data: { stopped: true } });
  });

  // DESTROY sandbox
  app.delete<{
    Params: { sandboxId: string };
  }>('/internal/v1/sandboxes/:sandboxId', async (request, reply) => {
    const { sandboxId } = request.params;

    await sandboxManager.destroySandbox(sandboxId);
    reply.send({ data: { destroyed: true } });
  });

  // LIST profiles
  app.get('/internal/v1/sandbox-profiles', async (_request, reply) => {
    const profiles = listProfiles();
    reply.send({ data: profiles });
  });
}
