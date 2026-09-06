"""BotConnector Parking — deployment profiles and payment-only gateway.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Tenant deployment profile & webhook configuration
    op.add_column("parking_tenant", sa.Column("deployment_profile", sa.String(32), server_default="FULL_STACK", nullable=False))
    op.add_column("parking_tenant", sa.Column("webhook_url", sa.String(512), nullable=True))
    op.add_column("parking_tenant", sa.Column("webhook_secret", sa.String(128), nullable=True))
    op.create_check_constraint(
        "ck_parking_tenant_deployment_profile",
        "parking_tenant",
        "deployment_profile IN ('FULL_STACK','EXISTING_HARDWARE','PAYMENT_ONLY')",
    )

    # 2. Payment table enhancements for standalone Payment-Only integration
    op.alter_column("parking_payment", "site_id", existing_type=sa.BigInteger(), nullable=True)
    op.alter_column("parking_payment", "session_id", existing_type=sa.BigInteger(), nullable=True)
    op.alter_column("parking_payment", "quote_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("parking_payment", sa.Column("merchant_order_ref", sa.String(128), nullable=True))
    op.add_column("parking_payment", sa.Column("webhook_status", sa.String(32), nullable=True))
    op.add_column("parking_payment", sa.Column("webhook_delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_parking_payment_merchant_ref", "parking_payment", ["tenant_id", "merchant_order_ref"])

    # 3. Expand payment methods to include GATEWAY_QRIS and SIMULATOR
    op.drop_constraint("ck_parking_payment_method_allowed", "parking_payment", type_="check")
    op.create_check_constraint(
        "ck_parking_payment_method_allowed",
        "parking_payment",
        "method IN ('CASH','QRIS_MPM_DYNAMIC','QRIS_CPM','COMPLIMENTARY','MEMBERSHIP','GATEWAY_QRIS','SIMULATOR')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_parking_payment_method_allowed", "parking_payment", type_="check")
    op.create_check_constraint(
        "ck_parking_payment_method_allowed",
        "parking_payment",
        "method IN ('CASH','QRIS_MPM_DYNAMIC','QRIS_CPM','COMPLIMENTARY','MEMBERSHIP')",
    )
    op.drop_index("ix_parking_payment_merchant_ref", table_name="parking_payment")
    op.drop_column("parking_payment", "webhook_delivered_at")
    op.drop_column("parking_payment", "webhook_status")
    op.drop_column("parking_payment", "merchant_order_ref")
    op.drop_constraint("ck_parking_tenant_deployment_profile", "parking_tenant", type_="check")
    op.drop_column("parking_tenant", "webhook_secret")
    op.drop_column("parking_tenant", "webhook_url")
    op.drop_column("parking_tenant", "deployment_profile")
