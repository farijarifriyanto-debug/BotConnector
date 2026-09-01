import type { FastifyInstance } from 'fastify';
import { randomUUID } from 'node:crypto';
import { validationError, notFoundError } from '../errors/index.js';
import { sendSuccess, sendCreated, sendError } from '../errors/response.js';
import { createRequestContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import { fingerprintRequest, getIdempotencyResult, claimIdempotencyKey } from '../db/idempotency.js';
import type { PrincipalResolver } from '../index.js';

interface CreateArtifactVersionBody {
  source_revision: string;
  content_hash: string;
}

function validateCreateArtifactVersion(body: unknown): CreateArtifactVersionBody {
  if (!body || typeof body !== 'object') {
    throw validationError('Request body is required');
  }
  const b = body as Record<string, unknown>;
  if (typeof b.source_revision !== 'string' || b.source_revision.trim().length === 0) {
    throw validationError('source_revision is required and must be a non-empty string');
  }
  if (typeof b.content_hash !== 'string' || b.content_hash.trim().length === 0) {
    throw validationError('content_hash is required and must be a non-empty string');
  }
  return { source_revision: b.source_revision.trim(), content_hash: b.content_hash.trim() };
}

const VERSION_COLUMNS = `id, artifact_id, sequence, source_revision, content_hash, created_at`;

export async function registerArtifactVersionRoutes(app: FastifyInstance, resolvePrincipal: PrincipalResolver): Promise<void> {
  app.post<{ Params: { artifactId: string }; Body: CreateArtifactVersionBody }>(
    '/api/v1/artifacts/:artifactId/versions',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { artifactId } = request.params;
        const body = validateCreateArtifactVersion(request.body);
        const workspaceId = principal.workspaceId;
        const idempotencyKey = request.headers['idempotency-key'] as string | undefined;

        const result = await withTenantTransaction(workspaceId, async (tx) => {
          const artifactCheck = await tx.client.query(
            `SELECT id, project_id FROM core.artifacts WHERE id = $1`,
            [artifactId],
          );
          if (artifactCheck.rows.length === 0) {
            throw notFoundError(`Artifact ${artifactId} not found`);
          }

          const projectId = artifactCheck.rows[0].project_id;

          if (idempotencyKey) {
            const fp = fingerprintRequest('POST', `/api/v1/artifacts/${artifactId}/versions`, body);
            const existing = await getIdempotencyResult(tx.client, idempotencyKey, workspaceId, fp);
            if (existing.found) {
              if (existing.sameRequest) {
                return { cached: true as const, version: existing.result };
              }
              return { conflict: true as const };
            }
          }

          const maxSeqResult = await tx.client.query(
            `SELECT COALESCE(MAX(sequence), 0) as max_seq FROM core.artifact_versions WHERE artifact_id = $1`,
            [artifactId],
          );
          const nextSequence = Number(maxSeqResult.rows[0].max_seq) + 1;

          const versionId = randomUUID();
          const insertResult = await tx.client.query(
            `INSERT INTO core.artifact_versions (id, artifact_id, project_id, workspace_id, sequence, source_revision, content_hash)
             VALUES ($1, $2, $3, $4, $5, $6, $7)
             RETURNING ${VERSION_COLUMNS}`,
            [versionId, artifactId, projectId, workspaceId, nextSequence, body.source_revision, body.content_hash],
          );

          await tx.client.query(
            `UPDATE core.artifacts SET current_version_id = $1, updated_at = now() WHERE id = $2`,
            [versionId, artifactId],
          );

          const version = insertResult.rows[0];

          if (idempotencyKey) {
            const fp = fingerprintRequest('POST', `/api/v1/artifacts/${artifactId}/versions`, body);
            await claimIdempotencyKey(tx.client, idempotencyKey, workspaceId, fp, version);
          }

          return { cached: false as const, version };
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
          sendSuccess(reply, requestCtx, result.version, { statusCode: 200 });
          return;
        }

        sendCreated(reply, requestCtx, result.version);
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  app.get<{ Params: { artifactId: string } }>(
    '/api/v1/artifacts/:artifactId/versions',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { artifactId } = request.params;
        const workspaceId = principal.workspaceId;

        const rows = await withTenantTransaction(workspaceId, async (tx) => {
          const result = await tx.client.query(
            `SELECT ${VERSION_COLUMNS} FROM core.artifact_versions WHERE artifact_id = $1 ORDER BY sequence ASC LIMIT 100`,
            [artifactId],
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
