#!/usr/bin/env python3
"""Fail-closed offline preprocessor for Director multimodal SFT packets.

Reads *reviewed* staging produced by prepare-multimedia-director-data.mjs.
Never downloads model weights, runs GPU jobs, or approves dataset rights.
Output is framework-neutral; the runtime adapter must load PIL images.

The packet is model-neutral: --model decides which allowed base model the
manifest seals (default Qwen3-VL-4B-Instruct, the measured Director primary;
SmolVLM2-2.2B only behind --allow-2b-legacy). The user prompt IS the serving
prompt object from multimedia-director-contract.py, so a trained prompt and a
probed prompt cannot differ. The filename keeps "smolvlm2" only because this
directory mirrors a private Draft PR byte-for-byte and a rename would add path
drift that costs more to sync than content drift.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def _load_contract():
    """Load the one runtime Director contract module (stdlib only).

    Cached in sys.modules so every consumer in this process shares ONE contract
    instance instead of private copies that can drift apart again.
    """
    name = "bico_multimedia_director_contract"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parent / "multimedia-director-contract.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


contract = _load_contract()

SCHEMA = "botconnector.multimedia-dataset.v1"
PREP_SCHEMA = "botconnector.multimedia-director-sft-prep.v1"
SPLITS = ("train", "val", "test")
SAFE_TASKS = {"product_photo", "ad_creative", "storyboard", "video_direction"}
GATE = "human_rights_review_assertions_required_but_not_independently_verified"
PRIMARY = contract.PRIMARY
LEGACY_2B = contract.LEGACY_2B
ALLOWED_MODELS = contract.ALLOWED_MODELS
TARGET_SCHEMA = contract.TARGET_SCHEMA
contract_skeleton = contract.contract_skeleton
make_prompt = contract.make_prompt


def safe_image_path(root, name):
    path = Path(name)
    if not name or path.is_absolute() or "\\" in name or ".." in path.parts:
        raise ValueError("unsafe image path")
    image = (root / path).resolve(strict=True)
    if not image.is_relative_to(root) or not image.is_file():
        raise ValueError("image path escapes dataset root")
    return image


def build_messages(row):
    """Training conversation whose user text IS the serving prompt object.

    Validation runs before make_prompt() because that builder indexes
    row["brief"] directly: a missing or empty brief must fail here with this
    script's own message, not escape as a KeyError.
    """
    task = row["task"]
    if task not in SAFE_TASKS:
        raise ValueError("unrecognized Director task")
    target = row["target"]
    if not isinstance(target, dict) or target.get("schema") != TARGET_SCHEMA or target.get("task") != task:
        raise ValueError("bad target schema")
    brief = row.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        raise ValueError("missing brief")
    return [
        {"role": "user", "content": [
            {"type": "image"},
            {"type": "text", "text": make_prompt(row)},
        ]},
        {"role": "assistant", "content": [
            {"type": "text", "text": json.dumps(target, ensure_ascii=False, sort_keys=True)},
        ]},
    ]


def records(staged, root, *, enforce_counts=True):
    summary_path = staged / "summary.json"
    if not summary_path.is_file():
        raise ValueError("staging summary missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    counts = summary.get("counts")
    if (summary.get("schema") != SCHEMA or summary.get("mode") != "gated_dataset"
        or summary.get("gate") != GATE or not isinstance(counts, dict)):
        raise ValueError("must use rights-gated dataset with source review attestation, not --smoke or ad-hoc input")
    if enforce_counts and any(counts.get(split, 0) < minimum for split, minimum in
                              (("train", 50), ("val", 10), ("test", 200))):
        raise ValueError("insufficient independently held-out data")
    result = {}
    group_splits, hash_splits, seen_ids = {}, {}, set()
    for split in SPLITS:
        path = staged / (split + ".jsonl")
        if not path.is_file():
            raise ValueError("missing stage split " + split)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(rows) != counts.get(split):
            raise ValueError("stage summary count mismatch: " + split)
        prepared = []
        for row in rows:
            if row.get("schema") != SCHEMA or row.get("split") != split:
                raise ValueError("invalid stage record schema/split")
            sample_id = row.get("id")
            if not isinstance(sample_id, str) or not sample_id or sample_id in seen_ids:
                raise ValueError("duplicate or missing staged sample ID")
            seen_ids.add(sample_id)
            group = row.get("group_id")
            digest = row.get("image_sha256")
            if not isinstance(group, str) or not group or not isinstance(digest, str):
                raise ValueError("missing group or SHA256")
            if group in group_splits and group_splits[group] != split:
                raise ValueError("cross-split product/character/project group leakage")
            if digest in hash_splits and hash_splits[digest] != split:
                raise ValueError("cross-split image checksum leakage")
            group_splits[group] = split
            hash_splits[digest] = split
            image_path = safe_image_path(root, row["image_path"])
            if hashlib.sha256(image_path.read_bytes()).hexdigest() != digest:
                raise ValueError("raw image checksum mismatch")
            prepared.append({
                "id": row["id"],
                "task": row["task"],
                "group_id": group,
                "source_id": row["source_id"],
                "license": row["license"],
                "attribution": row.get("attribution"),
                "image_path": row["image_path"],
                "image_sha256": digest,
                "messages": build_messages(row),
            })
        result[split] = prepared
    return result


def to_runtime_messages(prepared_row, assets_root):
    """Use this function inside a VLM-specific trainer after image processor tests.

    A PIL.Image object is passed in the image content part. The caller must
    then use a compatible image-aware collator, chat template and label mask.
    """
    from PIL import Image
    root = Path(assets_root).resolve(strict=True)
    image_path = safe_image_path(root, prepared_row["image_path"])
    if hashlib.sha256(image_path.read_bytes()).hexdigest() != prepared_row["image_sha256"]:
        raise ValueError("image checksum mismatch before runtime conversion")
    with Image.open(image_path) as img:
        rgb = img.convert("RGB")
    messages = json.loads(json.dumps(prepared_row["messages"]))
    messages[0]["content"][0]["image"] = rgb
    return messages


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Prepare Director VLM SFT dataset; validation only by default")
    p.add_argument("--staged", type=Path, required=True)
    p.add_argument("--assets-root", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--model", choices=sorted(ALLOWED_MODELS), default=PRIMARY,
                   help="base model this packet is sealed for")
    p.add_argument("--allow-2b-legacy", action="store_true")
    p.add_argument("--write", action="store_true", help="explicitly write validated JSONL")
    args = p.parse_args(argv)
    if args.model == LEGACY_2B and not args.allow_2b_legacy:
        p.error("2B legacy is measured insufficient (10/20 contract, factsRecall 0): "
                "pass --allow-2b-legacy only to reproduce the 1-2 Nov 2026 baseline")
    if args.out_dir.exists():
        p.error("refusing to overwrite output")
    result = records(args.staged.resolve(strict=True), args.assets_root.resolve(strict=True))
    counts = {split: len(data) for split, data in result.items()}
    if not args.write:
        print(json.dumps({"mode": "dry_run_only", "model": args.model, "counts": counts,
                          "files_written": 0, "gpu_started": False, "training_started": False}))
        return
    args.out_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        sealed = {}
        for split in ("train", "val"):
            path = args.out_dir / (split + ".jsonl")
            with path.open("x", encoding="utf-8") as file:
                for row in result[split]:
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")
            sealed[split] = hashlib.sha256(path.read_bytes()).hexdigest()
        # The raw held-out dataset is NEVER copied to the training directory.
        # Its SHA256 binds this manifest to the previously staged split without
        # revealing its records. This is provenance, NOT human/rights proof.
        test_seal = hashlib.sha256((args.staged / "test.jsonl").read_bytes()).hexdigest()
        with (args.out_dir / "manifest.json").open("x", encoding="utf-8") as file:
            json.dump({"schema": PREP_SCHEMA, "base_model": args.model,
                       "counts": counts, "gpu_started": False,
                       "source_gate": GATE,
                       "train_val_file_sha256": sealed,
                       "sealed_holdout_stage_sha256": test_seal,
                       "note": "Hash seals detect staged-file drift, not genuine ownership, visual truth or review. Never train on test split."},
                      file, ensure_ascii=False, indent=2)
    except BaseException:
        import shutil
        shutil.rmtree(args.out_dir, ignore_errors=True)
        raise
    print(json.dumps({"mode": "preprocessed_not_trained", "model": args.model,
                      "counts": counts, "output": str(args.out_dir), "gpu_started": False}))


if __name__ == "__main__":
    main()
