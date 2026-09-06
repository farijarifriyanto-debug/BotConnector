"""BotConnector Parking M7-M9 — device registry, ANPR events, barrier commands,
edge registry and sync events.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- M8: device registry + runtime + barrier commands --------------------
    op.create_table(
        "parking_device",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("gate_id", sa.BigInteger(), sa.ForeignKey("parking_gate.id"), nullable=True),
        sa.Column("lane_id", sa.BigInteger(), sa.ForeignKey("parking_lane.id"), nullable=True),
        sa.Column("device_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("adapter_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration_reference", sa.String(128), nullable=True),
        sa.Column("credential_reference", sa.String(128), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "device_id", name="device_tenant_id_uniq"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE','MAINTENANCE')", name="ck_parking_device_status_allowed"),
        sa.CheckConstraint("device_type IN ('ANPR_CAMERA','BARRIER_CONTROLLER','LOOP_SENSOR','QR_SCANNER','DISPLAY','EDGE_GATEWAY','OTHER')", name="ck_parking_device_device_type_allowed"),
    )
    op.create_index("ix_parking_device_tenant_site", "parking_device", ["tenant_id", "site_id"])

    op.create_table(
        "parking_device_runtime",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("device_id", sa.BigInteger(), sa.ForeignKey("parking_device.id"), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "device_id", name="device_runtime_tenant_site_device_uniq"),
        sa.CheckConstraint("state IN ('ONLINE','OFFLINE','DEGRADED','MAINTENANCE','UNKNOWN')", name="ck_parking_device_runtime_state_allowed"),
    )
    op.create_index("ix_parking_device_runtime_tenant_site", "parking_device_runtime", ["tenant_id", "site_id"])

    op.create_table(
        "parking_barrier_command",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("command_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("lane_id", sa.BigInteger(), sa.ForeignKey("parking_lane.id"), nullable=True),
        sa.Column("device_id", sa.BigInteger(), sa.ForeignKey("parking_device.id"), nullable=False),
        sa.Column("command_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_by", sa.String(120), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "command_id", name="barrier_command_tenant_id_uniq"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="barrier_command_tenant_idempotency_uniq"),
        sa.CheckConstraint("command_type IN ('OPEN','CLOSE','STATUS')", name="ck_parking_barrier_command_command_type_allowed"),
        sa.CheckConstraint("status IN ('CREATED','DISPATCHED','ACKNOWLEDGED','FAILED','EXPIRED')", name="ck_parking_barrier_command_status_allowed"),
    )
    op.create_index("ix_parking_barrier_command_tenant_site", "parking_barrier_command", ["tenant_id", "site_id"])
    op.create_index("ix_parking_barrier_command_device", "parking_barrier_command", ["device_id"])

    # ---- M7: ANPR events + corrections --------------------------------------
    op.create_table(
        "parking_anpr_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("gate_id", sa.BigInteger(), sa.ForeignKey("parking_gate.id"), nullable=True),
        sa.Column("lane_id", sa.BigInteger(), sa.ForeignKey("parking_lane.id"), nullable=True),
        sa.Column("device_id", sa.BigInteger(), sa.ForeignKey("parking_device.id"), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("plate_raw", sa.String(64), nullable=False),
        sa.Column("plate_normalized", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("vehicle_type_guess", sa.String(20), nullable=True),
        sa.Column("direction", sa.String(20), nullable=True),
        sa.Column("image_reference", sa.String(128), nullable=True),
        sa.Column("crop_reference", sa.String(128), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_event_id", sa.String(64), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "event_id", name="anpr_event_tenant_id_uniq"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_parking_anpr_event_confidence_range"),
        sa.CheckConstraint("state IN ('RECEIVED','PROCESSED','DUPLICATE','REJECTED','MANUAL_REVIEW','CORRECTED')", name="ck_parking_anpr_event_state_allowed"),
    )
    op.create_index("ix_parking_anpr_event_tenant_site", "parking_anpr_event", ["tenant_id", "site_id"])
    op.create_index("ix_parking_anpr_event_tenant_provider", "parking_anpr_event", ["tenant_id", "provider_event_id"])

    op.create_table(
        "parking_anpr_correction",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("anpr_event_id", sa.BigInteger(), sa.ForeignKey("parking_anpr_event.id"), nullable=False),
        sa.Column("original_plate", sa.String(32), nullable=False),
        sa.Column("corrected_plate", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_parking_anpr_correction_tenant", "parking_anpr_correction", ["tenant_id"])
    op.create_index("ix_parking_anpr_correction_event", "parking_anpr_correction", ["anpr_event_id"])

    # ---- M9: edge registry + sync events ------------------------------------
    op.create_table(
        "parking_edge",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("edge_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("credential_reference", sa.String(128), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "edge_id", name="edge_tenant_id_uniq"),
    )
    op.create_index("ix_parking_edge_tenant_site", "parking_edge", ["tenant_id", "site_id"])

    op.create_table(
        "parking_edge_sync_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("edge_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("parking_tenant.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("parking_site.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("sync_state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "event_id", name="edge_sync_event_tenant_event_uniq"),
    )
    op.create_index("ix_parking_edge_sync_event_edge_seq", "parking_edge_sync_event", ["edge_id", "sequence_number"])
    op.create_index("ix_parking_edge_sync_event_tenant_site", "parking_edge_sync_event", ["tenant_id", "site_id"])


def downgrade() -> None:
    op.drop_table("parking_edge_sync_event")
    op.drop_table("parking_edge")
    op.drop_table("parking_anpr_correction")
    op.drop_table("parking_anpr_event")
    op.drop_table("parking_barrier_command")
    op.drop_table("parking_device_runtime")
    op.drop_table("parking_device")
