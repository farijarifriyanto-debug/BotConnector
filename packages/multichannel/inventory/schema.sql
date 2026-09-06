/* Central Product / SKU Master + Central Inventory Core.
 *
 * Lapisan baru DI ATAS foundation beku dan di samping persistence
 * multichannel yang sudah ada. Tidak mengubah finance_core, tidak
 * mengubah tabel Codex legacy, tidak mengubah skema shop/order yang ada.
 *
 * KEBENARAN STOK HANYA DI SINI. Marketplace hanyalah proyeksi/cache.
 *
 * Kuantitas kanonik:
 *   ON_HAND  = fisik (masuk + retur + penyesuaian - keluar)
 *   RESERVED = terikat pesanan belum dikirim
 *   SAFETY_STOCK = penyangga (tidak dijual)
 *   AVAILABLE_TO_PROMISE = ON_HAND - RESERVED - SAFETY_STOCK  (>=0)
 *
 * Marketplace menyetel dari AVAILABLE_TO_PROMISE (proyeksi), bukan
 * menimpa ON_HAND.
 */

CREATE SCHEMA IF NOT EXISTS multichannel;

/* ============================================================ Product / SKU Master */
CREATE TABLE IF NOT EXISTS multichannel.product (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    brand       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_product_name ON multichannel.product(name, category);

CREATE TABLE IF NOT EXISTS multichannel.product_variant (
    id          BIGSERIAL PRIMARY KEY,
    product_id  BIGINT NOT NULL REFERENCES multichannel.product(id),
    name        TEXT NOT NULL,
    options     JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {warna:"Merah", ukuran:"M"}
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS multichannel.master_sku (
    id            BIGSERIAL PRIMARY KEY,
    sku           TEXT NOT NULL,               -- 'ABC-RED-M'
    product_id    BIGINT NOT NULL REFERENCES multichannel.product(id),
    variant_id    BIGINT REFERENCES multichannel.product_variant(id),
    barcode       TEXT NOT NULL DEFAULT '',
    on_hand       INTEGER NOT NULL DEFAULT 0,  -- ON_HAND (fisik)
    reserved      INTEGER NOT NULL DEFAULT 0,  -- RESERVED
    safety_stock  INTEGER NOT NULL DEFAULT 0,  -- SAFETY_STOCK
    version       BIGINT NOT NULL DEFAULT 0,   -- untuk optimistic-lock di lapisan DB
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_master_sku UNIQUE (sku),
    CONSTRAINT ck_onhand_ge0 CHECK (on_hand >= 0),
    CONSTRAINT ck_reserved_ge0 CHECK (reserved >= 0),
    CONSTRAINT ck_safety_ge0 CHECK (safety_stock >= 0)
);
CREATE INDEX IF NOT EXISTS idx_master_sku_product ON multichannel.master_sku(product_id);

/* ============================================================ Channel listing & SKU mapping */
CREATE TABLE IF NOT EXISTS multichannel.channel_listing (
    id            BIGSERIAL PRIMARY KEY,
    provider      TEXT NOT NULL,             -- 'shopee'|'tokopedia'|'tiktok_shop'|'blibli'|'lazada'
    shop_id       TEXT NOT NULL,
    product_id    TEXT NOT NULL DEFAULT '',
    listing_name  TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_channel_listing UNIQUE (provider, shop_id, product_id)
);

CREATE TABLE IF NOT EXISTS multichannel.channel_sku_map (
    id            BIGSERIAL PRIMARY KEY,
    channel_listing_id BIGINT NOT NULL REFERENCES multichannel.channel_listing(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    provider      TEXT NOT NULL,
    shop_id       TEXT NOT NULL,
    channel_sku   TEXT NOT NULL,             -- 'SP-123'
    extra         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_channel_sku_map UNIQUE (provider, shop_id, channel_sku),
    CONSTRAINT uq_channel_listing_sku UNIQUE (channel_listing_id, master_sku_id)
);
CREATE INDEX IF NOT EXISTS idx_channel_sku_map_master ON multichannel.channel_sku_map(master_sku_id);

/* ============================================================ Warehouse / location */
CREATE TABLE IF NOT EXISTS multichannel.warehouse (
    id          BIGSERIAL PRIMARY KEY,
    code        TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    is_default  BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_warehouse_code UNIQUE (code)
);

/* ============================================================ Inventory balances */
CREATE TABLE IF NOT EXISTS multichannel.inventory_balance (
    id            BIGSERIAL PRIMARY KEY,
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    warehouse_id  BIGINT REFERENCES multichannel.warehouse(id),
    on_hand       INTEGER NOT NULL DEFAULT 0,
    reserved      INTEGER NOT NULL DEFAULT 0,
    safety_stock  INTEGER NOT NULL DEFAULT 0,
    in_transit    INTEGER NOT NULL DEFAULT 0,   -- units in transit between locations
    available     INTEGER NOT NULL DEFAULT 0,   -- ON_HAND - RESERVED - SAFETY_STOCK
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_balance_master_sku_warehouse UNIQUE (master_sku_id, warehouse_id)
);

CREATE TABLE IF NOT EXISTS multichannel.inventory_reservation (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL,
    shop_id       TEXT NOT NULL,
    order_sn      TEXT NOT NULL,
    line_id       TEXT NOT NULL DEFAULT '',
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    channel_sku   TEXT NOT NULL DEFAULT '',
    qty           INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'RESERVED', -- RESERVED|RELEASED|CONSUMED|RETURNED
    event_seq     TEXT NOT NULL,             -- idempotensi natural (provider event/version)
    raw_event     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_reservation_event UNIQUE (provider, shop_id, order_sn, line_id, event_seq),
    CONSTRAINT ck_res_qty_positive CHECK (qty > 0)
);
CREATE INDEX IF NOT EXISTS idx_reservation_sku ON multichannel.inventory_reservation(master_sku_id, status);

CREATE TABLE IF NOT EXISTS multichannel.inventory_movement (
    id            BIGSERIAL PRIMARY KEY,
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    warehouse_id  BIGINT REFERENCES multichannel.warehouse(id),
    movement_type TEXT NOT NULL,        -- MASUK|KELUAR|RESERVASI|LEPAS|RETUR|PENYESUAIAN|WASTE|TRANSFER_OUT|TRANSFER_IN
    qty           INTEGER NOT NULL,
    on_hand_after INTEGER,
    reserved_after INTEGER,
    available_after INTEGER,
    reference     TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    tenant_id     TEXT NOT NULL DEFAULT '',
    actor         TEXT NOT NULL DEFAULT '',
    device_id     TEXT NOT NULL DEFAULT '',
    source_document TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_movement_sku ON multichannel.inventory_movement(master_sku_id, created_at);

CREATE TABLE IF NOT EXISTS multichannel.inventory_adjustment (
    id            BIGSERIAL PRIMARY KEY,
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    delta_on_hand INTEGER NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    reference     TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

/* ============================================================ Sync state + outbox + attempt + drift */
CREATE TABLE IF NOT EXISTS multichannel.inventory_sync_state (
    id            BIGSERIAL PRIMARY KEY,
    channel_sku_map_id BIGINT NOT NULL REFERENCES multichannel.channel_sku_map(id),
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    provider      TEXT NOT NULL,
    shop_id       TEXT NOT NULL,
    channel_sku   TEXT NOT NULL,
    desired_qty   INTEGER NOT NULL,        -- AVAILABLE_TO_PROMISE sekarang
    remote_qty    INTEGER,                 -- qty yang DIBACA terakhir di provider (bisa NULL)
    last_written_qty INTEGER NOT NULL DEFAULT 0,  -- qty terakhir yang DITULIS kita
    last_ack_qty  INTEGER,                 -- qty terakhir yang diakui provider (nullable)
    write_origin  TEXT NOT NULL DEFAULT '',     -- 'system' bila kita yang menulis
    last_write_at TIMESTAMPTZ,
    last_read_at  TIMESTAMPTZ,
    provider_event_seq TEXT NOT NULL DEFAULT '', -- version/event provider utk loop protection
    status        TEXT NOT NULL DEFAULT 'PENDING_SYNC', -- MATCHED|DRIFTED|PENDING_SYNC|FAILED|MANUAL_OVERRIDE|UNKNOWN
    last_error    TEXT NOT NULL DEFAULT '',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sync_map UNIQUE (channel_sku_map_id)
);
CREATE INDEX IF NOT EXISTS idx_sync_state_provider ON multichannel.inventory_sync_state(provider, status);

CREATE TABLE IF NOT EXISTS multichannel.inventory_sync_outbox (
    id            BIGSERIAL PRIMARY KEY,
    sync_state_id BIGINT NOT NULL REFERENCES multichannel.inventory_sync_state(id),
    provider      TEXT NOT NULL,
    shop_id       TEXT NOT NULL,
    channel_sku   TEXT NOT NULL,
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    desired_qty   INTEGER NOT NULL,
    origin        TEXT NOT NULL DEFAULT 'inventory',
    status        TEXT NOT NULL DEFAULT 'PENDING', -- PENDING|SENT|FAILED|DROPPED
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at       TIMESTAMPTZ,
    CONSTRAINT uq_outbox_sync UNIQUE (sync_state_id)
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON multichannel.inventory_sync_outbox(status) WHERE status IN ('PENDING','FAILED');

CREATE TABLE IF NOT EXISTS multichannel.inventory_sync_attempt (
    id               BIGSERIAL PRIMARY KEY,
    outbox_id        BIGINT NOT NULL REFERENCES multichannel.inventory_sync_outbox(id),
    provider         TEXT NOT NULL,
    status           TEXT NOT NULL,          -- SENT|FAILED
    remote_qty_before INTEGER NOT NULL DEFAULT -1,
    remote_qty_after  INTEGER NOT NULL DEFAULT -1,
    error            TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_attempt_outbox ON multichannel.inventory_sync_attempt(outbox_id);

CREATE TABLE IF NOT EXISTS multichannel.inventory_drift (
    id               BIGSERIAL PRIMARY KEY,
    channel_sku_map_id BIGINT NOT NULL REFERENCES multichannel.channel_sku_map(id),
    master_sku_id    BIGINT NOT NULL REFERENCES multichannel.master_sku(id),
    provider         TEXT NOT NULL,
    shop_id          TEXT NOT NULL,
    desired_qty      INTEGER NOT NULL,
    remote_qty       INTEGER NOT NULL,
    state            TEXT NOT NULL,   -- MATCHED|DRIFTED|PENDING_SYNC|FAILED|MANUAL_OVERRIDE|UNKNOWN
    delta            INTEGER NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_drift_map ON multichannel.inventory_drift(channel_sku_map_id, created_at);

/* ============================================================ Config / flags */
CREATE TABLE IF NOT EXISTS multichannel.inventory_config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO multichannel.inventory_config (key, value) VALUES
  ('GLOBAL_MULTICHANNEL_STOCK_WRITE','OFF'),
  ('AUTO_STOCK_DRIFT_REPAIR','OFF'),
  ('PAYMENT_CAPTURE','OFF'),
  ('AUTO_SETTLEMENT','OFF'),
  ('AUTO_FULFILLMENT','OFF'),
  ('FULL_CUTOVER','OFF')
ON CONFLICT (key) DO NOTHING;

/* ============================================================ Provider canary / real status */
CREATE TABLE IF NOT EXISTS multichannel.provider_canary (
    provider     TEXT PRIMARY KEY,
    auth_ready         TEXT NOT NULL DEFAULT 'NOT_READY',
    shop_identity      TEXT NOT NULL DEFAULT 'NOT_READY',
    sku_discovery      TEXT NOT NULL DEFAULT 'NOT_READY',
    order_read         TEXT NOT NULL DEFAULT 'NOT_READY',
    stock_read         TEXT NOT NULL DEFAULT 'NOT_READY',
    stock_write_canary TEXT NOT NULL DEFAULT 'NOT_ACCEPTED', -- BLOCKED_EXTERNAL|CANARY_ACCEPTED|...
    stock_write_approved TEXT NOT NULL DEFAULT 'NO',
    blocker            TEXT NOT NULL DEFAULT '',
    detail             JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO multichannel.provider_canary (provider) VALUES
    ('shopee'),('tokopedia'),('tiktok_shop'),('blibli'),('lazada')
ON CONFLICT (provider) DO NOTHING;

/* ============================================================ Seeder warehouse default */
INSERT INTO multichannel.warehouse (code, name, is_default)
    VALUES ('WH-DEFAULT','Gudang Utama', TRUE)
ON CONFLICT (code) DO NOTHING;
