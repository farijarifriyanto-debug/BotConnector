import type { FastifyInstance } from 'fastify';
import { randomUUID } from 'node:crypto';
import { validationError, notFoundError } from '../errors/index.js';
import { sendSuccess, sendCreated, sendError } from '../errors/response.js';
import { createRequestContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import { emitDomainEventForMutation } from '../events/service.js';
import type { PrincipalResolver } from '../index.js';

interface CreatePhaseBody {
  name: string;
  ordinal?: number;
}

function validateCreatePhase(body: unknown): CreatePhaseBody {
  if (!body || typeof body !== 'object') {
    throw validationError('Request body is required');
  }
  const b = body as Record<string, unknown>;
  if (typeof b.name !== 'string' || b.name.trim().length === 0) {
    throw validationError('name is required and must be a non-empty string');
  }
  if (b.ordinal !== undefined && (typeof b.ordinal !== 'number' || !Number.isInteger(b.ordinal) || b.ordinal < 0)) {
    throw validationError('ordinal must be a non-negative integer');
  }
  return { name: b.name.trim(), ordinal: b.ordinal as number | undefined };
}

const PHASE_COLUMNS = `id, project_id, ordinal, name, active, revision, base_revision, created_at`;

export async function registerPhaseRoutes(app: FastifyInstance, resolvePrincipal: PrincipalResolver): Promise<void> {
  app.post<{ Params: { projectId: string }; Body: CreatePhaseBody }>(
    '/api/v1/projects/:projectId/phases',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { projectId } = request.params;
        const body = validateCreatePhase(request.body);
        const workspaceId = principal.workspaceId;

        const phase = await withTenantTransaction(workspaceId, async (tx) => {
          const projectCheck = await tx.client.query(
            `SELECT id FROM core.projects WHERE id = $1`,
            [projectId],
          );
          if (projectCheck.rows.length === 0) {
            throw notFoundError(`Project ${projectId} not found`);
          }

          const maxOrdinalResult = await tx.client.query(
            `SELECT COALESCE(MAX(ordinal), -1) as max_ordinal FROM work.phases WHERE project_id = $1`,
            [projectId],
          );
          const ordinal = body.ordinal !== undefined ? body.ordinal : Number(maxOrdinalResult.rows[0].max_ordinal) + 1;

          const phaseId = randomUUID();
          const result = await tx.client.query(
            `INSERT INTO work.phases (id, project_id, workspace_id, ordinal, name, active, revision, base_revision)
             VALUES ($1, $2, $3, $4, $5, false, '0', '0')
             RETURNING ${PHASE_COLUMNS}`,
            [phaseId, projectId, workspaceId, ordinal, body.name],
          );

          const phase = result.rows[0];
          await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
            projectId,
            eventType: 'phase.created',
            aggregateType: 'phase',
            aggregateId: phaseId,
            payload: { phase_id: phaseId, name: phase.name, ordinal: phase.ordinal },
          });

          return phase;
        });

        sendCreated(reply, requestCtx, phase, { revision: phase.revision });
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  app.get<{ Params: { projectId: string } }>(
    '/api/v1/projects/:projectId/phases',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { projectId } = request.params;
        const workspaceId = principal.workspaceId;

        const rows = await withTenantTransaction(workspaceId, async (tx) => {
          const result = await tx.client.query(
            `SELECT ${PHASE_COLUMNS} FROM work.phases WHERE project_id = $1 ORDER BY ordinal ASC LIMIT 100`,
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
