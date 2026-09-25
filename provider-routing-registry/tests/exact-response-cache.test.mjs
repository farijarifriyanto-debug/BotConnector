import test from "node:test";
import assert from "node:assert/strict";
import { buildExactResponseCacheKey } from "../src/cache-key.ts";
import { InMemoryExactResponseCache } from "../src/exact-response-cache.ts";

const keyFor = (tenantId) => buildExactResponseCacheKey({
  tenantId,
  canonicalModelId: "laguna-s-2.1",
  providerId: "nararouter",
  providerModelId: "laguna-s-2.1",
  modelVersion: "v1",
  policyVersion: "p1",
  responseMode: "non-stream",
  messages: [{ role: "user", content: "same request" }],
});

test("exact response cache serves a hit without an upstream call", () => {
  const cache = new InMemoryExactResponseCache();
  const key = keyFor("tenant-a");
  let upstreamCalls = 0;
  const now = 1000;

  const miss = cache.get(key, now);
  assert.equal(miss, null);
  upstreamCalls += 1;
  cache.set(key, { answer: "cached" }, 60, now);

  const hit = cache.get(key, now + 1);
  assert.deepEqual(hit?.value, { answer: "cached" });
  assert.equal(hit?.hitCount, 1);
  assert.equal(upstreamCalls, 1);
});

test("TTL expiration and tenant isolation are fail-closed", () => {
  const cache = new InMemoryExactResponseCache();
  const a = keyFor("tenant-a");
  const b = keyFor("tenant-b");
  cache.set(a, "secret-a", 1, 1000);

  assert.equal(cache.get(b, 1500), null);
  assert.equal(cache.get(a, 2001), null);
});
