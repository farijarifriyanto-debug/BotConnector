export type CacheRouteMetric = {
  provider: string;
  providerModelId: string;
  requests: number;
  logicalInputTokens: number;
  uncachedInputTokens: number;
  cachedInputTokens: number;
  cacheWriteTokens: number;
  outputTokens: number;
  promptProfileRequests?: number;
  staticPrefixTokensEstimateTotal?: number;
  staticPrefixRepeatRequests?: number;
  staticPrefixRepeatTokensEstimate?: number;
};

export type CacheEconomicsPrice = {
  uncachedInputPerMTokensUsd: number;
  cachedInputPerMTokensUsd: number | null;
  cacheWritePerMTokensUsd: number | null;
  outputPerMTokensUsd: number;
};

export type CacheEconomicsResult = {
  actualCostUsd: number | null;
  noCacheEquivalentUsd: number;
  providerCacheSavingsUsd: number | null;
  providerCacheSavingsPct: number | null;
  providerCacheHitRate: number;
  staticPrefixRepeatRate: number | null;
};

function rate(value: number | null | undefined, field: string): number {
  if (value == null || !Number.isFinite(value) || value < 0) {
    throw new Error("INVALID_PRICE:" + field);
  }
  return value;
}

export function calculateCacheEconomics(
  metric: CacheRouteMetric,
  price: CacheEconomicsPrice,
): CacheEconomicsResult {
  const inputRate = rate(price.uncachedInputPerMTokensUsd, "input");
  const outputRate = rate(price.outputPerMTokensUsd, "output");

  const noCacheEquivalentUsd =
    (metric.logicalInputTokens / 1_000_000) * inputRate +
    (metric.outputTokens / 1_000_000) * outputRate;

  let actualCostUsd: number | null = null;
  if (
    (metric.cachedInputTokens === 0 || price.cachedInputPerMTokensUsd != null) &&
    (metric.cacheWriteTokens === 0 || price.cacheWritePerMTokensUsd != null)
  ) {
    const cachedRate =
      metric.cachedInputTokens === 0 ? 0 : rate(price.cachedInputPerMTokensUsd, "cached_input");
    const writeRate =
      metric.cacheWriteTokens === 0 ? 0 : rate(price.cacheWritePerMTokensUsd, "cache_write");
    actualCostUsd =
      (metric.uncachedInputTokens / 1_000_000) * inputRate +
      (metric.cachedInputTokens / 1_000_000) * cachedRate +
      (metric.cacheWriteTokens / 1_000_000) * writeRate +
      (metric.outputTokens / 1_000_000) * outputRate;
  }

  const providerCacheSavingsUsd =
    actualCostUsd == null ? null : Math.max(0, noCacheEquivalentUsd - actualCostUsd);
  const providerCacheSavingsPct =
    providerCacheSavingsUsd == null || noCacheEquivalentUsd === 0
      ? providerCacheSavingsUsd == null
        ? null
        : 0
      : (providerCacheSavingsUsd / noCacheEquivalentUsd) * 100;

  return {
    actualCostUsd,
    noCacheEquivalentUsd,
    providerCacheSavingsUsd,
    providerCacheSavingsPct,
    providerCacheHitRate:
      metric.logicalInputTokens === 0 ? 0 : metric.cachedInputTokens / metric.logicalInputTokens,
    staticPrefixRepeatRate:
      metric.promptProfileRequests && metric.promptProfileRequests > 0
        ? (metric.staticPrefixRepeatRequests ?? 0) / metric.promptProfileRequests
        : null,
  };
}
