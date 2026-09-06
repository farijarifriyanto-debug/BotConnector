"""Smart Reorder Recommendation Engine V1 for BC Bisnis.

Design invariants:
- Read-only: Zero inventory mutation, zero purchase order mutation, zero Finance mutation.
- Authoritative inventory: `multichannel.inventory_balance.available`.
- Canonical sales demand: `local_business.sale` (status IN ('COMPLETED', 'RETURNED'), voided_at IS NULL)
  joined with `local_business.sale_line` minus `local_business.sale_return_line`.
- Deterministic formulas:
    average_daily_sales = net_units_sold / observed_days
    lead_time_demand = average_daily_sales * lead_time_days (if lead_time configured)
    reorder_point = ceil(lead_time_demand + safety_stock) (if lead_time configured)
    raw_order_qty = max(target_stock - available, 0)
    suggested_order_qty = max(raw_order_qty, min_order_qty) if raw_order_qty > 0 else 0
    days_to_depletion = available / average_daily_sales (if sales > 0)
- Truthful data tiers:
    If lead time is not configured, clearly states "Belum diatur" without fabricating numbers.
    If lead_time_days is missing and available > 0: priority = DATA_INCOMPLETE.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal

from ..persistence.db import koneksi as _pg
from . import low_stock


def set_sku_lead_time(
    *,
    business_id: int,
    master_sku_id: int,
    lead_time_days: int,
    supplier_name: str = "",
    min_order_qty: int = 1,
    target_stock: int | None = None,
    purchase_unit_cost: float | Decimal | None = None,
    cur=None,
) -> dict:
    """Configure supplier replenishment parameters for an SKU (normalized)."""
    from . import procurement as proc
    sname = (supplier_name or "").strip() or "Supplier Utama"
    scode = sname.upper().replace(" ", "-")[:16]
    supp = proc.get_supplier(business_id=business_id, code=scode, cur=cur)
    if not supp:
        supp = proc.create_supplier(business_id=business_id, code=scode, name=sname, cur=cur)
    return proc.set_supplier_sku(
        business_id=business_id,
        supplier_id=supp["id"],
        master_sku_id=master_sku_id,
        lead_time_days=lead_time_days,
        min_order_qty=min_order_qty,
        target_stock=target_stock,
        purchase_unit_cost=purchase_unit_cost,
        preferred=True,
        cur=cur,
    )


def get_sku_lead_time(
    *,
    business_id: int,
    master_sku_id: int,
    cur=None,
) -> dict | None:
    """Fetch active preferred supplier terms for an SKU."""
    from . import procurement as proc
    return proc.get_preferred_supplier_sku(business_id=business_id, master_sku_id=master_sku_id, cur=cur)


def calculate_reorder_for_sku(
    *,
    business_id: int,
    master_sku_id: int,
    lookback_days: int = 30,
    warehouse_id: int | None = None,
    cur=None,
) -> dict:
    """Calculate deterministic replenishment metrics for a single SKU."""
    observed_days = max(int(lookback_days), 1)

    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        # 1. Product & SKU metadata
        cur.execute(
            """SELECT m.id AS master_sku_id, m.sku, p.name AS product_name
               FROM multichannel.master_sku m
               JOIN multichannel.product p ON p.id=m.product_id
               WHERE m.id=%s""",
            (master_sku_id,),
        )
        prod = cur.fetchone()
        if not prod:
            raise KeyError(f"master_sku {master_sku_id} tidak ditemukan")
        sku = prod["sku"]
        product_name = prod["product_name"]

        # 2. Authoritative inventory available & safety stock
        if warehouse_id is not None:
            cur.execute(
                """SELECT COALESCE(on_hand, 0) AS on_hand,
                          COALESCE(reserved, 0) AS reserved,
                          COALESCE(safety_stock, 0) AS safety_stock,
                          COALESCE(available, 0) AS available
                   FROM multichannel.inventory_balance
                   WHERE master_sku_id=%s AND warehouse_id=%s""",
                (master_sku_id, warehouse_id),
            )
            bal = cur.fetchone()
        else:
            cur.execute(
                """SELECT COALESCE(SUM(ib.on_hand), 0) AS on_hand,
                          COALESCE(SUM(ib.reserved), 0) AS reserved,
                          COALESCE(SUM(ib.safety_stock), 0) AS safety_stock,
                          COALESCE(SUM(ib.available), 0) AS available
                   FROM multichannel.inventory_balance ib
                   JOIN local_business.branch b ON b.warehouse_id=ib.warehouse_id
                   WHERE ib.master_sku_id=%s AND b.business_id=%s""",
                (master_sku_id, business_id),
            )
            bal = cur.fetchone()

        on_hand = bal["on_hand"] if bal else 0
        reserved = bal["reserved"] if bal else 0
        safety_stock = bal["safety_stock"] if bal else 0
        available = bal["available"] if bal else 0

        # 3. Completed sales in lookback period (including partially/fully returned)
        cur.execute(
            """SELECT COALESCE(SUM(sl.quantity), 0) AS qty_sold
               FROM local_business.sale_line sl
               JOIN local_business.sale s ON s.id=sl.sale_id
               WHERE s.business_id=%s AND sl.master_sku_id=%s
                 AND s.status IN ('COMPLETED', 'RETURNED') AND s.voided_at IS NULL
                 AND s.created_at >= now() - make_interval(days => %s)""",
            (business_id, master_sku_id, observed_days),
        )
        sold_row = cur.fetchone()
        qty_sold = int(sold_row["qty_sold"]) if sold_row else 0

        # 4. Completed returns in lookback period
        cur.execute(
            """SELECT COALESCE(SUM(srl.quantity), 0) AS qty_returned
               FROM local_business.sale_return_line srl
               JOIN local_business.sale_return sr ON sr.id=srl.return_id
               JOIN local_business.sale s ON s.id=sr.sale_id
               WHERE s.business_id=%s AND srl.master_sku_id=%s
                 AND sr.status='COMPLETED'
                 AND sr.created_at >= now() - make_interval(days => %s)""",
            (business_id, master_sku_id, observed_days),
        )
        ret_row = cur.fetchone()
        qty_returned = int(ret_row["qty_returned"]) if ret_row else 0

        net_units_sold = max(qty_sold - qty_returned, 0)
        average_daily_sales = round(net_units_sold / observed_days, 2)

        # 5. Days to depletion
        if available <= 0:
            estimated_depletion_days = 0.0
        elif average_daily_sales > 0:
            estimated_depletion_days = round(available / average_daily_sales, 1)
        else:
            estimated_depletion_days = None

        # 6. Supplier terms & replenishment config
        from . import procurement as proc
        supp_cfg = proc.get_preferred_supplier_sku(business_id=business_id, master_sku_id=master_sku_id, cur=cur)

        if supp_cfg:
            supplier_id = supp_cfg["supplier_id"]
            supplier_code = supp_cfg["supplier_code"]
            supplier_name = supp_cfg["supplier_name"]
            lead_time_days = supp_cfg["lead_time_days"]
            min_order_qty = int(supp_cfg.get("min_order_qty") or 1)
            target_stock = supp_cfg.get("target_stock")
            purchase_unit_cost = supp_cfg.get("purchase_unit_cost")
            lead_time_demand = round(average_daily_sales * lead_time_days, 1)
            reorder_point = math.ceil(lead_time_demand + safety_stock)

            if target_stock is not None:
                raw_order_qty = max(target_stock - available, 0)
                if raw_order_qty > 0:
                    suggested_order_qty = max(raw_order_qty, min_order_qty)
                else:
                    suggested_order_qty = 0
            else:
                suggested_order_qty = None
        else:
            supplier_id = None
            supplier_code = None
            supplier_name = None
            lead_time_days = None
            min_order_qty = 1
            target_stock = None
            purchase_unit_cost = None
            lead_time_demand = None
            reorder_point = None
            suggested_order_qty = None

        # 7. Low-stock threshold
        threshold = low_stock.get_threshold(business_id=business_id, master_sku_id=master_sku_id, cur=cur)

        # 8. Deterministic priority classification
        if available <= 0:
            priority = "KRITIS"
            priority_rank = 1
        elif lead_time_days is not None and estimated_depletion_days is not None and estimated_depletion_days <= lead_time_days:
            priority = "TINGGI"
            priority_rank = 2
        elif reorder_point is not None and available <= reorder_point:
            priority = "SEDANG"
            priority_rank = 3
        elif threshold is not None and available <= threshold:
            priority = "SEDANG"
            priority_rank = 3
        elif lead_time_days is None and available > 0:
            priority = "DATA_INCOMPLETE"
            priority_rank = 5
        else:
            priority = "NORMAL"
            priority_rank = 4

        return {
            "master_sku_id": master_sku_id,
            "sku": sku,
            "product_name": product_name,
            "on_hand": on_hand,
            "reserved": reserved,
            "safety_stock": safety_stock,
            "available": available,
            "observed_days": observed_days,
            "qty_sold": qty_sold,
            "qty_returned": qty_returned,
            "net_units_sold": net_units_sold,
            "average_daily_sales": average_daily_sales,
            "estimated_depletion_days": estimated_depletion_days,
            "supplier_id": supplier_id,
            "supplier_code": supplier_code,
            "supplier_name": supplier_name,
            "lead_time_days": lead_time_days,
            "min_order_qty": min_order_qty,
            "target_stock": target_stock,
            "purchase_unit_cost": purchase_unit_cost,
            "lead_time_demand": lead_time_demand,
            "reorder_point": reorder_point,
            "suggested_order_qty": suggested_order_qty,
            "threshold": threshold,
            "priority": priority,
            "priority_rank": priority_rank,
        }
    finally:
        if own:
            c.close()


def calculate_reorder_recommendations(
    *,
    business_id: int,
    lookback_days: int = 30,
    limit: int = 20,
    cur=None,
) -> list[dict]:
    """Calculate and rank reorder recommendations for all products of a business."""
    own = cur is None
    if own:
        c = _pg()
        cur = c.cursor()
    try:
        cur.execute(
            """SELECT DISTINCT m.id AS master_sku_id
               FROM multichannel.master_sku m
               JOIN multichannel.inventory_balance ib ON ib.master_sku_id=m.id
               JOIN local_business.branch b ON b.warehouse_id=ib.warehouse_id
               WHERE b.business_id=%s
               ORDER BY m.id""",
            (business_id,),
        )
        sku_rows = cur.fetchall()
        results = []
        for r in sku_rows:
            rec = calculate_reorder_for_sku(
                business_id=business_id,
                master_sku_id=r["master_sku_id"],
                lookback_days=lookback_days,
                cur=cur,
            )
            results.append(rec)

        def sort_key(item):
            depl = item["estimated_depletion_days"]
            depl_val = 999999.0 if depl is None else depl
            return (item["priority_rank"], depl_val, item["sku"])

        results.sort(key=sort_key)
        return results[:limit]
    finally:
        if own:
            c.close()


def render_reorder_item(item: dict) -> list[str]:
    """Render structured text lines for one recommendation item."""
    name = item["product_name"] or item["sku"]
    sku = item["sku"]
    avail = item["available"]
    ads = item["average_daily_sales"]
    obs = item["observed_days"]
    depl = item["estimated_depletion_days"]
    lt = item["lead_time_days"]
    rop = item["reorder_point"]
    prio = item["priority"]

    lines = [
        f"• {name}",
        f"  SKU: {sku}",
        f"  Stok tersedia: {avail}",
        f"  Penjualan rata-rata: {ads:g}/hari ({obs} hari)",
    ]

    if depl is not None:
        lines.append(f"  Estimasi habis: {depl:g} hari")
    else:
        lines.append("  Estimasi habis: Tidak ada penjualan")

    if lt is not None:
        lines.append(f"  Lead time: {lt} hari")
        if rop is not None:
            lines.append(f"  Reorder point: {rop}")
    else:
        lines.append("  Lead time: Belum diatur")
        lines.append("  Saran: Lengkapi data supplier")

    if item.get("suggested_order_qty") is not None:
        lines.append(f"  Saran order: {item['suggested_order_qty']}")

    lines.append(f"  Prioritas: {prio}")
    return lines


def render_reorder_message(items: list[dict], single_sku: bool = False) -> str:
    """Render complete Indonesian Telegram message for /reorder."""
    if not items:
        return "✅ Semua stok produk dalam kondisi aman."

    lines = ["📦 REKOMENDASI RESTOCK", ""]
    for idx, it in enumerate(items):
        lines.extend(render_reorder_item(it))
        if idx < len(items) - 1:
            lines.append("")
    return "\n".join(lines).strip()
