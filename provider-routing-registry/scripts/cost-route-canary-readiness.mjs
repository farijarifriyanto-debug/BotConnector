import fs from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import yaml from "yaml";

const ROOT = "/home/botadmin/newbotconnector";
const candidatePath =
  process.env.BOTCONNECTOR_PROVIDER_ROUTE_CANDIDATES_FILE ||
  ROOT + "/worktrees/provider-routing-registry/config/provider-route-candidates.json";
const gatewayConfigPath =
  process.env.BOTCONNECTOR_GATEWAY_CONFIG_FILE ||
  ROOT + "/production-candidate/build/gateway/config.yaml";
const composePath =
  process.env.BOTCONNECTOR_CANDIDATE_COMPOSE_FILE ||
  ROOT + "/production-candidate/compose.yaml";
const capacityPath =
  process.env.BOTCONNECTOR_PROVIDER_CAPACITY_FILE ||
  ROOT + "/production-candidate/artifacts/provider-capacity-snapshot.json";
const presencePath =
  process.env.BOTCONNECTOR_PROVIDER_MODEL_PRESENCE_FILE ||
  ROOT + "/production-candidate/artifacts/provider-model-presence-snapshot.json";
const cacheContainer =
  process.env.BOTCONNECTOR_CACHE_CONTAINER || "botconnector-production-candidate-cache";
const maxAgeSeconds = 180;

const readJson = (path) => {
  try {
    return JSON.parse(fs.readFileSync(path, "utf8"));
  } catch {
    return null;
  }
};
const ageSeconds = (value) => {
  const ms = Date.parse(value || "");
  return Number.isFinite(ms) ? Math.max(0, (Date.now() - ms) / 1000) : Infinity;
};
const fresh = (snapshot) =>
  Boolean(snapshot?.checkedAt) && ageSeconds(snapshot.checkedAt) <= maxAgeSeconds;

function redis(args) {
  try {
    return execFileSync("docker", ["exec", cacheContainer, "redis-cli", "--raw", ...args], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch {
    return "";
  }
}
function hgetall(key) {
  const raw = redis(["HGETALL", key]);
  if (!raw) return {};
  const lines = raw.split(/\r?\n/);
  const out = {};
  for (let i = 0; i + 1 < lines.length; i += 2) out[lines[i]] = lines[i + 1];
  return out;
}
function healthKey(provider, model) {
  const h = createHash("sha256");
  h.update("botconnector-route-health-v1\0");
  h.update(provider);
  h.update("\0");
  h.update(model);
  return "botconnector:health:v1:route:" + h.digest("hex");
}
function capabilityTrue(candidate, name) {
  return candidate?.capabilities?.[name] === true;
}
function baseEligible(candidate, executable, capacity, presence, isPrimary) {
  if (!candidate || candidate.availability !== "available" || !executable) return false;

  const h = hgetall(healthKey(candidate.provider, candidate.providerModelId));
  if (h.circuit_state === "open") {
    const until = Number(h.cooldown_until_ms || 0);
    if (!Number.isFinite(until) || until > Date.now()) return false;
  }

  // Match the runtime resolver: the explicitly requested/current route does
  // not require alternate-provider model-presence proof. Alternate routes on
  // monitored providers do require a fresh positive /models proof.
  const monitored = presence?.providers?.[candidate.provider];
  if (!isPrimary && monitored) {
    if (!fresh(presence)) return false;
    if (monitored.status !== "AVAILABLE") return false;
    if (monitored.models?.[candidate.providerModelId] !== true) return false;
  }

  if (candidate.free) {
    const p = capacity?.providers?.[candidate.provider];
    if (!fresh(capacity) || !p || p.status !== "AVAILABLE") return false;
    if (!(Number(p.freeTokens?.remaining || 0) > 0)) return false;
  }

  return true;
}

const routesDoc = readJson(candidatePath);
const gateway = yaml.parse(fs.readFileSync(gatewayConfigPath, "utf8"));
const compose = yaml.parse(fs.readFileSync(composePath, "utf8"));
const capacity = readJson(capacityPath);
const presence = readJson(presencePath);

if (!routesDoc?.routes) throw new Error("ROUTE_CANDIDATES_UNAVAILABLE");

const activeRaw =
  compose?.services?.gateway?.environment?.BOTCONNECTOR_COST_ROUTE_ACTIVE_CANONICAL || "";

const executable = new Set();
const runtimeCanonicalModels = new Set();
for (const client of gateway?.clients ?? []) {
  for (const model of client?.models ?? []) {
    executable.add(client.name + "\0" + model.real_name);
    if (model?.name) runtimeCanonicalModels.add(model.name);
  }
}

const requestedActive = String(activeRaw)
  .split(",")
  .map((x) => x.trim())
  .filter(Boolean);
const wildcardActive = requestedActive.includes("*");
const active = wildcardActive
  ? [...runtimeCanonicalModels].sort()
  : requestedActive;

const rows = [];
let failed = false;
for (const canonicalModelId of active) {
  const route = routesDoc.routes.find((x) => x.canonicalModelId === canonicalModelId);
  if (!route) {
    failed = true;
    rows.push({
      canonicalModelId,
      status: "FAIL",
      reason: "ROUTE_NOT_FOUND",
      plainTextReady: false,
      toolsReady: false,
      visionReady: false,
      eligibleCandidates: [],
    });
    continue;
  }

  const candidates = route.candidates.map((candidate) => {
    const isExecutable = executable.has(candidate.provider + "\0" + candidate.providerModelId);
    const isPrimary =
      route.primary?.provider === candidate.provider &&
      route.primary?.providerModelId === candidate.providerModelId;
    const eligible = baseEligible(
      candidate,
      isExecutable,
      capacity,
      presence,
      isPrimary,
    );
    const h = hgetall(healthKey(candidate.provider, candidate.providerModelId));
    return {
      provider: candidate.provider,
      providerModelId: candidate.providerModelId,
      free: Boolean(candidate.free),
      executable: isExecutable,
      eligible,
      costSwitchEligible: candidate.costSwitchEligible !== false,
      runtimeCurrentOnly: candidate.runtimeCurrentOnly === true,
      pricingTrusted: candidate.pricingTrusted !== false,
      circuitState: h.circuit_state || "closed-or-unseen",
      cooldownUntilMs: Number(h.cooldown_until_ms || 0),
      toolsVerified: capabilityTrue(candidate, "tools"),
      visionVerified: capabilityTrue(candidate, "vision"),
    };
  });

  const executableCandidates = candidates.filter((x) => x.executable);
  if (!executableCandidates.length) {
    failed = true;
  }

  const eligible = candidates.filter((x) => x.eligible);
  const switchEligible = eligible.filter((x) => x.costSwitchEligible);
  const eligibleProviderCount = new Set(switchEligible.map((x) => x.provider)).size;
  const plainTextReady = eligibleProviderCount >= 2;
  const toolsReady =
    new Set(
      switchEligible.filter((x) => x.toolsVerified).map((x) => x.provider),
    ).size >= 2;
  const visionReady =
    new Set(
      switchEligible.filter((x) => x.visionVerified).map((x) => x.provider),
    ).size >= 2;

  const routingState = !executableCandidates.length
    ? "NO_EXECUTABLE_CURRENT_ROUTE"
    : plainTextReady
      ? "SWITCH_READY"
      : switchEligible.length > 0
        ? "LOCKED_SINGLE_PROVIDER"
        : "DEGRADED_FAIL_OPEN_CURRENT";

  rows.push({
    canonicalModelId,
    status: executableCandidates.length ? "PASS" : "FAIL",
    routingState,
    scope:
      plainTextReady && toolsReady && visionReady
        ? "plain-text+tools+vision"
        : plainTextReady && toolsReady
          ? "plain-text+tools"
          : plainTextReady && visionReady
            ? "plain-text+vision"
            : plainTextReady
              ? "plain-text-only"
              : "current-route-only",
    plainTextReady,
    toolsReady,
    visionReady,
    primary: route.primary,
    eligibleCandidates: eligible,
    switchEligibleCandidates: switchEligible,
    allCandidates: candidates,
  });
}

const report = {
  schema: "botconnector.cost-route-canary-readiness.v1",
  generatedAt: new Date().toISOString(),
  maxSnapshotAgeSeconds: maxAgeSeconds,
  wildcardActive,
  activeCanonicalModels: active,
  capacitySnapshot: {
    available: Boolean(capacity),
    fresh: fresh(capacity),
    checkedAt: capacity?.checkedAt ?? null,
  },
  modelPresenceSnapshot: {
    available: Boolean(presence),
    fresh: fresh(presence),
    checkedAt: presence?.checkedAt ?? null,
  },
  status: failed ? "FAIL" : "PASS",
  rows,
};

const outputArg = process.argv.find((x) => x.startsWith("--output="));
if (outputArg) {
  fs.writeFileSync(outputArg.slice("--output=".length), JSON.stringify(report, null, 2) + "\n");
}
if (process.argv.includes("--json")) {
  console.log(JSON.stringify(report, null, 2));
} else {
  console.log("COST_ROUTE_CANARY_READINESS=" + report.status);
  console.log("ACTIVE_CANONICAL=" + active.join(","));
  for (const row of rows) {
    console.log(
      JSON.stringify({
        canonicalModelId: row.canonicalModelId,
        status: row.status,
        routingState: row.routingState,
        scope: row.scope,
        plainTextReady: row.plainTextReady,
        toolsReady: row.toolsReady,
        visionReady: row.visionReady,
        eligibleProviders: row.eligibleCandidates?.map((x) => x.provider) ?? [],
      }),
    );
  }
}
if (failed) process.exitCode = 1;
