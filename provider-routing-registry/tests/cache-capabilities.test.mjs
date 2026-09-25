import test from "node:test";
import assert from "node:assert/strict";
import { cachePolicy, getCacheCapability } from "../src/cache-capabilities.ts";

test("semantic cache is disabled by default and tenant isolation is mandatory", () => {
  assert.equal(cachePolicy.semanticCacheEnabledByDefault, false);
  assert.equal(cachePolicy.tenantIsolationRequired, true);
  assert.equal(cachePolicy.manualModelSelection, "same-canonical-model-only");
});

test("Nara cached token reporting is recorded as observed, not guessed pricing", () => {
  const nara = getCacheCapability("nararouter");
  assert.equal(nara.promptCache.support, "observed");
  assert.equal(nara.promptCache.usageReportsCachedTokens, true);
  assert.equal(nara.promptCache.minCacheableTokens, null);
});

test("Alibaba qwen3.8-flash implicit cache capability is verified and thresholded", () => {
  const alibaba = getCacheCapability("alibaba_global");
  assert.equal(alibaba.promptCache.support, "verified");
  assert.equal(alibaba.promptCache.mode, "implicit");
  assert.equal(alibaba.promptCache.usageReportsCachedTokens, true);
  assert.equal(alibaba.promptCache.minCacheableTokens, 1024);
});
