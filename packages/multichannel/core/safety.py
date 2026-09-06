"""Sakelar keselamatan. Bawaannya semua MATI.

Tidak ada satu pun panggilan jaringan yang boleh terjadi kecuali
seluruh gerbang di berkas pengaturan dinyalakan secara eksplisit.
"""

from __future__ import annotations

import json
from pathlib import Path

BERKAS = Path("/etc/botconnector-multichannel.json")

BAWAAN = {
    "NETWORK_ENABLED": False,
    "REAL_CREDENTIAL_ENABLED": False,
    "REAL_OAUTH_ENABLED": False,
    "PRODUCTION_ACTIVATION_APPROVED": False,
    "WRITE_OPERATIONS_APPROVED": False,
    "provider_diizinkan": [],
    "host_diizinkan": {},
}


class GerbangTertutup(RuntimeError):
    """Dilempar bila ada yang mencoba menembus sakelar keselamatan."""


def pengaturan() -> dict:
    data = dict(BAWAAN)
    try:
        if BERKAS.exists():
            data.update(json.loads(BERKAS.read_text(encoding="utf-8")))
    except Exception:
        pass
    return data


def periksa_jaringan(provider: str, host: str = "") -> None:
    cfg = pengaturan()
    if not cfg.get("NETWORK_ENABLED"):
        raise GerbangTertutup(
            "NETWORK_ENABLED=NO. Tidak ada panggilan jaringan yang diizinkan."
        )
    if provider not in cfg.get("provider_diizinkan", []):
        raise GerbangTertutup(f"Provider '{provider}' belum diizinkan.")
    if host:
        izin = cfg.get("host_diizinkan", {}).get(provider, [])
        if host not in izin:
            raise GerbangTertutup(f"Host '{host}' di luar daftar izin {provider}.")


def periksa_tulis(provider: str) -> None:
    cfg = pengaturan()
    if not cfg.get("WRITE_OPERATIONS_APPROVED"):
        raise GerbangTertutup(
            "WRITE_OPERATIONS_APPROVED=NO. Baca dahulu, tulis menyusul."
        )
    periksa_jaringan(provider)


def ringkasan() -> dict:
    cfg = pengaturan()
    return {k: cfg.get(k) for k in BAWAAN if isinstance(BAWAAN[k], bool)}
