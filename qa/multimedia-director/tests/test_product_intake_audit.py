"""Synthetic-only CI tests for quarantined product photo intake.

No real Pexels/ABO/Studio customer media, internet, model weights or secrets.
"""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
AUDITOR = ROOT / "scripts/audit-product-intake.py"
spec = importlib.util.spec_from_file_location("intake_audit", AUDITOR)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fake_photo(index):
    # Real valid PNG encoding with deterministic synthetic RGB pixels.
    def chunk(name, payload):
        return (
            struct.pack(">I", len(payload))
            + name + payload
            + struct.pack(">I", zlib.crc32(name + payload) & 0xffffffff)
        )
    scanlines = []
    for y in range(32):
        row = bytearray(b"\0")
        for x in range(32):
            row.extend(hashlib.sha256((str(index) + "/" + str(x) + "/" + str(y)).encode()).digest()[:3])
        scanlines.append(bytes(row))
    return (
        bytes.fromhex("89504e470d0a1a0a")
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(scanlines)))
        + chunk(b"IEND", b"")
    )


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bico-product-audit-")
        self.root = Path(self.tmp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.records = []
        self.drafts = []
        self.sources = []
        for i in range(3):
            photo = fake_photo(i)
            file = "images/sample-" + str(i) + ".png"
            (self.root / file).write_bytes(photo)
            digest = hashlib.sha256(photo).hexdigest()
            row = {
                "schema": module.SCHEMA,
                "sample_id": "sample-" + str(i),
                "image_path": file,
                "source_kind": "synthetic-test-internal",
                "source_page": "https://example.org/synthetic/" + str(i),
                "photographer": "Synthetic fixture",
                "license_page": "https://example.org/synthetic-license",
                "license_status": "unverified_for_ai_training",
                "category": "synthetic-product",
                "group_id": "fake-sku-" + str(i),
                "asset_sha256": digest,
                "image_width": 32,
                "image_height": 32,
                "image_bytes": len(photo),
                "split": "unassigned",
                "review_status": "pending",
                "brand_and_trademark_review": "pending",
                "commercial_training_allowed": False,
                "third_party_compute_allowed": False,
                "training_approved": False,
                "preliminary_visual_facts": ["Synthetic pattern"],
                "preliminary_unknowns": ["No real product label"],
            }
            self.records.append(row)
            self.drafts.append({
                "sample_id": row["sample_id"],
                "status": "assistant_draft_unreviewed_do_not_train",
                "target": {"schema": "botconnector.multimedia-director.v1", "task": "product_photo"},
            })
            self.sources.append({
                "sample_id": row["sample_id"],
                "image": file,
                "photographer": row["photographer"],
                "source_page": row["source_page"],
                "rights": "PENDING - NOT APPROVED",
                "sha256": digest,
                "width": 32, "height": 32, "bytes": len(photo),
            })
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        (self.root / "intake-manifest.jsonl").write_text(
            "\n".join(json.dumps(r) for r in self.records) + "\n",
            encoding="utf-8"
        )
        (self.root / "annotation-drafts-NOT-FOR-TRAINING.jsonl").write_text(
            "\n".join(json.dumps(r) for r in self.drafts) + "\n",
            encoding="utf-8"
        )
        keys = list(self.sources[0].keys())
        with (self.root / "sources-attribution.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(self.sources)

    def deny(self, code):
        with self.assertRaisesRegex(ValueError, code):
            module.audit(self.root)

    def test_happy_path_exact_images_quarantined(self):
        result = module.audit(self.root, expected_count=3)
        self.assertEqual(result["image_count"], 3)
        self.assertEqual(result["training_approved"], 0)
        self.assertEqual(result["status"], "QUARANTINED_QA_ONLY")

    def test_refuse_approved_training_flag(self):
        self.records[0]["training_approved"] = True
        self.save()
        self.deny("unauthorized_training_flag")

    def test_refuse_community_gpu_without_rights(self):
        self.records[0]["third_party_compute_allowed"] = True
        self.save()
        self.deny("unauthorized_training_flag")

    def test_refuse_false_commercial_license(self):
        self.records[0]["commercial_training_allowed"] = True
        self.save()
        self.deny("unauthorized_training_flag")

    def test_refuse_license_state_changed(self):
        self.records[0]["license_status"] = "approved"
        self.save()
        self.deny("quarantine_license_status_modified")

    def test_refuse_train_split_in_intake(self):
        self.records[0]["split"] = "train"
        self.save()
        self.deny("unreviewed_intake_must_remain_unassigned")

    def test_refuse_modified_image_checksum(self):
        path = self.root / self.records[0]["image_path"]
        path.write_bytes(path.read_bytes() + b"tampered")
        self.deny("image_size_mismatch")

    def test_refuse_traversal_path(self):
        self.records[0]["image_path"] = "images/../private.png"
        self.save()
        self.deny("unsafe_image_name")

    def test_refuse_duplicate_photo(self):
        self.records[1]["image_path"] = self.records[0]["image_path"]
        self.records[1]["asset_sha256"] = self.records[0]["asset_sha256"]
        self.records[1]["image_bytes"] = self.records[0]["image_bytes"]
        self.sources[1]["sha256"] = self.records[0]["asset_sha256"]
        self.save()
        self.deny("duplicate_image")

    def test_refuse_unmanifested_image(self):
        (self.images / "extra.png").write_bytes(fake_photo(12))
        self.deny("unmanifested_images")

    def test_refuse_missing_photographer(self):
        self.records[0]["photographer"] = ""
        self.save()
        self.deny("missing_attribution")

    def test_refuse_missing_draft(self):
        self.drafts.pop()
        self.save()
        self.deny("draft_manifest_mismatch")

    def test_refuse_approved_draft(self):
        self.drafts[0]["status"] = "approved"
        self.save()
        self.deny("draft_not_quarantined")

    def test_refuse_source_checksum_change(self):
        self.sources[0]["sha256"] = "0" * 64
        self.save()
        self.deny("source_checksum_mismatch")

    def test_refuse_wrong_expected_count(self):
        with self.assertRaisesRegex(ValueError, "wrong_count"):
            module.audit(self.root, expected_count=50)

    def test_cli_read_only(self):
        p = subprocess.run(
            [sys.executable, str(AUDITOR), "--root", str(self.root), "--expected-count", "3"],
            capture_output=True, text=True
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["network_requests"], 0)


if __name__ == "__main__":
    unittest.main()
