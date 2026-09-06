"""Perbatasan menuju sistem akuntansi.

Connector menyimpan detail per pesanan. Sistem akuntansi menerima
ringkasan harian. Satu ringkasan hanya boleh terkirim satu kali.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from .finance import Akun, Baris, Jurnal, NORMAL_DEBIT

BERKAS_PETA = Path("/etc/botconnector-akun.json")


class AkunBelumDipetakan(Exception):
    """Sengaja keras: lebih baik gagal daripada salah akun."""


class StatusPosting(str, Enum):
    SIAP = "siap"
    TERKIRIM = "terkirim"
    GAGAL = "gagal"


def peta_akun() -> dict:
    try:
        if BERKAS_PETA.exists():
            return json.loads(BERKAS_PETA.read_text(encoding="utf-8")).get("peta", {})
    except Exception:
        pass
    return {}


def kode_akun(a: Akun) -> str:
    kode = (peta_akun().get(a.value) or "").strip()
    if not kode:
        raise AkunBelumDipetakan(
            f"Akun '{a.value}' belum punya pasangan kode di {BERKAS_PETA}. "
            "Isi dulu sebelum mengekspor."
        )
    return kode


# ---------------------------------------------------------------- ringkasan
@dataclass(frozen=True)
class RingkasanHarian:
    tanggal: date
    provider: str
    id_toko: str
    jumlah_jurnal: int
    baris: tuple[Baris, ...]

    @property
    def kunci(self) -> str:
        return f"posting:{self.provider}:{self.id_toko}:{self.tanggal:%Y%m%d}"

    def total_debit(self) -> Decimal:
        return sum((b.debit for b in self.baris), Decimal("0"))

    def total_kredit(self) -> Decimal:
        return sum((b.kredit for b in self.baris), Decimal("0"))

    def seimbang(self) -> bool:
        return self.total_debit() == self.total_kredit()


def ringkas_harian(jurnal: list[Jurnal]) -> list[RingkasanHarian]:
    """Gabungkan jurnal per hari, per marketplace, per toko.

    Nilainya tidak boleh berubah; hanya jumlah barisnya yang menyusut.
    """
    kelompok: dict[tuple, list[Jurnal]] = defaultdict(list)
    for j in jurnal:
        kelompok[(j.tanggal.date(), j.provider, j.id_toko)].append(j)

    hasil = []
    for (tgl, prov, toko), daftar in sorted(kelompok.items(), key=lambda x: str(x[0])):
        per_akun: dict[Akun, Decimal] = defaultdict(lambda: Decimal("0"))
        for j in daftar:
            for b in j.baris:
                per_akun[b.akun] += b.debit - b.kredit

        baris = []
        for akun in Akun:                       # urutan tetap agar dapat diulang
            n = per_akun.get(akun, Decimal("0"))
            if n == 0:
                continue
            if n > 0:
                baris.append(Baris(akun, debit=n))
            else:
                baris.append(Baris(akun, kredit=-n))

        hasil.append(RingkasanHarian(
            tanggal=tgl, provider=prov, id_toko=toko,
            jumlah_jurnal=len(daftar), baris=tuple(baris),
        ))
    return hasil


# ---------------------------------------------------------------- catatan kirim
@dataclass
class Posting:
    ringkasan: RingkasanHarian
    status: StatusPosting = StatusPosting.SIAP
    id_eksternal: str = ""
    pesan: str = ""
    waktu: datetime | None = None


class BukuPosting:
    """Mencatat ringkasan mana yang sudah masuk ke sistem akuntansi."""

    def __init__(self) -> None:
        self._posting: dict[str, Posting] = {}

    def siapkan(self, r: RingkasanHarian) -> bool:
        """False bila ringkasan hari itu sudah pernah disiapkan."""
        if r.kunci in self._posting:
            return False
        if not r.seimbang():
            raise ValueError(f"ringkasan {r.kunci} tidak seimbang")
        self._posting[r.kunci] = Posting(ringkasan=r)
        return True

    def tandai_terkirim(self, kunci: str, id_eksternal: str,
                        waktu: datetime | None = None) -> None:
        p = self._posting[kunci]
        if p.status is StatusPosting.TERKIRIM:
            raise ValueError(f"{kunci} sudah terkirim sebagai {p.id_eksternal}")
        p.status = StatusPosting.TERKIRIM
        p.id_eksternal = id_eksternal
        p.waktu = waktu or datetime.now()

    def tandai_gagal(self, kunci: str, pesan: str) -> None:
        p = self._posting[kunci]
        p.status = StatusPosting.GAGAL
        p.pesan = pesan

    def tertunda(self) -> list[Posting]:
        return [p for p in self._posting.values()
                if p.status is not StatusPosting.TERKIRIM]

    def semua(self) -> list[Posting]:
        return list(self._posting.values())


# ---------------------------------------------------------------- ekspor
def ekspor(r: RingkasanHarian) -> dict:
    """Bentuk netral, siap diterjemahkan ke API akuntansi mana pun."""
    baris = []
    for b in r.baris:
        baris.append({
            "akun_internal": b.akun.value,
            "kode_akun": kode_akun(b.akun),      # menolak bila belum dipetakan
            "debit": str(b.debit),
            "kredit": str(b.kredit),
        })
    return {
        "kunci": r.kunci,
        "tanggal": r.tanggal.isoformat(),
        "provider": r.provider,
        "id_toko": r.id_toko,
        "keterangan": (f"Ringkasan {r.provider} {r.id_toko} "
                       f"{r.tanggal:%d/%m/%Y} ({r.jumlah_jurnal} transaksi)"),
        "baris": baris,
        "total_debit": str(r.total_debit()),
        "total_kredit": str(r.total_kredit()),
    }


def ekspor_banyak(daftar: list[RingkasanHarian]) -> str:
    return json.dumps([ekspor(r) for r in daftar], ensure_ascii=False, indent=2)


def periksa_pemetaan() -> dict:
    """Akun mana yang sudah siap dan mana yang belum."""
    p = peta_akun()
    return {a.value: bool((p.get(a.value) or "").strip()) for a in Akun}
