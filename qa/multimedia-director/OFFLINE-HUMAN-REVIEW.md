# BICO Multimedia Director — human visual review offline

This public repository contains ONLY a generic Python Tkinter/Pillow reviewer and synthetic tests. No ABO/Cleveland image files, customer images, commercial keys, models, reviews or private application code are committed.

On the owner's Windows workstation, open the Desktop launcher **BICO-Review-260-Produk-Internet.cmd**. It starts the local script and reads the already-curated **260 real ABO source photos** from the private local curation folder. It requires Python, tkinter and Pillow, already verified installed on that machine.

Alternative, run from PowerShell:

~~~powershell
$dir = "$HOME\Desktop\BICO-Internet-Curation-20261031"
python "$dir\BICO_Review_Produk_Offline.py" --data "$dir\abo-proposed-review-260.jsonl"
~~~

The GUI displays each **original source image**, initial metadata category, untrusted source title and proposed split. Human reviewers can enter: visual status (pending/candidate/needs_check/reject), corrected category, facts actually visible, uncertain/unreadable details, preservation rules, 3 ad concepts, rights/brand/privacy notes and a reviewer code. Save/Next writes an atomic file beside the manifest:

- bico-manual-visual-review-state.json — decision state; no photo bytes
- Local original photos remain untouched; source URL and SHA256 are checked before displaying
- candidate means **eligible for further review**, never license cleared or training approved.

The GUI has NO networking, cloud call, model inference or GPU training. To audit SHA256 of all source images headlessly:

~~~powershell
python "$dir\BICO_Review_Produk_Offline.py" --data "$dir\abo-proposed-review-260.jsonl" --audit
~~~

To export recorded decisions to JSONL (never silently overwrites an earlier export):

~~~powershell
python "$dir\BICO_Review_Produk_Offline.py" --data "$dir\abo-proposed-review-260.jsonl" --export "$dir\bico-review-export-001.jsonl"
~~~

The source license according to the current AWS Open Data Registry is ABO CC BY 4.0, but the copyright license does not imply all brand/trademark/privacy rights or automatic permission for third-party GPU upload. Legal, identity, logo, caption and semantic duplicate review must precede promotion to a different approved training dataset. Original raw images are not released to GitHub Actions.

**Current data:** 1,960 ABO plus 220 separate CMA CC0 images, with 260 selected ABO review cases (50 train / 10 val / 200 unseen holdout **proposals**), 80 ABO reserves and 80 supplementary CMA art-material cases. The automatic screen excluded 472 near-pair-marked ABO candidates and 64 objective quality flags from auto-selection, without deleting raw images. No human-grounded Director labels have yet been approved.

**Test evidence:** live Windows CLI hash audit matched all 260 source images; Tkinter/Pillow UI initialization smoke passed. Public Actions runs 12 synthetic unit tests covering hashes, tampering, state schema/permissions, JSONL export and no overwrite. No human click-through or actual model quality is claimed.

Target remains lightweight **SmolVLM2-2.2B**. Real image baseline, then LoRA only after verified rights and explicit rental budget approval.

## Optional AI draft suggestions — TRAIN ONLY, not human approved

Six preliminary AI assistant drafts were created by actually inspecting six original ABO product images. These source-grounded suggestions are stored only in the private local curation folder as **assistant-visual-drafts-six-NOT-FOR-TRAINING.jsonl** (image SHA256, original official source URL, train split, explicit false training/GPU flags).

The owner's Windows Desktop launcher **BICO-Review-260-Produk-Internet.cmd** now opens the same local GUI with the private --drafts file. Manual command:

    python BICO_Review_Produk_Offline.py --data abo-proposed-review-260.jsonl --drafts assistant-visual-drafts-six-NOT-FOR-TRAINING.jsonl

Use **Muat draft AI (train saja)** to opt in for one SKU. A confirmation appears before any prefill; the draft enters the GUI fields **in memory only** and status becomes needs_check. The reviewer must correct visible facts, brand/trademark, privacy, preservation rules and 3 proposed scenes, then explicitly Save. Nothing is auto-approved or auto-exported. The GUI refuses validation/heldout sources, duplicate drafts, wrong image hashes or URLs, missing concepts, and any training/GPU permission flag switched on.

Source-inspection discoveries: SKU **B07K71H6GP** was incorrectly categorized as clothing but shows a bandage package; SKU **B07RCN49NW** shows branding/artwork on a phone case differing from the product catalog title. Metadata must not be blindly promoted to image facts or brand truth.

The actual Windows CPU-only audit confirmed **260/260 source SHA256** and **6/6 train-only suggestions**. This is an assistant-written **draft**, not human review and NOT a result from SmolVLM2. SmolVLM2-2.2B is not installed locally; larger 8B/12B vision models were deliberately not used. No inference server, paid GPU or production integration was started.

Only generic code/tests/docs are in the public BotConnector repository. The real photos, assistant source-backed draft files and eventual reviewer state stay privately on the owner's machine. Public GitHub Actions run synthetic tests only.

## No-GO review readiness audit (offline, original image SHA256)

The same existing reviewer now supports `--readiness-report`: it opens the private 260-row review manifest,
the optional six train-only AI drafts and existing human review state (if any), verifies original
**image SHA256 for every source**, and writes a new JSON report containing progress counts, proposed
split counts, missing field names and a prioritized queue of SKUs requiring independent review.

```powershell
$dir = "$HOME\Desktop\BICO-Internet-Curation-20261031"
python "$dir\BICO_Review_Produk_Offline.py" `
  --data "$dir\abo-proposed-review-260.jsonl" `
  --drafts "$dir\assistant-visual-drafts-six-NOT-FOR-TRAINING.jsonl" `
  --readiness-report "$dir\review-readiness-my-new-run.json"
```

**Actual first run on 1 Nov 2026:** 260/260 actual image SHA256 verified;
260 unreviewed (`pending`), 0 candidate, 0 rejected, 6 source-bound
AI drafts waiting for independent human inspection, **0 training-approved**.
The underlying `bico-manual-visual-review-state.json` has not been created
by a reviewer yet. The report is deliberately `NO_GO_UNAPPROVED_DATA`.

The report file **refuses overwrite** to preserve an audit trail. It never
contains source photo bytes, reviewer annotations or model weights. A
syntactically complete review form is still not a quality, rights or training
approval. The script refuses saved review states attempting to flip
`annotation_finalized`, `license_approval`, `privacy_approval`,
`training_approved` or `third_party_gpu_allowed` and detects source URL or
split tampering. AI-produced drafts never count as independent human labels.

The extra report checks are tested with synthetic photos via **public
GitHub Actions**; no GitHub workflows are created in private Studio.

## Review queue UX and unsaved changes protection (1 Nov 2026)

When opened, the existing Tkinter reviewer now starts with the highest-priority
**train image with an available AI draft** (if it still needs independent review).
The **Review prioritas** control advances to the next unreviewed / needs-check
candidate, with other train candidates before val/test. It does not change
split assignments, image files, legal flags or source manifests.

**Critical protection:** Previously, searching for another SKU could discard
unsaved edits and Next/Previous could automatically save a pending item.
Now every navigation/search/close action checks whether review fields have
changed and prompts **Yes = save, No = discard local unsaved edits, Cancel = stay**.
Unchanged fields never get silently saved as a review decision.
The existing **Muat draft AI (train saja)** button still requires consent
before replacing unsaved inputs, and pending review remains unapproved.

Python syntax and real 260 source SHA256 + six draft schema audit pass
on the owner's authorized Windows computer. Public synthetic regression
tests cover the priority algorithm; automated tests do NOT claim real
end-user interactive click-through or visual truth approval.

## Save button repair (1 November 2026)

The **Simpan** button now invokes an actual write instead of the previous
no-op `navigate(0)`. A failed disk write displays **Gagal menyimpan** and
does **not** mutate the in-memory review decision. Search, navigation and
close continue to prompt for unsaved changes; no AI draft is auto-approved.
Public synthetic CI checks the button binding and both successful and
simulated-failure persistence. This is a source/test fix, **not** evidence
of end-user visual review or permission to train.
