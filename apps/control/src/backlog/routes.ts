import type { FastifyInstance } from 'fastify';
import { randomUUID } from 'node:crypto';
import { validationError, notFoundError } from '../errors/index.js';
import { sendSuccess, sendCreated, sendError } from '../errors/response.js';
import { createRequestContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import type { PrincipalResolver } from '../index.js';

interface CreateBacklogItemBody {
  title: string;
  description?: string;
  target_phase?: string | null;
}

function validateCreateBacklogItem(body: unknown): CreateBacklogItemBody {
  if (!body || typeof body !== 'object') {
    throw validationError('Request body is required');
  }
  const b = body as Record<string, unknown>;
  if (typeof b.title !== 'string' || b.title.trim().length === 0) {
    throw validationError('title is required and must be a non-empty string');
  }
  if (b.description !== undefined && typeof b.description !== 'string') {
    throw validationError('description must be a string');
  }
  if (b.target_phase !== undefined && b.target_phase !== null && typeof b.target_phase !== 'string') {
    throw validationError('target_phase must be a string or null');
  }
  return {
    title: b.title.trim(),
    description: (b.description as string) || '',
    target_phase: (b.target_phase as string | null) ?? null,
  };
}

const BACKLOG_COLUMNS = `id, project_id, title, description, target_phase, created_at`;

export async function registerBacklogRoutes(app: FastifyInstance, resolvePrincipal: PrincipalResolver): Promise<void> {
  app.post<{ Params: { projectId: string }; Body: CreateBacklogItemBody }>(
    '/api/v1/projects/:projectId/backlog',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { projectId } = request.params;
        const body = validateCreateBacklogItem(request.body);
        const workspaceId = principal.workspaceId;

        const item = await withTenantTransaction(workspaceId, async (tx) => {
          const projectCheck = await tx.client.query(
            `SELECT id FROM core.projects WHERE id = $1`,
            [projectId],
          );
          if (projectCheck.rows.length === 0) {
            throw notFoundError(`Project ${projectId} not found`);
          }

          const itemId = randomUUID();
          const result = await tx.client.query(
            `INSERT INTO work.backlog_items (id, project_id, workspace_id, title, description, target_phase)
             VALUES ($1, $2, $3, $4, $5, $6)
             RETURNING ${BACKLOG_COLUMNS}`,
            [itemId, projectId, workspaceId, body.title, body.description, body.target_phase],
          );

          return result.rows[0];
        });

        sendCreated(reply, requestCtx, item);
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  app.get<{ Params: { projectId: string } }>(
    '/api/v1/projects/:projectId/backlog',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { projectId } = request.params;
        const workspaceId = principal.workspaceId;

        const rows = await withTenantTransaction(workspaceId, async (tx) => {
          const result = await tx.client.query(
            `SELECT ${BACKLOG_COLUMNS} FROM work.backlog_items WHERE project_id = $1 ORDER BY created_at DESC LIMIT 100`,
            [projectId],
          );
          return result.rows;
        });

        sendSuccess(reply, requestCtx, rows);
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );
}
