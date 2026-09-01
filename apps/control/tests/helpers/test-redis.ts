import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Redis } from 'ioredis';

export interface TestRedisHandle {
  port: number;
  url: string;
  /** Stop the process (simulated outage). Data dir is preserved. */
  stop(): Promise<void>;
  /** Start a fresh process on the same port/dir (recovery). */
  restart(): Promise<void>;
  ping(): Promise<boolean>;
  /** Final cleanup: stop process and remove the temp dir. */
  cleanup(): Promise<void>;
}

const REDIS_BIN = process.env.REDIS_TEST_BIN || '/usr/bin/redis-server';

/**
 * Isolated disposable test Redis: dedicated process, dedicated port, temp dir.
 * Never touches the system/shared Redis on 6379. No persistence enabled.
 */
export async function spawnTestRedis(port = 6380): Promise<TestRedisHandle> {
  const dir = mkdtempSync(join(tmpdir(), 'botconnector-redis-test-'));

  function launch(): ChildProcess {
    return spawn(
      REDIS_BIN,
      [
        '--port', String(port),
        '--bind', '127.0.0.1',
        '--dir', dir,
        '--save', '',
        '--appendonly', 'no',
        '--daemonize', 'no',
      ],
      { stdio: 'ignore' },
    );
  }

  let child = launch();

  async function waitExit(timeoutMs = 5000): Promise<void> {
    if (child.exitCode !== null) {
      return;
    }
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, timeoutMs);
      child.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }

  async function waitReady(timeoutMs = 8000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const probe = new Redis(`redis://127.0.0.1:${port}`, {
          lazyConnect: true,
          maxRetriesPerRequest: 1,
          retryStrategy: () => null,
        });
        await probe.connect();
        await probe.ping();
        await probe.quit();
        return;
      } catch {
        await new Promise((r) => setTimeout(r, 150));
      }
    }
    throw new Error(`test redis on port ${port} did not become ready`);
  }

  await waitReady();

  return {
    port,
    url: `redis://127.0.0.1:${port}`,
    async stop() {
      try {
        child.kill('SIGTERM');
      } catch {
        // already dead
      }
      await waitExit();
    },
    async restart() {
      child = launch();
      await waitReady();
    },
    async ping() {
      try {
        const probe = new Redis(`redis://127.0.0.1:${port}`, {
          lazyConnect: true,
          maxRetriesPerRequest: 1,
          retryStrategy: () => null,
        });
        await probe.connect();
        const pong = await probe.ping();
        await probe.quit();
        return pong === 'PONG';
      } catch {
        return false;
      }
    },
    async cleanup() {
      try {
        child.kill('SIGTERM');
      } catch {
        // already dead
      }
      await waitExit();
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {
        // already removed
      }
    },
  };
}