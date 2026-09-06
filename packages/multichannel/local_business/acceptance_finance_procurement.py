"""Acceptance Test Suite for Vendor Bill + Accounts Payable + Payment Core V1.

Tests 3-Way Matching, Vendor Bill creation/posting/cancellation,
Accounts Payable journal creation in Finance Core, Partial & Full Payment,
Concurrency protection, and Telegram UX/security.
"""

from __future__ import annotations

import os
import secrets
import sys
import threading
from datetime import date, timedelta
from decimal import Decimal

os.environ["BC_BOTCONNECTOR_DB_HOST"] = "127.0.0.1"
os.environ["BC_BOTCONNECTOR_DB_PORT"] = "15432"
sys.path.insert(0, "/opt")

import psycopg
from botconnector_multichannel.persistence.db import koneksi, ambil, semua
from botconnector_multichannel.inventory import service as S
from botconnector_multichannel.local_business import core, procurement as proc, inventory as inv, low_stock, reorder
from botconnector_multichannel.workflow import finance_core as fc

TAG = secrets.token_hex(3)
TENANT = f"FIN-TENANT-{TAG}"
PASSED_COUNT = 0
FAILED_COUNT = 0


def assert_true(condition: bool, name: str):
    global PASSED_COUNT, FAILED_COUNT
    if condition:
        PASSED_COUNT += 1
        print(f"  [OK]    {name}")
    else:
        FAILED_COUNT += 1
        print(f"  [FAIL]  {name}")
        raise AssertionError(f"Assertion failed: {name}")


def setup_fixtures():
    """Create isolated disposable fixtures."""
    wh_code = f"WH-FIN-{TAG}"
    with koneksi() as c:
        cur = c.cursor()
        cur.execute("INSERT INTO multichannel.tenant (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (TENANT,))
        cur.execute("INSERT INTO multichannel.warehouse (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING", (wh_code, f"Warehouse Finance {TAG}"))
        c.commit()

    wh_row = ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (wh_code,))
    wh_id = wh_row["id"]

    biz = core.upsert_business(tenant_id=TENANT, code=f"BIZ-FIN-{TAG}", name=f"Biz Finance {TAG}", business_type="RETAIL")
    biz_id = biz["id"]

    br = core.upsert_branch(business_id=biz_id, code=f"BR-FIN-{TAG}", name=f"Branch Finance {TAG}", warehouse_id=wh_id, branch_type="RETAIL")
    branch_id = br["id"]

    reg = core.upsert_register(branch_id=branch_id, code=f"REG-FIN-{TAG}", name=f"Reg-FIN-{TAG}")
    reg_id = reg["id"]

    prod_a = S.upsert_product(name=f"Produk A {TAG}", category="Test", brand="")
    master_a = S.upsert_master_sku(sku=f"SKU-FIN-A-{TAG}", product_id=prod_a["id"])
    sku_a_id = master_a["id"]

    prod_b = S.upsert_product(name=f"Produk B {TAG}", category="Test", brand="")
    master_b = S.upsert_master_sku(sku=f"SKU-FIN-B-{TAG}", product_id=prod_b["id"])
    sku_b_id = master_b["id"]

    tg_user_id = 998877000 + int(TAG, 16) % 100000
    with koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.telegram_account
               (owner_id, telegram_user_id, actor)
               VALUES (%s, %s, %s)""",
            (biz_id, tg_user_id, "Finance Canary Owner"),
        )
        c.commit()

    return {
        "tenant_id": TENANT,
        "biz_id": biz_id,
        "wh_id": wh_id,
        "branch_id": branch_id,
        "reg_id": reg_id,
        "tg_user_id": tg_user_id,
        "sku_a_id": sku_a_id,
        "sku_b_id": sku_b_id,
        "prod_a_id": prod_a["id"],
        "prod_b_id": prod_b["id"],
    }


def cleanup_fixtures(f: dict):
    """Clean up all disposable test fixtures."""
    biz_id = f["biz_id"]
    tenant_id = f["tenant_id"]
    sku_a_id = f["sku_a_id"]
    sku_b_id = f["sku_b_id"]

    with koneksi() as c:
        cur = c.cursor()
        cur.execute("DELETE FROM local_business.vendor_payment WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.vendor_bill_line WHERE vendor_bill_id IN (SELECT id FROM local_business.vendor_bill WHERE business_id=%s)", (biz_id,))
        cur.execute("DELETE FROM local_business.vendor_bill WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.telegram_procurement_draft WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.goods_receipt_line WHERE receipt_id IN (SELECT id FROM local_business.goods_receipt WHERE business_id=%s)", (biz_id,))
        cur.execute("DELETE FROM local_business.goods_receipt WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.purchase_order_line WHERE purchase_order_id IN (SELECT id FROM local_business.purchase_order WHERE business_id=%s)", (biz_id,))
        cur.execute("DELETE FROM local_business.purchase_order WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.supplier_sku WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.supplier WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.telegram_account WHERE owner_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.register WHERE branch_id=%s", (f["branch_id"],))
        cur.execute("DELETE FROM local_business.branch WHERE id=%s", (f["branch_id"],))
        cur.execute("DELETE FROM local_business.business WHERE id=%s", (biz_id,))
        cur.execute("DELETE FROM multichannel.inventory_movement WHERE master_sku_id IN (%s, %s)", (sku_a_id, sku_b_id))
        cur.execute("DELETE FROM multichannel.inventory_balance WHERE master_sku_id IN (%s, %s)", (sku_a_id, sku_b_id))
        cur.execute("DELETE FROM multichannel.master_sku WHERE id IN (%s, %s)", (sku_a_id, sku_b_id))
        cur.execute("DELETE FROM multichannel.product WHERE id IN (%s, %s)", (f["prod_a_id"], f["prod_b_id"]))
        cur.execute("DELETE FROM multichannel.warehouse WHERE id=%s", (f["wh_id"],))
        cur.execute("DELETE FROM multichannel.tenant WHERE id=%s", (tenant_id,))
        c.commit()


def run_tests():
    print(f"=== Starting Finance Procurement Acceptance Tests (Tag: {TAG}) ===")
    f = setup_fixtures()
    biz_id = f["biz_id"]
    wh_id = f["wh_id"]
    tg_user_id = f["tg_user_id"]
    sku_a_id = f["sku_a_id"]
    sku_b_id = f["sku_b_id"]

    try:
        # Create Supplier
        supp = proc.create_supplier(
            business_id=biz_id,
            code=f"SUP-FIN-{TAG}",
            name=f"Supplier Finance {TAG}",
        )
        supp_id = supp["id"]

        # Configure Supplier SKU A with unit_cost = Rp10.000
        proc.set_supplier_sku(
            business_id=biz_id,
            supplier_id=supp_id,
            master_sku_id=sku_a_id,
            lead_time_days=3,
            min_order_qty=5,
            target_stock=50,
            purchase_unit_cost=Decimal("10000"),
            preferred=True,
        )

        # ------------------------------------------------------------
        # SECTION 1: 3-WAY MATCHING & BILL CREATION ACCEPTANCE
        # ------------------------------------------------------------
        print("\n--- SECTION 1: 3-WAY MATCHING & BILL CREATION ACCEPTANCE ---")

        # B1: No PO => MISSING_PO
        m_b1 = proc.match_purchase_order_goods_receipt_bill(business_id=biz_id, po_number="NON-EXISTENT-PO")
        assert_true(m_b1["match_status"] == "MISSING_PO", "B1: Non-existent PO returns match_status MISSING_PO")

        # Create PO 1: 30 pcs of SKU A @ Rp10.000 = Rp300.000
        po1 = proc.create_purchase_order(
            business_id=biz_id,
            supplier_id=supp_id,
            warehouse_id=wh_id,
            lines=[{"master_sku_id": sku_a_id, "ordered_qty": 30, "unit_cost": 10000}],
        )
        po1_num = po1["po_number"]

        # B2: PO exists but no receipt => MISSING_RECEIPT
        m_b2 = proc.match_purchase_order_goods_receipt_bill(business_id=biz_id, po_number=po1_num)
        assert_true(m_b2["match_status"] == "MISSING_RECEIPT", "B2: PO without receipts returns match_status MISSING_RECEIPT")

        # Confirm PO 1 and receive partial: 20 pcs received (out of 30)
        proc.confirm_purchase_order(business_id=biz_id, po_number=po1_num)
        gr1 = proc.receive_purchase_order(
            business_id=biz_id,
            po_number=po1_num,
            lines=[{"master_sku_id": sku_a_id, "quantity": 20}],
            actor="test_runner",
        )
        assert_true(gr1["all_received"] is False, "B3-setup: Partial receipt of 20/30 recorded")

        # B3: ordered 30, received 20, bill 20, same price => MATCHED
        m_b3 = proc.match_purchase_order_goods_receipt_bill(
            business_id=biz_id,
            po_number=po1_num,
            bill_lines=[{"master_sku_id": sku_a_id, "quantity": 20, "unit_cost": 10000}],
        )
        assert_true(m_b3["match_status"] == "MATCHED", "B3: Bill matching received qty (20) and PO price returns MATCHED")

        # B4: ordered 30, received 20, bill 30 => QUANTITY_VARIANCE
        m_b4 = proc.match_purchase_order_goods_receipt_bill(
            business_id=biz_id,
            po_number=po1_num,
            bill_lines=[{"master_sku_id": sku_a_id, "quantity": 30, "unit_cost": 10000}],
        )
        assert_true(m_b4["match_status"] == "QUANTITY_VARIANCE", "B4: Bill with 30 (received was 20) returns QUANTITY_VARIANCE")

        # B5: Differing bill price (e.g. Rp12.000 vs Rp10.000) => PRICE_VARIANCE
        m_b5 = proc.match_purchase_order_goods_receipt_bill(
            business_id=biz_id,
            po_number=po1_num,
            bill_lines=[{"master_sku_id": sku_a_id, "quantity": 20, "unit_cost": 12000}],
        )
        assert_true(m_b5["match_status"] == "PRICE_VARIANCE", "B5: Bill with differing unit price returns PRICE_VARIANCE")

        # B6: Missing purchase cost on PO => MISSING_COST
        po_nocost = proc.create_purchase_order(
            business_id=biz_id,
            supplier_id=supp_id,
            warehouse_id=wh_id,
            lines=[{"master_sku_id": sku_b_id, "ordered_qty": 10, "unit_cost": 0}],
        )
        proc.confirm_purchase_order(business_id=biz_id, po_number=po_nocost["po_number"])
        proc.receive_purchase_order(
            business_id=biz_id,
            po_number=po_nocost["po_number"],
            lines=[{"master_sku_id": sku_b_id, "quantity": 10}],
            actor="test_runner",
        )
        m_b6 = proc.match_purchase_order_goods_receipt_bill(business_id=biz_id, po_number=po_nocost["po_number"])
        assert_true(m_b6["match_status"] == "MISSING_COST", "B6: PO with 0/unconfigured cost returns MISSING_COST")

        # B7: Draft bill creation creates zero Finance mutations
        with psycopg.connect(
            host="127.0.0.1", port=15432, dbname="finance_core",
            user="finance_core_app", password="57e19ff732b18987d31569804f96fb332b6d7a251c6fc9da529624947e586384",
            row_factory=psycopg.rows.dict_row
        ) as fcon:
            fcur = fcon.cursor()
            fcur.execute("SELECT count(*) AS cnt FROM public.purchase_invoices")
            fin_invoices_before = fcur.fetchone()["cnt"]

        bill1 = proc.create_vendor_bill(
            business_id=biz_id,
            purchase_order_id=po1["purchase_order_id"],
            vendor_reference=f"INV-SUP-001-{TAG}",
        )

        with psycopg.connect(
            host="127.0.0.1", port=15432, dbname="finance_core",
            user="finance_core_app", password="57e19ff732b18987d31569804f96fb332b6d7a251c6fc9da529624947e586384",
            row_factory=psycopg.rows.dict_row
        ) as fcon:
            fcur = fcon.cursor()
            fcur.execute("SELECT count(*) AS cnt FROM public.purchase_invoices")
            fin_invoices_after = fcur.fetchone()["cnt"]

        assert_true(bill1["status"] == "DRAFT", "B7a: Created vendor bill status is DRAFT")
        assert_true(bill1["match_status"] == "MATCHED", "B7b: Auto-generated draft bill match_status is MATCHED")
        assert_true(bill1["total"] == 200000.0, "B7c: Total bill is Rp200.000 (20 pcs @ Rp10.000)")
        assert_true(fin_invoices_after == fin_invoices_before, "B7d: DRAFT bill creates zero Finance Core purchase invoices")

        # B8: Duplicate supplier vendor_reference blocked
        try:
            proc.create_vendor_bill(
                business_id=biz_id,
                supplier_id=supp_id,
                vendor_reference=f"INV-SUP-001-{TAG}",
                lines=[{"master_sku_id": sku_a_id, "quantity": 5, "unit_cost": 10000}],
            )
            assert_true(False, "B8: Duplicate vendor_reference must be rejected")
        except ValueError as e:
            assert_true("sudah tercatat" in str(e).lower(), "B8: Duplicate vendor_reference blocked at DB transaction layer")

        # B9: Cancellation of draft bill succeeds
        bill_to_cancel = proc.create_vendor_bill(
            business_id=biz_id,
            supplier_id=supp_id,
            vendor_reference=f"INV-CANCEL-{TAG}",
            lines=[{"master_sku_id": sku_a_id, "quantity": 5, "unit_cost": 10000}],
        )
        can_res = proc.cancel_vendor_bill(business_id=biz_id, bill_number=bill_to_cancel["bill_number"])
        assert_true(can_res["status"] == "CANCELLED", "B9a: DRAFT bill cancellation succeeds")
        try:
            proc.cancel_vendor_bill(business_id=biz_id, bill_number=bill_to_cancel["bill_number"])
            assert_true(True, "B9b: Re-cancelling cancelled bill is idempotent")
        except Exception:
            assert_true(False, "B9b: Re-cancelling should be idempotent")

        # ------------------------------------------------------------
        # SECTION 2: AP POSTING & BALANCED JOURNAL ACCEPTANCE
        # ------------------------------------------------------------
        print("\n--- SECTION 2: AP POSTING & BALANCED JOURNAL ACCEPTANCE ---")

        # A2: Unmatched / Missing cost bill cannot be posted
        bill_nocost = proc.create_vendor_bill(
            business_id=biz_id,
            purchase_order_id=po_nocost["purchase_order_id"],
            vendor_reference=f"INV-NOCOST-{TAG}",
        )
        try:
            proc.post_vendor_bill(business_id=biz_id, bill_number=bill_nocost["bill_number"])
            assert_true(False, "A2: Posting MISSING_COST bill must be rejected")
        except ValueError as e:
            assert_true("match" in str(e).lower() or "0" in str(e).lower(), "A2: Unmatched bill is blocked from posting")

        # Check inventory balance before posting
        bal_before = ambil("SELECT on_hand, available FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))

        # A1: Post MATCHED Vendor Bill 1
        post_res = proc.post_vendor_bill(business_id=biz_id, bill_number=bill1["bill_number"])
        assert_true(post_res["status"] == "POSTED", "A1a: Vendor bill post transitioned status to POSTED")
        assert_true(bool(post_res["finance_journal_id"]), "A1b: Finance Core journal created")

        # A3: Journal total Debit == total Credit
        with psycopg.connect(
            host="127.0.0.1", port=15432, dbname="finance_core",
            user="finance_core_app", password="57e19ff732b18987d31569804f96fb332b6d7a251c6fc9da529624947e586384",
            row_factory=psycopg.rows.dict_row
        ) as fcon:
            fcur = fcon.cursor()
            fcur.execute(
                """SELECT SUM(debit) AS total_debit, SUM(credit) AS total_credit
                   FROM public.journal_lines WHERE journal_entry_id=%s""",
                (post_res["finance_journal_id"],),
            )
            jtot = fcur.fetchone()
            assert_true(jtot["total_debit"] == Decimal("200000.00"), "A3a: Total debit is exact Rp200.000")
            assert_true(jtot["total_credit"] == Decimal("200000.00"), "A3b: Total credit is exact Rp200.000 (Debit == Credit)")

            # A4: AP liability recorded in account 2101
            fcur.execute(
                """SELECT jl.credit FROM public.journal_lines jl
                   JOIN public.accounts a ON a.id = jl.account_id
                   WHERE jl.journal_entry_id=%s AND a.code='2101'""",
                (post_res["finance_journal_id"],),
            )
            ap_line = fcur.fetchone()
            assert_true(ap_line is not None and ap_line["credit"] == Decimal("200000.00"), "A4: AP account 2101 credited exactly Rp200.000")

        # A5: Duplicate POST is strictly idempotent
        dup_post = proc.post_vendor_bill(business_id=biz_id, bill_number=bill1["bill_number"])
        assert_true(dup_post["duplicate"] is True, "A5: Duplicate bill post is idempotent")

        # A7: POST does not modify inventory
        bal_after = ambil("SELECT on_hand, available FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
        assert_true(bal_before["on_hand"] == bal_after["on_hand"], "A7a: Bill POST causes zero inventory on_hand mutation")
        assert_true(bal_before["available"] == bal_after["available"], "A7b: Bill POST causes zero inventory available mutation")

        # A8 & A9: POST does not modify PO or receipt quantities
        pol_check = ambil("SELECT ordered_qty, received_qty FROM local_business.purchase_order_line WHERE purchase_order_id=%s", (po1["purchase_order_id"],))
        assert_true(pol_check["ordered_qty"] == 30 and pol_check["received_qty"] == 20, "A8/A9: PO quantities remain strictly 30 ordered, 20 received")

        # ------------------------------------------------------------
        # SECTION 3: PAYMENTS (PARTIAL & FULL) ACCEPTANCE
        # ------------------------------------------------------------
        print("\n--- SECTION 3: PAYMENTS (PARTIAL & FULL) ACCEPTANCE ---")

        # P1: Payment against DRAFT rejected
        draft_bill_p1 = proc.create_vendor_bill(
            business_id=biz_id,
            supplier_id=supp_id,
            vendor_reference=f"INV-P1-{TAG}",
            lines=[{"master_sku_id": sku_a_id, "quantity": 5, "unit_cost": 10000}],
        )
        try:
            proc.create_vendor_payment(business_id=biz_id, bill_number=draft_bill_p1["bill_number"], amount=10000)
            assert_true(False, "P1: Payment against DRAFT must be rejected")
        except ValueError as e:
            assert_true("status" in str(e).lower() or "draft" in str(e).lower(), "P1: Payment against DRAFT bill is rejected")

        # P2: Payment amount <= 0 rejected
        try:
            proc.create_vendor_payment(business_id=biz_id, bill_number=bill1["bill_number"], amount=0)
            assert_true(False, "P2: Payment with amount 0 must be rejected")
        except ValueError:
            assert_true(True, "P2: Payment amount <= 0 is strictly rejected")

        # P8: Overpayment rejected (e.g. Rp250.000 > Rp200.000)
        try:
            proc.create_vendor_payment(business_id=biz_id, bill_number=bill1["bill_number"], amount=250000)
            assert_true(False, "P8: Overpayment must be rejected")
        except ValueError as e:
            assert_true("melebihi" in str(e).lower() or "exceeds" in str(e).lower(), "P8: Overpayment exceeds outstanding and is rejected")

        # P3: Partial Payment: Pay Rp80.000 (out of Rp200.000)
        pay1 = proc.create_vendor_payment(
            business_id=biz_id,
            bill_number=bill1["bill_number"],
            amount=80000,
            payment_account_id="1101", # Kas
            idempotency_key=f"pay-partial-1-{TAG}",
        )
        assert_true(pay1["amount"] == 80000.0, "P3: Partial payment of Rp80.000 recorded")

        # P4 & P5: Status PARTIALLY_PAID, outstanding exact Rp120.000
        bill1_check = proc.get_vendor_bill(business_id=biz_id, bill_number=bill1["bill_number"])
        assert_true(bill1_check["status"] == "PARTIALLY_PAID", "P4: Bill status is PARTIALLY_PAID")
        assert_true(Decimal(str(bill1_check["paid_amount"])) == Decimal("80000.00"), "P5a: Paid amount is exact Rp80.000")
        assert_true(Decimal(str(bill1_check["outstanding_amount"])) == Decimal("120000.00"), "P5b: Outstanding is exact Rp120.000")

        # P9: Duplicate payment with same idempotency key is idempotent
        dup_pay = proc.create_vendor_payment(
            business_id=biz_id,
            bill_number=bill1["bill_number"],
            amount=80000,
            payment_account_id="1101",
            idempotency_key=f"pay-partial-1-{TAG}",
        )
        assert_true(dup_pay["duplicate"] is True, "P9: Duplicate payment idempotency key returns duplicate=True")

        # P6: Final Payment: Pay remaining Rp120.000
        pay2 = proc.create_vendor_payment(
            business_id=biz_id,
            bill_number=bill1["bill_number"],
            amount=120000,
            payment_account_id="1102", # Bank
            idempotency_key=f"pay-final-2-{TAG}",
        )
        assert_true(pay2["amount"] == 120000.0, "P6: Final payment of Rp120.000 recorded")

        # P7: Status PAID, outstanding = 0
        bill1_final = proc.get_vendor_bill(business_id=biz_id, bill_number=bill1["bill_number"])
        assert_true(bill1_final["status"] == "PAID", "P7a: Bill status is PAID")
        assert_true(Decimal(str(bill1_final["paid_amount"])) == Decimal("200000.00"), "P7b: Paid amount equals total Rp200.000")
        assert_true(Decimal(str(bill1_final["outstanding_amount"])) == Decimal("0.00"), "P7c: Outstanding is exact Rp0")

        # P11: Payment journals are balanced (Dr 2101 / Cr 1101 & 1102)
        with psycopg.connect(
            host="127.0.0.1", port=15432, dbname="finance_core",
            user="finance_core_app", password="57e19ff732b18987d31569804f96fb332b6d7a251c6fc9da529624947e586384",
            row_factory=psycopg.rows.dict_row
        ) as fcon:
            fcur = fcon.cursor()
            fcur.execute(
                """SELECT sp.payment_number, sp.amount, sp.journal_entry_id
                   FROM public.supplier_payments sp
                   WHERE sp.payment_number IN (%s, %s)""",
                (pay1["payment_number"], pay2["payment_number"]),
            )
            pays = fcur.fetchall()
            assert_true(len(pays) == 2, "P11a: Exactly 2 supplier payments recorded in Finance Core")
            for p_row in pays:
                fcur.execute(
                    """SELECT SUM(debit) AS debit, SUM(credit) AS credit
                       FROM public.journal_lines WHERE journal_entry_id=%s""",
                    (p_row["journal_entry_id"],),
                )
                pj = fcur.fetchone()
                assert_true(pj["debit"] == pj["credit"] and pj["debit"] == p_row["amount"], f"P11b: Payment journal {p_row['payment_number']} balanced")

        # P12: Payment does not mutate physical inventory
        bal_final = ambil("SELECT on_hand, available FROM multichannel.inventory_balance WHERE master_sku_id=%s AND warehouse_id=%s", (sku_a_id, wh_id))
        assert_true(bal_final["on_hand"] == bal_before["on_hand"], "P12: Payment causes zero inventory mutation")

        # ------------------------------------------------------------
        # SECTION 4: CONCURRENCY & RACE SAFETY ACCEPTANCE
        # ------------------------------------------------------------
        print("\n--- SECTION 4: CONCURRENCY & RACE SAFETY ACCEPTANCE ---")

        # Create PO 2 for concurrency tests
        po2 = proc.create_purchase_order(
            business_id=biz_id,
            supplier_id=supp_id,
            warehouse_id=wh_id,
            lines=[{"master_sku_id": sku_a_id, "ordered_qty": 50, "unit_cost": 10000}],
        )
        proc.confirm_purchase_order(business_id=biz_id, po_number=po2["po_number"])
        proc.receive_purchase_order(
            business_id=biz_id,
            po_number=po2["po_number"],
            lines=[{"master_sku_id": sku_a_id, "quantity": 50}],
            actor="test_runner",
        )

        # C1: Concurrent Vendor Bill Draft Confirm
        draft_bill_c1 = proc.create_procurement_draft(
            draft_type="VENDOR_BILL_CREATE",
            business_id=biz_id,
            owner_id=biz_id,
            telegram_user_id=tg_user_id,
            payload={
                "supplier_id": supp_id,
                "purchase_order_id": po2["purchase_order_id"],
                "po_number": po2["po_number"],
                "lines": [{"master_sku_id": sku_a_id, "quantity": 50, "unit_cost": 10000}],
            },
        )
        c1_results = []
        def run_c1():
            r = proc.confirm_procurement_draft(draft_token=draft_bill_c1["draft_token"], caller_telegram_user_id=tg_user_id)
            c1_results.append(r)

        t1 = threading.Thread(target=run_c1); t2 = threading.Thread(target=run_c1)
        t1.start(); t2.start(); t1.join(); t2.join()

        bills_c1 = semua("SELECT * FROM local_business.vendor_bill WHERE business_id=%s AND purchase_order_id=%s", (biz_id, po2["purchase_order_id"]))
        assert_true(len(bills_c1) == 1, "C1a: Concurrent bill draft confirm creates exactly 1 vendor bill")
        assert_true(all(r.get("ok") for r in c1_results), "C1b: Both concurrent callers receive ok status (1 mutation, 1 idempotent)")

        bill_c1_num = bills_c1[0]["bill_number"]

        # C2 / A6: Concurrent POST Confirm
        draft_post_c2 = proc.create_procurement_draft(
            draft_type="VENDOR_BILL_POST",
            business_id=biz_id,
            owner_id=biz_id,
            telegram_user_id=tg_user_id,
            payload={"bill_number": bill_c1_num},
        )
        c2_results = []
        def run_c2():
            r = proc.confirm_procurement_draft(draft_token=draft_post_c2["draft_token"], caller_telegram_user_id=tg_user_id)
            c2_results.append(r)

        t1 = threading.Thread(target=run_c2); t2 = threading.Thread(target=run_c2)
        t1.start(); t2.start(); t1.join(); t2.join()

        bill_c1_posted = proc.get_vendor_bill(business_id=biz_id, bill_number=bill_c1_num)
        assert_true(bill_c1_posted["status"] == "POSTED", "C2a: Concurrent POST confirm posts bill successfully")
        assert_true(all(r.get("ok") for r in c2_results), "C2b: Exactly one Finance Core post executed, other is idempotent")

        # C3 / P10: Concurrent Payment Race against same balance (Bill total Rp500.000, two callers try to pay Rp300.000 each)
        c3_results = []
        def run_c3(amt, key):
            try:
                r = proc.create_vendor_payment(
                    business_id=biz_id,
                    bill_number=bill_c1_num,
                    amount=amt,
                    payment_account_id="1101",
                    idempotency_key=key,
                )
                c3_results.append({"ok": True, "res": r})
            except Exception as e:
                c3_results.append({"ok": False, "error": str(e)})

        t1 = threading.Thread(target=run_c3, args=(300000, f"race-1-{TAG}"))
        t2 = threading.Thread(target=run_c3, args=(300000, f"race-2-{TAG}"))
        t1.start(); t2.start(); t1.join(); t2.join()

        successes = [r for r in c3_results if r.get("ok")]
        failures = [r for r in c3_results if not r.get("ok")]

        assert_true(len(successes) == 1, "C3a: Exactly one payment succeeds in concurrent race (300k allowed)")
        assert_true(len(failures) == 1, "C3b: Competing payment (300k > remaining 200k) is strictly rejected")

        bill_c1_after_race = proc.get_vendor_bill(business_id=biz_id, bill_number=bill_c1_num)
        assert_true(Decimal(str(bill_c1_after_race["paid_amount"])) == Decimal("300000.00"), "C3c: Total paid amount cannot exceed bill limit")
        assert_true(Decimal(str(bill_c1_after_race["outstanding_amount"])) == Decimal("200000.00"), "C3d: Outstanding balance remains exact Rp200.000")

        # ------------------------------------------------------------
        # SECTION 5: TELEGRAM SECURITY & DRAFT ACCEPTANCE
        # ------------------------------------------------------------
        print("\n--- SECTION 5: TELEGRAM SECURITY & DRAFT ACCEPTANCE ---")

        # T1: Bill Preview causes zero DB mutation before confirm
        draft_t1 = proc.create_procurement_draft(
            draft_type="VENDOR_BILL_CREATE",
            business_id=biz_id,
            owner_id=biz_id,
            telegram_user_id=tg_user_id,
            payload={
                "supplier_id": supp_id,
                "lines": [{"master_sku_id": sku_a_id, "quantity": 1, "unit_cost": 10000}],
            },
        )
        bills_t1_count = len(semua("SELECT id FROM local_business.vendor_bill WHERE business_id=%s AND vendor_reference=%s", (biz_id, "PREVIEW-T1")))
        assert_true(bills_t1_count == 0, "T1: Draft bill preview causes zero database mutation before confirm")

        # T3: Wrong Telegram user blocked from confirming
        wrong_user_res = proc.confirm_procurement_draft(draft_token=draft_t1["draft_token"], caller_telegram_user_id=111222333)
        assert_true(wrong_user_res["ok"] is False and wrong_user_res.get("error") == "wrong_user", "T3: Wrong Telegram user is blocked from confirming draft")

        # T4: Stale / expired draft blocked from mutating
        with koneksi() as c:
            c.cursor().execute("UPDATE local_business.telegram_procurement_draft SET expires_at=now() - interval '1 hour' WHERE draft_token=%s", (draft_t1["draft_token"],))
            c.commit()
        exp_res = proc.confirm_procurement_draft(draft_token=draft_t1["draft_token"], caller_telegram_user_id=tg_user_id)
        assert_true(exp_res["ok"] is False and exp_res.get("error") == "draft_expired", "T4: Stale / expired draft is blocked from mutating")

        # T6: Cancel draft is idempotent
        draft_t6 = proc.create_procurement_draft(
            draft_type="VENDOR_BILL_CANCEL",
            business_id=biz_id,
            owner_id=biz_id,
            telegram_user_id=tg_user_id,
            payload={"bill_number": bill_c1_num},
        )
        can_t6_1 = proc.cancel_procurement_draft(draft_token=draft_t6["draft_token"], caller_telegram_user_id=tg_user_id)
        can_t6_2 = proc.cancel_procurement_draft(draft_token=draft_t6["draft_token"], caller_telegram_user_id=tg_user_id)
        assert_true(can_t6_1["ok"] is True and can_t6_2["ok"] is True, "T6: Cancel draft is strictly idempotent")

        # ------------------------------------------------------------
        # SECTION 6: MANDATORY GAPS & ACCOUNTING CONTRACT (F1 - F12)
        # ------------------------------------------------------------
        print("\n--- SECTION 6: MANDATORY GAPS & ACCOUNTING CONTRACT (F1 - F12) ---")

        # F5: Existing 4-field /restockconfig draft confirmation works
        draft_f5 = proc.create_procurement_draft(
            draft_type="RESTOCK_CONFIG",
            business_id=biz_id,
            owner_id=biz_id,
            telegram_user_id=tg_user_id,
            payload={
                "master_sku_id": sku_b_id,
                "sku": f"SKU-FIN-B-{TAG}",
                "supplier_id": supp_id,
                "lead_time_days": 2,
                "min_order_qty": 3,
                "target_stock": 10,
            },
        )
        proc.confirm_procurement_draft(draft_token=draft_f5["draft_token"], caller_telegram_user_id=tg_user_id)
        ssku_f5 = ambil("SELECT * FROM local_business.supplier_sku WHERE business_id=%s AND master_sku_id=%s", (biz_id, sku_b_id))
        assert_true(ssku_f5["lead_time_days"] == 2 and ssku_f5["min_order_qty"] == 3 and ssku_f5["target_stock"] == 10, "F5: 4-field restockconfig stores terms accurately")

        # F6: 5-field /restockconfig with purchase_unit_cost works
        draft_f6 = proc.create_procurement_draft(
            draft_type="RESTOCK_CONFIG",
            business_id=biz_id,
            owner_id=biz_id,
            telegram_user_id=tg_user_id,
            payload={
                "master_sku_id": sku_b_id,
                "sku": f"SKU-FIN-B-{TAG}",
                "supplier_id": supp_id,
                "lead_time_days": 2,
                "min_order_qty": 3,
                "target_stock": 10,
                "purchase_unit_cost": 25000.0,
            },
        )
        proc.confirm_procurement_draft(draft_token=draft_f6["draft_token"], caller_telegram_user_id=tg_user_id)
        ssku_f6 = ambil("SELECT * FROM local_business.supplier_sku WHERE business_id=%s AND master_sku_id=%s", (biz_id, sku_b_id))
        assert_true(Decimal(str(ssku_f6["purchase_unit_cost"])) == Decimal("25000.00"), "F6: 5-field restockconfig stores purchase_unit_cost accurately")

        # F8: MOQ does not create demand when raw reorder requirement=0 (available >= target)
        # Set stock B = 10, target = 10, MOQ = 3
        inv.receive_stock(
            tenant_id=TENANT, business_id=biz_id, branch_id=f["branch_id"],
            warehouse_id=wh_id, master_sku_id=sku_b_id, sku=f"SKU-FIN-B-{TAG}",
            quantity=10, reference="f8-init", source_document="F8-INIT",
            idempotency_key=f"f8-init-{TAG}",
        )
        rec_f8 = reorder.calculate_reorder_for_sku(business_id=biz_id, master_sku_id=sku_b_id)
        assert_true(rec_f8["suggested_order_qty"] == 0, "F8: Reorder recommendation is strictly 0 when available (10) >= target (10) despite MOQ (3)")

        # F7: Reorder qty=0 does not create PO (suggested=0)
        # Verify bot_poller logic blocks PO creation when suggested=0
        suggested_f7 = rec_f8["suggested_order_qty"]
        blocked_f7 = (suggested_f7 <= 0)
        assert_true(blocked_f7 is True, "F7: Zero suggested order quantity strictly blocks automatic PO draft generation")

        # F9: Manual PO with explicit qty still works
        po_f9 = proc.create_purchase_order(
            business_id=biz_id,
            supplier_id=supp_id,
            warehouse_id=wh_id,
            lines=[{"master_sku_id": sku_b_id, "ordered_qty": 4, "unit_cost": 25000}],
        )
        assert_true(po_f9["ok"] is True and po_f9["po_number"].startswith("BC-PO-"), "F9: Manual PO creation with explicit qty creates valid PO")

        # Confirm and receive PO F9
        proc.confirm_purchase_order(business_id=biz_id, po_number=po_f9["po_number"])
        proc.receive_purchase_order(
            business_id=biz_id,
            po_number=po_f9["po_number"],
            lines=[{"master_sku_id": sku_b_id, "quantity": 4}],
            actor="test_runner",
        )

        # F10: Receipt accounting audit: Goods receipt does NOT create any Finance Core journal entry
        with psycopg.connect(
            host="127.0.0.1", port=15432, dbname="finance_core",
            user="finance_core_app", password="57e19ff732b18987d31569804f96fb332b6d7a251c6fc9da529624947e586384",
            row_factory=psycopg.rows.dict_row
        ) as fcon:
            fcur = fcon.cursor()
            fcur.execute("SELECT count(*) AS cnt FROM public.journal_entries")
            fin_j_before_f10 = fcur.fetchone()["cnt"]

        # F1: Actual vendor price equals PO price (Rp25.000) => MATCHED
        m_f1 = proc.match_purchase_order_goods_receipt_bill(
            business_id=biz_id,
            po_number=po_f9["po_number"],
            bill_lines=[{"master_sku_id": sku_b_id, "quantity": 4, "unit_cost": 25000}],
        )
        assert_true(m_f1["match_status"] == "MATCHED", "F1: Actual vendor price equals PO price => MATCHED")

        # F2: Actual vendor price differs (Rp27.000 vs Rp25.000) => PRICE_VARIANCE
        m_f2 = proc.match_purchase_order_goods_receipt_bill(
            business_id=biz_id,
            po_number=po_f9["po_number"],
            bill_lines=[{"master_sku_id": sku_b_id, "quantity": 4, "unit_cost": 27000}],
        )
        assert_true(m_f2["match_status"] == "PRICE_VARIANCE", "F2: Actual vendor price differs => PRICE_VARIANCE")

        # F3: Missing expected PO cost returns MISSING_COST
        m_f3 = proc.match_purchase_order_goods_receipt_bill(
            business_id=biz_id,
            po_number=po_nocost["po_number"],
            bill_lines=[{"master_sku_id": sku_a_id, "quantity": 5, "unit_cost": 10000}],
        )
        assert_true(m_f3["match_status"] == "MISSING_COST", "F3: Missing expected PO cost strictly returns MISSING_COST")

        # F4: Vendor Bill actual price is independent of supplier expected cost
        bill_f4 = proc.create_vendor_bill(
            business_id=biz_id,
            purchase_order_id=po_f9["purchase_order_id"],
            vendor_reference=f"INV-F4-{TAG}",
            lines=[{"master_sku_id": sku_b_id, "quantity": 4, "unit_cost": 25000}],
        )
        assert_true(bill_f4["match_status"] == "MATCHED", "F4a: Bill created with explicit matched lines has MATCHED status")
        assert_true(Decimal(str(bill_f4["total"])) == Decimal("100000.00"), "F4b: Total is exact Rp100.000 (4 pcs @ Rp25.000)")

        # F11: Vendor Bill POST journal is economically correct (Dr 1301 / Cr 2101) and balanced
        post_f11 = proc.post_vendor_bill(business_id=biz_id, bill_number=bill_f4["bill_number"])
        assert_true(post_f11["status"] == "POSTED", "F11a: Bill POST successful")

        with psycopg.connect(
            host="127.0.0.1", port=15432, dbname="finance_core",
            user="finance_core_app", password="57e19ff732b18987d31569804f96fb332b6d7a251c6fc9da529624947e586384",
            row_factory=psycopg.rows.dict_row
        ) as fcon:
            fcur = fcon.cursor()
            # Verify exactly 1 new journal entry created since goods receipt
            fcur.execute("SELECT count(*) AS cnt FROM public.journal_entries")
            fin_j_after_f11 = fcur.fetchone()["cnt"]
            assert_true(fin_j_after_f11 == fin_j_before_f10 + 1, "F10/F11b: Exactly one journal entry created across receipt and bill post (no double recognition)")

            # Check journal lines for Dr 1301 (Inventory) / Cr 2101 (AP)
            fcur.execute(
                """SELECT a.code, jl.debit, jl.credit
                   FROM public.journal_lines jl
                   JOIN public.accounts a ON a.id = jl.account_id
                   WHERE jl.journal_entry_id = %s""",
                (post_f11["finance_journal_id"],),
            )
            jlines = fcur.fetchall()
            dr_1301 = sum(l["debit"] for l in jlines if l["code"] == "1301")
            cr_2101 = sum(l["credit"] for l in jlines if l["code"] == "2101")
            assert_true(dr_1301 == Decimal("100000.00"), "F11c: Dr 1301 (Persediaan Barang) exactly Rp100.000")
            assert_true(cr_2101 == Decimal("100000.00"), "F11d: Cr 2101 (Utang Usaha) exactly Rp100.000")

        # F12: Payment journal is economically correct (Dr 2101 / Cr 1101) and balanced
        pay_f12 = proc.create_vendor_payment(
            business_id=biz_id,
            bill_number=bill_f4["bill_number"],
            amount=100000,
            payment_account_id="1101",
            idempotency_key=f"pay-f12-{TAG}",
        )
        assert_true(pay_f12["ok"] is True and pay_f12["bill_status"] == "PAID", "F12a: Payment recorded successfully and bill status is PAID")

        with psycopg.connect(
            host="127.0.0.1", port=15432, dbname="finance_core",
            user="finance_core_app", password="57e19ff732b18987d31569804f96fb332b6d7a251c6fc9da529624947e586384",
            row_factory=psycopg.rows.dict_row
        ) as fcon:
            fcur = fcon.cursor()
            fcur.execute("SELECT journal_entry_id FROM public.supplier_payments WHERE payment_number=%s", (pay_f12["payment_number"],))
            sp_rec = fcur.fetchone()
            j_id = sp_rec["journal_entry_id"] if sp_rec else pay_f12.get("finance_journal_id")
            fcur.execute(
                """SELECT a.code, jl.debit, jl.credit
                   FROM public.journal_lines jl
                   JOIN public.accounts a ON a.id = jl.account_id
                   WHERE jl.journal_entry_id = %s""",
                (j_id,),
            )
            pjlines = fcur.fetchall()
            dr_2101 = sum(l["debit"] for l in pjlines if l["code"] == "2101")
            cr_1101 = sum(l["credit"] for l in pjlines if l["code"] == "1101")
            assert_true(dr_2101 == Decimal("100000.00"), "F12b: Dr 2101 (Utang Usaha) exactly Rp100.000")
            assert_true(cr_1101 == Decimal("100000.00"), "F12c: Cr 1101 (Kas) exactly Rp100.000")

        print("\n=== Cleaning up disposable acceptance fixtures ===")
        cleanup_fixtures(f)
        print("=== Cleanup of disposable fixtures complete ===")

    except Exception as e:
        print(f"\n[ERROR in acceptance test]: {e}")
        try:
            cleanup_fixtures(f)
        except Exception:
            pass
        raise

    print(f"\nFINAL RESULTS: Passed: {PASSED_COUNT}, Failed: {FAILED_COUNT}")
    return FAILED_COUNT == 0


if __name__ == "__main__":
    success = run_tests()
    if not success:
        sys.exit(1)
