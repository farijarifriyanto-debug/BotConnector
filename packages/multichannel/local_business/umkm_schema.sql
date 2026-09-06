-- ============================================================
-- BC BISNIS UMKM ESSENTIAL OPERATIONS SCHEMA
-- ============================================================

CREATE SEQUENCE IF NOT EXISTS local_business.expense_seq START WITH 1;

CREATE TABLE IF NOT EXISTS local_business.expense (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id),
    expense_number TEXT NOT NULL UNIQUE,
    expense_date DATE NOT NULL DEFAULT CURRENT_DATE,
    category TEXT NOT NULL,
    amount NUMERIC(15, 2) NOT NULL CHECK (amount > 0),
    payment_source TEXT NOT NULL,
    payment_account_code TEXT NOT NULL,
    expense_account_code TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    finance_transaction_id TEXT,
    finance_journal_id TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_expense_biz_date ON local_business.expense(business_id, expense_date);
CREATE INDEX IF NOT EXISTS idx_expense_biz_cat ON local_business.expense(business_id, category);
