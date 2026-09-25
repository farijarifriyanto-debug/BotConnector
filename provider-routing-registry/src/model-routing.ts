import routesJson from "../config/static-model-routes.json" with { type: "json" };
import pricesJson from "../config/price-registry.json" with { type: "json" };

export type ProviderId = "deepinfra" | "chutes" | "novita" | "fireworks" | "alibaba_global" | "inference_net" | "together" | "xiaomi_mimo" | "xkiro" | "siliconflow" | "nararouter" | "opencode_zen" | "poolside" | "agnes" | "cohere" | "openrouter" | "openai_direct" | "anthropic_direct";
export type Availability = "available" | "unavailable" | "unknown";
export type PricingKind = "list" | "tiered" | "promotion" | "free";
export type VerificationStatus = "VERIFIED" | "REVIEW_REQUIRED";
export type PriceDimensions = { uncachedInputPerMTokensUsd: number | null; cachedInputPerMTokensUsd: number | null; cacheWritePerMTokensUsd: number | null; outputPerMTokensUsd: number | null; providerFees: { perRequestUsd: number | null; perMTokensUsd: number | null; notes: string | null } | null };
export type PricingTier = { maxInputTokens: number; actualProviderPrice: PriceDimensions; standardReferencePrice: PriceDimensions | null };
export type RegionalPrice = { region: string; deploymentScope: string; actualProviderPrice: PriceDimensions; standardReferencePrice: PriceDimensions | null; tiers?: PricingTier[] };
export type Pricing = { kind: PricingKind; currency: string; actualProviderPrice: PriceDimensions; standardReferencePrice: PriceDimensions | null; verified: boolean; verifiedAt: string | null; sourceUrl: string | null; effectiveAt: string | null; timeLimited: boolean; expiresAt: string | null; verificationStatus: VerificationStatus; tiers?: PricingTier[]; regionalPrices?: RegionalPrice[] };
export type ProviderCapabilities = { tools: boolean | "unknown"; structuredOutput: boolean | "unknown"; vision: boolean | "unknown"; reasoning: boolean | "unknown"; embeddings: boolean | "unknown" };
export type OperationalMetadata = { maxContextTokens: number | null; maxOutputTokens: number | null; availability: Availability; rateLimitKnown: boolean; notes: string | null };
export type PrivacyMetadata = { policyKnown: boolean; zeroDataRetention: boolean | "unknown"; regionConstraint: string | null };
export type StaticRoute = { modelId: string; canonicalModelId: string; displayName: string; family: string; provider: ProviderId; providerModelId: string; locked: true; selectionPolicy: "reviewed-static-primary"; priceKey: string; priority?: "launch"; starterFreeEligible?: boolean };
export type StarterRoutePolicyRoute = { modelId: string; canonicalModelId: string; provider: ProviderId; providerModelId: string; starterFreeEligible: boolean };
export type StarterRoutePolicy = { schema: "botconnector.starter-route-policy.v1"; eligibleRouteCount: number; routes: StarterRoutePolicyRoute[] };
export type PriceOffer = { priceKey: string; modelId: string; canonicalModelId: string; provider: ProviderId; providerModelId: string; region: string; deploymentScope: string; pricing: Pricing; capabilities: ProviderCapabilities; operational: OperationalMetadata; privacy: PrivacyMetadata; notes?: string };
export type TrafficProfile = { inputTokens: number; outputTokens: number; region?: string; requiredContextTokens?: number; requiredCapabilities?: string[] };
export type CacheUsage = { cachedInputTokens?: number; cacheWriteTokens?: number };
export type EligibilityRequirements = Omit<TrafficProfile, "inputTokens" | "outputTokens"> & { forBilling?: boolean };
export type EligibilityResult = { eligible: boolean; reasons: string[] };
export type RouteClassification = "VERIFIED_PRIMARY" | "REVIEW_REQUIRED" | "PROMOTIONAL_PRIMARY" | "UNAVAILABLE" | "UNKNOWN";
export type DriftWarning = { modelId: string; canonicalModelId: string; selectedProvider: ProviderId; candidateProvider: ProviderId; selectedEstimatedCost: number; candidateEstimatedCost: number; savingsPct: number; trafficProfile: TrafficProfile; eligibilityEvidence: string[]; verifiedAt: string | null; action: "REVIEW_ONLY" };

type RegistryPolicy = { freshness: { verifiedMaxAgeDays: number; promotionMaxAgeDays: number } };
const routesDocument = routesJson as unknown as { routes: StaticRoute[]; policy: RegistryPolicy };
const pricesDocument = pricesJson as unknown as { offers: PriceOffer[]; policy: RegistryPolicy };
const routes = routesDocument.routes;
const offers = pricesDocument.offers;
const routeByCanonicalId = new Map(routes.map((route) => [route.canonicalModelId, route]));
const offerByKey = new Map(offers.map((offer) => [offer.priceKey, offer]));

export function buildStarterRoutePolicy(document: { routes: StaticRoute[] } = routesDocument): StarterRoutePolicy {
  const policyRoutes = document.routes.map((route) => ({
    modelId: route.modelId ?? route.canonicalModelId,
    canonicalModelId: route.canonicalModelId,
    provider: route.provider,
    providerModelId: route.providerModelId,
    starterFreeEligible: route.starterFreeEligible === true,
  }));
  return {
    schema: "botconnector.starter-route-policy.v1",
    eligibleRouteCount: policyRoutes.filter((route) => route.starterFreeEligible).length,
    routes: policyRoutes,
  };
}

export const XKIRO_PROVIDER: ProviderId = "xkiro";

export function isXkiroRoute(route: StaticRoute): boolean {
  return route.provider === XKIRO_PROVIDER;
}

export function isXkiroEligibleForFreePool(route: StaticRoute, offer: PriceOffer): EligibilityResult {
  const reasons: string[] = [];

  if (!isXkiroRoute(route)) {
    reasons.push("NOT_XKIRO_ROUTE");
    return { eligible: false, reasons };
  }

  if (offer.pricing.kind !== "free") {
    reasons.push("NOT_FREE_PRICING");
  }

  if (offer.pricing.actualProviderPrice.uncachedInputPerMTokensUsd !== 0) {
    reasons.push("HAS_INPUT_COST");
  }

  if (offer.pricing.actualProviderPrice.outputPerMTokensUsd !== 0) {
    reasons.push("HAS_OUTPUT_COST");
  }

  if (offer.pricing.verificationStatus !== "VERIFIED") {
    reasons.push("NOT_VERIFIED");
  }

  if (!offer.pricing.verified) {
    reasons.push("PRICING_NOT_VERIFIED");
  }

  if (offer.operational.availability !== "available") {
    reasons.push("PROVIDER_UNAVAILABLE");
  }

  return { eligible: reasons.length === 0, reasons };
}

export const FREE_PROVIDER_IDS = new Set<ProviderId>(["xkiro", "siliconflow", "nararouter", "openrouter", "opencode_zen", "poolside", "agnes", "novita"]);

export function isPaidProvider(provider: ProviderId): boolean {
  return !FREE_PROVIDER_IDS.has(provider);
}

export function preventPaidEscape(currentProvider: ProviderId, targetProvider: ProviderId): EligibilityResult {
  const reasons: string[] = [];

  if (isPaidProvider(currentProvider) && targetProvider !== currentProvider) {
    reasons.push("PAID_PROVIDER_ESCAPE_PREVENTED");
  }

  if (targetProvider === XKIRO_PROVIDER && isPaidProvider(currentProvider)) {
    reasons.push("PAID_TO_FREE_SWITCH_BLOCKED");
  }

  return { eligible: reasons.length === 0, reasons };
}

function ageInDays(verifiedAt: string | null, now: Date): number | null {
  if (!verifiedAt) return null;
  const timestamp = Date.parse(verifiedAt);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, now.getTime() - timestamp) / 86_400_000;
}

function hasUsablePrice(price: PriceDimensions | null | undefined): boolean {
  return price?.uncachedInputPerMTokensUsd != null && price.outputPerMTokensUsd != null;
}

function regionalPriceFor(offer: PriceOffer, region?: string): RegionalPrice | null {
  const regional = offer.pricing.regionalPrices ?? [];
  if (!region) return regional.find((entry) => entry.region === offer.region) ?? regional.find((entry) => entry.region === "global") ?? null;
  return regional.length ? regional.find((entry) => entry.region === region) ?? null : null;
}

function pricingFor(offer: PriceOffer, region?: string): { actualProviderPrice: PriceDimensions; standardReferencePrice: PriceDimensions | null; tiers?: PricingTier[] } {
  return regionalPriceFor(offer, region) ?? offer.pricing;
}

export function isTrustedPricing(offer: PriceOffer, now = new Date(), region?: string): boolean {
  const pricing = offer.pricing;
  if (!pricing.verified || pricing.verificationStatus !== "VERIFIED") return false;
  if (pricing.kind === "promotion" && !pricing.timeLimited) return false;
  if (!pricing.sourceUrl || ageInDays(pricing.verifiedAt, now) == null) return false;
  const maxAge = pricing.kind === "promotion" || pricing.kind === "free" ? pricesDocument.policy.freshness.promotionMaxAgeDays : pricesDocument.policy.freshness.verifiedMaxAgeDays;
  if ((ageInDays(pricing.verifiedAt, now) ?? Infinity) > maxAge) return false;
  const expiresAtParsed = pricing.timeLimited ? Date.parse(pricing.expiresAt ?? "") : 0;
  if (pricing.timeLimited && (!pricing.expiresAt || Number.isNaN(expiresAtParsed) || expiresAtParsed <= now.getTime())) return false;
  const selected = pricingFor(offer, region);
  return hasUsablePrice(selected.actualProviderPrice) || (selected.tiers ?? []).some((tier) => hasUsablePrice(tier.actualProviderPrice));
}

export function getStaticRoute(canonicalModelId: string): StaticRoute {
  const route = routeByCanonicalId.get(canonicalModelId);
  if (!route) throw new Error(`MODEL_ROUTE_NOT_FOUND:${canonicalModelId}`);
  return route;
}

export function getSelectedPrice(canonicalModelId: string): PriceOffer {
  const route = getStaticRoute(canonicalModelId);
  const price = offerByKey.get(route.priceKey);
  if (!price) throw new Error(`PRICE_NOT_FOUND:${route.priceKey}`);
  if (price.canonicalModelId !== route.canonicalModelId) throw new Error(`PRICE_MODEL_MISMATCH:${canonicalModelId}`);
  if (price.provider !== route.provider || price.providerModelId !== route.providerModelId) throw new Error(`PRICE_PROVIDER_MISMATCH:${canonicalModelId}`);
  return price;
}

export function evaluateProviderEligibility(canonicalModelId: string, offer: PriceOffer, requirements: EligibilityRequirements = {}, now = new Date()): EligibilityResult {
  const reasons: string[] = [];
  if (offer.canonicalModelId !== canonicalModelId || offer.modelId !== canonicalModelId) reasons.push("MODEL_ID_MISMATCH");
  if (offer.operational.availability === "unavailable") reasons.push("PROVIDER_UNAVAILABLE");
  if (offer.operational.availability === "unknown") reasons.push("PROVIDER_AVAILABILITY_UNKNOWN");
  const regional = regionalPriceFor(offer, requirements.region);
  if (requirements.region && offer.region !== "global" && offer.region !== requirements.region) reasons.push("REGION_MISMATCH");
  if (requirements.region && offer.region === "global" && offer.pricing.regionalPrices?.length && !regional) reasons.push("REGION_PRICE_UNAVAILABLE");
  if (requirements.requiredContextTokens != null) {
    if (offer.operational.maxContextTokens == null) reasons.push("CONTEXT_LIMIT_UNKNOWN");
    else if (offer.operational.maxContextTokens < requirements.requiredContextTokens) reasons.push("CONTEXT_LIMIT_MISMATCH");
  }
  for (const capability of requirements.requiredCapabilities ?? []) {
    const value = offer.capabilities[capability as keyof ProviderCapabilities];
    if (value !== true) reasons.push(value === "unknown" ? `CAPABILITY_UNKNOWN:${capability}` : `CAPABILITY_MISSING:${capability}`);
  }
  if (!isTrustedPricing(offer, now, requirements.region)) reasons.push("PRICE_NOT_TRUSTED_OR_FRESH");
  if (requirements.forBilling && reasons.length) reasons.push("BILLABLE_ROUTE_REVIEW_REQUIRED");
  return { eligible: reasons.length === 0, reasons };
}

export function selectPricingTier(offer: PriceOffer, inputTokens: number, region?: string): PricingTier | null {
  const pricing = pricingFor(offer, region);
  const tiers = [...(pricing.tiers ?? offer.pricing.tiers ?? [])].sort((a, b) => a.maxInputTokens - b.maxInputTokens);
  if (!tiers.length) return null;
  return tiers.find((tier) => inputTokens <= tier.maxInputTokens) ?? null;
}

export function estimateOfferCostUsd(offer: PriceOffer, inputTokens: number, outputTokens: number, region?: string, cacheUsage: CacheUsage = {}): number {
  if (!Number.isSafeInteger(inputTokens) || inputTokens < 0 || !Number.isSafeInteger(outputTokens) || outputTokens < 0) throw new Error("TOKEN_COUNTS_INVALID");
  const cachedInputTokens = cacheUsage.cachedInputTokens ?? 0;
  const cacheWriteTokens = cacheUsage.cacheWriteTokens ?? 0;
  if (!Number.isSafeInteger(cachedInputTokens) || cachedInputTokens < 0 || !Number.isSafeInteger(cacheWriteTokens) || cacheWriteTokens < 0) throw new Error("CACHE_TOKEN_COUNTS_INVALID");
  const pricing = pricingFor(offer, region);
  const tier = selectPricingTier(offer, inputTokens + cachedInputTokens + cacheWriteTokens, region);
  const actual = tier?.actualProviderPrice ?? pricing.actualProviderPrice;
  if (actual.uncachedInputPerMTokensUsd == null || actual.outputPerMTokensUsd == null) throw new Error(`PRICE_INCOMPLETE:${offer.priceKey}`);
  if ((pricing.tiers ?? offer.pricing.tiers)?.length && !tier) throw new Error(`PRICE_TIER_NOT_FOUND:${offer.canonicalModelId}:${inputTokens}`);
  if (cachedInputTokens && actual.cachedInputPerMTokensUsd == null) throw new Error(`CACHE_READ_PRICE_INCOMPLETE:${offer.priceKey}`);
  if (cacheWriteTokens && actual.cacheWritePerMTokensUsd == null) throw new Error(`CACHE_WRITE_PRICE_INCOMPLETE:${offer.priceKey}`);
  const providerFee = actual.providerFees;
  const feeCost = providerFee ? (providerFee.perRequestUsd ?? 0) + ((inputTokens + cachedInputTokens + cacheWriteTokens + outputTokens) / 1_000_000) * (providerFee.perMTokensUsd ?? 0) : 0;
  return (inputTokens / 1_000_000) * actual.uncachedInputPerMTokensUsd + (cachedInputTokens / 1_000_000) * (actual.cachedInputPerMTokensUsd ?? 0) + (cacheWriteTokens / 1_000_000) * (actual.cacheWritePerMTokensUsd ?? 0) + (outputTokens / 1_000_000) * actual.outputPerMTokensUsd + feeCost;
}

export function getBillablePrice(canonicalModelId: string, requirements: EligibilityRequirements = {}, now = new Date()) {
  const route = getStaticRoute(canonicalModelId);
  const offer = getSelectedPrice(canonicalModelId);
  const eligibility = evaluateProviderEligibility(canonicalModelId, offer, { ...requirements, forBilling: true }, now);
  if (!eligibility.eligible) throw new Error(`BILLABLE_ROUTE_NOT_READY:${canonicalModelId}:${eligibility.reasons.join(",")}`);
  return { route, offer, eligibility };
}

export function estimateCostUsd(canonicalModelId: string, inputTokens: number, outputTokens: number, requirements: EligibilityRequirements = {}): number {
  return estimateOfferCostUsd(getBillablePrice(canonicalModelId, requirements).offer, inputTokens, outputTokens, requirements.region);
}

export function classifyRoute(route: StaticRoute, now = new Date()): RouteClassification {
  const offer = offerByKey.get(route.priceKey);
  if (!offer) return "UNKNOWN";
  if (offer.operational.availability === "unavailable") return "UNAVAILABLE";
  if (!isTrustedPricing(offer, now)) return "REVIEW_REQUIRED";
  if (offer.operational.availability === "unknown") return "UNKNOWN";
  return offer.pricing.kind === "promotion" || offer.pricing.kind === "free" ? "PROMOTIONAL_PRIMARY" : "VERIFIED_PRIMARY";
}

export function findCheaperProviderDrift(profile: TrafficProfile = { inputTokens: 100_000, outputTokens: 25_000 }): DriftWarning[] {
  const warnings: DriftWarning[] = [];
  for (const route of routes) {
    const selected = offerByKey.get(route.priceKey);
    if (!selected || !evaluateProviderEligibility(route.canonicalModelId, selected, profile).eligible) continue;
    const candidates = offers.filter((offer) => offer.provider !== route.provider && offer.canonicalModelId === route.canonicalModelId && evaluateProviderEligibility(route.canonicalModelId, offer, profile).eligible);
    const selectedCost = estimateOfferCostUsd(selected, profile.inputTokens, profile.outputTokens, profile.region);
    for (const candidate of candidates) {
      const candidateCost = estimateOfferCostUsd(candidate, profile.inputTokens, profile.outputTokens, profile.region);
      const savingsPct = selectedCost === 0 ? 0 : ((selectedCost - candidateCost) / selectedCost) * 100;
      if (savingsPct >= Number(process.env.MIN_SAVINGS_PCT ?? 5)) warnings.push({ modelId: route.modelId, canonicalModelId: route.canonicalModelId, selectedProvider: route.provider, candidateProvider: candidate.provider, selectedEstimatedCost: selectedCost, candidateEstimatedCost: candidateCost, savingsPct, trafficProfile: profile, eligibilityEvidence: ["ELIGIBLE", `REGION:${candidate.region}`, `VERIFIED_AT:${candidate.pricing.verifiedAt}`], verifiedAt: candidate.pricing.verifiedAt, action: "REVIEW_ONLY" });
    }
  }
  return warnings;
}

export function registryStats(now = new Date()) {
  const counts = new Map<string, number>();
  for (const offer of offers) counts.set(offer.canonicalModelId, (counts.get(offer.canonicalModelId) ?? 0) + 1);
  const selected = routes.map((route) => ({ route, offer: offerByKey.get(route.priceKey), status: classifyRoute(route, now) }));
  return { routes: routes.length, priceOffers: offers.length, verifiedSelected: selected.filter((entry) => entry.offer?.pricing.verified === true).length, unverifiedSelected: selected.filter((entry) => entry.offer?.pricing.verified !== true).length, staleSelected: selected.filter((entry) => entry.offer && !isTrustedPricing(entry.offer, now) && entry.offer.pricing.verified).length, promotionalSelected: selected.filter((entry) => entry.offer && (entry.offer.pricing.kind === "promotion" || entry.offer.pricing.kind === "free")).length, singleOfferModels: [...new Set(routes.map((route) => route.canonicalModelId))].filter((id) => counts.get(id) === 1).length, multiOfferModels: [...new Set(routes.map((route) => route.canonicalModelId))].filter((id) => (counts.get(id) ?? 0) > 1).length };
}

export type CanonicalAuthorityBridgeEntry = {
  routeRef: string;
  canonicalModelId: string;
  providerModelId: string;
  authoritySource: string;
  hfSourceId?: string;
  externalCanonicalId?: string;
  membership: string;
  relatedAuthorityRecords?: string[];
  relationNote?: string;
  normalizationApplied?: string;
};

export type CanonicalAuthorityBridgeDocument = {
  schema: string;
  authorityRegistry: { identityForm: string };
  routes: CanonicalAuthorityBridgeEntry[];
};

export type ProductModelRegistrySnapshot = {
  schema: string;
  generatedAt: string;
  models: { id: string; source: string; source_id: string }[];
};

function normalizeProviderModelIdForAuthority(providerModelId: string, authoritySource: string): string | null {
  if (authoritySource !== "hf") return null;
  let candidate = providerModelId;
  if (candidate.startsWith("accounts/fireworks/models/")) candidate = candidate.split("/").at(-1) ?? candidate;
  if (candidate.endsWith("-TEE")) candidate = candidate.slice(0, -4);
  return candidate.includes("/") ? candidate : null;
}

export function validateCanonicalAuthorityBridge(
  routesDocumentInput: { routes: StaticRoute[] },
  bridge: CanonicalAuthorityBridgeDocument,
  snapshot?: ProductModelRegistrySnapshot,
) {
  const errors: string[] = [];
  const warnings: string[] = [];
  if (bridge.schema !== "botconnector.canonical-authority-bridge.v1") errors.push(`AUTHORITY_BRIDGE_SCHEMA_INVALID:${bridge.schema}`);
  if (bridge.authorityRegistry?.identityForm !== "source:source_id (e.g. hf:org/repo)") errors.push("AUTHORITY_BRIDGE_IDENTITY_FORM_INVALID");
  const bridgeByRef = new Map(bridge.routes.map((entry) => [entry.routeRef, entry]));
  for (const route of routesDocumentInput.routes) {
    const entry = bridgeByRef.get(`${route.modelId}:${route.provider}`);
    if (!entry) { errors.push(`AUTHORITY_BRIDGE_ENTRY_MISSING:${route.modelId}:${route.provider}`); continue; }
    if (entry.canonicalModelId !== route.canonicalModelId) errors.push(`AUTHORITY_BRIDGE_MODEL_MISMATCH:${route.modelId}`);
    if (entry.providerModelId !== route.providerModelId) errors.push(`AUTHORITY_BRIDGE_PROVIDER_MODEL_MISMATCH:${route.modelId}`);
    if (entry.authoritySource === "hf") {
      const normalized = normalizeProviderModelIdForAuthority(entry.providerModelId, entry.authoritySource);
      if (!normalized) errors.push(`AUTHORITY_BRIDGE_HF_SOURCE_ID_DERIVATION_FAILED:${route.modelId}`);
      else if (entry.hfSourceId !== normalized) errors.push(`AUTHORITY_BRIDGE_HF_SOURCE_ID_MISMATCH:${route.modelId}`);
      if (entry.membership === "VERIFIED_SEED" || entry.membership === "VERIFIED_SEED_NORMALIZED_TURBO") {
        if (!entry.externalCanonicalId) errors.push(`AUTHORITY_BRIDGE_EXTERNAL_ID_REQUIRED:${route.modelId}`);
        else if (snapshot) {
          const known = snapshot.models.some((model) => model.id === entry.externalCanonicalId);
          if (!known) errors.push(`AUTHORITY_MEMBERSHIP_NOT_IN_SNAPSHOT:${route.modelId}:${entry.externalCanonicalId}`);
        } else {
          warnings.push(`AUTHORITY_MEMBERSHIP_UNVERIFIABLE_NO_SNAPSHOT:${route.modelId}`);
        }
      } else if (entry.membership !== "PENDING_AUTHORITY_ENRICHMENT") {
        errors.push(`AUTHORITY_BRIDGE_MEMBERSHIP_INVALID:${route.modelId}:${entry.membership}`);
      } else {
        warnings.push(`AUTHORITY_MEMBERSHIP_PENDING:${route.modelId}:${entry.authoritySource === "hf" ? "hf" : "vendor_catalog"}`);
      }
    } else if (entry.membership !== "PENDING_AUTHORITY_ENRICHMENT") {
      errors.push(`AUTHORITY_BRIDGE_MEMBERSHIP_INVALID:${route.modelId}:${entry.membership}`);
    } else {
      warnings.push(`AUTHORITY_MEMBERSHIP_PENDING:${route.modelId}:vendor_catalog`);
    }
  }
  if (snapshot?.schema !== "botconnector.pmr-snapshot.v1") errors.push(`AUTHORITY_SNAPSHOT_SCHEMA_INVALID:${snapshot?.schema ?? "missing"}`);
  return { errors, warnings };
}

export function validateRegistryData(routesDocumentInput: { routes: StaticRoute[] }, pricesDocumentInput: { offers: PriceOffer[] }) {
  const errors: string[] = [];
  const warnings: string[] = [];
  const routeIds = new Set<string>();
  const priceKeys = new Set<string>();
  const offerByKeyInput = new Map(pricesDocumentInput.offers.map((offer) => [offer.priceKey, offer]));
  for (const route of routesDocumentInput.routes) {
    if (routeIds.has(route.canonicalModelId)) errors.push(`DUPLICATE_ROUTE:${route.canonicalModelId}`);
    routeIds.add(route.canonicalModelId);
    if (!route.canonicalModelId) errors.push(`CANONICAL_MODEL_ID_REQUIRED:${route.modelId}`);
    if (route.selectionPolicy !== "reviewed-static-primary" || route.locked !== true) errors.push(`STATIC_PRIMARY_POLICY_REQUIRED:${route.modelId}`);
    const offer = offerByKeyInput.get(route.priceKey);
    if (!offer) { errors.push(`MISSING_SELECTED_PRICE:${route.canonicalModelId}:${route.priceKey}`); continue; }
    if (offer.canonicalModelId !== route.canonicalModelId) errors.push(`PRICE_MODEL_MISMATCH:${route.modelId}`);
    if (offer.provider !== route.provider || offer.providerModelId !== route.providerModelId) errors.push(`PRICE_PROVIDER_MISMATCH:${route.modelId}`);
  }
  for (const offer of pricesDocumentInput.offers) {
    if (priceKeys.has(offer.priceKey)) errors.push(`DUPLICATE_PRICE_KEY:${offer.priceKey}`);
    priceKeys.add(offer.priceKey);
    if (!offer.pricing?.actualProviderPrice || !Object.hasOwn(offer.pricing, "standardReferencePrice")) errors.push(`PRICE_DIMENSIONS_REQUIRED:${offer.priceKey}`);
  }
  return { errors, warnings };
}

export const registry = { routes, offers, policy: routesDocument.policy };
