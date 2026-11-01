#!/usr/bin/env python3
"""Offline, human-operated BICO product image review.

Usage:
  python scripts/review-product-images.py --data path/to/abo-proposed-review-260.jsonl
  python scripts/review-product-images.py --data ... --audit
  python scripts/review-product-images.py --data ... --export /path/review-decisions.jsonl

Requires tkinter and Pillow ONLY for the graphical viewer.
No network, inference, auto-approval, or changes to source photographs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

SCHEMA = "botconnector.offline-visual-review.v1"
DRAFT_SCHEMA = "botconnector.assistant-image-observation-draft.v1"
TARGET_SCHEMA = "botconnector.multimedia-director.v1"
STATUSES = ("pending", "candidate", "needs_check", "reject")
FIELDS = ("category_corrected", "observed_facts", "unknowns",
          "preservation_rules", "concept_1", "concept_2", "concept_3",
          "brand_privacy_notes", "reviewer")
LABELS = {
 "category_corrected": "Kategori yang benar",
 "observed_facts": "Fakta terlihat — satu per baris",
 "unknowns": "Tidak pasti / label tidak terbaca",
 "preservation_rules": "Aturan menjaga bentuk, label, logo, warna",
 "concept_1": "Konsep 1 — scene / mood / tagline",
 "concept_2": "Konsep 2 — scene / mood / tagline",
 "concept_3": "Konsep 3 — scene / mood / tagline",
 "brand_privacy_notes": "Pemeriksaan merek, privasi dan lisensi",
 "reviewer": "Kode reviewer",
}


def load_rows(path):
    records = []
    seen = set()
    for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        sid = record.get("sku")
        digest = record.get("image_sha256")
        if (not isinstance(sid, str) or not sid or sid in seen
            or not isinstance(digest, str) or len(digest) != 64
            or not isinstance(record.get("local_image_path"), str)
            or record.get("commercial_training_approved") is not False
            or record.get("training_ready") is not False):
            raise ValueError("invalid or prematurely approved source at line " + str(index))
        seen.add(sid)
        records.append(record)
    if not records:
        raise ValueError("empty source manifest")
    return records


def load_ai_drafts(path, rows):
    """Validate unapproved, train-only image-grounded suggestions without writing state.

    Drafts are NOT human labels. No validation or held-out test image may be
    imported for assistant-generated SFT suggestions through this feature.
    """
    if not path.is_file():
        raise ValueError("draft file missing")
    reference = {r["sku"]: r for r in rows}
    drafts = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        sku = obj.get("item_id")
        if (obj.get("schema") != DRAFT_SCHEMA or not isinstance(sku, str)
            or sku not in reference or sku in drafts):
            raise ValueError("invalid or duplicate assistant draft item at line " + str(line_number))
        source = reference[sku]
        if source.get("proposed_split") != "train" or obj.get("proposed_split") != "train":
            raise ValueError("AI draft refused for validation/test holdout: " + sku)
        if (obj.get("image_sha256") != source.get("image_sha256")
            or obj.get("image_source_url") != source.get("source_url")):
            raise ValueError("draft provenance or original image hash mismatch: " + sku)
        if (obj.get("annotation_status") != "AI_DRAFT_NEEDS_INDEPENDENT_HUMAN_REVIEW"
            or obj.get("training_approved") is not False
            or obj.get("third_party_gpu_allowed") is not False
            or obj.get("annotation_finalized") is not False
            or obj.get("license_review") != "pending"
            or obj.get("brand_privacy_claims_review") != "pending"):
            raise ValueError("AI draft cannot authorize training or bypass human review: " + sku)
        target = obj.get("target")
        if (not isinstance(target, dict)
            or target.get("schema") != TARGET_SCHEMA or target.get("task") != "product_photo"):
            raise ValueError("invalid Director draft target: " + sku)
        visual = target.get("visual")
        if not isinstance(visual, dict):
            raise ValueError("draft missing observed facts and unknowns: " + sku)
        facts, unknowns = visual.get("observed_facts"), visual.get("unknowns")
        rules, concepts = target.get("preservation_rules"), target.get("concepts")
        def words(items):
            return isinstance(items, list) and all(isinstance(x, str) and x.strip() for x in items)
        if (not words(facts) or not facts or not words(unknowns)
            or not words(rules) or not rules or not isinstance(concepts, list)
            or len(concepts) != 3):
            raise ValueError("Director draft required visual fields incomplete: " + sku)
        if any(not isinstance(x, dict) or
               any(not isinstance(x.get(k), str) or not x[k].strip()
                   for k in ("title", "scene", "mood", "tagline"))
               for x in concepts):
            raise ValueError("Director draft concepts malformed: " + sku)
        if len({x["scene"].strip().casefold() for x in concepts}) != 3:
            raise ValueError("Director draft has duplicated scenes: " + sku)
        category = obj.get("category_corrected_proposal")
        if not isinstance(category, str) or not category.strip():
            raise ValueError("draft has no category correction: " + sku)
        drafts[sku] = obj
    if not drafts:
        raise ValueError("no valid source-grounded drafts")
    return drafts


def source_image(row):
    path = Path(row["local_image_path"])
    if not path.is_absolute() or not path.is_file():
        raise ValueError("missing local source image for " + row["sku"])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != row["image_sha256"].lower():
        raise ValueError("original image SHA256 mismatch: " + row["sku"])
    return path


def read_state(path, rows):
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != SCHEMA or not isinstance(document.get("decisions"), list):
        raise ValueError("review state schema mismatch")
    reference = {r["sku"]: r["image_sha256"] for r in rows}
    decisions = {}
    for raw in document["decisions"]:
        if not isinstance(raw, dict):
            raise ValueError("invalid review decision")
        sid = raw.get("sku")
        if sid not in reference or raw.get("image_sha256") != reference[sid] or sid in decisions:
            raise ValueError("review item missing or SHA256 mismatch")
        if raw.get("status") not in STATUSES:
            raise ValueError("invalid review status")
        if raw.get("status") == "reject" and (
                not isinstance(raw.get("reject_reason"), str)
                or not raw["reject_reason"].strip()):
            raise ValueError("rejected review must record a rejection reason")
        if (raw.get("training_approved") is not False
            or raw.get("third_party_gpu_allowed") is not False
            or raw.get("annotation_finalized", False) is not False
            or raw.get("license_approval", "pending") != "pending"
            or raw.get("privacy_approval", "pending") != "pending"):
            raise ValueError("review must never authorize model training, final annotation or GPU transfer")
        ref = next(row for row in rows if row["sku"] == sid)
        if (raw.get("source_url", ref.get("source_url")) != ref.get("source_url")
            or raw.get("proposed_split", ref.get("proposed_split")) != ref.get("proposed_split")):
            raise ValueError("review source URL or proposed split mismatch")
        decisions[sid] = raw
    return decisions


def write_state(path, decisions):
    if path.is_symlink():
        raise ValueError("refusing symlink review state")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"schema": SCHEMA,
                "purpose": "local visual triage, not training approval",
                "training_approved": False, "third_party_gpu_allowed": False,
                "decisions": list(decisions.values())}
    temp = path.with_name(path.name + ".tmp")
    if temp.exists():
        raise ValueError("temporary state file already exists")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def persist_decision(path, decisions, item):
    """Persist the full review state before mutating GUI memory.

    If disk I/O fails, the in-memory record must remain unchanged so that
    unsaved annotations are not treated as persisted decisions.
    """
    updated = dict(decisions)
    updated[item["sku"]] = item
    write_state(path, updated)
    decisions.clear()
    decisions.update(updated)


def export_review(path, decisions):
    if path.exists():
        raise ValueError("refusing to overwrite existing export")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for item in decisions.values():
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def approval_missing_fields(values):
    """Form fields that must be non-empty before a visual approval is recorded."""
    return [field for field in FIELDS
            if not isinstance(values.get(field), str) or not values[field].strip()]


def build_candidate_decision(row, values):
    """Record that a human accepted the VISUAL CHECK ONLY (status candidate).

    Never sets training, GPU, license, privacy or annotation-finalized rights.
    The original photo is re-verified (SHA-256) before anything is recorded.
    """
    source_image(row)
    missing = approval_missing_fields(values)
    if missing:
        raise ValueError("visual approval still missing: " + ", ".join(missing))
    item = {"sku": row["sku"], "image_sha256": row["image_sha256"],
            "source_url": row["source_url"],
            "proposed_split": row.get("proposed_split", ""),
            "status": "candidate",
            "training_approved": False, "third_party_gpu_allowed": False,
            "annotation_finalized": False,
            "license_approval": "pending", "privacy_approval": "pending"}
    for field in FIELDS:
        item[field] = values.get(field, "")
    return item


def build_reject_decision(row, reason, reviewer=""):
    """Record a rejection WITH a mandatory reason and reviewer identity.

    Never authorizes anything. The original photo is re-verified (SHA-256).
    """
    source_image(row)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("rejected review must record a rejection reason")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("rejected review must record the reviewer identity code")
    return {"sku": row["sku"], "image_sha256": row["image_sha256"],
            "source_url": row["source_url"],
            "proposed_split": row.get("proposed_split", ""),
            "status": "reject", "reject_reason": reason.strip(),
            "reviewer": (reviewer or "").strip(),
            "training_approved": False, "third_party_gpu_allowed": False,
            "annotation_finalized": False,
            "license_approval": "pending", "privacy_approval": "pending"}


def build_triage_decision(row, chosen_status, values):
    """Build a combobox-save decision; NEVER a bare reject.

    A rejection without a recorded reason would make the whole saved state
    unreadable on the next load, so combobox saves cannot write "reject":
    rejections must go through the Tolak action (build_reject_decision).
    """
    if chosen_status not in STATUSES:
        raise ValueError("invalid review status")
    if chosen_status == "reject":
        raise ValueError("a reject must be recorded through the Tolak action with a reason")
    source_image(row)
    item = {"sku": row["sku"], "image_sha256": row["image_sha256"],
            "source_url": row["source_url"],
            "proposed_split": row.get("proposed_split", ""),
            "status": chosen_status,
            "training_approved": False, "third_party_gpu_allowed": False,
            "annotation_finalized": False,
            "license_approval": "pending", "privacy_approval": "pending"}
    for field in FIELDS:
        item[field] = values.get(field, "")
    return item


def draft_prefill_allowed(row, decision):
    """Show AI suggestions only for UNREVIEWED train items; never a saved label."""
    if row.get("proposed_split") != "train":
        return False
    return decision is None


def draft_field_values(draft):
    """Map a validated assistant draft into displayable form field values.

    The reviewer code stays empty so the human reviewer must authenticate
    every approval with their own identifier.
    """
    target = draft["target"]
    values = {
        "category_corrected": draft["category_corrected_proposal"],
        "observed_facts": "\n".join(target["visual"]["observed_facts"]),
        "unknowns": "\n".join(target["visual"]["unknowns"]),
        "preservation_rules": "\n".join(target["preservation_rules"]),
        "brand_privacy_notes": "AI draft / perlu verifikasi: " + draft.get("risk_notes", ""),
    }
    for i, idea in enumerate(target["concepts"], 1):
        values["concept_" + str(i)] = (
            idea["title"] + " | " + idea["scene"] +
            " | " + idea["mood"] + " | " + idea["tagline"]
        )
    values["reviewer"] = ""
    return values


def next_outstanding(rows, decisions, ai_drafts, current_sku):
    """Index of the next item needing triage after the current one, or None."""
    ordered = review_priority_order(rows, decisions, ai_drafts)
    for index in ordered:
        if rows[index]["sku"] != current_sku:
            return index
    return None


def counter_text(position, total, reviewed):
    """Status line: how many photos a human triaged, how many still pending."""
    reviewed = max(0, min(total, reviewed))
    return (str(position + 1) + "/" + str(total) +
            " • diperiksa: " + str(reviewed) +
            " • pending: " + str(total - reviewed) +
            " • siap training: 0")




def review_readiness_report(rows, decisions, drafts, *, verify_images=True):
    """Data-local human-triage status; NEVER a training authorization or license decision.

    Checks original photos if requested. Full form fields alone cannot establish
    factual correctness, independent review, commercial rights, or model quality.
    Drafts may change scheduling priority but are NOT completed labels.
    """
    from collections import Counter, defaultdict
    counts = Counter(row.get("proposed_split", "unspecified") for row in rows)
    statuses = Counter()
    split_status = defaultdict(Counter)
    outstanding = []
    form_complete = 0
    source_sha_checked = 0
    unreviewed_drafts = 0
    mandatory = (
        "reviewer", "category_corrected", "observed_facts", "unknowns",
        "preservation_rules", "concept_1", "concept_2", "concept_3",
        "brand_privacy_notes",
    )
    for row in rows:
        sku = row["sku"]
        if verify_images:
            source_image(row)
            source_sha_checked += 1
        decision = decisions.get(sku, {})
        status = decision.get("status", "pending")
        if status not in STATUSES:
            raise ValueError("review report has unsupported status")
        split = row.get("proposed_split", "unspecified")
        statuses[status] += 1
        split_status[split][status] += 1
        missing = [name for name in mandatory
                   if not isinstance(decision.get(name), str)
                   or not decision[name].strip()]
        if status == "candidate" and not missing:
            form_complete += 1
        draft_available = sku in drafts
        if draft_available and (status == "pending" or status == "needs_check"):
            unreviewed_drafts += 1
        if status == "pending" or (status == "candidate" and missing) or status == "needs_check":
            reasons = (
                ["no_manual_review"] if status == "pending" else
                ["draft_or_product_requires_independent_review"] if status == "needs_check" else
                ["review_form_missing_fields"]
            )
            outstanding.append({
                "sku": sku, "split": split,
                "status": status, "ai_draft_available": draft_available,
                "reason_codes": reasons,
                "missing_review_fields": missing if status == "candidate" else [],
            })
    outstanding.sort(key=lambda item: (
        0 if item["split"] == "train" and item["ai_draft_available"] else
        1 if item["split"] == "train" else
        2 if item["split"] == "val" else 3,
        item["sku"],
    ))
    return {
        "schema": "botconnector.offline-visual-review-readiness.v1",
        "purpose": "local_human_triage_progress_NOT_train_authorization",
        "total_source_photos": len(rows),
        "source_original_sha256_verified": source_sha_checked,
        "proposed_split_counts": dict(sorted(counts.items())),
        "review_status_counts": {status: statuses.get(status, 0) for status in STATUSES},
        "per_split_status_counts": {
            split: {status: split_status[split].get(status, 0) for status in STATUSES}
            for split in sorted(counts)
        },
        "candidate_visual_review_forms_with_all_fields": form_complete,
        "assistant_drafts_pending_independent_review": unreviewed_drafts,
        "assistant_draft_total": len(drafts),
        "outstanding_count": len(outstanding),
        "outstanding_review_queue": outstanding,
        "human_ground_truth_independently_validated": 0,
        "training_approved": 0,
        "third_party_gpu_allowed": False,
        "baseline_eligible": False,
        "status": "NO_GO_UNAPPROVED_DATA",
        "limitations": [
            "Fields are syntactic completeness only, not factual visual correctness",
            "Candidate is NOT a license, trademark, PII or commercial model-training approval",
            "No actual 2.2B image-model result is measured in this report",
            "Validation/holdout gold labels require separate blinded independent review",
        ],
    }


def write_readiness_report(path, report):
    """Write a private read-only report; avoid destructive overwrite/symlink."""
    if path.exists() or path.is_symlink():
        raise ValueError("refusing to overwrite existing review readiness report")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")




def review_priority_order(rows, decisions, ai_drafts):
    """Returns indices requiring independent human triage, train-draft first.

    Existing validation/holdout samples have no assistant draft prefill.
    No record is approved here: ordering does not change rights or splits.
    """
    def rank(index):
        row = rows[index]
        split = row.get("proposed_split")
        sku = row["sku"]
        if split == "train" and sku in ai_drafts:
            priority = 0
        elif split == "train":
            priority = 1
        elif split == "val":
            priority = 2
        elif split == "test":
            priority = 3
        else:
            priority = 4
        return (priority, sku)
    outstanding = [
        i for i, row in enumerate(rows)
        if decisions.get(row["sku"], {}).get("status", "pending")
        in ("pending", "needs_check")
    ]
    return sorted(outstanding, key=rank)


def review_gui(rows, state_path, ai_drafts=None):
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk
    from PIL import Image, ImageOps, ImageTk

    decisions = read_state(state_path, rows)
    ai_drafts = ai_drafts or {}
    window = tk.Tk()
    window.title("BICO — Review Foto Produk Internet (OFFLINE)")
    window.geometry("1180x850")
    window.minsize(880, 680)
    current = [0]
    photo_ref = [None]
    loaded_form = [None]
    controls = {}
    root = ttk.Frame(window, padding=12)
    root.pack(fill="both", expand=True)
    warning = ttk.Label(root, text="Review visual saja • sumber ABO CC BY 4.0 • "
                        "bukan izin training/GPU • tidak mengunggah gambar")
    warning.pack(anchor="w")
    top = ttk.Frame(root)
    top.pack(fill="x", pady=8)
    counter = ttk.Label(top, text="")
    counter.pack(side="left")
    find_input = ttk.Entry(top, width=28)
    find_input.pack(side="right")
    ttk.Label(top, text="Cari SKU: ").pack(side="right")
    body = ttk.Panedwindow(root, orient="horizontal")
    body.pack(fill="both", expand=True)
    left = ttk.Frame(body, padding=6)
    body.add(left, weight=2)
    photo = ttk.Label(left, anchor="center")
    photo.pack(fill="both", expand=True)
    caption = ttk.Label(left, justify="left", wraplength=450)
    caption.pack(fill="x", pady=5)
    right = ttk.Frame(body, padding=8)
    body.add(right, weight=3)
    canvas = tk.Canvas(right, highlightthickness=0)
    bar = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
    panel = ttk.Frame(canvas)
    canvas.create_window((0, 0), window=panel, anchor="nw")
    canvas.configure(yscrollcommand=bar.set)
    panel.bind("<Configure>", lambda ev: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    status = tk.StringVar(value="pending")
    ttk.Label(panel, text="Status visual — tidak mengubah izin training").pack(anchor="w")
    status_select = ttk.Combobox(panel, textvariable=status, state="readonly", values=STATUSES)
    status_select.pack(fill="x", pady=(0, 8))
    actions = ttk.Frame(panel)
    actions.pack(fill="x", pady=(0, 8))
    for field in FIELDS:
        ttk.Label(panel, text=LABELS[field]).pack(anchor="w", pady=(4, 0))
        if field in ("category_corrected", "reviewer"):
            widget = ttk.Entry(panel)
        else:
            widget = tk.Text(panel, height=3, wrap="word", undo=True)
        widget.pack(fill="x", pady=(0, 5))
        controls[field] = widget

    def read_control(key):
        widget = controls[key]
        return (widget.get().strip() if isinstance(widget, ttk.Entry)
                else widget.get("1.0", "end").strip())

    def fill_control(key, value):
        widget = controls[key]
        if isinstance(widget, ttk.Entry):
            widget.delete(0, "end")
            widget.insert(0, value)
        else:
            widget.delete("1.0", "end")
            widget.insert("1.0", value)

    def form_snapshot():
        return {"status": status.get(), **{field: read_control(field) for field in FIELDS}}

    def display(index):
        current[0] = max(0, min(len(rows)-1, index))
        row = rows[current[0]]
        existing = decisions.get(row["sku"], {})
        try:
            original = source_image(row)
            with Image.open(original) as image:
                resized = ImageOps.exif_transpose(image).convert("RGB")
                resized.thumbnail((480, 540), Image.Resampling.LANCZOS)
            photo_ref[0] = ImageTk.PhotoImage(resized)
            photo.configure(image=photo_ref[0], text="")
        except Exception as exc:
            photo_ref[0] = None
            photo.configure(image="", text="IMAGE ERROR: " + str(exc))
        status.set(existing.get("status", "pending"))
        for field in FIELDS:
            initial = row.get("category", "") if field == "category_corrected" else ""
            fill_control(field, existing.get(field, initial))
        draft = ai_drafts.get(row["sku"])
        if draft_prefill_allowed(row, decisions.get(row["sku"])) and draft is not None:
            for field, value in draft_field_values(draft).items():
                fill_control(field, value)
            status.set("needs_check")
        reviewed = sum(1 for d in decisions.values() if d.get("status") != "pending")
        counter.configure(text=counter_text(current[0], len(rows), reviewed))
        caption.configure(text="SKU: " + row["sku"] +
                          "\nKategori awal (metadata): " + row.get("category", "") +
                          "\nUsulan split: " + row.get("proposed_split", "") +
                          "\nJudul metadata BUKAN fakta visual:\n" +
                          row.get("title_metadata_not_visual_fact", "")[:180] +
                          "\nSumber: " + row.get("source_url", ""))
        loaded_form[0] = form_snapshot()

    def save():
        row = rows[current[0]]
        item = build_triage_decision(
            row, status.get(), {field: read_control(field) for field in FIELDS})
        persist_decision(state_path, decisions, item)
        display(current[0])

    def save_current():
        try:
            save()
        except Exception as exc:
            messagebox.showerror("Gagal menyimpan", str(exc))

    def advance_after_triage(current_sku):
        """Move to the next item that still needs human triage, if any."""
        target = next_outstanding(rows, decisions, ai_drafts, current_sku)
        display(target if target is not None else current[0])

    def approve_current():
        """Setujui Visual: accept ONLY the human visual check, never any rights."""
        row = rows[current[0]]
        try:
            item = build_candidate_decision(
                row, {field: read_control(field) for field in FIELDS})
            persist_decision(state_path, decisions, item)
        except Exception as exc:
            messagebox.showerror(
                "Setujui Visual belum bisa",
                str(exc) + "\n\nIsi kode reviewer dan fakta visual dulu, atau pilih Koreksi.")
            return
        advance_after_triage(row["sku"])

    def open_editor():
        """Koreksi: focus the existing editor; the reviewer edits and saves."""
        status.set("needs_check")
        controls["category_corrected"].focus_set()

    def reject_current():
        """Tolak: save a rejection WITH a mandatory reason, then move on."""
        row = rows[current[0]]
        reason = simpledialog.askstring(
            "Tolak foto", "Alasan penolakan (wajib):", parent=window)
        if reason is None:
            return
        try:
            item = build_reject_decision(row, reason, read_control("reviewer"))
            persist_decision(state_path, decisions, item)
        except Exception as exc:
            messagebox.showerror("Tolak foto belum tersimpan", str(exc))
            return
        advance_after_triage(row["sku"])

    ttk.Button(actions, text="Setujui Visual", command=approve_current).pack(side="left")
    ttk.Button(actions, text="Koreksi", command=open_editor).pack(side="left", padx=6)
    ttk.Button(actions, text="Tolak", command=reject_current).pack(side="left")

    def confirm_leave():
        """Yes=save, No=discard local edits, Cancel=stay on current item."""
        if form_snapshot() == loaded_form[0]:
            return True
        answer = messagebox.askyesnocancel(
            "Ada perubahan belum disimpan",
            "Simpan perubahan sebelum berpindah atau menutup foto? "
            "Ya = simpan; Tidak = batalkan perubahan; Batal = tetap di foto ini.",
        )
        if answer is None:
            return False
        if answer:
            save()
        return True

    def navigate(delta):
        target = max(0, min(len(rows) - 1, current[0] + delta))
        if target == current[0]:
            return
        try:
            if confirm_leave():
                display(target)
        except Exception as exc:
            messagebox.showerror("Gagal menyimpan", str(exc))

    def next_priority():
        ordered = review_priority_order(rows, decisions, ai_drafts)
        choices = [idx for idx in ordered if idx != current[0]]
        if not choices:
            messagebox.showinfo("Antrean review", "Tidak ada kandidat lain yang menunggu triase.")
            return
        try:
            if confirm_leave():
                display(choices[0])
        except Exception as exc:
            messagebox.showerror("Gagal menyimpan", str(exc))

    def search():
        query = find_input.get().strip().lower()
        for i, row in enumerate(rows):
            if query in (row["sku"] + " " + row.get("category", "") +
                         " " + row.get("title_metadata_not_visual_fact", "")).lower():
                try:
                    if confirm_leave():
                        display(i)
                except Exception as exc:
                    messagebox.showerror("Gagal menyimpan", str(exc))
                return
        messagebox.showinfo("Tidak ditemukan", "Tidak ada SKU/kategori yang cocok")

    def insert_ai_draft():
        row = rows[current[0]]
        draft = ai_drafts.get(row["sku"])
        if draft is None:
            messagebox.showinfo("Belum ada draft", "Belum tersedia draft AI untuk SKU ini.")
            return
        if row.get("proposed_split") != "train":
            messagebox.showerror("Holdout dilindungi", "AI draft hanya diizinkan untuk calon train.")
            return
        if not messagebox.askyesno(
            "Masukkan draft AI?",
            "Isi form dengan saran berbasis foto yang BELUM diverifikasi manusia? "
            "Tulisan di form yang belum disimpan akan tertimpa. "
            "Ini TIDAK memberikan izin training atau cloud GPU."
        ):
            return
        for field, value in draft_field_values(draft).items():
            fill_control(field, value)
        status.set("needs_check")
        messagebox.showinfo("Draft dimuat", "Periksa fakta satu per satu. "
                            "Tombol Simpan masih wajib; status training tetap belum disetujui.")

    footer = ttk.Frame(root)
    footer.pack(fill="x", pady=9)
    ttk.Button(footer, text="◀ Sebelumnya", command=lambda: navigate(-1)).pack(side="left")
    ttk.Button(footer, text="Simpan", command=save_current).pack(side="left", padx=8)
    ttk.Button(footer, text="Berikutnya ▶", command=lambda: navigate(1)).pack(side="left")
    ttk.Button(footer, text="Cari", command=search).pack(side="right")
    ttk.Button(footer, text="Review prioritas",
               command=next_priority).pack(side="right", padx=8)
    ttk.Button(footer, text="Muat draft AI (train saja)",
               command=insert_ai_draft).pack(side="right", padx=8)
    find_input.bind("<Return>", lambda _: search())
    def closing():
        try:
            if confirm_leave():
                window.destroy()
        except Exception as exc:
            messagebox.showerror("Gagal menyimpan", str(exc))
    window.protocol("WM_DELETE_WINDOW", closing)
    order = review_priority_order(rows, decisions, ai_drafts)
    display(order[0] if order else 0)
    window.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--state", type=Path, help="local writable review state .json")
    parser.add_argument("--export", type=Path, help="read state and export JSONL (no image assets)")
    parser.add_argument("--audit", action="store_true", help="headless input/hash check, no GUI")
    parser.add_argument("--drafts", type=Path, help="unapproved visual drafts for TRAIN only")
    parser.add_argument("--readiness-report", type=Path,
                        help="write local JSON report on review status, never authorize training")
    args = parser.parse_args(argv)
    rows = load_rows(args.data)
    state = args.state or args.data.parent / "bico-manual-visual-review-state.json"
    ai_drafts = load_ai_drafts(args.drafts, rows) if args.drafts else {}
    if args.audit:
        for row in rows:
            source_image(row)
        print(json.dumps({"source_images_valid": len(rows),
                          "ai_drafts_checked": len(ai_drafts), "training_approved": 0,
                          "mode": "offline_read_only_audit"}))
        return 0
    if args.readiness_report:
        decisions = read_state(state, rows)
        report = review_readiness_report(rows, decisions, ai_drafts, verify_images=True)
        write_readiness_report(args.readiness_report, report)
        print(json.dumps({
            "source_images_verified": report["source_original_sha256_verified"],
            "review_status_counts": report["review_status_counts"],
            "assistant_drafts": report["assistant_draft_total"],
            "training_approved": report["training_approved"],
            "status": report["status"],
            "report": str(args.readiness_report),
        }, ensure_ascii=False))
        return 0
    if args.export:
        decisions = read_state(state, rows)
        export_review(args.export, decisions)
        print(json.dumps({"exported_decisions": len(decisions),
                          "training_approved": 0, "file": str(args.export)}))
        return 0
    review_gui(rows, state, ai_drafts)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print("REVIEW_STOPPED: " + str(exc), file=sys.stderr)
        sys.exit(2)
