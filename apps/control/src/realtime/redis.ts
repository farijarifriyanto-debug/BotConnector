import { Redis } from 'ioredis';
import type { DomainEvent } from '@botconnector/contracts';

/**
 * Redis is TRANSIENT DELIVERY / FANOUT ONLY. It is never the canonical event
 * source; durable history lives in event.domain_events (PostgreSQL).
 *
 * Channel naming is internal to the server — clients never supply channel
 * names. Redis channel naming is NOT a security boundary; authorization is
 * enforced per connection before delivery.
 */
export function eventChannel(workspaceId: string, projectId: string): string {
  return `botconnector:events:${workspaceId}:${projectId}`;
}

const ALL_CHANNELS_PATTERN = 'botconnector:events:*';

export interface TransientRedis {
  publishEvent(workspaceId: string, projectId: string, event: DomainEvent): Promise<void>;
  subscribePattern(handler: (channel: string, event: DomainEvent) => void): Promise<() => Promise<void>>;
  close(): Promise<void>;
}

function createRedisClient(redisUrl: string): Redis {
  const client = new Redis(redisUrl, {
    maxRetriesPerRequest: 2,
    retryStrategy: (times) => Math.min(times * 200, 2000),
    lazyConnect: true,
  });
  // Transient fanout: connection errors are expected during outages and are
  // handled by callers; never let them surface as unhandled error events.
  client.on('error', () => {});
  return client;
}

async function waitForReady(client: Redis, timeoutMs = 5000): Promise<void> {
  if (client.status === 'ready') {
    return;
  }
  if (client.status === 'connecting' || client.status === 'connect') {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        client.removeListener('ready', onReady);
        reject(new Error('redis connect timed out'));
      }, timeoutMs);
      const onReady = () => {
        clearTimeout(timer);
        resolve();
      };
      client.once('ready', onReady);
    });
    return;
  }
  await client.connect();
}

export function createTransientRedis(redisUrl: string): TransientRedis {
  const pub = createRedisClient(redisUrl);
  const sub = createRedisClient(redisUrl);

  return {
    async publishEvent(workspaceId: string, projectId: string, event: DomainEvent) {
      await waitForReady(pub);
      await pub.publish(
        eventChannel(workspaceId, projectId),
        JSON.stringify({ type: 'domain_event', version: 1, event }),
      );
    },

    async subscribePattern(handler) {
      await waitForReady(sub);
      await sub.psubscribe(ALL_CHANNELS_PATTERN);
      sub.on('pmessage', (_pattern, channel, message) => {
        try {
          const parsed = JSON.parse(message);
          if (parsed?.type !== 'domain_event' || !parsed?.event) {
            return;
          }
          handler(channel, parsed.event as DomainEvent);
        } catch {
          // malformed transient message: ignore, never crash the gateway
        }
      });
      return async () => {
        try {
          await sub.punsubscribe(ALL_CHANNELS_PATTERN);
        } catch {
          // already closed or disconnected
        }
      };
    },

    async close() {
      // disconnect() is immediate; quit() can hang while retrying a dead server
      try {
        pub.disconnect();
      } catch {
        // already closed
      }
      try {
        sub.disconnect();
      } catch {
        // already closed
      }
    },
  };
}