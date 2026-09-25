import test from "node:test";
import assert from "node:assert/strict";
import { normalizeProviderUsage } from "../src/usage-meter.ts";

test("normalizes OpenAI-style cached token usage", () => {
  const usage = normalizeProviderUsage({
    prompt_tokens: 54,
    completion_tokens: 7,
    prompt_tokens_details: { cached_tokens: 32 },
    total_tokens: 61,
  });
  assert.equal(usage.logicalInputTokens, 54);
  assert.equal(usage.freshInputTokens, 22);
  assert.equal(usage.cachedInputTokens, 32);
  assert.equal(usage.outputTokens, 7);
  assert.equal(usage.totalLogicalTokens, 61);
  assert.equal(usage.cacheHitRate, 32 / 54);
});

test("normalizes cache-write usage and validates impossible cached counts", () => {
  const usage = normalizeProviderUsage({
    input_tokens: 1000,
    output_tokens: 100,
    cache_creation_input_tokens: 800,
  });
  assert.equal(usage.cacheWriteTokens, 800);
  assert.throws(
    () => normalizeProviderUsage({ prompt_tokens: 5, prompt_tokens_details: { cached_tokens: 6 } }),
    /CACHED_TOKENS_EXCEED_LOGICAL_INPUT/,
  );
});
