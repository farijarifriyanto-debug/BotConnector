"""Gerbang penerimaan Stock Core dan Finance Core. Tanpa jaringan."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from botconnector_multichannel.core.models import (          # noqa: E402
    BarisPesanan, Pesanan, Settlement, StatusPesanan, Uang)
from botconnector_multichannel.core.stock import (           # noqa: E402
    BukuStok, Gerakan, JenisGerakan, PetaSKU, StokTidakCukup)
from botconnector_multichannel.core import finance as fin    # noqa: E402

T0 = datetime(2026, 8, 13, 8, 0)
lulus = gagal = 0


def uji(nama, fn):
    global lulus, gagal
    try:
        fn()
        print(f"  [OK]    {nama}")
        lulus += 1
    except Exception as e:
        print(f"  [GAGAL] {nama}: {type(e).__name__}: {e}")
        gagal += 1


def buku_awal(jumlah=10):
    b = BukuStok()
    b.catat(Gerakan("SKU-A", JenisGerakan.MASUK, jumlah, "beli-1", T0, "pembelian"))
    return b


print("\n=== STOCK CORE ===")


def _dasar():
    b = buku_awal()
    assert b.fisik("SKU-A") == 10, b.fisik("SKU-A")
    assert b.tersedia("SKU-A") == 10


uji("stok masuk terhitung", _dasar)


def _reservasi():
    b = buku_awal()
    b.pesan("SKU-A", 2, "shopee:t1:001", T0, "shopee")
    assert b.fisik("SKU-A") == 10, "fisik belum berubah sebelum dikirim"
    assert b.tersedia("SKU-A") == 8, b.tersedia("SKU-A")


uji("pesanan mengurangi tersedia, bukan fisik", _reservasi)


def _kirim():
    b = buku_awal()
    b.pesan("SKU-A", 2, "shopee:t1:001", T0, "shopee")
    b.kirim("SKU-A", 2, "kirim:shopee:t1:001", T0 + timedelta(hours=5))
    assert b.fisik("SKU-A") == 8, b.fisik("SKU-A")
    assert b.reservasi_terbuka("SKU-A") == 0
    assert b.tersedia("SKU-A") == 8


uji("pengiriman menutup reservasi", _kirim)


def _oversell():
    b = buku_awal(3)
    b.pesan("SKU-A", 2, "shopee:t1:001", T0, "shopee")
    try:
        b.pesan("SKU-A", 2, "tiktok:t9:777", T0, "tiktok_shop")
    except StokTidakCukup:
        return
    raise AssertionError("kanal kedua seharusnya ditolak")


uji("kelebihan jual antarkanal dicegah", _oversell)


def _penyangga():
    b = buku_awal(5)
    b.atur_penyangga("SKU-A", 2)
    assert b.tersedia("SKU-A") == 3, b.tersedia("SKU-A")


uji("penyangga menahan unit terakhir", _penyangga)


def _ganda():
    b = buku_awal()
    assert b.pesan("SKU-A", 2, "shopee:t1:001", T0) is True
    assert b.pesan("SKU-A", 2, "shopee:t1:001", T0) is False
    assert b.tersedia("SKU-A") == 8, "penarikan ulang tidak boleh menghitung dua kali"


uji("pesanan ganda tidak dihitung dua kali", _ganda)


def _batal():
    b = buku_awal()
    b.pesan("SKU-A", 3, "shopee:t1:002", T0)
    b.batalkan("SKU-A", 3, "batal:shopee:t1:002", T0)
    assert b.tersedia("SKU-A") == 10


uji("pembatalan mengembalikan ketersediaan", _batal)


def _retur():
    b = buku_awal()
    b.pesan("SKU-A", 2, "s:1", T0)
    b.kirim("SKU-A", 2, "k:1", T0)
    b.catat(Gerakan("SKU-A", JenisGerakan.RETUR, 2, "r:1", T0, "retur pembeli"))
    assert b.fisik("SKU-A") == 10


uji("retur mengembalikan stok fisik", _retur)


def _opname():
    b = buku_awal()
    b.catat(Gerakan("SKU-A", JenisGerakan.PENYESUAIAN, -1, "opname:1", T0,
                    "stok opname", "satu unit rusak"))
    assert b.fisik("SKU-A") == 9


uji("stok opname boleh negatif", _opname)


def _telusur():
    b = buku_awal()
    b.pesan("SKU-A", 2, "s:1", T0)
    teks = b.jelaskan("SKU-A")
    assert "masuk" in teks and "reservasi" in teks and "tersedia 8" in teks


uji("setiap angka dapat dijelaskan", _telusur)


def _sinkron():
    b = buku_awal(10)
    p = PetaSKU()
    p.daftarkan("shopee", "t1", "SHP-A", "SKU-A")
    p.daftarkan("tiktok_shop", "t9", "TT-A", "SKU-A")
    b.pesan("SKU-A", 3, "s:1", T0)
    r = b.rencana_sinkron(p, "SKU-A")
    assert len(r) == 2, r
    assert all(x["jumlah_target"] == 7 for x in r), r


uji("rencana sinkron sama untuk semua kanal", _sinkron)

print("\n=== FINANCE CORE ===")


def pesanan(total="100000", fee="12000", id_p="2408130001"):
    return Pesanan(
        provider="shopee", id_provider=id_p, id_toko="t1",
        status=StatusPesanan.DIBAYAR, dibuat_pada=T0,
        baris=(BarisPesanan("SHP-A", "Barang A", 1, Uang(Decimal(total))),),
        total=Uang(Decimal(total)),
        biaya_marketplace=Uang(Decimal(fee)))


def _pesanan_bukan_kas():
    bb = fin.BukuBesar()
    bb.catat(fin.jurnal_pesanan(pesanan()))
    assert bb.saldo(fin.Akun.KAS) == 0, "pesanan tidak boleh menambah kas"
    assert bb.saldo(fin.Akun.PIUTANG_MARKETPLACE) == Decimal("88000")
    assert bb.saldo(fin.Akun.PENJUALAN) == Decimal("100000")
    assert bb.saldo(fin.Akun.BEBAN_FEE) == Decimal("12000")


uji("pesanan menjadi piutang, bukan kas", _pesanan_bukan_kas)


def _seimbang():
    bb = fin.BukuBesar()
    bb.catat(fin.jurnal_pesanan(pesanan()))
    assert bb.neraca_percobaan()["seimbang"]


uji("neraca percobaan seimbang", _seimbang)


def _jurnal_ganda():
    bb = fin.BukuBesar()
    p = pesanan()
    assert bb.catat_bila_baru(fin.jurnal_pesanan(p)) is True
    assert bb.catat_bila_baru(fin.jurnal_pesanan(p)) is False
    assert bb.saldo(fin.Akun.PENJUALAN) == Decimal("100000")


uji("pesanan ganda tidak dibukukan dua kali", _jurnal_ganda)


def _settlement_pas():
    bb = fin.BukuBesar()
    bb.catat(fin.jurnal_pesanan(pesanan()))
    s = Settlement(provider="shopee", id_provider="ST-1", id_toko="t1",
                   tanggal=T0 + timedelta(days=14),
                   bruto=Uang(Decimal("100000")),
                   potongan=Uang(Decimal("12000")),
                   neto=Uang(Decimal("88000")))
    bb.catat(fin.jurnal_settlement(s, Decimal("88000")))
    assert bb.saldo(fin.Akun.KAS) == Decimal("88000")
    assert bb.saldo(fin.Akun.PIUTANG_MARKETPLACE) == 0, "piutang harus lunas"
    assert bb.saldo(fin.Akun.SELISIH_SETTLEMENT) == 0


uji("settlement melunasi piutang menjadi kas", _settlement_pas)


def _settlement_selisih():
    bb = fin.BukuBesar()
    bb.catat(fin.jurnal_pesanan(pesanan()))
    s = Settlement(provider="shopee", id_provider="ST-2", id_toko="t1",
                   tanggal=T0 + timedelta(days=14),
                   bruto=Uang(Decimal("100000")),
                   potongan=Uang(Decimal("14500")),
                   neto=Uang(Decimal("85500")))
    bb.catat(fin.jurnal_settlement(s, Decimal("88000")))
    assert bb.saldo(fin.Akun.SELISIH_SETTLEMENT) == Decimal("2500"), \
        bb.saldo(fin.Akun.SELISIH_SETTLEMENT)
    assert bb.saldo(fin.Akun.PIUTANG_MARKETPLACE) == 0
    assert bb.neraca_percobaan()["seimbang"]


uji("potongan tak terduga masuk akun selisih", _settlement_selisih)


def _retur_fin():
    bb = fin.BukuBesar()
    p = pesanan()
    bb.catat(fin.jurnal_pesanan(p))
    bb.catat(fin.jurnal_retur(p))
    assert bb.saldo(fin.Akun.PIUTANG_MARKETPLACE) == 0
    assert bb.saldo(fin.Akun.BEBAN_FEE) == 0
    assert bb.saldo(fin.Akun.RETUR_PENJUALAN) == Decimal("100000")
    assert bb.neraca_percobaan()["seimbang"]


uji("retur membalik piutang dan fee", _retur_fin)


def _tak_seimbang_ditolak():
    try:
        fin.Jurnal(tanggal=T0, keterangan="salah", kunci="x",
                   baris=(fin.Baris(fin.Akun.KAS, debit=Decimal("100")),))
    except fin.JurnalTidakSeimbang:
        return
    raise AssertionError("jurnal timpang seharusnya ditolak")


uji("jurnal tidak seimbang ditolak", _tak_seimbang_ditolak)


def _float_ditolak():
    try:
        fin.Baris(fin.Akun.KAS, debit=100.5)
    except TypeError:
        return
    raise AssertionError("float seharusnya ditolak")


uji("nilai float ditolak", _float_ditolak)

print("\n=== CONTOH ALUR PENUH ===")
bs = BukuStok()
bs.catat(Gerakan("SKU-A", JenisGerakan.MASUK, 10, "beli", T0, "pembelian awal"))
bb = fin.BukuBesar()
p1 = pesanan(total="100000", fee="12000", id_p="A1")
bs.pesan("SKU-A", 2, "stok:" + p1.kunci_dedup, T0, "shopee")
bb.catat(fin.jurnal_pesanan(p1))
bs.kirim("SKU-A", 2, "kirim:" + p1.kunci_dedup, T0 + timedelta(hours=6))
st = Settlement(provider="shopee", id_provider="ST-A", id_toko="t1",
                tanggal=T0 + timedelta(days=14),
                bruto=Uang(Decimal("100000")), potongan=Uang(Decimal("12000")),
                neto=Uang(Decimal("88000")))
bb.catat(fin.jurnal_settlement(st, Decimal("88000")))
print(bs.jelaskan("SKU-A"))
print()
print(bb.laporan())

print(f"\n  Lulus: {lulus}   Gagal: {gagal}\n")
sys.exit(1 if gagal else 0)
