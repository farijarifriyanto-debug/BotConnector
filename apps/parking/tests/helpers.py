"""Shared test helpers (domain-level fixtures)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from parking.repositories.registry import (
    GateRepository,
    LaneRepository,
    OperatorRepository,
    SiteRepository,
    TenantRepository,
)
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.auth import Scope, hash_api_key


def new_tenant(session, code: str = "T1", name: str = "Tenant 1"):
    return TenantRepository(session).create(code=code, name=name)


def new_site(session, tenant, code: str = "S1", name: str = "Site 1"):
    return SiteRepository(session, tenant.id).create(code=code, name=name)


def new_gate(session, tenant, site, code: str = "G1", direction: str = "ENTRY"):
    return GateRepository(session, tenant.id).create(site_id=site.id, code=code, name=code, direction=direction)


def new_lane(
    session,
    tenant,
    site,
    gate,
    code: str = "L1",
    direction: str = "ENTRY",
    vehicle_types=("MOTORCYCLE", "CAR"),
):
    return LaneRepository(session, tenant.id).create(
        site_id=site.id,
        gate_id=gate.id,
        code=code,
        name=code,
        direction=direction,
        vehicle_types=list(vehicle_types),
    )


def new_operator(session, tenant, username: str = "op1", token: str = "test-token-1", role: str = "OPERATOR"):
    return OperatorRepository(session, tenant.id).create(
        username=username, display_name=username, api_key_hash=hash_api_key(token), role=role
    )


def scope(tenant, actor: str = "operator:test") -> Scope:
    return Scope(tenant_id=tenant.id, actor=actor)


def new_flat_plan(
    session,
    tenant,
    site,
    *,
    vehicle_type: str = "CAR",
    amount: int = 5000,
    grace: int = 0,
    daily_max: int | None = None,
    code: str = "PLAN-A",
):
    repo = TariffPlanRepository(session, tenant.id)
    plan = repo.create(
        site_id=site.id,
        code=code,
        name=code,
        grace_period_minutes=grace,
        daily_max_amount=daily_max,
    )
    repo.add_rule(plan_id=plan.id, vehicle_type=vehicle_type, rule_type="FLAT", config={"amount": amount})
    return plan


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hours_ago(hours: float) -> datetime:
    # Return a time slightly LESS than `hours` in the past so the elapsed time
    # between entry and a later `calculate()` call stays just under the whole
    # minute boundary, keeping ceil-based duration assertions deterministic
    # (no off-by-one flakiness).
    return utcnow() - timedelta(hours=hours) + timedelta(seconds=30)
