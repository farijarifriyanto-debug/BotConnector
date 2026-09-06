"""Stock Core — satu sumber kebenaran stok untuk semua kanal.

Stok disimpan sebagai catatan gerakan yang hanya bisa ditambah,
bukan sebagai angka yang ditimpa. Angka apa pun selalu dapat
dijelaskan asal-usulnya.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JenisGerakan(str, Enum):
    MASUK = "masuk"              # pembelian, produksi, koreksi tambah
    KELUAR = "keluar"            # barang benar-benar dikirim
    RESERVASI = "reservasi"      # dipesan, belum dikirim
    LEPAS = "lepas"              # pesanan batal, reservasi dilepas
    RETUR = "retur"              # barang kembali ke gudang
    PENYESUAIAN = "penyesuaian"  # hasil stok opname


class StokTidakCukup(Exception):
    pass


class GerakanGanda(Exception):
    pass


@dataclass(frozen=True)
class Gerakan:
    sku: str
    jenis: JenisGerakan
    jumlah: int
    kunci: str
    waktu: datetime
    sumber: str = ""
    catatan: str = ""

    def __post_init__(self):
        if self.jumlah == 0:
            raise ValueError("jumlah gerakan tidak boleh nol")
        if self.jenis is not JenisGerakan.PENYESUAIAN and self.jumlah < 0:
            raise ValueError("hanya penyesuaian yang boleh bernilai negatif")


@dataclass
class PetaSKU:
    """Menghubungkan SKU marketplace ke SKU internal."""
    _peta: dict[tuple[str, str, str], str] = field(default_factory=dict)

    def daftarkan(self, provider: str, id_toko: str,
                  sku_provider: str, sku_internal: str) -> None:
        self._peta[(provider, id_toko, sku_provider)] = sku_internal

    def internal(self, provider: str, id_toko: str, sku_provider: str) -> str | None:
        return self._peta.get((provider, id_toko, sku_provider))

    def kanal_untuk(self, sku_internal: str) -> list[tuple[str, str, str]]:
        return [k for k, v in self._peta.items() if v == sku_internal]


class BukuStok:
    """Catatan gerakan stok. Hanya bisa ditambah, tidak pernah diubah."""

    def __init__(self) -> None:
        self._gerakan: list[Gerakan] = []
        self._kunci: set[str] = set()
        self._penyangga: dict[tuple[str, str], int] = {}

    # ---- pencatatan ----
    def catat(self, g: Gerakan) -> None:
        if g.kunci in self._kunci:
            raise GerakanGanda(f"gerakan '{g.kunci}' sudah pernah dicatat")
        self._kunci.add(g.kunci)
        self._gerakan.append(g)

    def catat_bila_baru(self, g: Gerakan) -> bool:
        """True bila tercatat, False bila memang sudah pernah masuk."""
        try:
            self.catat(g)
            return True
        except GerakanGanda:
            return False

    # ---- angka turunan ----
    def fisik(self, sku: str) -> int:
        n = 0
        for g in self._gerakan:
            if g.sku != sku:
                continue
            if g.jenis in (JenisGerakan.MASUK, JenisGerakan.RETUR):
                n += g.jumlah
            elif g.jenis is JenisGerakan.KELUAR:
                n -= g.jumlah
            elif g.jenis is JenisGerakan.PENYESUAIAN:
                n += g.jumlah
        return n

    def reservasi_terbuka(self, sku: str) -> int:
        n = 0
        for g in self._gerakan:
            if g.sku != sku:
                continue
            if g.jenis is JenisGerakan.RESERVASI:
                n += g.jumlah
            elif g.jenis in (JenisGerakan.LEPAS, JenisGerakan.KELUAR):
                n -= g.jumlah
        return max(n, 0)

    def penyangga(self, sku: str, provider: str = "") -> int:
        return self._penyangga.get((sku, provider), 0)

    def atur_penyangga(self, sku: str, jumlah: int, provider: str = "") -> None:
        """Cadangan pengaman agar kanal tidak menjual unit terakhir bersamaan."""
        self._penyangga[(sku, provider)] = jumlah

    def tersedia(self, sku: str, provider: str = "") -> int:
        # penyangga umum berlaku untuk semua kanal; penyangga kanal
        # hanya ditambahkan bila provider disebut, agar tidak terpotong dua kali
        umum = self.penyangga(sku)
        kanal = self.penyangga(sku, provider) if provider else 0
        return max(
            self.fisik(sku) - self.reservasi_terbuka(sku) - umum - kanal,
            0,
        )

    # ---- alur pesanan ----
    def pesan(self, sku: str, jumlah: int, kunci: str,
              waktu: datetime, provider: str = "", sumber: str = "") -> bool:
        """Reservasi stok. Menolak bila tidak cukup. Aman diulang."""
        if kunci in self._kunci:
            return False
        ada = self.tersedia(sku, provider)
        if jumlah > ada:
            raise StokTidakCukup(
                f"{sku}: diminta {jumlah}, tersedia {ada} "
                f"(fisik {self.fisik(sku)}, dipesan {self.reservasi_terbuka(sku)})"
            )
        self.catat(Gerakan(sku, JenisGerakan.RESERVASI, jumlah, kunci,
                           waktu, sumber, "reservasi pesanan"))
        return True

    def kirim(self, sku: str, jumlah: int, kunci: str,
              waktu: datetime, sumber: str = "") -> bool:
        """Barang benar-benar keluar gudang; reservasinya ikut tertutup."""
        if kunci in self._kunci:
            return False
        self.catat(Gerakan(sku, JenisGerakan.KELUAR, jumlah, kunci,
                           waktu, sumber, "pengiriman"))
        return True

    def batalkan(self, sku: str, jumlah: int, kunci: str,
                 waktu: datetime, sumber: str = "") -> bool:
        if kunci in self._kunci:
            return False
        self.catat(Gerakan(sku, JenisGerakan.LEPAS, jumlah, kunci,
                           waktu, sumber, "pesanan dibatalkan"))
        return True

    # ---- penjelasan & sinkronisasi ----
    def riwayat(self, sku: str) -> list[Gerakan]:
        return [g for g in self._gerakan if g.sku == sku]

    def jelaskan(self, sku: str) -> str:
        baris = [f"  SKU {sku}"]
        for g in self.riwayat(sku):
            baris.append(f"    {g.waktu:%Y-%m-%d %H:%M}  {g.jenis.value:<12}"
                         f"{g.jumlah:>5}   {g.sumber or g.catatan}")
        baris.append(f"    -> fisik {self.fisik(sku)}, "
                     f"dipesan {self.reservasi_terbuka(sku)}, "
                     f"tersedia {self.tersedia(sku)}")
        return "\n".join(baris)

    def rencana_sinkron(self, peta: PetaSKU, sku: str) -> list[dict]:
        """Angka yang SEHARUSNYA dikirim ke tiap kanal.

        Hanya rencana. Pengiriman sebenarnya menunggu gerbang jaringan.
        """
        rencana = []
        for provider, id_toko, sku_provider in peta.kanal_untuk(sku):
            rencana.append({
                "provider": provider,
                "id_toko": id_toko,
                "sku_provider": sku_provider,
                "jumlah_target": self.tersedia(sku, provider),
            })
        return rencana
