"""Transport terkendali.

Tidak ada pustaka jaringan yang diimpor di sini. Pengirim harus
disuntikkan dari luar, sehingga selama gerbang tertutup, tidak ada
jalan apa pun menuju jaringan.
"""

from __future__ import annotations

from typing import Callable, Optional
from urllib.parse import urlparse

from . import audit
from .kontrak import (GerbangTertutup, boleh_endpoint, boleh_host,
                      boleh_jaringan, boleh_toko, muat)

METODE_BACA = {"GET"}


class Transport:
    def __init__(self, pengirim: Optional[Callable] = None) -> None:
        """pengirim(metode, url, header, isi) -> jawaban.

        Bila None, tidak ada kemampuan jaringan sama sekali.
        """
        self._pengirim = pengirim

    def panggil(self, metode: str, url: str, id_toko: str = "",
                header: dict | None = None, isi: dict | None = None):
        metode = metode.upper()
        bagian = urlparse(url)
        host = bagian.hostname or ""
        jalur = bagian.path or ""
        tulis = metode not in METODE_BACA

        catatan = {"metode": metode, "host": host, "jalur": jalur,
                   "toko": id_toko, "tulis": tulis}

        try:
            boleh_jaringan()
            boleh_host(host)
            boleh_endpoint(jalur, tulis=tulis)
            if id_toko:
                boleh_toko(id_toko)
        except GerbangTertutup as e:
            audit.catat("ditolak", {**catatan, "alasan": str(e)})
            raise

        if self._pengirim is None:
            audit.catat("ditolak", {**catatan,
                                    "alasan": "tidak ada pengirim jaringan"})
            raise GerbangTertutup(
                "seluruh gerbang lolos tetapi pengirim jaringan belum dipasang")

        audit.catat("diizinkan", catatan)
        jawaban = self._pengirim(metode, url, header or {}, isi)
        audit.catat("selesai", {**catatan, "status": getattr(jawaban, "status", "")})
        return jawaban

    def baca(self, url: str, id_toko: str = "", header: dict | None = None):
        return self.panggil("GET", url, id_toko, header)


def transport_mati() -> Transport:
    """Transport tanpa kemampuan jaringan. Ini yang dipakai sekarang."""
    return Transport(pengirim=None)
