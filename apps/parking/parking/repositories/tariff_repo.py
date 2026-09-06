"""Tariff plan/rule repositories (tenant-scoped). Editing a rule bumps the plan
version so historical sessions keep a stable snapshot."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.enums import BASE_TARIFF_TYPES, TariffPlanStatus, TariffRuleType
from parking.models import ParkingTariffPlan, ParkingTariffRule
from parking.repositories.base import ScopedRepository
from parking.repositories.registry import SiteRepository
from parking.tariff.config import validate_config


class TariffPlanRepository(ScopedRepository):
    def create(
        self,
        *,
        site_id: int,
        code: str,
        name: str,
        grace_period_minutes: int = 0,
        daily_max_amount: int | None = None,
        currency: str = "IDR",
        timezone: str | None = None,
    ) -> ParkingTariffPlan:
        SiteRepository(self.session, self.tenant_id).get(site_id)
        plan = ParkingTariffPlan(
            tenant_id=self.tenant_id,
            site_id=site_id,
            code=code,
            name=name,
            grace_period_minutes=grace_period_minutes,
            daily_max_amount=daily_max_amount,
            currency=currency,
            timezone=timezone,
            version=1,
        )
        self.session.add(plan)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(
                    ErrorCode.RESOURCE_ALREADY_EXISTS, f"tariff plan {code} already exists for this site", status=409
                )
            raise
        return plan

    def get(self, plan_id: int) -> ParkingTariffPlan:
        plan = self.session.scalar(
            select(ParkingTariffPlan).where(
                ParkingTariffPlan.id == plan_id, ParkingTariffPlan.tenant_id == self.tenant_id
            )
        )
        if plan is None:
            raise ParkingError(ErrorCode.TARIFF_PLAN_NOT_FOUND, "tariff plan not found", status=404)
        return plan

    def list_for_site(self, site_id: int) -> list[ParkingTariffPlan]:
        return list(
            self.session.scalars(
                select(ParkingTariffPlan)
                .where(ParkingTariffPlan.tenant_id == self.tenant_id, ParkingTariffPlan.site_id == site_id)
                .order_by(ParkingTariffPlan.id)
            )
        )

    def get_active_for_site(self, site_id: int) -> ParkingTariffPlan:
        plan = self.session.scalar(
            select(ParkingTariffPlan)
            .where(
                ParkingTariffPlan.tenant_id == self.tenant_id,
                ParkingTariffPlan.site_id == site_id,
                ParkingTariffPlan.status == TariffPlanStatus.ACTIVE.value,
            )
            .order_by(ParkingTariffPlan.version.desc())
            .limit(1)
        )
        if plan is None:
            raise ParkingError(ErrorCode.TARIFF_PLAN_NOT_FOUND, "no active tariff plan for this site", status=404)
        return plan

    def add_rule(
        self,
        *,
        plan_id: int,
        vehicle_type: str,
        rule_type: str,
        config: dict,
        precedence: int = 10,
    ) -> ParkingTariffRule:
        plan = self.get(plan_id)
        canonical = validate_config(rule_type, config)
        if rule_type in BASE_TARIFF_TYPES:
            existing = self.rules_for(plan_id, vehicle_type)
            if any(r.rule_type in BASE_TARIFF_TYPES for r in existing):
                raise ParkingError(
                    ErrorCode.TARIFF_CONFIGURATION_INVALID,
                    f"a base tariff rule already exists for vehicle type {vehicle_type}",
                    status=400,
                )
        rule = ParkingTariffRule(
            tenant_id=self.tenant_id,
            site_id=plan.site_id,
            plan_id=plan_id,
            vehicle_type=vehicle_type,
            rule_type=rule_type,
            precedence=precedence,
            config=canonical,
        )
        self.session.add(rule)
        try:
            self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ParkingError(
                    ErrorCode.RESOURCE_ALREADY_EXISTS,
                    f"a {rule_type} rule already exists for vehicle type {vehicle_type}",
                    status=409,
                )
            raise
        # Adding rules is part of initial plan setup and does not bump the
        # version; only editing an existing rule (update_rule) increments it so
        # historical sessions keep a stable snapshot.
        return rule

    def update_rule(self, *, plan_id: int, vehicle_type: str, rule_type: str, config: dict) -> ParkingTariffRule:
        """Edit an existing rule's config; bumps the plan version so historical
        sessions keep their frozen snapshot."""
        plan = self.get(plan_id)
        canonical = validate_config(rule_type, config)
        rule = self.session.scalar(
            select(ParkingTariffRule).where(
                ParkingTariffRule.plan_id == plan_id,
                ParkingTariffRule.vehicle_type == vehicle_type,
                ParkingTariffRule.rule_type == rule_type,
            )
        )
        if rule is None:
            raise ParkingError(
                ErrorCode.TARIFF_CONFIGURATION_INVALID,
                f"no {rule_type} rule for vehicle type {vehicle_type} on this plan",
                status=404,
            )
        rule.config = canonical
        self.session.flush()
        self.bump_version(plan)
        return rule

    def rules_for(self, plan_id: int, vehicle_type: str) -> list[ParkingTariffRule]:
        return list(
            self.session.scalars(
                select(ParkingTariffRule)
                .where(
                    ParkingTariffRule.plan_id == plan_id,
                    ParkingTariffRule.vehicle_type == vehicle_type,
                )
                .order_by(ParkingTariffRule.precedence, ParkingTariffRule.id)
            )
        )

    def all_rules(self, plan_id: int) -> list[ParkingTariffRule]:
        return list(
            self.session.scalars(
                select(ParkingTariffRule)
                .where(ParkingTariffRule.plan_id == plan_id)
                .order_by(ParkingTariffRule.precedence, ParkingTariffRule.id)
            )
        )

    def bump_version(self, plan: ParkingTariffPlan) -> ParkingTariffPlan:
        plan.version = (plan.version or 1) + 1
        self.session.flush()
        return plan
