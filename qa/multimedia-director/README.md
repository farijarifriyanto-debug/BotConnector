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
