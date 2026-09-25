# BotConnector Latency Benchmark

GitHub Actions run: **36069367868**  
Result: **PASS**  
Fixture: official Bifrost mock provider, fixed 300 ms latency, zero jitter. No paid provider calls.

## Measured latency

- Direct mock provider p50/p95: **301.604 / 301.883 ms**
- Bifrost -> same provider p50/p95: **302.641 / 302.955 ms**
- Bifrost gateway delta p50/p95: **+1.037 / +1.072 ms**
- Exact-cache CPU hash/dict lookup p50/p95: **0.001 / 0.001 ms**
- Semantic-cache local TEI lookup p50/p95: **8.604 / 11.516 ms**
- LLMLingua-2 long-context CPU preprocessing p50/p95: **1746.733 / 1752.259 ms**
- Semantic-cache p50 speedup versus the 300 ms mock provider: **35.05x**

## Interpretation

Bifrost overhead is small enough for the proposed cache layer in this fixture.

Exact cache remains the fastest path, but its number above is CPU-only and excludes Redis, HTTP, serialization, and production network overhead. Do not use it as an end-to-end production latency claim.

Semantic cache is a strong interactive fast path: a safe hit avoids the provider and the local embedding/search path measured about 8.6 ms p50.

LLMLingua-2 is **not** an interactive latency fast path on CPU in this benchmark. It adds about 1.75 seconds of preprocessing for the long-context fixture. Therefore the latency policy keeps compression off by default for interactive chat. It may be enabled for cost-oriented/long-context work only when observed provider prefill savings exceed the local compressor overhead.

## Initial latency policy

- exact cache: enabled for cache-safe requests
- semantic cache: enabled for cache-safe/read-only requests
- semantic threshold: 0.92
- semantic lookup latency budget: 25 ms p95 before fail-open
- side-effect/write/tool-action requests: response-cache bypass
- Bifrost gateway overhead acceptance: <= 5 ms p95 in canary
- LLMLingua interactive default: disabled
- LLMLingua long-context: conditional only; fail-open to original prompt
- OpenRouter interactive: provider.sort = latency
- OpenRouter long generation: provider.sort = throughput
- OpenRouter multi-turn: stable session_id for sticky prompt-cache routing
- selected model: immutable; optimization must never silently change the user's model

## Limitations

This is a reproducible synthetic benchmark, not production traffic. The mock provider isolates gateway/cache-layer latency but does not represent internet RTT, provider queues, or model inference. TEI and LLMLingua performance will differ on the production VPS hardware. Production rollout still needs shadow/canary p50, p95, TTFT, throughput, cache-hit rate, and answer-quality measurements.
