"""Pydantic request/response schemas for the Parking API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from parking.domain.enums import (
    GateDirection,
    GateStatus,
    LaneStatus,
    OperatorRole,
    PaymentState,
    SessionState,
    SiteStatus,
    TariffPlanStatus,
    VehicleType,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CreateModel(BaseModel):
    """Create payloads: enum fields are stored as their plain values so
    model_dump() can be passed straight into repositories/DB columns."""

    model_config = ConfigDict(use_enum_values=True)


# ---- admin: sites / gates / lanes / operators ------------------------------
class SiteCreate(CreateModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    timezone: str = "Asia/Jakarta"
    address: str | None = None
    description: str | None = None
    currency: str = "IDR"


class SiteRead(ORMModel):
    id: int
    tenant_id: int
    code: str
    name: str
    timezone: str
    address: str | None = None
    description: str | None = None
    currency: str
    status: str
    created_at: datetime
    updated_at: datetime


class GateCreate(CreateModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    direction: GateDirection
    status: GateStatus = GateStatus.ACTIVE


class GateRead(ORMModel):
    id: int
    tenant_id: int
    site_id: int
    code: str
    name: str
    direction: str
    status: str
    created_at: datetime
    updated_at: datetime


class LaneCreate(CreateModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    gate_id: int
    direction: Literal["ENTRY", "EXIT", "BIDIRECTIONAL"] = "BIDIRECTIONAL"
    vehicle_types: list[VehicleType] = Field(default_factory=lambda: [VehicleType.MOTORCYCLE, VehicleType.CAR])
    status: LaneStatus = LaneStatus.ACTIVE


class LaneRead(ORMModel):
    id: int
    tenant_id: int
    site_id: int
    gate_id: int
    code: str
    name: str
    direction: str
    vehicle_types: list[str]
    status: str
    created_at: datetime
    updated_at: datetime


class OperatorCreate(CreateModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    role: OperatorRole = OperatorRole.OPERATOR


class OperatorRead(ORMModel):
    id: int
    tenant_id: int
    site_id: int | None
    username: str
    display_name: str
    role: str
    status: str
    api_token: str | None = None  # returned once at creation only
    created_at: datetime
    updated_at: datetime


# ---- sessions ---------------------------------------------------------------
class EntryRequest(CreateModel):
    site_id: int
    gate_id: int
    lane_id: int
    plate: str = Field(min_length=1, max_length=32)
    vehicle_type: VehicleType
    entry_at: datetime | None = None  # server-trusted override (simulator/testing)
    source: str | None = "SIMULATED_ANPR"
    metadata: dict | None = None


class EntryResponse(BaseModel):
    public_reference: str
    state: str
    site_id: int
    vehicle_type: str
    plate_normalized: str
    plate_display: str
    entry_at: datetime


class SessionRead(ORMModel):
    id: int
    public_reference: str
    tenant_id: int
    site_id: int
    vehicle_id: int
    vehicle_type: str
    plate_normalized: str
    plate_display: str
    entry_gate_id: int
    entry_lane_id: int
    entry_at: datetime
    exit_gate_id: int | None
    exit_lane_id: int | None
    exit_at: datetime | None
    state: str
    tariff_plan_id: int | None
    tariff_version: int | None
    calculated_amount: int
    paid_amount: int
    payment_state: str
    lost_ticket: bool
    source: str | None
    created_at: datetime
    updated_at: datetime


class CalculateResponse(BaseModel):
    public_reference: str
    state: str
    duration_minutes: int
    amount: int
    currency: str
    breakdown: list[dict]
    plan: dict | None = None


class LostTicketRequest(BaseModel):
    reason: str | None = None


class ComplimentaryRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class CancelRequest(BaseModel):
    reason: str | None = None


class ExitRequest(BaseModel):
    exit_gate_id: int
    exit_lane_id: int
    exit_at: datetime | None = None


class CommandResponse(BaseModel):
    public_reference: str
    state: str
    payment_state: str
    calculated_amount: int
    paid_amount: int
    lost_ticket: bool


class EventRead(ORMModel):
    id: int
    tenant_id: int
    site_id: int
    session_id: int | None
    event_type: str
    occurred_at: datetime
    actor: str | None
    metadata: dict = Field(validation_alias="metadata_")


# ---- tariffs ----------------------------------------------------------------
class TariffPlanCreate(CreateModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    grace_period_minutes: int = Field(0, ge=0)
    daily_max_amount: int | None = Field(None, ge=0)
    currency: str = "IDR"
    status: TariffPlanStatus = TariffPlanStatus.ACTIVE
    timezone: str | None = None


class TariffPlanRead(ORMModel):
    id: int
    tenant_id: int
    site_id: int
    code: str
    name: str
    status: str
    version: int
    grace_period_minutes: int
    daily_max_amount: int | None
    currency: str
    timezone: str | None
    created_at: datetime
    updated_at: datetime


class TariffRuleCreate(CreateModel):
    vehicle_type: VehicleType
    rule_type: Literal["FLAT", "HOURLY", "PROGRESSIVE", "LOST_TICKET_FEE"]
    config: dict
    precedence: int = 10


class TariffRuleRead(ORMModel):
    id: int
    tenant_id: int
    site_id: int
    plan_id: int
    vehicle_type: str
    rule_type: str
    precedence: int
    config: dict
    created_at: datetime
    updated_at: datetime
