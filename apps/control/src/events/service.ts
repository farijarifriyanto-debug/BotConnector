import { randomUUID } from 'node:crypto';
import { DomainEventSchema, type DomainEvent, type JsonValue } from '@botconnector/contracts';
import type { PoolClient } from 'pg';
import type { TenantTransaction } from '../db/tenant.js';
import type { PrincipalContext } from '../request-context/index.js';

export interface EmitDomainEventParams {
  workspaceId: string;
  projectId: string;
  eventType: string;
  aggregateType: string;
  aggregateId: string;
  actorType: 'user' | 'agent' | 'system';
  actorId: string;
  correlationId: string;
  causationId: string | null;
  payload: JsonValue;
  eventVersion?: number;
}

export interface DomainEventRow {
  id: string;
  workspace_id: string;
  project_id: string;
  event_type: string;
  aggregate_type: string;
  aggregate_id: string;
  payload: unknown;
  sequence: string;
  event_version: number;
  correlation_id: string;
  causation_id: string | null;
  actor_type: string;
  actor_id: string;
  timestamp: string;
  created_at: string;
}

const DOMAIN_EVENT_COLUMNS = `
  id, workspace_id, project_id, event_type, aggregate_type, aggregate_id,
  payload, sequence, event_version, correlation_id, causation_id,
  actor_type, actor_id, timestamp, created_at
`;

/**
 * Allocate the next atomic project sequence inside an open tenant transaction.
 * Uses event.project_sequences upsert (row-lock serialized, concurrent-safe).
 * Sequence starts at 1 (0 reserved as "before first event" sentinel).
 */
export async function allocateProjectSequence(
  client: PoolClient,
  workspaceId: string,
  projectId: string,
): Promise<string> {
  const { rows } = await client.query(
    `INSERT INTO event.project_sequences (workspace_id, project_id, current_value)
     VALUES ($1, $2, 1)
     ON CONFLICT (workspace_id, project_id)
     DO UPDATE SET current_value = event.project_sequences.current_value + 1, updated_at = now()
     RETURNING current_value`,
    [workspaceId, projectId],
  );
  return String(rows[0].current_value);
}

function toDomainEvent(row: DomainEventRow): DomainEvent {
  return {
    // Contract version literal is 1; DB event_version is asserted 1 at write.
    version: 1 as const,
    id: row.id,
    type: row.event_type,
    sequence: row.sequence,
    project_id: row.project_id,
    correlation_id: row.correlation_id,
    causation_id: row.causation_id,
    actor: { type: row.actor_type as 'user' | 'agent' | 'system', id: row.actor_id },
    timestamp:
      typeof row.timestamp === 'string'
        ? row.timestamp
        : new Date(row.timestamp).toISOString(),
    payload: row.payload as JsonValue,
  };
}

/**
 * Emit a durable domain event + outbox row inside the SAME transaction as the
 * domain mutation. Atomic: on commit both persist; on rollback neither does.
 * No Redis I/O happens here.
 */
export async function emitDomainEvent(
  tx: TenantTransaction,
  params: EmitDomainEventParams,
): Promise<DomainEvent> {
  const sequence = await allocateProjectSequence(tx.client, params.workspaceId, params.projectId);

  const eventId = randomUUID();
  const timestamp = new Date().toISOString();
  const eventVersion = params.eventVersion ?? 1;
  if (eventVersion !== 1) {
    throw new Error('Only event contract version 1 is supported');
  }

  const inserted = await tx.client.query(
    `INSERT INTO event.domain_events
       (id, workspace_id, project_id, event_type, aggregate_type, aggregate_id,
        payload, sequence, event_version, correlation_id, causation_id,
        actor_type, actor_id, timestamp)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
     RETURNING ${DOMAIN_EVENT_COLUMNS}`,
    [
      eventId,
      params.workspaceId,
      params.projectId,
      params.eventType,
      params.aggregateType,
      params.aggregateId,
      JSON.stringify(params.payload),
      sequence,
      eventVersion,
      params.correlationId,
      params.causationId,
      params.actorType,
      params.actorId,
      timestamp,
    ],
  );

  const outboxId = randomUUID();
  await tx.client.query(
    `INSERT INTO event.outbox (id, workspace_id, project_id, event_id)
     VALUES ($1, $2, $3, $4)`,
    [outboxId, params.workspaceId, params.projectId, eventId],
  );

  return DomainEventSchema.parse(toDomainEvent(inserted.rows[0]));
}

/**
 * Read canonical domain events after a given project sequence, ascending.
 * Must run inside a tenant transaction so RLS scopes to the workspace.
 * Returns bigint-safe decimal-string sequences (no Number conversion).
 */
export async function replayDomainEventsAfter(
  tx: TenantTransaction,
  projectId: string,
  afterSequence: string,
  limit = 1000,
): Promise<DomainEvent[]> {
  const { rows } = await tx.client.query(
    `SELECT ${DOMAIN_EVENT_COLUMNS}
     FROM event.domain_events
     WHERE project_id = $1 AND sequence::bigint > $2::bigint
     ORDER BY sequence ASC
     LIMIT $3`,
    [projectId, afterSequence, limit],
  );
  return rows.map((r) => DomainEventSchema.parse(toDomainEvent(r)));
}

/** Current durable high-water project sequence (0 when project has none yet). */
export async function getProjectHighWaterSequence(
  tx: TenantTransaction,
  projectId: string,
): Promise<string> {
  const { rows } = await tx.client.query(
    `SELECT current_value FROM event.project_sequences WHERE project_id = $1`,
    [projectId],
  );
  if (rows.length === 0) {
    return '0';
  }
  // current_value == last allocated (committed) sequence
  return String(rows[0].current_value);
}

/** Load a single canonical domain event by id within a tenant transaction. */
export async function loadDomainEventById(
  tx: TenantTransaction,
  eventId: string,
): Promise<DomainEvent | null> {
  const { rows } = await tx.client.query(
    `SELECT ${DOMAIN_EVENT_COLUMNS} FROM event.domain_events WHERE id = $1`,
    [eventId],
  );
  if (rows.length === 0) {
    return null;
  }
  return DomainEventSchema.parse(toDomainEvent(rows[0]));
}

/**
 * Convenience wrapper for Phase-3 mutation routes: fills actor + correlation
 * from the trusted principal and request id. Must be called inside the SAME
 * tenant transaction as the domain mutation.
 */
export async function emitDomainEventForMutation(
  tx: TenantTransaction,
  principal: PrincipalContext,
  requestId: string,
  params: Omit<
    EmitDomainEventParams,
    'workspaceId' | 'actorType' | 'actorId' | 'correlationId' | 'causationId'
  >,
): Promise<DomainEvent> {
  return emitDomainEvent(tx, {
    ...params,
    workspaceId: principal.workspaceId,
    actorType: principal.userId === 'system' ? 'system' : 'user',
    actorId: principal.userId,
    correlationId: requestId,
    causationId: null,
  });
}
