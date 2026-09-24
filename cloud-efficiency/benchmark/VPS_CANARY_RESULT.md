# VPS Cloud-Efficiency Canary

Date: **2026-09-25 WIB**  
Mode: **isolated loopback canary on the production VPS**  
Production routing changed: **no**

The canary used Bifrost, Redis Stack, local TEI `intfloat/multilingual-e5-small`, and a fixed 300 ms mock provider. LLMLingua was intentionally excluded from the interactive path.

## Primary results

| Path | p50 | p95 | p99 |
|---|---:|---:|---:|
| Direct 300 ms mock | 303.090 ms | 303.327 ms | 303.696 ms |
| Bifrost, cache bypass | 305.904 ms | 306.516 ms | 306.622 ms |
| Exact-cache hit | 3.129 ms | 3.619 ms | 3.922 ms |
| Semantic-cache hit, 50-run sample | 23.283 ms | 53.070 ms | 63.404 ms |
| Semantic miss | 323.433 ms | 340.875 ms | 343.047 ms |

Bifrost added **3.189 ms p95** over the same mock provider, below the 5 ms canary budget.

Exact cache avoided the provider: after the prime request, **50 measured hits still left the upstream call count at 1**.

Semantic cache also avoided the provider. The fixture similarity was **0.99444** at the unchanged threshold **0.92**. The 50-request sample had a 53.070 ms p95, while a separate 100-request profiling run measured **23.614 ms p50 / 37.364 ms p95 / 51.223 ms p99**.

Semantic misses added about **37.548 ms p95** over the direct 300 ms provider fixture.

## Isolation

The same prompt and cache partition remained at one provider call. Changing only the tenant partition increased the provider-call count to two; changing only the policy partition increased it to three.

**Tenant/policy partition isolation: PASS.**

## Embedding path

A configuration bug in the original build bundle was reproduced and fixed. The custom OpenAI-compatible Bifrost provider must use the TEI root URL:

`http://embeddings:80`

not `http://embeddings:80/v1`, because Bifrost adds the OpenAI-compatible endpoint path.

After the fix, Bifrost `/v1/embeddings` returned HTTP 200 with the expected **384-dimensional** vector.

100-request profiling:

- TEI direct: **15.518 / 25.989 ms p50/p95**
- Bifrost embedding proxy: **19.928 / 40.183 ms p50/p95**
- semantic hit end-to-end: **23.614 / 37.364 ms p50/p95**

The already-running Qwen3-Embedding 0.6B service was also tested, but measured **56.811 / 82.176 ms p50/p95**, so it is not selected for the interactive semantic-cache fast path.

## Calibrated VPS canary limits

- Bifrost overhead p95: **<= 5 ms**
- Exact lookup p95: **<= 10 ms**
- Semantic hit p95: **<= 60 ms**
- Semantic hit p99: **<= 75 ms**
- Semantic miss added p95: **<= 50 ms**
- Semantic similarity threshold remains **0.92**
- Provider-call avoidance must pass
- Tenant/model/provider/policy isolation must pass

The semantic p95 limit was raised from the GitHub-runner value because the actual production VPS CPU showed a wider latency distribution. The similarity threshold and isolation requirements were not weakened.

## Live-provider boundary

No production user traffic was routed through this canary. A live cloud request was deliberately not fabricated: protected web-cloud routes require the existing BFF secret **and** a canonical session-resolved user UUID plus a fresh request UUID. The canary does not invent identity or bypass that authentication boundary.

Next live evidence must therefore be collected through an authenticated BFF/session canary path.
