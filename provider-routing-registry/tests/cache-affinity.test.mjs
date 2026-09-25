import test from "node:test";
import assert from "node:assert/strict";
import { selectCacheAwareRoute } from "../src/cache-affinity.ts";
import { selectCostOptimizedExactModelRoute } from "../src/cost-optimized-routing.ts";

const priceA = { inputPerMTokensUsd: 0.10, cachedInputPerMTokensUsd: 0.01, cacheWritePerMTokensUsd: null, outputPerMTokensUsd: 0.20 };
const priceB = { inputPerMTokensUsd: 0.06, cachedInputPerMTokensUsd: 0.06, cacheWritePerMTokensUsd: null, outputPerMTokensUsd: 0.20 };

const candidates = [
  {
    canonicalModelId: "laguna-s-2.1",
    provider: "nararouter",
    providerModelId: "laguna-s-2.1",
    healthy: true,
    quotaAvailable: true,
    uptimePct: 99,
    expectedCacheHitRate: 0.9,
    price: priceA,
  },
  {
    canonicalModelId: "laguna-s-2.1",
    provider: "poolside",
    providerModelId: "poolside/laguna-s-2.1",
    healthy: true,
    quotaAvailable: true,
    uptimePct: 99,
    expectedCacheHitRate: 0,
    price: priceB,
  },
];

test("cache-aware cost can beat lower list-price route", () => {
  const result = selectCacheAwareRoute({
    canonicalModelId: "laguna-s-2.1",
    logicalInputTokens: 1_000_000,
    outputTokens: 100_000,
    candidates,
  });
  assert.equal(result.selected.provider, "nararouter");
  assert.equal(result.reason, "best-effective-cost");
});

test("session affinity keeps a warm provider inside switch margin", () => {
  const close = [
    { ...candidates[0], expectedCacheHitRate: 0.5, price: { ...priceA, inputPerMTokensUsd: 0.08, cachedInputPerMTokensUsd: 0.04 } },
    { ...candidates[1], price: { ...priceB, inputPerMTokensUsd: 0.058, cachedInputPerMTokensUsd: 0.058 } },
  ];
  const result = selectCacheAwareRoute({
    canonicalModelId: "laguna-s-2.1",
    logicalInputTokens: 100_000,
    outputTokens: 10_000,
    candidates: close,
    pinnedProvider: "nararouter",
    switchMarginPct: 30,
  });
  assert.equal(result.selected.provider, "nararouter");
  assert.equal(result.reason, "cache-affinity");
});

test("unhealthy or quota-exhausted pinned provider fails over", () => {
  const degraded = candidates.map((candidate) =>
    candidate.provider === "nararouter" ? { ...candidate, quotaAvailable: false } : candidate,
  );
  const result = selectCacheAwareRoute({
    canonicalModelId: "laguna-s-2.1",
    logicalInputTokens: 100_000,
    outputTokens: 10_000,
    candidates: degraded,
    pinnedProvider: "nararouter",
  });
  assert.equal(result.selected.provider, "poolside");
});

test("cross-model candidates never substitute the requested AI", () => {
  const result = selectCostOptimizedExactModelRoute({
    canonicalModelId: "laguna-s-2.1",
    logicalInputTokens: 100_000,
    outputTokens: 10_000,
    candidates: [
      ...candidates,
      {
        canonicalModelId: "different-ai",
        provider: "xkiro",
        providerModelId: "different-ai-free",
        healthy: true,
        quotaAvailable: true,
        uptimePct: 100,
        expectedCacheHitRate: 1,
        price: { inputPerMTokensUsd: 0, cachedInputPerMTokensUsd: 0, cacheWritePerMTokensUsd: null, outputPerMTokensUsd: 0 },
      },
    ],
  });
  assert.equal(result.selected.canonicalModelId, "laguna-s-2.1");
});

test("no exact-model capacity returns explicit unavailable error", () => {
  assert.throws(
    () => selectCacheAwareRoute({
      canonicalModelId: "laguna-s-2.1",
      logicalInputTokens: 1,
      outputTokens: 1,
      candidates: [{ ...candidates[0], canonicalModelId: "other-model" }],
    }),
    /MODEL_FREE_CAPACITY_UNAVAILABLE:laguna-s-2.1/,
  );
});
