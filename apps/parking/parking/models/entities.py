"""ORM models for BotConnector Parking (M1 foundation).

PostgreSQL is the production engine. JSONB is used for flexible payloads;
enums are stored as VARCHAR with CHECK constraints so migrations stay simple.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from parking.db import Base
from parking.domain.enums import (
    ACTIVE_SESSION_STATES,
    EventType,
    GateDirection,
    GateStatus,
    LaneDirection,
    LaneStatus,
    OperatorRole,
    OperatorStatus,
    PaymentState,
    SessionState,
    ShiftStatus,
    SiteStatus,
    TariffPlanStatus,
    TariffRuleType,
    TenantStatus,
    VehicleType,
)

JsonType = JSON().with_variant(JSONB(), "postgresql")


class ParkingTenant(Base):
    """Top authorization/ownership boundary. One tenant may own many sites."""

    __tablename__ = "parking_tenant"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TenantStatus.ACTIVE.value)
    deployment_profile: Mapped[str] = mapped_column(String(32), nullable=False, default="FULL_STACK")
    webhook_url: Mapped[str | None] = mapped_column(String(512))
    webhook_secret: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("code", name="tenant_code_uniq"),
        CheckConstraint("status IN ('ACTIVE','SUSPENDED')", name="status_allowed"),
        CheckConstraint(
            "deployment_profile IN ('FULL_STACK','EXISTING_HARDWARE','PAYMENT_ONLY')",
            name="ck_parking_tenant_deployment_profile",
        ),
    )


class ParkingSite(Base):
    __tablename__ = "parking_site"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Jakarta")
    address: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="IDR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SiteStatus.ACTIVE.value)
    capacity_total: Mapped[int | None] = mapped_column(Integer)
    capacity_motorcycle: Mapped[int | None] = mapped_column(Integer)
    capacity_car: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="site_tenant_code_uniq"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status_allowed"),
        CheckConstraint("capacity_total IS NULL OR capacity_total >= 0", name="capacity_total_nonneg"),
        CheckConstraint("capacity_motorcycle IS NULL OR capacity_motorcycle >= 0", name="capacity_motorcycle_nonneg"),
        CheckConstraint("capacity_car IS NULL OR capacity_car >= 0", name="capacity_car_nonneg"),
        Index("ix_parking_site_tenant_id", "tenant_id"),
    )


class ParkingGate(Base):
    __tablename__ = "parking_gate"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default=GateDirection.BIDIRECTIONAL.value)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=GateStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "code", name="gate_tenant_site_code_uniq"),
        CheckConstraint("direction IN ('ENTRY','EXIT','BIDIRECTIONAL')", name="direction_allowed"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE','MAINTENANCE')", name="status_allowed"),
        Index("ix_parking_gate_tenant_site", "tenant_id", "site_id"),
    )


class ParkingLane(Base):
    __tablename__ = "parking_lane"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    gate_id: Mapped[int] = mapped_column(ForeignKey("parking_gate.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default=LaneDirection.BIDIRECTIONAL.value)
    vehicle_types: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=LaneStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "gate_id", "code", name="lane_tenant_site_gate_code_uniq"),
        CheckConstraint("direction IN ('ENTRY','EXIT','BIDIRECTIONAL')", name="direction_allowed"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE','MAINTENANCE')", name="status_allowed"),
        Index("ix_parking_lane_tenant_site_gate", "tenant_id", "site_id", "gate_id"),
    )


class ParkingOperator(Base):
    """Operator identity. Bearer tokens authenticate; only the sha256 hash is stored."""

    __tablename__ = "parking_operator"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("parking_site.id"))
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=OperatorRole.OPERATOR.value)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OperatorStatus.ACTIVE.value)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="operator_tenant_username_uniq"),
        CheckConstraint("role IN ('OWNER','ADMIN','MANAGER','SUPERVISOR','OPERATOR','VIEWER')", name="role_allowed"),
        CheckConstraint("status IN ('ACTIVE','DISABLED')", name="status_allowed"),
        Index("ix_parking_operator_tenant", "tenant_id"),
        Index("ix_parking_operator_api_key_hash", "api_key_hash"),
    )


class ParkingShift(Base):
    __tablename__ = "parking_shift"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    operator_id: Mapped[int] = mapped_column(ForeignKey("parking_operator.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ShiftStatus.OPEN.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("status IN ('OPEN','CLOSED')", name="status_allowed"),
        Index("ix_parking_shift_tenant_site", "tenant_id", "site_id"),
    )


class ParkingVehicle(Base):
    """Vehicle registry entry. A vehicle may visit many times; the plate is
    normalized per tenant but never globally unique forever."""

    __tablename__ = "parking_vehicle"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    plate_normalized: Mapped[str] = mapped_column(String(32), nullable=False)
    plate_display: Mapped[str] = mapped_column(String(64), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(20), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "plate_normalized", name="vehicle_tenant_plate_uniq"),
        CheckConstraint("vehicle_type IN ('MOTORCYCLE','CAR','TRUCK','BUS','OTHER')", name="vehicle_type_allowed"),
        Index("ix_parking_vehicle_plate", "plate_normalized"),
    )


class ParkingSession(Base):
    __tablename__ = "parking_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_reference: Mapped[str] = mapped_column(String(40), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("parking_vehicle.id"), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(20), nullable=False)
    plate_normalized: Mapped[str] = mapped_column(String(32), nullable=False)
    plate_display: Mapped[str] = mapped_column(String(64), nullable=False)

    entry_gate_id: Mapped[int] = mapped_column(ForeignKey("parking_gate.id"), nullable=False)
    entry_lane_id: Mapped[int] = mapped_column(ForeignKey("parking_lane.id"), nullable=False)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    exit_gate_id: Mapped[int | None] = mapped_column(ForeignKey("parking_gate.id"))
    exit_lane_id: Mapped[int | None] = mapped_column(ForeignKey("parking_lane.id"))
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    state: Mapped[str] = mapped_column(String(32), nullable=False, default=SessionState.CREATED.value)

    tariff_plan_id: Mapped[int | None] = mapped_column(ForeignKey("parking_tariff_plan.id"))
    tariff_version: Mapped[int | None] = mapped_column(Integer)
    tariff_snapshot: Mapped[dict | None] = mapped_column(JsonType)

    calculated_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payment_state: Mapped[str] = mapped_column(String(20), nullable=False, default=PaymentState.NONE.value)
    lost_ticket: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("public_reference", name="session_public_reference_uniq"),
        CheckConstraint(
            "state IN ('CREATED','ENTERED','PARKED','PAYMENT_PENDING','PAID','EXIT_AUTHORIZED',"
            "'EXITED','CLOSED','CANCELLED','LOST_TICKET','MANUAL_REVIEW')",
            name="state_allowed",
        ),
        CheckConstraint("payment_state IN ('NONE','PENDING','PAID','COMPLIMENTARY')", name="payment_state_allowed"),
        CheckConstraint("calculated_amount >= 0", name="calculated_amount_nonneg"),
        CheckConstraint("paid_amount >= 0", name="paid_amount_nonneg"),
        Index("ix_parking_session_tenant_site_state", "tenant_id", "site_id", "state"),
        Index("ix_parking_session_tenant_site_entry_at", "tenant_id", "site_id", "entry_at"),
        Index("ix_parking_session_tenant_state", "tenant_id", "state"),
        Index("ix_parking_session_tenant_vehicle", "tenant_id", "vehicle_id"),
        # DB-level duplicate active-session guard (concurrency-safe).
        Index(
            "uq_parking_session_active_vehicle",
            "tenant_id",
            "site_id",
            "vehicle_id",
            unique=True,
            postgresql_where=text(
                "state IN ('CREATED','ENTERED','PARKED','PAYMENT_PENDING','LOST_TICKET','MANUAL_REVIEW')"
            ),
        ),
    )


class ParkingEvent(Base):
    """Append-oriented domain event ledger. Never stores credentials."""

    __tablename__ = "parking_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("parking_session.id"))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(120))
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_parking_event_tenant_site_time", "tenant_id", "site_id", "occurred_at"),
        Index("ix_parking_event_session_time", "session_id", "occurred_at"),
        Index("ix_parking_event_tenant_type", "tenant_id", "event_type"),
    )


class ParkingTariffPlan(Base):
    __tablename__ = "parking_tariff_plan"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TariffPlanStatus.ACTIVE.value)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    grace_period_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_max_amount: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="IDR")
    timezone: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "code", name="plan_tenant_site_code_uniq"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status_allowed"),
        CheckConstraint("grace_period_minutes >= 0", name="grace_nonneg"),
        CheckConstraint("daily_max_amount IS NULL OR daily_max_amount >= 0", name="daily_max_nonneg"),
        Index("ix_parking_tariff_plan_tenant_site_status", "tenant_id", "site_id", "status"),
    )


class ParkingTariffRule(Base):
    __tablename__ = "parking_tariff_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("parking_tariff_plan.id"), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    precedence: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    config: Mapped[dict] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("plan_id", "vehicle_type", "rule_type", name="rule_plan_vehicle_type_uniq"),
        CheckConstraint("rule_type IN ('FLAT','HOURLY','PROGRESSIVE','LOST_TICKET_FEE')", name="rule_type_allowed"),
        CheckConstraint("vehicle_type IN ('MOTORCYCLE','CAR','TRUCK','BUS','OTHER')", name="vehicle_type_allowed"),
        Index("ix_parking_tariff_rule_plan", "plan_id"),
        Index("ix_parking_tariff_rule_tenant_site", "tenant_id", "site_id"),
    )


class ParkingAuditLog(Base):
    """Audit trail for important manual/operator actions (distinct from debug logs)."""

    __tablename__ = "parking_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("parking_site.id"))
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_parking_audit_log_tenant_time", "tenant_id", "occurred_at"),
        Index("ix_parking_audit_log_object", "object_type", "object_id"),
    )


class ParkingGateRuntime(Base):
    """M4: explicit operational state for a gate, separate from configuration
    status. Tracks last-seen and state-change timestamps."""

    __tablename__ = "parking_gate_runtime"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    gate_id: Mapped[int] = mapped_column(ForeignKey("parking_gate.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="ONLINE")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "gate_id", name="gate_runtime_tenant_site_gate_uniq"),
        CheckConstraint("state IN ('ONLINE','OFFLINE','MAINTENANCE','BLOCKED')", name="state_allowed"),
        Index("ix_parking_gate_runtime_tenant_site", "tenant_id", "site_id"),
    )


class ParkingLaneRuntime(Base):
    """M4: explicit operational state for a lane."""

    __tablename__ = "parking_lane_runtime"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    lane_id: Mapped[int] = mapped_column(ForeignKey("parking_lane.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="ONLINE")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "lane_id", name="lane_runtime_tenant_site_lane_uniq"),
        CheckConstraint("state IN ('ONLINE','OFFLINE','MAINTENANCE','BLOCKED')", name="state_allowed"),
        Index("ix_parking_lane_runtime_tenant_site", "tenant_id", "site_id"),
    )


class ParkingIdempotencyRecord(Base):
    """M4: request-level idempotency. Same key + same semantic request returns
    the stored result; same key + conflicting request is rejected."""

    __tablename__ = "parking_idempotency_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="idempotency_tenant_key_uniq"),
        Index("ix_parking_idempotency_tenant_op", "tenant_id", "operation"),
    )


class ParkingExitQuote(Base):
    """M5: authoritative server-side tariff quote for an exit. Amount is always
    derived from the tariff engine, never from the client."""

    __tablename__ = "parking_exit_quote"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_reference: Mapped[str] = mapped_column(String(40), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    session_id: Mapped[int] = mapped_column(ForeignKey("parking_session.id"), nullable=False)
    tariff_version: Mapped[int | None] = mapped_column(Integer)
    tariff_snapshot: Mapped[dict | None] = mapped_column(JsonType)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="IDR")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("public_reference", name="exit_quote_public_reference_uniq"),
        CheckConstraint("amount >= 0", name="amount_nonneg"),
        CheckConstraint("status IN ('ACTIVE','EXPIRED','SUPERSEDED','PAID','CANCELLED')", name="status_allowed"),
        Index("ix_parking_exit_quote_tenant_site", "tenant_id", "site_id"),
        Index("ix_parking_exit_quote_session", "session_id"),
    )


class ParkingPayment(Base):
    """M6: provider-neutral payment. Amount authority comes from exit quote or merchant order."""

    __tablename__ = "parking_payment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_reference: Mapped[str] = mapped_column(String(40), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("parking_site.id"), nullable=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("parking_session.id"), nullable=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("parking_exit_quote.id"), nullable=True)
    merchant_order_ref: Mapped[str | None] = mapped_column(String(128))
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    expected_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="IDR")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    provider_reference: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
    webhook_status: Mapped[str | None] = mapped_column(String(32))
    webhook_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("public_reference", name="payment_public_reference_uniq"),
        UniqueConstraint("tenant_id", "idempotency_key", name="payment_tenant_idempotency_uniq"),
        CheckConstraint("expected_amount >= 0", name="expected_amount_nonneg"),
        CheckConstraint(
            "state IN ('CREATED','PENDING','PAID','FAILED','EXPIRED','CANCELLED','REFUNDED')",
            name="state_allowed",
        ),
        CheckConstraint(
            "method IN ('CASH','QRIS_MPM_DYNAMIC','QRIS_CPM','COMPLIMENTARY','MEMBERSHIP','GATEWAY_QRIS','SIMULATOR')",
            name="ck_parking_payment_method_allowed",
        ),
        Index("ix_parking_payment_tenant_site", "tenant_id", "site_id"),
        Index("ix_parking_payment_session", "session_id"),
        Index("ix_parking_payment_quote", "quote_id"),
        Index("ix_parking_payment_merchant_ref", "tenant_id", "merchant_order_ref"),
    )


class ParkingPaymentAttempt(Base):
    """M6: one logical attempt against a provider for a payment."""

    __tablename__ = "parking_payment_attempt"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    payment_id: Mapped[int] = mapped_column(ForeignKey("parking_payment.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("state IN ('CREATED','PENDING','SUCCEEDED','FAILED','EXPIRED')", name="state_allowed"),
        Index("ix_parking_payment_attempt_payment", "payment_id"),
        Index("ix_parking_payment_attempt_tenant", "tenant_id"),
    )


class ParkingPaymentEvent(Base):
    """M6: append-only payment event ledger. Never stores credentials/secrets."""

    __tablename__ = "parking_payment_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    payment_id: Mapped[int] = mapped_column(ForeignKey("parking_payment.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(120))
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_parking_payment_event_payment_time", "payment_id", "occurred_at"),
        Index("ix_parking_payment_event_tenant_time", "tenant_id", "occurred_at"),
    )


class ParkingDevice(Base):
    """M8: generic Parking device registry. Credentials are never stored inline;
    only a secret reference is kept."""

    __tablename__ = "parking_device"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    gate_id: Mapped[int | None] = mapped_column(ForeignKey("parking_gate.id"))
    lane_id: Mapped[int | None] = mapped_column(ForeignKey("parking_lane.id"))
    device_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    configuration_reference: Mapped[str | None] = mapped_column(String(128))
    credential_reference: Mapped[str | None] = mapped_column(String(128))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "device_id", name="device_tenant_id_uniq"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE','MAINTENANCE')", name="status_allowed"),
        CheckConstraint(
            "device_type IN ('ANPR_CAMERA','BARRIER_CONTROLLER','LOOP_SENSOR','QR_SCANNER','DISPLAY','EDGE_GATEWAY','OTHER')",
            name="device_type_allowed",
        ),
        Index("ix_parking_device_tenant_site", "tenant_id", "site_id"),
    )


class ParkingDeviceRuntime(Base):
    """M8: runtime/health state for a device, distinct from configuration status."""

    __tablename__ = "parking_device_runtime"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    device_id: Mapped[int] = mapped_column(ForeignKey("parking_device.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "device_id", name="device_runtime_tenant_site_device_uniq"),
        CheckConstraint("state IN ('ONLINE','OFFLINE','DEGRADED','MAINTENANCE','UNKNOWN')", name="state_allowed"),
        Index("ix_parking_device_runtime_tenant_site", "tenant_id", "site_id"),
    )


class ParkingBarrierCommand(Base):
    """M8: explicit, auditable barrier command. Only approved commands via adapter."""

    __tablename__ = "parking_barrier_command"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    command_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    lane_id: Mapped[int | None] = mapped_column(ForeignKey("parking_lane.id"))
    device_id: Mapped[int] = mapped_column(ForeignKey("parking_device.id"), nullable=False)
    command_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "command_id", name="barrier_command_tenant_id_uniq"),
        UniqueConstraint("tenant_id", "idempotency_key", name="barrier_command_tenant_idempotency_uniq"),
        CheckConstraint("command_type IN ('OPEN','CLOSE','STATUS')", name="command_type_allowed"),
        CheckConstraint("status IN ('CREATED','DISPATCHED','ACKNOWLEDGED','FAILED','EXPIRED')", name="status_allowed"),
        Index("ix_parking_barrier_command_tenant_site", "tenant_id", "site_id"),
        Index("ix_parking_barrier_command_device", "device_id"),
    )


class ParkingAnprEvent(Base):
    """M7: normalized ANPR recognition event. No image blobs; only references."""

    __tablename__ = "parking_anpr_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    gate_id: Mapped[int | None] = mapped_column(ForeignKey("parking_gate.id"))
    lane_id: Mapped[int | None] = mapped_column(ForeignKey("parking_lane.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("parking_device.id"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    plate_raw: Mapped[str] = mapped_column(String(64), nullable=False)
    plate_normalized: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    vehicle_type_guess: Mapped[str | None] = mapped_column(String(20))
    direction: Mapped[str | None] = mapped_column(String(20))
    image_reference: Mapped[str | None] = mapped_column(String(128))
    crop_reference: Mapped[str | None] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="RECEIVED")
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", name="anpr_event_tenant_id_uniq"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("state IN ('RECEIVED','PROCESSED','DUPLICATE','REJECTED','MANUAL_REVIEW','CORRECTED')", name="state_allowed"),
        Index("ix_parking_anpr_event_tenant_site", "tenant_id", "site_id"),
        Index("ix_parking_anpr_event_tenant_provider", "tenant_id", "provider_event_id"),
    )


class ParkingAnprCorrection(Base):
    """M7: audited manual plate correction. Never silently overwrites evidence."""

    __tablename__ = "parking_anpr_correction"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    anpr_event_id: Mapped[int] = mapped_column(ForeignKey("parking_anpr_event.id"), nullable=False)
    original_plate: Mapped[str] = mapped_column(String(32), nullable=False)
    corrected_plate: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_parking_anpr_correction_tenant", "tenant_id"),
        Index("ix_parking_anpr_correction_event", "anpr_event_id"),
    )


class ParkingEdge(Base):
    """M9: Edge Gateway registry. Credentials are referenced, never stored inline."""

    __tablename__ = "parking_edge"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    edge_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    credential_reference: Mapped[str | None] = mapped_column(String(128))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "edge_id", name="edge_tenant_id_uniq"),
        Index("ix_parking_edge_tenant_site", "tenant_id", "site_id"),
    )


class ParkingEdgeSyncEvent(Base):
    """M9: central-side record of an edge-synced event (idempotency by event_id)."""

    __tablename__ = "parking_edge_sync_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    edge_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("parking_tenant.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("parking_site.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    sync_state: Mapped[str] = mapped_column(String(20), nullable=False, default="SYNCED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", name="edge_sync_event_tenant_event_uniq"),
        Index("ix_parking_edge_sync_event_edge_seq", "edge_id", "sequence_number"),
        Index("ix_parking_edge_sync_event_tenant_site", "tenant_id", "site_id"),
    )
