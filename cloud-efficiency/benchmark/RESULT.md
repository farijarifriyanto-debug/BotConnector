# BotConnector Cloud Efficiency Benchmark

GitHub Actions run: 36053271767  
Benchmark job: PASS  
Fixture: synthetic BotConnector-style traffic (30 requests), not production traffic.

## Result

- Requests: **30**
- Provider calls after exact + semantic cache: **20**
- Provider-call reduction: **33.33%**
- Exact cache hits: **6**
- Semantic cache hits: **4**
- Cache-bypassed side-effecting requests: **8**
- Semantic threshold: **0.92**
- Cross-scope semantic similarity proof: **1.0** while tenant/model/policy scoping still prevented reuse

## LLMLingua-2 measured compression at rate 0.65

- History: **493 -> 331 tokens** (**32.86%** reduction)
- RAG: **466 -> 311 tokens** (**33.26%** reduction)
- Read-only tool output: **154 -> 106 tokens** (**31.17%** reduction)

## MCP schema benchmark

Heavy MCP fixture:
- Direct catalog: **47 tools / 4,702 schema tokens**
- lazy-tool search mode: **5 meta-tools / 211 schema tokens**
- Schema-only reduction: **95.51%**

This is schema-only. It must not be interpreted as a 95.51% reduction of the whole request. Upstream lazy-tool reports a smaller whole-input reduction in its own benchmark because system/user/context tokens remain.

## Combined provider-token model

- Baseline provider input tokens: **72,986**
- Optimized provider input tokens: **18,928**
- Combined provider input-token reduction: **74.07%**

Output was modelled at 400 tokens for each provider call that reaches the provider:
- Baseline modelled provider output: **12,000**
- Optimized modelled provider output: **8,000**

Modelled cost reduction for the same selected AI:
- input:output price ratio 1:1 -> **68.31%**
- input:output price ratio 1:3 -> **60.61%**
- input:output price ratio 1:5 -> **55.69%**

## Rollout interpretation

The safe expectation from this synthetic benchmark is **not** "production will always save 74%".
The measured components imply:

1. Cache saves the entire provider call only when there is a safe hit.
2. LLMLingua-2 reduced compressible context by roughly **31-33%** in this fixture.
3. lazy-tool produces very large schema savings only when the MCP catalog is large.
4. Actual cost savings depend on real cache hit rate, output length, provider tokenization, and each model's input/output price.

Initial canary policy:
- semantic threshold: **0.92**
- compression rate: **0.65**
- model selection: immutable
- scope: tenant + selected model + provider + policy fingerprint
- semantic cache: read-only/cache-safe requests only
- write/side-effect tools: cache bypass
- never compress active system/security policy, latest user instruction, tool arguments, IDs, amounts, dates, or exact structured values
- optimization failure: fail open to the original prompt
- auth/billing failure: fail closed

Artifact: `cloud-efficiency-benchmark-d3430235cef4cb950c7d129e1311d48598f57f36`
