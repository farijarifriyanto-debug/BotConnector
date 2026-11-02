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

    def numel(self):
        def count(item):
            return sum(count(x) for x in item) if isinstance(item, list) else 1
        return count(self.items)


class FakeTorch:
    long = "int64"

    @staticmethod
    def tensor(data, dtype):
        if dtype != "int64":
            raise AssertionError("labels not long dtype")
        return FakeTensor(data)


class FakeProcessor:
    tokenizer = type("T", (), {"pad_token_id": 0})()

    def __init__(self, bad_prefix=False, no_pixels=False, pixels=None,
                 missing_prompt_pixels=False, extra_keys=None):
        self.bad_prefix = bad_prefix
        self.no_pixels = no_pixels
        self.pixels = pixels
        self.missing_prompt_pixels = missing_prompt_pixels
        self.extra_keys = extra_keys or {}
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
        if not self.no_pixels and not (self.missing_prompt_pixels and add_generation_prompt):
            batch["pixel_values"] = (self.pixels if self.pixels is not None
                                     else FakeTensor([[1, 2, 3]]))
        for key, value in self.extra_keys.items():
            batch[key] = value
        return batch


def prepared_row(id, split, group, name, sha):
    output = {
        "schema": "botconnector.multimedia-director.v1",
        "task": "product_photo",
        "visual": {"observed_facts": ["warna sintetis"], "unknowns": ["label tidak diketahui"]},
        "preservation_rules": ["Jangan ubah produk"],
        "concepts": [
            {"title": "Premium", "scene": "Studio putih", "mood": "Lembut", "tagline": "Elegan"},
            {"title": "Lifestyle", "scene": "Meja kayu", "mood": "Hangat", "tagline": "Setiap hari"},
            {"title": "Bold", "scene": "Galeri warna", "mood": "Kontras", "tagline": "Berani"},
        ],
    }
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

    def test_empty_or_malformed_nested_vision_payload_is_refused(self):
        messages = prepared_row("r1", "train", "g1", "unused.png", "a" * 64)["messages"]
        messages[0]["content"][0]["image"] = object()
        for pixels in ([], [FakeTensor([])], [None], [FakeTensor([1]), []],
                       ["image-path-only.jpg"], [1], {}):
            with self.subTest(pixels=str(pixels)[:80]):
                with self.assertRaisesRegex(ValueError, "pixel_values"):
                    lora.encode_multimodal_messages(
                        messages, FakeProcessor(pixels=pixels), FakeTorch())

    def test_missing_prompt_vision_payload_is_refused(self):
        messages = prepared_row("r1", "train", "g1", "unused.png", "a" * 64)["messages"]
        messages[0]["content"][0]["image"] = object()
        with self.assertRaisesRegex(ValueError, "pixel_values"):
            lora.encode_multimodal_messages(
                messages, FakeProcessor(missing_prompt_pixels=True), FakeTorch())

    def test_nested_nonempty_vision_payload_passes(self):
        messages = prepared_row("r1", "train", "g1", "unused.png", "a" * 64)["messages"]
        messages[0]["content"][0]["image"] = object()
        result = lora.encode_multimodal_messages(
            messages, FakeProcessor(pixels=[[FakeTensor([1, 2])]]), FakeTorch())
        self.assertIn("labels", result)

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
        legacy = [
            ("model.vision_model.layers.0.self_attn.q_proj", object()),
            ("model.text_model.layers.0.self_attn.q_proj", object()),
            ("model.text_model.layers.0.self_attn.v_proj", object()),
            ("model.text_model.layers.1.self_attn.q_proj", object()),
            ("model.text_model.layers.1.self_attn.v_proj", object()),
            ("model.text_model.layers.1.self_attn.o_proj", object()),
        ]
        self.assertEqual(lora.choose_language_lora_modules(legacy, lora.LEGACY_2B), [
            "model.text_model.layers.0.self_attn.q_proj",
            "model.text_model.layers.0.self_attn.v_proj",
            "model.text_model.layers.1.self_attn.q_proj",
            "model.text_model.layers.1.self_attn.v_proj",
        ])
        qwen = [
            ("model.visual.blocks.0.attn.qkv", object()),
            ("model.visual.blocks.0.attn.q_proj", object()),
            ("model.language_model.layers.0.self_attn.q_proj", object()),
            ("model.language_model.layers.0.self_attn.v_proj", object()),
            ("model.language_model.layers.0.self_attn.o_proj", object()),
            ("model.language_model.layers.1.self_attn.q_proj", object()),
            ("model.language_model.layers.1.self_attn.v_proj", object()),
        ]
        self.assertEqual(lora.choose_language_lora_modules(qwen, lora.PRIMARY), [
            "model.language_model.layers.0.self_attn.q_proj",
            "model.language_model.layers.0.self_attn.v_proj",
            "model.language_model.layers.1.self_attn.q_proj",
            "model.language_model.layers.1.self_attn.v_proj",
        ])

    def test_qwen_module_naming_variants_are_accepted(self):
        # transformers has exposed the Qwen3-VL text decoder both ways, and the
        # GPU recipe that actually ran on 2 Nov 2026 accepted either naming.
        flat = [
            ("model.visual.blocks.0.attn.q_proj", object()),
            ("model.layers.0.self_attn.q_proj", object()),
            ("model.layers.0.self_attn.v_proj", object()),
            ("model.layers.1.self_attn.q_proj", object()),
            ("model.layers.1.self_attn.v_proj", object()),
        ]
        self.assertEqual(lora.choose_language_lora_modules(flat, lora.PRIMARY), [
            "model.layers.0.self_attn.q_proj",
            "model.layers.0.self_attn.v_proj",
            "model.layers.1.self_attn.q_proj",
            "model.layers.1.self_attn.v_proj",
        ])

    def test_refuse_unknown_model_module_names(self):
        for model_id, vision_only in (
            (lora.LEGACY_2B, "model.vision_model.layers.0.self_attn.q_proj"),
            (lora.PRIMARY, "model.visual.blocks.0.attn.q_proj"),
        ):
            with self.subTest(model=model_id):
                with self.assertRaisesRegex(ValueError, "not found"):
                    lora.choose_language_lora_modules([(vision_only, object())], model_id)

    def test_forbidden_trainable_markers_cover_qwen_visual_tower(self):
        for marker in ("visual", "vision", "connector"):
            self.assertIn(marker, lora.VISION_MARKERS)

    def test_registry_and_schema_come_from_contract_module(self):
        contract = sys.modules["bico_multimedia_director_contract"]
        spec = importlib.util.spec_from_file_location(
            "bico_sft_cross_check", ROOT / "scripts/prepare-smolvlm2-sft.py")
        sft = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sft)
        self.assertIs(lora.EXPECTED_ARCHITECTURES, contract.EXPECTED_ARCHITECTURES)
        self.assertEqual(lora.PRIMARY, contract.PRIMARY)
        self.assertEqual(lora.LEGACY_2B, contract.LEGACY_2B)
        self.assertEqual(lora.ALLOWED_MODELS, contract.ALLOWED_MODELS)
        self.assertEqual(lora.SCHEMA, sft.PREP_SCHEMA)

    def test_qwen_vision_keys_require_image_grid_thw(self):
        messages = prepared_row("r1", "train", "g1", "unused.png", "a" * 64)["messages"]
        messages[0]["content"][0]["image"] = object()
        qwen_keys = ("pixel_values", "image_grid_thw")
        result = lora.encode_multimodal_messages(
            messages, FakeProcessor(extra_keys={"image_grid_thw": FakeTensor([[1, 2, 2]])}),
            FakeTorch(), vision_keys=qwen_keys)
        self.assertIn("labels", result)
        with self.assertRaisesRegex(ValueError, "image_grid_thw"):
            lora.encode_multimodal_messages(messages, FakeProcessor(), FakeTorch(),
                                            vision_keys=qwen_keys)
        self.assertEqual(lora.vision_keys_for(lora.PRIMARY), qwen_keys)
        self.assertEqual(lora.vision_keys_for(lora.LEGACY_2B), ("pixel_values",))
        with self.assertRaisesRegex(ValueError, "unknown Director model"):
            lora.vision_keys_for("Qwen/Qwen3-VL-8B-Instruct")


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
        seals = {}
        for split, rows in self.rows.items():
            path = self.prepared / (split + ".jsonl")
            path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
            )
            seals[split] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {
            "schema": lora.SCHEMA,
            "base_model": model or lora.PRIMARY,
            "counts": counts or {"train": 50, "val": 10, "test": 200},
            "gpu_started": False,
            "source_gate": lora.GATE,
            "train_val_file_sha256": seals,
            # Synthetic holdout placeholder in unit tests; never training data.
            "sealed_holdout_stage_sha256":
                hashlib.sha256(b"synthetic sealed holdout not exported").hexdigest(),
        }
        (self.prepared / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_rejects_tampered_packed_train_file_even_if_valid_json(self):
        path = self.prepared / "train.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        rows[0]["messages"][0]["content"][1]["text"] = "attacker supplied prompt"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "prepared split SHA256 mismatch"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_unsealed_or_forged_holdout_digest(self):
        manifest_path = self.prepared / "manifest.json"
        for value in (None, "not-sha256", "x" * 64):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if value is None:
                manifest.pop("sealed_holdout_stage_sha256")
            else:
                manifest["sealed_holdout_stage_sha256"] = value
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "manifest SHA256 provenance|holdout SHA256 invalid"):
                    lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_missing_source_review_attestation(self):
        manifest_path = self.prepared / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("source_gate")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source review attestation"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_approved_stage_preflight_without_model_or_gpu(self):
        manifest, result = lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)
        self.assertEqual(manifest["base_model"], lora.PRIMARY)
        self.assertEqual([len(result["train"]), len(result["val"])], [50, 10])
        self.assertNotIn("test", result)

    def test_rejects_wrong_base_model(self):
        self.save(model="Qwen/Qwen3-VL-8B-Instruct")
        with self.assertRaisesRegex(ValueError, "model mismatch"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_heldout_export_into_training_folder(self):
        (self.prepared / "test.jsonl").write_text('{"test":"must remain sealed"}\n')
        with self.assertRaisesRegex(ValueError, "sealed holdout"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_cross_split_group_leakage(self):
        self.rows["val"][0]["group_id"] = self.rows["train"][0]["group_id"]
        self.save()
        with self.assertRaisesRegex(ValueError, "group leakage"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_cross_split_exact_image_leakage(self):
        self.rows["val"][0]["image_sha256"] = self.rows["train"][0]["image_sha256"]
        self.rows["val"][0]["image_path"] = self.rows["train"][0]["image_path"]
        self.save()
        with self.assertRaisesRegex(ValueError, "image leakage"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_modified_image(self):
        path = self.assets / self.rows["train"][0]["image_path"]
        path.write_bytes(path.read_bytes() + b"altered")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_test_count_below_holdout_gate(self):
        self.save(counts={"train": 50, "val": 10, "test": 100})
        with self.assertRaisesRegex(ValueError, "insufficient"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_test_filename_and_path_escape(self):
        self.rows["val"][0]["image_path"] = "../secret.png"
        self.save()
        with self.assertRaisesRegex(ValueError, "path traversal"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_target_with_repeated_ad_concepts(self):
        target = json.loads(self.rows["train"][0]["messages"][1]["content"][0]["text"])
        target["concepts"][1]["scene"] = target["concepts"][0]["scene"]
        self.rows["train"][0]["messages"][1]["content"][0]["text"] = json.dumps(target)
        self.save()
        with self.assertRaisesRegex(ValueError, "scenes are duplicated"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_target_without_verified_visual_facts(self):
        target = json.loads(self.rows["train"][0]["messages"][1]["content"][0]["text"])
        target["visual"]["observed_facts"] = []
        self.rows["train"][0]["messages"][1]["content"][0]["text"] = json.dumps(target)
        self.save()
        with self.assertRaisesRegex(ValueError, "observed facts"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_rejects_license_without_provenance(self):
        self.rows["train"][0]["license"] = "CC-BY-NC-4.0"
        self.save()
        with self.assertRaisesRegex(ValueError, "unsupported license"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)

    def test_dry_run_does_not_load_torch_or_write_artifacts(self):
        argv = [sys.executable, str(TRAINER_PATH),
                "--prepared", str(self.prepared),
                "--assets-root", str(self.assets)]
        result = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["gpu_started"])
        self.assertEqual(output["model"], lora.PRIMARY)
        self.assertEqual(output["verified_train_val_samples"], 60)
        self.assertEqual(output["test_samples_loaded"], 0)
        self.assertEqual(output["cost_usd"], 0)

    def test_checkpoint_preflight_matches_selected_architecture(self):
        model = self.root / "synthetic-model"
        model.mkdir()
        config = model / "config.json"
        (model / "model.safetensors").write_bytes(b"synthetic placeholder not a model")
        accepted = {lora.PRIMARY: ("qwen3_vl",),
                    lora.LEGACY_2B: ("idefics3", "smolvlm")}
        rejected = {lora.PRIMARY: ("idefics3", "smolvlm", "qwen2_vl", "llama", "gemma3"),
                    lora.LEGACY_2B: ("qwen3_vl", "qwen2_vl", "llama", "gemma3")}
        for model_id, types in accepted.items():
            for model_type in types:
                config.write_text(json.dumps({"model_type": model_type}), encoding="utf-8")
                with self.subTest(model=model_id, architecture=model_type):
                    self.assertEqual(lora.verify_local_checkpoint(model, model_id), model)
        for model_id, types in rejected.items():
            for model_type in types:
                config.write_text(json.dumps({"model_type": model_type}), encoding="utf-8")
                with self.subTest(model=model_id, architecture=model_type):
                    with self.assertRaisesRegex(ValueError, "architecture incompatible"):
                        lora.verify_local_checkpoint(model, model_id)
        with self.assertRaisesRegex(ValueError, "unknown Director model"):
            lora.verify_local_checkpoint(model, "Qwen/Qwen3-VL-8B-Instruct")

    def test_checkpoint_preflight_rejects_pickle_and_missing_weights(self):
        model = self.root / "synthetic-model"
        model.mkdir()
        (model / "config.json").write_text(
            json.dumps({"model_type":"idefics3"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "safetensors"):
            lora.verify_local_checkpoint(model, lora.LEGACY_2B)
        (model / "model.safetensors").write_bytes(b"synthetic")
        (model / "pytorch_model.bin").write_bytes(b"pickle")
        with self.assertRaisesRegex(ValueError, "pickle-format"):
            lora.verify_local_checkpoint(model, lora.LEGACY_2B)

    def test_stale_smolvlm2_packet_is_refused_by_default_model(self):
        manifest_path = self.prepared / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema"] = "botconnector.smolvlm2-sft-prep.v1"
        manifest["base_model"] = lora.LEGACY_2B
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "model mismatch"):
            lora.load_prepared(self.prepared, self.assets, lora.PRIMARY)
        with self.assertRaisesRegex(ValueError, "model mismatch"):
            lora.load_prepared(self.prepared, self.assets, lora.LEGACY_2B)

    def test_legacy_2b_training_requires_explicit_flag(self):
        argv = [sys.executable, str(TRAINER_PATH),
                "--prepared", str(self.prepared),
                "--assets-root", str(self.assets),
                "--model", lora.LEGACY_2B]
        refused = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("allow-2b-legacy", refused.stderr)
        self.save(model=lora.LEGACY_2B)
        allowed = subprocess.run(argv + ["--allow-2b-legacy"], capture_output=True, text=True)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(json.loads(allowed.stdout)["model"], lora.LEGACY_2B)

    def test_paid_run_requires_explicit_acknowledgment(self):
        args = type("Args", (), {"acknowledge_paid_gpu": False, "output_dir": None, "model_dir": None})()
        with self.assertRaisesRegex(ValueError, "acknowledge-paid-gpu"):
            lora.train(args, self.prepared, self.assets, self.rows)


if __name__ == "__main__":
    unittest.main()
