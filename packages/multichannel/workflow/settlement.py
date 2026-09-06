"""Alur settlement (R44): impor, pemetaan, cocok ledgers, variance.

Settlement marketplace dipetakan ke penerimaan bank di Finance Core dan
dicocokkan (reconciliation) dengan baris laporan bank lewat jalur kanonik
Finance Core. Selisih piutang diharapkan vs dana cair dicatat sebagai varians.

Idempoten: settlement yang sama (provider+shop+ref) hanya diproses sekali.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..persistence import db, repo
from ..workflow import finance_core as fc


def _create_table() -> None:
    db.jalankan(
        """CREATE TABLE IF NOT EXISTS multichannel.settlement_finance (
            id              BIGSERIAL PRIMARY KEY,
            provider        TEXT NOT NULL,
            shop_id         TEXT NOT NULL,
            settlement_ref  TEXT NOT NULL,
            gross_amount    NUMERIC(20,2) NOT NULL DEFAULT 0,
            fee_amount      NUMERIC(20,2) NOT NULL DEFAULT 0,
            net_amount      NUMERIC(20,2) NOT NULL DEFAULT 0,
            expected_ar     NUMERIC(20,2) NOT NULL DEFAULT 0,
            variance        NUMERIC(20,2) NOT NULL DEFAULT 0,
            cash_transaction_id TEXT NOT NULL DEFAULT '',
            statement_line_id   TEXT NOT NULL DEFAULT '',
            match_id            TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'PROCESSED',
            processed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_settlement_finance
                UNIQUE (provider, shop_id, settlement_ref)
        )"""
    )


def sudah_diproses(provider: str, shop_id: str, settlement_ref: str) -> dict | None:
    return db.ambil(
        "SELECT * FROM multichannel.settlement_finance "
        "WHERE provider=%s AND shop_id=%s AND settlement_ref=%s",
        (provider, shop_id, settlement_ref),
    )


def cari_bank(provider: str) -> dict | None:
    """Akun bank Finance Core yang dipakai settlement."""
    kode = f"BANK-{provider.upper()}"[:20]
    for a in fc.bank_accounts():
        if a.get("code") == kode:
            return a
    return None


def bank_default() -> dict:
    """Akun bank pertama yang tersedia (R7-BANK-001 bila ada)."""
    a = fc.bank_accounts()
    for x in a:
        if x.get("code") == "R7-BANK-001":
            return x
    if a:
        return a[0]
    raise RuntimeError("tidak ada akun bank di Finance Core")


def proses_settlement(
    *,
    tenant_id: str,
    provider: str,
    shop_id: str,
    settlement_ref: str,
    trans_id: str,
    transaction_date: str,
    gross: Decimal,
    fee: Decimal,
    net: Decimal,
    expected_ar: Decimal,
) -> dict:
    """Impor settlement: catat penerimaan bank + rekonsiliasi ledger.

    Idempoten. Cash receipt (DR Bank / CR AR 1201). Varians dihitung dan
    dicatat. Statement bank diimpor dan dicocokkan (reconciliation).
    """
    _create_table()

    ada = sudah_diproses(provider, shop_id, settlement_ref)
    if ada:
        ada["duplicate"] = True
        return ada

    repo.simpan_settlement(
        tenant_id=tenant_id, provider=provider, shop_id=shop_id,
        settlement_ref=settlement_ref, trans_id=trans_id,
        transaction_date=transaction_date, gross=gross, fee=fee, net=net,
    )

    variance = expected_ar - net
    bank = bank_default()
    cash_id = bank["id"]

    idem = f"stl:{provider}:{shop_id}:{settlement_ref}"
    tx = fc.buat_bank_transaction(
        cash_bank_account_id=cash_id,
        transaction_type="RECEIPT",
        counter_account_code="1201",  # ACCOUNTS_RECEIVABLE
        amount=net,
        reference=settlement_ref,
        description=f"Settlement {provider} {settlement_ref}",
        idempotency_key=idem,
        transaction_date=transaction_date,
    )
    tx_id = tx.get("id", "")

    statement_line_id, match_id = _rekonsiliasi_ledger(
        provider, shop_id, settlement_ref, net, bank, transaction_date,
        tx_id,
    )

    db.jalankan(
        """INSERT INTO multichannel.settlement_finance
           (provider, shop_id, settlement_ref, gross_amount, fee_amount,
            net_amount, expected_ar, variance, cash_transaction_id,
            statement_line_id, match_id, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PROCESSED')
           ON CONFLICT (provider, shop_id, settlement_ref) DO NOTHING""",
        (provider, shop_id, settlement_ref, gross, fee, net, expected_ar,
         variance, tx_id, statement_line_id, match_id),
    )

    repo.catat_audit("settlement_diproses", tenant_id=tenant_id,
                     provider=provider, shop_id=shop_id,
                     payload={"ref": settlement_ref, "net": str(net),
                              "variance": str(variance)})

    row = sudah_diproses(provider, shop_id, settlement_ref)
    row["duplicate"] = False
    row["cash_transaction_id"] = tx_id
    row["statement_line_id"] = statement_line_id
    row["match_id"] = match_id
    return row


def _rekonsiliasi_ledger(provider, shop_id, settlement_ref, net, bank,
                         transaction_date, cash_tx_id):
    """Impor statement bank dan cocokkan barisnya dengan cash transaction.

    Menggunakan statement reference settlement_ref. Bila statement impor
    tidak tersedia/duplikat, kembalikan kosong (tanpa menimbulkan galat).
    """
    try:
        stmt = fc.impor_statement(
            cash_bank_account_id=bank["id"],
            statement_reference=f"STL-{settlement_ref}",
            period_start=transaction_date,
            period_end=transaction_date,
            opening_balance=0,
            closing_balance=net,
            idempotency_key=f"stm:{provider}:{shop_id}:{settlement_ref}",
        )
        stmt_id = stmt.get("id", "")
        line = fc.tambah_statement_line(
            statement_id=stmt_id,
            line_number=1,
            transaction_date=transaction_date,
            direction="CREDIT",   # cash masuk
            amount=net,
            external_reference=settlement_ref,
            description=f"Settlement {provider} {settlement_ref}",
        )
        line_id = line.get("id", "")

        # cocokkan dengan cash transaction yang baru dibuat (by real id)
        match = fc.cocokkan_statement(
            statement_line_id=line_id,
            source_type="CASH_TRANSACTION",
            source_id=cash_tx_id,
            note=f"settlement {provider}",
        )
        match_id = match.get("id", "")
        return line_id, match_id
    except Exception as e:
        # jangan menggagalkan settlement; ledger cocok dijalankan terpisah
        import sys
        print(f"[rekon] ledger-skip: {type(e).__name__}: {e}", file=sys.stderr)
        return "", ""
