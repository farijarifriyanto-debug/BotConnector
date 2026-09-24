from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
import urllib.request
from pathlib import Path

MOCKER = os.getenv("MOCKER_URL", "http://127.0.0.1:18080")
BIFROST = os.getenv("BIFROST_URL", "http://127.0.0.1:18081")
OPTIMIZER = os.getenv("OPTIMIZER_URL", "http://127.0.0.1:18091")
EMBEDDINGS = os.getenv("EMBEDDINGS_URL", "http://127.0.0.1:18092")

OUT = Path("cloud-efficiency/benchmark/LATENCY_RESULT.json")
OUT_MD = Path("cloud-efficiency/benchmark/LATENCY_RESULT.md")

LONG_CONTEXT = """
BotConnector melayani banyak model cloud tetapi model yang dipilih user tidak boleh berubah.
Optimization layer hanya boleh mengurangi pekerjaan yang dikirim ke provider. Exact cache harus
dipisah menurut tenant, model, provider, policy fingerprint, tool set, dan parameter generation.
Semantic cache hanya boleh digunakan untuk request read-only yang aman. Request yang menjalankan
aksi seperti mengirim email, menghapus file, mengubah billing, menjalankan shell write, atau deploy
harus bypass response cache.

Riwayat chat lama, konteks RAG panjang, dan output tool read-only adalah kandidat untuk prompt
compression. System policy, instruksi keamanan, latest user request, tool arguments, identifier,
tanggal, jumlah uang, dan structured values yang harus presisi tidak boleh dikompres agresif.
Jika optimizer gagal, request asli harus tetap dapat diteruskan. Jika auth atau billing boundary
gagal, request harus berhenti.

Untuk latency, BotConnector membedakan time-to-first-token dan throughput. Chat interaktif lebih
sensitif terhadap TTFT, sedangkan coding atau output panjang lebih sensitif terhadap tokens per
second. Cache hit menghilangkan provider call. Semantic cache tetap membutuhkan embedding lookup,
sehingga latency-nya harus dibandingkan dengan provider call yang dihindari. LLMLingua menambah
preprocessing CPU, jadi hanya masuk akal pada context cukup panjang dan ketika penghematan prefill
provider melebihi biaya preprocessing lokal.
""".strip() * 4


def percentile(values: list[float], q: float) -> float:
    xs = sorted(values)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * q
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - k) + xs[hi] * (k - lo)


def summary_ms(values: list[float]) -> dict:
    return {
        "n": len(values),
        "mean_ms": round(statistics.mean(values), 3),
        "p50_ms": round(percentile(values, 0.50), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "p99_ms": round(percentile(values, 0.99), 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
    }


def http_json(url: str, payload: dict | None = None, timeout: float = 30) -> dict:
    data = None
    headers = {}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["content-type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def timed(fn, warmup: int, runs: int) -> list[float]:
    for _ in range(warmup):
        fn()
    values = []
    for _ in range(runs):
        t0 = time.perf_counter_ns()
        fn()
        values.append((time.perf_counter_ns() - t0) / 1_000_000)
    return values


def direct_provider_call() -> None:
    http_json(
        MOCKER + "/v1/chat/completions",
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Return a short latency benchmark response."}],
            "max_tokens": 32,
        },
    )


def bifrost_provider_call() -> None:
    http_json(
        BIFROST + "/v1/chat/completions",
        {
            "model": "botconnector-mock/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Return a short latency benchmark response."}],
            "max_tokens": 32,
        },
    )


def exact_cache_cpu_lookup() -> None:
    key = hashlib.sha256(
        b"tenant-a|space-bunny-alpha|openrouter|policy-v1|normalized-request"
    ).digest()
    _ = EXACT_CACHE[key]


def embedding(text: str) -> list[float]:
    data = http_json(
        EMBEDDINGS + "/v1/embeddings",
        {"model": "text-embeddings-inference", "input": ["query: " + text]},
        timeout=60,
    )
    return data["data"][0]["embedding"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


SEMANTIC_CORPUS_TEXT = [
    "Bagaimana mengecek penggunaan RAM pada VPS Ubuntu?",
    "Apa beda exact cache dan semantic cache untuk AI gateway?",
    "Bagaimana menghemat token ketika MCP memiliki banyak tools?",
    "Mengapa prompt caching dapat menurunkan biaya input token?",
    "Bagaimana mencegah cache AI bocor antar tenant?",
    "Bagian context mana yang aman dikompres pada chat panjang?",
    "Bagaimana mengukur time to first token pada model cloud?",
    "Apa perbedaan latency dan throughput untuk LLM?",
]
SEMANTIC_CORPUS: list[list[float]] = []


def semantic_cache_lookup() -> None:
    vec = embedding("Cara cek pemakaian RAM di server Ubuntu?")
    best = max(cosine(vec, candidate) for candidate in SEMANTIC_CORPUS)
    if best < 0.70:
        raise RuntimeError(f"semantic fixture unexpectedly weak: {best}")


def llmlingua_long_context() -> None:
    data = http_json(
        OPTIMIZER + "/v1/compress",
        {
            "rate": 0.65,
            "segments": [{"kind": "history", "compress": True, "text": LONG_CONTEXT}],
        },
        timeout=180,
    )
    segment = data["segments"][0]
    if not segment.get("compressed"):
        raise RuntimeError("LLMLingua fixture was not compressed")


EXACT_KEY = hashlib.sha256(
    b"tenant-a|space-bunny-alpha|openrouter|policy-v1|normalized-request"
).digest()
EXACT_CACHE = {EXACT_KEY: {"cached": True}}


def main() -> None:
    global SEMANTIC_CORPUS
    SEMANTIC_CORPUS = [embedding(text) for text in SEMANTIC_CORPUS_TEXT]

    # The mock provider is configured by the workflow with 300ms latency and 40ms jitter.
    direct = timed(direct_provider_call, warmup=3, runs=40)
    bifrost = timed(bifrost_provider_call, warmup=3, runs=40)

    # CPU-only hash/dict lookup. This intentionally excludes HTTP/Redis network overhead.
    exact = timed(exact_cache_cpu_lookup, warmup=100, runs=10000)

    # Includes local HTTP request + TEI embedding + cosine search over 8 candidates.
    semantic = timed(semantic_cache_lookup, warmup=2, runs=20)

    # Real LLMLingua-2 CPU service on a GitHub hosted runner.
    compressor = timed(llmlingua_long_context, warmup=1, runs=6)

    direct_s = summary_ms(direct)
    bifrost_s = summary_ms(bifrost)
    exact_s = summary_ms(exact)
    semantic_s = summary_ms(semantic)
    compressor_s = summary_ms(compressor)

    gateway_overhead_p50 = bifrost_s["p50_ms"] - direct_s["p50_ms"]
    gateway_overhead_p95 = bifrost_s["p95_ms"] - direct_s["p95_ms"]

    # Conservative synthetic speedup against the same fixed mock provider.
    semantic_speedup = direct_s["p50_ms"] / max(semantic_s["p50_ms"], 0.000001)

    result = {
        "benchmark": "BotConnector cloud-efficiency latency synthetic-v1",
        "environment": "GitHub-hosted ubuntu-latest",
        "mock_provider": {
            "configured_base_latency_ms": 300,
            "configured_jitter_ms": 0,
        },
        "direct_mock_provider": direct_s,
        "bifrost_to_same_mock_provider": bifrost_s,
        "bifrost_gateway_overhead_ms": {
            "p50_delta_ms": round(gateway_overhead_p50, 3),
            "p95_delta_ms": round(gateway_overhead_p95, 3),
        },
        "exact_cache_cpu_lookup": exact_s,
        "semantic_cache_local_tei_lookup": semantic_s,
        "llmlingua2_long_context_preprocessing": compressor_s,
        "synthetic_cache_speedup_vs_mock_provider": {
            "semantic_p50_x": round(semantic_speedup, 2),
            "exact_note": "Exact cache CPU lookup is below millisecond timer resolution here; do not report a multiplicative speedup from this fixture."
        },
        "policy": {
            "small_prompt_compression": "skip",
            "long_context_compression": "enable only when expected provider prefill savings exceed measured local preprocessing",
            "interactive_openrouter": {"provider.sort": "latency"},
            "long_generation_openrouter": {"provider.sort": "throughput"},
            "stable_session_id_for_prompt_cache": True,
        },
        "limitations": [
            "The provider is the official Bifrost mocker with fixed synthetic latency/jitter, not a live cloud provider.",
            "Exact-cache timing is CPU hash/dict lookup only and excludes Redis/network serialization.",
            "Semantic-cache timing includes local TEI HTTP embedding and an 8-vector cosine scan; production vector-store size can change this.",
            "LLMLingua timing is GitHub-runner CPU performance and will differ on the production VPS.",
            "OpenRouter latency/throughput routing is documented policy only; this benchmark does not call OpenRouter or spend provider credits.",
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")

    lines = [
        "# BotConnector Latency Benchmark",
        "",
        "Synthetic reproducible GitHub Runner benchmark; no paid provider calls.",
        "",
        f"- Direct mock provider p50/p95: **{direct_s['p50_ms']} / {direct_s['p95_ms']} ms**",
        f"- Bifrost -> same provider p50/p95: **{bifrost_s['p50_ms']} / {bifrost_s['p95_ms']} ms**",
        f"- Bifrost p50/p95 delta: **{gateway_overhead_p50:.3f} / {gateway_overhead_p95:.3f} ms**",
        f"- Exact-cache CPU lookup p50/p95: **{exact_s['p50_ms']} / {exact_s['p95_ms']} ms**",
        f"- Semantic-cache local TEI lookup p50/p95: **{semantic_s['p50_ms']} / {semantic_s['p95_ms']} ms**",
        f"- LLMLingua-2 long-context preprocess p50/p95: **{compressor_s['p50_ms']} / {compressor_s['p95_ms']} ms**",
        "- Exact cache CPU lookup is sub-millisecond in this fixture; no multiplicative speedup is reported because Redis/network overhead is excluded.",
        f"- Semantic cache synthetic p50 speedup vs 300ms mock provider: **{semantic_speedup:.2f}x**",
        "",
        "## Interpretation",
        "",
        "- Exact/semantic cache hits are the latency-fast path because they avoid the provider call.",
        "- LLMLingua is not a universal latency fast path: it adds local CPU preprocessing, so it should be gated to long context.",
        "- Bifrost is acceptable only if measured gateway delta stays small relative to provider latency.",
        "- Interactive OpenRouter requests should prefer provider.sort=latency; long generation should prefer provider.sort=throughput.",
        "- Stable session_id should be used for multi-turn prompt-cache stickiness.",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(json.dumps(result, indent=2))
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
