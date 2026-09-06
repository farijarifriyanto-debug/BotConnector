"""Acceptance Test Suite for UMKM Essential Core V1.

Covers the 7 BC Bisnis daily-use capabilities end-to-end:
1. /keluar  - Daily Expense Recording (with Confirm/Cancel draft lifecycle)
2. /pengeluaran - Expense Query (today / this month / YYYY-MM)
3. /kas     - Cash & Bank Balance View
4. /labarugi - Profit & Loss Report
5. /ringkasan - All-in-One Business Summary
6. /posisi  - Simple Financial Position (Balance Sheet)
7. /export  - Simple CSV Export

Accounting rule verified: Dr canonical expense account (6101) / Cr Kas (1101)
or Bank (1102) through the canonical Finance Core engine. Zero second-ledger.

Reuses existing frozen modules read-only; does not modify frozen baselines.
Preserves all real production fixtures. Cleans disposable data afterward.
"""

import io
import os
import sys
import uuid
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

# DB connection is driven by environment (isolated acceptance DB).
# Do NOT hardcode production host/port here. The shared production guard
# (persistence.guard) refuses destructive work against production.
sys.path.insert(0, "/opt")
sys.path.insert(0, "/opt/botconnector-multichannel")

import psycopg
from psycopg.rows import dict_row

from botconnector_multichannel.persistence import db
from botconnector_multichannel.persistence.db import koneksi, ambil, semua
from botconnector_multichannel.persistence.guard import (
    assert_isolated_test_db, require_test_tenant, print_test_context,
)
from botconnector_multichannel.inventory import service as S
from botconnector_multichannel.local_business import (
    core,
    umkm,
    bot_poller,
)
from botconnector_multichannel.workflow import finance_core as fc

TAG = uuid.uuid4().hex[:6].upper()
TENANT_ID = f"UMKM-TENANT-{TAG}"
BIZ_CODE = f"BIZ-UMKM-{TAG}"
PASSED = 0
FAILED = 0

# Finance Core DB connection is env-driven (isolated acceptance finance_core).
FINANCE_DB = {
    "host": os.environ.get("BC_FINANCE_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("BC_FINANCE_DB_PORT", "15432")),
    "dbname": os.environ.get("BC_FINANCE_DB_NAME", "finance_core"),
    "user": os.environ.get("BC_FINANCE_DB_USER", "finance_core_app"),
    "password": os.environ.get("BC_FINANCE_DB_PASSWORD", ""),
}


def assert_true(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK]    {name}")
    else:
        FAILED += 1
        print(f"  [FAIL]  {name}")
        raise AssertionError(f"Assertion failed: {name}")


def fin_tb_balance(code: str) -> Decimal:
    """Read an account net balance from the authoritative Finance Core
    trial-balance report (includes opening balances / posted-only totals)."""
    tb = fc._request("GET", "/api/v1/reports/trial-balance")
    for acc in tb.get("accounts", []):
        if acc.get("code") == code:
            return Decimal(str(acc.get("debit_minus_credit", 0)))
    return Decimal("0.00")


def fin_journal_count() -> int:
    with psycopg.connect(row_factory=dict_row, **FINANCE_DB) as con:
        cur = con.cursor()
        cur.execute("SELECT count(*) AS cnt FROM public.journal_entries")
        return int(cur.fetchone()["cnt"])


def run_tests():
    global PASSED, FAILED
    # HARD PRODUCTION GUARD — refuse destructive test work on production.
    assert_isolated_test_db()
    require_test_tenant(TENANT_ID)
    print_test_context(TENANT_ID)
    print(f"=== Starting UMKM Essential Core Acceptance Tests (Tag: {TAG}) ===")

    # ------------------------------------------------------------
    # FIXTURE SETUP (disposable, isolated)
    # ------------------------------------------------------------
    wh_code = f"WH-UMKM-{TAG}"
    db.jalankan(
        "INSERT INTO multichannel.warehouse (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING",
        (wh_code, f"Warehouse UMKM {TAG}"),
    )
    wh_id = ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (wh_code,))["id"]

    biz = core.upsert_business(tenant_id=TENANT_ID, code=BIZ_CODE, name=f"Biz UMKM {TAG}", business_type="RETAIL")
    biz_id = biz["id"]

    br = core.upsert_branch(business_id=biz_id, code=f"BR-UMKM-{TAG}", name=f"Branch UMKM {TAG}", warehouse_id=wh_id, branch_type="RETAIL")
    branch_id = br["id"]

    tg_user_id = 887766000 + int(TAG, 16) % 100000
    with koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "INSERT INTO local_business.telegram_account (owner_id, telegram_user_id, actor) VALUES (%s, %s, %s)",
            (biz_id, tg_user_id, "UMKM Canary Owner"),
        )
        c.commit()

    fx = {
        "tenant_id": TENANT_ID,
        "biz_id": biz_id,
        "wh_id": wh_id,
        "branch_id": branch_id,
        "tg_user_id": tg_user_id,
    }

    try:
        # ------------------------------------------------------------
        # SECTION 1: /keluar — EXPENSE RECORDING & ACCOUNTING MAPPING
        # ------------------------------------------------------------
        print("\n--- SECTION 1: EXPENSE RECORDING (/keluar) & ACCOUNTING ---")
        je_before = fin_journal_count()

        # E1: Category + payment source resolve to canonical GL accounts
        cat, gl, label = umkm.resolve_expense_category("transport")
        assert_true(cat == "Transport" and gl == "6101", "E1a: /keluar transport resolves to 6101 Beban Operasional")
        src, src_gl = umkm.resolve_payment_source("kas")
        assert_true(src == "KAS" and src_gl == "1101", "E1b: payment source 'kas' resolves to 1101")
        src2, src_gl2 = umkm.resolve_payment_source("bank")
        assert_true(src2 == "BANK" and src_gl2 == "1102", "E1c: payment source 'bank' resolves to 1102")

        # E2: Invalid category / source rejected
        try:
            umkm.resolve_expense_category("kategori-tidak-ada-xyz")
            assert_true(False, "E2a: Unknown category must be rejected")
        except ValueError:
            assert_true(True, "E2a: Unknown category rejected")
        try:
            umkm.resolve_payment_source("crypto-wallet")
            assert_true(False, "E2b: Unknown payment source must be rejected")
        except ValueError:
            assert_true(True, "E2b: Unknown payment source rejected")

        # E3: Zero/negative amount rejected
        try:
            umkm.record_expense(business_id=biz_id, category="transport", amount="0", payment_source="Kas")
            assert_true(False, "E3: Zero amount must be rejected")
        except ValueError:
            assert_true(True, "E3: Zero amount rejected")

        # E4: Record a Kas expense of Rp50.000
        exp1 = umkm.record_expense(
            business_id=biz_id,
            category="transport",
            amount="50000",
            payment_source="Kas",
            description="Bensin motor UMKM test",
            created_by="acceptance",
            idempotency_key=f"umkm-e4-{TAG}",
        )
        assert_true(exp1["expense_number"].startswith(f"EXP-{biz_id}-"), "E4a: Expense number generated (EXP-<biz>-<year>-<seq>)")
        assert_true(Decimal(str(exp1["amount"])) == Decimal("50000.00"), "E4b: Expense amount recorded")
        assert_true(exp1["payment_account_code"] == "1101", "E4c: Kas payment account recorded")
        assert_true(exp1["expense_account_code"] == "6101", "E4d: Expense account 6101 recorded")
        assert_true(bool(exp1["finance_transaction_id"]), "E4e: Finance Core transaction id captured")
        assert_true(je_before + 1 == fin_journal_count(), "E4f: Exactly one Finance Core journal created for the expense")

        # E4g: Deterministic accounting — Dr 6101 / Cr 1101 for the amount
        with psycopg.connect(row_factory=dict_row, **FINANCE_DB) as con:
            cur = con.cursor()
            cur.execute(
                """SELECT acc.code, jl.debit, jl.credit
                     FROM public.journal_lines jl
                     JOIN public.accounts acc ON acc.id=jl.account_id
                    WHERE jl.journal_entry_id = (
                          SELECT je.id FROM public.journal_entries je
                           WHERE je.journal_number=%s OR je.description ILIKE %s
                           ORDER BY je.created_at DESC LIMIT 1)
                    ORDER BY jl.line_number""",
                (f"PAY-{exp1['expense_number']}", f"%{exp1['description']}%"),
            )
            lines = cur.fetchall()
        dr = {r["code"]: (r["debit"], r["credit"]) for r in lines}
        assert_true(dr.get("6101") and Decimal(str(dr["6101"][0])) == Decimal("50000.00"), "E4g1: Dr 6101 = Rp50.000")
        assert_true(dr.get("1101") and Decimal(str(dr["1101"][1])) == Decimal("50000.00"), "E4g2: Cr 1101 = Rp50.000")

        # E5: Idempotency — same key does not create a second expense
        exp1b = umkm.record_expense(
            business_id=biz_id,
            category="transport",
            amount="50000",
            payment_source="Kas",
            description="Bensin motor UMKM test",
            idempotency_key=f"umkm-e4-{TAG}",
        )
        assert_true(int(exp1b["id"]) == int(exp1["id"]), "E5: Idempotent key prevents duplicate expense")
        assert_true(fin_journal_count() == je_before + 1, "E5: No second journal for duplicate idempotency key")

        # E6: Bank expense of Rp200.000
        exp2 = umkm.record_expense(
            business_id=biz_id,
            category="listrik",
            amount="200000",
            payment_source="Bank",
            description="Bayar listrik ruko",
            created_by="acceptance",
            idempotency_key=f"umkm-e6-{TAG}",
        )
        assert_true(exp2["payment_account_code"] == "1102", "E6a: Bank expense payment account 1102")
        assert_true(Decimal(str(exp2["amount"])) == Decimal("200000.00"), "E6b: Bank expense amount recorded")

        # ------------------------------------------------------------
        # SECTION 2: /keluar DRAFT LIFECYCLE (Confirm / Cancel callbacks)
        # ------------------------------------------------------------
        print("\n--- SECTION 2: EXPENSE DRAFT LIFECYCLE (Confirm/Cancel) ---")

        # D1: Create a draft (preview) — no finance mutation yet
        je_before_draft = fin_journal_count()
        draft = umkm.create_expense_draft(
            business_id=biz_id,
            owner_id=biz_id,
            telegram_user_id=tg_user_id,
            amount="75000",
            description="Belanja alat tulis kantor",
            category="operasional",
            payment_source="Kas",
        )
        assert_true(draft["draft_token"], "D1a: Draft token generated")
        assert_true(draft["category_label"] == "Beban Operasional Umum", "D1b: Draft category label resolved")
        assert_true(fin_journal_count() == je_before_draft, "D1c: Creating draft performs zero finance mutation")

        # D2: Wrong user cannot confirm
        res_wrong = umkm.confirm_expense_draft(draft["draft_token"], caller_telegram_user_id=999999999)
        assert_true(res_wrong.get("ok") is False, "D2: Non-owner cannot confirm another user's draft")

        # D3: Confirm draft records the expense + finance journal
        je_before_confirm = fin_journal_count()
        res = umkm.confirm_expense_draft(draft["draft_token"], caller_telegram_user_id=tg_user_id)
        assert_true(res.get("ok") is True, "D3a: Confirming draft succeeds")
        assert_true(bool(res["data"]["expense_number"]), "D3b: Confirmed draft produced expense number")
        assert_true(Decimal(str(res["data"]["amount"])) == Decimal("75000.00"), "D3c: Confirmed amount correct")
        assert_true(fin_journal_count() == je_before_confirm + 1, "D3d: Confirm created exactly one finance journal")

        # D4: Re-confirming is idempotent (already confirmed)
        res2 = umkm.confirm_expense_draft(draft["draft_token"], caller_telegram_user_id=tg_user_id)
        assert_true(res2.get("already_confirmed") is True, "D4: Re-confirm is idempotent")

        # D5: Cancel a pending draft
        draft2 = umkm.create_expense_draft(
            business_id=biz_id,
            owner_id=biz_id,
            telegram_user_id=tg_user_id,
            amount="30000",
            description="Membeli kopi untuk rapat",
            category="konsumsi",
            payment_source="Kas",
        )
        cancel_res = umkm.cancel_expense_draft(draft2["draft_token"], caller_telegram_user_id=tg_user_id)
        assert_true(cancel_res.get("ok") is True, "D5a: Cancel pending draft succeeds")
        # Confirming a cancelled draft is rejected
        res_cancel_confirm = umkm.confirm_expense_draft(draft2["draft_token"], caller_telegram_user_id=tg_user_id)
        assert_true(res_cancel_confirm.get("ok") is False, "D5b: Confirming a cancelled draft is rejected")

        # ------------------------------------------------------------
        # SECTION 3: /pengeluaran — EXPENSE QUERY
        # ------------------------------------------------------------
        print("\n--- SECTION 3: EXPENSE QUERY (/pengeluaran) ---")
        today = date.today()
        q = umkm.get_expenses(business_id=biz_id, start_date=today, end_date=today)
        assert_true(len(q["expenses"]) >= 3, "S3a: Today's expense query returns recorded expenses")
        assert_true(Decimal(str(q["total_amount"])) >= Decimal("50000.00"), "S3b: Today's expense query returns recorded total")
        by_cat = q["by_category"]
        assert_true("Transport" in by_cat, "S3c: Transport category present in aggregation")

        # Query month-to-date contains both Kas and Bank expenses
        month_start = date(today.year, today.month, 1)
        q_month = umkm.get_expenses(business_id=biz_id, start_date=month_start, end_date=today)
        assert_true(Decimal(str(q_month["total_amount"])) >= Decimal("250000.00"), "S3d: Month query aggregates recorded expenses")

        # ------------------------------------------------------------
        # SECTION 4: /kas — CASH & BANK VIEW
        # ------------------------------------------------------------
        print("\n--- SECTION 4: CASH & BANK VIEW (/kas) ---")
        cb = umkm.get_cash_bank_balances(business_id=biz_id)
        assert_true(cb["kas"] == fin_tb_balance("1101"), "S4a: /kas Kas balance matches Finance Core 1101")
        assert_true(cb["bank"] == fin_tb_balance("1102"), "S4b: /kas Bank balance matches Finance Core 1102")
        assert_true(cb["total"] == cb["kas"] + cb["bank"], "S4c: Total liquid = Kas + Bank")
        assert_true(len(cb["accounts"]) >= 2, "S4d: Both Kas and Bank account lines present")

        # ------------------------------------------------------------
        # SECTION 5: /labarugi — PROFIT & LOSS
        # ------------------------------------------------------------
        print("\n--- SECTION 5: PROFIT & LOSS (/labarugi) ---")
        pl = umkm.get_profit_loss(business_id=biz_id, date_from=month_start, date_to=today)
        assert_true(Decimal(str(pl["total_expenses"])) >= Decimal("250000.00"), "S5a: P&L reflects recorded expenses")
        assert_true(Decimal(str(pl["net_income"])) == Decimal(str(pl["revenue"])) - Decimal(str(pl["total_expenses"])), "S5b: Net income = Revenue - Total expenses")

        # ------------------------------------------------------------
        # SECTION 6: /ringkasan — BUSINESS SUMMARY (ALL-IN-ONE)
        # ------------------------------------------------------------
        print("\n--- SECTION 6: BUSINESS SUMMARY (/ringkasan) ---")
        summ = umkm.get_business_summary(business_id=biz_id)
        assert_true(Decimal(str(summ["today"]["expense_amount"])) >= Decimal("50000.00"), "S6a: Summary today's expense reflects recorded expenses")
        assert_true(summ["finance"]["kas"] == cb["kas"], "S6b: Summary Kas matches /kas")
        assert_true(summ["finance"]["bank"] == cb["bank"], "S6c: Summary Bank matches /kas")
        assert_true(Decimal(str(summ["month_to_date"]["expense"])) >= Decimal("250000.00"), "S6d: Summary MTD expense reflects recorded expenses")
        assert_true("net_income" in summ["month_to_date"], "S6e: Summary exposes MTD net income")
        assert_true("low_stock_count" in summ["inventory"] and "reorder_count" in summ["inventory"], "S6f: Summary exposes low-stock & reorder indicators")

        # ------------------------------------------------------------
        # SECTION 7: /posisi — FINANCIAL POSITION (BALANCE SHEET)
        # ------------------------------------------------------------
        print("\n--- SECTION 7: FINANCIAL POSITION (/posisi) ---")
        pos = umkm.get_financial_position(business_id=biz_id)
        assert_true(pos["balanced"] is True, "S7a: Balance sheet is balanced")
        assert_true("total_assets" in pos and pos["total_assets"] is not None, "S7b: Total assets returned")
        assert_true("modal" in pos["equity"] and "laba_berjalan" in pos["equity"], "S7c: Equity includes modal & laba berjalan")

        # ------------------------------------------------------------
        # SECTION 8: /export — SIMPLE CSV EXPORT
        # ------------------------------------------------------------
        print("\n--- SECTION 8: SIMPLE EXPORT (/export) ---")
        csv_content = umkm.generate_export_csv(business_id=biz_id, year=today.year, month=today.month)
        assert_true(csv_content.startswith("LAPORAN KEUANGAN UMKM BC BISNIS"), "S8a: Export CSV header present")
        assert_true("=== LABA RUGI ===" in csv_content, "S8b: Export contains P&L section")
        assert_true("=== SALDO KAS & BANK ===" in csv_content, "S8c: Export contains Cash & Bank section")
        assert_true("=== PIUTANG & UTANG ===" in csv_content, "S8d: Export contains AR/AP section")
        assert_true("=== DAFTAR PENGELUARAN ===" in csv_content, "S8e: Export contains expense detail section")
        assert_true(f"Bensin motor UMKM test" in csv_content, "S8f: Export contains recorded expense detail")
        # CSV is parseable
        import csv as csv_mod
        parsed = list(csv_mod.reader(io.StringIO(csv_content)))
        assert_true(len(parsed) > 5, "S8g: Export CSV parses into multiple rows")

        # ------------------------------------------------------------
        # SECTION 9: TELEGRAM WIRING (handler-level)
        # ------------------------------------------------------------
        print("\n--- SECTION 9: TELEGRAM HANDLER WIRING ---")
        from botconnector_multichannel.local_business.bot_client import BotApiClient
        assert_true(hasattr(BotApiClient, "send_document"), "S9a: BotApiClient exposes send_document for /export")
        assert_true(hasattr(BotApiClient, "send_message"), "S9b: BotApiClient exposes send_message")
        assert_true(hasattr(BotApiClient, "set_my_commands"), "S9c: BotApiClient exposes set_my_commands")

        # Verify bot_poller imports the umkm module & wiring references exist
        src = open("/opt/botconnector-multichannel/local_business/bot_poller.py").read()
        for needle in [
            'text.startswith("/keluar")',
            'text.startswith("/pengeluaran")',
            'text in ("/kas"',
            'text.startswith("/labarugi")',
            'text in ("/ringkasan"',
            'text in ("/posisi"',
            'text.startswith("/export")',
            'exp_confirm:',
            'exp_cancel:',
        ]:
            assert_true(needle in src, f"S9-{needle}: Telegram command wired in bot_poller.py")

        # ------------------------------------------------------------
        # SECTION 10: ZERO FROZEN-MODULE MUTATION
        # ------------------------------------------------------------
        print("\n--- SECTION 10: ZERO FROZEN-MODULE MUTATION ---")
        with koneksi() as c:
            cur = c.cursor()
            # No product/supplier/PO/bill/invoice mutations created by UMKM flow
            cur.execute("SELECT count(*) AS cnt FROM local_business.supplier WHERE business_id=%s", (biz_id,))
            assert_true(int(cur.fetchone()["cnt"]) == 0, "S10a: No supplier created by UMKM essential flow")
            cur.execute("SELECT count(*) AS cnt FROM local_business.purchase_order WHERE business_id=%s", (biz_id,))
            assert_true(int(cur.fetchone()["cnt"]) == 0, "S10b: No purchase order created by UMKM essential flow")
            cur.execute("SELECT count(*) AS cnt FROM local_business.vendor_bill WHERE business_id=%s", (biz_id,))
            assert_true(int(cur.fetchone()["cnt"]) == 0, "S10c: No vendor bill created by UMKM essential flow")
            cur.execute("SELECT count(*) AS cnt FROM local_business.sales_order WHERE business_id=%s", (biz_id,))
            assert_true(int(cur.fetchone()["cnt"]) == 0, "S10d: No sales order created by UMKM essential flow")

        # ------------------------------------------------------------
        # SUMMARY
        # ------------------------------------------------------------
        print(f"\n=== UMKM Essential Core PASSED: {PASSED}, FAILED: {FAILED} ===")

    finally:
        cleanup_fixtures(fx)


def cleanup_fixtures(fx):
    """Remove disposable local_business data. Finance Core journals are immutable
    and left in place (consistent with all existing acceptance suites)."""
    biz_id = fx["biz_id"]
    branch_id = fx["branch_id"]
    wh_id = fx["wh_id"]
    tenant_id = fx["tenant_id"]
    with koneksi() as c:
        cur = c.cursor()
        cur.execute("DELETE FROM local_business.expense WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.telegram_procurement_draft WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.telegram_account WHERE owner_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.register WHERE branch_id=%s", (branch_id,))
        cur.execute("DELETE FROM local_business.branch WHERE id=%s", (branch_id,))
        cur.execute("DELETE FROM local_business.business WHERE id=%s", (biz_id,))
        cur.execute("DELETE FROM multichannel.warehouse WHERE id=%s", (wh_id,))
        cur.execute("DELETE FROM multichannel.tenant WHERE id=%s", (tenant_id,))
        c.commit()


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        print(f"RESULT: {PASSED} passed, {FAILED} failed")
        if FAILED:
            sys.exit(1)
