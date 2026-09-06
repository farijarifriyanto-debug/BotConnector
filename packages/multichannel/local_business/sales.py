"""Sales Order-to-Cash (Customer, Quotation, Sales Order, Delivery, Customer Invoice, AR, Payment, Return, Credit Note).

One coherent implementation for B2B/Wholesale Order-to-Cash lifecycle.
Preserves existing retail direct cash sale path intact.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ..persistence.db import koneksi as _pg
from ..workflow import finance_core as fc
from . import core, inventory as inv


class SalesError(Exception):
    """Base exception for sales order-to-cash domain."""
    pass


class StokTidakCukup(SalesError):
    pass


class CreditLimitExceeded(SalesError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ============================================================
# SEQUENCES & NUMBERING HELPERS
# ============================================================

def _next_quotation_number(business_id: int, cur) -> str:
    cur.execute("""SELECT nextval('local_business.sales_quotation_seq') AS n""")
    n = cur.fetchone()["n"]
    yr = datetime.now(timezone.utc).year
    return f"BC-SQ-{yr}-{n:06d}"


def _next_sales_order_number(business_id: int, cur) -> str:
    cur.execute("""SELECT nextval('local_business.sales_order_seq') AS n""")
    n = cur.fetchone()["n"]
    yr = datetime.now(timezone.utc).year
    return f"BC-SO-{yr}-{n:06d}"


def _next_sales_delivery_number(business_id: int, cur) -> str:
    cur.execute("""SELECT nextval('local_business.sales_delivery_seq') AS n""")
    n = cur.fetchone()["n"]
    return f"DO-{business_id}-{n:06d}"


def _next_customer_invoice_number(business_id: int, cur) -> str:
    cur.execute("""SELECT nextval('local_business.customer_invoice_seq') AS n""")
    n = cur.fetchone()["n"]
    yr = datetime.now(timezone.utc).year
    return f"BC-CI-{yr}-{n:06d}"


def _next_customer_payment_number(business_id: int, cur) -> str:
    cur.execute("""SELECT nextval('local_business.customer_payment_seq') AS n""")
    n = cur.fetchone()["n"]
    yr = datetime.now(timezone.utc).year
    return f"BC-CP-{yr}-{n:06d}"


def _next_sales_return_number(business_id: int, cur) -> str:
    cur.execute("""SELECT nextval('local_business.sales_return_seq') AS n""")
    n = cur.fetchone()["n"]
    return f"SR-{business_id}-{n:06d}"


def _next_credit_note_number(business_id: int, cur) -> str:
    cur.execute("""SELECT nextval('local_business.credit_note_seq') AS n""")
    n = cur.fetchone()["n"]
    yr = datetime.now(timezone.utc).year
    return f"BC-CN-{yr}-{n:06d}"


# ============================================================
# CANONICAL SELLING PRICE
# ============================================================

def get_canonical_selling_price(
    *,
    business_id: int,
    master_sku_id: int,
    cur=None,
) -> Decimal | None:
    """Resolve canonical selling price for SKU in a business."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT selling_price FROM local_business.retail_selling_price
               WHERE business_id=%s AND master_sku_id=%s AND active=true
               LIMIT 1""",
            (business_id, master_sku_id),
        )
        row = cur.fetchone()
        if row and row["selling_price"] is not None:
            return Decimal(str(row["selling_price"]))
        return None
    finally:
        if own:
            c.close()


def set_canonical_selling_price(
    *,
    business_id: int,
    master_sku_id: int,
    selling_price: Decimal | float | int,
    cur=None,
) -> dict:
    """Set or update canonical selling price for SKU."""
    sp = Decimal(str(selling_price))
    if sp < 0:
        raise ValueError("Harga jual tidak boleh negatif")
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """INSERT INTO local_business.retail_selling_price
               (business_id, master_sku_id, selling_price, active, updated_at)
               VALUES (%s, %s, %s, true, now())
               ON CONFLICT (business_id, master_sku_id) WHERE active=true DO UPDATE SET
                   selling_price=EXCLUDED.selling_price,
                   active=true,
                   updated_at=now()
               RETURNING id, business_id, master_sku_id, selling_price, active""",
            (business_id, master_sku_id, sp),
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


# ============================================================
# CUSTOMER MASTER
# ============================================================

def create_customer(
    *,
    business_id: int,
    code: str,
    name: str,
    phone: str = "",
    email: str = "",
    billing_address: str = "",
    delivery_address: str = "",
    tax_id: str = "",
    payment_terms_days: int = 30,
    credit_limit: Decimal | float | int | None = None,
    notes: str = "",
    cur=None,
) -> dict:
    """Create a new customer in Customer Master. Code is unique per business."""
    code = code.strip().upper()
    name = name.strip()
    if not code:
        raise ValueError("Kode pelanggan wajib diisi")
    if not name:
        raise ValueError("Nama pelanggan wajib diisi")
    if payment_terms_days < 0:
        raise ValueError("Payment terms tidak boleh negatif")

    c_lim = Decimal(str(credit_limit)) if credit_limit is not None and str(credit_limit).strip() != "" else Decimal("0")
    if c_lim < 0:
        raise ValueError("Credit limit tidak boleh negatif")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """INSERT INTO local_business.customer
               (business_id, code, name, phone, email, billing_address, delivery_address,
                tax_id, payment_terms_days, credit_limit, active, notes, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, now(), now())
               RETURNING id, business_id, code, name, phone, email, billing_address, delivery_address,
                         tax_id, payment_terms_days, credit_limit, active, notes, created_at, updated_at""",
            (business_id, code, name, phone, email, billing_address, delivery_address,
             tax_id, payment_terms_days, c_lim, notes),
        )
        row = cur.fetchone()
        if own:
            c.commit()
        return dict(row)
    except psycopg.errors.UniqueViolation:
        if own:
            c.rollback()
        raise ValueError(f"Pelanggan dengan kode '{code}' sudah terdaftar")
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def update_customer(
    *,
    business_id: int,
    code: str,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    billing_address: str | None = None,
    delivery_address: str | None = None,
    tax_id: str | None = None,
    payment_terms_days: int | None = None,
    credit_limit: Decimal | float | int | None = None,
    active: bool | None = None,
    notes: str | None = None,
    cur=None,
) -> dict:
    """Update customer details."""
    code = code.strip().upper()
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.customer
               WHERE business_id=%s AND code=%s FOR UPDATE""",
            (business_id, code),
        )
        cust = cur.fetchone()
        if not cust:
            raise KeyError(f"Pelanggan '{code}' tidak ditemukan")

        new_name = name.strip() if name is not None else cust["name"]
        new_phone = phone if phone is not None else cust["phone"]
        new_email = email if email is not None else cust["email"]
        new_billing = billing_address if billing_address is not None else cust["billing_address"]
        new_delivery = delivery_address if delivery_address is not None else cust["delivery_address"]
        new_tax_id = tax_id if tax_id is not None else cust["tax_id"]
        new_terms = int(payment_terms_days) if payment_terms_days is not None else cust["payment_terms_days"]
        new_limit = Decimal(str(credit_limit)) if credit_limit is not None else cust["credit_limit"]
        new_active = active if active is not None else cust["active"]
        new_notes = notes if notes is not None else cust["notes"]

        cur.execute(
            """UPDATE local_business.customer
               SET name=%s, phone=%s, email=%s, billing_address=%s, delivery_address=%s,
                   tax_id=%s, payment_terms_days=%s, credit_limit=%s, active=%s, notes=%s,
                   updated_at=now()
               WHERE id=%s
               RETURNING id, business_id, code, name, phone, email, billing_address, delivery_address,
                         tax_id, payment_terms_days, credit_limit, active, notes, created_at, updated_at""",
            (new_name, new_phone, new_email, new_billing, new_delivery, new_tax_id,
             new_terms, new_limit, new_active, new_notes, cust["id"]),
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


def deactivate_customer(*, business_id: int, code: str, cur=None) -> dict:
    """Soft-deactivate customer (active=false)."""
    return update_customer(business_id=business_id, code=code, active=False, cur=cur)


def get_customer(*, business_id: int, code_or_id: str | int, cur=None) -> dict | None:
    """Get customer by code or internal ID."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        if isinstance(code_or_id, int) or (isinstance(code_or_id, str) and code_or_id.isdigit()):
            cur.execute(
                """SELECT * FROM local_business.customer
                   WHERE business_id=%s AND (id=%s OR code=%s) LIMIT 1""",
                (business_id, int(code_or_id), str(code_or_id).upper()),
            )
        else:
            cur.execute(
                """SELECT * FROM local_business.customer
                   WHERE business_id=%s AND code=%s LIMIT 1""",
                (business_id, str(code_or_id).strip().upper()),
            )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            c.close()


def list_customers(*, business_id: int, active_only: bool = True, cur=None) -> list[dict]:
    """List customers for a business."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cond = "AND active=true" if active_only else ""
        cur.execute(
            f"""SELECT * FROM local_business.customer
               WHERE business_id=%s {cond}
               ORDER BY name, code""",
            (business_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            c.close()


def get_customer_ar_exposure(*, business_id: int, customer_id: int, cur=None) -> dict:
    """Compute existing AR outstanding + open order exposure for customer."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT id, code, name, credit_limit, active FROM local_business.customer
               WHERE business_id=%s AND id=%s""",
            (business_id, customer_id),
        )
        cust = cur.fetchone()
        if not cust:
            raise KeyError(f"Pelanggan ID {customer_id} tidak ditemukan")

        # Outstanding posted customer invoices
        cur.execute(
            """SELECT COALESCE(SUM(outstanding_amount), 0) AS ar_total
               FROM local_business.customer_invoice
               WHERE business_id=%s AND customer_id=%s AND status IN ('POSTED', 'PARTIALLY_PAID')""",
            (business_id, customer_id),
        )
        ar_total = Decimal(str(cur.fetchone()["ar_total"]))

        # Confirmed sales orders not yet fully invoiced
        cur.execute(
            """SELECT COALESCE(SUM(total), 0) AS so_total
               FROM local_business.sales_order
               WHERE business_id=%s AND customer_id=%s AND status IN ('CONFIRMED', 'PARTIALLY_DELIVERED')""",
            (business_id, customer_id),
        )
        so_total = Decimal(str(cur.fetchone()["so_total"]))

        c_limit = Decimal(str(cust["credit_limit"])) if cust["credit_limit"] is not None else Decimal("0")
        total_exposure = ar_total + so_total
        is_over = (c_limit > 0) and (total_exposure > c_limit)

        return {
            "customer_id": cust["id"],
            "customer_code": cust["code"],
            "customer_name": cust["name"],
            "credit_limit": c_limit,
            "ar_outstanding": ar_total,
            "open_order_exposure": so_total,
            "total_exposure": total_exposure,
            "is_over_limit": is_over,
        }
    finally:
        if own:
            c.close()


# ============================================================
# SALES QUOTATION
# ============================================================

def create_sales_quotation(
    *,
    business_id: int,
    customer_id: int,
    lines: list[dict],
    validity_days: int = 14,
    notes: str = "",
    created_by: str = "system",
    cur=None,
) -> dict:
    """Create a DRAFT sales quotation. Uses canonical selling price. Zero stock/AR mutation."""
    if not lines:
        raise ValueError("Penawaran harga harus memiliki minimal 1 line item")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.customer WHERE business_id=%s AND id=%s""",
            (business_id, customer_id),
        )
        cust = cur.fetchone()
        if not cust:
            raise KeyError(f"Pelanggan ID {customer_id} tidak ditemukan")
        if not cust["active"]:
            raise ValueError(f"Pelanggan '{cust['code']}' sedang nonaktif")

        quot_number = _next_quotation_number(business_id, cur)
        q_date = _today()
        exp_date = q_date + timedelta(days=max(validity_days, 1))

        resolved_lines = []
        subtotal = Decimal("0")
        tax_total = Decimal("0")

        for idx, ln in enumerate(lines, start=1):
            msku_id = ln.get("master_sku_id")
            sku_code = ln.get("sku", "").strip()

            if not msku_id and sku_code:
                cur.execute("""SELECT id, sku FROM multichannel.master_sku WHERE sku=%s""", (sku_code,))
                msku = cur.fetchone()
                if msku:
                    msku_id = msku["id"]
                    sku_code = msku["sku"]
            elif msku_id and not sku_code:
                cur.execute("""SELECT id, sku FROM multichannel.master_sku WHERE id=%s""", (msku_id,))
                msku = cur.fetchone()
                if msku:
                    sku_code = msku["sku"]

            if not msku_id:
                raise KeyError(f"SKU '{sku_code or msku_id}' tidak ditemukan")

            qty = int(ln["quantity"])
            if qty <= 0:
                raise ValueError(f"Quantity untuk {sku_code} harus > 0")

            # Use canonical selling price
            c_price = get_canonical_selling_price(business_id=business_id, master_sku_id=msku_id, cur=cur)
            if c_price is None:
                if "unit_price" in ln and ln["unit_price"] is not None:
                    u_price = Decimal(str(ln["unit_price"]))
                else:
                    raise ValueError(f"Harga jual untuk SKU '{sku_code}' belum dikonfigurasi")
            else:
                u_price = c_price

            cur.execute(
                """SELECT p.name FROM multichannel.product p
                   JOIN multichannel.master_sku m ON m.product_id=p.id
                   WHERE m.id=%s""",
                (msku_id,),
            )
            p_row = cur.fetchone()
            p_name = ln.get("description") or (p_row["name"] if p_row else sku_code)

            tax_amt = Decimal(str(ln.get("tax_amount", 0)))
            line_tot = (u_price * qty) + tax_amt
            subtotal += (u_price * qty)
            tax_total += tax_amt

            resolved_lines.append({
                "master_sku_id": msku_id,
                "sku": sku_code,
                "description": p_name,
                "quantity": qty,
                "unit_price": u_price,
                "tax_amount": tax_amt,
                "line_total": line_tot,
                "line_no": idx,
            })

        total = subtotal + tax_total

        cur.execute(
            """INSERT INTO local_business.sales_quotation
               (business_id, customer_id, quotation_number, quotation_date, expiry_date,
                status, subtotal, tax_amount, total, notes, created_by, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s, %s, now(), now())
               RETURNING id, business_id, customer_id, quotation_number, quotation_date, expiry_date,
                         status, subtotal, tax_amount, total, notes, created_by, created_at, updated_at""",
            (business_id, customer_id, quot_number, q_date, exp_date, subtotal, tax_total, total,
             notes, created_by),
        )
        quot_row = dict(cur.fetchone())

        created_lines = []
        for rln in resolved_lines:
            cur.execute(
                """INSERT INTO local_business.sales_quotation_line
                   (quotation_id, master_sku_id, sku, description, quantity, unit_price,
                    tax_amount, line_total, line_no)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, quotation_id, master_sku_id, sku, description, quantity,
                             unit_price, tax_amount, line_total, line_no""",
                (quot_row["id"], rln["master_sku_id"], rln["sku"], rln["description"],
                 rln["quantity"], rln["unit_price"], rln["tax_amount"], rln["line_total"],
                 rln["line_no"]),
            )
            created_lines.append(dict(cur.fetchone()))

        quot_row["lines"] = created_lines
        quot_row["customer"] = dict(cust)

        if own:
            c.commit()
        return quot_row
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def accept_sales_quotation(
    *,
    business_id: int,
    quotation_number: str,
    cur=None,
) -> dict:
    """Transition quotation from DRAFT/SENT to ACCEPTED."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.sales_quotation
               WHERE business_id=%s AND quotation_number=%s FOR UPDATE""",
            (business_id, quotation_number),
        )
        quot = cur.fetchone()
        if not quot:
            raise KeyError(f"Penawaran {quotation_number} tidak ditemukan")

        if quot["status"] == "ACCEPTED":
            if own:
                c.commit()
            return {"ok": True, "duplicate": True, "quotation": dict(quot)}

        if quot["status"] in ("CONVERTED", "CANCELLED", "EXPIRED"):
            raise ValueError(f"Penawaran status {quot['status']} tidak dapat disetujui")

        if quot["expiry_date"] < _today():
            cur.execute("""UPDATE local_business.sales_quotation SET status='EXPIRED', updated_at=now() WHERE id=%s""", (quot["id"],))
            if own:
                c.commit()
            raise ValueError(f"Penawaran {quotation_number} sudah kedaluwarsa pada {quot['expiry_date']}")

        cur.execute(
            """UPDATE local_business.sales_quotation
               SET status='ACCEPTED', updated_at=now()
               WHERE id=%s
               RETURNING *""",
            (quot["id"],),
        )
        updated = dict(cur.fetchone())
        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "quotation": updated}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def convert_quotation_to_order(
    *,
    business_id: int,
    quotation_number: str,
    warehouse_id: int,
    created_by: str = "system",
    cur=None,
) -> dict:
    """Convert an ACCEPTED quotation into a Sales Order. Exactly once."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.sales_quotation
               WHERE business_id=%s AND quotation_number=%s FOR UPDATE""",
            (business_id, quotation_number),
        )
        quot = cur.fetchone()
        if not quot:
            raise KeyError(f"Penawaran {quotation_number} tidak ditemukan")

        if quot["status"] == "CONVERTED":
            if quot["sales_order_id"]:
                cur.execute("""SELECT * FROM local_business.sales_order WHERE id=%s""", (quot["sales_order_id"],))
                so_row = cur.fetchone()
                if own:
                    c.commit()
                return {"ok": True, "duplicate": True, "sales_order": dict(so_row) if so_row else {}}
            raise ValueError(f"Penawaran {quotation_number} sudah dikonversi")

        if quot["status"] != "ACCEPTED":
            raise ValueError(f"Hanya penawaran berstatus ACCEPTED yang dapat dikonversi (status saat ini: {quot['status']})")

        cur.execute(
            """SELECT * FROM local_business.sales_quotation_line
               WHERE quotation_id=%s ORDER BY line_no""",
            (quot["id"],),
        )
        qlines = cur.fetchall()

        so_lines = [{
            "master_sku_id": ql["master_sku_id"],
            "sku": ql["sku"],
            "description": ql["description"],
            "quantity": ql["quantity"],
            "unit_price": ql["unit_price"],
            "tax_amount": ql["tax_amount"],
        } for ql in qlines]

        so = create_sales_order(
            business_id=business_id,
            customer_id=quot["customer_id"],
            warehouse_id=warehouse_id,
            lines=so_lines,
            quotation_id=quot["id"],
            notes=f"Dikonversi dari penawaran {quotation_number}. {quot['notes']}".strip(),
            created_by=created_by,
            cur=cur,
        )

        cur.execute(
            """UPDATE local_business.sales_quotation
               SET status='CONVERTED', sales_order_id=%s, updated_at=now()
               WHERE id=%s""",
            (so["id"], quot["id"]),
        )

        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "sales_order": so, "quotation_number": quotation_number}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def cancel_sales_quotation(
    *,
    business_id: int,
    quotation_number: str,
    reason: str = "",
    cur=None,
) -> dict:
    """Cancel a DRAFT, SENT, or ACCEPTED quotation."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.sales_quotation
               WHERE business_id=%s AND quotation_number=%s FOR UPDATE""",
            (business_id, quotation_number),
        )
        quot = cur.fetchone()
        if not quot:
            raise KeyError(f"Penawaran {quotation_number} tidak ditemukan")

        if quot["status"] == "CANCELLED":
            if own:
                c.commit()
            return {"ok": True, "duplicate": True, "quotation": dict(quot)}

        if quot["status"] == "CONVERTED":
            raise ValueError(f"Penawaran yang sudah dikonversi ke Sales Order tidak dapat dibatalkan")

        cur.execute(
            """UPDATE local_business.sales_quotation
               SET status='CANCELLED', notes=CASE WHEN notes='' THEN %s ELSE notes || ' | Batal: ' || %s END, updated_at=now()
               WHERE id=%s
               RETURNING *""",
            (reason or "Dibatalkan", reason or "Dibatalkan", quot["id"]),
        )
        updated = dict(cur.fetchone())
        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "quotation": updated}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


# ============================================================
# SALES ORDER
# ============================================================

def create_sales_order(
    *,
    business_id: int,
    customer_id: int,
    warehouse_id: int,
    lines: list[dict],
    quotation_id: int | None = None,
    notes: str = "",
    created_by: str = "system",
    cur=None,
) -> dict:
    """Create a DRAFT Sales Order. Zero stock/AR/Finance mutation."""
    if not lines:
        raise ValueError("Sales Order harus memiliki minimal 1 line item")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.customer WHERE business_id=%s AND id=%s""",
            (business_id, customer_id),
        )
        cust = cur.fetchone()
        if not cust:
            raise KeyError(f"Pelanggan ID {customer_id} tidak ditemukan")
        if not cust["active"]:
            raise ValueError(f"Pelanggan '{cust['code']}' sedang nonaktif")

        cur.execute(
            """SELECT id FROM multichannel.warehouse WHERE id=%s""",
            (warehouse_id,),
        )
        if not cur.fetchone():
            raise KeyError(f"Gudang ID {warehouse_id} tidak ditemukan")

        order_num = _next_sales_order_number(business_id, cur)
        o_date = _today()

        resolved_lines = []
        subtotal = Decimal("0")
        tax_total = Decimal("0")

        for idx, ln in enumerate(lines, start=1):
            msku_id = ln.get("master_sku_id")
            sku_code = ln.get("sku", "").strip()

            if not msku_id and sku_code:
                cur.execute("""SELECT id, sku FROM multichannel.master_sku WHERE sku=%s""", (sku_code,))
                msku = cur.fetchone()
                if msku:
                    msku_id = msku["id"]
                    sku_code = msku["sku"]
            elif msku_id and not sku_code:
                cur.execute("""SELECT id, sku FROM multichannel.master_sku WHERE id=%s""", (msku_id,))
                msku = cur.fetchone()
                if msku:
                    sku_code = msku["sku"]

            if not msku_id:
                raise KeyError(f"SKU '{sku_code or msku_id}' tidak ditemukan")

            qty = int(ln.get("ordered_qty", ln.get("quantity", 0)))
            if qty <= 0:
                raise ValueError(f"Quantity untuk {sku_code} harus > 0")

            if "unit_price" in ln and ln["unit_price"] is not None:
                u_price = Decimal(str(ln["unit_price"]))
            else:
                c_price = get_canonical_selling_price(business_id=business_id, master_sku_id=msku_id, cur=cur)
                if c_price is None:
                    raise ValueError(f"Harga jual untuk SKU '{sku_code}' belum dikonfigurasi")
                u_price = c_price

            cur.execute(
                """SELECT p.name FROM multichannel.product p
                   JOIN multichannel.master_sku m ON m.product_id=p.id
                   WHERE m.id=%s""",
                (msku_id,),
            )
            p_row = cur.fetchone()
            p_name = ln.get("description") or (p_row["name"] if p_row else sku_code)

            tax_amt = Decimal(str(ln.get("tax_amount", 0)))
            line_tot = (u_price * qty) + tax_amt
            subtotal += (u_price * qty)
            tax_total += tax_amt

            resolved_lines.append({
                "master_sku_id": msku_id,
                "sku": sku_code,
                "description": p_name,
                "ordered_qty": qty,
                "unit_price": u_price,
                "tax_amount": tax_amt,
                "line_total": line_tot,
                "line_no": idx,
            })

        total = subtotal + tax_total

        cur.execute(
            """INSERT INTO local_business.sales_order
               (business_id, customer_id, quotation_id, warehouse_id, order_number, order_date,
                status, subtotal, tax_amount, total, notes, created_by, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s, %s, now(), now())
               RETURNING id, business_id, customer_id, quotation_id, warehouse_id, order_number,
                         order_date, status, subtotal, tax_amount, total, notes, created_by, created_at, updated_at""",
            (business_id, customer_id, quotation_id, warehouse_id, order_num, o_date, subtotal,
             tax_total, total, notes, created_by),
        )
        so_row = dict(cur.fetchone())

        created_lines = []
        for rln in resolved_lines:
            cur.execute(
                """INSERT INTO local_business.sales_order_line
                   (sales_order_id, master_sku_id, sku, description, ordered_qty, delivered_qty,
                    invoiced_qty, unit_price, tax_amount, line_total, line_no)
                   VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s)
                   RETURNING id, sales_order_id, master_sku_id, sku, description, ordered_qty,
                             delivered_qty, invoiced_qty, unit_price, tax_amount, line_total, line_no""",
                (so_row["id"], rln["master_sku_id"], rln["sku"], rln["description"],
                 rln["ordered_qty"], rln["unit_price"], rln["tax_amount"], rln["line_total"],
                 rln["line_no"]),
            )
            created_lines.append(dict(cur.fetchone()))

        so_row["lines"] = created_lines
        so_row["customer"] = dict(cust)

        if own:
            c.commit()
        return so_row
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def confirm_sales_order(
    *,
    business_id: int,
    order_number: str,
    actor: str = "system",
    cur=None,
) -> dict:
    """Confirm Sales Order. Checks credit limit. Zero stock/AR/Finance mutation."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.sales_order
               WHERE business_id=%s AND order_number=%s FOR UPDATE""",
            (business_id, order_number),
        )
        so = cur.fetchone()
        if not so:
            raise KeyError(f"Sales Order {order_number} tidak ditemukan")

        if so["status"] in ("CONFIRMED", "PARTIALLY_DELIVERED", "DELIVERED"):
            if own:
                c.commit()
            return {"ok": True, "duplicate": True, "sales_order": dict(so)}

        if so["status"] != "DRAFT":
            raise ValueError(f"Sales Order status {so['status']} tidak dapat dikonfirmasi")

        # Check Customer Credit Limit
        exp = get_customer_ar_exposure(business_id=business_id, customer_id=so["customer_id"], cur=cur)
        if exp["credit_limit"] > 0:
            if exp["ar_outstanding"] + Decimal(str(so["total"])) > exp["credit_limit"]:
                raise CreditLimitExceeded(
                    f"Batas kredit pelanggan '{exp['customer_code']}' terlampaui. "
                    f"Batas: Rp{exp['credit_limit']:,.0f}, Piutang saat ini: Rp{exp['ar_outstanding']:,.0f}, "
                    f"Total pesanan: Rp{Decimal(str(so['total'])):,.0f}"
                )

        cur.execute(
            """UPDATE local_business.sales_order
               SET status='CONFIRMED', updated_at=now()
               WHERE id=%s
               RETURNING *""",
            (so["id"],),
        )
        updated = dict(cur.fetchone())

        cur.execute(
            """SELECT * FROM local_business.sales_order_line
               WHERE sales_order_id=%s ORDER BY line_no""",
            (so["id"],),
        )
        updated["lines"] = [dict(r) for r in cur.fetchall()]

        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "sales_order": updated}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def cancel_sales_order(
    *,
    business_id: int,
    order_number: str,
    reason: str = "",
    actor: str = "system",
    cur=None,
) -> dict:
    """Cancel Sales Order if not yet delivered."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.sales_order
               WHERE business_id=%s AND order_number=%s FOR UPDATE""",
            (business_id, order_number),
        )
        so = cur.fetchone()
        if not so:
            raise KeyError(f"Sales Order {order_number} tidak ditemukan")

        if so["status"] == "CANCELLED":
            if own:
                c.commit()
            return {"ok": True, "duplicate": True, "sales_order": dict(so)}

        if so["status"] in ("PARTIALLY_DELIVERED", "DELIVERED"):
            raise ValueError("Sales Order yang sudah ada pengiriman tidak dapat dibatalkan")

        cur.execute(
            """UPDATE local_business.sales_order
               SET status='CANCELLED', notes=CASE WHEN notes='' THEN %s ELSE notes || ' | Batal: ' || %s END, updated_at=now()
               WHERE id=%s
               RETURNING *""",
            (reason or "Dibatalkan", reason or "Dibatalkan", so["id"]),
        )
        updated = dict(cur.fetchone())
        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "sales_order": updated}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def get_sales_order(*, business_id: int, order_number: str, cur=None) -> dict | None:
    """Get Sales Order details with lines and customer info."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT so.*, c.code AS customer_code, c.name AS customer_name, c.payment_terms_days,
                      w.name AS warehouse_name
               FROM local_business.sales_order so
               JOIN local_business.customer c ON c.id=so.customer_id
               JOIN multichannel.warehouse w ON w.id=so.warehouse_id
               WHERE so.business_id=%s AND so.order_number=%s""",
            (business_id, order_number),
        )
        so = cur.fetchone()
        if not so:
            return None
        res = dict(so)
        cur.execute(
            """SELECT * FROM local_business.sales_order_line
               WHERE sales_order_id=%s ORDER BY line_no""",
            (so["id"],),
        )
        res["lines"] = [dict(r) for r in cur.fetchall()]
        return res
    finally:
        if own:
            c.close()


# ============================================================
# SALES DELIVERY (PHYSICAL STOCK BOUNDARY)
# ============================================================

def deliver_sales_order(
    *,
    business_id: int,
    order_number: str,
    lines: list[dict],
    actor: str = "system",
    idempotency_key: str = "",
    notes: str = "",
    cur=None,
) -> dict:
    """Deliver items for a Sales Order. Calls canonical inventory consumption path. Blocks over-delivery."""
    if not lines:
        raise ValueError("Pengiriman harus memiliki minimal 1 line item")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        if idempotency_key:
            cur.execute(
                """SELECT d.*, so.order_number
                   FROM local_business.sales_delivery d
                   JOIN local_business.sales_order so ON so.id=d.sales_order_id
                   WHERE d.business_id=%s AND d.idempotency_key=%s""",
                (business_id, idempotency_key),
            )
            dup = cur.fetchone()
            if dup:
                if own:
                    c.commit()
                return {"ok": True, "duplicate": True, "delivery": dict(dup)}

        cur.execute(
            """SELECT * FROM local_business.sales_order
               WHERE business_id=%s AND order_number=%s FOR UPDATE""",
            (business_id, order_number),
        )
        so = cur.fetchone()
        if not so:
            raise KeyError(f"Sales Order {order_number} tidak ditemukan")

        if so["status"] not in ("CONFIRMED", "PARTIALLY_DELIVERED"):
            raise ValueError(f"Hanya Sales Order CONFIRMED/PARTIALLY_DELIVERED yang dapat dikirim (status saat ini: {so['status']})")

        cur.execute(
            """SELECT b.tenant_id, br.id AS branch_id, so.warehouse_id
               FROM local_business.sales_order so
               JOIN local_business.business b ON b.id=so.business_id
               JOIN local_business.branch br ON br.business_id=b.id
               WHERE so.id=%s LIMIT 1""",
            (so["id"],),
        )
        ctx = cur.fetchone()
        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        warehouse_id = so["warehouse_id"]

        cur.execute(
            """SELECT * FROM local_business.sales_order_line
               WHERE sales_order_id=%s FOR UPDATE""",
            (so["id"],),
        )
        so_lines = {r["master_sku_id"]: dict(r) for r in cur.fetchall()}

        delivery_num = _next_sales_delivery_number(business_id, cur)
        d_date = _today()

        deliv_lines_to_create = []

        for ln in lines:
            msku_id = ln.get("master_sku_id")
            sku_code = ln.get("sku", "").strip()

            if not msku_id and sku_code:
                cur.execute("""SELECT id FROM multichannel.master_sku WHERE sku=%s""", (sku_code,))
                msku_row = cur.fetchone()
                if msku_row:
                    msku_id = msku_row["id"]

            if not msku_id or msku_id not in so_lines:
                raise KeyError(f"SKU '{sku_code or msku_id}' tidak ada dalam Sales Order {order_number}")

            so_line = so_lines[msku_id]
            qty_deliver = int(ln["quantity"])
            if qty_deliver <= 0:
                raise ValueError(f"Jumlah kirim untuk {so_line['sku']} harus > 0")

            remaining_to_deliver = so_line["ordered_qty"] - so_line["delivered_qty"]
            if qty_deliver > remaining_to_deliver:
                raise ValueError(
                    f"Pengiriman {so_line['sku']} melebihi sisa pesanan: diminta {qty_deliver}, sisa {remaining_to_deliver}"
                )

            line_idem = f"deliv-{order_number}-{so_line['id']}-{qty_deliver}-{secrets.token_hex(4)}" if not idempotency_key else f"{idempotency_key}-{so_line['id']}"
            inv_res = inv.consume_location(
                tenant_id=tenant_id,
                business_id=business_id,
                branch_id=branch_id,
                warehouse_id=warehouse_id,
                master_sku_id=msku_id,
                sku=so_line["sku"],
                quantity=qty_deliver,
                reference=f"SO-DELIV:{order_number}",
                note=f"Pengiriman SO {order_number}",
                actor=actor,
                idempotency_key=line_idem,
                source_document=order_number,
                cur=cur,
            )

            deliv_lines_to_create.append({
                "sales_order_line_id": so_line["id"],
                "master_sku_id": msku_id,
                "sku": so_line["sku"],
                "quantity": qty_deliver,
            })

            new_deliv_qty = so_line["delivered_qty"] + qty_deliver
            cur.execute(
                """UPDATE local_business.sales_order_line
                   SET delivered_qty=%s WHERE id=%s""",
                (new_deliv_qty, so_line["id"]),
            )
            so_lines[msku_id]["delivered_qty"] = new_deliv_qty

        cur.execute(
            """INSERT INTO local_business.sales_delivery
               (business_id, sales_order_id, delivery_number, delivery_date, status,
                idempotency_key, actor, notes, created_at)
               VALUES (%s, %s, %s, %s, 'DELIVERED', %s, %s, %s, now())
               RETURNING *""",
            (business_id, so["id"], delivery_num, d_date, idempotency_key or None, actor, notes),
        )
        deliv_rec = dict(cur.fetchone())

        created_dlines = []
        for idx, dln in enumerate(deliv_lines_to_create, start=1):
            cur.execute(
                """INSERT INTO local_business.sales_delivery_line
                   (delivery_id, sales_order_line_id, master_sku_id, sku, quantity, line_no)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (deliv_rec["id"], dln["sales_order_line_id"], dln["master_sku_id"],
                 dln["sku"], dln["quantity"], idx),
            )
            created_dlines.append(dict(cur.fetchone()))

        deliv_rec["lines"] = created_dlines
        deliv_rec["order_number"] = order_number

        all_fully_delivered = all(
            so_line["delivered_qty"] >= so_line["ordered_qty"]
            for so_line in so_lines.values()
        )
        new_so_status = "DELIVERED" if all_fully_delivered else "PARTIALLY_DELIVERED"

        cur.execute(
            """UPDATE local_business.sales_order
               SET status=%s, updated_at=now() WHERE id=%s""",
            (new_so_status, so["id"]),
        )
        deliv_rec["order_status"] = new_so_status

        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "delivery": deliv_rec}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


# ============================================================
# CUSTOMER INVOICE & ACCOUNTS RECEIVABLE
# ============================================================

def create_customer_invoice(
    *,
    business_id: int,
    customer_id: int,
    sales_order_id: int | None = None,
    lines: list[dict] | None = None,
    due_date: date | str | None = None,
    notes: str = "",
    created_by: str = "system",
    cur=None,
) -> dict:
    """Create DRAFT Customer Invoice based on delivered un-invoiced quantities. Zero Finance Core mutation while DRAFT."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.customer WHERE business_id=%s AND id=%s""",
            (business_id, customer_id),
        )
        cust = cur.fetchone()
        if not cust:
            raise KeyError(f"Pelanggan ID {customer_id} tidak ditemukan")

        inv_num = _next_customer_invoice_number(business_id, cur)
        inv_date = _today()

        if due_date is None:
            terms = cust["payment_terms_days"] or 30
            d_date = inv_date + timedelta(days=terms)
        elif isinstance(due_date, str):
            d_date = date.fromisoformat(due_date)
        else:
            d_date = due_date

        resolved_lines = []
        subtotal = Decimal("0")
        tax_total = Decimal("0")

        if sales_order_id is not None:
            cur.execute(
                """SELECT * FROM local_business.sales_order
                   WHERE business_id=%s AND id=%s FOR UPDATE""",
                (business_id, sales_order_id),
            )
            so = cur.fetchone()
            if not so:
                raise KeyError(f"Sales Order ID {sales_order_id} tidak ditemukan")

            cur.execute(
                """SELECT * FROM local_business.sales_order_line
                   WHERE sales_order_id=%s ORDER BY line_no""",
                (sales_order_id,),
            )
            so_lines = cur.fetchall()

            if lines is not None:
                lines_by_sku = {l.get("sku", ""): l for l in lines}
            else:
                lines_by_sku = None

            for idx, sol in enumerate(so_lines, start=1):
                uninvoiced_deliv = sol["delivered_qty"] - sol["invoiced_qty"]
                if uninvoiced_deliv <= 0:
                    continue

                if lines_by_sku is not None:
                    if sol["sku"] not in lines_by_sku:
                        continue
                    req_qty = int(lines_by_sku[sol["sku"]]["quantity"])
                    if req_qty > uninvoiced_deliv:
                        raise ValueError(f"Kuantitas tagihan {sol['sku']} ({req_qty}) melebihi kuantitas terkirim belum ditagih ({uninvoiced_deliv})")
                    qty = req_qty
                else:
                    qty = uninvoiced_deliv

                u_price = Decimal(str(sol["unit_price"]))
                tax_amt = Decimal(str(sol["tax_amount"])) * (Decimal(qty) / Decimal(sol["ordered_qty"])) if sol["ordered_qty"] > 0 else Decimal("0")
                tax_amt = tax_amt.quantize(Decimal("0.01"))
                line_tot = (u_price * qty) + tax_amt
                subtotal += (u_price * qty)
                tax_total += tax_amt

                resolved_lines.append({
                    "sales_order_line_id": sol["id"],
                    "master_sku_id": sol["master_sku_id"],
                    "sku": sol["sku"],
                    "description": sol["description"],
                    "quantity": qty,
                    "unit_price": u_price,
                    "tax_amount": tax_amt,
                    "line_total": line_tot,
                    "line_no": idx,
                })
        elif lines:
            for idx, ln in enumerate(lines, start=1):
                msku_id = ln["master_sku_id"]
                cur.execute("""SELECT sku FROM multichannel.master_sku WHERE id=%s""", (msku_id,))
                msku_row = cur.fetchone()
                sku_code = msku_row["sku"] if msku_row else ln.get("sku", "")

                qty = int(ln["quantity"])
                u_price = Decimal(str(ln["unit_price"]))
                tax_amt = Decimal(str(ln.get("tax_amount", 0)))
                line_tot = (u_price * qty) + tax_amt
                subtotal += (u_price * qty)
                tax_total += tax_amt

                resolved_lines.append({
                    "sales_order_line_id": None,
                    "master_sku_id": msku_id,
                    "sku": sku_code,
                    "description": ln.get("description", sku_code),
                    "quantity": qty,
                    "unit_price": u_price,
                    "tax_amount": tax_amt,
                    "line_total": line_tot,
                    "line_no": idx,
                })
        else:
            raise ValueError("Tidak ada kuantitas terkirim yang dapat dibuatkan invoice")

        if not resolved_lines:
            raise ValueError("Tidak ada item yang dapat ditagih (belum ada barang yang dikirim)")

        total = subtotal + tax_total

        cur.execute(
            """INSERT INTO local_business.customer_invoice
               (business_id, customer_id, sales_order_id, invoice_number, invoice_date,
                due_date, subtotal, tax_amount, total, paid_amount, outstanding_amount,
                status, notes, created_by, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, 'DRAFT', %s, %s, now(), now())
               RETURNING *""",
            (business_id, customer_id, sales_order_id, inv_num, inv_date, d_date,
             subtotal, tax_total, total, total, notes, created_by),
        )
        inv_row = dict(cur.fetchone())

        created_lines = []
        for rln in resolved_lines:
            cur.execute(
                """INSERT INTO local_business.customer_invoice_line
                   (invoice_id, sales_order_line_id, master_sku_id, sku, description,
                    quantity, unit_price, tax_amount, line_total, line_no)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (inv_row["id"], rln["sales_order_line_id"], rln["master_sku_id"],
                 rln["sku"], rln["description"], rln["quantity"], rln["unit_price"],
                 rln["tax_amount"], rln["line_total"], rln["line_no"]),
            )
            created_lines.append(dict(cur.fetchone()))

            if rln["sales_order_line_id"]:
                cur.execute(
                    """UPDATE local_business.sales_order_line
                       SET invoiced_qty=invoiced_qty+%s WHERE id=%s""",
                    (rln["quantity"], rln["sales_order_line_id"]),
                )

        inv_row["lines"] = created_lines
        inv_row["customer"] = dict(cust)

        if own:
            c.commit()
        return inv_row
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def post_customer_invoice(
    *,
    business_id: int,
    invoice_number: str,
    actor: str = "system",
    cur=None,
) -> dict:
    """Post Customer Invoice to Finance Core (Dr 1201 Piutang Usaha / Cr 4101 Penjualan). Idempotent."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT inv.*, c.code AS customer_code, c.name AS customer_name
               FROM local_business.customer_invoice inv
               JOIN local_business.customer c ON c.id=inv.customer_id
               WHERE inv.business_id=%s AND inv.invoice_number=%s FOR UPDATE""",
            (business_id, invoice_number),
        )
        inv_row = cur.fetchone()
        if not inv_row:
            raise KeyError(f"Customer Invoice {invoice_number} tidak ditemukan")

        if inv_row["status"] in ("POSTED", "PARTIALLY_PAID", "PAID"):
            if own:
                c.commit()
            return {"ok": True, "duplicate": True, "invoice": dict(inv_row)}

        if inv_row["status"] != "DRAFT":
            raise ValueError(f"Customer Invoice status {inv_row['status']} tidak dapat diposting")

        cur.execute(
            """SELECT * FROM local_business.customer_invoice_line
               WHERE invoice_id=%s ORDER BY line_no""",
            (inv_row["id"],),
        )
        inv_lines = cur.fetchall()

        # 1. Ensure customer in Finance Core
        fin_cust_id = fc.pastikan_customer(code=inv_row["customer_code"], name=inv_row["customer_name"])

        # 2. Build Finance Core sales invoice payload
        fc_lines = [{
            "description": ln["description"] or ln["sku"],
            "quantity": str(ln["quantity"]),
            "unit_price": str(ln["unit_price"]),
            "tax_amount": str(ln["tax_amount"]),
        } for ln in inv_lines]

        fc_inv = fc._request("POST", "/api/v1/sales/invoices", {
            "customer_id": fin_cust_id,
            "invoice_number": inv_row["invoice_number"],
            "invoice_date": str(inv_row["invoice_date"]),
            "due_date": str(inv_row["due_date"]),
            "currency": "IDR",
            "source_system": "local_business",
            "source_id": f"invoice-{inv_row['id']}",
            "lines": fc_lines,
        })

        # 3. Issue sales invoice (creates journal Dr 1201 Piutang / Cr 4101 Penjualan)
        issue_res = fc._request("POST", f"/api/v1/sales/invoices/{fc_inv['id']}/issue")
        fin_journal_id = issue_res.get("journal_entry_id")

        cur.execute(
            """UPDATE local_business.customer_invoice
               SET status='POSTED', finance_invoice_id=%s, finance_journal_id=%s,
                   posted_at=now(), updated_at=now()
               WHERE id=%s
               RETURNING *""",
            (fc_inv["id"], fin_journal_id, inv_row["id"]),
        )
        updated = dict(cur.fetchone())
        updated["lines"] = [dict(l) for l in inv_lines]

        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "invoice": updated}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def cancel_customer_invoice(
    *,
    business_id: int,
    invoice_number: str,
    reason: str = "",
    actor: str = "system",
    cur=None,
) -> dict:
    """Cancel DRAFT Customer Invoice."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT * FROM local_business.customer_invoice
               WHERE business_id=%s AND invoice_number=%s FOR UPDATE""",
            (business_id, invoice_number),
        )
        inv_row = cur.fetchone()
        if not inv_row:
            raise KeyError(f"Customer Invoice {invoice_number} tidak ditemukan")

        if inv_row["status"] == "CANCELLED":
            if own:
                c.commit()
            return {"ok": True, "duplicate": True, "invoice": dict(inv_row)}

        if inv_row["status"] != "DRAFT":
            raise ValueError("Hanya Customer Invoice DRAFT yang dapat dibatalkan")

        # Revert invoiced_qty on sales order lines
        cur.execute(
            """SELECT * FROM local_business.customer_invoice_line WHERE invoice_id=%s""",
            (inv_row["id"],),
        )
        for ln in cur.fetchall():
            if ln["sales_order_line_id"]:
                cur.execute(
                    """UPDATE local_business.sales_order_line
                       SET invoiced_qty=GREATEST(invoiced_qty-%s, 0)
                       WHERE id=%s""",
                    (ln["quantity"], ln["sales_order_line_id"]),
                )

        cur.execute(
            """UPDATE local_business.customer_invoice
               SET status='CANCELLED', notes=CASE WHEN notes='' THEN %s ELSE notes || ' | Batal: ' || %s END, updated_at=now()
               WHERE id=%s
               RETURNING *""",
            (reason or "Dibatalkan", reason or "Dibatalkan", inv_row["id"]),
        )
        updated = dict(cur.fetchone())
        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "invoice": updated}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


def get_customer_invoice(*, business_id: int, invoice_number: str, cur=None) -> dict | None:
    """Get Customer Invoice details with lines and payment history."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT inv.*, c.code AS customer_code, c.name AS customer_name, c.payment_terms_days,
                      so.order_number
               FROM local_business.customer_invoice inv
               JOIN local_business.customer c ON c.id=inv.customer_id
               LEFT JOIN local_business.sales_order so ON so.id=inv.sales_order_id
               WHERE inv.business_id=%s AND inv.invoice_number=%s""",
            (business_id, invoice_number),
        )
        row = cur.fetchone()
        if not row:
            return None
        res = dict(row)
        cur.execute(
            """SELECT * FROM local_business.customer_invoice_line
               WHERE invoice_id=%s ORDER BY line_no""",
            (row["id"],),
        )
        res["lines"] = [dict(l) for l in cur.fetchall()]

        cur.execute(
            """SELECT * FROM local_business.customer_payment
               WHERE customer_invoice_id=%s ORDER BY payment_date, id""",
            (row["id"],),
        )
        res["payments"] = [dict(p) for p in cur.fetchall()]
        return res
    finally:
        if own:
            c.close()


# ============================================================
# CUSTOMER PAYMENT (AR COLLECTION)
# ============================================================

def create_customer_payment(
    *,
    business_id: int,
    invoice_number: str,
    amount: Decimal | float | int,
    payment_account_id: str = "1101",
    idempotency_key: str,
    payment_date: date | str | None = None,
    notes: str = "",
    actor: str = "system",
    cur=None,
) -> dict:
    """Record customer payment against POSTED invoice. Idempotent per key. Blocks overpayment."""
    pay_amount = Decimal(str(amount))
    if pay_amount <= 0:
        raise ValueError("Jumlah pembayaran harus lebih besar dari 0")

    pdate = date.fromisoformat(payment_date) if isinstance(payment_date, str) else (payment_date or _today())

    account_code = str(payment_account_id).strip()
    if account_code in ("1101", "KAS", "CASH"):
        account_label = "Kas (1101)"
    elif account_code in ("1102", "BANK", "TRANSFER"):
        account_label = "Bank (1102)"
    else:
        account_label = f"Akun {account_code}"

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        # 1. Check idempotency
        cur.execute(
            """SELECT p.*, inv.invoice_number, inv.status AS invoice_status, inv.outstanding_amount
               FROM local_business.customer_payment p
               JOIN local_business.customer_invoice inv ON inv.id=p.customer_invoice_id
               WHERE p.business_id=%s AND p.idempotency_key=%s""",
            (business_id, idempotency_key),
        )
        dup = cur.fetchone()
        if dup:
            if own:
                c.commit()
            return {"ok": True, "duplicate": True, "payment": dict(dup)}

        # 2. Lock invoice row
        cur.execute(
            """SELECT * FROM local_business.customer_invoice
               WHERE business_id=%s AND invoice_number=%s FOR UPDATE""",
            (business_id, invoice_number),
        )
        inv_row = cur.fetchone()
        if not inv_row:
            raise KeyError(f"Customer Invoice {invoice_number} tidak ditemukan")

        if inv_row["status"] not in ("POSTED", "PARTIALLY_PAID"):
            raise ValueError(f"Pembayaran tidak dapat diproses untuk invoice dengan status {inv_row['status']}")

        curr_outstanding = Decimal(str(inv_row["outstanding_amount"]))
        if pay_amount > curr_outstanding:
            raise ValueError(
                f"Jumlah bayar Rp{pay_amount:,.0f} melebihi sisa piutang Rp{curr_outstanding:,.0f}"
            )

        pay_num = _next_customer_payment_number(business_id, cur)

        # 3. Finance Core payment recording
        p_event = fc._request("POST", "/api/v1/events/business-core", {
            "source_system": "local_business",
            "source_event": "payment.paid",
            "source_event_id": f"cp-{pay_num}-{secrets.token_hex(4)}",
            "schema_version": 1,
            "payment": {
                "external_payment_id": pay_num,
                "order_id": inv_row["invoice_number"],
                "amount": str(pay_amount),
                "currency": "IDR",
                "status": "payment.paid",
            }
        })
        fin_journal_id = p_event.get("journal_entry_id")

        fin_inv_id = inv_row.get("finance_invoice_id")
        if fin_inv_id:
            try:
                unalloc = fc._request("GET", "/api/v1/payments/unallocated")
                matching = [p for p in unalloc.get("payments", []) if p["order_id"] == inv_row["invoice_number"]]
                if matching:
                    alloc_res = fc._request("POST", f"/api/v1/payments/{matching[0]['payment_id']}/allocate", {
                        "invoice_id": fin_inv_id,
                        "amount": str(pay_amount),
                    })
                    fin_journal_id = alloc_res.get("journal_entry_id") or fin_journal_id
            except Exception:
                pass

        # 4. Insert local customer payment
        cur.execute(
            """INSERT INTO local_business.customer_payment
               (business_id, customer_invoice_id, customer_id, payment_number, amount,
                payment_date, payment_account_id, payment_account_name, finance_payment_id,
                finance_journal_id, status, idempotency_key, notes, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'COMPLETED', %s, %s, now())
               RETURNING *""",
            (business_id, inv_row["id"], inv_row["customer_id"], pay_num, pay_amount,
             pdate, account_code, account_label, p_event.get("business_event_id"),
             fin_journal_id, idempotency_key, notes),
        )
        pay_row = dict(cur.fetchone())

        # 5. Update invoice balance and status
        new_paid = Decimal(str(inv_row["paid_amount"])) + pay_amount
        new_outstanding = curr_outstanding - pay_amount
        new_status = "PAID" if new_outstanding <= 0 else "PARTIALLY_PAID"
        paid_at_clause = "paid_at=now()," if new_status == "PAID" else ""

        cur.execute(
            f"""UPDATE local_business.customer_invoice
               SET paid_amount=%s, outstanding_amount=%s, {paid_at_clause}
                   status=%s, updated_at=now()
               WHERE id=%s
               RETURNING *""",
            (new_paid, new_outstanding, new_status, inv_row["id"]),
        )
        upd_inv = dict(cur.fetchone())

        pay_row["invoice_number"] = invoice_number
        pay_row["invoice_status"] = new_status
        pay_row["outstanding_amount"] = new_outstanding

        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "payment": pay_row, "invoice": upd_inv}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


# ============================================================
# AR AGING (DETERMINISTIC READ-ONLY)
# ============================================================

def get_ar_aging(
    *,
    business_id: int,
    customer_code: str | None = None,
    cur=None,
) -> dict:
    """Compute AR Aging buckets for all unpaid posted customer invoices."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        where_cust = ""
        params: list[Any] = [business_id]
        if customer_code:
            where_cust = "AND c.code=%s"
            params.append(customer_code.strip().upper())

        cur.execute(
            f"""SELECT inv.id, inv.invoice_number, inv.invoice_date, inv.due_date,
                      inv.total, inv.paid_amount, inv.outstanding_amount, inv.status,
                      c.code AS customer_code, c.name AS customer_name, c.payment_terms_days
               FROM local_business.customer_invoice inv
               JOIN local_business.customer c ON c.id=inv.customer_id
               WHERE inv.business_id=%s AND inv.status IN ('POSTED', 'PARTIALLY_PAID')
                     AND inv.outstanding_amount > 0 {where_cust}
               ORDER BY inv.due_date ASC, inv.id ASC""",
            tuple(params),
        )
        rows = cur.fetchall()

        today_dt = _today()

        buckets = {
            "CURRENT": Decimal("0"),
            "1_30": Decimal("0"),
            "31_60": Decimal("0"),
            "61_90": Decimal("0"),
            "OVER_90": Decimal("0"),
        }

        invoices = []
        total_outstanding = Decimal("0")

        for r in rows:
            out_amt = Decimal(str(r["outstanding_amount"]))
            due_d = r["due_date"]
            days_overdue = max((today_dt - due_d).days, 0)

            if days_overdue == 0:
                b_name = "CURRENT"
                buckets["CURRENT"] += out_amt
            elif 1 <= days_overdue <= 30:
                b_name = "1_30"
                buckets["1_30"] += out_amt
            elif 31 <= days_overdue <= 60:
                b_name = "31_60"
                buckets["31_60"] += out_amt
            elif 61 <= days_overdue <= 90:
                b_name = "61_90"
                buckets["61_90"] += out_amt
            else:
                b_name = "OVER_90"
                buckets["OVER_90"] += out_amt

            total_outstanding += out_amt

            invoices.append({
                "invoice_number": r["invoice_number"],
                "customer_code": r["customer_code"],
                "customer_name": r["customer_name"],
                "invoice_date": str(r["invoice_date"]),
                "due_date": str(due_d),
                "total": Decimal(str(r["total"])),
                "paid_amount": Decimal(str(r["paid_amount"])),
                "outstanding_amount": out_amt,
                "days_overdue": days_overdue,
                "bucket": b_name,
            })

        return {
            "business_id": business_id,
            "as_of_date": str(today_dt),
            "total_outstanding": total_outstanding,
            "buckets": buckets,
            "invoices": invoices,
        }
    finally:
        if own:
            c.close()


# ============================================================
# SALES RETURN & CREDIT NOTE
# ============================================================

def create_sales_return(
    *,
    business_id: int,
    order_number: str,
    lines: list[dict],
    reason: str = "",
    idempotency_key: str = "",
    actor: str = "system",
    cur=None,
) -> dict:
    """Customer Return & Credit Note. Increases inventory and reduces AR/creates Credit Note."""
    if not lines:
        raise ValueError("Retur harus memiliki minimal 1 line item")

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        if idempotency_key:
            cur.execute(
                """SELECT r.* FROM local_business.sales_order_return r
                   WHERE r.business_id=%s AND r.idempotency_key=%s""",
                (business_id, idempotency_key),
            )
            dup = cur.fetchone()
            if dup:
                if own:
                    c.commit()
                return {"ok": True, "duplicate": True, "sales_return": dict(dup)}

        cur.execute(
            """SELECT so.*, b.tenant_id, br.id AS branch_id
               FROM local_business.sales_order so
               JOIN local_business.business b ON b.id=so.business_id
               JOIN local_business.branch br ON br.business_id=b.id
               WHERE so.business_id=%s AND so.order_number=%s FOR UPDATE""",
            (business_id, order_number),
        )
        so = cur.fetchone()
        if not so:
            raise KeyError(f"Sales Order {order_number} tidak ditemukan")

        cur.execute(
            """SELECT * FROM local_business.sales_order_line
               WHERE sales_order_id=%s FOR UPDATE""",
            (so["id"],),
        )
        so_lines = {r["master_sku_id"]: dict(r) for r in cur.fetchall()}

        return_num = _next_sales_return_number(business_id, cur)
        r_date = _today()

        ret_lines_to_create = []
        total_refund_amount = Decimal("0")

        for ln in lines:
            msku_id = ln.get("master_sku_id")
            sku_code = ln.get("sku", "").strip()

            if not msku_id and sku_code:
                cur.execute("""SELECT id FROM multichannel.master_sku WHERE sku=%s""", (sku_code,))
                msku_row = cur.fetchone()
                if msku_row:
                    msku_id = msku_row["id"]

            if not msku_id or msku_id not in so_lines:
                raise KeyError(f"SKU '{sku_code or msku_id}' tidak ada dalam Sales Order {order_number}")

            so_line = so_lines[msku_id]
            qty_return = int(ln["quantity"])
            if qty_return <= 0:
                raise ValueError(f"Jumlah retur untuk {so_line['sku']} harus > 0")

            if qty_return > so_line["delivered_qty"]:
                raise ValueError(
                    f"Retur {so_line['sku']} ({qty_return}) melebihi kuantitas terkirim ({so_line['delivered_qty']})"
                )

            line_idem = f"ret-{order_number}-{so_line['id']}-{qty_return}-{secrets.token_hex(4)}" if not idempotency_key else f"{idempotency_key}-{so_line['id']}"
            inv.return_location(
                tenant_id=so["tenant_id"],
                business_id=business_id,
                branch_id=so["branch_id"],
                warehouse_id=so["warehouse_id"],
                master_sku_id=msku_id,
                sku=so_line["sku"],
                quantity=qty_return,
                reference=f"SO-RETURN:{order_number}",
                note=f"Retur barang SO {order_number}: {reason}",
                actor=actor,
                idempotency_key=line_idem,
                source_document=order_number,
                cur=cur,
            )

            u_price = Decimal(str(so_line["unit_price"]))
            line_tot = u_price * qty_return
            total_refund_amount += line_tot

            ret_lines_to_create.append({
                "sales_order_line_id": so_line["id"],
                "master_sku_id": msku_id,
                "sku": so_line["sku"],
                "quantity": qty_return,
                "unit_price": u_price,
                "line_total": line_tot,
            })

            cur.execute(
                """UPDATE local_business.sales_order_line
                   SET delivered_qty=delivered_qty-%s WHERE id=%s""",
                (qty_return, so_line["id"]),
            )

        cur.execute(
            """INSERT INTO local_business.sales_order_return
               (business_id, customer_id, sales_order_id, warehouse_id, return_number,
                return_date, status, reason, idempotency_key, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'COMPLETED', %s, %s, now())
               RETURNING *""",
            (business_id, so["customer_id"], so["id"], so["warehouse_id"],
             return_num, r_date, reason, idempotency_key or None),
        )
        ret_rec = dict(cur.fetchone())

        created_rlines = []
        for rln in ret_lines_to_create:
            cur.execute(
                """INSERT INTO local_business.sales_order_return_line
                   (return_id, sales_order_line_id, master_sku_id, sku, quantity, unit_price, line_total)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (ret_rec["id"], rln["sales_order_line_id"], rln["master_sku_id"],
                 rln["sku"], rln["quantity"], rln["unit_price"], rln["line_total"]),
            )
            created_rlines.append(dict(cur.fetchone()))

        ret_rec["lines"] = created_rlines

        # Link to customer invoice if exists
        cur.execute(
            """SELECT * FROM local_business.customer_invoice
               WHERE sales_order_id=%s AND status IN ('POSTED', 'PARTIALLY_PAID')
               ORDER BY id DESC LIMIT 1""",
            (so["id"],),
        )
        inv_to_credit = cur.fetchone()

        cn_num = _next_credit_note_number(business_id, cur)
        cur.execute(
            """INSERT INTO local_business.customer_credit_note
               (business_id, customer_id, customer_invoice_id, sales_order_return_id,
                credit_note_number, amount, status, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'POSTED', now())
               RETURNING *""",
            (business_id, so["customer_id"], inv_to_credit["id"] if inv_to_credit else None,
             ret_rec["id"], cn_num, total_refund_amount),
        )
        cn_rec = dict(cur.fetchone())
        ret_rec["credit_note"] = cn_rec

        if inv_to_credit:
            new_inv_out = max(Decimal(str(inv_to_credit["outstanding_amount"])) - total_refund_amount, Decimal("0"))
            new_inv_tot = max(Decimal(str(inv_to_credit["total"])) - total_refund_amount, Decimal("0"))
            new_status = "PAID" if new_inv_out <= 0 else inv_to_credit["status"]
            cur.execute(
                """UPDATE local_business.customer_invoice
                   SET total=%s, outstanding_amount=%s, status=%s, updated_at=now()
                   WHERE id=%s""",
                (new_inv_tot, new_inv_out, new_status, inv_to_credit["id"]),
            )

        if own:
            c.commit()
        return {"ok": True, "duplicate": False, "sales_return": ret_rec, "credit_note": cn_rec}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()


# ============================================================
# TELEGRAM DURABLE DRAFTS (ORDER-TO-CASH)
# ============================================================

def create_sales_draft(
    *,
    draft_type: str,
    business_id: int,
    owner_id: int,
    telegram_user_id: int,
    payload: dict,
    expires_in_seconds: int = 600,
) -> dict:
    """Create a pending draft for sales order-to-cash mutations."""
    draft_token = secrets.token_urlsafe(16)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.telegram_procurement_draft
               (draft_token, draft_type, business_id, owner_id, telegram_user_id,
                payload, status, expires_at, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s, now())
               RETURNING id, draft_token, draft_type, business_id, owner_id, telegram_user_id,
                         status, expires_at, created_at""",
            (draft_token, draft_type, business_id, owner_id, telegram_user_id,
             json.dumps(payload), expires_at),
        )
        row = cur.fetchone()
        c.commit()
    return dict(row)


def confirm_sales_draft(
    *,
    draft_token: str,
    caller_telegram_user_id: int,
    cur=None,
) -> dict:
    """Execute a pending sales draft atomically. Single-use and idempotent."""
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
            raise KeyError(f"Draft '{draft_token}' tidak ditemukan")

        if draft["telegram_user_id"] != caller_telegram_user_id:
            raise PermissionError("Aksi ditolak: Anda bukan pembuat draft ini")

        if draft["status"] == "CONFIRMED":
            if own:
                c.commit()
            return {"ok": True, "idempotent": True, "draft_type": draft["draft_type"]}

        if draft["status"] == "CANCELLED":
            raise ValueError("Draft ini sudah dibatalkan sebelumnya")

        if draft["expires_at"] < _now():
            cur.execute("""UPDATE local_business.telegram_procurement_draft SET status='EXPIRED' WHERE id=%s""", (draft["id"],))
            if own:
                c.commit()
            raise ValueError("Draft sudah kedaluwarsa. Silakan ulangi perintah")

        dtype = draft["draft_type"]
        p = json.loads(draft["payload"]) if isinstance(draft["payload"], str) else draft["payload"]
        biz_id = draft["business_id"]

        result_data: dict[str, Any] = {}

        if dtype == "CUSTOMER_CREATE":
            cust = create_customer(
                business_id=biz_id,
                code=p["code"],
                name=p["name"],
                phone=p.get("phone", ""),
                email=p.get("email", ""),
                billing_address=p.get("billing_address", ""),
                delivery_address=p.get("delivery_address", ""),
                tax_id=p.get("tax_id", ""),
                payment_terms_days=int(p.get("payment_terms_days", 30)),
                credit_limit=p.get("credit_limit"),
                notes=p.get("notes", ""),
                cur=cur,
            )
            result_data = {"customer": cust, "message": f"Pelanggan '{cust['code']}' ({cust['name']}) berhasil ditambahkan."}

        elif dtype == "CUSTOMER_UPDATE":
            cust = update_customer(
                business_id=biz_id,
                code=p["code"],
                name=p.get("name"),
                phone=p.get("phone"),
                email=p.get("email"),
                billing_address=p.get("billing_address"),
                delivery_address=p.get("delivery_address"),
                tax_id=p.get("tax_id"),
                payment_terms_days=p.get("payment_terms_days"),
                credit_limit=p.get("credit_limit"),
                active=p.get("active"),
                notes=p.get("notes"),
                cur=cur,
            )
            result_data = {"customer": cust, "message": f"Data pelanggan '{cust['code']}' berhasil diperbarui."}

        elif dtype == "CUSTOMER_OFF":
            cust = deactivate_customer(business_id=biz_id, code=p["code"], cur=cur)
            result_data = {"customer": cust, "message": f"Pelanggan '{cust['code']}' dinonaktifkan."}

        elif dtype == "QUOTATION_CREATE":
            quot = create_sales_quotation(
                business_id=biz_id,
                customer_id=p["customer_id"],
                lines=p["lines"],
                validity_days=int(p.get("validity_days", 14)),
                notes=p.get("notes", ""),
                created_by=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"quotation": quot, "message": f"Draft Penawaran {quot['quotation_number']} berhasil dibuat."}

        elif dtype == "QUOTATION_ACCEPT":
            q_res = accept_sales_quotation(business_id=biz_id, quotation_number=p["quotation_number"], cur=cur)
            result_data = {"quotation": q_res["quotation"], "message": f"Penawaran {p['quotation_number']} disetujui (ACCEPTED)."}

        elif dtype == "QUOTATION_CONVERT":
            conv = convert_quotation_to_order(
                business_id=biz_id,
                quotation_number=p["quotation_number"],
                warehouse_id=p["warehouse_id"],
                created_by=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"sales_order": conv["sales_order"], "message": f"Penawaran {p['quotation_number']} berhasil dikonversi ke Sales Order {conv['sales_order']['order_number']}."}

        elif dtype == "SALES_ORDER_CREATE":
            so = create_sales_order(
                business_id=biz_id,
                customer_id=p["customer_id"],
                warehouse_id=p["warehouse_id"],
                lines=p["lines"],
                quotation_id=p.get("quotation_id"),
                notes=p.get("notes", ""),
                created_by=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"sales_order": so, "message": f"Draft Sales Order {so['order_number']} berhasil dibuat."}

        elif dtype == "SALES_ORDER_CONFIRM":
            so_res = confirm_sales_order(
                business_id=biz_id,
                order_number=p["order_number"],
                actor=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"sales_order": so_res["sales_order"], "message": f"Sales Order {p['order_number']} berhasil dikonfirmasi (CONFIRMED)."}

        elif dtype == "SALES_ORDER_CANCEL":
            so_res = cancel_sales_order(
                business_id=biz_id,
                order_number=p["order_number"],
                reason=p.get("reason", ""),
                actor=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"sales_order": so_res["sales_order"], "message": f"Sales Order {p['order_number']} berhasil dibatalkan."}

        elif dtype == "SALES_ORDER_DELIVER":
            deliv_res = deliver_sales_order(
                business_id=biz_id,
                order_number=p["order_number"],
                lines=p["lines"],
                actor=f"telegram:{caller_telegram_user_id}",
                idempotency_key=p.get("idempotency_key", f"do-tg-{draft_token}"),
                notes=p.get("notes", ""),
                cur=cur,
            )
            d = deliv_res["delivery"]
            result_data = {"delivery": d, "message": f"Pengiriman {d['delivery_number']} untuk SO {d['order_number']} berhasil dicatat (status: {d['order_status']})."}

        elif dtype == "CUSTOMER_INVOICE_CREATE":
            inv_res = create_customer_invoice(
                business_id=biz_id,
                customer_id=p["customer_id"],
                sales_order_id=p.get("sales_order_id"),
                lines=p.get("lines"),
                due_date=p.get("due_date"),
                notes=p.get("notes", ""),
                created_by=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"invoice": inv_res, "message": f"Draft Invoice {inv_res['invoice_number']} berhasil dibuat."}

        elif dtype == "CUSTOMER_INVOICE_POST":
            post_res = post_customer_invoice(
                business_id=biz_id,
                invoice_number=p["invoice_number"],
                actor=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            result_data = {"invoice": post_res["invoice"], "message": f"Invoice {p['invoice_number']} berhasil diposting ke Piutang & Buku Besar."}

        elif dtype == "CUSTOMER_PAYMENT":
            pay_res = create_customer_payment(
                business_id=biz_id,
                invoice_number=p["invoice_number"],
                amount=p["amount"],
                payment_account_id=p.get("payment_account_id", "1101"),
                idempotency_key=p.get("idempotency_key", f"cp-tg-{draft_token}"),
                notes=p.get("notes", ""),
                actor=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            pay = pay_res["payment"]
            result_data = {"payment": pay, "invoice": pay_res["invoice"], "message": f"Penerimaan pembayaran {pay['payment_number']} sebesar Rp{Decimal(str(pay['amount'])):,.0f} berhasil dicatat."}

        elif dtype == "SALES_RETURN_CREATE":
            ret_res = create_sales_return(
                business_id=biz_id,
                order_number=p["order_number"],
                lines=p["lines"],
                reason=p.get("reason", ""),
                idempotency_key=p.get("idempotency_key", f"sr-tg-{draft_token}"),
                actor=f"telegram:{caller_telegram_user_id}",
                cur=cur,
            )
            ret = ret_res["sales_return"]
            result_data = {"sales_return": ret, "credit_note": ret_res.get("credit_note"), "message": f"Retur penjualan {ret['return_number']} berhasil dicatat dan stok dikembalikan."}

        else:
            raise ValueError(f"Jenis draft sales tidak dikenali: {dtype}")

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


def cancel_sales_draft(
    *,
    draft_token: str,
    caller_telegram_user_id: int,
    cur=None,
) -> dict:
    """Cancel a pending sales draft."""
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
            raise KeyError(f"Draft '{draft_token}' tidak ditemukan")

        if draft["telegram_user_id"] != caller_telegram_user_id:
            raise PermissionError("Aksi ditolak: Anda bukan pembuat draft ini")

        if draft["status"] == "CANCELLED":
            if own:
                c.commit()
            return {"ok": True, "duplicate": True}

        if draft["status"] == "CONFIRMED":
            raise ValueError("Draft yang sudah dikonfirmasi tidak dapat dibatalkan")

        cur.execute(
            """UPDATE local_business.telegram_procurement_draft
               SET status='CANCELLED'
               WHERE id=%s""",
            (draft["id"],),
        )

        if own:
            c.commit()
        return {"ok": True, "duplicate": False}
    except Exception:
        if own:
            c.rollback()
        raise
    finally:
        if own:
            c.close()
