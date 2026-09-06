"""Gerbang penerimaan lapisan posting."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from botconnector_multichannel.core.models import (          # noqa: E402
    BarisPesanan, Pesanan, Settlement, StatusPesanan, Uang)
from botconnector_multichannel.core import finance as fin    # noqa: E402
from botconnector_multichannel.core import posting as pos    # noqa: E402

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


def pesanan(total, fee, idp, jam=0):
    return Pesanan(
        provider="shopee", id_provider=idp, id_toko="t1",
        status=StatusPesanan.DIBAYAR, dibuat_pada=T0 + timedelta(hours=jam),
        baris=(BarisPesanan("SHP-A", "A", 1, Uang(Decimal(total))),),
        total=Uang(Decimal(total)), biaya_marketplace=Uang(Decimal(fee)))


def jurnal_sehari(n=5):
    return [fin.jurnal_pesanan(pesanan("100000", "12000", f"A{i}", i))
            for i in range(n)]


print("\n=== RINGKASAN ===")


def _menyusut():
    r = pos.ringkas_harian(jurnal_sehari(5))
    assert len(r) == 1, f"harusnya satu ringkasan, dapat {len(r)}"
    assert r[0].jumlah_jurnal == 5


uji("lima pesanan menjadi satu ringkasan", _menyusut)


def _nilai_utuh():
    js = jurnal_sehari(5)
    r = pos.ringkas_harian(js)[0]
    bb = fin.BukuBesar()
    for j in js:
        bb.catat(j)
    assert r.total_debit() == bb.neraca_percobaan()["debit"], "nilai berubah saat diringkas"
    assert r.seimbang()


uji("nilai tidak berubah saat diringkas", _nilai_utuh)


def _pisah_hari():
    js = jurnal_sehari(3)
    js.append(fin.jurnal_pesanan(pesanan("50000", "6000", "B1", 30)))  # besoknya
    r = pos.ringkas_harian(js)
    assert len(r) == 2, [x.tanggal for x in r]


uji("hari berbeda tidak digabung", _pisah_hari)


def _pisah_provider():
    js = jurnal_sehari(2)
    p = Pesanan(provider="tiktok_shop", id_provider="T1", id_toko="t9",
                status=StatusPesanan.DIBAYAR, dibuat_pada=T0,
                baris=(BarisPesanan("TT-A", "A", 1, Uang(Decimal("70000"))),),
                total=Uang(Decimal("70000")),
                biaya_marketplace=Uang(Decimal("7000")))
    js.append(fin.jurnal_pesanan(p))
    r = pos.ringkas_harian(js)
    assert len(r) == 2, [(x.provider, x.id_toko) for x in r]


uji("marketplace berbeda dipisah", _pisah_provider)


def _kunci_tetap():
    a = pos.ringkas_harian(jurnal_sehari(5))[0].kunci
    b = pos.ringkas_harian(jurnal_sehari(5))[0].kunci
    assert a == b == "posting:shopee:t1:20260813", a


uji("kunci ringkasan dapat diulang", _kunci_tetap)

print("\n=== ANTI KIRIM GANDA ===")


def _sekali():
    bp = pos.BukuPosting()
    r = pos.ringkas_harian(jurnal_sehari(3))[0]
    assert bp.siapkan(r) is True
    assert bp.siapkan(r) is False


uji("ringkasan hari yang sama tidak disiapkan dua kali", _sekali)


def _tandai():
    bp = pos.BukuPosting()
    r = pos.ringkas_harian(jurnal_sehari(3))[0]
    bp.siapkan(r)
    bp.tandai_terkirim(r.kunci, "JV-2026-0001")
    assert not bp.tertunda(), "tidak boleh ada yang tertunda"
    try:
        bp.tandai_terkirim(r.kunci, "JV-2026-0002")
    except ValueError:
        return
    raise AssertionError("pengiriman kedua seharusnya ditolak")


uji("yang sudah terkirim tidak bisa dikirim ulang", _tandai)


def _gagal_tetap_tertunda():
    bp = pos.BukuPosting()
    r = pos.ringkas_harian(jurnal_sehari(2))[0]
    bp.siapkan(r)
    bp.tandai_gagal(r.kunci, "akuntansi tidak menjawab")
    assert len(bp.tertunda()) == 1


uji("posting gagal tetap masuk antrean", _gagal_tetap_tertunda)

print("\n=== PEMETAAN AKUN ===")


def _tolak_belum_dipetakan():
    asli = pos.BERKAS_PETA
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"peta": {"kas": "1101"}}, f)      # sisanya kosong
        pos.BERKAS_PETA = Path(f.name)
    try:
        r = pos.ringkas_harian(jurnal_sehari(2))[0]
        try:
            pos.ekspor(r)
        except pos.AkunBelumDipetakan:
            return
        raise AssertionError("ekspor seharusnya menolak akun tanpa pasangan")
    finally:
        pos.BERKAS_PETA = asli


uji("akun belum dipetakan MENOLAK diekspor", _tolak_belum_dipetakan)


def _ekspor_lengkap():
    asli = pos.BERKAS_PETA
    lengkap = {a.value: f"{4000+i}" for i, a in enumerate(fin.Akun)}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"peta": lengkap}, f)
        pos.BERKAS_PETA = Path(f.name)
    try:
        r = pos.ringkas_harian(jurnal_sehari(3))[0]
        d = pos.ekspor(r)
        assert d["total_debit"] == d["total_kredit"], d
        assert all(b["kode_akun"] for b in d["baris"])
        assert "3 transaksi" in d["keterangan"], d["keterangan"]
    finally:
        pos.BERKAS_PETA = asli


uji("ekspor lengkap ketika seluruh akun dipetakan", _ekspor_lengkap)

print("\n=== KEADAAN PEMETAAN SAAT INI ===")
for akun, siap in pos.periksa_pemetaan().items():
    print(f"  {akun:<26}{'sudah' if siap else 'BELUM dipetakan'}")

print(f"\n  Lulus: {lulus}   Gagal: {gagal}\n")
sys.exit(1 if gagal else 0)
