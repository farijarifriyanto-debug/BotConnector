import assert from "node:assert/strict";
import test from "node:test";
import registry from "../config/free-provider-registry.json" with { type: "json" };
import {
  assertSameModelFallback,
  filterExactModelFreeCandidates,
  freeProviderCredentialState,
  freeProviderPolicy,
  getFreeProviderRuntimeConfig,
  listFreeProviders,
} from "../src/free-provider-routing.ts";
import { FREE_PROVIDER_IDS, isPaidProvider } from "../src/model-routing.ts";

test("requested free providers are installed and enabled", () => {
  const expected = ["xkiro", "siliconflow", "nararouter", "openrouter", "opencode_zen", "poolside", "agnes", "novita"];
  assert.deepEqual(listFreeProviders().map((p) => p.id), expected);
  assert.ok(listFreeProviders().every((p) => p.enabled === true));
  assert.deepEqual([...FREE_PROVIDER_IDS], expected);
  assert.ok(expected.every((id) => isPaidProvider(id) === false));
});

test("free provider registry contains no credential values", () => {
  const serialized = JSON.stringify(registry);
  assert.doesNotMatch(serialized, /sk-[A-Za-z0-9]|bearer\s+[A-Za-z0-9]/i);
  for (const provider of registry.providers) assert.match(provider.credentialEnv, /^[A-Z0-9_]+_API_KEY$/);
});

test("runtime config fails closed when provider key is absent", () => {
  assert.deepEqual(freeProviderCredentialState("nararouter", {}), {
    configured: false,
    envName: "NARAROUTER_API_KEY",
  });
  assert.throws(
    () => getFreeProviderRuntimeConfig("nararouter", {}),
    /FREE_PROVIDER_CREDENTIAL_MISSING:nararouter:NARAROUTER_API_KEY/,
  );
});

test("runtime config resolves endpoints only after credential is present", () => {
  const resolved = getFreeProviderRuntimeConfig("poolside", { POOLSIDE_API_KEY: "dummy-test-key" });
  assert.equal(resolved.baseUrl, "https://inference.poolside.ai/v1");
  assert.equal(resolved.modelsUrl, "https://inference.poolside.ai/v1/models");
  assert.equal(resolved.chatCompletionsUrl, "https://inference.poolside.ai/v1/chat/completions");
  assert.equal(resolved.apiKey, "dummy-test-key");
});

test("provider failover is same-canonical-model only", () => {
  const source = { canonicalModelId: "deepseek-v4-flash", provider: "xkiro", providerModelId: "a" };
  const same = { canonicalModelId: "deepseek-v4-flash", provider: "opencode_zen", providerModelId: "b" };
  const other = { canonicalModelId: "laguna-s-2.1", provider: "poolside", providerModelId: "c" };
  assert.doesNotThrow(() => assertSameModelFallback(source, same));
  assert.throws(() => assertSameModelFallback(source, other), /CROSS_MODEL_FALLBACK_BLOCKED/);
});

test("candidate filter never substitutes another AI", () => {
  const result = filterExactModelFreeCandidates("deepseek-v4-flash", [
    { canonicalModelId: "deepseek-v4-flash", provider: "xkiro", providerModelId: "x" },
    { canonicalModelId: "deepseek-v4-flash", provider: "opencode_zen", providerModelId: "z" },
    { canonicalModelId: "laguna-s-2.1", provider: "poolside", providerModelId: "p" },
    { canonicalModelId: "deepseek-v4-flash", provider: "deepinfra", providerModelId: "paid" },
  ]);
  assert.deepEqual(result.map((entry) => entry.provider), ["xkiro", "opencode_zen"]);
  assert.equal(freeProviderPolicy.autoModelSwitch, false);
  assert.equal(freeProviderPolicy.providerFallback, "same-canonical-model-only");
});
