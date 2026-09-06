/* ============================================================
 * BOTCONNECTOR LOCAL BUSINESS SUITE — schema
 *
 * Domain baru `local_business` untuk operasi POS retail/restoran,
 * multi-branch, dan warehouse. TIDAK membuat kernel produk/inventory/
 * finance baru. Semua referensi stok menunjuk ke Central Inventory
 * Core (`multichannel.master_sku` + `multichannel.inventory_balance`),
 * dan semua pembukuan menunjuk ke Finance Core (`finance_core`).
 *
 * KEBENARAN STOK TETAP DI `multichannel`. `local_business` hanya
 * memegang entitas operasional (bisnis, cabang, register, kasir,
 * shift, penjualan, transfer, menu, resep, KOT, antrean offline).
 *
 * Lokasi = `multichannel.warehouse`. Setiap branch/warehouse adalah
 * satu lokasi stok. Stok bersifat LOCATION-AWARE.
 * ============================================================ */

CREATE SCHEMA IF NOT EXISTS local_business;

/* Concurrency-safe receipt/order/transfer numbering (per-business sequences). */
CREATE SEQUENCE IF NOT EXISTS local_business.sale_receipt_seq;
CREATE SEQUENCE IF NOT EXISTS local_business.restaurant_order_seq;
CREATE SEQUENCE IF NOT EXISTS local_business.transfer_seq;
CREATE SEQUENCE IF NOT EXISTS local_business.return_seq;
CREATE SEQUENCE IF NOT EXISTS local_business.goods_receipt_seq;
CREATE SEQUENCE IF NOT EXISTS local_business.kot_seq;

/* ============================================================ Business / branch / register / cashier */
CREATE TABLE IF NOT EXISTS local_business.business (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    code          TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    business_type TEXT NOT NULL DEFAULT 'RETAIL',  -- RETAIL|RESTAURANT|HYBRID
    currency      TEXT NOT NULL DEFAULT 'IDR',
    timezone      TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    status        TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE|INACTIVE
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_business UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS local_business.branch (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    code          TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    warehouse_id  BIGINT NOT NULL REFERENCES multichannel.warehouse(id),
    branch_type   TEXT NOT NULL DEFAULT 'RETAIL',  -- RETAIL|RESTAURANT|WAREHOUSE
    address       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_branch UNIQUE (business_id, code)
);
CREATE INDEX IF NOT EXISTS idx_branch_warehouse ON local_business.branch(warehouse_id);

CREATE TABLE IF NOT EXISTS local_business.register (
    id            BIGSERIAL PRIMARY KEY,
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    code          TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    device_id     TEXT NOT NULL DEFAULT '',   -- identitas device/register stabil (PWA)
    status        TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_register UNIQUE (branch_id, code)
);
CREATE INDEX IF NOT EXISTS idx_register_device ON local_business.register(device_id);

CREATE TABLE IF NOT EXISTS local_business.cashier (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    code          TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'CASHIER',  -- OWNER|MANAGER|CASHIER|KITCHEN
    pin_hash      TEXT NOT NULL DEFAULT '',
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cashier UNIQUE (business_id, code)
);

/* ============================================================ Shift / cash movement */
CREATE TABLE IF NOT EXISTS local_business.shift (
    id            BIGSERIAL PRIMARY KEY,
    register_id   BIGINT NOT NULL REFERENCES local_business.register(id),
    cashier_id    BIGINT REFERENCES local_business.cashier(id),
    opened_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at     TIMESTAMPTZ,
    opening_cash  NUMERIC(20,2) NOT NULL DEFAULT 0,
    closing_cash  NUMERIC(20,2),
    expected_cash NUMERIC(20,2),
    status        TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN|CLOSED
    note          TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_shift_open ON local_business.shift(register_id) WHERE status='OPEN';

CREATE TABLE IF NOT EXISTS local_business.cash_movement (
    id            BIGSERIAL PRIMARY KEY,
    shift_id      BIGINT NOT NULL REFERENCES local_business.shift(id),
    movement_type TEXT NOT NULL,   -- CASH_IN|CASH_OUT|PAY_IN|PAY_OUT
    amount        NUMERIC(20,2) NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    actor         TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

/* ============================================================ Customer (optional) */
CREATE TABLE IF NOT EXISTS local_business.customer (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    code          TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    phone         TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    credit_limit  NUMERIC(20,2) NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_customer UNIQUE (business_id, code)
);

/* ============================================================ Retail sale */
CREATE TABLE IF NOT EXISTS local_business.sale (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    business_id     BIGINT NOT NULL REFERENCES local_business.business(id),
    branch_id       BIGINT NOT NULL REFERENCES local_business.branch(id),
    register_id     BIGINT NOT NULL REFERENCES local_business.register(id),
    cashier_id      BIGINT REFERENCES local_business.cashier(id),
    shift_id        BIGINT REFERENCES local_business.shift(id),
    customer_id     BIGINT REFERENCES local_business.customer(id),
    receipt_number  TEXT NOT NULL,
    sale_type       TEXT NOT NULL DEFAULT 'RETAIL',  -- RETAIL|RESTAURANT
    status          TEXT NOT NULL DEFAULT 'COMPLETED', -- COMPLETED|VOID|RETURNED
    subtotal        NUMERIC(20,2) NOT NULL DEFAULT 0,
    discount        NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_amount      NUMERIC(20,2) NOT NULL DEFAULT 0,
    total           NUMERIC(20,2) NOT NULL DEFAULT 0,
    tender_method   TEXT NOT NULL DEFAULT 'CASH',  -- CASH|BANK_TRANSFER_MANUAL|QRIS_MANUAL|CARD_MANUAL|RECEIVABLE
    amount_tendered NUMERIC(20,2) NOT NULL DEFAULT 0,
    change_due      NUMERIC(20,2) NOT NULL DEFAULT 0,
    client_event_id TEXT NOT NULL DEFAULT '',   -- idempotensi offline
    device_id       TEXT NOT NULL DEFAULT '',
    created_at_client TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    voided_at       TIMESTAMPTZ,
    void_reason     TEXT NOT NULL DEFAULT '',
    voided_by       TEXT NOT NULL DEFAULT '',
    finance_invoice_id TEXT NOT NULL DEFAULT '',
    finance_journal_id TEXT NOT NULL DEFAULT '',
    origin          TEXT NOT NULL DEFAULT 'ONLINE',  -- ONLINE|OFFLINE|PILOT
    CONSTRAINT uq_sale_receipt UNIQUE (business_id, receipt_number),
    CONSTRAINT uq_sale_client_event UNIQUE (business_id, device_id, client_event_id)
);
CREATE INDEX IF NOT EXISTS idx_sale_branch ON local_business.sale(branch_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sale_shift ON local_business.sale(shift_id);

CREATE TABLE IF NOT EXISTS local_business.sale_line (
    id            BIGSERIAL PRIMARY KEY,
    sale_id       BIGINT NOT NULL REFERENCES local_business.sale(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku           TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    quantity      INTEGER NOT NULL,
    unit_price    NUMERIC(20,2) NOT NULL DEFAULT 0,
    discount      NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total    NUMERIC(20,2) NOT NULL DEFAULT 0,
    is_ingredient BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE bila dari resep restoran
    line_no       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_sale_line_sale ON local_business.sale_line(sale_id);

/* ============================================================ Return / void */
CREATE TABLE IF NOT EXISTS local_business.sale_return (
    id            BIGSERIAL PRIMARY KEY,
    sale_id       BIGINT NOT NULL REFERENCES local_business.sale(id),
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    return_number TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    total_refund  NUMERIC(20,2) NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'COMPLETED',
    client_event_id TEXT NOT NULL DEFAULT '',
    device_id     TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_return_number UNIQUE (branch_id, return_number),
    CONSTRAINT uq_return_client_event UNIQUE (branch_id, device_id, client_event_id)
);

CREATE TABLE IF NOT EXISTS local_business.sale_return_line (
    id            BIGSERIAL PRIMARY KEY,
    return_id     BIGINT NOT NULL REFERENCES local_business.sale_return(id),
    sale_line_id  BIGINT NOT NULL REFERENCES local_business.sale_line(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    quantity      INTEGER NOT NULL,
    unit_price    NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total    NUMERIC(20,2) NOT NULL DEFAULT 0
);

/* ============================================================ Branch transfer lifecycle */
CREATE TABLE IF NOT EXISTS local_business.transfer (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    transfer_number TEXT NOT NULL,
    source_branch_id BIGINT NOT NULL REFERENCES local_business.branch(id),
    dest_branch_id   BIGINT NOT NULL REFERENCES local_business.branch(id),
    status        TEXT NOT NULL DEFAULT 'DRAFT',  -- DRAFT|APPROVED|SHIPPED|IN_TRANSIT|RECEIVED|COMPLETED|CANCELLED
    approved_by   TEXT NOT NULL DEFAULT '',
    shipped_at    TIMESTAMPTZ,
    received_at   TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    cancelled_at  TIMESTAMPTZ,
    note          TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_transfer_number UNIQUE (business_id, transfer_number)
);
CREATE INDEX IF NOT EXISTS idx_transfer_status ON local_business.transfer(status);

CREATE TABLE IF NOT EXISTS local_business.transfer_line (
    id            BIGSERIAL PRIMARY KEY,
    transfer_id   BIGINT NOT NULL REFERENCES local_business.transfer(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku           TEXT NOT NULL,
    quantity      INTEGER NOT NULL,
    received_qty  INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_transfer_qty CHECK (quantity > 0)
);
CREATE INDEX IF NOT EXISTS idx_transfer_line_transfer ON local_business.transfer_line(transfer_id);

/* ============================================================ Restaurant: menu / recipe / BOM */
CREATE TABLE IF NOT EXISTS local_business.menu_category (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    name          TEXT NOT NULL,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_menu_category UNIQUE (business_id, name)
);

CREATE TABLE IF NOT EXISTS local_business.menu_item (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    category_id   BIGINT REFERENCES local_business.menu_category(id),
    name          TEXT NOT NULL,
    price         NUMERIC(20,2) NOT NULL DEFAULT 0,
    is_stocked    BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE = pre-produced stocked item
    stocked_sku_id BIGINT REFERENCES multichannel.master_sku(id),  -- bila is_stocked
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_menu_item UNIQUE (business_id, name)
);

CREATE TABLE IF NOT EXISTS local_business.menu_variant (
    id            BIGSERIAL PRIMARY KEY,
    menu_item_id  BIGINT NOT NULL REFERENCES local_business.menu_item(id),
    name          TEXT NOT NULL,
    price_delta   NUMERIC(20,2) NOT NULL DEFAULT 0,
    CONSTRAINT uq_menu_variant UNIQUE (menu_item_id, name)
);

CREATE TABLE IF NOT EXISTS local_business.menu_modifier (
    id            BIGSERIAL PRIMARY KEY,
    menu_item_id  BIGINT NOT NULL REFERENCES local_business.menu_item(id),
    name          TEXT NOT NULL,
    price_delta   NUMERIC(20,2) NOT NULL DEFAULT 0,
    CONSTRAINT uq_menu_modifier UNIQUE (menu_item_id, name)
);

/* Recipe / BOM: ingredient master SKU -> component quantity */
CREATE TABLE IF NOT EXISTS local_business.recipe (
    id            BIGSERIAL PRIMARY KEY,
    menu_item_id  BIGINT NOT NULL REFERENCES local_business.menu_item(id),
    version       INTEGER NOT NULL DEFAULT 1,
    yield_qty     NUMERIC(20,4) NOT NULL DEFAULT 1,
    waste_factor  NUMERIC(20,4) NOT NULL DEFAULT 0,  -- 0..1
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_recipe UNIQUE (menu_item_id, version)
);

CREATE TABLE IF NOT EXISTS local_business.recipe_component (
    id            BIGSERIAL PRIMARY KEY,
    recipe_id     BIGINT NOT NULL REFERENCES local_business.recipe(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku           TEXT NOT NULL,
    quantity      NUMERIC(20,4) NOT NULL,   -- per 1 yield
    unit          TEXT NOT NULL DEFAULT 'pcs',
    CONSTRAINT ck_recipe_qty CHECK (quantity > 0)
);
CREATE INDEX IF NOT EXISTS idx_recipe_component_sku ON local_business.recipe_component(master_sku_id);

/* Modifier ingredient delta: add-on changes ingredient usage */
CREATE TABLE IF NOT EXISTS local_business.modifier_ingredient (
    id            BIGSERIAL PRIMARY KEY,
    modifier_id   BIGINT NOT NULL REFERENCES local_business.menu_modifier(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    quantity      NUMERIC(20,4) NOT NULL,
    unit          TEXT NOT NULL DEFAULT 'pcs'
);

/* ============================================================ Restaurant order / table / KOT */
CREATE TABLE IF NOT EXISTS local_business.restaurant_table (
    id            BIGSERIAL PRIMARY KEY,
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    name          TEXT NOT NULL,
    capacity      INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'AVAILABLE',  -- AVAILABLE|OCCUPIED|RESERVED
    CONSTRAINT uq_table UNIQUE (branch_id, name)
);

CREATE TABLE IF NOT EXISTS local_business.restaurant_order (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    register_id   BIGINT NOT NULL REFERENCES local_business.register(id),
    cashier_id    BIGINT REFERENCES local_business.cashier(id),
    table_id      BIGINT REFERENCES local_business.restaurant_table(id),
    order_number  TEXT NOT NULL,
    order_type    TEXT NOT NULL DEFAULT 'DINE_IN',  -- DINE_IN|TAKEAWAY
    guest_count   INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'NEW',  -- NEW|ACCEPTED|PREPARING|READY|SERVED|CANCELLED|PAID
    note          TEXT NOT NULL DEFAULT '',
    subtotal      NUMERIC(20,2) NOT NULL DEFAULT 0,
    discount      NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_amount    NUMERIC(20,2) NOT NULL DEFAULT 0,
    total         NUMERIC(20,2) NOT NULL DEFAULT 0,
    client_event_id TEXT NOT NULL DEFAULT '',
    device_id     TEXT NOT NULL DEFAULT '',
    created_at_client TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_restaurant_order UNIQUE (business_id, order_number),
    CONSTRAINT uq_restaurant_client_event UNIQUE (business_id, device_id, client_event_id)
);
CREATE INDEX IF NOT EXISTS idx_restaurant_order_status ON local_business.restaurant_order(status);

CREATE TABLE IF NOT EXISTS local_business.restaurant_order_line (
    id            BIGSERIAL PRIMARY KEY,
    order_id      BIGINT NOT NULL REFERENCES local_business.restaurant_order(id),
    menu_item_id  BIGINT NOT NULL REFERENCES local_business.menu_item(id),
    menu_item_name TEXT NOT NULL,
    variant_id    BIGINT REFERENCES local_business.menu_variant(id),
    quantity      INTEGER NOT NULL,
    unit_price    NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total    NUMERIC(20,2) NOT NULL DEFAULT 0,
    notes         TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'NEW',  -- NEW|PREPARING|READY|SERVED|CANCELLED
    line_no       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_restaurant_line_order ON local_business.restaurant_order_line(order_id);

CREATE TABLE IF NOT EXISTS local_business.restaurant_order_modifier (
    id            BIGSERIAL PRIMARY KEY,
    order_line_id BIGINT NOT NULL REFERENCES local_business.restaurant_order_line(id),
    modifier_id   BIGINT NOT NULL REFERENCES local_business.menu_modifier(id),
    name          TEXT NOT NULL,
    price_delta   NUMERIC(20,2) NOT NULL DEFAULT 0
);

/* Kitchen Order Ticket / KDS */
CREATE TABLE IF NOT EXISTS local_business.kot (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    order_id      BIGINT NOT NULL REFERENCES local_business.restaurant_order(id),
    kot_number    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'NEW',  -- NEW|ACCEPTED|PREPARING|READY|SERVED|CANCELLED
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_kot_number UNIQUE (business_id, kot_number)
);
CREATE INDEX IF NOT EXISTS idx_kot_status ON local_business.kot(status);

/* ============================================================ Offline queue / allowance / sync */
CREATE TABLE IF NOT EXISTS local_business.offline_queue (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    register_id   BIGINT NOT NULL REFERENCES local_business.register(id),
    device_id     TEXT NOT NULL,
    client_event_id TEXT NOT NULL,
    event_type    TEXT NOT NULL,   -- SALE|RETURN|RESTAURANT_ORDER|KOT_STATUS
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        TEXT NOT NULL DEFAULT 'LOCAL_PENDING',  -- LOCAL_PENDING|SYNCING|SYNCED|CONFLICT|REJECTED
    error         TEXT NOT NULL DEFAULT '',
    created_at_client TIMESTAMPTZ,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    synced_at     TIMESTAMPTZ,
    CONSTRAINT uq_offline_event UNIQUE (business_id, device_id, client_event_id)
);
CREATE INDEX IF NOT EXISTS idx_offline_queue_status ON local_business.offline_queue(status);

/* Offline stock allowance: server grants bounded sell allowance per SKU/location */
CREATE TABLE IF NOT EXISTS local_business.offline_allowance (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    register_id   BIGINT NOT NULL REFERENCES local_business.register(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    allowance     INTEGER NOT NULL DEFAULT 0,   -- units device may sell offline
    used          INTEGER NOT NULL DEFAULT 0,
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_allowance UNIQUE (register_id, master_sku_id),
    CONSTRAINT ck_allowance_ge0 CHECK (allowance >= 0),
    CONSTRAINT ck_allowance_used CHECK (used >= 0)
);
CREATE INDEX IF NOT EXISTS idx_allowance_sku ON local_business.offline_allowance(master_sku_id);

/* ============================================================ Procurement / goods receipt */
CREATE TABLE IF NOT EXISTS local_business.goods_receipt (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    receipt_number TEXT NOT NULL,
    supplier_code TEXT NOT NULL DEFAULT '',
    supplier_name TEXT NOT NULL DEFAULT '',
    reference     TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'RECEIVED',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_goods_receipt UNIQUE (business_id, receipt_number)
);

CREATE TABLE IF NOT EXISTS local_business.goods_receipt_line (
    id            BIGSERIAL PRIMARY KEY,
    receipt_id    BIGINT NOT NULL REFERENCES local_business.goods_receipt(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    sku           TEXT NOT NULL,
    quantity      INTEGER NOT NULL,
    unit_cost     NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total    NUMERIC(20,2) NOT NULL DEFAULT 0
);

/* ============================================================ Audit */
CREATE TABLE IF NOT EXISTS local_business.audit_log (
    id            BIGSERIAL PRIMARY KEY,
    event_type    TEXT NOT NULL,
    actor         TEXT NOT NULL DEFAULT '',
    tenant_id     TEXT NOT NULL DEFAULT '',
    business_id   BIGINT,
    branch_id     BIGINT,
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lb_audit ON local_business.audit_log(created_at DESC);
