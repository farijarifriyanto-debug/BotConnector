import fs from "node:fs";
import yaml from "yaml";

const ROOT = "/home/botadmin/newbotconnector";
const gatewayConfigPath =
  process.env.BOTCONNECTOR_GATEWAY_CONFIG_FILE ||
  ROOT + "/production-candidate/build/gateway/config.yaml";
const routeCandidatesPath =
  process.env.BOTCONNECTOR_PROVIDER_ROUTE_CANDIDATES_FILE ||
  ROOT + "/worktrees/provider-routing-registry/config/provider-route-candidates.json";
const shadowPath =
  process.env.BOTCONNECTOR_PROVIDER_SHADOW_OPPORTUNITIES_FILE ||
  ROOT + "/worktrees/provider-routing-registry/config/provider-shadow-opportunities.json";
const activationGatesPath =
  process.env.BOTCONNECTOR_PROVIDER_SHADOW_ACTIVATION_GATES_FILE ||
  ROOT + "/worktrees/provider-routing-registry/config/provider-shadow-activation-gates.json";

const gateway = yaml.parse(fs.readFileSync(gatewayConfigPath, "utf8"));
const routesDoc = JSON.parse(fs.readFileSync(routeCandidatesPath, "utf8"));
const shadow = JSON.parse(fs.readFileSync(shadowPath, "utf8"));
const activationGates = JSON.parse(
  fs.readFileSync(activationGatesPath, "utf8"),
);

const runtimeModels = new Set();
const executable = new Set();
for (const client of gateway?.clients ?? []) {
  for (const model of client?.models ?? []) {
    if (model?.name) runtimeModels.add(model.name);
    executable.add(client.name + "\0" + model.real_name);
  }
}

const shadowExact = new Set(shadow.exactModelIds ?? []);
const rows = [];

for (const canonicalModelId of [...runtimeModels].sort()) {
  const route = (routesDoc.routes ?? []).find(
    (x) => x.canonicalModelId === canonicalModelId,
  );
  const candidates = (route?.candidates ?? []).map((candidate) => ({
    provider: candidate.provider,
    providerModelId: candidate.providerModelId,
    executable: executable.has(
      candidate.provider + "\0" + candidate.providerModelId,
    ),
    availability: candidate.availability,
    pricingTrusted: candidate.pricingTrusted !== false,
    costSwitchEligible: candidate.costSwitchEligible !== false,
    runtimeCurrentOnly: candidate.runtimeCurrentOnly === true,
  }));

  const executableSwitchCandidates = candidates.filter(
    (x) =>
      x.executable &&
      x.availability === "available" &&
      x.pricingTrusted &&
      x.costSwitchEligible &&
      !x.runtimeCurrentOnly,
  );
  const executableProviderCount = new Set(
    executableSwitchCandidates.map((x) => x.provider),
  ).size;

  const gate = activationGates.models?.[canonicalModelId] ?? null;
  const requiredGates = activationGates.requiredGates ?? [];
  const missingGates = requiredGates.filter(
    (name) => gate?.[name] !== true,
  );
  const readyToPromote =
    Boolean(gate) &&
    requiredGates.length > 0 &&
    missingGates.length === 0;

  let state = "LOCKED_SINGLE_PROVIDER";
  if (!route) state = "NO_ROUTE_AUTHORITY";
  else if (executableProviderCount >= 2) state = "SWITCH_READY";
  else if (
    candidates.some(
      (x) =>
        x.executable &&
        (x.runtimeCurrentOnly || !x.pricingTrusted || !x.costSwitchEligible),
    )
  )
    state = "CURRENT_ROUTE_ONLY_UNTRUSTED";
  else if (shadowExact.has(canonicalModelId) && readyToPromote)
    state = "SHADOW_VERIFIED_READY_FOR_ROUTE_PROMOTION";
  else if (shadowExact.has(canonicalModelId))
    state = "SHADOW_EXACT_PROVIDER_PENDING_VERIFICATION";

  rows.push({
    canonicalModelId,
    state,
    executableProviderCount,
    currentCandidates: candidates,
    shadowOpportunities: shadowExact.has(canonicalModelId)
      ? [
          {
            provider: shadow.provider,
            providerModelId: canonicalModelId,
            activationPolicy: shadow.activationPolicy,
            gates: gate,
            requiredGates,
            missingGates,
            readyToPromote,
          },
        ]
      : [],
  });
}

const counts = {};
for (const row of rows) counts[row.state] = (counts[row.state] ?? 0) + 1;

const report = {
  schema: "botconnector.provider-opportunity-matrix.v1",
  generatedAt: new Date().toISOString(),
  runtimeModelCount: rows.length,
  shadowProvider: shadow.provider,
  shadowActivationPolicy: shadow.activationPolicy,
  counts,
  rows,
};

const outArg = process.argv.find((x) => x.startsWith("--output="));
if (outArg) {
  fs.writeFileSync(outArg.slice("--output=".length), JSON.stringify(report, null, 2) + "\n");
}

if (process.argv.includes("--json")) {
  console.log(JSON.stringify(report, null, 2));
} else {
  console.log("PROVIDER_OPPORTUNITY_MATRIX=PASS");
  console.log("RUNTIME_MODELS=" + report.runtimeModelCount);
  for (const [state, count] of Object.entries(counts).sort()) {
    console.log(state + "=" + count);
  }
  for (const row of rows) {
    console.log(
      JSON.stringify({
        canonicalModelId: row.canonicalModelId,
        state: row.state,
        executableProviderCount: row.executableProviderCount,
        shadowProviders: row.shadowOpportunities.map((x) => x.provider),
      }),
    );
  }
}
