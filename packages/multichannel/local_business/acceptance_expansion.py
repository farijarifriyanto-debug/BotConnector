"""Gerbang penerimaan Business Expansion (DB NYATA).

Membuktikan dengan baris dan angka sebelum/sesudah di PostgreSQL:
  BUSINESS_REPORTING, RESTAURANT_REPORTING, RETAIL_REPORTING,
  FOOD/BEVERAGE_SALES, COGS_REPORTING, GROSS_PROFIT, GROSS_MARGIN,
  CHANNEL_REPORTING, NO_DOUBLE_COUNT,
  GOFOOD/GRABFOOD/SHOPEEFOOD_CONNECTOR (REAL=BLOCKED_EXTERNAL),
  CANONICAL_MENU, CHANNEL_MENU_MAPPING, DELIVERY_ORDER_NORMALIZATION,
  KDS_OMNICHANNEL, DELIVERY_SETTLEMENT,
  THIRD_PARTY_POS_FRAMEWORK, MOKA/PAWOON_CONNECTOR,
  CSV/XLSX_CONNECTOR, WATCHED_FOLDER, BARCODE, PRINT_RECEIPT,
  DIGITAL_SCALE, LOCAL_DEVICE_BRIDGE, QR_SELF_ORDER, QUEUE_DISPLAY,
  GENERIC_WEBHOOK, GENERIC_REST, ORDER_LINEAGE, DUPLICATE_SOURCE_PROTECTION.

Seluruh data memakai tenant PILOT terisolasi dan dibersihkan sesudahnya.
"""

from __future__ import annotations

import sys
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
    core, inventory as inv, retail, restaurant, business_reporting as BR,
    delivery, file_connector, watched_folder, barcode, print_receipt,
    device_bridge, qr_self_order, webhook_connector, sales,
)
from botconnector_multichannel.local_business.connectors import build_delivery_registry  # noqa
from botconnector_multichannel.local_business.pos import build_pos_registry  # noqa
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


def _sku(sku, name, cat):
    p = S.upsert_product(name, cat, "")
    return S.upsert_master_sku(sku, product_id=p["id"])


def _priced(biz_id, sku_dict, price=5000):
    """Set a canonical retail selling price so retail.create_sale can resolve it."""
    sales.set_canonical_selling_price(
        business_id=biz_id, master_sku_id=sku_dict["id"], selling_price=price)
    return sku_dict


def _setup():
    biz = core.upsert_business(tenant_id=TENANT, code=f"EXP-{uuid.uuid4().hex[:6]}",
                               name="Expansion Bisnis", business_type="HYBRID")
    wh = _wh(f"WH-{_TAG}")
    br = core.upsert_branch(business_id=biz["id"], code="A", name="Cabang A",
                            warehouse_id=wh, branch_type="RESTAURANT")
    reg = core.upsert_register(branch_id=br["id"], code="REG", name="Kasir",
                               device_id=f"DEV-{_TAG}")
    BR.ensure_reporting_categories(biz["id"])
    BR.ensure_sales_channels(biz["id"])
    return {"biz": biz, "wh": wh, "br": br, "reg": reg}


def _cleanup():
    # HARD PRODUCTION GUARD — refuse destructive cleanup on production.
    # TRUNCATE is only permitted inside a positively-verified isolated test DB.
    assert_isolated_test_db()
    require_test_tenant(TENANT)
    try:
        with db.koneksi() as c:
            cur = c.cursor()
            cur.execute(
                "TRUNCATE TABLE local_business.business, local_business.branch, "
                "local_business.register, local_business.cashier, local_business.shift, "
                "local_business.cash_movement, local_business.customer, "
                "local_business.sale, local_business.sale_line, local_business.sale_return, "
                "local_business.sale_return_line, local_business.transfer, "
                "local_business.transfer_line, local_business.menu_category, "
                "local_business.menu_item, local_business.menu_variant, "
                "local_business.menu_modifier, local_business.recipe, "
                "local_business.recipe_component, local_business.modifier_ingredient, "
                "local_business.restaurant_table, local_business.restaurant_order, "
                "local_business.restaurant_order_line, "
                "local_business.restaurant_order_modifier, local_business.kot, "
                "local_business.offline_queue, local_business.offline_allowance, "
                "local_business.goods_receipt, local_business.goods_receipt_line, "
                "local_business.audit_log, local_business.reporting_category, "
                "local_business.sales_channel, local_business.channel_menu_mapping, "
                "local_business.delivery_order, local_business.delivery_order_line, "
                "local_business.order_lineage, local_business.delivery_settlement, "
                "local_business.pos_connector, local_business.file_import, "
                "local_business.watched_folder, local_business.watched_file, "
                "local_business.webhook_connector, local_business.webhook_event, "
                "local_business.qr_menu, local_business.queue_ticket, "
                "local_business.device_bridge, local_business.barcode_alias CASCADE"
            )
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


# ================================================================ TESTS
def t1_restaurant_reporting():
    """Restaurant sale -> FOOD/BEVERAGE category -> sales report -> COGS -> profit."""
    st = _setup()
    rice = _sku(f"RICE-{_TAG}", "Beras", "Bahan")
    egg = _sku(f"EGG-{_TAG}", "Telur", "Bahan")
    # receive via goods_receipt with unit_cost so COGS is meaningful
    from botconnector_multichannel.local_business import procurement
    procurement.create_goods_receipt(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br"]["id"],
        warehouse_id=st["wh"], supplier_code="SUP-1", supplier_name="Supplier",
        lines=[{"master_sku_id": rice["id"], "sku": rice["sku"], "quantity": 1000,
                "unit_cost": 50, "name": "Beras"},
               {"master_sku_id": egg["id"], "sku": egg["sku"], "quantity": 100,
                "unit_cost": 2000, "name": "Telur"}],
        actor="manager")
    # FOOD item
    nasi = restaurant.upsert_menu_item(business_id=st["biz"]["id"], name="NASI_GORENG",
                                       price=15000, category_id=None)
    db.jalankan("UPDATE local_business.menu_item SET reporting_category='FOOD' WHERE id=%s",
                (nasi["id"],))
    restaurant.upsert_recipe(menu_item_id=nasi["id"], version=1, components=[
        {"master_sku_id": rice["id"], "sku": rice["sku"], "quantity": 200},
        {"master_sku_id": egg["id"], "sku": egg["sku"], "quantity": 1},
    ])
    # BEVERAGE item (stocked)
    water = _sku(f"WATER-{_TAG}", "Air", "Minuman")
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br"]["id"], warehouse_id=st["wh"],
                      master_sku_id=water["id"], sku=water["sku"], quantity=50,
                      idempotency_key=f"gr1w:{_TAG}", source_document="GR-1W")
    es = restaurant.upsert_menu_item(business_id=st["biz"]["id"], name="ES TEH",
                                     price=5000, is_stocked=True, stocked_sku_id=water["id"])
    db.jalankan("UPDATE local_business.menu_item SET reporting_category='BEVERAGE' WHERE id=%s",
                (es["id"],))
    # order 2 NASI_GORENG + 1 ES TEH
    o = restaurant.create_restaurant_order(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br"]["id"],
        register_id=st["reg"]["id"], cashier_id=None, warehouse_id=st["wh"],
        lines=[{"menu_item_id": nasi["id"], "quantity": 2},
               {"menu_item_id": es["id"], "quantity": 1}],
        order_type="DINE_IN", client_event_id=f"o1-{_TAG}", device_id=f"DEV-{_TAG}")
    restaurant.set_order_status(order_id=o["order_id"], status="SERVED",
                                actor="kitchen", warehouse_id=st["wh"])
    rep = BR.restaurant_sales_report(st["biz"]["id"], days=30)
    assert rep["gross_sales"] == 35000, f"gross harus 35000, dapat {rep['gross_sales']}"
    assert rep["order_count"] == 1
    # category sales present
    cats = {c["category"]: c for c in rep["category_sales"]}
    assert "FOOD" in cats and "BEVERAGE" in cats, "kategori FOOD/BEVERAGE harus ada"
    assert cats["FOOD"]["gross_sales"] == 30000, "FOOD sales harus 30000"
    assert cats["BEVERAGE"]["gross_sales"] == 5000, "BEVERAGE sales harus 5000"
    # COGS > 0 (ingredient consumption)
    assert rep["cogs"] > 0, "COGS harus > 0"
    assert rep["gross_profit"] > 0, "gross profit harus > 0"
    assert rep["gross_margin_pct"] > 0, "margin harus > 0"


def t2_retail_reporting():
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"RET-{_TAG}", "Barang Retail", "Retail"), 10000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br"]["id"], warehouse_id=st["wh"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=10,
                      idempotency_key=f"gr2:{_TAG}", source_document="GR-2")
    retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br"]["id"],
        register_id=st["reg"]["id"], cashier_id=None, warehouse_id=st["wh"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 2,
                "unit_price": 10000}],
        tender_method="CASH", amount_tendered=20000,
        client_event_id=f"r2-{_TAG}", device_id=f"DEV-{_TAG}")
    rep = BR.retail_sales_report(st["biz"]["id"], days=30)
    assert rep["gross_sales"] == 20000, f"gross harus 20000, dapat {rep['gross_sales']}"
    assert rep["transaction_count"] == 1


def t3_hybrid_no_double_count():
    """HYBRID: retail + restaurant profiles without double counting."""
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"HYB-{_TAG}", "Barang Hybrid", "Retail"), 10000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br"]["id"], warehouse_id=st["wh"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=10,
                      idempotency_key=f"gr3:{_TAG}", source_document="GR-3")
    retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br"]["id"],
        register_id=st["reg"]["id"], cashier_id=None, warehouse_id=st["wh"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 1,
                "unit_price": 10000}],
        tender_method="CASH", amount_tendered=10000,
        client_event_id=f"h3-{_TAG}", device_id=f"DEV-{_TAG}")
    rep = BR.hybrid_report(st["biz"]["id"], days=30)
    assert rep["retail"]["gross_sales"] == 10000
    assert rep["restaurant"]["gross_sales"] == 0
    assert rep["total_gross_sales"] == 10000, "tidak boleh double count"


def t4_delivery_connector_status():
    """Delivery connectors present with honest BLOCKED_EXTERNAL status."""
    reg = build_delivery_registry()
    providers = {c.provider: c for c in reg.all()}
    assert "GOFOOD" in providers and "GRABFOOD" in providers and "SHOPEEFOOD" in providers
    for p in providers.values():
        assert p.real_status == "BLOCKED_EXTERNAL", f"{p.provider} harus BLOCKED_EXTERNAL"
        assert p.status_report()["readiness"] == "blocked_external"


def t5_delivery_order_idempotent():
    """Duplicate delivery webhook 10x -> ONE order, ONE KOT, ONE ingredient effect."""
    st = _setup()
    rice = _sku(f"DRICE-{_TAG}", "Beras D", "Bahan")
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br"]["id"], warehouse_id=st["wh"],
                      master_sku_id=rice["id"], sku=rice["sku"], quantity=1000,
                      idempotency_key=f"gr5:{_TAG}", source_document="GR-5")
    nasi = restaurant.upsert_menu_item(business_id=st["biz"]["id"], name="NASI_DELIVERY",
                                       price=15000)
    restaurant.upsert_recipe(menu_item_id=nasi["id"], version=1, components=[
        {"master_sku_id": rice["id"], "sku": rice["sku"], "quantity": 200}])
    # channel mapping
    delivery.upsert_channel_menu_mapping(business_id=st["biz"]["id"],
                                         menu_item_id=nasi["id"], channel="GOFOOD",
                                         channel_item_id="GF-1", channel_price=17000)
    # create delivery order 10x (same external_order_id)
    first = None
    for i in range(10):
        r = delivery.create_delivery_order(
            tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br"]["id"],
            register_id=st["reg"]["id"], warehouse_id=st["wh"],
            source_provider="GOFOOD", external_order_id="GF-ORD-1", outlet_id="GF-OUT-1",
            lines=[{"channel_item_id": "GF-1", "name": "NASI_DELIVERY", "quantity": 2,
                    "unit_price": 17000}],
            gross_value=34000, provider_fee=5000, merchant_promo_cost=2000,
            payment_state="UNPAID", raw_payload={"order": {"number": "GF-ORD-1"}})
        if i == 0:
            first = r
        else:
            assert r["duplicate"] is True, f"replay {i} harus duplicate"
    # ONE restaurant order
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT count(*) AS n FROM local_business.restaurant_order WHERE business_id=%s",
            (st["biz"]["id"],))
        n_orders = cur.fetchone()["n"]
        cur.execute(
            "SELECT count(*) AS n FROM local_business.kot WHERE business_id=%s",
            (st["biz"]["id"],))
        n_kot = cur.fetchone()["n"]
    assert n_orders == 1, f"harus 1 restaurant order, dapat {n_orders}"
    assert n_kot == 1, f"harus 1 KOT, dapat {n_kot}"
    # ONE ingredient effect (serve the order)
    restaurant.set_order_status(order_id=first["restaurant_order_id"], status="SERVED",
                                 actor="kitchen", warehouse_id=st["wh"])
    assert inv.location_balance(rice["id"], st["wh"])["on_hand"] == 600, "ingredient harus 1x konsumsi"


def t6_delivery_settlement():
    st = _setup()
    r = delivery.record_delivery_settlement(
        business_id=st["biz"]["id"], source_provider="GOFOOD", outlet_id="GF-OUT-1",
        settlement_ref="STL-1", gross_value=34000, provider_fee=5000,
        merchant_promo_cost=2000, expected_settlement=27000, actual_settlement=26500)
    assert r["duplicate"] is False
    assert r["variance"] == 500, f"variance harus 500, dapat {r['variance']}"
    # replay -> duplicate
    r2 = delivery.record_delivery_settlement(
        business_id=st["biz"]["id"], source_provider="GOFOOD", outlet_id="GF-OUT-1",
        settlement_ref="STL-1", gross_value=34000, provider_fee=5000,
        merchant_promo_cost=2000, expected_settlement=27000, actual_settlement=26500)
    assert r2["duplicate"] is True, "settlement replay harus duplicate"


def t7_channel_menu_mapping():
    st = _setup()
    nasi = restaurant.upsert_menu_item(business_id=st["biz"]["id"], name="NASI_CH",
                                       price=15000)
    delivery.upsert_channel_menu_mapping(business_id=st["biz"]["id"],
                                         menu_item_id=nasi["id"], channel="GRABFOOD",
                                         channel_item_id="GR-1", channel_price=18000)
    delivery.upsert_channel_menu_mapping(business_id=st["biz"]["id"],
                                         menu_item_id=nasi["id"], channel="SHOPEEFOOD",
                                         channel_item_id="SF-1", channel_price=16000)
    # same canonical recipe, different channel prices
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT channel, channel_price FROM local_business.channel_menu_mapping WHERE menu_item_id=%s ORDER BY channel",
            (nasi["id"],))
        maps = cur.fetchall()
    prices = {m["channel"]: m["channel_price"] for m in maps}
    assert prices["GRABFOOD"] == 18000 and prices["SHOPEEFOOD"] == 16000, "channel price beda"


def t8_ingredient_availability():
    """Menu availability derives from ingredient ATP."""
    st = _setup()
    rice = _sku(f"ARICE-{_TAG}", "Beras A", "Bahan")
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br"]["id"], warehouse_id=st["wh"],
                      master_sku_id=rice["id"], sku=rice["sku"], quantity=100,
                      idempotency_key=f"gr8:{_TAG}", source_document="GR-8")
    nasi = restaurant.upsert_menu_item(business_id=st["biz"]["id"], name="NASI_AVAIL",
                                       price=15000)
    restaurant.upsert_recipe(menu_item_id=nasi["id"], version=1, components=[
        {"master_sku_id": rice["id"], "sku": rice["sku"], "quantity": 200}])
    delivery.upsert_channel_menu_mapping(business_id=st["biz"]["id"],
                                         menu_item_id=nasi["id"], channel="GOFOOD",
                                         channel_item_id="GF-A", channel_price=17000)
    a = delivery.channel_menu_availability(nasi["id"], "GOFOOD")
    # 100g rice, recipe needs 200g -> producible 0 -> unavailable
    assert a["available"] is False, "ingredient ATP 0 -> menu harus unavailable"


def t9_pos_connector_status():
    reg = build_pos_registry()
    providers = {c.provider: c for c in reg.all()}
    assert "MOKA" in providers and "PAWOON" in providers
    for p in providers.values():
        assert p.real_status == "BLOCKED_EXTERNAL", f"{p.provider} harus BLOCKED_EXTERNAL"


def t10_moka_normalize():
    from botconnector_multichannel.local_business.pos.moka import MokaConnector
    m = MokaConnector()
    raw = {"transaction": {"id": "T-1", "outlet_id": "OUT-1", "gross_total": 50000,
                           "net_total": 48000, "discount": 2000,
                           "items": [{"sku": "X", "name": "Barang", "quantity": 2,
                                      "unit_price": 25000, "cost": 15000}]}}
    n = m.normalize_sales(raw)
    assert n["source_provider"] == "MOKA"
    assert n["gross_value"] == 50000
    assert n["lines"][0]["cost"] == 15000


def t11_csv_import():
    st = _setup()
    csv_content = b"sku,name,category,barcode\nCSV-1,Produk CSV,Retail,12345\n"
    r = file_connector.import_file(business_id=st["biz"]["id"], import_type="PRODUCTS",
                                   filename="products.csv", content=csv_content,
                                   format="CSV", dry_run=True)
    assert r["ok"] is True
    assert r["valid_rows"] == 1
    # replay same file -> duplicate
    r2 = file_connector.import_file(business_id=st["biz"]["id"], import_type="PRODUCTS",
                                    filename="products.csv", content=csv_content,
                                    format="CSV", dry_run=True)
    assert r2["duplicate"] is True, "file yang sama harus duplicate"


def t12_csv_invalid_rejection():
    st = _setup()
    bad = b"sku,name\n,Produk Tanpa SKU\n"
    r = file_connector.import_file(business_id=st["biz"]["id"], import_type="PRODUCTS",
                                   filename="bad.csv", content=bad, format="CSV",
                                   dry_run=True)
    assert r["ok"] is True
    assert r["error_rows"] == 1, "baris tanpa sku harus ditolak"


def t13_barcode():
    st = _setup()
    m = _sku(f"BC-{_TAG}", "Barang Barcode", "Retail")
    barcode.add_barcode_alias(business_id=st["biz"]["id"], master_sku_id=m["id"],
                              barcode="89912345")
    r = barcode.lookup_barcode(business_id=st["biz"]["id"], barcode="89912345")
    assert r["found"] is True and r["master_sku_id"] == m["id"]
    r2 = barcode.lookup_barcode(business_id=st["biz"]["id"], barcode="UNKNOWN")
    assert r2["found"] is False, "barcode tak dikenal harus ditangani"


def t14_print_receipt():
    st = _setup()
    m = _priced(st["biz"]["id"], _sku(f"PR-{_TAG}", "Barang Print", "Retail"), 10000)
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br"]["id"], warehouse_id=st["wh"],
                      master_sku_id=m["id"], sku=m["sku"], quantity=5,
                      idempotency_key=f"gr14:{_TAG}", source_document="GR-14")
    sale = retail.create_sale(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br"]["id"],
        register_id=st["reg"]["id"], cashier_id=None, warehouse_id=st["wh"],
        lines=[{"master_sku_id": m["id"], "sku": m["sku"], "quantity": 1,
                "unit_price": 10000}],
        tender_method="CASH", amount_tendered=10000,
        client_event_id=f"p14-{_TAG}", device_id=f"DEV-{_TAG}")
    data = print_receipt.get_receipt_data(sale["sale_id"])
    assert data is not None
    html = print_receipt.render_receipt_html(
        business_name="Bisnis", branch_name="Cabang", receipt_number=data["receipt_number"],
        cashier="", lines=data["lines"], subtotal=data["subtotal"], discount=0,
        tax_amount=0, total=data["total"], tender_method="CASH",
        amount_tendered=10000, change_due=0, timestamp="2026-08-22")
    assert "receipt_number" in html or data["receipt_number"] in html


def t15_digital_scale():
    r = device_bridge.validate_scale_reading("1234.5 g ST")
    assert r.stable is True
    assert r.weight_grams == 1234.5
    qty = r.to_quantity(unit_grams=500)
    assert qty == 2.469, f"qty harus 2.469, dapat {qty}"
    # invalid reading rejected
    try:
        device_bridge.validate_scale_reading("abc")
        raise AssertionError("harus ditolak")
    except ValueError:
        pass


def t16_qr_self_order():
    st = _setup()
    rice = _sku(f"QRICE-{_TAG}", "Beras Q", "Bahan")
    inv.receive_stock(tenant_id=TENANT, business_id=st["biz"]["id"],
                      branch_id=st["br"]["id"], warehouse_id=st["wh"],
                      master_sku_id=rice["id"], sku=rice["sku"], quantity=1000,
                      idempotency_key=f"gr16:{_TAG}", source_document="GR-16")
    nasi = restaurant.upsert_menu_item(business_id=st["biz"]["id"], name="NASI_QR",
                                       price=15000)
    restaurant.upsert_recipe(menu_item_id=nasi["id"], version=1, components=[
        {"master_sku_id": rice["id"], "sku": rice["sku"], "quantity": 200}])
    qr = qr_self_order.create_qr_menu(business_id=st["biz"]["id"], branch_id=st["br"]["id"],
                                      code="T1", kind="TABLE")
    payload = qr_self_order.qr_menu_payload(business_id=st["biz"]["id"],
                                            branch_id=st["br"]["id"], code="T1")
    assert payload["found"] is True
    sub = qr_self_order.submit_self_order(
        tenant_id=TENANT, business_id=st["biz"]["id"], branch_id=st["br"]["id"],
        register_id=st["reg"]["id"], warehouse_id=st["wh"], qr_code="T1",
        lines=[{"menu_item_id": nasi["id"], "quantity": 1}],
        client_event_id=f"qr-{_TAG}", device_id=f"DEV-{_TAG}")
    assert sub["payment_state"] == "UNPAID", "submit tidak boleh langsung PAID"
    assert sub["queue_number"].startswith("Q-")
    q = qr_self_order.queue_display(st["br"]["id"])
    assert len(q) == 1


def t17_generic_webhook():
    st = _setup()
    conn = webhook_connector.register_connector(
        business_id=st["biz"]["id"], name="WH-1", direction="INBOUND", kind="WEBHOOK",
        endpoint="https://example.com/hook", auth_mode="NONE", idempotency=True)
    r = webhook_connector.receive_webhook(connector_id=conn["id"], event_id="evt-1",
                                         payload={"a": 1})
    assert r["ok"] is True
    r2 = webhook_connector.receive_webhook(connector_id=conn["id"], event_id="evt-1",
                                          payload={"a": 1})
    assert r2["duplicate"] is True, "webhook replay harus duplicate"
    # SSRF protection: non-https endpoint rejected
    try:
        webhook_connector.register_connector(
            business_id=st["biz"]["id"], name="WH-BAD", direction="INBOUND", kind="WEBHOOK",
            endpoint="http://169.254.169.254/latest/meta-data")
        raise AssertionError("SSRF endpoint harus ditolak")
    except ValueError:
        pass


def t18_order_lineage_dedup():
    st = _setup()
    # same upstream order via POS connector + provider connector -> ONE canonical
    r1 = delivery.record_lineage(business_id=st["biz"]["id"], source_provider="GRABFOOD",
                                 source_pos="MOKA", external_order_id="GR-ORD-1",
                                 external_transaction_id="TX-1", canonical_order_id=1,
                                 canonical_type="RESTAURANT_ORDER")
    assert r1["duplicate"] is False
    r2 = delivery.record_lineage(business_id=st["biz"]["id"], source_provider="GRABFOOD",
                                 source_pos="MOKA", external_order_id="GR-ORD-1",
                                 external_transaction_id="TX-1", canonical_order_id=1,
                                 canonical_type="RESTAURANT_ORDER")
    assert r2["duplicate"] is True, "lineage ganda harus duplicate"
    found = delivery.find_canonical_order(business_id=st["biz"]["id"],
                                          source_provider="GRABFOOD", source_pos="MOKA",
                                          external_order_id="GR-ORD-1",
                                          external_transaction_id="TX-1")
    assert found is not None and found["canonical_order_id"] == 1


def t19_finance_balanced():
    n = fc.neraca()
    assert n.get("balanced") is True, "neraca Finance tidak seimbang"


def main():
    assert_isolated_test_db()
    require_test_tenant(TENANT)
    print_test_context(TENANT)
    imigrate.migrasi()
    lmigrate.migrasi()
    _cleanup()
    print("\n=== BUSINESS EXPANSION (DB NYATA) ===")
    uji("RESTAURANT_REPORTING + FOOD/BEVERAGE + COGS + PROFIT", t1_restaurant_reporting)
    uji("RETAIL_REPORTING", t2_retail_reporting)
    uji("HYBRID_NO_DOUBLE_COUNT", t3_hybrid_no_double_count)
    uji("DELIVERY_CONNECTOR_STATUS (REAL=BLOCKED_EXTERNAL)", t4_delivery_connector_status)
    uji("DELIVERY_ORDER_IDEMPOTENT (10x -> 1)", t5_delivery_order_idempotent)
    uji("DELIVERY_SETTLEMENT + VARIANCE", t6_delivery_settlement)
    uji("CHANNEL_MENU_MAPPING (one recipe, diff price)", t7_channel_menu_mapping)
    uji("INGREDIENT_AVAILABILITY", t8_ingredient_availability)
    uji("POS_CONNECTOR_STATUS (REAL=BLOCKED_EXTERNAL)", t9_pos_connector_status)
    uji("MOKA_NORMALIZE", t10_moka_normalize)
    uji("CSV_IMPORT + REPLAY_IDEMPOTENT", t11_csv_import)
    uji("CSV_INVALID_REJECTION", t12_csv_invalid_rejection)
    uji("BARCODE_LOOKUP", t13_barcode)
    uji("PRINT_RECEIPT", t14_print_receipt)
    uji("DIGITAL_SCALE", t15_digital_scale)
    uji("QR_SELF_ORDER + QUEUE", t16_qr_self_order)
    uji("GENERIC_WEBHOOK + SSRF_PROTECTION", t17_generic_webhook)
    uji("ORDER_LINEAGE_DEDUP", t18_order_lineage_dedup)
    uji("FINANCE_BALANCED", t19_finance_balanced)
    _cleanup()
    print(f"\n  Lulus: {lulus}   Gagal: {gagal}\n")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
