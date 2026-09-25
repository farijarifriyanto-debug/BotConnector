import test from "node:test";
import assert from "node:assert/strict";
import { buildExactResponseCacheKey } from "../src/cache-key.ts";

const base = {
  tenantId: "tenant-a",
  canonicalModelId: "laguna-s-2.1",
  providerId: "nararouter",
  providerModelId: "laguna-s-2.1",
  modelVersion: "2026-09",
  policyVersion: "p1",
  responseMode: "non-stream",
  messages: [{ role: "user", content: "hello" }],
  tools: [{ name: "x", schema: { b: 2, a: 1 } }],
  temperature: 0,
};

test("exact cache key is deterministic across object key ordering", () => {
  const a = buildExactResponseCacheKey(base);
  const b = buildExactResponseCacheKey({
    ...base,
    tools: [{ schema: { a: 1, b: 2 }, name: "x" }],
  });
  assert.equal(a, b);
  assert.match(a, /^bc:exact:v1:[a-f0-9]{64}$/);
});

test("tenant, model version, provider and response mode isolate cache entries", () => {
  const original = buildExactResponseCacheKey(base);
  for (const mutation of [
    { tenantId: "tenant-b" },
    { modelVersion: "2026-10" },
    { providerId: "poolside" },
    { responseMode: "stream" },
  ]) {
    assert.notEqual(buildExactResponseCacheKey({ ...base, ...mutation }), original);
  }
});
