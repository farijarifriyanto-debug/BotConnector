import type { FastifyInstance } from 'fastify';
import { randomUUID } from 'node:crypto';
import { validationError, notFoundError, controlApiError } from '../errors/index.js';
import { sendSuccess, sendCreated, sendError } from '../errors/response.js';
import { createRequestContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import { parseIfMatch, assertRevisionMatch, incrementRevision } from '../db/concurrency.js';
import { emitDomainEventForMutation } from '../events/service.js';
import type { PrincipalResolver } from '../index.js';

const FOCUS_LOCK_COLUMNS = `id, project_id, task_id, scope, owner_id, revision, base_revision, acquired_at, expires_at`;

interface AcquireFocusLockBody {
  task_id: string;
  scope: string;
  owner_id: string;
  expires_in_seconds?: number;
}

function validateAcquireFocusLock(body: unknown): AcquireFocusLockBody {
  if (!body || typeof body !== 'object') throw validationError('Request body is required');
  const b = body as Record<string, unknown>;
  if (typeof b.task_id !== 'string' || b.task_id.trim().length === 0) throw validationError('task_id is required');
  if (typeof b.scope !== 'string' || b.scope.trim().length === 0) throw validationError('scope is required');
  if (typeof b.owner_id !== 'string' || b.owner_id.trim().length === 0) throw validationError('owner_id is required');
  if (b.expires_in_seconds !== undefined && (typeof b.expires_in_seconds !== 'number' || b.expires_in_seconds <= 0)) {
    throw validationError('expires_in_seconds must be a positive number');
  }
  return {
    task_id: b.task_id.trim(),
    scope: b.scope.trim(),
    owner_id: b.owner_id.trim(),
    expires_in_seconds: typeof b.expires_in_seconds === 'number' ? b.expires_in_seconds : undefined,
  };
}

export async function registerFocusLockRoutes(app: FastifyInstance, resolvePrincipal: PrincipalResolver): Promise<void> {
  // ACQUIRE focus lock
  app.post<{ Params: { projectId: string }; Body: AcquireFocusLockBody }>(
    '/api/v1/projects/:projectId/focus-locks',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { projectId } = request.params;
        const body = validateAcquireFocusLock(request.body);
        const workspaceId = principal.workspaceId;

        const result = await withTenantTransaction(workspaceId, async (tx) => {
          // Serialize acquisition on project row to prevent future-expiry race
          // (partial unique index only covers expires_at IS NULL)
          const projLock = await tx.client.query(
            `SELECT id FROM core.projects WHERE id = $1 FOR UPDATE`,
            [projectId],
          );
          if (projLock.rows.length === 0) throw notFoundError(`Project ${projectId} not found`);

          // Verify task exists and belongs to project
          const taskCheck = await tx.client.query(
            `SELECT id FROM work.tasks WHERE id = $1 AND project_id = $2`,
            [body.task_id, projectId],
          );
          if (taskCheck.rows.length === 0) throw notFoundError(`Task ${body.task_id} not found in project ${projectId}`);

          // Check if an active (non-expired) lock already exists for this project
          const existingActive = await tx.client.query(
            `SELECT id FROM work.focus_locks
             WHERE project_id = $1
               AND (expires_at IS NULL OR expires_at > now())`,
            [projectId],
          );

          if (existingActive.rows.length > 0) {
            throw controlApiError(
              'FOCUS_LOCK_CONFLICT',
              `A focus lock already exists for project ${projectId}`,
              409,
            );
          }

          const lockId = randomUUID();
          const now = new Date().toISOString();
          const expiresAt = body.expires_in_seconds
            ? new Date(Date.now() + body.expires_in_seconds * 1000).toISOString()
            : null;

          let lock: Record<string, unknown>;
          try {
            const insertResult = await tx.client.query(
              `INSERT INTO work.focus_locks (id, project_id, workspace_id, task_id, scope, owner_id, revision, base_revision, acquired_at, expires_at)
               VALUES ($1, $2, $3, $4, $5, $6, '0', '0', $7, $8)
               RETURNING ${FOCUS_LOCK_COLUMNS}`,
              [lockId, projectId, workspaceId, body.task_id, body.scope, body.owner_id, now, expiresAt],
            );
            lock = insertResult.rows[0];
          } catch (err: unknown) {
            // Map DB unique_violation (23505) from partial index to domain error
            if (err && typeof err === 'object' && 'code' in err && (err as { code: string }).code === '23505') {
              throw controlApiError(
                'FOCUS_LOCK_CONFLICT',
                `A focus lock already exists for project ${projectId}`,
                409,
              );
            }
            throw err;
          }

          await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
            projectId,
            eventType: 'focus_lock.acquired',
            aggregateType: 'focus_lock',
            aggregateId: lockId,
            payload: { task_id: body.task_id, scope: body.scope, owner_id: body.owner_id },
          });

          return lock;
        });

        sendCreated(reply, requestCtx, result, { revision: (result as Record<string, unknown>).revision as string });
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  // LIST focus locks for project
  app.get<{ Params: { projectId: string } }>(
    '/api/v1/projects/:projectId/focus-locks',
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
            `SELECT ${FOCUS_LOCK_COLUMNS} FROM work.focus_locks WHERE project_id = $1 ORDER BY acquired_at DESC`,
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

  // GET focus lock
  app.get<{ Params: { lockId: string } }>(
    '/api/v1/focus-locks/:lockId',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { lockId } = request.params;
        const workspaceId = principal.workspaceId;

        const rows = await withTenantTransaction(workspaceId, async (tx) => {
          const result = await tx.client.query(
            `SELECT ${FOCUS_LOCK_COLUMNS} FROM work.focus_locks WHERE id = $1`,
            [lockId],
          );
          return result.rows;
        });

        if (rows.length === 0) throw notFoundError(`Focus lock ${lockId} not found`);
        sendSuccess(reply, requestCtx, rows[0], { revision: rows[0].revision });
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );

  // RELEASE focus lock
  app.post<{ Params: { lockId: string } }>(
    '/api/v1/focus-locks/:lockId/release',
    async (request, reply) => {
      const principal = resolvePrincipal(request.headers);
      const requestCtx = createRequestContext(principal);

      try {
        const { lockId } = request.params;
        const workspaceId = principal.workspaceId;

        const result = await withTenantTransaction(workspaceId, async (tx) => {
          const existing = await tx.client.query(
            `SELECT ${FOCUS_LOCK_COLUMNS} FROM work.focus_locks WHERE id = $1`,
            [lockId],
          );
          if (existing.rows.length === 0) throw notFoundError(`Focus lock ${lockId} not found`);

          const lock = existing.rows[0];

          // Delete the lock (release = remove)
          await tx.client.query(`DELETE FROM work.focus_locks WHERE id = $1`, [lockId]);

          await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
            projectId: lock.project_id,
            eventType: 'focus_lock.released',
            aggregateType: 'focus_lock',
            aggregateId: lockId,
            payload: { task_id: lock.task_id, scope: lock.scope, owner_id: lock.owner_id },
          });

          return lock;
        });

        sendSuccess(reply, requestCtx, result);
      } catch (e) {
        sendError(reply, requestCtx, e);
      }
    },
  );
}
