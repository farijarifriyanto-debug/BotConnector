import test from "node:test";
import assert from "node:assert/strict";
import { calculateEffectiveCost, calculateRequestCostWithRetries } from "../src/effective-cost.ts";

const usage = {
  logicalInputTokens: 1_000_000,
  freshInputTokens: 100_000,
  cachedInputTokens: 900_000,
  cacheWriteTokens: 0,
  outputTokens: 100_000,
  totalLogicalTokens: 1_100_000,
  cacheHitRate: 0.9,
};

const price = {
  inputPerMTokensUsd: 0.1,
  cachedInputPerMTokensUsd: 0.02,
  cacheWritePerMTokensUsd: null,
  outputPerMTokensUsd: 0.2,
};

test("effective cost uses cache-read rate and reports savings", () => {
  const cost = calculateEffectiveCost(usage, price);
  assert.ok(Math.abs(cost.freshInputCostUsd - 0.01) < 1e-12);
  assert.ok(Math.abs(cost.cachedInputCostUsd - 0.018) < 1e-12);
  assert.ok(Math.abs(cost.outputCostUsd - 0.02) < 1e-12);
  assert.ok(Math.abs(cost.effectiveCostUsd - 0.048) < 1e-12);
  assert.ok(Math.abs(cost.listPriceEquivalentUsd - 0.12) < 1e-12);
  assert.ok(Math.abs(cost.savingsPct - 60) < 1e-9);
});

test("cached tokens fail closed without a cache-read price", () => {
  assert.throws(
    () => calculateEffectiveCost(usage, { ...price, cachedInputPerMTokensUsd: null }),
    /CACHE_READ_PRICE_REQUIRED/,
  );
});

test("retry waste is included in cost per successful request", () => {
  const failedUsage = { ...usage, logicalInputTokens: 100_000, freshInputTokens: 100_000, cachedInputTokens: 0, outputTokens: 0, totalLogicalTokens: 100_000, cacheHitRate: 0 };
  const result = calculateRequestCostWithRetries([
    { usage: failedUsage, price, successful: false },
    { usage, price, successful: true },
  ]);
  assert.ok(result.retryWasteUsd > 0);
  assert.ok(result.effectiveCostUsd > result.attempts[1].cost.effectiveCostUsd);
});
