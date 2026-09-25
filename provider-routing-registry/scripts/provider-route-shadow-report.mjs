import fs from "node:fs";
import yaml from "yaml";

const candidatePath = process.argv[2] || "config/provider-route-candidates.json";
const gatewayConfigPath =
  process.argv[3] ||
  "/home/botadmin/newbotconnector/production-candidate/build/gateway/config.yaml";
const document = JSON.parse(fs.readFileSync(candidatePath, "utf8"));
const gateway = yaml.parse(fs.readFileSync(gatewayConfigPath, "utf8"));

const executable = new Set();
for (const client of gateway.clients ?? []) {
  for (const model of client.models ?? []) {
    executable.add(client.name + "\0" + model.real_name);
  }
}

const providerCount = (items) => new Set(items.map((candidate) => candidate.provider)).size;
const capabilityTrue = (candidate, name) => candidate.capabilities?.[name] === true;

const rows = [];
for (const route of document.routes) {
  const candidates = route.candidates.map((candidate) => ({
    ...candidate,
    executable: executable.has(candidate.provider + "\0" + candidate.providerModelId),
  }));
  const live = candidates.filter((candidate) => candidate.executable);
  const toolVerified = live.filter((candidate) => capabilityTrue(candidate, "tools"));
  const visionVerified = live.filter((candidate) => capabilityTrue(candidate, "vision"));
  const exactProviderCount = providerCount(live);

  rows.push({
    canonicalModelId: route.canonicalModelId,
    primary: route.primary,
    executableCandidates: live,
    exactProviderCount,
    toolVerifiedProviderCount: providerCount(toolVerified),
    visionVerifiedProviderCount: providerCount(visionVerified),
    switchReadyPlainText: exactProviderCount >= 2,
    switchReadyTools: providerCount(toolVerified) >= 2,
    switchReadyVision: providerCount(visionVerified) >= 2,
  });
}

const multi = rows.filter((row) => row.switchReadyPlainText);
console.log("PROVIDER_ROUTE_SHADOW=PASS");
console.log("EXECUTION_IDENTITIES=" + executable.size);
console.log("SWITCH_READY_PLAIN_TEXT_CANONICAL=" + multi.length);
console.log(
  "SWITCH_READY_TOOLS_CANONICAL=" +
    rows.filter((row) => row.switchReadyTools).length,
);
console.log(
  "SWITCH_READY_VISION_CANONICAL=" +
    rows.filter((row) => row.switchReadyVision).length,
);
for (const row of multi) {
  console.log(JSON.stringify(row));
}
