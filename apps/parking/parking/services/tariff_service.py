"""Tariff calculation orchestration with frozen snapshots.

Once a session has a stored snapshot, recalculations re-run the engine from
that snapshot (frozen plan version + rule values), so editing the live plan
never silently changes a historical bill. First calculation freezes the
current active plan.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.enums import BASE_TARIFF_TYPES, EventType
from parking.models import ParkingSession
from parking.repositories.session_repo import SessionRepository
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.auth import Scope
from parking.tariff.engine import RuleView, calculate
from parking.tariff.snapshot import build_snapshot, reproduce, to_result


def duration_minutes(entry_at: datetime, calculation_at: datetime) -> int:
    seconds = max(0, (calculation_at - entry_at).total_seconds())
    return math.ceil(seconds / 60)


class TariffService:
    def __init__(self, session, scope: Scope):
        self.session = session
        self.scope = scope

    def calculate(self, parking_session: ParkingSession, calculation_at: datetime | None = None) -> dict:
        at = calculation_at or datetime.now(timezone.utc)
        repo = SessionRepository(self.session, self.scope.tenant_id)

        if parking_session.tariff_snapshot:
            # Frozen snapshot path: reproduce from stored plan/rule values.
            result = reproduce(parking_session.tariff_snapshot, at)
            snapshot = parking_session.tariff_snapshot
            plan_id = snapshot["plan"]["id"]
            plan_version = snapshot["plan"]["version"]
            duration = duration_minutes(parking_session.entry_at, at)
        else:
            plan_repo = TariffPlanRepository(self.session, self.scope.tenant_id)
            plan = plan_repo.get_active_for_site(parking_session.site_id)
            rules = plan_repo.rules_for(plan.id, parking_session.vehicle_type)
            if not any(r.rule_type in BASE_TARIFF_TYPES for r in rules):
                raise ParkingError(
                    ErrorCode.TARIFF_CONFIGURATION_INVALID,
                    f"no base tariff rule configured for vehicle type {parking_session.vehicle_type}",
                    status=400,
                )
            duration = duration_minutes(parking_session.entry_at, at)
            result = calculate(
                vehicle_type=parking_session.vehicle_type,
                duration_minutes=duration,
                grace_period_minutes=plan.grace_period_minutes or 0,
                daily_max_amount=plan.daily_max_amount,
                currency=plan.currency or "IDR",
                rules=[RuleView(r.rule_type, r.config) for r in rules],
            )
            snapshot = build_snapshot(
                plan_id=plan.id,
                plan_code=plan.code,
                plan_name=plan.name,
                plan_version=plan.version,
                site_id=plan.site_id,
                rules=rules,
                vehicle_type=parking_session.vehicle_type,
                entry_at=parking_session.entry_at,
                calculation_at=at,
                duration_minutes=duration,
                grace_period_minutes=plan.grace_period_minutes or 0,
                daily_max_amount=plan.daily_max_amount,
                currency=plan.currency or "IDR",
                result=result,
            )
            plan_id = plan.id
            plan_version = plan.version

        parking_session.calculated_amount = result.amount
        parking_session.tariff_plan_id = plan_id
        parking_session.tariff_version = plan_version
        parking_session.tariff_snapshot = snapshot
        self.session.flush()

        repo.add_event(
            parking_session.tenant_id,
            parking_session.site_id,
            parking_session.id,
            EventType.TARIFF_CALCULATED.value,
            self.scope.actor,
            {"amount": result.amount, "duration_minutes": duration, "plan_version": plan_version},
        )
        return {
            "public_reference": parking_session.public_reference,
            "state": parking_session.state,
            "duration_minutes": duration,
            "amount": result.amount,
            "currency": result.currency,
            "breakdown": [
                {"label": item.label, "amount": item.amount, "detail": item.detail} for item in result.breakdown
            ],
            "plan": {"id": plan_id, "version": plan_version},
            "snapshot": snapshot,
        }
