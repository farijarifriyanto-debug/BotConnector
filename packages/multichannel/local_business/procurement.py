"""Procurement & Replenishment Core V1 for BC Bisnis.

Features:
- Normalized Supplier Master: `local_business.supplier`
- Supplier ↔ SKU Terms: `local_business.supplier_sku`
- Purchase Order Lifecycle: `local_business.purchase_order` & `purchase_order_line`
  (DRAFT -> CONFIRMED -> PARTIALLY_RECEIVED -> RECEIVED | CANCELLED)
- Goods Receipt against PO: `local_business.goods_receipt` linked to PO,
  calling canonical `inventory.receive_stock`
- Telegram Durable Procurement Drafts with strict authorization & concurrency safety
- Zero automatic purchasing / zero vendor bill / zero automatic payments.
"""

from __future__ import annotations

import math
import os
import secrets
import json
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal

from ..persistence.db import koneksi as _pg
from . import core
from . import inventory as inv


# ============================================================
# 1. SUPPLIER MASTER
# ============================================================

def create_supplier(
    *,
    business_id: int,
    code: str,
    name: str,
    contact_name: str = "",
    phone: str = "",
    email: str = "",
    address: str = "",
    notes: str = "",
    cur=None,
) -> dict:
    """Create a new supplier for a business. Code is unique per business."""
    code_norm = (code or "").strip().upper()
    name_norm = (name or "").strip()
    if not code_norm:
        raise ValueError("Kode supplier tidak boleh kosong")
    if not name_norm:
        raise ValueError("Nama supplier tidak boleh kosong")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT id, active FROM local_business.supplier
               WHERE business_id=%s AND code=%s""",
            (business_id, code_norm),
        )
        existing = cur.fetchone()
        if existing:
            if existing["active"]:
                raise ValueError(f"Supplier dengan kode '{code_norm}' sudah ada")
            else:
                # Reactivate and update
                cur.execute(
                    """UPDATE local_business.supplier
                       SET name=%s, contact_name=%s, phone=%s, email=%s,
                           address=%s, notes=%s, active=TRUE, updated_at=now()
                       WHERE id=%s
                       RETURNING id, business_id, code, name, contact_name, phone, email, address, active, notes, created_at, updated_at""",
                    (name_norm, contact_name.strip() or None, phone.strip() or None,
                     email.strip() or None, address.strip() or None, notes.strip() or None,
                     existing["id"]),
                )
                row = cur.fetchone()
                if own:
                    c.commit()
                return dict(row)

        cur.execute(
            """INSERT INTO local_business.supplier
               (business_id, code, name, contact_name, phone, email, address, notes, active, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, now(), now())
               RETURNING id, business_id, code, name, contact_name, phone, email, address, active, notes, created_at, updated_at""",
            (business_id, code_norm, name_norm, contact_name.strip() or None,
             phone.strip() or None, email.strip() or None, address.strip() or None,
             notes.strip() or None),
        )
        row = cur.fetchone()
        if own:
            c.commit()
        return dict(row)
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def update_supplier(
    *,
    business_id: int,
    code: str,
    name: str | None = None,
    contact_name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    address: str | None = None,
    notes: str | None = None,
    active: bool | None = None,
    cur=None,
) -> dict:
    """Update an existing supplier by code."""
    code_norm = (code or "").strip().upper()
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.supplier
               WHERE business_id=%s AND code=%s FOR UPDATE""",
            (business_id, code_norm),
        )
        supp = cur.fetchone()
        if not supp:
            raise KeyError(f"Supplier dengan kode '{code_norm}' tidak ditemukan")

        new_name = name.strip() if name is not None else supp["name"]
        new_contact = contact_name.strip() if contact_name is not None else supp["contact_name"]
        new_phone = phone.strip() if phone is not None else supp["phone"]
        new_email = email.strip() if email is not None else supp["email"]
        new_address = address.strip() if address is not None else supp["address"]
        new_notes = notes.strip() if notes is not None else supp["notes"]
        new_active = active if active is not None else supp["active"]

        cur.execute(
            """UPDATE local_business.supplier
               SET name=%s, contact_name=%s, phone=%s, email=%s,
                   address=%s, notes=%s, active=%s, updated_at=now()
               WHERE id=%s
               RETURNING id, business_id, code, name, contact_name, phone, email, address, active, notes, created_at, updated_at""",
            (new_name, new_contact, new_phone, new_email, new_address, new_notes, new_active, supp["id"]),
        )
        row = cur.fetchone()
        if own:
            c.commit()
        return dict(row)
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def deactivate_supplier(*, business_id: int, code: str, cur=None) -> dict:
    """Soft deactivate a supplier by code without deleting history."""
    return update_supplier(business_id=business_id, code=code, active=False, cur=cur)


def get_supplier(*, business_id: int, code: str, cur=None) -> dict | None:
    """Get supplier by business and code."""
    code_norm = (code or "").strip().upper()
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT id, business_id, code, name, contact_name, phone, email, address, active, notes, created_at, updated_at
               FROM local_business.supplier
               WHERE business_id=%s AND code=%s""",
            (business_id, code_norm),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            c.close()


def get_supplier_by_id(*, business_id: int, supplier_id: int, cur=None) -> dict | None:
    """Get supplier by primary key ID."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT id, business_id, code, name, contact_name, phone, email, address, active, notes, created_at, updated_at
               FROM local_business.supplier
               WHERE business_id=%s AND id=%s""",
            (business_id, supplier_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            c.close()


def list_suppliers(business_id: int, active_only: bool = True, cur=None) -> list[dict]:
    """List suppliers for a business."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = """SELECT id, business_id, code, name, contact_name, phone, email, address, active, notes, created_at, updated_at
                 FROM local_business.supplier
                 WHERE business_id=%s"""
        params = [business_id]
        if active_only:
            sql += " AND active=TRUE"
        sql += " ORDER BY code ASC"
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            c.close()


# ============================================================
# 2. SUPPLIER ↔ SKU TERMS & RESTOCK CONFIG
# ============================================================

def set_supplier_sku(
    *,
    business_id: int,
    supplier_id: int,
    master_sku_id: int,
    supplier_sku: str = "",
    lead_time_days: int,
    min_order_qty: int = 1,
    purchase_unit_cost: float | Decimal | None = None,
    target_stock: int | None = None,
    preferred: bool = True,
    active: bool = True,
    cur=None,
) -> dict:
    """Configure replenishment terms for a supplier-SKU relationship."""
    if lead_time_days < 0:
        raise ValueError("lead_time_days harus >= 0")
    if min_order_qty < 1:
        raise ValueError("min_order_qty harus >= 1")
    if purchase_unit_cost is not None and float(purchase_unit_cost) < 0:
        raise ValueError("purchase_unit_cost harus >= 0")
    if target_stock is not None:
        if target_stock < 0:
            raise ValueError("target_stock harus >= 0")
        if target_stock < min_order_qty:
            raise ValueError(f"target_stock ({target_stock}) tidak boleh lebih kecil dari min_order_qty ({min_order_qty})")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        # If preferred, demote existing preferred active supplier for this SKU
        if preferred and active:
            cur.execute(
                """UPDATE local_business.supplier_sku
                   SET preferred=FALSE, updated_at=now()
                   WHERE business_id=%s AND master_sku_id=%s AND supplier_id!=%s AND active=TRUE AND preferred=TRUE""",
                (business_id, master_sku_id, supplier_id),
            )

        cur.execute(
            """INSERT INTO local_business.supplier_sku
               (business_id, supplier_id, master_sku_id, supplier_sku, lead_time_days,
                min_order_qty, purchase_unit_cost, target_stock, preferred, active, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
               ON CONFLICT (business_id, supplier_id, master_sku_id)
               DO UPDATE SET supplier_sku=EXCLUDED.supplier_sku,
                             lead_time_days=EXCLUDED.lead_time_days,
                             min_order_qty=EXCLUDED.min_order_qty,
                             purchase_unit_cost=EXCLUDED.purchase_unit_cost,
                             target_stock=EXCLUDED.target_stock,
                             preferred=EXCLUDED.preferred,
                             active=EXCLUDED.active,
                             updated_at=now()
               RETURNING id, business_id, supplier_id, master_sku_id, supplier_sku,
                         lead_time_days, min_order_qty, purchase_unit_cost, target_stock, preferred, active, created_at, updated_at""",
            (business_id, supplier_id, master_sku_id, supplier_sku.strip() or None,
             lead_time_days, min_order_qty, purchase_unit_cost, target_stock, preferred, active),
        )
        row = cur.fetchone()
        if own:
            c.commit()
        return dict(row)
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def deactivate_supplier_sku(
    *,
    business_id: int,
    master_sku_id: int,
    supplier_id: int | None = None,
    cur=None,
) -> dict:
    """Deactivate supplier replenishment terms for an SKU."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        if supplier_id is not None:
            cur.execute(
                """UPDATE local_business.supplier_sku
                   SET active=FALSE, preferred=FALSE, updated_at=now()
                   WHERE business_id=%s AND master_sku_id=%s AND supplier_id=%s
                   RETURNING id""",
                (business_id, master_sku_id, supplier_id),
            )
        else:
            cur.execute(
                """UPDATE local_business.supplier_sku
                   SET active=FALSE, preferred=FALSE, updated_at=now()
                   WHERE business_id=%s AND master_sku_id=%s
                   RETURNING id""",
                (business_id, master_sku_id),
            )
        rows = cur.fetchall()
        if own:
            c.commit()
        return {"ok": True, "count": len(rows)}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def get_preferred_supplier_sku(
    *,
    business_id: int,
    master_sku_id: int,
    cur=None,
) -> dict | None:
    """Get the active preferred supplier terms for an SKU."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT ss.id, ss.business_id, ss.supplier_id, ss.master_sku_id,
                      ss.supplier_sku, ss.lead_time_days, ss.min_order_qty,
                      ss.purchase_unit_cost, ss.target_stock, ss.preferred, ss.active,
                      s.code AS supplier_code, s.name AS supplier_name
               FROM local_business.supplier_sku ss
               JOIN local_business.supplier s ON s.id=ss.supplier_id
               WHERE ss.business_id=%s AND ss.master_sku_id=%s
                 AND ss.active=TRUE AND ss.preferred=TRUE AND s.active=TRUE
               ORDER BY ss.id DESC LIMIT 1""",
            (business_id, master_sku_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            c.close()


def list_supplier_skus(
    *,
    business_id: int,
    master_sku_id: int | None = None,
    supplier_id: int | None = None,
    cur=None,
) -> list[dict]:
    """List supplier-SKU relationships."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = """SELECT ss.id, ss.business_id, ss.supplier_id, ss.master_sku_id,
                        ss.supplier_sku, ss.lead_time_days, ss.min_order_qty,
                        ss.purchase_unit_cost, ss.target_stock, ss.preferred, ss.active,
                        s.code AS supplier_code, s.name AS supplier_name,
                        m.sku, p.name AS product_name
                 FROM local_business.supplier_sku ss
                 JOIN local_business.supplier s ON s.id=ss.supplier_id
                 JOIN multichannel.master_sku m ON m.id=ss.master_sku_id
                 JOIN multichannel.product p ON p.id=m.product_id
                 WHERE ss.business_id=%s AND ss.active=TRUE"""
        params = [business_id]
        if master_sku_id is not None:
            sql += " AND ss.master_sku_id=%s"
            params.append(master_sku_id)
        if supplier_id is not None:
            sql += " AND ss.supplier_id=%s"
            params.append(supplier_id)
        sql += " ORDER BY m.sku ASC"
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            c.close()


# ============================================================
# 3. PURCHASE ORDER CORE
# ============================================================

def create_purchase_order(
    *,
    business_id: int,
    supplier_id: int,
    warehouse_id: int,
    lines: list[dict],  # [{master_sku_id, ordered_qty, unit_cost, supplier_sku, description}]
    expected_arrival_date: str | date | None = None,
    notes: str = "",
    created_by: str = "",
    client_event_id: str = "",
    device_id: str = "",
    cur=None,
) -> dict:
    """Create a DRAFT purchase order. Does not mutate stock or Finance."""
    if not lines:
        raise ValueError("PO harus memiliki minimal satu item")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        # Validate supplier
        cur.execute("SELECT * FROM local_business.supplier WHERE business_id=%s AND id=%s", (business_id, supplier_id))
        supp = cur.fetchone()
        if not supp:
            raise KeyError(f"Supplier ID {supplier_id} tidak ditemukan")

        # Generate unique PO number: BC-PO-YYYY-000001
        year = datetime.now(timezone.utc).year
        cur.execute("SELECT nextval('local_business.po_seq') AS n")
        n = cur.fetchone()["n"]
        po_number = f"BC-PO-{year}-{n:06d}"

        # Calculate line totals
        subtotal = Decimal("0")
        validated_lines = []
        for idx, ln in enumerate(lines, start=1):
            qty = int(ln.get("ordered_qty", ln.get("quantity", 0)))
            raw_uc = ln.get("unit_cost")
            if raw_uc is None or Decimal(str(raw_uc)) <= Decimal("0"):
                cur.execute(
                    """SELECT purchase_unit_cost FROM local_business.supplier_sku
                       WHERE business_id=%s AND supplier_id=%s AND master_sku_id=%s AND active=TRUE""",
                    (business_id, supplier_id, ln["master_sku_id"]),
                )
                ss_row = cur.fetchone()
                if ss_row and ss_row["purchase_unit_cost"] is not None:
                    unit_cost = Decimal(str(ss_row["purchase_unit_cost"]))
                else:
                    unit_cost = Decimal("0")
            else:
                unit_cost = Decimal(str(raw_uc))

            if unit_cost < 0:
                raise ValueError(f"Unit cost untuk item #{idx} harus >= 0")
            line_total = Decimal(qty) * unit_cost
            subtotal += line_total
            validated_lines.append({
                "line_no": idx,
                "master_sku_id": ln["master_sku_id"],
                "supplier_sku": ln.get("supplier_sku") or None,
                "description": ln.get("description", ln.get("name", "")),
                "ordered_qty": qty,
                "unit_cost": unit_cost,
                "line_total": line_total,
            })

        cur.execute(
            """INSERT INTO local_business.purchase_order
               (business_id, supplier_id, warehouse_id, po_number, status, expected_arrival_date,
                notes, subtotal, created_by, client_event_id, device_id, created_at, updated_at)
               VALUES (%s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s, %s, %s, now(), now())
               RETURNING id, po_number, status, expected_arrival_date, subtotal, created_at""",
            (business_id, supplier_id, warehouse_id, po_number, expected_arrival_date,
             notes.strip() or None, subtotal, created_by.strip() or None,
             client_event_id.strip() or None, device_id.strip() or None),
        )
        po_row = cur.fetchone()
        po_id = po_row["id"]

        for vln in validated_lines:
            cur.execute(
                """INSERT INTO local_business.purchase_order_line
                   (purchase_order_id, master_sku_id, supplier_sku, description, ordered_qty,
                    unit_cost, received_qty, line_total, line_no)
                   VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s)""",
                (po_id, vln["master_sku_id"], vln["supplier_sku"], vln["description"],
                 vln["ordered_qty"], vln["unit_cost"], vln["line_total"], vln["line_no"]),
            )

        if own:
            c.commit()

        return {
            "ok": True,
            "purchase_order_id": po_id,
            "po_number": po_number,
            "supplier_id": supplier_id,
            "supplier_code": supp["code"],
            "supplier_name": supp["name"],
            "warehouse_id": warehouse_id,
            "status": "DRAFT",
            "subtotal": float(subtotal),
            "expected_arrival_date": str(expected_arrival_date) if expected_arrival_date else None,
            "lines_count": len(validated_lines),
        }
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def confirm_purchase_order(
    *,
    business_id: int,
    po_id: int | None = None,
    po_number: str | None = None,
    cur=None,
) -> dict:
    """Human confirms a DRAFT PO -> CONFIRMED. Sets expected arrival based on lead time. Still no stock mutation."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = "SELECT * FROM local_business.purchase_order WHERE business_id=%s"
        params = [business_id]
        if po_id is not None:
            sql += " AND id=%s"
            params.append(po_id)
        elif po_number is not None:
            sql += " AND po_number=%s"
            params.append(po_number.strip().upper())
        else:
            raise ValueError("po_id atau po_number harus diberikan")
        sql += " FOR UPDATE"
        cur.execute(sql, params)
        po = cur.fetchone()
        if not po:
            raise KeyError("Purchase order tidak ditemukan")

        if po["status"] == "CONFIRMED":
            # Idempotent
            return {"ok": True, "duplicate": True, "po_number": po["po_number"], "status": "CONFIRMED"}

        if po["status"] != "DRAFT":
            raise ValueError(f"PO {po['po_number']} tidak dapat dikonfirmasi dari status {po['status']}")

        # Compute expected arrival date if not set: confirmation_date + max lead_time_days
        expected_date = po["expected_arrival_date"]
        if not expected_date:
            cur.execute(
                """SELECT COALESCE(MAX(ss.lead_time_days), 0) AS max_lt
                   FROM local_business.purchase_order_line pol
                   LEFT JOIN local_business.supplier_sku ss
                     ON ss.master_sku_id=pol.master_sku_id AND ss.supplier_id=%s AND ss.business_id=%s
                   WHERE pol.purchase_order_id=%s""",
                (po["supplier_id"], business_id, po["id"]),
            )
            lt_row = cur.fetchone()
            lead_days = lt_row["max_lt"] if lt_row else 0
            today = datetime.now(timezone.utc).date()
            expected_date = today + timedelta(days=lead_days)

        cur.execute(
            """UPDATE local_business.purchase_order
               SET status='CONFIRMED', expected_arrival_date=%s, confirmed_at=now(), updated_at=now()
               WHERE id=%s
               RETURNING id, po_number, status, expected_arrival_date, confirmed_at""",
            (expected_date, po["id"]),
        )
        upd = cur.fetchone()
        if own:
            c.commit()

        return {
            "ok": True,
            "purchase_order_id": upd["id"],
            "po_number": upd["po_number"],
            "status": "CONFIRMED",
            "expected_arrival_date": str(upd["expected_arrival_date"]),
            "confirmed_at": str(upd["confirmed_at"]),
        }
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def cancel_purchase_order(
    *,
    business_id: int,
    po_id: int | None = None,
    po_number: str | None = None,
    reason: str = "",
    cur=None,
) -> dict:
    """Cancel a DRAFT or CONFIRMED PO."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = "SELECT * FROM local_business.purchase_order WHERE business_id=%s"
        params = [business_id]
        if po_id is not None:
            sql += " AND id=%s"
            params.append(po_id)
        elif po_number is not None:
            sql += " AND po_number=%s"
            params.append(po_number.strip().upper())
        else:
            raise ValueError("po_id atau po_number harus diberikan")
        sql += " FOR UPDATE"
        cur.execute(sql, params)
        po = cur.fetchone()
        if not po:
            raise KeyError("Purchase order tidak ditemukan")

        if po["status"] == "CANCELLED":
            return {"ok": True, "duplicate": True, "po_number": po["po_number"], "status": "CANCELLED"}

        if po["status"] not in ("DRAFT", "CONFIRMED"):
            raise ValueError(f"PO {po['po_number']} status {po['status']} tidak dapat dibatalkan")

        cur.execute(
            """UPDATE local_business.purchase_order
               SET status='CANCELLED', notes=COALESCE(notes || '; Batal: ' || %s, %s), cancelled_at=now(), updated_at=now()
               WHERE id=%s
               RETURNING id, po_number, status, cancelled_at""",
            (reason.strip() or "Dibatalkan user", reason.strip() or "Dibatalkan user", po["id"]),
        )
        upd = cur.fetchone()
        if own:
            c.commit()

        return {
            "ok": True,
            "purchase_order_id": upd["id"],
            "po_number": upd["po_number"],
            "status": "CANCELLED",
            "cancelled_at": str(upd["cancelled_at"]),
        }
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def get_purchase_order(
    *,
    business_id: int,
    po_id: int | None = None,
    po_number: str | None = None,
    cur=None,
) -> dict | None:
    """Get full details of a purchase order including lines and supplier."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = """SELECT po.*, s.code AS supplier_code, s.name AS supplier_name,
                        w.code AS warehouse_code, w.name AS warehouse_name
                 FROM local_business.purchase_order po
                 JOIN local_business.supplier s ON s.id=po.supplier_id
                 JOIN multichannel.warehouse w ON w.id=po.warehouse_id
                 WHERE po.business_id=%s"""
        params = [business_id]
        if po_id is not None:
            sql += " AND po.id=%s"
            params.append(po_id)
        elif po_number is not None:
            sql += " AND po.po_number=%s"
            params.append(po_number.strip().upper())
        else:
            raise ValueError("po_id atau po_number harus diberikan")
        cur.execute(sql, params)
        po = cur.fetchone()
        if not po:
            return None

        cur.execute(
            """SELECT pol.*, m.sku, p.name AS product_name
               FROM local_business.purchase_order_line pol
               JOIN multichannel.master_sku m ON m.id=pol.master_sku_id
               JOIN multichannel.product p ON p.id=m.product_id
               WHERE pol.purchase_order_id=%s
               ORDER BY pol.line_no ASC""",
            (po["id"],),
        )
        lines = [dict(r) for r in cur.fetchall()]
        res = dict(po)
        res["lines"] = lines
        return res
    finally:
        if own:
            c.close()


def list_purchase_orders(
    *,
    business_id: int,
    status: str | None = None,
    limit: int = 50,
    cur=None,
) -> list[dict]:
    """List purchase orders for a business."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = """SELECT po.*, s.code AS supplier_code, s.name AS supplier_name,
                        w.code AS warehouse_code, w.name AS warehouse_name
                 FROM local_business.purchase_order po
                 JOIN local_business.supplier s ON s.id=po.supplier_id
                 JOIN multichannel.warehouse w ON w.id=po.warehouse_id
                 WHERE po.business_id=%s"""
        params = [business_id]
        if status is not None:
            sql += " AND po.status=%s"
            params.append(status)
        sql += " ORDER BY po.id DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            c.close()


# ============================================================
# 4. GOODS RECEIPT AGAINST PO (CANONICAL INVENTORY RECEIVE)
# ============================================================

def receive_purchase_order(
    *,
    tenant_id: str = "",
    business_id: int,
    branch_id: int | None = None,
    warehouse_id: int | None = None,
    po_id: int | None = None,
    po_number: str | None = None,
    lines: list[dict],  # [{master_sku_id, quantity, unit_cost}]
    actor: str = "",
    device_id: str = "",
    idempotency_key: str = "",
    cur=None,
) -> dict:
    """Receive goods against a CONFIRMED or PARTIALLY_RECEIVED purchase order.

    - Validates against over-receipt
    - Calls canonical `inv.receive_stock`
    - Transitions PO -> PARTIALLY_RECEIVED or RECEIVED
    - Idempotent per idempotency_key
    """
    if not lines:
        raise ValueError("Penerimaan barang harus memiliki minimal satu item")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        # Check idempotency
        if idempotency_key:
            cur.execute(
                "SELECT * FROM local_business.goods_receipt WHERE reference=%s",
                (idempotency_key,),
            )
            existing_gr = cur.fetchone()
            if existing_gr:
                if own:
                    c.commit()
                return {"ok": True, "duplicate": True, "receipt_id": existing_gr["id"], "receipt_number": existing_gr["receipt_number"]}

        # Lock PO
        sql = """SELECT po.*, s.code AS supplier_code, s.name AS supplier_name
                 FROM local_business.purchase_order po
                 JOIN local_business.supplier s ON s.id=po.supplier_id
                 WHERE po.business_id=%s"""
        params = [business_id]
        if po_id is not None:
            sql += " AND po.id=%s"
            params.append(po_id)
        elif po_number is not None:
            sql += " AND po.po_number=%s"
            params.append(po_number.strip().upper())
        else:
            raise ValueError("po_id atau po_number harus diberikan")
        sql += " FOR UPDATE OF po"
        cur.execute(sql, params)
        po = cur.fetchone()
        if not po:
            raise KeyError("Purchase order tidak ditemukan")

        if po["status"] not in ("CONFIRMED", "PARTIALLY_RECEIVED"):
            raise ValueError(f"Barang tidak dapat diterima untuk PO {po['po_number']} dengan status {po['status']}")

        target_wh = warehouse_id or po["warehouse_id"]
        if target_wh != po["warehouse_id"]:
            raise ValueError(f"Gudang penerimaan ({target_wh}) tidak sesuai dengan gudang PO ({po['warehouse_id']})")

        # Resolve branch if not provided
        if not branch_id:
            cur.execute("SELECT id FROM local_business.branch WHERE business_id=%s AND warehouse_id=%s LIMIT 1", (business_id, target_wh))
            br_row = cur.fetchone()
            branch_id = br_row["id"] if br_row else 0

        # Fetch and lock PO lines
        cur.execute(
            """SELECT * FROM local_business.purchase_order_line
               WHERE purchase_order_id=%s FOR UPDATE""",
            (po["id"],),
        )
        po_lines = {r["master_sku_id"]: dict(r) for r in cur.fetchall()}

        # Validate lines against over-receipt
        validated_receipt_lines = []
        for idx, ln in enumerate(lines, start=1):
            m_id = ln["master_sku_id"]
            if m_id not in po_lines:
                raise KeyError(f"Item #{idx} (master_sku_id {m_id}) tidak terdaftar dalam PO {po['po_number']}")
            po_ln = po_lines[m_id]
            qty_to_receive = int(ln.get("quantity", ln.get("received_qty", 0)))
            if qty_to_receive <= 0:
                raise ValueError(f"Quantity penerimaan item #{idx} harus > 0")

            remaining = po_ln["ordered_qty"] - po_ln["received_qty"]
            if qty_to_receive > remaining:
                raise ValueError(f"Quantity penerimaan ({qty_to_receive}) melebihi sisa pesanan ({remaining}) untuk SKU {po_ln['supplier_sku'] or m_id}")

            unit_cost = float(ln.get("unit_cost", po_ln["unit_cost"]) or 0)
            validated_receipt_lines.append({
                "po_line_id": po_ln["id"],
                "master_sku_id": m_id,
                "sku": ln.get("sku", po_ln["supplier_sku"] or ""),
                "quantity": qty_to_receive,
                "unit_cost": unit_cost,
                "ordered_qty": po_ln["ordered_qty"],
                "received_qty_before": po_ln["received_qty"],
            })

        # Generate Goods Receipt
        cur.execute("SELECT nextval('local_business.goods_receipt_seq') AS n")
        n = cur.fetchone()["n"]
        receipt_number = f"GR-{business_id}-{n:06d}"
        resolved_tenant = tenant_id or f"BIZ-{business_id}"

        cur.execute(
            """INSERT INTO local_business.goods_receipt
               (tenant_id, business_id, branch_id, purchase_order_id, receipt_number,
                supplier_code, supplier_name, reference, status, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'RECEIVED', now())
               RETURNING id""",
            (resolved_tenant, business_id, branch_id, po["id"], receipt_number,
             po["supplier_code"], po["supplier_name"], idempotency_key or po["po_number"]),
        )
        gr_id = cur.fetchone()["id"]

        # Process each item: insert GR line, increment PO line received_qty, call canonical receive_stock
        for vr in validated_receipt_lines:
            cur.execute(
                """INSERT INTO local_business.goods_receipt_line
                   (receipt_id, master_sku_id, sku, quantity, unit_cost, line_total)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (gr_id, vr["master_sku_id"], vr["sku"], vr["quantity"],
                 vr["unit_cost"], vr["quantity"] * vr["unit_cost"]),
            )
            # Update PO line received_qty
            new_po_received = vr["received_qty_before"] + vr["quantity"]
            cur.execute(
                """UPDATE local_business.purchase_order_line
                   SET received_qty=%s WHERE id=%s""",
                (new_po_received, vr["po_line_id"]),
            )
            po_lines[vr["master_sku_id"]]["received_qty"] = new_po_received

            # Canonical inventory receipt
            inv.receive_stock(
                tenant_id=resolved_tenant,
                business_id=business_id,
                branch_id=branch_id,
                warehouse_id=target_wh,
                master_sku_id=vr["master_sku_id"],
                sku=vr["sku"],
                quantity=vr["quantity"],
                unit_cost=vr["unit_cost"],
                reference=f"po:{po['po_number']}:{receipt_number}:{vr['master_sku_id']}",
                note=f"penerimaan PO {po['po_number']} ({receipt_number})",
                actor=actor or "procurement",
                device_id=device_id,
                idempotency_key=f"gr:{receipt_number}:{vr['master_sku_id']}",
                source_document=receipt_number,
                cur=cur,
            )

        # Check if PO is completely received
        all_fully_received = all(
            pl["received_qty"] >= pl["ordered_qty"] for pl in po_lines.values()
        )
        new_po_status = "RECEIVED" if all_fully_received else "PARTIALLY_RECEIVED"
        completed_at = "now()" if all_fully_received else "NULL"

        cur.execute(
            f"""UPDATE local_business.purchase_order
                SET status='{new_po_status}',
                    completed_at={completed_at},
                    updated_at=now()
                WHERE id=%s""",
            (po["id"],),
        )

        core.catat_audit(
            "po_goods_received",
            actor=actor or "system",
            tenant_id=resolved_tenant,
            business_id=business_id,
            branch_id=branch_id,
            payload={
                "po_number": po["po_number"],
                "receipt_number": receipt_number,
                "status": new_po_status,
                "lines_received": len(validated_receipt_lines),
            },
        )

        if own:
            c.commit()

        return {
            "ok": True,
            "receipt_id": gr_id,
            "receipt_number": receipt_number,
            "po_number": po["po_number"],
            "po_status": new_po_status,
            "all_received": all_fully_received,
            "lines_count": len(validated_receipt_lines),
        }
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def create_goods_receipt(
    *,
    tenant_id: str,
    business_id: int,
    branch_id: int,
    warehouse_id: int,
    supplier_code: str = "",
    supplier_name: str = "",
    reference: str = "",
    lines: list[dict],
    actor: str = "",
    device_id: str = "",
) -> dict:
    """Direct goods receipt without PO (backward compatibility for legacy ad-hoc receipts)."""
    if not lines:
        raise ValueError("receipt tanpa line")
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT nextval('local_business.goods_receipt_seq') AS n")
        n = cur.fetchone()["n"]
        receipt_number = f"GR-{business_id}-{n:06d}"
        cur.execute(
            """INSERT INTO local_business.goods_receipt
               (tenant_id, business_id, branch_id, receipt_number, supplier_code,
                supplier_name, reference, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'RECEIVED') RETURNING id""",
            (tenant_id, business_id, branch_id, receipt_number, supplier_code,
             supplier_name, reference),
        )
        rid = cur.fetchone()["id"]
        for ln in lines:
            qty = int(ln["quantity"])
            if qty <= 0:
                raise ValueError("quantity harus > 0")
            unit_cost = float(ln.get("unit_cost", 0))
            cur.execute(
                """INSERT INTO local_business.goods_receipt_line
                   (receipt_id, master_sku_id, sku, quantity, unit_cost, line_total)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (rid, ln["master_sku_id"], ln.get("sku", ""), qty, unit_cost,
                 qty * unit_cost),
            )
            inv.receive_stock(
                tenant_id=tenant_id, business_id=business_id, branch_id=branch_id,
                warehouse_id=warehouse_id, master_sku_id=ln["master_sku_id"],
                sku=ln.get("sku", ""), quantity=qty, unit_cost=unit_cost,
                reference=f"gr:{receipt_number}:{ln['master_sku_id']}",
                note=f"goods receipt {receipt_number}", actor=actor,
                device_id=device_id,
                idempotency_key=f"gr:{receipt_number}:{ln['master_sku_id']}",
                source_document=receipt_number, cur=cur,
            )
        core.catat_audit("goods_receipt_created", actor=actor, tenant_id=tenant_id,
                         business_id=business_id, branch_id=branch_id,
                         payload={"receipt": receipt_number, "lines": len(lines)})
        c.commit()
        return {"receipt_id": rid, "receipt_number": receipt_number, "status": "RECEIVED"}


# ============================================================
# 5. TELEGRAM DURABLE DRAFTS & CONFIRMATION GATE
# ============================================================

def create_procurement_draft(
    *,
    draft_type: str,
    business_id: int,
    owner_id: int,
    telegram_user_id: int,
    payload: dict,
    expires_in_seconds: int = 600,
    cur=None,
) -> dict:
    """Create a durable procurement confirmation draft."""
    token = f"pcd_{secrets.token_hex(8)}"
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """INSERT INTO local_business.telegram_procurement_draft
               (draft_token, draft_type, business_id, owner_id, telegram_user_id,
                payload, status, expires_at, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s, now())
               RETURNING id, draft_token, draft_type, business_id, owner_id, telegram_user_id, status, expires_at""",
            (token, draft_type, business_id, owner_id, telegram_user_id,
             json.dumps(payload, default=str), expires_at),
        )
        row = cur.fetchone()
        if own:
            c.commit()
        res = dict(row)
        res["payload"] = payload
        return res
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def confirm_procurement_draft(
    *,
    draft_token: str,
    caller_telegram_user_id: int,
    cur=None,
) -> dict:
    """Safely and atomically execute a confirmed procurement draft."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.telegram_procurement_draft
               WHERE draft_token=%s FOR UPDATE""",
            (draft_token,),
        )
        draft = cur.fetchone()
        if not draft:
            return {"ok": False, "error": "draft_not_found", "message": "Draft tidak ditemukan."}

        # Idempotent replay safety
        if draft["status"] == "CONFIRMED":
            return {"ok": True, "idempotent": True, "draft_type": draft["draft_type"], "message": "Draft sudah berhasil dieksekusi sebelumnya."}

        if draft["status"] == "CANCELLED":
            return {"ok": False, "error": "draft_cancelled", "message": "Draft ini sudah dibatalkan."}

        # Authorization: caller must match draft author
        if draft["telegram_user_id"] != caller_telegram_user_id:
            return {"ok": False, "error": "wrong_user", "message": "Anda tidak berhak mengonfirmasi draft ini."}

        # Expiry check
        now = datetime.now(timezone.utc)
        if draft["expires_at"] < now:
            cur.execute("UPDATE local_business.telegram_procurement_draft SET status='EXPIRED' WHERE id=%s", (draft["id"],))
            if own:
                c.commit()
            return {"ok": False, "error": "draft_expired", "message": "Draft sudah kedaluwarsa. Silakan ajukan ulang."}

        dtype = draft["draft_type"]
        p = draft["payload"]
        biz_id = draft["business_id"]

        result_data = {}

        if dtype == "SUPPLIER_CREATE":
            supp = create_supplier(
                business_id=biz_id,
                code=p["code"],
                name=p["name"],
                contact_name=p.get("contact_name", ""),
                phone=p.get("phone", ""),
                cur=cur,
            )
            result_data = {"supplier": supp, "message": f"Supplier {supp['code']} ({supp['name']}) berhasil dibuat."}

        elif dtype == "SUPPLIER_EDIT":
            supp = update_supplier(
                business_id=biz_id,
                code=p["code"],
                name=p.get("name"),
                contact_name=p.get("contact_name"),
                phone=p.get("phone"),
                cur=cur,
            )
            result_data = {"supplier": supp, "message": f"Supplier {supp['code']} berhasil diperbarui."}

        elif dtype == "SUPPLIER_OFF":
            supp = deactivate_supplier(business_id=biz_id, code=p["code"], cur=cur)
            result_data = {"supplier": supp, "message": f"Supplier {p['code']} berhasil dinonaktifkan."}

        elif dtype == "RESTOCK_CONFIG":
            cfg = set_supplier_sku(
                business_id=biz_id,
                supplier_id=p["supplier_id"],
                master_sku_id=p["master_sku_id"],
                lead_time_days=p["lead_time_days"],
                min_order_qty=p["min_order_qty"],
                purchase_unit_cost=p.get("purchase_unit_cost"),
                target_stock=p.get("target_stock"),
                preferred=p.get("preferred", True),
                cur=cur,
            )
            result_data = {"config": cfg, "message": f"Konfigurasi restock SKU {p['sku']} berhasil disimpan."}

        elif dtype == "RESTOCK_OFF":
            deactivate_supplier_sku(business_id=biz_id, master_sku_id=p["master_sku_id"], cur=cur)
            result_data = {"message": f"Konfigurasi restock SKU {p['sku']} dinonaktifkan."}

        elif dtype == "PO_CREATE":
            po = create_purchase_order(
                business_id=biz_id,
                supplier_id=p["supplier_id"],
                warehouse_id=p["warehouse_id"],
                lines=p["lines"],
                expected_arrival_date=p.get("expected_arrival_date"),
                notes=p.get("notes", ""),
                created_by=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"po": po, "message": f"Draft PO {po['po_number']} berhasil dibuat."}

        elif dtype == "PO_CONFIRM":
            po = confirm_purchase_order(business_id=biz_id, po_number=p["po_number"], cur=cur)
            result_data = {"po": po, "message": f"PO {po['po_number']} berhasil dikonfirmasi."}

        elif dtype == "PO_CANCEL":
            po = cancel_purchase_order(business_id=biz_id, po_number=p["po_number"], reason=p.get("reason", ""), cur=cur)
            result_data = {"po": po, "message": f"PO {po['po_number']} berhasil dibatalkan."}

        elif dtype == "PO_RECEIVE":
            gr = receive_purchase_order(
                business_id=biz_id,
                po_number=p["po_number"],
                lines=p["lines"],
                actor=f"telegram:{caller_telegram_user_id}",
                idempotency_key=p.get("idempotency_key", f"gr-tg-{draft_token}"),
                cur=cur,
            )
            status_text = "lengkap (RECEIVED)" if gr["all_received"] else "sebagian (PARTIALLY_RECEIVED)"
            result_data = {"receipt": gr, "message": f"Barang PO {gr['po_number']} diterima ({status_text}) dengan nomor {gr['receipt_number']}."}

        elif dtype == "VENDOR_BILL_CREATE":
            bill = create_vendor_bill(
                business_id=biz_id,
                supplier_id=p["supplier_id"],
                purchase_order_id=p.get("purchase_order_id"),
                vendor_reference=p.get("vendor_reference"),
                lines=p.get("lines"),
                notes=p.get("notes", ""),
                created_by=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"bill": bill, "message": f"Draft tagihan {bill['bill_number']} berhasil dibuat."}

        elif dtype == "VENDOR_BILL_POST":
            bill = post_vendor_bill(
                business_id=biz_id,
                bill_number=p["bill_number"],
                actor=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"bill": bill, "message": f"Tagihan {bill['bill_number']} berhasil diposting ke Buku Besar & Utang Usaha."}

        elif dtype == "VENDOR_BILL_CANCEL":
            bill = cancel_vendor_bill(
                business_id=biz_id,
                bill_number=p["bill_number"],
                reason=p.get("reason", ""),
                actor=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"bill": bill, "message": f"Tagihan {bill['bill_number']} berhasil dibatalkan."}

        elif dtype == "VENDOR_PAYMENT":
            pay = create_vendor_payment(
                business_id=biz_id,
                bill_number=p["bill_number"],
                amount=p["amount"],
                payment_account_id=p.get("payment_account_id"),
                idempotency_key=p.get("idempotency_key", f"vp-tg-{draft_token}"),
                notes=p.get("notes", ""),
                actor=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"payment": pay, "message": f"Pembayaran {pay['payment_number']} sebesar Rp{int(pay['amount']):,} untuk tagihan {pay['bill_number']} berhasil dicatat (Status: {pay['bill_status']})."}

        else:
            raise ValueError(f"Unknown draft_type: {dtype}")

        # Mark draft CONFIRMED
        cur.execute(
            """UPDATE local_business.telegram_procurement_draft
               SET status='CONFIRMED', confirmed_at=now()
               WHERE id=%s""",
            (draft["id"],),
        )

        if own:
            c.commit()

        return {"ok": True, "idempotent": False, "draft_type": dtype, "data": result_data}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def cancel_procurement_draft(
    *,
    draft_token: str,
    caller_telegram_user_id: int,
    cur=None,
) -> dict:
    """Cancel a pending procurement draft."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.telegram_procurement_draft
               WHERE draft_token=%s FOR UPDATE""",
            (draft_token,),
        )
        draft = cur.fetchone()
        if not draft:
            return {"ok": False, "error": "draft_not_found", "message": "Draft tidak ditemukan."}

        if draft["status"] == "CONFIRMED":
            return {"ok": False, "error": "already_confirmed", "message": "Draft sudah dikonfirmasi."}

        if draft["telegram_user_id"] != caller_telegram_user_id:
            return {"ok": False, "error": "wrong_user", "message": "Anda tidak berhak membatalkan draft ini."}

        cur.execute(
            """UPDATE local_business.telegram_procurement_draft
               SET status='CANCELLED' WHERE id=%s""",
            (draft["id"],),
        )
        if own:
            c.commit()
        return {"ok": True, "message": "Operasi dibatalkan."}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


# ============================================================
# 6. 3-WAY MATCHING (PO vs GOODS RECEIPT vs VENDOR BILL)
# ============================================================

def match_purchase_order_goods_receipt_bill(
    *,
    business_id: int,
    po_id: int | None = None,
    po_number: str | None = None,
    bill_lines: list[dict] | None = None,
    cur=None,
) -> dict:
    """Deterministic 3-way matching between PO, Goods Receipts, and Vendor Bill.

    Possible match statuses:
    - MATCHED
    - QUANTITY_VARIANCE
    - PRICE_VARIANCE
    - QUANTITY_AND_PRICE_VARIANCE
    - MISSING_PO
    - MISSING_RECEIPT
    - MISSING_COST
    """
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = "SELECT * FROM local_business.purchase_order WHERE business_id=%s"
        params = [business_id]
        if po_id is not None:
            sql += " AND id=%s"
            params.append(po_id)
        elif po_number is not None:
            sql += " AND po_number=%s"
            params.append(po_number.strip().upper())
        else:
            return {"match_status": "MISSING_PO", "message": "Purchase order tidak ditentukan", "can_post": False}

        cur.execute(sql, params)
        po = cur.fetchone()
        if not po:
            return {"match_status": "MISSING_PO", "message": "Purchase order tidak ditemukan", "can_post": False}

        po_id = po["id"]
        cur.execute(
            """SELECT pol.*, ms.sku, p.name AS product_name
               FROM local_business.purchase_order_line pol
               JOIN multichannel.master_sku ms ON ms.id = pol.master_sku_id
               LEFT JOIN multichannel.product p ON p.id = ms.product_id
               WHERE pol.purchase_order_id = %s
               ORDER BY pol.line_no""",
            (po_id,),
        )
        po_lines = cur.fetchall()

        total_received = sum(int(l["received_qty"]) for l in po_lines)
        if total_received == 0:
            return {
                "match_status": "MISSING_RECEIPT",
                "message": "Barang PO belum pernah diterima di gudang (received_qty = 0).",
                "po": po,
                "can_post": False,
            }

        # Check unconfigured / missing purchase cost
        missing_costs = []
        for l in po_lines:
            uc = float(l["unit_cost"] or 0)
            if uc <= 0:
                missing_costs.append(l["sku"])

        if missing_costs:
            return {
                "match_status": "MISSING_COST",
                "message": f"Harga beli belum diatur untuk SKU: {', '.join(missing_costs)}.",
                "po": po,
                "can_post": False,
                "missing_skus": missing_costs,
            }

        if bill_lines is None:
            return {
                "match_status": "MATCHED",
                "message": "3-Way Match sesuai (Dipesan, Diterima, dan Harga Beli cocok).",
                "po": po,
                "po_lines": po_lines,
                "can_post": True,
            }

        qty_variance = False
        price_variance = False

        po_line_map = {l["master_sku_id"]: l for l in po_lines}
        for bl in bill_lines:
            sku_id = bl.get("master_sku_id")
            if sku_id and sku_id in po_line_map:
                pol = po_line_map[sku_id]
                b_qty = float(bl.get("quantity", 0))
                p_rcv = float(pol["received_qty"])
                b_cost = float(bl.get("unit_cost", 0))
                p_cost = float(pol["unit_cost"])

                if b_qty != p_rcv:
                    qty_variance = True
                if b_cost != p_cost:
                    price_variance = True

        if qty_variance and price_variance:
            return {
                "match_status": "QUANTITY_AND_PRICE_VARIANCE",
                "message": "Terdapat selisih jumlah barang dan harga beli terhadap penerimaan PO.",
                "po": po,
                "can_post": False,
            }
        elif qty_variance:
            return {
                "match_status": "QUANTITY_VARIANCE",
                "message": "Terdapat selisih jumlah barang ditagih terhadap jumlah yang diterima di gudang.",
                "po": po,
                "can_post": False,
            }
        elif price_variance:
            return {
                "match_status": "PRICE_VARIANCE",
                "message": "Terdapat selisih harga beli ditagih terhadap harga pada Purchase Order.",
                "po": po,
                "can_post": False,
            }
        else:
            return {
                "match_status": "MATCHED",
                "message": "3-Way Match sesuai (Dipesan, Diterima, dan Harga Beli cocok).",
                "po": po,
                "po_lines": po_lines,
                "can_post": True,
            }
    finally:
        if own:
            c.close()


# ============================================================
# 7. VENDOR BILL CORE (DRAFT -> POSTED -> CANCELLED)
# ============================================================

def create_vendor_bill(
    *,
    business_id: int,
    supplier_id: int | None = None,
    purchase_order_id: int | None = None,
    po_number: str | None = None,
    vendor_reference: str | None = None,
    bill_date: date | str | None = None,
    due_date: date | str | None = None,
    currency: str = "IDR",
    lines: list[dict] | None = None,
    notes: str = "",
    created_by: str = "",
    client_event_id: str | None = None,
    cur=None,
) -> dict:
    """Create a Vendor Bill Draft with 3-way matching."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        po = None
        if po_number is not None and purchase_order_id is None:
            cur.execute("SELECT id FROM local_business.purchase_order WHERE business_id=%s AND po_number=%s", (business_id, po_number.strip().upper()))
            row = cur.fetchone()
            if row:
                purchase_order_id = row["id"]

        if purchase_order_id is not None:
            cur.execute("SELECT * FROM local_business.purchase_order WHERE business_id=%s AND id=%s", (business_id, purchase_order_id))
            po = cur.fetchone()
            if not po:
                raise KeyError(f"Purchase order id {purchase_order_id} tidak ditemukan")
            if supplier_id is None:
                supplier_id = po["supplier_id"]

        if not supplier_id:
            raise ValueError("supplier_id harus diberikan")

        cur.execute("SELECT * FROM local_business.supplier WHERE business_id=%s AND id=%s", (business_id, supplier_id))
        supp = cur.fetchone()
        if not supp:
            raise KeyError(f"Supplier id {supplier_id} tidak ditemukan")

        # If lines not provided, build from PO received quantities
        if lines is None and po is not None:
            cur.execute(
                """SELECT pol.*, ms.sku, p.name AS product_name
                   FROM local_business.purchase_order_line pol
                   JOIN multichannel.master_sku ms ON ms.id = pol.master_sku_id
                   LEFT JOIN multichannel.product p ON p.id = ms.product_id
                   WHERE pol.purchase_order_id = %s
                   ORDER BY pol.line_no""",
                (po["id"],),
            )
            po_lines = cur.fetchall()
            lines = []
            for pol in po_lines:
                rcv = int(pol["received_qty"])
                if rcv > 0:
                    uc = Decimal(str(pol["unit_cost"]))
                    lines.append({
                        "purchase_order_line_id": pol["id"],
                        "master_sku_id": pol["master_sku_id"],
                        "sku": pol["sku"],
                        "description": pol["description"] or pol.get("product_name") or pol["sku"],
                        "quantity": rcv,
                        "unit_cost": uc,
                        "tax_amount": Decimal("0"),
                        "line_total": Decimal(str(rcv)) * uc,
                    })

        if not lines:
            raise ValueError("Tagihan harus memiliki minimal 1 baris item")

        # Run 3-way match
        match_res = match_purchase_order_goods_receipt_bill(
            business_id=business_id,
            po_id=purchase_order_id,
            bill_lines=lines,
            cur=cur,
        )
        match_status = match_res["match_status"]

        bdate = bill_date or date.today()
        if isinstance(bdate, str):
            bdate = date.fromisoformat(bdate)
        ddate = due_date or (bdate + timedelta(days=14))
        if isinstance(ddate, str):
            ddate = date.fromisoformat(ddate)

        # Duplicate vendor reference protection
        vref = (vendor_reference or "").strip() or None
        if vref:
            cur.execute(
                """SELECT id, bill_number FROM local_business.vendor_bill
                   WHERE business_id=%s AND supplier_id=%s AND vendor_reference=%s AND status != 'CANCELLED'""",
                (business_id, supplier_id, vref),
            )
            existing_ref = cur.fetchone()
            if existing_ref:
                raise ValueError(f"Nomor invoice supplier '{vref}' sudah tercatat pada tagihan {existing_ref['bill_number']}")

        subtotal = Decimal("0")
        tax_total = Decimal("0")
        processed_lines = []
        for i, ln in enumerate(lines, start=1):
            qty = Decimal(str(ln["quantity"]))
            if qty <= 0:
                raise ValueError(f"Baris {i}: quantity harus > 0")
            uc = Decimal(str(ln["unit_cost"]))
            if uc < 0:
                raise ValueError(f"Baris {i}: unit_cost tidak boleh negatif")
            ltax = Decimal(str(ln.get("tax_amount", 0)))
            ltot = (qty * uc) + ltax
            subtotal += (qty * uc)
            tax_total += ltax
            processed_lines.append({
                "purchase_order_line_id": ln.get("purchase_order_line_id"),
                "goods_receipt_line_id": ln.get("goods_receipt_line_id"),
                "master_sku_id": ln.get("master_sku_id"),
                "description": ln.get("description") or ln.get("sku", ""),
                "quantity": qty,
                "unit_cost": uc,
                "tax_amount": ltax,
                "line_total": ltot,
                "line_no": i,
                "sku": ln.get("sku", ""),
            })

        grand_total = subtotal + tax_total

        cur.execute("SELECT nextval('local_business.vendor_bill_seq') AS seq")
        seq = cur.fetchone()["seq"]
        bill_number = f"BC-VB-{bdate.year}-{seq:06d}"

        cur.execute(
            """INSERT INTO local_business.vendor_bill
               (business_id, supplier_id, purchase_order_id, bill_number, vendor_reference,
                bill_date, due_date, currency, subtotal, tax_amount, total, paid_amount,
                outstanding_amount, match_status, status, notes, created_by, client_event_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, 'DRAFT', %s, %s, %s)
               RETURNING id, bill_number, match_status, status, created_at""",
            (business_id, supplier_id, purchase_order_id, bill_number, vref,
             bdate, ddate, currency, subtotal, tax_total, grand_total, grand_total,
             match_status, notes, created_by, client_event_id),
        )
        bill_row = cur.fetchone()
        bill_id = bill_row["id"]

        for pln in processed_lines:
            cur.execute(
                """INSERT INTO local_business.vendor_bill_line
                   (vendor_bill_id, purchase_order_line_id, goods_receipt_line_id, master_sku_id,
                    description, quantity, unit_cost, tax_amount, line_total, line_no)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (bill_id, pln["purchase_order_line_id"], pln["goods_receipt_line_id"],
                 pln["master_sku_id"], pln["description"], pln["quantity"], pln["unit_cost"],
                 pln["tax_amount"], pln["line_total"], pln["line_no"]),
            )

        core.catat_audit("vendor_bill_created", actor=created_by, tenant_id="", business_id=business_id,
                         payload={"bill_id": bill_id, "bill_number": bill_number, "total": str(grand_total), "match_status": match_status})

        if own:
            c.commit()

        return {
            "id": bill_id,
            "business_id": business_id,
            "supplier_id": supplier_id,
            "purchase_order_id": purchase_order_id,
            "bill_number": bill_number,
            "vendor_reference": vref,
            "bill_date": str(bdate),
            "due_date": str(ddate),
            "currency": currency,
            "subtotal": float(subtotal),
            "tax_amount": float(tax_total),
            "total": float(grand_total),
            "paid_amount": 0.0,
            "outstanding_amount": float(grand_total),
            "match_status": match_status,
            "status": "DRAFT",
            "lines": processed_lines,
        }
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def get_vendor_bill(
    *,
    business_id: int,
    bill_id: int | None = None,
    bill_number: str | None = None,
    cur=None,
) -> dict | None:
    """Retrieve full vendor bill details."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = """SELECT vb.*, s.code AS supplier_code, s.name AS supplier_name, po.po_number
                 FROM local_business.vendor_bill vb
                 JOIN local_business.supplier s ON s.id = vb.supplier_id
                 LEFT JOIN local_business.purchase_order po ON po.id = vb.purchase_order_id
                 WHERE vb.business_id = %s"""
        params = [business_id]
        if bill_id is not None:
            sql += " AND vb.id = %s"
            params.append(bill_id)
        elif bill_number is not None:
            sql += " AND vb.bill_number = %s"
            params.append(bill_number.strip().upper())
        else:
            raise ValueError("bill_id atau bill_number harus diberikan")

        cur.execute(sql, params)
        bill = cur.fetchone()
        if not bill:
            return None

        res = dict(bill)
        cur.execute(
            """SELECT vbl.*, ms.sku, p.name AS product_name
               FROM local_business.vendor_bill_line vbl
               LEFT JOIN multichannel.master_sku ms ON ms.id = vbl.master_sku_id
               LEFT JOIN multichannel.product p ON p.id = ms.product_id
               WHERE vbl.vendor_bill_id = %s
               ORDER BY vbl.line_no""",
            (bill["id"],),
        )
        res["lines"] = [dict(r) for r in cur.fetchall()]
        return res
    finally:
        if own:
            c.close()


def list_vendor_bills(
    *,
    business_id: int,
    supplier_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    cur=None,
) -> list[dict]:
    """List vendor bills for a business."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = """SELECT vb.*, s.code AS supplier_code, s.name AS supplier_name, po.po_number
                 FROM local_business.vendor_bill vb
                 JOIN local_business.supplier s ON s.id = vb.supplier_id
                 LEFT JOIN local_business.purchase_order po ON po.id = vb.purchase_order_id
                 WHERE vb.business_id = %s"""
        params = [business_id]
        if supplier_id is not None:
            sql += " AND vb.supplier_id = %s"
            params.append(supplier_id)
        if status is not None:
            sql += " AND vb.status = %s"
            params.append(status.strip().upper())
        sql += " ORDER BY vb.id DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            c.close()


def post_vendor_bill(
    *,
    business_id: int,
    bill_id: int | None = None,
    bill_number: str | None = None,
    actor: str = "",
    cur=None,
) -> dict:
    """Post a Vendor Bill: validate 3-way match, record AP liability in Finance Core."""
    from . import finance as biz_fin
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = """SELECT vb.*, s.code AS supplier_code, s.name AS supplier_name
                 FROM local_business.vendor_bill vb
                 JOIN local_business.supplier s ON s.id = vb.supplier_id
                 WHERE vb.business_id = %s"""
        params = [business_id]
        if bill_id is not None:
            sql += " AND vb.id = %s"
            params.append(bill_id)
        elif bill_number is not None:
            sql += " AND vb.bill_number = %s"
            params.append(bill_number.strip().upper())
        else:
            raise ValueError("bill_id atau bill_number harus diberikan")
        sql += " FOR UPDATE"
        cur.execute(sql, params)
        bill = cur.fetchone()
        if not bill:
            raise KeyError("Tagihan supplier tidak ditemukan")

        # Idempotent replay
        if bill["status"] == "POSTED":
            return {
                "ok": True,
                "duplicate": True,
                "bill_id": bill["id"],
                "bill_number": bill["bill_number"],
                "finance_invoice_id": bill["finance_invoice_id"],
                "finance_journal_id": bill["finance_journal_id"],
                "status": "POSTED",
            }

        if bill["status"] != "DRAFT":
            raise ValueError(f"Tagihan {bill['bill_number']} dengan status {bill['status']} tidak dapat diposting")

        if bill["match_status"] != "MATCHED":
            raise ValueError(f"Tagihan {bill['bill_number']} memiliki status match '{bill['match_status']}' dan tidak dapat diposting otomatis")

        if Decimal(str(bill["total"])) <= Decimal("0"):
            raise ValueError(f"Tagihan {bill['bill_number']} memiliki total Rp0 dan tidak dapat diposting ke Keuangan")

        cur.execute(
            """SELECT vbl.*, ms.sku, p.name AS product_name
               FROM local_business.vendor_bill_line vbl
               LEFT JOIN multichannel.master_sku ms ON ms.id = vbl.master_sku_id
               LEFT JOIN multichannel.product p ON p.id = ms.product_id
               WHERE vbl.vendor_bill_id = %s
               ORDER BY vbl.line_no""",
            (bill["id"],),
        )
        lines = cur.fetchall()

        # Post to Finance Core
        fin_res = biz_fin.post_vendor_bill_finance(
            bill_id=bill["id"],
            business_id=business_id,
            supplier_code=bill["supplier_code"],
            supplier_name=bill["supplier_name"],
            bill_number=bill["bill_number"],
            bill_date=str(bill["bill_date"]),
            due_date=str(bill["due_date"]),
            lines=[dict(l) for l in lines],
        )

        cur.execute(
            """UPDATE local_business.vendor_bill
               SET status='POSTED', finance_invoice_id=%s, finance_journal_id=%s,
                   posted_at=now(), updated_at=now()
               WHERE id=%s
               RETURNING id, bill_number, status, finance_invoice_id, finance_journal_id, posted_at""",
            (fin_res["invoice_id"], fin_res["journal_id"], bill["id"]),
        )
        upd = cur.fetchone()

        core.catat_audit("vendor_bill_posted", actor=actor, tenant_id="", business_id=business_id,
                         payload={"bill_id": bill["id"], "bill_number": bill["bill_number"],
                                  "invoice_id": fin_res["invoice_id"], "journal_id": fin_res["journal_id"]})

        if own:
            c.commit()

        return {
            "ok": True,
            "duplicate": False,
            "bill_id": upd["id"],
            "bill_number": upd["bill_number"],
            "finance_invoice_id": upd["finance_invoice_id"],
            "finance_journal_id": upd["finance_journal_id"],
            "status": "POSTED",
            "posted_at": str(upd["posted_at"]),
        }
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def cancel_vendor_bill(
    *,
    business_id: int,
    bill_id: int | None = None,
    bill_number: str | None = None,
    reason: str = "",
    actor: str = "",
    cur=None,
) -> dict:
    """Cancel a DRAFT Vendor Bill."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = "SELECT * FROM local_business.vendor_bill WHERE business_id=%s"
        params = [business_id]
        if bill_id is not None:
            sql += " AND id=%s"
            params.append(bill_id)
        elif bill_number is not None:
            sql += " AND bill_number=%s"
            params.append(bill_number.strip().upper())
        else:
            raise ValueError("bill_id atau bill_number harus diberikan")
        sql += " FOR UPDATE"
        cur.execute(sql, params)
        bill = cur.fetchone()
        if not bill:
            raise KeyError("Tagihan supplier tidak ditemukan")

        if bill["status"] == "CANCELLED":
            return {"ok": True, "duplicate": True, "bill_number": bill["bill_number"], "status": "CANCELLED"}

        if bill["status"] != "DRAFT":
            raise ValueError(f"Tagihan {bill['bill_number']} status {bill['status']} tidak dapat dibatalkan")

        cur.execute(
            """UPDATE local_business.vendor_bill
               SET status='CANCELLED', cancelled_at=now(), updated_at=now()
               WHERE id=%s
               RETURNING id, bill_number, status, cancelled_at""",
            (bill["id"],),
        )
        upd = cur.fetchone()

        core.catat_audit("vendor_bill_cancelled", actor=actor, tenant_id="", business_id=business_id,
                         payload={"bill_id": bill["id"], "bill_number": bill["bill_number"], "reason": reason})

        if own:
            c.commit()
        return {"ok": True, "bill_id": upd["id"], "bill_number": upd["bill_number"], "status": "CANCELLED"}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


# ============================================================
# 8. VENDOR PAYMENT CORE (AP SETTLEMENT)
# ============================================================

def resolve_cash_account(account_id_or_name: str | None = None) -> tuple[str, str]:
    """Resolve cash/bank GL account UUID and label."""
    ident = (account_id_or_name or "1101").strip().upper()
    if ident in ("1102", "BANK", "B"):
        return ("c8ea1bee-168d-4d73-85c7-b4b590773755", "Bank (1102)")
    return ("2b12626b-6140-464a-ab97-7345388e6212", "Kas (1101)")


def create_vendor_payment(
    *,
    business_id: int,
    bill_id: int | None = None,
    bill_number: str | None = None,
    amount: Decimal | float | int,
    payment_account_id: str | None = None,
    payment_date: date | str | None = None,
    idempotency_key: str | None = None,
    notes: str = "",
    actor: str = "",
    cur=None,
) -> dict:
    """Record an AP payment against a POSTED or PARTIALLY_PAID vendor bill."""
    from . import finance as biz_fin
    pay_amount = Decimal(str(amount))
    if pay_amount <= Decimal("0"):
        raise ValueError("Jumlah pembayaran harus lebih besar dari 0")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        # Check idempotency
        if idempotency_key:
            cur.execute(
                """SELECT * FROM local_business.vendor_payment
                   WHERE business_id=%s AND idempotency_key=%s""",
                (business_id, idempotency_key),
            )
            ex_pay = cur.fetchone()
            if ex_pay:
                return {
                    "ok": True,
                    "duplicate": True,
                    "payment_id": ex_pay["id"],
                    "payment_number": ex_pay["payment_number"],
                    "amount": float(ex_pay["amount"]),
                    "status": ex_pay["status"],
                }

        sql = "SELECT * FROM local_business.vendor_bill WHERE business_id=%s"
        params = [business_id]
        if bill_id is not None:
            sql += " AND id=%s"
            params.append(bill_id)
        elif bill_number is not None:
            sql += " AND bill_number=%s"
            params.append(bill_number.strip().upper())
        else:
            raise ValueError("bill_id atau bill_number harus diberikan")
        sql += " FOR UPDATE"
        cur.execute(sql, params)
        bill = cur.fetchone()
        if not bill:
            raise KeyError("Tagihan supplier tidak ditemukan")

        if bill["status"] not in ("POSTED", "PARTIALLY_PAID"):
            raise ValueError(f"Tagihan {bill['bill_number']} dengan status {bill['status']} tidak dapat menerima pembayaran")

        outstanding = Decimal(str(bill["outstanding_amount"]))
        if pay_amount > outstanding:
            raise ValueError(f"Jumlah pembayaran ({pay_amount}) melebihi sisa tagihan ({outstanding})")

        account_uuid, account_label = resolve_cash_account(payment_account_id)

        pdate = payment_date or date.today()
        if isinstance(pdate, str):
            pdate = date.fromisoformat(pdate)

        cur.execute("SELECT nextval('local_business.vendor_payment_seq') AS seq")
        seq = cur.fetchone()["seq"]
        payment_number = f"BC-VP-{pdate.year}-{seq:06d}"

        fin_res = biz_fin.pay_vendor_bill_finance(
            finance_invoice_id=bill["finance_invoice_id"],
            payment_number=payment_number,
            amount=pay_amount,
            payment_date=str(pdate),
            cash_account_id=account_uuid,
        )

        fin_journal_id = fin_res.get("journal_entry_id")
        if not fin_journal_id:
            try:
                with psycopg.connect(
                    host="127.0.0.1", port=15432, dbname="finance_core",
                    user="finance_core_app", password="57e19ff732b18987d31569804f96fb332b6d7a251c6fc9da529624947e586384",
                    row_factory=psycopg.rows.dict_row
                ) as fcon:
                    fcur = fcon.cursor()
                    fcur.execute("SELECT journal_entry_id FROM public.supplier_payments WHERE payment_number=%s", (payment_number,))
                    sp_rec = fcur.fetchone()
                    if sp_rec and sp_rec["journal_entry_id"]:
                        fin_journal_id = str(sp_rec["journal_entry_id"])
            except Exception:
                pass

        cur.execute(
            """INSERT INTO local_business.vendor_payment
               (business_id, vendor_bill_id, supplier_id, payment_number, amount,
                payment_date, payment_account_id, payment_account_name,
                finance_payment_id, finance_journal_id, status, idempotency_key, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'COMPLETED', %s, %s)
               RETURNING id, payment_number, amount, payment_date, status, created_at""",
            (business_id, bill["id"], bill["supplier_id"], payment_number, pay_amount,
             pdate, account_uuid, account_label, fin_res.get("payment_id"),
             fin_journal_id, idempotency_key, notes),
        )
        pay_row = cur.fetchone()

        new_paid = Decimal(str(bill["paid_amount"])) + pay_amount
        new_outstanding = Decimal(str(bill["total"])) - new_paid
        new_status = "PAID" if new_outstanding == Decimal("0") else "PARTIALLY_PAID"

        if new_status == "PAID":
            cur.execute(
                """UPDATE local_business.vendor_bill
                   SET paid_amount=%s, outstanding_amount=%s, status=%s,
                       paid_at=now(), updated_at=now()
                   WHERE id=%s""",
                (new_paid, new_outstanding, new_status, bill["id"]),
            )
        else:
            cur.execute(
                """UPDATE local_business.vendor_bill
                   SET paid_amount=%s, outstanding_amount=%s, status=%s,
                       updated_at=now()
                   WHERE id=%s""",
                (new_paid, new_outstanding, new_status, bill["id"]),
            )

        core.catat_audit("vendor_payment_created", actor=actor, tenant_id="", business_id=business_id,
                         payload={"payment_id": pay_row["id"], "payment_number": payment_number,
                                  "bill_number": bill["bill_number"], "amount": str(pay_amount),
                                  "new_status": new_status})

        if own:
            c.commit()

        return {
            "ok": True,
            "duplicate": False,
            "payment_id": pay_row["id"],
            "payment_number": payment_number,
            "amount": float(pay_amount),
            "payment_date": str(pdate),
            "payment_account": account_label,
            "bill_number": bill["bill_number"],
            "bill_total": float(bill["total"]),
            "paid_amount": float(new_paid),
            "outstanding_amount": float(new_outstanding),
            "bill_status": new_status,
            "finance_journal_id": fin_res.get("journal_entry_id"),
        }
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def list_vendor_payments(
    *,
    business_id: int,
    vendor_bill_id: int | None = None,
    supplier_id: int | None = None,
    limit: int = 50,
    cur=None,
) -> list[dict]:
    """List vendor payments."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        sql = """SELECT vp.*, vb.bill_number, s.name AS supplier_name
                 FROM local_business.vendor_payment vp
                 JOIN local_business.vendor_bill vb ON vb.id = vp.vendor_bill_id
                 JOIN local_business.supplier s ON s.id = vp.supplier_id
                 WHERE vp.business_id = %s"""
        params = [business_id]
        if vendor_bill_id is not None:
            sql += " AND vp.vendor_bill_id = %s"
            params.append(vendor_bill_id)
        if supplier_id is not None:
            sql += " AND vp.supplier_id = %s"
            params.append(supplier_id)
        sql += " ORDER BY vp.id DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            c.close()

