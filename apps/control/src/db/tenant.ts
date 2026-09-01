import type { PoolClient } from 'pg';

export interface TenantTransaction {
  client: PoolClient;
  workspaceId: string;
  commit: () => Promise<void>;
  rollback: () => Promise<void>;
}

export async function beginTenantTransaction(
  client: PoolClient,
  workspaceId: string,
): Promise<TenantTransaction> {
  await client.query('BEGIN');
  await client.query(
    `SELECT set_config('app.workspace_id', $1, true)`,
    [workspaceId],
  );
  await client.query('SET LOCAL ROLE application_role');

  return {
    client,
    workspaceId,
    commit: async () => {
      await client.query('RESET ROLE');
      await client.query('COMMIT');
    },
    rollback: async () => {
      try {
        await client.query('RESET ROLE');
      } catch {
        // transaction may already be broken
      }
      try {
        await client.query('ROLLBACK');
      } catch {
        // already rolled back
      }
    },
  };
}

export async function withTenantTransaction<T>(
  workspaceId: string,
  fn: (tx: TenantTransaction) => Promise<T>,
): Promise<T> {
  const { getPool } = await import('./pool.js');
  const pool = getPool();
  const client = await pool.connect();
  let released = false;

  const release = () => {
    if (!released) {
      released = true;
      client.release();
    }
  };

  try {
    const tx = await beginTenantTransaction(client, workspaceId);
    try {
      const result = await fn(tx);
      await tx.commit();
      return result;
    } catch (e) {
      await tx.rollback();
      throw e;
    } finally {
      release();
    }
  } catch (e) {
    release();
    throw e;
  }
}
