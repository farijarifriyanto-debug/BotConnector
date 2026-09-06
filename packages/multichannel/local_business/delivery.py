"""Generic Restaurant Order Core + canonical menu channel mapping + delivery order.

All restaurant order sources (LOCAL_DINE_IN, LOCAL_TAKEAWAY, LOCAL_PICKUP,
QR_SELF_ORDER, GOFOOD, GRABFOOD, SHOPEEFOOD) normalize into the SAME
Restaurant Order Core. One canonical menu/recipe truth; channel prices may
differ but ingredient truth remains ONE.

Order lineage / double-count protection: duplicate source data maps to ONE
canonical business event and ONE Finance posting.
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg
from . import core
from . import restaurant


# ============================================================ canonical menu channel mapping
def upsert_channel_menu_mapping(*, business_id: int, menu_item_id: int, channel: str,
                                channel_item_id: str = "", channel_price=None,
                                available: bool = True, channel_hours: dict | None = None,
                                channel_promo: dict | None = None) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.channel_menu_mapping
               (business_id, menu_item_id, channel, channel_item_id, channel_price,
                available, channel_hours, channel_promo)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (menu_item_id, channel) DO UPDATE SET
                 channel_item_id=EXCLUDED.channel_item_id,
                 channel_price=EXCLUDED.channel_price,
                 available=EXCLUDED.available,
                 channel_hours=EXCLUDED.channel_hours,
                 channel_promo=EXCLUDED.channel_promo,
                 updated_at=now()
               RETURNING id, menu_item_id, channel, channel_item_id, channel_price, available""",
            (business_id, menu_item_id, channel, channel_item_id, channel_price,
             available, __import__("json").dumps(channel_hours or {}),
             __import__("json").dumps(channel_promo or {})))
        r = cur.fetchone()
        c.commit()
        return r


def channel_menu_availability(menu_item_id: int, channel: str) -> dict:
    """Menu availability for a channel, derived from recipe/ingredient ATP."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM local_business.channel_menu_mapping
               WHERE menu_item_id=%s AND channel=%s""",
            (menu_item_id, channel))
        mapping = cur.fetchone()
    if not mapping:
        return {"available": False, "reason": "no_channel_mapping"}
    # recipe-controlled: derive from ingredient availability
    recipe = restaurant.get_active_recipe(menu_item_id)
    if recipe:
        # find branch warehouse for this business
        cur = None
        with _pg() as c2:
            cur2 = c2.cursor()
            cur2.execute(
                "SELECT warehouse_id FROM local_business.branch WHERE business_id=%s LIMIT 1",
                (mapping["business_id"],))
            b = cur2.fetchone()
        if b:
            from . import inventory as inv
            producible = restaurant.producible_quantity(menu_item_id, b["warehouse_id"])
            if producible <= 0:
                return {"available": False, "reason": "insufficient_ingredient",
                        "producible": 0}
    return {"available": bool(mapping["available"]), "channel_price": mapping["channel_price"]}


def generate_channel_availability_outbox(business_id: int, channel: str) -> dict:
    """Generate desired channel availability state for all menu items."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT id FROM local_business.menu_item WHERE business_id=%s AND active=TRUE",
            (business_id,))
        items = [r["id"] for r in cur.fetchall()]
    out = []
    for mid in items:
        a = channel_menu_availability(mid, channel)
        out.append({"menu_item_id": mid, "channel": channel, **a})
    return {"channel": channel, "items": out, "real_provider_write": "OFF"}


# ============================================================ order lineage
def record_lineage(*, business_id: int, source_provider: str, source_pos: str,
                   external_order_id: str, external_transaction_id: str,
                   canonical_order_id: int, canonical_type: str,
                   lineage_origin: str = "") -> dict:
    """Record order lineage. Idempotent per (provider, pos, order, tx)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.order_lineage
               (business_id, source_provider, source_pos, external_order_id,
                external_transaction_id, canonical_order_id, canonical_type,
                lineage_origin, correlation_state)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'RESOLVED')
               ON CONFLICT (source_provider, source_pos, external_order_id, external_transaction_id)
               DO NOTHING
               RETURNING id, correlation_state""",
            (business_id, source_provider, source_pos, external_order_id,
             external_transaction_id, canonical_order_id, canonical_type, lineage_origin))
        r = cur.fetchone()
        c.commit()
        if not r:
            return {"duplicate": True}
        return {"duplicate": False, "lineage_id": r["id"]}


def find_canonical_order(*, business_id: int, source_provider: str, source_pos: str,
                         external_order_id: str, external_transaction_id: str = "") -> dict | None:
    """Find existing canonical order for a source (double-count protection)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM local_business.order_lineage
               WHERE business_id=%s AND source_provider=%s AND source_pos=%s
                 AND external_order_id=%s AND external_transaction_id=%s""",
            (business_id, source_provider, source_pos, external_order_id,
             external_transaction_id))
        return cur.fetchone()


# ============================================================ delivery order core
def create_delivery_order(
    *,
    tenant_id: str, business_id: int, branch_id: int, register_id: int,
    warehouse_id: int, source_provider: str, external_order_id: str,
    outlet_id: str, order_type: str = "DELIVERY",
    lines: list[dict],  # [{channel_item_id, name, quantity, unit_price, modifiers}]
    gross_value=0, discount=0, service_charge=0, tax_amount=0,
    provider_fee=0, merchant_promo_cost=0, platform_promo=0,
    local_discount=0, other_adjustment=0,
    payment_state: str = "UNPAID", payment_method: str = "",
    scheduled_at=None, provider_status: str = "",
    raw_payload: dict | None = None,
    source_pos: str = "", external_transaction_id: str = "",
) -> dict:
    """Create a delivery order, normalize into Restaurant Order Core.

    Idempotent per (source_provider, outlet_id, external_order_id). Duplicate
    delivery (1x/5x/10x) produces ONE restaurant order, ONE KOT, ONE
    ingredient effect, ONE Finance effect.
    """
    with _pg() as c:
        cur = c.cursor()
        # idempotency: same provider+outlet+external_order -> return existing
        cur.execute(
            """SELECT id FROM local_business.delivery_order
               WHERE source_provider=%s AND outlet_id=%s AND external_order_id=%s""",
            (source_provider, outlet_id, external_order_id))
        ada = cur.fetchone()
        if ada:
            cur.execute("SELECT * FROM local_business.delivery_order WHERE id=%s", (ada["id"],))
            r = cur.fetchone()
            r["duplicate"] = True
            c.commit()
            return r

        # resolve channel menu mapping -> canonical menu_item
        menu_lines = []
        for ln in lines:
            cur.execute(
                """SELECT menu_item_id FROM local_business.channel_menu_mapping
                   WHERE business_id=%s AND channel=%s AND channel_item_id=%s""",
                (business_id, source_provider, ln.get("channel_item_id", "")))
            m = cur.fetchone()
            if m:
                menu_lines.append({"menu_item_id": m["menu_item_id"],
                                   "quantity": int(ln["quantity"]),
                                   "notes": ln.get("notes", "")})
            else:
                # no mapping: flag for review, do not silently drop
                menu_lines.append({"menu_item_id": None,
                                   "quantity": int(ln["quantity"]),
                                   "notes": ln.get("notes", ""),
                                   "unmapped": True})

        # create canonical restaurant order (if all lines mapped)
        restaurant_order_id = None
        if all(ml.get("menu_item_id") for ml in menu_lines):
            ro = restaurant.create_restaurant_order(
                tenant_id=tenant_id, business_id=business_id, branch_id=branch_id,
                register_id=register_id, cashier_id=None, warehouse_id=warehouse_id,
                lines=menu_lines, order_type=order_type,
                client_event_id=f"delivery:{source_provider}:{external_order_id}",
                device_id=f"DELIVERY-{source_provider}", origin="DELIVERY",
                source_provider=source_provider, sales_channel=source_provider,
                external_order_id=external_order_id, scheduled_at=scheduled_at,
                provider_status=provider_status, raw_payload=raw_payload)
            restaurant_order_id = ro["order_id"]

        net_value = gross_value - discount + service_charge
        expected_settlement = net_value - provider_fee - merchant_promo_cost

        cur.execute(
            """INSERT INTO local_business.delivery_order
               (tenant_id, business_id, branch_id, source_provider, external_order_id,
                outlet_id, order_type, status, provider_status, scheduled_at,
                gross_value, net_value, discount, service_charge, tax_amount,
                payment_state, payment_method, provider_fee, merchant_promo_cost,
                platform_promo, local_discount, other_adjustment,
                expected_settlement, restaurant_order_id, raw_payload)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'RECEIVED',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (tenant_id, business_id, branch_id, source_provider, external_order_id,
             outlet_id, order_type, provider_status, scheduled_at,
             gross_value, net_value, discount, service_charge, tax_amount,
             payment_state, payment_method, provider_fee, merchant_promo_cost,
             platform_promo, local_discount, other_adjustment,
             expected_settlement, restaurant_order_id,
             __import__("json").dumps(raw_payload or {}, default=str)))
        did = cur.fetchone()["id"]

        for i, ln in enumerate(lines, start=1):
            cur.execute(
                """INSERT INTO local_business.delivery_order_line
                   (delivery_order_id, menu_item_id, channel_item_id, name, quantity,
                    unit_price, line_total, modifier_json, line_no)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (did, ln.get("menu_item_id"), ln.get("channel_item_id", ""),
                 ln.get("name", ""), int(ln["quantity"]), float(ln.get("unit_price", 0)),
                 float(ln.get("quantity", 0)) * float(ln.get("unit_price", 0)),
                 __import__("json").dumps(ln.get("modifiers", {})), i))

        # record lineage
        if restaurant_order_id:
            record_lineage(business_id=business_id, source_provider=source_provider,
                           source_pos=source_pos or source_provider,
                           external_order_id=external_order_id,
                           external_transaction_id=external_transaction_id,
                           canonical_order_id=restaurant_order_id,
                           canonical_type="RESTAURANT_ORDER",
                           lineage_origin="delivery_adapter")

        core.catat_audit("delivery_order_created", tenant_id=tenant_id,
                         business_id=business_id, branch_id=branch_id,
                         payload={"provider": source_provider,
                                  "external_order_id": external_order_id,
                                  "restaurant_order_id": restaurant_order_id})
        c.commit()
        return {"duplicate": False, "delivery_order_id": did,
                "restaurant_order_id": restaurant_order_id,
                "expected_settlement": expected_settlement}


def set_delivery_status(*, delivery_order_id: int, status: str, actor: str = "") -> dict:
    """Transition delivery order status. Normalizes provider states."""
    allowed = {"RECEIVED", "ACCEPTED", "PREPARING", "READY", "DRIVER_ASSIGNED",
               "DRIVER_ARRIVED", "PICKED_UP", "COMPLETED", "CANCELLED"}
    if status not in allowed:
        raise ValueError(f"status {status} tidak valid")
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "UPDATE local_business.delivery_order SET status=%s, updated_at=now() WHERE id=%s RETURNING id, status",
            (status, delivery_order_id))
        r = cur.fetchone()
        c.commit()
        if not r:
            raise KeyError(f"delivery_order {delivery_order_id} tidak ada")
        return r


def record_delivery_settlement(
    *, business_id: int, source_provider: str, outlet_id: str, settlement_ref: str,
    gross_value, provider_fee, merchant_promo_cost, expected_settlement,
    actual_settlement, finance_tx_id: str = "",
) -> dict:
    """Record delivery settlement. Idempotent per (provider, outlet, ref)."""
    variance = expected_settlement - actual_settlement
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.delivery_settlement
               (business_id, source_provider, outlet_id, settlement_ref, gross_value,
                provider_fee, merchant_promo_cost, expected_settlement,
                actual_settlement, variance, status, finance_tx_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PROCESSED',%s)
               ON CONFLICT (source_provider, outlet_id, settlement_ref) DO NOTHING
               RETURNING id""",
            (business_id, source_provider, outlet_id, settlement_ref, gross_value,
             provider_fee, merchant_promo_cost, expected_settlement,
             actual_settlement, variance, finance_tx_id))
        r = cur.fetchone()
        c.commit()
        if not r:
            return {"duplicate": True}
        return {"duplicate": False, "settlement_id": r["id"], "variance": variance}
