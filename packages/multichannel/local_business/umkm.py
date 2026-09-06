"""
BC Bisnis — UMKM Essential Operations Core V1

Provides essential daily-use capabilities for UMKM owners:
1. Daily Expense Recording & Query (/keluar, /pengeluaran)
2. Cash & Bank Balance View (/kas)
3. Profit & Loss Report (/labarugi)
4. All-in-One Business Summary (/ringkasan)
5. Simple Financial Position (/posisi)
6. Simple Data Export (/export)

Reuses canonical Finance Core accounting backend and existing frozen modules read-only.
Zero second-ledger creation.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from botconnector_multichannel.persistence.db import ambil, semua, koneksi
from botconnector_multichannel.workflow import finance_core as fc
from botconnector_multichannel.local_business import (
    core,
    sales,
    procurement,
    low_stock,
    reorder,
    inventory as inv,
)

logger = logging.getLogger("bc.bisnis.umkm")

# ============================================================
# CONSTANTS & CATEGORY MAPPINGS
# ============================================================

# User-facing expense categories mapped to canonical Finance Core accounts
# 6101 = Beban Operasional (Operating Expense)
# 6201 = Biaya Payment Gateway (Payment Fee)
# 6190 = Selisih Persediaan (Inventory Adjustment)
EXPENSE_CATEGORY_MAP: Dict[str, Tuple[str, str]] = {
    "transport": ("6101", "Transportasi & Bensin"),
    "transportasi": ("6101", "Transportasi & Bensin"),
    "bensin": ("6101", "Transportasi & Bensin"),
    "listrik": ("6101", "Listrik & Air"),
    "air": ("6101", "Listrik & Air"),
    "pdam": ("6101", "Listrik & Air"),
    "sewa": ("6101", "Sewa Tempat / Ruko"),
    "internet": ("6101", "Internet & Komunikasi"),
    "pulsa": ("6101", "Internet & Komunikasi"),
    "telepon": ("6101", "Internet & Komunikasi"),
    "makan": ("6101", "Konsumsi & Operasional"),
    "konsumsi": ("6101", "Konsumsi & Operasional"),
    "operasional": ("6101", "Beban Operasional Umum"),
    "gaji": ("6101", "Gaji & Upah"),
    "upah": ("6101", "Gaji & Upah"),
    "maintenance": ("6101", "Perawatan & Perbaikan"),
    "perbaikan": ("6101", "Perawatan & Perbaikan"),
    "servis": ("6101", "Perawatan & Perbaikan"),
    "marketing": ("6101", "Pemasaran & Iklan"),
    "iklan": ("6101", "Pemasaran & Iklan"),
    "promosi": ("6101", "Pemasaran & Iklan"),
    "lain-lain": ("6101", "Beban Lain-lain"),
    "lainlain": ("6101", "Beban Lain-lain"),
    "lainnya": ("6101", "Beban Lain-lain"),
    "fee": ("6201", "Biaya Payment Gateway / Fee"),
}

PAYMENT_SOURCE_MAP: Dict[str, Tuple[str, str]] = {
    "kas": ("1101", "KAS"),
    "cash": ("1101", "KAS"),
    "tunai": ("1101", "KAS"),
    "bank": ("1102", "BANK"),
    "transfer": ("1102", "BANK"),
    "rekening": ("1102", "BANK"),
}


def resolve_expense_category(category_input: str) -> Tuple[str, str, str]:
    """
    Resolves user-entered category to canonical (category_code, gl_account_code, label).
    Raises ValueError if category cannot be resolved.
    """
    key = category_input.strip().lower()
    if key in EXPENSE_CATEGORY_MAP:
        gl_code, label = EXPENSE_CATEGORY_MAP[key]
        return key.title(), gl_code, label

    # Check substring match
    for k, (gl_code, label) in EXPENSE_CATEGORY_MAP.items():
        if k in key or key in k:
            return k.title(), gl_code, label

    raise ValueError("Kategori pengeluaran belum memiliki akun keuangan.")


def resolve_payment_source(source_input: str) -> Tuple[str, str]:
    """
    Resolves user-entered payment source to (payment_source_name, gl_account_code).
    Raises ValueError if payment source is unsupported.
    """
    key = source_input.strip().lower()
    if key in PAYMENT_SOURCE_MAP:
        gl_code, standard_name = PAYMENT_SOURCE_MAP[key]
        return standard_name, gl_code
    raise ValueError(f"Sumber pembayaran '{source_input}' tidak valid. Pilih: Kas atau Bank.")


# ============================================================
# FINANCE CORE REVENUE / CASH / BANK HELPERS
# ============================================================

def get_cash_bank_account_uuid(gl_account_code: str) -> str:
    """
    Retrieves the cash_bank_account UUID from Finance Core for a given GL account (1101 or 1102).

    Preferred source is /bank/accounts which exposes an explicit ``id`` and
    ``active`` flag. /bank/summary returns the same accounts but omits ``active``
    (null), so it cannot be trusted to select the active cash/bank account.
    """
    # Preferred: /bank/accounts carries an authoritative account id + active flag.
    try:
        bank = fc._request("GET", "/api/v1/bank/accounts")
    except Exception:
        bank = {}
    accounts = bank.get("accounts", bank if isinstance(bank, list) else [])
    for acc in accounts:
        if acc.get("gl_account_code") == gl_account_code and acc.get("id") and acc.get("active", True) is not False:
            return acc.get("id")

    # Fallback: /bank/summary (same account set, no explicit active field).
    try:
        summary = fc._request("GET", "/api/v1/bank/summary")
    except Exception:
        summary = {}
    for acc in summary.get("accounts", []):
        if acc.get("gl_account_code") == gl_account_code and acc.get("id"):
            return acc.get("id")

    raise RuntimeError(f"Akun Kas/Bank dengan GL code {gl_account_code} tidak ditemukan di Finance Core.")


# ============================================================
# 1. DAILY EXPENSE CORE
# ============================================================

def record_expense(
    business_id: int,
    category: str,
    amount: Decimal | float | int | str,
    payment_source: str = "Kas",
    description: str = "",
    expense_date: Optional[date] = None,
    created_by: str = "system",
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Records an operational expense and creates an authoritative journal in Finance Core:
    Dr 6101 (Beban Operasional) / Cr 1101 (Kas) or 1102 (Bank).
    Zero second-ledger creation.
    """
    amt = Decimal(str(amount))
    if amt <= Decimal("0.00"):
        raise ValueError("Jumlah pengeluaran harus lebih besar dari 0.")

    cat_name, expense_gl, cat_label = resolve_expense_category(category)
    pay_src, pay_gl = resolve_payment_source(payment_source)
    exp_date = expense_date or date.today()

    if not idempotency_key:
        idempotency_key = f"exp-{business_id}-{secrets.token_hex(8)}"

    # Check idempotency
    existing = ambil(
        "SELECT * FROM local_business.expense WHERE business_id=%s AND idempotency_key=%s",
        (business_id, idempotency_key),
    )
    if existing:
        return dict(existing)

    # Resolve cash/bank account UUID in Finance Core
    cash_bank_account_id = get_cash_bank_account_uuid(pay_gl)

    with koneksi() as conn:
        with conn.cursor() as cur:
            # Generate sequential expense number
            cur.execute("SELECT nextval('local_business.expense_seq') AS seq")
            seq = cur.fetchone()["seq"]
            exp_num = f"EXP-{business_id}-{exp_date.year}-{seq:06d}"

            # Post to Finance Core
            payload = {
                "cash_bank_account_id": cash_bank_account_id,
                "transaction_type": "PAYMENT",
                "counter_account_code": expense_gl,
                "amount": str(amt),
                "reference": exp_num,
                "description": f"Beban {cat_name}: {description}".strip(": "),
                "idempotency_key": idempotency_key,
                "transaction_date": exp_date.isoformat(),
            }

            fin_res = fc._request("POST", "/api/v1/bank/transactions", payload)
            fin_tx_id = fin_res.get("id")

            # Insert local record
            cur.execute(
                """
                INSERT INTO local_business.expense (
                    business_id, expense_number, expense_date, category,
                    amount, payment_source, payment_account_code,
                    expense_account_code, description, finance_transaction_id,
                    idempotency_key, created_by, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING *
                """,
                (
                    business_id,
                    exp_num,
                    exp_date,
                    cat_name,
                    amt,
                    pay_src,
                    pay_gl,
                    expense_gl,
                    description,
                    str(fin_tx_id),
                    idempotency_key,
                    created_by,
                ),
            )
            row = cur.fetchone()
        conn.commit()

    return dict(row)


def get_expenses(
    business_id: int,
    start_date: date,
    end_date: date,
) -> Dict[str, Any]:
    """
    Retrieves expenses within date range, grouped by category.
    """
    rows = semua(
        """
        SELECT * FROM local_business.expense
        WHERE business_id=%s AND expense_date >= %s AND expense_date <= %s
        ORDER BY expense_date DESC, id DESC
        """,
        (business_id, start_date, end_date),
    )

    by_category: Dict[str, Decimal] = {}
    total = Decimal("0.00")
    for r in rows:
        c = r["category"]
        a = Decimal(str(r["amount"]))
        by_category[c] = by_category.get(c, Decimal("0.00")) + a
        total += a

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_amount": total,
        "by_category": by_category,
        "expenses": [dict(r) for r in rows],
    }


# ============================================================
# 2. CASH / BANK VIEW
# ============================================================

def get_cash_bank_balances(business_id: int) -> Dict[str, Any]:
    """
    Reads authoritative cash and bank balances from canonical Finance Core.
    """
    tb = fc._request("GET", "/api/v1/reports/trial-balance")
    accounts = tb.get("accounts", [])

    kas_balance = Decimal("0.00")
    bank_balance = Decimal("0.00")
    account_list = []

    for acc in accounts:
        code = acc.get("code")
        name = acc.get("name")
        debit = Decimal(str(acc.get("debit", 0)))
        credit = Decimal(str(acc.get("credit", 0)))
        # For Asset normal balance = Debit - Credit
        net = debit - credit

        if code == "1101":
            kas_balance = net
            account_list.append({"code": code, "name": name, "balance": net})
        elif code == "1102":
            bank_balance = net
            account_list.append({"code": code, "name": name, "balance": net})

    total = kas_balance + bank_balance
    return {
        "kas": kas_balance,
        "bank": bank_balance,
        "total": total,
        "accounts": account_list,
    }


# ============================================================
# 3. PROFIT & LOSS REPORT
# ============================================================

def get_profit_loss(
    business_id: int,
    date_from: date,
    date_to: date,
) -> Dict[str, Any]:
    """
    Retrieves deterministic Profit & Loss from canonical Finance Core.
    """
    pl_data = fc._request(
        "GET",
        f"/api/v1/reports/profit-loss?date_from={date_from.isoformat()}&date_to={date_to.isoformat()}",
    )

    revenue_list = pl_data.get("revenue", [])
    expenses_list = pl_data.get("expenses", [])
    totals = pl_data.get("totals", {})

    total_revenue = Decimal(str(totals.get("revenue", 0)))
    total_expenses = Decimal(str(totals.get("expenses", 0)))
    net_income = Decimal(str(totals.get("net_income", 0)))

    # Separate HPP from operational expenses if present
    hpp = Decimal("0.00")
    operational_expenses = Decimal("0.00")

    for exp in expenses_list:
        code = exp.get("code")
        bal = Decimal(str(exp.get("balance", 0)))
        if code == "5101":
            hpp += bal
        else:
            operational_expenses += bal

    gross_profit = total_revenue - hpp

    return {
        "date_from": date_from,
        "date_to": date_to,
        "revenue": total_revenue,
        "revenue_breakdown": revenue_list,
        "hpp": hpp,
        "gross_profit": gross_profit,
        "operational_expenses": operational_expenses,
        "total_expenses": total_expenses,
        "expenses_breakdown": expenses_list,
        "net_income": net_income,
    }


# ============================================================
# 4. BUSINESS SUMMARY (OWNER ALL-IN-ONE DASHBOARD)
# ============================================================

def get_business_summary(
    business_id: int,
    target_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Aggregates all 8 core UMKM questions into a single clean summary:
    1. Hari ini jual berapa?
    2. Hari ini keluar uang berapa?
    3. Uang kas/bank sekarang berapa?
    4. Untung/rugi berapa?
    5. Piutang pelanggan berapa?
    6. Utang supplier berapa?
    7. Stok penting bagaimana?
    8. Apa yang perlu dibeli/restock?
    """
    t_date = target_date or date.today()
    month_start = date(t_date.year, t_date.month, 1)

    # 1. Today's sales (POS sales + Sales Orders)
    pos_sales_today = ambil(
        """
        SELECT COALESCE(SUM(total), 0) as total, COUNT(*) as count
        FROM local_business.sale
        WHERE business_id=%s AND DATE(created_at AT TIME ZONE 'Asia/Jakarta') = %s
        """,
        (business_id, t_date),
    )
    so_sales_today = ambil(
        """
        SELECT COALESCE(SUM(total), 0) as total, COUNT(*) as count
        FROM local_business.sales_order
        WHERE business_id=%s AND order_date = %s AND status != 'CANCELLED'
        """,
        (business_id, t_date),
    )
    today_sales_amt = Decimal(str(pos_sales_today["total"] if pos_sales_today else 0)) + Decimal(str(so_sales_today["total"] if so_sales_today else 0))
    today_tx_count = int(pos_sales_today["count"] if pos_sales_today else 0) + int(so_sales_today["count"] if so_sales_today else 0)

    # 2. Today's expenses
    exp_today = ambil(
        """
        SELECT COALESCE(SUM(amount), 0) as total, COUNT(*) as count
        FROM local_business.expense
        WHERE business_id=%s AND expense_date = %s
        """,
        (business_id, t_date),
    )
    today_exp_amt = Decimal(str(exp_today["total"] if exp_today else 0))

    # 3. Cash & Bank balances
    cash_bank = get_cash_bank_balances(business_id)

    # 4. Receivables (AR) & Payables (AP)
    ar_data = sales.get_ar_aging(business_id=business_id)
    total_ar = Decimal(str(ar_data.get("total_outstanding", 0)))

    ap_row = ambil(
        """
        SELECT COALESCE(SUM(outstanding_amount), 0) as total
        FROM local_business.vendor_bill
        WHERE business_id=%s AND status IN ('POSTED', 'PARTIALLY_PAID')
        """,
        (business_id,),
    )
    total_ap = Decimal(str(ap_row["total"] if ap_row else 0))

    # 5. Low-stock & Reorder indicators
    low_stock_rows = low_stock.list_low_stock_products(business_id=business_id)
    low_stock_count = len(low_stock_rows)

    reorder_res = reorder.calculate_reorder_recommendations(business_id=business_id)
    reorder_count = len(reorder_res)

    # 6. Month-to-date P&L
    pl_mtd = get_profit_loss(business_id=business_id, date_from=month_start, date_to=t_date)

    return {
        "business_id": business_id,
        "target_date": t_date,
        "today": {
            "sales_amount": today_sales_amt,
            "expense_amount": today_exp_amt,
            "transaction_count": today_tx_count,
        },
        "finance": {
            "kas": cash_bank["kas"],
            "bank": cash_bank["bank"],
            "total_liquid": cash_bank["total"],
            "ar_outstanding": total_ar,
            "ap_outstanding": total_ap,
        },
        "inventory": {
            "low_stock_count": low_stock_count,
            "reorder_count": reorder_count,
        },
        "month_to_date": {
            "period": f"{t_date.strftime('%B %Y')}",
            "revenue": pl_mtd["revenue"],
            "expense": pl_mtd["total_expenses"],
            "net_income": pl_mtd["net_income"],
        },
    }


# ============================================================
# 5. SIMPLE FINANCIAL POSITION (BALANCE SHEET)
# ============================================================

def get_financial_position(
    business_id: int,
    as_of_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Retrieves canonical financial position (Assets, Liabilities, Equity) from Finance Core.
    """
    as_of = as_of_date or date.today()
    bs_data = fc._request(
        "GET",
        f"/api/v1/reports/balance-sheet?as_of={as_of.isoformat()}",
    )

    assets = bs_data.get("assets", [])
    liabilities = bs_data.get("liabilities", [])
    equity = bs_data.get("equity", [])
    current_earnings = bs_data.get("current_earnings", {})
    totals = bs_data.get("totals", {})

    total_assets = Decimal(str(totals.get("assets", 0)))
    total_liabilities = Decimal(str(totals.get("liabilities", 0)))
    total_equity = Decimal(str(totals.get("equity_including_current_earnings", 0)))

    # Parse individual line items
    asset_dict: Dict[str, Decimal] = {}
    for a in assets:
        asset_dict[a.get("name")] = Decimal(str(a.get("balance", 0)))

    liability_dict: Dict[str, Decimal] = {}
    for l in liabilities:
        liability_dict[l.get("name")] = Decimal(str(l.get("balance", 0)))

    return {
        "as_of": as_of,
        "assets": asset_dict,
        "total_assets": total_assets,
        "liabilities": liability_dict,
        "total_liabilities": total_liabilities,
        "equity": {
            "modal": Decimal(str(totals.get("posted_equity", 0))),
            "laba_berjalan": Decimal(str(current_earnings.get("net_income", 0))),
            "total_equity": total_equity,
        },
        "balanced": bs_data.get("balanced", True),
    }


# ============================================================
# 6. SIMPLE EXPORT (CSV EXPORT OF MONTHLY REPORT)
# ============================================================

def generate_export_csv(
    business_id: int,
    year: int,
    month: int,
) -> str:
    """
    Generates a structured CSV report for UMKM containing:
    - Ringkasan Keuangan
    - Laba Rugi
    - Daftar Pengeluaran
    - Piutang & Utang
    - Saldo Kas & Bank
    """
    import calendar
    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    summary = get_business_summary(business_id=business_id, target_date=end_date)
    pl = get_profit_loss(business_id=business_id, date_from=start_date, date_to=end_date)
    expenses_data = get_expenses(business_id=business_id, start_date=start_date, end_date=end_date)
    cash_bank = get_cash_bank_balances(business_id=business_id)
    ar = sales.get_ar_aging(business_id=business_id)
    ap_row = ambil(
        """
        SELECT COALESCE(SUM(outstanding_amount), 0) as total
        FROM local_business.vendor_bill
        WHERE business_id=%s AND status IN ('POSTED', 'PARTIALLY_PAID')
        """,
        (business_id,),
    )
    total_ap = Decimal(str(ap_row["total"] if ap_row else 0))

    output = io.StringIO()
    writer = csv.writer(output)

    # 1. Header
    writer.writerow(["LAPORAN KEUANGAN UMKM BC BISNIS"])
    writer.writerow(["Periode", f"{year}-{month:02d} ({start_date.isoformat()} s/d {end_date.isoformat()})"])
    writer.writerow(["Tanggal Cetak", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")])
    writer.writerow([])

    # 2. Ringkasan Laba Rugi
    writer.writerow(["=== LABA RUGI ==="])
    writer.writerow(["Komponen", "Jumlah (Rp)"])
    writer.writerow(["Pendapatan", f"{pl['revenue']:.2f}"])
    writer.writerow(["Harga Pokok Penjualan (HPP)", f"{pl['hpp']:.2f}"])
    writer.writerow(["Laba Kotor", f"{pl['gross_profit']:.2f}"])
    writer.writerow(["Beban Operasional", f"{pl['operational_expenses']:.2f}"])
    writer.writerow(["Laba Bersih", f"{pl['net_income']:.2f}"])
    writer.writerow([])

    # 3. Saldo Kas & Bank
    writer.writerow(["=== SALDO KAS & BANK ==="])
    writer.writerow(["Akun", "Saldo (Rp)"])
    writer.writerow(["Kas", f"{cash_bank['kas']:.2f}"])
    writer.writerow(["Bank", f"{cash_bank['bank']:.2f}"])
    writer.writerow(["Total Saldo Kas/Bank", f"{cash_bank['total']:.2f}"])
    writer.writerow([])

    # 4. Piutang & Utang
    writer.writerow(["=== PIUTANG & UTANG ==="])
    writer.writerow(["Jenis", "Total Outstanding (Rp)"])
    writer.writerow(["Piutang Usaha (AR)", f"{ar.get('total_outstanding', 0):.2f}"])
    writer.writerow(["Utang Usaha Supplier (AP)", f"{total_ap:.2f}"])
    writer.writerow([])

    # 5. Detail Pengeluaran
    writer.writerow(["=== DAFTAR PENGELUARAN ==="])
    writer.writerow(["Nomor", "Tanggal", "Kategori", "Keterangan", "Sumber Bayar", "Jumlah (Rp)"])
    for exp in expenses_data.get("expenses", []):
        writer.writerow([
            exp.get("expense_number"),
            exp.get("expense_date"),
            exp.get("category"),
            exp.get("description"),
            exp.get("payment_source"),
            f"{Decimal(str(exp.get('amount', 0))):.2f}",
        ])
    writer.writerow(["TOTAL PENGELUARAN", "", "", "", "", f"{expenses_data['total_amount']:.2f}"])

    return output.getvalue()


# ============================================================
# 7. TELEGRAM DRAFT LIFECYCLE FOR EXPENSES
# ============================================================

def create_expense_draft(
    business_id: int,
    owner_id: int,
    telegram_user_id: int,
    amount: Decimal | float | int | str,
    description: str,
    category: str,
    payment_source: str = "Kas",
) -> Dict[str, Any]:
    """
    Creates a durable Telegram draft for expense recording with preview.
    """
    amt = Decimal(str(amount))
    if amt <= Decimal("0.00"):
        raise ValueError("Jumlah pengeluaran harus lebih besar dari 0.")

    cat_name, expense_gl, cat_label = resolve_expense_category(category)
    pay_src, pay_gl = resolve_payment_source(payment_source)

    token = secrets.token_urlsafe(16)
    payload = {
        "business_id": business_id,
        "owner_id": owner_id,
        "amount": str(amt),
        "description": description,
        "category": cat_name,
        "expense_gl": expense_gl,
        "category_label": cat_label,
        "payment_source": pay_src,
        "payment_gl": pay_gl,
    }

    with koneksi() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO local_business.telegram_procurement_draft (
                    draft_token, draft_type, business_id, owner_id,
                    telegram_user_id, status, payload, expires_at
                )
                VALUES (
                    %s, 'EXPENSE_RECORD', %s, %s, %s, 'PENDING', %s,
                    CURRENT_TIMESTAMP + INTERVAL '15 minutes'
                )
                RETURNING id, draft_token
                """,
                (token, business_id, owner_id, telegram_user_id, json.dumps(payload)),
            )
            row = cur.fetchone()
        conn.commit()

    return {
        "draft_id": row["id"],
        "draft_token": row["draft_token"],
        "category": cat_name,
        "category_label": cat_label,
        "amount": amt,
        "payment_source": pay_src,
        "description": description,
    }


def confirm_expense_draft(
    draft_token: str,
    caller_telegram_user_id: int,
) -> Dict[str, Any]:
    """
    Confirms an expense draft and records the expense in Finance Core.
    """
    with koneksi() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM local_business.telegram_procurement_draft
                WHERE draft_token=%s AND draft_type='EXPENSE_RECORD'
                FOR UPDATE
                """,
                (draft_token,),
            )
            draft = cur.fetchone()
            if not draft:
                return {"ok": False, "error": "Draft pengeluaran tidak ditemukan."}

            d = dict(draft)
            if d["status"] == "CONFIRMED":
                # Idempotent re-confirm: return the already-recorded expense
                # (looked up by its deterministic idempotency key).
                idem = f"exp-tg-{draft_token}"
                row = ambil(
                    "SELECT * FROM local_business.expense WHERE idempotency_key=%s",
                    (idem,),
                )
                return {"ok": True, "already_confirmed": True, "data": (dict(row) if row else None)}
            if d["status"] == "CANCELLED":
                return {"ok": False, "error": "Draft pengeluaran ini telah dibatalkan."}
            if d["expires_at"] and d["expires_at"] < datetime.now(timezone.utc):
                return {"ok": False, "error": "Draft pengeluaran telah kedaluwarsa. Silakan buat baru."}
            if d["telegram_user_id"] != caller_telegram_user_id:
                return {"ok": False, "error": "Akses ditolak: Anda bukan pemilik draft ini."}

            payload = d["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)

            # Record the expense
            exp_res = record_expense(
                business_id=payload["business_id"],
                category=payload["category"],
                amount=payload["amount"],
                payment_source=payload["payment_source"],
                description=payload["description"],
                created_by=f"telegram:{caller_telegram_user_id}",
                idempotency_key=f"exp-tg-{draft_token}",
            )

            # Update draft status (shared frozen table has no result_data column;
            # the confirmed expense is retrievable via its idempotency key).
            cur.execute(
                """
                UPDATE local_business.telegram_procurement_draft
                SET status='CONFIRMED', confirmed_at=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                (d["id"],),
            )
        conn.commit()

    return {"ok": True, "data": exp_res}


def cancel_expense_draft(
    draft_token: str,
    caller_telegram_user_id: int,
) -> Dict[str, Any]:
    """
    Cancels an expense draft.
    """
    with koneksi() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM local_business.telegram_procurement_draft
                WHERE draft_token=%s AND draft_type='EXPENSE_RECORD'
                FOR UPDATE
                """,
                (draft_token,),
            )
            draft = cur.fetchone()
            if not draft:
                return {"ok": False, "error": "Draft tidak ditemukan."}

            d = dict(draft)
            if d["status"] == "CANCELLED":
                return {"ok": True, "already_cancelled": True}
            if d["status"] == "CONFIRMED":
                return {"ok": False, "error": "Draft sudah dikonfirmasi, tidak dapat dibatalkan."}
            if d["telegram_user_id"] != caller_telegram_user_id:
                return {"ok": False, "error": "Akses ditolak: Anda bukan pemilik draft ini."}

            cur.execute(
                """
                UPDATE local_business.telegram_procurement_draft
                SET status='CANCELLED'
                WHERE id=%s
                """,
                (d["id"],),
            )
        conn.commit()

    return {"ok": True}
