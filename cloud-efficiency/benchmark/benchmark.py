from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.request
from dataclasses import dataclass

import tiktoken

OPTIMIZER = os.getenv("OPTIMIZER_URL", "http://127.0.0.1:18091")
EMBEDDINGS = os.getenv("EMBEDDINGS_URL", "http://127.0.0.1:18092")
SEMANTIC_THRESHOLD = float(os.getenv("SEMANTIC_THRESHOLD", "0.92"))
RATE = float(os.getenv("COMPRESSION_RATE", "0.65"))

SYSTEM_POLICY = (
    "You are BotConnector. Respect the selected cloud model exactly. "
    "Never change provider/model silently. Use tools only when needed and "
    "preserve user privacy and authorization boundaries."
)

HISTORY = """
Pengguna sedang mengelola layanan AI pada VPS Ubuntu untuk BotConnector. Dalam percakapan sebelumnya
mereka membahas pemilihan model cloud, model lokal, integrasi MCP, batas kuota, cache-aware billing,
dan kebutuhan agar model yang dipilih pengguna tidak pernah diganti diam-diam. Mereka juga membahas
LibreChat sebagai antarmuka chat, gateway BotConnector sebagai boundary autentikasi dan accounting,
serta Redis sebagai penyimpanan cache. Pengguna ingin sistem tetap sederhana, memanfaatkan komponen
siap pakai yang matang, dan menghindari pembuatan framework baru jika sudah ada proyek open-source
yang sesuai. Pada tahap terakhir mereka meminta penghematan biaya cloud tanpa menghilangkan kebebasan
memilih model.

Riwayat operasional mencatat bahwa deployment gateway harus fail closed untuk billing dan auth,
namun optimization layer seperti prompt compression harus fail open: jika optimizer tidak tersedia,
prompt asli tetap diteruskan. System prompt, instruksi keamanan, pesan pengguna terbaru, argumen tool,
ID, tanggal, jumlah uang, dan nilai terstruktur tidak boleh dikompres secara agresif. Bagian yang
boleh dioptimalkan adalah riwayat lama, potongan RAG yang panjang, dan output tool read-only yang
verbose. Semantic response cache harus dipisahkan menurut tenant, model, provider, dan policy
fingerprint agar jawaban antar pengguna atau antar model tidak pernah tercampur.

Catatan tambahan menjelaskan bahwa model cloud dipilih langsung oleh pengguna. Sebagian model
berasal dari OpenRouter, Novita, dan provider lain. Jika model A dipilih, seluruh request harus tetap
menuju model A. Penghematan dilakukan dengan menghindari provider call yang identik atau semantically
equivalent dalam scope aman, mengompres context lama, menggunakan provider-native prompt caching,
dan mengurangi tool schemas yang dikirim pada agent turn. Semua hit dan miss perlu diobservasi untuk
menghitung penghematan nyata, bukan hanya angka teoritis.
""".strip()

RAG = """
Dokumen arsitektur BotConnector menetapkan beberapa prinsip. Pertama, exact response cache hanya
boleh digunakan ketika request fingerprint identik pada tenant, model, provider, policy, tools, dan
parameter penting. Kedua, semantic cache hanya boleh digunakan untuk operasi read-only dan tidak
boleh melayani request yang dapat menimbulkan side effect. Ketiga, response dari cache tidak boleh
dihitung sebagai provider call dan accounting harus dapat membedakan uncached input, cached input,
cache write, dan output token.

Untuk prompt compression, dokumen merekomendasikan pemrosesan selektif. Riwayat chat lama dan
dokumen RAG dapat dipadatkan, tetapi instruksi keamanan, pesan terbaru, data numerik kritis, tool
arguments, dan nilai yang menjadi dasar transaksi wajib dipertahankan secara utuh. Optimizer tidak
boleh mengubah model yang dipilih pengguna. Jika optimizer timeout, error, atau tidak siap, gateway
meneruskan prompt asli.

Untuk MCP, dokumen mencatat bahwa katalog tool dapat membesar seiring integrasi GitHub, filesystem,
browser, office, dan layanan lain. Mengirim seluruh JSON schema tool pada setiap turn menambah input
token meski sebagian besar tool tidak digunakan. Discovery layer dapat mengekspos beberapa meta-tool
untuk mencari, menginspeksi, lalu memanggil tool yang tepat. Mode seperti ini hanya diaktifkan ketika
jumlah tool cukup besar; untuk katalog kecil, direct mode dapat tetap lebih sederhana.

Observability minimum mencakup cache hit type, selected model, selected provider, original input
tokens, optimized input tokens, output tokens, compressor ratio, tool catalog size, number of tools
actually exposed, provider latency, time-to-first-token, dan total provider cost. Metrik harus
diagregasi tanpa menyimpan prompt sensitif. Benchmark harus memisahkan penghematan request,
penghematan input token, dan penghematan biaya karena ketiganya tidak identik.
""".strip()

TOOL_OUTPUT = """
Hasil audit read-only menunjukkan service gateway aktif, Redis sehat, registry model dapat dibaca,
dan beberapa provider tersedia. Log berisi banyak baris status berulang yang tidak mengubah keputusan:
health check sukses, koneksi jaringan stabil, model catalog berhasil dibaca, dan worker tetap aktif.
Informasi penting yang perlu dipertahankan adalah bahwa semantic cache harus tenant-scoped,
model-scoped, provider-scoped, policy-scoped, dan hanya untuk operasi aman. Tidak ada credential
yang boleh dicatat ke benchmark atau artifact. Jika terjadi cache miss, request diteruskan ke model
yang dipilih pengguna tanpa mengganti model.
""".strip()


@dataclass(frozen=True)
class Request:
    tenant: str
    model: str
    policy: str
    text: str
    safe_cache: bool
    agent: bool = False


SAFE_GROUPS = [
    (
        "Bagaimana cara cek penggunaan RAM di VPS Ubuntu?",
        "Bagaimana cara cek penggunaan RAM di VPS Ubuntu?",
        "Bagaimana cara mengecek penggunaan RAM pada VPS Ubuntu?",
    ),
    (
        "Jelaskan perbedaan exact cache dan semantic cache untuk AI gateway.",
        "Jelaskan perbedaan exact cache dan semantic cache untuk AI gateway.",
        "Apa beda exact response cache dengan semantic cache pada AI gateway?",
    ),
    (
        "Bagaimana mengurangi token MCP ketika jumlah tool sangat banyak?",
        "Bagaimana mengurangi token MCP ketika jumlah tool sangat banyak?",
        "Apa cara menghemat token MCP kalau katalog tool sudah besar?",
    ),
    (
        "Mengapa prompt caching dapat menurunkan biaya input token?",
        "Mengapa prompt caching dapat menurunkan biaya input token?",
        "Kenapa provider prompt cache bisa membuat biaya input lebih murah?",
    ),
    (
        "Bagaimana menjaga cache AI agar tidak bocor antar user?",
        "Bagaimana menjaga cache AI agar tidak bocor antar user?",
        "Cara mencegah semantic cache mencampur jawaban antar tenant bagaimana?",
    ),
    (
        "Bagian prompt apa yang aman dikompres untuk chat panjang?",
        "Bagian prompt apa yang aman dikompres untuk chat panjang?",
        "Untuk percakapan panjang, context mana yang sebaiknya dikompresi?",
    ),
]

TRAFFIC: list[Request] = []
for group in SAFE_GROUPS:
    for text in group:
        TRAFFIC.append(Request("tenant-a", "space-bunny-alpha", "policy-v1", text, True))

# Same/similar content under a different model or tenant must NOT reuse cache.
TRAFFIC.extend(
    [
        Request("tenant-a", "ling-3.0-flash", "policy-v1", SAFE_GROUPS[0][0], True),
        Request("tenant-b", "space-bunny-alpha", "policy-v1", SAFE_GROUPS[1][0], True),
        Request("tenant-a", "space-bunny-alpha", "policy-v2", SAFE_GROUPS[2][0], True),
        Request("tenant-b", "ling-3.0-flash", "policy-v1", SAFE_GROUPS[3][0], True),
    ]
)

# Side-effecting / stateful turns bypass response cache.
for text in [
    "Kirim email ini sekarang ke pelanggan.",
    "Hapus file backup lama dari VPS.",
    "Restart service production sekarang.",
    "Buat issue GitHub dan assign ke maintainer.",
    "Ubah konfigurasi billing user ini.",
    "Deploy branch terbaru ke production.",
    "Jalankan perintah shell yang mengubah firewall.",
    "Simpan dokumen ini ke Google Drive.",
]:
    TRAFFIC.append(Request("tenant-a", "space-bunny-alpha", "policy-v1", text, False, True))


def post_json(url: str, payload: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def embedding(text: str) -> list[float]:
    data = post_json(
        EMBEDDINGS + "/v1/embeddings",
        {"model": "text-embeddings-inference", "input": [text]},
        timeout=120,
    )
    return data["data"][0]["embedding"]


def scope(req: Request) -> str:
    return f"{req.tenant}|{req.model}|{req.policy}"


def exact_key(req: Request) -> str:
    body = json.dumps(
        {"scope": scope(req), "text": req.text, "system": SYSTEM_POLICY},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()


def run_cache_benchmark() -> dict:
    exact_seen: set[str] = set()
    semantic_by_scope: dict[str, list[tuple[list[float], str]]] = {}
    exact_hits = semantic_hits = provider_calls = bypass = 0
    max_cross_scope_similarity = 0.0

    # Track a vector from a known phrase to prove scope isolation is doing work.
    same_phrase_vectors: list[tuple[str, list[float]]] = []

    for req in TRAFFIC:
        if not req.safe_cache:
            bypass += 1
            provider_calls += 1
            continue

        key = exact_key(req)
        if key in exact_seen:
            exact_hits += 1
            continue

        vec = embedding("query: " + req.text)
        if req.text == SAFE_GROUPS[0][0]:
            same_phrase_vectors.append((scope(req), vec))

        hit = False
        for prior_vec, _ in semantic_by_scope.get(scope(req), []):
            if cosine(vec, prior_vec) >= SEMANTIC_THRESHOLD:
                semantic_hits += 1
                hit = True
                break
        if hit:
            exact_seen.add(key)
            continue

        provider_calls += 1
        exact_seen.add(key)
        semantic_by_scope.setdefault(scope(req), []).append((vec, req.text))

    for i, (scope_a, a) in enumerate(same_phrase_vectors):
        for scope_b, b in same_phrase_vectors[i + 1 :]:
            if scope_a != scope_b:
                max_cross_scope_similarity = max(max_cross_scope_similarity, cosine(a, b))

    total = len(TRAFFIC)
    assert provider_calls + exact_hits + semantic_hits == total
    assert max_cross_scope_similarity > 0.99, (
        "fixture failed to prove cross-scope isolation using near-identical semantics"
    )
    return {
        "requests": total,
        "provider_calls": provider_calls,
        "exact_hits": exact_hits,
        "semantic_hits": semantic_hits,
        "cache_bypass": bypass,
        "provider_call_reduction_pct": round(100 * (1 - provider_calls / total), 2),
        "semantic_threshold": SEMANTIC_THRESHOLD,
        "cross_scope_similarity_proof": round(max_cross_scope_similarity, 6),
    }


def compress_segment(kind: str, text: str) -> dict:
    data = post_json(
        OPTIMIZER + "/v1/compress",
        {"rate": RATE, "segments": [{"kind": kind, "compress": True, "text": text}]},
        timeout=300,
    )
    item = data["segments"][0]
    origin = item.get("origin_tokens")
    compressed = item.get("compressed_tokens")
    if not isinstance(origin, int) or not isinstance(compressed, int):
        raise RuntimeError(f"LLMLingua token metrics missing for {kind}: {item}")
    return {
        "kind": kind,
        "origin_tokens": origin,
        "compressed_tokens": compressed,
        "saving_pct": round(100 * (1 - compressed / origin), 2),
    }


def tool_schema_tokens() -> dict:
    enc = tiktoken.get_encoding("cl100k_base")
    tools = []
    for i in range(47):
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": f"workspace_tool_{i+1}",
                    "description": (
                        "Read, inspect, search, or operate on an authorized workspace resource. "
                        "Use only when the requested capability is relevant and respect approval boundaries."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Workspace-relative path or resource id"},
                            "query": {"type": "string", "description": "Search query or operation input"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                        },
                        "required": ["query"],
                    },
                },
            }
        )
    meta = []
    for name, desc in [
        ("search_tools", "Find relevant capabilities by keyword or description."),
        ("inspect_capability", "Inspect the full schema for one discovered capability."),
        ("invoke_proxy_tool", "Invoke one previously discovered upstream tool."),
        ("get_proxy_prompt", "Fetch one indexed upstream prompt."),
        ("read_proxy_resource", "Read one indexed upstream resource."),
    ]:
        meta.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        )
    direct = len(enc.encode(json.dumps(tools, separators=(",", ":"))))
    lazy = len(enc.encode(json.dumps(meta, separators=(",", ":"))))
    return {
        "direct_tools": 47,
        "lazy_meta_tools": 5,
        "direct_schema_tokens": direct,
        "lazy_schema_tokens": lazy,
        "schema_token_reduction_pct": round(100 * (1 - lazy / direct), 2),
    }


def combined_model(cache: dict, compression: list[dict], tools: dict) -> dict:
    # Representative per-provider-call input. Protected/latest-user text is not compressed.
    noncompressible = 220
    origin_context = sum(x["origin_tokens"] for x in compression if x["kind"] in {"history", "rag"})
    optimized_context = sum(x["compressed_tokens"] for x in compression if x["kind"] in {"history", "rag"})
    orig_tool = tools["direct_schema_tokens"]
    opt_tool = tools["lazy_schema_tokens"]

    total = cache["requests"]
    misses = cache["provider_calls"]
    agent_requests = sum(1 for req in TRAFFIC if req.agent)

    # Baseline assumes every request reaches provider. Heavy-MCP schema is applied only to agent turns.
    baseline_input = total * (noncompressible + origin_context) + agent_requests * orig_tool

    # Optimized provider calls: all misses retain protected text and compressed context.
    # Cache-bypassed agent turns use lazy-tool meta schemas.
    optimized_agent_calls = sum(1 for req in TRAFFIC if req.agent)  # all are bypass in this fixture
    optimized_input = misses * (noncompressible + optimized_context) + optimized_agent_calls * opt_tool

    output_per_call = 400
    baseline_output = total * output_per_call
    optimized_output = misses * output_per_call

    cost_models = {}
    for name, (pin, pout) in {
        "input_output_1_to_1": (1.0, 1.0),
        "input_output_1_to_3": (1.0, 3.0),
        "input_output_1_to_5": (1.0, 5.0),
    }.items():
        before = baseline_input * pin + baseline_output * pout
        after = optimized_input * pin + optimized_output * pout
        cost_models[name] = round(100 * (1 - after / before), 2)

    return {
        "baseline_provider_input_tokens": baseline_input,
        "optimized_provider_input_tokens": optimized_input,
        "provider_input_token_reduction_pct": round(100 * (1 - optimized_input / baseline_input), 2),
        "baseline_provider_output_tokens_modelled": baseline_output,
        "optimized_provider_output_tokens_modelled": optimized_output,
        "output_assumption_tokens_per_call": output_per_call,
        "modelled_provider_cost_reduction_pct": cost_models,
        "note": "Combined token/cost model uses the measured compression and schema ratios on the synthetic traffic fixture. Output tokens are modelled at 400 per provider call.",
    }


def main():
    cache = run_cache_benchmark()
    compression = [
        compress_segment("history", HISTORY),
        compress_segment("rag", RAG),
        compress_segment("tool_output", TOOL_OUTPUT),
    ]
    tools = tool_schema_tokens()
    combined = combined_model(cache, compression, tools)

    result = {
        "benchmark": "BotConnector cloud-efficiency synthetic-v1",
        "timestamp": int(time.time()),
        "compression_rate": RATE,
        "cache": cache,
        "compression": compression,
        "tools": tools,
        "combined": combined,
        "limitations": [
            "Traffic is a reproducible synthetic BotConnector-style fixture, not production user traffic.",
            "Semantic cache simulation uses the same multilingual-e5-small embeddings and threshold as the proposed local cache layer, scoped by tenant+model+policy.",
            "LLMLingua token counts are measured by the compressor tokenizer; exact upstream provider tokenizers can differ.",
            "Cost percentages are modelled for input:output price ratios of 1:1, 1:3, and 1:5 and do not represent a specific provider price.",
            "No quality claim is made from compression alone; production rollout still needs answer-quality and cache-safety canaries.",
        ],
    }
    print(json.dumps(result, indent=2))
    with open("cloud-efficiency/benchmark/result.json", "w") as fh:
        json.dump(result, fh, indent=2)

    c = combined
    lines = [
        "# BotConnector Cloud Efficiency Benchmark",
        "",
        "Synthetic, reproducible benchmark; not production traffic.",
        "",
        f"- Requests: **{cache['requests']}**",
        f"- Provider calls after cache: **{cache['provider_calls']}**",
        f"- Provider-call reduction: **{cache['provider_call_reduction_pct']}%**",
        f"- Exact hits: **{cache['exact_hits']}**; semantic hits: **{cache['semantic_hits']}**",
        f"- Provider input-token reduction (combined): **{c['provider_input_token_reduction_pct']}%**",
        f"- Heavy MCP schema reduction (47 -> 5 tools): **{tools['schema_token_reduction_pct']}%**",
        "",
        "## LLMLingua measured compression",
        "",
    ]
    for row in compression:
        lines.append(
            f"- {row['kind']}: {row['origin_tokens']} -> {row['compressed_tokens']} tokens "
            f"(**{row['saving_pct']}%**) at rate {RATE}"
        )
    lines += [
        "",
        "## Modelled provider cost reduction",
        "",
        f"- Input:output price 1:1: **{c['modelled_provider_cost_reduction_pct']['input_output_1_to_1']}%**",
        f"- Input:output price 1:3: **{c['modelled_provider_cost_reduction_pct']['input_output_1_to_3']}%**",
        f"- Input:output price 1:5: **{c['modelled_provider_cost_reduction_pct']['input_output_1_to_5']}%**",
        "",
        "These percentages combine cache-hit call elimination, measured context compression, and tool-schema reduction. "
        "Output is modelled at 400 tokens for every provider call that is not served by cache.",
    ]
    with open("cloud-efficiency/benchmark/RESULT.md", "w") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
