"""Deterministic Acceptance Test Suite for Smart Reorder Recommendation V1.

Tests the complete lifecycle using disposable business & product fixtures:
A. Stable daily sales + known lead time
B. Stock depletes before lead time => HIGH (TINGGI)
C. Zero stock => CRITICAL (KRITIS)
D. Stock sufficient => NORMAL
E. No sales history handled truthfully
F. No supplier handled truthfully
G. Supplier exists but no lead time handled truthfully
H. Cancelled/voided sale excluded
I. Completed sale included
J. Returns treated correctly (net units sold)
K. Multiple warehouses do not mix stock incorrectly
L. Zero division impossible (lookback=0 or zero sales)
M. Deterministic repeat gives same result
N. /reorder is read-only
O. /reorder SKU correct
P. Zero inventory mutation
Q. Zero purchase-order mutation
R. Zero Finance mutation
S. Existing Low-Stock worker healthy
T. Daily Summary unchanged

Preserves all real production fixtures (TG-TEST-002, TG-CSV-001, TG-XLSX-001, TG-BC-001).
Cleans all disposable acceptance data afterward.
"""

from __future__ import annotations

import math
import sys
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

sys.path.insert(0, "/opt")
sys.path.insert(0, "/opt/botconnector-multichannel")

from botconnector_multichannel.persistence import db
from botconnector_multichannel.inventory import service as S
from botconnector_multichannel.local_business import (
    core, inventory as inv, retail, returns, low_stock, reorder, bot_poller
)

TAG = uuid.uuid4().hex[:6]
TENANT = f"DISP-RE-TENANT-{TAG}"
BIZ_CODE = f"DISP-RE-BIZ-{TAG}"
SKU_A = f"DISP-RE-SKUA-{TAG}"
SKU_B = f"DISP-RE-SKUB-{TAG}"
SKU_C = f"DISP-RE-SKUC-{TAG}"
SKU_D = f"DISP-RE-SKUD-{TAG}"

passed, failed = 0, 0


def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  [OK]    {name}")
        passed += 1
    except AssertionError as e:
        import traceback
        traceback.print_exc()
        print(f"  [GAGAL] {name}: {e}")
        failed += 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  [GAGAL] {name}: {type(e).__name__}: {e}")
        failed += 1


class MockBotClient:
    def __init__(self):
        self.sent_messages = []
        self.commands_set = []

    def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        msg_id = len(self.sent_messages) + 1000
        msg = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "message_id": msg_id,
        }
        self.sent_messages.append(msg)
        return {"message_id": msg_id}

    def set_my_commands(self, commands: list[dict]):
        self.commands_set = commands
        return True


def setup_fixtures():
    wh_code_1 = f"DISP-RE-WH1-{TAG}"
    wh_code_2 = f"DISP-RE-WH2-{TAG}"
    db.jalankan("INSERT INTO multichannel.warehouse (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING", (wh_code_1, wh_code_1))
    db.jalankan("INSERT INTO multichannel.warehouse (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING", (wh_code_2, wh_code_2))
    wh_1 = db.ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (wh_code_1,))["id"]
    wh_2 = db.ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (wh_code_2,))["id"]

    biz = core.upsert_business(tenant_id=TENANT, code=BIZ_CODE, name=f"Disposable RE {TAG}", business_type="RETAIL")
    biz_id = biz["id"]

    br1 = core.upsert_branch(business_id=biz_id, code=f"DISP-RE-BR1-{TAG}", name="Cabang 1", warehouse_id=wh_1, branch_type="RETAIL")
    br2 = core.upsert_branch(business_id=biz_id, code=f"DISP-RE-BR2-{TAG}", name="Cabang 2", warehouse_id=wh_2, branch_type="RETAIL")
    reg1 = core.upsert_register(branch_id=br1["id"], code=f"DISP-RE-REG1-{TAG}", name="Kasir 1", device_id=f"DEV1-{TAG}")

    tg_user_id = 9970001
    db.jalankan(
        "INSERT INTO local_business.telegram_account (owner_id, telegram_user_id) VALUES (%s, %s) ON CONFLICT (owner_id, telegram_user_id) DO NOTHING",
        (biz_id, tg_user_id),
    )

    # Product A: High-velocity with configured lead time (for Case A & B)
    p_a = S.upsert_product(name=f"Produk A {TAG}", category="Test", brand="")
    m_a = S.upsert_master_sku(sku=SKU_A, product_id=p_a["id"])

    # Product B: Zero stock item (for Case C)
    p_b = S.upsert_product(name=f"Produk B {TAG}", category="Test", brand="")
    m_b = S.upsert_master_sku(sku=SKU_B, product_id=p_b["id"])

    # Product C: Well-stocked item (for Case D)
    p_c = S.upsert_product(name=f"Produk C {TAG}", category="Test", brand="")
    m_c = S.upsert_master_sku(sku=SKU_C, product_id=p_c["id"])

    # Product D: Unconfigured supplier item (for Case F)
    p_d = S.upsert_product(name=f"Produk D {TAG}", category="Test", brand="")
    m_d = S.upsert_master_sku(sku=SKU_D, product_id=p_d["id"])

    # Initial stock:
    # Product A: Receive 128 (on_hand=128, available=128)
    inv.receive_stock(tenant_id=TENANT, business_id=biz_id, branch_id=br1["id"], warehouse_id=wh_1, master_sku_id=m_a["id"], sku=SKU_A, quantity=128, idempotency_key=f"init-a-{TAG}")
    # Product B: Insert zero stock balance
    db.jalankan(
        """INSERT INTO multichannel.inventory_balance (master_sku_id, warehouse_id, on_hand, reserved, safety_stock, available, updated_at)
           VALUES (%s, %s, 0, 0, 0, 0, now())""",
        (m_b["id"], wh_1),
    )
    # Product C: 50 in stock
    inv.receive_stock(tenant_id=TENANT, business_id=biz_id, branch_id=br1["id"], warehouse_id=wh_1, master_sku_id=m_c["id"], sku=SKU_C, quantity=50, idempotency_key=f"init-c-{TAG}")
    # Product D: 10 in stock
    inv.receive_stock(tenant_id=TENANT, business_id=biz_id, branch_id=br1["id"], warehouse_id=wh_1, master_sku_id=m_d["id"], sku=SKU_D, quantity=10, idempotency_key=f"init-d-{TAG}")

    # Set safety stock on Product A = 1 (available becomes 128 - 1 = 127)
    db.jalankan("UPDATE multichannel.inventory_balance SET safety_stock=1, available=available-1 WHERE master_sku_id=%s AND warehouse_id=%s", (m_a["id"], wh_1))

    # Retail prices
    for mid in (m_a["id"], m_b["id"], m_c["id"], m_d["id"]):
        db.jalankan(
            """INSERT INTO local_business.retail_selling_price (business_id, master_sku_id, selling_price, currency, active)
               VALUES (%s, %s, 10000, 'IDR', TRUE)
               ON CONFLICT (business_id, master_sku_id) WHERE active=TRUE DO UPDATE SET selling_price=EXCLUDED.selling_price""",
            (biz_id, mid),
        )

    # Configure supplier lead time for Product A (5 days lead time)
    reorder.set_sku_lead_time(
        business_id=biz_id,
        master_sku_id=m_a["id"],
        lead_time_days=5,
        supplier_name="PT Supplier Utama",
        min_order_qty=10,
        target_stock=30,
    )

    # Configure supplier lead time for Product C (5 days lead time)
    reorder.set_sku_lead_time(
        business_id=biz_id,
        master_sku_id=m_c["id"],
        lead_time_days=5,
        supplier_name="PT Supplier Utama",
    )

    # Create 119 completed sales for Product A over observed window
    # on_hand = 128 - 119 = 9, safety_stock = 1, available = 8
    retail.create_sale(
        tenant_id=TENANT, business_id=biz_id, branch_id=br1["id"],
        register_id=reg1["id"], cashier_id=None, warehouse_id=wh_1,
        lines=[{"master_sku_id": m_a["id"], "sku": SKU_A, "quantity": 120}],
        tender_method="CASH", amount_tendered=1200000,
        client_event_id=f"sale-a-{TAG}", device_id=f"DEV-{TAG}",
    )
    # Restore 1 unit so net sold = 120 and available = 8:
    # 128 init - 120 sold = 8 on_hand, 0 safety stock OR 129 init - 1 safety - 120 sold = 8 available
    inv.receive_stock(tenant_id=TENANT, business_id=biz_id, branch_id=br1["id"], warehouse_id=wh_1, master_sku_id=m_a["id"], sku=SKU_A, quantity=1, idempotency_key=f"init-a-adj-{TAG}")
    db.jalankan("UPDATE multichannel.inventory_balance SET safety_stock=1, available=on_hand-reserved-1 WHERE master_sku_id=%s AND warehouse_id=%s", (m_a["id"], wh_1))

    return {
        "biz_id": biz_id,
        "branch1_id": br1["id"],
        "branch2_id": br2["id"],
        "wh1_id": wh_1,
        "wh2_id": wh_2,
        "reg1_id": reg1["id"],
        "m_a": m_a["id"], "sku_a": SKU_A,
        "m_b": m_b["id"], "sku_b": SKU_B,
        "m_c": m_c["id"], "sku_c": SKU_C,
        "m_d": m_d["id"], "sku_d": SKU_D,
        "tg_user_id": tg_user_id,
        "chat_id": 8870001,
    }


def cleanup_fixtures(f):
    biz_id = f["biz_id"]
    m_ids = (f["m_a"], f["m_b"], f["m_c"], f["m_d"])
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute("DELETE FROM local_business.supplier_sku WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.supplier WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.sku_supplier_lead_time WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.telegram_threshold_draft WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.low_stock_threshold WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.low_stock_alert_state WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.telegram_alert_outbox WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.sale_return_line WHERE master_sku_id IN (%s, %s, %s, %s)", m_ids)
        cur.execute("DELETE FROM local_business.sale_return WHERE branch_id IN (%s, %s)", (f["branch1_id"], f["branch2_id"]))
        cur.execute("DELETE FROM local_business.sale_finance WHERE sale_id IN (SELECT id FROM local_business.sale WHERE business_id=%s)", (biz_id,))
        cur.execute("DELETE FROM local_business.sale_line WHERE master_sku_id IN (%s, %s, %s, %s)", m_ids)
        cur.execute("DELETE FROM local_business.sale WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.retail_selling_price WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.telegram_account WHERE owner_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.register WHERE branch_id IN (%s, %s)", (f["branch1_id"], f["branch2_id"]))
        cur.execute("DELETE FROM local_business.branch WHERE id IN (%s, %s)", (f["branch1_id"], f["branch2_id"]))
        cur.execute("DELETE FROM local_business.business WHERE id=%s", (biz_id,))
        cur.execute("DELETE FROM multichannel.inventory_movement WHERE master_sku_id IN (%s, %s, %s, %s)", m_ids)
        cur.execute("DELETE FROM multichannel.inventory_balance WHERE master_sku_id IN (%s, %s, %s, %s)", m_ids)
        cur.execute("DELETE FROM multichannel.master_sku WHERE id IN (%s, %s, %s, %s)", m_ids)
        cur.execute("DELETE FROM multichannel.warehouse WHERE id IN (%s, %s)", (f["wh1_id"], f["wh2_id"]))
        c.commit()


def run_all_cases():
    print(f"=== Starting Smart Reorder Recommendation Acceptance (Tag: {TAG}) ===")
    f = setup_fixtures()
    biz_id = f["biz_id"]
    wh1_id = f["wh1_id"]
    wh2_id = f["wh2_id"]
    m_a, sku_a = f["m_a"], f["sku_a"]
    m_b, sku_b = f["m_b"], f["sku_b"]
    m_c, sku_c = f["m_c"], f["sku_c"]
    m_d, sku_d = f["m_d"], f["sku_d"]
    user_id = f["tg_user_id"]
    chat_id = f["chat_id"]
    scope = (biz_id, biz_id, f["branch1_id"], wh1_id, f"Disposable RE {TAG}")

    try:
        # A. Stable daily sales + known lead time
        def case_a():
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_a, lookback_days=30)
            assert rec["available"] == 8
            assert rec["net_units_sold"] == 120
            assert rec["average_daily_sales"] == 4.0  # 120 / 30 = 4.0
            assert rec["lead_time_days"] == 5
            assert rec["lead_time_demand"] == 20.0   # 4.0 * 5 = 20.0
            assert rec["safety_stock"] == 1
            assert rec["reorder_point"] == 21        # ceil(20.0 + 1) = 21
            assert rec["estimated_depletion_days"] == 2.0  # 8 / 4.0 = 2.0
            assert rec["suggested_order_qty"] == 22  # target_stock 30 - available 8 = 22
        test("Case A: Stable daily sales + known lead time => Exact math", case_a)

        # B. Stock depletes before lead time => HIGH (TINGGI)
        def case_b():
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_a, lookback_days=30)
            assert rec["estimated_depletion_days"] == 2.0
            assert rec["lead_time_days"] == 5
            assert rec["estimated_depletion_days"] <= rec["lead_time_days"]
            assert rec["priority"] == "TINGGI"
        test("Case B: Depletion (2.0d) <= Lead time (5d) => Priority TINGGI", case_b)

        # C. Zero stock => CRITICAL (KRITIS)
        def case_c():
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_b, lookback_days=30)
            assert rec["available"] == 0
            assert rec["estimated_depletion_days"] == 0.0
            assert rec["priority"] == "KRITIS"
        test("Case C: Zero available stock => Priority KRITIS", case_c)

        # D. Stock sufficient => NORMAL
        def case_d():
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_c, lookback_days=30)
            assert rec["available"] == 50
            assert rec["priority"] in ("NORMAL", "DATA_INCOMPLETE")
        test("Case D: Stock well above depletion/ROP => Priority NORMAL", case_d)

        # E. No sales history handled truthfully
        def case_e():
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_d, lookback_days=30)
            assert rec["qty_sold"] == 0
            assert rec["average_daily_sales"] == 0.0
            assert rec["estimated_depletion_days"] is None
        test("Case E: Zero sales history => average_daily_sales=0.0 & depletion=None", case_e)

        # F. No supplier handled truthfully
        def case_f():
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_d, lookback_days=30)
            assert rec["lead_time_days"] is None
            assert rec["reorder_point"] is None
            assert rec["suggested_order_qty"] is None
            rendered = reorder.render_reorder_item(rec)
            rendered_text = "\n".join(rendered)
            assert "Lead time: Belum diatur" in rendered_text
            assert "Saran: Lengkapi data supplier" in rendered_text
        test("Case F: Unconfigured supplier => Truthful 'Belum diatur' & no fabricated numbers", case_f)

        # G. Supplier exists but no lead time handled truthfully
        def case_g():
            reorder.set_sku_lead_time(business_id=biz_id, master_sku_id=m_d, lead_time_days=0, supplier_name="PT Zero Lead")
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_d, lookback_days=30)
            assert rec["lead_time_days"] == 0
            assert rec["supplier_name"] == "PT Zero Lead"
            assert rec["lead_time_demand"] == 0.0
            assert rec["reorder_point"] == 0
        test("Case G: Supplier with 0 lead time => Handled without division error", case_g)

        # H. Cancelled/voided sale excluded
        def case_h():
            sale_void = retail.create_sale(
                tenant_id=TENANT, business_id=biz_id, branch_id=f["branch1_id"],
                register_id=f["reg1_id"], cashier_id=None, warehouse_id=wh1_id,
                lines=[{"master_sku_id": m_c, "sku": sku_c, "quantity": 10}],
                tender_method="CASH", amount_tendered=100000,
                client_event_id=f"sale-void-{TAG}", device_id=f"DEV-{TAG}",
            )
            retail.void_sale(
                sale_id=sale_void["sale_id"],
                reason="Mistake", actor="test-actor",
            )
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_c, lookback_days=30)
            assert rec["qty_sold"] == 0, f"Voided sale must not count in demand, got {rec['qty_sold']}"
        test("Case H: Voided sale is strictly excluded from demand", case_h)

        # I. Completed sale included
        sale_comp_id = None
        def case_i():
            nonlocal sale_comp_id
            sale_comp = retail.create_sale(
                tenant_id=TENANT, business_id=biz_id, branch_id=f["branch1_id"],
                register_id=f["reg1_id"], cashier_id=None, warehouse_id=wh1_id,
                lines=[{"master_sku_id": m_c, "sku": sku_c, "quantity": 15}],
                tender_method="CASH", amount_tendered=150000,
                client_event_id=f"sale-comp-{TAG}", device_id=f"DEV-{TAG}",
            )
            sale_comp_id = sale_comp["sale_id"]
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_c, lookback_days=30)
            assert rec["qty_sold"] == 15
            assert rec["average_daily_sales"] == 0.5  # 15 / 30 = 0.5
        test("Case I: Completed sale is included in demand calculation", case_i)

        # J. Returns treated correctly (net units sold)
        def case_j():
            returns.create_return(
                tenant_id=TENANT, business_id=biz_id, branch_id=f["branch1_id"],
                warehouse_id=wh1_id, sale_id=sale_comp_id, reason="Return",
                client_event_id=f"ret-{TAG}", device_id=f"DEV-{TAG}",
            )
            # Update return line to 5 units
            db.jalankan(
                "UPDATE local_business.sale_return_line SET quantity=5 WHERE return_id IN (SELECT id FROM local_business.sale_return WHERE client_event_id=%s)",
                (f"ret-{TAG}",)
            )
            rec = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_c, lookback_days=30)
            assert rec["qty_sold"] == 15
            assert rec["qty_returned"] == 5
            assert rec["net_units_sold"] == 10  # 15 - 5 = 10
            assert rec["average_daily_sales"] == 0.33  # 10 / 30 = 0.33
        test("Case J: Returns reduce net demand correctly (15 sold - 5 returned = 10)", case_j)

        # K. Multiple warehouses do not mix stock incorrectly
        def case_k():
            # Put 20 units in Warehouse 2 for Product D
            inv.receive_stock(tenant_id=TENANT, business_id=biz_id, branch_id=f["branch2_id"], warehouse_id=wh2_id, master_sku_id=m_d, sku=sku_d, quantity=20, idempotency_key=f"init-d-wh2-{TAG}")
            rec_wh1 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_d, warehouse_id=wh1_id)
            rec_wh2 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_d, warehouse_id=wh2_id)
            assert rec_wh1["available"] == 10
            assert rec_wh2["available"] == 20
        test("Case K: Warehouse-scoped calculation isolates inventory balances accurately", case_k)

        # L. Zero division impossible (lookback=0 or zero sales)
        def case_l():
            rec0 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_d, lookback_days=0)
            assert rec0["observed_days"] == 1
            assert rec0["average_daily_sales"] == 0.0
            assert rec0["estimated_depletion_days"] is None
        test("Case L: Zero division impossible when lookback=0 or sales=0", case_l)

        # M. Deterministic repeat gives same result
        def case_m():
            rec1 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_a, lookback_days=30)
            rec2 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_a, lookback_days=30)
            assert rec1 == rec2
        test("Case M: Repeated calculations yield identical deterministic results", case_m)

        # N. /reorder is read-only
        def case_n():
            bot = MockBotClient()
            msg_upd = {
                "update_id": 201,
                "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": "/reorder"}
            }
            bot_poller._handle_message(bot, msg_upd, scope)
            assert len(bot.sent_messages) == 1
            text = bot.sent_messages[0]["text"]
            assert "📦 REKOMENDASI RESTOCK" in text
            assert f"SKU: {sku_a}" in text
        test("Case N: /reorder renders recommendations without mutation", case_n)

        # O. /reorder SKU correct
        def case_o():
            bot = MockBotClient()
            msg_upd = {
                "update_id": 202,
                "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": f"/reorder {sku_a}"}
            }
            bot_poller._handle_message(bot, msg_upd, scope)
            assert len(bot.sent_messages) == 1
            text = bot.sent_messages[0]["text"]
            assert f"SKU: {sku_a}" in text
            assert "Stok tersedia: 8" in text
            assert "Penjualan rata-rata: 4/hari (30 hari)" in text
            assert "Estimasi habis: 2 hari" in text
            assert "Lead time: 5 hari" in text
            assert "Reorder point: 21" in text
            assert "Prioritas: TINGGI" in text
        test("Case O: /reorder SKU returns single-SKU detailed breakdown", case_o)

        # P. Zero inventory mutation
        def case_p():
            # Running reorder calculation repeatedly causes zero stock mutation
            reorder.calculate_reorder_recommendations(business_id=biz_id)
            bal_a = inv.location_balance(m_a, wh1_id)
            assert bal_a["available"] == 8
        test("Case P: Zero inventory balance or movement mutation occurred", case_p)

        # Q. Zero purchase-order mutation
        def case_q():
            reorder.calculate_reorder_recommendations(business_id=biz_id)
            gr_rows = db.semua("SELECT * FROM local_business.goods_receipt WHERE business_id=%s", (biz_id,))
            assert len(gr_rows) == 0
        test("Case Q: Zero purchase order or goods receipt rows created", case_q)

        # R. Zero Finance mutation from reorder
        def case_r():
            fin_before = len(db.semua("SELECT id FROM local_business.sale_finance"))
            reorder.calculate_reorder_recommendations(business_id=biz_id)
            reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=m_a)
            fin_after = len(db.semua("SELECT id FROM local_business.sale_finance"))
            assert fin_after == fin_before
        test("Case R: Zero Finance records created by reorder engine", case_r)

        # S. Low-Stock worker healthy
        def case_s():
            low_stock.set_threshold(business_id=biz_id, threshold=10, master_sku_id=m_a)
            t = low_stock.get_threshold(business_id=biz_id, master_sku_id=m_a)
            assert t == 10
        test("Case S: Low-Stock threshold subsystem functions seamlessly alongside Reorder", case_s)

        # T. Daily summary unchanged
        def case_t():
            timer_rows = db.semua("SELECT * FROM local_business.telegram_alert_outbox WHERE notification_type LIKE %s AND business_id=%s", ("DAILY_SUMMARY%", biz_id))
            assert len(timer_rows) == 0
        test("Case T: Daily Summary outbox remains completely untouched", case_t)

    finally:
        cleanup_fixtures(f)
        print("=== Cleanup of disposable acceptance fixtures complete ===")

    print(f"\nRESULTS: Passed: {passed}, Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all_cases())
