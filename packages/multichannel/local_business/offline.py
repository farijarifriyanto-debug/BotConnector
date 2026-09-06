"""Offline-first PWA support: durable queue, allowance, idempotent sync.

Server/PostgreSQL remains canonical. The browser holds only a local queue.
Every offline operation carries device_id + client_event_id; replay is
idempotent (unique constraints prevent duplicates).

Offline stock safety: server grants a bounded offline sell allowance per
SKU/location/register. Offline devices can only commit local sales within
their valid allowance. When online returns, queued transactions replay
idempotently and unused allowance expires.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..persistence.db import koneksi as _pg
from . import core
from . import inventory as inv


def _now():
    return datetime.now(timezone.utc)


# ============================================================ offline queue
def enqueue_offline_event(
    *, tenant_id: str, business_id: int, branch_id: int, register_id: int,
    device_id: str, client_event_id: str, event_type: str, payload: dict,
    created_at_client=None,
) -> dict:
    """Enqueue an offline event. Idempotent per (business, device, event)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.offline_queue
               (tenant_id, business_id, branch_id, register_id, device_id,
                client_event_id, event_type, payload, status, created_at_client)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'LOCAL_PENDING',%s)
               ON CONFLICT (business_id, device_id, client_event_id) DO NOTHING
               RETURNING id, status""",
            (tenant_id, business_id, branch_id, register_id, device_id,
             client_event_id, event_type, __import__("json").dumps(payload, default=str),
             created_at_client))
        r = cur.fetchone()
        c.commit()
        if not r:
            return {"duplicate": True}
        return {"duplicate": False, "queue_id": r["id"], "status": r["status"]}


def list_pending_offline(business_id: int) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM local_business.offline_queue
               WHERE business_id=%s AND status='LOCAL_PENDING' ORDER BY id""",
            (business_id,))
        return cur.fetchall()


def mark_offline_synced(queue_id: int, business_id: int | None = None) -> None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE local_business.offline_queue SET status='SYNCED', synced_at=now()
               WHERE id=%s AND (%s IS NULL OR business_id=%s)""",
            (queue_id, business_id, business_id))
        c.commit()


def mark_offline_rejected(queue_id: int, error: str, business_id: int | None = None) -> None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE local_business.offline_queue SET status='REJECTED', error=%s
               WHERE id=%s AND (%s IS NULL OR business_id=%s)""",
            (error[:500], queue_id, business_id, business_id))
        c.commit()


# ============================================================ offline allowance
def grant_allowance(*, business_id: int, branch_id: int, register_id: int,
                    master_sku_id: int, allowance: int, ttl_hours: int = 24) -> dict:
    """Grant a bounded offline sell allowance for a SKU at a register."""
    if allowance < 0:
        raise ValueError("allowance tidak boleh negatif")
    expires = _now() + timedelta(hours=ttl_hours)
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.offline_allowance
               (business_id, branch_id, register_id, master_sku_id, allowance, expires_at)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (register_id, master_sku_id) DO UPDATE SET
                 allowance=EXCLUDED.allowance, expires_at=EXCLUDED.expires_at,
                 updated_at=now()
               RETURNING id, allowance, used, expires_at""",
            (business_id, branch_id, register_id, master_sku_id, allowance, expires))
        r = cur.fetchone()
        c.commit()
        return r


def allowance_remaining(register_id: int, master_sku_id: int) -> int:
    """Remaining offline allowance for a SKU at a register (0 if expired)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT allowance, used, expires_at FROM local_business.offline_allowance
               WHERE register_id=%s AND master_sku_id=%s""",
            (register_id, master_sku_id))
        r = cur.fetchone()
        if not r:
            return 0
        if r["expires_at"] and r["expires_at"] < _now():
            return 0
        return max(r["allowance"] - r["used"], 0)


def consume_allowance(register_id: int, master_sku_id: int, qty: int) -> bool:
    """Atomically consume offline allowance. Returns False if insufficient/expired."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT allowance, used, expires_at FROM local_business.offline_allowance
               WHERE register_id=%s AND master_sku_id=%s FOR UPDATE""",
            (register_id, master_sku_id))
        r = cur.fetchone()
        if not r:
            c.rollback()
            return False
        if r["expires_at"] and r["expires_at"] < _now():
            c.rollback()
            return False
        if r["used"] + qty > r["allowance"]:
            c.rollback()
            return False
        cur.execute(
            "UPDATE local_business.offline_allowance SET used=used+%s, updated_at=now() WHERE register_id=%s AND master_sku_id=%s",
            (qty, register_id, master_sku_id))
        c.commit()
        return True


def release_allowance(register_id: int, master_sku_id: int, qty: int) -> None:
    """Release unused allowance (e.g. on void/return)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "UPDATE local_business.offline_allowance SET used=GREATEST(used-%s,0), updated_at=now() WHERE register_id=%s AND master_sku_id=%s",
            (qty, register_id, master_sku_id))
        c.commit()


def expire_allowances() -> int:
    """Expire all allowances past their expiry (used reset to 0)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "UPDATE local_business.offline_allowance SET used=0, updated_at=now() WHERE expires_at < now()")
        c.commit()
        return cur.rowcount


# ============================================================ offline sale (allowance-checked)
def create_offline_sale(
    *, tenant_id: str, business_id: int, branch_id: int, register_id: int,
    cashier_id: int | None, warehouse_id: int,
    lines: list[dict], tender_method: str = "CASH", amount_tendered=0,
    customer_id: int | None = None, shift_id: int | None = None,
    discount: float = 0, tax_amount: float = 0,
    client_event_id: str = "", device_id: str = "",
    created_at_client=None,
) -> dict:
    """Create a sale from an offline device, bounded by offline allowance.

    Each line consumes offline allowance atomically. If any line exceeds its
    allowance, the whole sale is rejected (no partial commit).
    """
    from . import retail
    # idempotency FIRST: if this offline event already created a sale, return it
    # without consuming allowance (replay-safe).
    if client_event_id and device_id:
        with _pg() as c:
            cur = c.cursor()
            cur.execute(
                """SELECT id FROM local_business.sale
                   WHERE business_id=%s AND device_id=%s AND client_event_id=%s""",
                (business_id, device_id, client_event_id))
            ada = cur.fetchone()
            if ada:
                cur.execute("SELECT * FROM local_business.sale WHERE id=%s", (ada["id"],))
                r = cur.fetchone()
                r["duplicate"] = True
                c.commit()
                return r
    # pre-check allowance for all lines
    for ln in lines:
        if allowance_remaining(register_id, ln["master_sku_id"]) < int(ln["quantity"]):
            raise inv.StokTidakCukup(
                f"offline allowance tidak cukup untuk sku {ln['master_sku_id']}")
    # consume allowance atomically for all lines
    for ln in lines:
        if not consume_allowance(register_id, ln["master_sku_id"], int(ln["quantity"])):
            raise inv.StokTidakCukup(
                f"offline allowance habis untuk sku {ln['master_sku_id']}")
    # create the sale (server-side, idempotent)
    try:
        return retail.create_sale(
            tenant_id=tenant_id, business_id=business_id, branch_id=branch_id,
            register_id=register_id, cashier_id=cashier_id, warehouse_id=warehouse_id,
            lines=lines, tender_method=tender_method, amount_tendered=amount_tendered,
            customer_id=customer_id, shift_id=shift_id, discount=discount,
            tax_amount=tax_amount, client_event_id=client_event_id,
            device_id=device_id, created_at_client=created_at_client,
            origin="OFFLINE")
    except Exception:
        # rollback allowance on failure
        for ln in lines:
            release_allowance(register_id, ln["master_sku_id"], int(ln["quantity"]))
        raise


# ============================================================ sync replay
def replay_offline_queue(business_id: int, *, warehouse_map: dict) -> dict:
    """Replay all LOCAL_PENDING offline events idempotently.

    warehouse_map: branch_id -> warehouse_id. Each event is applied once;
    unique constraints prevent duplicates.
    """
    from . import retail, returns, restaurant
    results = {"processed": 0, "duplicates": 0, "rejected": 0, "errors": []}
    for ev in list_pending_offline(business_id):
        try:
            payload = ev["payload"]
            if ev["event_type"] == "SALE":
                wh = warehouse_map.get(ev["branch_id"])
                if wh is None:
                    raise ValueError(f"branch {ev['branch_id']} tanpa warehouse")
                r = retail.create_sale(
                    tenant_id=ev["tenant_id"], business_id=ev["business_id"],
                    branch_id=ev["branch_id"], register_id=ev["register_id"],
                    cashier_id=payload.get("cashier_id"), warehouse_id=wh,
                    lines=payload["lines"], tender_method=payload.get("tender_method", "CASH"),
                    amount_tendered=payload.get("amount_tendered", 0),
                    customer_id=payload.get("customer_id"),
                    shift_id=payload.get("shift_id"),
                    discount=payload.get("discount", 0), tax_amount=payload.get("tax_amount", 0),
                    client_event_id=ev["client_event_id"], device_id=ev["device_id"],
                    created_at_client=ev["created_at_client"], origin="OFFLINE")
                if r.get("duplicate"):
                    results["duplicates"] += 1
                else:
                    results["processed"] += 1
                mark_offline_synced(ev["id"], business_id)
            elif ev["event_type"] == "RESTAURANT_ORDER":
                wh = warehouse_map.get(ev["branch_id"])
                if wh is None:
                    raise ValueError(f"branch {ev['branch_id']} tanpa warehouse")
                r = restaurant.create_restaurant_order(
                    tenant_id=ev["tenant_id"], business_id=ev["business_id"],
                    branch_id=ev["branch_id"], register_id=ev["register_id"],
                    cashier_id=payload.get("cashier_id"), warehouse_id=wh,
                    lines=payload["lines"], order_type=payload.get("order_type", "DINE_IN"),
                    table_id=payload.get("table_id"), guest_count=payload.get("guest_count", 1),
                    note=payload.get("note", ""), client_event_id=ev["client_event_id"],
                    device_id=ev["device_id"], created_at_client=ev["created_at_client"],
                    origin="OFFLINE")
                if r.get("duplicate"):
                    results["duplicates"] += 1
                else:
                    results["processed"] += 1
                mark_offline_synced(ev["id"], business_id)
            else:
                mark_offline_rejected(ev["id"], f"event_type tidak dikenal: {ev['event_type']}", business_id)
                results["rejected"] += 1
        except Exception as e:
            mark_offline_rejected(ev["id"], f"{type(e).__name__}: {e}", business_id)
            results["rejected"] += 1
            results["errors"].append(f"{ev['client_event_id']}: {type(e).__name__}: {e}")
    return results
