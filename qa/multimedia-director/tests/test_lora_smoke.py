"""Offline-only tests for BICO 2.2B image-grounded LoRA smoke path.

No torch, transformers, PEFT, cloud VM, credentials or model downloads.
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TRAINER_PATH = ROOT / "scripts/train-smolvlm2-lora.py"
spec = importlib.util.spec_from_file_location("bico_lora_smoke", TRAINER_PATH)
lora = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lora)

# Synthetically generated 2x2 PNGs; only signatures/checksums are inspected.
PNG = [
 "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGO8wyXHwMDAxMDAwMDAAAANGAEIahSdtwAAAABJRU5ErkJggg==",
 "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPkMrrDwMDAxMDAwMDAAAAMeAEc4HHGxwAAAABJRU5ErkJggg==",
]


class FakeTensor:
    def __init__(self, items):
        self.items = items

    def __getitem__(self, idx):
        return FakeTensor(self.items[idx])

    def tolist(self):
        return self.items


class FakeTorch:
    long = "int64"

    @staticmethod
    def tensor(data, dtype):
        if dtype != "int64":
            raise AssertionError("labels not long dtype")
        return FakeTensor(data)


class FakeProcessor:
    tokenizer = type("T", (), {"pad_token_id": 0})()

    def __init__(self, bad_prefix=False, no_pixels=False):
        self.bad_prefix = bad_prefix
        self.no_pixels = no_pixels
        self.calls = []

    def apply_chat_template(self, messages, *, add_generation_prompt,
                            tokenize, return_dict, return_tensors):
        self.calls.append({"messages": messages, "generation_prompt": add_generation_prompt})
        assert "image" in messages[0]["content"][0], "actual pixels missing"
        assert tokenize and return_dict and return_tensors == "pt"
        if add_generation_prompt:
            ids = [11, 12, 13, 14]
        else:
            ids = [11, 12, 22 if self.bad_prefix else 13, 14, 201, 0, 202]
        batch = {"input_ids": FakeTensor([ids])}
        if not self.no_pixels:
            batch["pixel_values"] = FakeTensor([[1, 2, 3]])
        return batch


def prepared_row(id, split, group, name, sha):
    output = {"schema": "botconnector.multimedia-director.v1", "task": "product_photo"}
    return {
        "id": id,
        "task": "product_photo",
        "group_id": group,
        "source_id": "abo",
        "license": "CC-BY-4.0",
        "attribution": "synthetic QA example",
        "image_path": name,
        "image_sha256": sha,
        "messages": [
            {"role": "user", "content": [
                {"type": "image"},
                {"type": "text", "text": "Periksa foto botol; jangan mengarang label."}
            ]},
            {"role": "assistant", "content": [
                {"type": "text", "text": json.dumps(output)}
            ]}
        ]
    }


class MaskingAndArchitectureTest(unittest.TestCase):
    def test_exact_assistant_only_mask(self):
        mask = lora.assistant_only_labels([11, 12, 13, 21, 0, 22], [11, 12, 13], pad_id=0)
        self.assertEqual(mask, [-100, -100, -100, 21, -100, 22])

    def test_reject_prompt_prefix_mismatch(self):
        with self.assertRaisesRegex(ValueError, "prompt/full mismatch"):
            lora.assistant_only_labels([11, 99, 21], [11, 12])

    def test_reject_zero_length_assistant_completion(self):
        with self.assertRaisesRegex(ValueError, "no trainable assistant"):
            lora.assistant_only_labels([1, 2], [1, 2])

    def test_reject_all_padding_completion(self):
        with self.assertRaisesRegex(ValueError, "all masked"):
            lora.assistant_only_labels([1, 0], [1], pad_id=0)

    def test_processor_must_include_pixels_and_valid_target_mask(self):
        messages = prepared_row("r1", "train", "g1", "unused.png", "a" * 64)["messages"]
        messages[0]["content"][0]["image"] = object()
        processor = FakeProcessor()
        result = lora.encode_multimodal_messages(messages, processor, FakeTorch())
        self.assertEqual(result["labels"].tolist(), [[-100, -100, -100, -100, 201, -100, 202]])
        self.assertEqual(len(processor.calls), 2)
        self.assertTrue(processor.calls[0]["generation_prompt"])
        self.assertFalse(processor.calls[1]["generation_prompt"])

    def test_vision_processor_text_only_output_is_refused(self):
        messages = prepared_row("r1", "train", "g1", "unused.png", "a" * 64)["messages"]
        messages[0]["content"][0]["image"] = object()
        with self.assertRaisesRegex(ValueError, "pixel_values"):
            lora.encode_multimodal_messages(messages, FakeProcessor(no_pixels=True), FakeTorch())

    def test_missing_image_pixels_is_refused(self):
        messages = prepared_row("r1", "train", "g1", "unused.png", "a" * 64)["messages"]
        with self.assertRaisesRegex(ValueError, "real image pixels"):
            lora.encode_multimodal_messages(messages, FakeProcessor(), FakeTorch())

    def test_vision_processor_template_mismatch_is_refused(self):
        messages = prepared_row("r1", "train", "g1", "unused.png", "a" * 64)["messages"]
        messages[0]["content"][0]["image"] = object()
        with self.assertRaisesRegex(ValueError, "prompt/full mismatch"):
            lora.encode_multimodal_messages(messages, FakeProcessor(bad_prefix=True), FakeTorch())

    def test_no_automatic_image_token_truncation(self):
        messages = prepared_row("r1", "train", "g1", "unused.png", "a" * 64)["messages"]
        messages[0]["content"][0]["image"] = object()
        with self.assertRaisesRegex(ValueError, "never truncate"):
            lora.encode_multimodal_messages(messages, FakeProcessor(), FakeTorch(), max_seq_len=5)

    def test_lora_targets_text_decoder_not_vision(self):
        modules = [
            ("model.vision_model.layers.0.self_attn.q_proj", object()),
            ("model.text_model.layers.0.self_attn.q_proj", object()),
            ("model.text_model.layers.0.self_attn.v_proj", object()),
            ("model.text_model.layers.1.self_attn.q_proj", object()),
            ("model.text_model.layers.1.self_attn.v_proj", object()),
            ("model.text_model.layers.1.self_attn.o_proj", object()),
        ]
        self.assertEqual(lora.choose_language_lora_modules(modules), [
            "model.text_model.layers.0.self_attn.q_proj",
            "model.text_model.layers.0.self_attn.v_proj",
            "model.text_model.layers.1.self_attn.q_proj",
            "model.text_model.layers.1.self_attn.v_proj",
        ])

    def test_refuse_unknown_model_module_names(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            lora.choose_language_lora_modules([
                ("model.vision_model.layers.0.self_attn.q_proj", object())
            ])


class DatasetGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.assets = self.root / "assets"
        self.prepared = self.root / "prepared"
        self.assets.mkdir()
        self.prepared.mkdir()
        self.rows = {"train": [], "val": []}
        for split, count in (("train", 50), ("val", 10)):
            for i in range(count):
                name = split + "-" + str(i) + ".png"
                # Synthetic distinct checksums: add harmless trailing synthetic bytes
                data = base64.b64decode(PNG[0]) + bytes([i]) + split.encode()
                path = self.assets / name
                path.write_bytes(data)
                sha = hashlib.sha256(data).hexdigest()
                self.rows[split].append(prepared_row(split + str(i), split, split + str(i), name, sha))
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, counts=None, model=None):
        manifest = {
            "schema": lora.SCHEMA,
            "base_model": model or lora.MODEL,
            "counts": counts or {"train": 50, "val": 10, "test": 200},
            "gpu_started": False,
        }
        (self.prepared / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for split, rows in self.rows.items():
            (self.prepared / (split + ".jsonl")).write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
            )

    def test_approved_stage_preflight_without_model_or_gpu(self):
        manifest, result = lora.load_prepared(self.prepared, self.assets)
        self.assertEqual(manifest["base_model"], lora.MODEL)
        self.assertEqual([len(result["train"]), len(result["val"])], [50, 10])
        self.assertNotIn("test", result)

    def test_rejects_wrong_base_model(self):
        self.save(model="Qwen/Qwen3-VL-8B-Instruct")
        with self.assertRaisesRegex(ValueError, "model mismatch"):
            lora.load_prepared(self.prepared, self.assets)

    def test_rejects_heldout_export_into_training_folder(self):
        (self.prepared / "test.jsonl").write_text('{"test":"must remain sealed"}\n')
        with self.assertRaisesRegex(ValueError, "sealed holdout"):
            lora.load_prepared(self.prepared, self.assets)

    def test_rejects_cross_split_group_leakage(self):
        self.rows["val"][0]["group_id"] = self.rows["train"][0]["group_id"]
        self.save()
        with self.assertRaisesRegex(ValueError, "group leakage"):
            lora.load_prepared(self.prepared, self.assets)

    def test_rejects_cross_split_exact_image_leakage(self):
        self.rows["val"][0]["image_sha256"] = self.rows["train"][0]["image_sha256"]
        self.rows["val"][0]["image_path"] = self.rows["train"][0]["image_path"]
        self.save()
        with self.assertRaisesRegex(ValueError, "image leakage"):
            lora.load_prepared(self.prepared, self.assets)

    def test_rejects_modified_image(self):
        path = self.assets / self.rows["train"][0]["image_path"]
        path.write_bytes(path.read_bytes() + b"altered")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            lora.load_prepared(self.prepared, self.assets)

    def test_rejects_test_count_below_holdout_gate(self):
        self.save(counts={"train": 50, "val": 10, "test": 100})
        with self.assertRaisesRegex(ValueError, "insufficient"):
            lora.load_prepared(self.prepared, self.assets)

    def test_rejects_test_filename_and_path_escape(self):
        self.rows["val"][0]["image_path"] = "../secret.png"
        self.save()
        with self.assertRaisesRegex(ValueError, "path traversal"):
            lora.load_prepared(self.prepared, self.assets)

    def test_dry_run_does_not_load_torch_or_write_artifacts(self):
        argv = [sys.executable, str(TRAINER_PATH),
                "--prepared", str(self.prepared),
                "--assets-root", str(self.assets)]
        result = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["gpu_started"])
        self.assertEqual(output["verified_train_val_samples"], 60)
        self.assertEqual(output["test_samples_loaded"], 0)
        self.assertEqual(output["cost_usd"], 0)

    def test_paid_run_requires_explicit_acknowledgment(self):
        args = type("Args", (), {"acknowledge_paid_gpu": False, "output_dir": None, "model_dir": None})()
        with self.assertRaisesRegex(ValueError, "acknowledge-paid-gpu"):
            lora.train(args, self.prepared, self.assets, self.rows)


if __name__ == "__main__":
    unittest.main()
