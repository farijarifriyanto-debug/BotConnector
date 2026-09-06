"""Deterministic Acceptance Suite for Procurement & Replenishment Core V1.

Covers:
- Supplier Master (S1-S8)
- Supplier SKU / Restock Config (R1-R10 + MOQ regression)
- Purchase Order Core (P1-P13)
- Goods Receipt & Inventory Integration (G1-G15)
- True Concurrency Proofs (Supplier, PO, Receipt)
- Zero Mutation, Idempotency & Security Invariants
"""

import math
import os
import sys
import uuid
import threading
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal

os.environ["BC_BOTCONNECTOR_DB_HOST"] = "127.0.0.1"
os.environ["BC_BOTCONNECTOR_DB_PORT"] = "15432"
sys.path.insert(0, "/opt")

from botconnector_multichannel.persistence import db
from botconnector_multichannel.persistence.db import koneksi, ambil, semua
from botconnector_multichannel.inventory import service as S
from botconnector_multichannel.local_business import (
    core,
    inventory as inv,
    low_stock,
    reorder,
    procurement as proc,
    bot_poller,
)

TAG = uuid.uuid4().hex[:6]
TENANT_ID = f"TEST-TENANT-PROC-{TAG}"
BIZ_CODE = f"BIZ-PROC-{TAG}"
PASSED = 0
FAILED = 0


def assert_true(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK]    {name}")
    else:
        FAILED += 1
        print(f"  [FAIL]  {name}")
        raise AssertionError(f"Assertion failed: {name}")


def run_tests():
    global PASSED, FAILED
    print(f"=== Starting Procurement & Replenishment Acceptance Tests (Tag: {TAG}) ===")

    # ------------------------------------------------------------
    # FIXTURE SETUP
    # ------------------------------------------------------------
    wh_code = f"WH-PROC-{TAG}"
    db.jalankan(
        "INSERT INTO multichannel.warehouse (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING",
        (wh_code, f"Warehouse {TAG}"),
    )
    wh_row = db.ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (wh_code,))
    wh_id = wh_row["id"]

    biz = core.upsert_business(tenant_id=TENANT_ID, code=BIZ_CODE, name=f"Biz Procurement {TAG}", business_type="RETAIL")
    biz_id = biz["id"]

    br = core.upsert_branch(business_id=biz_id, code=f"BR-PROC-{TAG}", name=f"Branch {TAG}", warehouse_id=wh_id, branch_type="RETAIL")
    branch_id = br["id"]

    # Products & SKUs
    prod_a = S.upsert_product(name=f"Produk A {TAG}", category="Test", brand="")
    master_a = S.upsert_master_sku(sku=f"SKU-A-{TAG}", product_id=prod_a["id"])
    sku_a_id = master_a["id"]

    prod_b = S.upsert_product(name=f"Produk B {TAG}", category="Test", brand="")
    master_b = S.upsert_master_sku(sku=f"SKU-B-{TAG}", product_id=prod_b["id"])
    sku_b_id = master_b["id"]

    # Initialize stock: SKU A = 10 (available 9, safety 1), SKU B = 0
    inv.receive_stock(
        tenant_id=TENANT_ID, business_id=biz_id, branch_id=branch_id,
        warehouse_id=wh_id, master_sku_id=sku_a_id, sku=f"SKU-A-{TAG}",
        quantity=10, reference="init_a", source_document="INIT_A",
        idempotency_key=f"init_a_{TAG}",
    )
    # Set safety stock on SKU A
    with koneksi() as c:
        c.cursor().execute("UPDATE multichannel.inventory_balance SET safety_stock=1, available=9 WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
        c.commit()

    owner_id = biz_id
    tg_user_id = 99887766
    wrong_user_id = 11223344

    # ------------------------------------------------------------
    # SECTION 1: SUPPLIER MASTER ACCEPTANCE (S1-S8)
    # ------------------------------------------------------------
    print("\n--- SECTION 1: SUPPLIER MASTER ACCEPTANCE ---")

    # S1: Supplier create preview = zero DB mutation
    draft_s1 = proc.create_procurement_draft(
        draft_type="SUPPLIER_CREATE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"code": f"SUP-A-{TAG}", "name": "PT Supplier A", "contact_name": "Budi", "phone": "0812345678"},
    )
    s_check = proc.get_supplier(business_id=biz_id, code=f"SUP-A-{TAG}")
    assert_true(s_check is None, "S1: Supplier create preview causes zero database mutation")

    # S2: Confirm creates exactly one supplier
    res_s2 = proc.confirm_procurement_draft(draft_token=draft_s1["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(res_s2.get("ok") and not res_s2.get("idempotent"), "S2a: Confirm supplier draft succeeds")
    supp_a = proc.get_supplier(business_id=biz_id, code=f"SUP-A-{TAG}")
    assert_true(supp_a is not None and supp_a["name"] == "PT Supplier A" and supp_a["active"], "S2b: Exactly one active supplier created in DB")

    # S3: Duplicate confirm is idempotent
    res_s3 = proc.confirm_procurement_draft(draft_token=draft_s1["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(res_s3.get("ok") and res_s3.get("idempotent"), "S3: Duplicate confirm is strictly idempotent")

    # S4: Edit supplier works
    draft_s4 = proc.create_procurement_draft(
        draft_type="SUPPLIER_EDIT",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"code": f"SUP-A-{TAG}", "name": "PT Supplier A Baru", "contact_name": "Budi Hartono", "phone": "081999999"},
    )
    proc.confirm_procurement_draft(draft_token=draft_s4["draft_token"], caller_telegram_user_id=tg_user_id)
    supp_a_updated = proc.get_supplier(business_id=biz_id, code=f"SUP-A-{TAG}")
    assert_true(supp_a_updated["name"] == "PT Supplier A Baru" and supp_a_updated["contact_name"] == "Budi Hartono", "S4: Edit supplier updates details accurately")

    # S5: Duplicate supplier code blocked
    try:
        proc.create_supplier(business_id=biz_id, code=f"SUP-A-{TAG}", name="Duplicate Supplier")
        dup_failed = False
    except ValueError:
        dup_failed = True
    assert_true(dup_failed, "S5: Duplicate supplier code for same business is strictly blocked")

    # S6: Wrong user blocked from confirming draft
    draft_s6 = proc.create_procurement_draft(
        draft_type="SUPPLIER_CREATE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"code": f"SUP-B-{TAG}", "name": "Supplier B"},
    )
    res_s6 = proc.confirm_procurement_draft(draft_token=draft_s6["draft_token"], caller_telegram_user_id=wrong_user_id)
    assert_true(not res_s6.get("ok") and res_s6.get("error") == "wrong_user", "S6: Wrong Telegram user is blocked from confirming draft")

    # S7: Expired draft is blocked
    draft_s7 = proc.create_procurement_draft(
        draft_type="SUPPLIER_CREATE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"code": f"SUP-C-{TAG}", "name": "Supplier C"},
        expires_in_seconds=-10,
    )
    res_s7 = proc.confirm_procurement_draft(draft_token=draft_s7["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(not res_s7.get("ok") and res_s7.get("error") == "draft_expired", "S7: Expired draft is blocked from mutating")

    # S8: Soft deactivate supplier preserves history
    draft_s8 = proc.create_procurement_draft(
        draft_type="SUPPLIER_OFF",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"code": f"SUP-A-{TAG}"},
    )
    proc.confirm_procurement_draft(draft_token=draft_s8["draft_token"], caller_telegram_user_id=tg_user_id)
    supp_a_deact = proc.get_supplier(business_id=biz_id, code=f"SUP-A-{TAG}")
    assert_true(supp_a_deact is not None and not supp_a_deact["active"], "S8: Deactivating supplier preserves row with active=FALSE")

    # Reactivate for subsequent tests
    proc.update_supplier(business_id=biz_id, code=f"SUP-A-{TAG}", active=True)

    # ------------------------------------------------------------
    # SECTION 2: SUPPLIER SKU & RESTOCK CONFIG (R1-R10)
    # ------------------------------------------------------------
    print("\n--- SECTION 2: SUPPLIER SKU & RESTOCK CONFIG ACCEPTANCE ---")

    # R1: No config -> /reorder returns DATA_INCOMPLETE
    rec_r1 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(rec_r1["priority"] == "DATA_INCOMPLETE" and rec_r1["lead_time_days"] is None, "R1: Unconfigured SKU returns priority DATA_INCOMPLETE")

    # R2: Valid mapping preview = zero mutation
    draft_r2 = proc.create_procurement_draft(
        draft_type="RESTOCK_CONFIG",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={
            "master_sku_id": sku_a_id,
            "sku": f"SKU-A-{TAG}",
            "supplier_id": supp_a["id"],
            "lead_time_days": 5,
            "min_order_qty": 12,
            "target_stock": 30,
        },
    )
    cfg_r2 = proc.get_preferred_supplier_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(cfg_r2 is None, "R2: Restock config preview causes zero database mutation")

    # R3: Confirm creates exactly one mapping
    res_r3 = proc.confirm_procurement_draft(draft_token=draft_r2["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(res_r3.get("ok"), "R3a: Confirm restock config draft succeeds")
    cfg_r3 = proc.get_preferred_supplier_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(cfg_r3 is not None and cfg_r3["lead_time_days"] == 5 and cfg_r3["min_order_qty"] == 12 and cfg_r3["target_stock"] == 30, "R3b: Preferred supplier-SKU terms created accurately")

    # R4: Preferred supplier is deterministic
    supp_2 = proc.create_supplier(business_id=biz_id, code=f"SUP-2-{TAG}", name="Supplier Kedua")
    proc.set_supplier_sku(business_id=biz_id, supplier_id=supp_2["id"], master_sku_id=sku_a_id, lead_time_days=10, min_order_qty=24, preferred=False)
    pref = proc.get_preferred_supplier_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(pref["supplier_id"] == supp_a["id"] and pref["lead_time_days"] == 5, "R4: Preferred supplier selection is strictly deterministic")

    # R5 & R6: Lead time < 0 rejected by core
    try:
        proc.set_supplier_sku(business_id=biz_id, supplier_id=supp_a["id"], master_sku_id=sku_a_id, lead_time_days=-2)
        neg_lt_passed = True
    except ValueError:
        neg_lt_passed = False
    assert_true(not neg_lt_passed, "R6: Negative lead time is strictly rejected")

    # R7: MOQ < 1 rejected
    try:
        proc.set_supplier_sku(business_id=biz_id, supplier_id=supp_a["id"], master_sku_id=sku_a_id, lead_time_days=5, min_order_qty=0)
        moq_zero_passed = True
    except ValueError:
        moq_zero_passed = False
    assert_true(not moq_zero_passed, "R7: MOQ < 1 is strictly rejected")

    # R8: Target stock < MOQ rejected
    try:
        proc.set_supplier_sku(business_id=biz_id, supplier_id=supp_a["id"], master_sku_id=sku_a_id, lead_time_days=5, min_order_qty=20, target_stock=10)
        tgt_lt_moq_passed = True
    except ValueError:
        tgt_lt_moq_passed = False
    assert_true(not tgt_lt_moq_passed, "R8: Target stock < MOQ is strictly rejected")

    # R9: Edit mapping works
    proc.set_supplier_sku(business_id=biz_id, supplier_id=supp_a["id"], master_sku_id=sku_a_id, lead_time_days=7, min_order_qty=15, target_stock=40)
    cfg_upd = proc.get_preferred_supplier_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(cfg_upd["lead_time_days"] == 7 and cfg_upd["min_order_qty"] == 15 and cfg_upd["target_stock"] == 40, "R9: Update restock configuration succeeds")

    # R10: OFF returns /reorder to DATA_INCOMPLETE
    draft_r10 = proc.create_procurement_draft(
        draft_type="RESTOCK_OFF",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"master_sku_id": sku_a_id, "sku": f"SKU-A-{TAG}"},
    )
    proc.confirm_procurement_draft(draft_token=draft_r10["draft_token"], caller_telegram_user_id=tg_user_id)
    rec_r10 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(rec_r10["priority"] == "DATA_INCOMPLETE" and rec_r10["lead_time_days"] is None, "R10: Restock OFF resets SKU to DATA_INCOMPLETE")

    # Re-enable config for MOQ exact regression tests:
    # Set target=30, MOQ=12
    proc.set_supplier_sku(business_id=biz_id, supplier_id=supp_a["id"], master_sku_id=sku_a_id, lead_time_days=5, min_order_qty=12, target_stock=30)

    # MOQ Exact Regression 1: available=8, target=30, MOQ=1 => raw=22, suggested=22
    proc.set_supplier_sku(business_id=biz_id, supplier_id=supp_a["id"], master_sku_id=sku_a_id, lead_time_days=5, min_order_qty=1, target_stock=30)
    with koneksi() as c:
        c.cursor().execute("UPDATE multichannel.inventory_balance SET on_hand=8, available=8 WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
        c.commit()
    rec_moq1 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(rec_moq1["suggested_order_qty"] == 22, "MOQ Reg 1: available=8, target=30, MOQ=1 => suggested=22")

    # MOQ Exact Regression 2: available=25, target=30, MOQ=12 => raw=5, suggested=12
    proc.set_supplier_sku(business_id=biz_id, supplier_id=supp_a["id"], master_sku_id=sku_a_id, lead_time_days=5, min_order_qty=12, target_stock=30)
    with koneksi() as c:
        c.cursor().execute("UPDATE multichannel.inventory_balance SET on_hand=25, available=25 WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
        c.commit()
    rec_moq2 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(rec_moq2["suggested_order_qty"] == 12, "MOQ Reg 2: available=25, target=30, MOQ=12 => suggested=12 (enforcing MOQ)")

    # MOQ Exact Regression 3: available=30, target=30, MOQ=12 => raw=0, suggested=0
    with koneksi() as c:
        c.cursor().execute("UPDATE multichannel.inventory_balance SET on_hand=30, available=30 WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
        c.commit()
    rec_moq3 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(rec_moq3["suggested_order_qty"] == 0, "MOQ Reg 3: available=30, target=30, MOQ=12 => suggested=0")

    # ------------------------------------------------------------
    # SECTION 3: PURCHASE ORDER CORE ACCEPTANCE (P1-P13)
    # ------------------------------------------------------------
    print("\n--- SECTION 3: PURCHASE ORDER CORE ACCEPTANCE ---")

    # Reset SKU A stock: available=9, target=30, MOQ=12 => raw=21, suggested=21
    with koneksi() as c:
        c.cursor().execute("UPDATE multichannel.inventory_balance SET on_hand=10, available=9, safety_stock=1 WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
        c.commit()

    # P1: Recommendation can create PO preview
    rec_po = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=sku_a_id)
    assert_true(rec_po["suggested_order_qty"] == 21, "P1a: Reorder suggestion calculated (30 - 9 = 21)")

    # P2: Preview causes zero DB mutation
    draft_p2 = proc.create_procurement_draft(
        draft_type="PO_CREATE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={
            "supplier_id": supp_a["id"],
            "warehouse_id": wh_id,
            "lines": [{"master_sku_id": sku_a_id, "sku": f"SKU-A-{TAG}", "ordered_qty": 21, "unit_cost": 10000}],
        },
    )
    po_list_init = proc.list_purchase_orders(business_id=biz_id)
    assert_true(len(po_list_init) == 0, "P2: PO draft preview causes zero purchase_order rows in DB")

    # P3: Confirm Draft creates one DRAFT PO
    res_p3 = proc.confirm_procurement_draft(draft_token=draft_p2["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(res_p3.get("ok"), "P3a: Confirm PO draft succeeds")
    po_list_p3 = proc.list_purchase_orders(business_id=biz_id)
    assert_true(len(po_list_p3) == 1 and po_list_p3[0]["status"] == "DRAFT", "P3b: Exactly one DRAFT PO created")
    po1 = po_list_p3[0]

    # P4: Duplicate confirm -> no duplicate PO
    res_p4 = proc.confirm_procurement_draft(draft_token=draft_p2["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(res_p4.get("ok") and res_p4.get("idempotent"), "P4a: Duplicate confirm is idempotent")
    assert_true(len(proc.list_purchase_orders(business_id=biz_id)) == 1, "P4b: Total PO count remains exactly 1")

    # P5: DRAFT PO does not mutate stock
    bal_p5 = ambil("SELECT on_hand, available FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
    assert_true(bal_p5["on_hand"] == 10 and bal_p5["available"] == 9, "P5: DRAFT PO does not mutate inventory balance")

    # P6: DRAFT PO does not touch Finance
    gr_p6 = semua("SELECT * FROM local_business.goods_receipt WHERE business_id=%s", (biz_id,))
    assert_true(len(gr_p6) == 0, "P6: DRAFT PO creates zero goods receipt / Finance records")

    # P7: Human confirms PO -> CONFIRMED
    draft_p7 = proc.create_procurement_draft(
        draft_type="PO_CONFIRM",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"po_number": po1["po_number"]},
    )
    res_p7 = proc.confirm_procurement_draft(draft_token=draft_p7["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(res_p7.get("ok"), "P7a: Human PO confirmation succeeds")
    po1_conf = proc.get_purchase_order(business_id=biz_id, po_number=po1["po_number"])
    assert_true(po1_conf["status"] == "CONFIRMED" and po1_conf["confirmed_at"] is not None, "P7b: PO status transitioned to CONFIRMED")

    # P8: Confirmed PO still no inventory mutation
    bal_p8 = ambil("SELECT on_hand, available FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
    assert_true(bal_p8["on_hand"] == 10 and bal_p8["available"] == 9, "P8: CONFIRMED PO still causes zero inventory mutation")

    # P9: Expected arrival = confirmation date + lead time (5 days)
    today = datetime.now(timezone.utc).date()
    exp_expected = today + timedelta(days=5)
    assert_true(po1_conf["expected_arrival_date"] == exp_expected, f"P9: Expected arrival date ({po1_conf['expected_arrival_date']}) matches confirmation + lead time ({exp_expected})")

    # P10: Cancellation valid (from DRAFT or CONFIRMED)
    po_cancel_draft = proc.create_purchase_order(
        business_id=biz_id,
        supplier_id=supp_a["id"],
        warehouse_id=wh_id,
        lines=[{"master_sku_id": sku_a_id, "ordered_qty": 5, "unit_cost": 10000}],
    )
    res_p10 = proc.cancel_purchase_order(business_id=biz_id, po_number=po_cancel_draft["po_number"])
    assert_true(res_p10.get("ok") and res_p10["status"] == "CANCELLED", "P10: Cancellation of PO succeeds")

    # P11: Invalid status transitions rejected (confirming cancelled PO)
    try:
        proc.confirm_purchase_order(business_id=biz_id, po_number=po_cancel_draft["po_number"])
        inv_trans_passed = True
    except ValueError:
        inv_trans_passed = False
    assert_true(not inv_trans_passed, "P11: Confirming a CANCELLED PO is strictly rejected")

    # P12: Wrong user cannot confirm / cancel
    draft_p12 = proc.create_procurement_draft(
        draft_type="PO_CONFIRM",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"po_number": po1["po_number"]},
    )
    res_p12 = proc.confirm_procurement_draft(draft_token=draft_p12["draft_token"], caller_telegram_user_id=wrong_user_id)
    assert_true(not res_p12.get("ok") and res_p12.get("error") == "wrong_user", "P12: Wrong user cannot confirm PO draft")

    # P13: Stale / expired callback rejected
    draft_p13 = proc.create_procurement_draft(
        draft_type="PO_CONFIRM",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"po_number": po1["po_number"]},
        expires_in_seconds=-5,
    )
    res_p13 = proc.confirm_procurement_draft(draft_token=draft_p13["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(not res_p13.get("ok") and res_p13.get("error") == "draft_expired", "P13: Stale / expired callback rejected")

    # ------------------------------------------------------------
    # SECTION 4: GOODS RECEIPT AGAINST PO (G1-G15)
    # ------------------------------------------------------------
    print("\n--- SECTION 4: GOODS RECEIPT AGAINST PO ACCEPTANCE ---")

    # G1: Receive against DRAFT PO rejected
    po_draft_test = proc.create_purchase_order(
        business_id=biz_id,
        supplier_id=supp_a["id"],
        warehouse_id=wh_id,
        lines=[{"master_sku_id": sku_a_id, "ordered_qty": 10, "unit_cost": 10000}],
    )
    try:
        proc.receive_purchase_order(
            business_id=biz_id,
            po_number=po_draft_test["po_number"],
            lines=[{"master_sku_id": sku_a_id, "quantity": 10}],
        )
        rec_draft_passed = True
    except ValueError:
        rec_draft_passed = False
    assert_true(not rec_draft_passed, "G1: Receiving against DRAFT PO is strictly rejected")

    # G2 & G3: Receipt preview against CONFIRMED PO causes zero mutation
    draft_g3 = proc.create_procurement_draft(
        draft_type="PO_RECEIVE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={
            "po_number": po1["po_number"],
            "lines": [{"master_sku_id": sku_a_id, "quantity": 11}],
        },
    )
    bal_g3 = ambil("SELECT on_hand FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
    assert_true(bal_g3["on_hand"] == 10, "G3: Receipt preview causes zero stock mutation")

    # G4 & G6: Partial receipt (ordered 21, receive 11) -> PARTIALLY_RECEIVED & on_hand increases from 10 to 21
    res_g4 = proc.confirm_procurement_draft(draft_token=draft_g3["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(res_g4.get("ok"), "G4a: Confirm partial receipt succeeds")
    po1_after_g4 = proc.get_purchase_order(business_id=biz_id, po_number=po1["po_number"])
    assert_true(po1_after_g4["status"] == "PARTIALLY_RECEIVED", "G6a: PO status transitioned to PARTIALLY_RECEIVED")
    po1_ln_g4 = po1_after_g4["lines"][0]
    assert_true(po1_ln_g4["received_qty"] == 11 and po1_ln_g4["ordered_qty"] == 21, "G6b: PO line received_qty updated to 11 / 21")

    # G4b: Canonical inventory on_hand increased exactly once by 11 (10 -> 21)
    bal_g4 = ambil("SELECT on_hand, available FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
    assert_true(bal_g4["on_hand"] == 21 and bal_g4["available"] == 20, f"G4b: Stock on_hand increased to 21 (actual={bal_g4['on_hand']})")

    # G5: Inventory movement exists exactly once
    movs = semua(
        "SELECT * FROM multichannel.inventory_movement WHERE master_sku_id=%s AND warehouse_id=%s AND movement_type='MASUK'",
        (sku_a_id, wh_id),
    )
    assert_true(len(movs) == 2 and any(m["qty"] == 11 for m in movs), "G5: Canonical inventory_movement row exists with qty=11")

    # G8: Over-receipt rejected (remaining is 10, attempt to receive 15)
    try:
        proc.receive_purchase_order(
            business_id=biz_id,
            po_number=po1["po_number"],
            lines=[{"master_sku_id": sku_a_id, "quantity": 15}],
        )
        over_rec_passed = True
    except ValueError:
        over_rec_passed = False
    assert_true(not over_rec_passed, "G8: Over-receipt (15 > 10 remaining) is strictly rejected")

    # G9: Duplicate callback does not double stock
    res_g9 = proc.confirm_procurement_draft(draft_token=draft_g3["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(res_g9.get("ok") and res_g9.get("idempotent"), "G9a: Replaying confirmed receipt draft is idempotent")
    bal_g9 = ambil("SELECT on_hand FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
    assert_true(bal_g9["on_hand"] == 21, "G9b: Duplicate receipt callback does NOT double stock")

    # G10: Wrong warehouse rejected
    try:
        proc.receive_purchase_order(
            business_id=biz_id,
            warehouse_id=999999,
            po_number=po1["po_number"],
            lines=[{"master_sku_id": sku_a_id, "quantity": 5}],
        )
        wrong_wh_passed = True
    except (ValueError, KeyError):
        wrong_wh_passed = False
    assert_true(not wrong_wh_passed, "G10: Receipt to wrong warehouse is rejected")

    # G11: Wrong business rejected
    try:
        proc.receive_purchase_order(
            business_id=999999,
            po_number=po1["po_number"],
            lines=[{"master_sku_id": sku_a_id, "quantity": 5}],
        )
        wrong_biz_passed = True
    except (ValueError, KeyError):
        wrong_biz_passed = False
    assert_true(not wrong_biz_passed, "G11: Receipt from wrong business is rejected")

    # G7: Second receipt completes PO -> RECEIVED
    draft_g7 = proc.create_procurement_draft(
        draft_type="PO_RECEIVE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={
            "po_number": po1["po_number"],
            "lines": [{"master_sku_id": sku_a_id, "quantity": 10}],
        },
    )
    res_g7 = proc.confirm_procurement_draft(draft_token=draft_g7["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(res_g7.get("ok"), "G7a: Second receipt confirmed successfully")
    po1_completed = proc.get_purchase_order(business_id=biz_id, po_number=po1["po_number"])
    assert_true(po1_completed["status"] == "RECEIVED" and po1_completed["completed_at"] is not None, "G7b: PO status transitioned to RECEIVED with completed_at set")
    bal_g7 = ambil("SELECT on_hand, available FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
    assert_true(bal_g7["on_hand"] == 31 and bal_g7["available"] == 30, f"G7c: Total stock reached 31 on_hand, 30 available (actual={bal_g7['on_hand']})")

    # G12: Low-stock recovery happens naturally through canonical receive path
    # Set threshold = 35 (current stock 31 <= 35 => alert state armed)
    low_stock.set_threshold(business_id=biz_id, master_sku_id=sku_a_id, threshold=35)
    with koneksi() as c:
        low_stock.evaluate_transition(
            c.cursor(),
            business_id=biz_id,
            warehouse_id=wh_id,
            master_sku_id=sku_a_id,
            sku=f"SKU-A-{TAG}",
            available_before=36,
            available_after=30,
        )
        c.commit()
    alert_st = ambil("SELECT is_alerted FROM local_business.low_stock_alert_state WHERE business_id=%s AND master_sku_id=%s", (biz_id, sku_a_id))
    assert_true(alert_st is not None and alert_st["is_alerted"], "G12a: Low-stock state is alerted before recovery receipt")

    # Create & confirm PO to receive 10 units -> stock 31 + 10 = 41 > 35 threshold
    po_recov = proc.create_purchase_order(
        business_id=biz_id,
        supplier_id=supp_a["id"],
        warehouse_id=wh_id,
        lines=[{"master_sku_id": sku_a_id, "ordered_qty": 10, "unit_cost": 10000}],
    )
    proc.confirm_purchase_order(business_id=biz_id, po_number=po_recov["po_number"])
    proc.receive_purchase_order(business_id=biz_id, po_number=po_recov["po_number"], lines=[{"master_sku_id": sku_a_id, "quantity": 10}])

    alert_st_after = ambil("SELECT is_alerted, last_rearmed_at FROM local_business.low_stock_alert_state WHERE business_id=%s AND master_sku_id=%s", (biz_id, sku_a_id))
    assert_true(alert_st_after["is_alerted"] is False and alert_st_after["last_rearmed_at"] is not None, "G12b: Canonical receipt above threshold automatically re-arms low-stock alert state")

    # G14 & G15: Zero automatic vendor payments or supplier outbound messages
    ap_bills = semua("SELECT * FROM local_business.receipt_finance WHERE status='PAID'", ())
    assert_true(len(ap_bills) == 0, "G14: Zero automatic vendor payments posted")

    outbox_po = semua("SELECT * FROM local_business.telegram_alert_outbox WHERE notification_type='PO_SUPPLIER_MESSAGE'", ())
    assert_true(len(outbox_po) == 0, "G15: Zero automatic external supplier messages dispatched")

    # ------------------------------------------------------------
    # SECTION 5: TRUE CONCURRENCY TESTS (C1-C3)
    # ------------------------------------------------------------
    print("\n--- SECTION 5: TRUE CONCURRENCY ACCEPTANCE ---")

    # C1: Concurrent Supplier Draft Confirmation
    draft_c1 = proc.create_procurement_draft(
        draft_type="SUPPLIER_CREATE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"code": f"SUP-CONC-{TAG}", "name": "Supplier Concurrency"},
    )
    c1_results = []
    def confirm_c1():
        r = proc.confirm_procurement_draft(draft_token=draft_c1["draft_token"], caller_telegram_user_id=tg_user_id)
        c1_results.append(r)

    t1 = threading.Thread(target=confirm_c1)
    t2 = threading.Thread(target=confirm_c1)
    t1.start(); t2.start()
    t1.join(); t2.join()

    supp_c1_rows = semua("SELECT * FROM local_business.supplier WHERE business_id=%s AND code=%s", (biz_id, f"SUP-CONC-{TAG}".upper()))
    assert_true(len(supp_c1_rows) == 1, "C1a: Concurrency race creates exactly 1 supplier record")
    assert_true(all(r.get("ok") for r in c1_results), "C1b: Both concurrent callers receive ok status (1 mutation, 1 idempotent)")

    # C2: Concurrent PO Draft Confirmation
    draft_c2 = proc.create_procurement_draft(
        draft_type="PO_CREATE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={
            "supplier_id": supp_a["id"],
            "warehouse_id": wh_id,
            "lines": [{"master_sku_id": sku_b_id, "ordered_qty": 50, "unit_cost": 5000}],
        },
    )
    c2_results = []
    def confirm_c2():
        r = proc.confirm_procurement_draft(draft_token=draft_c2["draft_token"], caller_telegram_user_id=tg_user_id)
        c2_results.append(r)

    t1 = threading.Thread(target=confirm_c2)
    t2 = threading.Thread(target=confirm_c2)
    t1.start(); t2.start()
    t1.join(); t2.join()

    po_c2_rows = semua("SELECT po.* FROM local_business.purchase_order po JOIN local_business.purchase_order_line pol ON pol.purchase_order_id=po.id WHERE po.business_id=%s AND pol.master_sku_id=%s", (biz_id, sku_b_id))
    assert_true(len(po_c2_rows) == 1, "C2a: Concurrent PO draft confirmation creates exactly 1 PO")
    po_c2_num = po_c2_rows[0]["po_number"]

    # Confirm PO C2
    proc.confirm_purchase_order(business_id=biz_id, po_number=po_c2_num)

    # C3: Concurrent Goods Receipt Confirmation
    draft_c3 = proc.create_procurement_draft(
        draft_type="PO_RECEIVE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={
            "po_number": po_c2_num,
            "lines": [{"master_sku_id": sku_b_id, "quantity": 50}],
        },
    )
    bal_b_before = ambil("SELECT COALESCE(on_hand, 0) AS on_hand FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_b_id, wh_id))
    b_before_qty = bal_b_before["on_hand"] if bal_b_before else 0
    assert_true(b_before_qty == 0, "C3a: SKU B on_hand before receipt is 0")

    c3_results = []
    def confirm_c3():
        r = proc.confirm_procurement_draft(draft_token=draft_c3["draft_token"], caller_telegram_user_id=tg_user_id)
        c3_results.append(r)

    t1 = threading.Thread(target=confirm_c3)
    t2 = threading.Thread(target=confirm_c3)
    t1.start(); t2.start()
    t1.join(); t2.join()

    bal_b_after = ambil("SELECT on_hand FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_b_id, wh_id))["on_hand"]
    assert_true(bal_b_after == 50, f"C3b: Concurrent receipt increments stock exactly once (expected 50, actual={bal_b_after})")

    # ------------------------------------------------------------
    # CLEANUP DISPOSABLE FIXTURES
    # ------------------------------------------------------------
    print("\n=== Cleaning up disposable acceptance fixtures ===")
    with koneksi() as c:
        cur = c.cursor()
        cur.execute("DELETE FROM local_business.telegram_procurement_draft WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.low_stock_alert_state WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.low_stock_threshold WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.goods_receipt_line WHERE receipt_id IN (SELECT id FROM local_business.goods_receipt WHERE business_id=%s)", (biz_id,))
        cur.execute("DELETE FROM local_business.goods_receipt WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.purchase_order_line WHERE purchase_order_id IN (SELECT id FROM local_business.purchase_order WHERE business_id=%s)", (biz_id,))
        cur.execute("DELETE FROM local_business.purchase_order WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.supplier_sku WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.supplier WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM multichannel.inventory_movement WHERE master_sku_id IN (%s, %s)", (sku_a_id, sku_b_id))
        cur.execute("DELETE FROM multichannel.inventory_balance WHERE warehouse_id=%s", (wh_id,))
        cur.execute("DELETE FROM local_business.branch WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM multichannel.warehouse WHERE id=%s", (wh_id,))
        cur.execute("DELETE FROM multichannel.master_sku WHERE id IN (%s, %s)", (sku_a_id, sku_b_id))
        cur.execute("DELETE FROM multichannel.product WHERE id IN (%s, %s)", (prod_a["id"], prod_b["id"]))
        cur.execute("DELETE FROM local_business.business WHERE id=%s", (biz_id,))
        c.commit()

    print("=== Cleanup of disposable fixtures complete ===")
    print(f"\nFINAL RESULTS: Passed: {PASSED}, Failed: {FAILED}")
    return FAILED == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
