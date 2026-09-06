-- Intake Engine schema: durable import batches + per-row intake drafts.
-- Additive, idempotent. No business mutation lives here; only staging.

CREATE TABLE IF NOT EXISTS local_business.intake_batch (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        TEXT NOT NULL,
    business_id     BIGINT NOT NULL REFERENCES local_business.business(id),
    source          TEXT NOT NULL DEFAULT 'CSV',   -- CSV|XLSX|MOBILE|TELEGRAM|QUICK
    filename        TEXT NOT NULL DEFAULT '',
    format          TEXT NOT NULL DEFAULT 'CSV',
    status          TEXT NOT NULL DEFAULT 'PREVIEW', -- PREVIEW|CONFIRMED|COMMITTED|REJECTED
    total_rows      INTEGER NOT NULL DEFAULT 0,
    ready_rows      INTEGER NOT NULL DEFAULT 0,
    warning_rows    INTEGER NOT NULL DEFAULT 0,
    rejected_rows   INTEGER NOT NULL DEFAULT 0,
    mapping_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_report    JSONB NOT NULL DEFAULT '[]'::jsonb,
    idempotency_key TEXT NOT NULL DEFAULT '',
    actor           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at    TIMESTAMPTZ,
    committed_at    TIMESTAMPTZ
);

-- Durable outcome tracking for idempotent re-confirmation.
ALTER TABLE local_business.intake_batch
    ADD COLUMN IF NOT EXISTS committed_price INTEGER,
    ADD COLUMN IF NOT EXISTS committed_stock INTEGER,
    ADD COLUMN IF NOT EXISTS committed_cost  INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_intake_batch_id' AND conrelid = 'local_business.intake_batch'::regclass
    ) THEN
        ALTER TABLE local_business.intake_batch ADD CONSTRAINT uq_intake_batch_id UNIQUE (batch_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_intake_batch_idem' AND conrelid = 'local_business.intake_batch'::regclass
    ) THEN
        ALTER TABLE local_business.intake_batch ADD CONSTRAINT uq_intake_batch_idem UNIQUE (business_id, source, idempotency_key);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS local_business.intake_row (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            BIGINT NOT NULL REFERENCES local_business.intake_batch(id),
    row_no              INTEGER NOT NULL,
    sku                 TEXT NOT NULL DEFAULT '',
    name                TEXT NOT NULL DEFAULT '',
    barcode             TEXT NOT NULL DEFAULT '',
    category            TEXT NOT NULL DEFAULT '',
    unit                TEXT NOT NULL DEFAULT '',
    selling_price       NUMERIC(20,2),
    cost                NUMERIC(20,2),
    opening_qty         INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'READY', -- READY|WARNING|REJECTED
    issues              JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical_master_sku_id BIGINT REFERENCES multichannel.master_sku(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_intake_row UNIQUE (batch_id, row_no)
);

CREATE TABLE IF NOT EXISTS local_business.telegram_account (
    id                 BIGSERIAL PRIMARY KEY,
    owner_id           BIGINT NOT NULL,
    telegram_user_id   BIGINT NOT NULL,
    pairing_token      TEXT NOT NULL DEFAULT '',
    actor              TEXT NOT NULL DEFAULT '',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_telegram_account UNIQUE (owner_id, telegram_user_id)
);

-- ============================================================
-- Telegram real channel: owner pairing with hash/expiry/consumed
-- and durable update idempotency.
-- ============================================================

-- Owner <-> Telegram pairing.
-- pairing_token_hash: hash of a one-time expiring token (never raw secret).
-- Pairing is authorized by telegram_user_id, never username.
ALTER TABLE local_business.telegram_account
    ADD COLUMN IF NOT EXISTS pairing_token_hash TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS pairing_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS pairing_consumed_at TIMESTAMPTZ;

-- Durable Telegram update idempotency boundary (update_id).
CREATE TABLE IF NOT EXISTS local_business.telegram_update (
    update_id   BIGINT PRIMARY KEY,
    chat_id     BIGINT NOT NULL DEFAULT 0,
    telegram_user_id BIGINT NOT NULL DEFAULT 0,
    kind        TEXT NOT NULL DEFAULT 'MESSAGE',  -- MESSAGE|CALLBACK|PAIRING
    file_unique_id TEXT NOT NULL DEFAULT '',
    batch_id    TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Long-poll offset tracking (durable, survives restart).
CREATE TABLE IF NOT EXISTS local_business.telegram_offset (
    id          BIGINT PRIMARY KEY DEFAULT 1,
    poll_offset BIGINT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO local_business.telegram_offset (id, poll_offset) VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

-- One-time expiring owner pairing tokens (stored hashed; never raw secret).
CREATE TABLE IF NOT EXISTS local_business.telegram_pairing (
    id          BIGSERIAL PRIMARY KEY,
    owner_id    BIGINT NOT NULL,
    business_id BIGINT NOT NULL DEFAULT 0,
    token_hash  TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_telegram_pairing_hash UNIQUE (token_hash)
);

-- BC Bisnis Telegram owner-alert outbox (durable, additive).
-- Telegram delivery is a side effect only; business events never depend on it.
-- States: PENDING|SENDING|SENT|FAILED|UNKNOWN|CANCELLED.
-- UNKNOWN (ambiguous transport outcome) is deliberately NOT auto-retried in V1
-- to avoid duplicate owner alerts.
CREATE TABLE IF NOT EXISTS local_business.telegram_alert_outbox (
    id                 BIGSERIAL PRIMARY KEY,
    business_id        BIGINT NOT NULL,
    owner_id           BIGINT NOT NULL,
    notification_type  TEXT NOT NULL,
    event_key          TEXT NOT NULL,
    local_date         DATE,
    payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    status             TEXT NOT NULL DEFAULT 'PENDING',
    attempt_count      INTEGER NOT NULL DEFAULT 0,
    next_attempt_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    telegram_message_id BIGINT,
    last_error         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at            TIMESTAMPTZ,
    CONSTRAINT uq_telegram_alert_logical UNIQUE (notification_type, event_key)
);

-- ============================================================
-- Low-stock alert V1: configurable threshold + episode state tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS local_business.low_stock_threshold (
    id               BIGSERIAL PRIMARY KEY,
    business_id      BIGINT NOT NULL REFERENCES local_business.business(id),
    master_sku_id    BIGINT REFERENCES multichannel.master_sku(id),
    threshold        INTEGER NOT NULL CHECK (threshold >= 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_low_stock_threshold_sku 
    ON local_business.low_stock_threshold (business_id, master_sku_id) 
    WHERE master_sku_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_low_stock_threshold_biz 
    ON local_business.low_stock_threshold (business_id) 
    WHERE master_sku_id IS NULL;

CREATE TABLE IF NOT EXISTS local_business.low_stock_alert_state (
    id               BIGSERIAL PRIMARY KEY,
    business_id      BIGINT NOT NULL,
    warehouse_id     BIGINT NOT NULL,
    master_sku_id    BIGINT NOT NULL,
    is_alerted       BOOLEAN NOT NULL DEFAULT FALSE,
    alert_cycle      INTEGER NOT NULL DEFAULT 0,
    last_alerted_at  TIMESTAMPTZ,
    last_rearmed_at  TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_low_stock_alert_state UNIQUE (business_id, warehouse_id, master_sku_id)
);

-- ============================================================
-- Telegram threshold draft / preview state
-- ============================================================
CREATE TABLE IF NOT EXISTS local_business.telegram_threshold_draft (
    id               BIGSERIAL PRIMARY KEY,
    draft_token      TEXT NOT NULL UNIQUE,
    business_id      BIGINT NOT NULL REFERENCES local_business.business(id),
    owner_id         BIGINT NOT NULL,
    telegram_user_id BIGINT NOT NULL,
    master_sku_id    BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku              TEXT NOT NULL,
    action           TEXT NOT NULL DEFAULT 'SET', -- SET | REMOVE
    new_threshold    INTEGER,
    old_threshold    INTEGER,
    status           TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | CONFIRMED | CANCELLED | EXPIRED
    expires_at       TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at     TIMESTAMPTZ
);

-- ============================================================
-- Procurement & Replenishment Core V1
-- ============================================================

CREATE SEQUENCE IF NOT EXISTS local_business.po_seq START WITH 1;

CREATE TABLE IF NOT EXISTS local_business.supplier (
    id               BIGSERIAL PRIMARY KEY,
    business_id      BIGINT NOT NULL REFERENCES local_business.business(id),
    code             TEXT NOT NULL,
    name             TEXT NOT NULL,
    contact_name     TEXT,
    phone            TEXT,
    email            TEXT,
    address          TEXT,
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_business_supplier_code UNIQUE (business_id, code)
);

CREATE TABLE IF NOT EXISTS local_business.supplier_sku (
    id                 BIGSERIAL PRIMARY KEY,
    business_id        BIGINT NOT NULL REFERENCES local_business.business(id),
    supplier_id        BIGINT NOT NULL REFERENCES local_business.supplier(id),
    master_sku_id      BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    supplier_sku       TEXT,
    lead_time_days     INTEGER NOT NULL CHECK (lead_time_days >= 0),
    min_order_qty      INTEGER NOT NULL DEFAULT 1 CHECK (min_order_qty >= 1),
    purchase_unit_cost NUMERIC CHECK (purchase_unit_cost IS NULL OR purchase_unit_cost >= 0),
    target_stock       INTEGER CHECK (target_stock IS NULL OR target_stock >= 0),
    preferred          BOOLEAN NOT NULL DEFAULT TRUE,
    active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_supplier_sku UNIQUE (business_id, supplier_id, master_sku_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_preferred_supplier_sku
    ON local_business.supplier_sku (business_id, master_sku_id)
    WHERE active = TRUE AND preferred = TRUE;

CREATE TABLE IF NOT EXISTS local_business.purchase_order (
    id                    BIGSERIAL PRIMARY KEY,
    business_id           BIGINT NOT NULL REFERENCES local_business.business(id),
    supplier_id           BIGINT NOT NULL REFERENCES local_business.supplier(id),
    warehouse_id          BIGINT NOT NULL REFERENCES multichannel.warehouse(id),
    po_number             TEXT NOT NULL UNIQUE,
    status                TEXT NOT NULL DEFAULT 'DRAFT', -- DRAFT | CONFIRMED | PARTIALLY_RECEIVED | RECEIVED | CANCELLED
    expected_arrival_date DATE,
    notes                 TEXT,
    subtotal              NUMERIC NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    created_by            TEXT,
    client_event_id       TEXT,
    device_id             TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at          TIMESTAMPTZ,
    cancelled_at          TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_business_po_number UNIQUE (business_id, po_number)
);

CREATE TABLE IF NOT EXISTS local_business.purchase_order_line (
    id                BIGSERIAL PRIMARY KEY,
    purchase_order_id BIGINT NOT NULL REFERENCES local_business.purchase_order(id),
    master_sku_id     BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    supplier_sku      TEXT,
    description       TEXT NOT NULL DEFAULT '',
    ordered_qty       INTEGER NOT NULL CHECK (ordered_qty > 0),
    unit_cost         NUMERIC NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
    received_qty      INTEGER NOT NULL DEFAULT 0 CHECK (received_qty >= 0),
    line_total        NUMERIC NOT NULL DEFAULT 0 CHECK (line_total >= 0),
    line_no           INTEGER NOT NULL DEFAULT 1
);

ALTER TABLE local_business.goods_receipt
    ADD COLUMN IF NOT EXISTS purchase_order_id BIGINT REFERENCES local_business.purchase_order(id);

CREATE TABLE IF NOT EXISTS local_business.telegram_procurement_draft (
    id               BIGSERIAL PRIMARY KEY,
    draft_token      TEXT NOT NULL UNIQUE,
    draft_type       TEXT NOT NULL, -- SUPPLIER_CREATE | SUPPLIER_EDIT | SUPPLIER_OFF | RESTOCK_CONFIG | RESTOCK_OFF | PO_CREATE | PO_CONFIRM | PO_CANCEL | PO_RECEIVE | VENDOR_BILL_CREATE | VENDOR_BILL_POST | VENDOR_BILL_CANCEL | VENDOR_PAYMENT
    business_id      BIGINT NOT NULL REFERENCES local_business.business(id),
    owner_id         BIGINT NOT NULL,
    telegram_user_id BIGINT NOT NULL,
    payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status           TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | CONFIRMED | CANCELLED | EXPIRED
    expires_at       TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at     TIMESTAMPTZ
);

CREATE SEQUENCE IF NOT EXISTS local_business.vendor_bill_seq START WITH 1;
CREATE SEQUENCE IF NOT EXISTS local_business.vendor_payment_seq START WITH 1;

CREATE TABLE IF NOT EXISTS local_business.vendor_bill (
    id                 BIGSERIAL PRIMARY KEY,
    business_id        BIGINT NOT NULL REFERENCES local_business.business(id),
    supplier_id        BIGINT NOT NULL REFERENCES local_business.supplier(id),
    purchase_order_id  BIGINT REFERENCES local_business.purchase_order(id),
    bill_number        TEXT NOT NULL,
    vendor_reference   TEXT,
    bill_date          DATE NOT NULL DEFAULT CURRENT_DATE,
    due_date           DATE NOT NULL,
    currency           CHAR(3) NOT NULL DEFAULT 'IDR',
    subtotal           NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    tax_amount         NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    total              NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK (total >= 0),
    paid_amount        NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    outstanding_amount NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK (outstanding_amount >= 0),
    match_status       TEXT NOT NULL, -- MATCHED | QUANTITY_VARIANCE | PRICE_VARIANCE | QUANTITY_AND_PRICE_VARIANCE | MISSING_PO | MISSING_RECEIPT | MISSING_COST
    status             TEXT NOT NULL DEFAULT 'DRAFT', -- DRAFT | POSTED | PARTIALLY_PAID | PAID | CANCELLED
    finance_invoice_id TEXT,
    finance_journal_id TEXT,
    notes              TEXT,
    created_by         TEXT,
    client_event_id    TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_at          TIMESTAMPTZ,
    cancelled_at       TIMESTAMPTZ,
    paid_at            TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_business_vendor_bill_number UNIQUE (business_id, bill_number)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_bill_supplier_ref
    ON local_business.vendor_bill (business_id, supplier_id, vendor_reference)
    WHERE vendor_reference IS NOT NULL AND status != 'CANCELLED';

CREATE TABLE IF NOT EXISTS local_business.vendor_bill_line (
    id                     BIGSERIAL PRIMARY KEY,
    vendor_bill_id         BIGINT NOT NULL REFERENCES local_business.vendor_bill(id) ON DELETE CASCADE,
    purchase_order_line_id BIGINT REFERENCES local_business.purchase_order_line(id),
    goods_receipt_line_id  BIGINT REFERENCES local_business.goods_receipt_line(id),
    master_sku_id          BIGINT REFERENCES multichannel.master_sku(id),
    description            TEXT NOT NULL DEFAULT '',
    quantity               NUMERIC(20,4) NOT NULL CHECK (quantity > 0),
    unit_cost              NUMERIC(20,2) NOT NULL CHECK (unit_cost >= 0),
    tax_amount             NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    line_total             NUMERIC(20,2) NOT NULL CHECK (line_total >= 0),
    line_no                INTEGER NOT NULL DEFAULT 1,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS local_business.vendor_payment (
    id                   BIGSERIAL PRIMARY KEY,
    business_id          BIGINT NOT NULL REFERENCES local_business.business(id),
    vendor_bill_id       BIGINT NOT NULL REFERENCES local_business.vendor_bill(id),
    supplier_id          BIGINT NOT NULL REFERENCES local_business.supplier(id),
    payment_number       TEXT NOT NULL,
    amount               NUMERIC(20,2) NOT NULL CHECK (amount > 0),
    payment_date         DATE NOT NULL DEFAULT CURRENT_DATE,
    payment_account_id   TEXT NOT NULL,
    payment_account_name TEXT,
    finance_payment_id   TEXT,
    finance_journal_id   TEXT,
    status               TEXT NOT NULL DEFAULT 'COMPLETED',
    idempotency_key      TEXT,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_business_vendor_payment_number UNIQUE (business_id, payment_number)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_payment_idempotency
    ON local_business.vendor_payment (business_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;




