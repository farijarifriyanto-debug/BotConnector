"""Daftar provider yang dikenal sistem."""

from __future__ import annotations

from .contract import Kemampuan, Kesiapan, Provider

_DAFTAR: dict[str, Provider] = {}


def daftarkan(p: Provider) -> None:
    if not p.id:
        raise ValueError("Provider tanpa id.")
    if p.id in _DAFTAR:
        raise ValueError(f"Provider '{p.id}' sudah terdaftar.")
    _DAFTAR[p.id] = p


def ambil(id_provider: str) -> Provider:
    if id_provider not in _DAFTAR:
        raise KeyError(f"Provider '{id_provider}' tidak dikenal.")
    return _DAFTAR[id_provider]


def semua() -> list[Provider]:
    return list(_DAFTAR.values())


def yang_siap(k: Kemampuan) -> list[Provider]:
    return [p for p in _DAFTAR.values()
            if p.dukung(k) and p.kesiapan != Kesiapan.BELUM_DIBANGUN]


def matriks() -> str:
    """Tabel kemampuan seluruh provider."""
    kolom = list(Kemampuan)
    lebar = max((len(p.nama) for p in _DAFTAR.values()), default=10) + 2
    baris = ["  " + "provider".ljust(lebar) + "kesiapan".ljust(20)
             + "".join(k.value[:9].ljust(11) for k in kolom)]
    baris.append("  " + "-" * (lebar + 20 + 11 * len(kolom)))
    for p in sorted(_DAFTAR.values(), key=lambda x: x.id):
        b = "  " + p.nama.ljust(lebar) + p.kesiapan.value.ljust(20)
        b += "".join(("ya" if p.dukung(k) else "-").ljust(11) for k in kolom)
        baris.append(b)
    return "\n".join(baris)


def muat_bawaan() -> None:
    from ..providers import shopee, tiktok_shop, tokopedia  # noqa
