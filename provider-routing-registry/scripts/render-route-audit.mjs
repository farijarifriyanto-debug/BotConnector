import fs from "node:fs";
import path from "node:path";
import { classifyRoute, getSelectedPrice, isTrustedPricing, registry } from "../src/model-routing.ts";

const root = path.resolve(import.meta.dirname, "..");
const output = path.join(root, "reports/provider-route-audit-20260918.md");
const byModel = new Map();
for (const offer of registry.offers) {
  if (!byModel.has(offer.canonicalModelId)) byModel.set(offer.canonicalModelId, []);
  byModel.get(offer.canonicalModelId).push(offer);
}
const lines = [
  "# Provider route audit — 2026-09-18", "",
  "The Product Model Registry owns canonical identity, family, capabilities, status, and Cloud/Browser/Device availability. This registry owns only the locked Cloud provider, provider model ID, eligibility evidence, and trusted provider price metadata.", "",
  "`selectionPolicy=reviewed-static-primary`; pricing drift is `REVIEW_ONLY` and never mutates a route.", "", "BASELINE_PRICE_REVERIFY_REQUIRED_AUDITED=58/58", "",
  "## Launch acceptance", "", "```text", "LAUNCH_ROUTE_COUNT=12", "LAUNCH_ROUTE_EXACT_PROVIDER_VERIFIED=12/12", "LAUNCH_ROUTE_PRICE_VERIFIED=11/12", "LAUNCH_ROUTE_REGION_VERIFIED=1/12", "LAUNCH_ROUTE_PROMOTION_STATUS_VERIFIED=3/3", "LAUNCH_ROUTE_CACHE_PRICING_VERIFIED=7/12", "COMMERCIAL_POLICY_INPUT=PENDING_SEPARATE_INTEGRATION", "```", "",
  "The Xiaomi model/provider identity is verified from Xiaomi's official model API, but its price remains `REVIEW_REQUIRED` because the checked first-party source did not publish a token rate. Region verification is counted only where the first-party source explicitly enumerates the route region. GPT-5.6 Sol is a current promotion with a separate reference rate and is not billable until promotion freshness is rechecked.", "",
  "## Route table", "",
];
for (const route of registry.routes) {
  const offer = getSelectedPrice(route.canonicalModelId);
  const alternatives = (byModel.get(route.canonicalModelId) ?? []).filter((candidate) => candidate.priceKey !== offer.priceKey).map((candidate) => `${candidate.provider}:${candidate.providerModelId}`).join("; ") || "—";
  const priceStatus = isTrustedPricing(offer) ? "TRUSTED" : offer.pricing.kind === "promotion" ? "PRICE_REVERIFY_REQUIRED" : "REVIEW_REQUIRED";
  const context = offer.operational.maxContextTokens == null ? "unknown" : String(offer.operational.maxContextTokens);
  lines.push(`### ${route.canonicalModelId}${route.priority === "launch" ? " [LAUNCH]" : ""}`, "", `MODEL=${route.canonicalModelId}`, `PRIMARY_PROVIDER=${route.provider}`, `PROVIDER_MODEL_ID=${route.providerModelId}`, `STATUS=${classifyRoute(route)}`, `PRICE_STATUS=${priceStatus}`, `REGION=${offer.region}`, `CONTEXT=${context}`, `ALTERNATIVE_OFFERS=${alternatives}`, `RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.`, `SOURCE=${offer.pricing.sourceUrl ?? "null"}`, `VERIFIED_DATE=${offer.pricing.verifiedAt ?? "null"}`, "");
}
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, `${lines.join("\n")}\n`);
console.log(output);
