"""Repository penyimpanan multichannel.

Semua operasi tulis idempoten (ditegakkan kunci unik). Duplikat ulang
dikembalikan sebagai data yang sudah ada, bukan galat. Setiap perubahan
penting dicatat ke multichannel.audit_log.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from . import db


def _now():
    return datetime.now(timezone.utc)


def _hash(nilai: str) -> str:
    return hashlib.sha256((nilai or "").encode()).hexdigest()[:24]


# ------------------------------------------------------------ tenant
def pastikan_tenant(tenant_id: str) -> bool:
    """Sisipkan tenant bila belum ada. Aman diulang."""
    db.jalankan(
        "INSERT INTO multichannel.tenant (id) VALUES (%s) "
        "ON CONFLICT (id) DO NOTHING",
        (tenant_id,),
    )
    return True


def daftar_tenant() -> list[dict]:
    return db.semua(
        "SELECT id, created_at FROM multichannel.tenant ORDER BY created_at"
    )


# ------------------------------------------------------------ shop binding
def simpan_shop(
    *,
    tenant_id: str,
    provider: str,
    shop_id: str,
    shop_name: str = "",
    shop_region: str = "",
    status: str = "BELUM_TERHUBUNG",
    meta: dict | None = None,
    binding_origin: str = "PILOT",
) -> dict:
    """Idempoten: toko yang sama (provider+shop_id) tidak digandakan.

    `binding_origin`: 'REAL' hanya boleh dari OAuth+identitas toko nyata;
    'PILOT' menandai data sintetik/uji internal. PILOT tidak pernah
    tampil sebagai Terhubung di antarmuka produksi.
    """
    pastikan_tenant(tenant_id)
    r = db.ambil(
        "SELECT id FROM multichannel.shop "
        "WHERE provider=%s AND shop_id=%s",
        (provider, shop_id),
    )
    if r:
        db.jalankan(
            """UPDATE multichannel.shop
               SET shop_name=COALESCE(NULLIF(%s,''),shop_name),
                   shop_region=COALESCE(NULLIF(%s,''),shop_region),
                   status=COALESCE(NULLIF(%s,''),status),
                   shop_meta=COALESCE(%s,shop_meta),
                   binding_origin=%s,
                   connected_at=COALESCE(
                     CASE WHEN %s='TERHUBUNG' THEN now() END, connected_at),
                   updated_at=now()
               WHERE id=%s""",
            (shop_name, shop_region, status, json.dumps(meta or {}),
             binding_origin, status, r["id"]),
        )
        row = db.ambil(
            "SELECT * FROM multichannel.shop WHERE id=%s", (r["id"],)
        )
        return row

    db.jalankan(
        """INSERT INTO multichannel.shop
           (tenant_id, provider, shop_id, shop_name, shop_region, status,
            binding_origin, access_hash, shop_meta, connected_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (provider, shop_id) DO NOTHING""",
        (tenant_id, provider, shop_id, shop_name, shop_region, status,
         binding_origin, "", json.dumps(meta or {}),
         _now() if status == "TERHUBUNG" else None),
    )
    row = db.ambil(
        "SELECT * FROM multichannel.shop WHERE provider=%s AND shop_id=%s",
        (provider, shop_id),
    )
    return row


def simpan_token(
    *,
    tenant_id: str,
    provider: str,
    shop_id: str,
    access_token: str,
    refresh_token: str,
    access_expires,
    access_issued=None,
) -> dict:
    """Simpan token OAuth (dienkripsi di aplikasi pemanggil; di sini hanya
    sidik jari + timestamp). Tidak pernah mengembalikan nilai token."""
    r = db.ambil(
        "SELECT id FROM multichannel.shop WHERE provider=%s AND shop_id=%s",
        (provider, shop_id),
    )
    if not r:
        raise ValueError("shop belum ada; simpan_shop dulu")
    db.jalankan(
        """INSERT INTO multichannel.shop_token
           (shop_id, provider, tenant_id, access_cipher, refresh_cipher,
            access_hash, refresh_hash, access_issued_at, access_expires_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (shop_id) DO UPDATE SET
             access_hash=EXCLUDED.access_hash,
             refresh_hash=EXCLUDED.refresh_hash,
             access_expires_at=EXCLUDED.access_expires_at,
             updated_at=now()""",
        (r["id"], provider, tenant_id,
         _cipher(access_token), _cipher(refresh_token),
         _hash(access_token), _hash(refresh_token),
         access_issued or _now(), access_expires),
    )
    # jaga akses_hash di shop agar status terlihat tanpa membuka token
    db.jalankan(
        "UPDATE multichannel.shop SET access_hash=%s, access_expires_at=%s "
        "WHERE id=%s",
        (_hash(access_token), access_expires, r["id"]),
    )
    return {"shop_id": shop_id, "saved": True}


def _cipher(nilai: str) -> bytes:
    """Enkripsi token dengan Fernet (AES-128-CBC + HMAC).

    Kunci diturunkan dari env BC_TOKEN_ENCRYPTION_KEY (32 byte hex) atau
    default hanya untuk pilot. Nilai token tidak pernah dikembalikan API.
    """
    from cryptography.fernet import Fernet
    import os
    key = os.environ.get(
        "BC_TOKEN_ENCRYPTION_KEY",
        "k7Pq2wErT5yU8i9OpL0zXcVbNm12345678",
    ).encode()
    key = key[:32].ljust(32, b"_")
    f = Fernet(_b64(key))
    return f.encrypt(nilai.encode())


def _b64(raw: bytes) -> bytes:
    import base64
    return base64.urlsafe_b64encode(raw)


def ambil_shop(provider: str, shop_id: str) -> dict | None:
    return db.ambil(
        "SELECT * FROM multichannel.shop WHERE provider=%s AND shop_id=%s",
        (provider, shop_id),
    )


def daftar_shop(tenant_id: str, provider: str = "") -> list[dict]:
    if provider:
        return db.semua(
            "SELECT * FROM multichannel.shop WHERE tenant_id=%s AND provider=%s "
            "ORDER BY shop_name, shop_id",
            (tenant_id, provider),
        )
    return db.semua(
        "SELECT * FROM multichannel.shop WHERE tenant_id=%s ORDER BY provider, shop_id",
        (tenant_id,),
    )


def pemilik_shop(provider: str, shop_id: str) -> dict | None:
    """Siapa (tenant) yang memiliki toko ini. Dipakai cegah toko ganda."""
    return db.ambil(
        "SELECT tenant_id FROM multichannel.shop "
        "WHERE provider=%s AND shop_id=%s AND status='TERHUBUNG'",
        (provider, shop_id),
    )


# ------------------------------------------------------------ OAuth state
def buat_state(tenant_id: str, provider: str, state: str, ttl_detik: int = 600) -> bool:
    db.jalankan(
        """INSERT INTO multichannel.oauth_state
           (state, tenant_id, provider, created_at, expires_at)
           VALUES (%s,%s,%s,now(), now() + make_interval(secs => %s))""",
        (state, tenant_id, provider, ttl_detik),
    )
    return True


def konsumsi_state(state: str) -> dict | None:
    """Ambil dan tandai used bila valid. Idempoten: digunakan hanya sekali."""
    r = db.ambil(
        "SELECT * FROM multichannel.oauth_state WHERE state=%s", (state,)
    )
    if not r:
        return None
    if r["used"]:
        return None
    if r["expires_at"] and r["expires_at"] < _now():
        return None
    db.jalankan(
        "UPDATE multichannel.oauth_state SET used=TRUE, consumed_at=now() "
        "WHERE state=%s AND used=FALSE",
        (state,),
    )
    return r


# ------------------------------------------------------------ order
def simpan_order(
    *,
    tenant_id: str,
    provider: str,
    shop_id: str,
    order_sn: str,
    order_status: str,
    order_status_normalized: str,
    total_amount: str | int | float,
    currency: str = "IDR",
    buyer_username: str = "",
    buyer_name: str = "",
    item_count: int = 0,
    raw: dict | None = None,
) -> dict:
    """Idempoten. Pesanan yang sama (provider+shop+order_sn) tidak diduplikasi.

    Bila sudah ada, perbarui status/total dan kembalikan baris dengan
    tanda 'duplicate': True (untuk bukti replay).
    """
    r = db.ambil(
        "SELECT * FROM multichannel.order WHERE provider=%s AND shop_id=%s AND order_sn=%s",
        (provider, shop_id, order_sn),
    )
    if r:
        db.jalankan(
            """UPDATE multichannel.order
               SET order_status=%s, order_status_normalized=%s,
                   total_amount=%s, currency=%s,
                   buyer_username=COALESCE(NULLIF(%s,''),buyer_username),
                   buyer_name=COALESCE(NULLIF(%s,''),buyer_name),
                   item_count=%s, raw_payload=%s, updated_at=now()
               WHERE id=%s""",
            (order_status, order_status_normalized, total_amount, currency,
             buyer_username, buyer_name, item_count,
             json.dumps(raw or {}), r["id"]),
        )
        row = db.ambil("SELECT * FROM multichannel.order WHERE id=%s", (r["id"],))
        row["duplicate"] = True
        return row

    db.jalankan(
        """INSERT INTO multichannel.order
           (tenant_id, provider, shop_id, order_sn, order_status,
            order_status_normalized, total_amount, currency,
            buyer_username, buyer_name, item_count, raw_payload)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (provider, shop_id, order_sn) DO NOTHING""",
        (tenant_id, provider, shop_id, order_sn, order_status,
         order_status_normalized, total_amount, currency,
         buyer_username, buyer_name, item_count, json.dumps(raw or {})),
    )
    row = db.ambil(
        "SELECT * FROM multichannel.order WHERE provider=%s AND shop_id=%s AND order_sn=%s",
        (provider, shop_id, order_sn),
    )
    row["duplicate"] = False
    return row


def ambil_order(provider: str, shop_id: str, order_sn: str) -> dict | None:
    return db.ambil(
        "SELECT * FROM multichannel.order WHERE provider=%s AND shop_id=%s AND order_sn=%s",
        (provider, shop_id, order_sn),
    )


def daftar_order(provider: str, shop_id: str = "", status: str = "") -> list[dict]:
    if shop_id and status:
        return db.semua(
            "SELECT * FROM multichannel.order WHERE provider=%s AND shop_id=%s AND order_status=%s "
            "ORDER BY first_seen_at DESC",
            (provider, shop_id, status),
        )
    if shop_id:
        return db.semua(
            "SELECT * FROM multichannel.order WHERE provider=%s AND shop_id=%s "
            "ORDER BY first_seen_at DESC",
            (provider, shop_id),
        )
    return db.semua(
        "SELECT * FROM multichannel.order WHERE provider=%s ORDER BY first_seen_at DESC",
        (provider,),
    )


def hitung_order(provider: str = "") -> int:
    if provider:
        r = db.ambil(
            "SELECT count(*) AS n FROM multichannel.order WHERE provider=%s",
            (provider,),
        )
    else:
        r = db.ambil("SELECT count(*) AS n FROM multichannel.order")
    return int(r["n"])


# ------------------------------------------------------------ settlement
def simpan_settlement(
    *,
    tenant_id: str,
    provider: str,
    shop_id: str,
    settlement_ref: str,
    trans_id: str = "",
    transaction_date,
    gross: int | float,
    fee: int | float,
    net: int | float,
    raw: dict | None = None,
) -> dict:
    r = db.ambil(
        "SELECT * FROM multichannel.settlement WHERE provider=%s AND shop_id=%s AND settlement_ref=%s",
        (provider, shop_id, settlement_ref),
    )
    if r:
        r["duplicate"] = True
        return r
    db.jalankan(
        """INSERT INTO multichannel.settlement
           (tenant_id, provider, shop_id, settlement_ref, trans_id,
            transaction_date, gross_amount, fee_amount, net_amount, raw_payload)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (provider, shop_id, settlement_ref) DO NOTHING""",
        (tenant_id, provider, shop_id, settlement_ref, trans_id,
         transaction_date, gross, fee, net, json.dumps(raw or {})),
    )
    row = db.ambil(
        "SELECT * FROM multichannel.settlement WHERE provider=%s AND shop_id=%s AND settlement_ref=%s",
        (provider, shop_id, settlement_ref),
    )
    row["duplicate"] = False
    return row


def daftar_settlement(provider: str = "", shop_id: str = "") -> list[dict]:
    if shop_id:
        return db.semua(
            "SELECT * FROM multichannel.settlement WHERE provider=%s AND shop_id=%s "
            "ORDER BY transaction_date DESC, id DESC",
            (provider, shop_id),
        )
    if provider:
        return db.semua(
            "SELECT * FROM multichannel.settlement WHERE provider=%s ORDER BY id DESC",
            (provider,),
        )
    return db.semua(
        "SELECT * FROM multichannel.settlement ORDER BY id DESC"
    )


# ------------------------------------------------------------ audit
def catat_audit(
    event_type: str,
    *,
    actor: str = "",
    tenant_id: str = "",
    provider: str = "",
    shop_id: str = "",
    payload: dict | None = None,
) -> None:
    db.jalankan(
        """INSERT INTO multichannel.audit_log
           (event_type, actor, tenant_id, provider, shop_id, payload)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (event_type, actor, tenant_id, provider, shop_id,
         json.dumps(payload or {})),
    )


def baca_audit(n: int = 50) -> list[dict]:
    return db.semua(
        "SELECT * FROM multichannel.audit_log ORDER BY id DESC LIMIT %s",
        (n,),
    )
