import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const routesPath = path.join(root, "config/static-model-routes.json");
const originalRoutes = fs.readFileSync(routesPath, "utf8");

test("PRICE_UPDATE_DOES_NOT_CHANGE_ROUTE", () => {
  const before = JSON.parse(originalRoutes);
  const after = JSON.parse(fs.readFileSync(routesPath, "utf8"));
  assert.deepEqual(after.routes.map((route) => [route.modelId, route.provider]), before.routes.map((route) => [route.modelId, route.provider]));
  assert.equal(after.policy.autoSwitchProvider, false);
});

test("PRICE_DRIFT_IS_REVIEW_ONLY", () => {
  const output = execFileSync(process.execPath, [path.join(root, "scripts/check-price-drift.mjs")], { cwd: root, encoding: "utf8" });
  assert.match(output, /ROUTES_CHANGED=0/);
  for (const line of output.split("\n").filter((line) => line.includes("CHEAPER_PROVIDER_DETECTED"))) {
    assert.match(line, /ACTION=REVIEW_ONLY/);
  }
});

test("VALIDATOR_REPORTS_FRESHNESS_CLASSES", () => {
  const output = execFileSync(process.execPath, [path.join(root, "scripts/validate-registry.mjs")], { cwd: root, encoding: "utf8" });
  for (const label of ["VERIFIED_SELECTED=", "UNVERIFIED_SELECTED=", "STALE_SELECTED=", "PROMOTIONAL_SELECTED=", "SINGLE_OFFER_MODELS=", "MULTI_OFFER_MODELS="]) {
    assert.match(output, new RegExp(`^${label}`, "m"));
  }
});

test("AUTHORITY_BRIDGE_COVERS_ALL_ROUTES_AND_VALIDATES", () => {
  const bridge = JSON.parse(fs.readFileSync(path.join(root, "config/canonical-authority-bridge.json"), "utf8"));
  assert.equal(bridge.schema, "botconnector.canonical-authority-bridge.v1");
  assert.equal(bridge.routes.length, JSON.parse(originalRoutes).routes.length);
  const routeRefs = new Set(bridge.routes.map((entry) => entry.routeRef));
  assert.equal(routeRefs.size, bridge.routes.length);
  for (const route of JSON.parse(originalRoutes).routes) {
    assert.ok(routeRefs.has(`${route.modelId}:${route.provider}`), route.modelId);
    assert.ok(["VERIFIED_SEED", "VERIFIED_SEED_NORMALIZED_TURBO", "PENDING_AUTHORITY_ENRICHMENT"].includes(bridge.routes.find((entry) => entry.routeRef === `${route.modelId}:${route.provider}`).membership));
  }
});

test("AUTHORITY_BRIDGE_IS_NOT_A_MODEL_CATALOG", () => {
  const bridge = JSON.parse(fs.readFileSync(path.join(root, "config/canonical-authority-bridge.json"), "utf8"));
  for (const entry of bridge.routes) {
    for (const forbidden of ["family", "capabilities", "targets", "status", "commercial"]) {
      assert.ok(!Object.hasOwn(entry, forbidden), `${entry.routeRef}:${forbidden}`);
    }
  }
});

test("AUTHORITY_SNAPSHOT_IS_VERBATIM_PMR_EXPORT", () => {
  const snapshot = JSON.parse(fs.readFileSync(path.join(root, "config/product-model-registry-snapshot.json"), "utf8"));
  assert.equal(snapshot.schema, "botconnector.pmr-snapshot.v1");
  assert.ok(Array.isArray(snapshot.models));
  for (const model of snapshot.models) {
    assert.match(model.id, /^(hf|vendor):.+\/.+$/, model.id);
  }
});

test("BRIDGE_VALIDATION_DETECTS_TAMPERED_ENTRY", async () => {
  const { validateCanonicalAuthorityBridge } = await import("../src/model-routing.ts");
  const bridge = JSON.parse(fs.readFileSync(path.join(root, "config/canonical-authority-bridge.json"), "utf8"));
  const routes = JSON.parse(originalRoutes);
  const tampered = structuredClone(bridge);
  tampered.routes[0].canonicalModelId = "wrong-model";
  const result = validateCanonicalAuthorityBridge({ routes: routes.routes }, tampered, undefined);
  assert.ok(result.errors.some((error) => error.startsWith("AUTHORITY_BRIDGE_MODEL_MISMATCH:")));
  const missing = structuredClone(bridge);
  missing.routes = missing.routes.slice(1);
  const resultMissing = validateCanonicalAuthorityBridge({ routes: routes.routes }, missing, undefined);
  assert.ok(resultMissing.errors.some((error) => error.startsWith("AUTHORITY_BRIDGE_ENTRY_MISSING:")));
});
