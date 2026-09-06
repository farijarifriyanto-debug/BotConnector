"""Mesin keadaan sambungan marketplace.

Menangani alur "Hubungkan Toko" dari sisi BotConnector. Tidak
melakukan panggilan jaringan sendiri; pertukaran token diserahkan
ke transport berpagar, dan penandatanganan ke foundation beku.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Optional
from urllib.parse import urlencode

from . import audit
from .kontrak import GerbangTertutup, boleh_jaringan, muat
from .kredensial import Rahasia

UMUR_STATE = timedelta(minutes=10)


def sekarang() -> datetime:
    return datetime.now(timezone.utc)


class StatusSambungan(str, Enum):
    BELUM_TERHUBUNG = "belum_terhubung"
    MENUNGGU_OTORISASI = "menunggu_otorisasi"
    TERHUBUNG = "terhubung"
    KEDALUWARSA = "kedaluwarsa"
    TERPUTUS = "terputus"


class SambunganDitolak(Exception):
    """Alur otorisasi ditolak karena alasan yang jelas."""


# ---------------------------------------------------------------- state
@dataclass
class Permintaan:
    """Satu permintaan otorisasi. State hanya boleh dipakai sekali."""
    state: str
    tenant: str
    provider: str
    dibuat: datetime
    dipakai: bool = False

    def kedaluwarsa(self, pada: datetime | None = None) -> bool:
        return (pada or sekarang()) - self.dibuat > UMUR_STATE


# ---------------------------------------------------------------- sambungan
@dataclass
class Sambungan:
    tenant: str
    provider: str
    id_toko: str
    status: StatusSambungan
    nama_toko: str = ""
    akses: Optional[Rahasia] = None
    segar: Optional[Rahasia] = None
    akses_habis: Optional[datetime] = None
    terhubung_pada: Optional[datetime] = None
    _riwayat: list = field(default_factory=list, repr=False)

    def __repr__(self) -> str:
        return (f"Sambungan(tenant={self.tenant!r}, provider={self.provider!r}, "
                f"id_toko={self.id_toko!r}, status={self.status.value!r}, "
                f"akses={self.akses!r}, segar={self.segar!r})")

    __str__ = __repr__

    def perlu_disegarkan(self, pada: datetime | None = None,
                         ambang: timedelta = timedelta(minutes=30)) -> bool:
        if self.status is not StatusSambungan.TERHUBUNG or not self.akses_habis:
            return False
        return (pada or sekarang()) + ambang >= self.akses_habis

    def untuk_tampilan(self) -> dict:
        """Isi kartu di halaman Integrasi."""
        if self.status is StatusSambungan.TERHUBUNG:
            return {
                "provider": self.provider,
                "status": "Terhubung",
                "toko": self.nama_toko or self.id_toko,
                "sinkron_otomatis": "Aktif",
                "tombol": "Pengaturan",
            }
        if self.status is StatusSambungan.MENUNGGU_OTORISASI:
            return {"provider": self.provider, "status": "Menunggu otorisasi",
                    "tombol": "Ulangi"}
        if self.status is StatusSambungan.KEDALUWARSA:
            return {"provider": self.provider, "status": "Perlu dihubungkan ulang",
                    "tombol": "Hubungkan ulang"}
        return {"provider": self.provider, "status": "Belum terhubung",
                "tombol": f"Hubungkan {self.provider.title()}"}


# ---------------------------------------------------------------- gudang
class GudangSambungan:
    """Penyimpan sambungan dan permintaan otorisasi."""

    def __init__(self) -> None:
        self._permintaan: dict[str, Permintaan] = {}
        self._sambungan: dict[tuple[str, str, str], Sambungan] = {}

    # ---- permintaan ----
    def buat_permintaan(self, tenant: str, provider: str) -> Permintaan:
        p = Permintaan(state=secrets.token_urlsafe(32), tenant=tenant,
                       provider=provider, dibuat=sekarang())
        self._permintaan[p.state] = p
        audit.catat("otorisasi_diminta",
                    {"tenant": tenant, "provider": provider,
                     "state": p.state[:8] + "..."})
        return p

    def ambil_permintaan(self, state: str) -> Permintaan:
        p = self._permintaan.get(state)
        if not p:
            raise SambunganDitolak("state tidak dikenal")
        if p.dipakai:
            raise SambunganDitolak("state sudah pernah dipakai")
        if p.kedaluwarsa():
            raise SambunganDitolak("state sudah kedaluwarsa")
        return p

    # ---- sambungan ----
    def simpan(self, s: Sambungan) -> None:
        self._sambungan[(s.tenant, s.provider, s.id_toko)] = s

    def ambil(self, tenant: str, provider: str, id_toko: str) -> Optional[Sambungan]:
        return self._sambungan.get((tenant, provider, id_toko))

    def milik_tenant_lain(self, provider: str, id_toko: str,
                          tenant: str) -> Optional[str]:
        """Toko yang sama tidak boleh dimiliki dua tenant."""
        for (t, p, i), s in self._sambungan.items():
            if p == provider and i == id_toko and t != tenant \
                    and s.status is StatusSambungan.TERHUBUNG:
                return t
        return None

    def daftar(self, tenant: str) -> list[Sambungan]:
        return [s for (t, _, _), s in self._sambungan.items() if t == tenant]


# ---------------------------------------------------------------- alur
def url_otorisasi(permintaan: Permintaan, redirect: str,
                  partner_id: str,
                  penanda_tangan: Optional[Callable] = None,
                  pangkalan: str = "https://partner.shopeemobile.com",
                  jalur: str = "/api/v2/shop/auth_partner") -> str:
    """Susun URL yang dibuka pengguna.

    Penandatanganan TIDAK ditulis ulang di sini; harus disuntikkan dari
    foundation beku. Tanpa itu, fungsi ini menolak.
    """
    if penanda_tangan is None:
        raise GerbangTertutup(
            "penanda tangan belum disuntikkan dari foundation beku")

    cap = int(sekarang().timestamp())
    tanda = penanda_tangan(jalur, cap)
    kueri = urlencode({
        "partner_id": partner_id,
        "timestamp": cap,
        "sign": tanda,
        "redirect": redirect,
        "state": permintaan.state,
    })
    audit.catat("url_otorisasi_dibuat",
                {"provider": permintaan.provider, "jalur": jalur,
                 "state": permintaan.state[:8] + "..."})
    return f"{pangkalan}{jalur}?{kueri}"


def tangani_callback(gudang: GudangSambungan, state: str, code: str,
                     id_toko: str, penukar: Optional[Callable] = None,
                     nama_toko: str = "") -> Sambungan:
    """Callback dari marketplace.

    penukar(code, id_toko) -> (akses, segar, detik_berlaku).
    Bila None, alur berhenti tepat sebelum jaringan dan melempar
    GerbangTertutup — inilah keadaan sekarang.
    """
    p = gudang.ambil_permintaan(state)

    pemilik = gudang.milik_tenant_lain(p.provider, id_toko, p.tenant)
    if pemilik:
        audit.catat("callback_ditolak",
                    {"alasan": "toko dimiliki tenant lain",
                     "provider": p.provider, "toko": id_toko})
        raise SambunganDitolak(
            f"toko {id_toko} sudah terhubung ke tenant lain")

    lama = gudang.ambil(p.tenant, p.provider, id_toko)
    if lama and lama.status is StatusSambungan.TERHUBUNG:
        p.dipakai = True
        audit.catat("callback_diulang",
                    {"provider": p.provider, "toko": id_toko})
        return lama                       # aman diulang, tidak menggandakan

    try:
        boleh_jaringan()
    except GerbangTertutup:
        audit.catat("callback_tertahan",
                    {"alasan": "gerbang jaringan tertutup",
                     "provider": p.provider, "toko": id_toko})
        raise

    if penukar is None:
        raise GerbangTertutup("penukar token belum dipasang")

    p.dipakai = True
    akses, segar, detik = penukar(code, id_toko)
    s = Sambungan(
        tenant=p.tenant, provider=p.provider, id_toko=id_toko,
        status=StatusSambungan.TERHUBUNG, nama_toko=nama_toko,
        akses=Rahasia(akses), segar=Rahasia(segar),
        akses_habis=sekarang() + timedelta(seconds=int(detik)),
        terhubung_pada=sekarang(),
    )
    gudang.simpan(s)
    audit.catat("tersambung", {"provider": s.provider, "toko": id_toko,
                               "tenant": p.tenant})
    return s


def putuskan(gudang: GudangSambungan, tenant: str, provider: str,
             id_toko: str) -> Sambungan:
    s = gudang.ambil(tenant, provider, id_toko)
    if not s:
        raise SambunganDitolak("sambungan tidak ditemukan")
    s.status = StatusSambungan.TERPUTUS
    s.akses = None
    s.segar = None
    s.akses_habis = None
    gudang.simpan(s)
    audit.catat("diputus", {"provider": provider, "toko": id_toko,
                            "tenant": tenant})
    return s


def halaman_integrasi(gudang: GudangSambungan, tenant: str,
                      provider_tersedia: list[str]) -> list[dict]:
    """Isi halaman Integrasi seperti pada dokumen ide utama."""
    hasil = []
    for prov in provider_tersedia:
        milik = [s for s in gudang.daftar(tenant) if s.provider == prov]
        terhubung = [s for s in milik
                     if s.status is StatusSambungan.TERHUBUNG]
        if terhubung:
            hasil.append(terhubung[0].untuk_tampilan())
        elif milik:
            hasil.append(milik[0].untuk_tampilan())
        else:
            hasil.append(Sambungan(tenant, prov, "",
                                   StatusSambungan.BELUM_TERHUBUNG)
                         .untuk_tampilan())
    return hasil
