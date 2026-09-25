import type { ProviderId } from "./model-routing.ts";
import { XKIRO_PROVIDER } from "./model-routing.ts";

export type PoolPressureTier = "NORMAL_POOL" | "POOL_PRESSURE" | "POOL_CRITICAL" | "POOL_EXHAUSTED";

export type XkiroUsage = {
  tokensUsed: number;
  tokensLimit: number;
  resetAt: Date;
  lastChecked: Date;
};

export type FairUseGuard = {
  maxTokensPerUser: number;
  windowHours: number;
  currentUsage: Map<string, number>;
};

const DEFAULT_TOKEN_LIMIT = 500_000;
const DEFAULT_USER_TOKEN_LIMIT = 100_000;
const DEFAULT_WINDOW_HOURS = 24;

let cachedUsage: XkiroUsage | null = null;
let lastFetchTime = 0;
const CACHE_TTL_MS = 60_000;

export async function fetchXkiroUsage(apiKey: string): Promise<XkiroUsage> {
  const now = Date.now();
  if (cachedUsage && now - lastFetchTime < CACHE_TTL_MS) {
    return cachedUsage;
  }

  const response = await fetch("https://api.xkiro.com/v1/usage", {
    headers: {
      Authorization: `Bearer ${apiKey}`,
    },
  });

  if (!response.ok) {
    throw new Error(`XKIRO_USAGE_FETCH_FAILED:${response.status}`);
  }

  const data = await response.json() as {
    tokens_used?: number;
    tokens_limit?: number;
    reset_at?: string;
  };

  cachedUsage = {
    tokensUsed: data.tokens_used ?? 0,
    tokensLimit: data.tokens_limit ?? DEFAULT_TOKEN_LIMIT,
    resetAt: new Date(data.reset_at ?? Date.now() + 86_400_000),
    lastChecked: new Date(),
  };
  lastFetchTime = now;

  return cachedUsage;
}

export function calculatePoolPressure(usage: XkiroUsage): PoolPressureTier {
  const usageRatio = usage.tokensUsed / usage.tokensLimit;

  if (usageRatio >= 1.0) {
    return "POOL_EXHAUSTED";
  } else if (usageRatio >= 0.8) {
    return "POOL_CRITICAL";
  } else if (usageRatio >= 0.5) {
    return "POOL_PRESSURE";
  } else {
    return "NORMAL_POOL";
  }
}

export function createFairUseGuard(
  maxTokensPerUser: number = DEFAULT_USER_TOKEN_LIMIT,
  windowHours: number = DEFAULT_WINDOW_HOURS
): FairUseGuard {
  return {
    maxTokensPerUser,
    windowHours,
    currentUsage: new Map(),
  };
}

export function checkFairUse(
  guard: FairUseGuard,
  userId: string,
  requestedTokens: number
): { allowed: boolean; reason?: string } {
  const currentUsage = guard.currentUsage.get(userId) ?? 0;

  if (currentUsage + requestedTokens > guard.maxTokensPerUser) {
    return {
      allowed: false,
      reason: `FAIR_USE_LIMIT_EXCEEDED:${guard.maxTokensPerUser}`,
    };
  }

  return { allowed: true };
}

export function recordUsage(guard: FairUseGuard, userId: string, tokensUsed: number): void {
  const currentUsage = guard.currentUsage.get(userId) ?? 0;
  guard.currentUsage.set(userId, currentUsage + tokensUsed);
}

export function resetFairUseGuard(guard: FairUseGuard): void {
  guard.currentUsage.clear();
}

export function shouldUseXkiroFreePool(
  usage: XkiroUsage,
  currentProvider: ProviderId,
  isPaidUser: boolean
): { useFreePool: boolean; reason: string } {
  if (isPaidUser) {
    return {
      useFreePool: false,
      reason: "PAID_USER_NOT_ELIGIBLE",
    };
  }

  if (currentProvider !== XKIRO_PROVIDER) {
    return {
      useFreePool: false,
      reason: "NOT_XKIRO_PROVIDER",
    };
  }

  const pressure = calculatePoolPressure(usage);

  switch (pressure) {
    case "POOL_EXHAUSTED":
      return {
        useFreePool: false,
        reason: "POOL_EXHAUSTED",
      };
    case "POOL_CRITICAL":
      return {
        useFreePool: false,
        reason: "POOL_CRITICAL",
      };
    case "POOL_PRESSURE":
      return {
        useFreePool: true,
        reason: "POOL_PRESSURE_THROTTLE",
      };
    case "NORMAL_POOL":
      return {
        useFreePool: true,
        reason: "NORMAL_POOL_OPERATION",
      };
  }
}
