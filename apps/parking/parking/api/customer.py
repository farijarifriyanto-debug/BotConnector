"""Customer portal routes: session discovery, entitlement check, first-run onboarding,
and safe simulator mode.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select

from parking.api.deps import get_db, get_scope
from parking.domain.errors import ErrorCode, ParkingError
from parking.gate.runtime import GateRuntimeService
from parking.gate.runtime_repo import GateRuntimeRepository, LaneRuntimeRepository
from parking.models import ParkingGate, ParkingLane, ParkingSession, ParkingSite, ParkingTenant
from parking.repositories.session_repo import SessionRepository
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.auth import Scope, require_role
from parking.services.customer_service import CustomerService
from parking.services.entry import EntryService
from parking.services.session_service import SessionService
from parking.services.tariff_service import TariffService

router = APIRouter(prefix="/customer")


@router.get("/me")
def get_customer_me(request: Request, db=Depends(get_db)) -> dict[str, Any]:
    bc_session = request.cookies.get("bc_session")
    return CustomerService.get_context(db, bc_session)


@router.post("/activate")
def activate_product(request: Request) -> dict[str, Any]:
    bc_session = request.cookies.get("bc_session")
    if not bc_session:
        raise ParkingError(ErrorCode.UNAUTHORIZED, "Sesi login diperlukan untuk aktivasi", status=401)
    return CustomerService.activate_product(bc_session)


@router.post("/provision")
def provision_tenant(request: Request, payload: dict[str, Any], db=Depends(get_db)) -> dict[str, Any]:
    bc_session = request.cookies.get("bc_session")
    if not bc_session:
        raise ParkingError(ErrorCode.UNAUTHORIZED, "Sesi login diperlukan untuk pengaturan", status=401)
    return CustomerService.provision(db, bc_session, payload)


@router.post("/update-profile")
def update_profile(
    payload: dict[str, Any],
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> dict[str, Any]:
    require_role(scope, "OWNER")
    prof = str(payload.get("deployment_profile") or "").upper()
    webhook = payload.get("webhook_url")
    return CustomerService.update_profile(db, scope.tenant_id, prof, webhook)


@router.post("/simulate-entry")
def simulate_entry(
    payload: dict[str, Any],
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Safe vehicle entry simulation for testing."""
    plate = str(payload.get("plate") or "B 1234 ABC").strip()
    vtype = str(payload.get("vehicle_type") or "CAR").strip().upper()

    site = db.scalar(
        select(ParkingSite).where(ParkingSite.tenant_id == scope.tenant_id).order_by(ParkingSite.id.asc())
    )
    if not site:
        raise ParkingError(ErrorCode.SITE_NOT_FOUND, "Belum ada Site parkir terkonfigurasi", status=400)

    lane = db.scalar(
        select(ParkingLane).where(
            ParkingLane.tenant_id == scope.tenant_id,
            ParkingLane.site_id == site.id,
            ParkingLane.direction == "ENTRY",
        ).order_by(ParkingLane.id.asc())
    )
    gate_id = lane.gate_id if lane else 1
    lane_id = lane.id if lane else 1

    svc = EntryService(db, scope)
    session = svc.create_entry(
        site_id=site.id,
        gate_id=gate_id,
        lane_id=lane_id,
        plate=plate,
        vehicle_type=vtype,
        source="SIMULASI",
        metadata={"channel": "BROWSER_SIMULATOR"},
    )
    db.commit()
    return {
        "status": "ok",
        "mode": "SIMULASI",
        "session_id": session.id,
        "public_reference": session.public_reference,
        "plate": session.plate_display,
        "vehicle_type": session.vehicle_type,
        "state": session.state,
        "entry_at": session.entry_at.isoformat() if session.entry_at else None,
    }


@router.post("/simulate-exit")
def simulate_exit(
    payload: dict[str, Any],
    scope: Scope = Depends(get_scope),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Safe vehicle exit & payment settlement simulation."""
    public_ref = str(payload.get("public_reference") or "").strip()
    if not public_ref:
        raise ParkingError(ErrorCode.VALIDATION_ERROR, "public_reference is required", status=400)

    sess = db.scalar(
        select(ParkingSession).where(
            ParkingSession.tenant_id == scope.tenant_id,
            ParkingSession.public_reference == public_ref,
        )
    )
    if not sess:
        raise ParkingError(ErrorCode.SESSION_NOT_FOUND, "Parking session not found", status=404)

    site_id = sess.site_id
    from parking.exit.runtime import ExitRuntimeService
    from parking.payment.service import PaymentService

    exit_svc = ExitRuntimeService(db, scope)
    quote_res = exit_svc.create_exit_quote(public_ref)
    total_amount = quote_res.amount

    # If unpaid, settle payment in simulation
    if sess.payment_state != "PAID":
        pay_svc = PaymentService(db, scope)
        idem = f"sim-pay-{sess.id}-{secrets.token_hex(4)}"
        pay_res = pay_svc.create_payment(
            session_reference=public_ref,
            method="CASH",
            idempotency_key=idem,
        )
        pay_svc.confirm_cash(pay_res.payment.public_reference)

    # Authorize exit
    exit_svc.authorize_exit(public_ref)

    exit_lane = db.scalar(
        select(ParkingLane).where(
            ParkingLane.tenant_id == scope.tenant_id,
            ParkingLane.site_id == site_id,
            ParkingLane.direction == "EXIT",
        ).order_by(ParkingLane.id.asc())
    )
    exit_gate_id = exit_lane.gate_id if exit_lane else 2
    exit_lane_id = exit_lane.id if exit_lane else 2

    closed_sess = exit_svc.record_vehicle_exited(
        public_reference=public_ref,
        exit_gate_id=exit_gate_id,
        exit_lane_id=exit_lane_id,
    )
    db.commit()

    return {
        "status": "ok",
        "mode": "SIMULASI",
        "session_id": closed_sess.id,
        "public_reference": closed_sess.public_reference,
        "state": closed_sess.state,
        "payment_state": closed_sess.payment_state,
        "total_amount": total_amount,
        "barrier_intent": "BARRIER_OPEN_INTENT_CREATED",
        "message": "Simulasi keluar berhasil. Palang gerbang menerima sinyal buka.",
    }
