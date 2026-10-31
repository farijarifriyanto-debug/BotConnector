"""Offline tests for product review GUI's noninteractive safety contract.

No tkinter windows, real ABO photos, network, secrets or GPU are used in CI.
"""
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
SCRIPT = ROOT / "scripts/review-product-images.py"
spec = importlib.util.spec_from_file_location("bico_product_review", SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def make_png(index):
    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff))
    data = b"\x00" + bytes((index, 128, 180))
    return (bytes.fromhex("89504e470d0a1a0a")
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(data))
            + chunk(b"IEND", b""))


class HumanReviewOfflineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bico-review-test-")
        self.root = Path(self.temp.name)
        self.rows = []
        for idx in range(2):
            path = self.root / ("synthetic-" + str(idx) + ".png")
            blob = make_png(idx)
            path.write_bytes(blob)
            self.rows.append({
                "sku": "SYNTH" + str(idx), "image_sha256": hashlib.sha256(blob).hexdigest(),
                "local_image_path": str(path),
                "source_url": "https://example.org/synthetic/" + str(idx),
                "category": "synthetic", "proposed_split": "train" if idx == 0 else "test",
                "title_metadata_not_visual_fact": "Synthetic fixture, not actual product",
                "commercial_training_approved": False, "training_ready": False,
            })
        self.dataset = self.root / "synthetic-review.jsonl"
        self.save()
        self.state = self.root / "manual-review.json"

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.dataset.write_text(
            "\n".join(json.dumps(r) for r in self.rows) + "\n", encoding="utf-8"
        )

    def decision(self):
        r = self.rows[0]
        return {
            "sku": r["sku"], "image_sha256": r["image_sha256"],
            "source_url": r["source_url"], "status": "candidate",
            "category_corrected": "synthetic", "observed_facts": "synthetic RGB pixel",
            "preservation_rules": "Do not alter image",
            "training_approved": False, "third_party_gpu_allowed": False,
            "annotation_finalized": False,
        }

    def test_synthetic_dataset_loads_without_gui(self):
        rows = review.load_rows(self.dataset)
        self.assertEqual(len(rows), 2)
        self.assertEqual(review.source_image(rows[0]), Path(self.rows[0]["local_image_path"]))

    def test_headless_audit_requires_no_torch_or_tkinter(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--data", str(self.dataset), "--audit"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data["source_images_valid"], 2)
        self.assertEqual(data["training_approved"], 0)

    def test_state_atomic_round_trip(self):
        d = self.decision()
        review.write_state(self.state, {d["sku"]: d})
        result = review.read_state(self.state, self.rows)
        self.assertEqual(result[d["sku"]]["status"], "candidate")
        self.assertFalse(result[d["sku"]]["training_approved"])

    def test_reject_training_approval_in_saved_review(self):
        d = self.decision()
        d["training_approved"] = True
        review.write_state(self.state, {d["sku"]: d})
        with self.assertRaisesRegex(ValueError, "never authorize"):
            review.read_state(self.state, self.rows)

    def test_reject_gpu_transfer_in_saved_review(self):
        d = self.decision()
        d["third_party_gpu_allowed"] = True
        review.write_state(self.state, {d["sku"]: d})
        with self.assertRaisesRegex(ValueError, "never authorize"):
            review.read_state(self.state, self.rows)

    def test_reject_changed_source_hash(self):
        d = self.decision()
        d["image_sha256"] = "a" * 64
        review.write_state(self.state, {d["sku"]: d})
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            review.read_state(self.state, self.rows)

    def test_reject_unknown_source_sku(self):
        d = self.decision()
        d["sku"] = "UNKNOWN"
        review.write_state(self.state, {"UNKNOWN": d})
        with self.assertRaisesRegex(ValueError, "missing or SHA256 mismatch"):
            review.read_state(self.state, self.rows)

    def test_reject_tampered_photo(self):
        photo = Path(self.rows[0]["local_image_path"])
        photo.write_bytes(photo.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            review.source_image(self.rows[0])

    def test_reject_dataset_approved_for_training(self):
        self.rows[0]["training_ready"] = True
        self.save()
        with self.assertRaisesRegex(ValueError, "prematurely approved"):
            review.load_rows(self.dataset)

    def test_reject_duplicate_sku(self):
        self.rows[1]["sku"] = self.rows[0]["sku"]
        self.save()
        with self.assertRaisesRegex(ValueError, "invalid or prematurely approved"):
            review.load_rows(self.dataset)

    def test_exports_decisions_but_not_images_and_no_overwrite(self):
        d = self.decision()
        review.write_state(self.state, {d["sku"]: d})
        target = self.root / "export.jsonl"
        p = subprocess.run([sys.executable, str(SCRIPT), "--data", str(self.dataset),
                            "--state", str(self.state), "--export", str(target)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        payload = json.loads(target.read_text().strip())
        self.assertFalse(payload["training_approved"])
        self.assertNotIn("image_bytes", payload)
        p2 = subprocess.run([sys.executable, str(SCRIPT), "--data", str(self.dataset),
                             "--state", str(self.state), "--export", str(target)],
                            capture_output=True, text=True)
        self.assertEqual(p2.returncode, 2)
        self.assertIn("refusing to overwrite", p2.stderr)

    def test_reject_unsafe_review_status(self):
        d = self.decision()
        d["status"] = "approved_for_training"
        review.write_state(self.state, {d["sku"]: d})
        with self.assertRaisesRegex(ValueError, "invalid review status"):
            review.read_state(self.state, self.rows)


if __name__ == "__main__":
    unittest.main()
