# STATUS — BotConnector AI 0.4

## Static acceptance performed here

- `node --check desktop/main.cjs` — PASS
- `node --check desktop/preload.cjs` — PASS
- `node --check desktop/desktop.js` — PASS
- `node --check runtime/hf.cjs` — PASS
- `node --check runtime/downloads.cjs` — PASS
- `node --check runtime/runtime-manager.cjs` — PASS
- `node --check runtime/llama.cjs` — PASS
- `node --check web/app.js` — PASS
- `node --check scripts/dev-server.mjs` — PASS
- desktop DOM selector audit — only dynamic modal IDs were absent from static HTML (expected)

## Live acceptance performed here (2026-09-12/13, Ryzen AI 7 350 / Radeon 860M / 15.6GB RAM)

- `npm run check` (all main/preload/desktop/runtime/bin syntax) — PASS
- `npm test` — 21/21 PASS (resolver, HF adapters, download pause/resume/cancel via local Range server, security, store, i18n)
- `node scripts/live-acceptance.mjs --backend vulkan` — 11/11 PASS
- Runtime resolver: newest usable release b10930 (vulkan+cpu); `/latest` (v0.4.0) carries no binaries — PASS
- Vulkan install + `llama-server.exe --version` (0.4.0-dev build 10930) — PASS
- Spark-X2.5-4B Q4_K_M preserved (2.42 GB), start, /health READY ~4-10s — PASS
- Non-stream + streaming chat, abort/stop-generation, stop, restart — PASS
- `/v1/models` + `/v1/chat/completions` via llama.cpp — PASS
- HF live search/details/capability/quant discovery — PASS
- CLI (`bin/botconnector.mjs`): version/doctor/ls/runtime/cloud/launch + live `server start`, `ps`, `chat`, `server stop` — PASS
- Electron GUI smoke: window "BotConnector AI" alive, no renderer errors (only dev CSP warning) — PASS
- `node scripts/doctor.mjs` — 10 PASS + 1 expected WARN (no NVIDIA GPU)
- No cloud endpoint is called by any local path (only huggingface.co, api.github.com, 127.0.0.1) — PASS

## Honestly not done / not tested

- MCP management UI, full SDK, and full Claude Code compatibility — NOT_IMPLEMENTED/NOT_TESTED
- Desktop/CLI process handoff is endpoint-based; HEADLESS_CORE=PARTIAL (documented)
- Dev-only Electron CSP warning remains (packaging concern, not a beta blocker)

## Continuation closeout (2026-09-13)

- Native b10930 matrix — PASS: `/v1/models`, OpenAI chat, Anthropic `/v1/messages` + streaming + `count_tokens`, Responses API + streaming + explicit 400 error, and embeddings route were live-tested.
- Embeddings — PASS 8/8 with `leliuga/all-MiniLM-L6-v2-GGUF@Q8_0`, numeric vectors, stable dimension 384, array input, and clean unload.
- Tool use — PASS 7/7 with Spark-X2.5-4B: structured `calculator` call for `27 + 15`, allowlisted Core execution to 42, result loop, Anthropic/Responses probes, and malformed-argument safety.
- Vision — PASS 7/7 with SmolVLM-500M Q8_0 plus matching mmproj; real red/blue image described correctly and text control passed.
- API auth — PASS 7/7: no token/wrong token rejected, Bearer and native `x-api-key` accepted, default remains OFF, `/health` is public by design.
- GUI tool loop — PASS live via Electron CDP: tool call, `calculator: 42`, final response, and runtime stop were observed in the UI.
- Shared process ownership — GUI/CLI claim the same ephemeral runtime state with atomic lock/release semantics; a second CLI start on the same port is rejected.
- Final retest: `npm run check` PASS, `npm test` 24/24 PASS, `npm run acceptance` 11/11 PASS, `npm run doctor` no FAIL (GPU WARN is expected on this AMD-only machine).

## Intentionally not implemented yet

- production cloud billing/auth/provider routing
- production account system
- Windows signed installer/update channel
- model-card README parsing/summarization
- additional tool integrations beyond the calculator allowlist / MCP management UI
- benchmark-based runtime tuning per model
- AMD iGPU VRAM/shared-memory telemetry beyond system RAM (current detector only has first-class NVIDIA VRAM via nvidia-smi)
