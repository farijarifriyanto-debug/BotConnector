import type { FastifyInstance } from 'fastify';
import { randomUUID } from 'node:crypto';
import {
  ArtifactTypeSchema,
  ArtifactLifecycleSchema,
} from '@botconnector/contracts';
import { validationError, notFoundError } from '../errors/index.js';
import { sendSuccess, sendCreated, sendError } from '../errors/response.js';
import { createRequestContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import { parseIfMatch, assertRevisionMatch, incrementRevision } from '../db/concurrency.js';
import { fingerprintRequest, getIdempotencyResult, claimIdempotencyKey } from '../db/idempotency.js';
import { emitDomainEventForMutation } from '../events/service.js';
import type { PrincipalResolver } from '../index.js';

interface CreateArtifactBody {
  type: string;
}

interface UpdateArtifactBody {
  lifecycle?: string;
}

function validateCreateArtifact(body: unknown): CreateArtifactBody {
  if (!body || typeof body !== 'object') {
    throw validationError('Request body is required');
  }
  const b = body as Record<string, unknown>;
  if (typeof b.type !== 'string') {
    throw validationError('type is required and must be a string');
  }
  const parsed = ArtifactTypeSchema.safeParse(b.type);
  if (!parsed.success) {
    throw validationError(`Invalid artifact type: ${b.type}. Must be one of: web, mobile, design, presentation, document, spreadsheet, visualization, animation`);
  }
  return { type: b.type };
}

function validateUpdateArtifact(body: unknown): UpdateArtifactBody {
  if (!body || typeof body !== 'object') {
    throw validationError('Request body is required');
  }
  const b = body as Record<string, unknown>;
  if (b.lifecycle !== undefined) {
    const parsed = ArtifactLifecycleSchema.safeParse(b.lifecycle);
    if (!parsed.success) {
      throw validationError(`Invalid lifecycle: ${b.lifecycle}. Must be one of: draft, generating, valid, ready, published, archived`);
    }
  }
  return { lifecycle: b.lifecycle as string | undefined };
}

const ARTIFACT_COLUMNS = `id, project_id, type, lifecycle, revision, base_revision, current_version_id, created_at, updated_at`;

export async function registerArtifactRoutes(app: FastifyInstance, resolvePrincipal: PrincipalResolver): Promise<void> {
  app.post<{ Params: { projectId: string }; Body: CreateArtifactBody }>('/api/v1/projects/:projectId/artifacts', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const { projectId } = request.params;
      const body = validateCreateArtifact(request.body);
      const workspaceId = principal.workspaceId;
      const idempotencyKey = request.headers['idempotency-key'] as string | undefined;

      const result = await withTenantTransaction(workspaceId, async (tx) => {
        const projectCheck = await tx.client.query(
          `SELECT id FROM core.projects WHERE id = $1`,
          [projectId],
        );
        if (projectCheck.rows.length === 0) {
          throw notFoundError(`Project ${projectId} not found`);
        }

        if (idempotencyKey) {
          const fp = fingerprintRequest('POST', `/api/v1/projects/${projectId}/artifacts`, body);
          const existing = await getIdempotencyResult(tx.client, idempotencyKey, workspaceId, fp);
          if (existing.found) {
            if (existing.sameRequest) {
              return { cached: true as const, artifact: existing.result };
            }
            return { conflict: true as const };
          }
        }

        const artifactId = randomUUID();
        const now = new Date().toISOString();
        const insertResult = await tx.client.query(
          `INSERT INTO core.artifacts (id, project_id, workspace_id, type, lifecycle, revision, base_revision, created_at, updated_at)
           VALUES ($1, $2, $3, $4, 'draft', '0', '0', $5, $5)
           RETURNING ${ARTIFACT_COLUMNS}`,
          [artifactId, projectId, workspaceId, body.type, now],
        );

        const artifact = insertResult.rows[0];

        await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
          projectId,
          eventType: 'artifact.created',
          aggregateType: 'artifact',
          aggregateId: artifactId,
          payload: { artifact_id: artifactId, type: artifact.type, revision: artifact.revision },
        });

        if (idempotencyKey) {
          const fp = fingerprintRequest('POST', `/api/v1/projects/${projectId}/artifacts`, body);
          await claimIdempotencyKey(tx.client, idempotencyKey, workspaceId, fp, artifact);
        }

        return { cached: false as const, artifact };
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
        const cachedArtifact = result.artifact as Record<string, unknown>;
        sendSuccess(reply, requestCtx, cachedArtifact, { revision: cachedArtifact.revision as string, statusCode: 200 });
        return;
      }

      sendCreated(reply, requestCtx, result.artifact, { revision: result.artifact.revision });
    } catch (e) {
      sendError(reply, requestCtx, e);
    }
  });

  app.get<{ Params: { projectId: string } }>('/api/v1/projects/:projectId/artifacts', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const { projectId } = request.params;
      const workspaceId = principal.workspaceId;

      const rows = await withTenantTransaction(workspaceId, async (tx) => {
        const result = await tx.client.query(
          `SELECT ${ARTIFACT_COLUMNS} FROM core.artifacts WHERE project_id = $1 ORDER BY created_at DESC LIMIT 100`,
          [projectId],
        );
        return result.rows;
      });

      sendSuccess(reply, requestCtx, rows);
    } catch (e) {
      sendError(reply, requestCtx, e);
    }
  });

  app.get<{ Params: { artifactId: string } }>('/api/v1/artifacts/:artifactId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const { artifactId } = request.params;
      const workspaceId = principal.workspaceId;

      const rows = await withTenantTransaction(workspaceId, async (tx) => {
        const result = await tx.client.query(
          `SELECT ${ARTIFACT_COLUMNS} FROM core.artifacts WHERE id = $1`,
          [artifactId],
        );
        return result.rows;
      });

      if (rows.length === 0) {
        throw notFoundError(`Artifact ${artifactId} not found`);
      }

      sendSuccess(reply, requestCtx, rows[0], { revision: rows[0].revision });
    } catch (e) {
      sendError(reply, requestCtx, e);
    }
  });

  app.patch<{ Params: { artifactId: string }; Body: UpdateArtifactBody }>('/api/v1/artifacts/:artifactId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const { artifactId } = request.params;
      const body = validateUpdateArtifact(request.body);
      const workspaceId = principal.workspaceId;
      const ifMatchHeader = request.headers['if-match'] as string | undefined;
      const ifMatchRevision = parseIfMatch(ifMatchHeader);

      const result = await withTenantTransaction(workspaceId, async (tx) => {
        const existing = await tx.client.query(
          `SELECT id, revision FROM core.artifacts WHERE id = $1`,
          [artifactId],
        );

        if (existing.rows.length === 0) {
          throw notFoundError(`Artifact ${artifactId} not found`);
        }

        const currentRevision = existing.rows[0].revision as string;
        assertRevisionMatch(currentRevision, ifMatchRevision, 'Artifact');

        const now = new Date().toISOString();
        const newRevision = incrementRevision(currentRevision);
        const lifecycle = body.lifecycle || undefined;

        let updateResult;
        if (lifecycle) {
          updateResult = await tx.client.query(
            `UPDATE core.artifacts SET lifecycle = $1, revision = $2::bigint, base_revision = $2::bigint, updated_at = $3
             WHERE id = $4 AND revision = $5::bigint
             RETURNING ${ARTIFACT_COLUMNS}`,
            [lifecycle, newRevision, now, artifactId, ifMatchRevision],
          );
        } else {
          updateResult = await tx.client.query(
            `UPDATE core.artifacts SET revision = $1::bigint, base_revision = $1::bigint, updated_at = $2
             WHERE id = $3 AND revision = $4::bigint
             RETURNING ${ARTIFACT_COLUMNS}`,
            [newRevision, now, artifactId, ifMatchRevision],
          );
        }

        if (updateResult.rows.length === 0) {
          throw notFoundError(`Artifact ${artifactId} not found or revision changed`);
        }

        const updated = updateResult.rows[0];
        await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
          projectId: updated.project_id,
          eventType: 'artifact.updated',
          aggregateType: 'artifact',
          aggregateId: artifactId,
          payload: {
            artifact_id: artifactId,
            lifecycle: updated.lifecycle,
            revision: updated.revision,
          },
        });

        return updated;
      });

      sendSuccess(reply, requestCtx, result, { revision: result.revision });
    } catch (e) {
      sendError(reply, requestCtx, e);
    }
  });
}
