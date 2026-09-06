"""Central Inventory Core service.

Semua operasi stok yang mengubah kuantitas WAJIB:
  1. dalam SATU transaksi PostgreSQL,
  2. mengunci baris master_sku (SELECT ... FOR UPDATE) agar dua kanal tidak
     oversell ON_HAND yang sama (atomic),
  3. menulis outbox SEBELUM commit (transactional outbox) supaya promosi ke
     marketplace dilakukan setelah kebenaran DB ditetapkan.

Invariant:
    AVAILABLE_TO_PROMISE = ON_HAND - RESERVED - SAFETY_STOCK  (>=0)
Marketplace hanya membaca/menetapkan AVAILABLE_TO_PROMISE sebagai proyeksi.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..persistence.db import koneksi as _pg_koneksi


def _now():
    return datetime.now(timezone.utc)


class StokTidakCukup(Exception):
    pass


# ============================================================ product core
def upsert_product(name: str, category: str = "", brand: str = "") -> dict:
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "INSERT INTO multichannel.product (name, category, brand) "
            "VALUES (%s,%s,%s) "
            "ON CONFLICT (name, category) DO UPDATE "
            "SET brand=EXCLUDED.brand, updated_at=now() RETURNING id, name, category",
            (name, category, brand),
        )
        r = cur.fetchone()
        c.commit()
        return r


def upsert_master_sku(
    sku: str, product_id: int, variant_id=None,
    barcode: str = "", safety_stock: int = 0,
) -> dict:
    """Buat/get MASTER_SKU (sumber kebenaran stok)."""
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "INSERT INTO multichannel.master_sku "
            "(sku, product_id, variant_id, barcode, safety_stock) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (sku) DO UPDATE SET barcode=EXCLUDED.barcode, "
            "safety_stock=EXCLUDED.safety_stock, updated_at=now() "
            "RETURNING id, sku, on_hand, reserved, safety_stock",
            (sku, product_id, variant_id, barcode, safety_stock),
        )
        r = cur.fetchone()
        c.commit()
        return r


def map_channel_sku(
    *, provider: str, shop_id: str, product_id_provider: str,
    channel_sku: str, master_sku_id: int, listing_name: str = "",
    extra: dict | None = None,
) -> dict:
    """Hubungkan SKU marketplace -> SATU MASTER_SKU (idempoten)."""
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO multichannel.channel_listing
               (provider, shop_id, product_id, listing_name)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (provider, shop_id, product_id) DO UPDATE
               SET listing_name=EXCLUDED.listing_name RETURNING id""",
            (provider, shop_id, product_id_provider, listing_name),
        )
        lid = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO multichannel.channel_sku_map
               (channel_listing_id, master_sku_id, provider, shop_id, channel_sku, extra)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (provider, shop_id, channel_sku) DO UPDATE
               SET master_sku_id=EXCLUDED.master_sku_id, extra=EXCLUDED.extra
               RETURNING id, master_sku_id, channel_sku""",
            (lid, master_sku_id, provider, shop_id, channel_sku,
             json.dumps(extra or {})),
        )
        r = cur.fetchone()
        cur.execute(
            """INSERT INTO multichannel.inventory_sync_state
               (channel_sku_map_id, master_sku_id, provider, shop_id, channel_sku, desired_qty)
               SELECT %s, %s, %s, %s, %s,
                      m.on_hand - m.reserved - m.safety_stock
               FROM multichannel.master_sku m WHERE m.id=%s
               ON CONFLICT (channel_sku_map_id) DO NOTHING""",
            (r["id"], master_sku_id, provider, shop_id, channel_sku, master_sku_id),
        )
        c.commit()
        return r


def resolve_master_sku(provider: str, shop_id: str, channel_sku: str) -> int:
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT master_sku_id FROM multichannel.channel_sku_map "
            "WHERE provider=%s AND shop_id=%s AND channel_sku=%s",
            (provider, shop_id, channel_sku),
        )
        r = cur.fetchone()
    if not r:
        raise KeyError(f"{provider}/{channel_sku} belum dipetakan ke master_sku")
    return r["master_sku_id"]


def atp(sku: str) -> int:
    """AVAILABLE_TO_PROMISE untuk satu MASTER_SKU."""
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT on_hand, reserved, safety_stock FROM multichannel.master_sku "
            "WHERE sku=%s", (sku,))
        r = cur.fetchone()
    if not r:
        raise KeyError(f"master_sku {sku} tidak ada")
    return max(r["on_hand"] - r["reserved"] - r["safety_stock"], 0)


def _enqueue_outbox_for_sku(cur, master_sku_id) -> None:
    """Tulis/refresh outbox PENDING untuk semua channel mapping SKU ini."""
    cur.execute(
        """INSERT INTO multichannel.inventory_sync_outbox
           (sync_state_id, provider, shop_id, channel_sku, master_sku_id, desired_qty, origin)
           SELECT ss.id, ss.provider, ss.shop_id, ss.channel_sku, ss.master_sku_id,
                  m.on_hand - m.reserved - m.safety_stock, 'inventory'
           FROM multichannel.channel_sku_map csm
           JOIN multichannel.inventory_sync_state ss ON ss.channel_sku_map_id=csm.id
           JOIN multichannel.master_sku m ON m.id=csm.master_sku_id
           WHERE csm.master_sku_id=%s AND (m.on_hand - m.reserved - m.safety_stock) >= 0
           ON CONFLICT (sync_state_id) DO UPDATE SET
             desired_qty=EXCLUDED.desired_qty,
             status='PENDING',
             attempts=0,
             created_at=now()""",
        (master_sku_id,))


# ============================================================ ATOMIC reservation
def reserve_order(
    *,
    provider: str, shop_id: str, order_sn: str, line_id: str,
    channel_sku: str, qty: int, event_seq: str,
    tenant_id: str = "default-tenant",
    raw_event: dict | None = None,
) -> dict:
    """Reservasi ATOMIK + idempoten untuk satu pesanan."""
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT m.id, m.sku, m.on_hand, m.reserved, m.safety_stock
               FROM multichannel.channel_sku_map csm
               JOIN multichannel.master_sku m ON m.id=csm.master_sku_id
               WHERE csm.provider=%s AND csm.shop_id=%s AND csm.channel_sku=%s
               FOR UPDATE OF m""",
            (provider, shop_id, channel_sku),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"channel_sku {provider}/{shop_id}/{channel_sku} belum dipetakan")
        mid, msku = row["id"], row["sku"]
        on_hand, reserved, safety = row["on_hand"], row["reserved"], row["safety_stock"]

        cur.execute(
            """SELECT id, status, qty FROM multichannel.inventory_reservation
               WHERE provider=%s AND shop_id=%s AND order_sn=%s AND line_id=%s AND event_seq=%s""",
            (provider, shop_id, order_sn, line_id, event_seq),
        )
        ada = cur.fetchone()
        if ada:
            c.rollback()
            return {"duplicate": True, "reservation_id": ada["id"],
                    "status": ada["status"], "qty": ada["qty"]}

        available = on_hand - reserved - safety
        if qty > available:
            raise StokTidakCukup(
                f"{msku}: diminta {qty}, tersedia {available} "
                f"(on_hand {on_hand}, reserved {reserved}, safety {safety})")

        cur.execute(
            "UPDATE multichannel.master_sku SET reserved=reserved+%s, "
            "version=version+1, updated_at=now() WHERE id=%s RETURNING reserved",
            (qty, mid))
        reserved_new = cur.fetchone()["reserved"]

        cur.execute(
            """INSERT INTO multichannel.inventory_reservation
               (tenant_id, provider, shop_id, order_sn, line_id, master_sku_id,
                channel_sku, qty, status, event_seq, raw_event)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'RESERVED',%s,%s)
               RETURNING id""",
            (tenant_id, provider, shop_id, order_sn, line_id, mid,
             channel_sku, qty, event_seq, json.dumps(raw_event or {}, default=str)))
        rid = cur.fetchone()["id"]

        cur.execute(
            """INSERT INTO multichannel.inventory_movement
               (master_sku_id, movement_type, qty, on_hand_after, reserved_after, available_after, reference)
               VALUES (%s,'RESERVASI',%s,%s,%s,%s,%s)""",
            (mid, qty, on_hand, reserved_new,
             max(on_hand - reserved_new - safety, 0),
             f"{provider}:{order_sn}:{line_id}"))

        _enqueue_outbox_for_sku(cur, mid)
        c.commit()
        return {"duplicate": False, "reservation_id": rid, "qty": qty,
                "available_after": max(on_hand - reserved_new - safety, 0)}


# ============================================================ lifecycle
def release_reservation(
    *, provider: str, shop_id: str, order_sn: str, line_id: str,
    event_seq: str, raw_event: dict | None = None,
) -> dict:
    """CANCEL: lepaskan RESERVED (ATP naik). Idempoten per event."""
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT r.id, r.qty, r.master_sku_id
               FROM multichannel.inventory_reservation r
               WHERE r.provider=%s AND r.shop_id=%s AND r.order_sn=%s
                 AND r.line_id=%s AND r.event_seq=%s AND r.status='RESERVED'
               FOR UPDATE OF r""",
            (provider, shop_id, order_sn, line_id, event_seq))
        r = cur.fetchone()
        if not r:
            cur.execute(
                """SELECT id, status FROM multichannel.inventory_reservation
                   WHERE provider=%s AND shop_id=%s AND order_sn=%s AND line_id=%s AND event_seq=%s""",
                (provider, shop_id, order_sn, line_id, event_seq))
            ada = cur.fetchone()
            c.rollback()
            return {"duplicate": True, "reservation_id": ada["id"] if ada else None,
                    "status": ada["status"] if ada else "NOT_FOUND"}
        mid, qty = r["master_sku_id"], r["qty"]
        cur.execute("SELECT on_hand, reserved, safety_stock FROM multichannel.master_sku WHERE id=%s FOR UPDATE",
                    (mid,))
        m = cur.fetchone()
        reserved_new = max(m["reserved"] - qty, 0)
        cur.execute("UPDATE multichannel.master_sku SET reserved=%s, version=version+1, updated_at=now() WHERE id=%s",
                    (reserved_new, mid))
        cur.execute("UPDATE multichannel.inventory_reservation SET status='RELEASED', updated_at=now() WHERE id=%s",
                    (r["id"],))
        cur.execute(
            """INSERT INTO multichannel.inventory_movement
               (master_sku_id, movement_type, qty, on_hand_after, reserved_after, available_after, reference)
               VALUES (%s,'LEPAS',%s,%s,%s,%s,%s)""",
            (mid, qty, m["on_hand"], reserved_new,
             max(m["on_hand"] - reserved_new - m["safety_stock"], 0),
             f"{provider}:{order_sn}:{line_id}"))
        _enqueue_outbox_for_sku(cur, mid)
        c.commit()
        return {"duplicate": False, "reservation_id": r["id"], "status": "RELEASED",
                "available_after": max(m["on_hand"] - reserved_new - m["safety_stock"], 0)}


def consume_reservation(
    *, provider: str, shop_id: str, order_sn: str, line_id: str,
    event_seq: str, qty: int = 0, raw_event: dict | None = None,
) -> dict:
    """SHIP: ON_HAND turun, RESERVED turun. ATP tidak melonjak."""
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT id, qty, master_sku_id FROM multichannel.inventory_reservation
             WHERE provider=%s AND shop_id=%s AND order_sn=%s AND line_id=%s AND event_seq=%s
               AND status='RESERVED' FOR UPDATE""",
            (provider, shop_id, order_sn, line_id, event_seq))
        r = cur.fetchone()
        if not r:
            c.rollback()
            return {"duplicate": True, "status": "NOT_RESERVED"}
        mid, rqty = r["master_sku_id"], r["qty"]
        consume = qty if qty else rqty
        cur.execute("SELECT * FROM multichannel.master_sku WHERE id=%s FOR UPDATE", (mid,))
        m = cur.fetchone()
        new_on_hand = max(m["on_hand"] - consume, 0)
        new_reserved = max(m["reserved"] - consume, 0)
        cur.execute("UPDATE multichannel.master_sku SET on_hand=%s, reserved=%s, version=version+1, updated_at=now() WHERE id=%s",
                    (new_on_hand, new_reserved, mid))
        cur.execute("UPDATE multichannel.inventory_reservation SET status='CONSUMED', updated_at=now() WHERE id=%s",
                    (r["id"],))
        cur.execute(
            """INSERT INTO multichannel.inventory_movement
               (master_sku_id, movement_type, qty, on_hand_after, reserved_after, available_after, reference)
               VALUES (%s,'KELUAR',%s,%s,%s,%s,%s)""",
            (mid, consume, new_on_hand, new_reserved,
             max(new_on_hand - new_reserved - m["safety_stock"], 0),
             f"{provider}:{order_sn}:{line_id}"))
        _enqueue_outbox_for_sku(cur, mid)
        c.commit()
        return {"duplicate": False, "reservation_id": r["id"], "status": "CONSUMED",
                "available_after": max(new_on_hand - new_reserved - m["safety_stock"], 0)}


def return_to_stock(
    *, provider: str, shop_id: str, order_sn: str, line_id: str,
    event_seq: str, master_sku_id: int, channel_sku: str, qty: int,
    raw_event: dict | None = None,
) -> dict:
    """RETURN: ON_HAND naik via movement RETUR. Idempoten per event."""
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute("SELECT on_hand, reserved, safety_stock FROM multichannel.master_sku WHERE id=%s FOR UPDATE",
                    (master_sku_id,))
        m = cur.fetchone()
        if not m:
            raise KeyError(f"master_sku {master_sku_id} tidak ada")
        cur.execute(
            """SELECT id FROM multichannel.inventory_reservation
               WHERE provider=%s AND shop_id=%s AND order_sn=%s AND line_id=%s AND event_seq=%s AND status='RETURNED'""",
            (provider, shop_id, order_sn, line_id, event_seq))
        if cur.fetchone():
            c.rollback()
            return {"duplicate": True}
        new_on_hand = m["on_hand"] + qty
        cur.execute("UPDATE multichannel.master_sku SET on_hand=%s, version=version+1, updated_at=now() WHERE id=%s",
                    (new_on_hand, master_sku_id))
        cur.execute(
            """INSERT INTO multichannel.inventory_reservation
               (tenant_id, provider, shop_id, order_sn, line_id, master_sku_id,
                channel_sku, qty, status, event_seq, raw_event)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'RETURNED',%s,%s)""",
            ("default-tenant", provider, shop_id, order_sn, line_id,
             master_sku_id, channel_sku, qty, event_seq,
             json.dumps(raw_event or {}, default=str)))
        cur.execute(
            """INSERT INTO multichannel.inventory_movement
               (master_sku_id, movement_type, qty, on_hand_after, reserved_after, available_after, reference)
               VALUES (%s,'RETUR',%s,%s,%s,%s,%s)""",
            (master_sku_id, qty, new_on_hand, m["reserved"],
             max(new_on_hand - m["reserved"] - m["safety_stock"], 0),
             f"{provider}:{order_sn}:{line_id}"))
        _enqueue_outbox_for_sku(cur, master_sku_id)
        c.commit()
        return {"duplicate": False, "available_after": max(new_on_hand - m["reserved"] - m["safety_stock"], 0)}


def adjust_stock(*, sku: str, delta_on_hand: int, reason: str = "", reference: str = "") -> dict:
    """PENYESUAIAN: ubah ON_HAND; hasil tidak boleh negatif."""
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute("SELECT id, on_hand, reserved, safety_stock FROM multichannel.master_sku WHERE sku=%s FOR UPDATE",
                    (sku,))
        m = cur.fetchone()
        if not m:
            raise KeyError(f"master_sku {sku} tidak ada")
        new_on_hand = m["on_hand"] + delta_on_hand
        if new_on_hand < 0:
            raise ValueError("on_hand tidak boleh negatif")
        cur.execute("UPDATE multichannel.master_sku SET on_hand=%s, version=version+1, updated_at=now() WHERE id=%s",
                    (new_on_hand, m["id"]))
        cur.execute("INSERT INTO multichannel.inventory_adjustment (master_sku_id, delta_on_hand, reason, reference) VALUES (%s,%s,%s,%s)",
                    (m["id"], delta_on_hand, reason, reference))
        cur.execute(
            """INSERT INTO multichannel.inventory_movement
               (master_sku_id, movement_type, qty, on_hand_after, reserved_after, available_after, reference)
               VALUES (%s,'PENYESUAIAN',%s,%s,%s,%s,%s)""",
            (m["id"], delta_on_hand, new_on_hand, m["reserved"],
             max(new_on_hand - m["reserved"] - m["safety_stock"], 0), reference))
        _enqueue_outbox_for_sku(cur, m["id"])
        c.commit()
        return {"sku": sku, "available_after": max(new_on_hand - m["reserved"] - m["safety_stock"], 0)}


def set_safety_stock(*, sku: str, safety_stock: int) -> dict:
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute("UPDATE multichannel.master_sku SET safety_stock=%s, version=version+1, updated_at=now() WHERE sku=%s RETURNING id, on_hand, reserved, safety_stock",
                    (safety_stock, sku))
        r = cur.fetchone()
        _enqueue_outbox_for_sku(cur, r["id"])
        c.commit()
        return {"sku": sku, "available_after": max(r["on_hand"] - r["reserved"] - safety_stock, 0)}


def set_on_hand(*, sku: str, on_hand: int, reason: str = "", reference: str = "") -> dict:
    """Atur ON_HAND ke nilai ABSOLUT (untuk seed/uji; hasil tak boleh negatif)."""
    with _pg_koneksi() as c:
        cur = c.cursor()
        cur.execute("SELECT id, on_hand, reserved, safety_stock FROM multichannel.master_sku WHERE sku=%s FOR UPDATE",
                    (sku,))
        m = cur.fetchone()
        if not m:
            raise KeyError(f"master_sku {sku} tidak ada")
        if on_hand < 0:
            raise ValueError("on_hand tidak boleh negatif")
        delta = on_hand - m["on_hand"]
        cur.execute("UPDATE multichannel.master_sku SET on_hand=%s, version=version+1, updated_at=now() WHERE id=%s",
                    (on_hand, m["id"]))
        if delta != 0:
            cur.execute("INSERT INTO multichannel.inventory_adjustment (master_sku_id, delta_on_hand, reason, reference) VALUES (%s,%s,%s,%s)",
                        (m["id"], delta, reason, reference))
            cur.execute(
                """INSERT INTO multichannel.inventory_movement
                   (master_sku_id, movement_type, qty, on_hand_after, reserved_after, available_after, reference)
                   VALUES (%s,'PENYESUAIAN',%s,%s,%s,%s,%s)""",
                (m["id"], delta, on_hand, m["reserved"],
                 max(on_hand - m["reserved"] - m["safety_stock"], 0), reference))
        _enqueue_outbox_for_sku(cur, m["id"])
        c.commit()
        return {"sku": sku, "on_hand": on_hand, "available_after": max(on_hand - m["reserved"] - m["safety_stock"], 0)}
