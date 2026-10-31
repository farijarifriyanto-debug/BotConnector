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
        if raw.get("training_approved") is not False or raw.get("third_party_gpu_allowed") is not False:
            raise ValueError("review must never authorize model training or GPU transfer")
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


def export_review(path, decisions):
    if path.exists():
        raise ValueError("refusing to overwrite existing export")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for item in decisions.values():
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def review_gui(rows, state_path):
    import tkinter as tk
    from tkinter import messagebox, ttk
    from PIL import Image, ImageOps, ImageTk

    decisions = read_state(state_path, rows)
    window = tk.Tk()
    window.title("BICO — Review Foto Produk Internet (OFFLINE)")
    window.geometry("1180x850")
    window.minsize(880, 680)
    current = [0]
    photo_ref = [None]
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
        done = sum(d.get("status") != "pending" for d in decisions.values())
        counter.configure(text=f"{current[0]+1}/{len(rows)} • sudah ditriase: {done} • "
                          f"siap training: 0")
        caption.configure(text="SKU: " + row["sku"] +
                          "\nKategori awal (metadata): " + row.get("category", "") +
                          "\nUsulan split: " + row.get("proposed_split", "") +
                          "\nJudul metadata BUKAN fakta visual:\n" +
                          row.get("title_metadata_not_visual_fact", "")[:180] +
                          "\nSumber: " + row.get("source_url", ""))

    def save():
        row = rows[current[0]]
        item = {"sku": row["sku"], "image_sha256": row["image_sha256"],
                "source_url": row["source_url"],
                "proposed_split": row.get("proposed_split", ""),
                "status": status.get(), "training_approved": False,
                "third_party_gpu_allowed": False, "annotation_finalized": False,
                "license_approval": "pending", "privacy_approval": "pending"}
        for field in FIELDS:
            item[field] = read_control(field)
        decisions[row["sku"]] = item
        write_state(state_path, decisions)
        display(current[0])

    def navigate(delta):
        try:
            save()
            display(current[0] + delta)
        except Exception as exc:
            messagebox.showerror("Gagal menyimpan", str(exc))

    def search():
        query = find_input.get().strip().lower()
        for i, row in enumerate(rows):
            if query in (row["sku"] + " " + row.get("category", "") +
                         " " + row.get("title_metadata_not_visual_fact", "")).lower():
                display(i)
                return
        messagebox.showinfo("Tidak ditemukan", "Tidak ada SKU/kategori yang cocok")

    footer = ttk.Frame(root)
    footer.pack(fill="x", pady=9)
    ttk.Button(footer, text="◀ Sebelumnya", command=lambda: navigate(-1)).pack(side="left")
    ttk.Button(footer, text="Simpan", command=lambda: navigate(0)).pack(side="left", padx=8)
    ttk.Button(footer, text="Berikutnya ▶", command=lambda: navigate(1)).pack(side="left")
    ttk.Button(footer, text="Cari", command=search).pack(side="right")
    find_input.bind("<Return>", lambda _: search())
    def closing():
        if messagebox.askyesno("Tutup", "Simpan item saat ini dan tutup?"):
            try:
                save()
            except Exception as exc:
                messagebox.showerror("Penyimpanan gagal", str(exc))
                return
        window.destroy()
    window.protocol("WM_DELETE_WINDOW", closing)
    display(0)
    window.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--state", type=Path, help="local writable review state .json")
    parser.add_argument("--export", type=Path, help="read state and export JSONL (no image assets)")
    parser.add_argument("--audit", action="store_true", help="headless input/hash check, no GUI")
    args = parser.parse_args(argv)
    rows = load_rows(args.data)
    state = args.state or args.data.parent / "bico-manual-visual-review-state.json"
    if args.audit:
        for row in rows:
            source_image(row)
        print(json.dumps({"source_images_valid": len(rows), "training_approved": 0,
                          "mode": "offline_read_only_audit"}))
        return 0
    if args.export:
        decisions = read_state(state, rows)
        export_review(args.export, decisions)
        print(json.dumps({"exported_decisions": len(decisions),
                          "training_approved": 0, "file": str(args.export)}))
        return 0
    review_gui(rows, state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print("REVIEW_STOPPED: " + str(exc), file=sys.stderr)
        sys.exit(2)
