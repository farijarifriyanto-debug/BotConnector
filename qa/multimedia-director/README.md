# BICO Multimedia Director — public offline CI mirror

This directory contains **only standalone, assistant-created offline test tools and synthetic fixtures**, mirrored byte-for-byte from a private Draft PR in the BICO Studio repository. Public GitHub Actions run the exact source blobs included here.

Scope:
- Image dataset manifest validation (declared commercial/third-party rights, reviewed metadata, SHA256 and train/val/test split isolation).
- Synthetic JSON/Director output contract checks.
- Python dry-run preflight for a research-grade ~2B visual-language model (never downloads weights by default).

**No** private BICO Studio production implementation, customer photo, licensed raw dataset, account token, environment variable, model weight, or private GitHub pull request content is fetched by this workflow. The private repository is **not** public, and the public workflow cannot validate code changes it does not contain.

Do not interpret passing CI as real image-grounding quality, successful GPU fine-tuning, a valid legal clearance or a production deployment. No GPU is provisioned or charged.

Maintainer: public workflow should be updated only when these safe test scripts change. Compare the Git blob SHA between each private source file and its corresponding public copy to prove parity (same SHA means same bytes), and log any parity gaps.

Run locally:

```sh
cd qa/multimedia-director
node --test tests/multimediaDatasetPipeline.test.mjs tests/multimediaDirectorBenchmark.test.mjs
node scripts/benchmark-multimedia-director.mjs tests/fixtures/multimedia-director-synthetic.jsonl tests/fixtures/multimedia-director-synthetic-predictions.jsonl
python3 -m unittest discover -s tests -p test_multimedia_vlm_probe.py -v
```

Security: repository Actions are read-only and do not use secrets, repository dispatch, fork write tokens, or third-party data access.


## 2B LoRA smoke preparation (no training in CI)

- [SmolVLM2-2.2B LoRA smoke runner](scripts/train-smolvlm2-lora.py): CPU-only preflight by default; only uses the actual image-aware processor and assistant-label masking with explicit paid-GPU flags and a locally verified model checkpoint.
- [LoRA smoke runbook](LORA-SMOKE-HANDOFF.md): data permissions, GPU preflight, exact CLI, checkpoint/export, rollback and release gates.
- [End-to-end synthetic pipeline test](tests/test_pipeline_e2e.py): builds 260 synthetic image cases and verifies Node rights gate -> Python SFT staging -> 2B runner preflight with holdout sealed.

No real ABO images, model weights, production customer data or credentials are public. A public green CI run is not actual model training evidence.


## Real product photo collection: private local quarantine

Use [audit-product-intake.py](scripts/audit-product-intake.py) to verify a **private** BICO QA collection of genuine sourced product images without uploading anything:

```sh
python3 scripts/audit-product-intake.py --root /path/to/private/BICO-Multimedia-Product-Dataset-20261031 --expected-count 3
```

It validates SHA256, source attribution, image paths, draft annotation IDs, duplicate files and locked training-rights flags. Its success means **QA intake only**: training-approved count must remain zero. Stock photo commercial-use permissions should not be interpreted as automatic permission to train a commercial multimodal model or transfer photos to third-party GPUs. If rights are confirmed, move approved assets to a separate, human-reviewed dataset through the existing rights gate rather than editing this quarantine manifest.

The public GitHub Actions job tests this validator against **synthetic local images**. Real Pexels/ABO photos and user-specific filenames/paths are never included in this public repository or its workflow.
