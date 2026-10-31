#!/usr/bin/env python3
"""BICO Multimedia Director 2.2B LoRA smoke runner.

Offline and validation-only by default. Actual training requires --run,
--acknowledge-paid-gpu, a LOCAL SmolVLM2 checkpoint, a licensed/reviewed staged
dataset, and a CUDA GPU. This script never creates a cloud VM, downloads model
weights, fetches private datasets, or exposes an inference endpoint.

Real SmolVLM2 processor/model/PEFT compatibility must still pass a GPU smoke.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

SCHEMA = "botconnector.smolvlm2-sft-prep.v1"
DIRECTOR_SCHEMA = "botconnector.multimedia-director.v1"
MODEL = "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
MIN_COUNTS = {"train": 50, "val": 10, "test": 200}
ALLOWED_TASKS = {"product_photo", "ad_creative", "storyboard", "video_direction"}
MAX_SAMPLES = 10000


def asset_path(root, name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("invalid image path")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("image path traversal")
    actual = (root / relative).resolve(strict=True)
    if not actual.is_relative_to(root) or not actual.is_file():
        raise ValueError("image escapes approved dataset root")
    if actual.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("image over size limit")
    return actual


def verify_sha(image, expected):
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("missing SHA256")
    actual = hashlib.sha256(image.read_bytes()).hexdigest()
    if actual != expected.lower():
        raise ValueError("raw image SHA256 mismatch")


def load_prepared(prepared, assets_root):
    manifest_path = prepared / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("missing reviewed SFT manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = manifest.get("counts")
    if manifest.get("schema") != SCHEMA or manifest.get("base_model") != MODEL:
        raise ValueError("SmolVLM2 preparation schema/model mismatch")
    if not isinstance(counts, dict) or any(
        not isinstance(counts.get(k), int) or counts[k] < limit
        for k, limit in MIN_COUNTS.items()
    ):
        raise ValueError("insufficient licensed train, val or sealed test cases")
    if (prepared / "test.jsonl").exists():
        raise ValueError("sealed holdout test data must never be exported to training")
    seen_ids = set()
    groups, hashes, result = {}, {}, {}
    for split in ("train", "val"):
        source = prepared / (split + ".jsonl")
        if not source.is_file():
            raise ValueError("missing training split " + split)
        rows = []
        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if len(rows) >= MAX_SAMPLES:
                raise ValueError("dataset exceeds smoke runner sample cap")
            row = json.loads(line)
            if row.get("id") in seen_ids or not isinstance(row.get("id"), str):
                raise ValueError("repeated or invalid sample ID")
            seen_ids.add(row["id"])
            if row.get("task") not in ALLOWED_TASKS:
                raise ValueError("invalid task in SFT dataset")
            group, digest = row.get("group_id"), row.get("image_sha256")
            if not isinstance(group, str) or not group:
                raise ValueError("invalid group ID")
            if group in groups and groups[group] != split:
                raise ValueError("train-validation group leakage")
            if digest in hashes and hashes[digest] != split:
                raise ValueError("train-validation exact-image leakage")
            groups[group], hashes[digest] = split, digest
            image = asset_path(assets_root, row.get("image_path"))
            verify_sha(image, digest)
            messages = row.get("messages")
            if (not isinstance(messages, list) or len(messages) != 2
                or messages[0].get("role") != "user"
                or messages[1].get("role") != "assistant"):
                raise ValueError("invalid user-image/assistant conversation")
            user_parts = messages[0].get("content")
            assistant_parts = messages[1].get("content")
            if (not isinstance(user_parts, list) or len(user_parts) != 2
                or user_parts[0] != {"type": "image"}
                or user_parts[1].get("type") != "text"
                or not isinstance(user_parts[1].get("text"), str)
                or not isinstance(assistant_parts, list) or len(assistant_parts) != 1
                or assistant_parts[0].get("type") != "text"):
                raise ValueError("multimodal message structure invalid")
            try:
                target = json.loads(assistant_parts[0]["text"])
            except (ValueError, TypeError) as exc:
                raise ValueError("assistant target is not JSON") from exc
            if target.get("schema") != DIRECTOR_SCHEMA or target.get("task") != row["task"]:
                raise ValueError("assistant Director target schema mismatch")
            # Structural quality was previously gated by the JS dataset validator;
            # full-image semantic truth and source license still require human review.
            rows.append(row)
        if len(rows) != counts.get(split):
            raise ValueError("manifest count disagrees with actual split " + split)
        result[split] = rows
    return manifest, result


def assistant_only_labels(full_tokens, prefix_tokens, pad_id=None):
    """Return token IDs only for target assistant completion; fail closed.

    Prefix must be an exact token prefix of the FULL MULTIMODAL conversation.
    User prompt and all image placeholder tokens are masked with -100.
    """
    full, prefix = list(full_tokens), list(prefix_tokens)
    if not prefix or len(full) <= len(prefix):
        raise ValueError("no trainable assistant completion")
    if full[:len(prefix)] != prefix:
        raise ValueError("processor prompt/full mismatch: refuse training wrong loss mask")
    labels = [-100] * len(prefix) + full[len(prefix):]
    if pad_id is not None:
        labels = [-100 if token == pad_id else label for token, label in zip(full, labels)]
    if not any(token != -100 for token in labels):
        raise ValueError("assistant labels all masked")
    return labels


def build_supervised_batch(row, assets_root, processor, torch_module, max_seq_len=4096):
    """One RGB image + user prompt + assistant JSON, no image-only/text-only shortcut.

    Microbatch is one. Validate exact prefix before loss masking. Any
    SmolVLM2 processor incompatibility fails instead of corrupting targets.
    """
    from PIL import Image, ImageOps
    image = asset_path(assets_root, row["image_path"])
    verify_sha(image, row["image_sha256"])
    Image.MAX_IMAGE_PIXELS = 20_000_000
    with Image.open(image) as img:
        rgb = ImageOps.exif_transpose(img).convert("RGB")
    if max(rgb.size) > 768:
        rgb.thumbnail((768, 768), Image.Resampling.LANCZOS)
    messages = json.loads(json.dumps(row["messages"]))
    messages[0]["content"][0]["image"] = rgb
    try:
        return encode_multimodal_messages(messages, processor, torch_module, max_seq_len)
    finally:
        rgb.close()


def encode_multimodal_messages(messages, processor, torch_module, max_seq_len=4096):
    """Pure processor adapter; testable with a fake VLM processor, no GPU.

    The caller must place a real PIL RGB image inside user content. This adapter
    refuses text-only processor output or a misaligned assistant loss mask.
    """
    if not isinstance(messages, list) or len(messages) != 2:
        raise ValueError("one user-image message + one assistant JSON required")
    user_parts = messages[0].get("content", [])
    if (not isinstance(user_parts, list) or len(user_parts) != 2
        or user_parts[0].get("type") != "image"
        or "image" not in user_parts[0]):
        raise ValueError("real image pixels must be attached, not a text-only placeholder")
    prompt = processor.apply_chat_template(
        messages[:1], add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt"
    )
    full_batch = processor.apply_chat_template(
        messages, add_generation_prompt=False, tokenize=True,
        return_dict=True, return_tensors="pt"
    )
    if "pixel_values" not in full_batch:
        raise ValueError("vision processor did not return pixel_values")
    full_tokens = full_batch["input_ids"][0].tolist()
    prefix_tokens = prompt["input_ids"][0].tolist()
    if len(full_tokens) > max_seq_len:
        raise ValueError("multimodal sequence exceeds budget; never truncate image tokens")
    tokenizer = getattr(processor, "tokenizer", None)
    pad_id = getattr(tokenizer, "pad_token_id", None)
    labels = assistant_only_labels(full_tokens, prefix_tokens, pad_id=pad_id)
    full_batch["labels"] = torch_module.tensor([labels], dtype=torch_module.long)
    return full_batch


def choose_language_lora_modules(named_modules):
    """Only q/v projections of the TEXT decoder; never vision tower modules."""
    names = [name for name, _ in named_modules]
    selected = [
        name for name in names
        if ".text_model." in "." + name + "."
        and name.endswith((".q_proj", ".v_proj"))
        and not any(forbidden in name for forbidden in ("vision_model", "vision_tower", "connector"))
    ]
    if len(selected) < 4 or not any(s.endswith(".q_proj") for s in selected) or not any(s.endswith(".v_proj") for s in selected):
        raise ValueError("expected SmolVLM2 text_model projections not found; inspect architecture")
    return selected


def train(args, prepared, assets_root, data):
    # Do not load ML dependencies or CUDA until every safety gate passes.
    if not args.acknowledge_paid_gpu or args.output_dir is None or args.model_dir is None:
        raise ValueError("--run requires --acknowledge-paid-gpu, --model-dir, --output-dir")
    model_dir = args.model_dir.resolve(strict=True)
    if not model_dir.is_dir() or not (model_dir / "config.json").is_file():
        raise ValueError("offline local model directory missing config.json")
    if args.output_dir.exists():
        raise ValueError("refuse to overwrite prior training output")
    if not 1 <= args.max_steps <= 20:
        raise ValueError("smoke max steps must be between 1 and 20")
    if not 256 <= args.max_seq_len <= 8192:
        raise ValueError("max_seq_len out of safe smoke bounds")
    # Enforce fully offline checkpoint resolution; no remote model download.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["WANDB_DISABLED"] = "true"
    import torch
    from transformers import (
        AutoModelForImageTextToText, AutoProcessor, Trainer, TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available; do not train on CPU")
    cuda = torch.cuda.get_device_properties(0)
    if cuda.total_memory < 15 * 2**30:
        raise RuntimeError("less than ~16 GiB VRAM; do not guess capacity")
    bf16 = torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else torch.float16
    processor = AutoProcessor.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False
    )
    model = AutoModelForImageTextToText.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False,
        torch_dtype=dtype
    ).to("cuda")
    if hasattr(model.config, "use_cache"):
        model.config.use_cache = False
    modules = choose_language_lora_modules(model.named_modules())
    model = get_peft_model(model, LoraConfig(
        r=8, lora_alpha=16, lora_dropout=0.05,
        target_modules=modules, bias="none",
    ))
    unsafe = [name for name, param in model.named_parameters()
              if param.requires_grad and any(k in name for k in ("vision_model", "vision_tower", "connector"))]
    if unsafe:
        raise RuntimeError("vision tower unexpectedly trainable: " + unsafe[0])
    class Rows:
        def __init__(self, rows):
            self.items = rows
        def __len__(self):
            return len(self.items)
        def __getitem__(self, index):
            return self.items[index]
    def collate(batch):
        if len(batch) != 1:
            raise RuntimeError("only single-example multimodal microbatch supported")
        return build_supervised_batch(batch[0], assets_root, processor, torch, args.max_seq_len)
    # Run one REAL image through the tokenizer, vision tower inputs and mask
    # BEFORE creating an output directory or starting Trainer.
    first_batch = collate([data["train"][0]])
    if first_batch["labels"].shape[-1] != first_batch["input_ids"].shape[-1]:
        raise RuntimeError("label length and multimodal input length mismatch")
    args.output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = time.monotonic()
    try:
        training_args = TrainingArguments(
            output_dir=str(args.output_dir),
            per_device_train_batch_size=1,
            per_device_eval_batch_size=1,
            gradient_accumulation_steps=8,
            learning_rate=5e-5,
            max_steps=args.max_steps,
            num_train_epochs=1,
            warmup_steps=0,
            logging_steps=1,
            eval_strategy="steps",
            eval_steps=max(1, args.max_steps // 2),
            save_strategy="no",
            report_to="none",
            bf16=bf16, fp16=not bf16,
            remove_unused_columns=False,
            dataloader_num_workers=0,
            seed=1337,
        )
        runner = Trainer(
            model=model,
            args=training_args,
            train_dataset=Rows(data["train"]),
            eval_dataset=Rows(data["val"]),
            data_collator=collate,
        )
        runner.train()
        # Save ONLY LoRA adapter, tokenizer/processor and non-private run metadata.
        model.save_pretrained(str(args.output_dir))
        processor.save_pretrained(str(args.output_dir))
        summary = {
            "schema": "botconnector.multimedia-director-lora-smoke.v1",
            "base_model": MODEL,
            "steps": args.max_steps,
            "runtime_seconds": round(time.monotonic() - started, 2),
            "gpu_name": cuda.name,
            "gpu_vram_gib": round(cuda.total_memory / 2**30, 2),
            "peak_gpu_allocated_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
            "train_examples": len(data["train"]),
            "val_examples": len(data["val"]),
            "test_examples_used": 0,
            "human_visual_eval": "not_performed",
            "cost_usd": None,
            "note": "LoRA adapter is an unreviewed experiment, not production ready.",
        }
        (args.output_dir / "run-summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        return summary
    except BaseException:
        # Preserve failed run artifacts for authorized forensic review;
        # caller must terminate cloud GPU and clean up residual storage manually.
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description="SmolVLM2-2.2B LoRA: offline validation by default")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--assets-root", type=Path, required=True)
    p.add_argument("--model-dir", type=Path)
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--max-steps", type=int, default=5)
    p.add_argument("--max-seq-len", type=int, default=4096)
    p.add_argument("--run", action="store_true")
    p.add_argument("--acknowledge-paid-gpu", action="store_true")
    args = p.parse_args(argv)
    if args.output_dir and args.output_dir.exists():
        p.error("output directory already exists")
    if args.max_steps < 1 or args.max_steps > 20:
        p.error("smoke run is limited to 1-20 steps")
    try:
        root = args.assets_root.resolve(strict=True)
        staged = args.prepared.resolve(strict=True)
        manifest, rows = load_prepared(staged, root)
        if not args.run:
            print(json.dumps({
                "status": "OFFLINE PREFLIGHT PASS; no model loaded or train started",
                "model": MODEL,
                "counts": manifest["counts"],
                "verified_train_val_samples": len(rows["train"]) + len(rows["val"]),
                "test_samples_loaded": 0,
                "gpu_started": False,
                "cost_usd": 0,
                "next_step": "authorize GPU spend and verify SmolVLM2 processor on the actual GPU",
            }, indent=2))
            return 0
        summary = train(args, staged, root, rows)
        print(json.dumps(summary, indent=2))
        return 0
    except Exception as exc:
        print("SMOKE STOPPED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
