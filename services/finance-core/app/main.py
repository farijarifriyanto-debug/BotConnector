import os
import uuid
from decimal import Decimal
from datetime import date, datetime, timezone

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ConfigDict


DB_HOST = os.environ.get("FINANCE_DB_HOST", "botconnector-core-postgres")
DB_PORT = int(os.environ.get("FINANCE_DB_PORT", "5432"))
DB_NAME = os.environ["FINANCE_DB_NAME"]
DB_USER = os.environ["FINANCE_DB_USER"]
DB_PASSWORD = os.environ["FINANCE_DB_PASSWORD"]


app = FastAPI(
    title="BotConnector Finance Core",
    version="0.7.2-r7b",
)


SUPPORTED_EVENTS = {
    "payment.pending",
    "payment.paid",
    "payment.failed",
    "payment.cancelled",
    "payment.expired",
    "payment.refunded",
}


class InventorySalesReturnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_inventory_movement_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    reference: str = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=255)



class InventoryOpeningValuationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_item_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    reference: str = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=500)
    source: str = Field(default="PILOT_REFERENCE", min_length=1, max_length=100)
    reference_date: date | None = Field(default=None)
    idempotency_key: str = Field(min_length=1, max_length=255)

class CanonicalPayment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_payment_id: str = Field(min_length=1, max_length=255)
    order_id: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    status: str = Field(min_length=1, max_length=100)


class CanonicalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1

    source_system: str = Field(
        default="business_core",
        min_length=1,
        max_length=100,
    )

    source_event: str = Field(
        min_length=1,
        max_length=100,
    )

    source_event_id: str = Field(
        min_length=1,
        max_length=255,
    )

    occurred_at: datetime | None = None

    payment: CanonicalPayment


def db():
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def default_company(cur):
    cur.execute(
        """
        SELECT id
        FROM companies
        WHERE code='DEFAULT'
        """
    )

    row = cur.fetchone()

    if not row:
        raise RuntimeError("default company missing")

    return row[0]


def account(cur, company_id, system_key):
    cur.execute(
        """
        SELECT id
        FROM accounts
        WHERE company_id=%s
          AND system_key=%s
          AND active=true
        """,
        (company_id, system_key),
    )

    row = cur.fetchone()

    if not row:
        raise RuntimeError(
            f"required account missing: {system_key}"
        )

    return row[0]


def fiscal_period(cur, company_id, journal_date):
    cur.execute(
        """
        SELECT id
        FROM fiscal_periods
        WHERE company_id=%s
          AND starts_on <= %s
          AND ends_on >= %s
          AND status='OPEN'
        ORDER BY starts_on DESC
        LIMIT 1
        """,
        (
            company_id,
            journal_date,
            journal_date,
        ),
    )

    row = cur.fetchone()

    if not row:
        raise RuntimeError(
            "no open fiscal period for event date"
        )

    return row[0]


@app.get("/health")
def health():
    try:
        with db() as con:
            with con.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        return {
            "ok": True,
            "service": "botconnector-finance-core",
            "version": "0.7.2-r7b",
            "database": "ok",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="database unavailable",
        ) from exc


@app.post("/api/v1/events/business-core")
def receive_business_core_event(event: CanonicalEvent):

    if event.source_event not in SUPPORTED_EVENTS:
        raise HTTPException(
            status_code=422,
            detail="unsupported canonical event",
        )

    if event.payment.status != event.source_event:
        raise HTTPException(
            status_code=422,
            detail="payment.status must equal source_event",
        )

    currency = event.payment.currency.upper()

    if currency != "IDR":
        raise HTTPException(
            status_code=422,
            detail="R3 accepts IDR only",
        )

    idempotency_key = (
        f"{event.source_system}:"
        f"{event.source_event}:"
        f"{event.source_event_id}"
    )

    occurred = event.occurred_at or datetime.now(timezone.utc)
    journal_date = occurred.date()

    try:
        with db() as con:
            with con.cursor() as cur:

                company_id = default_company(cur)

                # ------------------------------------------------
                # Idempotency first
                # ------------------------------------------------

                cur.execute(
                    """
                    SELECT
                        id,
                        status
                    FROM business_events
                    WHERE company_id=%s
                      AND idempotency_key=%s
                    """,
                    (
                        company_id,
                        idempotency_key,
                    ),
                )

                duplicate = cur.fetchone()

                if duplicate:
                    return {
                        "ok": True,
                        "duplicate": True,
                        "business_event_id": str(duplicate[0]),
                        "status": duplicate[1],
                    }

                business_event_id = uuid.uuid4()

                cur.execute(
                    """
                    INSERT INTO business_events (
                        id,
                        company_id,
                        source_system,
                        source_event,
                        source_event_id,
                        external_reference,
                        idempotency_key,
                        schema_version,
                        occurred_at,
                        payload
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    )
                    """,
                    (
                        business_event_id,
                        company_id,
                        event.source_system,
                        event.source_event,
                        event.source_event_id,
                        event.payment.order_id,
                        idempotency_key,
                        event.schema_version,
                        occurred,
                        event.model_dump_json(),
                    ),
                )

                # ------------------------------------------------
                # Non-financial state events:
                # ledger evidence only
                # ------------------------------------------------

                if event.source_event in {
                    "payment.pending",
                    "payment.failed",
                    "payment.cancelled",
                    "payment.expired",
                }:
                    cur.execute(
                        """
                        UPDATE business_events
                        SET
                            status='PROCESSED',
                            processed_at=now()
                        WHERE id=%s
                        """,
                        (business_event_id,),
                    )

                    con.commit()

                    return {
                        "ok": True,
                        "duplicate": False,
                        "posted": False,
                        "event": event.source_event,
                        "business_event_id": str(business_event_id),
                    }

                # ------------------------------------------------
                # payment.paid
                # ------------------------------------------------

                if event.source_event == "payment.paid":

                    period_id = fiscal_period(
                        cur,
                        company_id,
                        journal_date,
                    )

                    clearing = account(
                        cur,
                        company_id,
                        "PAYMENT_CLEARING",
                    )

                    suspense = account(
                        cur,
                        company_id,
                        "UNALLOCATED_RECEIPT",
                    )

                    journal_id = uuid.uuid4()

                    journal_number = (
                        "PAY-"
                        + event.source_event_id[:24]
                    )

                    cur.execute(
                        """
                        INSERT INTO journal_entries (
                            id,
                            company_id,
                            fiscal_period_id,
                            journal_number,
                            journal_date,
                            description,
                            currency,
                            source_system,
                            source_type,
                            source_id,
                            business_event_id
                        )
                        VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                        )
                        """,
                        (
                            journal_id,
                            company_id,
                            period_id,
                            journal_number,
                            journal_date,
                            (
                                "Canonical payment received "
                                f"for order {event.payment.order_id}"
                            ),
                            currency,
                            event.source_system,
                            event.source_event,
                            event.source_event_id,
                            business_event_id,
                        ),
                    )

                    amount = event.payment.amount

                    cur.execute(
                        """
                        INSERT INTO journal_lines (
                            journal_entry_id,
                            line_number,
                            account_id,
                            description,
                            debit,
                            credit
                        )
                        VALUES
                        (%s,1,%s,%s,%s,0),
                        (%s,2,%s,%s,0,%s)
                        """,
                        (
                            journal_id,
                            clearing,
                            "Payment clearing",
                            amount,

                            journal_id,
                            suspense,
                            "Unallocated receipt",
                            amount,
                        ),
                    )

                    cur.execute(
                        """
                        SELECT finance_post_journal(%s)
                        """,
                        (journal_id,),
                    )

                    cur.execute(
                        """
                        INSERT INTO payment_event_postings (
                            company_id,
                            business_event_id,
                            external_payment_id,
                            order_id,
                            amount,
                            currency,
                            canonical_status,
                            journal_entry_id
                        )
                        VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s
                        )
                        """,
                        (
                            company_id,
                            business_event_id,
                            event.payment.external_payment_id,
                            event.payment.order_id,
                            amount,
                            currency,
                            event.source_event,
                            journal_id,
                        ),
                    )

                    cur.execute(
                        """
                        UPDATE business_events
                        SET
                            status='PROCESSED',
                            processed_at=now()
                        WHERE id=%s
                        """,
                        (business_event_id,),
                    )

                    con.commit()

                    return {
                        "ok": True,
                        "duplicate": False,
                        "posted": True,
                        "event": event.source_event,
                        "business_event_id": str(business_event_id),
                        "journal_entry_id": str(journal_id),
                        "journal_number": journal_number,
                    }

                # ------------------------------------------------
                # payment.refunded
                #
                # R3 records canonical evidence only.
                # Full refund linkage/reversal comes in R4.
                # ------------------------------------------------

                if event.source_event == "payment.refunded":

                    # --------------------------------------------
                    # Resolve the original canonical payment.
                    #
                    # Require BOTH external_payment_id and order_id
                    # to prevent accidental cross-order refund.
                    # --------------------------------------------

                    cur.execute(
                        """
                        SELECT id
                        FROM payment_event_postings
                        WHERE company_id=%s
                          AND canonical_status='payment.paid'
                          AND external_payment_id=%s
                          AND order_id=%s
                        ORDER BY created_at
                        """,
                        (
                            company_id,
                            event.payment.external_payment_id,
                            event.payment.order_id,
                        ),
                    )

                    matching_payments = cur.fetchall()

                    if len(matching_payments) == 0:
                        raise HTTPException(
                            status_code=409,
                            detail="original payment.paid not found",
                        )

                    if len(matching_payments) > 1:
                        raise HTTPException(
                            status_code=409,
                            detail="original payment is ambiguous",
                        )

                    payment_posting_id = matching_payments[0][0]

                    # Canonical source_event_id is the immutable
                    # refund reference and therefore also provides
                    # refund-level idempotency.
                    cur.execute(
                        """
                        SELECT finance_refund_payment(
                            %s,
                            %s,
                            %s
                        )
                        """,
                        (
                            payment_posting_id,
                            event.payment.amount,
                            event.source_event_id,
                        ),
                    )

                    refund_id = cur.fetchone()[0]

                    # Link the accounting refund back to the
                    # canonical Business Core event.
                    cur.execute(
                        """
                        UPDATE payment_refunds
                        SET refund_business_event_id=%s
                        WHERE id=%s
                        """,
                        (
                            business_event_id,
                            refund_id,
                        ),
                    )

                    cur.execute(
                        """
                        UPDATE business_events
                        SET
                            status='PROCESSED',
                            processed_at=now()
                        WHERE id=%s
                        """,
                        (business_event_id,),
                    )

                    con.commit()

                    return {
                        "ok": True,
                        "duplicate": False,
                        "posted": True,
                        "event": event.source_event,
                        "business_event_id": str(business_event_id),
                        "refund_id": str(refund_id),
                        "original_payment_posting_id": str(
                            payment_posting_id
                        ),
                    }

        raise HTTPException(
            status_code=500,
            detail="unexpected event flow",
        )

    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="canonical event conflict",
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.get("/api/v1/ledger/trial-balance")
def trial_balance():
    with db() as con:
        with con.cursor() as cur:

            cur.execute(
                """
                SELECT
                    a.code,
                    a.name,
                    a.type::text,
                    COALESCE(SUM(
                        CASE
                            WHEN j.status IN ('POSTED','REVERSED')
                            THEN l.debit
                            ELSE 0
                        END
                    ),0) AS debit,

                    COALESCE(SUM(
                        CASE
                            WHEN j.status IN ('POSTED','REVERSED')
                            THEN l.credit
                            ELSE 0
                        END
                    ),0) AS credit

                FROM accounts a

                LEFT JOIN journal_lines l
                  ON l.account_id=a.id

                LEFT JOIN journal_entries j
                  ON j.id=l.journal_entry_id

                WHERE a.active=true

                GROUP BY
                    a.code,
                    a.name,
                    a.type

                ORDER BY a.code
                """
            )

            rows = cur.fetchall()

    return {
        "accounts": [
            {
                "code": r[0],
                "name": r[1],
                "type": r[2],
                "debit": str(r[3]),
                "credit": str(r[4]),
            }
            for r in rows
        ]
    }


# ============================================================
# R4B — SALES / AR API
# ============================================================

from datetime import timedelta
from typing import Optional


class CustomerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    email: str | None = None
    phone: str | None = None
    tax_id: str | None = None
    billing_address: str | None = None


class SalesInvoiceLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)


class SalesInvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: uuid.UUID
    invoice_number: str = Field(min_length=1, max_length=100)
    invoice_date: date
    due_date: date
    currency: str = Field(default="IDR", min_length=3, max_length=3)
    source_system: str = Field(default="finance_core", max_length=100)
    source_id: str | None = Field(default=None, max_length=255)

    lines: list[SalesInvoiceLineCreate] = Field(min_length=1)


class PaymentAllocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: uuid.UUID
    amount: Decimal = Field(gt=0)


def fetch_company_id(cur):
    cur.execute(
        """
        SELECT id
        FROM companies
        WHERE code='DEFAULT'
        """
    )

    row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=500,
            detail="default company missing",
        )

    return row[0]


@app.post("/api/v1/customers")
def create_customer(payload: CustomerCreate):
    try:
        with db() as con:
            with con.cursor() as cur:
                company_id = fetch_company_id(cur)

                customer_id = uuid.uuid4()

                cur.execute(
                    """
                    INSERT INTO customers (
                        id,
                        company_id,
                        code,
                        name,
                        email,
                        phone,
                        tax_id,
                        billing_address
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        customer_id,
                        company_id,
                        payload.code,
                        payload.name,
                        payload.email,
                        payload.phone,
                        payload.tax_id,
                        payload.billing_address,
                    ),
                )

                con.commit()

        return {
            "ok": True,
            "id": str(customer_id),
            "code": payload.code,
            "name": payload.name,
        }

    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="customer code already exists",
        ) from exc


@app.get("/api/v1/customers")
def list_customers():
    with db() as con:
        with con.cursor() as cur:
            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    id,
                    code,
                    name,
                    email,
                    phone,
                    tax_id,
                    billing_address,
                    active
                FROM customers
                WHERE company_id=%s
                ORDER BY name, code
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    return {
        "customers": [
            {
                "id": str(r[0]),
                "code": r[1],
                "name": r[2],
                "email": r[3],
                "phone": r[4],
                "tax_id": r[5],
                "billing_address": r[6],
                "active": r[7],
            }
            for r in rows
        ]
    }


@app.post("/api/v1/sales/invoices")
def create_sales_invoice(payload: SalesInvoiceCreate):

    if payload.due_date < payload.invoice_date:
        raise HTTPException(
            status_code=422,
            detail="due_date cannot be before invoice_date",
        )

    currency = payload.currency.upper()

    if currency != "IDR":
        raise HTTPException(
            status_code=422,
            detail="R4B accepts IDR only",
        )

    try:
        with db() as con:
            with con.cursor() as cur:
                company_id = fetch_company_id(cur)

                cur.execute(
                    """
                    SELECT id
                    FROM customers
                    WHERE id=%s
                      AND company_id=%s
                      AND active=true
                    """,
                    (
                        payload.customer_id,
                        company_id,
                    ),
                )

                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404,
                        detail="customer not found",
                    )

                cur.execute(
                    """
                    SELECT id
                    FROM accounts
                    WHERE company_id=%s
                      AND system_key='SALES_REVENUE'
                      AND active=true
                    """,
                    (company_id,),
                )

                revenue = cur.fetchone()

                if not revenue:
                    raise HTTPException(
                        status_code=500,
                        detail="sales revenue account missing",
                    )

                revenue_id = revenue[0]

                subtotal = Decimal("0")
                tax_total = Decimal("0")

                computed_lines = []

                for idx, line in enumerate(payload.lines, start=1):
                    line_subtotal = (
                        line.quantity * line.unit_price
                    ).quantize(Decimal("0.01"))

                    subtotal += line_subtotal
                    tax_total += line.tax_amount

                    computed_lines.append(
                        (
                            idx,
                            line.description,
                            line.quantity,
                            line.unit_price,
                            line_subtotal,
                            line.tax_amount,
                        )
                    )

                total = subtotal + tax_total

                if total <= 0:
                    raise HTTPException(
                        status_code=422,
                        detail="invoice total must be positive",
                    )

                invoice_id = uuid.uuid4()

                cur.execute(
                    """
                    INSERT INTO sales_invoices (
                        id,
                        company_id,
                        customer_id,
                        invoice_number,
                        invoice_date,
                        due_date,
                        currency,
                        subtotal,
                        tax_amount,
                        total_amount,
                        source_system,
                        source_id
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    )
                    """,
                    (
                        invoice_id,
                        company_id,
                        payload.customer_id,
                        payload.invoice_number,
                        payload.invoice_date,
                        payload.due_date,
                        currency,
                        subtotal,
                        tax_total,
                        total,
                        payload.source_system,
                        payload.source_id,
                    ),
                )

                for (
                    line_number,
                    description,
                    quantity,
                    unit_price,
                    line_subtotal,
                    tax_amount,
                ) in computed_lines:

                    cur.execute(
                        """
                        INSERT INTO sales_invoice_lines (
                            sales_invoice_id,
                            line_number,
                            description,
                            quantity,
                            unit_price,
                            line_subtotal,
                            tax_amount,
                            revenue_account_id
                        )
                        VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s
                        )
                        """,
                        (
                            invoice_id,
                            line_number,
                            description,
                            quantity,
                            unit_price,
                            line_subtotal,
                            tax_amount,
                            revenue_id,
                        ),
                    )

                con.commit()

        return {
            "ok": True,
            "id": str(invoice_id),
            "invoice_number": payload.invoice_number,
            "subtotal": str(subtotal),
            "tax_amount": str(tax_total),
            "total_amount": str(total),
            "status": "DRAFT",
        }

    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="invoice number already exists",
        ) from exc


@app.get("/api/v1/sales/invoices")
def list_sales_invoices():
    with db() as con:
        with con.cursor() as cur:
            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.id,
                    i.invoice_number,
                    i.invoice_date,
                    i.due_date,
                    i.currency,
                    i.subtotal,
                    i.tax_amount,
                    i.total_amount,
                    i.paid_amount,
                    i.total_amount-i.paid_amount,
                    i.status::text,
                    c.id,
                    c.code,
                    c.name
                FROM sales_invoices i
                JOIN customers c
                  ON c.id=i.customer_id
                WHERE i.company_id=%s
                ORDER BY i.invoice_date DESC,
                         i.invoice_number DESC
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    return {
        "invoices": [
            {
                "id": str(r[0]),
                "invoice_number": r[1],
                "invoice_date": r[2].isoformat(),
                "due_date": r[3].isoformat(),
                "currency": r[4],
                "subtotal": str(r[5]),
                "tax_amount": str(r[6]),
                "total_amount": str(r[7]),
                "paid_amount": str(r[8]),
                "outstanding": str(r[9]),
                "status": r[10],
                "customer": {
                    "id": str(r[11]),
                    "code": r[12],
                    "name": r[13],
                },
            }
            for r in rows
        ]
    }


@app.get("/api/v1/sales/invoices/{invoice_id}")
def get_sales_invoice(invoice_id: uuid.UUID):
    with db() as con:
        with con.cursor() as cur:
            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.id,
                    i.invoice_number,
                    i.invoice_date,
                    i.due_date,
                    i.currency,
                    i.subtotal,
                    i.tax_amount,
                    i.total_amount,
                    i.paid_amount,
                    i.total_amount-i.paid_amount,
                    i.status::text,
                    c.id,
                    c.code,
                    c.name,
                    i.journal_entry_id
                FROM sales_invoices i
                JOIN customers c
                  ON c.id=i.customer_id
                WHERE i.id=%s
                  AND i.company_id=%s
                """,
                (
                    invoice_id,
                    company_id,
                ),
            )

            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="invoice not found",
                )

            cur.execute(
                """
                SELECT
                    line_number,
                    description,
                    quantity,
                    unit_price,
                    line_subtotal,
                    tax_amount
                FROM sales_invoice_lines
                WHERE sales_invoice_id=%s
                ORDER BY line_number
                """,
                (invoice_id,),
            )

            lines = cur.fetchall()

    return {
        "id": str(row[0]),
        "invoice_number": row[1],
        "invoice_date": row[2].isoformat(),
        "due_date": row[3].isoformat(),
        "currency": row[4],
        "subtotal": str(row[5]),
        "tax_amount": str(row[6]),
        "total_amount": str(row[7]),
        "paid_amount": str(row[8]),
        "outstanding": str(row[9]),
        "status": row[10],
        "customer": {
            "id": str(row[11]),
            "code": row[12],
            "name": row[13],
        },
        "journal_entry_id": (
            str(row[14])
            if row[14]
            else None
        ),
        "lines": [
            {
                "line_number": r[0],
                "description": r[1],
                "quantity": str(r[2]),
                "unit_price": str(r[3]),
                "line_subtotal": str(r[4]),
                "tax_amount": str(r[5]),
            }
            for r in lines
        ],
    }


@app.post("/api/v1/sales/invoices/{invoice_id}/issue")
def issue_sales_invoice(invoice_id: uuid.UUID):
    try:
        with db() as con:
            with con.cursor() as cur:
                company_id = fetch_company_id(cur)

                cur.execute(
                    """
                    SELECT id
                    FROM sales_invoices
                    WHERE id=%s
                      AND company_id=%s
                    """,
                    (
                        invoice_id,
                        company_id,
                    ),
                )

                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404,
                        detail="invoice not found",
                    )

                cur.execute(
                    """
                    SELECT finance_issue_sales_invoice(%s)
                    """,
                    (invoice_id,),
                )

                journal_id = cur.fetchone()[0]

                con.commit()

        return {
            "ok": True,
            "invoice_id": str(invoice_id),
            "journal_entry_id": str(journal_id),
            "status": "ISSUED",
        }

    except psycopg.errors.RaiseException as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc




@app.post("/api/v1/inventory/sales-returns")
def create_inventory_sales_return(payload: InventorySalesReturnCreate):
    """Canonical sales return: reverse revenue-related COGS/inventory movement.

    Idempotent via idempotency_key. Calls the existing finance_inventory_sales_return
    database function which creates the journal reversal and inventory return movement.
    """
    with db() as con:
        try:
            with con.cursor() as cur:
                company_id = fetch_company_id(cur)
                cur.execute(
                    "SELECT finance_inventory_sales_return(%s,%s,%s,%s,%s)",
                    (
                        payload.original_inventory_movement_id,
                        payload.quantity,
                        payload.reference,
                        payload.idempotency_key,
                        payload.reason,
                    ),
                )
                return_id = cur.fetchone()[0]
                con.commit()
                return {
                    "ok": True,
                    "return_id": str(return_id),
                    "status": "POSTED",
                }
        except HTTPException:
            con.rollback()
            raise
    

@app.post("/api/v1/inventory/opening-valuation")
def create_inventory_opening_valuation(payload: InventoryOpeningValuationCreate):
    """Canonical opening valuation: assign a cost basis to existing stock without changing quantity.

    Idempotent via idempotency_key. Creates a journal entry (Dr Inventory, Cr Owner Equity)
    and an OPENING_VALUATION movement. Intended for truthful pilot reference cost
    initialization when no supplier invoice exists.
    """
    with db() as con:
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT finance_inventory_opening_valuation(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        payload.inventory_item_id,
                        payload.quantity,
                        payload.unit_cost,
                        payload.reference,
                        payload.reason,
                        payload.source,
                        payload.reference_date,
                        payload.idempotency_key,
                    ),
                )
                adjustment_id = cur.fetchone()[0]
                con.commit()
                return {
                    "ok": True,
                    "adjustment_id": str(adjustment_id),
                    "status": "POSTED",
                }
        except HTTPException:
            con.rollback()
            raise
        except Exception as exc:
            con.rollback()
            raise HTTPException(status_code=409, detail=str(exc))



@app.get("/api/v1/ar/outstanding")
def ar_outstanding():
    with db() as con:
        with con.cursor() as cur:
            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.id,
                    i.invoice_number,
                    c.code,
                    c.name,
                    i.invoice_date,
                    i.due_date,
                    i.total_amount,
                    i.paid_amount,
                    i.total_amount-i.paid_amount AS outstanding,
                    i.status::text
                FROM sales_invoices i
                JOIN customers c
                  ON c.id=i.customer_id
                WHERE i.company_id=%s
                  AND i.status IN (
                      'ISSUED',
                      'PARTIALLY_PAID'
                  )
                  AND i.total_amount-i.paid_amount > 0
                ORDER BY i.due_date,
                         i.invoice_number
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    return {
        "receivables": [
            {
                "invoice_id": str(r[0]),
                "invoice_number": r[1],
                "customer_code": r[2],
                "customer_name": r[3],
                "invoice_date": r[4].isoformat(),
                "due_date": r[5].isoformat(),
                "total_amount": str(r[6]),
                "paid_amount": str(r[7]),
                "outstanding": str(r[8]),
                "status": r[9],
            }
            for r in rows
        ]
    }


@app.get("/api/v1/ar/aging")
def ar_aging(as_of: Optional[date] = None):
    cutoff = as_of or date.today()

    with db() as con:
        with con.cursor() as cur:
            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.invoice_number,
                    c.code,
                    c.name,
                    i.due_date,
                    i.total_amount-i.paid_amount AS outstanding
                FROM sales_invoices i
                JOIN customers c
                  ON c.id=i.customer_id
                WHERE i.company_id=%s
                  AND i.status IN (
                      'ISSUED',
                      'PARTIALLY_PAID'
                  )
                  AND i.total_amount-i.paid_amount > 0
                ORDER BY i.due_date
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    buckets = {
        "current": Decimal("0"),
        "1_30": Decimal("0"),
        "31_60": Decimal("0"),
        "61_90": Decimal("0"),
        "over_90": Decimal("0"),
    }

    details = []

    for r in rows:
        days = (cutoff - r[3]).days
        amount = r[4]

        if days <= 0:
            bucket = "current"
        elif days <= 30:
            bucket = "1_30"
        elif days <= 60:
            bucket = "31_60"
        elif days <= 90:
            bucket = "61_90"
        else:
            bucket = "over_90"

        buckets[bucket] += amount

        details.append(
            {
                "invoice_number": r[0],
                "customer_code": r[1],
                "customer_name": r[2],
                "due_date": r[3].isoformat(),
                "days_overdue": max(days, 0),
                "outstanding": str(amount),
                "bucket": bucket,
            }
        )

    return {
        "as_of": cutoff.isoformat(),
        "buckets": {
            k: str(v)
            for k, v in buckets.items()
        },
        "details": details,
    }


@app.get("/api/v1/payments/unallocated")
def unallocated_payments():
    with db() as con:
        with con.cursor() as cur:
            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    p.id,
                    p.external_payment_id,
                    p.order_id,
                    p.amount,
                    p.currency,
                    p.created_at,
                    p.amount-COALESCE(
                        SUM(
                            CASE
                                WHEN a.status='ACTIVE'
                                THEN a.amount
                                ELSE 0
                            END
                        ),
                        0
                    ) AS available
                FROM payment_event_postings p
                LEFT JOIN payment_allocations a
                  ON a.payment_event_posting_id=p.id
                WHERE p.company_id=%s
                  AND p.canonical_status='payment.paid'
                GROUP BY
                    p.id,
                    p.external_payment_id,
                    p.order_id,
                    p.amount,
                    p.currency,
                    p.created_at
                HAVING
                    p.amount-COALESCE(
                        SUM(
                            CASE
                                WHEN a.status='ACTIVE'
                                THEN a.amount
                                ELSE 0
                            END
                        ),
                        0
                    ) > 0
                ORDER BY p.created_at
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    return {
        "payments": [
            {
                "payment_id": str(r[0]),
                "external_payment_id": r[1],
                "order_id": r[2],
                "amount": str(r[3]),
                "currency": r[4],
                "created_at": r[5].isoformat(),
                "available": str(r[6]),
            }
            for r in rows
        ]
    }


@app.post("/api/v1/payments/{payment_id}/allocate")
def allocate_payment(
    payment_id: uuid.UUID,
    payload: PaymentAllocationCreate,
):
    try:
        with db() as con:
            with con.cursor() as cur:

                cur.execute(
                    """
                    SELECT finance_allocate_payment(
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        payment_id,
                        payload.invoice_id,
                        payload.amount,
                    ),
                )

                journal_id = cur.fetchone()[0]

                con.commit()

        return {
            "ok": True,
            "payment_id": str(payment_id),
            "invoice_id": str(payload.invoice_id),
            "amount": str(payload.amount),
            "journal_entry_id": str(journal_id),
        }

    except psycopg.errors.RaiseException as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc


# ============================================================
# R5B — PURCHASE / ACCOUNTS PAYABLE API
# ============================================================

class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    email: str | None = None
    phone: str | None = None
    tax_id: str | None = None
    address: str | None = None


class PurchaseInvoiceLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)

    # Expense / inventory / asset account.
    posting_account_id: uuid.UUID


class PurchaseInvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: uuid.UUID

    invoice_number: str = Field(min_length=1, max_length=100)
    supplier_reference: str | None = Field(
        default=None,
        max_length=255,
    )

    invoice_date: date
    due_date: date

    currency: str = Field(
        default="IDR",
        min_length=3,
        max_length=3,
    )

    source_system: str = Field(
        default="finance_core",
        max_length=100,
    )

    source_id: str | None = Field(
        default=None,
        max_length=255,
    )

    lines: list[PurchaseInvoiceLineCreate] = Field(
        min_length=1
    )


class SupplierPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0)

    payment_number: str = Field(
        min_length=1,
        max_length=100,
    )

    payment_date: date

    # CASH or BANK.
    cash_account_id: uuid.UUID


@app.post("/api/v1/suppliers")
def create_supplier(payload: SupplierCreate):

    try:

        with db() as con:
            with con.cursor() as cur:

                company_id = fetch_company_id(cur)

                supplier_id = uuid.uuid4()

                cur.execute(
                    """
                    INSERT INTO suppliers (
                        id,
                        company_id,
                        code,
                        name,
                        email,
                        phone,
                        tax_id,
                        address
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s
                    )
                    """,
                    (
                        supplier_id,
                        company_id,
                        payload.code,
                        payload.name,
                        payload.email,
                        payload.phone,
                        payload.tax_id,
                        payload.address,
                    ),
                )

                con.commit()

        return {
            "ok": True,
            "id": str(supplier_id),
            "code": payload.code,
            "name": payload.name,
        }

    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="supplier code already exists",
        ) from exc


@app.get("/api/v1/suppliers")
def list_suppliers():

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    id,
                    code,
                    name,
                    email,
                    phone,
                    tax_id,
                    address,
                    active
                FROM suppliers
                WHERE company_id=%s
                ORDER BY name, code
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    return {
        "suppliers": [
            {
                "id": str(r[0]),
                "code": r[1],
                "name": r[2],
                "email": r[3],
                "phone": r[4],
                "tax_id": r[5],
                "address": r[6],
                "active": r[7],
            }
            for r in rows
        ]
    }


@app.post("/api/v1/purchases/invoices")
def create_purchase_invoice(
    payload: PurchaseInvoiceCreate
):

    if payload.due_date < payload.invoice_date:
        raise HTTPException(
            status_code=422,
            detail="due_date cannot be before invoice_date",
        )

    currency = payload.currency.upper()

    if currency != "IDR":
        raise HTTPException(
            status_code=422,
            detail="R5B accepts IDR only",
        )

    try:

        with db() as con:
            with con.cursor() as cur:

                company_id = fetch_company_id(cur)

                cur.execute(
                    """
                    SELECT id
                    FROM suppliers
                    WHERE id=%s
                      AND company_id=%s
                      AND active=true
                    """,
                    (
                        payload.supplier_id,
                        company_id,
                    ),
                )

                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404,
                        detail="supplier not found",
                    )

                subtotal = Decimal("0")
                tax_total = Decimal("0")

                computed = []

                for idx, line in enumerate(
                    payload.lines,
                    start=1,
                ):

                    # Validate account ownership and type.
                    cur.execute(
                        """
                        SELECT id
                        FROM accounts
                        WHERE id=%s
                          AND company_id=%s
                          AND active=true
                          AND type::text IN (
                              'ASSET',
                              'EXPENSE'
                          )
                        """,
                        (
                            line.posting_account_id,
                            company_id,
                        ),
                    )

                    if not cur.fetchone():
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                "invalid purchase "
                                "posting_account_id"
                            ),
                        )

                    line_subtotal = (
                        line.quantity * line.unit_price
                    ).quantize(Decimal("0.01"))

                    subtotal += line_subtotal
                    tax_total += line.tax_amount

                    computed.append(
                        (
                            idx,
                            line.description,
                            line.quantity,
                            line.unit_price,
                            line_subtotal,
                            line.tax_amount,
                            line.posting_account_id,
                        )
                    )

                total = subtotal + tax_total

                if total <= 0:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "purchase invoice total "
                            "must be positive"
                        ),
                    )

                invoice_id = uuid.uuid4()

                cur.execute(
                    """
                    INSERT INTO purchase_invoices (
                        id,
                        company_id,
                        supplier_id,
                        invoice_number,
                        supplier_reference,
                        invoice_date,
                        due_date,
                        currency,
                        subtotal,
                        tax_amount,
                        total_amount,
                        source_system,
                        source_id
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s
                    )
                    """,
                    (
                        invoice_id,
                        company_id,
                        payload.supplier_id,
                        payload.invoice_number,
                        payload.supplier_reference,
                        payload.invoice_date,
                        payload.due_date,
                        currency,
                        subtotal,
                        tax_total,
                        total,
                        payload.source_system,
                        payload.source_id,
                    ),
                )

                for (
                    line_number,
                    description,
                    quantity,
                    unit_price,
                    line_subtotal,
                    tax_amount,
                    posting_account_id,
                ) in computed:

                    cur.execute(
                        """
                        INSERT INTO purchase_invoice_lines (
                            purchase_invoice_id,
                            line_number,
                            description,
                            quantity,
                            unit_price,
                            line_subtotal,
                            tax_amount,
                            posting_account_id
                        )
                        VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s
                        )
                        """,
                        (
                            invoice_id,
                            line_number,
                            description,
                            quantity,
                            unit_price,
                            line_subtotal,
                            tax_amount,
                            posting_account_id,
                        ),
                    )

                con.commit()

        return {
            "ok": True,
            "id": str(invoice_id),
            "invoice_number": payload.invoice_number,
            "subtotal": str(subtotal),
            "tax_amount": str(tax_total),
            "total_amount": str(total),
            "status": "DRAFT",
        }

    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "purchase invoice number "
                "already exists"
            ),
        ) from exc


@app.get("/api/v1/purchases/invoices")
def list_purchase_invoices():

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.id,
                    i.invoice_number,
                    i.supplier_reference,
                    i.invoice_date,
                    i.due_date,
                    i.currency,
                    i.subtotal,
                    i.tax_amount,
                    i.total_amount,
                    i.paid_amount,
                    i.total_amount-i.paid_amount,
                    i.status::text,
                    s.id,
                    s.code,
                    s.name
                FROM purchase_invoices i
                JOIN suppliers s
                  ON s.id=i.supplier_id
                WHERE i.company_id=%s
                ORDER BY
                    i.invoice_date DESC,
                    i.invoice_number DESC
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    return {
        "invoices": [
            {
                "id": str(r[0]),
                "invoice_number": r[1],
                "supplier_reference": r[2],
                "invoice_date": r[3].isoformat(),
                "due_date": r[4].isoformat(),
                "currency": r[5],
                "subtotal": str(r[6]),
                "tax_amount": str(r[7]),
                "total_amount": str(r[8]),
                "paid_amount": str(r[9]),
                "outstanding": str(r[10]),
                "status": r[11],
                "supplier": {
                    "id": str(r[12]),
                    "code": r[13],
                    "name": r[14],
                },
            }
            for r in rows
        ]
    }


@app.get("/api/v1/purchases/invoices/{invoice_id}")
def get_purchase_invoice(invoice_id: uuid.UUID):

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.id,
                    i.invoice_number,
                    i.supplier_reference,
                    i.invoice_date,
                    i.due_date,
                    i.currency,
                    i.subtotal,
                    i.tax_amount,
                    i.total_amount,
                    i.paid_amount,
                    i.total_amount-i.paid_amount,
                    i.status::text,
                    s.id,
                    s.code,
                    s.name,
                    i.journal_entry_id
                FROM purchase_invoices i
                JOIN suppliers s
                  ON s.id=i.supplier_id
                WHERE i.id=%s
                  AND i.company_id=%s
                """,
                (
                    invoice_id,
                    company_id,
                ),
            )

            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="purchase invoice not found",
                )

            cur.execute(
                """
                SELECT
                    l.line_number,
                    l.description,
                    l.quantity,
                    l.unit_price,
                    l.line_subtotal,
                    l.tax_amount,
                    a.id,
                    a.code,
                    a.name
                FROM purchase_invoice_lines l
                JOIN accounts a
                  ON a.id=l.posting_account_id
                WHERE l.purchase_invoice_id=%s
                ORDER BY l.line_number
                """,
                (invoice_id,),
            )

            lines = cur.fetchall()

    return {
        "id": str(row[0]),
        "invoice_number": row[1],
        "supplier_reference": row[2],
        "invoice_date": row[3].isoformat(),
        "due_date": row[4].isoformat(),
        "currency": row[5],
        "subtotal": str(row[6]),
        "tax_amount": str(row[7]),
        "total_amount": str(row[8]),
        "paid_amount": str(row[9]),
        "outstanding": str(row[10]),
        "status": row[11],
        "supplier": {
            "id": str(row[12]),
            "code": row[13],
            "name": row[14],
        },
        "journal_entry_id": (
            str(row[15])
            if row[15]
            else None
        ),
        "lines": [
            {
                "line_number": r[0],
                "description": r[1],
                "quantity": str(r[2]),
                "unit_price": str(r[3]),
                "line_subtotal": str(r[4]),
                "tax_amount": str(r[5]),
                "posting_account": {
                    "id": str(r[6]),
                    "code": r[7],
                    "name": r[8],
                },
            }
            for r in lines
        ],
    }


@app.post(
    "/api/v1/purchases/invoices/{invoice_id}/issue"
)
def issue_purchase_invoice(invoice_id: uuid.UUID):

    try:

        with db() as con:
            with con.cursor() as cur:

                company_id = fetch_company_id(cur)

                cur.execute(
                    """
                    SELECT id
                    FROM purchase_invoices
                    WHERE id=%s
                      AND company_id=%s
                    """,
                    (
                        invoice_id,
                        company_id,
                    ),
                )

                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404,
                        detail="purchase invoice not found",
                    )

                cur.execute(
                    """
                    SELECT finance_issue_purchase_invoice(%s)
                    """,
                    (invoice_id,),
                )

                journal_id = cur.fetchone()[0]

                con.commit()

        return {
            "ok": True,
            "invoice_id": str(invoice_id),
            "journal_entry_id": str(journal_id),
            "status": "ISSUED",
        }

    except psycopg.errors.RaiseException as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc


@app.get("/api/v1/ap/outstanding")
def ap_outstanding():

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.id,
                    i.invoice_number,
                    s.code,
                    s.name,
                    i.invoice_date,
                    i.due_date,
                    i.total_amount,
                    i.paid_amount,
                    i.total_amount-i.paid_amount,
                    i.status::text
                FROM purchase_invoices i
                JOIN suppliers s
                  ON s.id=i.supplier_id
                WHERE i.company_id=%s
                  AND i.status IN (
                      'ISSUED',
                      'PARTIALLY_PAID'
                  )
                  AND i.total_amount-i.paid_amount > 0
                ORDER BY
                    i.due_date,
                    i.invoice_number
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    return {
        "payables": [
            {
                "invoice_id": str(r[0]),
                "invoice_number": r[1],
                "supplier_code": r[2],
                "supplier_name": r[3],
                "invoice_date": r[4].isoformat(),
                "due_date": r[5].isoformat(),
                "total_amount": str(r[6]),
                "paid_amount": str(r[7]),
                "outstanding": str(r[8]),
                "status": r[9],
            }
            for r in rows
        ]
    }


@app.get("/api/v1/ap/aging")
def ap_aging(as_of: Optional[date] = None):

    cutoff = as_of or date.today()

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.invoice_number,
                    s.code,
                    s.name,
                    i.due_date,
                    i.total_amount-i.paid_amount
                FROM purchase_invoices i
                JOIN suppliers s
                  ON s.id=i.supplier_id
                WHERE i.company_id=%s
                  AND i.status IN (
                      'ISSUED',
                      'PARTIALLY_PAID'
                  )
                  AND i.total_amount-i.paid_amount > 0
                ORDER BY i.due_date
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    buckets = {
        "current": Decimal("0"),
        "1_30": Decimal("0"),
        "31_60": Decimal("0"),
        "61_90": Decimal("0"),
        "over_90": Decimal("0"),
    }

    details = []

    for r in rows:

        days = (cutoff-r[3]).days
        amount = r[4]

        if days <= 0:
            bucket = "current"
        elif days <= 30:
            bucket = "1_30"
        elif days <= 60:
            bucket = "31_60"
        elif days <= 90:
            bucket = "61_90"
        else:
            bucket = "over_90"

        buckets[bucket] += amount

        details.append(
            {
                "invoice_number": r[0],
                "supplier_code": r[1],
                "supplier_name": r[2],
                "due_date": r[3].isoformat(),
                "days_overdue": max(days, 0),
                "outstanding": str(amount),
                "bucket": bucket,
            }
        )

    return {
        "as_of": cutoff.isoformat(),
        "buckets": {
            key: str(value)
            for key, value in buckets.items()
        },
        "details": details,
    }


@app.post(
    "/api/v1/ap/invoices/{invoice_id}/payments"
)
def pay_purchase_invoice(
    invoice_id: uuid.UUID,
    payload: SupplierPaymentCreate,
):

    try:

        with db() as con:
            with con.cursor() as cur:

                company_id = fetch_company_id(cur)

                cur.execute(
                    """
                    SELECT id
                    FROM purchase_invoices
                    WHERE id=%s
                      AND company_id=%s
                    """,
                    (
                        invoice_id,
                        company_id,
                    ),
                )

                if not cur.fetchone():
                    raise HTTPException(
                        status_code=404,
                        detail="purchase invoice not found",
                    )

                cur.execute(
                    """
                    SELECT finance_pay_supplier_invoice(
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        invoice_id,
                        payload.amount,
                        payload.payment_number,
                        payload.payment_date,
                        payload.cash_account_id,
                    ),
                )

                payment_id = cur.fetchone()[0]

                con.commit()

        return {
            "ok": True,
            "payment_id": str(payment_id),
            "invoice_id": str(invoice_id),
            "payment_number": payload.payment_number,
            "amount": str(payload.amount),
        }

    except psycopg.errors.RaiseException as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="supplier payment already exists",
        ) from exc


@app.get("/api/v1/ap/payments")
def list_supplier_payments():

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    sp.id,
                    sp.payment_number,
                    sp.payment_date,
                    sp.currency,
                    sp.amount,
                    sp.status::text,
                    s.id,
                    s.code,
                    s.name,
                    a.id,
                    a.code,
                    a.name
                FROM supplier_payments sp
                JOIN suppliers s
                  ON s.id=sp.supplier_id
                JOIN accounts a
                  ON a.id=sp.cash_account_id
                WHERE sp.company_id=%s
                ORDER BY
                    sp.payment_date DESC,
                    sp.payment_number DESC
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    return {
        "payments": [
            {
                "id": str(r[0]),
                "payment_number": r[1],
                "payment_date": r[2].isoformat(),
                "currency": r[3],
                "amount": str(r[4]),
                "status": r[5],
                "supplier": {
                    "id": str(r[6]),
                    "code": r[7],
                    "name": r[8],
                },
                "cash_account": {
                    "id": str(r[9]),
                    "code": r[10],
                    "name": r[11],
                },
            }
            for r in rows
        ]
    }


# ============================================================
# R6B-A — INVENTORY / PRODUCT REFERENCE API
#
# Finance Core does NOT own the commerce product catalog.
# source_system + external_product_id remain the canonical
# external identity.
# ============================================================

class InventoryItemSync(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(
        min_length=1,
        max_length=100,
    )

    external_product_id: str = Field(
        min_length=1,
        max_length=255,
    )

    sku: str | None = Field(
        default=None,
        max_length=255,
    )

    name: str = Field(
        min_length=1,
        max_length=500,
    )

    unit: str | None = Field(
        default=None,
        max_length=100,
    )

    active: bool = True


@app.post("/api/v1/inventory/items/sync")
def sync_inventory_item(payload: InventoryItemSync):

    source_system = payload.source_system.strip()
    external_id = payload.external_product_id.strip()

    if not source_system or not external_id:
        raise HTTPException(
            status_code=422,
            detail="external product identity required",
        )

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                INSERT INTO inventory_items (
                    company_id,
                    source_system,
                    external_product_id,
                    sku_snapshot,
                    name_snapshot,
                    unit_snapshot,
                    active
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT (
                    company_id,
                    source_system,
                    external_product_id
                )
                DO UPDATE SET
                    sku_snapshot=EXCLUDED.sku_snapshot,
                    name_snapshot=EXCLUDED.name_snapshot,
                    unit_snapshot=EXCLUDED.unit_snapshot,
                    active=EXCLUDED.active,
                    updated_at=now()
                RETURNING
                    id,
                    created_at,
                    updated_at
                """,
                (
                    company_id,
                    source_system,
                    external_id,
                    payload.sku,
                    payload.name,
                    payload.unit,
                    payload.active,
                ),
            )

            row = cur.fetchone()

            # Balance starts at zero only if not already present.
            cur.execute(
                """
                INSERT INTO inventory_balances (
                    company_id,
                    inventory_item_id
                )
                VALUES (%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (
                    company_id,
                    row[0],
                ),
            )

            con.commit()

    return {
        "ok": True,
        "inventory_item_id": str(row[0]),
        "source_system": source_system,
        "external_product_id": external_id,
        "sku": payload.sku,
        "name": payload.name,
        "unit": payload.unit,
        "active": payload.active,
    }


@app.get("/api/v1/inventory/items")
def list_inventory_items(
    source_system: str | None = None,
    active: bool | None = None,
):

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            conditions = ["i.company_id=%s"]
            params = [company_id]

            if source_system is not None:
                conditions.append("i.source_system=%s")
                params.append(source_system)

            if active is not None:
                conditions.append("i.active=%s")
                params.append(active)

            where = " AND ".join(conditions)

            cur.execute(
                f"""
                SELECT
                    i.id,
                    i.source_system,
                    i.external_product_id,
                    i.sku_snapshot,
                    i.name_snapshot,
                    i.unit_snapshot,
                    i.active,
                    COALESCE(b.quantity,0),
                    COALESCE(b.average_cost,0),
                    COALESCE(b.inventory_value,0)
                FROM inventory_items i
                LEFT JOIN inventory_balances b
                  ON b.company_id=i.company_id
                 AND b.inventory_item_id=i.id
                WHERE {where}
                ORDER BY
                    i.name_snapshot,
                    i.external_product_id
                """,
                params,
            )

            rows = cur.fetchall()

    return {
        "items": [
            {
                "id": str(r[0]),
                "source_system": r[1],
                "external_product_id": r[2],
                "sku": r[3],
                "name": r[4],
                "unit": r[5],
                "active": r[6],
                "quantity": str(r[7]),
                "average_cost": str(r[8]),
                "inventory_value": str(r[9]),
            }
            for r in rows
        ]
    }


@app.get("/api/v1/inventory/items/{item_id}")
def get_inventory_item(item_id: uuid.UUID):

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.id,
                    i.source_system,
                    i.external_product_id,
                    i.sku_snapshot,
                    i.name_snapshot,
                    i.unit_snapshot,
                    i.active,
                    COALESCE(b.quantity,0),
                    COALESCE(b.average_cost,0),
                    COALESCE(b.inventory_value,0),
                    i.created_at,
                    i.updated_at
                FROM inventory_items i
                LEFT JOIN inventory_balances b
                  ON b.company_id=i.company_id
                 AND b.inventory_item_id=i.id
                WHERE i.id=%s
                  AND i.company_id=%s
                """,
                (
                    item_id,
                    company_id,
                ),
            )

            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="inventory item not found",
                )

    return {
        "id": str(row[0]),
        "source_system": row[1],
        "external_product_id": row[2],
        "sku": row[3],
        "name": row[4],
        "unit": row[5],
        "active": row[6],
        "quantity": str(row[7]),
        "average_cost": str(row[8]),
        "inventory_value": str(row[9]),
        "created_at": row[10].isoformat(),
        "updated_at": row[11].isoformat(),
    }


@app.get("/api/v1/inventory/balances")
def inventory_balances():

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    i.id,
                    i.source_system,
                    i.external_product_id,
                    i.sku_snapshot,
                    i.name_snapshot,
                    i.unit_snapshot,
                    b.quantity,
                    b.average_cost,
                    b.inventory_value,
                    b.updated_at
                FROM inventory_balances b
                JOIN inventory_items i
                  ON i.id=b.inventory_item_id
                 AND i.company_id=b.company_id
                WHERE b.company_id=%s
                ORDER BY
                    i.name_snapshot,
                    i.external_product_id
                """,
                (company_id,),
            )

            rows = cur.fetchall()

    return {
        "balances": [
            {
                "inventory_item_id": str(r[0]),
                "source_system": r[1],
                "external_product_id": r[2],
                "sku": r[3],
                "name": r[4],
                "unit": r[5],
                "quantity": str(r[6]),
                "average_cost": str(r[7]),
                "inventory_value": str(r[8]),
                "updated_at": r[9].isoformat(),
            }
            for r in rows
        ]
    }


@app.get("/api/v1/inventory/movements")
def inventory_movements(
    inventory_item_id: uuid.UUID | None = None,
    limit: int = 100,
):

    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=422,
            detail="limit must be between 1 and 500",
        )

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            if inventory_item_id is None:

                cur.execute(
                    """
                    SELECT
                        m.id,
                        m.inventory_item_id,
                        i.sku_snapshot,
                        i.name_snapshot,
                        m.movement_type::text,
                        m.quantity,
                        m.unit_cost,
                        m.value_amount,
                        m.quantity_before,
                        m.quantity_after,
                        m.average_cost_before,
                        m.average_cost_after,
                        m.value_before,
                        m.value_after,
                        m.source_type,
                        m.source_id,
                        m.idempotency_key,
                        m.created_at
                    FROM inventory_movements m
                    JOIN inventory_items i
                      ON i.id=m.inventory_item_id
                     AND i.company_id=m.company_id
                    WHERE m.company_id=%s
                    ORDER BY m.created_at DESC
                    LIMIT %s
                    """,
                    (
                        company_id,
                        limit,
                    ),
                )

            else:

                cur.execute(
                    """
                    SELECT
                        m.id,
                        m.inventory_item_id,
                        i.sku_snapshot,
                        i.name_snapshot,
                        m.movement_type::text,
                        m.quantity,
                        m.unit_cost,
                        m.value_amount,
                        m.quantity_before,
                        m.quantity_after,
                        m.average_cost_before,
                        m.average_cost_after,
                        m.value_before,
                        m.value_after,
                        m.source_type,
                        m.source_id,
                        m.idempotency_key,
                        m.created_at
                    FROM inventory_movements m
                    JOIN inventory_items i
                      ON i.id=m.inventory_item_id
                     AND i.company_id=m.company_id
                    WHERE m.company_id=%s
                      AND m.inventory_item_id=%s
                    ORDER BY m.created_at DESC
                    LIMIT %s
                    """,
                    (
                        company_id,
                        inventory_item_id,
                        limit,
                    ),
                )

            rows = cur.fetchall()

    return {
        "movements": [
            {
                "id": str(r[0]),
                "inventory_item_id": str(r[1]),
                "sku": r[2],
                "name": r[3],
                "movement_type": r[4],
                "quantity": str(r[5]),
                "unit_cost": str(r[6]),
                "value_amount": str(r[7]),
                "quantity_before": str(r[8]),
                "quantity_after": str(r[9]),
                "average_cost_before": str(r[10]),
                "average_cost_after": str(r[11]),
                "value_before": str(r[12]),
                "value_after": str(r[13]),
                "source_type": r[14],
                "source_id": r[15],
                "idempotency_key": r[16],
                "created_at": r[17].isoformat(),
            }
            for r in rows
        ]
    }


@app.get("/api/v1/inventory/summary")
def inventory_summary():

    with db() as con:
        with con.cursor() as cur:

            company_id = fetch_company_id(cur)

            cur.execute(
                """
                SELECT
                    COUNT(*),
                    COUNT(*) FILTER (
                        WHERE i.active=true
                    ),
                    COUNT(*) FILTER (
                        WHERE COALESCE(b.quantity,0) > 0
                    ),
                    COALESCE(
                        SUM(
                            COALESCE(b.quantity,0)
                        ),
                        0
                    ),
                    COALESCE(
                        SUM(
                            COALESCE(b.inventory_value,0)
                        ),
                        0
                    )
                FROM inventory_items i
                LEFT JOIN inventory_balances b
                  ON b.company_id=i.company_id
                 AND b.inventory_item_id=i.id
                WHERE i.company_id=%s
                """,
                (company_id,),
            )

            row = cur.fetchone()

    return {
        "item_count": row[0],
        "active_item_count": row[1],
        "items_with_stock": row[2],
        "total_quantity": str(row[3]),
        "inventory_value": str(row[4]),
        "valuation_method": "MOVING_WEIGHTED_AVERAGE",
    }


@app.get("/api/v1/inventory/version")
def inventory_version():
    return {
        "service": "botconnector-finance-core",
        "inventory_api_version": "0.7.2-r7b",
        "valuation_method": "MOVING_WEIGHTED_AVERAGE",
    }


# ============================================================
# R6B-B — SALES / PURCHASE INVENTORY WIRING
#
# Clients use:
# source_system + external_product_id
#
# They never need Finance inventory_item_id.
# ============================================================

from decimal import Decimal
from datetime import date


class ExternalInventoryProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(
        min_length=1,
        max_length=100,
    )

    external_product_id: str = Field(
        min_length=1,
        max_length=255,
    )


class InventorySalesLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(
        min_length=1,
        max_length=100,
    )

    external_product_id: str = Field(
        min_length=1,
        max_length=255,
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)


class InventorySalesInvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_code: str = Field(
        min_length=1,
        max_length=100,
    )

    invoice_number: str = Field(
        min_length=1,
        max_length=100,
    )

    invoice_date: date
    due_date: date

    currency: str = Field(
        default="IDR",
        min_length=3,
        max_length=3,
    )

    lines: list[InventorySalesLine] = Field(
        min_length=1,
    )


class InventoryPurchaseLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str = Field(
        min_length=1,
        max_length=100,
    )

    external_product_id: str = Field(
        min_length=1,
        max_length=255,
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)


class InventoryPurchaseInvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_code: str = Field(
        min_length=1,
        max_length=100,
    )

    invoice_number: str = Field(
        min_length=1,
        max_length=100,
    )

    invoice_date: date
    due_date: date

    currency: str = Field(
        default="IDR",
        min_length=3,
        max_length=3,
    )

    lines: list[InventoryPurchaseLine] = Field(
        min_length=1,
    )


def finance_resolve_inventory_item(
    cur,
    company_id,
    source_system: str,
    external_product_id: str,
):
    source_system = source_system.strip()
    external_product_id = external_product_id.strip()

    cur.execute(
        """
        SELECT
            id,
            sku_snapshot,
            name_snapshot,
            unit_snapshot
        FROM inventory_items
        WHERE company_id=%s
          AND source_system=%s
          AND external_product_id=%s
          AND active=true
        """,
        (
            company_id,
            source_system,
            external_product_id,
        ),
    )

    row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=409,
            detail=(
                "inventory product reference not found: "
                + source_system
                + "/"
                + external_product_id
            ),
        )

    return row


@app.post("/api/v1/inventory/purchase-invoices")
def create_inventory_purchase_invoice(
    payload: InventoryPurchaseInvoiceCreate,
):
    with db() as con:
        try:
            with con.cursor() as cur:

                company_id = fetch_company_id(cur)

                cur.execute(
                    """
                    SELECT id
                    FROM suppliers
                    WHERE company_id=%s
                      AND code=%s
                      AND active=true
                    """,
                    (
                        company_id,
                        payload.supplier_code,
                    ),
                )

                supplier = cur.fetchone()

                if not supplier:
                    raise HTTPException(
                        status_code=404,
                        detail="supplier not found",
                    )

                cur.execute(
                    """
                    SELECT id
                    FROM accounts
                    WHERE company_id=%s
                      AND system_key='INVENTORY'
                      AND active=true
                    """,
                    (company_id,),
                )

                inventory_account = cur.fetchone()

                if not inventory_account:
                    raise HTTPException(
                        status_code=409,
                        detail="inventory account unavailable",
                    )

                resolved = []

                subtotal = Decimal("0")
                tax_total = Decimal("0")

                for line in payload.lines:

                    item = finance_resolve_inventory_item(
                        cur,
                        company_id,
                        line.source_system,
                        line.external_product_id,
                    )

                    line_subtotal = (
                        line.quantity * line.unit_price
                    ).quantize(Decimal("0.01"))

                    subtotal += line_subtotal
                    tax_total += line.tax_amount

                    resolved.append(
                        (
                            line,
                            item,
                            line_subtotal,
                        )
                    )

                total = subtotal + tax_total

                cur.execute(
                    """
                    INSERT INTO purchase_invoices (
                        company_id,
                        supplier_id,
                        invoice_number,
                        invoice_date,
                        due_date,
                        currency,
                        subtotal,
                        tax_amount,
                        total_amount,
                        source_system,
                        source_id
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,
                        %s,%s,%s,
                        'finance_core',
                        %s
                    )
                    RETURNING id
                    """,
                    (
                        company_id,
                        supplier[0],
                        payload.invoice_number,
                        payload.invoice_date,
                        payload.due_date,
                        payload.currency.upper(),
                        subtotal,
                        tax_total,
                        total,
                        "inventory-api:"
                        + payload.invoice_number,
                    ),
                )

                invoice_id = cur.fetchone()[0]

                for line_no, data in enumerate(
                    resolved,
                    start=1,
                ):
                    line, item, line_subtotal = data

                    description = (
                        line.description
                        or item[2]
                        or line.external_product_id
                    )

                    cur.execute(
                        """
                        INSERT INTO purchase_invoice_lines (
                            purchase_invoice_id,
                            line_number,
                            description,
                            quantity,
                            unit_price,
                            line_subtotal,
                            tax_amount,
                            posting_account_id,
                            inventory_item_id
                        )
                        VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s,%s
                        )
                        """,
                        (
                            invoice_id,
                            line_no,
                            description,
                            line.quantity,
                            line.unit_price,
                            line_subtotal,
                            line.tax_amount,
                            inventory_account[0],
                            item[0],
                        ),
                    )

                con.commit()

                return {
                    "ok": True,
                    "invoice_id": str(invoice_id),
                    "invoice_number": payload.invoice_number,
                    "subtotal": str(subtotal),
                    "tax_amount": str(tax_total),
                    "total_amount": str(total),
                    "status": "DRAFT",
                    "inventory_lines": len(resolved),
                }

        except HTTPException:
            con.rollback()
            raise
        except Exception as exc:
            con.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )


@app.post(
    "/api/v1/inventory/purchase-invoices/{invoice_id}/issue"
)
def issue_inventory_purchase_invoice(
    invoice_id: uuid.UUID,
):
    with db() as con:
        try:
            with con.cursor() as cur:

                company_id = fetch_company_id(cur)

                cur.execute(
                    """
                    SELECT
                        id,
                        invoice_number,
                        status::text
                    FROM purchase_invoices
                    WHERE id=%s
                      AND company_id=%s
                    FOR UPDATE
                    """,
                    (
                        invoice_id,
                        company_id,
                    ),
                )

                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="purchase invoice not found",
                    )

                if row[2] != "DRAFT":
                    raise HTTPException(
                        status_code=409,
                        detail="only DRAFT invoice can be issued",
                    )

                cur.execute(
                    """
                    SELECT finance_issue_purchase_invoice(%s)
                    """,
                    (invoice_id,),
                )

                journal_id = cur.fetchone()[0]

                con.commit()

                return {
                    "ok": True,
                    "invoice_id": str(invoice_id),
                    "invoice_number": row[1],
                    "journal_entry_id": str(journal_id),
                    "status": "ISSUED",
                }

        except HTTPException:
            con.rollback()
            raise
        except Exception as exc:
            con.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )


@app.post("/api/v1/inventory/sales-invoices")
def create_inventory_sales_invoice(
    payload: InventorySalesInvoiceCreate,
):
    with db() as con:
        try:
            with con.cursor() as cur:

                company_id = fetch_company_id(cur)

                cur.execute(
                    """
                    SELECT id
                    FROM customers
                    WHERE company_id=%s
                      AND code=%s
                      AND active=true
                    """,
                    (
                        company_id,
                        payload.customer_code,
                    ),
                )

                customer = cur.fetchone()

                if not customer:
                    raise HTTPException(
                        status_code=404,
                        detail="customer not found",
                    )

                cur.execute(
                    """
                    SELECT id
                    FROM accounts
                    WHERE company_id=%s
                      AND system_key='SALES_REVENUE'
                      AND active=true
                    """,
                    (company_id,),
                )

                revenue_account = cur.fetchone()

                if not revenue_account:
                    raise HTTPException(
                        status_code=409,
                        detail="sales revenue account unavailable",
                    )

                resolved = []

                subtotal = Decimal("0")
                tax_total = Decimal("0")

                for line in payload.lines:

                    item = finance_resolve_inventory_item(
                        cur,
                        company_id,
                        line.source_system,
                        line.external_product_id,
                    )

                    line_subtotal = (
                        line.quantity * line.unit_price
                    ).quantize(Decimal("0.01"))

                    subtotal += line_subtotal
                    tax_total += line.tax_amount

                    resolved.append(
                        (
                            line,
                            item,
                            line_subtotal,
                        )
                    )

                total = subtotal + tax_total

                cur.execute(
                    """
                    INSERT INTO sales_invoices (
                        company_id,
                        customer_id,
                        invoice_number,
                        invoice_date,
                        due_date,
                        currency,
                        subtotal,
                        tax_amount,
                        total_amount,
                        source_system,
                        source_id
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,
                        %s,%s,%s,
                        'finance_core',
                        %s
                    )
                    RETURNING id
                    """,
                    (
                        company_id,
                        customer[0],
                        payload.invoice_number,
                        payload.invoice_date,
                        payload.due_date,
                        payload.currency.upper(),
                        subtotal,
                        tax_total,
                        total,
                        "inventory-api:"
                        + payload.invoice_number,
                    ),
                )

                invoice_id = cur.fetchone()[0]

                for line_no, data in enumerate(
                    resolved,
                    start=1,
                ):
                    line, item, line_subtotal = data

                    description = (
                        line.description
                        or item[2]
                        or line.external_product_id
                    )

                    cur.execute(
                        """
                        INSERT INTO sales_invoice_lines (
                            sales_invoice_id,
                            line_number,
                            description,
                            quantity,
                            unit_price,
                            line_subtotal,
                            tax_amount,
                            revenue_account_id,
                            inventory_item_id
                        )
                        VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s,%s
                        )
                        """,
                        (
                            invoice_id,
                            line_no,
                            description,
                            line.quantity,
                            line.unit_price,
                            line_subtotal,
                            line.tax_amount,
                            revenue_account[0],
                            item[0],
                        ),
                    )

                con.commit()

                return {
                    "ok": True,
                    "invoice_id": str(invoice_id),
                    "invoice_number": payload.invoice_number,
                    "subtotal": str(subtotal),
                    "tax_amount": str(tax_total),
                    "total_amount": str(total),
                    "status": "DRAFT",
                    "inventory_lines": len(resolved),
                }

        except HTTPException:
            con.rollback()
            raise
        except Exception as exc:
            con.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )


@app.post(
    "/api/v1/inventory/sales-invoices/{invoice_id}/issue"
)
def issue_inventory_sales_invoice(
    invoice_id: uuid.UUID,
):
    with db() as con:
        try:
            with con.cursor() as cur:

                company_id = fetch_company_id(cur)

                cur.execute(
                    """
                    SELECT
                        id,
                        invoice_number,
                        status::text
                    FROM sales_invoices
                    WHERE id=%s
                      AND company_id=%s
                    FOR UPDATE
                    """,
                    (
                        invoice_id,
                        company_id,
                    ),
                )

                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="sales invoice not found",
                    )

                if row[2] != "DRAFT":
                    raise HTTPException(
                        status_code=409,
                        detail="only DRAFT invoice can be issued",
                    )

                cur.execute(
                    """
                    SELECT finance_issue_sales_invoice(%s)
                    """,
                    (invoice_id,),
                )

                journal_id = cur.fetchone()[0]

                con.commit()

                return {
                    "ok": True,
                    "invoice_id": str(invoice_id),
                    "invoice_number": row[1],
                    "journal_entry_id": str(journal_id),
                    "status": "ISSUED",
                }

        except HTTPException:
            con.rollback()
            raise
        except Exception as exc:
            con.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )


@app.get("/api/v1/inventory/invoice-wiring/version")
def inventory_invoice_wiring_version():
    return {
        "service": "botconnector-finance-core",
        "version": "0.7.2-r7b",
        "product_resolution": (
            "source_system+external_product_id"
        ),
        "inventory_item_id_required_from_client": False,
    }

# ============================================================
# R7B BANK + CASH INTERNAL API
# ============================================================

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field
from psycopg.rows import dict_row


def r7b_db():
    """
    R7B-local database connection.

    Existing Finance Core APIs intentionally keep the historical
    tuple-row contract from db(). R7B uses mapping rows only inside
    its own API block so R4/R5/R6 behavior is unchanged.
    """
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        row_factory=dict_row,
    )


class CashBankAccountCreate(BaseModel):
    code: str
    name: str
    account_kind: str
    gl_account_code: str
    currency: str = "IDR"
    bank_name: Optional[str] = None
    account_number_masked: Optional[str] = None


class CashTransactionCreate(BaseModel):
    cash_bank_account_id: str
    transaction_type: str
    counter_account_code: str
    amount: Decimal = Field(gt=0)
    reference: str
    description: Optional[str] = None
    idempotency_key: str
    transaction_date: date


class BankTransferCreate(BaseModel):
    from_account_id: str
    to_account_id: str
    amount: Decimal = Field(gt=0)
    reference: str
    description: Optional[str] = None
    idempotency_key: str
    transfer_date: date


class StatementImportCreate(BaseModel):
    cash_bank_account_id: str
    statement_reference: str
    period_start: date
    period_end: date
    opening_balance: Optional[Decimal] = None
    closing_balance: Optional[Decimal] = None
    idempotency_key: str


class StatementLineCreate(BaseModel):
    line_number: int = Field(gt=0)
    transaction_date: date
    direction: str
    amount: Decimal = Field(gt=0)
    external_reference: Optional[str] = None
    description: Optional[str] = None


class ReconciliationCreate(BaseModel):
    source_type: str
    source_id: str
    note: Optional[str] = None


@app.get("/api/v1/bank/accounts")
def r7b_list_accounts():
    with r7b_db() as conn:
        rows = conn.execute("""
            SELECT
              c.id,
              c.code,
              c.name,
              c.account_kind,
              c.currency,
              c.bank_name,
              c.account_number_masked,
              c.active,
              a.code AS gl_account_code,
              a.name AS gl_account_name
            FROM cash_bank_accounts c
            JOIN accounts a
              ON a.id=c.gl_account_id
            ORDER BY c.code
        """).fetchall()

        return {
            "accounts": [
                {
                    "id": str(r["id"]),
                    "code": r["code"],
                    "name": r["name"],
                    "account_kind": r["account_kind"],
                    "currency": r["currency"],
                    "bank_name": r["bank_name"],
                    "account_number_masked":
                        r["account_number_masked"],
                    "active": r["active"],
                    "gl_account_code":
                        r["gl_account_code"],
                    "gl_account_name":
                        r["gl_account_name"],
                }
                for r in rows
            ]
        }


@app.post("/api/v1/bank/accounts")
def r7b_create_account(payload: CashBankAccountCreate):
    kind = payload.account_kind.upper()

    if kind not in ("CASH", "BANK"):
        raise HTTPException(
            status_code=400,
            detail="account_kind must be CASH or BANK",
        )

    with r7b_db() as conn:
        company = conn.execute("""
            SELECT id
            FROM companies
            ORDER BY created_at
            LIMIT 1
        """).fetchone()

        if not company:
            raise HTTPException(
                status_code=409,
                detail="company unavailable",
            )

        gl = conn.execute("""
            SELECT id,system_key
            FROM accounts
            WHERE company_id=%s
              AND code=%s
              AND active=true
            LIMIT 1
        """, (
            company["id"],
            payload.gl_account_code,
        )).fetchone()

        if not gl:
            raise HTTPException(
                status_code=409,
                detail="GL account unavailable",
            )

        expected = (
            "BANK"
            if kind == "BANK"
            else "CASH"
        )

        if gl["system_key"] != expected:
            raise HTTPException(
                status_code=409,
                detail="GL account system key mismatch",
            )

        try:
            row = conn.execute("""
                INSERT INTO cash_bank_accounts (
                  company_id,
                  code,
                  name,
                  account_kind,
                  gl_account_id,
                  currency,
                  bank_name,
                  account_number_masked
                )
                VALUES (
                  %s,%s,%s,%s,%s,%s,%s,%s
                )
                RETURNING id
            """, (
                company["id"],
                payload.code,
                payload.name,
                kind,
                gl["id"],
                payload.currency,
                payload.bank_name,
                payload.account_number_masked,
            )).fetchone()

            conn.commit()

        except Exception as exc:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )

        return {
            "ok": True,
            "id": str(row["id"]),
            "code": payload.code,
        }


@app.post("/api/v1/bank/transactions")
def r7b_post_transaction(
    payload: CashTransactionCreate
):
    with r7b_db() as conn:
        counter = conn.execute("""
            SELECT id
            FROM accounts
            WHERE code=%s
              AND active=true
            ORDER BY created_at
            LIMIT 1
        """, (
            payload.counter_account_code,
        )).fetchone()

        if not counter:
            raise HTTPException(
                status_code=409,
                detail="counter account unavailable",
            )

        try:
            row = conn.execute("""
                SELECT finance_cash_transaction_post(
                  %s::uuid,
                  %s,
                  %s::uuid,
                  %s,
                  %s,
                  %s,
                  %s,
                  %s
                ) AS id
            """, (
                payload.cash_bank_account_id,
                payload.transaction_type.upper(),
                counter["id"],
                payload.amount,
                payload.reference,
                payload.description,
                payload.idempotency_key,
                payload.transaction_date,
            )).fetchone()

            conn.commit()

        except Exception as exc:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )

        return {
            "ok": True,
            "id": str(row["id"]),
        }


@app.get("/api/v1/bank/transactions")
def r7b_list_transactions():
    with r7b_db() as conn:
        rows = conn.execute("""
            SELECT
              t.id,
              t.transaction_number,
              t.transaction_date,
              t.transaction_type,
              t.amount,
              t.currency,
              t.description,
              t.status,
              c.code AS cash_bank_code,
              c.name AS cash_bank_name,
              a.code AS counter_account_code,
              a.name AS counter_account_name
            FROM cash_transactions t
            JOIN cash_bank_accounts c
              ON c.id=t.cash_bank_account_id
            JOIN accounts a
              ON a.id=t.counter_account_id
            ORDER BY t.transaction_date DESC,
                     t.created_at DESC
        """).fetchall()

        return {
            "transactions": [
                {
                    "id": str(r["id"]),
                    "transaction_number":
                        r["transaction_number"],
                    "transaction_date":
                        str(r["transaction_date"]),
                    "transaction_type":
                        r["transaction_type"],
                    "amount": str(r["amount"]),
                    "currency": r["currency"],
                    "description": r["description"],
                    "status": r["status"],
                    "cash_bank_code":
                        r["cash_bank_code"],
                    "cash_bank_name":
                        r["cash_bank_name"],
                    "counter_account_code":
                        r["counter_account_code"],
                    "counter_account_name":
                        r["counter_account_name"],
                }
                for r in rows
            ]
        }


@app.post("/api/v1/bank/transfers")
def r7b_post_transfer(
    payload: BankTransferCreate
):
    with r7b_db() as conn:
        try:
            row = conn.execute("""
                SELECT finance_bank_transfer_post(
                  %s::uuid,
                  %s::uuid,
                  %s,
                  %s,
                  %s,
                  %s,
                  %s
                ) AS id
            """, (
                payload.from_account_id,
                payload.to_account_id,
                payload.amount,
                payload.reference,
                payload.description,
                payload.idempotency_key,
                payload.transfer_date,
            )).fetchone()

            conn.commit()

        except Exception as exc:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )

        return {
            "ok": True,
            "id": str(row["id"]),
        }


@app.get("/api/v1/bank/transfers")
def r7b_list_transfers():
    with r7b_db() as conn:
        rows = conn.execute("""
            SELECT
              t.id,
              t.transfer_number,
              t.transfer_date,
              t.amount,
              t.currency,
              t.status,
              f.code AS from_code,
              f.name AS from_name,
              d.code AS to_code,
              d.name AS to_name
            FROM bank_transfers t
            JOIN cash_bank_accounts f
              ON f.id=t.from_account_id
            JOIN cash_bank_accounts d
              ON d.id=t.to_account_id
            ORDER BY t.transfer_date DESC,
                     t.created_at DESC
        """).fetchall()

        return {
            "transfers": [
                {
                    "id": str(r["id"]),
                    "transfer_number":
                        r["transfer_number"],
                    "transfer_date":
                        str(r["transfer_date"]),
                    "amount": str(r["amount"]),
                    "currency": r["currency"],
                    "status": r["status"],
                    "from_code": r["from_code"],
                    "from_name": r["from_name"],
                    "to_code": r["to_code"],
                    "to_name": r["to_name"],
                }
                for r in rows
            ]
        }


@app.post("/api/v1/bank/statements")
def r7b_import_statement(
    payload: StatementImportCreate
):
    with r7b_db() as conn:
        try:
            row = conn.execute("""
                SELECT finance_bank_statement_import(
                  %s::uuid,
                  %s,
                  %s,
                  %s,
                  %s,
                  %s,
                  %s
                ) AS id
            """, (
                payload.cash_bank_account_id,
                payload.statement_reference,
                payload.period_start,
                payload.period_end,
                payload.opening_balance,
                payload.closing_balance,
                payload.idempotency_key,
            )).fetchone()

            conn.commit()

        except Exception as exc:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )

        return {
            "ok": True,
            "id": str(row["id"]),
        }


@app.post(
    "/api/v1/bank/statements/{statement_id}/lines"
)
def r7b_add_statement_line(
    statement_id: str,
    payload: StatementLineCreate,
):
    with r7b_db() as conn:
        try:
            row = conn.execute("""
                SELECT finance_bank_statement_add_line(
                  %s::uuid,
                  %s,
                  %s,
                  %s,
                  %s,
                  %s,
                  %s
                ) AS id
            """, (
                statement_id,
                payload.line_number,
                payload.transaction_date,
                payload.direction.upper(),
                payload.amount,
                payload.external_reference,
                payload.description,
            )).fetchone()

            conn.commit()

        except Exception as exc:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )

        return {
            "ok": True,
            "id": str(row["id"]),
        }


@app.get("/api/v1/bank/reconciliation/outstanding")
def r7b_outstanding():
    with r7b_db() as conn:
        rows = conn.execute("""
            SELECT
              statement_line_id,
              account_code,
              account_name,
              statement_reference,
              line_number,
              transaction_date,
              direction,
              amount,
              external_reference,
              description
            FROM bank_statement_outstanding
            ORDER BY transaction_date,line_number
        """).fetchall()

        return {
            "outstanding": [
                {
                    "statement_line_id":
                        str(r["statement_line_id"]),
                    "account_code":
                        r["account_code"],
                    "account_name":
                        r["account_name"],
                    "statement_reference":
                        r["statement_reference"],
                    "line_number":
                        r["line_number"],
                    "transaction_date":
                        str(r["transaction_date"]),
                    "direction":
                        r["direction"],
                    "amount":
                        str(r["amount"]),
                    "external_reference":
                        r["external_reference"],
                    "description":
                        r["description"],
                }
                for r in rows
            ]
        }


@app.post(
    "/api/v1/bank/reconciliation/{statement_line_id}/match"
)
def r7b_match(
    statement_line_id: str,
    payload: ReconciliationCreate,
):
    with r7b_db() as conn:
        try:
            row = conn.execute("""
                SELECT finance_bank_statement_match(
                  %s::uuid,
                  %s,
                  %s::uuid,
                  %s
                ) AS id
            """, (
                statement_line_id,
                payload.source_type.upper(),
                payload.source_id,
                payload.note,
            )).fetchone()

            conn.commit()

        except Exception as exc:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            )

        return {
            "ok": True,
            "id": str(row["id"]),
        }


@app.get("/api/v1/bank/summary")
def r7b_summary():
    with r7b_db() as conn:
        rows = conn.execute("""
            SELECT
              c.id,
              c.code,
              c.name,
              c.account_kind,
              c.currency,
              a.code AS gl_account_code,
              COALESCE(
                SUM(
                  CASE
                    WHEN j.status IN ('POSTED','REVERSED')
                      THEN l.debit-l.credit
                    ELSE 0
                  END
                ),
                0
              ) AS gl_balance
            FROM cash_bank_accounts c
            JOIN accounts a
              ON a.id=c.gl_account_id
            LEFT JOIN journal_lines l
              ON l.account_id=c.gl_account_id
            LEFT JOIN journal_entries j
              ON j.id=l.journal_entry_id
            WHERE c.active=true
            GROUP BY
              c.id,
              c.code,
              c.name,
              c.account_kind,
              c.currency,
              a.code
            ORDER BY c.code
        """).fetchall()

        return {
            "accounts": [
                {
                    "id": str(r["id"]),
                    "code": r["code"],
                    "name": r["name"],
                    "account_kind":
                        r["account_kind"],
                    "currency":
                        r["currency"],
                    "gl_account_code":
                        r["gl_account_code"],
                    "gl_balance":
                        str(r["gl_balance"]),
                }
                for r in rows
            ]
        }

# ============================================================
# BOTCONNECTOR FINANCE CORE R8-R1
# REPORTING CONTRACT
# READ-ONLY REPORTING DATABASE CONNECTION
# ============================================================

import os as _r8_os
from datetime import date as _r8_date
from decimal import Decimal as _R8Decimal

import psycopg as _r8_psycopg
from psycopg.rows import dict_row as _r8_dict_row
from fastapi import HTTPException as _R8HTTPException


_R8_ZERO = _R8Decimal("0")


def _r8_money(value):
    if value is None:
        value = _R8_ZERO

    if not isinstance(value, _R8Decimal):
        value = _R8Decimal(str(value))

    return format(value.quantize(_R8Decimal("0.01")), "f")


def _r8_db():
    """
    Dedicated reporting connection.

    default_transaction_read_only=on prevents this R8 reporting
    layer from mutating Finance Core accounting state.
    """
    return _r8_psycopg.connect(
        host=_r8_os.environ["FINANCE_DB_HOST"],
        port=int(_r8_os.environ.get("FINANCE_DB_PORT", "5432")),
        dbname=_r8_os.environ["FINANCE_DB_NAME"],
        user=_r8_os.environ["FINANCE_DB_USER"],
        password=_r8_os.environ["FINANCE_DB_PASSWORD"],
        row_factory=_r8_dict_row,
        options="-c default_transaction_read_only=on",
    )


def _r8_company(conn):
    row = conn.execute(
        """
        SELECT id, name
        FROM companies
        ORDER BY created_at, id
        LIMIT 1
        """
    ).fetchone()

    if not row:
        raise _R8HTTPException(
            status_code=404,
            detail="finance company not found",
        )

    return row


def _r8_normalized(account_type, debit, credit):
    debit = _R8Decimal(str(debit or 0))
    credit = _R8Decimal(str(credit or 0))

    if account_type in ("LIABILITY", "EQUITY", "REVENUE"):
        return credit - debit

    return debit - credit


@app.get("/api/v1/reports/version")
def r8_reporting_version():
    return {
        "service": "botconnector-finance-core",
        "reporting_version": "0.8.1-r8-r1",
        "contract": "reporting-v1",
        "database_mode": "read-only",
        "current_earnings_mode": "virtual-before-close",
        "reports": [
            "trial-balance",
            "general-ledger",
            "profit-loss",
            "balance-sheet",
        ],
    }


@app.get("/api/v1/reports/trial-balance")
def r8_trial_balance(as_of: _r8_date | None = None):
    if as_of is None:
        as_of = _r8_date.today()

    try:
        with _r8_db() as conn:
            company = _r8_company(conn)

            rows = conn.execute(
                """
                SELECT
                    a.code,
                    a.name,
                    a.type::text AS type,
                    a.normal_balance::text AS normal_balance,

                    COALESCE(
                        SUM(jl.debit)
                        FILTER (
                            WHERE je.status = 'POSTED'
                              AND je.journal_date <= %s
                        ),
                        0
                    ) AS total_debit,

                    COALESCE(
                        SUM(jl.credit)
                        FILTER (
                            WHERE je.status = 'POSTED'
                              AND je.journal_date <= %s
                        ),
                        0
                    ) AS total_credit

                FROM accounts a

                LEFT JOIN journal_lines jl
                  ON jl.account_id = a.id

                LEFT JOIN journal_entries je
                  ON je.id = jl.journal_entry_id
                 AND je.company_id = %s

                WHERE a.company_id = %s
                  AND a.active = true

                GROUP BY
                    a.id,
                    a.code,
                    a.name,
                    a.type,
                    a.normal_balance

                ORDER BY a.code
                """,
                (
                    as_of,
                    as_of,
                    company["id"],
                    company["id"],
                ),
            ).fetchall()

            accounts = []

            total_debit = _R8_ZERO
            total_credit = _R8_ZERO

            for row in rows:
                debit = _R8Decimal(str(row["total_debit"]))
                credit = _R8Decimal(str(row["total_credit"]))

                total_debit += debit
                total_credit += credit

                signed = debit - credit

                accounts.append(
                    {
                        "code": row["code"],
                        "name": row["name"],
                        "type": row["type"],
                        "normal_balance": row["normal_balance"],
                        "debit": _r8_money(debit),
                        "credit": _r8_money(credit),
                        "debit_minus_credit": _r8_money(signed),
                    }
                )

            difference = total_debit - total_credit

            return {
                "company_id": str(company["id"]),
                "company_name": company["name"],
                "as_of": as_of.isoformat(),
                "posted_only": True,
                "accounts": accounts,
                "totals": {
                    "debit": _r8_money(total_debit),
                    "credit": _r8_money(total_credit),
                    "difference": _r8_money(difference),
                },
                "balanced": difference == _R8_ZERO,
            }

    except _R8HTTPException:
        raise

    except Exception as exc:
        raise _R8HTTPException(
            status_code=503,
            detail="reporting database unavailable",
        ) from exc


@app.get("/api/v1/reports/general-ledger")
def r8_general_ledger(
    account_code: str | None = None,
    date_from: _r8_date | None = None,
    date_to: _r8_date | None = None,
):
    if date_to is None:
        date_to = _r8_date.today()

    if date_from is None:
        date_from = _r8_date(1900, 1, 1)

    if date_from > date_to:
        raise _R8HTTPException(
            status_code=422,
            detail="date_from must be <= date_to",
        )

    try:
        with _r8_db() as conn:
            company = _r8_company(conn)

            params = [
                company["id"],
                date_from,
                company["id"],
                date_from,
                date_to,
            ]

            account_filter = ""

            if account_code:
                account_filter = " AND a.code = %s "
                params.append(account_code)

            rows = conn.execute(
                f"""
                WITH opening AS (
                    SELECT
                        jl.account_id,
                        COALESCE(SUM(jl.debit - jl.credit), 0)
                            AS opening_signed
                    FROM journal_lines jl
                    JOIN journal_entries je
                      ON je.id = jl.journal_entry_id
                    WHERE je.company_id = %s
                      AND je.status = 'POSTED'
                      AND je.journal_date < %s
                    GROUP BY jl.account_id
                ),

                activity AS (
                    SELECT
                        je.id AS journal_entry_id,
                        je.journal_number,
                        je.journal_date,
                        je.description AS journal_description,
                        je.source_type,
                        je.source_id,

                        jl.line_number,
                        jl.account_id,
                        jl.description AS line_description,
                        jl.debit,
                        jl.credit,

                        SUM(jl.debit - jl.credit)
                        OVER (
                            PARTITION BY jl.account_id
                            ORDER BY
                                je.journal_date,
                                je.created_at,
                                je.id,
                                jl.line_number
                            ROWS UNBOUNDED PRECEDING
                        ) AS activity_running

                    FROM journal_entries je

                    JOIN journal_lines jl
                      ON jl.journal_entry_id = je.id

                    WHERE je.company_id = %s
                      AND je.status = 'POSTED'
                      AND je.journal_date BETWEEN %s AND %s
                )

                SELECT
                    a.code AS account_code,
                    a.name AS account_name,
                    a.type::text AS account_type,
                    a.normal_balance::text AS normal_balance,

                    COALESCE(o.opening_signed, 0)
                        AS opening_signed,

                    ac.journal_entry_id,
                    ac.journal_number,
                    ac.journal_date,
                    ac.journal_description,
                    ac.source_type,
                    ac.source_id,
                    ac.line_number,
                    ac.line_description,
                    ac.debit,
                    ac.credit,

                    COALESCE(o.opening_signed, 0)
                      + ac.activity_running
                        AS running_signed

                FROM activity ac

                JOIN accounts a
                  ON a.id = ac.account_id

                LEFT JOIN opening o
                  ON o.account_id = ac.account_id

                WHERE a.company_id = %s
                  {account_filter}

                ORDER BY
                    a.code,
                    ac.journal_date,
                    ac.journal_entry_id,
                    ac.line_number
                """,
                [
                    params[0],
                    params[1],
                    params[2],
                    params[3],
                    params[4],
                    company["id"],
                    *(
                        [account_code]
                        if account_code
                        else []
                    ),
                ],
            ).fetchall()

            entries = []

            for row in rows:
                entries.append(
                    {
                        "account_code": row["account_code"],
                        "account_name": row["account_name"],
                        "account_type": row["account_type"],
                        "normal_balance": row["normal_balance"],
                        "opening_signed": _r8_money(
                            row["opening_signed"]
                        ),
                        "journal_entry_id": str(
                            row["journal_entry_id"]
                        ),
                        "journal_number": row["journal_number"],
                        "journal_date": row[
                            "journal_date"
                        ].isoformat(),
                        "description":
                            row["line_description"]
                            or row["journal_description"],
                        "source_type": row["source_type"],
                        "source_id": row["source_id"],
                        "line_number": row["line_number"],
                        "debit": _r8_money(row["debit"]),
                        "credit": _r8_money(row["credit"]),
                        "running_signed": _r8_money(
                            row["running_signed"]
                        ),
                    }
                )

            return {
                "company_id": str(company["id"]),
                "company_name": company["name"],
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "account_code": account_code,
                "posted_only": True,
                "entries": entries,
            }

    except _R8HTTPException:
        raise

    except Exception as exc:
        raise _R8HTTPException(
            status_code=503,
            detail="reporting database unavailable",
        ) from exc


@app.get("/api/v1/reports/profit-loss")
def r8_profit_loss(
    date_from: _r8_date | None = None,
    date_to: _r8_date | None = None,
):
    if date_to is None:
        date_to = _r8_date.today()

    if date_from is None:
        date_from = _r8_date(date_to.year, 1, 1)

    if date_from > date_to:
        raise _R8HTTPException(
            status_code=422,
            detail="date_from must be <= date_to",
        )

    try:
        with _r8_db() as conn:
            company = _r8_company(conn)

            rows = conn.execute(
                """
                SELECT
                    a.code,
                    a.name,
                    a.type::text AS type,
                    a.normal_balance::text AS normal_balance,
                    COALESCE(
                        SUM(jl.debit)
                        FILTER (WHERE je.id IS NOT NULL),
                        0
                    ) AS debit,
                    COALESCE(
                        SUM(jl.credit)
                        FILTER (WHERE je.id IS NOT NULL),
                        0
                    ) AS credit

                FROM accounts a

                LEFT JOIN journal_lines jl
                  ON jl.account_id = a.id

                LEFT JOIN journal_entries je
                  ON je.id = jl.journal_entry_id
                 AND je.company_id = %s
                 AND je.status = 'POSTED'
                 AND je.journal_date BETWEEN %s AND %s

                WHERE a.company_id = %s
                  AND a.active = true
                  AND a.type IN ('REVENUE','EXPENSE')

                GROUP BY
                    a.id,
                    a.code,
                    a.name,
                    a.type,
                    a.normal_balance

                ORDER BY a.code
                """,
                (
                    company["id"],
                    date_from,
                    date_to,
                    company["id"],
                ),
            ).fetchall()

            revenue = []
            expenses = []

            total_revenue = _R8_ZERO
            total_expenses = _R8_ZERO

            for row in rows:
                balance = _r8_normalized(
                    row["type"],
                    row["debit"],
                    row["credit"],
                )

                item = {
                    "code": row["code"],
                    "name": row["name"],
                    "balance": _r8_money(balance),
                }

                if row["type"] == "REVENUE":
                    revenue.append(item)
                    total_revenue += balance
                else:
                    expenses.append(item)
                    total_expenses += balance

            net_income = total_revenue - total_expenses

            return {
                "company_id": str(company["id"]),
                "company_name": company["name"],
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "posted_only": True,
                "revenue": revenue,
                "expenses": expenses,
                "totals": {
                    "revenue": _r8_money(total_revenue),
                    "expenses": _r8_money(total_expenses),
                    "net_income": _r8_money(net_income),
                },
            }

    except _R8HTTPException:
        raise

    except Exception as exc:
        raise _R8HTTPException(
            status_code=503,
            detail="reporting database unavailable",
        ) from exc


@app.get("/api/v1/reports/balance-sheet")
def r8_balance_sheet(as_of: _r8_date | None = None):
    if as_of is None:
        as_of = _r8_date.today()

    try:
        with _r8_db() as conn:
            company = _r8_company(conn)

            rows = conn.execute(
                """
                SELECT
                    a.code,
                    a.name,
                    a.type::text AS type,
                    a.normal_balance::text AS normal_balance,

                    COALESCE(
                        SUM(jl.debit)
                        FILTER (
                            WHERE je.status='POSTED'
                              AND je.journal_date <= %s
                        ),
                        0
                    ) AS debit,

                    COALESCE(
                        SUM(jl.credit)
                        FILTER (
                            WHERE je.status='POSTED'
                              AND je.journal_date <= %s
                        ),
                        0
                    ) AS credit

                FROM accounts a

                LEFT JOIN journal_lines jl
                  ON jl.account_id = a.id

                LEFT JOIN journal_entries je
                  ON je.id = jl.journal_entry_id
                 AND je.company_id = %s

                WHERE a.company_id = %s
                  AND a.active = true

                GROUP BY
                    a.id,
                    a.code,
                    a.name,
                    a.type,
                    a.normal_balance

                ORDER BY a.code
                """,
                (
                    as_of,
                    as_of,
                    company["id"],
                    company["id"],
                ),
            ).fetchall()

            assets = []
            liabilities = []
            equity = []

            total_assets = _R8_ZERO
            total_liabilities = _R8_ZERO
            posted_equity = _R8_ZERO

            total_revenue = _R8_ZERO
            total_expenses = _R8_ZERO

            for row in rows:
                account_type = row["type"]

                balance = _r8_normalized(
                    account_type,
                    row["debit"],
                    row["credit"],
                )

                item = {
                    "code": row["code"],
                    "name": row["name"],
                    "balance": _r8_money(balance),
                }

                if account_type == "ASSET":
                    assets.append(item)
                    total_assets += balance

                elif account_type == "LIABILITY":
                    liabilities.append(item)
                    total_liabilities += balance

                elif account_type == "EQUITY":
                    equity.append(item)
                    posted_equity += balance

                elif account_type == "REVENUE":
                    total_revenue += balance

                elif account_type == "EXPENSE":
                    total_expenses += balance

            current_earnings = total_revenue - total_expenses

            total_equity_with_current_earnings = (
                posted_equity + current_earnings
            )

            rhs = (
                total_liabilities
                + total_equity_with_current_earnings
            )

            difference = total_assets - rhs

            return {
                "company_id": str(company["id"]),
                "company_name": company["name"],
                "as_of": as_of.isoformat(),
                "posted_only": True,

                "assets": assets,
                "liabilities": liabilities,
                "equity": equity,

                "current_earnings": {
                    "mode": "virtual-before-close",
                    "revenue": _r8_money(total_revenue),
                    "expenses": _r8_money(total_expenses),
                    "net_income": _r8_money(current_earnings),
                },

                "totals": {
                    "assets": _r8_money(total_assets),
                    "liabilities": _r8_money(
                        total_liabilities
                    ),
                    "posted_equity": _r8_money(
                        posted_equity
                    ),
                    "current_earnings": _r8_money(
                        current_earnings
                    ),
                    "equity_including_current_earnings":
                        _r8_money(
                            total_equity_with_current_earnings
                        ),
                    "liabilities_and_equity":
                        _r8_money(rhs),
                    "difference": _r8_money(difference),
                },

                "balanced": difference == _R8_ZERO,
            }

    except _R8HTTPException:
        raise

    except Exception as exc:
        raise _R8HTTPException(
            status_code=503,
            detail="reporting database unavailable",
        ) from exc

# ============================================================
# END R8-R1 REPORTING CONTRACT
# ============================================================

# ============================================================
# R8-R4B PERIOD CLOSE INTERNAL API
# ============================================================

from datetime import date as _r8r4_date
import os as _r8r4_os

import psycopg as _r8r4_psycopg
from psycopg.rows import dict_row as _r8r4_dict_row
from fastapi import HTTPException as _R8R4HTTPException


def _r8r4_conn():
    return _r8r4_psycopg.connect(
        host=_r8r4_os.environ["FINANCE_DB_HOST"],
        port=int(_r8r4_os.environ.get("FINANCE_DB_PORT", "5432")),
        dbname=_r8r4_os.environ["FINANCE_DB_NAME"],
        user=_r8r4_os.environ["FINANCE_DB_USER"],
        password=_r8r4_os.environ["FINANCE_DB_PASSWORD"],
        row_factory=_r8r4_dict_row,
    )


@app.get("/api/v1/periods")
def r8r4_list_periods():
    with _r8r4_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    company_id,
                    period_year,
                    period_month,
                    starts_on,
                    ends_on,
                    status,
                    closed_at,
                    created_at
                FROM fiscal_periods
                ORDER BY starts_on DESC
                """
            )
            rows = cur.fetchall()

    return {"periods": rows}


@app.get("/api/v1/periods/{period_id}/close-status")
def r8r4_close_status(period_id: str):
    with _r8r4_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    fp.id,
                    fp.company_id,
                    fp.period_year,
                    fp.period_month,
                    fp.starts_on,
                    fp.ends_on,
                    fp.status,
                    fp.closed_at,

                    (
                        SELECT COUNT(*)
                        FROM journal_entries je
                        WHERE je.fiscal_period_id=fp.id
                          AND je.status='DRAFT'
                    ) AS draft_journals,

                    (
                        SELECT COUNT(*)
                        FROM journal_entries je
                        WHERE je.fiscal_period_id=fp.id
                          AND je.status='POSTED'
                    ) AS posted_journals,

                    (
                        SELECT id
                        FROM journal_entries je
                        WHERE je.fiscal_period_id=fp.id
                          AND je.status='POSTED'
                          AND je.source_type='period.close'
                          AND je.source_id=fp.id::text
                        LIMIT 1
                    ) AS close_journal_id

                FROM fiscal_periods fp
                WHERE fp.id=%s::uuid
                """,
                (period_id,),
            )

            row = cur.fetchone()

    if not row:
        raise _R8R4HTTPException(
            status_code=404,
            detail="fiscal period not found",
        )

    row["can_close_now"] = (
        row["status"] == "OPEN"
        and row["draft_journals"] == 0
        and _r8r4_date.today() > row["ends_on"]
    )

    return row


@app.get("/api/v1/periods/{period_id}/close-preview")
def r8r4_close_preview(period_id: str):
    with _r8r4_conn() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT *
                FROM fiscal_periods
                WHERE id=%s::uuid
                """,
                (period_id,),
            )

            period = cur.fetchone()

            if not period:
                raise _R8R4HTTPException(
                    status_code=404,
                    detail="fiscal period not found",
                )

            cur.execute(
                """
                SELECT
                    a.code,
                    a.name,
                    a.type,

                    CASE
                        WHEN a.type='REVENUE'
                        THEN COALESCE(
                            SUM(jl.credit-jl.debit)
                            FILTER (WHERE je.id IS NOT NULL),
                            0
                        )

                        WHEN a.type='EXPENSE'
                        THEN COALESCE(
                            SUM(jl.debit-jl.credit)
                            FILTER (WHERE je.id IS NOT NULL),
                            0
                        )

                        ELSE 0
                    END AS balance

                FROM accounts a

                LEFT JOIN journal_lines jl
                  ON jl.account_id=a.id

                LEFT JOIN journal_entries je
                  ON je.id=jl.journal_entry_id
                 AND je.fiscal_period_id=%s::uuid
                 AND je.status='POSTED'

                WHERE a.company_id=%s
                  AND a.type IN ('REVENUE','EXPENSE')

                GROUP BY
                    a.id,
                    a.code,
                    a.name,
                    a.type

                ORDER BY a.code
                """,
                (
                    period_id,
                    period["company_id"],
                ),
            )

            accounts = cur.fetchall()

            cur.execute(
                """
                SELECT COUNT(*)
                FROM journal_entries
                WHERE fiscal_period_id=%s::uuid
                  AND status='DRAFT'
                """,
                (period_id,),
            )

            drafts = cur.fetchone()["count"]

    revenue = sum(
        x["balance"]
        for x in accounts
        if x["type"] == "REVENUE"
    )

    expenses = sum(
        x["balance"]
        for x in accounts
        if x["type"] == "EXPENSE"
    )

    net_income = revenue - expenses

    return {
        "period_id": period["id"],
        "period_year": period["period_year"],
        "period_month": period["period_month"],
        "starts_on": period["starts_on"],
        "ends_on": period["ends_on"],
        "status": period["status"],
        "draft_journals": drafts,
        "accounts": accounts,
        "totals": {
            "revenue": revenue,
            "expenses": expenses,
            "net_income": net_income,
        },
        "can_close_now": (
            period["status"] == "OPEN"
            and drafts == 0
            and _r8r4_date.today() > period["ends_on"]
        ),
        "close_journal_number": (
            "CLOSE-"
            + str(period["period_year"])
            + "-"
            + str(period["period_month"]).zfill(2)
        ),
    }


@app.post("/api/v1/periods/{period_id}/close")
def r8r4_close_period(period_id: str):
    try:
        with _r8r4_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT finance_close_fiscal_period(%s::uuid) AS id
                    """,
                    (period_id,),
                )

                row = cur.fetchone()

            conn.commit()

        return {
            "ok": True,
            "period_id": period_id,
            "close_journal_id": row["id"],
        }

    except Exception as exc:
        msg = str(exc)

        if (
            "cannot be closed before period end" in msg
            or "contains DRAFT journals" in msg
            or "unsupported fiscal period status" in msg
            or "journal number collision" in msg
        ):
            raise _R8R4HTTPException(
                status_code=409,
                detail=msg.splitlines()[0],
            )

        if "fiscal period not found" in msg:
            raise _R8R4HTTPException(
                status_code=404,
                detail="fiscal period not found",
            )

        raise
