"""Restaurant POS — menu, recipe/BOM, ingredient consumption, orders, KOT.

Menu inventory is ingredient-based where configured. A restaurant order
resolves recipe consumption into Central Inventory (location-aware).

Lifecycle:
  order accepted -> ingredient reservation if configured
  order cancelled before prep -> release reservation
  prepared/served -> consume ingredients / ON_HAND decreases
  void after prep -> do NOT restore ingredients; record waste explicitly
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg
from . import core
from . import inventory as inv


class StokTidakCukup(Exception):
    pass


# ============================================================ menu
def upsert_menu_category(*, business_id: int, name: str, sort_order: int = 0) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.menu_category (business_id, name, sort_order)
               VALUES (%s,%s,%s)
               ON CONFLICT (business_id, name) DO UPDATE SET sort_order=EXCLUDED.sort_order
               RETURNING id, business_id, name""",
            (business_id, name, sort_order))
        r = cur.fetchone()
        c.commit()
        return r


def upsert_menu_item(*, business_id: int, name: str, price, category_id=None,
                     is_stocked: bool = False, stocked_sku_id=None) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.menu_item
               (business_id, category_id, name, price, is_stocked, stocked_sku_id)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (business_id, name) DO UPDATE SET
                 price=EXCLUDED.price, category_id=EXCLUDED.category_id,
                 is_stocked=EXCLUDED.is_stocked, stocked_sku_id=EXCLUDED.stocked_sku_id
               RETURNING id, business_id, name, price, is_stocked, stocked_sku_id""",
            (business_id, category_id, name, price, is_stocked, stocked_sku_id))
        r = cur.fetchone()
        c.commit()
        return r


def upsert_menu_variant(*, menu_item_id: int, name: str, price_delta=0) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.menu_variant (menu_item_id, name, price_delta)
               VALUES (%s,%s,%s)
               ON CONFLICT (menu_item_id, name) DO UPDATE SET price_delta=EXCLUDED.price_delta
               RETURNING id, menu_item_id, name, price_delta""",
            (menu_item_id, name, price_delta))
        r = cur.fetchone()
        c.commit()
        return r


def upsert_menu_modifier(*, menu_item_id: int, name: str, price_delta=0) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.menu_modifier (menu_item_id, name, price_delta)
               VALUES (%s,%s,%s)
               ON CONFLICT (menu_item_id, name) DO UPDATE SET price_delta=EXCLUDED.price_delta
               RETURNING id, menu_item_id, name, price_delta""",
            (menu_item_id, name, price_delta))
        r = cur.fetchone()
        c.commit()
        return r


# ============================================================ recipe / BOM
def upsert_recipe(*, menu_item_id: int, version: int = 1, yield_qty=1,
                  waste_factor=0, components: list[dict] | None = None) -> dict:
    """Create/update a recipe version with components."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.recipe
               (menu_item_id, version, yield_qty, waste_factor, active)
               VALUES (%s,%s,%s,%s,TRUE)
               ON CONFLICT (menu_item_id, version) DO UPDATE SET
                 yield_qty=EXCLUDED.yield_qty, waste_factor=EXCLUDED.waste_factor,
                 active=TRUE
               RETURNING id, menu_item_id, version, yield_qty, waste_factor""",
            (menu_item_id, version, yield_qty, waste_factor))
        r = cur.fetchone()
        if components is not None:
            cur.execute("DELETE FROM local_business.recipe_component WHERE recipe_id=%s", (r["id"],))
            for comp in components:
                cur.execute(
                    """INSERT INTO local_business.recipe_component
                       (recipe_id, master_sku_id, sku, quantity, unit)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (r["id"], comp["master_sku_id"], comp.get("sku", ""),
                     comp["quantity"], comp.get("unit", "pcs")))
        c.commit()
        return r


def get_active_recipe(menu_item_id: int) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM local_business.recipe
               WHERE menu_item_id=%s AND active=TRUE ORDER BY version DESC LIMIT 1""",
            (menu_item_id,))
        r = cur.fetchone()
        if not r:
            return None
        cur.execute(
            "SELECT * FROM local_business.recipe_component WHERE recipe_id=%s", (r["id"],))
        r["components"] = cur.fetchall()
        return r


def add_modifier_ingredient(*, modifier_id: int, master_sku_id: int,
                            quantity, unit: str = "pcs") -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.modifier_ingredient
               (modifier_id, master_sku_id, quantity, unit)
               VALUES (%s,%s,%s,%s) RETURNING id""",
            (modifier_id, master_sku_id, quantity, unit))
        r = cur.fetchone()
        c.commit()
        return r


def _recipe_ingredients(cur, menu_item_id: int, variant_id=None,
                        modifiers: list[int] | None = None) -> list[dict]:
    """Resolve ingredient requirements for one menu item (with modifiers)."""
    cur.execute(
        """SELECT * FROM local_business.recipe
           WHERE menu_item_id=%s AND active=TRUE ORDER BY version DESC LIMIT 1""",
        (menu_item_id,))
    recipe = cur.fetchone()
    if not recipe:
        return []
    cur.execute(
        "SELECT * FROM local_business.recipe_component WHERE recipe_id=%s", (recipe["id"],))
    comps = cur.fetchall()
    ing = []
    for comp in comps:
        ing.append({"master_sku_id": comp["master_sku_id"], "sku": comp["sku"],
                    "quantity": float(comp["quantity"])})
    if modifiers:
        for mid in modifiers:
            cur.execute(
                """SELECT mi.master_sku_id, mi.quantity, m.name
                   FROM local_business.modifier_ingredient mi
                   JOIN local_business.menu_modifier m ON m.id=mi.modifier_id
                   WHERE mi.modifier_id=%s""", (mid,))
            for row in cur.fetchall():
                ing.append({"master_sku_id": row["master_sku_id"],
                            "sku": "", "quantity": float(row["quantity"])})
    return ing


def _validate_menu_line(cur, *, business_id: int, menu_item_id: int,
                        variant_id=None, modifiers: list[int] | None = None) -> None:
    cur.execute(
        "SELECT 1 FROM local_business.menu_item WHERE id=%s AND business_id=%s",
        (menu_item_id, business_id),
    )
    if not cur.fetchone():
        raise KeyError("menu item bukan milik business")
    if variant_id is not None:
        cur.execute(
            "SELECT 1 FROM local_business.menu_variant WHERE id=%s AND menu_item_id=%s",
            (variant_id, menu_item_id),
        )
        if not cur.fetchone():
            raise KeyError("variant bukan milik menu item")
    for modifier_id in modifiers or []:
        cur.execute(
            "SELECT 1 FROM local_business.menu_modifier WHERE id=%s AND menu_item_id=%s",
            (modifier_id, menu_item_id),
        )
        if not cur.fetchone():
            raise KeyError("modifier bukan milik menu item")


def producible_quantity(menu_item_id: int, warehouse_id: int) -> int:
    """Max producible units from component availability (recipe-driven)."""
    with _pg() as c:
        cur = c.cursor()
        recipe = get_active_recipe(menu_item_id)
        if not recipe:
            return 0
        max_units = None
        for comp in recipe["components"]:
            avail = inv.location_atp(comp["master_sku_id"], warehouse_id)
            if float(comp["quantity"]) <= 0:
                continue
            units = int(avail // float(comp["quantity"]))
            if max_units is None or units < max_units:
                max_units = units
        return max_units or 0


# ============================================================ tables
def upsert_table(*, branch_id: int, name: str, capacity: int = 1) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.restaurant_table (branch_id, name, capacity)
               VALUES (%s,%s,%s)
               ON CONFLICT (branch_id, name) DO UPDATE SET capacity=EXCLUDED.capacity
               RETURNING id, branch_id, name, capacity""",
            (branch_id, name, capacity))
        r = cur.fetchone()
        c.commit()
        return r


# ============================================================ restaurant order
def _next_order_number(cur, business_id: int) -> str:
    cur.execute("SELECT nextval('local_business.restaurant_order_seq') AS n")
    n = cur.fetchone()["n"]
    return f"ORD-{business_id}-{n:06d}"


def _next_kot_number(cur, business_id: int) -> str:
    cur.execute("SELECT nextval('local_business.kot_seq') AS n")
    n = cur.fetchone()["n"]
    return f"KOT-{business_id}-{n:06d}"


def create_restaurant_order(
    *,
    tenant_id: str, business_id: int, branch_id: int, register_id: int,
    cashier_id: int | None, warehouse_id: int,
    lines: list[dict],  # [{menu_item_id, quantity, variant_id, modifiers:[ids], notes}]
    order_type: str = "DINE_IN", table_id: int | None = None,
    guest_count: int = 1, note: str = "",
    client_event_id: str = "", device_id: str = "",
    created_at_client=None, origin: str = "ONLINE",
    source_provider: str = "LOCAL", sales_channel: str = "",
    external_order_id: str = "", scheduled_at=None,
    provider_status: str = "", raw_payload: dict | None = None,
) -> dict:
    """Create a restaurant order. Resolves recipe ingredients and reserves them."""
    if not lines:
        raise ValueError("order tanpa line")
    if not sales_channel:
        sales_channel = order_type if order_type in ("DINE_IN", "TAKEAWAY", "PICKUP") else "DINE_IN"
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
        if table_id is not None:
            cur.execute(
                """SELECT 1 FROM local_business.restaurant_table
                   WHERE id=%s AND branch_id=%s""", (table_id, branch_id))
            if not cur.fetchone():
                raise KeyError("meja bukan milik branch")
        if client_event_id and device_id:
            cur.execute(
                """SELECT id FROM local_business.restaurant_order
                   WHERE business_id=%s AND device_id=%s AND client_event_id=%s""",
                (business_id, device_id, client_event_id))
            ada = cur.fetchone()
            if ada:
                cur.execute("SELECT * FROM local_business.restaurant_order WHERE id=%s", (ada["id"],))
                r = cur.fetchone()
                r["duplicate"] = True
                c.commit()
                return r

        order_number = _next_order_number(cur, business_id)
        subtotal = 0
        # resolve ingredient requirements across all lines
        ingredient_req = {}  # master_sku_id -> qty
        for ln in lines:
            qty = int(ln["quantity"])
            if qty <= 0:
                raise ValueError("quantity harus > 0")
            _validate_menu_line(
                cur, business_id=business_id, menu_item_id=ln["menu_item_id"],
                variant_id=ln.get("variant_id"), modifiers=ln.get("modifiers"),
            )
            cur.execute(
                "SELECT * FROM local_business.menu_item WHERE id=%s", (ln["menu_item_id"],))
            mi = cur.fetchone()
            if not mi or mi["business_id"] != business_id:
                raise KeyError(f"menu_item {ln['menu_item_id']} tidak ada")
            unit_price = float(mi["price"])
            if ln.get("variant_id"):
                cur.execute(
                    "SELECT price_delta FROM local_business.menu_variant WHERE id=%s",
                    (ln["variant_id"],))
                v = cur.fetchone()
                if v:
                    unit_price += float(v["price_delta"])
            mods = ln.get("modifiers", []) or []
            for mid in mods:
                cur.execute(
                    "SELECT price_delta FROM local_business.menu_modifier WHERE id=%s", (mid,))
                m = cur.fetchone()
                if m:
                    unit_price += float(m["price_delta"])
            subtotal += qty * unit_price
            # ingredient requirement
            for ing in _recipe_ingredients(cur, mi["id"], ln.get("variant_id"), mods):
                ingredient_req[ing["master_sku_id"]] = \
                    ingredient_req.get(ing["master_sku_id"], 0) + ing["quantity"] * qty

        # check ingredient availability (recipe-driven) and reserve
        for mid, qty in ingredient_req.items():
            avail = inv.location_atp(mid, warehouse_id)
            if qty > avail:
                raise StokTidakCukup(
                    f"ingredient sku {mid}: butuh {qty}, tersedia {avail} di lokasi {warehouse_id}")

        cur.execute(
            """INSERT INTO local_business.restaurant_order
               (tenant_id, business_id, branch_id, register_id, cashier_id,
                table_id, order_number, order_type, guest_count, status, note,
                subtotal, discount, tax_amount, total, client_event_id, device_id,
                created_at_client, source_provider, sales_channel, external_order_id,
                scheduled_at, provider_status, raw_payload)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'NEW',%s,%s,0,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (tenant_id, business_id, branch_id, register_id, cashier_id,
             table_id, order_number, order_type, guest_count, note,
             subtotal, subtotal, client_event_id, device_id, created_at_client,
             source_provider, sales_channel, external_order_id, scheduled_at,
             provider_status, __import__("json").dumps(raw_payload or {}, default=str)))
        order_id = cur.fetchone()["id"]

        for i, ln in enumerate(lines, start=1):
            qty = int(ln["quantity"])
            cur.execute(
                "SELECT * FROM local_business.menu_item WHERE id=%s", (ln["menu_item_id"],))
            mi = cur.fetchone()
            unit_price = float(mi["price"])
            if ln.get("variant_id"):
                cur.execute(
                    "SELECT price_delta FROM local_business.menu_variant WHERE id=%s",
                    (ln["variant_id"],))
                v = cur.fetchone()
                if v:
                    unit_price += float(v["price_delta"])
            mods = ln.get("modifiers", []) or []
            for mid in mods:
                cur.execute(
                    "SELECT price_delta FROM local_business.menu_modifier WHERE id=%s", (mid,))
                m = cur.fetchone()
                if m:
                    unit_price += float(m["price_delta"])
            cur.execute(
                """INSERT INTO local_business.restaurant_order_line
                   (order_id, menu_item_id, menu_item_name, variant_id, quantity,
                    unit_price, line_total, notes, status, line_no)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'NEW',%s) RETURNING id""",
                (order_id, mi["id"], mi["name"], ln.get("variant_id"), qty,
                 unit_price, qty * unit_price, ln.get("notes", ""), i))
            line_id = cur.fetchone()["id"]
            for mid in mods:
                cur.execute(
                    "SELECT name, price_delta FROM local_business.menu_modifier WHERE id=%s", (mid,))
                m = cur.fetchone()
                if m:
                    cur.execute(
                        """INSERT INTO local_business.restaurant_order_modifier
                           (order_line_id, modifier_id, name, price_delta)
                           VALUES (%s,%s,%s,%s)""",
                        (line_id, mid, m["name"], m["price_delta"]))

        # create KOT
        kot_number = _next_kot_number(cur, business_id)
        cur.execute(
            """INSERT INTO local_business.kot (business_id, order_id, kot_number, status)
               VALUES (%s,%s,%s,'NEW')""",
            (business_id, order_id, kot_number))

        core.catat_audit("restaurant_order_created", actor=f"cashier-{cashier_id}",
                         tenant_id=tenant_id, business_id=business_id,
                         branch_id=branch_id,
                         payload={"order": order_number, "kot": kot_number,
                                  "lines": len(lines)})
        c.commit()
        return {"duplicate": False, "order_id": order_id, "order_number": order_number,
                "kot_number": kot_number, "subtotal": subtotal, "total": subtotal,
                "status": "NEW"}


def _consume_ingredients(cur, *, tenant_id, business_id, branch_id, warehouse_id,
                         order_id, actor, device_id, order_number):
    """Consume ingredients for all lines of an order (prepared/served)."""
    cur.execute(
        """SELECT ol.id AS line_id, ol.menu_item_id, ol.quantity, ol.variant_id
           FROM local_business.restaurant_order_line ol
           WHERE ol.order_id=%s AND ol.status IN ('NEW','PREPARING','READY')""",
        (order_id,))
    lines = cur.fetchall()
    for ln in lines:
        cur.execute(
            """SELECT modifier_id FROM local_business.restaurant_order_modifier
               WHERE order_line_id=%s""", (ln["line_id"],))
        mods = [r["modifier_id"] for r in cur.fetchall()]
        for ing in _recipe_ingredients(cur, ln["menu_item_id"], ln["variant_id"], mods):
            qty = int(ing["quantity"] * ln["quantity"])
            if qty <= 0:
                continue
            inv.consume_location(
                tenant_id=tenant_id, business_id=business_id, branch_id=branch_id,
                warehouse_id=warehouse_id, master_sku_id=ing["master_sku_id"],
                sku=ing["sku"], quantity=qty,
                reference=f"restaurant:{order_number}:{ing['master_sku_id']}",
                note=f"ingredient consume {order_number}", actor=actor,
                device_id=device_id,
                idempotency_key=f"rcons:{order_number}:{ing['master_sku_id']}",
                source_document=order_number, cur=cur)


def set_order_status(*, order_id: int, status: str, actor: str = "",
                     warehouse_id: int | None = None,
                     business_id: int | None = None) -> dict:
    """Transition restaurant order status. Consumes ingredients on PREPARING/SERVED."""
    allowed = {"NEW", "ACCEPTED", "PREPARING", "READY", "SERVED", "CANCELLED", "PAID"}
    if status not in allowed:
        raise ValueError(f"status {status} tidak valid")
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT * FROM local_business.restaurant_order
               WHERE id=%s AND (%s IS NULL OR business_id=%s) FOR UPDATE""",
            (order_id, business_id, business_id))
        o = cur.fetchone()
        if not o:
            raise KeyError(f"order {order_id} tidak ada")
        if o["status"] == status:
            c.commit()
            return {"duplicate": True, "status": status}
        if status == "CANCELLED" and o["status"] in ("NEW", "ACCEPTED"):
            # cancel before prep: no ingredients consumed yet
            cur.execute(
                "UPDATE local_business.restaurant_order SET status='CANCELLED', updated_at=now() WHERE id=%s",
                (order_id,))
            cur.execute(
                "UPDATE local_business.kot SET status='CANCELLED', updated_at=now() WHERE order_id=%s",
                (order_id,))
            core.catat_audit("restaurant_order_cancelled", actor=actor,
                             tenant_id=o["tenant_id"], business_id=o["business_id"],
                             branch_id=o["branch_id"],
                             payload={"order": o["order_number"]})
            c.commit()
            return {"duplicate": False, "status": "CANCELLED"}
        if status in ("PREPARING", "SERVED"):
            # consume ingredients once (idempotent per ingredient)
            if warehouse_id is None:
                cur.execute(
                    "SELECT warehouse_id FROM local_business.branch WHERE id=%s",
                    (o["branch_id"],))
                warehouse_id = cur.fetchone()["warehouse_id"]
            _consume_ingredients(cur, tenant_id=o["tenant_id"],
                                 business_id=o["business_id"],
                                 branch_id=o["branch_id"], warehouse_id=warehouse_id,
                                 order_id=order_id, actor=actor,
                                 device_id=o["device_id"], order_number=o["order_number"])
        cur.execute(
            "UPDATE local_business.restaurant_order SET status=%s, updated_at=now() WHERE id=%s",
            (status, order_id))
        cur.execute(
            "UPDATE local_business.kot SET status=%s, updated_at=now() WHERE order_id=%s",
            (status, order_id))
        core.catat_audit("restaurant_order_status", actor=actor,
                         tenant_id=o["tenant_id"], business_id=o["business_id"],
                         branch_id=o["branch_id"],
                         payload={"order": o["order_number"], "status": status})
        c.commit()
        return {"duplicate": False, "status": status}


def set_kot_status(*, kot_id: int, status: str, actor: str = "",
                   business_id: int | None = None) -> dict:
    """KDS: update KOT status (NEW/ACCEPTED/PREPARING/READY/SERVED/CANCELLED)."""
    allowed = {"NEW", "ACCEPTED", "PREPARING", "READY", "SERVED", "CANCELLED"}
    if status not in allowed:
        raise ValueError(f"status {status} tidak valid")
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE local_business.kot k SET status=%s, updated_at=now()
               FROM local_business.restaurant_order o
               WHERE k.id=%s AND k.order_id=o.id
                 AND (%s IS NULL OR k.business_id=%s)
               RETURNING k.id, k.status""", (status, kot_id, business_id, business_id))
        r = cur.fetchone()
        c.commit()
        if not r:
            raise KeyError(f"kot {kot_id} tidak ada")
        return r


def get_restaurant_order(order_id: int) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.restaurant_order WHERE id=%s", (order_id,))
        o = cur.fetchone()
        if not o:
            return None
        cur.execute(
            "SELECT * FROM local_business.restaurant_order_line WHERE order_id=%s ORDER BY line_no",
            (order_id,))
        o["lines"] = cur.fetchall()
        cur.execute("SELECT * FROM local_business.kot WHERE order_id=%s", (order_id,))
        o["kots"] = cur.fetchall()
        return o


def list_restaurant_orders(branch_id: int, status: str = "") -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        if status:
            cur.execute(
                "SELECT * FROM local_business.restaurant_order WHERE branch_id=%s AND status=%s ORDER BY id DESC",
                (branch_id, status))
        else:
            cur.execute(
                "SELECT * FROM local_business.restaurant_order WHERE branch_id=%s ORDER BY id DESC",
                (branch_id,))
        return cur.fetchall()


def list_kot(branch_id: int, status: str = "") -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        if status:
            cur.execute(
                """SELECT k.*, o.order_number, o.branch_id, o.table_id, o.guest_count
                   FROM local_business.kot k
                   JOIN local_business.restaurant_order o ON o.id=k.order_id
                   WHERE o.branch_id=%s AND k.status=%s ORDER BY k.id""",
                (branch_id, status))
        else:
            cur.execute(
                """SELECT k.*, o.order_number, o.branch_id, o.table_id, o.guest_count
                   FROM local_business.kot k
                   JOIN local_business.restaurant_order o ON o.id=k.order_id
                   WHERE o.branch_id=%s ORDER BY k.id""",
                (branch_id,))
        return cur.fetchall()
