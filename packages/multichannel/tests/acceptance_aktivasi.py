"""Gerbang penerimaan kontrak aktivasi. Membuktikan bahwa jaringan
TIDAK MUNGKIN terbuka selama syarat belum terpenuhi."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from botconnector_multichannel.activation import audit          # noqa: E402
from botconnector_multichannel.activation import kontrak as kon  # noqa: E402
from botconnector_multichannel.activation import kredensial as kr  # noqa: E402
from botconnector_multichannel.activation.transport import (      # noqa: E402
    Transport, transport_mati)

lulus = gagal = 0
URL = "https://partner.shopeemobile.com/api/v2/shop/get_shop_info"


def uji(nama, fn):
    global lulus, gagal
    try:
        fn()
        print(f"  [OK]    {nama}")
        lulus += 1
    except Exception as e:
        print(f"  [GAGAL] {nama}: {type(e).__name__}: {e}")
        gagal += 1


def dengan_cfg(isi: dict):
    """Ganti berkas kontrak sementara."""
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(isi, f)
    f.close()
    return Path(f.name)


print("\n=== KEADAAN SEKARANG ===")
print(kon.laporan())
b = kon.bukti()
print(f"\n  toko kanari: {b['toko_kanari']}")
print(f"  endpoint baca diizinkan: {b['jumlah_endpoint_baca']}")
print(f"  endpoint tulis diizinkan: {b['jumlah_endpoint_tulis']}")

print("\n=== JARINGAN TERTUTUP ===")


def _tertutup():
    try:
        kon.boleh_jaringan()
    except kon.GerbangTertutup:
        return
    raise AssertionError("jaringan seharusnya masih tertutup")


uji("gerbang jaringan menolak", _tertutup)


def _transport_menolak():
    t = transport_mati()
    try:
        t.baca(URL)
    except kon.GerbangTertutup:
        return
    raise AssertionError("transport seharusnya menolak")


uji("transport menolak memanggil", _transport_menolak)


def _tidak_memanggil_pengirim():
    dipanggil = []

    def pengirim(*a, **k):
        dipanggil.append(a)
        return None

    t = Transport(pengirim=pengirim)
    try:
        t.baca(URL)
    except kon.GerbangTertutup:
        pass
    assert not dipanggil, "pengirim jaringan TERPANGGIL padahal gerbang tertutup"


uji("pengirim jaringan tidak pernah tersentuh", _tidak_memanggil_pengirim)


def _tanpa_pustaka_jaringan():
    src = (Path(kon.__file__).parent / "transport.py").read_text(encoding="utf-8")
    for pustaka in ("import requests", "import httpx", "import urllib.request",
                    "import http.client", "import socket"):
        assert pustaka not in src, f"transport mengimpor {pustaka}"


uji("transport tidak mengimpor pustaka jaringan", _tanpa_pustaka_jaringan)

print("\n=== DAFTAR IZIN ===")
LENGKAP = {
    "PRODUCTION_ACTIVATION_APPROVED": True, "NETWORK_ENABLED": True,
    "REAL_CREDENTIAL_ENABLED": True, "READ_ONLY_ACCEPTANCE_PASSED": False,
    "WRITE_OPERATIONS_APPROVED": False, "KILL_SWITCH": False,
    "host_diizinkan": ["partner.shopeemobile.com"],
    "endpoint_baca_diizinkan": ["/api/v2/shop/get_shop_info"],
    "endpoint_tulis_diizinkan": [],
    "toko_kanari": "TOKO-1",
    "berkas_audit": "/tmp/uji-audit.jsonl",
}


def _host_asing():
    c = dict(LENGKAP)
    try:
        kon.boleh_host("evil.example.com", c)
    except kon.GerbangTertutup:
        return
    raise AssertionError("host asing seharusnya ditolak")


uji("host di luar daftar ditolak", _host_asing)


def _endpoint_asing():
    try:
        kon.boleh_endpoint("/api/v2/order/cancel", tulis=False, cfg=LENGKAP)
    except kon.GerbangTertutup:
        return
    raise AssertionError("endpoint asing seharusnya ditolak")


uji("endpoint di luar daftar ditolak", _endpoint_asing)


def _tulis_ditolak():
    try:
        kon.boleh_endpoint("/api/v2/product/update_stock", tulis=True, cfg=LENGKAP)
    except kon.GerbangTertutup as e:
        assert "read-only" in str(e), str(e)
        return
    raise AssertionError("operasi tulis seharusnya ditolak")


uji("tulis ditolak sebelum read-only lulus", _tulis_ditolak)


def _toko_lain():
    try:
        kon.boleh_toko("TOKO-9", LENGKAP)
    except kon.GerbangTertutup:
        return
    raise AssertionError("toko selain kanari seharusnya ditolak")


uji("hanya toko kanari yang boleh", _toko_lain)

print("\n=== RAHASIA TIDAK BOCOR ===")
NILAI = "kunci-rahasia-yang-tidak-boleh-muncul-1234567890"


def _repr_aman():
    r = kr.Rahasia(NILAI)
    for teks in (repr(r), str(r), f"{r}", f"{r!r}"):
        assert NILAI not in teks, f"rahasia bocor: {teks}"
    assert r.buka() == NILAI


uji("mencetak Rahasia tidak membocorkan isinya", _repr_aman)


def _kredensial_aman():
    k = kr.Kredensial("12345", kr.Rahasia(NILAI), "/x")
    for teks in (repr(k), str(k)):
        assert NILAI not in teks, f"rahasia bocor: {teks}"


uji("mencetak Kredensial tidak membocorkan isinya", _kredensial_aman)


def _audit_menyamarkan():
    d = audit.samarkan({"partner_key": NILAI, "Authorization": "Bearer xyz",
                        "jalur": "/api/v2/shop/get_shop_info",
                        "isi": {"access_token": NILAI}})
    teks = json.dumps(d)
    assert NILAI not in teks, teks
    assert "Bearer" not in teks, teks
    assert "get_shop_info" in teks, "bidang aman ikut terhapus"


uji("audit menyamarkan bidang rahasia", _audit_menyamarkan)


def _izin_longgar_ditolak():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"partner_id": "1", "partner_key": NILAI}, f)
        jalur = Path(f.name)
    os.chmod(jalur, 0o644)                       # sengaja longgar
    asli = kon.BERKAS
    cfg = dengan_cfg({**LENGKAP, "berkas_credential": str(jalur)})
    kon.BERKAS = cfg
    try:
        try:
            kr.muat_kredensial()
        except kon.GerbangTertutup as e:
            assert "longgar" in str(e), str(e)
            return
        raise AssertionError("izin 0644 seharusnya ditolak")
    finally:
        kon.BERKAS = asli


uji("credential berizin longgar ditolak", _izin_longgar_ditolak)

print("\n=== KILL SWITCH ===")


def _kill():
    c = {**LENGKAP, "KILL_SWITCH": True}
    kurang = [x for x in kon.periksa_syarat(c) if not x.lolos]
    assert any("kill switch" in x.nama for x in kurang), [x.nama for x in kurang]
    try:
        kon.boleh_jaringan(c)
    except kon.GerbangTertutup:
        return
    raise AssertionError("kill switch seharusnya menutup jaringan")


uji("kill switch menutup segalanya", _kill)

print("\n=== JEJAK AUDIT ===")


def _penolakan_tercatat():
    asli = kon.BERKAS
    kon.BERKAS = dengan_cfg({**kon.BAWAAN, "berkas_audit": "/tmp/uji-audit.jsonl"})
    try:
        Path("/tmp/uji-audit.jsonl").unlink(missing_ok=True)
        t = transport_mati()
        try:
            t.baca(URL)
        except kon.GerbangTertutup:
            pass
        baris = audit.baca_terakhir(5)
        assert baris, "penolakan tidak tercatat"
        assert baris[-1]["peristiwa"] == "ditolak", baris[-1]
        assert "alasan" in baris[-1]
    finally:
        kon.BERKAS = asli


uji("setiap penolakan tercatat di audit", _penolakan_tercatat)

print(f"\n  Lulus: {lulus}   Gagal: {gagal}\n")
sys.exit(1 if gagal else 0)
