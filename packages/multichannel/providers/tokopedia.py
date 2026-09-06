"""Tokopedia — terdaftar, belum dibangun."""

from __future__ import annotations

from ..core.contract import Kesiapan, Provider
from ..core.registry import daftarkan


class Tokopedia(Provider):
    id = "tokopedia"
    nama = "Tokopedia"
    kesiapan = Kesiapan.BELUM_DIBANGUN
    kemampuan = frozenset()
    host = ("fs.tokopedia.net",)

    def status_foundation(self) -> dict:
        return {
            "provider": self.id,
            "kesiapan": self.kesiapan.value,
            "catatan": "Menunggu Shopee mencapai kanari read-only lebih dulu.",
        }


daftarkan(Tokopedia())
