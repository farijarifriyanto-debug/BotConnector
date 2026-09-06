"""Bentuk data baku lintas marketplace.

Inti sistem hanya mengenal bentuk ini. Perbedaan antarmarketplace
diterjemahkan oleh provider, tidak pernah bocor ke sini.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class StatusPesanan(str, Enum):
    """Status baku. Nama asli tiap marketplace dipetakan ke sini."""
    BARU = "baru"
    DIBAYAR = "dibayar"
    DIPROSES = "diproses"
    DIKIRIM = "dikirim"
    SELESAI = "selesai"
    DIBATALKAN = "dibatalkan"
    DIKEMBALIKAN = "dikembalikan"
    TIDAK_DIKENAL = "tidak_dikenal"


@dataclass(frozen=True)
class Uang:
    """Selalu Decimal, tidak pernah float. Uang tidak boleh dibulatkan diam-diam."""
    jumlah: Decimal
    mata_uang: str = "IDR"

    def __post_init__(self):
        if not isinstance(self.jumlah, Decimal):
            raise TypeError("jumlah wajib Decimal, bukan float")


@dataclass(frozen=True)
class BarisPesanan:
    sku_provider: str
    nama: str
    jumlah: int
    harga_satuan: Uang
    sku_internal: Optional[str] = None


@dataclass(frozen=True)
class Pesanan:
    provider: str
    id_provider: str
    id_toko: str
    status: StatusPesanan
    dibuat_pada: datetime
    baris: tuple[BarisPesanan, ...]
    total: Uang
    ongkir: Optional[Uang] = None
    biaya_marketplace: Optional[Uang] = None
    pembeli_nama: Optional[str] = None
    mentah: dict = field(default_factory=dict, repr=False)

    @property
    def kunci_dedup(self) -> str:
        """Satu pesanan hanya boleh masuk sekali, meski ditarik berulang."""
        return f"{self.provider}:{self.id_toko}:{self.id_provider}"


@dataclass(frozen=True)
class Produk:
    provider: str
    id_provider: str
    id_toko: str
    nama: str
    sku_provider: Optional[str] = None
    harga: Optional[Uang] = None
    mentah: dict = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Stok:
    provider: str
    id_toko: str
    sku_provider: str
    tersedia: int
    dipesan: int = 0


@dataclass(frozen=True)
class Settlement:
    """Pencairan dana dari marketplace, dasar rekonsiliasi keuangan."""
    provider: str
    id_provider: str
    id_toko: str
    tanggal: datetime
    bruto: Uang
    potongan: Uang
    neto: Uang
    mentah: dict = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Toko:
    provider: str
    id_toko: str
    nama: str
    wilayah: Optional[str] = None
