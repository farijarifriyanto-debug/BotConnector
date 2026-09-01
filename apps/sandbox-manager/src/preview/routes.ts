import type { FastifyInstance } from 'fastify';
import { isAbsolute } from 'node:path';
import { realpath } from 'node:fs/promises';
import type { PreviewManager } from './manager.js';
import type { WorkspaceManager } from '../workspace/manager.js';

export async function registerPreviewRoutes(
  app: FastifyInstance,
  previewManager: PreviewManager,
  workspaceManager: WorkspaceManager,
): Promise<void> {
  // CREATE preview
  app.post<{
    Body: {
      workspace_id: string;
      project_id: string;
      task_id: string;
      command?: string[];
      dev_port?: number;
    };
  }>('/internal/v1/previews', async (request, reply) => {
    const { workspace_id, project_id, task_id, command, dev_port } = request.body as {
      workspace_id: string;
      project_id: string;
      task_id: string;
      command?: string[];
      dev_port?: number;
    };

    if (!workspace_id || !project_id || !task_id) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'Missing required fields' },
      });
      return;
    }

    if (dev_port !== undefined && (!Number.isInteger(dev_port) || dev_port < 1 || dev_port > 65535)) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'Invalid dev_port' },
      });
      return;
    }
    if (command !== undefined &&
        (!Array.isArray(command) || command.length === 0 || command.some((part) => typeof part !== 'string'))) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'Invalid command' },
      });
      return;
    }

    // Validate workspace ID has no traversal components
    if (workspace_id.includes('..') || isAbsolute(workspace_id)) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'Invalid workspace_id' },
      });
      return;
    }

    const workspace = workspaceManager.get(workspace_id);
    if (!workspace) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: `Workspace ${workspace_id} not found` },
      });
      return;
    }

    if (workspace.projectId !== project_id || workspace.taskId !== task_id) {
      reply.code(403).send({
        error: { code: 'FORBIDDEN', message: 'Workspace does not belong to the requested project/task' },
      });
      return;
    }

    // Resolve symlinks before mounting any host path into a container.
    let resolvedPath: string;
    let root: string;
    try {
      [resolvedPath, root] = await Promise.all([
        realpath(workspace.worktreePath),
        realpath(workspaceManager.getWorkspaceRoot()),
      ]);
    } catch {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: `Workspace ${workspace_id} is unavailable` },
      });
      return;
    }
    if (!(resolvedPath.startsWith(root + '/') || resolvedPath === root)) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'Workspace path outside root' },
      });
      return;
    }

    const trustedWorkspace = { ...workspace, worktreePath: resolvedPath };

    try {
      const preview = await previewManager.createPreview({
        workspaceId: workspace_id,
        projectId: project_id,
        taskId: task_id,
        command,
        devPort: dev_port,
      }, trustedWorkspace);

      reply.code(201).send({ data: preview });
    } catch (err) {
      reply.code(500).send({
        error: { code: 'PREVIEW_ERROR', message: (err as Error).message },
      });
    }
  });

  // LIST previews
  app.get('/internal/v1/previews', async (_request, reply) => {
    const previews = await previewManager.listPreviews();
    reply.send({ data: previews });
  });

  // LIST previews by workspace
  app.get<{
    Params: { workspaceId: string };
  }>('/internal/v1/workspaces/:workspaceId/previews', async (request, reply) => {
    const { workspaceId } = request.params;
    const previews = await previewManager.listPreviews();
    const filtered = previews.filter(p => p.workspaceId === workspaceId);
    reply.send({ data: filtered });
  });

  // GET preview
  app.get<{
    Params: { previewId: string };
  }>('/internal/v1/previews/:previewId', async (request, reply) => {
    const { previewId } = request.params;

    const preview = await previewManager.getPreview(previewId);
    if (!preview) {
      reply.code(404).send({
        error: { code: 'NOT_FOUND', message: `Preview ${previewId} not found` },
      });
      return;
    }

    reply.send({ data: preview });
  });

  // STOP preview
  app.post<{
    Params: { previewId: string };
  }>('/internal/v1/previews/:previewId/stop', async (request, reply) => {
    const { previewId } = request.params;

    await previewManager.stopPreview(previewId);
    reply.send({ data: { stopped: true } });
  });

  // DESTROY preview
  app.delete<{
    Params: { previewId: string };
  }>('/internal/v1/previews/:previewId', async (request, reply) => {
    const { previewId } = request.params;

    await previewManager.destroyPreview(previewId);
    reply.send({ data: { destroyed: true } });
  });

  // LIST previews by project
  app.get<{
    Params: { projectId: string };
  }>('/internal/v1/projects/:projectId/previews', async (request, reply) => {
    const { projectId } = request.params;
    const previews = await previewManager.listPreviewsByProject(projectId);
    reply.send({ data: previews });
  });
}
