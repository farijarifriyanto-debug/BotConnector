"""API integrasi multichannel — endpoint baca untuk /integrasi.

Hanya READ. Menyajikan keadaan nyata dari basis data (tenant/toko/pesanan/
settlement) dan status aktivasi Shopee. Tidak pernah melakukan panggilan
keluar; tidak pernah membuka token.

Rute:
  GET /api/integrasi/state        -> kartu integrasi per provider
  GET /api/integrasi/shops        -> daftar toko terhubung
  GET /api/integrasi/orders       -> pesanan ternormalisasi
  GET /api/integrasi/settlements  -> settlement
  GET /api/integrasi/status       -> status aktivasi + gerbang
"""

from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from ..persistence import repo
from ..workflow import shop_binding
from ..activation.kontrak import bukti, periksa_syarat
from ..connector import registry as connector_registry
from ..inventory import service as inv_service

APP = FastAPI(title="BotConnector Integrasi API", version="1.0.0")

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


_PROVIDERS = ["shopee", "tokopedia", "tiktok_shop", "blibli", "lazada"]


def _provider_kar(tenant_id: str, provider: str) -> dict:
    return shop_binding.keadaan(tenant_id, provider)


@APP.get("/api/integrasi/state")
def state(tenant: str = "default-tenant"):
    """Kartu integrasi untuk semua provider (read-only, dari DB)."""
    providers = []
    for p in _PROVIDERS:
        kartu = _provider_kar(tenant, p)
        c = connector_registry.get(p)
        status = c.status_report() if c else {}
        kartu["connector_status"] = {
            "readiness": status.get("readiness", "unknown"),
            "blocker": status.get("blocker", ""),
        }
        providers.append(kartu)
    return {
        "ok": True,
        "tenant": tenant,
        "providers": providers,
    }


@APP.get("/api/integrasi/inventory")
def inventory(tenant: str = "default-tenant"):
    """Tampilan pusat inventory: master SKU + mapping + sync state (read-only)."""
    from ..persistence import db as _db
    with _db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT m.sku, m.on_hand, m.reserved, m.safety_stock,
                      (m.on_hand - m.reserved - m.safety_stock) AS available
               FROM multichannel.master_sku m
               ORDER BY m.sku"""
        )
        skus = cur.fetchall()
        # channel mappings + sync state
        cur.execute(
            """SELECT csm.provider, csm.shop_id, csm.channel_sku,
                      ss.desired_qty, ss.remote_qty, ss.status AS sync_status,
                      ss.last_write_at, ss.last_read_at, ss.last_error
               FROM multichannel.channel_sku_map csm
               JOIN multichannel.master_sku m ON m.id=csm.master_sku_id
               LEFT JOIN multichannel.inventory_sync_state ss ON ss.channel_sku_map_id=csm.id
               ORDER BY csm.provider, csm.channel_sku"""
        )
        maps = cur.fetchall()
    return {"ok": True, "skus": skus, "channel_mappings": maps}


@APP.get("/api/integrasi/shops")
def shops(tenant: str = "default-tenant"):
    return {"ok": True, "shops": repo.daftar_shop(tenant)}


@APP.get("/api/integrasi/orders")
def orders(provider: str = "", tenant: str = "default-tenant"):
    rows = repo.daftar_order(provider) if provider else repo.daftar_order()
    return {"ok": True, "count": len(rows), "orders": rows}


@APP.get("/api/integrasi/settlements")
def settlements(provider: str = ""):
    rows = repo.daftar_settlement(provider)
    return {"ok": True, "count": len(rows), "settlements": rows}


@APP.get("/api/integrasi/status")
def status(tenant: str = "default-tenant"):
    syarat = periksa_syarat()
    return {
        "ok": True,
        "aktivasi": {
            "syarat_lolos": sum(1 for s in syarat if s.lolos),
            "syarat_total": len(syarat),
            "belum_lolos": [s.nama for s in syarat if not s.lolos],
        },
        "kredensial": _kredensial_ringkas(),
        "gerbang": _app_bukti(),
    }


def _kredensial_ringkas() -> dict:
    from ..activation.kredensial import periksa_berkas
    b = periksa_berkas()
    b.pop("jalur", None)
    return b


def _app_bukti() -> dict:
    from ..activation.kontrak import bukti
    b = bukti()
    b.pop("host_diizinkan", None)
    b.pop("toko_kanari", None)
    return b


@APP.get("/health")
def health():
    return {"ok": True, "service": "botconnector-integrasi-api", "state": "read-only"}
