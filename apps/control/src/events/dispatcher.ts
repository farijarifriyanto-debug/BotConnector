import { randomUUID } from 'node:crypto';
import type { DomainEvent } from '@botconnector/contracts';
import type { TransientRedis } from '../realtime/redis.js';
import { withTenantTransaction } from '../db/tenant.js';
import { loadDomainEventById, type DomainEventRow } from './service.js';

const LEASE_TTL_MS = 30_000;
// Backoff is capped, not delivery lifetime: a prolonged Redis outage must
// never permanently orphan an otherwise valid outbox event. attempt_count
// keeps increasing while the retry delay stays capped at MAX_BACKOFF_MS.
const BASE_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 60_000;

interface ClaimedItem {
  outboxId: string;
  workspaceId: string;
  projectId: string;
  eventId: string;
  leaseToken: string;
  event: DomainEvent | null;
}

/**
 * Claim at most `batch` eligible outbox rows for one workspace inside a tenant
 * transaction (RLS-scoped). A claimed row gets a unique lease token + expiry.
 * The transaction is committed before any Redis I/O.
 */
async function claimBatchForWorkspace(
  workspaceId: string,
  batch: number,
): Promise<ClaimedItem[]> {
  const claimed: ClaimedItem[] = [];
  await withTenantTransaction(workspaceId, async (tx) => {
    const { rows } = await tx.client.query(
      `SELECT id, workspace_id, project_id, event_id
       FROM event.outbox
       WHERE dispatched_at IS NULL
         AND (lease_expires_at IS NULL OR lease_expires_at < now())
         AND next_attempt_at <= now()
       ORDER BY created_at ASC
       LIMIT $1`,
      [batch],
    );

    for (const row of rows) {
      const leaseToken = randomUUID();
      const claimedRows = await tx.client.query(
        `UPDATE event.outbox
         SET lease_token = $1,
             lease_expires_at = now() + interval '${LEASE_TTL_MS} milliseconds',
             attempt_count = attempt_count + 1
         WHERE id = $2
           AND (lease_expires_at IS NULL OR lease_expires_at < now())
         RETURNING id`,
        [leaseToken, row.id],
      );
      if (claimedRows.rows.length === 0) {
        continue; // another worker claimed it
      }
      const event = await loadDomainEventById(tx, row.event_id);
      claimed.push({
        outboxId: row.id,
        workspaceId: row.workspace_id,
        projectId: row.project_id,
        eventId: row.event_id,
        leaseToken,
        event,
      });
    }
  });
  return claimed;
}

/** Mark an outbox row dispatched; requires the matching lease token. */
async function markDispatched(
  workspaceId: string,
  outboxId: string,
  leaseToken: string,
): Promise<void> {
  await withTenantTransaction(workspaceId, async (tx) => {
    await tx.client.query(
      `UPDATE event.outbox
       SET dispatched_at = now(),
           lease_token = NULL,
           lease_expires_at = NULL,
           next_attempt_at = now()
       WHERE id = $1 AND lease_token = $2`,
      [outboxId, leaseToken],
    );
  });
}

/** Release a lease and schedule a bounded retry with backoff. */
async function scheduleRetry(
  workspaceId: string,
  outboxId: string,
  leaseToken: string,
  attemptCount: number,
  lastError: string,
): Promise<void> {
  const backoffMs = Math.min(BASE_BACKOFF_MS * 2 ** Math.min(attemptCount, 8), MAX_BACKOFF_MS);
  await withTenantTransaction(workspaceId, async (tx) => {
    await tx.client.query(
      `UPDATE event.outbox
       SET lease_token = NULL,
           lease_expires_at = NULL,
           next_attempt_at = now() + interval '${backoffMs} milliseconds',
           last_error = $1
       WHERE id = $2 AND lease_token = $3`,
      [sanitizeError(lastError).slice(0, 500), outboxId, leaseToken],
    );
  });
}

/** Sanitize error text: strip anything that looks like a credential/URL token. */
function sanitizeError(message: string): string {
  return String(message).replace(/rediss?:\/\/[^@\s]+@/g, 'redis://<redacted>@');
}

export interface OutboxDispatcherOptions {
  redis: TransientRedis;
  batch?: number;
  intervalMs?: number;
}

export class OutboxDispatcher {
  private readonly redis: TransientRedis;
  private readonly batch: number;
  private readonly intervalMs: number;
  private timer: NodeJS.Timeout | null = null;
  private running = false;

  constructor(options: OutboxDispatcherOptions) {
    this.redis = options.redis;
    this.batch = options.batch ?? 50;
    this.intervalMs = options.intervalMs ?? 1000;
  }

  /** One full dispatch cycle across all workspaces (workspace-scoped under RLS). */
  async runOnce(): Promise<{ claimed: number; delivered: number }> {
    const { getPool } = await import('../db/pool.js');
    const pool = getPool();
    const { rows } = await pool.query(`SELECT id FROM core.workspaces ORDER BY id`);
    let claimed = 0;
    let delivered = 0;

    for (const ws of rows) {
      const items = await claimBatchForWorkspace(ws.id, this.batch);
      claimed += items.length;

      for (const item of items) {
        if (!item.event) {
          // canonical event missing: drop the outbox reference (defensive)
          await markDispatched(item.workspaceId, item.outboxId, item.leaseToken);
          delivered += 1;
          continue;
        }

        try {
          // NO DB transaction held during Redis I/O
          await this.redis.publishEvent(item.workspaceId, item.projectId, item.event);
          await markDispatched(item.workspaceId, item.outboxId, item.leaseToken);
          delivered += 1;
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          const attemptCount = await this.readAttemptCount(item.outboxId);
          // Retry forever with capped backoff: an outage must not orphan a
          // valid event. attempt_count grows; delay caps at MAX_BACKOFF_MS.
          await scheduleRetry(item.workspaceId, item.outboxId, item.leaseToken, attemptCount, message);
        }
      }
    }

    return { claimed, delivered };
  }

  private async readAttemptCount(outboxId: string): Promise<number> {
    const { getPool } = await import('../db/pool.js');
    const pool = getPool();
    const { rows } = await pool.query(
      `SELECT attempt_count FROM event.outbox WHERE id = $1`,
      [outboxId],
    );
    return rows.length ? Number(rows[0].attempt_count) : 0;
  }

  start(): void {
    if (this.running) {
      return;
    }
    this.running = true;
    const tick = () => {
      this.runOnce().catch((err) => {
        // never crash the host process; transient Redis/DB errors handled per item
        const message = err instanceof Error ? err.message : String(err);
        // eslint-disable-next-line no-console
        console.error(`[dispatcher] cycle error: ${sanitizeError(message)}`);
      });
    };
    tick();
    this.timer = setInterval(tick, this.intervalMs);
  }

  stop(): void {
    this.running = false;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}

export type { DomainEventRow };
