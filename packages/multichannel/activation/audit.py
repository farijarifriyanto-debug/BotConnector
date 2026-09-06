"""Jejak audit yang tidak pernah membocorkan rahasia."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .kontrak import muat

# pola yang isinya wajib disamarkan bila sempat lewat
KUNCI_RAHASIA = re.compile(
    r"(partner[_-]?key|access[_-]?token|refresh[_-]?token|sign|signature|"
    r"secret|password|authorization)", re.I)


def samarkan(obj):
    """Ganti nilai bidang sensitif dengan penanda."""
    if isinstance(obj, dict):
        return {k: ("<disamarkan>" if KUNCI_RAHASIA.search(str(k))
                    else samarkan(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [samarkan(x) for x in obj]
    if isinstance(obj, str) and len(obj) > 64:
        return obj[:16] + f"...<{len(obj)} karakter>"
    return obj


def catat(peristiwa: str, rincian: dict) -> None:
    berkas = Path(str(muat().get("berkas_audit", "")))
    baris = {
        "waktu": datetime.now(timezone.utc).isoformat(),
        "peristiwa": peristiwa,
        **samarkan(rincian),
    }
    try:
        berkas.parent.mkdir(parents=True, exist_ok=True)
        with berkas.open("a", encoding="utf-8") as f:
            f.write(json.dumps(baris, ensure_ascii=False) + "\n")
    except Exception:
        pass          # audit tidak boleh menjatuhkan layanan


def baca_terakhir(n: int = 20) -> list[dict]:
    berkas = Path(str(muat().get("berkas_audit", "")))
    if not berkas.is_file():
        return []
    baris = berkas.read_text(encoding="utf-8").strip().split("\n")
    hasil = []
    for b in baris[-n:]:
        try:
            hasil.append(json.loads(b))
        except Exception:
            pass
    return hasil
