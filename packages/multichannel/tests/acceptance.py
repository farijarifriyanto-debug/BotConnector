"""Gerbang penerimaan lapisan multi-marketplace.

Menguji bahwa kontraknya benar DAN bahwa keselamatannya tidak bisa
ditembus. Tidak menyentuh jaringan.
"""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from botconnector_multichannel.core import registry, safety            # noqa: E402
from botconnector_multichannel.core.contract import Kemampuan, Kesiapan  # noqa: E402
from botconnector_multichannel.core.models import (                     # noqa: E402
    BarisPesanan, Pesanan, StatusPesanan, Uang)

registry.muat_bawaan()

lulus, gagal = 0, 0


def uji(nama, fn):
    global lulus, gagal
    try:
        fn()
        print(f"  [OK]    {nama}")
        lulus += 1
    except AssertionError as e:
        print(f"  [GAGAL] {nama}: {e}")
        gagal += 1
    except Exception as e:
        print(f"  [GAGAL] {nama}: {type(e).__name__}: {e}")
        gagal += 1


print("\n=== KONTRAK ===")
uji("tiga provider terdaftar",
    lambda: (_ for _ in ()).throw(AssertionError(f"jumlah {len(registry.semua())}"))
    if len(registry.semua()) != 3 else None)
uji("shopee dikenali", lambda: registry.ambil("shopee"))
uji("tiktok dikenali", lambda: registry.ambil("tiktok_shop"))
uji("tokopedia dikenali", lambda: registry.ambil("tokopedia"))


def _tak_dikenal():
    try:
        registry.ambil("bukalapak")
    except KeyError:
        return
    raise AssertionError("provider asing seharusnya ditolak")


uji("provider asing ditolak", _tak_dikenal)


def _daftar_ganda():
    try:
        registry.daftarkan(registry.ambil("shopee"))
    except ValueError:
        return
    raise AssertionError("pendaftaran ganda seharusnya ditolak")


uji("pendaftaran ganda ditolak", _daftar_ganda)

print("\n=== KESELAMATAN ===")


def _jaringan_tertutup():
    try:
        safety.periksa_jaringan("shopee", "partner.shopeemobile.com")
    except safety.GerbangTertutup:
        return
    raise AssertionError("jaringan seharusnya masih tertutup")


uji("jaringan bawaan MATI", _jaringan_tertutup)


def _tulis_tertutup():
    try:
        registry.ambil("shopee").perbarui_stok("SKU1", 5)
    except safety.GerbangTertutup:
        return
    except NotImplementedError:
        raise AssertionError("gerbang tulis dilewati sebelum diperiksa")
    raise AssertionError("operasi tulis seharusnya ditolak")


uji("operasi tulis MATI", _tulis_tertutup)
uji("semua gerbang bawaan mati",
    lambda: None if not any(safety.ringkasan().values())
    else (_ for _ in ()).throw(AssertionError(str(safety.ringkasan()))))

print("\n=== KEMAMPUAN ===")


def _baca_ditolak():
    try:
        registry.ambil("shopee").ambil_pesanan(None, None)
    except NotImplementedError:
        return
    raise AssertionError("baca pesanan seharusnya belum tersedia")


uji("shopee belum boleh baca pesanan", _baca_ditolak)
uji("tidak ada provider siap baca pesanan",
    lambda: None if not registry.yang_siap(Kemampuan.BACA_PESANAN)
    else (_ for _ in ()).throw(AssertionError("ada yang menyatakan siap")))
uji("shopee berstatus offline_foundation",
    lambda: None if registry.ambil("shopee").kesiapan == Kesiapan.OFFLINE_FOUNDATION
    else (_ for _ in ()).throw(AssertionError("kesiapan salah")))

print("\n=== BENTUK DATA ===")


def _uang_float_ditolak():
    try:
        Uang(1000.5)
    except TypeError:
        return
    raise AssertionError("float seharusnya ditolak")


uji("uang menolak float", _uang_float_ditolak)


def _dedup():
    p = Pesanan(
        provider="shopee", id_provider="2408130001", id_toko="toko1",
        status=StatusPesanan.DIBAYAR, dibuat_pada=datetime(2026, 8, 13),
        baris=(BarisPesanan("SKU-A", "Barang A", 2, Uang(Decimal("15000"))),),
        total=Uang(Decimal("30000")))
    if p.kunci_dedup != "shopee:toko1:2408130001":
        raise AssertionError(p.kunci_dedup)


uji("kunci dedup terbentuk benar", _dedup)
uji("status tak dikenal punya tempat",
    lambda: StatusPesanan("tidak_dikenal"))

print("\n=== MATRIKS KEMAMPUAN ===")
print(registry.matriks())

print(f"\n  Lulus: {lulus}   Gagal: {gagal}\n")
sys.exit(1 if gagal else 0)
