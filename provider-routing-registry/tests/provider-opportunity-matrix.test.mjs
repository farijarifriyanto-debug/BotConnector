import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const ROOT = path.resolve(import.meta.dirname, "..");
const SCRIPT = path.join(ROOT, "scripts/provider-opportunity-matrix.mjs");

test("shadow exact-name opportunity never becomes switch-ready without executable trusted route", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "bc-provider-opportunity-"));
  try {
    const gatewayPath = path.join(dir, "gateway.yaml");
    const routesPath = path.join(dir, "routes.json");
    const shadowPath = path.join(dir, "shadow.json");
    const gatesPath = path.join(dir, "gates.json");

    fs.writeFileSync(
      gatewayPath,
      [
        "clients:",
        "  - name: primary",
        "    models:",
        "      - name: model-a",
        "        real_name: upstream/model-a",
        "      - name: model-b",
        "        real_name: upstream/model-b",
        "      - name: model-c",
        "        real_name: upstream/model-c",
        "  - name: alternate",
        "    models:",
        "      - name: model-a-alt",
        "        real_name: alternate/model-a",
        "",
      ].join("\n"),
    );

    fs.writeFileSync(
      routesPath,
      JSON.stringify({
        routes: [
          {
            canonicalModelId: "model-a",
            candidates: [
              {
                provider: "primary",
                providerModelId: "upstream/model-a",
                availability: "available",
                pricingTrusted: true,
                costSwitchEligible: true,
                runtimeCurrentOnly: false,
              },
              {
                provider: "alternate",
                providerModelId: "alternate/model-a",
                availability: "available",
                pricingTrusted: true,
                costSwitchEligible: true,
                runtimeCurrentOnly: false,
              },
            ],
          },
          {
            canonicalModelId: "model-b",
            candidates: [
              {
                provider: "primary",
                providerModelId: "upstream/model-b",
                availability: "available",
                pricingTrusted: true,
                costSwitchEligible: true,
                runtimeCurrentOnly: false,
              },
            ],
          },
          {
            canonicalModelId: "model-c",
            candidates: [
              {
                provider: "primary",
                providerModelId: "upstream/model-c",
                availability: "available",
                pricingTrusted: false,
                costSwitchEligible: false,
                runtimeCurrentOnly: true,
              },
            ],
          },
        ],
      }),
    );

    fs.writeFileSync(
      shadowPath,
      JSON.stringify({
        provider: "nara",
        activationPolicy: "SHADOW_ONLY",
        entitlementVerified: false,
        pricingVerified: false,
        commercialScopeVerified: false,
        exactModelIds: ["model-b", "model-c"],
      }),
    );

    fs.writeFileSync(
      gatesPath,
      JSON.stringify({
        provider: "nara",
        activationPolicy: "FAIL_CLOSED",
        requiredGates: [
          "modelListed",
          "entitlementVerified",
          "pricingVerified",
          "commercialScopeVerified",
          "capabilitiesVerified",
          "executionClientReady",
        ],
        models: {
          "model-b": {
            modelListed: true,
            entitlementVerified: false,
            pricingVerified: false,
            commercialScopeVerified: false,
            capabilitiesVerified: false,
            executionClientReady: false,
          },
          "model-c": {
            modelListed: true,
            entitlementVerified: false,
            pricingVerified: false,
            commercialScopeVerified: false,
            capabilitiesVerified: false,
            executionClientReady: false,
          },
        },
      }),
    );

    const raw = execFileSync(
      process.execPath,
      [SCRIPT, "--json"],
      {
        cwd: ROOT,
        encoding: "utf8",
        env: {
          ...process.env,
          BOTCONNECTOR_GATEWAY_CONFIG_FILE: gatewayPath,
          BOTCONNECTOR_PROVIDER_ROUTE_CANDIDATES_FILE: routesPath,
          BOTCONNECTOR_PROVIDER_SHADOW_OPPORTUNITIES_FILE: shadowPath,
          BOTCONNECTOR_PROVIDER_SHADOW_ACTIVATION_GATES_FILE: gatesPath,
        },
      },
    );
    const report = JSON.parse(raw);
    const byId = Object.fromEntries(
      report.rows.map((row) => [row.canonicalModelId, row]),
    );

    assert.equal(byId["model-a"].state, "SWITCH_READY");
    assert.equal(
      byId["model-b"].state,
      "SHADOW_EXACT_PROVIDER_PENDING_VERIFICATION",
    );
    assert.equal(
      byId["model-c"].state,
      "CURRENT_ROUTE_ONLY_UNTRUSTED",
    );

    assert.equal(byId["model-b"].executableProviderCount, 1);
    assert.equal(byId["model-b"].shadowOpportunities.length, 1);
    assert.equal(byId["model-b"].shadowOpportunities[0].readyToPromote, false);
    assert.deepEqual(
      byId["model-b"].shadowOpportunities[0].requiredGates,
      [
        "modelListed",
        "entitlementVerified",
        "pricingVerified",
        "commercialScopeVerified",
        "capabilitiesVerified",
        "executionClientReady",
      ],
    );
    assert.equal(
      byId["model-b"].shadowOpportunities[0].gates.entitlementVerified,
      false,
    );
    assert.equal(
      byId["model-b"].shadowOpportunities[0].gates.executionClientReady,
      false,
    );
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
