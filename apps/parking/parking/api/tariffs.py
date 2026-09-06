"""Tariff plan/rule admin routes (tenant-scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from parking.api.deps import get_db, get_scope
from parking.api.schemas import TariffPlanCreate, TariffPlanRead, TariffRuleCreate, TariffRuleRead
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.auth import Scope, require_role

router = APIRouter()


@router.post("/sites/{site_id}/tariff-plans", response_model=TariffPlanRead, status_code=201)
def create_tariff_plan(site_id: int, body: TariffPlanCreate, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    plan = TariffPlanRepository(db, scope.tenant_id).create(site_id=site_id, **body.model_dump())
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/sites/{site_id}/tariff-plans", response_model=list[TariffPlanRead])
def list_tariff_plans(site_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return TariffPlanRepository(db, scope.tenant_id).list_for_site(site_id)


@router.get("/tariff-plans/{plan_id}", response_model=TariffPlanRead)
def get_tariff_plan(plan_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return TariffPlanRepository(db, scope.tenant_id).get(plan_id)


@router.post("/tariff-plans/{plan_id}/rules", response_model=TariffRuleRead, status_code=201)
def add_tariff_rule(plan_id: int, body: TariffRuleCreate, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    payload = body.model_dump()
    payload["vehicle_type"] = payload["vehicle_type"].value if hasattr(payload["vehicle_type"], "value") else payload["vehicle_type"]
    rule = TariffPlanRepository(db, scope.tenant_id).add_rule(plan_id=plan_id, **payload)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/tariff-plans/{plan_id}/rules", response_model=list[TariffRuleRead])
def list_tariff_rules(plan_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return TariffPlanRepository(db, scope.tenant_id).all_rules(plan_id)
