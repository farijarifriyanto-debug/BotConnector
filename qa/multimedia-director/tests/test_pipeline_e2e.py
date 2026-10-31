"""Synthetic end-to-end: Node rights gate -> Python SFT packager -> 2B LoRA dry-run.

No external downloads, GPU, model weights, credentials, or customer media.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
NODE_GATE = ROOT / "scripts/prepare-multimedia-director-data.mjs"
SFT_PACKAGER = ROOT / "scripts/prepare-smolvlm2-sft.py"
LORA = ROOT / "scripts/train-smolvlm2-lora.py"


def tiny_rgb_png(index):
    """Synthetic 1x1 image; source is not a product photo."""
    def chunk(tag, content):
        return struct.pack(">I", len(content)) + tag + content + struct.pack(">I", zlib.crc32(tag + content) & 0xffffffff)
    color = bytes((index % 256, index // 256, 75))
    raw = b"\x00" + color
    return (
        b"\x89PNG\r\n\x1a\n" +
        chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) +
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    )


def target():
    return {
        "schema": "botconnector.multimedia-director.v1",
        "task": "product_photo",
        "visual": {"observed_facts": ["pixel warna sintetis"], "unknowns": ["label produk tidak ada"]},
        "preservation_rules": ["Jangan ubah gambar sumber"],
        "concepts": [
            {"title": "Premium", "scene": "Studio minimalis", "mood": "Lembut", "tagline": "Elegan"},
            {"title": "Lifestyle", "scene": "Meja kayu", "mood": "Hangat", "tagline": "Sehari-hari"},
            {"title": "Bold", "scene": "Galeri bentuk", "mood": "Kontras", "tagline": "Berani"},
        ],
    }


class PipelineE2ETest(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("Node.js required for cross-language dataset gate")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.manifest = self.root / "manifest.jsonl"
        self.registry = self.root / "registry.json"
        self.staged = self.root / "staged"
        self.sft = self.root / "sft"
        self.rows = []
        self.registry.write_text(json.dumps({"records": [
            {"id": "abo", "status": "candidate_allowed_with_attribution", "license": "CC-BY-4.0"}
        ]}), encoding="utf-8")
        for idx in range(260):
            split = "train" if idx < 50 else "val" if idx < 60 else "test"
            file = "synthetic-" + str(idx) + ".png"
            data = tiny_rgb_png(idx)
            (self.images / file).write_bytes(data)
            row = {
                "id": "synthetic-" + str(idx),
                "source_id": "abo",
                "license": "CC-BY-4.0",
                "attribution": "SYNTHETIC ONLY, not actual ABO licensing",
                "asset_path": file,
                "asset_sha256": hashlib.sha256(data).hexdigest(),
                "task": "product_photo",
                "split": split,
                "group_id": "fake-product-" + str(idx),
                "brief": "Jelaskan gambar uji sintetis, bukan produk nyata.",
                "rights": {
                    "commercial_training_allowed": True,
                    "third_party_compute_allowed": True,
                    "contains_customer_data": False,
                    "contains_pii": False,
                    "contains_identifiable_people": False,
                    "asset_rights_reviewed": True,
                    "evidence_url": "https://registry.opendata.aws/amazon-berkeley-objects/",
                },
                "review": {
                    "status": "approved",
                    "reviewer_id": "synthetic-unittest-not-a-human",
                    "reviewed_at": "2026-10-31",
                },
                "target": target(),
            }
            self.rows.append(row)
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        self.manifest.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in self.rows) + "\n", encoding="utf-8"
        )

    def gate(self):
        return subprocess.run([
            "node", str(NODE_GATE),
            "--manifest", str(self.manifest),
            "--registry", str(self.registry),
            "--assets-root", str(self.images),
            "--out", str(self.staged)
        ], capture_output=True, text=True)

    def test_full_pipeline_only_runs_offline_and_seals_test(self):
        gate = self.gate()
        self.assertEqual(gate.returncode, 0, gate.stderr)
        summary = json.loads((self.staged / "summary.json").read_text())
        self.assertEqual(summary["counts"], {"train": 50, "val": 10, "test": 200})
        self.assertEqual(summary["mode"], "gated_dataset")
        package = subprocess.run([
            sys.executable, str(SFT_PACKAGER),
            "--staged", str(self.staged),
            "--assets-root", str(self.images),
            "--out-dir", str(self.sft),
            "--write"
        ], capture_output=True, text=True)
        self.assertEqual(package.returncode, 0, package.stderr)
        self.assertTrue((self.sft / "train.jsonl").exists())
        self.assertTrue((self.sft / "val.jsonl").exists())
        self.assertFalse((self.sft / "test.jsonl").exists())
        preflight = subprocess.run([
            sys.executable, str(LORA),
            "--prepared", str(self.sft),
            "--assets-root", str(self.images)
        ], capture_output=True, text=True)
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        output = json.loads(preflight.stdout)
        self.assertFalse(output["gpu_started"])
        self.assertEqual(output["verified_train_val_samples"], 60)
        self.assertEqual(output["test_samples_loaded"], 0)

    def test_noncommercial_rights_do_not_reach_staging(self):
        self.rows[0]["rights"]["commercial_training_allowed"] = False
        self.save()
        gate = self.gate()
        self.assertEqual(gate.returncode, 2, gate.stderr)
        self.assertFalse(self.staged.exists())

    def test_product_group_leakage_stops_before_export(self):
        self.rows[-1]["group_id"] = self.rows[0]["group_id"]
        self.save()
        gate = self.gate()
        self.assertEqual(gate.returncode, 2, gate.stderr)
        self.assertFalse(self.staged.exists())


if __name__ == "__main__":
    unittest.main()
