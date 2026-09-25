import test from "node:test";
import assert from "node:assert/strict";
import {
  calculateRouteEconomics,
  mergeMetrics,
} from "../src/effective-economics.ts";

const metric = {
  requests: 10,
  logicalInputTokens: 1_000_000,
  uncachedInputTokens: 100_000,
  cachedInputTokens: 900_000,
  cacheWriteTokens: 0,
  outputTokens: 100_000,
};

test("separates provider cache savings from route savings", () => {
  const selected = {
    uncachedInputPerMTokensUsd: 0.10,
    cachedInputPerMTokensUsd: 0.01,
    cacheWritePerMTokensUsd: null,
    outputPerMTokensUsd: 0.20,
  };
  const primary = {
    uncachedInputPerMTokensUsd: 0.30,
    cachedInputPerMTokensUsd: null,
    cacheWritePerMTokensUsd: null,
    outputPerMTokensUsd: 1.20,
  };
  const e = calculateRouteEconomics(metric, selected, primary, false);
  assert.ok(Math.abs(e.selectedActualCostUsd - 0.039) < 1e-12);
  assert.ok(Math.abs(e.selectedNoCacheCostUsd - 0.12) < 1e-12);
  assert.ok(Math.abs(e.primaryReferenceCostUsd - 0.42) < 1e-12);
  assert.ok(Math.abs(e.providerCacheSavingsUsd - 0.081) < 1e-12);
  assert.ok(Math.abs(e.routeSavingsUsd - 0.30) < 1e-12);
  assert.ok(Math.abs(e.combinedSavingsUsd - 0.381) < 1e-12);
});

test("free exact-model route measures avoided paid primary cost", () => {
  const free = {
    uncachedInputPerMTokensUsd: 0,
    cachedInputPerMTokensUsd: null,
    cacheWritePerMTokensUsd: null,
    outputPerMTokensUsd: 0,
  };
  const primary = {
    uncachedInputPerMTokensUsd: 0.30,
    cachedInputPerMTokensUsd: null,
    cacheWritePerMTokensUsd: null,
    outputPerMTokensUsd: 1.20,
  };
  const noCacheMetric = {
    ...metric,
    uncachedInputTokens: 1_000_000,
    cachedInputTokens: 0,
  };
  const e = calculateRouteEconomics(noCacheMetric, free, primary, false);
  assert.equal(e.selectedActualCostUsd, 0);
  assert.equal(e.routeSavingsUsd, e.primaryReferenceCostUsd);
  assert.equal(e.combinedSavingsPct, 100);
});

test("unknown cache price fails cost attribution closed", () => {
  const price = {
    uncachedInputPerMTokensUsd: 1,
    cachedInputPerMTokensUsd: null,
    cacheWritePerMTokensUsd: null,
    outputPerMTokensUsd: 2,
  };
  const e = calculateRouteEconomics(metric, price, price, true);
  assert.equal(e.selectedActualCostUsd, null);
  assert.equal(e.providerCacheSavingsUsd, null);
  assert.equal(e.combinedSavingsUsd, null);
});

test("mergeMetrics preserves all token buckets and requests", () => {
  const merged = mergeMetrics([metric, metric]);
  assert.equal(merged.requests, 20);
  assert.equal(merged.logicalInputTokens, 2_000_000);
  assert.equal(merged.cachedInputTokens, 1_800_000);
  assert.equal(merged.outputTokens, 200_000);
});
