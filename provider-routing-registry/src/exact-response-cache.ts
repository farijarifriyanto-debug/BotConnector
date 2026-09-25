export type ExactCacheEntry<T> = {
  value: T;
  createdAtMs: number;
  expiresAtMs: number;
  hitCount: number;
};

export interface ExactResponseCache<T> {
  get(key: string, nowMs?: number): ExactCacheEntry<T> | null;
  set(key: string, value: T, ttlSeconds: number, nowMs?: number): void;
  delete(key: string): boolean;
  clear(): void;
}

export class InMemoryExactResponseCache<T> implements ExactResponseCache<T> {
  #entries = new Map<string, ExactCacheEntry<T>>();

  get(key: string, nowMs = Date.now()): ExactCacheEntry<T> | null {
    const entry = this.#entries.get(key);
    if (!entry) return null;
    if (entry.expiresAtMs <= nowMs) {
      this.#entries.delete(key);
      return null;
    }
    entry.hitCount += 1;
    return { ...entry };
  }

  set(key: string, value: T, ttlSeconds: number, nowMs = Date.now()): void {
    if (!key.trim()) throw new Error("CACHE_KEY_REQUIRED");
    if (!Number.isSafeInteger(ttlSeconds) || ttlSeconds <= 0) throw new Error("CACHE_TTL_INVALID");
    this.#entries.set(key, {
      value,
      createdAtMs: nowMs,
      expiresAtMs: nowMs + ttlSeconds * 1000,
      hitCount: 0,
    });
  }

  delete(key: string): boolean {
    return this.#entries.delete(key);
  }

  clear(): void {
    this.#entries.clear();
  }
}
