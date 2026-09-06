"""Barcode support.

Standard keyboard-wedge barcode scanners work immediately. barcode -> master
SKU, multiple barcode aliases, unknown barcode handling, internal barcode/
label generation, stock opname + receiving barcode workflows. No paid
external barcode API required.
"""

from __future__ import annotations

import hashlib

from ..persistence.db import koneksi as _pg


def add_barcode_alias(*, business_id: int, master_sku_id: int, barcode: str) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.barcode_alias (business_id, master_sku_id, barcode)
               VALUES (%s,%s,%s)
               ON CONFLICT (business_id, barcode) DO UPDATE SET master_sku_id=EXCLUDED.master_sku_id
               RETURNING id, master_sku_id, barcode""",
            (business_id, master_sku_id, barcode))
        r = cur.fetchone()
        c.commit()
        return r


def lookup_barcode(*, business_id: int, barcode: str) -> dict:
    """Lookup a barcode -> master SKU. Checks aliases then master_sku.barcode."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT m.id, m.sku, m.barcode, p.name
               FROM local_business.barcode_alias ba
               JOIN multichannel.master_sku m ON m.id=ba.master_sku_id
               JOIN multichannel.product p ON p.id=m.product_id
               WHERE ba.business_id=%s AND ba.barcode=%s""",
            (business_id, barcode))
        r = cur.fetchone()
        if r:
            return {"found": True, "master_sku_id": r["id"], "sku": r["sku"],
                    "barcode": r["barcode"], "name": r["name"], "via": "alias"}
        cur.execute(
            """SELECT m.id, m.sku, m.barcode, p.name
               FROM multichannel.master_sku m
               JOIN multichannel.product p ON p.id=m.product_id
               WHERE m.barcode=%s""", (barcode,))
        r = cur.fetchone()
        if r:
            return {"found": True, "master_sku_id": r["id"], "sku": r["sku"],
                    "barcode": r["barcode"], "name": r["name"], "via": "master_sku"}
        return {"found": False, "barcode": barcode, "reason": "unknown_barcode"}


def generate_internal_barcode(*, business_id: int, master_sku_id: int, sku: str) -> str:
    """Generate an internal barcode for a SKU label (deterministic)."""
    raw = f"BC-{business_id}-{master_sku_id}-{sku}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12].upper()
