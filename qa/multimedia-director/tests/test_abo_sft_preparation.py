"""Dependency-free offline tests for ABO review queues and SmolVLM2 SFT staging."""
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
def imported(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

abo = imported("bico_abo", "scripts/select-abo-review.py")
sft = imported("bico_sft", "scripts/prepare-smolvlm2-sft.py")


def real_png(seed):
    """Fully decodable 1x1 RGB PNG generated offline; no customer media."""
    def chunk(tag, content):
        return (struct.pack(">I", len(content)) + tag + content +
                struct.pack(">I", zlib.crc32(tag + content) & 0xffffffff))
    rgb = bytes((seed % 256, (seed // 256) % 256, 70))
    raw = b"\x00" + rgb
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def example_target():
    return {
        "schema": "botconnector.multimedia-director.v1",
        "task": "product_photo",
        "visual": {
            "observed_facts": ["a visible product"],
            "unknowns": ["small label not legible"],
        },
        "preservation_rules": ["keep shape"],
        "concepts": [
            {"title": "Premium", "scene": "Studio", "mood": "Soft", "tagline": "Premium"},
            {"title": "Lifestyle", "scene": "Cafe", "mood": "Warm", "tagline": "Daily"},
            {"title": "Bold", "scene": "Gallery", "mood": "High contrast", "tagline": "Bold"},
        ],
    }


class ABOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.listings = [
            {"item_id": "item_" + str(i), "main_image_id": "img_" + str(i),
             "item_name": "Colorful product " + str(i), "color": "Blue"} for i in range(10)
        ]
        self.path = self.root / "abo.jsonl"
        self.path.write_text("\n".join(json.dumps(v) for v in self.listings), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_deterministic_sampling_and_unapproved_status(self):
        rows = list(abo.read_listings(self.path))
        sample1 = abo.choose(rows, 4, "same-seed")
        sample2 = abo.choose(list(reversed(rows)), 4, "same-seed")
        self.assertEqual(sample1, sample2)
        self.assertEqual(len(sample1), 4)
        self.assertTrue(all(x["train_ready"] is False and x["review_status"] == "pending" for x in sample1))
        self.assertTrue(all(x["commercial_training_allowed"] is False for x in sample1))

    def test_fails_on_missing_images_and_deduplicates_id(self):
        records = [dict(self.listings[0]), dict(self.listings[0]), {"item_id": "empty"}]
        self.assertEqual(len(abo.choose(records, 4)), 1)

    def test_parses_json_array_and_wrapper(self):
        for payload in (self.listings, {"listings": self.listings}):
            path = self.root / "wrapper.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(len(list(abo.read_listings(path))), 10)

    def test_reads_tar_members_without_extracting(self):
        archive = self.root / "listings.tar"
        blob = self.path.read_bytes()
        with tarfile.open(archive, "w") as tar:
            header = tarfile.TarInfo("metadata/listings.jsonl")
            header.size = len(blob)
            tar.addfile(header, io.BytesIO(blob))
            # ignored non-metadata and malicious paths are not extracted
            other = b"not important"
            header2 = tarfile.TarInfo("../escape.txt")
            header2.size = len(other)
            tar.addfile(header2, io.BytesIO(other))
        rows = list(abo.read_listings(archive))
        self.assertEqual(len(rows), 10)
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_reads_gzipped_jsonl(self):
        path = self.root / "meta.jsonl.gz"
        path.write_bytes(gzip.compress(self.path.read_bytes()))
        self.assertEqual(len(list(abo.read_listings(path))), 10)

    def test_missing_or_corrupt_json_fails_closed(self):
        path = self.root / "bad.jsonl"
        path.write_text('{"item_id":"ok"}\nthis is not json\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            list(abo.read_listings(path))

    def test_limit_and_cli_no_overwrite(self):
        with self.assertRaises(ValueError):
            abo.choose(self.listings, 1001)
        output = self.root / "queue.jsonl"
        argv = [sys.executable, str(ROOT / "scripts/select-abo-review.py"),
                "--metadata", str(self.path), "--out", str(output), "--max-items", "4"]
        run = subprocess.run(argv, text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        rows = [json.loads(x) for x in output.read_text().splitlines()]
        self.assertEqual(len(rows), 4)
        self.assertEqual(subprocess.run(argv, capture_output=True).returncode, 2)


class SFTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.imgroot = self.root / "images"
        self.staged = self.root / "stage"
        self.imgroot.mkdir()
        self.staged.mkdir()
        self.rows = {}
        k = 0
        for split, num in (("train", 50), ("val", 10), ("test", 200)):
            records = []
            for _ in range(num):
                name = "item_" + str(k) + ".png"
                data = real_png(k)
                (self.imgroot / name).write_bytes(data)
                records.append({
                    "schema": sft.SCHEMA, "id": "record-" + str(k), "split": split,
                    "task": "product_photo", "image_path": name,
                    "image_sha256": hashlib.sha256(data).hexdigest(),
                    "group_id": "sku-" + str(k), "source_id": "abo",
                    "license": "CC-BY-4.0", "attribution": "synthetic test only",
                    "brief": "Buat foto produk tanpa mengubah bentuk asli",
                    "target": example_target(),
                })
                k += 1
            self.rows[split] = records
        self.write_staging()

    def tearDown(self):
        self.temp.cleanup()

    def write_staging(self, *, mode="gated_dataset"):
        counts = {split: len(rows) for split, rows in self.rows.items()}
        (self.staged / "summary.json").write_text(
            json.dumps({"schema": sft.SCHEMA, "mode": mode, "gate": sft.GATE, "counts": counts}), encoding="utf-8")
        for split, rows in self.rows.items():
            (self.staged / (split + ".jsonl")).write_text(
                "\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")

    def test_count_and_image_hash_validation(self):
        rows = sft.records(self.staged, self.imgroot)
        self.assertEqual({k: len(v) for k, v in rows.items()}, {"train": 50, "val": 10, "test": 200})
        self.assertEqual(rows["train"][0]["messages"][0]["content"][0], {"type": "image"})

    def test_instruction_contains_brief_and_grounding(self):
        prompt = sft.build_messages(self.rows["train"][0])
        text = prompt[0]["content"][1]["text"]
        self.assertIn("BICO Multimedia Director", text)
        self.assertIn("Buat foto produk", text)
        assistant = json.loads(prompt[1]["content"][0]["text"])
        self.assertEqual(assistant["schema"], sft.TARGET_SCHEMA)

    def test_rejects_smoke_only(self):
        self.write_staging(mode="smoke_only")
        with self.assertRaisesRegex(ValueError, "rights-gated"):
            sft.records(self.staged, self.imgroot)

    def test_rejects_missing_source_review_gate(self):
        summary_path = self.staged / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary.pop("gate")
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "rights-gated dataset"):
            sft.records(self.staged, self.imgroot)

    def test_rejects_duplicate_sample_id_across_train_test(self):
        self.rows["test"][0]["id"] = self.rows["train"][0]["id"]
        self.write_staging()
        with self.assertRaisesRegex(ValueError, "duplicate or missing staged sample ID"):
            sft.records(self.staged, self.imgroot)

    def test_rejects_incorrect_summary_count(self):
        self.rows["train"].pop()
        self.write_staging()
        with self.assertRaisesRegex(ValueError, "insufficient"):
            sft.records(self.staged, self.imgroot)

    def test_rejects_group_leakage(self):
        self.rows["val"][0]["group_id"] = self.rows["train"][0]["group_id"]
        self.write_staging()
        with self.assertRaisesRegex(ValueError, "group leakage"):
            sft.records(self.staged, self.imgroot)

    def test_rejects_identical_image_in_different_splits(self):
        self.rows["val"][0]["image_path"] = self.rows["train"][0]["image_path"]
        self.rows["val"][0]["image_sha256"] = self.rows["train"][0]["image_sha256"]
        self.write_staging()
        with self.assertRaisesRegex(ValueError, "checksum leakage"):
            sft.records(self.staged, self.imgroot)

    def test_rejects_tampered_image(self):
        path = self.imgroot / self.rows["train"][0]["image_path"]
        path.write_bytes(path.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            sft.records(self.staged, self.imgroot)

    def test_rejects_path_traversal(self):
        self.rows["train"][0]["image_path"] = "../private.png"
        self.write_staging()
        with self.assertRaisesRegex(ValueError, "unsafe image path"):
            sft.records(self.staged, self.imgroot)

    def test_dry_run_then_write_without_test_export(self):
        out = self.root / "export"
        cmd = [sys.executable, str(ROOT / "scripts/prepare-smolvlm2-sft.py"),
               "--staged", str(self.staged), "--assets-root", str(self.imgroot), "--out-dir", str(out)]
        dry = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertFalse(out.exists())
        actual = subprocess.run(cmd + ["--write"], capture_output=True, text=True)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertTrue((out / "train.jsonl").is_file())
        self.assertTrue((out / "val.jsonl").is_file())
        self.assertFalse((out / "test.jsonl").exists())
        packet = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(packet["source_gate"], sft.GATE)
        self.assertEqual(packet["sealed_holdout_stage_sha256"],
                         hashlib.sha256((self.staged / "test.jsonl").read_bytes()).hexdigest())
        for split in ("train", "val"):
            self.assertEqual(packet["train_val_file_sha256"][split],
                             hashlib.sha256((out / (split + ".jsonl")).read_bytes()).hexdigest())
        self.assertEqual(subprocess.run(cmd + ["--write"], capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
