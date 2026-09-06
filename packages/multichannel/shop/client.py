"""Klien Shopee Open Platform (lapisan aktivasi produksi).

Lapisan baru DI ATAS foundation offline yang beku. Foundation tidak
diubah; klien ini menyediakan pemanggilan read-only yang sebenarnya
sesuai dokumentasi Open Platform terkini:

  - url otorisasi   : GET https://partner.shopeemobile.com/api/v2/shop/auth_partner
  - tukar kode token: POST /api/v2/auth/token/get  {code, shop_id, partner_id}
  - identitas toko   : GET /api/v2/shop/get_shop_info
  - daftar pesanan   : GET /api/v2/order/get_order_list
  - detail pesanan   : GET /api/v2/order/get_order_detail

Semua lewat transport berpagar; tanda memakai `signing`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from ..activation.kontrak import GerbangTertutup, muat
from ..persistence import repo
from . import signing
from .transport import Transport


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def url_otorisasi(
    *,
    partner_id: str,
    partner_key: bytes,
    redirect: str,
    state: str,
    base: str = "https://partner.shopeemobile.com",
    path: str = "/api/v2/shop/auth_partner",
) -> str:
    """Susun URL otorisasi Shopee (dokumentasi terkini)."""
    cap = _now()
    tanda = signing.sign_public(partner_id, path, cap, partner_key)
    q = urlencode({
        "partner_id": partner_id,
        "timestamp": cap,
        "sign": tanda,
        "redirect": redirect,
        "state": state,
    })
    return f"{base}{path}?{q}"


def tukar_kode(
    transport: Transport,
    *,
    partner_id: str,
    partner_key: bytes,
    code: str,
    shop_id: str,
) -> dict:
    """POST /api/v2/auth/token/get -> {access_token, refresh_token, shop_id, expire_in}."""
    path = "/api/v2/auth/token/get"
    cap = _now()
    tanda = signing.sign_public(partner_id, path, cap, partner_key)
    q = {
        "partner_id": partner_id,
        "timestamp": cap,
        "sign": tanda,
    }
    isi = {
        "code": code,
        "shop_id": int(shop_id),
        "partner_id": int(partner_id),
    }
    jawab = transport.panggil("POST", path, id_toko="", query=q, isi=isi)
    return _norm(jawab)


def segarkan_token(
    transport: Transport,
    *,
    partner_id: str,
    partner_key: bytes,
    refresh_token: str,
    shop_id: str,
) -> dict:
    """POST /api/v2/auth/access_token/get -> token baru (refresh)."""
    path = "/api/v2/auth/access_token/get"
    cap = _now()
    tanda = signing.sign_public(partner_id, path, cap, partner_key)
    q = {
        "partner_id": partner_id,
        "timestamp": cap,
        "sign": tanda,
    }
    isi = {
        "refresh_token": refresh_token,
        "shop_id": int(shop_id),
        "partner_id": int(partner_id),
    }
    jawab = transport.panggil("POST", path, id_toko="", query=q, isi=isi)
    return _norm(jawab)


def ambil_toko(
    transport: Transport,
    *,
    partner_id: str,
    partner_key: bytes,
    access_token: str,
    shop_id: str,
) -> dict:
    """GET /api/v2/shop/get_shop_info -> identitas toko."""
    path = "/api/v2/shop/get_shop_info"
    cap = _now()
    q = signing.query_params(
        partner_id, path, cap, partner_key, access_token, shop_id,
    )
    jawab = transport.panggil("GET", path, id_toko=shop_id, query=q)
    return _norm(jawab)


def daftar_pesanan(
    transport: Transport,
    *,
    partner_id: str,
    partner_key: bytes,
    access_token: str,
    shop_id: str,
    time_from: int,
    time_to: int,
    order_status: str = "",
    page: int = 0,
    page_size: int = 20,
) -> dict:
    """GET /api/v2/order/get_order_list."""
    path = "/api/v2/order/get_order_list"
    cap = _now()
    q = signing.query_params(
        partner_id, path, cap, partner_key, access_token, shop_id,
    )
    q["time_range_field"] = "create_time"
    q["time_from"] = time_from
    q["time_to"] = time_to
    q["page_size"] = page_size
    q["page_no"] = page
    if order_status:
        q["order_status"] = order_status
    jawab = transport.panggil("GET", path, id_toko=shop_id, query=q)
    return _norm(jawab)


def detail_pesanan(
    transport: Transport,
    *,
    partner_id: str,
    partner_key: bytes,
    access_token: str,
    shop_id: str,
    order_sn: str,
) -> dict:
    """GET /api/v2/order/get_order_detail."""
    path = "/api/v2/order/get_order_detail"
    cap = _now()
    q = signing.query_params(
        partner_id, path, cap, partner_key, access_token, shop_id,
    )
    q["order_sn_list"] = order_sn
    q["response_optional_fields"] = "buyer_user_name,item_list"
    jawab = transport.panggil("GET", path, id_toko=shop_id, query=q)
    return _norm(jawab)


def _norm(jawab):
    """Normalisasi jawaban transport (bisa objek atau dict)."""
    if hasattr(jawab, "json"):
        return jawab.json()
    if hasattr(jawab, "get"):
        return jawab
    return jawab
