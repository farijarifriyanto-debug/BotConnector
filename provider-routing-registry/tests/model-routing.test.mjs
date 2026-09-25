import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  estimateCostUsd,
  estimateOfferCostUsd,
  evaluateProviderEligibility,
  getBillablePrice,
  getSelectedPrice,
  isTrustedPricing,
  registry,
  validateRegistryData,
} from "../src/model-routing.ts";

const root = path.resolve(import.meta.dirname, "..");
const routes = JSON.parse(fs.readFileSync(path.join(root, "config/static-model-routes.json"), "utf8"));
const prices = JSON.parse(fs.readFileSync(path.join(root, "config/price-registry.json"), "utf8"));

const selectedOffers = new Map(prices.offers.map((offer) => [offer.priceKey, offer]));

test("STATIC_PRIMARY_POLICY_LOCKED", () => {
  for (const route of routes.routes) {
    assert.equal(route.selectionPolicy, "reviewed-static-primary", route.modelId);
    assert.equal(route.locked, true, route.modelId);
  }
  assert.equal(routes.policy.autoSwitchProvider, false);
});

test("CANONICAL_MODEL_ID_REQUIRED", () => {
  for (const route of routes.routes) {
    assert.equal(typeof route.canonicalModelId, "string", route.modelId);
    assert.ok(route.canonicalModelId.length > 0, route.modelId);
  }
});

test("SELECTED_OFFER_EXISTS", () => {
  for (const route of routes.routes) {
    const offer = selectedOffers.get(route.priceKey);
    assert.ok(offer, route.modelId);
    assert.equal(offer.provider, route.provider, route.modelId);
    assert.equal(offer.providerModelId, route.providerModelId, route.modelId);
    assert.equal(offer.canonicalModelId, route.canonicalModelId, route.modelId);
  }
});

test("PROVIDER_OFFER_SCHEMA_IS_EXPLICIT", () => {
  for (const offer of prices.offers) {
    assert.ok(["list", "tiered", "promotion", "free"].includes(offer.pricing?.kind), offer.priceKey);
    assert.equal(typeof offer.pricing?.currency, "string", offer.priceKey);
    assert.ok(Object.hasOwn(offer.pricing, "verifiedAt"), offer.priceKey);
    assert.ok(Object.hasOwn(offer.pricing, "sourceUrl"), offer.priceKey);
    assert.equal(typeof offer.region, "string", offer.priceKey);
    assert.equal(typeof offer.deploymentScope, "string", offer.priceKey);
    assert.ok(Object.hasOwn(offer, "capabilities"), offer.priceKey);
    assert.ok(Object.hasOwn(offer, "operational"), offer.priceKey);
    assert.ok(Object.hasOwn(offer, "privacy"), offer.priceKey);
    assert.ok(Object.hasOwn(offer.pricing, "actualProviderPrice"), offer.priceKey);
    assert.ok(Object.hasOwn(offer.pricing, "standardReferencePrice"), offer.priceKey);
    for (const price of [offer.pricing.actualProviderPrice, ...(offer.pricing.tiers ?? []).map((tier) => tier.actualProviderPrice)]) {
      for (const key of ["uncachedInputPerMTokensUsd", "cachedInputPerMTokensUsd", "cacheWritePerMTokensUsd", "outputPerMTokensUsd", "providerFees"]) {
        assert.ok(Object.hasOwn(price, key), `${offer.priceKey}:${key}`);
      }
    }
  }
});

test("ACTUAL_AND_REFERENCE_PRICE_REMAIN_SEPARATE", () => {
  const offer = getSelectedPrice("deepseek-v4.1-flash");
  assert.notEqual(offer.pricing.actualProviderPrice, offer.pricing.standardReferencePrice);
  assert.equal(offer.pricing.actualProviderPrice.uncachedInputPerMTokensUsd, 0.2);
  assert.equal(offer.pricing.actualProviderPrice.outputPerMTokensUsd, 0.6);
});

test("NO_DEFAULT_CACHE_MULTIPLIERS", () => {
  const offer = getSelectedPrice("claude-sonnet-5");
  assert.equal(offer.pricing.actualProviderPrice.cachedInputPerMTokensUsd, null);
  assert.equal(offer.pricing.actualProviderPrice.cacheWritePerMTokensUsd, null);
  assert.throws(() => estimateOfferCostUsd(offer, 100, 10, undefined, { cachedInputTokens: 10 }), /CACHE_READ_PRICE_INCOMPLETE/);
});

test("CACHE_READ_AND_WRITE_PRICING_IS_PROVIDER_EXPLICIT", () => {
  const offer = getSelectedPrice("qwen3.8-flash");
  const cost = estimateOfferCostUsd(offer, 1_000_000, 1_000_000, "singapore", { cachedInputTokens: 1_000_000, cacheWriteTokens: 1_000_000 });
  assert.equal(cost, 0.15 + 0.016 + 0.2 + 0.47);
});

test("LAUNCH_PRIORITY_ROUTES_HAVE_EXACT_PROVIDER_FIXTURES", () => {
  const expected = {
    "deepseek-v4.1-flash": ["deepinfra", "deepseek-ai/DeepSeek-V4.1-Flash"],
    "glm-5.3-flash": ["deepinfra", "zai-org/GLM-5.3-Flash"],
    "mimo-v2.5": ["xiaomi_mimo", "mimo-v2.5"],
    "glm-5.2": ["deepinfra", "zai-org/GLM-5.2"],
    "minimax-m3": ["deepinfra", "MiniMaxAI/MiniMax-M3"],
    "kimi-k3": ["inference_net", "moonshotai/kimi-k3"],
    "qwen3.8-flash": ["alibaba_global", "qwen3.8-flash"],
    "gpt-5.6-luna": ["openai_direct", "gpt-5.6-luna"],
    "gpt-5.6-terra": ["openai_direct", "gpt-5.6-terra"],
    "gpt-5.6-sol": ["openai_direct", "gpt-5.6-sol"],
    "claude-sonnet-5": ["anthropic_direct", "claude-sonnet-5"],
    "claude-opus-5": ["anthropic_direct", "claude-opus-5"],
  };
  assert.equal(Object.keys(expected).length, 12);
  for (const [modelId, [provider, providerModelId]] of Object.entries(expected)) {
    const route = routes.routes.find((candidate) => candidate.canonicalModelId === modelId);
    assert.ok(route, modelId);
    assert.equal(route.priority, "launch", modelId);
    assert.equal(route.provider, provider, modelId);
    assert.equal(route.providerModelId, providerModelId, modelId);
  }
});

test("QWEN_FLASH_REGION_PRICING_IS_EXPLICIT", () => {
  const offer = getSelectedPrice("qwen3.8-flash");
  assert.ok(Array.isArray(offer.pricing.regionalPrices));
  assert.ok(offer.pricing.regionalPrices.some((entry) => entry.region === "global"));
  assert.ok(offer.pricing.regionalPrices.some((entry) => entry.region !== "global"));
  assert.notEqual(estimateCostUsd("qwen3.8-flash", 1_000_000, 1_000_000, { region: "global" }), estimateCostUsd("qwen3.8-flash", 1_000_000, 1_000_000, { region: "singapore" }));
  assert.throws(() => getBillablePrice("qwen3.8-flash", { region: "unknown-region" }), /BILLABLE_ROUTE_NOT_READY/);
});

test("PROMOTIONAL_ACTUAL_PRICE_DOES_NOT_OVERWRITE_REFERENCE", () => {
  const offer = getSelectedPrice("gpt-5.6-sol");
  assert.equal(offer.pricing.kind, "promotion");
  assert.ok(offer.pricing.actualProviderPrice);
  assert.ok(offer.pricing.standardReferencePrice);
  assert.notDeepEqual(offer.pricing.actualProviderPrice, offer.pricing.standardReferencePrice);
});

test("PROMOTIONS_HAVE_EXPLICIT_EXPIRY_POLICY", () => {
  for (const offer of prices.offers) {
    if (offer.pricing?.kind === "promotion") {
      assert.equal(offer.pricing.timeLimited, true, offer.priceKey);
      assert.ok(Object.hasOwn(offer.pricing, "expiresAt"), offer.priceKey);
      if (offer.pricing.expiresAt == null) assert.equal(offer.pricing.verificationStatus, "REVIEW_REQUIRED", offer.priceKey);
    }
  }
});

test("CHEAPER_BUT_INELIGIBLE_PROVIDER_NOT_RECOMMENDED", () => {
  const candidate = structuredClone(registry.offers[0]);
  candidate.canonicalModelId = "candidate-model";
  candidate.modelId = "candidate-model";
  candidate.operational.availability = "unknown";
  const result = evaluateProviderEligibility("candidate-model", candidate);
  assert.equal(result.eligible, false);
  assert.ok(result.reasons.includes("PROVIDER_AVAILABILITY_UNKNOWN"));
});

test("UNKNOWN_PROVIDER_CAPABILITY_NOT_ASSUMED_TRUE", () => {
  const candidate = structuredClone(registry.offers[0]);
  candidate.canonicalModelId = "candidate-model";
  candidate.modelId = "candidate-model";
  const result = evaluateProviderEligibility("candidate-model", candidate, { requiredCapabilities: ["tools"] });
  assert.equal(result.eligible, false);
  assert.ok(result.reasons.includes("CAPABILITY_UNKNOWN:tools"));
});

test("REGION_MISMATCH_NOT_ELIGIBLE", () => {
  const candidate = structuredClone(registry.offers[0]);
  candidate.canonicalModelId = "candidate-model";
  candidate.modelId = "candidate-model";
  candidate.region = "us-east";
  const result = evaluateProviderEligibility("candidate-model", candidate, { region: "eu-west" });
  assert.equal(result.eligible, false);
  assert.ok(result.reasons.includes("REGION_MISMATCH"));
});

test("CONTEXT_LIMIT_MISMATCH_NOT_ELIGIBLE", () => {
  const candidate = structuredClone(registry.offers[0]);
  candidate.canonicalModelId = "candidate-model";
  candidate.modelId = "candidate-model";
  candidate.operational.maxContextTokens = 8_000;
  const result = evaluateProviderEligibility("candidate-model", candidate, { requiredContextTokens: 16_000 });
  assert.equal(result.eligible, false);
  assert.ok(result.reasons.includes("CONTEXT_LIMIT_MISMATCH"));
});

test("TIER_SELECTION_CORRECT", () => {
  const offer = getSelectedPrice("qwen3.5-397b-a17b");
  assert.equal(estimateOfferCostUsd(offer, 100_000, 1_000), 0.018232);
  assert.equal(estimateOfferCostUsd(offer, 200_000, 1_000), 0.08858);
});

test("NO_TIER_FOR_CONTEXT_FAILS_VISIBLE", () => {
  const offer = getSelectedPrice("qwen3.5-397b-a17b");
  assert.throws(() => estimateOfferCostUsd(offer, 300_000, 1_000), /PRICE_TIER_NOT_FOUND/);
});

test("PROMOTION_EXPIRED_NOT_TRUSTED", () => {
  const offer = structuredClone(registry.offers[0]);
  offer.pricing.kind = "promotion";
  offer.pricing.timeLimited = true;
  offer.pricing.expiresAt = "2026-09-17T00:00:00Z";
  assert.equal((evaluateProviderEligibility("candidate-model", { ...offer, canonicalModelId: "candidate-model", modelId: "candidate-model" })).eligible, false);
});

test("PROMOTION_MALFORMED_EXPIRY_NOT_TRUSTED", () => {
  const offer = structuredClone(registry.offers[0]);
  offer.pricing.kind = "promotion";
  offer.pricing.timeLimited = true;
  offer.pricing.verified = true;
  offer.pricing.verificationStatus = "VERIFIED";
  offer.pricing.verifiedAt = "2026-09-18";
  offer.pricing.sourceUrl = "https://example.com/";
  offer.pricing.actualProviderPrice.uncachedInputPerMTokensUsd = 0.1;
  offer.pricing.actualProviderPrice.outputPerMTokensUsd = 0.2;
  offer.pricing.expiresAt = "not-a-date";
  assert.equal(isTrustedPricing({ ...offer, canonicalModelId: "candidate-model", modelId: "candidate-model", provider: "deepinfra", providerModelId: "x/y" }), false);
});

test("PROMOTION_WITHOUT_TIME_LIMIT_NOT_TRUSTED", () => {
  const offer = structuredClone(registry.offers[0]);
  offer.pricing.kind = "promotion";
  offer.pricing.timeLimited = false;
  offer.pricing.expiresAt = null;
  offer.pricing.verified = true;
  offer.pricing.verificationStatus = "VERIFIED";
  offer.pricing.verifiedAt = "2026-09-18";
  offer.pricing.sourceUrl = "https://example.com/";
  assert.equal(isTrustedPricing({ ...offer, canonicalModelId: "candidate-model", modelId: "candidate-model", provider: "deepinfra", providerModelId: "x/y" }), false);
});

test("UNVERIFIED_PRICE_NOT_PRODUCTION_BILLABLE", () => {
  assert.throws(() => getBillablePrice("deepseek-v3.1"), /BILLABLE_ROUTE_NOT_READY/);
});

test("BILLING_USES_SERVER_PRICE_AND_IGNORES_CLIENT_PRICE", () => {
  const cost = estimateCostUsd("deepseek-v4.1-flash", 1_000, 1_000, { clientPriceUsd: 0.000001 });
  assert.ok(Math.abs(cost - 0.0008) < Number.EPSILON);
});

test("NO_PROVIDER_SECRET_EXPOSURE", () => {
  assert.doesNotMatch(JSON.stringify(registry), /api[_-]?key|secret|accessToken|bearer/i);
});

test("DUPLICATE_ROUTE_REJECTED", () => {
  const routesDocument = { routes: [registry.routes[0], registry.routes[0]], policy: registry.policy };
  const result = validateRegistryData(routesDocument, { offers: registry.offers, policy: registry.policy });
  assert.ok(result.errors.some((error) => error.startsWith("DUPLICATE_ROUTE:")));
});

test("DUPLICATE_PRICE_KEY_REJECTED", () => {
  const pricesDocument = { offers: [registry.offers[0], registry.offers[0]], policy: registry.policy };
  const result = validateRegistryData({ routes: registry.routes, policy: registry.policy }, pricesDocument);
  assert.ok(result.errors.some((error) => error.startsWith("DUPLICATE_PRICE_KEY:")));
});
