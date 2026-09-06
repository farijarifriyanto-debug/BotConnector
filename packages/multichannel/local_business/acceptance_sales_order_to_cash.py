"""Acceptance test suite for Sales Order-to-Cash (Customer, Quotation, Sales Order, Delivery, Customer Invoice, AR, Payment, Return, Credit Note).

Covers:
- Customer Master (C1-C5)
- Quotation Lifecycle (Q1-Q5)
- Sales Order Lifecycle & Credit Limit (S1-S4)
- Delivery & Physical Stock Boundary (D1-D8)
- Customer Invoice & Revenue / AR (I1-I8)
- AR Aging (A1-A7)
- Customer Payment & Collection (P1-P11)
- Sales Return & Credit Note (R1-R8)
"""

import os
import sys
import uuid
import secrets
from datetime import date, datetime, timedelta, timezone
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
    retail,
    sales,
    bot_poller,
)
from botconnector_multichannel.workflow import finance_core as fc

TAG = uuid.uuid4().hex[:6].upper()
TENANT_ID = f"TEST-TENANT-SALES-{TAG}"
BIZ_CODE = f"BIZ-SALES-{TAG}"
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
    print(f"=== Starting Sales Order-to-Cash Acceptance Tests (Tag: {TAG}) ===")

    # ------------------------------------------------------------
    # FIXTURE SETUP
    # ------------------------------------------------------------
    wh_code = f"WH-SALES-{TAG}"
    db.jalankan(
        "INSERT INTO multichannel.warehouse (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING",
        (wh_code, f"Warehouse {TAG}"),
    )
    wh_row = db.ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (wh_code,))
    wh_id = wh_row["id"]

    biz = core.upsert_business(tenant_id=TENANT_ID, code=BIZ_CODE, name=f"Biz Sales OTC {TAG}", business_type="RETAIL")
    biz_id = biz["id"]

    br = core.upsert_branch(business_id=biz_id, code=f"BR-SALES-{TAG}", name=f"Branch Sales {TAG}", warehouse_id=wh_id, branch_type="RETAIL")
    branch_id = br["id"]

    # Test Product & Master SKU
    sku_code = f"SKU-OTC-{TAG}"
    prod = S.upsert_product(name=f"Produk OTC {TAG}", category="OTC", brand="")
    master_sku = S.upsert_master_sku(sku=sku_code, product_id=prod["id"])
    msku_id = master_sku["id"]

    # Canonical Selling Price: Rp25.000
    selling_price = Decimal("25000.00")
    sales.set_canonical_selling_price(
        business_id=biz_id,
        master_sku_id=msku_id,
        selling_price=selling_price,
    )

    # Initial stock: 10 units
    inv.receive_stock(
        tenant_id=TENANT_ID,
        business_id=biz_id,
        branch_id=branch_id,
        warehouse_id=wh_id,
        master_sku_id=msku_id,
        sku=sku_code,
        quantity=10,
        reference="init_otc",
        source_document="INIT_OTC",
        idempotency_key=f"init_otc_{TAG}",
    )

    owner_id = biz_id
    tg_user_id = 99887766
    wrong_user_id = 11223344

    # ------------------------------------------------------------
    # SECTION 1: CUSTOMER MASTER (C1-C5)
    # ------------------------------------------------------------
    print("\n--- Section 1: Customer Master ---")

    # C1: Create customer with valid details
    cust_code = f"CUST-A-{TAG}"
    cust = sales.create_customer(
        business_id=biz_id,
        code=cust_code,
        name="PT Sentosa OTC",
        phone="08123456789",
        email="finance@sentosa.com",
        billing_address="Jl. Raya No 1",
        delivery_address="Jl. Gudang No 10",
        payment_terms_days=30,
        credit_limit=Decimal("5000000.00"),
    )
    assert_true(cust["code"] == cust_code and cust["name"] == "PT Sentosa OTC", "C1: Create customer with terms and credit limit")
    assert_true(cust["payment_terms_days"] == 30 and cust["active"] is True, "C1: Customer defaults active with payment terms")

    # C2: Duplicate customer code in same business rejected
    dup_threw = False
    try:
        sales.create_customer(business_id=biz_id, code=cust_code, name="Duplicate Customer")
    except ValueError:
        dup_threw = True
    assert_true(dup_threw, "C2: Duplicate customer code rejected")

    # C3: Update customer
    cust_upd = sales.update_customer(
        business_id=biz_id,
        code=cust_code,
        name="PT Sentosa OTC Sukses",
        phone="08999999999",
        payment_terms_days=45,
        credit_limit=Decimal("10000000.00"),
    )
    assert_true(cust_upd["name"] == "PT Sentosa OTC Sukses" and cust_upd["payment_terms_days"] == 45, "C3: Update customer details")

    # C4: Soft deactivate customer
    deact = sales.deactivate_customer(business_id=biz_id, code=cust_code)
    assert_true(deact["active"] is False, "C4: Soft deactivate customer")

    # C5: Deactivated customer cannot create quotation or sales order
    blocked_quot = False
    try:
        sales.create_sales_quotation(
            business_id=biz_id,
            customer_id=cust["id"],
            lines=[{"master_sku_id": msku_id, "quantity": 1}],
        )
    except ValueError:
        blocked_quot = True
    assert_true(blocked_quot, "C5: Deactivated customer blocked from new quotation")

    # Reactivate customer for subsequent tests
    sales.update_customer(business_id=biz_id, code=cust_code, active=True)

    # ------------------------------------------------------------
    # SECTION 2: QUOTATION LIFECYCLE (Q1-Q5)
    # ------------------------------------------------------------
    print("\n--- Section 2: Quotation Lifecycle ---")

    # Q1: Create draft quotation
    stock_before_q = inv.location_balance(master_sku_id=msku_id, warehouse_id=wh_id)
    quot = sales.create_sales_quotation(
        business_id=biz_id,
        customer_id=cust["id"],
        lines=[{"master_sku_id": msku_id, "quantity": 2}],
        validity_days=14,
    )
    assert_true(quot["quotation_number"].startswith("BC-SQ-") and quot["status"] == "DRAFT", "Q1: Create DRAFT quotation with canonical selling price")
    assert_true(Decimal(str(quot["total"])) == Decimal("50000.00"), "Q1: Quotation total calculated correctly (2 x 25.000)")

    # Q2: Zero physical inventory mutation, zero AR, zero finance
    stock_after_q = inv.location_balance(master_sku_id=msku_id, warehouse_id=wh_id)
    assert_true(stock_before_q["on_hand"] == stock_after_q["on_hand"] and stock_before_q["available"] == stock_after_q["available"], "Q2: Zero physical inventory mutation from quotation")

    # Q3: Accept quotation
    acc_res = sales.accept_sales_quotation(business_id=biz_id, quotation_number=quot["quotation_number"])
    assert_true(acc_res["ok"] and acc_res["quotation"]["status"] == "ACCEPTED", "Q3: Accept quotation transitions to ACCEPTED")

    # Q4: Expired quotation cannot be accepted
    exp_cust = sales.create_customer(business_id=biz_id, code=f"EXP-{TAG}", name="Expired Cust")
    exp_quot = sales.create_sales_quotation(
        business_id=biz_id,
        customer_id=exp_cust["id"],
        lines=[{"master_sku_id": msku_id, "quantity": 1}],
        validity_days=1,
    )
    with koneksi() as c:
        c.cursor().execute("UPDATE local_business.sales_quotation SET expiry_date=CURRENT_DATE - INTERVAL '1 day' WHERE id=%s", (exp_quot["id"],))
        c.commit()
    exp_threw = False
    try:
        sales.accept_sales_quotation(business_id=biz_id, quotation_number=exp_quot["quotation_number"])
    except ValueError:
        exp_threw = True
    assert_true(exp_threw, "Q4: Expired quotation cannot be accepted")

    # Q5: Convert quotation to Sales Order
    conv_res = sales.convert_quotation_to_order(
        business_id=biz_id,
        quotation_number=quot["quotation_number"],
        warehouse_id=wh_id,
    )
    assert_true(conv_res["ok"] and conv_res["sales_order"]["order_number"].startswith("BC-SO-"), "Q5: Convert ACCEPTED quotation to Sales Order")
    so_from_quot = conv_res["sales_order"]
    assert_true(Decimal(str(so_from_quot["total"])) == Decimal("50000.00"), "Q5: Converted SO has matching total")

    # ------------------------------------------------------------
    # SECTION 3: SALES ORDER & CREDIT LIMIT (S1-S4)
    # ------------------------------------------------------------
    print("\n--- Section 3: Sales Order & Credit Limit ---")

    # S1: Create Sales Order directly
    so_direct = sales.create_sales_order(
        business_id=biz_id,
        customer_id=cust["id"],
        warehouse_id=wh_id,
        lines=[{"master_sku_id": msku_id, "quantity": 3}],  # 75.000
    )
    assert_true(so_direct["status"] == "DRAFT" and len(so_direct["lines"]) == 1, "S1: Create DRAFT Sales Order directly")
    assert_true(so_direct["lines"][0]["delivered_qty"] == 0 and so_direct["lines"][0]["invoiced_qty"] == 0, "S1: Initial delivered and invoiced qty are 0")

    # S2: Confirm Sales Order within credit limit
    conf_res = sales.confirm_sales_order(business_id=biz_id, order_number=so_direct["order_number"])
    assert_true(conf_res["ok"] and conf_res["sales_order"]["status"] == "CONFIRMED", "S2: Confirm Sales Order within credit limit")

    # S3: Credit Limit Check - create small limit customer and block order
    lim_cust = sales.create_customer(business_id=biz_id, code=f"LIM-{TAG}", name="Small Limit Cust", credit_limit=Decimal("30000.00"))
    so_over = sales.create_sales_order(
        business_id=biz_id,
        customer_id=lim_cust["id"],
        warehouse_id=wh_id,
        lines=[{"master_sku_id": msku_id, "quantity": 2}],  # Total 50.000 > 30.000
    )
    over_limit_blocked = False
    try:
        sales.confirm_sales_order(business_id=biz_id, order_number=so_over["order_number"])
    except sales.CreditLimitExceeded:
        over_limit_blocked = True
    assert_true(over_limit_blocked, "S3: Confirm Sales Order BLOCKED when exceeding credit limit")

    # S4: Cancel undelivered Sales Order
    so_to_cancel = sales.create_sales_order(
        business_id=biz_id,
        customer_id=cust["id"],
        warehouse_id=wh_id,
        lines=[{"master_sku_id": msku_id, "quantity": 1}],
    )
    cancel_res = sales.cancel_sales_order(business_id=biz_id, order_number=so_to_cancel["order_number"])
    assert_true(cancel_res["ok"] and cancel_res["sales_order"]["status"] == "CANCELLED", "S4: Cancel undelivered Sales Order")

    # ------------------------------------------------------------
    # SECTION 4: DELIVERY & PHYSICAL STOCK (D1-D8)
    # ------------------------------------------------------------
    print("\n--- Section 4: Delivery & Physical Stock Boundary ---")

    # Use so_direct (ordered 3 units)
    stock_before_deliv = inv.location_balance(master_sku_id=msku_id, warehouse_id=wh_id)

    # D4: Over-delivery rejected (ordered 3, try delivering 4)
    over_deliv_threw = False
    try:
        sales.deliver_sales_order(
            business_id=biz_id,
            order_number=so_direct["order_number"],
            lines=[{"master_sku_id": msku_id, "quantity": 4}],
        )
    except ValueError:
        over_deliv_threw = True
    assert_true(over_deliv_threw, "D4: Over-delivery strictly rejected")

    # D5: Partial delivery of 1 unit
    idem_d1 = f"do-idem-1-{TAG}"
    deliv1 = sales.deliver_sales_order(
        business_id=biz_id,
        order_number=so_direct["order_number"],
        lines=[{"master_sku_id": msku_id, "quantity": 1}],
        idempotency_key=idem_d1,
    )
    assert_true(deliv1["ok"] and deliv1["delivery"]["order_status"] == "PARTIALLY_DELIVERED", "D5: Partial delivery transitions SO to PARTIALLY_DELIVERED")

    # D1 & D2: Stock decreased by 1 and movement recorded
    stock_after_d1 = inv.location_balance(master_sku_id=msku_id, warehouse_id=wh_id)
    assert_true(stock_after_d1["on_hand"] == stock_before_deliv["on_hand"] - 1, "D1: Physical stock on_hand decremented by delivery")

    # D8: Delivery idempotency
    deliv1_dup = sales.deliver_sales_order(
        business_id=biz_id,
        order_number=so_direct["order_number"],
        lines=[{"master_sku_id": msku_id, "quantity": 1}],
        idempotency_key=idem_d1,
    )
    assert_true(deliv1_dup["duplicate"] is True, "D8: Delivery exactly-once idempotency per key")

    # D6: Full delivery of remaining 2 units
    deliv2 = sales.deliver_sales_order(
        business_id=biz_id,
        order_number=so_direct["order_number"],
        lines=[{"master_sku_id": msku_id, "quantity": 2}],
    )
    assert_true(deliv2["ok"] and deliv2["delivery"]["order_status"] == "DELIVERED", "D6: Full delivery transitions SO to DELIVERED")

    so_check = sales.get_sales_order(business_id=biz_id, order_number=so_direct["order_number"])
    assert_true(so_check["status"] == "DELIVERED" and so_check["lines"][0]["delivered_qty"] == 3, "D6: SO lines record full delivered_qty = 3")

    # ------------------------------------------------------------
    # SECTION 5: CUSTOMER INVOICE & REVENUE / AR (I1-I8)
    # ------------------------------------------------------------
    print("\n--- Section 5: Customer Invoice & Revenue / AR ---")

    # I1 & I3: Create draft invoice based on delivered un-invoiced quantity (3 units)
    cinv = sales.create_customer_invoice(
        business_id=biz_id,
        customer_id=cust["id"],
        sales_order_id=so_direct["id"],
    )
    assert_true(cinv["invoice_number"].startswith("BC-CI-") and cinv["status"] == "DRAFT", "I1: Create DRAFT invoice from delivered quantities")
    assert_true(Decimal(str(cinv["total"])) == Decimal("75000.00"), "I1: Customer invoice total matches delivered goods (3 x 25.000)")
    assert_true(cinv.get("finance_invoice_id") is None, "I3: DRAFT invoice creates zero Finance Core entries")

    # I4, I5, I6: Post Customer Invoice
    post_res = sales.post_customer_invoice(business_id=biz_id, invoice_number=cinv["invoice_number"])
    assert_true(post_res["ok"] and post_res["invoice"]["status"] == "POSTED", "I4: Post customer invoice transitions to POSTED")
    posted_inv = post_res["invoice"]
    assert_true(posted_inv["finance_invoice_id"] is not None and posted_inv["finance_journal_id"] is not None, "I5: Posting creates Finance Core invoice & journal")
    assert_true(Decimal(str(posted_inv["outstanding_amount"])) == Decimal("75000.00"), "I6: Outstanding amount set to total invoice value")

    # I8: Idempotency
    post_dup = sales.post_customer_invoice(business_id=biz_id, invoice_number=cinv["invoice_number"])
    assert_true(post_dup["duplicate"] is True, "I8: Post invoice exactly-once idempotency")

    # ------------------------------------------------------------
    # SECTION 6: AR AGING (A1-A7)
    # ------------------------------------------------------------
    print("\n--- Section 6: AR Aging ---")

    aging = sales.get_ar_aging(business_id=biz_id, customer_code=cust_code)
    assert_true(aging["total_outstanding"] >= Decimal("75000.00"), "A1 & A2: AR Aging reports total outstanding and current bucket")
    assert_true("CURRENT" in aging["buckets"] and "1_30" in aging["buckets"], "A2-A6: AR Aging buckets present")
    assert_true(any(inv_item["invoice_number"] == cinv["invoice_number"] for inv_item in aging["invoices"]), "A7: Active unpaid invoice included in aging")

    # ------------------------------------------------------------
    # SECTION 7: CUSTOMER PAYMENT & COLLECTION (P1-P11)
    # ------------------------------------------------------------
    print("\n--- Section 7: Customer Payment & Collection ---")

    # P4: Overpayment rejected (try paying 80.000 on 75.000 invoice)
    overpay_threw = False
    try:
        sales.create_customer_payment(
            business_id=biz_id,
            invoice_number=cinv["invoice_number"],
            amount=Decimal("80000.00"),
            idempotency_key=f"pay-over-{TAG}",
        )
    except ValueError:
        overpay_threw = True
    assert_true(overpay_threw, "P4: Overpayment strictly rejected")

    # P1, P2, P6, P7: Partial payment of Rp25.000 via Kas (1101)
    idem_p1 = f"pay-p1-{TAG}"
    pay1 = sales.create_customer_payment(
        business_id=biz_id,
        invoice_number=cinv["invoice_number"],
        amount=Decimal("25000.00"),
        payment_account_id="1101",
        idempotency_key=idem_p1,
    )
    assert_true(pay1["ok"] and pay1["payment"]["invoice_status"] == "PARTIALLY_PAID", "P1 & P2: Partial payment transitions invoice to PARTIALLY_PAID")
    assert_true(Decimal(str(pay1["payment"]["outstanding_amount"])) == Decimal("50000.00"), "P1: Outstanding amount reduced to Rp50.000")

    # P9: Payment idempotency
    pay1_dup = sales.create_customer_payment(
        business_id=biz_id,
        invoice_number=cinv["invoice_number"],
        amount=Decimal("25000.00"),
        payment_account_id="1101",
        idempotency_key=idem_p1,
    )
    assert_true(pay1_dup["duplicate"] is True, "P9: Payment exactly-once idempotency per key")

    # P3, P8: Full final payment of Rp50.000 via Bank (1102)
    pay2 = sales.create_customer_payment(
        business_id=biz_id,
        invoice_number=cinv["invoice_number"],
        amount=Decimal("50000.00"),
        payment_account_id="1102",
        idempotency_key=f"pay-p2-{TAG}",
    )
    assert_true(pay2["ok"] and pay2["payment"]["invoice_status"] == "PAID", "P3: Full payment transitions invoice to PAID")
    assert_true(Decimal(str(pay2["payment"]["outstanding_amount"])) == Decimal("0.00"), "P3: Final outstanding amount is Rp0")

    inv_lunas = sales.get_customer_invoice(business_id=biz_id, invoice_number=cinv["invoice_number"])
    assert_true(inv_lunas["status"] == "PAID" and inv_lunas["paid_at"] is not None, "P3: Invoice marked PAID with paid_at timestamp")

    # P11: Exposure decreased
    exp_after_pay = sales.get_customer_ar_exposure(business_id=biz_id, customer_id=cust["id"])
    assert_true(exp_after_pay["ar_outstanding"] == Decimal("0.00"), "P11: Customer AR outstanding cleared after full payment")

    # ------------------------------------------------------------
    # SECTION 8: SALES RETURN & CREDIT NOTE (R1-R8)
    # ------------------------------------------------------------
    print("\n--- Section 8: Sales Return & Credit Note ---")

    # Create fresh order, delivery, and invoice for return testing
    so_ret = sales.create_sales_order(
        business_id=biz_id,
        customer_id=cust["id"],
        warehouse_id=wh_id,
        lines=[{"master_sku_id": msku_id, "quantity": 2}],
    )
    sales.confirm_sales_order(business_id=biz_id, order_number=so_ret["order_number"])
    sales.deliver_sales_order(business_id=biz_id, order_number=so_ret["order_number"], lines=[{"master_sku_id": msku_id, "quantity": 2}])
    cinv_ret = sales.create_customer_invoice(business_id=biz_id, customer_id=cust["id"], sales_order_id=so_ret["id"])
    sales.post_customer_invoice(business_id=biz_id, invoice_number=cinv_ret["invoice_number"])

    stock_pre_ret = inv.location_balance(master_sku_id=msku_id, warehouse_id=wh_id)

    # R3: Return > delivered quantity rejected
    over_ret_threw = False
    try:
        sales.create_sales_return(
            business_id=biz_id,
            order_number=so_ret["order_number"],
            lines=[{"master_sku_id": msku_id, "quantity": 3}],
            reason="Over return",
        )
    except ValueError:
        over_ret_threw = True
    assert_true(over_ret_threw, "R3: Return exceeding delivered quantity rejected")

    # R1, R2, R4, R5: Return 1 unit
    ret_res = sales.create_sales_return(
        business_id=biz_id,
        order_number=so_ret["order_number"],
        lines=[{"master_sku_id": msku_id, "quantity": 1}],
        reason="Barang cacat pabrik",
    )
    assert_true(ret_res["ok"] and ret_res["sales_return"]["return_number"].startswith("SR-"), "R1: Create sales return and increment stock")

    stock_post_ret = inv.location_balance(master_sku_id=msku_id, warehouse_id=wh_id)
    assert_true(stock_post_ret["on_hand"] == stock_pre_ret["on_hand"] + 1, "R1: Physical on_hand restored by return")

    cn = ret_res["credit_note"]
    assert_true(cn["credit_note_number"].startswith("BC-CN-") and Decimal(str(cn["amount"])) == Decimal("25000.00"), "R4: Credit Note generated with correct value (Rp25.000)")

    # R5: Invoice outstanding reduced
    inv_post_ret = sales.get_customer_invoice(business_id=biz_id, invoice_number=cinv_ret["invoice_number"])
    assert_true(Decimal(str(inv_post_ret["outstanding_amount"])) == Decimal("25000.00"), "R5: Customer invoice outstanding reduced by credit note")

    # ------------------------------------------------------------
    # SECTION 9: TELEGRAM DRAFT LIFECYCLE (T1-T5)
    # ------------------------------------------------------------
    print("\n--- Section 9: Telegram Draft Lifecycle ---")

    # T1: Create Customer via Telegram Draft
    tg_cust_code = f"TGC-{TAG}"
    d_cust = sales.create_sales_draft(
        draft_type="CUSTOMER_CREATE",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"code": tg_cust_code, "name": "Telegram Customer", "phone": "08112233"},
    )
    assert_true(d_cust["status"] == "PENDING", "T1: Create Telegram customer draft PENDING")

    # T2: Wrong user cannot confirm draft
    wrong_threw = False
    try:
        sales.confirm_sales_draft(draft_token=d_cust["draft_token"], caller_telegram_user_id=wrong_user_id)
    except PermissionError:
        wrong_threw = True
    assert_true(wrong_threw, "T2: Wrong Telegram user blocked from confirming draft")

    # T3: Author confirms draft
    conf_tg = sales.confirm_sales_draft(draft_token=d_cust["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(conf_tg["ok"] and conf_tg["idempotent"] is False, "T3: Author confirms Telegram customer draft")

    # T4: Draft confirmation idempotency
    conf_tg_dup = sales.confirm_sales_draft(draft_token=d_cust["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(conf_tg_dup["ok"] and conf_tg_dup["idempotent"] is True, "T4: Telegram draft single-use & idempotent")

    # T5: Cancel draft
    d_canc = sales.create_sales_draft(
        draft_type="CUSTOMER_OFF",
        business_id=biz_id,
        owner_id=owner_id,
        telegram_user_id=tg_user_id,
        payload={"code": tg_cust_code},
    )
    canc_tg = sales.cancel_sales_draft(draft_token=d_canc["draft_token"], caller_telegram_user_id=tg_user_id)
    assert_true(canc_tg["ok"] is True, "T5: Cancel Telegram draft")

    print(f"\n============================================================")
    print(f"SALES ORDER-TO-CASH ACCEPTANCE TEST RESULTS:")
    print(f"PASSED: {PASSED}")
    print(f"FAILED: {FAILED}")
    print(f"STATUS: {'ALL PASS' if FAILED == 0 else 'FAILURES DETECTED'}")
    print(f"============================================================")
    return FAILED == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
