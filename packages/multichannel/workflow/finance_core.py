"""Klien HTTP Finance Core (127.0.0.1:18200).

Klien ini memakai jalur API kanonik Finance Core dan TIDAK menulis ke
basis data finance_core secara langsung kecuali melalui endpoint resmi.
Semua posting lewat lifecycle kanonik: DRAFT -> issue -> finance_post_journal
-> POSTED.
"""

from __future__ import annotations

import json
import urllib.request
import uuid
from decimal import Decimal

import os

# Finance Core API base is env-configurable so isolated acceptance can point
# at an isolated Finance Core instance. Production default: 127.0.0.1:18200.
API = os.environ.get("BC_FINANCE_CORE_API", "http://127.0.0.1:18200")
BATAS = 20


class FinanceCoreError(RuntimeError):
    pass


def _request(method: str, jalur: str, isi=None):
    data = json.dumps(isi).encode() if isi is not None else None
    req = urllib.request.Request(API + jalur, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=BATAS) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise FinanceCoreError(f"{method} {jalur} -> {e.code}: {body[:300]}") from e
    except Exception as e:
        raise FinanceCoreError(f"{method} {jalur}: {type(e).__name__}: {e}") from e


def kesehatan() -> dict:
    return _request("GET", "/health")


def daftar_customer() -> list[dict]:
    d = _request("GET", "/api/v1/customers")
    return d.get("customers", [])


def cari_customer(kode: str) -> dict | None:
    for c in daftar_customer():
        if c["code"] == kode:
            return c
    return None


def pastikan_customer(*, code: str, name: str) -> str:
    """Buat/get customer. Idempoten berdasarkan kode."""
    ada = cari_customer(code)
    if ada:
        return ada["id"]
    d = _request("POST", "/api/v1/customers",
                 {"code": code, "name": name})
    return d["id"]


def buat_sales_invoice(
    *,
    customer_id: str,
    invoice_number: str,
    invoice_date: str,
    due_date: str,
    lines: list[dict],
    source_system: str = "multichannel",
    source_id: str = "",
) -> dict:
    """Buat Sales Invoice DRAFT."""
    return _request("POST", "/api/v1/sales/invoices", {
        "customer_id": customer_id,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "currency": "IDR",
        "source_system": source_system,
        "source_id": source_id,
        "lines": lines,
    })


def issue_sales_invoice(invoice_id: str) -> dict:
    """Issue -> finance_issue_sales_invoice -> finance_post_journal -> POSTED."""
    return _request("POST", f"/api/v1/sales/invoices/{invoice_id}/issue")


def cari_invoice(invoice_number: str) -> dict | None:
    d = _request("GET", "/api/v1/sales/invoices")
    for i in d.get("invoices", []):
        if i["invoice_number"] == invoice_number:
            # detail menyertakan journal_entry_id
            try:
                det = _request("GET", f"/api/v1/sales/invoices/{i['id']}")
                i["journal_entry_id"] = det.get("journal_entry_id") or \
                    det.get("journal", {}).get("journal_entry_id") or ""
            except Exception:
                i["journal_entry_id"] = ""
            return i
    return None


def neraca() -> dict:
    return _request("GET", "/api/v1/reports/trial-balance")


def bank_accounts() -> list[dict]:
    d = _request("GET", "/api/v1/bank/accounts")
    return d.get("accounts", d if isinstance(d, list) else [])


def buat_bank_transaction(
    *,
    cash_bank_account_id: str,
    transaction_type: str,
    counter_account_code: str,
    amount,
    reference: str,
    description: str = "",
    idempotency_key: str,
    transaction_date: str,
) -> dict:
    return _request("POST", "/api/v1/bank/transactions", {
        "cash_bank_account_id": cash_bank_account_id,
        "transaction_type": transaction_type,
        "counter_account_code": counter_account_code,
        "amount": str(amount),
        "reference": reference,
        "description": description,
        "idempotency_key": idempotency_key,
        "transaction_date": transaction_date,
    })


def impor_statement(
    *,
    cash_bank_account_id: str,
    statement_reference: str,
    period_start: str,
    period_end: str,
    opening_balance,
    closing_balance,
    idempotency_key: str,
) -> dict:
    return _request("POST", "/api/v1/bank/statements", {
        "cash_bank_account_id": cash_bank_account_id,
        "statement_reference": statement_reference,
        "period_start": period_start,
        "period_end": period_end,
        "opening_balance": str(opening_balance),
        "closing_balance": str(closing_balance),
        "idempotency_key": idempotency_key,
    })


def tambah_statement_line(
    *,
    statement_id: str,
    line_number: int,
    transaction_date: str,
    direction: str,
    amount,
    external_reference: str = "",
    description: str = "",
) -> dict:
    return _request("POST", f"/api/v1/bank/statements/{statement_id}/lines", {
        "line_number": line_number,
        "transaction_date": transaction_date,
        "direction": direction,
        "amount": str(amount),
        "external_reference": external_reference,
        "description": description,
    })


def statement_outstanding() -> list[dict]:
    d = _request("GET", "/api/v1/bank/reconciliation/outstanding")
    return d.get("outstanding", [])


def cocokkan_statement(*, statement_line_id: str, source_type: str,
                       source_id: str, note: str = "") -> dict:
    return _request("POST",
                    f"/api/v1/bank/reconciliation/{statement_line_id}/match",
                    {"source_type": source_type, "source_id": source_id,
                     "note": note})


def opening_valuation(
    *,
    inventory_item_id: str,
    quantity,
    unit_cost,
    reference: str,
    reason: str = "",
    source: str = "PILOT_REFERENCE",
    reference_date: str | None = None,
    idempotency_key: str,
) -> dict:
    """Canonical opening valuation: assign cost basis to existing stock."""
    payload = {
        "inventory_item_id": inventory_item_id,
        "quantity": str(quantity),
        "unit_cost": str(unit_cost),
        "reference": reference,
        "reason": reason,
        "source": source,
        "idempotency_key": idempotency_key,
    }
    if reference_date is not None:
        payload["reference_date"] = reference_date
    return _request("POST", "/api/v1/inventory/opening-valuation", payload)
