import documentJson from "../config/cache-capabilities.json" with { type: "json" };

export type PromptCacheSupport = "observed" | "verified" | "unknown" | "unsupported";
export type PromptCacheMode = "implicit" | "explicit" | "hybrid" | "unknown";

export type CacheCapability = {
  id: string;
  promptCache: {
    support: PromptCacheSupport;
    mode: PromptCacheMode;
    usageReportsCachedTokens: boolean;
    minCacheableTokens: number | null;
    ttlSeconds: number | null;
    notes: string;
  };
};

const document = documentJson as {
  schema: string;
  policy: {
    manualModelSelection: string;
    tenantIsolationRequired: boolean;
    semanticCacheEnabledByDefault: boolean;
    exactResponseCacheEnabledByDefault: boolean;
    sessionAffinityEnabledByDefault: boolean;
    unknownCachePricingBehavior: string;
  };
  providers: CacheCapability[];
};

const byId = new Map(document.providers.map((entry) => [entry.id, entry]));

export function getCacheCapability(providerId: string): CacheCapability {
  const found = byId.get(providerId);
  if (!found) throw new Error("CACHE_CAPABILITY_NOT_FOUND:" + providerId);
  return found;
}

export function listCacheCapabilities(): CacheCapability[] {
  return [...document.providers];
}

export const cachePolicy = document.policy;
