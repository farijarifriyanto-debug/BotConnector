-- ============================================================
-- Telegram V2 Schema Migration: Multi-Tenant, BYOB, Destinations, Scopes, Rules
-- ============================================================

-- 1. Extend local_business.telegram_account for multi-tenant and Core user identity
ALTER TABLE local_business.telegram_account
    ADD COLUMN IF NOT EXISTS core_user_id UUID,
    ADD COLUMN IF NOT EXISTS business_id BIGINT,
    ADD COLUMN IF NOT EXISTS membership_id BIGINT,
    ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'owner';

-- Backfill business_id from owner_id where missing
UPDATE local_business.telegram_account
SET business_id = owner_id
WHERE business_id IS NULL AND owner_id > 0;

-- 2. Extend local_business.telegram_pairing for Core user context and destinations
ALTER TABLE local_business.telegram_pairing
    ADD COLUMN IF NOT EXISTS core_user_id UUID,
    ADD COLUMN IF NOT EXISTS destination_type TEXT NOT NULL DEFAULT 'PRIVATE',
    ADD COLUMN IF NOT EXISTS telegram_bot_id BIGINT,
    ADD COLUMN IF NOT EXISTS branch_id BIGINT,
    ADD COLUMN IF NOT EXISTS purpose TEXT;

-- 3. Active Telegram user state (for multi-business switching and active branch context)
CREATE TABLE IF NOT EXISTS local_business.telegram_user_state (
    telegram_user_id BIGINT PRIMARY KEY,
    active_business_id BIGINT NOT NULL REFERENCES local_business.business(id) ON DELETE CASCADE,
    active_branch_id BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. Bot Registry (Supports SYSTEM_GLOBAL and CUSTOMER_BYOB)
CREATE TABLE IF NOT EXISTS local_business.telegram_bot (
    id BIGSERIAL PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    business_id BIGINT REFERENCES local_business.business(id) ON DELETE CASCADE,
    bot_type TEXT NOT NULL DEFAULT 'CUSTOMER_BYOB',
    bot_id BIGINT NOT NULL,
    bot_username TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    token_ciphertext TEXT,
    token_key_version INTEGER DEFAULT 1,
    webhook_secret_hash TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_by_core_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_telegram_bot_active_bot_id
    ON local_business.telegram_bot (bot_id)
    WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_telegram_bot_biz
    ON local_business.telegram_bot (business_id);

-- 5. Bot Scopes
CREATE TABLE IF NOT EXISTS local_business.telegram_bot_scope (
    id BIGSERIAL PRIMARY KEY,
    telegram_bot_id BIGINT NOT NULL REFERENCES local_business.telegram_bot(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL,
    scope_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_telegram_bot_scope_bot
    ON local_business.telegram_bot_scope (telegram_bot_id);

-- 6. Destinations (Private Chats, Groups, Supergroups)
CREATE TABLE IF NOT EXISTS local_business.telegram_destination (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id) ON DELETE CASCADE,
    telegram_bot_id BIGINT REFERENCES local_business.telegram_bot(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    chat_type TEXT NOT NULL DEFAULT 'PRIVATE',
    display_name TEXT NOT NULL DEFAULT '',
    branch_id BIGINT,
    purpose TEXT NOT NULL DEFAULT 'GENERAL',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_by_core_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_telegram_dest_biz_bot_chat UNIQUE (business_id, telegram_bot_id, chat_id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_dest_biz
    ON local_business.telegram_destination (business_id);

-- 7. Notification Routing Rules
CREATE TABLE IF NOT EXISTS local_business.telegram_notification_rule (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id) ON DELETE CASCADE,
    destination_id BIGINT NOT NULL REFERENCES local_business.telegram_destination(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    branch_id BIGINT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_telegram_rule UNIQUE (business_id, destination_id, event_type, branch_id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_rule_biz_event
    ON local_business.telegram_notification_rule (business_id, event_type);

-- 8. Extend telegram_alert_outbox for destination & bot routing
ALTER TABLE local_business.telegram_alert_outbox
    ADD COLUMN IF NOT EXISTS destination_id BIGINT REFERENCES local_business.telegram_destination(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS chat_id BIGINT,
    ADD COLUMN IF NOT EXISTS telegram_bot_id BIGINT REFERENCES local_business.telegram_bot(id) ON DELETE SET NULL;
