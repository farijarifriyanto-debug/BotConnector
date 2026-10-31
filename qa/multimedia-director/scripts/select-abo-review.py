#!/usr/bin/env python3
"""Select a human-review queue from locally obtained Amazon Berkeley Objects metadata.

NO downloads, no API keys, no training, no automated rights approval.
Accepts .jsonl/.json/.jsonl.gz or an ABO-style .tar/.tar.gz of metadata.
Only reads listing metadata; NEVER extracts image files or tar paths.
"""
import argparse
import gzip
import hashlib
import heapq
import io
import json
from pathlib import Path
import tarfile

SOURCE = "abo"
SOURCE_URL = "https://registry.opendata.aws/amazon-berkeley-objects/"
MAX_MEMBER_BYTES = 192 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
ALLOWED_EXT = (".json", ".jsonl", ".ndjson", ".json.gz", ".jsonl.gz", ".ndjson.gz")


def objects_from_stream(stream, name):
    data = stream.read(MAX_MEMBER_BYTES + 1)
    if len(data) > MAX_MEMBER_BYTES:
        raise ValueError("metadata member too large: " + name)
    if name.endswith(".gz"):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            data = gz.read(MAX_MEMBER_BYTES + 1)
        if len(data) > MAX_MEMBER_BYTES:
            raise ValueError("decompressed metadata too large: " + name)
    text = data.decode("utf-8-sig")
    # Some official listing packs are JSON arrays, others JSONL records.
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError("invalid JSON line in " + name + ":" + str(i)) from exc
                if not isinstance(value, dict):
                    raise ValueError("listing must be JSON object")
                yield value
        return
    if isinstance(parsed, list):
        records = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("listings"), list):
        records = parsed["listings"]
    elif isinstance(parsed, dict):
        records = [parsed]
    else:
        raise ValueError("unsupported metadata JSON payload")
    for value in records:
        if not isinstance(value, dict):
            raise ValueError("listing must be JSON object")
        yield value


def read_listings(file):
    if tarfile.is_tarfile(file):
        consumed = 0
        with tarfile.open(file, "r:*") as archive:
            for member in archive:
                if not member.isfile() or not member.name.lower().endswith(ALLOWED_EXT):
                    continue
                if member.size > MAX_MEMBER_BYTES:
                    raise ValueError("archive metadata file too large")
                consumed += member.size
                if consumed > MAX_ARCHIVE_BYTES:
                    raise ValueError("archive metadata size cap exceeded")
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                with stream:
                    yield from objects_from_stream(stream, member.name.lower())
    else:
        if file.stat().st_size > MAX_MEMBER_BYTES:
            raise ValueError("metadata file too large: use tar shards")
        with file.open("rb") as stream:
            yield from objects_from_stream(stream, file.name.lower())


def clean(value, limit=128):
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def image_ids(row):
    found = []
    for key in ("main_image_id", "mainImageId"):
        value = clean(row.get(key), 96)
        if value:
            found.append(value)
    for key in ("images", "image_ids", "other_image_ids", "other_image_id"):
        values = row.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str):
                found.append(clean(value, 96))
            elif isinstance(value, dict):
                found.append(clean(value.get("image_id") or value.get("imageId") or value.get("id"), 96))
    return list(dict.fromkeys(value for value in found if value))


def candidate(row):
    item_id = clean(row.get("item_id") or row.get("listing_id") or row.get("product_id"), 96)
    images = image_ids(row)
    if not item_id or not images:
        return None
    # Preserve exact source ID; source licenses/attribution still require human checks.
    return {
        "source_id": SOURCE,
        "source_url": SOURCE_URL,
        "item_id": item_id,
        "main_image_id": images[0],
        "other_image_ids": images[1:5],
        "metadata": {
            "item_name": clean(row.get("item_name") or row.get("item_title") or row.get("title"), 200),
            "product_type": clean(row.get("product_type") or row.get("category"), 100),
            "color": clean(row.get("color"), 80),
            "material": clean(row.get("material"), 100),
        },
        "review_status": "pending",
        "asset_license_status": "unverified",
        "commercial_training_allowed": False,
        "third_party_compute_allowed": False,
        "visual_facts_verified": False,
        "split": None,
        "train_ready": False,
    }


def choose(records, count=50, seed="bico-abo-v1"):
    if not 1 <= count <= 1000:
        raise ValueError("count must be 1..1000")
    # bounded deterministic top-k avoids materializing all listing metadata.
    best = []
    seen = set()
    for raw in records:
        item = candidate(raw)
        if item is None:
            continue
        uid = item["item_id"]
        if uid in seen:
            continue
        seen.add(uid)
        rank = int.from_bytes(hashlib.sha256((seed + "\0" + uid).encode()).digest(), "big")
        entry = (-rank, uid, item)
        if len(best) < count:
            heapq.heappush(best, entry)
        elif entry > best[0]:
            heapq.heapreplace(best, entry)
    return [item for _, _, item in sorted(best, reverse=True)]


def main(argv=None):
    p = argparse.ArgumentParser(description="ABO metadata -> unapproved manual review queue")
    p.add_argument("--metadata", type=Path, required=True, help="already-downloaded official metadata, local only")
    p.add_argument("--out", type=Path, required=True, help="new review queue JSONL")
    p.add_argument("--max-items", type=int, default=50)
    p.add_argument("--seed", default="bico-abo-v1")
    args = p.parse_args(argv)
    if not args.metadata.is_file():
        p.error("metadata file not found")
    if args.out.exists():
        p.error("refusing to overwrite output")
    selected = choose(read_listings(args.metadata), args.max_items, args.seed)
    if not selected:
        p.error("no listing contained both item ID and image ID; inspect metadata format")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in selected)
    # Use exclusive create to avoid overwrite races.
    with args.out.open("x", encoding="utf-8") as file:
        file.write(payload)
    print(json.dumps({"candidates": len(selected), "status": "review_only_not_training_ready",
                      "downloaded_images": 0, "training_started": False, "output": str(args.out)}))


if __name__ == "__main__":
    main()
