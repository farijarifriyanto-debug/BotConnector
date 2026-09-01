import type { TenantTransaction } from '../db/tenant.js';
import { incrementRevision } from '../db/concurrency.js';
import { emitDomainEventForMutation } from '../events/service.js';
import { canTransitionGenerationRun, isExecutorOnlyTransition } from './state-machine.js';
import type { PrincipalContext } from '../request-context/index.js';
import { controlApiError } from '../errors/index.js';
import type { z } from 'zod';
import type { GenerationStateSchema } from '@botconnector/contracts';

type GenerationState = z.infer<typeof GenerationStateSchema>;

const RUN_COLUMNS = `id, project_id, task_id, state, revision, base_revision, started_at, ended_at`;

export interface AckResult {
  run: Record<string, unknown>;
}

/**
 * Internal executor acknowledgement for GenerationRun safe-point transitions.
 *
 * pausing → paused
 * stopping → stopped
 *
 * Must be called inside a tenant transaction. Validates:
 *  - expected_from matches current state
 *  - transition is executor-only
 *  - revision is incremented
 *  - exactly one domain event + outbox row emitted
 *  - stale/invalid ack rejected without event
 */
export async function ackGenerationRun(
  tx: TenantTransaction,
  principal: PrincipalContext,
  requestId: string,
  runId: string,
  expectedFrom: 'pausing' | 'stopping',
): Promise<AckResult> {
  const targetState: GenerationState = expectedFrom === 'pausing' ? 'paused' : 'stopped';

  const existing = await tx.client.query(
    `SELECT ${RUN_COLUMNS} FROM ai.generation_runs WHERE id = $1`,
    [runId],
  );
  if (existing.rows.length === 0) {
    throw controlApiError('NOT_FOUND', `Generation run ${runId} not found`, 404);
  }

  const run = existing.rows[0];
  const currentState = run.state as GenerationState;

  if (currentState !== expectedFrom) {
    throw controlApiError(
      'INVALID_GENERATION_RUN_TRANSITION',
      `Expected generation run in state "${expectedFrom}" but found "${currentState}"`,
      422,
    );
  }

  if (!isExecutorOnlyTransition(currentState, targetState)) {
    throw controlApiError(
      'INVALID_GENERATION_RUN_TRANSITION',
      `State "${currentState}" to "${targetState}" is not an executor-acknowledged transition`,
      422,
    );
  }

  const newRevision = incrementRevision(run.revision as string);
  const now = new Date().toISOString();

  const updateResult = await tx.client.query(
    `UPDATE ai.generation_runs
     SET state = $1, revision = $2::bigint, base_revision = $2::bigint,
         ended_at = CASE WHEN $1 IN ('stopped','completed','failed') THEN $3 ELSE ended_at END
     WHERE id = $4
     RETURNING ${RUN_COLUMNS}`,
    [targetState, newRevision, now, runId],
  );

  const updated = updateResult.rows[0];

  const eventType = targetState === 'paused' ? 'generation_run.paused' : 'generation_run.stopped';

  await emitDomainEventForMutation(tx, principal, requestId, {
    projectId: updated.project_id,
    eventType,
    aggregateType: 'generation_run',
    aggregateId: runId,
    payload: { from_state: currentState, to_state: targetState },
  });

  return { run: updated };
}
