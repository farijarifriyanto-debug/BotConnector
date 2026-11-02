# BICO Multimedia Director — image LoRA smoke runbook (Qwen3-VL-4B primary)

**Prepared on:** 31 October 2026  
**Status:** Public offline training script and synthetic tests ONLY. Nothing in this directory rents a GPU, downloads a checkpoint or trains weights: every paid run below needs explicit local flags on an operator's own authorized machine. Licensed ABO review data, model checkpoints and the short-lived rented GPUs used for the 1-2 Nov 2026 measurements stay outside this public mirror, and no adapter from those runs is approved for production.

## Decisions

- Multimodal Director reads the product or shot reference **pixels** and generates fact-grounded JSON for the existing Studio Creative Director and Film Project. It does not replace the production image/video generator.
- **Primary:** Qwen/Qwen3-VL-4B-Instruct (`model_type qwen3_vl`). HuggingFaceTB/SmolVLM2-2.2B-Instruct is a measured-insufficient legacy baseline reachable only through `--allow-2b-legacy`; 7B/8B/9B remain excluded from this pilot.
  - **Update 2 Nov 2026 — the 2B failure is now measured, so Qwen3-VL-4B-Instruct is the Director primary.** 20 held-out ABO photos, exact-contract prompt, no LoRA: 4B contract pass 18/20 (90%), factsRecall 0.422; 2B 10/20 (50%), factsRecall 0.000, empty `preservation_rules` on 10/20. `probe-multimedia-director-vlm.py`, `prepare-smolvlm2-sft.py` and `train-smolvlm2-lora.py` all default to the 4B and gate the 2B behind `--allow-2b-legacy`, so the training scripts are no longer SmolVLM2-only. The model registry, the contract prompt and the architecture gate now come from one module, `scripts/multimedia-director-contract.py`, which means the prompt a packet is trained on and the prompt the probe serves are the same object.
- Public repo holds only test scripts, synthetic cases and tooling. Real reviewed commercial-training datasets, customer media, credentials, model checkpoints and private Studio implementation must **never** be pushed here.
- The planned rented hardware is a single **RunPod Community Cloud GPU 48GB** for temporary training, not serving. A cheaper 16/24GB Community GPU may be considered only after demonstrated fit/price comparison. Nothing in this repo starts a pod.

## Prerequisites

1. Obtain media **from a licensed public source** on an authorized non-production machine. For ABO, start with the official listing metadata and human review workflow in ABO-SFT-HANDOFF.md. Raw dataset downloads are outside GitHub Actions. Keep source URL, attribution, explicit rights for commercial training and third-party GPU processing, checksum, non-PII review and approval per item.
2. Run prepare-multimedia-director-data.mjs with at least **50 train**, **10 validation**, **200 holdout test** across disjoint products/brands/characters, then prepare-smolvlm2-sft.py with explicit --write. The latter only exports train and val, never test, and seals the manifest for one base model (`--model`, default the 4B primary).
3. **Human QA** must inspect visual facts, product labels, logo preservation and image copyrights; automated flags are not independent legal or semantic proof.
4. Confirm the selected base model's official commercial license and exact checkpoint revision (Qwen3-VL-4B-Instruct is published under Apache-2.0; confirm the revision you actually download), and separately provision authorized storage. Copy model weights into a trusted local --model-dir on a GPU host after checking SHA256 and licensing. Use audited **safetensors only**, never unknown .bin/.pt files, and avoid arbitrary remote code.
5. The LoRA runner requires torch, transformers, accelerate, peft, Pillow, safetensors **already installed in a pinned compatible local environment**. These exact version combinations have **not** been tested on a real GPU through this runner. The equivalent 4B recipe did complete once on a rented GPU on 2 Nov 2026 through a separate experiment wrapper outside this repo: LoRA r=8 / alpha=16 / dropout 0.05 on text-decoder q_proj and v_proj only, `pixel_values` plus `image_grid_thw` per microbatch, gradient checkpointing with `enable_input_require_grads()`, `remove_unused_columns=False`, `dataloader_num_workers=0`, >=15 GiB VRAM, seed 1337. The script never installs packages or downloads model weights itself.
6. Before creating a paid Community GPU, get **explicit spend approval with the current hourly price, storage costs, stop time and approved budget**. Prior proposal of up to US$20 or 24 GPU-hours is a planning cap, **not a guaranteed billing stop**.

## Phase 1: CPU-only dry-run / preflight (safe)

Run from the directory qa/multimedia-director:

~~~sh
python3 -m unittest discover -s tests -p 'test_lora_smoke.py' -v
python3 -m unittest discover -s tests -p 'test_pipeline_e2e.py' -v

python3 scripts/train-smolvlm2-lora.py \
  --prepared /authorized-data/director-prep-qwen-001 \
  --assets-root /authorized-data/abo-images
~~~

No torch, model weights or GPU are loaded by the default command; it checks the prepared dataset against `--model` (default Qwen/Qwen3-VL-4B-Instruct) and prints counts and the selected base model. It REJECTS forged/inconsistent stage format, a packet sealed for a different base model or under the previous manifest schema, missing 200 heldout declaration, test.jsonl in training folder, any train/val group or exact hash overlap, missing images or checksum changes, unsupported licenses, bad Director target JSON and altered sample IDs.

A pass does **not** prove license rights, visual accuracy or that the selected model's processor works. The test fixture uses synthetic small PNGs, not real product photos.

## Phase 2: measured multimodal GPU smoke (requires separate authorization)

These commands are **documentation only**, not run by GitHub Actions or the assistant. On an authorized single-GPU machine with vetted data/model:

~~~sh
nvidia-smi
python3 scripts/train-smolvlm2-lora.py \
  --prepared /authorized-data/director-prep-qwen-001 \
  --assets-root /authorized-data/abo-images \
  --model Qwen/Qwen3-VL-4B-Instruct \
  --model-dir /workspace/models/Qwen3-VL-4B-Instruct \
  --output-dir /workspace/outputs/bico-director-lora-smoke-001 \
  --max-steps 5 \
  --max-seq-len 4096 \
  --run --acknowledge-paid-gpu
~~~

The script enforces: local checkpoint only, no network downloads, no pickle-format weights, a `model_type` matching the selected base model (`qwen3_vl`, or `idefics3`/`smolvlm` for the gated 2B legacy), a GPU with approximately >=16GiB VRAM, LoRA rank 8 / alpha 16 on text-decoder q_proj/v_proj **only** (never `model.visual.*` or any vision/connector module), gradient checkpointing for the 4B primary so its activations fit a ~20 GiB card, one image per microbatch, accumulation=8, max 20 optimizer steps, image max dimension 768, no truncation of image tokens, and a strict assistant-only target loss mask. It aborts if it cannot prove the multimodal prompt is a prefix of the full conversation, or if a required vision tensor is missing or empty — `pixel_values` for every model and additionally `image_grid_thw` for Qwen3-VL, without which image tokens carry no positions.

**Actual Qwen3-VL-4B compatibility through this runner, optimizer behavior, memory use, BF16/FP16, Trainer argument versions and LoRA load/save remain unverified.** If an API mismatch occurs, repair only after inspecting official model/processor behavior and a measured smoke result. Do not invent a success report.

## Phase 3: checkpoint, cost and model quality gate

Once authorized run really completes, inspect the adapter and processor output, run-summary.json, measured peak GPU VRAM, throughput, elapsed time and *provider billing*. Verify adapter reload from scratch before deleting the source GPU and terminate the pod, attached volumes, snapshots and endpoints after exporting checksummed artifacts.

Benchmark:
- A: current text-only Creative Director (Agnes), explicitly labeled **no image input**.
- B: image-grounded base model **without** LoRA on real, unseen licensed images.
- C: exactly the same base model plus the new LoRA adapter on identical heldout inputs.

Arms B and C were measured on the legacy SmolVLM2-2.2B base on 1-2 Nov 2026 and both failed the contract (0/50); the Qwen3-VL-4B primary has so far only been measured zero-shot, without LoRA. B and C for the 4B primary are **not yet run**.
- Count actual contract JSON pass, human-verified observed facts, false/unsupported claims, label/logo preservation, diversity of concepts, continuity, p50/p95 latency, cost per accepted result, and worst-case errors. Training loss alone is not sufficient.
- Do not enable Studio's model selector or Account API inference until user isolation, billing, quote approval, rate limiting, fallback, media privacy, SSO/browser E2E and human visual QA have all passed.

## CI location

The GitHub Actions workflow is **public only**:
https://github.com/farijarifriyanto-debug/BotConnector/blob/native-agent-integration/.github/workflows/multimedia-director-public.yml

The Studio project remains private:
https://github.com/farijarifriyanto-debug/bico-studio/pull/80

The public CI never contacts the private repo and does not validate production integration. Keep PR #80 in Draft until real model and production gates pass.

## 1 Nov 2026 — offline fail-closed compatibility preflight

Public synthetic tests additionally guard the existing LoRA runner against two previously possible false PASS states:

- A local checkpoint with `config.json` and any `.safetensors` file could pass the pre-import check even when its `model_type` was unrelated to the selected base model. The runner now requires `qwen3_vl` for the primary, or `idefics3`/`smolvlm` for the gated 2B legacy, before importing Torch/CUDA, reading the same architecture table the serving probe uses. This does **not** establish model identity, weight integrity, licensing or actual model size; a real checkpoint must still be independently pinned/verified.
- A processor result could contain `pixel_values: []`, `[None]`, an empty tensor or malformed nested structure and pass presence-only validation. The runner now requires **nonempty tensor-like payloads** for every tensor the selected architecture needs — `pixel_values` for both bases, plus `image_grid_thw` for Qwen3-VL — in BOTH the prompt and the complete user/assistant messages. Synthetic fake-processor regressions cover missing, nested-empty and text-only cases.

These tests only prove that empty/invalid input representations are rejected. They do **not** prove compatibility with the real Qwen3-VL AutoProcessor, real image correctness, a successful forward/backward pass, GPU VRAM requirement, LoRA quality or training permissions. Do not add private GitHub Actions or release a model. Prior 260-source photo audit and six AI drafts remain **unapproved**, and no GPU rental/training is authorized.
