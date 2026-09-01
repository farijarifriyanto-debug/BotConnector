import type { FastifyInstance } from 'fastify';
import { randomUUID } from 'node:crypto';
import { validationError, notFoundError, controlApiError } from '../errors/index.js';
import { sendSuccess, sendCreated, sendError } from '../errors/response.js';
import { createRequestContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import { incrementRevision } from '../db/concurrency.js';
import { fingerprintRequest, getIdempotencyResult, claimIdempotencyKey } from '../db/idempotency.js';
import { emitDomainEventForMutation } from '../events/service.js';
import { canTransitionGenerationRun } from './state-machine.js';
import type { PrincipalResolver } from '../index.js';
import type { z } from 'zod';
import type { GenerationStateSchema } from '@botconnector/contracts';

type GenerationState = z.infer<typeof GenerationStateSchema>;

const RUN_COLUMNS = `id, project_id, task_id, state, revision, base_revision, started_at, ended_at`;

interface CreateGenerationRunBody {
  task_id: string;
}

function validateCreateGenerationRun(body: unknown): CreateGenerationRunBody {
  if (!body || typeof body !== 'object') throw validationError('Request body is required');
  const b = body as Record<string, unknown>;
  if (typeof b.task_id !== 'string' || b.task_id.trim().length === 0) throw validationError('task_id is required');
  return { task_id: b.task_id.trim() };
}

export async function registerGenerationRunRoutes(app: FastifyInstance, resolvePrincipal: PrincipalResolver): Promise<void> {
  // CREATE generation run (starts in planning state)
  app.post<{ Params: { projectId: string }; Body: CreateGenerationRunBody }>(
    '/api/v1/projects/:projectId/generation-runs',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { projectId } = request.params;
        const body = validateCreateGenerationRun(request.body);
        const workspaceId = principal.workspaceId;
        const idempotencyKey = request.headers['idempotency-key'] as string | undefined;

        const result = await withTenantTransaction(workspaceId, async (tx) => {
          if (idempotencyKey) {
            const fp = fingerprintRequest('POST', `/api/v1/projects/${projectId}/generation-runs`, body);
            const existing = await getIdempotencyResult(tx.client, idempotencyKey, workspaceId, fp);
            if (existing.found) {
              if (existing.sameRequest) return { cached: true as const, run: existing.result };
              return { conflict: true as const };
            }
          }

          // Verify project exists
          const projCheck = await tx.client.query(`SELECT id FROM core.projects WHERE id = $1`, [projectId]);
          if (projCheck.rows.length === 0) throw notFoundError(`Project ${projectId} not found`);

          // Verify task exists and belongs to project
          const taskCheck = await tx.client.query(
            `SELECT id FROM work.tasks WHERE id = $1 AND project_id = $2`,
            [body.task_id, projectId],
          );
          if (taskCheck.rows.length === 0) throw notFoundError(`Task ${body.task_id} not found in project ${projectId}`);

          const runId = randomUUID();
          const now = new Date().toISOString();

          const insertResult = await tx.client.query(
            `INSERT INTO ai.generation_runs (id, project_id, workspace_id, task_id, state, revision, base_revision, started_at, ended_at)
             VALUES ($1, $2, $3, $4, 'planning', '0', '0', NULL, NULL)
             RETURNING ${RUN_COLUMNS}`,
            [runId, projectId, workspaceId, body.task_id],
          );

          const run = insertResult.rows[0];

          await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
            projectId,
            eventType: 'generation_run.created',
            aggregateType: 'generation_run',
            aggregateId: runId,
            payload: { task_id: body.task_id, state: 'planning' },
          });

          if (idempotencyKey) {
            const fp = fingerprintRequest('POST', `/api/v1/projects/${projectId}/generation-runs`, body);
            await claimIdempotencyKey(tx.client, idempotencyKey, workspaceId, fp, run);
          }

          return { cached: false as const, run };
        });

        if (result.conflict) {
          reply.code(409).send({
            error: { code: 'IDEMPOTENCY_CONFLICT', message: 'Idempotency key already used with a different request', request_id: requestCtx.requestId },
          });
          return;
        }

        if (result.cached) {
          sendSuccess(reply, requestCtx, result.run, { revision: (result.run as Record<string, unknown>).revision as string, statusCode: 200 });
          return;
        }

        sendCreated(reply, requestCtx, result.run, { revision: result.run.revision });
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  // LIST project generation runs
  app.get<{ Params: { projectId: string } }>(
    '/api/v1/projects/:projectId/generation-runs',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { projectId } = request.params;
        const workspaceId = principal.workspaceId;

        const rows = await withTenantTransaction(workspaceId, async (tx) => {
          const projCheck = await tx.client.query(`SELECT id FROM core.projects WHERE id = $1`, [projectId]);
          if (projCheck.rows.length === 0) throw notFoundError(`Project ${projectId} not found`);

          const result = await tx.client.query(
            `SELECT ${RUN_COLUMNS} FROM ai.generation_runs WHERE project_id = $1 LIMIT 100`,
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

  // GET generation run
  app.get<{ Params: { runId: string } }>(
    '/api/v1/generation-runs/:runId',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { runId } = request.params;
        const workspaceId = principal.workspaceId;

        const rows = await withTenantTransaction(workspaceId, async (tx) => {
          const result = await tx.client.query(
            `SELECT ${RUN_COLUMNS} FROM ai.generation_runs WHERE id = $1`,
            [runId],
          );
          return result.rows;
        });

        if (rows.length === 0) throw notFoundError(`Generation run ${runId} not found`);
        sendSuccess(reply, requestCtx, rows[0], { revision: rows[0].revision });
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  // LIFECYCLE COMMANDS: start, pause, resume, stop
  const lifecycleCommands = ['start', 'pause', 'resume', 'stop'] as const;

  for (const command of lifecycleCommands) {
    const targetState: Record<string, GenerationState> = {
      start: 'running',
      pause: 'pausing',
      resume: 'running',
      stop: 'stopping',
    };

    app.post<{ Params: { runId: string } }>(
      `/api/v1/generation-runs/:runId/${command}`,
      async (request, reply) => {
        const principal = resolvePrincipal(request.headers);
        const requestCtx = createRequestContext(principal);

        try {
          const { runId } = request.params;
          const workspaceId = principal.workspaceId;

          const result = await withTenantTransaction(workspaceId, async (tx) => {
            const existing = await tx.client.query(
              `SELECT ${RUN_COLUMNS} FROM ai.generation_runs WHERE id = $1`,
              [runId],
            );
            if (existing.rows.length === 0) throw notFoundError(`Generation run ${runId} not found`);

            const run = existing.rows[0];
            const currentState = run.state as GenerationState;
            const target = targetState[command];

            // Validate transition
            if (!canTransitionGenerationRun(currentState, target)) {
              throw controlApiError(
                'INVALID_GENERATION_RUN_TRANSITION',
                `Cannot transition generation run from "${currentState}" to "${target}"`,
                422,
              );
            }

            const newRevision = incrementRevision(run.revision as string);
            const now = new Date().toISOString();

            // Set started_at when transitioning to running for the first time
            const startedAt = (command === 'start' && currentState === 'planning') ? now : run.started_at;

            const updateResult = await tx.client.query(
              `UPDATE ai.generation_runs
               SET state = $1, revision = $2::bigint, base_revision = $2::bigint, started_at = COALESCE($3, started_at)
               WHERE id = $4
               RETURNING ${RUN_COLUMNS}`,
              [target, newRevision, startedAt, runId],
            );

            const updated = updateResult.rows[0];

            const eventType = `generation_run.${command === 'start' ? 'started' : command === 'pause' ? 'pause_requested' : command === 'resume' ? 'resumed' : 'stop_requested'}`;

            await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
              projectId: updated.project_id,
              eventType,
              aggregateType: 'generation_run',
              aggregateId: runId,
              payload: { from_state: currentState, to_state: target },
            });

            return updated;
          });

          sendSuccess(reply, requestCtx, result, { revision: result.revision });
        } catch (e) {
          sendError(reply, requestCtx, e);
        }
      },
    );
  }

}
