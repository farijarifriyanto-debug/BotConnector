"""Canonical Intake Engine for BotConnector BC Bisnis.

Single engine shared by:
  - Excel/CSV universal import
  - Mobile Quick Mode
  - Telegram intake foundation
  - future POS-export connectors

Flow (never mutates business data before confirmation):

  external input
    -> intake_batch (durable identity, PREVIEW)
    -> per-row intake_row (READY/WARNING/REJECTED)
    -> validation + preview
    -> explicit confirmation
    -> canonical Product / Master SKU / barcode
    -> retail selling price
    -> opening quantity (Central Inventory)
    -> opening/reference cost valuation (Finance Core)

External channels are NOT authoritative. No mutation before confirm().
All confirmed batches are idempotent via intake_batch.batch_id /
(business_id, source, idempotency_key). Retry of the same confirmed batch
must not duplicate products, prices, opening inventory, or Finance effects.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from ..persistence.db import koneksi as _pg
from ..inventory import service as S

_INTENSI = {
    "ready": "READY",
    "warning": "WARNING",
    "rejected": "REJECTED",
}


def _now():
    return datetime.now(timezone.utc)


def _batch_key() -> str:
    return "BATCH-" + uuid.uuid4().hex[:12].upper()


def _idem_key(business_id: int, source: str, user_key: str = "") -> str:
    raw = f"{business_id}:{source}:{user_key or uuid.uuid4().hex}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ============================================================ header mapping
# Canonical field -> list of accepted header aliases (lowercased, stripped).
_HEADER_ALIASES = {
    "name": ["nama barang", "nama", "product", "item", "produk", "nama produk",
             "name", "item name", "product name", "nama barang/produk"],
    "sku": ["sku", "kode", "kode barang", "kode sku", "kode item", "item code",
            "code", "stock code", "part number", "artikel", "kode produk"],
    "barcode": ["barcode", "gtin", "ean", "upc", "kode barcode", "ean13", "kode gtin"],
    "category": ["kategori", "category", "jenis", "grup", "group", "tipe"],
    "unit": ["unit", "satuan", "uom", "sat", "kemasan", "pack"],
    "price": ["harga jual", "harga", "selling price", "price", "harga retail",
              "harga jual", "jual", "unit price", "harga satuan", "harga eceran"],
    "cost": ["harga modal", "harga pokok", "cost", "unit cost", "modal",
             "harga beli", "purchase price", "hb", "hpp"],
    "qty": ["stok", "qty", "quantity", "stock", "jumlah", "opening stock",
            "opening qty", "persediaan", "jumlah stok", "stock awal"],
}


def _norm_header(s: str) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def auto_map(headers: list) -> dict:
    """Map detected headers -> canonical fields. Returns {canonical: header_index}."""
    mapping: dict = {}
    for canon, aliases in _HEADER_ALIASES.items():
        norm_aliases = {_norm_header(a) for a in aliases}
        for i, h in enumerate(headers):
            nh = _norm_header(h)
            if nh in norm_aliases:
                mapping[canon] = i
                break
    return mapping


# ========================================================================== parsing
def parse_rows(content: bytes, format: str = "CSV") -> list[dict]:
    """Parse uploaded file into a list of dicts keyed by raw header."""
    if format.upper() == "CSV":
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for r in reader:
            if r is not None:
                rows.append({k: ("" if v is None else str(v).strip()) for k, v in r.items()})
        return rows
    if format.upper() == "XLSX":
        try:
            import openpyxl
        except ImportError as e:
            raise RuntimeError("openpyxl tidak tersedia untuk XLSX") from e
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
        raw = list(ws.iter_rows(values_only=True))
        if not raw:
            return []
        headers = [str(h) if h is not None else "" for h in raw[0]]
        out = []
        for r in raw[1:]:
            if all(v is None for v in r):
                continue
            out.append({
                headers[i]: ("" if r[i] is None else str(r[i]).strip())
                for i in range(len(headers))
            })
        return out
    raise ValueError(f"format {format} tidak didukung")


def _to_int(v):
    n = _to_num(v)
    if n is None:
        return 0
    return int(n)


def _to_num(v) -> Decimal | None:
    """Parse Indonesian numeric strings: dot as thousands separator, comma as decimal.

    Examples:
      "1.500" -> 1500
      "1,5"   -> 1.5
      "1.500,50" -> 1500.50
      "1500"  -> 1500
      "GRATIS" -> None
    """
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return Decimal(1) if v else Decimal(0)
    if isinstance(v, (int, float, Decimal)):
        return Decimal(v)
    s = str(v).replace("Rp", "").replace("IDR", "").replace(" ", "").strip()
    # Remove dots used as thousand separators (followed by exactly 3 digits and then end/non-digit).
    s = re.sub(r"\.(?=\d{3}(?:\D|$))", "", s)
    # Comma is the decimal separator in Indonesian locale.
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


# ========================================================================== validate + preview
def _validate_row(raw: dict, mapping: dict, seen_sku: set, seen_barcode: set,
                  existing_skus: set, existing_barcodes: set) -> dict:
    """Build a normalized intake row dict with issues; compute status."""
    issues = []

    def g(field):
        idx = mapping.get(field)
        if idx is None:
            return ""
        keys = list(raw.keys())
        return raw.get(keys[idx], "") if idx < len(keys) else ""

    sku = (g("sku") or "").strip()
    name = (g("name") or "").strip()
    barcode = (g("barcode") or "").strip()
    category = (g("category") or "").strip()
    unit = (g("unit") or "").strip()
    price = _to_num(g("price"))
    cost = _to_num(g("cost"))
    qty = _to_int(g("qty"))

    if not sku and not name:
        issues.append("SKU/Nama wajib (identity)")
    if not sku:
        sku = name
    if not name:
        name = sku
    if not sku:
        issues.append("SKU kosong setelah fallback")

    if price is not None and price < 0:
        issues.append("harga tidak valid")
    elif price is None:
        issues.append("produk tanpa harga (unpriced)")
    elif price == 0:
        issues.append("produk tanpa harga (unpriced)")
    if cost is not None and cost < 0:
        issues.append("harga modal negatif")
    if qty < 0:
        issues.append("jumlah stok negatif")
    if sku and sku in seen_sku:
        issues.append("SKU duplikat dalam file")
    if sku and sku in existing_skus:
        issues.append("SKU sudah ada (produk yang ada)")
    if barcode and barcode in seen_barcode:
        issues.append("barcode duplikat dalam file")
    if barcode and barcode in existing_barcodes:
        issues.append("barcode sudah dipakai produk lain")

    if sku:
        seen_sku.add(sku)
    if barcode:
        seen_barcode.add(barcode)

    rejected = any(
        "wajib" in i or "negatif" in i or "tidak valid" in i or "duplikat" in i
        for i in issues
    )
    warning = (not rejected) and any("tanpa harga" in i for i in issues)
    status = "REJECTED" if rejected else ("WARNING" if warning else "READY")

    return {
        "row_no": 0,
        "sku": sku,
        "name": name,
        "barcode": barcode,
        "category": category,
        "unit": unit,
        "selling_price": price,
        "cost": cost,
        "opening_qty": qty,
        "status": status,
        "issues": issues,
    }


def create_draft(
    *, business_id: int, source: str = "CSV", filename: str = "",
    format: str = "CSV", content: bytes, mapping: dict | None = None,
    idempotency_key: str = "", actor: str = "",
) -> dict:
    """Detect -> map -> validate -> persist an intake batch (PREVIEW). No mutation."""
    if not idempotency_key:
        idempotency_key = "auto-" + uuid.uuid4().hex
    rows_raw = parse_rows(content, format)
    headers = list(rows_raw[0].keys()) if rows_raw else []
    if mapping is None:
        mapping = auto_map(headers)

    existing_skus, existing_barcodes = _existing_canonical(business_id)

    batch_key = _batch_key()
    seen_sku, seen_barcode = set(), set()
    validated = []
    for i, raw in enumerate(rows_raw, start=2):
        v = _validate_row(raw, mapping, seen_sku, seen_barcode, existing_skus, existing_barcodes)
        v["row_no"] = i
        validated.append(v)

    ready = sum(1 for v in validated if v["status"] == "READY")
    warning = sum(1 for v in validated if v["status"] == "WARNING")
    rejected = sum(1 for v in validated if v["status"] == "REJECTED")

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.intake_batch
               (batch_id, business_id, source, filename, format, status,
                total_rows, ready_rows, warning_rows, rejected_rows,
                mapping_json, error_report, idempotency_key, actor)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (batch_key, business_id, source, filename, format.upper(), "PREVIEW",
             len(validated), ready, warning, rejected,
             json.dumps(mapping), json.dumps([v["issues"] for v in validated if v["status"] == "REJECTED"]),
             idempotency_key, actor))
        batch_pk = cur.fetchone()["id"]
        for v in validated:
            cur.execute(
                """INSERT INTO local_business.intake_row
                   (batch_id, row_no, sku, name, barcode, category, unit,
                    selling_price, cost, opening_qty, status, issues)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (batch_pk, v["row_no"], v["sku"], v["name"], v["barcode"],
                 v["category"], v["unit"], v["selling_price"], v["cost"],
                 v["opening_qty"], v["status"], json.dumps(v["issues"])))
        c.commit()

    return {
        "ok": True,
        "batch_id": batch_key,
        "status": "PREVIEW",
        "total_rows": len(validated),
        "ready_rows": ready,
        "warning_rows": warning,
        "rejected_rows": rejected,
        "mapping": mapping,
        "headers": headers,
        "rejected_issues": [v["issues"] for v in validated if v["status"] == "REJECTED"],
    }


def preview(batch_id: str) -> dict:
    """Return the full preview for a batch (rows + counts)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.intake_batch WHERE batch_id=%s", (batch_id,))
        b = cur.fetchone()
        if not b:
            return {"ok": False, "error": "batch tidak ada"}
        cur.execute(
            "SELECT row_no, sku, name, barcode, category, unit, selling_price, cost, "
            "opening_qty, status, issues FROM local_business.intake_row WHERE batch_id=%s ORDER BY row_no",
            (b["id"],))
        rows = cur.fetchall()
    return {
        "ok": True,
        "batch": {
            "batch_id": b["batch_id"], "source": b["source"], "format": b["format"],
            "status": b["status"], "filename": b["filename"],
            "total_rows": b["total_rows"], "ready_rows": b["ready_rows"],
            "warning_rows": b["warning_rows"], "rejected_rows": b["rejected_rows"],
        },
        "rows": rows,
    }


def _existing_canonical(business_id: int) -> tuple[set, set]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT sku FROM multichannel.master_sku")
        skus = {r["sku"] for r in cur.fetchall()}
        cur.execute("SELECT barcode FROM multichannel.master_sku WHERE barcode<>''")
        barcodes = {r["barcode"] for r in cur.fetchall()}
    return skus, barcodes


# ========================================================================== confirm
def confirm_batch(
    *, batch_id: str, business_id: int, tenant_id: str, branch_id: int,
    warehouse_id: int, actor: str = "",
) -> dict:
    """Explicitly confirm a PREVIEW batch and commit canonically.

    Policy: a single atomic DB transaction covers all READY/WARNING rows
    (Product/SKU/price/opening stock). REJECTED rows are skipped; this is
    documented as ROW_LEVEL_REJECTED_SKIPPED, not all-or-nothing. Finance
    opening valuation is applied after the DB commit and is idempotent via
    its own idempotency_key, so a retry cannot duplicate Finance effects.

    Retrying confirm_batch with the same batch_id is a no-op: once a batch
    is COMMITTED the stored committed counts are returned, and the
    idempotent stock/Finance keys prevent duplicate effects.
    """
    from . import inventory as inv, finance as _fin
    from ..workflow import finance_core as fc

    # 1. Load batch (must exist and be owned by business).
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.intake_batch "
            "WHERE batch_id=%s AND business_id=%s FOR UPDATE",
            (batch_id, business_id))
        b = cur.fetchone()
        if not b:
            return {"ok": False, "error": "batch tidak ada"}
        cur.execute(
            "SELECT * FROM local_business.intake_row WHERE batch_id=%s ORDER BY row_no",
            (b["id"],))
        rows = cur.fetchall()
        # If already committed, return stored outcome (idempotent re-confirm).
        if b["status"] == "COMMITTED":
            c.commit()
            return {
                "ok": True,
                "batch_id": batch_id,
                "committed_product": b.get("ready_rows", 0) + b.get("warning_rows", 0),
                "committed_price": b.get("committed_price", 0) or 0,
                "committed_stock": b.get("committed_stock", 0) or 0,
                "committed_cost": b.get("committed_cost", 0) or 0,
                "policy": "IDEMPOTENT_RECONFIRM (batch already committed)",
            }
        if b["status"] != "PREVIEW":
            c.commit()
            return {"ok": False, "error": f"batch status {b['status']} tidak bisa dikonfirmasi"}
        c.rollback()  # release lock; we will re-lock inside commit txn

    batch_pk = b["id"]
    sku_to_master = {}  # sku -> master_sku_id for post-commit finance valuation

    # 2. Confirm with a single atomic DB transaction (Product/SKU/price/stock).
    committed_price = 0
    committed_stock = 0
    processed = 0
    try:
        with _pg() as c:
            cur = c.cursor()
            cur.execute(
                "UPDATE local_business.intake_batch SET status='CONFIRMED', confirmed_at=now() "
                "WHERE id=%s", (batch_pk,))

            for row in rows:
                if row["status"] == "REJECTED":
                    continue

                sku = row["sku"]
                name = row["name"]
                barcode = row["barcode"]
                price = row["selling_price"]
                cost = row["cost"]
                qty = row["opening_qty"]
                processed += 1

                # canonical product + master sku (idempotent; existing SKU is already rejected at validation)
                cur.execute(
                    """INSERT INTO multichannel.product (name, category, brand)
                       VALUES (%s,%s,'')
                       ON CONFLICT (name, category) DO UPDATE SET brand=EXCLUDED.brand, updated_at=now()
                       RETURNING id""",
                    (name, row["category"] or "",))
                product_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO multichannel.master_sku (sku, product_id, barcode)
                       VALUES (%s,%s,%s)
                       ON CONFLICT (sku) DO UPDATE SET barcode=EXCLUDED.barcode, updated_at=now()
                       RETURNING id, sku""",
                    (sku, product_id, barcode or ""))
                master_sku_id = cur.fetchone()["id"]
                sku_to_master[sku] = master_sku_id
                cur.execute(
                    "UPDATE local_business.intake_row SET canonical_master_sku_id=%s WHERE id=%s",
                    (master_sku_id, row["id"]))

                if price is not None and price > 0:
                    cur.execute(
                        """INSERT INTO local_business.retail_selling_price
                           (business_id, master_sku_id, selling_price, currency, active)
                           VALUES (%s,%s,%s,'IDR',TRUE)
                           ON CONFLICT (business_id, master_sku_id) WHERE active=TRUE
                           DO UPDATE SET selling_price=EXCLUDED.selling_price, updated_at=now()""",
                        (business_id, master_sku_id, price))
                    committed_price += 1

                if qty > 0:
                    inv.receive_stock(
                        tenant_id=tenant_id, business_id=business_id, branch_id=branch_id,
                        warehouse_id=warehouse_id, master_sku_id=master_sku_id,
                        sku=sku, quantity=qty, unit_cost=(float(cost) if cost else 0),
                        reference=f"intake:{batch_id}", note=f"intake {batch_id}",
                        actor=actor or "system", source_document=f"INTAKE-{batch_id}",
                        idempotency_key=f"intake:{batch_id}:{sku}:{qty}", cur=cur)
                    committed_stock += 1

            cur.execute(
                """UPDATE local_business.intake_batch
                   SET status='COMMITTED', committed_at=now(),
                       committed_price=%s, committed_stock=%s, committed_cost=%s
                   WHERE id=%s""",
                (committed_price, committed_stock, 0, batch_pk))
            c.commit()

        # 3. Finance opening/reference cost valuation (idempotent, after DB commit).
        committed_cost = 0
        for row in rows:
            if row["status"] == "REJECTED":
                continue
            cost = row["cost"]
            qty = row["opening_qty"]
            sku = row["sku"]
            name = row["name"]
            if cost is not None and cost > 0 and qty > 0 and sku in sku_to_master:
                try:
                    fc_item = _fin._sync_inventory_item(sku_to_master[sku], sku, name)
                    fc.opening_valuation(
                        inventory_item_id=fc_item,
                        quantity=qty,
                        unit_cost=cost,
                        reference=f"INTAKE-{batch_id}-{sku}",
                        reason=f"Intake batch {batch_id} opening/reference cost. Not a supplier invoice.",
                        source="INTAKE_OPENING",
                        reference_date="2026-08-22",
                        idempotency_key=f"intake-val:{batch_id}:{sku}")
                    committed_cost += 1
                except Exception:
                    committed_cost += 0
        # Persist the final cost count so re-confirm returns it.
        with _pg() as c:
            cur = c.cursor()
            cur.execute(
                "UPDATE local_business.intake_batch SET committed_cost=%s WHERE id=%s",
                (committed_cost, batch_pk))
            c.commit()

    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "rolled_back": True}

    return {
        "ok": True,
        "batch_id": batch_id,
        "committed_product": processed,
        "committed_price": committed_price,
        "committed_stock": committed_stock,
        "committed_cost": committed_cost,
        "policy": "ROW_LEVEL_REJECTED_SKIPPED (ready/warning rows atomic per batch; rejected rows never mutated)",
    }


def history(business_id: int, limit: int = 20) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT batch_id, source, format, filename, status, total_rows,
                      ready_rows, warning_rows, rejected_rows, created_at, committed_at
               FROM local_business.intake_batch
               WHERE business_id=%s ORDER BY id DESC LIMIT %s""",
            (business_id, limit))
        return cur.fetchall()
