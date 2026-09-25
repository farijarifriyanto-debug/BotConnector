import fs from "node:fs";
import { execFileSync } from "node:child_process";
import { calculateCacheEconomics } from "../src/cache-economics.ts";

const container = process.env.BOTCONNECTOR_CACHE_CONTAINER || "botconnector-production-candidate-cache";
const prices = JSON.parse(
  fs.readFileSync(new URL("../config/price-registry.json", import.meta.url), "utf8"),
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

const keysRaw = redis(["--scan", "--pattern", "botconnector:metrics:v1:route:*"]);
const keys = keysRaw ? keysRaw.split(/\r?\n/).filter(Boolean) : [];
const exact = hgetall("botconnector:metrics:v1:exact");

const report = {
  generatedAt: new Date().toISOString(),
  exactCache: {
    hits: number(exact.hits),
    misses: number(exact.misses),
    hitRate:
      number(exact.hits) + number(exact.misses) === 0
        ? 0
        : number(exact.hits) / (number(exact.hits) + number(exact.misses)),
    avoidedUpstreamCalls: number(exact.hits),
  },
  routes: [],
};

for (const key of keys) {
  const h = hgetall(key);
  const provider = h.provider || "";
  const providerModelId = h.provider_model_id || "";
  if (!provider || !providerModelId) continue;
  const offer = prices.offers.find(
    (item) => item.provider === provider && item.providerModelId === providerModelId,
  );

  const metric = {
    provider,
    providerModelId,
    requests: number(h.requests),
    logicalInputTokens: number(h.logical_input_tokens),
    uncachedInputTokens: number(h.uncached_input_tokens),
    cachedInputTokens: number(h.cached_input_tokens),
    cacheWriteTokens: number(h.cache_write_tokens),
    outputTokens: number(h.output_tokens),
    promptProfileRequests: number(h.prompt_profile_requests),
    staticPrefixTokensEstimateTotal: number(h.static_prefix_tokens_estimate_total),
    staticPrefixRepeatRequests: number(h.static_prefix_repeat_requests),
    staticPrefixRepeatTokensEstimate: number(h.static_prefix_repeat_tokens_estimate),
  };

  let economics = null;
  if (offer?.pricing?.actualProviderPrice) {
    const p = offer.pricing.actualProviderPrice;
    economics = calculateCacheEconomics(metric, {
      uncachedInputPerMTokensUsd: p.uncachedInputPerMTokensUsd,
      cachedInputPerMTokensUsd: p.cachedInputPerMTokensUsd,
      cacheWritePerMTokensUsd: p.cacheWritePerMTokensUsd,
      outputPerMTokensUsd: p.outputPerMTokensUsd,
    });
  }

  report.routes.push({
    canonicalModelId: offer?.canonicalModelId ?? null,
    priceKey: offer?.priceKey ?? null,
    metric,
    economics,
  });
}

report.routes.sort((a, b) => b.metric.logicalInputTokens - a.metric.logicalInputTokens);

if (process.argv.includes("--json")) {
  console.log(JSON.stringify(report, null, 2));
  process.exit(0);
}

const pct = (v) => (v == null ? "n/a" : (v * 100).toFixed(1) + "%");
const usd = (v) => (v == null ? "n/a" : "$" + v.toFixed(6));

console.log("BOTCONNECTOR CACHE ECONOMICS");
console.log("Exact cache: hits=" + report.exactCache.hits +
  " misses=" + report.exactCache.misses +
  " hit-rate=" + pct(report.exactCache.hitRate) +
  " avoided-upstream-calls=" + report.exactCache.avoidedUpstreamCalls);

if (!report.routes.length) {
  console.log("Provider cache telemetry: no runtime samples yet.");
  process.exit(0);
}

for (const row of report.routes) {
  const e = row.economics;
  console.log("");
  console.log((row.canonicalModelId || "unknown") + " via " + row.metric.provider +
    " [" + row.metric.providerModelId + "]");
  console.log("  requests=" + row.metric.requests +
    " logical-input=" + row.metric.logicalInputTokens +
    " cached-input=" + row.metric.cachedInputTokens +
    " cache-hit-rate=" + (e ? pct(e.providerCacheHitRate) : "n/a"));
  console.log("  prefix-repeat=" + (e ? pct(e.staticPrefixRepeatRate) : "n/a") +
    " repeat-token-estimate=" + row.metric.staticPrefixRepeatTokensEstimate);
  console.log("  no-cache-equivalent=" + (e ? usd(e.noCacheEquivalentUsd) : "n/a") +
    " actual=" + (e ? usd(e.actualCostUsd) : "n/a") +
    " provider-cache-savings=" + (e ? usd(e.providerCacheSavingsUsd) : "n/a") +
    " savings=" + (e ? (e.providerCacheSavingsPct == null ? "n/a" : e.providerCacheSavingsPct.toFixed(1) + "%") : "n/a"));
}
