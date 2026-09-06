"""Kontrak aktivasi produksi.

Menyalakan satu gerbang tidak cukup. Jaringan hanya boleh terbuka
bila SELURUH syarat terpenuhi, dan tiap penolakan menyebutkan
syarat mana yang belum lolos.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

BERKAS = Path("/etc/botconnector-shopee-activation.json")

BAWAAN = {
    "PRODUCTION_ACTIVATION_APPROVED": False,
    "NETWORK_ENABLED": False,
    "REAL_CREDENTIAL_ENABLED": False,
    "REAL_OAUTH_ENABLED": False,
    "READ_ONLY_ACCEPTANCE_PASSED": False,
    "WRITE_OPERATIONS_APPROVED": False,
    "KILL_SWITCH": False,
    "berkas_credential": "/etc/botconnector-shopee-credential.json",
    "host_diizinkan": [],
    "endpoint_baca_diizinkan": [],
    "endpoint_tulis_diizinkan": [],
    "toko_kanari": "",
    "berkas_audit": "/var/log/botconnector-shopee-activation.jsonl",
}


class GerbangTertutup(RuntimeError):
    """Satu-satunya galat yang boleh muncul saat sesuatu ditolak."""


def muat() -> dict:
    d = dict(BAWAAN)
    try:
        if BERKAS.exists():
            d.update(json.loads(BERKAS.read_text(encoding="utf-8")))
    except Exception:
        pass
    return d


@dataclass(frozen=True)
class Syarat:
    nama: str
    lolos: bool
    keterangan: str = ""


def periksa_syarat(cfg: dict | None = None) -> list[Syarat]:
    """Seluruh syarat sebelum jaringan boleh dibuka."""
    c = cfg or muat()
    s: list[Syarat] = []

    s.append(Syarat("kill switch tidak aktif", not c.get("KILL_SWITCH"),
                    "KILL_SWITCH=true menutup segalanya"))
    s.append(Syarat("aktivasi produksi disetujui",
                    bool(c.get("PRODUCTION_ACTIVATION_APPROVED")),
                    "harus disetujui secara eksplisit, bukan efek samping"))
    s.append(Syarat("gerbang jaringan dinyalakan",
                    bool(c.get("NETWORK_ENABLED"))))
    s.append(Syarat("credential dinyalakan",
                    bool(c.get("REAL_CREDENTIAL_ENABLED"))))

    berkas = Path(str(c.get("berkas_credential", "")))
    ada = berkas.is_file()
    s.append(Syarat("berkas credential ada", ada, str(berkas)))

    izin_ok = False
    if ada:
        try:
            st = berkas.stat()
            izin = stat.S_IMODE(st.st_mode)
            izin_ok = (izin & 0o077) == 0
            s.append(Syarat("izin credential 0600 atau lebih ketat", izin_ok,
                            f"izin sekarang {oct(izin)}"))
        except Exception as e:
            s.append(Syarat("izin credential terbaca", False, str(e)))
    else:
        s.append(Syarat("izin credential 0600 atau lebih ketat", False,
                        "berkas belum ada"))

    s.append(Syarat("daftar host tidak kosong",
                    bool(c.get("host_diizinkan"))))
    s.append(Syarat("daftar endpoint baca tidak kosong",
                    bool(c.get("endpoint_baca_diizinkan"))))
    s.append(Syarat("toko kanari ditentukan", bool(c.get("toko_kanari")),
                    "mulai dari satu toko saja"))

    audit = Path(str(c.get("berkas_audit", "")))
    bisa = False
    try:
        bisa = audit.parent.is_dir() and os.access(audit.parent, os.W_OK)
    except Exception:
        pass
    s.append(Syarat("berkas audit dapat ditulis", bisa, str(audit.parent)))

    return s


def boleh_jaringan(cfg: dict | None = None) -> None:
    """Melempar GerbangTertutup dengan menyebut syarat yang belum lolos."""
    kurang = [x for x in periksa_syarat(cfg) if not x.lolos]
    if kurang:
        rincian = "; ".join(f"{x.nama}" + (f" ({x.keterangan})" if x.keterangan else "")
                            for x in kurang[:4])
        raise GerbangTertutup(
            f"{len(kurang)} syarat belum terpenuhi: {rincian}"
        )


def boleh_host(host: str, cfg: dict | None = None) -> None:
    c = cfg or muat()
    if host not in c.get("host_diizinkan", []):
        raise GerbangTertutup(f"host '{host}' di luar daftar izin")


def boleh_endpoint(jalur: str, tulis: bool = False,
                   cfg: dict | None = None) -> None:
    c = cfg or muat()
    if tulis:
        if not c.get("READ_ONLY_ACCEPTANCE_PASSED"):
            raise GerbangTertutup(
                "operasi tulis ditolak: read-only acceptance belum lulus")
        if not c.get("WRITE_OPERATIONS_APPROVED"):
            raise GerbangTertutup("WRITE_OPERATIONS_APPROVED=false")
        izin = c.get("endpoint_tulis_diizinkan", [])
    else:
        izin = c.get("endpoint_baca_diizinkan", [])
    if jalur not in izin:
        jenis = "tulis" if tulis else "baca"
        raise GerbangTertutup(f"endpoint {jenis} '{jalur}' di luar daftar izin")


def boleh_toko(id_toko: str, cfg: dict | None = None) -> None:
    c = cfg or muat()
    kanari = str(c.get("toko_kanari", ""))
    if not kanari:
        raise GerbangTertutup("toko kanari belum ditentukan")
    if str(id_toko) != kanari:
        raise GerbangTertutup(
            f"toko '{id_toko}' bukan toko kanari '{kanari}'")


def bukti(cfg: dict | None = None) -> dict:
    """Ringkasan keadaan untuk dicatat sebagai bukti runtime."""
    c = cfg or muat()
    syarat = periksa_syarat(c)
    return {
        "gerbang": {k: c.get(k) for k in BAWAAN if isinstance(BAWAAN[k], bool)},
        "syarat_lolos": sum(1 for x in syarat if x.lolos),
        "syarat_total": len(syarat),
        "belum_lolos": [x.nama for x in syarat if not x.lolos],
        "host_diizinkan": c.get("host_diizinkan", []),
        "jumlah_endpoint_baca": len(c.get("endpoint_baca_diizinkan", [])),
        "jumlah_endpoint_tulis": len(c.get("endpoint_tulis_diizinkan", [])),
        "toko_kanari": c.get("toko_kanari", "") or "(belum ada)",
    }


def laporan() -> str:
    baris = ["  syarat aktivasi produksi", "  " + "-" * 66]
    for x in periksa_syarat():
        tanda = "lolos " if x.lolos else "BELUM "
        ket = f"  {x.keterangan}" if x.keterangan and not x.lolos else ""
        baris.append(f"  {tanda} {x.nama}{ket}")
    b = bukti()
    baris.append("  " + "-" * 66)
    baris.append(f"  {b['syarat_lolos']} dari {b['syarat_total']} syarat lolos")
    return "\n".join(baris)
