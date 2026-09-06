"""Gerbang penerimaan alur Hubungkan Toko."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from botconnector_multichannel.activation import kontrak as kon   # noqa: E402
from botconnector_multichannel.activation import koneksi as kx     # noqa: E402

lulus = gagal = 0
RAHASIA = "token-rahasia-jangan-muncul-0987654321"


def uji(nama, fn):
    global lulus, gagal
    try:
        fn()
        print(f"  [OK]    {nama}")
        lulus += 1
    except Exception as e:
        print(f"  [GAGAL] {nama}: {type(e).__name__}: {e}")
        gagal += 1


def cfg_terbuka():
    """Kontrak dengan seluruh gerbang terbuka, untuk menguji alur penuh."""
    isi = {**kon.BAWAAN, "PRODUCTION_ACTIVATION_APPROVED": True,
           "NETWORK_ENABLED": True, "REAL_CREDENTIAL_ENABLED": True,
           "host_diizinkan": ["partner.shopeemobile.com"],
           "endpoint_baca_diizinkan": ["/api/v2/shop/get_shop_info"],
           "toko_kanari": "TOKO-1",
           "berkas_audit": "/tmp/uji-koneksi.jsonl"}
    kred = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"partner_id": "1", "partner_key": "k"}, kred)
    kred.close()
    Path(kred.name).chmod(0o600)
    isi["berkas_credential"] = kred.name
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(isi, f)
    f.close()
    return Path(f.name)


def penukar_palsu(code, id_toko):
    return (RAHASIA, RAHASIA + "-segar", 3600)


print("\n=== PERMINTAAN OTORISASI ===")


def _state_acak():
    g = kx.GudangSambungan()
    a = g.buat_permintaan("t1", "shopee")
    b = g.buat_permintaan("t1", "shopee")
    assert a.state != b.state, "state harus berbeda tiap permintaan"
    assert len(a.state) >= 32, len(a.state)


uji("state acak dan cukup panjang", _state_acak)


def _state_asing():
    g = kx.GudangSambungan()
    try:
        g.ambil_permintaan("state-karangan")
    except kx.SambunganDitolak:
        return
    raise AssertionError("state asing seharusnya ditolak")


uji("state asing ditolak", _state_asing)


def _state_kedaluwarsa():
    g = kx.GudangSambungan()
    p = g.buat_permintaan("t1", "shopee")
    p.dibuat = p.dibuat - timedelta(minutes=11)
    try:
        g.ambil_permintaan(p.state)
    except kx.SambunganDitolak as e:
        assert "kedaluwarsa" in str(e)
        return
    raise AssertionError("state kedaluwarsa seharusnya ditolak")


uji("state kedaluwarsa ditolak", _state_kedaluwarsa)


def _url_tanpa_penanda():
    g = kx.GudangSambungan()
    p = g.buat_permintaan("t1", "shopee")
    try:
        kx.url_otorisasi(p, "https://botconnector.id/cb", "12345")
    except kon.GerbangTertutup as e:
        assert "penanda tangan" in str(e)
        return
    raise AssertionError("URL tidak boleh dibuat tanpa penanda tangan")


uji("URL otorisasi menolak tanpa penanda tangan beku", _url_tanpa_penanda)


def _url_dengan_penanda():
    g = kx.GudangSambungan()
    p = g.buat_permintaan("t1", "shopee")
    url = kx.url_otorisasi(p, "https://botconnector.id/cb", "12345",
                           penanda_tangan=lambda j, t: "TANDA")
    assert p.state in url and "partner_id=12345" in url
    assert "sign=TANDA" in url


uji("URL tersusun benar bila penanda disuntikkan", _url_dengan_penanda)

print("\n=== CALLBACK TERTAHAN SELAMA GERBANG TERTUTUP ===")


def _callback_tertahan():
    asli = kon.BERKAS
    kon.BERKAS = Path("/tidak/ada.json")          # seluruh gerbang mati
    try:
        g = kx.GudangSambungan()
        p = g.buat_permintaan("t1", "shopee")
        try:
            kx.tangani_callback(g, p.state, "CODE", "TOKO-1",
                                penukar=penukar_palsu)
        except kon.GerbangTertutup:
            assert not g.ambil("t1", "shopee", "TOKO-1"), \
                "sambungan tidak boleh terbentuk"
            return
        raise AssertionError("callback seharusnya tertahan")
    finally:
        kon.BERKAS = asli


uji("callback tertahan dan tidak membuat sambungan", _callback_tertahan)

print("\n=== ALUR PENUH SAAT GERBANG DIBUKA ===")


def _alur_penuh():
    asli = kon.BERKAS
    kon.BERKAS = cfg_terbuka()
    try:
        g = kx.GudangSambungan()
        p = g.buat_permintaan("t1", "shopee")
        s = kx.tangani_callback(g, p.state, "CODE", "TOKO-1",
                                penukar=penukar_palsu, nama_toko="Toko ABC")
        assert s.status is kx.StatusSambungan.TERHUBUNG, s.status
        assert s.nama_toko == "Toko ABC"
        assert not s.perlu_disegarkan(), "token baru belum perlu disegarkan"
        kartu = s.untuk_tampilan()
        assert kartu["status"] == "Terhubung" and kartu["toko"] == "Toko ABC"
    finally:
        kon.BERKAS = asli


uji("toko tersambung dan kartu tampilan benar", _alur_penuh)


def _state_sekali_pakai():
    asli = kon.BERKAS
    kon.BERKAS = cfg_terbuka()
    try:
        g = kx.GudangSambungan()
        p = g.buat_permintaan("t1", "shopee")
        kx.tangani_callback(g, p.state, "CODE", "TOKO-1", penukar=penukar_palsu)
        try:
            kx.tangani_callback(g, p.state, "CODE", "TOKO-2",
                                penukar=penukar_palsu)
        except kx.SambunganDitolak as e:
            assert "sudah pernah dipakai" in str(e), str(e)
            return
        raise AssertionError("state seharusnya hanya sekali pakai")
    finally:
        kon.BERKAS = asli


uji("state hanya bisa dipakai sekali", _state_sekali_pakai)


def _callback_diulang():
    asli = kon.BERKAS
    kon.BERKAS = cfg_terbuka()
    try:
        g = kx.GudangSambungan()
        p1 = g.buat_permintaan("t1", "shopee")
        a = kx.tangani_callback(g, p1.state, "C1", "TOKO-1",
                                penukar=penukar_palsu)
        p2 = g.buat_permintaan("t1", "shopee")
        b = kx.tangani_callback(g, p2.state, "C1", "TOKO-1",
                                penukar=penukar_palsu)
        assert a is b, "callback ulang tidak boleh membuat sambungan kedua"
        assert len(g.daftar("t1")) == 1, len(g.daftar("t1"))
    finally:
        kon.BERKAS = asli


uji("callback berulang tidak menggandakan sambungan", _callback_diulang)


def _toko_tenant_lain():
    asli = kon.BERKAS
    kon.BERKAS = cfg_terbuka()
    try:
        g = kx.GudangSambungan()
        p1 = g.buat_permintaan("t1", "shopee")
        kx.tangani_callback(g, p1.state, "C", "TOKO-1", penukar=penukar_palsu)
        p2 = g.buat_permintaan("t2", "shopee")
        try:
            kx.tangani_callback(g, p2.state, "C", "TOKO-1",
                                penukar=penukar_palsu)
        except kx.SambunganDitolak as e:
            assert "tenant lain" in str(e), str(e)
            return
        raise AssertionError("toko milik tenant lain seharusnya ditolak")
    finally:
        kon.BERKAS = asli


uji("satu toko tidak bisa dimiliki dua tenant", _toko_tenant_lain)

print("\n=== TOKEN TIDAK BOCOR ===")


def _token_aman():
    asli = kon.BERKAS
    kon.BERKAS = cfg_terbuka()
    try:
        g = kx.GudangSambungan()
        p = g.buat_permintaan("t1", "shopee")
        s = kx.tangani_callback(g, p.state, "C", "TOKO-1",
                                penukar=penukar_palsu)
        for teks in (repr(s), str(s), f"{s}", json.dumps(s.untuk_tampilan())):
            assert RAHASIA not in teks, f"token bocor: {teks[:90]}"
        assert s.akses.buka() == RAHASIA
    finally:
        kon.BERKAS = asli


uji("token tidak muncul saat sambungan dicetak", _token_aman)

print("\n=== SIKLUS TOKEN & PEMUTUSAN ===")


def _perlu_segar():
    s = kx.Sambungan("t1", "shopee", "TOKO-1", kx.StatusSambungan.TERHUBUNG,
                     akses_habis=kx.sekarang() + timedelta(minutes=10))
    assert s.perlu_disegarkan(), "token hampir habis harus ditandai"


uji("token hampir habis ditandai perlu disegarkan", _perlu_segar)


def _putus():
    asli = kon.BERKAS
    kon.BERKAS = cfg_terbuka()
    try:
        g = kx.GudangSambungan()
        p = g.buat_permintaan("t1", "shopee")
        kx.tangani_callback(g, p.state, "C", "TOKO-1", penukar=penukar_palsu)
        s = kx.putuskan(g, "t1", "shopee", "TOKO-1")
        assert s.status is kx.StatusSambungan.TERPUTUS
        assert s.akses is None and s.segar is None, "token wajib dihapus"
    finally:
        kon.BERKAS = asli


uji("memutus sambungan menghapus token", _putus)

print("\n=== HALAMAN INTEGRASI ===")


def _halaman():
    asli = kon.BERKAS
    kon.BERKAS = cfg_terbuka()
    try:
        g = kx.GudangSambungan()
        p = g.buat_permintaan("t1", "shopee")
        kx.tangani_callback(g, p.state, "C", "TOKO-1",
                            penukar=penukar_palsu, nama_toko="Toko ABC")
        kartu = kx.halaman_integrasi(g, "t1",
                                     ["shopee", "tiktok_shop", "tokopedia"])
        assert len(kartu) == 3
        assert kartu[0]["status"] == "Terhubung"
        assert kartu[1]["status"] == "Belum terhubung"
        for k in kartu:
            print(f"          {k['provider']:<14}{k['status']:<20}{k['tombol']}")
    finally:
        kon.BERKAS = asli


uji("halaman integrasi menampilkan status tiap marketplace", _halaman)

print(f"\n  Lulus: {lulus}   Gagal: {gagal}\n")
sys.exit(1 if gagal else 0)
