import fs from "node:fs";
import path from "node:path";
import { classifyRoute, getSelectedPrice, isTrustedPricing, registry, registryStats, validateCanonicalAuthorityBridge, validateRegistryData } from "../src/model-routing.ts";

const validation = validateRegistryData({ routes: registry.routes }, { offers: registry.offers });

let bridgeResult = null;
let bridgeRoutes = [];
const bridgePath = path.join(path.resolve(import.meta.dirname, ".."), "config/canonical-authority-bridge.json");
const snapshotPath = path.join(path.resolve(import.meta.dirname, ".."), "config/product-model-registry-snapshot.json");
if (fs.existsSync(bridgePath)) {
  const bridge = JSON.parse(fs.readFileSync(bridgePath, "utf8"));
  bridgeRoutes = bridge.routes ?? [];
  const snapshot = fs.existsSync(snapshotPath) ? JSON.parse(fs.readFileSync(snapshotPath, "utf8")) : undefined;
  bridgeResult = validateCanonicalAuthorityBridge({ routes: registry.routes }, bridge, snapshot);
  for (const warning of bridgeResult.warnings) console.log(`WARN ${warning}`);
  validation.errors.push(...bridgeResult.errors);
}
const snapshotLoaded = fs.existsSync(snapshotPath);
const membershipVerified = bridgeRoutes.filter((entry) => entry.membership.startsWith("VERIFIED")).length;
const membershipPending = bridgeRoutes.filter((entry) => entry.membership === "PENDING_AUTHORITY_ENRICHMENT").length;
console.log(`AUTHORITY_BRIDGE_SCHEMA=${bridgeResult ? "VALIDATED" : "ABSENT"}`);
console.log(`AUTHORITY_BRIDGE_ENTRIES=${bridgeRoutes.length}`);
console.log(`AUTHORITY_SNAPSHOT_MODELS=${snapshotLoaded ? JSON.parse(fs.readFileSync(snapshotPath, "utf8")).models.length : 0}`);
console.log(`AUTHORITY_MEMBERSHIP_VERIFIED=${membershipVerified}`);
console.log(`AUTHORITY_MEMBERSHIP_PENDING=${membershipPending}`);
const warnings = [];
for (const route of registry.routes) {
  try {
    const selected = getSelectedPrice(route.canonicalModelId);
    if (!selected.pricing.sourceUrl) warnings.push(`SOURCE_REQUIRED:${route.modelId}`);
    if (!isTrustedPricing(selected)) warnings.push(`PRICE_REVERIFY_REQUIRED:${route.modelId}:${route.provider}`);
    console.log(`ROUTE_STATUS:${route.modelId}:${classifyRoute(route)}`);
  } catch (error) {
    validation.errors.push(error.message);
  }
}

const stats = registryStats();
console.log(`ROUTES=${stats.routes}`);
console.log(`PRICE_OFFERS=${stats.priceOffers}`);
console.log(`VERIFIED_SELECTED=${stats.verifiedSelected}`);
console.log(`UNVERIFIED_SELECTED=${stats.unverifiedSelected}`);
console.log(`STALE_SELECTED=${stats.staleSelected}`);
console.log(`PROMOTIONAL_SELECTED=${stats.promotionalSelected}`);
console.log(`SINGLE_OFFER_MODELS=${stats.singleOfferModels}`);
console.log(`MULTI_OFFER_MODELS=${stats.multiOfferModels}`);
for (const warning of warnings) console.log(`WARN ${warning}`);
for (const error of validation.errors) console.error(`ERROR ${error}`);
if (validation.errors.length) process.exit(1);
console.log("STATIC_MODEL_ROUTING_VALIDATION=PASS");
