import { createClient, type RedisClientType } from "redis";

export type RedisCacheEntry<T> = {
  value: T;
  createdAtMs: number;
  expiresAtMs: number;
  hitCount: number;
};

type StoredEntry<T> = {
  value: T;
  createdAtMs: number;
  expiresAtMs: number;
};

export class RedisExactResponseCache<T> {
  readonly url: string;
  #client: RedisClientType | null = null;

  constructor(url = process.env.BOTCONNECTOR_REDIS_URL?.trim() || "redis://127.0.0.1:16379/0") {
    this.url = url;
  }

  async connect(): Promise<void> {
    if (this.#client?.isOpen) return;
    const client = createClient({
      url: this.url,
      socket: {
        connectTimeout: 1_000,
        reconnectStrategy: false,
      },
    });
    client.on("error", () => {});
    await client.connect();
    this.#client = client as RedisClientType;
  }

  async close(): Promise<void> {
    if (!this.#client?.isOpen) return;
    await this.#client.quit();
    this.#client = null;
  }

  async ping(): Promise<string> {
    await this.connect();
    return this.#client!.ping();
  }

  async get(key: string, nowMs = Date.now()): Promise<RedisCacheEntry<T> | null> {
    await this.connect();
    const raw = await this.#client!.get(key);
    if (!raw) return null;
    let stored: StoredEntry<T>;
    try {
      stored = JSON.parse(raw) as StoredEntry<T>;
    } catch {
      await this.#client!.del(key);
      return null;
    }
    if (!Number.isFinite(stored.expiresAtMs) || stored.expiresAtMs <= nowMs) {
      await this.#client!.del(key);
      return null;
    }
    const hitsKey = key + ":hits";
    const hitCount = await this.#client!.incr(hitsKey);
    const ttlMs = Math.max(1, stored.expiresAtMs - nowMs);
    await this.#client!.pExpire(hitsKey, ttlMs);
    return { ...stored, hitCount };
  }

  async set(key: string, value: T, ttlSeconds: number, nowMs = Date.now()): Promise<void> {
    if (!key.trim()) throw new Error("CACHE_KEY_REQUIRED");
    if (!Number.isSafeInteger(ttlSeconds) || ttlSeconds <= 0) throw new Error("CACHE_TTL_INVALID");
    await this.connect();
    const expiresAtMs = nowMs + ttlSeconds * 1000;
    const stored: StoredEntry<T> = { value, createdAtMs: nowMs, expiresAtMs };
    await this.#client!.set(key, JSON.stringify(stored), { EX: ttlSeconds });
    await this.#client!.del(key + ":hits");
  }

  async delete(key: string): Promise<boolean> {
    await this.connect();
    const deleted = await this.#client!.del([key, key + ":hits"]);
    return deleted > 0;
  }
}
