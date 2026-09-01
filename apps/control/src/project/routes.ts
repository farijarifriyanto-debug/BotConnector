import type { FastifyInstance } from 'fastify';
import { randomUUID } from 'node:crypto';
import { validationError, notFoundError } from '../errors/index.js';
import { sendSuccess, sendCreated, sendError } from '../errors/response.js';
import { createRequestContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import { parseIfMatch, assertRevisionMatch, incrementRevision } from '../db/concurrency.js';
import { fingerprintRequest, getIdempotencyResult, claimIdempotencyKey } from '../db/idempotency.js';
import type { PrincipalResolver } from '../index.js';

interface CreateProjectBody {
  name: string;
}

interface UpdateProjectBody {
  name: string;
}

function validateCreateProject(body: unknown): CreateProjectBody {
  if (!body || typeof body !== 'object') {
    throw validationError('Request body is required');
  }
  const b = body as Record<string, unknown>;
  if (typeof b.name !== 'string' || b.name.trim().length === 0) {
    throw validationError('name is required and must be a non-empty string');
  }
  return { name: b.name.trim() };
}

function validateUpdateProject(body: unknown): UpdateProjectBody {
  if (!body || typeof body !== 'object') {
    throw validationError('Request body is required');
  }
  const b = body as Record<string, unknown>;
  if (typeof b.name !== 'string' || b.name.trim().length === 0) {
    throw validationError('name is required and must be a non-empty string');
  }
  return { name: b.name.trim() };
}

const PROJECT_COLUMNS = `id, name, revision, base_revision, created_at, updated_at`;

export async function registerProjectRoutes(app: FastifyInstance, resolvePrincipal: PrincipalResolver): Promise<void> {
  app.post<{ Body: CreateProjectBody }>('/api/v1/projects', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const body = validateCreateProject(request.body);
      const workspaceId = principal.workspaceId;
      const idempotencyKey = request.headers['idempotency-key'] as string | undefined;

      const result = await withTenantTransaction(workspaceId, async (tx) => {
        if (idempotencyKey) {
          const fp = fingerprintRequest('POST', '/api/v1/projects', body);
          const existing = await getIdempotencyResult(tx.client, idempotencyKey, workspaceId, fp);
          if (existing.found) {
            if (existing.sameRequest) {
              return { cached: true as const, project: existing.result };
            }
            return { conflict: true as const };
          }
        }

        const projectId = randomUUID();
        const now = new Date().toISOString();
        const insertResult = await tx.client.query(
          `INSERT INTO core.projects (id, workspace_id, name, revision, base_revision, created_at, updated_at)
           VALUES ($1, $2, $3, '0', '0', $4, $4)
           RETURNING ${PROJECT_COLUMNS}`,
          [projectId, workspaceId, body.name, now],
        );

        const project = insertResult.rows[0];

        if (idempotencyKey) {
          const fp = fingerprintRequest('POST', '/api/v1/projects', body);
          await claimIdempotencyKey(tx.client, idempotencyKey, workspaceId, fp, project);
        }

        return { cached: false as const, project };
      });

      if (result.conflict) {
        reply.code(409).send({
          error: {
            code: 'IDEMPOTENCY_CONFLICT',
            message: 'Idempotency key already used with a different request',
            request_id: requestCtx.requestId,
          },
        });
        return;
      }

      if (result.cached) {
        sendSuccess(reply, requestCtx, result.project, { revision: (result.project as Record<string, unknown>).revision as string, statusCode: 200 });
        return;
      }

      sendCreated(reply, requestCtx, result.project, { revision: result.project.revision });
    } catch (e) {
      sendError(reply, requestCtx, e);
    }
  });

  app.get('/api/v1/projects', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const workspaceId = principal.workspaceId;

      const rows = await withTenantTransaction(workspaceId, async (tx) => {
        const result = await tx.client.query(
          `SELECT ${PROJECT_COLUMNS} FROM core.projects ORDER BY created_at DESC LIMIT 100`,
        );
        return result.rows;
      });

      sendSuccess(reply, requestCtx, rows);
    } catch (e) {
      sendError(reply, requestCtx, e);
    }
  });

  app.get<{ Params: { projectId: string } }>('/api/v1/projects/:projectId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const { projectId } = request.params;
      const workspaceId = principal.workspaceId;

      const rows = await withTenantTransaction(workspaceId, async (tx) => {
        const result = await tx.client.query(
          `SELECT ${PROJECT_COLUMNS} FROM core.projects WHERE id = $1`,
          [projectId],
        );
        return result.rows;
      });

      if (rows.length === 0) {
        throw notFoundError(`Project ${projectId} not found`);
      }

      sendSuccess(reply, requestCtx, rows[0], { revision: rows[0].revision });
    } catch (e) {
      sendError(reply, requestCtx, e);
    }
  });

  app.patch<{ Params: { projectId: string }; Body: UpdateProjectBody }>('/api/v1/projects/:projectId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const { projectId } = request.params;
      const body = validateUpdateProject(request.body);
      const workspaceId = principal.workspaceId;
      const ifMatchHeader = request.headers['if-match'] as string | undefined;
      const ifMatchRevision = parseIfMatch(ifMatchHeader);

      const result = await withTenantTransaction(workspaceId, async (tx) => {
        const existing = await tx.client.query(
          `SELECT ${PROJECT_COLUMNS} FROM core.projects WHERE id = $1`,
          [projectId],
        );

        if (existing.rows.length === 0) {
          throw notFoundError(`Project ${projectId} not found`);
        }

        const currentRevision = existing.rows[0].revision as string;
        assertRevisionMatch(currentRevision, ifMatchRevision, 'Project');

        const now = new Date().toISOString();
        const newRevision = incrementRevision(currentRevision);

        const updateResult = await tx.client.query(
          `UPDATE core.projects SET name = $1, revision = $2::bigint, base_revision = $2::bigint, updated_at = $3
           WHERE id = $4 AND revision = $5::bigint
           RETURNING ${PROJECT_COLUMNS}`,
          [body.name, newRevision, now, projectId, ifMatchRevision],
        );

        if (updateResult.rows.length === 0) {
          throw notFoundError(`Project ${projectId} not found or revision changed`);
        }

        return updateResult.rows[0];
      });

      sendSuccess(reply, requestCtx, result, { revision: result.revision });
    } catch (e) {
      sendError(reply, requestCtx, e);
    }
  });
}
