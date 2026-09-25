import { findCheaperProviderDrift } from "../src/model-routing.ts";

const profile = {
  inputTokens: Number(process.env.INPUT_TOKENS ?? "100000"),
  outputTokens: Number(process.env.OUTPUT_TOKENS ?? "25000"),
  region: process.env.REGION || undefined,
  requiredContextTokens: process.env.CONTEXT_TOKENS ? Number(process.env.CONTEXT_TOKENS) : undefined,
  requiredCapabilities: process.env.REQUIRED_CAPABILITIES ? process.env.REQUIRED_CAPABILITIES.split(",").filter(Boolean) : undefined,
};

const warnings = findCheaperProviderDrift(profile);
for (const warning of warnings) {
  console.log([
    "CHEAPER_PROVIDER_DETECTED",
    `model=${warning.modelId}`,
    `selected=${warning.selectedProvider}`,
    `candidate=${warning.candidateProvider}`,
    `selectedEstimatedCost=${warning.selectedEstimatedCost.toFixed(8)}`,
    `candidateEstimatedCost=${warning.candidateEstimatedCost.toFixed(8)}`,
    `savingsPct=${warning.savingsPct.toFixed(2)}%`,
    `trafficProfile=${JSON.stringify(warning.trafficProfile)}`,
    `eligibilityEvidence=${JSON.stringify(warning.eligibilityEvidence)}`,
    `verifiedAt=${warning.verifiedAt ?? "null"}`,
    "ACTION=REVIEW_ONLY",
  ].join(" "));
}
console.log(`PRICE_DRIFT_COUNT=${warnings.length}`);
console.log("ROUTES_CHANGED=0");
