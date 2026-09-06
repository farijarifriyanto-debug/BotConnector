"""Skenario penerimaan end-to-end Local Business Suite (tenant disposable).

Menjalankan skenario realistis 10 langkah dari misi (bagian 28):
  1. receive stock
  2. retail sale
  3. restaurant recipe sale
  4. concurrent sale test
  5. branch transfer
  6. cancellation
  7. return
  8. waste
  9. offline transaction
  10. restore sync

Lalu menunjukkan kuantitas akhir dan membuktikan konservasi.

SAFETY: skenario destruktif ini WAJIB berjalan di database acceptance
terisolasi. Shared production guard (persistence.guard) memeriksa identitas
database dan menolak bila menyentuh production. Tenant memakai nilai disposable
LOCAL-TEST-<tag>, BUKAN production tenant LOCAL-PILOT.
"""

from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, "/opt")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from botconnector_multichannel.persistence import db  # noqa
from botconnector_multichannel.persistence.guard import (  # noqa
    assert_isolated_test_db, require_test_tenant, print_test_context,
    GuardError,
)
from botconnector_multichannel.inventory import migrate as imigrate  # noqa
from botconnector_multichannel.inventory import service as S  # noqa
from botconnector_multichannel.local_business import migrate as lmigrate  # noqa
from botconnector_multichannel.local_business import (  # noqa
    core, inventory as inv, retail, returns, transfer, restaurant,
    offline, procurement, marketplace, sales,
)
from botconnector_multichannel.workflow import finance_core as fc  # noqa

_TAG = uuid.uuid4().hex[:6]
TENANT = f"LOCAL-TEST-{_TAG}"


def _wh(code):
    db.jalankan(
        "INSERT INTO multichannel.warehouse (code,name) VALUES (%s,%s) ON CONFLICT (code) DO NOTHING",
        (code, code))
    return db.ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (code,))["id"]


def _sku(sku, name, cat):
    p = S.upsert_product(name, cat, "")
    return S.upsert_master_sku(sku, product_id=p["id"])


def _cleanup():
    # HARD PRODUCTION GUARD — refuse destructive cleanup on production.
    assert_isolated_test_db()
    require_test_tenant(TENANT)
    try:
        with db.koneksi() as c:
            cur = c.cursor()
            for t in ["sale_finance", "restaurant_finance", "receipt_finance",
                      "sale_return_line", "sale_return", "sale_line", "sale",
                      "restaurant_order_modifier", "restaurant_order_line", "kot",
                      "restaurant_order", "transfer_line", "transfer", "offline_queue",
                      "offline_allowance", "goods_receipt_line", "goods_receipt",
                      "recipe_component", "recipe", "modifier_ingredient", "menu_modifier",
                      "menu_variant", "menu_item", "menu_category", "restaurant_table",
                      "cash_movement", "shift", "customer", "register", "branch",
                      "cashier", "business", "audit_log"]:
                cur.execute(f"DELETE FROM local_business.{t}")
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
            for seq in ["sale_receipt_seq", "restaurant_order_seq", "transfer_seq",
                        "return_seq", "goods_receipt_seq", "kot_seq"]:
                cur.execute("SELECT setval('local_business.%s', 1, false)" % seq)
            c.commit()
    except Exception:
        pass


def main():
    assert_isolated_test_db()
    require_test_tenant(TENANT)
    print_test_context(TENANT)
    imigrate.migrasi()
    lmigrate.migrasi()
    _cleanup()

    print("\n=== SKENARIO PENERIMAAN LOCAL BUSINESS (10 LANGKAH) ===\n")

    # ---- setup ----
    biz = core.upsert_business(tenant_id=TENANT, code="PILOT", name="Pilot Bisnis",
                               business_type="HYBRID")
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

    water = _sku(f"WATER-600-{_TAG}", "Air Mineral", "Minuman")
    sales.set_canonical_selling_price(
        business_id=biz["id"], master_sku_id=water["id"], selling_price=5000)
    egg = _sku(f"EGG-{_TAG}", "Telur", "Bahan")
    rice = _sku(f"RICE-{_TAG}", "Beras", "Bahan")
    chicken = _sku(f"CHICKEN-{_TAG}", "Ayam", "Bahan")
    oil = _sku(f"OIL-{_TAG}", "Minyak", "Bahan")

    # ---- 1. receive stock ----
    inv.receive_stock(tenant_id=TENANT, business_id=biz["id"], branch_id=br_a["id"],
                      warehouse_id=wh_a, master_sku_id=water["id"], sku=water["sku"],
                      quantity=20, idempotency_key=f"1:{_TAG}", source_document="GR-1")
    for sku_id, sku, qty in [(egg["id"], egg["sku"], 50), (rice["id"], rice["sku"], 10000),
                             (chicken["id"], chicken["sku"], 5000), (oil["id"], oil["sku"], 5000)]:
        inv.receive_stock(tenant_id=TENANT, business_id=biz["id"], branch_id=br_b["id"],
                          warehouse_id=wh_b, master_sku_id=sku_id, sku=sku, quantity=qty,
                          idempotency_key=f"1b:{sku}:{_TAG}", source_document="GR-1B")
    print(f"[1] receive: WATER-600@A={inv.location_atp(water['id'], wh_a)}")

    # ---- 2. retail sale ----
    s1 = retail.create_sale(
        tenant_id=TENANT, business_id=biz["id"], branch_id=br_a["id"],
        register_id=reg_a["id"], cashier_id=None, warehouse_id=wh_a,
        lines=[{"master_sku_id": water["id"], "sku": water["sku"], "quantity": 2,
                "unit_price": 5000}],
        tender_method="CASH", amount_tendered=10000,
        client_event_id=f"2:{_TAG}", device_id=f"DEV-A-{_TAG}")
    print(f"[2] retail sale {s1['receipt_number']} total={s1['total']} -> WATER-600@A={inv.location_atp(water['id'], wh_a)}")

    # ---- 3. restaurant recipe sale ----
    mi = restaurant.upsert_menu_item(business_id=biz["id"], name="NASI_GORENG", price=15000)
    restaurant.upsert_recipe(menu_item_id=mi["id"], version=1, components=[
        {"master_sku_id": rice["id"], "sku": rice["sku"], "quantity": 200},
        {"master_sku_id": egg["id"], "sku": egg["sku"], "quantity": 1},
        {"master_sku_id": chicken["id"], "sku": chicken["sku"], "quantity": 50},
        {"master_sku_id": oil["id"], "sku": oil["sku"], "quantity": 15},
    ])
    o = restaurant.create_restaurant_order(
        tenant_id=TENANT, business_id=biz["id"], branch_id=br_b["id"],
        register_id=reg_b["id"], cashier_id=None, warehouse_id=wh_b,
        lines=[{"menu_item_id": mi["id"], "quantity": 2}], order_type="DINE_IN",
        client_event_id=f"3:{_TAG}", device_id=f"DEV-B-{_TAG}")
    restaurant.set_order_status(order_id=o["order_id"], status="PREPARING",
                                actor="kitchen", warehouse_id=wh_b)
    restaurant.set_order_status(order_id=o["order_id"], status="SERVED",
                                actor="kitchen", warehouse_id=wh_b)
    print(f"[3] restaurant order {o['order_number']} -> rice@B={inv.location_balance(rice['id'], wh_b)['on_hand']} (10000-400)")

    # ---- 4. concurrent sale test ----
    results = []
    lock = threading.Lock()
    def _sell(dev, evt):
        try:
            r = retail.create_sale(
                tenant_id=TENANT, business_id=biz["id"], branch_id=br_a["id"],
                register_id=reg_a["id"], cashier_id=None, warehouse_id=wh_a,
                lines=[{"master_sku_id": water["id"], "sku": water["sku"], "quantity": 3,
                        "unit_price": 5000}],
                tender_method="CASH", amount_tendered=15000,
                client_event_id=evt, device_id=dev)
            with lock:
                results.append(r)
        except inv.StokTidakCukup:
            with lock:
                results.append({"error": "insufficient"})
    t1 = threading.Thread(target=_sell, args=(f"DEV-A-{_TAG}", f"4a:{_TAG}"))
    t2 = threading.Thread(target=_sell, args=(f"DEV-A-{_TAG}", f"4b:{_TAG}"))
    t1.start(); t2.start(); t1.join(); t2.join()
    print(f"[4] concurrent 2x3 dari stok {inv.location_atp(water['id'], wh_a)+6} -> hasil={[r.get('receipt_number','insufficient') for r in results]}")

    # ---- 5. branch transfer ----
    t = transfer.create_transfer(
        tenant_id=TENANT, business_id=biz["id"], source_branch_id=br_a["id"],
        dest_branch_id=br_b["id"],
        lines=[{"master_sku_id": water["id"], "sku": water["sku"], "quantity": 5}],
        actor="manager")
    transfer.approve_transfer(transfer_id=t["transfer_id"], actor="manager")
    transfer.ship_transfer(transfer_id=t["transfer_id"], actor="manager")
    transfer.receive_transfer(transfer_id=t["transfer_id"], actor="manager")
    print(f"[5] transfer {t['transfer_number']} -> A={inv.location_balance(water['id'], wh_a)['on_hand']} B={inv.location_balance(water['id'], wh_b)['on_hand']}")

    # ---- 6. cancellation (transfer draft) ----
    t2 = transfer.create_transfer(
        tenant_id=TENANT, business_id=biz["id"], source_branch_id=br_a["id"],
        dest_branch_id=br_b["id"],
        lines=[{"master_sku_id": water["id"], "sku": water["sku"], "quantity": 2}],
        actor="manager")
    transfer.cancel_transfer(transfer_id=t2["transfer_id"], actor="manager")
    print(f"[6] cancel transfer {t2['transfer_number']} -> status={transfer.get_transfer(t2['transfer_id'])['status']}")

    # ---- 7. return ----
    s2 = retail.create_sale(
        tenant_id=TENANT, business_id=biz["id"], branch_id=br_a["id"],
        register_id=reg_a["id"], cashier_id=None, warehouse_id=wh_a,
        lines=[{"master_sku_id": water["id"], "sku": water["sku"], "quantity": 1,
                "unit_price": 5000}],
        tender_method="CASH", amount_tendered=5000,
        client_event_id=f"7:{_TAG}", device_id=f"DEV-A-{_TAG}")
    r = returns.create_return(
        tenant_id=TENANT, business_id=biz["id"], branch_id=br_a["id"],
        warehouse_id=wh_a, sale_id=s2["sale_id"], reason="kadaluarsa",
        actor="cashier", client_event_id=f"7r:{_TAG}", device_id=f"DEV-A-{_TAG}")
    print(f"[7] return {r['return_number']} refund={r['total_refund']} -> WATER-600@A={inv.location_atp(water['id'], wh_a)}")

    # ---- 8. waste ----
    inv.waste_location(tenant_id=TENANT, business_id=biz["id"], branch_id=br_b["id"],
                       warehouse_id=wh_b, master_sku_id=egg["id"], sku=egg["sku"],
                       quantity=2, reason="pecah", idempotency_key=f"8:{_TAG}",
                       source_document="WASTE-1")
    print(f"[8] waste egg 2 -> egg@B={inv.location_balance(egg['id'], wh_b)['on_hand']} (50-2)")

    # ---- 9. offline transaction ----
    offline.grant_allowance(business_id=biz["id"], branch_id=br_a["id"],
                            register_id=reg_a["id"], master_sku_id=water["id"],
                            allowance=3, ttl_hours=24)
    osale = offline.create_offline_sale(
        tenant_id=TENANT, business_id=biz["id"], branch_id=br_a["id"],
        register_id=reg_a["id"], cashier_id=None, warehouse_id=wh_a,
        lines=[{"master_sku_id": water["id"], "sku": water["sku"], "quantity": 2,
                "unit_price": 5000}],
        tender_method="CASH", amount_tendered=10000,
        client_event_id=f"9:{_TAG}", device_id=f"DEV-A-{_TAG}")
    print(f"[9] offline sale {osale['receipt_number']} -> WATER-600@A={inv.location_atp(water['id'], wh_a)}")

    # ---- 10. restore sync (replay offline queue) ----
    offline.enqueue_offline_event(
        tenant_id=TENANT, business_id=biz["id"], branch_id=br_a["id"],
        register_id=reg_a["id"], device_id=f"DEV-A-{_TAG}",
        client_event_id=f"10:{_TAG}", event_type="SALE",
        payload={"lines": [{"master_sku_id": water["id"], "sku": water["sku"],
                            "quantity": 1, "unit_price": 5000}],
                 "tender_method": "CASH", "amount_tendered": 5000})
    wmap = {br_a["id"]: wh_a, br_b["id"]: wh_b}
    sync = offline.replay_offline_queue(biz["id"], warehouse_map=wmap)
    print(f"[10] sync replay -> {sync}")

    # ---- final quantities + conservation ----
    print("\n=== KUANTITAS AKHIR ===")
    print(f"WATER-600: A on_hand={inv.location_balance(water['id'], wh_a)['on_hand']} "
          f"B on_hand={inv.location_balance(water['id'], wh_b)['on_hand']} "
          f"in_transit={inv.location_balance(water['id'], wh_a)['in_transit']}")
    print(f"RICE@B={inv.location_balance(rice['id'], wh_b)['on_hand']} "
          f"EGG@B={inv.location_balance(egg['id'], wh_b)['on_hand']} "
          f"CHICKEN@B={inv.location_balance(chicken['id'], wh_b)['on_hand']} "
          f"OIL@B={inv.location_balance(oil['id'], wh_b)['on_hand']}")

    # conservation: WATER-600 total = 20 (received) - sales + returns
    # sold: step2=2, step4=6 (2x3 both succeeded), step7=1, step9=2, step10=1 => 12
    # returned: step7=1
    # transferred 5 to B (A on_hand -5, B on_hand +5, in_transit 0)
    # A on_hand + B on_hand + in_transit = 20 - 12 + 1 = 9
    a_oh = inv.location_balance(water["id"], wh_a)["on_hand"]
    b_oh = inv.location_balance(water["id"], wh_b)["on_hand"]
    it = inv.location_balance(water["id"], wh_a)["in_transit"]
    total_water = a_oh + b_oh + it
    print(f"\nKONSERVASI WATER-600: A({a_oh}) + B({b_oh}) + in_transit({it}) = {total_water}")
    assert total_water == 9, f"konservasi gagal: {total_water} != 9"

    # finance balanced
    n = fc.neraca()
    print(f"FINANCE: balanced={n.get('balanced')} diff={n.get('totals',{}).get('difference')}")
    assert n.get("balanced") is True

    print("\nSKENARIO 10 LANGKAH SELESAI — konservasi & finance terbukti.")
    _cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
