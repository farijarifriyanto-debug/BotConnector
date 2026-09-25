import type { EffectivePrice } from "./effective-cost.ts";

export type CacheAwareCandidate = {
  canonicalModelId: string;
  provider: string;
  providerModelId: string;
  healthy: boolean;
  quotaAvailable: boolean;
  uptimePct?: number;
  expectedCacheHitRate: number;
  price: EffectivePrice;
};

export type RouteSelectionInput = {
  canonicalModelId: string;
  logicalInputTokens: number;
  outputTokens: number;
  candidates: CacheAwareCandidate[];
  pinnedProvider?: string | null;
  pinnedProviderModelId?: string | null;
  switchMarginPct?: number;
  hardUptimeFloorPct?: number;
};

export type ScoredCandidate = CacheAwareCandidate & {
  expectedEffectiveCostUsd: number;
};

function boundedRatio(value: number): number {
  if (!Number.isFinite(value) || value < 0 || value > 1) throw new Error("CACHE_HIT_RATE_INVALID");
  return value;
}

export function estimateExpectedRouteCostUsd(
  candidate: CacheAwareCandidate,
  logicalInputTokens: number,
  outputTokens: number,
): number {
  if (!Number.isSafeInteger(logicalInputTokens) || logicalInputTokens < 0) throw new Error("INPUT_TOKENS_INVALID");
  if (!Number.isSafeInteger(outputTokens) || outputTokens < 0) throw new Error("OUTPUT_TOKENS_INVALID");
  const hit = boundedRatio(candidate.expectedCacheHitRate);
  const cachedTokens = Math.floor(logicalInputTokens * hit);
  const freshTokens = logicalInputTokens - cachedTokens;
  const inputRate = candidate.price.inputPerMTokensUsd;
  const outputRate = candidate.price.outputPerMTokensUsd;
  if (!Number.isFinite(inputRate) || inputRate < 0 || !Number.isFinite(outputRate) || outputRate < 0) {
    throw new Error("ROUTE_PRICE_INVALID");
  }
  if (cachedTokens > 0 && candidate.price.cachedInputPerMTokensUsd == null) {
    return Number.POSITIVE_INFINITY;
  }
  const cachedRate = candidate.price.cachedInputPerMTokensUsd ?? 0;
  const fee = candidate.price.perRequestUsd ?? 0;
  return (
    (freshTokens / 1_000_000) * inputRate +
    (cachedTokens / 1_000_000) * cachedRate +
    (outputTokens / 1_000_000) * outputRate +
    fee
  );
}

export function selectCacheAwareRoute(input: RouteSelectionInput): {
  selected: ScoredCandidate;
  candidates: ScoredCandidate[];
  reason: "best-effective-cost" | "cache-affinity";
} {
  const hardUptimeFloorPct = input.hardUptimeFloorPct ?? 85;
  const switchMarginPct = input.switchMarginPct ?? 15;
  if (!Number.isFinite(switchMarginPct) || switchMarginPct < 0) throw new Error("SWITCH_MARGIN_INVALID");

  const eligible = input.candidates.filter(
    (candidate) =>
      candidate.canonicalModelId === input.canonicalModelId &&
      candidate.healthy &&
      candidate.quotaAvailable &&
      (candidate.uptimePct == null || candidate.uptimePct >= hardUptimeFloorPct),
  );

  if (!eligible.length) throw new Error("MODEL_FREE_CAPACITY_UNAVAILABLE:" + input.canonicalModelId);

  const scored = eligible
    .map((candidate) => ({
      ...candidate,
      expectedEffectiveCostUsd: estimateExpectedRouteCostUsd(
        candidate,
        input.logicalInputTokens,
        input.outputTokens,
      ),
    }))
    .filter((candidate) => Number.isFinite(candidate.expectedEffectiveCostUsd))
    .sort((a, b) => a.expectedEffectiveCostUsd - b.expectedEffectiveCostUsd);

  if (!scored.length) throw new Error("CACHE_PRICING_UNAVAILABLE:" + input.canonicalModelId);

  const best = scored[0];
  const pinned = scored.find(
    (candidate) =>
      candidate.provider === input.pinnedProvider &&
      (!input.pinnedProviderModelId || candidate.providerModelId === input.pinnedProviderModelId),
  );

  if (pinned) {
    const threshold = best.expectedEffectiveCostUsd * (1 + switchMarginPct / 100);
    if (pinned.expectedEffectiveCostUsd <= threshold) {
      return { selected: pinned, candidates: scored, reason: "cache-affinity" };
    }
  }

  return { selected: best, candidates: scored, reason: "best-effective-cost" };
}
