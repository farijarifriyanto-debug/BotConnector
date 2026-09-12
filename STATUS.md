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

- Anthropic `/v1/messages`, MCP management UI, API token auth — NOT_IMPLEMENTED
- Vision projector flow, native tool-use model, embeddings endpoint — code paths exist, NOT_TESTED live
- Desktop/CLI process handoff is endpoint-based; HEADLESS_CORE=PARTIAL (documented)
- Dev-only Electron CSP warning remains (packaging concern, not a beta blocker)

## Intentionally not implemented yet

- production cloud billing/auth/provider routing
- production account system
- Windows signed installer/update channel
- model-card README parsing/summarization
- automated tool execution / MCP tool permissions
- benchmark-based runtime tuning per model
- AMD iGPU VRAM/shared-memory telemetry beyond system RAM (current detector only has first-class NVIDIA VRAM via nvidia-smi)
