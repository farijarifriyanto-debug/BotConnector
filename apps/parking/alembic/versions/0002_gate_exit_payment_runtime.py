"""BotConnector Parking M4-M6 — gate runtime, exit quote, payment runtime.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- M4: gate / lane runtime state -------------------------------------
    op.create_table(
        "parking_gate_runtime",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("gate_id", sa.BigInteger(), sa.ForeignKey("parking_gate.id"), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "gate_id", name="gate_runtime_tenant_site_gate_uniq"),
        sa.CheckConstraint("state IN ('ONLINE','OFFLINE','MAINTENANCE','BLOCKED')", name="ck_parking_gate_runtime_state_allowed"),
    )
    op.create_index("ix_parking_gate_runtime_tenant_site", "parking_gate_runtime", ["tenant_id", "site_id"])

    op.create_table(
        "parking_lane_runtime",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("lane_id", sa.BigInteger(), sa.ForeignKey("parking_lane.id"), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "lane_id", name="lane_runtime_tenant_site_lane_uniq"),
        sa.CheckConstraint("state IN ('ONLINE','OFFLINE','MAINTENANCE','BLOCKED')", name="ck_parking_lane_runtime_state_allowed"),
    )
    op.create_index("ix_parking_lane_runtime_tenant_site", "parking_lane_runtime", ["tenant_id", "site_id"])

    # ---- M4: request-level idempotency -------------------------------------
    op.create_table(
        "parking_idempotency_record",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="idempotency_tenant_key_uniq"),
    )
    op.create_index("ix_parking_idempotency_tenant_op", "parking_idempotency_record", ["tenant_id", "operation"])

    # ---- M5: exit quote -----------------------------------------------------
    op.create_table(
        "parking_exit_quote",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("public_reference", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("parking_session.id"), nullable=False),
        sa.Column("tariff_version", sa.Integer(), nullable=True),
        sa.Column("tariff_snapshot", JSONB(), nullable=True),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("public_reference", name="exit_quote_public_reference_uniq"),
        sa.CheckConstraint("amount >= 0", name="ck_parking_exit_quote_amount_nonneg"),
        sa.CheckConstraint("status IN ('ACTIVE','EXPIRED','SUPERSEDED','PAID','CANCELLED')", name="ck_parking_exit_quote_status_allowed"),
    )
    op.create_index("ix_parking_exit_quote_tenant_site", "parking_exit_quote", ["tenant_id", "site_id"])
    op.create_index("ix_parking_exit_quote_session", "parking_exit_quote", ["session_id"])

    # ---- M6: payment --------------------------------------------------------
    op.create_table(
        "parking_payment",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("public_reference", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("parking_session.id"), nullable=False),
        sa.Column("quote_id", sa.BigInteger(), sa.ForeignKey("parking_exit_quote.id"), nullable=False),
        sa.Column("method", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("expected_amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("provider_reference", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("public_reference", name="payment_public_reference_uniq"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="payment_tenant_idempotency_uniq"),
        sa.CheckConstraint("expected_amount >= 0", name="ck_parking_payment_expected_amount_nonneg"),
        sa.CheckConstraint("state IN ('CREATED','PENDING','PAID','FAILED','EXPIRED','CANCELLED','REFUNDED')", name="ck_parking_payment_state_allowed"),
        sa.CheckConstraint("method IN ('CASH','QRIS_MPM_DYNAMIC','QRIS_CPM','COMPLIMENTARY','MEMBERSHIP')", name="ck_parking_payment_method_allowed"),
    )
    op.create_index("ix_parking_payment_tenant_site", "parking_payment", ["tenant_id", "site_id"])
    op.create_index("ix_parking_payment_session", "parking_payment", ["session_id"])
    op.create_index("ix_parking_payment_quote", "parking_payment", ["quote_id"])

    op.create_table(
        "parking_payment_attempt",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), sa.ForeignKey("parking_payment.id"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_reference", sa.String(128), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("state IN ('CREATED','PENDING','SUCCEEDED','FAILED','EXPIRED')", name="ck_parking_payment_attempt_state_allowed"),
    )
    op.create_index("ix_parking_payment_attempt_payment", "parking_payment_attempt", ["payment_id"])
    op.create_index("ix_parking_payment_attempt_tenant", "parking_payment_attempt", ["tenant_id"])

    op.create_table(
        "parking_payment_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), sa.ForeignKey("parking_payment.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor", sa.String(120), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
    )
    op.create_index("ix_parking_payment_event_payment_time", "parking_payment_event", ["payment_id", "occurred_at"])
    op.create_index("ix_parking_payment_event_tenant_time", "parking_payment_event", ["tenant_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("parking_payment_event")
    op.drop_table("parking_payment_attempt")
    op.drop_table("parking_payment")
    op.drop_table("parking_exit_quote")
    op.drop_table("parking_idempotency_record")
    op.drop_table("parking_lane_runtime")
    op.drop_table("parking_gate_runtime")
