"""PUBLIC CI: 2B real-image baseline guard tests, synthetic media only.

No model checkpoint weights, actual customer/product pictures, external
downloads, CUDA/GPU, paid inference or training.
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/probe-multimedia-director-vlm.py"
spec = importlib.util.spec_from_file_location("bico_2b_baseline", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def tiny_png(number):
    def chunk(name, payload):
        return (struct.pack(">I", len(payload)) + name + payload
                + struct.pack(">I", zlib.crc32(name + payload) & 0xffffffff))
    data = b"\0" + bytes((number % 256, (number // 256) % 256, 97))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(data)) + chunk(b"IEND", b""))


class Pixels:
    def __init__(self, count):
        self.count = count
    def numel(self):
        return self.count


class BaselineSafetyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bico-2b-contract-")
        self.root = Path(self.temp.name)
        self.model = self.root / "model"
        self.model.mkdir()
        self.stage = self.root / "stage"
        self.stage.mkdir()
        self.assets = self.root / "assets"
        self.assets.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def checkpoint(self, kind="idefics3", weight="model-00001.safetensors"):
        (self.model / "config.json").write_text(
            json.dumps({"model_type": kind}), encoding="utf-8"
        )
        (self.model / weight).write_bytes(b"dummy synthetic bytes; not a real checkpoint")
        return self.model

    def test_missing_explicit_checkpoint_is_denied(self):
        with self.assertRaisesRegex(ValueError, "model-dir"):
            probe.verify_local_checkpoint(None, probe.PRIMARY)

    def test_expected_architecture_and_safetensors_presence(self):
        model = self.checkpoint()
        self.assertEqual(probe.verify_local_checkpoint(model, probe.PRIMARY), model)

    def test_reject_mismatched_8b_architecture(self):
        model = self.checkpoint(kind="qwen3_vl")
        with self.assertRaisesRegex(ValueError, "incompatible"):
            probe.verify_local_checkpoint(model, probe.PRIMARY)

    def test_reject_pickle_weight_even_with_safetensors(self):
        model = self.checkpoint()
        (model / "pytorch_model.bin").write_bytes(b"pickle")
        with self.assertRaisesRegex(ValueError, "pickle-format"):
            probe.verify_local_checkpoint(model, probe.PRIMARY)

    def test_no_weights_is_denied(self):
        model = self.model
        (model / "config.json").write_text('{"model_type":"idefics3"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "safetensors"):
            probe.verify_local_checkpoint(model, probe.PRIMARY)

    def test_wrong_or_missing_config_is_denied(self):
        (self.model / "file.safetensors").write_bytes(b"fake")
        with self.assertRaisesRegex(ValueError, "config.json"):
            probe.verify_local_checkpoint(self.model, probe.PRIMARY)
        (self.model / "config.json").write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            probe.verify_local_checkpoint(self.model, probe.PRIMARY)

    def test_valid_pixel_tensors_and_list(self):
        self.assertTrue(probe.require_real_pixel_values(
            {"input_ids": [[1, 2]], "pixel_values": Pixels(512)}
        ))
        self.assertTrue(probe.require_real_pixel_values(
            {"input_ids": [[1, 2]], "pixel_values": [Pixels(12)]}
        ))

    def test_reject_text_only_or_empty_pixel_tensors(self):
        bad = [
            {}, {"pixel_values": Pixels(1)},
            {"input_ids": [[1]]},
            {"input_ids": [[1]], "pixel_values": None},
            {"input_ids": [[1]], "pixel_values": Pixels(0)},
            {"input_ids": [[1]], "pixel_values": []},
            {"input_ids": [[1]], "pixel_values": "not-a-tensor"},
        ]
        for row in bad:
            with self.subTest(row=str(row)):
                with self.assertRaises(ValueError):
                    probe.require_real_pixel_values(row)

    def make_complete_staging(self):
        rows = {}
        k = 0
        for split, n in (("train", 50), ("val", 10), ("test", 200)):
            rows[split] = []
            for _ in range(n):
                blob = tiny_png(k)
                name = f"image-{k:03d}.png"
                (self.assets / name).write_bytes(blob)
                rows[split].append({
                    "schema": probe.STAGING_SCHEMA,
                    "split": split, "id": f"syn-{k:03d}",
                    "task": "product_photo",
                    "image_path": name,
                    "image_sha256": hashlib.sha256(blob).hexdigest(),
                    "group_id": f"sku-{k:03d}",
                    "source_id": "synthetic-license-test",
                    "license": "CC-BY-4.0",
                    "attribution": "Synthetic test — no real products",
                    "brief": "Synthetic test image, not for commercial training",
                    "target": {
                        "schema": "botconnector.multimedia-director.v1",
                        "task": "product_photo",
                        "visual": {"observed_facts": ["synthetic"],
                                   "unknowns": ["no product"]},
                        "preservation_rules": ["No product"],
                        "concepts": [
                            {"title": str(i), "scene": "Scene " + str(i),
                             "mood": "neutral", "tagline": "fake"} for i in range(3)
                        ],
                    },
                })
                k += 1
        self.write_staging(rows)
        return rows

    def write_staging(self, rows, gate=None):
        for split in ("train", "val", "test"):
            content = "\n".join(json.dumps(r) for r in rows[split]) + "\n"
            (self.stage / (split + ".jsonl")).write_text(content, encoding="utf-8")
        summary = {
            "schema": probe.STAGING_SCHEMA,
            "mode": "gated_dataset",
            "counts": {split: len(r) for split, r in rows.items()},
            "gate": gate or "human_rights_review_assertions_required_but_not_independently_verified",
        }
        (self.stage / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary

    def test_full_stage_260_synthetic_pixels_hash_and_split_pass(self):
        rows = self.make_complete_staging()
        summary = json.loads((self.stage / "summary.json").read_text())
        actual = probe.verify_full_gated_staging(self.stage, self.assets, summary)
        self.assertEqual(actual, {"train": 50, "val": 10, "test": 200})
        self.assertEqual(len(rows["test"]), 200)

    def test_full_stage_blocks_cross_split_group_leakage(self):
        rows = self.make_complete_staging()
        rows["val"][0]["group_id"] = rows["train"][0]["group_id"]
        summary = self.write_staging(rows)
        with self.assertRaisesRegex(ValueError, "group leakage"):
            probe.verify_full_gated_staging(self.stage, self.assets, summary)

    def test_full_stage_blocks_cross_split_identical_image(self):
        rows = self.make_complete_staging()
        rows["test"][0]["image_sha256"] = rows["train"][0]["image_sha256"]
        rows["test"][0]["image_path"] = rows["train"][0]["image_path"]
        summary = self.write_staging(rows)
        with self.assertRaisesRegex(ValueError, "exact-image leakage"):
            probe.verify_full_gated_staging(self.stage, self.assets, summary)

    def test_full_stage_blocks_tampered_image(self):
        rows = self.make_complete_staging()
        photo = self.assets / rows["test"][0]["image_path"]
        photo.write_bytes(photo.read_bytes() + b"tampered")
        summary = self.write_staging(rows)
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            probe.verify_full_gated_staging(self.stage, self.assets, summary)

    def test_full_stage_blocks_misreported_counts(self):
        rows = self.make_complete_staging()
        rows["val"].pop()
        summary = self.write_staging(rows)
        with self.assertRaisesRegex(ValueError, "insufficient"):
            probe.verify_full_gated_staging(self.stage, self.assets, summary)

    def test_full_stage_blocks_missing_attribution(self):
        rows = self.make_complete_staging()
        rows["test"][0]["attribution"] = ""
        summary = self.write_staging(rows)
        with self.assertRaisesRegex(ValueError, "attribution"):
            probe.verify_full_gated_staging(self.stage, self.assets, summary)

    def test_full_stage_blocks_fake_gate_summary(self):
        rows = self.make_complete_staging()
        summary = self.write_staging(rows, gate="smoke_only")
        with self.assertRaisesRegex(ValueError, "rights-gate attestation"):
            probe.verify_full_gated_staging(self.stage, self.assets, summary)

    def test_cli_requires_explicit_model_dir_before_torch_import(self):
        self.make_complete_staging()
        out = self.root / "test-results.jsonl"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--staged", str(self.stage),
             "--assets-root", str(self.assets), "--split", "val",
             "--run", "--acknowledge-runtime-cost", "--out", str(out)],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("model-dir", result.stderr)
        self.assertFalse(out.exists())

    def test_cli_refuses_train_split_for_baseline(self):
        self.make_complete_staging()
        out = self.root / "train-predictions.jsonl"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--staged", str(self.stage),
             "--assets-root", str(self.assets), "--split", "train",
             "--run", "--acknowledge-runtime-cost", "--out", str(out)],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("never train", result.stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
