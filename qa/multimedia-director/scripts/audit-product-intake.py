#!/usr/bin/env python3
"""Fail-closed offline audit for quarantined, sourced BICO product photos.

Never downloads assets, approves training licenses, loads model weights,
calls APIs or uploads user media. Public CI tests use SYNTHETIC fixtures only.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "botconnector.product-image-intake.v1"
HEX_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
SAFE_IMAGE = re.compile(r"^images/[A-Za-z0-9._-]+\.(?:jpe?g|png|webp)$", re.IGNORECASE)


def no(code, detail):
    raise ValueError(code + ": " + str(detail))


def load_jsonl(path):
    if not path.is_file():
        no("missing_manifest", path.name)
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            no("invalid_jsonl", str(line_no))
        if not isinstance(row, dict):
            no("invalid_record", str(line_no))
        rows.append(row)
    if not rows:
        no("empty_manifest", path.name)
    return rows


def audit(root, expected_count=None):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        no("invalid_root", root)
    manifest = load_jsonl(root / "intake-manifest.jsonl")
    draft = load_jsonl(root / "annotation-drafts-NOT-FOR-TRAINING.jsonl")
    source_csv = root / "sources-attribution.csv"
    if not source_csv.is_file():
        no("missing_source_attribution", source_csv.name)
    with source_csv.open(encoding="utf-8-sig", newline="") as handle:
        sources = list(csv.DictReader(handle))
    if expected_count is not None and len(manifest) != expected_count:
        no("wrong_count", str(len(manifest)))
    ids, sha_seen, path_seen = set(), set(), set()
    safe = []
    image_dir = (root / "images").resolve(strict=True)
    if not image_dir.is_dir() or not image_dir.is_relative_to(root):
        no("invalid_images_root", "images")
    for item in manifest:
        if item.get("schema") != SCHEMA:
            no("schema_mismatch", item.get("sample_id"))
        sid = item.get("sample_id")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{4,128}", sid):
            no("invalid_sample_id", sid)
        if sid in ids:
            no("duplicate_sample_id", sid)
        ids.add(sid)
        name = item.get("image_path")
        if not isinstance(name, str) or not SAFE_IMAGE.fullmatch(name):
            no("unsafe_image_name", sid)
        image = (root / name).resolve(strict=True)
        if not image.is_file() or not image.is_relative_to(image_dir):
            no("image_path_escape", sid)
        size = image.stat().st_size
        if size < 1000 or size > 25 * 1024 * 1024 or size != item.get("image_bytes"):
            no("image_size_mismatch", sid)
        width, height = item.get("image_width"), item.get("image_height")
        if not isinstance(width, int) or not isinstance(height, int) or min(width, height) <= 0:
            no("invalid_dimensions", sid)
        expected_sha = item.get("asset_sha256")
        if not isinstance(expected_sha, str) or not HEX_SHA256.fullmatch(expected_sha):
            no("invalid_sha256", sid)
        actual = hashlib.sha256(image.read_bytes()).hexdigest()
        if actual != expected_sha.lower():
            no("sha256_mismatch", sid)
        if actual in sha_seen or name in path_seen:
            no("duplicate_image", sid)
        sha_seen.add(actual)
        path_seen.add(name)
        first_bytes = image.open("rb").read(12)
        png = first_bytes.startswith(bytes.fromhex("89504e470d0a1a0a"))
        jpg = first_bytes.startswith(bytes.fromhex("ffd8ff"))
        webp = first_bytes[:4] == b"RIFF" and first_bytes[8:12] == b"WEBP"
        if not (png or jpg or webp):
            no("bad_image_signature", sid)
        if item.get("split") != "unassigned" or item.get("review_status") != "pending":
            no("unreviewed_intake_must_remain_unassigned", sid)
        if item.get("license_status") != "unverified_for_ai_training":
            no("quarantine_license_status_modified", sid)
        for key in ("commercial_training_allowed", "third_party_compute_allowed", "training_approved"):
            if item.get(key) is not False:
                no("unauthorized_training_flag", sid + ":" + key)
        if not isinstance(item.get("source_page"), str) or not item["source_page"].startswith("https://"):
            no("missing_provenance", sid)
        if not isinstance(item.get("license_page"), str) or not item["license_page"].startswith("https://"):
            no("missing_license_page", sid)
        if not isinstance(item.get("photographer"), str) or not item["photographer"].strip():
            no("missing_attribution", sid)
        if not isinstance(item.get("preliminary_visual_facts"), list) or not item["preliminary_visual_facts"]:
            no("missing_visual_facts", sid)
        safe.append({
            "sample_id": sid,
            "sha256": actual,
            "width": width,
            "height": height,
            "source_page": item["source_page"],
            "category": item.get("category"),
        })
    ids_from_drafts = set()
    for item in draft:
        sid = item.get("sample_id")
        if sid in ids_from_drafts or item.get("status") != "assistant_draft_unreviewed_do_not_train":
            no("draft_not_quarantined", sid)
        if item.get("target", {}).get("schema") != "botconnector.multimedia-director.v1":
            no("draft_target_schema_mismatch", sid)
        ids_from_drafts.add(sid)
    if ids_from_drafts != ids:
        no("draft_manifest_mismatch", "draft sample IDs")
    ids_from_sources = set()
    for item in sources:
        sid = item.get("sample_id")
        if sid in ids_from_sources:
            no("duplicate_attribution", sid)
        ids_from_sources.add(sid)
        row = next((r for r in manifest if r["sample_id"] == sid), None)
        if not row or item.get("sha256", "").lower() != row["asset_sha256"].lower():
            no("source_checksum_mismatch", sid)
        if item.get("photographer") != row.get("photographer"):
            no("source_photographer_mismatch", sid)
        if item.get("rights") != "PENDING - NOT APPROVED":
            no("source_rights_not_quarantined", sid)
    if ids_from_sources != ids:
        no("missing_attribution_record", "IDs")
    actual_names = {
        "images/" + p.name for p in image_dir.iterdir()
        if p.is_file()
    }
    if actual_names != path_seen:
        no("unmanifested_images", "listed=" + str(len(path_seen)) + " actual=" + str(len(actual_names)))
    return {
        "schema": "botconnector.product-image-intake-audit.v1",
        "status": "QUARANTINED_QA_ONLY",
        "image_count": len(safe),
        "distinct_product_groups": len({r["group_id"] for r in manifest}),
        "licenses_verified_for_ai_training": 0,
        "training_approved": 0,
        "network_requests": 0,
        "notes": "Checksums, provenance fields and quarantine flags checked; no legal or semantic approval.",
        "images": safe,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline QA-only product image manifest audit")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--expected-count", type=int)
    args = parser.parse_args(argv)
    try:
        report = audit(args.root, expected_count=args.expected_count)
    except (OSError, ValueError) as exc:
        parser.exit(status=2, message="PRODUCT_INTAKE_AUDIT_STOP: " + str(exc) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
