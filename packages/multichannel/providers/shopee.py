"""Adaptor Shopee.

Membungkus foundation offline yang sudah DIBEKUKAN. Berkas foundation
tidak diimpor sebagai kode aktif dan tidak diubah sedikit pun; yang
dibaca hanya keadaannya sebagai bukti.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ..core import safety
from ..core.contract import Kemampuan, Kesiapan, Provider
from ..core.registry import daftarkan

# Config-driven, not a hardcoded deployment path: override with
# SHOPEE_OFFLINE_FOUNDATION_ROOT in any environment where this optional
# foundation artifact lives somewhere other than the production default.
# Absence of this path is expected and safe — it only ever changes
# `foundation_ditemukan`/`rilis_aktif` in status_foundation(); `kemampuan`
# stays frozenset() (no capability) regardless.
AKAR = Path(
    os.environ.get(
        "SHOPEE_OFFLINE_FOUNDATION_ROOT",
        "/opt/botconnector-shopee-real-provider",
    )
)
POINTER = AKAR / "current-offline-shopee-provider-composition"


class Shopee(Provider):
    id = "shopee"
    nama = "Shopee"
    kesiapan = Kesiapan.OFFLINE_FOUNDATION
    kemampuan = frozenset()          # kosong sampai kanari read-only lulus
    host = ("partner.shopeemobile.com",)

    def status_foundation(self) -> dict:
        ada = POINTER.exists()
        rilis = ""
        try:
            rilis = str(POINTER.resolve()) if ada else ""
        except Exception:
            pass
        return {
            "provider": self.id,
            "kesiapan": self.kesiapan.value,
            "foundation_ditemukan": ada,
            "rilis_aktif": rilis,
            "beku": True,
            "gerbang": safety.ringkasan(),
            "catatan": (
                "Foundation offline dibekukan. Kemampuan baca baru "
                "dinyalakan setelah Production Activation Contract dan "
                "kanari read-only lulus."
            ),
        }


daftarkan(Shopee())
