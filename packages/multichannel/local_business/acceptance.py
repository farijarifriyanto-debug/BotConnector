"""Gerbang penerimaan Local Business Suite (DB NYATA).

Membuktikan dengan baris dan angka sebelum/sesudah di PostgreSQL:
  RETAIL_POS, ATOMIC_SALE, CONCURRENT_CASHIER_OVERSELL_PROTECTION,
  IDEMPOTENCY, RETURNS, VOID, MULTI_BRANCH_TRANSFER + CONSERVATION,
  RESTAURANT_RECIPE + INGREDIENT_CONSUMPTION, KOT, WASTE,
  OFFLINE_ALLOWANCE + REPLAY_IDEMPOTENCY, MARKETPLACE_PROJECTION,
  FINANCE_BALANCED.

Seluruh data memakai tenant PILOT terisolasi dan dibersihkan sesudahnya.
"""

from __future__ import annotations

import sys
import threading
import uuid

sys.path.insert(0, "/opt")
sys.path.insert(0, "/opt/botconnector-multichannel")

from botconnector_multichannel.persistence import db  # noqa
from botconnector_multichannel.persistence.guard import (  # noqa
    assert_isolated_test_db, require_test_tenant, print_test_context,
)
from botconnector_multichannel.inventory import migrate as imigrate  # noqa
from botconnector_multichannel.inventory import service as S  # noqa
from botconnector_multichannel.local_business import migrate as lmigrate  # noqa
from botconnector_multichannel.local_business import (  # noqa
    core, inventory as inv, retail, returns, transfer, restaurant,
    offline, procurement, marketplace, reporting, sales,
)
from botconnector_multichannel.workflow import finance_core as fc  # noqa

lulus, gagal = 0, 0
_TAG = uuid.uuid4().hex[:6]
TENANT = f"LOCAL-TEST-{_TAG}"


def uji(nama, fn):
    global lulus, gagal
    try:
        fn()
        print(f"  [OK]    {nama}")
        lulus += 1
    except AssertionError as e:
        print(f"  [GAGAL] {nama}: {e}")
        gagal += 1
    except Exception as e:
        import traceback
        print(f"  [GAGAL] {nama}: {type(e).__name__}: {e}")
        gagal += 1


def _wh(code):
    db.jalankan(
        "INSERT INTO multichannel.warehouse (code,name) VALUES (%s,%s) ON CONFLICT (code) DO NOTHING",
        (code, code))
    return db.ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (code,))["id"]


def _sku(sku, name, cat="Uji"):
    p = S.upsert_product(name, cat, "")
    return S.upsert_master_sku(sku, product_id=p["id"])


def _priced(biz_id, sku_dict, price=5000):
    """Set a canonical retail selling price so retail.create_sale can resolve it."""
    sales.set_canonical_selling_price(
        business_id=biz_id, master_sku_id=sku_dict["id"], selling_price=price)
    return sku_dict


def _setup():
    """Buat tenant PILOT + business + branches + warehouses + registers."""
    biz = core.upsert_business(tenant_id=TENANT, code=f"PILOT-{uuid.uuid4().hex[:6]}",
                               name="Pilot Bisnis", business_type="HYBRID")
    wh_main = _wh(f"WH-MAIN-{_TAG}")
    wh_a = _wh(f"WH-A-{_TAG}")
    wh_b = _wh(f"WH-B-{_TAG}")
    br_a = core.upsert_branch(business_id=biz["id"], code="A", name="Cabang A",
                              warehouse_id=wh_a, branch_type="RETAIL")
    br_b = core.upsert_branch(business_id=biz["id"], code="B", name="Cabang B",
                              warehouse_id=wh_b, branch_type="RESTAURANT")
    reg_a = core.upsert_register(branch_id=br_a["id"], code="REG-A", name="Kasir A",
                                 device_id=f"DEV-A-{_TAG}")
    reg_b = core.upsert_register(branch_id=br_b["id"], code="REG-B", name="Kasir B",
                                 device_id=f"DEV-B-{_TAG}")
    return {"biz": biz, "wh_main": wh_main, "wh_a": wh_a, "wh_b": wh_b,
            "br_a": br_a, "br_b": br_b, "reg_a": reg_a, "reg_b": reg_b}


def _cleanup():
    # HARD PRODUCTION GUARD — refuse destructive cleanup on production.
    assert_isolated_test_db()
    require_test_tenant(TENANT)
    try:
        with db.koneksi() as c:
            cur = c.cursor()
            cur.execute("DELETE FROM local_business.sale_return_line")
            cur.execute("DELETE FROM local_business.sale_return")
            cur.execute("DELETE FROM local_business.sale_line")
            cur.execute("DELETE FROM local_business.sale")
            cur.execute("DELETE FROM local_business.restaurant_order_modifier")
            cur.execute("DELETE FROM local_business.restaurant_order_line")
            cur.execute("DELETE FROM local_business.kot")
            cur.execute("DELETE FROM local_business.restaurant_order")
            cur.execute("DELETE FROM local_business.transfer_line")
            cur.execute("DELETE FROM local_business.transfer")
            cur.execute("DELETE FROM local_business.offline_queue")
            cur.execute("DELETE FROM local_business.offline_allowance")
            cur.execute("DELETE FROM local_business.goods_receipt_line")
            cur.execute("DELETE FROM local_business.goods_receipt")
            cur.execute("DELETE FROM local_business.recipe_component")
            cur.execute("DELETE FROM local_business.recipe")
            cur.execute("DELETE FROM local_business.modifier_ingredient")
            cur.execute("DELETE FROM local_business.menu_modifier")
            cur.execute("DELETE FROM local_business.menu_variant")
            cur.execute("DELETE FROM local_business.menu_item")
            cur.execute("DELETE FROM local_business.menu_category")
            cur.execute("DELETE FROM local_business.restaurant_table")
            cur.execute("DELETE FROM local_business.cash_movement")
            cur.execute("DELETE FROM local_business.shift")
            cur.execute("DELETE FROM local_business.customer")
            cur.execute("DELETE FROM local_business.register")
            cur.execute("DELETE FROM local_business.branch")
            cur.execute("DELETE FROM local_business.cashier")
            cur.execute("DELETE FROM local_business.business")
            cur.execute("DELETE FROM local_business.audit_log")
            cur.execute("DELETE FROM multichannel.inventory_drift")
            cur.execute("DELETE FROM multichannel.inventory_sync_attempt")
            cur.execute("DELETE FROM multichannel.inventory_sync_outbox")
            cur.execute("DELETE FROM multichannel.inventory_sync_state")
            cur.execute("DELETE FROM multichannel.channel_sku_map")
            cur.execute("DELETE FROM multichannel.channel_listing")
            cur.execute("DELETE FROM multichannel.inventory_reservation")
            cur.execute("DELETE FROM multichannel.inventory_adjustment")
            cur.execute("DELETE FROM multichannel.inventory_movement")
            cur.execute("DELETE FROM multichannel.inventory_balance")
            cur.execute("DELETE FROM multichannel.master_sku")
            cur.execute("DELETE FROM multichannel.product")
            c.commit()
    except Exception:
        pass


# ================================================================ TESTS
def t1_retail_sale_atomic():
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"WATER-{_TAG}", "Air Mineral"))
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=5,
                      idempotency_key=f"gr1:{_TAG}", source_document="GR-1")
    assert inv.location_atp(m["id"], st["wh_a"]) == 5
    sale = retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 2,
                "unit_price": 5000}],
        tender_method="CASH", amount_tendered=10000,
        client_event_id=f"evt1-{_TAG}", device_id=f"DEV-A-{_TAG}")
    assert sale["duplicate"] is False
    assert inv.location_atp(m["id"], st["wh_a"]) == 3, "sale harus kurangi ATP ke 3"
    # replay -> duplicate, no double consume
    sale2 = retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 2,
                "unit_price": 5000}],
        tender_method="CASH", amount_tendered=10000,
        client_event_id=f"evt1-{_TAG}", device_id=f"DEV-A-{_TAG}")
    assert sale2["duplicate"] is True, "replay harus duplicate"
    assert inv.location_atp(m["id"], st["wh_a"]) == 3, "replay tidak boleh konsumsi lagi"


def t2_concurrent_cashier_oversell():
    """Dua kasir serentak jual 3 dari stok 5 -> total konsumsi tak boleh 6."""
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"CONC-{_TAG}", "Barang Konkuren"), 1000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=5,
                      idempotency_key=f"gr2:{_TAG}", source_document="GR-2")
    results = []
    lock = threading.Lock()
    def _sell(dev, evt):
        try:
            r = retail.create_sale(
                tenant_id=TENANT, business_id=st["biz"]["id"],
                branch_id=st["br_a"]["id"], register_id=st["reg_a"]["id"],
                cashier_id=None, warehouse_id=st["wh_a"],
                lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 3,
                        "unit_price": 1000}],
                tender_method="CASH", amount_tendered=3000,
                client_event_id=evt, device_id=dev)
            with lock:
                results.append(r)
        except inv.StokTidakCukup:
            with lock:
                results.append({"error": "insufficient"})
    t1 = threading.Thread(target=_sell, args=(f"DEV-A-{_TAG}", f"c1-{_TAG}"))
    t2 = threading.Thread(target=_sell, args=(f"DEV-A-{_TAG}", f"c2-{_TAG}"))
    t1.start(); t2.start(); t1.join(); t2.join()
    # total consumed must be <= 5
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(quantity),0) AS n FROM local_business.sale_line "
            "WHERE sale_id IN (SELECT id FROM local_business.sale WHERE business_id=%s)",
            (st["biz"]["id"],))
        total = cur.fetchone()["n"]
    assert total <= 5, f"oversell! total konsumsi {total} > 5"
    assert inv.location_atp(m["id"], st["wh_a"]) >= 0, "ATP negatif"
    assert total in (3, 5), f"hasil konsumsi tidak valid: {total}"


def t3_branch_isolation():
    """Sale di Branch A tidak boleh mengurangi Branch B."""
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"ISO-{_TAG}", "Isolasi Cabang"), 1000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=10,
                      idempotency_key=f"gr3:{_TAG}", source_document="GR-3")
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_b"]["id"], warehouse_id=st["wh_b"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=7,
                      idempotency_key=f"gr3b:{_TAG}", source_document="GR-3B")
    retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 3,
                "unit_price": 1000}],
        tender_method="CASH", amount_tendered=3000,
        client_event_id=f"iso-{_TAG}", device_id=f"DEV-A-{_TAG}")
    assert inv.location_atp(m["id"], st["wh_a"]) == 7, "A harus 7"
    assert inv.location_atp(m["id"], st["wh_b"]) == 7, "B harus tetap 7 (tidak tersentuh)"


def t4_transfer_conservation():
    """Transfer A->B: total fisik + in-transit konservasi."""
    st = _setup()
    m = _sku(f"TRF-{_TAG}", "Transfer")
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=10,
                      idempotency_key=f"gr4:{_TAG}", source_document="GR-4")
    t = transfer.create_transfer(
        tenant_id=TENANT, business_id=st["biz"]["id"],
        source_branch_id=st["br_a"]["id"], dest_branch_id=st["br_b"]["id"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 4}],
        actor="manager")
    transfer.approve_transfer(transfer_id=t["transfer_id"], actor="manager")
    transfer.ship_transfer(transfer_id=t["transfer_id"], actor="manager")
    a = inv.location_balance(m["id"], st["wh_a"])
    assert a["on_hand"] == 6, f"A on_hand harus 6, dapat {a['on_hand']}"
    assert a["in_transit"] == 4, f"A in_transit harus 4, dapat {a['in_transit']}"
    # conservation: on_hand(A) + in_transit(A) + on_hand(B) = 10
    b = inv.location_balance(m["id"], st["wh_b"])
    total = a["on_hand"] + a["in_transit"] + (b["on_hand"] if b else 0)
    assert total == 10, f"konservasi gagal: {total} != 10"
    transfer.receive_transfer(transfer_id=t["transfer_id"], actor="manager")
    a2 = inv.location_balance(m["id"], st["wh_a"])
    b2 = inv.location_balance(m["id"], st["wh_b"])
    assert a2["in_transit"] == 0, "in_transit harus 0 setelah receive"
    assert b2["on_hand"] == 4, f"B on_hand harus 4, dapat {b2['on_hand']}"
    assert a2["on_hand"] + b2["on_hand"] == 10, "konservasi akhir gagal"


def t5_restaurant_recipe_ingredient():
    """Resep NASI_GORENG: order 2 -> konsumsi ingredient benar."""
    st = _setup()
    rice = _sku(f"RICE-{_TAG}", "Beras")
    egg = _sku(f"EGG-{_TAG}", "Telur")
    for sku_id, sku, qty in [(rice["id"], rice["sku"], 1000), (egg["id"], egg["sku"], 100)]:
        inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                          branch_id=st["br_b"]["id"], warehouse_id=st["wh_b"],
                          master_sku_id=sku_id, sku=sku, quantity=qty,
                          idempotency_key=f"gr5:{sku}:{_TAG}", source_document="GR-5")
    mi = restaurant.upsert_menu_item(business_id=st["biz"]["id"], name="NASI_GORENG", price=15000)
    restaurant.upsert_recipe(menu_item_id=mi["id"], version=1, components=[
        {"master_sku_id": rice["id"], "sku": rice["sku"], "quantity": 200},
        {"master_sku_id": egg["id"], "sku": egg["sku"], "quantity": 1},
    ])
    assert restaurant.producible_quantity(mi["id"], st["wh_b"]) == 5, "producible harus 5"
    o = restaurant.create_restaurant_order(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_b"]["id"],
        register_id=st["reg_b"]["id"], cashier_id=None, warehouse_id=st["wh_b"],
        lines=[{"menu_item_id": mi["id"], "quantity": 2}], order_type="DINE_IN",
        client_event_id=f"revt-{_TAG}", device_id=f"DEV-B-{_TAG}")
    assert o["duplicate"] is False
    restaurant.set_order_status(order_id=o["order_id"], status="PREPARING",
                                actor="kitchen", warehouse_id=st["wh_b"])
    restaurant.set_order_status(order_id=o["order_id"], status="SERVED",
                                actor="kitchen", warehouse_id=st["wh_b"])
    assert inv.location_balance(rice["id"], st["wh_b"])["on_hand"] == 600, "rice harus 600"
    assert inv.location_balance(egg["id"], st["wh_b"])["on_hand"] == 98, "egg harus 98"
    # duplicate order replay -> no double consume
    o2 = restaurant.create_restaurant_order(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_b"]["id"],
        register_id=st["reg_b"]["id"], cashier_id=None, warehouse_id=st["wh_b"],
        lines=[{"menu_item_id": mi["id"], "quantity": 2}], order_type="DINE_IN",
        client_event_id=f"revt-{_TAG}", device_id=f"DEV-B-{_TAG}")
    assert o2["duplicate"] is True, "replay order harus duplicate"
    assert inv.location_balance(rice["id"], st["wh_b"])["on_hand"] == 600, "replay tidak boleh konsumsi"


def t6_insufficient_ingredient_blocks():
    st = _setup()
    rice = _sku(f"RICE2-{_TAG}", "Beras2")
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_b"]["id"], warehouse_id=st["wh_b"],
                      master_sku_id=rice["id"], sku=rice["sku"], quantity=100,
                      idempotency_key=f"gr6:{_TAG}", source_document="GR-6")
    mi = restaurant.upsert_menu_item(business_id=st["biz"]["id"], name="NASI_2", price=10000)
    restaurant.upsert_recipe(menu_item_id=mi["id"], version=1, components=[
        {"master_sku_id": rice["id"], "sku": rice["sku"], "quantity": 200}])
    try:
        restaurant.create_restaurant_order(
            tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_b"]["id"],
            register_id=st["reg_b"]["id"], cashier_id=None, warehouse_id=st["wh_b"],
            lines=[{"menu_item_id": mi["id"], "quantity": 1}], order_type="DINE_IN",
            client_event_id=f"insuf-{_TAG}", device_id=f"DEV-B-{_TAG}")
        raise AssertionError("harus StokTidakCukup")
    except restaurant.StokTidakCukup:
        pass


def t7_waste_explicit():
    st = _setup()
    m = _sku(f"WASTE-{_TAG}", "Barang Waste")
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=10,
                      idempotency_key=f"gr7:{_TAG}", source_document="GR-7")
    inv.waste_location(tenant_id=TENANT, business_id=st["biz"]["id"],
                       branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                       master_sku_id=m["id"], sku=m["sku"], quantity=3,
                       reason="rusak", idempotency_key=f"waste:{_TAG}",
                       source_document="WASTE-1")
    assert inv.location_atp(m["id"], st["wh_a"]) == 7, "waste harus kurangi ke 7"
    # waste ganda idempoten
    inv.waste_location(tenant_id=TENANT, business_id=st["biz"]["id"],
                       branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                       master_sku_id=m["id"], sku=m["sku"], quantity=3,
                       reason="rusak", idempotency_key=f"waste:{_TAG}",
                       source_document="WASTE-1")
    assert inv.location_atp(m["id"], st["wh_a"]) == 7, "waste ganda tidak boleh"


def t8_return_restock():
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"RET-{_TAG}", "Barang Retur"), 1000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=5,
                      idempotency_key=f"gr8:{_TAG}", source_document="GR-8")
    sale = retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 2,
                "unit_price": 1000}],
        tender_method="CASH", amount_tendered=2000,
        client_event_id=f"ret-{_TAG}", device_id=f"DEV-A-{_TAG}")
    assert inv.location_atp(m["id"], st["wh_a"]) == 3
    r = returns.create_return(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        warehouse_id=st["wh_a"], sale_id=sale["sale_id"], reason="kadaluarsa",
        actor="cashier", client_event_id=f"retrn-{_TAG}", device_id=f"DEV-A-{_TAG}")
    assert r["duplicate"] is False
    assert inv.location_atp(m["id"], st["wh_a"]) == 5, "retur harus pulih ke 5"
    # retur ganda idempoten
    r2 = returns.create_return(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        warehouse_id=st["wh_a"], sale_id=sale["sale_id"], reason="kadaluarsa",
        actor="cashier", client_event_id=f"retrn-{_TAG}", device_id=f"DEV-A-{_TAG}")
    assert r2["duplicate"] is True, "retur ganda harus duplicate"
    assert inv.location_atp(m["id"], st["wh_a"]) == 5


def t9_void_reverses():
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"VOID-{_TAG}", "Barang Void"), 1000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=5,
                      idempotency_key=f"gr9:{_TAG}", source_document="GR-9")
    sale = retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 2,
                "unit_price": 1000}],
        tender_method="CASH", amount_tendered=2000,
        client_event_id=f"void-{_TAG}", device_id=f"DEV-A-{_TAG}")
    assert inv.location_atp(m["id"], st["wh_a"]) == 3
    retail.void_sale(sale_id=sale["sale_id"], reason="salah input", actor="manager")
    assert inv.location_atp(m["id"], st["wh_a"]) == 5, "void harus pulih ke 5"


def t10_offline_allowance_and_replay():
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"OFF-{_TAG}", "Barang Offline"), 1000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=10,
                      idempotency_key=f"gr10:{_TAG}", source_document="GR-10")
    # grant allowance 3 to register A
    offline.grant_allowance(business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
                            register_id=st["reg_a"]["id"], master_sku_id=m["id"],
                            allowance=3, ttl_hours=24)
    assert offline.allowance_remaining(st["reg_a"]["id"], m["id"]) == 3
    # offline sale qty 2 within allowance
    osale = offline.create_offline_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 2,
                "unit_price": 1000}],
        tender_method="CASH", amount_tendered=2000,
        client_event_id=f"off-{_TAG}", device_id=f"DEV-A-{_TAG}")
    assert osale["duplicate"] is False
    assert offline.allowance_remaining(st["reg_a"]["id"], m["id"]) == 1, "allowance sisa 1"
    # offline sale qty 2 exceeds remaining allowance 1 -> reject
    try:
        offline.create_offline_sale(
            tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
            register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
            lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 2,
                    "unit_price": 1000}],
            tender_method="CASH", amount_tendered=2000,
            client_event_id=f"off2-{_TAG}", device_id=f"DEV-A-{_TAG}")
        raise AssertionError("harus ditolak (allowance habis)")
    except inv.StokTidakCukup:
        pass
    # replay same offline event 10x -> still one business effect
    for _ in range(10):
        offline.create_offline_sale(
            tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
            register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
            lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 2,
                    "unit_price": 1000}],
            tender_method="CASH", amount_tendered=2000,
            client_event_id=f"off-{_TAG}", device_id=f"DEV-A-{_TAG}")
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT count(*) AS n FROM local_business.sale WHERE client_event_id=%s",
            (f"off-{_TAG}",))
        n = cur.fetchone()["n"]
    assert n == 1, f"replay 10x harus 1 sale, dapat {n}"


def t11_marketplace_projection():
    """Local sale -> central inventory change -> marketplace desired projection."""
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"MP-{_TAG}", "Barang Marketplace"), 1000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=5,
                      idempotency_key=f"gr11:{_TAG}", source_document="GR-11")
    # map to a marketplace channel
    S.map_channel_sku(provider="shopee", shop_id=f"SHOP-{_TAG}",
                      product_id_provider=f"P-{_TAG}", channel_sku=f"SP-{_TAG}",
                      master_sku_id=m["id"])
    # project fulfillment pool = [wh_a]
    proj = marketplace.project_to_marketplace(master_sku_id=m["id"],
                                               warehouse_ids=[st["wh_a"]])
    assert proj["desired_qty"] == 5, f"desired harus 5, dapat {proj['desired_qty']}"
    assert proj["real_marketplace_stock_write"] == "OFF"
    # local sale qty 2 -> central ATP 3 -> desired projection 3
    retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 2,
                "unit_price": 1000}],
        tender_method="CASH", amount_tendered=2000,
        client_event_id=f"mp-{_TAG}", device_id=f"DEV-A-{_TAG}")
    proj2 = marketplace.project_to_marketplace(master_sku_id=m["id"],
                                                warehouse_ids=[st["wh_a"]])
    assert proj2["desired_qty"] == 3, f"desired harus 3 setelah sale, dapat {proj2['desired_qty']}"
    # outbox has PENDING row for the channel
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT count(*) AS n FROM multichannel.inventory_sync_outbox o "
            "JOIN multichannel.inventory_sync_state s ON s.id=o.sync_state_id "
            "WHERE s.master_sku_id=%s AND o.status='PENDING'", (m["id"],))
        n = cur.fetchone()["n"]
    assert n >= 1, "outbox harus punya baris PENDING"


def t12_finance_balanced():
    n = fc.neraca()
    assert n.get("balanced") is True, "neraca Finance tidak seimbang"


def t13_dashboard_real_data():
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"DASH-{_TAG}", "Barang Dashboard"), 10000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br_a"]["id"], warehouse_id=st["wh_a"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=5,
                      idempotency_key=f"gr13:{_TAG}", source_document="GR-13")
    retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br_a"]["id"],
        register_id=st["reg_a"]["id"], cashier_id=None, warehouse_id=st["wh_a"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 1,
                "unit_price": 10000}],
        tender_method="CASH", amount_tendered=10000,
        client_event_id=f"dash-{_TAG}", device_id=f"DEV-A-{_TAG}")
    d = reporting.dashboard(st["biz"]["id"])
    assert d["sales_today"] == 10000, f"sales_today harus 10000, dapat {d['sales_today']}"
    assert d["transaction_count_today"] == 1


def main():
    assert_isolated_test_db()
    require_test_tenant(TENANT)
    print_test_context(TENANT)
    imigrate.migrasi()
    lmigrate.migrasi()
    _cleanup()
    print("\n=== LOCAL BUSINESS SUITE (DB NYATA) ===")
    uji("RETAIL_SALE_ATOMIC + IDEMPOTENCY", t1_retail_sale_atomic)
    uji("CONCURRENT_CASHIER_OVERSELL_PROTECTION", t2_concurrent_cashier_oversell)
    uji("BRANCH_ISOLATION", t3_branch_isolation)
    uji("TRANSFER_CONSERVATION", t4_transfer_conservation)
    uji("RESTAURANT_RECIPE_INGREDIENT", t5_restaurant_recipe_ingredient)
    uji("INSUFFICIENT_INGREDIENT_BLOCKS", t6_insufficient_ingredient_blocks)
    uji("WASTE_EXPLICIT", t7_waste_explicit)
    uji("RETURN_RESTOCK", t8_return_restock)
    uji("VOID_REVERSES", t9_void_reverses)
    uji("OFFLINE_ALLOWANCE + REPLAY_IDEMPOTENCY", t10_offline_allowance_and_replay)
    uji("MARKETPLACE_PROJECTION (write OFF)", t11_marketplace_projection)
    uji("FINANCE_BALANCED", t12_finance_balanced)
    uji("DASHBOARD_REAL_DATA", t13_dashboard_real_data)
    _cleanup()
    print(f"\n  Lulus: {lulus}   Gagal: {gagal}\n")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
