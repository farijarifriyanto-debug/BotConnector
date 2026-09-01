import type { PoolClient } from 'pg';
import { createHash } from 'node:crypto';

export interface IdempotencyCheckResult {
  exists: boolean;
  operation?: string;
  result?: unknown;
}

export function fingerprintRequest(method: string, path: string, body: unknown): string {
  const payload = JSON.stringify({ method, path, body });
  return createHash('sha256').update(payload).digest('hex');
}

export async function checkIdempotencyKey(
  client: PoolClient,
  key: string,
  workspaceId: string,
): Promise<IdempotencyCheckResult> {
  const { rows } = await client.query(
    `SELECT operation, result FROM ops.idempotency_keys WHERE id = $1 AND workspace_id = $2`,
    [key, workspaceId],
  );

  if (rows.length === 0) {
    return { exists: false };
  }

  return {
    exists: true,
    operation: rows[0].operation,
    result: rows[0].result,
  };
}

export async function claimIdempotencyKey(
  client: PoolClient,
  key: string,
  workspaceId: string,
  fingerprint: string,
  result: unknown,
  ttlSeconds: number = 3600,
): Promise<void> {
  await client.query(
    `INSERT INTO ops.idempotency_keys (id, workspace_id, operation, result, expires_at)
     VALUES ($1, $2, $3, $4, now() + interval '${ttlSeconds} seconds')`,
    [key, workspaceId, fingerprint, JSON.stringify(result)],
  );
}

export async function getIdempotencyResult<T = unknown>(
  client: PoolClient,
  key: string,
  workspaceId: string,
  expectedFingerprint: string,
): Promise<{ found: true; result: T; sameRequest: boolean } | { found: false }> {
  const check = await checkIdempotencyKey(client, key, workspaceId);

  if (!check.exists) {
    return { found: false };
  }

  const sameRequest = check.operation === expectedFingerprint;

  return { found: true, result: check.result as T, sameRequest };
}
