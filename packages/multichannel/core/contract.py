"""Kontrak yang wajib dipenuhi setiap provider marketplace.

Menambah marketplace baru berarti menulis satu berkas yang memenuhi
kontrak ini. Inti sistem tidak berubah sama sekali.
"""

from __future__ import annotations

import abc
from enum import Enum
from typing import Iterable

from .models import Pesanan, Produk, Settlement, Stok, Toko
from . import safety


class Kemampuan(str, Enum):
    BACA_TOKO = "baca_toko"
    BACA_PESANAN = "baca_pesanan"
    BACA_PRODUK = "baca_produk"
    BACA_STOK = "baca_stok"
    BACA_SETTLEMENT = "baca_settlement"
    TULIS_STOK = "tulis_stok"
    TULIS_STATUS_PESANAN = "tulis_status_pesanan"


class Kesiapan(str, Enum):
    BELUM_DIBANGUN = "belum_dibangun"
    OFFLINE_FOUNDATION = "offline_foundation"
    KANARI_READ_ONLY = "kanari_read_only"
    PRODUCTION = "production"


class Provider(abc.ABC):
    """Satu marketplace. Wajib menyatakan kemampuan dan kesiapannya."""

    id: str = ""
    nama: str = ""
    kesiapan: Kesiapan = Kesiapan.BELUM_DIBANGUN
    kemampuan: frozenset[Kemampuan] = frozenset()
    host: tuple[str, ...] = ()

    # ---- wajib ----
    @abc.abstractmethod
    def status_foundation(self) -> dict:
        """Bukti keadaan provider: versi, sidik jari, gerbang keselamatan."""

    # ---- baca ----
    def ambil_toko(self) -> Toko:
        raise NotImplementedError(self._pesan(Kemampuan.BACA_TOKO))

    def ambil_pesanan(self, sejak, sampai) -> Iterable[Pesanan]:
        raise NotImplementedError(self._pesan(Kemampuan.BACA_PESANAN))

    def ambil_produk(self) -> Iterable[Produk]:
        raise NotImplementedError(self._pesan(Kemampuan.BACA_PRODUK))

    def ambil_stok(self) -> Iterable[Stok]:
        raise NotImplementedError(self._pesan(Kemampuan.BACA_STOK))

    def ambil_settlement(self, sejak, sampai) -> Iterable[Settlement]:
        raise NotImplementedError(self._pesan(Kemampuan.BACA_SETTLEMENT))

    # ---- tulis: selalu lewat gerbang tambahan ----
    def perbarui_stok(self, sku: str, jumlah: int) -> None:
        safety.periksa_tulis(self.id)
        raise NotImplementedError(self._pesan(Kemampuan.TULIS_STOK))

    # ---- bantu ----
    def _pesan(self, k: Kemampuan) -> str:
        return (f"Provider '{self.id}' belum mendukung {k.value} "
                f"(kesiapan: {self.kesiapan.value}).")

    def dukung(self, k: Kemampuan) -> bool:
        return k in self.kemampuan

    def ringkas(self) -> dict:
        return {
            "id": self.id,
            "nama": self.nama,
            "kesiapan": self.kesiapan.value,
            "kemampuan": sorted(x.value for x in self.kemampuan),
            "host": list(self.host),
        }
