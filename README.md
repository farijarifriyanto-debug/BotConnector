# BotConnector AI 0.4 — functional integration beta

This candidate replaces the earlier static catalog with a technical, LM-Studio-style workflow while keeping BotConnector's own UI and architecture.

## What is implemented

### Desktop
- Live Hugging Face GGUF discovery (trending + search).
- Capability filters: Chat, Tools, Vision, Coding, Reasoning, Embeddings, Audio.
- Dynamic hardware-fit ranking from detected RAM and NVIDIA VRAM.
- Model detail view with **real GGUF repository files**, quantization labels, shard grouping, exact repository file sizes, and optional multimodal projector selection.
- Direct Hugging Face downloads to a configurable model directory.
- Download progress, pause, resume, cancel, `.part` files, HTTP Range resume, and SHA-256 verification when Hugging Face exposes an LFS SHA-256 object id.
- Installed-model scanning, reveal-in-folder, delete, and one-click Run.
- Managed llama.cpp installer from the official `ggml-org/llama.cpp` GitHub release assets for Windows x64: CUDA 12/13, Vulkan, CPU and ROCm where the release provides an asset.
- Runtime release SHA-256 verification when GitHub exposes the release asset digest.
- `llama-server` loopback binding at `127.0.0.1:11435`.
- Streaming local chat through `/v1/chat/completions`.
- Image attachment path for multimodal models (requires a compatible model/projector and llama.cpp support).
- OpenAI-compatible local API reference.
- English + Bahasa Indonesia navigation/header language; model metadata is left in source language.
- Hugging Face token storage encrypted through Electron `safeStorage`.

### Website
The website has been changed from a marketing landing page to a technical product page:
- runtime/backends,
- live Hugging Face model browser,
- API contract,
- local/cloud execution split,
- architecture,
- current preview scope.

The web model browser uses a local server-side proxy to Hugging Face during development (`npm run web`).

## Run on Windows

```powershell
cd "$HOME\Downloads\botconnector-ai-cloud-poc-v0.4-complete-beta"
npm install
npm run doctor
npm run desktop
```

Technical website preview:

```powershell
npm run web
```

Open `http://127.0.0.1:4173`.

## First functional test

1. Open **Runtime**.
2. For a Ryzen/Radeon machine without NVIDIA, use **Auto** or **Vulkan**.
3. Click **Check latest** then **Install / update**.
4. Open **Discover**.
5. Pick a small model, open **Details**, choose a quantization that fits, and click **Download**.
6. Wait for the download to complete.
7. Open **Installed**, click **Run**.
8. Open **Chat** and test streaming output.
9. Test the API endpoint at `http://127.0.0.1:11435/v1/chat/completions`.

## Important boundaries

- Capability classification is metadata-derived. A `Vision` or `Tools` label is not a guarantee that every quantization/repository variant works with every llama.cpp build.
- Hardware fit is an estimate, not a memory allocation guarantee. Context length and KV cache can materially change RAM/VRAM use.
- The cloud flagship control plane is **not enabled** in 0.4. The Cloud page describes the intended route contract only.
- Installer packaging (`.exe`/MSIX) is not part of this source candidate yet. Run it through Electron with `npm run desktop`.
- This environment could perform static syntax checks but could not reach Hugging Face/GitHub from the container, so live network/download/runtime acceptance must be performed on the Windows machine.

## Security choices

- Browser renderer has no Node integration.
- Runtime binds to localhost.
- External links are allow-listed.
- Hugging Face token is encrypted with Electron safeStorage before persistence.
- Model deletion is constrained to the configured model directory.
- llama.cpp is started with `spawn(..., shell:false)`.
