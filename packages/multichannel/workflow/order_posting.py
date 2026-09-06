"""Alur posting pesanan ternormalisasi ke Finance Core (jalur kanonik).

Idempoten: setiap pesanan hanya diposting sekali. Duplikat ulang
dikembalikan sebagai sudah ada.

Jalur kanonik (handoff):
  pesanan lunas -> Sales Invoice -> issue -> finance_issue_sales_invoice
                  -> finance_post_journal -> POSTED
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from ..persistence import db, repo
from ..workflow import finance_core as fc


_STATUS_TOK = {
    "UNPAID": "baru",
    "READY_TO_SHIP": "dibayar",
    "PROCESSED": "diproses",
    "SHIPPED": "dikirim",
    "COMPLETED": "selesai",
    "CANCELLED": "dibatalkan",
    "IN_CANCEL": "dibatalkan",
    "TO_RETURN": "dikembalikan",
}


def normalisasi_status(s: str) -> str:
    return _STATUS_TOK.get(s, "tidak_dikenal")


def total_pesanan(mentah: dict) -> Decimal:
    """Total pesanan dari payload ternormalisasi."""
    resp = mentah.get("response", mentah)
    total = resp.get("total_amount")
    if total is not None:
        return Decimal(str(total))
    jumlah = Decimal("0")
    for it in resp.get("item_list", []):
        for itm in it.get("item_list", []):
            jumlah += Decimal(str(itm.get("item_price", 0))) * \
                int(itm.get("item_sku", 0))
    return jumlah


def _create_finance_table() -> None:
    db.jalankan(
        """CREATE TABLE IF NOT EXISTS multichannel.order_finance (
            id            BIGSERIAL PRIMARY KEY,
            provider      TEXT NOT NULL,
            shop_id       TEXT NOT NULL,
            order_sn      TEXT NOT NULL,
            invoice_number TEXT NOT NULL,
            invoice_id    TEXT NOT NULL,
            journal_id    TEXT NOT NULL,
            customer_code TEXT NOT NULL,
            total         NUMERIC(20,2) NOT NULL,
            status        TEXT NOT NULL DEFAULT 'POSTED',
            posted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_order_finance UNIQUE (provider, shop_id, order_sn)
        )"""
    )


def sudah_diposting(provider: str, shop_id: str, order_sn: str) -> dict | None:
    return db.ambil(
        "SELECT * FROM multichannel.order_finance "
        "WHERE provider=%s AND shop_id=%s AND order_sn=%s",
        (provider, shop_id, order_sn),
    )


def post_invoice_order(
    *,
    tenant_id: str,
    provider: str,
    shop_id: str,
    order_sn: str,
    order_date: str,
    total: Decimal,
    line_desc: str = "",
    invoice_number: str = "",
) -> dict:
    """Posting satu pesanan lunas -> Sales Invoice -> POSTED (idempoten)."""
    _create_finance_table()

    ada = sudah_diposting(provider, shop_id, order_sn)
    if ada:
        ada["duplicate"] = True
        return ada

    # satu customer per marketplace (keputusan handoff)
    cust_code = f"MKT-{provider.upper()}"
    customer_id = fc.pastikan_customer(
        code=cust_code, name=f"Marketplace {provider.title()}")

    if not invoice_number:
        invoice_number = f"SP-{provider[:3]}-{order_sn}"[:24]

    # Idempoten di tingkat Finance: invoice sudah ada -> kembalikan sebagai
    # duplikat (proteksi replay lintas-proses).
    existing = fc.cari_invoice(invoice_number)
    if existing:
        db.jalankan(
            """INSERT INTO multichannel.order_finance
               (provider, shop_id, order_sn, invoice_number, invoice_id,
                journal_id, customer_code, total, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (provider, shop_id, order_sn) DO NOTHING""",
            (provider, shop_id, order_sn, invoice_number,
             existing["id"], existing.get("journal_entry_id") or "",
             cust_code, total, "POSTED"),
        )
        row = sudah_diposting(provider, shop_id, order_sn)
        row["duplicate"] = True
        row["invoice_id"] = existing["id"]
        row["journal_id"] = existing.get("journal_entry_id") or ""
        return row

    inv_date = order_date
    due_date = (date.fromisoformat(order_date) + timedelta(days=14)).isoformat()

    inv = fc.buat_sales_invoice(
        customer_id=customer_id,
        invoice_number=invoice_number,
        invoice_date=inv_date,
        due_date=due_date,
        lines=[{
            "description": line_desc or f"Pesanan {provider} {order_sn}",
            "quantity": 1,
            "unit_price": str(total),
            "tax_amount": "0",
        }],
        source_system="multichannel",
        source_id=f"{provider}:{shop_id}:{order_sn}",
    )

    hasil = fc.issue_sales_invoice(inv["id"])

    db.jalankan(
        """INSERT INTO multichannel.order_finance
           (provider, shop_id, order_sn, invoice_number, invoice_id,
            journal_id, customer_code, total, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (provider, shop_id, order_sn) DO NOTHING""",
        (provider, shop_id, order_sn, invoice_number,
         inv["id"], hasil["journal_entry_id"], cust_code, total, "POSTED"),
    )

    repo.catat_audit("pesanan_diposting", tenant_id=tenant_id,
                     provider=provider, shop_id=shop_id,
                     payload={"order_sn": order_sn,
                              "invoice": invoice_number,
                              "journal": hasil["journal_entry_id"]})

    row = sudah_diposting(provider, shop_id, order_sn)
    row["duplicate"] = False
    row["invoice_id"] = inv["id"]
    row["journal_id"] = hasil["journal_entry_id"]
    return row
