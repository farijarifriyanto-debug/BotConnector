"""Gerbang penerimaan rekonsiliasi. Sebagian menyentuh Finance Core, tetapi
hanya membaca."""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from botconnector_multichannel.core import posting as pos      # noqa: E402
from botconnector_multichannel.core import rekonsiliasi as rek  # noqa: E402
from botconnector_multichannel.core.stock import (              # noqa: E402
    BukuStok, Gerakan, JenisGerakan)

T0 = datetime(2026, 8, 13, 8, 0)
lulus = gagal = lewat = 0


def uji(nama, fn):
    global lulus, gagal
    try:
        fn()
        print(f"  [OK]    {nama}")
        lulus += 1
    except Exception as e:
        print(f"  [GAGAL] {nama}: {type(e).__name__}: {e}")
        gagal += 1


def coba(nama, fn):
    """Uji yang bergantung pada Finance Core hidup."""
    global lulus, gagal, lewat
    try:
        fn()
        print(f"  [OK]    {nama}")
        lulus += 1
    except rek.FinanceTidakTerjangkau as e:
        print(f"  [LEWAT] {nama}: Finance Core tidak terjangkau")
        lewat += 1
    except Exception as e:
        print(f"  [GAGAL] {nama}: {type(e).__name__}: {e}")
        gagal += 1


print("\n=== PEMETAAN AKUN ===")
p = pos.periksa_pemetaan()
for akun, siap in p.items():
    print(f"    {akun:<26}{'sudah' if siap else 'BELUM'}")

uji("tiga akun inti sudah dipetakan",
    lambda: None if all(p[k] for k in
                        ("kas", "piutang_marketplace", "penjualan"))
    else (_ for _ in ()).throw(AssertionError(str(p))))

uji("akun yang belum diputuskan tetap kosong",
    lambda: None if not any(p[k] for k in
                            ("beban_fee_marketplace", "retur_penjualan",
                             "selisih_settlement"))
    else (_ for _ in ()).throw(AssertionError("ada yang terisi diam-diam")))


def _ekspor_masih_menolak():
    from botconnector_multichannel.core import finance as fin
    js = [fin.jurnal_pesanan(__import__("types").SimpleNamespace(
        provider="shopee", id_provider="A1", id_toko="t1", dibuat_pada=T0,
        total=type("U", (), {"jumlah": Decimal("100000")})(),
        biaya_marketplace=type("U", (), {"jumlah": Decimal("12000")})(),
        kunci_dedup="shopee:t1:A1"))]
    r = pos.ringkas_harian(js)[0]
    try:
        pos.ekspor(r)
    except pos.AkunBelumDipetakan:
        return
    raise AssertionError("ekspor seharusnya masih menolak")


uji("ekspor menolak selama akun belum lengkap", _ekspor_masih_menolak)

print("\n=== FINANCE CORE (baca saja) ===")
coba("health terjawab",
     lambda: None if rek.kesehatan().get("ok")
     else (_ for _ in ()).throw(AssertionError("ok bukan true")))
coba("neraca seimbang",
     lambda: None if rek.neraca_seimbang()
     else (_ for _ in ()).throw(AssertionError("neraca tidak seimbang")))


def _akun_inti_ada():
    s = rek.saldo_akun()
    for kode in ("1102", "1201", "4101", "1301", "5101"):
        if kode not in s:
            raise AssertionError(f"akun {kode} tidak ditemukan")


coba("akun inti ada di bagan akun", _akun_inti_ada)


def _usulan_belum_ada():
    s = rek.saldo_akun()
    ada = [k for k in ("6202", "4102", "6203") if k in s]
    if ada:
        print(f"          catatan: {ada} sudah dibuat, pemetaan bisa diisi")


coba("periksa akun usulan", _usulan_belum_ada)

coba("agustus 2026 masih terbuka",
     lambda: None if rek.periode_terbuka_pada("2026-08")
     else (_ for _ in ()).throw(AssertionError(
         f"periode terbuka: {rek.periode_terbuka()}")))


def _periode_lengkap():
    p = rek.periode()
    assert p, "daftar periode kosong"
    a = [x for x in p if x["kode"] == "2026-08"]
    assert a, [x["kode"] for x in p]
    assert a[0]["status"] == "OPEN" and not a[0]["tertutup_pada"], a[0]
    print(f"          {a[0]['kode']}  {a[0]['status']}  "
          f"{a[0]['mulai']} sampai {a[0]['selesai']}")


coba("rincian periode terbaca lengkap", _periode_lengkap)

print("\n=== PERBANDINGAN STOK ===")


def _banding():
    b = BukuStok()
    b.catat(Gerakan("SKU-A", JenisGerakan.MASUK, 10, "m1", T0, "uji"))
    hasil = rek.bandingkan_stok(b, {"SKU-A": "TIDAK-ADA-DI-FINANCE"})
    assert len(hasil) == 1
    assert not hasil[0].cocok, "item yang tidak ada harus terdeteksi sebagai selisih"
    print(rek.laporan(hasil))


coba("item tak dikenal terdeteksi sebagai selisih", _banding)

print(f"\n  Lulus: {lulus}   Gagal: {gagal}   Lewat: {lewat}\n")
sys.exit(1 if gagal else 0)
