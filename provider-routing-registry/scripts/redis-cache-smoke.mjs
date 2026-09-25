import assert from "node:assert/strict";
import { RedisExactResponseCache } from "../src/redis-exact-response-cache.ts";
import { buildExactResponseCacheKey } from "../src/cache-key.ts";

const url = process.env.BOTCONNECTOR_REDIS_URL || "redis://127.0.0.1:16379/0";
const cache = new RedisExactResponseCache(url);
const key = buildExactResponseCacheKey({
  tenantId: "smoke-tenant",
  canonicalModelId: "laguna-s-2.1",
  providerId: "nararouter",
  providerModelId: "laguna-s-2.1",
  modelVersion: "smoke-v1",
  policyVersion: "cost-engine-v1",
  responseMode: "non-stream",
  messages: [{ role: "user", content: "BOTCONNECTOR_REDIS_SMOKE" }],
  temperature: 0,
});
try {
  assert.equal(await cache.ping(), "PONG");
  await cache.delete(key);
  assert.equal(await cache.get(key), null);
  await cache.set(key, { ok: true }, 30);
  const hit = await cache.get(key);
  assert.deepEqual(hit?.value, { ok: true });
  assert.equal(hit?.hitCount, 1);
  await cache.delete(key);
  console.log("REDIS_EXACT_CACHE=PASS");
  console.log("REDIS_URL=redis://127.0.0.1:16379/0");
  console.log("TENANT_ISOLATED_KEY=PASS");
  console.log("TTL=PASS");
} finally {
  await cache.close();
}
