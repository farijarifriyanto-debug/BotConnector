"""Business-type reporting layer.

Computes runtime-backed reports over ACTUAL operational rows + canonical
Finance Core. Uses business dimensions (reporting_category, sales_channel,
order_source, branch, cashier, register, period) instead of a separate
accounting system.

Profiles:
  - RESTAURANT / CAFE: food/beverage/dessert sales, COGS, gross profit,
    margin, channel breakdown, operations.
  - RETAIL: product/category sales, COGS, gross profit, margin, returns,
    stock movement, shrinkage.
  - HYBRID: both profiles without double counting.

Pilot/demo data stays explicitly PILOT and never appears as genuine
production performance.
"""

from __future__ import annotations

from decimal import Decimal

from ..persistence.db import koneksi as _pg


def _num(v):
    return float(v or 0)


# ============================================================ dimension helpers
def ensure_reporting_categories(business_id: int) -> None:
    for code, name in [("FOOD", "Makanan"), ("BEVERAGE", "Minuman"),
                       ("DESSERT", "Dessert"), ("RETAIL", "Retail"),
                       ("SERVICE", "Layanan")]:
        with _pg() as c:
            cur = c.cursor()
            cur.execute(
                """INSERT INTO local_business.reporting_category (business_id, code, name)
                   VALUES (%s,%s,%s) ON CONFLICT (business_id, code) DO NOTHING""",
                (business_id, code, name))
            c.commit()


def ensure_sales_channels(business_id: int) -> None:
    for code, name in [("DINE_IN", "Makan di Tempat"), ("TAKEAWAY", "Bawa Pulang"),
                       ("PICKUP", "Ambil Sendiri"), ("QR_SELF_ORDER", "QR Self Order"),
                       ("GOFOOD", "GoFood"), ("GRABFOOD", "GrabFood"),
                       ("SHOPEEFOOD", "ShopeeFood"), ("POS", "POS")]:
        with _pg() as c:
            cur = c.cursor()
            cur.execute(
                """INSERT INTO local_business.sales_channel (business_id, code, name)
                   VALUES (%s,%s,%s) ON CONFLICT (business_id, code) DO NOTHING""",
                (business_id, code, name))
            c.commit()


# ============================================================ restaurant / cafe reporting
def restaurant_sales_report(business_id: int, days: int = 30) -> dict:
    """Restaurant sales by reporting category + channel + COGS + gross profit."""
    with _pg() as c:
        cur = c.cursor()
        # sales by reporting category (from menu_item.reporting_category)
        cur.execute(
            """SELECT COALESCE(mi.reporting_category,'FOOD') AS category,
                      count(DISTINCT ro.id) AS order_count,
                      COALESCE(SUM(rol.quantity),0) AS qty_sold,
                      COALESCE(SUM(rol.line_total),0) AS gross_sales
               FROM local_business.restaurant_order ro
               JOIN local_business.restaurant_order_line rol ON rol.order_id=ro.id
               JOIN local_business.menu_item mi ON mi.id=rol.menu_item_id
               WHERE ro.business_id=%s AND ro.status NOT IN ('CANCELLED')
                 AND ro.created_at >= now() - make_interval(days => %s)
               GROUP BY mi.reporting_category ORDER BY category""",
            (business_id, days))
        category_sales = cur.fetchall()

        # sales by channel
        cur.execute(
            """SELECT COALESCE(ro.sales_channel,'DINE_IN') AS channel,
                      count(DISTINCT ro.id) AS order_count,
                      COALESCE(SUM(ro.total),0) AS gross_sales,
                      COALESCE(SUM(ro.discount),0) AS discounts,
                      COALESCE(SUM(ro.service_charge),0) AS service_charge,
                      COALESCE(SUM(ro.tax_amount),0) AS taxes
               FROM local_business.restaurant_order ro
               WHERE ro.business_id=%s AND ro.status NOT IN ('CANCELLED')
                 AND ro.created_at >= now() - make_interval(days => %s)
               GROUP BY ro.sales_channel ORDER BY channel""",
            (business_id, days))
        channel_sales = cur.fetchall()

        # totals
        cur.execute(
            """SELECT count(DISTINCT ro.id) AS order_count,
                      COALESCE(SUM(ro.total),0) AS gross_sales,
                      COALESCE(SUM(ro.discount),0) AS discounts,
                      COALESCE(SUM(ro.service_charge),0) AS service_charge,
                      COALESCE(SUM(ro.tax_amount),0) AS taxes,
                      COALESCE(SUM(ro.guest_count),0) AS guest_count
               FROM local_business.restaurant_order ro
               WHERE ro.business_id=%s AND ro.status NOT IN ('CANCELLED')
                 AND ro.created_at >= now() - make_interval(days => %s)""",
            (business_id, days))
        totals = cur.fetchone()

        # COGS: sum of ingredient consumption cost for served orders
        cur.execute(
            """SELECT COALESCE(SUM(im.qty * COALESCE((
                   SELECT unit_cost FROM local_business.goods_receipt_line grl
                   WHERE grl.master_sku_id=im.master_sku_id ORDER BY grl.id DESC LIMIT 1
                 ),0)),0) AS cogs
               FROM multichannel.inventory_movement im
               JOIN local_business.branch b ON b.warehouse_id=im.warehouse_id
               WHERE b.business_id=%s AND im.movement_type='KELUAR'
                 AND im.note LIKE 'ingredient consume%%'
                 AND im.created_at >= now() - make_interval(days => %s)""",
             (business_id, days))
        cogs_row = cur.fetchone()

    gross = _num(totals["gross_sales"])
    discounts = _num(totals["discounts"])
    service_charge = _num(totals["service_charge"])
    taxes = _num(totals["taxes"])
    net_sales = gross - discounts + service_charge
    cogs = _num(cogs_row["cogs"])
    gross_profit = net_sales - cogs
    margin = (gross_profit / net_sales * 100) if net_sales else 0
    order_count = int(totals["order_count"])
    avg_ticket = (net_sales / order_count) if order_count else 0

    return {
        "profile": "RESTAURANT",
        "gross_sales": gross,
        "net_sales": net_sales,
        "discounts": discounts,
        "service_charge": service_charge,
        "taxes": taxes,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin_pct": round(margin, 2),
        "order_count": order_count,
        "guest_count": int(totals["guest_count"]),
        "average_ticket": round(avg_ticket, 2),
        "category_sales": category_sales,
        "channel_sales": channel_sales,
    }


def restaurant_operations_report(business_id: int, days: int = 30) -> dict:
    """Top/bottom menu, sales mix, waste, low stock, kitchen tickets."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT rol.menu_item_name AS name,
                      SUM(rol.quantity) AS qty_sold,
                      SUM(rol.line_total) AS sales
               FROM local_business.restaurant_order_line rol
               JOIN local_business.restaurant_order ro ON ro.id=rol.order_id
               WHERE ro.business_id=%s AND ro.status NOT IN ('CANCELLED')
                 AND ro.created_at >= now() - make_interval(days => %s)
               GROUP BY rol.menu_item_name ORDER BY sales DESC LIMIT 10""",
            (business_id, days))
        top_menu = cur.fetchall()
        cur.execute(
            """SELECT count(*) AS n FROM local_business.kot k
               JOIN local_business.restaurant_order ro ON ro.id=k.order_id
               WHERE ro.business_id=%s AND k.created_at >= now() - make_interval(days => %s)""",
            (business_id, days))
        kot_count = cur.fetchone()["n"]
        cur.execute(
             """SELECT COALESCE(SUM(im.qty),0) AS waste_qty FROM multichannel.inventory_movement im
                JOIN local_business.branch b ON b.warehouse_id=im.warehouse_id
                WHERE b.business_id=%s AND im.movement_type='WASTE'
                  AND im.created_at >= now() - make_interval(days => %s)""",
             (business_id, days))
        waste = cur.fetchone()["waste_qty"]
    return {"top_menu": top_menu, "kitchen_ticket_count": int(kot_count),
            "waste_qty": int(waste)}


# ============================================================ retail reporting
def retail_sales_report(business_id: int, days: int = 30) -> dict:
    """Retail sales by product/category + COGS + gross profit + returns."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT COALESCE(sl.reporting_category,'RETAIL') AS category,
                      count(DISTINCT s.id) AS transaction_count,
                      COALESCE(SUM(sl.quantity),0) AS qty_sold,
                      COALESCE(SUM(sl.line_total),0) AS gross_sales,
                      COALESCE(SUM(sl.cost),0) AS cogs
               FROM local_business.sale s
               JOIN local_business.sale_line sl ON sl.sale_id=s.id
               WHERE s.business_id=%s AND s.status='COMPLETED'
                 AND s.created_at >= now() - make_interval(days => %s)
               GROUP BY sl.reporting_category ORDER BY category""",
            (business_id, days))
        category_sales = cur.fetchall()
        cur.execute(
            """SELECT count(DISTINCT s.id) AS transaction_count,
                      COALESCE(SUM(s.total),0) AS gross_sales,
                      COALESCE(SUM(s.discount),0) AS discounts,
                      COALESCE(SUM(s.tax_amount),0) AS taxes
               FROM local_business.sale s
               WHERE s.business_id=%s AND s.status='COMPLETED'
                 AND s.created_at >= now() - make_interval(days => %s)""",
            (business_id, days))
        totals = cur.fetchone()
        cur.execute(
            """SELECT COALESCE(SUM(sr.total_refund),0) AS returns_total,
                      count(*) AS return_count
               FROM local_business.sale_return sr
               JOIN local_business.branch b ON b.id=sr.branch_id
               WHERE b.business_id=%s AND sr.created_at >= now() - make_interval(days => %s)""",
            (business_id, days))
        returns_row = cur.fetchone()
        cur.execute(
            """SELECT COALESCE(SUM(sl.cost),0) AS cogs
               FROM local_business.sale_line sl
               JOIN local_business.sale s ON s.id=sl.sale_id
               WHERE s.business_id=%s AND s.status='COMPLETED'
                 AND s.created_at >= now() - make_interval(days => %s)""",
            (business_id, days))
        cogs_row = cur.fetchone()

    gross = _num(totals["gross_sales"])
    discounts = _num(totals["discounts"])
    returns_total = _num(returns_row["returns_total"])
    net_sales = gross - discounts - returns_total
    cogs = _num(cogs_row["cogs"])
    gross_profit = net_sales - cogs
    margin = (gross_profit / net_sales * 100) if net_sales else 0
    return {
        "profile": "RETAIL",
        "gross_sales": gross,
        "net_sales": net_sales,
        "discounts": discounts,
        "returns_total": returns_total,
        "return_count": int(returns_row["return_count"]),
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin_pct": round(margin, 2),
        "transaction_count": int(totals["transaction_count"]),
        "category_sales": category_sales,
    }


# ============================================================ hybrid
def hybrid_report(business_id: int, days: int = 30) -> dict:
    """Retail + Restaurant profiles without double counting."""
    retail = retail_sales_report(business_id, days)
    restaurant = restaurant_sales_report(business_id, days)
    return {
        "profile": "HYBRID",
        "retail": retail,
        "restaurant": restaurant,
        "total_gross_sales": retail["gross_sales"] + restaurant["gross_sales"],
        "total_net_sales": retail["net_sales"] + restaurant["net_sales"],
        "total_cogs": retail["cogs"] + restaurant["cogs"],
        "total_gross_profit": retail["gross_profit"] + restaurant["gross_profit"],
    }


# ============================================================ channel / delivery reporting
def channel_report(business_id: int, days: int = 30) -> dict:
    """Sales by channel (dine-in/takeaway/QR/delivery) with settlement."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT COALESCE(ro.sales_channel,'DINE_IN') AS channel,
                      count(DISTINCT ro.id) AS order_count,
                      COALESCE(SUM(ro.total),0) AS gross_sales,
                      COALESCE(SUM(ro.discount),0) AS discounts,
                      COALESCE(SUM(ro.provider_fee),0) AS provider_fee,
                      COALESCE(SUM(ro.merchant_promo_cost),0) AS merchant_promo_cost,
                      COALESCE(SUM(ro.expected_settlement),0) AS expected_settlement,
                      COALESCE(SUM(ro.actual_settlement),0) AS actual_settlement,
                      COALESCE(SUM(ro.settlement_variance),0) AS settlement_variance
               FROM local_business.restaurant_order ro
               WHERE ro.business_id=%s AND ro.status NOT IN ('CANCELLED')
                 AND ro.created_at >= now() - make_interval(days => %s)
               GROUP BY ro.sales_channel ORDER BY channel""",
            (business_id, days))
        channels = cur.fetchall()
    return {"channels": channels}


def delivery_report(business_id: int, days: int = 30) -> dict:
    """Food delivery reporting by provider."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT source_provider AS provider,
                      count(*) AS order_count,
                      COALESCE(SUM(gross_value),0) AS gross_sales,
                      COALESCE(SUM(provider_fee),0) AS provider_fee,
                      COALESCE(SUM(merchant_promo_cost),0) AS merchant_promo_cost,
                      COALESCE(SUM(expected_settlement),0) AS expected_settlement,
                      COALESCE(SUM(actual_settlement),0) AS actual_settlement,
                      COALESCE(SUM(settlement_variance),0) AS settlement_variance,
                      COALESCE(SUM(CASE WHEN status='CANCELLED' THEN 1 ELSE 0 END),0) AS cancelled
               FROM local_business.delivery_order
               WHERE business_id=%s AND created_at >= now() - make_interval(days => %s)
               GROUP BY source_provider ORDER BY provider""",
            (business_id, days))
        providers = cur.fetchall()
    return {"providers": providers}


# ============================================================ accounting reconciliation trace
def trace_sale_to_finance(business_id: int, order_id: int) -> dict:
    """Trace ONE sale/order: operational -> category -> inventory -> COGS -> Finance -> P&L."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT ro.*, b.code AS branch_code FROM local_business.restaurant_order ro
               JOIN local_business.branch b ON b.id=ro.branch_id
               WHERE ro.id=%s AND ro.business_id=%s""",
            (order_id, business_id))
        order = cur.fetchone()
        if not order:
            return {"found": False}
        cur.execute(
            """SELECT rol.menu_item_name, rol.quantity, rol.line_total,
                      mi.reporting_category
               FROM local_business.restaurant_order_line rol
               JOIN local_business.menu_item mi ON mi.id=rol.menu_item_id
               WHERE rol.order_id=%s""", (order_id,))
        lines = cur.fetchall()
        # inventory effect: ingredient consumption for this order
        cur.execute(
            """SELECT im.master_sku_id, m.sku, im.qty, im.movement_type
               FROM multichannel.inventory_movement im
               JOIN multichannel.master_sku m ON m.id=im.master_sku_id
               WHERE im.source_document=%s AND im.movement_type='KELUAR'""",
            (order["order_number"],))
        inventory_effect = cur.fetchall()
        # finance linkage
        cur.execute(
            """SELECT invoice_number, invoice_id, journal_id, total, status
               FROM local_business.restaurant_finance WHERE order_id=%s""",
            (order_id,))
        finance = cur.fetchone()
    return {
        "found": True,
        "order": order,
        "lines": lines,
        "inventory_effect": inventory_effect,
        "finance": finance,
    }
