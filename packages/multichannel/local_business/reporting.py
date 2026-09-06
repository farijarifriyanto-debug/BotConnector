"""Multi-branch reporting for Local Business.

Per-branch sales, per-branch stock, global stock, stock movement, transfer
report, cashier shift, restaurant order status, inventory adjustment/waste,
low stock. Reuses Finance reporting where appropriate.
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg


def sales_by_branch(business_id: int, days: int = 30) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT b.id AS branch_id, b.code AS branch_code, b.name AS branch_name,
                      count(s.id) AS sales_count,
                      COALESCE(SUM(s.total),0) AS total
               FROM local_business.sale s
               JOIN local_business.branch b ON b.id=s.branch_id
               WHERE s.business_id=%s AND s.status='COMPLETED'
                 AND s.created_at >= now() - make_interval(days => %s)
               GROUP BY b.id, b.code, b.name ORDER BY b.code""",
            (business_id, days))
        return cur.fetchall()


def stock_by_branch(business_id: int) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT b.id AS branch_id, b.code AS branch_code, b.name AS branch_name,
                      w.id AS warehouse_id, m.sku, ib.on_hand, ib.reserved,
                      ib.safety_stock, ib.in_transit, ib.available
               FROM local_business.branch b
               JOIN multichannel.warehouse w ON w.id=b.warehouse_id
               JOIN multichannel.inventory_balance ib ON ib.warehouse_id=w.id
               JOIN multichannel.master_sku m ON m.id=ib.master_sku_id
               WHERE b.business_id=%s ORDER BY b.code, m.sku""",
            (business_id,))
        return cur.fetchall()


def global_stock(business_id: int) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT m.sku, p.name,
                      COALESCE(SUM(ib.on_hand),0) AS total_on_hand,
                      COALESCE(SUM(ib.reserved),0) AS total_reserved,
                      COALESCE(SUM(ib.in_transit),0) AS total_in_transit,
                      COALESCE(SUM(ib.available),0) AS total_available
               FROM multichannel.master_sku m
               JOIN multichannel.product p ON p.id=m.product_id
               LEFT JOIN multichannel.inventory_balance ib ON ib.master_sku_id=m.id
               WHERE m.id IN (
                 SELECT DISTINCT master_sku_id FROM multichannel.inventory_balance ib2
                 JOIN local_business.branch b ON b.warehouse_id=ib2.warehouse_id
                 WHERE b.business_id=%s)
               GROUP BY m.sku, p.name ORDER BY m.sku""",
            (business_id,))
        return cur.fetchall()


def low_stock(business_id: int, threshold: int = 5) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT b.code AS branch_code, m.sku, ib.on_hand, ib.available
               FROM local_business.branch b
               JOIN multichannel.inventory_balance ib ON ib.warehouse_id=b.warehouse_id
               JOIN multichannel.master_sku m ON m.id=ib.master_sku_id
               WHERE b.business_id=%s AND ib.available <= %s
               ORDER BY ib.available ASC""",
            (business_id, threshold))
        return cur.fetchall()


def stock_movements(business_id: int, limit: int = 200) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT im.id, im.movement_type, im.qty, im.on_hand_after,
                      im.available_after, im.reference, im.note, im.actor,
                      im.created_at, m.sku, w.code AS warehouse_code
               FROM multichannel.inventory_movement im
               JOIN multichannel.master_sku m ON m.id=im.master_sku_id
               LEFT JOIN multichannel.warehouse w ON w.id=im.warehouse_id
               WHERE im.warehouse_id IN (
                 SELECT warehouse_id FROM local_business.branch WHERE business_id=%s)
               ORDER BY im.id DESC LIMIT %s""",
            (business_id, limit))
        return cur.fetchall()


def transfer_report(business_id: int) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT t.transfer_number, t.status, t.created_at, t.shipped_at,
                      t.received_at, sb.code AS source_branch, db.code AS dest_branch,
                      count(tl.id) AS line_count
               FROM local_business.transfer t
               JOIN local_business.branch sb ON sb.id=t.source_branch_id
               JOIN local_business.branch db ON db.id=t.dest_branch_id
               LEFT JOIN local_business.transfer_line tl ON tl.transfer_id=t.id
               WHERE t.business_id=%s
               GROUP BY t.id, t.transfer_number, t.status, t.created_at, t.shipped_at,
                        t.received_at, sb.code, db.code
               ORDER BY t.id DESC""",
            (business_id,))
        return cur.fetchall()


def shift_report(business_id: int) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT sh.id, sh.opened_at, sh.closed_at, sh.opening_cash,
                      sh.closing_cash, sh.expected_cash, sh.status,
                      r.code AS register_code, b.code AS branch_code,
                      ca.name AS cashier_name
               FROM local_business.shift sh
               JOIN local_business.register r ON r.id=sh.register_id
               JOIN local_business.branch b ON b.id=r.branch_id
               LEFT JOIN local_business.cashier ca ON ca.id=sh.cashier_id
               WHERE b.business_id=%s ORDER BY sh.id DESC""",
            (business_id,))
        return cur.fetchall()


def restaurant_order_status(business_id: int) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT status, count(*) AS n FROM local_business.restaurant_order
               WHERE business_id=%s GROUP BY status ORDER BY status""",
            (business_id,))
        return cur.fetchall()


def dashboard(business_id: int) -> dict:
    """Live metrics from real data (no synthetic acceptance data)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT count(*) AS n, COALESCE(SUM(total),0) AS total
               FROM local_business.sale
               WHERE business_id=%s AND status='COMPLETED'
                 AND created_at >= date_trunc('day', now())""",
            (business_id,))
        today = cur.fetchone()
        cur.execute(
            """SELECT COALESCE(SUM(total),0) AS total, count(*) AS n
               FROM local_business.sale
               WHERE business_id=%s AND status='COMPLETED'""",
            (business_id,))
        all_sales = cur.fetchone()
        cur.execute(
            """SELECT count(*) AS n FROM local_business.restaurant_order
               WHERE business_id=%s AND status IN ('NEW','ACCEPTED','PREPARING','READY')""",
            (business_id,))
        open_orders = cur.fetchone()
        cur.execute(
            """SELECT count(*) AS n FROM local_business.kot k
               JOIN local_business.restaurant_order o ON o.id=k.order_id
               WHERE o.business_id=%s AND k.status IN ('NEW','ACCEPTED','PREPARING')""",
            (business_id,))
        pending_kitchen = cur.fetchone()
        cur.execute(
            """SELECT count(*) AS n FROM local_business.offline_queue
               WHERE business_id=%s AND status='LOCAL_PENDING'""",
            (business_id,))
        pending_offline = cur.fetchone()
        cur.execute(
            """SELECT count(*) AS n FROM local_business.transfer
               WHERE business_id=%s AND status IN ('APPROVED','IN_TRANSIT')""",
            (business_id,))
        active_transfers = cur.fetchone()
        avg_ticket = (float(all_sales["total"]) / int(all_sales["n"])) if int(all_sales["n"]) else 0
        return {
            "sales_today": float(today["total"]),
            "transaction_count_today": int(today["n"]),
            "average_ticket": round(avg_ticket, 2),
            "open_restaurant_orders": int(open_orders["n"]),
            "pending_kitchen_orders": int(pending_kitchen["n"]),
            "pending_offline_sync": int(pending_offline["n"]),
            "active_transfers": int(active_transfers["n"]),
        }


def daily_summary(*, business_id: int, local_date, timezone: str) -> dict:
    """Compute a canonical daily owner summary for one local calendar day.

    Uses the business's canonical timezone to derive the exact UTC window for
    the given local date, then reads authoritative sale rows (status=COMPLETED).
    Read-only; never posts to Finance or mutates business data.

    Included metrics are those proven canonical from local_business.sale:
    business name, local date, omzet (sum total), and transaction count.
    Payment-method totals are included only when tender_method is present.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone or "UTC")
    day_start_local = datetime.combine(local_date, datetime.min.time(), tzinfo=tz)
    day_end_local = day_start_local + timedelta(days=1)
    start_utc = day_start_local.astimezone(ZoneInfo("UTC"))
    end_utc = day_end_local.astimezone(ZoneInfo("UTC"))

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT name, timezone FROM local_business.business WHERE id=%s",
            (business_id,))
        biz = cur.fetchone()
        if not biz:
            return {"ok": False, "error": "business_not_found"}
        cur.execute(
            """SELECT COALESCE(SUM(total),0) AS omzet, count(*) AS tx_count
               FROM local_business.sale
               WHERE business_id=%s AND status='COMPLETED'
                 AND created_at >= %s AND created_at < %s""",
            (business_id, start_utc, end_utc))
        row = cur.fetchone()
        cur.execute(
            """SELECT tender_method, COALESCE(SUM(total),0) AS total, count(*) AS n
               FROM local_business.sale
               WHERE business_id=%s AND status='COMPLETED'
                 AND created_at >= %s AND created_at < %s
                 AND tender_method IS NOT NULL AND tender_method<>''
               GROUP BY tender_method""",
            (business_id, start_utc, end_utc))
        methods = {r["tender_method"]: float(r["total"]) for r in cur.fetchall()}

    return {
        "ok": True,
        "business_id": business_id,
        "business_name": biz["name"],
        "timezone": biz["timezone"] or "UTC",
        "local_date": str(local_date),
        "omzet": float(row["omzet"]),
        "transaction_count": int(row["tx_count"]),
        "payment_methods": methods,
        "range_start_utc": start_utc.isoformat(),
        "range_end_utc": end_utc.isoformat(),
    }
