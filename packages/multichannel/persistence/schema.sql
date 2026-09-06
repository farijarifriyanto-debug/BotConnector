/* Persistence durabel multichannel di basis data `botconnector`.
 *
 * Lapisan baru DI ATAS foundation beku; tidak mengubah finance_core
 * maupun foundation. Menyimpan: tenant, toko (shop binding), pesanan
 * marketplace ternormalisasi, token OAuth (terenkripsi/tidak pernah
 * dibuka polos oleh API), permintaan otorisasi, settlement, audit.
 *
 * Idempotensi ditegakkan dengan kunci unik natural; duplikat ulang
 * ditolak/dikembalikan sebagai yang sudah ada (bukan galat).
 */

CREATE SCHEMA IF NOT EXISTS multichannel;

-- ============================================================ tenant
CREATE TABLE IF NOT EXISTS multichannel.tenant (
    id            TEXT PRIMARY KEY,          -- identitas tenant (mis. user id)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================ toko (shop)
-- Toko marketplace yang terikat ke tenant. Satu toko hanya boleh
-- dimiliki satu tenant (unique provider+shop_id).
CREATE TABLE IF NOT EXISTS multichannel.shop (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES multichannel.tenant(id),
    provider       TEXT NOT NULL,            -- 'shopee' | 'tiktok_shop' | 'tokopedia'
    shop_id        TEXT NOT NULL,            -- id toko dari marketplace
    shop_name      TEXT NOT NULL DEFAULT '',
    shop_region    TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'BELUM_TERHUBUNG',  -- BELUM_TERHUBUNG|MENUNGGU_OTORISASI|TERHUBUNG|KEDALUWARSA|TERPUTUS
    binding_origin TEXT NOT NULL DEFAULT 'PILOT',   -- REAL=produksi terotentikasi; PILOT=sintetik/uji internal
    access_token   BYTEA,                    -- dienkripsi
    refresh_token  BYTEA,                    -- dienkripsi
    access_expires_at TIMESTAMPTZ,
    refresh_expires_at TIMESTAMPTZ,
    access_hash    TEXT NOT NULL DEFAULT '', -- sidik jari SHA-256 token (tidak bocor nilai)
    shop_meta      JSONB NOT NULL DEFAULT '{}'::jsonb,  -- identitas toko read-only
    connected_at   TIMESTAMPTZ,
    last_read_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_shop_provider_shop UNIQUE (provider, shop_id),
    CONSTRAINT uq_shop_tenant_provider UNIQUE (tenant_id, provider)
);

-- migrasi aman: tambah kolom origin bila belum ada (tabel sudah ada)
ALTER TABLE multichannel.shop
    ADD COLUMN IF NOT EXISTS binding_origin TEXT NOT NULL DEFAULT 'PILOT';

-- ============================================================ kredensial OAuth tersimpan
-- Token tidak pernah terbaca lewat API publik. Sidik air disimpan untuk
-- menguji kehadiran/rotasi tanpa membuka nilai.
CREATE TABLE IF NOT EXISTS multichannel.shop_token (
    shop_id          BIGINT PRIMARY KEY REFERENCES multichannel.shop(id),
    provider         TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    access_cipher    BYTEA,
    refresh_cipher   BYTEA,
    access_hash      TEXT NOT NULL,
    refresh_hash     TEXT NOT NULL,
    access_issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    access_expires_at TIMESTAMPTZ,
    refresh_expires_at TIMESTAMPTZ,
    generation       INT NOT NULL DEFAULT 1,
    revoked          BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================ permintaan otorisasi (state)
CREATE TABLE IF NOT EXISTS multichannel.oauth_state (
    state         TEXT PRIMARY KEY,          -- 32+ byte acak, sekali pakai
    tenant_id     TEXT NOT NULL,
    provider      TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    used          BOOLEAN NOT NULL DEFAULT FALSE,
    consumed_at   TIMESTAMPTZ
);

-- ============================================================ pesanan ternormalisasi
CREATE TABLE IF NOT EXISTS multichannel.order (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    provider        TEXT NOT NULL,
    shop_id         TEXT NOT NULL,
    order_sn        TEXT NOT NULL,           -- nomor pesanan asli (order_sn)
    order_status    TEXT NOT NULL,          -- status asli Shopee
    order_status_normalized TEXT NOT NULL,  -- status baku (baru/dibayar/...)
    total_amount    NUMERIC(20,2) NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'IDR',
    buyer_username  TEXT NOT NULL DEFAULT '',
    buyer_name      TEXT NOT NULL DEFAULT '',
    item_count      INT NOT NULL DEFAULT 0,
    raw_payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- kunci idempotensi natural: satu pesanan per provider+shop+order_sn
    CONSTRAINT uq_order_provider_shop_order UNIQUE (provider, shop_id, order_sn)
);

CREATE INDEX IF NOT EXISTS idx_order_shop_status
    ON multichannel.order (provider, shop_id, order_status);

-- ============================================================ settlement
CREATE TABLE IF NOT EXISTS multichannel.settlement (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           TEXT NOT NULL,
    provider            TEXT NOT NULL,
    shop_id             TEXT NOT NULL,
    settlement_ref      TEXT NOT NULL,       -- referensi settlement asli
    trans_id            TEXT NOT NULL DEFAULT '',
    transaction_date    TIMESTAMPTZ,
    gross_amount        NUMERIC(20,2) NOT NULL DEFAULT 0,
    fee_amount          NUMERIC(20,2) NOT NULL DEFAULT 0,
    net_amount          NUMERIC(20,2) NOT NULL DEFAULT 0,
    raw_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_settlement_ref UNIQUE (provider, shop_id, settlement_ref)
);

-- ============================================================ audit idempoten
CREATE TABLE IF NOT EXISTS multichannel.audit_log (
    id            BIGSERIAL PRIMARY KEY,
    event_type    TEXT NOT NULL,
    actor         TEXT NOT NULL DEFAULT '',
    tenant_id     TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL DEFAULT '',
    shop_id       TEXT NOT NULL DEFAULT '',
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON multichannel.audit_log(created_at DESC);

-- ============================================================ status posting pesanan -> Finance
CREATE TABLE IF NOT EXISTS multichannel.order_finance (
    id            BIGSERIAL PRIMARY KEY,
    provider      TEXT NOT NULL,
    shop_id       TEXT NOT NULL,
    order_sn      TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    invoice_id    TEXT NOT NULL,
    journal_id    TEXT NOT NULL,
    customer_code TEXT NOT NULL,
    total         NUMERIC(20,2) NOT NULL,
    status        TEXT NOT NULL DEFAULT 'POSTED',
    posted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_order_finance UNIQUE (provider, shop_id, order_sn)
);

-- ============================================================ status settlement -> Finance
CREATE TABLE IF NOT EXISTS multichannel.settlement_finance (
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
);

-- ============================================================ ping / seeder
INSERT INTO multichannel.tenant (id) VALUES ('default-tenant')
ON CONFLICT (id) DO NOTHING;
