import type { FastifyInstance } from 'fastify';
import { randomUUID } from 'node:crypto';
import { validationError, notFoundError, revisionConflictError, controlApiError } from '../errors/index.js';
import { sendSuccess, sendCreated, sendError } from '../errors/response.js';
import { createRequestContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import { parseIfMatch, assertRevisionMatch, incrementRevision } from '../db/concurrency.js';
import { fingerprintRequest, getIdempotencyResult, claimIdempotencyKey } from '../db/idempotency.js';
import { emitDomainEventForMutation } from '../events/service.js';
import { canTransitionTask, isTerminalTaskState } from './state-machine.js';
import type { PrincipalResolver } from '../index.js';
import type { z } from 'zod';
import type { TaskStateSchema } from '@botconnector/contracts';

type TaskState = z.infer<typeof TaskStateSchema>;

const TASK_COLUMNS = `id, project_id, phase_id, title, state, revision, base_revision, acceptance_contract_id, created_at, updated_at`;

interface CreateTaskBody {
  phase_id: string;
  title: string;
}

interface UpdateTaskBody {
  title?: string;
}

function validateCreateTask(body: unknown): CreateTaskBody {
  if (!body || typeof body !== 'object') throw validationError('Request body is required');
  const b = body as Record<string, unknown>;
  if (typeof b.phase_id !== 'string' || b.phase_id.trim().length === 0) throw validationError('phase_id is required');
  if (typeof b.title !== 'string' || b.title.trim().length === 0) throw validationError('title is required');
  return { phase_id: b.phase_id.trim(), title: b.title.trim() };
}

function validateUpdateTask(body: unknown): UpdateTaskBody {
  if (!body || typeof body !== 'object') throw validationError('Request body is required');
  const b = body as Record<string, unknown>;
  // Reject lifecycle field injection attempts
  if ('state' in b) throw validationError('Cannot set lifecycle field "state" via PATCH; use POST /tasks/:taskId/{approve,queue,cancel}');
  if ('status' in b) throw validationError('Cannot set lifecycle field "status" via PATCH; use POST /tasks/:taskId/{approve,queue,cancel}');
  if (b.title !== undefined && (typeof b.title !== 'string' || b.title.trim().length === 0)) {
    throw validationError('title must be a non-empty string');
  }
  return { title: typeof b.title === 'string' ? b.title.trim() : undefined };
}

export async function registerTaskRoutes(app: FastifyInstance, resolvePrincipal: PrincipalResolver): Promise<void> {
  // CREATE task
  app.post<{ Params: { projectId: string }; Body: CreateTaskBody }>(
    '/api/v1/projects/:projectId/tasks',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { projectId } = request.params;
        const body = validateCreateTask(request.body);
        const workspaceId = principal.workspaceId;
        const idempotencyKey = request.headers['idempotency-key'] as string | undefined;

        const result = await withTenantTransaction(workspaceId, async (tx) => {
          if (idempotencyKey) {
            const fp = fingerprintRequest('POST', `/api/v1/projects/${projectId}/tasks`, body);
            const existing = await getIdempotencyResult(tx.client, idempotencyKey, workspaceId, fp);
            if (existing.found) {
              if (existing.sameRequest) return { cached: true as const, task: existing.result };
              return { conflict: true as const };
            }
          }

          // Verify project exists (RLS-scoped)
          const projCheck = await tx.client.query(`SELECT id FROM core.projects WHERE id = $1`, [projectId]);
          if (projCheck.rows.length === 0) throw notFoundError(`Project ${projectId} not found`);

          // Verify phase exists and belongs to project
          const phaseCheck = await tx.client.query(
            `SELECT id FROM work.phases WHERE id = $1 AND project_id = $2`,
            [body.phase_id, projectId],
          );
          if (phaseCheck.rows.length === 0) throw notFoundError(`Phase ${body.phase_id} not found in project ${projectId}`);

          const taskId = randomUUID();
          const now = new Date().toISOString();
          const insertResult = await tx.client.query(
            `INSERT INTO work.tasks (id, project_id, workspace_id, phase_id, title, state, revision, base_revision, created_at, updated_at)
             VALUES ($1, $2, $3, $4, $5, 'draft', '0', '0', $6, $6)
             RETURNING ${TASK_COLUMNS}`,
            [taskId, projectId, workspaceId, body.phase_id, body.title, now],
          );

          const task = insertResult.rows[0];

          await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
            projectId,
            eventType: 'task.created',
            aggregateType: 'task',
            aggregateId: taskId,
            payload: { title: task.title, phase_id: task.phase_id, state: task.state },
          });

          if (idempotencyKey) {
            const fp = fingerprintRequest('POST', `/api/v1/projects/${projectId}/tasks`, body);
            await claimIdempotencyKey(tx.client, idempotencyKey, workspaceId, fp, task);
          }

          return { cached: false as const, task };
        });

        if (result.conflict) {
          reply.code(409).send({
            error: { code: 'IDEMPOTENCY_CONFLICT', message: 'Idempotency key already used with a different request', request_id: requestCtx.requestId },
          });
          return;
        }

        if (result.cached) {
          sendSuccess(reply, requestCtx, result.task, { revision: (result.task as Record<string, unknown>).revision as string, statusCode: 200 });
          return;
        }

        sendCreated(reply, requestCtx, result.task, { revision: result.task.revision });
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  // LIST project tasks
  app.get<{ Params: { projectId: string } }>(
    '/api/v1/projects/:projectId/tasks',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { projectId } = request.params;
        const workspaceId = principal.workspaceId;

        const rows = await withTenantTransaction(workspaceId, async (tx) => {
          // Verify project exists
          const projCheck = await tx.client.query(`SELECT id FROM core.projects WHERE id = $1`, [projectId]);
          if (projCheck.rows.length === 0) throw notFoundError(`Project ${projectId} not found`);

          const result = await tx.client.query(
            `SELECT ${TASK_COLUMNS} FROM work.tasks WHERE project_id = $1 ORDER BY created_at DESC LIMIT 100`,
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

  // GET task
  app.get<{ Params: { taskId: string } }>(
    '/api/v1/tasks/:taskId',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { taskId } = request.params;
        const workspaceId = principal.workspaceId;

        const rows = await withTenantTransaction(workspaceId, async (tx) => {
          const result = await tx.client.query(
            `SELECT ${TASK_COLUMNS} FROM work.tasks WHERE id = $1`,
            [taskId],
          );
          return result.rows;
        });

        if (rows.length === 0) throw notFoundError(`Task ${taskId} not found`);
        sendSuccess(reply, requestCtx, rows[0], { revision: rows[0].revision });
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  // UPDATE mutable metadata (title only)
  app.patch<{ Params: { taskId: string }; Body: UpdateTaskBody }>(
    '/api/v1/tasks/:taskId',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { taskId } = request.params;
        const body = validateUpdateTask(request.body);
        const workspaceId = principal.workspaceId;
        const ifMatchHeader = request.headers['if-match'] as string | undefined;
        const ifMatchRevision = parseIfMatch(ifMatchHeader);

        if (body.title === undefined) {
          throw validationError('At least one mutable field (title) must be provided');
        }

        const result = await withTenantTransaction(workspaceId, async (tx) => {
          const existing = await tx.client.query(`SELECT ${TASK_COLUMNS} FROM work.tasks WHERE id = $1`, [taskId]);
          if (existing.rows.length === 0) throw notFoundError(`Task ${taskId} not found`);

          const currentRevision = existing.rows[0].revision as string;
          assertRevisionMatch(currentRevision, ifMatchRevision, 'Task');

          const newRevision = incrementRevision(currentRevision);
          const now = new Date().toISOString();

          const updateResult = await tx.client.query(
            `UPDATE work.tasks SET title = $1, revision = $2::bigint, base_revision = $2::bigint, updated_at = $3
             WHERE id = $4 AND revision = $5::bigint
             RETURNING ${TASK_COLUMNS}`,
            [body.title, newRevision, now, taskId, ifMatchRevision],
          );

          if (updateResult.rows.length === 0) {
            throw revisionConflictError('Task revision changed during update');
          }

          const updated = updateResult.rows[0];
          await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
            projectId: updated.project_id,
            eventType: 'task.updated',
            aggregateType: 'task',
            aggregateId: taskId,
            payload: { title: updated.title },
          });

          return updated;
        });

        sendSuccess(reply, requestCtx, result, { revision: result.revision });
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  // LIFECYCLE COMMANDS: approve, queue, cancel
  const lifecycleCommands = ['approve', 'queue', 'cancel'] as const;

  for (const command of lifecycleCommands) {
    const targetState: Record<string, TaskState> = {
      approve: 'approved',
      queue: 'queued',
      cancel: 'cancelled',
    };

    const eventTypeMap: Record<string, string> = {
      approve: 'task.approved',
      queue: 'task.queued',
      cancel: 'task.cancelled',
    };

    app.post<{ Params: { taskId: string } }>(
      `/api/v1/tasks/:taskId/${command}`,
      async (request, reply) => {
        const principal = resolvePrincipal(request.headers);
        const requestCtx = createRequestContext(principal);

        try {
          const { taskId } = request.params;
          const workspaceId = principal.workspaceId;
          const idempotencyKey = request.headers['idempotency-key'] as string | undefined;

          const result = await withTenantTransaction(workspaceId, async (tx) => {
            // Idempotency check for lifecycle commands
            if (idempotencyKey) {
              const fp = fingerprintRequest('POST', `/api/v1/tasks/${taskId}/${command}`, {});
              const existing = await getIdempotencyResult(tx.client, idempotencyKey, workspaceId, fp);
              if (existing.found) {
                if (existing.sameRequest) return { cached: true as const, task: existing.result };
                return { conflict: true as const };
              }
            }

            const existing = await tx.client.query(`SELECT ${TASK_COLUMNS} FROM work.tasks WHERE id = $1`, [taskId]);
            if (existing.rows.length === 0) throw notFoundError(`Task ${taskId} not found`);

            const task = existing.rows[0];
            const currentState = task.state as TaskState;
            const target = targetState[command];

            // Validate transition
            if (!canTransitionTask(currentState, target)) {
              throw controlApiError(
                'INVALID_TASK_TRANSITION',
                `Cannot transition task from "${currentState}" to "${target}"`,
                422,
              );
            }

            const newRevision = incrementRevision(task.revision as string);
            const now = new Date().toISOString();

            const updateResult = await tx.client.query(
              `UPDATE work.tasks SET state = $1, revision = $2::bigint, base_revision = $2::bigint, updated_at = $3
               WHERE id = $4
               RETURNING ${TASK_COLUMNS}`,
              [target, newRevision, now, taskId],
            );

            const updated = updateResult.rows[0];

            await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
              projectId: updated.project_id,
              eventType: eventTypeMap[command],
              aggregateType: 'task',
              aggregateId: taskId,
              payload: { from_state: currentState, to_state: target },
            });

            if (idempotencyKey) {
              const fp = fingerprintRequest('POST', `/api/v1/tasks/${taskId}/${command}`, {});
              await claimIdempotencyKey(tx.client, idempotencyKey, workspaceId, fp, updated);
            }

            return { cached: false as const, task: updated };
          });

          if (result.conflict) {
            reply.code(409).send({
              error: { code: 'IDEMPOTENCY_CONFLICT', message: 'Idempotency key already used with a different request', request_id: requestCtx.requestId },
            });
            return;
          }

          if (result.cached) {
            sendSuccess(reply, requestCtx, result.task, { revision: (result.task as Record<string, unknown>).revision as string, statusCode: 200 });
            return;
          }

          sendSuccess(reply, requestCtx, result.task, { revision: result.task.revision });
        } catch (e) {
          sendError(reply, requestCtx, e);
        }
      },
    );
  }
}
