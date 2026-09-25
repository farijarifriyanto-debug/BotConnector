# BotConnector Cloud Efficiency Stack

This public build bundle reduces cloud-provider cost and latency without changing the AI model selected by the user.

## Invariant

If a user selects model A, the request stays on model A. Cache, compression, prompt-cache hints, and MCP tool discovery may reduce work, but never silently switch models.

## Layers

1. Existing exact response cache
2. Bifrost semantic cache, scoped by model and provider
3. LLMLingua-2 context compression
4. lazy-tool MCP discovery to avoid injecting every tool schema
5. Provider-native prompt caching/sticky sessions where supported

## Safety

Semantic cache must also be tenant/policy scoped at integration time. Do not serve semantic hits across tenants, models, providers, or different system policies.

Do not compress the active system/security policy, latest user instruction, tool arguments, IDs, amounts, dates, or exact structured values. Initial compression targets are old history, long RAG passages, and verbose read-only tool output.

This repository builds the reusable components in GitHub Actions. It contains no provider keys and does not deploy to production.


## VPS canary status

Isolated production-VPS canary evidence is recorded in `benchmark/VPS_CANARY_RESULT.md`.

Current measured limits:

- Bifrost overhead: <= 5 ms p95
- exact-cache hit: <= 10 ms p95
- semantic-cache hit: <= 60 ms p95 and <= 75 ms p99
- semantic miss added latency: <= 50 ms p95
- semantic similarity threshold remains 0.92
- tenant/model/provider/policy partition isolation and provider-call avoidance are mandatory

The Bifrost TEI custom provider uses the root URL `http://embeddings:80`.
The default compose keeps LLMLingua off the interactive path; start the
`long-context` profile only for conditional long-context optimization.

## Accounting gate

Semantic response caching must remain behind BotConnector authentication and
quota reservation. Full trusted Bifrost response-cache hits must be normalized
to cached input for settlement while output remains charged. Arbitrary external
providers are not trusted to claim this discount.

See `SEMANTIC_CACHE_ACCOUNTING.md` and
`semantic-cache-accounting.contract.json`.

Authenticated live-provider cutover remains gated on the canonical production
gateway source repository plus a session-resolved BFF canary. No fabricated
user UUID or authentication bypass is allowed.


## Latency Profiler

`latency_profiler.py` is the request-level timing contract for the BotConnector
cloud fast path. It records timing metadata only; prompt text, response content,
tool arguments, secrets, and API keys are never part of the trace.

Recommended integration points in the canonical gateway:

1. create a trace at authenticated request ingress;
2. wrap `auth_quota`, `route`, and any other local critical-path stage with
   `trace.stage(...)`;
3. call `trace.mark("provider_request")` immediately before the outbound
   provider request;
4. call `trace.mark("first_byte")` on the first upstream response byte;
5. call `trace.mark("first_token")` on the first model token/SSE content chunk;
6. call `trace.finish()` when the stream or non-stream response completes;
7. export `trace.to_json()` to structured telemetry and optionally expose
   `trace.server_timing_header()` for authenticated diagnostics;
8. feed completed traces into `RollingLatencyStore` for bounded in-memory
   p50/p95/p99 model+provider telemetry.

The profiler does not alter the selected model and is not billing authority.
Durable usage settlement remains in the existing accounting path.

The GitHub contract workflow runs deterministic tests plus a bookkeeping-only
microbenchmark and uploads `LATENCY_PROFILER_OVERHEAD.json` as evidence.
