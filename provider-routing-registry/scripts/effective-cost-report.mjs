import fs from "node:fs";
import { execFileSync } from "node:child_process";
import {
  calculateRouteEconomics,
  mergeMetrics,
} from "../src/effective-economics.ts";

const container =
  process.env.BOTCONNECTOR_CACHE_CONTAINER || "botconnector-production-candidate-cache";
const hoursArg = process.argv.find((x) => x.startsWith("--hours="));
const hours = hoursArg ? Number(hoursArg.split("=", 2)[1]) : 24;
if (!Number.isInteger(hours) || hours < 1 || hours > 168) {
  throw new Error("HOURS_MUST_BE_INTEGER_1_TO_168");
}
const jsonMode = process.argv.includes("--json");
const outArg = process.argv.find((x) => x.startsWith("--output="));
const outPath = outArg ? outArg.slice("--output=".length) : null;

const prices = JSON.parse(
  fs.readFileSync(new URL("../config/price-registry.json", import.meta.url), "utf8"),
);
const candidates = JSON.parse(
  fs.readFileSync(new URL("../config/provider-route-candidates.json", import.meta.url), "utf8"),
);

function redis(args) {
  return execFileSync("docker", ["exec", container, "redis-cli", "--raw", ...args], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function number(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) && n >= 0 ? n : 0;
}

function hgetall(key) {
  const raw = redis(["HGETALL", key]);
  if (!raw) return {};
  const lines = raw.split(/\r?\n/);
  const out = {};
  for (let i = 0; i + 1 < lines.length; i += 2) out[lines[i]] = lines[i + 1];
  return out;
}

function metricFromHash(h) {
  return {
    requests: number(h.requests),
    logicalInputTokens: number(h.logical_input_tokens),
    uncachedInputTokens: number(h.uncached_input_tokens),
    cachedInputTokens: number(h.cached_input_tokens),
    cacheWriteTokens: number(h.cache_write_tokens),
    outputTokens: number(h.output_tokens),
  };
}

function priceOf(offer) {
  const p = offer?.pricing?.actualProviderPrice;
  if (!p) return null;
  return {
    uncachedInputPerMTokensUsd: p.uncachedInputPerMTokensUsd,
    cachedInputPerMTokensUsd: p.cachedInputPerMTokensUsd,
    cacheWritePerMTokensUsd: p.cacheWritePerMTokensUsd,
    outputPerMTokensUsd: p.outputPerMTokensUsd,
  };
}

const currentHour = Math.floor(Date.now() / 3_600_000);
const firstHour = currentHour - hours + 1;
const routeKeysRaw = redis(["--scan", "--pattern", "botconnector:metrics:v1:hour:*:route:*"]);
const routeKeys = routeKeysRaw ? routeKeysRaw.split(/\r?\n/).filter(Boolean) : [];
const exactKeysRaw = redis(["--scan", "--pattern", "botconnector:metrics:v1:hour:*:exact"]);
const exactKeys = exactKeysRaw ? exactKeysRaw.split(/\r?\n/).filter(Boolean) : [];

const routeGroups = new Map();
for (const key of routeKeys) {
  const match = key.match(/^botconnector:metrics:v1:hour:(\d+):route:/);
  if (!match) continue;
  const bucket = Number(match[1]);
  if (bucket < firstHour || bucket > currentHour) continue;
  const h = hgetall(key);
  const provider = h.provider || "";
  const providerModelId = h.provider_model_id || "";
  if (!provider || !providerModelId) continue;
  const groupKey = provider + "\0" + providerModelId;
  const list = routeGroups.get(groupKey) || [];
  list.push(metricFromHash(h));
  routeGroups.set(groupKey, list);
}

let exactHits = 0;
let exactMisses = 0;
for (const key of exactKeys) {
  const match = key.match(/^botconnector:metrics:v1:hour:(\d+):exact$/);
  if (!match) continue;
  const bucket = Number(match[1]);
  if (bucket < firstHour || bucket > currentHour) continue;
  const h = hgetall(key);
  exactHits += number(h.hits);
  exactMisses += number(h.misses);
}

const routes = [];
for (const [groupKey, metrics] of routeGroups) {
  const [provider, providerModelId] = groupKey.split("\0");
  const metric = mergeMetrics(metrics);
  const offer = prices.offers.find(
    (x) => x.provider === provider && x.providerModelId === providerModelId,
  );
  if (!offer) {
    routes.push({
      provider,
      providerModelId,
      canonicalModelId: null,
      metric,
      economics: null,
      attribution: "PRICE_OFFER_NOT_FOUND",
    });
    continue;
  }

  // Canonical model identity comes from the route-authority artifact, not
  // necessarily the raw price offer. Free/provider-scoped offers may use a
  // provider-specific canonical alias while still representing the exact same
  // user-selected AI.
  const route =
    candidates.routes.find((x) =>
      x.candidates?.some(
        (candidate) =>
          candidate.provider === provider &&
          candidate.providerModelId === providerModelId,
      ),
    ) ??
    candidates.routes.find((x) => x.canonicalModelId === offer.canonicalModelId);
  const primaryOffer = route?.primary
    ? prices.offers.find((x) => x.priceKey === route.primary.priceKey)
    : null;
  const selectedPrice = priceOf(offer);
  const primaryPrice = priceOf(primaryOffer);
  const selectedIsPrimary =
    Boolean(route?.primary) &&
    route.primary.provider === provider &&
    route.primary.providerModelId === providerModelId;

  let economics = null;
  let attribution = "OK";
  if (!selectedPrice) {
    attribution = "SELECTED_PRICE_MISSING";
  } else {
    try {
      economics = calculateRouteEconomics(
        metric,
        selectedPrice,
        primaryPrice,
        selectedIsPrimary,
      );
    } catch (error) {
      attribution = String(error?.message || error);
    }
  }

  routes.push({
    provider,
    providerModelId,
    canonicalModelId: route?.canonicalModelId ?? offer.canonicalModelId,
    priceKey: offer.priceKey,
    primaryPriceKey: route?.primary?.priceKey ?? null,
    selectedIsPrimary,
    metric,
    economics,
    attribution,
  });
}

routes.sort((a, b) => b.metric.logicalInputTokens - a.metric.logicalInputTokens);

const totals = {
  requests: routes.reduce((s, x) => s + x.metric.requests, 0),
  logicalInputTokens: routes.reduce((s, x) => s + x.metric.logicalInputTokens, 0),
  outputTokens: routes.reduce((s, x) => s + x.metric.outputTokens, 0),
  actualCostUsd: 0,
  primaryReferenceCostUsd: 0,
  providerCacheSavingsUsd: 0,
  routeSavingsUsd: 0,
  combinedSavingsUsd: 0,
  unattributedRouteCount: 0,
};
for (const row of routes) {
  const e = row.economics;
  if (!e || e.selectedActualCostUsd == null || e.primaryReferenceCostUsd == null) {
    totals.unattributedRouteCount += 1;
    continue;
  }
  totals.actualCostUsd += e.selectedActualCostUsd;
  totals.primaryReferenceCostUsd += e.primaryReferenceCostUsd;
  totals.providerCacheSavingsUsd += e.providerCacheSavingsUsd ?? 0;
  totals.routeSavingsUsd += e.routeSavingsUsd ?? 0;
  totals.combinedSavingsUsd += e.combinedSavingsUsd ?? 0;
}
const logicalTotal = totals.logicalInputTokens + totals.outputTokens;
const report = {
  schema: "botconnector.effective-cost-report.v1",
  generatedAt: new Date().toISOString(),
  windowHours: hours,
  windowStartHour: firstHour,
  windowEndHour: currentHour,
  exactCache: {
    hits: exactHits,
    misses: exactMisses,
    hitRate: exactHits + exactMisses === 0 ? 0 : exactHits / (exactHits + exactMisses),
    avoidedUpstreamCalls: exactHits,
  },
  totals: {
    ...totals,
    combinedSavingsPct:
      totals.primaryReferenceCostUsd === 0
        ? 0
        : (totals.combinedSavingsUsd / totals.primaryReferenceCostUsd) * 100,
    effectiveCostPerMLogicalTokensUsd:
      logicalTotal === 0 ? null : totals.actualCostUsd / (logicalTotal / 1_000_000),
    costPerSuccessfulRequestUsd:
      totals.requests === 0 ? null : totals.actualCostUsd / totals.requests,
  },
  routes,
};

if (outPath) {
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2) + "\n");
}

if (jsonMode) {
  console.log(JSON.stringify(report, null, 2));
  process.exit(0);
}

const usd = (v) => (v == null ? "n/a" : "$" + Number(v).toFixed(6));
const pct = (v) => (v == null ? "n/a" : Number(v).toFixed(1) + "%");

console.log("BOTCONNECTOR EFFECTIVE COST REPORT");
console.log("window=" + hours + "h generated=" + report.generatedAt);
console.log(
  "exact-cache hits=" + exactHits +
    " misses=" + exactMisses +
    " hit-rate=" + pct(report.exactCache.hitRate * 100) +
    " avoided-upstream=" + exactHits,
);
console.log(
  "requests=" + totals.requests +
    " logical-input=" + totals.logicalInputTokens +
    " output=" + totals.outputTokens,
);
console.log(
  "primary-reference=" + usd(totals.primaryReferenceCostUsd) +
    " actual=" + usd(totals.actualCostUsd) +
    " cache-savings=" + usd(totals.providerCacheSavingsUsd) +
    " route-savings=" + usd(totals.routeSavingsUsd) +
    " combined-savings=" + usd(totals.combinedSavingsUsd) +
    " (" + pct(report.totals.combinedSavingsPct) + ")",
);
console.log(
  "effective-cost/M-logical=" + usd(report.totals.effectiveCostPerMLogicalTokensUsd) +
    " cost/successful-request=" + usd(report.totals.costPerSuccessfulRequestUsd) +
    " unattributed-routes=" + totals.unattributedRouteCount,
);

if (!routes.length) {
  console.log("No successful hourly provider usage samples in this window yet.");
}
for (const row of routes) {
  const e = row.economics;
  console.log("");
  console.log(
    (row.canonicalModelId || "unknown") + " via " + row.provider + " [" + row.providerModelId + "]",
  );
  console.log(
    "  requests=" + row.metric.requests +
      " logical-input=" + row.metric.logicalInputTokens +
      " cached-input=" + row.metric.cachedInputTokens +
      " output=" + row.metric.outputTokens,
  );
  console.log(
    "  actual=" + usd(e?.selectedActualCostUsd) +
      " primary-ref=" + usd(e?.primaryReferenceCostUsd) +
      " cache-save=" + usd(e?.providerCacheSavingsUsd) +
      " route-save=" + usd(e?.routeSavingsUsd) +
      " combined=" + usd(e?.combinedSavingsUsd),
  );
  if (row.attribution !== "OK") console.log("  attribution=" + row.attribution);
}
