"""Penandatanganan Shopee berdasarkan dokumentasi Open Platform terkini.

Dokumen resmi Shopee Open Platform (developer-guide, 2026) menetapkan
tanda HMAC-SHA256 dengan base string:

  panggilan publik (token exchange):
      base = partner_id + path + timestamp
      sign = HMAC-SHA256(base, partner_key)

  panggilan yang mewakili toko (identitas/pesanan):
      base = partner_id + path + timestamp + access_token + shop_id
      sign = HMAC-SHA256(base, partner_key)

Modul ini MURNI komputasi; tidak melakukan jaringan apa pun.
"""

from __future__ import annotations

import hashlib
import hmac


def _key_bytes(key) -> bytes:
    if not isinstance(key, bytes):
        raise ValueError("partner_key harus bytes")
    if len(key) < 16:
        raise ValueError("partner_key terlalu pendek (<16)")
    return key


def sign_public(partner_id: str, path: str, timestamp: int, partner_key: bytes) -> str:
    """Tanda untuk panggilan publik (token get, auth partner)."""
    base = f"{partner_id}{path}{timestamp}"
    return hmac.new(_key_bytes(partner_key), base.encode(), hashlib.sha256).hexdigest()


def sign_shop(
    partner_id: str,
    path: str,
    timestamp: int,
    partner_key: bytes,
    access_token: str,
    shop_id: str,
) -> str:
    """Tanda untuk panggilan yang mewakili toko."""
    base = f"{partner_id}{path}{timestamp}{access_token}{shop_id}"
    return hmac.new(_key_bytes(partner_key), base.encode(), hashlib.sha256).hexdigest()


def query_params(
    partner_id: str,
    path: str,
    timestamp: int,
    partner_key: bytes,
    access_token: str = "",
    shop_id: str = "",
) -> dict:
    """Kueri standar Shopee untuk sebuah panggilan."""
    if access_token and shop_id:
        tanda = sign_shop(
            partner_id, path, timestamp, partner_key, access_token, shop_id,
        )
    else:
        tanda = sign_public(partner_id, path, timestamp, partner_key)
    q = {
        "partner_id": partner_id,
        "timestamp": timestamp,
        "sign": tanda,
    }
    if access_token:
        q["access_token"] = access_token
    if shop_id:
        q["shop_id"] = shop_id
    return q
