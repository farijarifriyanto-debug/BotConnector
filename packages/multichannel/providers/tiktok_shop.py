"""TikTok Shop — terdaftar, belum dibangun.

Sengaja hadir sebagai kerangka agar rencana multi-marketplace terlihat
dan terukur, tanpa memberi kesan sudah berfungsi.
"""

from __future__ import annotations

from ..core.contract import Kesiapan, Provider
from ..core.registry import daftarkan


class TikTokShop(Provider):
    id = "tiktok_shop"
    nama = "TikTok Shop"
    kesiapan = Kesiapan.BELUM_DIBANGUN
    kemampuan = frozenset()
    host = ("open-api.tiktokglobalshop.com",)

    def status_foundation(self) -> dict:
        return {
            "provider": self.id,
            "kesiapan": self.kesiapan.value,
            "catatan": "Menunggu Shopee mencapai kanari read-only lebih dulu.",
        }


daftarkan(TikTokShop())
