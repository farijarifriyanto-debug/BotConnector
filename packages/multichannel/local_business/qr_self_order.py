"""QR menu / self-order + queue / customer display.

Local self-ordering without third-party API. Flow: table/pickup QR ->
responsive menu -> cart -> modifier -> note -> submit -> canonical Restaurant
Order -> KDS -> inventory/recipe -> POS/payment recording -> reporting.

Prevents fake "paid" state merely because the user submitted an order.
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg
from . import core
from . import restaurant


def create_qr_menu(*, business_id: int, branch_id: int, code: str,
                   kind: str = "TABLE", table_id: int | None = None) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.qr_menu
               (business_id, branch_id, code, kind, table_id)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (business_id, branch_id, code) DO UPDATE SET
                 kind=EXCLUDED.kind, table_id=EXCLUDED.table_id, active=TRUE
               RETURNING id, code, kind, table_id""",
            (business_id, branch_id, code, kind, table_id))
        r = cur.fetchone()
        c.commit()
        return r


def qr_menu_payload(*, business_id: int, branch_id: int, code: str) -> dict:
    """Menu payload for a QR code (responsive self-order)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM local_business.qr_menu
               WHERE business_id=%s AND branch_id=%s AND code=%s AND active=TRUE""",
            (business_id, branch_id, code))
        qr = cur.fetchone()
        if not qr:
            return {"found": False}
        cur.execute(
            """SELECT mi.id, mi.name, mi.price, mi.reporting_category,
                      mc.name AS category
               FROM local_business.menu_item mi
               LEFT JOIN local_business.menu_category mc ON mc.id=mi.category_id
               WHERE mi.business_id=%s AND mi.active=TRUE ORDER BY mi.name""",
            (business_id,))
        menu = cur.fetchall()
        # modifiers per item
        for m in menu:
            cur.execute(
                """SELECT id, name, price_delta FROM local_business.menu_modifier
                   WHERE menu_item_id=%s""", (m["id"],))
            m["modifiers"] = cur.fetchall()
    return {"found": True, "qr": qr, "menu": menu}


def submit_self_order(
    *, tenant_id: str, business_id: int, branch_id: int, register_id: int,
    warehouse_id: int, qr_code: str, lines: list[dict],
    order_type: str = "DINE_IN", guest_count: int = 1, note: str = "",
    client_event_id: str = "", device_id: str = "",
) -> dict:
    """Submit a QR self-order -> canonical Restaurant Order -> KDS.

    Does NOT mark paid. Payment is recorded separately at POS.
    """
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT id, kind, table_id FROM local_business.qr_menu
               WHERE business_id=%s AND branch_id=%s AND code=%s AND active=TRUE""",
            (business_id, branch_id, qr_code))
        qr = cur.fetchone()
        if not qr:
            raise KeyError(f"QR {qr_code} tidak valid")
        c.commit()

    table_id = qr["table_id"] if qr["kind"] == "TABLE" else None
    if qr["kind"] == "TAKEAWAY":
        order_type = "TAKEAWAY"
    elif qr["kind"] == "PICKUP":
        order_type = "PICKUP"

    ro = restaurant.create_restaurant_order(
        tenant_id=tenant_id, business_id=business_id, branch_id=branch_id,
        register_id=register_id, cashier_id=None, warehouse_id=warehouse_id,
        lines=lines, order_type=order_type, table_id=table_id,
        guest_count=guest_count, note=note,
        client_event_id=client_event_id, device_id=device_id, origin="QR_SELF_ORDER")

    # create queue ticket
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(id),0)+1 AS n FROM local_business.queue_ticket WHERE business_id=%s",
            (business_id,))
        n = cur.fetchone()["n"]
        queue_number = f"Q-{n:03d}"
        cur.execute(
            """INSERT INTO local_business.queue_ticket
               (business_id, branch_id, queue_number, order_id, status)
               VALUES (%s,%s,%s,%s,'QUEUED')""",
            (business_id, branch_id, queue_number, ro["order_id"]))
        c.commit()

    core.catat_audit("qr_self_order", tenant_id=tenant_id, business_id=business_id,
                     branch_id=branch_id,
                     payload={"qr": qr_code, "order": ro["order_number"],
                              "queue": queue_number})
    return {**ro, "queue_number": queue_number, "payment_state": "UNPAID"}


def queue_display(branch_id: int) -> list[dict]:
    """Queue/customer display data (QUEUED/PREPARING/READY)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT qt.queue_number, qt.status, qt.updated_at, ro.order_number
               FROM local_business.queue_ticket qt
               JOIN local_business.restaurant_order ro ON ro.id=qt.order_id
               WHERE qt.branch_id=%s AND qt.status IN ('QUEUED','PREPARING','READY')
               ORDER BY qt.id""",
            (branch_id,))
        return cur.fetchall()


def set_queue_status(*, queue_ticket_id: int, status: str) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "UPDATE local_business.queue_ticket SET status=%s, updated_at=now() WHERE id=%s RETURNING id, status",
            (status, queue_ticket_id))
        r = cur.fetchone()
        c.commit()
        return r
