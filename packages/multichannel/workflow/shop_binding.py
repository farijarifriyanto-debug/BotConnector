"""Alur sambungan toko Shopee — terikat persistence (bukan memori).

Menggantikan GudangSambungan berbasis memori dengan penyimpanan permanen
di `botconnector` DB. Alur otorisasi tetap memakai mesin keadaan, tetapi
state dan sambungan disimpan di tabel `multichannel`.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..activation.kontrak import (
    GerbangTertutup,
    boleh_jaringan,
    muat,
)
from ..persistence import repo
from ..shop import client, signing
from ..shop.transport import Transport


def _now():
    return datetime.now(timezone.utc)


def _kredensial():
    """Ambil partner_id/partner_key dari berkas credential bila diizinkan."""
    from ..activation.kredensial import muat_kredensial
    k = muat_kredensial()
    return k.partner_id, k.partner_key.buka()


def mulai_otorisasi(
    *,
    tenant_id: str,
    provider: str = "shopee",
    redirect_uri: str,
) -> dict:
    """Buat state acak sekali pakai dan URL otorisasi Shopee.

    Menolak bila kontrak aktivasi belum lolos (belum ada toko kanari,
    belum disetujui, dll).
    """
    # pastikan gerbang lolos (membuang pesan bila belum)
    from ..activation.kontrak import boleh_jaringan, periksa_syarat
    kurang = [x.nama for x in periksa_syarat() if not x.lolos]
    if kurang:
        raise GerbangTertutup(f"{len(kurang)} syarat belum terpenuhi: "
                              f"{'; '.join(kurang[:4])}")

    state = secrets.token_urlsafe(32)
    repo.buat_state(tenant_id=tenant_id, provider=provider,
                    state=state, ttl_detik=600)

    partner_id, partner_key = _kredensial()
    url = client.url_otorisasi(
        partner_id=partner_id,
        partner_key=partner_key.encode(),
        redirect=redirect_uri,
        state=state,
    )
    repo.catat_audit(
        "otorisasi_diminta",
        tenant_id=tenant_id, provider=provider,
        payload={"state": state[:8] + "...", "url_created": True},
    )
    return {"state": state, "url": url}


def terima_callback(
    *,
    tenant_id: str,
    provider: str,
    state: str,
    code: str,
    shop_id: str,
    transport: Transport,
) -> dict:
    """Tukar kode jadi token, simpan shop binding, tandai TERHUBUNG.

    Idempoten: state hanya dipakai sekali; toko yang sama tidak
    dimiliki dua tenant.
    """
    st = repo.konsumsi_state(state)
    if not st:
        raise ValueError("state tidak dikenal, sudah dipakai, atau kedaluwarsa")

    # cegah toko milik tenant lain
    pemilik = repo.pemilik_shop(provider, shop_id)
    if pemilik and pemilik["tenant_id"] != tenant_id:
        repo.catat_audit("callback_ditolak", tenant_id=tenant_id,
                         provider=provider, shop_id=shop_id,
                         payload={"alasan": "toko milik tenant lain"})
        raise ValueError(f"toko {shop_id} sudah terhubung ke tenant lain")

    # existing connected shop -> idempoten, kembalikan yang lama
    lama = repo.ambil_shop(provider, shop_id)
    if lama and lama["status"] == "TERHUBUNG":
        repo.catat_audit("callback_diulang", tenant_id=tenant_id,
                         provider=provider, shop_id=shop_id)
        return lama

    from ..activation.kontrak import boleh_jaringan
    boleh_jaringan()

    pid, kode = _kredensial()
    hasil = client.tukar_kode(
        transport,
        partner_id=pid,
        partner_key=kode.encode(),
        code=code,
        shop_id=shop_id,
    )
    access = hasil.get("access_token", "")
    refresh = hasil.get("refresh_token", "")
    expire = int(hasil.get("expire_in", 14400))

    if not access or not refresh:
        repo.catat_audit("callback_gagal", tenant_id=tenant_id,
                         provider=provider, shop_id=shop_id,
                         payload={"detail": "token kosong"})
        raise ValueError("token exchange tidak mengembalikan token")

    kini = _now()
    repo.simpan_shop(
        tenant_id=tenant_id, provider=provider, shop_id=shop_id,
        status="TERHUBUNG",
        binding_origin="REAL",           # dari OAuth token exchange nyata
        meta={"oauth_exchanged": True},
    )
    repo.simpan_token(
        tenant_id=tenant_id, provider=provider, shop_id=shop_id,
        access_token=access, refresh_token=refresh,
        access_issued=kini,
        access_expires=kini + timedelta(seconds=expire),
    )
    repo.catat_audit("tersambung", tenant_id=tenant_id, provider=provider,
                     shop_id=shop_id)
    row = repo.ambil_shop(provider, shop_id)
    return row


def ambil_toko_terhubung(tenant_id: str, provider: str = "shopee"):
    """Toko yang benar-benar terhubung (binding REAL) untuk tenant."""
    for s in repo.daftar_shop(tenant_id, provider):
        if s["status"] == "TERHUBUNG" and s.get("binding_origin") == "REAL":
            return s
    return None


def keadaan(tenant_id: str, provider: str = "shopee") -> dict:
    """Keadaan kartu integrasi dari DB nyata.

    Hanya binding REAL (dari OAuth+identitas toko nyata) yang boleh
    tampil sebagai "Terhubung". PILOT/sintetik TIDAK pernah membuat
    antarmuka produksi tampak terhubung dengan Shopee asli.
    """
    tokos = repo.daftar_shop(tenant_id, provider)
    real = [s for s in tokos
            if s["status"] == "TERHUBUNG" and s.get("binding_origin") == "REAL"]
    if real:
        s = real[0]
        return {
            "provider": provider,
            "status": "Terhubung",
            "toko": s["shop_name"] or s["shop_id"],
            "sinkron_otomatis": "Aktif",
            "tombol": "Pengaturan",
            "shop_id": s["shop_id"],
            "terhubung_pada": str(s.get("connected_at") or ""),
        }
    # Ada toko PILOT/sintetik internal — tetap tampil belum terhubung
    # ke mata pengguna, tidak bocor sebagai real.
    if tokos:
        return {"provider": provider, "status": "Belum terhubung",
                "tombol": "Hubungkan Shopee", "shop_id": "",
                "_internal_pilot_present": True}
    return {"provider": provider, "status": "Belum terhubung",
            "tombol": "Hubungkan Shopee", "shop_id": ""}
