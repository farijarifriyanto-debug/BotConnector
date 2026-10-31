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
