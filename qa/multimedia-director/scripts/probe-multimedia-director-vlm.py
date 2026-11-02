#!/usr/bin/env python3
"""Explicit, local-only VLM Director probe; dry-run by default.

Primary model is Qwen3-VL-4B-Instruct (model decision 2 Nov 2026). The
SmolVLM2-2.2B pilot baseline is kept as a gated legacy option so the measured
2B failure stays reproducible. --constrained-decoding arms an xgrammar mask
built from the same contract as the prompt, so a constrained run cannot emit
invalid JSON; the unconstrained baseline stays measurable without it. This does
NOT fine-tune weights, download models, access customer media, or reserve a
Community GPU. Run mode requires a reviewed staged dataset and a locally cached
trusted model checkpoint on a pre-authorized GPU.
"""
import argparse
import hashlib
import importlib.util
import json
import numbers
import os
import pathlib
import sys
import time


def _load_contract():
    """Load the one runtime Director contract module (stdlib only).

    Cached in sys.modules so every consumer in this process shares ONE contract
    instance instead of private copies that can drift apart again.
    """
    name = "bico_multimedia_director_contract"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = pathlib.Path(__file__).resolve().parent / "multimedia-director-contract.py"
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

# The measured model decision, the contract text and the architecture gate live
# in multimedia-director-contract.py. These re-exports keep this probe's public
# names unchanged while deleting the second copy that drifted from the training
# prompt builder on 1-2 Nov 2026.
PRIMARY = contract.PRIMARY
LEGACY_2B = contract.LEGACY_2B
ALLOWED_MODELS = contract.ALLOWED_MODELS
TARGET_SCHEMA = contract.TARGET_SCHEMA
DIRECTOR_TASKS = contract.DIRECTOR_TASKS
EXPECTED_ARCHITECTURES = contract.EXPECTED_ARCHITECTURES
contract_skeleton = contract.contract_skeleton
contract_json_schema = contract.contract_json_schema
make_prompt = contract.make_prompt
STAGING_SCHEMA = "botconnector.multimedia-dataset.v1"


def verify_local_checkpoint(path, model_id):
    """Fail closed before importing torch: only an explicit LOCAL safetensors tree."""
    if path is None:
        raise ValueError("--run requires --model-dir with an already-installed local checkpoint")
    if path.is_symlink():
        raise ValueError("checkpoint path must not be a symlink")
    root = path.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("model-dir is not a directory")
    config_path = root / "config.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError("local checkpoint missing plain config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("model config must be JSON object")
    # The two allowed model families must not silently load another architecture.
    model_type = config.get("model_type")
    if model_type not in EXPECTED_ARCHITECTURES[model_id]:
        raise ValueError("local checkpoint model_type incompatible with selected model (check version)")
    weights = list(root.glob("*.safetensors"))
    if not weights:
        raise ValueError("no local safetensors weights found; remote model downloads are forbidden")
    if any(p.is_symlink() for p in weights):
        raise ValueError("symlinked weight files not accepted in this offline baseline")
    if any(root.glob("*.bin")) or any(root.glob("*.pt")) or any(root.glob("*.pth")):
        raise ValueError("pickle-format model weights forbidden")
    return root


def nonempty_vision_payload(value):
    """Accept a nonempty tensor/array or nested list of nonempty tensors.

    A list containing None, an empty tensor, a string or an image placeholder
    must never count as vision input. This is a *shape/presence* gate, not proof
    that the tensors correspond to the approved image's actual pixels.
    """
    if isinstance(value, (list, tuple)):
        return bool(value) and all(nonempty_vision_payload(part) for part in value)
    if value is None or isinstance(value, (str, bytes, bytearray, dict)):
        return False
    numel = getattr(value, "numel", None)
    if callable(numel):
        size = numel()
        return isinstance(size, numbers.Integral) and size > 0
    size = getattr(value, "size", None)
    return isinstance(size, numbers.Integral) and size > 0


def require_real_pixel_values(batch):
    """Refuse empty/malformed image tensors or text-only processor outputs."""
    if not hasattr(batch, "keys") or "input_ids" not in batch:
        raise ValueError("vision processor omitted input_ids")
    if "pixel_values" not in batch or not nonempty_vision_payload(batch["pixel_values"]):
        raise ValueError("processor omitted nonempty pixel_values: text-only fallback forbidden")
    return True


def inside(root, name):
    if pathlib.Path(name).is_absolute() or "\\" in name or ".." in pathlib.PurePosixPath(name).parts:
        raise ValueError("unsafe image path")
    p = (root / name).resolve(strict=True)
    if not p.is_file() or not p.is_relative_to(root):
        raise ValueError("image escapes assets root")
    return p


def load_samples(staged, assets_root, split, limit):
    path = staged / (split + ".jsonl")
    if not path.is_file():
        raise ValueError("staged dataset split missing: " + str(path))
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("schema") != STAGING_SCHEMA or row.get("split") != split:
            raise ValueError("invalid staging schema/split")
        image_path = inside(assets_root, str(row.get("image_path", "")))
        actual = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if actual != row.get("image_sha256"):
            raise ValueError("image SHA256 mismatch")
        if not isinstance(row.get("brief"), str) or not row.get("brief"):
            raise ValueError("empty brief")
        rows.append((row, image_path))
        if len(rows) >= limit:
            break
    if not rows:
        raise ValueError("no staged samples in split")
    return rows



def verify_full_gated_staging(staged, assets_root, summary):
    """Recount all three approved-stage split files and confirm no ID/image/group leakage.

    A staged summary is a *claim*, not independent legal proof of rights.
    This check catches altered/incomplete stages; independent human/rights
    audit remains a separate release requirement.
    """
    minimums = {"train": 50, "val": 10, "test": 200}
    if summary.get("gate") != "human_rights_review_assertions_required_but_not_independently_verified":
        raise ValueError("missing original rights-gate attestation in staging summary")
    counts = summary.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("staging summary missing counts")
    ids, groups, hashes = set(), {}, {}
    verified = {}
    for split, minimum in minimums.items():
        path = staged / (split + ".jsonl")
        if not path.is_file():
            raise ValueError("full gated stage missing " + split + ".jsonl")
        n = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("schema") != STAGING_SCHEMA or row.get("split") != split:
                raise ValueError("staged split schema mismatch")
            sample_id = row.get("id")
            group = row.get("group_id")
            digest = row.get("image_sha256")
            if (not isinstance(sample_id, str) or not sample_id or sample_id in ids
                or not isinstance(group, str) or not group
                or not isinstance(digest, str) or len(digest) != 64):
                raise ValueError("duplicate id or missing group/hash in staged dataset")
            ids.add(sample_id)
            if group in groups and groups[group] != split:
                raise ValueError("train/evaluation product group leakage")
            if digest in hashes and hashes[digest] != split:
                raise ValueError("train/evaluation exact-image leakage")
            groups[group], hashes[digest] = split, digest
            image = inside(assets_root, str(row.get("image_path", "")))
            if hashlib.sha256(image.read_bytes()).hexdigest() != digest.lower():
                raise ValueError("staged full-split image SHA256 mismatch")
            if (row.get("license") not in ("CC-BY-4.0", "CC0-1.0")
                or (row.get("license") == "CC-BY-4.0" and
                    (not isinstance(row.get("attribution"), str)
                     or not row["attribution"].strip()))):
                raise ValueError("staged source license/attribution metadata missing")
            if not isinstance(row.get("target"), dict):
                raise ValueError("staged human-reviewed reference target missing")
            n += 1
            if n > 10000:
                raise ValueError("per-split limit exceeded")
        if n < minimum or n != counts.get(split):
            raise ValueError("gated stage count mismatch or insufficient split: " + split)
        verified[split] = n
    return verified


def contract_constraint(processor, task):
    """Compile the contract into (compiled_grammar, processor_factory).

    Fail closed: a missing xgrammar must stop the run instead of silently
    decoding unconstrained, which would produce results the flag did not promise.
    The compiled grammar is cacheable across rows; processor_factory() builds a
    fresh logits processor per generation because it holds per-sequence state.
    """
    try:
        import xgrammar as xgr
    except ImportError as exc:
        raise RuntimeError(
            "constrained decoding requested but xgrammar is not installed; "
            "install xgrammar in the GPU image or drop --constrained-decoding") from exc
    try:
        from xgrammar.contrib.logits_processor import XGrammarLogitsProcessor
    except ImportError as exc:
        raise RuntimeError(
            "xgrammar is installed but its logits processor is unavailable") from exc
    tokenizer = getattr(processor, "tokenizer", processor)
    tokenizer_info = xgr.TokenizerInfo.from_hf_tokenizer(tokenizer)
    compiled = xgr.GrammarCompiler(tokenizer_info, max_threads=1).compile(
        xgr.Grammar.from_json_schema(json.dumps(contract_json_schema(task))))
    return compiled, XGrammarLogitsProcessor


def probe(argv=None):
    p = argparse.ArgumentParser(description="Offline-preflight VLM baseline; --run is explicit")
    p.add_argument("--staged", required=True, type=pathlib.Path)
    p.add_argument("--assets-root", required=True, type=pathlib.Path)
    p.add_argument("--split", choices=("train", "val", "test"), default="val")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--model", choices=sorted(ALLOWED_MODELS), default=PRIMARY)
    p.add_argument("--allow-2b-legacy", action="store_true")
    p.add_argument("--constrained-decoding", action="store_true",
                   help="mask generation with an xgrammar grammar built from the contract schema")
    p.add_argument("--run", action="store_true")
    p.add_argument("--acknowledge-runtime-cost", action="store_true")
    p.add_argument("--out", type=pathlib.Path)
    p.add_argument("--model-dir", type=pathlib.Path,
                   help="explicit downloaded local safetensors directory; required for --run")
    args = p.parse_args(argv)
    if not 1 <= args.limit <= 50:
        p.error("limit must be 1..50")
    if args.model == LEGACY_2B and not args.allow_2b_legacy:
        p.error("2B legacy is measured insufficient (10/20 contract, factsRecall 0): "
                "pass --allow-2b-legacy only to reproduce the 1-2 Nov 2026 baseline")
    if args.run and (not args.acknowledge_runtime_cost or not args.out):
        p.error("actual GPU inference requires --acknowledge-runtime-cost and --out")
    try:
        assets_root = args.assets_root.resolve(strict=True)
        staged = args.staged.resolve(strict=True)
        samples = load_samples(staged, assets_root, args.split, args.limit)
        if args.run:
            summary_path = staged / "summary.json"
            if not summary_path.is_file():
                raise ValueError("GPU baseline requires a fully gated dataset summary, not ad-hoc staging")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            counts = summary.get("counts", {})
            if (summary.get("schema") != STAGING_SCHEMA or
                summary.get("mode") != "gated_dataset" or
                not isinstance(counts, dict) or
                counts.get("train", 0) < 50 or counts.get("val", 0) < 10 or counts.get("test", 0) < 200):
                raise ValueError("GPU baseline requires reviewed train/val/heldout counts; --smoke is not eligible")
            verify_full_gated_staging(staged, assets_root, summary)
        if args.run and args.split == "train":
            raise ValueError("baseline must use reviewed validation/test samples, never train")
        if args.run and args.out.exists():
            raise FileExistsError("refusing to overwrite predictions before loading checkpoint")
        model_dir = verify_local_checkpoint(args.model_dir, args.model) if args.run else None
        if not args.run:
            print(json.dumps({"mode": "dry_run_only", "model": args.model,
                "sample_count": len(samples), "split": args.split,
                "constrained_decoding": bool(args.constrained_decoding),
                "image_files_checked": True,
                "gpu_started": False, "model_downloaded": False,
                "training_started": False,
                "note": "Model compatibility, visual quality and GPU memory remain unverified."}, indent=2))
            return 0
        # Imports and model access happen only after explicit --run and local checks.
        # No HTTP, Hub API, third-party telemetry or automatic checkpoint downloads.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["WANDB_DISABLED"] = "true"
        import torch
        from PIL import Image
        from transformers import AutoModelForImageTextToText, AutoProcessor
        if not torch.cuda.is_available():
            raise RuntimeError("No CUDA GPU; refuse CPU model loading")
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        model = AutoModelForImageTextToText.from_pretrained(
            str(model_dir), local_files_only=True, torch_dtype=dtype,
            use_safetensors=True, trust_remote_code=False
        ).to("cuda")
        processor = AutoProcessor.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False)
        # Grammar is compiled once per task; a fresh logits processor per row
        # because it carries per-sequence state.
        constraint_cache = {}
        results = []
        for row, path in samples:
            task = row["task"]
            image = Image.open(path).convert("RGB")
            messages = [{"role": "user", "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": make_prompt(row)},
            ]}]
            try:
                encoded = processor.apply_chat_template(
                    messages, add_generation_prompt=True, tokenize=True,
                    return_dict=True, return_tensors="pt"
                )
                require_real_pixel_values(encoded)
                inputs = encoded.to("cuda")
            except Exception as exc:
                raise RuntimeError("Model-specific vision processor/chat template incompatible; pin/test transformers recipe") from exc
            started = time.perf_counter()
            constraint = None
            if args.constrained_decoding:
                if task not in constraint_cache:
                    constraint_cache[task] = contract_constraint(processor, task)
                compiled, make_processor = constraint_cache[task]
                constraint = make_processor(compiled)
            generate_kwargs = {"max_new_tokens": 768, "do_sample": False}
            if constraint is not None:
                generate_kwargs["logits_processor"] = [constraint]
            with torch.inference_mode():
                ids = model.generate(**inputs, **generate_kwargs)
            torch.cuda.synchronize()
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            text = processor.batch_decode(ids[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
            try:
                response = json.loads(text)
            except json.JSONDecodeError:
                response = text  # Never synthesize a fake valid response.
            results.append({"id": row["id"], "model_id": args.model,
                "response": response, "latency_ms": elapsed_ms,
                "cost_usd": None,
                "constrained_decoding": bool(args.constrained_decoding),
                "image_sha256": row["image_sha256"],
                "image_pixels_encoded": True,
                "visual_quality_review": "required"})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create prevents overwriting another reviewer run.
        with args.out.open("x", encoding="utf-8") as handle:
            handle.write("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n")
        print(json.dumps({"mode": "inference_only", "outputs": str(args.out),
                          "samples": len(results), "training_started": False}, indent=2))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(probe())
