"""Location-aware inventory operations for Local Business.

Reuses the Central Inventory Core (`multichannel.master_sku` +
`multichannel.inventory_balance`). Every stock change produces a durable
`multichannel.inventory_movement` with tenant/location/sku/qty/type/source/
idempotency/actor/audit. No ad-hoc overwrite without movement.

Location = `multichannel.warehouse`. A branch maps to one warehouse.

Each mutating function accepts an optional `cur` (psycopg cursor). When
provided, the operation runs inside the CALLER's transaction (for atomic
multi-step flows like a POS sale). When omitted, it opens its own
transaction.
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg


class StokTidakCukup(Exception):
    pass


def _assert_scope(cur, *, business_id: int, branch_id: int,
                  warehouse_id: int, master_sku_id: int) -> None:
    """Validate the complete location/catalog boundary before any mutation."""
    cur.execute(
        """SELECT 1 FROM local_business.branch
           WHERE id=%s AND business_id=%s AND warehouse_id=%s AND status='ACTIVE'""",
        (branch_id, business_id, warehouse_id),
    )
    if not cur.fetchone():
        raise KeyError("lokasi tidak termasuk business")
    cur.execute(
        """SELECT 1 FROM local_business.business_product
           WHERE business_id=%s AND master_sku_id=%s AND active=TRUE""",
        (business_id, master_sku_id),
    )
    if not cur.fetchone():
        raise KeyError("produk tidak termasuk business")


# ============================================================ balance helpers
def _ensure_balance(cur, master_sku_id: int, warehouse_id: int) -> None:
    cur.execute(
        """INSERT INTO multichannel.inventory_balance
           (master_sku_id, warehouse_id, on_hand, reserved, safety_stock, in_transit, available)
           VALUES (%s,%s,0,0,0,0,0)
           ON CONFLICT (master_sku_id, warehouse_id) DO NOTHING""",
        (master_sku_id, warehouse_id))


def location_balance(master_sku_id: int, warehouse_id: int) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM multichannel.inventory_balance
               WHERE master_sku_id=%s AND warehouse_id=%s""",
            (master_sku_id, warehouse_id))
        return cur.fetchone()


def location_atp(master_sku_id: int, warehouse_id: int) -> int:
    b = location_balance(master_sku_id, warehouse_id)
    if not b:
        return 0
    return max(b["on_hand"] - b["reserved"] - b["safety_stock"], 0)


def _write_movement(cur, *, master_sku_id, warehouse_id, movement_type, qty,
                    on_hand_after, reserved_after, available_after,
                    reference, note, tenant_id, actor, device_id,
                    idempotency_key, source_document):
    cur.execute(
        """INSERT INTO multichannel.inventory_movement
           (master_sku_id, warehouse_id, movement_type, qty, on_hand_after,
            reserved_after, available_after, reference, note, tenant_id,
            actor, device_id, source_document, idempotency_key)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (master_sku_id, warehouse_id, movement_type, qty, on_hand_after,
         reserved_after, available_after, reference, note, tenant_id,
         actor, device_id, source_document, idempotency_key))


def _idem_exists(cur, idempotency_key: str, movement_type: str) -> bool:
    if not idempotency_key:
        return False
    cur.execute(
        """SELECT id FROM multichannel.inventory_movement
           WHERE idempotency_key=%s AND movement_type=%s""",
        (idempotency_key, movement_type))
    return cur.fetchone() is not None


def _lock_balance(cur, master_sku_id: int, warehouse_id: int) -> dict:
    _ensure_balance(cur, master_sku_id, warehouse_id)
    cur.execute(
        """SELECT on_hand, reserved, safety_stock, in_transit FROM multichannel.inventory_balance
           WHERE master_sku_id=%s AND warehouse_id=%s FOR UPDATE""",
        (master_sku_id, warehouse_id))
    return cur.fetchone()


def _update_balance(cur, master_sku_id, warehouse_id, on_hand, reserved, safety, in_transit=None):
    if in_transit is None:
        cur.execute(
            "SELECT in_transit FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s",
            (master_sku_id, warehouse_id))
        in_transit = cur.fetchone()["in_transit"]
    available = max(on_hand - reserved - safety, 0)
    cur.execute(
        """UPDATE multichannel.inventory_balance
           SET on_hand=%s, reserved=%s, safety_stock=%s, in_transit=%s, available=%s, updated_at=now()
           WHERE master_sku_id=%s AND warehouse_id=%s""",
        (on_hand, reserved, safety, in_transit, available, master_sku_id, warehouse_id))
    return available


def _evaluate_low_stock(cur, *, business_id: int, branch_id: int, warehouse_id: int,
                        master_sku_id: int, sku: str, available_before: int,
                        available_after: int, actor: str = "", tenant_id: str = ""):
    """Non-blocking low-stock event evaluation hook."""
    if not business_id or not warehouse_id or not master_sku_id:
        return
    try:
        from . import low_stock
        low_stock.evaluate_transition(
            cur, business_id=business_id, branch_id=branch_id,
            warehouse_id=warehouse_id, master_sku_id=master_sku_id,
            sku=sku, available_before=available_before, available_after=available_after)
    except Exception as exc:
        try:
            from . import core
            core.catat_audit(
                "low_stock_alert_deferred", actor=actor or "system",
                tenant_id=tenant_id, business_id=business_id, branch_id=branch_id,
                payload={"sku": sku, "master_sku_id": master_sku_id, "error": str(exc)[:500]})
        except Exception:
            pass


# ============================================================ goods receipt / opening stock
def receive_stock(*, tenant_id: str, business_id: int, branch_id: int,
                  warehouse_id: int, master_sku_id: int, sku: str,
                  quantity: int, unit_cost=0, reference: str = "",
                  note: str = "", actor: str = "", device_id: str = "",
                  idempotency_key: str = "", source_document: str = "",
                  cur=None) -> dict:
    """MASUK: ON_HAND naik di lokasi. Idempoten per idempotency_key."""
    if quantity <= 0:
        raise ValueError("quantity harus > 0")
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        _assert_scope(cur, business_id=business_id, branch_id=branch_id,
                      warehouse_id=warehouse_id, master_sku_id=master_sku_id)
        if _idem_exists(cur, idempotency_key, "MASUK"):
            if own:
                c.rollback()
            return {"duplicate": True}
        cur.execute(
            "SELECT id FROM multichannel.master_sku WHERE id=%s FOR UPDATE", (master_sku_id,))
        if not cur.fetchone():
            raise KeyError(f"master_sku {master_sku_id} tidak ada")
        b = _lock_balance(cur, master_sku_id, warehouse_id)
        avail_before = max(b["on_hand"] - b["reserved"] - b["safety_stock"], 0)
        new_on_hand = b["on_hand"] + quantity
        new_available = _update_balance(cur, master_sku_id, warehouse_id,
                                         new_on_hand, b["reserved"], b["safety_stock"])
        _write_movement(cur, master_sku_id=master_sku_id, warehouse_id=warehouse_id,
                        movement_type="MASUK", qty=quantity,
                        on_hand_after=new_on_hand, reserved_after=b["reserved"],
                        available_after=new_available,
                        reference=idempotency_key or source_document,
                        note=note or f"goods receipt {source_document}",
                        tenant_id=tenant_id, actor=actor, device_id=device_id,
                        idempotency_key=idempotency_key, source_document=source_document)
        _evaluate_low_stock(cur, business_id=business_id, branch_id=branch_id,
                            warehouse_id=warehouse_id, master_sku_id=master_sku_id,
                            sku=sku, available_before=avail_before,
                            available_after=new_available, actor=actor, tenant_id=tenant_id)
        if own:
            c.commit()
        return {"duplicate": False, "on_hand_after": new_on_hand,
                "available_after": new_available}
    except Exception:
        if own:
            c.rollback()
        raise


# ============================================================ location consume (sale / ingredient)
def consume_location(*, tenant_id: str, business_id: int, branch_id: int,
                     warehouse_id: int, master_sku_id: int, sku: str,
                     quantity: int, reference: str = "", note: str = "",
                     actor: str = "", device_id: str = "",
                     idempotency_key: str = "", source_document: str = "",
                     cur=None) -> dict:
    """KELUAR: ON_HAND turun di lokasi. Oversell ditolak (row lock)."""
    if quantity <= 0:
        raise ValueError("quantity harus > 0")
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        _assert_scope(cur, business_id=business_id, branch_id=branch_id,
                      warehouse_id=warehouse_id, master_sku_id=master_sku_id)
        if _idem_exists(cur, idempotency_key, "KELUAR"):
            if own:
                c.rollback()
            return {"duplicate": True}
        cur.execute(
            "SELECT id FROM multichannel.master_sku WHERE id=%s FOR UPDATE", (master_sku_id,))
        if not cur.fetchone():
            raise KeyError(f"master_sku {master_sku_id} tidak ada")
        b = _lock_balance(cur, master_sku_id, warehouse_id)
        avail_before = max(b["on_hand"] - b["reserved"] - b["safety_stock"], 0)
        available = b["on_hand"] - b["reserved"] - b["safety_stock"]
        if quantity > available:
            raise StokTidakCukup(
                f"{sku}: diminta {quantity}, tersedia {available} di lokasi {warehouse_id}")
        new_on_hand = b["on_hand"] - quantity
        new_available = _update_balance(cur, master_sku_id, warehouse_id,
                                        new_on_hand, b["reserved"], b["safety_stock"])
        _write_movement(cur, master_sku_id=master_sku_id, warehouse_id=warehouse_id,
                        movement_type="KELUAR", qty=quantity,
                        on_hand_after=new_on_hand, reserved_after=b["reserved"],
                        available_after=new_available,
                        reference=idempotency_key or source_document,
                        note=note, tenant_id=tenant_id, actor=actor,
                        device_id=device_id, idempotency_key=idempotency_key,
                        source_document=source_document)
        _evaluate_low_stock(cur, business_id=business_id, branch_id=branch_id,
                            warehouse_id=warehouse_id, master_sku_id=master_sku_id,
                            sku=sku, available_before=avail_before,
                            available_after=new_available, actor=actor, tenant_id=tenant_id)
        if own:
            c.commit()
        return {"duplicate": False, "on_hand_after": new_on_hand,
                "available_after": new_available}
    except Exception:
        if own:
            c.rollback()
        raise


# ============================================================ location return (restock)
def return_location(*, tenant_id: str, business_id: int, branch_id: int,
                    warehouse_id: int, master_sku_id: int, sku: str,
                    quantity: int, reference: str = "", note: str = "",
                    actor: str = "", device_id: str = "",
                    idempotency_key: str = "", source_document: str = "",
                    cur=None) -> dict:
    """RETUR: ON_HAND naik di lokasi. Idempoten."""
    if quantity <= 0:
        raise ValueError("quantity harus > 0")
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        _assert_scope(cur, business_id=business_id, branch_id=branch_id,
                      warehouse_id=warehouse_id, master_sku_id=master_sku_id)
        if _idem_exists(cur, idempotency_key, "RETUR"):
            if own:
                c.rollback()
            return {"duplicate": True}
        cur.execute(
            "SELECT id FROM multichannel.master_sku WHERE id=%s FOR UPDATE", (master_sku_id,))
        if not cur.fetchone():
            raise KeyError(f"master_sku {master_sku_id} tidak ada")
        b = _lock_balance(cur, master_sku_id, warehouse_id)
        avail_before = max(b["on_hand"] - b["reserved"] - b["safety_stock"], 0)
        new_on_hand = b["on_hand"] + quantity
        new_available = _update_balance(cur, master_sku_id, warehouse_id,
                                        new_on_hand, b["reserved"], b["safety_stock"])
        _write_movement(cur, master_sku_id=master_sku_id, warehouse_id=warehouse_id,
                        movement_type="RETUR", qty=quantity,
                        on_hand_after=new_on_hand, reserved_after=b["reserved"],
                        available_after=new_available,
                        reference=idempotency_key or source_document,
                        note=note, tenant_id=tenant_id, actor=actor,
                        device_id=device_id, idempotency_key=idempotency_key,
                        source_document=source_document)
        _evaluate_low_stock(cur, business_id=business_id, branch_id=branch_id,
                            warehouse_id=warehouse_id, master_sku_id=master_sku_id,
                            sku=sku, available_before=avail_before,
                            available_after=new_available, actor=actor, tenant_id=tenant_id)
        if own:
            c.commit()
        return {"duplicate": False, "on_hand_after": new_on_hand,
                "available_after": new_available}
    except Exception:
        if own:
            c.rollback()
        raise


# ============================================================ waste / damage / adjustment
def waste_location(*, tenant_id: str, business_id: int, branch_id: int,
                   warehouse_id: int, master_sku_id: int, sku: str,
                   quantity: int, reason: str = "", reference: str = "",
                   actor: str = "", device_id: str = "",
                   idempotency_key: str = "", source_document: str = "",
                   cur=None) -> dict:
    """WASTE: ON_HAND turun (damage/loss/spoilage). Tidak boleh negatif."""
    if quantity <= 0:
        raise ValueError("quantity harus > 0")
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        _assert_scope(cur, business_id=business_id, branch_id=branch_id,
                      warehouse_id=warehouse_id, master_sku_id=master_sku_id)
        if _idem_exists(cur, idempotency_key, "WASTE"):
            if own:
                c.rollback()
            return {"duplicate": True}
        cur.execute(
            "SELECT id FROM multichannel.master_sku WHERE id=%s FOR UPDATE", (master_sku_id,))
        if not cur.fetchone():
            raise KeyError(f"master_sku {master_sku_id} tidak ada")
        b = _lock_balance(cur, master_sku_id, warehouse_id)
        avail_before = max(b["on_hand"] - b["reserved"] - b["safety_stock"], 0)
        if quantity > b["on_hand"]:
            raise StokTidakCukup(f"{sku}: waste {quantity} > on_hand {b['on_hand']}")
        new_on_hand = b["on_hand"] - quantity
        new_available = _update_balance(cur, master_sku_id, warehouse_id,
                                        new_on_hand, b["reserved"], b["safety_stock"])
        _write_movement(cur, master_sku_id=master_sku_id, warehouse_id=warehouse_id,
                        movement_type="WASTE", qty=quantity,
                        on_hand_after=new_on_hand, reserved_after=b["reserved"],
                        available_after=new_available,
                        reference=idempotency_key or source_document,
                        note=f"waste: {reason}", tenant_id=tenant_id, actor=actor,
                        device_id=device_id, idempotency_key=idempotency_key,
                        source_document=source_document)
        _evaluate_low_stock(cur, business_id=business_id, branch_id=branch_id,
                            warehouse_id=warehouse_id, master_sku_id=master_sku_id,
                            sku=sku, available_before=avail_before,
                            available_after=new_available, actor=actor, tenant_id=tenant_id)
        if own:
            c.commit()
        return {"duplicate": False, "on_hand_after": new_on_hand,
                "available_after": new_available}
    except Exception:
        if own:
            c.rollback()
        raise


# ============================================================ stock opname / count correction
def adjust_location(*, tenant_id: str, business_id: int, branch_id: int,
                    warehouse_id: int, master_sku_id: int, sku: str,
                    delta_on_hand: int, reason: str = "", reference: str = "",
                    actor: str = "", device_id: str = "",
                    idempotency_key: str = "", source_document: str = "",
                    cur=None) -> dict:
    """PENYESUAIAN: ubah ON_HAND (opname/count correction). Hasil tak boleh negatif."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        _assert_scope(cur, business_id=business_id, branch_id=branch_id,
                      warehouse_id=warehouse_id, master_sku_id=master_sku_id)
        if _idem_exists(cur, idempotency_key, "PENYESUAIAN"):
            if own:
                c.rollback()
            return {"duplicate": True}
        cur.execute(
            "SELECT id FROM multichannel.master_sku WHERE id=%s FOR UPDATE", (master_sku_id,))
        if not cur.fetchone():
            raise KeyError(f"master_sku {master_sku_id} tidak ada")
        b = _lock_balance(cur, master_sku_id, warehouse_id)
        avail_before = max(b["on_hand"] - b["reserved"] - b["safety_stock"], 0)
        new_on_hand = b["on_hand"] + delta_on_hand
        if new_on_hand < 0:
            raise ValueError("on_hand tidak boleh negatif")
        new_available = _update_balance(cur, master_sku_id, warehouse_id,
                                        new_on_hand, b["reserved"], b["safety_stock"])
        _write_movement(cur, master_sku_id=master_sku_id, warehouse_id=warehouse_id,
                        movement_type="PENYESUAIAN", qty=delta_on_hand,
                        on_hand_after=new_on_hand, reserved_after=b["reserved"],
                        available_after=new_available,
                        reference=idempotency_key or source_document,
                        note=f"adjust: {reason}", tenant_id=tenant_id, actor=actor,
                        device_id=device_id, idempotency_key=idempotency_key,
                        source_document=source_document)
        _evaluate_low_stock(cur, business_id=business_id, branch_id=branch_id,
                            warehouse_id=warehouse_id, master_sku_id=master_sku_id,
                            sku=sku, available_before=avail_before,
                            available_after=new_available, actor=actor, tenant_id=tenant_id)
        if own:
            c.commit()
        return {"duplicate": False, "on_hand_after": new_on_hand,
                "available_after": new_available}
    except Exception:
        if own:
            c.rollback()
        raise


# ============================================================ global / aggregate
def global_available(master_sku_id: int) -> int:
    """Aggregate available across all locations (reporting only)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT COALESCE(SUM(on_hand - reserved - safety_stock),0) AS a
               FROM multichannel.inventory_balance WHERE master_sku_id=%s""",
            (master_sku_id,))
        r = cur.fetchone()
        return max(int(r["a"]), 0)


def location_movements(master_sku_id: int, warehouse_id: int, limit: int = 100) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM multichannel.inventory_movement
               WHERE master_sku_id=%s AND warehouse_id=%s
               ORDER BY id DESC LIMIT %s""",
            (master_sku_id, warehouse_id, limit))
        return cur.fetchall()
