"""Finance Core — pesanan marketplace menjadi pembukuan.

Kaidah utamanya: pesanan bukan kas. Yang lahir dari pesanan adalah
piutang ke marketplace. Kas baru muncul saat settlement cair.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Akun(str, Enum):
    KAS = "kas"
    PIUTANG_MARKETPLACE = "piutang_marketplace"
    PENJUALAN = "penjualan"
    BEBAN_FEE = "beban_fee_marketplace"
    RETUR_PENJUALAN = "retur_penjualan"
    SELISIH_SETTLEMENT = "selisih_settlement"


NORMAL_DEBIT = {Akun.KAS, Akun.PIUTANG_MARKETPLACE,
                Akun.BEBAN_FEE, Akun.RETUR_PENJUALAN,
                Akun.SELISIH_SETTLEMENT}


class JurnalGanda(Exception):
    pass


class JurnalTidakSeimbang(Exception):
    pass


@dataclass(frozen=True)
class Baris:
    akun: Akun
    debit: Decimal = Decimal("0")
    kredit: Decimal = Decimal("0")

    def __post_init__(self):
        for n in (self.debit, self.kredit):
            if not isinstance(n, Decimal):
                raise TypeError("nilai wajib Decimal")
        if self.debit and self.kredit:
            raise ValueError("satu baris hanya boleh debit atau kredit")


@dataclass(frozen=True)
class Jurnal:
    tanggal: datetime
    keterangan: str
    kunci: str
    baris: tuple[Baris, ...]
    provider: str = ""
    id_toko: str = ""

    def __post_init__(self):
        d = sum((b.debit for b in self.baris), Decimal("0"))
        k = sum((b.kredit for b in self.baris), Decimal("0"))
        if d != k:
            raise JurnalTidakSeimbang(f"debit {d} != kredit {k}")


class BukuBesar:
    def __init__(self) -> None:
        self._jurnal: list[Jurnal] = []
        self._kunci: set[str] = set()

    def catat(self, j: Jurnal) -> None:
        if j.kunci in self._kunci:
            raise JurnalGanda(f"jurnal '{j.kunci}' sudah pernah dicatat")
        self._kunci.add(j.kunci)
        self._jurnal.append(j)

    def catat_bila_baru(self, j: Jurnal) -> bool:
        try:
            self.catat(j)
            return True
        except JurnalGanda:
            return False

    def saldo(self, akun: Akun) -> Decimal:
        d = sum((b.debit for j in self._jurnal for b in j.baris if b.akun is akun),
                Decimal("0"))
        k = sum((b.kredit for j in self._jurnal for b in j.baris if b.akun is akun),
                Decimal("0"))
        return d - k if akun in NORMAL_DEBIT else k - d

    def neraca_percobaan(self) -> dict:
        d = sum((b.debit for j in self._jurnal for b in j.baris), Decimal("0"))
        k = sum((b.kredit for j in self._jurnal for b in j.baris), Decimal("0"))
        return {"debit": d, "kredit": k, "seimbang": d == k}

    def laporan(self) -> str:
        baris = ["  akun                        saldo"]
        baris.append("  " + "-" * 42)
        for a in Akun:
            baris.append(f"  {a.value:<28}{self.saldo(a):>14,}")
        n = self.neraca_percobaan()
        baris.append("  " + "-" * 42)
        baris.append(f"  neraca percobaan: debit {n['debit']:,} "
                     f"kredit {n['kredit']:,} "
                     f"{'SEIMBANG' if n['seimbang'] else 'TIDAK SEIMBANG'}")
        return "\n".join(baris)


# ---------------------------------------------------------------- aturan
def jurnal_pesanan(pesanan) -> Jurnal:
    """Pesanan lunas: piutang lahir, penjualan diakui, fee dibebankan."""
    total = pesanan.total.jumlah
    fee = pesanan.biaya_marketplace.jumlah if pesanan.biaya_marketplace \
        else Decimal("0")
    return Jurnal(
        tanggal=pesanan.dibuat_pada,
        keterangan=f"Pesanan {pesanan.provider} {pesanan.id_provider}",
        kunci=f"jurnal:pesanan:{pesanan.kunci_dedup}",
        provider=pesanan.provider,
        id_toko=pesanan.id_toko,
        baris=(
            Baris(Akun.PIUTANG_MARKETPLACE, debit=total - fee),
            Baris(Akun.BEBAN_FEE, debit=fee),
            Baris(Akun.PENJUALAN, kredit=total),
        ),
    )


def jurnal_settlement(settlement, piutang_diharapkan: Decimal) -> Jurnal:
    """Settlement cair: kas masuk, piutang lunas, selisih dicatat terpisah."""
    neto = settlement.neto.jumlah
    selisih = piutang_diharapkan - neto
    baris = [Baris(Akun.KAS, debit=neto)]
    if selisih > 0:
        baris.append(Baris(Akun.SELISIH_SETTLEMENT, debit=selisih))
    elif selisih < 0:
        baris.append(Baris(Akun.SELISIH_SETTLEMENT, kredit=-selisih))
    baris.append(Baris(Akun.PIUTANG_MARKETPLACE, kredit=piutang_diharapkan))
    return Jurnal(
        tanggal=settlement.tanggal,
        keterangan=f"Settlement {settlement.provider} {settlement.id_provider}",
        kunci=f"jurnal:settlement:{settlement.provider}:{settlement.id_provider}",
        provider=settlement.provider,
        id_toko=settlement.id_toko,
        baris=tuple(baris),
    )


def jurnal_retur(pesanan) -> Jurnal:
    total = pesanan.total.jumlah
    fee = pesanan.biaya_marketplace.jumlah if pesanan.biaya_marketplace \
        else Decimal("0")
    return Jurnal(
        tanggal=pesanan.dibuat_pada,
        keterangan=f"Retur {pesanan.provider} {pesanan.id_provider}",
        kunci=f"jurnal:retur:{pesanan.kunci_dedup}",
        provider=pesanan.provider,
        id_toko=pesanan.id_toko,
        baris=(
            Baris(Akun.RETUR_PENJUALAN, debit=total),
            Baris(Akun.PIUTANG_MARKETPLACE, kredit=total - fee),
            Baris(Akun.BEBAN_FEE, kredit=fee),
        ),
    )
