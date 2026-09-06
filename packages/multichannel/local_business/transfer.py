"""Multi-branch stock transfer lifecycle with quantity conservation.

DRAFT -> APPROVED -> SHIPPED -> IN_TRANSIT -> RECEIVED -> COMPLETED

Stock semantics (using `in_transit` bucket on source location):
  - Before shipment: source stock may be reserved (RESERVASI).
  - At shipment: source ON_HAND decreases, source IN_TRANSIT increases.
  - At destination receipt: source IN_TRANSIT decreases, dest ON_HAND increases.
  - Cancellation/reversal preserves quantity conservation.

Conservation invariant: total physical + in-transit is conserved through
the transfer. We never create stock at both branches simultaneously.
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg
from . import core
from . import inventory as inv


class TransferStateError(RuntimeError):
    pass


def _next_number(cur, business_id: int) -> str:
    cur.execute("SELECT nextval('local_business.transfer_seq') AS n")
    n = cur.fetchone()["n"]
    return f"TRF-{business_id}-{n:06d}"


def create_transfer(
    *, tenant_id: str, business_id: int, source_branch_id: int,
    dest_branch_id: int, lines: list[dict],  # [{master_sku_id, sku, quantity}]
    note: str = "", actor: str = "",
) -> dict:
    """Create a DRAFT transfer."""
    if source_branch_id == dest_branch_id:
        raise ValueError("source dan dest tidak boleh sama")
    if not lines:
        raise ValueError("transfer tanpa line")
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT count(*) AS n FROM local_business.branch
               WHERE business_id=%s AND id IN (%s,%s)""",
            (business_id, source_branch_id, dest_branch_id))
        if cur.fetchone()["n"] != 2:
            raise KeyError("branch transfer bukan milik business")
        number = _next_number(cur, business_id)
        cur.execute(
            """INSERT INTO local_business.transfer
               (tenant_id, business_id, transfer_number, source_branch_id,
                dest_branch_id, status, note)
               VALUES (%s,%s,%s,%s,%s,'DRAFT',%s) RETURNING id""",
            (tenant_id, business_id, number, source_branch_id, dest_branch_id, note))
        tid = cur.fetchone()["id"]
        for ln in lines:
            qty = int(ln["quantity"])
            if qty <= 0:
                raise ValueError("quantity harus > 0")
            cur.execute(
                """SELECT 1 FROM local_business.business_product
                   WHERE business_id=%s AND master_sku_id=%s AND active=TRUE""",
                (business_id, ln["master_sku_id"]))
            if not cur.fetchone():
                raise KeyError("produk transfer bukan milik business")
            cur.execute(
                """INSERT INTO local_business.transfer_line
                   (transfer_id, master_sku_id, sku, quantity)
                   VALUES (%s,%s,%s,%s)""",
                (tid, ln["master_sku_id"], ln.get("sku", ""), qty))
        core.catat_audit("transfer_created", actor=actor, tenant_id=tenant_id,
                         business_id=business_id,
                         payload={"transfer": number, "lines": len(lines)})
        c.commit()
        return {"transfer_id": tid, "transfer_number": number, "status": "DRAFT"}


def approve_transfer(*, transfer_id: int, actor: str = "", business_id: int | None = None) -> dict:
    """DRAFT -> APPROVED."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.transfer WHERE id=%s AND (%s IS NULL OR business_id=%s) FOR UPDATE",
            (transfer_id, business_id, business_id))
        t = cur.fetchone()
        if not t:
            raise KeyError(f"transfer {transfer_id} tidak ada")
        if t["status"] != "DRAFT":
            raise TransferStateError(f"status {t['status']} tidak bisa approve")
        cur.execute(
            "UPDATE local_business.transfer SET status='APPROVED', approved_by=%s, updated_at=now() WHERE id=%s",
            (actor, transfer_id))
        core.catat_audit("transfer_approved", actor=actor, tenant_id=t["tenant_id"],
                         business_id=t["business_id"],
                         payload={"transfer": t["transfer_number"]})
        c.commit()
        return {"transfer_id": transfer_id, "status": "APPROVED"}


def ship_transfer(*, transfer_id: int, actor: str = "", business_id: int | None = None) -> dict:
    """APPROVED -> IN_TRANSIT. Source ON_HAND decreases, source IN_TRANSIT increases."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.transfer WHERE id=%s AND (%s IS NULL OR business_id=%s) FOR UPDATE",
            (transfer_id, business_id, business_id))
        t = cur.fetchone()
        if not t:
            raise KeyError(f"transfer {transfer_id} tidak ada")
        if t["status"] not in ("APPROVED", "DRAFT"):
            raise TransferStateError(f"status {t['status']} tidak bisa ship")
        src = _branch_warehouse(cur, t["source_branch_id"])
        cur.execute(
            "SELECT * FROM local_business.transfer_line WHERE transfer_id=%s", (transfer_id,))
        lines = cur.fetchall()
        for ln in lines:
            # consume source ON_HAND (raises StokTidakCukup if insufficient)
            inv.consume_location(
                tenant_id=t["tenant_id"], business_id=t["business_id"],
                branch_id=t["source_branch_id"], warehouse_id=src,
                master_sku_id=ln["master_sku_id"], sku=ln["sku"],
                quantity=ln["quantity"],
                reference=f"transfer:{t['transfer_number']}:{ln['master_sku_id']}",
                note=f"transfer out {t['transfer_number']}", actor=actor,
                idempotency_key=f"trf-out:{t['transfer_number']}:{ln['master_sku_id']}",
                source_document=t["transfer_number"], cur=cur)
            # IN_TRANSIT: increase on source (units in transit, not sellable)
            _add_in_transit(cur, t["tenant_id"], t["business_id"],
                            t["source_branch_id"], src, ln, t["transfer_number"], actor)
        cur.execute(
            "UPDATE local_business.transfer SET status='IN_TRANSIT', shipped_at=now(), updated_at=now() WHERE id=%s",
            (transfer_id,))
        core.catat_audit("transfer_shipped", actor=actor, tenant_id=t["tenant_id"],
                         business_id=t["business_id"],
                         payload={"transfer": t["transfer_number"]})
        c.commit()
        return {"transfer_id": transfer_id, "status": "IN_TRANSIT"}


def _add_in_transit(cur, tenant_id, business_id, branch_id, warehouse_id,
                    ln, transfer_number, actor):
    cur.execute(
        """SELECT on_hand, reserved, safety_stock, in_transit FROM multichannel.inventory_balance
           WHERE master_sku_id=%s AND warehouse_id=%s FOR UPDATE""",
        (ln["master_sku_id"], warehouse_id))
    b = cur.fetchone()
    if not b:
        raise KeyError(f"balance {ln['master_sku_id']}/{warehouse_id} tidak ada")
    new_in_transit = b["in_transit"] + ln["quantity"]
    new_available = max(b["on_hand"] - b["reserved"] - b["safety_stock"], 0)
    cur.execute(
        """UPDATE multichannel.inventory_balance
           SET in_transit=%s, available=%s, updated_at=now()
           WHERE master_sku_id=%s AND warehouse_id=%s""",
        (new_in_transit, new_available, ln["master_sku_id"], warehouse_id))
    cur.execute(
        """INSERT INTO multichannel.inventory_movement
           (master_sku_id, warehouse_id, movement_type, qty, on_hand_after,
            reserved_after, available_after, reference, note, tenant_id, actor,
            source_document, idempotency_key)
           VALUES (%s,%s,'TRANSFER_OUT',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (ln["master_sku_id"], warehouse_id, ln["quantity"], b["on_hand"],
         b["reserved"], new_available,
         f"transfer:{transfer_number}:{ln['master_sku_id']}",
         f"in-transit {transfer_number}", tenant_id, actor,
         transfer_number, f"trf-int:{transfer_number}:{ln['master_sku_id']}"))


def receive_transfer(*, transfer_id: int, actor: str = "", business_id: int | None = None) -> dict:
    """IN_TRANSIT -> COMPLETED. Source IN_TRANSIT decreases, dest ON_HAND increases."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.transfer WHERE id=%s AND (%s IS NULL OR business_id=%s) FOR UPDATE",
            (transfer_id, business_id, business_id))
        t = cur.fetchone()
        if not t:
            raise KeyError(f"transfer {transfer_id} tidak ada")
        if t["status"] != "IN_TRANSIT":
            raise TransferStateError(f"status {t['status']} tidak bisa receive")
        src = _branch_warehouse(cur, t["source_branch_id"])
        dst = _branch_warehouse(cur, t["dest_branch_id"])
        cur.execute(
            "SELECT * FROM local_business.transfer_line WHERE transfer_id=%s", (transfer_id,))
        lines = cur.fetchall()
        for ln in lines:
            # release IN_TRANSIT on source
            _release_in_transit(cur, t["tenant_id"], t["business_id"],
                                t["source_branch_id"], src, ln, t["transfer_number"], actor)
            # increase dest ON_HAND
            inv.receive_stock(
                tenant_id=t["tenant_id"], business_id=t["business_id"],
                branch_id=t["dest_branch_id"], warehouse_id=dst,
                master_sku_id=ln["master_sku_id"], sku=ln["sku"],
                quantity=ln["quantity"],
                reference=f"transfer:{t['transfer_number']}:{ln['master_sku_id']}",
                note=f"transfer in {t['transfer_number']}", actor=actor,
                idempotency_key=f"trf-in:{t['transfer_number']}:{ln['master_sku_id']}",
                source_document=t["transfer_number"], cur=cur)
            cur.execute(
                "UPDATE local_business.transfer_line SET received_qty=%s WHERE id=%s",
                (ln["quantity"], ln["id"]))
        cur.execute(
            "UPDATE local_business.transfer SET status='COMPLETED', received_at=now(), completed_at=now(), updated_at=now() WHERE id=%s",
            (transfer_id,))
        core.catat_audit("transfer_received", actor=actor, tenant_id=t["tenant_id"],
                         business_id=t["business_id"],
                         payload={"transfer": t["transfer_number"]})
        c.commit()
        return {"transfer_id": transfer_id, "status": "COMPLETED"}


def _release_in_transit(cur, tenant_id, business_id, branch_id, warehouse_id,
                        ln, transfer_number, actor):
    cur.execute(
        """SELECT on_hand, reserved, safety_stock, in_transit FROM multichannel.inventory_balance
           WHERE master_sku_id=%s AND warehouse_id=%s FOR UPDATE""",
        (ln["master_sku_id"], warehouse_id))
    b = cur.fetchone()
    if not b:
        raise KeyError(f"balance {ln['master_sku_id']}/{warehouse_id} tidak ada")
    new_in_transit = max(b["in_transit"] - ln["quantity"], 0)
    new_available = max(b["on_hand"] - b["reserved"] - b["safety_stock"], 0)
    cur.execute(
        """UPDATE multichannel.inventory_balance
           SET in_transit=%s, available=%s, updated_at=now()
           WHERE master_sku_id=%s AND warehouse_id=%s""",
        (new_in_transit, new_available, ln["master_sku_id"], warehouse_id))
    cur.execute(
        """INSERT INTO multichannel.inventory_movement
           (master_sku_id, warehouse_id, movement_type, qty, on_hand_after,
            reserved_after, available_after, reference, note, tenant_id, actor,
            source_document, idempotency_key)
           VALUES (%s,%s,'TRANSFER_IN',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (ln["master_sku_id"], warehouse_id, ln["quantity"], b["on_hand"],
         b["reserved"], new_available,
         f"transfer:{transfer_number}:{ln['master_sku_id']}",
         f"in-transit released {transfer_number}", tenant_id, actor,
         transfer_number, f"trf-rel:{transfer_number}:{ln['master_sku_id']}"))


def cancel_transfer(*, transfer_id: int, actor: str = "", business_id: int | None = None) -> dict:
    """Cancel a DRAFT/APPROVED transfer (no stock moved yet)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.transfer WHERE id=%s AND (%s IS NULL OR business_id=%s) FOR UPDATE",
            (transfer_id, business_id, business_id))
        t = cur.fetchone()
        if not t:
            raise KeyError(f"transfer {transfer_id} tidak ada")
        if t["status"] not in ("DRAFT", "APPROVED"):
            raise TransferStateError(f"status {t['status']} tidak bisa cancel")
        cur.execute(
            "UPDATE local_business.transfer SET status='CANCELLED', cancelled_at=now(), updated_at=now() WHERE id=%s",
            (transfer_id,))
        core.catat_audit("transfer_cancelled", actor=actor, tenant_id=t["tenant_id"],
                         business_id=t["business_id"],
                         payload={"transfer": t["transfer_number"]})
        c.commit()
        return {"transfer_id": transfer_id, "status": "CANCELLED"}


def _branch_warehouse(cur, branch_id: int) -> int:
    cur.execute("SELECT warehouse_id FROM local_business.branch WHERE id=%s", (branch_id,))
    r = cur.fetchone()
    if not r:
        raise KeyError(f"branch {branch_id} tidak ada")
    return r["warehouse_id"]


def get_transfer(transfer_id: int, business_id: int | None = None) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.transfer WHERE id=%s AND (%s IS NULL OR business_id=%s)",
            (transfer_id, business_id, business_id))
        t = cur.fetchone()
        if not t:
            return None
        cur.execute("SELECT * FROM local_business.transfer_line WHERE transfer_id=%s", (transfer_id,))
        t["lines"] = cur.fetchall()
        return t


def list_transfers(business_id: int) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.transfer WHERE business_id=%s ORDER BY id DESC",
            (business_id,))
        return cur.fetchall()
