# BICO Multimedia Director — ABO samples -> 2B multimodal SFT (31 Oct 2026)

**Status:** Tools implemented, offline tests required. No actual ABO files, model weights or customer data were downloaded; no GPU rented or model trained. This lives in the **public BotConnector QA repository**, never in private GitHub Actions.

## A. Prepare raw product data without spending GPU money

Official source: https://registry.opendata.aws/amazon-berkeley-objects/
Source documentation and official download index: https://amazon-berkeley-objects.s3.us-east-1.amazonaws.com/index.html

ABO metadata contains product listings, item IDs and image IDs. It is subject to CC BY 4.0 attribution and asset-level checks. Do not treat product names or metadata as facts observed in pixels.

1. On a machine **other than the BICO production VPS**, download ABO's official small listings metadata archive (historical published filename: abo-listings.tar, around 83 MB) manually after checking source licensing/terms. There is no implicit network access in these QA tools.
2. Create an **unapproved review queue** from existing local metadata:

~~~sh
cd qa/multimedia-director
python3 scripts/select-abo-review.py \
  --metadata /private-data/abo-listings.tar \
  --out /private-data/review-queue-50.jsonl \
  --max-items 50 \
  --seed bico-first-pilot
~~~

The parser accepts JSON, JSONL, gzip or a tar containing JSON/JSONL files; no tar member is extracted. The output contains product ID and image IDs only, metadata hints, and these deliberately unsafe-for-training flags: review_status=pending, asset_license_status=unverified, commercial_training_allowed=false, third_party_compute_allowed=false, train_ready=false. This is a **selection queue**, NOT a finished dataset or permission to use Community GPU.

3. Review the 50 candidate records and manually locate/copy licensed image bytes from official ABO image shards. Avoid bulk download of the ~110 GB full-resolution image archive until necessary. The published small-image archive is several GB and contains images with insufficient resolution for reliable small-label OCR. The script DOES NOT resolve S3 shard/image paths or download any image bytes. Confirm exact source metadata layout on a real archive; the parser is tested on synthetic fixtures only.
4. For each asset record attribution, source, rights evidence, image SHA256, product group, PII, media format, brief, visual verified facts and human-verified Director target. Do NOT auto-mark data as approved. Human QA must inspect every photo and separate brand claims in source metadata from pixels seen in the image.
5. Create the structured approved manifest described in the private Draft PR #80. Stage it through the existing rights/checksum/leakage gate:

~~~sh
node scripts/prepare-multimedia-director-data.mjs \
  --manifest /private-data/approved-manifest.jsonl \
  --registry /private-data/licensed-source-registry.json \
  --assets-root /private-data/abo-images \
  --out /private-data/reviewed-stage-001
~~~

This requires >=50 train, >=10 validation and >=200 truly unseen test examples; the 50-item raw shortlist alone does NOT meet this gate. The official source registry used privately contains ABO and explicit non-commercial blocks, so never replace it with an automatically permissive registry.

## B. Prepare lightweight SmolVLM2 SFT examples

Once stage summary reports mode=gated_dataset and all three split sizes are complete:

~~~sh
python3 scripts/prepare-smolvlm2-sft.py \
  --staged /private-data/reviewed-stage-001 \
  --assets-root /private-data/abo-images \
  --out-dir /private-data/smolvlm2-prep-001
~~~

By default the command only validates local image SHA256 and checks for split leakage, then reports counts. It **does not write data** without explicit --write and **never loads model/GPU**.

To export train.jsonl, val.jsonl and a manifest (intentionally NOT the held-out test set), repeat with --write. The output contains a multimodal chat structure: user image placeholder plus Indonesian Director brief, assistant JSON target, source/license/attribution, original image path. The records are NOT directly consumable by SFTTrainer until a model-specific adapter loads PIL images via to_runtime_messages() and applies SmolVLM2's vision processor, chat template, label mask and data collator.

**One 48 GB RunPod Community GPU is the temporary *training* choice only**, and no paid resource is created by any workflow. The base candidate is HuggingFaceTB/SmolVLM2-2.2B-Instruct; 4B is a conditional fallback only after documented quality failure of ~2B. Before renting, verify live GPU rates, complete model license review, run a licensed image-grounded baseline, establish storage/export and cost stop, then get explicit spending approval. No customer media/PII/credentials may be sent to community GPU.

## C. Test locally or in public GitHub Actions

~~~sh
python3 -m unittest discover -s tests -p 'test_abo_sft_preparation.py' -v
python3 -m unittest discover -s tests -p 'test_multimedia_vlm_probe.py' -v
node --test tests/multimediaDatasetPipeline.test.mjs tests/multimediaDirectorBenchmark.test.mjs
~~~

All automated test images and listings are generated from synthetic fixtures. Public CI runs offline, read-only and without cloud secrets or weights. A green check validates preparation tools and synthetic cases, **not** model accuracy, image understanding, customer privacy automatically or rights clearance.
