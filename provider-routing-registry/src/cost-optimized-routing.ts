import { selectCacheAwareRoute, type CacheAwareCandidate } from "./cache-affinity.ts";
import { assertSameModelFallback, type ModelProviderCandidate } from "./free-provider-routing.ts";

export type CostOptimizedRouteRequest = {
  canonicalModelId: string;
  logicalInputTokens: number;
  outputTokens: number;
  candidates: CacheAwareCandidate[];
  pinnedProvider?: string | null;
  pinnedProviderModelId?: string | null;
  switchMarginPct?: number;
  hardUptimeFloorPct?: number;
};

export function selectCostOptimizedExactModelRoute(request: CostOptimizedRouteRequest) {
  for (const candidate of request.candidates) {
    if (candidate.canonicalModelId !== request.canonicalModelId) continue;
    const source: ModelProviderCandidate = {
      canonicalModelId: request.canonicalModelId,
      provider: candidate.provider as ModelProviderCandidate["provider"],
      providerModelId: candidate.providerModelId,
    };
    const target = { ...source };
    assertSameModelFallback(source, target);
  }

  const result = selectCacheAwareRoute(request);

  if (result.selected.canonicalModelId !== request.canonicalModelId) {
    throw new Error("CROSS_MODEL_FALLBACK_BLOCKED:" + request.canonicalModelId + ":" + result.selected.canonicalModelId);
  }

  return result;
}
