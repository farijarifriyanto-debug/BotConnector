import fs from "node:fs";
import path from "node:path";
import { classifyRoute, isTrustedPricing, registry } from "../src/model-routing.ts";

const root = path.resolve(import.meta.dirname, "..");
const checklistPath = path.join(root, "reports/baseline-reverify-58.txt");
const entries = fs
  .readFileSync(checklistPath, "utf8")
  .split("\n")
  .map((line) => line.trim())
  .filter((line) => line.startsWith("PRICE_REVERIFY_REQUIRED:"))
  .map((line) => {
    const rest = line.slice("PRICE_REVERIFY_REQUIRED:".length);
    const index = rest.lastIndexOf(":");
    return { modelId: rest.slice(0, index), provider: rest.slice(index + 1) };
  });

if (entries.length !== 58) {
  console.error(`ERROR BASELINE_CHECKLIST_COUNT=${entries.length} expected 58`);
  process.exit(1);
}

const offerByKey = new Map(registry.offers.map((offer) => [offer.priceKey, offer]));
const routeByKey = new Map(registry.routes.map((route) => [`${route.modelId}:${route.provider}`, route]));

const statuses = new Map();
const lines = ["# Baseline-58 reverify per-item audit — 2026-09-18", "", "modelId|provider|presentAsOffer|stillSelected|priceKey|verificationStatus|verifiedAt|kind|trustClass|routeClass", ""];
let stillReverify = 0;
for (const entry of entries) {
  const key = `${entry.modelId}:${entry.provider}`;
  const offer = offerByKey.get(`${entry.provider}:${entry.modelId}`);
  const route = routeByKey.get(key);
  if (!offer) {
    lines.push(`${entry.modelId}|${entry.provider}|MISSING|${route ? "yes" : "no"}|—|—|—|—|ERROR_OFFER_MISSING|—`);
    stillReverify += 1;
    statuses.set("ERROR", (statuses.get("ERROR") ?? 0) + 1);
    continue;
  }
  const trusted = isTrustedPricing(offer);
  const trustClass = trusted ? "TRUSTED" : "REVIEW_REQUIRED";
  if (!trusted) stillReverify += 1;
  statuses.set(trustClass, (statuses.get(trustClass) ?? 0) + 1);
  const routeClass = route ? classifyRoute(route) : "NOT_SELECTED_ANYMORE";
  lines.push([
    entry.modelId,
    entry.provider,
    "yes",
    route ? "yes" : "no",
    offer.priceKey,
    offer.pricing.verificationStatus,
    offer.pricing.verifiedAt ?? "null",
    offer.pricing.kind,
    trustClass,
    routeClass,
  ].join("|"));
}
lines.push("", "## Summary", "", `BASELINE_ITEMS=58`, `PRESENT_AS_OFFER=${entries.length - [...statuses.keys()].filter((s) => s === "ERROR").length}`, `TRUSTED_NOW=${statuses.get("TRUSTED") ?? 0}`, `STILL_REVIEW_REQUIRED=${statuses.get("REVIEW_REQUIRED") ?? 0}`, `ERROR=${statuses.get("ERROR") ?? 0}`, "");
const output = path.join(root, "reports/baseline-reverify-58-audit.md");
fs.writeFileSync(output, `${lines.join("\n")}\n`);
console.log(`BASELINE_REVERIFY_AUDIT=COMPLETE`);
console.log(`BASELINE_ITEMS=58`);
console.log(`TRUSTED_NOW=${statuses.get("TRUSTED") ?? 0}`);
console.log(`STILL_REVIEW_REQUIRED=${statuses.get("REVIEW_REQUIRED") ?? 0}`);
console.log(`ERROR=${statuses.get("ERROR") ?? 0}`);
console.log(output);