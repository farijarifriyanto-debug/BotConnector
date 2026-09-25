import type { NormalizedUsage } from "./usage-meter.ts";

export type EffectivePrice = {
  inputPerMTokensUsd: number;
  cachedInputPerMTokensUsd: number | null;
  cacheWritePerMTokensUsd: number | null;
  outputPerMTokensUsd: number;
  perRequestUsd?: number;
};

export type AttemptCost = {
  usage: NormalizedUsage;
  price: EffectivePrice;
  successful: boolean;
};

export type CostBreakdown = {
  freshInputCostUsd: number;
  cachedInputCostUsd: number;
  cacheWriteCostUsd: number;
  outputCostUsd: number;
  requestFeeUsd: number;
  effectiveCostUsd: number;
  listPriceEquivalentUsd: number;
  savingsUsd: number;
  savingsPct: number;
};

function validRate(value: number | null | undefined, field: string): number {
  if (value == null || !Number.isFinite(value) || value < 0) throw new Error("PRICE_INVALID:" + field);
  return value;
}

export function calculateEffectiveCost(
  usage: NormalizedUsage,
  price: EffectivePrice,
): CostBreakdown {
  const inputRate = validRate(price.inputPerMTokensUsd, "input");
  const outputRate = validRate(price.outputPerMTokensUsd, "output");

  if (usage.cachedInputTokens > 0 && price.cachedInputPerMTokensUsd == null) {
    throw new Error("CACHE_READ_PRICE_REQUIRED");
  }
  if (usage.cacheWriteTokens > 0 && price.cacheWritePerMTokensUsd == null) {
    throw new Error("CACHE_WRITE_PRICE_REQUIRED");
  }

  const cachedRate = usage.cachedInputTokens > 0
    ? validRate(price.cachedInputPerMTokensUsd, "cached_input")
    : 0;
  const cacheWriteRate = usage.cacheWriteTokens > 0
    ? validRate(price.cacheWritePerMTokensUsd, "cache_write")
    : 0;
  const requestFeeUsd = validRate(price.perRequestUsd ?? 0, "per_request");

  const freshInputCostUsd = (usage.freshInputTokens / 1_000_000) * inputRate;
  const cachedInputCostUsd = (usage.cachedInputTokens / 1_000_000) * cachedRate;
  const cacheWriteCostUsd = (usage.cacheWriteTokens / 1_000_000) * cacheWriteRate;
  const outputCostUsd = (usage.outputTokens / 1_000_000) * outputRate;
  const effectiveCostUsd =
    freshInputCostUsd + cachedInputCostUsd + cacheWriteCostUsd + outputCostUsd + requestFeeUsd;

  const listPriceEquivalentUsd =
    (usage.logicalInputTokens / 1_000_000) * inputRate +
    (usage.outputTokens / 1_000_000) * outputRate +
    requestFeeUsd;

  const savingsUsd = Math.max(0, listPriceEquivalentUsd - effectiveCostUsd);
  const savingsPct = listPriceEquivalentUsd === 0 ? 0 : (savingsUsd / listPriceEquivalentUsd) * 100;

  return {
    freshInputCostUsd,
    cachedInputCostUsd,
    cacheWriteCostUsd,
    outputCostUsd,
    requestFeeUsd,
    effectiveCostUsd,
    listPriceEquivalentUsd,
    savingsUsd,
    savingsPct,
  };
}

export function calculateRequestCostWithRetries(attempts: AttemptCost[]) {
  if (!attempts.length) throw new Error("ATTEMPTS_REQUIRED");
  const attemptBreakdowns = attempts.map((attempt) => ({
    successful: attempt.successful,
    cost: calculateEffectiveCost(attempt.usage, attempt.price),
  }));
  const successfulAttempts = attemptBreakdowns.filter((entry) => entry.successful);
  if (successfulAttempts.length !== 1) throw new Error("EXACTLY_ONE_SUCCESSFUL_ATTEMPT_REQUIRED");

  const effectiveCostUsd = attemptBreakdowns.reduce((sum, entry) => sum + entry.cost.effectiveCostUsd, 0);
  const successfulListPriceUsd = successfulAttempts[0].cost.listPriceEquivalentUsd;
  const retryWasteUsd = attemptBreakdowns
    .filter((entry) => !entry.successful)
    .reduce((sum, entry) => sum + entry.cost.effectiveCostUsd, 0);

  return {
    attempts: attemptBreakdowns,
    effectiveCostUsd,
    successfulListPriceUsd,
    retryWasteUsd,
    costPerSuccessfulRequestUsd: effectiveCostUsd,
  };
}
