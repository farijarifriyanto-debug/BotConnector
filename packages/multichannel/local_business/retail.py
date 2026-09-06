"""Retail POS — atomic sale creation with concurrency protection.

A completed POS sale atomically coordinates (in ONE PostgreSQL transaction):
  sale + sale lines -> inventory availability check -> location consumption
  -> Finance linkage -> idempotency/audit.

Concurrent cashiers selling the last units cannot oversell: each line locks
the location balance row (SELECT ... FOR UPDATE) before consuming.

Tender methods are RECORDING only (CASH, BANK_TRANSFER_MANUAL, QRIS_MANUAL,
CARD_MANUAL, RECEIVABLE). PAYMENT_CAPTURE stays OFF.
"""

from __future__ import annotations

from datetime import datetime, timezone, date
from decimal import Decimal

from ..persistence.db import koneksi as _pg
from . import core
from . import inventory as inv
from . import finance as lb_finance


class StokTidakCukup(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _next_receipt(cur, business_id: int) -> str:
    # concurrency-safe: use a per-business sequence so two cashiers never
    # get the same receipt number (SELECT MAX(id)+1 would race).
    cur.execute(
        """SELECT nextval('local_business.sale_receipt_seq') AS n""")
    n = cur.fetchone()["n"]
    return f"RCPT-{business_id}-{n:06d}"




def _post_finance_for_sale(*, sale_id: int, business_id: int, receipt: str,
                            lines: list[dict], total, tender_method: str):
    """Call canonical Finance Core posting for a completed retail sale."""
    from decimal import Decimal
    biz = core.get_business(business_id)
    business_name = biz.get("name", f"Local Business {business_id}") if biz else f"Local Business {business_id}"
    # enrich lines with product names
    finance_lines = []
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT 1 FROM local_business.branch
               WHERE id=%s AND business_id=%s AND warehouse_id=%s""",
            (branch_id, business_id, warehouse_id))
        if not cur.fetchone():
            raise KeyError("branch/warehouse bukan milik business")
        cur.execute(
            """SELECT 1 FROM local_business.register r
               JOIN local_business.branch b ON b.id=r.branch_id
               WHERE r.id=%s AND b.business_id=%s AND b.id=%s""",
            (register_id, business_id, branch_id))
        if not cur.fetchone():
            raise KeyError("register bukan milik business")
        if cashier_id is not None:
            cur.execute("SELECT 1 FROM local_business.cashier WHERE id=%s AND business_id=%s",
                        (cashier_id, business_id))
            if not cur.fetchone():
                raise KeyError("cashier bukan milik business")
        if customer_id is not None:
            cur.execute("SELECT 1 FROM local_business.customer WHERE id=%s AND business_id=%s",
                        (customer_id, business_id))
            if not cur.fetchone():
                raise KeyError("customer bukan milik business")
        for ln in lines:
            cur.execute("SELECT p.name FROM multichannel.product p JOIN multichannel.master_sku m ON m.product_id=p.id WHERE m.id=%s", (ln["master_sku_id"],))
            row = cur.fetchone()
            name = row["name"] if row else ln.get("sku", "")
            finance_lines.append({
                "master_sku_id": ln["master_sku_id"],
                "sku": ln.get("sku", ""),
                "name": name,
                "quantity": int(ln["quantity"]),
                "unit_price": ln["resolved_unit_price"],
                "tax_amount": Decimal("0"),
            })
    lb_finance.post_retail_sale_finance(
        sale_id=sale_id, business_id=business_id, business_name=business_name,
        invoice_date=str(date.today()), lines=finance_lines,
        total=Decimal(str(total)), tender_method=tender_method)

def create_sale(
    *,
    tenant_id: str, business_id: int, branch_id: int, register_id: int,
    cashier_id: int | None, warehouse_id: int,
    lines: list[dict],  # [{master_sku_id, sku, quantity, unit_price, discount, description}]
    tender_method: str = "CASH", amount_tendered=0,
    customer_id: int | None = None, shift_id: int | None = None,
    discount: float = 0, tax_amount: float = 0,
    client_event_id: str = "", device_id: str = "",
    created_at_client=None, origin: str = "ONLINE",
    finance_invoice_id: str = "", finance_journal_id: str = "",
) -> dict:
    """Create a completed retail sale atomically. Idempotent per client_event_id."""
    if not lines:
        raise ValueError("sale tanpa line")
    with _pg() as c:
        cur = c.cursor()
        # idempotency: same device+client_event -> return existing
        if client_event_id and device_id:
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

        receipt = _next_receipt(cur, business_id)

        # ---- consume inventory per line (row-locked, oversell-safe) ----
        subtotal = 0
        for ln in lines:
            qty = int(ln["quantity"])
            if qty <= 0:
                raise ValueError("quantity harus > 0")
            
            cur.execute(
                """SELECT 1 FROM local_business.business_product
                   WHERE business_id=%s AND master_sku_id=%s AND active=TRUE""",
                (business_id, ln["master_sku_id"]),
            )
            if not cur.fetchone():
                raise KeyError("produk bukan milik business")
            # Server-side price authority: resolve canonical retail price
            cur.execute(
                """SELECT selling_price FROM local_business.retail_selling_price 
                WHERE business_id=%s AND master_sku_id=%s AND active=TRUE""",
                (business_id, ln["master_sku_id"]))
            price_row = cur.fetchone()
            if not price_row:
                raise ValueError(f"Produk {ln.get('sku', ln['master_sku_id'])} tidak memiliki harga retail aktif")
            
            unit_price = float(price_row["selling_price"])
            ln["resolved_unit_price"] = unit_price
            line_disc = float(ln.get("discount", 0))
            line_total = qty * unit_price - line_disc
            subtotal += line_total
            # consume location stock (raises StokTidakCukup on oversell)
            inv.consume_location(
                tenant_id=tenant_id, business_id=business_id, branch_id=branch_id,
                warehouse_id=warehouse_id, master_sku_id=ln["master_sku_id"],
                sku=ln.get("sku", ""), quantity=qty,
                reference=f"sale:{receipt}:{ln['master_sku_id']}",
                note=f"retail sale {receipt}", actor=f"cashier-{cashier_id}",
                device_id=device_id, idempotency_key=f"sale:{receipt}:{ln['master_sku_id']}",
                source_document=receipt, cur=cur)

        total = subtotal - discount + tax_amount
        change = max(float(amount_tendered) - total, 0)

        # Server-side cash tender validation
        if tender_method == "CASH" and float(amount_tendered) < total:
            raise ValueError(f"Tunai kurang: dibayar {amount_tendered}, total {total}")

        cur.execute(
            """INSERT INTO local_business.sale
               (tenant_id, business_id, branch_id, register_id, cashier_id,
                shift_id, customer_id, receipt_number, sale_type, status,
                subtotal, discount, tax_amount, total, tender_method,
                amount_tendered, change_due, client_event_id, device_id,
                created_at_client, origin, finance_invoice_id, finance_journal_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'RETAIL','COMPLETED',
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (tenant_id, business_id, branch_id, register_id, cashier_id,
             shift_id, customer_id, receipt, subtotal, discount, tax_amount,
             total, tender_method, amount_tendered, change, client_event_id,
             device_id, created_at_client, origin, finance_invoice_id,
             finance_journal_id))
        sale_id = cur.fetchone()["id"]

        for i, ln in enumerate(lines, start=1):
            cur.execute(
                """INSERT INTO local_business.sale_line
                   (sale_id, master_sku_id, sku, description, quantity,
                    unit_price, discount, line_total, is_ingredient, line_no)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,FALSE,%s)""",
                (sale_id, ln["master_sku_id"], ln.get("sku", ""),
                 ln.get("description", ""), int(ln["quantity"]),
                 ln["resolved_unit_price"], float(ln.get("discount", 0)),
                 int(ln["quantity"]) * ln["resolved_unit_price"]
                 - float(ln.get("discount", 0)), i))

        core.catat_audit("sale_created", actor=f"cashier-{cashier_id}",
                         tenant_id=tenant_id, business_id=business_id,
                         branch_id=branch_id,
                         payload={"receipt": receipt, "total": str(total),
                                  "tender": tender_method, "lines": len(lines)})
        c.commit()

        # Post to Finance Core (idempotent). If Finance fails, leave sale COMPLETED
        # so the operational record is durable; reconciliation will repair Finance exactly once.
        try:
            fin = _post_finance_for_sale(
                sale_id=sale_id, business_id=business_id, receipt=receipt,
                lines=lines, total=Decimal(str(total)), tender_method=tender_method)
            if fin and not fin.get("duplicate"):
                cur.execute(
                    "UPDATE local_business.sale SET finance_invoice_id=%s, finance_journal_id=%s WHERE id=%s",
                    (fin.get("invoice_id", ""), fin.get("journal_id", ""), sale_id))
                c.commit()
        except Exception as exc:
            core.catat_audit("sale_finance_deferred", actor="system",
                             tenant_id=tenant_id, business_id=business_id,
                             branch_id=branch_id,
                             payload={"sale_id": sale_id, "receipt": receipt,
                                      "error": str(exc)[:500]})
            c.commit()

        return {"duplicate": False, "sale_id": sale_id, "receipt_number": receipt,
                "subtotal": subtotal, "discount": discount, "tax_amount": tax_amount,
                "total": total, "tender_method": tender_method,
                "amount_tendered": amount_tendered, "change_due": change}


def void_sale(*, sale_id: int, reason: str = "", actor: str = "") -> dict:
    """VOID before completion: reverse inventory consumption, mark VOID."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.sale WHERE id=%s FOR UPDATE", (sale_id,))
        s = cur.fetchone()
        if not s:
            raise KeyError(f"sale {sale_id} tidak ada")
        if s["status"] != "COMPLETED":
            return {"duplicate": True, "status": s["status"]}
        # reverse inventory: return each line to its branch warehouse
        cur.execute(
            """SELECT sl.master_sku_id, sl.sku, sl.quantity, b.warehouse_id
               FROM local_business.sale_line sl
               JOIN local_business.sale s ON s.id=sl.sale_id
               JOIN local_business.branch b ON b.id=s.branch_id
               WHERE sl.sale_id=%s""", (sale_id,))
        for ln in cur.fetchall():
            inv.return_location(
                tenant_id=s["tenant_id"], business_id=s["business_id"],
                branch_id=s["branch_id"], warehouse_id=ln["warehouse_id"],
                master_sku_id=ln["master_sku_id"], sku=ln["sku"],
                quantity=ln["quantity"], reference=f"void:{s['receipt_number']}:{ln['master_sku_id']}",
                note=f"void sale {s['receipt_number']}", actor=actor,
                device_id=s["device_id"],
                idempotency_key=f"void:{s['receipt_number']}:{ln['master_sku_id']}",
                source_document=s["receipt_number"], cur=cur)
        cur.execute(
            """UPDATE local_business.sale SET status='VOID', voided_at=now(),
               void_reason=%s, voided_by=%s WHERE id=%s""",
            (reason, actor, sale_id))
        core.catat_audit("sale_voided", actor=actor, tenant_id=s["tenant_id"],
                         business_id=s["business_id"], branch_id=s["branch_id"],
                         payload={"receipt": s["receipt_number"], "reason": reason})
        c.commit()

        # Reverse Finance Core posting if present. Failure does not break the void.
        try:
            lb_finance.reverse_retail_sale_finance(
                sale_id=sale_id, reference=f"void:{s['receipt_number']}", reason=reason)
        except Exception as exc:
            core.catat_audit("sale_finance_reversal_deferred", actor=actor,
                             tenant_id=s["tenant_id"], business_id=s["business_id"],
                             branch_id=s["branch_id"],
                             payload={"sale_id": sale_id, "receipt": s["receipt_number"],
                                      "error": str(exc)[:500]})

        return {"duplicate": False, "sale_id": sale_id, "status": "VOID"}


def get_sale(sale_id: int, business_id: int | None = None) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.sale WHERE id=%s AND (%s IS NULL OR business_id=%s)",
            (sale_id, business_id, business_id))
        s = cur.fetchone()
        if not s:
            return None
        cur.execute("SELECT * FROM local_business.sale_line WHERE sale_id=%s ORDER BY line_no", (sale_id,))
        s["lines"] = cur.fetchall()
        return s


def list_sales(branch_id: int, limit: int = 100) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.sale WHERE branch_id=%s ORDER BY id DESC LIMIT %s",
            (branch_id, limit))
        return cur.fetchall()


def sales_today(branch_id: int) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT count(*) AS n, COALESCE(SUM(total),0) AS total
               FROM local_business.sale
               WHERE branch_id=%s AND status='COMPLETED'
                 AND created_at >= date_trunc('day', now())""",
            (branch_id,))
        r = cur.fetchone()
        return {"count": int(r["n"]), "total": float(r["total"])}
