"""Finance Core integration for Local Business.

Reuses the canonical Finance Core contracts:
  - inventory items sync (POST /api/v1/inventory/items/sync)
  - inventory sales invoice (POST /api/v1/inventory/sales-invoices + issue)
  - inventory purchase invoice (POST /api/v1/inventory/purchase-invoices + issue)
  - cash/bank transaction (POST /api/v1/bank/transactions)

Retail cash sale maps through canonical accounts (SALES_REVENUE, COGS,
INVENTORY, CASH/BANK, OUTPUT_TAX). Restaurant ingredient consumption uses
the canonical Inventory/COGS contract. Transfers within one tenant do NOT
create revenue/expense. Duplicate POS sync never duplicates Finance posting
(idempotency keys + unique constraints).

PAYMENT_CAPTURE stays OFF: manual QRIS/card/transfer recording is NOT
represented as automated payment capture.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from ..persistence.db import koneksi as _pg
from ..workflow import finance_core as fc
from . import core


SOURCE_SYSTEM = "local_business"


def _create_finance_table() -> None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS local_business.sale_finance (
                id            BIGSERIAL PRIMARY KEY,
                sale_id       BIGINT NOT NULL REFERENCES local_business.sale(id),
                invoice_number TEXT NOT NULL,
                invoice_id    TEXT NOT NULL,
                journal_id    TEXT NOT NULL,
                customer_code TEXT NOT NULL,
                total         NUMERIC(20,2) NOT NULL,
                status        TEXT NOT NULL DEFAULT 'POSTED',
                posted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_sale_finance UNIQUE (sale_id)
            )"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS local_business.restaurant_finance (
                id            BIGSERIAL PRIMARY KEY,
                order_id      BIGINT NOT NULL REFERENCES local_business.restaurant_order(id),
                invoice_number TEXT NOT NULL,
                invoice_id    TEXT NOT NULL,
                journal_id    TEXT NOT NULL,
                customer_code TEXT NOT NULL,
                total         NUMERIC(20,2) NOT NULL,
                status        TEXT NOT NULL DEFAULT 'POSTED',
                posted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_restaurant_finance UNIQUE (order_id)
            )"""
        )
        c.commit()




def _record_deferred_sale_finance(*, sale_id: int, business_id: int,
                                   invoice_number: str, total: Decimal, error: str = "") -> None:
    """Record that Finance Core posting is deferred so retry can be idempotent and visible."""
    _create_finance_table()
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.sale_finance
               (sale_id, invoice_number, invoice_id, journal_id, customer_code, total, status)
               VALUES (%s,%s,'','','',%s,'DEFERRED')
               ON CONFLICT (sale_id) DO UPDATE SET
                   status='DEFERRED',
                   total=EXCLUDED.total,
                   posted_at=now()""",
            (sale_id, invoice_number, total))
        c.commit()
    core.catat_audit("sale_finance_deferred", tenant_id="", business_id=business_id,
                     payload={"sale_id": sale_id, "invoice": invoice_number,
                              "error": error})

def _sync_inventory_item(master_sku_id: int, sku: str, name: str) -> str:
    """Sync a master SKU to Finance Core inventory items. Returns item id."""
    d = fc._request("POST", "/api/v1/inventory/items/sync", {
        "source_system": SOURCE_SYSTEM,
        "external_product_id": f"sku-{master_sku_id}",
        "sku": sku,
        "name": name or sku,
        "unit": "pcs",
        "active": True,
    })
    return d.get("inventory_item_id", "")


def _ensure_customer(business_id: int, business_name: str) -> str:
    """Ensure a Finance Core customer for the business (idempotent by code)."""
    code = f"LB-{business_id}"
    return fc.pastikan_customer(code=code, name=business_name or f"Local Business {business_id}")


def _ensure_supplier(supplier_code: str, supplier_name: str) -> str:
    """Ensure a Finance Core supplier (idempotent by code)."""
    d = fc._request("GET", "/api/v1/suppliers")
    for s in d.get("suppliers", []):
        if s["code"] == supplier_code:
            return s["id"]
    d = fc._request("POST", "/api/v1/suppliers", {
        "code": supplier_code, "name": supplier_name})
    return d["id"]


def post_retail_sale_finance(
    *, sale_id: int, business_id: int, business_name: str,
    invoice_date: str, lines: list[dict],  # [{master_sku_id, sku, name, quantity, unit_price, tax_amount}]
    total: Decimal, tender_method: str = "CASH",
) -> dict:
    """Post a retail sale to Finance Core via canonical inventory sales invoice.

    Idempotent per sale_id. Returns journal_id.
    """
    _create_finance_table()
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT id, status FROM local_business.sale_finance WHERE sale_id=%s", (sale_id,))
        row = cur.fetchone()
        if row:
            status = row["status"]
            c.rollback()
            if status == "POSTED":
                return {"duplicate": True, "reason": "already posted"}
            # DEFERRED rows are allowed to retry
        c.commit()

    customer_id = _ensure_customer(business_id, business_name)
    invoice_number = f"LB-SALE-{sale_id}"
    # ensure inventory items exist in Finance Core
    for ln in lines:
        _sync_inventory_item(ln["master_sku_id"], ln["sku"], ln.get("name", ln["sku"]))

    inv_lines = []
    for ln in lines:
        inv_lines.append({
            "source_system": SOURCE_SYSTEM,
            "external_product_id": f"sku-{ln['master_sku_id']}",
            "description": ln.get("name", ln["sku"]),
            "quantity": int(ln["quantity"]),
            "unit_price": str(Decimal(str(ln["unit_price"]))),
            "tax_amount": str(Decimal(str(ln.get("tax_amount", 0)))),
        })

    try:
        inv = fc._request("POST", "/api/v1/inventory/sales-invoices", {
            "customer_code": f"LB-{business_id}",
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "due_date": (date.fromisoformat(invoice_date) + timedelta(days=14)).isoformat(),
            "currency": "IDR",
            "lines": inv_lines,
        })
        issued = fc._request("POST", f"/api/v1/inventory/sales-invoices/{inv['invoice_id']}/issue")
        journal_id = issued.get("journal_entry_id", "")
    except Exception as exc:
        _record_deferred_sale_finance(sale_id=sale_id, business_id=business_id,
                                       invoice_number=invoice_number, total=total,
                                       error=str(exc)[:500])
        raise

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.sale_finance
               (sale_id, invoice_number, invoice_id, journal_id, customer_code, total, status)
               VALUES (%s,%s,%s,%s,%s,%s,'POSTED')
               ON CONFLICT (sale_id) DO UPDATE SET
                   invoice_number=EXCLUDED.invoice_number,
                   invoice_id=EXCLUDED.invoice_id,
                   journal_id=EXCLUDED.journal_id,
                   customer_code=EXCLUDED.customer_code,
                   total=EXCLUDED.total,
                   status='POSTED',
                   posted_at=now()""",
            (sale_id, invoice_number, inv["invoice_id"], journal_id,
             f"LB-{business_id}", total))
        c.commit()
    core.catat_audit("sale_finance_posted", tenant_id="", business_id=business_id,
                     payload={"sale_id": sale_id, "invoice": invoice_number,
                              "journal": journal_id})
    return {"duplicate": False, "invoice_id": inv["invoice_id"], "journal_id": journal_id}






def reverse_retail_sale_finance(*, sale_id: int, reference: str = "", reason: str = "") -> dict:
    """Reverse the Finance Core effects of a retail sale via canonical sales return.

    Idempotent via idempotency_key. Requires the sale to have a POSTED sale_finance row.
    """
    _create_finance_table()
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.sale_finance WHERE sale_id=%s", (sale_id,))
        sf = cur.fetchone()
        if not sf:
            return {"duplicate": False, "reversed": False, "reason": "no finance posting to reverse"}
        if sf["status"] == "REVERSED":
            return {"duplicate": True, "reversed": True, "reason": "already reversed"}
        if sf["status"] != "POSTED":
            return {"duplicate": False, "reversed": False, "reason": f"sale_finance status {sf['status']}"}
        cur.execute("SELECT business_id FROM local_business.sale WHERE id=%s", (sale_id,))
        sale_row = cur.fetchone()
        business_id = sale_row["business_id"] if sale_row else 0
        invoice_number = sf["invoice_number"]

    # Find original SALE_OUT inventory movements in Finance Core
    movements = fc._request("GET", f"/api/v1/inventory/movements?limit=500").get("movements", [])
    # source_id may be the invoice_id UUID (issue step) or a prefixed invoice number (create step)
    invoice_id = sf.get("invoice_id") or ""
    sale_outs = [m for m in movements
                 if (m["source_id"] == invoice_id or m["source_id"].startswith(f"inventory-api:{invoice_number}"))
                 and m["movement_type"] == "SALE_OUT"]
    if not sale_outs:
        return {"duplicate": False, "reversed": False, "reason": "no matching SALE_OUT movements in Finance Core"}

    return_ids = []
    for m in sale_outs:
        idempotency_key = f"lb-return:{sale_id}:{m['id']}"
        try:
            res = fc._request("POST", "/api/v1/inventory/sales-returns", {
                "original_inventory_movement_id": m["id"],
                "quantity": str(m["quantity"]),
                "reference": reference or f"LB-RETURN-{sale_id}",
                "reason": reason or "retail sale return/void",
                "idempotency_key": idempotency_key,
            })
            return_ids.append(res.get("return_id"))
        except Exception as exc:
            # Idempotent: if already exists, ignore
            if "idempotency" in str(exc).lower() or "already" in str(exc).lower():
                continue
            raise

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "UPDATE local_business.sale_finance SET status='REVERSED' WHERE sale_id=%s",
            (sale_id,))
        c.commit()
    core.catat_audit("sale_finance_reversed", tenant_id="", business_id=business_id,
                     payload={"sale_id": sale_id, "invoice": invoice_number,
                              "finance_return_ids": return_ids})
    return {"duplicate": False, "reversed": True, "return_ids": return_ids}

def reconcile_retail_sale_finance(sale_id: int) -> dict:
    """Repair missing Finance posting for an existing retail sale. Idempotent."""
    _create_finance_table()
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT status FROM local_business.sale_finance WHERE sale_id=%s", (sale_id,))
        row = cur.fetchone()
        if row and row["status"] == "POSTED":
            return {"duplicate": True, "reason": "finance already posted"}
        # DEFERRED rows continue to retry below
        cur.execute("SELECT * FROM local_business.sale WHERE id=%s", (sale_id,))
        sale = cur.fetchone()
        if not sale:
            raise KeyError(f"sale {sale_id} tidak ada")
        if sale["status"] != "COMPLETED":
            return {"duplicate": False, "posted": False, "reason": f"sale status {sale['status']}"}
        cur.execute("SELECT * FROM local_business.sale_line WHERE sale_id=%s ORDER BY line_no", (sale_id,))
        sale_lines = cur.fetchall()
        cur.execute("SELECT p.name, m.id AS master_sku_id, m.sku FROM multichannel.product p JOIN multichannel.master_sku m ON m.product_id=p.id WHERE m.id=%s", (sale_lines[0]["master_sku_id"],))
        # Fetch all product names
        line_map = {}
        cur.execute("""SELECT m.id AS master_sku_id, m.sku, p.name
                       FROM multichannel.master_sku m
                       JOIN multichannel.product p ON p.id=m.product_id
                       WHERE m.id IN %s""", (tuple(sl["master_sku_id"] for sl in sale_lines),))
        for row in cur.fetchall():
            line_map[row["master_sku_id"]] = row
    finance_lines = []
    for sl in sale_lines:
        info = line_map.get(sl["master_sku_id"], {"sku": sl["sku"], "name": sl["sku"]})
        finance_lines.append({
            "master_sku_id": sl["master_sku_id"],
            "sku": info["sku"],
            "name": info["name"],
            "quantity": int(sl["quantity"]),
            "unit_price": Decimal(str(sl["unit_price"])),
            "tax_amount": Decimal(str(sl.get("tax_amount", 0))),
        })
    biz = core.get_business(sale["business_id"])
    business_name = biz.get("name", f"Local Business {sale['business_id']}") if biz else f"Local Business {sale['business_id']}"
    return post_retail_sale_finance(
        sale_id=sale_id, business_id=sale["business_id"], business_name=business_name,
        invoice_date=str(sale["created_at"].date()), lines=finance_lines,
        total=Decimal(str(sale["total"])), tender_method=sale["tender_method"])

def post_restaurant_finance(
    *, order_id: int, business_id: int, business_name: str,
    invoice_date: str, lines: list[dict], total: Decimal,
) -> dict:
    """Post a restaurant order to Finance Core (revenue + COGS via inventory)."""
    _create_finance_table()
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT id FROM local_business.restaurant_finance WHERE order_id=%s", (order_id,))
        if cur.fetchone():
            c.rollback()
            return {"duplicate": True}
        c.commit()

    customer_id = _ensure_customer(business_id, business_name)
    invoice_number = f"LB-ORD-{order_id}"
    for ln in lines:
        _sync_inventory_item(ln["master_sku_id"], ln["sku"], ln.get("name", ln["sku"]))

    inv_lines = [{
        "source_system": SOURCE_SYSTEM,
        "external_product_id": f"sku-{ln['master_sku_id']}",
        "description": ln.get("name", ln["sku"]),
        "quantity": int(ln["quantity"]),
        "unit_price": str(Decimal(str(ln["unit_price"]))),
        "tax_amount": "0",
    } for ln in lines]

    try:
        inv = fc._request("POST", "/api/v1/inventory/sales-invoices", {
            "customer_code": f"LB-{business_id}",
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "due_date": (date.fromisoformat(invoice_date) + timedelta(days=14)).isoformat(),
            "currency": "IDR",
            "lines": inv_lines,
        })
        issued = fc._request("POST", f"/api/v1/inventory/sales-invoices/{inv['invoice_id']}/issue")
        journal_id = issued.get("journal_entry_id", "")
    except Exception as exc:
        _record_deferred_sale_finance(sale_id=sale_id, business_id=business_id,
                                       invoice_number=invoice_number, total=total,
                                       error=str(exc)[:500])
        raise

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.restaurant_finance
               (order_id, invoice_number, invoice_id, journal_id, customer_code, total, status)
               VALUES (%s,%s,%s,%s,%s,%s,'POSTED')
               ON CONFLICT (order_id) DO NOTHING""",
            (order_id, invoice_number, inv["invoice_id"], journal_id,
             f"LB-{business_id}", total))
        c.commit()
    core.catat_audit("restaurant_finance_posted", tenant_id="", business_id=business_id,
                     payload={"order_id": order_id, "invoice": invoice_number,
                              "journal": journal_id})
    return {"duplicate": False, "invoice_id": inv["invoice_id"], "journal_id": journal_id}


def post_goods_receipt_finance(
    *, receipt_id: int, business_id: int, supplier_code: str,
    supplier_name: str, invoice_date: str, lines: list[dict],
) -> dict:
    """Post a goods receipt to Finance Core via canonical inventory purchase invoice.

    DR Inventory / CR AP. Idempotent per receipt_id.
    """
    _create_finance_table()
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS local_business.receipt_finance (
                id BIGSERIAL PRIMARY KEY,
                receipt_id BIGINT NOT NULL REFERENCES local_business.goods_receipt(id),
                invoice_number TEXT NOT NULL,
                invoice_id TEXT NOT NULL,
                journal_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'POSTED',
                posted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_receipt_finance UNIQUE (receipt_id)
            )"""
        )
        cur.execute("SELECT id FROM local_business.receipt_finance WHERE receipt_id=%s", (receipt_id,))
        if cur.fetchone():
            c.rollback()
            return {"duplicate": True}
        c.commit()

    supplier_id = _ensure_supplier(supplier_code, supplier_name)
    invoice_number = f"LB-GR-{receipt_id}"
    for ln in lines:
        _sync_inventory_item(ln["master_sku_id"], ln["sku"], ln.get("name", ln["sku"]))

    inv_lines = [{
        "source_system": SOURCE_SYSTEM,
        "external_product_id": f"sku-{ln['master_sku_id']}",
        "description": ln.get("name", ln["sku"]),
        "quantity": int(ln["quantity"]),
        "unit_price": str(Decimal(str(ln["unit_cost"]))),
        "tax_amount": "0",
    } for ln in lines]

    inv = fc._request("POST", "/api/v1/inventory/purchase-invoices", {
        "supplier_code": supplier_code,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "due_date": (date.fromisoformat(invoice_date) + timedelta(days=14)).isoformat(),
        "currency": "IDR",
        "lines": inv_lines,
    })
    issued = fc._request("POST", f"/api/v1/inventory/purchase-invoices/{inv['invoice_id']}/issue")
    journal_id = issued.get("journal_entry_id", "")

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.receipt_finance
               (receipt_id, invoice_number, invoice_id, journal_id, status)
               VALUES (%s,%s,%s,%s,'POSTED')
               ON CONFLICT (receipt_id) DO NOTHING""",
            (receipt_id, invoice_number, inv["invoice_id"], journal_id))
        c.commit()
    core.catat_audit("goods_receipt_finance_posted", tenant_id="", business_id=business_id,
                     payload={"receipt_id": receipt_id, "invoice": invoice_number,
                              "journal": journal_id})
    return {"duplicate": False, "invoice_id": inv["invoice_id"], "journal_id": journal_id}


def post_vendor_bill_finance(
    *,
    bill_id: int,
    business_id: int,
    supplier_code: str,
    supplier_name: str,
    bill_number: str,
    bill_date: str,
    due_date: str,
    lines: list[dict],
) -> dict:
    """Post a Vendor Bill to Finance Core via canonical inventory purchase invoice.

    DR Persediaan Barang (1301) / CR Utang Usaha (2101).
    """
    supplier_id = _ensure_supplier(supplier_code, supplier_name)
    invoice_number = f"VB-{bill_number}"
    for ln in lines:
        if ln.get("master_sku_id"):
            _sync_inventory_item(ln["master_sku_id"], ln.get("sku", ""), ln.get("name", ln.get("sku", "")))

    inv_lines = [{
        "source_system": SOURCE_SYSTEM,
        "external_product_id": f"sku-{ln['master_sku_id']}" if ln.get("master_sku_id") else f"item-{bill_id}-{i}",
        "description": ln.get("description") or ln.get("name") or ln.get("sku", "Item"),
        "quantity": int(Decimal(str(ln["quantity"]))),
        "unit_price": str(Decimal(str(ln["unit_cost"]))),
        "tax_amount": str(Decimal(str(ln.get("tax_amount", 0)))),
    } for i, ln in enumerate(lines)]

    inv = fc._request("POST", "/api/v1/inventory/purchase-invoices", {
        "supplier_code": supplier_code,
        "invoice_number": invoice_number,
        "invoice_date": bill_date,
        "due_date": due_date,
        "currency": "IDR",
        "lines": inv_lines,
    })
    issued = fc._request("POST", f"/api/v1/inventory/purchase-invoices/{inv['invoice_id']}/issue")
    journal_id = issued.get("journal_entry_id", "")

    return {"duplicate": False, "invoice_id": inv["invoice_id"], "journal_id": journal_id}


def pay_vendor_bill_finance(
    *,
    finance_invoice_id: str,
    payment_number: str,
    amount: Decimal | float | int,
    payment_date: str,
    cash_account_id: str,
) -> dict:
    """Post an AP payment against an issued purchase invoice in Finance Core.

    DR Utang Usaha (2101) / CR Kas (1101) or Bank (1102).
    """
    res = fc._request("POST", f"/api/v1/ap/invoices/{finance_invoice_id}/payments", {
        "amount": str(Decimal(str(amount))),
        "payment_number": payment_number,
        "payment_date": payment_date,
        "cash_account_id": cash_account_id,
    })
    return res

