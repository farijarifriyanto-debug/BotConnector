import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

test("runtime gateway augmentation covers executable models without enabling stale-price switching", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "bc-runtime-routes-"));
  const out = path.join(dir, "candidates.json");
  const gateway = path.join(dir, "gateway.yaml");
  fs.writeFileSync(
    gateway,
    `clients:
  - name: deepinfra
    models:
      - name: glm-5.3-flash
        real_name: zai-org/GLM-5.3-Flash
  - name: openai_direct
    models:
      - name: gpt-5.6-sol
        real_name: gpt-5.6-sol
  - name: xkiro
    models:
      - name: qwen3.7-flash-free
        real_name: qwen/qwen3.7-flash:free
`,
  );

  execFileSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "scripts/generate-provider-route-candidates.mjs",
      out,
      gateway,
    ],
    { cwd: process.cwd(), stdio: "pipe" },
  );

  const d = JSON.parse(fs.readFileSync(out, "utf8"));
  for (const id of ["glm-5.3-flash", "gpt-5.6-sol", "qwen3.7-flash-free"]) {
    assert.ok(d.routes.some((route) => route.canonicalModelId === id), id);
  }

  for (const id of ["glm-5.3-flash", "gpt-5.6-sol"]) {
    const route = d.routes.find((item) => item.canonicalModelId === id);
    assert.equal(route.candidates.length, 1);
    assert.equal(route.candidates[0].runtimeCurrentOnly, true);
    assert.equal(route.candidates[0].pricingTrusted, false);
    assert.equal(route.candidates[0].costSwitchEligible, false);
  }

  const xkiro = d.routes.find((item) => item.canonicalModelId === "qwen3.7-flash-free");
  assert.equal(xkiro.candidates[0].provider, "xkiro");
  assert.equal(xkiro.candidates[0].runtimeCurrentOnly, false);
  assert.equal(xkiro.candidates[0].pricingTrusted, true);
});

test("provider candidate artifact keeps canonical model locked and exposes exact MiniMax M3 routes", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "bc-routes-"));
  const out = path.join(dir, "candidates.json");
  execFileSync(process.execPath, [
    "--experimental-strip-types",
    "scripts/generate-provider-route-candidates.mjs",
    out,
  ], { cwd: process.cwd(), stdio: "pipe" });

  const d = JSON.parse(fs.readFileSync(out, "utf8"));
  assert.equal(d.policy.canonicalModelLocked, true);
  assert.equal(d.policy.providerFallback, "same-canonical-model-only");
  assert.equal(d.policy.autoModelSwitch, false);

  const minimax = d.routes.find((route) => route.canonicalModelId === "minimax-m3");
  assert.ok(minimax);
  const providers = new Set(minimax.candidates.map((candidate) => candidate.provider));
  assert.equal(providers.has("deepinfra"), true);
  assert.equal(providers.has("xkiro"), true);

  const xkiro = minimax.candidates.find((candidate) => candidate.provider === "xkiro");
  assert.equal(xkiro.providerModelId, "minimax/minimax-m3:free");
  assert.equal(xkiro.free, true);

  const starterMinimax = d.routes.find(
    (route) => route.canonicalModelId === "minimax-m3-free",
  );
  assert.ok(starterMinimax);
  const starterProviders = new Set(
    starterMinimax.candidates.map((candidate) => candidate.provider),
  );
  assert.equal(starterProviders.has("xkiro"), true);
  assert.equal(starterProviders.has("deepinfra"), true);
  assert.equal(starterProviders.has("together"), false);
  assert.equal(
    starterMinimax.candidates.find((candidate) => candidate.provider === "deepinfra")
      .providerModelId,
    "MiniMaxAI/MiniMax-M3",
  );

  for (const route of d.routes) {
    assert.ok(route.canonicalModelId);
    assert.ok(route.candidates.length > 0);

    let previousPaidBaseline = -Infinity;
    for (const candidate of route.candidates) {
      assert.equal(typeof candidate.pricing.uncachedInputPerMTokensUsd, "number");
      assert.equal(typeof candidate.pricing.outputPerMTokensUsd, "number");

      if (candidate.free) {
        assert.equal(candidate.pricing.uncachedInputPerMTokensUsd, 0);
        assert.equal(candidate.pricing.outputPerMTokensUsd, 0);
        continue;
      }

      const baseline =
        candidate.pricing.uncachedInputPerMTokensUsd * 0.8 +
        candidate.pricing.outputPerMTokensUsd * 0.2;
      assert.ok(
        baseline >= previousPaidBaseline,
        `paid candidate baseline must be nondecreasing for ${route.canonicalModelId}`,
      );
      previousPaidBaseline = baseline;
    }
  }
});
