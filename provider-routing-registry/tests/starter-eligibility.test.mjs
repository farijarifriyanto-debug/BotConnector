import assert from "node:assert/strict";
import test from "node:test";
import routesDocument from "../config/static-model-routes.json" with { type: "json" };
import pricesDocument from "../config/price-registry.json" with { type: "json" };
import { buildStarterRoutePolicy } from "../src/model-routing.ts";

test("starter policy is explicit and fail-closed for the frozen registry", () => {
  const policy = buildStarterRoutePolicy(routesDocument);
  assert.equal(policy.routes.length, routesDocument.routes.length);

  const eligibleRoutes = policy.routes.filter((route) => route.starterFreeEligible === true);
  assert.equal(policy.eligibleRouteCount, eligibleRoutes.length);
  assert.ok(eligibleRoutes.length > 0);

  const offersByKey = new Map(pricesDocument.offers.map((offer) => [offer.priceKey, offer]));
  const sourceRoutesByCanonical = new Map(
    routesDocument.routes.map((route) => [route.canonicalModelId, route]),
  );

  for (const route of eligibleRoutes) {
    const sourceRoute = sourceRoutesByCanonical.get(route.canonicalModelId);
    assert.ok(sourceRoute, "eligible route must exist in source registry");
    const offer = offersByKey.get(sourceRoute.priceKey);
    assert.ok(offer, "eligible route must have a price offer");

    assert.equal(offer.canonicalModelId, route.canonicalModelId);
    assert.equal(offer.provider, route.provider);
    assert.equal(offer.providerModelId, route.providerModelId);
    assert.equal(offer.pricing.kind, "free");
    assert.equal(offer.pricing.actualProviderPrice.uncachedInputPerMTokensUsd, 0);
    assert.equal(offer.pricing.actualProviderPrice.outputPerMTokensUsd, 0);
    assert.equal(offer.pricing.verified, true);
    assert.equal(offer.pricing.verificationStatus, "VERIFIED");
    assert.equal(offer.operational.availability, "available");
  }
});
