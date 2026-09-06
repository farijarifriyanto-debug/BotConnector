"""API endpoints for PAYMENT_ONLY deployment profile and merchant payment gateway."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select

from parking.api.deps import get_db, get_scope
from parking.domain.errors import ErrorCode, ParkingError
from parking.models import ParkingTenant
from parking.payment.gateway import PaymentGatewayService
from parking.services.auth import Scope

router = APIRouter(prefix="/payment-gateway")


@router.post("/orders")
def create_order(
    payload: dict[str, Any],
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> dict[str, Any]:
    svc = PaymentGatewayService(db, scope)
    return svc.create_order(payload)


@router.get("/orders/{payment_reference}")
def get_order(
    payment_reference: str,
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> dict[str, Any]:
    svc = PaymentGatewayService(db, scope)
    return svc.get_order(payment_reference)


@router.post("/orders/{payment_reference}/simulate-pay")
def simulate_settle(
    payment_reference: str,
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> dict[str, Any]:
    svc = PaymentGatewayService(db, scope)
    return svc.simulate_settle(payment_reference)


@router.get("/transactions")
def list_transactions(
    limit: int = 50,
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> list[dict[str, Any]]:
    svc = PaymentGatewayService(db, scope)
    return svc.list_transactions(limit=limit)


@router.get("/reconciliation")
def reconcile(
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> dict[str, Any]:
    svc = PaymentGatewayService(db, scope)
    return svc.reconcile()


@router.get("/settings")
def get_settings(
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> dict[str, Any]:
    tenant = db.scalar(select(ParkingTenant).where(ParkingTenant.id == scope.tenant_id))
    if not tenant:
        raise ParkingError(ErrorCode.TENANT_NOT_FOUND, "Tenant not found", status=404)
    return {
        "tenant_id": tenant.id,
        "tenant_code": tenant.code,
        "deployment_profile": tenant.deployment_profile,
        "webhook_url": tenant.webhook_url,
        "webhook_secret": tenant.webhook_secret,
    }


@router.post("/settings")
def update_settings(
    payload: dict[str, Any],
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> dict[str, Any]:
    tenant = db.scalar(select(ParkingTenant).where(ParkingTenant.id == scope.tenant_id))
    if not tenant:
        raise ParkingError(ErrorCode.TENANT_NOT_FOUND, "Tenant not found", status=404)

    if "webhook_url" in payload:
        tenant.webhook_url = str(payload.get("webhook_url") or "").strip() or None
    if "deployment_profile" in payload:
        prof = str(payload.get("deployment_profile") or "").upper()
        if prof in ("FULL_STACK", "EXISTING_HARDWARE", "PAYMENT_ONLY"):
            tenant.deployment_profile = prof
    db.commit()
    return {
        "status": "ok",
        "tenant_id": tenant.id,
        "deployment_profile": tenant.deployment_profile,
        "webhook_url": tenant.webhook_url,
    }
