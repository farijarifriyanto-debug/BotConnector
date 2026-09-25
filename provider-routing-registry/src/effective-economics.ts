export type EconomicsMetric = {
  requests: number;
  logicalInputTokens: number;
  uncachedInputTokens: number;
  cachedInputTokens: number;
  cacheWriteTokens: number;
  outputTokens: number;
};

export type EconomicsPrice = {
  uncachedInputPerMTokensUsd: number;
  cachedInputPerMTokensUsd: number | null;
  cacheWritePerMTokensUsd: number | null;
  outputPerMTokensUsd: number;
};

export type RouteEconomics = {
  selectedActualCostUsd: number | null;
  selectedNoCacheCostUsd: number;
  primaryReferenceCostUsd: number | null;
  providerCacheSavingsUsd: number | null;
  routeSavingsUsd: number | null;
  combinedSavingsUsd: number | null;
  combinedSavingsPct: number | null;
  effectiveCostPerMLogicalTokensUsd: number | null;
  costPerSuccessfulRequestUsd: number | null;
};

function nonNegative(value: number, field: string): number {
  if (!Number.isFinite(value) || value < 0) throw new Error("INVALID_ECONOMICS_VALUE:" + field);
  return value;
}

function rate(value: number | null | undefined, field: string): number {
  if (value == null || !Number.isFinite(value) || value < 0) {
    throw new Error("INVALID_ECONOMICS_PRICE:" + field);
  }
  return value;
}

export function costWithObservedCache(
  metric: EconomicsMetric,
  price: EconomicsPrice,
): number | null {
  const input = rate(price.uncachedInputPerMTokensUsd, "input");
  const output = rate(price.outputPerMTokensUsd, "output");
  if (metric.cachedInputTokens > 0 && price.cachedInputPerMTokensUsd == null) return null;
  if (metric.cacheWriteTokens > 0 && price.cacheWritePerMTokensUsd == null) return null;

  const cached = metric.cachedInputTokens
    ? rate(price.cachedInputPerMTokensUsd, "cached_input")
    : 0;
  const write = metric.cacheWriteTokens
    ? rate(price.cacheWritePerMTokensUsd, "cache_write")
    : 0;

  return (
    (nonNegative(metric.uncachedInputTokens, "uncached_input") / 1_000_000) * input +
    (nonNegative(metric.cachedInputTokens, "cached_input") / 1_000_000) * cached +
    (nonNegative(metric.cacheWriteTokens, "cache_write") / 1_000_000) * write +
    (nonNegative(metric.outputTokens, "output") / 1_000_000) * output
  );
}

export function noCacheCost(metric: EconomicsMetric, price: EconomicsPrice): number {
  const input = rate(price.uncachedInputPerMTokensUsd, "input");
  const output = rate(price.outputPerMTokensUsd, "output");
  return (
    (nonNegative(metric.logicalInputTokens, "logical_input") / 1_000_000) * input +
    (nonNegative(metric.outputTokens, "output") / 1_000_000) * output
  );
}

export function calculateRouteEconomics(
  metric: EconomicsMetric,
  selectedPrice: EconomicsPrice,
  primaryPrice: EconomicsPrice | null,
  selectedIsPrimary: boolean,
): RouteEconomics {
  const selectedActualCostUsd = costWithObservedCache(metric, selectedPrice);
  const selectedNoCacheCostUsd = noCacheCost(metric, selectedPrice);
  const primaryReferenceCostUsd = primaryPrice ? noCacheCost(metric, primaryPrice) : null;

  const providerCacheSavingsUsd =
    selectedActualCostUsd == null
      ? null
      : Math.max(0, selectedNoCacheCostUsd - selectedActualCostUsd);

  // Route savings intentionally excludes cache savings. Compare both routes at
  // uncached/list economics so "free route" and "prompt cache" remain separate.
  const routeSavingsUsd =
    primaryReferenceCostUsd == null
      ? null
      : selectedIsPrimary
        ? 0
        : Math.max(0, primaryReferenceCostUsd - selectedNoCacheCostUsd);

  const combinedSavingsUsd =
    primaryReferenceCostUsd == null || selectedActualCostUsd == null
      ? null
      : Math.max(0, primaryReferenceCostUsd - selectedActualCostUsd);

  const combinedSavingsPct =
    combinedSavingsUsd == null || primaryReferenceCostUsd == null
      ? null
      : primaryReferenceCostUsd === 0
        ? 0
        : (combinedSavingsUsd / primaryReferenceCostUsd) * 100;

  const logicalTotal = metric.logicalInputTokens + metric.outputTokens;
  const effectiveCostPerMLogicalTokensUsd =
    selectedActualCostUsd == null || logicalTotal === 0
      ? null
      : selectedActualCostUsd / (logicalTotal / 1_000_000);

  const costPerSuccessfulRequestUsd =
    selectedActualCostUsd == null || metric.requests <= 0
      ? null
      : selectedActualCostUsd / metric.requests;

  return {
    selectedActualCostUsd,
    selectedNoCacheCostUsd,
    primaryReferenceCostUsd,
    providerCacheSavingsUsd,
    routeSavingsUsd,
    combinedSavingsUsd,
    combinedSavingsPct,
    effectiveCostPerMLogicalTokensUsd,
    costPerSuccessfulRequestUsd,
  };
}

export function mergeMetrics(metrics: EconomicsMetric[]): EconomicsMetric {
  return metrics.reduce<EconomicsMetric>(
    (sum, item) => ({
      requests: sum.requests + item.requests,
      logicalInputTokens: sum.logicalInputTokens + item.logicalInputTokens,
      uncachedInputTokens: sum.uncachedInputTokens + item.uncachedInputTokens,
      cachedInputTokens: sum.cachedInputTokens + item.cachedInputTokens,
      cacheWriteTokens: sum.cacheWriteTokens + item.cacheWriteTokens,
      outputTokens: sum.outputTokens + item.outputTokens,
    }),
    {
      requests: 0,
      logicalInputTokens: 0,
      uncachedInputTokens: 0,
      cachedInputTokens: 0,
      cacheWriteTokens: 0,
      outputTokens: 0,
    },
  );
}
