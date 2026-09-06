/* Business Suite customer boundary V1. Apply after the existing local_business
 * and multichannel schemas. No pilot row is deleted or reassigned. */
ALTER TABLE local_business.business
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(id) ON DELETE RESTRICT;

CREATE TABLE IF NOT EXISTS local_business.business_membership (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES local_business.business(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    role TEXT NOT NULL DEFAULT 'STAFF'
        CHECK (role IN ('OWNER','ADMIN','MANAGER','CASHIER','STAFF')),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('INVITED','ACTIVE','DISABLED')),
    permissions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_business_membership UNIQUE (business_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_business_membership_user_business
    ON local_business.business_membership(user_id, business_id, status);
CREATE INDEX IF NOT EXISTS idx_business_membership_business_role
    ON local_business.business_membership(business_id, role, status);

/* The central SKU kernel is deliberately global. This mapping is the
 * Business Suite catalog boundary and prevents a global SKU from being
 * implicitly visible to another business. */
CREATE TABLE IF NOT EXISTS local_business.business_product (
    business_id BIGINT NOT NULL REFERENCES local_business.business(id) ON DELETE CASCADE,
    master_sku_id BIGINT NOT NULL REFERENCES multichannel.master_sku(id) ON DELETE RESTRICT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (business_id, master_sku_id)
);
CREATE INDEX IF NOT EXISTS idx_business_product_sku_business
    ON local_business.business_product(master_sku_id, business_id, active);

/* All existing operational records belong to the explicit internal pilot;
 * customer businesses start with no products and no inherited stock. */
INSERT INTO local_business.business_product (business_id, master_sku_id)
SELECT 336, m.id FROM multichannel.master_sku m
ON CONFLICT (business_id, master_sku_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_business_branch_created
    ON local_business.branch(business_id, created_at);
CREATE INDEX IF NOT EXISTS idx_business_sale_created
    ON local_business.sale(business_id, created_at);
CREATE INDEX IF NOT EXISTS idx_business_order_created
    ON local_business.restaurant_order(business_id, created_at);
CREATE INDEX IF NOT EXISTS idx_business_transfer_created
    ON local_business.transfer(business_id, created_at);
CREATE INDEX IF NOT EXISTS idx_business_offline_status
    ON local_business.offline_queue(business_id, status, id);

/* Core catalog entry. Existing products are untouched. */
INSERT INTO products (slug, name, description, status)
VALUES (
    'business-suite',
    'Business Suite',
    'POS, inventory, restaurant, finance, reports, and integrations untuk bisnis Anda.',
    'active'
)
ON CONFLICT (slug) DO UPDATE SET
    name=EXCLUDED.name,
    description=EXCLUDED.description,
    status=EXCLUDED.status,
    updated_at=now();
