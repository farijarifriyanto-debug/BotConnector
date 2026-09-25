import fs from "node:fs";
import path from "node:path";
import yaml from "yaml";
import routesDocument from "../config/static-model-routes.json" with { type: "json" };
import pricesDocument from "../config/price-registry.json" with { type: "json" };
import aliasesDocument from "../config/exact-model-route-aliases.json" with { type: "json" };
import { evaluateProviderEligibility } from "../src/model-routing.ts";

const output = process.argv[2] || path.resolve("config/provider-route-candidates.json");
const gatewayConfigPath =
  process.argv[3] ||
  process.env.BOTCONNECTOR_GATEWAY_CONFIG_FILE ||
  null;
const now = new Date();

const byCanonical = new Map();
const runtimeSeedPriceKeys = new Map();
for (const route of routesDocument.routes) {
  if (!byCanonical.has(route.canonicalModelId)) {
    byCanonical.set(route.canonicalModelId, {
      canonicalModelId: route.canonicalModelId,
      displayName: route.displayName,
      primary: {
        provider: route.provider,
        providerModelId: route.providerModelId,
        priceKey: route.priceKey,
      },
      candidates: [],
    });
  }
}

// Exact-model alias coverage: a product/runtime SKU can intentionally share the
// same underlying model with an already-verified provider route without
// permitting cross-model substitution. Seed an entry from its own exact offer;
// alias price keys only add explicitly approved exact-model providers.
for (const alias of aliasesDocument.aliases ?? []) {
  if (byCanonical.has(alias.canonicalModelId)) continue;
  const primaryOffer =
    (alias.priceKeys ?? [])
      .map((priceKey) =>
        pricesDocument.offers.find((offer) => offer.priceKey === priceKey),
      )
      .find(Boolean) ??
    pricesDocument.offers.find(
      (offer) => offer.canonicalModelId === alias.canonicalModelId,
    );
  if (!primaryOffer) continue;
  byCanonical.set(alias.canonicalModelId, {
    canonicalModelId: alias.canonicalModelId,
    displayName: alias.canonicalModelId,
    primary: {
      provider: primaryOffer.provider,
      providerModelId: primaryOffer.providerModelId,
      priceKey: primaryOffer.priceKey,
    },
    candidates: [],
  });
}

// Runtime coverage augmentation: every executable gateway model with a trusted
// exact provider/model price offer gets at least a single-provider route entry.
// This does not create cross-model fallback. It only makes the currently
// executable route visible to the cost/health engine when static routing has
// not yet caught up with gateway inventory.
if (gatewayConfigPath && fs.existsSync(gatewayConfigPath)) {
  const gateway = yaml.parse(fs.readFileSync(gatewayConfigPath, "utf8"));
  for (const client of gateway?.clients ?? []) {
    for (const model of client?.models ?? []) {
      const canonicalModelId = model?.name;
      const providerModelId = model?.real_name;
      if (!canonicalModelId || !providerModelId) continue;

      const exactOffer = pricesDocument.offers.find(
        (offer) =>
          offer.provider === client.name &&
          offer.providerModelId === providerModelId &&
          offer.operational?.availability !== "unavailable",
      );
      if (!exactOffer) continue;

      const runtimeEligibility = evaluateProviderEligibility(
        exactOffer.canonicalModelId,
        exactOffer,
        {},
        now,
      );
      if (!byCanonical.has(canonicalModelId)) {
        byCanonical.set(canonicalModelId, {
          canonicalModelId,
          displayName: canonicalModelId,
          primary: {
            provider: client.name,
            providerModelId,
            priceKey: exactOffer.priceKey,
          },
          candidates: [],
        });
      }
      runtimeSeedPriceKeys.set(canonicalModelId, {
        priceKey: exactOffer.priceKey,
        pricingTrusted: runtimeEligibility.eligible,
      });
    }
  }
}

for (const [canonicalModelId, entry] of byCanonical) {
  const runtimeSeed = runtimeSeedPriceKeys.get(canonicalModelId);
  const exactAliasPriceKeys = new Set(
    (aliasesDocument.aliases ?? [])
      .filter((alias) => alias.canonicalModelId === canonicalModelId)
      .flatMap((alias) => alias.priceKeys ?? []),
  );
  const offers = pricesDocument.offers.filter(
    (offer) =>
      offer.canonicalModelId === canonicalModelId ||
      offer.priceKey === runtimeSeed?.priceKey ||
      exactAliasPriceKeys.has(offer.priceKey),
  );
  for (const offer of offers) {
    const eligibilityCanonical =
      offer.canonicalModelId === canonicalModelId ? canonicalModelId : offer.canonicalModelId;
    const eligibility = evaluateProviderEligibility(eligibilityCanonical, offer, {}, now);
    const isRuntimeCurrentOnly =
      runtimeSeed &&
      !runtimeSeed.pricingTrusted &&
      offer.priceKey === runtimeSeed.priceKey;
    if (!eligibility.eligible && !isRuntimeCurrentOnly) continue;
    const actual = offer.pricing.actualProviderPrice;
    const requiredRates = [
      actual.uncachedInputPerMTokensUsd,
      actual.outputPerMTokensUsd,
    ];
    const optionalRates = [
      actual.cachedInputPerMTokensUsd,
      actual.cacheWritePerMTokensUsd,
    ];
    if (
      requiredRates.some((value) => typeof value !== "number" || !Number.isFinite(value) || value < 0) ||
      optionalRates.some((value) => value != null && (typeof value !== "number" || !Number.isFinite(value) || value < 0))
    ) {
      continue;
    }
    const currentRoutePricingTrusted =
      !runtimeSeed || runtimeSeed.pricingTrusted;
    entry.candidates.push({
      provider: offer.provider,
      providerModelId: offer.providerModelId,
      priceKey: offer.priceKey,
      pricingKind: offer.pricing.kind,
      pricingTrusted: eligibility.eligible,
      costSwitchEligible:
        eligibility.eligible && currentRoutePricingTrusted,
      runtimeCurrentOnly: Boolean(isRuntimeCurrentOnly),
      free: offer.pricing.kind === "free" &&
        actual.uncachedInputPerMTokensUsd === 0 &&
        actual.outputPerMTokensUsd === 0,
      verifiedAt: offer.pricing.verifiedAt,
      availability: offer.operational.availability,
      maxContextTokens: offer.operational.maxContextTokens,
      maxOutputTokens: offer.operational.maxOutputTokens,
      pricing: {
        uncachedInputPerMTokensUsd: actual.uncachedInputPerMTokensUsd,
        cachedInputPerMTokensUsd: actual.cachedInputPerMTokensUsd,
        cacheWritePerMTokensUsd: actual.cacheWritePerMTokensUsd,
        outputPerMTokensUsd: actual.outputPerMTokensUsd,
      },
      capabilities: offer.capabilities,
    });
  }
  entry.candidates.sort((a, b) => {
    if (a.free !== b.free) return a.free ? -1 : 1;
    // Deterministic fresh-cost baseline only. Runtime re-scores with observed
    // cache ratios and request-specific input/output token estimates.
    const aBaseline = (a.pricing.uncachedInputPerMTokensUsd ?? Number.POSITIVE_INFINITY) * 0.8 +
      (a.pricing.outputPerMTokensUsd ?? Number.POSITIVE_INFINITY) * 0.2;
    const bBaseline = (b.pricing.uncachedInputPerMTokensUsd ?? Number.POSITIVE_INFINITY) * 0.8 +
      (b.pricing.outputPerMTokensUsd ?? Number.POSITIVE_INFINITY) * 0.2;
    if (aBaseline !== bBaseline) return aBaseline - bBaseline;
    if (a.provider === entry.primary.provider) return -1;
    if (b.provider === entry.primary.provider) return 1;
    return a.provider.localeCompare(b.provider);
  });
}

const routes = [...byCanonical.values()].filter((entry) => entry.candidates.length > 0);
const document = {
  schema: "botconnector.provider-route-candidates.v1",
  generatedAt: now.toISOString(),
  source: {
    registry: "botconnector-model-routing-registry",
    staticRouteCount: routesDocument.routes.length,
    priceOfferCount: pricesDocument.offers.length,
    exactModelAliasCount: (aliasesDocument.aliases ?? []).length,
  },
  policy: {
    canonicalModelLocked: true,
    providerFallback: "same-canonical-model-only",
    autoModelSwitch: false,
    unverifiedExcluded: true,
    unavailableExcluded: true,
    runtimeExecutionIntersectionRequired: true,
    capacityCheckRequiredForFreeRoutes: true,
  },
  routes,
};

fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, JSON.stringify(document, null, 2) + "\n");
console.log("PROVIDER_ROUTE_CANDIDATES=PASS");
console.log("OUTPUT=" + output);
console.log("CANONICAL_ROUTES=" + routes.length);
console.log("MULTI_PROVIDER_CANONICAL=" + routes.filter((entry) => new Set(entry.candidates.map((x) => x.provider)).size > 1).length);
