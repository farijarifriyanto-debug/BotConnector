/* ============================================================
 * BOTCONNECTOR BUSINESS EXPANSION — schema additions
 *
 * Extends `local_business` (NOT a new kernel). Adds:
 *   - reporting dimensions (reporting_category, sales_channel, order_source)
 *   - canonical menu channel mapping (one menu truth, per-channel price)
 *   - generic delivery order core (all sources normalize here)
 *   - order lineage / double-count protection
 *   - delivery settlement (receivable/fee/promo/settlement/variance)
 *   - third-party POS connector framework
 *   - universal file connector (CSV/XLSX import/export)
 *   - watched-folder automation
 *   - generic webhook/REST connectors
 *   - QR self-order + queue display
 *   - local device bridge (scale/printer)
 *
 * Reuses Central Inventory + Finance Core. No duplicate kernels.
 * ============================================================ */

/* ============================================================ Reporting dimensions */
CREATE TABLE IF NOT EXISTS local_business.reporting_category (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    code          TEXT NOT NULL,   -- FOOD|BEVERAGE|DESSERT|RETAIL|SERVICE
    name          TEXT NOT NULL,
    CONSTRAINT uq_reporting_category UNIQUE (business_id, code)
);

CREATE TABLE IF NOT EXISTS local_business.sales_channel (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    code          TEXT NOT NULL,   -- DINE_IN|TAKEAWAY|PICKUP|QR_SELF_ORDER|GOFOOD|GRABFOOD|SHOPEEFOOD|POS
    name          TEXT NOT NULL,
    CONSTRAINT uq_sales_channel UNIQUE (business_id, code)
);

/* ============================================================ Canonical menu channel mapping */
CREATE TABLE IF NOT EXISTS local_business.channel_menu_mapping (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    menu_item_id  BIGINT NOT NULL REFERENCES local_business.menu_item(id),
    channel       TEXT NOT NULL,   -- POS|GOFOOD|GRABFOOD|SHOPEEFOOD|QR
    channel_item_id TEXT NOT NULL DEFAULT '',
    channel_price NUMERIC(20,2),
    available     BOOLEAN NOT NULL DEFAULT TRUE,
    channel_hours JSONB NOT NULL DEFAULT '{}'::jsonb,
    channel_promo JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_channel_menu UNIQUE (menu_item_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_channel_menu_channel ON local_business.channel_menu_mapping(channel);

/* ============================================================ Generic delivery order core */
CREATE TABLE IF NOT EXISTS local_business.delivery_order (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    business_id     BIGINT NOT NULL REFERENCES local_business.business(id),
    branch_id       BIGINT NOT NULL REFERENCES local_business.branch(id),
    source_provider TEXT NOT NULL,   -- GOFOOD|GRABFOOD|SHOPEEFOOD|QR_SELF_ORDER
    external_order_id TEXT NOT NULL,
    outlet_id       TEXT NOT NULL DEFAULT '',
    order_type      TEXT NOT NULL DEFAULT 'DELIVERY',  -- DELIVERY|DINE_IN|TAKEAWAY|PICKUP
    status          TEXT NOT NULL DEFAULT 'RECEIVED',  -- RECEIVED|ACCEPTED|PREPARING|READY|DRIVER_ASSIGNED|DRIVER_ARRIVED|PICKED_UP|COMPLETED|CANCELLED
    provider_status TEXT NOT NULL DEFAULT '',
    scheduled_at    TIMESTAMPTZ,
    gross_value     NUMERIC(20,2) NOT NULL DEFAULT 0,
    net_value       NUMERIC(20,2) NOT NULL DEFAULT 0,
    discount        NUMERIC(20,2) NOT NULL DEFAULT 0,
    service_charge  NUMERIC(20,2) NOT NULL DEFAULT 0,
    tax_amount      NUMERIC(20,2) NOT NULL DEFAULT 0,
    payment_state   TEXT NOT NULL DEFAULT 'UNPAID',  -- UNPAID|PAID|REFUNDED
    payment_method  TEXT NOT NULL DEFAULT '',
    provider_fee    NUMERIC(20,2) NOT NULL DEFAULT 0,
    merchant_promo_cost NUMERIC(20,2) NOT NULL DEFAULT 0,
    platform_promo  NUMERIC(20,2) NOT NULL DEFAULT 0,
    local_discount  NUMERIC(20,2) NOT NULL DEFAULT 0,
    other_adjustment NUMERIC(20,2) NOT NULL DEFAULT 0,
    expected_settlement NUMERIC(20,2) NOT NULL DEFAULT 0,
    actual_settlement   NUMERIC(20,2),
    settlement_variance NUMERIC(20,2),
    restaurant_order_id BIGINT REFERENCES local_business.restaurant_order(id),
    raw_payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_delivery_order UNIQUE (source_provider, outlet_id, external_order_id)
);
CREATE INDEX IF NOT EXISTS idx_delivery_order_status ON local_business.delivery_order(status);
CREATE INDEX IF NOT EXISTS idx_delivery_order_provider ON local_business.delivery_order(source_provider, external_order_id);

CREATE TABLE IF NOT EXISTS local_business.delivery_order_line (
    id            BIGSERIAL PRIMARY KEY,
    delivery_order_id BIGINT NOT NULL REFERENCES local_business.delivery_order(id),
    menu_item_id  BIGINT REFERENCES local_business.menu_item(id),
    channel_item_id TEXT NOT NULL DEFAULT '',
    name          TEXT NOT NULL,
    quantity      INTEGER NOT NULL,
    unit_price    NUMERIC(20,2) NOT NULL DEFAULT 0,
    line_total    NUMERIC(20,2) NOT NULL DEFAULT 0,
    modifier_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    line_no       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_delivery_line_order ON local_business.delivery_order_line(delivery_order_id);

/* ============================================================ Order lineage / double-count protection */
CREATE TABLE IF NOT EXISTS local_business.order_lineage (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    source_provider TEXT NOT NULL,
    source_pos     TEXT NOT NULL DEFAULT '',
    external_order_id TEXT NOT NULL,
    external_transaction_id TEXT NOT NULL DEFAULT '',
    canonical_order_id BIGINT,   -- restaurant_order.id or sale.id
    canonical_type TEXT NOT NULL DEFAULT '',  -- RESTAURANT_ORDER|SALE
    lineage_origin TEXT NOT NULL DEFAULT '',
    correlation_state TEXT NOT NULL DEFAULT 'RESOLVED',  -- RESOLVED|AMBIGUOUS|REVIEW
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_lineage UNIQUE (source_provider, source_pos, external_order_id, external_transaction_id)
);
CREATE INDEX IF NOT EXISTS idx_lineage_canonical ON local_business.order_lineage(canonical_order_id);

/* ============================================================ Delivery settlement */
CREATE TABLE IF NOT EXISTS local_business.delivery_settlement (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    source_provider TEXT NOT NULL,
    outlet_id     TEXT NOT NULL DEFAULT '',
    settlement_ref TEXT NOT NULL,
    gross_value    NUMERIC(20,2) NOT NULL DEFAULT 0,
    provider_fee   NUMERIC(20,2) NOT NULL DEFAULT 0,
    merchant_promo_cost NUMERIC(20,2) NOT NULL DEFAULT 0,
    expected_settlement NUMERIC(20,2) NOT NULL DEFAULT 0,
    actual_settlement   NUMERIC(20,2) NOT NULL DEFAULT 0,
    variance       NUMERIC(20,2) NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'PROCESSED',
    finance_tx_id  TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_delivery_settlement UNIQUE (source_provider, outlet_id, settlement_ref)
);

/* ============================================================ Third-party POS connector */
CREATE TABLE IF NOT EXISTS local_business.pos_connector (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    provider      TEXT NOT NULL,   -- MOKA|PAWOON|OLSERA|MAJOO|QASIR|KASIR_PINTAR|UNIVERSAL_FILE
    outlet_id     TEXT NOT NULL DEFAULT '',
    auth_mode     TEXT NOT NULL DEFAULT 'NONE',  -- NONE|OAUTH|API_KEY|BASIC
    status        TEXT NOT NULL DEFAULT 'BLOCKED_EXTERNAL',  -- BLOCKED_EXTERNAL|CONNECTED|ERROR
    last_sync_at  TIMESTAMPTZ,
    last_error    TEXT NOT NULL DEFAULT '',
    config        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pos_connector UNIQUE (business_id, provider, outlet_id)
);

/* ============================================================ Universal file connector */
CREATE TABLE IF NOT EXISTS local_business.file_import (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    import_type   TEXT NOT NULL,   -- SALES|PRODUCTS|INVENTORY|STOCK_MOVEMENT|RESTAURANT_SALES|SETTLEMENT
    filename      TEXT NOT NULL,
    file_fingerprint TEXT NOT NULL,
    format        TEXT NOT NULL,   -- CSV|XLSX
    status        TEXT NOT NULL DEFAULT 'UPLOADED',  -- UPLOADED|PREVIEW|VALIDATED|DRY_RUN|COMMITTED|REJECTED
    total_rows    INTEGER NOT NULL DEFAULT 0,
    valid_rows    INTEGER NOT NULL DEFAULT 0,
    error_rows    INTEGER NOT NULL DEFAULT 0,
    mapping_profile TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL DEFAULT '',
    error_report  JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    committed_at  TIMESTAMPTZ,
    CONSTRAINT uq_file_import_fingerprint UNIQUE (business_id, file_fingerprint)
);

/* ============================================================ Watched folder */
CREATE TABLE IF NOT EXISTS local_business.watched_folder (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    folder_path   TEXT NOT NULL,
    import_type   TEXT NOT NULL DEFAULT 'SALES',
    status        TEXT NOT NULL DEFAULT 'ACTIVE',
    last_scan_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_watched_folder UNIQUE (business_id, folder_path)
);

CREATE TABLE IF NOT EXISTS local_business.watched_file (
    id            BIGSERIAL PRIMARY KEY,
    watched_folder_id BIGINT NOT NULL REFERENCES local_business.watched_folder(id),
    filename      TEXT NOT NULL,
    file_fingerprint TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'INCOMING',  -- INCOMING|PROCESSING|PROCESSED|ERROR|ARCHIVED
    import_id     BIGINT REFERENCES local_business.file_import(id),
    error         TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at  TIMESTAMPTZ,
    CONSTRAINT uq_watched_file UNIQUE (watched_folder_id, file_fingerprint)
);

/* ============================================================ Generic webhook / REST connector */
CREATE TABLE IF NOT EXISTS local_business.webhook_connector (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    name          TEXT NOT NULL,
    direction     TEXT NOT NULL,   -- INBOUND|OUTBOUND
    kind          TEXT NOT NULL,   -- WEBHOOK|REST_PULL|REST_PUSH|LOCAL_NETWORK
    endpoint      TEXT NOT NULL,
    auth_mode     TEXT NOT NULL DEFAULT 'NONE',  -- NONE|API_KEY|BASIC|SIGNATURE
    signature_secret_hash TEXT NOT NULL DEFAULT '',
    idempotency   BOOLEAN NOT NULL DEFAULT TRUE,
    retry_count   INTEGER NOT NULL DEFAULT 3,
    timeout_sec   INTEGER NOT NULL DEFAULT 30,
    status        TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_webhook_connector UNIQUE (business_id, name)
);

CREATE TABLE IF NOT EXISTS local_business.webhook_event (
    id            BIGSERIAL PRIMARY KEY,
    connector_id  BIGINT NOT NULL REFERENCES local_business.webhook_connector(id),
    event_id      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'RECEIVED',  -- RECEIVED|PROCESSED|FAILED|RETRY
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT NOT NULL DEFAULT '',
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at  TIMESTAMPTZ,
    CONSTRAINT uq_webhook_event UNIQUE (connector_id, event_id)
);

/* ============================================================ QR self-order */
CREATE TABLE IF NOT EXISTS local_business.qr_menu (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    code          TEXT NOT NULL,   -- table/pickup QR code
    kind          TEXT NOT NULL DEFAULT 'TABLE',  -- TABLE|TAKEAWAY|PICKUP
    table_id      BIGINT REFERENCES local_business.restaurant_table(id),
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_qr_menu UNIQUE (business_id, branch_id, code)
);

/* ============================================================ Queue / customer display */
CREATE TABLE IF NOT EXISTS local_business.queue_ticket (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    queue_number  TEXT NOT NULL,
    order_id      BIGINT REFERENCES local_business.restaurant_order(id),
    status        TEXT NOT NULL DEFAULT 'QUEUED',  -- QUEUED|PREPARING|READY|PICKED_UP
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_queue_number UNIQUE (business_id, branch_id, queue_number)
);

/* ============================================================ Local device bridge */
CREATE TABLE IF NOT EXISTS local_business.device_bridge (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    branch_id     BIGINT NOT NULL REFERENCES local_business.branch(id),
    device_type   TEXT NOT NULL,   -- SCALE|PRINTER|CUSTOMER_DISPLAY|CASH_DRAWER
    device_id     TEXT NOT NULL,
    protocol      TEXT NOT NULL DEFAULT 'WEB_SERIAL',  -- WEB_SERIAL|LOCAL_BRIDGE
    status        TEXT NOT NULL DEFAULT 'DISCONNECTED',  -- CONNECTED|DISCONNECTED|ERROR
    last_seen_at  TIMESTAMPTZ,
    config        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_device_bridge UNIQUE (business_id, branch_id, device_type, device_id)
);

/* ============================================================ Barcode aliases */
CREATE TABLE IF NOT EXISTS local_business.barcode_alias (
    id            BIGSERIAL PRIMARY KEY,
    business_id   BIGINT NOT NULL REFERENCES local_business.business(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    barcode       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_barcode_alias UNIQUE (business_id, barcode)
);
