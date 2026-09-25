import test from "node:test";
import assert from "node:assert/strict";
import { calculateCacheEconomics } from "../src/cache-economics.ts";

test("cache economics separates provider cache savings from logical usage", () => {
  const result = calculateCacheEconomics(
    {
      provider: "alibaba_global",
      providerModelId: "qwen3.8-flash",
      requests: 10,
      logicalInputTokens: 1_000_000,
      uncachedInputTokens: 100_000,
      cachedInputTokens: 900_000,
      cacheWriteTokens: 0,
      outputTokens: 100_000,
      promptProfileRequests: 10,
      staticPrefixRepeatRequests: 8,
    },
    {
      uncachedInputPerMTokensUsd: 0.113,
      cachedInputPerMTokensUsd: 0.014,
      cacheWritePerMTokensUsd: 0.177,
      outputPerMTokensUsd: 0.382,
    },
  );
  assert.ok(Math.abs(result.noCacheEquivalentUsd - 0.1512) < 1e-12);
  assert.ok(Math.abs(result.actualCostUsd - 0.0621) < 1e-12);
  assert.ok(Math.abs(result.providerCacheSavingsUsd - 0.0891) < 1e-12);
  assert.equal(result.providerCacheHitRate, 0.9);
  assert.equal(result.staticPrefixRepeatRate, 0.8);
});

test("unknown cache-read price fails cost attribution closed, not usage metrics", () => {
  const result = calculateCacheEconomics(
    {
      provider: "unknown",
      providerModelId: "m",
      requests: 1,
      logicalInputTokens: 100,
      uncachedInputTokens: 50,
      cachedInputTokens: 50,
      cacheWriteTokens: 0,
      outputTokens: 10,
    },
    {
      uncachedInputPerMTokensUsd: 1,
      cachedInputPerMTokensUsd: null,
      cacheWritePerMTokensUsd: null,
      outputPerMTokensUsd: 2,
    },
  );
  assert.equal(result.actualCostUsd, null);
  assert.equal(result.providerCacheSavingsUsd, null);
  assert.equal(result.providerCacheHitRate, 0.5);
});
