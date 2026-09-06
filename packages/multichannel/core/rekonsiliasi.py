"""Pemeriksa rekonsiliasi antara Multichannel dan Finance Core.

HANYA MEMBACA. Seluruh permintaan ke Finance Core memakai GET.

Pembagian kebenaran:
  Finance Core  -> nilai persediaan, HPP, piutang, kas, pajak
  Multichannel  -> ketersediaan: reservasi, penyangga, target per kanal

Keduanya menyimpan jumlah barang, dan itu pasti menyimpang suatu saat.
Berkas ini yang menemukannya sebelum jadi masalah.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

API = "http://127.0.0.1:18200"
BATAS_DETIK = 15


class FinanceTidakTerjangkau(Exception):
    pass


def _ambil(jalur: str) -> Any:
    """GET ke Finance Core. Tidak ada metode lain yang disediakan di sini."""
    try:
        req = urllib.request.Request(API + jalur, method="GET")
        with urllib.request.urlopen(req, timeout=BATAS_DETIK) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise FinanceTidakTerjangkau(f"{jalur}: {type(e).__name__}: {e}") from e


# ---------------------------------------------------------------- pembacaan
def kesehatan() -> dict:
    return _ambil("/health")


def saldo_akun() -> dict[str, Decimal]:
    """Kode akun -> saldo debit dikurangi kredit."""
    d = _ambil("/api/v1/reports/trial-balance")
    hasil = {}
    for a in d.get("accounts", []):
        hasil[str(a["code"])] = Decimal(str(a["debit_minus_credit"]))
    return hasil


def neraca_seimbang() -> bool:
    d = _ambil("/api/v1/reports/trial-balance")
    return bool(d.get("balanced")) and Decimal(
        str(d.get("totals", {}).get("difference", "1"))) == 0


def persediaan_finance() -> dict[str, Decimal]:
    """Pengenal item -> jumlah menurut Finance Core."""
    d = _ambil("/api/v1/inventory/balances")
    hasil = {}
    baris = d if isinstance(d, list) else d.get("balances", d.get("items", []))
    for b in baris:
        kunci = str(b.get("sku") or b.get("code") or b.get("item_id") or "")
        jml = b.get("quantity", b.get("qty", b.get("on_hand", 0)))
        if kunci:
            hasil[kunci] = Decimal(str(jml))
    return hasil


def periode(kode_saja: bool = False) -> list[dict]:
    """Daftar periode fiskal apa adanya dari Finance Core.

    PERIODE_FIX_V1 — jawaban memakai period_year dan period_month,
    bukan code atau name.
    """
    d = _ambil("/api/v1/periods")
    baris = d if isinstance(d, list) else d.get("periods", [])
    hasil = []
    for p in baris:
        tahun = p.get("period_year")
        bulan = p.get("period_month")
        kode = f"{tahun}-{int(bulan):02d}" if tahun and bulan else ""
        hasil.append({
            "kode": kode,
            "status": str(p.get("status", "")).upper(),
            "tertutup_pada": p.get("closed_at"),
            "mulai": p.get("starts_on"),
            "selesai": p.get("ends_on"),
            "id": p.get("id"),
        })
    return [x["kode"] for x in hasil] if kode_saja else hasil


def periode_terbuka() -> list[str]:
    """Kode periode yang masih OPEN, contoh: 2026-08."""
    return [p["kode"] for p in periode()
            if p["status"] == "OPEN" and not p["tertutup_pada"]]


def periode_terbuka_pada(kode: str) -> bool:
    """Benar bila periode tertentu masih boleh dibukukan."""
    return kode in periode_terbuka()


# ---------------------------------------------------------------- hasil
@dataclass
class Selisih:
    perkara: str
    kunci: str
    multichannel: Any
    finance: Any

    @property
    def cocok(self) -> bool:
        return self.multichannel == self.finance

    def __str__(self) -> str:
        tanda = "cocok" if self.cocok else "SELISIH"
        return (f"  {tanda:<8} {self.perkara:<14} {self.kunci:<20}"
                f"multichannel={self.multichannel}  finance={self.finance}")


def bandingkan_stok(buku_stok, peta_item: dict[str, str]) -> list[Selisih]:
    """peta_item: SKU internal -> pengenal item di Finance Core."""
    fin = persediaan_finance()
    hasil = []
    for sku, id_finance in peta_item.items():
        hasil.append(Selisih(
            perkara="stok",
            kunci=sku,
            multichannel=Decimal(buku_stok.fisik(sku)),
            finance=fin.get(id_finance, Decimal("-1")),
        ))
    return hasil


def bandingkan_piutang(buku_pembantu, kode_akun_piutang: str = "1201") -> Selisih:
    """Piutang marketplace di connector vs saldo GL."""
    from .finance import Akun
    saldo = saldo_akun()
    return Selisih(
        perkara="piutang",
        kunci=kode_akun_piutang,
        multichannel=buku_pembantu.saldo(Akun.PIUTANG_MARKETPLACE),
        finance=saldo.get(kode_akun_piutang, Decimal("-1")),
    )


def laporan(selisih: list[Selisih]) -> str:
    baris = ["  hasil                perkara       kunci               nilai"]
    baris.append("  " + "-" * 76)
    baris += [str(s) for s in selisih]
    tidak = [s for s in selisih if not s.cocok]
    baris.append("  " + "-" * 76)
    baris.append(f"  {len(selisih) - len(tidak)} cocok, {len(tidak)} selisih")
    if tidak:
        baris.append("  Selisih WAJIB ditelusuri sebelum tutup periode.")
    return "\n".join(baris)
