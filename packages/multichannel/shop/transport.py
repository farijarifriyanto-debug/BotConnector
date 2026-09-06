"""Transport Shopee berpagar.

Seluruh panggilan keluar lewat satu titik ini. Bawaan TIDAK ada pengirim
jaringan (offline). Pengirim nyata hanya disuntikkan bila kontrak aktivasi
produksi lolos.

Tidak ada pustaka jaringan diimpor di sini; pengirim datang dari luar.
"""

from __future__ import annotations

from typing import Callable, Optional
from urllib.parse import urlencode

from ..activation.kontrak import (
    GerbangTertutup,
    boleh_endpoint,
    boleh_host,
    boleh_jaringan,
    boleh_toko,
)

HOST_PROD = "partner.shopeemobile.com"
HOST_UAT = "partner.uat.shopeemobile.com"

METODE_BACA = {"GET", "POST"}


class Transport:
    def __init__(self, pengirim: Optional[Callable] = None, uat: bool = False):
        """pengirim(metode, url, header, isi) -> jawaban.

        None = tidak ada kemampuan jaringan.
        """
        self._pengirim = pengirim
        self._uat = uat

    def host(self) -> str:
        return HOST_UAT if self._uat else HOST

    def panggil(
        self,
        metode: str,
        jalur: str,
        id_toko: str = "",
        query: dict | None = None,
        isi: dict | None = None,
        header: dict | None = None,
    ):
        metode = metode.upper()
        host = self.host()

        # gerbang sebelum jaringan
        boleh_jaringan()
        boleh_host(host)
        boleh_endpoint(jalur, tulis=False)
        if id_toko:
            boleh_toko(id_toko)

        if self._pengirim is None:
            raise GerbangTertutup(
                "gerbang lolos tetapi pengirim jaringan belum dipasang")

        url = f"https://{host}{jalur}"
        if query:
            url += "?" + urlencode(query)

        return self._pengirim(
            metode, url, header or {}, isi,
        )

    def baca(
        self,
        jalur: str,
        id_toko: str = "",
        query: dict | None = None,
        header: dict | None = None,
    ):
        return self.panggil("GET", jalur, id_toko, query, None, header)


def transport_mati() -> Transport:
    """Transport tanpa jaringan. Ini keadaan bawaan."""
    return Transport(pengirim=None)
