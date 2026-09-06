"""Batas credential.

Rahasia tidak pernah masuk kode, tidak pernah masuk log, dan tidak
pernah tampil saat objeknya dicetak.
"""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path

from .kontrak import GerbangTertutup, muat


class Rahasia:
    """Pembungkus nilai rahasia. Mencetaknya tidak membocorkan isinya."""

    __slots__ = ("_nilai",)

    def __init__(self, nilai: str) -> None:
        object.__setattr__(self, "_nilai", str(nilai))

    def buka(self) -> str:
        """Satu-satunya jalan mengambil nilainya. Jangan pernah dicatat."""
        return self._nilai

    def sidik(self) -> str:
        return hashlib.sha256(self._nilai.encode()).hexdigest()[:12]

    def __repr__(self) -> str:
        return f"<Rahasia {self.sidik()} panjang={len(self._nilai)}>"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class Kredensial:
    partner_id: str
    partner_key: Rahasia
    berkas: str

    def __repr__(self) -> str:
        return (f"Kredensial(partner_id={self.partner_id!r}, "
                f"partner_key={self.partner_key!r})")

    __str__ = __repr__

    def sidik(self) -> str:
        return self.partner_key.sidik()


def muat_kredensial() -> Kredensial:
    """Menolak bila gerbang tertutup atau izin berkas longgar."""
    c = muat()
    if c.get("KILL_SWITCH"):
        raise GerbangTertutup("KILL_SWITCH aktif")
    if not c.get("REAL_CREDENTIAL_ENABLED"):
        raise GerbangTertutup("REAL_CREDENTIAL_ENABLED=false")

    berkas = Path(str(c.get("berkas_credential", "")))
    if not berkas.is_file():
        raise GerbangTertutup(f"berkas credential tidak ada: {berkas}")

    izin = stat.S_IMODE(berkas.stat().st_mode)
    if izin & 0o077:
        raise GerbangTertutup(
            f"izin credential terlalu longgar ({oct(izin)}), wajib 0600")

    # rahasia tidak boleh berada di dalam repositori
    for induk in [berkas] + list(berkas.parents):
        if (induk / ".git").exists():
            raise GerbangTertutup(
                f"berkas credential berada di dalam repositori git: {induk}")

    data = json.loads(berkas.read_text(encoding="utf-8"))
    pid = str(data.get("partner_id", "")).strip()
    key = str(data.get("partner_key", "")).strip()
    if not pid or not key:
        raise GerbangTertutup("partner_id atau partner_key kosong")

    return Kredensial(partner_id=pid, partner_key=Rahasia(key),
                      berkas=str(berkas))


def periksa_berkas() -> dict:
    """Keadaan berkas credential tanpa membukanya."""
    c = muat()
    berkas = Path(str(c.get("berkas_credential", "")))
    hasil = {"jalur": str(berkas), "ada": berkas.is_file()}
    if hasil["ada"]:
        izin = stat.S_IMODE(berkas.stat().st_mode)
        hasil["izin"] = oct(izin)
        hasil["izin_ketat"] = (izin & 0o077) == 0
    return hasil
