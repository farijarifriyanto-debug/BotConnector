"""BotConnector Parking M1 foundation — initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parking_tenant",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code", name="tenant_code_uniq"),
        sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED')", name="ck_parking_tenant_status_allowed"),
    )

    op.create_table(
        "parking_site",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="site_tenant_code_uniq"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_parking_site_status_allowed"),
    )
    op.create_index("ix_parking_site_tenant_id", "parking_site", ["tenant_id"])

    op.create_table(
        "parking_gate",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "code", name="gate_tenant_site_code_uniq"),
        sa.CheckConstraint("direction IN ('ENTRY','EXIT','BIDIRECTIONAL')", name="ck_parking_gate_direction_allowed"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE','MAINTENANCE')", name="ck_parking_gate_status_allowed"),
    )
    op.create_index("ix_parking_gate_tenant_site", "parking_gate", ["tenant_id", "site_id"])

    op.create_table(
        "parking_lane",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("gate_id", sa.BigInteger(), sa.ForeignKey("parking_gate.id"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("vehicle_types", JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "gate_id", "code", name="lane_tenant_site_gate_code_uniq"),
        sa.CheckConstraint("direction IN ('ENTRY','EXIT','BIDIRECTIONAL')", name="ck_parking_lane_direction_allowed"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE','MAINTENANCE')", name="ck_parking_lane_status_allowed"),
    )
    op.create_index("ix_parking_lane_tenant_site_gate", "parking_lane", ["tenant_id", "site_id", "gate_id"])

    op.create_table(
        "parking_operator",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("api_key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "username", name="operator_tenant_username_uniq"),
        sa.CheckConstraint("role IN ('ADMIN','SUPERVISOR','OPERATOR')", name="ck_parking_operator_role_allowed"),
        sa.CheckConstraint("status IN ('ACTIVE','DISABLED')", name="ck_parking_operator_status_allowed"),
    )
    op.create_index("ix_parking_operator_tenant", "parking_operator", ["tenant_id"])
    op.create_index("ix_parking_operator_api_key_hash", "parking_operator", ["api_key_hash"])

    op.create_table(
        "parking_shift",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), sa.ForeignKey("parking_operator.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('OPEN','CLOSED')", name="ck_parking_shift_status_allowed"),
    )
    op.create_index("ix_parking_shift_tenant_site", "parking_shift", ["tenant_id", "site_id"])

    op.create_table(
        "parking_vehicle",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("plate_normalized", sa.String(32), nullable=False),
        sa.Column("plate_display", sa.String(64), nullable=False),
        sa.Column("vehicle_type", sa.String(20), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "plate_normalized", name="vehicle_tenant_plate_uniq"),
        sa.CheckConstraint(
            "vehicle_type IN ('MOTORCYCLE','CAR','TRUCK','BUS','OTHER')", name="ck_parking_vehicle_vehicle_type_allowed"
        ),
    )
    op.create_index("ix_parking_vehicle_plate", "parking_vehicle", ["plate_normalized"])

    op.create_table(
        "parking_tariff_plan",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("grace_period_minutes", sa.Integer(), nullable=False),
        sa.Column("daily_max_amount", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "code", name="plan_tenant_site_code_uniq"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_parking_tariff_plan_status_allowed"),
        sa.CheckConstraint("grace_period_minutes >= 0", name="ck_parking_tariff_plan_grace_nonneg"),
        sa.CheckConstraint("daily_max_amount IS NULL OR daily_max_amount >= 0", name="ck_parking_tariff_plan_daily_max_nonneg"),
    )
    op.create_index("ix_parking_tariff_plan_tenant_site_status", "parking_tariff_plan", ["tenant_id", "site_id", "status"])

    op.create_table(
        "parking_tariff_rule",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("plan_id", sa.BigInteger(), sa.ForeignKey("parking_tariff_plan.id"), nullable=False),
        sa.Column("vehicle_type", sa.String(20), nullable=False),
        sa.Column("rule_type", sa.String(30), nullable=False),
        sa.Column("precedence", sa.Integer(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("plan_id", "vehicle_type", "rule_type", name="rule_plan_vehicle_type_uniq"),
        sa.CheckConstraint("rule_type IN ('FLAT','HOURLY','PROGRESSIVE','LOST_TICKET_FEE')", name="ck_parking_tariff_rule_rule_type_allowed"),
        sa.CheckConstraint(
            "vehicle_type IN ('MOTORCYCLE','CAR','TRUCK','BUS','OTHER')", name="ck_parking_tariff_rule_vehicle_type_allowed"
        ),
    )
    op.create_index("ix_parking_tariff_rule_plan", "parking_tariff_rule", ["plan_id"])
    op.create_index("ix_parking_tariff_rule_tenant_site", "parking_tariff_rule", ["tenant_id", "site_id"])

    op.create_table(
        "parking_session",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("public_reference", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("vehicle_id", sa.BigInteger(), sa.ForeignKey("parking_vehicle.id"), nullable=False),
        sa.Column("vehicle_type", sa.String(20), nullable=False),
        sa.Column("plate_normalized", sa.String(32), nullable=False),
        sa.Column("plate_display", sa.String(64), nullable=False),
        sa.Column("entry_gate_id", sa.BigInteger(), sa.ForeignKey("parking_gate.id"), nullable=False),
        sa.Column("entry_lane_id", sa.BigInteger(), sa.ForeignKey("parking_lane.id"), nullable=False),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_gate_id", sa.BigInteger(), sa.ForeignKey("parking_gate.id"), nullable=True),
        sa.Column("exit_lane_id", sa.BigInteger(), sa.ForeignKey("parking_lane.id"), nullable=True),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("tariff_plan_id", sa.BigInteger(), sa.ForeignKey("parking_tariff_plan.id"), nullable=True),
        sa.Column("tariff_version", sa.Integer(), nullable=True),
        sa.Column("tariff_snapshot", JSONB(), nullable=True),
        sa.Column("calculated_amount", sa.Integer(), nullable=False),
        sa.Column("paid_amount", sa.Integer(), nullable=False),
        sa.Column("payment_state", sa.String(20), nullable=False),
        sa.Column("lost_ticket", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("public_reference", name="session_public_reference_uniq"),
        sa.CheckConstraint(
            "state IN ('CREATED','ENTERED','PARKED','PAYMENT_PENDING','PAID','EXIT_AUTHORIZED',"
            "'EXITED','CLOSED','CANCELLED','LOST_TICKET','MANUAL_REVIEW')",
            name="ck_parking_session_state_allowed",
        ),
        sa.CheckConstraint(
            "payment_state IN ('NONE','PENDING','PAID','COMPLIMENTARY')",
            name="ck_parking_session_payment_state_allowed",
        ),
        sa.CheckConstraint("calculated_amount >= 0", name="ck_parking_session_calculated_amount_nonneg"),
        sa.CheckConstraint("paid_amount >= 0", name="ck_parking_session_paid_amount_nonneg"),
    )
    op.create_index("ix_parking_session_tenant_site_state", "parking_session", ["tenant_id", "site_id", "state"])
    op.create_index("ix_parking_session_tenant_site_entry_at", "parking_session", ["tenant_id", "site_id", "entry_at"])
    op.create_index("ix_parking_session_tenant_state", "parking_session", ["tenant_id", "state"])
    op.create_index("ix_parking_session_tenant_vehicle", "parking_session", ["tenant_id", "vehicle_id"])
    op.create_index(
        "uq_parking_session_active_vehicle",
        "parking_session",
        ["tenant_id", "site_id", "vehicle_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('CREATED','ENTERED','PARKED','PAYMENT_PENDING','LOST_TICKET','MANUAL_REVIEW')"
        ),
    )

    op.create_table(
        "parking_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("parking_session.id"), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor", sa.String(120), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
    )
    op.create_index("ix_parking_event_tenant_site_time", "parking_event", ["tenant_id", "site_id", "occurred_at"])
    op.create_index("ix_parking_event_session_time", "parking_event", ["session_id", "occurred_at"])
    op.create_index("ix_parking_event_tenant_type", "parking_event", ["tenant_id", "event_type"])

    op.create_table(
        "parking_audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=True),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(64), nullable=False),
        sa.Column("object_id", sa.String(64), nullable=True),
        sa.Column("details", JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_parking_audit_log_tenant_time", "parking_audit_log", ["tenant_id", "occurred_at"])
    op.create_index("ix_parking_audit_log_object", "parking_audit_log", ["object_type", "object_id"])


def downgrade() -> None:
    op.drop_table("parking_audit_log")
    op.drop_table("parking_event")
    op.drop_table("parking_session")
    op.drop_table("parking_tariff_rule")
    op.drop_table("parking_tariff_plan")
    op.drop_table("parking_vehicle")
    op.drop_table("parking_shift")
    op.drop_table("parking_operator")
    op.drop_table("parking_lane")
    op.drop_table("parking_gate")
    op.drop_table("parking_site")
    op.drop_table("parking_tenant")
