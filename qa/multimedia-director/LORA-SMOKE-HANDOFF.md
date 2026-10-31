# BICO Multimedia Director — SmolVLM2-2.2B image LoRA smoke runbook

**Prepared on:** 31 October 2026  
**Status:** Public offline training script and synthetic tests ONLY. No licensed raw ABO image dataset has been collected, no model checkpoint downloaded, no RunPod pod rented, no LoRA weights trained and no production changes made.

## Decisions

- Multimodal Director reads the product or shot reference **pixels** and generates fact-grounded JSON for the existing Studio Creative Director and Film Project. It does not replace the production image/video generator.
- **Primary:** HuggingFaceTB/SmolVLM2-2.2B-Instruct. 4B is conditional **only after a measured 2B failure**, 7B/8B/9B are excluded from this pilot.
- Public repo holds only test scripts, synthetic cases and tooling. Real reviewed commercial-training datasets, customer media, credentials, model checkpoints and private Studio implementation must **never** be pushed here.
- The planned rented hardware is a single **RunPod Community Cloud GPU 48GB** for temporary training, not serving. A cheaper 16/24GB Community GPU may be considered only after demonstrated fit/price comparison. Nothing in this repo starts a pod.

## Prerequisites

1. Obtain media **from a licensed public source** on an authorized non-production machine. For ABO, start with the official listing metadata and human review workflow in ABO-SFT-HANDOFF.md. Raw dataset downloads are outside GitHub Actions. Keep source URL, attribution, explicit rights for commercial training and third-party GPU processing, checksum, non-PII review and approval per item.
2. Run prepare-multimedia-director-data.mjs with at least **50 train**, **10 validation**, **200 holdout test** across disjoint products/brands/characters, then prepare-smolvlm2-sft.py with explicit --write. The latter only exports train and val, never test.
3. **Human QA** must inspect visual facts, product labels, logo preservation and image copyrights; automated flags are not independent legal or semantic proof.
4. Confirm SmolVLM2-2.2B official commercial license and base checkpoint revision, and separately provision authorized storage. Copy model weights into a trusted local --model-dir on a GPU host after checking SHA256 and licensing. Use audited **safetensors only**, never unknown .bin/.pt files, and avoid arbitrary remote code.
5. The LoRA runner requires torch, transformers, accelerate, peft, Pillow, safetensors **already installed in a pinned compatible local environment**. These exact version combinations and SmolVLM2 image processor behavior have **not** yet been tested on a real GPU. The script never installs packages or downloads model weights itself.
6. Before creating a paid Community GPU, get **explicit spend approval with the current hourly price, storage costs, stop time and approved budget**. Prior proposal of up to US$20 or 24 GPU-hours is a planning cap, **not a guaranteed billing stop**.

## Phase 1: CPU-only dry-run / preflight (safe)

Run from the directory qa/multimedia-director:

~~~sh
python3 -m unittest discover -s tests -p 'test_lora_smoke.py' -v
python3 -m unittest discover -s tests -p 'test_pipeline_e2e.py' -v

python3 scripts/train-smolvlm2-lora.py \
  --prepared /authorized-data/smolvlm2-prep-001 \
  --assets-root /authorized-data/abo-images
~~~

No torch, model weights or GPU are loaded by the default command; it checks the prepared dataset and prints counts. It REJECTS forged/inconsistent stage format, missing 200 heldout declaration, test.jsonl in training folder, any train/val group or exact hash overlap, missing images or checksum changes, unsupported licenses, bad Director target JSON and altered sample IDs.

A pass does **not** prove license rights, visual accuracy or that the SmolVLM2 processor works. The test fixture uses synthetic small PNGs, not real product photos.

## Phase 2: measured multimodal GPU smoke (requires separate authorization)

These commands are **documentation only**, not run by GitHub Actions or the assistant. On an authorized single-GPU machine with vetted data/model:

~~~sh
nvidia-smi
python3 scripts/train-smolvlm2-lora.py \
  --prepared /authorized-data/smolvlm2-prep-001 \
  --assets-root /authorized-data/abo-images \
  --model-dir /workspace/models/SmolVLM2-2.2B-Instruct \
  --output-dir /workspace/outputs/bico-director-lora-smoke-001 \
  --max-steps 5 \
  --max-seq-len 4096 \
  --run --acknowledge-paid-gpu
~~~

The script enforces: local checkpoint only, no network downloads, no pickle-format weights, a GPU with approximately >=16GiB VRAM, LoRA rank 8 / alpha 16 on text q_proj/v_proj **only**, one image per microbatch, accumulation=8, max 20 optimizer steps, image max dimension 768, no truncation of image tokens, and a strict assistant-only target loss mask. It aborts if it cannot prove the multimodal prompt is a prefix of the full conversation or if pixel_values are missing.

**Actual SmolVLM2 model compatibility, optimizer behavior, memory use, BF16/FP16, Trainer argument versions and LoRA load/save remain unverified.** If an API mismatch occurs, repair only after inspecting official model/processor behavior and a measured smoke result. Do not invent a success report.

## Phase 3: checkpoint, cost and model quality gate

Once authorized run really completes, inspect the adapter and processor output, run-summary.json, measured peak GPU VRAM, throughput, elapsed time and *provider billing*. Verify adapter reload from scratch before deleting the source GPU and terminate the pod, attached volumes, snapshots and endpoints after exporting checksummed artifacts.

Benchmark:
- A: current text-only Creative Director (Agnes), explicitly labeled **no image input**.
- B: original SmolVLM2-2.2B image-grounded base model on real, unseen licensed images.
- C: exactly the same 2B model plus new LoRA adapter on identical heldout inputs.
- Count actual contract JSON pass, human-verified observed facts, false/unsupported claims, label/logo preservation, diversity of concepts, continuity, p50/p95 latency, cost per accepted result, and worst-case errors. Training loss alone is not sufficient.
- Do not enable Studio's model selector or Account API inference until user isolation, billing, quote approval, rate limiting, fallback, media privacy, SSO/browser E2E and human visual QA have all passed.

## CI location

The GitHub Actions workflow is **public only**:
https://github.com/farijarifriyanto-debug/BotConnector/blob/native-agent-integration/.github/workflows/multimedia-director-public.yml

The Studio project remains private:
https://github.com/farijarifriyanto-debug/bico-studio/pull/80

The public CI never contacts the private repo and does not validate production integration. Keep PR #80 in Draft until real model and production gates pass.
