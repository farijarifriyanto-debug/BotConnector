-- local_business/sales_schema.sql
-- Order-to-Cash (Customer, Quotation, Sales Order, Delivery, Customer Invoice, AR, Payment, Return, Credit Note)

CREATE SEQUENCE IF NOT EXISTS local_business.sales_quotation_seq START WITH 1;
CREATE SEQUENCE IF NOT EXISTS local_business.sales_order_seq START WITH 1;
CREATE SEQUENCE IF NOT EXISTS local_business.sales_delivery_seq START WITH 1;
CREATE SEQUENCE IF NOT EXISTS local_business.customer_invoice_seq START WITH 1;
CREATE SEQUENCE IF NOT EXISTS local_business.customer_payment_seq START WITH 1;
CREATE SEQUENCE IF NOT EXISTS local_business.sales_return_seq START WITH 1;
CREATE SEQUENCE IF NOT EXISTS local_business.credit_note_seq START WITH 1;

ALTER TABLE local_business.customer ADD COLUMN IF NOT EXISTS billing_address TEXT DEFAULT NULL;
ALTER TABLE local_business.customer ADD COLUMN IF NOT EXISTS delivery_address TEXT DEFAULT NULL;
ALTER TABLE local_business.customer ADD COLUMN IF NOT EXISTS tax_id TEXT DEFAULT NULL;
ALTER TABLE local_business.customer ADD COLUMN IF NOT EXISTS payment_terms_days INTEGER NOT NULL DEFAULT 30;
ALTER TABLE local_business.customer ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE local_business.customer ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT '';
ALTER TABLE local_business.customer ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_business_code ON local_business.customer(business_id, code);

CREATE TABLE IF NOT EXISTS local_business.sales_quotation (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id),
    customer_id BIGINT NOT NULL REFERENCES local_business.customer(id),
    quotation_number TEXT NOT NULL,
    quotation_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    subtotal NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
    total NUMERIC(20,2) NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    sales_order_id BIGINT,
    created_by TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_quotation_number UNIQUE (business_id, quotation_number)
);

CREATE TABLE IF NOT EXISTS local_business.sales_quotation_line (
    id BIGSERIAL PRIMARY KEY,
    quotation_id BIGINT NOT NULL REFERENCES local_business.sales_quotation(id) ON DELETE CASCADE,
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_no INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS local_business.sales_order (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id),
    customer_id BIGINT NOT NULL REFERENCES local_business.customer(id),
    quotation_id BIGINT REFERENCES local_business.sales_quotation(id),
    warehouse_id BIGINT NOT NULL REFERENCES multichannel.warehouse(id),
    order_number TEXT NOT NULL,
    order_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    subtotal NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
    total NUMERIC(20,2) NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_order_number UNIQUE (business_id, order_number)
);

CREATE TABLE IF NOT EXISTS local_business.sales_order_line (
    id BIGSERIAL PRIMARY KEY,
    sales_order_id BIGINT NOT NULL REFERENCES local_business.sales_order(id) ON DELETE CASCADE,
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    ordered_qty INTEGER NOT NULL,
    delivered_qty INTEGER NOT NULL DEFAULT 0,
    invoiced_qty INTEGER NOT NULL DEFAULT 0,
    unit_price NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_no INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS local_business.sales_delivery (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id),
    sales_order_id BIGINT NOT NULL REFERENCES local_business.sales_order(id),
    delivery_number TEXT NOT NULL,
    delivery_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status TEXT NOT NULL DEFAULT 'DELIVERED',
    idempotency_key TEXT,
    actor TEXT NOT NULL DEFAULT 'system',
    notes TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_delivery_number UNIQUE (business_id, delivery_number),
    CONSTRAINT uq_sales_delivery_idem UNIQUE (business_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS local_business.sales_delivery_line (
    id BIGSERIAL PRIMARY KEY,
    delivery_id BIGINT NOT NULL REFERENCES local_business.sales_delivery(id) ON DELETE CASCADE,
    sales_order_line_id BIGINT NOT NULL REFERENCES local_business.sales_order_line(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    line_no INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS local_business.customer_invoice (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id),
    customer_id BIGINT NOT NULL REFERENCES local_business.customer(id),
    sales_order_id BIGINT REFERENCES local_business.sales_order(id),
    invoice_number TEXT NOT NULL,
    invoice_date DATE NOT NULL DEFAULT CURRENT_DATE,
    due_date DATE NOT NULL,
    subtotal NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
    total NUMERIC(20,2) NOT NULL DEFAULT 0,
    paid_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
    outstanding_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    finance_invoice_id TEXT DEFAULT NULL,
    finance_journal_id TEXT DEFAULT NULL,
    posted_at TIMESTAMPTZ DEFAULT NULL,
    paid_at TIMESTAMPTZ DEFAULT NULL,
    notes TEXT DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_customer_invoice_number UNIQUE (business_id, invoice_number)
);

CREATE TABLE IF NOT EXISTS local_business.customer_invoice_line (
    id BIGSERIAL PRIMARY KEY,
    invoice_id BIGINT NOT NULL REFERENCES local_business.customer_invoice(id) ON DELETE CASCADE,
    sales_order_line_id BIGINT REFERENCES local_business.sales_order_line(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_no INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS local_business.customer_payment (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id),
    customer_invoice_id BIGINT NOT NULL REFERENCES local_business.customer_invoice(id),
    customer_id BIGINT NOT NULL REFERENCES local_business.customer(id),
    payment_number TEXT NOT NULL,
    amount NUMERIC(20,2) NOT NULL,
    payment_date DATE NOT NULL DEFAULT CURRENT_DATE,
    payment_account_id TEXT NOT NULL,
    payment_account_name TEXT NOT NULL DEFAULT '',
    finance_payment_id TEXT DEFAULT NULL,
    finance_journal_id TEXT DEFAULT NULL,
    status TEXT NOT NULL DEFAULT 'COMPLETED',
    idempotency_key TEXT NOT NULL,
    notes TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_customer_payment_number UNIQUE (business_id, payment_number),
    CONSTRAINT uq_customer_payment_idem UNIQUE (business_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS local_business.sales_order_return (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id),
    customer_id BIGINT NOT NULL REFERENCES local_business.customer(id),
    sales_order_id BIGINT REFERENCES local_business.sales_order(id),
    warehouse_id BIGINT NOT NULL REFERENCES multichannel.warehouse(id),
    return_number TEXT NOT NULL,
    return_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status TEXT NOT NULL DEFAULT 'COMPLETED',
    reason TEXT DEFAULT '',
    idempotency_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sales_order_return_num UNIQUE (business_id, return_number),
    CONSTRAINT uq_sales_order_return_idem UNIQUE (business_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS local_business.sales_order_return_line (
    id BIGSERIAL PRIMARY KEY,
    return_id BIGINT NOT NULL REFERENCES local_business.sales_order_return(id) ON DELETE CASCADE,
    sales_order_line_id BIGINT REFERENCES local_business.sales_order_line(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(20,2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS local_business.customer_credit_note (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id),
    customer_id BIGINT NOT NULL REFERENCES local_business.customer(id),
    customer_invoice_id BIGINT REFERENCES local_business.customer_invoice(id),
    sales_order_return_id BIGINT REFERENCES local_business.sales_order_return(id),
    credit_note_number TEXT NOT NULL,
    amount NUMERIC(20,2) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'POSTED',
    finance_journal_id TEXT DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_customer_credit_note_num UNIQUE (business_id, credit_note_number)
);
